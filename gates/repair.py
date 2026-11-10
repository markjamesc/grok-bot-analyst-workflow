"""Repair-round cap: three unsuccessful repairs of the same defect, then ESCALATE.

Ledger: artifacts/repairs.json  {"defects": {<defect_id>: {"gate", "status": OPEN|RESOLVED|ESCALATED, "attempts": [...]}}}
Changing author does not reset the count (the count is per defect id, not per author).
"""
from __future__ import annotations

import os

from gates.common import load_json_strict, now_utc, write_json_atomic

CAP = 3
LEDGER = "artifacts/repairs.json"


class RepairCapExceeded(Exception):
    pass


def _load(root):
    path = os.path.join(root, LEDGER)
    if not os.path.exists(path):
        return {"defects": {}}
    obj, err = load_json_strict(path)
    if err or not isinstance(obj, dict) or not isinstance(obj.get("defects"), dict):
        raise ValueError(f"{LEDGER} {err or 'malformed'}")
    return obj


def open_defect(root, defect_id, gate, description):
    led = _load(root)
    if defect_id in led["defects"]:
        raise ValueError(f"defect {defect_id} already recorded")
    led["defects"][defect_id] = {"gate": gate, "description": description, "status": "OPEN", "opened_at_utc": now_utc(), "attempts": []}
    write_json_atomic(led, os.path.join(root, LEDGER))
    return led["defects"][defect_id]


def record_attempt(root, defect_id, author, passed, note=""):
    """Record one repair attempt. After CAP unsuccessful attempts the defect is ESCALATED and no more repairs are accepted."""
    led = _load(root)
    d = led["defects"].get(defect_id)
    if d is None:
        raise ValueError(f"unknown defect {defect_id}")
    if d["status"] == "ESCALATED":
        raise RepairCapExceeded(f"{defect_id}: repair cap {CAP} reached; escalate to the owner")
    if d["status"] == "RESOLVED":
        raise ValueError(f"{defect_id} already resolved")
    d["attempts"].append({"n": len(d["attempts"]) + 1, "author": author, "passed": bool(passed), "note": note, "at_utc": now_utc()})
    failed = sum(1 for a in d["attempts"] if not a["passed"])
    if passed:
        d["status"] = "RESOLVED"
    elif failed >= CAP:
        d["status"] = "ESCALATED"
    write_json_atomic(led, os.path.join(root, LEDGER))
    return d["status"]


def cap_checks(gate, gates_scope=None):
    """Adds repair-cap checks to a Gate. A missing ledger means no repairs were needed."""
    try:
        led = _load(gate.root)
    except ValueError as e:
        gate.add("Repair ledger parses", False, str(e))
        return
    if os.path.exists(os.path.join(gate.root, LEDGER)):
        gate.use(LEDGER)
    rows = [(k, v) for k, v in led["defects"].items() if gates_scope is None or v.get("gate") in gates_scope]
    bad = [k for k, v in rows if not isinstance(v, dict) or v.get("status") not in ("OPEN", "RESOLVED", "ESCALATED")
           or not isinstance(v.get("attempts"), list)]
    gate.add("Repair ledger well-formed", not bad, f"malformed defects: {bad}" if bad else "ok")
    miscounted = [k for k, v in rows if k not in bad and v["status"] != "ESCALATED"
                  and sum(1 for a in v["attempts"] if isinstance(a, dict) and not a.get("passed")) >= CAP]
    gate.add("Repair count consistent with status", not miscounted,
             f"{CAP}+ failed repairs but not ESCALATED: {miscounted}" if miscounted else "ok")
    esc = [k for k, v in rows if k not in bad and v["status"] == "ESCALATED"]
    if esc or miscounted:
        gate.extra["escalate"] = sorted(set(esc + miscounted))
    gate.add("Repair cap not exceeded", not esc and not miscounted,
             f"ESCALATE to owner (3 failed repairs): {sorted(set(esc + miscounted))}" if esc or miscounted else f"cap {CAP}")
    opened = [k for k, v in rows if k not in bad and v["status"] == "OPEN"]
    gate.add("No open defects", not opened, f"open: {opened}" if opened else "none open")
