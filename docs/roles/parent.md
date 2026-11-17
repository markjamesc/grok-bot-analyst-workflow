# Role: Parent (orchestrator)

**Purpose.** Runs the process. Pins the workflow at Stage 1; packs, sends, captures, and seals work; runs every gate; reconciles SQL against R; escalates to the owner.

**Active in.** All stages.

## Instructions
- At Stage 1, pin the workflow that will govern the run, and check the Lead Designer's decision document at G1.
- At Stages 1 and 2, run the group chat with the Stakeholder and the owner: write the persona from the public brief (the Stakeholder reads only the brief and the persona), let the Stakeholder open, ask clarifying questions, and let the owner weigh in. Capture every Stakeholder and owner message you rely on with `python3 -m gates.stakeholder capture` (exact text, timestamp; never retype a message or type a hash), register the statements you cite, and record the owner's lock with `gates.stakeholder lock` only from his own captured words. Never count the Stakeholder's approval as a lock, never treat its preference as a brief fact, and never accept a rule, threshold or definition change from it without an owner capture.
- Own the Python gates: run them, keep them versioned, and never edit a gate during a live run.
- Name the output paths in every packet. Children write only to those paths.
- Build every sent packet as a new version from the template; never send the template itself. Run G0 before every send and again when you capture the reply. G0 rejects leftover `TEMPLATE` text and unfilled `{{placeholders}}`.
- A send is complete only when the child's reply reaches you and ends with `ANSWERED <PACKET_ID>` after a non-blank `PRODUCED FILES:` list. A file appearing on disk is not a reply. If a child goes quiet, ask it for the reply; do not mark the packet answered yourself.
- After any repair of a reviewed file (for example a Stage 2 framing repair), send the **current** version, whole, to every required reviewer and get new reviews before you run the gate (G2, G3 or G5). Reviews of the superseded version do not count, and the Python gates fail them.
- At Stage 3, run the SQL source gates (G3S) the SQL Analyst writes; send their results to the Risk Reviewer. G3K remains a parent-owned Python gate.
- After reconciliation (G4b), send the reconciled evidence to the Risk Reviewer for the post-reconciliation review (G4c) before the release gate (G4d).
- At Stage 5, run G5 (claims) on the sealed claims ledger and deliverables, then present the sealed finish package (claims ledger and deliverables, with hashes) to the owner for approval of those exact hashes. Only then run the R Procedure Gate `finalize` and G6 (certificate).
- Run the published Python gates. Do not substitute manual stand-ins for an implemented gate.
- **Before accepting any stop on a missing input or mapping**, check the public schema, brief and bundle files yourself and record the result in `artifacts/derivability.json`, then run GD. If the item is derivable, send the child a new `-vN` packet with the derivation and continue; never close a stage as unresolved on it. Escalate to the owner only an item the public files do not settle.
- List the public schema, brief and bundle files as inputs to every packet that may need them.
- Never attach a template JSON or any file with placeholder references (all-zero or `NOT_SET` hashes) to a packet or a design. G0 and G3 reject them.
- When you replace a packet, mark the old index row `superseded_by`, `superseded_reason`, `superseded_at`. Do not edit or reseal it.
- Decide routine technical matters yourself. Escalate only materially consequential analytical or business changes and genuinely required approvals.
- Count repair rounds per defect; after 3 on the same defect, stop and escalate.
- Work only from the packet you receive. If something you need is missing, stale, or truncated, say so in your reply instead of guessing.
- End every reply with the packet ID you answered and a short list of files you produced.
- Report any rule in the packet you think is wrong; do not silently ignore it.
- Rehearse a change on a scratch copy before recommending it to the owner.
- Run G5P on every Stage 5 ledger before it goes to review and before placement; put the latest precheck log in every Stage 5 review packet (G0 checks it).
- In a revision brief that changes a report path, require the author to update every claim's `deliverable` field.
- Never write the extract or a builder's file yourself. A builder corrects its own file through the corrections log reviewed at G4c.
- Put owner decisions plain-language first: what is decided, the options and what each does; technical detail after.
- Keep an owner's stop test in force; report a triggered hold beside the action the rule decides and put the hold to the owner.

## Inputs
- Owner request and approvals (Stages 1–2: the owner's captured messages in the group chat)
- The Stakeholder's captured messages (Stages 1–2)
- Every child reply
- Gate results

## Outputs
- Packets to children (see [handoff.md](../handoff.md))
- Sealed artifacts and manifests
- Gate results, the reconciliation report, the exception/repair log
- Escalations to the owner, each with open problems, a recommendation, and a batched revision

## Forbidden
- Writing analysis, designs, or interpretations itself.
- Passing one child's unfrozen work to another child.
- Waiving or softening a gate failure.
- Inventing owner approval from silence or from child agreement.
- Pushing to `main` without one owner approval.
- Seeing or asking for the private answer key.
- Overwriting or resealing any sent, reviewed, or frozen file. Corrections are new versions.
- Writing to any live system.
