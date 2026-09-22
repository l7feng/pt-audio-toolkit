# -*- coding: utf-8 -*-
"""rename-unify 核心规则引擎（与 GUI 完全解耦，可独立测试）

设计要点
--------
1. 规则 = 模板字符串 + 字段值，不是硬编码分支。
   模板里的 {占位符} 由「字段表」填充，改规则只需改模板。
2. 识别 = 候选模板族 × 正则匹配，逐个试，第一个命中即为归属。
   每条识别规则带自己的 regex，支持多套历史命名风格共存。
3. 计划（plan）与执行（apply）分离：
   - build_plan() 只算不动盘，返回 items + 冲突清单
   - apply_plan() 才真正 rename
   这是「不可逆操作前先预览」的硬保证。
4. 全程零第三方依赖。

本文件只依赖标准库。
"""

import csv
import os
import re
import datetime
from collections import Counter

# ---------------------------------------------------------------------------
# 默认规则（GUI 里可改，改完存 config.json）
# ---------------------------------------------------------------------------

# 交付命名模板：段间空格，类型段内下划线+连字符。
# ⚠️ 模板**不含扩展名**——扩展名由 render 从源文件保留拼接，
#    写进模板会导致「xxx.wav.wav」双扩展名（曾经的 bug）。
DEFAULT_TEMPLATE = "{片名} {集数}集 {日期} {版本} {档位}_{类型}"

# 识别规则族：每行 [目录, regex, 输出类型]
#
# 规则里用 {片名} {集数} {日期} {版本} {档位} 占位符（宽松匹配，兼容历史命名），
# 也可写普通正则。输出类型用 **命名引用** \g<lane> / \g<seq> 引用显式捕获组，
# 不依赖组的位置序号 —— 见 _LOOSE 上方注释。
DEFAULT_RULES = [
    # ---- 总线分轨：四种历史写法 ----
    # 新式带 BUS 后缀：前夫 10集 0920 V01 7F_DX BUS.wav
    ["BUS", r"^{片名}\s*{集数}\s+{日期}\s+{版本}\s+{档位}_(?P<lane>DX|FX|MX)\s+BUS$",
     "BUS-\\g<lane>"],
    # 无 BUS 后缀（裸集数）：前夫1_DX Folder.wav
    ["BUS", r"^{片名}\s*{裸集数}_(?P<lane>DX|FX|MX)\s+Folder$", "BUS-\\g<lane>"],
    # BUS 在前（裸集数）：前夫2_BUS DX Folder.wav
    ["BUS", r"^{片名}\s*{裸集数}_BUS\s+(?P<lane>DX|FX|MX)\s+Folder$", "BUS-\\g<lane>"],
    # 已是统一格式：前夫 01集 0920 V01 7F_BUS-DX.wav
    ["BUS", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{档位}_BUS-(?P<lane>DX|FX|MX)$",
     "BUS-\\g<lane>"],

    # ---- 混音成品 ----
    # 前夫 1集 0920 V01 7F.wav → MIX
    ["MIX", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{档位}$", "MIX"],
    # 前夫 10集 0920 V01 7F_Master.wav → MIX-MASTER
    ["MIX", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{档位}_Master$", "MIX-MASTER"],
    # 已是统一格式
    ["MIX", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{档位}_(?P<lane>MIX|MIX-MASTER)$",
     "\\g<lane>"],

    # ---- 分段素材 ----
    # 前夫 10集 0920 V01 7F_MX 2.wav → STEM-MX-02
    ["Stem", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{档位}_(?P<lane>DX|FX|MX)\s+(?P<seq>\d+)$",
     "STEM-\\g<lane>-\\g<seq>"],
    # 已是统一格式
    ["Stem", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{档位}_STEM-(?P<lane>DX|FX|MX)-(?P<seq>\d+)$",
     "STEM-\\g<lane>-\\g<seq>"],
]

# 默认字段值（模板渲染用，GUI 里可改）
DEFAULT_FIELDS = {
    "片名": "前夫",
    "日期": "0920",
    "版本": "V01",
    "档位": "7F",
}


# ---------------------------------------------------------------------------
# 命名实体清单（可勾选）
# ---------------------------------------------------------------------------
# 用户在页1 勾选「本次要产出哪些交付类型、对哪些集生效」。
# 未勾选的类型在计划阶段即判为 excluded，不动盘 —— 这样「第 1 集只交 BUS、
# 第 4 集只交 STEM」这类按集差异，不需要改模板、不需要挪文件。
#
# 结构：list[dict]
#   type    输出类型（与规则输出列同值，如 BUS-DX / MIX-MASTER / STEM-MX-02）
#   enabled 是否启用
#   eps     生效集数，逗号/空格分隔；留空 = 全部集
#   note    备注（给人看，不参与逻辑）
#
# type 支持两种匹配：
#   - 精确：'BUS-FX'
#   - 通配：'STEM-MX-*'（星号匹配任意后缀）
# 清单里已有精确项时，通配项对同一具体类型不重复生效。
#
# ⚠️ STEM 类型自带**序号**（STEM-DX-01、STEM-MX-02 ...），所以默认项必须带尾随 *，
#    写成 'STEM-DX' 会导致一条都匹配不上（曾经的坑）。
DEFAULT_ENABLED_TYPES = [
    {"type": "BUS-DX", "enabled": True, "eps": "", "note": "对白总线分轨"},
    {"type": "BUS-FX", "enabled": True, "eps": "", "note": "音效总线分轨"},
    {"type": "BUS-MX", "enabled": True, "eps": "", "note": "音乐总线分轨"},
    {"type": "MIX", "enabled": True, "eps": "", "note": "混音成品"},
    {"type": "MIX-MASTER", "enabled": True, "eps": "", "note": "混音终稿"},
    {"type": "STEM-DX-*", "enabled": True, "eps": "", "note": "对白分段素材（序号不限）"},
    {"type": "STEM-FX-*", "enabled": True, "eps": "", "note": "音效分段素材（序号不限）"},
    {"type": "STEM-MX-*", "enabled": True, "eps": "", "note": "音乐分段素材（序号不限）"},
]


def _type_matches(pattern, type_str):
    """清单条目是否覆盖某个具体输出类型。通配符 * 匹配任意后缀（含空）。

    比较**不做大小写折叠**以外的事：两边 strip 后按 casefold 比。
    """
    p = str(pattern or "").strip().casefold()
    t = str(type_str or "").strip().casefold()
    if not p:
        return False
    if "*" not in p:
        return p == t
    head, _, tail = p.partition("*")
    if not t.startswith(head):
        return False
    return t.endswith(tail) if tail else True


def parse_eps(raw):
    """把「1,3-5」这类集数表达式解析成集合。

    支持：逗号/空格/顿号分隔的单项，以及 a-b 区间。
    返回 set[int]；空输入返回空 set（= 不限集数）。
    非法片段忽略。
    """
    out = set()
    s = str(raw or "").replace("，", ",").replace("、", ",").replace(";", ",")
    for chunk in s.replace(",", " ").split():
        c = chunk.strip()
        if not c:
            continue
        if "-" in c:
            a, _, b = c.partition("-")
            if a.strip().isdigit() and b.strip().isdigit():
                lo, hi = int(a), int(b)
                if lo > hi:
                    lo, hi = hi, lo
                out.update(range(lo, hi + 1))
        elif c.isdigit():
            out.add(int(c))
    return out


def enabled_state(enabled_types, type_str, ep_raw):
    """判断某个 (输出类型, 集数) 是否允许命名。

    返回 (allowed: bool, reason: str)。
    reason 仅在 allowed=False 时有意义，用于计划表的「说明」列。
    """
    if not enabled_types:
        # 未配置清单 = 不启用该功能，全部放行（向后兼容旧 config.json）
        return True, ""
    covered = [e for e in enabled_types if _type_matches(e.get("type"), type_str)]
    if not covered:
        return False, "清单未列出该类型"
    # 任一覆盖项被启用且集数放行 → 放行
    for e in covered:
        if not e.get("enabled", True):
            continue
        eps = parse_eps(e.get("eps"))
        if not eps or ep_int(ep_raw) in eps:
            return True, ""
    # 全部被禁用或被集数限制挡住
    if any(not e.get("enabled", True) for e in covered):
        return False, "清单中已取消勾选"
    lo = min((e for e in covered), key=lambda e: str(e.get("eps") or ""))
    return False, "清单限定集数不含 %s 集" % (normalize_ep(ep_raw),)


# ---------------------------------------------------------------------------
# 宽占位符展开：把 {剧名} 这类模糊占位符变成捕获组
# ---------------------------------------------------------------------------

# 用于「识别」时展开 {占位符} 的模式表。
#
# ⚠️ 设计约束（踩过的两个坑，别重犯）：
#   1. 每个占位符的替换串**必须自带完整括号**，_loose_regex 只管直接替换，
#      不再二次加括号 —— 否则 ((...)) 会产生多余嵌套捕获组。
#   2. 捕获组一律用**命名组**。用 \1 \2 位置引用时，任一规则多加一个组
#      就会把全部序号推错（曾经的 bug：BUS-\2 展开成了日期 0920）。
#      命名组让「输出模板」与「组顺序」彻底解耦。
#   3. {剧名} 用非捕获组：它是自由文本，不该占一个组。
_LOOSE = {
    "{片名}": r"(?P<show>.+?)",
    # {集数} 匹配「数字+集」；{裸集数} 只匹配数字（用于 前夫1_DX Folder 这类旧命名）
    "{集数}": r"(?P<ep>\d+)\s*集",
    "{裸集数}": r"(?P<ep>\d+)",
    "{日期}": r"(?P<date>\d{4,8})",
    "{版本}": r"(?P<ver>V\d+)",
    "{档位}": r"(?P<slate>[A-Za-z0-9]{1,8})",
}

# 替换顺序：长的在前，避免 {集数} 抢先匹配掉 {裸集数} 的前缀
_PLACEHOLDERS = ("{片名}", "{裸集数}", "{集数}", "{日期}", "{版本}", "{档位}")


def _loose_regex(pattern, fields):
    r"""把带 {占位符} 的规则展开为可匹配历史命名的正则（不含扩展名）。

    可用占位符：{片名} {集数}（数字+集）{裸集数}（纯数字）
                {日期} {版本} {档位}
    之外可写任意普通正则（如显式的 (?P<lane>DX|FX|MX) 捕获组）。
    输出模板用 \g<名字> 或 \1 引用。注意 \1 对应 {集数} 的 ep 组。
    """
    out = pattern
    for ph in _PLACEHOLDERS:
        if ph in out:
            out = out.replace(ph, _LOOSE[ph])
    return out


def _esc(s):
    return re.escape(s)


# ---------------------------------------------------------------------------
# 集数解析
# ---------------------------------------------------------------------------

def normalize_ep(raw):
    """集数规范化：'9' -> '09'，'10' -> '10'，非数字原样返回。"""
    s = str(raw).strip()
    if s.isdigit():
        return "%02d" % int(s)
    return s


def ep_int(raw):
    """取集数整数值，用于排序；非数字返回 10**9（排最后）。"""
    s = str(raw).strip()
    return int(s) if s.isdigit() else 10 ** 9


# ---------------------------------------------------------------------------
# 单文件：识别 + 生成新名
# ---------------------------------------------------------------------------

class RuleError(Exception):
    pass


def identify(filename, rules, fields):
    """识别一个文件名（不含扩展名）。

    返回 (目录, ep_raw, type_str) 或 None。
    ep_raw 是原始集数字符串（未补零），type_str 已展开（如 BUS-DX）。

    集数取值：优先命名组 ``ep``（{集数} 展开而来）；没有则回退第一个捕获组。
    ⚠️ 不要改成「第一个像数字的捕获组」——日期 0920、序号 01 都是数字，
    会误判（曾经的 bug）。
    """
    for row in rules:
        if len(row) < 3:
            continue
        d, pattern, out = row[0], str(row[1]), str(row[2])
        try:
            rx = re.compile(_loose_regex(pattern, fields) + r"$")
        except re.error:
            continue
        m = rx.match(filename)
        if not m:
            continue
        # 展开输出模板里的 \g<lane> / \1 ...
        try:
            type_str = m.expand(out) if "\\" in out else out
        except (re.error, IndexError):
            continue
        # 集数：命名组 ep → 否则第一个捕获组
        gd = m.groupdict() or {}
        if gd.get("ep"):
            ep = gd["ep"]
        elif m.groups():
            ep = m.group(1) or ""
        else:
            ep = ""
        return d, str(ep), type_str
    return None


def render(template, ep_raw, type_str, fields):
    """按模板渲染新文件名主体（**不含扩展名**）。

    - 序号补零：类型串里形如 -2 的尾部数字补成 -02。
    - 容错：用户若在模板里误写了 .wav，这里剥掉，避免双扩展名。
    """
    type_fixed = re.sub(r"-(\d+)$", lambda m: "-%02d" % int(m.group(1)), type_str)
    ep = normalize_ep(ep_raw)
    vals = dict(fields)
    vals["集数"] = ep
    vals["类型"] = type_fixed
    tpl = (template or "").strip()
    # 剥掉模板末尾可能误写的扩展名
    m = re.search(r"\.(wav|aif|aiff|mp3|flac|w64)$", tpl, re.I)
    if m:
        tpl = tpl[:m.start()]
    try:
        return tpl.format(**vals)
    except KeyError as e:
        raise RuleError("模板里有未知占位符: %s（可用: 片名/集数/日期/版本/档位/类型）" % e)
    except (IndexError, ValueError) as e:
        raise RuleError("模板格式错误: %s" % e)


def build_item(path, template, rules, fields):
    """对单个文件算出 (新路径, 类型, 集数)。识别不了返回 None。

    扩展名一律**沿用源文件**，不用模板里的。
    """
    folder, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    hit = identify(stem, rules, fields)
    if hit is None:
        return None
    _d, ep, type_str = hit
    new_stem = render(template, ep, type_str, fields)
    # 双保险：万一模板仍带扩展名，剥掉后再拼源扩展名
    if new_stem.lower().endswith(ext.lower()) and ext:
        new_stem = new_stem[: -len(ext)]
    return os.path.join(folder, new_stem + ext), type_str, ep


# ---------------------------------------------------------------------------
# 目录扫描 + 计划
# ---------------------------------------------------------------------------

def scan_dir(root, recursive=True, exts=(".wav", ".aif", ".aiff", ".mp3", ".flac", ".w64")):
    """列出待处理文件（相对 root 的路径）。隐藏文件跳过。"""
    out = []
    if not os.path.isdir(root):
        return out
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                if exts and os.path.splitext(fn)[1].lower() not in exts:
                    continue
                out.append(os.path.join(dirpath, fn))
    else:
        for fn in os.listdir(root):
            p = os.path.join(root, fn)
            if os.path.isfile(p) and not fn.startswith("."):
                if exts and os.path.splitext(fn)[1].lower() not in exts:
                    continue
                out.append(p)
    return sorted(out)


class PlanItem(object):
    __slots__ = ("src", "dst", "type_str", "ep", "status", "note")

    def __init__(self, src, dst, type_str="", ep="", status="", note=""):
        self.src = src
        self.dst = dst
        self.type_str = type_str
        self.ep = ep
        self.status = status          # rename / skip / error / conflict / excluded
        self.note = note

    @property
    def changed(self):
        return os.path.normcase(self.src) != os.path.normcase(self.dst)


def make_plan(paths, template, rules, fields, enabled_types=None):
    """生成计划：返回 (items, stats)。

    安全闸：
      - 目标名重复 → conflict
      - 目标名已被别的现存文件占用 → conflict
      - 识别失败 → error
      - 命名实体清单未勾选 / 集数不匹配 → excluded（跳过，不动盘）
      - 新旧名相同 → skip
    """
    items = []
    for p in paths:
        try:
            r = build_item(p, template, rules, fields)
        except RuleError as e:
            items.append(PlanItem(p, p, status="error", note=str(e)))
            continue
        if r is None:
            items.append(PlanItem(p, p, status="error", note="无规则命中"))
            continue
        dst, type_str, ep = r
        item = PlanItem(p, dst, type_str, ep)
        # ---- 命名实体清单过滤（在冲突检测之前，排除项不参与占位）----
        ok, why = enabled_state(enabled_types, type_str, ep)
        if not ok:
            item.status = "excluded"
            item.note = why
        items.append(item)

    # ---- 冲突检测（只看仍然待改名的项）----
    dst_counter = Counter(os.path.normcase(i.dst) for i in items if i.status == "")
    # 现存文件集合（排除本次计划里将被改名的那些）
    src_set = {os.path.normcase(i.src) for i in items}
    exist = set()
    for i in items:
        folder = os.path.dirname(i.dst)
        if os.path.isdir(folder):
            try:
                for fn in os.listdir(folder):
                    exist.add(os.path.normcase(os.path.join(folder, fn)))
            except OSError:
                pass

    for i in items:
        if i.status:
            continue
        key = os.path.normcase(i.dst)
        if dst_counter[key] > 1:
            i.status = "conflict"
            i.note = "目标名重复（本批内多条命中同名）"
        elif key in exist and key not in src_set:
            i.status = "conflict"
            i.note = "目标名已被现存文件占用"
        elif not i.changed:
            i.status = "skip"
            i.note = "已是目标命名"

    stats = {
        "total": len(items),
        "rename": sum(1 for i in items if i.status == ""),
        "skip": sum(1 for i in items if i.status == "skip"),
        "error": sum(1 for i in items if i.status == "error"),
        "conflict": sum(1 for i in items if i.status == "conflict"),
        "excluded": sum(1 for i in items if i.status == "excluded"),
    }
    return items, stats


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

def apply_plan(items, write_log=True, log_path=None):
    """执行改名。只处理 status == '' 的项。

    两阶段提交：先把「目标名已被本批某个源名占用」的项挪开，再统一改名 ——
    避免「A→B 且 B→C」的交叉覆盖把数据弄丢。

    回溯日志列顺序固定为 **原文件, 新文件**（与 undo_from_log 严格对应，
    曾经写成颠倒顺序导致撤销全部失败）。

    返回 (done_rows, failed_rows, log_path)。
    """
    done, failed = [], []
    to_do = [i for i in items if i.status == ""]

    # ---- 阶段1：把将成为他人目标的源文件先挪到临时名 ----
    dst_set = {os.path.normcase(i.dst) for i in to_do}
    staged = []          # (item, temp_path)
    occupied = {os.path.normcase(i.src) for i in to_do}
    conflicts = [i for i in to_do
                 if os.path.normcase(i.src) in dst_set]
    # make_plan 已保证无冲突，这里是防御性兜底
    if conflicts:
        for i in conflicts:
            tmp = i.src + ".ru_tmp_%d" % abs(hash(i.src)) % 100000
            try:
                os.rename(i.src, tmp)
                staged.append((i, tmp))
            except OSError as e:
                failed.append((i.src, i.dst, "暂存失败: %s" % e))

    for i in to_do:
        src = i.src
        for it, tmp in staged:
            if it is i:
                src = tmp
                break
        if any(f[0] == i.src for f in failed):
            continue
        try:
            # 统一用绝对路径，避免日志里落 8.3 短路径（ADMINI~1）
            os.rename(src, os.path.abspath(i.dst))
            done.append((os.path.abspath(i.src), os.path.abspath(i.dst)))
        except OSError as e:
            failed.append((i.src, i.dst, str(e)))

    log_path_out = None
    if write_log and done:
        if log_path is None:
            root = os.path.dirname(to_do[0].src) if to_do else "."
            log_path = os.path.join(root, "rename_log_%s.csv"
                                    % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            with open(log_path, "w", encoding="utf-8-sig", newline="") as fp:
                w = csv.writer(fp)
                w.writerow(["原文件", "新文件"])
                w.writerows(done)
            log_path_out = log_path
        except OSError:
            log_path_out = None
    return done, failed, log_path_out


# ---------------------------------------------------------------------------
# 撤销（读日志反向改名）
# ---------------------------------------------------------------------------

LOG_HEADER = ["原文件", "新文件"]


def undo_from_log(log_path, dry_run=False):
    """读回溯日志，把「新文件」改回「原文件」。

    日志列顺序是 原文件, 新文件（apply_plan 写出），所以：
        行 = [原文件, 新文件]
        需要检查存在的是 row[1]（新文件），改回 row[0]（原文件）。
    ⚠️ 这两个索引曾写反，导致撤销 100% 失败 —— 改动前先看这段注释。

    倒序执行，防同名交叉。
    dry_run=True 时只算不改，返回 (可行列表, 问题列表)。
    返回 (done, failed)，failed 项为 (新路径, 原路径, 原因)。
    """
    done, failed = [], []
    try:
        with open(log_path, "r", encoding="utf-8-sig", newline="") as fp:
            rows = list(csv.reader(fp))
    except OSError as e:
        return [], [(log_path, "", "读取失败: %s" % e)]
    if not rows:
        return [], []

    body = rows[1:] if rows[0][:2] == LOG_HEADER else rows
    for row in reversed(body):
        if len(row) < 2:
            continue
        old_p, new_p = row[0], row[1]
        if not old_p or not new_p:
            continue
        # 长/短路径都认一下
        if not os.path.exists(new_p):
            alt = _try_short_to_long(new_p)
            if alt and os.path.exists(alt):
                new_p = alt
        if not os.path.exists(new_p):
            failed.append((new_p, old_p, "新文件不存在（可能已被移动或删除）"))
            continue
        if os.path.exists(old_p) and os.path.normcase(old_p) != os.path.normcase(new_p):
            failed.append((new_p, old_p, "原文件名已被占用，跳过以免覆盖"))
            continue
        if dry_run:
            done.append((new_p, old_p))
            continue
        try:
            # ⚠️ 归位记录的目标父目录（集目录\BUS 等）可能已被 apply_regroup
            # 的「清理空文件夹」删掉 —— 反向移动前必须先补回来，否则整批撤销失败。
            parent = os.path.dirname(old_p)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            os.rename(new_p, old_p)
            done.append((new_p, old_p))
        except OSError as e:
            failed.append((new_p, old_p, str(e)))
    return done, failed


def _try_short_to_long(path):
    """把可能含 8.3 短名的路径转成真实长路径；失败返回 None。"""
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(1024)
        # GetLongPathNameW
        n = ctypes.windll.kernel32.GetLongPathNameW(
            ctypes.c_wchar_p(path), buf, 1024)
        return buf.value if n else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 按集归位（原 FinalMix按集归位.ps1 的能力，移植为跨平台纯 Python）
# ---------------------------------------------------------------------------
# 把分类平铺结构：
#     FinalMix/MIX/x.wav   FinalMix/BUS/x.wav   FinalMix/Stem/x.wav
# 重组为按集分文件夹：
#     FinalMix/前夫 01集 0920 V01/            <- MIX / MIX-MASTER 放集根
#     FinalMix/前夫 01集 0920 V01/BUS/        <- BUS-*
#     FinalMix/前夫 01集 0920 V01/STEM/       <- STEM-*
#
# 安全语义与原 ps1 完全一致：只移动绝不覆盖；解析不了跳过并报告；
# 搬空后清理类别空文件夹。

# 归类文件夹名（大小写沿用原 ps1 的 BUS / STEM）
SCAN_CATEGORIES = ("MIX", "BUS", "Stem")


def regroup_target(type_str):
    """由输出类型决定归位子目录：BUS / STEM / ''（集根）。"""
    t = str(type_str or "").upper()
    if t.startswith("BUS-"):
        return "BUS"
    if t.startswith("STEM-"):
        return "STEM"
    return ""


def find_category_dirs(root):
    """找出 root 下存在的分类平铺目录（大小写不敏感匹配 SCAN_CATEGORIES）。"""
    found = []
    try:
        entries = os.listdir(root)
    except OSError:
        return found
    low = {e.casefold(): e for e in entries}
    for cat in SCAN_CATEGORIES:
        real = low.get(cat.casefold())
        if real:
            p = os.path.join(root, real)
            if os.path.isdir(p):
                found.append(p)
    return found


def build_regroup_plan(root, rules, fields, split_mark=" 7F_"):
    """扫描分类目录，算出「平铺 → 按集」的移动计划。

    返回 (items, stats)；item 是 PlanItem 复用体：
        src  源文件绝对路径
        dst  目标绝对路径
        status: ''（待移动）/ skip / error
    split_mark 原本用于从模块名切出「集前缀」；但本工具已有强识别引擎，
    优先走 identify()（能处理 -DX Folder / 裸集数等历史写法），
    识别不出再回退到 split_mark 的字面切分。
    """
    items = []
    if not os.path.isdir(root):
        return items, {"total": 0, "move": 0, "skip": 0, "error": 0}

    for cat_dir in find_category_dirs(root):
        try:
            names = sorted(os.listdir(cat_dir))
        except OSError:
            continue
        for fn in names:
            src = os.path.join(cat_dir, fn)
            if not os.path.isfile(src) or fn.startswith("."):
                continue
            stem, ext = os.path.splitext(fn)

            ep_prefix = ""
            type_str = ""
            hit = identify(stem, rules, fields)
            if hit is not None:
                _d, ep, type_str = hit
                # 集前缀 = 新命名去掉类型段后的部分
                full = render(DEFAULT_TEMPLATE, ep, type_str, fields)
                tail = "_" + str(type_str)
                ep_prefix = full[: -len(tail)] if full.endswith(tail) else full
            else:
                # 回退：按分隔标记字面切分（与原 ps1 行为一致）
                idx = stem.find(split_mark)
                if idx < 1:
                    items.append(PlanItem(src, src, status="error",
                                          note="无法解析集前缀"))
                    continue
                ep_prefix = stem[:idx]
                type_str = stem[idx + len(split_mark):]

            sub = regroup_target(type_str)
            ep_dir = os.path.join(root, ep_prefix)
            target = os.path.join(ep_dir, sub) if sub else ep_dir
            dst = os.path.join(target, fn)

            item = PlanItem(src, dst, type_str)
            if os.path.normcase(src) == os.path.normcase(dst):
                item.status = "skip"
                item.note = "已在该集目录"
            elif os.path.exists(dst):
                item.status = "error"
                item.note = "目标已存在（不覆盖，已跳过）"
            items.append(item)

    stats = {
        "total": len(items),
        "move": sum(1 for i in items if i.status == ""),
        "skip": sum(1 for i in items if i.status == "skip"),
        "error": sum(1 for i in items if i.status == "error"),
    }
    return items, stats


def apply_regroup(items, cleanup_empty=True):
    """执行归位移动，返回 (done, failed, cleaned)。

    done 每项为 (源绝对路径, 目标绝对路径)，供写回溯日志。
    cleanup_empty 为真时，把搬空的分类文件夹删掉（仅当确实为空）。
    """
    done, failed, touched_dirs = [], [], set()
    for i in items:
        if i.status != "":
            continue
        target_dir = os.path.dirname(i.dst)
        try:
            if not os.path.isdir(target_dir):
                os.makedirs(target_dir, exist_ok=True)
            os.replace(i.src, i.dst)
            done.append((os.path.abspath(i.src), os.path.abspath(i.dst)))
            touched_dirs.add(os.path.dirname(i.src))
        except OSError as e:
            failed.append((i.src, i.dst, str(e)))

    cleaned = []
    if cleanup_empty:
        for d in sorted(touched_dirs, key=len, reverse=True):
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
                    cleaned.append(d)
            except OSError:
                pass
    return done, failed, cleaned
