"""Gate attempts (known fix 1, owner correction 2026-11-20): python3 -m gates.attempt <GATE_ID> <project_root> <attempt id>

Problem fixed: a failed or crashed retry left an older PASS record current, and the run moved on as if the retry passed.

Every gate run has an attempt id. gates.run writes the outcome of every recorded attempt once to
artifacts/gates/attempts/<attempt id>.json {attempt_id, gate, result PASS|FAIL|TOOL_ERROR, checked_at_utc, record_sha256}
and also makes that attempt the current record artifacts/gates/<GATE>.json (TOOL_ERROR included).

The coordinating role (the parent, or whichever role coordinates the case) requests a gate run with an attempt id it
chooses and advances only when this check exits 0 for that same attempt id:
- the attempt file exists, is for this gate, and its result is PASS;
- the current record for the gate is that attempt (no later attempt replaced it) and still matches the attempt's hash;
- every input the record lists is unchanged ("PASS by hash", gates/common.gate_record_current).
Exit 0 PASS (may advance), 1 FAIL (may not advance), 2 bad arguments.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys

from gates.common import FAIL, GATE_DIR, PASS, gate_record_current, load_json_strict, now_utc, sha256_file, write_once

ATTEMPT_DIR = f"{GATE_DIR}/attempts"
ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,119}$")


def new_attempt_id(gate_id):
    return f"{gate_id}-{now_utc().replace(':', '').replace('-', '')}-{secrets.token_hex(4)}"


def attempt_id_shape_problem(attempt_id):
    if not isinstance(attempt_id, str) or not ATTEMPT_ID_RE.match(attempt_id):
        return f"attempt id {attempt_id!r} must be 3-120 characters of letters, digits, '.', '_' or '-'"
    return None


def attempt_path(root, attempt_id):
    return os.path.join(root, ATTEMPT_DIR, f"{attempt_id}.json")


def attempt_id_problem(root, attempt_id):
    """None when the id is well formed and unused; otherwise why the run is refused."""
    shape = attempt_id_shape_problem(attempt_id)
    if shape:
        return shape
    if os.path.exists(attempt_path(root, attempt_id)):
        return f"attempt id {attempt_id!r} already used; request a new attempt id"
    return None


def record_attempt(root, rec):
    """Write the attempt outcome once. rec is the gate record just written as the current record."""
    cur = os.path.join(root, GATE_DIR, f"{rec['gate']}.json")
    out = {"attempt_id": rec["attempt_id"], "gate": rec["gate"], "result": rec["result"],
           "checked_at_utc": rec.get("checked_at_utc"), "record_sha256": sha256_file(cur) if os.path.isfile(cur) else None}
    if rec.get("error"):
        out["error"] = str(rec["error"])[-500:]
    write_once(attempt_path(root, rec["attempt_id"]), (json.dumps(out, indent=2) + "\n").encode("utf-8"))
    return f"{ATTEMPT_DIR}/{rec['attempt_id']}.json"


def attempt_check(root, gate_id, attempt_id):
    """(ok, detail): the requested attempt passed and is still the current, unchanged record for the gate."""
    shape = attempt_id_shape_problem(attempt_id)
    if shape:
        return False, shape
    at, err = load_json_strict(attempt_path(root, attempt_id))
    if err or not isinstance(at, dict):
        return False, f"attempt {attempt_id} has no recorded outcome ({err or 'not an object'}); it never ran or was not recorded"
    if at.get("gate") != gate_id or at.get("attempt_id") != attempt_id:
        return False, f"attempt {attempt_id} is for gate {at.get('gate')!r}, not {gate_id}"
    if at.get("result") != PASS:
        return False, f"attempt {attempt_id} ended {at.get('result')!r}; only a PASS for the requested attempt advances"
    cur_rel = f"{GATE_DIR}/{gate_id}.json"
    cur, err = load_json_strict(os.path.join(root, cur_rel))
    if err or not isinstance(cur, dict) or cur.get("attempt_id") != attempt_id:
        got = cur.get("attempt_id") if isinstance(cur, dict) else None
        return False, f"current {gate_id} record is attempt {got!r}, not the requested {attempt_id}"
    if sha256_file(os.path.join(root, cur_rel)) != at.get("record_sha256"):
        return False, f"current {gate_id} record changed since attempt {attempt_id} was recorded"
    ok, det, _ = gate_record_current(root, gate_id)
    return ok, f"attempt {attempt_id}: {det}"


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 3 or not os.path.isdir(a[1]):
        print(__doc__)
        return 2
    ok, det = attempt_check(a[1], a[0], a[2])
    print(json.dumps({"gate": a[0], "attempt_id": a[2], "result": PASS if ok else FAIL, "detail": det}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
