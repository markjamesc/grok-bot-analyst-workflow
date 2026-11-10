# Stage-by-stage flow

Each step is: parent packs → child works → parent captures and seals → gate. A failed gate goes back to the owning stage.

| Stage | Author | Reviewers | Gate | Owner touchpoint |
|---|---|---|---|---|
| 1 Start | Lead Designer (decision document) | — (parent pins the workflow and checks it at G1) | G1 decision | None unless the decision is unclear |
| 2 Framing | Lead Designer | Second Designer, Risk Reviewer | G2 question lock | Approve the locked question |
| 2→3 Feasibility | SQL Analyst | Risk Reviewer | G2F feasibility | Only on `partly` / `no` |
| 3 Design | Lead Designer; SQL Analyst (source gates) | Second Designer (independent design, then compare), Risk Reviewer (red-team and source-gate review) | G3S SQL source gates, G3K early key/count checks, G3 design lock | Approve the exact design hash |
| 4 Execution | R-A, R-B, SQL Analyst | Risk Reviewer (post-reconciliation evidence) | G4a fixtures, G4b reconciliation, G4c post-reconciliation review, G4d release | Only after 3 failed repairs or a changed decision |
| 5 Finish | Lead Designer | Second Designer (inference), Risk Reviewer (numbers) | G5 claims, G6 certificate | Approve the exact finish package hashes (after G5, before G6) |
| Score | Scorer outside live roles (earlier ChatGPT key preparer) | — | — | — |

## Notes
- Every packet passes G0 (packet integrity) before it is sent, and every reply is checked by G0 when captured. A child's work counts only when its reply ends with `ANSWERED <PACKET_ID>` after a non-blank list of produced files.
- After a repair of a reviewed file (for example a Stage 2 framing repair), the current version goes back to the required reviewers before the gate. G2, G3 and G5 fail a review of a superseded file.
- The first Stage 2 framing states the capacity rule (including whether an option may be taken at a loss) and the decision unit (pooled or per site/segment) explicitly.
- Stage 5 order: Lead Designer write-up and claims ledger → Second Designer inference review and Risk Reviewer number audit → G5 → owner approves the exact finish package hashes → R Procedure Gate `finalize` → G6 certificate. G4d never overwrites a Workflow Gate report the R Procedure Gate has recorded.
- Stages 1–2 never see data values. Feasibility sees structure and quality only, not values or the answer key, and cannot add or reshape questions.
- Stage 1 has no Second Designer role. The Lead Designer writes the Stage 1 decision document. The parent pins the workflow and checks it at the start gate G1.
- At Stage 2, the Second Designer critiques the Lead Designer's framing and the Risk Reviewer checks that framing alongside it. The Risk Reviewer also reviews G2F feasibility.
- At Stage 3, the Second Designer first writes its own independent design from the Stage 3 inputs, without seeing the Lead Designer's draft or reasoning. After that design is sealed, the parent sends the lead's design so the Second Designer can compare and report differences. The Risk Reviewer red-teams the design.
- Also at Stage 3, the SQL Analyst writes the SQL source gates (G3S: extraction completeness, keys, joins, counts) against the design; the parent runs them; the Risk Reviewer reviews them. G3K remains the parent-owned Python early key/count checks. G3S and G3K must PASS before G3 locks the design.
- Stage 5 reuses the existing bots: the Lead Designer writes the interpretation, the Second Designer checks the inference, and the Risk Reviewer audits every number (and may recompute arithmetic from sealed results, but never sees the answer key). There are no dedicated finish bots.
- Stage 4 order: R-A, R-B, and SQL build independently on the frozen, hashed snapshot (not live systems) → freeze each → fixtures (G4a) → parent reconciles R-A vs R-B vs SQL (G4b) → Risk Reviewer checks the reconciled evidence (G4c) → release gate (G4d). SQL source gates already passed in Stage 3.
- A difference in reconciliation is traced to a cause and repaired from the design. The design itself does not change without owner change control and a new version.
- Large artifacts are requested in parts from the start and joined with an assembly script that logs every transform.
- After the freeze, the earlier key preparer from the ChatGPT (Version 1) side holds the private key and scores both versions blind. Live roles never see the key.
