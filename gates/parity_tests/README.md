# Parity tests (R referee vs Python port)

`python3 -m gates.parity_tests.run_parity --r-repo <ai-augmented-analyst-workflow checkout> [--only test_x.R ...]`

1. Copies the R repo to a scratch rig (the R repo is never modified).
2. Prepends one line to each R test script in the rig: `source("gates/parity_tests/r_prelude.R")`. Nothing else changes,
   and each R suite must still pass.
3. The prelude shadows R's `system2`, `source` and `sys.source`:
   - every `workflow_gate.R` / `procedure_gate.R` call: the project is snapshotted, the Python port runs first on that
     state, the project is restored, then R runs; status, exit code and the full check list (name, result, detail) are
     compared;
   - every outermost call of `m_design`, `m_execution`, `m_ai`, `m_finish`, `m_change`, `m_operations`,
     `m_checkpoint_contract`, `m_operational_design`, `m_validation`, `m_source`, `m_inventory`, `m_review_subjects`,
     `m_compare`, `m_ref_ok`, `m_refs_ok`, `m_historical`, `m_equal_ids`, `m_missing_rule` and `validate_stage_receipt`:
     the type-tagged R arguments are passed to the Python function and the results compared.
4. Every comparison is one JSON line in `<out>/<suite>.parity.jsonl`; `<out>/summary.json` has per-suite counts.

Details are compared exactly, except the text of an R error message inside "Methodology well-formed contract" and
"... parses" FAIL checks (the verdict and check name are still compared).

Suites: test_workflow_gate.R (21 workflow-gate runs incl. 17 planted defects), test_procedure_gate.R (incl. 23 refused
amendments), test_historical_sends.R, test_methodology.R, test_targeted_gates.R, test_acceptance.R, test_livefix.R,
test_remediation.R, test_successor.R. `tools/tests/test_planted_defects.R` is not a gate test (it needs a builder-pair
project) and is not run.

`gates/tests/test_parity.py` runs this harness (workflow suite by default; `GATES_RUN_PARITY=full` for all suites).
