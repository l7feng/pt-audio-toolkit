#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一命名工具 (rename-unify) —— 音效/影视交付文件批量命名统一

设计原则
--------
壳不动芯：所有识别与重命名逻辑只在 core_rules.py 里维护，
GUI 只负责收集参数 → 调 core → 展示计划。core 可独立跑测试。

标签页按「使用人 × 前置条件」切分：
  页1「项目信息与模板」—— 字段值 + 模板库，无前置条件
  页2「目标与归位」    —— 每个目标放哪、用哪套模板、处理哪些集，无前置条件
  页3「预览与执行」    —— 需要先选目录；识别失败的可在计划表里「手动分类」
  页4「回溯与撤销」    —— 需要有一份 rename_log

v1.2.0 变更（2026-09-23）
   * 「命名清单」升级为**目标表**：目标（MIX / BUS / STEM / AIFX）各自绑定
     归位目录 + 一套模板 —— 这就是「模板和目标拆开」：Master 走全格式，
     BUS/STEM 可以走短格式，各改各的。
   * 模板库可增删改（页1），目标从库里**选一套**（页2）。
   * `{档位}` → `{用户}`（7F 是用户代号）。旧配置自动迁移，不静默丢。
   * 原「按集归位」独立步骤已**内联**进主流程（目标表的「归位目录」决定最终
     落点，平铺的分类目录会被自动重组为集目录），故页3 不再有该区块。
   * 识别失败的项可在页3「手动分类」：指定 集数 + 目标 + 轨道信息，重算落点。

零第三方依赖（仅标准库 + tkinter）。

用法：python main.py
"""
import os
import re
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
    "excluded": "#8e24aa",   # 目标未启用 / 集数不在限定范围
}
STATUS_TEXT = {
    "": "待改名",
    "rename": "待改名",
    "skip": "已合规",
    "error": "识别失败",
    "conflict": "命名冲突",
    "excluded": "按目标排除",
}

# 页2 模板列的两个特殊值
TPL_GLOBAL = "（用兜底模板）"


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
        self._last_stats_sig = None   # R2：统计行只在扫描结果变化时输出一次
        self.last_log = ""
        self.busy = False
        # 手动分类：{normcase(src): {"ep":..., "target":..., "info":...}}
        # 为什么单独存：识别失败的项重算计划时会重新变回 error，
        # 存成覆盖表才能让用户的手工指定在多次「生成计划」之间保持住。
        self.manual = {}

        self._load_targets_and_templates()
        self._build_ui()

        self.title(CFG.title())
        try:
            self.geometry(self.cfg.get("window") or "1280x820")
        except tk.TclError:
            self.geometry("1280x820")
        self.minsize(1080, 700)

        self._center_on_screen()
        self.overrideredirect(False)
        self.attributes("-alpha", 1.0)
        self.deiconify()
        self.lift()
        self.focus_force()

        self._refresh_preview()

    # ------------------------------------------------------------------
    # 配置装载（含 v1.1.0 → v1.2.0 迁移）
    # ------------------------------------------------------------------
    def _load_targets_and_templates(self):
        """载入模板库与目标表，并迁移旧版「命名清单」。"""
        self.templates = [dict(t) for t in
                          (self.cfg.get("templates") or CORE.DEFAULT_TEMPLATES)]
        if not self.templates:
            self.templates = [dict(t) for t in CORE.DEFAULT_TEMPLATES]

        tgts = self.cfg.get("targets") or []
        if not tgts and self.cfg.get("enabled_types"):
            # v1.1.0 的「命名清单」（BUS-DX / STEM-MX-* …）折成目标表
            tgts = CORE.migrate_enabled_types(self.cfg["enabled_types"])
        self.targets = CORE.normalize_targets(tgts)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.nb = nb

        self.tab_rule = ttk.Frame(nb)
        self.tab_target = ttk.Frame(nb)
        self.tab_run = ttk.Frame(nb)
        self.tab_undo = ttk.Frame(nb)
        nb.add(self.tab_rule, text="  1 · 项目信息与模板  ")
        nb.add(self.tab_target, text="  2 · 目标与归位  ")
        nb.add(self.tab_run, text="  3 · 预览与执行  ")
        nb.add(self.tab_undo, text="  4 · 回溯与撤销  ")

        self._build_rule_tab()
        self._build_target_tab()
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

        # ---- 字段值 ----
        fld = ttk.LabelFrame(f, text="字段值（改这里即可换项目，无需碰模板）")
        fld.pack(fill="x", padx=10, pady=(10, 6))

        hint_map = {
            "片名": "剧名/项目名，如 法老、前夫、誓言",
            "日期": "如 0923 或 20260923",
            "版本": "如 V01、V02",
            "用户": "你的个人代号，如 7F（v1.1.0 里叫「档位」）",
        }
        self.field_vars = {}
        row = 0
        for key in ("片名", "日期", "版本", "用户"):
            ttk.Label(fld, text=key + ":").grid(row=row, column=0, sticky="w", **pad)
            v = tk.StringVar(value=self.cfg["fields"].get(key, ""))
            self.field_vars[key] = v
            ttk.Entry(fld, textvariable=v, width=26).grid(row=row, column=1,
                                                          sticky="w", **pad)
            ttk.Label(fld, text=hint_map.get(key, ""), style="Hint.TLabel").grid(
                row=row, column=2, sticky="w", padx=6)
            row += 1

        ex = ttk.Frame(fld)
        ex.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=(6, 4))
        ttk.Label(ex, text="实时样例:").pack(side="left")
        self.var_sample = tk.StringVar(value="")
        ttk.Label(ex, textvariable=self.var_sample, foreground=COLOR_OK,
                  font=("Consolas", 10, "bold")).pack(side="left", padx=8)

        # ---- 模板库 ----
        tb = ttk.LabelFrame(
            f, text="模板库（第 1 条为兜底模板：目标表里没单独指定模板的目标用它）")
        tb.pack(fill="both", expand=True, padx=10, pady=6)

        ttk.Label(
            tb, justify="left", style="Hint.TLabel",
            text=("模板与目标已拆开：MIX 可以走「全格式」，BUS/STEM 走「短格式」，"
                  "各改各的。占位符：{片名} {集数} {日期} {版本} {用户} {轨道信息}。\n"
                  "扩展名自动沿用源文件，模板里不要写 .wav。双击一行即可编辑。")
        ).pack(anchor="w", padx=8, pady=(6, 4))

        cols = ("no", "name", "tpl", "sample")
        self.tree_tpl = ttk.Treeview(tb, columns=cols, show="headings", height=8)
        self.tree_tpl.heading("no", text="#")
        self.tree_tpl.heading("name", text="模板名")
        self.tree_tpl.heading("tpl", text="模板内容")
        self.tree_tpl.heading("sample", text="样例（1 集 / DX BUS）")
        self.tree_tpl.column("no", width=40, anchor="center", stretch=False)
        self.tree_tpl.column("name", width=140, stretch=False)
        self.tree_tpl.column("tpl", width=420)
        self.tree_tpl.column("sample", width=320)
        ts = ttk.Scrollbar(tb, orient="vertical", command=self.tree_tpl.yview)
        self.tree_tpl.configure(yscrollcommand=ts.set)
        ts.pack(side="right", fill="y", pady=6)
        self.tree_tpl.pack(fill="both", expand=True, side="left", padx=(8, 0), pady=6)
        self.tree_tpl.bind("<Double-Button-1>", self._on_tpl_dblclick)

        b1 = ttk.Frame(f)
        b1.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(b1, text="保存为默认", command=self._save_cfg).pack(side="right", padx=4)
        ttk.Button(b1, text="恢复内置模板", command=self._reset_templates).pack(side="right", padx=4)
        ttk.Button(b1, text="删除模板", command=self._del_template).pack(side="right", padx=4)
        ttk.Button(b1, text="编辑模板", command=self._edit_template).pack(side="right", padx=4)
        ttk.Button(b1, text="新增模板", command=self._add_template).pack(side="right", padx=4)

        self._reload_templates()

        for v in self.field_vars.values():
            v.trace_add("write", lambda *a: self._on_field_change())

    def _on_field_change(self):
        """字段变了：样例要重算，模板库的样例列也要重算。"""
        self._reload_templates()
        self._refresh_preview()

    def _reload_templates(self):
        self.tree_tpl.delete(*self.tree_tpl.get_children())
        fields = self._fields()
        for i, t in enumerate(self.templates):
            tpl = str(t.get("tpl", ""))
            try:
                sample = CORE.render(tpl, "1", "DX BUS", fields) + ".wav"
            except Exception as e:
                sample = "[模板错误] %s" % e
            self.tree_tpl.insert("", "end", iid=str(i), values=(
                i + 1,
                str(t.get("name", "")),
                tpl,
                sample))

    def _tpl_sel_index(self):
        sel = self.tree_tpl.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except (ValueError, IndexError):
            return None

    def _add_template(self):
        name = simpledialog.askstring("新增模板", "模板名（如 全格式 / 短格式）:",
                                      parent=self)
        if not name:
            return
        tpl = simpledialog.askstring(
            "新增模板", "模板内容:\n可用 {片名} {集数} {日期} {版本} {用户} {轨道信息}",
            initialvalue=CORE.DEFAULT_TEMPLATE, parent=self)
        if not tpl:
            return
        self.templates.append({"name": name.strip(), "tpl": tpl.strip()})
        self._reload_templates()
        self._log("已新增模板: %s" % name.strip())

    def _on_tpl_dblclick(self, _event):
        self._edit_template()

    def _edit_template(self):
        i = self._tpl_sel_index()
        if i is None:
            messagebox.showinfo("未选中", "请先选中一行模板。")
            return
        t = self.templates[i]
        name = simpledialog.askstring("编辑模板", "模板名:", initialvalue=t.get("name", ""),
                                      parent=self)
        if name is None:
            return
        tpl = simpledialog.askstring("编辑模板", "模板内容:",
                                     initialvalue=t.get("tpl", ""), parent=self)
        if tpl is None:
            return
        t["name"] = name.strip()
        t["tpl"] = tpl.strip()
        self._reload_templates()
        self._refresh_preview()

    def _del_template(self):
        i = self._tpl_sel_index()
        if i is None:
            messagebox.showinfo("未选中", "请先选中一行模板。")
            return
        if len(self.templates) <= 1:
            messagebox.showwarning("不能删除", "至少要保留一套模板（第 1 条兼作兜底）。")
            return
        t = self.templates[i]
        if not messagebox.askokcancel("删除模板", "删除模板「%s」？" % t.get("name", "")):
            return
        self.templates.pop(i)
        self._reload_templates()
        self._refresh_preview()

    def _reset_templates(self):
        if not messagebox.askokcancel("恢复内置模板", "将丢弃当前模板库，恢复内置默认？"):
            return
        self.templates = [dict(t) for t in CORE.DEFAULT_TEMPLATES]
        self._reload_templates()
        self._refresh_preview()
        self._log("已恢复内置模板库")

    def _global_template(self):
        """兜底模板 = 模板库第 1 条的内容。"""
        if self.templates:
            tpl = str(self.templates[0].get("tpl", "")).strip()
            if tpl:
                return tpl
        return CORE.DEFAULT_TEMPLATE

    # ============ 页2：目标与归位 ============
    def _build_target_tab(self):
        """可编辑的目标表 + 识别规则表。

        为什么这一页：交付类型并非每集都一样 —— 第 1 集可能只交 BUS，
        第 4 集才补 STEM。用「启用 + 限定集数」表达这种差异，比改模板或事后
        挪文件都安全（未启用的目标在计划阶段就标「按目标排除」，不动盘）。
        """
        f = self.tab_target
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=3)
        f.rowconfigure(1, weight=2)

        ttk.Label(
            f, justify="left", style="Hint.TLabel",
            text=("目标决定「东西放哪、用哪套模板」。双击：『启用』列切换勾选，"
                  "『归位目录』『限定集数』列输入，『用哪套模板』列从模板库选。\n"
                  "限定集数留空 = 全部集；填 1 或 1,3-5 可只对指定集生效。")
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

        wrap = ttk.LabelFrame(f, text="目标与归位（双击编辑）")
        wrap.grid(row=0, column=0, sticky="nsew", padx=10, pady=(22, 6))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        cols = ("enabled", "name", "dir", "tpl", "eps", "note")
        self.tree_tgt = ttk.Treeview(wrap, columns=cols, show="headings", height=7)
        self.tree_tgt.heading("enabled", text="启用")
        self.tree_tgt.heading("name", text="目标")
        self.tree_tgt.heading("dir", text="归位目录")
        self.tree_tgt.heading("tpl", text="用哪套模板")
        self.tree_tgt.heading("eps", text="限定集数")
        self.tree_tgt.heading("note", text="说明")
        self.tree_tgt.column("enabled", width=70, anchor="center", stretch=False)
        self.tree_tgt.column("name", width=90, anchor="center", stretch=False)
        self.tree_tgt.column("dir", width=110, anchor="center", stretch=False)
        self.tree_tgt.column("tpl", width=180, stretch=False)
        self.tree_tgt.column("eps", width=120, anchor="center", stretch=False)
        self.tree_tgt.column("note", width=340)
        tsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree_tgt.yview)
        self.tree_tgt.configure(yscrollcommand=tsb.set)
        tsb.grid(row=0, column=1, sticky="ns", pady=6)
        self.tree_tgt.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=6)
        self.tree_tgt.tag_configure("on", foreground=COLOR_OK)
        self.tree_tgt.tag_configure("off", foreground="#9e9e9e")
        self.tree_tgt.tag_configure("limited", foreground=COLOR_WARN)
        self.tree_tgt.bind("<Double-Button-1>", self._on_target_dblclick)

        self._reload_targets()

        tb = ttk.Frame(f)
        tb.grid(row=0, column=0, sticky="sew", padx=16, pady=(0, 16))
        ttk.Button(tb, text="保存为默认", command=self._save_cfg).pack(side="right", padx=4)
        ttk.Button(tb, text="恢复内置目标", command=self._reset_targets).pack(side="right", padx=4)
        ttk.Button(tb, text="删除目标", command=self._del_target).pack(side="right", padx=4)
        ttk.Button(tb, text="新增目标", command=self._add_target).pack(side="right", padx=4)
        ttk.Button(tb, text="全不选", command=lambda: self._set_all_targets(False)).pack(side="right", padx=4)
        ttk.Button(tb, text="全选", command=lambda: self._set_all_targets(True)).pack(side="right", padx=4)

        # ---- 识别规则（高级）----
        rl = ttk.LabelFrame(
            f, text="识别规则（高级：把历史命名映射到目标；自上而下首个命中生效，一般不用改）")
        rl.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        rl.rowconfigure(0, weight=1)
        rl.columnconfigure(0, weight=1)

        rcols = ("target", "pattern", "out")
        self.tree_rules = ttk.Treeview(rl, columns=rcols, show="headings", height=6)
        self.tree_rules.heading("target", text="目标")
        self.tree_rules.heading("pattern", text="匹配模式（支持 {片名} 等宽松占位符）")
        self.tree_rules.heading("out", text="轨道信息")
        self.tree_rules.column("target", width=90, anchor="center", stretch=False)
        self.tree_rules.column("pattern", width=620)
        self.tree_rules.column("out", width=170, stretch=False)
        rsb = ttk.Scrollbar(rl, orient="vertical", command=self.tree_rules.yview)
        self.tree_rules.configure(yscrollcommand=rsb.set)
        rsb.grid(row=0, column=1, sticky="ns", pady=6)
        self.tree_rules.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=6)

        self.rules = [list(r) for r in
                      (self.cfg["rules"] if self.cfg.get("rules") else CORE.DEFAULT_RULES)]
        self._reload_rules()

        rb = ttk.Frame(f)
        rb.grid(row=1, column=0, sticky="sew", padx=16, pady=(0, 20))
        ttk.Button(rb, text="恢复内置规则", command=self._reset_rules).pack(side="right", padx=4)

    def _reload_targets(self):
        self.tree_tgt.delete(*self.tree_tgt.get_children())
        for idx, t in enumerate(self.targets):
            self.tree_tgt.insert("", "end", iid=str(idx),
                                 values=self._target_row_values(t),
                                 tags=(self._target_row_tag(t),))

    def _target_row_values(self, t):
        return ("[√] 启用" if t.get("enabled", True) else "[ ] 停用",
                t.get("name", ""),
                t.get("dir", "") or "（集根）",
                t.get("tpl_name", "") or TPL_GLOBAL,
                t.get("eps", "") or "（全部集）",
                t.get("note", ""))

    @staticmethod
    def _target_row_tag(t):
        if not t.get("enabled", True):
            return "off"
        if CORE.parse_eps(t.get("eps")):
            return "limited"
        return "on"

    def _target_sel_index(self):
        sel = self.tree_tgt.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except (ValueError, IndexError):
            return None

    def _on_target_dblclick(self, event):
        row = self.tree_tgt.identify_row(event.y)
        col = self.tree_tgt.identify_column(event.x)
        if not row:
            return
        try:
            t = self.targets[int(row)]
        except (ValueError, IndexError):
            return

        if col == "#1":                      # 启用
            t["enabled"] = not t.get("enabled", True)
        elif col == "#3":                    # 归位目录
            new = simpledialog.askstring(
                "归位目录",
                "放到集目录下的哪一层？（留空 = 直接放集根）\n例：BUS、STEM",
                initialvalue=t.get("dir", ""), parent=self)
            if new is None:
                return
            t["dir"] = new.strip()
        elif col == "#4":                    # 用哪套模板
            picked = self._pick_template(t)
            if picked is None:
                return
        elif col == "#5":                    # 限定集数
            new = simpledialog.askstring(
                "限定集数",
                "只对哪些集生效？（留空 = 全部集）\n例：1 或 1,3-5",
                initialvalue=t.get("eps", ""), parent=self)
            if new is None:
                return
            t["eps"] = new.strip()
        else:
            return
        self._reload_targets()
        self._refresh_preview()

    def _pick_template(self, t):
        """从模板库 + 两个特殊值里挑一套，写回 t 的 templates/tpl_name。"""
        opts = [(TPL_GLOBAL, TPL_GLOBAL + "（第 1 条）")]
        for tp in self.templates:
            opts.append((str(tp.get("name", "")), "模板：%s" % tp.get("name", "")))
        opts.append((CORE.KEEP_NAME, "保持原名（只归类、不改名）"))

        cur = t.get("tpl_name", "") or TPL_GLOBAL
        picked = self._choose_dialog("用哪套模板",
                                     "目标「%s」改名时用哪一套？" % t.get("name", ""),
                                     opts, cur)
        if picked is None:
            return None
        if picked == TPL_GLOBAL:
            t["templates"] = []
            t["tpl_name"] = ""
        elif picked == CORE.KEEP_NAME:
            t["templates"] = [CORE.KEEP_NAME]
            t["tpl_name"] = CORE.KEEP_NAME
        else:
            hit = [tp for tp in self.templates if str(tp.get("name", "")) == picked]
            if not hit:
                return None
            t["templates"] = [str(hit[0].get("tpl", ""))]
            t["tpl_name"] = picked
        return picked

    def _choose_dialog(self, title, prompt, options, current=None):
        """通用单选对话框。options = [(value, label)]，取消返回 None。"""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("440x380")
        ttk.Label(dlg, text=prompt, wraplength=400, justify="left").pack(
            anchor="w", padx=12, pady=(12, 8))
        lb = tk.Listbox(dlg, activestyle="dotbox")
        lb.pack(fill="both", expand=True, padx=12)
        for _v, label in options:
            lb.insert("end", label)
        for i, (v, _l) in enumerate(options):
            if current is not None and v == current:
                lb.selection_set(i)
                lb.see(i)
                break

        result = {"v": None}

        def ok():
            sel = lb.curselection()
            if sel:
                result["v"] = options[sel[0]][0]
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=12, pady=10)
        ttk.Button(bf, text="确定", command=ok).pack(side="right", padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="right", padx=4)
        lb.bind("<Double-Button-1>", lambda _e: ok())
        self.wait_window(dlg)
        return result["v"]

    def _add_target(self):
        name = simpledialog.askstring("新增目标", "目标名（如 BUS / STEM / MIX）:", parent=self)
        if not name:
            return
        name = name.strip().upper()
        if any(t.get("name") == name for t in self.targets):
            messagebox.showwarning("已存在", "目标「%s」已经在表里了。" % name)
            return
        self.targets.append({"name": name, "dir": name, "enabled": True, "eps": "",
                             "note": "自定义目标", "templates": [], "tpl_name": ""})
        self._reload_targets()
        self._refresh_preview()

    def _del_target(self):
        i = self._target_sel_index()
        if i is None:
            messagebox.showinfo("未选中", "请先选中一行目标。")
            return
        t = self.targets[i]
        if not messagebox.askokcancel(
                "删除目标", "删除目标「%s」？\n（已归属该目标的文件将因『目标表未列出』被判为排除）"
                % t.get("name", "")):
            return
        self.targets.pop(i)
        self._reload_targets()
        self._refresh_preview()

    def _set_all_targets(self, flag):
        for t in self.targets:
            t["enabled"] = flag
        self._reload_targets()
        self._refresh_preview()

    def _reset_targets(self):
        if not messagebox.askokcancel("恢复内置目标", "将丢弃当前目标表，恢复内置默认？"):
            return
        self.targets = CORE.normalize_targets(CORE.DEFAULT_TARGETS)
        self._reload_targets()
        self._refresh_preview()
        self._log("已恢复内置目标表")

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

    # ============ 页3：预览与执行 ============
    def _build_run_tab(self):
        f = self.tab_run

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

        # v1.3.0 开关（2026-09-23 用户新增能力，默认全开）
        opt2 = ttk.Frame(top)
        opt2.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 6))
        self.var_mtime_date = tk.BooleanVar(value=bool(self.cfg.get("date_from_mtime", True)))
        ttk.Checkbutton(
            opt2, text="日期用文件修改时间兜底（源名/目录都没有日期时）",
            variable=self.var_mtime_date,
            command=self._refresh_preview).pack(side="left", padx=(0, 12))
        self.var_rename_dirs = tk.BooleanVar(value=bool(self.cfg.get("rename_ep_dirs", True)))
        ttk.Checkbutton(
            opt2, text="集目录按「片名 N集 日期 版本 用户」改名",
            variable=self.var_rename_dirs,
            command=self._refresh_preview).pack(side="left")

        ttk.Label(top, foreground="#666", justify="left",
                  text=("落点由页2 的「目标表」决定：MIX → 集根；BUS → 集目录\\BUS；"
                        "STEM/AIFX → 集目录\\STEM。集目录名与 Master 文件名同构；"
                        "改名后旧目录空壳只提醒、不自动删。")
                  ).grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 6))

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
        self.btn_manual = ttk.Button(act, text="手动分类…", command=self._on_manual)
        self.btn_manual.pack(side="right", padx=4)

        pv = ttk.LabelFrame(
            f, text="变更计划（先预览；识别失败的可选中后点「手动分类」指定集数与目标）")
        pv.pack(fill="both", expand=True, padx=10, pady=6)

        cols = ("st", "old", "new", "target", "note")
        self.tree_plan = ttk.Treeview(pv, columns=cols, show="headings")
        self.tree_plan.heading("st", text="状态")
        self.tree_plan.heading("old", text="原文件名")
        self.tree_plan.heading("new", text="新文件名")
        self.tree_plan.heading("target", text="目标")
        self.tree_plan.heading("note", text="说明")
        self.tree_plan.column("st", width=90, anchor="center", stretch=False)
        self.tree_plan.column("old", width=330)
        self.tree_plan.column("new", width=360)
        self.tree_plan.column("target", width=90, anchor="center", stretch=False)
        self.tree_plan.column("note", width=230)
        for st, col in STATUS_COLOR.items():
            self.tree_plan.tag_configure(st or "ok", foreground=col)

        vs = ttk.Scrollbar(pv, orient="vertical", command=self.tree_plan.yview)
        self.tree_plan.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y", pady=6)
        self.tree_plan.pack(fill="both", expand=True, side="left", padx=(6, 0), pady=6)
        self.tree_plan.bind("<Double-Button-1>", self._on_plan_dblclick)

        lg = ttk.LabelFrame(f, text="日志")
        lg.pack(fill="both", padx=10, pady=(0, 10))
        self.txt_log = tk.Text(lg, height=6, wrap="none", state="disabled",
                               font=("Consolas", 9))
        ls = ttk.Scrollbar(lg, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=ls.set)
        ls.pack(side="right", fill="y", padx=(0, 4), pady=4)
        self.txt_log.pack(fill="both", expand=True, side="left", padx=6, pady=4)

    # ============ 页4：回溯与撤销 ============
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
            w = self.winfo_width() or 1280
            h = self.winfo_height() or 820
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

    # ---- 计划 ----
    def _refresh_preview(self):
        """重建计划表（同时更新实时样例）。这是「生成计划」的唯一入口。"""
        # 1) 样例（用兜底模板，即模板库第 1 条）
        try:
            sample = CORE.render(self._global_template(), "1", "DX BUS",
                                 self._fields()) + ".wav"
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
            items, stats = CORE.make_plan(paths, self._global_template(),
                                          self.rules, self._fields(),
                                          targets=self.targets, root=root,
                                          date_from_mtime=self.var_mtime_date.get(),
                                          rename_ep_dirs=self.var_rename_dirs.get())
            items, stats = self._apply_manual(items)
        except Exception as e:
            self.items, self.stats = [], {}
            self._set_plan_state("规划失败: %s" % e, "bad")
            self.btn_apply.configure(state="disabled")
            return

        self.items, self.stats = items, stats
        self._fill_plan(items)
        self._update_plan_state()
        self._log_scan_stats()

    # ---- R2：识别率统计行 ----
    def _log_scan_stats(self):
        """跑完输出统计行（X 文件 / 已合规 / 失败 / 清单）；
        失败比例 ≥10% 时提示「识别规则可能需要补」。同为结果不变不重复刷。"""
        s = self.stats
        if not s or s.get("total", 0) == 0:
            return
        sig = tuple(sorted(s.items()))
        if sig == self._last_stats_sig:
            return
        self._last_stats_sig = sig
        total = s["total"]
        bad = [i for i in self.items if i.status in ("error", "conflict")]
        line = "统计：共 %d 个文件 · 待改名 %d · 已合规 %d" % (
            total, s["rename"], s["skip"])
        if s.get("excluded"):
            line += " · 按目标排除 %d" % s["excluded"]
        if s["error"]:
            line += " · 识别失败 %d" % s["error"]
        if s["conflict"]:
            line += " · 冲突 %d" % s["conflict"]
        self._log(line)
        if bad:
            self._log("失败/冲突清单（前 20 条）：")
            for i in bad[:20]:
                self._log("  · %s（%s）" % (os.path.basename(i.src),
                                            (i.note or i.status).strip()))
        if total and len(bad) * 10 >= total:
            self._log("⚠ 失败比例 ≥10%%（%d/%d），识别规则可能需要补"
                      "（页1 规则库 / 页2 模板与归位）。" % (len(bad), total))
        _log = CFG.setup_logging()
        if _log is not None:
            _log.info("扫描统计: %s | 失败数=%d", line, len(bad))

    def _apply_manual(self, items):
        """把手动分类的覆盖应用回计划，并重算这些项的冲突状态。"""
        if not self.manual:
            return items, CORE.count_stats(items)
        touched = False
        for idx, i in enumerate(items):
            ov = self.manual.get(os.path.normcase(i.src))
            if not ov:
                continue
            items[idx] = CORE.manual_plan_item(
                i.src, ov.get("ep", ""), ov.get("target", ""), ov.get("info", ""),
                self._global_template(), self._fields(),
                root=(self.var_root.get() or "").strip(), targets=self.targets,
                rename_ep_dirs=self.var_rename_dirs.get())
            touched = True
        if not touched:
            return items, CORE.count_stats(items)
        CORE.mark_conflicts(items)
        return items, CORE.count_stats(items)

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
                msg += " / 按目标排除 %d" % s["excluded"]
            if s["error"]:
                msg += " / 识别失败 %d" % s["error"]
            if s["conflict"]:
                msg += " / 冲突 %d" % s["conflict"]
            self._set_plan_state(msg, "warn" if (s["error"] or s["conflict"]) else "ok")
            self.btn_apply.configure(state="normal")
        self.var_status.set("扫描 %d 个文件 · %s" % (s["total"], self.var_plan_state.get()))

    def _set_plan_state(self, text, kind):
        style = {"ok": "Ok.TLabel", "bad": "Bad.TLabel", "warn": "Warn.TLabel"}.get(
            kind, "Hint.TLabel")
        self.var_plan_state.set(text)
        self.lbl_plan_state.configure(style=style)

    def _fill_plan(self, items):
        self.tree_plan.delete(*self.tree_plan.get_children())
        for n, i in enumerate(items):
            st = i.status or "ok"
            note = i.note
            if os.path.normcase(i.src) in self.manual:
                note = ("[人工分类] " + note).strip()
            if not note and st == "ok":
                note = "%s · %s集" % (i.target, CORE.normalize_ep(i.ep))
            self.tree_plan.insert("", "end", iid=str(n), values=(
                STATUS_TEXT.get(i.status, i.status),
                os.path.basename(i.src),
                os.path.basename(i.dst),
                i.target,
                note), tags=(st,))

    # ---- 手动分类 ----
    def _on_plan_dblclick(self, event):
        row = self.tree_plan.identify_row(event.y)
        if not row:
            return
        self.tree_plan.selection_set(row)
        self._on_manual()

    def _on_manual(self):
        sel = self.tree_plan.selection()
        if not sel:
            messagebox.showinfo("未选中", "请先在计划表里选中一行（通常是「识别失败」的）。")
            return
        try:
            item = self.items[int(sel[0])]
        except (ValueError, IndexError):
            return
        if item.status in ("conflict",):
            messagebox.showinfo("无需手动分类",
                                "该行是「命名冲突」，不是识别失败 —— 请改页2 的目标/模板，"
                                "或直接看目标名是否重复。")
            return
        self._open_manual_dialog(item)

    def _open_manual_dialog(self, item):
        """手动分类对话框：指定 集数 + 目标 + 轨道信息。"""
        dlg = tk.Toplevel(self)
        dlg.title("手动分类")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("560x300")

        ttk.Label(dlg, text=os.path.basename(item.src), font=("", 10, "bold"),
                  wraplength=520, justify="left").pack(anchor="w", padx=14, pady=(12, 4))
        ttk.Label(dlg, foreground="#666", wraplength=520, justify="left",
                  text="识别不出来的文件，人工指定它属于第几集、归哪个目标、轨道信息是什么。"
                       "指定后会走与自动识别完全相同的命名逻辑。").pack(
            anchor="w", padx=14, pady=(0, 10))

        body = ttk.Frame(dlg)
        body.pack(fill="x", padx=14)

        # 预填：从文件名里挑第一段数字当集数候选
        m = re.search(r"(\d+)", os.path.basename(item.src))
        guess_ep = m.group(1) if m else item.ep
        guess_info = CORE.guess_info_from_name(item.src)
        ov = self.manual.get(os.path.normcase(item.src)) or {}

        ttk.Label(body, text="集数:").grid(row=0, column=0, sticky="w", pady=5)
        var_ep = tk.StringVar(value=str(ov.get("ep") or guess_ep or ""))
        ttk.Entry(body, textvariable=var_ep, width=20).grid(row=0, column=1, sticky="w", pady=5)
        ttk.Label(body, text="（只填数字，如 20）", style="Hint.TLabel").grid(
            row=0, column=2, sticky="w", padx=8)

        ttk.Label(body, text="目标:").grid(row=1, column=0, sticky="w", pady=5)
        names = [t.get("name", "") for t in self.targets]
        var_tgt = tk.StringVar(value=str(ov.get("target") or (names[0] if names else "STEM")))
        cb = ttk.Combobox(body, textvariable=var_tgt, values=names, width=18,
                          state="readonly")
        cb.grid(row=1, column=1, sticky="w", pady=5)
        ttk.Label(body, text="（放哪、用哪套模板由页2 目标表决定）",
                  style="Hint.TLabel").grid(row=1, column=2, sticky="w", padx=8)

        ttk.Label(body, text="轨道信息:").grid(row=2, column=0, sticky="w", pady=5)
        var_info = tk.StringVar(value=str(ov.get("info") or guess_info or ""))
        ttk.Entry(body, textvariable=var_info, width=32).grid(row=2, column=1,
                                                              columnspan=2,
                                                              sticky="we", pady=5)
        ttk.Label(body, text="（会原样填进模板的 {轨道信息}，如 DX BUS / Ai FX 1）",
                  style="Hint.TLabel").grid(row=3, column=1, columnspan=2,
                                            sticky="w", padx=0)

        ttk.Label(dlg, text="预览:", style="Hint.TLabel").pack(anchor="w", padx=14,
                                                              pady=(10, 0))
        var_prev = tk.StringVar(value="")
        ttk.Label(dlg, textvariable=var_prev, foreground=COLOR_OK,
                  font=("Consolas", 10, "bold"), wraplength=520,
                  justify="left").pack(anchor="w", padx=14)

        def update_prev(*_a):
            try:
                tmp = CORE.manual_plan_item(
                    item.src, var_ep.get().strip(), var_tgt.get().strip(),
                    var_info.get().strip(), self._global_template(), self._fields(),
                    root=(self.var_root.get() or "").strip(), targets=self.targets,
                    rename_ep_dirs=self.var_rename_dirs.get())
                var_prev.set("→ %s\\%s" % (os.path.basename(os.path.dirname(tmp.dst)),
                                           os.path.basename(tmp.dst)))
            except Exception as e:
                var_prev.set("[无法预览] %s" % e)

        for v in (var_ep, var_tgt, var_info):
            v.trace_add("write", update_prev)
        update_prev()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=14, pady=12)

        def ok():
            ep = var_ep.get().strip()
            if not ep.isdigit():
                messagebox.showwarning("集数无效", "集数请填数字，如 20。", parent=dlg)
                return
            self.manual[os.path.normcase(item.src)] = {
                "ep": ep, "target": var_tgt.get().strip(), "info": var_info.get().strip()}
            dlg.destroy()
            self._refresh_preview()

        def clear():
            self.manual.pop(os.path.normcase(item.src), None)
            dlg.destroy()
            self._refresh_preview()

        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="right", padx=4)
        ttk.Button(bf, text="确定", command=ok).pack(side="right", padx=4)
        if os.path.normcase(item.src) in self.manual:
            ttk.Button(bf, text="取消该条手动指定", command=clear).pack(side="left", padx=4)

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
                "即将重命名/移动 %d 个文件。\n\n"
                "· 会生成回溯日志 rename_log_*.csv，可随时撤销\n"
                "· 如有同名文件将按计划跳过（不会覆盖）%s\n\n"
                "是否继续？" % (len(todo), warn)):
            return

        self.busy = True
        self.btn_apply.configure(state="disabled")
        self._log("=== 开始执行：待处理 %d ===" % len(todo))

        def worker():
            try:
                done, failed, _ = CORE.apply_plan(self.items, write_log=False)
                _log = CFG.setup_logging()
                if _log is not None:
                    _log.info("执行重命名：成功 %d / 失败 %d", len(done), len(failed))
                self._log("完成: 成功 %d / 失败 %d" % (len(done), len(failed)))
                for src, dst, err in failed:
                    self._log("  失败: %s -> %s (%s)" % (os.path.basename(src),
                                                         os.path.basename(dst), err))
                logp = self._write_log(done)
                if logp:
                    self.last_log = logp
                    self._log("回溯日志: %s（%d 条）" % (logp, len(done)))
                    self.after(0, lambda: self.var_logfile.set(logp))
                # v1.3.0：集目录改名后旧目录可能空了 —— 只提醒，不自动删
                try:
                    emptied = CORE.list_emptied_dirs(self.items)
                except Exception:
                    emptied = []
                if emptied:
                    self._log("⚠ 以下原集目录已空，可自行回收（工具不代删）：")
                    for d in emptied:
                        self._log("  空目录: %s" % d)
            except Exception:
                self._log(traceback.format_exc())
            finally:
                self.busy = False
                self.after(0, self._after_apply)

        threading.Thread(target=worker, daemon=True).start()

    def _write_log(self, rows):
        if not rows:
            return None
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
        self.manual.clear()          # 落盘后手动指定已完成使命
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
            body = rows[1:] if rows and rows[0][:2] == CORE.LOG_HEADER else rows
            lines = ["日志: %s" % p,
                     "共 %d 条记录（倒序撤销）" % len(body), ""]
            for r in body:
                if len(r) >= 2:
                    ok = "✓" if os.path.exists(r[1]) else "✗ 新文件不存在"
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
        _log = CFG.setup_logging()
        if _log is not None:
            _log.info("撤销（%s）：成功 %d / 失败 %d", p, len(done), len(failed))
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
        cfg["template"] = self._global_template()
        cfg["fields"] = self._fields()
        cfg["rules"] = [list(r) for r in self.rules]
        cfg["templates"] = [dict(t) for t in self.templates]
        cfg["targets"] = [dict(t) for t in self.targets]
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
    _log = CFG.setup_logging()
    if _log is not None:
        _log.info("GUI 启动 v%s (%s)", CFG.APP_VERSION, CFG.build_date())
    try:
        App().mainloop()
    except Exception:
        _safe_io()
        tb = traceback.format_exc()
        if _log is not None:
            _log.error("启动异常：\n%s", tb)
        try:
            messagebox.showerror("启动失败", tb)
        except Exception:
            sys.stderr.write(tb)


if __name__ == "__main__":
    main()
