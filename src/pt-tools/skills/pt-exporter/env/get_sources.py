"""Call GetExportMixSourceList for each source type."""
from ptsl import Engine
from ptsl.ops import Operation
from ptsl import PTSL_pb2 as pb


class CId_GetExportMixSourceList(Operation):
    pass


pt = Engine(company_name="local", application_name="pt-exporter")

for stype_name in ["EMSType_PhysicalOut", "EMSType_Bus", "EMSType_Output", "EMSType_Renderer"]:
    stype = getattr(pb, stype_name)
    op = CId_GetExportMixSourceList(type=stype)
    try:
        pt.client.run(op)
        print(f"=== {stype_name} ===")
        print(op.response)
    except Exception as e:
        print(f"--- {stype_name} FAIL: {e} ---")

pt.close()
