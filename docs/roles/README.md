# Roles

| File | Role |
|---|---|
| [parent.md](parent.md) | Parent (orchestrator). Pins the workflow at Stage 1; runs the Stakeholder chat; packs, sends and routes packets; records owner approvals; escalates. Runs no gate and executes no SQL. |
| [coordinator.md](coordinator.md) | Coordinator (operational). Requests gate runs with attempt ids; advances a stage only on a PASS for the attempt it requested. |
| [gate-runner.md](gate-runner.md) | Gate Runner (operational). Runs every Python gate and the capture, promote, seal and close tools. |
| [database-connector.md](database-connector.md) | Database Connector (operational). Executes SELECT-only SQL read-only on the frozen snapshot and reports the snapshot it opened. |
| [stakeholder.md](stakeholder.md) | Stakeholder (Stages 1–2 only: plays the business person in the group chat with the owner and the parent; reads only the public brief and its persona; never locks) |
| [lead-designer.md](lead-designer.md) | Lead Designer |
| [second-designer.md](second-designer.md) | Second Designer |
| [risk-reviewer.md](risk-reviewer.md) | Risk Reviewer (Stages 2–5: framing, red-team, source gates, post-reconciliation evidence, numbers audit) |
| [analyst-r-a.md](analyst-r-a.md) | Analyst R-A |
| [analyst-r-b.md](analyst-r-b.md) | Analyst R-B |
| [sql-analyst.md](sql-analyst.md) | SQL Analyst (SELECT-only feasibility, Stage 3 source gates, and Stage 4 computation on the frozen snapshot) |
