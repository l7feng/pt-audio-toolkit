from ptsl import PTSL_pb2 as pb

for n in ["GetExportMixSourceListRequestBody", "GetExportMixSourceListResponseBody"]:
    m = getattr(pb, n, None)
    print(f"=== {n} ===")
    if m is None:
        print("  NOT FOUND"); continue
    for f in m.DESCRIPTOR.fields:
        print(f"  {f.name}")
