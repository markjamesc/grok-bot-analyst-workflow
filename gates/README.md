# Gates (Python, run by the Gate Runner)

Analysis stays in R. Only the gates and checks are Python (standard library only; no pandas or pyyaml needed).
Every gate returns **PASS**, **FAIL** or **TOOL_ERROR**. An unrun gate is not PASS, and a gate with missing input never PASSes.

**Status (2026-11-10).** Every gate below is implemented and tested. Tested means: covered by `gates/tests` (good path
plus planted-defect fault injection) and, where an R gate exists, by R-vs-Python parity on the R repo's own test suites
and on the gate fixtures.

| ID | Status | Module | R checks inside (parity-tested port) | Tests |
|---|---|---|---|---|
| G0 Packet integrity | Implemented, tested | `packet.g0` | none (no R counterpart: the R gate has no packet format) | good path + 17 faults + supersession (3), template-input and derivability (2) tests + captured/promote (5) and "MISSING INPUT: none." (2) tests (`test_case03_changes.py`); exact-ledger G5P precheck (7) tests (`test_sunday_changes.py`) |
| GD Public-file derivability | Implemented, tested | `derivability.gd` (also run inside G0) | none (no R counterpart) | Case-C-style regression + 2 faults + nothing-raised path |
| G1 Decision | Implemented, tested | `stage_gates.g1` | R `complete start` checks (validate_stage_receipt + operations ledger + closure) | good path + 5 faults |
| G2 Question lock | Implemented, tested | `stage_gates.g2` | R `complete framing` checks | good path + 6 faults; Stage 2 conversation checks (`test_live_stakeholder.py`) |
| Live Stakeholder conversation (inside G1 and G2) | Implemented, tested | `stakeholder` (checks and the capture tool) | none (no R equivalent) | good path + planted failures and tool refusals (`test_live_stakeholder.py`) |
| G2F Feasibility | Implemented, tested | `stage_gates.g2f` | none (no R equivalent) | good path + 6 faults |
| G3S SQL source-gate runner | Implemented, tested (sqlite engine only) | `stage_gates.g3s`, `sql_select_only` | none (no R equivalent) | good path + 6 faults + authorizer + TOOL_ERROR; snapshot identity and binding (7) tests (`test_sunday_changes.py`) |
| G3K Early key/count checks | Implemented, tested | `stage_gates.g3k`, `repair` | none (no R equivalent) | good path + 4 faults + 3 repair-cap tests |
| G3 Design lock | Implemented, tested | `stage_gates.g3` | R `complete design` checks (incl. m_design, m_ai) | good path + 7 faults + template-placeholder and descriptive-rate tests (4) + next-stage entry (3), version (3), threshold-field (2) and exposure (1) tests (`test_case03_changes.py`); decision-flip fixture (3) and rounding-tolerance (3) tests (`test_sunday_changes.py`) |
| G4a Fixtures | Implemented, tested | `stage_gates.g4a`, `reconcile` | ported R m_compare run on every pair | good path + 3 faults; Stage 4 snapshot bound to G3S (2) tests (`test_sunday_changes.py`) |
| G4b Reconciliation | Implemented, tested | `stage_gates.g4b`, `reconcile` | ported R m_compare run on every pair | good path + 8 tests |
| G4c Post-reconciliation review | Implemented, tested | `stage_gates.g4c` | none (no R equivalent) | good path + 3 faults |
| G4d Release | Implemented, tested | `stage_gates.g4d` | R `complete execution` checks + the whole ported R Workflow Gate | good path + 6 faults + R-report kept |
| G5 Claims | Implemented, tested | `stage_gates.g5` | R `complete finish` checks (validate_stage_receipt incl. m_finish claim ledger and m_ai, operations ledger, closure) | good path + 12 faults; R stage-check parity; companion (2), status-word and triage (4), uncovered_claims and finding-id (3) tests (`test_case03_changes.py`) |
| G5P Stage 5 precheck | Implemented, tested | `stage_gates.g5p` | none (runs exactly the G5 claim and content checks; no R or review checks) | mirror test + unplaced-ledger, CSV, path, threshold and hold tests (`test_case02_changes.py`); companion, status-word and stale-reference tests (`test_case03_changes.py`) |
| G6 Certificate | Implemented, tested | `stage_gates.g6` | requires the R `finalize` certificate (ported in `procedure.py`) and re-checks every hash it recorded | good path + 10 faults; R vs Python `finalize` verdict parity |
| Stage close check | Implemented, tested | `close.close_check` (`python3 -m gates.close`) | none (reads recorded verdicts) | certified-base PASS + G3 FAIL refused + changed input + missing record + CLI exit codes (`test_case03_changes.py`) |
| GP Assembly regression | Implemented, tested | `gp_assembly`, `assembly` | none | 16 assembly + 6 GP tests |
| Repair cap (3, then ESCALATE) | Implemented, tested | `repair` | — | in G3K/G4d tests |
| Gate attempts (attempt ids, every outcome recorded) | Implemented, tested | `attempt`, `run` | none | 10 attempt tests + TOOL_ERROR-retry chain test (`test_sunday_changes.py`) |
| R Workflow Gate port | Implemented, parity-tested | `workflow_gate.py` (+ `methodology.py`, `rsem.py`) | all | 27 whole-gate + 1,200+ function-level parity comparisons |
| R Procedure Gate port (procedure-followed check) | Implemented, parity-tested except `successor` | `procedure.py` | all | 77 whole-command parity comparisons |

## Run

```
python3 -m gates.run <GATE_ID> <project_root> [--attempt=<id>]  # exit 0 PASS, 1 FAIL, 2 TOOL_ERROR; writes artifacts/gates/<ID>.json
python3 -m gates.attempt <GATE_ID> <project_root> <attempt id>  # exit 0 only if that attempt PASSed and is still the current record
python3 -m gates.run G5P <project_root> --ledger=<claims json>   # precheck any ledger before review or placement
python3 -m gates.close <CLOSING_GATE> <project_root>  # exit 0 only if the stage may be sealed closed (G1 G2 G2F G3 G4d G5 G6)
python3 -m gates.packet promote <project_root> <packet id>   # captured -> answered, only on a G0 PASS
python3 -m gates.stakeholder init|capture|statement|lock <project_root> --stage 1|2 ...   # live Stakeholder chat (docs/handoff.md)
python3 -m gates.workflow_gate <project_root> [--dry-run]
GATES_FRAMEWORK_ROOT=<R repo> python3 -m gates.procedure start|begin|complete|status|finalize|amend|successor <root> ...
python3 -m gates.assembly <project_root> <split.json> [--report-only]
python3 -m unittest discover -s gates/tests -t .     # GATES_R_REPO=<R repo>; GATES_RUN_PARITY=full for all R suites
```

Each run writes `artifacts/gates/<ID>.json` (current verdict, with the path and sha256 of every input) and a write-once
copy under `artifacts/gates/history/`. A later gate accepts a lower gate only if its record is PASS **and every recorded
input still has the recorded hash** ("PASS by hash").

**Attempts (known fix 1).** Every run has an attempt id (`--attempt=<id>`, or generated) and, when recorded, its outcome is
written once to `artifacts/gates/attempts/<id>.json` {attempt_id, gate, result, checked_at_utc, record_sha256}, TOOL_ERROR
included. A TOOL_ERROR also replaces the current record, so a failed retry never leaves an older PASS current. A reused
attempt id is refused. The coordinating role advances only when `python3 -m gates.attempt` exits 0 for the attempt it asked for.

## Inputs (project-relative)

| Gate | Files |
|---|---|
| G1 | `artifacts/stage1_decision.json` (R Stage 1 receipt plus `actions_per_result` [>=2 {result, action}], `limits` [text]); `artifacts/workflow_pin.json` {base, commit, files[{path, sha256}]}; R `artifacts/operations/start.json`; Stage 1 receipt also `agreed_question` and `sources` [{brief_quote} or {statement, use} or {capture, quote, use}]; `artifacts/stage1/conversation.json` {stage, run_kind live/rehearsal, brief, persona, stakeholder_inputs, capture_dir, captures[{id, speaker stakeholder/owner/lead, timestamp, path, sha256}], opening, statements[{id, capture, kind, quote, brief_quote?, authorized_by?}]}; `captures/stage1_chat/<id>.txt` + `SHA256SUMS`; `artifacts/stage1_owner_lock.json` {stage, subject {path, sha256}, conversation, capture, quote} |
| G2 | `artifacts/stage2_framing.json` (R Stage 2 receipt plus one `analytical_question`/`question_id`, `population`, `window` {start, end}, `metric`, `threshold`, `review_subjects`); `artifacts/stage2/reviews/second_designer_critique.json`, `risk_reviewer_framing_check.json`; framing `sources`; the Stage 1 record and `artifacts/stage2/conversation.json` with `captures/stage2_chat/`; `artifacts/stage2_owner_lock.json` |
| G2F | `artifacts/stage2f_feasibility.json` {questions[{question_id, feasibility yes/partly/no, reason, structure[], quality[]}], owner_decision if partly/no}; `artifacts/stage2f/reviews/risk_reviewer_feasibility.json`; current G2 record |
| G3S | `artifacts/stage3/source_gates/manifest.json` {database {engine: sqlite, snapshot {id, path, sha256}}, gates[{id, check, sql {path, sha256}}]}; the record keeps `snapshot` {id, sha256, path}; each query returns violating rows (PASS = 0 rows); results written write-once under `artifacts/stage3/source_gates/results/` |
| G3K | `artifacts/stage3_grok_design.json` `early_checks` {keys[{id, table, columns}], counts[{id, table, expected_rows}]}; `artifacts/repairs.json` |
| G3 | R `artifacts/stage3_locked_design.json`; `artifacts/stage3_grok_design.json` {fixtures, reconciliation (tolerance {fields, absolute_tolerance, relative_tolerance, rounding_reason}), early_checks, decision_flip_fixtures[{kind threshold_boundary/pooling/missing_values/duplicate_join, fixture + flips, or not_applicable}], review_subjects}; reviews `artifacts/stage3/reviews/{second_designer_compare, risk_reviewer_red_team, risk_reviewer_source_gates}.json`; `artifacts/stage3_owner_approval.json` {design_sha256, grok_design_sha256, approval_text, approval_timestamp}; current G3S and G3K records |
| G4a/G4b | `artifacts/stage4/outputs.json` {snapshot {id, sha256, path}, outputs {ra, rb, sql: {name: {path, sha256}}}, fixtures {ra, rb, sql: {fixture_id: {path, sha256}}}}; the current G3S record |
| G4c | `artifacts/stage4/reviews/risk_reviewer_g4c.json` covering the current G4b record and every reconciled output |
| G4d | every lower gate record; `artifacts/repairs.json`; R `artifacts/stage4_validation_status.json` and Stage 4 evidence (the ported Workflow Gate). If R `artifacts/procedure/run_state.json` records a Workflow Gate report, G4d does not overwrite it and requires it unchanged |
| GD | `artifacts/derivability.json` {public_sources[{path, sha256}], items[{id, stage, raised_in, item, search_terms, derivable, derivation + derived_from + resolution `continued` (derivable) or not_derivable_reason + escalated_at + resolution `escalated_to_owner` + term_hits_reviewed[{path, why_not_derivable}] (not derivable)}]}; the `MISSING INPUT:` lines of sealed replies in the packet index. See `gates/derivability.py` |
| G0 | `artifacts/packets/index.json` {packets[{id, path, status draft/sent/answered, sha256 (once sent), reply {path, sha256} (once answered), superseded_by?, superseded_reason?, superseded_at?}], forbidden_strings?, forbidden_path_prefixes? (`private/` always applies)}; each packet in the [handoff format](../docs/handoff.md); each reply ends with `PRODUCED FILES:` + `- <path>` lines, then `ANSWERED <PACKET_ID>` |
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
  leaves the packet unanswered, and G6 refuses unanswered packets. A row marked `superseded_by` (a packet in the index,
  no cycle) with `superseded_reason` and an ISO `superseded_at` keeps its sealed hash but is not content-checked or
  counted (reported in `superseded`). No input may be a template `*.example.json` or a JSON file holding placeholder
  references (all-zero or `NOT_SET` hashes), followed through referenced JSON files (`gates/guards.py`). Every
  `MISSING INPUT:` line in a sealed reply must pass the GD derivability checks. A Stage 5 Second Designer or Risk Reviewer
  packet must list a G5P record written by the runner (bytes equal to an `artifacts/gates/history/G5P-*.json` copy) whose
  result is PASS, whose `ledger` {path, sha256} is an input of the same packet at that hash, and whose inputs are unchanged.
- **GD:** a stop on a missing input or mapping counts only after a check of the public files: public sources current
  and not private or an answer key; a derivable item records its derivation and `derived_from` and continues; a
  non-derivable item is escalated to the owner with a reason and time, and explains each public file that mentions one
  of its search terms. Otherwise it is treated as derivable.
- **G3 (design lock):** no template placeholder reference in the design files, their review subjects, or JSON files
  they reference (the R `finalize` evidence closure would fail on them later), and no blanket ban on descriptive rates.
- **G5:** sealed evidence means an input of a current PASS gate record G1–G4d, or that record itself. Every number in a
  claim quote must appear in that claim's evidence or be declared under `derived` with its basis (for the Risk
  Reviewer's recomputation). Claim types must sit within the locked design's `allowed_claim_types`. A claim whose quote
  states a rate or difference (`%`, percent, points) is descriptive or associational and says so in `label` or the quote.
- **G6:** each gate ran after the gates it depends on (record timestamps); every lower record is PASS by hash; the
  owner approved the exact claims ledger and deliverable hashes; the R certificate is PASS and certified, and its
  completed-stage artifacts, deliverables, evidence inventory and Workflow Gate report hashes are still current.

- **G4b:** exact full-field match between R-A, R-B and SQL (all three pairs). Every column, compared as the text R's
  `read.csv(colClasses = "character")` reads (no trimming), keyed by the design keys; row order is ignored. A numeric
  tolerance applies only to columns the locked design lists under `tolerance.fields`. The ported R `m_compare` runs on
  every pair as well, so G4b is never looser than the R comparison. Mismatch count must be 0. G3 accepts a non-zero
  tolerance only with a `rounding_reason` (fields where rounding legitimately differs); every other field is exact.
- **G4a/G4b snapshot binding:** `outputs.json` `snapshot` {id, sha256} must equal the snapshot recorded by the current G3S
  PASS (and its file, when a path is given, must be current). Snapshot B after a G3S PASS on snapshot A fails until G3S
  is run on B. G4a compares every implementation with the fixtures' worked answers even when they agree with each other.
- **G3S:** SELECT-only by static lint (one statement, SELECT/WITH, no write/DDL/session keyword outside quotes and
  comments; conservative, so a bare identifier such as `comment` or `set` must be quoted) **and** by execution on a
  read-only, immutable sqlite connection with `query_only` and an authorizer that denies all but reads. Engines other
  than sqlite need an executor (the Database Connector) passed to `g3s(root, executor=...)`; without one the gate is
  TOOL_ERROR. The executor returns `(columns, rows, total, opened)` where `opened` is `{id, sha256}` of the snapshot it
  actually opened; the built-in sqlite connector hashes the file it opens. Each query FAILs on `<id>: connector opened the
  requested snapshot` unless `opened` equals the manifest's snapshot id and sha256, even with zero violating rows; a
  connector that reports no identity fails the same check. Each result row keeps `opened_snapshot`.
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

Run order at the end of a run: R `complete execution` → G4d → G5P → Stage 5 reviews → then the finish order
owner approves the exact finish package -> R `complete finish` -> G5 -> R `finalize` -> G6
(G0 is run again before G6). G4d never overwrites a report the R Procedure Gate recorded.
PASS by hash is one level deep: a gate record stays current while its own recorded inputs are unchanged, so G6
re-checks every lower record directly.

The R-equivalent checks inside G1, G2, G3 and G4d require the R receipts and operations ledgers with their existing
field names (for example `ai2_independent_reconstruction`, `ai3_independent_red_team`) and the R Stage 4 evidence layout.
Grok runs must produce those files, or the owner must approve a Grok-specific mapping. Weakening them is not allowed.

## Case02 changes (0.3.0)

- **G3** also checks: every Stage 3 field the R Workflow Gate reads at G4d is present in the locked design
  (`workflow_gate_field_gaps`); `decision_thresholds` [{id, value, statement}] in the Grok design; any `owner_holds`
  {decision_output {output, impl?, final_action_field, rule_action_fields[], hold_values[]}, holds [{id, owner_source, statement}]}.
- **G4c** also checks `artifacts/stage4/corrections.json` when present (each entry: id, path of the new version, optional old_path, old_sha256, new_sha256 = current
  file, author_role, reason, logged_at) and adds the log to the review subjects. No file: PASS "no corrections logged".
- **G5** reads CSV/TSV evidence cell by cell (`evidence_numbers`), checks each claim's `deliverable` is in the ledger, that every
  decision threshold appears as its number and id on one deliverable line, and that every row whose final action is a hold value
  is reported on one line with the rule's action values and a hold id. The hold itself is not removed or overridden.
- **G5P** = the same claim and content checks (`claim_checks`, `finish_content_checks`) on any ledger; used before each Stage 5
  review packet and before placement. **G0** fails a Stage 5 Second Designer or Risk Reviewer packet without a precheck log input.


## 2026-11-22 changes (0.6.0)

- **Attempt ids (`gates/attempt.py`, `gates/run.py`).** Every outcome is recorded per attempt, TOOL_ERROR included; a TOOL_ERROR
  becomes the current record; `python3 -m gates.attempt` passes only for a PASS of the requested attempt that is still current.
- **Snapshot binding (G3S, G4a, G4b).** G3S needs a snapshot `id` and records {id, sha256, path}; G4a/G4b fail when
  `outputs.json` `snapshot` is not that exact snapshot, and they list the G3S record as an input.
- **Precheck by record (G0, G5P).** G5P records the exact `ledger` it checked; G0 accepts only a runner-written G5P PASS for
  the ledger in the same packet.
- **Finish order** stated the same way here, in docs/stages.md, docs/gates.md and the parent role.
- **G3:** `decision_flip_fixtures` (Stage 3) and rounding-only tolerances (Stage 4).
- Tests: `gates/tests/test_sunday_changes.py`. The base fixtures now carry a snapshot id, the Stage 4 snapshot and the
  decision-flip declarations, so every existing good path still passes.

## Repair round 1 (2026-11-22, after outside review of 3faeb07)

- **G3S checks the snapshot actually opened.** The connector returns the identity of the snapshot it opened with every
  result; G3S FAILs a query whose opened snapshot is not the requested one, even when all checks return zero rows.
- **G5P binds every report it reviewed.** The G5P record lists `deliverables` [{path, sha256}] (deliverables and companions)
  and adds them to its inputs; G0 rejects a Stage 5 review packet whose G5P record lacks them or whose reports changed after
  G5P. G5 and G6 already refuse a report changed after G5 (tested).
- **Exact-threshold fixture.** The base fixture's customer c3 totals exactly 10 (TH1: expand only above 10) and the summary
  carries the decision, so an implementation using >= 10 fails G4a against the worked answer and G4b against its peers.
- **Operational roles.** Gate runs, captures, seals and closes belong to the Gate Runner, read-only SQL execution to the
  Database Connector, and stage advancement to the Coordinator (docs/roles/).
- Tests: `gates/tests/test_sunday_fixes_r1.py`.

## Repair round 2 (2026-11-22, after the independent review of 9035ebd)

- **The sqlite connector queries the bytes it hashed.** It copies the snapshot to a private directory, hashes the copy and
  opens that copy; the path is fully percent-encoded in the URI (a `%42` file name is no longer read as `B`).
- **G0: the review packet carries exactly the prechecked package.** The precheck must be the current G5P record (a later G5P
  run, PASS or FAIL, supersedes it); every deliverable G5P recorded must be an input at its recorded hash; every other input
  must be part of the prechecked package (ledger, deliverables, G5P inputs) at the recorded hash.
- **G5P records only bytes it checked:** the ledger, deliverables and companions are hashed before the checks and must be
  unchanged at the end (`Reviewed files unchanged while G5P ran`).
- **G6 depends on everything the chain depended on:** it lists the inputs of every chain record and the companions, so a
  recorded G6 attempt is no longer accepted after a report or companion changes.
- **Attempt check reads the current record once** and judges that record's attempt id, hash and inputs together.
- **Finish order enforced:** G5 requires the exact-package owner approval and R finish completion no earlier than it; G6
  requires owner approval <= R finish completion <= G5 <= R finalization (`Finish steps in the documented order`).
  Test fixtures now approve before G5 and rerun R `finalize` after G5.
- Not changed (design changes, see CHANGELOG 0.6.2): signed or out-of-band gate records; execution records that bind each
  Stage 4 output to the snapshot it was computed from; companions in the R certificate (R repo).
- Tests: `gates/tests/test_sunday_fixes_r2.py`.

## Repair round 3 (2026-11-22, after the independent review of 584ad98)

- **G5P hashes the ledger before parsing it**, so the recorded ledger hash is the hash of the ledger it checked.
- **G0 and later G5P runs:** G0 records `artifacts/gates/G5P.json` as an input, so a later G5P run makes the G0 record (and
  therefore G6) stale until G0 runs again. An attached precheck still counts when the current G5P record is a PASS for the
  same ledger and the same reports (a rerun on unchanged bytes for the second reviewer); a later FAIL still rejects it.
- **G5 refuses an R finish completion recorded later than G5 itself** (`R finish step completed before G5`).
- Docs: the G1 check, Stakeholder-chat captures and sealing of the Second Designer's design are the Gate Runner's.
- Tests: `gates/tests/test_sunday_fixes_r3.py`.
