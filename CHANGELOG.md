# Changelog

All notable changes to this design draft are recorded here. Dates are America/Chicago.

## 0.1.1 — 2026-11-09

- Corrected the approved post-benchmark change list to all ten items. Item 7 (feasibility gate sees structure and quality only, not values or the answer key) is now listed separately from item 3 (the data-feasibility gate itself).
- Locked Stage 5 to reuse the existing bots: the Lead Designer writes the interpretation, the Second Designer checks the inference, and the Risk Reviewer audits the numbers. No dedicated finish bots.
- Recorded copyright: the owner holds copyright; no LICENSE file; no license is granted.
- Recorded scoring and lock rules: the earlier key preparer from the ChatGPT (Version 1) side holds the private key and scores blind; Version 2 seeks an official lock; Version 1 is scored on accuracy only.
- Recorded the run cap: one attempt per version on Case B, a maximum of 3 repair rounds, stop and report after about a day of work per side, and retry up to 3 times if blocked.

## 0.1.0 — 2026-11-09

- Initial local design of the Grok Bot team workflow: parent plus six child roles, five stages, gate list, handoff format, and comparison protocol.
- Incorporates the approved post-benchmark changes as design requirements (Python gates with parity tests, analysis in R, data-feasibility gate, fewer clearer rules, greater autonomy, persistent lessons, large outputs in parts, early key/counting checks with a 3-round repair cap, and the explainer).
- Gate code and parity tests are specified only and marked **NOT IMPLEMENTED**. No tests were run.
- Public-scope rule added: method only; no keys, case data, evidence packets, account identifiers, or private paths.
