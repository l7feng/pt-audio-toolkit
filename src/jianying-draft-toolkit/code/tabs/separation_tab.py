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
        self.build()
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
        """检测 demucs 命令是否可用。"""
        # 优先用 pt-build-env 的 python（开发/打包环境）
        candidates = [
            r"D:\My-Temporary\pt-build-env\Scripts\python.exe",
            sys.executable,
        ]
        found = None
        for py in candidates:
            if not Path(py).is_file():
                continue
            try:
                r = subprocess.run(
                    [py, "-c", "import demucs; print(demucs.__version__)"],
                    capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    found = py
                    ver = r.stdout.strip()
                    self.demucs_ok = True
                    self.demucs_py = py
                    self.env_label.configure(
                        text=f"✓ Demucs {ver} 就绪", foreground="#4a4")
                    self.btn_run.configure(state="normal")
                    return
            except Exception:
                continue
        self.demucs_ok = False
        self.demucs_py = None
        self.env_label.configure(
            text="✗ Demucs 未安装——请运行 pip install demucs",
            foreground="#c44")
        self.btn_run.configure(state="disabled")

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
            cmd = [self.demucs_py, "-m", "demucs", "-o", out]
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
