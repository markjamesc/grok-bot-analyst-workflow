"""Gate runner: python3 -m gates.run <GATE_ID> <project_root> [--no-record] [--ledger=<path>] [--attempt=<id>]
(--ledger: G5P only)

Returns PASS, FAIL or TOOL_ERROR (exit 0, 1, 2) and records artifacts/gates/<ID>.json unless --no-record.
Implemented gates (G0-G6, G5P, GD, GP) are listed in IMPLEMENTED; an unknown gate id is TOOL_ERROR and exits 2 (never PASS).

Attempts (known fix 1, 2026-11-22): every run has an attempt id (given with --attempt=<id>, or generated) and, when
recorded, its outcome is written once to artifacts/gates/attempts/<id>.json, including TOOL_ERROR. A TOOL_ERROR also
replaces the current record artifacts/gates/<ID>.json, so a failed retry can never leave an older PASS current. The
coordinating role advances only when `python3 -m gates.attempt <GATE_ID> <root> <attempt id>` exits 0 for the attempt it
requested (gates/attempt.py). A reused attempt id is refused (TOOL_ERROR) and nothing is run.
"""
from __future__ import annotations

import json
import sys
import traceback

from gates import attempt as A
from gates import stage_gates
from gates.common import FAIL, PASS, TOOL_ERROR, ToolError, now_utc, record_gate
from gates.derivability import gd
from gates.gp_assembly import gp
from gates.packet import g0

GATES = ["G0", "GD", "G1", "G2", "G2F", "G3S", "G3K", "G3", "G4a", "G4b", "G4c", "G4d", "G5", "G5P", "G6", "GP", "PROC"]
IMPLEMENTED = dict(stage_gates.GATES, G0=g0, GD=gd, GP=gp)
NOT_IMPLEMENTED = [g for g in GATES if g not in IMPLEMENTED and g != "PROC"]  # PROC = python3 -m gates.procedure


def run_gate(gate_id, project_root, record=True, attempt_id=None, **kw):
    """Returns the gate record dict; record["result"] is PASS, FAIL or TOOL_ERROR; record["attempt_id"] names the attempt."""
    attempt_id = attempt_id if attempt_id is not None else A.new_attempt_id(gate_id)
    if gate_id not in IMPLEMENTED:
        return {"gate": gate_id, "result": TOOL_ERROR, "checks": [], "inputs": [], "checked_at_utc": now_utc(),
                "error": f"{gate_id}: unknown gate", "attempt_id": attempt_id}
    problem = A.attempt_id_problem(project_root, attempt_id) if record else A.attempt_id_shape_problem(attempt_id)
    if problem:
        return {"gate": gate_id, "result": TOOL_ERROR, "checks": [], "inputs": [], "checked_at_utc": now_utc(),
                "error": problem, "attempt_id": attempt_id}
    try:
        rec = IMPLEMENTED[gate_id](project_root, **kw)
    except ToolError as e:
        rec = {"gate": gate_id, "result": TOOL_ERROR, "checks": [], "inputs": [], "checked_at_utc": now_utc(), "error": str(e)}
    except Exception:  # noqa: BLE001 - a gate crash is a tool error, never PASS
        rec = {"gate": gate_id, "result": TOOL_ERROR, "checks": [], "inputs": [], "checked_at_utc": now_utc(),
               "error": traceback.format_exc()[-2000:]}
    rec["attempt_id"] = attempt_id
    if record:
        # Every outcome is recorded, TOOL_ERROR included: the current record always reflects the latest attempt.
        rec["record_path"] = record_gate(project_root, rec)
        rec["attempt_path"] = A.record_attempt(project_root, rec)
    return rec


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 2:
        print(__doc__)
        return 2
    kw = {x.split("=", 1)[0][2:]: x.split("=", 1)[1] for x in a[2:] if x.startswith("--ledger=")}
    if kw and a[0] != "G5P":
        print("--ledger applies to G5P only")
        return 2
    att = [x.split("=", 1)[1] for x in a[2:] if x.startswith("--attempt=")]
    rec = run_gate(a[0], a[1], record="--no-record" not in a, attempt_id=att[-1] if att else None, **kw)
    print(json.dumps({k: rec[k] for k in rec if k != "comparisons"}, indent=1, default=str))
    return {PASS: 0, FAIL: 1}.get(rec["result"], 2)


if __name__ == "__main__":
    sys.exit(main())
