"""Repair round 4 (2026-11-22): each test reproduces a false PASS that the round 3 independent review found on e1f257a.
In each case a gate judged one read of a file and recorded the hash from another read of it.

1. G0 judged the current G5P record (a PASS) and recorded the hash of a G5P FAIL published right after that read.
2. G5P parsed one ledger and recorded the hash of another one that was at the path before and after the parse.
3. G6 judged an earlier gate record (a PASS) and recorded the hash of a FAIL published right after that read.
4. The explainer still gave the G1 and G3S runs to the parent.

The hooks act on the n-th time a gate opens a file, not on any function name, so they apply to any implementation.
"""
from __future__ import annotations

import builtins
import glob
import hashlib
import io
import json
import os
import shutil
import unittest
from unittest import mock

from gates import attempt as A
from gates import stage_gates as SG
from gates.run import run_gate
from gates.tests import fixture_project as F
from gates.tests import test_finish_gates as TFG

failed = TFG.failed
REAL_OPEN = builtins.open


def _bytes(path):
    with REAL_OPEN(path, "rb") as fh:
        return fh.read()


def _put(path, data):
    with REAL_OPEN(path, "wb") as fh:
        fh.write(data)


class PublishAfterFirstRead:
    """Replace `path` with `new_bytes` right after the gate's first read of it (before any second open). If the gate never
    opens it a second time, `finish()` replaces it after the gate returns: either way the replacement comes after the read
    the gate judged, so the gate's record must not be current afterwards."""

    def __init__(self, path, new_bytes):
        self.path, self.new, self.opens, self.done = os.path.abspath(path), new_bytes, 0, False

    def __call__(self, file, mode="r", *args, **kw):
        if isinstance(file, (str, bytes, os.PathLike)) and os.path.abspath(os.fsdecode(file)) == self.path \
                and "r" in mode and "+" not in mode:
            self.opens += 1
            if self.opens == 2 and not self.done:
                self.done = True
                _put(self.path, self.new)
        return REAL_OPEN(file, mode, *args, **kw)

    def finish(self):
        if not self.done:
            self.done = True
            _put(self.path, self.new)


def _fail_copy(path):
    rec = json.loads(_bytes(path))
    rec["result"] = "FAIL"
    return (json.dumps(rec, indent=2) + "\n").encode("utf-8")


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build an R-certified project")
class RepairRound4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TFG.FinishGates.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        RepairRound4.n += 1
        d = os.path.join(self.tmp, f"r4_{RepairRound4.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    def _hist_for(self, r, rec):
        return [os.path.relpath(h, r) for h in glob.glob(os.path.join(r, "artifacts/gates/history/G5P-*.json"))
                if F.rj(r, os.path.relpath(h, r)).get("attempt_id") == rec["attempt_id"]][0]

    # ---- 1. G0 records the G5P record it judged
    def test_g0_does_not_record_a_g5p_fail_published_after_it_judged_the_pass(self):
        r = self.copy()
        p = run_gate("G5P", r, ledger=SG.CLAIMS)
        self.assertEqual(p["result"], "PASS", failed(p))
        out = "artifacts/stage5/reviews/risk_reviewer_numbers.json"
        body = F.packet_text(r, "CASE-5-01", role="Risk Reviewer", stage="5", inputs=[SG.CLAIMS, *F.DELIVERABLES, self._hist_for(r, p)],
                             expected=out)
        F.add_packets(r, [("CASE-5-01", body, "answered", F.reply_text("CASE-5-01", (out,)))])
        cur = os.path.join(r, "artifacts/gates/G5P.json")
        hook = PublishAfterFirstRead(cur, _fail_copy(cur))
        with mock.patch("builtins.open", hook):
            g0 = run_gate("G0", r, attempt_id="G0-r4-1")
        hook.finish()
        self.assertEqual(g0["result"], "PASS", failed(g0))           # it judged the PASS it read
        ok, det = A.attempt_check(r, "G0", "G0-r4-1")
        self.assertFalse(ok, f"the G5P record G0 judged was replaced by a FAIL; G0 must not stay current: {det}")

    # ---- 2. G5P records the ledger it parsed
    def test_g5p_never_passes_a_ledger_it_did_not_parse(self):
        base = self.copy()
        valid = _bytes(os.path.join(base, SG.CLAIMS))
        bad = json.loads(valid)
        bad["claims"][0]["quote"] = "This quotation is absent from the report."
        bad_bytes = (json.dumps(bad, indent=2) + "\n").encode("utf-8")
        bad_sha = hashlib.sha256(bad_bytes).hexdigest()
        for k in range(1, 7):                                         # serve the valid ledger on the k-th open only
            r = self.copy()
            path = os.path.abspath(os.path.join(r, SG.CLAIMS))
            _put(path, bad_bytes)
            self.assertEqual(run_gate("G5P", r, ledger=SG.CLAIMS, record=False)["result"], "FAIL")
            state = {"n": 0}

            def serve_valid_once(file, mode="r", *args, **kw):
                if isinstance(file, (str, os.PathLike)) and os.path.abspath(os.fspath(file)) == path and mode in ("r", "rb"):
                    state["n"] += 1
                    if state["n"] == k:
                        return io.BytesIO(valid) if "b" in mode else io.StringIO(valid.decode("utf-8"))
                return REAL_OPEN(file, mode, *args, **kw)

            with mock.patch("builtins.open", serve_valid_once):
                rec = run_gate("G5P", r, ledger=SG.CLAIMS)
            self.assertFalse(rec["result"] == "PASS" and (rec.get("ledger") or {}).get("sha256") == bad_sha,
                             f"open #{k}: G5P recorded PASS for a ledger it did not parse")
            self.assertNotEqual(rec["result"], "PASS", f"open #{k}: {failed(rec)}")

    # ---- 3. G6 records the earlier gate records it judged
    def test_g6_does_not_record_a_g0_fail_published_after_it_judged_the_pass(self):
        r = self.copy()
        cur = os.path.join(r, "artifacts/gates/G0.json")
        hook = PublishAfterFirstRead(cur, _fail_copy(cur))
        with mock.patch("builtins.open", hook):
            g6 = run_gate("G6", r, attempt_id="G6-r4-1")
        hook.finish()
        self.assertEqual(g6["result"], "PASS", failed(g6))
        ok, det = A.attempt_check(r, "G6", "G6-r4-1")
        self.assertFalse(ok, f"the G0 record G6 judged was replaced by a FAIL; G6 must not stay current: {det}")


class ExplainerRoles(unittest.TestCase):
    def test_explainer_names_the_gate_runner(self):
        with REAL_OPEN(os.path.join(F.PKG, "docs/explainer.md"), encoding="utf-8") as fh:
            s = fh.read()
        self.assertNotIn("The parent pins the workflow and checks it at the start gate G1", s)
        self.assertNotIn("the parent runs them", s)
        self.assertIn("the Gate Runner runs the start gate G1", s)
        self.assertIn("Database Connector", s)


if __name__ == "__main__":
    unittest.main()
