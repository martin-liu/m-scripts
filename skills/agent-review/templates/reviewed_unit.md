# Ordinary Reviewed unit record

Create/adopt before first dispatch; reread on resume. Carry facts and references, not
duplicated product files/logs or an approval artifact. Bind dispatches to this record's
exact path and byte hash; use an immutable copy if it may change during reading.
Shared policy is `agent-review/SKILL.md`; Review is `agent-review/references/review.md`.
xdev uses `xdev/templates/plan_and_track.md`.

```markdown
# Unit — <objective ID> / <unit ID>
schema_version: 3.0

## Identity and goal
- Objective ID / goal revision; stable unit ID / complete accepted end-to-end outcome:
- Route; repository root/base; exact live record locator:
- Goal statement/basis/status; initial clarification used:
- Dependency/input-assessment/reply references:

## Original basis
- Verbatim original request, later constraints and exact grants:
- Assumptions/defaults and reconsideration triggers:
- Authoritative sources/raw evidence/contrary evidence/access limits:
- Material undecided questions; historical parent choices/artifacts, not constraints:

## Target
- Intended behavior/output, authoritative basis, allowed scope/exclusions:
- Criterion IDs/materiality/observable expectations; cases/invariants:
- Required validation commands/scenarios/evidence and execution owner:

## Snapshot
- Commit/tree or deterministic manifest/hash; modes/deletions/exclusions:
- Output evidence separately:

## Criterion evidence
| Criterion | Expected/actual and execution/static/scenario reference | Owner | Result |
|---|---|---|---|

## Current state
- Integration/non-superseded results; pending implementation/correction/integration/validation:
- Known defects/residual risk; authorized next action:

## Tasks
| Logical task ID | Generation | Status | Runtime transport ref | Scope | Integration | Durable result |
|---|---|---|---|---|---|---|

## Assessments and correction
| Ordinal | Mode | Task/generation | Snapshot | Raw result | Findings/dispositions | Correction evidence |
|---|---|---|---|---|---|---|
- Complete prior results/finding resolutions and supersession mapping:
- Second-deficiency changed strategy, earlier failure and regression controls:

## Decisions
| ID | Oracle-derived course / historical parent choice reference | Selection | Rationale | Trigger |
|---|---|---|---|---|
```

Update whenever dispatch, correction or integration changes facts. Shared identity and
Review rules govern statuses, generations, stable finding IDs, clarification and expenditure;
none resets on rename, resume or snapshot change.
