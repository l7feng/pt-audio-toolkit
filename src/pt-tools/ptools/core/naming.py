# -*- coding: utf-8 -*-
"""timecode 换算 / 档案读取 / 导出模式→CLI（W1 三层拆分 · core/naming）。

纯逻辑层（不 import tkinter）：GUI 与回归测试共用，shell 不动芯。
"""
import json
import os
import re

from .i18n import T
from .settings import (
    DEFAULT_EXPORT_FORMAT, EXPORT_FORMATS, EXPORT_MODES,
    FORMAT_LABEL_KEYS, TC_RE,
)

# ---------------------------------------------------------------------------
# 共享工具（timecode 校验 / profile 读取）
# ---------------------------------------------------------------------------

def tc_to_frame(tc, fps):
    h, m, s, f = (int(x) for x in tc.split(":"))
    return ((h * 3600 + m * 60 + s) * fps) + f


def frame_to_tc(frames, fps):
    """帧号 → HH:MM:SS:FF（v1.2.0：视频时长 + 余量换算结束时间用）。"""
    fps = max(int(round(fps)), 1)
    f = int(round(frames)) % fps
    total = int(round(frames)) // fps
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%02d:%02d" % (h, m, s, f)


def fmt_tc_ok(tc):
    return bool(TC_RE.match(tc or ""))


# ---------------------------------------------------------------------------
# 导出格式：内部 key ⇄ 本地化显示名（v1.3.0）
# ---------------------------------------------------------------------------

def fmt_label(key):
    """内部 key → 显示名。未知 key 原样返回（便于排查，不静默吞掉）。"""
    lk = FORMAT_LABEL_KEYS.get(key)
    return T(lk) if lk else key


def fmt_choices():
    """下拉选项（显示名列表，顺序 = EXPORT_FORMATS）。"""
    return [fmt_label(k) for k in EXPORT_FORMATS]


def fmt_key_of(value):
    """显示名 / 内部 key → 内部 key。

    识别不了返回 **None** —— 调用方必须显式报错。
    ⚠️ 这里绝不静默回落到默认值：v2.6.1 剪映侧 `_read_spec` 就是"取首 token
    当 key、查不到就回落默认且不报错"，用户以为选了 A 实际导出的是 B。
    """
    v = (value or "").strip()
    if v in FORMAT_LABEL_KEYS:
        return v
    for k, lk in FORMAT_LABEL_KEYS.items():
        if v == T(lk):
            return k
    return None


def fmt_display_of(value):
    """把可能是内部 key 的旧配置值，规整成显示名（启动时回填 UI 用）。"""
    k = fmt_key_of(value)
    return fmt_label(k) if k else fmt_label(DEFAULT_EXPORT_FORMAT)


def load_profile(path):
    """读取并校验 pt-profile.json，失败抛 ValueError"""
    if not path or not os.path.isfile(path):
        raise ValueError(T("msg_profile_invalid") + "：%s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("session", "sources", "tracks"):
        if key not in data:
            raise ValueError("档案缺少字段 `%s`，可能是旧版档案，请重新扫描" % key)
    return data


def open_in_explorer(path):
    if path and os.path.isdir(path):
        os.startfile(path)  # noqa  Windows only
        return True
    return False


# ---------------------------------------------------------------------------
# 导出模式 → CLI 命令序列（v1.1.0 · 纯逻辑，GUI 与回归测试共用）
# ---------------------------------------------------------------------------

# 模式 → 子命令与来源
#   MIX  : ExportMix 主输出（sources.output）整段并轨，1 个文件
#   BUS  : ExportMix 全部总线（sources.bus），每条 1 个文件
#   STEM : BounceTrack 全部轨道（--all-tracks），默认排除总线类轨 + 空轨；
#          stem_aux=True 时改白名单（audio/aux/instrument/midi），含效果辅助轨
#   TRACK: BounceTrack 指定轨道名（用户从档案轨道列表挑选）
def _group_by_format(names, default_fmt, track_formats):
    """把轨道按「有效导出格式」分组 → [(fmt, [轨道名…]), …]

    v1.3.0（Q5）：声道/格式应在**每条轨道**上选，而不是一个下拉控制整个列表。
    每条轨道可覆盖全局，未覆盖的沿用全局。`--format` 是**命令级**参数，
    所以同格式的轨并成一条命令，不同格式各跑一条。
    """
    buckets = {}
    for n in names:
        f = (track_formats or {}).get(n) or default_fmt
        f = fmt_key_of(f) or default_fmt
        buckets.setdefault(f, []).append(n)
    return [(f, buckets[f]) for f in EXPORT_FORMATS if f in buckets]


def build_export_cmds(venv_python, script_path, profile_path, profile, *,
                      modes, stem_aux=False, tracks=(), session=None,
                      out="", start="", end="", sample_rate="48000",
                      bit_depth="24", fmt=DEFAULT_EXPORT_FORMAT, dry_run=False,
                      stem_tracks=(), exclude_names=(), track_formats=None,
                      exclude_empty=True):
    """按勾选的导出模式构造 CLI 命令列表（顺序 MIX → BUS → STEM → TRACK）。

    壳不动芯：每条命令独立调一次 pt_export.py（各自连接 PTSL，顺序执行，
    该链路已在批量编排中实测连续连接/导出可行）。校验失败抛 ValueError
    （消息已本地化，GUI 直接弹框、测试直接断言）。
    ⚠️ --profile 是全局参数，必须位于子命令之前（§8.3 老坑，勿挪）。

    v1.2.0：`stem_tracks` 非空时 STEM 改为**只导勾选轨**（--source 列表，
    名字级精确导出）；为空时保持 --all-tracks 全轨模式。
    `exclude_names` 透传 --exclude-name（精确 + * ? 通配）。

    v1.3.0：`fmt` 默认改 `interleaved`（旧默认 `mono` 会静默下混立体声）；
    识别不了的格式**显式报错**而不是回落默认。`track_formats` 支持每条轨道
    单独指定格式（{"轨名": "mono"}），相同格式并成一条命令。
    """
    if not profile:
        raise ValueError(T("msg_no_profile"))
    modes = [m for m in EXPORT_MODES if m in (modes or [])]
    if not modes:
        raise ValueError(T("msg_no_mode"))

    # 通用参数校验（时间 / 输出 / 采样率）
    if not fmt_tc_ok(start) or not fmt_tc_ok(end):
        raise ValueError(T("msg_tc_bad"))
    try:
        fps = float(str(profile["session"].get("timecode_rate") or "25").split()[0])
    except (ValueError, TypeError, AttributeError):
        fps = 25.0
    if tc_to_frame(end, fps) <= tc_to_frame(start, fps):
        raise ValueError(T("msg_end_le"))
    if not (out or "").strip():
        raise ValueError(T("msg_out_missing"))
    try:
        int(sample_rate)
    except (TypeError, ValueError):
        raise ValueError(T("msg_sr_bad"))

    # v1.3.0：格式值必须可识别，识别不了直接报错（绝不静默回落）
    _fmt = fmt_key_of(fmt)
    if _fmt is None:
        raise ValueError(T("msg_fmt_bad") % fmt)

    base = ["--out", out, "--start", start, "--end", end,
            "--sample-rate", str(sample_rate), "--bit-depth", str(bit_depth)]
    if session:
        base += ["--session", session]
    if dry_run:
        base += ["--dry-run"]

    def common_with(f):
        return base + ["--format", f]

    common = common_with(_fmt)

    srcs = profile.get("sources", {})
    cmds = []
    for m in modes:
        if m == "mix":
            outs = srcs.get("output") or []
            if not outs:
                raise ValueError(T("msg_no_output_src"))
            cmd = [venv_python, script_path, "--profile", profile_path, "mix"]
            for name in outs:
                cmd += ["--source", name]
            cmds.append(cmd + ["--source-type", "output"] + common)
        elif m == "bus":
            buses = srcs.get("bus") or []
            if not buses:
                raise ValueError(T("msg_no_bus_src"))
            cmd = [venv_python, script_path, "--profile", profile_path, "mix"]
            for name in buses:
                cmd += ["--source", name]
            cmds.append(cmd + ["--source-type", "bus"] + common)
        elif m == "stem":
            picked_stem = [t for t in (stem_tracks or ()) if t]
            if picked_stem:
                # 勾选式 STEM：只导勾选轨（按档案顺序，名字必须存在于档案）。
                # v1.3.0：按每条轨道的格式分组，不同格式各出一条命令。
                known = {t.get("name", "") for t in profile.get("tracks", [])}
                for name in picked_stem:
                    if name not in known:
                        raise ValueError(T("msg_src_unknown") % (name, "tracks"))
                excl = [str(x).strip() for x in (exclude_names or ()) if str(x).strip()]
                for f, names in _group_by_format(picked_stem, _fmt, track_formats):
                    cmd = [venv_python, script_path, "--profile", profile_path,
                           "stems", "--source-type", "track"]
                    for name in names:
                        cmd += ["--source", name]
                    for name in excl:
                        cmd += ["--exclude-name", name]
                    cmds.append(cmd + common_with(f))
            else:
                # 未勾选任何轨 → 全轨模式（--all-tracks），沿用旧语义
                cmd = [venv_python, script_path, "--profile", profile_path,
                       "stems", "--source-type", "track", "--all-tracks"]
                if stem_aux:
                    # 含效果辅助轨：白名单模式（aux 进来，master/vca/folder 仍排除）
                    for t in ("audio", "aux", "instrument", "midi"):
                        cmd += ["--track-type", t]
                else:
                    cmd += ["--skip-buses"]
                if exclude_empty:
                    cmd += ["--exclude-empty"]
                for name in (exclude_names or ()):
                    if name and str(name).strip():
                        cmd += ["--exclude-name", str(name).strip()]
                cmds.append(cmd + common)
        elif m == "track":
            names = [t for t in (tracks or []) if t]
            if not names:
                raise ValueError(T("msg_no_track_sel"))
            known = {t.get("name", "") for t in profile.get("tracks", [])}
            for name in names:
                if name not in known:
                    raise ValueError(T("msg_src_unknown") % (name, "tracks"))
            for f, group in _group_by_format(names, _fmt, track_formats):
                cmd = [venv_python, script_path, "--profile", profile_path,
                       "stems", "--source-type", "track"]
                for name in group:
                    cmd += ["--source", name]
                cmds.append(cmd + common_with(f))
        else:  # pragma: no cover — EXPORT_MODES 已约束
            raise ValueError("unknown mode: %s" % m)
    return cmds


TC_OUT_RE = re.compile(r"->\s*(\d{2}:\d{2}:\d{2}:\d{2})")


def parse_video_duration_output(text):
    """从 video_duration.py 输出解析 HH:MM:SS:FF（取第一个 `-> TC`）；失败返回 None。"""
    m = TC_OUT_RE.search(text or "")
    return m.group(1) if m else None
