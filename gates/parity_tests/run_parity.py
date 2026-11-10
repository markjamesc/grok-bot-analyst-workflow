"""Run the R gate test suites with the Python port shadowing every gate call, then summarise parity.

usage: python3 -m gates.parity_tests.run_parity --r-repo /path/to/ai-augmented-analyst-workflow [--out DIR] [--only NAME ...]

The R repo is copied to a scratch rig (it is never modified). In the rig, each R test script gets one line
prepended that sources r_prelude.R; nothing else in the test changes, so the R suite must still pass.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(os.path.dirname(HERE))
SUITES = [
    "workflow-gate/tests/test_workflow_gate.R",
    "procedure-gate/tests/test_procedure_gate.R",
    "procedure-gate/tests/test_historical_sends.R",
    "methodology/tests/test_methodology.R",
    "methodology/tests/test_targeted_gates.R",
    "methodology/tests/test_acceptance.R",
    "methodology/tests/test_livefix.R",
    "methodology/tests/test_remediation.R",
    "methodology/tests/test_successor.R",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--r-repo", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--rscript", default=shutil.which("Rscript") or "Rscript")
    a = ap.parse_args()
    out = a.out or tempfile.mkdtemp(prefix="gates-parity-")
    os.makedirs(out, exist_ok=True)
    rig = os.path.join(out, "rig")
    if os.path.exists(rig):
        shutil.rmtree(rig)
    shutil.copytree(a.r_repo, rig, ignore=shutil.ignore_patterns(".git"))
    prelude = os.path.join(HERE, "r_prelude.R")
    results = {}
    for rel in SUITES:
        name = os.path.basename(rel)
        if a.only and name not in a.only and rel not in a.only:
            continue
        path = os.path.join(rig, rel)
        if not os.path.exists(path):
            results[name] = {"present": False}
            continue
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f'source("{prelude}")\n' + body)
        log = os.path.join(out, name + ".parity.jsonl")
        if os.path.exists(log):
            os.remove(log)
        env = dict(os.environ, PARITY_LOG=log, PARITY_PKG_ROOT=PKG_ROOT, PARITY_PYTHON=sys.executable)
        t0 = time.time()
        p = subprocess.run([a.rscript, path, rig], cwd=rig, env=env, capture_output=True, text=True)
        with open(os.path.join(out, name + ".R.log"), "w") as fh:
            fh.write(p.stdout + "\n--- stderr ---\n" + p.stderr)
        recs = []
        if os.path.exists(log):
            with open(log, encoding="utf-8") as fh:
                recs = [json.loads(line) for line in fh if line.strip()]
        by = collections.defaultdict(lambda: {"match": 0, "mismatch": 0, "skipped": 0})
        for r in recs:
            key = r["kind"] + ":" + str(r.get("name"))
            by[key]["match" if r.get("match") is True else "mismatch" if r.get("match") is False else "skipped"] += 1
        results[name] = {"present": True, "r_exit": p.returncode, "r_tail": p.stdout.strip().splitlines()[-3:],
                         "seconds": round(time.time() - t0, 1), "comparisons": len(recs),
                         "mismatches": sum(v["mismatch"] for v in by.values()), "by": dict(by)}
        print(json.dumps({name: results[name]}, indent=1), flush=True)
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    print("OUT", out)
    bad = [n for n, v in results.items() if v.get("present") and (v["r_exit"] != 0 or v["mismatches"] or not v["comparisons"])]
    print("PARITY", "PASS" if not bad else "FAIL " + ", ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
