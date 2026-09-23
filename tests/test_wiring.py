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


# ───────── folder-builder ─────────
sys.path.insert(0, os.path.join(SRC, "pt-project-folder-builder"))
import folder_builder_gui as fb

TPL = fresh("fb_gui_tpl")
os.makedirs(os.path.join(TPL, "文件夹模板", "Audio"), exist_ok=True)
os.makedirs(os.path.join(TPL, "Project模板"), exist_ok=True)
open(os.path.join(TPL, "Project模板", "T.ptx"), "w").write("x")
OUT = fresh("fb_gui_out")


def fb_compute():
    app = fb.App()
    try:
        app.var_template.set(TPL)
        app.var_output.set(OUT)
        app.var_eps.set("1-3")
        app.var_name.set("誓言")
        app.var_seq.set("10")
        app.var_date.set("20260920")
        app.var_user.set("7F")
        got = app._compute()
        assert len(got) == 6, "App._compute 返回 %d 元组（应为 6）" % len(got)
        eps, errs, project_root, steps, warns, ep_names = got
        assert eps == [1, 2, 3], eps
        assert project_root.endswith("10-誓言D_20260920_7F"), project_root
        app._refresh_preview()          # 不应抛异常
        prev = app.preview.get("1.0", "end")
        assert "项目根" in prev and "分类目录" in prev, prev[:120]
        return "eps=%s steps=%d preview行=%d" % (eps, len(steps), prev.count("\n"))
    finally:
        app.destroy()


run("folder-builder App._compute/_refresh_preview 接线（回归 unpack 修复）", fb_compute)


def fb_apply():
    """模拟 _on_build worker 的落地逻辑，验证 steps 能真正建成。"""
    eps, errs, proj, steps, warns, ep_names = None, None, None, None, None, None
    proj, steps, warns, ep_names = fb.plan_creation(
        [1, 2, 3], "誓言", "10", "D", "20260920", "7F", OUT, TPL,
        "项目根", "重命名", "name_num")
    src_ptx = fb.locate_template_ptx(TPL)
    os.makedirs(proj, exist_ok=True)
    for action, path in steps:
        if action == "mkdir":
            os.makedirs(path, exist_ok=True)
        elif action == "copy":
            shutil.copy2(src_ptx, path)
    assert os.path.isdir(os.path.join(proj, "Audio")), os.listdir(proj)
    assert os.path.isfile(os.path.join(proj, "誓言1", "誓言1.ptx")), os.listdir(proj)
    assert len(os.listdir(proj)) == 4, os.listdir(proj)   # Audio + 3 集
    return "已建: %s" % sorted(os.listdir(proj))


run("folder-builder plan→落地（真建目录到沙箱）", fb_apply)


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
