# -*- coding: utf-8 -*-
"""后台命令执行 + PTSL 在线探测（W1 三层拆分 · worker/runner）。

CmdWorker：subprocess → reader 线程喂队列 → 主线程 poll 刷新 UI；
失败即停、可取消（terminate → taskkill 树）、无输出看门狗。
仅操作本工具自己 spawn 的 venv python 子树，绝不碰 ProTools.exe。
"""
import os
import socket
import subprocess
import threading
import time

from ptools.core.logs import LOG_FILE
from ptools.core.i18n import T

from ptools.core.settings import (
    APP_VERSION, CONFIG_FILE, build_date,
    CREATE_NO_WINDOW, PTSL_HOST, PTSL_PORT,
)

# ---------------------------------------------------------------------------
# PTSL 在线探测（socket 端口，零依赖）
# ---------------------------------------------------------------------------

def ptsl_online():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect((PTSL_HOST, PTSL_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def kill_process_tree(proc):
    """终止子进程整棵树：Windows 走 taskkill /T /F，其他平台退回 kill()。

    ⚠️ 红线：只对**本工具自己 spawn 出来的 venv python 子树**调用，
       绝不碰 ProTools.exe —— 传错 pid 会连带杀掉用户的工程。
    """
    pid = getattr(proc, "pid", None)
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW, timeout=20)
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 后台命令执行（subprocess -> 队列 -> 主线程刷新 UI）
# ---------------------------------------------------------------------------

class CmdWorker(threading.Thread):
    """命令队列执行器：逐条 subprocess，全部输出进队列，失败即停。

    v1.1.0：接受单条命令或命令列表（多导出模式一次勾选 → 多条命令顺序跑）。
    每条之间发 ("step", i/n) 供日志分节；结束发 ("done", 汇总退出码)
    ——任一条非零即停并以其退出码收场。

    v1.3.0 卡死专项（Q12）：
      * stdout 读取改由**独立 reader 线程**喂队列，主线程只 poll() 轮询。
        旧写法 `for line in self.proc.stdout` 在子进程不关 pipe 时永不返回，
        而 `cancelled` 标志全仓无人置 True —— 于是"活着但不出活"时 UI 完全
        无法感知、也无法打断，表现为 exe 假死。
      * `cancel()` 真正可用：terminate → 等 1.5s → kill_process_tree()。
      * 无输出看门狗：`NO_OUTPUT_TIMEOUT` 秒内 stdout 一行都没有 →
        发 ("stall", 秒数) 让 UI 红字告警（不自动杀，交给人判断）。
      * 每次收到输出发 ("tick",) 供 UI 刷新"已运行 / 距上次输出"计时。
    """

    NO_OUTPUT_TIMEOUT = 300   # 秒：无任何 stdout 输出即告警

    def __init__(self, cmds, out_queue):
        super().__init__(daemon=True)
        if cmds and isinstance(cmds[0], str):
            cmds = [cmds]  # 兼容单命令
        self.cmds = cmds
        self.out_queue = out_queue
        self.proc = None
        self.cancelled = False
        self._reader = None
        self._last_out = time.time()
        self.started_at = time.time()

    # ---------------- 取消（UI「中止」按钮 / 关窗口时调用）----------------

    def cancel(self):
        """请求中止：置标志 → terminate → 1.5s 内未退则杀进程树。"""
        self.cancelled = True
        proc = self.proc
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=1.5)
            return
        except Exception:
            pass
        kill_process_tree(proc)

    # ---------------- 内部 ----------------

    def _pump(self):
        """reader 线程体：stdout 逐行进队列；pipe 关闭即自然退出。"""
        try:
            for line in self.proc.stdout:
                self._last_out = time.time()
                self.out_queue.put(("line", line))
                self.out_queue.put(("tick", None))
        except (ValueError, OSError):
            pass

    def _run_one(self, cmd):
        """跑一条命令，返回退出码；-1 表示被中止/卡死。"""
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # 找不到 python 等
            self.out_queue.put(("line", T("err_cmd_start") % exc))
            return 1
        self._last_out = time.time()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        stalled = False
        while True:
            if self.cancelled:
                break
            if self.proc.poll() is not None:
                break
            if time.time() - self._last_out > self.NO_OUTPUT_TIMEOUT:
                stalled = True
                break
            time.sleep(0.2)
        if stalled:
            self.out_queue.put(("stall", int(time.time() - self._last_out)))
            self.cancel()
            self._reader.join(timeout=3)
            return -1
        if self.cancelled:
            self._reader.join(timeout=3)
            return -1
        self.proc.wait()
        self._reader.join(timeout=5)
        return self.proc.returncode

    def run(self):
        total = len(self.cmds)
        rc = 0
        for i, cmd in enumerate(self.cmds):
            if self.cancelled:
                break
            if total > 1:
                self.out_queue.put(("line",
                                    "\n──── [%d/%d] ────\n" % (i + 1, total)))
            rc = self._run_one(cmd)
            if self.cancelled:
                rc = -1
                break
            if rc != 0:
                if i < total - 1:
                    self.out_queue.put((
                        "line",
                        T("err_cmd_stop") % (i + 1, total - i - 1)))
                break
        self.out_queue.put(("done", rc))


def build_diag_bundle(zip_path):
    """导出诊断包 zip = 日志 + 配置 + 版本号（W2 完整版的第 5 步）。

    从 worker 层收集 core 的日志/配置路径打成 zip，不碰 Pro Tools 数据，
    不上传任何内容 —— 纯本地打包，供用户把「报障包」交给排查方。
    """
    import zipfile
    from datetime import datetime
    entries = []
    for arc, src in (("pt-tools.log", LOG_FILE),
                     ("config.json", CONFIG_FILE)):
        if os.path.isfile(src):
            entries.append((arc, src))
    v = ("pt-tools v%s (%s) · diag %s\n"
         % (APP_VERSION, build_date(),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("version.txt", v)
        for arc, src in entries:
            z.write(src, arc)
    return (zip_path, len(entries) + 1)
