"""Repair round 2 (2026-11-22): each test reproduces a false PASS that the round 1 independent review found on 9035ebd.

1. The built-in sqlite connector hashed one file and queried another (a '%xx' file name decoded by the URI parser; a file
   swapped at the path around the open).
2. G0 accepted a Stage 5 review packet that pointed at an unchecked ledger or omitted the prechecked reports, and accepted
   an old G5P PASS after a newer G5P run had failed.
3. G5P could record bytes that replaced the checked ones while it ran.
4. A recorded G6 attempt stayed acceptable after a report it certified changed.
5. The attempt check could combine one record's hash with another record's inputs.
6. The documented finish order (owner approval, R finish completion, G5, R finalization, G6) was not enforced.
7. Some instructions still gave the G1 check, SQL execution or sealing to the wrong role.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from gates import attempt as A
from gates import sql_select_only as S
from gates import stage_gates as SG
from gates.run import run_gate
from gates.tests import fixture_project as F
from gates.tests import test_finish_gates as TFG
from gates.tests.test_sunday_changes import MANIFEST, make_g3s_project

failed = TFG.failed


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------- 1. the sqlite connector queries what it hashed
class SqliteConnectorOpensWhatItHashed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grok-r2-sqlite-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_percent_encoded_file_name_queries_the_hashed_file(self):
        # A (requested, one duplicate order) is at data/%42.sqlite; a URI parser reads %42 as 'B'. B is clean.
        make_g3s_project(self.tmp, snap_rel="data/%42.sqlite", dup_order=True)
        F.make_snapshot(os.path.join(self.tmp, "data/B.sqlite"))
        rec = run_gate("G3S", self.tmp)
        self.assertEqual(rec["result"], "FAIL", "G3S must report A's duplicate order, not B's clean result")
        self.assertIn("keys: zero violating rows", failed(rec))
        self.assertNotIn("keys: query ran read-only", failed(rec))

    def test_file_swapped_at_the_path_while_opening_queries_the_hashed_file(self):
        make_g3s_project(self.tmp, dup_order=True)             # A, requested and hashed, has a duplicate order
        a = os.path.join(self.tmp, "data/snapshot.sqlite")
        F.make_snapshot(os.path.join(self.tmp, "data/clean.sqlite"))
        real = sqlite3.connect

        def swapping_connect(database, *args, **kw):
            # move the clean file to A's path only for the open, then move both back (both files stay linked, so the
            # connection keeps reading the clean file while A's path again holds A's bytes)
            clean, parked = os.path.join(self.tmp, "data/clean.sqlite"), a + ".parked"
            os.replace(a, parked)
            os.replace(clean, a)
            try:
                return real(database, *args, **kw)
            finally:
                os.replace(a, clean)
                os.replace(parked, a)

        with mock.patch.object(S.sqlite3, "connect", swapping_connect):
            rec = run_gate("G3S", self.tmp)
        self.assertEqual(rec["result"], "FAIL", "the bytes hashed as A must be the bytes queried")
        self.assertIn("keys: zero violating rows", failed(rec))
        self.assertNotIn("keys: query ran read-only", failed(rec))

    def test_clean_snapshot_still_passes(self):
        make_g3s_project(self.tmp, snap_rel="data/%42 and ?#.sqlite")
        rec = run_gate("G3S", self.tmp)
        self.assertEqual(rec["result"], "PASS", failed(rec))


# ---------------------------------------------------------------- 5. the attempt check judges one record
class AttemptCheckReadsOneRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grok-r2-attempt-")
        make_g3s_project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_record_published_during_the_check_is_not_mixed_in(self):
        old = run_gate("G3S", self.tmp, attempt_id="G3S-old")
        self.assertEqual(old["result"], "PASS", failed(old))
        sql = os.path.join(self.tmp, "sql/g3s/keys.sql")
        with open(sql, "a") as fh:
            fh.write("-- edited after the old attempt\n")       # the old attempt's inputs are now stale
        m = F.rj(self.tmp, MANIFEST)
        for gt in m["gates"]:
            if gt["id"] == "keys":
                gt["sql"] = F.ref(self.tmp, "sql/g3s/keys.sql")
        F.wj(self.tmp, MANIFEST, m)
        cur = os.path.join(self.tmp, "artifacts/gates/G3S.json")
        old_bytes = _read(cur)
        new = run_gate("G3S", self.tmp, attempt_id="G3S-new")    # a genuine newer PASS on the edited SQL
        self.assertEqual(new["result"], "PASS", failed(new))
        new_bytes = _read(cur)
        with open(cur, "wb") as fh:
            fh.write(old_bytes)                                  # the old record is current when the check starts
        real = A.sha256_file
        state = {"swapped": False}

        def publish_during_check(path):
            h = real(path)
            if os.path.abspath(path) == os.path.abspath(cur) and not state["swapped"]:
                state["swapped"] = True
                with open(cur, "wb") as fh:                      # the newer record is published mid-check
                    fh.write(new_bytes)
            return h

        with mock.patch.object(A, "sha256_file", publish_during_check):
            ok, det = A.attempt_check(self.tmp, "G3S", "G3S-old")
        self.assertFalse(ok, f"an attempt whose own inputs are stale must not advance: {det}")


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build an R-certified project")
class RepairRound2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TFG.FinishGates.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        RepairRound2.n += 1
        d = os.path.join(self.tmp, f"r2_{RepairRound2.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    EXACT = "Packet CASE-5-01 Stage 5 precheck PASS for the exact ledger"

    def _precheck_hist(self, r):
        self.assertEqual(run_gate("G5P", r, ledger=SG.CLAIMS)["result"], "PASS")
        cur = F.sha(os.path.join(r, "artifacts/gates/G5P.json"))
        return [os.path.relpath(h, r) for h in glob.glob(os.path.join(r, "artifacts/gates/history/G5P-*.json")) if F.sha(h) == cur][0]

    def _s5_packet(self, r, inputs):
        body = F.packet_text(r, "CASE-5-01", role="Risk Reviewer", stage="5", inputs=inputs,
                             expected="artifacts/stage5/reviews/risk_reviewer_numbers.json")
        F.add_packets(r, [("CASE-5-01", body, "answered", F.reply_text("CASE-5-01", ("artifacts/stage5/reviews/risk_reviewer_numbers.json",)))])
        return run_gate("G0", r)

    # ---- 2. the review packet carries exactly the prechecked package
    def test_g0_rejects_unchecked_ledger_beside_the_prechecked_one(self):
        r = self.copy()
        hist = self._precheck_hist(r)
        other = F.rj(r, SG.CLAIMS)
        other["claims"][0]["quote"] = "A quotation absent from the report."
        F.wj(r, "artifacts/stage5/claims_unchecked.json", other)
        g0 = self._s5_packet(r, [SG.CLAIMS, *F.DELIVERABLES, hist, "artifacts/stage5/claims_unchecked.json"])
        self.assertIn(self.EXACT, failed(g0))

    def test_g0_rejects_packet_that_omits_the_prechecked_reports(self):
        r = self.copy()
        hist = self._precheck_hist(r)
        F.wt(r, "stage5-replacement.md", "A replacement report nobody prechecked.\n")
        g0 = self._s5_packet(r, [SG.CLAIMS, "stage5-replacement.md", hist])
        self.assertIn(self.EXACT, failed(g0))

    def test_g0_rejects_a_precheck_superseded_by_a_later_g5p_run(self):
        r = self.copy()
        hist = self._precheck_hist(r)
        keep = _read(os.path.join(r, "stage5-decision.md"))
        F.wt(r, "stage5-decision.md", "Changed for a newer precheck.\n")
        self.assertEqual(run_gate("G5P", r, ledger=SG.CLAIMS)["result"], "FAIL")   # the newer G5P run fails
        with open(os.path.join(r, "stage5-decision.md"), "wb") as fh:
            fh.write(keep)                                                         # original bytes restored
        g0 = self._s5_packet(r, [SG.CLAIMS, *F.DELIVERABLES, hist])
        self.assertIn(self.EXACT, failed(g0))

    def test_g0_accepts_the_exact_prechecked_package(self):
        r = self.copy()
        hist = self._precheck_hist(r)
        g0 = self._s5_packet(r, [SG.CLAIMS, *F.DELIVERABLES, hist])
        self.assertEqual(g0["result"], "PASS", failed(g0))

    # ---- 3. G5P records only bytes it checked
    def test_g5p_fails_when_a_report_is_replaced_while_it_runs(self):
        r = self.copy()
        real = SG.stale_nested_ref_checks

        def write_during_run(g, root, stage):
            real(g, root, stage)
            F.wt(r, "stage5-evidence.md", "Replaced after the content checks, before the hashes were recorded.\n")

        with mock.patch.object(SG, "stale_nested_ref_checks", write_during_run):
            rec = run_gate("G5P", r, ledger=SG.CLAIMS)
        self.assertEqual(rec["result"], "FAIL", "G5P must not certify bytes it did not check")
        self.assertIn("Reviewed files unchanged while G5P ran", failed(rec))

    # ---- 4. an accepted G6 attempt depends on every report it certified
    def test_recorded_g6_attempt_is_stale_after_a_report_edit(self):
        r = self.copy()
        g6 = run_gate("G6", r, attempt_id="G6-r2-1")
        self.assertEqual(g6["result"], "PASS", failed(g6))
        self.assertTrue(A.attempt_check(r, "G6", "G6-r2-1")[0])
        F.wt(r, "monitoring-plan.md", F.DELIVERABLES["monitoring-plan.md"] + "Edited after G6.\n")
        ok, det = A.attempt_check(r, "G6", "G6-r2-1")
        self.assertFalse(ok, det)

    # ---- 6. the documented finish order is enforced
    def test_g5_requires_the_exact_owner_approval_first(self):
        r = self.copy()
        os.remove(os.path.join(r, SG.FINISH_APPROVAL))
        rec = run_gate("G5", r)
        self.assertIn("Owner approved the exact finish package before G5", failed(rec))

    def test_g5_requires_r_finish_completion_after_the_approval(self):
        r = self.copy()
        st = F.rj(r, SG.RUN_STATE)
        st["completed_steps"].pop("finish", None)
        F.wj(r, SG.RUN_STATE, st)
        rec = run_gate("G5", r)
        self.assertIn("R finish step completed after the owner approval", failed(rec))
        r2 = self.copy()
        ap = F.rj(r2, SG.FINISH_APPROVAL)
        ap["approval_timestamp"] = "2099-01-01T00:00:00Z"        # approval recorded after R completed finish
        F.wj(r2, SG.FINISH_APPROVAL, ap)
        self.assertIn("R finish step completed after the owner approval", failed(run_gate("G5", r2)))

    def test_g6_refuses_g5_run_after_r_finalization(self):
        r = self.copy()
        time.sleep(1.1)
        self.assertEqual(run_gate("G5", r)["result"], "PASS")    # G5 rerun after R finalized: reversed order
        rec = run_gate("G6", r)
        self.assertEqual(rec["result"], "FAIL")
        self.assertIn("Finish steps in the documented order", failed(rec))


# ---------------------------------------------------------------- 7. who does what, in every instruction
class RoleInstructions(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(F.PKG, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_instructions_name_the_role_that_acts(self):
        readme, stages, handoff = self.read("README.md"), self.read("docs/stages.md"), self.read("docs/handoff.md")
        self.assertNotIn("the parent pins the workflow and checks it at G1", readme)
        self.assertNotIn("The parent pins the workflow and checks it at the start gate G1", stages)
        self.assertIn("the Gate Runner runs G1", readme)
        self.assertIn("the Gate Runner runs the start gate G1", stages)
        self.assertNotIn("so the SQL Analyst can run independent SELECT-only queries", handoff)
        self.assertNotIn("A reviewer or builder commits and seals its first answer", stages)
        for role in ("docs/roles/second-designer.md", "docs/roles/risk-reviewer.md"):
            self.assertNotIn("Seal your first independent answer", self.read(role))
        gr = self.read("docs/roles/gate-runner.md")
        self.assertIn("Seal each captured reply", gr)


if __name__ == "__main__":
    unittest.main()
