# Ordinary Reviewed unit record

Create this durable carrier before the first child dispatch. It **references** evidence — never
pasted logs, duplicated product files, or an approval artifact. Bind dispatches to its path and byte
hash, not its own; if it can change while Oracle reads it, copy it immutably as evidence.

```markdown
# Unit record — <objective ID> / <unit ID>

## Identity
- Objective ID / goal revision; unit ID / complete accepted end-to-end outcome:
- Route: Direct | Reviewed | xdev; generation: <current logical generation>
- Repository root / base; live record locator: <path>

## Goal state
- Goal statement / basis; status: clear | clarified | open; clarification used: yes (<refs>) | no
- Dependency / assessment / reply references:

## Original intent
- Exact original request; later constraints; exact authorizations; assumptions and trigger:

## Contract
- Bounded target (behavior/output, authoritative basis, allowed scope); expected outcomes and
  criterion IDs; invariants, edge cases, exclusions:
- Required validation (commands, scenarios, faithful evidence, owner):

## Snapshot
- Product identity: <commit/tree or path+hash set, material modes, deletions, exclusions>
- Output evidence: <separate references>

## Criterion evidence
| Criterion | Evidence (execution or static/scenario) | Owner | Result |
|---|---|---|---|

## State
- Integration status and non-superseded results; pending implementation, correction, integration,
  validation; known defects and residual risk; authorized next action:

## Tasks
| Logical task ID | Generation | Status | Runtime ref | Scope | Integration |
|---|---|---|---|---|---|

Statuses: pending | running | completed | failed | blocked | cancelled | superseded. Runtime IDs
are transport metadata; never integrate a superseded generation's output.

## Review dispatches
| # | Lane | Date | Runtime ref | Verdict | Findings | Disposition | Correction evidence |
|---|---|---|---|---|---|---|---|

`agent-review/references/review.md` owns the dispatch cap, readiness gates, and correction rules —
cite, do not restate. Attach each raw result and finding disposition (corrected | rebutted |
superseded | outstanding), with, after a second whole-unit FAIL, the changed strategy and the
earlier failure's cause.

## Decisions
| Decision | Options | Selection | Rationale | Evidence that would change it |
|---|---|---|---|---|
```

Keep it current whenever a dispatch, correction, or integration changes a fact; generation,
rename, or snapshot changes never reset unit identity, finding IDs, the clarification allowance, or
the dispatch count. xdev uses `xdev/templates/plan_and_track.md`.
