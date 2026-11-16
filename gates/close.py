"""Stage close check (case02 change A1): python3 -m gates.close <GATE_ID> <project_root> [--no-record]

A stage may be sealed or called closed only after this command exits 0. It does not re-run any gate. It reads the
recorded verdicts and refuses the close unless:
- the closing gate and every gate it depends on (and G0) has a recorded PASS whose inputs are all still current;
- G0 lists no captured reply waiting for promotion (gates/packet.py) and no sent packet without an answer.

A FAIL or TOOL_ERROR record, a missing record, or a record whose inputs changed refuses the close (exit 1). This is the
check that stops a FAIL from being sealed as "closed" (lesson L21). Exit 0 PASS, 1 FAIL, 2 TOOL_ERROR (bad arguments).
Unless --no-record, the verdict is also written once to artifacts/gates/close/<GATE>-<time>-<hash>.json.

Closing gates by stage: Stage 1 G1, Stage 2 G2, Stage 2F G2F, Stage 3 G3, Stage 4 G4d, Stage 5 G5 then G6.
"""
from __future__ import annotations

import json
import os
import sys

from gates.common import FAIL, PASS, gate_record_current, load_json_strict, now_utc, sha256_bytes, write_once
from gates.stage_gates import CHAIN, DEPS

CLOSE_DIR = "artifacts/gates/close"
CLOSING = ("G1", "G2", "G2F", "G3S", "G3K", "G3", "G4a", "G4b", "G4c", "G4d", "G5", "G6")


def required_gates(gate_id):
    """The closing gate, everything it depends on (transitively) and G0, in dependency order."""
    if gate_id == "G6":
        return list(CHAIN) + ["G6"]
    out, todo = [], [gate_id]
    while todo:
        gid = todo.pop()
        if gid in out:
            continue
        out.append(gid)
        todo.extend(DEPS.get(gid, ()))
    order = ["G0", "G1", "G2", "G2F", "G3S", "G3K", "G3", "G4a", "G4b", "G4c", "G4d", "G5", "G6"]
    return [g for g in order if g in out or g == "G0"]


def close_check(root, gate_id):
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "result": PASS if ok else FAIL, "detail": detail})

    for gid in required_gates(gate_id):
        ok, det, _ = gate_record_current(root, gid)
        add(f"{gid} PASS and current", ok, det)
    g0, err = load_json_strict(os.path.join(root, "artifacts/gates/G0.json"))
    g0 = g0 if isinstance(g0, dict) and not err else {}
    cap = g0.get("captured") if isinstance(g0.get("captured"), list) else []
    add("No captured reply waiting for promotion", "result" in g0 and not cap,
        f"captured: {cap} -- run python3 -m gates.packet promote <root> <id>" if cap else "none")
    idx, err = load_json_strict(os.path.join(root, "artifacts/packets/index.json"))
    pk = idx.get("packets") if isinstance(idx, dict) and isinstance(idx.get("packets"), list) else []
    sent = [p.get("id") for p in pk if isinstance(p, dict) and p.get("status") == "sent"
            and not any(k in p for k in ("superseded_by", "superseded_reason", "superseded_at"))]
    add("No sent packet without an answer", not err and not sent, f"sent, not answered: {sent}" if sent else "none")
    ok = bool(checks) and all(c["result"] == PASS for c in checks)
    return {"close": gate_id, "result": PASS if ok else FAIL, "checks": checks, "checked_at_utc": now_utc(),
            "note": "Seal the stage only when this is PASS. A FAIL here means the stage is not closed."}


def record_close(root, rec):
    data = (json.dumps(rec, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    rel = f"{CLOSE_DIR}/{rec['close']}-{rec['checked_at_utc'].replace(':', '')}-{sha256_bytes(data)[:12]}.json"
    full = os.path.join(root, rel)
    if not os.path.exists(full):
        write_once(full, data)
    return rel


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 2 or a[0] not in CLOSING or not os.path.isdir(a[1]):
        print(__doc__)
        return 2
    rec = close_check(a[1], a[0])
    if "--no-record" not in a:
        rec["record_path"] = record_close(a[1], rec)
    print(json.dumps(rec, indent=1))
    return 0 if rec["result"] == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
