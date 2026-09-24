#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② 导入多轨页 —— 把 PT 工程（或交付包 json）写成剪映草稿的多轨结构。

两种数据源（页面顶部切换）：

  A) **Pro Tools 工程（需 PT 在线）**
     点「① 解析 PT 工程」→ 通过 PTSL 向运行中的 Pro Tools 要会话信息 → 得到 pt-clips.json。
     ⚠️ PTSL 不是文件解析器，它必须向「正在运行的 PT」发命令，
        所以这一步**无法离线**。解析完就与 PT 无关了。

  B) **交付包 json（完全离线）**
     直接选别人发来的 `xxx.pt-clips.json`（音频在同级 audio/）。
     无 PT、无原始工程路径也能导入 —— 这是跨设备场景的正解。

两段式交互的用意：
  「解析」与「写入」是**两个时刻**，各有前置条件，且条件互斥：
    · 解析时：PT 必须在线（剪映开不开无所谓）
    · 写入时：剪映必须关闭（PT 开不开无所谓）
  所以拆成两个按钮，各自在自己的时刻检查自己的条件。这样「离线场景」
  天然只走第 ② 步，不满足条件时按钮直接置灰，不会走到一半报错。
"""

import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import main as core
from .base import BaseTab, default_draft_root, list_drafts

SRC_PT = "pt"
SRC_JSON = "json"


class ImportTab(BaseTab):
    title = "② 导入多轨"
    config_keys = ("import_json", "import_draft_dir", "import_exclude", "import_keep_aux")

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._drafts = []
        self.build()

    # ───────────── 界面 ─────────────

    def build(self):
        outer = self

        # ── 数据源 ──
        src_box = ttk.LabelFrame(outer, text="数据源", padding=8)
        src_box.pack(fill="x", padx=8, pady=(0, 6))

        self.var_src = tk.StringVar(value=self._guess_source())
        src_row = ttk.Frame(src_box)
        src_row.pack(fill="x")
        ttk.Radiobutton(src_row, text="Pro Tools 工程（需 PT 在线）", value=SRC_PT,
                        variable=self.var_src,
                        command=self._on_source_change).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(src_row, text="交付包 json（完全离线）", value=SRC_JSON,
                        variable=self.var_src,
                        command=self._on_source_change).pack(side="left")

        self.lbl_src_hint = ttk.Label(src_box, text="", foreground="#888", wraplength=760,
                                      justify="left")
        self.lbl_src_hint.pack(fill="x", pady=(4, 0))

        # PT 文件行
        self.row_pt = ttk.Frame(src_box)
        self.var_ptx = tk.StringVar(value="")
        ttk.Label(self.row_pt, text=".ptx 工程").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(self.row_pt, textvariable=self.var_ptx, width=48).grid(
            row=0, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(self.row_pt, text="浏览…", command=self._pick_ptx).grid(row=0, column=2, padx=4)
        self.lbl_pt_state = ttk.Label(self.row_pt, text="检测中…", foreground="#888")
        self.lbl_pt_state.grid(row=0, column=3, sticky="w", padx=8)
        self.btn_parse = ttk.Button(self.row_pt, text="① 解析 PT 工程",
                                    command=self.parse_pt)
        self.btn_parse.grid(row=0, column=4, padx=4)
        self.row_pt.columnconfigure(1, weight=1)

        # json 文件行
        self.row_json = ttk.Frame(src_box)
        self.var_json = tk.StringVar(value=self.cfg.get("import_json", ""))
        ttk.Label(self.row_json, text="pt-clips.json").grid(
            row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(self.row_json, textvariable=self.var_json, width=48).grid(
            row=0, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(self.row_json, text="浏览…", command=self._pick_json).grid(row=0, column=2, padx=4)
        self.lbl_json_state = ttk.Label(self.row_json, text="", foreground="#888")
        self.lbl_json_state.grid(row=0, column=3, columnspan=2, sticky="w", padx=8)
        self.row_json.columnconfigure(1, weight=1)

        # ── 目标草稿 ──
        dst_box = ttk.LabelFrame(outer, text="写入目标", padding=8)
        dst_box.pack(fill="x", padx=8, pady=(0, 6))

        self.var_draft_dir = tk.StringVar(value=self.cfg.get("import_draft_dir", ""))
        ttk.Label(dst_box, text="剪映草稿").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.cmb_draft = ttk.Combobox(dst_box, textvariable=self.var_draft_dir, width=46)
        self.cmb_draft.grid(row=0, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(dst_box, text="刷新列表", command=self.refresh_drafts).grid(row=0, column=2, padx=4)
        ttk.Button(dst_box, text="浏览…", command=self._pick_draft_dir).grid(row=0, column=3, padx=4)
        self.lbl_draft_state = ttk.Label(dst_box, text="", foreground="#888")
        self.lbl_draft_state.grid(row=0, column=4, sticky="w", padx=8)
        dst_box.columnconfigure(1, weight=1)

        opt = ttk.Frame(dst_box)
        opt.grid(row=1, column=0, columnspan=5, sticky="we", padx=4, pady=3)
        ttk.Label(opt, text="排除轨道关键词").pack(side="left")
        self.var_exclude = tk.StringVar(value=self.cfg.get("import_exclude", ""))
        ttk.Entry(opt, textvariable=self.var_exclude, width=34).pack(side="left", padx=6)
        ttk.Label(opt, text="（逗号分隔；留空 = 默认排除 VCA/Verb/Dly/BUS 等辅助轨）",
                  foreground="#888").pack(side="left")
        self.var_keep_aux = tk.BooleanVar(value=bool(self.cfg.get("import_keep_aux", False)))
        ttk.Checkbutton(opt, text="保留辅助轨", variable=self.var_keep_aux).pack(side="left", padx=16)

        # ── 按钮 ──
        btn_box = ttk.Frame(outer)
        btn_box.pack(fill="x", padx=8, pady=(0, 4))
        self.btn_preview = ttk.Button(btn_box, text="预演（不写入）", command=self.preview)
        self.btn_preview.pack(side="left", padx=4)
        self.btn_import = ttk.Button(btn_box, text="② 导入到剪映草稿", command=self.do_import)
        self.btn_import.pack(side="right", padx=4)
        self.btn_import.configure(style="Accent.TButton")

        ttk.Label(outer,
                  text=("流程：① 解析/选择数据源 → ② 选目标草稿 → ③ 点导入。\n"
                        "· 选 .ptx 时 Pro Tools 必须已打开该工程；选 json 则完全离线。\n"
                        "· 写入前请【完全退出剪映】—— 否则剪映会用内存里的旧内容覆盖写入。"),
                  foreground="#777", justify="left").pack(anchor="w", padx=12, pady=(0, 4))

        self.make_log(outer, height=12)

        self._on_source_change()
        self.refresh_drafts()

    def _guess_source(self) -> str:
        """默认选中：已存 json 就用 json 模式，否则 PT 模式。"""
        return SRC_JSON if self.cfg.get("import_json") else SRC_PT

    # ───────────── 状态联动 ─────────────

    def _on_source_change(self):
        is_pt = self.var_src.get() == SRC_PT
        self.row_pt.pack(fill="x", pady=(6, 0)) if is_pt else self.row_pt.pack_forget()
        self.row_json.pack(fill="x", pady=(6, 0)) if not is_pt else self.row_json.pack_forget()

        if is_pt:
            self.lbl_src_hint.configure(
                text=("⚠️ 解析 .ptx 必须由**正在运行的 Pro Tools** 提供数据"
                      "（PTSL 是客户端不是文件解析器），因此这一步无法离线。"
                      "解析成功后即与 PT 无关，可关闭 PT。\n"
                      "需要给剪辑/其他机器导入时，请用 pt-tools「扫描建档 → 生成交付包」"
                      "（v2.7.0 起③页退役，交付包在那边一步直出）。"))
        else:
            self.lbl_src_hint.configure(
                text=("✓ 完全离线：直接选交付包里的 pt-clips.json，音频从同级的 audio/ 目录读取。"
                      "不需要 Pro Tools，也不需要原始工程路径。"))
        self.refresh_states()

    def refresh_states(self):
        """刷新 PT / 剪映 / json 的状态提示，并按前置条件启用或禁用按钮。

        ⚠️ **本函数在主线程被高频调用**（切页 / 选文件 / 刷草稿列表 / 任务完成
        共 8 个触发点），因此**绝不能在这里做同步探测** —— 一次
        ``pro_tools_status()`` 就要 0.4~0.7s（tasklist 0.43s + 端口探活超时），
        正是 2026-09-19 用户反馈的「切页卡顿」主因。

        现在改为**读共享探测器的缓存**（后台线程在跑，状态栏用的就是同一份），
        瞬时返回；缓存还没就绪时按「检测中」显示并暂时禁用按钮，
        等 ``StatusProbe`` 回调后由主窗口再触发一次 ``refresh_states()``。
        """
        # PT 状态（只在 PT 模式下需要）—— 读缓存，不探测
        if self.var_src.get() == SRC_PT:
            cached = None
            try:
                cached = self.app._probe.get_cached()
            except Exception:
                cached = None
            if cached and cached.get("pt") and cached["pt"][1]:
                ok, msg = cached["pt"]
                self.lbl_pt_state.configure(text=("✓ " if ok else "✗ ") + msg,
                                            foreground=("#2e7d32" if ok else "#c62828"))
                self.btn_parse.configure(state="normal" if ok else "disabled")
            else:
                # 探测尚未就绪：给中性提示，按钮先禁用（避免用户点了才失败）
                self.lbl_pt_state.configure(text="… 正在检测 Pro Tools 状态",
                                            foreground="#888")
                self.btn_parse.configure(state="disabled")
        else:
            self.lbl_pt_state.configure(text="")
            self.btn_parse.configure(state="disabled")

        # json 状态
        jp = Path(self.var_json.get().strip()) if self.var_json.get().strip() else None
        if jp and jp.is_file():
            try:
                doc, n_wav, is_pkg = self._json_summary(jp)
                n_track = len(doc.get("tracks", []))
                n_clip = sum(len(t.get("clips", [])) for t in doc.get("tracks", []))
                audio_dir = jp.parent / "audio"
                extra = ""
                if is_pkg or audio_dir.is_dir():
                    extra = f"｜音频 {n_wav} 个（包内 audio/）"
                elif doc.get("online_files"):
                    extra = "｜素材指向原始路径（本机自用）"
                self.lbl_json_state.configure(
                    text=f"✓ {n_track} 轨 / {n_clip} 片段{extra}", foreground="#2e7d32")
            except Exception as e:
                self.lbl_json_state.configure(text=f"✗ 解析失败: {e}", foreground="#c62828")
        elif jp:
            self.lbl_json_state.configure(text="✗ 文件不存在", foreground="#c62828")
        else:
            self.lbl_json_state.configure(text="")

        # 剪映状态（写入前置条件）
        draft = Path(self.var_draft_dir.get().strip()) if self.var_draft_dir.get().strip() else None
        ready = bool(jp and jp.is_file() and draft and draft.is_dir())
        if draft and draft.is_dir():
            blockers, warns = self._jy_state(draft)
            if blockers:
                self.lbl_draft_state.configure(
                    text="✗ 剪映正在运行，导入会无效", foreground="#c62828")
                ready = False
            elif warns:
                self.lbl_draft_state.configure(text="! " + warns[0].split("（")[0],
                                               foreground="#ef6c00")
            else:
                self.lbl_draft_state.configure(text="✓ 可以写入", foreground="#2e7d32")
        elif draft:
            self.lbl_draft_state.configure(text="✗ 目录不存在", foreground="#c62828")
        else:
            self.lbl_draft_state.configure(text="", foreground="#888")
            ready = False

        state = "normal" if ready else "disabled"
        self.btn_import.configure(state=state)
        self.btn_preview.configure(state="normal" if jp and jp.is_file() else "disabled")

    def _json_summary(self, jp: Path):
        """读 pt-clips.json 概要：``(doc, wav_count, is_delivery_package)``。

        **带 mtime 缓存**：``refresh_states`` 会在每次切页/选文件时调到这里，
        而 json 有 58KB、`glob("*.wav")` 在交付包里要扫几百个文件 ——
        每次都重读会让切页明显发涩（2026-09-19 实测 ~50ms/次）。
        文件没被改过（mtime+size 都没变）就直接复用上次结果。
        """
        try:
            st = jp.stat()
            key = (str(jp), st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        if key is not None and getattr(self, "_jsum_key", None) == key:
            return self._jsum_val
        doc = json.loads(jp.read_text(encoding="utf-8"))
        is_pkg = bool(doc.get("_delivery_package"))
        audio_dir = jp.parent / "audio"
        n_wav = len(list(audio_dir.glob("*.wav"))) if audio_dir.is_dir() else 0
        val = (doc, n_wav, is_pkg)
        if key is not None:
            self._jsum_key = key
            self._jsum_val = val
        return val

    @staticmethod
    def _jy_state(draft: Path, realtime: bool = False):
        """复用导入器的剪映检测（同一判据，避免两处不一致）。

        ``realtime=False``（默认，用于状态提示/按钮门控）：可吃 tasklist 缓存，
        省掉每次 ``refresh_states()`` 的 ~0.5s 进程枚举 —— ``refresh_states``
        被切页、选文件、刷草稿列表等 8 个点触发，是切页卡顿的主要来源。

        ``realtime=True``（**真正点下「导入」时**）：强制实时枚举，
        因为这是最后一次拦截机会，缓存 5 秒的误差会放过「刚打开剪映」。
        """
        try:
            import import_audio
            if realtime:
                return import_audio.jianying_running_realtime(draft)
            return import_audio.jianying_running(draft)
        except Exception:
            return [], []

    def on_show(self):
        self.refresh_states()

    def collect(self):
        self.cfg["import_json"] = self.var_json.get().strip()
        self.cfg["import_draft_dir"] = self.var_draft_dir.get().strip()
        self.cfg["import_exclude"] = self.var_exclude.get().strip()
        self.cfg["import_keep_aux"] = bool(self.var_keep_aux.get())

    def apply_config(self):
        """把 self.cfg 的值刷回控件（菜单「重新载入配置」「默认路径」后调用）。"""
        c = self.cfg
        self.var_json.set(c.get("import_json", ""))
        self.var_draft_dir.set(c.get("import_draft_dir", ""))
        self.var_exclude.set(c.get("import_exclude", ""))
        self.var_keep_aux.set(bool(c.get("import_keep_aux", False)))
        self.var_src.set(self._guess_source())
        self._on_source_change()

    # ───────────── 选择器 ─────────────

    def _pick_ptx(self):
        p = self.ask_file("选择 Pro Tools 工程（.ptx）", initial=self.var_ptx.get(),
                          filetypes=[("Pro Tools 工程", "*.ptx;*.ptf;*.sesx"),
                                     ("所有文件", "*.*")])
        if p:
            self.var_ptx.set(p)
            self.refresh_states()

    def _pick_json(self):
        p = self.ask_file("选择 pt-clips.json（交付包里的那份）",
                          initial=self.var_json.get(),
                          filetypes=[("PT 解析结果", "*.json"), ("所有文件", "*.*")])
        if p:
            self.var_json.set(p)
            self.refresh_states()

    def _pick_draft_dir(self):
        p = self.ask_dir("选择剪映草稿文件夹", initial=self.var_draft_dir.get())
        if p:
            self.var_draft_dir.set(p)
            self.refresh_states()

    def refresh_drafts(self):
        """从剪映默认草稿目录拉草稿列表填进下拉框。"""
        root = default_draft_root()
        self._drafts = list_drafts(root)
        names = [d.name for d in self._drafts]
        self.cmb_draft.configure(values=names)
        if names and not self.var_draft_dir.get().strip():
            self.var_draft_dir.set(str(root / names[0]))
        elif names:
            cur = Path(self.var_draft_dir.get().strip()).name
            if cur in names:
                self.var_draft_dir.set(str(root / cur))
        self.log(f"· 草稿目录：{root}\n· 发现 {len(names)} 个草稿"
                 f"{'：' + '、'.join(names[:8]) + ('…' if len(names) > 8 else '') if names else ''}\n")
        self.refresh_states()

    # ───────────── ① 解析 PT ─────────────

    def parse_pt(self):
        if self.running:
            return
        ptx = self.var_ptx.get().strip()
        if not ptx:
            messagebox.showwarning("缺少工程文件", "请先选择 .ptx 工程文件。")
            return
        # 这里是**用户点按钮时**的前置校验（低频、且此刻界面可以短暂无响应）：
        # 有意用同步实时探测而不是读缓存 —— 点了「解析」就该拿到确定结论，
        # 拿 5 秒前的缓存糊弄会导致「以为能解析，结果 PTSL 刚断」。
        # 高频路径（切页/选文件刷新门控）才必须用缓存，见 refresh_states。
        ok, msg = core.pro_tools_status()
        if not ok:
            messagebox.showerror("Pro Tools 不可用", msg)
            return

        out_dir = self._default_json_dir()
        self.var_json.set(str(out_dir / "pt-clips.json"))

        def job():
            import sys
            import pt_clip_scan
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
            args = _PTArgs(out=str(out_dir), name="pt-clips.json",
                           tracks="", exclude="")
            pt_clip_scan.run(args)

        def done(err):
            if err is None:
                p = out_dir / "pt-clips.json"
                if p.is_file():
                    self.var_json.set(str(p))
                    self.var_src.set(SRC_JSON)      # 解析完自动切到「用 json」路径
                    self._on_source_change()
                    self.log(f"\n✓ 解析完成，已切到「交付包 json」模式：{p}\n")
                    return
            self.log("\n✗ 解析失败，请确认：PT 已打开目标工程 / PTSL 已启用 / "
                     "py-ptsl 已安装。\n")
            self.refresh_states()

        self.run_async(job, on_done=done, btn=self.btn_parse, busy_text="解析中…")

    def _default_json_dir(self) -> Path:
        """解析结果的落点：优先用户指定的交付包输出目录，否则默认工作目录。"""
        pkg = self.cfg.get("import_pkg_out", "").strip()
        if pkg:
            p = Path(pkg)
        else:
            p = core.APP_DIR / "工作目录"
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            p = Path.cwd()
        return p

    # ───────────── ② 预演 / 导入 ─────────────

    def _exclude_args(self):
        ex_raw = self.var_exclude.get().strip()
        ex = [s.strip().lower() for s in re.split(r"[,，]", ex_raw) if s.strip()]
        keep = bool(self.var_keep_aux.get())
        if not ex and not keep:
            import import_audio
            ex = list(import_audio.DEFAULT_EXCLUDE)
        return tuple(ex)

    def preview(self):
        if self.running:
            return
        jp = Path(self.var_json.get().strip())
        if not jp.is_file():
            messagebox.showwarning("缺少数据源", "请先选择 pt-clips.json。")
            return
        ex = self._exclude_args()

        def job():
            import import_audio
            rows = import_audio.parse_pt_clips(jp, ex)
            print(f"\n数据源: {jp.name}")
            print(f"可用片段 {len(rows)} 个，涉及素材 "
                  f"{len({r['source'] for r in rows})} 个\n")
            if not rows:
                # v2.6.5（J7）：诊断细节由 parse_pt_clips 的 [diag] 段输出
                print("（预演不写任何文件）")
                return
            by_track = {}
            for r in rows:
                by_track.setdefault(r["_pt_track"], []).append(r)
            for tname, items in by_track.items():
                n_fade = sum(1 for i in items
                             if i.get("_fade_in_ms") or i.get("_fade_out_ms"))
                print(f"  轨 {tname:<26} 片段 {len(items):>3} 个"
                      f"{f'  含 fade {n_fade} 个' if n_fade else ''}")
            n_fade = sum(1 for r in rows if r.get("_fade_in_ms") or r.get("_fade_out_ms"))
            last = max((r["start_ms"] + int(r["duration_ms"]) for r in rows), default=0)
            print(f"\n合计：{len(by_track)} 条轨道 / {len(rows)} 个片段 / "
                  f"{n_fade} 个淡入淡出 / 时间线总长 {last/1000:.1f}s")
            print("（预演不写任何文件）")

        self.run_async(job, btn=self.btn_preview, busy_text="预演中…")

    def do_import(self):
        if self.running:
            return
        jp = Path(self.var_json.get().strip())
        draft = Path(self.var_draft_dir.get().strip())
        if not jp.is_file():
            messagebox.showwarning("缺少数据源", "请先选择 pt-clips.json。")
            return
        if not draft.is_dir():
            messagebox.showwarning("缺少目标", "请选择要写入的剪映草稿文件夹。")
            return
        # 最后一次拦截：用实时结果，不吃缓存（statusbar 的门控可以吃缓存，
        # 但真正落盘前必须确认剪映此刻确实没在跑）
        blockers, _warns = self._jy_state(draft, realtime=True)
        if blockers:
            messagebox.showerror(
                "剪映正在运行",
                "导入前必须【完全退出剪映】（含托盘图标与后台进程）。\n\n"
                "原因：剪映内存里持有草稿副本，退出时会用旧内容覆盖磁盘写入 —— "
                "结果就是「导入了但剪映里看不到变化」。\n\n"
                + "\n".join(blockers))
            return

        ex = self._exclude_args()
        self.save_config(quiet=True)

        def job():
            import sys
            import import_audio
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
            argv = ["import_audio.py", "--pt-clips", str(jp), str(draft)]
            if ex:
                argv += ["--exclude", ",".join(ex)]
            old = sys.argv
            sys.argv = argv
            try:
                import_audio.main()
            finally:
                sys.argv = old

        def done(err):
            if err is None:
                self.log("\n✓ 导入完成。请打开剪映确认轨道/片段/淡入淡出。\n")
            else:
                self.log(f"\n✗ 导入失败: {err}\n")
            self.refresh_states()

        self.run_async(job, on_done=done, btn=self.btn_import, busy_text="写入中…")


class _PTArgs:
    """pt_clip_scan.run() 需要的参数容器（避免为 GUI 改动其 argparse 定义）。"""

    def __init__(self, **kw):
        self.out = "."
        self.name = "pt-clips.json"
        self.tracks = ""
        self.exclude = ""
        self.__dict__.update(kw)
