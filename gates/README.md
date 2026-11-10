# Gates (skeleton)

**Status: NOT IMPLEMENTED.** This folder only reserves the layout for the parent's Python gates and their parity tests. No code here runs, and no tests have been run.

Planned layout:
- `gates/<gate_id>.py` with one function per gate in [../docs/gates.md](../docs/gates.md), returning PASS, FAIL, or TOOL_ERROR
- `gates/parity_tests/` runs each Python gate and the matching R gate on the same synthetic receipts and requires identical verdicts
- SQL source gates (G3S) live in the project, written by the SQL Analyst at Stage 3. The parent's Python runner only checks that they are SELECT-only and records their results.
