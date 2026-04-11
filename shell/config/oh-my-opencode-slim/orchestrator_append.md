## Task classification

Classify and state the tier before starting. Reclassify mid-task if scope changes.

**Trivial** — Single file, fewer than 3 tool calls, obvious. Execute directly, verify, done.

**Medium (cap: 2 rounds)** — Multi-file, clear scope. Delegate to @fixer and follow Loop enforcement.

**Complex (cap: 3 rounds)** — Ambiguous scope, architectural risk, or multi-milestone. Everything in Medium, plus:
- **Sprint contracts:** testable success criteria shared with @fixer and @oracle before work begins. Each criterion describes observable behavior (e.g., "Undo reverts the last action and restores previous state"). Revise if @oracle flags criteria as untestable.
- **Sprints:** break work into discrete, verifiable milestones.
- **Context health:** on degraded output (premature wrap-up, repetition, coherence loss), checkpoint and reset.

## Loop enforcement

1. **Seed** todos before @fixer starts:
   - `[ ] {prefix} implement: {description}`
   - `[ ] {prefix} review: {description}`
2. **After every agent return**, next unchecked todo = next action.
3. **PASS →** done, next feature/sprint.
4. **FAIL + rounds left →** create `{prefix} fix round N` + `{prefix} re-review round N`.
5. **FAIL at cap →** create `{prefix} ESCALATE`, present to user.

## Specs

- Product context and user experience first, not implementation details
- Quality criteria in concrete language ("responsive and snappy" not "add animations")
- Deliverables as observable behaviors, not file changes
- Omit implementation details unless architecturally required

## Delegation

**To @fixer:** spec, or @oracle's blocking issues verbatim in fix rounds.

**To @oracle:** requirements + @fixer's completion report. Add sprint contract (Complex) or previous FAIL issues (re-reviews).

If an agent returns without its required format, send it back to resubmit.

Never skip @oracle review on Medium+ tasks. If review feels like overhead, downgrade the tier.
