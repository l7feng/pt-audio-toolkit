"""Try bounce with different source type/name combos on a 10-sec selection."""
import os
from ptsl import Engine
from ptsl import PTSL_pb2 as pb

OUT = r"D:\Ai-Files\Agent-Preset\pt-exporter\test_out"
os.makedirs(OUT, exist_ok=True)

pt = Engine(company_name="local", application_name="pt-exporter")
pt.set_timeline_selection(in_time="00:00:30:00", out_time="00:00:40:00")

audio = pb.EM_AudioInfo(
    compression_type=pb.CType_PCM, export_format=pb.EFormat_Mono,
    bit_depth=pb.Bit24, sample_rate=pb.SRate_48000,
    pad_to_frame_boundary=pb.TBool_False,
    delivery_format=pb.EM_DF_FilePerMixSource,
)
video = pb.EM_VideoInfo(include_video=pb.TBool_False, export_option=pb.VE_None,
                        replace_timecode_track=pb.TBool_False)
loc = pb.EM_LocationInfo(import_after_bounce=pb.TBool_False,
                         file_destination=pb.EM_FD_Directory, directory=OUT + "\\")
dolby = pb.EM_DolbyAtmosInfo()

attempts = [
    ("DX-BUS", "DX-BUS-Master", pb.EMSType_Bus),
    ("MX-BUS", "MX-BUS-Master", pb.EMSType_Bus),
    ("MasterOut", "Master Hole", pb.EMSType_Output),
]

for label, name, stype in attempts:
    src = pb.EM_SourceInfo(source_type=stype, name=name)
    print(f"--- try {label} name={name!r} ---")
    try:
        pt.export_mix(base_name=f"test_{label}_{name or 'default'}",
                      file_type=pb.EM_WAV, sources=[src],
                      audio_info=audio, video_info=video, location_info=loc,
                      dolby_atmos_info=dolby, offline_bounce=pb.TBool_False)
        print("  OK")
    except Exception as e:
        print(f"  FAIL: {e}")

print("--- files ---")
for f in os.listdir(OUT):
    print(f"  {f}  {os.path.getsize(os.path.join(OUT,f))}")

pt.close()
