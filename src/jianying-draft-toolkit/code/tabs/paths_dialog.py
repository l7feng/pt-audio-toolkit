#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tabs/paths_dialog.py — 「默认路径设置」对话框（视图层）

本项目三页的输入/输出目录分散在各自标签页，用户换工作目录要切页逐个改。
本对话框把 5 个路径类字段集中到一处，改完写进 config.json 就成了**默认**——
下次开 exe 直接是这套路径。

与菜单的关系：``gui.py`` 的「设置 → 默认路径设置…」调本对话框；
具体读写逻辑在 ``core.menus``（消息类型化、可单测），本文件只管画控件。

设计：
  · 只列路径类字段（``core.menus.PATH_KEYS``），不碰格式/模板/开关；
  · 每个字段带一枚「浏览…」按钮 + 灰色说明；
  · 底部三键：恢复出厂默认（仅路径）/ 取消 / 保存。
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core import menus


class PathsDialog(tk.Toplevel):
    """模态对话框：集中编辑路径类默认值。

    用法::

        dlg = PathsDialog(parent)
        parent.wait_window(dlg)
        if dlg.saved:
            ...  # 需要时刷新界面显示
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("默认路径设置")
        self.transient(parent)
        self.resizable(True, False)
        self.saved = False
        self.vars: dict = {}

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text=("这里设置的是**默认路径**，保存后写入配置文件，下次打开程序即生效。\n"
                  "各页仍可在自己的标签页里临时改（那只影响当次，不改默认）。"),
            justify="left", foreground="#555").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        # 只取路径类字段（core.menus 是单一来源，避免两处各列一遍）
        fields = menus.default_paths()
        r = 1
        for key, (label, hint, value) in fields.items():
            var = tk.StringVar(value=value)
            self.vars[key] = var
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w",
                                             padx=(0, 8), pady=5)
            ttk.Entry(body, textvariable=var, width=52).grid(
                row=r, column=1, sticky="we", pady=5)
            ttk.Button(body, text="浏览…",
                       command=lambda v=var, k=key: self._pick(v, k)).grid(
                row=r, column=2, padx=(8, 0), pady=5)
            ttk.Label(body, text=hint, foreground="#888").grid(
                row=r + 1, column=1, columnspan=2, sticky="w", pady=(0, 6))
            r += 2
        body.columnconfigure(1, weight=1)

        ttk.Separator(body, orient="horizontal").grid(
            row=r, column=0, columnspan=3, sticky="we", pady=(8, 4))
        ttk.Label(body,
                  text=("提示：「恢复出厂默认」只重置上面这些**路径**，"
                        "不会动你调好的命名模板 / 规格 / 开关。"),
                  foreground="#777", justify="left").grid(
            row=r + 1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        btns = ttk.Frame(body)
        btns.grid(row=r + 2, column=0, columnspan=3, sticky="we")
        ttk.Button(btns, text="恢复出厂默认（仅路径）",
                   command=self._restore).pack(side="left")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right",
                                                                 padx=(6, 0))
        ttk.Button(btns, text="保存", command=self._save,
                   style="Accent.TButton").pack(side="right")

        self._center(parent)
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())

    # ───────────── 动作 ─────────────

    def _pick(self, var: tk.StringVar, key: str):
        """浏览：输出/包目录选目录；其余（含文件型）也按目录处理。

        这 5 个字段全是目录语义，统一用 askdirectory 最不容易选错。
        """
        cur = var.get().strip()
        initial = cur if cur and __import__("pathlib").Path(cur).is_dir() else None
        p = filedialog.askdirectory(title="选择目录", initialdir=initial)
        if p:
            var.set(p)

    def _restore(self):
        if not messagebox.askyesno(
                "恢复出厂默认",
                "将把 5 个路径字段重置为出厂默认值：\n\n"
                "  · 输出目录 → D:/导出音频\n"
                "  · 其余路径 → 留空（自动定位）\n\n"
                "命名模板 / 规格 / 开关等参数**不受影响**。继续？"):
            return
        menus.restore_default_paths()
        for key, var in self.vars.items():
            var.set(menus.default_paths().get(key, ("", "", ""))[2])
        messagebox.showinfo("已恢复", "路径已重置为出厂默认，点「保存」写入配置文件。")

    def _save(self):
        vals = {k: v.get().strip() for k, v in self.vars.items()}
        if not vals.get("output_dir"):
            if not messagebox.askyesno(
                    "输出目录为空",
                    "「① 导出音频的输出目录」为空，导出页将无法工作。\n"
                    "确定要这样保存吗？"):
                return
        try:
            path = menus.apply_paths(vals)
        except Exception as e:
            messagebox.showerror("保存失败", f"写入配置失败：{e}")
            return
        self.saved = True
        messagebox.showinfo("已保存", f"默认路径已写入：\n{path}")
        self.destroy()

    def _center(self, parent):
        self.update_idletasks()
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 3)}")
        except Exception:
            pass
