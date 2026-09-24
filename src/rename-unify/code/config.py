# -*- coding: utf-8 -*-
"""rename-unify 配置与路径（单一来源，避免两处各猜 frozen）

⚠️ frozen 模式下代码在 _internal\\ 里（只读、可能被清理），
   配置/日志/回溯日志绝不能写代码目录 —— 一律落 exe 旁（APP_DIR）。
"""
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

APP_NAME = "rename-unify"
# 四工具统一口径：版本号 X.Y.Z（不带 v 前缀），显示时补 v（见 title()）。
# v1.5.0（2026-09-24）：R1 执行前审计 json（rename_audit_*.json）+ 按审计跨会话回滚
#   + R3 规则集导出/导入。
APP_VERSION = "1.5.0"


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
    # 全局模板：目标没在「目标表」里单独配模板时用它兜底
    "template": "{片名} {集数}集 {日期} {版本} {用户}_{轨道信息}",
    "fields": {"片名": "前夫", "日期": "0920", "版本": "V01", "用户": "7F"},
    "rules": [],          # 空 = 用 core_rules.DEFAULT_RULES
    # 模板库（页1 可增删改）：空 = 用 core_rules.DEFAULT_TEMPLATES
    "templates": [],
    # 目标表（页2「目标与归位」）：空 = 用 core_rules.DEFAULT_TARGETS
    # 每项 = {name, dir, enabled, eps, note, templates[], tpl_name}
    "targets": [],
    # v1.3.0 开关：
    # date_from_mtime —— 源名/集目录都没有日期时，用文件修改时间(MMDD)兜底
    #   （导出时刻，与手工标注 100% 吻合；优先级：源名 > 多数票 > mtime > 全局）
    "date_from_mtime": True,
    # rename_ep_dirs —— 集目录名统一按「片名 N集 日期 版本 用户」渲染改名
    #   （13/ → 法老 13集 0922 V01 7F/）；关掉 = 沿用旧「就地不改名」行为
    "rename_ep_dirs": True,
    # ⚠️ 仅作 v1.1.0 → v1.2.0 的迁移源：旧「命名清单」会被折成目标表
    #    （core.migrate_enabled_types），新配置不再写这个键。
    "enabled_types": [],
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
    raw_fields = cfg.get("fields") if isinstance(cfg.get("fields"), dict) else {}
    f = dict(DEFAULTS["fields"])
    if raw_fields:
        f.update({str(k): str(v) for k, v in raw_fields.items()})
    # v1.1.0 的「档位」→ v1.2.0 的「用户」（7F 是用户代号，不是「档位」）。
    # ⚠️ 判据必须看**旧配置原文** raw_fields，不能看合并后的 f：
    #    DEFAULTS 里「用户」已带占位值 7F，用 f 判断会误认为「用户已设过」，
    #    导致旧配置的「档位」被静默丢掉（2026-09-23 回归抓到的 bug）。
    if "档位" in raw_fields and not str(raw_fields.get("用户", "") or "").strip():
        f["用户"] = str(raw_fields["档位"])
    f.pop("档位", None)
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


def setup_logging():
    """初始化滚动日志到 app_dir()/rename-unify.log（W2 骨架）。

    配置/日志/回溯日志一律落 exe 旁（APP_DIR），不写代码目录。
    返回 logger；失败静默返回 None（日志绝不影响主流程）。
    """
    try:
        os.makedirs(app_dir(), exist_ok=True)
        path = os.path.join(app_dir(), "rename-unify.log")
        logger = logging.getLogger("rename-unify")
        if not logger.handlers:
            handler = RotatingFileHandler(path, maxBytes=1_000_000,
                                          backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.info("=== rename-unify v%s (%s) 启动 ===",
                        APP_VERSION, build_date())
        return logger
    except Exception:
        return None
