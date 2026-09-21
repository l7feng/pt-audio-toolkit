#!/usr/bin/env python3
r"""
video_duration.py — 读取视频时长（MP4 mvhd box），换算 timecode

用法：
  python video_duration.py <视频路径> [更多路径...] [--fps <帧率>] [--profile <pt-profile.json>]

- 无 --fps/--profile：只打印秒数与 mm:ss
- 提供 --fps 或 --profile（内含 timecode_rate）：额外输出 HH:MM:SS:FF（按帧率整数帧）
- --profile 优先用于取帧率，--fps 可覆盖（profile 里 timecode_rate 是 "25" 这类字符串）

示例：
  python video_duration.py "D:\video\ep1.mp4" --profile pt-profile.json
  python video_duration.py a.mp4 b.mp4 --fps 25
"""
import argparse
import json
import os
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def mp4_duration(path):
    """读取 MP4 时长（秒），失败返回 None。"""
    with open(path, "rb") as f:
        while True:
            header = f.read(8)
            if len(header) < 8:
                return None
            size, boxtype = struct.unpack(">I4s", header)
            boxtype = boxtype.decode("latin1")
            if boxtype == "moov":
                break
            f.seek(size - 8, 1)
        end = f.tell() + size - 8
        while f.tell() < end:
            sub = f.read(8)
            if len(sub) < 8:
                return None
            ssize, stype = struct.unpack(">I4s", sub)
            stype = stype.decode("latin1")
            if stype == "mvhd":
                ver = f.read(1)[0]
                f.read(3)  # flags
                if ver == 1:
                    f.read(16)  # ctime/mtime
                    timescale = struct.unpack(">I", f.read(4))[0]
                    duration = struct.unpack(">Q", f.read(8))[0]
                else:
                    f.read(8)
                    timescale = struct.unpack(">I", f.read(4))[0]
                    duration = struct.unpack(">I", f.read(4))[0]
                return duration / timescale
            f.seek(ssize - 8, 1)
    return None


def seconds_to_timecode(seconds, fps):
    """秒 → HH:MM:SS:FF；帧 = 小数秒 × 帧率，向下取整。"""
    total_frames = round(seconds * fps)
    frames = int(total_frames % fps)
    total_secs = int(total_frames // fps)
    h, rem = divmod(total_secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"


def fps_from_profile(profile_path):
    try:
        with open(profile_path, encoding="utf-8") as f:
            p = json.load(f)
        rate = p["session"]["timecode_rate"]  # 如 "25"、"29.97 DF"
        rate = rate.split()[0]
        return float(rate)
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser(description="Read video duration from MP4")
    p.add_argument("files", nargs="+", help="video file path(s)")
    p.add_argument("--fps", type=float, default=None, help="framerate to "
                   "compute timecode (overrides --profile)")
    p.add_argument("--profile", default=None,
                   help="pt-profile.json (uses session.timecode_rate)")
    args = p.parse_args()

    fps = args.fps
    if fps is None and args.profile:
        fps = fps_from_profile(args.profile)

    for v in args.files:
        if not os.path.isfile(v):
            print(f"[error] not found: {v}")
            continue
        d = mp4_duration(v)
        if d is None:
            print(f"[error] cannot parse duration: {v}")
            continue
        m, s = divmod(int(d), 60)
        line = f"{v}: {d:.2f}s  ({m}:{s:02d})"
        if fps:
            line += f"  -> {seconds_to_timecode(d, fps)}  @{fps:g}fps"
        print(line)


if __name__ == "__main__":
    main()