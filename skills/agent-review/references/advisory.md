## ORACLE_ASSIGNMENT v2

Every advisory dispatch supplies this typed core; arrays are required, empty when inapplicable.
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
- **A3** Parent interpretations may appear only as labelled non-authoritative historical evidence, never expected results or the choice set. Structural preflight cannot prove semantic neutrality; the assigned adviser tests these interpretations after its own source-first framing within the same call, not staged disclosure.

## Intelligence and actionable returns

Advisers inspect and recommend; report blockers or context pressure to the parent. Never
delegate, execute validation, edit state, ask the user, approve delivery or emit lifecycle
markers. Name the exact missing check and its owner. A diff is not snapshot identity;
disclose whose evidence you inspected, and never claim future or unverified results.

- **B1** The assigned adviser independently reconstructs the intended outcome from original instructions, criteria, sources and raw evidence before evaluating parent conclusions. Planning originates the bounded course it would choose, tests premise/decomposition necessity and considers simpler/no-change courses; do not merely expand a supplied design.
- **B2** For unresolved material decisions, derive decisive levers and materially distinct authorized courses with exclusion reasons, select one and test beyond the parent frame: what it omitted or why no further supported course survives. No quota or exhaustive-discovery claim; settled work needs basis and bounded action, not manufactured alternatives.
- **B3** Planning and Review judge necessity and warranted better approaches, including costs, risks, reversibility, causal mechanism and what would favor the submitted course. Keep criterion defects separate from acceptable-but-improvable author decisions; advice never relaxes criteria, satisfied criteria never silence advice, and neither expands scope or authorization.
- **B4** Actions are ordered and concrete: name files/edits or exact checks when evidence permits, with observable executable/scenario/static predicates and owners. Every action cites a real finding or decision; never “ask an adviser again”, vague categories or approval of future bytes.

**Pi-only exceptional Planning handoff.** Only `oracle` assigned Planning may return the
following single fenced record *instead of* a completed plan, when the strategic choice
remains unresolved after proportionate checks and choosing wrongly materially affects the
outcome. Give the decision, the consequence and what further reasoning could change. Bind
`assignmentRef` to the originating assignment's exact path/hash or verbatim inline identity
and basis. `cheapChecks` and `evidenceRefs` are nonempty arrays of results/references, or
for checks an evidence-backed explanation of why none can discriminate. Use exactly these fields:

```pi-planning-handoff
{"version":1,"outcome":"PLANNER_NEEDED","dependencyId":"<assigned subjectId>","assignmentRef":"<exact originating assignment>","decision":"<unresolved question and what further reasoning could settle>","consequence":"<cost of choosing wrongly>","cheapChecks":["<check and result or exclusion>"],"evidenceRefs":["<bound source>"]}
```

This is neither a selected plan nor an action to launch an agent. It cannot accompany any
other return or authorize implementation, contact, closure or delivery. Match the actual
role/lane and exact current assignment; reject stale, mixed, malformed or consumed handoffs.
Only the orchestrator dispatches. Record its linked Planner task and the raw result; a handoff
alone leaves Planning outstanding. Planner returns the ordinary plan or a concrete blocker,
never a second handoff. All other lanes and OpenCode retain their existing contracts.

Completed Planning returns a bounded target, original-outcome/non-goal alignment, premise judgment,
assumptions, acceptance/evidence, validation commands/owners/cadence and costly-check triggers,
the first working end-to-end slice, coherent implementation/review boundaries, material cases,
discovery and reconsideration triggers, plus exactly one `oracle-advisory-result`, no verdict.
Sequence a working intended path before optional polish/broad audits; required safety,
security, integrity and material acceptance remain part of implementation, not deferred advice.
Give actions sufficient for autonomous execution through the next coherent boundary,
not a plan that depends on routine intermediate consultations.

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
Actions use execute/discover/validate for Planning. In new Pi records use `owner: "parent"`:
only the orchestrator dispatches, normally to `worker` for a bounded action. Preserve the other
existing v2 owner token (OpenCode's bounded execution role name) in historical records;
on Pi it maps to `worker`, not a literal launch target. OpenCode may still emit either v2
owner. Ownership is proposed, not delegation or authorization. All arrays remain present; each action has nonempty instruction
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
