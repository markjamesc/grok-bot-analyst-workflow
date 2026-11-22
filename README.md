# Grok Bot analyst workflow (design draft)

This folder is the design of a Grok Bot team version of a five-stage analyst workflow. A parent orchestrates; three operational roles (Coordinator, Gate Runner, Database Connector) run the process tools; seven child roles do the analytical work (the Stakeholder only in Stages 1–2). It is published as a **public method repository**, a portable workflow design, not a case archive.

A later push to `main` still needs a separate, single owner approval.

## What this is, and what it is not

- It is the design for **Version 2** of a head-to-head methods test: a parent Grok Bot plus child Grok Bots, compared later with a single ChatGPT chat that does the same job alone (Version 1).
- It incorporates the ten approved post-benchmark changes listed below.
- It is **method only**. It contains no case data, private answer keys, evidence packets, live-file hashes, account names, emails, tokens, or private local paths.
- It does **not** claim that the team is more accurate than a single model, or that same-family bots are independent in the way different model families can be.
- Gate **code** is implemented here: every Python gate G0–G6 and GP is implemented and tested, including G5 (claims) and G6 (certificate), so a run can now reach a Python-gate certificate. It still needs the R Procedure Gate certificate and an owner approval of the exact finish package. See [gates/README.md](gates/README.md).

## Honest limit

Every bot in this version is a Grok Bot, so they share one model family. Separate instructions, memories, and packets are real process discipline. Agreement among them still counts for less than agreement across different model families. This design must be described as a **same-family role split**, never as three-family independence.

## Roles

| Role | Who | Job |
|---|---|---|
| Parent | Orchestrator | Pins the workflow, writes the persona and runs the Stakeholder group chat, packs and sends packets, routes reviews, puts decisions to the owner and records his approvals, escalates. Does not run gates, capture, seal or close, execute SQL, or advance a stage; does not author analysis or interpretation. |
| Coordinator | Operational role | Requests each gate run with an attempt id and advances a stage only on a PASS for the attempt it requested (`python3 -m gates.attempt`); counts repairs. |
| Gate Runner | Operational role | Runs every Python gate (G0–G6, G5P, GD, GP) and the capture, promote, seal and close tools; records every outcome under the Coordinator's attempt id. |
| Database Connector | Operational role | Executes the SQL Analyst's SELECT-only SQL read-only on the frozen snapshot (feasibility, G3S, Stage 4) and returns the identity of the snapshot it actually opened. |
| Stakeholder | Child bot | Stages 1–2 only. Plays the business person in a group chat with the owner and the parent: opens the case, answers clarifying questions from the brief, reacts to the framing. Reads only the public brief and a persona written from it; never locks anything. |
| Lead Designer | Child bot | Writes the Stage 1 decision document, drafts Stages 2–3, and writes the Stage 5 write-up. |
| Second Designer | Child bot | Writes an independent Stage 3 design before seeing the lead's, then compares; also Stage 2 critique and Stage 5 inference review. |
| Risk Reviewer | Child bot | Checks framing at Stage 2, red-teams the design at Stage 3, reviews source gates and post-reconciliation evidence, and audits every number at Stage 5. |
| Analyst R-A | Child bot | Independent judged analysis in R. |
| Analyst R-B | Child bot | Second independent judged analysis in R. Does not see R-A before freeze. |
| SQL Analyst | Child bot | SELECT-only SQL: data-feasibility check, Stage 3 source gates (Gate Runner runs them through the Database Connector, Risk Reviewer reviews), and an independent Stage 4 computation on the frozen hashed snapshot. |

Role instructions: [docs/roles/](docs/roles/). Operational roles (repair round 1, 2026-11-22): the **Gate Runner** runs every gate and the capture, promote, seal and close tools; the **Database Connector** executes the SQL Analyst's SELECT-only SQL read-only on the frozen snapshot and reports the snapshot it opened; the **Coordinator** requests each gate run with an attempt id and advances a stage only on a PASS for the attempt it requested. The parent orchestrates and never does those three jobs itself. **Stage 5 reuses these existing bots:** the Lead Designer writes the interpretation, the Second Designer checks the inference, and the Risk Reviewer audits every number (and may recompute arithmetic from sealed results, but never sees the answer key). There are no dedicated finish bots.

## Stages

1. **Start** — a live conversation in a group chat: the Stakeholder opens, the parent asks clarifying questions, the owner weighs in; every message relied on is captured exactly. The Lead Designer writes the Stage 1 decision document (agreed decision and question) from the brief and the captures; the owner locks it in his own words; the parent pins the workflow and the Gate Runner runs G1.
2. **Framing** — turn the decision into one precise question, talked through with the Stakeholder in the same group chat and locked by the owner in his own words.
3. **Design** — lock how the question will be measured and tested. A **data-feasibility gate** sits between Stage 2 and Stage 3. In Stage 3 the SQL Analyst writes the SQL source gates; the Gate Runner runs them through the Database Connector.
4. **Execution** — write and check the code (R-A, R-B, and SELECT-only SQL on the frozen hashed snapshot). The Gate Runner reconciles SQL against R (G4b); the Risk Reviewer then checks the reconciled evidence.
5. **Finish** — interpret the sealed results and recommend an action. Scoring happens only after the freeze, by someone who was not a live role.

Details: [docs/stages.md](docs/stages.md) and [docs/explainer.md](docs/explainer.md).

## Approved post-benchmark changes built into this design

These are design requirements for this draft. Items 1, 8 and 9 have Python gate code; the rest are process rules in the documents.

1. **Python gates with parity tests** against the current R gates. Implemented: see [Status](#status).
2. **Analysis stays in R.** SQL is SELECT-only (feasibility, Stage 3 source gates, and an independent Stage 4 computation on the frozen hashed snapshot). The Gate Runner runs the SQL source gates at Stage 3 (the Database Connector executes them) and reconciles SQL against R at Stage 4 (G4b). The Risk Reviewer reviews the source gates and, after reconciliation, the evidence.
3. **Data-feasibility gate** between Stage 2 and Stage 3: `yes` / `partly` / `no`, with a reason. Stages 1 and 2 stay blind to the data. Data must never shape or add questions. A `partly` or `no` goes to the owner.
4. **Fewer, clearer rules**, backed by the evidence rules below.
5. **Greater autonomy.** Escalate only materially consequential analytical or business changes, and genuinely required approvals.
6. **Persistent lessons** from benchmark runs: process lessons only, never keys or case answers. See [docs/lessons.md](docs/lessons.md).
7. **Feasibility gate sees structure and quality only**, not values or the answer key.
8. **Large outputs in parts**, with an assembly script, a transform log, and a regression test for omitted output (gate GP, implemented and tested).
9. **Early key and counting checks** (gate G3K, implemented and tested), with a repair cap of **3** on the same defect (implemented and tested). After that, escalate to the owner with the open problems, a recommendation, and a batched revision.
10. **Explainer document** for the five stages: [docs/explainer.md](docs/explainer.md).

## Workflow changes of 2026-11-22 (owner-approved)

Inside the existing roles and gates; details in [docs/stages.md](docs/stages.md) ("Workflow changes") and standing rules 37–44.

- **Four known fixes (gate code, tested):** attempt ids with every outcome recorded (TOOL_ERROR included) and advance only on a PASS of the requested attempt; G3S bound to the exact frozen snapshot, so Stage 4 on another snapshot needs a fresh check; G0 accepts only a runner-written G5P PASS for the exact claims ledger in a Stage 5 review packet; one finish order everywhere (owner approves the exact finish package -> R `complete finish` -> G5 -> R `finalize` -> G6).
- **Stage 1:** keeping the current policy and waiting or deferring are real options; the question does not presuppose the hoped-for conclusion.
- **Stage 2:** the Risk Reviewer asks whether the finding could appear even if the action would do little good; the Second Designer gives one concrete example where two readings of a key term come apart.
- **Stage 3:** hand-checkable decision-flip fixtures (exact threshold, pooling, missing values, duplicate joins), checked at G3.
- **Stage 4:** results checked against known answers even when R-A, R-B and SQL agree; tolerances only on declared rounding fields, exact elsewhere.
- **Stage 5:** the best justified action, with no change as a real option, and any causal claim stated separately.
- **Across stages:** checkable reviewer tasks; each role's first independent answer kept; reproduce, hold up and fits the action judged as three separate claims; a light review-cost log.

Not adopted (kept as possible later experiments): moving the feasibility check before the Stage 2 lock, a second model family, and the 750-run benchmark.

## Standing rules

- **Do not weaken gates.** Version 2 (this Grok Bot design) seeks an official lock under these gates. Version 1 of the head-to-head (one ChatGPT, no second model) is scored on accuracy only, outside the official lock. It does not earn a Design or Finish lock under these rules.
- **Immutability.** Never overwrite or reseal a sent, reviewed, or frozen input. Repairs create a new versioned artifact and a truthful change record.
- **Parent/child isolation.** The parent must not leak one child’s work into another child’s packet before the relevant freeze. Blinded scoring stays outside the live roles. Live roles never see the private answer key. The private key is held, and scoring is done, by the earlier key preparer from the ChatGPT (Version 1) side.
- **No writes to live systems** without owner approval. Default execution uses frozen, hashed extracts or an owner-approved read-only source.
- **Review coverage.** A required review counts only if that role received every current subject whole, at the same project path, with the current hash.
- **A recorded split is not a guarantee of independent errors.**
- **Check public files before stopping.** A missing input or mapping is checked against the public schema, brief and bundle files first; derivable items are recorded and the work continues; only non-derivable items stop and go to the owner (GD, inside G0).
- **Descriptive rates are allowed and expected**, labeled descriptive or associational, not causal. No blanket "no rates" rule (G3, G5).
- **Live Stakeholder (Stages 1–2).** The request is a captured back-and-forth with a Stakeholder role and the owner. Captures are exact and write-once; the framing cites them with the brief; a preference is never a fact; only the owner changes a rule or locks a stage (G1, G2; standing rules 31–36). Freeze counts restarted at zero with the first case run this way.
- **No template placeholders in evidence** (G0 at send, G3 at the design lock), and **replaced packets are marked superseded** in the packet index (G0).

## Run cap (head-to-head test)

One attempt per version on Case B. A maximum of 3 repair rounds. Stop and report after about a day of work per side. If a side is blocked, wait and retry up to 3 times, then report.

## Copyright

The owner holds the copyright to this design. No license is granted, and no LICENSE file is included or should be added. The public may read this repository; that is not permission to copy, modify, or reuse it.

## Document index

| Document | Contents |
|---|---|
| [docs/explainer.md](docs/explainer.md) | Plain-language tour of the five stages |
| [docs/stages.md](docs/stages.md) | Stage-by-stage flow and role handoffs |
| [docs/gates.md](docs/gates.md) | Gate list and what each one decides |
| [docs/handoff.md](docs/handoff.md) | Packet format between parent and children |
| [docs/comparison.md](docs/comparison.md) | Scoring protocol vs the single-ChatGPT version |
| [docs/roles/](docs/roles/) | One file per bot (including the Stakeholder) |
| [docs/lessons.md](docs/lessons.md) | How persistent lessons are recorded |
| [docs/public-scope.md](docs/public-scope.md) | What must never go in this public repository |
| [docs/rules.md](docs/rules.md) | Standing operating rules |
| [docs/judgment_checks.md](docs/judgment_checks.md) | Judgment checks for designer and reviewer replies |
| [CHANGELOG.md](CHANGELOG.md) | Design revisions |
| [gates/](gates/) | Python gates G0–G6, GD and GP, with unit, planted-defect and R parity tests |

## Status

This is design documentation plus the Python gate implementation.

- **Implemented and tested:** G0 (packet integrity), G1, G2, G2F, G3S (SQLite engine only), G3K, G3, G4a, G4b, G4c, G4d, G5 (claims), G6 (certificate), GD (public-file derivability) and GP (assembly regression), plus the repair cap (3, then escalate). G1, G2, G3, G4d and G5 include ported R stage checks, and G4d includes the whole ported R Workflow Gate; those ports pass R-vs-Python parity on the R repo's own test suites and on the gate fixtures. G6 requires the R Procedure Gate `finalize` certificate and re-checks every hash it recorded. G0 has no R counterpart. Tests use synthetic data only.
- G1 and G2 also check the live Stakeholder conversation (`gates/stakeholder.py`, which is also the capture tool).
- G3S runs on SQLite only; other engines need an executor (otherwise TOOL_ERROR).
- No workflow has been started from these gates yet.

Details and test commands: [gates/README.md](gates/README.md) and [docs/gates.md](docs/gates.md).
