# -*- coding: utf-8 -*-
"""
PT 工程文件夹生成器 (pt-project-folder-builder)
=================================================
根据 D:/DAW-Project/00文件夹模板 批量建立剧集工程文件夹。

GUI 输入：
  1. 集数      如 "1-10, 23, 38, 46-49"（支持逗号分隔 + 连字符区间，自动去重排序）
  2. 项目名称   如 "誓言"（对应命名里的「项目名」）
  3. 输出路径   新项目根将建在此路径下
  4. 模板路径   默认 D:/DAW-Project/00文件夹模板（可改）

命名 = 规则 + 信息 两部分拆开：
  - 规则（结构，固定默认）:  {序号} - {项目名}{等级} _ {日期} _ {用户名}
  - 信息（均可更改）:         序号(自动顺延) / 项目名 / 等级(ABCD) / 日期 / 用户名称
  默认示例:  10-誓言D_20260920_7F
  - 集数文件夹默认命名:  项目名+数字（如 睡父亲1）；可在「命名信息」切换 纯数字 / 项目名+等级+数字

零第三方依赖，仅用标准库 + tkinter。可用 build.ps1 打包为 exe。
"""

import os
import re
import sys
import shutil
import datetime
import traceback
import threading

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox


# ---------------------------------------------------------------------------
# 命名：规则与信息（与 GUI 解耦，便于无界面测试）
# ---------------------------------------------------------------------------

# 命名规则（结构，默认固定）。序号不再作为独立前缀开关，而是模板中的一个占位符。
NAMING_RULE = "{序号}-{项目名}{等级}_{日期}_{用户名}"


def build_project_name(seq, name, level, date_str, username):
    """按规则拼出项目根目录名。

    信息字段：seq(序号) / name(项目名) / level(等级) / date_str(日期) / username(用户名称)。
    - 等级直接拼在项目名之后（如 誓言D），无分隔符。
    - 若序号为空，则退化为「项目名等级_日期_用户名」（不写前导连字符）。
    """
    body = "%s%s_%s_%s" % (name.strip(), (level or ""), date_str, username)
    seq = (seq or "").strip()
    return ("%s-%s" % (seq, body)) if seq else body


def build_episode_name(name, level, ep, mode):
    """集数文件夹名（与项目根命名拆开，可独立配置）。

    mode:
      'num'           -> '1'                    （纯数字，旧默认）
      'name_num'      -> '睡父亲1'              （项目名+数字，新默认）
      'name_level_num'-> '睡父亲D1'             （项目名+等级+数字）
    等级直接拼在项目名之后（如 睡父亲D），无分隔符。
    """
    nm = (name or "").strip()
    if mode == "num":
        return str(ep)
    if mode == "name_level_num":
        return "%s%s%d" % (nm, (level or ""), ep)
    return "%s%d" % (nm, ep)  # name_num


def detect_next_seq(output_root):
    """扫描输出目录下已有的「数字前缀」文件夹，返回下一个序号（max+1）。"""
    try:
        names = [n for n in os.listdir(output_root)
                 if os.path.isdir(os.path.join(output_root, n))]
    except OSError:
        return 1
    mx = 0
    for n in names:
        m = re.match(r"^(\d+)", n)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


# ---------------------------------------------------------------------------
# 核心逻辑（其余与 GUI 解耦，便于无界面测试）
# ---------------------------------------------------------------------------

def parse_episodes(text):
    """解析 "1-10, 23, 38, 46-49" -> [1,2,...,10,23,38,46,47,48,49]

    支持：逗号分隔、连字符区间（允许两侧空格）、自动去重、升序排列。
    非法片段会被忽略并在返回 (列表, 错误列表)。
    """
    episodes = []
    errors = []
    text = (text or "").strip()
    if not text:
        return [], ["集数输入为空"]
    for raw in text.split(","):
        part = raw.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = a.strip(), b.strip()
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                errors.append("无法解析区间: %r" % part)
                continue
            if lo > hi:
                lo, hi = hi, lo
            episodes.extend(range(lo, hi + 1))
        else:
            try:
                episodes.append(int(part))
            except ValueError:
                errors.append("无法解析数字: %r" % part)
                continue
    seen, out = set(), []
    for e in sorted(episodes):
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out, errors


def locate_template_ptx(template_root):
    """在模板的 Project模板 下找到第一个 .ptx 作为复制源。"""
    project_tpl = os.path.join(template_root, "Project模板")
    if not os.path.isdir(project_tpl):
        # 兼容：模板根直接含分集文件夹
        project_tpl = template_root
    for root, _dirs, files in os.walk(project_tpl):
        for f in files:
            if f.lower().endswith(".ptx"):
                return os.path.join(root, f)
    return None


def plan_creation(episodes, name, seq, level, date_str, username,
                 output_root, template_root, ep_placement, ptx_mode, ep_naming):
    """返回 (project_root, [(action, path), ...], warnings)

    action ∈ {"mkdir", "copy"}；path 为将要创建/复制的目标路径。
    不实际写入磁盘，只规划。
    """
    warnings = []
    proj_dir_name = build_project_name(seq, name, level, date_str, username)
    project_root = os.path.join(output_root, proj_dir_name)

    if os.path.exists(project_root):
        warnings.append("项目根已存在，将在其内增量建立（已存在项跳过）: %s" % project_root)

    steps = []

    # 1) 文件夹模板（分类目录）合并到项目根
    folder_tpl = os.path.join(template_root, "文件夹模板")
    if os.path.isdir(folder_tpl):
        for item in sorted(os.listdir(folder_tpl)):
            src = os.path.join(folder_tpl, item)
            dst = os.path.join(project_root, item)
            if os.path.isdir(src):
                steps.append(("mkdir", dst))  # 顶级分类目录本身
                for sub in _walk_rel(src):
                    steps.append(("mkdir", os.path.join(dst, sub)))
            else:
                steps.append(("copy", dst))
    else:
        warnings.append("未找到 文件夹模板 子目录: %s" % folder_tpl)

    # 2) 集数文件夹
    src_ptx = locate_template_ptx(template_root) if ptx_mode != "none" else None
    if ptx_mode != "none" and src_ptx is None:
        warnings.append("模板中未找到可复制的 .ptx 文件，将改为只建空文件夹")

    ep_names = [build_episode_name(name, level, ep, ep_naming) for ep in episodes]
    for ep_name in ep_names:
        if ep_placement == "Project子目录":
            ep_dir = os.path.join(project_root, "Project", ep_name)
        else:
            ep_dir = os.path.join(project_root, ep_name)
        steps.append(("mkdir", ep_dir))
        if ptx_mode != "none" and src_ptx is not None:
            if ptx_mode == "重命名":
                dst_name = "%s.ptx" % ep_name
            else:
                dst_name = os.path.basename(src_ptx)
            steps.append(("copy", os.path.join(ep_dir, dst_name)))

    return project_root, steps, warnings, ep_names


def _walk_rel(src):
    """返回 src 下相对路径列表（含目录，用于 mkdir 规划）。"""
    rels = []
    for root, dirs, _files in os.walk(src):
        for d in dirs:
            rels.append(os.path.relpath(os.path.join(root, d), src))
    return sorted(rels)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # 避免 exe 启动时的空白 tk 残窗
        self.title("PT 工程文件夹生成器")
        self._center_on_screen(760, 720)
        self.configure(padx=12, pady=12)

        self.template_default = r"D:\DAW-Project\00文件夹模板"
        self.output_default = r"D:\DAW-Project"
        self.date_str = datetime.datetime.now().strftime("%Y%m%d")

        # 命名信息（默认）
        self.var_seq = tk.StringVar(value=str(detect_next_seq(self.output_default)))
        self.var_level = tk.StringVar(value="D")
        self.var_user = tk.StringVar(value="7F")
        self.var_ep_naming = tk.StringVar(value="name_num")  # 集数文件夹默认: 项目名+数字

        self._build_widgets()
        self.deiconify()
        self.lift()
        self.focus_force()

    # ----- 布局 -----
    def _build_widgets(self):
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True)

        # 模板路径
        ttk.Label(f, text="模板路径").grid(row=0, column=0, sticky="w", pady=2)
        self.var_template = tk.StringVar(value=self.template_default)
        ttk.Entry(f, textvariable=self.var_template, width=56).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="浏览", command=self._pick_template).grid(row=0, column=2)

        # 输出路径
        ttk.Label(f, text="输出路径").grid(row=1, column=0, sticky="w", pady=2)
        self.var_output = tk.StringVar(value=self.output_default)
        ttk.Entry(f, textvariable=self.var_output, width=56).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="浏览", command=self._pick_output).grid(row=1, column=2)

        # 集数
        ttk.Label(f, text="集数").grid(row=2, column=0, sticky="nw", pady=2)
        self.var_eps = tk.StringVar(value="1-10, 23, 38, 46-49")
        ttk.Entry(f, textvariable=self.var_eps, width=56).grid(row=2, column=1, sticky="ew", padx=4, columnspan=2)
        ttk.Label(f, text="支持 逗号分隔 + 连字符区间，如 1-10, 23, 38, 46-49").grid(row=3, column=1, sticky="w", padx=4)

        # 项目名称（对应命名里的「项目名」）
        ttk.Label(f, text="项目名称").grid(row=4, column=0, sticky="w", pady=2)
        self.var_name = tk.StringVar(value="誓言")
        ttk.Entry(f, textvariable=self.var_name, width=56).grid(row=4, column=1, sticky="ew", padx=4, columnspan=2)

        # ====== 命名规则（结构，固定默认）======
        rule_f = ttk.LabelFrame(f, text="命名规则（结构，默认固定）")
        rule_f.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        ttk.Label(rule_f, text="结构:  {序号} - {项目名}{等级} _ {日期} _ {用户名}").pack(anchor="w", padx=8, pady=(4, 0))
        ttk.Label(rule_f, text="集数文件夹默认: 项目名+数字（如 睡父亲1）；可在下方「命名信息」切换").pack(anchor="w", padx=8, pady=(0, 2))
        self.var_example = tk.StringVar(value="")
        ttk.Label(rule_f, textvariable=self.var_example, foreground="#2a7").pack(anchor="w", padx=8, pady=(0, 6))

        # ====== 命名信息（均可更改）======
        info_f = ttk.LabelFrame(f, text="命名信息（均可更改）")
        info_f.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(2, 4))
        info_f.columnconfigure(1, weight=1)

        # 序号
        ttk.Label(info_f, text="序号").grid(row=0, column=0, sticky="w", padx=8, pady=3)
        ttk.Entry(info_f, textvariable=self.var_seq, width=10).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(info_f, text="自动顺延（扫描输出目录下最大数字前缀 +1），可手动改").grid(row=0, column=2, sticky="w", padx=8)

        # 等级（ABCD）
        ttk.Label(info_f, text="等级").grid(row=1, column=0, sticky="w", padx=8, pady=3)
        level_row = ttk.Frame(info_f)
        level_row.grid(row=1, column=1, columnspan=2, sticky="w", padx=4)
        for lv in ("A", "B", "C", "D"):
            ttk.Radiobutton(level_row, text=lv, variable=self.var_level, value=lv,
                            command=self._refresh_preview).pack(side="left", padx=6)

        # 日期
        ttk.Label(info_f, text="日期").grid(row=2, column=0, sticky="w", padx=8, pady=3)
        self.var_date = tk.StringVar(value=self.date_str)
        ttk.Entry(info_f, textvariable=self.var_date, width=14).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(info_f, text="格式 YYYYMMDD").grid(row=2, column=2, sticky="w", padx=8)

        # 用户名称
        ttk.Label(info_f, text="用户名称").grid(row=3, column=0, sticky="w", padx=8, pady=3)
        ttk.Entry(info_f, textvariable=self.var_user, width=14).grid(row=3, column=1, sticky="w", padx=4)

        # 集数文件夹命名
        ttk.Label(info_f, text="集数文件夹命名").grid(row=4, column=0, sticky="w", padx=8, pady=3)
        epname_row = ttk.Frame(info_f)
        epname_row.grid(row=4, column=1, columnspan=2, sticky="w", padx=4)
        ttk.Radiobutton(epname_row, text="纯数字", variable=self.var_ep_naming, value="num",
                        command=self._refresh_preview).pack(side="left", padx=6)
        ttk.Radiobutton(epname_row, text="项目名+数字", variable=self.var_ep_naming, value="name_num",
                        command=self._refresh_preview).pack(side="left", padx=6)
        ttk.Radiobutton(epname_row, text="项目名+等级+数字", variable=self.var_ep_naming, value="name_level_num",
                        command=self._refresh_preview).pack(side="left", padx=6)

        # 集数位置
        ttk.Label(f, text="集数位置").grid(row=7, column=0, sticky="w", pady=2)
        self.var_placement = tk.StringVar(value="项目根")
        ttk.Radiobutton(f, text="项目根（1/ 2/ ...）", variable=self.var_placement,
                        value="项目根", command=self._refresh_preview).grid(row=7, column=1, sticky="w", padx=4)
        ttk.Radiobutton(f, text="Project 子目录", variable=self.var_placement,
                        value="Project子目录", command=self._refresh_preview).grid(row=7, column=2, sticky="w")

        # ptx 处理
        ttk.Label(f, text="模板 ptx").grid(row=8, column=0, sticky="w", pady=2)
        self.var_ptx = tk.StringVar(value="原样复制")
        ttk.Radiobutton(f, text="原样复制", variable=self.var_ptx, value="原样复制",
                        command=self._refresh_preview).grid(row=8, column=1, sticky="w", padx=4)
        ttk.Radiobutton(f, text="重命名(项目名+集数)", variable=self.var_ptx, value="重命名",
                        command=self._refresh_preview).grid(row=8, column=2, sticky="w")
        ttk.Radiobutton(f, text="不复制(只建空文件夹)", variable=self.var_ptx, value="none",
                        command=self._refresh_preview).grid(row=9, column=1, sticky="w", padx=4)

        # 跳过已存在
        self.var_skip = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="已存在项跳过(不覆盖)", variable=self.var_skip).grid(row=9, column=2, sticky="w")

        # 预览
        ttk.Label(f, text="预览（将建立的目录结构）").grid(row=10, column=0, sticky="w", pady=(8, 2))
        self.preview = scrolledtext.ScrolledText(f, height=13, width=90, state="disabled")
        self.preview.grid(row=11, column=0, columnspan=3, sticky="ew", pady=2)

        # 按钮
        btn = ttk.Frame(f)
        btn.grid(row=12, column=0, columnspan=3, sticky="e", pady=(6, 0))
        ttk.Button(btn, text="刷新预览", command=self._refresh_preview).pack(side="right", padx=4)
        ttk.Button(btn, text="建立文件夹", command=self._on_build).pack(side="right", padx=4)

        # 日志
        ttk.Label(f, text="日志").grid(row=13, column=0, sticky="w", pady=(8, 2))
        self.log = scrolledtext.ScrolledText(f, height=6, width=90, state="disabled")
        self.log.grid(row=14, column=0, columnspan=3, sticky="ew")

        f.columnconfigure(1, weight=1)

        # 绑定实时预览
        for v in (self.var_eps, self.var_name, self.var_output, self.var_template,
                  self.var_seq, self.var_level, self.var_date, self.var_user,
                  self.var_ep_naming):
            v.trace_add("write", lambda *a: self._refresh_preview())
        self._refresh_preview()

    # ----- 交互 -----
    def _pick_template(self):
        p = filedialog.askdirectory(initialdir=self.var_template.get())
        if p:
            self.var_template.set(p)
            self._refresh_preview()

    def _pick_output(self):
        p = filedialog.askdirectory(initialdir=self.var_output.get())
        if p:
            self.var_output.set(p)
            # 切换输出目录时按新目录自动顺延序号（可手动覆盖）
            self.var_seq.set(str(detect_next_seq(p)))
            self._refresh_preview()

    def _center_on_screen(self, w, h):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = (sw - w) // 2, (sh - h) // 2
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _compute(self):
        eps, errs = parse_episodes(self.var_eps.get())
        project_root, steps, warns, ep_names = plan_creation(
            eps, self.var_name.get(), self.var_seq.get(), self.var_level.get(),
            self.var_date.get(), self.var_user.get(),
            self.var_output.get(), self.var_template.get(),
            self.var_placement.get(), self.var_ptx.get(), self.var_ep_naming.get())
        return eps, errs, project_root, steps, warns, ep_names

    def _refresh_preview(self):
        try:
            eps, errs, project_root, steps, warns, ep_names = self._compute()
        except Exception as e:
            self._set_preview("[规划出错] %s" % e)
            return
        # 更新规则示例
        self.var_example.set("示例: %s" % os.path.basename(project_root))
        lines = []
        lines.append("项目根: %s" % project_root)
        if errs:
            lines.append("⚠ 集数解析警告: %s" % "; ".join(errs))
        if warns:
            for w in warns:
                lines.append("⚠ %s" % w)
        if not eps:
            lines.append("(无有效集数，仅建立分类目录)")
        lines.append("")
        # 以树形展示：先分类目录，再集数
        cat_lines, ep_lines = [], []
        ep_set = set(ep_names)
        for action, path in steps:
            rel = os.path.relpath(path, project_root)
            base = os.path.basename(rel)
            parent_base = os.path.basename(os.path.dirname(rel))
            if base in ep_set or parent_base in ep_set:
                ep_lines.append("  %s" % rel)
            else:
                cat_lines.append("  %s" % rel)
        if cat_lines:
            lines.append("[分类目录]")
            lines.extend(cat_lines)
        if ep_lines:
            lines.append("[集数文件夹] (%d 集)" % len(eps))
            lines.extend(ep_lines)
        lines.append("")
        lines.append("合计将建立: %d 项（目录 %d + 复制 %d）" % (
            len(steps),
            sum(1 for a, _ in steps if a == "mkdir"),
            sum(1 for a, _ in steps if a == "copy")))
        self._set_preview("\n".join(lines))

    def _set_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_build(self):
        try:
            eps, errs, project_root, steps, warns = self._compute()
        except Exception as e:
            messagebox.showerror("规划失败", str(e))
            return
        if not steps:
            messagebox.showwarning("无可建立项", "请检查集数/模板路径")
            return
        # 确认
        n = len(steps)
        if not messagebox.askokcancel("确认建立",
                                      "将在以下位置建立 %d 个目录/文件：\n%s\n\n是否继续？" % (n, project_root)):
            return
        skip = self.var_skip.get()
        self._log("=== 开始建立: %s ===" % project_root)
        for w in warns:
            self._log("⚠ %s" % w)
        if errs:
            self._log("⚠ 集数解析: %s" % "; ".join(errs))

        # 在后台线程执行，避免大批量时界面卡死
        def worker():
            created = skipped = failed = 0
            try:
                os.makedirs(project_root, exist_ok=True)
                # 先建分类目录
                src_ptx = locate_template_ptx(self.var_template.get()) if self.var_ptx.get() != "none" else None
                for action, path in steps:
                    try:
                        if action == "mkdir":
                            if os.path.isdir(path):
                                skipped += 1
                                continue
                            os.makedirs(path, exist_ok=True)
                            created += 1
                            self._log("建目录: %s" % path)
                        elif action == "copy":
                            if os.path.exists(path):
                                if skip:
                                    skipped += 1
                                    continue
                                os.remove(path)
                            if src_ptx and os.path.exists(src_ptx):
                                shutil.copy2(src_ptx, path)
                                created += 1
                                self._log("复制: %s" % path)
                            else:
                                skipped += 1
                    except Exception as e:
                        failed += 1
                        self._log("失败: %s -> %s" % (path, e))
                self._log("=== 完成: 新建 %d / 跳过 %d / 失败 %d ===" % (created, skipped, failed))
                if failed == 0:
                    try:
                        os.startfile(project_root)
                    except Exception:
                        pass
            except Exception:
                self._log(traceback.format_exc())
        threading.Thread(target=worker, daemon=True).start()


def main():
    try:
        App().mainloop()
    except Exception:
        traceback.print_exc()
        messagebox.showerror("启动失败", traceback.format_exc())


if __name__ == "__main__":
    main()
