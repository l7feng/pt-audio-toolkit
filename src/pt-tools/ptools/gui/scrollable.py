#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ScrollableFrame —— 可滚动容器（G2/J12 2026-09-27；S8 手感重做 2026-09-27）。

⚠️ **同源副本**：本文件、`src/pt-tools/ptools/gui/scrollable.py`、
`src/jianying-draft-toolkit/code/tabs/base.py::ScrollableFrame` **三处同源**，
改一处必须同步三处（工具各自独立打包，不引公共包）。
`tests/test_scroll_sync.py` 会断言三份一致 —— 别绕过它。
同步方法：改本文件后跑 `python tools/sync_scrollable.py`（一次性脚本，
把本文件的类体同步到另外两处）。

用法：页面 build() 里把 ``outer = self`` 换成::

    outer = ScrollableFrame(self, padding=0)   # 页面自带 padding 时传 0
    outer.pack(fill="both", expand=True)
    outer = outer.inner

之后照常向 ``outer`` 上 pack/grid 子控件。窗口不够高时右侧出现滚动条，
鼠标滚轮直接滚动；鼠标指向日志框 / 列表框 / 树等**自身可滚的控件**时
让位给它们，不会双重滚动。

S8（v3.8.0）手感重做，修掉四件事：

1. **触控板小幅度被吞**：旧版 ``int(-delta/120)`` 对触控板的 ±3~±40
   整除后得 0 → 一动不动。改为 **delta 累加器**（满 40 滚一格，余量留着）。
2. **横滚按像素**：旧版按 ``units``（模糊单位，忽大忽小），改为
   ``xview_scroll(-delta, "pixels")``，跟手；Shift **或** Ctrl + 滚轮都行。
3. **中键拖拽平移**（PS / Figma 的抓手手感）+ 键盘 Home/End/PageUp/PageDown。
4. **横滚条按需显隐**：不再常驻吃掉一行高度，页面也不再看着像「塞不下」；
   首次出现时右下角淡出一条手势提示（只提示一次）。

滚轮绑定（2026-09-27）：``bind_all(..., add="+")`` 多实例共存 +
「鼠标所在控件必须在本容器子树内」判定 —— 只滚鼠标所在的那个页，
切到别的页签 / 别的工具窗口都不会误滚，也修掉了旧版多页签
``bind_all`` 互相覆盖导致「切页后滚轮失效」的 bug。
"""

import tkinter as tk
from tkinter import ttk

try:
    from theme import get_colors
except ImportError:
    from ptools.gui.theme import get_colors

__all__ = ["ScrollableFrame"]

#: 纵向滚一格所需的 delta 累计量（鼠标一格 120 → 3 格；触控板小步可累积）
STEP_DELTA = 40


class ScrollableFrame(ttk.Frame):
    """纵向可滚动容器。构造参数与 ttk.Frame 相同，另接受 padding。"""

    def __init__(self, master, padding=10, **kw):
        super().__init__(master, **kw)
        self._pal = get_colors()
        self.canvas = tk.Canvas(self, highlightthickness=0, takefocus=1,
                                bg=self._pal["BG"], bd=0,
                                highlightbackground=self._pal["BG"])
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
