---
name: xdev
description: Full software-lifecycle route for complex multi-sprint work requiring durable coordination across phases, risk boundaries, or context limits. Use Direct or Reviewed for bounded work.
license: MIT
metadata:
  author: martinliu
  version: "2.0.0"
---

# xdev

Durable coordination for multi-day work: an original-outcome anchor, coherent end-to-end
batches, cost-aware validation and evidence-backed progress/recovery.
`plan_and_track.md` is the sole durable state record. Autonomy means continued authorized
progress within the agreed outcome, not unlimited unchanged validation or fix/Review loops.
Load `agent-review/references/execution.md` and `agent-review/references/coordination.md` for target quality, safety, decisions/contact, recovery,
snapshots/evidence/media/corpus and completion; never replace missing shared policy.
`agent-review/references/review.md` alone owns Review eligibility, submissions/results,
IDs, correction and effort rules. This skill owns lifecycle, revisions, tasks/todos,
batching and closure, not duplicated Review semantics.

Apply P7's first-principles thinking throughout xdev: choose the simplest sufficient course from
the original outcome, evidence and binding constraints. On resume and recovery, revisit changed
assumptions and reuse still-supported plans under I2.

## Locator and authority

- **X1** Resolve one exact state locator per objective: caller path or `.tmp/xdev/{objective-slug}/plan_and_track.md`. Record path/objective; create only an absent file, never overwrite an existing plan or silently create a second one.
- **X2** Resume reads the recorded locator before dispatch; missing/conflicting/ambiguous locators or another-objective default collision stop/escalate under shared policy. For bootstrap, migration or malformed-state recovery, read `xdev/templates/plan_and_track.md` and applicable versioned templates. If unavailable, search matching existing plans before creation; ambiguity or unsafe migration fails closed. Preserve IDs, revisions, goal/clarification history, validation, findings and complete Review history; never invent authority or reset history.
- **X3** Ordinary resume reads the live plan, not template prose: check schema/locator, original outcome, task generations/status and integration, complete todos, prior findings, evidence and next due check. Read `xdev/templates/sprint_block.md` when creating or updating a sprint. The parent alone writes state/checkboxes, one writer per record/worktree. Workers propose changes and report evidence, never edit state.
- **X4** Transport/results/notifications inform reconciliation but cannot reconstruct semantic state. Repair from the record and authoritative reports/evidence; retain terminal references and replacement reasons, not volatile unchanged-resume/nudge counts.

Keep the canonical plan safe for its intended readers: record operative constraints, grants and non-sensitive identifiers; bind restricted source values by permitted reference, not by copying them into the plan, logs or assignments. A PR-only disclosure ban does not itself bar a permitted internal reload. Recover unclear restrictions from permitted sources before opening or searching for an old plan. If raw tool output is forbidden, never open the old plan through that tool. An already-authorized view of the same exact revision may supply the full reconciliation state (including every applicable fact in X3/X9/X19); a summary, a second plan or an unreadable pointer cannot. If no compliant view exists, leave dependent integration pending and continue independent authorized work.

## Revisions, tasks and todos

- **X5** Each durable semantic write increments State revision exactly once; apply all related scope/task/todo/candidate/binding changes atomically R to N=R+1. Create tasks/candidates/todos at N before dispatch. Runtime-ID, dispatch and running/pending transport updates are neutral unless scope, acceptance, integration or closure premise changes; formatting is neutral unless authority changes.
- **X6** Every authorized dispatch has a pre-dispatch ledger entry with logical task ID/generation, role/lane, exact scope, pending status and applicable supersession lineage/replacement reason. Attach the runtime transport ID when the launch receipt arrives; record status, integration and authoritative terminal result/evidence as observed. Logical ID/generation is identity; a missing receipt proves neither that launch failed nor that a writer stopped (P21).
- **X7** Replacements use new generations for unfinished scope. Planning and Review are distinct immutable lanes, each with at most one active generation; shared replacement rules apply. Historical entries retain original state, not current authority. Current unit scope, eligibility, integration and validation have one authoritative record referenced by resume fields.
- **X8** Todo IDs are stable and never reused. Unchecked means outstanding; check only after recorded reconciliation, integration, required evidence and discharge revision/reference. Never silently delete/reopen; replacement/follow-up IDs carry lineage. Todos reference ledger, contracts and evidence rather than duplicating them.
- **X9** Reconcile the complete todo list on resume, before dispatch, after results, before delivery assessment and before closure. Scoped implementation/correction/integration/required-validation todos are discharged before assessment; one designated Review-action todo stays open until a clear delivery result is integrated. Failed attempts/replacements retain generations; create correction todos for real blocking work, not another assessment attempt.
- **X10** Outcome is active/delivered/conclusively blocked/unsuccessful; task/sprint Status is pending/running/completed/failed/blocked/cancelled/superseded. Local results never replace Outcome. Delivered requires contract/validation satisfaction; conclusively blocked is exact evidence-backed terminal non-delivery with no viable authorized remedy. Unsuccessful records genuinely exhausted proportionate materially distinct authorized recovery under X18/X22, not a lifetime Review count, elapsed days, technical impossibility or lack of authorization; neither negative Outcome satisfies any delivery criterion.
- **X11** Keep revision, phase, sprint, next owner/action, pending tasks, integration, validation, final assessment and Outcome explicit before dispatch/after integration. History retains semantic/recovery-significant baseline/assessment acceptance, completed/assessed sprints, revisions, blockers/replacements, final validation and settlement; routine diagnostics update their task/sprint, not vague Latest history.

## Evidence and continuation

- **X12** Baseline, sprint and final checks/scenarios record revision, snapshot, execution owner, expected/actual, PASS/FAIL/BLOCKED, command exit where applicable and material raw evidence. Carry V1–V2 cadence, due/deferred checks and P11 unchanged-input applicability in the existing validation strategy/evidence; deferred checks have no PASS. Summaries cannot replace inspection/reproduction evidence. Product snapshots follow shared policy; historical sprints retain execution bindings and final validation/assessment share one final snapshot with explicit reuse applicability.
- **X13** Review records additionally bind assessment revision/owner, covered units/sprints, canonical oracle-review-result and findings. Advisory dispatches use `ORACLE_ASSIGNMENT v2` plus the bound record their lane requires: Review adds `REVIEW_SUBMISSION v2`, Planning adds its decision basis, Input adds the dependency evidence, Closure adds its revision-bound candidate. Worker dispatches use their bounded TARGET only. Store the exact assignment and linked result/next task in the ledger; a Planning handoff is not a selected course. Never duplicate these schemas here.
- **X14** Before ending an active root turn, reread the exact plan and reconcile received results with the complete todo list and original-outcome anchor; execute/dispatch ready authorized work unless terminal closure holds, the separate contact gate permits an asked necessary question under I5–I7, or no action is ready and a named non-superseded task/generation is confirmed live with automatic resume. A completed turn, sprint or readiness report does not establish delivered Outcome; unfinished required work or its unresolved dependencies rule out DONE.
- **X15** User dependencies block only dependents. Status updates, child completion, remediable failure, context pressure, compaction and a future Next action are not terminal exits. A live host may automatically continue durably recorded work; a saved Next action is not a wake. After a cold restart reconcile the exact plan, receipts, current liveness and non-superseded results on the next supplied turn. Do not replay a dispatch or effect merely because its receipt is missing. Neither interruption nor a reconciliation nudge is abandonment, closure or proof of a stopped writer.

## Baseline, sprints and completion

At intake record the I6–I7 outcome anchor in the baseline, separate from agent design. Resolve
indispensable ambiguity before dependent work; a clear goal needs no user ratification. Use I2
Planning, not a preimplementation Baseline Review. Compare resume, sprint and correction work to that anchor.

For a local development objective, default to one final whole-state Review against local acceptance,
not production readiness. Use focused Worker checks between sprints; bring a distinct material risk
forward only when later work depends on resolving it. Group related findings into one repair batch.
For a readiness objective, include the named decision's criteria at final validation and Review. A requested promotion adds newly due checks and authority checks for the actual next effect; retain history and reuse only applicable bound evidence (P10–P11). For both targets keep safety, security and integrity in the first working slice and later checks pending with their owner. If a report itself needs xdev, its final unit is the report and its evidence, not delivery of the product it assesses. Apply X17 to that unit. A supported negative conclusion neither requires subject repairs nor discharges a separate product objective.

- **X16** Batch consecutive sprints sharing contract, invariants or validation into one delivery assessment; sprint completion alone is no assessment reason. Complete accepted scope and all known required corrections first; split only for failure isolation, ordering or materially different invariants, not sprint boundaries. Name every covered sprint and stable delivery outcome; preserve dispatch/finding history across regrouping, replacement and resume. xdev has no hard lifetime delivery-Review cap; R16's ordinary Reviewed allowance does not apply. Continue while meaningful in-scope progress or viable materially distinct authorized recovery remains. At coherent milestones/correction boundaries record criterion or defect-class improvement, decisive new evidence or a supported next recovery action against the original-outcome anchor in existing sprint/Review/history fields. Cosmetic edits, renamed findings, new snapshots, repeated commands and narrowed goals are not progress. After deficiencies apply one whole correction batch and R15 stabilization. A failed causal correction or recurring class requires root-cause analysis and a materially changed repair/validation mechanism, not an unchanged retry. Obtain or reuse grouped recovery Planning under I2 when that substantive strategy remains unsettled; then execute through the next coherent boundary without per-edit consultations. No fresh Review of a usable assessment without required new correction/evidence; optional advice creates no mandatory cycle. A confirmed-terminal generation with no usable result may be replaced under X7 on the unchanged eligible candidate; retain history, not a duplicate judgment.
- **X17** A last/only sprint assessment serves final whole-state assessment when scope/evidence coincide; otherwise obtain whole-state assessment. Successful completion requires Outcome delivered, every approved final check and required validation complete, clear final independent delivery assessment, zero pending tasks, integrated non-superseded results and every non-closure todo satisfied.

## Parent-objective closure

Before proposing closure, the parent rereads the exact plan and reconciles baseline/criteria,
all sprints, task generations/supersession, integration, validation, findings, blockers,
recovery, remaining authorized actions and complete todo settlement.

- **X18** Routine active recovery needs no closure assessment. Delivered closure fully covered by the final sprint's exact whole-state scope/evidence and all completion invariants may use that clear result plus parent reconciliation without a separate assessment. Negative/blocked/unsuccessful closure or any uncovered delivered premise requires a separate revision-bound Oracle assessment. Before proposing unsuccessful settlement, record supported proportionate materially distinct recovery courses, their attempted results or evidence-backed exclusions and why no viable authorized recovery remains; preserve unresolved findings/validation/unmet todos and finish other ready authorized work. Review count, elapsed days, context pressure or an unchanged failed attempt do not establish exhaustion. Closure tests the recovery/settlement premise and remaining work, not delivery approval: identify viable materially distinct recovery or missing premise evidence as CONTINUE_REQUIRED. It cannot prescribe unchanged repetition, waive independent delivery assessment or infer technical impossibility.
- **X19** Before dispatch at N, atomically record candidate ID/revision N, proposed Outcome, reconciliation/evidence and Oracle logical task/generation. Oracle reads the entire exact plan under the permitted reload rule and authorized evidence references, including todos/lineage/discharge, ledger, criteria, validation and findings; missing, contradictory, stale or unreconciled evidence fails closed.
- **X20** Bind assessment to candidate ID/revision/proposed Outcome/task/generation and authoritative assessment reference. Conclusions are advisory: CONTINUE_REQUIRED retains active and identifies concrete ready authorized progress/recovery or missing settlement evidence, even after many Reviews; USER_INPUT_REQUIRED retains active and identifies exact user dependency/question without contact permission; TERMINAL_PREMISE_SUPPORTED supports parent settlement only with matching binding and every applicable invariant.
- **X21** Atomic assessment integration records the bound task result, assessment, parent decision and designated assessment-todo settlement from N to N+1; on resume, match the current candidate/revision/task/generation and do not integrate an already settled result twice; this integration does not stale its binding. Only a substantive premise-changing event requires a new candidate/assessment. Malformed, missing, stale, unavailable or contradictory binding/evidence keeps Outcome active with no terminal claim.
- **X22** Delivered settlement satisfies every non-closure todo and completion invariant. Blocked settlement records the exact blocker/no viable authorized action. Unsuccessful settlement records genuinely exhausted proportionate materially distinct authorized recovery, attempted results/evidence-backed exclusions, unresolved criteria/findings and why no viable next recovery remains; a lifetime Review count alone never supports it. It grants no waiver, contact or impossible-outcome claim. In either negative settlement satisfied todos remain satisfied and each unfinished todo stays explicitly evidence-backed unmet/blocked with dependency and no-action or exhausted-recovery basis, never falsely discharged.
- **X23** At delivered candidate N only the designated assessment todo may remain open; blocked/unsuccessful candidates may also retain evidence-backed unmet/blocked todos. Settle the assessment todo atomically at N+1. Missing/stale/unreconciled todo state prevents assessment eligibility/closure; active Outcome permits no terminal user-facing claim. Unsuccessful settlement reports unsuccessful non-delivery (Pi STATUS:FAILED), never DONE or an automatic user question.
- **X24** Awaiting_user is execution disposition, not Outcome. Closure USER_INPUT_REQUIRED does not permit contact. Apply the separate input-assessment gate: reuse a matching current-request Input result when I4 permits, otherwise assign the Input lane. Each task returns only its own lane's record.

Closure returns one `oracle-closure-assessment` with:
candidateId, stateRevision, proposedOutcome, taskId, generation, evidenceRefs, conclusion,
rationale and nextActions. Echo assigned bindings; conclusion is exactly
CONTINUE_REQUIRED/USER_INPUT_REQUIRED/TERMINAL_PREMISE_SUPPORTED.
USER_INPUT_REQUIRED additionally carries dependency, whyAgentCannotResolve and one concise
question. Actions are proposed authorized work, not delegation/permission; Oracle never
changes state, asks the user, approves completion or emits lifecycle markers.
The parent records the authoritative assessment reference during integration.
