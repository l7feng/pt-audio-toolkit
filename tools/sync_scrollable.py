#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `rename-unify/code/scrollable.py` 的 ScrollableFrame 同步到另外两处。

三处同源（工具各自独立打包，不引公共包）：

1. `src/rename-unify/code/scrollable.py`（**权威源**，改这个）
2. `src/pt-tools/ptools/gui/scrollable.py`（整文件复制）
3. `src/jianying-draft-toolkit/code/tabs/base.py::__ScrollableFrame__`（类体替换）

为什么要有脚本：2026-09-27 实测发现三份已经漂移（base.py 版多了一行
`tk.Toplevel` 让位判断），人手同步必然会漏。改完跑一次本脚本，
`tests/test_scroll_sync.py` 会做最终断言。

用法::

    python tools/sync_scrollable.py            # 同步
    python tools/sync_scrollable.py --check    # 只检查是否一致，不一致退出码 1
"""

from __future__ import annotations

import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "rename-unify" / "code" / "scrollable.py"
DST_PT = ROOT / "src" / "pt-tools" / "ptools" / "gui" / "scrollable.py"
DST_JY = ROOT / "src" / "jianying-draft-toolkit" / "code" / "tabs" / "base.py"

ANCHOR_START = "class ScrollableFrame(ttk.Frame):"
ANCHOR_END = "class BaseTab(ttk.Frame):"


def class_body(text: str) -> str:
    """取源文件中从类定义到结尾的部分。"""
    i = text.index(ANCHOR_START)
    return text[i:].rstrip() + "\n"


def check() -> int:
    src = SRC.read_text(encoding="utf-8")
    body = class_body(src)
    pt = DST_PT.read_text(encoding="utf-8")
    jy = DST_JY.read_text(encoding="utf-8")
    ok = True
    if pt != src:
        print("[FAIL] pt-tools/scrollable.py 与权威源不一致")
        ok = False
    if body not in jy:
        print("[FAIL] jianying tabs/base.py 内嵌 ScrollableFrame 与权威源不一致")
        ok = False
    if ok:
        print("[OK] 三处 ScrollableFrame 一致")
    return 0 if ok else 1


def sync() -> int:
    src = SRC.read_text(encoding="utf-8")
    body = class_body(src)

    shutil.copyfile(SRC, DST_PT)
    print("  → 已复制：%s" % DST_PT.relative_to(ROOT))

    jy = DST_JY.read_text(encoding="utf-8")
    a = jy.index(ANCHOR_START)
    b = jy.index(ANCHOR_END)
    DST_JY.write_text(jy[:a] + body + "\n\n" + jy[b:], encoding="utf-8")
    print("  → 已替换：%s 内嵌 ScrollableFrame" % DST_JY.relative_to(ROOT))
    return check()


def main() -> int:
    if "--check" in sys.argv:
        return check()
    print("同步 ScrollableFrame（源：%s）" % SRC.relative_to(ROOT))
    rc = sync()
    if rc:
        print("⚠ 同步后仍不一致，请手工核对")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
