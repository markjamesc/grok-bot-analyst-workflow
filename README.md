# Grok Bot analyst workflow (design draft)

This folder is the design of a Grok Bot team version of a five-stage analyst workflow. A parent bot orchestrates; six child bots take named roles. It is published as a **public method repository**, a portable workflow design, not a case archive.

A later push to `main` still needs a separate, single owner approval.

## What this is, and what it is not

- It is the design for **Version 2** of a head-to-head methods test: a parent Grok Bot plus child Grok Bots, compared later with a single ChatGPT chat that does the same job alone (Version 1).
- It incorporates the ten approved post-benchmark changes listed below.
- It is **method only**. It contains no case data, private answer keys, evidence packets, live-file hashes, account names, emails, tokens, or private local paths.
- It does **not** claim that the team is more accurate than a single model, or that same-family bots are independent in the way different model families can be.
- Gate **code** is not implemented here. See [gates/README.md](gates/README.md).

## Honest limit

Every bot in this version is a Grok Bot, so they share one model family. Separate instructions, memories, and packets are real process discipline. Agreement among them still counts for less than agreement across different model families. This design must be described as a **same-family role split**, never as three-family independence.

## Roles

| Role | Who | Job |
|---|---|---|
| Parent | Data Analysis and Coding bot | Orchestrates, pins the workflow, packs and seals work, runs gates, reconciles outputs, escalates. Does not author analysis or interpretation. |
| Lead Designer | Child bot | Writes the Stage 1 decision document, drafts Stages 2–3, and writes the Stage 5 write-up. |
| Second Designer | Child bot | Writes an independent Stage 3 design before seeing the lead's, then compares; also Stage 2 critique and Stage 5 inference review. |
| Risk Reviewer | Child bot | Checks framing at Stage 2, red-teams the design at Stage 3, reviews source gates and post-reconciliation evidence, and audits every number at Stage 5. |
| Analyst R-A | Child bot | Independent judged analysis in R. |
| Analyst R-B | Child bot | Second independent judged analysis in R. Does not see R-A before freeze. |
| SQL Analyst | Child bot | SELECT-only SQL: data-feasibility check, Stage 3 source gates (parent runs, Risk Reviewer reviews), and an independent Stage 4 computation on the frozen hashed snapshot. |

Role instructions: [docs/roles/](docs/roles/). **Stage 5 reuses these existing bots:** the Lead Designer writes the interpretation, the Second Designer checks the inference, and the Risk Reviewer audits every number (and may recompute arithmetic from sealed results, but never sees the answer key). There are no dedicated finish bots.

## Stages

1. **Start** — the Lead Designer writes the Stage 1 decision document; the parent pins the workflow and checks it at G1.
2. **Framing** — turn the decision into one precise, locked question.
3. **Design** — lock how the question will be measured and tested. A **data-feasibility gate** sits between Stage 2 and Stage 3. In Stage 3 the SQL Analyst writes the SQL source gates; the parent runs them.
4. **Execution** — write and check the code (R-A, R-B, and SELECT-only SQL on the frozen hashed snapshot). The parent reconciles SQL against R; the Risk Reviewer then checks the reconciled evidence.
5. **Finish** — interpret the sealed results and recommend an action. Scoring happens only after the freeze, by someone who was not a live role.

Details: [docs/stages.md](docs/stages.md) and [docs/explainer.md](docs/explainer.md).

## Approved post-benchmark changes built into this design

These are design requirements for this draft. They are not yet implemented as executable code.

1. **Python gates with parity tests** against the current R gates. Skeleton only; not implemented.
2. **Analysis stays in R.** SQL is SELECT-only (feasibility, Stage 3 source gates, and an independent Stage 4 computation on the frozen hashed snapshot). The parent runs the SQL source gates at Stage 3 and reconciles SQL against R at Stage 4. The Risk Reviewer reviews the source gates and, after reconciliation, the evidence.
3. **Data-feasibility gate** between Stage 2 and Stage 3: `yes` / `partly` / `no`, with a reason. Stages 1 and 2 stay blind to the data. Data must never shape or add questions. A `partly` or `no` goes to the owner.
4. **Fewer, clearer rules**, backed by the evidence rules below.
5. **Greater autonomy.** Escalate only materially consequential analytical or business changes, and genuinely required approvals.
6. **Persistent lessons** from benchmark runs: process lessons only, never keys or case answers. See [docs/lessons.md](docs/lessons.md).
7. **Feasibility gate sees structure and quality only**, not values or the answer key.
8. **Large outputs in parts**, with an assembly script, a transform log, and a regression test for omitted output. The test is not yet written.
9. **Early key and counting checks**, with a repair cap of **3** on the same defect. After that, escalate to the owner with the open problems, a recommendation, and a batched revision.
10. **Explainer document** for the five stages: [docs/explainer.md](docs/explainer.md).

## Standing rules

- **Do not weaken gates.** Version 2 (this Grok Bot design) seeks an official lock under these gates. Version 1 of the head-to-head (one ChatGPT, no second model) is scored on accuracy only, outside the official lock. It does not earn a Design or Finish lock under these rules.
- **Immutability.** Never overwrite or reseal a sent, reviewed, or frozen input. Repairs create a new versioned artifact and a truthful change record.
- **Parent/child isolation.** The parent must not leak one child’s work into another child’s packet before the relevant freeze. Blinded scoring stays outside the live roles. Live roles never see the private answer key. The private key is held, and scoring is done, by the earlier key preparer from the ChatGPT (Version 1) side.
- **No writes to live systems** without owner approval. Default execution uses frozen, hashed extracts or an owner-approved read-only source.
- **Review coverage.** A required review counts only if that role received every current subject whole, at the same project path, with the current hash.
- **A recorded split is not a guarantee of independent errors.**

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
| [docs/roles/](docs/roles/) | One file per bot |
| [docs/lessons.md](docs/lessons.md) | How persistent lessons are recorded |
| [docs/public-scope.md](docs/public-scope.md) | What must never go in this public repository |
| [docs/rules.md](docs/rules.md) | Standing operating rules |
| [CHANGELOG.md](CHANGELOG.md) | Design revisions |
| [gates/](gates/) | Intended Python gate skeleton (**NOT IMPLEMENTED**) |

## Status

This is design documentation plus an honest, unimplemented gate skeleton. Python gates, parity tests, assembly scripts, and the assembly regression test are **NOT IMPLEMENTED**. No tests have been run. No workflow has been started from this draft.
