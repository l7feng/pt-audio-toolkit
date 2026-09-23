# -*- coding: utf-8 -*-
"""视频名补录弹窗 —— 工具判断不出项目名时，让人一次性补齐。

触发条件（见 core/videoname.py）：
    ① 纯数字视频名（`17.mp4`）→ 通常是集数，缺项目名
    ② 项目名超过 4 个字（`法老的禁忌神谕 第10集`）→ 交付文件名会过长，要缩写

设计要点
--------
- **一次问完**：同名只问一次，答案回填到所有同名片段。
- **给默认值**：默认填「已解析出的项目名众数」或「缩写建议」，多数情况直接回车。
- **可以留空**：留空 = 该片段继续用原视频名当文件夹名，工具不猜。
- 返回 `None` = 用户取消（调用方应中止导出，而不是带着缺项跑）。
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional


def ask_video_projects(parent, infos, suggest: Optional[str] = None,
                       title: str = "补充视频项目信息") -> Optional[Dict[str, str]]:
    """弹窗补录项目名。

    | 参数 | 含义 |
    |---|---|
    | `parent` | 父窗口 |
    | `infos` | 待补的 `VideoNameInfo` 列表（已去重，一个原始名一条） |
    | `suggest` | 全局默认项目名（取自己解析出的众数），写进每个输入框 |

    返回 `{原始视频名: 项目名}`；取消返回 `None`。
    """
    if not infos:
        return {}

    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent)
    win.grab_set()
    win.resizable(True, True)
    win.geometry("760x420")

    result: Dict[str, str] = {}
    answered = {"ok": False}

    head = ("以下视频名无法自动判断**项目名**（工具不猜，交给您确认）：\n"
            "· 纯数字通常是集数，缺的是项目名；· 项目名超过 4 个字时建议填缩写。\n"
            "留空则沿用原视频名作为文件夹名。")
    ttk.Label(win, text=head, justify="left", wraplength=720).pack(
        anchor="w", padx=12, pady=(10, 6))

    # ── 表体（可滚动）──
    wrap = ttk.Frame(win)
    wrap.pack(fill="both", expand=True, padx=12, pady=4)
    canvas = tk.Canvas(wrap, highlightthickness=0)
    sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
    body = ttk.Frame(canvas)
    body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    ttk.Label(body, text="视频名", font=("Microsoft YaHei UI", 9, "bold")).grid(
        row=0, column=0, sticky="w", padx=4, pady=2)
    ttk.Label(body, text="已识别", font=("Microsoft YaHei UI", 9, "bold")).grid(
        row=0, column=1, sticky="w", padx=4, pady=2)
    ttk.Label(body, text="项目名（请填）", font=("Microsoft YaHei UI", 9, "bold")).grid(
        row=0, column=2, sticky="w", padx=4, pady=2)

    vars_: List[tk.StringVar] = []
    default = suggest or ""
    for r, info in enumerate(infos, start=1):
        known = []
        if info.ep:
            known.append("第%s集" % info.ep)
        if info.seq:
            known.append("编号%s" % info.seq)
        if info.aifx:
            known.append("AiFX")
        ttk.Label(body, text=info.raw, wraplength=280, justify="left").grid(
            row=r, column=0, sticky="w", padx=4, pady=3)
        ttk.Label(body, text="/".join(known) or "—", foreground="#888").grid(
            row=r, column=1, sticky="w", padx=4, pady=3)
        v = tk.StringVar(value=info.suggest or default)
        vars_.append(v)
        ttk.Entry(body, textvariable=v, width=24).grid(
            row=r, column=2, sticky="we", padx=4, pady=3)
        ttk.Label(body, text=info.reason, foreground="#a86").grid(
            row=r, column=3, sticky="w", padx=4, pady=3)
    body.columnconfigure(2, weight=1)

    # ── 按钮 ──
    def _fill_all():
        first = vars_[0].get().strip() if vars_ else ""
        if not first:
            return
        for v in vars_:
            v.set(first)

    def _ok():
        for info, v in zip(infos, vars_):
            result[info.raw] = v.get().strip()
        answered["ok"] = True
        win.destroy()

    def _cancel():
        win.destroy()

    btn = ttk.Frame(win)
    btn.pack(fill="x", padx=12, pady=(6, 10))
    ttk.Button(btn, text="把第一行填到全部", command=_fill_all).pack(side="left", padx=4)
    ttk.Label(btn, text="（同一项目的多个视频，填一次即可）",
              foreground="#888").pack(side="left", padx=4)
    ttk.Button(btn, text="取消", command=_cancel).pack(side="right", padx=4)
    ttk.Button(btn, text="确定", command=_ok).pack(side="right", padx=4)

    win.protocol("WM_DELETE_WINDOW", _cancel)
    win.wait_window()
    return result if answered["ok"] else None
