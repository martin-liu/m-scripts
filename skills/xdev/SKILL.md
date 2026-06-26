---
name: xdev
description: Full software-lifecycle skill for multi-sprint feature work. Drives requirements → design → sprint loop → production close, with file-based state that survives context resets. NOT for single-PR work — use the orchestrator's Medium tier (oracle review loop) for that.
license: MIT
metadata:
  author: martinliu
  version: "1.0.0"
allowed-tools: Read, Write, Edit, Bash(*)
---

# xdev — Extended Development Lifecycle

## TL;DR — How xdev Runs

xdev turns one large feature into a resumable, human-gated lifecycle. The orchestrator runs this skill, oracle plans and reviews, and fixer implements. The sprint loop is the normal orchestrator → oracle/fixer delegation loop plus xdev state, markers, and phase gates.

1. **One state file:** `.tmp/xdev/{feature}/plan_and_track.md`. Its `## Status` block (`Latest marker:` + `Current sprint:`) is the **single source of truth** — do not keep a parallel orchestrator todo list.
2. **Resume = read the Status block, route via the Marker Reference table.** Always start there, new run or resumed.
3. **Four phases, each gated by oracle review:** Frame → Design → Sprint loop → Close. Oracle writes plans/contracts and reviews them in fresh review sessions; fixer implements sprint contracts. Fixer never evaluates its own work.
4. **Caps stop loops:** N failed review rounds → oracle consultation (fresh oracle session, full context) → if oracle unblocks: one bonus round; if oracle can't → `[RAISED]` marker → stop and ask the user.
5. **Handover to another agent = point it at `plan_and_track.md` and this Golden Rule.** The file *is* the handover; there is nothing to generate.

**xdev is additive.** It does not redefine orchestrator, oracle, or fixer behavior. The default prompts remain authoritative for delegation, review format, severity, direct reads, fixer execution, stuck detection, and `Orchestrator:` directives. xdev adds only the durable state file, lifecycle phases, markers, round caps, sprint contracts, completion reports, and RAISED recovery.

Everything below is reference. If you've run xdev before, the Status block + Marker Reference table are all you need to operate.

---

## Golden Rule: Read `plan_and_track.md` First

Every xdev session — **new or resumed** — starts with:

```
Read .tmp/xdev/{feature}/plan_and_track.md
```

Read `Latest marker:` and `Current sprint:` together. On active handoff, follow the latest oracle `Orchestrator:` directive. On cold resume or missing directive, use these fields with the Marker Reference table to recover the next mechanical route.

Also check `## Escalations` for any unresolved `Delegation failure:` entries. Do not advance lifecycle work until they are resolved; if they block every safe route, use the checkpoint directive rule below.

**Pointer sections:** if `## Requirements` or `## Design` contains only a `→ see <file>` line, read that file for the section's content. This is the escape hatch for large sections — treat it as if the content were inline.

**If the expected `plan_and_track.md` path is missing but the feature directory exists:** if any non-empty `plan_and_track.md` is present in that directory, resume from it. Otherwise write `Delegation failure: plan_and_track.md missing but feature directory exists` under `## Escalations` if possible, then stop until user direction.

**If the file doesn't exist and neither does the directory → follow Bootstrap below.**

**If the file exists and the user is making a new ask for the same feature:** do not re-bootstrap. Read `## Requirements` and `## Status`, add the new ask as `### Amendment N` under `## Requirements`, then delegate to oracle to assess: fits the current sprint (extend contract), needs a new sprint (append to Sprint List), or invalidates current design (`[ABORTED: DESIGN — reason]`).

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
   b. Replace any remaining `{agent or @handle}` placeholders with `@oracle` or `@fixer` as appropriate.
   c. Leave `Sprint N: {Title}` as-is — filled per-sprint at 3a.
   d. Check `.gitignore` — add `.tmp/` if not present. **Note:** `.tmp/` means "local only, not committed" — not "auto-deleted." Do not add to auto-clean scripts.
8. Set `Latest marker:` to `(none)`, `Current sprint:` to `(none)`.
9. Enter Phase 1 — Frame.

xdev writes files and delegates; it does not make git commits or manage branches.

xdev assumes sequential execution — only one agent is active at a time writing to shared files.

---

## When to Invoke

**Yes:**
- Scope spans multiple sprints (can't finish in one orchestrator session)
- Requirements are ambiguous and need their own document before coding starts
- Design decisions involve tradeoffs that need explicit record-keeping
- The feature touches multiple packages, services, or subsystems

**No (use the orchestrator's Trivial or Medium tier instead):**
- Single bug fix with a clear root cause → Trivial
- Refactor within one package → Medium
- A feature that can be fully scoped, implemented, and reviewed within the Medium cap → Medium

**Once invoked, stay in xdev through execution.** The sprint loop (Phase 3) is the orchestrator delegating to its fixer/oracle lanes — not a planning step you hand off to ad-hoc fixers afterward. Dropping back to free-form orchestration mid-feature abandons the state file and the review gates, which is where xdev's value is.

**Boundary:** Non-xdev and xdev are separate lifecycles. Do not import xdev marker/phase machinery into Trivial/Medium, and do not return to the lightweight Medium loop after xdev has been invoked for a feature.

---

## xdev Agent Responsibilities

xdev uses the standard opencode agents directly.

| Agent | Additional xdev responsibility |
|-------|--------------------------------|
| `orchestrator` | Runs the xdev lifecycle, reads markers, routes work, writes `[ABORTED]` markers on explicit user instruction, logs `Delegation failure:` entries under `## Escalations`, and resets `Rounds:` after RAISED recovery. |
| `oracle` | Writes requirements, design, sprint contracts, design revisions, review verdicts, `[APPROVED]` markers, and `[RAISED]` markers. |
| `fixer` | Implements sprint contracts, runs validation, fixes blocking issues, and fills Completion Reports. |

**Oracle freshness:** when oracle reviews an artifact that oracle previously wrote or revised, use a fresh oracle session. The same oracle session must not approve its own output.

**Marker ownership:**
- Oracle writes all `[APPROVED: ...]` and `[RAISED: ...]` markers directly to `plan_and_track.md`.
- Orchestrator writes `[ABORTED: ...]` markers only on explicit user instruction.
- Orchestrator reads markers and routes; it never writes approval/raised markers itself.

**Delegation failures:** if oracle or fixer returns malformed output, times out, or refuses, orchestrator writes `Delegation failure: [reason]` under `## Escalations`. This does not count against the round cap.

If unresolved `Delegation failure:` entries block every safe next route, orchestrator asks oracle for a checkpoint directive. Oracle must either provide an executable route or append `Checkpoint unresolved: [reason]` under `## Escalations`; do not write `[RAISED: ...]` unless the blocked state is already in a cap-hit path.

---

## Severity

xdev uses the default oracle severity rules. When a fix round is already running, fixer also applies quick-win minor items that are low-risk, bounded, and in-scope.

---

## Round-Cap Semantics

A **round** = one oracle verdict written (including the initial review). `Rounds:` starts at `0/CAP` and oracle increments it each time it writes a verdict. Cap hit = `Rounds:` reaches `N/N` and the verdict is still FAIL → write the corresponding RAISED marker.

Example with cap 2: initial review → `Rounds: 1/2`. If FAIL: oracle revises, oracle re-reviews in a fresh review session → `Rounds: 2/2`. If still FAIL → RAISED. If PASS at any round → write APPROVED.

**Malformed verdict:** if oracle returns a verdict missing `Rounds:` or with invalid format, treat as a delegation failure (write to `## Escalations`, do not increment counter, do not advance).

If the same agent returns malformed output twice for the same phase/sprint, retry once with a fresh instance; if that also fails, treat it as a blocking delegation failure and invoke the checkpoint directive rule.

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
| `[APPROVED: REQUIREMENTS]` | oracle | Scope locked | Enter Phase 2 |
| `[APPROVED: DESIGN]` | oracle | Architecture locked | If Sprint List is empty → Phase 4; otherwise → Phase 3 Sprint 1 (3a) |
| `[APPROVED: DESIGN_REV_N]` | oracle | Design revised mid-sprint | Orchestrator reads `Current sprint:`, then asks oracle to assess whether the sprint's contract criteria are still valid (oracle appends this assessment to `## Design Revisions`). If contract stale → orchestrator routes to 3a (oracle rewrites contract); if contract valid and Completion Report submitted → 3d; if contract valid and no submitted report → 3c |
| `[APPROVED: SPRINT_N_CONTRACT]` | oracle | Contract verified | Check if Completion Report is **submitted** under Sprint N: submitted → 3d; not submitted → 3c |
| `[APPROVED: SPRINT_N]` | oracle | Sprint N complete | If Sprint N is last in Sprint List → Phase 4; otherwise → Sprint N+1 at 3a |
| `[APPROVED: PRODUCTION]` | oracle | Done | Lifecycle complete |
| `[RAISED: REQUIREMENTS]` | oracle | Requirements cap hit | See Raised-State Recovery; re-entry: oracle integrates user direction → Phase 1 step 4 |
| `[RAISED: DESIGN]` | oracle | Design cap hit | See Raised-State Recovery; re-entry: oracle integrates → Phase 2 step 3 |
| `[RAISED: DESIGN_REV_N]` | oracle | Design revision cap hit | See Raised-State Recovery; re-entry: oracle revises changed section → oracle re-reviews in a fresh review session → on PASS write `[APPROVED: DESIGN_REV_N]` and resume sprint |
| `[RAISED: SPRINT_N_CONTRACT]` | oracle | Contract cap hit | See Raised-State Recovery; re-entry: oracle rewrites contract from scratch → 3b |
| `[RAISED: SPRINT_N]` | oracle | Sprint cap hit | See Raised-State Recovery; re-entry: fixer addresses issues → 3d |
| `[RAISED: PRODUCTION]` | oracle | Close cap hit | See Raised-State Recovery; re-entry: fixer fixes → Phase 4 step 2 |
| `[ABORTED: SPRINT_N — {reason}]` | orchestrator | Mid-sprint pivot | Sprints 1..N-1 already approved remain valid. Oracle revises sprint list from Sprint N onwards (adding `[INVALIDATED: SPRINT_M]` annotations to Sprint N and any now-invalid future sprints); re-enter Phase 2 step 2 to revise the remaining sprint list only |
| `[ABORTED: DESIGN — {reason}]` | orchestrator | Design restart | Oracle revises the `## Design` section based on reason; re-enter Phase 2 step 1 |
| `[ABORTED: REQUIREMENTS — {reason}]` | orchestrator | Scope restart | Oracle clears `[APPROVED: DESIGN]`, marks all sprints `[INVALIDATED: SPRINT_M]`, resets Sprint List, then revises the `## Requirements` section; re-enter Phase 1 step 3 |
| `[INVALIDATED: SPRINT_M]` | oracle | Sprint made moot | Not a `Latest marker:` value — annotation only. For sprints with an existing block: written inside Sprint M's verdict section. For sprints not yet started (no block exists): written in the Sprint List table's Scope column as `[INVALIDATED]` and noted in `## Design Revisions`. Skip all invalidated sprints when advancing; if all remaining sprints are invalidated, enter Phase 4 |

If `Latest marker:` is missing, malformed, or unrecognized: write a `Delegation failure: malformed Latest marker` note under `## Escalations` and stop — only the user can repair this.

Valid `Current sprint:` values: `(none)`, `(none — zero sprints)`, `(complete)`, or an integer N. Any other value is malformed.

If `Current sprint:` is missing, malformed, or inconsistent with `Latest marker:` (e.g. marker says `[APPROVED: SPRINT_3_CONTRACT]` but `Current sprint:` says `2`): write a `Delegation failure: malformed Current sprint or unresolved placeholders` note under `## Escalations` and stop — only the user can repair this. Unresolved placeholders (e.g. `{feature}`, `{agent or @handle}`) in `plan_and_track.md` are also treated as malformed state — write a `Delegation failure: unresolved placeholders` note under `## Escalations` and stop.

---

## Oracle Consultation Protocol

Triggered **once per cap event**, before writing any `[RAISED: ...]` marker.

When `Rounds:` reaches `N/N` and the oracle's verdict is still FAIL, the orchestrator runs an oracle consultation **before** writing `[RAISED: ...]`. Use a fresh oracle session, never the same oracle session that wrote the final failing verdict.

**Oracle brief:** point it at `plan_and_track.md` — the full history of all prior verdicts, fix attempts, and completion reports for the blocked phase/sprint. Prompt:

> "You are reviewing a stuck phase. Read all prior verdicts and fix attempts in `plan_and_track.md`. Your task: identify the root cause of repeated failure and provide concrete, executable fix steps the fixer can follow next. Choose one: (A) output `UNBLOCK: [specific steps]` if you can identify a clear fix path; (B) output `ESCALATE: [what the user must decide or provide]` if the blocker requires information or decisions only the user can give."

**If oracle says UNBLOCK:**
1. Orchestrator writes `Oracle direction: [steps]` under `## Escalations`, tagged with the blocked phase/sprint (e.g. `Sprint N oracle:`).
2. Fixer gets **one bonus round** — the orchestrator gives it the oracle direction as part of its brief. This bonus round does **not** increment `Rounds:` (the cap counter stays at `N/N`).
3. Oracle re-reviews in a fresh review session. **PASS** → write `[APPROVED: ...]`. **FAIL** → write `[RAISED: ...]` + escalation summary. No second oracle consultation for this cap event.

**If oracle says ESCALATE:**
- Write `[RAISED: ...]` + escalation summary immediately (oracle's explanation becomes the escalation body).

**Delegation failure in oracle:** if the oracle itself fails (malformed output, refusal, timeout), treat as a delegation failure — log under `## Escalations`, skip the bonus round, and write `[RAISED: ...]`.

---

## Raised-State Recovery Protocol

When a `[RAISED: ...]` marker exists and the user has responded:

1. Orchestrator reads the escalation summary from `## Escalations`.
2. Orchestrator writes user response as `User direction: ...` under that entry.
3. If the user response is not actionable, append `User direction insufficient: [reason]` under the same escalation entry, keep the `[RAISED: ...]` marker unchanged, do not reset `Rounds:`, and stop until clearer direction is provided.
4. Orchestrator resets the `Rounds:` counter for the affected phase to `0/CAP` in `plan_and_track.md` (orchestrator is the active role here, not oracle).
5. Orchestrator follows the re-entry path in the marker table above.
6. On PASS, oracle writes the standard `[APPROVED: ...]` marker, replacing the RAISED marker as `Latest marker:`.

---

## Phase Procedures

The marker table above routes you into a phase. Read `$SKILL_DIR/reference/phases.md` for that phase's step-by-step mechanics (if `$SKILL_DIR` is unset: `~/.agents/skills/xdev/reference/phases.md` or the project-local skill path). The invariants in this file (agent responsibilities, severity, caps, doc-as-state) apply across all phases and are assumed already in context when reading that file.

---

## Doc-as-State Contract

`plan_and_track.md` is the **only** durable state file. (`requirements.md` / `design.md` may exist alongside it if a section was explicitly extracted via `→ see <file>` — treated as an extension of the plan file, not separate state.)

- Update `plan_and_track.md` **before** delegating to any sub-agent.
- `Latest marker:` is the canonical resume anchor — read it first, always.
- **Sprint archival:** after `[APPROVED: SPRINT_N]`, if `plan_and_track.md` exceeds ~400 lines, move the approved sprint's full block to `sprint_archive.md` (appending), replacing it inline with: `Sprint N — [APPROVED: SPRINT_N] — full block in sprint_archive.md`. The Status block, `## Requirements`, `## Design`, `## Phase Rounds`, `## Escalations`, and the current active sprint always remain in the active file.
- **Prefer reset over compaction.** On a long run, when the orchestrator's own context grows heavy, reset to a clean slate rather than compacting — `plan_and_track.md` is a complete handoff artifact. Re-read it and resume from `Latest marker:`; never rely on retained conversation history. (This is why every delegation brief is self-contained.)
- **Reference files by path, never paste file contents into the docs.** Contents go stale and bloat the handoff artifact; a path stays current.
- **Never write credentials, tokens, API keys, or secrets into xdev docs.**
- **Single source of truth.** The `## Status` block supersedes any orchestrator todo list — do not maintain both. Derive the next action from `Latest marker:` + the Marker Reference table, not from a parallel tracker.
- **Handover is the file, not a generated prompt.** To hand work to another agent (or a fresh you), give it the path to `plan_and_track.md` and the Golden Rule — it resumes from the Status block. Do not summarize state into a separate brief; a summary goes stale, the file does not.
- If a fact isn't in the docs, it doesn't exist for `xdev`.

---

## Repo AGENTS.md Checklist

xdev is repo-agnostic. For live verification (real running system, real data — not a committed test suite) to work inside xdev contracts, the repo's `AGENTS.md` (or `CLAUDE.md`) must document:

- **Live verification command** — the command to run: browser automation, API round-trips, file ingestion, DB write checks, etc. (e.g. `agent-browser`, a shell script, `playwright test` used ad-hoc locally)
- **Local env setup** — how to start the local stack before verification runs (e.g. `docker-compose up -d`, seed command, required env vars)
- **Test data preparation** — how to write real entries to the DB or prepare real files; how to clean up afterward
- **Pass criteria** — what a passing live verification looks like (exit code, log line, screenshot, observable state change, etc.)

If any of these are absent, xdev will log a `Delegation failure: live verification instructions missing` note under `## Escalations` at 3a

---

## File Layout

```
{repo}/
  .tmp/xdev/{feature}/
    plan_and_track.md          ← the single state file (req + design + tracking)
    sprint_block.md            ← template for appending sprint sections (not edited)
    requirements.md            ← optional: only if ## Requirements was extracted
    design.md                  ← optional: only if ## Design was extracted
    sprint_archive.md          ← optional: approved sprint blocks extracted for compactness
  .gitignore                   ← .tmp/ must be listed
```

---

## Checklist

- [ ] Bootstrap or resume (`plan_and_track.md` exists? Placeholders resolved?)
- [ ] Phase 1: Frame → `[APPROVED: REQUIREMENTS]`
- [ ] Phase 2: Design → `[APPROVED: DESIGN]`
- [ ] For each sprint (skip if Sprint List empty):
  - [ ] 3a Draft contract
  - [ ] 3b Review contract → `[APPROVED: SPRINT_N_CONTRACT]`
  - [ ] 3c Implement (no failing validation; Completion Report fully populated)
  - [ ] 3d/3e Evaluate + fix → `[APPROVED: SPRINT_N]`
- [ ] Phase 4: Close → `[APPROVED: PRODUCTION]`
- [ ] (Optional) Post-production revision — external review re-enters the lifecycle as new sprints
