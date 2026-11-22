"""Repair round 1 (2026-11-22) of the workflow changes: each test reproduces a false PASS an outside review found on 3faeb07.

1. G3S recorded PASS for snapshot A while the connector had actually opened snapshot B.
2. G0 accepted a Stage 5 review packet whose report was edited after G5P (the G5P record bound only the ledger).
3. The decision-flip fixture claimed an exact-threshold case (a total of exactly 10) that its data never contained.
"""
from __future__ import annotations

import glob
import os
import shutil
import tempfile
import unittest

from gates import sql_select_only as S
from gates import stage_gates as SG
from gates.run import run_gate
from gates.tests import fixture_project as F
from gates.tests import test_finish_gates as TFG
from gates.tests.test_sunday_changes import MANIFEST, make_g3s_project

failed = TFG.failed
OPENED = "connector opened the requested snapshot"


class Connector:
    """A simulated database connector: runs SELECT-only SQL on whichever frozen snapshot it actually opens and reports
    that snapshot's identity (id + sha256) with every result, as the connector contract requires."""

    def __init__(self, root, opens_rel, opens_id):
        self.path = os.path.join(root, opens_rel)
        self.opened = {"id": opens_id, "sha256": F.sha(self.path)}

    def __call__(self, sql, database):
        cols, rows, total = S.run_sqlite(self.path, sql)
        return cols, rows, total, dict(self.opened)


class SnapshotActuallyOpened(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grok-r1-snap-")
        make_g3s_project(self.tmp)                       # manifest requests snap-A
        F.make_snapshot(os.path.join(self.tmp, "data/snapshot_b.sqlite"))
        with open(os.path.join(self.tmp, "data/snapshot_b.sqlite"), "ab") as fh:
            fh.write(b"\0" * 16)                         # same tables and rows: every SQL check comes back clean on B
        m = F.rj(self.tmp, MANIFEST)
        m["database"]["engine"] = "external"
        F.wj(self.tmp, MANIFEST, m)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_connector_opening_b_while_a_requested_fails_g3s(self):
        rec = run_gate("G3S", self.tmp, executor=Connector(self.tmp, "data/snapshot_b.sqlite", "snap-B"))
        self.assertEqual(rec["result"], "FAIL", failed(rec))
        self.assertTrue(all(c["result"] == "PASS" for c in rec["checks"] if c["check"].endswith("zero violating rows")),
                        "all four SQL checks are clean on B; only the identity check may fail")
        self.assertTrue([c for c in failed(rec) if OPENED in c], failed(rec))

    def test_connector_same_id_other_bytes_fails_g3s(self):
        rec = run_gate("G3S", self.tmp, executor=Connector(self.tmp, "data/snapshot_b.sqlite", "snap-A"))
        self.assertTrue([c for c in failed(rec) if OPENED in c], failed(rec))

    def test_connector_without_identity_fails_g3s(self):
        def old_style(sql, database):
            return S.run_sqlite(os.path.join(self.tmp, "data/snapshot.sqlite"), sql)
        rec = run_gate("G3S", self.tmp, executor=old_style)
        self.assertEqual(rec["result"], "FAIL")
        self.assertTrue([c for c in failed(rec) if OPENED in c], failed(rec))

    def test_connector_opening_a_passes_and_records_identity(self):
        rec = run_gate("G3S", self.tmp, executor=Connector(self.tmp, "data/snapshot.sqlite", "snap-A"))
        self.assertEqual(rec["result"], "PASS", failed(rec))
        self.assertIn(f"keys: {OPENED}", [c["check"] for c in rec["checks"]])
        res = F.rj(self.tmp, rec["results_record"]["path"])["results"]
        self.assertTrue(all(r["opened_snapshot"]["id"] == "snap-A" for r in res))

    def test_builtin_sqlite_connector_reports_what_it_opened(self):
        m = F.rj(self.tmp, MANIFEST)
        m["database"]["engine"] = "sqlite"
        F.wj(self.tmp, MANIFEST, m)
        rec = run_gate("G3S", self.tmp)
        self.assertEqual(rec["result"], "PASS", failed(rec))
        self.assertIn(f"keys: {OPENED}", [c["check"] for c in rec["checks"]])


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build an R-certified project")
class RepairRound1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TFG.FinishGates.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        RepairRound1.n += 1
        d = os.path.join(self.tmp, f"r1_{RepairRound1.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    # ---------------------------------------------------------------- 2. precheck bound to the reports
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

    def test_g5p_records_every_deliverable(self):
        r = self.copy()
        rec = run_gate("G5P", r, ledger=SG.CLAIMS)
        got = {d["path"] for d in rec.get("deliverables", [])}
        self.assertEqual(got, set(F.DELIVERABLES))
        self.assertTrue(set(F.DELIVERABLES) <= {i["path"] for i in rec["inputs"]})

    def test_g0_rejects_report_edited_after_g5p(self):
        r = self.copy()
        hist = self._precheck_hist(r)
        F.wt(r, "stage5-decision.md", F.DELIVERABLES["stage5-decision.md"] + "Added after the precheck.\n")
        g0 = self._s5_packet(r, [SG.CLAIMS, *F.DELIVERABLES, hist])
        self.assertEqual(g0["result"], "FAIL")
        self.assertIn(self.EXACT, failed(g0))

    def test_g0_rejects_precheck_record_without_deliverables(self):
        r = self.copy()
        hist = self._precheck_hist(r)
        rec = F.rj(r, hist)
        rec.pop("deliverables", None)
        F.wj(r, "artifacts/gates/history/G5P-hand-trimmed.json", rec)
        g0 = self._s5_packet(r, [SG.CLAIMS, *F.DELIVERABLES, "artifacts/gates/history/G5P-hand-trimmed.json"])
        self.assertIn(self.EXACT, failed(g0))

    def test_g0_accepts_unchanged_reports(self):
        r = self.copy()
        hist = self._precheck_hist(r)
        g0 = self._s5_packet(r, [SG.CLAIMS, *F.DELIVERABLES, hist])
        self.assertEqual(g0["result"], "PASS", failed(g0))

    def test_g5_and_g6_refuse_a_report_changed_after_g5(self):
        r = self.copy()
        F.wt(r, "stage5-decision.md", F.DELIVERABLES["stage5-decision.md"] + "Added after G5.\n")
        rec6 = run_gate("G6", r)
        self.assertEqual(rec6["result"], "FAIL")
        for name in ("G5 PASS and current", "Owner approved the exact finish package", "R certificate deliverables unchanged"):
            self.assertIn(name, failed(rec6))
        self.assertEqual(run_gate("G5", r)["result"], "FAIL")

    # ---------------------------------------------------------------- 3. exact-threshold fixture
    def test_fixture_has_customer_exactly_at_threshold_and_holds(self):
        rows = [l.split(",") for l in F.CSV_SUMMARY.strip().splitlines()]
        head, body = rows[0], rows[1:]
        self.assertIn("decision", head)
        at = [dict(zip(head, b)) for b in body if b[head.index("total")] == "10"]
        self.assertEqual(len(at), 1, "one customer totals exactly the threshold of 10")
        self.assertEqual(at[0]["decision"], "hold", "TH1 is 'above 10', so exactly 10 is not expanded")
        expect = {b[0]: ("expand" if float(b[head.index("total")]) > 10 else "hold") for b in body}
        self.assertEqual(expect, {b[0]: b[head.index("decision")] for b in body})

    def test_greater_or_equal_bug_fails_g4a_and_g4b(self):
        r = self.copy()
        bug = F.CSV_SUMMARY.replace("c3,10,1,hold", "c3,10,1,expand")   # an R-B that used >= 10 instead of > 10
        self.assertNotEqual(bug, F.CSV_SUMMARY)
        F.add_stage4_outputs(r, {"rb": bug, "rb_F1": bug})
        rec_a = run_gate("G4a", r)
        self.assertIn("Fixture F1 rb matches worked answer", failed(rec_a))
        self.assertIn("Fixture F1 ra matches worked answer", [c["check"] for c in rec_a["checks"] if c["result"] == "PASS"])
        rec_b = run_gate("G4b", r)
        self.assertIn("summary: ra vs rb exact match", failed(rec_b))

    def test_r_a_and_r_b_agree_with_the_worked_answer(self):
        for g in ("G4a", "G4b"):
            self.assertEqual(self.records[g]["result"], "PASS", failed(self.records[g]))



# ---------------------------------------------------------------- 4. operational roles in the docs
class OperationalRoleDocs(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(F.PKG, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_operational_roles_documented_consistently(self):
        for f in ("coordinator.md", "gate-runner.md", "database-connector.md"):
            self.assertTrue(os.path.isfile(os.path.join(F.PKG, "docs/roles", f)), f)
        readme = self.read("README.md")
        for row in ("| Coordinator |", "| Gate Runner |", "| Database Connector |"):
            self.assertIn(row, readme)
        parent_row = [l for l in readme.splitlines() if l.startswith("| Parent |")][0]
        self.assertNotIn("runs gates", parent_row)
        self.assertNotIn("seals work", parent_row)
        self.assertIn("Does not run gates", parent_row)
        gates_md = self.read("docs/gates.md")
        run_by = [l.split("|")[4].strip() for l in gates_md.splitlines() if l.startswith("| G") and l.count("|") >= 7]
        self.assertTrue(run_by and all(r.startswith("Gate Runner") for r in run_by), run_by)
        self.assertIn("Database Connector", [l for l in gates_md.splitlines() if l.startswith("| G3S |")][0])
        handoff, stages = self.read("docs/handoff.md"), self.read("docs/stages.md")
        self.assertNotIn("The parent runs those gates", handoff)
        self.assertNotIn("After the parent runs G3S", handoff)
        self.assertIn("Gate Runner records the chat", handoff)
        self.assertIn("Gate Runner captures and seals", stages)
        self.assertIn("Coordinator advances only on a PASS for that attempt", stages)
        self.assertNotIn("the parent runs them", stages)
        # the role table names roles only: the Parent row's second cell is the role, not a bot
        self.assertEqual(parent_row.split("|")[2].strip(), "Orchestrator")


if __name__ == "__main__":
    unittest.main()
