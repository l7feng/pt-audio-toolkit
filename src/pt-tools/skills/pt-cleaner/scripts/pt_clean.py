#!/usr/bin/env python3
r"""
pt_clean.py — Pro Tools 批量 IO 输出清理工具（基于 PTSL / py-ptsl）

功能（P1：批量改 IO 输出）：
  - 把指定轨道的**主输出**统一改到某个输出路径（signal path）
  - 可选项：用 CreateSignalPath 先建一个输出路径再批量指派
  - 全程 dry-run 预览；写操作前自动 SaveSessionAs 备份副本

⚠️ 已确认边界（2026-09-15 E0/E3 实测定案）：
  - 删发送（send）/ 删插件（insert）/ 删 IO 路径 **PTSL 不支持**（无命令），
    本工具不做，也不要假装能做。
  - PTSL 没有「列出全部 signal path」的读命令，只有 GetExportMixSourceList
    能拿到输出路径的**名字**。因此 signalpath 目标用名字传参（与导出源同源），
    CreateSignalPath 新建的路径返回 SignalPathInfo.id 可直接用。

前提：Pro Tools 已启动并加载工程，PTSL 监听 localhost:31416。

示例：
  # 1) dry-run 预览：把 DX 相关音频轨的主输出改到 Master Hole
  python pt_clean.py --profile pt-profile.json \
      --tracks "DX 1" "DX VO" --output "Master Hole" --dry-run

  # 2) 确认后执行（会自动备份副本后写入）
  python pt_clean.py --profile pt-profile.json \
      --tracks "DX 1" "DX VO" --output "Master Hole"

  # 3) 模式：按轨道前缀匹配（推荐给 AI 用，不用逐个列名字）
  python pt_clean.py --profile pt-profile.json \
      --track-prefix "DX" --output "Master Hole"

  # 4) 新建输出路径再指派（CreateSignalPath）
  python pt_clean.py --profile pt-profile.json \
      --tracks "DX 1" --create-path "DX-BUS-Master" --output "DX-BUS-Master"
"""
import argparse
import json
import os
import sys
from datetime import datetime
from ptsl import Engine
from ptsl.ops import Operation
from ptsl import PTSL_pb2 as pb

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── 枚举 ──────────────────────────────────────────────────────────────
# SignalPathType（CreateSignalPath 用）
SIGNAL_PATH_TYPE = {
    "input": pb.SPType_Input, "output": pb.SPType_Output,
    "bus": pb.SPType_Bus, "rendererbed": pb.SPType_RendererBed,
    "rendererobject": pb.SPType_RendererObject,
}
SIGNAL_PATH_TYPE_NAME = {v: k for k, v in SIGNAL_PATH_TYPE.items()}

SOURCE_SIGNAL_TYPE = {"bus": pb.SPType_Bus, "output": pb.SPType_Output,
                      "physicalout": pb.SPType_Output}


# ── 自定义 Operation（py-ptsl 未封装；与 GetExportMixSourceList 同手法）──
class CId_SetTrackMainOutputAssignments(Operation):
    pass


class CId_CreateSignalPath(Operation):
    pass


def load_profile(path):
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[warn] profile 读取失败（{exc}），跳过校验", file=sys.stderr)
        return {}


def pick_tracks(profile, names, prefix):
    """从 profile.tracks 选出目标轨道。返回 (选中名列表, 未命中列表)。"""
    all_tracks = [t["name"] for t in profile.get("tracks", [])]
    selected, missed = [], []
    if prefix:
        selected = [n for n in all_tracks if n.startswith(prefix)]
        if not selected:
            print(f"[warn] 前缀 '{prefix}' 未匹配任何轨道（共 {len(all_tracks)} 条）")
        return selected, []
    for n in names:
        if n in all_tracks:
            selected.append(n)
        else:
            missed.append(n)
    return selected, missed


def verify_output(profile, output_name):
    """在 profile.sources 里找 output_name 属于哪类（output/bus/physicalout）。"""
    for stype, names in profile.get("sources", {}).items():
        if output_name in names:
            return stype, True
    return None, False


def create_signal_path(pt, name, sp_type=pb.SPType_Output):
    """CreateSignalPath；返回 SignalPathInfo（含 id）。"""
    op = CId_CreateSignalPath(
        signalpath_name=name,
        signalpath_type=sp_type,
        signalpath_format=pb.TF_Stereo,  # 与导出端默认一致，可后续扩展
    )
    pt.client.run(op)
    return op.response.signalpath_info


def connect_pt():
    try:
        return Engine(company_name="local", application_name="pt-cleaner")
    except Exception as exc:
        print(f"[warn] 无法连接 Pro Tools（{type(exc).__name__}）",
              file=sys.stderr)
        return None


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
    profile = load_profile(args.profile)
    pt = connect_pt()

    if pt is not None:
        guard_session_ready(pt)
        print(f"[session] {pt.session_name()}")
    else:
        print("[warn] PTSL 不可达：确认 Pro Tools 已启动、工程已加载。"
              "dry-run 模式可继续预览（基于 profile）。")

    # ── 目标轨道选择 ────────────────────────────────────────────────
    selected, missed = pick_tracks(profile, args.tracks, args.track_prefix)
    if missed:
        print(f"[warn] 以下轨道不在 profile 中：{missed}")
    if not selected:
        print("[error] 没有可操作的目标轨道。检查 --tracks / --track-prefix。")
        sys.exit(1)

    # ── 输出路径校验 ─────────────────────────────────────────────────
    stype, found = verify_output(profile, args.output)
    if not found:
        print(f"[warn] '{args.output}' 不在 profile.sources 任一列表里！")
        print("       列出的是 profile 中的全部输出路径：")
        for st, names in profile.get("sources", {}).items():
            print(f"       {st}: {', '.join(names) if names else '(空)'}")
        print("       将仍然尝试（这个命令以名字传参）；若报路径无效请核对。")

    # ── 计划展示（dry-run 核心） ────────────────────────────────────
    print(f"\n=== 清理计划（{len(selected)} 条轨道） ===")
    print(f"目标输出 : {args.output}  ({stype if stype else '未知类型'})")
    for i, name in enumerate(selected, 1):
        print(f"  {i:>2}. {name}")
    if args.create_path:
        print(f"[plan] 将先用 CreateSignalPath 新建输出路径: "
              f"{args.create_path}")

    if args.dry_run:
        print("\n[dry-run] 预览结束，未做任何更改。确认无误后去掉 --dry-run。")
        if pt is not None:
            pt.close()
        return

    if pt is None:
        print("[error] PTSL 不可达，无法执行。请先启动 Pro Tools。",
              file=sys.stderr)
        sys.exit(1)

    # ── 备份 ─────────────────────────────────────────────────────────
    sess_path = pt.session_path()
    bak = sess_path.replace(".ptx", f"_cleaner-backup-"
                                     f"{datetime.now():%Y%m%d-%H%M%S}.ptx")
    if args.backup:
        try:
            pt.save_session_as(bak)
            print(f"[backup] 已保存备份副本 -> {bak}")
        except Exception as exc:
            print(f"[warn] 备份失败（{exc}），用户自行决定是否继续。")
    else:
        print("[warn] 未做备份（--no-backup）。改坏了由用户负责。")

    # ── 执行 ─────────────────────────────────────────────────────────
    target_path_id = args.output
    if args.create_path:
        info = create_signal_path(pt, args.create_path)
        print(f"[create] 信号路径 '{args.create_path}' 已创建 "
              f"(id={info.id}, type="
              f"{SIGNAL_PATH_TYPE_NAME.get(info.type, info.type)})")
        target_path_id = args.output  # 用名字传参（新路径名 = --output）

    op = CId_SetTrackMainOutputAssignments(
        track_names=list(selected),
        signalpath_ids=[target_path_id],
    )
    try:
        pt.client.run(op)
        print(f"[ok] 已将 {len(selected)} 条轨道的主输出改为 "
              f"'{args.output}'")
    except Exception as exc:
        print(f"[fail] {exc}")
        print("       可能原因：signalpath 名无效 / 轨道名无效 / 服务端"
              "未实现该命令（PTSL 版本过低）")
    finally:
        if args.save:
            pt.save_session()
        pt.close()
    print("[done] clean complete")


def main():
    p = argparse.ArgumentParser(
        description="Pro Tools batch IO output cleaner (PTSL)")
    p.add_argument("--profile", default=None,
                   help="pt-profile.json（pt-scanner 生成；轨道/路径校验）")
    p.add_argument("--output", required=True,
                   help="目标输出路径名（与导出源名字一致，如 Master Hole）")
    p.add_argument("--tracks", nargs="*", default=[],
                   help="轨道名列表（精确匹配 profile.tracks）")
    p.add_argument("--track-prefix", default=None,
                   help="按前缀选轨（如 --track-prefix DX 匹配所有 DX 开头轨）")
    p.add_argument("--create-path", default=None,
                   help="可选：先 CreateSignalPath 新建该输出路径")
    p.add_argument("--dry-run", action="store_true",
                   help="只展示计划，不改任何东西")
    p.add_argument("--backup", dest="backup", action="store_true",
                   default=True, help="执行前 SaveSessionAs 备份（默认开）")
    p.add_argument("--no-backup", dest="backup", action="store_false")
    p.add_argument("--save", action="store_true",
                   help="执行后保存工程（默认不保存）")
    args = p.parse_args()
    if not args.tracks and not args.track_prefix:
        print("[error] 必须提供 --tracks 或 --track-prefix", file=sys.stderr)
        sys.exit(1)
    run(args)


if __name__ == "__main__":
    main()