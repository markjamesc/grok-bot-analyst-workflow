# Gate list

Every gate returns PASS, FAIL (analysis defect), or TOOL_ERROR. An unrun gate is not PASS. No verbal waiver. All gates are owned and run by the parent, except where noted.

| ID | Gate | Written by | Run by | Reviewed by | Checks |
|---|---|---|---|---|---|
| G0 | Packet integrity | Parent (Python) | Parent | — | Every attachment whole, current hash, correct path; no forbidden content or template leftovers; sealed once sent; an answered packet has a reply ending `ANSWERED <PACKET_ID>` with a non-blank produced-files list |
| G1 | Decision | Parent (Python) | Parent | — | Stage 1 decision document present (decision, owner, actions per result, limits); workflow pinned by the parent |
| G2 | Question lock | Parent (Python) | Parent | — | One question; population, window, metric, threshold; capacity stance; review coverage (Second Designer critique and Risk Reviewer framing check) |
| G2F | Data feasibility | Parent (Python) wraps SQL Analyst output | Parent | Risk Reviewer | yes/partly/no plus reason per question; structure and quality only, not values or the answer key; no new questions |
| G3S | **SQL source gates** | **SQL Analyst** (SELECT-only SQL) | Parent | **Risk Reviewer** | Extraction completeness, keys, joins, and counts match the design |
| G3K | Early key/count checks | Parent (Python) | Parent | Risk Reviewer | Keys unique, counts reconcile on fixtures; repair cap 3 |
| G3 | Design lock | Parent (Python) | Parent | — | Required fields, ML mode explicit, fixtures with worked answers, review coverage, G3S and G3K PASS, owner hash approval |
| G4a | Fixtures | Parent (Python) | Parent | — | R-A, R-B, and SQL match worked answers |
| G4b | Reconciliation | Parent (Python) | Parent | — | Exact match on locked critical fields; mismatch count 0 |
| G4c | Post-reconciliation review | Parent (Python) wraps Risk Reviewer output | Parent | Risk Reviewer | After G4b, the Risk Reviewer checks the reconciled evidence from R-A, R-B, and SQL; no open must-fix findings |
| G4d | Release (Stage 4→5) | Parent (Python) | Parent | — | All lower gates PASS by hash; no open issues |
| G5 | Claims | Parent (Python) | Parent | Second Designer, Risk Reviewer | Every material claim quoted from a deliverable, within the claim ceiling, tied to sealed evidence, every number traced; R finish checks |
| G6 | Certificate | Parent (Python) | Parent | — | All stages in order; hashes still current; every packet answered; owner approved the exact finish package; R `finalize` certificate current |
| GP | Assembly regression | Parent (Python) | Parent | — | Assembled parts equal the declared whole; no omitted part |

G3S and G3K are Stage 3 gates and must PASS before G3 locks the design. G3K remains parent-owned Python. ID mapping from earlier drafts: former G4a (SQL source gates) is now G3S; former G4b (fixtures) is now G4a; former G4c (reconciliation) is now G4b; G4c is the new post-reconciliation review; G4d remains the release gate.

**Python gates stay with the parent.** Each needs a parity test against the existing R gate before use. Status (2026-11-10): G0, G1, G2, G2F, G3S (sqlite engine), G3K, G3, G4a, G4b, G4c, G4d, G5, G6 and GP are **implemented and tested**, and the repair cap is too. G1, G2, G3, G4d and G5 include the ported R stage checks, and G4d includes the whole ported R Workflow Gate. Those ports pass R-vs-Python parity on the R repo's own test suites and on the gate fixtures. G6 requires the R `finalize` certificate and re-checks its hashes. G0 has no R counterpart. See [../gates/README.md](../gates/README.md).

**Review coverage.** A review counts only if the reviewer received every current subject whole, at the same path, with the current hash.

**Repair cap.** Three unsuccessful repairs on the same defect, then escalate. Changing author does not reset the count.

**Finding classes (Risk Reviewer).** `must fix` requires a revision; `advisory` does not block the gate by itself.
