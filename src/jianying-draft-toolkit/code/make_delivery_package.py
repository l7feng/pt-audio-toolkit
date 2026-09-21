#!/usr/bin/env python3
"""生成「交付包」—— 把 PT 工程信息 + 音频素材打包，供他人（剪辑）在自己机器上导入剪映。

为什么需要这东西：
    `pt-clips.json` 由 PTSL 从「在线的 Pro Tools」提取，里面的 `online_files[].location`
    记录的是**本机绝对路径**（如 `D:\\DAW-Project\\...\\22\\Audio Files\\`）。
    把这样一份 json 直接发给剪辑，他机器上没有该路径 → 导入器找不到素材。

    本脚本把 json 里的路径**改成相对路径**，并把实际用到的音频文件复制到包内
    `audio/` 目录，同时把 L/R 单声道预先合成为立体声，让剪辑侧「解压即用」、
    **完全不需要 Pro Tools、不需要任何原始工程路径**。

交付包结构：
    <工程名>-导入包/
    ├── 01-使用说明.txt          ← 给剪辑看的三步说明
    ├── <工程名>.pt-clips.json    ← 结构数据（路径已改为相对）
    ├── audio/                    ← 音频素材（含预合成的 *.stereo.wav）
    └── （导入 exe 由打包环节放入）

用法：
    python make_delivery_package.py <pt-clips.json> [输出目录] [--exclude ...] [--dry-run]
"""

import argparse
import json
import shutil
import sys
import wave
from pathlib import Path

# 复用导入器的解析逻辑，保证「包内音频」与「导入时实际使用的文件」完全一致
sys.path.insert(0, str(Path(__file__).parent))
import import_audio as core  # noqa: E402


def merge_stereo_to(l_path: Path, r_path: Path, dest: Path) -> bool:
    """把 L/R 两个单声道 wav 交错合成立体声写入 dest（无损，不走 ffmpeg）。

    返回 True 表示成功写入；False 表示无法合成（采样率/位深不匹配等）。
    """
    try:
        with wave.open(str(l_path), "rb") as wl:
            nl, sw, fr, nf = (wl.getnchannels(), wl.getsampwidth(),
                              wl.getframerate(), wl.getnframes())
            ldata = wl.readframes(nf)
        with wave.open(str(r_path), "rb") as wr:
            nr, sw2, fr2, nf2 = (wr.getnchannels(), wr.getsampwidth(),
                                 wr.getframerate(), wr.getnframes())
            rdata = wr.readframes(nf2)
        if sw != sw2 or fr != fr2 or nl != 1 or nr != 1:
            return False
        n = min(nf, nf2)
        inter = bytearray()
        for i in range(n):
            s = i * sw
            inter += ldata[s:s + sw]
            inter += rdata[s:s + sw]
        dest.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dest), "wb") as wo:
            wo.setnchannels(2)
            wo.setsampwidth(sw)
            wo.setframerate(fr)
            wo.writeframes(bytes(inter))
        return True
    except Exception as e:
        print(f"[warn] 立体声合成失败 {l_path.name}: {e}")
        return False


README_TEMPLATE = """剪映多轨音频导入 —— 使用说明
================================================

这个包里是什么？
  - {json_name}    : 工程结构数据（每条轨道的音频块位置/长度/淡入淡出）
  - audio\\         : 对应的音频素材文件
  - 导入工具.exe   : 双击运行（放在本文件夹里）

怎么用（三步）
------------------------------------------------
1. 双击运行「导入工具.exe」

2. 切到「② 导入多轨」页
   · 数据源选「交付包 json（完全离线）」
   · 点「浏览…」选中本文件夹里的  {json_name}
     （音频会自动从同级的 audio\\ 目录读取，不用另外指路径）
   · 下方会显示「✓ xx 轨 / xx 片段｜音频 xx 个」，看到即正常

3. 选目标草稿 → 点「② 导入到剪映草稿」
   想先看效果可先点「预演（不写入）」，不写任何文件

注意事项
------------------------------------------------
· 导入前请【完全退出剪映】（含托盘图标、后台进程）。
  剪映开着时写入会被它内存里的旧内容覆盖，导入会看不到效果。
  工具会自动检测：剪映没退出时导入按钮是灰的，退出后自动变亮。
· 本包不需要 Pro Tools，也不需要任何原始工程路径。
· 包里的 *.stereo.wav 是预先合成的立体声版本，请勿删除或改名。
· 导入只写剪映草稿，不改动任何原始音频文件。
· 导入前草稿会自动备份为同名 .jybak，需要时可还原。
· 必须整个文件夹一起用（exe 旁还有 _internal\\ 和 tools\\）。

生成信息
------------------------------------------------
工程名称 : {session_name}
导入轨道 : {import_track_count} 条（PT 工程共 {track_count} 轨，已过滤辅助轨）
片段数量 : {clip_count}
生成时间 : {generated_at}
"""


def build_package(json_path: Path, out_dir: Path, exclude: tuple,
                  dry_run: bool = False, light: bool = False,
                  exe_src: Path | None = None) -> int:
    """生成交付包。

    `light=True` 时只产出「json + audio/」两样（不含说明书与 exe）——
    适合「说明书与 exe 早已一次性做好、每次交付只需重跑数据」的场景。
    """
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    session = doc.get("session", {}) or {}
    session_name = (session.get("name") or json_path.stem).strip() or json_path.stem
    json_name = f"{session_name}.pt-clips.json"

    # 1) 用导入器自身的解析逻辑取出「实际会用到的素材」
    #    这样能保证包内文件与导入时寻址的文件严格一致（含 L/R 合成规则）
    print(f"[1/4] 解析工程结构: {json_path.name}")
    src_dir = core.resolve_audio_dir(json_path, doc, None)
    if src_dir is None:
        print("[错误] 找不到素材目录。json 里的 online_files 路径在本机不存在，"
              "且 json 同级没有 audio/ 目录。")
        return 1
    print(f"       素材源目录: {src_dir}")

    # 复用导入器的 L/R 合成：它在系统临时目录产出 *.stereo.wav，
    # 稍后我们把这些成品直接拷进包里，剪辑侧无需再合成。
    rows = core.parse_pt_clips(json_path, exclude, audio_dir=src_dir)
    if not rows:
        print("[错误] 未解析出任何片段，检查 --exclude 设置。")
        return 1
    print(f"       片段 {len(rows)} 个，涉及素材文件 {len({r['source'] for r in rows})} 个")

    # 2) 规划包内文件名：L/R 合成件用 *.stereo.wav，单声道保持原名
    used = {}          # 源文件 -> 包内相对名
    for r in rows:
        src = Path(r["source"])
        used.setdefault(src, "audio/" + src.name)

    if dry_run:
        print("\n[dry-run] 将复制以下素材到包内 audio/ :")
        for src, rel in sorted(used.items(), key=lambda kv: kv[1]):
            print(f"    {src.name:50s} {src.stat().st_size/1048576:8.2f} MB")
        total = sum(s.stat().st_size for s in used)
        print(f"\n[dry-run] 合计 {len(used)} 个文件，{total/1048576:.1f} MB")
        return 0

    # 3) 建包
    #    注意：不删除旧包目录 —— 逐个覆盖文件即可（省去一次全量复制，也避免
    #    触发「批量删除确认」。旧包中已不用的素材会残留，属可接受折中，
    #    需要绝对干净时请手动清空输出目录后重跑）。
    pkg = out_dir / f"{session_name}-导入包"
    audio_out = pkg / "audio"
    audio_out.mkdir(parents=True, exist_ok=True)

    print(f"[2/4] 复制素材到 {audio_out.relative_to(out_dir)}")
    copied = 0
    for src, rel in sorted(used.items(), key=lambda kv: kv[1]):
        dest = pkg / rel
        try:
            if dest.is_file() and dest.stat().st_size == src.stat().st_size:
                continue                 # 已存在且大小一致 → 跳过，加快重跑
            shutil.copy2(src, dest)
            copied += 1
        except Exception as e:
            print(f"       [warn] 复制失败 {src.name}: {e}")
    print(f"       新增/更新 {copied} 个文件（共 {len(used)} 个）")

    # 4) 写「路径已相对化」的 json
    #    这里有三处必须同步改写，缺一不可（否则剪辑侧找不到素材）：
    #      a. online_files[].location  → 指向包内 audio/
    #      b. clip_file_map 的值       → 改成**包内实际文件名**
    #         （解析出的 source 可能是 L/R 合成件 `X.L.stereo.wav`，
    #          而原始映射记的是 `X.L.wav`；不改则导入器按旧名寻址必然失败）
    #      c. 音效类「单引用」片段名去掉了 `-NN` 序号，映射也要按去序号名补一条
    print("[3/4] 改写 json 路径与文件名映射")
    doc2 = json.loads(json.dumps(doc))

    # a) 相对化素材目录
    #    注意：清单要列「包内**实际存在**的文件名」。若照抄原始 online_files
    #    （如 `1.L.wav`），而包内实际是合成件 `1.L.stereo.wav`，导入器的
    #    「在线文件清单校验」会把所有素材挡掉 → 必须按包内实况重建。
    pkg_files = sorted({Path(r["source"]).name for r in rows})
    doc2["online_files"] = [{"name": n, "location": "audio/"} for n in pkg_files]

    # b) 建立「原映射文件名 -> 包内文件名」的换算表
    #    rows 里每一行的 _src_name 是解析前的原始素材名（如 `1.L.wav`），
    #    source 是包内将要使用的文件（如 `1.L.stereo.wav`）。
    name_map = {}
    for r in rows:
        orig = r.get("_src_name") or ""
        pkg_name = Path(r["source"]).name
        if orig:
            name_map[orig] = pkg_name
        # 已经是立体声合成件的，原始名通常是去 `.stereo` 的版本
        if pkg_name.endswith(".stereo.wav"):
            name_map.setdefault(pkg_name[: -len(".stereo.wav")] + ".wav", pkg_name)

    new_map = {}
    remapped = 0
    for clip_key, fname in (doc2.get("clip_file_map") or {}).items():
        if fname in name_map and name_map[fname] != fname:
            new_map[clip_key] = name_map[fname]
            remapped += 1
        else:
            new_map[clip_key] = fname
    doc2["clip_file_map"] = new_map
    print(f"       文件名映射修正 {remapped} 条")

    # c) 音效类片段名去序号（`X-01.L` → `X.L`）需补映射，导入器回退查找才会命中
    base_names = {k: v for k, v in new_map.items()}
    import re as _re
    for clip_key, fname in list(base_names.items()):
        stripped = _re.sub(r"-\d{2}(?=\.[LR]$)", "", clip_key)
        if stripped != clip_key and stripped not in doc2["clip_file_map"]:
            doc2["clip_file_map"][stripped] = fname

    doc2["_delivery_package"] = {
        "note": "路径已相对化，音频位于本包 audio/ 目录；文件名映射已同步修正；不需 Pro Tools。",
        "original_location": (doc.get("online_files") or [{}])[0].get("location", ""),
        "generated_at": session.get("scanned_at", ""),
        "audio_files": len(used),
    }
    (pkg / json_name).write_text(
        json.dumps(doc2, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5) 说明书 / exe —— 都是「一次性做好、长期复用」的固定资产，
    #    light 模式下不生成、不复制（你只需把现成的那份一起丢进包里）。
    from datetime import datetime
    n_tracks = len({r["_pt_track"] for r in rows if r.get("_pt_track")})
    produced = [json_name, f"audio\\ ({len(used)} 文件)"]

    if not light:
        readme = README_TEMPLATE.format(
            json_name=json_name,
            session_name=session_name,
            import_track_count=n_tracks,
            track_count=doc.get("track_count", "?"),
            clip_count=len(rows),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
        (pkg / "01-使用说明.txt").write_text(readme, encoding="utf-8")
        produced.append("01-使用说明.txt")

    # exe：指定了来源就复制进包（放在包根，与 json 同级）
    if exe_src is not None:
        if exe_src.is_file():
            shutil.copy2(exe_src, pkg / exe_src.name)
            produced.append(exe_src.name)
        elif exe_src.is_dir():
            dest = pkg / exe_src.name
            shutil.copytree(exe_src, dest, dirs_exist_ok=True)
            produced.append(exe_src.name + "\\")

    total_mb = sum(f.stat().st_size for f in pkg.rglob("*") if f.is_file()) / 1048576
    print(f"[4/4] 完成")
    print(f"\n交付包: {pkg}")
    print(f"  体积  : {total_mb:.1f} MB")
    print(f"  本次产出: {' / '.join(produced)}")
    if light:
        print(f"\n  （精简模式：说明书与 exe 未生成 —— 请把现成的那两份一起放进该目录）")
    print(f"\n下一步：整个文件夹压缩后发给剪辑即可。")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="生成剪映导入交付包（离线/跨设备用：json 路径相对化 + 音频随包）")
    ap.add_argument("pt_clips", type=Path, help="PT 解析结果 pt-clips.json")
    ap.add_argument("out_dir", nargs="?", type=Path, default=Path("."),
                    help="包输出目录（默认当前目录）")
    ap.add_argument("--exclude", default="", help="排除轨道关键词（与导入器一致）")
    ap.add_argument("--keep-aux", action="store_true", help="保留辅助轨")
    ap.add_argument("--dry-run", action="store_true", help="只列出要打包的素材，不实际复制")
    ap.add_argument("--light", action="store_true",
                    help="精简模式：只产出 json + audio/，不生成说明书（说明书与 exe 复用现成的那份）")
    ap.add_argument("--with-exe", type=Path, default=None,
                    help="把导入 exe（文件或文件夹）复制进包内")
    args = ap.parse_args()

    if not args.pt_clips.is_file():
        print(f"[错误] 找不到 {args.pt_clips}")
        sys.exit(1)

    ex = [s.strip().lower() for s in args.exclude.split(",") if s.strip()]
    if not ex and not args.keep_aux:
        ex = list(core.DEFAULT_EXCLUDE)

    sys.exit(build_package(args.pt_clips, args.out_dir, tuple(ex), args.dry_run,
                           light=args.light, exe_src=args.with_exe))


if __name__ == "__main__":
    main()
