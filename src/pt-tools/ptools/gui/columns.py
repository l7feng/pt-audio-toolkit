# -*- coding: utf-8 -*-
"""表格列宽按权重自适应（S11 / v3.10.0）—— 同源双副本之一。

副本规则（与 scrollable.py 相同）：
  ① src/pt-tools/ptools/gui/columns.py  ← 权威源
  ② src/rename-unify/code/columns.py    ← 整文件复制
改一必须同步二。

为什么需要：Tk 的 Treeview `stretch=True` 只在容器**变宽**时把多余空间分给
各列；容器**变窄**时列宽不收，整表超出容器 → 父容器被迫出横向滚动条。
列宽写死总和 1100px > 窗口 minsize 880px 的树（rename-unify 预览表），
窗口一缩就出横条。本模块在容器每次变宽/变窄时按**权重**重新分配可用总宽，
做到「窗口怎么拖都不出横条」；窄到各列最小宽之和都放不下时，才交给树
自身的横向滚动条兜底。

用法（树建好后一行挂上，权重缺省按当前列宽比例，保留设计意图）：
    from ptools.gui.columns import fit_tree_columns   # rename-unify: import columns
    fit_tree_columns(self.tree_plan)
也可显式给权重 / 最小宽：
    fit_tree_columns(tree, weights={"old": 3, "new": 3, "note": 2},
                     min_widths={"note": 120})
"""

import tkinter as tk

DEFAULT_MIN = 36   # 每列最小宽度（px）
PAD = 24           # 容器宽 → 可用宽 的扣减（内边距 + 竖向滚动条预留）


def fit_tree_columns(tree, weights=None, min_widths=None, pad=PAD):
    """把树挂上 <Configure> 自适应：容器每次变宽都按权重重新分配列宽。"""
    cols = list(tree["columns"])
    if not cols:
        return tree
    wmap = {}
    for c in cols:
        w = (weights or {}).get(c)
        if not w:
            try:
                w = tree.column(c, "width") or 1
            except Exception:
                w = 1
        wmap[c] = max(float(w), 1.0)
    mins = {}
    for c in cols:
        m = (min_widths or {}).get(c)
        mins[c] = int(m) if m else DEFAULT_MIN
    state = {"last": None}

    def _apply(event=None):
        w = tree.winfo_width()
        if w <= 1:            # 尚未布局
            return
        if state["last"] == w:  # 同宽不重排（防抖 + 防递归）
            return
        state["last"] = w
        avail = max(sum(mins.values()), w - pad)
        floor = sum(mins.values())
        if avail <= floor:
            # 极窄：全给最小宽，交给树自身横向滚动条兜底
            for c in cols:
                tree.column(c, width=mins[c])
            return
        extra = avail - floor
        wsum = sum(wmap.values()) or 1.0
        for c in cols:
            tree.column(c, width=int(mins[c] + extra * wmap[c] / wsum))

    def _on_cfg(_event):
        # after_idle：等 Tk 自己算完本轮布局再改列宽，避免 Configure 递归
        try:
            tree.after_idle(_apply)
        except Exception:
            pass

    tree.bind("<Configure>", _on_cfg, add="+")
    tree.after_idle(_apply)
    return tree
