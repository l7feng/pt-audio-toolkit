"""Dump PTSL enums needed for export_mix / export_clips_as_files."""
from ptsl import PTSL_pb2 as pb

def dump(enum_name):
    e = getattr(pb, enum_name, None)
    if e is None:
        print(f"!! {enum_name} not found")
        return
    print(f"=== {enum_name} ===")
    for k in sorted(e.keys()):
        print(f"  {k} = {e.Value(k)}")

for name in [
    "EM_FileType", "EM_SourceType", "SampleRate", "BitDepth",
    "ExportFormat", "TripleBool", "EM_FileDestination",
    "CompressionType", "EM_DeliveryFormat", "EM_VideoExportOptions",
]:
    dump(name)
    print()
