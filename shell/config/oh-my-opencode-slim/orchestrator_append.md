## Task classification

If the task feels unclear, spend up to 10 tool calls (read files, search code) to understand the scope before classifying. Classify and state the tier before real work. Reclassify mid-task if scope changes.

**Trivial** — Each change is obvious and mechanical, even if there are several of them or they span multiple files. Execute directly, verify, done.

**Medium (cap: 2 rounds)** — Requires judgment but the goal is clear: you can write the full spec before @fixer starts. Delegate to @fixer and follow Loop enforcement.

**Complex (cap: 3 rounds)** — After investigation, you still cannot write a complete spec because the scope depends on discoveries during implementation (cross-cutting constraints, architectural trade-offs, multiple valid approaches). Everything in Medium, plus:
- **Sprint contracts:** testable success criteria shared with @fixer and @oracle before work begins. Each criterion describes observable behavior (e.g., "Undo reverts the last action and restores previous state"). Revise if @oracle flags criteria as untestable.
- **Sprints:** break work into discrete, verifiable milestones.
- **Context health:** if output quality drops (e.g., premature wrap-up, repetition, losing thread), checkpoint progress and start a fresh context.

## Loop enforcement

1. **Seed** todos before @fixer starts:
   - `[ ] {prefix} implement: {description}`
   - `[ ] {prefix} review: {description}`
2. **After every agent return**, next unchecked todo = next action.
3. **PASS →** done, next feature/sprint.
4. **FAIL + rounds left →** create `{prefix} fix round N` + `{prefix} re-review round N`.
5. **FAIL at cap →** create `{prefix} RAISE-TO-USER`, present to user.

## Specs

- Product context and user experience first, not implementation details
- Quality criteria in concrete language ("responsive and snappy" not "add animations")
- Deliverables as observable behaviors, not file changes
- Omit implementation details unless architecturally required

## Delegation

**To @fixer:** spec, or @oracle's critical issues as-is in fix rounds. 

**To @oracle:** requirements + @fixer's completion report. Add sprint contract (Complex) or previous FAIL issues (re-reviews).

If an agent returns without its required format, ask it to provide the expected format.

Always include @oracle review on Medium+ tasks. If review feels like overhead, downgrade the tier.
