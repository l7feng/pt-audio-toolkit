#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人声分离页签（J11）—— 调 Demucs 命令行模型，把 WAV 拆成人声/伴奏。

设计要点：
- Demucs 不打进 exe（torch ~2.5GB），运行时检测；
- 不可用时按钮置灰并提示「请先安装人声分离模型」；
- 最小版只做两轨分离（vocals / instrumental），后续可扩四轨。
"""

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import tkinter as tk
from tkinter import ttk

from .base import BaseTab, ScrollableFrame


class SeparationTab(BaseTab):
    title = "④ 人声分离"
    config_keys = (
        "sep_input", "sep_output", "sep_stems",
    )

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.demucs_ok = False
        self.demucs_py = None
        self.demucs_cmd = None          # 实际执行命令（[python, -m, demucs] 或 [demucs.exe]）
        self.build()
        # ⚠️ 必须在后台线程检测：import demucs 会拉起 torch（GB 级），
        # 同步检测会阻塞 GUI 主线程 → mainloop 迟迟不跑 → 窗口不弹出。
        self._check_demucs()

    # ───────────── 界面 ─────────────

    def build(self):
        outer = ScrollableFrame(self)
        outer.pack(fill="both", expand=True)
        wrap = outer.inner

        # 环境状态
        env_box = ttk.LabelFrame(wrap, text="模型环境", padding=6)
        env_box.pack(fill="x", padx=8, pady=4)
        self.env_label = ttk.Label(env_box, text="检测中…", foreground="#888")
        self.env_label.pack(side="left", padx=4)
        ttk.Button(env_box, text="重新检测", command=self._check_demucs).pack(
            side="left", padx=4)

        # 输入
        in_box = ttk.LabelFrame(wrap, text="输入音频", padding=6)
        in_box.pack(fill="x", padx=8, pady=4)
        self.var_in = tk.StringVar()
        self.path_row(in_box, 0, "文件/目录:", self.var_in, self._pick_in,
                      hint="WAV/MP3/M4A，或整个文件夹")
        ttk.Label(in_box, text="拖拽文件到此处也可", foreground="#aaa").grid(
            row=1, column=1, sticky="w", padx=4)

        # 输出
        out_box = ttk.LabelFrame(wrap, text="输出目录", padding=6)
        out_box.pack(fill="x", padx=8, pady=4)
        self.var_out = tk.StringVar()
        self.path_row(out_box, 0, "输出到:", self.var_out, self._pick_out)

        # 选项
        opt_box = ttk.LabelFrame(wrap, text="分离选项", padding=6)
        opt_box.pack(fill="x", padx=8, pady=4)
        ttk.Label(opt_box, text="分离模式:").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.var_stems = tk.StringVar(value="vocals")
        ttk.Radiobutton(opt_box, text="人声 / 伴奏（两轨，推荐）",
                        variable=self.var_stems, value="vocals").grid(
            row=0, column=1, sticky="w", padx=4)
        ttk.Radiobutton(opt_box, text="四轨（人声/鼓/贝斯/其他）",
                        variable=self.var_stems, value="all").grid(
            row=1, column=1, sticky="w", padx=4)

        # 按钮行
        btn_box = ttk.Frame(wrap)
        btn_box.pack(fill="x", padx=8, pady=6)
        self.btn_run = ttk.Button(btn_box, text="开始分离", command=self._on_run)
        self.btn_run.pack(side="left", padx=4)
        ttk.Button(btn_box, text="打开输出目录",
                   command=lambda: self.open_in_explorer(self.var_out.get())).pack(
            side="left", padx=4)

        # 日志
        self.make_log(wrap, height=12)

    # ───────────── 路径选择 ─────────────

    def _pick_in(self):
        p = self.ask_file("选择音频文件", filetypes=[
            ("音频", "*.wav *.mp3 *.m4a *.flac"), ("全部", "*.*")])
        if p:
            self.var_in.set(p)

    def _pick_out(self):
        p = self.ask_dir("选择输出目录", self.var_out.get())
        if p:
            self.var_out.set(p)

    # ───────────── demucs 检测 ─────────────

    def _check_demucs(self):
        """后台线程检测 demucs 是否可用，避免阻塞 GUI 启动。

        检测策略（轻量、不拉起 torch、不重新启动本程序）：
          ① PATH 上的 ``demucs`` 命令（console_scripts 入口，最优先）；
          ② 非冻结环境下，用当前 python ``-m demucs`` 探一下（仅开发/源码模式）。
             冻结（--windowed exe）下**绝不**用 ``sys.executable`` 去 ``import demucs``——
             那等于把整个 GUI 程序当子进程重跑一遍，会卡死启动。
        结果回主线程刷新标签与按钮。
        """
        def job():
            found_py = None
            found_cmd = None
            ver = ""
            # ① PATH 上的 demucs 命令
            exe = shutil.which("demucs")
            if exe:
                found_py = exe
                found_cmd = [exe]
            # ② 非冻结环境：当前 python 能否 import demucs（不拉 torch 进 GUI 进程检测太重，
            #    但源码模式用户本地常装了 demucs，给一条兜底）
            if found_cmd is None and not getattr(sys, "frozen", False):
                try:
                    r = subprocess.run(
                        [sys.executable, "-c",
                         "import demucs; print(getattr(demucs, '__version__', ''))"],
                        capture_output=True, text=True, timeout=20)
                    if r.returncode == 0:
                        found_py = sys.executable
                        found_cmd = [sys.executable, "-m", "demucs"]
                        ver = (r.stdout or "").strip()
                except Exception:
                    pass

            def apply():
                if found_cmd:
                    self.demucs_ok = True
                    self.demucs_py = found_py
                    self.demucs_cmd = found_cmd
                    text = "✓ Demucs 就绪" + (f" {ver}" if ver else "")
                    self.env_label.configure(text=text, foreground="#4a4")
                    self.btn_run.configure(state="normal")
                else:
                    self.demucs_ok = False
                    self.demucs_py = None
                    self.demucs_cmd = None
                    self.env_label.configure(
                        text="✗ Demucs 未安装——请运行 pip install demucs",
                        foreground="#c44")
                    self.btn_run.configure(state="disabled")
            try:
                self.app.root.after(0, apply)
            except Exception:
                pass

        threading.Thread(target=job, daemon=True).start()

    # ───────────── 执行 ─────────────

    def collect(self):
        self.cfg["sep_input"] = self.var_in.get()
        self.cfg["sep_output"] = self.var_out.get()
        self.cfg["sep_stems"] = self.var_stems.get()

    def apply_config(self):
        self.var_in.set(self.cfg.get("sep_input", ""))
        self.var_out.set(self.cfg.get("sep_output", ""))
        self.var_stems.set(self.cfg.get("sep_stems", "vocals"))

    def _on_run(self):
        if not self.demucs_ok:
            messagebox.showwarning(
                "模型未安装",
                "人声分离模型（Demucs）未安装。\n\n"
                "请在命令行运行：\n"
                "pip install demucs\n\n"
                "安装完成后点「重新检测」。")
            return
        inp = self.var_in.get().strip()
        out = self.var_out.get().strip()
        if not inp or not Path(inp).exists():
            messagebox.showwarning("缺输入", "请选择要分离的音频文件或目录。")
            return
        if not out:
            out = str(Path(inp).parent / "separated")
            self.var_out.set(out)
        Path(out).mkdir(parents=True, exist_ok=True)
        self.save_config(quiet=True)
        self.run_async(self._run_demucs, btn=self.btn_run, busy_text="分离中…")

    def _run_demucs(self):
        inp = self.var_in.get().strip()
        out = self.var_out.get().strip()
        stems = self.var_stems.get()

        # 收集要处理的文件
        if Path(inp).is_dir():
            files = [str(p) for p in Path(inp).iterdir()
                     if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".flac")]
        else:
            files = [inp]

        if not files:
            print("[错误] 没找到音频文件")
            return

        print(f"[信息] 共 {len(files)} 个文件，输出到 {out}")
        two_stems = "--two-stems=vocals" if stems == "vocals" else ""

        for i, f in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}] {Path(f).name}")
            cmd = list(self.demucs_cmd) + ["-o", out]
            if two_stems:
                cmd.append(two_stems)
            cmd.append(f)
            print("  $ " + " ".join(cmd))
            r = subprocess.run(cmd, capture_output=False, text=True)
            if r.returncode != 0:
                print(f"  [失败] 返回码 {r.returncode}")
            else:
                print("  [完成]")

        print(f"\n[全部完成] 产物在: {out}")
