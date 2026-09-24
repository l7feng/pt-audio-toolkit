#!/usr/bin/env python3
"""
剪映工程工具包 — 图形界面（三标签页）
=====================================

一个 exe，两件事，页配置彼此完全独立：

  ① 导出音频     剪映草稿 → 切片导出（不需要 Pro Tools）
  ② 导入多轨     .ptx（需 PT 在线）/ 交付包 json（离线）→ 写剪映草稿

  v2.7.0（J8）：③「生成交付包」页退役 —— 交付包改由 pt-tools 扫描建档页
  一步直出（扫描 + 打包一气呵成）；本工具保留**离线导入**消费能力。

用法：
  python gui.py          # 源码模式
  或打包为 exe 后双击运行（导出到同一入口）

与 CLI 共存：GUI 的配置写在 exe 旁（源码模式为包根）的 config.json，
CLI 参数行为不变。
"""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import main as core
from tabs.export_tab import ExportTab
from tabs.import_tab import ImportTab
from tabs.paths_dialog import PathsDialog
from core.host import StatusProbe
from core import menus as menu_actions

# 拖拽支持（tkinterdnd2）。未安装时优雅降级为普通选择。
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:                                    # pragma: no cover
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

APP_TITLE = f"剪映工程工具包 v{core.APP_VERSION} ({core.app_build_date()})"


def make_root() -> tk.Tk:
    """优先用支持拖拽的根窗口；tkinterdnd2 缺失时降级为普通 Tk。"""
    if DND_AVAILABLE:
        try:
            return TkinterDnD.Tk()  # type: ignore[union-attr]
        except Exception:
            pass
    return tk.Tk()


# ───────────── Toast 通知（W7 · ctypes 直调 Shell_NotifyIcon，零第三方依赖）────────────

def toast(root, title, message, timeout_ms=6000):
    """任务完成弹 Windows 通知（托盘气泡）。失败静默吞掉，不影响主流程。"""
    if os.name != "nt" or root is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        NIM_ADD = 0x00000000
        NIM_DELETE = 0x00000002
        NIF_ICON = 0x00000002
        NIF_INFO = 0x00000010
        NIIF_INFO = 0x00000001
        IDI_INFORMATION = 32516

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]

        user32 = ctypes.windll.user32
        user32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        user32.Shell_NotifyIconW.restype = wintypes.BOOL
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadIconW.restype = wintypes.HICON

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = int(root.winfo_id())
        nid.uID = 1
        nid.uFlags = NIF_INFO | NIF_ICON
        nid.hIcon = user32.LoadIconW(None, IDI_INFORMATION)
        nid.dwInfoFlags = NIIF_INFO
        nid.szInfoTitle = (title or "")[:63]
        nid.szInfo = (message or "")[:255]
        user32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        try:
            root.after(timeout_ms + 1000,
                       lambda: user32.Shell_NotifyIconW(NIM_DELETE,
                                                        ctypes.byref(nid)))
        except Exception:
            pass
    except Exception:
        pass


def parse_drop_paths(data: str) -> list:
    """把 tkinter 拖拽事件里的路径串解析为 Path 列表。

    Windows 下含空格的路径会被 {} 包裹，如：
      {C:/a b/c.mp4} D:/d.mp4
    """
    paths, buf, in_brace = [], "", False
    for ch in data:
        if ch == "{":
            in_brace, buf = True, ""
        elif ch == "}":
            in_brace = False
            if buf:
                paths.append(buf)
            buf = ""
        elif ch == " " and not in_brace:
            if buf:
                paths.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        paths.append(buf)
    return [Path(p) for p in paths if p]


class JianYingToolkitApp:
    """主窗口：三个标签页 + 共享消息队列 + 拖放转发。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x780")
        self.root.minsize(820, 680)

        self.msg_queue = queue.Queue()
        self._tabs = []
        self.logger = core.setup_logging()
        if self.logger is not None:
            self.logger.info("GUI 启动 v%s (%s)", core.APP_VERSION,
                             core.app_build_date())

        # ⚠️ 顺序有讲究：_probe 必须在 _build_ui 之前建好 ——
        # 各标签页构造时会调 refresh_states()，而它读的是 self.app._probe 的缓存。
        self._probe = StatusProbe()

        self._load_cfg()
        self._build_menu()          # 必须在 _build_ui 之前：菜单挂在 root 上
        self._build_ui()
        self._setup_dnd()
        # v2.6.4（W3）：注册关闭协议 —— 点窗口 X 与菜单「退出」走同一道关卡，
        # 有任务在跑时先确认再退出，避免 ffmpeg / jy-draftc 子进程残留。
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_queue)
        self._refresh_status()
        # J1（v2.7.0）：启动时扫描草稿 schema 版本 —— 发现"没见过的版本"就挂黄条
        # 告警（不硬崩、不打断启动），提醒先备份再动导入。
        self._draft_versions = {}
        self._version_bar = None
        self.root.after(400, self._startup_version_check)

    # ───────────── 配置 ─────────────

    def _load_cfg(self):
        """载入配置：导出页字段走 DEFAULT_CONFIG，导入页字段并入同一份文件。"""
        path = core.config_path()
        disk = {}
        if path.is_file():
            try:
                disk = json.loads(path.read_text(encoding="utf-8")) or {}
            except Exception as e:
                print(f"[cfg] 读取失败，用默认值: {e}")
        self.cfg = {**core.DEFAULT_CONFIG,
                    **core.DEFAULT_IMPORT_CONFIG,
                    **disk}

    # ───────────── 菜单栏 ─────────────

    def _build_menu(self):
        """构建菜单栏：文件 / 设置 / 工具 / 帮助。

        动作实现在 ``core/menus.py``（不放 UI 层，便于复用与单测）；
        本方法只负责「画菜单 + 绑回调」。

        「设置 → 默认路径设置…」是本菜单的核心项 —— 三页路径集中一处设置，
        省得每次换工作目录都要切页逐个改。
        """
        bar = tk.Menu(self.root)

        # ── 文件 ──
        m_file = tk.Menu(bar, tearoff=0)
        m_file.add_command(label="保存全部配置", accelerator="Ctrl+S",
                           command=self.save_all)
        m_file.add_command(label="重新载入配置（丢弃未保存改动）",
                           command=self._menu_reload)
        m_file.add_separator()
        m_file.add_command(label="打开配置文件所在文件夹",
                           command=self._menu_open_cfg_dir)
        m_file.add_command(label="打开配置文件（记事本）",
                           command=self._menu_open_cfg_file)
        m_file.add_separator()
        m_file.add_command(label="退出", accelerator="Alt+F4",
                           command=self._menu_quit)
        bar.add_cascade(label="文件", menu=m_file)

        # ── 设置 ──
        m_set = tk.Menu(bar, tearoff=0)
        m_set.add_command(label="默认路径设置…",
                          command=self._menu_paths)
        m_set.add_separator()
        m_set.add_command(label="恢复出厂默认（仅路径）",
                          command=self._menu_restore_paths)
        bar.add_cascade(label="设置", menu=m_set)

        # ── 工具 ──
        m_tool = tk.Menu(bar, tearoff=0)
        m_tool.add_command(label="刷新状态（PT / 剪映）",
                           command=self._refresh_status)
        m_tool.add_command(label="环境自检（Python / ffmpeg / 剪映 / jy-draftc）",
                           command=self._menu_env_check)
        m_tool.add_separator()
        # J1（v2.7.0）：草稿库一键备份 —— 剪映无草稿格式承诺，升级有风险，先备份再说
        m_tool.add_command(label="一键备份草稿库…",
                           command=self._menu_backup_drafts)
        m_tool.add_command(label="清理立体声合成缓存",
                           command=self._menu_clear_cache)
        m_tool.add_command(label="打开临时目录",
                           command=self._menu_open_temp)
        bar.add_cascade(label="工具", menu=m_tool)

        # ── 帮助 ──
        m_help = tk.Menu(bar, tearoff=0)
        m_help.add_command(label="使用说明（01-使用说明.txt）",
                           command=self._menu_manual)
        m_help.add_command(label="打开程序目录",
                           command=lambda: self._menu_open_dir(menu_actions.app_dir()))
        m_help.add_separator()
        m_help.add_command(label="关于", command=self._menu_about)
        bar.add_cascade(label="帮助", menu=m_help)

        self.root.configure(menu=bar)
        self.menubar = bar

        # 快捷键：保存
        try:
            self.root.bind_all("<Control-s>", lambda _e: self.save_all())
        except Exception:
            pass

    # ───────────── 菜单动作 ─────────────

    def _menu_reload(self):
        """从磁盘重读配置并刷回三页控件。

        用途：用户按了「打开配置文件」手改 JSON 之后，不必重启程序。
        """
        if self._any_running():
            messagebox.showwarning("有任务在跑", "请等当前任务结束后再重新载入配置。")
            return
        if not messagebox.askyesno(
                "重新载入配置",
                "将丢弃三页未保存的界面改动，从配置文件重读。继续？"):
            return
        try:
            self.cfg = menu_actions.reload_config()
            self._apply_cfg_to_tabs()
            self.log_to_current("\n· 配置已重新载入。\n")
        except Exception as e:
            messagebox.showerror("载入失败", f"读取配置失败：{e}")

    def _apply_cfg_to_tabs(self):
        """把 self.cfg 的值刷回各页控件（各页自己实现 apply_config）。"""
        for t in self._tabs:
            fn = getattr(t, "apply_config", None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

    def _menu_paths(self):
        """设置 → 默认路径设置…（核心项）"""
        if self._any_running():
            messagebox.showwarning("有任务在跑", "请等当前任务结束后再改路径。")
            return
        dlg = PathsDialog(self.root)
        self.root.wait_window(dlg)
        if getattr(dlg, "saved", False):
            # 路径写盘了，同步刷新内存与各页显示
            try:
                self.cfg = menu_actions.reload_config()
                self._apply_cfg_to_tabs()
            except Exception:
                pass
            self.log_to_current("\n· 默认路径已更新并写入配置。\n")

    def _menu_restore_paths(self):
        if self._any_running():
            messagebox.showwarning("有任务在跑", "请等当前任务结束后再操作。")
            return
        if not messagebox.askyesno(
                "恢复出厂默认",
                f"把 5 个**路径**字段重置为出厂默认（输出目录 → {core.DEFAULT_CONFIG['output_dir']}，其余留空）。\n\n"
                "命名模板 / 规格 / 开关等参数不受影响。继续？"):
            return
        try:
            changed = menu_actions.restore_default_paths()
            self.cfg = menu_actions.reload_config()
            self._apply_cfg_to_tabs()
            if changed:
                self.log_to_current("\n· 路径已恢复出厂默认：" +
                                    "、".join(changed.keys()) + "\n")
            else:
                self.log_to_current("\n· 路径本来就是出厂默认，无需改动。\n")
        except Exception as e:
            messagebox.showerror("恢复失败", f"操作失败：{e}")

    def _menu_env_check(self):
        """工具 → 环境自检：切到导出页并触发那边的自检（复用同一实现）。"""
        try:
            self.notebook.select(0)
        except Exception:
            pass
        for t in self._tabs:
            fn = getattr(t, "run_check", None)
            if callable(fn):
                fn()
                return

    def _menu_clear_cache(self):
        n, size = menu_actions.stereo_cache_info()
        if n == 0:
            messagebox.showinfo(
                "缓存已是空的",
                f"没有找到立体声合成缓存。\n\n目录：\n{menu_actions.stereo_cache_dir()}")
            return
        if not messagebox.askyesno(
                "清理立体声合成缓存",
                f"将删除 {n} 个文件（{menu_actions.human_size(size)}）。\n\n"
                f"位置：{menu_actions.stereo_cache_dir()}\n\n"
                "说明：这是导入时把 PT 的 L/R 两个单声道合成成对立体声的中间产物，\n"
                "删掉不影响任何草稿与交付包 —— 下次导入会按需重新生成。\n\n继续？"):
            return
        try:
            dn, dsize = menu_actions.clear_stereo_cache()
        except Exception as e:
            messagebox.showerror("清理失败", f"删除失败：{e}")
            return
        self.log_to_current(
            f"\n· 已清理立体声合成缓存：{dn} 个文件，释放 {menu_actions.human_size(dsize)}。\n")

    def _menu_open_temp(self):
        import tempfile
        self._menu_open_dir(Path(tempfile.gettempdir()))

    # ───────────── J1：草稿库备份 + 版本防线 ─────────────

    def _draft_root(self) -> Path:
        """当前草稿库根：优先配置 input_dir，回落出厂默认草稿根。"""
        raw = str(self.cfg.get("input_dir") or "").strip()
        if raw and Path(raw).is_dir():
            return Path(raw)
        if core.DEFAULT_JIANYING_DRAFT_ROOT.is_dir():
            return core.DEFAULT_JIANYING_DRAFT_ROOT
        return Path(raw) if raw else core.DEFAULT_JIANYING_DRAFT_ROOT

    def _menu_backup_drafts(self):
        """工具 → 一键备份草稿库：先估体积并确认，后台 robocopy 整库复制。"""
        root = self._draft_root()
        if not root.is_dir():
            messagebox.showerror(
                "备份草稿库",
                f"草稿库目录不存在：\n{root}\n\n"
                "请先在「设置 → 默认路径设置…」里确认草稿目录。")
            return
        n, size = menu_actions.draft_library_size(root)
        target = root.parent / ("草稿库备份-" +
                                __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S"))
        if not messagebox.askyesno(
                "一键备份草稿库",
                f"源：{root}\n目标：{target}\n\n"
                f"约 {n} 个文件（{menu_actions.human_size(size)}）。\n"
                "备份期间请勿在剪映里保存草稿（剪映没开最稳）。\n\n继续？"):
            return
        self.log_to_current(f"\n· 开始备份草稿库：{root} → {target}\n")

        def job():
            def prog(text):
                self.msg_queue.put(text)
            try:
                dst = menu_actions.backup_draft_library(root, log=prog)
                self.msg_queue.put(
                    f"\n✓ 备份完成：{dst}\n")
                try:
                    self.root.after(0, lambda d=str(dst): toast(
                        self.root, "剪映工程工具包", f"草稿库备份完成：{d}"))
                except Exception:
                    pass
            except Exception as e:
                self.msg_queue.put(f"\n✗ 备份失败：{e}\n")

        threading.Thread(target=job, daemon=True).start()

    def _startup_version_check(self):
        """J1 ②：后台扫描草稿版本，出现「已知列表之外」的版本就挂黄条。"""
        root = self._draft_root()

        def job():
            try:
                result = menu_actions.scan_draft_versions(root)
            except Exception:
                result = {"versions": {}, "unknown": [], "total": 0}
            self.root.after(0, lambda: self._apply_version_scan(result))

        threading.Thread(target=job, daemon=True).start()

    def _apply_version_scan(self, result: dict):
        self._draft_versions = result
        versions = result.get("versions") or {}
        known = set(self.cfg.get("known_draft_versions") or [])
        fresh = sorted(v for v in versions if v and v not in known)
        if fresh:
            self._show_version_bar(fresh)

    def _show_version_bar(self, fresh_versions):
        """顶部黄色告警条：点了弹出明细对话框（记录已知 / 查看分布）。"""
        if self._version_bar is not None:
            try:
                self._version_bar.destroy()
            except Exception:
                pass
        total = sum((self._draft_versions or {}).get("versions", {}).values())
        bar = tk.Label(
            self.root,
            text=("⚠ 检测到没见过的剪映草稿版本：%s（草稿库共 %d 个，点此查看）"
                  "—— 新版本草稿结构可能不兼容，建议先「工具 → 一键备份草稿库」"
                  % (", ".join(fresh_versions), total)),
            bg="#ffe066", fg="#5a4a00", anchor="w", padx=10, pady=4,
            cursor="hand2", wraplength=860, justify="left")
        bar.bind("<Button-1>", lambda _e: self._version_dialog(fresh_versions))
        try:
            bar.pack(fill="x", before=self.notebook)
        except Exception:
            bar.pack(fill="x")
        self._version_bar = bar

    def _version_dialog(self, fresh_versions):
        result = self._draft_versions or {}
        versions = result.get("versions") or {}
        unknown = result.get("unknown") or []
        lines = ["草稿库各版本分布："]
        for v, n in sorted(versions.items()):
            mark = "（新）" if v in fresh_versions else ""
            lines.append(f"  版本 {v}: {n} 个草稿 {mark}")
        if unknown:
            lines.append(f"  读不出的草稿（加密/损坏）: {len(unknown)} 个")
        lines += ["", "说明：本工具按草稿 JSON 结构解析，剪映升级后结构可能变化。",
                  "「记为已知」只关闭提醒；真的升级剪映前请先备份草稿库。"]
        dlg = tk.Toplevel(self.root)
        dlg.title("草稿版本检查")
        dlg.transient(self.root)
        dlg.geometry("560x360")
        t = tk.Text(dlg, wrap="word", padx=12, pady=12,
                    font=("Microsoft YaHei UI", 10))
        t.insert("1.0", "\n".join(lines))
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)

        def mark_known():
            merged = sorted(set(self.cfg.get("known_draft_versions") or [])
                            | set(versions))
            self.cfg["known_draft_versions"] = merged
            try:
                path = core.config_path()
                disk = {k: self.cfg.get(k) for k in self.cfg}
                path.write_text(json.dumps(disk, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            except Exception as e:
                messagebox.showerror("写入失败", f"配置写入失败：{e}", parent=dlg)
            if self._version_bar is not None:
                try:
                    self._version_bar.destroy()
                except Exception:
                    pass
                self._version_bar = None
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(bf, text="记为已知（不再提醒）",
                   command=mark_known).pack(side="right")
        ttk.Button(bf, text="关闭", command=dlg.destroy).pack(side="right", padx=6)

    def _menu_open_cfg_dir(self):
        self._menu_open_dir(menu_actions.config_file().parent)

    def _menu_open_cfg_file(self):
        import os
        p = menu_actions.config_file()
        try:
            if not p.exists():
                menu_actions.apply_paths({})       # 没有就先生成一份
            os.startfile(str(p))                   # type: ignore[attr-defined]
        except Exception as e:
            messagebox.showerror("打开失败", f"无法打开配置文件：{e}\n{p}")

    def _menu_manual(self):
        """帮助 → 使用说明：找 exe 旁 / 程序目录里的说明书。"""
        cands = [
            menu_actions.app_dir() / "01-使用说明.txt",
            menu_actions.app_dir() / "README.md",
            menu_actions.app_dir().parent / "01-使用说明.txt",
        ]
        for p in cands:
            if p.exists():
                try:
                    import os
                    os.startfile(str(p))           # type: ignore[attr-defined]
                    return
                except Exception:
                    break
        messagebox.showinfo(
            "使用说明",
            "没找到说明书文件（01-使用说明.txt）。\n\n"
            "说明：说明书与导入 exe 是「一次性固定资产」，通常与 exe 同目录；\n"
            f"若确实缺失，位置应为：\n{menu_actions.app_dir()}\\01-使用说明.txt")

    def _menu_open_dir(self, path):
        try:
            menu_actions.reveal(Path(path))
        except Exception as e:
            messagebox.showerror("无法打开", f"打开失败：{e}\n{path}")

    def _menu_about(self):
        messagebox.showinfo(
            "关于",
            "\n".join(menu_actions.about_lines(core.APP_VERSION,
                                              core.app_build_date())))

    def _menu_quit(self):
        self._on_close()

    def _on_close(self):
        """关闭主窗（点 X / 菜单退出）——有活任务先确认再退出。
        对齐 pt-tools v1.3.0 的关闭协议；随后 destroy 并强制退出，
        跳过 atexit 的 subprocess 等待，保证进程一定退出。
        """
        if self._any_running():
            if not messagebox.askyesno(
                    "有任务在跑",
                    "还有任务正在执行，现在退出会中断它（已写入的文件不会回滚）。\n\n"
                    "确定退出？"):
                return
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    # ───────────── 菜单辅助 ─────────────

    def _any_running(self) -> bool:
        return any(getattr(t, "running", False) for t in self._tabs)

    def log_to_current(self, text: str):
        tab = self._current_tab()
        if tab is not None:
            try:
                tab.log(text)
            except Exception:
                pass

    # ───────────── UI ─────────────

    def _setup_styles(self):
        """定义自定义 ttk 样式。

        ``Accent.TButton`` 此前被三处 tab 引用但**从未定义** → ttk 静默回落到
        默认样式（不报错，只是「主按钮」和普通按钮长得一样）。这里补上，
        让「开始导出 / 导入到剪映草稿 / 保存」这几个主按钮真正突出。
        """
        try:
            st = ttk.Style(self.root)
            # 优先用 vista 主题（Windows 原生），拿不到就用默认
            if "vista" in st.theme_names():
                st.theme_use("vista")
            st.configure("Accent.TButton", font=("Microsoft YaHei UI", 9, "bold"))
            # 悬停/按下时也加粗，避免交互时字重跳变
            st.map("Accent.TButton", foreground=[("disabled", "#8a8a8a")])
        except Exception:
            pass

    def _build_ui(self):
        self._setup_styles()

        # 顶部标题条
        head = ttk.Frame(self.root, padding=(12, 8, 12, 0))
        head.pack(fill="x")
        ttk.Label(head, text=APP_TITLE,
                  font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        self.var_status = tk.StringVar(value="检测中…")
        self.lbl_status = ttk.Label(head, textvariable=self.var_status,
                                    foreground="#666", cursor="hand2")
        self.lbl_status.pack(side="right")
        self.lbl_status.bind("<Button-1>", lambda _e: self._refresh_status())

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=(6, 8))
        self.notebook = nb

        for cls in (ExportTab, ImportTab):   # v2.7.0（J8）：③交付包页退役
            tab = cls(nb, self)
            nb.add(tab, text=tab.title)
            self._tabs.append(tab)

        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # 底部状态条
        foot = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        foot.pack(fill="x")
        ttk.Label(foot, text=f"配置文件：{core.CONFIG_PATH}",
                  foreground="#999").pack(side="left")
        self.btn_refresh = ttk.Button(foot, text="刷新状态",
                                       command=self._refresh_status)
        self.btn_refresh.pack(side="right", padx=(0, 8))
        self.btn_save_all = ttk.Button(foot, text="保存全部配置",
                                       command=self.save_all)
        self.btn_save_all.pack(side="right")

    def _on_tab_changed(self, _evt=None):
        tab = self._current_tab()
        if tab is not None:
            try:
                tab.on_show()
            except Exception:
                pass
        self._refresh_status()

    def _current_tab(self):
        try:
            idx = self.notebook.index(self.notebook.select())
            return self._tabs[idx]
        except Exception:
            return None

    def save_all(self):
        for t in self._tabs:
            t.save_config(quiet=True)
        try:
            path = core.config_path()
            disk = {k: self.cfg.get(k) for k in self.cfg}
            path.write_text(json.dumps(disk, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            messagebox.showinfo("已保存", f"三页配置已写入：\n{path}")
        except Exception as e:
            messagebox.showerror("保存失败", f"配置写入失败：{e}")

    def _refresh_status(self):
        """触发后台探测 PT / 剪映状态（不再阻塞主线程，不再 6 秒轮询）。

        探测放进 worker 线程跑，结果经 ``_on_probe_done`` 回调回到 UI 线程渲染。
        轮询策略改为：启动一次 + 切页时（_on_tab_changed）+ 手动刷新（点状态条 / 底部按钮）。
        """
        draft_dir = (core.DEFAULT_JIANYING_DRAFT_ROOT
                     if core.DEFAULT_JIANYING_DRAFT_ROOT.is_dir()
                     else Path.cwd())
        self._probe.request(draft_dir, self._on_probe_done)

    def _on_probe_done(self, pt, jy):
        # 在 worker 线程被调用，必须切回 UI 线程更新 Tkinter 控件
        self.root.after(0, lambda: self._apply_status(pt, jy))

    def _apply_status(self, pt, jy):
        parts = [
            "PT " + ("在线" if pt[0] else "离线"),
            "剪映 " + ("运行中（导入前请退出）" if jy else "未运行"),
        ]
        self.var_status.set(" ｜ ".join(parts))
        # 探测结果回来后，让当前页的门控（按钮启用/禁用）跟着刷新 ——
        # 各页 refresh_states 现在读的是探测缓存，必须有人通知它们「有结果了」。
        tab = self._current_tab()
        if tab is not None and hasattr(tab, "refresh_states"):
            try:
                tab.refresh_states()
            except Exception:
                pass

    # ───────────── 拖放 ─────────────

    def _setup_dnd(self):
        if not DND_AVAILABLE:
            return
        tab = self._tabs[0]
        # v2.6.2（Q10）：拖拽区已取消。拖放目标改为**输入框本身** ——
        # 「剪映草稿目录」和「输出目录」都可以直接把文件夹拖进来，
        # 这正是用户原本想要的用法（拖到框里，而不是拖到一个大区域里）。
        targets = []
        for attr in ("entry_input_dir", "entry_output_dir"):
            w = getattr(tab, attr, None)
            if w is not None:
                targets.append(w)
        for t in targets:
            try:
                t.drop_target_register(DND_FILES)
                t.dnd_bind("<<Drop>>", self._on_drop)
                t.dnd_bind("<<DragEnter>>", self._on_drag_enter)
                t.dnd_bind("<<DragLeave>>", self._on_drag_leave)
            except Exception as e:
                print(f"[dnd] 注册失败 {t}: {e}")

    def _on_drag_enter(self, event):
        # 拖拽区已移除，不再做高亮（保留钩子，避免 dnd 绑定报错）
        return event.action

    def _on_drag_leave(self, event):
        return event.action

    def _on_drop(self, event):
        paths = parse_drop_paths(getattr(event, "data", "") or "")
        if not paths:
            return
        self.notebook.select(0)                   # 拖入即切到导出页
        self._tabs[0].on_drop(paths)

    # ───────────── 消息泵 ─────────────

    def _poll_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__tablog__":
                    _, tab, text = item
                    if tab._log is not None:
                        tab._log.configure(state="normal")
                        tab._log.insert("end", text)
                        tab._log.see("end")
                        tab._log.configure(state="disabled")
                elif isinstance(item, tuple) and item and item[0] == "__done__":
                    _, tab, on_done, err = item
                    btn = getattr(tab, "btn_run", None) or getattr(tab, "btn_import", None)
                    idle = getattr(tab, "btn_run", None)
                    tab.finish(on_done, err,
                               self._busy_button(tab),
                               self._idle_text(tab))
                    # W7：长任务跑完弹通知（成功才弹；失败靠日志，避免骚扰）
                    if err is None and getattr(tab, "title", None):
                        toast(self.root, "剪映工程工具包",
                              f"{tab.title} 完成")
                else:
                    tab = self._current_tab()
                    if tab is not None and tab._log is not None:
                        tab._log.configure(state="normal")
                        tab._log.insert("end", item)
                        tab._log.see("end")
                        tab._log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    @staticmethod
    def _busy_button(tab):
        """找出该页正在跑任务时被禁用的那个按钮。"""
        for name in ("btn_run", "btn_import", "btn_parse", "btn_preview", "btn_dry"):
            b = getattr(tab, name, None)
            if b is not None and str(b["state"]) == "disabled":
                return b
        return None

    @staticmethod
    def _idle_text(tab):
        """按按钮身份还原正确文案。"""
        b = JianYingToolkitApp._busy_button(tab)
        if b is None:
            return ""
        mapping = {
            "btn_run": "▶ 开始导出",
            "btn_import": "② 导入到剪映草稿",
            "btn_parse": "① 解析 PT 工程",
            "btn_preview": "预演（不写入）",
            "btn_dry": "预演（只列素材不复制）",
        }
        val = getattr(tab, "_idle_label", None)
        if val:
            return val
        m = mapping.get(_button_name(tab, b))
        if isinstance(m, tuple):
            # 导出页与交付页都叫 btn_run，用页标题区分
            return m[0] if tab.title.startswith("①") else m[1]
        return m or "执行"


def _button_name(tab, btn) -> str:
    for name in ("btn_run", "btn_import", "btn_parse", "btn_preview", "btn_dry"):
        if getattr(tab, name, None) is btn:
            return name
    return ""


def main():
    try:
        core._safe_io()          # --windowed 打包时 stdout/stderr 可能为 None
    except Exception:
        pass
    root = make_root()
    JianYingToolkitApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
