"""Inspect message field structures."""
from ptsl import PTSL_pb2 as pb

for msg_name in ["TimelineLocation", "EM_SourceInfo", "EM_AudioInfo",
                 "EM_VideoInfo", "EM_LocationInfo", "EM_DolbyAtmosInfo",
                 "EM_FileDestination"]:
    msg = getattr(pb, msg_name, None)
    if msg is None:
        print(f"!! {msg_name} not found")
        continue
    print(f"=== {msg_name} ===")
    for f in msg.DESCRIPTOR.fields:
        print(f"  {f.name}  {f.message_type.name if f.message_type else ''}")
    print()
