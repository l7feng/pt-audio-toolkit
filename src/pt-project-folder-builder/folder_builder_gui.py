# -*- coding: utf-8 -*-
"""
PT 工程文件夹生成器 (pt-project-folder-builder)
=================================================
根据 D:/DAW-Project/00文件夹模板 批量建立剧集工程文件夹。

GUI 输入：
  1. 集数      如 "1-10, 23, 38, 46-49"（支持逗号分隔 + 连字符区间，自动去重排序）
  2. 项目名称   如 "测试"（对应命名里的「项目名」）
  3. 输出路径   新项目根将建在此路径下
  4. 模板路径   默认 D:/DAW-Project/00文件夹模板（可改）

命名 = 规则 + 信息 两部分拆开：
  - 规则（结构，固定默认）:  {序号} - {项目名}{等级} _ {日期} _ {用户名}
  - 信息（均可更改）:         序号(自动顺延) / 项目名 / 等级(ABCD) / 日期 / 用户名称
  默认示例:  10-测试D_20260920_7F
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
# 版本与构建日期
# ---------------------------------------------------------------------------
# 四工具统一口径：版本号 X.Y.Z（不带 v 前缀），标题写 vX.Y.Z (YYYY-MM-DD)。
# ⚠️ build_date() 在 pt-tools / jianying-draft-toolkit / rename-unify 各有一份
#    逐字相同的实现（各工具独立打包、无共享模块），改动时四处需同步。
# v1.0.1（2026-09-24 · GUI 美化）：单页平铺 grid 重排为 6 区块 LabelFrame
#   （路径 / 本批内容 / 命名规则 / 命名信息 / 选项 / 预览 / 日志），主按钮
#   「建立文件夹」固定最右；控件与逻辑不变，纯布局调整。
APP_VERSION = "1.2.0"  # F2 按钮区固定 / F3 默认名「测试」/ F6 根名提取（v1.2.0）


def build_date():
    """构建日期：frozen 取 exe 文件时间（打包时刻），源码模式取本文件时间。

    目标：标题栏一眼识别新旧。
    ⚠️ sys.executable 是 str，必须先 Path() 包一层再 .stat()（曾写成 src.stat()
       直接调用 → AttributeError 被 except 吞掉 → 标题恒显示「未知」）。
    """
    try:
        import datetime as _dt
        from pathlib import Path
        src = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
        return _dt.datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d")
    except Exception:
        return "未知"


def app_dir():
    """可写目录：frozen 取 exe 旁，源码模式取本文件目录（日志落点）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def setup_logging():
    """初始化滚动日志到 app_dir()/pt-project-folder-builder.log（W2 骨架）。

    返回 logger；失败静默返回 None（日志绝不影响主流程）。
    """
    try:
        import logging
        from logging.handlers import RotatingFileHandler
        os.makedirs(app_dir(), exist_ok=True)
        path = os.path.join(app_dir(), "pt-project-folder-builder.log")
        logger = logging.getLogger("pt-project-folder-builder")
        if not logger.handlers:
            handler = RotatingFileHandler(path, maxBytes=1_000_000,
                                          backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.info("=== pt-project-folder-builder v%s (%s) 启动 ===",
                        APP_VERSION, build_date())
        return logger
    except Exception:
        return None

# ---------------------------------------------------------------------------
# 命名：规则与信息（与 GUI 解耦，便于无界面测试）
# ---------------------------------------------------------------------------

# 命名规则（结构，默认固定）。序号不再作为独立前缀开关，而是模板中的一个占位符。
NAMING_RULE = "{序号}-{项目名}{等级}_{日期}_{用户名}"


def build_project_name(seq, name, level, date_str, username):
    """按规则拼出项目根目录名。

    信息字段：seq(序号) / name(项目名) / level(等级) / date_str(日期) / username(用户名称)。
    - 等级直接拼在项目名之后（如 测试D），无分隔符。
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


def parse_project_root_name(dirname):
    """F6（v2.6.5）：解析「序号-项目名{等级}_YYYYMMDD_用户名」形态的项目根名。

    根文件夹是信息最全的命名源（用户反馈定案），形态示例：
      15-测试D_20260925_7F  →  name=测试, level=D, date=20260925, user=7F
    等级是结尾的单字母 A/B/C/D 时拆出，否则整体算项目名。
    解析失败（形态不符）返回 None。
    """
    m = re.match(r"^\d+-(.+)_(\d{8})_(.+)$", (dirname or "").strip())
    if not m:
        return None
    body, date_str, user = m.group(1).strip(), m.group(2), m.group(3).strip()
    if len(body) > 1 and body[-1] in "ABCD":
        return {"name": body[:-1], "level": body[-1],
                "date": date_str, "user": user}
    return {"name": body, "level": "", "date": date_str, "user": user}


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


def precheck_build(template_root, output_root, project_root, steps, ptx_mode):
    """F1（v1.1.0）：建立前预检 —— 模板存在性 / 可读性 / 输出盘可写，一次列全。

    旧行为是"边建边报错"：模板缺失要到复制那一步才炸、输出盘只读要等
    建目录失败才知道。现在确认框之前把问题一次列全，让用户先修再点。
    返回问题列表（空 = 全部通过；纯可读性探测，不写任何业务文件）。
    """
    problems = []

    # 1) 模板根
    if not os.path.isdir(template_root):
        problems.append("模板路径不存在: %s" % template_root)
        return problems                      # 后面全是围绕它的，没有继续的意义

    # 2) 分类目录模板
    if not os.path.isdir(os.path.join(template_root, "文件夹模板")):
        problems.append("模板缺少「文件夹模板」子目录（将只建集数文件夹）: %s"
                        % os.path.join(template_root, "文件夹模板"))

    # 3) .ptx 模板（ptx_mode != none 时必须可读，且不能被 PT 独占锁死）
    if ptx_mode != "none":
        src_ptx = locate_template_ptx(template_root)
        if src_ptx is None:
            problems.append("模板中未找到可复制的 .ptx 文件（ptx 选项≠不复制）")
        else:
            try:
                with open(src_ptx, "rb"):
                    pass
            except OSError as e:
                problems.append(".ptx 模板不可读: %s (%s)" % (src_ptx, e))
            try:
                # r+b 只在文件被独占锁（如 PT 正开着它）时失败，不改内容
                with open(src_ptx, "r+b"):
                    pass
            except OSError as e:
                problems.append(".ptx 模板疑似被占用（PT 开着它？）: %s (%s)"
                                % (src_ptx, e))

    # 4) 输出位置：已存在项目根 → 至少要可写；不存在 → 试建/试删同目录探针文件
    probe_dir = project_root if os.path.isdir(project_root) else output_root
    if not os.path.isdir(probe_dir):
        try:
            os.makedirs(probe_dir, exist_ok=True)
        except OSError as e:
            problems.append("输出目录不可创建: %s (%s)" % (probe_dir, e))
            return problems
    probe = os.path.join(probe_dir, "~fb_precheck_%d.tmp"
                         % (os.getpid() % 100000))
    try:
        with open(probe, "w") as fh:
            fh.write("precheck")
        os.remove(probe)
    except OSError as e:
        problems.append("输出盘不可写: %s (%s)" % (probe_dir, e))
    return problems


def plan_creation(episodes, name, seq, level, date_str, username,
                 output_root, template_root, ep_placement, ptx_mode, ep_naming):
    """返回 (project_root, [(action, path), ...], warnings, ep_names)

    action ∈ {"mkdir", "copy"}；path 为将要创建/复制的目标路径。
    不实际写入磁盘，只规划。
    注意：本函数与 _compute() 均返回 4 / 6 元组，调用处解包个数必须一致。
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
        self.title("PT 工程文件夹生成器 v%s (%s)" % (APP_VERSION, build_date()))
        self._center_on_screen(860, 860)
        self.minsize(800, 620)   # F2（v2.6.5）：低于此高度按钮区可能被裁
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
    # v1.0.1（2026-09-24 · GUI 美化）：旧版全部控件挤在一个平铺 grid 里
    # （路径 / 集数 / 选项 / 预览 / 日志混排，row 0-14 一路排下来），视觉上
    # 分不清哪几行是一组的。现按功能分成 6 个区块，自上而下即操作顺序：
    # 路径 → 本批内容 → 命名规则 → 命名信息 → 选项 → 预览 → 按钮 → 日志。
    # 控件与变量名全部不变，只动布局。
    def _build_widgets(self):
        f = ttk.Frame(self, padding=4)
        f.pack(fill="both", expand=True)

        # ====== ① 路径 ======
        path_f = ttk.LabelFrame(f, text=" 路径 ", padding=8)
        path_f.pack(fill="x", pady=(0, 6))
        path_f.columnconfigure(1, weight=1)
        ttk.Label(path_f, text="模板路径").grid(row=0, column=0, sticky="w", pady=3)
        self.var_template = tk.StringVar(value=self.template_default)
        ttk.Entry(path_f, textvariable=self.var_template).grid(
            row=0, column=1, sticky="ew", padx=6)
        ttk.Button(path_f, text="浏览", width=8,
                   command=self._pick_template).grid(row=0, column=2)
        ttk.Label(path_f, text="输出路径").grid(row=1, column=0, sticky="w", pady=3)
        self.var_output = tk.StringVar(value=self.output_default)
        ttk.Entry(path_f, textvariable=self.var_output).grid(
            row=1, column=1, sticky="ew", padx=6)
        ttk.Button(path_f, text="浏览", width=8,
                   command=self._pick_output).grid(row=1, column=2)

        # ====== ② 本批内容 ======
        batch_f = ttk.LabelFrame(f, text=" 本批内容 ", padding=8)
        batch_f.pack(fill="x", pady=(0, 6))
        batch_f.columnconfigure(1, weight=1)
        ttk.Label(batch_f, text="项目名称").grid(row=0, column=0, sticky="w", pady=3)
        # F3（v2.6.5）：出厂默认改「测试」——不携带个人项目信息
        self.var_name = tk.StringVar(value="测试")
        ttk.Entry(batch_f, textvariable=self.var_name).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=6)
        # F6（v2.6.5）：一键从输出根最新的「数字前缀项目根」提取项目名/等级
        ttk.Button(batch_f, text="从上次项目提取", width=14,
                   command=self._infer_name_from_root).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(batch_f, text="集数").grid(row=1, column=0, sticky="nw", pady=3)
        self.var_eps = tk.StringVar(value="1-10, 23, 38, 46-49")
        ttk.Entry(batch_f, textvariable=self.var_eps).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=6)
        ttk.Label(batch_f, text="支持 逗号分隔 + 连字符区间，如 1-10, 23, 38, 46-49",
                  foreground="#888").grid(row=2, column=1, sticky="w", padx=6)

        # ====== ③ 命名规则（结构，固定默认）======
        rule_f = ttk.LabelFrame(f, text=" 命名规则（结构，默认固定） ", padding=6)
        rule_f.pack(fill="x", pady=(0, 6))
        ttk.Label(rule_f, text="结构:  {序号} - {项目名}{等级} _ {日期} _ {用户名}").pack(
            anchor="w", padx=4)
        ttk.Label(rule_f, text="集数文件夹默认: 项目名+数字（如 睡父亲1）；可在下方「命名信息」切换",
                  foreground="#666").pack(anchor="w", padx=4)
        self.var_example = tk.StringVar(value="")
        ttk.Label(rule_f, textvariable=self.var_example,
                  foreground="#2a7").pack(anchor="w", padx=4, pady=(2, 0))

        # ====== ④ 命名信息（均可更改）======
        info_f = ttk.LabelFrame(f, text=" 命名信息（均可更改） ", padding=8)
        info_f.pack(fill="x", pady=(0, 6))
        info_f.columnconfigure(1, weight=1)

        # 序号
        ttk.Label(info_f, text="序号").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(info_f, textvariable=self.var_seq, width=10).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(info_f, text="自动顺延（扫描输出目录下最大数字前缀 +1），可手动改",
                  foreground="#888").grid(row=0, column=2, sticky="w", padx=8)

        # 等级（ABCD）
        ttk.Label(info_f, text="等级").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        level_row = ttk.Frame(info_f)
        level_row.grid(row=1, column=1, columnspan=2, sticky="w", padx=4)
        for lv in ("A", "B", "C", "D"):
            ttk.Radiobutton(level_row, text=lv, variable=self.var_level, value=lv,
                            command=self._refresh_preview).pack(side="left", padx=6)

        # 日期
        ttk.Label(info_f, text="日期").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        self.var_date = tk.StringVar(value=self.date_str)
        ttk.Entry(info_f, textvariable=self.var_date, width=14).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(info_f, text="格式 YYYYMMDD", foreground="#888").grid(row=2, column=2, sticky="w", padx=8)

        # 用户名称
        ttk.Label(info_f, text="用户名称").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(info_f, textvariable=self.var_user, width=14).grid(row=3, column=1, sticky="w", padx=4)

        # 集数文件夹命名
        ttk.Label(info_f, text="集数文件夹命名").grid(row=4, column=0, sticky="w", padx=4, pady=3)
        epname_row = ttk.Frame(info_f)
        epname_row.grid(row=4, column=1, columnspan=2, sticky="w", padx=4)
        ttk.Radiobutton(epname_row, text="纯数字", variable=self.var_ep_naming, value="num",
                        command=self._refresh_preview).pack(side="left", padx=6)
        ttk.Radiobutton(epname_row, text="项目名+数字", variable=self.var_ep_naming, value="name_num",
                        command=self._refresh_preview).pack(side="left", padx=6)
        ttk.Radiobutton(epname_row, text="项目名+等级+数字", variable=self.var_ep_naming, value="name_level_num",
                        command=self._refresh_preview).pack(side="left", padx=6)

        # ====== ⑤ 选项 ======
        opt_f = ttk.LabelFrame(f, text=" 选项 ", padding=8)
        opt_f.pack(fill="x", pady=(0, 6))
        opt_f.columnconfigure(1, weight=1)

        ttk.Label(opt_f, text="集数位置").grid(row=0, column=0, sticky="w", pady=3)
        place_row = ttk.Frame(opt_f)
        place_row.grid(row=0, column=1, columnspan=2, sticky="w", padx=4)
        self.var_placement = tk.StringVar(value="项目根")
        ttk.Radiobutton(place_row, text="项目根（1/ 2/ ...）", variable=self.var_placement,
                        value="项目根", command=self._refresh_preview).pack(side="left", padx=6)
        ttk.Radiobutton(place_row, text="Project 子目录", variable=self.var_placement,
                        value="Project子目录", command=self._refresh_preview).pack(side="left", padx=6)

        ttk.Label(opt_f, text="模板 ptx").grid(row=1, column=0, sticky="w", pady=3)
        ptx_row = ttk.Frame(opt_f)
        ptx_row.grid(row=1, column=1, columnspan=2, sticky="w", padx=4)
        self.var_ptx = tk.StringVar(value="原样复制")
        ttk.Radiobutton(ptx_row, text="原样复制", variable=self.var_ptx, value="原样复制",
                        command=self._refresh_preview).pack(side="left", padx=6)
        ttk.Radiobutton(ptx_row, text="重命名(项目名+集数)", variable=self.var_ptx, value="重命名",
                        command=self._refresh_preview).pack(side="left", padx=6)
        ttk.Radiobutton(ptx_row, text="不复制(只建空文件夹)", variable=self.var_ptx, value="none",
                        command=self._refresh_preview).pack(side="left", padx=6)
        self.var_skip = tk.BooleanVar(value=True)
        ttk.Checkbutton(ptx_row, text="已存在项跳过(不覆盖)",
                        variable=self.var_skip).pack(side="left", padx=(18, 0))

        # ====== ⑥ 预览 / 按钮 / 日志 ======
        # F2（v2.6.5）：旧顺序「预览(expand) → 按钮 → 日志」在 800×780 默认窗口下，
        # 上方五个固定区块 + 11 行预览已占满窗口，按钮和日志被挤出可视区——
        # 必须放大全屏才能点。现改为「日志、按钮先从底部预留（side=bottom），
        # 预览最后 pack(expand) 吃剩余」：tkinter 空间不足时先压缩最后 pack 的
        # 预览区，按钮永远可见。预览 11→7 行、日志 6→4 行进一步减压。
        log_f = ttk.LabelFrame(f, text=" 日志 ", padding=4)
        log_f.pack(side="bottom", fill="x")
        self.log = scrolledtext.ScrolledText(log_f, height=4, state="disabled",
                                             font=("Consolas", 9))
        self.log.pack(fill="x")

        btn = ttk.Frame(f)
        btn.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(btn, text="建立文件夹", command=self._on_build).pack(side="right", padx=4)
        ttk.Button(btn, text="刷新预览", command=self._refresh_preview).pack(side="right", padx=4)

        prev_f = ttk.LabelFrame(f, text=" 预览（将建立的目录结构） ", padding=4)
        prev_f.pack(fill="both", expand=True, pady=(0, 6))
        self.preview = scrolledtext.ScrolledText(prev_f, height=7, state="disabled",
                                                 font=("Consolas", 9))
        self.preview.pack(fill="both", expand=True)

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

    def _infer_name_from_root(self):
        """F6（v2.6.5）：从输出根下「序号最大」的项目根文件夹提取命名字段。

        背景：项目名称清空时，集名/ptx 只剩集数（build_episode_name 的 name
        段为空串）。用户定案「根文件夹信息最全」——本按钮把项目名/等级一键
        取回并写回输入框（不静默代填、不动日期与用户名：新项目日期应随当天）。
        """
        out_root = self.var_output.get().strip()
        if not out_root or not os.path.isdir(out_root):
            messagebox.showwarning("无法提取", "输出路径不存在：%s" % (out_root or "（空）"))
            return
        best = None                     # (seq, dirname)
        try:
            entries = os.listdir(out_root)
        except OSError as e:
            messagebox.showwarning("无法提取", "输出目录不可读：%s" % e)
            return
        for n in entries:
            if os.path.isdir(os.path.join(out_root, n)):
                m = re.match(r"^(\d+)-", n)
                if m:
                    seq = int(m.group(1))
                    if best is None or seq > best[0]:
                        best = (seq, n)
        if best is None:
            messagebox.showinfo(
                "无法提取",
                "输出目录下没有「数字前缀-」形态的项目文件夹。\n"
                "（期待形态如：15-测试D_20260925_7F）\n"
                "请手动填写项目名称。")
            return
        parsed = parse_project_root_name(best[1])
        if parsed is None:
            messagebox.showwarning(
                "解析失败",
                "「%s」不符合命名规则（序号-项目名{等级}_日期_用户名）。\n"
                "请手动填写项目名称。" % best[1])
            return
        self.var_name.set(parsed["name"])
        if parsed["level"] in ("A", "B", "C", "D"):
            self.var_level.set(parsed["level"])
        self._log("已从「%s」提取：项目名=%s 等级=%s"
                  "（日期/用户名保持当前值，可手动修改）"
                  % (best[1], parsed["name"], parsed["level"] or "（无）"))

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
        if not self.var_name.get().strip():
            # F6（v2.6.5）：项目名为空时集名/ptx 只剩集数，预览里给出醒目引导
            lines.append("⚠ 项目名称为空 —— 集名/ptx 将只有集数。"
                         "可点「从上次项目提取」自动填入，或手动填写。")
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
            eps, errs, project_root, steps, warns, ep_names = self._compute()
        except Exception as e:
            messagebox.showerror("规划失败", str(e))
            return
        if not steps:
            messagebox.showwarning("无可建立项", "请检查集数/模板路径")
            return
        # F1（v1.1.0）：建立前预检 —— 问题一次列全再让确认，不等边建边炸
        try:
            problems = precheck_build(self.var_template.get().strip(),
                                      self.var_output.get().strip(),
                                      project_root, steps, self.var_ptx.get())
        except Exception as e:
            problems = ["预检执行异常（不阻断，可继续）: %s" % e]
        if problems:
            if not messagebox.askokcancel(
                    "预检发现 %d 个问题" % len(problems),
                    "\n".join("· " + p for p in problems)
                    + "\n\n仍要继续建立吗？"):
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
                            # ⚠️ 必须先确认「源可复制」再动目标文件。
                            #    早期写成「先 os.remove 旧文件 → 再判断源是否存在」，
                            #    一旦模板 .ptx 在规划后被移走/改名，就会删掉旧文件却不复制
                            #    回来（不可逆数据丢失）。2026-09-23 调整顺序修复。
                            if not (src_ptx and os.path.exists(src_ptx)):
                                skipped += 1
                                continue
                            if os.path.exists(path):
                                if skip:
                                    skipped += 1
                                    continue
                                os.remove(path)
                            shutil.copy2(src_ptx, path)
                            created += 1
                            self._log("复制: %s" % path)
                    except Exception as e:
                        failed += 1
                        self._log("失败: %s -> %s" % (path, e))
                self._log("=== 完成: 新建 %d / 跳过 %d / 失败 %d ===" % (created, skipped, failed))
                _log = setup_logging()
                if _log is not None:
                    _log.info("建立完成 %s：新建 %d / 跳过 %d / 失败 %d",
                              project_root, created, skipped, failed)
                if failed == 0:
                    try:
                        os.startfile(project_root)
                    except Exception:
                        pass
            except Exception:
                self._log(traceback.format_exc())
        threading.Thread(target=worker, daemon=True).start()


def main():
    _log = setup_logging()
    if _log is not None:
        _log.info("GUI 启动 v%s (%s)", APP_VERSION, build_date())
    try:
        App().mainloop()
    except Exception:
        tb = traceback.format_exc()
        if _log is not None:
            _log.error("启动异常：\n%s", tb)
        traceback.print_exc()
        messagebox.showerror("启动失败", traceback.format_exc())


if __name__ == "__main__":
    main()
