# Review reference

Review modes, entry conditions, the assignment template, the result schema, and the anti-loop rules;
loaded from `SKILL.md`. A Review is a delivery gate, never an intermediate micro-gate.

## Modes and entry conditions

| Mode | Admissible when | Not a substitute for |
|---|---|---|
| `DELIVERY` | `REVIEW_READY` (below), pre-Review validation passing, no pending delivery-blocking correction, reconciled state, xdev todo reconciliation with its Review-action todo open. | — |
| `STATIC/DESIGN` | Identified sources or design scope, authoritative criteria, reviewer evidence; completed implementation **not** required. | Delivery Review; a PASS here never approves delivery. |
| `BLOCKED_REVIEW` | Feasible checks run, blocked checks evidenced, no viable authorized in-scope remedy. | Readiness, approval, or relaxation of xdev closure; returns only `Verdict: FAIL`. |

`REVIEW_READY` means ready for delivery Review, not approved. Its criterion-level content is the
**criterion self-audit**: per material criterion a reference to passing applicable execution
evidence, or to static or scenario evidence where the criterion cannot honestly reduce to a command,
plus a reconciled disposition per prior finding. It is a parent check, not an artifact.

- An incomplete unit or failed check returns to authorized repair, discovery, or decision advice,
  not user contact. Decision advice cannot waive acceptance, required validation, snapshot identity,
  or final independent Review. Readiness defects block Review only while material acceptance,
  snapshot, integration, pending-work, or required-validation claims stay indeterminate; cosmetic
  record defects are observations once authoritative evidence fixes the material facts.
- Oracle reads authoritative changed files and validation evidence directly, names the exact shell
  checks the parent must run rather than running missing validation, and discloses evidence
  ownership: parent and Fixer checks are execution evidence, not Oracle computations.
- Durable evidence is a repository path plus content hash, an immutable artifact or URL, or inline
  material evidence; runtime IDs, notifications, temporary paths, and task reports alone are
  volatile and establish nothing. Missing required parent-owned evidence, or required independent
  media verification the reviewer cannot perform, is a precondition failure.
- Never dispatch `BLOCKED_REVIEW` to find a remedy or spend a capped slot early.

## Parent dispatch discipline

Parent-owned and stated in the orchestrator contract: Review covers a complete coherent unit, never
an isolated file, finding, or task generation, so finish the accepted scope **and** the existing
corrections batch and integrate results first; the full evidence set is supplied; PASS is never
requested or preferred; the filled assignment is validated before dispatch, because an invalid one
spends no slot, and reusing unit identity or dispatch history neither resets the count nor
establishes readiness.

## REVIEW_ASSIGNMENT v1 — required input

Fill every field; arrays may reference durable records instead of duplicating evidence bodies, but
Oracle must be able to read what is referenced.

```text
REVIEW_ASSIGNMENT v1
Mode: DELIVERY | STATIC/DESIGN | BLOCKED_REVIEW
Review contract: <accessible path + hash>
Objective ID / goal revision: <stable identity>
Unit ID / complete accepted outcome: <identity and end-to-end boundary>
Review dispatch ordinal / prior dispatches: <history references>
Review ID: <exact identity string, echoed verbatim in the result>
Route: <route>
xdev state path / revision / covered sprint and todo IDs: <values or N/A>

SNAPSHOT BINDING <root/base; commit/tree or manifest + hash; Snapshot ID; paths, status, modes,
byte hashes, deletions, exclusions; product inputs and integration context; change since the last
Review; output evidence separate.>
ORIGINAL INSTRUCTIONS <task verbatim; later constraints and exact authorizations; references only
where Oracle can read their exact contents.>
CONTRACT AND CRITERIA <contract + hash; criterion IDs with observable expected outcomes,
authoritative basis, invariants, allowed scope, exclusions, required validation and owner.>
OBSERVATIONS AND RAW EVIDENCE <observation | source/owner | exact reference | coverage limits;
check commands, inputs, exit status, expected vs actual, raw output.>
CONTRARY EVIDENCE AND KNOWN GAPS <fact or gap | source | affected criterion | consequence; access
and modality limits; parent-owned media or corpus evidence.>
PARENT INTERPRETATIONS — NOT AUTHORITATIVE EXPECTED RESULTS <labeled, with supporting and contrary
references, or none; no requested verdict, approval framing, or preference.>
RECONCILED STATE <per-criterion acceptance claims with evidence and owner; integration and
nonsuperseded results; pending work; defects; validation applicability; readiness gate and
evidence. DELIVERY: REVIEW_READY. STATIC/DESIGN: sources, criteria, assessment evidence.
BLOCKED_REVIEW: feasible checks, blocked-check evidence, exhausted remedies.>
COMPLETE PRIOR-FINDINGS BATCH <every prior raw Review result; per finding ID its requirement,
required action, parent disposition (corrected | rebutted | superseded | outstanding), evidence,
affected paths and checks, supersession mapping; after a second whole-unit FAIL, the changed
strategy and evidence, with intended-path and disabled-feature controls.>
REQUEST Assess this exact current unit independently against the authoritative criteria; return
the mandated result with all material findings as one batch. Do not approve future corrections or
treat summaries as inspected evidence.
```

## Mandated Oracle result

Return one `Verdict: PASS` or `Verdict: FAIL` line plus exactly one `oracle-review-result` JSON
block whose `verdict` matches it. `a | b` marks **allowed alternatives**, not text to emit.

```json
{"version": 1, "mode": "DELIVERY", "reviewId": "<id>", "unitId": "<unit id>",
 "snapshotId": "<snapshot id>", "verdict": "FAIL", "reasonCodes": [],
 "preconditions": {"status": "MET", "evidenceRefs": []},
 "criteria": [{"id": "<criterion ID>", "status": "satisfied | not-satisfied | not-assessed",
               "evidenceRefs": [], "findingIds": []}],
 "findings": [{"id": "<unitId>-F001", "blocking": true, "criterionIds": [],
   "locations": [{"path": "<path>", "lineStart": 1, "lineEnd": 1}],
   "defect": "<current-state failure>",
   "evidenceRefs": ["<reproduction: command, scenario, or static proof; expected vs observed>"],
   "requiredAction": {"instruction": "<bounded remediation outcome>",
     "acceptancePredicate": "<observable condition resolving the defect>"}}],
 "priorFindingResolutions": [{"id": "<prior id>",
   "status": "resolved | unresolved | withdrawn | superseded", "evidenceRefs": []}],
 "coverage": {"inspectedRefs": [], "executionOwners": [], "limitations": []},
 "residualRisks": [],
 "orchestratorBrief": {"stage": "DELIVERY",
   "judgment": {"qualityLevel": "DEFICIENT", "authorDecisionItems": []},
   "nextActions": [{"kind": "remedy", "owner": "parent",
     "instruction": "<bounded next action covering one coherent findings batch>",
     "acceptancePredicate": "<observable resolution condition>",
     "findingIds": [], "decisionIds": []}]}}
```

### `orchestratorBrief` — the orchestrator-facing instruction

Mandatory in every Review result; it removes and relaxes no field, enum, binding, finding, or verdict
invariant.

Planning returns no Review verdict. It adds one `oracle-advisory-result` block (`version`,
`dependencyId`, and an `ADVISORY` brief with `NOT_ASSESSED` quality) beside its decision explanation,
and neither supplements nor relaxes the input-assessment or xdev closure contracts.
An `acceptancePredicate` is an executable check, a faithful scenario, or a static proof; commands
name bound inputs, expected result, and owner, and architectural or product-level judgment gets no
invented one.

### Field types, alternatives, and binding agreement

`version` is `1`; `mode` equals the assignment `Mode`; `verdict` is exactly `PASS` or `FAIL` and must
equal the textual verdict line; every enum
takes exactly one alternative shown, else contract-invalid. `reviewId`, `unitId`, and `snapshotId`
reproduce the assignment `Review ID`, `Unit ID`, and `Snapshot ID` verbatim; an xdev unit also
carries `stateRevision`, its assigned revision verbatim, because product bytes cannot show state
change. `preconditions.status` is `MET` or unmet, unmet must be represented as
`REVIEW_PRECONDITION_NOT_MET`, and that forces `FAIL`. `reasonCodes`, `criteria`, `findings`,
`priorFindingResolutions`, and `residualRisks` are arrays, empty rather than omitted; `locations`
holds integer `lineStart`/`lineEnd`. `requiredAction.type` (`implementation`, `validation`,
`evidence`, `decision`) is permitted, not mandatory. Unmet-precondition, `STATIC/DESIGN`, and xdev
results use one shape: only the applicable fields are populated, non-applicable ones stay empty,
and nothing is fabricated.

`orchestratorBrief` is always present with its three properties `stage`, `judgment`
(`qualityLevel`, `authorDecisionItems`), and `nextActions`. `stage` is `ADVISORY | QUALITY | DELIVERY`;
`STATIC/DESIGN` maps to `QUALITY`, `DELIVERY` and `BLOCKED_REVIEW` to `DELIVERY`. `qualityLevel` is
`ACCEPTABLE | DEFICIENT | NOT_ASSESSED`:
PASS gives `ACCEPTABLE`, FAIL `DEFICIENT`, unmet material preconditions `NOT_ASSESSED` while retaining
mandatory FAIL and `REVIEW_PRECONDITION_NOT_MET`, and Planning `NOT_ASSESSED`. `authorDecisionItems`
separates a justified author-owned contract or strategy decision — `id`, `owner`, `decision`,
`selectedOption`, `rationale`, `assumptions`, `reconsiderationTrigger`, `evidenceRefs` — from a defect
in the submitted sources; they are recommendations, not acceptance criteria, and a user-owned
dependency still needs the unchanged input-assessment protocol.
`nextActions` is ordered, nonempty on Review FAIL, and empty only when no advice applies; each entry
has `kind`, `owner` (`parent | fixer`, a proposed owner, not delegation or authorization),
`instruction`, `acceptancePredicate`, `findingIds`, `decisionIds`, referencing real entries rather
than an invented anonymous blocker.

Kinds are stage-gated: ADVISORY takes `execute | discover | validate`, QUALITY takes
`remedy | validate | discover`, DELIVERY PASS takes `reconcile`, and **DELIVERY FAIL takes `remedy`
only**. A delivery remedy may cover implementation, validation, evidence repair, or decision
settlement, but names a bounded outcome and acceptance predicate; it never says "rebuild and come
back" or "ask Oracle again", and never approves future corrected bytes. Per-finding `requiredAction`
stays authoritative — the brief groups and orders those actions and cannot make a preferred
implementation mandatory where an equivalent remedy satisfies the finding. An empty `instruction` or
`acceptancePredicate`, a stage-illegal `kind`, a missing brief, or an entry referencing no real finding
or decision is contract-invalid exactly as a malformed pre-existing field is; adding a brief never
repairs a malformed result.

### Result invariants

PASS requires met preconditions, satisfied material criteria, and no blocking finding. Every
blocking issue, including missing material evidence, has a finding ID and a required action, never
an anonymous blocker outside the batch, and every prior finding gets a resolution entry. Required
actions specify the **observable condition that resolves the defect**, never "improve", "be more
careful", or "ask Oracle again". Evidence may be a direct static proof, and Oracle must not run
forbidden validation to manufacture a command result: do not raise a finding unsupported by the
submitted standard.

### Deterministic IDs

Each finding gets a stable `<unitId>-F001`, `F002`, … Reuse the prior ID for the same root cause
after line movement; never renumber, reuse, or reset IDs after snapshot or generation changes, and
allocate new IDs after the highest historical suffix. Semantic equivalence still needs judgment; a
hash of changing prose does not decide it. No generation, rename, or snapshot change resets unit
identity, finding IDs, or the clarification allowance.

## Correction after FAIL

The orchestrator contract owns the correction workflow: one whole-unit batch, compatible corrections
batched, affected checks rerun, unchanged-input evidence preserved, and a materially changed pass
over root causes, equivalent affected paths, correction-induced defects, and test adequacy after a
second whole-unit FAIL, with implicated regression behaviour shown to execute the intended path and
fail with the guard or feature disabled, and prior state or retries isolated so they cannot mask
that control. Oracle's part: a recurring finding states **why the earlier
correction failed** and how the new repair differs, and the stable finding ID carries that history.

## Effort limit

Ordinary Reviewed units have at most three unit-associated Review dispatches, counting replacements,
precondition failures, and `BLOCKED_REVIEW`. Expenditure is decided **before the call starts** and is
never inferred afterwards from Oracle's findings: a call the parent rejects during preflight spends no
slot, and **every started call spends one, including a malformed assignment and a
precondition-failed call**. Because malformed-ness is only discoverable by parsing, preflight is the
parent's structural and internal-consistency check — required fields, bound evidence, identity,
history, pending work — not a promise of semantic admissibility. Generation, snapshot, or rename
cannot reset the count, and the third dispatch still requires `REVIEW_READY` plus any second-FAIL
stabilization. Exhaustion, non-delivery, and xdev batching belong to the parent contract.

## Anti-loop rules

Report the complete submitted unit in the first Review, not likely problems only, and re-review the
whole batch; never freeze re-review to old findings only, which hides genuine defects. Every new
finding must demonstrate a defect in this snapshot or its bound evidence, so the restriction is
against findings unsupported by the reviewed state, never against newly discovered material
findings: never fail for hypothetical future change, a stale defect absent from the current state,
unrelated scope, or an unstated preference, and report a previously overlooked current defect with
its evidence and the earlier coverage gap. Defect classification (mechanical versus judgment) is
optional diagnostic annotation in correction notes, never part of the result schema or bookkeeping. A
replacement dispatch after transport failure, cancellation, or regeneration reviews the current
snapshot on its own terms: evidence for unchanged inputs survives, and findings the parent rebutted
with evidence the earlier Review lacked are not re-litigated.

## Scope and limitations

A shared contract fixes thin dispatch context and vague correction instructions but cannot offset
weak validation or guarantee exhaustive first-pass discovery; a persistent loop with complete
assignments and actionable findings points at validation adequacy and correction strategy, not at
adding more template fields.
