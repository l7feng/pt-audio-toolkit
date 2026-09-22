#!/usr/bin/env python3
"""core/config.py — 配置单一来源（L1 分层：领域层）

把配置相关的**常量、默认值、读写、交互向导**从 ``main.py`` 收敛到此处。
本模块只依赖标准库，不 import ``main`` / ``import_audio`` / tkinter，因此
可被 CLI、GUI、tab、单测任意引用，无环依赖。

路径锚点说明（沿用 2026-09-18 既定设计）：
  所有可变文件（config.json）**一律写 APP_DIR**，不写代码目录。
  - 源码模式： APP_DIR = code 包的父目录（即工具包根）
  - frozen 模式（exe）：APP_DIR = exe 所在目录
  老用户历史配置在 ``code/config.json``，由 :func:`config_path` 首次运行自动迁移。

模块内不再重复定义 ``_app_dir()``：由 :func:`set_app_dir` 在 ``main`` 导入时注入，
避免本模块去猜 frozen 状态（保持单一真相源在 ``main`` 的 ``APP_DIR``）。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

# ──────────────────── 常量（整轨 / 规格）────────────────────
# 原定义于 main.py（整轨功能区块）。放进 config 是因为 DEFAULT_CONFIG 依赖它们，
# 而 config 不应反向 import main。

# 整轨命名默认模板
DEFAULT_TRACK_TEMPLATE = "{项目名}_{轨道名}"

# 规格预设键（完整 SPEC_PRESETS 表仍在 main.py，此处只放默认键）
DEFAULT_SPEC_KEY = "keep"

# 片段命名默认模板（兼容旧配置 / CLI 回退）
DEFAULT_CLIPS_TEMPLATE = "{项目名}_{素材类型}_{序号:03d}_{原始名}_{时长}s"

# 命名模板预设库（「多选命名模板」的候选，用户可在界面增删）
NAMING_PRESETS = [
    "{项目名}_{素材类型}_{序号:03d}_{原始名}_{时长}s",
    "{原始名}",
    "{素材类型}_{序号:03d}_{原始名}",
    "{项目名}_{序号:03d}_{原始名}",
    "{项目名}_{素材类型}_{序号:03d}_{原始名}",
]


# ──────────────────── 路径锚点（由 main 注入）────────────────────

# APP_DIR：可变文件落点（源码模式=包根，frozen=exe 旁）
APP_DIR: Path = Path(__file__).resolve().parent.parent.parent
# code 源码目录
SCRIPT_DIR: Path = Path(__file__).resolve().parent.parent


def set_app_dir(app_dir: Path) -> None:
    """由 ``main`` 在导入时注入真实 APP_DIR，并在注入后重算 CONFIG_PATH。

    这样 frozen 判定逻辑只保留在 ``main._app_dir()`` 一处（单一真相源）。
    """
    global APP_DIR, CONFIG_PATH, LEGACY_CONFIG_PATH
    APP_DIR = Path(app_dir)
    CONFIG_PATH = APP_DIR / "config.json"
    LEGACY_CONFIG_PATH = SCRIPT_DIR / "config.json"


# 模块可被直接 import（不注入）时，退化为「包根」；main 会立刻用 set_app_dir 纠正。
CONFIG_PATH: Path = APP_DIR / "config.json"
LEGACY_CONFIG_PATH: Path = SCRIPT_DIR / "config.json"


# ──────────────────── 默认配置模板 ────────────────────

DEFAULT_CONFIG = {
    "input_dir": "",
    "output_dir": "D:/导出音频",
    "name_template": "{项目名}_{素材类型}_{序号:03d}_{原始名}_{时长}s",
    # ── 命名模板多选（2026-09-22 新增）──
    "name_templates": NAMING_PRESETS,                 # 命名模板库（候选清单，可增删）
    "name_templates_active": [NAMING_PRESETS[0]],     # 当前勾选的模板（多选 → 各生成一份）
    "audio_format": "mp3",
    "bitrate_kbps": 192,
    "conflict": "rename",
    "dedupe": True,
    "extract_video_tracks": True,
    "skip_existing": True,
    "temp_dir": "",
    # ── 整轨 / AAF（2026-09-18 新增）──
    "export_mode": "tracks",                     # tracks=整轨（默认）| clips=片段
    "track_name_template": DEFAULT_TRACK_TEMPLATE,
    "track_spec": DEFAULT_SPEC_KEY,
    "export_aaf": False,
    "aaf_media_mode": "media",                   # media=AAF+Media 文件夹 | embed=单文件内嵌
    # ── 导入页配置（与导出页完全独立，见 tabs/import_tab.py）──
    "import_json": "",
    "import_draft_dir": "",
    "import_pkg_out": "",
    "import_exclude": "",
    "import_keep_aux": False,
}

# 导入页默认配置（与 DEFAULT_CONFIG 分离，避免两页互相覆写）
DEFAULT_IMPORT_CONFIG = {
    "import_json": "",
    "import_draft_dir": "",
    "import_pkg_out": "",
    "import_exclude": "",
    "import_keep_aux": False,
}

# 配置字段说明（用于向导提示与诊断）
CONFIG_FIELDS = {
    "input_dir": ("剪映草稿输入目录", "留空 = 自动定位剪映默认草稿目录"),
    "output_dir": ("音频输出目录（必填）", ""),
    "name_template": ("命名模板（主模板/兼容字段）", "{项目名}/{素材类型}/{序号:03d}/{原始名}/{日期}/{时长}/{备注}，示例 `{项目名}_{素材类型}_{序号:03d}_{原始名}_{时长}s`"),
    "name_templates": ("命名模板库（多选）", "片段导出可用的命名模板清单，界面可增删"),
    "name_templates_active": ("当前勾选的命名模板", "多选；勾选的每套模板都会各生成一份输出（多模板时按 模板N 分目录）"),
    "audio_format": ("音频格式", "mp3 或 wav"),
    "bitrate_kbps": ("比特率 kbps（仅 mp3）", "如 128 / 192 / 320"),
    "conflict": ("重名冲突策略", "rename=自动重命名 | cover=覆盖 | skip=跳过"),
    "dedupe": ("内容去重", "true=启用（基于首 4KB 哈希）| false=关闭"),
    "extract_video_tracks": ("提取视频内嵌音轨", "true=启用（方案扩展场景）| false=仅独立音频轨道"),
    "skip_existing": ("断点续跑", "true=跳过已处理草稿 | false=每次全量"),
    "temp_dir": ("临时目录", "留空 = 输出目录/.tmp"),
}


# ──────────────────── 读写 ────────────────────

def config_path() -> Path:
    """返回配置文件路径，并在首次运行时把历史 code/config.json 迁移过来。"""
    if not CONFIG_PATH.exists() and LEGACY_CONFIG_PATH.is_file():
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(LEGACY_CONFIG_PATH, CONFIG_PATH)
        except Exception:
            pass
    return CONFIG_PATH


def load_config(config_path: Path) -> dict:
    """从磁盘读配置；文件不存在或 JSON 损坏时返回空 dict（调用方补默认值）。"""
    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8-sig")  # utf-8-sig 自动剥离 BOM
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(cfg: dict, config_path: Optional[Path] = None) -> Path:
    """写配置到磁盘（UTF-8 / 不转义中文 / 缩进 2）。默认写 CONFIG_PATH。"""
    path = Path(config_path) if config_path else CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ──────────────────── 交互向导辅助 ────────────────────

def ask(prompt: str, default: str = "") -> str:
    """交互式提问，支持回车取默认值"""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    try:
        val = input(prompt).strip()
    except EOFError:
        val = ""
    return val if val else default


def parse_bool(val: str, default: bool) -> bool:
    """解析布尔输入：y/n/true/false/1/0，空取默认"""
    v = val.strip().lower()
    if v in ("y", "yes", "true", "1", "on"):
        return True
    if v in ("n", "no", "false", "0", "off"):
        return False
    return default


def init_config(config_path: Path) -> dict:
    """交互式初始化向导，让用户配置输出路径等参数，写入 config.json"""
    print("=" * 56)
    print("剪映批量导出音频 — 初始化向导")
    print("（直接回车使用默认值；可随时重新运行 --init 修改）")
    print("=" * 56)

    # 预载现有配置作为默认值
    current = load_config(config_path)

    # 1. 输出目录（必填）
    output_dir = ask("音频输出目录（必填）", current.get("output_dir", DEFAULT_CONFIG["output_dir"]) or DEFAULT_CONFIG["output_dir"])
    while not output_dir:
        print("  ⚠ 输出目录不能为空")
        output_dir = ask("音频输出目录（必填）").strip() or ""
    try:
        Path(output_dir).parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"  ⚠ 目录创建提示: {e}")

    # 2. 输入目录
    input_dir = ask("剪映草稿目录（留空自动定位）", current.get("input_dir", ""))

    # 3. 命名模板
    name_template = ask("命名模板", current.get("name_template", DEFAULT_CONFIG["name_template"]))

    # 4. 音频格式
    audio_format = ask("音频格式（mp3/wav）", current.get("audio_format", DEFAULT_CONFIG["audio_format"]))
    if audio_format not in ("mp3", "wav"):
        print(f"  ⚠ 未知格式 {audio_format}，回退 mp3")
        audio_format = "mp3"

    # 5. 码率
    bitrate = ask("比特率 kbps（仅 mp3）", str(current.get("bitrate_kbps", DEFAULT_CONFIG["bitrate_kbps"])))
    try:
        bitrate = int(bitrate)
    except ValueError:
        bitrate = 192

    # 6. 冲突策略
    conflict = ask("重名冲突策略（rename/cover/skip）", current.get("conflict", DEFAULT_CONFIG["conflict"]))
    if conflict not in ("rename", "cover", "skip"):
        conflict = "rename"

    # 7-9. 布尔项
    dedupe = parse_bool(ask("启用内容去重？(y/n)", "y" if current.get("dedupe", True) else "n") or "y", True)
    extract_video = parse_bool(ask("提取视频内嵌音轨？(y/n)", "y" if current.get("extract_video_tracks", True) else "n") or "y", True)
    skip_existing = parse_bool(ask("断点续跑，跳过已处理草稿？(y/n)", "y" if current.get("skip_existing", True) else "n") or "y", True)

    # 10. 备注（模板字段 {备注}）
    remarks = ask("备注文案（命名模板 {备注} 字段，可留空）", current.get("remarks", ""))

    cfg = {
        "input_dir": input_dir,
        "output_dir": output_dir,
        "name_template": name_template,
        "audio_format": audio_format,
        "bitrate_kbps": bitrate,
        "conflict": conflict,
        "dedupe": dedupe,
        "extract_video_tracks": extract_video,
        "skip_existing": skip_existing,
        "temp_dir": current.get("temp_dir", ""),
        "remarks": remarks,
    }

    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 配置已保存: {config_path}")
    print(f"   输出目录: {output_dir}")
    return cfg
