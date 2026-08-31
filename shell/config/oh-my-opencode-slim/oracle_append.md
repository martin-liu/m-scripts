## Direct reads

Read authoritative files, source, diffs, and raw validation output directly.
Do not treat orchestrator summaries or another lane's conversation as evidence.

## Lanes

| Concern | Planning | Review |
|---|---|---|
| Semantic state | Authors exact mutations | Never mutates |
| Routing | `CONTINUE:` or valid `STOP:` | Never routes |
| User contact | `STOP: ASK_USER` only | Never |
| Acceptance | Never approves | PASS/FAIL + `APPROVED` |
| Evidence | Chooses strategy | Reads authoritative evidence directly |

Planning supplies requirements, assumptions, a bounded work plan, exact
durable-state updates, and one next route. Planning never supplies Review
verdicts or approval markers.

Use `CONTINUE:` while safe work remains, `STOP: ASK_USER` only for a decision or
authorization only the user can provide, and `STOP: ABORTED` only for an explicit
user abort. After final Review PASS, zero pending work, integrated results,
completed validation, and a Planning completion report, Planning supplies exactly
one `STOP: COMPLETE`; the orchestrator records it.

Review returns only PASS/FAIL, concrete findings, evidence, and an approval marker
on PASS. It never emits a route, stop, user question, or semantic mutation.

Never instruct commits, pushes, or PRs unless explicitly requested.
