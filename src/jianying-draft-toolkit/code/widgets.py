# -*- coding: utf-8 -*-
"""自绘组件库（v3.12.0）—— Canvas 矢量图标 + 现代控件，突破 tkinter 原生视觉瓶颈。

同源三副本（与 theme.py 相同规则）：
  ① src/pt-tools/ptools/gui/widgets.py     ← 权威源
  ② src/rename-unify/code/widgets.py        ← 整文件复制
  ③ src/jianying-draft-toolkit/code/widgets.py ← 整文件复制

组件清单：
  · draw_icon()      矢量图标绘制（30+ 图标，24x24 线条风格，主题感知）
  · IconButton       Canvas 图标按钮（图标+文字，hover/press 反馈）
  · ToggleSwitch     iOS 风格开关（滑动动画）
  · StatusLED        状态指示灯（呼吸动画）
  · Badge            徽章标签
  · ProgressRing     圆形进度环
  · Tooltip          工具提示气泡
  · CollapsibleFrame 可折叠面板（chevron 旋转）
  · HoverCard        可点击卡片（hover 高亮 + hand2）
  · SideNav          侧边垂直导航栏（图标+文字，选中态）
  · Segmented        分段控制器
  · attach_tree_hover()  Treeview 行 hover 高亮
  · attach_drop_highlight() 拖拽区域高亮
"""
import tkinter as tk
from tkinter import ttk
try:
    from theme import current_theme_name, THEMES, FONT_BODY, FONT_BOLD, FONT_SMALL, \
        FONT_SUBTITLE, FONT_TITLE, PAD_XS, PAD_SM, PAD_MD, PAD_LG, PAD_XL
except ImportError:  # pt-tools 包结构
    from ptools.gui.theme import (current_theme_name, THEMES, FONT_BODY, FONT_BOLD,
        FONT_SMALL, FONT_SUBTITLE, FONT_TITLE, PAD_XS, PAD_SM, PAD_MD, PAD_LG, PAD_XL)


# ══════════════════════════════════════════════════════════════════
# 配色辅助（跟随当前主题）
# ══════════════════════════════════════════════════════════════════

def _pal():
    """取当前主题完整色板（基础 + 派生色），未 apply 时回落 warm。"""
    try:
        try:
            from theme import get_colors
        except ImportError:
            from ptools.gui.theme import get_colors
        return get_colors()
    except Exception:
        name = current_theme_name() or "warm"
        return dict(THEMES.get(name, THEMES["warm"]))


def _mix(c1, c2, t):
    """颜色混合：t=0 全 c1，t=1 全 c2。"""
    def hx(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    a, b = hx(c1), hx(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ══════════════════════════════════════════════════════════════════
# 矢量图标系统（24x24 线条风格，参考 Lucide/Feather）
# ══════════════════════════════════════════════════════════════════
# 每个 _ic_xxx(cv, x, y, s, color, w) 在 cv 的 (x,y) 处绘制尺寸 s 的图标，
# 返回 item id 列表。坐标基于 0..24，绘制时按 s/24 缩放。

def _pts(points, x, y, s):
    """把 24 网格坐标点缩放到实际像素。"""
    k = s / 24.0
    return [x + p * k if i % 2 == 0 else y + p * k
            for i, p in enumerate(points)]


def _ic_play(cv, x, y, s, c, w):
    return [cv.create_polygon(_pts([7, 5, 19, 12, 7, 19], x, y, s),
                              fill=c, outline=c, width=w)]


def _ic_square(cv, x, y, s, c, w):
    p = _pts([7, 7, 17, 7, 17, 17, 7, 17], x, y, s)
    return [cv.create_polygon(p, fill=c, outline=c)]


def _ic_pause(cv, x, y, s, c, w):
    p1 = _pts([8, 6, 10, 6, 10, 18, 8, 18], x, y, s)
    p2 = _pts([14, 6, 16, 6, 16, 18, 14, 18], x, y, s)
    return [cv.create_polygon(p1, fill=c), cv.create_polygon(p2, fill=c)]


def _ic_folder(cv, x, y, s, c, w):
    k = s / 24.0
    items = [cv.create_polygon(
        _pts([3, 7, 9, 7, 11, 9, 21, 9, 21, 18, 3, 18], x, y, s),
        outline=c, fill="", width=w, joinstyle=tk.ROUND)]
    return items


def _ic_search(cv, x, y, s, c, w):
    k = s / 24.0
    r = 6 * k
    cx, cy = x + 10 * k, y + 10 * k
    items = [cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=c, width=w),
             cv.create_line(x + 15 * k, y + 15 * k, x + 20 * k, y + 20 * k,
                            fill=c, width=w, capstyle=tk.ROUND)]
    return items


def _ic_gear(cv, x, y, s, c, w):
    import math
    k = s / 24.0
    cx, cy = x + 12 * k, y + 12 * k
    items = []
    # 8 齿
    teeth = []
    for i in range(16):
        ang = math.pi / 8 * i
        rr = (9 if i % 2 == 0 else 7) * k
        teeth.extend([cx + rr * math.cos(ang), cy + rr * math.sin(ang)])
    items.append(cv.create_polygon(teeth, outline=c, fill="", width=w,
                                   smooth=False))
    items.append(cv.create_oval(cx - 3.5 * k, cy - 3.5 * k,
                                cx + 3.5 * k, cy + 3.5 * k, outline=c, width=w))
    return items


def _ic_plus(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_line(x + 12 * k, y + 5 * k, x + 12 * k, y + 19 * k,
                           fill=c, width=w, capstyle=tk.ROUND),
            cv.create_line(x + 5 * k, y + 12 * k, x + 19 * k, y + 12 * k,
                           fill=c, width=w, capstyle=tk.ROUND)]


def _ic_minus(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_line(x + 5 * k, y + 12 * k, x + 19 * k, y + 12 * k,
                           fill=c, width=w, capstyle=tk.ROUND)]


def _ic_trash(cv, x, y, s, c, w):
    k = s / 24.0
    items = [
        cv.create_line(x + 4 * k, y + 7 * k, x + 20 * k, y + 7 * k,
                       fill=c, width=w, capstyle=tk.ROUND),
        cv.create_polygon(_pts([7, 7, 17, 7, 16, 20, 8, 20], x, y, s),
                          outline=c, fill="", width=w, joinstyle=tk.ROUND),
        cv.create_line(x + 10 * k, y + 4 * k, x + 14 * k, y + 4 * k,
                       fill=c, width=w, capstyle=tk.ROUND),
        cv.create_line(x + 10 * k, y + 11 * k, x + 10 * k, y + 17 * k, fill=c, width=w),
        cv.create_line(x + 14 * k, y + 11 * k, x + 14 * k, y + 17 * k, fill=c, width=w)]
    return items


def _ic_refresh(cv, x, y, s, c, w):
    k = s / 24.0
    items = [cv.create_arc(x + 4 * k, y + 4 * k, x + 20 * k, y + 20 * k,
                           start=30, extent=280, style=tk.ARC, outline=c, width=w)]
    # 箭头
    items.append(cv.create_polygon(
        _pts([19, 3, 21, 8, 16, 8], x, y, s), fill=c))
    return items


def _ic_download(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_line(x + 12 * k, y + 4 * k, x + 12 * k, y + 15 * k,
                       fill=c, width=w, capstyle=tk.ROUND),
        cv.create_line(x + 7 * k, y + 11 * k, x + 12 * k, y + 16 * k,
                       x + 17 * k, y + 11 * k, fill=c, width=w,
                       capstyle=tk.ROUND, joinstyle=tk.ROUND),
        cv.create_line(x + 5 * k, y + 20 * k, x + 19 * k, y + 20 * k,
                       fill=c, width=w, capstyle=tk.ROUND)]


def _ic_upload(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_line(x + 12 * k, y + 15 * k, x + 12 * k, y + 4 * k,
                       fill=c, width=w, capstyle=tk.ROUND),
        cv.create_line(x + 7 * k, y + 8 * k, x + 12 * k, y + 3 * k,
                       x + 17 * k, y + 8 * k, fill=c, width=w,
                       capstyle=tk.ROUND, joinstyle=tk.ROUND),
        cv.create_line(x + 5 * k, y + 20 * k, x + 19 * k, y + 20 * k,
                       fill=c, width=w, capstyle=tk.ROUND)]


def _ic_check(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_line(x + 5 * k, y + 12.5 * k, x + 10 * k, y + 18 * k,
                           x + 19 * k, y + 6 * k, fill=c, width=w,
                           capstyle=tk.ROUND, joinstyle=tk.ROUND)]


def _ic_x(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_line(x + 6 * k, y + 6 * k, x + 18 * k, y + 18 * k,
                           fill=c, width=w, capstyle=tk.ROUND),
            cv.create_line(x + 18 * k, y + 6 * k, x + 6 * k, y + 18 * k,
                           fill=c, width=w, capstyle=tk.ROUND)]


def _ic_chevron_down(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_line(x + 6 * k, y + 10 * k, x + 12 * k, y + 16 * k,
                           x + 18 * k, y + 10 * k, fill=c, width=w,
                           capstyle=tk.ROUND, joinstyle=tk.ROUND)]


def _ic_chevron_right(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_line(x + 10 * k, y + 6 * k, x + 16 * k, y + 12 * k,
                           x + 10 * k, y + 18 * k, fill=c, width=w,
                           capstyle=tk.ROUND, joinstyle=tk.ROUND)]


def _ic_music(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_line(x + 9 * k, y + 18 * k, x + 9 * k, y + 6 * k,
                       x + 18 * k, y + 4 * k, x + 18 * k, y + 15 * k,
                       fill=c, width=w, capstyle=tk.ROUND, joinstyle=tk.ROUND),
        cv.create_oval(x + 6 * k, y + 16 * k, x + 10 * k, y + 20 * k,
                       outline=c, width=w),
        cv.create_oval(x + 15 * k, y + 13 * k, x + 19 * k, y + 17 * k,
                       outline=c, width=w)]


def _ic_scissors(cv, x, y, s, c, w):
    k = s / 24.0
    items = [
        cv.create_line(x + 6 * k, y + 9 * k, x + 20 * k, y + 18 * k, fill=c, width=w),
        cv.create_line(x + 6 * k, y + 15 * k, x + 20 * k, y + 6 * k, fill=c, width=w),
        cv.create_oval(x + 4 * k, y + 7 * k, x + 8 * k, y + 11 * k, outline=c, width=w),
        cv.create_oval(x + 4 * k, y + 13 * k, x + 8 * k, y + 17 * k, outline=c, width=w)]
    return items


def _ic_database(cv, x, y, s, c, w):
    k = s / 24.0
    items = [
        cv.create_oval(x + 5 * k, y + 5 * k, x + 19 * k, y + 9 * k, outline=c, width=w),
        cv.create_line(x + 5 * k, y + 7 * k, x + 5 * k, y + 18 * k, fill=c, width=w),
        cv.create_line(x + 19 * k, y + 7 * k, x + 19 * k, y + 18 * k, fill=c, width=w),
        cv.create_oval(x + 5 * k, y + 14 * k, x + 19 * k, y + 18 * k, outline=c, width=w)]
    return items


def _ic_home(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_polygon(
        _pts([4, 11, 12, 4, 20, 11, 20, 20, 4, 20], x, y, s),
        outline=c, fill="", width=w, joinstyle=tk.ROUND)]


def _ic_file(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_polygon(
        _pts([6, 3, 14, 3, 18, 7, 18, 21, 6, 21], x, y, s),
        outline=c, fill="", width=w, joinstyle=tk.ROUND),
        cv.create_line(x + 14 * k, y + 3 * k, x + 14 * k, y + 7 * k,
                       x + 18 * k, y + 7 * k, fill=c, width=w)]


def _ic_alert(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_polygon(_pts([12, 3, 22, 20, 2, 20], x, y, s),
                          outline=c, fill="", width=w, joinstyle=tk.ROUND),
        cv.create_line(x + 12 * k, y + 10 * k, x + 12 * k, y + 14 * k,
                       fill=c, width=w, capstyle=tk.ROUND),
        cv.create_oval(x + 12 * k - 0.5, y + 17 * k - 0.5,
                       x + 12 * k + 0.5, y + 17 * k + 0.5, fill=c)]


def _ic_info(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_oval(x + 3 * k, y + 3 * k, x + 21 * k, y + 21 * k,
                       outline=c, width=w),
        cv.create_line(x + 12 * k, y + 11 * k, x + 12 * k, y + 17 * k,
                       fill=c, width=w, capstyle=tk.ROUND),
        cv.create_oval(x + 12 * k - 0.5, y + 7.5 * k - 0.5,
                       x + 12 * k + 0.5, y + 7.5 * k + 0.5, fill=c)]


def _ic_sun(cv, x, y, s, c, w):
    import math
    k = s / 24.0
    cx, cy = x + 12 * k, y + 12 * k
    items = [cv.create_oval(cx - 4 * k, cy - 4 * k, cx + 4 * k, cy + 4 * k,
                            outline=c, width=w)]
    for i in range(8):
        a = math.pi / 4 * i
        items.append(cv.create_line(
            cx + 6 * k * math.cos(a), cy + 6 * k * math.sin(a),
            cx + 9 * k * math.cos(a), cy + 9 * k * math.sin(a),
            fill=c, width=w, capstyle=tk.ROUND))
    return items


def _ic_moon(cv, x, y, s, c, w):
    k = s / 24.0
    return [cv.create_polygon(
        _pts([20, 14, 13, 20, 6, 18, 12, 12, 8, 4, 16, 6, 20, 10], x, y, s),
        outline=c, fill="", width=w, smooth=True, joinstyle=tk.ROUND)]


def _ic_eye(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_polygon(_pts([2, 12, 7, 6, 12, 5, 17, 6, 22, 12, 17, 18, 12, 19, 7, 18], x, y, s),
                          outline=c, fill="", width=w, smooth=True),
        cv.create_oval(x + 9.5 * k, y + 9.5 * k, x + 14.5 * k, y + 14.5 * k,
                       outline=c, width=w)]


def _ic_edit(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_polygon(_pts([15, 4, 20, 9, 9, 20, 4, 20, 4, 15], x, y, s),
                          outline=c, fill="", width=w, joinstyle=tk.ROUND),
        cv.create_line(x + 13 * k, y + 6 * k, x + 18 * k, y + 11 * k,
                       fill=c, width=w)]


def _ic_zap(cv, x, y, s, c, w):
    return [cv.create_polygon(_pts([13, 2, 4, 14, 11, 14, 10, 22, 20, 10, 13, 10], x, y, s),
                              fill=c, outline=c)]


def _ic_clock(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_oval(x + 4 * k, y + 4 * k, x + 20 * k, y + 20 * k,
                       outline=c, width=w),
        cv.create_line(x + 12 * k, y + 12 * k, x + 12 * k, y + 7 * k, fill=c, width=w),
        cv.create_line(x + 12 * k, y + 12 * k, x + 16 * k, y + 12 * k, fill=c, width=w)]


def _ic_layers(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_polygon(_pts([12, 3, 21, 8, 12, 13, 3, 8], x, y, s),
                          outline=c, fill="", width=w, joinstyle=tk.ROUND),
        cv.create_polygon(_pts([3, 12, 12, 17, 21, 12], x, y, s),
                          outline=c, fill="", width=w, joinstyle=tk.ROUND),
        cv.create_polygon(_pts([3, 16, 12, 21, 21, 16], x, y, s),
                          outline=c, fill="", width=w, joinstyle=tk.ROUND)]


def _ic_grid(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_rectangle(x + 4 * k, y + 4 * k, x + 10 * k, y + 10 * k, outline=c, width=w),
        cv.create_rectangle(x + 14 * k, y + 4 * k, x + 20 * k, y + 10 * k, outline=c, width=w),
        cv.create_rectangle(x + 4 * k, y + 14 * k, x + 10 * k, y + 20 * k, outline=c, width=w),
        cv.create_rectangle(x + 14 * k, y + 14 * k, x + 20 * k, y + 20 * k, outline=c, width=w)]


def _ic_list(cv, x, y, s, c, w):
    k = s / 24.0
    items = []
    for i, yy in enumerate([6, 12, 18]):
        items.append(cv.create_oval(x + 5 * k - 1, y + yy * k - 1,
                                    x + 5 * k + 1, y + yy * k + 1, fill=c))
        items.append(cv.create_line(x + 9 * k, y + yy * k, x + 19 * k, y + yy * k,
                                    fill=c, width=w, capstyle=tk.ROUND))
    return items


def _ic_filter(cv, x, y, s, c, w):
    return [cv.create_polygon(_pts([3, 5, 21, 5, 14, 13, 14, 20, 10, 18, 10, 13], x, y, s),
                              outline=c, fill="", width=w, joinstyle=tk.ROUND)]


def _ic_save(cv, x, y, s, c, w):
    k = s / 24.0
    return [
        cv.create_polygon(_pts([4, 4, 17, 4, 20, 7, 20, 20, 4, 20], x, y, s),
                          outline=c, fill="", width=w, joinstyle=tk.ROUND),
        cv.create_rectangle(x + 8 * k, y + 4 * k, x + 16 * k, y + 10 * k,
                            outline=c, width=w),
        cv.create_rectangle(x + 8 * k, y + 14 * k, x + 16 * k, y + 20 * k,
                            outline=c, width=w)]


def _ic_wand(cv, x, y, s, c, w):
    k = s / 24.0
    items = [cv.create_line(x + 5 * k, y + 19 * k, x + 15 * k, y + 9 * k,
                            fill=c, width=w, capstyle=tk.ROUND)]
    for dx, dy in [(17, 5), (19, 9), (14, 3), (9, 3)]:
        items.append(cv.create_line(x + (dx - 1.5) * k, y + dy * k,
                                    x + (dx + 1.5) * k, y + dy * k, fill=c, width=w))
        items.append(cv.create_line(x + dx * k, y + (dy - 1.5) * k,
                                    x + dx * k, y + (dy + 1.5) * k, fill=c, width=w))
    return items


# 图标名 → 绘制函数
ICONS = {
    "play": _ic_play, "square": _ic_square, "pause": _ic_pause,
    "folder": _ic_folder, "search": _ic_search, "gear": _ic_gear,
    "plus": _ic_plus, "minus": _ic_minus, "trash": _ic_trash,
    "refresh": _ic_refresh, "download": _ic_download, "upload": _ic_upload,
    "check": _ic_check, "x": _ic_x,
    "chevron-down": _ic_chevron_down, "chevron-right": _ic_chevron_right,
    "music": _ic_music, "scissors": _ic_scissors, "database": _ic_database,
    "home": _ic_home, "file": _ic_file, "alert": _ic_alert, "info": _ic_info,
    "sun": _ic_sun, "moon": _ic_moon, "eye": _ic_eye, "edit": _ic_edit,
    "zap": _ic_zap, "clock": _ic_clock, "layers": _ic_layers,
    "grid": _ic_grid, "list": _ic_list, "filter": _ic_filter,
    "save": _ic_save, "wand": _ic_wand,
}


def draw_icon(cv, name, x, y, size=18, color=None, width=2):
    """在 Canvas 上绘制矢量图标。
    cv: Canvas；name: ICONS 中的图标名；x,y: 左上角；size: 像素尺寸。
    返回 item id 列表（图标未注册返回空列表）。
    """
    fn = ICONS.get(name)
    if fn is None:
        return []
    c = color or _pal()["FG"]
    try:
        return fn(cv, x, y, size, c, width)
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════
# IconButton —— Canvas 图标按钮
# ══════════════════════════════════════════════════════════════════

class IconButton(tk.Canvas):
    """Canvas 自绘图标按钮（图标 + 可选文字），带 hover/press 视觉反馈。

    用法：
        btn = IconButton(parent, icon="play", text="开始", command=fn,
                         primary=True)
        btn.pack()
    primary=True 时用强调色填充（主按钮）；否则透明/浅底（次按钮）。
    danger=True 时红色填充。
    """

    def __init__(self, master, icon=None, text="", command=None,
                 primary=False, danger=False, icon_size=16,
                 bg=None, fg=None, font=None, padx=12, pady=7, **kw):
        pal = _pal()
        self._bg_base = bg or pal["BG"]
        self._primary = primary
        self._danger = danger
        if primary:
            self._fill = pal["ACCENT"]
            self._fill_hv = pal["ACCENT_HV"]
            self._fg = "#ffffff"
        elif danger:
            self._fill = pal["DANGER"]
            self._fill_hv = pal["DANGER_HV"]
            self._fg = "#ffffff"
        else:
            self._fill = pal["SURFACE"]
            self._fill_hv = _mix(pal["SURFACE"], pal["FG"], 0.08)
            self._fg = fg or pal["FG"]
        self._icon_name = icon
        self._icon_size = icon_size
        self._text = text
        self._command = command
        self._font = font or FONT_BOLD
        self._px, self._py = padx, pady
        self._pressed = False
        self._hover = False

        # 先测量文字宽度
        tmp = tk.Toplevel(); tmp.withdraw()
        tc = tk.Canvas(tmp)
        tw = tc.fontmeasure(self._font, text)[0] if text else 0
        tmp.destroy()

        iw = icon_size + (6 if text else 0) if icon else 0
        w = self._px * 2 + iw + tw
        h = self._py * 2 + max(icon_size, 16)
        tk.Canvas.__init__(self, master, width=w, height=h,
                          bg=self._bg_base, highlightthickness=0, bd=0, **kw)
        self._w, self._h = w, h
        self._draw()
        self.configure(cursor="hand2")
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self):
        self.delete("all")
        fill = self._fill_hv if (self._hover or self._pressed) else self._fill
        if self._pressed:
            fill = self._fill_hv
        r = 8
        # 按钮背景（圆角矩形，用多边形近似）
        if self._primary or self._danger or self._hover:
            self._round_rect(1, 1, self._w - 1, self._h - 1, r,
                             fill=fill, outline="")
        else:
            self._round_rect(1, 1, self._w - 1, self._h - 1, r,
                             fill=fill, outline=_pal()["BORDER"])
        cx = self._px
        cy = (self._h - self._icon_size) / 2
        if self._icon_name:
            draw_icon(self, self._icon_name, cx, cy,
                      size=self._icon_size, color=self._fg, width=2)
            cx += self._icon_size + 6
        if self._text:
            ty = self._h / 2
            self.create_text(cx, ty, text=self._text, fill=self._fg,
                             font=self._font, anchor="w")

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
               x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2,
               x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _on_enter(self, e):
        self._hover = True
        self._draw()

    def _on_leave(self, e):
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, e):
        self._pressed = True
        self._draw()

    def _on_release(self, e):
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and self._command:
            self._command()

    def set_command(self, fn):
        self._command = fn

    def configure_text(self, text=None, icon=None):
        if text is not None:
            self._text = text
        if icon is not None:
            self._icon_name = icon
        self._draw()


# ══════════════════════════════════════════════════════════════════
# ToggleSwitch —— iOS 风格开关（滑动动画）
# ══════════════════════════════════════════════════════════════════

class ToggleSwitch(tk.Canvas):
    """iOS 风格开关，点击平滑滑动。sw.get() / sw.set(bool)。"""

    def __init__(self, master, value=False, command=None, bg=None,
                 width=44, height=24, **kw):
        pal = _pal()
        self._bg = bg or pal["BG"]
        self._on_color = pal["SUCCESS"]
        self._off_color = _mix(pal["FG"], pal["BG"], 0.7)
        self._value = bool(value)
        self._command = command
        self._w, self._h = width, height
        tk.Canvas.__init__(self, master, width=width, height=height,
                           bg=self._bg, highlightthickness=0, bd=0, **kw)
        self.configure(cursor="hand2")
        self.bind("<ButtonRelease-1>", self._toggle)
        self._knob_x = self._knob_target()
        self._draw()

    def _knob_target(self):
        pad, d = 3, self._h - 6
        return self._w - pad - d if self._value else pad

    def _draw(self):
        self.delete("all")
        track_c = self._on_color if self._value else self._off_color
        self._round_rect(0, 0, self._w, self._h, self._h / 2,
                         fill=track_c, outline="")
        pad, d = 3, self._h - 6
        kx = self._knob_x
        self.create_oval(kx, pad, kx + d, pad + d, fill="#ffffff", outline="")

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _toggle(self, e=None):
        self._value = not self._value
        self._animate()
        if self._command:
            self._command(self._value)

    def _animate(self):
        target = self._knob_target()
        def step():
            cur = self._knob_x
            diff = target - cur
            if abs(diff) < 1:
                self._knob_x = target; self._draw(); return
            self._knob_x = cur + diff * 0.35
            self._draw(); self.after(12, step)
        step()

    def get(self):
        return self._value

    def set(self, value, fire=False):
        if self._value != bool(value):
            self._value = bool(value); self._animate()
            if fire and self._command:
                self._command(self._value)


# ══════════════════════════════════════════════════════════════════
# StatusLED —— 状态指示灯（呼吸动画）
# ══════════════════════════════════════════════════════════════════

class StatusLED(tk.Canvas):
    """圆形状态指示灯。state: ok(绿)/warn(橙)/err(红闪)/off(灰)。"""

    def __init__(self, master, state="off", size=14, bg=None, pulse=True, **kw):
        import math
        pal = _pal()
        self._bg = bg or pal["BG"]
        self._size, self._state, self._pulse_on = size, state, pulse
        self._phase = 0.0
        tk.Canvas.__init__(self, master, width=size, height=size,
                           bg=self._bg, highlightthickness=0, bd=0, **kw)
        self._colors = {
            "ok": pal["SUCCESS"], "warn": pal["WARNING"],
            "err": pal["DANGER"], "off": _mix(pal["FG"], pal["BG"], 0.65)}
        self._tick()

    def _tick(self):
        import math
        self.delete("all")
        base = self._colors.get(self._state, self._colors["off"])
        if self._state == "err":
            alpha = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(self._phase))
        elif self._state == "ok" and self._pulse_on:
            alpha = 0.8 + 0.2 * (0.5 + 0.5 * math.sin(self._phase))
        else:
            alpha = 1.0
        d = self._size
        glow = _mix(base, self._bg, 1 - alpha * 0.5)
        self.create_oval(0, 0, d, d, fill=glow, outline="")
        inset = d * 0.22
        inner = _mix(base, "#ffffff", 0.25 * alpha)
        self.create_oval(inset, inset, d - inset, d - inset, fill=inner, outline="")
        self._phase += 0.18
        self.after(60, self._tick)

    def set_state(self, state):
        self._state = state


# ══════════════════════════════════════════════════════════════════
# Badge —— 徽章标签
# ══════════════════════════════════════════════════════════════════

class Badge(tk.Canvas):
    """彩色徽章。variant: accent/success/warning/danger/neutral。"""

    def __init__(self, master, text="", variant="neutral", bg=None,
                 font=None, padx=7, pady=2, **kw):
        pal = _pal()
        self._bg = bg or pal["BG"]
        cmap = {"accent": pal["ACCENT"], "success": pal["SUCCESS"],
                "warning": pal["WARNING"], "danger": pal["DANGER"],
                "neutral": pal["FG_DIM"]}
        self._color = cmap.get(variant, pal["FG_DIM"])
        self._text = text
        self._font = font or ("Microsoft YaHei UI", 8, "bold")
        self._px, self._py = padx, pady
        tmp = tk.Toplevel(); tmp.withdraw()
        tw = tk.Canvas(tmp).fontmeasure(self._font, text)[0]
        tmp.destroy()
        self._w = padx * 2 + tw
        self._h = pady * 2 + 13
        tk.Canvas.__init__(self, master, width=self._w, height=self._h,
                           bg=self._bg, highlightthickness=0, bd=0, **kw)
        self._draw()

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        self.delete("all")
        soft = _mix(self._color, self._bg, 0.82)
        self._round_rect(0, 0, self._w, self._h, self._h / 2, fill=soft, outline="")
        self.create_text(self._w / 2, self._h / 2, text=self._text,
                         fill=self._color, font=self._font)

    def set_text(self, text):
        self._text = text; self._draw()


# ══════════════════════════════════════════════════════════════════
# ProgressRing —— 圆形进度环
# ══════════════════════════════════════════════════════════════════

class ProgressRing(tk.Canvas):
    """圆形进度环。ring.set(0.65)；ring.indeterminate(True) 旋转。"""

    def __init__(self, master, size=44, thickness=4, bg=None, **kw):
        pal = _pal()
        self._bg = bg or pal["BG"]
        self._size, self._th = size, thickness
        self._value, self._indet, self._angle = 0.0, False, 0
        tk.Canvas.__init__(self, master, width=size, height=size,
                           bg=self._bg, highlightthickness=0, bd=0, **kw)
        self._tick()

    def _tick(self):
        self.delete("all")
        pal = _pal()
        pad = self._th / 2 + 1
        x1 = y1 = pad; x2 = y2 = self._size - pad
        self.create_oval(x1, y1, x2, y2,
                         outline=_mix(pal["FG"], pal["BG"], 0.8), width=self._th)
        if self._indet:
            self.create_arc(x1, y1, x2, y2, start=self._angle, extent=90,
                            style=tk.ARC, outline=pal["ACCENT"], width=self._th)
            self._angle = (self._angle + 12) % 360
        elif self._value > 0:
            self.create_arc(x1, y1, x2, y2, start=90, extent=-360 * self._value,
                            style=tk.ARC, outline=pal["ACCENT"], width=self._th)
        self.after(40, self._tick)

    def set(self, v):
        self._value = max(0.0, min(1.0, v))

    def indeterminate(self, on):
        self._indet = on
        if on:
            self._value = 0


# ══════════════════════════════════════════════════════════════════
# Tooltip —— 工具提示气泡
# ══════════════════════════════════════════════════════════════════

class Tooltip:
    """鼠标悬停显示的小气泡提示。

    用法：Tooltip(widget, text="这是说明文字")
    也可 widget.tooltip_text = "..." 后 attach_tooltip(widget)。
    """

    def __init__(self, widget, text="", delay=450, wraplength=240):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self.tipwin = None
        self._id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, e=None):
        self._cancel()
        self._id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._id:
            try:
                self.widget.after_cancel(self._id)
            except Exception:
                pass
            self._id = None

    def _show(self):
        if self.tipwin or not self.text:
            return
        pal = _pal()
        x = self.widget.winfo_rootx() + 14
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        win = tk.Toplevel(self.widget)
        win.wm_overrideredirect(True)
        win.wm_geometry("+%d+%d" % (x, y))
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        frame = tk.Frame(win, bg=pal["FG"], bd=0, highlightthickness=0)
        frame.pack()
        lbl = tk.Label(frame, text=self.text, bg=pal["FG"], fg=pal["BG"],
                       font=FONT_SMALL, justify="left", wraplength=self.wraplength,
                       padx=9, pady=5)
        lbl.pack()
        self.tipwin = win

    def _hide(self, e=None):
        self._cancel()
        if self.tipwin:
            try:
                self.tipwin.destroy()
            except Exception:
                pass
            self.tipwin = None

    def set_text(self, text):
        self.text = text


def attach_tooltip(widget, text):
    """便捷函数：给控件挂 Tooltip。"""
    widget._tooltip = Tooltip(widget, text)
    return widget._tooltip


# ══════════════════════════════════════════════════════════════════
# CollapsibleFrame —— 可折叠面板
# ══════════════════════════════════════════════════════════════════

class CollapsibleFrame(tk.Frame):
    """点击标题栏展开/折叠的面板，chevron 图标指示方向。

    用法：
        cf = CollapsibleFrame(parent, title="高级选项", open=False)
        ttk.Checkbutton(cf.body, text="...").pack(anchor="w")
    """

    def __init__(self, master, title="", open=False, bg=None, command=None, **kw):
        pal = _pal()
        self._bg = bg or pal["BG"]
        tk.Frame.__init__(self, master, bg=self._bg, **kw)
        self._open = open
        self._command = command
        self._title = title
        # 标题栏
        self.header = tk.Canvas(self, height=30, bg=self._bg,
                                highlightthickness=0, bd=0)
        self.header.pack(fill="x")
        self.header.configure(cursor="hand2")
        self.header.bind("<Button-1>", self.toggle)
        # 内容容器
        self.body = tk.Frame(self, bg=self._bg)
        self._draw_header()
        if open:
            self.body.pack(fill="x", padx=6)

    def _draw_header(self):
        pal = _pal()
        self.header.delete("all")
        w = max(self.winfo_width(), 120)
        # 底色 hover
        self.header.create_rectangle(0, 0, w, 30, fill=pal["HEAD_BG"], outline="")
        # chevron
        icon_name = "chevron-down" if self._open else "chevron-right"
        draw_icon(self.header, icon_name, 8, 7, size=16,
                  color=pal["ACCENT"], width=2)
        self.header.create_text(32, 15, text=self._title, fill=pal["FG"],
                                font=FONT_BOLD, anchor="w")

    def toggle(self, e=None):
        self._open = not self._open
        if self._open:
            self.body.pack(fill="x", padx=6)
        else:
            self.body.pack_forget()
        self._draw_header()
        if self._command:
            self._command(self._open)

    def open(self):
        if not self._open:
            self.toggle()

    def collapse(self):
        if self._open:
            self.toggle()


# ══════════════════════════════════════════════════════════════════
# HoverCard —— 可点击卡片
# ══════════════════════════════════════════════════════════════════

class HoverCard(tk.Frame):
    """整块可点击的卡片，hover 时边框/背景高亮。

    用法：
        card = HoverCard(parent, command=on_click)
        ttk.Label(card.body, text="...").pack()
    """

    def __init__(self, master, command=None, bg=None, **kw):
        pal = _pal()
        self._bg_default = bg or pal["SURFACE"]
        self._bg_hover = _mix(pal["SURFACE"], pal["ACCENT"], 0.10)
        self._command = command
        tk.Frame.__init__(self, master, bg=self._bg_default,
                          highlightbackground=pal["BORDER"],
                          highlightthickness=1, bd=0, **kw)
        self.body = tk.Frame(self, bg=self._bg_default)
        self.body.pack(fill="both", expand=True, padx=12, pady=10)
        if command:
            self.configure(cursor="hand2")
            for w in (self, self.body):
                w.bind("<Enter>", self._enter)
                w.bind("<Leave>", self._leave)
                w.bind("<Button-1>", self._click)
            self._bind_children(self.body)

    def _bind_children(self, parent):
        for c in parent.winfo_children():
            try:
                c.bind("<Enter>", self._enter)
                c.bind("<Leave>", self._leave)
                c.bind("<Button-1>", self._click)
            except Exception:
                pass
            self._bind_children(c)

    def _enter(self, e=None):
        pal = _pal()
        self.configure(bg=self._bg_hover, highlightbackground=pal["ACCENT"])
        self.body.configure(bg=self._bg_hover)

    def _leave(self, e=None):
        pal = _pal()
        self.configure(bg=self._bg_default, highlightbackground=pal["BORDER"])
        self.body.configure(bg=self._bg_default)

    def _click(self, e=None):
        if self._command:
            self._command()


# ══════════════════════════════════════════════════════════════════
# Segmented —— 分段控制器
# ══════════════════════════════════════════════════════════════════

class Segmented(tk.Canvas):
    """iOS/Mac 风格分段选择器。

    用法：
        seg = Segmented(parent, options=[("a","选项A"),("b","选项B")],
                        value="a", command=on_change)
    """

    def __init__(self, master, options, value=None, command=None, bg=None,
                 font=None, padx=14, pady=6, **kw):
        pal = _pal()
        self._bg = bg or pal["BG"]
        self._options = options   # [(key, label), ...]
        self._value = value or (options[0][0] if options else None)
        self._command = command
        self._font = font or FONT_BOLD
        self._px, self._py = padx, pady
        tmp = tk.Toplevel(); tmp.withdraw()
        tc = tk.Canvas(tmp)
        widths = [tc.fontmeasure(self._font, lbl)[0] for _, lbl in options]
        tmp.destroy()
        self._seg_w = [w + padx * 2 for w in widths]
        total_w = sum(self._seg_w)
        self._h = pady * 2 + 16
        tk.Canvas.__init__(self, master, width=total_w, height=self._h,
                           bg=self._bg, highlightthickness=0, bd=0, **kw)
        self._total_w = total_w
        self.bind("<Button-1>", self._on_click)
        self.configure(cursor="hand2")
        self._draw()

    def _draw(self):
        pal = _pal()
        self.delete("all")
        track = _mix(pal["FG"], pal["BG"], 0.85)
        self._round_rect(0, 0, self._total_w, self._h, 7, fill=track, outline="")
        x = 0
        for i, (key, lbl) in enumerate(self._options):
            w = self._seg_w[i]
            if key == self._value:
                self._round_rect(x + 2, 2, x + w - 2, self._h - 2, 6,
                                 fill=pal["SURFACE"], outline="")
                c = pal["FG"]
            else:
                c = pal["FG_DIM"]
            self.create_text(x + w / 2, self._h / 2, text=lbl, fill=c,
                             font=self._font)
            x += w

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _on_click(self, e):
        x = e.x
        acc = 0
        for i, (key, _) in enumerate(self._options):
            acc += self._seg_w[i]
            if x < acc:
                if key != self._value:
                    self._value = key
                    self._draw()
                    if self._command:
                        self._command(key)
                return

    def get(self):
        return self._value

    def set(self, key):
        if any(k == key for k, _ in self._options):
            self._value = key; self._draw()


# ══════════════════════════════════════════════════════════════════
# SideNav —— 侧边垂直导航栏
# ══════════════════════════════════════════════════════════════════

class SideNav(tk.Canvas):
    """垂直侧边导航（图标+文字），现代 App 风格，替代水平页签。

    用法：
        nav = SideNav(parent, items=[("scan","扫描","search"),
                                      ("export","导出","download")],
                      value="scan", command=on_nav)
    items: [(key, 文字, 图标名), ...]
    """

    def __init__(self, master, items, value=None, command=None, bg=None,
                 width=168, item_h=42, **kw):
        pal = _pal()
        self._nav_bg = _mix(pal["BG"], pal["FG"], 0.03)
        self._items = items
        self._value = value or (items[0][0] if items else None)
        self._command = command
        self._w, self._ih = width, item_h
        self._h = item_h * len(items) + 24
        tk.Canvas.__init__(self, master, width=width, height=self._h,
                           bg=self._nav_bg, highlightthickness=0, bd=0, **kw)
        self._hover_key = None
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _set_hover(self, key):
        if self._hover_key != key:
            self._hover_key = key
            self._draw()

    def _on_motion(self, e):
        idx = (e.y - 12) // self._ih
        if 0 <= idx < len(self._items):
            self._set_hover(self._items[idx][0])
        else:
            self._set_hover(None)
        self.configure(cursor="hand2" if self._hover_key else "arrow")

    def _on_click(self, e):
        idx = (e.y - 12) // self._ih
        if 0 <= idx < len(self._items):
            key = self._items[idx][0]
            if key != self._value:
                self._value = key; self._draw()
                if self._command:
                    self._command(key)

    def _draw(self):
        pal = _pal()
        self.delete("all")
        for i, (key, label, icon) in enumerate(self._items):
            y = 12 + i * self._ih
            if key == self._value:
                self._round_rect(8, y, self._w - 8, y + self._ih - 4,
                                 9, fill=pal["ACCENT"], outline="")
                tc, ic = "#ffffff", "#ffffff"
            elif key == self._hover_key:
                self._round_rect(8, y, self._w - 8, y + self._ih - 4,
                                 9, fill=_mix(pal["FG"], self._nav_bg, 0.88),
                                 outline="")
                tc, ic = pal["FG"], pal["FG"]
            else:
                tc, ic = pal["FG_DIM"], pal["FG_DIM"]
            draw_icon(self, icon, 20, y + (self._ih - 4 - 18) / 2,
                      size=18, color=ic, width=2)
            self.create_text(46, y + (self._ih - 4) / 2, text=label,
                             fill=tc, font=FONT_BODY, anchor="w")

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def set_value(self, key):
        if any(k == key for k, _, _ in self._items):
            self._value = key; self._draw()


# ══════════════════════════════════════════════════════════════════
# 辅助：Treeview 行 hover 高亮 / 拖拽区域高亮
# ══════════════════════════════════════════════════════════════════

def attach_tree_hover(tree):
    """给 Treeview 加鼠标行 hover 高亮（<Motion> 跟踪行）。"""
    state = {"hover": ""}
    def on_motion(e):
        if tree.identify("region", e.x, e.y) == "cell" or \
           tree.identify("region", e.x, e.y) == "tree":
            item = tree.identify_row(e.y)
            if item and item != state["hover"]:
                if state["hover"]:
                    tree.item(state["hover"], tags=())
                pal = _pal()
                tree.item(item, tags=("hoverrow",))
                tree.tag_configure("hoverrow",
                                   background=_mix(pal["ACCENT"], pal["BG"], 0.85))
                state["hover"] = item
        else:
            if state["hover"]:
                tree.item(state["hover"], tags=())
                state["hover"] = ""
    tree.bind("<Motion>", on_motion, add="+")
    tree.bind("<Leave>", lambda e: (
        tree.item(state["hover"], tags=()) if state["hover"] else None,
        state.update(hover="")), add="+")
    return tree


def attach_drop_highlight(widget, on_drop_check=None):
    """拖拽文件进入时给 widget 加高亮边框，离开/放下后恢复。

    需 tkinterdnd2；widget 已绑定 DND_FILES 时调用。视觉层用
    highlightthickness 切换。
    """
    pal = _pal()
    old = widget.cget("highlightthickness") or 0
    old_bg = widget.cget("highlightbackground")
    def enter(e):
        try:
            widget.configure(highlightthickness=3,
                             highlightbackground=pal["ACCENT"])
        except Exception:
            pass
    def leave(e):
        try:
            widget.configure(highlightthickness=old, highlightbackground=old_bg)
        except Exception:
            pass
    widget.bind("<DragEnter>", enter, add="+")
    widget.bind("<DragLeave>", leave, add="+")
    widget.bind("<Drop>", leave, add="+")
    return widget


# ══════════════════════════════════════════════════════════════════
# auto_tooltip —— 按按钮文字智能批量挂载 Tooltip
# ══════════════════════════════════════════════════════════════════

_TOOLTIP_RULES = [
    (("扫描", "识别", "检测工程"), "扫描当前打开的 Pro Tools 工程，读取轨道、采样率等信息"),
    (("导出", "开始导出", "批量导出"), "按勾选的导出模式（整轨/分轨/总线）导出音频文件"),
    (("浏览", "选择文件", "选择目录"), "打开文件/文件夹选择对话框"),
    (("删除", "清空", "清理", "移除"), "删除选中项，操作不可恢复，请确认"),
    (("刷新", "重新识别", "重新检测"), "重新检测 Pro Tools / 剪映运行状态"),
    (("保存全部", "保存配置"), "把所有页签的配置写入配置文件"),
    (("全选",), "勾选列表中的全部轨道"),
    (("取消全选", "全不选", "清空选择"), "取消列表中所有轨道的勾选"),
    (("打开目录", "打开文件夹", "打开所在"), "在 Windows 资源管理器中打开对应目录"),
    (("导入",), "从外部文件 / 其他工程导入数据"),
    (("执行", "开始重命名", "重命名"), "按规则执行批量重命名，可在撤销页回溯"),
    (("撤销", "回溯", "还原"), "恢复到重命名操作之前的文件名"),
    (("交付", "打包交付"), "把素材整理成标准交付包结构"),
    (("停止", "中止"), "中止当前正在运行的任务"),
    (("新增", "添加", "新建"), "添加一个新条目"),
    (("生成", "创建文件夹"), "按命名规则批量生成工程文件夹结构"),
    (("解密",), "解密剪映草稿文件以便读取内容"),
    (("人声分离", "分离"), "调用 Demucs 对音频做人声 / 伴奏分离（耗时较长）"),
    (("预览",), "按当前规则预演结果，不会实际修改文件"),
    (("设置", "配置"), "调整工具参数与偏好"),
]


def auto_tooltip(root):
    """遍历所有按钮，按文字关键词自动挂载 Tooltip。

    无法匹配的按钮跳过；已挂 Tooltip 的不重复挂载。
    """
    def _tip_for(text):
        if not text:
            return None
        for keys, tip in _TOOLTIP_RULES:
            for k in keys:
                if k in text:
                    return tip
        return None

    def walk(w):
        try:
            cls = w.winfo_class()
        except Exception:
            cls = ""
        if cls in ("TButton", "Button"):
            try:
                if not getattr(w, "_tooltip", None):
                    txt = w.cget("text")
                    tip = _tip_for(txt)
                    if tip:
                        Tooltip(w, tip)
            except Exception:
                pass
        try:
            for c in w.winfo_children():
                walk(c)
        except Exception:
            pass
    walk(root)
    return root


# ══════════════════════════════════════════════════════════════════
# HeroHeader —— 顶部横幅（大图标色块 + 标题 + 状态区）
# ══════════════════════════════════════════════════════════════════

class HeroHeader(tk.Frame):
    """现代 App 顶部横幅，制造视觉焦点。

    用法：
        hdr = HeroHeader(parent, title="剪映工程工具包",
                         subtitle="v2.15.0 · 2026-09-28", icon="music")
        hdr.pack(fill="x")
        # 右侧放状态灯/设置：hdr.right 容器
        StatusLED(hdr.right, ...).pack(side="left", padx=4)
    """

    def __init__(self, master, title="", subtitle="", icon=None,
                 bg=None, accent=None, height=72, **kw):
        pal = _pal()
        self._bg = bg or pal.get("ELEVATED", pal["SURFACE"])
        self._accent = accent or pal["ACCENT"]
        self._fg = pal["FG"]
        self._dim_c = pal["FG_DIM"]
        tk.Frame.__init__(self, master, bg=self._bg, **kw)
        pad = 14
        inner = tk.Frame(self, bg=self._bg)
        inner.pack(fill="x", padx=pad, pady=10)

        # 左侧大图标色块
        if icon:
            ib = tk.Canvas(inner, width=44, height=44, bg=self._bg,
                           highlightthickness=0, bd=0)
            ib.pack(side="left", padx=(0, 12))
            # 强调色圆角方块
            self._icon_block(ib, 0, 0, 44, 12, fill=self._accent)
            draw_icon(ib, icon, 11, 11, size=22, color="#ffffff", width=2)

        # 标题 + 副标题
        txt_box = tk.Frame(inner, bg=self._bg)
        txt_box.pack(side="left", fill="y")
        tk.Label(txt_box, text=title, bg=self._bg, fg=self._fg,
                 font=FONT_TITLE, anchor="w").pack(anchor="w", pady=(2, 0))
        if subtitle:
            tk.Label(txt_box, text=subtitle, bg=self._bg, fg=self._dim_c,
                     font=FONT_SMALL, anchor="w").pack(anchor="w")

        # 右侧容器（状态灯/设置）
        self.right = tk.Frame(inner, bg=self._bg)
        self.right.pack(side="right")

        # 底部强调色细线
        line = tk.Frame(self, bg=pal["BORDER"], height=1)
        line.pack(fill="x", side="bottom")
        accent_line = tk.Frame(self, bg=self._accent, height=2)
        # 强调线只占左侧一小段，更精致
        accent_line.pack(fill="x", side="bottom")

    def _icon_block(self, cv, x1, y1, d, r, fill):
        pts = [x1+r, y1, x1+d-r, y1, x1+d, y1, x1+d, y1+r,
               x1+d, y1+d-r, x1+d, y1+d, x1+d-r, y1+d, x1+r, y1+d,
               x1, y1+d, x1, y1+d-r, x1, y1+r, x1, y1]
        return cv.create_polygon(pts, smooth=True, fill=fill)
