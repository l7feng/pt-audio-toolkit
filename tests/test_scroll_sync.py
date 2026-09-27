#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三处 ScrollableFrame 同源一致性（S8，2026-09-27）。

背景：滚动容器在三个工具里各存一份（工具独立打包，不引公共包）。
2026-09-27 实测发现三份已经漂移 —— 剪映 `tabs/base.py` 的内嵌版比另两份
多一行 `tk.Toplevel` 让位判断。改一处漏两处是必然事件，所以加机器断言。

同步方法：改 `src/rename-unify/code/scrollable.py` 后跑
`python tools/sync_scrollable.py`。
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "rename-unify" / "code" / "scrollable.py"
DST_PT = ROOT / "src" / "pt-tools" / "ptools" / "gui" / "scrollable.py"
DST_JY = ROOT / "src" / "jianying-draft-toolkit" / "code" / "tabs" / "base.py"

ANCHOR_START = "class ScrollableFrame(ttk.Frame):"
ANCHOR_END = "class BaseTab(ttk.Frame):"

FAILED = []


def _check(cond, name, detail=""):
    if cond:
        print("  ✅ %s" % name)
    else:
        print("  ❌ %s %s" % (name, detail))
        FAILED.append(name)


def main():
    src = SRC.read_text(encoding="utf-8")
    pt = DST_PT.read_text(encoding="utf-8")
    jy = DST_JY.read_text(encoding="utf-8")

    _check(SRC.is_file() and DST_PT.is_file() and DST_JY.is_file(),
           "三份文件都存在")

    body = src[src.index(ANCHOR_START):].rstrip()
    _check(pt == src, "pt-tools/scrollable.py 与权威源逐字节一致",
           "(跑 tools/sync_scrollable.py 修复)")
    _check(body in jy, "剪映 tabs/base.py 内嵌版类体与权威源一致",
           "(跑 tools/sync_scrollable.py 修复)")

    # S8 手感重做的关键特征，三份都必须有（防止同步到旧版本）
    for name, text in (("权威源", src), ("pt-tools", pt), ("剪映内嵌", jy)):
        _check("STEP_DELTA" in text, "%s 含 delta 累加器（触控板可滚）" % name)
        _check('xview_scroll(-delta, "pixels")' in text,
               "%s 横滚按像素" % name)
        _check("_pan_move" in text, "%s 含中键拖拽平移" % name)
        _check("_hint_hscroll" in text, "%s 含横滚手势提示" % name)
        _check("bind_all(\"<MouseWheel>\", self._on_wheel, add=\"+\")" in text,
               "%s 滚轮绑定带 add=+（修切页失效）" % name)

    print()
    if FAILED:
        print("❌ %d 项未通过：%s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("✅ 三处 ScrollableFrame 同源一致，S8 特征齐全")
    return 0


if __name__ == "__main__":
    sys.exit(main())
