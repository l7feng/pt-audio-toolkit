#!/usr/bin/env python3
"""
剪映批量导出音频脚本 — 通用版
扫描剪映草稿目录 → 解密草稿 JSON → 解析音频片段 → ffmpeg 切片转码 → 命名归档

技术路线：jy-draftc 解密（调用剪映自身 videoeditor.dll）+ JSON 解析 + ffmpeg
支持剪映 6.0+（加密草稿）与 5.x（明文草稿）自动识别

用法：
  python main.py --init          进入交互式初始化向导（配置输出目录等）
  python main.py                 直接运行（使用现有配置；未初始化则先进入向导）
  python main.py <草稿目录>      指定草稿目录运行
  python main.py --check         环境自检（Python/ffmpeg/剪映/jy-draftc）
"""

import json
import os
import re
import subprocess
import hashlib
import sys
import shutil
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ──────────────────── 配置 ────────────────────

# ── 版本号（2026-09-21 增加：标题栏可见，用于识别 exe 新旧）──
# 版本史：v1.0.0 基础导出 → v1.1.0 GUI+exe → v1.2.0 拖拽+整轨提取（09-17）
#        → v2.0.0 整轨+AAF+三标签页合并（09-18）→ v2.1.0 L0/L1 分层（09-18）
#        → v2.2.0 L0.5 黑窗+切页卡顿根治（09-19）
#        → v2.3.0 菜单栏（文件/设置/工具/帮助）+ 默认路径设置对话框（09-21）
APP_VERSION = "2.3.0"


def app_build_date() -> str:
    """构建日期：frozen 取 exe 文件时间（打包时刻），源码模式取本文件时间。

    目标：标题栏一眼识别新旧 —— 拿错旧版 exe 时日期会明显比固定资产旧。
    """
    try:
        # ⚠️ sys.executable 是 str，必须先 Path() 包一层再 .stat()
        # （曾写成 src.stat() 直接调用 → AttributeError 被 except 吞掉 →
        #  标题栏恒显示「未知」，版本号功能等于半废）
        src = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
        return datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d")
    except Exception:
        return "未知"


DEFAULT_JIANYING_DRAFT_ROOT = Path(os.environ.get(
    "LOCALAPPDATA",
    r"C:\Users\Administrator\AppData\Local"
)) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"

# ── 应用基目录（PyInstaller 冻结感知）──────────────────
# 源码模式：代码目录的父目录（包根，含 tools/）
# frozen 模式（打包为 exe）：exe 所在目录（可写的真实目录，config.json / tools/ 都在此）
def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

APP_DIR = _app_dir()
SCRIPT_DIR = Path(__file__).resolve().parent  # 源码目录

# ⚠️ 所有可变文件（配置 / 交付包）**一律写 APP_DIR**，不写代码目录。
# 原因：打包成 exe 后代码在 _internal/ 内部（PyInstaller 临时目录，只读且会被清理）；
# 即便源码模式，多标签页共用同一份 config.json 也需要一个稳定的落点。
# 老用户的历史配置在 code/config.json，首次运行会由 config_path() 自动迁移过来。
#
# 配置相关（常量 / 默认值 / 读写 / 向导）已收敛到 core/config.py（L1 分层）。
# APP_DIR 的 frozen 判定仍以本文件的 _app_dir() 为单一真相源，通过 set_app_dir 注入。
from core import config as _cfg
_cfg.set_app_dir(APP_DIR)

# 兼容旧引用：原 main.py 内的模块级名字继续可用（CLI / GUI / tab 行为不变）
from core.config import (              # noqa: E402
    DEFAULT_CONFIG, DEFAULT_IMPORT_CONFIG, CONFIG_FIELDS,
    CONFIG_PATH, LEGACY_CONFIG_PATH,
    DEFAULT_TRACK_TEMPLATE, DEFAULT_SPEC_KEY,
    config_path, load_config, save_config, ask, parse_bool, init_config,
)

# jy-draftc 定位：优先包内 tools/，命中前先看 exe 旁（onedir 打包时 tools/ 在 exe 同级）
def find_jy_draftc() -> Optional[Path]:
    """定位 jy-draftc.exe。

    候选顺序（先命中先用）：
      1. APP_DIR/tools/jy-draftc/jy-draftc-amd64-windows/jy-draftc.exe   ← 标准布局
      2. `tools/jy-draftc/jy-draftc.exe`                                 ← 解压时少一层目录
      3. `tools/jy-draftc.exe`
      4. `jy-draftc.exe`（与 exe 同级）
    这样无论用户是「整个文件夹搬」还是「手动解压少了层目录」都能找到。
    """
    base = APP_DIR / "tools" / "jy-draftc"
    cands = [
        base / "jy-draftc-amd64-windows" / "jy-draftc.exe",
        base / "jy-draftc.exe",
        APP_DIR / "tools" / "jy-draftc.exe",
        APP_DIR / "jy-draftc.exe",
    ]
    for c in cands:
        if c.is_file():
            return c
    return cands[0]                  # 都没找到时返回标准路径（报错信息更有指向性）

# 兼容旧引用（模块级常量在 import 时求值，进程内 tools/ 不会中途变化）
JY_DRAFTC_EXE = find_jy_draftc()
JY_DRAFTC_ENV = JY_DRAFTC_EXE.parent / ".env"


# config_path() 已移至 core/config.py（见上方 import）

# 素材类型 → 归档分类（music / voice / sfx / audio）
TYPE_CATEGORY = {
    "audio": "audio",                    # 通用音频
    "voice": "voice",                    # 朗读/配音
    "music": "music",                    # 音乐
    "sfx": "sfx",                        # 音效
    "video": "audio",                    # 视频内嵌音轨 → audio
    "video_original_sound": "voice",     # 视频原声（分离到独立音轨的干声/人声）→ voice
}

# 文件名非法字符与长度限制
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
MAX_FILENAME_LEN = 180

# 媒体文件扩展名（拖入文件 / 文件夹递归时识别）
MEDIA_EXTS = {
    ".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".rmvb",
    ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".ape",
}
# 剪映草稿标志文件（含其一即视为草稿文件夹）
DRAFT_MARKERS = ("draft_content.json", "draft_info.json", "draft_meta_info.json")


def find_jianying_install_dir() -> Optional[Path]:
    """自动定位剪映安装目录（含 videoeditor.dll 的 Apps/<version>/ 目录）"""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "JianyingPro" / "Apps"
    if not base.exists():
        return None
    versions = sorted(base.iterdir(), reverse=True)  # 最新版本优先
    for v in versions:
        if (v / "videoeditor.dll").exists():
            return v
    return None


# ──────────────────── Scanner ────────────────────

def read_main_timeline_id(draft_dir: Path) -> Optional[str]:
    """读取草稿的主时间线 ID。

    剪映 6.x 草稿是「多时间线」结构，`Timelines/project.json` 是**明文** JSON，
    其中的 `main_timeline_id` 指向剪映实际使用的那条时间线。
    """
    p = draft_dir / "Timelines" / "project.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    tid = d.get("main_timeline_id")
    if not tid:
        # 回退：取 timelines 列表里第一条
        tls = d.get("timelines") or []
        if tls and isinstance(tls[0], dict):
            tid = tls[0].get("id")
    return tid or None


def resolve_draft_content_file(draft_dir: Path) -> Path:
    """定位草稿的「权威内容文件」——即剪映**实际读取**的那份 draft_content.json。

    ⚠️ 背景（2026-09-17 实测踩坑）：剪映 6.x 草稿有两份 draft_content.json：
      - `<草稿>/draft_content.json`                    —— 会话快照，剪映**不以此为准**
      - `<草稿>/Timelines/<main_timeline_id>/draft_content.json` —— **权威源**

    剪映 load/save 时会用时间线那份回写覆盖根目录那份。写入方若只写根目录文件，
    剪映读不到任何改动（这正是「导入了但剪映里看不到」的根本原因）。
    导出侧同理：只读根目录在「剪映未正常同步」场景下会拿到旧内容。

    无 `Timelines/` 结构时（旧版草稿）回退根目录。
    """
    tid = read_main_timeline_id(draft_dir)
    if tid:
        p = draft_dir / "Timelines" / tid / "draft_content.json"
        if p.is_file():
            return p
    return draft_dir / "draft_content.json"


def scan_drafts(root: Path) -> List[Path]:
    """扫描草稿根目录，返回草稿文件夹列表（已排除 Timelines/<uuid> 嵌套目录）"""
    if not root.exists():
        print(f"[scanner] 草稿目录不存在: {root}")
        return []
    drafts = [e for e in root.iterdir() if is_draft_dir(e)]
    print(f"[scanner] 找到 {len(drafts)} 个草稿")
    return sorted(drafts)


_UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")


def _looks_like_uuid(name: str) -> bool:
    return bool(_UUID_RE.match(name))


def is_draft_dir(path: Path) -> bool:
    """目录是否为剪映草稿文件夹。

    剪映草稿目录下还会嵌套 Timelines/<uuid>/ 子目录，里面同样有 draft_content.json，
    但它们不是独立草稿（是同一草稿的多时间线备份），**必须排除**，否则会重复计数。
    """
    if not path.is_dir():
        return False
    if path.parent.name == "Timelines":          # 明确排除多时间线子目录
        return False
    if not any((path / m).exists() for m in DRAFT_MARKERS):
        return False
    if (path / "draft_meta_info.json").exists():
        return True
    # 兜底：目录名不形如 UUID 的才算草稿
    return not _looks_like_uuid(path.name)


def is_draft_json(path: Path) -> bool:
    """文件是否为剪映草稿 JSON（加密的 draft_content.json / 解密产物 / .jane 工程）"""
    if not path.is_file():
        return False
    if path.suffix.lower() == ".jane":
        return True
    return path.name in (
        "draft_content.json", "draft_info.json",
        "draft_content.json.dec.json", "draft_info.json.dec.json",
    )


def media_kind(path: Path) -> str:
    """媒体文件类型：video / audio / ""（非媒体）"""
    ext = path.suffix.lower()
    if ext not in MEDIA_EXTS:
        return ""
    return "audio" if ext in {
        ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".ape",
    } else "video"


def resolve_input_paths(paths: List[Path]) -> Tuple[List[Path], Path, bool]:
    """把「用户拖入的文件夹/文件混合列表」解析为可导出输入。

    返回 (草稿目录列表, 草稿根, 是否纯文件模式)。

    规则（智能识别）：
    - 拖入文件夹：递归查找其中所有草稿文件夹（含 draft_content.json）；
      若一个都没找到，则退回「递归找媒体文件」模式，把该文件夹下的音视频当作直接输入。
    - 拖入文件：草稿 JSON / .jane → 其所在目录即一个草稿；音视频 → 作为直接输入文件。
    """
    draft_dirs: List[Path] = []
    media_files: List[Path] = []
    seen: set = set()

    def add_draft(d: Path):
        d = d.resolve()
        if d not in seen:
            seen.add(d)
            draft_dirs.append(d)

    def add_media(f: Path):
        f = f.resolve()
        if f not in seen:
            seen.add(f)
            media_files.append(f)

    for p in paths:
        p = Path(p)
        if not p.exists():
            print(f"[input] ✗ 路径不存在，已忽略: {p}")
            continue

        if p.is_dir():
            if is_draft_dir(p):                       # 本身就指向一个草稿
                add_draft(p)
                continue
            # 递归找草稿（草稿可嵌套在子目录）
            found = [d for d in p.rglob("*") if is_draft_dir(d)]
            if found:
                for d in found:
                    add_draft(d)
            else:                                     # 无草稿 → 当普通媒体文件夹
                print(f"[input] 目录内未发现剪映草稿，按媒体文件夹处理: {p}")
                for f in p.rglob("*"):
                    if f.is_file() and media_kind(f):
                        add_media(f)

        elif is_draft_json(p):                        # 拖入单个草稿 JSON
            add_draft(p.parent)
        elif media_kind(p):                           # 拖入音视频文件
            add_media(p)
        else:
            print(f"[input] ⏭ 不支持的文件类型，已忽略: {p.name}")

    if draft_dirs:
        # 用公共父目录作为「草稿根」（仅用于日志展示）
        try:
            common = Path(os.path.commonpath([str(d) for d in draft_dirs]))
        except ValueError:
            common = draft_dirs[0]
        for d in draft_dirs:
            print(f"[input] 草稿: {d}")
        for f in media_files:
            print(f"[input] 媒体文件: {f}")
        return draft_dirs, common, False

    if media_files:
        print(f"[input] 未识别到草稿，直接处理 {len(media_files)} 个媒体文件")
        return [], Path("."), True

    print("[input] ✗ 未识别到任何可导出的草稿或媒体文件")
    return [], Path("."), False


# ──────────────────── Decrypter ────────────────────

def is_encrypted_json(path: Path) -> bool:
    """判断 JSON 文件是否为加密格式（不以 { 开头）"""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        return head[0:1] != b"{"
    except Exception:
        return False


def find_videoeditor_dll() -> Optional[Path]:
    """定位 videoeditor.dll 文件路径"""
    install_dir = find_jianying_install_dir()
    if install_dir is None:
        return None
    return install_dir / "videoeditor.dll"


def ensure_jy_draftc_env():
    """确保 jy-draftc 的 .env 文件配置了 JY_INSTALL_DIR"""
    install_dir = find_jianying_install_dir()
    if install_dir is None:
        raise RuntimeError("未找到剪映安装目录（videoeditor.dll），请确认剪映已安装")
    env_content = f"JY_INSTALL_DIR={install_dir}"
    JY_DRAFTC_ENV.write_text(env_content, encoding="utf-8")
    print(f"[decrypter] 配置 videoeditor.dll 路径: {install_dir}")
    return install_dir


def decrypt_draft_file(draft_file: Path) -> Path:
    """调用 jy-draftc 解密单个草稿 JSON 文件，返回解密后的文件路径"""
    if not is_encrypted_json(draft_file):
        # 已是明文 JSON，直接返回原文件
        return draft_file

    if not JY_DRAFTC_EXE.exists():
        raise RuntimeError(f"jy-draftc 未找到: {JY_DRAFTC_EXE}")

    ensure_jy_draftc_env()

    result = subprocess.run(
        [str(JY_DRAFTC_EXE), "-d", str(draft_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60, **subprocess_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"jy-draftc 解密失败: {result.stderr}")

    output = draft_file.parent / f"{draft_file.name}.dec.json"
    if not output.exists():
        raise RuntimeError(f"解密输出文件不存在: {output}")
    return output


# ──────────────────── Parser ────────────────────

@dataclass
class AudioSegment:
    """音频片段信息"""
    project: str           # 草稿名称
    track_type: str        # audio / voice / video（内嵌音轨）
    source_path: str       # 源文件本地路径
    start_us: int          # 起始时间（微秒）
    end_us: int            # 结束时间（微秒）
    material_name: str     # 素材文件名
    material_id: str       # 素材 ID

    @property
    def duration_s(self) -> float:
        return (self.end_us - self.start_us) / 1_000_000


def parse_draft_json(draft_dir: Path, json_path: Path, extract_video_tracks: bool = True) -> List[AudioSegment]:
    """解析解密后的 draft_content.json，提取音频片段清单"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    project_name = draft_dir.name
    segments: List[AudioSegment] = []

    # 构建素材 ID → 素材信息 映射
    materials_map = {}
    for category in ("videos", "audios", "texts"):
        for mat in data.get("materials", {}).get(category, []):
            materials_map[mat["id"]] = mat

    # 遍历所有轨道
    for track in data.get("tracks", []):
        track_type = track.get("type", "")

        # 音频轨道：直接是音频
        if track_type in ("audio",):
            for seg in track.get("segments", []):
                mat_id = seg.get("material_id", "")
                mat = materials_map.get(mat_id, {})
                source_path = mat.get("path", "")
                mat_name = mat.get("material_name", Path(source_path).stem if source_path else "")
                # 用 source_timerange（素材原始时间码）切片，target 为时间线位置
                time_range = seg.get("source_timerange", seg.get("target_timerange", {}))
                start = time_range.get("start", 0)
                end = start + time_range.get("duration", 0)
                segments.append(AudioSegment(
                    project=project_name,
                    track_type=mat.get("type", "audio"),
                    source_path=source_path,
                    start_us=start,
                    end_us=end,
                    material_name=mat_name,
                    material_id=mat_id,
                ))

        # 视频轨道：从视频中提取内嵌音轨（方案扩展场景）
        elif track_type == "video" and extract_video_tracks:
            for seg in track.get("segments", []):
                mat_id = seg.get("material_id", "")
                mat = materials_map.get(mat_id, {})
                source_path = mat.get("path", "")
                if not source_path:
                    continue
                mat_name = mat.get("material_name", Path(source_path).stem if source_path else "")
                # 用 source_timerange（素材原始时间码）切片，target 为时间线位置
                time_range = seg.get("source_timerange", seg.get("target_timerange", {}))
                start = time_range.get("start", 0)
                end = start + time_range.get("duration", 0)
                segments.append(AudioSegment(
                    project=project_name,
                    track_type="video",  # 标记为视频内嵌音轨
                    source_path=source_path,
                    start_us=start,
                    end_us=end,
                    material_name=mat_name,
                    material_id=mat_id,
                ))

    # 音轨段优先于视频内嵌音轨（去重覆盖判定依赖注册顺序）
    segments.sort(key=lambda s: 1 if s.track_type == "video" else 0)

    return segments


# ──────────────────── 整轨（Track）模型 ────────────────────
# 为什么需要整轨：片段模式把每段音频单独导出（4s、5s…一堆短文件），
# 导入 PT 后全部堆在 0s，要手动摆位 N 次。整轨模式一条轨只出一个文件，
# 长度 = 视频长度，空白补真静音 → 所有轨天然对齐，拖进 PT 即可用。

#: 整轨输出规格预设：key → (界面标签, 采样率, 位深, 声道)，None = 跟随素材
SPEC_PRESETS = {
    "keep":       ("保持素材原始规格",  None,   None, None),
    "48k24b_st":  ("48k/24bit 立体声", 48000,    24,    2),
    "48k24b_mo":  ("48k/24bit 单声道", 48000,    24,    1),
    "44k16b_st":  ("44.1k/16bit 立体声", 44100,  16,    2),
    "48k16b_st":  ("48k/16bit 立体声", 48000,    16,    2),
}
# DEFAULT_SPEC_KEY 已移至 core/config.py（见顶部 import）

#: 位深 → WAV PCM 编码器
PCM_CODEC = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}

# DEFAULT_TRACK_TEMPLATE 已移至 core/config.py（见顶部 import）


@dataclass
class TrackSegment:
    """整轨视角的片段：**同时**保留取材区间与时间线落点。

    | 字段 | 来自 | 含义 |
    |---|---|---|
    | `src_start_us` / `src_dur_us` | `source_timerange` | 从源文件第几微秒取、取多长 |
    | `tl_start_us` / `tl_dur_us`   | `target_timerange` | 落在时间线第几微秒、占多长 |

    片段模式只读了前者、丢了后者 —— 这就是「位置信息丢失」的根因。
    """
    source_path: str
    material_name: str
    material_id: str
    src_start_us: int = 0
    src_dur_us: int = 0
    tl_start_us: int = 0
    tl_dur_us: int = 0


@dataclass
class AudioTrack:
    """一条剪映轨道（audio，或开启后的 video 内嵌音轨）"""
    project: str
    name: str
    index: int
    source_kind: str                       # audio / video
    segments: List[TrackSegment]

    @property
    def display_name(self) -> str:
        """轨道名（剪映里叫什么就叫什么；无名时退化 Track N）"""
        return self.name or f"Track {self.index}"

    @property
    def end_us(self) -> int:
        return max((s.tl_start_us + s.tl_dur_us) for s in self.segments) if self.segments else 0


def _range_us(tr) -> Tuple[int, int]:
    """从 timerange dict 取 (start, duration)，单位微秒；缺字段退化 0"""
    if not isinstance(tr, dict):
        return 0, 0
    return int(tr.get("start", 0) or 0), int(tr.get("duration", 0) or 0)


def parse_draft_tracks(draft_dir: Path, json_path: Path,
                       extract_video_tracks: bool = True) -> Tuple[List[AudioTrack], int]:
    """把草稿解析为「轨道视图」。

    返回 (轨道列表, 时间线总长微秒)。与 `parse_draft_json` 的差别就是
    **读取 target_timerange**，位置信息得以保留。
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    project_name = draft_dir.name
    materials_map = {}
    for category in ("videos", "audios", "texts"):
        for mat in data.get("materials", {}).get(category, []):
            materials_map[mat["id"]] = mat

    tracks: List[AudioTrack] = []
    idx = 0
    for track in data.get("tracks", []):
        ttype = track.get("type", "")
        if ttype == "audio":
            kind = "audio"
        elif ttype == "video" and extract_video_tracks:
            kind = "video"
        else:
            continue

        idx += 1
        segs: List[TrackSegment] = []
        for seg in track.get("segments", []) or []:
            mat = materials_map.get(seg.get("material_id", ""), {})
            src_path = mat.get("path", "")
            if not src_path:
                continue
            s_start, s_dur = _range_us(seg.get("source_timerange"))
            t_start, t_dur = _range_us(seg.get("target_timerange"))
            if t_dur <= 0:
                t_dur = s_dur                    # 无落点信息时退化为取材长度
            if s_dur <= 0:
                s_dur = t_dur
            segs.append(TrackSegment(
                source_path=src_path,
                material_name=mat.get("material_name") or Path(src_path).stem,
                material_id=seg.get("material_id", ""),
                src_start_us=s_start,
                src_dur_us=s_dur,
                tl_start_us=t_start,
                tl_dur_us=t_dur,
            ))
        if not segs:
            continue
        segs.sort(key=lambda s: s.tl_start_us)
        tracks.append(AudioTrack(
            project=project_name,
            name=(track.get("name") or "").strip(),
            index=idx,
            source_kind=kind,
            segments=segs,
        ))

    return tracks, resolve_timeline_length_us(data, tracks)


def resolve_timeline_length_us(data: dict, tracks: List[AudioTrack]) -> int:
    """时间线总长（微秒）—— **跟随视频轨**最后一个片段的结束点。

    基准为什么是视频轨：整轨的意义是「所有轨等长、天然对齐」，
    决定成片长度的永远是画面。无视频轨时退化用音频轨最远结束点，
    再退化用草稿 `duration` 字段。
    """
    video_end = audio_end = 0
    for t in tracks:
        end = t.end_us
        if t.source_kind == "video":
            video_end = max(video_end, end)
        else:
            audio_end = max(audio_end, end)
    if video_end > 0:
        return video_end
    if audio_end > 0:
        return audio_end
    return int(data.get("duration", 0) or 0)


def probe_audio_spec(path: Path) -> Tuple[int, int, int]:
    """ffprobe 读音频流规格 → (采样率, 声道数, 位深)；失败退回 (48000, 2, 16)"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=sample_rate,channels,bits_per_raw_sample",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, **subprocess_kwargs(),)
        if r.returncode == 0 and r.stdout.strip():
            line = r.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            sr = int(float(parts[0])) if parts and parts[0] else 48000
            ch = int(parts[1]) if len(parts) > 1 and parts[1] else 2
            bits = int(parts[2]) if len(parts) > 2 and parts[2] else 16
            return sr, max(ch, 1), bits
    except Exception:
        pass
    return 48000, 2, 16


def resolve_spec(spec_key: str, segments: List[TrackSegment]) -> Tuple[int, int, int]:
    """把规格预设解析为具体 (采样率, 位深, 声道)；`keep` 取首个可用素材的规格。"""
    label, sr, bits, ch = SPEC_PRESETS.get(spec_key, SPEC_PRESETS[DEFAULT_SPEC_KEY])
    base_sr, base_ch, base_bits = 48000, 2, 16
    for s in segments:
        p = Path(s.source_path)
        if p.exists():
            base_sr, base_ch, base_bits = probe_audio_spec(p)
            break
    return (sr or base_sr), (bits or base_bits), (ch or base_ch)


def render_track_name(template: str, project: str, track_name: str,
                      index: int, duration_s: float, remarks: str = "") -> str:
    """整轨命名：额外提供 {轨道名} 字段（片段模式没有这个概念）"""
    import datetime
    fields = {
        "项目名": project,
        "轨道名": track_name,
        "序号": index,
        "日期": datetime.date.today().strftime("%Y%m%d"),
        "时长": int(duration_s),
        "备注": remarks,
    }
    try:
        return sanitize_filename(template.format(**fields))
    except KeyError as e:
        key = e.args[0] if e.args else str(e)
        logging.warning(f"[namer] 模板含有未知字段 {{{key}}}，已忽略")
        return sanitize_filename(template.replace("{" + key + "}", ""))


def extract_track_audio(track: AudioTrack, total_us: int, output_file: Path,
                        spec_key: str = DEFAULT_SPEC_KEY, log=print) -> bool:
    """把一条轨道渲染成**整轨 WAV**：片段按时间线落点摆放，空白补真静音。

    ffmpeg 一次调用成型（无中间文件）：
        每段 → atrim(取材区间) → asetpts → aformat → adelay(落点) → apad → atrim(总长)
        多段 → amix(normalize=0) 求和（同一轨的片段本就不重叠，求和等价拼接）
    空白段是**全零采样**（volumedetect ≈ -91dB 数字静音），不是"没有音频"。
    """
    segs = [s for s in track.segments if s.tl_dur_us > 0]
    missing = [s for s in segs if not Path(s.source_path).exists()]
    for s in missing:
        log(f"  [warn] 源文件不存在，该片段留静音: {Path(s.source_path).name}")
    segs = [s for s in segs if Path(s.source_path).exists()]
    if not segs:
        log("  ✗ 该轨道所有片段源文件均缺失")
        return False

    sr, bits, ch = resolve_spec(spec_key, segs)
    total_s = total_us / 1e6
    if total_s <= 0:
        total_s = track.end_us / 1e6
    if total_s <= 0:
        return False

    layout = "stereo" if ch >= 2 else "mono"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for s in segs:
        cmd += ["-i", str(Path(s.source_path))]

    chains, labels = [], []
    for i, s in enumerate(segs):
        delay_ms = max(int(round(s.tl_start_us / 1000)), 0)
        src_s = s.src_start_us / 1e6
        dur_s = s.src_dur_us / 1e6
        delays = "|".join([str(delay_ms)] * ch)
        chains.append(
            f"[{i}:a]atrim=start={src_s:.6f}:duration={dur_s:.6f},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates={sr}:channel_layouts={layout},"
            f"adelay={delays},apad,atrim=0:{total_s:.6f}[s{i}]"
        )
        labels.append(f"[s{i}]")

    if len(segs) == 1:
        chains.append(f"{labels[0]}anull[out]")
    else:
        chains.append("".join(labels) +
                      f"amix=inputs={len(segs)}:duration=longest:normalize=0,"
                      f"apad,atrim=0:{total_s:.6f}[out]")

    cmd += ["-filter_complex", ";".join(chains), "-map", "[out]",
            "-ar", str(sr), "-ac", str(ch),
            "-c:a", PCM_CODEC.get(bits, "pcm_s16le"), str(output_file)]

    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800, **subprocess_kwargs(),)
    if r.returncode != 0:
        log(f"  ✗ ffmpeg 整轨失败: {(r.stderr or '').strip()[-300:]}")
        return False
    return True


# ──────────────────── Extractor（ffmpeg）────────────────────

def extract_audio(seg: AudioSegment, output_file: Path, audio_format: str = "mp3", bitrate_kbps: int = 192) -> bool:
    """用 ffmpeg 从源文件按时间码切片转码为音频"""
    src = Path(seg.source_path)
    if not src.exists():
        print(f"  [extractor] ✗ 源文件不存在: {src}")
        return False

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if seg.start_us > 0:
        cmd += ["-ss", f"{seg.start_us / 1e6:.3f}"]
    cmd += ["-i", str(src)]
    if seg.end_us > seg.start_us:
        cmd += ["-t", f"{(seg.end_us - seg.start_us) / 1e6:.3f}"]

    if audio_format == "mp3":
        cmd += ["-ac", "2", "-b:a", f"{bitrate_kbps}k", "-ar", "44100", str(output_file)]
    else:  # wav
        cmd += ["-ac", "2", "-ar", "44100", str(output_file)]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, **subprocess_kwargs(),)
    return result.returncode == 0


# ──────────────────── Namer ────────────────────

def sanitize_filename(name: str) -> str:
    """替换非法字符并截断超长文件名"""
    name = ILLEGAL_CHARS.sub("_", name)
    name = name.strip().strip(".")
    if len(name) > MAX_FILENAME_LEN:
        name = name[:MAX_FILENAME_LEN]
    return name


def render_name(template: str, seg: AudioSegment, seq_index: int, remarks: str = "") -> str:
    """按命名模板渲染目标文件名（不含扩展名）"""
    import datetime
    fields = {
        "项目名": seg.project,
        "素材类型": TYPE_CATEGORY.get(seg.track_type, "audio"),
        "序号": seq_index,
        "原始名": Path(seg.material_name).stem if seg.material_name else Path(seg.source_path).stem,
        "日期": datetime.date.today().strftime("%Y%m%d"),
        "时长": int(seg.duration_s),
        "备注": remarks,
    }
    try:
        return sanitize_filename(template.format(**fields))
    except KeyError as e:
        key = e.args[0] if e.args else str(e)
        logging.warning(f"[namer] 模板含有未知字段 {{{key}}}，已忽略")
        return sanitize_filename(template.replace("{" + key + "}", ""))


# ──────────────────── Archiver ────────────────────

def resolve_conflict(output_file: Path, conflict: str = "rename") -> Optional[Path]:
    """处理文件重名冲突：cover 覆盖 / skip 跳过 / rename 追加 -1 -2"""
    if conflict == "cover" or not output_file.exists():
        return output_file
    if conflict == "skip":
        return None
    # rename：追加 -1、-2 后缀
    i = 1
    while True:
        candidate = output_file.with_name(f"{output_file.stem}-{i}{output_file.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _intervals_cover(query_s: int, query_e: int, intervals: List[Tuple[int, int]]) -> bool:
    """判断 query 区间 [query_s, query_e) 是否被已注册区间的并集完整覆盖"""
    if not intervals:
        return False
    cursor = query_s  # 当前最左需被覆盖的起点
    for s, e in sorted(intervals):
        if e <= cursor:
            continue       # 完全在光标左侧，无贡献
        if s > cursor:
            return False   # 起点前有空隙，无法完整覆盖
        cursor = max(cursor, e)
        if cursor >= query_e:
            return True
    return False


def dedupe_check(source_path: str, start_us: int, end_us: int, seen_intervals: dict) -> Optional[str]:
    """按源文件内容 + 时间区间的并集去重。

    同一文件的多个不同切片各自注册；新区间若被已注册区间的并集完整覆盖
    （如 video 整段 0~176.5s 覆盖音轨的两个分片），则判为重复返回代表名。
    """
    try:
        with open(source_path, "rb") as f:
            h = hashlib.sha256(f.read(4096)).hexdigest()
    except Exception:
        return None
    intervals = seen_intervals.setdefault(h, [])
    if _intervals_cover(start_us, end_us, intervals):
        return f"{Path(source_path).name} (已含同源切片)"
    intervals.append((start_us, end_us))
    return None


# ──────────────────── Logger ────────────────────

def setup_logger(log_file: Path):
    # 先清理旧 handler（GUI 多次导出等场景避免日志重复挂载）
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
        filemode="w",
    )
    # 同时输出到控制台
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.getLogger().addHandler(console)


# ──────────────────── Main ────────────────────

def process_draft(draft_dir: Path, cfg: dict, temp_dir: Path, seen_ids: dict, stats: dict):
    """处理单个草稿：解密 → 解析 → 提取 → 归档"""
    # 优先读剪映实际使用的那份（Timelines/<main_timeline_id>/），
    # 而非根目录的会话快照 —— 见 resolve_draft_content_file 的说明。
    raw_file = resolve_draft_content_file(draft_dir)
    print(f"\n[process] 草稿: {draft_dir.name}")
    if raw_file.parent != draft_dir:
        print(f"  [info] 内容源: {raw_file.relative_to(draft_dir)}")

    try:
        decrypted = decrypt_draft_file(raw_file)
        segments = parse_draft_json(draft_dir, decrypted, cfg.get("extract_video_tracks", True))
        print(f"  → 解析到 {len(segments)} 个音频片段")
    except Exception as e:
        print(f"  ✗ 草稿解析失败: {e}")
        logging.error(f"草稿 {draft_dir.name} 解析失败: {e}")
        stats["failed"] += 1
        return

    conflict = cfg.get("conflict", "rename")
    audio_format = cfg.get("audio_format", "mp3")
    bitrate = cfg.get("bitrate_kbps", 192)
    template = cfg.get("name_template", "{项目名}_{素材类型}_{序号:03d}_{原始名}")
    remarks = cfg.get("remarks", "")

    for i, seg in enumerate(segments, 1):
        try:
            # 源文件存在性
            src = Path(seg.source_path)
            if not src.exists():
                # 尝试在草稿目录/输入目录下递归搜索同名文件
                print(f"  [warn] 源文件不存在，尝试重建路径: {src.name}")
                found = find_source_file(seg, draft_dir)
                if found is None:
                    print(f"  ⏭ 跳过（找不到源文件）: {src.name}")
                    logging.warning(f"[SKIP] 源文件缺失: {src}")
                    stats["skipped"] += 1
                    continue
                seg.source_path = str(found)

            # 去重（键 = 文件内容 + 时间切片）
            if cfg.get("dedupe", True):
                dup = dedupe_check(seg.source_path, seg.start_us, seg.end_us, seen_ids)
                if dup:
                    print(f"  ⏭ 去重跳过（与 {dup} 重复）: {seg.material_name}")
                    stats["skipped"] += 1
                    continue

            # 命名与归档
            base_name = render_name(template, seg, i, remarks)
            category = TYPE_CATEGORY.get(seg.track_type, "audio")
            category_dir = Path(cfg.get("output_dir", "D:/导出音频")) / category
            category_dir.mkdir(parents=True, exist_ok=True)

            out_file = category_dir / f"{base_name}.{audio_format}"
            resolved = resolve_conflict(out_file, conflict)
            if resolved is None:
                print(f"  ⏭ 跳过（已存在）: {out_file.name}")
                stats["skipped"] += 1
                continue

            # ffmpeg 提取到临时文件再原子移动到归档位置
            temp_file = temp_dir / f"tmp_{i}_{base_name}.{audio_format}"
            if extract_audio(seg, temp_file, audio_format, bitrate):
                temp_file.replace(resolved)
                print(f"  ✓ 导出: {category}/{resolved.name} ({seg.duration_s:.1f}s)")
                logging.info(f"[OK] {draft_dir.name} → {category}/{resolved.name}")
                stats["success"] += 1
            else:
                print(f"  ✗ ffmpeg 提取失败: {seg.source_path}")
                logging.error(f"[FAIL] ffmpeg 提取失败: {seg.source_path}")
                stats["failed"] += 1
        except Exception as e:
            print(f"  ✗ 片段处理异常: {e}")
            logging.error(f"[ERROR] {draft_dir.name} 片段异常: {e}", exc_info=True)
            stats["failed"] += 1


def process_draft_tracks(draft_dir: Path, cfg: dict, temp_dir: Path, stats: dict):
    """整轨模式：一个草稿 → 每条音频轨一个 WAV（等长、带位置信息）+ 可选 AAF。

    输出到 `<输出目录>/<草稿名>/`，一个草稿一个文件夹，可整体拷走。
    """
    raw_file = resolve_draft_content_file(draft_dir)
    print(f"\n[process] 草稿: {draft_dir.name}")
    if raw_file.parent != draft_dir:
        print(f"  [info] 内容源: {raw_file.relative_to(draft_dir)}")

    try:
        decrypted = decrypt_draft_file(raw_file)
        tracks, total_us = parse_draft_tracks(
            draft_dir, decrypted, cfg.get("extract_video_tracks", True))
    except Exception as e:
        print(f"  ✗ 草稿解析失败: {e}")
        logging.error(f"草稿 {draft_dir.name} 解析失败: {e}")
        stats["failed"] += 1
        return

    total_s = total_us / 1e6
    print(f"  → {len(tracks)} 条音频轨 ｜ 时间线 {total_s:.3f}s（跟随视频轨）")
    if not tracks:
        print("  ⏭ 无可导出的音频轨")
        return

    conflict = cfg.get("conflict", "rename")
    spec_key = cfg.get("track_spec", DEFAULT_SPEC_KEY)
    template = cfg.get("track_name_template") or DEFAULT_TRACK_TEMPLATE
    remarks = cfg.get("remarks", "")
    out_root = Path(cfg.get("output_dir", DEFAULT_CONFIG["output_dir"])) / draft_dir.name
    out_root.mkdir(parents=True, exist_ok=True)
    # 临时目录自建，不依赖调用方（execute_export 建了，但单独调用本函数时没有）
    Path(temp_dir).mkdir(parents=True, exist_ok=True)

    for t in tracks:
        try:
            base = render_track_name(template, draft_dir.name,
                                     t.display_name, t.index, total_s, remarks)
            out_file = out_root / f"{base}.wav"
            resolved = resolve_conflict(out_file, conflict)
            if resolved is None:
                print(f"  ⏭ 跳过（已存在）: {out_file.name}")
                stats["skipped"] += 1
                continue
            temp_file = temp_dir / f"trk_{t.index}_{base}.wav"
            if extract_track_audio(t, total_us, temp_file, spec_key):
                temp_file.replace(resolved)
                print(f"  ✓ 整轨: {resolved.name}（{len(t.segments)} 段 / {total_s:.3f}s）")
                logging.info(f"[OK] {draft_dir.name} → {resolved.name}")
                stats["success"] += 1
            else:
                stats["failed"] += 1
        except Exception as e:
            print(f"  ✗ 轨道处理异常: {e}")
            logging.error(f"[ERROR] {draft_dir.name} 轨道异常: {e}", exc_info=True)
            stats["failed"] += 1

    # AAF（可选，默认关）
    if cfg.get("export_aaf"):
        try:
            from aaf_writer import write_aaf
            ok, msg = write_aaf(tracks, total_us, draft_dir.name, out_root, cfg)
            if ok:
                print(f"  ✓ AAF: {msg}")
                logging.info(f"[OK] AAF {draft_dir.name} → {msg}")
                stats["success"] += 1
            else:
                print(f"  ✗ AAF 失败: {msg}")
                stats["failed"] += 1
        except Exception as e:
            print(f"  ✗ AAF 导出异常: {e}")
            logging.error(f"[ERROR] {draft_dir.name} AAF: {e}", exc_info=True)
            stats["failed"] += 1


# ──────────────────── Direct file（拖入音视频，非草稿）────────────────────

def probe_duration_us(path: Path) -> int:
    """用 ffprobe 读取媒体文件总时长（微秒）；失败返回 0"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, **subprocess_kwargs(),
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(float(result.stdout.strip()) * 1_000_000)
    except Exception:
        pass
    return 0


def process_direct_file(media_file: Path, cfg: dict, temp_dir: Path, seen_ids: dict, stats: dict):
    """把单个音视频文件整体提取为音频（不走草稿解析）。

    用于「拖入文件」场景：剪映内置素材、已导出成片、外部素材等。
    """
    kind = media_kind(media_file) or "audio"
    conflict = cfg.get("conflict", "rename")
    audio_format = cfg.get("audio_format", "mp3")
    bitrate = cfg.get("bitrate_kbps", 192)
    template = cfg.get("name_template", "{项目名}_{素材类型}_{序号:03d}_{原始名}")
    remarks = cfg.get("remarks", "")

    # 项目名用文件名本身（比所在文件夹名更有辨识度）
    project = media_file.stem
    # 探测真实时长，供命名模板 {时长} 字段使用
    duration_us = probe_duration_us(media_file)
    seg = AudioSegment(
        project=project,
        track_type="video" if kind == "video" else "audio",
        source_path=str(media_file),
        start_us=0,                       # 0 表示整轨（extract_audio 会省略 -ss）
        end_us=duration_us,               # 0 表示到结尾（省略 -t）
        material_name=media_file.stem,
        material_id="",
    )

    print(f"\n[process] 文件: {media_file.name}")

    if cfg.get("dedupe", True):
        dup = dedupe_check(seg.source_path, 0, 0, seen_ids)
        if dup:
            print(f"  ⏭ 去重跳过（与 {dup} 重复）: {media_file.name}")
            stats["skipped"] += 1
            return

    try:
        base_name = render_name(template, seg, 1, remarks)
        category = TYPE_CATEGORY.get(seg.track_type, "audio")
        category_dir = Path(cfg.get("output_dir", "D:/导出音频")) / category
        category_dir.mkdir(parents=True, exist_ok=True)

        out_file = category_dir / f"{base_name}.{audio_format}"
        resolved = resolve_conflict(out_file, conflict)
        if resolved is None:
            print(f"  ⏭ 跳过（已存在）: {out_file.name}")
            stats["skipped"] += 1
            return

        temp_file = temp_dir / f"tmp_direct_{base_name}.{audio_format}"
        if extract_audio(seg, temp_file, audio_format, bitrate):
            temp_file.replace(resolved)
            print(f"  ✓ 导出: {category}/{resolved.name}")
            logging.info(f"[OK] {media_file.name} → {category}/{resolved.name}")
            stats["success"] += 1
        else:
            print(f"  ✗ ffmpeg 提取失败: {media_file}")
            logging.error(f"[FAIL] ffmpeg 提取失败: {media_file}")
            stats["failed"] += 1
    except Exception as e:
        print(f"  ✗ 文件处理异常: {e}")
        logging.error(f"[ERROR] {media_file} 处理异常: {e}", exc_info=True)
        stats["failed"] += 1


def find_source_file(seg: AudioSegment, draft_dir: Path) -> Optional[Path]:
    """按文件名在草稿目录递归搜索源文件，重建失效路径"""
    name = Path(seg.source_path).name
    for root, _, files in os.walk(draft_dir):
        if name in files:
            return Path(root) / name
    return None



def load_processed(output_dir: Path) -> set:
    """加载已处理草稿记录（断点续跑）"""
    state_file = output_dir / ".processed_drafts.txt"
    if state_file.exists():
        return set(state_file.read_text(encoding="utf-8").splitlines())
    return set()


def save_processed(output_dir: Path, name: str, processed: set):
    """追加已处理草稿记录"""
    if name not in processed:
        processed.add(name)
        state_file = output_dir / ".processed_drafts.txt"
        with open(state_file, "a", encoding="utf-8") as f:
            f.write(name + "\n")


# ──────────────────── 配置（已移至 core/config.py）────────────────────
# DEFAULT_CONFIG / DEFAULT_IMPORT_CONFIG / CONFIG_FIELDS / load_config /
# save_config / ask / parse_bool / init_config 均在 core/config.py，
# 本模块顶部已 import，名字保持兼容（CLI / GUI / tab 行为不变）。


def check_environment() -> dict:
    """环境自检：Python / ffmpeg / 剪映 / jy-draftc"""
    print("=" * 56)
    print("环境自检")
    print("=" * 56)

    checks = {}

    # Python
    py = sys.version_info
    ok = py.major == 3 and py.minor >= 9
    checks["Python"] = (ok, f"{py.major}.{py.minor}.{py.micro} (需要 3.9+)")
    print(f"  [{'✓' if ok else '✗'}] Python {checks['Python'][1]}")

    # ffmpeg
    ffmpeg_ok = False
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=15, **subprocess_kwargs(),)
        ffmpeg_ok = r.returncode == 0 and "ffmpeg version" in r.stdout
    except Exception:
        pass
    checks["ffmpeg"] = (ffmpeg_ok, "ffmpeg 命令可用" if ffmpeg_ok else "未找到 ffmpeg（winget install Gyan.FFmpeg）")
    print(f"  [{'✓' if ffmpeg_ok else '✗'}] {checks['ffmpeg'][1]}")

    # 剪映
    jy_dir = find_jianying_install_dir()
    checks["剪映"] = (jy_dir is not None, jy_dir.name if jy_dir else "未找到剪映 videoeditor.dll（请先安装剪映专业版）")
    print(f"  [{'✓' if jy_dir else '✗'}] {checks['剪映'][1]}")

    # jy-draftc
    draftc = JY_DRAFTC_EXE.exists()
    checks["jy-draftc"] = (draftc, "解密工具就绪" if draftc else f"未找到 jy-draftc（{JY_DRAFTC_EXE}）")
    print(f"  [{'✓' if draftc else '✗'}] {checks['jy-draftc'][1]}")

    return checks


# ──────────────────── Pro Tools 可用性（导入页「选 .ptx」前置条件）────────────────────

# 探测逻辑已收敛到 core/host.py（L0 卡顿修复 + 分层起点）。
# 此处保留同名引用，确保 CLI / GUI（core.pro_tools_status）行为不变。
from core.host import pro_tools_status, PT_URL, subprocess_kwargs


# ──────────────────── 非交互参数 ────────────────────

def apply_cli_overrides(cfg: dict, args: list) -> dict:
    """从命令行覆盖配置（供 Skill / 无交互场景）并消费对应参数。
    支持的覆盖参数：--output-dir --format --bitrate --conflict --name-template --remarks
                    --no-video-track --no-dedupe --refresh
                    --mode --spec --track-template --aaf --aaf-embed
    未识别参数保留在 args 中（仍可用于位置参数 = 草稿目录）。"""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--mode" and i + 1 < len(args):
            cfg["export_mode"] = args[i + 1]; del args[i:i + 2]
        elif a == "--spec" and i + 1 < len(args):
            cfg["track_spec"] = args[i + 1]; del args[i:i + 2]
        elif a == "--track-template" and i + 1 < len(args):
            cfg["track_name_template"] = args[i + 1]; del args[i:i + 2]
        elif a == "--aaf":
            cfg["export_aaf"] = True; del args[i]
        elif a == "--aaf-embed":
            cfg["export_aaf"] = True; cfg["aaf_media_mode"] = "embed"; del args[i]
        elif a == "--output-dir" and i + 1 < len(args):
            cfg["output_dir"] = args[i + 1]; del args[i:i + 2]
        elif a == "--format" and i + 1 < len(args):
            cfg["audio_format"] = args[i + 1]; del args[i:i + 2]
        elif a == "--bitrate" and i + 1 < len(args):
            try: cfg["bitrate_kbps"] = int(args[i + 1])
            except ValueError: pass
            del args[i:i + 2]
        elif a == "--conflict" and i + 1 < len(args):
            cfg["conflict"] = args[i + 1]; del args[i:i + 2]
        elif a == "--name-template" and i + 1 < len(args):
            cfg["name_template"] = args[i + 1]; del args[i:i + 2]
        elif a == "--remarks" and i + 1 < len(args):
            cfg["remarks"] = args[i + 1]; del args[i:i + 2]
        elif a == "--no-video-track":
            cfg["extract_video_tracks"] = False; del args[i]
        elif a == "--no-dedupe":
            cfg["dedupe"] = False; del args[i]
        elif a == "--refresh":
            cfg["skip_existing"] = False; del args[i]
        else:
            i += 1
    return cfg


def execute_export(cfg: dict, root: Path, log_file: Optional[Path] = None,
                   draft_dirs: Optional[List[Path]] = None,
                   media_files: Optional[List[Path]] = None) -> dict:
    """执行完整导出流程（输出准备 → 扫描 → 逐草稿处理 → 汇总）。

    被 CLI main() 与 GUI（gui.py）共用。返回统计 dict:
    {"success": int, "failed": int, "skipped": int}

    draft_dirs / media_files 非空时直接使用该列表（拖拽场景），
    否则回退到按 root 目录扫描。
    """
    output_dir = Path(cfg.get("output_dir", DEFAULT_CONFIG["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = Path(cfg["temp_dir"]) if cfg.get("temp_dir") else (output_dir / ".tmp")
    temp_dir.mkdir(parents=True, exist_ok=True)

    if log_file is None:
        log_file = output_dir / "导出日志.log"
    setup_logger(log_file)

    mode = cfg.get("export_mode", "tracks")
    mode_label = "整轨（一条轨一个 WAV，等长对齐）" if mode == "tracks" else "片段（一段一个文件）"
    print(f"剪映草稿目录: {root}")
    print(f"输出目录:     {output_dir}")
    print(f"导出模式:     {mode_label}\n")

    stats = {"success": 0, "failed": 0, "skipped": 0}
    seen_ids = {}
    processed = load_processed(output_dir)
    skip_existing = cfg.get("skip_existing", True)

    # 直接文件（拖入音视频）优先处理
    for f in (media_files or []):
        process_direct_file(Path(f), cfg, temp_dir, seen_ids, stats)

    drafts = [Path(d) for d in draft_dirs] if draft_dirs else scan_drafts(root)

    for d in drafts:
        # 断点续跑：已处理草稿跳过
        if skip_existing and d.name in processed:
            print(f"[skip] 已处理草稿，跳过: {d.name}")
            continue
        if mode == "tracks":
            process_draft_tracks(d, cfg, temp_dir, stats)
        else:
            process_draft(d, cfg, temp_dir, seen_ids, stats)
        save_processed(output_dir, d.name, processed)

    # 清理临时目录
    shutil.rmtree(temp_dir, ignore_errors=True)

    # 汇总报告
    print(f"\n{'='*60}")
    print(f"统计：成功 {stats['success']} ｜ 失败 {stats['failed']} ｜ 跳过 {stats['skipped']}")
    print(f"日志：{log_file}")
    return stats


def _safe_io():
    """打包为 --windowed exe 时 stdout/stderr 可能为 None；
    且中文 Windows 控制台默认 GBK 无法编码 ✓/✗ 等字符。
    兜底：None → devnull；可 reconfigure 的流 → UTF-8（errors=replace 防崩）。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except Exception:
                pass
        elif hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main():
    _safe_io()
    args = sys.argv[1:]
    cfg_path = CONFIG_PATH

    # --init：进入初始化向导
    if "--init" in args:
        init_config(cfg_path)
        return

    # --check：仅环境自检
    if "--check" in args:
        check_environment()
        return

    cfg = load_config(cfg_path)

    # 首次运行（无配置或缺少 output_dir）：强制进入初始化向导
    if not cfg.get("output_dir"):
        print("⚠ 尚未初始化配置，进入初始化向导…\n")
        cfg = init_config(cfg_path)

    # CLI 覆盖（供无交互 / Skill 场景）；消费覆盖参数后剩余留作位置参数
    args = list(sys.argv[1:])
    cfg = apply_cli_overrides(cfg, args)

    # 输入目录：命令行位置参数优先 > config > 默认剪映草稿目录
    # 位置参数可为「文件夹 / 剪映草稿 JSON / 音视频文件」，自动智能识别
    pos_args = [a for a in args if not a.startswith("--")]
    if pos_args:
        draft_dirs, root, _file_mode = resolve_input_paths([Path(a) for a in pos_args])
        execute_export(cfg, root, draft_dirs=draft_dirs)
    elif cfg.get("input_dir"):
        root = Path(cfg["input_dir"])
        execute_export(cfg, root)
    else:
        root = DEFAULT_JIANYING_DRAFT_ROOT
        execute_export(cfg, root)


if __name__ == "__main__":
    main()