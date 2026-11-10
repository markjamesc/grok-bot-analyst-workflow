# Handoff packet format

Every message between the parent and a child is a packet. Packets are sealed once sent and never edited.

```text
PACKET_ID: <run>-<stage>-<seq>[-vN]
ROLE: <child role>
STAGE: <1-5 or 2F>
TASK: <one paragraph>
INPUTS:
  - <relative path> sha256=<hash> bytes=<n>   (whole file; parts listed as part k of K)
ALLOWED TO SEE: <list>
NOT ALLOWED TO SEE: answer key; peer paths before freeze; <others>
RULES: <only the rules this task needs>
EXPECTED OUTPUT: <named output paths and format; parts if large>
REPLY ENDS WITH: ANSWERED <PACKET_ID> + list of produced files
```

## Parent duties
- Record send time, the packet hash, and the captured reply hash in the run ledger.
- Name the output paths in each packet under EXPECTED OUTPUT. The child writes only to those paths.
- Check the reply against EXPECTED OUTPUT before sealing it.
- A correction is a new packet with a `-vN` suffix that names what it supersedes.

## Stage 3 packets for the Second Designer
- First packet: Stage 3 inputs only. Do not include the Lead Designer's draft or reasoning.
- After the Second Designer's independent design is sealed, send a second packet with the lead's design so the Second Designer can compare and report differences.

## Stage 2 packets for the Risk Reviewer
- Send the Lead Designer's framing for a check, alongside the Second Designer's critique.
- Send the G2F feasibility result for review.

## Stage 3 packets for the SQL Analyst
- Send the current design so the SQL Analyst can write the G3S source gates (extraction completeness, keys, joins, counts). The parent runs those gates.

## Stage 3 packets for the Risk Reviewer
- Send the current design for a red-team.
- After the parent runs G3S, send the source-gate code and results for review.

## Stage 4 packets for the SQL Analyst
- Send the locked design and the frozen, hashed snapshot (not a live system) so the SQL Analyst can run independent SELECT-only queries. Do not include R-A or R-B work before freeze.

## Stage 4 packets for the Risk Reviewer
- After the parent reconciles R-A, R-B, and SQL (G4b), send the reconciliation report and the reconciled evidence for the G4c review. Name the output paths in the packet.
