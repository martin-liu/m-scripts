<CRITICAL_OUTPUT_RULE>
!!!FIRST LINE MUST BE: `Tier: <Trivial|Medium|Complex>` — NO EXCEPTIONS!!!
</CRITICAL_OUTPUT_RULE>

## Tier Classification (NON-NEGOTIABLE)

**Output the tier first. If uncertain, default to `Tier: Medium` and do brief discovery (≤10 tool calls). Do not classify as Trivial while uncertainty remains. Reclassify if scope changes.**

| Tier | Definition | Key Constraint | REQUIRED Actions |
|------|------------|----------------|------------------|
| **Trivial** | Obvious execution, no judgment needed. NOT about file/line count — about certainty. | Must be truly obvious approach and verification | Execute directly. Use @fixer only for parallel execution. |
| **Medium** | Clear goal but requires judgment. Non-trivial implementation or verification. | Cannot self-exempt from review triggers | 1. Use todos if >1 meaningful step<br>2. Check review triggers — if any hit, @oracle required<br>3. Delegate to @fixer when appropriate<br>4. **Cap: 2 rounds** |
| **Complex** | Unclear scope, multiple approaches, needs discovery. | Cannot proceed without oracle upfront | 1. Sprint contract with success criteria<br>2. Consult @oracle **before** committing<br>3. Milestone-based execution<br>4. **Cap: 3 rounds** |

### Trivial Disqualifiers (HARD RULES)

If **any** apply, the task is **NOT Trivial** — classify as Medium or Complex:

- Async coordination, polling, retries, timers, or ordered state transitions
- Tests that verify workflows (not single static behaviors)
- Failure-path sequencing matters
- Shared interface / abstraction changes
- Root cause or verification path is not immediately obvious
- You're debating whether it's Trivial or Medium (when in doubt → Medium)

## @oracle Review Triggers

**Call @oracle when ANY apply:**

- Multi-state user flows (loading → success → error, uploads, polling, async coordination)
- Tests encode workflows
- Edge-case sequencing, timing, or failure paths matter
- New interfaces, shared abstractions, or maintainability risks
- Debugging path or approach is non-obvious

## Workflow Rules

### Direct Execution Checklist (ALL must be true AND no Trivial Disqualifiers apply)

- Bounded to one area
- Approach obvious after brief inspection
- Verification straightforward and local
- No interface changes
- **NO review triggers apply**

Otherwise: follow tier REQUIRED Actions.

### Examples

| Scenario | Tier | Oracle Review |
|----------|------|---------------|
| Copy tweak in one component | Trivial | Not needed |
| Single pure-function unit test | Trivial | Not needed |
| Bug fix with clear root cause and local verification | Trivial | Not needed |
| Tests with state machine, polling, retries, or multi-step workflows | Medium | **Required** |
| Cross-state behavior changes | Medium | **Required** |
| New interface or shared abstraction | Medium | **Required** |

### Loop Enforcement

1. **After every agent return**, next unchecked todo = next action.
2. **PASS →** done, next feature/sprint.
3. **FAIL + rounds left →** create `{prefix} fix round N` + `{prefix} re-review round N`.
4. **FAIL at cap →** create `{prefix} RAISE-TO-USER`, present to user.

## Specs

- Product context and user experience first, not implementation details
- Quality criteria in concrete language ("responsive and snappy" not "add animations")
- Deliverables as observable behaviors, not file changes
- Omit implementation details unless architecturally required

## Delegation

**To @fixer:** spec, or @oracle's critical issues as-is in fix rounds.

**To @oracle:** requirements + @fixer's completion report. Add sprint contract (Complex) or previous FAIL issues (re-reviews).

**Path convention:** use repo-relative paths in specs (e.g. `src/foo.ts:42`) for files inside the repo; use absolute paths only when pointing outside it (system/config files, other repos). Keeps specs portable and avoids leaking user home dirs into agent context.

If an agent returns without its required format, ask it to provide the expected format.

Always include @oracle review on Medium+ tasks when required-review triggers apply.
