# -*- coding: utf-8 -*-
"""配置读取 / 保存 / 迁移（W1 三层拆分 · core/config）。

只补缺省、绝不擦用户已存键；全部 OSError 静默（配置异常不挡启动）。
"""
import json
import os
from .i18n import detect_system_lang
from .settings import (
    APP_DIR, CONFIG_FILE,
    DEFAULT_EXPORT_FORMAT, DEFAULT_FALLBACK_DURATION,
    DEFAULT_OUT_ROOT, DEFAULT_PROFILE_DIR, DEFAULT_VIDEO_MARGIN,
)


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
    # v1.4.0：档案目录 / 输出根的出厂默认（老配置缺键时补，不覆盖已设值）
    cfg.setdefault("profile_dir", DEFAULT_PROFILE_DIR)
    if not str(cfg.get("last_out_dir") or "").strip():
        cfg["last_out_dir"] = DEFAULT_OUT_ROOT
    _migrate_cfg(cfg)
    return cfg


def _migrate_cfg(cfg):
    """配置迁移（只补缺省 / 升级已知坏值，绝不擦掉用户已存的其它键）。

    v1.3.0（cfg_version 1 → 2）三处默认值修正，都是"旧默认会把活悄悄做错"：
      ① format：旧默认 `mono` 会把立体声**下混**，用户完全不知情 → interleaved
      ② video_margin：旧默认 240s，每条片子都被加 4 分钟尾巴 → 0
      ③ fallback_duration：旧默认 240s，没检出视频时**假装片子 4 分钟**
        （6 分钟的片会被悄悄截断）→ 60
    v1.4.0（cfg_version 2 → 3）默认路径收口：
      ④ profile_dir 缺省 → PT-Tools-Backup/json（建档输出 + 档案浏览默认目录）
      ⑤ last_out_dir 为空 → PT-Tools-Backup/out
    用户若手工改过这些值，一律保留，不覆盖。
    """
    ver = int(cfg.get("cfg_version") or 0)
    if ver >= 3:
        return
    if ver < 2:
        if cfg.get("format") in (None, "", "mono"):
            cfg["format"] = DEFAULT_EXPORT_FORMAT
        if _as_int(cfg.get("video_margin")) in (None, 240):
            cfg["video_margin"] = DEFAULT_VIDEO_MARGIN
        if _as_int(cfg.get("fallback_duration")) in (None, 240):
            cfg["fallback_duration"] = DEFAULT_FALLBACK_DURATION
    if not str(cfg.get("profile_dir") or "").strip():
        cfg["profile_dir"] = DEFAULT_PROFILE_DIR
    if not str(cfg.get("last_out_dir") or "").strip():
        cfg["last_out_dir"] = DEFAULT_OUT_ROOT
    cfg["cfg_version"] = 3


def _as_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def save_config(cfg):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass
