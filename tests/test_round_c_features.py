# -*- coding: utf-8 -*-
"""方案C（v2.7.0）功能包回归：J1 模板命名 / J10a 分包模板 / J10b 字幕 / J8 退役 / P1 技能。

纯逻辑层 + 最小 json；无 PT/剪映真机依赖。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

C.ensure_tk()

SRC = str(C.SRC)
JY_CODE = os.path.join(SRC, "jianying-draft-toolkit", "code")
case = C.case

sys.path.insert(0, JY_CODE)
import main as core                                    # noqa: E402
from tabs.export_tab import normalize_template_entry   # noqa: E402


# ───────── J1：模板命名 ─────────
@case("J1 归一：str 条目 → dict（名字=前12字符）")
def j1_normalize_str():
    e = normalize_template_entry("{项目名}_{原始名}_额外额外额外")
    assert e["name"] == "{项目名}_{原始名}_额外"[:12] and e["template"].startswith("{项目名}"), e


@case("J1 归一：dict 缺 name 补齐；空串兜底「模板」")
def j1_normalize_dict():
    e = normalize_template_entry({"template": "{原始名}"})
    assert e == {"name": "{原始名}", "template": "{原始名}"}, e
    e2 = normalize_template_entry({"name": "", "template": ""})
    assert e2["name"] == "模板", e2


@case("J1 预设库：NAMING_PRESETS 全部为带名 dict 且无重名")
def j1_presets():
    assert all(isinstance(p, dict) and p.get("name") and p.get("template")
               for p in core.NAMING_PRESETS), core.NAMING_PRESETS
    names = [p["name"] for p in core.NAMING_PRESETS]
    assert len(names) == len(set(names)), names


@case("J1 UI 接线：管理弹窗/管理按钮/collect dict 适配存在")
def j1_wired():
    src = open(os.path.join(JY_CODE, "tabs", "export_tab.py"),
               encoding="utf-8").read()
    assert "_manage_templates" in src and "管理…" in src
    assert 'lib[i]["template"]' in src, "collect 应从 dict 取模板串"


# ───────── J10a：分包夹名模板 ─────────
@case("J10a 默认模板：{视频名}（保持现状）且 UI 接线存在")
def j10a_default():
    assert core.DEFAULT_CONFIG.get("split_folder_template") == "{视频名}"
    src = open(os.path.join(JY_CODE, "main.py"), encoding="utf-8").read()
    assert "split_folder_template" in src, "分包夹名模板应接入 process_draft_tracks"


# ───────── J10b：字幕导出 ─────────
def _mk_draft(tmp, texts, cues):
    d = C.fresh(tmp)
    p = Path(d) / "draft_content.json"
    p.write_text(json.dumps({
        "materials": {"texts": [{"id": t["id"], "content": t["content"]}
                                for t in texts]},
        "tracks": [{"type": "text", "segments": [
            {"material_id": c["mid"],
             "target_timerange": {"start": c["s"], "duration": c["d"]}}
            for c in cues]},
            {"type": "audio", "segments": []}],
    }, ensure_ascii=False), encoding="utf-8")
    return p


@case("J10b 字幕：基础导出（条数/内容/时码格式）")
def j10b_basic():
    p = _mk_draft("j10_a",
                  [{"id": "t1", "content": "你好"}, {"id": "t2", "content": "世界"}],
                  [{"mid": "t1", "s": 1_000_000, "d": 1_500_000},
                   {"mid": "t2", "s": 3_000_000, "d": 2_000_000}])
    out = Path(C.fresh("j10_a_out")) / "字幕" / "草稿.srt"
    n = core.export_subtitles(p, out)
    assert n == 2, n
    body = out.read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:02,500" in body and "你好" in body, body
    assert "00:00:03,000 --> 00:00:05,000" in body and "世界" in body, body


@case("J10b 字幕：窗口裁剪 + 时间码平移到窗口起点")
def j10b_window():
    p = _mk_draft("j10_b",
                  [{"id": "t1", "content": "窗口内"},
                   {"id": "t2", "content": "窗口前"}, {"id": "t3", "content": "窗口后"}],
                  [{"mid": "t1", "s": 12_000_000, "d": 1_000_000},
                   {"mid": "t2", "s": 1_000_000, "d": 1_000_000},
                   {"mid": "t3", "s": 99_000_000, "d": 1_000_000}])
    out = Path(C.fresh("j10_b_out")) / "字幕" / "集.srt"
    n = core.export_subtitles(p, out, win=(10_000_000, 20_000_000))
    assert n == 1, n
    body = out.read_text(encoding="utf-8")
    assert "00:00:02,000 --> 00:00:03,000" in body and "窗口内" in body, body
    assert "窗口前" not in body and "窗口后" not in body, body


@case("J10b 集成：GUI 复选框/collect/CLI 参数已接线")
def j10b_wired():
    tab_src = open(os.path.join(JY_CODE, "tabs", "export_tab.py"),
                   encoding="utf-8").read()
    assert "导出字幕（.srt，文本轨）" in tab_src
    assert '"export_subtitles"' in tab_src
    main_src = open(os.path.join(JY_CODE, "main.py"), encoding="utf-8").read()
    assert '"--subtitles"' in main_src
    assert core.DEFAULT_CONFIG.get("export_subtitles") is False


# ───────── J8/J9：③页退役 ─────────
@case("J8 退役：delivery_tab.py / make_delivery_package.py 已删除")
def j8_retired():
    assert not os.path.exists(os.path.join(JY_CODE, "tabs", "delivery_tab.py"))
    assert not os.path.exists(os.path.join(JY_CODE, "make_delivery_package.py"))
    gui_src = open(os.path.join(JY_CODE, "gui.py"), encoding="utf-8").read()
    assert "DeliveryTab" not in gui_src, "gui.py 不应再引用 DeliveryTab"


@case("J8 消费端保留：导入页交付包 json 模式与 _delivery_package 逻辑不变")
def j8_consumer():
    ia = open(os.path.join(JY_CODE, "import_audio.py"), encoding="utf-8").read()
    assert "_delivery_package" in ia, "导入端离线识别逻辑应保留"


# ───────── P1：交付包一步直出 ─────────
@case("P1 技能就位：pt-clips 三件套 + 总控脚本存在")
def p1_scripts():
    d = os.path.join(SRC, "pt-tools", "skills", "pt-clips", "scripts")
    for f in ("pt-clips.py", "pt_clip_scan.py", "make_delivery_package.py",
              "import_audio.py"):
        assert os.path.isfile(os.path.join(d, f)), f
    sys.path.insert(0, os.path.join(SRC, "pt-tools"))
    sys.modules.pop("ptools.core.settings", None)
    sys.modules.pop("ptools.core", None)
    sys.modules.pop("ptools", None)
    from ptools.core.settings import SCRIPTS
    assert SCRIPTS.get("pt-clips") == "pt-clips.py", SCRIPTS


@case("P1 总控逻辑：light 打包/默认排除/失败码在总控脚本中")
def p1_wired():
    s = open(os.path.join(SRC, "pt-tools", "skills", "pt-clips", "scripts",
                          "pt-clips.py"), encoding="utf-8").read()
    assert "build_package" in s and "light=True" in s
    assert "DEFAULT_EXCLUDE" in s
    assert "pt_clip_scan.run" in s
    app_src = open(os.path.join(SRC, "pt-tools", "ptools", "gui", "app.py"),
                   encoding="utf-8").read()
    assert "do_delivery" in app_src and '"pt-clips"' in app_src
    build_src = open(os.path.join(SRC, "..", "tools", "build.py"),
                     encoding="utf-8").read()
    assert '"pt-clips"' in build_src, "打包应内置 pt-clips 技能"


if __name__ == "__main__":
    sys.exit(C.report("方案C（v2.7.0）功能包回归"))
