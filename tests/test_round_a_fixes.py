# -*- coding: utf-8 -*-
"""方案A（v2.6.5）快修回归：F6 根名解析 / P2 文案与弹窗 / J7 空结果诊断。

纯逻辑层，无 PT 依赖；J7 用最小 json 结构直接调 parse_pt_clips。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

C.ensure_tk()          # folder_builder_gui / ptools.gui.app 都 import tkinter

SRC = str(C.SRC)
case = C.case

# ───────── F6：folder-builder 根名解析 ─────────
sys.path.insert(0, os.path.join(SRC, "pt-project-folder-builder"))
import folder_builder_gui as fb                        # noqa: E402


@case("F6 根名解析：标准形态 15-测试D_20260925_7F")
def f6_standard():
    r = fb.parse_project_root_name("15-测试D_20260925_7F")
    assert r == {"name": "测试", "level": "D",
                 "date": "20260925", "user": "7F"}, r


@case("F6 根名解析：结尾非 ABCD → 整体算项目名")
def f6_no_level():
    r = fb.parse_project_root_name("3-星际穿越_20260901_7F")
    assert r["name"] == "星际穿越" and r["level"] == "", r
    assert r["date"] == "20260901" and r["user"] == "7F", r


@case("F6 根名解析：形态不符（纯数字/无序号/空/缺日期段）→ None")
def f6_bad():
    assert fb.parse_project_root_name("15") is None
    assert fb.parse_project_root_name("测试D_20260925_7F") is None
    assert fb.parse_project_root_name("15-测试D") is None
    assert fb.parse_project_root_name("") is None
    assert fb.parse_project_root_name(None) is None


@case("F6 根名解析：单字母项目名不误拆等级")
def f6_single_letter():
    # 项目名本身只有 1 个字符时不能把名字拆没（len(body) > 1 才拆等级）
    r = fb.parse_project_root_name("7-D_20260925_7F")
    assert r["name"] == "D" and r["level"] == "", r


@case("F6 默认项目名：出厂默认已改「测试」（F3）")
def f3_default_name():
    src = open(os.path.join(SRC, "pt-project-folder-builder",
                            "folder_builder_gui.py"),
               encoding="utf-8").read()
    assert 'tk.StringVar(value="测试")' in src, "默认项目名应为「测试」"
    assert 'value="誓言"' not in src, "默认项目名不得携带个人项目信息"


# ───────── P2：ptools 文案 / 弹窗居中 ─────────
sys.path.insert(0, os.path.join(SRC, "pt-tools"))
from ptools.core import i18n                           # noqa: E402


@case("P2 文案：e_fmt_mono 不再出现「会下混」旧表述")
def p2_wording():
    for lang, table in i18n.TEXTS.items():
        v = table.get("e_fmt_mono", "")
        assert "会下混" not in v, (lang, v)
        assert "Mono (downmix)" not in v, (lang, v)   # 旧文案整串匹配
        assert v, "e_fmt_mono 不得为空"


@case("P2 弹窗居中：center_on_parent 存在且对异常容错")
def p2_center():
    from ptools.gui.app import center_on_parent
    center_on_parent(None, None)      # 不抛异常即通过（内部全兜底）


# ───────── J2：AAF 门控文案 ─────────
@case("J2 AAF 文案：置灰态携带原因说明")
def j2_wording():
    src = open(os.path.join(SRC, "jianying-draft-toolkit", "code",
                            "tabs", "export_tab.py"),
               encoding="utf-8").read()
    assert "需先勾选「整轨」模式" in src, "AAF 置灰文案应解释原因"
    assert "纯片段模式无法生成" in src, "AAF 文案应说明格式语义约束"


# ───────── J7：0 片段诊断 ─────────
JY_CODE = os.path.join(SRC, "jianying-draft-toolkit", "code")
sys.path.insert(0, JY_CODE)
import import_audio                                    # noqa: E402


@case("J7 空诊断：无 tracks 字段的 json（疑似档案）→ 空列表不抛异常")
def j7_no_tracks():
    d = C.fresh("j7_a")
    p = Path(d) / "pt-clips.json"
    p.write_text(json.dumps({"session": {"fps": 25}}, ensure_ascii=False),
                 encoding="utf-8")
    rows = import_audio.parse_pt_clips(p)
    assert rows == [], rows


@case("J7 空诊断：唯一轨命中排除名单（Master）→ 空列表不抛异常")
def j7_all_excluded():
    d = C.fresh("j7_b")
    p = Path(d) / "pt-clips.json"
    p.write_text(json.dumps({
        "session": {"fps": 25, "raw_summary": {"工程起始时间码": "01:00:00:00"}},
        "tracks": [{"name": "Master", "clips": [
            {"name": "a.L", "start": "01:00:00:00", "end": "01:00:01:00"}]}],
    }, ensure_ascii=False), encoding="utf-8")
    # 注意：显式传默认排除名单（GUI 侧由 _exclude_args 补默认；裸调用不自动带）
    rows = import_audio.parse_pt_clips(p, exclude=import_audio.DEFAULT_EXCLUDE)
    assert rows == [], rows


@case("J7 空诊断：正常单轨片段仍可解析（防诊断改动伤正常路径）")
def j7_normal_path():
    d = C.fresh("j7_c")
    p = Path(d) / "pt-clips.json"
    p.write_text(json.dumps({
        "session": {"fps": 25, "raw_summary": {"工程起始时间码": "01:00:00:00"}},
        "clip_file_map": {},
        "online_files": [],
        "tracks": [{"name": "DX 1", "clips": [
            {"name": "dx.L", "start": "01:00:00:00", "end": "01:00:02:00"}]}],
    }, ensure_ascii=False), encoding="utf-8")
    rows = import_audio.parse_pt_clips(p)
    # 素材文件不存在 → 该片段被跳过（warn），但仍不抛异常
    assert isinstance(rows, list), type(rows)


if __name__ == "__main__":
    sys.exit(C.report("方案A（v2.6.5）快修回归"))
