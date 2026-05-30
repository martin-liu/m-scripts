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

## Requirements Review

<!-- Evaluator APPENDS verdict here each round during Phase 1. Never overwrite — preserve history.
Format:
Requirements verdict: PASS | FAIL
Rounds: N/3
Issues (if FAIL — at least one critical or major):
- [area] — severity: critical|major|minor — [specific issue]
-->

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
<!-- Design revision verdicts are APPENDED here below the corresponding entry. -->

---

## Feedback Log

<!-- Used only during warm-session feedback integration after [APPROVED: PRODUCTION]. -->
<!-- Triage entries: [comment summary] → implement | defer | reject — [rationale] -->
<!-- FB sprint blocks appended below (same structure as sprint_block.md). -->
