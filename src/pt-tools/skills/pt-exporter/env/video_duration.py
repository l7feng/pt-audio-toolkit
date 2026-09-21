"""Read MP4 duration (seconds) by parsing the mvhd box."""
import struct
import sys

def mp4_duration(path):
    with open(path, "rb") as f:
        # find 'moov' -> 'mvhd'
        while True:
            header = f.read(8)
            if len(header) < 8:
                return None
            size, boxtype = struct.unpack(">I4s", header)
            boxtype = boxtype.decode("latin1")
            if boxtype == "moov":
                break
            f.seek(size - 8, 1)
        # inside moov, find mvhd
        end = f.tell() + size - 8
        while f.tell() < end:
            sub = f.read(8)
            if len(sub) < 8:
                return None
            ssize, stype = struct.unpack(">I4s", sub)
            stype = stype.decode("latin1")
            if stype == "mvhd":
                ver = f.read(1)[0]
                f.read(3)  # flags
                if ver == 1:
                    f.read(16)  # ctime/mtime
                    timescale = struct.unpack(">I", f.read(4))[0]
                    duration = struct.unpack(">Q", f.read(8))[0]
                else:
                    f.read(8)
                    timescale = struct.unpack(">I", f.read(4))[0]
                    duration = struct.unpack(">I", f.read(4))[0]
                return duration / timescale
            f.seek(ssize - 8, 1)
    return None

for v in ["2.mp4", "3.mp4"]:
    p = rf"D:\DAW-Project\10-誓言D_20260915_7F\Video\{v}"
    d = mp4_duration(p)
    m, s = divmod(int(d), 60)
    print(f"{v}: {d:.2f}s  ({m}:{s:02d})")
