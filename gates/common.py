"""Shared pieces for the Grok workflow gates (G1-G4d, G2F, G3S, G3K, GP).

Every gate returns a record {"gate", "result": PASS|FAIL|TOOL_ERROR, "checks": [...], "inputs": [{path, sha256}], ...}.
An unrun gate is not PASS. A gate never PASSes on missing input.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import tempfile

PASS, FAIL, TOOL_ERROR = "PASS", "FAIL", "TOOL_ERROR"
GATE_DIR = "artifacts/gates"
TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?(Z|[+-][0-9]{2}:[0-9]{2})$")
PLACEHOLDER_RE = re.compile(r"^\s*(PENDING|TBD|TODO)\b", re.IGNORECASE)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ToolError(Exception):
    """The gate could not be run (missing executor, unreadable environment). Not an analysis verdict."""


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def text(x):
    return isinstance(x, str) and x.strip() != ""


def safe_rel(root, rel):
    """Project-relative path that stays inside root (no absolute paths, no '..', no symlink escape)."""
    if not text(rel) or os.path.isabs(rel) or "\\" in rel:
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    full = os.path.join(root, rel)
    real_root = os.path.realpath(root)
    if not os.path.realpath(full).startswith(real_root + os.sep):
        return None
    return full


def load_json_strict(path):
    """Parse JSON; reject duplicate keys, NaN/Infinity and a non-UTF-8 file. Returns (obj, error)."""
    def hook(pairs):
        keys = [k for k, _ in pairs]
        dup = sorted({k for k in keys if keys.count(k) > 1})
        if dup:
            raise ValueError(f"duplicate keys {dup}")
        return dict(pairs)

    def bad_const(name):
        raise ValueError(f"non-finite number {name}")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return json.loads(raw.decode("utf-8"), object_pairs_hook=hook, parse_constant=bad_const), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:  # noqa: BLE001 - any parse problem is a FAIL of "parses"
        return None, f"does not parse: {e}"


def ref_current(root, ref, need_nonempty=True):
    """A {path, sha256} reference to a project file whose current bytes match the recorded hash."""
    if not isinstance(ref, dict) or not text(ref.get("path")) or not isinstance(ref.get("sha256"), str):
        return False
    full = safe_rel(root, ref["path"])
    if full is None or not os.path.isfile(full):
        return False
    if need_nonempty and os.path.getsize(full) == 0:
        return False
    return HEX64.match(ref["sha256"].lower()) is not None and sha256_file(full) == ref["sha256"].lower()


def ref_of(root, rel):
    full = safe_rel(root, rel)
    if full is None or not os.path.isfile(full):
        return {"path": rel, "sha256": None}
    return {"path": rel, "sha256": sha256_file(full)}


class Gate:
    """Collects checks for one gate run."""

    def __init__(self, gate_id, root):
        self.gate_id = gate_id
        self.root = root
        self.checks = []
        self.inputs = []
        self.extra = {}

    def add(self, name, ok, detail=""):
        ok = bool(ok)
        self.checks.append({"check": name, "result": PASS if ok else FAIL, "detail": detail})
        return ok

    def extend(self, checks, prefix=""):
        for c in checks:
            res = c.get("result")
            self.checks.append({"check": prefix + str(c.get("check")), "result": PASS if res == "PASS" else FAIL,
                                "detail": c.get("detail")})

    def use(self, rel):
        """Record an input file (path + current hash) that the verdict depends on."""
        r = ref_of(self.root, rel)
        if r not in self.inputs:
            self.inputs.append(r)
        return r

    def load(self, rel, label=None):
        label = label or rel
        full = safe_rel(self.root, rel)
        if full is None:
            self.add(f"{label} parses", False, f"{rel}: unsafe path")
            return None
        obj, err = load_json_strict(full)
        self.use(rel)
        self.add(f"{label} parses", err is None and isinstance(obj, dict), f"{rel}: {err or 'ok'}" if err else rel)
        return obj if err is None and isinstance(obj, dict) else None

    def result(self):
        ok = bool(self.checks) and all(c["result"] == PASS for c in self.checks)
        out = {"gate": self.gate_id, "result": PASS if ok else FAIL, "checks": self.checks, "inputs": self.inputs,
               "checked_at_utc": now_utc(), "implementation": "python"}
        out.update(self.extra)
        return out


def write_json_atomic(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def write_once(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "xb") as fh:
        fh.write(data)


def record_gate(root, rec):
    """Write artifacts/gates/<ID>.json (current verdict) and a write-once history copy."""
    data = (json.dumps(rec, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    hist = os.path.join(root, GATE_DIR, "history", f"{rec['gate']}-{rec['checked_at_utc'].replace(':', '')}-{sha256_bytes(data)[:12]}.json")
    if not os.path.exists(hist):
        write_once(hist, data)
    write_json_atomic(rec, os.path.join(root, GATE_DIR, f"{rec['gate']}.json"))
    return os.path.join(GATE_DIR, f"{rec['gate']}.json")


def gate_record_current(root, gate_id):
    """(ok, detail, ref): the recorded verdict is PASS and every input it was based on still has the recorded hash."""
    rel = f"{GATE_DIR}/{gate_id}.json"
    full = os.path.join(root, rel)
    rec, err = load_json_strict(full)
    if err:
        return False, f"{rel} {err}", None
    if rec.get("gate") != gate_id or rec.get("result") != PASS:
        return False, f"{gate_id} recorded result is {rec.get('result')!r}", None
    inputs = rec.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        return False, f"{gate_id} record lists no inputs", None
    stale = [i.get("path") for i in inputs if not (isinstance(i, dict) and ref_current(root, i, need_nonempty=False))]
    if stale:
        return False, f"{gate_id} inputs changed since the gate ran: {stale}", None
    return True, f"{gate_id} PASS; {len(inputs)} inputs current", {"path": rel, "sha256": sha256_file(full)}


def approval_ok(rec):
    return (isinstance(rec, dict) and text(rec.get("approval_text")) and not PLACEHOLDER_RE.search(rec["approval_text"])
            and isinstance(rec.get("approval_timestamp"), str) and TIMESTAMP_RE.match(rec["approval_timestamp"]) is not None)


def review_checks(gate, review_rel, role, subjects, label):
    """Review coverage: the reviewer received every current subject whole, at the same path, with the current hash;
    no open must-fix finding. `subjects` are project-relative paths."""
    rv = gate.load(review_rel, f"{label} review record")
    if rv is None:
        gate.add(f"{label} review coverage", False, f"{review_rel} missing")
        return
    gate.add(f"{label} reviewer role", rv.get("role") == role, f"role must equal {role}")
    got = rv.get("subjects")
    got = {s.get("path"): (s.get("sha256") or "").lower() for s in got if isinstance(s, dict)} if isinstance(got, list) else {}
    missing = []
    for rel in subjects:
        cur = ref_of(gate.root, rel)
        if cur["sha256"] is None or got.get(rel) != cur["sha256"]:
            missing.append(rel)
    gate.add(f"{label} review coverage", bool(subjects) and not missing,
             "every current subject reviewed whole at the same path with the current hash" + (f"; not covered: {missing}" if missing else ""))
    findings = rv.get("findings")
    ok_shape = isinstance(findings, list) and all(isinstance(f, dict) and f.get("class") in ("must_fix", "advisory")
                                                   and f.get("status") in ("open", "closed") for f in findings)
    gate.add(f"{label} findings well-formed", ok_shape, "findings: list of {class: must_fix|advisory, status: open|closed}")
    open_mf = [f.get("id") for f in (findings if ok_shape else []) if f.get("class") == "must_fix" and f.get("status") == "open"]
    gate.add(f"{label} no open must-fix", ok_shape and not open_mf, f"open must-fix: {open_mf}" if open_mf else "none open")
