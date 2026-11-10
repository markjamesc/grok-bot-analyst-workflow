# Gates (Python, parent-owned)

Analysis stays in R. Only the gates and checks are Python (standard library only; no pandas or pyyaml needed).
Every gate returns **PASS**, **FAIL** or **TOOL_ERROR**. An unrun gate is not PASS, and a gate with missing input never PASSes.

**Status (2026-11-10).** Every gate below is implemented and tested. Tested means: covered by `gates/tests` (good path
plus planted-defect fault injection) and, where an R gate exists, by R-vs-Python parity on the R repo's own test suites
and on the gate fixtures.

| ID | Status | Module | R checks inside (parity-tested port) | Tests |
|---|---|---|---|---|
| G0 Packet integrity | Implemented, tested | `packet.g0` | none (no R counterpart: the R gate has no packet format) | good path + 17 faults |
| G1 Decision | Implemented, tested | `stage_gates.g1` | R `complete start` checks (validate_stage_receipt + operations ledger + closure) | good path + 5 faults |
| G2 Question lock | Implemented, tested | `stage_gates.g2` | R `complete framing` checks | good path + 6 faults |
| G2F Feasibility | Implemented, tested | `stage_gates.g2f` | none (no R equivalent) | good path + 6 faults |
| G3S SQL source-gate runner | Implemented, tested (sqlite engine only) | `stage_gates.g3s`, `sql_select_only` | none (no R equivalent) | good path + 6 faults + authorizer + TOOL_ERROR |
| G3K Early key/count checks | Implemented, tested | `stage_gates.g3k`, `repair` | none (no R equivalent) | good path + 4 faults + 3 repair-cap tests |
| G3 Design lock | Implemented, tested | `stage_gates.g3` | R `complete design` checks (incl. m_design, m_ai) | good path + 7 faults |
| G4a Fixtures | Implemented, tested | `stage_gates.g4a`, `reconcile` | ported R m_compare run on every pair | good path + 3 faults |
| G4b Reconciliation | Implemented, tested | `stage_gates.g4b`, `reconcile` | ported R m_compare run on every pair | good path + 8 tests |
| G4c Post-reconciliation review | Implemented, tested | `stage_gates.g4c` | none (no R equivalent) | good path + 3 faults |
| G4d Release | Implemented, tested | `stage_gates.g4d` | R `complete execution` checks + the whole ported R Workflow Gate | good path + 6 faults + R-report kept |
| G5 Claims | Implemented, tested | `stage_gates.g5` | R `complete finish` checks (validate_stage_receipt incl. m_finish claim ledger and m_ai, operations ledger, closure) | good path + 12 faults; R stage-check parity |
| G6 Certificate | Implemented, tested | `stage_gates.g6` | requires the R `finalize` certificate (ported in `procedure.py`) and re-checks every hash it recorded | good path + 10 faults; R vs Python `finalize` verdict parity |
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
| G4d | every lower gate record; `artifacts/repairs.json`; R `artifacts/stage4_validation_status.json` and Stage 4 evidence (the ported Workflow Gate). If R `artifacts/procedure/run_state.json` records a Workflow Gate report, G4d does not overwrite it and requires it unchanged |
| G0 | `artifacts/packets/index.json` {packets[{id, path, status draft/sent/answered, sha256 (once sent), reply {path, sha256} (once answered)}], forbidden_strings?, forbidden_path_prefixes? (`private/` always applies)}; each packet in the [handoff format](../docs/handoff.md); each reply ends with `PRODUCED FILES:` + `- <path>` lines, then `ANSWERED <PACKET_ID>` |
| G5 | R `artifacts/stage5_interpretation_status.json`; `artifacts/stage5_claims.json` {deliverables[{path, sha256}], claims[{id, type, deliverable, quote, evidence[{path, sha256}], derived?[{value, basis}]}]}; reviews `artifacts/stage5/reviews/{second_designer_inference, risk_reviewer_numbers}.json`; current G4d record |
| G6 | every gate record G0–G5; `artifacts/stage5_owner_approval.json` {claims_sha256, deliverables[{path, sha256}], approval_text, approval_timestamp}; R `artifacts/final_certificate.json` and `artifacts/procedure/run_state.json`; writes `artifacts/gates/G6.json` (the Grok certificate) |
| GP | `artifacts/assembly/index.json` {assemblies[{split}]}; split specs, replies, part files, outputs and transform logs |

A review record is {role, subjects[{path, sha256}], findings[{id, class must_fix|advisory, status open|closed}]}. It counts
only if every current subject is listed at the same path with the current hash; an open must-fix blocks the gate.

## Rules each gate enforces

- **G0:** run before every send and after every capture. A sent packet is sealed (hash must not change). Inputs are
  `- <path> sha256=<hash> bytes=<n> [part k of K]` and must be whole and current. No input under `private/` or a
  declared forbidden prefix, and no answer-key file. No `TEMPLATE`, `{{placeholder}}` or handoff-format `<...>`
  placeholder. A `-vN` correction (N >= 2) names what it SUPERSEDES. An answered packet has a sealed reply ending
  `ANSWERED <PACKET_ID>` with a non-blank produced-files list covering every EXPECTED OUTPUT; a file on disk alone
  leaves the packet unanswered, and G6 refuses unanswered packets.
- **G5:** sealed evidence means an input of a current PASS gate record G1–G4d, or that record itself. Every number in a
  claim quote must appear in that claim's evidence or be declared under `derived` with its basis (for the Risk
  Reviewer's recomputation). Claim types must sit within the locked design's `allowed_claim_types`.
- **G6:** each gate ran after the gates it depends on (record timestamps); every lower record is PASS by hash; the
  owner approved the exact claims ledger and deliverable hashes; the R certificate is PASS and certified, and its
  completed-stage artifacts, deliverables, evidence inventory and Workflow Gate report hashes are still current.

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

Stage-check parity (`gates/tests/test_finish_gates.py`): the R checks inside G1, G2, G3, G4d and G5 are compared
one-for-one (name and verdict) with the R repo's own `validate_stage_receipt`, `m_operations` and `step_closure`
(`parity_tests/r_stage_checks.R`), on an R-certified project and on planted defects; and the Python `finalize` port and
R `finalize` give the same verdict and failing checks on the same state.

Known gaps: the `successor` command is not exercised through the CLI by the R suites (no parity evidence for it);
the certificate's `certificate_sha256` is SHA-256 of canonical JSON, not R's `digest()` of the R object; inventory
order uses byte order (R uses the locale; identical in the C/UTF-8 locale the suites ran in); wording of R/Python
error messages differs (verdicts and check lists are identical).

## Production note

Run order at the end of a run: R `complete execution` → G4d → G5 → owner approval of the exact finish package →
R `complete finish` and `finalize` → G0 (final) → G6. G4d never overwrites a report the R Procedure Gate recorded.
PASS by hash is one level deep: a gate record stays current while its own recorded inputs are unchanged, so G6
re-checks every lower record directly.

The R-equivalent checks inside G1, G2, G3 and G4d require the R receipts and operations ledgers with their existing
field names (for example `ai2_independent_reconstruction`, `ai3_independent_red_team`) and the R Stage 4 evidence layout.
Grok runs must produce those files, or the owner must approve a Grok-specific mapping. Weakening them is not allowed.
