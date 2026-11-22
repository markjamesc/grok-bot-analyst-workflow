# Changelog

All notable changes to this design draft are recorded here. Dates are America/Chicago.

## 0.6.3 — 2026-11-22 (repair round 3)

Fixes for results an independent review reproduced on 0.6.2 (584ad98). Lessons L43–L46.

- **G5P** hashes the ledger before parsing it.
- **G0** records the current G5P record as an input (a later G5P run makes G0, and so G6, stale) and accepts an attached precheck when the current G5P record is a PASS for the same ledger and reports.
- **G5** refuses an R finish completion recorded later than G5.
- **Docs:** remaining G1, capture and sealing instructions assigned to the Gate Runner.
- Tests: `gates/tests/test_sunday_fixes_r3.py`.

## 0.6.2 — 2026-11-22 (repair round 2)

Fixes for false passes an independent review reproduced on 0.6.1 (9035ebd). Lessons L37–L42.

- **G3S / sqlite connector:** queries a private copy whose hash it reports; the URI path is fully percent-encoded.
- **G0:** a Stage 5 review packet must carry the current G5P record and exactly the prechecked package (no unchecked ledger or report; no prechecked report omitted).
- **G5P:** fails when a reviewed file changes while it runs.
- **G6:** records the inputs of every chain gate and the companions, so an old G6 attempt goes stale when any of them changes.
- **Attempt check:** one read of the current record.
- **Finish order enforced** in G5 and G6 from the recorded times; test fixtures approve before G5 and rerun R `finalize` after G5.
- **Docs:** the G1 check, SQL execution and sealing of first answers are assigned to the Gate Runner and Database Connector everywhere.
- Positive Stage 5 review-packet tests now attach every prechecked report (the reviewer covers the whole package).
- Open (design changes, not made): records an actor with write access to `artifacts/gates/` could fabricate (needs signed or out-of-band records); Stage 4 outputs computed from another snapshot but declared as the checked one (needs execution records binding outputs to the snapshot used); companions in the R final certificate (R repo).
- Tests: `gates/tests/test_sunday_fixes_r2.py`.

## 0.6.1 — 2026-11-22 (repair round 1)

Fixes for the false passes an outside review reproduced on 0.6.0 (3faeb07). Lessons L33–L36.

- **G3S verifies the snapshot the connector actually opened** (id and sha256 returned with every result); a clean result on another snapshot FAILs.
- **G5P records every deliverable and companion it reviewed**, as `deliverables` and as inputs; G0 rejects a Stage 5 review packet whose reports changed after G5P.
- **Exact-threshold fixture:** customer c3 totals exactly 10 and the summary carries the decision; a >= 10 implementation fails G4a and G4b.
- **Operational roles** (docs/roles/coordinator.md, gate-runner.md, database-connector.md): gate runs, captures, seals and closes belong to the Gate Runner, read-only SQL execution to the Database Connector, stage advancement on a PASS for the requested attempt to the Coordinator. The README role table no longer names a bot.
- Tests: `gates/tests/test_sunday_fixes_r1.py`; base fixture data and the tests that quote it updated.

## 0.6.0 — 2026-11-22

Owner-approved workflow changes: the four known fixes and the stage refinements, inside the existing roles and gates (lessons L29–L32; standing rules 37–44). Not adopted: feasibility before the Stage 2 lock, a model-family switch, the 750-run benchmark.

- **Attempt ids (new `gates/attempt.py`; `gates/run.py`).** Every gate run has an attempt id; every recorded outcome, TOOL_ERROR included, is written once to `artifacts/gates/attempts/<id>.json`, and a TOOL_ERROR becomes the current record. `python3 -m gates.attempt <GATE> <root> <id>` exits 0 only for a PASS of that attempt that is still current. A reused id is refused.
- **Snapshot binding (G3S, G4a, G4b).** The G3S manifest names the snapshot by `id` and `sha256`, recorded in the G3S result; `artifacts/stage4/outputs.json` names the snapshot Stage 4 ran on, and G4a/G4b fail unless it is the one the current G3S PASS checked.
- **Precheck by record (G0, G5P).** G5P records the exact `ledger`; a Stage 5 review packet must carry a runner-written G5P PASS for the ledger in the same packet, with unchanged inputs. A file named "precheck" no longer passes.
- **Finish order** aligned in docs/stages.md (summary table), gates/README.md, docs/gates.md and the parent role: owner approves the exact finish package -> R `complete finish` -> G5 -> R `finalize` -> G6.
- **G3:** `decision_flip_fixtures` for the exact threshold, pooling, missing values and duplicate joins; a non-zero tolerance needs `rounding_reason`.
- **Process (role text and docs/judgment_checks.md v03):** Stage 1 keep-current and wait/defer options and no presupposed conclusion; the two Stage 2 review questions; Stage 4 known answers even when the implementations agree; Stage 5 best justified action with no change as an option and causal claims stated separately; checkable reviewer tasks; first independent answers kept; three separate claims; light review-cost log.
- Tests: `gates/tests/test_sunday_changes.py` (35 tests); `test_case02_changes.py` precheck test updated (a file name alone now fails). Base fixtures carry the snapshot id, the Stage 4 snapshot and decision-flip declarations.

## 0.5.0 — 2026-11-16 (draft, not merged)

Owner-approved process change: a live Stakeholder for Stages 1 and 2 (lesson L28). Stages 3, 4 and 5 are unchanged.

- **Stakeholder role (new, docs/roles/stakeholder.md).** Plays the business person in a group chat with the owner and the parent, in Stages 1 and 2 only. Reads only the public brief and a persona the parent writes from it. Never approves a lock, never changes a rule, never does the analysis. Standing rule 32.
- **Stage 1 and Stage 2 run as a conversation.** The Stakeholder opens, the parent asks clarifying questions, the owner weighs in or adds twists; the Lead Designer writes the decision document (`agreed_question`) and the framing from the brief and the captures; the owner locks each in his own words (docs/stages.md).
- **Exact captures (new tool `python3 -m gates.stakeholder`).** init, capture, statement, lock. One write-once, read-only file per message under `captures/stage<N>_chat/`, sha256 from the file, `SHA256SUMS` regenerated from the files, conversation record `artifacts/stage<N>/conversation.json`, owner locks `artifacts/stage<N>_owner_lock.json` bound to the exact decision-document or framing hash. Standing rule 31.
- **G1 and G2 check the conversation.** Capture integrity, Stakeholder isolation, Stakeholder opening/participation, statements in captures, preference never a brief fact, rule/threshold/definition changes only with an owner capture, Stakeholder numbers traced to the brief, `sources` citing the brief and the captures, framing threshold traced, owner-only locks (Stakeholder approval never counts). Standing rules 33–35.
- **Freeze counts restart at zero** with the first case run this way (standing rule 36).
- Tests: `gates/tests/test_live_stakeholder.py`. The base fixtures now carry a synthetic captured conversation, so every existing good path still passes.

## 0.4.0 — 2026-11-16

Process changes from the fourth head-to-head case (no case content or answers). Lessons L21–L27 in docs/lessons.md.

- **Stage close check (new, `gates/close.py`).** `python3 -m gates.close <closing gate> <root>` exits 0 only if the closing gate, every gate it depends on and G0 are PASS with current inputs, and no packet is sent but unanswered or captured but not promoted. A FAIL can no longer be sealed as closed. Standing rule 25.
- **Captured replies (G0).** New packet status `captured`: every reply and derivability check runs, but the packet stays unanswered (and is listed in `captured`) until `python3 -m gates.packet promote <root> <id>` moves it to `answered` on a G0 PASS. Standing rule 26.
- **Next stage's entry check at lock (G3).** Each fixture's worked answer is compared with itself by the G4a compare, every tolerance must have the G4a/G4b shape (no bare number), and output keys must be non-blank. Standing rule 27.
- **Design version check (G3).** Versioned docs/stage3 files named by the locked design (deliverables, stage_records) must carry the design version (fixtures: the fixture version).
- **Derivability.** `MISSING INPUT: none.` (any case, with or without a full stop) is not a missing input.
- **Stage 5 companions and status words (G5P, G5).** Companion files (declared in the ledger or approval `companions`, or `companion <path> sha256 <hash>` in the approval text) must be current and are review subjects of both Stage 5 reviews. A report or companion that calls an open G4c finding resolved/closed/fixed fails, and every finding the Stage 4 triage disposes of as carried must be carried. Standing rule 28.
- **Stage 5 review records (G5).** `uncovered_claims` is `[]` or claim ids; the two reviews may not share a finding id (role prefixes SD5-, RR5-, X5-). Standing rule 29.
- **Stale nested references (G3, G5P, G5).** A `{path, sha256}` inside a sent JSON attachment that no longer matches must be resolved by an H1 historical-send record with an archived copy. Standing rule 30.
- **Docs and code agree.** Thresholds accept `number` or `value` (both must agree when given); exposure sentences ("has been computed or seen") and `methodology.exposure` / `results_seen` are not read as rate bans; the owner_holds shape is in the Lead Designer role; the Stage 1 review mapping and the real Stage 5 order are in docs/stages.md, docs/gates.md and the reviewer roles.
- Tests: `gates/tests/test_case03_changes.py` (47 tests). The base fixture's Stage 5 reviews now use role-prefixed ids.

## 0.3.0 — 2026-11-15

Process changes from the third head-to-head case (no case content or answers). Lessons L14–L20 in docs/lessons.md.

- **G3 lock completeness.** G3 fails a locked design missing any Stage 3 field the R Workflow Gate reads at G4d (`ml_mode`, `fixture_version`, `fixture_ids`, `reconciliation_critical_fields`, `ranking_contract` under a hard attention budget, and the required core fields). G3 also requires `decision_thresholds` [{id, value, statement}] in the Grok design, and checks any `owner_holds` for an owner source and a decision output that keeps the rule's action beside the hold.
- **G5 evidence numbers.** CSV/TSV evidence is read cell by cell; a row such as `x,6,3,0.5` no longer reads as one number.
- **G5P precheck (new).** Runs exactly the G5 claim and content checks on any ledger (`ledger=`), before review and placement. G0 fails a Stage 5 Second Designer or Risk Reviewer packet that does not carry a precheck log.
- **Per-claim deliverable check.** G5/G5P fail a claim whose `deliverable` is not one of the ledger's deliverables.
- **Builder corrections log.** G4c checks `artifacts/stage4/corrections.json` (when present): each entry has old/new hash (new = current file), role, reason and time, and the log is a subject of the G4c review. Replaces unlock/re-freeze.
- **Report content.** G5/G5P require each decision threshold as a number with its id on one deliverable line, and a triggered owner hold reported on the same line as the rule's action values and the hold id. The owner's stop test is unchanged; only its reporting is checked.
- Docs: standing rules 18–24, stage notes, handoff additions, role text for all child roles and the parent. Fixture design declares `TH1`; the fixture decision deliverable states it.

## 0.2.1 — 2026-11-10

Process fixes from the second head-to-head case (no case content or answers). Lessons in docs/lessons.md.

- **Public-file derivability check (new GD, also inside G0).** A role may stop on a missing input or mapping only after the public schema, brief and bundle files were checked. A reply that stops writes `MISSING INPUT: <item>`; a reply that settled it writes `DERIVED: <item> from <path>: <how>` and continues. The parent records each check in `artifacts/derivability.json`. GD/G0 fail an unchecked stop, a derivable item that did not continue, and a "not derivable" item when a public file mentions its search terms and the record does not explain why that file does not settle it. Only non-derivable items are escalated to the owner.
- **Labeled descriptive rates allowed and expected.** New standing rule. G3 fails a design that bans rates or differences outright (a sentence that only restricts causal wording is fine). G5 fails a claim that states a rate or difference without a descriptive/associational label.
- **Template placeholder references rejected early.** G0 rejects a packet input that is a template `*.example.json` or a JSON file holding placeholder references (all-zero or `NOT_SET` hashes), and G3 rejects them anywhere in the design files and the JSON files they reference, with a message naming the fix. Before this, only R `finalize` (evidence dependency closure) caught them, at the end of the run.
- **Supersession in G0.** A packet row may be marked `superseded_by` (a packet in the index, no cycle), `superseded_reason` and `superseded_at`. It keeps its sealed hash but is no longer content-checked or counted as unanswered, so a replaced packet no longer blocks G6.
- New module `gates/guards.py` (shared checks) and `gates/derivability.py`; regression tests in `gates/tests/test_finish_gates.py` and `gates/tests/test_stage_gates.py`. No R gate logic changed, so R-vs-Python parity is unaffected.

## 0.2.0 — 2026-11-10

- Implemented and tested **G0 packet integrity** (`gates/packet.py`): every packet in `artifacts/packets/index.json` must keep its sealed hash once sent, carry every handoff field, list whole current inputs (hash and byte count, every part of a split input), take nothing from a forbidden or answer-key path, name the answer key under NOT ALLOWED TO SEE, contain no `TEMPLATE` text or unfilled placeholders, and require `ANSWERED <PACKET_ID>`. An answered packet needs a sealed reply whose last line is `ANSWERED <PACKET_ID>` and whose produced-files list is not blank and covers every expected output. A file on disk is not a completed send.
- Implemented and tested **G5 claims**: the R `complete finish` checks (including the R claim ledger), plus a claims ledger in which every claim is quoted verbatim from a deliverable, sits within the locked claim ceiling, is tied to evidence sealed by a current PASS gate, and has every number traced to that evidence or a declared derivation; Second Designer and Risk Reviewer reviews must cover the current ledger and deliverables.
- Implemented and tested **G6 certificate**: G0–G5 all PASS and current, in dependency order; every packet answered; owner approval of the exact finish package; and the R Procedure Gate `finalize` certificate, with every hash it recorded still current. The G6 record is the Grok certificate.
- G4d no longer overwrites a Workflow Gate report that the R Procedure Gate already recorded. It recomputes every check and requires that report unchanged.
- New R-certified test fixture built with the R Procedure Gate CLI; R parity of the stage checks inside G1/G2/G3/G4d/G5 and of the `finalize` verdict.
- Process corrections from the Case B head-to-head run: re-review the current file after a repair before its gate; children must reply to the parent and end with a produced-files list and `ANSWERED <PACKET_ID>`; never send a template; Stage 5 order G5 → owner finish approval → R `finalize` → G6; the first framing states the capacity/loss rule and the decision unit. New lessons L5–L9.

## 0.1.4 — 2026-11-10

- Added the Python gates and R-vs-Python parity tests. Implemented and tested: G1, G2, G2F, G3S (SQLite engine only), G3K, G3, G4a, G4b, G4c, G4d and GP (assembly regression), plus the repair cap (3, then escalate). G1, G2, G3 and G4d include ported R stage checks, and G4d includes the whole ported R Workflow Gate; those ports pass parity on the R repo's own test suites.
- G0 (packet integrity), G5 (claims) and G6 (certificate) were not yet implemented at 0.1.4; they were added in 0.2.0.
- Removed the gate skeleton stub (`gates/gate_stub.py`). The test suite now requires `GATES_R_REPO` and an `Rscript` on `PATH`, and fails clearly if either is missing. Added a `.gitignore` for Python cache files.

## 0.1.3 — 2026-11-09

- Expanded the Risk Reviewer to Stages 2, 3, 4, and 5: Stage 2 framing check (alongside the Second Designer) and G2F review; Stage 3 design red-team and SQL source-gate review; Stage 4 post-reconciliation evidence review (new G4c); Stage 5 audit of every number, with arithmetic recomputation from sealed results allowed and no access to the answer key. Findings are classed must fix (required revision) or advisory. Output paths are named in each packet.
- Clarified Stage 1: the Lead Designer writes the Stage 1 decision document; the parent pins the workflow and checks it at G1. The Second Designer still has no Stage 1 role.
- Moved SQL source gates to Stage 3 as G3S (extraction completeness, keys, joins, counts). The SQL Analyst writes them against the design; the parent runs them. G3K remains the parent-owned Python early key/count checks. In Stage 4 the SQL Analyst runs independent SELECT-only queries on the frozen hashed snapshot (not live systems); the parent reconciles SQL against R.
- Relabeled Stage 4 gates: former G4a (source gates) is now G3S; former G4b (fixtures) is now G4a; former G4c (reconciliation) is now G4b; new G4c is the post-reconciliation review; G4d remains the release gate.

## 0.1.2 — 2026-11-09

- Clarified the Second Designer's Stage 3 job: it first writes its own independent design from the Stage 3 inputs, without seeing the Lead Designer's draft or reasoning, then compares against the lead's design and reports differences.
- Removed the Second Designer from Stage 1. Stage 1 has no Second Designer role; the parent runs G1. The Second Designer is active in Stages 2, 3, and 5 only.

## 0.1.1 — 2026-11-09

- Corrected the approved post-benchmark change list to all ten items. Item 7 (feasibility gate sees structure and quality only, not values or the answer key) is now listed separately from item 3 (the data-feasibility gate itself).
- Locked Stage 5 to reuse the existing bots: the Lead Designer writes the interpretation, the Second Designer checks the inference, and the Risk Reviewer audits the numbers. No dedicated finish bots.
- Recorded copyright: the owner holds copyright; no LICENSE file; no license is granted.
- Recorded scoring and lock rules: the earlier key preparer from the ChatGPT (Version 1) side holds the private key and scores blind; Version 2 seeks an official lock; Version 1 is scored on accuracy only.
- Recorded the run cap: one attempt per version on Case B, a maximum of 3 repair rounds, stop and report after about a day of work per side, and retry up to 3 times if blocked.

## 0.1.0 — 2026-11-09

- Initial local design of the Grok Bot team workflow: parent plus six child roles, five stages, gate list, handoff format, and comparison protocol.
- Incorporates the approved post-benchmark changes as design requirements (Python gates with parity tests, analysis in R, data-feasibility gate, fewer clearer rules, greater autonomy, persistent lessons, large outputs in parts, early key/counting checks with a 3-round repair cap, and the explainer).
- Gate code and parity tests are specified only and marked **NOT IMPLEMENTED**. No tests were run.
- Public-scope rule added: method only; no keys, case data, evidence packets, account identifiers, or private paths.
