"""List all PTSL CommandId names containing bounce/export/track."""
from ptsl import PTSL_pb2 as pb

print("=== bounce/export related commands ===")
for k in sorted(pb.CommandId.keys()):
    if any(w in k.lower() for w in ["bounce", "export", "track"]):
        print(f"  {k} = {pb.CommandId.Value(k)}")
