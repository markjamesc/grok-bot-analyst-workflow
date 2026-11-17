"""Tests for the live Stakeholder conversation in Stages 1 and 2 (gates/stakeholder.py, G1 and G2; docs/rules.md 31-36).

A good project (R-valid receipts + the synthetic captured conversations of fixture_project.add_live_stakeholder)
passes G1 and G2. Each planted failure copies it, plants one defect and asserts the named check FAILs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from gates import stakeholder as SH
from gates.run import run_gate
from gates.tests import fixture_project as F

PKG = F.PKG
REC1, REC2 = SH.record_rel("1"), SH.record_rel("2")
DEC, FRAME = "artifacts/stage1_decision.json", "artifacts/stage2_framing.json"


def failed(rec):
    return [c["check"] for c in rec["checks"] if c["result"] != "PASS"]


def _doc(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed to build R-valid receipts")
class LiveStakeholder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="grok-live-sh-")
        cls.base = os.path.join(cls.tmp, "base")
        F.build_r_project(cls.base, last=2)
        F.add_stage2(cls.base, os.path.join(cls.tmp, "pin"))
        cls.g1 = run_gate("G1", cls.base, record=False)
        cls.g2 = run_gate("G2", cls.base, record=False)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        LiveStakeholder.n += 1
        d = os.path.join(self.tmp, f"c{LiveStakeholder.n}")
        shutil.copytree(self.base, d, symlinks=True)
        return d

    def fails(self, gate, root, needle):
        rec = run_gate(gate, root, record=False)
        self.assertEqual(rec["result"], "FAIL", f"{gate} should FAIL")
        self.assertTrue([c for c in failed(rec) if needle in c], f"no failing check with {needle!r}: {failed(rec)}")
        return rec

    def check(self, rec, name):
        hit = [c for c in rec["checks"] if name in c["check"]]
        self.assertTrue(hit, f"no check {name!r}")
        return hit

    def edit(self, r, rel, fn):
        d = F.rj(r, rel)
        fn(d)
        F.wj(r, rel, d)

    def add_capture(self, r, stage, cid, who, ts, body):
        return SH.capture(r, stage, cid, who, ts, body.encode("utf-8"))

    # ------------------------------------------------------------------ good path
    def test_00_good_conversation_passes_g1_and_g2(self):
        for rec in (self.g1, self.g2):
            self.assertEqual(rec["result"], "PASS", failed(rec))
        names = [c["check"] for c in self.g1["checks"]]
        for n in ("Stage 1 chat: Stakeholder opened the case", "Decision document sources: every stakeholder statement cited is in a capture",
                  "Stage 1 owner lock: owner's own words (Stakeholder approval never counts)", "Agreed question written up"):
            self.assertIn(n, names)
        names2 = [c["check"] for c in self.g2["checks"]]
        for n in ("Stage 2 chat: Stakeholder took part", "Framing threshold traced to the brief or an owner capture",
                  "Stage 2 owner lock: owner's own words (Stakeholder approval never counts)"):
            self.assertIn(n, names2)
        caps = F.rj(self.base, REC1)["captures"]
        self.assertTrue(all(SH.is_readonly(os.path.join(self.base, c["path"])) for c in caps))

    # ------------------------------------------------------------------ G1: citations
    def test_g1_uncaptured_stakeholder_statement_cited(self):
        r = self.copy()
        self.edit(r, DEC, lambda d: d["sources"].append({"statement": "ST9", "use": "context"}))
        self.fails("G1", r, "every stakeholder statement cited is in a capture")

    def test_g1_cited_quote_not_in_capture(self):
        r = self.copy()
        self.edit(r, DEC, lambda d: d["sources"].append({"capture": "S1-M01", "quote": "we must reach 25 percent", "use": "context"}))
        self.fails("G1", r, "every stakeholder statement cited is in a capture")

    def test_g1_statement_not_in_its_capture(self):
        r = self.copy()
        self.edit(r, REC1, lambda d: d["statements"][1].update(quote="I want a weekly view"))
        self.fails("G1", r, "every statement is in its capture")

    def test_g1_sources_without_captures(self):
        r = self.copy()
        self.edit(r, DEC, lambda d: d.update(sources=[{"brief_quote": "Active customers only."}]))
        self.fails("G1", r, "cite the brief and the captures")

    def test_g1_brief_quote_not_in_brief(self):
        r = self.copy()
        self.edit(r, DEC, lambda d: d["sources"].append({"brief_quote": "Weekly reporting is required."}))
        self.fails("G1", r, "brief quotes are in the brief")

    # ------------------------------------------------------------------ G1: preference vs fact
    def test_g1_preference_cited_as_brief_fact(self):
        r = self.copy()
        self.edit(r, DEC, lambda d: d["sources"].__setitem__(2, {"statement": "ST2", "use": "fact"}))
        self.fails("G1", r, "no preference or chat remark used as a brief fact")

    def test_g1_preference_registered_as_brief_fact(self):
        r = self.copy()
        self.edit(r, REC1, lambda d: d["statements"][1].update(kind="brief_fact", brief_quote="Active customers only."))
        self.fails("G1", r, "a stakeholder preference is not a brief fact")

    def test_g1_brief_fact_without_brief_quote(self):
        r = self.copy()
        self.edit(r, REC1, lambda d: d["statements"][0].pop("brief_quote"))
        self.fails("G1", r, "brief facts quote the brief")

    # ------------------------------------------------------------------ G1: rule changes
    def test_g1_stakeholder_rule_change_without_owner(self):
        r = self.copy()
        self.add_capture(r, "1", "S1-M05", "stakeholder", "2026-11-09T09:04:00-06:00", "Let's use a threshold of 25 instead.")
        SH.statement(r, "1", "ST5", "S1-M05", "rule_change", "use a threshold of 25")
        self.fails("G1", r, "rule, threshold or definition changes need an owner capture")

    def test_g1_stakeholder_number_change_hidden_as_clarification(self):
        r = self.copy()
        self.add_capture(r, "1", "S1-M05", "stakeholder", "2026-11-09T09:04:00-06:00", "Let's use a threshold of 25 instead.")
        SH.statement(r, "1", "ST5", "S1-M05", "clarification", "use a threshold of 25")
        self.fails("G1", r, "stakeholder numbers traced to the brief")

    def test_g1_rule_change_authorised_by_owner_passes(self):
        r = self.copy()
        self.add_capture(r, "1", "S1-M05", "owner", "2026-11-09T09:04:00-06:00", "Twist: raise the bar to 25 this time.")
        self.add_capture(r, "1", "S1-M06", "stakeholder", "2026-11-09T09:04:30-06:00", "Understood, the owner moved it: a threshold of 25.")
        SH.statement(r, "1", "ST5", "S1-M06", "rule_change", "a threshold of 25", None, "S1-M05", "raise the bar to 25")
        rec = run_gate("G1", r, record=False)
        self.assertEqual(rec["result"], "PASS", failed(rec))

    def test_g1_rule_change_authorised_by_stakeholder_fails(self):
        r = self.copy()
        self.add_capture(r, "1", "S1-M05", "stakeholder", "2026-11-09T09:04:00-06:00", "I am changing the threshold to 25.")
        SH.statement(r, "1", "ST5", "S1-M05", "rule_change", "changing the threshold to 25", None, "S1-M01", "I run customer growth")
        self.fails("G1", r, "rule, threshold or definition changes need an owner capture")

    # ------------------------------------------------------------------ G1: locks
    def test_g1_stakeholder_approval_is_not_a_lock(self):
        r = self.copy()
        self.edit(r, SH.lock_rel("1"), lambda d: d.update(capture="S1-M01", quote="Hi, I run customer growth."))
        self.fails("G1", r, "owner's own words (Stakeholder approval never counts)")

    def test_g1_lock_tool_refuses_stakeholder_capture(self):
        r = self.copy()
        os.remove(os.path.join(r, SH.lock_rel("1")))
        with self.assertRaises(SH.Refused):
            SH.lock(r, "1", "S1-M01", "Hi, I run customer growth.")

    def test_g1_lock_is_for_an_older_decision_document(self):
        r = self.copy()
        self.edit(r, DEC, lambda d: d["limits"].append("late edit"))
        self.fails("G1", r, "Stage 1 owner lock: for the current")

    def test_g1_lock_negated(self):
        r = self.copy()
        self.add_capture(r, "1", "S1-M05", "owner", "2026-11-09T09:06:00-06:00", "Don't lock it yet.")
        self.edit(r, SH.lock_rel("1"), lambda d: d.update(capture="S1-M05", quote="Don't lock it yet."))
        self.fails("G1", r, "plain lock words")

    def test_g1_lock_before_the_messages_it_relies_on(self):
        r = self.copy()
        self.add_capture(r, "1", "S1-M00", "owner", "2026-11-09T08:00:00-06:00", "Lock it.")
        self.edit(r, SH.lock_rel("1"), lambda d: d.update(capture="S1-M00", quote="Lock it."))
        self.fails("G1", r, "after every message it relies on")

    def test_g1_lock_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, SH.lock_rel("1")))
        self.fails("G1", r, "Stage 1 owner lock")

    # ------------------------------------------------------------------ G1: captures
    def test_g1_no_conversation_record(self):
        r = self.copy()
        os.remove(os.path.join(r, REC1))
        self.fails("G1", r, "conversation captured")

    def test_g1_capture_edited_after_capture(self):
        r = self.copy()
        p = os.path.join(r, "captures/stage1_chat/S1-M03.txt")
        os.chmod(p, 0o644)
        with open(p, "a") as fh:
            fh.write(" Also use 25.")
        os.chmod(p, 0o444)
        self.fails("G1", r, "capture hashes generated from the files")

    def test_g1_capture_left_writable(self):
        r = self.copy()
        os.chmod(os.path.join(r, "captures/stage1_chat/S1-M01.txt"), 0o644)
        self.fails("G1", r, "captures read-only")

    def test_g1_hand_typed_hash(self):
        r = self.copy()
        self.edit(r, REC1, lambda d: d["captures"][0].update(sha256="a" * 64))
        self.fails("G1", r, "capture hashes generated from the files")

    def test_g1_sha256sums_missing_a_capture(self):
        r = self.copy()
        p = os.path.join(r, "captures/stage1_chat/SHA256SUMS")
        os.chmod(p, 0o644)
        with open(p) as fh:
            lines = fh.read().splitlines(True)
        with open(p, "w") as fh:
            fh.write("".join(lines[1:]))
        self.fails("G1", r, "SHA256SUMS lists every capture")

    def test_g1_header_speaker_mismatch(self):
        r = self.copy()
        self.edit(r, REC1, lambda d: d["captures"][3].update(speaker="stakeholder"))
        self.fails("G1", r, "capture headers match the record")

    def test_g1_stakeholder_isolation_breach(self):
        r = self.copy()
        F.wt(r, "private_keys/key.md", "synthetic\n")
        self.edit(r, REC1, lambda d: d["stakeholder_inputs"].append(F.ref(r, "private_keys/key.md")))
        self.fails("G1", r, "Stakeholder reads only the brief and the persona")

    def test_g1_init_refuses_forbidden_persona_path(self):
        r = self.copy()
        os.remove(os.path.join(r, REC1))
        F.wt(r, "scoring/persona.md", "synthetic\n")
        with self.assertRaises(SH.Refused):
            SH.init(r, "1", "inputs/public/brief.md", "scoring/persona.md")

    def test_g1_live_record_with_mock_captures(self):
        r = self.copy()
        self.edit(r, REC1, lambda d: d.update(run_kind="rehearsal"))
        self.fails("G1", r, "rehearsal mocks never count as live")

    def test_g1_opening_not_by_stakeholder(self):
        r = self.copy()
        self.edit(r, REC1, lambda d: d.update(opening="S1-M04"))
        self.fails("G1", r, "Stakeholder opened the case")

    def test_g1_agreed_question_missing(self):
        r = self.copy()
        self.edit(r, DEC, lambda d: d.pop("agreed_question"))
        self.fails("G1", r, "Agreed question written up")

    # ------------------------------------------------------------------ G2
    def test_g2_framing_cites_uncaptured_statement(self):
        r = self.copy()
        self.edit(r, FRAME, lambda d: d["sources"].append({"statement": "ST9", "use": "clarification"}))
        self.fails("G2", r, "Framing sources: every stakeholder statement cited is in a capture")

    def test_g2_framing_preference_as_fact(self):
        r = self.copy()
        self.edit(r, FRAME, lambda d: d["sources"].append({"statement": "ST2", "use": "fact"}))
        self.fails("G2", r, "no preference or chat remark used as a brief fact")

    def test_g2_threshold_not_traced(self):
        r = self.copy()
        self.edit(r, FRAME, lambda d: d.update(threshold=25))
        self.fails("G2", r, "Framing threshold traced to the brief or an owner capture")

    def test_g2_threshold_traced_through_owner_rule_change(self):
        r = self.copy()
        self.add_capture(r, "2", "S2-M03", "owner", "2026-11-09T10:06:00-06:00", "Change the threshold to 25.")
        SH.statement(r, "2", "ST6", "S2-M03", "rule_change", "Change the threshold to 25.")
        self.edit(r, FRAME, lambda d: d.update(threshold=25))
        rec = run_gate("G2", r, record=False)
        self.assertEqual([c["result"] for c in self.check(rec, "Framing threshold traced")], ["PASS"])

    def test_g2_stakeholder_approval_is_not_a_lock(self):
        r = self.copy()
        self.edit(r, SH.lock_rel("2"), lambda d: d.update(capture="S2-M01", quote="The framing reads clearly"))
        self.fails("G2", r, "Stage 2 owner lock: owner's own words (Stakeholder approval never counts)")

    def test_g2_no_stakeholder_in_stage2_chat(self):
        r = self.copy()
        self.edit(r, REC2, lambda d: d["captures"][0].update(speaker="lead"))
        self.fails("G2", r, "Stage 2 chat: Stakeholder took part")

    def test_g2_stage2_conversation_missing(self):
        r = self.copy()
        os.remove(os.path.join(r, REC2))
        self.fails("G2", r, "Stage 2 chat: conversation captured")

    # ------------------------------------------------------------------ CLI
    def test_cli_capture_is_write_once_and_rehearsal_needs_label(self):
        r = self.copy()
        t = os.path.join(self.tmp, f"chat{LiveStakeholder.n}.txt")
        with open(t, "w") as fh:
            fh.write("Exact chat text.")
        cmd = [sys.executable, "-m", "gates.stakeholder", "capture", r, "--stage", "1", "--id", "S1-M01", "--speaker",
               "stakeholder", "--timestamp", "2026-11-09T09:00:00-06:00", "--text-file", t]
        p = subprocess.run(cmd, cwd=PKG, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("write-once", p.stdout)
        cmd[cmd.index("S1-M01")] = "S1-M09"
        p = subprocess.run(cmd, cwd=PKG, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(json.loads(p.stdout)["capture"]["sha256"], F.sha(os.path.join(r, "captures/stage1_chat/S1-M09.txt")))
        self.edit(r, REC1, lambda d: d.update(run_kind="rehearsal"))
        cmd[cmd.index("S1-M09")] = "S1-M10"
        p = subprocess.run(cmd, cwd=PKG, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout)

    def test_statement_tool_refuses_quote_not_in_capture(self):
        r = self.copy()
        with self.assertRaises(SH.Refused):
            SH.statement(r, "1", "ST7", "S1-M01", "clarification", "a sentence nobody said")


class LiveStakeholderDocs(unittest.TestCase):
    def test_docs_describe_the_live_stakeholder(self):
        self.assertTrue(os.path.isfile(os.path.join(PKG, "docs/roles/stakeholder.md")))
        role = _doc("docs/roles/stakeholder.md")
        for s in ("public brief", "persona", "never", "lock"):
            self.assertIn(s, role)
        rules = _doc("docs/rules.md")
        for s in ("Stakeholder reads only", "preference is not a fact", "Stakeholder approval is never a lock"):
            self.assertIn(s, rules)
        stages = _doc("docs/stages.md")
        self.assertIn("Freeze counts restart at zero", stages)
        self.assertIn("python3 -m gates.stakeholder capture", _doc("docs/handoff.md"))
        self.assertIn("stakeholder.md", _doc("docs/roles/README.md"))


if __name__ == "__main__":
    unittest.main()
