"""Gate runner: python3 -m gates.run <GATE_ID> <project_root> [--no-record]

Returns PASS, FAIL or TOOL_ERROR (exit 0, 1, 2) and records artifacts/gates/<ID>.json unless --no-record.
Implemented gates are listed in IMPLEMENTED; anything else is NOT IMPLEMENTED and exits 2 (never PASS).
"""
from __future__ import annotations

import json
import sys
import traceback

from gates import stage_gates
from gates.common import FAIL, PASS, TOOL_ERROR, ToolError, now_utc, record_gate
from gates.gp_assembly import gp

GATES = ["G0", "G1", "G2", "G2F", "G3S", "G3K", "G3", "G4a", "G4b", "G4c", "G4d", "G5", "G6", "GP", "PROC"]
IMPLEMENTED = dict(stage_gates.GATES, GP=gp)
NOT_IMPLEMENTED = [g for g in GATES if g not in IMPLEMENTED and g != "PROC"]  # PROC = python3 -m gates.procedure


def run_gate(gate_id, project_root, record=True, **kw):
    """Returns the gate record dict; record["result"] is PASS, FAIL or TOOL_ERROR."""
    if gate_id not in IMPLEMENTED:
        return {"gate": gate_id, "result": TOOL_ERROR, "checks": [], "inputs": [], "checked_at_utc": now_utc(),
                "error": f"{gate_id}: NOT IMPLEMENTED"}
    try:
        rec = IMPLEMENTED[gate_id](project_root, **kw)
    except ToolError as e:
        rec = {"gate": gate_id, "result": TOOL_ERROR, "checks": [], "inputs": [], "checked_at_utc": now_utc(), "error": str(e)}
    except Exception:  # noqa: BLE001 - a gate crash is a tool error, never PASS
        rec = {"gate": gate_id, "result": TOOL_ERROR, "checks": [], "inputs": [], "checked_at_utc": now_utc(),
               "error": traceback.format_exc()[-2000:]}
    if record and rec["result"] in (PASS, FAIL):
        rec["record_path"] = record_gate(project_root, rec)
    return rec


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 2:
        print(__doc__)
        return 2
    rec = run_gate(a[0], a[1], record="--no-record" not in a)
    print(json.dumps({k: rec[k] for k in rec if k != "comparisons"}, indent=1, default=str))
    return {PASS: 0, FAIL: 1}.get(rec["result"], 2)


if __name__ == "__main__":
    sys.exit(main())
