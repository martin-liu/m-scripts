## Non-trivial convergence

For every Medium or xdev task, create distinct Planning and Review sessions. A
Planning session never becomes Review, and vice versa. Planning routes work;
Review independently accepts it; fixer executes only Review-approved work, except
for a Planning-authored final-verification plan containing only local,
non-privileged, non-external, non-side-effectful read-only commands.

Track every dispatched task by role, lane, generation, scope, status, and
progress, and integrate every non-superseded result. Completion requires a
final independent Review PASS, a Planning completion report, no pending tasks,
all non-superseded results integrated, and required validation complete.
Planning then supplies `STOP: COMPLETE`; the orchestrator records it and
terminates the loop. No approval marker or fixer report completes work by itself.

### Liveness and replacement

Only on a transport resume inspect a task with `task_status` or `task_result`;
never poll. After two unchanged resumes, send exactly one `task_message`, then
inspect at the next resume. An active stale task gets `task_cancel` before a
fresh same-role, same-lane replacement. A terminal failed, cancelled,
unreachable, or unusable task is replaced without cancel. Do not use
`task_revive` for stale or failure recovery. Preserve integrated evidence, mark
the prior generation superseded, and give the replacement only unfinished scope.
Never integrate late output from a superseded generation. Do not cross lanes,
reuse, duplicate, or drop work, and do not wait indefinitely; recoverable
failures are `CONTINUE`, not `ASK_USER`.

### Medium loop

1. Planning supplies one bounded work plan: scope, allowed files, acceptance
   criteria, validation command, and assumptions.
2. Review reads authoritative files and returns PASS or concrete findings.
3. On PASS, fixer implements only that plan and returns changed paths plus raw
   validation output.
4. Review evaluates changed files and raw evidence.
5. On FAIL, send Review findings and raw evidence to Planning. Planning selects
   a revised plan or an explicitly bounded fixer correction.
6. On final PASS, Planning supplies the completion report and `STOP: COMPLETE`.

Do not create additional verifier artifacts, recovery contracts, or approval
layers unless the feature itself requires them. Repeated findings require a
changed approach, not more bookkeeping. Transport waits preserve active work and
never produce a final response.

## Task classification

- **Trivial:** one obvious bounded change; execute directly and verify locally.
- **Medium:** requires judgment but fits one session; use the loop above.
- **Complex:** requires durable multi-sprint state; use xdev.

## Safety

Use `CONTINUE` for safe investigation, reversible assumptions, recovery, and
alternate validation. Failures, missing fixtures/baselines/labels, ordinary
preferences, and alternate-validation needs are `CONTINUE`. Do not perform
destructive, irreversible, privileged, externally side-effectful,
security-sensitive, real-API, real-DB, or full-system actions without explicit
authorization. Planning supplies `STOP: ASK_USER` only for user-only
authorization or consequential material product intent that repository
evidence cannot decide.
