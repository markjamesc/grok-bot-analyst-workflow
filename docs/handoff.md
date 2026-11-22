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
Gate runs (G0 included), captures, promotes, seals and closes are done by the Gate Runner; SQL is executed by the Database Connector; stage advancement is the Coordinator's (docs/roles/). The parent's own duties:
- List every packet in `artifacts/packets/index.json` (id, path, status draft/sent/answered, sealed sha256, and the sealed reply once answered) and have the Gate Runner run G0 before each send and after each capture.
- Build each sent packet from the template as a new file; never send the template. G0 rejects `TEMPLATE` text, `{{placeholders}}` and the format's `<...>` placeholders.
- A packet is answered only when the child's reply arrives and ends with `ANSWERED <PACKET_ID>`. A file appearing on disk is not a completed send.
- Record send time, the packet hash, and the captured reply hash in the run ledger.
- Name the output paths in each packet under EXPECTED OUTPUT. The child writes only to those paths.
- Check the reply against EXPECTED OUTPUT before the Gate Runner seals it.
- A correction is a new packet with a `-vN` suffix that names what it supersedes.
- When a packet is replaced (for example a sent packet that failed G0), mark the old row in `artifacts/packets/index.json` with `superseded_by` (the newer packet id), `superseded_reason` and `superseded_at` (ISO timestamp with zone). Never edit or reseal the old packet.
- List the public schema, brief and bundle files as inputs in every packet that might need them, so a child can derive a value meaning or a mapping instead of stopping.
- Never attach a template JSON (`*.example.json`) or any JSON with placeholder references as an input. Attach the adapted, real file or a prose summary (G0).

## Live Stakeholder chat (Stages 1 and 2)
The Stakeholder gets no packet. It is briefed with exactly two files, the public brief and the persona the parent writes from it, and speaks only in the group chat with the owner and the parent. The Gate Runner records the chat with the capture tool, never by hand:

```text
python3 -m gates.stakeholder init <root> --stage 1 --brief <brief> --persona <persona> --run-kind live
python3 -m gates.stakeholder capture <root> --stage 1 --id S1-M01 --speaker stakeholder --timestamp <ISO with zone> --text-file <exact chat text>
python3 -m gates.stakeholder statement <root> --stage 1 --id ST1 --capture S1-M01 --kind brief_fact --quote "<exact words>" --brief-quote "<brief line>"
python3 -m gates.stakeholder lock <root> --stage 1 --capture <owner capture id> --quote "<owner's lock words>"
```

- The text file holds the message exactly as it appears in the chat (copied from the chat record, not retyped). The tool writes `captures/stage<N>_chat/<id>.txt` once, read-only, computes its sha256 and regenerates `SHA256SUMS`.
- Capture the Stakeholder's and the owner's messages the stage relies on (the parent's own questions may be captured too, speaker `lead`).
- Register only statements you will cite; a statement's quote must be in its capture. Kinds: `brief_fact` (with the brief line), `preference`, `clarification`, `twist`, `rule_change` (owner's words, or `--authorized-by <owner capture> --authorized-quote <words>`).
- Run the lock command only after the owner's own lock message is captured, and after the decision document (Stage 1) or framing (Stage 2) is final; the lock binds that file's hash.
- A rehearsal uses `--run-kind rehearsal` and `--label "REHEARSAL MOCK"` on every capture.
- Stage 1 and Stage 2 packets to the Lead Designer, Second Designer and Risk Reviewer list the conversation record and every capture as inputs (whole, with hashes), alongside the brief.

## Stage 3 packets for the Second Designer
- First packet: Stage 3 inputs only. Do not include the Lead Designer's draft or reasoning.
- After the Second Designer's independent design is sealed, send a second packet with the lead's design so the Second Designer can compare and report differences.

## Stage 2 packets for the Risk Reviewer
- Send the Lead Designer's framing for a check, alongside the Second Designer's critique.
- Send the G2F feasibility result for review.

## Stage 3 packets for the SQL Analyst
- Send the current design so the SQL Analyst can write the G3S source gates (extraction completeness, keys, joins, counts). The Gate Runner runs those gates through the Database Connector, which reports the snapshot it opened.

## Stage 3 packets for the Risk Reviewer
- Send the current design for a red-team.
- After the Gate Runner runs G3S, send the source-gate code and results for review.

## Stage 4 packets for the SQL Analyst
- Send the locked design and the frozen, hashed snapshot (not a live system) so the SQL Analyst can write independent SELECT-only queries; the Database Connector executes them read-only. Do not include R-A or R-B work before freeze.

## Stage 4 packets for the Risk Reviewer
- After the Gate Runner reconciles R-A, R-B, and SQL (G4b), send the reconciliation report and the reconciled evidence for the G4c review. Name the output paths in the packet.

## Case02 additions
- **Stage 5 review packets** list, as inputs, the claims ledger under review and the runner-written G5P record for that exact ledger (`artifacts/gates/history/G5P-*.json`). G0 fails a Stage 5 Second Designer or Risk Reviewer packet unless that record is a PASS for the same ledger path and hash with unchanged inputs and unchanged reports; a file merely named "precheck" does not count. A reviewer reads the precheck first and says whether each failing check is a real defect or a tool limit.
- **Stage 5 review record shape** (G5): `{"role", "subjects": [{path, sha256}], "findings": [{"id": "SD5-01", "class": "must_fix"|"advisory", "status": "open"|"closed", ...}], "claim_results": [...], "uncovered_claims": [], "verdict"}`. Ids carry the role: `SD5-` Second Designer, `RR5-` Risk Reviewer, `X5-` cross review. `uncovered_claims` is `[]` when every claim is covered, otherwise a list of claim ids; never a note. Every declared companion file of the finish package is a subject of both reviews.
- **Capture, then promote.** The step that saves a reply sets the packet to `captured`. `python3 -m gates.packet promote <root> <id>` sets it to `answered` only when G0 passes. Nothing may seal a captured packet's files.
- **Cite versioned paths.** A review should cite the ledger it read by its versioned copy (for example `outputs/<packet>/stage5_claims_vNN.json`). When the canonical ledger is replaced after a review cited it, the archiving step writes the H1 historical-send record (`artifacts/operations/finish.historical.json` and its supersession record); G5P and G5 fail an unresolved stale reference.
- **Revision briefs that change a report path** say, in the brief: "update the `deliverable` field of every claim that quotes the moved report, not only the deliverables list". G5P catches a miss before placement.
- **Builders' corrections** before send are logged in `artifacts/stage4/corrections.json`; the brief never asks the parent to unlock or re-freeze a builder's file, and the parent never writes the extract.
- **Owner decisions** in a packet or brief are stated plain-language first (what is being decided, the options, what each does), then the technical detail.
