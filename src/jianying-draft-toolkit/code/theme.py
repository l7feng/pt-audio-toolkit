# -*- coding: utf-8 -*-
"""共享视觉主题（S13 / v3.10.0）—— 同源三副本之一。

副本规则（与 scrollable.py 相同）：
  ① src/pt-tools/ptools/gui/theme.py         ← 权威源
  ② src/rename-unify/code/theme.py           ← 整文件复制
  ③ src/jianying-draft-toolkit/code/theme.py  ← 整文件复制
改一必须同步二三。

设计取向（2026-09-28 裁决 D3-甲）：参考 Claude Desktop / opencode 的 UI 风格——
浅色米白底、低饱和、细边框、扁平克制；主按钮一个强调色，删除类按钮标红。
不做图标、不做深色模式。

用法：
    import theme
    theme.apply(root)                      # 入口：一次性装配全部 ttk 样式
    root.geometry(theme.initial_geometry(cfg.get("window"), root))   # S12
    theme.window_size(root)                # 关闭前取 "WxH" 存回 cfg["window"]
    ttk.Button(..., style="Accent.TButton")  # 主按钮（开始/导出/执行）
    ttk.Button(..., style="Danger.TButton")  # 危险按钮（删除/清空/中止）
"""

import re
import tkinter as tk
from tkinter import ttk

# ── 调色板（低饱和 · 米白暖灰）─────────────────────────────────
BG         = "#f7f6f3"   # 窗口底
SURFACE    = "#ffffff"   # 卡片 / 输入框 / 表格底
BORDER     = "#e2dfda"   # 细边框
FG         = "#2b2a28"   # 正文
FG_DIM     = "#8a8781"   # 次要文字
ACCENT     = "#c96442"   # 主按钮（陶橙，Claude 系）
ACCENT_HV  = "#b4552f"   # 主按钮悬停 / 按下
DANGER     = "#b3372f"   # 删除 / 清空 / 中止
DANGER_HV  = "#992c25"
SELECT_BG  = "#ece9e2"   # 选中底
HEAD_BG    = "#f1efeb"   # 表头底

FONT       = ("Microsoft YaHei UI", 9)
FONT_BOLD  = ("Microsoft YaHei UI", 9, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")

MIN_W, MIN_H = 900, 620   # S12：三工具统一最小尺寸


def apply(root):
    """一次性装配主题。幂等：重复调用无害。"""
    st = ttk.Style(root)
    # clam：tkinter 自带主题里唯一能完整控制配色的底子
    # （vista/w10 是系统原生渲染，不吃 configure 的颜色，做不了扁平浅色）
    try:
        st.theme_use("clam")
    except Exception:
        pass
    st.configure(".", background=BG, foreground=FG, font=FONT,
                 bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                 troughcolor=BG, selectbackground=SELECT_BG, selectforeground=FG)
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("TButton", background=SURFACE, foreground=FG, font=FONT,
                 bordercolor=BORDER, lightcolor=SURFACE, darkcolor=BORDER,
                 relief="flat", padding=(10, 4), focusthickness=1)
    st.map("TButton",
           background=[("pressed", "#e8e5df"), ("active", "#f2f0ec")],
           lightcolor=[("pressed", "#e8e5df")],
           darkcolor=[("pressed", "#e8e5df")])
    # 主按钮（Accent）
    st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                 font=FONT_BOLD, bordercolor=ACCENT, lightcolor=ACCENT,
                 darkcolor=ACCENT, relief="flat", padding=(14, 4))
    st.map("Accent.TButton",
           background=[("disabled", "#d8c2b8"),
                       ("pressed", ACCENT_HV), ("active", ACCENT_HV)],
           foreground=[("disabled", "#f2e6e0")],
           lightcolor=[("pressed", ACCENT_HV), ("active", ACCENT_HV)],
           darkcolor=[("pressed", ACCENT_HV), ("active", ACCENT_HV)])
    # 危险按钮（Danger）
    st.configure("Danger.TButton", background=DANGER, foreground="#ffffff",
                 font=FONT_BOLD, bordercolor=DANGER, lightcolor=DANGER,
                 darkcolor=DANGER, relief="flat", padding=(10, 4))
    st.map("Danger.TButton",
           background=[("disabled", "#d3b9b6"),
                       ("pressed", DANGER_HV), ("active", DANGER_HV)],
           foreground=[("disabled", "#f0e2e0")],
           lightcolor=[("pressed", DANGER_HV), ("active", DANGER_HV)],
           darkcolor=[("pressed", DANGER_HV), ("active", DANGER_HV)])
    # 输入类
    st.configure("TEntry", fieldbackground=SURFACE, foreground=FG,
                 bordercolor=BORDER, lightcolor=BORDER, insertcolor=FG, padding=2)
    st.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE,
                 foreground=FG, bordercolor=BORDER, lightcolor=BORDER,
                 arrowcolor=FG_DIM, padding=2)
    st.map("TCombobox",
           fieldbackground=[("readonly", SURFACE)],
           bordercolor=[("active", ACCENT)])
    # 页签
    st.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(8, 6, 8, 0))
    st.configure("TNotebook.Tab", background=BG, foreground=FG_DIM, padding=(14, 6),
                 font=FONT)
    st.map("TNotebook.Tab",
           background=[("selected", SURFACE)],
           foreground=[("selected", FG)])
    # 表格
    st.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                 foreground=FG, bordercolor=BORDER, rowheight=26, font=FONT)
    st.configure("Treeview.Heading", background=HEAD_BG, foreground=FG_DIM,
                 bordercolor=BORDER, relief="flat", font=FONT_BOLD, padding=(6, 4))
    st.map("Treeview",
           background=[("selected", SELECT_BG)],
           foreground=[("selected", FG)])
    st.map("Treeview.Heading", background=[("active", HEAD_BG)])
    # 滚动条（clam 下可调窄、去立体）
    st.configure("TScrollbar", background=BG, troughcolor=BG, bordercolor=BG,
                 arrowcolor=FG_DIM, relief="flat")
    st.map("TScrollbar", background=[("active", "#e8e5df")])
    # 进度条 / 分隔线 / 分组框
    st.configure("TProgressbar", background=ACCENT, troughcolor=BG, bordercolor=BG)
    st.configure("Separator", background=BORDER)
    st.configure("TLabelframe", background=BG, bordercolor=BORDER)
    st.configure("TLabelframe.Label", background=BG, foreground=FG)
    try:
        root.configure(background=BG)
    except Exception:
        pass
    return st


# ── S12：窗口几何（记住上次 + 首次自适应）─────────────────────

def initial_geometry(saved=None, root=None, min_w=MIN_W, min_h=MIN_H):
    """cfg 有记录 → 用记录（钳到 minsize）；无记录 → 按屏幕自适应。

    1920x1080 屏 → 1180x842（比例 1.40）；更大屏幕封顶 1180x860，
    避免 4K 上开出一个占不满也用不上的巨窗。
    """
    if saved:
        m = re.match(r"^\s*(\d+)x(\d+)\s*$", str(saved))
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            return "%dx%d" % (max(w, min_w), max(h, min_h))
    try:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    except Exception:
        sw, sh = 1920, 1080
    w = min(int(sw * 0.62), 1180)
    h = min(int(sh * 0.78), 860)
    return "%dx%d" % (max(w, min_w), max(h, min_h))


def window_size(win):
    """关闭前取当前尺寸 "WxH"（去掉 "+x+y" 位置部分），失败返回空串。"""
    try:
        return win.geometry().split("+")[0]
    except Exception:
        return ""
