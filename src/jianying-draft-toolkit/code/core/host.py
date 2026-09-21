#!/usr/bin/env python3
"""core/host.py — 进程 / 端口探测封装（L0 卡顿修复 + L1 分层起点）

把原本散落在 ``main.pro_tools_status`` / ``import_audio.jianying_running`` 的
「前置条件探测」收敛到一处，且全部可在后台线程跑，避免阻塞 UI 主线程。

本模块 **只依赖标准库**，不 import tkinter / main / import_audio，
因此可被 GUI、CLI、单测任意引用，无环依赖。

L0 卡顿根因与修复：
  原 ``gui._refresh_status`` 在主线程跑 tasklist + 网络探活（离线时要等 0.6s 超时），
  并每 6 秒递归轮询一次 → UI 周期性卡顿。
  现改为：探测放进 worker 线程（StatusProbe），UI 线程只在回调里更新标签；
  轮询改为「启动一次 + 切页 + 手动刷新」。

L0.5 黑窗与切页卡顿修复（2026-09-19 实测反馈）：
  症状①：双击 exe 后**反复弹出 cmd 黑窗**。
  根因：``--windowed`` 打包的进程没有控制台可继承，每次 ``subprocess.run(["tasklist", ...])``
        都会为子进程新建一个控制台窗口，一次探测调两次 → 弹两个黑窗。
  修复：所有子进程加 ``CREATE_NO_WINDOW``（0x08000000），非 Windows 平台自动忽略。

  症状②：三个标签页来回切换仍卡顿。
  根因：``_on_tab_changed`` 每次都触发探测，而 ``StatusProbe._running`` 只能挡住
        「正在跑的那一次」，挡不住「跑完之后紧接着又来一次」；快速切页 →
        探测一个接一个排队，每次都烧 ~1s（tasklist 全量 0.56s + 过滤 0.43s）。
  修复：① 加**最短重探间隔**（默认 8s），窗口内重复请求直接复用缓存、不再起线程；
        ② 剪映进程检测**合并成一次全量 tasklist**，PT 的判断改从同一份输出里取，
        一次探测从「2 次子进程」压到「1 次」。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Tuple

# Pro Tools PTSL 服务端口（本地环回）。
PT_URL = "http://localhost:31416"

# 剪映 / 必剪（CapCut）进程关键字。
_JIANYING_KEYWORDS = ("jianyingpro", "capcut")

# PT 主进程关键字（与 tasklist 输出的小写比对）。
_PT_KEYWORDS = ("protools.exe",)

# Windows：让子进程不弹控制台黑窗。
# --windowed 打包的进程自身无控制台，子进程默认会新建一个窗口。
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# tasklist 输出缓存（进程在 / 不在几秒内不会变，缓存可省掉 ~0.5s 的枚举）。
_TASKLIST_CACHE: dict = {}
_TASKLIST_LOCK = threading.Lock()


def _no_window_kwargs() -> dict:
    """返回抑制子进程黑窗的 Popen 关键字（非 Windows 平台为空 dict）。

    供本模块用；其他模块请用 ``subprocess_kwargs()``（公开别名）。
    """
    return subprocess_kwargs()


def subprocess_kwargs(**extra) -> dict:
    """通用子进程关键字：Windows 下抑制黑窗 + 合并调用方额外参数。

    用法（替换裸 ``subprocess.run(...)``）：

        subprocess.run(cmd, capture_output=True, text=True,
                       **subprocess_kwargs())

    为什么需要：``--windowed`` 打包的 exe **没有控制台可继承**，
    任何子进程都会新建一个控制台窗口 → 界面反复弹 cmd 黑窗。
    加 ``CREATE_NO_WINDOW`` 是唯一根治办法（重定向 stdout 不够，
    本机实测仍然闪窗）。
    """
    kw: dict = {}
    if _CREATE_NO_WINDOW:
        kw["creationflags"] = _CREATE_NO_WINDOW
    kw.update(extra)
    return kw


def _tasklist_csv(filter_expr: str = "", *, use_cache: bool = True,
                  max_age: float = 5.0) -> str:
    """跑一次 ``tasklist`` 并返回小写的 CSV 输出；失败返回空串。

    统一入口，保证：① 永不弹黑窗；② 所有调用方共享同一套超时与编码处理；
    ③ **带缓存** —— 一次 tasklist 全量枚举实测 ~0.45~0.56s，是探测耗时的
    绝对大头；进程「在不在」在几秒内不会变，5 秒内复用同一份输出足以。

    ``use_cache=False`` 时强制重新枚举（诊断场景用）。
    """
    if use_cache:
        with _TASKLIST_LOCK:
            cached = _TASKLIST_CACHE.get("out")
            at = _TASKLIST_CACHE.get("at", 0.0)
        if cached is not None and (time.monotonic() - at) < max_age:
            return cached

    cmd = ["tasklist", "/FO", "CSV", "/NH"]
    if filter_expr:
        cmd += ["/FI", filter_expr]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, encoding="gbk", errors="replace",
            timeout=20, stdin=subprocess.DEVNULL, **_no_window_kwargs())
        out = (r.stdout or "").lower()
    except Exception:
        out = ""
    if out:
        with _TASKLIST_LOCK:
            _TASKLIST_CACHE["out"] = out
            _TASKLIST_CACHE["at"] = time.monotonic()
    return out


def _pt_reachable(timeout: float) -> bool:
    """PTSL 端口探活（独立出来，便于与进程枚举并行）。"""
    try:
        with urllib.request.urlopen(PT_URL, timeout=timeout) as _resp:  # noqa: F841
            return True
    except urllib.error.HTTPError:
        return True               # 有 HTTP 响应即说明端口通了（PTSL 常回 4xx）
    except Exception:
        return False


def pro_tools_status(timeout: float = 1.5, tasklist_out: str = "") -> Tuple[bool, str]:
    """探测 Pro Tools 的 PTSL 服务是否在线，返回 ``(是否在线, 说明文本)``。

    为什么用 HTTP 探活（localhost:31416）而非 import ptsl：
    后者在未装 py-ptsl 时会抛错，而探活能给出「服务在 / 不在」的确定结论，
    且无需把 py-ptsl 打进 exe（剪辑机器上不需要它）。

    ``tasklist_out``：可选的**已获取** tasklist 输出（小写）。传入即复用，
    避免同一次探测里重复枚举进程（见 ``probe_all``）。
    """
    if tasklist_out:
        out = tasklist_out
    else:
        out = _tasklist_csv("IMAGENAME eq ProTools.exe")
    running = any(kw in out for kw in _PT_KEYWORDS)
    reachable = _pt_reachable(timeout)

    if reachable:
        return True, "PTSL 服务在线（可解析 .ptx）"
    if running:
        return False, "Pro Tools 已在运行，但 PTSL 服务未监听（请在 PT 里启用 PTSL / 检查端口 31416）"
    return False, "Pro Tools 未运行 —— 解析 .ptx 需要 PT 在线；离线请改用交付包 json"


def jianying_running(draft_dir: Path, tasklist_out: str = "") -> Tuple[list, list]:
    """检测剪映状态，返回 ``(阻断原因列表, 提示信息列表)``。

    阻断：剪映进程在跑 —— 它的内存态会在保存时覆盖磁盘写入（2026-09-17 实测）。
    提示：.locked 残留 —— 剪映已退出时常见，不阻断写入。

    ``tasklist_out``：可选的**已获取** tasklist 输出（小写），语义同
    ``pro_tools_status``。

    ⚠️ **语义区分（重要）**：本函数是**阻断性判断**，调用方分两类：
      · 状态栏显示 → 可以吃 tasklist 缓存（5 秒误差无妨）
      · **写入前校验** → 必须拿到实时结果，否则「刚打开剪映」会被缓存放过，
        导致写入被剪映内存态覆盖（2026-09-17 踩过的坑）。
    因此写入前校验请显式传 ``tasklist_out=_tasklist_csv(use_cache=False)``。
    """
    blockers, warns = [], []
    out = tasklist_out or _tasklist_csv()
    for kw in _JIANYING_KEYWORDS:
        if kw in out:
            blockers.append(f"检测到剪映进程（{kw}）正在运行，共 {out.count(kw)} 个相关进程")
            break
    lock = draft_dir / ".locked"
    if lock.exists():
        age = time.time() - lock.stat().st_mtime
        if blockers:
            warns.append(f"草稿存在 .locked 锁文件（{int(age)} 秒前更新），草稿正处于打开状态")
        elif age < 900:
            warns.append(f"存在 .locked 残留锁文件（{int(age)} 秒前），剪映进程已退出，视为残留")
        else:
            warns.append(f"存在 .locked 残留锁文件（{int(age/3600)} 小时前），视为陈旧文件")
    return blockers, warns


def jianying_running_realtime(draft_dir: Path) -> Tuple[list, list]:
    """**写入前校验专用**：强制实时枚举进程，绝不吃 tasklist 缓存。

    与 ``jianying_running`` 的区别只在数据新鲜度 —— 语义完全相同。
    分开成独立函数是为了让调用点一眼看出「这里不能缓存」，
    比在两处都写 ``tasklist_out=_tasklist_csv(use_cache=False)`` 更难写错。
    """
    return jianying_running(draft_dir, tasklist_out=_tasklist_csv(use_cache=False))


def probe_all(draft_dir: Path, timeout: float = 0.6) -> dict:
    """一次完整探测：``{"pt": (bool, str), "jianying": bool}``。

    三层优化让单次探测从 ~1.1s 降到「缓存命中时 ≈ timeout」：
      ① **只跑一次 tasklist**（全量），PT 与剪映的判断都从这份输出里取；
      ② tasklist 输出**带 5 秒缓存**，连续探测不再重复枚举进程；
      ③ 进程枚举与端口探活**并行**，总耗时取两者较大者而非相加。
    """
    result: dict = {}

    def _enum():
        result["out"] = _tasklist_csv()

    th = threading.Thread(target=_enum, daemon=True)
    th.start()
    reachable = _pt_reachable(timeout)
    th.join(timeout=25)
    out = result.get("out", "")

    running = any(kw in out for kw in _PT_KEYWORDS)
    if reachable:
        pt = (True, "PTSL 服务在线（可解析 .ptx）")
    elif running:
        pt = (False, "Pro Tools 已在运行，但 PTSL 服务未监听（请在 PT 里启用 PTSL / 检查端口 31416）")
    else:
        pt = (False, "Pro Tools 未运行 —— 解析 .ptx 需要 PT 在线；离线请改用交付包 json")

    try:
        blockers, _ = jianying_running(draft_dir, tasklist_out=out)
        jy = bool(blockers)
    except Exception:
        jy = False
    return {"pt": pt, "jianying": jy}


class StatusProbe:
    """后台线程探测 PT / 剪映状态，结果缓存 + 回调 + 最小重探间隔。

    UI 不直接调用探测函数，而是 ``request(draft_dir, on_done)``：
    探测在 worker 线程跑，``on_done(pt, jianying)`` 也在 worker 线程被调用，
    调用方需自行用 ``root.after(0, ...)`` 切回 UI 线程更新界面。

    三种请求路径（2026-09-19 定稿）：
      A. 没有可用的缓存           → 起线程探测，``on_done`` 在 worker 线程回调
      B. 有缓存但仍在节流窗口内   → **不起线程**，直接回放缓存
      C. 正在探测中，又来新请求   → 挂到 ``_waiters``，本次探测跑完一并回放
                                    （不能静默丢弃 —— 否则用户切页后界面无反馈）

    节流（``min_interval`` 秒）解决「快速切换标签页 → 探测一个接一个排队 →
    界面发涩」；等待者回放解决「点了刷新却毫无动静」。
    """

    def __init__(self, timeout: float = 0.6, min_interval: float = 8.0):
        self._timeout = timeout
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._running = False
        self._cache: dict = {"pt": (False, ""), "jianying": False}
        self._cache_at = 0.0          # 缓存时间戳（time.monotonic）
        self._has_cache = False
        self._waiters: list = []      # 探测进行中挂起的回调

    def get_cached(self) -> dict:
        """返回最近一次探测结果（线程安全拷贝）。"""
        with self._lock:
            return dict(self._cache)

    def request(self, draft_dir: Path,
                on_done: Callable[[Tuple[bool, str], bool], None]) -> None:
        """发起一次探测；节流窗口内回放缓存，探测中则挂钩等待。

        ``on_done(pt_status, jianying_running)`` 在 **worker 线程** 调用，
        调用方需自行切回 UI 线程。
        """
        with self._lock:
            if self._running:
                # 路径 C：正在探测 —— 挂起来，等这轮跑完回放（不丢反馈）
                self._waiters.append(on_done)
                return
            fresh = (self._has_cache
                     and (time.monotonic() - self._cache_at) < self._min_interval)
            if fresh:
                cached = dict(self._cache)     # 路径 B
            else:
                self._running = True           # 路径 A
        if fresh:
            # 不起线程，直接回放缓存（在锁外回调，避免死锁）
            self._emit(on_done, cached.get("pt", (False, "")),
                       bool(cached.get("jianying")))
            return
        t = threading.Thread(target=self._run, args=(draft_dir, on_done), daemon=True)
        t.start()

    @staticmethod
    def _emit(on_done, pt, jy) -> None:
        try:
            on_done(pt, jy)
        except Exception:
            pass

    def _run(self, draft_dir: Path, on_done) -> None:
        result = probe_all(draft_dir, timeout=self._timeout)
        pt = result["pt"]
        jy = bool(result["jianying"])
        with self._lock:
            self._cache = {"pt": pt, "jianying": jy}
            self._cache_at = time.monotonic()
            self._has_cache = True
            self._running = False
            waiters, self._waiters = self._waiters, []
        self._emit(on_done, pt, jy)
        for w in waiters:                      # 回放给等待者
            self._emit(w, pt, jy)
