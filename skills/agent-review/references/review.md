# Independent Review assessment

This file alone owns Review. Load `agent-review/SKILL.md` first; Review dispatch and assessment also require `agent-review/references/advisory.md`.
Review judges evidence and gives concrete corrections/decisions; it is not a permission
ballot or an intermediate micro-assessment. The parent owns delivery.

## Modes and eligibility

- **R1** DELIVERY requires the exact complete unit, contract and immutable snapshot; passing criterion-level execution or faithful static/scenario evidence; integrated non-superseded results; no pending scoped implementation, correction or integration; all required validation passing on that snapshot, including explicitly justified unchanged-input applicability under P11; resolved/revalidated prior blocking findings and no known material in-scope defect; nonblocking advice has a recorded disposition, not mandatory repair. xdev also requires complete todo reconciliation, with only the designated Review-action todo open for the unit being assessed. Leave later-sprint work open and explicitly outside this assessment; it still counts at final closure.
- **R2** STATIC/DESIGN requires identified sources/design scope, authoritative criteria and reviewer evidence, not implementation or passing delivery checks. It is optional, non-gating and once per coherent unit across snapshots/generations; never return to it or substitute it for delivery assessment.
- **R3** BLOCKED_REVIEW requires all feasible checks run, authoritative blocked-check evidence and no viable authorized in-scope remedy. It is explicit non-delivery, always has blocking findings and never relaxes readiness, authorization or xdev closure. Never use it to discover remedies or spend a slot early.
- **R4** Incomplete/remediable work returns to authorized repair, discovery or decision advice, not user contact. Advice cannot waive acceptance, validation, snapshot identity or independent delivery assessment.
- **R5** Missing/contradictory context preventing judgment of target, snapshot, material acceptance, integration, pending work or required validation is an unmet precondition, including unestablished evidence provenance, missing required parent media evidence or unavailable explicitly required independent verification. Cosmetic record defects are observations once authoritative evidence fixes material facts.

Eligibility is recorded as reconciled facts, not a separate readiness label or approval.
The parent supplies its complete criterion self-audit and prior resolutions. Oracle reads
authoritative changed files and validation evidence directly, names exact missing checks
for the parent and discloses execution ownership under shared policy.
Read a changed file rather than request the same unchanged diff twice.

## Submission and preflight

Use `ORACLE_ASSIGNMENT v2` plus this bound submission. Fill all fields, N/A only where
inapplicable. Original instructions/sources/raw evidence precede parent conclusions.

```text
REVIEW_SUBMISSION v2
Mode: DELIVERY | STATIC/DESIGN | BLOCKED_REVIEW
Review contract: <exact accessible path + hash>
Objective ID / goal revision:
Unit ID / complete accepted end-to-end outcome:
Review ID:
Dispatch ordinal / complete prior dispatch history / recorded owner extension: <or N/A>
Route:
xdev state path / revision / covered sprint and todo IDs: <or N/A>

SNAPSHOT BINDING
<root/base; commit/tree or deterministic manifest + hash; exact Snapshot ID;
paths/status/material modes/byte hashes/deletions/exclusions; product inputs,
integration context and change since prior assessment; output evidence separately>

CONTRACT AND CRITERIA
<contract + hash; IDs, materiality, observable expectations, authoritative basis,
invariants, original outcome/non-goals, allowed scope/exclusions; required validation,
owner/cadence, completed evidence and unchanged-input applicability>

RAW EVIDENCE AND LIMITS
<observation | source/inspection or execution owner | exact reference | coverage;
commands/inputs/exits/expected vs actual/raw output; contrary evidence and gaps;
access/modality limits and parent-recorded media/corpus evidence>

RECONCILED STATE
<criterion self-audit with evidence/owner; integration/non-superseded results;
pending work, defects, validation applicability and every mode-eligibility fact;
material undecided questions; labelled parent interpretations are non-authoritative>

COMPLETE PRIOR-FINDINGS BATCH
<every raw prior result; each finding's requirement/action/disposition:
corrected | rebutted | superseded | outstanding; evidence and supersession mapping;
for every redispatch: defect-class mapping, equivalent in-scope paths/stages inspected,
class-level corrections/rebuttals/checks and limits; when R15 applies: earlier correction
failure, changed repair/validation mechanism, intended-path/disabled-feature controls>

REQUEST
Assess this exact current unit against authoritative criteria and independently
judge its approach. Return all material findings, prior resolutions, decisions and
ordered actions in one bound result. Parent interpretations do not bound the search.
Do not approve future corrections or claim summaries were directly inspected.
```

- **R6** Before call start, parent preflight checks fields, readable bindings, identity, history, pending work and structural/internal consistency; malformedness requires parsing, not semantic judgment. Settle safety/corpus/provenance dependencies before dispatch, not with a capped intake call.
- **R7** Finish accepted scope, whole corrections batch and integration before assessing the coherent unit; never dispatch per file, finding, diagnostic or generation. First establish the working intended end-to-end path and complete material acceptance, not fragment polish; an early irreversible/safety/design decision uses bounded Planning or the optional STATIC/DESIGN mode, not premature delivery Review. Independence concerns authorship, not model choice: parent self-review cannot supply independent delivery evidence.

## Result

Return exactly one `oracle-review-result`, no verdict/approval line or scalar ballot.
Allowed alternatives below are enums, not literal pipe strings.

```json
{
  "version": 2, "mode": "DELIVERY", "reviewId": "<assigned Review ID>",
  "unitId": "<assigned Unit ID>", "snapshotId": "<assigned Snapshot ID>",
  "reasonCodes": [],
  "preconditions": {"status": "MET", "evidenceRefs": []},
  "criteria": [{
    "id": "C1", "status": "not-satisfied", "evidenceRefs": [], "findingIds": ["<unit>-F001"]
  }],
  "findings": [{
    "id": "<unit>-F001", "blocking": true, "criterionIds": ["C1"],
    "locations": [{"path": "<path>", "lineStart": 1, "lineEnd": 1}],
    "defect": "<current-state failure>",
    "evidenceRefs": ["<static proof or reproduction: expected vs observed>"],
    "requiredAction": {
      "instruction": "<bounded remediation outcome>",
      "acceptancePredicate": "<observable condition resolving this defect>"
    }
  }],
  "priorFindingResolutions": [],
  "coverage": {"inspectedRefs": [], "executionOwners": [], "limitations": []},
  "residualRisks": [],
  "authorDecisionItems": [],
  "nextActions": [{
    "kind": "remedy", "owner": "parent",
    "instruction": "<one coherent corrective batch>",
    "acceptancePredicate": "<observable resolution>",
    "findingIds": ["<unit>-F001"], "decisionIds": []
  }]
}
```

- **R8** Echo assigned mode, Review ID, Unit ID and Snapshot ID verbatim. xdev results carry assigned stateRevision verbatim; non-xdev results omit it. Product bytes cannot identify semantic state. Version is 2; all shown fields/arrays are required, empty rather than fabricated.
- **R9** Preconditions status is MET or REVIEW_PRECONDITION_NOT_MET; unmet status includes that reason code and a blocking finding. Criteria are satisfied/not-satisfied/not-assessed, covering every assigned criterion; unmet material criteria have blocking finding IDs. Every prior finding receives resolved/unresolved/withdrawn/superseded status with evidence; an unresolved nonblocking observation may retain a reasoned defer/reject disposition and does not prevent clear delivery.
- **R10** Every blocking issue has a stable finding ID and current-state evidence tied to a material assigned criterion or required invariant; no demonstrated material consequence means observation/advice, not a blocker. Missing required material validation/evidence or assessment preconditions is itself a material evidence failure, without needing a proven implementation bug. Every requiredAction has a falsifiable acceptance predicate. Deterministic claims require a mechanical predicate naming fixed inputs, a repeatable executable or rule-based static check and its expected result; where judgment is indispensable, name the authoritative criterion, concrete scenario/evidence and observable resolving condition, and explain why a mechanical check alone is insufficient. Oracle repairs incomplete predicates before returning; a non-conforming return is malformed, not delivery evidence, and the parent preserves it rather than inventing or weakening its predicate. No anonymous blocker, unsupported standard, vague “improve” or “ask Oracle again”. Locations use integer lineStart/lineEnd; requiredAction type implementation/validation/evidence/decision is optional.
- **R11** A clear delivery assessment means DELIVERY mode, met preconditions, every material criterion satisfied and no blocking finding; the parent derives it from the result, never requests a ballot. BLOCKED_REVIEW cannot be clear. A deficient delivery assessment has unmet preconditions, unmet/unassessed material criteria or blocking findings.
- **R12** Decisions use the shared structured rationale and remain recommendations, not acceptance criteria. Ordered nextActions cite real findings/decisions and nonempty instructions/predicates. Planning allows execute/discover/validate; STATIC/DESIGN allows remedy/validate/discover; DELIVERY or BLOCKED_REVIEW with deficiencies allows remedy only; clear DELIVERY allows reconcile only. Remedies cover implementation, validation, evidence repair or decision settlement, not a mandatory implementation over equivalent remedies. Actions are nonempty for deficient/blocked assessments and empty only when no action/advice applies.

Criteria violations are findings. An acceptable-but-improvable or unnecessary approach is
a shared authorDecisionItems recommendation, never an invented blocking defect.
Block on demonstrated material failures against the original outcome, authoritative criteria
or required safety/security/integrity invariants, not hypothetical edge cases, stylistic
preferences or a newly invented standard. Real in-scope security and edge-case failures still
block when their evidence establishes material consequences; working normal flow alone is
not sufficient. Batch findings by shared cause and prioritize outcome/correctness blockers.
The parent records a reasoned accept/defer/reject disposition for optional advice; that advice
neither obliges another repair cycle nor stales a clear assessment without product changes.
Apply shared source-first intelligence and exact next steps even when criteria are satisfied.
An out-of-scope or newly protected alternative is reported, never performed or assumed.
An unmet-precondition result uses this same shape, with applicable fields and no fabricated
inspection. A malformed result cannot be rescued by its actions.

## IDs, correction and effort

- **R13** Findings use `<unitId>-F001`, F002 and onward. Reuse the prior ID for the same root cause after line movement; never renumber, reset or assign an old ID to a different cause. Allocate new IDs after the highest historical suffix. Generation, snapshot, rename or prose hash never decides semantic identity or resets unit identity, contact allowance or dispatch count.
- **R14** Turn the whole blocking-findings batch into one corrective contract; record optional advice dispositions without mandatory implementation. Before every redispatch, name each prior finding's defect class (shared failure mechanism, not instance/location), identify and inspect equivalent in-scope paths/stages, and record how corrections or evidence-backed rebuttals and class-level checks cover them; justify inapplicability. Repair/self-review/validate locally with due affected checks under V1–V2, then establish every required delivery check on the current snapshot by execution or P11 unchanged-input applicability. Do not rerun expensive unaffected checks merely for another correction or dispatch. Never interleave assessment with partial corrections.
- **R15** On recurrence of a defect class, even under a new finding ID, or after a second deficient whole-unit delivery assessment, stabilize before redispatch. Explain why the previous correction/check missed the class and materially change the repair or validation mechanism to address that cause; another snapshot, additional instances patched or another assessment alone is not a changed strategy. Recheck root causes, equivalent affected paths, induced defects and test adequacy. Executable regressions must execute the intended path and fail with the guard/feature disabled, isolating prior state/retries; static/evidence/judgment repairs must demonstrate detection of the prior failure by repeatable comparison or criterion-grounded adverse scenario. Recurring findings retain history.
- **R16** Ordinary Reviewed units default to at most six DELIVERY/BLOCKED_REVIEW dispatches; STATIC/DESIGN, Planning, Input and Closure are not delivery calls and cannot substitute for them. Treat six as a ceiling, not a target: R15 and P20 permit earlier proportionate unsuccessful settlement when materially distinct recovery is exhausted. Commit expenditure before call start: preflight rejection spends none; every started DELIVERY/BLOCKED_REVIEW call spends one, including cancelled, replacement, malformed and precondition-failed calls. No generation/snapshot/rename/sprint/regrouping/route change resets expenditure; replacements or overlapping/repartitioned units retain spent history for the same unfinished outcome. A route label alone cannot evade this allowance. Genuine xdev escalation requires durable coordination under its route criteria, preserves complete dispatch/finding history and follows xdev progress/recovery rather than inheriting this lifetime numeric limit. This allowance and extension policy does not govern xdev. Independent new ordinary Reviewed outcomes have their own allowance, never fresh slots for an old repair. Only the repository owner, or a human explicitly designated by that owner for this decision, may extend a named ordinary Reviewed unit's limit by an explicit finite added allowance. Before using it, record the exact instruction, authority, unit, added allowance and resulting cumulative limit in the unit's existing assessment history. The parent cannot self-grant, infer or generalize an extension; it changes effort only, not eligibility, findings, validation or independent assessment, and grants no user contact. Later and extended dispatches still require eligibility and R15 stabilization. At exhaustion without a clear delivery assessment retain findings/evidence and explicit unsuccessful non-delivery; finish other ready authorized work, then settle the ordinary Reviewed unit. Never loop through advice/closure to obtain delivery approval, self-approve, request an extension automatically or call the unresolved outcome impossible.
- **R17** Assess the complete current unit on first and subsequent calls, not just old findings. Previously overlooked defects include evidence and the earlier coverage gap. Never block on hypothetical future bytes, absent stale defects, unrelated scope or preferences; genuine new material findings remain required. Replacements assess current bytes independently; unchanged-input evidence survives and evidence-backed rebuttals are not re-litigated.

The parent owns ordinary Reviewed expenditure and explicit unsuccessful non-delivery;
xdev owns its progress/recovery, batching and closure. R14–R15 and independent final delivery
evidence apply to both routes. Record class checks and ordinary Reviewed extensions in
existing evidence/history, not new schema fields.

## Prompt preservation

- **R18** Bind baseline and shipping scope. The parent contextually reads every affected source block, including lists/tables/schemas/subordinate clauses, recording complete range coverage and grouped duty dispositions, destination quotes, owner/load applicability, rationale and reader. Other affected text gets explicit no-duty dispositions; unchanged bytes/applicability need no re-audit. Extraction/counts prove integrity, not completeness.
- **R19** Compare actor, condition, prohibition and exception. For changed safety, contact, role, evidence/validation, identity, lifecycle or Review-limit duties, supply adverse scenarios/static proofs scaled to consequence. Investigate mismatches and restore losses unless actual instructions authorize them; disclosure alone authorizes nothing.
- **R20** Supported coverage/dispositions, risk evidence and resolved known losses provide bounded assurance, not exhaustive equivalence. Missing evidence or unauthorized loss is blocking. Report residual uncertainty; use existing routes/assessment, never extra completeness Reviews.

Shared contracts cannot substitute for faithful validation or exhaustive discovery.
Persistent loops need improved correction and validation, not additional schema ceremony.
