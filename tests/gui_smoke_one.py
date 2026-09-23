# -*- coding: utf-8 -*-
"""单个 GUI 冒烟：建窗 → 600ms 后自动销毁（子进程调用，便于超时控制）"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

SRC = str(C.SRC)
which = sys.argv[1]

try:
    import tkinter as tk

    if which == "folder":
        sys.path.insert(0, os.path.join(SRC, "pt-project-folder-builder"))
        import folder_builder_gui as m
        app = m.App()
        win = app
    elif which == "rename":
        sys.path.insert(0, os.path.join(SRC, "rename-unify", "code"))
        import main as m
        app = m.App()
        win = app
    elif which == "pt":
        sys.path.insert(0, os.path.join(SRC, "pt-tools"))
        import pt_tools_gui as m
        app = m.App()
        win = app
    elif which == "jy":
        sys.path.insert(0, os.path.join(SRC, "jianying-draft-toolkit", "code"))
        import gui as m
        root = tk.Tk()
        app = m.JianYingToolkitApp(root)
        win = root
    else:
        raise SystemExit("unknown target: %s" % which)

    title = win.title()
    win.after(600, win.destroy)
    win.mainloop()
    print("SMOKE_OK title=%r" % title)
except Exception:
    print("SMOKE_FAIL")
    traceback.print_exc()
    sys.exit(1)
