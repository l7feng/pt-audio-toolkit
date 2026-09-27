# -*- coding: utf-8 -*-
"""folder-builder GUI↔核心接线 + pt-tools 命令执行层（无 PT 环境可跑的部分）"""
import os
import shutil
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

# tkinter 必须在本脚本任何 import 之前就绪：入口解释器没有它时先自愈重启。
# （注意顺序 —— 原版把 `import tkinter` 放在 _common 之前，换解释器即崩）
C.ensure_tk()
import tkinter as tk                                   # noqa: E402

SRC = str(C.SRC)
SB = str(C.SANDBOX)

# 用例登记与沙箱目录一律走公共模块（区分 FAIL / ERROR / SKIP）
run = C.run_case
fresh = C.fresh


# (folder-builder 已并入 rename-unify 第5页签；GUI 接线归 rename-unify 冒烟覆盖)
# ───────── pt-tools ─────────
def pt_resolver():
    sys.path.insert(0, os.path.join(SRC, "pt-tools"))
    import pt_tools_gui as pt
    cfg = {"skills_root": ""}
    r, ok, msg = pt.PathResolver.detect(cfg)
    assert ok, msg
    assert r.script("pt-scanner").endswith("pt_scan.py")
    return "%s -> %s" % (r.skills_root, msg)


run("pt-tools PathResolver.detect 技能目录自检", pt_resolver)


def pt_worker():
    import queue
    sys.path.insert(0, os.path.join(SRC, "pt-tools"))
    import pt_tools_gui as pt
    q = queue.Queue()
    w = pt.CmdWorker([sys.executable, "-c", "print('hello-cmdworker')"], q)
    w.start()
    w.join(timeout=60)
    lines = []
    while not q.empty():
        lines.append(q.get())
    txt = "\n".join(str(x) for x in lines)
    assert "hello-cmdworker" in txt, txt
    return "CmdWorker 输出: %s" % txt.strip().splitlines()[-1][:60]


run("pt-tools CmdWorker subprocess→队列 链路", pt_worker)


def pt_gui_tabs():
    app_src = os.path.join(SRC, "pt-tools")
    sys.path.insert(0, app_src)
    import pt_tools_gui as pt
    app = pt.App()
    try:
        tabs = [w for w in app.winfo_children()]
        assert tabs, "App 无子控件"
        app.after(50, app.quit)
        app.update()
        return "App 建成，顶层控件 %d 个" % len(tabs)
    finally:
        app.destroy()


run("pt-tools App 三标签页构建", pt_gui_tabs)


sys.exit(C.report("接线层测试结果"))
