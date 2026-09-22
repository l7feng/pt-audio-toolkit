#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一命名工具 (rename-unify) —— 音效/影视交付文件批量命名统一

设计原则
--------
壳不动芯：所有规则识别与重命名逻辑只在 core_rules.py 里维护，
GUI 只负责收集参数 → 调 core → 展示计划。core 可独立跑测试。

标签页按「使用人 × 前置条件」切分：
  页1「规则设置」—— 改项目信息与命名模板，无前置条件
  页2「预览与执行」—— 需要先选目录，且必须先出计划才允许执行
  页3「回溯」—— 需要有一份 rename_log

零第三方依赖（仅标准库 + tkinter）。

用法：python main.py
"""
import os
import sys
import datetime
import threading
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as CFG
import core_rules as CORE


# --- windowed 模式下 stdout/stderr 可能是 None，任何 print 都会崩 ---
def _safe_io():
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8",
                                        errors="replace"))
            except OSError:
                pass
        elif hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


COLOR_OK = "#2e7d32"
COLOR_BAD = "#c62828"
COLOR_WARN = "#ef6c00"
COLOR_HINT = "#1565c0"

# 计划表每行的状态 -> 颜色
STATUS_COLOR = {
    "": COLOR_OK,           # 待改名（正常）
    "rename": COLOR_OK,
    "skip": "#757575",      # 已是目标命名
    "error": COLOR_BAD,     # 识别失败
    "conflict": COLOR_WARN,  # 命名冲突
    "excluded": "#8e24aa",   # 按命名清单排除
}
STATUS_TEXT = {
    "": "待改名",
    "rename": "待改名",
    "skip": "已是目标名",
    "error": "识别失败",
    "conflict": "命名冲突",
    "excluded": "按清单排除",
}


class QueueWriter(object):
    """把 core 的 print 搬上界面（线程安全）。"""

    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)

    def flush(self):
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # 三重保险消除 Tk 启动闪窗
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-alpha", 0.0)

        try:
            ttk.Style(master=self).configure("Hint.TLabel", foreground=COLOR_HINT)
            ttk.Style(master=self).configure("Ok.TLabel", foreground=COLOR_OK)
            ttk.Style(master=self).configure("Bad.TLabel", foreground=COLOR_BAD)
            ttk.Style(master=self).configure("Warn.TLabel", foreground=COLOR_WARN)
        except tk.TclError:
            pass

        self.cfg = CFG.load_config()
        self.items = []          # 当前计划
        self.stats = {}
        self.last_log = ""
        self.busy = False

        self._build_ui()

        self.title(CFG.title())
        try:
            self.geometry(self.cfg.get("window") or "1180x760")
        except tk.TclError:
            self.geometry("1180x760")
        self.minsize(1020, 660)

        self._center_on_screen()
        self.overrideredirect(False)
        self.attributes("-alpha", 1.0)
        self.deiconify()
        self.lift()
        self.focus_force()

        self._refresh_preview()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.nb = nb

        self.tab_rule = ttk.Frame(nb)
        self.tab_types = ttk.Frame(nb)
        self.tab_run = ttk.Frame(nb)
        self.tab_undo = ttk.Frame(nb)
        nb.add(self.tab_rule, text="  1 · 项目信息与模板  ")
        nb.add(self.tab_types, text="  2 · 命名清单（勾选）  ")
        nb.add(self.tab_run, text="  3 · 预览与执行  ")
        nb.add(self.tab_undo, text="  4 · 回溯与撤销  ")

        self._build_rule_tab()
        self._build_types_tab()
        self._build_run_tab()
        self._build_undo_tab()

        # 状态栏
        bar = ttk.Frame(self)
        bar.pack(fill="x", side="bottom", padx=10, pady=(0, 6))
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.var_status, style="Hint.TLabel").pack(side="left")
        ttk.Label(bar, text="配置文件: " + CFG.CONFIG_PATH,
                  foreground="#888").pack(side="right")

    # ============ 页1：项目信息与模板 ============
    def _build_rule_tab(self):
        f = self.tab_rule
        pad = {"padx": 6, "pady": 3}

        # ---- 命名模板 ----
        tpl = ttk.LabelFrame(f, text="命名模板（段间空格，类型段内用下划线+连字符）")
        tpl.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(tpl, text="模板:").grid(row=0, column=0, sticky="w", **pad)
        self.var_template = tk.StringVar(value=self.cfg["template"])
        ttk.Entry(tpl, textvariable=self.var_template).grid(
            row=0, column=1, sticky="ew", **pad)
        ttk.Label(tpl, text="扩展名自动沿用源文件，模板里不要写 .wav",
                  style="Hint.TLabel").grid(row=1, column=1, sticky="w", padx=6)

        ttk.Label(tpl, text="可用占位符:").grid(row=2, column=0, sticky="nw", **pad)
        ttk.Label(tpl, foreground="#666", justify="left",
                  text=("{片名} {集数} {日期} {版本} {档位} {类型}\n"
                        "示例:  " + CORE.DEFAULT_TEMPLATE)).grid(
            row=2, column=1, sticky="w", padx=6, pady=(3, 6))
        tpl.columnconfigure(1, weight=1)

        # ---- 字段值 ----
        fld = ttk.LabelFrame(f, text="字段值（改这里即可换项目，无需碰模板）")
        fld.pack(fill="x", padx=10, pady=6)

        self.field_vars = {}
        row = 0
        for key in ("片名", "日期", "版本", "档位"):
            ttk.Label(fld, text=key + ":").grid(row=row, column=0, sticky="w", **pad)
            v = tk.StringVar(value=self.cfg["fields"].get(key, ""))
            self.field_vars[key] = v
            ttk.Entry(fld, textvariable=v, width=24).grid(row=row, column=1, sticky="w", **pad)
            row += 1
            if key == "片名":
                ttk.Label(fld, text="剧名/项目名，如 前夫、誓言", style="Hint.TLabel").grid(
                    row=row - 1, column=2, sticky="w", padx=6)
            elif key == "日期":
                ttk.Label(fld, text="如 0920 或 20260920", style="Hint.TLabel").grid(
                    row=row - 1, column=2, sticky="w", padx=6)
            elif key == "版本":
                ttk.Label(fld, text="如 V01、V02", style="Hint.TLabel").grid(
                    row=row - 1, column=2, sticky="w", padx=6)
            elif key == "档位":
                ttk.Label(fld, text="工程档位/用户标识，如 7F、5F", style="Hint.TLabel").grid(
                    row=row - 1, column=2, sticky="w", padx=6)

        # 实时样例
        ex = ttk.Frame(fld)
        ex.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=(6, 4))
        ttk.Label(ex, text="实时样例:").pack(side="left")
        self.var_sample = tk.StringVar(value="")
        ttk.Label(ex, textvariable=self.var_sample, foreground=COLOR_OK,
                  font=("Consolas", 10, "bold")).pack(side="left", padx=8)

        # ---- 识别规则 ----
        rl = ttk.LabelFrame(
            f, text="识别规则（把历史命名映射到统一格式；自上而下首个命中生效）")
        rl.pack(fill="both", expand=True, padx=10, pady=6)

        cols = ("dir", "pattern", "out")
        self.tree_rules = ttk.Treeview(rl, columns=cols, show="headings", height=9)
        self.tree_rules.heading("dir", text="归属目录")
        self.tree_rules.heading("pattern", text="匹配模式（正则）")
        self.tree_rules.heading("out", text="输出类型")
        self.tree_rules.column("dir", width=80, anchor="center", stretch=False)
        self.tree_rules.column("pattern", width=640)
        self.tree_rules.column("out", width=150, stretch=False)
        self.tree_rules.pack(fill="both", expand=True, side="left", padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(rl, orient="vertical", command=self.tree_rules.yview)
        sb.pack(side="right", fill="y", pady=6)
        self.tree_rules.configure(yscrollcommand=sb.set)

        rb = ttk.Frame(f)
        rb.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(rb, text="保存为默认", command=self._save_cfg).pack(side="right", padx=4)
        ttk.Button(rb, text="恢复内置规则", command=self._reset_rules).pack(side="right", padx=4)

        # 载入规则
        self.rules = [list(r) for r in
                      (self.cfg["rules"] if self.cfg.get("rules") else CORE.DEFAULT_RULES)]
        self._reload_rules()

        for v in self.field_vars.values():
            v.trace_add("write", lambda *a: self._refresh_preview())
        self.var_template.trace_add("write", lambda *a: self._refresh_preview())

    def _reload_rules(self):
        self.tree_rules.delete(*self.tree_rules.get_children())
        for r in self.rules:
            self.tree_rules.insert("", "end", values=tuple(r[:3]))

    def _reset_rules(self):
        if not messagebox.askokcancel("恢复内置规则", "将丢弃当前规则，恢复内置默认规则？"):
            return
        self.rules = [list(r) for r in CORE.DEFAULT_RULES]
        self._reload_rules()
        self._refresh_preview()
        self._log("已恢复内置识别规则")

    # ============ 页2：命名清单（勾选） ============
    def _build_types_tab(self):
        """可勾选的命名实体清单。

        为什么要这一页：交付类型并非每集都一样 —— 第 1 集可能只交 BUS，
        第 4 集才补 STEM。用「勾选 + 集数限定」表达这种差异，
        比改模板或事后挪文件都安全（未勾选的项在计划阶段就跳过，不动盘）。

        交互用**直接编辑表格**（双击勾选格切换、双击集数格输入），
        避免再开一个对话框。
        """
        f = self.tab_types

        ttk.Label(
            f, justify="left", style="Hint.TLabel",
            text=("勾选本次要产出的交付类型。未勾选的类型在「生成计划」时会被标为"
                  "「按清单排除」并跳过，不会改名、不会移动。\n"
                  "「生效集数」留空 = 全部集；填 1 或 1,3-5 可只对指定集生效"
                  "（例：第 1 集只需命名 BUS → 只勾 BUS-*，其余取消勾选）。")
        ).pack(anchor="w", padx=12, pady=(10, 6))

        wrap = ttk.LabelFrame(f, text="命名实体清单（双击「启用」格切换勾选，双击「生效集数」格输入）")
        wrap.pack(fill="both", expand=True, padx=10, pady=6)

        cols = ("enabled", "type", "eps", "note")
        self.tree_types = ttk.Treeview(wrap, columns=cols, show="headings", height=14)
        self.tree_types.heading("enabled", text="启用")
        self.tree_types.heading("type", text="输出类型")
        self.tree_types.heading("eps", text="生效集数")
        self.tree_types.heading("note", text="备注")
        self.tree_types.column("enabled", width=70, anchor="center", stretch=False)
        self.tree_types.column("type", width=170, anchor="w", stretch=False)
        self.tree_types.column("eps", width=140, anchor="center", stretch=False)
        self.tree_types.column("note", width=420)
        ts = ttk.Scrollbar(wrap, orient="vertical", command=self.tree_types.yview)
        self.tree_types.configure(yscrollcommand=ts.set)
        ts.pack(side="right", fill="y", pady=6)
        self.tree_types.pack(fill="both", expand=True, side="left", padx=(6, 0), pady=6)

        self.tree_types.tag_configure("on", foreground=COLOR_OK)
        self.tree_types.tag_configure("off", foreground="#9e9e9e")
        self.tree_types.tag_configure("limited", foreground=COLOR_WARN)

        self.tree_types.bind("<Double-Button-1>", self._on_type_dblclick)

        # 载入清单：配置为空 → 用内置默认（首次打开就能看到全部类型）
        self.enabled_types = self._load_enabled_types()
        self._reload_types()

        btns = ttk.Frame(f)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="保存为默认", command=self._save_cfg).pack(side="right", padx=4)
        ttk.Button(btns, text="全不选", command=lambda: self._set_all_types(False)).pack(side="right", padx=4)
        ttk.Button(btns, text="全选", command=lambda: self._set_all_types(True)).pack(side="right", padx=4)
        ttk.Button(btns, text="恢复内置清单", command=self._reset_types).pack(side="right", padx=4)

    def _load_enabled_types(self):
        cfg_types = CFG.load_config().get("enabled_types") or []
        if cfg_types:
            return [dict(e) for e in cfg_types]
        return [dict(e) for e in CORE.DEFAULT_ENABLED_TYPES]

    def _reload_types(self):
        self.tree_types.delete(*self.tree_types.get_children())
        for idx, e in enumerate(self.enabled_types):
            self.tree_types.insert("", "end", iid=str(idx),
                                   values=self._type_row_values(e),
                                   tags=(self._type_row_tag(e),))

    @staticmethod
    def _type_row_values(e):
        return ("[√] 启用" if e.get("enabled", True) else "[ ] 停用",
                e.get("type", ""),
                e.get("eps", "") or "（全部集）",
                e.get("note", ""))

    @staticmethod
    def _type_row_tag(e):
        if not e.get("enabled", True):
            return "off"
        if CORE.parse_eps(e.get("eps")):
            return "limited"
        return "on"

    def _on_type_dblclick(self, event):
        """双击：点「启用」列切换勾选，点「生效集数」列弹输入框。"""
        row = self.tree_types.identify_row(event.y)
        col = self.tree_types.identify_column(event.x)
        if not row:
            return
        try:
            e = self.enabled_types[int(row)]
        except (ValueError, IndexError):
            return

        if col == "#1":                      # 启用列
            e["enabled"] = not e.get("enabled", True)
        elif col == "#3":                    # 生效集数列
            cur = e.get("eps", "")
            new = simpledialog.askstring(
                "生效集数",
                "只对哪些集生效？（留空 = 全部集）\n例：1 或 1,3-5",
                initialvalue=cur, parent=self)
            if new is None:                  # 取消
                return
            e["eps"] = new.strip()
        else:
            return
        self._reload_types()
        self._refresh_preview()

    def _set_all_types(self, flag):
        for e in self.enabled_types:
            e["enabled"] = flag
        self._reload_types()
        self._refresh_preview()

    def _reset_types(self):
        if not messagebox.askokcancel("恢复内置清单", "将丢弃当前清单，恢复内置默认清单？"):
            return
        self.enabled_types = [dict(e) for e in CORE.DEFAULT_ENABLED_TYPES]
        self._reload_types()
        self._refresh_preview()
        self._log("已恢复内置命名实体清单")

    # ============ 页3：预览与执行 ============
    def _build_run_tab(self):
        f = self.tab_run

        # ---- 目录与范围 ----
        top = ttk.LabelFrame(f, text="目标范围")
        top.pack(fill="x", padx=10, pady=(10, 6))
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="目标目录:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.var_root = tk.StringVar(value=self.cfg["last_root"])
        ttk.Entry(top, textvariable=self.var_root).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="浏览…", command=self._pick_root).grid(row=0, column=2, padx=6)

        opt = ttk.Frame(top)
        opt.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6))
        self.var_rec = tk.BooleanVar(value=bool(self.cfg["recursive"]))
        ttk.Checkbutton(opt, text="含子目录", variable=self.var_rec,
                        command=self._refresh_preview).pack(side="left", padx=(0, 12))
        ttk.Label(opt, text="扩展名:").pack(side="left")
        self.var_exts = tk.StringVar(value=self.cfg["exts"])
        ttk.Entry(opt, textvariable=self.var_exts, width=30).pack(side="left", padx=6)

        # ---- 归位选项（原 FinalMix按集归位.ps1 的能力）----
        rg = ttk.LabelFrame(f, text="按集归位（可选：把平铺的分类目录重组为「每集一个文件夹」）")
        rg.pack(fill="x", padx=10, pady=(0, 6))
        rg.columnconfigure(1, weight=1)

        self.var_regroup = tk.BooleanVar(value=bool(self.cfg.get("regroup_after")))
        ttk.Checkbutton(
            rg, text="重命名完成后，自动按集归位", variable=self.var_regroup,
            command=self._refresh_preview).grid(row=0, column=0, columnspan=3,
                                                sticky="w", padx=6, pady=(4, 2))

        ttk.Label(rg, text="归位目标:").grid(row=1, column=0, sticky="w", padx=6)
        self.var_regroup_root = tk.StringVar(value=self.cfg.get("regroup_root", ""))
        ttk.Entry(rg, textvariable=self.var_regroup_root).grid(
            row=1, column=1, sticky="ew", padx=6)
        ttk.Button(rg, text="浏览…", command=self._pick_regroup_root).grid(
            row=1, column=2, padx=6)

        self.var_regroup_clean = tk.BooleanVar(value=bool(self.cfg.get("regroup_cleanup", True)))
        ttk.Checkbutton(rg, text="归位后清理搬空的类别文件夹（MIX / BUS / Stem）",
                        variable=self.var_regroup_clean).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=6)

        ttk.Label(rg, foreground="#666", justify="left",
                  text=("归位规则：MIX / MIX-MASTER 放集根目录；BUS-* → 集目录\\BUS；"
                        "STEM-* → 集目录\\STEM。只移动、绝不覆盖，解析不了的跳过并报告。\n"
                        "目标留空 = 直接用上面的「目标目录」。")).grid(
            row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6))

        # ---- 状态指示灯 + 按钮 ----
        act = ttk.Frame(f)
        act.pack(fill="x", padx=10, pady=(0, 6))
        self.var_plan_state = tk.StringVar(value="尚未生成计划")
        self.lbl_plan_state = ttk.Label(act, textvariable=self.var_plan_state,
                                        style="Bad.TLabel")
        self.lbl_plan_state.pack(side="left")

        self.btn_apply = ttk.Button(act, text="执行重命名", command=self._on_apply,
                                    state="disabled")
        self.btn_apply.pack(side="right", padx=4)
        self.btn_plan = ttk.Button(act, text="生成计划", command=self._refresh_preview)
        self.btn_plan.pack(side="right", padx=4)

        # ---- 计划表 ----
        pv = ttk.LabelFrame(f, text="变更计划（先预览，确认无误再执行）")
        pv.pack(fill="both", expand=True, padx=10, pady=6)

        cols = ("st", "old", "new", "note")
        self.tree_plan = ttk.Treeview(pv, columns=cols, show="headings")
        self.tree_plan.heading("st", text="状态")
        self.tree_plan.heading("old", text="原文件名")
        self.tree_plan.heading("new", text="新文件名")
        self.tree_plan.heading("note", text="说明")
        self.tree_plan.column("st", width=90, anchor="center", stretch=False)
        self.tree_plan.column("old", width=380)
        self.tree_plan.column("new", width=380)
        self.tree_plan.column("note", width=200)
        for st, col in STATUS_COLOR.items():
            self.tree_plan.tag_configure(st or "ok", foreground=col)

        vs = ttk.Scrollbar(pv, orient="vertical", command=self.tree_plan.yview)
        self.tree_plan.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y", pady=6)
        self.tree_plan.pack(fill="both", expand=True, side="left", padx=(6, 0), pady=6)

        # ---- 日志 ----
        lg = ttk.LabelFrame(f, text="日志")
        lg.pack(fill="both", padx=10, pady=(0, 10))
        self.txt_log = tk.Text(lg, height=7, wrap="none", state="disabled",
                               font=("Consolas", 9))
        ls = ttk.Scrollbar(lg, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=ls.set)
        ls.pack(side="right", fill="y", padx=(0, 4), pady=4)
        self.txt_log.pack(fill="both", expand=True, side="left", padx=6, pady=4)

    # ============ 页3：回溯与撤销 ============
    def _build_undo_tab(self):
        f = self.tab_undo
        top = ttk.LabelFrame(f, text="回溯日志（每次执行自动生成 rename_log_*.csv）")
        top.pack(fill="x", padx=10, pady=(10, 6))
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="日志文件:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.var_logfile = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.var_logfile).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="选择…", command=self._pick_log).grid(row=0, column=2, padx=6)

        row = ttk.Frame(top)
        row.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6))
        ttk.Button(row, text="列出目录下的日志", command=self._list_logs).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="清空日志目录", command=self._clear_logs).pack(side="left")

        # 撤销区
        un = ttk.LabelFrame(f, text="撤销（把「新文件名」改回「原文件名」）")
        un.pack(fill="both", expand=True, padx=10, pady=6)
        ttk.Label(un, foreground=COLOR_WARN, justify="left",
                  text=("撤销按日志逐条反向改名。若原文件名已被别的文件占用，该条会失败并跳过。\n"
                        "执行前请确认目标目录没有新增同名文件。")).pack(anchor="w", padx=8, pady=6)

        self.txt_preview_log = tk.Text(un, height=16, wrap="none", state="disabled",
                                       font=("Consolas", 9))
        ps = ttk.Scrollbar(un, orient="vertical", command=self.txt_preview_log.yview)
        self.txt_preview_log.configure(yscrollcommand=ps.set)
        ps.pack(side="right", fill="y", padx=(0, 6), pady=6)
        self.txt_preview_log.pack(fill="both", expand=True, side="left", padx=8, pady=6)

        ub = ttk.Frame(f)
        ub.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(ub, text="执行撤销", command=self._on_undo).pack(side="right", padx=4)
        ttk.Button(ub, text="读取并预览", command=self._preview_log).pack(side="right", padx=4)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _center_on_screen(self):
        try:
            self.update_idletasks()
            w = self.winfo_width() or 1180
            h = self.winfo_height() or 760
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry("+%d+%d" % (max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        except tk.TclError:
            pass

    def _log(self, text):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text.rstrip() + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _pick_root(self):
        p = filedialog.askdirectory(initialdir=self.var_root.get() or "D:\\")
        if p:
            self.var_root.set(p)
            self._refresh_preview()

    def _pick_regroup_root(self):
        cur = self.var_regroup_root.get() or self.var_root.get() or "D:\\"
        p = filedialog.askdirectory(initialdir=cur)
        if p:
            self.var_regroup_root.set(p)
            self._refresh_preview()

    def _regroup_root(self):
        return (self.var_regroup_root.get() or "").strip() or \
               (self.var_root.get() or "").strip()

    def _pick_log(self):
        p = filedialog.askopenfilename(
            initialdir=self.var_root.get() or "D:\\",
            filetypes=[("CSV 日志", "*.csv"), ("全部文件", "*.*")])
        if p:
            self.var_logfile.set(p)
            self._preview_log()

    # ---- 当前字段与规则 ----
    def _fields(self):
        return {k: v.get().strip() for k, v in self.field_vars.items()}

    def _exts(self):
        raw = (self.var_exts.get() or "").replace(",", " ").split()
        return tuple(e if e.startswith(".") else "." + e for e in raw) or None

    # ---- 实时样例 ----
    def _refresh_preview(self):
        """重建计划表（同时更新实时样例）。这是「生成计划」的唯一入口。"""
        # 1) 样例
        try:
            sample = CORE.render(self.var_template.get(), "1", "BUS-DX", self._fields()) + ".wav"
        except Exception as e:
            sample = "[模板错误] %s" % e
        self.var_sample.set(sample)

        # 2) 扫描 + 计划
        root = (self.var_root.get() or "").strip()
        if not root or not os.path.isdir(root):
            self.items, self.stats = [], {}
            self._set_plan_state("目标目录不存在", "bad")
            self._fill_plan([])
            self.btn_apply.configure(state="disabled")
            self.var_status.set("请选择一个存在的目标目录")
            return

        try:
            paths = CORE.scan_dir(root, recursive=self.var_rec.get(),
                                  exts=self._exts())
            items, stats = CORE.make_plan(paths, self.var_template.get(),
                                          self.rules, self._fields(),
                                          enabled_types=self.enabled_types)
        except Exception as e:
            self.items, self.stats = [], {}
            self._set_plan_state("规划失败: %s" % e, "bad")
            self.btn_apply.configure(state="disabled")
            return

        self.items, self.stats = items, stats
        self._fill_plan(items)
        self._update_plan_state()

    def _update_plan_state(self):
        s = self.stats
        if not s or s["total"] == 0:
            self._set_plan_state("该目录下没有可处理的文件", "warn")
            self.btn_apply.configure(state="disabled")
        elif s["rename"] == 0:
            n = s["skip"] + s["error"] + s["conflict"] + s.get("excluded", 0)
            self._set_plan_state("无需改动（%d 个文件均已符合命名或已排除）" % n, "ok")
            self.btn_apply.configure(state="disabled")
        else:
            msg = "待改名 %d" % s["rename"]
            if s["skip"]:
                msg += " / 已合规 %d" % s["skip"]
            if s.get("excluded"):
                msg += " / 清单排除 %d" % s["excluded"]
            if s["error"]:
                msg += " / 识别失败 %d" % s["error"]
            if s["conflict"]:
                msg += " / 冲突 %d" % s["conflict"]
            self._set_plan_state(msg, "warn" if (s["error"] or s["conflict"]) else "ok")
            self.btn_apply.configure(state="normal")
        self.var_status.set("扫描 %d 个文件 · %s" % (s["total"], self.var_plan_state.get()))

    def _set_plan_state(self, text, kind):
        style = {"ok": "Ok.TLabel", "bad": "Bad.TLabel", "warn": "Warn.TLabel"}.get(kind, "Hint.TLabel")
        self.var_plan_state.set(text)
        self.lbl_plan_state.configure(style=style)

    def _fill_plan(self, items):
        self.tree_plan.delete(*self.tree_plan.get_children())
        for i in items:
            st = i.status or "ok"
            note = i.note
            if not note and st == "ok":
                note = "%s · %s集" % (i.type_str, CORE.normalize_ep(i.ep))
            self.tree_plan.insert("", "end", values=(
                STATUS_TEXT.get(i.status, i.status),
                os.path.basename(i.src),
                os.path.basename(i.dst),
                note), tags=(st,))

    # ---- 执行 ----
    def _on_apply(self):
        if self.busy:
            return
        todo = [i for i in self.items if i.status == ""]
        if not todo:
            messagebox.showinfo("无需改动", "当前计划里没有被标记为「待改名」的文件。")
            return

        bad = self.stats.get("error", 0) + self.stats.get("conflict", 0)
        warn = ("\n\n注意：另有 %d 个文件因识别失败或命名冲突将被跳过。" % bad) if bad else ""
        if not messagebox.askokcancel(
                "确认执行重命名",
                "即将重命名 %d 个文件。\n\n"
                "· 会生成回溯日志 rename_log_*.csv，可随时撤销\n"
                "· 如有同名文件将按计划跳过（不会覆盖）%s\n\n"
                "是否继续？" % (len(todo), warn)):
            return

        self.busy = True
        self.btn_apply.configure(state="disabled")
        self._log("=== 开始执行：待改名 %d ===" % len(todo))

        do_regroup = bool(self.var_regroup.get())
        rg_root = self._regroup_root()
        rg_clean = bool(self.var_regroup_clean.get())
        rules_snapshot = [list(r) for r in self.rules]
        fields_snapshot = self._fields()

        def worker():
            try:
                done, failed, logp = CORE.apply_plan(self.items, write_log=False)
                self._log("改名完成: 成功 %d / 失败 %d" % (len(done), len(failed)))
                for src, dst, err in failed:
                    self._log("  失败: %s -> %s (%s)" % (os.path.basename(src),
                                                         os.path.basename(dst), err))

                moved = []
                if do_regroup and os.path.isdir(rg_root):
                    self._log("=== 按集归位: %s ===" % rg_root)
                    ritems, rstats = CORE.build_regroup_plan(
                        rg_root, rules_snapshot, fields_snapshot)
                    self._log("归位计划: 待移动 %d / 已就位 %d / 跳过 %d"
                              % (rstats["move"], rstats["skip"], rstats["error"]))
                    for i in ritems:
                        if i.status == "error":
                            self._log("  跳过: %s (%s)" % (os.path.basename(i.src), i.note))
                    moved, mfail, cleaned = CORE.apply_regroup(
                        ritems, cleanup_empty=rg_clean)
                    self._log("归位完成: 移动 %d / 失败 %d" % (len(moved), len(mfail)))
                    for src, dst, err in mfail:
                        self._log("  失败: %s (%s)" % (os.path.basename(src), err))
                    for c in cleaned:
                        self._log("  清理空文件夹: %s" % c)
                elif do_regroup:
                    self._log("!! 归位目标不存在，已跳过归位: %s" % rg_root)

                # 改名 + 归位写进**同一份**日志，撤销顺序天然是「先归位后改名」
                logp = self._write_combined_log(done, moved)
                if logp:
                    self.last_log = logp
                    self._log("回溯日志: %s（含改名 %d 条 + 归位 %d 条）"
                              % (logp, len(done), len(moved)))
                    self.var_logfile.set(logp)
            except Exception:
                self._log(traceback.format_exc())
            finally:
                self.busy = False
                self.after(0, self._after_apply)

        threading.Thread(target=worker, daemon=True).start()

    def _write_combined_log(self, renamed, moved):
        """把改名记录与归位记录合并成一份可撤销日志。

        撤销按**倒序**执行：先反向归位（集目录 → 分类目录），
        再反向改名（新名 → 原名），正好是执行顺序的镜像。
        日志位置落在归位根（或首条源文件所在目录）。
        """
        rows = list(renamed) + list(moved)
        if not rows:
            return None
        base = self._regroup_root() if self.var_regroup.get() else ""
        if not (base and os.path.isdir(base)):
            base = os.path.dirname(rows[0][0]) or "."
        path = os.path.join(base, "rename_log_%s.csv"
                            % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            import csv
            with open(path, "w", encoding="utf-8-sig", newline="") as fp:
                w = csv.writer(fp)
                w.writerow(CORE.LOG_HEADER)
                w.writerows(rows)
            return path
        except OSError as e:
            self._log("  警告: 日志写入失败 (%s)" % e)
            return None

    def _after_apply(self):
        self._log("=== 执行结束，重新扫描 ===")
        self._refresh_preview()
        if self.last_log:
            self.var_logfile.set(self.last_log)
            self._preview_log()

    # ---- 撤销 ----
    def _list_logs(self):
        root = (self.var_root.get() or "").strip()
        if not root or not os.path.isdir(root):
            messagebox.showwarning("目录无效", "请先在「预览与执行」页选择目标目录。")
            return
        found = []
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                if fn.lower().startswith("rename_log_") and fn.lower().endswith(".csv"):
                    found.append(os.path.join(dp, fn))
        if not found:
            messagebox.showinfo("未找到日志", "该目录下没有 rename_log_*.csv")
            return
        found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        dlg = tk.Toplevel(self)
        dlg.title("选择回溯日志")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("760x360")
        lb = tk.Listbox(dlg, font=("Consolas", 9))
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        for p in found:
            lb.insert("end", p)
        lb.selection_set(0)

        def choose():
            sel = lb.curselection()
            if sel:
                self.var_logfile.set(lb.get(sel[0]))
                self._preview_log()
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bf, text="选用", command=choose).pack(side="right", padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="right", padx=4)
        lb.bind("<Double-Button-1>", lambda e: choose())

    def _clear_logs(self):
        root = (self.var_root.get() or "").strip()
        if not root or not os.path.isdir(root):
            return
        found = []
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                if fn.lower().startswith("rename_log_") and fn.lower().endswith(".csv"):
                    found.append(os.path.join(dp, fn))
        if not found:
            messagebox.showinfo("无日志", "该目录下没有 rename_log_*.csv")
            return
        if not messagebox.askokcancel(
                "确认清理", "将删除 %d 个回溯日志文件（不可恢复）：\n%s" %
                (len(found), "\n".join(os.path.basename(p) for p in found[:10]))):
            return
        n = 0
        for p in found:
            try:
                os.remove(p)
                n += 1
            except OSError:
                pass
        self._log("已清理 %d 个日志文件" % n)

    def _preview_log(self):
        p = (self.var_logfile.get() or "").strip()
        self.txt_preview_log.configure(state="normal")
        self.txt_preview_log.delete("1.0", "end")
        if not p or not os.path.isfile(p):
            self.txt_preview_log.insert("1.0", "（未选择有效的日志文件）")
            self.txt_preview_log.configure(state="disabled")
            return
        try:
            import csv
            with open(p, "r", encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh))
            body = rows[1:] if rows and rows[0][:2] == ["原文件", "新文件"] else rows
            lines = ["日志: %s" % p,
                     "共 %d 条记录（倒序撤销）" % len(body), ""]
            for r in body:
                if len(r) >= 2:
                    ok = "✓" if os.path.exists(r[0]) else "✗ 新文件不存在"
                    lines.append("%s  %s\n      → %s" % (ok, os.path.basename(r[0]),
                                                        os.path.basename(r[1])))
            self.txt_preview_log.insert("1.0", "\n".join(lines))
        except Exception as e:
            self.txt_preview_log.insert("1.0", "读取失败: %s" % e)
        self.txt_preview_log.configure(state="disabled")

    def _on_undo(self):
        p = (self.var_logfile.get() or "").strip()
        if not p or not os.path.isfile(p):
            messagebox.showwarning("未选日志", "请先选择一份回溯日志。")
            return
        if not messagebox.askokcancel(
                "确认撤销",
                "将按日志把文件改回原文件名：\n%s\n\n"
                "已存在的原文件不会被覆盖（该条跳过）。是否继续？" % p):
            return
        done, failed = CORE.undo_from_log(p)
        self._log("=== 撤销完成: 成功 %d / 失败 %d ===" % (len(done), len(failed)))
        for a, b, err in failed:
            self._log("  失败: %s (%s)" % (os.path.basename(a), err))
        self._preview_log()
        self._refresh_preview()

    # ---- 配置 ----
    def _save_cfg(self):
        cfg = dict(self.cfg)
        cfg["last_root"] = self.var_root.get()
        cfg["recursive"] = bool(self.var_rec.get())
        cfg["exts"] = self.var_exts.get()
        cfg["template"] = self.var_template.get()
        cfg["fields"] = self._fields()
        cfg["rules"] = [list(r) for r in self.rules]
        cfg["enabled_types"] = [dict(e) for e in self.enabled_types]
        cfg["regroup_after"] = bool(self.var_regroup.get())
        cfg["regroup_root"] = self.var_regroup_root.get()
        cfg["regroup_cleanup"] = bool(self.var_regroup_clean.get())
        try:
            cfg["window"] = self.geometry().split("+")[0]
        except Exception:
            pass
        if CFG.save_config(cfg):
            self.cfg = CFG.load_config()
            self._log("配置已保存: %s" % CFG.CONFIG_PATH)
            self.var_status.set("配置已保存")
        else:
            messagebox.showerror("保存失败", "无法写入配置文件：\n%s" % CFG.CONFIG_PATH)


def main():
    _safe_io()
    try:
        App().mainloop()
    except Exception:
        _safe_io()
        tb = traceback.format_exc()
        try:
            messagebox.showerror("启动失败", tb)
        except Exception:
            sys.stderr.write(tb)


if __name__ == "__main__":
    main()
