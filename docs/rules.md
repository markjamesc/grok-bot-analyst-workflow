# Standing rules (short list)

1. Do not weaken a gate. No verbal waivers. Version 2 may seek an official lock; Version 1 is scored on accuracy only and cannot earn one.
2. Never overwrite or reseal sent, reviewed, or frozen inputs. Make new versions.
3. Keep the parent and children isolated; score blind; keep the key away from live roles. The earlier key preparer from the ChatGPT (Version 1) side holds the key and scores.
4. All bots share one model family, so their independence is limited. Say so.
5. Analysis is in R. SQL is SELECT-only. Gates are Python, owned by the parent.
6. No writes to live systems without owner approval.
7. Escalate only material analytical or business changes and required approvals.
8. Repair cap of 3 per defect, then escalate with problems, a recommendation, and a batched revision.
9. Large outputs come in parts, with assembly and a log.
10. No push to `main` without one owner approval.
11. After a repair, the current file goes back to every required reviewer before its gate. A review of a superseded version does not count.
12. A child's work is done only when its reply reaches the parent and ends with `ANSWERED <PACKET_ID>` after a non-blank list of produced files. A file on disk is not a reply.
13. Never send a template. Sent packets are new versions with no `TEMPLATE` text or `{{placeholders}}` (G0).
14. **Check public files before stopping.** A missing input or mapping (what a field value means, which entity is which, a code list, a unit) is first checked against the public schema, brief and bundle files. If they settle it, record the derivation and continue. Only an item they do not settle may stop the work, and it goes to the owner. The parent records every check in `artifacts/derivability.json`; G0 and GD fail a stop that was not checked or that a public file already answers.
15. **Descriptive rates are allowed and expected.** Report group rates and their differences (for example each group's rate and the gap in points) when the question calls for them, labeled descriptive or associational, not causal. Never write a blanket "no rates" rule; restrict causal wording instead. G3 fails a design that bans rates; G5 fails a rate claim without a descriptive label.
16. **No template placeholders in the evidence.** Never attach a shape template (`*.example.json`, placeholder fixtures, all-zero or `NOT_SET` hashes) as a packet input or design reference. Adapt it with real frozen files first. G0 rejects it before the send and G3 at the design lock, because R `finalize` would fail on it at the end.
17. **Replaced packets are marked superseded.** A packet replaced by a newer one is marked in the packet index with `superseded_by`, `superseded_reason` and `superseded_at`. It stays sealed; G0 stops checking its content and G6 no longer counts it.
18. **Stage 3 locks every Workflow Gate field.** G3 fails a locked design that lacks any Stage 3 field the R Workflow Gate reads at G4d (including `ml_mode`, `fixture_version`, `fixture_ids`, `reconciliation_critical_fields`, and the `ranking_contract` under a hard attention budget), so the gap is found at lock and not at release.
19. **Prechecks travel with reviews.** Before a Stage 5 ledger goes to review or is placed, the parent runs G5P, which runs exactly the G5 claim and content checks (CSV evidence read cell by cell). The latest G5P log of the ledger under review is an input of every Stage 5 review packet (G0 checks it).
20. **Report path changes reach every claim.** A revision brief that changes a deliverable path requires the author to update the `deliverable` field of every claim that quotes it, not only the deliverables list. G5 and G5P fail a claim whose deliverable is not in the ledger.
21. **The SQL Analyst writes the extract.** The parent never writes an extract or a builder's file. A builder corrects its own file before send by a logged correction (`artifacts/stage4/corrections.json`, reviewed at G4c), not by unlocking and re-freezing.
22. **Disclosures state what the record says.** A disclosure quotes or paraphrases the sealed record it refers to, not a recollection. When a disclosure is corrected, every ledger field that repeats it (claims, quotes, notes, deliverables) is swept and updated in the same revision.
23. **Thresholds are stated as numbers.** The final report states every decision threshold numerically, with its design id (`decision_thresholds` in the Grok design, declared at G3 and checked at G5).
24. **Owner holds are disclosed, never withholding.** An owner hold or stop test (for example a stop test the owner set at Stage 5) stays in force and is disclosed. It never withholds the action the stated rule decides: the decision output keeps the rule's action and the hold side by side, and the report gives the rule's action with the hold put to the owner on the same line. The hold still waits for the owner; only how it is reported changes. G3 checks the hold is declared with its owner source; G5 checks the report.

## Run cap (head-to-head test)

One attempt per version on Case B. Maximum of 3 repair rounds. Stop and report after about a day of work per side. If a side is blocked, wait and retry up to 3 times, then report.

## Copyright

The owner holds the copyright. No license is granted. Do not add a LICENSE file.
