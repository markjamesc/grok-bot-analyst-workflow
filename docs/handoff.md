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
EXPECTED OUTPUT: <files and format; parts if large>
REPLY ENDS WITH: ANSWERED <PACKET_ID> + list of produced files
```

## Parent duties
- Record send time, the packet hash, and the captured reply hash in the run ledger.
- Check the reply against EXPECTED OUTPUT before sealing it.
- A correction is a new packet with a `-vN` suffix that names what it supersedes.
