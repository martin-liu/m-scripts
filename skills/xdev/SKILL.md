---
name: xdev
description: Full software-lifecycle skill for multi-sprint feature work. Drives requirements → design → sprint loop → production close, with file-based state that survives context resets. NOT for single-PR work — use the orchestrator's Complex tier for that.
license: MIT
metadata:
  author: martinliu
  version: "1.0.0"
allowed-tools: Read, Write, Edit, Bash(*)
---

# xdev — Extended Development Lifecycle

## Golden Rule: Read `plan_and_track.md` First

Every xdev session — **new or resumed** — starts with:

```
Read .tmp/xdev/{feature}/plan_and_track.md
```

Read `Latest marker:` and `Current sprint:` together — they fully determine the next action via the Marker Reference table.

Also check `## Escalations` for any unresolved `Delegation failure:` entries — if present, surface to user and resolve before routing.

**If the file doesn't exist but the feature directory exists:** check whether `requirements.md` or `design.md` exist and are non-empty. If either is non-empty, the feature has in-progress state — **stop and ask the user** what happened before touching anything. Only if all docs are empty or missing: re-run Bootstrap from step 4 (skip mkdir), copying only template files that do not already exist or are empty.

**If the file doesn't exist and neither does the directory → follow Bootstrap below.**

If args were provided at invocation (e.g. `/xdev add OAuth login`), treat them as the initial feature description — skip asking "what are we building?"

---

## Bootstrap (New Feature)

1. Determine feature name from invocation args or ask the user.
2. Confirm doc location (default: `.tmp/xdev/{feature}/`).
3. **Guard:** if `plan_and_track.md` already exists at that path and is non-empty, this is an existing feature — do not bootstrap, go to Golden Rule resume instead.
4. `mkdir -p .tmp/xdev/{feature}/`
5. For each template file in `$SKILL_DIR/templates/`: copy to the feature directory **only if the destination does not exist or is empty**.
   - `$SKILL_DIR` is set by the harness. If absent, locate templates at `~/.agents/skills/xdev/templates/` or the project-local skill path.
6. Write the initial feature description into `requirements.md` under `## Initial Brief`. If invocation args were provided, paste them there. If no args, write a brief summary from the user's response.
7. Resolve placeholders in the copied files in this order:
   a. Replace `{Feature Name}` and `{feature}` (feature name) in all files.
   b. Resolve role bindings (see Role Model) — ask user or use harness convention.
   c. Replace `{agent or @handle}` with resolved bindings in `plan_and_track.md`.
   d. Leave `Sprint N: {Title}` as-is — filled per-sprint at 3a.
   e. Check `.gitignore` — add `.tmp/` if not present. **Note:** `.tmp/` means "local only, not committed" — not "auto-deleted." Do not add to auto-clean scripts.
 8. Set `Latest marker:` to `(none)`, `Current sprint:` to `(none)`.
 9. Enter Phase 1 — Frame.

xdev writes files and delegates; it does not make git commits or manage branches.

xdev assumes sequential execution — only one role is active at a time writing to shared files.

---

## When to Invoke

**Yes:**
- Scope spans multiple sprints (can't finish in one orchestrator session)
- Requirements are ambiguous and need their own document before coding starts
- Design decisions involve tradeoffs that need explicit record-keeping
- The feature touches multiple packages, services, or subsystems

**No (use the orchestrator's Complex tier instead):**
- Single bug fix with a clear root cause
- Refactor within one package
- A feature that can be fully scoped, implemented, and reviewed in ~3 orchestrator rounds

---

## Role Model

`xdev` describes work in terms of **roles**. The host harness binds roles to its real subagents.

| Role           | Owns                                                                 |
|----------------|----------------------------------------------------------------------|
| `orchestrator` | Runs this skill (the host loop). Reads markers and routes; writes only `[ABORTED]` markers and `## Escalations` notes; never writes `[APPROVED]` or `[RAISED]` markers |
| `planner`      | Requirements, design, sprint contracts, design-change updates        |
| `generator`    | Sprint implementation, test runs, completion reports                 |
| `evaluator`    | Contract quality verdicts, completion-report verdicts, all `[APPROVED]` and `[RAISED]` markers |
| `researcher`   | External doc / library lookups (optional)                           |

**Hard rules:**
- Generator and evaluator must always be **different instances**. A generator cannot evaluate its own work.
- Planner and evaluator must always be **different instances** (different invocations, fresh context), even when bound to the same underlying agent. Planner does the work of writing artifacts; evaluator judges them — same-instance review is not permitted.

**Marker ownership:**
- **Evaluator** writes all `[APPROVED: ...]` and `[RAISED: ...]` markers.
- **Orchestrator** writes `[ABORTED: ...]` markers on explicit user instruction — the one exception to evaluator-writes-all.
- The orchestrator reads markers and routes; it never writes approval/raised markers itself.

**Delegation failures:** if a delegated role returns malformed output, times out, or refuses, the orchestrator writes a one-line note as `Delegation failure: [reason]` under `## Escalations`. Surface to the user. Does not count against the round cap. All delegation failures are logged in `## Escalations` only — never in verdict sections.

### Binding

Resolve in this order:

1. `## Bindings` block in `plan_and_track.md` → use it (resume path).
2. Example binding for OMO-style harnesses: `planner=@oracle`, `generator=@fixer`, `evaluator=@oracle` (always fresh invocation, never same instance as planner), `researcher=@librarian`.
3. Ask the user once, then write the answer.

### Delegation Briefs

Every prompt to a role must include:

- **planner**: paths to read (`requirements.md`, `design.md`) → section to produce → where to write in `plan_and_track.md` → marker to set on success.
- **generator**: path to the sprint's `#### Contract` section + referenced `design.md` sections + relevant source file paths → validation command → where to write `#### Completion Report`.
- **evaluator**: path to section to judge + hard-threshold criteria → where to write verdict → marker to set on PASS → current `Rounds:` value to increment.

No role needs conversation history. Every handoff is a file read.

---

## Severity Levels

Used in all FAIL verdicts:

| Severity | Meaning | Blocks? |
|----------|---------|---------|
| **critical** | Incorrect behavior, data loss, security issue, blocks ship | Yes — FAIL |
| **major** | Significant gap against contract criteria, must fix before ship | Yes — FAIL |
| **minor** | Advisory, style, or non-blocking observation | No — PASS with notes |

**Rule:** evaluator may only write FAIL when at least one critical or major issue exists. Minor-only findings → PASS with a notes section listing them.

---

## Round-Cap Semantics

A **round** = one evaluator verdict written (including the initial review). `Rounds:` starts at `0/CAP` and the evaluator increments it each time it writes a verdict. Cap hit = `Rounds:` reaches `N/N` and the verdict is still FAIL → write the corresponding RAISED marker.

Example with cap 2: initial review → `Rounds: 1/2`. If FAIL: planner fixes, evaluator re-reviews → `Rounds: 2/2`. If still FAIL → RAISED. If PASS at any round → write APPROVED.

**Malformed verdict:** if evaluator returns a verdict missing `Rounds:` or with invalid format, treat as a delegation failure (write to `## Escalations`, do not increment counter, do not advance).

---

## Completion Report: Submitted Definition

A report is **submitted** when: `**Files changed:**` is non-empty; `**Validation output:**` is non-empty; every criterion in `**Criteria status:**` is `[x] — passed` or `[ ] — pre-existing failure: [test name] (excluded per contract Out-of-scope)`. Zero-file sprints are not supported. An empty or placeholder body is **not submitted** — cold-resume treats it the same as absent.

---

## Marker Reference

`Latest marker:` in `plan_and_track.md` is the **canonical resume anchor**. It persists until the next marker is written — ABORTED and RAISED markers are durable states, not transitions.

| Marker | Writer | Meaning | Next action |
|--------|--------|---------|-------------|
| `(none)` | — | Not started | Enter Phase 1 |
| `[APPROVED: REQUIREMENTS]` | evaluator | Scope locked | Enter Phase 2 |
| `[APPROVED: DESIGN]` | evaluator | Architecture locked | If Sprint List is empty → Phase 4; otherwise → Phase 3 Sprint 1 (3a) |
| `[APPROVED: DESIGN_REV_N]` | evaluator | Design revised mid-sprint | Orchestrator reads `Current sprint:`, then asks evaluator to assess whether the sprint's contract criteria are still valid. If contract stale → orchestrator routes to 3a (planner rewrites contract); if contract valid and Completion Report submitted → 3d; if contract valid and no submitted report → 3c |
| `[APPROVED: SPRINT_N_CONTRACT]` | evaluator | Contract verified | Check if Completion Report is **submitted** under Sprint N: submitted → 3d; not submitted → 3c |
| `[APPROVED: SPRINT_N]` | evaluator | Sprint N complete | If Sprint N is last in Sprint List → Phase 4; otherwise → Sprint N+1 at 3a |
| `[APPROVED: PRODUCTION]` | evaluator | Done | Lifecycle complete |
| `[RAISED: REQUIREMENTS]` | evaluator | Requirements cap hit | See Raised-State Recovery; re-entry: planner integrates user direction → Phase 1 step 4 |
| `[RAISED: DESIGN]` | evaluator | Design cap hit | See Raised-State Recovery; re-entry: planner integrates → Phase 2 step 3 |
| `[RAISED: DESIGN_REV_N]` | evaluator | Design revision cap hit | See Raised-State Recovery; re-entry: planner revises changed section → evaluator re-reviews → on PASS write `[APPROVED: DESIGN_REV_N]` and resume sprint |
| `[RAISED: SPRINT_N_CONTRACT]` | evaluator | Contract cap hit | See Raised-State Recovery; re-entry: planner rewrites contract from scratch → 3b |
| `[RAISED: SPRINT_N]` | evaluator | Sprint cap hit | See Raised-State Recovery; re-entry: generator addresses issues → 3d |
| `[RAISED: PRODUCTION]` | evaluator | Close cap hit | See Raised-State Recovery; re-entry: generator fixes → Phase 4 step 2 |
| `[ABORTED: SPRINT_N — {reason}]` | orchestrator | Mid-sprint pivot | Sprints 1..N-1 already approved remain valid. Planner revises sprint list from Sprint N onwards (adding `[INVALIDATED: SPRINT_M]` annotations to Sprint N and any now-invalid future sprints); re-enter Phase 2 step 2 to revise the remaining sprint list only |
| `[ABORTED: DESIGN — {reason}]` | orchestrator | Design restart | Planner revises `design.md` based on reason; re-enter Phase 2 step 1 |
| `[ABORTED: REQUIREMENTS — {reason}]` | orchestrator | Scope restart | All downstream state is invalidated: clear `[APPROVED: DESIGN]`, mark all sprints `[INVALIDATED: SPRINT_M]`, reset Sprint List. Planner revises `requirements.md`; re-enter Phase 1 step 3 |
| `[INVALIDATED: SPRINT_M]` | planner | Sprint made moot | Not a `Latest marker:` value — annotation only. For sprints with an existing block: written inside Sprint M's verdict section. For sprints not yet started (no block exists): written in the Sprint List table's Scope column as `[INVALIDATED]` and noted in `## Design Revisions`. Skip all invalidated sprints when advancing; if all remaining sprints are invalidated, enter Phase 4 |

If `Latest marker:` is missing, malformed, or unrecognized: stop and ask the user before proceeding.

Valid `Current sprint:` values: `(none)`, `(none — zero sprints)`, `(complete)`, an integer N, or `FB_N`. Any other value is malformed.

If `Current sprint:` is missing, malformed, or inconsistent with `Latest marker:` (e.g. marker says `[APPROVED: SPRINT_3_CONTRACT]` but `Current sprint:` says `2`): stop and ask the user before proceeding. Unresolved placeholders (e.g. `{feature}`, `{agent or @handle}`) in `plan_and_track.md` are also treated as malformed state — stop and ask.

### Feedback Markers

These markers are used only during warm-session feedback integration. They are not part of the main lifecycle table above.

| Marker | Writer | Meaning | Next action |
|--------|--------|---------|-------------|
| `[APPROVED: FB_N_CONTRACT]` | evaluator | FB sprint contract verified | Check if FB_N Completion Report submitted → 3d; not submitted → 3c |
| `[APPROVED: FB_N]` | evaluator | FB sprint complete | Start FB_N+1 contract if more implement items remain; otherwise reconfirm `[APPROVED: PRODUCTION]` |
| `[RAISED: FB_N_CONTRACT]` | evaluator | FB contract cap hit | See Raised-State Recovery; re-entry: planner rewrites FB contract → 3b |
| `[RAISED: FB_N]` | evaluator | FB sprint cap hit | See Raised-State Recovery; re-entry: generator addresses issues → 3d |

> **Feedback integration — cold-start guard:** On a cold start, any `FB_*` value in `Latest marker:` *or* `Current sprint:` means feedback integration was in progress. **Do not auto-resume.** Treat the lifecycle as complete and ask the user before doing anything. The Feedback Markers table above applies only within a warm session.

---

## Raised-State Recovery Protocol

When a `[RAISED: ...]` marker exists and the user has responded:

1. Orchestrator reads the escalation summary from `## Escalations`.
2. Orchestrator writes user response as `User direction: ...` under that entry.
3. **Orchestrator** resets the `Rounds:` counter for the affected phase to `0/CAP` in `plan_and_track.md` (orchestrator is the active role here, not evaluator).
4. Orchestrator follows the re-entry path in the marker table above.
5. On PASS, evaluator writes the standard `[APPROVED: ...]` marker, replacing the RAISED marker as `Latest marker:`.

---

## Lifecycle — 4 Phases

Happy path: `(none)` → `[APPROVED: REQUIREMENTS]` → `[APPROVED: DESIGN]` → (if Sprint List non-empty) `[APPROVED: SPRINT_N_CONTRACT]` + `[APPROVED: SPRINT_N]` × N → `[APPROVED: PRODUCTION]`

**Design revisions** during Phase 3 produce `[APPROVED: DESIGN_REV_N]` — lifecycle position unchanged; resume current sprint per marker table.

**Verdict history:** evaluator always **appends** new verdict entries to the relevant section (`## Requirements Review`, `## Design Review`, `## Production Review`, sprint `#### Contract Review Verdict`, sprint `#### Evaluation Verdict`). Never overwrite previous verdicts — history is preserved for debugging.

**`Current sprint:` ownership:** planner sets it when appending a new sprint block (3a). Orchestrator sets it to `(none — zero sprints)` at end of Phase 2 if Sprint List is empty. Evaluator sets it to `(complete)` when writing `[APPROVED: PRODUCTION]`. Orchestrator sets it to `FB_N` when starting a feedback sprint.

**Zero-sprint:** `[APPROVED: DESIGN]` with empty Sprint List routes to Phase 4. Phase 4 still runs in full; generator still runs the test suite.

**Sprint list mutation:** planner may add, remove, or reorder **future unapproved** sprints at any time; record the change under `## Design Revisions`. Already-approved sprints cannot be modified — use `[INVALIDATED: SPRINT_M]` annotation in that sprint's verdict section instead.

**Sprint granularity:** a sprint should be small enough to implement, validate, and review within the configured round cap. If a planned sprint is too large, split it into multiple sprints during Phase 2 step 2 or before writing its contract.

---

### Phase 1 — Frame

**Goal:** Lock scope before any design work.

**Round cap: 3. Track in `## Phase Rounds` → `Requirements: Rounds: N/3`.**

1. Read project `CLAUDE.md` / `AGENTS.md` (if present) for red lines and conventions.
2. Explore codebase for prior art. Delegate to `{researcher}` (if bound) for broad searches or unfamiliar libraries.
3. `{planner}` fills `requirements.md`. All open questions must be resolved — leave none blank.
4. `{evaluator}` reviews: clarity, scope discipline, missing constraints, unresolved open questions. Writes verdict in `## Requirements Review` using this format:
   ```
   Requirements verdict: PASS | FAIL
   Rounds: N/3
   Issues (if FAIL — at least one critical or major):
   - [area] — severity: critical|major|minor — [specific issue]
   ```
   Increments `Requirements: Rounds:`.
5. `{planner}` (fresh instance) fixes; `{evaluator}` re-reviews (writes new verdict in `## Requirements Review`). Cap: 3 rounds total. Cap hit → write `[RAISED: REQUIREMENTS]` + escalation summary under `## Escalations`.
6. On PASS: `{evaluator}` writes `[APPROVED: REQUIREMENTS]` as `Latest marker:`.

**Scope change after approval:** orchestrator writes `[ABORTED: REQUIREMENTS — {reason}]`; re-enter step 3.

---

### Phase 2 — Design

**Goal:** Architecture locked, sprint list drafted — no implementation yet.

**Round cap: 3. Track in `## Phase Rounds` → `Design: Rounds: N/3`.**

1. `{planner}` writes `design.md` from template.
2. `{planner}` drafts sprint list in `plan_and_track.md`: titles + one-line scope only. Leave empty if no implementation needed.
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

`{planner}` appends a new sprint block (from `sprint_block.md`) under `## Sprint Log` in `plan_and_track.md`, then writes the contract. Consult `{researcher}` (if bound) before finalizing criteria referencing unfamiliar libraries.

```markdown
#### Contract
- **Scope:** which sections of design.md apply
- **Success criteria:** (hard thresholds — each independently verifiable)
  - [ ] `<test command>` exits 0
  - [ ] `<file or output>` exists / matches expected
- **Out-of-scope:** what NOT to touch this sprint; pre-existing failures to exclude
- **Validation command:** `<scoped command that proves all criteria>`
```

*Success criteria* = assertions. *Validation command* = the command that checks them. Both required.

#### 3b — Review Contract

`{evaluator}` checks: are all success criteria hard thresholds verifiable without interpretation?

**Required verdict format:**
```
Contract verdict: PASS | FAIL
Rounds: N/2
Issues (if FAIL):
- [criterion text] — too vague because: [reason] — rewrite as: [concrete alternative]
```

- **PASS** → write `[APPROVED: SPRINT_N_CONTRACT]`.
- **FAIL** → `{planner}` (fresh instance) rewrites. Cap: 2 rounds. Cap hit → write `[RAISED: SPRINT_N_CONTRACT]` + escalation summary.

#### 3c — Implement

`{generator}` reads: sprint contract, referenced `design.md` sections, relevant source files. Implements, runs validation command. **Generator must not submit a Completion Report with a failing validation command — fix failures first.**

**Generator stuck:** if the validation command cannot be made to pass (e.g. pre-existing infrastructure failure, blocked dependency), generator stops and surfaces the blockage to the orchestrator. The orchestrator writes a `Delegation failure: validation blocked — [reason]` note under `## Escalations` and surfaces to the user before proceeding.

Generator **fills** the `#### Completion Report` section under the existing heading in the sprint block (see definition above — all three fields must be populated):

```markdown
#### Completion Report
- **Files changed:** (list — at least one entry required)
- **Validation output:** (paste or summary — required)
- **Criteria status:**
  - [x] criterion 1 — passed
  - [ ] criterion 2 — pre-existing failure: [test name] (excluded per contract Out-of-scope)
- **Notes:** (deviations from contract, if any)
```

All new-code criteria must be `[x] — passed`. The only allowed `[ ]` entries are pre-existing failures named in the contract's `Out-of-scope`.

#### 3d — Evaluate

`{evaluator}` reads contract + Completion Report, spot-checks changed files.

**Required verdict format:**
```
Sprint verdict: PASS | FAIL
Rounds: N/2
Issues (if FAIL — must contain at least one critical or major):
- [criterion or file] — severity: critical|major|minor — [specific actionable description]
Minor-only findings (list here, set verdict to PASS):
```

- **PASS** → write `[APPROVED: SPRINT_N]`.
- **FAIL** → proceed to 3e.

#### 3e — Fix

`{generator}` addresses critical and major issues, updates Completion Report. Minor issues are advisory. Back to 3d. **Cap: 2 rounds total (tracked in `Rounds:` of the Evaluation Verdict).** Cap hit → write `[RAISED: SPRINT_N]` + escalation summary.

**Mid-sprint design change:** if implementation reveals a design error → write `Design Rev N: Paused sprint: M — [what changed and why]` under `## Design Revisions` and add `Design Rev N: Rounds: 0/2` under `## Phase Rounds` → `{planner}` updates `design.md` → `{evaluator}` appends verdict to `## Design Revisions` using this format:

```
Design revision verdict: PASS | FAIL
Rounds: N/2
Issues (if FAIL):
- [section] — severity: critical|major|minor — [specific description]
```

Cap: 2 rounds total. Cap hit → write `[RAISED: DESIGN_REV_N]`. On PASS → write `[APPROVED: DESIGN_REV_N]`. Resume per marker table conditional (evaluator checks if contract is now stale → 3a if stale). If change invalidates an approved sprint, add `[INVALIDATED: SPRINT_M]` to that sprint's verdict section.

---

### Phase 4 — Close

**Goal:** Production sign-off.

**Round cap: 3. Track in `## Phase Rounds` → `Production: Rounds: N/3`.**

1. `{generator}` runs full test suite across affected packages. **Affected packages** = all packages containing files listed in any sprint's Completion Report `**Files changed:**`. Zero-sprint projects: generator runs the full suite against all packages whose paths appear in `design.md` under Architecture or Data Model sections. Document pre-existing failures — don't fix unrelated things.
2. `{evaluator}` holistic review: security, reliability, observability, data integrity, performance, red-line compliance (re-read `CLAUDE.md` / `AGENTS.md` if present). Writes verdict in `## Production Review` in `plan_and_track.md`. Increments `Production: Rounds:`.

**Required verdict format (append to `## Production Review`):**
```
Production verdict: PASS | FAIL
Rounds: N/3
Issues (if FAIL — at least one critical or major):
- [area] — severity: critical|major|minor — [specific actionable description]
```

3. `{generator}` fixes implementation issues (no format required for fix work itself); `{planner}` updates `design.md` only if a doc-level concern arises. `{evaluator}` re-reviews. Cap: 3 rounds total. Cap hit → write `[RAISED: PRODUCTION]` + escalation summary.
4. On PASS: `{evaluator}` writes `[APPROVED: PRODUCTION]` as `Latest marker:` and sets `Current sprint:` to `(complete)`.

---

### Feedback Integration (Optional — warm session only)

**Scope:** incorporate external review comments after `[APPROVED: PRODUCTION]`.

**Warning:** not resumable from a cold start. Complete in one session. If interrupted, restart from the original review comments.

1. `{evaluator}` triages each comment: **implement / defer / reject** (with rationale). Write triage into `## Feedback Log` (create this section if it doesn't exist).
2. For each implement item: run a mini sprint (3a → 3b → 3c → 3d) numbered `FB_1, FB_2, ...`. Set `Current sprint: FB_N`. Store sprint blocks in `## Feedback Log`.
3. When all implement items complete: write `[APPROVED: PRODUCTION]` (reconfirm), set `Current sprint:` to `(complete)`.

---

## Doc-as-State Contract

The three `.md` files are the **only** durable state.

- Update `plan_and_track.md` **before** delegating to any sub-agent.
- `Latest marker:` is the canonical resume anchor — read it first, always.
- **Never write credentials, tokens, API keys, or secrets into xdev docs.**
- If a fact isn't in the docs, it doesn't exist for `xdev`.

---

## File Layout

```
{repo}/
  .tmp/xdev/{feature}/
    requirements.md
    design.md
    plan_and_track.md
    sprint_block.md      ← template for appending sprint sections
  .gitignore             ← .tmp/ must be listed
```

---

## Checklist

- [ ] Bootstrap or resume (`plan_and_track.md` exists? Placeholders resolved?)
- [ ] Resolve role bindings
- [ ] Phase 1: Frame → `[APPROVED: REQUIREMENTS]`
- [ ] Phase 2: Design → `[APPROVED: DESIGN]`
- [ ] For each sprint (skip if Sprint List empty):
  - [ ] 3a Draft contract
  - [ ] 3b Review contract → `[APPROVED: SPRINT_N_CONTRACT]`
  - [ ] 3c Implement (no failing validation; Completion Report fully populated)
  - [ ] 3d/3e Evaluate + fix → `[APPROVED: SPRINT_N]`
- [ ] Phase 4: Close → `[APPROVED: PRODUCTION]`
- [ ] (Optional, warm session only) Feedback integration
