#!/usr/bin/env python3
r"""
find_session_videos.py — 在 Pro Tools 工程目录树中检索视频文件

为什么需要：导出时长要以视频为准（工程默认长度 06:00:00:00 不是真实长度）。
此前流程要人工指视频文件；本脚本按「工程路径 → 同级目录树」自动检索，
供 GUI / pt-exporter 批量流程调用，找到多条时由上层让用户选择。

检索范围（按序，找到即停）：
  1. --session 给出 .ptx 时：.ptx 所在目录树（深度 ≤ --depth，默认 4）
  2. --dir 给出目录时：该目录树

识别的视频扩展名：.mp4 .mov .mxf .avi .wmv .m4v .mts .m2ts
（.mov 与 .mp4 同为 ISO-BMFF 容器，mvhd 读时长通用）

用法：
  python find_session_videos.py --session "D:\pt\誓言1\誓言1.ptx" --profile pt-profile.json
  python find_session_videos.py --dir "D:\pt\誓言1"

输出（stdout，UTF-8 JSON；供上层解析）：
  {"session": "...", "searched_root": "...",
   "videos": [{"path": "...", "name": "...", "duration_sec": 118.5,
               "tc_end": "00:01:58:13"}],   ← 提供 --profile/--fps 时才有 tc_end
   "count": 1}

退出码：0 找到 ≥1 条；1 没找到；2 参数/环境错误。
"""
import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from video_duration import mp4_duration, seconds_to_timecode, fps_from_profile  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".avi", ".wmv", ".m4v", ".mts", ".m2ts"}

# 检索时跳过的目录名（PT 内部噪声/海量小文件区，避免慢扫误报）
SKIP_DIRS = {"Session File Backups", "WaveCache", "Region Groups",
             "Session Data", "Clip Groups", "Bounced Files", ".ptx.backup",
             "Rendered Files", "PreRender", "Recover Files"}

# 小于该秒数的视频视为碎片/参考小样，不进清单（可调）
DEFAULT_MIN_DURATION = 10.0


def iter_video_files(root: Path, depth: int):
    """在 root 目录树内按扩展名收集视频文件，限制深度、跳过噪声目录。"""
    root = Path(root)
    if not root.is_dir():
        return
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        cur_depth = len(Path(dirpath).parts) - base_depth
        if cur_depth >= depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if Path(fn).suffix.lower() in VIDEO_EXTS:
                yield Path(dirpath) / fn


def search_videos(root: Path, fps, min_duration: float):
    """返回视频清单（含时长秒；读不出时长的文件跳过并记录原因）。"""
    videos, skipped = [], []
    for p in iter_video_files(root, depth=8):   # 深度兜底 8，防异常深树
        try:
            dur = mp4_duration(str(p))
        except Exception:
            dur = None
        if dur is None:
            skipped.append({"path": str(p), "reason": "无法读取时长（可能非 ISO-BMFF 容器）"})
            continue
        if dur < min_duration:
            skipped.append({"path": str(p), "reason": f"时长 {dur:.1f}s 低于下限 {min_duration:.0f}s（疑似碎片）"})
            continue
        item = {"path": str(p), "name": p.name,
                "duration_sec": round(dur, 3)}
        if fps:
            item["tc_end"] = seconds_to_timecode(dur, fps)
        videos.append(item)
    videos.sort(key=lambda v: v["duration_sec"], reverse=True)  # 长的在前
    return videos, skipped


def main():
    p = argparse.ArgumentParser(description="Find video files in a PT session tree")
    p.add_argument("--session", default=None, help=".ptx path（取其所在目录树检索）")
    p.add_argument("--dir", default=None, help="直接指定检索根目录")
    p.add_argument("--profile", default=None, help="pt-profile.json（取时码率算 tc_end）")
    p.add_argument("--fps", type=float, default=None, help="手动指定帧率（覆盖 --profile）")
    p.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION,
                   help="视频时长下限秒数（过滤碎片，默认 10）")
    args = p.parse_args()

    if not args.session and not args.dir:
        print(json.dumps({"error": "需要 --session 或 --dir 之一"}, ensure_ascii=False))
        return 2

    # v1.3.0：显式 --dir 优先于 --session（调用方要做候选根逐级上溯，
    # 若被 --session 抢回 .ptx 同级目录，父级候选就永远走不到）。
    if args.dir:
        root = Path(args.dir).resolve()
    else:
        root = Path(args.session).resolve().parent
    if not root.is_dir():
        print(json.dumps({"error": f"目录不存在: {root}"}, ensure_ascii=False))
        return 2

    fps = args.fps
    if fps is None and args.profile:
        fps = fps_from_profile(args.profile)

    videos, skipped = search_videos(root, fps, args.min_duration)
    out = {
        "session": args.session or "",
        "searched_root": str(root),
        "videos": videos,
        "skipped": skipped,
        "count": len(videos),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if videos else 1


if __name__ == "__main__":
    sys.exit(main())
