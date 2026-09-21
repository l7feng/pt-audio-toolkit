"""Inspect current Pro Tools session: name, sample rate, length, track list."""
from ptsl import Engine

pt = Engine(company_name="local", application_name="pt-exporter")

print("=== session ===")
print("name:", pt.session_name())
print("path:", pt.session_path())
print("sample_rate:", pt.session_sample_rate())
print("length:", pt.session_length())
print("timecode_rate:", pt.session_timecode_rate())

print("\n=== tracks ===")
tracks = pt.track_list()
for t in tracks:
    name = getattr(t, "name", str(t))
    ttype = getattr(t, "track_type", getattr(t, "type", ""))
    print(f"- {name}  [{ttype}]")

pt.close()
