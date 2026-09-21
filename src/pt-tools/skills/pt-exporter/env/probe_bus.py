"""Probe monitor output path and try different source names/types."""
from ptsl import Engine

pt = Engine(company_name="local", application_name="pt-exporter")

print("monitor output path:", pt.get_monitor_output_path())

# Show track names/types again for reference
print("\n=== tracks (name : type_num) ===")
for t in pt.track_list():
    print(f"  {t.name!r}  type={t.type}")

pt.close()
