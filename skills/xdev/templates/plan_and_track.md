# Plan & Track: {Feature Name}
**schema_version:** 3.2
Lifecycle authority: `xdev/SKILL.md`; shared policy: `agent-review/references/execution.md` and `agent-review/references/coordination.md`;
Review authority: `agent-review/references/review.md`.
Setup notes (do not copy into live state):
When creating a default locator, trim and lowercase the objective slug, replace each run
of non-alphanumeric characters with one hyphen, then trim leading and trailing hyphens.
For migration or malformed-state recovery, reconstruct changed anchor/cadence/recovery
fields from authoritative instructions and evidence before dependent work. For a 3.0/3.1
plan, retain policy-derived spent calls/limits as history, not xdev stop authority.
Explicit user/host constraints remain binding; preserve the complete Review history (X2).

## State Locator
- **Objective identity:**
- **Resolved state file:** {exact path}

## Task Ledger
| Logical task ID | Role/lane | Runtime transport ID | Generation | Scope and assignment ref | Status | Supersedes | Integration / linked next task | Durable terminal result/evidence | Replacement reason |
|---|---|---|---|---|---|---|---|---|---|

## Authoritative Todo List
Rows: `- [ ] TODO-{stable ID} — ...`, checked form `- [x]`.
Each has type (implementation/correction/integration/required-validation/Review-action/
closure-assessment), owner, bounded scope/authority reference, evidence,
discharge revision/reference and lineage. Settlement distinguishes satisfaction from
evidence-backed unmet/blocked work.

## State
- **State revision:**
- **Lifecycle phase:** baseline / sprint / final validation / complete
- **Outcome:** active / delivered / conclusively blocked / unsuccessful
- **Execution disposition:** continue / awaiting_user
- **Closure candidate:** {terminal record reference or none}
- **Current delivery-unit record:** {scope/eligibility/validation/integration authority}
- **Snapshot ID:** {current product binding; final validation/assessment share final ID}
- **Current sprint:**
- **Next action and owner:**
- **Pending tasks:** {ledger references or none}
- **Integration:** {unit reference}
- **Validation:** {due/deferred check names or IDs and evidence refs; outstanding checks are pending}
- **Final Review:** {pending or result reference}

## Coherent Baseline
### Goal Understanding
- **Goal statement / high-level outcome:** {requested deliverable and finish line: working outcome or readiness for a named decision}
- **Objective / goal revision:**
- **Basis:** {original request and later constraints/grants; verbatim if permitted, otherwise exact permitted reference and operative limits}
- **Original-outcome anchor / non-goals / observable acceptance / material assumptions:**
- **Goal revision/source history:** {only authoritative outcome changes; design is separate}
- **Latest resume/milestone alignment:** {progress/next action versus original anchor}
- **Goal status:** clear / clarified / open
- **Initial clarification used:** {no or dependency/assessment/reply references}
- **Material undecided questions / historical choices, not constraints:**

### Target
- **Scope / allowed files / exclusions:**
- **Intended behavior / expected outputs:**
- **Authoritative basis:**
- **Planning result/decisions / reconsideration triggers:**
- **Design / risk boundaries:**
- **First working end-to-end slice / coherent delivery-unit boundaries:**
- **Normal, boundary/error and regression/invariant cases:**
| Criterion ID/materiality | Observable expectation | Authoritative basis | Result/evidence | Todo IDs |
|---|---|---|---|---|
| Assumption ID | Default/source | Consequence | Reconsideration/validation trigger | Status |
|---|---|---|---|---|

### Validation Strategy
- **Final-validation execution owner:**
Schedule each required deterministic check or faithful scenario once. Deferred checks stay pending with their owner and due point, never PASS.

| Check name or ID / criterion | Exact command/scenario / inputs / expected | Owner | Cadence / due point | Cost/duration / why cheaper evidence cannot suffice if run early | Rerun trigger / evidence applicability |
|---|---|---|---|---|---|

- **Corpus claim class / claimed and automation scopes / exact rules / mismatches:**
- **Semantic truth:** {parent contextual item-level baseline}
- **Mechanical expectation:** {exact rule/invariant/fixture basis}
- **Population support:** {defined population and independent method/exhaustive evidence}

### Baseline Validation Evidence
Record each execution once. Sprint and final evidence may reference its exact row and raw result;
retain the original revision/snapshot and justify applicability to current inputs under P11, or rerun.

| Revision | Execution snapshot / current applicability | Owner | Command/scenario/inputs / duration | Expected | Actual | PASS/FAIL/BLOCKED | Exit | Material raw reference |
|---|---|---|---|---|---|---|---|---|

## Sprint Records
{Use `xdev/templates/sprint_block.md`; preserve historical snapshot bindings.}

## Review Coverage Log
Record each assessment once; an exact reference to an existing sprint assessment suffices. Preserve complete dispatch/finding lineage, not a lifetime Review allowance.

| Review ID / ordinal | Stable outcome / covered unit/sprint IDs | Revision / owner / snapshot | Raw oracle-review-result / criterion evidence | Stable findings / prior resolutions | Parent integration / corrective batch / class strategy / progress ref | Optional advice disposition (accept/defer/reject with rationale) |
|---|---|---|---|---|---|---|

- **Latest coherent-boundary progress/recovery:** {criterion/class improvement or decisive new
  evidence; failed mechanism and changed repair/validation; Planning result/trigger when needed;
  viable materially distinct next action versus original-outcome anchor, with evidence refs}

## Final Validation Evidence
| Revision | Execution snapshot / current applicability | Owner | Command/scenario/inputs / duration | Expected | Actual | PASS/FAIL/BLOCKED | Exit | Material raw reference |
|---|---|---|---|---|---|---|---|---|

## Final Whole-State Review
- **Final assessment:** {exact whole-state Review Coverage Log entry, or pending; reuse a covering sprint only when scope and evidence coincide}
- **Covering delivery-unit eligibility and todo reconciliation:** {authoritative reference;
  record independent facts only where final scope differs}
- **Remaining authorized actions / blockers:** {evidence or none}

## Terminal Decision Record
- **Candidate ID / candidate revision / proposed Outcome:**
- **Oracle logical task ID / generation:**
- **Closure basis:** {coincident final assessment or bound closure assessment}
- **Assessment conclusion / authoritative reference:**
- **Reconciliation:** {baseline/criteria, sprints, generations/supersession, integration,
  validation, findings, blockers/recovery, remaining actions, complete todos}
- **Authoritative evidence / unmet criteria:**
- **Materially distinct recovery courses / attempted results / evidence-backed exclusions:**
- **Unresolved findings / unsuccessful basis:** {genuine recovery exhaustion, not count or impossibility}
- **Remaining authorized actions / why no viable recovery remains:**
- **Todo settlement:** {satisfied refs; unmet/blocked dependencies or exhausted-recovery basis;
  designated assessment todo discharge revision/reference}
- **Parent decision:** {Outcome, disposition, rationale, atomic integration revision}

## History
{Semantic/recovery-significant revisions and authoritative references only.}
