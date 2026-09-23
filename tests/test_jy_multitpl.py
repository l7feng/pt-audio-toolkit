# -*- coding: utf-8 -*-
"""剪映工具包：片段模式 + 多命名模板端到端（v2.4.0 新功能）

直接调 execute_export 传内存 cfg，不写仓库 config.json（不影响用户配置）。
草稿名可用环境变量 `PT_JY_DRAFT_NAME` 覆盖，默认「前夫」。

独立跑法：python tests/test_jy_multitpl.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

JY = str(C.SRC / "jianying-draft-toolkit" / "code")
sys.path.insert(0, JY)
import main as jymain                                  # noqa: E402

DRAFT_ROOT = C.DRAFT
DRAFT = DRAFT_ROOT / (os.environ.get("PT_JY_DRAFT_NAME") or "前夫")
OUT = Path(C.SANDBOX) / "jy_e2e_clips"

cfg = {
    "output_dir": str(OUT),
    "export_mode": ["clips"],
    "name_templates_active": [
        "{项目名}_{素材类型}_{序号:03d}_{原始名}_{时长}s",
        "{原始名}",
    ],
    "audio_format": "mp3",
    "bitrate_kbps": 192,
    "conflict": "rename",
    "dedupe": True,
    "extract_video_tracks": False,
    "skip_existing": False,
    "temp_dir": "",
}


def _e2e():
    C.ensure_dirs()
    if not DRAFT.is_dir():
        raise C.SkipCase("草稿不存在：%s（可用 PT_JY_DRAFT_NAME 指定草稿名）" % DRAFT)

    # 每轮清空，避免上一轮产物残留导致「分目录」断言误判
    C.fresh("sandbox/jy_e2e_clips")
    out = Path(C.SANDBOX) / "jy_e2e_clips"

    stats = jymain.execute_export(cfg, DRAFT_ROOT, draft_dirs=[DRAFT])
    print("[stats]", stats)

    tpl_dirs = sorted([d.name for d in out.iterdir() if d.is_dir() and d.name.startswith("模板")])
    files1 = list((out / "模板1").rglob("*.mp3")) if (out / "模板1").is_dir() else []
    files2 = list((out / "模板2").rglob("*.mp3")) if (out / "模板2").is_dir() else []
    print("[模板子目录]", tpl_dirs)
    print("[模板1 文件数]", len(files1), "| [模板2 文件数]", len(files2))
    print("[样例]", [f.name for f in files1[:2]], [f.name for f in files2[:2]])
    assert tpl_dirs == ["模板1", "模板2"], tpl_dirs
    assert len(files1) > 0 and len(files2) > 0, (len(files1), len(files2))
    return "模板1=%d 文件 / 模板2=%d 文件" % (len(files1), len(files2))


C.run_case("剪映片段模式 + 多命名模板端到端（v2.4.0，真实草稿）", _e2e)
sys.exit(C.report("剪映片段模式 + 多命名模板端到端"))
