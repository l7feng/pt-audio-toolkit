#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 导出音频页 —— 剪映草稿 → 切片导出（原 06 项目的全部功能）。

与其他两页完全独立：输入源、输出目录、命名规则都用自己的配置字段。
"""

import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import main as core
from .base import BaseTab


class ExportTab(BaseTab):
    title = "① 导出音频"
    config_keys = (
        "input_dir", "output_dir", "name_template", "audio_format", "bitrate_kbps",
        "conflict", "dedupe", "extract_video_tracks", "skip_existing", "remarks",
        "export_mode", "track_name_template", "track_spec", "export_aaf", "aaf_media_mode",
    )

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.dropped_paths = []
        self.build()

    # ───────────── 界面 ─────────────

    def build(self):
        outer = self

        # ── 导出模式（整轨 / 片段 可多选，同时勾选则一次导出两种产物）──
        mode_box = ttk.LabelFrame(
            outer, text="导出模式（可多选：同时勾选则一次导出「整轨 + 片段」）", padding=8)
        mode_box.pack(fill="x", padx=8, pady=(0, 6))

        mset = self._mode_set()
        self.var_mode_tracks = tk.BooleanVar(value="tracks" in mset)
        self.var_mode_clips = tk.BooleanVar(value="clips" in mset)
        ttk.Checkbutton(
            mode_box, text="① 导出音频轨道（整轨：一条轨一个 WAV，等长对齐，导入 PT 即就位）",
            variable=self.var_mode_tracks, command=self._sync_mode,
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=4, pady=2)
        ttk.Checkbutton(
            mode_box, text="② 导出音频素材（片段：一段一个文件，用于取素材/建素材库）",
            variable=self.var_mode_clips, command=self._sync_mode,
        ).grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=2)

        ttk.Label(mode_box, text="整轨规格").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        self.var_spec = tk.StringVar(value=self.cfg.get("track_spec", core.DEFAULT_SPEC_KEY))
        self.cb_spec = ttk.Combobox(
            mode_box, textvariable=self.var_spec, state="readonly", width=22,
            values=[f"{k}  {v[0]}" for k, v in core.SPEC_PRESETS.items()])
        self._set_spec_display()
        self.cb_spec.grid(row=2, column=1, sticky="w", padx=4, pady=3)

        ttk.Label(mode_box, text="整轨命名").grid(row=2, column=1, sticky="e", padx=(24, 4))
        self.var_track_tpl = tk.StringVar(
            value=self.cfg.get("track_name_template") or core.DEFAULT_TRACK_TEMPLATE)
        self.entry_track_tpl = ttk.Entry(mode_box, textvariable=self.var_track_tpl, width=40)
        self.entry_track_tpl.grid(row=2, column=2, columnspan=2, sticky="we", padx=4, pady=3)

        self.var_aaf = tk.BooleanVar(value=bool(self.cfg.get("export_aaf", False)))
        self.var_aaf_mode = tk.StringVar(value=self.cfg.get("aaf_media_mode", "media"))
        aaf_row = ttk.Frame(mode_box)
        aaf_row.grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=3)
        self.chk_aaf = ttk.Checkbutton(
            aaf_row, text="同时导出 AAF（交给 Pro Tools 混音）",
            variable=self.var_aaf, command=self._sync_mode)
        self.chk_aaf.pack(side="left")
        ttk.Label(aaf_row, text="交付方式").pack(side="left", padx=(16, 4))
        self.cb_aaf = ttk.Combobox(
            aaf_row, textvariable=self.var_aaf_mode, state="readonly", width=26,
            values=("media  AAF + Media 文件夹（推荐）", "embed  仅单个 .aaf 文件"))
        self._set_aaf_display()
        self.cb_aaf.pack(side="left")

        mode_box.columnconfigure(2, weight=1)

        cfg_box = ttk.LabelFrame(outer, text="导出配置（片段模式）", padding=8)
        cfg_box.pack(fill="x", padx=8, pady=(0, 6))

        # 草稿目录
        self.var_input_dir = tk.StringVar(value=self.cfg.get("input_dir", ""))
        self.path_row(cfg_box, 0, "剪映草稿目录", self.var_input_dir,
                      lambda: self._pick_dir(self.var_input_dir),
                      "留空 = 自动定位剪映默认目录")
        self.entry_input_dir = cfg_box.grid_slaves(row=0, column=1)[0]

        # 输出目录
        self.var_output_dir = tk.StringVar(value=self.cfg.get("output_dir", ""))
        self.path_row(cfg_box, 1, "输出目录（必填）", self.var_output_dir,
                      lambda: self._pick_dir(self.var_output_dir),
                      "按 类型/素材 自动分目录")

        # 命名模板（多选：勾选多个 → 各生成一份输出）
        ttk.Label(cfg_box, text="命名模板（可多选）").grid(row=2, column=0, sticky="nw", padx=4, pady=3)
        nt_frame = ttk.Frame(cfg_box)
        nt_frame.grid(row=2, column=1, columnspan=3, sticky="we", padx=4, pady=3)
        self._seed_templates()
        self.lb_templates = tk.Listbox(nt_frame, height=4, selectmode="extended",
                                       exportselection=0)
        self.lb_templates.grid(row=0, column=0, columnspan=4, sticky="we", padx=(0, 4))
        row_nt = ttk.Frame(nt_frame)
        row_nt.grid(row=1, column=0, columnspan=4, sticky="w", pady=(3, 0))
        self.var_new_tpl = tk.StringVar()
        ttk.Entry(row_nt, textvariable=self.var_new_tpl, width=42).pack(side="left", padx=(0, 4))
        ttk.Button(row_nt, text="添加模板", command=self._add_template).pack(side="left", padx=2)
        ttk.Button(row_nt, text="删除选中", command=self._remove_template).pack(side="left", padx=2)
        ttk.Label(nt_frame,
                  text="Ctrl/Shift 多选；勾选的模板会各生成一份输出（多模板时按「模板N」分目录）",
                  foreground="#888").grid(row=2, column=0, columnspan=4, sticky="w")
        self._fill_templates()

        # 格式 / 码率 / 重名
        ttk.Label(cfg_box, text="音频格式").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        self.var_format = tk.StringVar(value=self.cfg.get("audio_format", "mp3"))
        self.cb_format = ttk.Combobox(cfg_box, textvariable=self.var_format, values=("mp3", "wav"),
                                      width=10, state="readonly")
        self.cb_format.grid(row=3, column=1, sticky="w", padx=4)

        ttk.Label(cfg_box, text="码率 kbps").grid(row=3, column=1, sticky="e", padx=(24, 4))
        self.var_bitrate = tk.StringVar(value=str(self.cfg.get("bitrate_kbps", 192)))
        self.cb_bitrate = ttk.Combobox(cfg_box, textvariable=self.var_bitrate,
                                       values=("128", "192", "256", "320"), width=8)
        self.cb_bitrate.grid(row=3, column=2, sticky="w", padx=4)

        ttk.Label(cfg_box, text="重名策略").grid(row=3, column=2, sticky="e", padx=(24, 4))
        self.var_conflict = tk.StringVar(value=self.cfg.get("conflict", "rename"))
        ttk.Combobox(cfg_box, textvariable=self.var_conflict,
                     values=("rename", "cover", "skip"), width=10, state="readonly").grid(
            row=3, column=3, sticky="w", padx=4)

        # 开关
        self.var_dedupe = tk.BooleanVar(value=bool(self.cfg.get("dedupe", True)))
        self.var_extract_video = tk.BooleanVar(
            value=bool(self.cfg.get("extract_video_tracks", True)))
        self.var_skip_existing = tk.BooleanVar(
            value=bool(self.cfg.get("skip_existing", True)))
        row = ttk.Frame(cfg_box)
        row.grid(row=4, column=0, columnspan=4, sticky="w", padx=4, pady=3)
        self.chk_dedupe = ttk.Checkbutton(row, text="按内容去重", variable=self.var_dedupe)
        self.chk_dedupe.pack(side="left")
        ttk.Checkbutton(row, text="提取视频内嵌音轨",
                        variable=self.var_extract_video).pack(side="left", padx=16)
        ttk.Checkbutton(row, text="断点续跑（跳过已处理草稿）",
                        variable=self.var_skip_existing).pack(side="left", padx=16)

        # 备注
        ttk.Label(cfg_box, text="备注文案").grid(row=5, column=0, sticky="w", padx=4, pady=3)
        self.var_remarks = tk.StringVar(value=self.cfg.get("remarks", ""))
        ttk.Entry(cfg_box, textvariable=self.var_remarks, width=66).grid(
            row=5, column=1, columnspan=3, sticky="we", padx=4, pady=3)
        cfg_box.columnconfigure(1, weight=1)

        # 拖拽区
        drop_box = ttk.LabelFrame(
            outer, text="拖拽区（可直接把文件夹 / 草稿 / 音视频拖到这里）", padding=8)
        drop_box.pack(fill="x", padx=8, pady=(0, 6))
        self.drop_label = tk.Label(
            drop_box,
            text=("拖拽到此处\n"
                  "· 文件夹 → 自动识别其中的剪映草稿\n"
                  "· 剪映草稿文件夹 / draft_content.json / .jane → 按时间线片段导出\n"
                  "· 音视频文件 → 整轨提取音频"),
            justify="center", anchor="center", bg="#2b2b2b", fg="#9cdcfe",
            font=("Microsoft YaHei UI", 10), height=4, relief="ridge", bd=1,
            cursor="hand2")
        self.drop_label.pack(fill="x", padx=2, pady=2)
        drop_btns = ttk.Frame(drop_box)
        drop_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(drop_btns, text="选择文件夹…",
                   command=self._pick_input_dir).pack(side="left", padx=4)
        ttk.Button(drop_btns, text="选择文件…",
                   command=self._pick_input_files).pack(side="left", padx=4)
        ttk.Button(drop_btns, text="清空",
                   command=self._clear_dropped).pack(side="left", padx=4)
        self.var_drop_summary = tk.StringVar(
            value="尚未拖入任何内容（未拖入时按上方「剪映草稿目录」处理）")
        ttk.Label(drop_btns, textvariable=self.var_drop_summary,
                  foreground="#888").pack(side="left", padx=8)

        # 按钮
        btn_box = ttk.Frame(outer)
        btn_box.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(btn_box, text="环境自检", command=self.run_check).pack(side="left", padx=4)
        ttk.Button(btn_box, text="保存配置",
                   command=lambda: self.save_config()).pack(side="left", padx=4)
        ttk.Button(btn_box, text="打开输出目录",
                   command=self.open_output_dir).pack(side="left", padx=4)
        self.btn_run = ttk.Button(btn_box, text="▶ 开始导出", command=self.start_export)
        self.btn_run.pack(side="right", padx=4)

        # 日志
        self.make_log(outer, height=13,
                      tip=("用法：① 把草稿/文件夹拖进拖拽区（或填草稿目录）"
                           "‣ ② 填输出目录 ‣ ③ 点开始导出。\n"
                           "本页功能完全独立，不需要 Pro Tools。\n"
                           "整轨模式输出到「输出目录/<草稿名>/」，一条轨一个 WAV，"
                           "所有轨等长对齐，导入 PT 无需手动摆位。\n\n"))

        self._sync_mode()

    def _mode_set(self) -> set:
        """当前勾选的导出模式集合（兼容旧配置的单字符串值）。"""
        m = self.cfg.get("export_mode", ["tracks"])
        if isinstance(m, str):
            m = [m]
        return set(m) & {"tracks", "clips"}

    def collect(self):
        """只写本页字段，绝不触碰导入页/交付页的配置。"""
        self.cfg["input_dir"] = self.var_input_dir.get().strip()
        self.cfg["output_dir"] = self.var_output_dir.get().strip()
        sel_idx = list(self.lb_templates.curselection())
        lib = self.cfg["name_templates"]
        active = [lib[i] for i in sel_idx if 0 <= i < len(lib)]
        if not active:
            active = [lib[0]] if lib else [core.DEFAULT_CLIPS_TEMPLATE]
        self.cfg["name_templates_active"] = active
        self.cfg["name_template"] = active[0]   # 兼容旧字段 / CLI
        self.cfg["audio_format"] = self.var_format.get()
        try:
            self.cfg["bitrate_kbps"] = int(self.var_bitrate.get())
        except ValueError:
            self.cfg["bitrate_kbps"] = 192
        self.cfg["conflict"] = self.var_conflict.get()
        self.cfg["dedupe"] = bool(self.var_dedupe.get())
        self.cfg["extract_video_tracks"] = bool(self.var_extract_video.get())
        self.cfg["skip_existing"] = bool(self.var_skip_existing.get())
        self.cfg["remarks"] = self.var_remarks.get().strip()
        sel = []
        if self.var_mode_tracks.get():
            sel.append("tracks")
        if self.var_mode_clips.get():
            sel.append("clips")
        self.cfg["export_mode"] = sel
        self.cfg["track_name_template"] = self.var_track_tpl.get().strip() or core.DEFAULT_TRACK_TEMPLATE
        self.cfg["track_spec"] = self._read_spec()
        self.cfg["export_aaf"] = bool(self.var_aaf.get())
        self.cfg["aaf_media_mode"] = self._read_aaf_mode()

    def apply_config(self):
        """把 self.cfg 的值刷回控件（菜单「重新载入配置」「默认路径」后调用）。

        只刷 collect 里读过的字段，顺序与 collect 对称。
        """
        c = self.cfg
        self.var_input_dir.set(c.get("input_dir", ""))
        self.var_output_dir.set(c.get("output_dir", ""))
        self.var_template.set(c.get("name_template", ""))
        self.var_format.set(c.get("audio_format", "mp3"))
        self.var_bitrate.set(str(c.get("bitrate_kbps", 192)))
        self.var_conflict.set(c.get("conflict", "rename"))
        self.var_dedupe.set(bool(c.get("dedupe", True)))
        self.var_extract_video.set(bool(c.get("extract_video_tracks", True)))
        self.var_skip_existing.set(bool(c.get("skip_existing", True)))
        self.var_remarks.set(c.get("remarks", ""))
        self._seed_templates()
        self._fill_templates()
        mraw = c.get("export_mode", ["tracks"])
        mset = {mraw} if isinstance(mraw, str) else set(mraw)
        self.var_mode_tracks.set("tracks" in mset)
        self.var_mode_clips.set("clips" in mset)
        self.var_track_tpl.set(c.get("track_name_template")
                               or core.DEFAULT_TRACK_TEMPLATE)
        self.var_aaf.set(bool(c.get("export_aaf", False)))
        self.var_aaf_mode.set(c.get("aaf_media_mode", "media"))
        self._set_spec_display()
        self._set_aaf_display()
        self._sync_mode()

    # ───────────── 命名模板库（多选）─────────────

    def _seed_templates(self):
        """向后兼容 + 初始化模板库：旧配置只有单 ``name_template`` 时，补出
        ``name_templates`` / ``name_templates_active``。"""
        if not self.cfg.get("name_templates"):
            presets = list(core.NAMING_PRESETS)
            legacy = self.cfg.get("name_template") or core.DEFAULT_CLIPS_TEMPLATE
            if legacy and legacy not in presets:
                presets.insert(0, legacy)
            self.cfg["name_templates"] = presets
        if not self.cfg.get("name_templates_active"):
            legacy = self.cfg.get("name_template") or (
                self.cfg["name_templates"][0] if self.cfg["name_templates"]
                else core.DEFAULT_CLIPS_TEMPLATE)
            active = [legacy] if legacy in self.cfg["name_templates"] else \
                [self.cfg["name_templates"][0]]
            self.cfg["name_templates_active"] = active

    def _fill_templates(self):
        """把模板库渲染进 Listbox，并选中 active 项。"""
        self.lb_templates.delete(0, "end")
        for tpl in self.cfg["name_templates"]:
            self.lb_templates.insert("end", tpl)
        active = set(self.cfg.get("name_templates_active", []))
        for i, tpl in enumerate(self.cfg["name_templates"]):
            if tpl in active:
                self.lb_templates.selection_set(i)

    def _add_template(self):
        new = self.var_new_tpl.get().strip()
        if not new:
            return
        if new not in self.cfg["name_templates"]:
            self.cfg["name_templates"].append(new)
        if new not in self.cfg["name_templates_active"]:
            self.cfg["name_templates_active"].append(new)
        self.var_new_tpl.set("")
        self._fill_templates()

    def _remove_template(self):
        idxs = list(self.lb_templates.curselection())
        if not idxs:
            return
        for i in sorted(idxs, reverse=True):
            if 0 <= i < len(self.cfg["name_templates"]):
                removed = self.cfg["name_templates"].pop(i)
                if removed in self.cfg["name_templates_active"]:
                    self.cfg["name_templates_active"].remove(removed)
        if not self.cfg["name_templates"]:
            self.cfg["name_templates"] = [core.DEFAULT_CLIPS_TEMPLATE]
        if not self.cfg["name_templates_active"]:
            self.cfg["name_templates_active"] = [self.cfg["name_templates"][0]]
        self._fill_templates()

    # ───────────── 规格 / AAF 下拉的「值 ↔ 显示」转换 ─────────────

    def _set_spec_display(self):
        """把配置里的 key 回填成下拉里的显示串（key 是前缀）。"""
        key = self.cfg.get("track_spec", core.DEFAULT_SPEC_KEY)
        for label in self.cb_spec["values"]:
            if label.split()[0] == key:
                self.var_spec.set(label)
                return
        self.var_spec.set(self.cb_spec["values"][0]) if self.cb_spec["values"] else None

    def _read_spec(self) -> str:
        """从下拉显示串取回 key。"""
        v = (self.var_spec.get() or "").split()
        return v[0] if v else core.DEFAULT_SPEC_KEY

    def _set_aaf_display(self):
        key = self.cfg.get("aaf_media_mode", "media")
        for label in self.cb_aaf["values"]:
            if label.split()[0] == key:
                self.var_aaf_mode.set(label)
                return
        if self.cb_aaf["values"]:
            self.var_aaf_mode.set(self.cb_aaf["values"][0])

    def _read_aaf_mode(self) -> str:
        v = (self.var_aaf_mode.get() or "").split()
        return v[0] if v else "media"

    def _sync_mode(self):
        """按勾选模式开关控件：整轨专属项（规格/整轨命名/AAF）仅在勾了整轨时可用；
        片段专属项（格式/码率/去重）仅在勾了片段时可用。

        门控思路与导入页一致 —— 不满足条件直接置灰，而不是等点了才报错。
        """
        mset = self._mode_set()
        tracks = "tracks" in mset
        clip = "clips" in mset
        state = "normal" if tracks else "disabled"
        for w in (self.cb_spec, self.entry_track_tpl, self.chk_aaf):
            try:
                w.configure(state=state)
            except Exception:
                pass
        # AAF 交付方式只在勾了整轨且勾了 AAF 时可改
        try:
            self.cb_aaf.configure(state="normal" if (tracks and self.var_aaf.get()) else "disabled")
        except Exception:
            pass
        # 片段专属项（整轨固定 WAV，码率/去重无意义）
        clip_state = "normal" if clip else "disabled"
        for w in (self.cb_format, self.cb_bitrate, self.chk_dedupe):
            try:
                w.configure(state=clip_state)
            except Exception:
                pass

    # ───────────── 拖拽 ─────────────

    def _pick_dir(self, var: tk.StringVar):
        p = self.ask_dir(initial=var.get())
        if p:
            var.set(p)

    def _pick_input_dir(self):
        p = self.ask_dir("选择文件夹（草稿目录 / 媒体目录）")
        if p:
            self._set_dropped([Path(p)])

    def _pick_input_files(self):
        from tkinter import filedialog
        files = filedialog.askopenfilenames(
            title="选择草稿 JSON 或音视频文件",
            filetypes=[
                ("全部支持", "*.json;*.jane;*.mp4;*.mov;*.mkv;*.avi;*.flv;*.webm;*.mp3;*.wav;*.flac;*.m4a;*.aac"),
                ("剪映草稿", "*.json;*.jane"),
                ("音视频", "*.mp4;*.mov;*.mkv;*.avi;*.webm;*.mp3;*.wav;*.flac;*.m4a;*.aac"),
                ("所有文件", "*.*"),
            ])
        if files:
            self._set_dropped([Path(f) for f in files])

    def _set_dropped(self, paths):
        self.on_drop(list(paths))

    def _clear_dropped(self):
        self.dropped_paths = []
        self.var_drop_summary.set("尚未拖入任何内容（未拖入时按上方「剪映草稿目录」处理）")
        self.log("· 已清空拖拽列表，恢复按「剪映草稿目录」处理\n")

    def on_drop(self, paths):
        """由主窗口的拖放处理器转发进来。"""
        paths = [p for p in paths if p.exists()]
        if not paths:
            self.log("✗ 拖入的内容无法识别（路径不存在）\n")
            return
        self.dropped_paths = paths
        try:
            draft_dirs, _root, file_mode = core.resolve_input_paths(paths)
        except Exception as e:
            self.log(f"✗ 拖入内容解析失败: {e}\n")
            return
        names = "、".join(p.name for p in paths[:6])
        if len(paths) > 6:
            names += f" 等 {len(paths)} 项"

        if draft_dirs:
            self.var_drop_summary.set(f"已识别 {len(draft_dirs)} 个剪映草稿（来源：{names}）")
            self.log(f"✓ 拖入识别：{len(draft_dirs)} 个草稿 —— {names}\n")
            for d in draft_dirs[:20]:
                self.log(f"    · 草稿 {d.name}\n")
        elif file_mode:
            self.var_drop_summary.set(f"未发现草稿，将按媒体文件整轨提取（来源：{names}）")
            self.log(f"✓ 拖入识别：未发现草稿，按媒体文件处理 —— {names}\n")
        else:
            self.var_drop_summary.set("拖入内容中未识别到草稿或音视频，请检查")
            self.log(f"✗ 未识别到可导出的内容: {names}\n")

        if len(paths) == 1 and paths[0].is_dir():
            self.var_input_dir.set(str(paths[0]))

    # ───────────── 动作 ─────────────

    def open_output_dir(self):
        path = self.var_output_dir.get().strip() or core.DEFAULT_CONFIG["output_dir"]
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("无法创建", f"输出目录创建失败：{e}")
            return
        self.open_in_explorer(path)

    def run_check(self):
        if self.running:
            return
        self.log("=" * 40 + "\n环境自检开始…\n" + "=" * 40 + "\n")

        def job():
            core.check_environment()
            print("\n环境自检完成。ffmpeg / 剪映就绪即可开始导出。\n")

        self.run_async(job)

    def start_export(self):
        if self.running:
            return
        self.collect()

        if not self._mode_set():
            messagebox.showwarning("未选择导出模式",
                                   "请至少勾选一种导出模式（整轨 / 片段）。")
            return

        if not self.cfg.get("output_dir"):
            messagebox.showwarning("缺少输出目录", "请先填写「输出目录」，或点「浏览…」选择。")
            return

        draft_dirs, media_files, root = [], [], None
        if self.dropped_paths:
            draft_dirs, root, file_mode = core.resolve_input_paths(self.dropped_paths)
            if not draft_dirs and not media_files and not file_mode:
                messagebox.showwarning("无法识别输入",
                                       "拖入的内容里没有识别到剪映草稿或音视频文件。")
                return
            if file_mode:
                media_files = self._collect_media_files()
        else:
            root_str = self.cfg.get("input_dir", "").strip()
            root = Path(root_str) if root_str else core.DEFAULT_JIANYING_DRAFT_ROOT

        self.save_config(quiet=True)
        cfg = dict(self.cfg)

        def job():
            stats = core.execute_export(cfg, root, draft_dirs=draft_dirs,
                                        media_files=media_files)
            print(f"\n✓ 导出完成：成功 {stats['success']} ｜ 失败 {stats['failed']} ｜ "
                  f"跳过 {stats['skipped']}")

        self.run_async(job, btn=self.btn_run, busy_text="导出中…")

    def _collect_media_files(self):
        files = []
        for p in self.dropped_paths:
            if p.is_file() and core.media_kind(p):
                files.append(p)
            elif p.is_dir():
                files.extend(f for f in p.rglob("*")
                             if f.is_file() and core.media_kind(f))
        return files

    def on_show(self):
        self._sync_mode()
