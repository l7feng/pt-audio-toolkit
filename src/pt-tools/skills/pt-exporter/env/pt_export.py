#!/usr/bin/env python3
r"""
pt_export.py — Pro Tools 无界面导出工具（基于 PTSL / py-ptsl）

功能：
  - 并轨混音（Bounce to Disk）：按 bus / 主输出整段 bounce，实时渲染插件与自动化
  - 分轨导出（Stems）：对多个 bus 分别 bounce，每个 source 一个 WAV 文件

前提：Pro Tools 已启动并加载工程，PTSL 监听 localhost:31416。

示例：
  # 第二集：整段并轨到 Test 目录（实时，保留插件）
  python pt_export.py mix --session "D:\...\project\2\誓言2.ptx" ^
      --source "Master Hole" --source-type Output ^
      --out "D:\...\Test" --start 00:00:00:00 --end 00:02:00:00 --realtime

  # 第三集：DX / MX 分轨到 Test - 副本
  python pt_export.py stems --session "D:\...\project\3\誓言3.ptx" ^
      --source "DX-BUS-Master" --source "MX-BUS-Master" --source-type Bus ^
      --out "D:\...\Test - 副本" --start 00:00:00:00 --end 00:02:00:00 --realtime
"""
import argparse
import os
import sys
from ptsl import Engine
from ptsl import PTSL_pb2 as pb

# ── 枚举速查 ──────────────────────────────────────────────────────────
FILE_TYPE = {"wav": pb.EM_WAV, "aiff": pb.EM_AIFF}
SAMPLE_RATE = {48000: pb.SRate_48000, 44100: pb.SRate_44100,
               96000: pb.SRate_96000}
BIT_DEPTH = {16: pb.Bit16, 24: pb.Bit24, 32: pb.Bit32Float}
SOURCE_TYPE = {"bus": pb.EMSType_Bus, "output": pb.EMSType_Output,
               "physicalout": pb.EMSType_PhysicalOut}
EXPORT_FORMAT = {"mono": pb.EFormat_Mono, "interleaved": pb.EFormat_Interleaved,
                 "multiple-mono": pb.EFormat_MultipleMono}


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


def bounce_one(pt, source_name, source_type, base_name, audio_info,
               location, realtime):
    src = pb.EM_SourceInfo(source_type=source_type, name=source_name)
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


def run(args):
    os.makedirs(args.out, exist_ok=True)
    pt = Engine(company_name="local", application_name="pt-exporter")

    if args.session:
        print(f"[open] {args.session}")
        pt.open_session(args.session)

    print(f"[session] {pt.session_name()}  sr={pt.session_sample_rate()}  len={pt.session_length()}")

    pt.set_timeline_selection(in_time=args.start, out_time=args.end)
    sel = pt.get_timeline_selection()
    print(f"[range] {sel[0]} -> {sel[1]}")

    audio_info = build_audio_info(args)
    location = build_location(args.out)
    source_type = SOURCE_TYPE[args.source_type]

    for name in args.source:
        safe = name.replace(" ", "_").replace("-", "_")
        base = f"{args.prefix}{safe}" if args.prefix else safe
        print(f"[bounce] {name} -> {base}.wav  ({'realtime' if args.realtime else 'offline'})")
        bounce_one(pt, name, source_type, base, audio_info, location, args.realtime)
        # verify
        wav = os.path.join(args.out, base + ".wav")
        size = os.path.getsize(wav) if os.path.exists(wav) else -1
        print(f"[ok] {base}.wav  {size:,} bytes")

    if args.save:
        pt.save_session()
    pt.close()
    print("[done] all exports complete")


def main():
    p = argparse.ArgumentParser(description="Pro Tools CLI exporter via PTSL")
    sub = p.add_subparsers(dest="mode", required=True)

    for mode in ("mix", "stems"):
        sp = sub.add_parser(mode)
        sp.add_argument("--session", help=".ptx path (omit to use currently open)")
        sp.add_argument("--source", action="append", required=True,
                       help="source name (repeatable for stems)")
        sp.add_argument("--source-type", choices=list(SOURCE_TYPE), default="bus")
        sp.add_argument("--out", required=True, help="output directory")
        sp.add_argument("--start", required=True, help="TC in, e.g. 00:00:00:00")
        sp.add_argument("--end", required=True, help="TC out, e.g. 00:02:00:00")
        sp.add_argument("--sample-rate", type=int, default=48000, choices=list(SAMPLE_RATE))
        sp.add_argument("--bit-depth", type=int, default=24, choices=list(BIT_DEPTH))
        sp.add_argument("--format", default="mono", choices=list(EXPORT_FORMAT))
        sp.add_argument("--realtime", action="store_true",
                       help="real-time bounce (renders all plugins/automation)")
        sp.add_argument("--prefix", default="", help="filename prefix")
        sp.add_argument("--save", action="store_true", help="save session before close")

    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
