# -*- coding: utf-8 -*-
"""滚动日志（W1 三层拆分 · core/logs）。

RotatingFileHandler 1MB × 3，UTF-8；任何失败返回 None ——
日志绝不影响主流程。D2 起并入「导出诊断包」。
"""
import os
from .settings import APP_DIR, APP_VERSION, build_date

# 日志文件落点（W4 起 = exe 旁，与配置同目录；D2 起并入「导出诊断包」）
LOG_FILE = os.path.join(APP_DIR, "pt-tools.log")

# ---------------------------------------------------------------------------
# 日志（滚动文件落配置目录，失败静默）
# ---------------------------------------------------------------------------

def setup_logging():
    """初始化独立滚动日志到 **exe 旁**（W4 迁移）/pt-tools.log。

    返回 logger（失败返回 None，日志绝不影响主流程）。
    日志会并入「工具 → 导出诊断包」一键打包上报。
    """
    try:
        import logging
        from logging.handlers import RotatingFileHandler
        os.makedirs(APP_DIR, exist_ok=True)
        path = LOG_FILE
        logger = logging.getLogger("pt-tools")
        if not logger.handlers:
            handler = RotatingFileHandler(path, maxBytes=1_000_000,
                                          backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.info("=== pt-tools v%s (%s) 启动 ===", APP_VERSION, build_date())
        return logger
    except Exception:
        return None
