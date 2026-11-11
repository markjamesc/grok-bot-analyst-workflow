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

## Run cap (head-to-head test)

One attempt per version on Case B. Maximum of 3 repair rounds. Stop and report after about a day of work per side. If a side is blocked, wait and retry up to 3 times, then report.

## Copyright

The owner holds the copyright. No license is granted. Do not add a LICENSE file.
