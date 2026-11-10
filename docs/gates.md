# Gate list

Every gate returns PASS, FAIL (analysis defect), or TOOL_ERROR. An unrun gate is not PASS. No verbal waiver. All gates are owned and run by the parent, except where noted.

| ID | Gate | Written by | Run by | Reviewed by | Checks |
|---|---|---|---|---|---|
| G0 | Packet integrity | Parent (Python) | Parent | — | Every attachment whole, current hash, correct path; no forbidden content |
| G1 | Decision | Parent (Python) | Parent | — | Decision, owner, actions per result, limits present |
| G2 | Question lock | Parent (Python) | Parent | — | One question; population, window, metric, threshold; capacity stance |
| G2F | Data feasibility | Parent (Python) wraps SQL Analyst output | Parent | Risk Reviewer | yes/partly/no plus reason per question; structure and quality only, not values or the answer key; no new questions |
| G3 | Design lock | Parent (Python) | Parent | — | Required fields, ML mode explicit, fixtures with worked answers, review coverage, owner hash approval |
| G3K | Early key/count checks | Parent (Python) | Parent | Risk Reviewer | Keys unique, counts reconcile on fixtures; repair cap 3 |
| G4a | **SQL source gates** | **SQL Analyst** (SELECT-only SQL) | Parent | **Risk Reviewer** | Row counts, keys, duplicates, nulls, ranges match the design |
| G4b | Fixtures | Parent (Python) | Parent | — | R-A, R-B, and SQL match worked answers |
| G4c | Reconciliation | Parent (Python) | Parent | — | Exact match on locked critical fields; mismatch count 0 |
| G4d | Release (Stage 4→5) | Parent (Python) | Parent | — | All lower gates PASS by hash; no open issues |
| G5 | Claims | Parent (Python) | Parent | — | Every material claim tied to sealed evidence |
| G6 | Certificate | Parent (Python) | Parent | — | All stages in order; hashes still current |
| GP | Assembly regression | Parent (Python) | Parent | — | Assembled parts equal the declared whole; no omitted part |

**Python gates stay with the parent.** Each needs a parity test against the existing R gate before use. Status: **NOT IMPLEMENTED**. See [../gates/README.md](../gates/README.md).

**Review coverage.** A review counts only if the reviewer received every current subject whole, at the same path, with the current hash.

**Repair cap.** Three unsuccessful repairs on the same defect, then escalate. Changing author does not reset the count.
