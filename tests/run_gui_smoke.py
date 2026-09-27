# -*- coding: utf-8 -*-
"""GUI 冒烟总调度：3 个界面逐个起（独立子进程 + 超时），失败继续下一条。"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

PY = C.PY
HERE = os.path.dirname(os.path.abspath(__file__))
# 2026-09-27：folder-builder 已退役（能力并入 rename-unify 第 5 页签）
TARGETS = [("pt-tools", "pt"),
           ("rename-unify", "rename"), ("jianying-draft-toolkit", "jy")]

for label, key in TARGETS:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        p = subprocess.run([PY, "-B", os.path.join(HERE, "gui_smoke_one.py"), key],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, env=env)
        raw = (p.stdout or "") + (p.stderr or "")
        ok = "SMOKE_OK" in raw
    except subprocess.TimeoutExpired:
        ok, raw = False, "TIMEOUT(120s) —— 建窗后未能在 600ms 内销毁，疑似阻塞"
    C.record(label, C.PASS if ok else C.FAIL, " ".join(raw.split()))

sys.exit(C.report("GUI 冒烟结果"))
