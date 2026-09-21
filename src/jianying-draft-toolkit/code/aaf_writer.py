#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剪映时间线 → AAF（交给 Pro Tools 混音用）。

**AAF 不是「导出」出来的，是「翻译」出来的。**

剪映压根不支持导出 AAF，本模块也没打算让它支持。整条链路只借用剪映一件事
—— 解密草稿（jy-draftc 调它自己的 videoeditor.dll）；拿到明文 JSON 后，
把剪映的时间线模型**翻译**成 AAF 的对象模型，再用 pyaaf2 写文件。

    剪映 tracks[]              → TimelineMobSlot（AAF 里的一条轨）
    track.name                 → SlotName（PT 里看到的轨道名）
    segment.target_timerange   → SourceClip 在时间线上的**位置与长度**
    segment.source_timerange   → SourceClip.StartTime（从素材第几秒取）
    时间线空白                  → Filler（AAF 的空白占位符，不占体积）
    片段修剪后的 WAV            → SourceMob + PCMDescriptor（内嵌 PCM）

为什么 essence 是「片段修剪后」而不是整条素材：
    实测草稿里 1.L.stereo 素材原长 318.9s，只被引用了 98.4s。内嵌整条素材
    等于把 3 倍无用音频塞进 AAF —— 12 轨瞬间逼近 PT 的 2GB 上限。
    只嵌用到的部分，体积**仅随实际用量增长**。

已知限制（与片段模式一致）：剪映的变速/变调特效 AAF 承载不了，导出的是烘焙结果。
"""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from core.host import subprocess_kwargs

AAF_SR = 48000          # AAF 编辑率 = 采样率（音频轨必须这样设）
AAF_BITS = 24

_PCM = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}
_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def _sanitize(name: str, limit: int = 120) -> str:
    name = _ILLEGAL.sub("_", (name or "").strip().strip("."))
    return name[:limit] or "untitled"


def us2samples(us: int, sr: int = AAF_SR) -> int:
    """微秒 → 采样点（AAF 里所有长度/位置都以 edit rate 为单位）"""
    return max(int(round(us / 1_000_000 * sr)), 0)


def render_segment_wav(seg, out_path: Path, sr: int = AAF_SR, bits: int = AAF_BITS) -> bool:
    """把片段的「取材区间」单独渲染成 WAV —— 作为 AAF 的 essence。

    只取 `source_timerange` 那一段；声道数保持素材原样（立体声仍是立体声）。
    """
    src_s = seg.src_start_us / 1e6
    dur_s = max(seg.src_dur_us, 1) / 1e6
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{src_s:.6f}", "-i", str(seg.source_path),
           "-t", f"{dur_s:.6f}",
           "-ar", str(sr), "-c:a", _PCM.get(bits, "pcm_s24le"),
           str(out_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, **subprocess_kwargs(),)
    except Exception:
        return False
    return r.returncode == 0 and Path(out_path).exists()


def write_aaf(tracks, total_us: int, project: str, out_root: Path, cfg: dict):
    """把轨道列表写成 AAF。

    返回 `(是否成功, 说明文本)`。

    `aaf_media_mode`:
      - `media`（默认）→ 额外把片段 WAV 落到 `<输出>/<草稿>/Media/`，
        便于人工核对、复用素材、AAF 万一 Relink 失败时兜底。
      - `embed`        → 只产出单个 .aaf，不留副本。

    ⚠️ 两种模式的 AAF **都是内嵌 essence**（不写外部链接）。原因是 PT 对
    「链接式多声道 WAV」支持不可靠（实测会只剩 ch1），内嵌是唯一稳妥解；
    纯外部链接模式留到 PT 实测通过后再开。
    """
    try:
        import aaf2
        from aaf2.rational import AAFRational
    except ImportError:
        return False, "未安装 pyaaf2（pip install pyaaf2）"

    media_mode = cfg.get("aaf_media_mode", "media") != "embed"
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    # 中间产物放系统临时目录（时间戳命名，从不删除既有目录）
    work_dir = Path(__import__("tempfile").gettempdir()) / f"jy_aaf_{int(time.time())}"
    work_dir.mkdir(parents=True, exist_ok=True)
    media_dir = (out_root / "Media") if media_mode else None
    if media_dir:
        media_dir.mkdir(parents=True, exist_ok=True)

    aaf_path = out_root / f"{_sanitize(project)}.aaf"
    er = AAFRational(AAF_SR, 1)
    used_tracks = 0
    used_clips = 0
    manifest = []

    try:
        with aaf2.open(str(aaf_path), "w") as f:
            dd = f.dictionary.lookup_datadef("Sound")

            comp = f.create.CompositionMob()
            comp.name = project                 # Mob 的 Name 必须是 str，传 bytes 会炸
            f.content.mobs.append(comp)

            slot_id = 1
            for t in tracks:
                segs = [s for s in t.segments
                        if s.tl_dur_us > 0 and Path(s.source_path).exists()]
                if not segs:
                    continue

                slot = comp.create_timeline_slot(er, slot_id=slot_id)
                slot_id += 1
                slot["SlotName"].value = t.display_name     # 中文 / 点号轨名实测无问题

                seq = f.create.Sequence()
                seq["DataDefinition"].value = dd
                parts = []
                cursor = 0

                for i, s in enumerate(segs, 1):
                    wav = work_dir / f"t{t.index:02d}_{i:02d}.wav"
                    if not render_segment_wav(s, wav):
                        print(f"    [warn] 片段渲染失败，留空白: {s.material_name}")
                        continue

                    if media_dir:
                        dst = media_dir / _sanitize(
                            f"{t.display_name}_{i:02d}_{Path(s.material_name).stem}.wav")
                        try:
                            shutil.copy2(wav, dst)
                        except Exception:
                            pass

                    sm = f.create.SourceMob()
                    f.content.mobs.append(sm)               # 必须先 append 再设 descriptor
                    sm.name = f"{t.display_name}_{i:02d}"
                    sm.import_audio_essence(str(wav), edit_rate=er)

                    # 落点前有空隙 → Filler 占位
                    if s.tl_start_us > cursor:
                        fl = f.create.Filler()
                        fl["DataDefinition"].value = dd
                        fl["Length"].value = us2samples(s.tl_start_us - cursor)
                        parts.append(fl)

                    clip = f.create.SourceClip()
                    clip["DataDefinition"].value = dd
                    clip["StartTime"].value = 0             # 素材已在渲染时裁好，从头取
                    clip["Length"].value = us2samples(s.tl_dur_us)
                    clip["SourceID"].value = sm.mob_id
                    clip["SourceMobSlotID"].value = 1
                    parts.append(clip)

                    cursor = s.tl_start_us + s.tl_dur_us
                    used_clips += 1
                    manifest.append({
                        "track": t.display_name,
                        "index": i,
                        "material": s.material_name,
                        "timeline_start_s": round(s.tl_start_us / 1e6, 3),
                        "duration_s": round(s.tl_dur_us / 1e6, 3),
                    })

                # 尾部补齐到时间线总长（跟随视频轨）
                if cursor < total_us:
                    fl = f.create.Filler()
                    fl["DataDefinition"].value = dd
                    fl["Length"].value = us2samples(total_us - cursor)
                    parts.append(fl)

                if not parts:
                    continue
                seq["Components"].value = parts
                slot["Segment"].value = seq
                used_tracks += 1

        if used_tracks == 0:
            return False, "没有任何可用轨道（源文件全部缺失？）"

        # 配套清单（AAF 是二进制难核对，给一份人类可读的对照表）
        try:
            (out_root / "timeline.json").write_text(
                json.dumps({"project": project,
                            "total_s": round(total_us / 1e6, 3),
                            "clips": manifest},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    size_mb = aaf_path.stat().st_size / 1024 / 1024 if aaf_path.exists() else 0
    extra = f" + Media/({used_clips} 个片段 WAV)" if media_mode else ""
    return True, f"{aaf_path.name}（{used_tracks} 轨 / {used_clips} 片段 / {size_mb:.1f}MB）{extra}"
