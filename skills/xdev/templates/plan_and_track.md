# Plan & Track: {Feature Name}

**schema_version:** 1.2

Use the exact fields in this template.

## State Locator
- **Objective identity:** {objective identity}
- **Resolved state file:** {exact resolved path}
- **Locator rule:** `.tmp/xdev/{objective-slug}/plan_and_track.md` using the deterministic normalized slug, or the exact caller-supplied path
- **Default slug normalization:** lowercase, trim, replace every run of non-alphanumeric characters with a hyphen, then trim hyphens
- **Bootstrap/resume:** create only if absent; resume this same locator; never overwrite
- **State writer:** Orchestrator only
- **Template use:** read this exact template on bootstrap/migration/malformed
  recovery; ordinary resume uses schema version and durable fields; read
  `skills/xdev/templates/sprint_block.md` before creating each sprint block

## Task Ledger
Apply `skills/xdev/SKILL.md` sections **Durable task ledger and outcomes**
and **Durable revisions, snapshots, and recovery**. The table below records
the authoritative task identities, transport state, integration, and evidence.

| Logical Task ID | Role / lane | Runtime ID (transport) | Generation | Scope | Status | Supersedes | Integration | Durable terminal result/evidence (class + reference) | Replacement reason |
|---|---|---|---:|---|---|---|---|---|---|---|

## Authoritative Todo List
Apply `skills/xdev/SKILL.md` sections **Bootstrap, resume, and state authority**
and **Parent-objective closure**. Use the row schema below.
Bootstrap contains no todo rows until authorized work exists; add no placeholder.

Todo row schema (append only when real work exists): `- [ ] TODO-{stable ID} — ...`;
the checked form is `- [x]`. Each row records **type:** implementation /
correction / integration / required-validation / Review-action /
closure-assessment; **owner:** {role}; **scope/reference:** {bounded action and
authoritative record}; **evidence:** pending (durable class + reference);
**discharge revision/reference:** pending; **lineage:** —

## State
- **State revision:** {monotonic revision; every durable semantic write increments once}
- **Lifecycle phase:** {baseline / sprint / final validation / complete}
- **Outcome:** active / delivered / conclusively blocked
- **Execution disposition:** continue / awaiting_user
- **Closure candidate:** {candidate ID or none}; **candidate revision:** {state revision or none}
- **Proposed outcome:** none / delivered / conclusively blocked
- **Closure assessment:** **status:** pending / valid / invalid / stale / unavailable; **conclusion:** CONTINUE_REQUIRED / USER_INPUT_REQUIRED / TERMINAL_PREMISE_SUPPORTED / none; **candidate ID:** {candidate ID or none}; **candidate revision:** {state revision or none}; **proposed Outcome:** {outcome or none}; **Oracle logical task ID:** {task ID or none}; **Oracle generation:** {generation or none}; **reference:** {authoritative assessment reference or none}; **user-owned decision/action:** {exact action or none}; **why evidence cannot decide:** {reason or none}; **authorized question:** {exact concise question or none}
- **Current state snapshot ID:** {snapshot ID for the current state; each validation/Review record names the ID for its corresponding unit/state}
- **Current sprint:** {sprint ID or none}
- **Next owner:** {role or runtime}
- **Next action:** {specific action}
- **Final-validation owner:** {owner}; **status:** pending
- **Final Review:** pending
- **Pending task IDs:** {IDs or none}
- **Non-superseded integration:** pending
- **Required validation:** pending
- **Sprint/task statuses:** {sprint/task IDs and pending / running / completed / failed / blocked / cancelled / superseded}

## Coherent Baseline
### Requirements
#### Initial Brief
#### Scope
#### Intended Behavior / Expected Outputs
#### Authoritative Basis
#### Acceptance Criteria
| Criterion ID | Criterion | Authoritative evidence reference(s) | Result | Todo ID(s) |
|---|---|---|---|---|
#### Assumptions
| ID | Assumption/default | Source | Consequence | Validation/retirement trigger | Status |
|---|---|---|---|---|---|

### Design Details
### Material Cases and Invariants
- **Normal:**
- **Boundary/error:**
- **Regression/invariant:**
### Risk Boundaries
### Validation Strategy
#### Deterministic tests/checks
#### Behavioral/integration or other evidence
#### Source-corpus validation (when applicable)
- **Claimed source scope:**
- **Semantic item-level ground-truth baseline:** {Orchestrator item-by-item contextual expected results, when this claim type applies}
- **Mechanically specified transformations:** {exact rule and expected-result basis, when applicable}
- **Population/statistical claim basis:** {defined population and independent sampling/estimation method, when applicable}
- **Automation scope:**
- **Mismatch status:**

#### Baseline Validation Evidence
| Revision | Snapshot ID | Owner | Check/scenario | Expected | Actual | Status | Exit status | Raw reference (when material) |
|---|---|---|---|---|---|---|---|---|

## Sprint Records
After the Orchestrator accepts the coherent baseline (and records the applicable corpus basis), instantiate one sprint block for each planned review-worthy risk boundary before implementation. There is no preimplementation Baseline Review; strategic scrutiny belongs to Planning evidence. Update each block in place through execution, bounded correction, validation, and Review. Historical sprint validation and Review records retain their original snapshot IDs.

## Final Validation Evidence
| Revision | Snapshot ID | Owner | Check/scenario | Expected | Actual | Status | Exit status | Raw reference (when material) | Findings |
|---|---|---|---|---|---|---|---|---|---|

## Final Whole-State Review
- **Review revision:**
- **Review owner:**
- **Snapshot identity:** {one final immutable snapshot ID, recorded in current State and used by the corresponding final validation}
- **Expected:**
- **Actual:**
- **Verdict:** PASS / FAIL
- **Reason code (when precondition fails):** REVIEW_PRECONDITION_NOT_MET
- **Exit status:**
- **Raw evidence reference (when material):**
- **Findings:**

## Final Review Readiness
- **Exact delivery unit / contract / snapshot:**
- **Snapshot identity:** {snapshot ID for this exact delivery unit; commit/tree ID only when it exactly materializes every relevant file, otherwise deterministic manifest/hash covering all relevant tracked, staged, and untracked files}
- **Snapshot manifest contents:** {repository root/base; sorted relevant paths/status/modes/byte hashes; manifest hash; explicit exclusions}
- **Acceptance criteria:** all satisfied / not satisfied (authoritative criteria and evidence)
- **Todo reconciliation:** consistent at revision {revision}; scoped implementation/correction/integration/required-validation todos discharged; Review-action todo {ID/status}
- **Non-superseded results integrated:** yes / no
- **Pending implementation, correction, or integration tasks:** none / listed
- **Every required validation ran against snapshot:** yes, all `PASS` / not ready
- **Prior actionable Review findings:** resolved and revalidated / outstanding
- **Known actionable in-scope defect:** none / listed
- **Gate:** `REVIEW_READY` / `NOT_REVIEW_READY` / `BLOCKED_REVIEW` (explicit non-delivery only)
- **Remaining actions / blocker evidence:**

## Terminal Decision Record
- **Closure candidate ID / revision:** {ID} / {revision}
- **Proposed outcome:** none / delivered / conclusively blocked
- **Closure basis:** delivered when the final sprint Review scope and evidence exactly equal whole-state scope and all completion invariants pass; otherwise blocked/negative or an uncovered premise requires the revision-bound Oracle closure assessment
- **Reconciliation:** baseline and criteria; all sprints; task generations/supersession; integration; validation; Review findings; blockers/recovery; remaining authorized actions
- **Authoritative evidence references:** {exact paths or references}
- **Unmet criteria:** {none or criteria and evidence}
- **Recovery attempts:** {none or materially distinct attempts and results}
- **Remaining authorized actions:** {none or actions}
- **Oracle assessment:** {status, conclusion, candidate ID, candidate revision, proposed Outcome, logical Oracle task ID, generation, and authoritative reference; required only for blocked/negative or otherwise uncovered closure premises; not required for coincident final Review delivered closure}
- **Orchestrator decision:** {Outcome: active / delivered / conclusively blocked; execution disposition: continue / awaiting_user; rationale and revision}
- **Recording rule:** follow `SKILL.md` sections **Durable revisions, snapshots, and recovery** and **Parent-objective closure**, including the atomic N→N+1 closure integration.

## History
Append only accepted baseline/Review, completed sprint, semantic revision,
material blocker or replacement, final validation, and completion.
