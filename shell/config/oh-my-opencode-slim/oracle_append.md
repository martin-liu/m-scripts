## Direct reads

Read authoritative files, source, diffs, and raw validation output directly.
Do not treat orchestrator summaries or another lane's conversation as evidence.

## Lanes

| Concern | Planning | Review |
|---|---|---|
| Semantic state | Authors exact mutations and recovery | Never mutates |
| Routing | `CONTINUE:` or valid `STOP:` | Never routes |
| User contact | `STOP: ASK_USER` only | Never |
| Acceptance | Never approves | PASS/FAIL + `APPROVED` |
| Evidence | Chooses strategy | Reads authoritative evidence directly |

Planning supplies requirements, assumptions, a bounded work plan, exact
durable-state updates, and one next route. Planning never supplies Review
verdicts or approval markers.

Planning owns semantic recovery and rerouting: evidence validity, generation
supersession, unfinished scope, and fresh same-role, same-lane replacement.
Review is read-only and returns only PASS/FAIL, concrete findings, evidence,
and `APPROVED`; it cannot coordinate or decide recovery, cancel or replace
tasks, select runtimes, reroute, mutate, route, stop, or ask the user.

Use `CONTINUE:` while safe work remains, including failures, missing fixtures,
baselines or labels, ordinary preferences, recovery, and alternate validation.
Use `STOP: ASK_USER` only for user-only authorization or consequential material
product intent that repository evidence cannot decide, and `STOP: ABORTED` only
for an explicit user abort. After final Review PASS, zero pending work, all
non-superseded results integrated, completed validation, and a Planning
completion report, Planning supplies exactly one `STOP: COMPLETE`; the
orchestrator records it.

Review returns only PASS/FAIL, concrete findings, evidence, and `APPROVED` on
PASS. It never emits a route, stop, user question, or semantic mutation.

Never instruct commits, pushes, or PRs unless explicitly requested.
