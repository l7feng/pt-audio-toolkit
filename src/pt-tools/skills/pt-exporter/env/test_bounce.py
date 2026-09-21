"""Live test: bounce 10 seconds of DX BUS to a temp folder via export_mix."""
import os
from ptsl import Engine
from ptsl import PTSL_pb2 as pb

OUT = r"D:\Ai-Files\Agent-Preset\pt-exporter\test_out"
os.makedirs(OUT, exist_ok=True)

pt = Engine(company_name="local", application_name="pt-exporter")

source = pb.EM_SourceInfo(source_type=pb.EMSType_Bus, name="DX BUS")

audio = pb.EM_AudioInfo(
    compression_type=pb.CType_PCM,
    export_format=pb.EFormat_Mono,
    bit_depth=pb.Bit24,
    sample_rate=pb.SRate_48000,
    pad_to_frame_boundary=pb.TBool_False,
    delivery_format=pb.EM_DF_FilePerMixSource,
)

video = pb.EM_VideoInfo(
    include_video=pb.TBool_False,
    export_option=pb.VE_None,
    replace_timecode_track=pb.TBool_False,
)

loc = pb.EM_LocationInfo(
    import_after_bounce=pb.TBool_False,
    file_destination=pb.EM_FD_Directory,
    directory=OUT + "\\",
)

dolby = pb.EM_DolbyAtmosInfo()

start = pb.TimelineLocation(location="00:00:00:00")
end = pb.TimelineLocation(location="00:00:10:00")

print("setting timeline selection 00:00:30:00 -> 00:00:40:00 ...")
pt.set_timeline_selection(in_time="00:00:30:00", out_time="00:00:40:00")
print("selection now:", pt.get_timeline_selection())

print("bounce starting...")
try:
    pt.export_mix(
        base_name="test_DXBUS",
        file_type=pb.EM_WAV,
        sources=[source],
        audio_info=audio,
        video_info=video,
        location_info=loc,
        dolby_atmos_info=dolby,
        offline_bounce=pb.TBool_False,
    )
    print("bounce returned OK")
except Exception as e:
    print(f"bounce FAILED: {type(e).__name__}: {e}")

print("--- files in output ---")
for f in os.listdir(OUT):
    p = os.path.join(OUT, f)
    print(f"  {f}  {os.path.getsize(p)} bytes")

pt.close()
