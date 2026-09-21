#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
pt_media_relocate.py — 「文件去找路径」媒体就位工具（05 号方案 · 路线 2）

背景（2026-09-18 拍板）：
  PTSL 协议层无任何 relink / 媒体搜索命令；.ptx 是 Avid 专有二进制不可安全改写。
  故「打开工程弹媒体丢失查找框」无法在协议层根治，人类否决了「人工 relink」，
  采纳路线 2：**不碰工程文件，把实际存在的媒体文件搬到（链接到）PT 期望的位置**，
  让弹窗自愈。

情报来源（唯一权威）：Pro Tools 弹窗上显示的「期望完整路径」。
  → 需要人类把弹窗上的路径喂给本工具（--expected）。

行为：
  1. 对每个 expected 路径：已存在 → [ok] 已就位（幂等，可反复跑）。
  2. 不存在 → 按文件名在搜索根里检索（ptx 工程树、--search-root、全盘备选根），
     命中后创建父目录，用 --mode 方式就位：
       auto（默认）: hardlink（同卷零拷贝，最稳）→ symlink → copy 逐级回退
       link        : 只 hardlink/symlink
       copy        : 只复制（跨卷时用）
  3. 绝不删除、绝不覆盖已有文件（目标已存在按幂等成功处理）。

用法示例：
  # 人类从弹窗读到位移：PT 在找 D:\...\Video\24.mp4，实际文件在 Video\归档\24.mp4
  python pt_media_relocate.py \
      --expected "D:\DAW-Project\10-誓言D_20260915_7F\Video\24.mp4" \
      --ptx "D:\DAW-Project\10-誓言D_20260915_7F\project\24\誓言24.ptx"

  # 只有文件名、不知道期望路径时：全检索 + 试探性落到期望目录
  python pt_media_relocate.py --name "24.mp4" \
      --expected-dir "D:\DAW-Project\10-誓言D_20260915_7F\Video" \
      --search-root "D:\DAW-Project\10-誓言D_20260915_7F\Video\归档"

  # 干跑（只报告打算做什么）
  python pt_media_relocate.py --expected "..." --dry-run
"""

import argparse
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".mts", ".m2ts", ".avi", ".m4v"}


def iter_files(root, max_depth=6):
    """深度受限遍历（避免全盘失控）。root 不存在则静默返回。"""
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        cur_depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        if cur_depth >= max_depth:
            dirnames[:] = []
        for f in filenames:
            yield os.path.join(dirpath, f)


def find_source(filename, search_roots, min_size=1024):
    """按文件名在检索根中找第一个可用同名文件（跳过太小/占位文件）。
    返回 (path, size) 或 (None, 0)。"""
    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue
        for p in iter_files(root):
            if os.path.basename(p).lower() == filename.lower():
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                if size >= min_size:
                    return p, size
    return None, 0


def place(src, dst, mode):
    """把 src 就位到 dst。返回 (status, method)。已存在视为幂等成功。"""
    if os.path.exists(dst):
        return "ok(exists)", "already"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    attempts = {
        "auto": ["hardlink", "symlink", "copy"],
        "link": ["hardlink", "symlink"],
        "copy": ["copy"],
    }.get(mode, ["hardlink", "symlink", "copy"])
    errors = []
    for method in attempts:
        try:
            if method == "hardlink":
                os.link(src, dst)
            elif method == "symlink":
                os.symlink(src, dst)
            elif method == "copy":
                shutil.copy2(src, dst)
            return "ok", method
        except OSError as exc:
            errors.append("%s: %s" % (method, exc))
    return "error", "; ".join(errors)


def default_search_roots(ptx):
    """由 ptx 推断的默认检索根：工程目录、工程树两级、其 Video 归档。"""
    roots = []
    if ptx:
        proj_dir = os.path.dirname(os.path.abspath(ptx))          # ...\project\24
        project_tree = os.path.dirname(proj_dir)                  # ...\project
        show_root = os.path.dirname(project_tree)                 # ...\10-誓言D_xxx
        roots += [proj_dir, project_tree,
                  os.path.join(show_root, "Video"), show_root]
    return roots


def main():
    p = argparse.ArgumentParser(
        description="PT media relocate: bring the file to where PT expects it")
    p.add_argument("--expected", action="append", default=[],
                   help="PT 期望的完整文件路径（弹窗情报，可重复）")
    p.add_argument("--name", action="append", default=[],
                   help="只知道文件名时使用（可重复），需配合 --expected-dir")
    p.add_argument("--expected-dir", default=None,
                   help="--name 模式的期望目录")
    p.add_argument("--ptx", default=None, help="工程文件路径（用于推断检索根）")
    p.add_argument("--search-root", action="append", default=[],
                   help="额外检索根（可重复）")
    p.add_argument("--mode", choices=["auto", "link", "copy"], default="auto")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.expected and not args.name:
        p.error("需要 --expected（弹窗情报路径）或 --name（文件名检索）")

    search_roots = default_search_roots(args.ptx) + args.search_root
    search_roots = list(dict.fromkeys(search_roots))  # 去重保序

    # 组装任务清单 [(期望路径, 文件名)]
    tasks = []
    for exp in args.expected:
        tasks.append((exp, os.path.basename(exp)))
    if args.name:
        if not args.expected_dir:
            p.error("--name 模式需要 --expected-dir")
        for n in args.name:
            tasks.append((os.path.join(args.expected_dir, n), n))

    print("=== pt_media_relocate ===")
    print("检索根：")
    for r in search_roots:
        print("  - %s%s" % (r, "" if os.path.isdir(r) else "  （不存在，跳过）"))
    if args.dry_run:
        print("[dry-run] 以下为计划，不落盘：")

    had_error = False
    for dst, fname in tasks:
        print("\n→ 期望位置: %s" % dst)
        if os.path.exists(dst):
            print("  [ok] 已就位（幂等，跳过）")
            continue
        src, size = find_source(fname, search_roots)
        if src is None:
            print("  [miss] 检索根中未找到 %r —— 需要人类确认该媒体是否真的存在"
                  % fname)
            had_error = True
            continue
        print("  [found] %s  (%s bytes)" % (format(size, ","), src and src))
        if args.dry_run:
            print("  [dry-run] 将以 mode=%s 就位" % args.mode)
            continue
        status, method = place(src, dst, args.mode)
        if status.startswith("ok"):
            print("  [ok] 就位完成（method=%s）→ 重开工程弹窗应自愈" % method)
        else:
            print("  [error] 就位失败：%s" % method)
            had_error = True

    print("\n[done] %s" % ("存在未解决项，请核对上方 [miss]/[error]" if had_error
                            else "全部就位"))
    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()
