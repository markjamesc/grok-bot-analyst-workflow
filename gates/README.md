# Gates (Python, parent-owned)

Analysis stays in R. Only the gates and checks are Python (standard library only; no pandas or pyyaml needed).
Every gate returns **PASS**, **FAIL** or **TOOL_ERROR**. An unrun gate is not PASS, and a gate with missing input never PASSes.

**Draft status (2026-11-09, uncommitted working tree).** Tested means: covered by `gates/tests` (fault injection),
and, where an R gate exists, by R-vs-Python parity on the R repo's own test suites. Gates without tests are
**NOT IMPLEMENTED**.

| ID | Status | Module | R checks inside (parity-tested port) | Tests |
|---|---|---|---|---|
| G0 Packet integrity | **NOT IMPLEMENTED** | — | — | — |
| G1 Decision | Implemented, tested | `stage_gates.g1` | R `complete start` checks (validate_stage_receipt + operations ledger + closure) | good path + 5 faults |
| G2 Question lock | Implemented, tested | `stage_gates.g2` | R `complete framing` checks | good path + 6 faults |
| G2F Feasibility | Implemented, tested | `stage_gates.g2f` | none (no R equivalent) | good path + 6 faults |
| G3S SQL source-gate runner | Implemented, tested (sqlite engine only) | `stage_gates.g3s`, `sql_select_only` | none (no R equivalent) | good path + 6 faults + authorizer + TOOL_ERROR |
| G3K Early key/count checks | Implemented, tested | `stage_gates.g3k`, `repair` | none (no R equivalent) | good path + 4 faults + 3 repair-cap tests |
| G3 Design lock | Implemented, tested | `stage_gates.g3` | R `complete design` checks (incl. m_design, m_ai) | good path + 7 faults |
| G4a Fixtures | Implemented, tested | `stage_gates.g4a`, `reconcile` | ported R m_compare run on every pair | good path + 3 faults |
| G4b Reconciliation | Implemented, tested | `stage_gates.g4b`, `reconcile` | ported R m_compare run on every pair | good path + 8 tests |
| G4c Post-reconciliation review | Implemented, tested | `stage_gates.g4c` | none (no R equivalent) | good path + 3 faults |
| G4d Release | Implemented, tested | `stage_gates.g4d` | R `complete execution` checks + the whole ported R Workflow Gate | good path + 5 faults |
| G5 Claims | **NOT IMPLEMENTED** | — | — | — |
| G6 Certificate | **NOT IMPLEMENTED** as a Grok gate (the R `finalize` port exists in `procedure.py`) | — | — | — |
| GP Assembly regression | Implemented, tested | `gp_assembly`, `assembly` | none | 16 assembly + 6 GP tests |
| Repair cap (3, then ESCALATE) | Implemented, tested | `repair` | — | in G3K/G4d tests |
| R Workflow Gate port | Implemented, parity-tested | `workflow_gate.py` (+ `methodology.py`, `rsem.py`) | all | 27 whole-gate + 1,200+ function-level parity comparisons |
| R Procedure Gate port (procedure-followed check) | Implemented, parity-tested except `successor` | `procedure.py` | all | 77 whole-command parity comparisons |

## Run

```
python3 -m gates.run <GATE_ID> <project_root>        # exit 0 PASS, 1 FAIL, 2 TOOL_ERROR; writes artifacts/gates/<ID>.json
python3 -m gates.workflow_gate <project_root> [--dry-run]
GATES_FRAMEWORK_ROOT=<R repo> python3 -m gates.procedure start|begin|complete|status|finalize|amend|successor <root> ...
python3 -m gates.assembly <project_root> <split.json> [--report-only]
python3 -m unittest discover -s gates/tests -t .     # GATES_R_REPO=<R repo>; GATES_RUN_PARITY=full for all R suites
```

Each run writes `artifacts/gates/<ID>.json` (current verdict, with the path and sha256 of every input) and a write-once
copy under `artifacts/gates/history/`. A later gate accepts a lower gate only if its record is PASS **and every recorded
input still has the recorded hash** ("PASS by hash").

## Inputs (project-relative)

| Gate | Files |
|---|---|
| G1 | `artifacts/stage1_decision.json` (R Stage 1 receipt plus `actions_per_result` [>=2 {result, action}], `limits` [text]); `artifacts/workflow_pin.json` {base, commit, files[{path, sha256}]}; R `artifacts/operations/start.json` |
| G2 | `artifacts/stage2_framing.json` (R Stage 2 receipt plus one `analytical_question`/`question_id`, `population`, `window` {start, end}, `metric`, `threshold`, `review_subjects`); `artifacts/stage2/reviews/second_designer_critique.json`, `risk_reviewer_framing_check.json` |
| G2F | `artifacts/stage2f_feasibility.json` {questions[{question_id, feasibility yes/partly/no, reason, structure[], quality[]}], owner_decision if partly/no}; `artifacts/stage2f/reviews/risk_reviewer_feasibility.json`; current G2 record |
| G3S | `artifacts/stage3/source_gates/manifest.json` {database {engine: sqlite, snapshot {path, sha256}}, gates[{id, check, sql {path, sha256}}]}; each query returns violating rows (PASS = 0 rows); results written write-once under `artifacts/stage3/source_gates/results/` |
| G3K | `artifacts/stage3_grok_design.json` `early_checks` {keys[{id, table, columns}], counts[{id, table, expected_rows}]}; `artifacts/repairs.json` |
| G3 | R `artifacts/stage3_locked_design.json`; `artifacts/stage3_grok_design.json` {fixtures, reconciliation, early_checks, review_subjects}; reviews `artifacts/stage3/reviews/{second_designer_compare, risk_reviewer_red_team, risk_reviewer_source_gates}.json`; `artifacts/stage3_owner_approval.json` {design_sha256, grok_design_sha256, approval_text, approval_timestamp}; current G3S and G3K records |
| G4a/G4b | `artifacts/stage4/outputs.json` {outputs {ra, rb, sql: {name: {path, sha256}}}, fixtures {ra, rb, sql: {fixture_id: {path, sha256}}}} |
| G4c | `artifacts/stage4/reviews/risk_reviewer_g4c.json` covering the current G4b record and every reconciled output |
| G4d | every lower gate record; `artifacts/repairs.json`; R `artifacts/stage4_validation_status.json` and Stage 4 evidence (the ported Workflow Gate) |
| GP | `artifacts/assembly/index.json` {assemblies[{split}]}; split specs, replies, part files, outputs and transform logs |

A review record is {role, subjects[{path, sha256}], findings[{id, class must_fix|advisory, status open|closed}]}. It counts
only if every current subject is listed at the same path with the current hash; an open must-fix blocks the gate.

## Rules each gate enforces

- **G4b:** exact full-field match between R-A, R-B and SQL (all three pairs). Every column, compared as the text R's
  `read.csv(colClasses = "character")` reads (no trimming), keyed by the design keys; row order is ignored. A numeric
  tolerance applies only to columns the locked design lists under `tolerance.fields`. The ported R `m_compare` runs on
  every pair as well, so G4b is never looser than the R comparison. Mismatch count must be 0.
- **G3S:** SELECT-only by static lint (one statement, SELECT/WITH, no write/DDL/session keyword outside quotes and
  comments; conservative, so a bare identifier such as `comment` or `set` must be quoted) **and** by execution on a
  read-only, immutable sqlite connection with `query_only` and an authorizer that denies all but reads. Engines other
  than sqlite need an executor passed to `g3s(root, executor=...)`; without one the gate is TOOL_ERROR.
- **G2F:** structure and quality only: whitelisted keys, flat entries, forbidden value-like keys
  (values, samples, min, max, mean, rows, answer_key, ...), no mention of the answer key, no new or missing questions.
- **Repair cap:** three unsuccessful repairs of the same defect id, then ESCALATED; a fourth attempt is refused; a change
  of author does not reset the count. An escalated or open defect fails G3K (for G3K/G3S defects), G4b (G4a/G4b) and G4d (all).

## Parity with the R referee

See [parity_tests/README.md](parity_tests/README.md). The R repo's own suites (workflow gate, procedure gate, historical
sends, methodology, targeted gates, acceptance, livefix, remediation, successor) are run unchanged, with every
`workflow_gate.R` / `procedure_gate.R` invocation and every outermost methodology contract call also run by the Python
port on the same state. Last full run: 9 suites, R all green, 1,254 comparisons, 0 mismatches.

Known gaps: the `successor` command is not exercised through the CLI by the R suites (no parity evidence for it);
the certificate's `certificate_sha256` is SHA-256 of canonical JSON, not R's `digest()` of the R object; inventory
order uses byte order (R uses the locale; identical in the C/UTF-8 locale the suites ran in); wording of R/Python
error messages differs (verdicts and check lists are identical).

## Production note

The R-equivalent checks inside G1, G2, G3 and G4d require the R receipts and operations ledgers with their existing
field names (for example `ai2_independent_reconstruction`, `ai3_independent_red_team`) and the R Stage 4 evidence layout.
Grok runs must produce those files, or the owner must approve a Grok-specific mapping. Weakening them is not allowed.
