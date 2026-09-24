#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1（v2.7.0）：PT → 剪映 交付包一键总控（扫描 + 打包一步完成）。

pt-tools 扫描建档页「生成交付包」经技能 venv 的 python 子进程调用本脚本：

  ① pt_clip_scan.run()                       走 PTSL 提取 pt-clips.json（需 PT 在线）
  ② make_delivery_package.build_package(light=True)
                                             产出 json + audio/（仅数据；导入工具
                                             exe 与使用说明已随 v2.7.0 J8 退役）

⚠️ 同源约定：本目录的 pt_clip_scan.py / make_delivery_package.py / import_audio.py
   与剪映工具 `code/` 下同名模块**同源**——修 bug/改逻辑必须双向同步
   （单一真源问题登记在 13 号方案 D 批工具合并时统一）。
"""
import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pt_clip_scan                      # noqa: E402
import make_delivery_package             # noqa: E402
import import_audio                      # noqa: E402  # 默认排除名单来源


def main():
    ap = argparse.ArgumentParser(description="PT → 剪映 delivery package builder")
    ap.add_argument("--json-dir", required=True, help="pt-clips.json 落点目录")
    ap.add_argument("--pkg-dir", required=True, help="交付包输出目录")
    ap.add_argument("--name", default="pt-clips.json", help="json 文件名")
    ap.add_argument("--exclude", default="",
                    help="排除轨道关键词（逗号分隔）；留空用内置默认排除名单")
    a = ap.parse_args()

    json_dir = Path(a.json_dir)
    json_dir.mkdir(parents=True, exist_ok=True)
    pkg_dir = Path(a.pkg_dir)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    exclude = tuple(x.strip() for x in (a.exclude or "").split(",") if x.strip()) \
        or tuple(import_audio.DEFAULT_EXCLUDE)

    print("=" * 60)
    print("[1/2] PTSL 扫描 → %s" % a.name)
    print("=" * 60)
    args = SimpleNamespace(out=str(json_dir), name=a.name, tracks="",
                           exclude=",".join(exclude))
    pt_clip_scan.run(args)
    jp = json_dir / a.name
    if not jp.is_file():
        print("\n[error] 扫描未产出 %s —— 确认 Pro Tools 已打开目标工程且 PTSL 在线。"
              % a.name)
        return 2

    print("\n" + "=" * 60)
    print("[2/2] 生成交付包（仅数据：json + audio/）")
    print("=" * 60)
    rc = make_delivery_package.build_package(jp, pkg_dir, exclude, light=True)
    if rc != 0:
        print("\n[error] 打包失败（见上方输出）。")
        return rc

    print("\n[done] 交付包就绪：%s\\<工程名>-导入包\\" % pkg_dir)
    print("       剪辑机器上用剪映工具「导入多轨 → 交付包 json（完全离线）」导入。")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
