# -*- coding: utf-8 -*-
"""pt-tools 入口（W1 三层拆分 · v1.5.0 起兼任 --batch CLI）。

两层入口，按参数分流：
  * 无参数         → GUI（三层包 ptools，本文件只是 38 行薄壳公共面）
  * --batch <jobs> → W8 夜间批量 CLI：绝不能先建 Tk；jobs.json 由 GUI
                     批量对话框「保存任务清单…」生成，输出落 exe 旁
                     pt-batch-<时间戳>.log（--windowed exe 无控制台）。

维护约定：
- 新增公共名字 → 在对应层包定义，这里只加一行 re-export。
- 原单文件已备份为 `pt_tools_gui.w1d2.bak`。
"""
import os
import sys

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


def _cli_batch(argv):
    """--batch CLI（W8）：跑批量导出，输出进日志文件，返回退出码。"""
    import datetime
    from ptools.core.settings import APP_DIR, APP_VERSION, build_date
    from ptools.worker.batch_cli import run_batch

    jobs = ""
    if "--batch" in argv:
        i = argv.index("--batch")
        if i + 1 < len(argv):
            jobs = argv[i + 1]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(APP_DIR, "pt-batch-%s.log" % stamp)
    lines = ["pt-tools v%s (%s) --batch" % (APP_VERSION, build_date()),
             "开始时间: %s" % stamp]

    def log(text):
        lines.append(str(text))
        try:                                   # 源码模式/重定向时可见；windowed 静默
            sys.stdout.write(str(text) + "\n")
            sys.stdout.flush()
        except Exception:
            pass

    if not jobs:
        log("[错误] 用法: pt-tools --batch <jobs.json>")
        rc = 2
    else:
        rc = run_batch(jobs, log)
    lines.append("EXIT rc=%d  结束时间: %s"
                 % (rc, datetime.datetime.now().strftime("%H:%M:%S")))
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass
    return rc


if __name__ == "__main__":
    if "--batch" in sys.argv:
        sys.exit(_cli_batch(sys.argv))
    main()
