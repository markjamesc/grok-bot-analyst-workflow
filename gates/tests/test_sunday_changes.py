"""Regression tests for the 2026-11-22 workflow changes (owner-approved "four known fixes" and stage refinements).

Known fix 1 (attempt ids): a failed or crashed retry can never leave an older PASS current, and the coordinating role
advances only on a PASS for the attempt it requested (gates/attempt.py, gates/run.py).
Known fix 2 (snapshot binding): a G3S PASS is bound to the exact frozen snapshot (id + sha256); Stage 4 on another
snapshot needs a fresh G3S on it (stage_gates.snapshot_binding_checks, inside G4a/G4b).
Known fix 3 (precheck by record): a Stage 5 review packet must carry a runner-written G5P PASS record for the exact claims
ledger in the packet; a file named "precheck" no longer passes (packet.precheck_checks).
Known fix 4 (finish order): the stage guide table, the gate README and the parent role state the same finish order.
Stage 3 decision-flip fixtures and Stage 4 rounding-only tolerances are checked at the design lock (G3).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import tempfile
import unittest

from gates import attempt as A
from gates import packet as PK
from gates import stage_gates as SG
from gates.common import Gate, gate_record_current
from gates.run import main as run_main
from gates.run import run_gate
from gates.tests import fixture_project as F
from gates.tests import test_finish_gates as TFG

failed = TFG.failed
MANIFEST = "artifacts/stage3/source_gates/manifest.json"


def make_g3s_project(root, snap_rel="data/snapshot.sqlite", snap_id="snap-A", dup_order=False):
    """A project with just the G3S inputs (no R needed): a frozen sqlite snapshot and the four source gates."""
    F.make_snapshot(os.path.join(root, snap_rel), dup_order=dup_order)
    gates = [{"id": n, "check": k, "sql": F.wt(root, f"sql/g3s/{n}.sql", q + "\n")} for n, (k, q) in F.SQL.items()]
    F.wj(root, MANIFEST, {"database": {"engine": "sqlite", "snapshot": dict(F.ref(root, snap_rel), id=snap_id)}, "gates": gates})


def point_manifest(root, snap_rel, snap_id):
    m = F.rj(root, MANIFEST)
    m["database"]["snapshot"] = dict(F.ref(root, snap_rel), id=snap_id)
    F.wj(root, MANIFEST, m)


# ------------------------------------------------------------------------------------------------ known fix 1
class Attempts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grok-attempts-")
        make_g3s_project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pass_for_requested_attempt_advances(self):
        rec = run_gate("G3S", self.tmp, attempt_id="G3S-try-1")
        self.assertEqual(rec["result"], "PASS", failed(rec))
        self.assertEqual(rec["attempt_id"], "G3S-try-1")
        self.assertEqual(F.rj(self.tmp, "artifacts/gates/attempts/G3S-try-1.json")["result"], "PASS")
        ok, det = A.attempt_check(self.tmp, "G3S", "G3S-try-1")
        self.assertTrue(ok, det)

    def test_generated_attempt_id_is_recorded(self):
        rec = run_gate("G3S", self.tmp)
        self.assertTrue(rec["attempt_id"].startswith("G3S-"))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, rec["attempt_path"])))

    def test_failed_retry_does_not_leave_old_pass_current(self):
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="try-1")["result"], "PASS")
        F.wt(self.tmp, "sql/g3s/keys.sql", "DELETE FROM orders\n")
        m = F.rj(self.tmp, MANIFEST)
        m["gates"][1]["sql"] = F.ref(self.tmp, "sql/g3s/keys.sql")
        F.wj(self.tmp, MANIFEST, m)
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="try-2")["result"], "FAIL")
        ok2, det2 = A.attempt_check(self.tmp, "G3S", "try-2")
        self.assertFalse(ok2)
        self.assertIn("FAIL", det2)
        ok1, det1 = A.attempt_check(self.tmp, "G3S", "try-1")
        self.assertFalse(ok1, "the earlier PASS must not stand in for the retry the coordinator requested")
        self.assertIn("not the requested try-1", det1)

    def test_tool_error_retry_is_recorded_and_replaces_old_pass(self):
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="try-1")["result"], "PASS")
        m = F.rj(self.tmp, MANIFEST)
        m["database"]["engine"] = "external"
        F.wj(self.tmp, MANIFEST, m)
        rec = run_gate("G3S", self.tmp, attempt_id="try-2")
        self.assertEqual(rec["result"], "TOOL_ERROR")
        self.assertEqual(F.rj(self.tmp, "artifacts/gates/attempts/try-2.json")["result"], "TOOL_ERROR")
        self.assertEqual(F.rj(self.tmp, "artifacts/gates/G3S.json")["result"], "TOOL_ERROR")
        self.assertFalse(gate_record_current(self.tmp, "G3S")[0], "a TOOL_ERROR retry must leave no PASS current")
        self.assertFalse(A.attempt_check(self.tmp, "G3S", "try-2")[0])
        self.assertFalse(A.attempt_check(self.tmp, "G3S", "try-1")[0])

    def test_unrun_or_unrecorded_attempt_never_advances(self):
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="try-1")["result"], "PASS")
        self.assertFalse(A.attempt_check(self.tmp, "G3S", "try-9")[0])
        rec = run_gate("G3S", self.tmp, record=False, attempt_id="try-3")
        self.assertEqual(rec["result"], "PASS")
        self.assertFalse(A.attempt_check(self.tmp, "G3S", "try-3")[0], "an unrecorded run is not an attempt outcome")

    def test_attempt_for_another_gate_never_advances(self):
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="try-1")["result"], "PASS")
        ok, det = A.attempt_check(self.tmp, "G3K", "try-1")
        self.assertFalse(ok)
        self.assertIn("not G3K", det)

    def test_reused_attempt_id_refused(self):
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="try-1")["result"], "PASS")
        rec = run_gate("G3S", self.tmp, attempt_id="try-1")
        self.assertEqual(rec["result"], "TOOL_ERROR")
        self.assertIn("already used", rec["error"])
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="bad id/../x")["result"], "TOOL_ERROR")

    def test_inputs_changed_after_pass(self):
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="try-1")["result"], "PASS")
        F.make_snapshot(os.path.join(self.tmp, "data/snapshot.sqlite"), dup_order=True)
        self.assertFalse(A.attempt_check(self.tmp, "G3S", "try-1")[0])

    def test_edited_current_record_never_advances(self):
        self.assertEqual(run_gate("G3S", self.tmp, attempt_id="try-1")["result"], "PASS")
        rec = F.rj(self.tmp, "artifacts/gates/G3S.json")
        rec["note"] = "edited by hand"
        F.wj(self.tmp, "artifacts/gates/G3S.json", rec)
        ok, det = A.attempt_check(self.tmp, "G3S", "try-1")
        self.assertFalse(ok)
        self.assertIn("changed since", det)

    def test_cli_exit_codes(self):
        self.assertEqual(run_main(["G3S", self.tmp, "--attempt=cli-1"]), 0)
        self.assertEqual(A.main(["G3S", self.tmp, "cli-1"]), 0)
        self.assertEqual(A.main(["G3S", self.tmp, "cli-2"]), 1)
        self.assertEqual(A.main(["G3S", self.tmp]), 2)


# ------------------------------------------------------------------------------------------------ known fix 2
class SnapshotBinding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grok-snap-")
        make_g3s_project(self.tmp)
        F.make_snapshot(os.path.join(self.tmp, "data/snapshot_b.sqlite"), dup_order=False)
        with open(os.path.join(self.tmp, "data/snapshot_b.sqlite"), "ab") as fh:
            fh.write(b"\0" * 16)  # same tables, different bytes: a different frozen snapshot

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bind(self, snap_rel, snap_id):
        g = Gate("G4a", self.tmp)
        SG.snapshot_binding_checks(g, self.tmp, {"snapshot": dict(F.ref(self.tmp, snap_rel), id=snap_id)})
        return g.checks[-1]

    def test_g3s_records_the_snapshot_it_checked(self):
        rec = run_gate("G3S", self.tmp)
        self.assertEqual(rec["result"], "PASS", failed(rec))
        self.assertEqual(rec["snapshot"]["id"], "snap-A")
        self.assertEqual(rec["snapshot"]["sha256"], F.sha(os.path.join(self.tmp, "data/snapshot.sqlite")))

    def test_g3s_fails_without_snapshot_id(self):
        m = F.rj(self.tmp, MANIFEST)
        del m["database"]["snapshot"]["id"]
        F.wj(self.tmp, MANIFEST, m)
        rec = run_gate("G3S", self.tmp)
        self.assertEqual(rec["result"], "FAIL")
        self.assertIn("Frozen snapshot identified", failed(rec))

    def test_same_snapshot_binds(self):
        run_gate("G3S", self.tmp)
        self.assertEqual(self.bind("data/snapshot.sqlite", "snap-A")["result"], "PASS")

    def test_switch_to_snapshot_b_needs_fresh_check(self):
        run_gate("G3S", self.tmp)
        c = self.bind("data/snapshot_b.sqlite", "snap-B")
        self.assertEqual(c["result"], "FAIL", "an old PASS on snapshot A must not cover snapshot B")
        self.assertIn("run G3S on this snapshot", c["detail"])
        point_manifest(self.tmp, "data/snapshot_b.sqlite", "snap-B")
        self.assertEqual(run_gate("G3S", self.tmp)["result"], "PASS")
        self.assertEqual(self.bind("data/snapshot_b.sqlite", "snap-B")["result"], "PASS")
        self.assertEqual(self.bind("data/snapshot.sqlite", "snap-A")["result"], "FAIL", "now A is the unchecked one")

    def test_same_id_different_bytes_fails(self):
        run_gate("G3S", self.tmp)
        self.assertEqual(self.bind("data/snapshot_b.sqlite", "snap-A")["result"], "FAIL")

    def test_missing_stage4_snapshot_fails(self):
        run_gate("G3S", self.tmp)
        g = Gate("G4a", self.tmp)
        SG.snapshot_binding_checks(g, self.tmp, {})
        self.assertEqual(g.checks[-1]["result"], "FAIL")

    def test_failed_g3s_binds_nothing(self):
        run_gate("G3S", self.tmp)
        F.make_snapshot(os.path.join(self.tmp, "data/snapshot.sqlite"), dup_order=True)
        point_manifest(self.tmp, "data/snapshot.sqlite", "snap-A")
        self.assertEqual(run_gate("G3S", self.tmp)["result"], "FAIL")
        self.assertEqual(self.bind("data/snapshot.sqlite", "snap-A")["result"], "FAIL")


# ------------------------------------------------------------------------------------------------ known fix 4
class FinishOrderDocs(unittest.TestCase):
    ORDER = "owner approves the exact finish package -> R `complete finish` -> G5 -> R `finalize` -> G6"

    def read(self, rel):
        with open(os.path.join(F.PKG, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_same_finish_order_everywhere(self):
        for rel in ("docs/stages.md", "gates/README.md", "docs/roles/parent.md", "docs/gates.md"):
            self.assertIn(self.ORDER, self.read(rel), rel)

    def test_old_orders_removed(self):
        self.assertNotIn("(after G5, before G6)", self.read("docs/stages.md"))
        self.assertNotIn("G4d → G5 → owner approval", self.read("gates/README.md"))
        self.assertNotIn("run G5 (claims) on the sealed claims ledger and deliverables, then present", self.read("docs/roles/parent.md"))


# ------------------------------------------------------------------------------------------------ R-certified project
@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build an R-certified project")
class SundayChanges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TFG.FinishGates.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        SundayChanges.n += 1
        d = os.path.join(self.tmp, f"sun_{SundayChanges.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    def assertFailsOn(self, gate, root, check_substr):
        rec = run_gate(gate, root)
        self.assertEqual(rec["result"], "FAIL", f"{gate} should FAIL; checks={failed(rec)} error={rec.get('error')}")
        self.assertTrue([c for c in failed(rec) if check_substr in c], f"{gate}: no failing check {check_substr!r}: {failed(rec)}")
        return rec

    def edit_design(self, r, fn):
        d = F.rj(r, SG.GROK_DESIGN)
        fn(d)
        F.wj(r, SG.GROK_DESIGN, d)

    # known fix 1 on the full chain: a TOOL_ERROR retry of a lower gate blocks the close and every later gate
    def test_tool_error_retry_blocks_close_and_later_gates(self):
        from gates import close as C
        r = self.copy()
        self.assertEqual(C.close_check(r, "G4d")["result"], "PASS")
        m = F.rj(r, MANIFEST)
        m["database"]["engine"] = "external"
        F.wj(r, MANIFEST, m)
        self.assertEqual(run_gate("G3S", r, attempt_id="g3s-retry")["result"], "TOOL_ERROR")
        self.assertEqual(C.close_check(r, "G4d")["result"], "FAIL")
        self.assertFailsOn("G4d", r, "G3S PASS and current")

    # known fix 2 end to end
    def test_g4a_g4b_fail_when_stage4_ran_on_another_snapshot(self):
        r = self.copy()
        F.make_snapshot(os.path.join(r, "data/snapshot_b.sqlite"))
        with open(os.path.join(r, "data/snapshot_b.sqlite"), "ab") as fh:
            fh.write(b"\0" * 16)
        o = F.rj(r, SG.OUTPUTS)
        o["snapshot"] = dict(F.ref(r, "data/snapshot_b.sqlite"), id="snap-B")
        F.wj(r, SG.OUTPUTS, o)
        self.assertFailsOn("G4a", r, "Stage 4 snapshot is the one G3S checked")
        self.assertFailsOn("G4b", r, "Stage 4 snapshot is the one G3S checked")

    def test_g4a_good_path_records_g3s_binding(self):
        rec = self.records["G4a"]
        self.assertIn("Stage 4 snapshot is the one G3S checked", [c["check"] for c in rec["checks"]])
        self.assertIn("artifacts/gates/G3S.json", [i["path"] for i in rec["inputs"]])

    # known fix 3
    def _s5_packet(self, r, inputs):
        body = F.packet_text(r, "CASE-5-01", role="Risk Reviewer", stage="5", inputs=inputs,
                             expected="artifacts/stage5/reviews/risk_reviewer_numbers.json")
        F.add_packets(r, [("CASE-5-01", body, "answered", F.reply_text("CASE-5-01", ("artifacts/stage5/reviews/risk_reviewer_numbers.json",)))])
        return run_gate("G0", r)

    def _precheck(self, r, ledger=SG.CLAIMS):
        rec = run_gate("G5P", r, ledger=ledger)
        hist = sorted(glob.glob(os.path.join(r, "artifacts/gates/history/G5P-*.json")), key=os.path.getmtime)
        for h in hist:
            if F.sha(h) == F.sha(os.path.join(r, "artifacts/gates/G5P.json")):
                return rec, os.path.relpath(h, r)
        raise AssertionError("no history copy of the G5P record")

    PRESENT = "Packet CASE-5-01 Stage 5 review carries a precheck log"
    EXACT = "Packet CASE-5-01 Stage 5 precheck PASS for the exact ledger"

    def test_g5p_pass_for_exact_ledger_accepted(self):
        r = self.copy()
        rec, hist = self._precheck(r)
        self.assertEqual(rec["result"], "PASS", failed(rec))
        self.assertEqual(rec["ledger"]["path"], SG.CLAIMS)
        g0 = self._s5_packet(r, [SG.CLAIMS, "stage5-evidence.md", hist])
        self.assertNotIn(self.PRESENT, failed(g0))
        self.assertNotIn(self.EXACT, failed(g0))
        self.assertEqual(g0["result"], "PASS", failed(g0))

    def test_filename_alone_is_not_a_precheck(self):
        r = self.copy()
        F.wt(r, "artifacts/stage5/precheck_CASE-5-01.txt", "G5P PASS\n")
        g0 = self._s5_packet(r, [SG.CLAIMS, "stage5-evidence.md", "artifacts/stage5/precheck_CASE-5-01.txt"])
        self.assertEqual(g0["result"], "FAIL")
        self.assertIn(self.PRESENT, failed(g0))
        self.assertIn(self.EXACT, failed(g0))

    def test_no_precheck_at_all(self):
        r = self.copy()
        g0 = self._s5_packet(r, [SG.CLAIMS, "stage5-evidence.md"])
        self.assertIn(self.PRESENT, failed(g0))

    def test_precheck_of_another_ledger_rejected(self):
        r = self.copy()
        c = F.rj(r, SG.CLAIMS)
        c["note"] = "a different version of the ledger"
        F.wj(r, "artifacts/stage5/claims_v02.json", c)
        rec, hist = self._precheck(r, "artifacts/stage5/claims_v02.json")
        self.assertEqual(rec["result"], "PASS", failed(rec))
        g0 = self._s5_packet(r, [SG.CLAIMS, "stage5-evidence.md", hist])
        self.assertNotIn(self.PRESENT, failed(g0))
        self.assertIn(self.EXACT, failed(g0))

    def test_ledger_changed_after_precheck_rejected(self):
        r = self.copy()
        _, hist = self._precheck(r)
        c = F.rj(r, SG.CLAIMS)
        c["note"] = "edited after the precheck"
        F.wj(r, SG.CLAIMS, c)
        g0 = self._s5_packet(r, [SG.CLAIMS, "stage5-evidence.md", hist])
        self.assertIn(self.EXACT, failed(g0))

    def test_failed_precheck_rejected(self):
        r = self.copy()
        c = F.rj(r, SG.CLAIMS)
        c["claims"][0]["quote"] = "Customer c1 spent 99.9 over 2 orders."
        F.wj(r, "artifacts/stage5/claims_v03.json", c)
        rec, hist = self._precheck(r, "artifacts/stage5/claims_v03.json")
        self.assertEqual(rec["result"], "FAIL")
        g0 = self._s5_packet(r, ["artifacts/stage5/claims_v03.json", "stage5-evidence.md", hist])
        self.assertIn(self.EXACT, failed(g0))

    def test_hand_written_record_rejected(self):
        r = self.copy()
        F.wj(r, "artifacts/stage5/precheck_fake.json", {"gate": "G5P", "result": "PASS", "ledger": F.ref(r, SG.CLAIMS),
                                                        "inputs": [F.ref(r, SG.CLAIMS)]})
        g0 = self._s5_packet(r, [SG.CLAIMS, "stage5-evidence.md", "artifacts/stage5/precheck_fake.json"])
        self.assertNotIn(self.PRESENT, failed(g0))
        self.assertIn(self.EXACT, failed(g0))

    # Stage 3: decision-flip fixtures
    def test_g3_requires_decision_flip_fixtures(self):
        r = self.copy()
        self.edit_design(r, lambda d: d.pop("decision_flip_fixtures"))
        self.assertFailsOn("G3", r, "Decision-flip fixtures declared")

    def test_g3_decision_flip_kind_missing_or_unknown_fixture(self):
        r = self.copy()
        self.edit_design(r, lambda d: d.update(decision_flip_fixtures=d["decision_flip_fixtures"][:3]))
        self.assertFailsOn("G3", r, "Decision-flip fixtures declared")
        r = self.copy()
        self.edit_design(r, lambda d: d["decision_flip_fixtures"][0].update(fixture="F9"))
        self.assertFailsOn("G3", r, "Decision-flip fixtures declared")
        r = self.copy()
        self.edit_design(r, lambda d: d["decision_flip_fixtures"][2].update(not_applicable="TBD"))
        self.assertFailsOn("G3", r, "Decision-flip fixtures declared")

    def test_g3_good_path_has_decision_flip_and_rounding_checks(self):
        names = [c["check"] for c in self.records["G3"]["checks"]]
        self.assertIn("Decision-flip fixtures declared", names)
        self.assertIn("Tolerances only on declared rounding fields", names)

    # Stage 4: tolerances only on declared rounding fields
    def test_g3_tolerance_without_rounding_reason_fails(self):
        r = self.copy()
        self.edit_design(r, lambda d: d["reconciliation"]["outputs"][0].update(
            tolerance={"fields": ["total"], "absolute_tolerance": 1e-6, "relative_tolerance": 0}))
        self.assertFailsOn("G3", r, "Tolerances only on declared rounding fields")

    def test_g3_tolerance_with_rounding_reason_accepted(self):
        r = self.copy()
        self.edit_design(r, lambda d: d["reconciliation"]["outputs"][0].update(
            tolerance={"fields": ["total"], "absolute_tolerance": 1e-6, "relative_tolerance": 0,
                       "rounding_reason": "R and SQL round the summed amount at different steps"}))
        rec = run_gate("G3", r)
        self.assertNotIn("Tolerances only on declared rounding fields", failed(rec))

    def test_zero_width_tolerance_needs_no_reason(self):
        g = Gate("G3", self.base)
        SG.rounding_tolerance_checks(g, {"reconciliation": {"outputs": [{"name": "s", "tolerance": {"fields": ["x"]}}]}})
        self.assertEqual(g.checks[-1]["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
