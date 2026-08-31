# xdev

xdev is the durable lifecycle for complex work: requirements → design →
reviewed sprints → final verification. `plan_and_track.md` is the sole durable
state file.

## Authority

| Role | Owns |
|---|---|
| Planning | requirements, assumptions, design, contracts, routes, reports, `CONTINUE`, and `STOP` |
| Review | independent PASS/FAIL, findings, and `APPROVED` markers |
| Fixer | approved bounded changes, raw evidence, and Completion Reports |
| Orchestrator | lane/runtime tracking, exact recording, task coordination, and final STOP transition |

Planning and Review have immutable distinct lanes. On runtime failure, retire only
that lane's runtime and append a fresh same-lane generation; never cross-reuse a
runtime.

## Completion

Completion requires five durable facts: final independent Review `PASS`, a
Planning completion report, zero pending tasks, all dispatched results
integrated, and all required validation complete. Planning then supplies
`STOP: COMPLETE`; the orchestrator records it as the final transition. Review,
fixer, approval markers, and transport notifications never complete the lifecycle.

## Resume

Read `Latest marker`, `Current sprint`, `Next owner`, `Next action`, Lane
Durability, unresolved escalations, and the latest verdict. Preserve history;
never infer missing state. A marker, sprint, or lane-generation change
replaces a stale next action.

## Lifecycle

1. Planning drafts requirements and may ask targeted material product questions.
2. Review approves requirements.
3. Planning authors design, Global Flow, assumptions, and sprint list.
4. Review approves design.
5. For every sprint: Planning contract → Review contract → Fixer → Review →
   Planning report.
6. Planning supplies a bounded final-verification plan. Fixer runs its read-only
   commands; Review approves production. A separate Review approval is required
   first only for file-changing, privileged, external, or side-effectful checks.
   Planning then supplies the final report and `STOP: COMPLETE`.

After requirements approval, ordinary missing fixtures, baselines, labels, or
preferences use assumptions or alternate validation. Only unavoidable user-owned
intent or authorization permits `STOP: ASK_USER`.

Repeated findings return to Planning. Planning materially changes or narrows the
approach before retrying; repeated findings never stop work automatically.

## Verification

Use existing tests, lint, typecheck, build, or genuine product-level integration
checks. Do not create a bespoke verifier or evidence artifact merely to prove a
workflow contract. Review reads raw evidence directly.
