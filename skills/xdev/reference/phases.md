# xdev phases

Global authority, safety, completion, and resume rules are in `SKILL.md`.

## Phase 1 — Requirements

Planning drafts the PRD, assumptions, scope, acceptance criteria, and targeted
questions. Review independently approves requirements.

## Phase 2 — Design

Planning authors the Global Flow and sprint list. Review independently approves
the design. A material design change returns to this phase.

## Phase 3 — Sprint loop

Planning supplies a bounded contract: scope, allowed files, Global Flow nodes,
independently verifiable acceptance criteria, one validation command, evidence
paths, assumptions, and out-of-scope work. Review PASS permits fixer execution;
FAIL returns concrete findings to Planning.

Fixer implements only the approved contract and returns raw evidence. Review
evaluates code and evidence. On FAIL, Planning chooses a revised contract or an
explicitly bounded fixer correction. On PASS, Planning records a sprint report
and routes the next sprint or final verification.

## Phase 4 — Close

Planning supplies a bounded final-verification plan. Fixer runs its read-only
commands; Review independently approves production. File-changing, privileged,
external, or side-effectful final checks require a Review-approved contract first.
Planning supplies the final report and `STOP: COMPLETE`; the orchestrator records
it only after the five completion facts are true.
