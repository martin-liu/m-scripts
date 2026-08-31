# Plan & Track: {Feature Name}

## Bindings

- **orchestrator:** @orchestrator
- **fixer:** @fixer
- **doc location:** .tmp/xdev/{feature}/

## Lane Durability

| Lane | Lane ID | Runtime ID | Generation | Status | Reason | Successor runtime | Handoff |
|------|---------|------------|------------|--------|--------|-------------------|---------|
| Planning | {immutable lane ID} | {runtime ID} | 1 | active | — | — | bootstrap |
| Review | {immutable lane ID} | {runtime ID} | 1 | active | — | — | bootstrap |

Exactly one active row per lane is valid. On replacement, retire the old row and
append a fresh active row for the same lane.

## Status

- **Latest marker:** (none)
- **Current sprint:** (none)
- **Next owner:** Planning
- **Next action:** draft requirements
- **Final Review:** pending
- **Planning completion report:** pending
- **Pending task IDs:** (none)
- **Integration status:** pending
- **Validation status:** pending
- **STOP: COMPLETE status:** not recorded

## Requirements

### Initial Brief

### Scope

### Acceptance Criteria

### Assumptions

| ID | Assumption/default | Source | Consequence | Validation/retirement trigger | Status |
|----|--------------------|--------|-------------|--------------------------------|--------|

## Requirements Review

## Design

### Global Flow

```text
[GF-01 Entry] → [GF-02 Decision] → [GF-03 Observable outcome]
```

### Details

## Design Review

## Sprint List

| # | Title | Global Flow nodes | Scope |
|---|-------|-------------------|-------|

## Planning Reports

| Report ID | Phase/sprint | State | Basis/provenance | Review evidence | Pending | Integrated | Validation | Next owner/action |
|-----------|--------------|-------|------------------|-----------------|---------|------------|------------|-------------------|

## Escalations

## History

Append requirements/design/sprint verdicts, Completion Reports, and factual
delegation failures here. Preserve history; it never overrides Status.
