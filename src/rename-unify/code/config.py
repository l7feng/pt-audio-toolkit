# -*- coding: utf-8 -*-
"""rename-unify 配置与路径（单一来源，避免两处各猜 frozen）

⚠️ frozen 模式下代码在 _internal\\ 里（只读、可能被清理），
   配置/日志/回溯日志绝不能写代码目录 —— 一律落 exe 旁（APP_DIR）。
"""
import json
import os
import sys

APP_NAME = "rename-unify"
APP_VERSION = "v1.0.0"


def app_dir():
    """可写目录：frozen 取 exe 旁，源码模式取项目根。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def asset_dir():
    """只读资源目录：frozen 时是 _internal。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(app_dir(), "config.json")

DEFAULTS = {
    "last_root": r"D:\DAW-Project",
    "recursive": True,
    "exts": ".wav .aif .aiff .mp3 .flac .w64",
    "template": "{片名} {集数}集 {日期} {版本} {档位}_{类型}",
    "fields": {"片名": "前夫", "日期": "0920", "版本": "V01", "档位": "7F"},
    "rules": [],          # 空 = 用 core_rules.DEFAULT_RULES
    "window": "1180x760",
}


def load_config():
    cfg = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg = data
    except (OSError, json.JSONDecodeError):
        cfg = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    # fields 做逐键合并，避免用户配置缺键导致 KeyError
    f = dict(DEFAULTS["fields"])
    if isinstance(cfg.get("fields"), dict):
        f.update({str(k): str(v) for k, v in cfg["fields"].items()})
    out["fields"] = f
    return out


def save_config(cfg):
    try:
        os.makedirs(app_dir(), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def build_date():
    """构建日期：frozen 取 exe 修改时间，源码模式取本文件时间。

    ⚠️ sys.executable 是 str，必须先包一层 Path 再 .stat()。
    """
    try:
        from pathlib import Path
        src = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
        import datetime
        return datetime.datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d")
    except Exception:
        return "未知"


def title():
    return "统一命名工具 %s (%s)" % (APP_VERSION, build_date())
