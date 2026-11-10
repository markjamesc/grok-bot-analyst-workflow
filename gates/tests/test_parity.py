"""R vs Python parity: runs the R repo's own gate test suites with every gate call shadowed by the Python port
(gates/parity_tests/r_prelude.R + gates/parity_tests/runner.py) and requires zero mismatches.

Default: the Workflow Gate suite only (about 30 s). GATES_RUN_PARITY=full runs every suite (about 4 min).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from gates.tests import fixture_project as F

PKG = F.PKG


@unittest.skipUnless(F.r_available(), "Rscript and the R repo (GATES_R_REPO) are needed for parity")
class Parity(unittest.TestCase):
    def test_parity(self):
        out = tempfile.mkdtemp(prefix="gates-parity-")
        cmd = [sys.executable, "-m", "gates.parity_tests.run_parity", "--r-repo", F.r_repo(), "--out", out, "--rscript", F.rscript()]
        if os.environ.get("GATES_RUN_PARITY") != "full":
            cmd += ["--only", "test_workflow_gate.R"]
        env = dict(os.environ, PATH=os.path.dirname(F.rscript()) + os.pathsep + os.environ.get("PATH", ""))
        p = subprocess.run(cmd, cwd=PKG, capture_output=True, text=True, env=env)
        summary = json.load(open(os.path.join(out, "summary.json")))
        for name, s in summary.items():
            with self.subTest(suite=name):
                self.assertEqual(s["r_exit"], 0, f"R suite failed with the prelude: {s['r_tail']}")
                self.assertGreater(s["comparisons"], 0)
                self.assertEqual(s["mismatches"], 0, json.dumps(s["by"]))
        self.assertIn("PARITY PASS", p.stdout, p.stdout[-2000:] + p.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
