# -*- coding: utf-8 -*-
"""共享视觉主题（S13 / v3.10.0）—— 同源三副本之一。

副本规则（与 scrollable.py 相同）：
  ① src/pt-tools/ptools/gui/theme.py         ← 权威源
  ② src/rename-unify/code/theme.py           ← 整文件复制
  ③ src/jianying-draft-toolkit/code/theme.py  ← 整文件复制
改一必须同步二三。

设计取向（2026-09-28 裁决 D3-甲 + 本轮追加「多色彩主题」）：
  四套内置主题，运行时可切换、持久化到 cfg["theme"]：
    · warm     米白暖调（默认，Claude Desktop 风）
    · cool     冷灰专业（偏蓝灰，适合白天大屏）
    · dark     深蓝夜间（低亮度护眼）
    · contrast 墨黑高对比（视力辅助 / 投影）
  主按钮一个强调色，删除类按钮标红；不做图标。

用法：
    import theme
    theme.apply(root)                              # 入口：装配全部 ttk 样式（读 cfg 或默认 warm）
    theme.apply(root, theme_name="dark")          # 强制指定主题
    theme.set_theme(root, "cool")                 # 运行时切换（含原生控件重着色）
    for name, label in theme.list_themes(): ...   # 设置菜单枚举
    root.geometry(theme.initial_geometry(cfg.get("window"), root))   # S12
    theme.window_size(root)                        # 关闭前取 "WxH" 存回 cfg["window"]
    ttk.Button(..., style="Accent.TButton")       # 主按钮（开始/导出/执行）
    ttk.Button(..., style="Danger.TButton")       # 危险按钮（删除/清空/中止）
"""

import re
import tkinter as tk
from tkinter import ttk

# ── 主题注册表 ────────────────────────────────────────────────────
# 每套主题必须包含全部 12 个色键；切换时整组替换，不留半旧半新。
THEMES = {
    "warm": {
        "label":      "米白暖调",
        "BG":         "#f5f3ef",   # 窗口底（稍暖，不晃眼）
        "SURFACE":    "#fdfcfa",   # 卡片 / 输入框 / 表格底（极淡暖白，非纯白）
        "BORDER":     "#e2dfda",   # 细边框
        "FG":         "#2b2a28",   # 正文
        "FG_DIM":     "#8a8781",   # 次要文字
        "ACCENT":     "#c96442",   # 主按钮（陶橙）
        "ACCENT_HV":  "#b4552f",   # 主按钮悬停 / 按下
        "DANGER":     "#b3372f",   # 删除 / 清空 / 中止
        "DANGER_HV":  "#992c25",
        "SELECT_BG":  "#ece9e2",   # 选中底
        "HEAD_BG":    "#f1efeb",   # 表头底
    },
    "cool": {
        "label":      "冷灰专业",
        "BG":         "#f2f4f7",
        "SURFACE":    "#fbfcfd",
        "BORDER":     "#d8dde3",
        "FG":         "#1f2937",
        "FG_DIM":     "#6b7280",
        "ACCENT":     "#2563eb",   # 主按钮（专业蓝）
        "ACCENT_HV":  "#1d4ed8",
        "DANGER":     "#dc2626",
        "DANGER_HV":  "#b91c1c",
        "SELECT_BG":  "#dbeafe",
        "HEAD_BG":    "#eef1f5",
    },
    "dark": {
        "label":      "深蓝夜间",
        "BG":         "#1e2430",   # 深蓝灰底
        "SURFACE":    "#272e3b",   # 卡片底
        "BORDER":     "#3a4252",
        "FG":         "#e4e7ec",
        "FG_DIM":     "#8b95a5",
        "ACCENT":     "#5b9cf6",   # 主按钮（亮蓝，深色下够亮）
        "ACCENT_HV":  "#3b82f6",
        "DANGER":     "#ef4444",
        "DANGER_HV":  "#dc2626",
        "SELECT_BG":  "#2d3a4f",
        "HEAD_BG":    "#232a36",
    },
    "contrast": {
        "label":      "墨黑高对比",
        "BG":         "#0a0a0a",
        "SURFACE":    "#171717",
        "BORDER":     "#404040",
        "FG":         "#fafafa",
        "FG_DIM":     "#a3a3a3",
        "ACCENT":     "#f59e0b",   # 主按钮（琥珀，黑底下最醒目）
        "ACCENT_HV":  "#d97706",
        "DANGER":     "#ff3b30",
        "DANGER_HV":  "#e0241a",
        "SELECT_BG":  "#374151",
        "HEAD_BG":    "#1f1f1f",
    },
}

DEFAULT_THEME = "warm"
_state = {"current": None}   # 运行时当前主题名

FONT       = ("Microsoft YaHei UI", 9)
FONT_BOLD  = ("Microsoft YaHei UI", 9, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")

MIN_W, MIN_H = 900, 620   # S12：三工具统一最小尺寸


# ── 主题查询 ──────────────────────────────────────────────────────

def list_themes():
    """返回 [(key, 中文标签), ...]，供设置菜单枚举。"""
    return [(k, v["label"]) for k, v in THEMES.items()]


def current_theme_name():
    """当前已应用的主题 key；未 apply 过返回 None。"""
    return _state["current"]


def theme_label(name):
    """key → 中文标签；未知 key 返回 key 本身。"""
    return THEMES.get(name, {}).get("label", name)


def _resolve_theme(name):
    """取主题调色板；未知或 None → 默认。"""
    if name and name in THEMES:
        return name, THEMES[name]
    return DEFAULT_THEME, THEMES[DEFAULT_THEME]


# ── 主题应用 ──────────────────────────────────────────────────────

def apply(root, theme_name=None):
    """装配主题。幂等：重复调用无害。

    theme_name 为 None 时不改变当前主题（首次则用默认 warm）；
    传入具体 key 则切换到该主题。运行时切换请用 set_theme()。
    """
    name, pal = _resolve_theme(theme_name or _state["current"])
    _state["current"] = name

    st = ttk.Style(root)
    # clam：tkinter 自带主题里唯一能完整控制配色的底子
    try:
        st.theme_use("clam")
    except Exception:
        pass

    BG, SURFACE, BORDER = pal["BG"], pal["SURFACE"], pal["BORDER"]
    FG, FG_DIM = pal["FG"], pal["FG_DIM"]
    ACCENT, ACCENT_HV = pal["ACCENT"], pal["ACCENT_HV"]
    DANGER, DANGER_HV = pal["DANGER"], pal["DANGER_HV"]
    SELECT_BG, HEAD_BG = pal["SELECT_BG"], pal["HEAD_BG"]

    st.configure(".", background=BG, foreground=FG, font=FONT,
                 bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                 troughcolor=BG, selectbackground=SELECT_BG, selectforeground=FG)
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("TButton", background=SURFACE, foreground=FG, font=FONT,
                 bordercolor=BORDER, lightcolor=SURFACE, darkcolor=BORDER,
                 relief="flat", padding=(10, 4), focusthickness=1)
    # 普通按钮悬停色：浅色主题用稍深灰，深色主题用稍亮灰
    btn_hover = _lighten(BG, 8) if _is_dark(pal) else _darken(BG, 6)
    btn_press = _lighten(BG, 4) if _is_dark(pal) else _darken(BG, 10)
    st.map("TButton",
           background=[("pressed", btn_press), ("active", btn_hover),
                       ("disabled", pal["BG"])],
           foreground=[("disabled", pal["FG_DIM"])],
           lightcolor=[("pressed", btn_press), ("active", btn_hover)],
           darkcolor=[("pressed", btn_press), ("active", btn_hover)])
    # 主按钮（Accent）
    st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                 font=FONT_BOLD, bordercolor=ACCENT, lightcolor=ACCENT,
                 darkcolor=ACCENT, relief="flat", padding=(14, 4))
    st.map("Accent.TButton",
           background=[("disabled", _dim(ACCENT, BG)),
                       ("pressed", ACCENT_HV), ("active", ACCENT_HV)],
           foreground=[("disabled", _dim("#ffffff", BG))],
           lightcolor=[("pressed", ACCENT_HV), ("active", ACCENT_HV)],
           darkcolor=[("pressed", ACCENT_HV), ("active", ACCENT_HV)])
    # 危险按钮（Danger）
    st.configure("Danger.TButton", background=DANGER, foreground="#ffffff",
                 font=FONT_BOLD, bordercolor=DANGER, lightcolor=DANGER,
                 darkcolor=DANGER, relief="flat", padding=(10, 4))
    st.map("Danger.TButton",
           background=[("disabled", _dim(DANGER, BG)),
                       ("pressed", DANGER_HV), ("active", DANGER_HV)],
           foreground=[("disabled", _dim("#ffffff", BG))],
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
    # 滚动条
    st.configure("TScrollbar", background=BG, troughcolor=BG, bordercolor=BG,
                 arrowcolor=FG_DIM, relief="flat")
    st.map("TScrollbar", background=[("active", _lighten(BG, 10) if _is_dark(pal) else _darken(BG, 8))])
    # 进度条 / 分隔线 / 分组框
    st.configure("TProgressbar", background=ACCENT, troughcolor=BG, bordercolor=BG)
    st.configure("Separator", background=BORDER)
    st.configure("TLabelframe", background=BG, bordercolor=BORDER)
    st.configure("TLabelframe.Label", background=BG, foreground=FG)
    # Checkbutton / Radiobutton
    st.configure("TCheckbutton", background=BG, foreground=FG)
    st.configure("TRadiobutton", background=BG, foreground=FG)
    st.map("TCheckbutton", background=[("active", BG)])
    st.map("TRadiobutton", background=[("active", BG)])

    try:
        root.configure(background=BG)
    except Exception:
        pass

    # 运行时切换：递归重着色原生 tk 控件（Text / Listbox / Canvas / Entry 等）
    _recolor_native(root, pal)
    return st


def set_theme(root, theme_name):
    """运行时切换主题。ttk 控件自动响应；原生 tk 控件递归重着色。

    切换后建议把 theme_name 写进 cfg["theme"] 并持久化，下次启动自动恢复。
    返回实际应用的主题 key（未知 key 回落默认）。
    """
    name, _ = _resolve_theme(theme_name)
    apply(root, theme_name=name)
    return name


# ── 原生控件重着色（运行时切换的关键）────────────────────────────

_NATIVE_BG_KINDS = (tk.Text, tk.Listbox, tk.Entry, tk.Spinbox, tk.Canvas)
_NATIVE_FG_KINDS = (tk.Text, tk.Listbox, tk.Entry, tk.Spinbox)


def _recolor_native(widget, pal):
    """递归遍历 widget 树，把原生 tk 控件的背景/前景刷成当前主题色。

    ttk 控件由 Style 全局驱动，不需碰；只处理 tk.* 原生控件。
    """
    try:
        cls = widget.winfo_class()
    except Exception:
        return
    # 原生控件类名首字母大写（Text / Listbox / Entry / Canvas / Spinbox）
    if cls in ("Text", "Listbox", "Entry", "Spinbox"):
        try:
            widget.configure(background=pal["SURFACE"], foreground=pal["FG"],
                             insertbackground=pal["FG"],
                             selectbackground=pal["SELECT_BG"],
                             selectforeground=pal["FG"],
                             highlightcolor=pal["BORDER"],
                             highlightbackground=pal["BORDER"])
        except Exception:
            pass
    elif cls == "Canvas":
        try:
            widget.configure(background=pal["BG"])
        except Exception:
            pass
    elif cls in ("Frame", "Labelframe", "Toplevel"):
        # 原生 Frame（非 ttk）也刷底色
        try:
            widget.configure(background=pal["BG"])
        except Exception:
            pass
    # 递归子控件
    try:
        for child in widget.winfo_children():
            _recolor_native(child, pal)
    except Exception:
        pass


# ── 颜色工具（内部）───────────────────────────────────────────────

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def _lighten(hex_color, amount):
    """向白色靠拢 amount（0-255）。"""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((r + amount, g + amount, b + amount))


def _darken(hex_color, amount):
    """向黑色靠拢 amount（0-255）。"""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((r - amount, g - amount, b - amount))


def _is_dark(pal):
    """用 FG 亮度判断主题深浅（FG 亮 = 深色主题）。"""
    r, g, b = _hex_to_rgb(pal["FG"])
    return (0.299 * r + 0.587 * g + 0.114 * b) > 128


def _dim(color, bg):
    """禁用态：把 color 向 bg 混合 55%。"""
    cr, cg, cb = _hex_to_rgb(color)
    br, bg_, bb = _hex_to_rgb(bg)
    return _rgb_to_hex((cr * 0.45 + br * 0.55,
                         cg * 0.45 + bg_ * 0.55,
                         cb * 0.45 + bb * 0.55))


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


# ── 按钮交互增强（S13-v2：图形按钮 + 鼠标交互）──────────────────

def buttonize(root):
    """递归给所有 ttk.Button 加 hand2 光标（悬停变手型）。

    ttk.Button 默认是箭头光标，悬停没有反馈。调用一次后所有按钮
    （含动态创建的子窗口按钮）悬停时变手型，提升可点击感。
    幂等：重复调用无害（已绑定的按钮跳过）。
    """
    def _walk(w):
        try:
            cls = w.winfo_class()
        except Exception:
            return
        if cls in ("TButton", "TCheckbutton", "TRadiobutton", "TMenubutton"):
            try:
                if not getattr(w, "_btn_hand_cursor", False):
                    w.configure(cursor="hand2")
                    w._btn_hand_cursor = True
            except Exception:
                pass
        try:
            for c in w.winfo_children():
                _walk(c)
        except Exception:
            pass
    try:
        root.after(100, lambda: _walk(root))
    except Exception:
        pass


# 常用图标（Unicode 符号，微软雅黑下单色渲染，不引第三方库）
ICON_PLAY = "\u25b6"   # ▶ 播放/导出/执行
ICON_STOP = "\u25a0"   # ■ 停止/中止
ICON_DOWN = "\u2193"   # ↓ 导入/下载
ICON_GEAR = "\u2699"   # ⚙ 设置
ICON_CHECK = "\u2713"  # ✓ 确认/完成
ICON_CROSS = "\u2717"  # ✗ 删除/清空/取消
ICON_PLUS = "\uff0b"   # ＋ 新增/添加
ICON_REFRESH = "\u21bb"  # ↻ 刷新/重新识别
ICON_FOLDER = "\U0001f4c2"  # 📂 打开目录（emoji，Windows 下单色）
ICON_SCAN = "\U0001f50d"    # 🔍 扫描（emoji）
ICON_SAVE = "\U0001f4be"    # 💾 保存（emoji）


def icon(label):
    """给按钮文字加图标前缀。用法：text=theme.icon(theme.ICON_PLAY)+"开始导出" """
    return label + " "



# ── 动态像素粒子背景（S13-v3：视觉增强）──────────────────────────

class ParticleCanvas(tk.Canvas):
    """窗口底层动态像素粒子背景。

    设计取向：
      · 像素风——粒子是 2~4px 的小方块（不是圆点），契合"像素粒子"需求
      · 低干扰——粒子用主题色的低饱和变体，慢速漂浮 + 渐入渐出，不抢内容视线
      · 性能友好——默认 30 粒子 / 25fps，窗口最小化时自动暂停
      · 主题感知——深浅主题自动切换粒子颜色（亮色主题用暗粒子，深色主题用亮粒子）
      · 可关闭——cfg["particle_bg"]=False 时不创建

    用法（在 _build_ui 最开始、所有控件之前）：
        self.particle = ParticleCanvas(self, enabled=cfg.get("particle_bg", True))
        self.particle.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.particle.lower()
    """

    PARTICLE_COUNT = 30      # 粒子数量
    TICK_MS = 40             # 25fps
    SIZE_MIN, SIZE_MAX = 2, 4  # 粒子尺寸（px，像素方块）
    SPEED_MAX = 0.6          # 最大漂移速度（px/tick）
    LIFE_MIN, LIFE_MAX = 120, 300  # 生命周期（tick 数）

    def __init__(self, master, enabled=True, theme_name=None):
        super().__init__(master, highlightthickness=0, bd=0)
        self._enabled = enabled
        self._theme_name = theme_name or "warm"
        self._particles = []
        self._job = None
        self._paused = False
        if enabled:
            self._configure_bg()
            self._spawn_initial()
            self._start()
            # 窗口最小化/恢复时暂停/继续
            try:
                self.bind("<Unmap>", lambda _e: self._pause())
                self.bind("<Map>", lambda _e: self._resume())
            except Exception:
                pass

    def _configure_bg(self):
        """根据主题设置画布背景色和粒子调色板。"""
        pal = THEMES.get(self._theme_name, THEMES[DEFAULT_THEME])
        try:
            self.configure(background=pal["BG"])
        except Exception:
            pass
        # 粒子颜色：亮色主题用 ACCENT 的暗色变体 + FG_DIM；深色主题用亮色变体
        if _is_dark(pal):
            self._colors = [
                _lighten(pal["ACCENT"], 30),
                _lighten(pal["FG_DIM"], 20),
                _lighten(pal["SELECT_BG"], 10),
            ]
        else:
            self._colors = [
                _darken(pal["ACCENT"], 10),
                pal["FG_DIM"],
                _darken(pal["SELECT_BG"], 5),
            ]

    def set_theme(self, theme_name):
        """切换主题时更新背景色和粒子颜色。"""
        self._theme_name = theme_name
        self._configure_bg()
        # 更新已有粒子颜色
        for p in self._particles:
            try:
                self.itemconfig(p["id"], fill=p["color"])
            except Exception:
                pass

    def _spawn_initial(self):
        """初始生成粒子（随机位置和生命周期）。"""
        try:
            w = max(self.winfo_width(), 800)
            h = max(self.winfo_height(), 600)
        except Exception:
            w, h = 800, 600
        import random
        for _ in range(self.PARTICLE_COUNT):
            self._spawn_one(x=random.uniform(0, w), y=random.uniform(0, h),
                            initial_life=True)

    def _spawn_one(self, x=None, y=None, initial_life=False):
        """生成一个新粒子。"""
        import random
        try:
            w = max(self.winfo_width(), 800)
            h = max(self.winfo_height(), 600)
        except Exception:
            w, h = 800, 600
        if x is None:
            x = random.uniform(0, w)
        if y is None:
            y = random.uniform(0, h)
        size = random.randint(self.SIZE_MIN, self.SIZE_MAX)
        color = random.choice(self._colors)
        max_life = random.randint(self.LIFE_MIN, self.LIFE_MAX)
        life = random.randint(0, max_life) if initial_life else 0
        # 速度：慢速漂浮，带轻微向上倾向
        angle = random.uniform(0, 6.283)
        speed = random.uniform(0.1, self.SPEED_MAX)
        vx = speed * 0.4  # 水平漂移慢
        vy = -speed * 0.6  # 轻微向上飘
        item = self.create_rectangle(x, y, x + size, y + size,
                                      fill=color, outline="", width=0)
        self._particles.append({
            "id": item, "x": x, "y": y, "vx": vx, "vy": vy,
            "size": size, "color": color, "life": life, "max_life": max_life,
        })

    def _tick(self):
        """动画帧：更新所有粒子位置和生命周期。"""
        if not self._enabled or self._paused:
            return
        try:
            w = max(self.winfo_width(), 100)
            h = max(self.winfo_height(), 100)
        except Exception:
            w, h = 800, 600

        alive = []
        for p in self._particles:
            p["life"] += 1
            if p["life"] >= p["max_life"]:
                # 粒子死亡：删除并在底部生成新的
                try:
                    self.delete(p["id"])
                except Exception:
                    pass
                continue
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            # 边界环绕
            if p["x"] < -10:
                p["x"] = w + 5
            elif p["x"] > w + 10:
                p["x"] = -5
            if p["y"] < -10:
                p["y"] = h + 5
            elif p["y"] > h + 10:
                p["y"] = -5
            # 渐入渐出：生命前 15% 和后 15% 改变透明度（用颜色深浅模拟）
            fade_ratio = 1.0
            fade_in = int(p["max_life"] * 0.15)
            fade_out = int(p["max_life"] * 0.85)
            if p["life"] < fade_in:
                fade_ratio = p["life"] / max(fade_in, 1)
            elif p["life"] > fade_out:
                fade_ratio = (p["max_life"] - p["life"]) / max(p["max_life"] - fade_out, 1)
            # 用 move 移动（比 coords 快）
            try:
                self.move(p["id"], p["vx"], p["vy"])
            except Exception:
                pass
            alive.append(p)

        self._particles = alive
        # 补充死亡的粒子
        while len(self._particles) < self.PARTICLE_COUNT:
            self._spawn_one(y=max(self.winfo_height() - 10, 100))

        self._job = self.after(self.TICK_MS, self._tick)

    def _start(self):
        if self._job is None and self._enabled:
            self._job = self.after(self.TICK_MS, self._tick)

    def _pause(self):
        self._paused = True
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _resume(self):
        if self._paused and self._enabled:
            self._paused = False
            self._start()

    def destroy(self):
        self._pause()
        self._particles = []
        try:
            super().destroy()
        except Exception:
            pass
