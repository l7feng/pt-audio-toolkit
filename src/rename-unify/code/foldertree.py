# -*- coding: utf-8 -*-
"""工程文件夹建树核心（foldertree）—— 原 pt-project-folder-builder 迁入

2026-09-27 · D 档 F7+R2 合并（甲案）：folder-builder 整体并入 rename-unify，
作为第 5 页签「5 · 工程文件夹」。本模块是**纯逻辑层**（零 tkinter），
GUI 只负责收集参数 → 调 plan_creation / apply_plan → 展示计划。
（沿用 rename-unify「壳不动芯」原则：逻辑可独立跑测试。）

为什么要合并：三套命名字段链本就同构（Q4 判定）——
rename-unify 的 片名/集数/日期/版本/用户、folder-builder 的 项目名/等级/日期/用户、
剪映的 视频名解析。合并后共用一条字段捕获链，不再各填一遍、各解析一遍。

铁律（沿用 rename-unify）：**不补零、已合规不动**。
铁律（沿用 folder-builder）：copy 步骤**必须先确认源可复制再动目标**——
早期写成「先 os.remove 旧文件 → 再判断源是否存在」，模板 .ptx 一旦在规划后
被移走/改名，就会删掉旧文件却不复制回来（不可逆数据丢失）。2026-09-23 修复。

F5（2026-09-27）：删「项目根」选项 —— 集数文件夹固定建在 Project 子目录下
（`ep_placement` 参数保留仅为兼容旧调用，UI 不再暴露）。
"""
import os
import re
import shutil

#: 集数文件夹位置。F5 之后唯一取值（保留常量便于测试与兼容）。
EP_PLACEMENT_DEFAULT = "Project子目录"

#: 集数文件夹命名模式
EP_NAMING_MODES = (
    ("num", "纯数字（1 / 2）"),
    ("name_num", "项目名+数字（睡父亲1）"),
    ("name_level_num", "项目名+等级+数字（睡父亲D1）"),
)

#: 模板 ptx 处理方式
PTX_MODES = (
    ("原样复制", "原样复制"),
    ("重命名", "重命名（项目名+集数）"),
    ("none", "不复制（只建空文件夹）"),
)


# ---------------------------------------------------------------------------
# 命名拼装
# ---------------------------------------------------------------------------

def build_project_name(seq, name, level, date_str, username):
    """按规则拼出项目根目录名：{序号}-{项目名}{等级}_{日期}_{用户名}

    等级直接拼在项目名之后（如 测试D），无分隔符。
    序号为空时退化为「项目名等级_日期_用户名」（不写前导连字符）。
    """
    body = "%s%s_%s_%s" % ((name or "").strip(), (level or ""), date_str, username)
    seq = (seq or "").strip()
    return ("%s-%s" % (seq, body)) if seq else body


def build_episode_name(name, level, ep, mode="name_num"):
    """集数文件夹名（与项目根命名拆开，可独立配置）。"""
    nm = (name or "").strip()
    if mode == "num":
        return str(ep)
    if mode == "name_level_num":
        return "%s%s%d" % (nm, (level or ""), ep)
    return "%s%d" % (nm, ep)          # name_num（默认）


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
    """F6：解析「序号-项目名{等级}_YYYYMMDD_用户名」形态的项目根名。

    根文件夹是信息最全的命名源（用户反馈定案）：
      ``15-测试D_20260925_7F`` → name=测试, level=D, date=20260925, user=7F
    等级是结尾的单字母 A/B/C/D 时拆出，否则整体算项目名。解析失败返回 None。
    """
    m = re.match(r"^\d+-(.+)_(\d{8})_(.+)$", (dirname or "").strip())
    if not m:
        return None
    body, date_str, user = m.group(1).strip(), m.group(2), m.group(3).strip()
    if len(body) > 1 and body[-1] in "ABCD":
        return {"name": body[:-1], "level": body[-1],
                "date": date_str, "user": user}
    return {"name": body, "level": "", "date": date_str, "user": user}


def infer_fields_from_output(output_root):
    """F6：从输出根下「序号最大」的项目根文件夹提取命名字段。

    返回 dict（name/level/date/user）或 None。与 rename-unify 的字段捕获链
    同源思路：**源名捕获 > 目录推断**，这里取「目录推断」的一条。
    """
    if not output_root or not os.path.isdir(output_root):
        return None
    best = None                      # (seq, dirname)
    try:
        entries = os.listdir(output_root)
    except OSError:
        return None
    for n in entries:
        if not os.path.isdir(os.path.join(output_root, n)):
            continue
        m = re.match(r"^(\d+)", n)
        seq = int(m.group(1)) if m else -1
        if best is None or seq > best[0]:
            best = (seq, n)
    if not best:
        return None
    return parse_project_root_name(best[1])


# ---------------------------------------------------------------------------
# 输入解析
# ---------------------------------------------------------------------------

def parse_episodes(text):
    """解析 "1-10, 23, 38, 46-49" -> ([1,2,...,10,23,38,46,47,48,49], errors)

    支持逗号分隔、连字符区间（允许两侧空格）、自动去重、升序。
    非法片段忽略并进 errors（不抛异常——UI 直接展示即可）。
    """
    episodes, errors = [], []
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
    """在模板的「Project模板」下找到第一个 .ptx 作为复制源（找不到返回 None）。"""
    project_tpl = os.path.join(template_root, "Project模板")
    if not os.path.isdir(project_tpl):
        project_tpl = template_root          # 兼容：模板根直接含分集文件夹
    for root, _dirs, files in os.walk(project_tpl):
        for f in files:
            if f.lower().endswith(".ptx"):
                return os.path.join(root, f)
    return None


def _walk_rel(src):
    """返回 src 下相对目录路径列表（用于 mkdir 规划）。"""
    rels = []
    for root, dirs, _files in os.walk(src):
        for d in dirs:
            rels.append(os.path.relpath(os.path.join(root, d), src))
    return sorted(rels)


# ---------------------------------------------------------------------------
# 预检与规划（都不写盘）
# ---------------------------------------------------------------------------

def precheck_build(template_root, output_root, project_root, ptx_mode):
    """F1（v1.1.0）建立前预检：模板存在性/可读性/输出盘可写，**一次列全**。

    旧行为是「边建边报错」（模板缺失要到复制那步才炸、输出盘只读要等建目录失败
    才知道）。返回问题列表（空＝全部通过）；纯可读性探测，不写任何业务文件。
    """
    problems = []
    if not os.path.isdir(template_root):
        problems.append("模板路径不存在: %s" % template_root)
        return problems                       # 后面都围绕它，没有继续的意义

    if not os.path.isdir(os.path.join(template_root, "文件夹模板")):
        problems.append("模板缺少「文件夹模板」子目录（将只建集数文件夹）: %s"
                        % os.path.join(template_root, "文件夹模板"))

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

    probe_dir = project_root if os.path.isdir(project_root) else output_root
    if not os.path.isdir(probe_dir):
        try:
            os.makedirs(probe_dir, exist_ok=True)
        except OSError as e:
            problems.append("输出目录不可创建: %s (%s)" % (probe_dir, e))
            return problems
    probe = os.path.join(probe_dir, "~ft_precheck_%d.tmp" % (os.getpid() % 100000))
    try:
        with open(probe, "w") as fh:
            fh.write("precheck")
        os.remove(probe)
    except OSError as e:
        problems.append("输出盘不可写: %s (%s)" % (probe_dir, e))
    return problems


def plan_creation(episodes, name, seq, level, date_str, username,
                  output_root, template_root, ptx_mode="原样复制",
                  ep_naming="name_num", ep_placement=EP_PLACEMENT_DEFAULT):
    """返回 (project_root, steps, warnings, ep_names)。

    steps = [(action, path), ...]，action ∈ {"mkdir", "copy"}。
    **不实际写入磁盘**，只规划——预览与执行共用同一份计划。
    """
    warnings = []
    proj_dir_name = build_project_name(seq, name, level, date_str, username)
    project_root = os.path.join(output_root, proj_dir_name)

    if os.path.exists(project_root):
        warnings.append("项目根已存在，将在其内增量建立（已存在项跳过）: %s"
                        % project_root)

    steps = []

    # 1) 分类目录模板合并到项目根
    folder_tpl = os.path.join(template_root, "文件夹模板")
    if os.path.isdir(folder_tpl):
        for item in sorted(os.listdir(folder_tpl)):
            src = os.path.join(folder_tpl, item)
            dst = os.path.join(project_root, item)
            if os.path.isdir(src):
                steps.append(("mkdir", dst))
                for sub in _walk_rel(src):
                    steps.append(("mkdir", os.path.join(dst, sub)))
            else:
                steps.append(("copy", dst))
    else:
        warnings.append("未找到 文件夹模板 子目录: %s" % folder_tpl)

    # 2) 集数文件夹（F5：固定 Project 子目录）
    src_ptx = locate_template_ptx(template_root) if ptx_mode != "none" else None
    if ptx_mode != "none" and src_ptx is None:
        warnings.append("模板中未找到可复制的 .ptx 文件，将改为只建空文件夹")

    ep_names = [build_episode_name(name, level, ep, ep_naming) for ep in episodes]
    for ep_name in ep_names:
        if ep_placement == EP_PLACEMENT_DEFAULT:
            ep_dir = os.path.join(project_root, "Project", ep_name)
        else:
            ep_dir = os.path.join(project_root, ep_name)
        steps.append(("mkdir", ep_dir))
        if ptx_mode != "none" and src_ptx is not None:
            dst_name = ("%s.ptx" % ep_name) if ptx_mode == "重命名" \
                else os.path.basename(src_ptx)
            steps.append(("copy", os.path.join(ep_dir, dst_name)))

    return project_root, steps, warnings, ep_names


def plan_tree_text(project_root, steps, ep_names):
    """把计划渲染成树形文本（预览用，不写盘）。"""
    lines = []
    ep_set = set(ep_names)
    cat, eps = [], []
    seen = set()
    for _action, path in steps:
        try:
            rel = os.path.relpath(path, project_root)
        except ValueError:
            rel = path
        top = rel.split(os.sep)[0]
        if top in ep_set or rel.startswith(os.path.join("Project", "")):
            eps.append(rel)
        elif top not in seen:
            seen.add(top)
            cat.append(top)
    if cat:
        lines.append("分类目录（来自 文件夹模板）:")
        for c in cat:
            lines.append("  ├── %s" % c)
    if eps:
        lines.append("集数文件夹（Project 子目录）:")
        for e in eps[:40]:
            lines.append("  ├── %s" % e)
        if len(eps) > 40:
            lines.append("  ... 其余 %d 项省略" % (len(eps) - 40))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

def apply_plan(project_root, steps, src_ptx=None, skip_existing=True, log=None):
    """执行建立计划，返回 (created, skipped, failed)。

    ⚠️ copy 分支铁律：**先确认源可复制再动目标**（见模块 docstring）。
    log 为可选回调（str -> None），用于把进度打到 GUI 日志框。
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    created = skipped = failed = 0
    try:
        os.makedirs(project_root, exist_ok=True)
    except OSError as e:
        _log("项目根建立失败: %s -> %s" % (project_root, e))
        return 0, 0, 1

    for action, path in steps:
        try:
            if action == "mkdir":
                if os.path.isdir(path):
                    skipped += 1
                    continue
                os.makedirs(path, exist_ok=True)
                created += 1
                _log("建目录: %s" % path)
            elif action == "copy":
                # 先确认源可复制，再动目标（不可逆丢失防线）
                if not (src_ptx and os.path.exists(src_ptx)):
                    skipped += 1
                    continue
                if os.path.exists(path):
                    if skip_existing:
                        skipped += 1
                        continue
                    os.remove(path)
                shutil.copy2(src_ptx, path)
                created += 1
                _log("复制: %s" % path)
        except Exception as e:
            failed += 1
            _log("失败: %s -> %s" % (path, e))
    return created, skipped, failed
