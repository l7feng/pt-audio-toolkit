# -*- coding: utf-8 -*-
"""P0 回归：read_wav_header 在真实 PT bounce 产物上的块遍历（曾无限循环挂死质检线程）。

发现方式（2026-09-26 PTSL 端到端实测）：拿 pt_scan 定位的「法老35」工程做
10 秒真 bounce，产物交给 qc_wavs 质检，程序直接卡死不返回。

两个叠加缺陷：
  1. 跳块用 fh.seek(csz) —— 把「块长」当成「绝对偏移」，跳回文件中部；
  2. 无进度/EOF 保护，撞上零长块就在两个偏移间无限循环。
     PT 产物在 data 之后还有 regn/umid/DGDA 元数据块，末尾残留 8 字节
     读作 cid=b'\\0\\0\\0\\0' csz=0 → seek(0) → 回到 RIFF 头 → 死循环。

后果：pt-tools 的「导出质检」（P2）在任何真实 PT 产物上永远不返回，
后台 daemon 线程永久泄漏，界面照常跑但质检结果始终出不来。

本测试用与 PT 落盘一致的块布局（JUNK/bext/fmt/data/regn/umid/DGDA）
构造最小 wav，并加看门狗线程：修复前会超时失败，而不是把测试套件挂死。
"""
import os
import struct
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src", "pt-tools"))

from ptools.core.qc import read_wav_header, qc_wavs, WavHeaderError  # noqa: E402
from _common import fresh as fresh_dir  # noqa: E402

FAILS = []


def run(name, fn):
    try:
        fn()
    except Exception as exc:                      # noqa: BLE001
        FAILS.append(name)
        print("  [FAIL] %s -- %r" % (name, exc))
    else:
        print("  [ok]   %s" % name)


def _chunk(cid, body):
    """按 wav 规范拼一个块：4 字节 id + 4 字节小端长度 + 体（奇数长度补 1 字节）。"""
    out = cid + struct.pack("<I", len(body)) + body
    if len(body) & 1:
        out += b"\x00"
    return out


def make_pt_style_wav(path, channels=2, sr=48000, bits=24, seconds=10):
    """复刻 PT Bounce 落盘布局：JUNK → bext → fmt → data → 尾部元数据块。"""
    byte_rate = sr * channels * bits // 8
    block_align = channels * bits // 8
    data = b"\x00" * (byte_rate * seconds)

    fmt_body = struct.pack("<HHIIHH", 1, channels, sr, byte_rate, block_align, bits)
    fmt_body += b"\x00" * (40 - len(fmt_body))          # 24-bit 也补到 extensible 长度
    body = b"WAVE"
    body += _chunk(b"JUNK", b"\x00" * 64)                # PT 固定写 64 字节 JUNK
    body += _chunk(b"bext", b"\x00" * 602)               # Broadcast Extension
    body += _chunk(b"fmt ", fmt_body)
    body += _chunk(b"minf", b"\x00" * 16)
    body += _chunk(b"elm1", b"\x00" * 242)               # 故意用奇数长度块测 padding
    body += _chunk(b"data", data)
    body += _chunk(b"regn", b"\x00" * 92)                # data 之后仍有元数据块
    body += _chunk(b"umid", b"\x00" * 24)
    body += _chunk(b"DGDA", b"\x00" * 16005)             # iXML 尾巴，体积大易触发跳错
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def parse_with_watchdog(path, timeout=8.0):
    """把解析丢进守护线程；修复前会死循环，join 超时即判失败（不会挂死测试）。"""
    box = {}

    def _work():
        try:
            box["h"] = read_wav_header(path)
        except BaseException as exc:                  # noqa: BLE001
            box["e"] = exc

    th = threading.Thread(target=_work, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise AssertionError("read_wav_header 超时未返回（%ss）—— 块遍历又死循环了？" % timeout)
    if "e" in box:
        raise box["e"]
    return box["h"]


def test_pt_style_layout_terminates():
    """PT 真实布局（含 data 后元数据块）必须能解析出正确头，且不死循环。"""
    d = fresh_dir("qc_p0_ptwav")
    p = os.path.join(d, "pt_style_24bit.wav")
    make_pt_style_wav(p, channels=2, sr=48000, bits=24, seconds=10)
    h = parse_with_watchdog(p)
    assert h["channels"] == 2, h
    assert h["sample_rate"] == 48000, h
    assert h["bits"] == 24, h
    assert h["frames"] == 48000 * 10, h
    assert abs(h["duration_sec"] - 10.0) < 1e-6, h


def test_qc_wavs_reports_clean():
    """整链质检：干净产物 0 issue（修复前根本返回不了）。"""
    d = fresh_dir("qc_p0_dir")
    make_pt_style_wav(os.path.join(d, "clean.wav"), seconds=10)
    checked, issues = qc_wavs(d, since_ts=0.0, expected_sr=48000,
                              expected_bd=24, expected_dur_sec=10.0)
    assert len(checked) == 1, checked
    assert issues == [], issues


def test_zero_length_unknown_chunk():
    """data 之后的零长未知块（PT 末尾 padding 形态）不得触发回退死循环。"""
    d = fresh_dir("qc_p0_zero")
    p = os.path.join(d, "zerolen.wav")
    make_pt_style_wav(p, seconds=2)
    with open(p, "rb") as fh:
        raw = fh.read()
    # 在 data 块之后追加一个 cid 全零、长度为 0 的块：旧实现会 seek(0) 无限循环
    raw += b"\x00" * 8
    raw = raw[:4] + struct.pack("<I", len(raw) - 8) + raw[8:]
    with open(p, "wb") as fh:
        fh.write(raw)
    h = parse_with_watchdog(p)
    assert h["channels"] == 2, h
    assert abs(h["duration_sec"] - 2.0) < 1e-6, h


def test_mono_and_32f():
    """单声道 / 32-bit float 也走同一条遍历路径。"""
    d = fresh_dir("qc_p0_variants")
    for tag, kw in (("mono", dict(channels=1, bits=16)),
                    ("f32", dict(channels=2, bits=32))):
        p = os.path.join(d, "%s.wav" % tag)
        make_pt_style_wav(p, seconds=3, **kw)
        h = parse_with_watchdog(p)
        assert h["channels"] == kw["channels"], h
        assert h["bits"] == kw["bits"], h
        assert abs(h["duration_sec"] - 3.0) < 1e-6, h


def test_broken_still_raises():
    """非 RIFF / 过小文件仍要抛 WavHeaderError，别被新遍历吞掉。"""
    d = fresh_dir("qc_p0_bad")
    bad = os.path.join(d, "bad.wav")
    with open(bad, "wb") as fh:
        fh.write(b"NOPE" + b"\x00" * 200)
    try:
        read_wav_header(bad)
    except WavHeaderError:
        pass
    else:
        raise AssertionError("非 RIFF 文件应抛 WavHeaderError")
    tiny = os.path.join(d, "tiny.wav")
    with open(tiny, "wb") as fh:
        fh.write(b"RIFF")
    try:
        read_wav_header(tiny)
    except WavHeaderError:
        pass
    else:
        raise AssertionError("过小文件应抛 WavHeaderError")


if __name__ == "__main__":
    print("== tests/test_qc_p0_realwav.py ==")
    for fn in (test_pt_style_layout_terminates,
               test_qc_wavs_reports_clean,
               test_zero_length_unknown_chunk,
               test_mono_and_32f,
               test_broken_still_raises):
        run(fn.__name__, fn)
    print("-- %d fail" % len(FAILS))
    sys.exit(1 if FAILS else 0)
