# -*- coding: utf-8 -*-
"""导出产物质检（P2 · v1.5.0）——「只管导不管验」的补丁。

导出链路此前"命令跑完=成功"，但声道/采样率/时长对不对没人查；
本模块对本次导出落盘的 wav 逐个读头核对，抓「导错了还以为导对了」的静默错误。

纯标准库：手工解析 RIFF/WAVE 头（标准库 wave 模块对 24-bit / WAVE_FORMAT_EXTENSIBLE
等 PT 常见产物支持不全），不依赖外部包，GUI 与测试共用。
"""
import os
import struct

# WAVE 格式码
WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

_RIFF_FMT = struct.Struct("<4sI4s")
_CHUNK_FMT = struct.Struct("<4sI")


class WavHeaderError(ValueError):
    """wav 头解析失败（不是 RIFF / 半截文件 / 异常块布局）。"""


def read_wav_header(path):
    """读 wav 头，返回 dict(channels, sample_rate, bits, frames, duration_sec)。

    支持 PCM / IEEE float / WAVE_FORMAT_EXTENSIBLE（PT 的 24/32-bit 产物常见）。
    失败抛 WavHeaderError。data 块大小为 0 / 0xFFFFFFFF（流式写入未回填）时
    frames 记 -1（无法判时长，不算错误，调用方自行决定是否跳过时长核对）。
    """
    try:
        size = os.path.getsize(path)
        if size < 44:
            raise WavHeaderError("文件过小（%dB），不像有效 wav" % size)
        with open(path, "rb") as fh:
            riff = fh.read(12)
            if len(riff) < 12:
                raise WavHeaderError("头部不足 12 字节")
            tag, _sz, wave = _RIFF_FMT.unpack(riff)
            if tag != b"RIFF" or wave != b"WAVE":
                raise WavHeaderError("不是 RIFF/WAVE 文件")
            channels = sample_rate = bits = None
            data_size = None
            byte_rate = 0
            block_align = 0
            while True:
                head = fh.read(8)
                if len(head) < 8:
                    break
                cid, csz = _CHUNK_FMT.unpack(head)
                if csz > 0x7FFFFFFF:          # 异常块大小，按剩余文件裁
                    csz = max(0, size - fh.tell())
                if cid == b"fmt ":
                    body = fh.read(csz)
                    if len(body) < 16:
                        raise WavHeaderError("fmt 块不足 16 字节")
                    (_fmt_tag, ch, sr, byte_rate, block_align, bits) = \
                        struct.unpack("<HHIIHH", body[:16])
                    channels, sample_rate = ch, sr
                    fmt_tag = _fmt_tag
                    if fmt_tag == WAVE_FORMAT_EXTENSIBLE and len(body) >= 40:
                        # SubFormat GUID 前 2 字节才是真实格式码
                        sub = struct.unpack("<H", body[24:26])[0]
                        fmt_tag = sub
                    if fmt_tag not in (WAVE_FORMAT_PCM, WAVE_FORMAT_IEEE_FLOAT,
                                       WAVE_FORMAT_EXTENSIBLE):
                        raise WavHeaderError("非 PCM 格式（format=0x%04X）" % fmt_tag)
                elif cid == b"data":
                    data_size = csz
                    if channels is not None:
                        break        # fmt 在前 data 在后（常规布局），可停
                    fh.seek(csz + (csz & 1))   # 极少见：data 在 fmt 前，跳过继续
                else:
                    fh.seek(csz + (csz & 1))   # 奇数块补 1 字节 padding
            if channels is None:
                raise WavHeaderError("缺少 fmt 块")
            if data_size is None:
                raise WavHeaderError("缺少 data 块")
            if block_align > 0 and data_size:
                frames = data_size // block_align
            else:
                frames = -1
            dur = (frames / sample_rate) if (sample_rate and frames and frames > 0) else -1.0
            return {
                "channels": channels,
                "sample_rate": sample_rate,
                "bits": bits,
                "frames": frames if data_size else -1,
                "duration_sec": dur,
            }
    except WavHeaderError:
        raise
    except OSError as e:
        raise WavHeaderError("读取失败: %s" % e)
    except struct.error as e:
        raise WavHeaderError("头部解析失败: %s" % e)


def qc_wavs(out_dir, since_ts=0.0, expected_sr=None, expected_bd=None,
            expected_dur_sec=None):
    """质检 out_dir 下 mtime >= since_ts 的 wav 产物（即"本次导出"的文件）。

    返回 (checked, issues)：
      checked = [(path, header_dict), …]   解析成功的文件
      issues  = [(path, reason), …]        异常清单（解析失败也算一条）
    核对项：可解析 / 声道 ≥1 / 采样率 == 期望 / 位深 == 期望 / 时长 > 0 /
    时长 vs 期望（容差 max(2s, 5%)；只报偏短与严重超长——bounce 本应精确）。
    """
    checked, issues = [], []
    wavs = []
    try:
        for name in os.listdir(out_dir):
            p = os.path.join(out_dir, name)
            if os.path.isfile(p) and name.lower().endswith(".wav"):
                try:
                    if os.path.getmtime(p) >= since_ts:
                        wavs.append(p)
                except OSError:
                    pass
    except OSError as e:
        return [], [(out_dir, "输出目录不可读: %s" % e)]
    wavs.sort()
    if not wavs:
        return checked, issues
    # 时长容差：1s 下限 + 2% 相对（PT bounce 帧级精确，QC 抓的是"截断整段"
    # 级别的错误；容差只吸收帧量化/舍入，2s 级别的下限会放过短素材截断）
    tol = max(1.0, (expected_dur_sec or 0) * 0.02)
    for p in wavs:
        try:
            h = read_wav_header(p)
        except WavHeaderError as e:
            issues.append((p, str(e)))
            continue
        checked.append((p, h))
        if (h["channels"] or 0) < 1:
            issues.append((p, "声道数异常: %s" % h["channels"]))
        if expected_sr and h["sample_rate"] != int(expected_sr):
            issues.append((p, "采样率不符: 实际 %s ≠ 期望 %s"
                           % (h["sample_rate"], expected_sr)))
        if expected_bd and h["bits"] not in (None, int(expected_bd)):
            issues.append((p, "位深不符: 实际 %s ≠ 期望 %s" % (h["bits"], expected_bd)))
        dur = h.get("duration_sec") or 0
        if dur <= 0:
            # frames=-1 表示 data 块大小未回填，无法判时长 —— 单独提示不算错误
            if h.get("frames") == -1:
                pass
            else:
                issues.append((p, "时长异常: %s" % dur))
        elif expected_dur_sec:
            if dur < expected_dur_sec - tol:
                issues.append((p, "时长偏短: %.1fs < 期望 %.1fs（可能被截断）"
                               % (dur, expected_dur_sec)))
            elif dur > expected_dur_sec + tol * 3:
                issues.append((p, "时长超长: %.1fs > 期望 %.1fs"
                               % (dur, expected_dur_sec)))
    return checked, issues
