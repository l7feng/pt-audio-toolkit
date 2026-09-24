# -*- coding: utf-8 -*-
"""pt-tools 主窗口与页签（W1 三层拆分 · gui/app）。

唯一 GUI 层：只负责收集参数 → 调 core/naming.build_export_cmds →
交给 worker/runner.CmdWorker 后台执行；领域逻辑一律在 core。
"""
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ptools.core.config import load_config, save_config
from ptools.core.i18n import T, get_lang, set_lang, LANG_EN, LANG_ZH
from ptools.core.logs import setup_logging
from ptools.core.naming import (
    build_export_cmds, fmt_choices, fmt_display_of, fmt_key_of,
    fmt_label, frame_to_tc, load_profile, open_in_explorer,
    parse_video_duration_output, tc_to_frame,
)
from ptools.core.notify import toast
from ptools.core.paths import PathResolver
from ptools.core.settings import (
    APP_DIR, BIT_DEPTHS, CREATE_NO_WINDOW, DEFAULT_EXPORT_FORMAT,
    DEFAULT_FALLBACK_DURATION, DEFAULT_VIDEO_MARGIN, EXPORT_MODES,
    FORMAT_FOLLOW, SAMPLE_RATES, TRACK_FMT_CYCLE,
)
from ptools.worker.runner import CmdWorker, ptsl_online

# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # 三重保险消除 Tk 启动闪窗：
        #  Tk() 创建根窗口即按默认标题 "tk" 映射；withdraw 隐藏（窗口 unmapped，
        #  不可见也不接收输入），overrideredirect 使其不进任务栏，alpha=0 全透明
        #  兜底最后一张渲染帧。全部构建完成后一次性恢复显示。
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-alpha", 0.0)

        # 样式必须绑定本 root 配置（显式 master=self）。
        # 曾经的 bug：ttk.Style().configure(...) 在 App() 之前调用 —— 那时还没有任何
        # root，ttk.Style() 会隐式创建一个默认 Tk() root（标题 'tk'）；App() 随后再建
        # 第二个 root，结果永久残留一个空白「tk」小窗（withdraw 只作用于第二个 root）。
        # 传 master=self 保证复用本 root，绝不产生第二个窗口。
        try:
            ttk.Style(master=self).configure("Danger.TFrame", background="#b00")
        except tk.TclError:
            pass

        self.cfg = load_config()
        set_lang(self.cfg.get("lang", LANG_ZH))
        self.logger = setup_logging()
        if self.logger is not None:
            self.logger.info("语言=%s 技能目录=%s",
                             self.cfg.get("lang"),
                             self.cfg.get("skills_root") or "(探测中)")
        self.resolver, _ok, _msg = PathResolver.detect(self.cfg)
        self.profile_path = self.cfg.get("last_profile", "")
        self.profile_data = None
        self.ptsl_on = False

        self.out_queue = queue.Queue()
        self.workers = []
        self.active_worker = None      # v1.3.0：当前在跑的 worker（中止按钮用）
        self._vars = {}

        self._build_ui()
        self._restore_profile_to_tabs()

        # v1.3.0：点 X 一定关得掉。
        # 旧行为的根因之二：App 从未注册 WM_DELETE_WINDOW，destroy 之后主线程试图
        # 退出却被 subprocess 的 atexit 钩子挂住（它在等仍存活的子进程）。
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.after(100, self._poll_queue)
        self.after(1000, self._poll_ptsl)
        self._refresh_resolver_status()
        if self.profile_path:
            self._try_load_profile(self.profile_path)

        # 控件就绪后一次性显示
        self._center_on_screen()
        self.overrideredirect(False)
        self.attributes("-alpha", 1.0)
        self.deiconify()
        self.lift()
        self.focus_force()

    def _center_on_screen(self):
        """把窗口摆到屏幕中央（避免出现在左上角默认位置）"""
        try:
            self.update_idletasks()
            w = self.winfo_width() or 860
            h = self.winfo_height() or 680
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
            self.geometry("+%d+%d" % (x, y))
        except tk.TclError:
            pass

    # ---------------- UI 构建 / 重建 ----------------

    def _build_ui(self):
        self.title(T("app_title"))
        self.geometry("860x680")
        self.minsize(780, 600)
        self._build_menubar()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.scan_tab = ScanTab(nb, self)
        self.export_tab = ExportTab(nb, self)
        self.clean_tab = CleanTab(nb, self)
        nb.add(self.scan_tab, text=T("tab_scan"))
        nb.add(self.export_tab, text=T("tab_export"))
        nb.add(self.clean_tab, text=T("tab_clean"))
        self._build_log()
        self._build_statusbar()

    def _rebuild_ui(self):
        """语言切换/设置变更后整体重建（StringVar 快照恢复）"""
        vals = self._snapshot_vars()
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()
        self._restore_vars(vals)
        self._restore_profile_to_tabs()
        self._refresh_resolver_status()
        self.scan_tab.set_ptsl(self.ptsl_on)
        self._refresh_gating()

    def _restore_profile_to_tabs(self):
        """重建后把已加载的档案重新喂给各页（不弹框，失败仅日志）"""
        if self.profile_path and os.path.isfile(self.profile_path):
            try:
                data = load_profile(self.profile_path)
            except ValueError as exc:
                self.log(T("msg_warn_profile_start") % exc)
                return
            self.profile_data = data
            self.export_tab.on_profile_loaded(self.profile_path, data)
            self.clean_tab.on_profile_loaded(data)

    # ---------------- StringVar 登记 ----------------

    def v(self, name, default=""):
        var = tk.StringVar(value=default)
        self._vars[name] = var
        return var

    def _snapshot_vars(self):
        return {k: vg.get() for k, vg in self._vars.items()}

    def _restore_vars(self, vals):
        for k, val in vals.items():
            if k in self._vars:
                self._vars[k].set(val)

    # ---------------- 菜单栏 ----------------

    def _build_menubar(self):
        mb = tk.Menu(self)

        m_file = tk.Menu(mb, tearoff=0)
        m_file.add_command(label=T("file_open_outdir"), command=self._open_outdir)
        m_file.add_command(label=T("file_open_cfgdir"), command=self._open_cfgdir)
        m_file.add_separator()
        m_file.add_command(label=T("file_exit"), command=self.destroy)
        mb.add_cascade(label=T("menu_file"), menu=m_file)

        m_sett = tk.Menu(mb, tearoff=0)
        m_lang = tk.Menu(m_sett, tearoff=0)
        zh_label = ("✓ " if get_lang() == LANG_ZH else "") + T("sett_lang_zh")
        en_label = ("✓ " if get_lang() == LANG_EN else "") + T("sett_lang_en")
        m_lang.add_command(label=zh_label, command=lambda: self.set_language(LANG_ZH))
        m_lang.add_command(label=en_label, command=lambda: self.set_language(LANG_EN))
        m_sett.add_cascade(label=T("sett_lang"), menu=m_lang)
        m_sett.add_separator()
        m_sett.add_command(label=T("sett_skills"), command=self._browse_skills_root)
        m_sett.add_command(label=T("sett_outdir"), command=self._set_default_outdir)
        mb.add_cascade(label=T("menu_settings"), menu=m_sett)

        m_tools = tk.Menu(mb, tearoff=0)
        m_tools.add_command(label=T("tools_open_skills"), command=self._open_skills_dir)
        m_tools.add_command(label=T("tools_open_outdir"), command=self._open_outdir)
        m_tools.add_command(label=T("tools_open_cfgdir"), command=self._open_cfgdir)
        m_tools.add_separator()
        m_tools.add_command(label=T("tools_clear_log"), command=self._clear_log)
        m_tools.add_command(label=T("tools_export_diag"), command=self._export_diag_bundle)
        mb.add_cascade(label=T("menu_tools"), menu=m_tools)

        m_help = tk.Menu(mb, tearoff=0)
        m_help.add_command(label=T("help_howto"), command=self._show_help)
        m_help.add_command(label=T("help_about"), command=self._show_about)
        mb.add_cascade(label=T("menu_help"), menu=m_help)

        self.config(menu=mb)

    def _open_outdir(self):
        d = self.cfg.get("last_out_dir", "")
        if not open_in_explorer(d):
            messagebox.showinfo(T("menu_file"), T("no_outdir"))

    def _open_cfgdir(self):
        os.makedirs(APP_DIR, exist_ok=True)
        os.startfile(APP_DIR)

    def _open_skills_dir(self):
        open_in_explorer(self.resolver.skills_root)

    def _browse_skills_root(self):
        chosen = filedialog.askdirectory(
            title=T("choose_skills_title"),
            initialdir=self.resolver.skills_root if os.path.isdir(self.resolver.skills_root) else None)
        if not chosen:
            return
        self.cfg["skills_root"] = chosen
        save_config(self.cfg)
        self.resolver = PathResolver(chosen)
        self._refresh_resolver_status()
        self.log("[cfg] 技能目录 -> %s\n" % chosen)

    def _set_default_outdir(self):
        chosen = filedialog.askdirectory(
            title=T("choose_outdir_title"),
            initialdir=self.cfg.get("last_out_dir") or None)
        if chosen:
            self.cfg["last_out_dir"] = chosen
            save_config(self.cfg)
            self._restore_vars({"export_out": chosen})
            self.log("[cfg] 默认输出目录 -> %s\n" % chosen)

    # ---------------- 语言切换 ----------------

    def set_language(self, lang):
        if lang == get_lang():
            return
        self.cfg["lang"] = lang
        save_config(self.cfg)
        set_lang(lang)
        self._rebuild_ui()
        self.log(T("lang_changed"))

    # ---------------- 日志 / 状态栏 ----------------

    def _build_log(self):
        frame = ttk.LabelFrame(self, text="  " + T("log_frame") + "  ", padding=(6, 4))
        frame.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        self.log_text = tk.Text(frame, height=9, wrap="word", undo=False,
                                font=("Consolas", 9))
        sb = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=8)
        ttk.Button(btn_row, text=T("log_clear"), command=self._clear_log,
                   width=16).pack(side="left")
        # v1.3.0 卡死专项：中止按钮 + 运行时长 / 无输出看门狗读数
        self.abort_btn = ttk.Button(btn_row, text=T("log_abort"),
                                    command=self._abort_worker, width=12,
                                    state="disabled")
        self.abort_btn.pack(side="left", padx=(8, 0))
        self.run_time_var = tk.StringVar(value="")
        ttk.Label(btn_row, textvariable=self.run_time_var,
                  foreground="#c00").pack(side="left", padx=(8, 0))
        ttk.Label(btn_row, text=T("log_hint"),
                  foreground="#888").pack(side="right")

    def _build_statusbar(self):
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(fill="x")
        self.status_ptsl_var = tk.StringVar(value="…")
        self.status_sess_var = tk.StringVar(value=T("status_session") % "—")
        self.status_prof_var = tk.StringVar(value=T("status_profile") % "—")
        self.status_skills_var = tk.StringVar(value="…")
        ttk.Label(bar, textvariable=self.status_ptsl_var).pack(side="left")
        ttk.Label(bar, textvariable=self.status_sess_var,
                  foreground="#555").pack(side="left", padx=16)
        ttk.Label(bar, textvariable=self.status_prof_var,
                  foreground="#555").pack(side="left", padx=16)
        ttk.Label(bar, textvariable=self.status_skills_var,
                  foreground="#888").pack(side="right")

    # 日志滚动上限：批量几十集时 Text 行数是主线程卡顿的隐形来源
    LOG_MAX_LINES = 5000

    def log(self, text):
        if not getattr(self, "log_text", None):
            return
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self._trim_log()

    def _trim_log(self):
        try:
            n = int(self.log_text.index("end-1c").split(".")[0])
            if n > self.LOG_MAX_LINES:
                self.log_text.delete("1.0", "%d.0" % (n - self.LOG_MAX_LINES + 1))
        except Exception:
            pass

    def _clear_log(self):
        if getattr(self, "log_text", None):
            self.log_text.delete("1.0", "end")

    def _export_diag_bundle(self):
        """工具 → 导出诊断包：调 worker.build_diag_bundle 打包日志+配置+版本号。

        产物落在 APP_DIR（%APPDATA%\\pt-tools\\）下，弹托盘通知给出路径。
        App 本身即 Tk 根窗口，toast 的第一个参数传 self（曾误写 App.win → AttributeError）。
        """
        import os
        from ptools.core.i18n import T
        from ptools.core.settings import APP_DIR, APP_VERSION, build_date
        from ptools.core.notify import toast
        from ptools.worker.runner import build_diag_bundle
        fname = "pt-tools-diag-%s-%s.zip" % (APP_VERSION, build_date())
        out = os.path.join(APP_DIR, fname)
        try:
            path, n = build_diag_bundle(out)
            toast(self, T("toast_title"), T("msg_diag_exported") % path)
        except Exception as e:
            toast(self, T("toast_title"), T("msg_diag_failed") % e)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.out_queue.get_nowait()
                if kind == "line":
                    self.log(payload if payload.endswith("\n") else payload + "\n")
                elif kind == "tick":
                    pass          # 心跳：worker 内部已更新 _last_out
                elif kind == "stall":
                    self.log(T("log_stalled") % payload)
                elif kind == "done":
                    self._on_worker_done(payload)
        except queue.Empty:
            pass
        self._update_run_clock()
        self.after(100, self._poll_queue)

    def _update_run_clock(self):
        """运行时长 + 距上次输出秒数（无输出 ≥30s 才显示，避免刷屏）。"""
        w = self.active_worker
        if w is None or not w.is_alive():
            if self.run_time_var.get():
                self.run_time_var.set("")
            return
        el = int(time.time() - w.started_at)
        txt = T("log_running") % (el // 60, el % 60)
        gap = int(time.time() - w._last_out)
        if gap >= 30:
            txt += " · " + (T("log_no_output") % gap)
        self.run_time_var.set(txt)

    def _abort_worker(self):
        """「■ 中止」按钮 —— 真正能停（旧版 cancelled 标志全仓无人置 True）。"""
        w = self.active_worker
        if w is None:
            return
        if not messagebox.askyesno(T("abort_title"), T("abort_confirm")):
            return
        self.log(T("log_aborting"))
        w.cancel()

    def _on_worker_done(self, returncode):
        self.active_worker = None
        if getattr(self, "abort_btn", None):
            self.abort_btn.configure(state="disabled")
        self.scan_tab.on_worker_done(returncode)
        self.export_tab.on_worker_done(returncode)
        self._refresh_gating()
        if self.logger is not None:
            self.logger.info("命令队列结束，退出码=%s", returncode)
        if returncode == -1:
            self.log(T("cmd_aborted"))
            toast(self, T("toast_title"), T("toast_aborted"))
        else:
            self.log(T("cmd_done") % returncode)
            # W7：长任务跑完弹通知，人切去干别的也能被叫回来
            toast(self, T("toast_title"), T("toast_done") % returncode)

    def start_worker(self, cmds):
        """启动后台命令队列。cmds 可为单条命令（list[str]）或命令列表。"""
        if cmds and isinstance(cmds[0], str):
            cmds = [cmds]
        for cmd in cmds:
            self.log("> %s\n" % " ".join('"%s"' % c if " " in c else c for c in cmd))
        if self.logger is not None:
            self.logger.info(
                "启动命令队列（%d 条）：%s",
                len(cmds),
                " | ".join(" ".join(c) for c in cmds))
        self.workers = [x for x in self.workers if x.is_alive()]   # 只留活着的
        w = CmdWorker(cmds, self.out_queue)
        self.workers.append(w)
        self.active_worker = w
        if getattr(self, "abort_btn", None):
            self.abort_btn.configure(state="normal")
        w.start()
        return w

    def _on_close(self):
        """点 X 一定关得掉（Q12）。

        旧行为：destroy 之后主线程试图退出，却被 subprocess 的 atexit 钩子挂住
        —— 它在等仍存活的子进程 —— 于是表现为"点关闭没反应，只能从任务管理器杀"。
        现在：有活任务先问一句，确认后终止本工具自己 spawn 的子进程树，再退出。
        ⚠️ 只杀 self.workers 里的子进程，绝不碰 ProTools.exe。
        """
        running = [w for w in self.workers if w.is_alive()]
        if running:
            if not messagebox.askyesno(T("quit_title"), T("quit_confirm")):
                return
            for w in running:
                try:
                    w.cancel()
                except Exception:
                    pass
            for w in running:
                w.join(timeout=3)
        try:
            self.destroy()
        except Exception:
            pass
        # os._exit 跳过 atexit 的 subprocess 等待，保证进程一定退出
        os._exit(0)

    # ---------------- 状态 ----------------

    def _poll_ptsl(self):
        on = ptsl_online()
        self.ptsl_on = on
        self.status_ptsl_var.set(T("status_ptsl_on") if on else T("status_ptsl_off"))
        self.scan_tab.set_ptsl(on)
        self._refresh_gating()
        self.after(5000, self._poll_ptsl)

    def _refresh_gating(self):
        self.scan_tab.refresh_buttons()
        self.export_tab.refresh_buttons()

    def _refresh_resolver_status(self):
        ok, _msg = self.resolver.status()
        self.status_skills_var.set(T("status_skills_ok") if ok
                                   else T("status_skills_bad"))
        if not ok:
            self.log("[warn] " + _msg + "\n")

    # ---------------- profile 共享 ----------------

    def apply_profile(self, path):
        """扫描完成后：应用档案到全局与各页"""
        try:
            data = load_profile(path)
        except ValueError as exc:
            messagebox.showerror(T("msg_profile_invalid"), str(exc))
            return False
        self.profile_path = path
        self.profile_data = data
        self.cfg["last_profile"] = path
        save_config(self.cfg)
        sess = data["session"]
        self.status_sess_var.set(T("status_session") % sess.get("name", "?"))
        self.status_prof_var.set(T("status_profile") % path)
        self.export_tab.on_profile_loaded(path, data)
        self.clean_tab.on_profile_loaded(data)
        return True

    def _try_load_profile(self, path):
        try:
            data = load_profile(path)
        except ValueError as exc:
            self.log(T("msg_warn_profile_start") % exc)
            return
        self.profile_data = data
        sess = data["session"]
        self.status_sess_var.set(T("status_session") % sess.get("name", "?"))
        self.status_prof_var.set(T("status_profile") % path)
        self.export_tab.on_profile_loaded(path, data)
        self.clean_tab.on_profile_loaded(data)

    # ---------------- 帮助 / 关于 ----------------

    def _show_help(self):
        win = tk.Toplevel(self)
        win.title(T("help_howto"))
        win.transient(self)
        win.geometry("560x430")
        t = tk.Text(win, wrap="word", padx=12, pady=12, font=("Microsoft YaHei UI", 10))
        t.insert("1.0", T("help_text"))
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)

    def _show_about(self):
        win = tk.Toplevel(self)
        win.title(T("help_about"))
        win.transient(self)
        win.geometry("460x260")
        t = tk.Text(win, wrap="word", padx=12, pady=12, font=("Microsoft YaHei UI", 10))
        t.insert("1.0", T("about_text"))
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)


# ---------------------------------------------------------------------------
# Tab 1 · 扫描建档
# ---------------------------------------------------------------------------

class ScanTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        self.busy = False
        self.last_profile_path = ""

        # —— 本页功能说明 ——
        what = ttk.LabelFrame(self, text="  " + T("s_what_title") + "  ", padding=8)
        what.pack(fill="x")
        ttk.Label(what, text=T("s_what_body"), wraplength=760,
                  justify="left").pack(anchor="w")

        # —— 扫描前提 + 步骤 ——
        cond = ttk.Frame(self)
        cond.pack(fill="x", pady=(8, 8))
        req = ttk.LabelFrame(cond, text="  " + T("s_req_title") + "  ", padding=8)
        req.pack(side="left", fill="x", expand=True)
        self.ptsl_label = ttk.Label(req, text=T("s_req_ptsl_off"))
        self.ptsl_label.pack(anchor="w")
        ttk.Label(req, text=T("s_req_line2"), foreground="#555").pack(anchor="w", pady=(2, 0))

        steps = ttk.LabelFrame(cond, text="  " + T("s_steps_title") + "  ", padding=8)
        steps.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Label(steps, text=T("s_step1")).pack(anchor="w")
        ttk.Label(steps, text=T("s_step2"), foreground="#555").pack(anchor="w", pady=(2, 0))
        ttk.Label(steps, text=T("s_step3"), foreground="#555").pack(anchor="w", pady=(2, 0))

        # —— 输出目录 / 档案名 / 扫描按钮 ——
        # v1.4.0：建档输出默认走 profile_dir（PT-Tools-Backup/json），不再与
        # 导出输出共用 last_out_dir —— 两个落点语义不同，混用一个值会互相带偏。
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text=T("s_out")).pack(side="left")
        self.out_var = app.v("scan_out",
                             app.cfg.get("profile_dir") or app.cfg.get("last_out_dir", ""))
        ttk.Entry(row, textvariable=self.out_var, width=44).pack(side="left", padx=6)
        ttk.Button(row, text=T("s_browse"), command=self._browse_out,
                   width=10).pack(side="left")

        row2 = ttk.Frame(self)
        row2.pack(fill="x", pady=(0, 10))
        ttk.Label(row2, text=T("s_name")).pack(side="left")
        self.name_var = app.v("scan_name", "pt-profile.json")
        ttk.Entry(row2, textvariable=self.name_var, width=24).pack(side="left", padx=6)
        self.scan_btn = ttk.Button(row2, text=T("s_scan_btn"),
                                   command=self.do_scan)
        self.scan_btn.pack(side="left", padx=6)

        # —— 扫描摘要 ——
        summ = ttk.LabelFrame(self, text="  " + T("s_summary") + "  ", padding=6)
        summ.pack(fill="both", expand=True)
        self.summary_text = tk.Text(summ, height=12, wrap="word",
                                    font=("Consolas", 9), state="disabled")
        sb = ttk.Scrollbar(summ, command=self.summary_text.yview)
        self.summary_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.summary_text.pack(side="left", fill="both", expand=True)

    def _browse_out(self):
        chosen = filedialog.askdirectory(
            title=T("choose_outdir_title"),
            initialdir=self.out_var.get() or None)
        if chosen:
            self.out_var.set(chosen)
            # 建档目录单独记忆（profile_dir），不与导出输出（last_out_dir）混用
            self.app.cfg["profile_dir"] = chosen
            save_config(self.app.cfg)

    def set_ptsl(self, on):
        if not getattr(self, "ptsl_label", None):
            return
        text = T("s_req_ptsl_on") if on else T("s_req_ptsl_off")
        color = "#0a0" if on else "#b00"
        self.ptsl_label.configure(text=text, foreground=color)

    def refresh_buttons(self):
        self.scan_btn.state(["disabled"] if (self.busy or not self.app.ptsl_on)
                            else ["!disabled"])

    def do_scan(self):
        out = self.out_var.get().strip()
        name = self.name_var.get().strip()
        if not out:
            messagebox.showerror(T("msg_missing"), T("s_missing_out"))
            return
        if not name.endswith(".json"):
            messagebox.showerror(T("msg_invalid"), T("s_bad_name"))
            return
        # v1.4.0：建档目录不存在就现建，别等扫描器写文件时才报错
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(T("msg_invalid"), str(exc))
            return
        cmd = [self.app.resolver.venv_python,
               self.app.resolver.script("pt-scanner"),
               "--out", out, "--name", name]
        self.busy = True
        self.refresh_buttons()
        self.app.start_worker(cmd)

    def on_worker_done(self, returncode):
        if not self.busy:
            return
        self.busy = False
        if returncode == 0:
            out = self.out_var.get().strip()
            path = os.path.join(out, self.name_var.get().strip())
            # v1.4.0：平铺档案按工程名自动命名（用户拍板方案 B）
            path = self._rename_by_session(out, path)
            self.last_profile_path = path
            self._show_summary(path)
            if self.app.apply_profile(path):
                self.app.log(T("s_auto_applied") % path)
        self.refresh_buttons()

    def _rename_by_session(self, out_dir, path):
        """v1.4.0：扫描完成后把档案改名成 `<工程名>-pt-profile.json`。

        档案存放方式（2026-09-24 拍板）：**平铺 + 文件名区分**，不建
        per-project 文件夹 —— pt-profile.json 是自包含单文件，平铺后
        「浏览档案」一眼看全所有工程，按名排序即按工程分组。
        工程名取自扫描结果 session.name（非法文件名字符清洗为下划线）；
        同名重扫直接覆盖（同一工程刷新档案）；改名失败不阻断流程，
        保留原文件名照常加载。
        """
        try:
            data = load_profile(path)
            name = ((data.get("session") or {}).get("name") or "").strip()
        except Exception:
            return path
        if not name:
            return path
        safe = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .") or "pt-profile"
        target = os.path.join(out_dir, "%s-pt-profile.json" % safe)
        try:
            if os.path.abspath(target) != os.path.abspath(path):
                if os.path.exists(target):
                    os.remove(target)
                os.rename(path, target)
            self.name_var.set(os.path.basename(target))
            return target
        except OSError:
            return path

    def _show_summary(self, path):
        try:
            data = load_profile(path)
        except ValueError as exc:
            self._set_summary(T("sum_err") % exc)
            return
        sess = data["session"]
        src = data["sources"]
        lines = [
            "%s: %s" % (T("sum_session"), sess.get("name", "?")),
            "%s: %s" % (T("sum_path"), sess.get("path", "?")),
            T("sum_rate") % (sess.get("sample_rate"), sess.get("bit_depth"),
                             sess.get("timecode_rate")),
            T("sum_range") % (sess.get("start_time"), sess.get("length")),
            "%s: %d" % (T("sum_tracks"), len(data.get("tracks", []))),
            "%s: %s" % (T("sum_bus"), ", ".join(src.get("bus", []))),
            "%s: %s" % (T("sum_output"), ", ".join(src.get("output", []))),
            "%s: %s" % (T("sum_phys"), ", ".join(src.get("physicalout", []))),
        ]
        self._set_summary("\n".join(lines) + "\n")

    def _set_summary(self, text):
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", text)
        self.summary_text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Tab 2 · 导出
# ---------------------------------------------------------------------------

class ExportTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        self.busy = False
        self.preview_ok = False
        self._profile_path = ""
        self._profile = None
        self._preview_signature = ""

        # -- 档案
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text=T("e_profile")).pack(side="left")
        self.profile_var = app.v("export_profile", app.profile_path)
        ttk.Entry(row, textvariable=self.profile_var, width=44).pack(side="left", padx=6)
        ttk.Button(row, text=T("e_browse"),
                   command=self._browse_profile).pack(side="left")

        # -- 导出模式（v1.1.0 四模式多选：勾哪几个就按顺序导哪几路）
        row2 = ttk.Frame(self)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text=T("e_mode")).pack(side="left")
        # 勾选用 StringVar("1"/"0")：走 App._vars 快照，语言切换整窗重建不丢状态
        self.mode_mix_var = app.v("mode_mix", "1")
        self.mode_stem_var = app.v("mode_stem", "1")
        self.stem_aux_var = app.v("stem_aux", "0")
        self.mode_bus_var = app.v("mode_bus", "0")
        self.mode_track_var = app.v("mode_track", "0")
        self.cb_mix = ttk.Checkbutton(row2, text=T("e_mode_mix"),
                                      variable=self.mode_mix_var,
                                      onvalue="1", offvalue="0")
        self.cb_stem = ttk.Checkbutton(row2, text=T("e_mode_stem"),
                                       variable=self.mode_stem_var,
                                       onvalue="1", offvalue="0")
        self.cb_stem_aux = ttk.Checkbutton(row2, text=T("e_mode_stem_aux"),
                                           variable=self.stem_aux_var,
                                           onvalue="1", offvalue="0")
        self.cb_bus = ttk.Checkbutton(row2, text=T("e_mode_bus"),
                                      variable=self.mode_bus_var,
                                      onvalue="1", offvalue="0")
        self.cb_track = ttk.Checkbutton(row2, text=T("e_mode_track"),
                                        variable=self.mode_track_var,
                                        onvalue="1", offvalue="0")
        for _w in (self.cb_mix, self.cb_stem, self.cb_stem_aux,
                   self.cb_bus, self.cb_track):
            _w.pack(side="left", padx=3)

        # -- 工程
        row2b = ttk.Frame(self)
        row2b.pack(fill="x", pady=(4, 0))
        ttk.Label(row2b, text=T("e_session"),
                  foreground="#555").pack(side="left")
        self.sess_mode_var = app.v("sess_mode", "current")
        ttk.Radiobutton(row2b, text=T("e_sess_current"), value="current",
                        variable=self.sess_mode_var,
                        command=self._on_sess_mode_change).pack(side="left")
        ttk.Radiobutton(row2b, text=T("e_sess_file"), value="file",
                        variable=self.sess_mode_var,
                        command=self._on_sess_mode_change).pack(side="left")
        self.session_var = app.v("session_file", "")
        ttk.Entry(row2b, textvariable=self.session_var, width=40,
                  state="readonly").pack(side="left", padx=4)
        ttk.Button(row2b, text=T("e_browse"),
                   command=self._browse_session).pack(side="left")

        # -- 轨道列表（v1.2.0 勾选式选轨：STEM /「按轨道名称」共用；
        #    空轨与排除名单默认不勾，全选/全不选一键切换）
        src = ttk.LabelFrame(self, text="  " + T("e_track_frame_v2") + "  ", padding=6)
        src.pack(fill="both", expand=True, pady=(8, 0))

        # 排除名单行（config 记忆：track_exclude）
        xrow = ttk.Frame(src)
        xrow.pack(fill="x")
        ttk.Label(xrow, text=T("e_exclude"),
                  foreground="#555").pack(side="left")
        self.exclude_var = app.v("track_exclude",
                                 app.cfg.get("track_exclude", ""))
        ttk.Entry(xrow, textvariable=self.exclude_var).pack(
            side="left", fill="x", expand=True, padx=6)
        self.exclude_var.trace_add("write", self._on_exclude_changed)
        ttk.Button(xrow, text=T("e_select_all"), width=9,
                   command=lambda: self._set_all_tracks(True)).pack(side="left", padx=2)
        ttk.Button(xrow, text=T("e_deselect_all"), width=9,
                   command=lambda: self._set_all_tracks(False)).pack(side="left", padx=2)

        # 搜索行
        srow = ttk.Frame(src)
        srow.pack(fill="x")
        ttk.Label(srow, text=T("e_search") + " ",
                  foreground="#555").pack(side="left")
        self.search_var = app.v("src_search", "")
        ttk.Entry(srow, textvariable=self.search_var, width=18).pack(side="left", padx=6)
        self.search_var.trace_add("write", lambda *a: self._reload_sources())
        self.src_count_var = tk.StringVar(value=T("e_selected") % 0)
        ttk.Label(srow, textvariable=self.src_count_var,
                  foreground="#555").pack(side="right")

        # 列：选(☑/☐) / 名称 / 类型 / 音频块 / 声道（v1.3.0 每条轨道可单独指定）
        self.src_tree = ttk.Treeview(
            src, columns=("sel", "name", "type", "clips", "fmt"),
            show="headings", selectmode="none", height=6)
        self.src_tree.heading("sel", text=T("e_sel_col"))
        self.src_tree.heading("name", text=T("e_name_col"))
        self.src_tree.heading("type", text=T("e_type_col"))
        self.src_tree.heading("clips", text=T("e_clips_col"))
        self.src_tree.heading("fmt", text=T("e_fmt_col"))
        self.src_tree.column("sel", width=44, anchor="center", stretch=False)
        self.src_tree.column("name", width=250)
        self.src_tree.column("type", width=70, anchor="center", stretch=False)
        self.src_tree.column("clips", width=50, anchor="center", stretch=False)
        self.src_tree.column("fmt", width=150, anchor="center", stretch=False)
        tree_wrap = ttk.Frame(src)
        tree_wrap.pack(fill="both", expand=True, pady=(4, 0))
        sb = ttk.Scrollbar(tree_wrap, command=self.src_tree.yview)
        self.src_tree.configure(yscrollcommand=sb.set)
        self.src_tree.pack(in_=tree_wrap, side="left", fill="both", expand=True)
        sb.pack(in_=tree_wrap, side="left", fill="y")
        self.src_tree.bind("<Button-1>", self._on_track_click)
        # 勾选集合（轨道名）与排除名单解析缓存
        self.track_checked = set()
        self._exclude_pats = []
        # v1.3.0：每条轨道的格式覆盖（轨名 -> 内部 key；空串/缺失 = 跟随全局）
        self.track_fmt = {}
        # v1.3.0：被剔除的空轨里，用户显式「加回（撤回）」的那些 —— 不再被剔除
        self.track_restored = set()
        self._reparse_exclude()

        ttk.Label(src, text=T("e_fmt_hint"), foreground="#888",
                  wraplength=720, justify="left").pack(fill="x", pady=(2, 0))

        # -- 时间 / 格式 / 输出
        opt = ttk.LabelFrame(self, text="  " + T("e_params") + "  ", padding=6)
        opt.pack(fill="x", pady=(8, 0))
        opt.columnconfigure(1, weight=3)
        opt.columnconfigure(3, weight=1)
        ttk.Label(opt, text=T("e_start")).grid(row=0, column=0, sticky="w")
        self.start_var = app.v("start", "00:00:00:00")
        ttk.Entry(opt, textvariable=self.start_var, width=14).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(opt, text=T("e_end")).grid(row=0, column=2, sticky="w")
        self.end_var = app.v("end", "")
        ttk.Entry(opt, textvariable=self.end_var, width=14).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Button(opt, text=T("e_video_auto"), width=12,
                   command=self._autodetect_video).grid(row=0, column=4, sticky="w", padx=(4, 0))
        ttk.Button(opt, text=T("e_fill_video"), width=12,
                   command=self._fill_from_video).grid(row=0, column=5, sticky="w", padx=(4, 0))
        ttk.Label(opt, text=T("e_tc_hint"), foreground="#888").grid(row=0, column=6, sticky="w")

        # v1.2.0：视频余量 / 兜底时长（config 记忆，批量对话框沿用）
        mrow = ttk.Frame(opt)
        mrow.grid(row=1, column=0, columnspan=7, sticky="w", pady=(4, 0))
        ttk.Label(mrow, text=T("e_margin")).pack(side="left")
        # v1.3.0：默认 0（旧默认 240 = 每条片子都被加 4 分钟尾巴）
        self.margin_var = app.v("video_margin",
                                str(app.cfg.get("video_margin", DEFAULT_VIDEO_MARGIN)))
        ttk.Spinbox(mrow, from_=0, to=3600, increment=10, width=7,
                    textvariable=self.margin_var).pack(side="left", padx=(2, 12))
        ttk.Label(mrow, text=T("e_fallback")).pack(side="left")
        # v1.3.0：默认 60（旧默认 240 = 没检出视频时假装片子 4 分钟，会截断长片）
        self.fallback_var = app.v("fallback_duration",
                                  str(app.cfg.get("fallback_duration",
                                                  DEFAULT_FALLBACK_DURATION)))
        ttk.Spinbox(mrow, from_=1, to=3600, increment=10, width=7,
                    textvariable=self.fallback_var).pack(side="left", padx=(2, 12))
        ttk.Label(mrow, text=T("e_video_margin_note"),
                  foreground="#888").pack(side="left", padx=(0, 16))
        self.by_session_var = app.v("out_by_session",
                                    "1" if app.cfg.get("out_by_session", True) else "0")
        ttk.Checkbutton(mrow, text=T("e_by_session"),
                        variable=self.by_session_var,
                        onvalue="1", offvalue="0").pack(side="left")

        ttk.Label(opt, text=T("e_sr")).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.sr_var = app.v("sample_rate", str(SAMPLE_RATES[0]))
        ttk.Combobox(opt, textvariable=self.sr_var, values=[str(x) for x in SAMPLE_RATES],
                     state="readonly", width=10).grid(row=2, column=1, sticky="w", padx=4, pady=(4, 0))
        ttk.Label(opt, text=T("e_bd")).grid(row=2, column=2, sticky="w")
        self.bd_var = app.v("bit_depth", "24")
        ttk.Combobox(opt, textvariable=self.bd_var, values=[str(x) for x in BIT_DEPTHS],
                     state="readonly", width=8).grid(row=2, column=3, sticky="w", padx=4, pady=(4, 0))
        ttk.Label(opt, text=T("e_fmt")).grid(row=2, column=4, sticky="w")
        # v1.3.0：默认 interleaved（旧默认 mono 会把立体声静默下混）+ 中文显示名
        self.fmt_var = app.v("format", fmt_display_of(app.cfg.get("format")))
        ttk.Combobox(opt, textvariable=self.fmt_var, values=fmt_choices(),
                     state="readonly", width=26).grid(row=2, column=5, sticky="w", padx=4, pady=(4, 0))

        # v1.3.0：剔除空轨道（Q7）—— 空轨默认不导，且可查看/撤回
        erow = ttk.Frame(opt)
        erow.grid(row=4, column=0, columnspan=7, sticky="w", pady=(4, 0))
        self.exclude_empty_var = app.v("exclude_empty",
                                       "1" if app.cfg.get("exclude_empty", True) else "0")
        ttk.Checkbutton(erow, text=T("e_exclude_empty"),
                        variable=self.exclude_empty_var, onvalue="1", offvalue="0",
                        command=self._on_param_changed).pack(side="left")
        self.excluded_btn = ttk.Button(erow, text=T("e_excluded_view") % 0,
                                       command=self._show_excluded, state="disabled")
        self.excluded_btn.pack(side="left", padx=(12, 0))

        ttk.Label(opt, text=T("e_out")).grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.out_var = app.v("export_out", app.cfg.get("last_out_dir", ""))
        self.out_entry = ttk.Entry(opt, textvariable=self.out_var)
        self.out_entry.grid(row=3, column=1, columnspan=4, sticky="we", padx=4, pady=(4, 0))
        self.out_browse_btn = ttk.Button(opt, text=T("e_browse"), command=self._browse_out)
        self.out_browse_btn.grid(row=3, column=5, sticky="w", padx=4)
        # v1.3.0：输出目录锁定（Q3）+ 落盘预览（Q6）
        self.out_locked = False
        self.out_lock_btn = ttk.Button(opt, text=T("e_lock"), width=8,
                                       command=self._toggle_out_lock)
        self.out_lock_btn.grid(row=3, column=6, sticky="w", padx=(4, 0))
        ttk.Button(opt, text=T("e_out_preview"), width=14,
                   command=self._preview_out_paths).grid(row=3, column=7, sticky="w", padx=(4, 0))

        # -- 参数变化联动：勾选联动 + 预览失效闸门（v1.1.0 补实装）
        #    此前 UI 文案承诺「参数一变执行按钮熄灭」但从未比对签名——现绑定 trace 补齐
        for _var in (self.mode_mix_var, self.mode_stem_var, self.stem_aux_var,
                     self.mode_bus_var, self.mode_track_var,
                     self.start_var, self.end_var, self.sr_var, self.bd_var,
                     self.fmt_var, self.out_var, self.session_var,
                     self.sess_mode_var, self.profile_var,
                     self.margin_var, self.fallback_var, self.by_session_var,
                     self.exclude_empty_var):
            _var.trace_add("write", lambda *a: self._on_param_changed())
        self._sync_mode_gating()

        # -- 操作按钮
        btnrow = ttk.Frame(self)
        btnrow.pack(fill="x", pady=(8, 0))
        self.preview_btn = ttk.Button(btnrow, text=T("e_preview"),
                                      command=self.do_preview)
        self.preview_btn.pack(side="left")
        self.export_btn = ttk.Button(btnrow, text=T("e_export"),
                                     command=self.do_export)
        self.export_btn.pack(side="left", padx=8)
        self.batch_btn = ttk.Button(btnrow, text=T("e_batch"),
                                    command=self.open_batch_dialog)
        self.batch_btn.pack(side="left", padx=8)
        ttk.Label(btnrow, text=T("e_verify"),
                  foreground="#888").pack(side="right")

    # ---------------- 档案与数据 ----------------

    def _browse_profile(self):
        # v1.4.0：没加载过档案时，默认打开建档输出目录（profile_dir），
        # 而不是系统「最近的」某个无关目录 —— 档案就该在档案库里找。
        initial = os.path.dirname(self.profile_var.get()) if self.profile_var.get() \
            else (self.app.cfg.get("profile_dir") or None)
        path = filedialog.askopenfilename(
            title=T("choose_profile_title"),
            filetypes=[("JSON", "*.json")],
            initialdir=initial or None)
        if path:
            self._load_profile(path)

    def on_profile_loaded(self, path, data):
        self._load_profile(path, data)

    def _load_profile(self, path, data=None):
        try:
            if data is None:
                data = load_profile(path)
        except ValueError as exc:
            messagebox.showerror(T("msg_profile_invalid"), str(exc))
            return
        self._profile_path = path
        self._profile = data
        self.profile_var.set(path)
        sess = data["session"]
        if not self.end_var.get() and sess.get("length"):
            self.end_var.set(sess["length"])
        sr = sess.get("sample_rate")
        if sr and str(sr) in [str(x) for x in SAMPLE_RATES]:
            self.sr_var.set(str(sr))
        # v1.4.0（Q·指定文件默认父级）：档案里记着扫描时的 .ptx 路径（= PT 当前
        # 打开的工程）。此刻若处于「指定文件」模式且框是空的，直接预填它 ——
        # 点「浏览」也会默认开在其父级目录，不用每次手翻。
        if self.sess_mode_var.get() == "file" and not self.session_var.get().strip():
            sp = (sess.get("path") or "").strip()
            if sp:
                self.session_var.set(sp)
        self._reload_sources()
        self.refresh_buttons()

    def _reparse_exclude(self):
        """排除名单 → pattern 列表（逗号分隔；含 * ? 按通配，否则精确）。"""
        import fnmatch
        raw = (self.exclude_var.get() or "").strip()
        self._exclude_pats = [x.strip() for x in raw.split(",") if x.strip()]
        self._exclude_fn = fnmatch.fnmatchcase

    def _on_exclude_changed(self, *_a):
        """排除名单变化：重解析 + 重渲染列表 + 存配置。"""
        self._reparse_exclude()
        self.app.cfg["track_exclude"] = self.exclude_var.get().strip()
        save_config(self.app.cfg)
        self._reload_sources()
        self._invalidate_preview()

    def _track_excluded(self, name):
        return any(self._exclude_fn(name, p) for p in self._exclude_pats)

    def _track_default_checked(self, t, name):
        """默认勾选规则：有音频块 且 不在排除名单（用户手动勾选不受影响）。"""
        clips = (t.get("attributes") or {}).get("contains_clips")
        if clips is None:
            clips = t.get("contains_clips")
        if clips is False:
            return False
        return not self._track_excluded(name)

    def _reload_sources(self):
        """档案轨道 → 勾选式列表（选/名称/类型/音频块）。

        v1.2.0：默认勾选 = 有音频块 且 不在排除名单；空轨与排除轨灰显标注。
        用户此前手动勾过的轨道保持原状（switch 到别的档案时重置）。
        """
        new_profile = self._profile_path != getattr(self, "_loaded_for", None)
        if new_profile:
            self.track_checked = set()
            self._loaded_for = self._profile_path
        self.src_tree.delete(*self.src_tree.get_children())
        if not self._profile:
            self._update_src_count()
            return
        q = self.search_var.get().strip().lower()
        for t in self._profile.get("tracks", []):
            name = t.get("name", "")
            if q and q not in name.lower():
                continue
            clips = (t.get("attributes") or {}).get("contains_clips")
            excluded = self._track_excluded(name)
            if excluded:
                self.track_checked.discard(name)
            elif self._track_default_checked(t, name) and new_profile:
                self.track_checked.add(name)
            checked = name in self.track_checked
            sel_txt = "☑" if checked else "☐"
            clip_txt = (T("e_clips_yes") if clips is not False
                        else T("e_clips_no"))
            fmt_txt = self._fmt_cell_text(name)
            if excluded:
                self.src_tree.insert("", "end", iid=name, tags=("excluded",),
                                     values=(sel_txt,
                                             name + T("e_excluded_mark"),
                                             t.get("type", ""), clip_txt,
                                             fmt_txt))
            elif clips is False:
                self.src_tree.insert("", "end", iid=name, tags=("empty",),
                                     values=(sel_txt, name,
                                             t.get("type", ""), clip_txt,
                                             fmt_txt))
            else:
                self.src_tree.insert("", "end", iid=name,
                                     values=(sel_txt, name,
                                             t.get("type", ""), clip_txt,
                                             fmt_txt))
        try:
            self.src_tree.tag_configure("excluded", foreground="#999")
            self.src_tree.tag_configure("empty", foreground="#777")
        except tk.TclError:
            pass
        self._update_src_count()
        self._update_excluded_btn()

    # ---------------- 单轨声道 / 剔除空轨（v1.3.0 · Q5 Q7）----------------

    def _fmt_cell_text(self, name):
        """轨道列表「声道」列的显示文本（未单独指定 = 跟随全局）。"""
        v = self.track_fmt.get(name)
        return fmt_label(v) if v else T("e_fmt_follow")

    def _cycle_track_fmt(self, iid):
        """点击「声道」列 → 在 跟随全局 / 立体声 / 单声道 / 每声道独立 间循环。"""
        cur = self.track_fmt.get(iid, FORMAT_FOLLOW)
        try:
            nxt = TRACK_FMT_CYCLE[(TRACK_FMT_CYCLE.index(cur) + 1) % len(TRACK_FMT_CYCLE)]
        except ValueError:
            nxt = FORMAT_FOLLOW
        if nxt == FORMAT_FOLLOW:
            self.track_fmt.pop(iid, None)
        else:
            self.track_fmt[iid] = nxt
        vals = list(self.src_tree.item(iid)["values"])
        if len(vals) < 5:
            vals += [""] * (5 - len(vals))
        vals[4] = self._fmt_cell_text(iid)
        self.src_tree.item(iid, values=vals)
        self._invalidate_preview()

    def _empty_track_names(self):
        """档案里无音频块的轨道名（剔除空轨的候选名单）。"""
        if not self._profile:
            return []
        out = []
        for t in self._profile.get("tracks", []):
            clips = (t.get("attributes") or {}).get("contains_clips")
            if clips is None:
                clips = t.get("contains_clips")
            if clips is False:
                out.append(t.get("name", ""))
        return [x for x in out if x]

    def _dropped_names(self):
        """实际被剔除的（空轨 减去 用户加回的）。"""
        return [n for n in self._empty_track_names()
                if n not in self.track_restored]

    def _update_excluded_btn(self):
        n = len(self._dropped_names())
        if not getattr(self, "excluded_btn", None):
            return
        self.excluded_btn.configure(
            text=T("e_excluded_view") % n,
            state="normal" if n else "disabled")

    def _show_excluded(self):
        """查看被剔除的轨道 —— 逐条可「加回」（撤回）。"""
        names = self._dropped_names()
        if not names:
            return
        dlg = tk.Toplevel(self)
        dlg.title(T("e_excluded_title"))
        dlg.transient(self.winfo_toplevel())
        dlg.geometry("420x320")
        dlg.grab_set()
        ttk.Label(dlg, text=T("e_excluded_title"),
                  padding=(10, 8)).pack(fill="x")
        lst = tk.Listbox(dlg)
        lst.pack(fill="both", expand=True, padx=10)
        for n in names:
            lst.insert("end", n)

        def restore():
            sel = lst.curselection()
            if not sel:
                return
            name = lst.get(sel[0])
            self.track_restored.add(name)          # 豁免剔除（撤回）
            self.track_checked.add(name)           # 加回 = 重新勾选
            self._reload_sources()
            self.app.log(T("e_restored") % name)
            self._invalidate_preview()
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text=T("e_restore"),
                   command=restore).pack(side="left")
        ttk.Button(btns, text=T("e_close"),
                   command=dlg.destroy).pack(side="right")
        lst.bind("<Double-1>", lambda _e: restore())

    def _on_track_click(self, event):
        """点击行切换勾选（点在「选」列或行任意处均可；滚动条除外）。

        v1.3.0：点在**「声道」列**时改为循环切换该轨的格式（跟随全局 → 立体声
        → 单声道 → 每声道独立），而不是改勾选 —— 这是 Q5「每条轨道各选各的」。
        """
        region = self.src_tree.identify("region", event.x, event.y)
        if region not in ("cell", "tree"):
            return
        iid = self.src_tree.identify_row(event.y)
        if not iid:
            return
        col = self.src_tree.identify_column(event.x)
        if col == "#5":          # 第 5 列 = 声道
            self._cycle_track_fmt(iid)
            return
        if iid in self.track_checked:
            self.track_checked.discard(iid)
        else:
            self.track_checked.add(iid)
        vals = list(self.src_tree.item(iid)["values"])
        vals[0] = "☑" if iid in self.track_checked else "☐"
        self.src_tree.item(iid, values=vals)
        self._update_src_count()
        self._invalidate_preview()

    def _set_all_tracks(self, checked: bool):
        """全选 / 全不选（作用于当前列表所有行，含空轨与排除轨——
        全选是显式意图，覆盖默认规则）。"""
        for iid in self.src_tree.get_children():
            vals = list(self.src_tree.item(iid)["values"])
            vals[0] = "☑" if checked else "☐"
            self.src_tree.item(iid, values=vals)
        if checked:
            self.track_checked = set(self.src_tree.get_children())
        else:
            self.track_checked = set()
        self._update_src_count()
        self._invalidate_preview()

    def _update_src_count(self):
        self.src_count_var.set(T("e_selected") % len(self.track_checked))

    # ---------------- 模式联动与预览闸门 ----------------

    def _mode_on(self, m):
        return {"mix": self.mode_mix_var, "stem": self.mode_stem_var,
                "bus": self.mode_bus_var,
                "track": self.mode_track_var}[m].get() == "1"

    def _sync_mode_gating(self):
        """勾选联动（v1.2.0）：STEM 或「按轨道名称」任一勾选时轨道列表可交互
        （STEM 勾选轨 = 只导勾选的；全不勾 = 全轨模式）；
        未勾 STEM 时 aux 子项禁用。"""
        track_on = self.mode_track_var.get() == "1"
        stem_on = self.mode_stem_var.get() == "1"
        try:
            self.src_tree.state(["!disabled"] if (track_on or stem_on)
                                else ["disabled"])
            self.cb_stem_aux.state(["!disabled"] if stem_on else ["disabled"])
        except tk.TclError:
            pass

    def _on_param_changed(self):
        self._sync_mode_gating()
        self._invalidate_preview()

    def _invalidate_preview(self):
        """参数变化后使预览失效（执行按钮熄灭），需重新预览才能导出。"""
        if self.preview_ok and self._param_signature() != self._preview_signature:
            self.preview_ok = False
            self._preview_signature = ""
            self.refresh_buttons()

    # ---------------- 参数收集与校验 ----------------

    def _selected_sources(self):
        """勾选的轨道名（按档案顺序，不在列表中的勾选如跨档案残留则忽略）。

        v1.3.0（Q7）：勾选「剔除空轨道」时，空轨一律不进选中列表 ——
        **怎么选都不导出**（此前空轨只是"默认不勾"，用户一勾就又导了）。
        在「查看被剔除」里点「加回」的轨道会记进 `track_restored`，豁免剔除。
        """
        known = set(self.src_tree.get_children())
        picked = [n for n in self.track_checked if n in known]
        if self.exclude_empty_var.get() != "1":
            return picked
        empty = set(self._empty_track_names()) - self.track_restored
        return [n for n in picked if n not in empty]

    def _param_signature(self):
        return json.dumps({
            "profile": self._profile_path,
            "modes": [m for m in EXPORT_MODES if self._mode_on(m)],
            "stem_aux": self.stem_aux_var.get() == "1",
            "tracks": self._selected_sources(),
            "start": self.start_var.get(),
            "end": self.end_var.get(),
            "sr": self.sr_var.get(),
            "bd": self.bd_var.get(),
            "fmt": self.fmt_var.get(),
            "track_fmt": dict(self.track_fmt),
            "exclude_empty": self.exclude_empty_var.get(),
            "out": self.out_var.get(),
            "session": self.session_var.get()
                       if self.sess_mode_var.get() == "file" else "",
        }, ensure_ascii=False)

    def _resolve_out_dir(self):
        """输出目录（v1.2.0）：勾「输出按工程名建夹」时拼 <输出根>/<工程名>。"""
        base = self.out_var.get().strip()
        if self.by_session_var.get() == "1" and self._profile:
            name = ((self._profile.get("session") or {}).get("name") or "").strip()
            if name:
                base = os.path.join(base, name)
        return base

    def _build_cmds(self, dry_run):
        """构造 CLI 命令列表（--profile 必须在子命令前）。失败抛 ValueError。"""
        if not self._profile:
            raise ValueError(T("msg_no_profile"))
        sess = None
        if self.sess_mode_var.get() == "file":
            sess = self.session_var.get().strip()
            if not sess:
                raise ValueError(T("msg_sess_missing"))
        # v1.4.0：输出目录不存在就现建（出厂默认 PT-Tools-Backup/out 首次
        # 使用时还没有实体目录），别等 exporter 写文件时才失败。
        out_dir = self._resolve_out_dir()
        if out_dir:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as exc:
                raise ValueError(T("msg_out_missing") + "\n%s\n%s" % (out_dir, exc))
        stem_on = self.mode_stem_var.get() == "1"
        track_on = self.mode_track_var.get() == "1"
        picked = self._selected_sources()
        return build_export_cmds(
            self.app.resolver.venv_python,
            self.app.resolver.script("pt-exporter"),
            self._profile_path,
            self._profile,
            modes=[m for m in EXPORT_MODES if self._mode_on(m)],
            stem_aux=self.stem_aux_var.get() == "1",
            tracks=picked if track_on else [],
            # STEM 勾选式：列表里有勾选 → 只导勾选轨；全不勾 → 全轨模式
            stem_tracks=picked if (stem_on and picked) else [],
            exclude_names=self._exclude_pats,
            session=sess,
            out=out_dir,
            start=self.start_var.get().strip(),
            end=self.end_var.get().strip(),
            sample_rate=self.sr_var.get(),
            bit_depth=self.bd_var.get(),
            fmt=self.fmt_var.get(),
            dry_run=dry_run,
            # v1.3.0：每条轨道可覆盖全局格式（Q5）
            track_formats=dict(self.track_fmt),
            exclude_empty=self.exclude_empty_var.get() == "1",
        )

    # ---------------- 视频锁定时长（v1.2.0：自动检索 + 手动选择）----------------

    def _export_scripts_dir(self):
        return os.path.dirname(self.app.resolver.script("pt-exporter"))

    def _session_video_roots(self):
        """视频检索候选根（v1.3.0 · Q1）——按顺序试，第一个检出视频的即用。

        旧逻辑只查「.ptx 所在目录」向下 8 层，而实际工程里视频通常放在
        **.ptx 的父级**（如 `D:\\DAW-Project\\<项目>\\Video\\` 与 .ptx 目录并列），
        os.walk 只向下不向上，于是永远扫不到 —— 这就是"自动检测总是不对"的根因。
        现在候选链：.ptx 同级 → 父目录 → 祖父目录（去重，只保留真实存在的）。
        """
        p = ""
        if self.sess_mode_var.get() == "file" and self.session_var.get().strip():
            p = self.session_var.get().strip()
        elif self._profile:
            p = (self._profile.get("session") or {}).get("path") or ""
        if not p:
            return []
        out, seen = [], set()
        cur = os.path.dirname(os.path.abspath(p))
        for _ in range(3):
            if cur and cur not in seen and os.path.isdir(cur):
                out.append(cur)
                seen.add(cur)
            parent = os.path.dirname(cur)
            if not parent or parent == cur:
                break
            cur = parent
        return out

    def _session_video_root(self):
        roots = self._session_video_roots()
        return roots[0] if roots else ""

    def _session_fps(self):
        try:
            return float(str(self._profile["session"].get("timecode_rate")
                             or "25").split()[0])
        except (KeyError, TypeError, ValueError, AttributeError):
            return 25.0

    def _apply_video_duration(self, dur_sec, video_name):
        """end = 视频时长 + 余量（帧域换算），开始固定 00:00:00:00。"""
        fps = self._session_fps()
        try:
            margin = max(float(self.margin_var.get() or 0), 0)
        except ValueError:
            margin = 0
        tc = frame_to_tc(round((float(dur_sec) + margin) * fps), fps)
        self.start_var.set("00:00:00:00")
        self.end_var.set(tc)
        self.app.log(T("e_video_applied") % (video_name, tc, margin))

    def _autodetect_video(self):
        """工程目录树自动检索视频 → 1 条直接应用；多条弹窗选择；0 条提示。

        v1.3.0（Q1）：检索根改**候选链**（.ptx 同级 → 父级 → 祖父级），
        逐个试到检出为止，并把实际检索到的那个根写进日志，做到可核对。
        """
        if not self._profile:
            messagebox.showerror(T("msg_missing"), T("msg_no_profile"))
            return
        roots = self._session_video_roots()
        if not roots:
            self.app.log(T("e_video_none"))
            return
        script = os.path.join(self._export_scripts_dir(),
                              "find_session_videos.py")
        if not os.path.isfile(script):
            self.app.log(T("e_video_fail") % ("script missing: %s" % script))
            return
        self.app.log(T("e_video_root_note") + "：\n")
        for r in roots:
            self.app.log("    · %s\n" % r)
        threading.Thread(target=self._video_detect_worker, daemon=True,
                         args=(script, roots)).start()

    def _video_detect_worker(self, script, roots):
        """按候选根顺序检索，第一个检出视频的根即采用。"""
        for root in roots:
            try:
                p = subprocess.run(
                    [self.app.resolver.venv_python, script,
                     "--dir", root, "--profile", self._profile_path],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120,
                    creationflags=CREATE_NO_WINDOW)
                text = p.stdout or ""
            except Exception as exc:
                self.app.after(0, lambda e=str(exc): self.app.log(
                    T("b_search_fail") % e))
                return
            data = None
            try:
                start = text.index("{")
                data = json.loads(text[start:text.rindex("}") + 1])
            except (ValueError, json.JSONDecodeError):
                data = None
            if (data or {}).get("videos"):
                self.app.after(0, lambda d=data, r=root: self._video_detect_done(d, r))
                return
            self.app.after(0, lambda r=root: self.app.log(
                T("e_video_root_empty") % r))
        self.app.after(0, lambda: self._video_detect_done(None, ""))

    def _video_detect_done(self, data, root=""):
        videos = (data or {}).get("videos") or []
        if not videos:
            self.app.log(T("e_video_none"))
            return
        if root:
            self.app.log(T("e_video_root_hit") % root)
        if len(videos) == 1:
            v = videos[0]
            self.app.log(T("e_video_found1") % v.get("name", ""))
            self._apply_video_duration(v["duration_sec"], v.get("name", ""))
            return
        self.app.log(T("e_video_found_n") % len(videos))
        picked = self._video_choose_dialog(videos)
        if picked:
            self._apply_video_duration(picked["duration_sec"],
                                       picked.get("name", ""))

    def _video_choose_dialog(self, videos):
        """模态视频选择窗：清单（名称/时长/路径）→ 返回选中 dict 或 None。"""
        dlg = tk.Toplevel(self)
        dlg.title(T("e_video_pick_title"))
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.resizable(True, True)
        tree = ttk.Treeview(dlg, columns=("name", "dur", "path"),
                            show="headings", height=8)
        tree.heading("name", text=T("e_name_col"))
        tree.heading("dur", text=T("e_clips_col"))
        tree.heading("path", text="Path")
        tree.column("name", width=220)
        tree.column("dur", width=70, anchor="center", stretch=False)
        tree.column("path", width=380)
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        for i, v in enumerate(videos):
            tree.insert("", "end", iid=str(i), values=(
                v.get("name", ""), "%.1fs" % v.get("duration_sec", 0),
                v.get("path", "")))
        tree.selection_set("0")
        result = {"picked": None}

        def confirm(_e=None):
            sel = tree.selection()
            if sel:
                result["picked"] = videos[int(sel[0])]
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="OK", command=confirm).pack(side="right")
        ttk.Button(btns, text="Cancel",
                   command=dlg.destroy).pack(side="right", padx=6)
        tree.bind("<Double-1>", confirm)
        dlg.wait_window()
        return result["picked"]

    def _fill_from_video(self):
        """手动选视频文件 → video_duration.py 读时长 → 应用（含余量）。"""
        if not self._profile:
            messagebox.showerror(T("msg_missing"), T("msg_no_profile"))
            return
        path = filedialog.askopenfilename(
            title=T("e_video_title"),
            filetypes=[("Video", "*.mp4 *.mov *.m4v *.webm"), ("All", "*.*")])
        if not path:
            return
        script = os.path.join(self._export_scripts_dir(),
                              "video_duration.py")
        if not os.path.isfile(script):
            self.app.log(T("e_video_fail") % ("script missing: %s" % script))
            return
        self.app.log(T("e_video_running") % os.path.basename(path))
        threading.Thread(target=self._video_worker, daemon=True,
                         args=(script, path)).start()

    def _video_worker(self, script, video):
        """后台读视频时长（venv python 冷启动约 1~2 秒，不阻塞 UI）。"""
        try:
            p = subprocess.run(
                [self.app.resolver.venv_python, script, video,
                 "--profile", self._profile_path],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60,
                creationflags=CREATE_NO_WINDOW)
            text = (p.stdout or "") + (p.stderr or "")
        except Exception as exc:
            text = str(exc)
        tc = parse_video_duration_output(text)
        self.app.after(0, lambda: self._video_apply(tc, text, video))

    def _video_apply(self, tc, raw, video=""):
        if not tc:
            lines = [x for x in (raw or "").strip().splitlines() if x.strip()]
            self.app.log(T("e_video_fail") % (lines[-1] if lines else "?"))
            return
        # 人工模式同样叠加余量：tc → 帧 → +margin → 回时码
        try:
            margin = max(float(self.margin_var.get() or 0), 0)
        except ValueError:
            margin = 0
        fps = self._session_fps()
        tc = frame_to_tc(tc_to_frame(tc, fps) + int(round(margin * fps)), fps)
        self.start_var.set("00:00:00:00")
        self.end_var.set(tc)
        self.app.log(T("e_video_ok") % tc)

    # ---------------- 操作 ----------------

    def refresh_buttons(self):
        has_profile = self._profile is not None
        self.preview_btn.state(["disabled"] if
                               (self.busy or not has_profile) else ["!disabled"])
        can_export = (has_profile and self.preview_ok and self.app.ptsl_on
                      and not self.busy)
        self.export_btn.state(["disabled"] if not can_export else ["!disabled"])

    def do_preview(self):
        try:
            cmds = self._build_cmds(dry_run=True)
        except ValueError as exc:
            messagebox.showerror(T("msg_invalid"), str(exc))
            return
        self.busy = True
        self.refresh_buttons()
        self.preview_ok = False
        self._preview_signature = ""
        self.app.log(T("preview_start"))
        self.app.start_worker(cmds)

    def do_export(self):
        if not self.preview_ok:
            messagebox.showwarning(T("msg_preview_first_title"),
                                   T("msg_preview_first_body"))
            return
        try:
            cmds = self._build_cmds(dry_run=False)
        except ValueError as exc:
            messagebox.showerror(T("msg_invalid"), str(exc))
            return
        if not self.app.ptsl_on:
            messagebox.showerror(T("msg_invalid"), T("msg_ptsl_off_export"))
            return
        if not messagebox.askyesno(T("msg_confirm_title"), T("msg_confirm_body")):
            return
        self.busy = True
        self.refresh_buttons()
        self.app.start_worker(cmds)

    def on_worker_done(self, returncode):
        if not self.busy:
            return
        self.busy = False
        if returncode == 0:
            if self._preview_signature == "":
                self.preview_ok = True
                self._preview_signature = self._param_signature()
                self.app.log(T("preview_pass"))
            else:
                self.preview_ok = False
                self._preview_signature = ""
        self.refresh_buttons()

    # ---------------- 小工具 ----------------

    def _browse_out(self):
        chosen = filedialog.askdirectory(
            title=T("choose_outdir_title"),
            initialdir=self.out_var.get() or None)
        if chosen:
            self.out_var.set(chosen)
            self.app.cfg["last_out_dir"] = chosen
            save_config(self.app.cfg)

    def _browse_session(self):
        # v1.4.0：浏览框默认开在「当前工程 .ptx 的父级目录」——
        # 优先取框里已填路径的目录，其次取档案里记录的 session.path（PT
        # 当前打开的工程）所在目录，都不存在才走系统默认。
        initial = ""
        cur = self.session_var.get().strip()
        if cur:
            initial = os.path.dirname(cur)
        else:
            sp = ((self._profile or {}).get("session") or {}).get("path") or ""
            if sp:
                initial = os.path.dirname(sp)
        chosen = filedialog.askopenfilename(
            title=T("choose_ptx_title"),
            filetypes=[("Pro Tools Session", "*.ptx"), ("All", "*.*")],
            initialdir=initial or None)
        if chosen:
            self.session_var.set(chosen)

    def _on_sess_mode_change(self):
        """v1.4.0：切到「指定文件」模式时预填当前工程的 .ptx 路径。

        档案里的 session.path 就是扫描时 PT 打开的工程；预填后用户看到
        的是完整默认值，要换工程点浏览（默认开在其父级）即可。"""
        if self.sess_mode_var.get() == "file" and not self.session_var.get().strip():
            sp = ((self._profile or {}).get("session") or {}).get("path") or ""
            if sp:
                self.session_var.set(sp)

    # ---------------- 输出目录锁定 / 落盘预览（v1.3.0 · Q3 Q6）----------------

    def _toggle_out_lock(self):
        """输出目录锁定：锁定后禁止改动，防止换工程时误导出到上一个目录。"""
        self.out_locked = not self.out_locked
        st = "disabled" if self.out_locked else "normal"
        self.out_entry.configure(state=st)
        self.out_browse_btn.configure(state=st)
        self.out_lock_btn.configure(
            text=T("e_locked") if self.out_locked else T("e_lock"))

    def _preview_out_paths(self):
        """只读预览：本次导出会落到哪个目录、哪些文件（不写盘、不改任何状态）。"""
        out = self.out_var.get().strip()
        if not out:
            messagebox.showerror(T("msg_invalid"), T("msg_out_missing"))
            return
        sess_name = ((self._profile or {}).get("session") or {}).get("name", "")
        root = os.path.join(out, sess_name) if (
            self.by_session_var.get() == "1" and sess_name) else out

        srcs = (self._profile or {}).get("sources", {})
        empty = set(self._empty_track_names())
        picked = [i for i in self.src_tree.get_children()
                  if i in self.track_checked]
        if self.exclude_empty_var.get() == "1":
            picked = [p for p in picked if p not in empty]

        lines = [root, ""]
        n = 0
        if self._mode_on("mix"):
            for name in (srcs.get("output") or []):
                lines.append("  MIX   %s" % name)
                n += 1
        if self._mode_on("bus"):
            for name in (srcs.get("bus") or []):
                lines.append("  BUS   %s" % name)
                n += 1
        if self._mode_on("stem") or self._mode_on("track"):
            for name in picked:
                lines.append("  STEM  %s   （声道：%s）"
                             % (name, self._fmt_cell_text(name)))
                n += 1
        if n == 0:
            lines.append(T("e_out_preview_none"))
        lines += ["", T("e_out_preview_total") % n]
        if empty and self.exclude_empty_var.get() == "1":
            lines.append(T("e_out_preview_dropped") % len(empty))

        dlg = tk.Toplevel(self)
        dlg.title(T("e_out_preview_title"))
        dlg.transient(self.winfo_toplevel())
        dlg.geometry("640x380")
        txt = tk.Text(dlg, wrap="none", font=("Consolas", 10))
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Button(dlg, text=T("e_close"),
                   command=dlg.destroy).pack(pady=(0, 10))

    # ---------------- 批量导出（v1.2.0）----------------

    def open_batch_dialog(self):
        if not self.app.ptsl_on:
            messagebox.showerror(T("msg_invalid"), T("b_need_ptsl"))
            return
        if not self._profile:
            messagebox.showerror(T("msg_missing"), T("msg_no_profile"))
            return
        BatchExportDialog(self)


class BatchExportDialog(tk.Toplevel):
    """多工程批量导出：前置检索视频（开 PT 前就选定），生成 jobs.json 交给
    pt_batch_export.py 编排执行（open/close 守卫、逐工程扫描、产物核对都
    在脚本侧，壳不动芯）。轨道规则沿用导出页当前设置。"""

    def __init__(self, tab: "ExportTab"):
        super().__init__(tab)
        self.tab = tab
        self.title(T("b_title"))
        self.transient(tab.winfo_toplevel())
        self.geometry("860x560")
        self.rows: dict = {}          # ptx -> {"videos": [...], "picked": None}

        # -- 工程列表
        box = ttk.LabelFrame(self, text="  " + T("b_ptx_frame") + "  ", padding=6)
        box.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        btns = ttk.Frame(box)
        btns.pack(fill="x")
        ttk.Button(btns, text=T("b_add"), command=self._add_sessions).pack(side="left")
        ttk.Button(btns, text=T("b_remove"), command=self._remove_selected).pack(
            side="left", padx=6)
        ttk.Button(btns, text=T("b_rescan"), command=self._rescan_all).pack(side="left")
        self.tree = ttk.Treeview(box, columns=("session", "video", "status"),
                                 show="headings", height=10)
        self.tree.heading("session", text=T("b_col_session"))
        self.tree.heading("video", text=T("b_col_video"))
        self.tree.heading("status", text=T("b_col_status"))
        self.tree.column("session", width=330)
        self.tree.column("video", width=260)
        self.tree.column("status", width=160, anchor="center")
        self.tree.pack(fill="both", expand=True, pady=(4, 0))
        self.tree.bind("<Double-1>", self._on_double)

        # -- 策略
        pol = ttk.LabelFrame(self, text="  " + T("b_policy_frame") + " / "
                             + T("b_multi_frame") + "  ", padding=6)
        pol.pack(fill="x", padx=10, pady=4)
        ttk.Label(pol, text=T("b_policy_frame") + ":").pack(side="left")
        self.no_video_var = tk.StringVar(value="fallback")
        ttk.Radiobutton(pol, text=T("b_policy_fallback"), value="fallback",
                        variable=self.no_video_var).pack(side="left", padx=(4, 14))
        ttk.Radiobutton(pol, text=T("b_policy_skip"), value="skip",
                        variable=self.no_video_var).pack(side="left")
        ttk.Label(pol, text="    |    " + T("b_multi_frame") + ":").pack(side="left")
        self.multi_var = tk.StringVar(value="skip")
        ttk.Radiobutton(pol, text=T("b_multi_pick"), value="pick",
                        variable=self.multi_var).pack(side="left", padx=(4, 14))
        ttk.Radiobutton(pol, text=T("b_multi_skip"), value="skip",
                        variable=self.multi_var).pack(side="left")

        ttk.Label(self, text=T("b_rule_note"), foreground="#888",
                  wraplength=820, justify="left").pack(
            fill="x", padx=12, pady=(2, 0))

        # -- 开始
        start_row = ttk.Frame(self)
        start_row.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Button(start_row, text=T("b_start"), command=self._start).pack(side="right")

    # ---- 行管理 ----

    def _add_sessions(self):
        files = filedialog.askopenfilenames(
            title=T("choose_ptx_title"),
            filetypes=[("Pro Tools Session", "*.ptx"), ("All", "*.*")])
        for f in files:
            if f in self.rows:
                continue
            self.rows[f] = {"videos": [], "picked": None}
            self.tree.insert("", "end", iid=f, values=(
                os.path.basename(f), T("b_video_none"), "…"))
            self._search_one(f)
        if files:
            self.tree.selection_set(files[0])

    def _remove_selected(self):
        for iid in self.tree.selection():
            self.rows.pop(iid, None)
            self.tree.delete(iid)

    def _rescan_all(self):
        for f in list(self.rows):
            self._search_one(f)

    def _on_double(self, _e):
        iid = self.tree.identify_row(_e.y)
        if iid and (self.rows.get(iid, {}).get("videos")):
            self._pick_video(iid)

    @staticmethod
    def _video_roots_for(ptx):
        """候选检索根（与导出页同源）：.ptx 同级 → 父级 → 祖父级。"""
        out, seen = [], set()
        cur = os.path.dirname(os.path.abspath(ptx))
        for _ in range(3):
            if cur and cur not in seen and os.path.isdir(cur):
                out.append(cur)
                seen.add(cur)
            parent = os.path.dirname(cur)
            if not parent or parent == cur:
                break
            cur = parent
        return out

    def _search_one(self, ptx):
        """后台检索一个工程的视频（不开 PT，纯文件系统）。"""
        roots = self._video_roots_for(ptx)
        script = os.path.join(self.tab._export_scripts_dir(),
                              "find_session_videos.py")
        if not os.path.isfile(script):
            self._set_row(ptx, video=T("b_video_none"), status=T("b_search_fail") % "script missing")
            return
        self.tab.app.log(T("b_searching") % os.path.basename(ptx))
        threading.Thread(target=self._search_worker, daemon=True,
                         args=(ptx, script, roots)).start()

    def _search_worker(self, ptx, script, roots):
        """按候选根顺序检索，第一个检出视频的即用（v1.3.0 · Q1）。"""
        if not roots:
            self.after(0, lambda: self._search_done(ptx, None, "no search root"))
            return
        text = ""
        for root in roots:
            try:
                p = subprocess.run(
                    # 只给 --dir（脚本里显式 --dir 优先；同时给 --session 会被
                    # 抢回 .ptx 同级目录，父级候选就永远走不到）
                    [self.tab.app.resolver.venv_python, script,
                     "--dir", root,
                     "--profile", self.tab._profile_path],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120,
                    creationflags=CREATE_NO_WINDOW)
                text = p.stdout or ""
            except Exception as exc:
                self.after(0, lambda e=str(exc): self._search_done(ptx, None, e))
                return
            data = None
            try:
                start = text.index("{")
                data = json.loads(text[start:text.rindex("}") + 1])
            except (ValueError, json.JSONDecodeError):
                data = None
            if (data or {}).get("videos"):
                self.after(0, lambda d=data: self._search_done(ptx, d, ""))
                return
        self.after(0, lambda: self._search_done(ptx, None, text[-200:]))

    def _search_done(self, ptx, data, raw):
        row = self.rows.get(ptx)
        if row is None:
            return  # 行已被移除
        videos = (data or {}).get("videos") or []
        row["videos"] = videos
        row["picked"] = None
        if not videos:
            self._set_row(ptx, video=T("b_video_none"),
                          status=(T("b_policy_fallback")
                                  if self.no_video_var.get() == "fallback"
                                  else T("b_policy_skip")))
        elif len(videos) == 1:
            row["picked"] = videos[0]
            self._set_row(ptx, video=T("b_video_ok") % (
                videos[0].get("name", ""), videos[0].get("duration_sec", 0)),
                status="OK")
        else:
            n = len(videos)
            self._set_row(ptx, video=T("b_video_multi") % n,
                          status=(T("b_multi_pick") + " / " + T("b_video_pick")
                                  if self.multi_var.get() == "pick"
                                  else T("b_multi_skip")))
        self._invalidate_parent_preview()

    def _set_row(self, ptx, video=None, status=None):
        if not self.tree.exists(ptx):
            return
        vals = list(self.tree.item(ptx)["values"])
        if video is not None:
            vals[1] = video
        if status is not None:
            vals[2] = status
        self.tree.item(ptx, values=vals)

    def _pick_video(self, ptx):
        videos = self.rows.get(ptx, {}).get("videos") or []
        picked = self.tab._video_choose_dialog(videos)
        if not picked:
            return
        self.rows[ptx]["picked"] = picked
        self._set_row(ptx, video=T("b_video_ok") % (
            picked.get("name", ""), picked.get("duration_sec", 0)), status="OK")

    def _invalidate_parent_preview(self):
        try:
            self.tab._invalidate_preview()
        except Exception:
            pass

    # ---- 生成 jobs 并启动 ----

    def _start(self):
        if not self.rows:
            messagebox.showwarning(T("msg_invalid"), T("b_need_ptx"))
            return
        tab = self.tab
        try:
            margin = max(float(tab.margin_var.get() or 0), 0)
        except ValueError:
            margin = 0
        fallback = float(DEFAULT_FALLBACK_DURATION)
        try:
            fallback = max(float(tab.fallback_var.get() or DEFAULT_FALLBACK_DURATION), 1)
        except ValueError:
            pass
        exclude = list(tab._exclude_pats)
        stem_on = tab.mode_stem_var.get() == "1"
        track_on = tab.mode_track_var.get() == "1"
        picked_tracks = tab._selected_sources()
        stem_aux = tab.stem_aux_var.get() == "1"

        exports = []
        modes = [m for m in EXPORT_MODES if tab._mode_on(m)]
        if not modes:
            messagebox.showwarning(T("msg_invalid"), T("msg_no_mode"))
            return
        srcs = (tab._profile or {}).get("sources", {})
        for m in modes:
            if m == "mix":
                exports.append({"kind": "output",
                                "sources": srcs.get("output") or []})
            elif m == "bus":
                exports.append({"kind": "bus",
                                "sources": srcs.get("bus") or []})
            elif m == "stem":
                if picked_tracks:
                    exports.append({"kind": "track", "sources": picked_tracks})
                else:
                    exp = {"kind": "track-all", "exclude_empty": True,
                           "exclude_names": exclude}
                    if stem_aux:
                        exp["track_types"] = ["audio", "aux", "instrument", "midi"]
                    else:
                        exp["skip_buses"] = True
                    exports.append(exp)
            elif m == "track":
                if not picked_tracks:
                    messagebox.showwarning(T("msg_invalid"), T("msg_no_track_sel"))
                    return
                exports.append({"kind": "track", "sources": picked_tracks})
        if any((e.get("kind") in ("output", "bus")) and not e.get("sources")
               for e in exports):
            messagebox.showwarning(T("msg_invalid"),
                                   T("msg_no_output_src") if "output" in
                                   [e.get("kind") for e in exports if not e.get("sources")]
                                   else T("msg_no_bus_src"))
            return

        jobs = []
        self._fallback_used = False
        for i, (ptx, info) in enumerate(self.rows.items(), 1):
            job = {"id": str(i), "ptx": ptx, "session_name_expect": "",
                   "exports": exports}
            picked = info.get("picked")
            videos = info.get("videos") or []
            if picked:
                job["duration_sec"] = round(
                    float(picked.get("duration_sec", 0)) + margin, 3)
            elif videos:
                # 多视频且未选 → 用户策略：跳过记录（清单进汇总）
                job["_videos"] = videos
                job["skip_on_no_duration"] = True
            else:
                if self.no_video_var.get() == "fallback":
                    job["duration_sec"] = fallback
                    self._fallback_used = True
                else:
                    job["_videos"] = []
                    job["skip_on_no_duration"] = True
            jobs.append(job)

        out_root = tab.out_var.get().strip()
        if not out_root:
            messagebox.showwarning(T("msg_invalid"), T("msg_out_missing"))
            return
        spec = {
            "defaults": {
                "sample_rate": tab.sr_var.get(),
                "bit_depth": tab.bd_var.get(),
                # v1.3.0：UI 里存的是显示名，写进 jobs.json 必须是内部 key
                "format": fmt_key_of(tab.fmt_var.get()) or DEFAULT_EXPORT_FORMAT,
                "fps": tab._session_fps(),
                "save_on_close": True,
            },
            "paths": {
                "venv_python": tab.app.resolver.venv_python,
                "scan_script": tab.app.resolver.script("pt-scanner"),
                "export_script": tab.app.resolver.script("pt-exporter"),
                "profile_dir": os.path.join(tempfile.gettempdir(),
                                            "pt_tools_batch_profiles"),
                "out_root": out_root,
            },
            "jobs": jobs,
        }
        os.makedirs(spec["paths"]["profile_dir"], exist_ok=True)
        tmp = tempfile.mkdtemp(prefix="pt_batch_jobs_")
        jobs_path = os.path.join(tmp, "jobs.json")
        with open(jobs_path, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=2)
        batch_script = os.path.join(tab._export_scripts_dir(),
                                    "pt_batch_export.py")
        cmd = [tab.app.resolver.venv_python, batch_script, "--jobs", jobs_path]
        tab.app.log(T("b_generating") % jobs_path)
        tab.app.log(T("b_started") % len(jobs))
        if getattr(self, "_fallback_used", False):
            # 兜底是"猜"的，必须显式告警（旧默认值 240s 会悄悄截断长片）
            tab.app.log(T("e_fallback_warn") % int(fallback))
        tab.app.start_worker([cmd])
        self.destroy()


# ---------------------------------------------------------------------------
# Tab 3 · 清理（骨架置灰：需 PT 2025.10+）
# ---------------------------------------------------------------------------

class CleanTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app

        warn = ttk.Frame(self, style="Danger.TFrame")
        warn.pack(fill="x", pady=(0, 8))
        ttk.Label(
            warn,
            text=T("c_warn"),
            foreground="#fff", background="#b00").pack(padx=8, pady=6)

        info = ttk.LabelFrame(self, text="  " + T("c_cap") + "  ", padding=6)
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, text=T("c_cap1")).pack(anchor="w")
        ttk.Label(info, text=T("c_cap2")).pack(anchor="w", pady=(2, 0))
        ttk.Label(info, text=T("c_cap3")).pack(anchor="w", pady=(2, 0))

        form = ttk.LabelFrame(self, text="  " + T("c_params") + "  ", padding=6)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text=T("c_track_mode")).grid(row=0, column=0, sticky="w")
        self.track_tree = ttk.Treeview(form, columns=("name",), show="headings",
                                       height=6)
        self.track_tree.heading("name", text=T("c_track_col"))
        self.track_tree.column("name", width=420)
        self.track_tree.grid(row=1, column=0, columnspan=2, sticky="we", pady=4)
        ttk.Label(form, text=T("c_target_out")).grid(row=2, column=0, sticky="w")
        ttk.Label(form, text=T("c_backup")).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.track_tree.state(["disabled"])
        ttk.Label(form, text=T("c_note"),
                  foreground="#888").grid(row=4, column=0, sticky="w", pady=(12, 0))

    def on_profile_loaded(self, data):
        n = len(data.get("tracks", []))
        self.track_tree.delete(*self.track_tree.get_children())
        for t in data.get("tracks", [])[:200]:
            self.track_tree.insert("", "end", iid=t.get("name", ""),
                                   values=(t.get("name", ""),))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    app = App()
    _ok, _msg = app.resolver.status()
    if not _ok:
        messagebox.showwarning(T("skills_broken_title"),
                               _msg + "\n\n" + T("skills_broken_hint"))
        app.log("[warn] " + _msg + "\n")
    app.mainloop()
