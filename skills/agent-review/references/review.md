# Review reference

Modes, entry conditions, assignment, result schema and anti-loop rules; loaded from `SKILL.md`.
Review is a delivery gate, never an intermediate micro-gate.

## Modes and entry conditions

| Mode | Admissible when | Not a substitute for |
|---|---|---|
| `DELIVERY` | `REVIEW_READY` (below), pre-Review validation passing, no pending delivery-blocking correction, reconciled state, xdev todo reconciliation with its Review-action todo open. | — |
| `STATIC/DESIGN` | Identified sources or design scope, authoritative criteria, reviewer evidence; completed implementation **not** required. | Delivery Review; a PASS here never approves delivery. |
| `BLOCKED_REVIEW` | Feasible checks run, blocked checks evidenced, no viable authorized in-scope remedy. | Readiness, approval, or relaxation of xdev closure; returns only `Verdict: FAIL`. |

`REVIEW_READY` means ready for delivery Review, not approved. The parent **criterion self-audit**
references passing applicable execution evidence per material criterion, or static/scenario evidence
where a command cannot honestly suffice, and reconciles every prior finding. It needs no separate
artifact or approval.

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

The parent supplies all evidence, never requests or prefers PASS, and validates the assignment
before dispatch. Finish accepted scope, the full corrections batch and integration before Review of
the complete coherent unit, never a file, finding or generation. Preflight rejection before call start
spends no slot; reused identity/history resets neither count nor readiness. Independence concerns
authorship, not model choice: parent self-review cannot supply independent delivery PASS.

## REVIEW_ASSIGNMENT v1 — required input

Fill every field; arrays may reference durable evidence Oracle can read.

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

Required in every Review result; relaxes no contract invariant.

Planning's full return contract is in `agent-review/SKILL.md`: decision and one `oracle-advisory-result`,
no Review verdict. Input-assessment and xdev closure contracts are unchanged.
An `acceptancePredicate` is an executable check, a faithful scenario, or a static proof; commands
name bound inputs, expected result, and owner, and architectural or product-level judgment gets no
invented one.

### Field types, alternatives, and binding agreement

`version` is `1`; `mode` equals assignment `Mode`; `verdict` is exactly `PASS` or `FAIL` and matches
the textual verdict line. Each enum takes one shown alternative, else contract-invalid. `reviewId`,
`unitId`, and `snapshotId` echo assigned `Review ID`, `Unit ID`, and `Snapshot ID` verbatim.
xdev results must carry the assigned `stateRevision` verbatim; non-xdev results omit it. Product bytes cannot identify
semantic state. `preconditions.status` is `MET` or unmet, unmet must be represented as
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
only**. Delivery remedies may cover implementation, validation, evidence repair or decision settlement;
require bounded outcomes and acceptance predicates; never say "rebuild and come back" or "ask Oracle
again", or approve future corrected bytes. Per-finding `requiredAction` governs: the brief groups and
orders actions, never mandates a preferred implementation over an equivalent remedy satisfying the
finding. Empty `instruction` or `acceptancePredicate`, stage-illegal `kind`, missing brief or an action
referencing no real finding or decision is contract-invalid; adding a brief cannot repair a malformed
result.

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
after line movement; never renumber, reuse, or reset IDs after snapshot or generation changes.
Allocate new IDs sequentially after the highest historical suffix. Semantic equivalence still needs
judgment; a hash of changing prose does not decide it. No generation, rename, or snapshot change resets unit
identity, finding IDs, or the clarification allowance.

## Correction after FAIL

Turn Oracle's whole findings batch into one corrective contract; repair and validate locally,
rerun affected checks and preserve unchanged-input evidence.
After a second whole-unit FAIL, materially recheck root causes, equivalent affected paths, induced
defects and test adequacy. Show implicated regression behaviour executes the intended path and fails
with guard/feature disabled, prior state or retries isolated so they cannot mask that control.
Recurring findings retain their ID/history and explain why the earlier correction failed and how
the new repair differs.

## Effort limit

Ordinary Reviewed units have at most three DELIVERY/`BLOCKED_REVIEW` dispatches; `STATIC/DESIGN`,
Planning, and xdev are excluded. Expenditure is decided **before the call starts**, never inferred
from findings: preflight rejection spends no slot; **every started DELIVERY/`BLOCKED_REVIEW` call
spends one, including replacements, malformed assignments, and precondition failures**.
Preflight checks required fields, bound evidence, identity, history and pending work for structure
and internal consistency, not semantic admissibility; malformed-ness requires parsing. No generation,
snapshot or rename resets the count. The third dispatch still needs `REVIEW_READY` and second-FAIL
stabilization. The parent owns exhaustion, non-delivery and xdev batching.

## Anti-loop rules

Inspect and report the complete unit on first Review and the whole batch on re-review, not just
likely or old findings. Each finding demonstrates a current snapshot/bound-evidence defect;
previously overlooked defects include evidence and the earlier coverage gap. Never fail for
hypothetical future changes, absent stale defects, unrelated scope or unstated preferences;
genuine new material findings remain required. Mechanical/judgment classification is optional
correction-note diagnostics, not schema or bookkeeping. Transport-failed, cancelled or regenerated
replacements judge the current snapshot independently: unchanged-input evidence survives; do not
re-litigate rebuttals supported by evidence the earlier Review lacked.

## Prompt preservation

For prompt/skill rewrites, bind baseline and shipping scope. The parent contextually reads every
affected source block, including lists, tables, schemas and subordinate clauses. Record complete
range coverage and grouped duty-family dispositions, destination quotes, owner/load applicability,
rationale and reader; give explicit no-duty dispositions for other affected text. Unchanged bytes
and applicability need no re-audit. Extraction/counts establish integrity, not completeness.

Compare actors, conditions, prohibitions and exceptions. Scale evidence by consequence: adverse
scenarios or static proofs for each affected safety, user-contact, role, evidence/validation,
identity, lifecycle or Review-limit invariant. Investigate mismatches; restore losses unless actual
instructions authorize the change. Disclosure authorizes nothing.

Accept supported coverage/dispositions, risk evidence and all known-loss resolutions, not an
exhaustive-equivalence certificate. Missing evidence or demonstrated unauthorized loss fails
preservation. Report bounded assurance and residual uncertainty, never unqualified completeness.
Use existing routes/gates, not extra completeness Reviews.

## Scope and limitations

Shared contracts fix thin context and vague remedies, not weak validation or exhaustive discovery.
Persistent loops with complete assignments and actionable findings require better validation and
correction strategy, not more fields.
