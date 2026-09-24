# -*- coding: utf-8 -*-
"""pt-tools 常量与版本口径（W1 三层拆分 · core/data）。

分层原则：settings 只放**纯数据**（常量 / 路径 / 版本），不放逻辑，
四个工具各自独立打包、无共享模块 —— 常量改动只影响本包。
"""
import os
import re
import sys

# ---------------------------------------------------------------------------
# 常量与路径
# ---------------------------------------------------------------------------

PTSL_HOST = "127.0.0.1"
PTSL_PORT = 31416

DEFAULT_SKILLS_ROOT = r"D:\Ai-Files\Agent-Preset\Skills\protools-skills"
ENV_SKILLS_ROOT = "PTOOLS_SKILLS_ROOT"

# 出厂默认路径（2026-09-24 定稿；权威清单见知识库
# 4-项目/12-pt-audio-toolkit仓库维护/06-2026-09-24-四工具默认路径总表.md）：
#   · 档案（pt-profile.json）平铺存 json 目录，扫描完自动命名 <工程名>-pt-profile.json
#   · 导出产物统一落 out 目录
DEFAULT_PROFILE_DIR = r"D:\My-Temporary\PT-Tools-Backup\json"
DEFAULT_OUT_ROOT = r"D:\My-Temporary\PT-Tools-Backup\out"

# ---------------------------------------------------------------------------
# 配置落点（W4 · 2026-09-24 拍板：四工具统一 **exe 旁**，便携、随 exe 走）
# ---------------------------------------------------------------------------
# 旧版 pt-tools 配置/日志在 %APPDATA%\pt-tools\，两机同步时与
# 「剪映 / rename-unify 已是 exe 旁」的行为不一致。现在统一 exe 旁：
#   frozen：exe 所在目录；源码模式：src/pt-tools（本文件向上三级）。
# 首次运行时若 exe 旁还没有 config.json，会把旧 %APPDATA% 的一份**复制**过来
# （迁移不删旧文件，见 config.migrate_legacy_config）。
def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # settings.py 位于 <pt-tools>/ptools/core/ 下，向上三级 = src/pt-tools
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


LEGACY_APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                              "pt-tools")
APP_DIR = _app_dir()
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
LEGACY_CONFIG_FILE = os.path.join(LEGACY_APP_DIR, "config.json")

SCRIPTS = {
    "pt-scanner": "pt_scan.py",
    "pt-exporter": "pt_export.py",
    "pt-cleaner": "pt_clean.py",
}

SOURCE_TYPES = ["bus", "output", "physicalout"]  # ExportMix 路径制三类（扫描摘要仍用）
# 导出模式（v1.1.0 四模式多选；顺序即执行顺序）
EXPORT_MODES = ["mix", "bus", "stem", "track"]
SAMPLE_RATES = [48000, 44100, 96000, 88200, 192000]
BIT_DEPTHS = [16, 24, 32]
# 导出格式（v1.3.0 语义澄清 + 默认不再丢声道）
#
# ⚠️ 认知陷阱：这三个值**不是"你要几个声道"**，而是 bounce 产物**怎么装进文件**：
#     interleaved   该轨在 PT 里是立体声/5.1/7.1 → 原样保留，出一个文件
#     multiple-mono 每声道一个独立文件（_L.wav / _R.wav …）
#     mono          强制下混成单声道 —— **会丢声道**，故不再作为默认
# 实际声道数由 PT 工程里该轨道/输出本身的宽度决定，本工具改不了也不该改，
# 所以下拉里**不该**出现 5.1 / 7.1 这类"宽度"选项。
# 旧默认 `mono` 会把立体声素材静默下混，属会污染产物的默认值（v1.3.0 修正）。
EXPORT_FORMATS = ["interleaved", "multiple-mono", "mono"]
FORMAT_LABEL_KEYS = {
    "interleaved": "e_fmt_interleaved",
    "multiple-mono": "e_fmt_multimono",
    "mono": "e_fmt_mono",
}
DEFAULT_EXPORT_FORMAT = "interleaved"
DEFAULT_VIDEO_MARGIN = 0        # 旧值 240：每条片子都被加 4 分钟尾巴
DEFAULT_FALLBACK_DURATION = 60  # 旧值 240：没检出视频时假装片子 4 分钟
# 每条轨道可单独覆盖全局格式；此值表示"跟随全局下拉"
FORMAT_FOLLOW = ""
TRACK_FMT_CYCLE = ["", "interleaved", "mono", "multiple-mono"]

TC_RE = re.compile(r"^\d{2}:\d{2}:\d{2}:\d{2}$")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# ---------------------------------------------------------------------------
# 版本与构建日期
# ---------------------------------------------------------------------------
# 四工具统一口径：版本号 X.Y.Z（不带 v 前缀），标题/关于里写 vX.Y.Z (YYYY-MM-DD)。
# ⚠️ build_date() 在 pt-project-folder-builder / jianying-draft-toolkit /
#    rename-unify 各有一份逐字相同的实现（各工具独立打包、无共享模块），
#    改动时四处需同步。
# v1.4.0（2026-09-24）：① 建档/档案/输出默认路径收口（profile_dir=json 目录、
#   last_out_dir=out 目录，_migrate_cfg 2→3 只补缺不覆盖）② 档案平铺存放，
#   扫描完自动改名 <工程名>-pt-profile.json ③「指定文件」模式预填档案里的
#   .ptx 路径、浏览框默认开其父级 ④ 输出/建档目录不存在时现建。
# v1.4.1（2026-09-24）：① 任务完成弹 Windows 托盘通知（W7）② 接入滚动日志
#   %APPDATA%\pt-tools\pt-tools.log（W2 骨架，D2 并入诊断包）。
# v1.5.0（2026-09-24）：① W4 配置/日志迁 exe 旁（旧 %APPDATA% 首次运行自动复制）
#   ② P1 PT 离线常驻黄条 ③ P2 导出后自动质检 wav ④ P3 档案库页 ⑤ P4 导出历史
#   ⑥ W8 --batch CLI（jobs.json 夜间批量）⑦ 批量对话框可保存 jobs.json。
APP_VERSION = "1.5.2"


def build_date():
    """构建日期：frozen 取 exe 文件时间（打包时刻），源码模式取本文件时间。

    目标：标题栏一眼识别新旧 —— 拿错旧版 exe 时日期明显比固定资产旧。
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

LANG_ZH = "zh"
LANG_EN = "en"
