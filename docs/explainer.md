# The five stages, explained

1. **Start.** Find the decision behind the request and who makes it.
2. **Framing.** Turn it into one precise question: who or what is measured, over which window, what counts as better, and what threshold changes the decision.
3. **Feasibility, then Design.** First check whether the data can answer the question (yes, partly, or no), looking only at structure and quality, not values or the answer key. Then define every metric exactly, handle the edge cases, write test cases with known answers, have the design reviewed, and lock it with the owner.
4. **Execution.** Confirm the source with SQL source gates, then build the analysis twice in R and once in SQL, each independently. Test on the fixtures, reconcile, and release only when every gate passes.
5. **Finish.** Interpret only the sealed results, have the claims checked, recommend an action, and score blind afterwards. Stage 5 reuses the existing bots: the Lead Designer writes the interpretation, the Second Designer checks the inference, and the Risk Reviewer audits the numbers.

A mistake early carries forward, so Stage 3 matters most.
