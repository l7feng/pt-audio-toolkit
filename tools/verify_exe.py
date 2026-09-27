# -*- coding: utf-8 -*-
"""核验打包好的 exe：产物清单 + 附属文件 + 真实启动 + 顶层窗口枚举。

用法
----
    python tools/verify_exe.py                  # 自动取出口根下最新的「音频工具箱-v*」
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

# 控制台默认 GBK，打印 ⚠/✅ 之类字符会 UnicodeEncodeError 把核验中断
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 出口布局（2026-09-27 人类裁决①甲，与 tools/build.py 的 TARGETS/FAMILIES 同源）：
#   <root>/音频工具箱-v<仓库版本>-<日期>/      ← PT 工具箱 + 剪映工具包
#   <root>/统一命名工具-v<该工具版本>-<日期>/   ← 通用工具（独立家族）
#   <root>/剧本双语拆分工具-v.../              ← 独立仓库 script-splitter 自建自检
# 下面这份 (工具键, 中文展示名, 家族) 是 build.py TARGETS 的副本，改动必须两处同步。
# ⚠️ rename-unify 现在**不在**「音频工具箱」目录里 —— 核验必须按家族分别定位，
#    沿用「一个 --dir 管全部」的旧写法会把它误判成 MISS。
APPS = [
    ("pt-tools", "Pro Tools工具箱", "audio"),
    ("jianying-draft-toolkit", "剪映工程工具包", "audio"),
    ("rename-unify", "统一命名工具", "solo"),
]
# 家族 → 出口目录通配（含历史 ASCII 前缀，保证旧目录仍可核验）
FAMILY_GLOBS = {
    "audio": ("音频工具箱-v*", "audio-toolkit-v*", "pt-audio-toolkit-v*"),
    "solo": ("统一命名工具-v*",),
}
EXE_ROOT = Path(os.environ.get("PT_EXE_ROOT", r"D:\Ai-Files\Agent-Preset\exe"))

# 关键附属文件（打包后置动作的产物）—— 缺了工具仍能启动但功能不全
# 元组：(说明, 所属工具的中文目录名, 相对路径, 家族)
CHECKS = [
    ("pt-tools 内置技能 pt-scanner",
     "Pro Tools工具箱", "_internal/skills/pt-scanner/scripts/pt_scan.py", "audio"),
    ("pt-tools 内置技能 pt-exporter",
     "Pro Tools工具箱", "_internal/skills/pt-exporter/scripts/pt_export.py", "audio"),
    ("pt-tools 内置技能 pt-cleaner",
     "Pro Tools工具箱", "_internal/skills/pt-cleaner/scripts/pt_clean.py", "audio"),
    ("jianying 解密器 jy-draftc.exe",
     "剪映工程工具包", "tools/jy-draftc/jy-draftc-amd64-windows/jy-draftc.exe", "audio"),
]

# 可选附属项：缺了不影响判定，只打 INFO。
# tkinterdnd2 —— v2.6.2 起剪映工具包**取消了拖拽区**（改「输入源」选择框，
# 见 Q10），该依赖已不再需要；保留检查只为观察是否仍被打包进去。
OPTIONAL_CHECKS = [
    ("jianying 拖拽依赖 tkinterdnd2（v2.6.2 起已不需要）",
     "剪映工程工具包", "_internal/tkinterdnd2", "audio"),
]

user32 = ctypes.windll.user32
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

# PyInstaller / pythonw 启动失败时弹出的错误框标题（判定「程序没起来」的硬证据）
CRASH_TITLES = (
    "unhandled exception in script",
    "failed to execute script",
    "python error",
    "fatal python error",
)


def _is_crash_box(title):
    """窗口标题是否是启动崩溃框（而非工具主窗）。"""
    t = (title or "").strip().lower()
    return any(t.startswith(p) or p in t for p in CRASH_TITLES)


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
    # 2026-09-27（裁决①甲）：出口目录改中文并按家族分家 —— PT/剪映在
    # 「音频工具箱-v<版本>-<日期>」，通用工具另立目录。旧的 ASCII 前缀也认，
    # 避免历史目录突然找不到。
    cands = sorted(
        [d for pat in FAMILY_GLOBS["audio"]
         for d in EXE_ROOT.glob(pat) if d.is_dir()],
        key=lambda d: d.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def family_roots(forced_audio=None):
    """定位各家族的出口目录：{家族: 目录 或 None}。"""
    out = {}
    for fam, pats in FAMILY_GLOBS.items():
        if fam == "audio" and forced_audio:
            out[fam] = Path(forced_audio)
            continue
        cands = sorted([d for pat in pats for d in EXE_ROOT.glob(pat) if d.is_dir()],
                       key=lambda d: d.stat().st_mtime, reverse=True)
        out[fam] = cands[0] if cands else None
    return out


def dir_size_mb(d):
    return sum(os.path.getsize(os.path.join(r, f))
               for r, _dd, fs in os.walk(d) for f in fs) / 1048576.0


def main():
    ap = argparse.ArgumentParser(description="核验打包好的 exe")
    ap.add_argument("--dir", default=None, help="出口目录（缺省取最新的 音频工具箱-v*）")
    ap.add_argument("--no-launch", action="store_true", help="只核清单，不启动 GUI")
    args = ap.parse_args()

    roots = family_roots(args.dir)
    if not roots.get("audio") or not roots["audio"].is_dir():
        print("[FAIL] 找不到「音频工具箱」出口目录。用 --dir 指定，或设置 PT_EXE_ROOT。")
        print("       出口根：%s" % EXE_ROOT)
        return 1

    ok_all = True
    print("=" * 76)
    for fam in sorted(roots):
        print("出口目录[%s]：%s" % (fam, roots[fam] or "（未找到）"))
    print("=" * 76)
    print("① 工具产物")
    print("-" * 76)

    def app_dir(cn, fam):
        r = roots.get(fam)
        return (r / cn) if r else None

    for key, cn, fam in APPS:
        d = app_dir(cn, fam)
        exe = (d / (cn + ".exe")) if d else None
        if not d or not d.is_dir():
            print("[MISS] %-28s 目录不存在（%s，家族 %s）" % (cn, key, fam))
            ok_all = False
            continue
        n = sum(len(fs) for _r, _dd, fs in os.walk(d))
        has = exe.is_file()
        ok_all = ok_all and has
        print("[%s] %-28s %6.1f MB  %4d 文件  exe=%s"
              % ("OK" if has else "NO", cn, dir_size_mb(d), n,
                 ("%.2f MB" % (exe.stat().st_size / 1048576.0)) if has else "缺"))

    print()
    print("② 关键附属文件")
    print("-" * 76)
    for label, cn, rel, fam in CHECKS:
        d = app_dir(cn, fam)
        p = (d / rel) if d else None
        ok = bool(p) and p.exists()
        ok_all = ok_all and ok
        print("[%s] %s" % ("OK" if ok else "MISS", label))

    for label, cn, rel, fam in OPTIONAL_CHECKS:
        d = app_dir(cn, fam)
        p = (d / rel) if d else None
        print("[%s] %s" % ("OK" if (p and p.exists()) else "INFO", label))

    if args.no_launch:
        print()
        print("结论：%s（未启动 GUI）" % ("全部通过" if ok_all else "有缺项，见上"))
        return 0 if ok_all else 1

    print()
    print("③ 真实启动 + 顶层窗口枚举")
    print("-" * 76)
    for key, cn, fam in APPS:
        d = app_dir(cn, fam)
        exe = (d / (cn + ".exe")) if d else None
        if not exe or not exe.is_file():
            continue
        try:
            proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
        except Exception as e:
            print("[FAIL] %-28s 启动异常：%s" % (cn, e))
            ok_all = False
            continue
        time.sleep(3.5)
        alive = proc.poll() is None
        wins = windows_of_pid(proc.pid)
        time.sleep(0.6)
        wins = windows_of_pid(proc.pid)
        residual = [w for w in wins if w[0].strip().lower() in ("tk", "")]
        # ⚠️ 崩溃框必须判 FAIL，不能只看「进程存活 + 有窗口」。
        # 2026-09-26 实测教训：pt-tools 因 `_DND_BASE` 未定义（NameError）在
        # import 期就崩，PyInstaller 弹「Unhandled exception in script」框，
        # 进程**仍存活**、**确有顶层窗口** → 旧版判据全绿，把一个「双击即崩」
        # 的缺陷放行了三个版本（v2.6.6 / v2.7.0 / v2.8.0）。
        crash = [w for w in wins if _is_crash_box(w[0])]
        if not alive or residual or crash:
            ok_all = False
        good = alive and not residual and not crash
        print("[%s] %-28s 进程存活=%s  顶层窗口=%d%s"
              % ("OK" if good else "WARN", cn, alive, len(wins),
                 "  ⚠崩溃框=%d" % len(crash) if crash else ""))
        for t, c, vis in wins:
            print("        · title=%-34r class=%-14s visible=%s" % (t, c, vis))
        if residual:
            print("      ⚠ 疑似残留空窗（历史坑）：%s" % residual)
        if crash:
            print("      ✗ 崩溃框（程序没起来，只是弹了错误框）：%s"
                  % [w[0] for w in crash])
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
