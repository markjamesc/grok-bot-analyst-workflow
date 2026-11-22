"""Regression tests for the case02 workflow changes. Each test plants one failure seen in the third head-to-head case and shows the
changed gate catches it at the earliest point: G3 at lock, G4c for builder corrections, G5P before a ledger is placed,
G5 at finish and G0 for review packets.

Base project: the same R-certified project as test_finish_gates (every gate G1..G6 PASS in order).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from gates import stage_gates as SG
from gates.run import run_gate
from gates.tests import fixture_project as F
from gates.tests import test_finish_gates as TFG

failed = TFG.failed

HOLD_DESIGN = {"decision_output": {"output": "decision", "impl": "ra", "final_action_field": "final_action",
                                   "rule_action_fields": ["rule_action"], "hold_values": ["HELD_FOR_OWNER"]},
               "holds": [{"id": "H1", "owner_source": "approvals/owner_stop_test.txt",
                          "statement": "hold an expansion for the owner when the stop test triggers"}]}


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build an R-certified project")
class Case02Changes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TFG.FinishGates.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        Case02Changes.n += 1
        d = os.path.join(self.tmp, f"c02_{Case02Changes.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    def assertFailsOn(self, gate, root, check_substr, **kw):
        rec = run_gate(gate, root, **kw)
        self.assertEqual(rec["result"], "FAIL", f"{gate} should FAIL; checks={failed(rec)} error={rec.get('error')}")
        self.assertTrue([c for c in failed(rec) if check_substr in c], f"{gate}: no failing check with {check_substr!r}: {failed(rec)}")
        return rec

    def check(self, rec, name):
        hit = [c for c in rec["checks"] if c["check"] == name]
        self.assertTrue(hit, f"no check named {name!r}")
        return hit[0]

    def edit_json(self, r, rel, fn):
        d = F.rj(r, rel)
        fn(d)
        F.wj(r, rel, d)

    # ------------------------------------------------------------ change 1: Stage 3 lock checks every Workflow Gate field
    def test_good_base_passes_new_checks(self):
        for g, name in (("G3", "Workflow Gate fields present at lock"), ("G3", "Decision thresholds declared"),
                        ("G3", "Owner holds declared with source"), ("G4c", "Builder corrections logged"),
                        ("G5", "Decision thresholds stated numerically"), ("G5", "Owner hold reported beside the rule's action")):
            self.assertEqual(self.check(self.records[g], name)["result"], "PASS", f"{g}: {name}")

    def test_g3_missing_workflow_gate_fields_caught_at_lock(self):
        for field in ("fixture_version", "fixture_ids", "reconciliation_critical_fields"):
            with self.subTest(field=field):
                r = self.copy()
                self.edit_json(r, SG.R_STEP["G3"][1], lambda d: d.pop(field, None))
                F.approve_design(r)
                rec = self.assertFailsOn("G3", r, "Workflow Gate fields present at lock")
                self.assertIn(field, self.check(rec, "Workflow Gate fields present at lock")["detail"])

    def test_g3_ranking_contract_required_under_hard_attention_budget(self):
        s3 = {"stage": 3, "status": "x", "design_version": 1, "population": "p", "grain": "g", "window_start": "a", "window_end": "b",
              "decision_rules": ["r"], "required_outputs": ["o"], "ml_mode": "None", "fixture_version": "v1", "fixture_ids": ["F1"],
              "reconciliation_critical_fields": ["total"]}
        self.assertEqual(SG.workflow_gate_field_gaps(s3, {"capacity_stance": "none"}), [])
        self.assertEqual(SG.workflow_gate_field_gaps(s3, {"capacity_stance": "hard_attention_budget"}), ["ranking_contract"])
        s3["ranking_contract"] = {"key": "score", "tie_break": "id", "capacity_unit": "accounts", "membership_first": True,
                                  "padding_allowed": False, "owner_n_deferred": True}
        self.assertEqual(SG.workflow_gate_field_gaps(s3, {"capacity_stance": "hard_attention_budget"}), [])

    # ------------------------------------------------------------ change 7 at lock: thresholds declared
    def test_g3_decision_thresholds_missing(self):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.pop("decision_thresholds"))
        F.approve_design(r)
        self.assertFailsOn("G3", r, "Decision thresholds declared")

    def test_g3_owner_hold_without_source(self):
        r = self.copy()
        bad = json.loads(json.dumps(HOLD_DESIGN))
        bad["holds"][0].pop("owner_source")
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.update(owner_holds=bad))
        F.approve_design(r)
        self.assertFailsOn("G3", r, "Owner holds declared with source")

    # ------------------------------------------------------------ change 2: G5 reads CSV evidence cell by cell; G5P mirrors G5
    def test_g5_csv_row_is_not_one_number(self):
        self.assertNotIn("7", SG.numbers_in(F.CSV_SUMMARY), "the old whole-text reading merges `7,1` into 71")
        self.assertTrue({"7", "1", "15.5", "2"} <= SG.evidence_numbers("outputs/ra/summary.csv", F.CSV_SUMMARY))
        self.assertEqual(SG.evidence_numbers("x.csv", "x,6,3,0.5\n") >= {"6", "3", "0.5"}, True)
        r = self.copy()
        with open(os.path.join(r, "monitoring-plan.md"), "a") as fh:
            fh.write("Customer c2 spent 7 over 1 order.\n")
        led = F.rj(r, SG.CLAIMS)
        F.claims_ledger(r, led["claims"] + [{"id": "C4", "type": "descriptive", "deliverable": "monitoring-plan.md",
                                             "quote": "Customer c2 spent 7 over 1 order.",
                                             "evidence": [F.ref(r, "outputs/ra/summary.csv")]}])
        rec = run_gate("G5P", r)
        self.assertEqual(self.check(rec, "Claim C4 every number traced")["result"], "PASS", failed(rec))
        self.assertEqual(rec["result"], "PASS", failed(rec))

    def test_g5p_mirrors_g5_claim_and_content_checks(self):
        p = run_gate("G5P", self.base, record=False)
        g5 = {c["check"]: c["result"] for c in self.records["G5"]["checks"]}
        shared = [c for c in p["checks"] if c["check"].startswith(("Claim", "Every deliverable", "Decision thresholds", "Owner hold"))]
        self.assertTrue(shared)
        for c in shared:
            self.assertEqual(g5.get(c["check"]), c["result"], c["check"])

    def test_g5p_on_unplaced_ledger(self):
        r = self.copy()
        led = F.rj(r, SG.CLAIMS)
        led["claims"][0]["quote"] = "Customer c1 spent 16 over 2 orders."
        F.wj(r, "replies/grok/claims_v02.json", led)
        self.assertFailsOn("G5P", r, "Claim C1", ledger="replies/grok/claims_v02.json")

    # ------------------------------------------------------------ change 3: report path change must update every claim
    def test_g5_claim_deliverable_path_mismatch(self):
        r = self.copy()
        led = F.rj(r, SG.CLAIMS)
        led["claims"][0]["deliverable"] = "outputs/old_report/stage5-evidence.md"
        F.wj(r, SG.CLAIMS, led)
        self.assertFailsOn("G5", r, "Claim C1 deliverable listed in deliverables")
        self.assertFailsOn("G5P", r, "Claim C1 deliverable listed in deliverables")

    # ------------------------------------------------------------ change 7 at finish: thresholds stated numerically
    def test_g5_threshold_not_stated_numerically(self):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d["decision_thresholds"].append(
            {"id": "TH2", "value": 0.25, "statement": "share of orders above the cap"}))
        rec = self.assertFailsOn("G5P", r, "Decision thresholds stated numerically")
        self.assertIn("TH2", self.check(rec, "Decision thresholds stated numerically")["detail"])

    def test_g5_threshold_stated_in_words_only(self):
        r = self.copy()
        with open(os.path.join(r, "stage5-decision.md"), "w") as fh:
            fh.write("Decision: expand for c1, whose total is above the threshold of 10.\nThreshold TH1 is the locked cut-off.\n")
        F.claims_ledger(r)
        self.assertFailsOn("G5P", r, "Decision thresholds stated numerically")

    # ------------------------------------------------------------ change 8: a triggered hold never withholds the rule's action
    def _with_hold(self, final_action):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.update(owner_holds=HOLD_DESIGN))
        dec = F.wt(r, "outputs/ra/decision.csv", f"unit,rule_action,final_action\nA1,EXPAND,{final_action}\n")
        self.edit_json(r, SG.OUTPUTS, lambda o: o["outputs"]["ra"].update(decision=dec))
        return r

    def test_g5_stop_gate_withholding_decided_action(self):
        r = self._with_hold("HELD_FOR_OWNER")
        with open(os.path.join(r, "stage5-decision.md"), "a") as fh:
            fh.write("U1 is held for the owner (H1); no action is recommended.\n")
        F.claims_ledger(r)
        self.assertFailsOn("G5P", r, "Owner hold reported beside the rule's action")

    def test_g5_stop_gate_reported_beside_rule_action(self):
        r = self._with_hold("HELD_FOR_OWNER")
        with open(os.path.join(r, "stage5-decision.md"), "a") as fh:
            fh.write("U1: the stated rule decides EXPAND; hold H1 puts it to the owner before it is carried out.\n")
        F.claims_ledger(r)
        rec = run_gate("G5P", r)
        self.assertEqual(self.check(rec, "Owner hold reported beside the rule's action")["result"], "PASS", failed(rec))

    def test_g5_hold_not_triggered(self):
        r = self._with_hold("EXPAND")
        rec = run_gate("G5P", r)
        c = self.check(rec, "Owner hold reported beside the rule's action")
        self.assertEqual(c["result"], "PASS")
        self.assertIn("no hold triggered", c["detail"])

    # ------------------------------------------------------------ change 4: builder corrections are logged, never unlock/re-freeze
    def _g4c_review_with_log(self, r):
        o = F.rj(r, SG.OUTPUTS)
        files = ["artifacts/gates/G4b.json"] + [x["path"] for i in ("ra", "rb", "sql") for x in o["outputs"][i].values()] + [SG.CORRECTIONS]
        F.review(r, "artifacts/stage4/reviews/risk_reviewer_g4c.json", "risk_reviewer", files)

    def test_g4c_corrections_log_malformed(self):
        r = self.copy()
        F.wj(r, SG.CORRECTIONS, {"corrections": [{"id": "K1", "path": "outputs/ra/summary.csv", "old_sha256": "0" * 64,
                                                  "new_sha256": "f" * 64, "author_role": "analyst-r-a", "reason": "typo",
                                                  "logged_at": "2026-11-15T10:00:00-06:00"}]})
        self._g4c_review_with_log(r)
        self.assertFailsOn("G4c", r, "Builder corrections logged")

    def test_g4c_corrections_log_good(self):
        r = self.copy()
        F.wj(r, SG.CORRECTIONS, {"corrections": [{"id": "K1", "path": "outputs/ra/summary.csv", "old_sha256": "0" * 64,
                                                  "new_sha256": F.sha(os.path.join(r, "outputs/ra/summary.csv")),
                                                  "author_role": "analyst-r-a", "reason": "header typo fixed before send",
                                                  "logged_at": "2026-11-15T10:00:00-06:00"}]})
        self._g4c_review_with_log(r)
        rec = run_gate("G4c", r)
        self.assertEqual(rec["result"], "PASS", failed(rec))

    # ------------------------------------------------------------ change 2: precheck carried into Stage 5 review packets
    def _s5_packet(self, r, inputs):
        body = F.packet_text(r, "CASE-5-01", role="Risk Reviewer", stage="5", inputs=inputs,
                             expected="artifacts/stage5/reviews/risk_reviewer_numbers.json")
        F.add_packets(r, [("CASE-5-01", body, "answered", F.reply_text("CASE-5-01", ("artifacts/stage5/reviews/risk_reviewer_numbers.json",)))])
        return run_gate("G0", r)

    def test_g0_stage5_review_packet_without_precheck(self):
        r = self.copy()
        rec = self._s5_packet(r, [SG.CLAIMS, "stage5-evidence.md"])
        self.assertEqual(rec["result"], "FAIL")
        self.assertIn("Packet CASE-5-01 Stage 5 review carries a precheck log", failed(rec))

    def test_g0_stage5_review_packet_with_precheck(self):
        # 2026-11-22 (known fix 3): the precheck is the runner-written G5P record for this exact ledger, not a file name.
        r = self.copy()
        self.assertEqual(run_gate("G5P", r, ledger=SG.CLAIMS)["result"], "PASS")
        cur = F.sha(os.path.join(r, "artifacts/gates/G5P.json"))
        hist = [os.path.join("artifacts/gates/history", n) for n in os.listdir(os.path.join(r, "artifacts/gates/history"))
                if n.startswith("G5P-") and F.sha(os.path.join(r, "artifacts/gates/history", n)) == cur]
        rec = self._s5_packet(r, [SG.CLAIMS, *F.DELIVERABLES, hist[0]])
        self.assertNotIn("Packet CASE-5-01 Stage 5 review carries a precheck log", failed(rec))
        self.assertNotIn("Packet CASE-5-01 Stage 5 precheck PASS for the exact ledger", failed(rec))

    def test_g0_stage5_precheck_file_name_alone_no_longer_counts(self):
        r = self.copy()
        F.wt(r, "artifacts/stage5/precheck_CASE-5-01.txt", "G5P PASS\n")
        rec = self._s5_packet(r, [SG.CLAIMS, "stage5-evidence.md", "artifacts/stage5/precheck_CASE-5-01.txt"])
        self.assertIn("Packet CASE-5-01 Stage 5 review carries a precheck log", failed(rec))


if __name__ == "__main__":
    unittest.main()
