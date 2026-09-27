#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ScrollableFrame —— 纵向可滚动容器（G2/J12 全局滚动改造，2026-09-27）。

⚠️ 同源副本：`src/rename-unify/code/scrollable.py` 与
`src/jianying-draft-toolkit/code/tabs/base.py::ScrollableFrame` 三处同源，
改一处要同步改三处（工具独立打包，不引公共包）。

用法：页面 build() 里把 ``outer = self`` 换成::

    outer = ScrollableFrame(self, padding=0)   # 页面自带 padding 时传 0
    outer.pack(fill="both", expand=True)
    outer = outer.inner

之后照常向 ``outer`` 上 pack/grid 子控件。窗口不够高时右侧出现滚动条，
鼠标滚轮直接滚动；鼠标指向日志框 / 列表框 / 树等**自身可滚的控件**时
让位给它们，不会双重滚动。

滚轮绑定（2026-09-27 修正）：``bind_all(..., add="+")`` 多实例共存 +
"鼠标所在控件必须在本容器子树内"判定 —— 只滚鼠标所在的那个页，
切到别的页签/别的工具窗口都不会误滚，也修掉了旧版多页签
``bind_all`` 互相覆盖导致「切页后滚轮失效」的 bug。
"""

import tkinter as tk
from tkinter import ttk

__all__ = ["ScrollableFrame"]


class ScrollableFrame(ttk.Frame):
    """纵向可滚动容器。构造参数与 ttk.Frame 相同，另接受 padding。"""

    def __init__(self, master, padding=10, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.vsb.pack(side="right", fill="y")
        self.hsb.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # add="+"：多个实例（多个页签）都挂全局滚轮，互不覆盖；
        # 实际只滚"鼠标所在子树"对应的实例（见 _on_wheel）。
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _on_canvas_configure(self, e):
        # S3（v3.5.0）：inner 宽度 = max(内容需求宽, 画布宽)。窄窗时拉伸填满；
        # 内容超宽时 inner 不被压成窗口宽，横向滚动条出现（旧版强制等宽，
        # 超宽按钮被挤成文字消失却仍可点，最坑）。
        req = self.inner.winfo_reqwidth()
        self.canvas.itemconfigure(self._win, width=max(req, e.width))

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
            if isinstance(x, (tk.Text, tk.Listbox, ttk.Treeview, ttk.Combobox)):
                return
            x = getattr(x, "master", None)
        if e.state & 0x0001:  # Shift 按住 → 横滚
            try:
                self.canvas.xview_scroll(int(-e.delta / 120) * 3, "units")
            except Exception:
                pass
            return
        try:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except Exception:
            pass
