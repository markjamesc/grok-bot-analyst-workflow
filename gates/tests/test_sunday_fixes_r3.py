"""Repair round 3 (2026-11-22): each test reproduces a result the round 2 independent review found on 584ad98.

1. G5P parsed one ledger and recorded the hash of a ledger written just after parsing.
2. A later G5P run left an earlier G0 record current, and a rerun on unchanged bytes made G0 reject the first reviewer's packet.
3. G5 passed while the recorded R finish completion was later than G5 itself.
4. Four instructions still gave the G1 check, captures or sealing to the wrong role.
"""
from __future__ import annotations

import datetime
import glob
import os
import shutil
import unittest
from unittest import mock

from gates import attempt as A
from gates import common as C
from gates import stage_gates as SG
from gates.run import run_gate
from gates.tests import fixture_project as F
from gates.tests import test_finish_gates as TFG

failed = TFG.failed


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build an R-certified project")
class RepairRound3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TFG.FinishGates.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        RepairRound3.n += 1
        d = os.path.join(self.tmp, f"r3_{RepairRound3.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    EXACT = "Packet CASE-5-01 Stage 5 precheck PASS for the exact ledger"

    def _hist_for(self, r, rec):
        return [os.path.relpath(h, r) for h in glob.glob(os.path.join(r, "artifacts/gates/history/G5P-*.json"))
                if F.rj(r, os.path.relpath(h, r)).get("attempt_id") == rec["attempt_id"]][0]

    def _s5_packet(self, r, pid, inputs, status="answered"):
        out = f"artifacts/stage5/reviews/{'risk_reviewer_numbers' if pid.endswith('1') else 'second_designer_inference'}.json"
        role = "Risk Reviewer" if pid.endswith("1") else "Second Designer"
        body = F.packet_text(r, pid, role=role, stage="5", inputs=inputs, expected=out)
        return (pid, body, status, F.reply_text(pid, (out,)) if status == "answered" else None)

    # ---- 1. G5P hashes the ledger before it parses it
    def test_g5p_fails_when_the_ledger_is_replaced_right_after_parsing(self):
        r = self.copy()
        real = C.Gate.load
        bad = F.rj(r, SG.CLAIMS)
        bad["claims"][0]["quote"] = "This quotation is absent from the report."

        def load_then_replace(gate, rel, label=None):
            obj = real(gate, rel, label)
            if gate.gate_id == "G5P" and rel == SG.CLAIMS:
                F.wj(r, SG.CLAIMS, bad)
            return obj

        with mock.patch.object(C.Gate, "load", load_then_replace):
            rec = run_gate("G5P", r, ledger=SG.CLAIMS)
        self.assertEqual(rec["result"], "FAIL", "the recorded ledger hash must be the hash of the ledger that was checked")
        self.assertIn("Reviewed files unchanged while G5P ran", failed(rec))

    # ---- 2. a later G5P run: G0 goes stale; an unchanged rerun keeps the first packet valid
    def test_later_g5p_run_makes_the_recorded_g0_attempt_stale(self):
        r = self.copy()
        p1 = run_gate("G5P", r, ledger=SG.CLAIMS)
        hist = self._hist_for(r, p1)
        F.add_packets(r, [self._s5_packet(r, "CASE-5-01", [SG.CLAIMS, *F.DELIVERABLES, hist])])
        g0 = run_gate("G0", r, attempt_id="G0-r3-1")
        self.assertEqual(g0["result"], "PASS", failed(g0))
        self.assertTrue(A.attempt_check(r, "G0", "G0-r3-1")[0])
        self.assertEqual(run_gate("G5P", r, ledger=SG.CLAIMS)["result"], "PASS")   # a later G5P run
        ok, det = A.attempt_check(r, "G0", "G0-r3-1")
        self.assertFalse(ok, f"G0 judged the precheck; a later G5P run must make that judgement stale: {det}")

    def test_second_reviewer_precheck_keeps_the_first_packet_valid(self):
        r = self.copy()
        p1 = run_gate("G5P", r, ledger=SG.CLAIMS)
        first = self._s5_packet(r, "CASE-5-01", [SG.CLAIMS, *F.DELIVERABLES, self._hist_for(r, p1)])
        p2 = run_gate("G5P", r, ledger=SG.CLAIMS)                   # fresh precheck before the second packet, same bytes
        second = self._s5_packet(r, "CASE-5-02", [SG.CLAIMS, *F.DELIVERABLES, self._hist_for(r, p2)], status="draft")
        F.add_packets(r, [first, second])
        g0 = run_gate("G0", r)
        self.assertNotIn(self.EXACT, failed(g0))
        self.assertNotIn("Packet CASE-5-02 Stage 5 precheck PASS for the exact ledger", failed(g0))

    def test_failed_later_g5p_run_still_rejects_the_earlier_precheck(self):
        r = self.copy()
        p1 = run_gate("G5P", r, ledger=SG.CLAIMS)
        hist = self._hist_for(r, p1)
        keep = F.DELIVERABLES["stage5-decision.md"]
        F.wt(r, "stage5-decision.md", "Changed.\n")
        self.assertEqual(run_gate("G5P", r, ledger=SG.CLAIMS)["result"], "FAIL")
        F.wt(r, "stage5-decision.md", keep)
        F.add_packets(r, [self._s5_packet(r, "CASE-5-01", [SG.CLAIMS, *F.DELIVERABLES, hist])])
        self.assertIn(self.EXACT, failed(run_gate("G0", r)))

    # ---- 3. G5 cannot precede the recorded R finish completion
    def test_g5_refuses_r_finish_completion_later_than_g5(self):
        r = self.copy()
        st = F.rj(r, SG.RUN_STATE)
        st["completed_steps"]["finish"]["completed_at_utc"] = "2099-01-01T00:00:00Z"
        F.wj(r, SG.RUN_STATE, st)
        rec = run_gate("G5", r)
        self.assertEqual(rec["result"], "FAIL")
        self.assertIn("R finish step completed before G5", failed(rec))


class RoleInstructionsRound3(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(F.PKG, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_remaining_instructions_name_the_role_that_acts(self):
        self.assertNotIn("and check the Lead Designer's decision document at G1", self.read("docs/roles/parent.md"))
        self.assertNotIn("The parent captures every message", self.read("docs/roles/stakeholder.md"))
        self.assertNotIn("owner and captures the answer", self.read("docs/stages.md"))
        self.assertNotIn("before writing and sealing your own Stage 3 design", self.read("docs/roles/second-designer.md"))
        for rel in ("README.md", "docs/stages.md", "docs/handoff.md", "docs/roles/parent.md", "docs/roles/stakeholder.md"):
            low = self.read(rel).lower()
            for phrase in ("the parent captures", "parent runs g", "the parent seals", "parent checks it at g1"):
                self.assertNotIn(phrase, low, f"{rel}: {phrase}")


if __name__ == "__main__":
    unittest.main()
