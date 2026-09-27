# -*- coding: utf-8 -*-
"""S9：输出目录层级 —— **分类在外、项目在内**（v3.9.0）

人类原话：「out 下面是输出的常驻的根目录，比如 01WAV、02、03AAF，
项目打包要在这里面。」

目标形状：
```
out/
 ├─ 01-多条WAV/<项目>/…
 ├─ 02-素材片段/<项目>[/模板N]/…
 └─ 03-AAF/<项目>/…
```

两条腿：
  ① 静态：源码里 6 处落点必须写成 `out/分类/项目`，**反向写法绝迹**
    （这条腿不依赖剪映草稿 / ffmpeg，任何机器都能跑，是最硬的回归护栏）
  ② 端到端：有真实草稿时跑一次片段导出，断言产物树形状（无草稿则 SKIP）

跑法：python tests/test_outdir_layout.py
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402
C.ensure_tk()

JY = C.SRC / "jianying-draft-toolkit" / "code"
MAIN = JY / "main.py"
EXPORT_TAB = JY / "tabs" / "export_tab.py"
MENUS = JY / "core" / "menus.py"

# ① 静态：必须出现的「分类在外」写法
MUST_HAVE = [
    'output_root / "01-多条WAV" / draft_dir.name',
    'output_root / "01-多条WAV" / folder',
    'output_root / "03-AAF" / folder',
    'output_root / "03-AAF" / draft_dir.name',
    '[base_out, "02-素材片段", chunk_dir or draft_dir.name]',
]
# ① 静态：必须绝迹的「项目在外」写法（v2.6.1 老结构）
MUST_NOT = [
    r'draft_dir\.name\s*/\s*"01-多条WAV"',
    r'folder\s*/\s*"01-多条WAV"',
    r'draft_dir\.name\s*/\s*"03-AAF"',
    r'folder\s*/\s*"03-AAF"',
    r'\[base_out,\s*(?:chunk_dir|draft_dir\.name)[^\]]*"02-素材片段"',
]


def _static_source():
    s = MAIN.read_text(encoding="utf-8")
    miss = [m for m in MUST_HAVE if m not in s]
    assert not miss, "源码里缺新结构写法（分类在外）：%s" % miss
    hit = [p for p in MUST_NOT if re.search(p, s)]
    assert not hit, "源码里仍存在旧结构写法（项目在外）：%s" % hit
    return "源码 6 处落点：分类在外 ✓ / 反向写法 0 处 ✓"


def _static_doc():
    """界面文案也要跟着翻，否则人照着提示去找目录会找错。"""
    for p in (EXPORT_TAB, MENUS):
        s = p.read_text(encoding="utf-8")
        bad = re.search(r'<草稿名>\s*/\s*<集名>\s*/\s*(?:01-多条WAV|02-素材片段|03-AAF)', s)
        assert not bad, "文案仍写旧结构：%s -> %s" % (p.name, bad.group(0))
    s = EXPORT_TAB.read_text(encoding="utf-8")
    assert "01-多条WAV/<草稿名|集名>/" in s, "导出页未更新为新结构说明"
    return "导出页 / 路径设置文案已同步 ✓"


def _pick_draft():
    """挑一个真实草稿（没有就跳过）。"""
    root = C.DRAFT
    if not root.is_dir():
        raise C.SkipCase("草稿根不存在：%s（可用 PT_JY_DRAFT 指定）" % root)
    env = os.environ.get("PT_JY_DRAFT_NAME")
    if env:
        d = root / env
        return root, d if d.is_dir() else None
    for d in sorted(root.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            return root, d
    return root, None


def _e2e():
    """有真实草稿时跑一次片段导出，断言 out/ 下先看到分类目录。"""
    root, draft = _pick_draft()
    if draft is None:
        raise C.SkipCase("草稿根下没有可用草稿：%s" % root)
    sys.path.insert(0, str(JY))
    import main as jymain                              # noqa: E402

    C.ensure_dirs()
    out = Path(C.fresh("sandbox/jy_outdir_layout"))
    cfg = {
        "output_dir": str(out),
        "export_mode": ["clips"],
        "name_templates_active": ["{项目名}_{素材类型}_{序号:03d}_{原始名}"],
        "audio_format": "mp3",
        "bitrate_kbps": 192,
        "conflict": "rename",
        "dedupe": True,
        "extract_video_tracks": False,
        "skip_existing": False,
        "temp_dir": "",
    }
    stats = jymain.execute_export(cfg, root, draft_dirs=[draft])
    print("[stats]", stats)

    top = sorted([d.name for d in out.iterdir() if d.is_dir()])
    print("[out 顶层目录]", top)
    # 顶层只应是分类目录，绝不能出现项目目录
    cats = {"01-多条WAV", "02-素材片段", "03-AAF"}
    stray = [n for n in top if n not in cats]
    assert not stray, "out 顶层出现非分类目录（项目跑到外面了）：%s" % stray
    assert "02-素材片段" in top, "片段模式产物不在 02-素材片段 下：%s" % top

    proj = out / "02-素材片段" / draft.name
    assert proj.is_dir(), "项目层不在分类目录内：%s" % proj
    files = list(proj.rglob("*.mp3"))
    print("[02-素材片段/%s 文件数]" % draft.name, len(files))
    assert files, "分类目录内没有产物：%s" % proj
    return "out 顶层=%s ｜ 02-素材片段/%s 有 %d 个文件" % (top, draft.name, len(files))


C.run_case("S9 静态：产物目录落点分类在外", _static_source)
C.run_case("S9 静态：界面文案同步新结构", _static_doc)
C.run_case("S9 端到端：跑一次片段导出断言产物树", _e2e)
sys.exit(C.report("S9 输出目录层级（分类在外 · 项目在内）"))
