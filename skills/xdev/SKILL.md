---
name: xdev
description: Full software-lifecycle route for complex multi-sprint work requiring durable coordination across phases, risk boundaries, or context limits. Use Direct or Reviewed for bounded work.
license: MIT
metadata:
  author: martinliu
  version: "2.0.0"
---

# xdev

Durable coordination: coherent baseline, risk-bounded sprints, final whole-state evidence.
`plan_and_track.md` is the sole durable state record.
Load `agent-review/SKILL.md` for target quality, safety, decisions/contact, recovery,
snapshots/evidence/media/corpus and completion; never replace missing shared policy.
`agent-review/references/review.md` alone owns Review eligibility, submissions/results,
IDs, correction and effort rules. This skill owns lifecycle, revisions, tasks/todos,
batching and closure, not duplicated Review semantics.

## Locator and authority

- **X1** Resolve one exact state locator per objective: caller path or `.tmp/xdev/{objective-slug}/plan_and_track.md`. Slug normalization lowercases/trims, replaces non-alphanumeric runs with hyphens and trims hyphens; record path/objective. Create only an absent file, never overwrite an existing plan or silently create a second one.
- **X2** Resume reads the recorded locator before dispatch; missing/conflicting/ambiguous locators or another-objective default collision stop/escalate under shared policy. Bootstrap/migration/malformed-state recovery reads exact versioned templates and fails closed unless required fields migrate safely. If a template is unavailable, search matching existing plans before creation; ambiguity fails closed.
- **X3** Ordinary resume reads recorded schema, locator, task/todo/evidence/status fields without rereading template prose; creating/updating a sprint reads exact `xdev/templates/sprint_block.md`. The parent alone writes state/checkboxes, one writer per record/worktree. Workers propose changes and report evidence, never edit state.
- **X4** Transport/results/notifications inform reconciliation but cannot reconstruct semantic state. Repair from the record and authoritative reports/evidence; retain terminal references and replacement reasons, not volatile unchanged-resume/nudge counts.

## Revisions, tasks and todos

- **X5** Each durable semantic write increments State revision exactly once; apply all related scope/task/todo/candidate/binding changes atomically R to N=R+1. Create tasks/candidates/todos at N before dispatch. Runtime-ID, dispatch and running/pending transport updates are neutral unless scope, acceptance, integration or closure premise changes; formatting is neutral unless authority changes.
- **X6** Every authorized dispatch has a pre-dispatch ledger entry: logical task ID/generation, role/lane, exact scope, runtime transport ID, Status, supersession/replacement lineage, integration, authoritative terminal result/evidence and replacement reason. Logical ID/generation is identity; missing runtime receipts do not invalidate it.
- **X7** Replacements use new generations for unfinished scope. Planning and Review are distinct immutable lanes, each with at most one active generation; shared replacement rules apply. Historical entries retain original state, not current authority. Current unit scope, eligibility, integration and validation have one authoritative record referenced by resume fields.
- **X8** Todo IDs are stable and never reused. Unchecked means outstanding; check only after recorded reconciliation, integration, required evidence and discharge revision/reference. Never silently delete/reopen; replacement/follow-up IDs carry lineage. Todos reference ledger, contracts and evidence rather than duplicating them.
- **X9** Reconcile the complete todo list on resume, before dispatch, after results, before delivery assessment and before closure. Scoped implementation/correction/integration/required-validation todos are discharged before assessment; one designated Review-action todo stays open until a clear delivery result is integrated. Failed attempts/replacements retain generations; create correction todos for real blocking work, not another assessment attempt.
- **X10** Outcome is active/delivered/conclusively blocked; task/sprint Status is pending/running/completed/failed/blocked/cancelled/superseded. Local results never replace Outcome. Delivered requires contract/validation satisfaction; conclusively blocked is exact evidence-backed terminal non-delivery with no viable authorized remedy, satisfying no delivery criterion.
- **X11** Keep revision, phase, sprint, next owner/action, pending tasks, integration, validation, final assessment and Outcome explicit before dispatch/after integration. History retains semantic/recovery-significant baseline/assessment acceptance, completed/assessed sprints, revisions, blockers/replacements, final validation and settlement; routine diagnostics update their task/sprint, not vague Latest history.

## Evidence and continuation

- **X12** Baseline, sprint and final checks/scenarios record revision, snapshot, execution owner, expected/actual, PASS/FAIL/BLOCKED, command exit where applicable and material raw evidence. Summaries cannot replace inspection/reproduction evidence. Product snapshots follow shared policy; historical sprints retain bindings and final validation/assessment share one final snapshot.
- **X13** Review records additionally bind assessment revision/owner, covered units/sprints, canonical oracle-review-result and findings. Oracle dispatches use `ORACLE_ASSIGNMENT v2` plus the bound record their lane requires: Review adds `REVIEW_SUBMISSION v2`, Planning adds its decision basis, Input adds the dependency evidence, Closure adds its revision-bound candidate. Fixer dispatches use their bounded TARGET only. Never duplicate these schemas here.
- **X14** Before ending an active root turn, reread the exact plan and reconcile received results with the complete todo list; execute/dispatch ready authorized work unless terminal closure holds, the separate contact gate permits an asked necessary question with no other ready work, or no action is ready and a named non-superseded task/generation is confirmed live with automatic resume.
- **X15** User dependencies block only dependents. Status updates, child completion, remediable failure, context pressure, compaction and a future Next action are not terminal exits. Automatic CONTINUE may carry durably recorded work to another root turn, never abandonment/closure; live waits retain their wake path.

## Baseline, sprints and completion

Author a coherent baseline under shared target/corpus rules; Planning is conditional,
never a preimplementation Baseline Review. Carry goal statement/basis/status and initial
clarification/dependency/assessment/reply history so resume cannot reset intake.
Execute bounded sprint contracts with fewer, larger evidence-backed risk boundaries;
combine mechanical work sharing contract/validation, split for failure isolation,
ordering or materially different invariants, never arbitrary files/checklist items.

- **X16** Batch consecutive sprints sharing contract, invariants or validation into one delivery assessment; sprint completion alone is no assessment reason. Complete accepted scope and all known corrections first; split only for failure isolation, ordering or materially different invariants, not sprint boundaries. Name every covered sprint.
- **X17** A last/only sprint assessment serves final whole-state assessment when scope/evidence coincide; otherwise obtain whole-state assessment. Successful completion requires Outcome delivered, every approved final check and required validation complete, clear final independent delivery assessment, zero pending tasks, integrated non-superseded results and every non-closure todo satisfied.

## Parent-objective closure

Before proposing closure, the parent rereads the exact plan and reconciles baseline/criteria,
all sprints, task generations/supersession, integration, validation, findings, blockers,
recovery, remaining authorized actions and complete todo settlement.

- **X18** Routine active recovery needs no closure assessment. Delivered closure fully covered by the final sprint's exact whole-state scope/evidence and all completion invariants may use that clear result plus parent reconciliation without a separate assessment. Negative/blocked closure or any uncovered delivered premise requires a separate revision-bound Oracle assessment.
- **X19** Before dispatch at N, atomically record candidate ID/revision N, proposed Outcome, reconciliation/evidence and Oracle logical task/generation. Oracle reads the entire exact plan and authoritative references, including todos/lineage/discharge, ledger, criteria, validation and findings; missing, contradictory, stale or unreconciled evidence fails closed.
- **X20** Bind assessment to candidate ID/revision/proposed Outcome/task/generation and authoritative assessment reference. Conclusions are advisory: CONTINUE_REQUIRED retains active and identifies authorized work; USER_INPUT_REQUIRED retains active and identifies exact user dependency/question without contact permission; TERMINAL_PREMISE_SUPPORTED supports parent settlement only with matching binding and every applicable invariant.
- **X21** Atomic assessment integration records the bound task result, assessment, parent decision and designated assessment-todo settlement from N to N+1; this integration does not stale its binding. Only a substantive premise-changing event requires a new candidate/assessment. Malformed, missing, stale, unavailable or contradictory binding/evidence keeps Outcome active with no terminal claim.
- **X22** Delivered settlement satisfies every non-closure todo and completion invariant. Blocked settlement records the exact blocker/no viable authorized action; satisfied todos remain satisfied and each unfinished todo stays explicitly evidence-backed unmet/blocked with dependency and no-action basis, never falsely discharged.
- **X23** At delivered candidate N only the designated assessment todo may remain open; blocked candidates may also retain evidence-backed unmet/blocked todos. Settle the assessment todo atomically at N+1. Missing/stale/unreconciled todo state prevents assessment eligibility/closure; active Outcome permits no terminal user-facing claim.
- **X24** Awaiting_user is execution disposition, not Outcome. Closure USER_INPUT_REQUIRED does not permit contact; apply the separate input-assessment gate. One explicitly assigned Input task with dependency ID may supply both records; otherwise obtain the separate input record.

Closure returns one `oracle-closure-assessment` with:
candidateId, stateRevision, proposedOutcome, taskId, generation, evidenceRefs, conclusion,
rationale and nextActions. Echo assigned bindings; conclusion is exactly
CONTINUE_REQUIRED/USER_INPUT_REQUIRED/TERMINAL_PREMISE_SUPPORTED.
USER_INPUT_REQUIRED additionally carries dependency, whyAgentCannotResolve and one concise
question. Actions are proposed authorized work, not delegation/permission; Oracle never
changes state, asks the user, approves completion or emits lifecycle markers.
The parent records the authoritative assessment reference during integration.
