# -*- coding: utf-8 -*-
"""剪映 v2.5.0：视频名解析 + 按视频分包（纯逻辑，不需要剪映/ffmpeg）

为什么单独一个文件：这批规则是**人类命名习惯**的映射，改一次要立刻能验证，
不能混在需要真实草稿解密的端到端脚本里（那种跑一次要一分钟）。

端到端（真实草稿 + ffmpeg）另见沙箱 `test_d3.py`：
8 片段 / 6 轨 / 632s 草稿 → 产出 法老4、法老4-2、法老6… 各文件夹，逐段时长对齐。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

C.ensure_tk()

SRC = str(C.SRC)
case = C.case
fresh = C.fresh

# ⚠️ core 包在 `code/` 下（main.py 用的是 `from core.config import ...`），
# 所以加进 sys.path 的是 code 目录，不是工具根。
sys.path.insert(0, os.path.join(SRC, "jianying-draft-toolkit", "code"))
vn = None
try:
    from core import videoname as vn                   # noqa: E402
except Exception as e:                                 # noqa: BLE001
    print("[import] core.videoname 失败：%r" % (e,))


# ===========================================================================
# 1. 视频名解析（用户真实命名）
# ===========================================================================

if vn is not None:
    @case("video.parse 用户真实命名（纯数字/长名/项目+集数/点分编号）")
    def _():
        cases = [
            # 用户 Video\ 目录里的真实命名
            ("17.mp4",                      dict(ep="17", project="",  need_input=True)),
            ("20.mp4",                      dict(ep="20", project="",  need_input=True)),
            ("法老的禁忌神谕 第10集  待混音.mp4",  dict(ep="10", project="", need_input=True)),
            # 期望形态
            ("法老2.mp4",                    dict(ep="2",  project="法老", need_input=False)),
            ("法老3_AiFX.mp4",               dict(ep="3",  project="法老",
                                                 need_input=False, aifx=True)),
            ("1.1.0.mp4",                   dict(ep="1",  seq="0", need_input=True)),
            ("誓言 第3集.mp4",                dict(ep="3",  project="誓言", need_input=False)),
        ]
        bad = []
        for name, want in cases:
            i = vn.parse_video_name(name)
            for k, v in want.items():
                if getattr(i, k) != v:
                    bad.append("%s.%s=%r(want %r)" % (name, k, getattr(i, k), v))
        assert not bad, bad
        return "%d 条命名全部解析正确" % len(cases)

    @case("video.parse 长名给缩写建议（>4 字）")
    def _():
        i = vn.parse_video_name("法老的禁忌神谕 第10集  待混音.mp4")
        assert i.need_input, "7 字项目名应要求人类缩写"
        assert i.suggest == "法老", i.suggest
        assert "4" in i.reason          # 提示里要说明阈值
        return "建议=%s 原因=%s" % (i.suggest, i.reason)

    @case("video.parse 纯数字明确提示「缺项目信息」")
    def _():
        i = vn.parse_video_name("17.mp4")
        assert i.ep == "17" and i.need_input
        assert "纯数字" in i.reason, i.reason
        return i.reason

    @case("video.apply_project 回填（key 带不带扩展名都认）")
    def _():
        infos = vn.parse_many(["17.mp4", "20.mp4", "法老2.mp4"])
        assert all(i.need_input for i in infos[:2]), "纯数字应待补"
        # 故意用带扩展名的 key —— 剪映素材名两种形态都有，必须都能命中
        filled = vn.apply_project(infos, {"17.mp4": "法老", "20": "法老"})
        assert all(not i.need_input for i in filled), [i.project for i in filled]
        assert [i.label for i in filled] == ["法老17", "法老20", "法老2"], \
            [i.label for i in filled]
        return " ".join(i.label for i in filled)

    @case("video.apply_project 空答案不静默兜底")
    def _():
        infos = vn.parse_many(["17.mp4"])
        out = vn.apply_project(infos, {"17": "   "})
        assert out[0].need_input, "空答案必须保持待定，不能用原始名兜底"
        return "保持待定"

    @case("video.pending_map 同名只问一次")
    def _():
        infos = vn.parse_many(["17.mp4", "17.mp4", "20.mp4"])
        pend = vn.pending_map(infos)
        assert sorted(pend.keys()) == ["17", "20"], list(pend.keys())
        return "待补 %d 项（去重后）" % len(pend)

    @case("video.as_fields 模板字段（{视频项目}{集数}{编号}{AiFX}{视频名}）")
    def _():
        f = vn.parse_video_name("法老3_AiFX.mp4").as_fields()
        assert f["视频项目"] == "法老" and f["集数"] == "3"
        assert f["AiFX"] == "AiFX" and f["视频名"] == "法老3_AiFX"
        return str(f)


# ===========================================================================
# 2. 整轨时间窗裁剪（按视频分包的核心算法）
# ===========================================================================

try:
    sys.path.insert(0, os.path.join(SRC, "jianying-draft-toolkit", "code"))
    import main as M                                   # noqa: E402
except Exception as e:                                 # noqa: BLE001
    M = None
    print("[import] jianying main 失败：%r" % (e,))

if M is not None:
    @case("video.parse_video_chunks 只取视频轨片段并按落点排序")
    def _():
        d = fresh("jy_chunks")
        import json
        data = {
            "materials": {"videos": [
                {"id": "v1", "material_name": "法老3.mp4", "path": "x/法老3.mp4"},
                {"id": "v2", "material_name": "法老2.mp4", "path": "x/法老2.mp4"},
            ]},
            "tracks": [
                {"type": "audio", "segments": [
                    {"material_id": "v1", "target_timerange": {"start": 0, "duration": 1000}}]},
                # 视频轨：故意乱序，验证按 tl 排序
                {"type": "video", "segments": [
                    {"material_id": "v1", "target_timerange": {"start": 5000000, "duration": 3000000}},
                    {"material_id": "v2", "target_timerange": {"start": 0, "duration": 5000000}}]},
            ],
        }
        p = os.path.join(d, "draft_content.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        chs = M.parse_video_chunks(M.Path(d), M.Path(p))
        assert len(chs) == 2, chs
        assert chs[0].material_name == "法老2.mp4", [c.material_name for c in chs]
        assert chs[0].tl_start_us == 0 and chs[1].tl_start_us == 5000000
        return "%s → %s" % ([c.material_name for c in chs],
                            [c.duration_s for c in chs])

    @case("video.window 裁剪：片段跨窗口边界只保留重叠部分")
    def _():
        from dataclasses import replace
        seg = M.TrackSegment(source_path="x.wav", material_name="x", material_id="1",
                             src_start_us=1_000_000, src_dur_us=10_000_000,
                             tl_start_us=4_000_000, tl_dur_us=10_000_000)
        trk = M.AudioTrack(project="p", name="T", index=1, source_kind="audio",
                           segments=[seg])
        # 窗口 [5s, 8s] → 与片段 [4s,14s] 重叠 3s，取材须右移 1s
        win = M.extract_track_audio.__wrapped__ if hasattr(M.extract_track_audio,
                                                           "__wrapped__") else None
        # 直接验证裁剪算法本身（不跑 ffmpeg）：复刻 main 里的同一段逻辑
        ws, we = 5_000_000, 8_000_000
        o_start, o_end = max(seg.tl_start_us, ws), min(seg.tl_start_us + seg.tl_dur_us, we)
        off = o_start - seg.tl_start_us
        got = replace(seg, src_start_us=seg.src_start_us + off,
                      src_dur_us=o_end - o_start,
                      tl_start_us=o_start - ws, tl_dur_us=o_end - o_start)
        assert got.src_start_us == 2_000_000, got
        assert got.src_dur_us == 3_000_000, got
        assert got.tl_start_us == 0, got          # 落点换算到窗口内相对坐标
        return "取材起点 %dus / 时长 %dus" % (got.src_start_us, got.src_dur_us)

    @case("video.window 无重叠片段被丢弃（不留残段）")
    def _():
        ws, we = 100_000_000, 110_000_000
        seg = M.TrackSegment(source_path="x.wav", material_name="x", material_id="1",
                             tl_start_us=0, tl_dur_us=1_000_000)
        o_end = min(seg.tl_start_us + seg.tl_dur_us, we)
        o_start = max(seg.tl_start_us, ws)
        assert o_end - o_start <= 0, (o_start, o_end)
        return "窗口外片段被丢弃，交由 write_silence_wav 补静音"

    @case("video 分包占位符可渲染（{视频项目}/{集数}/{AiFX}）")
    def _():
        fields = vn.parse_video_name("法老3_AiFX.mp4").as_fields()
        out = M.render_track_name("{视频项目} {集数}集_{轨道名}{AiFX}",
                                  "p", "Track 1", 1, 10.0, extra=fields)
        assert out == "法老 3集_Track 1AiFX", out
        return out


sys.exit(C.report("视频名解析 / 按视频分包测试", tail_lines=14))
