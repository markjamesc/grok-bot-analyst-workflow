"""End-to-end, planted-defect and R-parity tests for G0 (packet integrity), G5 (claims) and G6 (certificate).

The base project is R-CERTIFIED: the R repo's own Procedure Gate CLI ran start..finish and finalize on it
(make_r_certified_project.R). The Grok gate inputs are added on top and every gate G1..G6 must PASS in order.
Each planted-defect test copies the base, plants one defect, and asserts the gate FAILs on the named check.
R parity: the R checks inside G1/G2/G3/G4d/G5 are compared one-for-one with the R repo's own functions
(parity_tests/r_stage_checks.R), and the R `finalize` verdict is compared with the Python port's on the same state.
G0 has no R counterpart (the R gate has no packet format); its tests are fault injection only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from gates import repair
from gates import stage_gates as SG
from gates.run import run_gate
from gates.tests import fixture_project as F

ORDER = ["G1", "G2", "G2F", "G3S", "G3K", "G3", "G4a", "G4b", "G4c", "G4d", "G5", "G0", "G6"]
PKG = F.PKG


def failed(rec):
    return [c["check"] for c in rec["checks"] if c["result"] != "PASS"]


def r_stage_checks(root, step, rel):
    p = subprocess.run([F.rscript(), os.path.join(PKG, "gates/parity_tests/r_stage_checks.R"), F.r_repo(), root, step, rel],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stdout + p.stderr)
    return json.loads(p.stdout)


def py_stage_checks(rec):
    return [{"check": c["check"][3:], "result": c["result"]} for c in rec["checks"] if c["check"].startswith("R: ")]


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build an R-certified project")
class FinishGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="grok-finish-")
        cls.base = os.path.join(cls.tmp, "base")
        cls.pin = os.path.join(cls.tmp, "pin")
        F.build_r_certified_project(cls.base)
        F.add_stage2(cls.base, cls.pin)
        F.add_feasibility(cls.base)
        F.add_stage3(cls.base)
        F.add_stage4_outputs(cls.base)
        with open(os.path.join(cls.base, SG.WG_REPORT), "rb") as fh:
            cls.r_report = fh.read()
        cls.records = {}
        for g in ORDER:
            if g == "G4c":
                F.add_g4c_review(cls.base)
            if g == "G5":
                F.add_stage5(cls.base)
            if g == "G0":
                F.add_packets(cls.base)
            if g == "G6":
                F.approve_finish(cls.base)
            cls.records[g] = run_gate(g, cls.base)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        FinishGates.n += 1
        d = os.path.join(self.tmp, f"case{FinishGates.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    def assertFailsOn(self, gate, root, check_substr):
        rec = run_gate(gate, root)
        self.assertEqual(rec["result"], "FAIL", f"{gate} should FAIL; checks={failed(rec)} error={rec.get('error')}")
        hit = [c for c in failed(rec) if check_substr in c]
        self.assertTrue(hit, f"{gate}: expected a failing check containing {check_substr!r}; failing: {failed(rec)}")
        return rec

    def packets(self, r, rows):
        F.add_packets(r, rows)

    # ---------------------------------------------------------------- good path
    def test_00_certified_project_passes_every_gate_in_order(self):
        for g in ORDER:
            rec = self.records[g]
            self.assertEqual(rec["result"], "PASS", f"{g}: {failed(rec)} {rec.get('error', '')}")
        self.assertTrue(any(c["check"].startswith("R: ") for c in self.records["G5"]["checks"]))
        cert = self.records["G6"]["certificate"]
        self.assertEqual(sorted(cert["gates"]), sorted(SG.CHAIN))
        self.assertEqual(F.rj(self.base, "artifacts/gates/G6.json")["result"], "PASS")

    def test_01_g4d_keeps_the_r_recorded_workflow_report(self):
        with open(os.path.join(self.base, SG.WG_REPORT), "rb") as fh:
            self.assertEqual(fh.read(), self.r_report, "G4d must not overwrite the report the R Procedure Gate recorded")
        self.assertIn("R-recorded Workflow Gate report unchanged", [c["check"] for c in self.records["G4d"]["checks"]])

    def test_g4d_r_recorded_report_edited(self):
        r = self.copy()
        with open(os.path.join(r, SG.WG_REPORT), "a") as fh:
            fh.write(" ")
        self.assertFailsOn("G4d", r, "R-recorded Workflow Gate report unchanged")

    # ---------------------------------------------------------------- R parity
    def test_parity_r_stage_checks_good_project(self):
        for gid, (step, rel) in SG.R_STEP.items():
            with self.subTest(gate=gid):
                self.assertEqual(py_stage_checks(self.records[gid]), r_stage_checks(self.base, step, rel))

    def test_parity_r_stage_checks_planted_defects(self):
        plants = {"G1": ("artifacts/stage1_decision.json", "unresolved_issues", 1),
                  "G5": ("artifacts/stage5_interpretation_status.json", "human_analyst_approval", "PENDING"),
                  "G3": ("artifacts/stage3_locked_design.json", "ml_mode", "maybe")}
        for gid, (rel, key, val) in plants.items():
            with self.subTest(gate=gid):
                r = self.copy()
                d = F.rj(r, rel); d[key] = val; F.wj(r, rel, d)
                rec = run_gate(gid, r)
                self.assertEqual(rec["result"], "FAIL")
                py = py_stage_checks(rec)
                self.assertTrue(any(c["result"] == "FAIL" for c in py), gid)
                self.assertEqual(py, r_stage_checks(r, SG.R_STEP[gid][0], rel))
        r = self.copy()
        d = F.rj(r, "artifacts/stage5_interpretation_status.json"); d.pop("claim_ledger")
        F.wj(r, "artifacts/stage5_interpretation_status.json", d)
        rec = run_gate("G5", r)
        self.assertEqual(py_stage_checks(rec), r_stage_checks(r, "finish", "artifacts/stage5_interpretation_status.json"))

    def _finalize_both(self, r):
        """Python port first, the project restored in place (the R certificate is bound to its project root), then R."""
        snap = r + "-snap"
        shutil.copytree(r, snap, symlinks=True)
        env = dict(os.environ, GATES_FRAMEWORK_ROOT=F.r_repo(), PYTHONPATH=PKG)
        pp = subprocess.run([sys.executable, "-m", "gates.procedure", "finalize", r], capture_output=True, text=True, env=env, cwd=PKG)
        pcert = F.rj(r, "artifacts/final_certificate.json")
        shutil.rmtree(r)
        shutil.copytree(snap, r, symlinks=True)
        shutil.rmtree(snap)
        pr = subprocess.run([F.rscript(), os.path.join(F.r_repo(), "procedure-gate/procedure_gate.R"), "finalize", r],
                            capture_output=True, text=True)
        return pr.returncode, pp.returncode, F.rj(r, "artifacts/final_certificate.json"), pcert

    def test_parity_r_finalize_verdicts(self):
        r = os.path.join(self.tmp, "fin")
        F.build_r_certified_project(r)
        rc, pc, rcert, pcert = self._finalize_both(r)
        self.assertEqual((rc, rcert["result"], rcert["certified"]), (0, "PASS", True))
        self.assertEqual((pc, pcert["result"], pcert["certified"]), (0, "PASS", True))
        self.assertEqual(rcert["completed_steps"], pcert["completed_steps"])
        self.assertEqual(rcert["deliverables"], pcert["deliverables"])
        d = F.rj(r, "artifacts/stage1_decision.json"); d["limits"].append("late edit"); F.wj(r, "artifacts/stage1_decision.json", d)
        rc, pc, rcert, pcert = self._finalize_both(r)
        self.assertNotEqual(rc, 0)
        self.assertNotEqual(pc, 0)
        self.assertEqual((rcert["result"], pcert["result"]), ("FAIL", "FAIL"))
        self.assertEqual([c["check"] for c in rcert["checks"] if c["result"] != "PASS"],
                         [c["check"] for c in pcert["checks"] if c["result"] != "PASS"])
        g = self.copy()
        d = F.rj(g, "artifacts/stage1_decision.json"); d["limits"].append("late edit"); F.wj(g, "artifacts/stage1_decision.json", d)
        rec = self.assertFailsOn("G6", g, "R certificate stages complete and unchanged")
        self.assertIn("G1 PASS and current", failed(rec))

    # ---------------------------------------------------------------- G0 planted defects
    def _one(self, r, body, status="answered", rep="default", pid="CASE-4-01"):
        rep = F.reply_text(pid) if rep == "default" else rep
        self.packets(r, [(pid, body, status, rep)])

    def test_g0_template_marker_left_in_packet(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01") + "TEMPLATE note: replace before sending\n")
        self.assertFailsOn("G0", r, "no template leftovers")

    def test_g0_unfilled_placeholder(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01").replace("Review the reconciled", "Review {{subject}} and the reconciled"))
        self.assertFailsOn("G0", r, "no template leftovers")
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01").replace("ROLE: Risk Reviewer", "ROLE: <child role>"))
        rec = self.assertFailsOn("G0", r, "no template leftovers")
        self.assertIn("Packet CASE-4-01 ROLE known", failed(rec))

    def test_g0_input_stale_hash(self):
        r = self.copy()
        body = F.packet_text(r, "CASE-4-01")
        F.wt(r, "outputs/ra/summary.csv", F.CSV_SUMMARY + "c3,1,1\n")
        self._one(r, body)
        self.assertFailsOn("G0", r, "inputs whole and current")

    def test_g0_partial_input(self):
        r = self.copy()
        full = os.path.join(r, "outputs/ra/summary.csv")
        line = f"  - outputs/ra/summary.csv sha256={F.sha(full)} bytes={os.path.getsize(full) - 5}"
        self._one(r, F.packet_text(r, "CASE-4-01", inputs=[("x", line)]))
        self.assertFailsOn("G0", r, "inputs whole and current")

    def test_g0_split_input_missing_part(self):
        r = self.copy()
        F.wt(r, "parts/D/p1.md", "part one\n"); F.wt(r, "parts/D/p3.md", "part three\n")
        lines = []
        for k in (1, 3):
            full = os.path.join(r, f"parts/D/p{k}.md")
            lines.append(("x", f"  - parts/D/p{k}.md sha256={F.sha(full)} bytes={os.path.getsize(full)} part {k} of 3"))
        self._one(r, F.packet_text(r, "CASE-4-01", inputs=lines))
        self.assertFailsOn("G0", r, "split inputs complete")

    def test_g0_forbidden_inputs(self):
        for rel in ("private/reference.md", "keys/k.md", "docs/answer_key.md"):
            with self.subTest(path=rel):
                r = self.copy()
                F.wt(r, rel, "secret\n")
                self._one(r, F.packet_text(r, "CASE-4-01", inputs=[rel]))
                self.assertFailsOn("G0", r, "no forbidden inputs")

    def test_g0_answer_key_not_withheld(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01", not_allowed="peer paths before freeze"))
        self.assertFailsOn("G0", r, "answer key withheld")

    def test_g0_packet_edited_after_send(self):
        r = self.copy()
        with open(os.path.join(r, "packets/grok/CASE-4-01.md"), "a") as fh:
            fh.write("RULES: late addition\n")
        self.assertFailsOn("G0", r, "sealed hash current")

    def test_g0_header_field_missing(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01").replace("RULES: review coverage needs whole current files\n", ""))
        self.assertFailsOn("G0", r, "header fields")

    def test_g0_packet_id_mismatch(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01").replace("PACKET_ID: CASE-4-01", "PACKET_ID: CASE-4-99"))
        self.assertFailsOn("G0", r, "PACKET_ID matches index")

    def test_g0_forbidden_string(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01", extra="NOTE: do-not-ship-marker\n"))
        self.assertFailsOn("G0", r, "no forbidden strings")

    def test_g0_blank_produced_files_list(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01"), rep=F.reply_text("CASE-4-01", produced=()))
        rec = self.assertFailsOn("G0", r, "produced-files list not blank")
        self.assertIn("Packet CASE-4-01 produced files cover expected outputs", failed(rec))

    def test_g0_reply_without_answered_marker(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01"), rep=F.reply_text("CASE-4-01", last="Done."))
        self.assertFailsOn("G0", r, "reply ends with ANSWERED")

    def test_g0_file_on_disk_is_not_a_completed_send(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01"), status="sent", rep=None)
        rec = run_gate("G0", r)
        self.assertEqual(rec["result"], "PASS", failed(rec))
        self.assertEqual(rec["unanswered"], ["CASE-4-01"])
        self.assertFailsOn("G6", r, "Every packet answered")
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01"), status="answered", rep=None)
        self.assertFailsOn("G0", r, "reply sealed")

    def test_g0_produced_file_missing(self):
        r = self.copy()
        self._one(r, F.packet_text(r, "CASE-4-01"),
                  rep=F.reply_text("CASE-4-01", produced=("artifacts/stage4/reviews/risk_reviewer_g4c.json", "docs/not_written.md")))
        self.assertFailsOn("G0", r, "produced files exist")

    def test_g0_correction_must_name_superseded_packet(self):
        r = self.copy()
        rows = [("CASE-4-01", F.packet_text(r, "CASE-4-01"), "answered", F.reply_text("CASE-4-01")),
                ("CASE-4-01-v2", F.packet_text(r, "CASE-4-01-v2"), "answered", F.reply_text("CASE-4-01-v2"))]
        self.packets(r, rows)
        self.assertFailsOn("G0", r, "names what it supersedes")
        rows[1] = ("CASE-4-01-v2", F.packet_text(r, "CASE-4-01-v2", extra="SUPERSEDES: CASE-4-01\n"), "answered", F.reply_text("CASE-4-01-v2"))
        self.packets(r, rows)
        self.assertEqual(run_gate("G0", r)["result"], "PASS")

    def test_g0_missing_index(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/packets/index.json"))
        self.assertFailsOn("G0", r, "Packet index parses")

    # ---------------------------------------------------------------- G5 planted defects
    def claims(self, r):
        return F.rj(r, "artifacts/stage5_claims.json")["claims"]

    def plant_claims(self, r, claims):
        F.add_stage5(r, claims)

    def test_g5_quote_not_in_deliverable(self):
        r = self.copy()
        c = self.claims(r); c[0]["quote"] = "Customer c1 spent 99 over 2 orders."
        self.plant_claims(r, c)
        self.assertFailsOn("G5", r, "Claim C1 quoted verbatim from a deliverable")

    def test_g5_untraced_number(self):
        r = self.copy()
        F.wt(r, "stage5-evidence.md", "Customer c1 spent 15.5 over 2 orders, 31% of revenue.\n")
        c = self.claims(r); c[0]["quote"] = "Customer c1 spent 15.5 over 2 orders, 31% of revenue."
        self.plant_claims(r, c)
        self.assertFailsOn("G5", r, "Claim C1 every number traced")
        c[0]["derived"] = [{"value": "31", "basis": "15.5 / 50 from the sealed summary, recomputed by the Risk Reviewer"}]
        self.plant_claims(r, c)
        rec = run_gate("G5", r)
        self.assertNotIn("Claim C1 every number traced", failed(rec))

    def test_g5_evidence_not_sealed(self):
        r = self.copy()
        F.wt(r, "notes/scratch.csv", "customer_id,total\nc1,15.5\n")
        c = self.claims(r); c[0]["evidence"] = [F.ref(r, "notes/scratch.csv")]
        self.plant_claims(r, c)
        self.assertFailsOn("G5", r, "Claim C1 tied to sealed evidence")

    def test_g5_claim_without_evidence(self):
        r = self.copy()
        c = self.claims(r); c[2]["evidence"] = []
        self.plant_claims(r, c)
        self.assertFailsOn("G5", r, "Claim C3 tied to sealed evidence")

    def test_g5_claim_above_ceiling(self):
        r = self.copy()
        c = self.claims(r); c[1]["type"] = "causal"
        self.plant_claims(r, c)
        self.assertFailsOn("G5", r, "Claim C2 type within the claim ceiling")

    def test_g5_deliverable_without_claim(self):
        r = self.copy()
        self.plant_claims(r, self.claims(r)[:2])
        self.assertFailsOn("G5", r, "Every deliverable carries a recorded claim")

    def test_g5_deliverables_differ_from_r_receipt(self):
        r = self.copy()
        F.wt(r, "extra.md", "Customer c1 spent 15.5 over 2 orders.\n")
        F.add_stage5(r)
        led = F.rj(r, "artifacts/stage5_claims.json"); led["deliverables"].append(F.ref(r, "extra.md"))
        F.wj(r, "artifacts/stage5_claims.json", led)
        self.assertFailsOn("G5", r, "Deliverables equal the R finish receipt")

    def test_g5_review_of_stale_ledger(self):
        r = self.copy()
        led = F.rj(r, "artifacts/stage5_claims.json"); led["claims"][0]["note"] = "edited after review"
        F.wj(r, "artifacts/stage5_claims.json", led)
        rec = self.assertFailsOn("G5", r, "Risk Reviewer numbers review coverage")
        self.assertIn("Second Designer inference review coverage", failed(rec))

    def test_g5_open_must_fix(self):
        r = self.copy()
        F.review(r, "artifacts/stage5/reviews/risk_reviewer_numbers.json", "risk_reviewer",
                 ["artifacts/stage5_claims.json"] + list(F.DELIVERABLES), [{"id": "N1", "class": "must_fix", "status": "open"}])
        self.assertFailsOn("G5", r, "Risk Reviewer numbers no open must-fix")

    def test_g5_requires_release(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/gates/G4d.json"))
        self.assertFailsOn("G5", r, "G4d PASS and current")

    def test_g5_evidence_changed_after_seal(self):
        r = self.copy()
        F.wt(r, "outputs/ra/summary.csv", F.CSV_SUMMARY + "c3,1,1\n")
        rec = self.assertFailsOn("G5", r, "Claim C1 tied to sealed evidence")  # G4b, which sealed it, is no longer current
        self.assertIn("Claim C2 tied to sealed evidence", failed(rec))
        self.assertFailsOn("G6", r, "G4b PASS and current")

    def test_g5_escalated_defect(self):
        r = self.copy()
        repair.open_defect(r, "D5", "G5", "claim wording")
        for a in ("lead", "second", "lead"):
            repair.record_attempt(r, "D5", a, False)
        self.assertFailsOn("G5", r, "Repair cap not exceeded")

    # ---------------------------------------------------------------- G6 planted defects
    def test_g6_owner_finish_approval_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/stage5_owner_approval.json"))
        self.assertFailsOn("G6", r, "Owner approved the exact finish package")

    def test_g6_placeholder_finish_approval(self):
        r = self.copy()
        F.approve_finish(r, text="PENDING owner reply")
        self.assertFailsOn("G6", r, "Owner approved the exact finish package")

    def test_g6_ledger_changed_after_approval(self):
        r = self.copy()
        led = F.rj(r, "artifacts/stage5_claims.json"); led["claims"][0]["note"] = "late"
        F.wj(r, "artifacts/stage5_claims.json", led)
        rec = self.assertFailsOn("G6", r, "Owner approved the exact finish package")
        self.assertIn("G5 PASS and current", failed(rec))

    def test_g6_deliverable_changed_after_certification(self):
        r = self.copy()
        F.wt(r, "monitoring-plan.md", "Monitor weekly.\n")
        rec = self.assertFailsOn("G6", r, "R certificate deliverables unchanged")
        self.assertIn("Owner approved the exact finish package", failed(rec))

    def test_g6_r_certificate_missing_or_failed(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/final_certificate.json"))
        self.assertFailsOn("G6", r, "R certificate PASS")
        r = self.copy()
        c = F.rj(r, "artifacts/final_certificate.json"); c["result"] = "FAIL"; c["certified"] = False
        F.wj(r, "artifacts/final_certificate.json", c)
        rec = self.assertFailsOn("G6", r, "R certificate PASS")
        self.assertIn("R run state certified this certificate", failed(rec))

    def test_g6_workflow_report_changed(self):
        r = self.copy()
        with open(os.path.join(r, SG.WG_REPORT), "a") as fh:
            fh.write(" ")
        rec = self.assertFailsOn("G6", r, "R Workflow Gate report unchanged")
        self.assertIn("G4d PASS and current", failed(rec))

    def test_g6_stages_out_of_order(self):
        r = self.copy()
        rec = F.rj(r, "artifacts/gates/G5.json"); rec["checked_at_utc"] = "2000-01-01T00:00:00Z"
        F.wj(r, "artifacts/gates/G5.json", rec)
        self.assertFailsOn("G6", r, "All stages in order")

    def test_g6_g0_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/gates/G0.json"))
        rec = self.assertFailsOn("G6", r, "G0 PASS and current")
        self.assertIn("Every packet answered", failed(rec))

    def test_g6_lower_gate_stale(self):
        r = self.copy()
        d = F.rj(r, "artifacts/stage2f_feasibility.json"); d["questions"][0]["reason"] = "edited"
        F.wj(r, "artifacts/stage2f_feasibility.json", d)
        self.assertFailsOn("G6", r, "G2F PASS and current")

    # ---------------------------------------------------------------- process correction: re-review after a framing repair
    def test_g2_framing_repair_needs_rereview_of_current_file(self):
        r = self.copy()
        F.wt(r, "docs/stage2/FRAMING_RECORD_v02.md", "Synthetic framing record, repaired\n")
        d = F.rj(r, "artifacts/stage2_framing.json"); d["review_subjects"] = ["docs/stage2/FRAMING_RECORD_v02.md"]
        F.wj(r, "artifacts/stage2_framing.json", d)
        rec = run_gate("G2", r)
        self.assertIn("Second Designer critique review coverage", failed(rec))
        self.assertIn("Risk Reviewer framing check review coverage", failed(rec))
        for rel, role in (("artifacts/stage2/reviews/second_designer_critique.json", "second_designer"),
                          ("artifacts/stage2/reviews/risk_reviewer_framing_check.json", "risk_reviewer")):
            F.review(r, rel, role, ["docs/stage2/FRAMING_RECORD_v02.md"])
        rec = run_gate("G2", r)
        self.assertFalse([c for c in failed(rec) if "review coverage" in c], failed(rec))


if __name__ == "__main__":
    unittest.main()
