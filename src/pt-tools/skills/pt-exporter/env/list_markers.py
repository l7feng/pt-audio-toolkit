"""List memory locations (markers) and current timeline selection."""
from ptsl import Engine

pt = Engine(company_name="local", application_name="pt-exporter")

print("=== memory locations ===")
for ml in pt.get_memory_locations():
    print(" ", ml)

print("\n=== current timeline selection ===")
try:
    print(pt.get_timeline_selection())
except Exception as e:
    print("err:", e)

pt.close()
