# -*- coding: utf-8 -*-
"""rename-unify 配置与路径（单一来源，避免两处各猜 frozen）

⚠️ frozen 模式下代码在 _internal\\ 里（只读、可能被清理），
   配置/日志/回溯日志绝不能写代码目录 —— 一律落 exe 旁（APP_DIR）。
"""
import json
import os
import sys

APP_NAME = "rename-unify"
# 四工具统一口径：版本号 X.Y.Z（不带 v 前缀），显示时补 v（见 title()）。
APP_VERSION = "1.1.0"


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
    # 命名实体清单（可勾选）：空 = 不启用过滤（等于旧行为）；见 core_rules.DEFAULT_ENABLED_TYPES
    "enabled_types": [],
    # 执行完改名后自动按集归位（平铺分类目录 → 集文件夹）
    "regroup_after": False,
    "regroup_root": "",       # 归位目标；空 = 用 last_root
    "regroup_cleanup": True,  # 归位后清理搬空的类别文件夹
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
    # enabled_types 逐项清洗，容忍手改配置写坏结构
    out["enabled_types"] = _clean_enabled_types(cfg.get("enabled_types"))
    return out


def _clean_enabled_types(raw):
    """规范化命名实体清单：只留已知字段，补齐缺省，丢掉无 type 的项。"""
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        t = str(e.get("type", "")).strip()
        if not t:
            continue
        en = e.get("enabled", True)
        out.append({
            "type": t,
            "enabled": bool(en) if isinstance(en, bool) else str(en).strip().lower() not in ("0", "false", "no", ""),
            "eps": str(e.get("eps", "") or "").strip(),
            "note": str(e.get("note", "") or "").strip(),
        })
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
    return "统一命名工具 v%s (%s)" % (APP_VERSION, build_date())
