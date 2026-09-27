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


# ──────────────────── 通用 GUI 助手（S7 / S8，2026-09-27）────────────────────

def center_on_parent(win, parent=None, w=None, h=None):
    """把 Toplevel 摆到父窗口正中央并强制冒头 —— 双屏下不再躲到另一块屏。

    S7（v3.7.0）背景：人类双屏，剪映导出时弹窗（补项目名 / 无法识别输入）
    开在另一块屏或被主窗口盖住，而 `grab_set()` 把主窗口锁死 → 人类看到
    的現象就是「点完导出程序卡死了」。

    三保险（见 [[19-2026-09-27-卡死根治与交互优化方案]] 步 7.1）：
        ① 本函数：居中 + clamp 到主屏 + 短暂 topmost + 抢焦点 + 响一声；
        ② `BaseTab.alert_line`：弹窗前在日志区留一行醒目提醒；
        ③ 状态栏显示「等待你确认…」。

    topmost **300ms 后自动撤销** —— 只保证冒头，不赖在别人窗口上面。
    """
    try:
        win.update_idletasks()
    except Exception:
        pass
    try:
        if parent is not None:
            try:
                parent.update_idletasks()
                px, py = parent.winfo_rootx(), parent.winfo_rooty()
                pw, ph = parent.winfo_width(), parent.winfo_height()
            except Exception:
                px, py, pw, ph = 0, 0, 0, 0
            try:
                parent.deiconify()
                parent.lift()
            except Exception:
                pass
        else:
            px, py, pw, ph = 0, 0, 0, 0
        ww = int(w or win.winfo_reqwidth() or 480)
        wh = int(h or win.winfo_reqheight() or 240)
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, min(px + (pw - ww) // 2, max(0, sw - ww)))
        y = max(0, min(py + (ph - wh) // 2, max(0, sh - wh)))
        win.geometry("%dx%d+%d+%d" % (ww, wh, x, y))
        win.lift()
        try:
            win.attributes("-topmost", True)
            win.after(300, lambda: win.attributes("-topmost", False)
                      if win.winfo_exists() else None)
        except Exception:
            pass
        win.focus_force()
        try:
            win.bell()      # 裁决⑯：响一声，双屏更容易注意到
        except Exception:
            pass
    except Exception:
        pass


def elide_middle(text, max_chars=48):
    """长路径中间省略：`D:\\a\\b\\…\\法老正在做的`（S8：只读预览用）。

    ⚠️ 只用于**只读文本**（Label / 预览），不要写回 StringVar ——
    省略后的值会被 collect() 当成真实路径存进配置。
    """
    s = str(text or "")
    if len(s) <= max_chars:
        return s
    head = max(8, max_chars // 3)
    tail = max_chars - head - 3
    if tail <= 0:
        return s[:max(1, max_chars - 1)] + "…"
    return s[:head] + "…" + s[-tail:]


def attach_path_tip(widget, var):
    """给路径输入框挂悬停提示：窗口窄、路径被截断时鼠标停一下看全文。"""
    state = {"win": None}

    def hide(_e=None):
        if state["win"] is not None:
            try:
                state["win"].destroy()
            except Exception:
                pass
            state["win"] = None

    def show(_e=None):
        try:
            txt = var.get() if var is not None else ""
        except Exception:
            txt = ""
        if not txt or state["win"] is not None:
            return
        try:
            w = tk.Toplevel(widget)
            w.wm_overrideredirect(True)
            ttk.Label(w, text=txt, background="#ffffe0", relief="solid",
                      borderwidth=1, padding=4, wraplength=560,
                      justify="left").pack()
            w.geometry("+%d+%d" % (widget.winfo_rootx() + 8,
                                   widget.winfo_rooty() + widget.winfo_height() + 4))
            state["win"] = w
        except Exception:
            pass

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)
    widget.bind("<ButtonPress>", hide)
    return widget


def _ui_log(text):
    """把界面日志同步写进文件（S7）。

    旧版界面日志只活在 Text 控件里，窗口一关就蒸发 —— 卡死现场永远查不到。
    写盘失败一律静默：日志是诊断手段，绝不能反过来把界面搞崩。
    """
    try:
        lg = core.setup_logging()
        if lg is not None:
            lg.info("[UI] %s", str(text).rstrip("\n"))
    except Exception:
        pass


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


class ScrollableFrame(ttk.Frame):
    """纵向可滚动容器。构造参数与 ttk.Frame 相同，另接受 padding。"""

    def __init__(self, master, padding=10, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, takefocus=1)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.vsb.pack(side="right", fill="y")
        self.hsb.pack(side="bottom", fill="x")
        self._hsb_shown = True
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # add="+"：多个实例（多个页签）都挂全局滚轮，互不覆盖；
        # 实际只滚"鼠标所在子树"对应的实例（见 _on_wheel）。
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")
        # S8：中键拖拽平移（抓手手感）
        self.canvas.bind("<ButtonPress-2>", self._pan_start)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._pan_end)
        self.canvas.bind("<ButtonPress-1>", lambda _e: self.canvas.focus_set())
        # S8：键盘（canvas 需先获得焦点）
        self.canvas.bind("<Home>", lambda _e: self.canvas.xview_moveto(0.0))
        self.canvas.bind("<End>", lambda _e: self.canvas.xview_moveto(1.0))
        self.canvas.bind("<Prior>", lambda _e: self.canvas.yview_scroll(-1, "pages"))
        self.canvas.bind("<Next>", lambda _e: self.canvas.yview_scroll(1, "pages"))
        self.canvas.bind("<Up>", lambda _e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Down>", lambda _e: self.canvas.yview_scroll(1, "units"))
        self._acc = 0          # delta 累加器
        self._pan = None       # 中键拖拽起点

    def _on_canvas_configure(self, e):
        # S3（v3.5.0）：inner 宽度 = max(内容需求宽, 画布宽)。窄窗时拉伸填满；
        # 内容超宽时 inner 不被压成窗口宽（旧版强制等宽，超宽按钮被挤成
        # 文字消失却仍可点，最坑）。
        req = self.inner.winfo_reqwidth()
        self.canvas.itemconfigure(self._win, width=max(req, e.width))
        # S8：横滚条按需显隐 —— 不占高度，也不让每个页看着像「内容塞不下」
        try:
            need = req > e.width + 4
            if need and not self._hsb_shown:
                self.hsb.pack(side="bottom", fill="x")
                self._hsb_shown = True
                self._hint_hscroll()
            elif not need and self._hsb_shown:
                self.hsb.pack_forget()
                self._hsb_shown = False
        except Exception:
            pass

    def _hint_hscroll(self):
        """横滚条首次出现时，右下角淡出一条手势提示（只提示一次）。

        Shift+滚轮是「隐藏手势」，不写出来没人知道 —— 这是横向滚动
        「体验不好」的第一条原因。
        """
        if getattr(self, "_hint_shown", False):
            return
        self._hint_shown = True
        try:
            lbl = tk.Label(self.canvas, text="Shift+滚轮 / 中键拖拽 可横向查看",
                           bg="#333333", fg="#ffffff", padx=8, pady=4)
            lbl.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)
            self.after(4000, lbl.destroy)
        except Exception:
            pass

    # ───────── 中键拖拽平移 ─────────

    def _pan_start(self, e):
        self._pan = (e.x, e.y, self.canvas.canvasx(0), self.canvas.canvasy(0))
        try:
            self.canvas.configure(cursor="fleur")
        except Exception:
            pass

    def _pan_move(self, e):
        if not self._pan:
            return
        x0, y0, cx0, cy0 = self._pan
        dx, dy = e.x - x0, e.y - y0
        try:
            bbox = self.canvas.bbox("all")
            if not bbox:
                return
            tw = max(1.0, float(bbox[2] - bbox[0]))
            th = max(1.0, float(bbox[3] - bbox[1]))
            self.canvas.xview_moveto(min(1.0, max(0.0, (cx0 - dx) / tw)))
            self.canvas.yview_moveto(min(1.0, max(0.0, (cy0 - dy) / th)))
        except Exception:
            pass

    def _pan_end(self, _e=None):
        self._pan = None
        try:
            self.canvas.configure(cursor="")
        except Exception:
            pass

    # ───────── 滚轮 ─────────

    def _on_wheel(self, e):
        # 鼠标下的控件不在本容器子树内 → 不是本页的事，跳过
        # （切到别的页签 / 弹窗上 / 已销毁实例，全都自然短路）
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return
        inside = False
        x = w
        while x is not None:
            if x is self.canvas:
                inside = True
                break
            x = getattr(x, "master", None)
        if not inside:
            return
        # 鼠标落在自身可滚的控件上时让位（Text/Listbox/Treeview/Combobox）
        x = w
        while x is not None and x is not self.canvas:
            if isinstance(x, (tk.Text, tk.Listbox, tk.Toplevel, ttk.Treeview, ttk.Combobox)):
                return
            x = getattr(x, "master", None)

        delta = int(getattr(e, "delta", 0) or 0)
        if delta == 0:
            return

        # 横向：Shift(0x0001) 或 Ctrl(0x0004) 按住 → 按像素横滚（跟手）
        if e.state & 0x0001 or e.state & 0x0004:
            try:
                self.canvas.xview_scroll(-delta, "pixels")
            except Exception:
                pass
            return

        # 纵向：delta 累加器 —— 触控板小幅度不再被 int(delta/120)=0 吞掉
        self._acc = getattr(self, "_acc", 0) + delta
        steps = 0
        while abs(self._acc) >= STEP_DELTA:
            step = 1 if self._acc > 0 else -1
            steps += step
            self._acc -= step * STEP_DELTA
        if steps:
            try:
                self.canvas.yview_scroll(-steps, "units")
            except Exception:
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
        self._stage = ""                        # S7：当前阶段名（心跳日志读它）
        self._hb_stop = None                    # S7：心跳线程的停止信号

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
        """线程安全地追加日志（主线程直接写，工作线程走队列）。

        S7：主线程这一路顺带写文件日志（工作线程那一路由 `_poll_queue`
        统一落盘），保证关窗后现场还在。
        """
        if self._log is None:
            return
        if threading.current_thread() is threading.main_thread():
            self._log.configure(state="normal")
            self._log.insert("end", text)
            self._log.see("end")
            self._log.configure(state="disabled")
            _ui_log(text)
        else:
            self.app.msg_queue.put(("__tablog__", self, text))

    # ───────────── S7：弹窗三保险 + 阶段心跳 ─────────────

    def alert_line(self, text: str):
        """（弹窗之前调用）在日志区留一行醒目提醒。

        双屏下弹窗可能开在另一块屏，主窗口被 `grab_set` 锁死 → 人类看到
        的就是「程序卡死」。居中置顶之外再多这一行，哪怕还是没看见，
        事后翻日志也知道程序当时在等什么。
        """
        self.log("\n" + "⚠ " + text + "\n")

    def set_stage(self, text: str):
        """标记当前阶段名（供心跳线程写日志；工作线程里可安全调用）。"""
        self._stage = text

    @staticmethod
    def _hb_sec():
        """心跳间隔（秒），配置键 `heartbeat_sec`，默认 5。"""
        try:
            cfg = core.load_config(core.config_path()) or {}
            return max(1.0, float(cfg.get("heartbeat_sec", 5) or 5))
        except Exception:
            return 5.0

    def warn(self, title, msg):
        """居中且置顶的告警框 —— 替代原生 `messagebox`（它无法定位）。"""
        top = self.winfo_toplevel()
        win = tk.Toplevel(top)
        win.title(title)
        win.transient(top)
        win.resizable(False, False)
        ttk.Label(win, text=msg, wraplength=520, justify="left").pack(
            padx=16, pady=(14, 8), anchor="w")
        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(bar, text="确定", command=win.destroy).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self.alert_line("弹出窗口「%s」，等你确认后才会继续。"
                        "若没看到，请检查另一块屏或按 Alt+Tab 找一下。" % title)
        center_on_parent(win, top)
        win.grab_set()
        # 三保险③：状态栏显示等待态（弹窗万一还是没被看见，主窗口会说话）
        app = getattr(self, "app", None)
        try:
            if app is not None and hasattr(app, "set_waiting"):
                app.set_waiting("等待你确认：%s" % title)
        except Exception:
            pass
        win.wait_window()
        try:
            if app is not None and hasattr(app, "set_waiting"):
                app.set_waiting(None)
        except Exception:
            pass

    def error(self, title, msg):
        """居中且置顶的错误框 —— 替代原生 `messagebox.showerror`。"""
        self.warn(title, msg)

    def clear_log(self):
        if self._log is not None:
            self._log.configure(state="normal")
            self._log.delete("1.0", "end")
            self._log.configure(state="disabled")

    def _trim_log(self, max_lines=4000):
        """日志行数超限时裁掉最旧的，防止长导出把 Text 控件撑爆（AppHang 主因之一）。
        调用时日志控件必须处于 state="normal"。"""
        if self._log is None:
            return
        try:
            n = int(self._log.index("end-1c").split(".")[0])
        except Exception:
            return
        if n > max_lines:
            self._log.delete("1.0", "%d.0" % (n - max_lines))

    # ───────────── 异步执行 ─────────────

    def run_async(self, fn, on_done=None, busy_text="处理中…", btn=None):
        """在后台线程跑 fn()；期间禁用 btn、把 stdout 接到本页日志。"""
        if self.running:
            return
        self.running = True
        self.log("\n" + "─" * 46 + "\n")
        _log = core.setup_logging()
        if _log is not None:
            _log.info("任务开始：%s（%s）",
                      self.title, getattr(fn, "__name__", str(fn)[:80]))

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
        # S7：心跳线程 —— 每 N 秒把「当前阶段 + 已运行秒数」写进文件日志。
        # 卡住时最后一条心跳就是定位依据（旧版只有开始/结束两条，查无可查）。
        stop = threading.Event()
        self._hb_stop = stop

        def beat():
            import time as _t
            t0 = _t.monotonic()
            while not stop.wait(self._hb_sec()):
                try:
                    lg = core.setup_logging()
                    if lg is not None:
                        lg.info("[心跳] %s ｜ 阶段=%s ｜ 已运行 %ds",
                                self.title, self._stage or "（未标记）",
                                int(_t.monotonic() - t0))
                except Exception:
                    pass

        threading.Thread(target=beat, daemon=True).start()

    def finish(self, on_done, err, btn, idle_text):
        """工作线程结束后由主线程调用（框架自动接好）。"""
        if self._hb_stop is not None:      # S7：任务结束，停心跳
            self._hb_stop.set()
            self._hb_stop = None
        self.running = False
        _log = core.setup_logging()
        if _log is not None:
            _log.info("任务结束：%s —— %s", self.title,
                      ("成功" if err is None else "失败：%s" % err))
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
        """一行「标签 + 输入框 + 浏览按钮 + 灰色提示」。

        S8：输入框**不再写死 width=50**（≈400px，是「横向截断」的源头 ——
        加上标签和按钮必然超出 880 宽的窗口）。改为随窗口伸缩 + 悬停看全文。
        """
        try:
            parent.columnconfigure(1, weight=1)
        except Exception:
            pass
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        e = ttk.Entry(parent, textvariable=var, width=1)
        e.grid(row=row, column=1, sticky="we", padx=4, pady=3)
        attach_path_tip(e, var)
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

    v2.6.3：出厂默认草稿库迁到 Backup-Jianying 后，**导入页的草稿下拉
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
