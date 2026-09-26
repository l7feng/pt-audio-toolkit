# -*- coding: utf-8 -*-
"""PT-Deliver 交付格式正式化（D 档决策 3 后半）回归

覆盖：
  1. 结构校验：合格包 / 缺字段 / clip_file_map 悬空引用
  2. 兼容：1.0 → 1.1 补齐（只补缺失，不改既有值）
  3. 包校验：素材存在性 + md5 + 统计
  4. 既有产物兼容：真实 pt-clips.json（schema_version=1.1）应直接通过结构校验
     （文件不在则 SKIP，不算失败）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import SRC, case, fresh, report  # noqa: E402

PT_CORE = str(SRC / "pt-tools")
if PT_CORE not in sys.path:
    sys.path.insert(0, PT_CORE)

from ptools.core import deliver as DL  # noqa: E402


def _good_doc():
    return {
        "schema_version": "1.1",
        "source": "PTSL ExportSessionInfoAsText (CId 30) + GetTrackList",
        "scanned_at": "2026-09-27T00:00:00+00:00",
        "session": {"name": "测试工程", "sample_rate": 48000, "fps": 30,
                    "raw_summary": {}},
        "online_files": [{"name": "a.L.wav", "location": "audio/"},
                         {"name": "a.R.wav", "location": "audio/"}],
        "clip_file_map": {"a-01.L": "a.L.wav", "a-01.R": "a.R.wav"},
        "track_meta": [{"name": "DX 1", "index": 1, "format": 35, "type": 14}],
        "track_count": 1,
        "tracks": [{"name": "DX 1", "format": "立体声",
                    "clips": [{"name": "a-01", "start": "00:00:00:00",
                               "end": "00:00:05:00"}], "fades": []}],
    }


@case("1 · 结构校验：合格包零 error")
def _():
    errs, warns = DL.validate_structure(_good_doc())
    assert not errs, errs
    return "零 error（warning %d 条）" % len(warns)


@case("2 · 结构校验：缺字段 / 悬空引用 必须报错")
def _():
    d = _good_doc()
    del d["online_files"]
    errs, _w = DL.validate_structure(d)
    assert any("online_files" in e for e in errs), errs

    d2 = _good_doc()
    d2["clip_file_map"]["a-01.L"] = "not_in_package.wav"
    errs2, _w2 = DL.validate_structure(d2)
    assert any("clip_file_map" in e for e in errs2), errs2

    errs3, _w3 = DL.validate_structure({"schema_version": "9.9"})
    assert errs3, "未知版本必须报错"
    return "缺字段 / 悬空引用 / 未知版本 三类均拦截"


@case("3 · 兼容：1.0 → 1.1 只补缺失，不改既有值")
def _():
    d = {"schema_version": "1.0", "session": {"name": "老包"},
         "online_files": [{"name": "x.wav", "location": "audio/"}],
         "tracks": [{"name": "DX 1", "clips": []}]}
    d2, warns = DL.upgrade(dict(d))
    assert d2["track_meta"] == [] and d2["clip_file_map"] == {}, d2
    assert d2["session"]["name"] == "老包", "既有值不得被改写"
    assert warns, "补齐应留下 warning 便于排查"
    errs, _w = DL.validate_structure(d2)
    assert not errs, errs
    return "补齐 track_meta/clip_file_map，既有值保留"


@case("4 · 包校验：素材齐全通过；缺文件报错")
def _():
    sb = fresh("pt_deliver_pkg")
    pkg = os.path.join(sb, "测试工程-导入包")
    audio = os.path.join(pkg, DL.AUDIO_SUBDIR)
    os.makedirs(audio, exist_ok=True)
    for n in ("a.L.wav", "a.R.wav"):
        with open(os.path.join(audio, n), "wb") as fh:
            fh.write(b"RIFF" + b"\0" * 100)
    doc = _good_doc()
    with open(os.path.join(pkg, "pt-clips.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)

    errs, warns, stats = DL.validate_package(doc, pkg, check_md5=True)
    assert not errs, errs
    assert stats["files"] == 2 and stats["missing"] == 0, stats
    assert set(stats["md5"]) == {"a.L.wav", "a.R.wav"}, stats.get("md5")

    # 删掉一个素材 → 必须报 missing
    os.remove(os.path.join(audio, "a.R.wav"))
    errs2, _w2, stats2 = DL.validate_package(doc, pkg, check_md5=False)
    assert stats2["missing"] == 1, stats2
    assert any("缺少 1 个素材" in e for e in errs2), errs2
    return "齐全通过（md5 2 份）；缺 1 个文件即报错"


@case("5 · describe 摘要与常量自洽")
def _():
    s = DL.describe(_good_doc())
    assert "PT-Deliver" in s and "v1.1" in s and "2 素材" in s, s
    assert DL.SPEC_NAME == "PT-Deliver"
    assert DL.SPEC_VERSION in DL.SUPPORTED_VERSIONS
    return s


@case("6 · 既有产物兼容：真实 pt-clips.json 直接通过结构校验")
def _():
    from _common import SkipCase
    cand = r"D:\My-Temporary\ptsl-run-20260926-235608\pt-clips.json"
    if not os.path.isfile(cand):
        raise SkipCase("真实产物不在：%s" % cand)
    doc = json.load(open(cand, encoding="utf-8"))
    errs, warns = DL.validate_structure(doc)
    assert not errs, errs
    return "%s（现有产物无需迁移即为合法 %s 包）" % (DL.describe(doc), DL.SPEC_NAME)


if __name__ == "__main__":
    sys.exit(report("PT-Deliver 交付格式正式化：schema + 校验器 + 兼容规则"))
