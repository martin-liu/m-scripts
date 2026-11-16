---
name: agent-review
description: Shared policy and Oracle contracts for independent Planning, decisions, input assessment and Review. Load before Oracle dispatch or bounded implementation.
license: MIT
metadata:
  author: martinliu
  version: "3.0.0"
---

# Agent protocol

This file owns shared policy, assignment and intelligence contracts.
`references/review.md` alone owns Review semantics.
`templates/reviewed_unit.md` carries ordinary Reviewed facts.
`xdev/SKILL.md` alone owns xdev lifecycle and closure.

Resolve `<skill>/<path>` through installed skill roots, or repository `skills/<skill>/<path>`;
bare `references/` and `templates/` resolve against this skill, never a record directory.
Never use `../` traversal. Parent, Oracle and Fixer load their exact bound policy before
dependent work; frontmatter is discovery only. Missing/unreadable policy stops dependent
work and is reported to the parent, never guessed or treated as grounds for user contact.
First Reviewed dispatch/every resume loads its template; any Review loads its reference;
xdev work/closure loads its skill. Reload lost policy on resume.

For a prompt or skill rewrite on **any route**, the parent first reads and applies
`agent-review/references/review.md` **Prompt preservation** (R18–R20), and supplies that procedure
and its bound evidence in assignments. This is a loading duty, not a Review requirement: ordinary
Direct work still needs no Review, and this creates no additional assessment call.

## Shared policy

- **P1** The parent alone owns effects, state, routing, delegation, integration, recovery, user contact, continuation and closure; workers return advice or evidence, never permission, lifecycle markers or state edits.
- **P2** Protected effects include identified staging/production actions, consequential external/shared mutations, privileged actions, deploy/publish, machine-wide changes and destructive local database operations unless affirmatively disposable development/test state; unknown or potentially valuable local databases remain protected.
- **P3** Ordinary repository work, local containers/processes, tests and local dependency installation are not protected merely for state or network use.
- **P4** Only the parent executes protected effects with sufficient explicit authorization covering the exact effect, target and limits; reuse a still-valid grant, never demand fresh confirmation merely on a later turn.
- **P5** Broad goals, routes, advice, assessment evidence and worker contracts grant no protected authorization; missing authorization blocks only that effect, not authorized inspection/preparation. Workers never execute or authorize protected effects. Prompt policy is not OS isolation; isolate untrusted work.
- **P6** A bounded target names output/behavior, authoritative basis, allowed scope/non-goals, criterion IDs and observable expectations, evidence, validation owner/commands/cadence, material cases and invariants; it creates no artifact or user-approval requirement. Planning follows I2, not target paperwork.
- **P7** Choose the smallest coherent evidence-backed solution, not smallest diff; preserve correctness, security, integrity, operational invariants and manageable lifetime maintenance. Inspect authoritative files and nearby patterns; reuse only when assumptions fit. For material choices — including ones the parent settles by default without consulting Oracle — compare causal mechanisms, coupling and reversibility, and stress-check the rationale under plausible evidence-supported changes in conditions. Add no abstraction, optimization, refactoring or hardening without requirements/evidence.
- **P8** Required deterministic behavior uses faithful input/output, boundary, error and regression checks; use faithful scenarios/integration evidence when tests do not suffice. Required checks pass; investigate every mismatch and never weaken authoritative expected results.
- **P9** Durable evidence is repository path plus content hash, immutable artifact/URL or inline material evidence; runtime IDs, notifications, temporary paths and task reports alone establish nothing.
- **P10** Bind validation and assessment to root/base and a commit/tree materializing all relevant bytes, or a deterministic manifest: sorted relevant tracked/staged/untracked paths, status, material modes, byte hashes, deletions, exclusions and manifest-lines hash. Include implementation, tests, fixtures and required validation inputs; reference output separately.
- **P11** Exclude mutable plans, runtime receipts, generated reports and the manifest itself from product identity. Product mutation stales whole-snapshot assessment, not every check automatically; bookkeeping-only edits stale neither. Reuse a check only when its complete relevant inputs, dependency/configuration/environment and freshness requirements are demonstrably unchanged; unknown applicability requires rerun. Preserve its original execution snapshot and evidence, record applicability to the current snapshot, and rerun affected checks. Historical records retain bindings; final validation and assessment share one final snapshot with every required check passing or supported by explicit unchanged-input applicability.
- **P12** Disclose inspection/execution owners, exact check inputs, commands, exits, expected/actual results and material raw evidence; never claim computations, inspection, modality access or verification not performed. Parent/Fixer execution is not Oracle computation; do not require personal hash computation unless independent execution was arranged.
- **P13** Artifact identity, access, modality capability and evidence owner are distinct. The parent inspects user attachments and materially relevant visual/spatial/temporal/audio content, including dependent final validation, before delegation; workers do not inherit attachments.
- **P14** Parent-recorded criterion-level media inspection can support Oracle assessment without direct attachment access; that lack alone is no blocker or extra-call reason. Explicit independent media verification requires exact access and capability; summaries cannot substitute. Exact filesystem work also requires direct path access, capability and assigned scope.
- **P15** With inaccessible media, Fixer proceeds only from independently sufficient textual/structured requirements and binds conclusions to them, or reports a blocker; contract-supported artifact-independent deterministic implementation remains allowed.
- **P16** Keep corpus claims separate: semantic item-level truth requires parent contextual reading of every claimed item before identical-scope automation; exact-rule transformation uses stated rules/invariants/reference fixtures; population claims require a defined population and independent sampling/estimation or exhaustive support.
- **P17** Samples support discovery or sample-scoped claims, never unprocessed items. Keep corpus scope/rules identical and investigate every mismatch without moving the baseline. Scripts, fixtures, presets, generated data, prior outputs and summaries are not corpus truth; Oracle/Fixer never establish, recreate or redefine it.
- **P18** A worker result or terminal operation does not close an objective. Integrate every non-superseded result and take the next authorized action after non-completing results; failed prerequisites block only dependents. Use reversible defaults and narrow diagnostics before costly unchanged retries.
- **P19** Negative/blocked conclusions requiring material semantic inference through retrieval, selection, materialization, filtering, ranking or counts require a separate Planning premise assessment, not contact permission; routine bounded blockers do not. Reconcile normal-path count-relevant stages and earliest losses over the configured bounded window; state what controls prove. Different-path controls do not prove normal outcomes; full-population tracing is required only for population-exhaustion claims.
- **P20** Stop unfinished work only for an authoritative non-recoverable blocker, unavailable boundary expansion/reroute or exhausted proportionate materially distinct recovery; ordinary Reviewed additionally permits Review-cap non-delivery under R16. xdev uses its progress/recovery and settlement rules, never a lifetime Review count as a stop reason. Neither route permits an impossibility claim, waiver of delivery requirements, route evasion or automatic contact.
- **P21** Inspect Reviewed/xdev background children only on completion or transport resume, never poll. Cancel active stale work before same-role/same-lane replacement; replace terminal failed/cancelled/unreachable work without cancellation, assigning only unfinished scope. Never revive superseded work, cross lanes, duplicate/drop scope or integrate late superseded output; recovery cannot lower route or bypass assessment.
- **P22** Wait only on confirmed-live started work with a verifiable child/provider event that automatically resumes; unstarted work is not a wait. Preserve integrated evidence and scheduled handoffs.
- **P23** Ordinary Reviewed tasks durably bind logical task ID plus generation before dispatch; runtime ID is transport metadata. Replacements use a new generation for unfinished scope. Status is pending/running/completed/failed/blocked/cancelled/superseded, not lifecycle outcome. Resume reads exact context, pending generations and all non-superseded results; material conflicts fail closed.
- **P24** Reviewed completion requires a clear final independent delivery assessment under `agent-review/references/review.md`, zero pending work, integrated non-superseded results and all required validation; xdev additionally satisfies its lifecycle. Worker evidence, advice and approval markers alone never complete work. Before those conditions hold, the parent must not describe the Reviewed/xdev outcome or current snapshot as done, complete or ready; report 'implemented, unassessed', 'assessment deficient' or the exact outstanding condition. Defined task/transport statuses and factual completed substeps are unchanged.

## Validation cadence

For Reviewed/xdev, the default sequence is: align the outcome → obtain/reuse substantive Oracle plan →
implement with targeted feedback → integrate a working end-to-end batch → run due final
checks → one whole-unit Review → one complete correction batch if needed. Repeat Review
only for corrected material deficiencies under R14–R15 and the route's recovery/effort rules:
R16 for ordinary Reviewed, xdev progress/recovery for xdev. Do not improve an already clear
result through more assessment or obtain advice on every local edit.

- **V1** Before implementation, assign checks to iteration, milestone or final validation in the existing target/record. For each name the criterion, exact command/scenario, inputs, owner, expected result, cost/duration estimate or observation, due point and rerun trigger; simple work may share one default. Iteration uses the cheapest faithful local check that answers the changed behavior; broad builds, image creation and long integration suites normally wait for an integrated milestone/final candidate, not every edit, Fixer dispatch or Review correction. A safety invariant, decisive uncertainty or dependent next action may require an early expensive check; record why cheaper evidence is insufficient. Never weaken required final checks or expected outputs to save time.
- **V2** Complete the coherent implementation/correction batch before checks due at its milestone. Do not duplicate a check across workers and parent; use P11 applicability. A not-yet-due check is deferred, not passed, waived or a blocker; record its owner/due point and keep required validation pending until supported. For potentially long commands, set an evidence-backed duration/progress bound and preserve completed output. If a command exceeds its expected duration or yields no useful progress, inspect bounded diagnostics and resource/progress evidence before safely cancelling, narrowing or retrying; extend the bound only for observed useful progress, and avoid unbounded waits and repeated unchanged costly commands. A timeout or narrower diagnostic is not a pass for the required check. Use the host's completion/wake mechanism for long running work, not child polling.

## Decisions and contact

- **I1** Use evidence-backed authorized reversible in-scope defaults for routine choices without menus, confirmation, “unless you object” or waiting for a pick; record material assumptions and reconsideration triggers. Substantive unsettled choices follow I2; only indispensable user-owned dependencies follow the contact gate.
- **I2** On Reviewed/xdev, obtain or reuse source-first Oracle Planning before dependent implementation when substantive goal interpretation, architecture, strategy, decomposition or validation design remains unsettled; Direct retains its bounded no-strategic-Planning route and reroutes if that boundary changes. Group related questions into one coherent plan with actions and reconsideration triggers; a valid existing Oracle plan suffices, but a parent-authored design/default alone does not settle substantive work. Parent preference, equivalent routine implementations, execution, targeted validation and actionable repair need no call. Reconsult only when material new evidence invalidates the selected course, a substantive decision remains unresolved or R15 requires a changed strategy not supplied by prior advice; accumulate nonblocking questions for the next coherent boundary, not every fix/snapshot.
- **I3** Technical, implementation, strategy, architecture and ordinary product/UI choices, including uncertainty and “is this in scope”, are agent-owned. Exactly three user-owned kinds exist: required protected authorization; indispensable user-only access/fact with no reasonable compliant substitute; genuinely incompatible product-intent readings changing the expected outcome, not valid implementation tradeoffs.
- **I4** Before any user question, check instructions/grants, obtainable evidence and authorized alternatives; obtain the actual fenced matching `USER_INPUT_REQUIRED` input record from a completed Oracle run witnessed starting in the current request epoch. Only this record permits asking, never execution or closure.
- **I5** For ordinary indispensable blockers, finish other feasible authorized work and permitted preparation first; deduplicate dependency/question and ask only when no authorized work remains ready. Initial outcome alignment follows I7 before dependent implementation, not after completing unrelated sprints. Targets, baselines, test plans, failed checks, unavailable assessment, uncertainty, disabled continuation and exhausted effort alone permit no contact.
- **I6** Before dependent implementation, record objective ID/goal revision, verbatim original basis, high-level goal/status, non-goals, observable acceptance, material assumptions, initial clarification use and dependency/assessment/reply references in existing state: conversation target for Direct, unit record for Reviewed, baseline for xdev. Briefly state the understood outcome and boundaries at intake; a clear goal proceeds without ratification or specified implementation. On resume and coherent milestones compare work and next actions to this outcome anchor. Technical plan changes do not replace it; outcome/acceptance changes require authoritative instruction or clarification, an explicit revision/basis and retained history, never silent drift, invented requirements or convenience-based narrowing.
- **I7** Initial goal clarification is one question in one user turn per objective, only for irreconcilable outcome readings after proportionate discovery and bounded intake preparation. Resolve indispensable high-level ambiguity at intake, before dependent implementation or long-running work; the I4 input assessment is still required. Use purpose goal-clarification and kind product-intent; never a menu/questionnaire or a choice among valid implementations. Resume, compaction, generations and assessment failures do not reset it; only a materially replaced objective does.
- **I8** Never reopen a clear goal. An inadequate/partial reply neither authorizes guessing nor repeats the unchanged question; use resolved facts and retain dependencies. Re-ask only through the ordinary indispensable-blocker gate with materially new grounds or a narrower item, never waiving required authorization/access/fact questions.
- **I9** Only the parent emits `USER_QUESTION: <exact question>` once, verbatim from the record, in its final message. Pi user BLOCKED binds the same oracle run and dependency; Oracle carries the question only in JSON. Contact permission is not permission to abandon other ready work.

## ORACLE_ASSIGNMENT v2

Every dispatch supplies this typed core; arrays are required, empty when inapplicable.
References contain readable exact material or durable path/hash identities, never summaries
as substitutes. `identity` records objective/goal revision, unit/dependency/candidate,
logical task/generation and route. `state` binds context path/hash, root/base, product
snapshot, integration, pending work and history. Lane-specific details are additional
bound records, not a second choice prompt.

```json
{
  "version": 2,
  "lane": "Planning",
  "identity": {
    "objectiveId": "<objective>", "goalRevision": 1, "subjectId": "<unit/dependency>",
    "taskId": "<logical task>", "generation": 1, "route": "Reviewed"
  },
  "policyRefs": ["<exact readable policy path + hash>"],
  "basis": {
    "originalInstructions": ["<verbatim request and later instructions>"],
    "intendedOutcome": "<requested outcome>",
    "userConstraints": [], "authorizations": [],
    "sources": ["<authoritative readable source + hash>"],
    "observations": [], "contraryEvidence": [], "gaps": [],
    "openQuestions": [], "priorChoices": []
  },
  "state": {
    "contextRef": "<exact path + hash or inline Direct context>",
    "root": "<root>", "base": "<base>", "snapshotRef": "<identity or N/A>",
    "integration": "<current facts>", "pendingWork": [], "historyRefs": []
  },
  "request": {"kind": "originate"}
}
```

The core has exactly these keys and nested fields. Lane is Planning, Input, Review or
Closure. Request has only `kind`: Planning=originate; Input=assess-ownership;
Review=assess-current; Closure=assess-candidate. Identity numbers are positive integers.
Input additionally binds dependency ID/purpose, missing item, discovery tried, grants,
tried alternatives and why assumptions are inadequate. Review adds its canonical submission;
Closure adds its revision-bound candidate. Bounded Direct advice needs no durable unit record.

- **A1** Parent preflight checks the typed core, lane/request agreement, required readable bindings and internal consistency before dispatch; no requested answer, verdict, approval, preferred solution, shortlist or leaning is an input field.
- **A2** Supply original instructions, outcome, user constraints, raw evidence and open assumptions without a preferred solution or shortlist; state material undecided questions. Historical choices/artifacts are evidence, not constraints. Do not omit user-required designs, self-audit, prior findings, contrary evidence or material facts to simulate neutrality.
- **A3** Parent interpretations may appear only as labelled non-authoritative historical evidence, never expected results or the choice set. Structural preflight cannot prove semantic neutrality; Oracle tests these interpretations after its own source-first framing within the same call, not staged disclosure.

## Intelligence and actionable returns

- **B1** Oracle independently reconstructs the intended outcome from original instructions, criteria, sources and raw evidence before evaluating parent conclusions. Planning originates the bounded course it would choose, tests premise/decomposition necessity and considers simpler/no-change courses; do not merely expand a supplied design.
- **B2** For unresolved material decisions, derive decisive levers and materially distinct authorized courses with exclusion reasons, select one and test beyond the parent frame: what it omitted or why no further supported course survives. No quota or exhaustive-discovery claim; settled work needs basis and bounded action, not manufactured alternatives.
- **B3** Planning and Review judge necessity and warranted better approaches, including costs, risks, reversibility, causal mechanism and what would favor the submitted course. Keep criterion defects separate from acceptable-but-improvable author decisions; advice never relaxes criteria, satisfied criteria never silence advice, and neither expands scope or authorization.
- **B4** Actions are ordered and concrete: name files/edits or exact checks when evidence permits, with observable executable/scenario/static predicates and owners. Every action cites a real finding or decision; never “ask Oracle again”, vague categories or approval of future bytes.

Planning returns a bounded target, original-outcome/non-goal alignment, premise judgment,
assumptions, acceptance/evidence, validation commands/owners/cadence and costly-check triggers,
the first working end-to-end slice, coherent implementation/review boundaries, material cases,
discovery and reconsideration triggers, plus exactly one `oracle-advisory-result`, no verdict.
Sequence a working intended path before optional polish/broad audits; required safety,
security, integrity and material acceptance remain part of implementation, not deferred advice.
Give actions sufficient for autonomous execution through the next coherent boundary,
not a plan that depends on routine intermediate Oracle consultations.

```json
{
  "version": 2, "dependencyId": "<assigned subjectId>",
  "authorDecisionItems": [{
    "id": "D1", "owner": "parent", "state": "unresolved",
    "decision": "<outcome interpretation and premise judgment>",
    "selectedOption": "<selected authorized course>",
    "rationale": {
      "levers": ["<objective/evidence lever>"],
      "courses": [{"course": "<independently derived course>", "disposition": "selected", "basis": "<why>"}],
      "frameCheck": "<what the parent frame omits, or why no further supported course survives>",
      "selectionBasis": "<why this course best satisfies the objective>"
    },
    "assumptions": [], "reconsiderationTrigger": "<material change>", "evidenceRefs": []
  }],
  "nextActions": [{
    "kind": "execute", "owner": "parent", "instruction": "<bounded action>",
    "acceptancePredicate": "<observable result>", "findingIds": [], "decisionIds": ["D1"]
  }]
}
```

Decision fields are exactly shown; owner is parent. State unresolved uses the structured
rationale above, nonempty levers/courses/frameCheck/selectionBasis, exactly one selected
course and rejected courses with bases where supported. State settled instead uses
`rationale: {"basis": "<settled evidence>", "boundedAction": "<action>"}`.
Every rationale and selectedOption is substantive; “None” without basis is invalid.
Actions use execute/discover/validate for Planning; owner parent/fixer is proposed, not
delegation or authorization. All arrays remain present; each action has nonempty instruction
and predicate and resolves every cited ID, including at least one decision. No nested
brief, stage, quality scoreboard or verdict. Review reuses these decisions/actions under
its own legality rules; Input and Closure do not inherit this envelope.

## Input assessment

Return exactly one `oracle-input-assessment` and no question outside it.
Outcome AGENT_DECISION includes selectedOption/rationale/assumptions/reconsiderationTrigger
and no user-only fields. Outcome USER_INPUT_REQUIRED includes kind/dependency/question/
whyAgentCannotResolve and no agent-only fields. Kind authorization/access/fact/product-intent
represents the three ownership classes; access and fact share one class.

```json
{
  "version": 1, "dependencyId": "<assigned ID>", "outcome": "USER_INPUT_REQUIRED",
  "kind": "authorization", "dependency": "<exact required missing grant>",
  "question": "<one necessary concise question>",
  "whyAgentCannotResolve": "<why no authorized alternative or compliant substitute suffices>"
}
```

A goal-clarification assessment decides only indispensable outcome ambiguity, never a
menu or choice among valid implementations. The record grants no authorization, route,
continuation, delivery or closure decision.
