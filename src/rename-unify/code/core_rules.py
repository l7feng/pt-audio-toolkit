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
        self.status = status          # rename / skip / error / conflict
        self.note = note

    @property
    def changed(self):
        return os.path.normcase(self.src) != os.path.normcase(self.dst)


def make_plan(paths, template, rules, fields):
    """生成计划：返回 (items, stats)。

    安全闸：
      - 目标名重复 → conflict
      - 目标名已被别的现存文件占用 → conflict
      - 识别失败 → error
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
        items.append(PlanItem(p, dst, type_str, ep))

    # ---- 冲突检测 ----
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
