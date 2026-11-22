---
name: judgment-checks
description: Lead Designer, Second Designer and Risk Reviewer. Load before writing or reviewing any framing, design, claim, disclosure or review verdict. Author steps run after drafting and before replying; reviewer steps find where the author skipped them.
---

# Judgment checks (v03: owner-approved 2026-11-22; adds checkable tasks, first-answer rule, three separate claims and stage questions to v02 of 2026-11-16)

## Why this exists
Most slips in our runs were not arithmetic. They were calls made from memory: a status word nobody re-opened, a definition that let one record be read two ways, a required item lost while text moved, a reviewer who rated a real defect as advisory. Re-reading your own draft rarely finds these. Opening the record does. So every check below asks you to open something and quote it, not to think harder.

This skill does not replace gates, prechecks or your role rules. If they disagree, your role rules and the packet win; say so in your reply.

## Words used here
- **Record**: a file on your INPUTS or ALLOWED TO SEE list (a sealed review, gate log, locked design, approval, ledger, brief, or a Stakeholder or owner chat capture). A Stakeholder preference or a "the brief doesn't say" answer is a record of a preference, not of a fact.
- **Claim**: any sentence in your output that states a fact, a status, a grade, a cause or a judgment.
- **Status word**: resolved, closed, open, PASS, FAIL, confirmed, clean, accepted, locked, none.
- **Required item**: every requirement, owner hold, owner limit, carried advisory, fix-request line and required disclosure handed to you.

## Author steps (Lead Designer; Second Designer when it writes a blind rebuild or design)
Draft first. Then stop at this pause point, before you write your reply, and do each step.

1. **Source every statement.** Each claim points to a record, a locked rule, or is marked "inferred" with its reason. If you need a fact no record gives, do not supply it: write `MISSING INPUT: <item>` and leave that claim out. Never fill a gap with a plausible owner, threshold, cut-off or criterion. A judgment word (dominant, material, small, enough) needs a locked threshold behind it, or it does not go in.
2. **Claim to record.** For every status word, citation, cause and disclosure: open the cited record now, find the line, and copy the key words into your notes. Ask "what does the record say?", not "is it resolved?". Write what the record says, not why it happened (say "recorded as FAIL", not "not evaluated"). A citation must point to a file that actually contains the rule. If the record and your claim differ, change the claim.
3. **Inputs to deliverable.** List every required item from your packet. Mark each one: used (where), carried forward (to where), or not applicable (why). Do this again after every move, split, merge or correction of text, and fix every other place that restates a corrected point. A hold or stop sits beside the rule's action and never replaces it. A locked item is never narrowed or widened without an owner decision.
4. **Pin every definition.** For each unit, class, numerator and denominator: say which record counts when a unit appears more than once, show that each record lands in exactly one class, and confirm every numerator counts only members of its own denominator.
5. **Test each rule at its edges.** For each rule, stop test and guard, try the cases most likely to break it: the largest value it must bound, mixed cases, empty or blank, ties, and repeats. Name in your notes the case you tried and the result.
6. **Grade no higher than the weakest support.** Any strength word or grade (yes, confirmed, strong, high) is limited by the weakest record under it. Anything resting on a statement the data cannot check is at most "partly". Category matters too: evidence for one term cannot be counted as evidence for another.
7. **Fill the self-check block** (template below) and put it in your reply body, before the reply ending. Never put it inside a deliverable file.

## Reviewer steps (Second Designer and Risk Reviewer reviewing someone else's work)
Find where the author did not do the author steps. Work record-first: open the cited record and write down what it says before you read the author's reasoning about it.

R1. **Unsourced statements.** Find claims with no record, locked rule or "inferred" mark, and judgment words with no locked threshold.
R2. **Claims vs records.** For every status word, citation, cause and disclosure, open the cited record and compare finding by finding. Do not trust the author's self-check block; check at least every status word and every disclosure yourself.
R3. **Dropped or drifted items.** Start from the packet's required items (not from the deliverable) and trace each into the work. Check that corrections were made everywhere the point is restated, and that no hold replaces an action.
R4. **Definitions.** Try to class one record two ways, or count a numerator member outside its denominator.
R5. **Edges.** Try the largest value, mixed, blank, tie and repeat cases against each rule and guard.
R6. **Grades.** Find any grade above its weakest support, or evidence counted in the wrong category.
R7. **Self-check block.** Missing, or any line without evidence, is a finding.

**Severity rule.** must_fix if the slip would leave a claim, number, status, definition, rule, disclosure or required item wrong in what gets locked or delivered, so that the owner or a later stage would act differently. advisory for a real gap that changes nothing anyone would act on (for example a paraphrase that keeps the meaning, or a missing breakdown when the total is already backed by a record); give one line saying why it changes nothing. If you are unsure, ask that one question: would anyone act differently if this stayed? Yes, or the records can't tell you, means must_fix, and name the action that changes. No means advisory. Rating a real defect as advisory has been our most common reviewer slip, so a wrong number, status word, owner or grade, or a missing or dropped disclosure is always must_fix.

**Accept rule.** Do not accept until you have done R2 and R3 yourself and listed what you opened. "No findings" must name the records checked.

## Checkable tasks, first answers and stage questions (v03)
**Checkable task.** Every review does at least one task someone else could repeat, and names it in the reply: recompute a named number from the sealed results, open a named source and quote the line, work a hidden or decision-flip fixture by hand, or name one specific unsupported inference. "Looks fine" or "no concerns" without a task is not a review.

**First independent answer.** Submit your review (or design, or build), and have it captured and sealed by the Gate Runner, before you see a peer's conclusion. If you change it after seeing theirs, write a new version and keep the first; say what changed and why.

**Three claims, judged separately.** (a) Does the result reproduce on the frozen data? (b) Does it hold up under other defensible analytical choices? (c) Does the recommendation fit the action the business faces? A pass on one is never evidence for another. The Risk Reviewer leads on (a); the Second Designer on (b) and (c).

**Stage questions.**
- Stage 1: are keeping the current policy and waiting or deferring real options? Does the question or decision rule presuppose the hoped-for conclusion?
- Stage 2, Risk Reviewer: "Could we observe the finding this question measures even if the proposed action would do little good? What evidence would distinguish that situation?"
- Stage 2, Second Designer: "Could two competent analysts read a key term differently and produce answers that would matter differently to this executive? Give one example where the meanings come apart."
- Stage 3: does each decision-flip fixture (exact threshold, pooling, missing values, duplicate joins) really flip the decision if the mistake is made? Is every tolerance on a rounding field only?
- Stage 5: is the recommended action the best justified one given uncertainty, costs, reversibility and alternatives, with no change weighed as a real option? Is any causal claim stated separately and supported by the design?

Use the existing record (brief, captures, locked files) before asking the owner anything; let a clear case pass without extra questions.

## Self-check block template (author)
```
JUDGMENT SELF-CHECK
1 Sources: every claim has a record, locked rule or "inferred" mark: yes/no. MISSING INPUT lines: <list, or omit the line if none>
2 Claim to record: status words and disclosures checked: <n>. Each: <claim id> -> <record path> "<key words quoted>"
3 Inputs to deliverable: required items <n>: used <n>, carried <n>, not applicable <n> (reasons). Re-run after last text move: yes/no
4 Definitions pinned (unit, repeats, one class per record, numerator within denominator): yes/no, where
5 Edge cases tried: <rule id>: <case> -> <result>
6 Grades at or below weakest support: yes/no, lowest support named for each grade
```
If nothing is missing, follow the packet's ending format; do not write "MISSING INPUT: none." unless your packet says the gate accepts it.

## Examples (types only, from our earlier runs)
- A ledger claim said review advisories were resolved; the sealed review still showed them open. Step 2 catches it: open the review, quote the status.
- A required disclosure disappeared from the report after text moved to a companion file. Step 3, re-run after the move, catches it.
- A stop option replaced the rule's action although an input rule forbade that. Step 3 catches it.
- A guard was checked against one product, not the largest value it had to bound. Step 5 catches it.
- A framing let a unit in two groups be counted in both. Step 4 catches it.
- A decision owner was written that the request never named. Step 1 catches it.
- A reviewer rated a stale version reference as advisory. The severity rule makes it must_fix.

## Limits
Both reviewers come from the same model family, so they can share blind spots. This skill makes each pass more systematic; it does not make them independent. It adds a few minutes of checking per reply and should not add sends.

## How roles use it
- Lead designer: author steps 1-7 on every framing, design, claim or disclosure reply; self-check block in the reply body only.
- Second designer: reviewer steps R1-R7 plus the severity and accept rules on every review; author steps on any blind rebuild.
- Risk reviewer: reviewer steps R1-R7 plus the severity and accept rules on every review.
Every reviewer also does the checkable task, first-answer and three-claim steps above. Stages and send counts are unchanged; the gates that back these steps are listed in docs/stages.md ("Workflow changes").
