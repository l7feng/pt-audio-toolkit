#!/usr/bin/env python3
r"""
pt_scan.py — Pro Tools 工程扫描器（基于 PTSL / py-ptsl）

功能：
  - 连接正在运行的 Pro Tools（PTSL localhost:31416）
  - 读取机器环境（主机名 / Python / PTSL 版本）
  - 读取当前工程（名称 / 路径 / 采样率 / 位深 / 时码率 / 长度）
  - 读取全部轨道（名称 / 类型 / 格式 / 时基 / 静音 / 独奏 / 隐藏 等）
  - 读取导出源列表（Bus / Output / PhysicalOut / Renderer）
  - 输出统一 JSON 档案（pt-profile.json），供 pt-exporter 等后续工具使用

前提：Pro Tools 已启动并加载工程，PTSL 监听 localhost:31416。

示例：
  python pt_scan.py --out "D:\path\to\dir" --name pt-profile.json
  python pt_scan.py        # 输出到当前目录 pt-profile.json
"""
import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone

# Windows 控制台 GBK code page 下强制 UTF-8 输出，避免中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from ptsl import Engine
from ptsl.ops import Operation
from ptsl import PTSL_pb2 as pb

# ── 枚举映射（数值以 PTSL_pb2 实际 proto 为准）────────────────────────

# SessionTimeCodeRate —— 时码率
TIMECODE_RATE = {
    0: "unknown", 1: "23.976", 2: "24", 3: "25", 4: "29.97", 5: "29.97 DF",
    6: "30", 7: "30 DF", 8: "47.952", 9: "48", 10: "50", 11: "59.94",
    12: "59.94 DF", 13: "60", 14: "60 DF", 15: "100", 16: "119.88",
    17: "119.88 DF", 18: "120", 19: "120 DF",
}

# BitDepth —— 位深
BIT_DEPTH = {
    0: "unknown", 1: "none", 2: "16-bit", 3: "24-bit", 4: "32-bit float",
}

# TrackType —— 轨道类型
TRACK_TYPE = {
    0: "unknown", 1: "midi", 2: "audio", 3: "aux", 4: "video", 5: "vca",
    6: "tempo", 7: "markers", 8: "meter", 9: "key-signature",
    10: "chord-symbols", 11: "instrument", 12: "master", 13: "heat",
    14: "basic-folder", 15: "routing-folder", 16: "comp-lane",
}

# TrackFormat —— 轨道格式
TRACK_FORMAT = {
    0: "unknown", 1: "mono", 2: "stereo", 3: "LCR", 4: "LCRS", 5: "quad",
    6: "5.0", 7: "5.1", 8: "5.0.2", 9: "5.1.2", 10: "5.0.4", 11: "5.1.4",
    12: "6.0", 13: "6.1", 14: "7.0", 15: "7.1", 16: "7.0 SDDS",
    17: "7.1 SDDS", 18: "7.0.2", 19: "7.1.2", 20: "7.0.4", 21: "7.1.4",
    22: "7.0.6", 23: "7.1.6", 24: "9.0.4", 25: "9.1.4", 26: "9.0.6",
    27: "9.1.6", 28: "1st-order ambisonics", 29: "2nd-order ambisonics",
    30: "3rd-order ambisonics", 31: "4th-order ambisonics",
    32: "5th-order ambisonics", 33: "6th-order ambisonics",
    34: "7th-order ambisonics", 35: "none", 36: "2.1", 37: "overhead",
}

# TrackTimebase —— 轨道时基
TRACK_TIMEBASE = {0: "unknown", 1: "samples", 2: "ticks", 3: "none"}

# EM_SourceType —— 导出源类型
SOURCE_TYPE = {
    0: "unknown", 1: "physicalout", 2: "bus", 3: "output", 4: "renderer",
}


# 自定义 Operation：GetExportMixSourceList（py-ptsl 未封装为 Engine 方法）
# json_cleanup 修复 PTSL 的中文编码 bug：物理输出名中的非 ASCII 字符会被
# 转义成 \xNN（GBK 双字节序列），这不是合法 JSON（\u 才是），必须还原。
import re as _re
import json as _json

_GBK_RUN_RE = _re.compile(r"(?:\\x[0-9a-fA-F]{2})+")
_GBK_BYTE_RE = _re.compile(r"\\x([0-9a-fA-F]{2})")


def _decode_gbk_run(match):
    r"""把一段连续的 \xNN 序列按 GBK 整体解码为合法 JSON 字符串内容。"""
    raw = bytes(int(h, 16) for h in _GBK_BYTE_RE.findall(match.group(0)))
    decoded = raw.decode("gbk", errors="replace")
    return _json.dumps(decoded, ensure_ascii=False)[1:-1]


class CId_GetExportMixSourceList(Operation):
    def json_cleanup(self, in_json: str) -> str:
        return _GBK_RUN_RE.sub(_decode_gbk_run, in_json)


def collect_sources(pt):
    """返回 {source_type: [source_name, ...]}，按类型收集导出源。

    renderer 类型在无 Dolby Renderer 的工程中会报 PT_InvalidParameter，
    属预期行为：此时记空列表并打警告，不把错误写进 profile。
    """
    result = {}
    errors = []
    for stype_name in ("EMSType_PhysicalOut", "EMSType_Bus",
                       "EMSType_Output", "EMSType_Renderer"):
        stype = getattr(pb, stype_name)
        stype_key = SOURCE_TYPE.get(stype, stype_name)
        op = CId_GetExportMixSourceList(type=stype)
        try:
            pt.client.run(op)
            result[stype_key] = list(op.response.source_list)
        except Exception as exc:
            result[stype_key] = []
            errors.append(f"{stype_key}: {exc}")
    if errors:
        print("[warn] source list errors (will not appear in profile):")
        for err in errors:
            print(f"       {err}")
    return result


def collect_tracks(pt):
    """返回轨道列表，每条含名称/类型/格式/时基/颜色/父文件夹/关键属性。"""
    keep_attrs = (
        "is_inactive", "is_hidden", "is_selected", "contains_clips",
        "contains_automation", "is_soloed", "is_record_enabled",
        "is_input_monitoring_on", "is_smart_dsp_on", "is_locked",
        "is_muted", "is_frozen", "is_open", "is_online",
        "has_edit_selection",
    )
    tracks = []
    for t in pt.track_list():
        attr = {}
        for name in keep_attrs:
            attr[name] = bool(getattr(t.track_attributes, name, False))
        tracks.append({
            "index": t.index,
            "name": t.name,
            "type": TRACK_TYPE.get(t.type, str(t.type)),
            "format": TRACK_FORMAT.get(t.format, str(t.format)),
            "timebase": TRACK_TIMEBASE.get(t.timebase, str(t.timebase)),
            "color": t.color or "",
            "parent_folder": t.parent_folder_name or "",
            "attributes": attr,
        })
    return tracks


# ── 模态弹窗防御（2026-09-15 实测：PT 弹"媒体丢失"等模态框会阻塞 PTSL）─
def guard_session_ready(pt, timeout=5.0):
    """确认 PTSL 会话可读；带超时，防模态弹窗造成无提示卡死。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if pt.session_name():
                return
        except Exception:
            pass
        time.sleep(0.3)
    print("[error] Pro Tools 会话无响应（疑似模态弹窗阻塞，如媒体丢失"
          "查找框）。请人工处理后重试。", file=sys.stderr)
    sys.exit(1)


def run(args):
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, args.name)

    pt = Engine(company_name="local", application_name="pt-scanner")
    guard_session_ready(pt)

    profile = {
        "schema_version": "1.0",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "machine": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "ptsl_version": str(pt.ptsl_version()),
        },
        "session": {
            "name": pt.session_name(),
            "path": pt.session_path(),
            "sample_rate": pt.session_sample_rate(),
            "bit_depth": BIT_DEPTH.get(pt.session_bit_depth(), "unknown"),
            "bit_depth_raw": int(pt.session_bit_depth()),
            "timecode_rate": TIMECODE_RATE.get(pt.session_timecode_rate(),
                                               "unknown"),
            "timecode_rate_raw": int(pt.session_timecode_rate()),
            "start_time": pt.session_start_time(),
            "length": pt.session_length(),
        },
        "tracks": collect_tracks(pt),
        "sources": collect_sources(pt),
    }
    pt.close()

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    # ── 控制台摘要 ──────────────────────────────────────────────────
    s = profile["session"]
    print("=== machine ===")
    print(f"host      : {profile['machine']['hostname']}")
    print(f"ptsl      : {profile['machine']['ptsl_version']}")
    print(f"python    : {profile['machine']['python']}")
    print("\n=== session ===")
    print(f"name      : {s['name']}")
    print(f"path      : {s['path']}")
    print(f"sr        : {s['sample_rate']} Hz")
    print(f"bit depth : {s['bit_depth']}")
    print(f"timecode  : {s['timecode_rate']} fps")
    print(f"start     : {s['start_time']}")
    print(f"length    : {s['length']}")

    print("\n=== tracks ===")
    for t in profile["tracks"]:
        flags = ""
        if t["attributes"]["is_muted"]:
            flags += " M"
        if t["attributes"]["is_soloed"]:
            flags += " S"
        if t["attributes"]["is_hidden"]:
            flags += " H"
        if t["attributes"]["is_inactive"]:
            flags += " I"
        print(f"[{t['index']:>2}] {t['name']:<40} "
              f"{t['type']:<10} {t['format']:<6}{flags}")

    print("\n=== sources ===")
    for stype, names in profile["sources"].items():
        if names:
            print(f"{stype:<12}: {', '.join(names)}")

    print(f"\n[ok] saved -> {out_path}")


def main():
    p = argparse.ArgumentParser(description="Pro Tools session scanner (PTSL)")
    p.add_argument("--out", default=".", help="output directory (default: .)")
    p.add_argument("--name", default="pt-profile.json",
                   help="profile filename (default: pt-profile.json)")
    args = p.parse_args()
    try:
        run(args)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        print("请确认 Pro Tools 已启动、工程已加载、PTSL 服务可用。",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()