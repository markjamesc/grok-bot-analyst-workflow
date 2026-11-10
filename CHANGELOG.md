# Changelog

All notable changes to this design draft are recorded here. Dates are America/Chicago.

## 0.1.4 — 2026-11-10

- Added the Python gates and R-vs-Python parity tests. Implemented and tested: G1, G2, G2F, G3S (SQLite engine only), G3K, G3, G4a, G4b, G4c, G4d and GP (assembly regression), plus the repair cap (3, then escalate). G1, G2, G3 and G4d include ported R stage checks, and G4d includes the whole ported R Workflow Gate; those ports pass parity on the R repo's own test suites.
- Still **NOT IMPLEMENTED:** G0 (packet integrity), G5 (claims) and G6 (certificate). An official Finish lock or final certificate is not available from these Python gates.
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
