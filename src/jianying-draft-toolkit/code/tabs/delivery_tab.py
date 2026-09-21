#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""③ 生成交付包页 —— 把 json 路径相对化 + 音频随包，产出能直接发给剪辑的文件夹。

为什么单独一页：这一步只做**数据**（json + audio/）。
`导入工具.exe` 与使用说明是**一次性固定资产**，做好就长期复用，
不参与日常打包 —— 你只需把生成好的包连同那两样一起发出去即可。
"""

import json
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import main as core
from .base import BaseTab


class DeliveryTab(BaseTab):
    title = "③ 生成交付包"
    config_keys = ("import_pkg_out",)

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.build()

    # ───────────── 界面 ─────────────

    def build(self):
        outer = self

        ttk.Label(outer,
                  text=("把 PT 解析结果打包成「解压即用」的交付包：json 里的路径改成相对路径，"
                        "音频随包复制并预合成 L/R 立体声。\n"
                        "剪辑拿到后不需要 Pro Tools、不需要任何原始工程路径。"),
                  foreground="#666", justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        box = ttk.LabelFrame(outer, text="打包设置", padding=8)
        box.pack(fill="x", padx=8, pady=(0, 6))

        # 源 json
        self.var_json = tk.StringVar(value=self.cfg.get("import_json", ""))
        ttk.Label(box, text="源 json").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(box, textvariable=self.var_json, width=52).grid(
            row=0, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(box, text="浏览…", command=self._pick_json).grid(row=0, column=2, padx=4)
        self.lbl_src = ttk.Label(box, text="", foreground="#888")
        self.lbl_src.grid(row=0, column=3, sticky="w", padx=8)

        # 输出目录
        self.var_out = tk.StringVar(value=self.cfg.get("import_pkg_out", ""))
        ttk.Label(box, text="包输出目录").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(box, textvariable=self.var_out, width=52).grid(
            row=1, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(box, text="浏览…", command=self._pick_out).grid(row=1, column=2, padx=4)
        ttk.Label(box, text="会在此目录下新建 <工程名>-导入包/", foreground="#888").grid(
            row=1, column=3, sticky="w", padx=8)

        # 排除
        opt = ttk.Frame(box)
        opt.grid(row=2, column=0, columnspan=4, sticky="we", padx=4, pady=3)
        ttk.Label(opt, text="排除轨道关键词").pack(side="left")
        self.var_exclude = tk.StringVar(value=self.cfg.get("import_exclude", ""))
        ttk.Entry(opt, textvariable=self.var_exclude, width=32).pack(side="left", padx=6)
        ttk.Label(opt, text="（与导入页一致；留空 = 默认排除辅助轨）",
                  foreground="#888").pack(side="left")
        box.columnconfigure(1, weight=1)

        # 打包内容说明
        content = ttk.LabelFrame(outer, text="包内结构", padding=8)
        content.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(content, text=(
            "<工程名>-导入包/\n"
            "├── <工程名>.pt-clips.json    ← 结构数据（路径已相对化）\n"
            "├── audio/                     ← 音频素材（含预合成的 *.stereo.wav）\n"
            "├── 导入工具.exe               ← 固定资产，本页不生成\n"
            "└── 01-使用说明.txt            ← 固定资产，本页不生成"
        ), justify="left", font=("Consolas", 9)).pack(anchor="w")
        ttk.Label(content,
                  text=("导入工具.exe 与 01-使用说明.txt 是**一次性做好长期复用**的两样东西，"
                        "本页只负责生成 json + audio/。\n"
                        "生成完把整个文件夹压缩发给剪辑即可 —— 无需每次重新打包。"),
                  foreground="#666", justify="left", wraplength=760).pack(
            anchor="w", pady=(6, 0))

        # 按钮
        btn_box = ttk.Frame(outer)
        btn_box.pack(fill="x", padx=8, pady=(0, 4))
        self.btn_dry = ttk.Button(btn_box, text="预演（只列素材不复制）", command=self.dry_run)
        self.btn_dry.pack(side="left", padx=4)
        ttk.Button(btn_box, text="打开输出目录",
                   command=lambda: self.open_in_explorer(
                       self.var_out.get().strip() or str(core.APP_DIR))).pack(side="left", padx=4)
        self.btn_run = ttk.Button(btn_box, text="生成交付包", command=self.build_pkg)
        self.btn_run.pack(side="right", padx=4)
        self.btn_run.configure(style="Accent.TButton")

        self.make_log(outer, height=12,
                      tip=("用法：① 选源 json（PT 解析结果）‣ ② 选包输出目录 ‣ ③ 点生成。\n"
                           "完成后把生成的 <工程名>-导入包 整个文件夹压缩发给剪辑。\n\n"))

    def collect(self):
        self.cfg["import_pkg_out"] = self.var_out.get().strip()
        # 与导入页共用「源 json」，此处同步回去，方便两页接力
        self.cfg["import_json"] = self.var_json.get().strip()

    def apply_config(self):
        """把 self.cfg 的值刷回控件（菜单「重新载入配置」「默认路径」后调用）。"""
        c = self.cfg
        self.var_json.set(c.get("import_json", ""))
        self.var_out.set(c.get("import_pkg_out", ""))
        self.var_exclude.set(c.get("import_exclude", ""))
        self._refresh_src()

    def on_show(self):
        # 从导入页接力：那边解析/选择了 json，切过来自动带过来
        jp = self.cfg.get("import_json", "").strip()
        if jp and jp != self.var_json.get().strip():
            self.var_json.set(jp)
        if not self.var_out.get().strip():
            self.var_out.set(self.cfg.get("import_pkg_out", "") or str(core.APP_DIR / "交付包"))
        self._refresh_src()

    # ───────────── 选择器 ─────────────

    def _pick_json(self):
        p = self.ask_file("选择 pt-clips.json", initial=self.var_json.get(),
                          filetypes=[("PT 解析结果", "*.json"), ("所有文件", "*.*")])
        if p:
            self.var_json.set(p)
            self._refresh_src()

    def _pick_out(self):
        p = self.ask_dir("选择包输出目录", initial=self.var_out.get())
        if p:
            self.var_out.set(p)

    def _refresh_src(self):
        jp = Path(self.var_json.get().strip()) if self.var_json.get().strip() else None
        if not jp or not jp.is_file():
            self.lbl_src.configure(text="未选择" if not jp else "✗ 文件不存在",
                                   foreground="#888" if not jp else "#c62828")
            return
        try:
            doc = json.loads(jp.read_text(encoding="utf-8"))
            session = (doc.get("session") or {}).get("name") or jp.stem
            pkg = jp.parent / "audio"
            has_audio = pkg.is_dir() and any(pkg.glob("*.wav"))
            self.lbl_src.configure(
                text=f"✓ {session}｜{doc.get('track_count', '?')} 轨"
                     f"{'｜已是交付包' if doc.get('_delivery_package') else ''}"
                     f"{'｜同级有 audio/' if has_audio else ''}",
                foreground="#2e7d32")
        except Exception as e:
            self.lbl_src.configure(text=f"✗ 解析失败: {e}", foreground="#c62828")

    # ───────────── 执行 ─────────────

    def _exclude_args(self):
        import re
        raw = self.var_exclude.get().strip()
        ex = [s.strip().lower() for s in re.split(r"[,，]", raw) if s.strip()]
        if not ex:
            import import_audio
            ex = list(import_audio.DEFAULT_EXCLUDE)
        return tuple(ex)

    def _validate(self):
        jp = self.var_json.get().strip()
        out = self.var_out.get().strip()
        if not jp or not Path(jp).is_file():
            messagebox.showwarning("缺少数据源", "请先选择 pt-clips.json。")
            return None
        if not out:
            messagebox.showwarning("缺少输出目录", "请选择包输出目录。")
            return None
        Path(out).mkdir(parents=True, exist_ok=True)
        return Path(jp), Path(out)

    def dry_run(self):
        if self.running:
            return
        v = self._validate()
        if not v:
            return
        jp, out = v
        ex = self._exclude_args()

        def job():
            import make_delivery_package
            make_delivery_package.build_package(jp, out, ex, dry_run=True, light=True)

        self.run_async(job, btn=self.btn_dry, busy_text="预演中…")

    def build_pkg(self):
        if self.running:
            return
        v = self._validate()
        if not v:
            return
        jp, out = v
        ex = self._exclude_args()
        self.save_config(quiet=True)

        def job():
            import make_delivery_package
            rc = make_delivery_package.build_package(jp, out, ex, dry_run=False, light=True)
            if rc != 0:
                raise RuntimeError(f"生成失败（返回码 {rc}）")

        def done(err):
            if err is not None:
                self.log(f"\n✗ 生成失败: {err}\n")
                return
            # 提示固定资产的落点，方便用户把两样东西拖进来
            self.log("\n提示：gen 好的包里还需要放入两样固定资产（一次性做好长期复用）：\n"
                     "    · 导入工具.exe\n"
                     "    · 01-使用说明.txt\n")
            assets = self._find_assets()
            if assets:
                for a in assets:
                    self.log(f"    现成位置：{a}\n")
                if messagebox.askyesno(
                        "是否顺手复制固定资产？",
                        "检测到现成的「导入工具.exe / 01-使用说明.txt」。\n\n"
                        "要现在把它们复制进刚生成的包里吗？\n"
                        "（只需点一次「是」；以后重跑这页生成的包可以直接手拖过去）"):
                    self._copy_assets(jp, out)
            else:
                self.log("    （未找到现成资产，第一次请手动放入）\n")

        self.run_async(job, on_done=done, btn=self.btn_run, busy_text="生成中…")

    # ───────────── 固定资产 ─────────────

    @staticmethod
    def _find_assets():
        """在几个约定位置找「导入工具.exe」与通用说明书。"""
        cands = [
            Path(r"D:\Ai-Files\Agent-Out-exe\_delivery\_交付模板"),
            core.APP_DIR / "_交付模板",
            core.APP_DIR,
        ]
        found = []
        for d in cands:
            if not d.is_dir():
                continue
            for name in ("导入工具.exe", "01-使用说明.txt"):
                p = d / name
                if p.exists() and p not in found:
                    found.append(p)
        return found

    def _copy_assets(self, json_path: Path, out: Path):
        try:
            import make_delivery_package
            doc = json.loads(json_path.read_text(encoding="utf-8"))
            name = ((doc.get("session") or {}).get("name") or json_path.stem).strip()
        except Exception:
            name = json_path.stem
        pkg = out / f"{name}-导入包"
        if not pkg.is_dir():
            self.log(f"✗ 找不到包目录：{pkg}\n")
            return
        n = 0
        for a in self._find_assets():
            try:
                dest = pkg / a.name
                if a.is_dir():
                    shutil.copytree(a, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(a, dest)
                n += 1
                self.log(f"✓ 已放入 {a.name}\n")
            except Exception as e:
                self.log(f"✗ 复制 {a.name} 失败: {e}\n")
        self.log(f"完成，共放入 {n} 项。\n")
