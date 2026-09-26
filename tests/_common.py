# -*- coding: utf-8 -*-
"""pt-audio-toolkit 回归测试公共模块：路径解析 + 结果分级。

为什么有这个文件（改进方案 A2 · 跨机化）
========================================
原测试脚本写死了开发机路径 —— 解释器
`C:\\Users\\Administrator\\...\\Python312\\python.exe`、仓库
`D:\\Ai-Files\\GitHub-warehouse\\pt-audio-toolkit\\src`、沙箱
`D:\\My-Temporary\\pt-toolkit-test\\sandbox`。换到家用机（用户名 `32112`）
即 FileNotFoundError —— 与 `pt-project-folder-builder/build.ps1` 曾经
写死用户名是同一类缺陷，只是藏在测试资产里。

本模块把机器相关路径一律收敛为「环境变量 → 合理默认 → 明确报错」：

| 名称       | 覆盖用环境变量  | 默认                                                      |
|------------|-----------------|-----------------------------------------------------------|
| `REPO`     | —（位置反推）   | `tests/` 的父目录                                          |
| `PY`       | `PT_TEST_PY`    | 自动探测**带 tkinter** 的解释器                            |
| `TMP`      | `PT_TEST_TMP`   | `D:\\My-Temporary\\pt-toolkit-test`（无 D 盘则回落系统临时区） |
| `EXE_ROOT` | `PT_EXE_ROOT`   | `D:\\Ai-Files\\Agent-Preset\\exe`                          |
| `DRAFT`    | `PT_JY_DRAFT`   | `%LOCALAPPDATA%\\JianyingPro\\...\\com.lveditor.draft`      |

结果分级（改进方案 A3）
=======================
`PASS` 正常 ｜ `SKIP` 环境不满足（Pro Tools 未开等）｜
`FAIL` 断言不成立（产品行为异常）｜ `ERROR` 用例自身抛异常（多为脚本跟不上接口变动）。

退出码：`0` 全通过 ｜ `1` 有 FAIL ｜ `2` 有 ERROR —— 便于将来接 CI。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

# 报告器必须能打印任意文本：控制台默认 GBK，遇到 ✅/→ 之类字符会在
# **打印失败明细时**抛 UnicodeEncodeError，把真正的 FAIL/ERROR 顶掉
# （2026-09-26 实测：core_logic 的真实断言错被这条盖住，报告直接中断）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 结果分级常量 ──────────────────────────────────────────────
PASS, SKIP, FAIL, ERROR = "PASS", "SKIP", "FAIL", "ERROR"
RESULTS = []          # [(name, status, detail)]


class SkipCase(Exception):
    """用例主动跳过（环境不满足）。raise SkipCase("原因") 即可。"""


# ── 路径：仓库 / 源码 ─────────────────────────────────────────
# tests/ 的父目录即仓库根 —— 不写盘符、不写用户名
TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
SRC = REPO / "src"


# ── 路径：解释器（必须带 tkinter）────────────────────────────
def _has_tkinter(py):
    """探活：该解释器能否 import tkinter。托管版通常没有。"""
    try:
        r = subprocess.run([py, "-c", "import tkinter"],
                           capture_output=True, timeout=45)
        return r.returncode == 0
    except Exception:
        return False


def _candidates():
    """按优先级给出候选解释器。"""
    out = []
    env = os.environ.get("PT_TEST_PY")
    if env:
        out.append(env)
    if sys.executable:
        out.append(sys.executable)
    # Windows 常见安装位置（用户名取当前用户，不写死）
    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local) / "Programs" / "Python"
        if base.is_dir():
            for d in sorted(base.iterdir(), reverse=True):
                for exe in ("python.exe", "python3.exe"):
                    p = d / exe
                    if p.is_file():
                        out.append(str(p))
    for name in ("python", "python3"):
        w = shutil.which(name)
        if w:
            out.append(w)
    # 去重保序
    seen, uniq = set(), []
    for c in out:
        k = os.path.normcase(os.path.abspath(c))
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def _resolve_py():
    for c in _candidates():
        if os.path.isfile(c) and _has_tkinter(c):
            return c
    raise RuntimeError(
        "找不到带 tkinter 的 Python 解释器 —— 测试的 GUI 用例需要它。\n"
        "  处置：安装带 tkinter 的 Python 3.12（或设置环境变量 PT_TEST_PY\n"
        "        指向形如 ...\\Python312\\python.exe 的解释器）。\n"
        "  候选已试：%s" % (", ".join(_candidates()) or "（无）"))


PY = _resolve_py()
"""带 tkinter 的解释器绝对路径。"""


def ensure_tk():
    """确保**当前进程**能 import tkinter —— 不能就用 PY 重启自身。

    为什么需要：`PY` 只约束子进程用哪个解释器，管不到本进程。而
    `test_core_logic.py` / `test_wiring.py` 会在本进程内 import 工具的
    GUI 模块（它们自己 `import tkinter`）。若用托管版 Python（无 tkinter）
    直接 `python tests/test_core_logic.py`，会以
    `ModuleNotFoundError: No module named 'tkinter'` 崩掉 —— 看着像产品
    缺陷，实际只是入口解释器选错了。

    这两个脚本在 import 任何被测模块**之前**调用本函数即可自愈：
    无 tkinter 时用 `PY` 原样重启自己（参数透传，环境变量打标防死循环）。
    """
    try:
        import tkinter  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("_PT_TK_REEXEC") == "1":
        raise RuntimeError(
            "重启解释器后仍无 tkinter：%s\n"
            "  处置：安装带 tkinter 的 Python，或用 PT_TEST_PY 指向它。" % PY)
    os.environ["_PT_TK_REEXEC"] = "1"
    print("[_common] 当前解释器无 tkinter，改用 %s 重启本脚本" % PY)
    os.execv(PY, [PY, os.path.abspath(sys.argv[0])] + sys.argv[1:])


# ── 路径：测试临时区（沙箱）──────────────────────────────────
def _resolve_tmp():
    env = os.environ.get("PT_TEST_TMP")
    if env:
        return Path(env)
    d = Path("D:/My-Temporary/pt-toolkit-test")
    try:
        if d.drive and Path(d.drive + os.sep).exists():
            return d
    except Exception:
        pass
    return Path(tempfile.gettempdir()) / "pt-toolkit-test"


TMP = _resolve_tmp()
SANDBOX = TMP / "sandbox"
BUILD_DIR = TMP / "build"
SPEC_DIR = TMP / "spec"
LOG_DIR = TMP / "logs"


def fresh(sub):
    """在沙箱内新建（必要时先清空）子目录，返回绝对路径字符串。

    ⚠️ 只允许操作 TMP 内的路径 —— 越界直接拒绝，防止误删仓库或其他目录。
    """
    p = (TMP / sub).resolve()
    root = TMP.resolve()
    if p != root and root not in p.parents:
        raise RuntimeError("fresh() 越界，拒绝操作：%s" % p)
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def ensure_dirs():
    for d in (TMP, SANDBOX, BUILD_DIR, SPEC_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ── 路径：exe 出口 ───────────────────────────────────────────
EXE_ROOT = Path(os.environ.get("PT_EXE_ROOT", r"D:\Ai-Files\Agent-Preset\exe"))


def exe_dir(version=None, date=None):
    """定位 exe 出口目录。

    给定 version（如 "1.1.0"）与 date（如 "20260923"）→ 拼出
    `pt-audio-toolkit-v<version>-<date>`；未给则取 EXE_ROOT 下最新的一个，
    让核验脚本不必随版本改代码。
    """
    if version and date:
        return EXE_ROOT / ("pt-audio-toolkit-v%s-%s" % (version, date))
    cands = sorted([d for d in EXE_ROOT.glob("pt-audio-toolkit-v*") if d.is_dir()],
                   key=lambda d: d.stat().st_mtime, reverse=True)
    return cands[0] if cands else EXE_ROOT / "pt-audio-toolkit-vUNKNOWN"


# ── 路径：剪映草稿根 ─────────────────────────────────────────
def _resolve_draft():
    env = os.environ.get("PT_JY_DRAFT")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("环境变量 LOCALAPPDATA 缺失，请用 PT_JY_DRAFT 显式指定剪映草稿根")
    return Path(local) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"


DRAFT = _resolve_draft()
"""剪映草稿根（含各剧集草稿子目录）。"""


# ── 用例登记与报告 ───────────────────────────────────────────
def case(name):
    """装饰器版用例：自动判定 PASS / SKIP / FAIL / ERROR 并登记。"""
    def deco(fn):
        try:
            detail = fn() or ""
            RESULTS.append((name, PASS, str(detail)))
        except SkipCase as e:
            RESULTS.append((name, SKIP, str(e)))
        except AssertionError:
            RESULTS.append((name, FAIL, traceback.format_exc()))
        except Exception:
            RESULTS.append((name, ERROR, traceback.format_exc()))
        return fn
    return deco


def run_case(name, fn):
    """命令式版用例（需要传参或提前准备环境时用）。"""
    try:
        detail = fn() or ""
        RESULTS.append((name, PASS, str(detail)))
    except SkipCase as e:
        RESULTS.append((name, SKIP, str(e)))
    except AssertionError:
        RESULTS.append((name, FAIL, traceback.format_exc()))
    except Exception:
        RESULTS.append((name, ERROR, traceback.format_exc()))


def record(name, status, detail=""):
    RESULTS.append((name, status, str(detail)))


def report(title, tail_lines=12):
    """打印汇总并返回退出码（0 全通过 / 1 有 FAIL / 2 有 ERROR）。"""
    icon = {PASS: "PASS", SKIP: "SKIP", FAIL: "FAIL", ERROR: "ERROR"}
    print("=" * 76)
    print(title)
    print("=" * 76)
    for name, status, detail in RESULTS:
        print("[%s] %s" % (icon[status], name))
        if status == PASS:
            one = " ".join(str(detail).split())
            if one:
                print("      -> %s" % one[:150])
        elif status == SKIP:
            print("      ~ %s" % " ".join(str(detail).split())[:150])
        else:
            body = "\n".join(str(detail).strip().splitlines()[-tail_lines:])
            print("      " + body.replace("\n", "\n      "))
    n = {s: sum(1 for _n, st, _d in RESULTS if st == s) for s in (PASS, SKIP, FAIL, ERROR)}
    print("-" * 76)
    print("合计 %d 项：通过 %d ｜ 跳过 %d ｜ 失败 %d ｜ 错误 %d"
          % (len(RESULTS), n[PASS], n[SKIP], n[FAIL], n[ERROR]))
    if n[ERROR]:
        return 2
    if n[FAIL]:
        return 1
    return 0
