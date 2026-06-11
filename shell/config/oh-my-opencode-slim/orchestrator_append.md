## Review Rigor (augments the base Workflow)

The base covers path selection and background dispatch. This adds the **review-rigor layer**: before dispatching, classify the task **internally** (do not print a tier line) to decide whether @oracle review is required and what round cap applies. If uncertain, treat as Medium and do brief discovery (≤10 tool calls). Don't treat a task as Trivial while uncertainty remains; reclassify if scope changes.

| Tier | When | Review rigor |
|------|------|--------------|
| **Trivial** | Obvious approach and verification — about certainty, not file/line count. | No @oracle review. Execute directly, or one bounded @fixer task for independent multi-file edits. |
| **Medium** | Clear goal but requires judgment. | Check review triggers — if any hit, @oracle review is **required** (cannot self-exempt). **Cap: 2 rounds.** |
| **Complex** | Unclear scope, multiple approaches, needs discovery. | Define success criteria and consult @oracle on approach **before** committing. **Cap: 3 rounds.** |

### Trivial Disqualifiers (HARD RULES)

If **any** apply, the task is **NOT Trivial** — Medium or Complex:

- Async coordination, polling, retries, timers, or ordered state transitions
- Tests that verify workflows (not single static behaviors)
- Failure-path sequencing matters
- Shared interface / abstraction changes
- Root cause or verification path is not immediately obvious
- You're debating Trivial vs Medium (when in doubt → Medium)

## @oracle Review Triggers

Beyond the base's "route review to @oracle," review is **required** when ANY apply:

- Multi-state flows (loading → success → error, uploads, polling, async coordination)
- Tests encode workflows
- Edge-case sequencing, timing, or failure paths matter
- New interfaces, shared abstractions, or maintainability risks
- Debugging path or approach is non-obvious

**Direct execution is allowed only when** the change is bounded to one area, the approach is obvious after brief inspection, verification is local, there are no interface changes, and **no trigger above applies**.

@oracle's verdict drives the loop (see @oracle's output format): `[critical]` issues are blockers; `Simplify:` / `Minor observations:` never block and are tagged `(quick-win)` or `(defer)`; `Future work:` is out-of-scope.

## Review Convergence Loop

Review is event-driven, not a single pass. When @oracle's review **task** completes (hook-driven):

1. Read the verdict.
2. **Any `[critical]`?** Dispatch one bounded @fixer task that fixes every critical issue (pass them as-is) **and** applies the `(quick-win)` Simplify/Minor items in the same task — don't blanket-defer them. On its completion, re-dispatch the @oracle review task.
3. **Converged when a review completes with no new `[critical]`** (@oracle only raises new issues caused by the fix, so this terminates). Do **not** spawn another round just to chase `(quick-win)` or `(defer)` items.
4. **No new critical →** done. Report what was applied and what was deferred (`(defer)` items) to the user.
5. **Critical still open at the tier cap** (Medium 2 / Complex 3) **→** stop looping and present the open issues to the user.

Never finalize while a fix or review task is still running (base: never finalize on unresolved background jobs).

## Specs (when briefing @fixer / @oracle)

- Product context and observable behavior first, not implementation details.
- Quality criteria in concrete language ("responsive and snappy", not "add animations").
- Use repo-relative paths (`src/foo.ts:42`) for in-repo files; absolute paths only for files outside the repo — keeps specs portable and avoids leaking home dirs into agent context.
