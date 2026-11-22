"""Grok workflow gates G1, G2, G2F, G3S, G3K, G3, G4a, G4b, G4c, G4d, G5, G6 (docs/gates.md). G0 is in gates/packet.py.

Never weaker than the R referee: G1, G2 and G3 include every check the R procedure gate runs when it completes the
matching stage (validate_stage_receipt + methodology operations ledger + evidence closure, ported in gates/procedure.py
and gates/methodology.py). G4d includes the complete ported R Workflow Gate (gates/workflow_gate.py) and the R
Stage 4 completion checks. G5 includes the R `complete finish` checks (incl. the R claim ledger, m_finish). G6 requires
the R Procedure Gate `finalize` certificate and re-checks that every hash it recorded is still current. Input files are listed in gates/README.md.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import os
import re
from decimal import Decimal, InvalidOperation

from gates import methodology as M
from gates import procedure as P
from gates import guards, reconcile, repair, sql_select_only
from gates import stakeholder as SH
from gates import workflow_gate as WG
from gates.common import (FAIL, GATE_DIR, PASS, PLACEHOLDER_RE, Gate, ToolError, approval_ok, gate_record_current, ref_current, ref_of,
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
    return _plain_at(g.root, rel)


def _plain_at(root, rel):
    full = safe_rel(root, rel)
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
    stage1_conversation_checks(g, d)
    return g.result()


def stage1_conversation_checks(g, d):
    """Stage 1 runs as a captured group chat with the Stakeholder (gates/stakeholder.py; docs/rules.md 31-36)."""
    g.add("Agreed question written up", text(d.get("agreed_question")), "agreed_question: the question the chat settled, in plain words")
    conv = SH.conversation_checks(g, "1")
    ts = SH.source_checks(g, "Decision document", d.get("sources"), [conv] if conv else [], conv.brief_text if conv else "")
    SH.lock_checks(g, "1", conv, ts)


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
    stage2_conversation_checks(g, f)
    return g.result()


def stage2_conversation_checks(g, f):
    """Stage 2 also runs as a captured group chat (owner scope 2026-11-16): the framing cites the brief and the Stage 1
    or Stage 2 captures, its threshold traces to the brief or an owner-authorised change, and the owner locks it."""
    c1 = SH.conversation_checks(g, "1")
    c2 = SH.conversation_checks(g, "2")
    convs = [c for c in (c1, c2) if c]
    brief = c1.brief_text if c1 else (c2.brief_text if c2 else "")
    if c1 and c2:
        g.add("Stage 2 chat: same brief as Stage 1", c1.rec.get("brief") == c2.rec.get("brief"), "brief {path, sha256} equal in both records")
    ts = SH.source_checks(g, "Framing", f.get("sources"), convs, brief)
    allowed = SH.numbers(brief)
    for c in convs:
        for s in c.statements.values():
            if s.get("kind") in ("rule_change", "twist") and SH._in(s.get("quote"), c.bodies.get(s.get("capture"))) \
                    and SH._authorized(c, s):
                allowed |= SH.numbers(s.get("quote"))
    th = f.get("threshold")
    th_nums = SH.numbers(json.dumps(th) if not isinstance(th, str) else th)
    extra = sorted(th_nums - allowed)
    g.add("Framing threshold traced to the brief or an owner capture", bool(th_nums) and not extra,
          "every threshold number is in the brief or in an owner-authorised rule_change/twist statement"
          + (f"; untraced: {extra}" if extra else ""))
    SH.lock_checks(g, "2", c2, ts)


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
    snap = snapshot_identity(db.get("snapshot") if isinstance(db, dict) else None)
    g.add("Frozen snapshot identified", snap is not None,
          "database.snapshot needs an id and the sha256 of the exact frozen snapshot queried (known fix 2); the G3S result "
          "is bound to that snapshot and does not carry over to another one")
    g.extra["snapshot"] = snap
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


def snapshot_identity(snap):
    """{id, sha256, path?} of a frozen snapshot reference, or None when the id or hash is missing."""
    if not isinstance(snap, dict) or not text(snap.get("id")) or not isinstance(snap.get("sha256"), str) \
            or not re.fullmatch(r"[0-9a-f]{64}", snap["sha256"].lower()):
        return None
    out = {"id": snap["id"], "sha256": snap["sha256"].lower()}
    if text(snap.get("path")):
        out["path"] = snap["path"]
    return out


def snapshot_binding_checks(g, root, o):
    """Known fix 2 (owner correction 2026-11-20): the Stage 4 outputs name the frozen snapshot they ran on
    (`snapshot` {id, sha256, path?} in artifacts/stage4/outputs.json) and it must be the exact snapshot the current G3S
    PASS checked. Switching from snapshot A to snapshot B needs a fresh G3S run on B; an old PASS on A never covers B."""
    ok3s, det3s, ref3s = gate_record_current(root, "G3S")
    if ref3s:
        g.inputs.append(ref3s)
    rec = _plain_at(root, f"{GATE_DIR}/G3S.json") if ok3s else None
    checked = snapshot_identity((rec or {}).get("snapshot"))
    ran = snapshot_identity(o.get("snapshot") if isinstance(o, dict) else None)
    file_ok = ran is not None and ("path" not in ran or ref_current(root, ran))
    if ran and "path" in ran:
        g.use(ran["path"])
    same = checked is not None and ran is not None and checked["id"] == ran["id"] and checked["sha256"] == ran["sha256"]
    g.add("Stage 4 snapshot is the one G3S checked", ok3s and same and file_ok,
          ("G3S: " + det3s + "; " if not ok3s else "")
          + f"G3S checked {checked and (checked['id'], checked['sha256'][:12])}; Stage 4 ran on "
          f"{ran and (ran['id'], ran['sha256'][:12])}" + ("" if file_ok else " (snapshot {id, sha256, path?} missing or not current)")
          + ("" if same else " -- run G3S on this snapshot before Stage 4"))


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
    design_lock_guards(g, [GROK_DESIGN, R_STEP["G3"][1]] + subj)
    lock_completeness_checks(g, d, outs)
    next_stage_entry_checks(g, root, d)
    decision_flip_checks(g, d)
    rounding_tolerance_checks(g, d)
    design_version_checks(g, _plain(R_STEP["G3"][1], g))
    stale_nested_ref_checks(g, root, "design")
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


# Fields the nested R Workflow Gate (gates/workflow_gate.py, run inside G4d) reads from the locked Stage 3 design.
# Lesson L14 (2026-11-15): G3 passed a design without them and the run could only fail at G4d. Check them at lock time.
WG_STAGE3_REQUIRED = ("stage", "status", "design_version", "population", "grain", "window_start", "window_end", "decision_rules",
                      "required_outputs")
WG_STAGE3_SCALARS = ("fixture_version",)
WG_STAGE3_LISTS = ("fixture_ids", "reconciliation_critical_fields")


def workflow_gate_field_gaps(s3, s2):
    """Names of Stage 3 fields the Workflow Gate needs at G4d that the locked design lacks (plain dicts in, list out)."""
    s3 = s3 if isinstance(s3, dict) else {}
    s2 = s2 if isinstance(s2, dict) else {}
    gaps = [k for k in WG_STAGE3_REQUIRED if k not in s3]
    if s3.get("ml_mode") not in ("None", "A", "B"):
        gaps.append("ml_mode")
    gaps += [k for k in WG_STAGE3_SCALARS if not text(s3.get(k))]
    gaps += [k for k in WG_STAGE3_LISTS if not (isinstance(s3.get(k), list) and s3[k] and all(text(v) for v in s3[k]))]
    if s2.get("capacity_stance") == "hard_attention_budget":
        rc = s3.get("ranking_contract")
        n = rc.get("n") if isinstance(rc, dict) else None
        n_ok = isinstance(n, (int, float)) and not isinstance(n, bool) and n >= 1 and float(n) == int(n)
        if not (isinstance(rc, dict) and all(text(rc.get(k)) for k in ("key", "tie_break", "capacity_unit"))
                and rc.get("membership_first") is True and rc.get("padding_allowed") is False
                and (rc.get("owner_n_deferred") is True or n_ok)):
            gaps.append("ranking_contract")
    return gaps


def lock_completeness_checks(g, d, outs):
    """Case02 changes 1, 7, 8: Workflow Gate fields present at lock; decision thresholds declared for the Stage 5 report;
    any owner hold declared with its source and a decision output that records both the rule's action and the hold."""
    gaps = workflow_gate_field_gaps(_plain(R_STEP["G3"][1], g), _plain(R_STEP["G2"][1], g))
    g.add("Workflow Gate fields present at lock", not gaps,
          "the locked design must carry every Stage 3 field the R Workflow Gate reads at G4d" + (f"; missing: {gaps}" if gaps else ""))
    th = d.get("decision_thresholds")
    th_ok = isinstance(th, list) and len(th) > 0 and all(
        isinstance(t, dict) and text(t.get("id")) and threshold_value(t) is not None and text(t.get("statement")) for t in th)
    th_ok = th_ok and len({t["id"] for t in th}) == len(th)
    g.add("Decision thresholds declared", th_ok,
          "decision_thresholds: [{id, number (or value), statement}] for every threshold the decision rule uses (the Stage 5 report "
          "must state each one numerically with its id)")
    oh = d.get("owner_holds")
    if oh is None:
        g.add("Owner holds declared with source", True, "no owner hold in the design")
        return
    names = {o.get("name") for o in outs or [] if isinstance(o, dict)}
    do = oh.get("decision_output") if isinstance(oh, dict) else None
    holds = oh.get("holds") if isinstance(oh, dict) else None
    ok = (isinstance(do, dict) and do.get("output") in names and text(do.get("final_action_field"))
          and isinstance(do.get("rule_action_fields"), list) and do["rule_action_fields"] and all(text(f) for f in do["rule_action_fields"])
          and isinstance(do.get("hold_values"), list) and do["hold_values"] and all(text(v) for v in do["hold_values"])
          and isinstance(holds, list) and holds
          and all(isinstance(h, dict) and text(h.get("id")) and text(h.get("owner_source")) and text(h.get("statement")) for h in holds))
    g.add("Owner holds declared with source", ok,
          "owner_holds: {decision_output {output (a reconciled output), final_action_field, rule_action_fields[], hold_values[]}, "
          "holds [{id, owner_source, statement}]}: a hold comes from an owner decision and the output keeps the rule's action beside it")


def threshold_value(t):
    """A decision threshold's number (case02 change A6: docs say `number`, older gate code read `value`; both are accepted).
    When both are given they must agree."""
    if not isinstance(t, dict):
        return None
    vals = [_num(str(t[k])) for k in ("number", "value") if k in t and t[k] is not None]
    if not vals or any(v is None for v in vals) or len(set(vals)) != 1:
        return None
    return vals[0]


def _tolerance_shape_ok(tol):
    """The tolerance shape G4a/G4b read: absent, or {fields: [names], absolute_tolerance?, relative_tolerance?,
    numeric_missingness?}. A bare number is not accepted (case02 lesson A2)."""
    if tol is None:
        return True
    if not isinstance(tol, dict) or not isinstance(tol.get("fields", []), list) or not all(text(f) for f in tol.get("fields", [])):
        return False
    for k in ("absolute_tolerance", "relative_tolerance"):
        v = tol.get(k, 0)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            return False
    nm = tol.get("numeric_missingness")
    return nm is None or isinstance(nm, dict)


DECISION_FLIP_KINDS = ("threshold_boundary", "pooling", "missing_values", "duplicate_join")


def decision_flip_checks(g, d):
    """Stage 3 change (2026-11-22): hand-checkable fixtures where a plausible mistake flips the decision. The Grok design
    declares `decision_flip_fixtures` [{kind, fixture, flips}] covering every kind in DECISION_FLIP_KINDS
    (a value exactly at the threshold versus just over it, pooled versus per-unit, missing values, duplicate join rows).
    `fixture` names a declared fixture whose worked answer can be checked by hand and `flips` says which decision the
    mistake would change; a kind that cannot arise in this case gives `not_applicable` with a reason instead.
    These fixtures are the known answers G4a checks for R-A, R-B and SQL, even when the three agree with each other."""
    fids = {f.get("id") for f in d.get("fixtures", []) if isinstance(f, dict)} if isinstance(d.get("fixtures"), list) else set()
    df = d.get("decision_flip_fixtures")
    got, bad = set(), []
    for e in df if isinstance(df, list) else []:
        e = e if isinstance(e, dict) else {}
        k = e.get("kind")
        if k not in DECISION_FLIP_KINDS:
            bad.append(f"unknown kind {k!r}")
            continue
        if text(e.get("not_applicable")) and not PLACEHOLDER_RE.search(e["not_applicable"]):
            got.add(k)
        elif e.get("fixture") in fids and text(e.get("flips")):
            got.add(k)
        else:
            bad.append(f"{k}: needs a declared fixture id and `flips`, or `not_applicable` with a reason")
    missing = [k for k in DECISION_FLIP_KINDS if k not in got]
    g.add("Decision-flip fixtures declared", isinstance(df, list) and not missing and not bad,
          "decision_flip_fixtures: [{kind, fixture, flips} | {kind, not_applicable}] for each of " + ", ".join(DECISION_FLIP_KINDS)
          + (f"; missing: {missing}" if missing else "") + (f"; bad: {bad[:4]}" if bad else ""))


def rounding_tolerance_checks(g, d):
    """Stage 4 change (2026-11-22), within the locked numeric boundary policy (control C39: no post hoc widening).
    A tolerance is allowed only on fields where rounding legitimately differs: every tolerance with fields and a non-zero
    width carries `rounding_reason` (why these fields round differently). Every other field, and every key, identifier,
    count and decision field, is compared exactly."""
    tols = []
    for f in d.get("fixtures", []) if isinstance(d.get("fixtures"), list) else []:
        if isinstance(f, dict):
            tols.append((f"fixture {f.get('id')}", f.get("tolerance")))
    rc = d.get("reconciliation")
    for o in rc.get("outputs", []) if isinstance(rc, dict) and isinstance(rc.get("outputs"), list) else []:
        if isinstance(o, dict):
            tols.append((f"output {o.get('name')}", o.get("tolerance")))
    bad = []
    for lab, t in tols:
        if not isinstance(t, dict) or not t.get("fields"):
            continue
        wide = any(isinstance(t.get(k), (int, float)) and not isinstance(t.get(k), bool) and t.get(k) > 0
                   for k in ("absolute_tolerance", "relative_tolerance"))
        if wide and not (text(t.get("rounding_reason")) and not PLACEHOLDER_RE.search(t["rounding_reason"])):
            bad.append(lab)
    g.add("Tolerances only on declared rounding fields", not bad,
          "a non-zero tolerance names its fields and gives `rounding_reason`; all other fields match exactly"
          + (f"; no rounding_reason: {bad}" if bad else ""))


def next_stage_entry_checks(g, root, d):
    """Case02 change A2 (owner rule: a design is not locked until the next stage's entry gates pass on it). Runs the
    G4a/G4b shape checks on the locked fixtures now: each worked answer is compared with itself using the fixture's keys
    and tolerance through the same reconcile.compare that G4a uses, and every tolerance has the shape G4a/G4b read.
    A blank or duplicated key, a missing key column or a bare-number tolerance fails here instead of at Stage 4."""
    fx = d.get("fixtures") if isinstance(d.get("fixtures"), list) else []
    bad = []
    for f in fx:
        f = f if isinstance(f, dict) else {}
        lab = f"fixture {f.get('id')}"
        tol = f.get("tolerance")
        if not _tolerance_shape_ok(tol):
            bad.append(f"{lab}: tolerance must be {{fields: [...], absolute_tolerance, relative_tolerance}}, not {type(tol).__name__}")
            tol = None
        wa = f.get("worked_answer")
        if not ref_current(root, wa):
            bad.append(f"{lab}: worked answer not current")
            continue
        ok, det = reconcile.compare(root, wa, wa, f.get("keys") or [], tol)
        if not ok:
            bad.append(f"{lab}: {det.get('error') or 'self-comparison failed'}")
    rc = d.get("reconciliation")
    outs = rc.get("outputs") if isinstance(rc, dict) and isinstance(rc.get("outputs"), list) else []
    for o in outs:
        o = o if isinstance(o, dict) else {}
        if not _tolerance_shape_ok(o.get("tolerance")):
            bad.append(f"output {o.get('name')}: tolerance must be {{fields: [...], ...}}, not {type(o.get('tolerance')).__name__}")
        keys = o.get("keys")
        if not (isinstance(keys, list) and keys and all(text(k) for k in keys) and len(set(keys)) == len(keys)):
            bad.append(f"output {o.get('name')}: keys must be non-blank and unique")
    g.add("Next-stage entry check (G4a/G4b shape) passes on the locked design", bool(fx) and not bad,
          "each fixture's worked answer compared with itself by G4a's compare, and every tolerance in G4a/G4b's shape"
          + (f"; failed: {bad[:6]}" if bad else ""))


VERSION_IN_NAME = re.compile(r"_v(\d+)\.[A-Za-z0-9]+$")


def _version_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if not isinstance(v, str):
        return None
    m = re.search(r"(?:^|[^A-Za-z0-9])v(\d+)\b", v) or re.search(r"\b(\d+)\b", v)
    return int(m.group(1)) if m else None


def design_version_checks(g, s3):
    """Case02 change A7: every versioned docs/stage3 file the locked design names (deliverables, stage_records) carries the
    locked design version; fixture files carry the fixture version when it has a number. Catches a design locked as v04
    whose deliverables still name the v02 files."""
    s3 = s3 if isinstance(s3, dict) else {}
    dv, fv = _version_number(s3.get("design_version")), _version_number(s3.get("fixture_version"))
    paths = [x for x in s3.get("deliverables", []) if isinstance(x, str)] if isinstance(s3.get("deliverables"), list) else []
    sr = s3.get("stage_records")
    paths += [x.get("path") for x in sr if isinstance(x, dict) and isinstance(x.get("path"), str)] if isinstance(sr, list) else []
    wrong = []
    for pth in dict.fromkeys(paths):
        m = VERSION_IN_NAME.search(pth)
        if not m or not pth.startswith("docs/stage3/"):
            continue
        want = fv if "/fixtures/" in pth else dv
        if want is not None and int(m.group(1)) != want:
            wrong.append(f"{pth} (expected v{want:02d})")
    g.add("Locked design names its own version's files", dv is not None and not wrong,
          f"design_version {s3.get('design_version')!r}" + (f"; wrong version: {wrong[:6]}" if wrong else "; every versioned file matches")
          + ("" if dv is not None else "; design_version has no version number"))


def stale_nested_refs(root, stage):
    """Case02 change A10. [(send id, attachment, nested path, cited sha256)] for every {path, sha256} reference inside a
    JSON attachment of a send in artifacts/operations/<stage>.json that no longer matches the current file, and that is
    not resolved by an H1 historical-send record (artifacts/operations/<stage>.historical.json naming the send, whose
    supersession record maps the path in superseded_inputs to a current archived copy with the cited hash)."""
    ops = _plain_at(root, f"artifacts/operations/{stage}.json")
    sends = ops.get("sends") if isinstance(ops, dict) and isinstance(ops.get("sends"), list) else []
    hist = _plain_at(root, f"artifacts/operations/{stage}.historical.json")
    hmap = {}
    for e in (hist.get("historical_sends") if isinstance(hist, dict) and isinstance(hist.get("historical_sends"), list) else []):
        if isinstance(e, dict) and ref_current(root, e.get("supersession")):
            rec = _plain_at(root, e["supersession"]["path"]) or {}
            named = rec.get("historical_sent_fail") == e.get("send_id") or e.get("send_id") in (rec.get("historical_sends") or [])
            si = rec.get("superseded_inputs") if isinstance(rec.get("superseded_inputs"), dict) else {}
            if named:
                hmap[e.get("send_id")] = si
    out = []
    for snd in sends:
        if not isinstance(snd, dict):
            continue
        for att in snd.get("attachments") or []:
            if not (isinstance(att, dict) and text(att.get("path")) and att["path"].lower().endswith(".json") and ref_current(root, att)):
                continue
            obj = _plain_at(root, att["path"])
            for ref in guards.nested_refs(obj):
                cited = str(ref.get("sha256")).lower()
                if ref_current(root, ref):
                    continue
                arch = hmap.get(snd.get("id"), {}).get(ref.get("path"))
                if isinstance(arch, dict) and str(arch.get("sha256", "")).lower() == cited and ref_current(root, arch):
                    continue
                out.append((snd.get("id"), att["path"], ref.get("path"), cited))
    return out


def stale_nested_ref_checks(g, root, stage):
    stale = stale_nested_refs(root, stage)
    g.add(f"No stale nested references in the {stage} sends", not stale,
          "every {path, sha256} cited inside a sent JSON attachment is current, or the send is declared historical (H1) with an "
          "archived copy of the cited bytes" + (f"; stale: {[f'{a} -> {c} ({b})' for a, b, c, _ in stale[:5]]}" if stale else ""))


def design_lock_guards(g, rels):
    """Lessons L11/L12 (gates/guards.py): no template placeholder reference anywhere in the design files or the JSON files
    they reference, and no blanket ban on labeled descriptive rates."""
    rels = list(dict.fromkeys(r for r in rels if text(r)))
    hits = guards.placeholder_refs(g.root, rels)
    g.add("No template placeholder references in the design", not hits,
          (guards.describe(hits) + " -- " + guards.TEMPLATE_HINT) if hits else "none")
    bans = []
    for rel in rels:
        body = _read_text(g.root, rel)
        if body is None:
            continue
        if rel.lower().endswith(".json"):
            obj = _plain(rel, g)
            body = "\n".join(guards.text_strings(obj, skip_keys=guards.EXPOSURE_KEYS)) if obj is not None else body
        bans += [f"{rel}: {h}" for h in guards.rate_ban_hits(body)]
    g.add("Descriptive rates not banned", not bans,
          "labeled descriptive (associational) rates and differences are allowed and expected; restrict causal wording "
          "instead of banning rates" + (f"; ban found: {bans[:4]}" if bans else ""))


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
    snapshot_binding_checks(g, g.root, o)
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
    corr = corrections_checks(g, root)
    review_checks(g, "artifacts/stage4/reviews/risk_reviewer_g4c.json", "risk_reviewer", files + corr, "Risk Reviewer post-reconciliation")
    return g.result()


CORRECTIONS = "artifacts/stage4/corrections.json"


def corrections_checks(g, root):
    """Case02 change 4: a builder never unlocks and re-freezes a file. A correction to its own file before send is logged in
    artifacts/stage4/corrections.json {corrections[{id, path, old_path?, old_sha256, new_sha256, author_role, reason, logged_at}]};
    `path` is the corrected (new) version and its current hash is new_sha256 (old_path names the earlier version when it differs), and the log is a subject of the G4c review. Returns extra review subjects."""
    full = safe_rel(root, CORRECTIONS)
    if full is None or not os.path.exists(full):
        g.add("Builder corrections logged", True, "no corrections logged")
        return []
    c = g.load(CORRECTIONS, "Builder corrections log") or {}
    es = c.get("corrections")
    bad = []
    for e in es if isinstance(es, list) else []:
        e = e if isinstance(e, dict) else {}
        well = (all(text(e.get(k)) for k in ("id", "path", "author_role", "reason", "logged_at"))
                and all(isinstance(e.get(k), str) and re.fullmatch(r"[0-9a-f]{64}", e[k].lower() or "") for k in ("old_sha256", "new_sha256"))
                and e.get("old_sha256", "").lower() != e.get("new_sha256", "").lower())
        if not (well and ref_current(root, {"path": e.get("path"), "sha256": e.get("new_sha256")})):
            bad.append(e.get("id"))
    g.add("Builder corrections logged", isinstance(es, list) and bool(es) and not bad,
          "corrections: [{id, path (new version), old_path (optional), old_sha256, new_sha256 (= current file at path), author_role, reason, logged_at}]"
          + (f"; malformed or not current: {bad}" if bad else ""))
    return [CORRECTIONS]


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


def evidence_numbers(rel, body):
    """Numbers in an evidence file. CSV/TSV files are read cell by cell (lesson L15: a whole row such as `x,6,3,0.5`
    otherwise reads as one comma-grouped number and no cell value can be traced)."""
    if not isinstance(body, str):
        return set()
    low = str(rel or "").lower()
    if low.endswith((".csv", ".tsv")):
        out = set()
        for row in csv.reader(io.StringIO(body), delimiter="\t" if low.endswith(".tsv") else ","):
            for cell in row:
                out |= numbers_in(cell)
        return out
    return numbers_in(body)


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
    claim_checks(g, root, c, dpaths)
    finish_content_checks(g, root, dpaths)
    ap5 = _plain(FINISH_APPROVAL, g)
    if ap5 is not None:
        g.use(FINISH_APPROVAL)
    comps = companion_checks(g, root, c, approval=ap5)
    status_word_checks(g, root, [pth for pth in dpaths if text(pth)] + comps)
    stale_nested_ref_checks(g, root, "finish")
    subj = [CLAIMS] + [pth for pth in dpaths if text(pth)] + comps
    review_checks(g, S5_REVIEWS[0], "second_designer", subj, "Second Designer inference")
    review_checks(g, S5_REVIEWS[1], "risk_reviewer", subj, "Risk Reviewer numbers")
    stage5_review_shape_checks(g, root)
    repair.cap_checks(g)
    return g.result()


def claim_checks(g, root, c, dpaths):
    """The G5 claim checks, shared by G5 and the G5P precheck so that a precheck mirrors G5 exactly."""
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
        g.add(f"{lab} deliverable listed in deliverables", text(dv) and dv in dpaths,
              f"claim deliverable {dv!r} must be one of the ledger deliverables {sorted(p for p in dpaths if text(p))}; when the report "
              "path changes, update every claim's deliverable field, not only the deliverables list")
        if guards.states_rate(q):
            g.add(f"{lab} rate labeled descriptive", guards.rate_claim_labeled(x),
                  "a rate or difference is reported as descriptive/associational, not causal: say so in `label` or the quote")
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
            ev_nums |= evidence_numbers(e.get("path"), t) if t else set()
        der = x.get("derived", [])
        der = der if isinstance(der, list) else []
        der_ok = all(isinstance(d, dict) and _num(str(d.get("value", ""))) is not None and text(d.get("basis")) for d in der)
        der_vals = {_num(str(d.get("value"))) for d in der if isinstance(d, dict)} if der_ok else set()
        loose = sorted(numbers_in(q) - ev_nums - der_vals) if text(q) else []
        g.add(f"{lab} every number traced", der_ok and not loose,
              "each number in the quote appears in its evidence (CSV evidence is read cell by cell) or is listed under derived "
              "[{value (a numeral), basis}]" + (f"; untraced: {loose}" if loose else "") + ("" if der_ok else "; derived entries malformed"))
    uncovered = [pth for pth in dpaths if text(pth) and pth not in covered]
    g.add("Every deliverable carries a recorded claim", bool(dpaths) and not uncovered, f"no claim quoted from: {uncovered}" if uncovered else "ok")


def _lines(root, dpaths):
    out = []
    for pth in dpaths:
        t = _read_text(root, pth) if text(pth) else None
        out += [(pth, ln) for ln in (t or "").splitlines()]
    return out


def _decision_rows(root, do):
    o = _plain_at(root, OUTPUTS) or {}
    impl = do.get("impl", "ra") if isinstance(do, dict) else "ra"
    ref = (((o.get("outputs") or {}).get(impl) or {}).get(do.get("output")) if isinstance(o.get("outputs"), dict) else None) or {}
    body = _read_text(root, ref.get("path")) if isinstance(ref, dict) and text(ref.get("path")) else None
    if body is None:
        return None
    return list(csv.DictReader(io.StringIO(body)))


def finish_content_checks(g, root, dpaths):
    """Case02 changes 7 and 8 on the Stage 5 deliverables (shared by G5 and G5P)."""
    d = _plain(GROK_DESIGN, g) or {}
    lines = _lines(root, dpaths)
    th = d.get("decision_thresholds") if isinstance(d.get("decision_thresholds"), list) else []
    missing = []
    for t in th:
        if not isinstance(t, dict):
            continue
        tid, val = str(t.get("id", "")), threshold_value(t)
        idre = re.compile(r"(?<![\w-])" + re.escape(tid) + r"(?![\w-])")
        if not any(idre.search(ln) and val in numbers_in(ln) for _, ln in lines):
            missing.append(tid)
    g.add("Decision thresholds stated numerically", bool(th) and not missing,
          "each decision_thresholds entry of the Grok design appears in a deliverable as its number and its id on the same line"
          + (f"; not stated: {missing}" if missing else "") + ("" if th else "; the design declares no decision_thresholds"))
    oh = d.get("owner_holds")
    if not isinstance(oh, dict):
        g.add("Owner hold reported beside the rule's action", True, "no owner hold in the design")
        return
    do = oh.get("decision_output") or {}
    rows = _decision_rows(root, do)
    if rows is None:
        g.add("Owner hold reported beside the rule's action", False, f"decision output {do.get('output')!r} not readable from {OUTPUTS}")
        return
    hold_ids = [h.get("id") for h in oh.get("holds", []) if isinstance(h, dict) and text(h.get("id"))]
    held = [r for r in rows if r.get(do.get("final_action_field")) in (do.get("hold_values") or [])]
    bad = []
    for r in held:
        acts = [r.get(f) for f in do.get("rule_action_fields") or [] if text(r.get(f))]
        ok = bool(acts) and any(all(a in ln for a in acts) and any(h in ln for h in hold_ids) for _, ln in lines)
        if not ok:
            bad.append(acts)
    g.add("Owner hold reported beside the rule's action", not bad,
          ("no hold triggered" if not held else "a triggered owner hold is reported on the same line as the action the stated rule "
           "decides (rule action values and the hold id); the hold stays with the owner, the rule's action is never withheld")
          + (f"; rule action not reported beside the hold: {bad}" if bad else ""))


S5_REVIEWS = ("artifacts/stage5/reviews/second_designer_inference.json", "artifacts/stage5/reviews/risk_reviewer_numbers.json")
G4C_REVIEW = "artifacts/stage4/reviews/risk_reviewer_g4c.json"
COMPANION_IN_APPROVAL = re.compile(r"\bcompanion\s+(?:file\s+)?(\S+?)\s+sha256[ =:]*([0-9a-fA-F]{64})\b")


def declared_companions(c, approval):
    """Companion files of the finish package (case02 change A5): `companions: [{path, sha256}]` in the claims ledger or the
    owner finish approval, or a `companion <path> sha256 <hash>` phrase in the approval text. Returns {path: sha256}."""
    out = {}
    for src in (c, approval):
        cs = src.get("companions") if isinstance(src, dict) else None
        for x in cs if isinstance(cs, list) else []:
            if isinstance(x, dict) and text(x.get("path")):
                out.setdefault(x["path"], str(x.get("sha256", "")).lower())
    at = approval.get("approval_text") if isinstance(approval, dict) else None
    for m in COMPANION_IN_APPROVAL.finditer(at or ""):
        out.setdefault(m.group(1).rstrip(";,."), m.group(2).lower())
    return out


def companion_checks(g, root, c, approval):
    """Every declared companion is current at its declared hash and every source declares the same hash. Returns the paths,
    which G5 adds to the review subjects of both Stage 5 reviews and to the status-word check."""
    comps = declared_companions(c, approval)
    srcs = []
    for src in (c, approval):
        cs = src.get("companions") if isinstance(src, dict) and isinstance(src.get("companions"), list) else []
        srcs.append({x.get("path"): str(x.get("sha256", "")).lower() for x in cs if isinstance(x, dict)})
    at = approval.get("approval_text") if isinstance(approval, dict) else None
    srcs.append({m.group(1).rstrip(";,."): m.group(2).lower() for m in COMPANION_IN_APPROVAL.finditer(at or "")})
    clash = sorted({p for s in srcs for p in s if any(p in t and t[p] != s[p] for t in srcs)})
    stale = [p for p, h in comps.items() if not ref_current(root, {"path": p, "sha256": h})]
    for p in comps:
        if not stale or p not in stale:
            g.use(p)
    g.add("Companion files current", not stale and not clash,
          ("no companion declared" if not comps else f"companions {sorted(comps)}")
          + (f"; not current: {stale}" if stale else "") + (f"; declared with different hashes: {clash}" if clash else ""))
    return sorted(comps)


ID_TOKEN = r"(?:[A-Z][A-Z0-9]*-[A-Z0-9]*\d+|-\d+)"
STATUS_CLAIM_RE = re.compile(r"(?P<ids>" + ID_TOKEN + r"(?:\s*(?:,|and|&|or|,\s*and)\s*" + ID_TOKEN + r")*)\s+"
                             r"(?:(?:is|are|was|were|has\s+been|have\s+been|now|marked|listed|recorded|treated|as)\s+){0,3}"
                             r"(?P<word>resolved|closed|fixed)\b", re.IGNORECASE)
NEGATED_RE = re.compile(r"\b(?:not|never|un)\s*(?:yet\s+)?$", re.IGNORECASE)
CARRY_NEG_RE = re.compile(r"\b(?:does\s+not|do\s+not|not)\s+carr|\bomit|\bleaves?\s+out\b", re.IGNORECASE)


def _expand_ids(chunk):
    ids, prefix = [], None
    for tok in re.findall(ID_TOKEN, chunk):
        if tok.startswith("-"):
            if prefix:
                ids.append(prefix + tok[1:].zfill(2) if len(tok) <= 3 else prefix + tok[1:])
        else:
            ids.append(tok)
            prefix = tok.rsplit("-", 1)[0] + "-"
    return ids


def status_claims(body):
    """[(finding id, word, sentence)] where text calls a finding resolved, closed or fixed (e.g. "marks G4C-02, -04 and -07 as
    resolved"; "G4C-11 is closed"). A negated statement ("is not resolved") is not a claim."""
    out = []
    for sent in re.split(r"(?<=[.;!?])\s+|\n+", body or ""):
        for m in STATUS_CLAIM_RE.finditer(sent):
            between = sent[m.end("ids"):m.start("word")]
            if re.search(r"\bnot\b|\bnever\b|\byet\b", between, re.IGNORECASE):
                continue
            ids = _expand_ids(m.group("ids"))
            if re.match(r"\s*(?:is|was|has\s+been)\b", between, re.IGNORECASE):
                ids = ids[-1:]  # singular verb: only the last id is the subject ("..., and G4C-11 is closed")
            for fid in ids:
                out.append((fid, m.group("word").lower(), sent.strip()[:200]))
    return out


def status_word_checks(g, root, rels):
    """Case02 change A5. (1) A deliverable or companion that calls a G4c finding resolved/closed/fixed must agree with the
    sealed G4c review, where that finding must be closed. (2) Every finding the Stage 4 methodology triage disposes of as
    carried to the Stage 5 disclosures must be carried: named in a deliverable or companion on a line that does not say it
    is not carried."""
    rv = _plain_at(root, G4C_REVIEW)
    fnd = rv.get("findings") if isinstance(rv, dict) and isinstance(rv.get("findings"), list) else []
    status = {f.get("id"): f.get("status") for f in fnd if isinstance(f, dict) and text(f.get("id"))}
    if not status:
        g.add("Finding status words match the G4c review", True, "no G4c review findings to compare")
        return
    g.use(G4C_REVIEW)
    bodies = {r: _read_text(root, r) or "" for r in rels}
    wrong = [f"{r}: {fid} called {w} but open in the G4c review" for r, b in bodies.items() for fid, w, _ in status_claims(b)
             if status.get(fid) == "open"]
    g.add("Finding status words match the G4c review", not wrong,
          "a statement that a review finding is resolved/closed/fixed must match that finding's status in "
          f"{G4C_REVIEW}" + (f"; mismatch: {wrong[:5]}" if wrong else ""))
    s4 = _plain_at(root, R_STEP["G4d"][1]) or {}
    mref = (s4.get("evidence_receipts") or {}).get("methodology") if isinstance(s4.get("evidence_receipts"), dict) else None
    meth = _plain_at(root, mref["path"]) if ref_current(root, mref) else None
    tri = meth.get("triage") if isinstance(meth, dict) and isinstance(meth.get("triage"), list) else []
    carried = [t.get("id") for t in tri if isinstance(t, dict) and t.get("id") in status
               and re.search(r"carried|disclos", str(t.get("disposition", "")), re.IGNORECASE)]
    lines = [ln for b in bodies.values() for ln in b.splitlines()]
    not_carried = []
    for fid in carried:
        idre = re.compile(r"(?<![\w-])" + re.escape(fid) + r"(?![\w-])")
        if not any(idre.search(ln) and not _id_in_negated_carry(ln, fid) for ln in lines):
            not_carried.append(fid)
    if tri:
        g.use(mref["path"])
    g.add("Triage 'carried' findings carried in the report", not not_carried,
          ("no triage receipt" if not tri else f"{len(carried)} G4c findings the triage carries to Stage 5")
          + (f"; triage says carried but no deliverable or companion carries: {not_carried}" if not_carried else ""))


def _id_in_negated_carry(line, fid):
    """True when `fid` sits in the part of the line after a "does not carry" style phrase (up to the next ; or .)."""
    for m in CARRY_NEG_RE.finditer(line):
        tail = re.split(r"[;.]", line[m.end():], maxsplit=1)[0]
        if re.search(r"(?<![\w-])" + re.escape(fid) + r"(?![\w-])", tail):
            return True
    return False


def stage5_review_shape_checks(g, root):
    """Case02 change A9: `uncovered_claims` is a list of claim ids ([] when none, never a note such as "nothing uncovered"),
    and the two Stage 5 reviews use different finding ids (role prefixes SD5-, RR5- and X5- for cross review)."""
    c = _plain_at(root, CLAIMS) or {}
    cids = {x.get("id") for x in c.get("claims", []) if isinstance(x, dict)} if isinstance(c.get("claims"), list) else set()
    bad, ids = [], {}
    for rel in S5_REVIEWS:
        rv = _plain_at(root, rel)
        if not isinstance(rv, dict):
            continue
        uc = rv.get("uncovered_claims", [])
        if not (isinstance(uc, list) and all(isinstance(u, str) and u in cids for u in uc)):
            bad.append(f"{rel}: uncovered_claims {uc!r}")
        for f in rv.get("findings", []) if isinstance(rv.get("findings"), list) else []:
            if isinstance(f, dict) and text(f.get("id")):
                ids.setdefault(f["id"], set()).add(rel)
    g.add("Stage 5 uncovered_claims are claim ids", not bad,
          "uncovered_claims: [] or a list of claim ids from the ledger; no notes" + (f"; bad: {bad}" if bad else ""))
    clash = sorted(i for i, rs in ids.items() if len(rs) > 1)
    g.add("Stage 5 finding ids distinct across reviews", not clash,
          "each review prefixes its finding ids by role (SD5-, RR5-; X5- for cross review)" + (f"; used by both: {clash[:8]}" if clash else ""))


def g5p(root, ledger=CLAIMS):
    """G5P: the G5 claim and content checks on any claims ledger (e.g. a child's reply before placement). Writes nothing unless run
    through gates.run with a record; no R, review or G4d checks. A clean G5P means these G5 checks will pass on the placed ledger."""
    g = Gate("G5P", root)
    c = g.load(ledger, "Claims ledger") or {}
    g.extra["ledger"] = ref_of(root, ledger)  # the exact ledger this precheck judged (known fix 3; read by G0)
    dl = c.get("deliverables")
    dl = dl if isinstance(dl, list) else []
    dpaths = [x.get("path") for x in dl if isinstance(x, dict)]
    g.add("Deliverables declared and current", bool(dl) and all(ref_current(root, x) for x in dl) and len(set(dpaths)) == len(dpaths),
          "deliverables: [{path, sha256}] current, no duplicates")
    claim_checks(g, root, c, dpaths)
    finish_content_checks(g, root, dpaths)
    comps = companion_checks(g, root, c, approval=None)
    status_word_checks(g, root, [pth for pth in dpaths if text(pth)] + comps)
    stale_nested_ref_checks(g, root, "finish")
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
         "G5": g5, "G5P": g5p, "G6": g6}
