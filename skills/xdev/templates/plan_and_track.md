# Plan & Track: {Feature Name}

## Bindings

<!-- Resolved once at bootstrap. Do not change after first sprint begins. -->
- **planner:** {agent or @handle}
- **generator:** {agent or @handle}
- **evaluator:** {agent or @handle}
- **researcher:** {agent or @handle} ← omit if not available
- **doc location:** .tmp/xdev/{feature}/

## Status

<!-- CANONICAL RESUME ANCHOR — evaluator writes APPROVED/RAISED markers; orchestrator writes ABORTED markers. -->
**Latest marker:** (none)
**Current sprint:** (none)

## Phase Rounds

<!-- Evaluator increments on every verdict. Orchestrator resets to 0/CAP after a RAISED state is resolved. -->
- Requirements: Rounds: 0/3
- Design: Rounds: 0/3
- Production: Rounds: 0/3
<!-- Design revisions: add "Design Rev N: Rounds: 0/2" here when each mid-sprint revision starts -->

## Research Log

<!-- Confirmed external/codebase findings, reconciled and accepted. Reviewers treat these as
     shared accepted context — do NOT re-research what is recorded here.
     Reference files by path only; never paste file contents.
     Format per entry: [finding] — source: [path or URL] — confirmed by: {researcher|planner} -->

## Requirements

<!-- Filled by planner during Phase 1. All Open Questions must be resolved before [APPROVED: REQUIREMENTS].
     If this section grows unwieldy, extract it to requirements.md and replace the body with:
     → see requirements.md -->

### Initial Brief

<!-- The original user request or feature description. Every role reads this to understand the goal. -->

### User Stories

<!-- Who needs this, and what outcome do they get? -->
<!-- Format: As a {role}, I want to {action} so that {outcome}. -->

### In Scope (MVP)

<!-- What must ship for this to be useful? Be specific. -->

### Out of Scope (Deferred)

<!-- Explicitly list what is NOT in this release. Prevents scope creep. -->

### Hard Constraints

<!-- Non-negotiable: security, compliance, performance, compatibility. Fill in only what applies. -->
- **Security:**
- **Performance:**
- **Compatibility:**

### Open Questions

<!-- Unresolved decisions that block design. ALL must be answered before [APPROVED: REQUIREMENTS]. -->
<!-- Format: Q: [question] → A: [answer] -->

## Requirements Review

<!-- Evaluator APPENDS verdict here each round during Phase 1. Never overwrite — preserve history.
Format:
Requirements verdict: PASS | FAIL
Rounds: N/3
Issues (if FAIL — at least one critical or major):
- [area] — severity: critical|major|minor — [specific issue]
-->

## Design

<!-- Filled by planner during Phase 2. All Open Questions must be resolved before [APPROVED: DESIGN].
     If this section grows unwieldy, extract it to design.md and replace the body with:
     → see design.md -->

### Architecture

<!-- High-level diagram (text). How does this fit into the existing system? -->

```
[component] → [component] → [component]
```

### Data Model

<!-- Tables, schemas, or types introduced or modified. -->

### State Machines

<!-- Any meaningful state transitions. Format: state → event → next state -->

### Interfaces / API Surface

<!-- New or changed public interfaces, endpoints, or contracts. -->

### Error Handling

<!-- How failures propagate. What is retried, what is terminal, what surfaces to the user. -->

### Key Alternatives Considered

<!-- What else was on the table, and why this approach was chosen. Keep brief. -->

| Alternative | Why Rejected |
|-------------|--------------|
| | |

### Open Questions

<!-- Unresolved at design time. Must be resolved before [APPROVED: DESIGN]. -->
-

## Design Review

<!-- Evaluator APPENDS verdict here each round during Phase 2. Never overwrite — preserve history.
Format:
Design verdict: PASS | FAIL
Rounds: N/3
Issues (if FAIL — at least one critical or major):
- [area] — severity: critical|major|minor — [specific issue]
-->

## Sprint List

<!-- Filled during Phase 2. Titles and one-line scope only — contracts written just-in-time. -->
<!-- Leave empty for zero-sprint case. -->
<!-- For unstarted invalidated sprints, update Scope column to [INVALIDATED] and note in Design Revisions. -->

| # | Title | Scope |
|---|-------|-------|

---

## Sprint Log

<!-- Planner appends sprint_block.md content here for each new sprint at step 3a. -->

---

## Production Review

<!-- Evaluator APPENDS verdict here each round during Phase 4. Never overwrite — preserve history.
Format:
Production verdict: PASS | FAIL
Rounds: N/3
Issues (if FAIL — at least one critical or major):
- [area] — severity: critical|major|minor — [specific actionable description]
-->

---

## Escalations

<!-- Written by evaluator on cap hit, or by orchestrator on delegation failure. Format per entry:
[RAISED: X] — what failed, why cap was hit, what user needs to decide.
User direction: (written by orchestrator after user responds)

Delegation failure: [context] — [reason]
-->

---

## Design Revisions

<!-- Written when mid-sprint design changes occur, or sprint list is mutated. -->
<!-- Format: Design Rev N: Paused sprint: M — [what changed and why] -->
<!-- Sprint list change: Sprint N added/removed/reordered/invalidated — [reason] -->
<!-- Design revision verdicts are APPENDED here below the corresponding entry.
Verdict format:
Design revision verdict: PASS | FAIL
Rounds: N/2
Issues (if FAIL):
- [section] — severity: critical|major|minor — [specific description]
-->

---

## Feedback Log

<!-- Used for post-production revision: external review comments after [APPROVED: PRODUCTION]. -->
<!-- Triage entries: [comment summary] → implement | defer | reject — [rationale] -->
<!-- Implement items become ordinary sprints appended to the Sprint List (standard SPRINT_N markers). -->
<!-- Origin noted under Design Revisions as "external review". -->
