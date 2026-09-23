# -*- coding: utf-8 -*-
"""pt-audio-toolkit 逐模块导入自检（不修改任何源文件）"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C                                    # noqa: E402

PY = C.PY
SRC = str(C.SRC)
JY = os.path.join(SRC, "jianying-draft-toolkit", "code")

CASES = [
    ("pt-tools/gui",            os.path.join(SRC, "pt-tools"),              "import pt_tools_gui"),
    ("folder-builder/gui",      os.path.join(SRC, "pt-project-folder-builder"), "import folder_builder_gui"),
    ("rename-unify/config",     os.path.join(SRC, "rename-unify", "code"),  "import config"),
    ("rename-unify/core_rules", os.path.join(SRC, "rename-unify", "code"),  "import core_rules"),
    ("rename-unify/main",       os.path.join(SRC, "rename-unify", "code"),  "import main"),
    ("jianying/core.config",    JY, "from core import config"),
    ("jianying/core.host",      JY, "from core import host"),
    ("jianying/core.menus",     JY, "from core import menus"),
    ("jianying/aaf_writer",     JY, "import aaf_writer"),
    ("jianying/main",           JY, "import main"),
    ("jianying/gui",            JY, "import gui"),
    ("jianying/import_audio",   JY, "import import_audio"),
    ("jianying/pt_clip_scan",   JY, "import pt_clip_scan"),
    ("jianying/make_delivery",  JY, "import make_delivery_package"),
    ("jianying/tabs.*",         JY, "import tabs.base, tabs.export_tab, tabs.import_tab, tabs.delivery_tab, tabs.paths_dialog"),
]

for name, cwd, code in CASES:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        p = subprocess.run([PY, "-c", code], cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=90, env=env)
        ok = p.returncode == 0
        detail = (p.stdout or "").strip() + (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        ok, detail = False, "TIMEOUT(90s) —— 疑似导入时阻塞（等待输入/网络/GUI）"
    # 缺第三方可选依赖（如 py-ptsl）属环境不满足 → SKIP，不计入失败
    if not ok and "ModuleNotFoundError" in detail:
        last = (detail.strip().splitlines() or [""])[-1]
        C.record(name, C.SKIP, "缺可选依赖：" + last)
    else:
        C.record(name, C.PASS if ok else C.FAIL, detail)

sys.exit(C.report("导入自检结果"))
