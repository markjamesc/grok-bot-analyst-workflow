# Handoff packet format

Every message between the parent and a child is a packet. Packets are sealed once sent and never edited.

```text
PACKET_ID: <run>-<stage>-<seq>[-vN]
ROLE: <child role>
STAGE: <1-5 or 2F>
SUPERSEDES: <earlier packet id>   (only on a -vN correction)
TASK: <one paragraph>
INPUTS:
  - <relative path> sha256=<hash> bytes=<n>   (whole file; parts listed as part k of K)
ALLOWED TO SEE: <list>
NOT ALLOWED TO SEE: answer key; peer paths before freeze; <others>
RULES: <only the rules this task needs>
EXPECTED OUTPUT: <named output paths and format; parts if large>
REPLY ENDS WITH: ANSWERED <PACKET_ID> + list of produced files
```

Every reply ends like this, with the `PRODUCED FILES:` list never blank and `ANSWERED` as the last line:

```text
PRODUCED FILES:
- <path of each file written>

ANSWERED <PACKET_ID>
```

A reply that settled a missing item from the public files says so before the list, one line per item, and keeps working:

```text
DERIVED: <item> from <public file path>: <how>
```

A reply that must stop because the public files do not settle an item says so, one line per item:

```text
MISSING INPUT: <item>
```

## Parent duties
- List every packet in `artifacts/packets/index.json` (id, path, status draft/sent/answered, sealed sha256, and the sealed reply once answered) and run G0 before each send and after each capture.
- Build each sent packet from the template as a new file; never send the template. G0 rejects `TEMPLATE` text, `{{placeholders}}` and the format's `<...>` placeholders.
- A packet is answered only when the child's reply arrives and ends with `ANSWERED <PACKET_ID>`. A file appearing on disk is not a completed send.
- Record send time, the packet hash, and the captured reply hash in the run ledger.
- Name the output paths in each packet under EXPECTED OUTPUT. The child writes only to those paths.
- Check the reply against EXPECTED OUTPUT before sealing it.
- A correction is a new packet with a `-vN` suffix that names what it supersedes.
- When a packet is replaced (for example a sent packet that failed G0), mark the old row in `artifacts/packets/index.json` with `superseded_by` (the newer packet id), `superseded_reason` and `superseded_at` (ISO timestamp with zone). Never edit or reseal the old packet.
- List the public schema, brief and bundle files as inputs in every packet that might need them, so a child can derive a value meaning or a mapping instead of stopping.
- Never attach a template JSON (`*.example.json`) or any JSON with placeholder references as an input. Attach the adapted, real file or a prose summary (G0).

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

## Case02 additions
- **Stage 5 review packets** list the latest G5P precheck log of the ledger under review as an input (G0 fails a Stage 5 Second Designer or Risk Reviewer packet without one). A reviewer reads the precheck first and says whether each failing check is a real defect or a tool limit.
- **Revision briefs that change a report path** say, in the brief: "update the `deliverable` field of every claim that quotes the moved report, not only the deliverables list". G5P catches a miss before placement.
- **Builders' corrections** before send are logged in `artifacts/stage4/corrections.json`; the brief never asks the parent to unlock or re-freeze a builder's file, and the parent never writes the extract.
- **Owner decisions** in a packet or brief are stated plain-language first (what is being decided, the options, what each does), then the technical detail.
