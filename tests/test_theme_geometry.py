# -*- coding: utf-8 -*-
"""S11/S12/S13 专项测试：表格列宽自适应 · 窗口几何 · 多色彩主题。

覆盖：
  · theme.py 六套主题注册表完整性（每套 16 色键）
  · apply / set_theme / current_theme_name 运行时切换
  · 颜色工具函数（_lighten / _darken / _is_dark / _dim）
  · initial_geometry（有记录 / 无记录 / 钳到 minsize）
  · window_size
  · columns.fit_tree_columns（建树 → 触发 Configure → 列宽按权重重分配）
  · 三副本同源一致性（theme.py ×3 / columns.py ×3 MD5 比对）
"""
import os
import sys
import hashlib
from pathlib import Path

# 确保带 tkinter 的解释器
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_tk, case, run_case, report, SRC, PASS, FAIL  # noqa: E402

ensure_tk()

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

# ── 定位三份 theme.py / columns.py ──
PT_THEME = SRC / "pt-tools" / "ptools" / "gui" / "theme.py"
RU_THEME = SRC / "rename-unify" / "code" / "theme.py"
JY_THEME = SRC / "jianying-draft-toolkit" / "code" / "theme.py"
PT_COL = SRC / "pt-tools" / "ptools" / "gui" / "columns.py"
RU_COL = SRC / "rename-unify" / "code" / "columns.py"
JY_COL = SRC / "jianying-draft-toolkit" / "code" / "columns.py"

REQUIRED_COLOR_KEYS = {"BG", "SURFACE", "BORDER", "FG", "FG_DIM",
                        "ACCENT", "ACCENT_HV", "DANGER", "DANGER_HV",
                        "SELECT_BG", "HEAD_BG", "SUCCESS", "WARNING", "INFO", "label"}


def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ── 用例 ──

@case("theme 注册表：六套主题齐全")
def t_themes_count():
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    names = [k for k, _ in theme.list_themes()]
    assert set(names) == {"warm", "emerald", "nord", "dark", "contrast", "ocean"}, \
        "期望 6 套主题，实际: %s" % names
    assert theme.DEFAULT_THEME == "warm"
    return "6 套: %s" % ", ".join(names)


@case("theme 每套主题 16 色键完整")
def t_theme_keys():
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    missing = []
    for name, pal in theme.THEMES.items():
        keys = set(pal.keys())
        if not REQUIRED_COLOR_KEYS.issubset(keys):
            missing.append("%s 缺: %s" % (name, REQUIRED_COLOR_KEYS - keys))
    assert not missing, "; ".join(missing)
    return "6 套 × 16 色键全部齐全"


@case("theme 颜色值均为合法 #rrggbb")
def t_theme_color_format():
    import re
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    pat = re.compile(r"^#[0-9a-fA-F]{6}$")
    bad = []
    for name, pal in theme.THEMES.items():
        for k, v in pal.items():
            if k == "label":
                continue
            if not pat.match(v):
                bad.append("%s.%s=%r" % (name, k, v))
    assert not bad, "非法颜色值: %s" % "; ".join(bad[:10])
    return "全部颜色值格式合法"


@case("theme apply：建 root + apply 不抛异常")
def t_apply():
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    root = tk.Tk()
    root.withdraw()
    try:
        st = theme.apply(root, theme_name="warm")
        assert st is not None
        assert theme.current_theme_name() == "warm"
        # 验证关键样式已配置
        assert st.lookup("Accent.TButton", "background") is not None
        assert st.lookup("Danger.TButton", "background") is not None
    finally:
        root.destroy()
    return "apply(warm) 成功，Accent/Danger 样式已注册"


@case("theme set_theme：运行时切换 warm→dark→emerald→nord→ocean→contrast")
def t_set_theme():
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    root = tk.Tk()
    root.withdraw()
    try:
        theme.apply(root, theme_name="warm")
        for target in ("dark", "emerald", "nord", "ocean", "contrast", "warm"):
            actual = theme.set_theme(root, target)
            assert actual == target, "期望 %s，实际 %s" % (target, actual)
            assert theme.current_theme_name() == target
        # 未知主题回落默认
        actual = theme.set_theme(root, "nonexistent")
        assert actual == "warm"
    finally:
        root.destroy()
    return "6套主题循环切换成功，未知主题回落 warm"


@case("theme 颜色工具：_lighten / _darken / _dim")
def t_color_utils():
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    # _lighten: #000000 + 255 = #ffffff
    assert theme._lighten("#000000", 255) == "#ffffff"
    # _darken: #ffffff - 255 = #000000
    assert theme._darken("#ffffff", 255) == "#000000"
    # _dim: 向 bg 混合 55%
    result = theme._dim("#ffffff", "#000000")
    r, g, b = theme._hex_to_rgb(result)
    # 白(255)*0.45 + 黑(0)*0.55 ≈ 114.75 → 114
    assert 110 <= r <= 120, "dim 结果异常: %s (r=%d)" % (result, r)
    # _is_dark: warm 的 FG 是深色 → False；dark 的 FG 是浅色 → True
    assert theme._is_dark(theme.THEMES["warm"]) is False
    assert theme._is_dark(theme.THEMES["dark"]) is True
    return "_lighten/_darken/_dim/_is_dark 全部正确"


@case("geometry initial_geometry：有记录时用记录并钳到 minsize")
def t_geometry_saved():
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    root = tk.Tk()
    root.withdraw()
    try:
        # 正常记录
        g = theme.initial_geometry("1000x700", root)
        assert g == "1000x700", g
        # 小于 minsize → 钳到 900x620
        g = theme.initial_geometry("500x300", root)
        assert g == "900x620", g
        # 非法格式 → 回落自适应
        g = theme.initial_geometry("abc", root)
        w, h = g.split("x")
        assert int(w) >= 900 and int(h) >= 620
    finally:
        root.destroy()
    return "记录/钳位/非法格式回落 全部正确"


@case("geometry initial_geometry：无记录时按屏幕自适应")
def t_geometry_auto():
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    root = tk.Tk()
    root.withdraw()
    try:
        g = theme.initial_geometry(None, root)
        w, h = (int(x) for x in g.split("x"))
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        # 不超过屏幕 62%/78%，封顶 1180/860，不低于 minsize
        assert w <= min(int(sw * 0.62), 1180) + 1
        assert h <= min(int(sh * 0.78), 860) + 1
        assert w >= 900 and h >= 620
    finally:
        root.destroy()
    return "自适应尺寸在合理范围内: %s" % g


@case("geometry window_size：取当前窗口尺寸")
def t_window_size():
    sys.path.insert(0, str(PT_THEME.parent))
    import theme
    root = tk.Tk()
    root.withdraw()
    try:
        root.geometry("1024x768+100+100")
        root.update_idletasks()
        s = theme.window_size(root)
        assert s == "1024x768", "期望 1024x768，实际 %r" % s
    finally:
        root.destroy()
    return "window_size 返回 '1024x768'（去掉 +x+y）"


@case("columns fit_tree_columns：建树后列宽按权重重分配")
def t_fit_columns():
    sys.path.insert(0, str(PT_COL.parent))
    from columns import fit_tree_columns
    root = tk.Tk()
    root.withdraw()
    try:
        # 建一个 3 列的树，初始列宽 100/200/300（合计 600）
        tree = ttk.Treeview(root, columns=("a", "b", "c"), show="headings")
        tree.column("a", width=100)
        tree.column("b", width=200)
        tree.column("c", width=300)
        fit_tree_columns(tree, min_widths={"a": 40, "b": 60, "c": 80})
        tree.pack(fill="both", expand=True)
        root.update_idletasks()
        root.geometry("800x400")
        root.update_idletasks()
        # 触发 after_idle 的重排
        root.update()
        root.after(50, root.quit)
        root.mainloop()
        wa = tree.column("a", "width")
        wb = tree.column("b", "width")
        wc = tree.column("c", "width")
        total = wa + wb + wc
        # 三列按权重 1:2:3 分配，比例应大致保持
        ratio_b = wb / max(wa, 1)
        ratio_c = wc / max(wa, 1)
        assert 1.5 < ratio_b < 2.5, "b/a 比例异常: %.2f (wa=%d wb=%d)" % (ratio_b, wa, wb)
        assert 2.5 < ratio_c < 3.5, "c/a 比例异常: %.2f (wa=%d wc=%d)" % (ratio_c, wa, wc)
        # 不低于最小宽
        assert wa >= 40 and wb >= 60 and wc >= 80
    finally:
        root.destroy()
    return "列宽按 1:2:3 权重重分配 (a=%d b=%d c=%d, 合计=%d)" % (wa, wb, wc, total)


@case("同源一致性：theme.py 三份 MD5 相同")
def t_theme_md5():
    h1, h2, h3 = _md5(PT_THEME), _md5(RU_THEME), _md5(JY_THEME)
    assert h1 == h2 == h3, "MD5 不一致: pt=%s ru=%s jy=%s" % (h1[:8], h2[:8], h3[:8])
    return "三份一致 (%s)" % h1[:8]


@case("同源一致性：columns.py 三份 MD5 相同")
def t_columns_md5():
    h1, h2, h3 = _md5(PT_COL), _md5(RU_COL), _md5(JY_COL)
    assert h1 == h2 == h3, "MD5 不一致: pt=%s ru=%s jy=%s" % (h1[:8], h2[:8], h3[:8])
    return "三份一致 (%s)" % h1[:8]


# ── 运行 ──
if __name__ == "__main__":
    code = report("S11/S12/S13 专项测试结果（列宽自适应 · 窗口几何 · 多色彩主题）")
    sys.exit(code)
