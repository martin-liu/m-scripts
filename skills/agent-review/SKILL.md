---
name: agent-review
description: Shared Oracle Review contract — the fill-in Review Assignment template, the mandated oracle-review-result schema, and whole-unit anti-loop rules. Read before every DELIVERY, STATIC/DESIGN, or BLOCKED_REVIEW dispatch.
license: MIT
metadata:
  author: martinliu
  version: "1.0.0"
---

# agent-review

This is the sole contract for Oracle **Review** dispatches: `DELIVERY`, `STATIC/DESIGN`,
and exceptional `BLOCKED_REVIEW`. The parent reads it and fills the Review Assignment
template before every Review dispatch; Oracle reads the exact identified contract before
judging. Planning, `USER_INPUT_ASSESSMENT`, and xdev closure assessment keep their own
separate contracts — this skill does not govern them.

Its purpose is to reduce avoidable Review loops by fixing **both** loop causes at once: an
under-specifying dispatch, and vague correction instructions. It does **not** weaken the
existing gates; delivery readiness, the ordinary Reviewed three-dispatch cap, the
second-whole-unit-FAIL stabilization, and xdev closure rules all still apply. Neither this
template nor any check on it grants readiness, approval, user-contact permission, or closure.

## Parent dispatch discipline

- Review covers a complete coherent unit — not an isolated file, finding, or task generation.
- Finish the unit's accepted scope **and** the complete existing corrections batch, integrate
  results, and satisfy the mode's entry conditions before dispatching.
- Supply original instructions, authoritative criteria, exact snapshot bindings, raw evidence
  and execution ownership, contrary evidence, known gaps, reconciled state, and the **complete**
  prior-findings batch.
- Keep observations separate from interpretations. Never request PASS or present a preferred
  verdict; an interpretation is an input to independent judgment, not authoritative truth.
- Validate the filled assignment before dispatch. An invalid assignment spends no Review slot
  because no call starts.
- The BLOCKED_REVIEW mode is admissible only when **all feasible checks have already run**, the
  blocked checks have authoritative evidence, and **no viable authorized in-scope remedy remains**.
  Do not dispatch it to discover a remedy or to spend a capped slot prematurely; Oracle can return
  it only as `Verdict: FAIL`, as non-delivery that never establishes readiness and never relaxes
  xdev closure.
- Reuse the existing unit identity and dispatch history. Completing the template neither resets
  the dispatch count nor establishes readiness.

## REVIEW_ASSIGNMENT v1 — required input

Fill every field. Tables/arrays may reference existing durable records rather than duplicate
large evidence bodies, but referenced content must be independently readable by Oracle.

```text
REVIEW_ASSIGNMENT v1

Mode: DELIVERY | STATIC/DESIGN | BLOCKED_REVIEW
Review contract: <exact accessible path + hash of this skill>
Objective ID / goal revision: <stable identity>
Unit ID / complete accepted outcome: <identity + end-to-end boundary>
Review dispatch ordinal / prior dispatches: <history references>
Review ID: <this dispatch's exact identity string, echoed verbatim in the result>
Route: <route>
xdev state path / revision / covered sprint and todo IDs: <values or N/A>

SNAPSHOT BINDING
<Repository root/base; exact commit/tree or manifest reference + hash; Snapshot ID echoed
verbatim in the result; relevant paths/status/modes/byte hashes, deletions and explicit
exclusions.>
<Product inputs and supporting integration context covered by the binding.>
<Changed scope since the previous Review; previous/current snapshot references.>
<Output evidence references separately from product identity.>

ORIGINAL INSTRUCTIONS
<Original task verbatim; material later constraints and exact authorizations.
References are acceptable only when Oracle can read their exact contents.>

CONTRACT AND CRITERIA
<Exact contract reference + hash>
<Criterion IDs, observable expected outcomes, authoritative basis,
material invariants, allowed scope, exclusions, required validation.>

OBSERVATIONS AND RAW EVIDENCE
<Observation | source/owner | exact reference | coverage/limitations>
<Include check commands, input bindings, execution owner, exit status,
expected/actual results, and material raw outputs.>

CONTRARY EVIDENCE AND KNOWN GAPS
<Contrary fact or gap | source | affected criterion | material consequence>
<Access/modality limits and parent-owned media/corpus evidence where applicable.>

PARENT INTERPRETATIONS — NOT AUTHORITATIVE EXPECTED RESULTS
<Labeled interpretations with supporting/contrary references, or none.
No requested verdict, approval framing, or unstated preference.>

RECONCILED STATE
<Acceptance claims per criterion with evidence and claim owner;
integration and non-superseded results;
pending implementation/correction/integration/validation work;
known defects; required-validation applicability;
readiness gate and evidence.>
<DELIVERY: REVIEW_READY.
STATIC/DESIGN: sources, criteria, and assessment evidence.
BLOCKED_REVIEW: feasible checks, blocked-check evidence, and exhausted remedies.>

COMPLETE PRIOR-FINDINGS BATCH
<Every prior raw Review result reference.>
<Every finding ID/key, original requirement and required action;
parent disposition: corrected | rebutted | superseded | outstanding;
correction/rebuttal evidence, affected paths/checks, and supersession mapping.>
<After second whole-unit FAIL: changed repair/validation strategy and evidence,
including intended-path/disabled-feature controls when implicated.>

REQUEST
Independently assess this exact current unit against the authoritative criteria.
Return the mandated Review result. Report all material findings as one batch.
Do not approve future corrections or treat summaries as inspected evidence.
```

## Mandated Oracle result

Return one textual `Verdict: PASS` or `Verdict: FAIL` line, followed by exactly one
`oracle-review-result` JSON block. The JSON `verdict` must match the line; they are two
representations of the same judgment, not separate approvals. In the shape below,
`a | b` denotes **allowed alternatives**, not a literal value to emit.

```json
{
  "version": 1,
  "mode": "DELIVERY",
  "reviewId": "<dispatch identity>",
  "unitId": "<stable unit identity>",
  "snapshotId": "<submitted binding>",
  "verdict": "FAIL",
  "reasonCodes": [],
  "preconditions": { "status": "MET", "evidenceRefs": [] },
  "criteria": [
    { "id": "<criterion ID>", "status": "satisfied | not-satisfied | not-assessed", "evidenceRefs": [], "findingIds": [] }
  ],
  "findings": [
    {
      "id": "<unitId>-F001",
      "blocking": true,
      "criterionIds": [],
      "locations": [{ "path": "<exact path>", "lineStart": 1, "lineEnd": 1 }],
      "defect": "<specific current-state failure>",
      "evidenceRefs": ["<reproduction evidence: command/scenario/static proof and expected vs observed>"],
      "requiredAction": {
        "instruction": "<bounded remediation outcome>",
        "acceptancePredicate": "<observable condition resolving the defect>"
      }
    }
  ],
  "priorFindingResolutions": [
    { "id": "<prior finding ID>", "status": "resolved | unresolved | withdrawn | superseded", "evidenceRefs": [] }
  ],
  "coverage": { "inspectedRefs": [], "executionOwners": [], "limitations": [] },
  "residualRisks": []
}
```

### Field types, alternatives, and binding agreement

- `version` is the number `1`. `mode` is exactly one of `DELIVERY`, `STATIC/DESIGN`,
  `BLOCKED_REVIEW` and must equal the assignment's `Mode`.
- `reviewId`, `unitId`, `snapshotId` must reproduce the assignment's `Review ID`, `Unit ID`, and
  `Snapshot ID` verbatim. An xdev unit must carry a `stateRevision` reproducing its assigned xdev
  state revision verbatim; a result that omits it or gives a disagreeing revision is
  contract-invalid. Non-xdev results omit the field. Snapshot identity is not a substitute: xdev
  semantic state can change while product bytes stay identical.
- `verdict` is exactly `PASS` or `FAIL` and must equal the textual verdict line.
- `preconditions.status` is exactly `MET` or unmet, and on unmet must be represented as
  `REVIEW_PRECONDITION_NOT_MET`; any unmet material precondition forces `FAIL`.
- Each `criteria[].status` is exactly one of `satisfied`, `not-satisfied`, `not-assessed`.
- Each `priorFindingResolutions[].status` is exactly one of `resolved`, `unresolved`,
  `withdrawn`, `superseded`.
- `reasonCodes`, `criteria`, `findings`, `priorFindingResolutions`, and `residualRisks` are
  arrays; they are empty arrays rather than omitted when unused. `locations` is an array of
  `{path, lineStart, lineEnd}`; `lineStart`/`lineEnd` are integers.
- A `requiredAction.type` of `implementation`, `validation`, `evidence`, or `decision` is
  permitted but not mandatory; the instruction and its acceptance predicate carry the obligation.
- Unmet preconditions and `STATIC/DESIGN`/xdev results follow the same shape; only the
  applicable fields are populated and non-applicable ones are empty, never fabricated.

### Result invariants

- Exactly one verdict line; exactly one result block; the two verdicts agree.
- Missing material preconditions require FAIL with `REVIEW_PRECONDITION_NOT_MET`.
- `BLOCKED_REVIEW` can return only FAIL; it is never readiness or approval.
- PASS requires met preconditions, satisfied material criteria, and no blocking findings.
- Every blocking issue — including missing material evidence — has a finding ID and a required
  action. No anonymous blockers outside the batch.
- Every prior finding receives a resolution entry; none silently disappears.
- Required actions specify the **observable condition that resolves the defect** — never
  "improve", "be more careful", or "ask Oracle again".
- Oracle may suggest an implementation, but cannot make a preferred implementation mandatory
  when an equivalent remedy satisfies the requirement.
- Evidence may be a direct static proof. Oracle must not execute forbidden validation to
  manufacture a command result.
- Cosmetic record defects remain non-blocking when current authoritative evidence establishes
  the material facts.

### Deterministic IDs

Give each finding a stable ID of the form `<unitId>-F001`, `F002`, … Reuse the prior ID for the
same root-cause finding, including after line movement; never renumber, reuse, or reset IDs after
snapshot or generation changes. Allocate new IDs sequentially after the highest historical
suffix. Recognizing semantic equivalence of findings still requires judgment; a hash of changing
prose does not solve it.

### Anti-loop rules

- Inspect and report the complete submitted unit in the first Review, not only likely problems.
- After FAIL, correct or evidence-rebut the entire batch — including correction-induced defects —
  before redispatch. Never interleave Review with partial corrections of the same findings batch.
- Re-review independently checks the current submitted snapshot and resolves the complete prior
  batch; do not re-review one finding at a time.
- Every new finding must demonstrate a defect in that current snapshot or its bound required
  evidence. Do not fail for hypothetical future changes, stale defects absent from the current
  state, unrelated scope, or an unstated reviewer preference.
- A finding that fixes a changed path is identified by its location; a previously overlooked
  defect in the current state is reported with its evidence and the earlier coverage gap.
- Do not freeze re-review to old findings only: that would hide genuine defects and weaken
  independent final Review. The restriction is against findings unsupported by the reviewed
  state, never against newly discovered material findings.

### Composition with existing gates

- Preserve the ordinary Reviewed three-dispatch cap, counting replacements, precondition
  failures, and `BLOCKED_REVIEW`.
- Preserve the materially changed repair/validation pass after the second whole-unit FAIL.
- Completing the template neither resets the count nor establishes readiness.
- `STATIC/DESIGN` Review, Planning, and xdev remain outside the ordinary cap.
- xdev may batch several sprints into one Review; the assignment names the covered sprints, and
  a matching last-sprint/final whole-state Review remains reusable.
- Cap exhaustion remains explicit unapproved non-delivery — not approval, impossibility, route
  evasion, or automatic user escalation.

## Scope and limitations

A shared input/output contract attacks both likely loop causes: inadequate dispatch context and
vague correction instructions, while making prior-finding reconciliation inspectable without
adding another approval gate. It cannot guarantee exhaustive first-pass discovery or compensate
for weak validation; persistent loops with complete assignments and actionable findings point to
validation adequacy and correction strategy, not to adding more template fields.