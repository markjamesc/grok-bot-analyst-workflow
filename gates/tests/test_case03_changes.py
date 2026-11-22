"""Regression tests for the case03 workflow changes (lessons L21-L27, from the case02 lessons A1-A13).

Each test plants one failure seen in the case02 run and shows the changed gate or tool now catches it, or shows a false
failure is gone. The past failures covered here:
- a G3 FAIL that was sealed as "Stage 3 closed" (close check, A1);
- a capture whose G0 failed but which was still marked answered (captured status and promote, A4);
- a design locked with a bare-number tolerance and blank fixture keys, found only at Stage 4 (next-stage entry check, A2);
- a locked design naming an older design version's files (A7);
- "MISSING INPUT: none." failing the derivability check (A3);
- a companion file that no gate checked, and a report contradicting the Stage 4 triage receipt (A5);
- a note inside uncovered_claims and two reviews using the same finding ids (A9);
- a stale nested reference after the claims ledger moved (A10);
- `number` vs `value` for thresholds, and an exposure sentence read as a rate ban (A6).

Gate-level tests use the R-certified base project of test_finish_gates (every gate G1..G6 PASS in order). Function-level
tests build small temporary roots and need no R.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from gates import close as C
from gates import guards
from gates import packet as P
from gates import stage_gates as SG
from gates.common import Gate
from gates.derivability import missing_lines
from gates.run import run_gate
from gates.tests import fixture_project as F
from gates.tests import test_finish_gates as TFG

failed = TFG.failed
PKG = F.PKG


def _doc(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------------------------------------------ no R needed
class Case03Units(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c03u-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # A3 -------------------------------------------------------------------------------------------------------
    def test_missing_input_none_is_not_an_item(self):
        for line in ("MISSING INPUT: none.", "MISSING INPUT: none", "missing input: NONE.", "MISSING INPUT: None", "MISSING INPUT: nothing."):
            with self.subTest(line=line):
                self.assertEqual(missing_lines(f"Reply text\n{line}\nANSWERED X-1\n"), [])

    def test_missing_input_real_item_still_raised(self):
        self.assertEqual(missing_lines("MISSING INPUT: the unit of amount\n"), ["the unit of amount"])
        self.assertEqual(missing_lines("MISSING INPUT: none of the codes for region\n"), ["none of the codes for region"])

    def test_missing_input_dash_form_none(self):
        self.assertEqual(missing_lines("- MISSING INPUT: none.\n"), [])

    # A6 -------------------------------------------------------------------------------------------------------
    def test_threshold_number_or_value(self):
        self.assertEqual(SG.threshold_value({"id": "TH1", "number": 3}), "3")
        self.assertEqual(SG.threshold_value({"id": "TH1", "value": 3}), "3")
        self.assertEqual(SG.threshold_value({"id": "TH1", "value": 3, "number": 3.0}), "3")
        self.assertIsNone(SG.threshold_value({"id": "TH1", "value": 3, "number": 4}))
        self.assertIsNone(SG.threshold_value({"id": "TH1", "number": "three"}))
        self.assertIsNone(SG.threshold_value({"id": "TH1"}))

    def test_exposure_sentence_is_not_a_rate_ban(self):
        self.assertEqual(guards.rate_ban_hits("No rate, gap or decision for the candidate has been computed or seen."), [])
        self.assertTrue(guards.rate_ban_hits("No rates."))
        self.assertTrue(guards.rate_ban_hits("Do not report rates that have been computed."))

    def test_exposure_keys_not_scanned(self):
        obj = {"methodology": {"exposure": "no rate yet", "results_seen": "no rates"}, "note": "keep"}
        self.assertEqual(list(guards.text_strings(obj, skip_keys=guards.EXPOSURE_KEYS)), ["keep"])
        self.assertEqual(len(list(guards.text_strings(obj))), 3)

    # A7 -------------------------------------------------------------------------------------------------------
    def _version(self, s3):
        g = Gate("X", self.tmp)
        SG.design_version_checks(g, s3)
        return g.checks[0]

    def test_locked_design_naming_older_version_fails(self):
        s3 = {"design_version": "v04 (docs/stage3/DESIGN_RECORD_v04.md)", "fixture_version": "F1-v02",
              "deliverables": ["docs/stage3/DESIGN_RECORD_v02.md", "docs/stage3/GROK_DESIGN_v02.json", "docs/stage3/fixtures/F1_input_v02.csv"]}
        c = self._version(s3)
        self.assertEqual(c["result"], "FAIL")
        self.assertIn("DESIGN_RECORD_v02.md", c["detail"])
        self.assertNotIn("F1_input_v02.csv", c["detail"])

    def test_locked_design_naming_own_version_passes(self):
        s3 = {"design_version": "v05 (x)", "fixture_version": "F1-v05",
              "deliverables": ["docs/stage3/DESIGN_RECORD_v05.md", "docs/stage3/fixtures/F1_input_v05.csv"],
              "stage_records": [{"path": "docs/stage3/GROK_DESIGN_v05.json", "sha256": "0" * 64}]}
        self.assertEqual(self._version(s3)["result"], "PASS")
        s3["stage_records"][0]["path"] = "docs/stage3/GROK_DESIGN_v03.json"
        self.assertEqual(self._version(s3)["result"], "FAIL")

    def test_integer_design_version(self):
        self.assertEqual(self._version({"design_version": 1, "deliverables": ["docs/stage3/DESIGN.md"]})["result"], "PASS")

    # A5 -------------------------------------------------------------------------------------------------------
    def test_status_claims_parse(self):
        got = [x[0] for x in SG.status_claims("The triage marks G4C-02, -04, -07, -08, -10 and -13 as resolved.")]
        self.assertEqual(got, ["G4C-02", "G4C-04", "G4C-07", "G4C-08", "G4C-10", "G4C-13"])
        got = [x[0] for x in SG.status_claims("It does not carry G4C-02, G4C-04 and G4C-13, and G4C-11 is closed in that review.")]
        self.assertEqual(got, ["G4C-11"])
        self.assertEqual(SG.status_claims("G4C-02 is not resolved."), [])
        self.assertEqual([x[0] for x in SG.status_claims("RR5-03 and SD5-01 are fixed")], ["RR5-03", "SD5-01"])

    def _status_root(self, report, disposition="advisory: carried to the Stage 5 disclosures"):
        r = self.tmp
        F.wj(r, SG.G4C_REVIEW, {"role": "risk_reviewer", "subjects": [], "findings": [
            {"id": "G4C-01", "class": "advisory", "status": "open"}, {"id": "G4C-02", "class": "advisory", "status": "open"},
            {"id": "G4C-03", "class": "advisory", "status": "closed"}]})
        m = F.wj(r, "receipts/run/methodology.json", {"triage": [
            {"id": "G4C-01", "status": "resolved", "disposition": disposition},
            {"id": "G4C-02", "status": "resolved", "disposition": disposition},
            {"id": "G4C-03", "status": "resolved", "disposition": "closed by the reviewer"}]})
        F.wj(r, SG.R_STEP["G4d"][1], {"evidence_receipts": {"methodology": m}})
        F.wt(r, "report.md", report)
        g = Gate("X", r)
        SG.status_word_checks(g, r, ["report.md"])
        return {c["check"]: c for c in g.checks}

    def test_report_calling_open_finding_resolved_fails(self):
        c = self._status_root("- G4C-01 and G4C-02 carried as disclosures.\nThe triage marks G4C-01, -02 as resolved.\n")
        self.assertEqual(c["Finding status words match the G4c review"]["result"], "FAIL")
        self.assertIn("G4C-02", c["Finding status words match the G4c review"]["detail"])

    def test_report_not_carrying_triage_carried_findings_fails(self):
        # case02 C61: the report said it did not carry advisories that the Stage 4 triage records as carried to Stage 5.
        c = self._status_root("- G4C-01 carried (D1); it does not carry the open advisory G4C-02, and G4C-03 is closed in that review.\n")
        self.assertEqual(c["Finding status words match the G4c review"]["result"], "PASS")
        self.assertEqual(c["Triage 'carried' findings carried in the report"]["result"], "FAIL")
        self.assertIn("G4C-02", c["Triage 'carried' findings carried in the report"]["detail"])

    def test_report_carrying_every_triage_finding_passes(self):
        c = self._status_root("- carried: G4C-01 (D1), G4C-02 (D2); G4C-03 is closed in that review.\n")
        self.assertTrue(all(x["result"] == "PASS" for x in c.values()), c)

    def test_companions_from_approval_text(self):
        h = "a" * 64
        comps = SG.declared_companions({}, {"approval_text": f"deliverable x.md sha256 {'b' * 64}; companion docs/P.md sha256 {h}; done"})
        self.assertEqual(comps, {"docs/P.md": h})

    # A10 ------------------------------------------------------------------------------------------------------
    def _stale_root(self, historical):
        r = self.tmp
        old = F.wt(r, "artifacts/stage5/history/v01/stage5_claims.json", '{"claims": []}\n')
        F.wt(r, SG.CLAIMS, '{"claims": [1]}\n')
        rv = F.wj(r, "outputs/S5-13/review.json", {"subjects": [{"path": SG.CLAIMS, "sha256": old["sha256"]}]})
        F.wj(r, "artifacts/operations/finish.json", {"sends": [{"id": "S5-15", "attachments": [rv]}]})
        if historical:
            rec = F.wj(r, "artifacts/stage5/h1_record_v01.json", {"historical_sent_fail": "S5-15", "superseded_inputs": {SG.CLAIMS: old}})
            F.wj(r, "artifacts/operations/finish.historical.json", {"historical_sends": [{"send_id": "S5-15", "supersession": rec}]})
        return r

    def test_stale_nested_ref_after_claims_move_fails(self):
        stale = SG.stale_nested_refs(self._stale_root(False), "finish")
        self.assertEqual([(s[0], s[2]) for s in stale], [("S5-15", SG.CLAIMS)])

    def test_stale_nested_ref_resolved_by_h1_record(self):
        self.assertEqual(SG.stale_nested_refs(self._stale_root(True), "finish"), [])

    # A2 -------------------------------------------------------------------------------------------------------
    def test_tolerance_shape(self):
        self.assertTrue(SG._tolerance_shape_ok(None))
        self.assertTrue(SG._tolerance_shape_ok({"fields": ["rate"], "absolute_tolerance": 1e-9, "relative_tolerance": 0}))
        self.assertFalse(SG._tolerance_shape_ok(1e-9))
        self.assertFalse(SG._tolerance_shape_ok({"fields": "rate"}))
        self.assertFalse(SG._tolerance_shape_ok({"fields": ["rate"], "absolute_tolerance": -1}))

    # A1 -------------------------------------------------------------------------------------------------------
    def test_close_required_gates(self):
        self.assertEqual(C.required_gates("G3"), ["G0", "G1", "G2", "G2F", "G3S", "G3K", "G3"])
        self.assertEqual(C.required_gates("G6")[-3:], ["G4d", "G5", "G6"])

    def test_close_without_records_refused(self):
        rec = C.close_check(self.tmp, "G1")
        self.assertEqual(rec["result"], "FAIL")

    def test_close_cli_bad_gate_is_tool_error(self):
        p = subprocess.run([sys.executable, "-m", "gates.close", "G9", self.tmp], cwd=PKG, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    # docs (A6, A9, A11, A13, A1) ------------------------------------------------------------------------------
    def test_docs_match_gate_code(self):
        lead = _doc("docs/roles/lead-designer.md")
        self.assertIn('"owner_holds"', lead)
        self.assertIn('"final_action_field"', lead)
        self.assertIn("number", _doc("docs/stages.md"))
        for rel in ("docs/handoff.md", "docs/roles/second-designer.md", "docs/roles/risk-reviewer.md", "docs/gates.md"):
            self.assertNotIn('"uncovered_claims": ["', _doc(rel), rel)
        # 2026-11-22 (known fix 4): one wording of the finish order everywhere (see test_sunday_changes.FinishOrderDocs)
        self.assertIn("owner approves the exact finish package -> R `complete finish` -> G5 -> R `finalize` -> G6", _doc("docs/stages.md"))
        self.assertIn("Stage 1 reviews", _doc("docs/stages.md"))
        self.assertIn("Stage 1", _doc("docs/roles/second-designer.md"))
        self.assertIn("python3 -m gates.close", _doc("docs/rules.md"))
        self.assertIn("next stage's entry", _doc("docs/rules.md"))


# ------------------------------------------------------------------------------------------------ gate level (R base)
@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build an R-certified project")
class Case03Changes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TFG.FinishGates.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        Case03Changes.n += 1
        d = os.path.join(self.tmp, f"c03_{Case03Changes.n}")
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

    def test_good_base_passes_new_checks(self):
        for g, name in (("G3", "Next-stage entry check (G4a/G4b shape) passes on the locked design"),
                        ("G3", "Locked design names its own version's files"), ("G3", "No stale nested references in the design sends"),
                        ("G5", "Companion files current"), ("G5", "Finding status words match the G4c review"),
                        ("G5", "Triage 'carried' findings carried in the report"), ("G5", "No stale nested references in the finish sends"),
                        ("G5", "Stage 5 uncovered_claims are claim ids"), ("G5", "Stage 5 finding ids distinct across reviews")):
            self.assertEqual(self.check(self.records[g], name)["result"], "PASS", f"{g}: {name}")
        for g in ("G3", "G5", "G6"):
            self.assertEqual(self.records[g]["result"], "PASS", failed(self.records[g]))

    # A1: a FAIL can never be sealed as closed ---------------------------------------------------------------
    def test_close_passes_on_certified_base(self):
        r = self.copy()
        for gid in ("G3", "G4d", "G6"):
            with self.subTest(gate=gid):
                rec = C.close_check(r, gid)
                self.assertEqual(rec["result"], "PASS", [c for c in rec["checks"] if c["result"] != "PASS"])

    def test_close_refused_after_g3_fail(self):
        # Regression: case02 predecessor run, Stage 3 `complete` printed G3 FAIL but exited 0 and the close was sealed.
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.update(decision_thresholds=[]))
        F.approve_design(r)
        self.assertEqual(run_gate("G3", r)["result"], "FAIL")
        rec = C.close_check(r, "G3")
        self.assertEqual(rec["result"], "FAIL")
        self.assertIn("recorded result is 'FAIL'", self.check(rec, "G3 PASS and current")["detail"])
        p = subprocess.run([sys.executable, "-m", "gates.close", "G3", r], cwd=PKG, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout[-800:])
        self.assertTrue(os.listdir(os.path.join(r, C.CLOSE_DIR)), "the refused close is recorded")

    def test_close_refused_when_inputs_changed(self):
        r = self.copy()
        with open(os.path.join(r, "fixtures/F1_expected.csv"), "a") as fh:
            fh.write("c3,1,1\n")
        rec = C.close_check(r, "G3")
        self.assertEqual(rec["result"], "FAIL")
        self.assertIn("inputs changed", self.check(rec, "G3 PASS and current")["detail"])

    def test_close_refused_when_record_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, "artifacts/gates/G4c.json"))
        rec = C.close_check(r, "G4d")
        self.assertEqual(rec["result"], "FAIL")
        self.assertEqual(self.check(rec, "G4c PASS and current")["result"], "FAIL")

    # A4: captured replies --------------------------------------------------------------------------------------
    def _captured(self, r, last=None, extra=""):
        F.add_packets(r, [("CASE-4-01", F.packet_text(r, "CASE-4-01"), "captured", extra + F.reply_text("CASE-4-01", last=last))])

    def test_captured_packet_is_unanswered_and_blocks_close(self):
        r = self.copy()
        self._captured(r)
        rec = run_gate("G0", r)
        self.assertEqual(rec["result"], "PASS", failed(rec))
        self.assertEqual(rec["captured"], ["CASE-4-01"])
        self.assertEqual(rec["unanswered"], ["CASE-4-01"])
        c = C.close_check(r, "G6")
        self.assertEqual(self.check(c, "No captured reply waiting for promotion")["result"], "FAIL")

    def test_promote_captured_on_pass(self):
        r = self.copy()
        self._captured(r)
        code, msg = P.promote(r, "CASE-4-01")
        self.assertEqual(code, 0, msg)
        self.assertEqual(F.rj(r, P.INDEX)["packets"][0]["status"], "answered")
        self.assertEqual(run_gate("G0", r)["result"], "PASS")

    def test_failed_capture_stays_captured(self):
        # Regression: a capture whose G0 failed was still marked answered.
        r = self.copy()
        self._captured(r, last="DONE")
        code, msg = P.promote(r, "CASE-4-01")
        self.assertEqual(code, 1, msg)
        self.assertIn("stays captured", msg)
        self.assertEqual(F.rj(r, P.INDEX)["packets"][0]["status"], "captured")
        self.assertIn("Packet CASE-4-01 reply ends with ANSWERED", failed(run_gate("G0", r)))
        p = subprocess.run([sys.executable, "-m", "gates.packet", "promote", r, "CASE-4-01"], cwd=PKG, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_promote_refuses_non_captured(self):
        r = self.copy()
        code, _ = P.promote(r, "CASE-4-01")
        self.assertEqual(code, 1)

    def test_captured_reply_missing_input_checked(self):
        r = self.copy()
        self._captured(r, extra="MISSING INPUT: the unit of amount\n")
        self.assertIn("Derivability: Every MISSING INPUT checked against public files", failed(run_gate("G0", r)))

    # A3: "MISSING INPUT: none." ------------------------------------------------------------------------------
    def test_g0_missing_input_none_passes(self):
        # Regression: G0 FAILED on "MISSING INPUT: none." in two case02 Stage 5 replies.
        r = self.copy()
        F.add_packets(r, [("CASE-4-01", F.packet_text(r, "CASE-4-01"), "answered", "MISSING INPUT: none.\n" + F.reply_text("CASE-4-01"))])
        rec = run_gate("G0", r)
        self.assertEqual(rec["result"], "PASS", failed(rec))

    def test_g0_real_missing_input_still_fails(self):
        r = self.copy()
        F.add_packets(r, [("CASE-4-01", F.packet_text(r, "CASE-4-01"), "answered", "MISSING INPUT: region codes\n" + F.reply_text("CASE-4-01"))])
        self.assertIn("Derivability: Every MISSING INPUT checked against public files", failed(run_gate("G0", r)))

    # A2: next stage's entry check at lock ----------------------------------------------------------------------
    def test_g3_bare_float_tolerance_caught_at_lock(self):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d["fixtures"][0].update(tolerance=1e-9))
        F.approve_design(r)
        rec = self.assertFailsOn("G3", r, "Next-stage entry check")
        self.assertIn("not float", self.check(rec, "Next-stage entry check (G4a/G4b shape) passes on the locked design")["detail"])

    def test_g3_output_bare_float_tolerance_caught_at_lock(self):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d["reconciliation"]["outputs"][0].update(tolerance=0.001))
        F.approve_design(r)
        self.assertFailsOn("G3", r, "Next-stage entry check")

    def test_g3_blank_fixture_keys_caught_at_lock(self):
        r = self.copy()
        wa = F.wt(r, "fixtures/F1_expected_blank.csv", "customer_id,total,n_orders\nc1,15.5,2\n,7,1\n")
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d["fixtures"][0].update(worked_answer=wa))
        F.approve_design(r)
        rec = self.assertFailsOn("G3", r, "Next-stage entry check")
        self.assertIn("keys missing, blank or duplicated", self.check(rec, "Next-stage entry check (G4a/G4b shape) passes on the locked design")["detail"])

    # A6: thresholds `number` or `value`; exposure not a ban -----------------------------------------------------
    def test_g3_threshold_number_field_accepted(self):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.update(decision_thresholds=[{"id": "TH1", "number": 10, "statement": "above 10"}]))
        F.approve_design(r)
        rec = run_gate("G3", r)
        self.assertEqual(self.check(rec, "Decision thresholds declared")["result"], "PASS")

    def test_g3_threshold_number_and_value_disagree(self):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.update(decision_thresholds=[{"id": "TH1", "number": 10, "value": 12, "statement": "x"}]))
        F.approve_design(r)
        self.assertFailsOn("G3", r, "Decision thresholds declared")

    def test_g5_threshold_number_field_stated(self):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.update(decision_thresholds=[{"id": "TH1", "number": 10, "statement": "above 10"}]))
        rec = run_gate("G5P", r)
        self.assertEqual(self.check(rec, "Decision thresholds stated numerically")["result"], "PASS")

    def test_g3_exposure_text_not_a_rate_ban(self):
        r = self.copy()
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.update(methodology={"results_seen": "no rates",
                                                                           "exposure": "No rate, gap or decision has been computed or seen."}))
        F.approve_design(r)
        self.assertEqual(self.check(run_gate("G3", r), "Descriptive rates not banned")["result"], "PASS")
        self.edit_json(r, SG.GROK_DESIGN, lambda d: d.update(notes="No rates."))
        F.approve_design(r)
        self.assertFailsOn("G3", r, "Descriptive rates not banned")

    # A5: companion files and status words ----------------------------------------------------------------------
    def _companion(self, r):
        return F.wt(r, "docs/stage5/PARENT_RECORDS_v01.md", "Parent records for the owner. Advisory A1 stays open.\n")

    def test_companion_not_reviewed_fails(self):
        # Regression: case02 docs/stage5/PARENT_RECORDS_v01.md was on the approval card but on no reviewer's list.
        r = self.copy()
        comp = self._companion(r)
        F.approve_finish(r, text=f"Approved: finish package as listed; companion {comp['path']} sha256 {comp['sha256']}")
        rec = self.assertFailsOn("G5", r, "review coverage")
        self.assertIn(comp["path"], self.check(rec, "Risk Reviewer numbers review coverage")["detail"])
        subj = [SG.CLAIMS] + list(F.DELIVERABLES) + [comp["path"]]
        F.review(r, SG.S5_REVIEWS[0], "second_designer", subj, [{"id": "SD5-01", "class": "advisory", "status": "open"}])
        F.review(r, SG.S5_REVIEWS[1], "risk_reviewer", subj, [{"id": "RR5-01", "class": "advisory", "status": "open"}])
        rec = run_gate("G5", r)
        self.assertEqual(rec["result"], "PASS", failed(rec))

    def test_companion_changed_after_declaration_fails(self):
        r = self.copy()
        comp = self._companion(r)
        self.edit_json(r, SG.CLAIMS, lambda d: d.update(companions=[comp]))
        F.wt(r, comp["path"], "edited after the ledger named it\n")
        self.assertFailsOn("G5P", r, "Companion files current")

    def test_companion_calling_open_finding_resolved_fails(self):
        r = self.copy()
        F.add_g4c_review(r, [{"id": "G4C-01", "class": "advisory", "status": "open"}])
        comp = F.wt(r, "docs/stage5/PARENT_RECORDS_v01.md", "Advisory G4C-01 is resolved.\n")
        self.edit_json(r, SG.CLAIMS, lambda d: d.update(companions=[comp]))
        rec = self.assertFailsOn("G5P", r, "Finding status words match the G4c review")
        self.assertIn("G4C-01 called resolved", self.check(rec, "Finding status words match the G4c review")["detail"])

    # A9: uncovered_claims and finding ids ------------------------------------------------------------------------
    def test_uncovered_claims_note_fails(self):
        r = self.copy()
        self.edit_json(r, SG.S5_REVIEWS[1], lambda d: d.update(uncovered_claims=["nothing uncovered"]))
        self.assertFailsOn("G5", r, "Stage 5 uncovered_claims are claim ids")

    def test_uncovered_claims_empty_or_ids_pass(self):
        for uc in ([], ["C1"]):
            with self.subTest(uc=uc):
                r = self.copy()
                self.edit_json(r, SG.S5_REVIEWS[1], lambda d: d.update(uncovered_claims=uc))
                self.assertEqual(self.check(run_gate("G5", r), "Stage 5 uncovered_claims are claim ids")["result"], "PASS")

    def test_same_finding_ids_in_both_reviews_fail(self):
        r = self.copy()
        for rel in S5:
            self.edit_json(r, rel, lambda d: d.update(findings=[{"id": "F5-02", "class": "advisory", "status": "open"}]))
        rec = self.assertFailsOn("G5", r, "Stage 5 finding ids distinct across reviews")
        self.assertIn("F5-02", self.check(rec, "Stage 5 finding ids distinct across reviews")["detail"])

    # A10: stale nested reference after the ledger moved -----------------------------------------------------------
    def test_g5p_stale_ref_after_claims_move(self):
        r = self.copy()
        old = F.ref(r, SG.CLAIMS)
        with open(os.path.join(r, SG.CLAIMS), encoding="utf-8") as fh:
            hist = F.wt(r, "artifacts/stage5/history/v01/stage5_claims.json", fh.read())
        rv = F.wj(r, "outputs/CASE-5-02/second_designer_inference_v01.json", {"role": "second_designer", "subjects": [old]})
        ops_rel = "artifacts/operations/finish.json"
        ops = F.rj(r, ops_rel) if os.path.exists(os.path.join(r, ops_rel)) else {"sends": []}
        ops.setdefault("sends", []).append({"id": "CASE-5-03", "attachments": [rv]})
        F.wj(r, ops_rel, ops)
        self.assertEqual(self.check(run_gate("G5P", r), "No stale nested references in the finish sends")["result"], "PASS")
        self.edit_json(r, SG.CLAIMS, lambda d: d.update(note="ledger replaced after the review"))  # the `claims` move
        rec = self.assertFailsOn("G5P", r, "No stale nested references in the finish sends")
        self.assertIn("CASE-5-03", self.check(rec, "No stale nested references in the finish sends")["detail"])
        sup = F.wj(r, "artifacts/stage5/h1_record_v01.json", {"historical_sent_fail": "CASE-5-03", "superseded_inputs": {SG.CLAIMS: hist}})
        F.wj(r, "artifacts/operations/finish.historical.json", {"historical_sends": [{"send_id": "CASE-5-03", "supersession": sup}]})
        self.assertEqual(self.check(run_gate("G5P", r), "No stale nested references in the finish sends")["result"], "PASS")


S5 = SG.S5_REVIEWS

if __name__ == "__main__":
    unittest.main()
