#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标签页公共底座：配置存取 + 路径工具 + 后台任务执行。

三条设计约定（都是「踩过坑」之后加的）：

1. **配置按前缀隔离**：每页只认自己那批 key（如导入页只认 `import_*`），
   保存时合并写回、不碰别页的字段。这样三页各自「保存配置」互不干扰。

2. **长任务一律走线程 + 队列**：GUI 主线程里跑 ffmpeg / 解密会冻结界面，
   用户会以为程序死了。统一走 `run_async()`。

3. **标准输出重定向**：核心模块全是 `print` 驱动的（原本是给 CLI 用的），
   重定向到队列就能变成实时日志，不用改动核心代码。
"""

import json
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import main as core


class QueueWriter:
    """把 print 输出送进线程安全队列，供 UI 主线程轮询显示。"""

    def __init__(self, q: queue.Queue, tee=None):
        self.q = q
        self.tee = tee            # 可选的额外接收端（如文件）

    def write(self, s: str):
        if not s:
            return
        self.q.put(s)
        if self.tee is not None:
            try:
                self.tee.write(s)
            except Exception:
                pass

    def flush(self):
        pass


class BaseTab(ttk.Frame):
    """标签页基类：统一提供配置读写、日志、异步执行。"""

    #: 本页负责的配置键（子类覆写）。保存/载入只碰这些键。
    config_keys: tuple = ()

    #: 标签标题
    title = "标签页"

    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.cfg = app.cfg                      # 共享的配置字典（内存）
        self.running = False
        self._log = None                        # 由 build() 里创建

    # ───────────── 子类实现 ─────────────

    def build(self):
        """构建界面。子类必须实现。"""
        raise NotImplementedError

    def collect(self):
        """把控件值写回 self.cfg。子类实现。"""
        return

    def apply_config(self):
        """把 self.cfg 的值刷回本页控件（与 collect 反向）。

        用途：菜单「重新载入配置」「默认路径设置」写盘后，界面要跟着更新。
        子类把「collect 里读控件的字段」在这里反向写一遍即可；
        未实现的页继承空实现，界面不会崩。
        """
        return

    def on_show(self):
        """本页被切到前台时调用（用于刷新状态显示）。"""
        return

    # ───────────── 配置 ─────────────

    def save_config(self, quiet: bool = False):
        """合并式保存：只更新本页的键，别页配置原样保留。"""
        try:
            self.collect()
        except Exception as e:
            self.log(f"✗ 读取界面值失败: {e}\n")
            return
        try:
            path = core.config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            disk = {}
            if path.is_file():
                try:
                    disk = json.loads(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    disk = {}
            disk.update({k: self.cfg.get(k) for k in self.config_keys})
            path.write_text(json.dumps(disk, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            if not quiet:
                self.log(f"✓ 配置已保存: {path}\n")
        except Exception as e:
            self.log(f"✗ 配置保存失败: {e}\n")

    # ───────────── 日志 ─────────────

    def make_log(self, parent, height=14, tip: str = ""):
        """在 parent 里放一个只读日志窗，返回 Text 控件。"""
        box = ttk.LabelFrame(parent, text="运行日志", padding=6)
        box.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        text = tk.Text(box, height=height, wrap="word", state="disabled",
                       background="#1e1e1e", foreground="#d4d4d4",
                       font=("Consolas", 9))
        sb = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._log = text
        if tip:
            self.log(tip)
        return text

    def log(self, text: str):
        """线程安全地追加日志（主线程直接写，工作线程走队列）。"""
        if self._log is None:
            return
        if threading.current_thread() is threading.main_thread():
            self._log.configure(state="normal")
            self._log.insert("end", text)
            self._log.see("end")
            self._log.configure(state="disabled")
        else:
            self.app.msg_queue.put(("__tablog__", self, text))

    def clear_log(self):
        if self._log is not None:
            self._log.configure(state="normal")
            self._log.delete("1.0", "end")
            self._log.configure(state="disabled")

    # ───────────── 异步执行 ─────────────

    def run_async(self, fn, on_done=None, busy_text="处理中…", btn=None):
        """在后台线程跑 fn()；期间禁用 btn、把 stdout 接到本页日志。"""
        if self.running:
            return
        self.running = True
        self.log("\n" + "─" * 46 + "\n")

        def worker():
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = QueueWriter(self.app.msg_queue)
            err = None
            try:
                fn()
            except Exception as e:                     # 核心模块的异常不该炸掉界面
                err = e
                self.app.msg_queue.put(("__tablog__", self, f"\n✗ 执行异常: {e}\n"))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                self.app.msg_queue.put(("__done__", self, on_done, err))

        if btn is not None:
            btn.configure(state="disabled", text=busy_text)
        threading.Thread(target=worker, daemon=True).start()

    def finish(self, on_done, err, btn, idle_text):
        """工作线程结束后由主线程调用（框架自动接好）。"""
        self.running = False
        if btn is not None:
            try:
                btn.configure(state="normal", text=idle_text)
            except Exception:
                pass
        if on_done is not None:
            try:
                on_done(err)
            except Exception as e:
                self.log(f"✗ 收尾处理失败: {e}\n")

    # ───────────── 常用小控件 ─────────────

    @staticmethod
    def path_row(parent, row, label, var, pick, hint="", col_hint=3):
        """一行「标签 + 输入框 + 浏览按钮 + 灰色提示」。"""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(parent, textvariable=var, width=50).grid(
            row=row, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(parent, text="浏览…", command=pick).grid(row=row, column=2, padx=4)
        if hint:
            ttk.Label(parent, text=hint, foreground="#888").grid(
                row=row, column=col_hint, sticky="w", padx=4)

    @staticmethod
    def ask_dir(title="选择目录", initial: str = "") -> str:
        from tkinter import filedialog
        return filedialog.askdirectory(title=title, initialdir=initial or None) or ""

    @staticmethod
    def ask_file(title="选择文件", initial: str = "", filetypes=None) -> str:
        from tkinter import filedialog
        return filedialog.askopenfilename(title=title, initialdir=initial or None,
                                          filetypes=filetypes) or ""

    @staticmethod
    def open_in_explorer(path: str):
        """在资源管理器里打开目录（或选中文件）。"""
        import os
        p = Path(path)
        try:
            if p.is_dir():
                os.startfile(str(p))                    # type: ignore[attr-defined]
            elif p.is_file():
                os.startfile(str(p.parent))             # type: ignore[attr-defined]
            else:
                raise FileNotFoundError(path)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("无法打开", f"打开失败：{e}\n{path}")


def default_draft_root() -> Path:
    """剪映草稿根目录：优先用配置里设置的草稿目录（input_dir，存在即用），
    否则回落自动定位（AppData 剪映默认位置）。

    v2.6.3：出厂默认草稿库迁到 Jianying-Backup 后，**导入页的草稿下拉
    也必须列新库** —— 旧版写死 DEFAULT_JIANYING_DRAFT_ROOT，配置里
    改了草稿目录对导入页完全不生效，两页看到的草稿库不一致。
    """
    try:
        disk = core.load_config(core.config_path()) or {}
        p = Path(str(disk.get("input_dir", "") or "").strip())
        if p.is_dir():
            return p
    except Exception:
        pass
    return core.DEFAULT_JIANYING_DRAFT_ROOT


def list_drafts(root: Path):
    """列出草稿目录下的草稿（供下拉选择）。"""
    try:
        return core.scan_drafts(root) if root and Path(root).exists() else []
    except Exception:
        return []
