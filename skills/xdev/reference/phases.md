# xdev — Phase Procedures

> **Reference file — loaded on demand.** Load this file (`$SKILL_DIR/reference/phases.md`) when the Marker Reference table in `SKILL.md` routes you into a phase. The router and invariants (Marker Reference, xdev Agent Responsibilities, Severity, Round-Cap Semantics, Completion Report definition, Raised-State Recovery, Doc-as-State) live in `SKILL.md` and are assumed already in context.

## Lifecycle — 4 Phases

Happy path: `(none)` → (`[GATE: REQUIREMENTS]` — at most once, only if blocking user decisions exist) → `[APPROVED: REQUIREMENTS]` → `[APPROVED: DESIGN]` → (if Sprint List non-empty) `[APPROVED: SPRINT_N_CONTRACT]` + `[APPROVED: SPRINT_N]` × N → `[APPROVED: PRODUCTION]`

**Design revisions** during Phase 3 produce `[APPROVED: DESIGN_REV_N]` — lifecycle position unchanged; resume current sprint per marker table.

**Oracle `Orchestrator:` directive:** xdev verdicts use the default oracle verdict format. In xdev, the directive must name the next marker-derived route.

**Verdict history:** oracle always **appends** new verdict entries to the relevant section (`## Requirements Review`, `## Design Review`, `## Production Review`, sprint `#### Contract Review Verdict`, sprint `#### Evaluation Verdict`). Never overwrite previous verdicts — history is preserved for debugging.

**`Current sprint:` ownership:** oracle sets it when appending a new sprint block (3a), when approving a zero-sprint design, and when writing `[APPROVED: PRODUCTION]`.

**Zero-sprint:** `[APPROVED: DESIGN]` with empty Sprint List routes to Phase 4. Phase 4 still runs in full; fixer still runs the test suite.

**Sprint list mutation:** oracle may add, remove, or reorder **future unapproved** sprints at any time; record the change under `## Design Revisions`. Already-approved sprints cannot be modified — use `[INVALIDATED: SPRINT_M]` annotation in that sprint's verdict section instead.

**Sprint granularity:** a sprint should be small enough to implement, validate, and review within the configured round cap. If a planned sprint is too large, split it into multiple sprints during Phase 2 step 2 or before writing its contract.

---

### Phase 1 — Frame

**Goal:** Lock scope before any design work — a PRD grounded in codebase evidence, where every interpretive choice is either user-confirmed or recorded as a defaulted assumption. Requirements failures poison every downstream sprint; this phase is where xdev spends its thinking.

**Round cap: 3. Track in `## Phase Rounds` → `Requirements: Rounds: N/3`.**

**User-contact budget: at most ONE clarification gate (step 4). Everything else is resolved autonomously and recorded.**

1. Read project `CLAUDE.md` / `AGENTS.md` (if present) for red lines and conventions.
2. Explore codebase for prior art, existing patterns, and constraints — broad searches or unfamiliar libraries as needed. Record confirmed findings in `## Research Log` (path-referenced, per its format); reviewers treat these as accepted context and do not re-research them. If the feature has any user-facing surface (UI, API, file ingestion, user-visible state), also check `AGENTS.md` / `CLAUDE.md` against the Repo AGENTS.md Checklist (see `SKILL.md`); if live-verification instructions are missing, oracle adds a `user-decision — blocking: yes` Open Question ("provide live-verification command/setup, or waive") so it rides the clarification gate instead of stalling Sprint 1 at 3a.
3. Oracle drafts the full `## Requirements` section (the PRD): User Stories, In/Out of Scope, Hard Constraints, and Open Questions. Every open question gets classified before any answer is written:
   - **self-resolved** — answerable from the codebase, the Initial Brief, or repo conventions. Oracle answers it directly, citing evidence (`source: [path or Research Log entry]`). Guessing without a source is not allowed — an unsourced answer is a user-decision in disguise.
   - **user-decision** — a product/scope/tradeoff call that no amount of code reading can answer. Oracle MUST attach a recommended default and its consequence (`default: [choice] — consequence: [what the user gives up]`), and mark `blocking: yes` only when a wrong guess would invalidate the feature: contradictory Initial Brief, ambiguous core goal, irreversible or externally visible behavior, security or data-loss tradeoffs. Everything else is `blocking: no`.
4. **Clarification gate — at most once per feature:**
   - No `blocking: yes` questions → do NOT contact the user. Apply every default, record each under `### Assumptions` with `status: defaulted`, continue to step 5. This is the zero-ask path and the expected common case.
   - Any `blocking: yes` question → oracle writes `[GATE: REQUIREMENTS]` as `Latest marker:`. Orchestrator presents ONE batch to the user: a short requirements summary plus ALL user-decision questions (blocking and non-blocking — the single ask is spent, use it fully), each with its recommended default so the user can reply "defaults fine." Stop until the user responds.
   - On response: orchestrator appends `User input: [answer]` under each answered question in `### Open Questions`; oracle integrates — answered questions become `status: user-confirmed` in `### Assumptions`, unanswered non-blocking ones fall back to `status: defaulted`. Continue to step 5. The gate never fires again (mechanical test: any `User input:` entry under `### Open Questions` means it already fired): ambiguity discovered later is defaulted + recorded, or escalates through the normal cap → RAISED path.
5. A fresh oracle session reviews: clarity, scope, constraints; every open question answered with cited evidence or `User input:`; every `### Assumptions` entry has default + consequence; no `blocking: yes` question was silently defaulted. Appends verdict to `## Requirements Review`. Increments `Requirements: Rounds:`.
6. Oracle revises; fresh oracle re-reviews. Cap: 3 rounds total. Cap hit → run **Oracle Consultation Protocol** (see `SKILL.md`) → if ESCALATE: write `[RAISED: REQUIREMENTS]` + escalation summary under `## Escalations`.
7. On PASS: oracle writes `[APPROVED: REQUIREMENTS]` as `Latest marker:`.

**Scope change after approval:** orchestrator writes `[ABORTED: REQUIREMENTS — {reason}]`; re-enter step 3. The gate does not re-arm on scope restart — new blocking ambiguity in the restart ask is already user contact; fold its answers in directly.

---

### Phase 2 — Design

**Goal:** Architecture locked, sprint list drafted — no implementation yet.

**Round cap: 3. Track in `## Phase Rounds` → `Design: Rounds: N/3`.**

1. Oracle fills the `## Design` section. Record new codebase findings in `## Research Log`. Design-time open questions are resolved by oracle with cited evidence — there is no user gate in Phase 2. A technical tradeoff with no clear winner: pick one, record it under `### Key Alternatives Considered`. A genuine product ambiguity surfacing here means requirements missed it: default it, record it under `### Assumptions` in `## Requirements`, and continue — or if it invalidates approved scope, that is an `[ABORTED: REQUIREMENTS]` decision for the user, surfaced via the normal escalation paths.
2. Oracle drafts the `## Sprint List` table: titles + one-line scope only. Leave empty if no implementation needed.
3. A fresh oracle session reviews design. Writes verdict in `## Design Review`. Increments `Design: Rounds:`.
4. Oracle revises; fresh oracle re-reviews. Cap: 3 rounds. Cap hit → run **Oracle Consultation Protocol** → if ESCALATE: write `[RAISED: DESIGN]` + escalation summary.
5. On PASS: oracle writes `[APPROVED: DESIGN]`. If Sprint List is empty, oracle also sets `Current sprint:` to `(none — zero sprints)`.
6. Orchestrator posts a brief informational summary to the user — key design decisions, assumptions in effect, sprint list — then proceeds immediately to Phase 3. This is visibility, not a gate: do not wait for a reply, do not ask a question.

**Design change after approval:** orchestrator writes `[ABORTED: DESIGN — {reason}]`; re-enter step 1.

---

### Phase 3 — Sprint Loop

Repeat for each sprint in order. **Do not start Sprint N+1 until `[APPROVED: SPRINT_N]` is set.**

For each new sprint, oracle appends `sprint_block.md` content (with N and title substituted) under `## Sprint Log` in `plan_and_track.md`, and sets `Current sprint:` to `N`.

**Pre-existing test failures:** validation commands must be scoped to the sprint's new tests. If a broader test suite is unavoidable, the contract's `Out-of-scope` must list pre-existing failing tests by name — these are excluded from the FAIL criteria.

#### 3a — Draft Contract

Oracle writes the contract and verifies any criteria that depend on unfamiliar libraries before finalizing them.

**Live verification obligation:** if the sprint includes user-facing changes (UI, API endpoints, file ingestion, or any state visible to end-users), at least one success criterion must be a live verification check — real running system, real data, not a unit test or committed test suite.

Before writing the criterion, consult `AGENTS.md` / `CLAUDE.md` for the repo's live verification command, local env setup, and test data preparation steps.

**If no live verification instructions are found**, do not silently skip. First check `## Requirements`: Phase 1 step 2 normally resolved this at the clarification gate — if a command or waiver is recorded there, apply it and continue (a waiver goes into the contract's Out-of-scope as Exit C below). Reaching this point unresolved means the feature became user-facing only after Phase 1; follow this protocol:

1. Write a `Delegation failure: live verification instructions missing from AGENTS.md` note under `## Escalations`. The orchestrator may not proceed to 3b until this is resolved.
2. **Resolution paths (orchestrator applies user direction once received):**
   - **Exit A — user updates `AGENTS.md`:** orchestrator re-reads the file, extracts the command, drafts the criterion, continues to 3a normally.
   - **Exit B — user provides the command inline:** orchestrator writes it to `AGENTS.md` under `## Live Verification` (creating the section if absent), then continues as Exit A.
   - **Exit C — user waives:** orchestrator records `Live verification: waived — [user's reason]` in the contract's `Out-of-scope`. The Phase 4 checklist item is skipped for this feature without oracle penalty.

Never proceed to 3b without one of these exits resolved.

Oracle fills the pre-seeded `#### Contract` block in the sprint block (skeleton and field guidance live in `sprint_block.md`): Scope, Success criteria, Out-of-scope, Validation command.

*Success criteria* = assertions. *Validation command* = the command that checks them. Both required.

#### 3b — Review Contract

A fresh oracle checks: are all success criteria hard thresholds verifiable without interpretation? Appends verdict to the `#### Contract Review Verdict` block using the format pre-seeded there.

- **PASS** → write `[APPROVED: SPRINT_N_CONTRACT]`. **Minor-only findings are PASS** — note them, don't fail.
- **FAIL** ([critical] or [major] only) → oracle rewrites; a fresh oracle session re-reviews. Cap: 2 rounds. Cap hit → run **Oracle Consultation Protocol** → if ESCALATE: write `[RAISED: SPRINT_N_CONTRACT]` + escalation summary.

#### 3c — Implement

Fixer reads: sprint contract, referenced `## Design` subsections, relevant source files. Implements, runs validation command. **Fixer must not submit a Completion Report with a failing validation command — fix failures first.**

**Fixer stuck:** if the validation command cannot be made to pass (e.g. pre-existing infrastructure failure, blocked dependency), fixer stops and surfaces the blockage to the orchestrator. The orchestrator writes a `Delegation failure: validation blocked — [reason]` note under `## Escalations`. The orchestrator may not proceed until the blockage is resolved (via user direction or oracle consultation).

Fixer **fills** the `#### Completion Report` section under the existing heading in the sprint block, using the format pre-seeded in that section's comment (see **Completion Report: Submitted Definition** in `SKILL.md` — all three fields must be populated).

All new-code criteria must be `[x] — passed`. The only allowed `[ ]` entries are pre-existing failures named in the contract's `Out-of-scope`.

#### 3d — Evaluate

Oracle reads contract + Completion Report, spot-checks changed files. Appends verdict to the `#### Evaluation Verdict` block using the format pre-seeded there.

- **PASS** → write `[APPROVED: SPRINT_N]`. **Minor-only findings are PASS** — note them in the verdict, don't fail.
- **FAIL** (critical or major only) → proceed to 3e.

#### 3e — Fix

Fixer addresses critical and major issues blocking approval, updates Completion Report. Minor issues are advisory — but since a round is already running, fixer also applies the quick-win minors (low-risk, bounded, in-scope) here per the Severity Levels rule (in `SKILL.md`); the rest stay in the verdict notes for the user. Back to 3d. **Cap: 2 rounds total (tracked in `Rounds:` of the Evaluation Verdict).** Cap hit → run **Oracle Consultation Protocol** → if ESCALATE: write `[RAISED: SPRINT_N]` + escalation summary.

**Mid-sprint design change:** if implementation reveals a design error → write `Design Rev N: Paused sprint: M — [what changed and why]` under `## Design Revisions` and add `Design Rev N: Rounds: 0/2` under `## Phase Rounds` → oracle updates the `## Design` section → a fresh oracle reviews and appends verdict to `## Design Revisions` using the format pre-seeded in that section.

Cap: 2 rounds total. Cap hit → run **Oracle Consultation Protocol** → if ESCALATE: write `[RAISED: DESIGN_REV_N]`. On PASS → write `[APPROVED: DESIGN_REV_N]`. Resume per marker table conditional (oracle checks if contract is now stale → 3a if stale). If change invalidates an approved sprint, add `[INVALIDATED: SPRINT_M]` to that sprint's verdict section.

---

### Phase 4 — Close

**Goal:** Ready-to-ship sign-off — the feature is ready to merge, **not** a deployment step. For a PR, "closed" means a reviewer would approve it.

**Round cap: 3. Track in `## Phase Rounds` → `Production: Rounds: N/3`.**

**Close checklist** (oracle confirms each; skip lines that don't apply to the project):
- [ ] Full test suite passes (or pre-existing failures documented, not introduced)
- [ ] Lint / typecheck / build clean
- [ ] **Live verification passes** — required if the feature touches UI, external API, file ingestion, or any user-visible state; run against a real local system with real data per `AGENTS.md` (browser automation, real DB writes, real file ingestion, API round-trips — whatever applies); this is not a committed test suite. Skip only if every sprint in the Sprint List has `Live verification: waived` in its Out-of-scope, or the Sprint List is empty (zero-sprint) and the feature has no user-facing path.
- [ ] No unrelated or stray files in the diff
- [ ] PR description / changelog reflects what shipped
- [ ] Red lines from `CLAUDE.md` / `AGENTS.md` respected

**Pre-flight (orchestrator runs before delegating to fixer):**
- a. Run `git diff --name-only` (or `git status --short`) and collect all modified files.
- b. Collect the union of all `**Files changed:**` lists from every sprint's Completion Report.
- c. Flag any modified file that does **not** appear in any sprint's Files changed — write a `Delegation failure: stray modified files detected` note under `## Escalations`. The orchestrator may not proceed until the files are accounted for — resolve via the standard mediation rule (an oracle checkpoint directive may direct reverting them or attributing them to a sprint's report); user contact only if oracle escalates. This prevents workspace contamination from failing the production review.

1. Fixer runs full test suite across affected packages. **Affected packages** = all packages containing files listed in any sprint's Completion Report `**Files changed:**`. Zero-sprint projects: fixer runs the full suite against all packages whose paths appear in the `## Design` section under Architecture or Data Model. For features with a user-facing path, this sweep also includes live verification per `AGENTS.md` (start local env, prepare real test data, run browser/API/ingestion commands). Document pre-existing failures — don't fix unrelated things.
2. Oracle does holistic review: security, reliability, observability, data integrity, performance, red-line compliance (re-read `CLAUDE.md` / `AGENTS.md` if present). Appends verdict to `## Production Review` using the format pre-seeded in that section. Increments `Production: Rounds:`.

3. Fixer fixes implementation issues (no format required for fix work itself); oracle updates the `## Design` section only if a doc-level concern arises. A fresh oracle session re-reviews. Cap: 3 rounds total. Cap hit → run **Oracle Consultation Protocol** → if ESCALATE: write `[RAISED: PRODUCTION]` + escalation summary.
4. On PASS: oracle writes `[APPROVED: PRODUCTION]` as `Latest marker:` and sets `Current sprint:` to `(complete)`.

---

### Post-Production Revision (Optional)

**Scope:** incorporate external review comments after `[APPROVED: PRODUCTION]`.

This re-enters the normal lifecycle. It introduces no new markers and is fully cold-resumable — external review items are just additional sprints.

1. Oracle triages each comment: **implement / defer / reject** (with rationale). Write triage into `## Feedback Log` (create this section if it doesn't exist).
2. For each implement item, oracle appends a new sprint to the `## Sprint List` (future-sprint mutation is already permitted, per Lifecycle above), noting its origin as "external review" under `## Design Revisions`. Oracle sets `Current sprint:` to the next integer N when appending the sprint, then the orchestrator routes to 3a. Each runs as an ordinary sprint (3a → 3d) using the standard `[APPROVED: SPRINT_N_CONTRACT]` / `[APPROVED: SPRINT_N]` markers.
3. When all new sprints are approved, re-run Phase 4 to re-close → `[APPROVED: PRODUCTION]`, oracle sets `Current sprint:` to `(complete)`.

If a cold reset lands after a post-production sprint is appended but before its contract is approved, `[APPROVED: PRODUCTION]` plus integer `Current sprint:` is valid and routes to Sprint N at 3a.
