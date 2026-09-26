# -*- coding: utf-8 -*-
"""PT-Deliver 交付格式：schema 常量 + 校验器（D 档决策 3 后半 · 2026-09-27）

背景
----
C 批（``b736fb3``）的「交付包一步直出」已经产出事实格式：一个 json 清单 +
``audio/`` 素材目录，json 里带 ``schema_version``。它一直缺三样东西：
**正式名字**、**字段说明**、**校验器**（导入端拿到包只能"试着读"，坏包要到
导入失败才知道哪里坏）。

本模块把这四件事补齐：

1. **命名**：格式正式定名 **PT-Deliver**（json + 目录，不做二进制）；
2. **版本**：沿用既有 ``schema_version`` 字段（当前 ``1.1``）——既有产物
   **无需迁移**，直接就是合法的 PT-Deliver 1.1 包；
3. **校验器**：结构校验（纯 json，不碰盘）+ 包校验（素材存在性 / md5 / 时长）；
4. **兼容规则**：``upgrade()`` 把旧版 doc 补齐成当前版本可读形态。

与 AAF 的关系：AAF 是**对外交换**格式（给别的 DAW/剪辑），PT-Deliver 是
**内部流水线**格式（PT → 剪映），两者不冲突，可并存。

⚠️ 纯逻辑层：**不 import tkinter**，可独立跑测试。
"""
import hashlib
import os

# ── 格式标识 ────────────────────────────────────────────────
SPEC_NAME = "PT-Deliver"
#: 当前写入版本（与 pt-clips.json 的 schema_version 同字段、同语义）
SPEC_VERSION = "1.1"
#: 本校验器能读取的版本（新版本若只是加可选字段，仍可读）
SUPPORTED_VERSIONS = ("1.0", "1.1")

#: 必需顶层字段（缺任一即视为结构损坏）
REQUIRED_FIELDS = ("session", "online_files", "tracks", "track_meta")

#: 素材子目录（包内相对路径）
AUDIO_SUBDIR = "audio"


# ── 兼容：旧版本 doc 补齐 ────────────────────────────────────
def upgrade(doc):
    """把旧版 doc 补齐成当前版本可读形态（**原地补默认、不改既有值**）。

    规则（与 config 的合并式落盘同源）：只加缺失键，用户/生产者已写的
    值一律保留。未知的新版本（比 SPEC_VERSION 大）原样返回并记 warning。
    """
    if not isinstance(doc, dict):
        return doc, ["文档不是 dict，无法校验"]

    warns = []
    ver = str(doc.get("schema_version") or "")
    if not ver:
        doc["schema_version"] = "1.0"
        warns.append("缺少 schema_version，按 1.0 处理")
        ver = "1.0"

    if ver == "1.0":
        # 1.0 → 1.1：1.1 新增 track_meta / clip_file_map / source / scanned_at
        if "track_meta" not in doc:
            doc["track_meta"] = []
            warns.append("1.0 → 1.1：补齐 track_meta=[]")
        if "clip_file_map" not in doc:
            doc["clip_file_map"] = {}
            warns.append("1.0 → 1.1：补齐 clip_file_map={}")
        if "source" not in doc:
            doc["source"] = ""
        if "scanned_at" not in doc:
            doc["scanned_at"] = ""
    elif ver not in SUPPORTED_VERSIONS:
        warns.append("未知版本 %s（本校验器支持 %s）——按原样读取，可能有字段缺失"
                     % (ver, ", ".join(SUPPORTED_VERSIONS)))
    return doc, warns


# ── 结构校验（纯 json，不碰盘）────────────────────────────────
def validate_structure(doc):
    """校验 json 清单结构，返回 (errors, warnings)。

    errors 非空 = 这个包**不该**被导入；warnings 只是提示。
    """
    errors, warns = [], []
    if not isinstance(doc, dict):
        return ["文档不是 dict"], []

    doc, up_warns = upgrade(doc)
    warns.extend(up_warns)

    ver = str(doc.get("schema_version") or "")
    if ver not in SUPPORTED_VERSIONS:
        errors.append("schema_version=%r 不受支持（支持：%s）"
                      % (ver, ", ".join(SUPPORTED_VERSIONS)))

    for key in REQUIRED_FIELDS:
        if key not in doc:
            errors.append("缺少必需字段: %s" % key)

    sess = doc.get("session")
    if isinstance(sess, dict):
        if not str(sess.get("name") or "").strip():
            warns.append("session.name 为空（导入端将无法按工程名归档）")
    elif "session" in doc:
        errors.append("session 不是 dict")

    online = doc.get("online_files")
    if isinstance(online, list):
        names = {str(f.get("name") or "") for f in online if isinstance(f, dict)}
        if not names:
            errors.append("online_files 为空 —— 没有素材可导入")
        # clip_file_map 的值必须能在素材清单里找到，否则导入端会按旧名寻址失败
        cmap = doc.get("clip_file_map")
        if isinstance(cmap, dict):
            missing = sorted({v for v in cmap.values()
                              if isinstance(v, str) and v and v not in names})
            if missing:
                errors.append("clip_file_map 指向 %d 个不在 online_files 里的文件"
                              "（例：%s）" % (len(missing), missing[:3]))
    elif "online_files" in doc:
        errors.append("online_files 不是 list")

    tracks = doc.get("tracks")
    if isinstance(tracks, list):
        if not tracks:
            warns.append("tracks 为空（工程里没有可导出轨？）")
        n_clips = sum(len(t.get("clips") or []) for t in tracks
                      if isinstance(t, dict))
        if n_clips == 0:
            warns.append("tracks 里没有任何片段（clips 全空）")
    elif "tracks" in doc:
        errors.append("tracks 不是 list")

    return errors, warns


# ── 包校验（含文件）──────────────────────────────────────────
def _md5(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def validate_package(doc, pkg_dir, check_md5=True, check_duration=False):
    """校验一个 PT-Deliver **包目录**，返回 (errors, warnings, stats)。

    在结构校验之上追加：素材存在性（``audio/`` 下）、md5 清单（可选）、
    时长对齐（可选，需读 WAV 头）。stats 给出计数便于日志展示。
    """
    errors, warns = validate_structure(doc)
    stats = {"files": 0, "missing": 0, "total_bytes": 0, "clips": 0}

    if not pkg_dir or not os.path.isdir(pkg_dir):
        errors.append("包目录不存在: %s" % pkg_dir)
        return errors, warns, stats

    audio_dir = os.path.join(pkg_dir, AUDIO_SUBDIR)
    names = [str(f.get("name") or "") for f in (doc.get("online_files") or [])
             if isinstance(f, dict) and f.get("name")]
    stats["files"] = len(names)
    stats["clips"] = sum(len(t.get("clips") or [])
                         for t in (doc.get("tracks") or []) if isinstance(t, dict))

    if not os.path.isdir(audio_dir):
        errors.append("包内缺少 %s/ 目录: %s" % (AUDIO_SUBDIR, audio_dir))
        return errors, warns, stats

    present = set(os.listdir(audio_dir))
    missing = [n for n in names if n not in present]
    stats["missing"] = len(missing)
    if missing:
        errors.append("audio/ 下缺少 %d 个素材（例：%s）"
                      % (len(missing), missing[:3]))

    for n in names:
        p = os.path.join(audio_dir, n)
        if os.path.isfile(p):
            stats["total_bytes"] += os.path.getsize(p)

    if check_md5:
        md5s = {}
        for n in names:
            p = os.path.join(audio_dir, n)
            if os.path.isfile(p):
                try:
                    md5s[n] = _md5(p)
                except OSError as e:
                    warns.append("md5 计算失败 %s: %s" % (n, e))
        stats["md5"] = md5s

    if check_duration:
        try:
            from . import qc
        except Exception:
            qc = None
            warns.append("时长对齐跳过：qc 模块不可用")
        if qc is not None:
            bad = []
            for n in names:
                p = os.path.join(audio_dir, n)
                if not os.path.isfile(p) or not n.lower().endswith(".wav"):
                    continue
                try:
                    info = qc.read_wav_header(p)
                except Exception as e:
                    warns.append("时长读取失败 %s: %s" % (n, e))
                    continue
                dur = (info or {}).get("duration") if isinstance(info, dict) else None
                if dur is not None and dur <= 0:
                    bad.append(n)
            if bad:
                errors.append("%d 个 WAV 时长为 0（例：%s）" % (len(bad), bad[:3]))

    return errors, warns, stats


def describe(doc):
    """一行摘要（日志/UI 展示用）。"""
    sess = doc.get("session") if isinstance(doc, dict) else None
    name = (sess or {}).get("name", "?") if isinstance(sess, dict) else "?"
    return "%s v%s · %s · %d 素材 / %d 轨" % (
        SPEC_NAME, (doc or {}).get("schema_version", "?"), name,
        len((doc or {}).get("online_files") or []),
        len((doc or {}).get("tracks") or []))
