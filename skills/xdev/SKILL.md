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

## TL;DR — How xdev Runs

xdev turns one large feature into a resumable, human-gated lifecycle. The orchestrator runs this skill and delegates each step to its own lanes — there is **no separate execution mode to fall back to**: the sprint loop *is* the orchestrator driving its generator (fixer) and evaluator (oracle) lanes.

1. **One state file:** `.tmp/xdev/{feature}/plan_and_track.md`. Its `## Status` block (`Latest marker:` + `Current sprint:`) is the **single source of truth** — do not keep a parallel orchestrator todo list.
2. **Resume = read the Status block, route via the Marker Reference table.** Always start there, new run or resumed.
3. **Four phases, each gated by an evaluator verdict:** Frame → Design → Sprint loop → Close. Generator and evaluator are always different instances.
4. **Caps stop loops:** N failed review rounds → `[RAISED]` marker → stop and ask the user.
5. **Handover to another agent = point it at `plan_and_track.md` and this Golden Rule.** The file *is* the handover; there is nothing to generate.

Everything below is reference. If you've run xdev before, the Status block + Marker Reference table are all you need to operate.

---

## Golden Rule: Read `plan_and_track.md` First

Every xdev session — **new or resumed** — starts with:

```
Read .tmp/xdev/{feature}/plan_and_track.md
```

Read `Latest marker:` and `Current sprint:` together — they fully determine the next action via the Marker Reference table.

Also check `## Escalations` for any unresolved `Delegation failure:` entries — if present, surface to user and resolve before routing.

**Pointer sections:** if `## Requirements` or `## Design` contains only a `→ see <file>` line, read that file for the section's content. This is the escape hatch for large sections — treat it as if the content were inline.

**If the file doesn't exist but the feature directory exists:** check whether `plan_and_track.md` exists and is non-empty. If it is, the feature has in-progress state — **stop and ask the user** what happened before touching anything. Only if it is empty or missing: re-run Bootstrap from step 4 (skip mkdir), copying only template files that do not already exist or are empty.

**If the file doesn't exist and neither does the directory → follow Bootstrap below.**

If args were provided at invocation (e.g. `/xdev add OAuth login`), treat them as the initial feature description — skip asking "what are we building?"

---

## Bootstrap (New Feature)

1. Determine feature name from invocation args or ask the user.
2. Confirm doc location (default: `.tmp/xdev/{feature}/`).
3. **Guard:** if `plan_and_track.md` already exists at that path and is non-empty, this is an existing feature — do not bootstrap, go to Golden Rule resume instead.
4. `mkdir -p .tmp/xdev/{feature}/`
5. Copy `plan_and_track.md` and `sprint_block.md` from `$SKILL_DIR/templates/` to the feature directory (only if the destination does not exist or is empty).
   - `$SKILL_DIR` is set by the harness. If absent, locate templates at `~/.agents/skills/xdev/templates/` or the project-local skill path.
6. Write the initial feature description into the `### Initial Brief` subsection of `## Requirements` in `plan_and_track.md`. If invocation args were provided, paste them there. If no args, write a brief summary from the user's response.
7. Resolve placeholders in `plan_and_track.md` in this order:
   a. Replace `{Feature Name}` and `{feature}` (feature name).
   b. Resolve role bindings (see Role Model) — ask user or use harness convention.
   c. Replace `{agent or @handle}` with resolved bindings.
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

**Once invoked, stay in xdev through execution.** The sprint loop (Phase 3) is the orchestrator delegating to its generator/evaluator lanes — not a planning step you hand off to ad-hoc fixers afterward. Dropping back to free-form orchestration mid-feature abandons the state file and the review gates, which is where xdev's value is.

---

## Role Model

`xdev` describes work in terms of **roles**. The host harness binds roles to its real subagents.

| Role           | Owns                                                                 |
|----------------|----------------------------------------------------------------------|
| `orchestrator` | Runs this skill (the host loop). Reads markers and routes; writes only `[ABORTED]` markers and `## Escalations` notes; never writes `[APPROVED]` or `[RAISED]` markers |
| `planner`      | Requirements, design, sprint contracts, design-change updates        |
| `generator`    | Sprint implementation, test runs, completion reports                 |
| `evaluator`    | Contract quality verdicts, completion-report verdicts, all `[APPROVED]` and `[RAISED]` markers |
| `researcher`   | External doc / library lookups (optional); reconciles confirmed findings into `## Research Log` |

**Hard rules:**
- Generator and evaluator must always be **different instances**. A generator cannot evaluate its own work.
- Planner and evaluator must always be **different instances** (different invocations, fresh context), even when bound to the same underlying agent. Planner does the work of writing artifacts; evaluator judges them — same-instance review is not permitted.

**Marker ownership:**
- **Evaluator** writes all `[APPROVED: ...]` and `[RAISED: ...]` markers **directly to `plan_and_track.md`** — no copy-paste via the orchestrator.
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

- **planner**: sections to read (`## Requirements`, `## Design` in `plan_and_track.md`) → section to produce → where to write in `plan_and_track.md` → marker to set on success.
- **generator**: path to the sprint's `#### Contract` section + referenced `## Design` subsections + relevant source file paths → validation command → where to write `#### Completion Report`.
- **evaluator**: section to judge + hard-threshold criteria → where to write verdict → marker to set on PASS → current `Rounds:` value to increment.

No role needs conversation history. Every handoff is a file read.

---

## Severity Levels

Used in all FAIL verdicts:

| Severity | Meaning | Blocks? |
|----------|---------|---------|
| **critical** | Incorrect behavior, data loss, security issue, blocks ship | Yes — FAIL |
| **major** | Significant gap against contract criteria, must fix before ship | Yes — FAIL |
| **minor** | Advisory, style, or non-blocking observation | No — PASS with notes |

**Rule:** evaluator may only write FAIL when at least one critical or major issue exists. Minor-only findings → PASS — but minors are not blanket-deferred: when a fix round is already running for critical/major issues, the generator also applies the **quick-win** minors (low-risk, bounded, in-scope — a one-line simplification, an obvious clarity fix) in that same round. Minors that are risky, large, or out-of-scope go into the verdict's notes section for the user. Minors never trigger a new round on their own.

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

Markers compose **3 verbs** — `APPROVED` / `RAISED` / `ABORTED` — with lifecycle stages; the resume logic branches on verb + stage, not on each row independently. `INVALIDATED` is an **annotation**, not a resume marker (it never appears in `Latest marker:`) — it is listed in the table below only for reference.

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
| `[ABORTED: DESIGN — {reason}]` | orchestrator | Design restart | Planner revises the `## Design` section based on reason; re-enter Phase 2 step 1 |
| `[ABORTED: REQUIREMENTS — {reason}]` | orchestrator | Scope restart | Planner clears `[APPROVED: DESIGN]`, marks all sprints `[INVALIDATED: SPRINT_M]`, resets Sprint List, then revises the `## Requirements` section; re-enter Phase 1 step 3 |
| `[INVALIDATED: SPRINT_M]` | planner | Sprint made moot | Not a `Latest marker:` value — annotation only. For sprints with an existing block: written inside Sprint M's verdict section. For sprints not yet started (no block exists): written in the Sprint List table's Scope column as `[INVALIDATED]` and noted in `## Design Revisions`. Skip all invalidated sprints when advancing; if all remaining sprints are invalidated, enter Phase 4 |

If `Latest marker:` is missing, malformed, or unrecognized: stop and ask the user before proceeding.

Valid `Current sprint:` values: `(none)`, `(none — zero sprints)`, `(complete)`, or an integer N. Any other value is malformed.

If `Current sprint:` is missing, malformed, or inconsistent with `Latest marker:` (e.g. marker says `[APPROVED: SPRINT_3_CONTRACT]` but `Current sprint:` says `2`): stop and ask the user before proceeding. Unresolved placeholders (e.g. `{feature}`, `{agent or @handle}`) in `plan_and_track.md` are also treated as malformed state — stop and ask.

---

## Raised-State Recovery Protocol

When a `[RAISED: ...]` marker exists and the user has responded:

1. Orchestrator reads the escalation summary from `## Escalations`.
2. Orchestrator writes user response as `User direction: ...` under that entry.
3. **Orchestrator** resets the `Rounds:` counter for the affected phase to `0/CAP` in `plan_and_track.md` (orchestrator is the active role here, not evaluator).
4. Orchestrator follows the re-entry path in the marker table above.
5. On PASS, evaluator writes the standard `[APPROVED: ...]` marker, replacing the RAISED marker as `Latest marker:`.

---

## Phase Procedures

The marker table above routes you into a phase. Read `$SKILL_DIR/reference/phases.md` for that phase's step-by-step mechanics (if `$SKILL_DIR` is unset, use the same fallback paths as Bootstrap step 5). The invariants in this file (roles, severity, caps, doc-as-state) apply across all phases and are assumed already in context when reading that file.

---

## Doc-as-State Contract

`plan_and_track.md` is the **only** durable state file. (`requirements.md` / `design.md` may exist alongside it if a section was explicitly extracted via `→ see <file>` — treated as an extension of the plan file, not separate state.)

- Update `plan_and_track.md` **before** delegating to any sub-agent.
- `Latest marker:` is the canonical resume anchor — read it first, always.
- **Prefer reset over compaction.** On a long run, when the orchestrator's own context grows heavy, reset to a clean slate rather than compacting — `plan_and_track.md` is a complete handoff artifact. Re-read it and resume from `Latest marker:`; never rely on retained conversation history. (This is why every delegation brief is self-contained.)
- **Reference files by path, never paste file contents into the docs.** Contents go stale and bloat the handoff artifact; a path stays current.
- **Never write credentials, tokens, API keys, or secrets into xdev docs.**
- **Single source of truth.** The `## Status` block supersedes any orchestrator todo list — do not maintain both. Derive the next action from `Latest marker:` + the Marker Reference table, not from a parallel tracker.
- **Handover is the file, not a generated prompt.** To hand work to another agent (or a fresh you), give it the path to `plan_and_track.md` and the Golden Rule — it resumes from the Status block. Do not summarize state into a separate brief; a summary goes stale, the file does not.
- If a fact isn't in the docs, it doesn't exist for `xdev`.

---

## File Layout

```
{repo}/
  .tmp/xdev/{feature}/
    plan_and_track.md          ← the single state file (req + design + tracking)
    sprint_block.md            ← template for appending sprint sections (not edited)
    requirements.md            ← optional: only if ## Requirements was extracted
    design.md                  ← optional: only if ## Design was extracted
  .gitignore                   ← .tmp/ must be listed
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
- [ ] (Optional) Post-production revision — external review re-enters the lifecycle as new sprints
