# -*- coding: utf-8 -*-
"""核验打包好的 exe：产物清单 + 附属文件 + 真实启动 + 顶层窗口枚举。

用法
----
    python tools/verify_exe.py                  # 自动取出口根下最新的 pt-audio-toolkit-v*
    python tools/verify_exe.py --dir <出口目录>
    python tools/verify_exe.py --no-launch      # 只核清单，不启动 GUI

退出码：0 全部通过 ｜ 1 有缺项/异常

历史痛点
--------
`ttk.Style()` 早于 `Tk()` 会隐式建一个标题为 `tk` 的空白小窗。本脚本对每个进程
枚举顶层窗口，单独标记可疑残留空窗 —— 这个坑反复出现过，必须每次打包后查。
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

APPS = ["pt-tools", "pt-project-folder-builder", "jianying-draft-toolkit", "rename-unify"]
EXE_ROOT = Path(os.environ.get("PT_EXE_ROOT", r"D:\Ai-Files\Agent-Preset\exe"))

# 关键附属文件（打包后置动作的产物）—— 缺了工具仍能启动但功能不全
CHECKS = [
    ("pt-tools 内置技能 pt-scanner",
     "pt-tools/_internal/skills/pt-scanner/scripts/pt_scan.py"),
    ("pt-tools 内置技能 pt-exporter",
     "pt-tools/_internal/skills/pt-exporter/scripts/pt_export.py"),
    ("pt-tools 内置技能 pt-cleaner",
     "pt-tools/_internal/skills/pt-cleaner/scripts/pt_clean.py"),
    ("jianying 解密器 jy-draftc.exe",
     "jianying-draft-toolkit/tools/jy-draftc/jy-draftc-amd64-windows/jy-draftc.exe"),
]

# 可选附属项：缺了不影响判定，只打 INFO。
# tkinterdnd2 —— v2.6.2 起剪映工具包**取消了拖拽区**（改「输入源」选择框，
# 见 Q10），该依赖已不再需要；保留检查只为观察是否仍被打包进去。
OPTIONAL_CHECKS = [
    ("jianying 拖拽依赖 tkinterdnd2（v2.6.2 起已不需要）",
     "jianying-draft-toolkit/_internal/tkinterdnd2"),
]

user32 = ctypes.windll.user32
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def windows_of_pid(pid):
    """枚举该进程的全部顶层窗口：(标题, 类名, 是否可见)"""
    out = []

    def cb(hwnd, _l):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            out.append((buf.value, cls.value, bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return out


def latest_exe_dir():
    cands = sorted([d for d in EXE_ROOT.glob("pt-audio-toolkit-v*") if d.is_dir()],
                   key=lambda d: d.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def dir_size_mb(d):
    return sum(os.path.getsize(os.path.join(r, f))
               for r, _dd, fs in os.walk(d) for f in fs) / 1048576.0


def main():
    ap = argparse.ArgumentParser(description="核验打包好的 exe")
    ap.add_argument("--dir", default=None, help="出口目录（缺省取最新的 pt-audio-toolkit-v*）")
    ap.add_argument("--no-launch", action="store_true", help="只核清单，不启动 GUI")
    args = ap.parse_args()

    out_root = Path(args.dir) if args.dir else latest_exe_dir()
    if not out_root or not out_root.is_dir():
        print("[FAIL] 找不到出口目录。用 --dir 指定，或设置 PT_EXE_ROOT。")
        print("       出口根：%s" % EXE_ROOT)
        return 1

    ok_all = True
    print("=" * 76)
    print("出口目录：%s" % out_root)
    print("=" * 76)
    print("① 工具产物")
    print("-" * 76)
    for a in APPS:
        d = out_root / a
        exe = d / (a + ".exe")
        if not d.is_dir():
            print("[MISS] %-28s 目录不存在" % a)
            ok_all = False
            continue
        n = sum(len(fs) for _r, _dd, fs in os.walk(d))
        has = exe.is_file()
        ok_all = ok_all and has
        print("[%s] %-28s %6.1f MB  %4d 文件  exe=%s"
              % ("OK" if has else "NO", a, dir_size_mb(d), n,
                 ("%.2f MB" % (exe.stat().st_size / 1048576.0)) if has else "缺"))

    print()
    print("② 关键附属文件")
    print("-" * 76)
    for label, rel in CHECKS:
        p = out_root / rel
        ok = p.exists()
        ok_all = ok_all and ok
        print("[%s] %s" % ("OK" if ok else "MISS", label))

    for label, rel in OPTIONAL_CHECKS:
        p = out_root / rel
        print("[%s] %s" % ("OK" if p.exists() else "INFO", label))

    if args.no_launch:
        print()
        print("结论：%s（未启动 GUI）" % ("全部通过" if ok_all else "有缺项，见上"))
        return 0 if ok_all else 1

    print()
    print("③ 真实启动 + 顶层窗口枚举")
    print("-" * 76)
    for a in APPS:
        exe = out_root / a / (a + ".exe")
        if not exe.is_file():
            continue
        try:
            proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
        except Exception as e:
            print("[FAIL] %-28s 启动异常：%s" % (a, e))
            ok_all = False
            continue
        time.sleep(3.5)
        alive = proc.poll() is None
        wins = windows_of_pid(proc.pid)
        time.sleep(0.6)
        wins = windows_of_pid(proc.pid)
        residual = [w for w in wins if w[0].strip().lower() in ("tk", "")]
        if not alive or residual:
            ok_all = False
        print("[%s] %-28s 进程存活=%s  顶层窗口=%d"
              % ("OK" if (alive and not residual) else "WARN", a, alive, len(wins)))
        for t, c, vis in wins:
            print("        · title=%-34r class=%-14s visible=%s" % (t, c, vis))
        if residual:
            print("      ⚠ 疑似残留空窗（历史坑）：%s" % residual)
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    print()
    print("=" * 76)
    print("结论：%s" % ("全部通过" if ok_all else "有缺项或异常，见上"))
    print("=" * 76)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
