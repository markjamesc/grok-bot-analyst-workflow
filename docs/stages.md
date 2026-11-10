# Stage-by-stage flow

Each step is: parent packs → child works → parent captures and seals → gate. A failed gate goes back to the owning stage.

| Stage | Author | Reviewers | Gate | Owner touchpoint |
|---|---|---|---|---|
| 1 Start | Lead Designer | Second Designer | G1 decision | None unless the decision is unclear |
| 2 Framing | Lead Designer | Second Designer | G2 question lock | Approve the locked question |
| 2→3 Feasibility | SQL Analyst | Risk Reviewer | G2F feasibility | Only on `partly` / `no` |
| 3 Design | Lead Designer | Second Designer (cross-review), Risk Reviewer | G3 design lock, early key/count checks | Approve the exact design hash |
| 4 Execution | R-A, R-B, SQL Analyst | Risk Reviewer (SQL source gates) | G4a source, G4b fixtures, G4c reconciliation, G4d release | Only after 3 failed repairs or a changed decision |
| 5 Finish | Lead Designer | Second Designer (inference), Risk Reviewer (numbers) | G5 claims, G6 certificate | Human approval of the finish |
| Score | Scorer outside live roles (earlier ChatGPT key preparer) | — | — | — |

## Notes
- Stages 1–2 never see data values. Feasibility sees structure and quality only, not values or the answer key, and cannot add or reshape questions.
- Stage 5 reuses the existing bots: the Lead Designer writes the interpretation, the Second Designer checks the inference, and the Risk Reviewer audits the numbers. There are no dedicated finish bots.
- Stage 4 order: SQL source gates pass → R-A, R-B, and SQL build independently → freeze each → fixtures → parent reconciles R-A vs R-B vs SQL → release gate.
- A difference in reconciliation is traced to a cause and repaired from the design. The design itself does not change without owner change control and a new version.
- Large artifacts are requested in parts from the start and joined with an assembly script that logs every transform.
- After the freeze, the earlier key preparer from the ChatGPT (Version 1) side holds the private key and scores both versions blind. Live roles never see the key.
