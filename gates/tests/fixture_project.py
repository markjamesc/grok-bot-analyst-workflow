"""Builds a complete synthetic project for the Grok gates on top of an R-referee-valid project.

The R part (stage receipts, operations ledgers, Stage 4 evidence) is built by the R repo's own test helpers
(make_r_project.R), so the ported R checks inside G1/G2/G3/G4d see exactly what the R gate sees in its own tests.
"""
from __future__ import annotations

import hashlib
import json
import os


def _rb(p):
    with open(p, "rb") as fh:
        return fh.read()
import shutil
import sqlite3
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(os.path.dirname(HERE))


def rscript():
    """Path of Rscript found on PATH. Fails clearly if Rscript is not on PATH (there is no fallback location)."""
    path = shutil.which("Rscript")
    if not path:
        raise RuntimeError("Rscript was not found on PATH. Put an R installation's bin directory on PATH "
                           "before running the gates tests.")
    return path


def r_repo():
    """The R workflow repo named by GATES_R_REPO. Fails clearly if it is unset or not an R workflow repo."""
    path = os.environ.get("GATES_R_REPO")
    if not path:
        raise RuntimeError("GATES_R_REPO is not set. Set it to a local checkout of the R workflow repo, "
                           "e.g. GATES_R_REPO=<path to R repo> python3 -m unittest discover -s gates/tests -t .")
    if not os.path.isdir(os.path.join(path, "procedure-gate")):
        raise RuntimeError(f"GATES_R_REPO={path!r} does not look like the R workflow repo "
                           "(no procedure-gate/ directory).")
    return path


def r_available():
    """True when Rscript and the R repo are usable; raises a clear RuntimeError otherwise (never skips silently)."""
    rscript()
    r_repo()
    return True


def sha(path):
    return hashlib.sha256(_rb(path)).hexdigest()


def wj(root, rel, obj):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    return {"path": rel, "sha256": sha(p)}


def wt(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return {"path": rel, "sha256": sha(p)}


def ref(root, rel):
    return {"path": rel, "sha256": sha(os.path.join(root, rel))}


def rj(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return json.load(fh)


EXTRAS = {
    "stage1_decision.json": {"actions_per_result": [{"result": "above threshold", "action": "expand"},
                                                    {"result": "below threshold", "action": "hold"}],
                             "limits": ["No causal claim", "Snapshot window only"]},
    "stage2_framing.json": {"population": "Active customers", "metric": "Order amount per customer", "threshold": 10,
                            "window": {"start": "2026-01-01", "end": "2026-03-31"},
                            "review_subjects": ["docs/stage2/FRAMING_RECORD.md"]},
}

CSV_SUMMARY = "customer_id,total,n_orders\nc1,15.5,2\nc2,7,1\n"
CSV_ORDERS = "id,customer_id,amount\n1,c1,10\n2,c1,5.5\n3,c2,7\n"


def build_r_project(root, last=4):
    extras = os.path.join(os.path.dirname(root), os.path.basename(root) + "-extras.json")
    with open(extras, "w") as fh:
        json.dump(EXTRAS, fh)
    rs = rscript()
    env = dict(os.environ, PATH=os.path.dirname(rs) + os.pathsep + os.environ.get("PATH", ""))
    p = subprocess.run([rs, os.path.join(HERE, "make_r_project.R"), r_repo(), root, extras, str(last)],
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise RuntimeError(p.stdout + p.stderr)


def review(root, rel, role, subjects, findings=None):
    return wj(root, rel, {"role": role, "subjects": [ref(root, s) for s in subjects],
                          "findings": findings if findings is not None else [{"id": "A1", "class": "advisory", "status": "open"}]})


def add_stage2(root, pin_base):
    wt(pin_base, "docs/workflow.md", "pinned workflow text\n")
    wj(root, "artifacts/workflow_pin.json", {"base": pin_base, "commit": "a331d6c", "files": [ref(pin_base, "docs/workflow.md")]})
    review(root, "artifacts/stage2/reviews/second_designer_critique.json", "second_designer", ["docs/stage2/FRAMING_RECORD.md"])
    review(root, "artifacts/stage2/reviews/risk_reviewer_framing_check.json", "risk_reviewer", ["docs/stage2/FRAMING_RECORD.md"])


def add_feasibility(root, feas="yes", extra_q=None):
    q = {"question_id": "question-1", "feasibility": feas, "reason": "All needed tables exist with keys",
         "structure": [{"table": "orders", "column": "id", "type": "integer", "primary_key": True}],
         "quality": [{"table": "orders", "column": "amount", "null_rate": 0.0}]}
    if extra_q:
        q.update(extra_q)
    wj(root, "artifacts/stage2f_feasibility.json", {"stage": "2F", "questions": [q]})
    review(root, "artifacts/stage2f/reviews/risk_reviewer_feasibility.json", "risk_reviewer", ["artifacts/stage2f_feasibility.json"])


SQL = {
    "completeness": ("extraction_completeness", "SELECT 'orders short' AS problem WHERE (SELECT COUNT(*) FROM orders) <> 3"),
    "keys": ("keys", "SELECT id, COUNT(*) AS n FROM orders GROUP BY id HAVING COUNT(*) > 1"),
    "joins": ("joins", "SELECT o.id FROM orders o LEFT JOIN customers c ON o.customer_id = c.id WHERE c.id IS NULL"),
    "counts": ("counts", "SELECT 'customers' AS t WHERE (SELECT COUNT(*) FROM customers) <> 2"),
}


def make_snapshot(path, dup_order=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE orders(id INTEGER, customer_id TEXT, amount REAL)")
    con.execute("CREATE TABLE customers(id TEXT)")
    rows = [(1, "c1", 10), (2, "c1", 5.5), (3, "c2", 7)] + ([(3, "c2", 7)] if dup_order else [])
    con.executemany("INSERT INTO orders VALUES (?,?,?)", rows)
    con.executemany("INSERT INTO customers VALUES (?)", [("c1",), ("c2",)])
    con.commit()
    con.close()


def add_stage3(root, sql_overrides=None):
    make_snapshot(os.path.join(root, "data/snapshot.sqlite"))
    gates = []
    for name, (kind, q) in SQL.items():
        q = (sql_overrides or {}).get(name, q)
        gates.append({"id": name, "check": kind, "sql": wt(root, f"sql/g3s/{name}.sql", q + "\n")})
    wj(root, "artifacts/stage3/source_gates/manifest.json",
       {"database": {"engine": "sqlite", "snapshot": ref(root, "data/snapshot.sqlite")}, "gates": gates})
    wt(root, "data/orders.csv", CSV_ORDERS)
    wt(root, "fixtures/F1_input.csv", CSV_ORDERS)
    wt(root, "fixtures/F1_expected.csv", CSV_SUMMARY)
    design = {"fixtures": [{"id": "F1", "input": ref(root, "fixtures/F1_input.csv"), "worked_answer": ref(root, "fixtures/F1_expected.csv"),
                            "keys": ["customer_id"]}],
              "reconciliation": {"outputs": [{"name": "summary", "keys": ["customer_id"]}]},
              "early_checks": {"keys": [{"id": "orders_pk", "table": ref(root, "data/orders.csv"), "columns": ["id"]}],
                               "counts": [{"id": "orders_n", "table": ref(root, "data/orders.csv"), "expected_rows": 3}]},
              "review_subjects": ["artifacts/stage3_grok_design.json", "artifacts/stage3_locked_design.json"]}
    wj(root, "artifacts/stage3_grok_design.json", design)
    subj = design["review_subjects"]
    review(root, "artifacts/stage3/reviews/second_designer_compare.json", "second_designer", subj)
    review(root, "artifacts/stage3/reviews/risk_reviewer_red_team.json", "risk_reviewer", subj)
    review(root, "artifacts/stage3/reviews/risk_reviewer_source_gates.json", "risk_reviewer",
           ["artifacts/stage3/source_gates/manifest.json"] + [g["sql"]["path"] for g in gates])
    approve_design(root)


def approve_design(root, text="Approved: design hash as listed"):
    wj(root, "artifacts/stage3_owner_approval.json", {"design_sha256": sha(os.path.join(root, "artifacts/stage3_locked_design.json")),
                                                     "grok_design_sha256": sha(os.path.join(root, "artifacts/stage3_grok_design.json")),
                                                     "approval_text": text, "approval_timestamp": "2026-11-09T12:00:00-06:00"})


def add_stage4_outputs(root, overrides=None):
    o = {"outputs": {}, "fixtures": {}}
    for impl in ("ra", "rb", "sql"):
        body = (overrides or {}).get(impl, CSV_SUMMARY)
        o["outputs"][impl] = {"summary": wt(root, f"outputs/{impl}/summary.csv", body)}
        fbody = (overrides or {}).get(f"{impl}_F1", CSV_SUMMARY)
        o["fixtures"][impl] = {"F1": wt(root, f"outputs/{impl}/fixtures/F1.csv", fbody)}
    wj(root, "artifacts/stage4/outputs.json", o)


def add_g4c_review(root, findings=None):
    o = rj(root, "artifacts/stage4/outputs.json")
    files = ["artifacts/gates/G4b.json"] + [r["path"] for impl in ("ra", "rb", "sql") for r in o["outputs"][impl].values()]
    review(root, "artifacts/stage4/reviews/risk_reviewer_g4c.json", "risk_reviewer", files, findings)


def add_assembly(root):
    split = {"name": "W", "items_key": "case_expected", "expected_ids": ["c1", "c2", "c3"], "item_required_fields": ["fixture_id", "tables"],
             "header": {"part": 1, "key": "header", "required_fields": ["covered_tables"]},
             "coverage": {"header_field": "covered_tables", "item_field": "tables"},
             "parts": [{"part": 1, "reply": "transcripts/W1_reply.md", "end_marker": "ANSWERED W-1", "item_ids": ["c1", "c2"]},
                       {"part": 2, "reply": "transcripts/W2_reply.md", "end_marker": "ANSWERED W-2", "item_ids": ["c3"]}],
             "output": "docs/W_whole.json", "log": "evidence/W_transform_log.json", "part_dir": "artifacts/parts/W"}
    wj(root, "operator/W_split.json", split)
    p1 = {"part": 1, "header": {"covered_tables": ["t1"]}, "case_expected": {
        "c1": {"fixture_id": "F1", "tables": {"t1": [1]}}, "c2": {"fixture_id": "F1", "tables": {"t1": [2]}}}}
    p2 = {"part": 2, "case_expected": {"c3": {"fixture_id": "F2", "tables": {"t1": [3]}}}}
    wt(root, "transcripts/W1_reply.md", "Here is part 1.\n```json\n" + json.dumps(p1, indent=1) + "\n```\nANSWERED W-1\n")
    wt(root, "transcripts/W2_reply.md", "Part 2:\n```\n" + json.dumps(p2, indent=1) + "\n```\nANSWERED W-2\n")
    wj(root, "artifacts/assembly/index.json", {"assemblies": [{"split": "operator/W_split.json"}]})
    return "operator/W_split.json"
