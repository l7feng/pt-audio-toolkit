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

# ---------------------------------------------------------------------------
# 下拉「显示名 ⇄ 内部 key」（v2.6.2 · Q9 Q11）
#
# 旧版把内部 key 直接拼进显示串（"48k24b_st  48k/24bit 立体声"、
# "media  AAF + Media 文件夹"），用户看到的是给程序读的英文；更糟的是
# `_read_spec()` 取首 token 当 key、查不到就**静默回落默认值且不报错** ——
# 用户以为选了 44.1k/16bit，实际导出的是默认值。现在：显示名里只有人话，
# 取不回 key 就 **显式报错**（见 _read_spec / _read_aaf_mode / _read_conflict）。
# ---------------------------------------------------------------------------
SPEC_LABEL_TO_KEY = {v[0]: k for k, v in core.SPEC_PRESETS.items()}
AAF_MODES = {
    "media": "AAF + Media 文件夹（推荐，便于核对素材）",
    "embed": "仅单个 .aaf 文件（体积小，不含素材副本）",
}
AAF_LABEL_TO_KEY = {v: k for k, v in AAF_MODES.items()}
CONFLICT_MODES = {
    "rename": "自动重命名（两份都留）",
    "cover": "覆盖同名文件",
    "skip": "跳过不导出",
}
CONFLICT_LABEL_TO_KEY = {v: k for k, v in CONFLICT_MODES.items()}


class ExportTab(BaseTab):
    title = "① 导出音频"
    config_keys = (
        "input_dir", "output_dir", "name_template", "audio_format", "bitrate_kbps",
        "conflict", "dedupe", "extract_video_tracks", "skip_existing", "remarks",
        "export_mode", "track_name_template", "track_spec", "export_aaf", "aaf_media_mode",
        "split_by_video", "video_project_answers",
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

        # v2.6.2 布局修正：旧版「整轨规格」下拉与「整轨命名」Label **都占了
        # row2/column1**，Label 又被 sticky="e" 挤到右边 —— 视觉上就是下拉框的
        # 边框被压掉一截。现在各占一行，不再抢格。
        ttk.Label(mode_box, text="整轨规格").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        self.var_spec = tk.StringVar()
        self.cb_spec = ttk.Combobox(
            mode_box, textvariable=self.var_spec, state="readonly", width=34,
            values=list(SPEC_LABEL_TO_KEY))
        self._set_spec_display()
        self.cb_spec.grid(row=2, column=1, columnspan=3, sticky="w", padx=4, pady=3)

        ttk.Label(mode_box, text="整轨命名").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        self.var_track_tpl = tk.StringVar(
            value=self.cfg.get("track_name_template") or core.DEFAULT_TRACK_TEMPLATE)
        self.entry_track_tpl = ttk.Entry(mode_box, textvariable=self.var_track_tpl, width=52)
        self.entry_track_tpl.grid(row=3, column=1, columnspan=3, sticky="we", padx=4, pady=3)

        self.var_aaf = tk.BooleanVar(value=bool(self.cfg.get("export_aaf", False)))
        self.var_aaf_mode = tk.StringVar(value=self.cfg.get("aaf_media_mode", "media"))
        aaf_row = ttk.Frame(mode_box)
        aaf_row.grid(row=4, column=0, columnspan=4, sticky="w", padx=4, pady=3)
        self.chk_aaf = ttk.Checkbutton(
            aaf_row, text="同时导出 AAF（交给 Pro Tools 混音）",
            variable=self.var_aaf, command=self._sync_mode)
        self.chk_aaf.pack(side="left")
        ttk.Label(aaf_row, text="交付方式").pack(side="left", padx=(16, 4))
        self.cb_aaf = ttk.Combobox(
            aaf_row, textvariable=self.var_aaf_mode, state="readonly", width=42,
            values=list(AAF_LABEL_TO_KEY))
        self._set_aaf_display()
        self.cb_aaf.pack(side="left")

        mode_box.columnconfigure(2, weight=1)

        cfg_box = ttk.LabelFrame(outer, text="导出配置（片段模式）", padding=8)
        cfg_box.pack(fill="x", padx=8, pady=(0, 6))

        # 草稿目录
        self.var_input_dir = tk.StringVar(value=self.cfg.get("input_dir", ""))
        self.path_row(cfg_box, 0, "剪映草稿目录", self.var_input_dir,
                      self._browse_input_dir,
                      "留空 = 自动定位剪映默认目录；可填草稿根目录，也可填单个草稿文件夹")
        self.entry_input_dir = cfg_box.grid_slaves(row=0, column=1)[0]
        # 目录内容变化即刷新识别结果（手填路径也生效，不只浏览按钮）
        self.var_input_dir.trace_add("write", lambda *a: self._schedule_input_summary())

        # 输出目录
        self.var_output_dir = tk.StringVar(value=self.cfg.get("output_dir", ""))
        self.path_row(cfg_box, 1, "输出目录（必填）", self.var_output_dir,
                      lambda: self._pick_dir(self.var_output_dir),
                      "按 类型/素材 自动分目录")
        # 也可直接把文件夹拖到这个框里（v2.6.2 Q10）
        self.entry_output_dir = cfg_box.grid_slaves(row=1, column=1)[0]

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
                                       values=("128", "192", "256", "320"), width=8,
                                       state="readonly")
        self.cb_bitrate.grid(row=3, column=2, sticky="w", padx=4)

        ttk.Label(cfg_box, text="重名策略").grid(row=3, column=2, sticky="e", padx=(24, 4))
        self.var_conflict = tk.StringVar()
        # v2.6.2：旧版这里是纯英文的 rename/cover/skip
        ttk.Combobox(cfg_box, textvariable=self.var_conflict,
                     values=list(CONFLICT_LABEL_TO_KEY), width=20,
                     state="readonly").grid(row=3, column=3, sticky="w", padx=4)
        self._set_conflict_display()

        # 开关
        self.var_dedupe = tk.BooleanVar(value=bool(self.cfg.get("dedupe", True)))
        self.var_extract_video = tk.BooleanVar(
            value=bool(self.cfg.get("extract_video_tracks", True)))
        self.var_skip_existing = tk.BooleanVar(
            value=bool(self.cfg.get("skip_existing", True)))
        self.var_split_video = tk.BooleanVar(
            value=bool(self.cfg.get("split_by_video", False)))
        row = ttk.Frame(cfg_box)
        row.grid(row=4, column=0, columnspan=4, sticky="w", padx=4, pady=3)
        self.chk_dedupe = ttk.Checkbutton(row, text="按内容去重", variable=self.var_dedupe)
        self.chk_dedupe.pack(side="left")
        ttk.Checkbutton(row, text="提取视频内嵌音轨",
                        variable=self.var_extract_video).pack(side="left", padx=16)
        ttk.Checkbutton(row, text="断点续跑（跳过已处理草稿）",
                        variable=self.var_skip_existing).pack(side="left", padx=16)
        # v2.5.0：按视频片段分包（一个视频 = 一个交付文件夹）
        self.chk_split = ttk.Checkbutton(
            row, text="按视频分包（一个视频片段一个文件夹）",
            variable=self.var_split_video)
        self.chk_split.pack(side="left", padx=16)
        ttk.Label(cfg_box,
                  text="分包时可用新占位符：{视频项目} {集数} {编号} {AiFX} {视频名}；"
                       "整轨命名另可用 {轨道类别}（MX/DX/SFX/AiFX 自动判定）；"
                       "视频名是纯数字或项目名超过 4 字时会弹窗请您补项目名。",
                  foreground="#888").grid(row=6, column=0, columnspan=4, sticky="w",
                                          padx=4, pady=(0, 4))

        # 备注
        ttk.Label(cfg_box, text="备注文案").grid(row=5, column=0, sticky="w", padx=4, pady=3)
        self.var_remarks = tk.StringVar(value=self.cfg.get("remarks", ""))
        ttk.Entry(cfg_box, textvariable=self.var_remarks, width=66).grid(
            row=5, column=1, columnspan=3, sticky="we", padx=4, pady=3)
        cfg_box.columnconfigure(1, weight=1)

        # v2.6.2（Q10）：**取消拖拽区**。
        #   ① 拖拽区占版面但拖进来的语义和「剪映草稿目录」重复；
        #   ② 更严重的是 start_export 里 dropped_paths 恒优先，导致在上面
        #      填/选的目录永远不生效 —— 看起来就是"只能靠拖拽读信息"。
        # 现在只保留单一入口：上方「剪映草稿目录」+ 这里的选择按钮与即时反馈。
        # 拖拽能力本身保留在代码层（on_drop 不删），需要时可随时加回。
        src_box = ttk.LabelFrame(outer, text="输入源（与上方「剪映草稿目录」同一个入口）",
                                 padding=8)
        src_box.pack(fill="x", padx=8, pady=(0, 6))
        src_btns = ttk.Frame(src_box)
        src_btns.pack(fill="x")
        ttk.Button(src_btns, text="选择草稿根目录 / 草稿文件夹…",
                   command=self._browse_input_dir).pack(side="left", padx=4)
        ttk.Button(src_btns, text="选择文件…",
                   command=self._pick_input_files).pack(side="left", padx=4)
        ttk.Button(src_btns, text="清空",
                   command=self._clear_dropped).pack(side="left", padx=4)
        ttk.Button(src_btns, text="重新识别", width=10,
                   command=self._refresh_input_summary).pack(side="left", padx=(12, 0))
        self.var_input_summary = tk.StringVar(value="")
        ttk.Label(src_btns, textvariable=self.var_input_summary,
                  foreground="#2a9").pack(side="left", padx=8)

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
                      tip=("用法：① 填/选「剪映草稿目录」（下方会即时显示识别到几个草稿）"
                           "‣ ② 填输出目录 ‣ ③ 点开始导出。\n"
                           "本页功能完全独立，不需要 Pro Tools。\n"
                           "· 该目录可填**草稿根目录**（自动向下找草稿），也可填**单个草稿文件夹**。\n"
                        "产物按类型分组（v2.6.1）：\n"
                        "  · <草稿名>/<集名>/01-多条WAV/ —— 整轨模式（一条轨一个 WAV，等长对齐）\n"
                        "  · <草稿名>/<集名>/02-素材片段/ —— 片段模式\n"
                        "  · <草稿名>/<集名>/03-AAF/ —— AAF（整轨一个 / 分包每集一个，可直接交 PT）\n"
                           "日志与断点续跑记录在「默认路径设置」指定的日志/数据目录，不混在产物里。\n\n"))

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
        self.cfg["conflict"] = self._read_conflict()
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
        # 分包只在整轨模式下有意义（片段模式本来就是按片段出的）
        self.cfg["split_by_video"] = bool(self.var_split_video.get()) and \
            "tracks" in self._mode_set()

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
        self._set_conflict_display()
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
        self._set_aaf_display()
        self.var_split_video.set(bool(c.get("split_by_video", False)))
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
        """配置 key → 下拉显示名（v2.6.2：显示名里不再混内部 key）。"""
        key = self.cfg.get("track_spec", core.DEFAULT_SPEC_KEY)
        if key not in core.SPEC_PRESETS:
            key = core.DEFAULT_SPEC_KEY     # 脏数据只影响显示，写回前会报错
        self.var_spec.set(core.SPEC_PRESETS[key][0])

    def _read_spec(self) -> str:
        """显示名 → key。

        ⚠️ v2.6.2：认不出来**抛 ValueError，绝不静默回落**。旧实现是
        `v.split()[0] if v else DEFAULT` —— 把框里的字删空、或手打了任意字，
        都会无声无息变成默认规格，用户以为选了 44.1k/16bit，实际导出的是默认值。
        """
        label = (self.var_spec.get() or "").strip()
        if label in SPEC_LABEL_TO_KEY:
            return SPEC_LABEL_TO_KEY[label]
        if label in core.SPEC_PRESETS:          # 兼容旧 config 里存的裸 key
            return label
        raise ValueError("「整轨规格」当前值是「%s」，不在可选项里 —— 请从下拉重新选一项"
                         "（工具不会擅自替你猜一个）。" % (label or "（空）"))

    def _set_aaf_display(self):
        key = self.cfg.get("aaf_media_mode", "media")
        self.var_aaf_mode.set(AAF_MODES.get(key, AAF_MODES["media"]))

    def _read_aaf_mode(self) -> str:
        label = (self.var_aaf_mode.get() or "").strip()
        if label in AAF_LABEL_TO_KEY:
            return AAF_LABEL_TO_KEY[label]
        if label in AAF_MODES:
            return label
        raise ValueError("「交付方式」当前值是「%s」，不在可选项里 —— 请从下拉重新选一项。"
                         % (label or "（空）"))

    def _set_conflict_display(self):
        key = self.cfg.get("conflict", "rename")
        self.var_conflict.set(CONFLICT_MODES.get(key, CONFLICT_MODES["rename"]))

    def _read_conflict(self) -> str:
        label = (self.var_conflict.get() or "").strip()
        if label in CONFLICT_LABEL_TO_KEY:
            return CONFLICT_LABEL_TO_KEY[label]
        if label in CONFLICT_MODES:
            return label
        raise ValueError("「重名策略」当前值是「%s」，不在可选项里 —— 请从下拉重新选一项。"
                         % (label or "（空）"))

    def _sync_mode(self):
        """按勾选模式开关控件：整轨专属项（规格/整轨命名/AAF）仅在勾了整轨时可用；
        片段专属项（格式/码率/去重）仅在勾了片段时可用。

        门控思路与导入页一致 —— 不满足条件直接置灰，而不是等点了才报错。
        """
        mset = self._mode_set()
        tracks = "tracks" in mset
        clip = "clips" in mset
        state = "normal" if tracks else "disabled"
        # 分包依赖整轨（按视频区间切整轨），未勾整轨时置灰
        self.chk_split.configure(state=state)
        for w in (self.entry_track_tpl, self.chk_aaf):
            try:
                w.configure(state=state)
            except Exception:
                pass
        # ⚠️ v2.6.2 真 bug 修复：下拉必须用 **readonly**，不能用 normal。
        #    旧版这里写 `state = "normal" if tracks else "disabled"`，把建控件时
        #    设的 readonly 覆盖掉 → 框里的字能删；删空后旧 `_read_spec()` 取首
        #    token 查不到就静默回落默认值，用户完全不知情。
        combo_state = "readonly" if tracks else "disabled"
        try:
            self.cb_spec.configure(state=combo_state)
        except Exception:
            pass
        # AAF 交付方式只在勾了整轨且勾了 AAF 时可改
        try:
            self.cb_aaf.configure(state="readonly" if (tracks and self.var_aaf.get())
                                  else "disabled")
        except Exception:
            pass
        # 片段专属项（整轨固定 WAV，码率/去重无意义）
        clip_state = "readonly" if clip else "disabled"
        for w in (self.cb_format, self.cb_bitrate):
            try:
                w.configure(state=clip_state)
            except Exception:
                pass
        try:
            self.chk_dedupe.configure(state="normal" if clip else "disabled")
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

    def _browse_input_dir(self):
        """浏览选目录 → 写入「剪映草稿目录」并**立刻反馈识别结果**。

        v2.6.2（Q10）：旧版只 `var.set(p)` 就结束，没有任何反馈；而且因为
        start_export 里 `if self.dropped_paths:` 恒优先，历史上拖过一次后
        这里填什么目录都不生效。现在改成「**最后操作者优先**」—— 选目录即清空
        拖拽列表，目录里的草稿立刻数给你看，不用等到点「开始导出」才发现。
        """
        p = self.ask_dir("选择剪映草稿根目录 / 草稿文件夹",
                         initial=self.var_input_dir.get())
        if not p:
            return
        self.var_input_dir.set(p)
        self.dropped_paths = []
        self._refresh_input_summary()

    def _schedule_input_summary(self):
        """手填路径时延迟刷新识别（避免每敲一个字都递归扫描）。"""
        if getattr(self, "_sum_job", None):
            try:
                self.after_cancel(self._sum_job)
            except Exception:
                pass
        try:
            self._sum_job = self.after(600, self._refresh_input_summary)
        except Exception:
            pass

    def _refresh_input_summary(self):
        """即时识别「剪映草稿目录」里有几个草稿，并给出可读反馈。"""
        if not getattr(self, "var_input_summary", None):
            return
        raw = self.var_input_dir.get().strip()
        if not raw:
            self.var_input_summary.set("未填写 —— 将自动定位剪映默认草稿目录")
            return
        root = Path(raw)
        if not root.exists():
            self.var_input_summary.set("⚠ 路径不存在：%s" % raw)
            return
        try:
            drafts, _r, _fm = core.resolve_input_paths([root])
        except Exception as e:
            self.var_input_summary.set("⚠ 识别失败：%s" % e)
            return
        if drafts:
            self.var_input_summary.set("✓ 已识别 %d 个剪映草稿" % len(drafts))
            self.log("· 草稿目录识别：%d 个 —— %s\n" % (
                len(drafts), "、".join(d.name for d in drafts[:10])))
        else:
            self.var_input_summary.set("⚠ 该目录下没识别到剪映草稿"
                                       "（可往上一级选草稿根目录）")

    def _set_dropped(self, paths):
        self.on_drop(list(paths))

    def _clear_dropped(self):
        self.dropped_paths = []
        self.var_input_dir.set("")
        self._refresh_input_summary()
        self.log("· 已清空输入源\n")

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
            self.var_input_summary.set(f"✓ 已识别 {len(draft_dirs)} 个剪映草稿")
            self.log(f"✓ 拖入识别：{len(draft_dirs)} 个草稿 —— {names}\n")
            for d in draft_dirs[:20]:
                self.log(f"    · 草稿 {d.name}\n")
        elif file_mode:
            self.var_input_summary.set(f"未发现草稿，将按媒体文件整轨提取（来源：{names}）")
            self.log(f"✓ 拖入识别：未发现草稿，按媒体文件处理 —— {names}\n")
        else:
            self.var_input_summary.set("拖入内容中未识别到草稿或音视频，请检查")
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
        try:
            self.collect()
        except ValueError as e:
            # v2.6.2：界面取值不合法就**明确告知**，不再悄悄按默认值跑
            messagebox.showwarning("界面取值有误", str(e))
            return

        if not self._mode_set():
            messagebox.showwarning("未选择导出模式",
                                   "请至少勾选一种导出模式（整轨 / 片段）。")
            return

        if not self.cfg.get("output_dir"):
            messagebox.showwarning("缺少输出目录", "请先填写「输出目录」，或点「浏览…」选择。")
            return

        draft_dirs, media_files, root = [], [], None
        # v2.6.2（Q10）：改成「**最后操作者优先**」。旧版这里 `if self.dropped_paths:`
        # 恒优先 —— 只要历史拖过一次没清空，上面「剪映草稿目录」填什么目录都不生效，
        # 于是看起来就是"只能通过拖拽读取信息"。现在：选/填目录会清空 dropped_paths，
        # 拖入会写回目录框，两者互为最后操作，不会互相压过。
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
            # 浏览按钮选中的目录也走递归草稿识别（与拖拽一致），避免只扫直接子目录
            if root_str:
                found, _, _ = core.resolve_input_paths([root])
                if found:
                    draft_dirs = found

        # 分包模式：先解析视频名，判断不出的项目名**先问人**再跑（工具不猜）
        if self.cfg.get("split_by_video"):
            if not self._prepare_video_names(root, draft_dirs):
                return

        self.save_config(quiet=True)
        cfg = dict(self.cfg)

        def job():
            stats = core.execute_export(cfg, root, draft_dirs=draft_dirs,
                                        media_files=media_files)
            print(f"\n✓ 导出完成：成功 {stats['success']} ｜ 失败 {stats['failed']} ｜ "
                  f"跳过 {stats['skipped']}")

        self.run_async(job, btn=self.btn_run, busy_text="导出中…")

    def _prepare_video_names(self, root, draft_dirs) -> bool:
        """分包前的视频名解析 + 项目名补录。

        流程：扫描草稿 → 取视频轨片段名 → 解析（已存过的答案直接沿用）→
        仍有缺项就弹窗问 → 答案存进 `cfg["video_project_answers"]`（下次不再问）。

        返回 `False` = 用户取消，调用方应中止导出。
        """
        from core.videoname import parse_many, pending_map, suggest_project
        from .videoname_dialog import ask_video_projects

        names = []
        dirs = list(draft_dirs or [])
        if not dirs and root:
            try:
                dirs = core.scan_drafts(Path(root))
            except Exception as e:
                self.log(f"  [warn] 扫描草稿失败：{e}\n")
        for d in dirs:
            try:
                raw = core.resolve_draft_content_file(Path(d))
                dec = core.decrypt_draft_file(raw)
                for ch in core.parse_video_chunks(Path(d), dec):
                    if ch.material_name:
                        names.append(ch.material_name)
            except Exception as e:
                self.log(f"  [warn] 视频名解析失败（{Path(d).name}）：{e}\n")
        if not names:
            return True

        infos = core.apply_project(
            parse_many(names), self.cfg.get("video_project_answers") or {})
        pend = pending_map(infos)
        if not pend:
            return True

        got = ask_video_projects(self.winfo_toplevel(), list(pend.values()),
                                 suggest_project(infos))
        if got is None:                      # 取消 → 中止，不带着缺项跑
            return False
        answers = dict(self.cfg.get("video_project_answers") or {})
        answers.update({k: v for k, v in got.items() if v})
        self.cfg["video_project_answers"] = answers
        self.var_split_video.set(True)
        return True

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
