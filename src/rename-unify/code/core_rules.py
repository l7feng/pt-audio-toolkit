# -*- coding: utf-8 -*-
"""rename-unify 核心规则引擎 v1.2.0（与 GUI 完全解耦，可独立测试）

v1.2.0 设计改变（2026-09-23）
-----------------------------
v1.1.0 的模型是「一条规则 → 一个类型串（BUS-DX / STEM-MX-02）」，导致：
  * 类型串与归位目录、命名模板三者硬绑，无法「模板和目标拆开」
  * `_` 之后的**自由轨道信息**（`MX Verb ST` / `DX UI` / `Ai FX 1` / `FX 1 MON`）
    一条都识别不了（实测 20/28 失败，含已交付的 17 集成品）

v1.2.0 改为「**目标（Target）+ 轨道信息（info）**」两段式：

    识别（宽松正则） ──► (目标, 集数, 轨道信息, 已捕获字段)
                          │      │      │            │
                          │      │      │            └─ 源名里已带的 日期/版本/用户，优先于全局字段
                          │      │      └─ 原样保留，填进模板的 {轨道信息}
                          │      └─ 补零后填 {集数}
                          └─ 目标表 → 归位目录 + 命名模板（可多选）

目标表（可编辑）：
    MIX  → 归位「集根」   BUS → 归位「BUS/」
    STEM → 归位「STEM/」  AIFX → 归位「STEM/」（AI 音效与 STEM 同目录）

关键安全设计
------------
1. **源名里已有的 日期/版本/用户 优先于全局字段** —— 已合规的文件不会被
   全局字段「顺手改掉」（如 `法老 12集 0922 V01 7F_Master` 不会被改成 0923）。
2. **轨道信息原样保留** —— 不重排、不翻译，源文件风格（`DX BUS` vs `BUS-DX`）保持。
3. 计划（plan）与执行（apply）分离；执行前先生成回溯日志。全程零第三方依赖。
"""

import csv
import os
import re
import datetime
from collections import Counter

# ---------------------------------------------------------------------------
# 术语别名（v1.2.0：{档位} → {用户}，旧写法永久兼容）
# ---------------------------------------------------------------------------
# 用户 2026-09-23 指出：`7F` 是混音师/用户代号，不是「档位」。占位符改名为
# `{用户}`；旧配置与旧规则里的 `{档位}` 在展开前统一归一化为 `{用户}`，
# 因此**不会**出现「两个命名组同名」的 re.error。
PLACEHOLDER_ALIAS = {"{档位}": "{用户}", "{Slate}": "{用户}", "{slate}": "{用户}"}

# 模板里可用的占位符（UI 提示用）
TEMPLATE_FIELDS = ("片名", "集数", "日期", "版本", "用户", "轨道信息")

DEFAULT_TEMPLATE = "{片名} {集数}集 {日期} {版本} {用户}_{轨道信息}"

# 「保持原名」：只归类、不改名（配合归位使用）
KEEP_NAME = "保持原名"

# 内置模板库（GUI 页1 可增删改；页2 每个目标从这里**选一套**）
# B 语义（2026-09-23 用户定案）：每类目标各用各自模板，**不产生多份副本**。
# （A 语义「勾多套＝各生成一份」已否决，理由是重命名场景下音频体积会翻倍。）
DEFAULT_TEMPLATES = [
    {"name": "全格式", "tpl": DEFAULT_TEMPLATE},
    {"name": "短格式", "tpl": "{片名} {集数}_{轨道信息}"},
]


# ---------------------------------------------------------------------------
# 默认目标表（GUI 里可改，改完存 config.json）
# ---------------------------------------------------------------------------
# templates 存**模板内容**（不是名字），core 直接拿去渲染；
# tpl_name 只用于 GUI 回显「这个目标选的是库里哪一套」。
DEFAULT_TARGETS = [
    {"name": "MIX", "dir": "", "enabled": True, "eps": "",
     "note": "混音成品/终稿 → 集根目录", "templates": [], "tpl_name": ""},
    {"name": "BUS", "dir": "BUS", "enabled": True, "eps": "",
     "note": "总线分轨 → <集目录>/BUS", "templates": [], "tpl_name": ""},
    {"name": "STEM", "dir": "STEM", "enabled": True, "eps": "",
     "note": "分段素材 → <集目录>/STEM", "templates": [], "tpl_name": ""},
    {"name": "AIFX", "dir": "STEM", "enabled": True, "eps": "",
     "note": "AI 音效（与 STEM 同目录）", "templates": [], "tpl_name": ""},
]

# 归位目录名（识别「集目录」时要向上剥掉的层）
CATEGORY_DIR_NAMES = ("MIX", "MIX-MASTER", "BUS", "STEM", "Stem", "AIFX")


# ---------------------------------------------------------------------------
# 识别规则族：每行 [目标, 正则, 轨道信息模板]
# ---------------------------------------------------------------------------
# 正则里可用的**宽松占位符**（见 _LOOSE）：
#     {片名}  {集数}（数字+集）  {裸集数}（纯数字）  {日期}  {版本}  {用户}  {轨道信息}
# 之外可写任意普通正则（如显式的 (?P<info>.+) 捕获组）。
# 轨道信息模板用 \g<名字> 引用捕获组；写死字符串则原样使用。
#
# ⚠️ 顺序即优先级（自上而下**首个命中生效**）：越具体的越靠前，
#    「裸集数 + 自由轨道信息」这条兜底规则必须放最后。
DEFAULT_RULES = [
    # ==================== AIFX：AI 音效 ====================
    ["AIFX", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{用户}_(?P<info>Ai\s*FX(?:\s+\d+)?)$", "\\g<info>"],
    ["AIFX", r"^{片名}\s*{裸集数}_(?P<info>Ai\s*FX(?:\s+\d+)?)$", "\\g<info>"],

    # ==================== BUS：总线分轨 ====================
    # 全格式：法老 17集 0922 V01 7F_DX BUS  /  ..._BUS-DX
    ["BUS", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{用户}_(?P<info>(?:DX|FX|MX)\s+BUS)$", "\\g<info>"],
    ["BUS", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{用户}_BUS-(?P<info>DX|FX|MX)$", "BUS-\\g<info>"],
    # 裸集数：法老20_DX BUS  /  前夫2_BUS DX Folder  /  前夫1_DX Folder
    ["BUS", r"^{片名}\s*{裸集数}_(?P<info>(?:DX|FX|MX)\s+BUS)$", "\\g<info>"],
    ["BUS", r"^{片名}\s*{裸集数}_BUS\s+(?P<info>DX|FX|MX)\s+Folder$", "BUS-\\g<info>"],
    ["BUS", r"^{片名}\s*{裸集数}_(?P<info>DX|FX|MX)\s+Folder$", "BUS-\\g<info>"],

    # ==================== MIX：混音成品（放集根） ====================
    # 全格式：法老 17集 0922 V01 7F_Master  /  ..._Master BUS  /  ..._MIX-MASTER
    ["MIX", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{用户}_Master(?:\s+BUS)?$", "Master"],
    ["MIX", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{用户}_(?P<info>MIX|MIX-MASTER)$", "\\g<info>"],
    ["MIX", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{用户}$", "Master"],
    # 裸集数：法老20_Master BUS  /  法老20_Master
    ["MIX", r"^{片名}\s*{裸集数}_Master\s+BUS$", "Master"],
    ["MIX", r"^{片名}\s*{裸集数}_Master$", "Master"],

    # ==================== STEM：分段素材 ====================
    # 全格式 + 自由轨道信息：..._DX 1 / ..._Ai FX 1 / ..._MX Verb ST / ..._DX UI
    ["STEM", r"^{片名}\s+{集数}\s+{日期}\s+{版本}\s+{用户}_(?P<info>.+)$", "\\g<info>"],
    # 兜底：裸集数 + 自由轨道信息（法老20_DX 1 / 法老13_FX 1 MON / 法老12_MX Verb ST）
    ["STEM", r"^{片名}\s*{裸集数}_(?P<info>.+)$", "\\g<info>"],
]

# 默认字段值（模板渲染用，GUI 里可改）
DEFAULT_FIELDS = {
    "片名": "前夫",
    "日期": "0920",
    "版本": "V01",
    "用户": "7F",
}


# ---------------------------------------------------------------------------
# 宽占位符展开
# ---------------------------------------------------------------------------
# ⚠️ 设计约束（踩过的坑，别重犯）：
#   1. 每个占位符的替换串**必须自带完整括号**，_loose_regex 只管直接替换。
#   2. 捕获组一律用**命名组**；用 \1 \2 位置引用时，任一规则多加一个组就全错位。
#   3. {片名} 用非贪婪 `.+?`，否则会把集数一起吞掉。
_LOOSE = {
    "{片名}": r"(?P<show>.+?)",
    "{集数}": r"(?P<ep>\d+)\s*集",
    "{裸集数}": r"(?P<ep>\d+)",
    "{日期}": r"(?P<date>\d{4,8})",
    "{版本}": r"(?P<ver>V\d+)",
    "{用户}": r"(?P<user>[A-Za-z0-9]{1,8})",
    "{轨道信息}": r"(?P<info>.+)",
}

# 替换顺序：长的在前，避免 {集数} 抢掉 {裸集数} 的前缀
_PLACEHOLDERS = ("{片名}", "{裸集数}", "{集数}", "{日期}", "{版本}", "{用户}", "{轨道信息}")


def normalize_placeholder(text):
    """把旧占位符别名统一成新写法（{档位} → {用户}）。"""
    out = str(text or "")
    for old, new in PLACEHOLDER_ALIAS.items():
        if old in out:
            out = out.replace(old, new)
    return out


def _loose_regex(pattern):
    r"""把带 {占位符} 的规则展开为可匹配历史命名的正则（不含扩展名）。

    会先把 {档位} 之类旧别名归一化为 {用户}，避免出现同名捕获组。
    """
    out = normalize_placeholder(pattern)
    for ph in _PLACEHOLDERS:
        if ph in out:
            out = out.replace(ph, _LOOSE[ph])
    return out


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


def parse_eps(raw):
    """把「1,3-5」这类集数表达式解析成集合。

    支持：逗号/空格/顿号分隔的单项，以及 a-b 区间。
    返回 set[int]；空输入返回空 set（= 不限集数）。非法片段忽略。
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


# ---------------------------------------------------------------------------
# 目标表
# ---------------------------------------------------------------------------

class Hit(object):
    """一次识别的结果。"""

    __slots__ = ("target", "ep", "info", "captured", "rule_index")

    def __init__(self, target, ep, info, captured=None, rule_index=-1):
        self.target = target          # 目标名（MIX / BUS / STEM / AIFX ...）
        self.ep = str(ep or "")       # 原始集数（未补零）
        self.info = str(info or "")   # 轨道信息（原样保留的自由文本）
        self.captured = dict(captured or {})   # 源名里已带的字段
        self.rule_index = rule_index


def normalize_targets(raw):
    """清洗目标表：补默认键、丢掉无名项、去重。"""
    if not isinstance(raw, list) or not raw:
        return [dict(t) for t in DEFAULT_TARGETS]
    out, seen = [], set()
    for e in raw:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name", "")).strip().upper()
        if not name or name in seen:
            continue
        seen.add(name)
        tpls = e.get("templates")
        if isinstance(tpls, str):
            tpls = [tpls]
        tpls = [str(t).strip() for t in (tpls or []) if str(t).strip()]
        out.append({
            "name": name,
            "dir": str(e.get("dir", "") or "").strip(),
            "enabled": bool(e.get("enabled", True)),
            "eps": str(e.get("eps", "") or "").strip(),
            "note": str(e.get("note", "") or ""),
            "templates": tpls,
            "tpl_name": str(e.get("tpl_name", "") or "").strip(),
        })
    return out or [dict(t) for t in DEFAULT_TARGETS]


def resolve_targets(targets):
    """目标表统一入口：None / 空列表 → 内置默认表。

    为什么不把「空」解释成「不分层」：目标表是 v1.2.0 的核心模型，没有它
    就不知道 BUS / STEM 该放进集目录下的哪一层。裸调用（脚本、单元测试）
    也应当拿到合理默认，而不是静默把所有文件都堆回集根。
    """
    return targets if targets else DEFAULT_TARGETS


def target_map(targets):
    """目标名 → 目标定义（大小写不敏感）。"""
    return {str(t.get("name", "")).strip().upper(): t for t in (targets or [])}


def target_state(targets, target, ep_raw):
    """判断某个 (目标, 集数) 是否允许处理。返回 (allowed, reason)。"""
    tmap = target_map(targets)
    if not tmap:
        return True, ""
    t = tmap.get(str(target or "").strip().upper())
    if t is None:
        return False, "目标表未列出该目标"
    if not t.get("enabled", True):
        return False, "目标已取消勾选"
    eps = parse_eps(t.get("eps"))
    if eps and ep_int(ep_raw) not in eps:
        return False, "目标限定集数不含 %s 集" % normalize_ep(ep_raw)
    return True, ""


def templates_for(target, targets, global_template):
    """取某个目标要用的模板列表。

    目标没配模板 → 回落到全局模板；空列表同样回落（保证永远有模板可用）。
    """
    t = target_map(targets).get(str(target or "").strip().upper())
    tpls = list((t or {}).get("templates") or [])
    if not tpls:
        tpls = [str(global_template or DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE]
    return tpls


# ---------------------------------------------------------------------------
# 单文件：识别 + 生成新名
# ---------------------------------------------------------------------------

class RuleError(Exception):
    pass


def identify(filename, rules, targets=None):
    """识别一个文件名（不含扩展名）。识别不了返回 None。

    返回 Hit(target, ep, info, captured)：
      target    目标名，如 BUS / STEM / AIFX / MIX
      ep        原始集数字符串（未补零）
      info      轨道信息（源名 `_` 之后的原文，原样保留）
      captured  源名里已成功捕获的字段（日期/版本/用户/片名），渲染时**优先于全局字段**

    集数取值：只认命名组 ``ep``（{集数} / {裸集数} 展开而来）。
    ⚠️ 不要改成「第一个像数字的捕获组」—— 日期 0920、序号 01 都是数字，
    会误判（曾经的 bug）。
    """
    rules = rules or DEFAULT_RULES
    for idx, row in enumerate(rules):
        if not row or len(row) < 3:
            continue
        tgt, pattern, out = str(row[0]).strip(), str(row[1]), str(row[2])
        if not tgt:
            continue
        try:
            rx = re.compile(_loose_regex(pattern) + r"$")
        except re.error:
            continue
        m = rx.match(filename)
        if not m:
            continue

        # 展开轨道信息模板里的 \g<info> / \g<lane> ...
        try:
            info = m.expand(out) if "\\" in out else out
        except (re.error, IndexError):
            continue

        gd = m.groupdict() or {}
        ep = gd.get("ep") or ""
        captured = {}
        for src, dst in (("date", "日期"), ("ver", "版本"), ("user", "用户"),
                         ("show", "片名")):
            v = gd.get(src)
            if v:
                captured[dst] = v.strip()
        return Hit(tgt, ep, info, captured, idx)
    return None


def render(template, ep_raw, info, fields, captured=None):
    """按模板渲染新文件名主体（**不含扩展名**）。

    - 轨道信息**原样保留、绝不改写**（见 normalize_info 的说明）。
    - 源名已捕获的字段（日期/版本/用户/片名）优先于全局字段。
    - 容错：模板里误写了 .wav 会被剥掉，避免双扩展名。
    """
    tpl = normalize_placeholder(str(template or "").strip())
    # 剥掉模板末尾可能误写的扩展名
    m = re.search(r"\.(wav|aif|aiff|mp3|flac|w64)$", tpl, re.I)
    if m:
        tpl = tpl[:m.start()]

    vals = {k: str(v) for k, v in (fields or {}).items()}
    # 旧配置可能只有「档位」键 → 迁移成「用户」
    for old, new in PLACEHOLDER_ALIAS.items():
        key, nkey = old.strip("{}"), new.strip("{}")
        if key in vals and nkey not in vals:
            vals[nkey] = vals.pop(key)
    for k, v in (captured or {}).items():
        if v:
            vals[k] = str(v)          # 源名已带的字段优先
    vals["集数"] = normalize_ep(ep_raw)
    vals["轨道信息"] = normalize_info(info)
    vals["类型"] = vals["轨道信息"]   # 兼容旧模板里的 {类型}
    vals.setdefault("用户", "")
    try:
        return tpl.format(**vals)
    except KeyError as e:
        raise RuleError("模板里有未知占位符: %s（可用: %s）"
                        % (e, "/".join(TEMPLATE_FIELDS)))
    except (IndexError, ValueError) as e:
        raise RuleError("模板格式错误: %s" % e)


def normalize_info(info):
    """轨道信息规范化 —— **只去首尾空白，其余一律原样保留**。

    ⚠️ 这里曾经给「尾段是纯数字」的序号补零（`DX 1` → `DX 01`），2026-09-23
    用真实数据回归时发现它会**把用户已交付的成品改掉**：
        `法老 17集 0922 V01 7F_Ai FX 1.wav` → 被改成 `..._Ai FX 01.wav`
    而 17 集是用户手工做好的标准答案，序号本来就是 1 位。补零属于「顺手改写
    别人的既定命名」，违反本工具「已合规就不动」的核心承诺 —— 故永久取消。

    结论：**轨道信息是识别出来的原文，不是重新生成的**。风格差异
    （`DX BUS` / `BUS-DX` / `DX 1` / `DX 01`）由源文件决定，工具不统一。
    """
    return str(info or "").strip()


def build_item(path, template, rules, fields, root=None, targets=None):
    """对单个文件算出 (目标绝对路径, Hit, 是否需新建集目录)。识别不了返回 None。

    落点规则（root＝用户在「目标目录」里选的根）：
      * 先找到该文件的**集目录** —— 从父目录向上剥掉 BUS/STEM/MIX 这类分类目录名；
      * 若剥完恰好等于 root 且 root 自身不像集目录 → 视为**平铺布局**，
        在 root 下新建「<片名> <集数>集 <日期> <版本> <用户>」集目录；
      * 否则**就地**（保留现成的集目录名，如 `13` / `20`）—— 这是法老D 的现状。
    目标表里的 dir（BUS / STEM / 空）决定集目录下的哪一层。
    """
    targets = resolve_targets(targets)
    folder, filename = os.path.split(os.path.abspath(path))
    stem, ext = os.path.splitext(filename)
    hit = identify(stem, rules, targets)
    if hit is None:
        return None

    ep_dir, need_new_ep = _resolve_ep_dir(folder, root, hit, fields, targets)
    sub = ""
    t = target_map(targets).get(hit.target.upper())
    if t is not None:
        sub = str(t.get("dir") or "").strip()
    dst_dir = os.path.join(ep_dir, sub) if sub else ep_dir

    new_stem = _render_for_target(hit, template, fields, targets)
    if new_stem is None:                    # 「保持原名」→ 沿用源名
        new_stem = stem
    elif ext and new_stem.lower().endswith(ext.lower()):
        new_stem = new_stem[: -len(ext)]
    return os.path.join(dst_dir, new_stem + ext), hit, need_new_ep


def _render_for_target(hit, template, fields, targets):
    """按**该目标自己绑定的模板**渲染新名主体。

    这就是「模板和目标拆开」的落点：MIX 走全格式、BUS/STEM 走短格式，
    各改各的、互不干扰。目标没配模板 → 回落全局模板（保证永远有名字可用）。

    「保持原名」（KEEP_NAME）是特殊值：返回 None，由调用方沿用源文件名，
    只做归位、不改名 —— 对应「只改 Master、BUS/STEM 保持原名」那种状态。
    """
    tpls = templates_for(hit.target, targets, template)
    tpl = str(tpls[0]).strip() if tpls else str(template or "").strip()
    if not tpl or tpl == KEEP_NAME:
        return None
    return render(tpl, hit.ep, hit.info, fields, hit.captured)


def _looks_like_ep_dir(name):
    """目录名是否「像集目录」：纯数字、或含「集」字。"""
    n = str(name or "").strip()
    return bool(re.fullmatch(r"\d{1,4}", n)) or ("集" in n)


def _is_category_dir(name):
    n = str(name or "").strip()
    return any(n.casefold() == c.casefold() for c in CATEGORY_DIR_NAMES)


def _resolve_ep_dir(folder, root, hit, fields, targets=None):
    """返回 (集目录绝对路径, 是否需要新建该目录)。"""
    d = os.path.abspath(folder)
    while _is_category_dir(os.path.basename(d)) and os.path.dirname(d) != d:
        d = os.path.dirname(d)

    root_abs = os.path.abspath(root) if root else None
    if root_abs and os.path.normcase(d) == os.path.normcase(root_abs) \
            and not _looks_like_ep_dir(os.path.basename(d)):
        # 平铺布局：在 root 下新建以「集前缀」命名的集目录
        prefix_tpl = "{片名} {集数}集 {日期} {版本} {用户}"
        try:
            prefix = render(prefix_tpl, hit.ep, hit.info, fields, hit.captured)
        except RuleError:
            prefix = ""
        if prefix:
            return os.path.join(root_abs, prefix), True
    return d, False


# ---------------------------------------------------------------------------
# 目录扫描 + 计划
# ---------------------------------------------------------------------------

def scan_dir(root, recursive=True, exts=(".wav", ".aif", ".aiff", ".mp3", ".flac", ".w64")):
    """列出待处理文件（绝对路径）。隐藏文件跳过。"""
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
                out.append(os.path.abspath(os.path.join(dirpath, fn)))
    else:
        for fn in os.listdir(root):
            p = os.path.abspath(os.path.join(root, fn))
            if os.path.isfile(p) and not fn.startswith("."):
                if exts and os.path.splitext(p)[1].lower() not in exts:
                    continue
                out.append(p)
    return sorted(out)


class PlanItem(object):
    __slots__ = ("src", "dst", "target", "info", "ep", "status", "note", "new_dir")

    def __init__(self, src, dst, target="", info="", ep="", status="", note="", new_dir=False):
        self.src = src
        self.dst = dst
        self.target = target      # 目标名（MIX / BUS / STEM / AIFX）
        self.info = info          # 轨道信息
        self.ep = ep
        self.status = status      # ''(待处理) / skip / error / conflict / excluded
        self.note = note
        self.new_dir = new_dir    # 需要新建集目录

    # 兼容 v1.1.0 的属性名
    @property
    def type_str(self):
        return "%s %s" % (self.target, self.info) if self.info else self.target

    @property
    def changed(self):
        return os.path.normcase(self.src) != os.path.normcase(self.dst)


# 疑似衍生文件的轨道信息特征（只提示、不改归属）：
#   `.dup1`（PT 里复制出来的副本）、` MON`（单声道试听版）
_SUSPECT_RE = re.compile(r"(\.dup\w*|\sMON)\s*$", re.I)


def ep_dir_of(path):
    """取文件所属的**集目录**（向上剥掉 BUS/STEM/MIX 这类分类目录名）。

    与 build_item 的落点判定用同一套剥离规则，因此可用作「目录级字段推断」的 key。
    """
    d = os.path.dirname(os.path.abspath(path))
    while _is_category_dir(os.path.basename(d)) and os.path.dirname(d) != d:
        d = os.path.dirname(d)
    return d


def collect_dir_defaults(paths, rules):
    """按「集目录」统计源文件里已带的字段（多数票），作为**目录级默认值**。

    为什么需要：同一集里 Master 已经写成 `法老 12集 0922 V01 7F_Master`，
    而该集的 BUS/STEM 还是源名（没有日期）。若直接用全局字段 0923 补，
    就会出现「同一个集目录里 0922 和 0923 并存」的不一致。
    目录级推断让 `0922` 自动继承给同集其它文件。

    字段优先级：**源文件自身捕获 > 集目录多数票 > 全局字段**。
    返回 {集目录绝对路径: {字段: 值}}。
    """
    buckets = {}
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        h = identify(stem, rules)
        if h is None or not h.captured:
            continue
        d = ep_dir_of(p)
        for k, v in h.captured.items():
            buckets.setdefault(d, {}).setdefault(k, Counter())[v] += 1
    out = {}
    for d, ks in buckets.items():
        out[d] = {k: c.most_common(1)[0][0] for k, c in ks.items()}
    return out


def mark_conflicts(items):
    """就地标注「冲突 / 已合规」。只处理 status == '' 的项，已标注的不动。

    抽成独立函数的理由：GUI 的「手动分类」替换了某些项的目标路径后，
    必须**只重算这些项**，不能整表重来（否则用户手填的集数会丢）。
    """
    dst_counter = Counter(os.path.normcase(i.dst) for i in items if i.status == "")
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
    return items


def count_stats(items):
    """汇总统计（GUI 状态栏 / 预览报告共用，避免两处口径不一致）。"""
    stats = {
        "total": len(items),
        "rename": sum(1 for i in items if i.status == ""),
        "skip": sum(1 for i in items if i.status == "skip"),
        "error": sum(1 for i in items if i.status == "error"),
        "conflict": sum(1 for i in items if i.status == "conflict"),
        "excluded": sum(1 for i in items if i.status == "excluded"),
    }
    stats["move"] = sum(1 for i in items if i.status == "" and
                       os.path.normcase(os.path.dirname(i.src)) !=
                       os.path.normcase(os.path.dirname(i.dst)))
    # 目标目录尚不存在 → 执行时会新建（含 BUS/ STEM/ 这类子目录）
    stats["new_dirs"] = len({os.path.normcase(os.path.dirname(i.dst)) for i in items
                             if i.status == "" and not os.path.isdir(os.path.dirname(i.dst))})
    return stats


def make_plan(paths, global_template, rules, fields, targets=None, root=None):
    """生成计划：返回 (items, stats)。

    安全闸：
      - 识别失败 → error（GUI 里可「手动分类」指定集数与目标）
      - 目标未勾选 / 集数不匹配 → excluded（跳过，不动盘）
      - 目标名重复 → conflict
      - 目标名已被别的现存文件占用 → conflict
      - 新旧名完全相同 → skip
    """
    targets = resolve_targets(targets)
    items = []
    dir_defaults = collect_dir_defaults(paths, rules)
    for p in paths:
        # 集目录级字段（源文件自身捕获的字段在 render 里再覆盖一次，优先级更高）
        eff_fields = dict(fields or {})
        eff_fields.update(dir_defaults.get(ep_dir_of(p), {}))
        try:
            r = build_item(p, global_template, rules, eff_fields, root=root, targets=targets)
        except RuleError as e:
            items.append(PlanItem(p, p, status="error", note=str(e)))
            continue
        if r is None:
            items.append(PlanItem(p, p, status="error", note="无规则命中"))
            continue
        dst, hit, need_new = r
        item = PlanItem(p, dst, hit.target, hit.info, hit.ep, new_dir=need_new)
        ok, why = target_state(targets, hit.target, hit.ep)
        if not ok:
            item.status = "excluded"
            item.note = why
        elif _SUSPECT_RE.search(hit.info):
            # 不是错误、不改归属，只是提醒人类看一眼再执行
            item.note = "疑似衍生文件 %s · 请确认是否要一并交付" % \
                        _SUSPECT_RE.search(hit.info).group(1).strip()
        items.append(item)

    mark_conflicts(items)
    return items, count_stats(items)


# ---------------------------------------------------------------------------
# 手动分类（识别失败的人工兜底，GUI 页3 用）
# ---------------------------------------------------------------------------

def guess_info_from_name(filename):
    """识别失败时猜「轨道信息」候选：取源名最后一个 `_` 之后的原文。

    用户的真实命名里 `_` 之后就是轨道信息（`法老20_DX BUS` → `DX BUS`）。
    猜不准没关系 —— 只用于给「手动分类」对话框预填，用户可以改。
    """
    stem = os.path.splitext(os.path.basename(str(filename)))[0]
    if "_" in stem:
        return stem.rsplit("_", 1)[1].strip()
    return stem.strip()


def manual_plan_item(path, ep, target, info, template, fields, root=None, targets=None):
    """人工分类：对识别失败的文件指定「集数 + 目标 + 轨道信息」后重算落点。

    识别失败的项没有 Hit（正是因为识别不出来才需要人工），所以这里现造一个，
    再走与自动流程**完全相同**的落点/渲染逻辑 —— 保证人工指定的结果和自动
    识别出来的格式一模一样，不会出现两套命名风格。
    """
    targets = resolve_targets(targets)
    hit = Hit(target, ep, info, {}, -1)
    folder = os.path.dirname(os.path.abspath(path))
    ep_dir, need_new = _resolve_ep_dir(folder, root, hit, fields, targets)
    t = target_map(targets).get(str(target or "").strip().upper())
    sub = str((t or {}).get("dir") or "").strip()
    dst_dir = os.path.join(ep_dir, sub) if sub else ep_dir

    stem, ext = os.path.splitext(os.path.basename(path))
    new_stem = _render_for_target(hit, template, fields, targets)
    if new_stem is None:
        new_stem = stem
    elif ext and new_stem.lower().endswith(ext.lower()):
        new_stem = new_stem[: -len(ext)]
    return PlanItem(path, os.path.join(dst_dir, new_stem + ext),
                    str(target or "").strip().upper(), str(info or ""), str(ep or ""),
                    new_dir=need_new)


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

def apply_plan(items, write_log=True, log_path=None):
    """执行改名/移动。只处理 status == '' 的项。

    两阶段提交：先把「目标名已被本批某个源名占用」的项挪到临时名，再统一改名 ——
    避免「A→B 且 B→C」的交叉覆盖把数据弄丢。

    回溯日志列顺序固定为 **原文件, 新文件**（与 undo_from_log 严格对应，
    曾经写成颠倒顺序导致撤销全部失败）。

    返回 (done_rows, failed_rows, log_path)。
    """
    done, failed = [], []
    to_do = [i for i in items if i.status == ""]

    # ---- 阶段1：把将成为他人目标的源文件先挪到临时名 ----
    dst_set = {os.path.normcase(i.dst) for i in to_do}
    staged = []
    conflicts = [i for i in to_do if os.path.normcase(i.src) in dst_set]
    if conflicts:
        for i in conflicts:
            tmp = i.src + ".ru_tmp_%d" % (abs(hash(i.src)) % 100000)
            try:
                os.rename(i.src, tmp)
                staged.append((i, tmp))
            except OSError as e:
                failed.append((i.src, i.dst, "暂存失败: %s" % e))

    # ---- 阶段2：统一改名（顺带建目标目录）----
    for i in to_do:
        src = i.src
        for it, tmp in staged:
            if it is i:
                src = tmp
                break
        if any(f[0] == i.src for f in failed):
            continue
        try:
            folder = os.path.dirname(i.dst)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
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

    倒序执行，防同名交叉。dry_run=True 时只算不改。
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
            # ⚠️ 改名时新建的目标父目录（集目录\BUS 等）可能已被清理，
            # 反向移动前必须先补回来，否则整批撤销失败。
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
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetLongPathNameW(
            ctypes.c_wchar_p(path), buf, 1024)
        return buf.value if n else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 兼容层：v1.1.0 的「类型串」清单（enabled_types）→ 目标表
# ---------------------------------------------------------------------------

def migrate_enabled_types(enabled_types):
    """把 v1.1.0 的 `enabled_types`（BUS-DX / STEM-MX-* …）折成目标表。

    `BUS-*` → BUS；`STEM-*` → STEM；含 `AI FX` → AIFX；`MIX*` → MIX。
    没被任何条目覆盖的目标置 enabled=False。无有效条目时返回 []（= 用默认表）。
    """
    if not isinstance(enabled_types, list) or not enabled_types:
        return []
    want = {}
    for e in enabled_types:
        if not isinstance(e, dict):
            continue
        t = str(e.get("type", "")).strip().upper()
        if not t:
            continue
        if "AI FX" in t or t.startswith("AIFX"):
            name = "AIFX"
        elif t.startswith("BUS"):
            name = "BUS"
        elif t.startswith("STEM"):
            name = "STEM"
        elif t.startswith("MIX"):
            name = "MIX"
        else:
            continue
        cur = want.setdefault(name, {"enabled": False, "eps": ""})
        if e.get("enabled", True):
            cur["enabled"] = True
        if not cur["eps"]:
            cur["eps"] = str(e.get("eps", "") or "").strip()
    if not want:
        return []
    out = []
    for t in DEFAULT_TARGETS:
        name = t["name"]
        d = dict(t)
        if name in want:
            d["enabled"] = want[name]["enabled"]
            d["eps"] = want[name]["eps"]
        else:
            d["enabled"] = False
        out.append(d)
    return out
