# Persistent lessons

Lessons from benchmark runs are kept as process rules, never as case content or answers.

Format: `ID | observed failure (generic) | rule change | regression test (name or NOT YET WRITTEN)`.

Seed lessons (generic):
- L1 | Large design outputs truncated in one reply | request in parts from the start | GP assembly test (NOT YET WRITTEN)
- L2 | Review counted on a stale or partial file | review coverage requires whole current files | G0/G3 coverage test (NOT YET WRITTEN)
- L3 | Counting/key errors found late | run early key/count checks at Stage 3 | G3K test (NOT YET WRITTEN)
- L4 | External account lockouts stalled a run | wait and retry up to 3 times, then report | none
