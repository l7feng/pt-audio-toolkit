#!/usr/bin/env python3
r"""
pt_clip_scan.py — Pro Tools 工程片段扫描器（M2.5 核心）

用途：把 Pro Tools 工程的「轨道 + 每段 clip」元数据完整提取出来，作为剪映导入的数据源。
      替代旧的手工 CSV 清单，一次性修复 M2 暴露的 3 个 bug：
        - Bug A 时长错：读 clip 在 PT 时间线的真实起止/长度，而非音频文件总时长
        - Bug B 淡入淡出丢：解析导出的 (淡出)/(淡入) 事件
        - Bug C 轨道错位：按 PT 轨道真实顺序输出，不再依赖手工 track_no

原理（2026-09-17 实测确定）：
  走 PTSL（py-ptsl）调用 **ExportSessionInfoAsText (CId 30)** → 导出会话全文
  → 解析出「轨道名 / 通道 / 事件 / 片段名称 / 开始时间 / 结束时间 / 长度 / 状态」。

  为什么不用 GetPlaylistElements(158)/GetTrackPlaylists(154)？
  实测本机 PT 25.6.1（ptsl_version=2025）返回
    ErrType 133: PT_UnsupportedCommand (Unsupported command ID: 154)
  这批新命令（CId 141-159）本机服务端未实现，与 05-PT 项目实测 146/147 同理。
  而 ExportSessionInfoAsText 是**老命令（CId 30）**，本机完全可用，且输出已含
  clip 级明细 + 淡入淡出事件，正是所需。

前提：Pro Tools 已启动、加载目标工程、PTSL 监听 localhost:31416。

示例：
  python pt_clip_scan.py --out "D:\out"
  python pt_clip_scan.py --out "D:\out" --tracks "DX 1,MX 1"      # 只保留含这些关键词的轨
  python pt_clip_scan.py --out "D:\out" --exclude "Verb,Dly,BUS"  # 排除辅助轨
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from ptsl import Engine
from ptsl.ops import Operation
from ptsl import PTSL_pb2 as pb


# ── PTSL 中文编码 bug 修复（同 pt-scanner）──────────────────────────
_GBK_RUN_RE = re.compile(r"(?:\\x[0-9a-fA-F]{2})+")
_GBK_BYTE_RE = re.compile(r"\\x([0-9a-fA-F]{2})")


def _decode_gbk_run(match):
    raw = bytes(int(h, 16) for h in _GBK_BYTE_RE.findall(match.group(0)))
    return json.dumps(raw.decode("gbk", errors="replace"),
                      ensure_ascii=False)[1:-1]


class CId_ExportSessionInfoAsText(Operation):
    """导出会话全文信息（含轨道 + clip 明细 + fade 事件）。"""
    def json_cleanup(self, in_json: str) -> str:
        return _GBK_RUN_RE.sub(_decode_gbk_run, in_json)


def guard_session_ready(pt, timeout=5.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if pt.session_name():
                return
        except Exception:
            pass
        time.sleep(0.3)
    print("[error] Pro Tools 会话无响应（疑似模态弹窗阻塞）。请人工处理后重试。",
          file=sys.stderr)
    sys.exit(1)


class CId_GetTrackList(Operation):
    """取权威轨道顺序与格式（name/index/format/type）。

    为什么需要：ExportSessionInfoAsText 的轨道列表顺序不可断言是 PT 界面顺序；
    GetTrackList 给出 index（界面序号）与 format（1=单声道/2=立体声），
    据此建立剪映轨道可保证「轨道顺序与 PT 一致」。
    """
    pass


def fetch_track_meta(pt):
    """返回 [{name, index, format, type}]（按 index 升序），失败返回 []。"""
    try:
        op = CId_GetTrackList(pagination_request=pb.PaginationRequest(limit=1000, offset=0))
        pt.client.run(op)
        out = []
        for t in op.response.track_list:
            out.append({
                "name": t.name,
                "index": int(t.index),
                "format": int(t.format),
                "type": int(t.type),
            })
        out.sort(key=lambda x: x["index"])
        return out
    except Exception as e:
        print(f"[warn] GetTrackList 失败（不影响主流程）: {e}", file=sys.stderr)
        return []


# ── 解析器：会话信息文本 -> 结构化 JSON ──────────────────────────────
RE_HEADER_FIELD = re.compile(r"^([^：\t]{2,12})[：:]\s*(.*)$")
RE_TRACK_NAME = re.compile(r"^轨道名[：:]\s*(.+?)\s*$")
RE_CLIP_ROW = re.compile(r"^(\d+)\s+(\d+)\s+(.+?)\s+(\d{2}:\d{2}:\d{2}[:;]\d{2})\s+"
                         r"(\d{2}:\d{2}:\d{2}[:;]\d{2})\s+"
                         r"(\d{2}:\d{2}:\d{2}[:;]\d{2})\s*(.*)$")
# 「工程中的在线片段」区：片段名<TAB>文件名（两侧名字均可含空格）
RE_CLIP_FILE = re.compile(r"^(.+?)\s*\t+\s*(.+?\.(?:wav|WAV|aif|aiff|AIF|mp3|mxf))\s*$")
# 「工程中在线的文件」区：文件名<TAB>位置（文件名可含空格）
RE_FILE_LOC = re.compile(r"^(.+?\.(?:wav|WAV|aif|aiff|AIF|mp3|mxf))\s*\t+\s*(.+?)\s*$")

SECTION_FILES = "工 程 中 在 线 的 文 件"
SECTION_CLIPMAP = "工 程 中 的 在 线 片 段"
SECTION_TRACKS = "轨 道 列 表"


def _tc_to_frames(tc, fps=25):
    """timecode -> 帧数（默认 25fps；女帝22 为 25 帧）。"""
    if not tc:
        return None
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})[:;](\d{2})", tc)
    if not m:
        return None
    h, mi, s, f = (int(x) for x in m.groups())
    return ((h * 60 + mi) * 60 + s) * fps + f


def parse_session_info(text, fps=25):
    """把 ExportSessionInfoAsText 的文本解析为结构化 dict。

    返回：
      {
        session: {...},
        online_files: [{name, location}],
        clip_file_map: {片段名: 文件名},
        tracks: [{name, format, clips:[...], fades:[...]}],
      }
    """
    lines = text.splitlines()
    session = {}
    online_files = []
    clip_file_map = {}
    tracks = []
    cur_track = None
    section = "header"

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue

        # 区段切换
        if SECTION_FILES in stripped:
            section = "files"; continue
        if "离 线 的 文 件" in stripped:
            section = "offline"; continue
        if SECTION_CLIPMAP in stripped:
            section = "clipmap"; continue
        if SECTION_TRACKS in stripped:
            section = "tracks"; continue

        m_tr = RE_TRACK_NAME.match(stripped)
        if m_tr:
            section = "tracks"
            label = m_tr.group(1)
            name, _, fmt = label.rpartition(" (")
            if name:
                fmt = fmt.rstrip(")")
            else:
                name, fmt = label, ""
            cur_track = {"name": name.strip(), "format": fmt.strip(),
                         "clips": [], "fades": []}
            tracks.append(cur_track)
            continue

        if section == "tracks":
            m_clip = RE_CLIP_ROW.match(stripped)
            if m_clip and cur_track is not None:
                ch, ev, cname, start, end, length, status = m_clip.groups()
                rec = {
                    "channel": int(ch),
                    "event": int(ev),
                    "name": cname.strip(),
                    "start": start,
                    "end": end,
                    "length": length,
                    "status": status.strip(),
                    "start_frames": _tc_to_frames(start, fps),
                    "end_frames": _tc_to_frames(end, fps),
                    "length_frames": _tc_to_frames(length, fps),
                }
                if cname.strip() in ("(淡出)", "(淡入)", "(交叉淡化)"):
                    cur_track["fades"].append(rec)
                else:
                    cur_track["clips"].append(rec)
            continue

        if section == "files":
            m = RE_FILE_LOC.match(stripped)
            if m:
                online_files.append({"name": m.group(1), "location": m.group(2).strip()})
            continue

        if section == "clipmap":
            m = RE_CLIP_FILE.match(stripped)
            if m:
                clip_file_map[m.group(1).strip()] = m.group(2).strip()
            continue

        # header
        m = RE_HEADER_FIELD.match(stripped)
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            if k and v:
                session[k] = v

    return {
        "session": session,
        "online_files": online_files,
        "clip_file_map": clip_file_map,
        "tracks": tracks,
    }


def run(args):
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    pt = Engine(company_name="local", application_name="pt-clip-scan")
    guard_session_ready(pt)

    fps = 25
    sr = pt.session_sample_rate()
    session_name = pt.session_name()
    track_meta = fetch_track_meta(pt)

    op = CId_ExportSessionInfoAsText(
        include_file_list=True,
        include_clip_list=True,
        include_markers=True,
        include_plugin_list=False,
        include_track_edls=True,
        show_sub_frames=False,
        include_user_timestamps=False,
        track_list_type=1,        # TListType_AllTracks
        fade_handling_type=1,     # FHType_ShowCrossfades（fade 作为独立事件列出）
        track_offset_options=3,   # TOOptions_TimeCode
        text_as_file_format=2,    # TFFormat_UTF8
        output_type=2,            # ESIOType_String
        location_type=5,          # TLType_TimeCode
    )
    pt.client.run(op)
    raw_text = op.response.session_info
    pt.close()

    # 时间码帧率（会话头「时间码格式：25 帧」）
    m = re.search(r"时间码格式[：:]\s*([\d.]+)", raw_text)
    if m:
        try:
            fps = int(float(m.group(1)))
        except ValueError:
            pass

    parsed = parse_session_info(raw_text, fps)

    # 过滤
    include = [s.strip().lower() for s in args.tracks.split(",") if s.strip()]
    exclude = [s.strip().lower() for s in args.exclude.split(",") if s.strip()]
    tracks = []
    for t in parsed["tracks"]:
        ln = t["name"].lower()
        if include and not any(k in ln for k in include):
            continue
        if exclude and any(k in ln for k in exclude):
            continue
        tracks.append(t)

    # 把权威轨道元数据（index / format）并入解析结果
    meta_by_name = {m["name"]: m for m in track_meta}
    for t in tracks:
        m = meta_by_name.get(t["name"])
        if m:
            t["index"] = m["index"]
            t["format_code"] = m["format"]   # 1=Mono 2=Stereo
            t["type_code"] = m["type"]       # 2=Audio 3=Aux 5=VCA ...
        else:
            t["index"] = None
            t["format_code"] = None
            t["type_code"] = None
    # 按 PT 界面顺序排序（无 index 的排最后，保持原相对顺序）
    _orig = {t["name"]: i for i, t in enumerate(tracks)}
    tracks.sort(key=lambda t: (t["index"] if t["index"] is not None else 10 ** 6,
                               _orig.get(t["name"], 0)))

    result = {
        "schema_version": "1.1",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "source": "PTSL ExportSessionInfoAsText (CId 30) + GetTrackList",
        "session": {
            "name": session_name,
            "sample_rate": sr,
            "fps": fps,
            "raw_summary": parsed["session"],
        },
        "online_files": parsed["online_files"],
        "clip_file_map": parsed["clip_file_map"],
        "track_meta": track_meta,
        "track_count": len(tracks),
        "tracks": tracks,
    }

    # 保存原始文本 + 结构化 JSON
    raw_path = os.path.join(out_dir, f"{session_name}-session-info.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw_text)
    out_path = os.path.join(out_dir, args.name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total_clips = sum(len(t["clips"]) for t in tracks)
    total_fades = sum(len(t["fades"]) for t in tracks)
    print(f"[info] session={session_name}  fps={fps}  sr={sr}")
    print(f"[info] online_files={len(parsed['online_files'])}  clip_file_map={len(parsed['clip_file_map'])}")
    print(f"[scan] tracks={len(tracks)}  clips={total_clips}  fades={total_fades}")
    for t in tracks:
        print(f"   {t['name']:<24} {t['format']:<8} clips={len(t['clips']):<3} fades={len(t['fades'])}")
    print(f"\n[ok] raw  -> {raw_path}")
    print(f"[ok] json -> {out_path}")


def main():
    p = argparse.ArgumentParser(description="Pro Tools clip scanner (PTSL)")
    p.add_argument("--out", default=".", help="output directory")
    p.add_argument("--name", default="pt-clips.json", help="output filename")
    p.add_argument("--tracks", default="", help="keep tracks whose name contains any (comma-sep)")
    p.add_argument("--exclude", default="", help="drop tracks whose name contains any (comma-sep)")
    args = p.parse_args()
    try:
        run(args)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        print("请确认 Pro Tools 已启动、工程已加载、PTSL 服务可用。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
