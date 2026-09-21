#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剪映多轨音频导入器 — M2.5（PT 工程翻译器）
============================================
把 Pro Tools 工程解析结果（pt-clips.json，由 pt_clip_scan.py 生成）批量导入剪映草稿：
素材注册 + 轨道建立（按 PT 轨道顺序）+ 片段落位（真实起止/时长）+ 淡入淡出 + 音量。

技术路线（与 31 号共用底座）：
  解密(jy-draftc -d) -> 修改 JSON -> 回加密(jy-draftc -e) -> 覆盖草稿文件

数据源二选一：
  1) --pt-clips pt-clips.json   推荐：PT 解析结果（含真实时长/fade，修复 M2 的 3 个 bug）
  2) 清单.csv                    兼容旧流程：CSV 清单（手工维护）

修复的 3 个 M2 bug：
  - Bug A 时长错：用 PT clip 的真实起点/长度（而非音频文件总时长）
  - Bug B 淡入淡出丢：写 audio_fades（PT 的 (淡入)/(淡出) 事件）
  - Bug C 轨道错位：按 PT 轨道真实顺序建轨，不再依赖手工 track_no

用法：
  python import_audio.py --pt-clips out/pt-clips.json "草稿目录"
  python import_audio.py --pt-clips out/pt-clips.json "草稿目录" --dry-run
  python import_audio.py 清单.csv "草稿目录"                       # 旧 CSV 模式
  python import_audio.py --pt-clips out/pt-clips.json "草稿目录" --exclude "Verb,Dly,BUS"

M3 时长延长（目标时长 > 源文件时长时）：
  循环延长（默认）：多段引用同一素材顺延时间码，交界处交叉淡化（默认 200ms）
  变速延长（实验）：单段变速，写真实 speed 素材（speed = 可用源长/目标长）
  python import_audio.py --pt-clips … "草稿目录" --extend "素材名=目标毫秒:loop"
  python import_audio.py --pt-clips … "草稿目录" --extend "素材名=目标毫秒:stretch"
  也可把 target_ms / extend_mode 直接写进 pt-clips.json 的 clip 条目（随交付包走）。
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

# ---------- 常量 ----------
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DRAFTC = Path(r"D:\Ai-Files\Agent-Preset\Skills\my-skills\jianying-audio-exporter\tools\jy-draftc\jy-draftc-amd64-windows\jy-draftc.exe")

# 类别前缀 -> 素材 type（剪映 audios 素材 type 枚举）
CATEGORY_MAP = {
    "MX": "music", "BGM": "music", "MUSIC": "music",
    "DX": "record", "VO": "record", "VOCAL": "record", "REC": "record",
    "FX": "sound", "SFX": "sound", "EFF": "sound", "FOL": "sound",
    "AMB": "sound", "BG": "sound",
}
DEFAULT_MAT_TYPE = "music"

# 片段挂接的占位素材分类（对齐本机真实草稿实测：audio 段 5 件套）
PLACEHOLDER_CATS = [
    "speeds",
    "placeholder_infos",
    "beats",
    "sound_channel_mappings",
    "vocal_separations",
]

# 默认排除的辅助轨关键词（总线/效果发送/混响辅助，非内容轨）
# 注意：用「词边界」匹配，避免 "Audio FX ST"（含 aux 子串）被误伤
DEFAULT_EXCLUDE = ("vca", "verb", "dly", "bus", "delay", "reverb", "master")


# ---------- 工具 ----------
def new_id() -> str:
    return str(uuid.uuid4()).upper()


def ffprobe_duration_ms(path: Path) -> int:
    """用 ffprobe 读取音频真实时长（毫秒）"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, **subprocess_kwargs(),)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {r.stderr.strip()}")
    return int(round(float(r.stdout.strip()) * 1000))


def wav_duration_ms(path: Path) -> int:
    """用标准库 wave 读 wav 时长（毫秒），避免依赖 ffprobe。"""
    import wave
    with wave.open(str(path), "rb") as w:
        return int(round(w.getnframes() / w.getframerate() * 1000))


def probe_duration_ms(path: Path) -> int:
    """优先用 wave（wav 文件，零依赖），失败回退 ffprobe。"""
    if path.suffix.lower() == ".wav":
        try:
            return wav_duration_ms(path)
        except Exception:
            pass
    return ffprobe_duration_ms(path)


def decrypt_file(draftc: Path, target: Path) -> Path:
    r = subprocess.run([str(draftc), "-d", str(target)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120, **subprocess_kwargs(),)
    if r.returncode != 0 or "ok" not in r.stdout:
        raise RuntimeError(f"jy-draftc 解密失败: {r.stdout} {r.stderr}")
    return target.with_suffix(target.suffix + ".dec.json")


def encrypt_file(draftc: Path, dec_file: Path) -> Path:
    r = subprocess.run([str(draftc), "-e", str(dec_file)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120, **subprocess_kwargs(),)
    if r.returncode != 0 or "ok" not in r.stdout:
        raise RuntimeError(f"jy-draftc 回加密失败: {r.stdout} {r.stderr}")
    return Path(str(dec_file) + ".enc.json")


# ---------- 草稿文件定位（剪映「双份草稿」结构） ----------
# 本机剪映（6.x）草稿是「两份 + 多时间线」结构：
#   <草稿>/draft_content.json                        ← 会话快照（旧的兼容槽）
#   <草稿>/Timelines/project.json                    ← 明文，含 main_timeline_id
#   <草稿>/Timelines/<main_timeline_id>/draft_content.json   ← ★剪映实际读取的内容
# 只写根目录 -> 剪映仍显示时间线目录里的旧内容（2026-09-17 实测踩坑）。
# 正确做法：以「时间线目录那份」为权威 base，改完同时写回两份。
def read_main_timeline_id(draft_dir: Path):
    pj = draft_dir / "Timelines" / "project.json"
    if not pj.is_file():
        return None
    try:
        return json.loads(pj.read_text(encoding="utf-8")).get("main_timeline_id")
    except Exception:
        return None


def resolve_content_files(draft_dir: Path):
    """返回 (权威读取文件, 需要同步写入的全部文件列表, 说明文本)。"""
    root = draft_dir / "draft_content.json"
    tl_root = draft_dir / "Timelines"
    tl_files = []
    if tl_root.is_dir():
        for n in sorted(os.listdir(tl_root)):
            d = tl_root / n
            if d.is_dir() and (d / "draft_content.json").is_file():
                tl_files.append(d / "draft_content.json")

    main_id = read_main_timeline_id(draft_dir)
    authoritative, note = None, ""
    if main_id:
        cand = tl_root / main_id / "draft_content.json"
        if cand.is_file():
            authoritative = cand
            note = f"main_timeline_id={main_id[:8]}…（时间线目录为权威源）"
    if authoritative is None and len(tl_files) == 1:
        authoritative = tl_files[0]
        note = "唯一时间线目录为权威源（project.json 无 main_timeline_id）"
    if authoritative is None:
        authoritative = root if root.is_file() else (tl_files[0] if tl_files else None)
        note = "回退为根目录为权威源（未发现 Timelines 结构）"

    targets = []
    if root.is_file():
        targets.append(root)
    for f in tl_files:
        if f not in targets:
            targets.append(f)
    if not targets and authoritative is not None:
        targets = [authoritative]
    return authoritative, targets, note


# 探测逻辑已收敛到 core/host.py（L0 卡顿修复 + 分层起点）。
# 此处保留同名引用，确保 tab / GUI（import_audio.jianying_running）行为不变。
from core.host import jianying_running, jianying_running_realtime, subprocess_kwargs


def tc_to_ms(tc: str, fps: int, start_tc: str = "00:00:00:00") -> int:
    """timecode(时:分:秒:帧) -> 毫秒；减去工程起始时码。"""
    import re
    def to_frames(t):
        m = re.match(r"(\d+):(\d+):(\d+)[:;](\d+)", t)
        if not m:
            return 0
        h, mi, s, f = (int(x) for x in m.groups())
        return ((h * 60 + mi) * 60 + s) * fps + f
    return int(round((to_frames(tc) - to_frames(start_tc)) / fps * 1000))


# ---------- 数据源 1：PT 解析结果 ----------
def _word_match(name: str, keywords) -> str:
    """按「词」匹配排除关键词，避免子串误伤（如 'Audio FX ST' 不因 'aux' 被排）。

    规则：关键词作为独立词出现（前后是空格/开头/结尾或 . - _）才命中。
    """
    import re
    low = name.lower()
    for k in keywords:
        if re.search(r"(?:^|[\s._\-])" + re.escape(k) + r"(?:$|[\s._\-])", low):
            return k
    return ""


def _src_offset_ms(clip_start_ms: int, src_dur_ms: int, clip_dur_ms: int,
                   multi_ref: bool) -> int:
    """推导 clip 在源文件内的起始偏移（剪映 source_timerange.start）。

    背景（2026-09-17 实测确定，这是「时长对不上」的真正根因）：
      PT 的 ExportSessionInfoAsText **只给时间线起止与长度，没有源内偏移列**。
      已排除的只读替代路径：GetClipList 明细返回空、GetTrackPlaylists /
      GetPlaylistElements 本机 PT 报 ErrType 133 不支持、文本导出加开关无该列、
      PTSL 的 ExportSelectedTracksAsAAFOMF 在本机 PT 25.6.1 稳定断言失败
      （PtSess_AAFGeneric.cpp:311，单轨/多轨/ASCII/中文路径全复现）。

    推导规则（女帝22 实测归纳，两类素材语义不同）：
      A) 「多引用长轨素材」（如 1.L.wav 318.9s 被切 4 段、2.L.wav 切 8 段、
         3.L.wav 切 11 段）：多段在时间线上首尾相接、单调递增且不重叠，说明
         素材是从 0 顺着时间线铺开的 → 源内偏移 == 时间线起点。
      B) 「单引用短音效」（如 71寻找.L.wav 18.3s 摆在时间线 85.2s）：时间线
         起点远超素材长度，若直接当源偏移必然越界 → 只能从源文件开头取
         （start=0），保证「位置准 + 时长准 + 内容够长」。
      超界时的兜底：任何情况下都夹住到「源时长 - 片段时长」，绝不越界。
    """
    if src_dur_ms <= 0:
        return 0
    off = clip_start_ms if multi_ref else 0
    max_off = max(0, src_dur_ms - clip_dur_ms)
    if off > max_off:
        off = max_off
    return max(0, off)


def _merge_stereo(l_path: Path, r_path: Path, cache_dir: Path) -> Path:
    """把独立的 L/R 单声道 wav 合成一个双声道立体声 wav（缓存复用）。

    PT 的 Audio Files 里同一素材常以「X.L.wav + X.R.wav」两个单声道文件存在。
    剪映一个 audio segment 只能挂一个素材文件，若只取 .L 会丢掉右声道，
    因此这里用标准库 wave 做一次无损拼接（同采样率/位深，直接交错写入）。

    返回合成后的立体声文件路径；失败则回退返回 l_path。
    """
    import wave
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        rel = l_path.stem
        out = cache_dir / f"{rel}.stereo.wav"
        if out.is_file() and out.stat().st_mtime_ns >= max(
                l_path.stat().st_mtime_ns, r_path.stat().st_mtime_ns):
            return out
        with wave.open(str(l_path), "rb") as wl:
            nl, sw, fr, nf = wl.getnchannels(), wl.getsampwidth(), wl.getframerate(), wl.getnframes()
            ldata = wl.readframes(nf)
        with wave.open(str(r_path), "rb") as wr:
            nr, sw2, fr2, nf2 = wr.getnchannels(), wr.getsampwidth(), wr.getframerate(), wr.getnframes()
            rdata = wr.readframes(nf2)
        if sw != sw2 or fr != fr2 or nl != 1 or nr != 1:
            return l_path
        n = min(nf, nf2)
        frame_bytes = sw
        ldata = ldata[:n * frame_bytes]
        rdata = rdata[:n * frame_bytes]
        inter = bytearray()
        # 交错：L0 R0 L1 R1 ...
        for i in range(n):
            s = i * frame_bytes
            inter += ldata[s:s + frame_bytes]
            inter += rdata[s:s + frame_bytes]
        with wave.open(str(out), "wb") as wo:
            wo.setnchannels(2)
            wo.setsampwidth(sw)
            wo.setframerate(fr)
            wo.writeframes(bytes(inter))
        return out
    except Exception as e:
        print(f"[warn] 立体声合成失败 {l_path.name}: {e}")
        return l_path


def resolve_audio_dir(json_path: Path, doc: dict, override: Path | None = None) -> Path | None:
    """定位素材目录。优先级：
    1. 显式 `--audio-dir` 覆盖；
    2. json 同级的 `audio/` 子目录（交付包形态：json + audio/ 一起发给剪辑）；
    3. json 里 `online_files` 记录的原始 location（本机自用时可用）。

    交付包场景下剪辑机器上没有原始路径，靠第 2 条即可离线工作。
    """
    if override is not None:
        return override
    # 交付包形态：json 放在包根，音频在同级 audio/
    for cand in (json_path.parent / "audio", json_path.parent):
        if cand.is_dir() and any(cand.glob("*.wav")):
            return cand
    if doc.get("online_files"):
        p = Path(doc["online_files"][0]["location"])
        if p.is_dir():
            return p
    return None


def parse_pt_clips(json_path: Path, exclude: tuple = (),
                   verbose: bool = True, audio_dir: Path | None = None) -> list[dict]:
    """把 pt-clips.json 转成统一的行列表（一行为一个 clip）。

    PT 导出中每个 clip 按声道（L/R）分行，这里按「时间码 + 名称去声道后缀」合并为单行。
    素材文件用 clip_file_map（片段名 -> 文件名）解析，比猜测命名规则可靠。
    每个 clip 附带 _src_offset_ms（源内偏移），由 _src_offset_ms() 推导。

    `audio_dir` 非空时覆盖素材目录 —— 这是「离线/跨设备」的关键：剪辑机器上
    没有 PT 原始路径，只要把音频放在 json 同级的 audio/ 目录即可正常工作。
    """
    d = json.loads(json_path.read_text(encoding="utf-8"))
    session = d.get("session", {})
    fps = int(session.get("fps") or 25)
    raw = session.get("raw_summary", {}) or {}
    start_tc = raw.get("工程起始时间码", "00:00:00:00")
    clip_file_map = d.get("clip_file_map", {}) or {}
    files_dir = resolve_audio_dir(json_path, d, audio_dir)
    online_names = {f["name"] for f in d.get("online_files", [])}
    # 交付包标志：json 自带 `_delivery_package` 段，或素材目录被解析到 json 同级。
    # 此时不做「在线文件清单校验」—— 包内文件名已规范化（如 L/R 合成件），
    # 与原始清单必然不同，强行校验会导致全部素材被误挡。
    is_delivery = bool(d.get("_delivery_package")) or (
        files_dir is not None and audio_dir is None
        and files_dir.parent == json_path.parent)
    # 立体声合成缓存：优先放 json 同级的 audio/_stereo_cache（交付包场景，剪辑机器上
    # 临时目录可能被清理），否则回落系统临时目录。
    import tempfile
    if files_dir is not None and audio_dir is not None:
        stereo_cache = files_dir / "_stereo_cache"
    else:
        stereo_cache = Path(tempfile.gettempdir()) / "jy_audio_import_stereo"

    # 统计每个素材文件被引用的次数（推导源偏移要用）
    ref_count = {}
    for _t in d.get("tracks", []):
        for _c in _t.get("clips", []):
            _fn = clip_file_map.get(_c["name"])
            if _fn:
                ref_count[_fn] = ref_count.get(_fn, 0) + 1

    # PT 权威轨道顺序（GetTrackList 的 index）与格式（1=Mono / 2=Stereo）
    meta_by_name = {m["name"]: m for m in (d.get("track_meta") or [])}
    # 纯 Aux/VCA 等非音频内容轨（用于 --keep-aux 之外的默认跳过）
    NON_AUDIO_TYPES = {3, 5, 12, 14, 15}  # Aux / Vca / Master / BasicFolder / RoutingFolder

    def resolve_file(clip_name: str):
        """片段名 -> 素材文件 Path。优先用映射表，再按常见规则回退。"""
        if not files_dir:
            return None
        cand_names = []
        if clip_name in clip_file_map:
            cand_names.append(clip_file_map[clip_name])
        # 回退：去声道后缀 / 去 -NN 序号 后组合
        base = clip_name
        for suf in (".L", ".R"):
            if base.endswith(suf):
                base = base[:-len(suf)]
                break
        import re as _re
        base2 = _re.sub(r"-\d{2}$", "", base)
        for b in (base, base2):
            for suf in (".L.wav", ".R.wav", ".wav"):
                cand_names.append(b + suf)
        seen = set()
        for n in cand_names:
            if n in seen:
                continue
            seen.add(n)
            # 本机自用时按在线文件清单校验（防误命中同名无关文件）；
            # 交付包场景文件名可能被规范化（含 L/R 合成件），不做该校验。
            if online_names and not is_delivery and n not in online_names:
                continue
            p = files_dir / n
            if p.is_file():
                return p
        return None

    rows = []
    skipped_tracks = []
    for t in d.get("tracks", []):
        tname = t.get("name", "")
        if not t.get("clips"):
            continue
        hit = _word_match(tname, exclude) if exclude else ""
        if hit:
            skipped_tracks.append((tname, hit))
            continue

        grouped = {}
        for c in t["clips"]:
            nm = c["name"]
            base = nm
            for suf in (".L", ".R", ".l", ".r"):
                if base.endswith(suf):
                    base = base[:-len(suf)]
                    break
            key = (c["start"], c["end"], base)
            if key not in grouped:
                grouped[key] = {"start": c["start"], "end": c["end"],
                                "name": base, "raw_name": nm, "channels": []}
            grouped[key]["channels"].append(c)

        for key, g in sorted(grouped.items()):
            start_ms = tc_to_ms(g["start"], fps, start_tc)
            end_ms = tc_to_ms(g["end"], fps, start_tc)
            dur_ms = end_ms - start_ms
            if dur_ms <= 0:
                continue
            src = resolve_file(g["raw_name"]) or resolve_file(g["name"])
            if src is None:
                print(f"[warn] 找不到素材文件: {g['raw_name']}  (轨 {tname})，跳过")
                continue
            # L/R 双单声道 -> 合成立体声（否则丢一个声道）
            src_name = clip_file_map.get(g["raw_name"]) or src.name
            if src.name.endswith(".L.wav"):
                r_src = src.with_name(src.name[:-6] + ".R.wav")
                if r_src.is_file():
                    merged = _merge_stereo(src, r_src, stereo_cache)
                    if merged != src:
                        src_name = merged.name
                    src = merged
            is_multi = ref_count.get(clip_file_map.get(g["raw_name"]) or "", 1) > 1
            try:
                src_dur_ms = probe_duration_ms(src)
            except Exception:
                src_dur_ms = 0
            src_off_ms = _src_offset_ms(start_ms, src_dur_ms, dur_ms, is_multi)
            if is_multi and src_off_ms + dur_ms > src_dur_ms + 50:
                print(f"[warn] {src_name}: 源偏移裁剪 "
                      f"({start_ms}ms -> {src_off_ms}ms)，片段仍将完整落位")
            row = {
                "source": src,
                "track_no": len(rows) + 1,
                "track_name": tname,
                "start_ms": start_ms,
                "duration_ms": str(dur_ms),
                "volume_db": 0.0,
                "remark": "",
                "_pt_track": tname,
                "_pt_index": (meta_by_name.get(tname) or {}).get("index"),
                "_pt_fmt": (meta_by_name.get(tname) or {}).get("format"),
                "_pt_clip_name": g["name"],
                "_src_name": src_name,
                "_src_dur_ms": src_dur_ms,
                "_src_offset_ms": src_off_ms,
                "_multi_ref": is_multi,
            }
            # M3：clip 条目可内嵌延长覆盖（随 json/交付包走，无需命令行）
            _c0 = g["channels"][0]
            _cm = _c0.get("target_ms") or _c0.get("extend_ms")
            _em = str(_c0.get("extend_mode") or "").strip().lower()
            if _cm:
                row["_target_ms"] = int(_cm)
            if _em in ("loop", "stretch"):
                row["_extend_mode"] = _em
            rows.append(row)

    # 按 PT 轨道顺序 + 时间线起点排序（保证剪映轨道顺序与 PT 一致）
    rows.sort(key=lambda r: (r.get("_pt_index") if r.get("_pt_index") is not None
                             else 10 ** 6, r["start_ms"]))
    for i, r in enumerate(rows, start=1):
        r["track_no"] = i

    if skipped_tracks:
        print(f"[info] 已排除辅助轨 {len(skipped_tracks)} 条：")
        for nm, k in skipped_tracks:
            print(f"    - {nm}  (命中 '{k}')")

    fade_map = _collect_fades(d, fps, start_tc)
    for row in rows:
        f = fade_map.get((row["_pt_track"], row["start_ms"]))
        if f:
            row["_fade_in_ms"] = f.get("in", 0)
            row["_fade_out_ms"] = f.get("out", 0)
    return rows


def _collect_fades(d: dict, fps: int, start_tc: str) -> dict:
    """把 (淡入)/(淡出) 事件映射到 (轨道, clip起点ms) -> {in,out}。

    规则：淡出事件的起点紧邻前一个 clip 的终点 → 记为该 clip 的淡出；
         淡入事件紧邻后一个 clip 的起点 → 记为其淡入。
    """
    out = {}
    for t in d.get("tracks", []):
        tname = t.get("name", "")
        clips = sorted(t.get("clips", []),
                       key=lambda c: (c.get("start", ""), c.get("channel", 0)))
        fades = t.get("fades", [])
        for f in fades:
            fname = f["name"]
            fstart = tc_to_ms(f["start"], fps, start_tc)
            fend = tc_to_ms(f["end"], fps, start_tc)
            flen = max(0, fend - fstart)
            if "淡出" in fname:
                # 找终点 == 该淡出起点的 clip
                for c in clips:
                    if tc_to_ms(c["end"], fps, start_tc) == fstart:
                        k = (tname, tc_to_ms(c["start"], fps, start_tc))
                        out.setdefault(k, {})["out"] = flen
                        break
            elif "淡入" in fname:
                for c in clips:
                    if tc_to_ms(c["start"], fps, start_tc) == fend:
                        k = (tname, tc_to_ms(c["start"], fps, start_tc))
                        out.setdefault(k, {})["in"] = flen
                        break
    return out


# ---------- 数据源 2：CSV 清单（兼容旧流程）----------
def parse_manifest(csv_path: Path) -> list[dict]:
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for i, rec in enumerate(csv.DictReader(f), start=2):
            if not rec.get("source") or not rec["source"].strip():
                continue
            src = Path(rec["source"].strip())
            if not src.is_file():
                raise RuntimeError(f"第 {i} 行：源文件不存在 {src}")
            track_no = int(rec.get("track_no") or 0)
            if track_no < 1:
                raise RuntimeError(f"第 {i} 行：track_no 必须 >= 1，实际 {track_no}")
            rows.append({
                "source": src,
                "track_no": track_no,
                "track_name": (rec.get("track_name") or "").strip(),
                "start_ms": int((rec.get("start_ms") or "0").strip() or 0),
                "duration_ms": (rec.get("duration_ms") or "").strip(),
                "volume_db": float((rec.get("volume_db") or "0").strip() or 0),
                "remark": (rec.get("remark") or "").strip(),
            })
    if not rows:
        raise RuntimeError("清单为空或列名不匹配（需含 source/track_no 列）")
    return rows


# ---------- 素材与片段构造 ----------
def make_audio_material(path: Path, duration_ms: int, mat_type: str) -> dict:
    return {
        "id": new_id(),
        "type": mat_type,
        "name": path.stem,
        "duration": duration_ms * 1000,
        "path": path.as_posix(),
        "resource_id": "",
        "local_material_id": str(uuid.uuid4()).lower(),
        "similiar_music_info": {},
        "tts_benefit_info": {"benefit_type": "none"},
        "_jy_import": True,   # 幂等标记
    }


def make_fade(fade_in_ms: int = 0, fade_out_ms: int = 0) -> dict:
    return {
        "id": new_id(),
        "type": "audio_fade",
        "fade_in_duration": fade_in_ms * 1000,
        "fade_out_duration": fade_out_ms * 1000,
        "fade_in_curve": 0,
        "fade_out_curve": 0,
        "_jy_import": True,   # 幂等标记
    }


def make_speed_material(speed: float) -> dict:
    """构造真实变速素材（M3 stretch 模式）。

    与占位 speeds（仅 {id, type}）不同，真实变速需要 mode/speed 字段：
      - mode "Speed" = 常规匀速变速（区别于曲线变速 CurvedSpeed）
      - speed = 源时长 / 目标时长（>1 加速变短，<1 减速变长）
    关系约束：segment 的 target_timerange.duration == source_timerange.duration / speed。
    ⚠️ 音调是否变化（变调/不变调）待剪映内实测确认 —— 这是 M3 实验目的。
    """
    return {
        "id": new_id(),
        "type": "speed",
        "mode": "Speed",
        "speed": round(speed, 6),
        "category_name": "常规",
        "_jy_import": True,   # 幂等标记
    }


def make_placeholder(cat: str) -> dict:
    """构造 segment 的占位附属素材（剪映 audio 片段固定 5 件套）。

    必须带 `_jy_import` 标记 —— 否则 `_purge_previous()` 清不掉，重跑会累积
    （2026-09-17 实测：38 片段 × 5 件套 = 190 条/次，草稿体积不断膨胀）。
    """
    if cat == "speeds":
        d = {"id": new_id(), "type": "speed"}
    elif cat == "placeholder_infos":
        d = {"id": new_id(), "type": "placeholder_info", "meta_type": "none"}
    elif cat == "beats":
        d = {"id": new_id(), "type": "beats", "ai_beats": {"melody_percents": [0.6]}}
    elif cat == "sound_channel_mappings":
        d = {"id": new_id(), "type": "none"}
    elif cat == "vocal_separations":
        d = {"id": new_id(), "type": "vocal_separation"}
    else:
        raise ValueError(cat)
    d["_jy_import"] = True
    return d


def category_prefix_type(track_name: str) -> str:
    up = track_name.upper()
    for prefix, t in CATEGORY_MAP.items():
        if up.startswith(prefix) or prefix in up:
            return t
    return DEFAULT_MAT_TYPE


def make_segment(mat_id: str, target_start_us: int, dur_us: int, track_idx: int,
                 src_off_us: int = 0, src_dur_us: int | None = None) -> dict:
    """构造 audio segment。

    source_timerange = 从素材内的哪一段取（start=源内偏移，duration=取多长）
    target_timerange = 放到时间线的哪个位置（start=时间线位置，duration=多长）
    普通片段二者 duration 必须相等，否则剪映会拉伸或截断（M2「时长对不上」根因）；
    变速片段（M3 stretch）例外：传 src_dur_us 使二者解耦，时长差由 speed 素材表达。
    """
    src_dur = src_dur_us if src_dur_us is not None else dur_us

    def trange(start: int, duration: int) -> dict:
        return {"duration": duration} if start == 0 else {"start": start, "duration": duration}
    return {
        "id": new_id(),
        "source_timerange": trange(src_off_us, src_dur),
        "target_timerange": trange(target_start_us, dur_us),
        "render_timerange": {},
        "material_id": mat_id,
        "extra_material_refs": [],
        "enable_lut": False,
        "enable_adjust": False,
        "enable_hsl": False,
        "track_render_index": track_idx,
        "responsive_layout": {},
        "enable_adjust_mask": False,
        "source": "segmentsourcenormal",
    }


def _plan_loop_rows(row: dict, target_ms: int, crossfade_ms: int = 200) -> list[dict]:
    """M3 循环延长：把一行拆成 N 个首尾交叉衔接的子行（引用同一素材）。

    几何关系（f = 交叉淡化时长，avail = 源内可用长度 = src_dur - src_off）：
      每段播放源 [src_off, src_off + d_i]，相邻段在时间线上重叠 f：
        第 i 段起点 = 起点 + i * step，其中 step = avail - f（每段净推进）
        前 n-1 段 d_i = avail（整段可用），末段 d_n = target - (n-1)*step
      总覆盖 = (n-1)*step + d_n = target，恰好等于目标时长。
    交界处：前段 fade_out(f) + 后段 fade_in(f) = 真交叉淡化（无爆音、无空洞）。
    段内原有的 PT fade 保留在首段（淡入）与末段（淡出）。
    """
    src_dur = int(row.get("_src_dur_ms") or 0)
    src_off = int(row.get("_src_offset_ms") or 0)
    avail = max(0, src_dur - src_off)
    if avail < 1000:
        raise RuntimeError(
            f"{row['source'].name}: 可用素材仅 {avail}ms，无法循环延长（需 >=1s）；"
            f"请改用 :stretch 变速延长")
    f = max(0, min(int(crossfade_ms), avail // 4))
    step = avail - f
    if step < 500:
        raise RuntimeError(
            f"{row['source'].name}: 交叉淡化后步长仅 {step}ms，无法循环延长")

    n = max(1, -(-target_ms // step))          # ceil
    last = target_ms - (n - 1) * step
    if last <= 0:                              # 恰好整除时的兜底
        n -= 1
        last = target_ms - (n - 1) * step

    fi0 = int(row.get("_fade_in_ms") or 0)
    fo0 = int(row.get("_fade_out_ms") or 0)
    base = row["start_ms"]
    pieces = []
    for i in range(n):
        d = avail if i < n - 1 else last
        r = dict(row)
        r["start_ms"] = base + i * step
        r["duration_ms"] = str(int(d))
        r["_fade_in_ms"] = min(f if i > 0 else fi0, d)
        r["_fade_out_ms"] = min(f if i < n - 1 else fo0, d)
        r["_loop_piece"] = (i + 1, n)
        pieces.append(r)
    return pieces


def apply_extends(rows: list[dict], specs, default_mode: str = "loop") -> list[dict]:
    """把 --extend 命令行覆盖落到行上（子串匹配片段名或素材文件名，大小写不敏感）。"""
    for spec in specs:
        if "=" not in spec:
            raise RuntimeError(f"--extend 格式应为 名称=目标毫秒[:loop|stretch]，实际: {spec}")
        head, rest = spec.split("=", 1)
        mode = str(default_mode).lower()
        if ":" in rest:
            rest, mode = rest.rsplit(":", 1)
            mode = mode.strip().lower()
        if mode not in ("loop", "stretch"):
            raise RuntimeError(f"--extend 模式只能是 loop 或 stretch，实际: {mode}")
        try:
            tgt = int(rest)
        except ValueError:
            raise RuntimeError(f"--extend 目标时长必须是毫秒整数，实际: {rest}")
        name = head.strip().lower()
        hit = [r for r in rows
               if name in str(r.get("_pt_clip_name") or "").lower()
               or name in r["source"].stem.lower()
               or name in r["source"].name.lower()]
        if not hit:
            cand = sorted({r["source"].stem for r in rows})[:8]
            raise RuntimeError(
                f"--extend 未匹配到任何片段: '{head}'；可匹配的素材名示例: {cand} …")
        if len(hit) > 1:
            print(f"[warn] '{head}' 命中 {len(hit)} 个片段，将全部延长为 {tgt}ms ({mode})")
        for r in hit:
            r["_target_ms"] = tgt
            r["_extend_mode"] = mode
        print(f"[info] 延长覆盖: '{head}' -> {tgt}ms ({mode})，命中 {len(hit)} 个片段")
    return rows


# ---------- 主流程 ----------
def _purge_previous(all_tracks: list, mats: dict, verbose: bool = True,
                    pt_track_names: set | None = None) -> int:
    """清空草稿里上一次导入的痕迹，保证工具可重复运行（幂等）。

    两条判据，任一命中即视为本工具的产物：
    1. `_jy_import` 标记（新版本写入的轨道/素材带此标记，最可靠）；
    2. 兼容旧产物（无标记）：audio 轨且轨名命中本次 PT 轨道名集合 —— 这些轨只可能是
       上一次本工具导入留下的（草稿模板自带的 video 轨 name 为 None，不会误伤）。
    素材同理：path 位于「本次 PT 在线文件目录」之下的 audio 素材即本工具注册的。
    """
    pt_track_names = pt_track_names or set()
    # 模板自带的占位轨名（剪映新建草稿时预置，非用户内容）：导入是「翻译 PT 工程」，
    # 这些占位轨会残留成 4 条空壳，须一并清掉。
    TEMPLATE_STUBS = {"DX-对白", "BGM-音乐", "FX-音效", "人声", "音乐", "音效", "对白"}
    removed_tracks, kept = 0, []
    for t in all_tracks:
        if t.get("_jy_import"):
            removed_tracks += 1
            continue
        tname = t.get("name")
        is_audio = t.get("type") == "audio"
        if is_audio and tname and tname in pt_track_names and t.get("segments"):
            # 旧产物：轨名与本次 PT 轨名完全一致（旧版不做 -2 后缀时才成立）
            removed_tracks += 1
            continue
        if is_audio and not t.get("segments") and (tname is None or tname in TEMPLATE_STUBS):
            # 模板占位空轨：无片段 + 无名或模板名
            removed_tracks += 1
            continue
        if is_audio and t.get("segments") and (tname is None or tname in TEMPLATE_STUBS):
            # 模板占位轨但被剪映塞过内容（如 129.8s 整条占位）：同样视为模板残留
            removed_tracks += 1
            continue
        kept.append(t)
    if removed_tracks:
        all_tracks[:] = kept

    # 清理带标记的素材与辅助表
    for cat in ("audios", "audio_fades", "placeholder_infos", "speeds",
                "beats", "sound_channel_mappings", "vocal_separations"):
        arr = mats.get(cat)
        if isinstance(arr, list) and arr:
            mats[cat] = [x for x in arr if not (isinstance(x, dict) and x.get("_jy_import"))]

    # 孤儿清理：全部素材表统一按「是否仍被保留的 segment 引用」判定。
    # 适用 audios + 五件套占位表（placeholder_infos/speeds/beats/
    # sound_channel_mappings/vocal_separations）——它们由 segment 的
    # extra_material_refs 间接引用，模板残留或旧版无标记产物都会成为孤儿。
    if removed_tracks:
        used_ids = set()
        for t in all_tracks:
            for s in t.get("segments", []):
                if s.get("material_id"):
                    used_ids.add(s["material_id"])
                for r in s.get("extra_material_refs", []) or []:
                    used_ids.add(r)
        for cat in ("audios", "audio_fades", "placeholder_infos", "speeds",
                    "beats", "sound_channel_mappings", "vocal_separations"):
            arr = mats.get(cat)
            if isinstance(arr, list) and arr:
                before = len(arr)
                mats[cat] = [x for x in arr if isinstance(x, dict) and x.get("id") in used_ids]
                dropped = before - len(mats[cat])
                if verbose and dropped:
                    print(f"[info] 已清除 {dropped} 条孤儿 {cat}")

    if verbose and removed_tracks:
        print(f"[info] 已清除上次导入的 {removed_tracks} 条轨道（保证重复运行不叠加）")
    return removed_tracks


def apply_import(dec_content: dict, rows: list[dict], dry_run: bool = False,
                 use_pt_tracks: bool = False, crossfade_ms: int = 200) -> dict:
    d = dec_content
    mats = d.setdefault("materials", {})
    for cat in ("videos", "audios", "texts", "canvases", "beats", "material_animations",
                "placeholder_infos", "speeds", "sound_channel_mappings",
                "material_colors", "vocal_separations", "audio_fades"):
        mats.setdefault(cat, [])

    # 0) 幂等：先清掉上次导入的产物，避免重复运行时轨道叠加、名字被加 -2 后缀
    pt_names = {r.get("_pt_track") for r in rows if r.get("_pt_track")}
    _purge_previous(d.setdefault("tracks", []), mats,
                    verbose=not dry_run, pt_track_names=pt_names)

    audios = mats["audios"]
    paths = {}

    # 1) 素材注册（去重）
    for row in rows:
        src = row["source"]
        if src not in paths:
            dur_src = row.get("_src_dur_ms") or probe_duration_ms(src)
            mat_type = category_prefix_type(row["track_name"] or "")
            mat = make_audio_material(src, dur_src, mat_type)
            audios.append(mat)
            paths[src] = mat["id"]
            row["_src_dur_ms"] = dur_src
            row["_mat_id"] = mat["id"]
        else:
            row["_mat_id"] = paths[src]

    # 1.5) M3 时长延长：把「目标 > 源」的行展开为可写入的形态
    #      loop（默认）：多段引用同一素材，交界处交叉淡化（_plan_loop_rows）；
    #      stretch：单段变速（写真实 speed 素材，替代占位 speeds）。
    #      _target_ms 小于等于源时长时退化为普通缩短/等长覆盖。
    expanded = []
    for row in rows:
        tgt = int(row.pop("_target_ms", 0) or 0)
        mode = str(row.pop("_extend_mode", "") or "loop").strip().lower()
        if mode not in ("loop", "stretch"):
            mode = "loop"
        src_dur = row.get("_src_dur_ms") or 0
        try:
            cur = int(row["duration_ms"] or 0)
        except (TypeError, ValueError):
            cur = 0
        if tgt and src_dur and tgt > src_dur + 50:
            if mode == "stretch":
                avail = max(0, src_dur - int(row.get("_src_offset_ms") or 0))
                if avail <= 0:
                    print(f"[warn] {row['source'].name}: 可用源长为 0，忽略 stretch")
                    expanded.append(row)
                    continue
                row["duration_ms"] = str(tgt)
                row["_stretch_speed"] = round(avail / tgt, 6)
                expanded.append(row)
            else:
                expanded.extend(_plan_loop_rows(row, tgt, crossfade_ms))
        else:
            if tgt and tgt != cur:
                row["duration_ms"] = str(tgt)   # 缩短/等长覆盖
            expanded.append(row)
    rows = expanded

    # 2) 轨道规划
    # 说明：PT 的 .L / .R 是「clip 名」层面的声道后缀（如 `1.L` / `1.R`），
    # 已在 parse_pt_clips 里按 (时间码, 去声道名) 合并成一个立体声片段；
    # PT 的轨道名本身不含声道后缀（GetTrackList 实测：'Audio FX ST' / 'MX 2' 等），
    # 因此这里直接一轨一容器，无需再做声道归并。
    all_tracks = d.setdefault("tracks", [])
    used_names = {}
    for t in all_tracks:
        if t.get("name"):
            used_names[t["name"]] = used_names.get(t["name"], 0) + 1

    tracks_by_key = {}
    ordered_keys = []
    for row in rows:
        if use_pt_tracks:
            key = row.get("_pt_track") or row["track_name"] or f"{row['track_no']:02d}-音频"
        else:
            key = row["track_no"]
        if key not in tracks_by_key:
            name = (row.get("_pt_track") or row["track_name"]
                    or (f"{key:02d}-音频" if isinstance(key, int) else str(key)))
            if name in used_names:
                used_names[name] += 1
                name = f"{name}-{used_names[name]}"
            else:
                used_names[name] = 1
            track = {
                "id": new_id(),
                "type": "audio",
                "is_default_name": False,
                "name": name,
                "segments": [],
                "_jy_import": True,   # 幂等标记：重跑时据此清除，不误伤用户手改内容
            }
            all_tracks.append(track)
            tracks_by_key[key] = track
            ordered_keys.append(key)
        row["_track"] = tracks_by_key[key]

    # 3) 片段构造与落位（M3：支持延长 —— 循环多段 / 变速单段）
    for row in rows:
        track = row["_track"]
        src_dur = row.get("_src_dur_ms") or 0
        target_dur = int(row["duration_ms"]) if row["duration_ms"] else src_dur

        start_us = row["start_ms"] * 1000
        dur_us = target_dur * 1000
        src_off_us = int(row.get("_src_offset_ms") or 0) * 1000
        track_idx = all_tracks.index(track)

        # 变速延长：源取整个可用区间，目标为延长后长度，speed = 源/目标
        speed_mat = None
        src_dur_us = None
        if row.get("_stretch_speed"):
            src_dur_us = max(0, src_dur - int(row.get("_src_offset_ms") or 0)) * 1000
            speed_mat = make_speed_material(row["_stretch_speed"])
            mats["speeds"].append(speed_mat)

        seg = make_segment(row["_mat_id"], start_us, dur_us, track_idx, src_off_us,
                           src_dur_us=src_dur_us)
        for cat in PLACEHOLDER_CATS:
            if cat == "speeds" and speed_mat is not None:
                seg["extra_material_refs"].append(speed_mat["id"])   # 真实变速替代占位
                continue
            ph = make_placeholder(cat)
            mats[cat].append(ph)
            seg["extra_material_refs"].append(ph["id"])
        # 淡入淡出（Bug B 修复；循环延长交界处的交叉淡化同样走这里）
        fi = int(row.get("_fade_in_ms") or 0)
        fo = int(row.get("_fade_out_ms") or 0)
        if fi or fo:
            fade = make_fade(fi, fo)
            mats["audio_fades"].append(fade)
            seg["extra_material_refs"].append(fade["id"])
        if row["volume_db"]:
            seg["volume"] = round(10 ** (row["volume_db"] / 20), 6)
            seg["last_nonzero_volume"] = seg["volume"]
        track["segments"].append(seg)
        row["_seg"] = seg

    max_end = 0
    for t in all_tracks:
        for s in t.get("segments", []):
            st = s["target_timerange"].get("start", 0)
            max_end = max(max_end, st + s["target_timerange"]["duration"])
    d["duration"] = max_end

    # 4) 清理空白轨道
    # 剪映草稿模板常带一条空的默认 video 轨；导入只加音频轨，空轨会让用户看到一条多余的
    # 「空轨」占位并影响导出。rule：只删「无片段」的轨道，且至少保留 1 条（剪映要求非空 tracks）。
    if not dry_run:
        before = len(all_tracks)
        kept = [t for t in all_tracks if t.get("segments")]
        if not kept and all_tracks:
            kept = [all_tracks[0]]
        if len(kept) != before:
            all_tracks[:] = kept
            d["tracks"] = all_tracks
            print(f"[info] 清理空轨 {before - len(kept)} 条（保留 {len(kept)} 条有内容轨道）")
        # track_render_index 需按新顺序重排，否则剪映渲染层级错乱
        for i, t in enumerate(all_tracks):
            for s in t.get("segments", []):
                s["track_render_index"] = i

    if dry_run:
        print("[dry-run] 计划写入：")
        print(f"  素材注册: {len(audios)} 条（去重后）")
        print(f"  新建轨道: {len(tracks_by_key)} 条")
        for key in ordered_keys:
            t = tracks_by_key[key]
            print(f"    轨 {t['name']:<24} 片段 {len(t['segments'])} 个")
        n_fade = sum(1 for r in rows if r.get("_fade_in_ms") or r.get("_fade_out_ms"))
        print(f"  淡入淡出: {n_fade} 段")
        n_multi = sum(1 for r in rows if r.get("_multi_ref"))
        print(f"  源偏移: 多引用长轨 {n_multi} 段（源偏移=时间线位置） / "
              f"单引用音效 {len(rows)-n_multi} 段（源偏移=0）")
        for row in rows:
            fade = ""
            if row.get("_fade_in_ms") or row.get("_fade_out_ms"):
                fade = f"  [fade {row.get('_fade_in_ms',0)}/{row.get('_fade_out_ms',0)}ms]"
            tag = ""
            if row.get("_loop_piece"):
                i, n = row["_loop_piece"]
                tag = f"  [循环 {i}/{n} 段]"
            elif row.get("_stretch_speed"):
                tag = f"  [变速 x{row['_stretch_speed']:g}]"
            print(f"    tl@{row['start_ms']:>8}ms  src@{row.get('_src_offset_ms',0):>8}ms  "
                  f"len={row['duration_ms']:>7}ms  {row['source'].name[:34]:<34}"
                  f" -> {row['_track']['name']}{fade}{tag}")
    return d


def main():
    ap = argparse.ArgumentParser(description="剪映多轨音频导入器（M2.5 PT 工程翻译器）")
    ap.add_argument("manifest", nargs="?", type=Path, help="CSV 清单路径（旧模式）")
    ap.add_argument("draft_dir", type=Path, help="目标草稿目录（含 draft_content.json）")
    ap.add_argument("--pt-clips", type=Path, help="PT 解析结果 pt-clips.json（推荐）")
    ap.add_argument("--audio-dir", type=Path,
                    help="素材目录覆盖（交付包场景：json 同级 audio/ 会自动识别，一般无需指定）")
    ap.add_argument("--exclude", default="", help="排除轨道关键词（逗号分隔；默认排除辅助轨）")
    ap.add_argument("--keep-aux", action="store_true", help="保留辅助轨（不默认排除 VCA/Verb/Dly/BUS）")
    ap.add_argument("--draftc", type=Path, default=DEFAULT_DRAFTC, help="jy-draftc 路径")
    ap.add_argument("--dry-run", action="store_true", help="只解析打印不写入")
    ap.add_argument("--extend", action="append", default=[], metavar="名称=目标毫秒[:loop|stretch]",
                    help="M3 延长指定素材（子串匹配片段名/文件名，可重复）。"
                         "例: --extend \"107林间小路=146000:loop\"")
    ap.add_argument("--loop-crossfade", type=int, default=200, metavar="MS",
                    help="循环延长交界处交叉淡化时长（默认 200ms）")
    ap.add_argument("--force", action="store_true",
                    help="剪映运行中仍强制写入（默认拒绝，避免被剪映内存态覆盖）")
    args = ap.parse_args()

    if not args.draftc.is_file():
        print(f"[错误] jy-draftc 未找到: {args.draftc}")
        sys.exit(1)

    # 定位草稿内容文件：剪映 6.x 是「根目录 + Timelines/<main_timeline_id>/」双份结构，
    # 剪映实际读取时间线目录那份，必须两份同步写入。
    content_file, write_targets, note = resolve_content_files(args.draft_dir)
    if content_file is None or not content_file.is_file():
        print(f"[错误] 未找到 draft_content.json: {args.draft_dir}")
        sys.exit(1)
    print(f"[info] 草稿结构: {note}")
    print(f"[info] 权威读取源: {content_file.relative_to(args.draft_dir)}")
    if len(write_targets) > 1:
        print(f"[info] 同步写入 {len(write_targets)} 份内容文件：")
        for t in write_targets:
            print(f"         {t.relative_to(args.draft_dir)}  ({t.stat().st_size}B)")

    # 剪映运行中：其内存态会在保存时覆盖磁盘写入（2026-09-17 实测踩坑）
    if not args.dry_run:
        # ⚠️ 写入前校验必须拿**实时**进程列表：tasklist 输出有 5 秒缓存，
        #    若在这里吃缓存，用户「刚打开剪映」的窗口期会被放过去，
        #    写入随即被剪映内存态覆盖 —— 正是 2026-09-17 踩过的坑。
        blockers, warns = jianying_running_realtime(args.draft_dir)
        for w in warns:
            print(f"[提示] {w}")
        if blockers:
            for b in blockers:
                print(f"[警告] {b}")
            if not args.force:
                print("\n[中止] 剪映运行时会用内存中的旧内容覆盖本次写入，导入将看不到效果。")
                print("       请完全退出剪映（含托盘/后台进程）后重试；确实要强制写入请加 --force。")
                sys.exit(2)
            print("[警告] 已 --force，继续写入（结果可能随后被剪映覆盖）。")

    # 数据源
    from_pt = args.pt_clips is not None
    if from_pt:
        ex = [s.strip().lower() for s in args.exclude.split(",") if s.strip()]
        if not ex and not args.keep_aux:
            ex = list(DEFAULT_EXCLUDE)
        rows = parse_pt_clips(args.pt_clips, tuple(ex), audio_dir=args.audio_dir)
        print(f"[info] 数据源: PT 解析结果 {args.pt_clips.name}  片段 {len(rows)} 个"
              f"{'  (排除: ' + ','.join(ex) + ')' if ex else ''}")
    else:
        if args.manifest is None:
            print("[错误] 需提供 CSV 清单，或使用 --pt-clips 指定 PT 解析结果")
            sys.exit(1)
        rows = parse_manifest(args.manifest)
        print(f"[info] 数据源: CSV 清单 {args.manifest.name}  行 {len(rows)} 个")

    if args.extend:
        rows = apply_extends(rows, args.extend)

    dec_file = Path(str(content_file) + ".dec.json")
    if (not dec_file.is_file()
            or content_file.stat().st_mtime_ns > dec_file.stat().st_mtime_ns):
        if dec_file.exists():
            dec_file.unlink()
        dec_file = decrypt_file(args.draftc, content_file)
    try:
        d = json.loads(dec_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[错误] 解密 JSON 解析失败: {e}")
        sys.exit(1)

    d2 = apply_import(d, rows, dry_run=args.dry_run, use_pt_tracks=from_pt,
                      crossfade_ms=args.loop_crossfade)

    if args.dry_run or d2 is None:
        return

    dec_file.write_text(json.dumps(d2, ensure_ascii=False, indent=2), encoding="utf-8")
    enc_file = encrypt_file(args.draftc, dec_file)

    # 双份同步写入：根目录 + Timelines/<main_timeline_id>/（后者才是剪映读的那份）
    for tgt in write_targets:
        bak = tgt.parent / (tgt.name + ".jybak")
        if not bak.exists():
            bak.write_bytes(tgt.read_bytes())
            print(f"[info] 写入前备份: {tgt.relative_to(args.draft_dir)} -> {bak.name}")
        shutil.copy2(enc_file, tgt)
        print(f"[info] 已写入: {tgt.relative_to(args.draft_dir)}  ({tgt.stat().st_size}B)")
    enc_file.unlink(missing_ok=True)
    dec_file.unlink(missing_ok=True)

    chk = decrypt_file(args.draftc, content_file)
    v = json.loads(chk.read_text(encoding="utf-8"))
    chk.unlink(missing_ok=True)
    n_audio = sum(1 for t in v.get("tracks", []) if t.get("type") == "audio")
    n_seg = sum(len(t.get("segments", [])) for t in v.get("tracks", []) if t.get("type") == "audio")
    print("[完成] 导入成功并经往返校验：")
    print(f"  目标草稿: {args.draft_dir.name}")
    print(f"  audio 轨: {n_audio} 条，audio 片段: {n_seg} 个")
    print(f"  写入份数: {len(write_targets)}（根目录 + 时间线目录，保证剪映读到新内容）")
    print("  请用剪映打开该草稿验证轨道位置/时长/音频块完整性。")


if __name__ == "__main__":
    main()
