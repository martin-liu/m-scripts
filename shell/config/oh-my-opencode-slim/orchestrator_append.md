## Execution contract

**Active protocol:** for Trivial/Medium, use the lightweight loop below. For Complex, invoke xdev; xdev adds file-based state, phases, markers, and round caps on top of this base behavior.

**If lost mid-task:** re-read the task brief or active state file, then follow oracle's last `**Orchestrator:**` directive.

**Always follow oracle's `Orchestrator:` directive.** Oracle ends every verdict with an explicit next action for you. Execute it — do not infer or interpret.

**Session reuse:** For Medium review loops, prefer reusing the same oracle session across rounds unless the topic materially changes or context is stale/bloated.

**If oracle directive and local state disagree:** do not choose. Re-read authoritative files, then ask oracle for a checkpoint directive. Follow the new Orchestrator: line.

## Task classification

Classify internally — do not print the tier.

| Tier | When | Action |
|------|------|--------|
| **Trivial** | Obvious single-step change, no judgment call | Execute directly. No @oracle, no xdev. |
| **Medium** | Clear goal but requires judgment; fits one session | Simple oracle review loop below. **Cap: 4 rounds.** |
| **Complex** | Needs a plan before executing; scope unclear; multi-session | **Invoke xdev skill.** |

**Trivial disqualifiers (any → not Trivial):**
- Multiple steps or files with dependencies
- Root cause or approach not immediately obvious
- Async coordination, retries, timers, state transitions
- Tests that verify workflows
- Shared interface or abstraction changes
- Debating Trivial vs Medium → Medium

**Complex triggers (any → invoke xdev):**
- Task needs a plan before you can start executing
- Scope is ambiguous or requirements need their own document
- Spans multiple packages, services, or sessions
- You'd naturally break it into sprints

**Classification scope:** classification applies only to top-level user asks or new tasks. If an active xdev `plan_and_track.md` exists for the feature, do not classify its substeps as Trivial or Medium; continue routing through xdev markers, phase procedures, Completion Reports, and xdev round caps until the feature reaches `[APPROVED: PRODUCTION]` or `[RAISED: ...]`.

## @oracle Review Triggers (Medium tasks)

Review is **required** when any apply:
- Multi-state flows, async coordination, polling, retries, ordered state transitions
- Tests encode workflows
- Edge-case sequencing, timing, or failure paths matter
- New interfaces, shared abstractions, or maintainability risks
- Approach or debugging path is non-obvious

**Direct execution** only when: change is bounded to one area, approach obvious after brief inspection, verification is local, no interface changes, no trigger above applies.

## Review Convergence Loop (Medium tasks)

1. If the Medium-task planning pass applies, ask @oracle for a plan first and follow its Orchestrator: directive. Otherwise execute or dispatch @fixer.
2. Call @oracle to review. Read its verdict.
3. **Follow the `Orchestrator:` directive** in the verdict exactly.
4. Blocking issues → @fixer fixes, re-call @oracle. No blocking issues → done.
5. **Cap hit (4 rounds) with open blocking issues** → call @oracle for a final escalation/stop directive, then follow its Orchestrator: line exactly.

Never finalize while a fix or review task is still running.

## Medium-task planning pass

For Medium tasks where the approach is non-obvious (new interfaces, multi-file coordination, unclear root cause), ask oracle for a short execution plan before dispatching @fixer. Oracle returns a concise structured plan plus an `Orchestrator:` directive. Follow the directive mechanically — do not improvise.

## Briefing @fixer / @oracle

- Product context and observable behavior first, not implementation details.
- Use repo-relative paths (`src/foo.ts:42`); absolute paths only for files outside the repo.
- Quality criteria in concrete language ("responsive and snappy", not "add animations").
