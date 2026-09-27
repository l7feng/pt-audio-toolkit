#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2.10.0 六项反馈整改回归（2026-09-27）。

覆盖用户当日 6 条反馈中可纯逻辑验证的部分：
  Q1  素材类型手动覆盖（render_name type_override）
  Q2  断点续跑出厂默认翻转 + 一次性迁移
  Q3  AAF 失败写文件日志 + 03-AAF 落点常量
  Q4  片段模式按视频窗归「集」的门控放开（源码语义核对）
  Q6  导入页 json 类型判别（pt-clips vs pt-profile）
AAF 打包核验与真机链路在 live 步骤做，不在此文件。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

C.ensure_tk()          # tabs.import_tab import tkinter

SRC = str(C.SRC)
case = C.case

CODE = os.path.join(SRC, "jianying-draft-toolkit", "code")
sys.path.insert(0, CODE)

import main as core                                    # noqa: E402
from core.config import DEFAULT_CONFIG, load_config, save_config  # noqa: E402


def _seg(track_type="audio"):
    """构造最小 AudioSegment（只用到 render_name 的字段）。"""
    return core.AudioSegment(
        project="测试", track_type=track_type,
        source_path="D:/nonexistent/src.wav",
        start_us=0, end_us=1_000_000,
        material_name="AI配音_01", material_id="m1",
    )


# ───────── Q1：素材类型手动覆盖 ─────────

@case("Q1 空覆盖/不传 → 自动判定（voice 源）")
def q1_auto():
    seg = _seg("voice")
    tpl = "{素材类型}_{原始名}"
    assert core.render_name(tpl, seg, 1, type_override="") == "voice_AI配音_01", \
        core.render_name(tpl, seg, 1, type_override="")
    assert core.render_name(tpl, seg, 1) == "voice_AI配音_01"


@case("Q1 UCS 码覆盖：FX/MX/DX/AMB/BG/DIA/MUS 全部生效")
def q1_ucsi():
    seg = _seg("voice")
    tpl = "{素材类型}_{原始名}"
    for code in ("FX", "MX", "DX", "AMB", "BG", "DIA", "MUS"):
        got = core.render_name(tpl, seg, 1, type_override=code)
        assert got == f"{code}_AI配音_01", (code, got)


@case("Q1 覆盖优先于自动判定（music 源 + AMB）且值被清洗")
def q1_priority():
    seg = _seg("music")
    assert core.render_name("{素材类型}", seg, 1, type_override="AMB") == "AMB"
    assert core.render_name("{素材类型}", _seg("voice"), 1,
                            type_override="  FX ") == "FX"


@case("Q1 出厂配置带 clip_type_override 键且默认空")
def q1_config_key():
    assert DEFAULT_CONFIG.get("clip_type_override") == "", \
        DEFAULT_CONFIG.get("clip_type_override")


# ───────── Q2：断点续跑默认翻转 ─────────

@case("Q2 出厂默认 skip_existing=False")
def q2_default():
    assert DEFAULT_CONFIG.get("skip_existing") is False


@case("Q2 旧默认 True 一次性迁移翻转并落标记")
def q2_migrate():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "config.json"
        save_config({"skip_existing": True}, p)
        got = load_config(p)
        assert got.get("skip_existing") is False, got.get("skip_existing")
        assert got.get("_migrated_2100_skip") is True


@case("Q2 迁移后用户特意勾回 True → 永久尊重")
def q2_respect_user():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "config.json"
        save_config({"skip_existing": True}, p)
        got = load_config(p)
        got["skip_existing"] = True
        save_config(got, p)
        got2 = load_config(p)
        assert got2.get("skip_existing") is True, got2.get("skip_existing")


@case("Q2 已是 False 的配置不受迁移影响")
def q2_keep_false():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "config.json"
        save_config({"skip_existing": False}, p)
        got = load_config(p)
        assert got.get("skip_existing") is False
        assert got.get("_migrated_2100_skip") is True


# ───────── Q3：AAF 失败落日志 + 落点 ─────────

@case("Q3 非分包 AAF 失败写文件日志（旧版只 print）")
def q3_logging():
    src = open(os.path.join(CODE, "main.py"), encoding="utf-8").read()
    assert "[FAIL] AAF {draft_dir.name}: {msg}" in src, "缺 [FAIL] 日志行"


@case("Q3 AAF 落点仍为 03-AAF（非分包 + 分包按集，与 01-多条WAV 同级）")
def q3_paths():
    src = open(os.path.join(CODE, "main.py"), encoding="utf-8").read()
    assert 'output_root / draft_dir.name / "03-AAF"' in src
    assert 'output_root / folder / "03-AAF"' in src


# ───────── Q4：片段按集分包门控放开 ─────────

@case("Q4 collect 不再把 split_by_video 强制绑在整轨上")
def q4_gate():
    src = open(os.path.join(CODE, "tabs", "export_tab.py"),
               encoding="utf-8").read()
    assert 'self.cfg["split_by_video"] = bool(self.var_split_video.get())' in src, \
        "collect 应直接采用复选框值"
    assert 'and \\\n            "tracks" in self._mode_set()' not in src, \
        "旧门控残留"


@case("Q4 片段按视频窗归夹逻辑在位（chunk_dir / 02-素材片段）")
def q4_core_logic():
    src = open(os.path.join(CODE, "main.py"), encoding="utf-8").read()
    assert 'chunk_dir / "02-素材片段"' in src
    assert "chunk_index_for_tl" in src


# ───────── Q6：json 类型判别 ─────────

@case("Q6 pt-clips 识别（tracks[].clips 存在，含空数组）")
def q6_ptclips():
    from tabs.import_tab import ImportTab
    kind = ImportTab._json_kind
    assert kind({"schema_version": "1.1",
                 "tracks": [{"name": "A", "clips": []}]}) == "pt-clips"


@case("Q6 pt-profile 档案识别（有 session/tracks、轨上无 clips）")
def q6_profile():
    from tabs.import_tab import ImportTab
    kind = ImportTab._json_kind
    profile = {"schema_version": "1.0", "session": {"name": "法老35"},
               "tracks": [{"name": "A", "attributes": {}, "type": 2}]}
    assert kind(profile) == "pt-profile", kind(profile)


@case("Q6 未知/空结构 → unknown（不误伤）")
def q6_unknown():
    from tabs.import_tab import ImportTab
    kind = ImportTab._json_kind
    assert kind({"foo": 1}) == "unknown"
    assert kind({}) == "unknown"


@case("Q6 do_import 硬拦截在位（源码含 _json_kind 门）")
def q6_guard():
    src = open(os.path.join(CODE, "tabs", "import_tab.py"),
               encoding="utf-8").read()
    assert 'if self._json_kind(doc) != "pt-clips":' in src


if __name__ == "__main__":
    sys.exit(C.report("v2.10.0 六项反馈整改回归"))
