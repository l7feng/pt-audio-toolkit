#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/menus.py — 菜单动作层（L1 分层：领域层）

菜单栏的**业务动作**收敛在这里，``tabs`` / ``gui`` 只负责「画菜单 + 调本模块」。
理由与 L1 铁律一致：
  · UI 层（gui.py）不该长业务逻辑 —— 否则以后加一项菜单就要改视图代码；
  · 动作要能被复用 —— 「恢复默认路径」既在菜单里，也可能被「设置」对话框调用；
  · 本模块只依赖标准库 + ``core.config``，不 import tkinter，可单测。

菜单项分四组（对应用户高频动作）：

  文件  保存全部配置 / 重新载入配置 / 打开配置文件 / 打开配置文件夹 / 退出
  设置  默认路径设置…（本工具核心诉求）/ 恢复全部默认值
  工具  环境自检 / 刷新状态 / 清理立体声合成缓存 / 打开临时目录
  帮助  使用说明 / 关于

**为什么菜单里要有「默认路径设置」**：三页的输入/输出目录分散在各自标签页，
用户每次换工作目录都要切页逐个改。菜单提供一处集中设置，且**能存成默认**——
下次开 exe 直接就是这套路径，不用重新指。

设计约定（沿用本项目既有风格）：
  · 路径类默认值一律写进 config.json（APP_DIR），不写代码目录；
  · 「恢复默认」只回滚**路径类字段**，不动用户调好的格式/模板等参数；
  · 清理缓存只删自己生成的临时目录，绝不动用户文件。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from . import config as cfg_mod

# ──────────────────── 路径类字段（「恢复默认路径」的作用范围）────────────────────
# 只管「在哪儿读、往哪儿写」，不碰格式/模板/开关等调参项 —— 那些是用户调好的，不该被重置。
# v2.6.0：新增 log_dir（导出日志）/ data_dir（运行数据），与产物目录分离。
PATH_KEYS = ("input_dir", "output_dir", "log_dir", "data_dir", "temp_dir",
             "import_draft_dir", "import_pkg_out")

# 立体声合成缓存目录名（import_audio.py 生成，见其 resolve 逻辑）
STEREO_CACHE_DIRNAME = "jy_audio_import_stereo"


def app_dir() -> Path:
    """可变文件落点（config.json / 交付包）。由 main 注入，见 core.config。"""
    return cfg_mod.APP_DIR


def config_file() -> Path:
    """配置文件路径（含首次运行的旧位置迁移）。"""
    return cfg_mod.config_path()


# ──────────────────── ① 文件 ────────────────────

def reload_config() -> dict:
    """从磁盘重新读配置（把外部手改的内容拉回内存）。

    返回合并了默认值之后的 dict；调用方负责把值刷回各页控件。
    """
    disk = cfg_mod.load_config(config_file()) or {}
    merged = {**cfg_mod.DEFAULT_CONFIG, **cfg_mod.DEFAULT_IMPORT_CONFIG, **disk}
    return merged


def reveal(path: Path, select: bool = False) -> None:
    """在资源管理器里打开目录（或选中文件）。失败抛异常由调用方提示。"""
    p = Path(path)
    if p.is_file() or (select and p.exists()):
        import os
        os.startfile(str(p.parent))            # type: ignore[attr-defined]
    elif p.is_dir():
        import os
        os.startfile(str(p))                   # type: ignore[attr-defined]
    else:
        raise FileNotFoundError(str(p))


# ──────────────────── ② 设置：默认路径 ────────────────────

def default_paths() -> dict:
    """返回「默认路径设置」对话框要展示的 7 个字段及当前值。

    ``{key: (标签, 说明, 当前值)}`` —— 与 ``CONFIG_FIELDS`` 同风格，
    但只取路径类字段（对话框只关心这几个）。
    """
    cur = {**cfg_mod.DEFAULT_CONFIG, **cfg_mod.DEFAULT_IMPORT_CONFIG}
    try:
        cur.update(cfg_mod.load_config(config_file()) or {})
    except Exception:
        pass
    labels = {
        "input_dir": ("剪映草稿目录", "出厂默认 = Jianying-Backup 草稿库；清空 = 自动定位剪映默认草稿目录"),
        "output_dir": ("① 导出音频的输出目录", "必填；产物按 <草稿名>/<集名>/01-多条WAV|02-素材片段|03-AAF 分组"),
        "log_dir": ("导出日志目录", "导出日志.log 的落点；留空 = 输出目录根"),
        "data_dir": ("运行数据目录", "processed_drafts.txt（断点续跑）/ tmp 临时文件的落点；留空 = 输出目录根"),
        "temp_dir": ("临时目录", "出厂默认 = Tools/tmp；留空 = 数据目录/tmp"),
        "import_draft_dir": ("② 导入多轨的默认目标草稿", "可选；留空 = 每次在下拉里选（下拉列表来自上方草稿目录）"),
        "import_pkg_out": ("③ 生成交付包的输出目录", "PTSL 解析结果 json 的落点；交付包在此下建 <工程名>-导入包/"),
    }
    return {k: (labels[k][0], labels[k][1], str(cur.get(k, "") or ""))
            for k in PATH_KEYS}


def apply_paths(new_vals: dict) -> Path:
    """把对话框结果写进 config.json（合并式，不碰其他字段）。返回配置文件路径。

    ``new_vals`` 只需含路径类字段；缺的键保持磁盘原值。
    """
    path = config_file()
    disk: dict = {}
    if path.is_file():
        try:
            disk = cfg_mod.load_config(path) or {}
        except Exception:
            disk = {}
    for k in PATH_KEYS:
        if k in new_vals:
            disk[k] = str(new_vals[k] or "").strip()
    cfg_mod.save_config(disk, path)
    return path


def restore_default_paths() -> dict:
    """把路径类字段回滚为出厂默认；**其余调参项原样保留**。返回被改动的键值。

    刻意只重置路径：用户花时间调好的命名模板 / 规格 / 开关不该被一次误点清掉。
    """
    path = config_file()
    disk: dict = {}
    if path.is_file():
        try:
            disk = cfg_mod.load_config(path) or {}
        except Exception:
            disk = {}
    changed = {}
    for k in PATH_KEYS:
        default = cfg_mod.DEFAULT_CONFIG.get(
            k, cfg_mod.DEFAULT_IMPORT_CONFIG.get(k, ""))
        if disk.get(k) != default:
            changed[k] = default
        disk[k] = default
    cfg_mod.save_config(disk, path)
    return changed


# ──────────────────── ③ 工具：缓存 ────────────────────

def stereo_cache_dir() -> Path:
    """立体声合成缓存的候选目录（可能不存在）。

    与 ``import_audio`` 的落点规则保持一致：交付包场景在包内 ``audio/_stereo_cache``，
    否则回落系统临时目录 ``%TEMP%/jy_audio_import_stereo``。这里返回后者
    （前者随交付包走，不该由本工具清理）。
    """
    return Path(tempfile.gettempdir()) / STEREO_CACHE_DIRNAME


def stereo_cache_info() -> tuple:
    """返回 ``(文件数, 总字节数)``，目录不存在则 ``(0, 0)``。"""
    d = stereo_cache_dir()
    if not d.is_dir():
        return 0, 0
    n = 0
    size = 0
    try:
        for f in d.rglob("*"):
            if f.is_file():
                n += 1
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return n, size


def clear_stereo_cache() -> tuple:
    """清空立体声合成缓存。返回 ``(删除文件数, 释放字节数)``。

    只删自己生成的缓存目录整体；目录不存在视为「本来就干净」（返回 0,0），不报错。
    """
    d = stereo_cache_dir()
    n, size = stereo_cache_info()
    if not d.is_dir():
        return 0, 0
    shutil.rmtree(d, ignore_errors=True)
    return n, size


def human_size(num_bytes: float) -> str:
    """人类可读体积。"""
    b = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} GB"


# ──────────────────── ④ 帮助：关于信息 ────────────────────

def about_lines(version: str, build_date: str) -> list:
    """「关于」对话框正文（版本 / 构建日期 / 配置文件 / 三页职责）。"""
    return [
        f"剪映工程工具包  v{version}",
        f"构建日期：{build_date}",
        "",
        "一个 exe，三件独立的事：",
        "  ① 导出音频    剪映草稿 → 切片/整轨导出（不需要 Pro Tools）",
        "  ② 导入多轨    .ptx（需 PT 在线）/ 交付包 json（离线）→ 写剪映草稿",
        "  ③ 生成交付包  json 路径相对化 + 音频随包（只做数据）",
        "",
        f"配置文件：{config_file()}",
        f"程序目录：{app_dir()}",
        "",
        "工作目录说明：",
        "  D:\\My-Temporary\\Jianying-Backup\\ 是工具的工作目录（草稿库 + 产物）",
        "  它【不是】临时目录，请勿删除——删除将丢失草稿库与历史导出产物",
        "",
        "前置条件速查：",
        "  解析 .ptx  需要 PT 在线（剪映开否无关）",
        "  导入草稿   需要剪映关闭（PT 开否无关）",
        "  生成交付包 无任何要求",
    ]
