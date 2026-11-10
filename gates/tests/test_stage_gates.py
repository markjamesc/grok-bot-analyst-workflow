"""End-to-end and fault-injection tests for G1, G2, G2F, G3S, G3K, G3, G4a, G4b, G4c, G4d.

A good project (R-valid receipts built by the R repo's own test helpers + Grok gate inputs) must PASS every gate in order.
Each fault-injection test copies the good project, plants one defect, and asserts the gate FAILs on the named check.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from gates import repair
from gates import sql_select_only as S
from gates.run import run_gate
from gates.tests import fixture_project as F

ORDER = ["G1", "G2", "G2F", "G3S", "G3K", "G3", "G4a", "G4b", "G4c", "G4d"]


def failed(rec):
    return [c["check"] for c in rec["checks"] if c["result"] != "PASS"]


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build R-valid receipts")
class StageGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="grok-gates-")
        cls.base = os.path.join(cls.tmp, "base")
        cls.pin = os.path.join(cls.tmp, "pin")
        F.build_r_project(cls.base, last=4)
        F.add_stage2(cls.base, cls.pin)
        F.add_feasibility(cls.base)
        F.add_stage3(cls.base)
        F.add_stage4_outputs(cls.base)
        cls.records = {}
        for g in ORDER:
            if g == "G4c":
                F.add_g4c_review(cls.base)
            rec = run_gate(g, cls.base)
            cls.records[g] = rec
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        StageGates.n += 1
        d = os.path.join(self.tmp, f"case{StageGates.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    def assertFailsOn(self, gate, root, check_substr, **kw):
        rec = run_gate(gate, root, **kw)
        self.assertEqual(rec["result"], "FAIL", f"{gate} should FAIL; checks={failed(rec)} error={rec.get('error')}")
        hit = [c for c in failed(rec) if check_substr in c]
        self.assertTrue(hit, f"{gate}: expected a failing check containing {check_substr!r}; failing: {failed(rec)}")
        return rec

    # ---------------------------------------------------------------- good path
    def test_00_good_project_passes_every_gate_in_order(self):
        for g in ORDER:
            rec = self.records[g]
            self.assertEqual(rec["result"], "PASS", f"{g}: {failed(rec)} {rec.get('error', '')}")
            self.assertTrue(os.path.exists(os.path.join(self.base, "artifacts/gates", f"{g}.json")))
        # G1/G2/G3/G4d carry the ported R stage checks; G4d carries the full ported R Workflow Gate.
        for g in ("G1", "G2", "G3", "G4d"):
            self.assertTrue(any(c["check"].startswith("R: ") for c in self.records[g]["checks"]), g)
        self.assertTrue(any(c["check"].startswith("Workflow Gate: ") for c in self.records["G4d"]["checks"]))

    # ---------------------------------------------------------------- G1
    def test_g1_missing_limits(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage1_decision.json"); d.pop("limits"); F.wj(r, "artifacts/stage1_decision.json", d)
        self.assertFailsOn("G1", r, "Limits stated")

    def test_g1_single_action(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage1_decision.json"); d["actions_per_result"] = d["actions_per_result"][:1]
        F.wj(r, "artifacts/stage1_decision.json", d)
        self.assertFailsOn("G1", r, "Actions per result")

    def test_g1_workflow_pin_stale(self):
        r = self.copy()
        pin = F.rj(r, "artifacts/workflow_pin.json")
        newbase = os.path.join(self.tmp, f"pin{StageGates.n}")
        shutil.copytree(self.pin, newbase)
        with open(os.path.join(newbase, "docs/workflow.md"), "a") as fh:
            fh.write("edited after pin\n")
        pin["base"] = newbase
        F.wj(r, "artifacts/workflow_pin.json", pin)
        self.assertFailsOn("G1", r, "Workflow pinned")

    def test_g1_r_check_unresolved_issues(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage1_decision.json"); d["unresolved_issues"] = 1; F.wj(r, "artifacts/stage1_decision.json", d)
        self.assertFailsOn("G1", r, "R: Stage 1 unresolved issues")

    def test_g1_r_check_missing_receipt(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/stage1_decision.json"))
        self.assertFailsOn("G1", r, "R: Required receipt exists and parses")

    # ---------------------------------------------------------------- G2
    def test_g2_two_questions(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage2_framing.json"); d["questions"] = ["q1", "q2"]; F.wj(r, "artifacts/stage2_framing.json", d)
        self.assertFailsOn("G2", r, "One question")

    def test_g2_missing_threshold(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage2_framing.json"); d.pop("threshold"); F.wj(r, "artifacts/stage2_framing.json", d)
        self.assertFailsOn("G2", r, "Question threshold")

    def test_g2_review_of_stale_subject(self):
        r = self.copy()
        with open(os.path.join(r, "docs/stage2/FRAMING_RECORD.md"), "a") as fh:
            fh.write("changed after review\n")
        self.assertFailsOn("G2", r, "review coverage")

    def test_g2_open_must_fix(self):
        r = self.copy()
        F.review(r, "artifacts/stage2/reviews/risk_reviewer_framing_check.json", "risk_reviewer", ["docs/stage2/FRAMING_RECORD.md"],
                 [{"id": "M1", "class": "must_fix", "status": "open"}])
        self.assertFailsOn("G2", r, "no open must-fix")

    def test_g2_wrong_reviewer_role(self):
        r = self.copy()
        F.review(r, "artifacts/stage2/reviews/second_designer_critique.json", "risk_reviewer", ["docs/stage2/FRAMING_RECORD.md"])
        self.assertFailsOn("G2", r, "reviewer role")

    def test_g2_r_check_capacity_stance(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage2_framing.json"); d["capacity_stance"] = "maybe"; F.wj(r, "artifacts/stage2_framing.json", d)
        self.assertFailsOn("G2", r, "R: Capacity stance explicit")

    # ---------------------------------------------------------------- G2F
    def test_g2f_new_question(self):
        r = self.copy()
        f = F.rj(r, "artifacts/stage2f_feasibility.json")
        f["questions"].append(dict(f["questions"][0], question_id="question-2"))
        F.wj(r, "artifacts/stage2f_feasibility.json", f)
        F.review(r, "artifacts/stage2f/reviews/risk_reviewer_feasibility.json", "risk_reviewer", ["artifacts/stage2f_feasibility.json"])
        self.assertFailsOn("G2F", r, "No new or missing questions")

    def test_g2f_values_leak(self):
        r = self.copy()
        F.add_feasibility(r, extra_q={"structure": [{"table": "orders", "column": "amount", "values": [10, 5.5]}]})
        self.assertFailsOn("G2F", r, "structure entries")
        F.add_feasibility(r, extra_q={"samples": [1, 2]})
        self.assertFailsOn("G2F", r, "no values")

    def test_g2f_answer_key_mention(self):
        r = self.copy()
        F.add_feasibility(r, extra_q={"reason": "Matches the answer key layout"})
        self.assertFailsOn("G2F", r, "no answer key")

    def test_g2f_partly_needs_owner_decision(self):
        r = self.copy()
        F.add_feasibility(r, feas="partly")
        self.assertFailsOn("G2F", r, "Owner decision on partly/no")
        f = F.rj(r, "artifacts/stage2f_feasibility.json")
        f["owner_decision"] = {"decision": "proceed", "approval_text": "Proceed with partial coverage", "approval_timestamp": "2026-11-09T10:00:00Z"}
        F.wj(r, "artifacts/stage2f_feasibility.json", f)
        F.review(r, "artifacts/stage2f/reviews/risk_reviewer_feasibility.json", "risk_reviewer", ["artifacts/stage2f_feasibility.json"])
        self.assertEqual(run_gate("G2F", r)["result"], "PASS")

    def test_g2f_requires_current_g2(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/gates/G2.json"))
        self.assertFailsOn("G2F", r, "G2 PASS and current")

    def test_g2f_review_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/stage2f/reviews/risk_reviewer_feasibility.json"))
        self.assertFailsOn("G2F", r, "Risk Reviewer feasibility review coverage")

    # ---------------------------------------------------------------- G3S
    def test_g3s_write_statement_refused(self):
        r = self.copy()
        F.add_stage3(r, {"keys": "DELETE FROM orders"})
        self.assertFailsOn("G3S", r, "keys: SELECT-only")

    def test_g3s_stacked_statement_refused(self):
        r = self.copy()
        F.add_stage3(r, {"joins": "SELECT 1 WHERE 0; DROP TABLE orders"})
        self.assertFailsOn("G3S", r, "joins: SELECT-only")

    def test_g3s_sql_edited_after_manifest(self):
        r = self.copy()
        with open(os.path.join(r, "sql/g3s/counts.sql"), "a") as fh:
            fh.write("-- edited\n")
        self.assertFailsOn("G3S", r, "counts: SQL file current")

    def test_g3s_violation_rows(self):
        r = self.copy()
        F.make_snapshot(os.path.join(r, "data/snapshot.sqlite"), dup_order=True)
        m = F.rj(r, "artifacts/stage3/source_gates/manifest.json")
        m["database"]["snapshot"] = F.ref(r, "data/snapshot.sqlite")
        F.wj(r, "artifacts/stage3/source_gates/manifest.json", m)
        rec = self.assertFailsOn("G3S", r, "keys: zero violating rows")
        self.assertIn("completeness: zero violating rows", failed(rec))

    def test_g3s_snapshot_not_frozen(self):
        r = self.copy()
        con = sqlite3.connect(os.path.join(r, "data/snapshot.sqlite"))
        con.execute("INSERT INTO customers VALUES ('c3')"); con.commit(); con.close()
        self.assertFailsOn("G3S", r, "Frozen snapshot pinned")

    def test_g3s_category_missing(self):
        r = self.copy()
        m = F.rj(r, "artifacts/stage3/source_gates/manifest.json")
        m["gates"] = [g for g in m["gates"] if g["check"] != "joins"]
        F.wj(r, "artifacts/stage3/source_gates/manifest.json", m)
        self.assertFailsOn("G3S", r, "Coverage")

    def test_g3s_external_engine_without_executor_is_tool_error(self):
        r = self.copy()
        m = F.rj(r, "artifacts/stage3/source_gates/manifest.json")
        m["database"] = {"engine": "external"}
        F.wj(r, "artifacts/stage3/source_gates/manifest.json", m)
        self.assertEqual(run_gate("G3S", r)["result"], "TOOL_ERROR")

    def test_g3s_authorizer_blocks_writes_even_without_lint(self):
        r = self.copy()
        db = os.path.join(r, "data/snapshot.sqlite")
        for q in ("DELETE FROM orders", "CREATE TABLE x(a)", "ATTACH DATABASE ':memory:' AS m", "PRAGMA writable_schema=1"):
            with self.assertRaises(sqlite3.DatabaseError, msg=q):
                S.run_sqlite(db, q)
        self.assertEqual(S.run_sqlite(db, "SELECT COUNT(*) FROM orders")[1], [[3]])

    # ---------------------------------------------------------------- G3K + repair cap
    def test_g3k_duplicate_key(self):
        r = self.copy()
        F.wt(r, "data/orders.csv", F.CSV_ORDERS + "3,c2,7\n")
        d = F.rj(r, "artifacts/stage3_grok_design.json")
        d["early_checks"]["keys"][0]["table"] = F.ref(r, "data/orders.csv")
        F.wj(r, "artifacts/stage3_grok_design.json", d)
        self.assertFailsOn("G3K", r, "Key orders_pk unique")

    def test_g3k_count_mismatch(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage3_grok_design.json"); d["early_checks"]["counts"][0]["expected_rows"] = 4
        F.wj(r, "artifacts/stage3_grok_design.json", d)
        self.assertFailsOn("G3K", r, "Count orders_n reconciles")

    def test_g3k_blank_key(self):
        r = self.copy()
        F.wt(r, "data/orders.csv", "id,customer_id,amount\n1,c1,10\n,c1,5.5\n3,c2,7\n")
        d = F.rj(r, "artifacts/stage3_grok_design.json")
        d["early_checks"]["keys"][0]["table"] = F.ref(r, "data/orders.csv")
        d["early_checks"]["counts"][0]["table"] = F.ref(r, "data/orders.csv")
        F.wj(r, "artifacts/stage3_grok_design.json", d)
        self.assertFailsOn("G3K", r, "Key orders_pk unique")

    def test_g3k_table_changed_after_design(self):
        r = self.copy()
        F.wt(r, "data/orders.csv", F.CSV_ORDERS.replace("5.5", "5.6"))
        self.assertFailsOn("G3K", r, "Key orders_pk unique")

    def test_repair_cap_escalates_after_three_and_author_change_does_not_reset(self):
        r = self.copy()
        repair.open_defect(r, "D1", "G3K", "duplicate key")
        self.assertEqual(repair.record_attempt(r, "D1", "lead", False), "OPEN")
        self.assertEqual(repair.record_attempt(r, "D1", "lead", False), "OPEN")
        self.assertEqual(repair.record_attempt(r, "D1", "second_designer", False), "ESCALATED")
        with self.assertRaises(repair.RepairCapExceeded):
            repair.record_attempt(r, "D1", "sql_analyst", True)
        rec = self.assertFailsOn("G3K", r, "Repair cap not exceeded")
        self.assertEqual(rec.get("escalate"), ["D1"])

    def test_repair_resolved_before_cap_passes(self):
        r = self.copy()
        repair.open_defect(r, "D2", "G3K", "count")
        repair.record_attempt(r, "D2", "lead", False)
        self.assertFailsOn("G3K", r, "No open defects")
        self.assertEqual(repair.record_attempt(r, "D2", "lead", True), "RESOLVED")
        self.assertEqual(run_gate("G3K", r)["result"], "PASS")

    def test_repair_ledger_tampered_count(self):
        r = self.copy()
        repair.open_defect(r, "D3", "G3K", "x")
        led = F.rj(r, "artifacts/repairs.json")
        led["defects"]["D3"]["attempts"] = [{"n": i, "author": "a", "passed": False} for i in (1, 2, 3)]
        F.wj(r, "artifacts/repairs.json", led)
        self.assertFailsOn("G3K", r, "Repair count consistent with status")

    # ---------------------------------------------------------------- G3
    def test_g3_owner_approval_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/stage3_owner_approval.json"))
        self.assertFailsOn("G3", r, "Owner approved the exact design hash")

    def test_g3_design_changed_after_approval(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage3_grok_design.json"); d["note"] = "late edit"; F.wj(r, "artifacts/stage3_grok_design.json", d)
        self.assertFailsOn("G3", r, "Owner approved the exact design hash")

    def test_g3_placeholder_approval(self):
        r = self.copy()
        F.approve_design(r, text="PENDING owner reply")
        self.assertFailsOn("G3", r, "Owner approved the exact design hash")

    def test_g3_requires_g3s_and_g3k(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/gates/G3S.json"))
        rec = F.rj(r, "artifacts/gates/G3K.json"); rec["result"] = "FAIL"; F.wj(r, "artifacts/gates/G3K.json", rec)
        rec = self.assertFailsOn("G3", r, "G3S PASS and current")
        self.assertIn("G3K PASS and current", failed(rec))

    def test_g3_worked_answer_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, "fixtures/F1_expected.csv"))
        self.assertFailsOn("G3", r, "Fixtures with worked answers")

    def test_g3_r_check_ml_mode(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage3_locked_design.json"); d["ml_mode"] = "maybe"; F.wj(r, "artifacts/stage3_locked_design.json", d)
        rec = self.assertFailsOn("G3", r, "R: ML mode explicit")
        self.assertIn("ML mode explicit", failed(rec))

    def test_g3_source_gate_review_stale(self):
        r = self.copy()
        F.add_stage3(r, {"counts": "SELECT 'customers' AS t WHERE (SELECT COUNT(*) FROM customers) <> 2 -- v2"})
        F.review(r, "artifacts/stage3/reviews/risk_reviewer_source_gates.json", "risk_reviewer", ["artifacts/stage3/source_gates/manifest.json"])
        self.assertFailsOn("G3", r, "Risk Reviewer source-gate review coverage")

    # ---------------------------------------------------------------- G4a
    def test_g4a_sql_fixture_wrong(self):
        r = self.copy()
        F.add_stage4_outputs(r, {"sql_F1": F.CSV_SUMMARY.replace("c2,7,1", "c2,7,2")})
        rec = self.assertFailsOn("G4a", r, "Fixture F1 sql matches worked answer")
        self.assertEqual(sum(1 for c in failed(rec) if c.startswith("Fixture")), 1)

    def test_g4a_missing_impl_output(self):
        r = self.copy()
        o = F.rj(r, "artifacts/stage4/outputs.json"); o["fixtures"]["rb"] = {}; F.wj(r, "artifacts/stage4/outputs.json", o)
        self.assertFailsOn("G4a", r, "rb: fixture outputs match the declared set")

    def test_g4a_requires_locked_design(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/gates/G3.json"))
        self.assertFailsOn("G4a", r, "G3 PASS and current")

    # ---------------------------------------------------------------- G4b
    def test_g4b_one_field_differs(self):
        r = self.copy()
        F.add_stage4_outputs(r, {"rb": F.CSV_SUMMARY.replace("15.5", "15.50")})
        rec = self.assertFailsOn("G4b", r, "summary: ra vs rb exact match")
        self.assertEqual(rec["mismatch_count"], 2)  # ra-rb and rb-sql
        self.assertIn("Mismatch count 0", failed(rec))

    def test_g4b_tolerance_only_when_design_states_it(self):
        r = self.copy()
        F.add_stage4_outputs(r, {"sql": F.CSV_SUMMARY.replace("15.5", "15.5000001")})
        self.assertFailsOn("G4b", r, "ra vs sql exact match")
        d = F.rj(r, "artifacts/stage3_grok_design.json")
        d["reconciliation"]["outputs"][0]["tolerance"] = {"fields": ["total"], "absolute_tolerance": 1e-6, "relative_tolerance": 0}
        F.wj(r, "artifacts/stage3_grok_design.json", d)
        F.approve_design(r)
        F.review(r, "artifacts/stage3/reviews/second_designer_compare.json", "second_designer", d["review_subjects"])
        F.review(r, "artifacts/stage3/reviews/risk_reviewer_red_team.json", "risk_reviewer", d["review_subjects"])
        self.assertFailsOn("G3", r, "G3K PASS and current")  # G3K read the old design
        self.assertEqual(run_gate("G3K", r)["result"], "PASS")
        self.assertEqual(run_gate("G3", r)["result"], "PASS")
        self.assertEqual(run_gate("G4a", r)["result"], "PASS")
        self.assertEqual(run_gate("G4b", r)["result"], "PASS")
        F.add_stage4_outputs(r, {"sql": F.CSV_SUMMARY.replace("15.5", "15.51")})
        self.assertEqual(run_gate("G4a", r)["result"], "PASS")
        self.assertFailsOn("G4b", r, "ra vs sql exact match")

    def test_g4b_missing_row(self):
        r = self.copy()
        F.add_stage4_outputs(r, {"ra": "customer_id,total,n_orders\nc1,15.5,2\n"})
        self.assertFailsOn("G4b", r, "summary: ra vs rb exact match")

    def test_g4b_extra_column(self):
        r = self.copy()
        F.add_stage4_outputs(r, {"sql": "customer_id,total,n_orders,x\nc1,15.5,2,1\nc2,7,1,1\n"})
        self.assertFailsOn("G4b", r, "ra vs sql exact match")

    def test_g4b_whitespace_is_a_difference(self):
        r = self.copy()
        F.add_stage4_outputs(r, {"rb": "customer_id,total,n_orders\nc1,15.5,2\nc2,7, 1\n"})
        self.assertFailsOn("G4b", r, "ra vs rb exact match")

    def test_g4b_row_order_is_not_a_difference(self):
        r = self.copy()
        F.add_stage4_outputs(r, {"rb": "customer_id,total,n_orders\nc2,7,1\nc1,15.5,2\n"})
        self.assertFailsOn("G4b", r, "G4a PASS and current")  # outputs record changed since G4a ran
        self.assertEqual(run_gate("G4a", r)["result"], "PASS")
        self.assertEqual(run_gate("G4b", r)["result"], "PASS")

    def test_g4b_output_changed_after_freeze(self):
        r = self.copy()
        F.wt(r, "outputs/sql/summary.csv", F.CSV_SUMMARY)  # same bytes is fine
        self.assertEqual(run_gate("G4b", r)["result"], "PASS")
        F.wt(r, "outputs/sql/summary.csv", F.CSV_SUMMARY + "c3,1,1\n")
        self.assertFailsOn("G4b", r, "ra vs sql exact match")

    def test_g4b_duplicate_keys(self):
        r = self.copy()
        dup = F.CSV_SUMMARY + "c2,7,1\n"
        F.add_stage4_outputs(r, {"ra": dup, "rb": dup, "sql": dup})
        self.assertFailsOn("G4b", r, "ra vs rb exact match")

    # ---------------------------------------------------------------- G4c
    def test_g4c_open_must_fix(self):
        r = self.copy()
        F.add_g4c_review(r, [{"id": "M9", "class": "must_fix", "status": "open"}])
        self.assertFailsOn("G4c", r, "no open must-fix")

    def test_g4c_review_of_superseded_reconciliation(self):
        r = self.copy()
        import time
        time.sleep(1.1)
        self.assertEqual(run_gate("G4b", r)["result"], "PASS")  # a re-run writes a new G4b record (new hash)
        self.assertFailsOn("G4c", r, "review coverage")

    def test_g4c_requires_g4b(self):
        r = self.copy()
        F.add_stage4_outputs(r, {"rb": F.CSV_SUMMARY.replace("c1", "c9")})
        run_gate("G4b", r)
        self.assertFailsOn("G4c", r, "G4b PASS and current")

    # ---------------------------------------------------------------- G4d
    def test_g4d_lower_gate_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/gates/G2F.json"))
        self.assertFailsOn("G4d", r, "G2F PASS and current")

    def test_g4d_lower_gate_input_changed(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage1_decision.json"); d["limits"].append("late"); F.wj(r, "artifacts/stage1_decision.json", d)
        self.assertFailsOn("G4d", r, "G1 PASS and current")

    def test_g4d_workflow_gate_fails(self):
        r = self.copy()
        p = "evidence-v2/source.json"
        with open(os.path.join(r, p), "w") as fh:
            json.dump({"status": "FAIL"}, fh)
        rec = self.assertFailsOn("G4d", r, "Workflow Gate")
        self.assertTrue(any(c.startswith("Workflow Gate: ") for c in failed(rec)))

    def test_g4d_r_stage4_status(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage4_validation_status.json"); d["status"] = "FAIL"; F.wj(r, "artifacts/stage4_validation_status.json", d)
        self.assertFailsOn("G4d", r, "R: Stage 4 status")

    def test_g4d_escalated_defect_blocks_release(self):
        r = self.copy()
        repair.open_defect(r, "D7", "G4b", "x")
        for a in ("ra", "rb", "lead"):
            repair.record_attempt(r, "D7", a, False)
        self.assertFailsOn("G4d", r, "Repair cap not exceeded")


class Runner(unittest.TestCase):
    def test_not_implemented_is_tool_error(self):
        with tempfile.TemporaryDirectory() as d:
            for g in ("G0", "G5", "G6", "nonsense"):
                self.assertEqual(run_gate(g, d)["result"], "TOOL_ERROR")

    def test_empty_project_never_passes(self):
        with tempfile.TemporaryDirectory() as d:
            for g in ORDER + ["GP"]:
                self.assertIn(run_gate(g, d, record=False)["result"], ("FAIL", "TOOL_ERROR"), g)


if __name__ == "__main__":
    unittest.main()
