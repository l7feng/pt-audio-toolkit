#!/usr/bin/env python3
r"""
pt_export.py — Pro Tools 无界面导出工具（基于 PTSL / py-ptsl）

功能：
  - 并轨混音（mix）：按 bus / 主输出整段 bounce，实时渲染插件与自动化
  - 分轨导出（stems）：对多个 bus 分别 bounce，每个 source 一个 WAV 文件
  - **按轨道导出（--source-type track）**：对单个轨道（audio/aux/master/folder…）
    走 BounceTrack 命令，每条轨一个 WAV——这是 Studio One「Export Stems Tracks」
    的等价能力，对应 PT 右键轨道 > Bounce（Shift+Opt+Cmd+B）
  - dry-run：只打印将执行的操作清单，不真正导出（安全预览）

两条命令线（2026-09-17 实测厘清）：
  ┌ ExportMix（CId 28）＝ PT 菜单 File > Bounce Mix  → 路径制（bus/output/physicalout）
  └ BounceTrack（CId 134）＝ PT 右键轨道 > Bounce     → 轨道制（src_track_id）

  ⚠ BounceTrack 三个坑（均实测踩过）：
    1. track id 必须带花括号 `{00000000-2a000000-…}`，去括号报
       `Could not parse Sys_TrackUID`
    2. 导出区间**唯一来源是 set_timeline_selection**；传 in_location/out_location
       会报「由于时间轴上没有内容」
    3. 选区为空同样报该错 → 轨道模式强制先设选区


通用化（2026-09-15 E2 改造）：
  - 不再依赖任何硬编码 source 名/路径/帧率——工程信息从 pt-profile.json 读取
    （profile 由 pt-scanner 生成，含可用 source 列表、session 时码率等）
  - --profile 可选；给了则校验 source 名 + 打印 session 摘要（环境探测步骤）
  - --dry-run 走完整流程直到导出前一步，适合 agent 先预览再确认

前提：Pro Tools 已启动并加载工程，PTSL 监听 localhost:31416。

示例：
  # 先有 profile（pt-scanner 生成）：
  #  dry-run 预览
  python pt_export.py mix --profile pt-profile.json \
      --source "Master Hole" --source-type Output \
      --out "D:\out" --start 00:00:00:00 --end 00:02:00:00 --realtime --dry-run

  # 实际导出（并轨，整段带插件实时渲染）
  python pt_export.py mix --profile pt-profile.json \
      --source "Master Hole" --source-type Output \
      --out "D:\out" --start 00:00:00:00 --end 00:02:00:00 --realtime

  # 分轨：DX / MX 两个 bus 各出一个 WAV
  python pt_export.py stems --profile pt-profile.json \
      --source "DX-BUS-Master" --source "MX-BUS-Master" --source-type Bus \
      --out "D:\out" --start 00:00:00:00 --end 00:02:00:00 --realtime

  # 无 profile 也可用：但 source 名必须是你确信的（不推荐，先扫）
  python pt_export.py stems \
      --source "DX-BUS-Master" --source-type Bus \
      --out "D:\out" --start 00:00:00:00 --end 00:02:00:00

  # 按轨道导出（BounceTrack）：把某几根轨各导成一个 WAV
  python pt_export.py stems --profile pt-profile.json \
      --source "DX 1" --source "Audio FX ST.dup1" --source-type track \
      --out "D:\out" --start 00:00:00:00 --end 00:01:58:13

  # 按轨道批量：导出工程里所有「含音频块」的非总线轨道（排除 aux/master/folder/vca）
  python pt_export.py stems --profile pt-profile.json \
      --source-type track --all-tracks --skip-buses \
      --out "D:\out" --start 00:00:00:00 --end 00:01:34:07
"""

import argparse
import json
import os
import sys
from ptsl import Engine
from ptsl import PTSL_pb2 as pb
from ptsl.ops import Operation

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


class CId_BounceTrack(Operation):
    """PT 右键轨道 > Bounce（轨道制）。py-ptsl 602.0.0 未封装 CId 上的 op，
    但 proto 里已有 BounceTrackRequestBody/ResponseBody，故此处只做类名绑定，
    请求/响应体与命令号由 Operation 自动推导。"""
    pass

# ── 枚举速查 ──────────────────────────────────────────────────────────
FILE_TYPE = {"wav": pb.EM_WAV, "aiff": pb.EM_AIFF}
SAMPLE_RATE = {48000: pb.SRate_48000, 44100: pb.SRate_44100,
               96000: pb.SRate_96000}
BIT_DEPTH = {16: pb.Bit16, 24: pb.Bit24, 32: pb.Bit32Float}
SOURCE_TYPE = {"bus": pb.EMSType_Bus, "output": pb.EMSType_Output,
               "physicalout": pb.EMSType_PhysicalOut}
# "track" 不是 EMSType 成员——它走 BounceTrack 命令，单列处理（见 run()）
SOURCE_TYPE_CHOICES = ["bus", "output", "physicalout", "track"]
EXPORT_FORMAT = {"mono": pb.EFormat_Mono, "interleaved": pb.EFormat_Interleaved,
                 "multiple-mono": pb.EFormat_MultipleMono}
SR_STR = {pb.SRate_48000: "48000", pb.SRate_44100: "44100",
          pb.SRate_96000: "96000"}

# ── 轨道类型速查（BounceTrack 用）─────────────────────────────────────
# PT 工程内的「总线类」轨道：有汇总信号、无自身素材，逐轨导出通常无意义
BUS_LIKE_TYPES = {pb.TType_Aux, pb.TType_Master, pb.TType_Vca,
                  pb.TType_RoutingFolder, pb.TType_BasicFolder}
# 有素材、值得逐轨导出的类型
STEM_ELIGIBLE_TYPES = {pb.TType_Audio, pb.TType_Instrument, pb.TType_Midi}
TRACK_TYPE_NAME = {
    pb.TType_Audio: "audio", pb.TType_Aux: "aux",
    pb.TType_Master: "master", pb.TType_Vca: "vca",
    pb.TType_RoutingFolder: "routing-folder",
    pb.TType_BasicFolder: "basic-folder",
    pb.TType_Instrument: "instrument", pb.TType_Midi: "midi",
    pb.TType_Video: "video",
}


def track_type_name(ttype):
    return TRACK_TYPE_NAME.get(ttype, "type-%d" % ttype)


def load_profile(path):
    """读取 pt-profile.json；缺字段时返回 {} 而不是报错。"""
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[warn] profile 读取失败（{exc}），跳过校验", file=sys.stderr)
        return {}


def build_audio_info(args):
    return pb.EM_AudioInfo(
        compression_type=pb.CType_PCM,
        export_format=EXPORT_FORMAT[args.format],
        bit_depth=BIT_DEPTH[args.bit_depth],
        sample_rate=SAMPLE_RATE[args.sample_rate],
        pad_to_frame_boundary=pb.TBool_False,
        delivery_format=pb.EM_DF_FilePerMixSource,
    )


def build_video_info():
    return pb.EM_VideoInfo(
        include_video=pb.TBool_False,
        export_option=pb.VE_None,
        replace_timecode_track=pb.TBool_False,
    )


def build_location(out_dir):
    return pb.EM_LocationInfo(
        import_after_bounce=pb.TBool_False,
        file_destination=pb.EM_FD_Directory,
        directory=os.path.normpath(out_dir) + "\\",
    )


def run_with_timeout(fn, timeout, what, hint=None):
    """把可能因 PT 模态弹窗而无限挂起的 PTSL 调用包成带超时的调用。
    超时即 fail-fast 退出（exit 1），不静默卡死。"""
    import threading
    result = {}

    def _call():
        try:
            fn()
            result["ok"] = True
        except Exception as exc:
            result["err"] = exc

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print("[error] %s 超过 %.0f 秒未返回：Pro Tools 可能弹出了模态对话框"
              "（如「视频丢失 / 媒体丢失」查找框），阻塞了 PTSL。\n"
              "        请在桌面端处理该弹窗后重试；或把 Video 轨设为离线"
              "（Take Video Offline）再跑。" % (what, timeout),
              file=sys.stderr)
        if hint:
            print("        " + hint, file=sys.stderr)
        sys.exit(1)
    if "err" in result:
        raise result["err"]


# ── BounceTrack（轨道制）───────────────────────────────────────────────
def list_tracks(pt, timeout=15.0):
    """取工程轨道列表。返回 {name: Track} 与按索引排序的列表。"""
    box = {}

    def _get():
        box["tracks"] = list(pt.track_list())

    run_with_timeout(_get, timeout, "track_list", "工程可能未完全加载。")
    tracks = box.get("tracks", [])
    by_name = {}
    for t in tracks:
        by_name[t.name] = t
    return tracks, by_name


def select_tracks(tracks, args):
    """按 --source / --all-tracks / --skip-buses / --track-type 组合挑出目标轨。"""
    picked = []
    reasons = []

    if args.all_tracks:
        for t in tracks:
            if t.type == pb.TType_Video:
                continue
            if args.skip_buses and t.type in BUS_LIKE_TYPES:
                continue
            if args.track_type and track_type_name(t.type) not in args.track_type:
                continue
            picked.append(t)
    else:
        by_name = {t.name: t for t in tracks}
        missing = []
        for name in args.source:
            t = by_name.get(name)
            if t is None:
                missing.append(name)
            else:
                picked.append(t)
        if missing:
            reasons.append("以下轨道在工程中不存在：%s" % missing)
            cand = [t.name for t in tracks
                    if any(m.lower() in t.name.lower() for m in missing)]
            if cand:
                reasons.append("近似的轨道名（供核对）：%s" % cand[:12])
    return picked, reasons


def build_bounce_track(track_id, prefix, audio_info, location, realtime,
                       render_volume=True, render_pan=True):
    """构造 BounceTrack op。注意 track_id 必须保留花括号，区间靠选区而非 in/out。"""
    return CId_BounceTrack(
        preset_path="",
        file_name_prefix=prefix,
        file_type=pb.EM_WAV,
        audio_info=audio_info,
        location_info=location,
        offline_bounce=pb.TBool_False if realtime else pb.TBool_True,
        audio_encoding_options=pb.AudioEncodingOptions(),
        src_track_id=track_id,
        automation_options=pb.RenderAutomationOptions(
            render_volume_automation=render_volume,
            render_pan_automation=render_pan,
        ),
    )


def bounce_track_one(pt, op, realtime, timeout=600.0):
    """执行 BounceTrack；返回落盘文件路径列表。"""
    box = {}

    def _run():
        pt.client.run(op)
        box["paths"] = list(op.response.file_paths)

    run_with_timeout(_run, timeout, "BounceTrack（轨道导出）",
                     "轨道导出是离线 bounce，通常几秒内完成；"
                     "若整段很长或插件极重，可用 --bounce-timeout 放宽。")
    return box.get("paths", [])


def bounce_one(pt, source_name, source_type, base_name, audio_info,
               location, realtime, timeout=120.0):
    """执行 export_mix；PT 弹模态框（如视频丢失/媒体丢失）会令该调用无限挂起，
    用后台线程 + 超时令其 fail-fast，避免无提示卡死。"""
    import threading
    src = pb.EM_SourceInfo(source_type=source_type, name=source_name)
    result = {}

    def _bounce():
        try:
            pt.export_mix(
                base_name=base_name,
                file_type=pb.EM_WAV,
                sources=[src],
                audio_info=audio_info,
                video_info=build_video_info(),
                location_info=location,
                dolby_atmos_info=pb.EM_DolbyAtmosInfo(),
                offline_bounce=pb.TBool_False if realtime else pb.TBool_True,
            )
            result["ok"] = True
        except Exception as exc:
            result["err"] = exc

    t = threading.Thread(target=_bounce, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print("[error] export_mix 超过 %.0f 秒未返回：Pro Tools 可能弹出了模态"
              "对话框（如「视频丢失 / 媒体丢失」查找框），阻塞了离线 bounce。\n"
              "        请在桌面端处理该弹窗后重试；或把 Video 轨设为离线"
              "（Take Video Offline）再跑。" % timeout, file=sys.stderr)
        sys.exit(1)
    if "err" in result:
        raise result["err"]


def print_session_summary(pt):
    """第 0 步：环境/工程摘要打印。"""
    print("=== session ===")
    print(f"name      : {pt.session_name()}")
    print(f"sr        : {pt.session_sample_rate()}")
    print(f"bit depth : {pt.session_bit_depth()}")
    print(f"timecode  : {pt.session_timecode_rate()}")
    print(f"length    : {pt.session_length()}")


def verify_sources_against_profile(profile, sources, source_type):
    """profile 存在时，校验 source 名在对应类型列表里。返回 (ok, reasons)。"""
    key = SOURCE_TYPE[source_type]
    names_by_type = profile.get("sources", {}).get(key, [])
    if not names_by_type:
        return True, []
    missing = [s for s in sources if s not in names_by_type]
    return (not missing, missing)


def connect_pt():
    """连接 PTSL；失败返回 None（由调用方决定是否致命）。"""
    try:
        return Engine(company_name="local", application_name="pt-exporter")
    except Exception as exc:
        print(f"[warn] 无法连接 Pro Tools（{type(exc).__name__}）", file=sys.stderr)
        return None


# ── 模态弹窗防御（2026-09-15 实测：PT 弹"媒体丢失"等模态框会阻塞 PTSL）─
def guard_session_ready(pt, timeout=5.0):
    """确认 PTSL 会话可读；带超时，防模态弹窗造成无提示卡死。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if pt.session_name():
                return
        except Exception:
            pass
        time.sleep(0.3)
    print("[error] Pro Tools 会话无响应（疑似模态弹窗阻塞，如媒体丢失"
          "查找框）。请人工处理后重试。", file=sys.stderr)
    sys.exit(1)


def open_session_guarded(pt, path, timeout=10.0):
    """open_session 带超时：PTSL 遇模态弹窗会无限挂起，用线程包装。"""
    import threading
    result = {}

    def _open():
        try:
            pt.open_session(path)
            result["ok"] = True
        except Exception as exc:
            result["err"] = exc

    t = threading.Thread(target=_open, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print(f"[error] open_session 超过 {timeout:.0f} 秒未返回：Pro Tools "
              "可能弹出了模态对话框（如媒体丢失查找框）。请人工处理弹窗"
              "后重试。", file=sys.stderr)
        sys.exit(1)
    if "err" in result:
        raise result["err"]
    guard_session_ready(pt)


def safe_name(name):
    """轨道/source 名 → 文件名安全片段（PT 本身会加 -St / 类型后缀）。"""
    out = []
    for ch in name:
        if ch.isalnum() or ch in "._":
            out.append(ch)
        elif ch in " -":
            out.append("_")
    s = "".join(out).strip("_")
    return s or "track"


def _run_path_mode(args, profile, pt):
    """File > Bounce Mix 路线：bus / output / physicalout。"""
    source_type = SOURCE_TYPE[args.source_type]
    ok, missing = verify_sources_against_profile(profile, args.source,
                                                 args.source_type)
    if missing:
        print(f"[warn] 以下 source 不在 profile 的 {args.source_type} 列表中："
              f"{missing}")
        print("       可用名单见 profile 的 sources 节；继续尝试导出，"
              "若报 source not found 请核对。")
    else:
        print(f"[ok] profile 校验：{len(args.source)} 个 source 均在 "
              f"{args.source_type} 列表内")

    plan = []
    for name in args.source:
        base = f"{args.prefix}{safe_name(name)}"
        plan.append((name, base))

    print("\n=== 导出计划（Bounce Mix / 路径制）===")
    print(f"范围 : {args.start} -> {args.end}")
    print(f"格式 : {args.sample_rate}/{args.bit_depth}-bit "
          f"{args.format}  {'REALTIME(实时)' if args.realtime else 'offline'}")
    print(f"输出 : {args.out}")
    for name, base in plan:
        print(f"  bounce : {name}  ->  {base}.wav")

    if args.dry_run:
        return

    pt.set_timeline_selection(in_time=args.start, out_time=args.end)
    sel = pt.get_timeline_selection()
    print(f"\n[range] {sel[0]} -> {sel[1]}")

    audio_info = build_audio_info(args)
    location = build_location(args.out)

    for name, base in plan:
        try:
            print(f"[bounce] {name} -> {base}.wav  "
                  f"({'realtime' if args.realtime else 'offline'})")
            bounce_one(pt, name, source_type, base, audio_info, location,
                       args.realtime, timeout=args.bounce_timeout)
            wav = os.path.join(args.out, base + ".wav")
            size = os.path.getsize(wav) if os.path.exists(wav) else -1
            print(f"[ok] {base}.wav  {size:,} bytes")
        except Exception as exc:
            print(f"[fail] {name}: {exc}")
            print("       常见原因：source 名错（提示 Required mix source "
                  "was not found）/ 时间范围内无内容 / 工程未加载")
            print("       建议用 pt-scanner 重新扫描确认列表，或加 --dry-run "
                  "核对计划。")


def _prof_attr(info, key):
    """profile 的轨道属性嵌套在 attributes 下（attributes.contains_clips），
    少数版本可能提升到顶层——两处都查，兼容。"""
    if not info:
        return None
    if key in info:
        return info.get(key)
    return (info.get("attributes") or {}).get(key)


def _filter_by_profile(profile, tracks):
    """用 profile 的 contains_clips 信息做二次筛选（仅 --all-tracks 时）。
    返回 (保留列表, 被排除的可疑名单)。

    v1.1.0：空轨过滤从「仅 audio」扩到「audio + aux」——含效果辅助轨的
    白名单模式（--track-type audio aux ...）下，无音频块的 aux 会导出成
    纯静音文件（实测 aux 轨 ≈ 信号中间节点），一并排除以免交付混入空响。
    """
    prof = {t.get("name"): t for t in profile.get("tracks", [])}
    if not prof:
        return tracks, []
    keep, suspect = [], []
    for t in tracks:
        info = prof.get(t.name)
        if info is None:
            keep.append(t)  # profile 里没有 → 可能工程已变，保守保留
            continue
        if (_prof_attr(info, "contains_clips") is False
                and t.type in (pb.TType_Audio, pb.TType_Aux)):
            suspect.append(t)
        else:
            keep.append(t)
    return keep, suspect


def _run_track_mode(args, profile, pt):
    """右键轨道 > Bounce 路线（BounceTrack，轨道制）。"""
    tracks, by_name = list_tracks(pt)
    print(f"[info] 工程共 {len(tracks)} 根轨")

    picked, reasons = select_tracks(tracks, args)
    for r in reasons:
        print(f"[warn] {r}")

    if args.all_tracks and args.skip_buses:
        dropped = [t for t in tracks if t.type in BUS_LIKE_TYPES]
        if dropped:
            print(f"[info] --skip-buses 排除 {len(dropped)} 根总线类轨"
                  f"（aux/master/folder/vca）")

    if args.exclude_empty:
        picked, suspect = _filter_by_profile(profile, picked)
        if suspect:
            print(f"[info] --exclude-empty 依据 profile 排除 "
                  f"{len(suspect)} 根无音频块的轨：")
            for t in suspect[:20]:
                print(f"         - {t.name}")

    # --exclude-name（v1.2.0）：名字级排除名单。含 * ? 时按通配符匹配，
    # 否则精确匹配（fnmatch 对无通配 pattern 等价精确，一套逻辑两用）。
    if getattr(args, "exclude_name", None):
        import fnmatch
        pats = [x.strip() for x in args.exclude_name if x and x.strip()]
        def _is_excluded(name):
            return any(fnmatch.fnmatchcase(name, p) for p in pats)
        dropped = [t for t in picked if _is_excluded(t.name)]
        if dropped:
            picked = [t for t in picked if not _is_excluded(t.name)]
            print(f"[info] --exclude-name 按名单排除 {len(dropped)} 根轨：")
            for t in dropped[:20]:
                print(f"         - {t.name}")

    if not picked:
        print("[error] 没有可导出的轨道。请检查 --source 名，或改用 "
              "--all-tracks。", file=sys.stderr)
        sys.exit(1)

    print("\n=== 导出计划（BounceTrack / 轨道制）===")
    print(f"范围 : {args.start} -> {args.end}（由时间轴选区决定）")
    print(f"格式 : {args.sample_rate}/{args.bit_depth}-bit "
          f"{args.format}  {'REALTIME(实时)' if args.realtime else 'offline'}")
    print(f"输出 : {args.out}")

    plan = []
    for t in picked:
        base = f"{args.prefix}{safe_name(t.name)}"
        plan.append((t, base))
        print(f"  bounce : {t.name:<28} [{track_type_name(t.type):>14}]"
              f"  ->  {base}.wav")

    vca = [t for t in picked if t.type == pb.TType_Vca]
    if vca:
        print(f"\n[note] 选了 {len(vca)} 根 VCA 轨。VCA 不是信号路径，"
              "实测会「返回成功但零文件」，属预期行为，不是 bug。")

    if args.dry_run:
        return

    # ── 执行：选区是区间唯一来源 ───────────────────────────────────
    pt.set_timeline_selection(in_time=args.start, out_time=args.end)
    sel = pt.get_timeline_selection()
    print(f"\n[range] {sel[0]} -> {sel[1]}")
    if not sel or not sel[0] or not sel[1] or str(sel[0]) == str(sel[1]):
        print("[error] 时间轴选区为空——BounceTrack 的导出区间只能来自选区，"
              "空选区会报「由于时间轴上没有内容」。请检查 --start/--end。",
              file=sys.stderr)
        sys.exit(1)

    audio_info = build_audio_info(args)
    location = build_location(args.out)

    ok_n = 0
    for t, base in plan:
        try:
            print(f"[bounce] {t.name} -> {base}.wav  "
                  f"({'realtime' if args.realtime else 'offline'})")
            op = build_bounce_track(t.id, base, audio_info, location,
                                    args.realtime)
            paths = bounce_track_one(pt, op, args.realtime,
                                     timeout=args.bounce_timeout)
            if not paths:
                print("[warn] 命令返回成功但没有文件。若这是 VCA 轨属预期；"
                      "否则请检查该轨是否有音频块（contains_clips）。")
                continue
            for p in paths:
                size = os.path.getsize(p) if os.path.exists(p) else -1
                print(f"[ok] {os.path.basename(p)}  {size:,} bytes")
            ok_n += 1
        except Exception as exc:
            print(f"[fail] {t.name}: {exc}")
            print("       常见原因：track id 未带花括号 / 选区为空 / "
                  "该轨在时间范围内无内容")

    print(f"\n[summary] {ok_n}/{len(plan)} 轨导出成功")


def run(args):
    profile = load_profile(args.profile)

    os.makedirs(args.out, exist_ok=True)
    pt = connect_pt()

    if pt is not None:
        if args.session:
            print(f"[open] {args.session}")
            open_session_guarded(pt, args.session)
        else:
            guard_session_ready(pt)
        print_session_summary(pt)
    else:
        print("[warn] PTSL 不可达：确认 Pro Tools 已启动、工程已加载。"
              "dry-run 模式继续预览（基于 profile），实际导出前必须修好连接。")

    dry_only = args.dry_run or (pt is None and args.source_type == "track"
                                and not args.source)
    if pt is None and args.source_type == "track":
        if not args.dry_run:
            print("[error] 轨道模式需要读取工程轨道列表（track_list），"
                  "必须连上 Pro Tools。", file=sys.stderr)
            sys.exit(1)

    if args.dry_run and pt is None:
        # dry-run + 无连接：路径制可纯靠 profile 预览，轨道制则需先扫 profile
        if args.source_type == "track":
            print("[dry-run] 无 PTSL 连接，轨道列表改从 profile 的 tracks 节读取。")
            _track_plan_from_profile(args, profile)
            return

    try:
        if args.source_type == "track":
            _run_track_mode(args, profile, pt)
        else:
            _run_path_mode(args, profile, pt)
    finally:
        if pt is not None:
            if args.save and not args.dry_run:
                try:
                    pt.save_session()
                except Exception as exc:
                    print(f"[warn] save_session 失败：{exc}", file=sys.stderr)
            pt.close()

    if args.dry_run:
        print("\n[dry-run] 预览结束，未执行任何导出。确认无误后去掉 "
              "--dry-run 再跑。")
    else:
        print("\n[done] all exports complete")


def _track_plan_from_profile(args, profile):
    """无 PT 连接时的轨道模式 dry-run：只用 profile 数据出计划。"""
    rows = profile.get("tracks", [])
    if not rows:
        print("[warn] profile 里没有 tracks 节，无法预览。请先跑 pt-scanner。")
        return
    picked = []
    for r in rows:
        name = r.get("name", "")
        ttype = r.get("type", "")
        if ttype == "video":
            continue
        if args.skip_buses and ttype in ("aux", "master", "vca",
                                         "routing-folder", "basic-folder"):
            continue
        if args.all_tracks:
            if args.exclude_empty and _prof_attr(r, "contains_clips") is False:
                continue
            picked.append(r)
        elif name in args.source:
            picked.append(r)
    print("\n=== 导出计划（BounceTrack / 轨道制，基于 profile 预览）===")
    print(f"范围 : {args.start} -> {args.end}（由时间轴选区决定）")
    print(f"输出 : {args.out}")
    for r in picked:
        print(f"  bounce : {r.get('name'):<28} [{r.get('type'):>14}]"
              f"  clips={_prof_attr(r, 'contains_clips')}")
    if not picked:
        print("  （空——检查 --source 名是否与 profile 一致）")


def main():
    p = argparse.ArgumentParser(description="Pro Tools CLI exporter via PTSL")
    p.add_argument("--profile", default=None,
                   help="pt-profile.json（pt-scanner 生成；用于校验 "
                        "source 名与 session 摘要，可选但推荐）")
    sub = p.add_subparsers(dest="mode", required=True)

    for mode in ("mix", "stems"):
        sp = sub.add_parser(mode)
        sp.add_argument("--session", help=".ptx path (omit to use currently open)")
        sp.add_argument("--source", action="append", default=[],
                       help="source/track name (repeatable for stems)")
        sp.add_argument("--source-type", choices=SOURCE_TYPE_CHOICES,
                        default="bus",
                        type=lambda s: s.lower(),
                        help="bus | output | physicalout（Bounce Mix 路径制）"
                             " | track（BounceTrack 轨道制）")
        # ── 轨道模式专用 ─────────────────────────────────────────
        sp.add_argument("--all-tracks", action="store_true",
                       help="[track] 导出工程内全部轨道（自动跳过 video）")
        sp.add_argument("--skip-buses", action="store_true",
                       help="[track] 配合 --all-tracks：排除 aux/master/"
                            "folder/vca 等总线类轨")
        sp.add_argument("--exclude-empty", action="store_true",
                       help="[track] 配合 --all-tracks：依据 profile 的 "
                            "contains_clips 排除无音频块的轨")
        sp.add_argument("--track-type", action="append", default=[],
                       metavar="TYPE",
                       help="[track] 只要这些类型（audio/aux/master/vca/"
                            "routing-folder/instrument/midi），可重复")
        sp.add_argument("--exclude-name", action="append", default=[],
                       metavar="NAME",
                       help="[track] 按名字排除轨道，可重复；含 * ? 时按"
                            "通配符匹配，否则精确匹配（v1.2.0）")
        sp.add_argument("--bounce-timeout", type=float, default=600.0,
                       help="单次导出超时秒数（默认 600）。实时导出长素材时"
                            "应 ≥ 素材时长 + 余量；超时即 fail-fast，"
                            "用于兜住 PT 模态弹窗造成的挂起。")
        # ── 通用 ────────────────────────────────────────────────
        sp.add_argument("--out", required=True, help="output directory")
        sp.add_argument("--start", required=True, help="TC in, e.g. 00:00:00:00")
        sp.add_argument("--end", required=True, help="TC out, e.g. 00:02:00:00")
        sp.add_argument("--sample-rate", type=int, default=48000,
                        choices=list(SAMPLE_RATE))
        sp.add_argument("--bit-depth", type=int, default=24,
                        choices=list(BIT_DEPTH))
        sp.add_argument("--format", default="mono", choices=list(EXPORT_FORMAT))
        sp.add_argument("--realtime", action="store_true",
                       help="real-time bounce (renders all plugins/automation)")
        sp.add_argument("--prefix", default="", help="filename prefix")
        sp.add_argument("--save", action="store_true",
                       help="save session before close")
        sp.add_argument("--dry-run", action="store_true",
                       help="print plan only, do not export")

    args = p.parse_args()
    if not args.source and not args.all_tracks:
        p.error("需要 --source（可重复）或 --all-tracks")
    run(args)


if __name__ == "__main__":
    main()