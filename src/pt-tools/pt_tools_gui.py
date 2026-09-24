# -*- coding: utf-8 -*-
"""pt-tools 入口薄壳（W1 三层拆分 · 取代原 3449 行单文件）。

领域层 core / 执行层 worker / 展现层 gui 已拆为独立包（统一挂在
`ptools` 命名空间下，避免与 jianying 的顶层 `core` 包撞名）；本文件只是
对接测试与旧调用习惯的**公共面**：原 `import pt_tools_gui as pt` 的
5 个名字在这里一键 re-export，新增逻辑一律落到对应层，不许回填 monolith。

维护约定：
- 新增公共名字 → 在对应层包定义，这里只加一行 re-export。
- 原单文件已备份为 `pt_tools_gui.w1d2.bak`。
"""
from ptools.core.i18n import (             # noqa: F401
    T,
    set_lang,
    get_lang,
    detect_system_lang,
    LANG_ZH,
    LANG_EN,
)
from ptools.core.config import load_config, save_config      # noqa: F401
from ptools.core.paths import PathResolver      # noqa: F401  ← PathResolver.detect / .script
from ptools.core.naming import (               # noqa: F401
    build_export_cmds,
    parse_video_duration_output,
)
from ptools.core.logs import setup_logging     # noqa: F401
from ptools.core.notify import toast           # noqa: F401
from ptools.worker.runner import CmdWorker, ptsl_online   # noqa: F401
from ptools.gui.app import App, main as _gui_main   # noqa: F401  ← App + 页签 + main


def main():                                   # 委托 gui.app 的唯一入口（含技能状态告警）
    _gui_main()


if __name__ == "__main__":
    main()
