# xdev — Phase Procedures

> **Reference file — loaded on demand.** Load this file (`$SKILL_DIR/reference/phases.md`) when the Marker Reference table in `SKILL.md` routes you into a phase. The router and invariants (Marker Reference, Role Model, Severity Levels, Round-Cap Semantics, Completion Report definition, Raised-State Recovery, Doc-as-State) live in `SKILL.md` and are assumed already in context.

## Lifecycle — 4 Phases

Happy path: `(none)` → `[APPROVED: REQUIREMENTS]` → `[APPROVED: DESIGN]` → (if Sprint List non-empty) `[APPROVED: SPRINT_N_CONTRACT]` + `[APPROVED: SPRINT_N]` × N → `[APPROVED: PRODUCTION]`

**Design revisions** during Phase 3 produce `[APPROVED: DESIGN_REV_N]` — lifecycle position unchanged; resume current sprint per marker table.

**Verdict history:** evaluator always **appends** new verdict entries to the relevant section (`## Requirements Review`, `## Design Review`, `## Production Review`, sprint `#### Contract Review Verdict`, sprint `#### Evaluation Verdict`). Never overwrite previous verdicts — history is preserved for debugging.

**`Current sprint:` ownership:** planner sets it when appending a new sprint block (3a). Orchestrator sets it to `(none — zero sprints)` at end of Phase 2 if Sprint List is empty. Evaluator sets it to `(complete)` when writing `[APPROVED: PRODUCTION]`.

**Zero-sprint:** `[APPROVED: DESIGN]` with empty Sprint List routes to Phase 4. Phase 4 still runs in full; generator still runs the test suite.

**Sprint list mutation:** planner may add, remove, or reorder **future unapproved** sprints at any time; record the change under `## Design Revisions`. Already-approved sprints cannot be modified — use `[INVALIDATED: SPRINT_M]` annotation in that sprint's verdict section instead.

**Sprint granularity:** a sprint should be small enough to implement, validate, and review within the configured round cap. If a planned sprint is too large, split it into multiple sprints during Phase 2 step 2 or before writing its contract.

---

### Phase 1 — Frame

**Goal:** Lock scope before any design work.

**Round cap: 3. Track in `## Phase Rounds` → `Requirements: Rounds: N/3`.**

1. Read project `CLAUDE.md` / `AGENTS.md` (if present) for red lines and conventions.
2. Explore codebase for prior art. Delegate to `{researcher}` (if bound) for broad searches or unfamiliar libraries.
3. `{planner}` fills the `## Requirements` section. All open questions must be resolved — leave none blank.
4. `{evaluator}` reviews: clarity, scope discipline, missing constraints, unresolved open questions. Appends verdict to `## Requirements Review` using the format pre-seeded in that section. Increments `Requirements: Rounds:`.
5. `{planner}` (fresh instance) fixes; `{evaluator}` re-reviews (writes new verdict in `## Requirements Review`). Cap: 3 rounds total. Cap hit → write `[RAISED: REQUIREMENTS]` + escalation summary under `## Escalations`.
6. On PASS: `{evaluator}` writes `[APPROVED: REQUIREMENTS]` as `Latest marker:`.

**Scope change after approval:** orchestrator writes `[ABORTED: REQUIREMENTS — {reason}]`; re-enter step 3.

---

### Phase 2 — Design

**Goal:** Architecture locked, sprint list drafted — no implementation yet.

**Round cap: 3. Track in `## Phase Rounds` → `Design: Rounds: N/3`.**

1. `{planner}` fills the `## Design` section.
2. `{planner}` drafts the `## Sprint List` table: titles + one-line scope only. Leave empty if no implementation needed.
3. `{evaluator}` reviews design for correctness, security, over-engineering, gaps. Writes verdict in `## Design Review` in `plan_and_track.md`. Increments `Design: Rounds:`.
4. `{planner}` (fresh instance) fixes; `{evaluator}` re-reviews (writes new verdict in `## Design Review`). Cap: 3 rounds. Cap hit → write `[RAISED: DESIGN]` + escalation summary.
5. On PASS: `{evaluator}` writes `[APPROVED: DESIGN]`. Orchestrator updates `Current sprint:` to `(none — zero sprints)` if Sprint List is empty.

**Design change after approval:** orchestrator writes `[ABORTED: DESIGN — {reason}]`; re-enter step 1.

---

### Phase 3 — Sprint Loop

Repeat for each sprint in order. **Do not start Sprint N+1 until `[APPROVED: SPRINT_N]` is set.**

For each new sprint, `{planner}` appends `sprint_block.md` content (with N and title substituted) under `## Sprint Log` in `plan_and_track.md`, and sets `Current sprint:` to `N`.

**Pre-existing test failures:** validation commands must be scoped to the sprint's new tests. If a broader test suite is unavoidable, the contract's `Out-of-scope` must list pre-existing failing tests by name — these are excluded from the FAIL criteria.

#### 3a — Draft Contract

`{planner}` writes the contract. Consult `{researcher}` (if bound) before finalizing criteria referencing unfamiliar libraries.

```markdown
#### Contract
- **Scope:** which subsections of ## Design apply
- **Success criteria:** (hard thresholds — each independently verifiable)
  - [ ] `<test command>` exits 0
  - [ ] `<file or output>` exists / matches expected
- **Out-of-scope:** what NOT to touch this sprint; pre-existing failures to exclude
- **Validation command:** `<scoped command that proves all criteria>`
```

*Success criteria* = assertions. *Validation command* = the command that checks them. Both required.

#### 3b — Review Contract

`{evaluator}` checks: are all success criteria hard thresholds verifiable without interpretation? Appends verdict to the `#### Contract Review Verdict` block using the format pre-seeded there.

- **PASS** → write `[APPROVED: SPRINT_N_CONTRACT]`. **Minor-only findings are PASS** — note them, don't fail.
- **FAIL** (critical or major only) → `{planner}` (fresh instance) rewrites. Cap: 2 rounds. Cap hit → write `[RAISED: SPRINT_N_CONTRACT]` + escalation summary.

#### 3c — Implement

`{generator}` reads: sprint contract, referenced `## Design` subsections, relevant source files. Implements, runs validation command. **Generator must not submit a Completion Report with a failing validation command — fix failures first.**

**Generator stuck:** if the validation command cannot be made to pass (e.g. pre-existing infrastructure failure, blocked dependency), generator stops and surfaces the blockage to the orchestrator. The orchestrator writes a `Delegation failure: validation blocked — [reason]` note under `## Escalations` and surfaces to the user before proceeding.

Generator **fills** the `#### Completion Report` section under the existing heading in the sprint block (see **Completion Report: Submitted Definition** in `SKILL.md` — all three fields must be populated):

```markdown
#### Completion Report
- **Files changed:** (list — at least one entry required; use `git diff --name-only` to populate)
- **Validation output:** (paste or summary — required)
- **Criteria status:**
  - [x] criterion 1 — passed
  - [ ] criterion 2 — pre-existing failure: [test name] (excluded per contract Out-of-scope)
- **Notes:** (deviations from contract, if any)
```

All new-code criteria must be `[x] — passed`. The only allowed `[ ]` entries are pre-existing failures named in the contract's `Out-of-scope`.

#### 3d — Evaluate

`{evaluator}` reads contract + Completion Report, spot-checks changed files. Appends verdict to the `#### Evaluation Verdict` block using the format pre-seeded there.

- **PASS** → write `[APPROVED: SPRINT_N]`. **Minor-only findings are PASS** — note them in the verdict, don't fail.
- **FAIL** (critical or major only) → proceed to 3e.

#### 3e — Fix

`{generator}` addresses critical and major issues, updates Completion Report. Minor issues are advisory — but since a round is already running, generator also applies the quick-win minors (low-risk, bounded, in-scope) here per the Severity Levels rule (in `SKILL.md`); the rest stay in the verdict notes for the user. Back to 3d. **Cap: 2 rounds total (tracked in `Rounds:` of the Evaluation Verdict).** Cap hit → write `[RAISED: SPRINT_N]` + escalation summary.

**Mid-sprint design change:** if implementation reveals a design error → write `Design Rev N: Paused sprint: M — [what changed and why]` under `## Design Revisions` and add `Design Rev N: Rounds: 0/2` under `## Phase Rounds` → `{planner}` updates the `## Design` section → `{evaluator}` appends verdict to `## Design Revisions` using the format pre-seeded in that section.

Cap: 2 rounds total. Cap hit → write `[RAISED: DESIGN_REV_N]`. On PASS → write `[APPROVED: DESIGN_REV_N]`. Resume per marker table conditional (evaluator checks if contract is now stale → 3a if stale). If change invalidates an approved sprint, add `[INVALIDATED: SPRINT_M]` to that sprint's verdict section.

---

### Phase 4 — Close

**Goal:** Ready-to-ship sign-off — the feature is ready to merge, **not** a deployment step. For a PR, "closed" means a reviewer would approve it.

**Round cap: 3. Track in `## Phase Rounds` → `Production: Rounds: N/3`.**

**Close checklist** (evaluator confirms each; skip lines that don't apply to the project):
- [ ] Full test suite passes (or pre-existing failures documented, not introduced)
- [ ] Lint / typecheck / build clean
- [ ] e2e or manual verification of the user-facing path, if the feature has one
- [ ] No unrelated or stray files in the diff
- [ ] PR description / changelog reflects what shipped
- [ ] Red lines from `CLAUDE.md` / `AGENTS.md` respected

**Pre-flight (orchestrator runs before delegating to generator):**
- a. Run `git diff --name-only` (or `git status --short`) and collect all modified files.
- b. Collect the union of all `**Files changed:**` lists from every sprint's Completion Report.
- c. Flag any modified file that does **not** appear in any sprint's Files changed — surface to the user and resolve (revert or acknowledge as intentional) before proceeding. This prevents workspace contamination from failing the production review.

1. `{generator}` runs full test suite across affected packages. **Affected packages** = all packages containing files listed in any sprint's Completion Report `**Files changed:**`. Zero-sprint projects: generator runs the full suite against all packages whose paths appear in the `## Design` section under Architecture or Data Model. Document pre-existing failures — don't fix unrelated things.
2. `{evaluator}` holistic review: security, reliability, observability, data integrity, performance, red-line compliance (re-read `CLAUDE.md` / `AGENTS.md` if present). Appends verdict to `## Production Review` using the format pre-seeded in that section. Increments `Production: Rounds:`.

3. `{generator}` fixes implementation issues (no format required for fix work itself); `{planner}` updates the `## Design` section only if a doc-level concern arises. `{evaluator}` re-reviews. Cap: 3 rounds total. Cap hit → write `[RAISED: PRODUCTION]` + escalation summary.
4. On PASS: `{evaluator}` writes `[APPROVED: PRODUCTION]` as `Latest marker:` and sets `Current sprint:` to `(complete)`.

---

### Post-Production Revision (Optional)

**Scope:** incorporate external review comments after `[APPROVED: PRODUCTION]`.

This re-enters the normal lifecycle. It introduces no new markers and is fully cold-resumable — external review items are just additional sprints.

1. `{evaluator}` triages each comment: **implement / defer / reject** (with rationale). Write triage into `## Feedback Log` (create this section if it doesn't exist).
2. For each implement item, `{planner}` appends a new sprint to the `## Sprint List` (future-sprint mutation is already permitted, per Lifecycle above), noting its origin as "external review" under `## Design Revisions`. The orchestrator sets `Current sprint:` to the next integer N and routes to 3a. Each runs as an ordinary sprint (3a → 3d) using the standard `[APPROVED: SPRINT_N_CONTRACT]` / `[APPROVED: SPRINT_N]` markers.
3. When all new sprints are approved, re-run Phase 4 to re-close → `[APPROVED: PRODUCTION]`, set `Current sprint:` to `(complete)`.

If a cold reset lands after a new sprint is appended but before its contract is approved, `Latest marker:` (`[APPROVED: PRODUCTION]`) and `Current sprint:` (integer N) will disagree — this trips the consistency check (stop and ask the user), which is the intended safety net.
