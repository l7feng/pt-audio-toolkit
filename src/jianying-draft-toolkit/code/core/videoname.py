# -*- coding: utf-8 -*-
"""视频文件名 → 结构化字段（项目 / 集数 / 编号 / AiFX）。

为什么要有这个模块
------------------
剪映草稿里的视频素材名经常**就是**交付信息的唯一载体：
`17.mp4`、`法老2.mp4`、`法老的禁忌神谕 第10集 待混音.mp4`、`1.1.0.mp4`。
而工具此前只把「草稿文件夹名」当项目名 —— 视频名里的集数/编号全被丢掉，
于是同一草稿里的多集音频导出来只能靠人工分辨。

设计原则
--------
1. **能提取就提取，提取不了就明确报「需要人类补」** —— 不猜、不静默填空。
   猜错的项目名会流进几十个文件名，比留空危害大得多。
2. 两类必须人类介入的情况（用户 2026-09-23 定案）：
   - **纯数字**（`17.mp4`）：通常就是集数，缺的是项目名 → 让人类补项目名。
   - **项目名候选超过 4 个字**（`法老的禁忌神谕…`）：交付文件名会过长 →
     让人类给一个缩写（工具给建议值，回车即采纳）。
3. 本模块**零依赖**（不 import tkinter / 不读文件），可在测试里直接跑。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

#: 项目名（中文/英文）超过这个字数就要求人类给缩写
MAX_PROJECT_LEN = 4

#: 视为「AiFX 标记」的关键字（大小写不敏感）
AIFX_PAT = re.compile(r"(ai[\s_\-]*fx|aifx|ai音效)", re.I)

#: `第10集` / `第10期` / `EP10` / `E10`  → 集数
EP_PAT = re.compile(r"(?:第\s*(\d{1,4})\s*[集期话回]|(?<![A-Za-z0-9])(?:EP|E)\s*(\d{1,4})(?![A-Za-z0-9]))", re.I)

#: 纯数字：`17` / `017`
PURE_NUM_PAT = re.compile(r"^\d{1,4}$")

#: 点分数字：`1.1.0` / `2.1`
DOT_NUM_PAT = re.compile(r"^(\d{1,3})(?:[.\-_](\d{1,3}))+$")

#: 项目名 + 尾随集数：`法老2` / `法老-12` / `法老_3`
NAME_EP_PAT = re.compile(r"^(.*?[\u4e00-\u9fffA-Za-z])[\s_\-]*(\d{1,4})$")

#: 需要从项目名候选里剔除的修饰词（尾部/整体）
NOISE_WORDS = ("待混音", "待剪辑", "成片", "定稿", "终稿", "粗剪", "精剪",
               "final", "FINAL", "mix", "MIX", "导出", "输出", "副本", "copy")

#: 常见视频扩展名（解析前先剥掉）
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".ts",
              ".m4v", ".mpg", ".mpeg", ".webm")


@dataclass
class VideoNameInfo:
    """一个视频名解析后的结果。

    | 字段 | 含义 |
    |---|---|
    | `raw` | 原始素材名（已剥扩展名） |
    | `project` | 项目名；空 = 需要人类补 |
    | `ep` | 集数（纯数字字符串，未补零） |
    | `seq` | 编号（点分数字的最后一段） |
    | `aifx` | 名称里带 AiFX 标记 |
    | `need_input` | 是否需要人类补项目名 |
    | `reason` | 为什么要人类补（用于弹窗提示） |
    | `suggest` | 建议项目名（人类可直接回车采纳） |
    """
    raw: str
    project: str = ""
    ep: str = ""
    seq: str = ""
    aifx: bool = False
    need_input: bool = False
    reason: str = ""
    suggest: str = ""
    explicit_ep: bool = False   # 集数来自显式写法（第N集 / EP N），而非尾随数字

    @property
    def label(self) -> str:
        """用于分包文件夹 / 文件名的显示名：`项目+集数`（缺什么补什么）。"""
        parts = [p for p in (self.project, self.ep) if p]
        if parts:
            out = "".join(parts) if self.ep and self.project else "".join(parts)
            return out
        return self.raw

    def as_fields(self) -> Dict[str, str]:
        """给命名模板用的字段字典。"""
        return {
            "视频项目": self.project or self.raw,
            "集数": self.ep,
            "编号": self.seq,
            "AiFX": "AiFX" if self.aifx else "",
            "视频名": self.raw,
        }


def strip_ext(name: str) -> str:
    """剥掉扩展名（只剥已知视频扩展名，避免误伤 `1.1.0` 这类名字）。"""
    s = (name or "").strip()
    low = s.lower()
    for ext in VIDEO_EXTS:
        if low.endswith(ext):
            return s[: -len(ext)].strip()
    return s


def _clean_project(cand: str) -> str:
    """清洗项目名候选：去修饰词、去首尾标点空白。"""
    s = (cand or "").strip()
    for w in NOISE_WORDS:
        # 只去**整体尾部**出现的修饰词，避免把项目名本身切坏
        if s.endswith(w) and len(s) > len(w):
            s = s[: -len(w)].strip()
    s = s.strip(" \t-_（）()[]【】")
    return s


def _suggest_abbrev(project: str) -> str:
    """项目名过长时给一个缩写建议：中文取前 2 字，英文取首字母大写。"""
    s = (project or "").strip()
    if not s:
        return ""
    if re.search(r"[\u4e00-\u9fff]", s):
        return s[:2]
    # 英文：按空格/连字符取各段首字母
    parts = [p for p in re.split(r"[\s_\-]+", s) if p]
    if len(parts) > 1:
        return "".join(p[0].upper() for p in parts)
    return s[:4].upper()


def parse_video_name(name: str) -> VideoNameInfo:
    """解析单个视频名。

    判定顺序（先具体后宽泛）：
      1. `第10集` / `EP10` 显式集数 → 其余文字为项目名候选
      2. 点分数字 `1.1.0` → 集数=首段、编号=末段，项目名缺失
      3. 纯数字 `17` → 集数=17，项目名缺失
      4. `法老2` → 项目名=法老、集数=2
      5. 其余 → 整串当项目名候选
    """
    raw = strip_ext(name)
    info = VideoNameInfo(raw=raw)
    info.aifx = bool(AIFX_PAT.search(raw))

    # AiFX 标记不参与项目名（如 `法老2_AiFX`）
    body = AIFX_PAT.sub("", raw).strip(" \t-_")

    # ① 显式集数
    m = EP_PAT.search(body)
    if m:
        info.ep = str(int(m.group(1) or m.group(2)))
        info.explicit_ep = True
        rest = (body[: m.start()] + body[m.end():]).strip()
        proj = _clean_project(rest)
    else:
        proj = ""

    if not info.ep:
        # ② 点分数字
        m2 = DOT_NUM_PAT.match(body)
        if m2:
            nums = re.findall(r"\d{1,3}", body)
            info.ep = str(int(nums[0])) if nums else ""
            info.seq = str(int(nums[-1])) if len(nums) > 1 else ""
            proj = ""
        else:
            # ③ 纯数字
            if PURE_NUM_PAT.match(body):
                info.ep = str(int(body))
                proj = ""
            else:
                # ④ 项目名 + 尾随集数
                m4 = NAME_EP_PAT.match(body)
                if m4:
                    proj = _clean_project(m4.group(1))
                    info.ep = str(int(m4.group(2)))
                else:
                    # ⑤ 整串当项目名
                    proj = _clean_project(body)

    # 项目名过长 → 要求人类缩写（建议值给出，回车即采纳）
    if proj and len(proj) > MAX_PROJECT_LEN:
        info.project = ""
        info.need_input = True
        info.suggest = _suggest_abbrev(proj)
        info.reason = "项目名 %d 字（>%d），请给个缩写" % (len(proj), MAX_PROJECT_LEN)
        return info

    if proj:
        info.project = proj
        return info

    # 走到这里：项目名为空 → 需要人类补
    info.need_input = True
    if not info.ep:
        info.reason = "无法从视频名判断项目，请补项目名"
    elif info.seq:
        info.reason = "只有编号式数字（如 集.编号），缺项目信息"
    elif info.explicit_ep:
        info.reason = "只写了集数（如 EP05 / 第5集），缺项目信息"
    else:
        info.reason = "纯数字视频名，通常是集数但缺项目信息"
    return info


def parse_many(names: List[str]) -> List[VideoNameInfo]:
    """批量解析（保持输入顺序）。"""
    return [parse_video_name(n) for n in names]


def pending_map(infos: List[VideoNameInfo]) -> Dict[str, VideoNameInfo]:
    """待补项目名的**去重清单**：同一原始名只需补一次。

    返回 `{原始名: VideoNameInfo}`，UI 按此弹一次窗，填完应用到所有同名项。
    """
    out: Dict[str, VideoNameInfo] = {}
    for i in infos:
        if i.need_input:
            out.setdefault(i.raw, i)
    return out


def _lookup(answers: Dict[str, str], raw: str) -> str:
    """答案查找：**扩展名无关**。

    剪映素材名有的带 `.mp4`、有的不带（`3.mp4` vs `3`），而 `parse_video_name`
    一律先剥扩展名。若要求 key 一字不差，人类补录的答案会对不上（静默失效）。
    """
    if not answers:
        return ""
    if raw in answers:
        return answers[raw] or ""
    for k, v in answers.items():
        if strip_ext(k) == raw:
            return v or ""
    return ""


def apply_project(infos: List[VideoNameInfo], answers: Dict[str, str]) -> List[VideoNameInfo]:
    """把人类补的项目名回填；`answers = {原始名: 项目名}`（key 带不带扩展名都认）。

    返回**新列表**（不原地改），未补的保持 `need_input=True`。
    空答案视为「不补」，保持待定 —— 绝不静默用原始名兜底。
    """
    result = []
    for i in infos:
        ans = (_lookup(answers, i.raw) or "").strip()
        if i.need_input and ans:
            result.append(replace(i, project=ans, need_input=False, reason=""))
        else:
            result.append(i)
    return result


def suggest_project(infos: List[VideoNameInfo]) -> Optional[str]:
    """从**已解析出**的项目名里统计众数，给弹窗当默认值。"""
    from collections import Counter
    cnt = Counter(i.project for i in infos if i.project)
    return cnt.most_common(1)[0][0] if cnt else None
