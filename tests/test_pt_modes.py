# -*- coding: utf-8 -*-
"""pt-tools v1.1.0 导出模式多选改造 · 专项回归（纯逻辑 + GUI 轻冒烟）

覆盖：
  - build_export_cmds 四模式（MIX/BUS/STEM/按轨道名称）单独与组合的命令构造
  - STEM 子选项（含效果辅助轨 aux → 白名单模式）
  - 校验链（空模式 / 未选轨 / 档案缺 output·bus / 时间格式 / 采样率 / 输出目录）
  - parse_video_duration_output（按视频填入的输出解析）
  - CmdWorker 命令队列（顺序执行 + 失败即停）
  - App/ExportTab 建窗与模式联动（轨道列表启停、aux 子项启停）

环境要求：带 tkinter 的解释器（_common.ensure_tk 自愈），无 Pro Tools 也能跑。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

C.ensure_tk()
import tkinter as tk                                   # noqa: E402

sys.path.insert(0, str(C.SRC / "pt-tools"))
import pt_tools_gui as pt                              # noqa: E402

run = C.run_case

# ── 档案夹具（结构对齐 pt_scan.py 产物）────────────────────────
PROFILE = {
    "session": {"name": "测试工程", "sample_rate": 48000, "bit_depth": "24",
                "timecode_rate": "25", "length": "00:02:00:00"},
    "sources": {
        "bus": ["DX-BUS-Master", "MX-BUS-Master"],
        "output": ["MX-BUS-Master"],
        "physicalout": ["输出 1-2"],
    },
    "tracks": [
        {"name": "DX 1", "type": "audio",
         "attributes": {"contains_clips": True}},
        {"name": "DX VO", "type": "audio",
         "attributes": {"contains_clips": False}},
        {"name": "DX Room Verb", "type": "aux",
         "attributes": {"contains_clips": False}},
        {"name": "Master Hole", "type": "master"},
        {"name": "DX VCA", "type": "vca"},
    ],
}

PY = "PY.EXE"
SCRIPT = "pt_export.py"
BASE = dict(out=r"D:\out", start="00:00:00:00", end="00:02:00:00")


def _build(**kw):
    """统一入口：填默认参数后调 build_export_cmds。"""
    params = dict(venv_python=PY, script_path=SCRIPT,
                  profile_path="pt-profile.json", profile=PROFILE)
    params.update(BASE)
    params.update(kw)
    return pt.build_export_cmds(**params)


def _flags(cmd, flag):
    """命令里某开关的出现次数。"""
    return sum(1 for x in cmd if x == flag)


def _val(cmd, flag):
    """某开关后的值（取最后一次出现）。"""
    idx = len(cmd) - 1 - cmd[::-1].index(flag)
    return cmd[idx + 1]


# ── 单模式命令构造 ────────────────────────────────────────────
def mix_only():
    cmds = _build(modes=["mix"])
    assert len(cmds) == 1, cmds
    c = cmds[0]
    assert c[2] == "--profile" and c[3] == "pt-profile.json", c[:5]
    assert c[4] == "mix", c[:6]          # --profile 必须在子命令前（§8.3 老坑）
    assert _flags(c, "--source") == 1    # 档案 output 1 条
    assert _val(c, "--source-type") == "output"
    assert "--all-tracks" not in c and "--dry-run" not in c
    return "1 条 mix 命令，source=output 列表"


run("MIX 模式 → ExportMix(output) 单命令", mix_only)


def bus_only():
    cmds = _build(modes=["bus"])
    c = cmds[0]
    assert len(cmds) == 1 and c[4] == "mix", cmds
    assert _flags(c, "--source") == 2    # 档案 bus 2 条
    assert _val(c, "--source-type") == "bus"
    return "1 条 mix 命令，--source ×2（逐 bus 落文件）"


run("BUS 模式 → ExportMix(bus) 全总线", bus_only)


def stem_default():
    cmds = _build(modes=["stem"])
    c = cmds[0]
    assert len(cmds) == 1 and c[4] == "stems", cmds
    assert _val(c, "--source-type") == "track"
    assert _flags(c, "--all-tracks") == 1
    assert _flags(c, "--skip-buses") == 1
    assert _flags(c, "--exclude-empty") == 1
    assert "--track-type" not in c
    return "stems --all-tracks --skip-buses --exclude-empty"


run("STEM 默认 → 全轨但排除总线类/空轨", stem_default)


def stem_with_aux():
    cmds = _build(modes=["stem"], stem_aux=True)
    c = cmds[0]
    assert "--skip-buses" not in c, c
    types = [c[i + 1] for i, x in enumerate(c) if x == "--track-type"]
    assert types == ["audio", "aux", "instrument", "midi"], types
    assert _flags(c, "--exclude-empty") == 1
    return "白名单 %s（aux 进、master/vca/folder 仍排除）" % types


run("STEM 含 aux → --track-type 白名单", stem_with_aux)


def track_by_name():
    cmds = _build(modes=["track"], tracks=["DX 1", "Master Hole"])
    c = cmds[0]
    assert len(cmds) == 1 and c[4] == "stems", cmds
    assert _val(c, "--source-type") == "track"
    assert "--all-tracks" not in c
    names = [c[i + 1] for i, x in enumerate(c) if x == "--source"]
    assert names == ["DX 1", "Master Hole"], names
    return "--source ×%d 按轨道名称" % len(names)


run("按轨道名称 → BounceTrack 指定轨", track_by_name)


def track_unknown_name():
    try:
        _build(modes=["track"], tracks=["不存在的轨"])
    except ValueError as exc:
        assert "tracks" in str(exc) or "轨道" in str(exc), exc
        return "未知轨名被拦截：%s" % exc
    raise AssertionError("未知轨名未拦截")


run("按轨道名称 · 未知轨名 → ValueError", track_unknown_name)


def multi_mode_order():
    cmds = _build(modes=["mix", "bus", "stem", "track"],
                  tracks=["DX 1"])
    subs = [c[4] for c in cmds]
    assert subs == ["mix", "mix", "stems", "stems"], subs
    assert all(c[2] == "--profile" for c in cmds)
    return "4 条命令顺序 %s（MIX→BUS→STEM→TRACK）" % subs


run("多选组合 → 命令队列顺序正确", multi_mode_order)


def dry_run_flag():
    cmds = _build(modes=["mix", "stem"], dry_run=True)
    assert all(_flags(c, "--dry-run") == 1 for c in cmds)
    return "每条命令均带 --dry-run"


run("dry-run 标志透传到每条命令", dry_run_flag)


def session_passthrough():
    cmds = _build(modes=["mix"], session=r"D:\proj\誓言24.ptx")
    assert _val(cmds[0], "--session") == r"D:\proj\誓言24.ptx"
    cmds = _build(modes=["mix"], session=None)
    assert "--session" not in cmds[0]
    return "指定文件模式透传 --session，当前打开模式不传"


run("session 参数透传", session_passthrough)


# ── 校验链 ────────────────────────────────────────────────────
def expect_err(fn, *keywords):
    try:
        fn()
    except ValueError as exc:
        msg = str(exc)
        assert any(k in msg for k in keywords), "消息不匹配：%s" % msg
        return msg
    raise AssertionError("应抛 ValueError 而未抛")


def v_empty_modes():
    return expect_err(lambda: _build(modes=[]), "至少", "at least")


run("校验 · 未勾任何模式", v_empty_modes)


def v_track_no_pick():
    return expect_err(lambda: _build(modes=["track"], tracks=[]),
                      "按轨道名称", "track")


run("校验 · 勾按轨道名称但未选轨", v_track_no_pick)


def v_no_output():
    prof = {**PROFILE, "sources": {**PROFILE["sources"], "output": []}}
    return expect_err(lambda: _build(profile=prof, modes=["mix"]),
                      "output", "输出")


run("校验 · 档案无 output 而 MIX 被勾", v_no_output)


def v_no_bus():
    prof = {**PROFILE, "sources": {**PROFILE["sources"], "bus": []}}
    return expect_err(lambda: _build(profile=prof, modes=["bus"]),
                      "bus", "总线")


run("校验 · 档案无 bus 而 BUS 被勾", v_no_bus)


def v_tc_format():
    return expect_err(lambda: _build(modes=["mix"], start="0:0:0:0"),
                      "HH:MM:SS:FF")


run("校验 · 时间格式错误", v_tc_format)


def v_end_le_start():
    return expect_err(lambda: _build(modes=["mix"], end="00:00:00:00"),
                      "晚于", "later")


run("校验 · End 不晚于 Start", v_end_le_start)


def v_end_le_start_fps():
    # 29.97 DF 之类浮点帧率也要能比较（timecode_rate 取 "29.97 DF" 首段）
    prof = {**PROFILE, "session": {**PROFILE["session"],
                                   "timecode_rate": "29.97 DF"}}
    return expect_err(lambda: _build(profile=prof, modes=["mix"],
                                     end="00:00:00:00"),
                      "晚于", "later")


run("校验 · 浮点帧率下 End<=Start 仍拦截", v_end_le_start_fps)


def v_out_missing():
    return expect_err(lambda: _build(modes=["mix"], out="  "),
                      "输出", "output")


run("校验 · 输出目录为空", v_out_missing)


def v_sr_bad():
    return expect_err(lambda: _build(modes=["mix"], sample_rate="48k"),
                      "采样率", "rate")


run("校验 · 采样率非法", v_sr_bad)


def v_no_profile():
    return expect_err(lambda: _build(profile=None, modes=["mix"]),
                      "档案", "profile")


run("校验 · 未加载档案", v_no_profile)


# ── 视频时长解析 ──────────────────────────────────────────────
def video_parse_ok():
    line = (r"D:\video\ep1.mp4: 118.53s (1:58)"
            " -> 00:01:58:13  @25fps")
    assert pt.parse_video_duration_output(line) == "00:01:58:13"
    multi = ("a.mp4: 10.00s (0:10) -> 00:00:10:00 @25fps\n"
             "b.mp4: 20.00s (0:20) -> 00:00:20:00 @25fps\n")
    assert pt.parse_video_duration_output(multi) == "00:00:10:00"  # 取首个
    return "正则取 `-> HH:MM:SS:FF` 首个命中"


run("parse_video_duration_output 正例", video_parse_ok)


def video_parse_fail():
    assert pt.parse_video_duration_output("") is None
    assert pt.parse_video_duration_output("[error] cannot parse: x.mp4") is None
    assert pt.parse_video_duration_output(None) is None
    return "空/错误输出 → None"


run("parse_video_duration_output 负例", video_parse_fail)


# ── CmdWorker 命令队列 ────────────────────────────────────────
def worker_queue_ok():
    import queue
    q = queue.Queue()
    done_file = os.path.join(C.fresh("pt_modes_worker"), "second.done")
    cmds = [
        [sys.executable, "-c", "print('first-ok')"],
        [sys.executable, "-c",
         "import sys; print('second-ok'); "
         "open(sys.argv[1], 'w').write('done')", done_file],
    ]
    w = pt.CmdWorker(cmds, q)
    w.start()
    w.join(timeout=120)
    items = []
    while not q.empty():
        items.append(q.get())
    kinds = [k for k, _v in items]
    done = [v for k, v in items if k == "done"]
    text = "\n".join(str(v) for k, v in items if k == "line")
    assert kinds.count("done") == 1, kinds
    assert done == [0], done
    assert "first-ok" in text and "second-ok" in text, text
    assert os.path.isfile(done_file), "第二条命令未执行"
    assert "[1/2]" in text and "[2/2]" in text, "缺分节标记"
    return "两条顺序执行，done=0，分节标记齐全"


run("CmdWorker 队列 · 两条全成", worker_queue_ok)


def worker_fail_fast():
    import queue
    q = queue.Queue()
    done_file = os.path.join(C.fresh("pt_modes_worker2"), "never.done")
    cmds = [
        [sys.executable, "-c",
         "import sys; print('boom'); sys.exit(3)"],
        [sys.executable, "-c",
         "import sys; open(sys.argv[1], 'w').write('x')", done_file],
    ]
    w = pt.CmdWorker(cmds, q)
    w.start()
    w.join(timeout=120)
    items = []
    while not q.empty():
        items.append(q.get())
    done = [v for k, v in items if k == "done"]
    text = "\n".join(str(v) for k, v in items if k == "line")
    assert done == [3], done
    assert "boom" in text
    assert not os.path.isfile(done_file), "失败后不应继续执行剩余命令"
    assert "跳过" in text or "skipped" in text, "缺失败停机提示"
    return "首条失败 done=3，剩余命令被跳过"


run("CmdWorker 队列 · 失败即停", worker_fail_fast)


def worker_single_compat():
    """单命令（list[str] 而非 list[list[str]]）仍兼容 —— ScanTab 路径。"""
    import queue
    q = queue.Queue()
    w = pt.CmdWorker([sys.executable, "-c", "print('solo-ok')"], q)
    w.start()
    w.join(timeout=60)
    items = []
    while not q.empty():
        items.append(q.get())
    done = [v for k, v in items if k == "done"]
    text = "\n".join(str(v) for k, v in items if k == "line")
    assert done == [0] and "solo-ok" in text, (done, text)
    return "单命令自动包装，done=0"


run("CmdWorker 单命令兼容", worker_single_compat)


# ── GUI 轻冒烟：建窗 + 模式联动 ───────────────────────────────
def gui_modes():
    app = pt.App()
    try:
        tab = app.export_tab
        # 出厂默认：MIX + STEM 勾选，BUS/TRACK 未勾
        assert tab._mode_on("mix") and tab._mode_on("stem"), "出厂默认勾选错误"
        assert not tab._mode_on("bus") and not tab._mode_on("track")
        # v1.2.0 勾选式选轨语义：STEM 或「按轨道名称」任一勾选 → 轨道列表可交互
        # （STEM 勾选轨 = 只导勾选的；全不勾 = 全轨模式）。出厂默认 STEM 已勾
        # → 列表与 aux 子项都应可用。⚠️ 旧断言写的是 v1.1.0 语义（TRACK 不勾
        # 就禁用），v1.2.0 改勾选式后未同步；v2.6.2 轮无法带 tkinter 跑全量，
        # 此项 FAIL 一直未暴露（2026-09-24 修正为现行语义）。
        assert "disabled" not in tab.src_tree.state(), tab.src_tree.state()
        assert "disabled" not in tab.cb_stem_aux.state()
        # STEM / TRACK 全不勾 → 列表与 aux 子项禁用；勾 TRACK → 列表恢复
        tab.mode_stem_var.set("0")
        assert "disabled" in tab.src_tree.state(), tab.src_tree.state()
        assert "disabled" in tab.cb_stem_aux.state()
        tab.mode_track_var.set("1")
        assert "disabled" not in tab.src_tree.state()
        tab.mode_track_var.set("0")
        tab.mode_stem_var.set("1")      # 复原联动测试的勾选，回到默认 MIX+STEM
        # 无档案时 _build_cmds 报「未加载档案」
        try:
            tab._build_cmds(dry_run=True)
            raise AssertionError("无档案应抛 ValueError")
        except ValueError as exc:
            assert "档案" in str(exc) or "profile" in str(exc), exc
        # 塞入档案后（对齐真实流程：加载档案会自动填 end=会话长度）：
        # 默认 MIX+STEM → 2 条命令 dry-run
        tab.end_var.set("00:02:00:00")
        if not tab.out_var.get().strip():
            tab.out_var.set(r"D:\pt-modes-test-out")
        tab._profile_path = "pt-profile.json"
        tab._profile = PROFILE
        tab._reload_sources()           # 真实流程由 _load_profile 触发，此处手动补
        cmds = tab._build_cmds(dry_run=True)
        assert [c[4] for c in cmds] == ["mix", "stems"], cmds
        # 按轨道名称：勾选 + 选中轨（模拟 selection）
        tab.mode_track_var.set("1")
        kids = tab.src_tree.get_children()
        assert kids, "轨道列表未填充"
        tab.src_tree.selection_set(kids[0])
        cmds = tab._build_cmds(dry_run=False)
        assert len(cmds) == 3, cmds           # mix + stems + track
        # 预览失效闸门：改参数后签名变化可被检出
        sig_a = tab._param_signature()
        tab.end_var.set("00:01:30:00")
        assert tab._param_signature() != sig_a, "参数变化未反映到签名"
        return "建窗/联动/_build_cmds/签名 全通过"
    finally:
        app.destroy()
    time.sleep(0)  # noqa — 保持 import 整洁（time 仅在需要时使用）


run("App/ExportTab 建窗 + 模式联动 + 命令构造", gui_modes)


sys.exit(C.report("pt-tools v1.1.0 导出模式专项测试"))
