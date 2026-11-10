"""Large-output assembly + GP assembly-regression gate (regression harness for the large-output assembler)."""
from __future__ import annotations

import json
import os


def _rb(p):
    with open(p, "rb") as fh:
        return fh.read()
import shutil
import tempfile
import unittest

from gates import assembly
from gates.run import run_gate
from gates.tests import fixture_project as F

SPLIT = "operator/W_split.json"


class Assembly(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="asm-")
        F.add_assembly(self.d)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def reply(self, n, text):
        F.wt(self.d, f"transcripts/W{n}_reply.md", text)

    def part1(self, obj, marker="ANSWERED W-1", fence="```json"):
        self.reply(1, f"Part 1\n{fence}\n" + json.dumps(obj) + "\n```\n" + marker + "\n")

    P1 = {"part": 1, "header": {"covered_tables": ["t1"]}, "case_expected": {
        "c1": {"fixture_id": "F1", "tables": {"t1": [1]}}, "c2": {"fixture_id": "F1", "tables": {"t1": [2]}}}}

    def assertRefused(self, needle):
        rep = assembly.assemble(self.d, SPLIT)
        self.assertEqual(rep["result"], "FAIL")
        self.assertTrue(any(needle in e for e in rep["errors"]), rep["errors"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "docs/W_whole.json")), "nothing may be written on failure")

    def test_good(self):
        rep = assembly.assemble(self.d, SPLIT)
        self.assertEqual(rep["result"], "ASSEMBLED", rep["errors"])
        whole = F.rj(self.d, "docs/W_whole.json")
        self.assertEqual(list(whole["case_expected"]), ["c1", "c2", "c3"])
        log = F.rj(self.d, "evidence/W_transform_log.json")
        self.assertEqual(len(log["part_files"]), 2)
        self.assertEqual(log["output"]["sha256"], F.sha(os.path.join(self.d, "docs/W_whole.json")))
        for pf in log["part_files"]:
            src = _rb(os.path.join(self.d, pf["source"]["path"]))
            s, e = pf["byte_range"]
            self.assertEqual(src[s:e], _rb(os.path.join(self.d, pf["path"])), "byte-exact extraction")

    def test_rerun_refuses_overwrite(self):
        self.assertEqual(assembly.assemble(self.d, SPLIT)["result"], "ASSEMBLED")
        before = F.sha(os.path.join(self.d, "docs/W_whole.json"))
        rep = assembly.assemble(self.d, SPLIT)
        self.assertEqual(rep["result"], "FAIL")
        self.assertTrue(any("refusing to overwrite" in e for e in rep["errors"]))
        self.assertEqual(before, F.sha(os.path.join(self.d, "docs/W_whole.json")))

    def test_deterministic(self):
        other = tempfile.mkdtemp(prefix="asm2-")
        try:
            F.add_assembly(other)
            assembly.assemble(self.d, SPLIT)
            assembly.assemble(other, SPLIT)
            self.assertEqual(F.sha(os.path.join(self.d, "docs/W_whole.json")), F.sha(os.path.join(other, "docs/W_whole.json")))
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_report_only_writes_nothing(self):
        rep = assembly.assemble(self.d, SPLIT, report_only=True)
        self.assertEqual(rep["result"], "REPORT_ONLY_OK")
        self.assertFalse(os.path.exists(os.path.join(self.d, "docs/W_whole.json")))
        self.assertFalse(os.path.exists(os.path.join(self.d, "evidence/W_transform_log.json")))

    def test_duplicate_case(self):
        p2 = {"part": 2, "case_expected": {"c3": {"fixture_id": "F2", "tables": {"t1": [3]}}, "c1": {"fixture_id": "F1", "tables": {"t1": [1]}}}}
        self.reply(2, "```json\n" + json.dumps(p2) + "\n```\nANSWERED W-2\n")
        self.assertRefused("duplicate item ids across parts")

    def test_bad_marker(self):
        self.part1(self.P1, marker="ANSWERED W-9")
        self.assertRefused("last line is not ANSWERED W-1")

    def test_missing_case(self):
        p = json.loads(json.dumps(self.P1)); p["case_expected"].pop("c2")
        self.part1(p)
        self.assertRefused("missing ['c2']")

    def test_missing_covered_table(self):
        p = json.loads(json.dumps(self.P1)); p["case_expected"]["c2"]["tables"] = {"t9": []}
        self.part1(p)
        self.assertRefused("c2 lacks covered")

    def test_wrong_part_number(self):
        p = dict(self.P1, part=2)
        self.part1(p)
        self.assertRefused('"part" is 2, expected 1')

    def test_missing_reply(self):
        os.remove(os.path.join(self.d, "transcripts/W2_reply.md"))
        self.assertRefused("part 2: reply missing")

    def test_two_fenced_blocks(self):
        self.reply(1, "```json\n{}\n```\n```json\n" + json.dumps(self.P1) + "\n```\nANSWERED W-1\n")
        self.assertRefused("exactly one fenced block")

    def test_duplicate_json_keys(self):
        self.reply(1, '```json\n{"part": 1, "part": 1, "header": {"covered_tables": ["t1"]}, "case_expected": {}}\n```\nANSWERED W-1\n')
        self.assertRefused("duplicate keys")

    def test_unexpected_top_level_key(self):
        self.part1(dict(self.P1, notes="extra"))
        self.assertRefused("unexpected top-level keys")

    def test_split_omits_declared_item(self):
        sp = F.rj(self.d, SPLIT); sp["expected_ids"].append("c4"); F.wj(self.d, SPLIT, sp)
        self.assertRefused("partition expected_ids")

    def test_item_missing_required_field(self):
        p = json.loads(json.dumps(self.P1)); p["case_expected"]["c1"].pop("fixture_id")
        self.part1(p)
        self.assertRefused("c1 lacks required fields")

    # ------------------------------------------------------------------ GP gate
    def test_gp_good(self):
        assembly.assemble(self.d, SPLIT)
        rec = run_gate("GP", self.d)
        self.assertEqual(rec["result"], "PASS", [c for c in rec["checks"] if c["result"] != "PASS"])

    def test_gp_not_assembled(self):
        self.assertEqual(run_gate("GP", self.d)["result"], "FAIL")

    def test_gp_tampered_output(self):
        assembly.assemble(self.d, SPLIT)
        p = os.path.join(self.d, "docs/W_whole.json")
        data = F.rj(self.d, "docs/W_whole.json"); data["case_expected"].pop("c3")
        os.chmod(p, 0o644)
        with open(p, "w") as fh:
            json.dump(data, fh, indent=2)
        rec = run_gate("GP", self.d)
        self.assertEqual(rec["result"], "FAIL")
        bad = [c["check"] for c in rec["checks"] if c["result"] != "PASS"]
        self.assertTrue(any("output matches log" in c for c in bad) and any("re-assembly equals output" in c for c in bad), bad)

    def test_gp_reply_changed_after_assembly(self):
        assembly.assemble(self.d, SPLIT)
        p = json.loads(json.dumps(self.P1)); p["case_expected"]["c1"]["tables"]["t1"] = [99]
        self.part1(p)
        rec = run_gate("GP", self.d)
        self.assertEqual(rec["result"], "FAIL")
        self.assertTrue(any("re-assembly equals output" in c["check"] for c in rec["checks"] if c["result"] != "PASS"))

    def test_gp_part_file_deleted(self):
        assembly.assemble(self.d, SPLIT)
        os.remove(os.path.join(self.d, "artifacts/parts/W/part_2.json"))
        rec = run_gate("GP", self.d)
        self.assertEqual(rec["result"], "FAIL")
        self.assertTrue(any("part files current" in c["check"] for c in rec["checks"] if c["result"] != "PASS"))

    def test_gp_index_missing(self):
        assembly.assemble(self.d, SPLIT)
        os.remove(os.path.join(self.d, "artifacts/assembly/index.json"))
        self.assertEqual(run_gate("GP", self.d)["result"], "FAIL")

    def test_gp_explicit_no_assemblies(self):
        F.wj(self.d, "artifacts/assembly/index.json", {"assemblies": []})
        self.assertEqual(run_gate("GP", self.d)["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
