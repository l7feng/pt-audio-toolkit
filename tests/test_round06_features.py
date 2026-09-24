# -*- coding: utf-8 -*-
"""round06（v2.6.4 / 07清单 D2-D4+附加）新功能回归：纯逻辑层，无 PT/剪映依赖。

覆盖：
  P2  ptools.core.qc  wav 头解析 + 质检清单（含 mtime 过滤）
  W4  pt-tools 配置迁移（%APPDATA% → exe 旁，只复制不删除）
  W8  batch_cli.validate_jobs 结构校验
  J1  剪映 menus.scan_draft_versions 草稿版本扫描
  J2  import_audio.verify_written 写回后逐轨校验
  R1  rename-unify 审计 json 写/读 + undo_from_rows 真回滚
  F1  folder-builder precheck_build 预检
"""
import json
import os
import shutil
import struct
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

SRC = str(C.SRC)
run = C.run_case
fresh = C.fresh

# ───────── pt-tools：P2 质检 ─────────
sys.path.insert(0, os.path.join(SRC, "pt-tools"))
import pt_tools_gui as pt                              # noqa: E402
from ptools.core.qc import read_wav_header, qc_wavs, WavHeaderError   # noqa: E402


def _write_wav(path, sr=48000, ch=2, sampwidth=2, frames=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(sampwidth)
        w.setframerate(sr)
        w.writeframes(b"\x00" * (frames * ch * sampwidth))


def qc_header_parse():
    d = fresh("qc_hdr")
    p48 = os.path.join(d, "a_48k_st.wav")
    _write_wav(p48, sr=48000, ch=2, sampwidth=2, frames=96000)
    h = read_wav_header(p48)
    assert h["channels"] == 2 and h["sample_rate"] == 48000, h
    assert h["bits"] == 16, h
    assert abs(h["duration_sec"] - 2.0) < 0.01, h
    p24 = os.path.join(d, "b_44k_24.wav")
    _write_wav(p24, sr=44100, ch=1, sampwidth=3, frames=44100)
    h2 = read_wav_header(p24)
    assert h2["bits"] == 24 and h2["channels"] == 1, h2
    # 非 wav 内容必须报 WavHeaderError，而不是悄悄给出垃圾头
    bad = os.path.join(d, "c_bad.wav")
    open(bad, "wb").write(b"not a wav at all........")
    try:
        read_wav_header(bad)
        raise AssertionError("坏文件未抛 WavHeaderError")
    except WavHeaderError:
        pass
    return "48k/16/stereo+44.1k/24/mono 解析 OK，坏文件正确报错"


def qc_wavs_issues():
    d = fresh("qc_dir")
    _write_wav(os.path.join(d, "ok.wav"), sr=48000, ch=2, sampwidth=3, frames=96000)
    _write_wav(os.path.join(d, "wrong_sr.wav"), sr=44100, ch=2, sampwidth=3, frames=88200)
    _write_wav(os.path.join(d, "short.wav"), sr=48000, ch=2, sampwidth=3, frames=24000)
    # mtime 早于 since 的旧文件必须被排除（since = 导出发起时刻）
    old = os.path.join(d, "old.wav")
    _write_wav(old)
    os.utime(old, (1, 1))
    checked, issues = qc_wavs(d, since_ts=100.0, expected_sr=48000, expected_bd=24,
                              expected_dur_sec=2.0)
    names = [os.path.basename(p) for p, _h in checked]
    assert "old.wav" not in names, names
    flagged = {os.path.basename(p): why for p, why in issues}
    assert "wrong_sr.wav" in flagged, flagged
    assert "采样率不符" in flagged["wrong_sr.wav"], flagged
    assert "short.wav" in flagged and "时长偏短" in flagged["short.wav"], flagged
    assert "ok.wav" not in flagged, flagged            # 全部符合的文件不出现在异常清单
    # 位深核对单独验证：24-bit 产物对 24 期望零异常
    _checked2, issues2 = qc_wavs(d, since_ts=100.0, expected_bd=24)
    assert issues2 == [], issues2
    return "4 新文件 1 旧文件：sr/时长异常各命中，旧文件被 mtime 过滤，位深全符"


run("P2 read_wav_header 解析（PCM 16/24bit + 坏文件）", qc_header_parse)
run("P2 qc_wavs 质检清单（sr/时长/位深 + since 过滤）", qc_wavs_issues)


def w4_migrate():
    """W4：旧 %APPDATA% 配置 → exe 旁 只复制不删除。"""
    from ptools.core import config as cfg_mod
    from ptools.core import settings as st_mod
    d = fresh("w4_mig")
    new_cfg = os.path.join(d, "config.json")
    legacy = os.path.join(d, "legacy", "pt-tools", "config.json")
    os.makedirs(os.path.dirname(legacy), exist_ok=True)
    with open(legacy, "w", encoding="utf-8") as fh:
        json.dump({"last_profile": "X:\\keep-me.json", "lang": "zh"}, fh)
    saved = (cfg_mod.CONFIG_FILE, cfg_mod.APP_DIR, st_mod.LEGACY_CONFIG_FILE)
    try:
        cfg_mod.CONFIG_FILE = new_cfg
        cfg_mod.APP_DIR = d
        st_mod.LEGACY_CONFIG_FILE = legacy
        assert cfg_mod.migrate_legacy_config() is True
        with open(new_cfg, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["last_profile"] == "X:\\keep-me.json", data
        assert os.path.isfile(legacy), "旧配置被删除了（应只复制）"
        # 已有新配置时不再迁移
        assert cfg_mod.migrate_legacy_config() is False
        got = cfg_mod.load_config()
        assert got["last_profile"] == "X:\\keep-me.json", got
    finally:
        (cfg_mod.CONFIG_FILE, cfg_mod.APP_DIR, st_mod.LEGACY_CONFIG_FILE) = saved
    return "旧配置字段完整迁移、旧文件保留、二次调用幂等"


run("W4 pt-tools 配置迁移（legacy → exe 旁，只复制不删）", w4_migrate)


def w8_validate():
    from ptools.worker.batch_cli import validate_jobs
    errs = validate_jobs({"jobs": []})
    assert any("jobs" in e for e in errs), errs
    errs = validate_jobs({"jobs": [{"ptx": ""}], "paths": {}})
    assert any("ptx" in e for e in errs) and any("paths." in e for e in errs), errs
    ok_spec = {"jobs": [{"ptx": "X:\\a.ptx", "exports": [{"kind": "output",
                                                          "sources": ["Out1"]}]}],
               "paths": {"venv_python": "v", "export_script": "s",
                         "out_root": "o"}}
    assert validate_jobs(ok_spec) == [], validate_jobs(ok_spec)
    return "空 jobs / 缺 ptx / 缺 paths 全部命中，合法 spec 零报错"


run("W8 batch_cli.validate_jobs 结构校验", w8_validate)


# ───────── 剪映：J1 版本扫描 + J2 校验 ─────────
sys.path.insert(0, os.path.join(SRC, "jianying-draft-toolkit", "code"))


def j1_scan_versions():
    from core import menus
    d = fresh("jy_drafts")
    for name, ver in (("法老6", "6.1.0"), ("法老7", "6.1.0"), ("法老8", "5.9.5")):
        dd = os.path.join(d, name)
        os.makedirs(dd, exist_ok=True)
        with open(os.path.join(dd, "draft_content.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": ver, "duration": 1}, fh)
    # 加密/损坏：读不出的进 unknown
    dd = os.path.join(d, "坏草稿")
    os.makedirs(dd, exist_ok=True)
    open(os.path.join(dd, "draft_content.json"), "wb").write(b"\x01\x02bin")
    result = menus.scan_draft_versions(d)
    assert result["total"] == 4, result
    assert result["versions"].get("6.1.0") == 2, result
    assert result["versions"].get("5.9.5") == 1, result
    assert "坏草稿" in result["unknown"], result
    # Timelines 权威源优先生效
    dd = os.path.join(d, "多时间线", "Timelines", "abc")
    os.makedirs(dd, exist_ok=True)
    with open(os.path.join(dd, "draft_content.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": "7.0.0"}, fh)
    result2 = menus.scan_draft_versions(d)
    assert result2["versions"].get("7.0.0") == 1, result2
    return "版本统计 + 坏草稿归 unknown + Timelines 结构识别"


def j2_verify_written():
    import import_audio
    plan = {"tracks": {"MX": {"segments": 2, "duration_ms": 5000}},
            "audio_materials": 1, "max_end_us": 5_000_000}
    seg = {"material_id": "m1", "extra_material_refs": ["p1"],
           "target_timerange": {"start": 0, "duration": 2_500_000}}
    content = {"duration": 5_000_000,
               "materials": {"audios": [{"id": "m1"}],
                             "placeholder_infos": [{"id": "p1"}]},
               "tracks": [{"type": "audio", "name": "MX", "_jy_import": True,
                           "segments": [dict(seg), dict(seg)]}]}
    lines, ok = import_audio.verify_written(content, plan)
    assert ok, "\n".join(lines)
    # 缺一条片段 + 悬空引用 → 必须判不一致
    content["tracks"][0]["segments"] = [dict(seg)]
    lines2, ok2 = import_audio.verify_written(content, plan)
    assert not ok2, "\n".join(lines2)
    assert any("片段 1/2" in l for l in lines2), lines2
    content["tracks"][0]["segments"] = [dict(seg), dict(seg)]
    content["tracks"][0]["segments"][0]["material_id"] = "ghost"
    _lines3, ok3 = import_audio.verify_written(content, plan)
    assert not ok3, "悬空 material_id 未被抓到"
    return "一致→ok；缺片段/悬空素材引用→判不一致"


run("J1 scan_draft_versions 草稿版本扫描", j1_scan_versions)
run("J2 verify_written 写回后逐轨校验", j2_verify_written)


# ───────── rename-unify：R1 审计 + 回滚 ─────────
sys.path.insert(0, os.path.join(SRC, "rename-unify", "code"))
import core_rules as CORE_RU                           # noqa: E402


def r1_audit_roundtrip():
    d = fresh("ru_audit")
    src = os.path.join(d, "a.txt")
    dst = os.path.join(d, "b.txt")
    open(src, "w").write("x")
    audit = os.path.join(d, "rename_audit_20260924_000000.json")
    CORE_RU.write_audit(audit, [[src, dst]], {"count": 1, "root": d})
    rows, meta = CORE_RU.load_audit(audit)
    assert rows == [[src, dst]], rows
    assert meta.get("count") == 1, meta
    # 坏格式必须报 ValueError
    bad = os.path.join(d, "bad.json")
    open(bad, "w", encoding="utf-8").write('{"no": "items"}')
    try:
        CORE_RU.load_audit(bad)
        raise AssertionError("坏审计文件未抛 ValueError")
    except ValueError:
        pass
    return "审计 json 写/读往返 + 坏格式显式报错"


def r1_undo_rows():
    d = fresh("ru_undo")
    src = os.path.join(d, "原文件.wav")
    dst = os.path.join(d, "新文件.wav")
    open(src, "w").write("x")
    os.rename(src, dst)                       # 模拟已改名后的世界
    rows = [[src, dst]]
    done, failed = CORE_RU.undo_from_rows(rows)
    assert not failed and done == [(dst, src)], (done, failed)
    assert os.path.isfile(src) and not os.path.exists(dst)
    # 新文件不存在 → 记 failed 不炸
    done2, failed2 = CORE_RU.undo_from_rows(rows)
    assert not done2 and len(failed2) == 1, (done2, failed2)
    # 与 undo_from_log 同源：csv 也走 undo_from_rows
    csv_path = os.path.join(d, "rename_log_1.csv")
    open(src, "w").write("y")
    os.rename(src, dst)
    import csv as _csv
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(CORE_RU.LOG_HEADER)
        w.writerows(rows)
    done3, failed3 = CORE_RU.undo_from_log(csv_path)
    assert not failed3 and done3 == [(dst, src)], (done3, failed3)
    assert os.path.isfile(src)
    return "真回滚 OK；缺新文件记 failed；CSV 与审计共用同一循环"


run("R1 write_audit/load_audit 审计往返", r1_audit_roundtrip)
run("R1 undo_from_rows 跨会话回滚（真改名）", r1_undo_rows)


# ───────── folder-builder：F1 预检 ─────────
sys.path.insert(0, os.path.join(SRC, "pt-project-folder-builder"))
import folder_builder_gui as fb                        # noqa: E402


def f1_precheck():
    # 场景1：模板根不存在 → 一条致命问题即返回
    problems = fb.precheck_build("X:\\不存在\\模板", "X:\\不存在\\输出",
                                 "X:\\不存在\\输出\\proj", [], "重命名")
    assert problems and "模板路径不存在" in problems[0], problems
    # 场景2：完整模板 + 可写输出 → 零问题
    tpl = fresh("fb_tpl_ok")
    os.makedirs(os.path.join(tpl, "文件夹模板", "Audio"), exist_ok=True)
    os.makedirs(os.path.join(tpl, "Project模板"), exist_ok=True)
    open(os.path.join(tpl, "Project模板", "T.ptx"), "w").write("x")
    out = fresh("fb_out_ok")
    problems2 = fb.precheck_build(tpl, out, os.path.join(out, "01-测试D"),
                                  [], "重命名")
    assert problems2 == [], problems2
    # 场景3：ptx 选项≠none 但模板没有 .ptx → 命中
    tpl2 = fresh("fb_tpl_noptx")
    os.makedirs(tpl2, exist_ok=True)
    problems3 = fb.precheck_build(tpl2, out, os.path.join(out, "02-x"),
                                  [], "重命名")
    assert any(".ptx" in p for p in problems3), problems3
    return "缺模板/无ptx 命中，完整模板零问题"


run("F1 precheck_build 建立前预检", f1_precheck)


sys.exit(C.report("round06 新功能回归结果"))
