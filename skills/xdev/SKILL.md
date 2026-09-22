---
name: xdev
description: Full software-lifecycle route for complex multi-sprint work requiring durable coordination across phases, risk boundaries, or context limits. Use Direct or Reviewed for bounded work.
license: MIT
metadata:
  author: martinliu
  version: "1.1.0"
---

# xdev

xdev is the durable lifecycle for complex work requiring coordination across
phases, risk boundaries, or context limits. `plan_and_track.md` is its sole
durable state record: coherent target baseline → risk-bounded sprints → final
whole-state verification. The baseline defines intended behavior, authoritative
basis, acceptance evidence, and risk boundaries. Apply the Orchestrator's global
target-definition, routing, safety, liveness/recovery, source-corpus,
user-contact, reconciliation, escalation, and completion policy; this skill adds
only the durable lifecycle rules below.

## Bootstrap, resume, and state authority

Each template has a concise `schema_version`. Bootstrap, migration, or malformed
state recovery first reads the exact templates and fails closed if the version or
required fields cannot be migrated safely. Ordinary resume reads the recorded
schema version, state locator, durable task/todo/evidence fields, and current
status; it need not reread all template prose. Before creating or updating a
sprint block, read the exact `skills/xdev/templates/sprint_block.md` template and
preserve its required fields. Reuse the exact resolved path. If a template is
unavailable, search existing xdev plans for a matching recorded objective identity
before creating anything; an ambiguous match fails closed, and a second plan must
never be created silently.

The Orchestrator determines one deterministic state-file locator from the
objective. Unless the caller supplies a path, use the concise default
`.tmp/xdev/{objective-slug}/plan_and_track.md`. Normalize the objective slug by
lowercase, trim, replace every run of non-alphanumeric characters with a
hyphen, and trim hyphens. A caller-supplied path remains exact; do not
normalize it. Record the resolved exact path and objective identity in the
state. Bootstrap creates the file only when it is absent; it never overwrites
an existing plan. If a default path exists for a different objective, do not
overwrite it; stop or escalate under the global policy. Resume uses the same
locator, reads the durable record before dispatch, and escalates a missing,
conflicting, or ambiguous locator under the global policy.

The Orchestrator is the sole writer of `plan_and_track.md`. Planning, Fixer, and
Review return contracts, reports, verdicts, and evidence; they do not edit the
record. Transport state (`task_status`, `task_result`, notifications, or
runtime availability) may inform reconciliation, but never supplies a semantic
reconstruction of the durable record. Repair missing or malformed state only
from the record and authoritative task reports/evidence, under the global
reconciliation rules.

`plan_and_track.md` contains one authoritative checkbox todo list because
OpenCode has no todo tools. The Orchestrator is its sole writer. Todo IDs are
stable and never reused: unchecked means outstanding, and an item may be
checked only after reconciliation, integration, and required evidence are
recorded with a state revision and authoritative reference. Never silently
delete or reopen a todo; replacement or follow-up work receives a new ID with
lineage. The task ledger remains authoritative for transport, generation, and
integration; sprint contracts for acceptance; and evidence/Review for results.
Todos point to those records rather than duplicating them.

On resume, before dispatch, after results, before Review readiness, and before a
closure candidate, the Orchestrator reads and reconciles the complete todo list.
Review readiness requires scoped implementation, correction, integration, and
required-validation todos to be discharged; the designated Review-action todo
may remain open. Review `FAIL` creates new todo IDs for batched corrections and
follow-ups. Fixer and Oracle may propose changes but never edit checkboxes.

## Durable revisions, snapshots, and recovery

Every durable semantic write to `plan_and_track.md` increments **State
revision** exactly once. Logical task/candidate/todo creation is the semantic
binding at revision N, one transition from prior revision R to N=R+1, before
dispatch. Dispatching that task, setting its runtime transport ID, and updating
running/pending transport status are revision-neutral bookkeeping unless they
change scope, acceptance, integration, or the closure premise. Closure binding
uses the logical task/generation pair and revision, not runtime identity. The
bound closure task result, assessment, and decision remain one atomic
transition from N to N+1; any substantive premise change invalidates them and
requires a new binding.
Purely typographic or formatting-only edits do not change revision unless they
alter authoritative content. Record the revision with every validation and
Review evidence.

Each validation and Review record names the snapshot ID for its corresponding
unit/state. Its canonical manifest records repository root and base, sorted
relevant paths with status and file mode, byte hashes, the hash of those
manifest lines, and explicit exclusions. A commit/tree ID is usable only when
it exactly materializes all relevant changed files for that unit; otherwise use
that deterministic manifest/hash over relevant tracked, staged, and untracked
changed files. Historical sprint records retain their original snapshot IDs.
The final whole-state validation and Review use one final snapshot ID, recorded
in the current state and each corresponding final record. Bookkeeping-only
state changes do not stale an unchanged product snapshot; evidence captured
before a product mutation is stale.

Durable evidence is a repository path plus content hash, immutable artifact or
URL, or inline material evidence. Transport-only references cannot discharge
todos or establish Review readiness.

The plan, task ledger, authoritative todos, validation/Review records, and
their references are sufficient to resume after context reset. Record an
authoritative terminal result/evidence reference and, for replacements, the
replacement reason. Do not make volatile unchanged-resume counts or nudge
history part of semantic state.

## Durable task ledger and outcomes

The record contains a durable task ledger with one entry per authorized task
dispatch, created in the pre-dispatch transition.
Each entry records logical task ID, role/lane, runtime transport ID, generation,
exact scope, status,
supersedes/replacement lineage, integration state, authoritative terminal
result/evidence reference, and replacement reason where applicable. Planning and Review are
immutable, distinct lanes with one active generation per lane. Invoke rather
than redefine the Orchestrator's global transport and replacement protocol:
retire a prior generation while preserving valid evidence, create a fresh
generation for unfinished scope only, and never integrate superseded results,
cross lanes, duplicate work, or drop work.

The lifecycle state records one singular **Outcome**: `active`, `delivered`, or
`conclusively blocked`. Each sprint and task has a separate **Status** using only
`pending`, `running`, `completed`, `failed`, `blocked`, `cancelled`, or
`superseded`; it may also record a local result classification, but never replaces
or implies the lifecycle Outcome.
`delivered` requires the applicable contract and validation to be satisfied.
At lifecycle level, `conclusively blocked` means no viable in-scope remediation
remains and the exact blocker is recorded; it is terminal non-delivery, never
successful delivery, and cannot satisfy a delivery acceptance criterion.

Status is authoritative and must be current before dispatch and after
integrated results. Use explicit state fields (revision, phase, current sprint,
next owner/action, pending tasks, integration, validation, final Review, and
outcomes) as the resume index; do not use a vague `Latest` marker. History is
for semantic or recovery-significant facts only: accepted baseline or Review,
completed/reviewed sprint, semantic revision, material blocker or replacement,
final validation, and completion. Routine dispatches, diagnostics, and
failures update Status or the relevant sprint/task entry.

## Active-lifecycle continuation

Before ending an xdev root turn, reread the exact resolved plan from disk and
reconcile every result received during the turn. End only when (a) the lifecycle
is terminal and all closure, validation, Review, todo, and integration invariants
are recorded; (b) Oracle Planning explicitly authorized the specific user
question and that question is now asked; or (c) no action is ready and a named,
non-superseded task is confirmed live, with its task ID and generation recorded.
Otherwise execute or dispatch the next authorized action. A status-only update,
child completion, remediable failure, context pressure, compaction, or a future
Next action is not an exit condition. At each xdev reconciliation point, use the
exact resolved plan path and complete authoritative todo list.

## Baseline, sprint, and Review evidence

Baseline and sprint validation must be compact and verifiable. For each check or
scenario record the state revision, snapshot ID, execution owner, expected result, actual
result, status (`PASS`, `FAIL`, or `BLOCKED`), exit status when a command ran,
and a raw-output/evidence reference when material. Do not replace raw evidence
with a summary when the reference is needed to reproduce or inspect the result.
Review evidence uses the same fields, includes the Review revision, Review owner,
and snapshot ID; Review returns an independent `Verdict: PASS` or `Verdict: FAIL`, findings, and
`APPROVED` only on `Verdict: PASS`. A precondition failure is `Verdict: FAIL` with reason code
`REVIEW_PRECONDITION_NOT_MET`; `BLOCKED_REVIEW` is never an approval.

## Completion and Review

The Orchestrator records successful completion only when the plan's final-
validation evidence table has a result for every approved check, the final
whole-state Review record has `Verdict: PASS` and its required evidence fields,
zero pending tasks, all non-superseded results integrated, all required
validation complete, and the lifecycle Outcome is `delivered`. When the final
sprint Review has exactly the whole-state scope and evidence, that Review plus
Orchestrator reconciliation is sufficient for delivered closure; no second
closure assessment is required. Any other delivered closure has an uncovered
closure premise and uses the revision-bound closure-assessment route. A
lifecycle `conclusively blocked` outcome is terminal non-delivery, not
successful delivery. A sprint presented for Review is otherwise complete only when the
Orchestrator's global Review-readiness gate is `REVIEW_READY` for its exact
unit, contract, and snapshot: behavior is implemented, every acceptance
criterion passes, all non-superseded results are integrated, no unit work is
pending, every required validation passes against that snapshot, prior
actionable findings are resolved and revalidated, and no known actionable
in-scope defect remains. A remediable failure is not complete. The separate
`BLOCKED_REVIEW` exception is non-delivery only and does not alter parent
closure rules.

Each completed risk-boundary sprint receives independent Review. A last or only
sprint Review may also be final whole-state Review when scope and evidence
coincide, with one
verdict serving both. Review is read-only and does not create truth, mutate,
route, or recover.

## Parent-objective closure

Routine recovery while Outcome is `active` remains Orchestrator-owned and does
not require Oracle. A separate revision-bound closure candidate and independent
full-context Oracle assessment is required for blocked/negative closure or when
the closure premise is otherwise uncovered; for a delivered outcome whose final
sprint Review scope and evidence coincide with whole-state scope, that Review
and Orchestrator reconciliation cover the closure premise without a duplicate
Oracle call. The Orchestrator first rereads the exact resolved plan path from disk
and reconciles the complete record: baseline and criteria, all sprints, task
generations and supersession, integration, validation, Review findings,
blockers and recovery attempts, and remaining authorized actions.

The candidate records its ID, current state revision, proposed Outcome,
reconciliation, and authoritative evidence references. Oracle reads the entire
current plan and those authoritative references directly. The assessment is
valid only for the exact candidate ID, candidate revision, and proposed
Outcome, and is durably bound to the Oracle logical task ID, task generation, and
authoritative assessment reference. It has one of these advisory conclusions:
`CONTINUE_REQUIRED`, `USER_INPUT_REQUIRED`, or `TERMINAL_PREMISE_SUPPORTED`.
Missing, malformed, stale, or unavailable assessment evidence leaves Outcome
`active`; only a substantive event that changes the closure premise invalidates
the candidate and assessment. The bound task's terminal result is explicitly
exempt because it is integrated atomically with the assessment and decision.
`awaiting_user` is an execution disposition, not an Outcome. `USER_INPUT_REQUIRED`
must state the exact user-owned decision or action, why available evidence
cannot decide it, and the exact concise question authorized for the Orchestrator;
Oracle defines this as Planning-lane semantic advice and never contacts the
user.

When the closure-assessment route applies, the candidate and Oracle logical task ID+generation are created at state revision
N before dispatch. Oracle assesses that exact candidate at N. The Orchestrator
atomically records the terminal task
result, assessment, and decision as one closure transition producing revision
N+1. The bound task's terminal result and this atomic integration are explicitly
exempt from invalidation; only a substantive event that changes the closure
premise requires a new candidate and assessment.

The Orchestrator is the sole state writer and decision owner. If the final
sprint Review scope and evidence exactly equal the whole-state scope and all
completion invariants pass, that `PASS` Review and Orchestrator reconciliation
may transition to `delivered` without a separate closure assessment. For
blocked/negative closure, or for any otherwise uncovered closure premise, a
terminal transition requires the matching candidate ID, candidate revision,
proposed Outcome, and durable revision-bound Oracle assessment with conclusion
`TERMINAL_PREMISE_SUPPORTED`. A
`CONTINUE_REQUIRED` or `USER_INPUT_REQUIRED` conclusion forces Outcome to
remain `active`; no terminal transition or terminal user-facing claim is
permitted. No terminal user-facing claim is permitted while the durable Outcome
remains `active`. Successful delivery still requires final whole-state Review
`PASS` and every existing completion invariant. A blocked closure is terminal
non-delivery and requires a recorded blocker with no remaining viable
authorized action.

Closure requires no unchecked non-closure todo. When the closure-assessment
route applies, its designated todo may remain open at candidate revision N and
is atomically discharged with the bound task result, assessment, and decision at
revision N+1. Missing, contradictory, stale, or unreconciled todo state fails
closed and prevents Review readiness or terminal closure.

## Lifecycle

1. The Orchestrator authors and accepts a coherent baseline, directly for
   ordinary work or after incorporating Oracle Planning when conditionally
   invoked. The baseline includes authoritative discovery, requirements,
   assumptions, intended output or behavior, material edge cases and
   invariants, risk boundaries, validation, and sprint contracts. For
   deterministic functional work, record expected tests or scenarios. When
   acceptance depends on extracting, transforming, classifying, matching, or
   counting a defined source corpus, distinguish the claim type. For semantic
   item-level ground-truth claims, the Orchestrator first reads every claimed
   item and records an item-by-item contextual expected result; identical-scope
   automation runs only after that baseline. Mechanically specified
   transformations use the contract's exact rules, invariants, and reference
   fixtures for expected results. Population/statistical claims use a defined
   population plus independent sampling/estimation or exhaustive support. None
   of these rules permits self-generated expected truth. Oracle Planning may
   incorporate the recorded basis but never creates corpus truth; the
   Orchestrator remains the owner of the baseline and its acceptance. Ordinary
   source-code work does not trigger this corpus ordering.
2. Keep Oracle Planning and delivery-unit Review lanes distinct. The Orchestrator
   authors and accepts the baseline; there is no optional or conditional
   preimplementation Baseline Review. Invoke Oracle Planning only for strategic
   design, material tradeoffs, unresolved assumptions, semantic replanning, or
   another global trigger that materially requires it; otherwise the
   Orchestrator authors and accepts the baseline directly.
3. After the accepted baseline, the Orchestrator dispatches each approved sprint's
   bounded Fixer contract. Same-scope automation may run only now. The
   Orchestrator reconciles completion and validation evidence, rebuilds the
   global Review-readiness gate, and dispatches sprint Review for each genuine
   risk boundary only when that gate is `REVIEW_READY` (or as an explicitly
   labeled non-delivery `BLOCKED_REVIEW`).
4. On Review FAIL, the Orchestrator reconciles all findings, batches compatible
   unchanged-semantics corrections, integrates them, reruns affected and
   contract-required validation, rebuilds readiness, and sends one whole-unit
   Review. Do not review individual findings, files, diagnostics, or results.
   Return to Planning for a semantic, design, risk-boundary, or validation-
   strategy change.
5. The Orchestrator assigns and records the final-validation execution owner in
   the baseline. That owner runs the approved final checks and returns the
   evidence record; the Orchestrator records it, and final Review independently
   checks the whole resulting state. The Orchestrator reconciles the explicit
   completion invariants—final evidence for every approved check, final Review
   `PASS`, zero pending tasks, all non-superseded results integrated, and all
   required validation complete—then records completion through the conditional
   delivered or revision-bound closure-assessment protocol above.

Sprints are review-worthy risk boundaries, not arbitrary files or checklist
items. Combine adjacent mechanical changes sharing a contract and validation;
split for independent failure isolation, ordering, or materially different
invariants. User contact and escalation follow the Orchestrator's global policy.
