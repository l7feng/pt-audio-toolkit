# -*- coding: utf-8 -*-
"""D3·J10（v2.9.2）批量多工程导入回归：only 过滤 / list_track_names / GUI 接线。

纯逻辑层 + 最小 json + 合成 wav；无 PT/剪映真机依赖。
"""
import json
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

C.ensure_tk()

SRC = str(C.SRC)
JY_CODE = os.path.join(SRC, "jianying-draft-toolkit", "code")
case = C.case

sys.path.insert(0, JY_CODE)
import import_audio                                    # noqa: E402


def _mk_wav(path: Path, seconds: float = 1.0, rate: int = 48000):
    """最小合法 PCM WAV（16bit 单声道）。"""
    n = int(seconds * rate)
    data = struct.pack("<%dh" % n, *([0] * n))
    hdr = struct.pack("<4sI4s4sIHHIIHH4sI",
                      b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16,
                      1, 1, rate, rate * 2, 2, 16, b"data", len(data))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(hdr + data)


def _mk_pkg(tmp: str):
    """最小交付包：json（两轨音频 + 一条 VCA）+ audio/ 下两个 wav。"""
    d = Path(C.fresh(tmp))
    (d / "audio").mkdir(parents=True, exist_ok=True)
    _mk_wav(d / "audio" / "ClipA.wav")
    _mk_wav(d / "audio" / "ClipB.wav")
    jp = d / "pt-clips.json"
    jp.write_text(json.dumps({
        "session": {"fps": 25, "raw_summary": {"工程起始时间码": "00:00:00:00"}},
        "tracks": [
            {"name": "DX 1", "clips": [
                {"name": "ClipA", "start": "00:00:01:00", "end": "00:00:02:00"}]},
            {"name": "MX 1", "clips": [
                {"name": "ClipB", "start": "00:00:01:00", "end": "00:00:02:00"}]},
        ],
        "track_meta": [
            {"name": "DX 1", "index": 1, "format": 1, "type": 0},
            {"name": "MX 1", "index": 2, "format": 1, "type": 0},
            {"name": "MX VCA", "index": 3, "format": 35, "type": 5},
        ],
        "clip_file_map": {"ClipA": "ClipA.wav", "ClipB": "ClipB.wav"},
        "online_files": [{"name": "ClipA.wav"}, {"name": "ClipB.wav"}],
    }, ensure_ascii=False), encoding="utf-8")
    return jp, d / "audio"


@case("J10c 轨名清单：list_track_names 列音频轨、剔除 VCA/Folder")
def j10c_names():
    jp, _audio = _mk_pkg("j10c_names")
    names = import_audio.list_track_names(jp)
    assert names == ["DX 1", "MX 1"], names


@case("J10c only 过滤：只保留勾选轨（精确名匹配）")
def j10c_only():
    jp, audio = _mk_pkg("j10c_only")
    rows = import_audio.parse_pt_clips(jp, (), audio_dir=audio, only=("DX 1",))
    assert rows and {r["_pt_track"] for r in rows} == {"DX 1"}, rows
    assert rows[0]["_pt_clip_name"] == "ClipA", rows[0]


@case("J10c only 为空：行为与旧版完全一致（全轨）")
def j10c_no_only():
    jp, audio = _mk_pkg("j10c_no_only")
    rows_old = import_audio.parse_pt_clips(jp, (), audio_dir=audio, verbose=False)
    rows_new = import_audio.parse_pt_clips(jp, (), audio_dir=audio, only=(), verbose=False)
    assert {r["_pt_track"] for r in rows_old} == {"DX 1", "MX 1"}
    assert rows_old == rows_new, "only=() 不应改变行为"


@case("J10c only 全不匹配：结果为空且不抛异常")
def j10c_only_empty():
    jp, audio = _mk_pkg("j10c_only_empty")
    rows = import_audio.parse_pt_clips(jp, (), audio_dir=audio,
                                       only=("不存在的轨",), verbose=False)
    assert rows == [], rows


@case("J10c CLI：main() argparse 带 --only；GUI 批量对话框已接线")
def j10c_wired():
    ia = open(os.path.join(JY_CODE, "import_audio.py"), encoding="utf-8").read()
    assert '"--only"' in ia and "only=only" in ia, "main() 应消费 --only"
    tab = open(os.path.join(JY_CODE, "tabs", "import_tab.py"),
               encoding="utf-8").read()
    for kw in ("_do_import_batch", "_BatchPickDialog", "_json_batch",
               "list_track_names", '"--only"', "askopenfilenames"):
        assert kw in tab, f"import_tab 缺 {kw}"


@case("J10c 同源：三处滚动容器实现一致（防漂移）")
def j10c_scrollable_sync():
    import hashlib
    pts = os.path.join(C.SRC, "pt-tools", "ptools", "gui", "scrollable.py")
    ru = os.path.join(C.SRC, "rename-unify", "code", "scrollable.py")
    h1 = hashlib.md5(open(pts, "rb").read()).hexdigest()
    h2 = hashlib.md5(open(ru, "rb").read()).hexdigest()
    assert h1 == h2, "scrollable.py 两份同源副本内容不一致，需同步"
    jy = open(os.path.join(C.SRC, "jianying-draft-toolkit", "code", "tabs",
                           "base.py"), encoding="utf-8").read()
    assert 'bind_all("<MouseWheel>", self._on_wheel, add=" + ")'.replace(" ", "") \
           not in jy.replace(" ", "") or 'add="+"' in jy, "剪映 base.py 应为 add=+ 绑定"


if __name__ == "__main__":
    sys.exit(C.report("J10 批量导入回归"))
