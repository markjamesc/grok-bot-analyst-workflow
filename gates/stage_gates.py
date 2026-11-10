"""Grok workflow gates G1, G2, G2F, G3S, G3K, G3, G4a, G4b, G4c, G4d, G5, G6 (docs/gates.md). G0 is in gates/packet.py.

Never weaker than the R referee: G1, G2 and G3 include every check the R procedure gate runs when it completes the
matching stage (validate_stage_receipt + methodology operations ledger + evidence closure, ported in gates/procedure.py
and gates/methodology.py). G4d includes the complete ported R Workflow Gate (gates/workflow_gate.py) and the R
Stage 4 completion checks. G5 includes the R `complete finish` checks (incl. the R claim ledger, m_finish). G6 requires
the R Procedure Gate `finalize` certificate and re-checks that every hash it recorded is still current. Input files are listed in gates/README.md.
"""
from __future__ import annotations

import datetime
import json
import os
import re
from decimal import Decimal, InvalidOperation

from gates import methodology as M
from gates import procedure as P
from gates import reconcile, repair, sql_select_only
from gates import workflow_gate as WG
from gates.common import (FAIL, PASS, Gate, ToolError, approval_ok, gate_record_current, ref_current, ref_of,
                          review_checks, safe_rel, sha256_file, text, write_once)
from gates.rsem import RError

R_STEP = {"G1": ("start", "artifacts/stage1_decision.json"), "G2": ("framing", "artifacts/stage2_framing.json"),
          "G3": ("design", "artifacts/stage3_locked_design.json"), "G4d": ("execution", "artifacts/stage4_validation_status.json"),
          "G5": ("finish", "artifacts/stage5_interpretation_status.json")}
GROK_DESIGN = "artifacts/stage3_grok_design.json"
FEASIBILITY = "artifacts/stage2f_feasibility.json"
OUTPUTS = "artifacts/stage4/outputs.json"
IMPLS = ("ra", "rb", "sql")


def r_stage_checks(g, step_id):
    """The checks the R procedure gate applies at `complete <step>` (except run-state bookkeeping)."""
    rel = R_STEP[g.gate_id][1]
    g.use(rel)
    receipt = P.read_artifact_safe(os.path.join(os.path.realpath(g.root), rel))
    g.add("R: Required receipt exists and parses", M.is_list(receipt), rel)
    try:
        g.extend(P.validate_stage_receipt(step_id, receipt, g.root), "R: ")
        g.extend(M.m_operations(g.root, None, step_id, receipt=rel), "R: ")
        closure = P.step_closure(g.root, step_id, receipt)
        g.add("R: Stage evidence closure", closure is not None, "All receipt and packet references must remain valid before completion")
    except (RError, P.Stop) as e:
        g.add("R: stage checks ran", False, f"the R gate stops on this input: {e}")
    return receipt


def _plain(rel, g):
    full = safe_rel(g.root, rel)
    if full is None:
        return None
    from gates.common import load_json_strict
    obj, err = load_json_strict(full)
    return obj if err is None else None


# ------------------------------------------------------------------------------------------------ G1 decision
def g1(root):
    g = Gate("G1", root)
    r_stage_checks(g, "start")
    d = g.load(R_STEP["G1"][1], "Stage 1 decision document")
    d = d or {}
    g.add("Decision stated", text(d.get("decision_statement")), "decision_statement")
    g.add("Decision owner named", text(d.get("decision_owner")), "decision_owner")
    apr = d.get("actions_per_result")
    g.add("Actions per result", isinstance(apr, list) and len(apr) >= 2 and all(
        isinstance(a, dict) and text(a.get("result")) and text(a.get("action")) for a in apr)
        and len({a["result"] for a in apr}) == len(apr), "actions_per_result: >=2 distinct {result, action}")
    lim = d.get("limits")
    g.add("Limits stated", isinstance(lim, list) and len(lim) > 0 and all(text(x) for x in lim), "limits: non-empty list of text")
    pin = g.load("artifacts/workflow_pin.json", "Workflow pin")
    files = (pin or {}).get("files")
    base = (pin or {}).get("base")
    ok = isinstance(files, list) and len(files) > 0 and text(base) and os.path.isdir(base)
    stale = []
    if ok:
        for f in files:
            p = os.path.join(base, f.get("path", "")) if isinstance(f, dict) and text(f.get("path")) else None
            if p is None or not os.path.isfile(p) or sha256_file(p) != str(f.get("sha256", "")).lower():
                stale.append(f.get("path") if isinstance(f, dict) else f)
    g.add("Workflow pinned by the parent", ok and not stale and text((pin or {}).get("commit")),
          "workflow_pin.json: base, commit, files[{path, sha256}] all current" + (f"; stale: {stale}" if stale else ""))
    return g.result()


# ------------------------------------------------------------------------------------------------ G2 question lock
def g2(root):
    g = Gate("G2", root)
    r_stage_checks(g, "framing")
    f = g.load(R_STEP["G2"][1], "Stage 2 framing") or {}
    q = f.get("analytical_question")
    g.add("One question", text(q) and text(f.get("question_id")) and not isinstance(f.get("questions"), list),
          "exactly one analytical_question (text) with one question_id; no question list")
    for k in ("population", "metric", "threshold"):
        v = f.get(k)
        g.add(f"Question {k}", text(v) or (isinstance(v, (dict, list)) and len(v) > 0) or (isinstance(v, (int, float)) and not isinstance(v, bool)), k)
    w = f.get("window")
    g.add("Question window", (isinstance(w, dict) and text(w.get("start")) and text(w.get("end"))) or
          (text(f.get("window_start")) and text(f.get("window_end"))), "window {start, end} or window_start/window_end")
    g.add("Capacity stance", f.get("capacity_stance") in ("unordered_ok", "hard_attention_budget"), "capacity_stance")
    subj = f.get("review_subjects")
    subj = [s for s in subj if text(s)] if isinstance(subj, list) else []
    g.add("Review subjects declared", bool(subj), "review_subjects: framing files the reviewers must receive")
    review_checks(g, "artifacts/stage2/reviews/second_designer_critique.json", "second_designer", subj, "Second Designer critique")
    review_checks(g, "artifacts/stage2/reviews/risk_reviewer_framing_check.json", "risk_reviewer", subj, "Risk Reviewer framing check")
    return g.result()


# ------------------------------------------------------------------------------------------------ G2F feasibility
F_TOP = {"stage", "questions", "owner_decision", "sources"}
F_Q = {"question_id", "feasibility", "reason", "structure", "quality"}
F_STRUCT = {"table", "column", "type", "nullable", "primary_key", "foreign_key", "grain", "description", "available"}
F_QUAL = {"table", "column", "issue", "null_rate", "duplicate_rate", "coverage", "freshness", "note", "severity"}
F_SOURCE = {"name", "kind", "description"}
F_FORBIDDEN_KEYS = {"value", "values", "sample", "samples", "example", "examples", "rows", "data", "top_values",
                    "distinct_values", "min", "max", "mean", "median", "sum", "avg", "answer", "answers", "answer_key",
                    "expected", "result", "results", "estimate", "new_questions"}


def _walk(x, path="$"):
    if isinstance(x, dict):
        for k, v in x.items():
            yield path, k, v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")


def g2f(root):
    g = Gate("G2F", root)
    fz = g.load(FEASIBILITY, "Feasibility record")
    fr = _plain(R_STEP["G2"][1], g)
    g.use(R_STEP["G2"][1])
    locked = [fr.get("question_id")] if isinstance(fr, dict) and text(fr.get("question_id")) else []
    g.add("Locked question available", bool(locked), "Stage 2 question_id (G2 must have run)")
    ok2, det2, _ = gate_record_current(root, "G2")
    g.add("G2 PASS and current", ok2, det2)
    fz = fz or {}
    g.add("Feasibility top-level keys", set(fz) <= F_TOP and "questions" in fz, f"allowed {sorted(F_TOP)}")
    qs = fz.get("questions")
    qs = qs if isinstance(qs, list) else []
    ids = [q.get("question_id") for q in qs if isinstance(q, dict)]
    g.add("No new or missing questions", len(ids) == len(qs) and len(set(ids)) == len(ids) and set(ids) == set(locked) and bool(qs),
          f"question ids must equal the locked question ids {locked}; got {ids}")
    for i, q in enumerate(qs):
        q = q if isinstance(q, dict) else {}
        lab = f"Question {q.get('question_id', i)}"
        g.add(f"{lab} keys", set(q) <= F_Q, f"allowed {sorted(F_Q)}")
        g.add(f"{lab} feasibility", q.get("feasibility") in ("yes", "partly", "no"), "yes | partly | no")
        g.add(f"{lab} reason", text(q.get("reason")), "reason required")
        for part, allowed in (("structure", F_STRUCT), ("quality", F_QUAL)):
            items = q.get(part, [])
            g.add(f"{lab} {part} entries", isinstance(items, list) and all(
                isinstance(it, dict) and set(it) <= allowed and all(not isinstance(v, (dict, list)) for v in it.values()) for it in items),
                f"list of flat objects with keys in {sorted(allowed)}")
    src = fz.get("sources", [])
    g.add("Sources entries", isinstance(src, list) and all(isinstance(s, dict) and set(s) <= F_SOURCE for s in src), f"keys in {sorted(F_SOURCE)}")
    bad = [f"{p}.{k}" for p, k, _ in _walk({k: v for k, v in fz.items() if k != "owner_decision"}) if str(k).lower() in F_FORBIDDEN_KEYS]
    leaks = [p for p, k, v in _walk(fz) if isinstance(v, str) and ("answer_key" in v.lower() or "answer key" in v.lower())]
    g.add("Structure and quality only (no values, no answer key)", not bad and not leaks,
          f"forbidden keys {bad}; answer-key mentions {leaks}" if bad or leaks else "ok")
    needs_owner = any(isinstance(q, dict) and q.get("feasibility") in ("partly", "no") for q in qs)
    if needs_owner:
        od = fz.get("owner_decision")
        g.add("Owner decision on partly/no", approval_ok(od) and isinstance(od, dict) and od.get("decision") in ("proceed", "stop"),
              "owner_decision {decision: proceed|stop, approval_text, approval_timestamp} required when any answer is partly or no")
        if isinstance(od, dict) and od.get("decision") == "stop":
            g.add("Owner decided to proceed", False, "owner chose stop")
    review_checks(g, "artifacts/stage2f/reviews/risk_reviewer_feasibility.json", "risk_reviewer", [FEASIBILITY], "Risk Reviewer feasibility")
    return g.result()


# ------------------------------------------------------------------------------------------------ G3S SQL source gates
G3S_MANIFEST = "artifacts/stage3/source_gates/manifest.json"
G3S_KINDS = ("extraction_completeness", "keys", "joins", "counts")


def g3s(root, executor=None):
    """Runs the SQL Analyst's source gates. Each gate query returns violating rows; PASS means zero rows.
    executor(sql_text, manifest_database) -> (columns, rows, total) for non-sqlite engines; ToolError if absent."""
    g = Gate("G3S", root)
    m = g.load(G3S_MANIFEST, "Source-gate manifest") or {}
    db = m.get("database")
    db_ok = isinstance(db, dict) and db.get("engine") in ("sqlite", "external") and (
        db.get("engine") == "external" or ref_current(root, db.get("snapshot")))
    g.add("Frozen snapshot pinned", db_ok, "database {engine: sqlite, snapshot: {path, sha256}} current, or engine external with an executor")
    if isinstance(db, dict) and isinstance(db.get("snapshot"), dict) and text(db["snapshot"].get("path")):
        g.use(db["snapshot"]["path"])
    gates = m.get("gates")
    gates = gates if isinstance(gates, list) else []
    ids = [x.get("id") for x in gates if isinstance(x, dict)]
    g.add("Source gates declared", bool(gates) and len(ids) == len(gates) and all(text(i) for i in ids) and len(set(ids)) == len(ids),
          "gates: non-empty list with unique ids")
    kinds = {x.get("check") for x in gates if isinstance(x, dict)}
    g.add("Coverage: completeness, keys, joins, counts", set(G3S_KINDS) <= kinds and kinds <= set(G3S_KINDS),
          f"each of {list(G3S_KINDS)} at least once; got {sorted(k for k in kinds if k)}")
    results = []
    for x in gates:
        x = x if isinstance(x, dict) else {}
        gid = x.get("id")
        sref = x.get("sql")
        cur = ref_current(root, sref)
        if isinstance(sref, dict) and text(sref.get("path")):
            g.use(sref["path"])
        g.add(f"{gid}: SQL file current", cur, "sql {path, sha256} must match")
        if not cur:
            results.append({"id": gid, "status": "NOT_RUN"})
            continue
        with open(safe_rel(root, sref["path"]), encoding="utf-8") as fh:
            sql = fh.read()
        probs = sql_select_only.lint(sql)
        g.add(f"{gid}: SELECT-only", not probs, "; ".join(probs) if probs else "single SELECT/WITH statement")
        if probs or not db_ok:
            results.append({"id": gid, "status": "NOT_RUN", "lint": probs})
            continue
        try:
            if db["engine"] == "sqlite":
                cols, rows, total = sql_select_only.run_sqlite(safe_rel(root, db["snapshot"]["path"]), sql)
            elif executor is not None:
                cols, rows, total = executor(sql, db)
            else:
                raise ToolError("engine external needs an executor")
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001 - a failing query is a FAIL of that gate, recorded
            g.add(f"{gid}: query ran read-only", False, f"{type(e).__name__}: {e}")
            results.append({"id": gid, "status": "ERROR", "error": str(e)})
            continue
        g.add(f"{gid}: query ran read-only", True, "read-only connection, SELECT-only authorizer")
        g.add(f"{gid}: zero violating rows", total == 0, f"{total} violating rows")
        results.append({"id": gid, "check": x.get("check"), "status": "PASS" if total == 0 else "FAIL", "violations": total,
                        "columns": cols, "first_rows": rows[:20], "sql_sha256": sref["sha256"]})
    rec = {"manifest": ref_of(root, G3S_MANIFEST), "results": results}
    data = (json.dumps(rec, indent=2, ensure_ascii=False, default=str) + "\n").encode()
    from gates.common import sha256_bytes, now_utc
    rel = f"artifacts/stage3/source_gates/results/run-{now_utc().replace(':', '')}-{sha256_bytes(data)[:12]}.json"
    if not os.path.exists(os.path.join(root, rel)):
        write_once(os.path.join(root, rel), data)
    g.extra["results_record"] = ref_of(root, rel)
    return g.result()


# ------------------------------------------------------------------------------------------------ G3K early key/count checks
def g3k(root):
    g = Gate("G3K", root)
    d = g.load(GROK_DESIGN, "Grok design") or {}
    ec = d.get("early_checks")
    ec = ec if isinstance(ec, dict) else {}
    keys, counts = ec.get("keys"), ec.get("counts")
    g.add("Early checks declared", isinstance(keys, list) and keys and isinstance(counts, list) and counts,
          "early_checks.keys and early_checks.counts must be non-empty")
    for k in keys if isinstance(keys, list) else []:
        k = k if isinstance(k, dict) else {}
        t, cols = k.get("table"), k.get("columns")
        lab = f"Key {k.get('id')}"
        if isinstance(t, dict) and text(t.get("path")):
            g.use(t["path"])
        if not (ref_current(root, t) and isinstance(cols, list) and cols and all(text(c) for c in cols)):
            g.add(f"{lab} unique", False, "table {path, sha256} current and columns non-empty required")
            continue
        try:
            df = M.m_csv(t, root)
        except (RError, OSError, UnicodeDecodeError) as e:
            g.add(f"{lab} unique", False, f"unreadable: {e}")
            continue
        missing = [c for c in cols if c not in df.cols]
        if missing:
            g.add(f"{lab} unique", False, f"columns missing: {missing}")
            continue
        vals = list(zip(*[reconcile._col(df, c) for c in cols])) if df.nrow else []
        blank = sum(1 for row in vals if any(v is None or str(v).strip() == "" for v in row))
        dup = len(vals) - len(set(vals))
        g.add(f"{lab} unique", blank == 0 and dup == 0, f"{df.nrow} rows; {dup} duplicate keys; {blank} blank keys")
    for c in counts if isinstance(counts, list) else []:
        c = c if isinstance(c, dict) else {}
        t, exp = c.get("table"), c.get("expected_rows")
        lab = f"Count {c.get('id')}"
        if isinstance(t, dict) and text(t.get("path")):
            g.use(t["path"])
        if not (ref_current(root, t) and isinstance(exp, int) and not isinstance(exp, bool) and exp >= 0):
            g.add(f"{lab} reconciles", False, "table current and integer expected_rows required")
            continue
        try:
            n = M.m_csv(t, root).nrow
        except (RError, OSError, UnicodeDecodeError) as e:
            g.add(f"{lab} reconciles", False, f"unreadable: {e}")
            continue
        g.add(f"{lab} reconciles", n == exp, f"{n} rows; expected {exp}")
    repair.cap_checks(g, gates_scope={"G3K", "G3S"})
    return g.result()


# ------------------------------------------------------------------------------------------------ G3 design lock
def g3(root):
    g = Gate("G3", root)
    s3 = r_stage_checks(g, "design")
    d = g.load(GROK_DESIGN, "Grok design") or {}
    g.add("ML mode explicit", M.is_list(s3) and M.dollar(s3, "ml_mode") in ("None", "A", "B"), "ml_mode None | A | B")
    fx = d.get("fixtures")
    ok = isinstance(fx, list) and len(fx) > 0
    fids = []
    for f in fx if ok else []:
        f = f if isinstance(f, dict) else {}
        fids.append(f.get("id"))
        for part in ("input", "worked_answer"):
            r = f.get(part)
            if isinstance(r, dict) and text(r.get("path")):
                g.use(r["path"])
            ok = ok and ref_current(root, r)
        ok = ok and isinstance(f.get("keys"), list) and len(f["keys"]) > 0
    g.add("Fixtures with worked answers", ok and len(set(fids)) == len(fids) and all(text(i) for i in fids),
          "fixtures: [{id, input {path, sha256}, worked_answer {path, sha256}, keys}] all current")
    rc = d.get("reconciliation")
    outs = rc.get("outputs") if isinstance(rc, dict) else None
    g.add("Reconciliation outputs declared", isinstance(outs, list) and len(outs) > 0 and all(
        isinstance(o, dict) and text(o.get("name")) and isinstance(o.get("keys"), list) and o["keys"] for o in outs),
        "reconciliation.outputs: [{name, keys, tolerance?}]")
    subj = [s for s in d.get("review_subjects", []) if text(s)] if isinstance(d.get("review_subjects"), list) else []
    g.add("Review subjects declared", bool(subj) and GROK_DESIGN in subj and R_STEP["G3"][1] in subj,
          "review_subjects must include the locked design files")
    review_checks(g, "artifacts/stage3/reviews/second_designer_compare.json", "second_designer", subj, "Second Designer compare")
    review_checks(g, "artifacts/stage3/reviews/risk_reviewer_red_team.json", "risk_reviewer", subj, "Risk Reviewer red-team")
    review_checks(g, "artifacts/stage3/reviews/risk_reviewer_source_gates.json", "risk_reviewer",
                  [G3S_MANIFEST] + _g3s_sql_paths(root), "Risk Reviewer source-gate")
    for gid in ("G3S", "G3K"):
        okg, det, _ = gate_record_current(root, gid)
        g.add(f"{gid} PASS and current", okg, det)
    ap = g.load("artifacts/stage3_owner_approval.json", "Owner design approval") or {}
    cur_design = ref_of(root, R_STEP["G3"][1])["sha256"]
    cur_grok = ref_of(root, GROK_DESIGN)["sha256"]
    g.add("Owner approved the exact design hash", approval_ok(ap) and cur_design is not None and cur_grok is not None
          and str(ap.get("design_sha256", "")).lower() == cur_design and str(ap.get("grok_design_sha256", "")).lower() == cur_grok,
          "stage3_owner_approval.json design_sha256 and grok_design_sha256 must equal the current files")
    return g.result()


def _g3s_sql_paths(root):
    from gates.common import load_json_strict
    full = safe_rel(root, G3S_MANIFEST)
    m, err = load_json_strict(full) if full else (None, "x")
    if err or not isinstance(m, dict) or not isinstance(m.get("gates"), list):
        return []
    return [x["sql"]["path"] for x in m["gates"] if isinstance(x, dict) and isinstance(x.get("sql"), dict) and text(x["sql"].get("path"))]


# ------------------------------------------------------------------------------------------------ G4 helpers
def _design_and_outputs(g):
    d = g.load(GROK_DESIGN, "Grok design") or {}
    o = g.load(OUTPUTS, "Stage 4 outputs record") or {}
    ok3, det3, _ = gate_record_current(g.root, "G3")
    g.add("G3 PASS and current (design locked)", ok3, det3)
    return d, o


def _impl_ref(g, o, section, impl, name):
    r = (((o.get(section) or {}).get(impl) or {}).get(name)) if isinstance(o.get(section), dict) else None
    if isinstance(r, dict) and text(r.get("path")):
        g.use(r["path"])
    return r


# ------------------------------------------------------------------------------------------------ G4a fixtures
def g4a(root):
    g = Gate("G4a", root)
    d, o = _design_and_outputs(g)
    fx = d.get("fixtures") if isinstance(d.get("fixtures"), list) else []
    g.add("Fixtures declared", bool(fx), "design fixtures")
    declared = {f.get("id") for f in fx if isinstance(f, dict)}
    for impl in IMPLS:
        got = set(((o.get("fixtures") or {}).get(impl) or {}).keys()) if isinstance(o.get("fixtures"), dict) else set()
        g.add(f"{impl}: fixture outputs match the declared set", got == declared, f"missing {sorted(declared - got)}; extra {sorted(got - declared)}")
    reports = []
    for f in fx:
        f = f if isinstance(f, dict) else {}
        wa = f.get("worked_answer")
        for impl in IMPLS:
            r = _impl_ref(g, o, "fixtures", impl, f.get("id"))
            lab = f"Fixture {f.get('id')} {impl}"
            if not (ref_current(root, r) and ref_current(root, wa)):
                g.add(f"{lab} matches worked answer", False, "output and worked answer must be current {path, sha256}")
                continue
            ok, det = reconcile.compare(root, r, wa, f.get("keys") or [], f.get("tolerance"))
            reports.append({"fixture": f.get("id"), "impl": impl, "match": ok, **det})
            g.add(f"{lab} matches worked answer", ok, f"mismatches={det.get('mismatch_count')}; {det.get('error', '')}".strip("; "))
    g.extra["comparisons"] = reports
    return g.result()


# ------------------------------------------------------------------------------------------------ G4b reconciliation
def g4b(root):
    g = Gate("G4b", root)
    d, o = _design_and_outputs(g)
    oka, deta, _ = gate_record_current(root, "G4a")
    g.add("G4a PASS and current", oka, deta)
    outs = (d.get("reconciliation") or {}).get("outputs") if isinstance(d.get("reconciliation"), dict) else None
    outs = outs if isinstance(outs, list) else []
    g.add("Reconciliation outputs declared", bool(outs), "design reconciliation.outputs")
    declared = {x.get("name") for x in outs if isinstance(x, dict)}
    for impl in IMPLS:
        got = set(((o.get("outputs") or {}).get(impl) or {}).keys()) if isinstance(o.get("outputs"), dict) else set()
        g.add(f"{impl}: outputs match the declared set", got == declared, f"missing {sorted(declared - got)}; extra {sorted(got - declared)}")
    total, reports = 0, []
    for x in outs:
        x = x if isinstance(x, dict) else {}
        refs = {impl: _impl_ref(g, o, "outputs", impl, x.get("name")) for impl in IMPLS}
        for a, b in (("ra", "rb"), ("ra", "sql"), ("rb", "sql")):
            lab = f"{x.get('name')}: {a} vs {b}"
            if not (ref_current(root, refs[a]) and ref_current(root, refs[b])):
                g.add(f"{lab} exact match", False, "both outputs must be current {path, sha256} (frozen)")
                total += 1
                continue
            ok, det = reconcile.compare(root, refs[a], refs[b], x.get("keys") or [], x.get("tolerance"))
            n = det.get("mismatch_count", 1 if not ok else 0) or (0 if ok else 1)
            total += n
            reports.append({"output": x.get("name"), "pair": [a, b], "match": ok, **det})
            tol = " (design tolerance on " + ", ".join(det.get("tolerance_fields") or []) + ")" if det.get("tolerance_fields") else " (full-field exact)"
            g.add(f"{lab} exact match", ok, f"mismatches={det.get('mismatch_count')}{tol} {det.get('error', '')}".strip())
    g.add("Mismatch count 0", total == 0, f"{total} mismatches")
    g.extra["mismatch_count"] = total
    g.extra["comparisons"] = reports
    repair.cap_checks(g, gates_scope={"G4a", "G4b"})
    return g.result()


# ------------------------------------------------------------------------------------------------ G4c post-reconciliation review
def g4c(root):
    g = Gate("G4c", root)
    okb, detb, refb = gate_record_current(root, "G4b")
    g.add("G4b PASS and current", okb, detb)
    o = _plain(OUTPUTS, g) or {}
    files = ["artifacts/gates/G4b.json"]
    for impl in IMPLS:
        for r in ((o.get("outputs") or {}).get(impl) or {}).values() if isinstance(o.get("outputs"), dict) else []:
            if isinstance(r, dict) and text(r.get("path")):
                files.append(r["path"])
    review_checks(g, "artifacts/stage4/reviews/risk_reviewer_g4c.json", "risk_reviewer", files, "Risk Reviewer post-reconciliation")
    return g.result()


# ------------------------------------------------------------------------------------------------ G4d release
LOWER = ("G1", "G2", "G2F", "G3S", "G3K", "G3", "G4a", "G4b", "G4c")
RUN_STATE = "artifacts/procedure/run_state.json"
WG_REPORT = "artifacts/workflow_gate_status.json"


def g4d(root):
    g = Gate("G4d", root)
    for gid in LOWER:
        ok, det, ref = gate_record_current(root, gid)
        g.add(f"{gid} PASS and current", ok, det)
        if ref:
            g.inputs.append(ref)
    repair.cap_checks(g)
    r_stage_checks(g, "execution")
    # If the R Procedure Gate already recorded its Workflow Gate report (R `complete execution`), never overwrite it:
    # recompute every check without writing and require the recorded report to be unchanged.
    st = _plain(RUN_STATE, g)
    wgr = st.get("workflow_gate") if isinstance(st, dict) else None
    r_recorded = isinstance(wgr, dict) and text(wgr.get("report_sha256"))
    status, report, checks = WG.run(root, write=not r_recorded)
    cur = g.use(WG_REPORT)
    if r_recorded:
        g.add("R-recorded Workflow Gate report unchanged", cur["sha256"] == str(wgr.get("report_sha256")).lower(),
              "artifacts/workflow_gate_status.json must still have the hash the R Procedure Gate recorded")
    if report is None:
        g.add("R Workflow Gate (python port) ran", False, "the R workflow gate halts on this input")
    else:
        g.extend(checks or [], "Workflow Gate: ")
        g.add("Workflow Gate PASS", report.get("result") == "PASS" and status == 0, f"result={report.get('result')}")
    return g.result()




# ------------------------------------------------------------------------------------------------ G5 claims
CLAIMS = "artifacts/stage5_claims.json"
CLAIM_TYPES = ("descriptive", "associational", "predictive", "causal", "recommendation")
NUM_RE = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?(?![\w])")
SEALED_GATES = LOWER + ("G4d",)


def _num(tok):
    t = tok.replace(",", "").rstrip("%").lstrip("+")
    try:
        return str(Decimal(t).normalize()) if t not in ("", "-") else None
    except InvalidOperation:
        return None


def numbers_in(s):
    return {n for n in (_num(m.group(0)) for m in NUM_RE.finditer(s)) if n is not None}


def _read_text(root, rel):
    full = safe_rel(root, rel)
    try:
        with open(full, "rb") as fh:
            return fh.read().decode("utf-8")
    except (OSError, TypeError, UnicodeDecodeError):
        return None


def sealed_evidence(root):
    """{path: sha256} of every input of a current PASS gate record G1..G4d, plus those gate records themselves."""
    out = {}
    for gid in SEALED_GATES:
        ok, _, ref = gate_record_current(root, gid)
        if not ok:
            continue
        out[ref["path"]] = ref["sha256"]
        from gates.common import load_json_strict
        rec, _ = load_json_strict(os.path.join(root, ref["path"]))
        for i in (rec if isinstance(rec, dict) else {}).get("inputs", []):
            if isinstance(i, dict) and text(i.get("path")) and isinstance(i.get("sha256"), str):
                out[i["path"]] = i["sha256"].lower()
    return out


def g5(root):
    g = Gate("G5", root)
    r5 = r_stage_checks(g, "finish")
    ok4, det4, _ = gate_record_current(root, "G4d")
    g.add("G4d PASS and current (release)", ok4, det4)
    c = g.load(CLAIMS, "Claims ledger") or {}
    dl = c.get("deliverables")
    dl = dl if isinstance(dl, list) else []
    dpaths = [d.get("path") for d in dl if isinstance(d, dict)]
    g.add("Deliverables declared and current", bool(dl) and all(ref_current(root, d) for d in dl) and len(set(dpaths)) == len(dpaths),
          "deliverables: [{path, sha256}] current, no duplicates")
    for pth in dpaths:
        if text(pth):
            g.use(pth)
    r_dl = M.dollar(r5, "deliverables") if M.is_list(r5) else None
    r_dl = [x for x in (r_dl if isinstance(r_dl, list) else [r_dl] if isinstance(r_dl, str) else []) if isinstance(x, str)]
    g.add("Deliverables equal the R finish receipt", bool(r_dl) and set(r_dl) == set(dpaths),
          f"R receipt {sorted(r_dl)}; claims ledger {sorted(p for p in dpaths if text(p))}")
    s3 = _plain(R_STEP["G3"][1], g) or {}
    allowed = ((s3.get("methodology") or {}).get("analytical_target") or {}).get("allowed_claim_types") if isinstance(s3.get("methodology"), dict) else None
    allowed = [a for a in allowed if a in CLAIM_TYPES] if isinstance(allowed, list) and allowed else list(CLAIM_TYPES)
    claims = c.get("claims")
    claims = claims if isinstance(claims, list) else []
    ids = [x.get("id") for x in claims if isinstance(x, dict)]
    g.add("Claims listed", bool(claims) and len(ids) == len(claims) and all(text(i) for i in ids) and len(set(ids)) == len(ids),
          "claims: non-empty list with unique ids (every material claim in the deliverables)")
    sealed = sealed_evidence(root)
    texts = {pth: _read_text(root, pth) for pth in dpaths if text(pth)}
    covered = set()
    for x in claims:
        x = x if isinstance(x, dict) else {}
        lab = f"Claim {x.get('id')}"
        g.add(f"{lab} type within the claim ceiling", x.get("type") in allowed, f"type in {allowed} (locked design)")
        q, dv = x.get("quote"), x.get("deliverable")
        in_dl = text(q) and dv in texts and texts[dv] is not None and q in texts[dv]
        g.add(f"{lab} quoted verbatim from a deliverable", in_dl, "quote must appear verbatim in the named deliverable")
        if in_dl:
            covered.add(dv)
        ev = x.get("evidence")
        ev = ev if isinstance(ev, list) else []
        not_sealed = [e.get("path") if isinstance(e, dict) else e for e in ev
                      if not (isinstance(e, dict) and ref_current(root, e) and sealed.get(e.get("path")) == str(e.get("sha256")).lower())]
        g.add(f"{lab} tied to sealed evidence", bool(ev) and not not_sealed,
              "evidence: [{path, sha256}] each an input of a current PASS gate record G1-G4d (or that record)"
              + (f"; not sealed or not current: {not_sealed}" if not_sealed else ""))
        for e in ev:
            if isinstance(e, dict) and text(e.get("path")):
                g.use(e["path"])
        ev_nums = set()
        for e in ev:
            t = _read_text(root, e.get("path")) if isinstance(e, dict) and text(e.get("path")) else None
            ev_nums |= numbers_in(t) if t else set()
        der = x.get("derived", [])
        der = der if isinstance(der, list) else []
        der_ok = all(isinstance(d, dict) and _num(str(d.get("value", ""))) is not None and text(d.get("basis")) for d in der)
        der_vals = {_num(str(d.get("value"))) for d in der if isinstance(d, dict)} if der_ok else set()
        loose = sorted(numbers_in(q) - ev_nums - der_vals) if text(q) else []
        g.add(f"{lab} every number traced", der_ok and not loose,
              "each number in the quote appears in its evidence or is listed under derived [{value, basis}]"
              + (f"; untraced: {loose}" if loose else "") + ("" if der_ok else "; derived entries malformed"))
    uncovered = [pth for pth in dpaths if text(pth) and pth not in covered]
    g.add("Every deliverable carries a recorded claim", bool(dpaths) and not uncovered, f"no claim quoted from: {uncovered}" if uncovered else "ok")
    subj = [CLAIMS] + [pth for pth in dpaths if text(pth)]
    review_checks(g, "artifacts/stage5/reviews/second_designer_inference.json", "second_designer", subj, "Second Designer inference")
    review_checks(g, "artifacts/stage5/reviews/risk_reviewer_numbers.json", "risk_reviewer", subj, "Risk Reviewer numbers")
    repair.cap_checks(g)
    return g.result()


# ------------------------------------------------------------------------------------------------ G6 certificate
CHAIN = ("G0",) + LOWER + ("G4d", "G5")
DEPS = {"G2": ("G1",), "G2F": ("G2",), "G3S": ("G2F",), "G3K": ("G2F",), "G3": ("G3S", "G3K"), "G4a": ("G3",), "G4b": ("G4a",),
        "G4c": ("G4b",), "G4d": ("G4c",), "G5": ("G4d",)}
R_CERT = "artifacts/final_certificate.json"
FINISH_APPROVAL = "artifacts/stage5_owner_approval.json"
R_STEPS = ("start", "framing", "design", "execution", "finish")


def _t(rec):
    try:
        return datetime.datetime.strptime(rec.get("checked_at_utc", ""), "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, AttributeError):
        return None


def g6(root):
    g = Gate("G6", root)
    recs, refs = {}, {}
    for gid in CHAIN:
        ok, det, ref = gate_record_current(root, gid)
        g.add(f"{gid} PASS and current", ok, det)
        if ref:
            g.inputs.append(ref)
            refs[gid] = ref
            recs[gid] = _plain(ref["path"], g) or {}
    g0 = recs.get("G0", {})
    un = g0.get("unanswered") if isinstance(g0.get("unanswered"), list) else None
    g.add("Every packet answered", "G0" in recs and un == [], f"unanswered packets: {un}" if un else "G0 lists none unanswered")
    late = []
    for gid, deps in DEPS.items():
        for d in deps:
            a, b = _t(recs.get(gid, {})), _t(recs.get(d, {}))
            if gid in recs and d in recs and (a is None or b is None or a < b):
                late.append(f"{gid} before {d}")
    g.add("All stages in order", len(recs) == len(CHAIN) and not late,
          "each gate ran after the gates it depends on" + (f"; out of order: {late}" if late else ""))
    repair.cap_checks(g)
    # owner approval of the exact finish package
    c = _plain(CLAIMS, g)
    g.use(CLAIMS)
    ap = g.load(FINISH_APPROVAL, "Owner finish approval") or {}
    cdl = {d.get("path"): str(d.get("sha256")).lower() for d in (c or {}).get("deliverables", []) if isinstance(d, dict)}
    adl = {d.get("path"): str(d.get("sha256")).lower() for d in ap.get("deliverables", []) if isinstance(d, dict)} \
        if isinstance(ap.get("deliverables"), list) else {}
    cur_claims = ref_of(root, CLAIMS)["sha256"]
    g.add("Owner approved the exact finish package", approval_ok(ap) and cur_claims is not None
          and str(ap.get("claims_sha256", "")).lower() == cur_claims and bool(adl) and adl == cdl
          and all(ref_current(root, {"path": k, "sha256": v}) for k, v in adl.items()),
          "stage5_owner_approval.json claims_sha256 and deliverables must equal the current claims ledger and files")
    # R Procedure Gate certificate, and every hash it recorded still current
    cert = g.load(R_CERT, "R final certificate") or {}
    g.add("R certificate PASS", cert.get("result") == PASS and cert.get("certified") is True
          and cert.get("certificate") == "five_stage_procedure_certificate", "R `finalize` must have certified the run")
    cs = cert.get("completed_steps") if isinstance(cert.get("completed_steps"), list) else []
    got = [s.get("id") for s in cs if isinstance(s, dict)]
    stale = [s.get("id") for s in cs if not (isinstance(s, dict) and ref_current(root, {"path": s.get("artifact_path"), "sha256": s.get("artifact_sha256")}))]
    g.add("R certificate stages complete and unchanged", got == list(R_STEPS) and not stale,
          f"completed_steps {got}; changed since certification: {stale}")
    for s in cs:
        if isinstance(s, dict) and text(s.get("artifact_path")):
            g.use(s["artifact_path"])
    dls = cert.get("deliverables") if isinstance(cert.get("deliverables"), list) else []
    rdl = {d.get("path"): str(d.get("sha256")).lower() for d in dls if isinstance(d, dict)}
    g.add("R certificate deliverables unchanged", bool(rdl) and all(ref_current(root, {"path": k, "sha256": v}) for k, v in rdl.items())
          and rdl == cdl, "certified deliverables still current and equal to the approved finish package")
    inv = cert.get("evidence_inventory")
    g.add("R evidence inventory unchanged", ref_current(root, inv), "evidence_inventory {path, sha256} current")
    if isinstance(inv, dict) and text(inv.get("path")):
        g.use(inv["path"])
    g.add("R Workflow Gate report unchanged", ref_of(root, WG_REPORT)["sha256"] == str(cert.get("workflow_gate_report_sha256", "")).lower(),
          "workflow_gate_status.json still has the hash the certificate recorded")
    st = _plain(RUN_STATE, g) or {}
    fc = st.get("final_certificate") if isinstance(st.get("final_certificate"), dict) else {}
    g.add("R run state certified this certificate", st.get("status") == "CERTIFIED" and fc.get("path") == R_CERT
          and fc.get("sha256") == ref_of(root, R_CERT)["sha256"], "run_state status CERTIFIED and final_certificate hash current")
    g.extra["certificate"] = {"certificate": "grok_five_stage_gate_certificate", "gates": refs, "r_certificate": ref_of(root, R_CERT),
                              "claims": ref_of(root, CLAIMS), "owner_finish_approval": ref_of(root, FINISH_APPROVAL),
                              "note": "Recorded gate checks and approvals; not a proof of correctness or AI independence."}
    return g.result()


GATES = {"G1": g1, "G2": g2, "G2F": g2f, "G3S": g3s, "G3K": g3k, "G3": g3, "G4a": g4a, "G4b": g4b, "G4c": g4c, "G4d": g4d,
         "G5": g5, "G6": g6}
