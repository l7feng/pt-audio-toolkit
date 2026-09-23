#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pt-tools-gui —— Pro Tools 自动化技能族·人类直用通道（UI v2）

v2 变更：
  - 单语 UI（中文 / English）：菜单栏 设置 > 语言 切换，写入 config.json
  - 菜单栏：文件 / 设置 / 工具 / 帮助（打开目录、技能目录、使用说明、关于等）
  - 技能目录不再常驻界面：启动自动探测（exe 相对 → 环境变量 → 默认路径），
    找不到才提示通过 设置 > 技能目录 指定
  - 扫描页重构：页面内功能说明 + PTSL 指示灯 + 三步引导 + 扫描成功自动应用档案
  - 消除 Tk 启动闪窗：withdraw + overrideredirect + alpha 三重保险
  - 打包时 scripts 复制进 dist\\_internal\\skills\\，exe 相对自身定位脚本

壳不动芯原则不变：UI 只收集参数 -> 拼 CLI -> subprocess 调技能脚本（PTSL 连接、
GBK json_cleanup、模态弹窗守卫全部在技能脚本内）。零第三方依赖。

用法：python pt_tools_gui.py
"""
import json
import os
import re
import queue
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------------------------------------------------------
# 常量与路径
# ---------------------------------------------------------------------------

PTSL_HOST = "127.0.0.1"
PTSL_PORT = 31416

DEFAULT_SKILLS_ROOT = r"D:\Ai-Files\Agent-Preset\Skills\protools-skills"
ENV_SKILLS_ROOT = "PTOOLS_SKILLS_ROOT"

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                       "pt-tools")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

SCRIPTS = {
    "pt-scanner": "pt_scan.py",
    "pt-exporter": "pt_export.py",
    "pt-cleaner": "pt_clean.py",
}

SOURCE_TYPES = ["bus", "output", "physicalout"]
SAMPLE_RATES = [48000, 44100, 96000, 88200, 192000]
BIT_DEPTHS = [16, 24, 32]
EXPORT_FORMATS = ["mono", "interleaved"]

TC_RE = re.compile(r"^\d{2}:\d{2}:\d{2}:\d{2}$")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# ---------------------------------------------------------------------------
# 版本与构建日期
# ---------------------------------------------------------------------------
# 四工具统一口径：版本号 X.Y.Z（不带 v 前缀），标题/关于里写 vX.Y.Z (YYYY-MM-DD)。
# ⚠️ build_date() 在 pt-project-folder-builder / jianying-draft-toolkit /
#    rename-unify 各有一份逐字相同的实现（各工具独立打包、无共享模块），
#    改动时四处需同步。
APP_VERSION = "1.0.0"


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

# ---------------------------------------------------------------------------
# i18n 词条表（单语 UI：中文 / English）
# ---------------------------------------------------------------------------

TEXTS = {
    LANG_ZH: {
        "app_title": "pt-tools v%s (%s) — Pro Tools 自动化工具" % (APP_VERSION, build_date()),

        "menu_file": "文件",
        "menu_settings": "设置",
        "menu_tools": "工具",
        "menu_help": "帮助",

        "file_open_outdir": "打开输出目录",
        "file_open_cfgdir": "打开配置与日志目录",
        "file_exit": "退出",

        "sett_lang": "语言",
        "sett_lang_zh": "中文",
        "sett_lang_en": "English",
        "sett_skills": "技能目录（Skills Root）…",
        "sett_outdir": "默认输出目录…",

        "tools_open_skills": "打开技能目录（资源管理器）",
        "tools_open_outdir": "打开输出目录",
        "tools_open_cfgdir": "打开配置与日志目录",
        "tools_clear_log": "清空日志",

        "help_howto": "使用说明",
        "help_about": "关于 pt-tools",

        "tab_scan": " 1 · 扫描建档 ",
        "tab_export": " 2 · 导出 ",
        "tab_clean": " 3 · 清理 ",

        # —— 扫描页 ——
        "s_what_title": "本页功能",
        "s_what_body": ("扫描当前 Pro Tools 工程，生成「工程档案」（pt-profile.json）。"
                        "档案记录轨道、总线、主输出的清单与时长——导出页（页签 2）"
                        "直接从档案取源，不会猜错名字，扫描一次即可反复使用。"),
        "s_req_title": "扫描前提",
        "s_req_ptsl_on": "●  Pro Tools 运行中（PTSL 在线）",
        "s_req_ptsl_off": "○  Pro Tools 未运行（PTSL 离线）",
        "s_req_line2": "请在 Pro Tools 中打开要导出的工程（如「誓言24.ptx」）。",
        "s_steps_title": "操作步骤",
        "s_step1": "1)  启动 Pro Tools 并打开工程",
        "s_step2": "2)  点下方「扫描并生成档案」（只读，安全）",
        "s_step3": "3)  成功后档案自动应用，直接去「导出」页",
        "s_out": "输出目录（档案放这里）:",
        "s_name": "档案文件名:",
        "s_scan_btn": "扫描并生成档案",
        "s_summary": "扫描摘要",
        "s_browse": "浏览…",
        "s_auto_applied": "[scan] 档案已自动应用：%s\n",
        "s_missing_out": "请先选择输出目录。",
        "s_bad_name": "档案文件名必须以 .json 结尾。",

        # —— 导出页 ——
        "e_profile": "档案（pt-profile.json）:",
        "e_browse": "浏览…",
        "e_mode": "导出模式:",
        "e_mode_mix": "混音 Mix（整段并轨）",
        "e_mode_stems": "分轨 Stems（按 bus 逐个 WAV）",
        "e_session": "工程:",
        "e_sess_current": "当前打开的",
        "e_sess_file": "指定文件",
        "e_source_frame": "导出源 —— 列表来自档案，杜绝猜名",
        "e_stype": "源类型:",
        "e_search": "搜索:",
        "e_selected": "已选 %d 个",
        "e_name_col": "名称",
        "e_params": "参数",
        "e_start": "开始:",
        "e_end": "结束:",
        "e_tc_hint": "格式 HH:MM:SS:FF",
        "e_sr": "采样率:",
        "e_bd": "位深:",
        "e_fmt": "格式:",
        "e_out": "输出目录:",
        "e_preview": "预览导出计划",
        "e_export": "执行导出",
        "e_verify": "校验：时长×采样率×位深≈WAV 字节数",

        # —— 清理页 ——
        "c_warn": ("⚠ 需 Pro Tools 2025.10+（CId 146/147）。当前 PT 25.6.1 实测支持不了"
                   "（ErrType 133），升级前此页不可操作。"),
        "c_cap": "能力边界",
        "c_cap1": "✅ 批量改轨道主输出（SetTrackMainOutputAssignments）",
        "c_cap2": "✅ 新建输出路径（CreateSignalPath）",
        "c_cap3": "❌ 删发送 / 删插件 / 删 IO 路径 —— PTSL 不支持",
        "c_params": "参数（骨架，待 PT 升级后启用）",
        "c_track_mode": "选轨方式: 按名字 / 按前缀",
        "c_track_col": "轨道列表（从档案读取，待启用）",
        "c_target_out": "目标输出: （下拉，待启用）",
        "c_backup": "备份/保存: （复选框，待启用）",
        "c_note": "预览 / 执行按钮将在 PT 升级且扫描建档后启用。",

        # —— 日志 / 状态栏 ——
        "log_frame": "日志",
        "log_clear": "清空日志",
        "log_hint": "耗时操作在后台执行，请留意底部状态。",
        "status_ptsl_on": "●  PTSL 在线（Pro Tools 运行中）",
        "status_ptsl_off": "○  PTSL 离线（请先启动 Pro Tools）",
        "status_session": "工程：%s",
        "status_profile": "档案：%s",
        "status_skills_ok": "技能 OK",
        "status_skills_bad": "⚠ 技能目录不可用",
        "lang_changed": "[i18n] 语言已切换。\n",
        "preview_start": "[preview] 预览开始（dry-run）……\n",
        "preview_pass": "[preview] 预览通过。参数未再改动前，可执行导出。\n",
        "cmd_done": "— 命令结束，退出码 %d —\n",
        "err_cmd_start": "[error] 无法启动命令：%s\n",

        # —— 设置/技能目录 ——
        "skills_ok": "技能目录 OK：%s",
        "err_root_missing": "技能目录不存在：%s",
        "err_venv_missing": "未找到 venv 解释器：%s\n（在 pt-exporter/env 下重建 venv 并 pip install py-ptsl）",
        "err_venv_missing_builtin": "技能脚本已内置，仅缺运行解释器的 venv：%s\n"
                                    "（venv 含 py-ptsl、体积大，不随 exe 打包；"
                                    "请在 设置 > 技能目录 指向含 venv 的技能目录，如 %s）",
        "err_scripts_missing": "缺少脚本：%s",
        "skills_broken_title": "技能目录不可用",
        "skills_broken_hint": "请通过 设置 > 技能目录 选择 protools-skills 文件夹（需含 venv 与三个技能脚本）。",
        "choose_skills_title": "选择 protools-skills 技能目录",
        "choose_outdir_title": "选择输出目录",
        "choose_profile_title": "选择 pt-profile.json",
        "choose_ptx_title": "选择 Pro Tools 工程（.ptx）",
        "no_outdir": "还没有设置过输出目录，请先在导出页选择。",

        # —— 弹窗 / 校验 ——
        "msg_profile_invalid": "档案无效",
        "msg_missing": "缺参数",
        "msg_invalid": "参数错误",
        "msg_no_profile": "尚未加载档案，请先扫描或浏览选择 pt-profile.json。",
        "msg_no_source": "请至少选择一个导出源。",
        "msg_no_srctype": "档案中无 %s 类型源。",
        "msg_src_unknown": "源「%s」不在档案的 %s 列表内，请重新扫描。",
        "msg_tc_bad": "时间格式须为 HH:MM:SS:FF，如 00:00:00:00。",
        "msg_end_le": "End 必须晚于 Start。",
        "msg_out_missing": "请选择输出目录。",
        "msg_sr_bad": "采样率无效。",
        "msg_sess_missing": "已选「指定文件」，请提供 .ptx 路径。",
        "msg_warn_profile_start": "[warn] 启动时档案不可用：%s\n",
        "msg_preview_first_title": "请先预览",
        "msg_preview_first_body": "参数可能已变化，请先点「预览导出计划」确认后再执行。",
        "msg_confirm_title": "确认执行",
        "msg_confirm_body": "将按预览计划执行导出并落盘。\n确定执行吗？",
        "msg_ptsl_off_export": "执行导出需要 Pro Tools 正在运行（PTSL 在线）。",
        "msg_len_summary": "校验公式：时长×采样率×位深≈WAV 字节数",

        # —— 摘要字段 ——
        "sum_session": "工程",
        "sum_path": "路径",
        "sum_rate": "采样率 %s Hz  ·  位深 %s  ·  时码率 %s fps",
        "sum_range": "起始 %s  ·  长度 %s",
        "sum_tracks": "轨道数",
        "sum_bus": "总线",
        "sum_output": "主输出",
        "sum_phys": "物理输出",
        "sum_err": "[error] %s",

        # —— 帮助 / 关于 ——
        "help_text": (
            "pt-tools 三步工作流\n"
            "═" * 30 + "\n"
            "1. 扫描建档（页签 1）\n"
            "   启动 Pro Tools 并打开工程，确认 PTSL 在线后，点「扫描并生成档案」。\n"
            "   扫描只读、安全；成功后档案自动应用，无需再做其他操作。\n\n"
            "2. 导出（页签 2）\n"
            "   选择导出模式与源（列表来自档案，不会猜错名字），\n"
            "   点「预览导出计划」核对，再点「执行导出」。\n\n"
            "3. 校验\n"
            "   底部公式：时长 × 采样率 × 位深 ≈ WAV 字节数。\n\n"
            "常见问题\n"
            "═" * 30 + "\n"
            "· PTSL 离线：请先启动 Pro Tools（PTSL 服务随 Pro Tools 一起启动）。\n"
            "· 导出卡住：通常是 Pro Tools 弹了模态框（如「缺少文件」），\n"
            "  人工处理后重试。\n"
            "· 技能目录不可用：设置 > 技能目录，指向 protools-skills 文件夹\n"
            "  （内含三个技能 + pt-exporter\\env\\venv）。\n"),
        "about_text": (
            "pt-tools — Pro Tools 自动化桌面工具\n"
            "版本：v%s（%s）\n" % (APP_VERSION, build_date()) +
            "定位：Pro Tools 自动化技能族的人类直用通道\n\n"
            "技术：tkinter GUI → 调用技能脚本 → PTSL（gRPC 127.0.0.1:31416）\n"
            "依赖：protools-skills 技能目录（内置 py-ptsl venv）\n"
            "配置与日志：%APPDATA%\\pt-tools\\\n"),
    },

    LANG_EN: {
        "app_title": "pt-tools v%s (%s) — Pro Tools Automation" % (APP_VERSION, build_date()),

        "menu_file": "File",
        "menu_settings": "Settings",
        "menu_tools": "Tools",
        "menu_help": "Help",

        "file_open_outdir": "Open Output Folder",
        "file_open_cfgdir": "Open Config & Log Folder",
        "file_exit": "Exit",

        "sett_lang": "Language",
        "sett_lang_zh": "中文",
        "sett_lang_en": "English",
        "sett_skills": "Skills Root…",
        "sett_outdir": "Default Output Folder…",

        "tools_open_skills": "Open Skills Root (Explorer)",
        "tools_open_outdir": "Open Output Folder",
        "tools_open_cfgdir": "Open Config & Log Folder",
        "tools_clear_log": "Clear Log",

        "help_howto": "How to Use",
        "help_about": "About pt-tools",

        "tab_scan": " 1 · Scan ",
        "tab_export": " 2 · Export ",
        "tab_clean": " 3 · Clean ",

        "s_what_title": "What this tab does",
        "s_what_body": ("Scans the currently open Pro Tools session and builds a "
                        "\"session profile\" (pt-profile.json): track / bus / output "
                        "lists with duration. The Export tab reads sources straight "
                        "from this profile — nothing to guess, scan once, reuse."),
        "s_req_title": "Requirements",
        "s_req_ptsl_on": "●  Pro Tools running (PTSL online)",
        "s_req_ptsl_off": "○  Pro Tools not running (PTSL offline)",
        "s_req_line2": "Open the session you want to export in Pro Tools (e.g. \"ShiYan24.ptx\").",
        "s_steps_title": "Steps",
        "s_step1": "1)  Start Pro Tools and open the session",
        "s_step2": "2)  Click \"Scan & Save Profile\" below (read-only, safe)",
        "s_step3": "3)  Profile is applied automatically — go to the Export tab",
        "s_out": "Output folder (profile goes here):",
        "s_name": "Profile name:",
        "s_scan_btn": "Scan & Save Profile",
        "s_summary": "Scan Summary",
        "s_browse": "Browse…",
        "s_auto_applied": "[scan] Profile applied automatically: %s\n",
        "s_missing_out": "Please choose an output folder first.",
        "s_bad_name": "Profile name must end with .json.",

        "e_profile": "Profile (pt-profile.json):",
        "e_browse": "Browse…",
        "e_mode": "Export mode:",
        "e_mode_mix": "Mix (one merged file)",
        "e_mode_stems": "Stems (one WAV per bus)",
        "e_session": "Session:",
        "e_sess_current": "Current",
        "e_sess_file": "File…",
        "e_source_frame": "Source — list comes from the profile",
        "e_stype": "Source type:",
        "e_search": "Search:",
        "e_selected": "%d selected",
        "e_name_col": "Name",
        "e_params": "Parameters",
        "e_start": "Start:",
        "e_end": "End:",
        "e_tc_hint": "Format HH:MM:SS:FF",
        "e_sr": "Sample rate:",
        "e_bd": "Bit depth:",
        "e_fmt": "Format:",
        "e_out": "Output:",
        "e_preview": "Preview Plan",
        "e_export": "Export",
        "e_verify": "Check: duration × rate × depth ≈ WAV bytes",

        "c_warn": ("⚠ Requires Pro Tools 2025.10+ (CId 146/147). Tested on "
                   "PT 25.6.1 it raises ErrType 133 — disabled until you upgrade."),
        "c_cap": "Capability",
        "c_cap1": "✅ Reassign track main outputs (SetTrackMainOutputAssignments)",
        "c_cap2": "✅ Create signal path (CreateSignalPath)",
        "c_cap3": "❌ Delete sends / inserts / IO paths — not supported by PTSL",
        "c_params": "Parameters (skeleton, awaits PT upgrade)",
        "c_track_mode": "Track mode: by name / by prefix",
        "c_track_col": "Track list (from profile, to be enabled)",
        "c_target_out": "Target output: (dropdown, to be enabled)",
        "c_backup": "Backup/Save: (checkbox, to be enabled)",
        "c_note": "Preview / Apply enabled after PT upgrade + scan.",

        "log_frame": "Log",
        "log_clear": "Clear Log",
        "log_hint": "Long tasks run in the background. Watch the status bar.",
        "status_ptsl_on": "●  PTSL online (Pro Tools running)",
        "status_ptsl_off": "○  PTSL offline (start Pro Tools)",
        "status_session": "Session: %s",
        "status_profile": "Profile: %s",
        "status_skills_ok": "Skills OK",
        "status_skills_bad": "⚠ Skills root unavailable",
        "lang_changed": "[i18n] Language switched.\n",
        "preview_start": "[preview] Dry-run started……\n",
        "preview_pass": "[preview] Preview passed. Export is enabled until parameters change.\n",
        "cmd_done": "— Command finished, exit code %d —\n",
        "err_cmd_start": "[error] Cannot start command: %s\n",

        "skills_ok": "Skills root OK: %s",
        "err_root_missing": "Skills root does not exist: %s",
        "err_venv_missing": "venv interpreter not found: %s\n(recreate venv under pt-exporter/env and pip install py-ptsl)",
        "err_venv_missing_builtin": "Scripts are bundled; only the runtime venv is missing: %s\n"
                                    "(the venv carries py-ptsl and is too large to bundle; "
                                    "point Settings > Skills Root at a skills folder that has one, e.g. %s)",
        "err_scripts_missing": "Missing script(s): %s",
        "skills_broken_title": "Skills root unavailable",
        "skills_broken_hint": "Use Settings > Skills Root to select the protools-skills folder (needs venv + three skills).",
        "choose_skills_title": "Select protools-skills root",
        "choose_outdir_title": "Choose output folder",
        "choose_profile_title": "Choose pt-profile.json",
        "choose_ptx_title": "Choose Pro Tools session (.ptx)",
        "no_outdir": "No output folder set yet — choose one on the Export tab.",

        "msg_profile_invalid": "Invalid profile",
        "msg_missing": "Missing",
        "msg_invalid": "Invalid parameters",
        "msg_no_profile": "No profile loaded. Scan first or browse for pt-profile.json.",
        "msg_no_source": "Select at least one source.",
        "msg_no_srctype": "Profile has no %s sources.",
        "msg_src_unknown": "Source \"%s\" is not in the profile's %s list. Re-scan.",
        "msg_tc_bad": "Time must be HH:MM:SS:FF, e.g. 00:00:00:00.",
        "msg_end_le": "End must be later than Start.",
        "msg_out_missing": "Choose an output folder.",
        "msg_sr_bad": "Invalid sample rate.",
        "msg_sess_missing": "\"File\" was selected — provide a .ptx path.",
        "msg_warn_profile_start": "[warn] Profile unavailable at startup: %s\n",
        "msg_preview_first_title": "Preview first",
        "msg_preview_first_body": "Parameters may have changed. Click \"Preview Plan\" to confirm, then export.",
        "msg_confirm_title": "Confirm",
        "msg_confirm_body": "Export will run and write files. Continue?",
        "msg_ptsl_off_export": "Export needs Pro Tools running (PTSL online).",
        "msg_len_summary": "Check: duration × rate × depth ≈ WAV bytes",

        "sum_session": "Session",
        "sum_path": "Path",
        "sum_rate": "Rate %s Hz  ·  Depth %s  ·  TC rate %s fps",
        "sum_range": "Start %s  ·  Length %s",
        "sum_tracks": "Tracks",
        "sum_bus": "Bus",
        "sum_output": "Output",
        "sum_phys": "PhysicalOut",
        "sum_err": "[error] %s",

        "help_text": (
            "pt-tools in three steps\n"
            "═" * 30 + "\n"
            "1. Scan (tab 1)\n"
            "   Start Pro Tools, open the session, check PTSL online, click \"Scan & Save Profile\".\n"
            "   Read-only and safe; the profile is applied automatically.\n\n"
            "2. Export (tab 2)\n"
            "   Pick the mode and sources (list comes from the profile), click \"Preview Plan\",\n"
            "   then \"Export\".\n\n"
            "3. Verify\n"
            "   duration × rate × depth ≈ WAV bytes.\n\n"
            "FAQ\n"
            "═" * 30 + "\n"
            "· PTSL offline: start Pro Tools (its PTSL service starts with it).\n"
            "· Export hangs: Pro Tools usually has a modal dialog open (e.g. \"missing files\");\n"
            "   handle it manually and retry.\n"
            "· Skills root unavailable: Settings > Skills Root, point to protools-skills\n"
            "  (three skills + pt-exporter\\env\\venv).\n"),
        "about_text": (
            "pt-tools — Pro Tools Automation desktop tool\n"
            "Version: v%s (%s)\n" % (APP_VERSION, build_date()) +
            "Role: human-facing channel for the Pro Tools automation skill family\n\n"
            "Tech: tkinter GUI → skill scripts → PTSL (gRPC 127.0.0.1:31416)\n"
            "Depends on: protools-skills folder (bundles py-ptsl venv)\n"
            "Config & logs: %APPDATA%\\pt-tools\\\n"),
    },
}

_cur_lang = LANG_ZH


def set_lang(lang):
    global _cur_lang
    _cur_lang = lang if lang in (LANG_ZH, LANG_EN) else LANG_ZH


def T(key):
    """按当前语言取词条；缺词回退中文；再缺回 key 本身"""
    d = TEXTS.get(_cur_lang) or TEXTS[LANG_ZH]
    if key in d:
        return d[key]
    return TEXTS[LANG_ZH].get(key, key)


def detect_system_lang():
    try:
        import locale
        lc, _ = locale.getdefaultlocale()
        if lc and lc.lower().startswith("zh"):
            return LANG_ZH
    except Exception:
        pass
    return LANG_EN


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict):
            cfg = {}
    except (OSError, json.JSONDecodeError):
        cfg = {}
    cfg.setdefault("skills_root", "")
    cfg.setdefault("last_profile", "")
    cfg.setdefault("last_out_dir", "")
    cfg.setdefault("lang", detect_system_lang())
    return cfg


def save_config(cfg):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 路径解析：venv python（来自技能树）+ 脚本（优先 exe 内置 _internal\\skills）
# ---------------------------------------------------------------------------

class PathResolver:
    def __init__(self, skills_root):
        self.skills_root = skills_root

    # ---- 内置脚本（打包时复制进 dist\\_internal\\skills\\）----
    @staticmethod
    def _builtin_scripts_root():
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(sys.argv[0]))
        cand = os.path.join(base, "_internal", "skills")
        return cand if os.path.isdir(cand) else None

    @property
    def venv_python(self):
        return os.path.join(self.skills_root, "pt-exporter", "env", "venv",
                            "Scripts", "python.exe")

    def script(self, skill_name):
        builtin = self._builtin_scripts_root()
        if builtin:
            p = os.path.join(builtin, skill_name, "scripts", SCRIPTS[skill_name])
            if os.path.isfile(p):
                return p
        return os.path.join(self.skills_root, skill_name, "scripts",
                            SCRIPTS[skill_name])

    def status(self):
        """返回 (ok, msg)：技能目录可用性。

        判定顺序按「到底缺哪一环」排，而不是按目录是否存在 —— 打包后脚本已内置到
        `<exe目录>/_internal/skills/`，此时技能目录不存在并不等于脚本缺失。
        venv 因体积不随 exe 打包，是唯一**必须外置**的依赖，缺它时应给出可操作指引。
        """
        builtin = self._builtin_scripts_root()
        missing = [s for s in SCRIPTS if not os.path.isfile(self.script(s))]
        if missing:
            if not os.path.isdir(self.skills_root) and not builtin:
                return False, T("err_root_missing") % self.skills_root
            return False, T("err_scripts_missing") % ", ".join(missing)
        if not os.path.isfile(self.venv_python):
            if builtin:
                return False, T("err_venv_missing_builtin") % (self.venv_python,
                                                               DEFAULT_SKILLS_ROOT)
            return False, T("err_venv_missing") % self.venv_python
        return True, T("skills_ok") % self.skills_root

    @classmethod
    def detect(cls, cfg):
        """自动探测技能目录：配置值（用户显式设过）→ 环境变量 → 默认路径。
        返回 (resolver, ok, msg)，并把命中的目录回写配置。"""
        candidates = []
        if cfg.get("skills_root"):
            candidates.append(cfg["skills_root"])
        env = os.environ.get(ENV_SKILLS_ROOT)
        if env:
            candidates.append(env)
        candidates.append(DEFAULT_SKILLS_ROOT)

        for c in candidates:
            r = cls(c)
            ok, msg = r.status()
            if ok:
                if cfg.get("skills_root") != c:
                    cfg["skills_root"] = c
                    save_config(cfg)
                return r, True, msg
        r = cls(cfg.get("skills_root") or DEFAULT_SKILLS_ROOT)
        ok, msg = r.status()
        return r, ok, msg


# ---------------------------------------------------------------------------
# PTSL 在线探测（socket 端口，零依赖）
# ---------------------------------------------------------------------------

def ptsl_online():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect((PTSL_HOST, PTSL_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 后台命令执行（subprocess -> 队列 -> 主线程刷新 UI）
# ---------------------------------------------------------------------------

class CmdWorker(threading.Thread):
    def __init__(self, cmd, out_queue):
        super().__init__(daemon=True)
        self.cmd = cmd
        self.out_queue = out_queue
        self.proc = None

    def run(self):
        try:
            self.proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # 找不到 python 等
            self.out_queue.put(("line", T("err_cmd_start") % exc))
            self.out_queue.put(("done", 1))
            return
        for line in self.proc.stdout:
            self.out_queue.put(("line", line))
        self.proc.wait()
        self.out_queue.put(("done", self.proc.returncode))


# ---------------------------------------------------------------------------
# 共享工具（timecode 校验 / profile 读取）
# ---------------------------------------------------------------------------

def tc_to_frame(tc, fps):
    h, m, s, f = (int(x) for x in tc.split(":"))
    return ((h * 3600 + m * 60 + s) * fps) + f


def fmt_tc_ok(tc):
    return bool(TC_RE.match(tc or ""))


def load_profile(path):
    """读取并校验 pt-profile.json，失败抛 ValueError"""
    if not path or not os.path.isfile(path):
        raise ValueError(T("msg_profile_invalid") + "：%s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("session", "sources", "tracks"):
        if key not in data:
            raise ValueError("档案缺少字段 `%s`，可能是旧版档案，请重新扫描" % key)
    return data


def open_in_explorer(path):
    if path and os.path.isdir(path):
        os.startfile(path)  # noqa  Windows only
        return True
    return False


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # 三重保险消除 Tk 启动闪窗：
        #  Tk() 创建根窗口即按默认标题 "tk" 映射；withdraw 隐藏（窗口 unmapped，
        #  不可见也不接收输入），overrideredirect 使其不进任务栏，alpha=0 全透明
        #  兜底最后一张渲染帧。全部构建完成后一次性恢复显示。
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-alpha", 0.0)

        # 样式必须绑定本 root 配置（显式 master=self）。
        # 曾经的 bug：ttk.Style().configure(...) 在 App() 之前调用 —— 那时还没有任何
        # root，ttk.Style() 会隐式创建一个默认 Tk() root（标题 'tk'）；App() 随后再建
        # 第二个 root，结果永久残留一个空白「tk」小窗（withdraw 只作用于第二个 root）。
        # 传 master=self 保证复用本 root，绝不产生第二个窗口。
        try:
            ttk.Style(master=self).configure("Danger.TFrame", background="#b00")
        except tk.TclError:
            pass

        self.cfg = load_config()
        set_lang(self.cfg.get("lang", LANG_ZH))
        self.resolver, _ok, _msg = PathResolver.detect(self.cfg)
        self.profile_path = self.cfg.get("last_profile", "")
        self.profile_data = None
        self.ptsl_on = False

        self.out_queue = queue.Queue()
        self.workers = []
        self._vars = {}

        self._build_ui()
        self._restore_profile_to_tabs()

        self.after(100, self._poll_queue)
        self.after(1000, self._poll_ptsl)
        self._refresh_resolver_status()
        if self.profile_path:
            self._try_load_profile(self.profile_path)

        # 控件就绪后一次性显示
        self._center_on_screen()
        self.overrideredirect(False)
        self.attributes("-alpha", 1.0)
        self.deiconify()
        self.lift()
        self.focus_force()

    def _center_on_screen(self):
        """把窗口摆到屏幕中央（避免出现在左上角默认位置）"""
        try:
            self.update_idletasks()
            w = self.winfo_width() or 860
            h = self.winfo_height() or 680
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
            self.geometry("+%d+%d" % (x, y))
        except tk.TclError:
            pass

    # ---------------- UI 构建 / 重建 ----------------

    def _build_ui(self):
        self.title(T("app_title"))
        self.geometry("860x680")
        self.minsize(780, 600)
        self._build_menubar()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.scan_tab = ScanTab(nb, self)
        self.export_tab = ExportTab(nb, self)
        self.clean_tab = CleanTab(nb, self)
        nb.add(self.scan_tab, text=T("tab_scan"))
        nb.add(self.export_tab, text=T("tab_export"))
        nb.add(self.clean_tab, text=T("tab_clean"))
        self._build_log()
        self._build_statusbar()

    def _rebuild_ui(self):
        """语言切换/设置变更后整体重建（StringVar 快照恢复）"""
        vals = self._snapshot_vars()
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()
        self._restore_vars(vals)
        self._restore_profile_to_tabs()
        self._refresh_resolver_status()
        self.scan_tab.set_ptsl(self.ptsl_on)
        self._refresh_gating()

    def _restore_profile_to_tabs(self):
        """重建后把已加载的档案重新喂给各页（不弹框，失败仅日志）"""
        if self.profile_path and os.path.isfile(self.profile_path):
            try:
                data = load_profile(self.profile_path)
            except ValueError as exc:
                self.log(T("msg_warn_profile_start") % exc)
                return
            self.profile_data = data
            self.export_tab.on_profile_loaded(self.profile_path, data)
            self.clean_tab.on_profile_loaded(data)

    # ---------------- StringVar 登记 ----------------

    def v(self, name, default=""):
        var = tk.StringVar(value=default)
        self._vars[name] = var
        return var

    def _snapshot_vars(self):
        return {k: vg.get() for k, vg in self._vars.items()}

    def _restore_vars(self, vals):
        for k, val in vals.items():
            if k in self._vars:
                self._vars[k].set(val)

    # ---------------- 菜单栏 ----------------

    def _build_menubar(self):
        mb = tk.Menu(self)

        m_file = tk.Menu(mb, tearoff=0)
        m_file.add_command(label=T("file_open_outdir"), command=self._open_outdir)
        m_file.add_command(label=T("file_open_cfgdir"), command=self._open_cfgdir)
        m_file.add_separator()
        m_file.add_command(label=T("file_exit"), command=self.destroy)
        mb.add_cascade(label=T("menu_file"), menu=m_file)

        m_sett = tk.Menu(mb, tearoff=0)
        m_lang = tk.Menu(m_sett, tearoff=0)
        zh_label = ("✓ " if _cur_lang == LANG_ZH else "") + T("sett_lang_zh")
        en_label = ("✓ " if _cur_lang == LANG_EN else "") + T("sett_lang_en")
        m_lang.add_command(label=zh_label, command=lambda: self.set_language(LANG_ZH))
        m_lang.add_command(label=en_label, command=lambda: self.set_language(LANG_EN))
        m_sett.add_cascade(label=T("sett_lang"), menu=m_lang)
        m_sett.add_separator()
        m_sett.add_command(label=T("sett_skills"), command=self._browse_skills_root)
        m_sett.add_command(label=T("sett_outdir"), command=self._set_default_outdir)
        mb.add_cascade(label=T("menu_settings"), menu=m_sett)

        m_tools = tk.Menu(mb, tearoff=0)
        m_tools.add_command(label=T("tools_open_skills"), command=self._open_skills_dir)
        m_tools.add_command(label=T("tools_open_outdir"), command=self._open_outdir)
        m_tools.add_command(label=T("tools_open_cfgdir"), command=self._open_cfgdir)
        m_tools.add_separator()
        m_tools.add_command(label=T("tools_clear_log"), command=self._clear_log)
        mb.add_cascade(label=T("menu_tools"), menu=m_tools)

        m_help = tk.Menu(mb, tearoff=0)
        m_help.add_command(label=T("help_howto"), command=self._show_help)
        m_help.add_command(label=T("help_about"), command=self._show_about)
        mb.add_cascade(label=T("menu_help"), menu=m_help)

        self.config(menu=mb)

    def _open_outdir(self):
        d = self.cfg.get("last_out_dir", "")
        if not open_in_explorer(d):
            messagebox.showinfo(T("menu_file"), T("no_outdir"))

    def _open_cfgdir(self):
        os.makedirs(APP_DIR, exist_ok=True)
        os.startfile(APP_DIR)

    def _open_skills_dir(self):
        open_in_explorer(self.resolver.skills_root)

    def _browse_skills_root(self):
        chosen = filedialog.askdirectory(
            title=T("choose_skills_title"),
            initialdir=self.resolver.skills_root if os.path.isdir(self.resolver.skills_root) else None)
        if not chosen:
            return
        self.cfg["skills_root"] = chosen
        save_config(self.cfg)
        self.resolver = PathResolver(chosen)
        self._refresh_resolver_status()
        self.log("[cfg] 技能目录 -> %s\n" % chosen)

    def _set_default_outdir(self):
        chosen = filedialog.askdirectory(
            title=T("choose_outdir_title"),
            initialdir=self.cfg.get("last_out_dir") or None)
        if chosen:
            self.cfg["last_out_dir"] = chosen
            save_config(self.cfg)
            self._restore_vars({"export_out": chosen})
            self.log("[cfg] 默认输出目录 -> %s\n" % chosen)

    # ---------------- 语言切换 ----------------

    def set_language(self, lang):
        if lang == _cur_lang:
            return
        self.cfg["lang"] = lang
        save_config(self.cfg)
        set_lang(lang)
        self._rebuild_ui()
        self.log(T("lang_changed"))

    # ---------------- 日志 / 状态栏 ----------------

    def _build_log(self):
        frame = ttk.LabelFrame(self, text="  " + T("log_frame") + "  ", padding=(6, 4))
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        self.log_text = tk.Text(frame, height=9, wrap="word", undo=False,
                                font=("Consolas", 9))
        sb = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=8)
        ttk.Button(btn_row, text=T("log_clear"), command=self._clear_log,
                   width=16).pack(side="left")
        ttk.Label(btn_row, text=T("log_hint"),
                  foreground="#888").pack(side="right")

    def _build_statusbar(self):
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(fill="x")
        self.status_ptsl_var = tk.StringVar(value="…")
        self.status_sess_var = tk.StringVar(value=T("status_session") % "—")
        self.status_prof_var = tk.StringVar(value=T("status_profile") % "—")
        self.status_skills_var = tk.StringVar(value="…")
        ttk.Label(bar, textvariable=self.status_ptsl_var).pack(side="left")
        ttk.Label(bar, textvariable=self.status_sess_var,
                  foreground="#555").pack(side="left", padx=16)
        ttk.Label(bar, textvariable=self.status_prof_var,
                  foreground="#555").pack(side="left", padx=16)
        ttk.Label(bar, textvariable=self.status_skills_var,
                  foreground="#888").pack(side="right")

    def log(self, text):
        if not getattr(self, "log_text", None):
            return
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def _clear_log(self):
        if getattr(self, "log_text", None):
            self.log_text.delete("1.0", "end")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.out_queue.get_nowait()
                if kind == "line":
                    self.log(payload if payload.endswith("\n") else payload + "\n")
                elif kind == "done":
                    self._on_worker_done(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _on_worker_done(self, returncode):
        self.scan_tab.on_worker_done(returncode)
        self.export_tab.on_worker_done(returncode)
        self._refresh_gating()
        self.log(T("cmd_done") % returncode)

    def start_worker(self, cmd):
        self.log("> %s\n" % " ".join('"%s"' % c if " " in c else c for c in cmd))
        w = CmdWorker(cmd, self.out_queue)
        self.workers.append(w)
        w.start()
        return w

    # ---------------- 状态 ----------------

    def _poll_ptsl(self):
        on = ptsl_online()
        self.ptsl_on = on
        self.status_ptsl_var.set(T("status_ptsl_on") if on else T("status_ptsl_off"))
        self.scan_tab.set_ptsl(on)
        self._refresh_gating()
        self.after(5000, self._poll_ptsl)

    def _refresh_gating(self):
        self.scan_tab.refresh_buttons()
        self.export_tab.refresh_buttons()

    def _refresh_resolver_status(self):
        ok, _msg = self.resolver.status()
        self.status_skills_var.set(T("status_skills_ok") if ok
                                   else T("status_skills_bad"))
        if not ok:
            self.log("[warn] " + _msg + "\n")

    # ---------------- profile 共享 ----------------

    def apply_profile(self, path):
        """扫描完成后：应用档案到全局与各页"""
        try:
            data = load_profile(path)
        except ValueError as exc:
            messagebox.showerror(T("msg_profile_invalid"), str(exc))
            return False
        self.profile_path = path
        self.profile_data = data
        self.cfg["last_profile"] = path
        save_config(self.cfg)
        sess = data["session"]
        self.status_sess_var.set(T("status_session") % sess.get("name", "?"))
        self.status_prof_var.set(T("status_profile") % path)
        self.export_tab.on_profile_loaded(path, data)
        self.clean_tab.on_profile_loaded(data)
        return True

    def _try_load_profile(self, path):
        try:
            data = load_profile(path)
        except ValueError as exc:
            self.log(T("msg_warn_profile_start") % exc)
            return
        self.profile_data = data
        sess = data["session"]
        self.status_sess_var.set(T("status_session") % sess.get("name", "?"))
        self.status_prof_var.set(T("status_profile") % path)
        self.export_tab.on_profile_loaded(path, data)
        self.clean_tab.on_profile_loaded(data)

    # ---------------- 帮助 / 关于 ----------------

    def _show_help(self):
        win = tk.Toplevel(self)
        win.title(T("help_howto"))
        win.transient(self)
        win.geometry("560x430")
        t = tk.Text(win, wrap="word", padx=12, pady=12, font=("Microsoft YaHei UI", 10))
        t.insert("1.0", T("help_text"))
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)

    def _show_about(self):
        win = tk.Toplevel(self)
        win.title(T("help_about"))
        win.transient(self)
        win.geometry("460x260")
        t = tk.Text(win, wrap="word", padx=12, pady=12, font=("Microsoft YaHei UI", 10))
        t.insert("1.0", T("about_text"))
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)


# ---------------------------------------------------------------------------
# Tab 1 · 扫描建档
# ---------------------------------------------------------------------------

class ScanTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        self.busy = False
        self.last_profile_path = ""

        # —— 本页功能说明 ——
        what = ttk.LabelFrame(self, text="  " + T("s_what_title") + "  ", padding=8)
        what.pack(fill="x")
        ttk.Label(what, text=T("s_what_body"), wraplength=760,
                  justify="left").pack(anchor="w")

        # —— 扫描前提 + 步骤 ——
        cond = ttk.Frame(self)
        cond.pack(fill="x", pady=(8, 8))
        req = ttk.LabelFrame(cond, text="  " + T("s_req_title") + "  ", padding=8)
        req.pack(side="left", fill="x", expand=True)
        self.ptsl_label = ttk.Label(req, text=T("s_req_ptsl_off"))
        self.ptsl_label.pack(anchor="w")
        ttk.Label(req, text=T("s_req_line2"), foreground="#555").pack(anchor="w", pady=(2, 0))

        steps = ttk.LabelFrame(cond, text="  " + T("s_steps_title") + "  ", padding=8)
        steps.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Label(steps, text=T("s_step1")).pack(anchor="w")
        ttk.Label(steps, text=T("s_step2"), foreground="#555").pack(anchor="w", pady=(2, 0))
        ttk.Label(steps, text=T("s_step3"), foreground="#555").pack(anchor="w", pady=(2, 0))

        # —— 输出目录 / 档案名 / 扫描按钮 ——
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text=T("s_out")).pack(side="left")
        self.out_var = app.v("scan_out", app.cfg.get("last_out_dir", ""))
        ttk.Entry(row, textvariable=self.out_var, width=44).pack(side="left", padx=6)
        ttk.Button(row, text=T("s_browse"), command=self._browse_out,
                   width=10).pack(side="left")

        row2 = ttk.Frame(self)
        row2.pack(fill="x", pady=(0, 10))
        ttk.Label(row2, text=T("s_name")).pack(side="left")
        self.name_var = app.v("scan_name", "pt-profile.json")
        ttk.Entry(row2, textvariable=self.name_var, width=24).pack(side="left", padx=6)
        self.scan_btn = ttk.Button(row2, text=T("s_scan_btn"),
                                   command=self.do_scan)
        self.scan_btn.pack(side="left", padx=6)

        # —— 扫描摘要 ——
        summ = ttk.LabelFrame(self, text="  " + T("s_summary") + "  ", padding=6)
        summ.pack(fill="both", expand=True)
        self.summary_text = tk.Text(summ, height=12, wrap="word",
                                    font=("Consolas", 9), state="disabled")
        sb = ttk.Scrollbar(summ, command=self.summary_text.yview)
        self.summary_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.summary_text.pack(side="left", fill="both", expand=True)

    def _browse_out(self):
        chosen = filedialog.askdirectory(
            title=T("choose_outdir_title"),
            initialdir=self.out_var.get() or None)
        if chosen:
            self.out_var.set(chosen)
            self.app.cfg["last_out_dir"] = chosen
            save_config(self.app.cfg)

    def set_ptsl(self, on):
        if not getattr(self, "ptsl_label", None):
            return
        text = T("s_req_ptsl_on") if on else T("s_req_ptsl_off")
        color = "#0a0" if on else "#b00"
        self.ptsl_label.configure(text=text, foreground=color)

    def refresh_buttons(self):
        self.scan_btn.state(["disabled"] if (self.busy or not self.app.ptsl_on)
                            else ["!disabled"])

    def do_scan(self):
        out = self.out_var.get().strip()
        name = self.name_var.get().strip()
        if not out:
            messagebox.showerror(T("msg_missing"), T("s_missing_out"))
            return
        if not name.endswith(".json"):
            messagebox.showerror(T("msg_invalid"), T("s_bad_name"))
            return
        cmd = [self.app.resolver.venv_python,
               self.app.resolver.script("pt-scanner"),
               "--out", out, "--name", name]
        self.busy = True
        self.refresh_buttons()
        self.app.start_worker(cmd)

    def on_worker_done(self, returncode):
        if not self.busy:
            return
        self.busy = False
        if returncode == 0:
            path = os.path.join(self.out_var.get().strip(),
                                self.name_var.get().strip())
            self.last_profile_path = path
            self._show_summary(path)
            if self.app.apply_profile(path):
                self.app.log(T("s_auto_applied") % path)
        self.refresh_buttons()

    def _show_summary(self, path):
        try:
            data = load_profile(path)
        except ValueError as exc:
            self._set_summary(T("sum_err") % exc)
            return
        sess = data["session"]
        src = data["sources"]
        lines = [
            "%s: %s" % (T("sum_session"), sess.get("name", "?")),
            "%s: %s" % (T("sum_path"), sess.get("path", "?")),
            T("sum_rate") % (sess.get("sample_rate"), sess.get("bit_depth"),
                             sess.get("timecode_rate")),
            T("sum_range") % (sess.get("start_time"), sess.get("length")),
            "%s: %d" % (T("sum_tracks"), len(data.get("tracks", []))),
            "%s: %s" % (T("sum_bus"), ", ".join(src.get("bus", []))),
            "%s: %s" % (T("sum_output"), ", ".join(src.get("output", []))),
            "%s: %s" % (T("sum_phys"), ", ".join(src.get("physicalout", []))),
        ]
        self._set_summary("\n".join(lines) + "\n")

    def _set_summary(self, text):
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", text)
        self.summary_text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Tab 2 · 导出
# ---------------------------------------------------------------------------

class ExportTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        self.busy = False
        self.preview_ok = False
        self._profile_path = ""
        self._profile = None
        self._preview_signature = ""

        # -- 档案
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text=T("e_profile")).pack(side="left")
        self.profile_var = app.v("export_profile", app.profile_path)
        ttk.Entry(row, textvariable=self.profile_var, width=44).pack(side="left", padx=6)
        ttk.Button(row, text=T("e_browse"),
                   command=self._browse_profile).pack(side="left")

        # -- 模式 / 工程
        row2 = ttk.Frame(self)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text=T("e_mode")).pack(side="left")
        self.mode_var = app.v("export_mode", "stems")
        ttk.Radiobutton(row2, text=T("e_mode_mix"), value="mix",
                        variable=self.mode_var).pack(side="left", padx=4)
        ttk.Radiobutton(row2, text=T("e_mode_stems"), value="stems",
                        variable=self.mode_var).pack(side="left", padx=4)
        ttk.Label(row2, text="  " + T("e_session") + " ",
                  foreground="#555").pack(side="left", padx=(16, 0))
        self.sess_mode_var = app.v("sess_mode", "current")
        ttk.Radiobutton(row2, text=T("e_sess_current"), value="current",
                        variable=self.sess_mode_var).pack(side="left")
        ttk.Radiobutton(row2, text=T("e_sess_file"), value="file",
                        variable=self.sess_mode_var).pack(side="left")
        self.session_var = app.v("session_file", "")
        ttk.Entry(row2, textvariable=self.session_var, width=22,
                  state="readonly").pack(side="left", padx=4)
        ttk.Button(row2, text=T("e_browse"),
                   command=self._browse_session).pack(side="left")

        # -- source
        src = ttk.LabelFrame(self, text="  " + T("e_source_frame") + "  ", padding=6)
        src.pack(fill="both", expand=True, pady=(8, 0))
        srow = ttk.Frame(src)
        srow.pack(fill="x")
        ttk.Label(srow, text=T("e_stype")).pack(side="left")
        self.stype_var = app.v("src_type", "bus")
        self.stype_cb = ttk.Combobox(srow, textvariable=self.stype_var,
                                     values=SOURCE_TYPES, state="readonly", width=14)
        self.stype_cb.pack(side="left", padx=6)
        self.stype_cb.bind("<<ComboboxSelected>>", lambda e: self._reload_sources())
        ttk.Label(srow, text="  " + T("e_search") + " ",
                  foreground="#555").pack(side="left", padx=(16, 0))
        self.search_var = app.v("src_search", "")
        ttk.Entry(srow, textvariable=self.search_var, width=18).pack(side="left", padx=6)
        self.search_var.trace_add("write", lambda *a: self._reload_sources())
        self.src_count_var = tk.StringVar(value=T("e_selected") % 0)
        ttk.Label(srow, textvariable=self.src_count_var,
                  foreground="#555").pack(side="right")

        self.src_tree = ttk.Treeview(src, columns=("name",), show="headings",
                                     selectmode="extended", height=6)
        self.src_tree.heading("name", text=T("e_name_col"))
        self.src_tree.column("name", width=440)
        sb = ttk.Scrollbar(src, command=self.src_tree.yview)
        self.src_tree.configure(yscrollcommand=sb.set)
        self.src_tree.pack(side="left", fill="both", expand=True, pady=(4, 0))
        sb.pack(side="left", fill="y", pady=(4, 0))
        self.src_tree.bind("<<TreeviewSelect>>", self._on_src_select)

        # -- 时间 / 格式 / 输出
        opt = ttk.LabelFrame(self, text="  " + T("e_params") + "  ", padding=6)
        opt.pack(fill="x", pady=(8, 0))
        opt.columnconfigure(1, weight=3)
        opt.columnconfigure(3, weight=1)
        ttk.Label(opt, text=T("e_start")).grid(row=0, column=0, sticky="w")
        self.start_var = app.v("start", "00:00:00:00")
        ttk.Entry(opt, textvariable=self.start_var, width=14).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(opt, text=T("e_end")).grid(row=0, column=2, sticky="w")
        self.end_var = app.v("end", "")
        ttk.Entry(opt, textvariable=self.end_var, width=14).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(opt, text="  " + T("e_tc_hint"), foreground="#888").grid(row=0, column=4, sticky="w")

        ttk.Label(opt, text=T("e_sr")).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.sr_var = app.v("sample_rate", str(SAMPLE_RATES[0]))
        ttk.Combobox(opt, textvariable=self.sr_var, values=[str(x) for x in SAMPLE_RATES],
                     state="readonly", width=10).grid(row=1, column=1, sticky="w", padx=4, pady=(4, 0))
        ttk.Label(opt, text=T("e_bd")).grid(row=1, column=2, sticky="w", pady=(4, 0))
        self.bd_var = app.v("bit_depth", "24")
        ttk.Combobox(opt, textvariable=self.bd_var, values=[str(x) for x in BIT_DEPTHS],
                     state="readonly", width=8).grid(row=1, column=3, sticky="w", padx=4, pady=(4, 0))
        ttk.Label(opt, text=T("e_fmt")).grid(row=1, column=4, sticky="w", pady=(4, 0))
        self.fmt_var = app.v("format", "mono")
        ttk.Combobox(opt, textvariable=self.fmt_var, values=EXPORT_FORMATS,
                     state="readonly", width=12).grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(opt, text=T("e_out")).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.out_var = app.v("export_out", app.cfg.get("last_out_dir", ""))
        ttk.Entry(opt, textvariable=self.out_var).grid(row=2, column=1, columnspan=3, sticky="we", padx=4, pady=(4, 0))
        ttk.Button(opt, text=T("e_browse"), command=self._browse_out).grid(row=2, column=4, sticky="w", padx=4)

        # -- 操作按钮
        btnrow = ttk.Frame(self)
        btnrow.pack(fill="x", pady=(8, 0))
        self.preview_btn = ttk.Button(btnrow, text=T("e_preview"),
                                      command=self.do_preview)
        self.preview_btn.pack(side="left")
        self.export_btn = ttk.Button(btnrow, text=T("e_export"),
                                     command=self.do_export)
        self.export_btn.pack(side="left", padx=8)
        ttk.Label(btnrow, text=T("e_verify"),
                  foreground="#888").pack(side="right")

    # ---------------- 档案与数据 ----------------

    def _browse_profile(self):
        path = filedialog.askopenfilename(
            title=T("choose_profile_title"),
            filetypes=[("JSON", "*.json")],
            initialdir=os.path.dirname(self.profile_var.get()) if self.profile_var.get() else None)
        if path:
            self._load_profile(path)

    def on_profile_loaded(self, path, data):
        self._load_profile(path, data)

    def _load_profile(self, path, data=None):
        try:
            if data is None:
                data = load_profile(path)
        except ValueError as exc:
            messagebox.showerror(T("msg_profile_invalid"), str(exc))
            return
        self._profile_path = path
        self._profile = data
        self.profile_var.set(path)
        sess = data["session"]
        if not self.end_var.get() and sess.get("length"):
            self.end_var.set(sess["length"])
        sr = sess.get("sample_rate")
        if sr and str(sr) in [str(x) for x in SAMPLE_RATES]:
            self.sr_var.set(str(sr))
        self._reload_sources()
        self.refresh_buttons()

    def _reload_sources(self):
        self.src_tree.delete(*self.src_tree.get_children())
        if not self._profile:
            self._update_src_count()
            return
        stype = self.stype_var.get()
        names = self._profile.get("sources", {}).get(stype, []) or []
        q = self.search_var.get().strip().lower()
        for name in names:
            if q and q not in name.lower():
                continue
            self.src_tree.insert("", "end", iid=name, values=(name,))
        self._update_src_count()

    def _on_src_select(self, _evt=None):
        self._update_src_count()

    def _update_src_count(self):
        n = len(self.src_tree.selection())
        self.src_count_var.set(T("e_selected") % n)

    # ---------------- 参数收集与校验 ----------------

    def _selected_sources(self):
        return [self.src_tree.item(i)["values"][0]
                for i in self.src_tree.selection()]

    def _param_signature(self):
        return json.dumps({
            "profile": self._profile_path,
            "mode": self.mode_var.get(),
            "sources": self._selected_sources(),
            "stype": self.stype_var.get(),
            "start": self.start_var.get(),
            "end": self.end_var.get(),
            "sr": self.sr_var.get(),
            "bd": self.bd_var.get(),
            "fmt": self.fmt_var.get(),
            "out": self.out_var.get(),
            "session": self.session_var.get(),
        }, ensure_ascii=False)

    def _build_cmd(self, dry_run):
        """构造 CLI 参数（--profile 必须在子命令前）。失败抛 ValueError"""
        if not self._profile:
            raise ValueError(T("msg_no_profile"))
        sources = self._selected_sources()
        if not sources:
            raise ValueError(T("msg_no_source"))
        stype = self.stype_var.get()
        for s in sources:
            if stype not in self._profile.get("sources", {}):
                raise ValueError(T("msg_no_srctype") % stype)
            if s not in self._profile["sources"][stype]:
                raise ValueError(T("msg_src_unknown") % (s, stype))
        start = self.start_var.get().strip()
        end = self.end_var.get().strip()
        if not fmt_tc_ok(start) or not fmt_tc_ok(end):
            raise ValueError(T("msg_tc_bad"))
        fps = float(self._profile["session"].get("timecode_rate") or 25)
        if tc_to_frame(end, fps) <= tc_to_frame(start, fps):
            raise ValueError(T("msg_end_le"))
        out = self.out_var.get().strip()
        if not out:
            raise ValueError(T("msg_out_missing"))
        try:
            int(self.sr_var.get())
        except ValueError:
            raise ValueError(T("msg_sr_bad"))
        if self.sess_mode_var.get() == "file":
            sess = self.session_var.get().strip()
            if not sess:
                raise ValueError(T("msg_sess_missing"))
        else:
            sess = None

        cmd = [self.app.resolver.venv_python,
               self.app.resolver.script("pt-exporter"),
               "--profile", self._profile_path,
               self.mode_var.get()]
        for s in sources:
            cmd += ["--source", s]
        cmd += ["--source-type", stype,
                "--out", out,
                "--start", start, "--end", end,
                "--sample-rate", self.sr_var.get(),
                "--bit-depth", self.bd_var.get(),
                "--format", self.fmt_var.get()]
        if sess:
            cmd += ["--session", sess]
        if dry_run:
            cmd.append("--dry-run")
        return cmd

    # ---------------- 操作 ----------------

    def refresh_buttons(self):
        has_profile = self._profile is not None
        self.preview_btn.state(["disabled"] if
                               (self.busy or not has_profile) else ["!disabled"])
        can_export = (has_profile and self.preview_ok and self.app.ptsl_on
                      and not self.busy)
        self.export_btn.state(["disabled"] if not can_export else ["!disabled"])

    def do_preview(self):
        try:
            cmd = self._build_cmd(dry_run=True)
        except ValueError as exc:
            messagebox.showerror(T("msg_invalid"), str(exc))
            return
        self.busy = True
        self.refresh_buttons()
        self.preview_ok = False
        self._preview_signature = ""
        self.app.log(T("preview_start"))
        self.app.start_worker(cmd)

    def do_export(self):
        if not self.preview_ok:
            messagebox.showwarning(T("msg_preview_first_title"),
                                   T("msg_preview_first_body"))
            return
        try:
            cmd = self._build_cmd(dry_run=False)
        except ValueError as exc:
            messagebox.showerror(T("msg_invalid"), str(exc))
            return
        if not self.app.ptsl_on:
            messagebox.showerror(T("msg_invalid"), T("msg_ptsl_off_export"))
            return
        if not messagebox.askyesno(T("msg_confirm_title"), T("msg_confirm_body")):
            return
        self.busy = True
        self.refresh_buttons()
        self.app.start_worker(cmd)

    def on_worker_done(self, returncode):
        if not self.busy:
            return
        self.busy = False
        if returncode == 0:
            if self._preview_signature == "":
                self.preview_ok = True
                self._preview_signature = self._param_signature()
                self.app.log(T("preview_pass"))
            else:
                self.preview_ok = False
                self._preview_signature = ""
        self.refresh_buttons()

    # ---------------- 小工具 ----------------

    def _browse_out(self):
        chosen = filedialog.askdirectory(
            title=T("choose_outdir_title"),
            initialdir=self.out_var.get() or None)
        if chosen:
            self.out_var.set(chosen)
            self.app.cfg["last_out_dir"] = chosen
            save_config(self.app.cfg)

    def _browse_session(self):
        chosen = filedialog.askopenfilename(
            title=T("choose_ptx_title"),
            filetypes=[("Pro Tools Session", "*.ptx"), ("All", "*.*")])
        if chosen:
            self.session_var.set(chosen)


# ---------------------------------------------------------------------------
# Tab 3 · 清理（骨架置灰：需 PT 2025.10+）
# ---------------------------------------------------------------------------

class CleanTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app

        warn = ttk.Frame(self, style="Danger.TFrame")
        warn.pack(fill="x", pady=(0, 8))
        ttk.Label(
            warn,
            text=T("c_warn"),
            foreground="#fff", background="#b00").pack(padx=8, pady=6)

        info = ttk.LabelFrame(self, text="  " + T("c_cap") + "  ", padding=6)
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, text=T("c_cap1")).pack(anchor="w")
        ttk.Label(info, text=T("c_cap2")).pack(anchor="w", pady=(2, 0))
        ttk.Label(info, text=T("c_cap3")).pack(anchor="w", pady=(2, 0))

        form = ttk.LabelFrame(self, text="  " + T("c_params") + "  ", padding=6)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text=T("c_track_mode")).grid(row=0, column=0, sticky="w")
        self.track_tree = ttk.Treeview(form, columns=("name",), show="headings",
                                       height=6)
        self.track_tree.heading("name", text=T("c_track_col"))
        self.track_tree.column("name", width=420)
        self.track_tree.grid(row=1, column=0, columnspan=2, sticky="we", pady=4)
        ttk.Label(form, text=T("c_target_out")).grid(row=2, column=0, sticky="w")
        ttk.Label(form, text=T("c_backup")).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.track_tree.state(["disabled"])
        ttk.Label(form, text=T("c_note"),
                  foreground="#888").grid(row=4, column=0, sticky="w", pady=(12, 0))

    def on_profile_loaded(self, data):
        n = len(data.get("tracks", []))
        self.track_tree.delete(*self.track_tree.get_children())
        for t in data.get("tracks", [])[:200]:
            self.track_tree.insert("", "end", iid=t.get("name", ""),
                                   values=(t.get("name", ""),))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    app = App()
    _ok, _msg = app.resolver.status()
    if not _ok:
        messagebox.showwarning(T("skills_broken_title"),
                               _msg + "\n\n" + T("skills_broken_hint"))
        app.log("[warn] " + _msg + "\n")
    app.mainloop()


if __name__ == "__main__":
    main()