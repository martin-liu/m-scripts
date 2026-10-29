# Plan & Track: {Feature Name}

**schema_version:** 2.0

## State Locator
- **Objective identity:** {objective identity}
- **Resolved state file:** {exact resolved path}
Canonical state, todo, snapshot, evidence, and closure rules: `skills/xdev/SKILL.md`.

## Task Ledger
| Logical Task ID | Role / lane | Runtime ID (transport) | Generation | Scope | Status | Supersedes | Integration | Durable terminal result/evidence (class + reference) | Replacement reason |
|---|---|---|---:|---|---|---|---|---|---|

## Authoritative Todo List
Todo row schema: `- [ ] TODO-{stable ID} — ...`; checked form: `- [x]`.
Each row records **type:** implementation / correction / integration /
required-validation / Review-action / closure-assessment; **owner:** {role};
**scope/reference:** {bounded action and authoritative record};
**evidence:** {pending or durable class + reference};
**discharge revision/reference:** {pending or revision/reference}; **lineage:** {none or predecessor}.
Settlement references distinguish satisfied work from evidence-backed unmet/blocked dispositions.

## State
- **State revision:** {revision}
- **Lifecycle phase:** {baseline / sprint / final validation / complete}
- **Outcome:** active / delivered / conclusively blocked
- **Execution disposition:** continue / awaiting_user
- **Closure candidate:** {reference to Terminal Decision Record or none}
- **Current delivery-unit record:** {section/reference holding scope, readiness, validation and integration facts}
- **Snapshot ID:** {current unit/state snapshot ID; final ID shared by final validation and Review}
- **Current sprint:** {sprint ID or none}
- **Next action and owner:** {specific action; owner}
- **Pending tasks:** {ledger references or none}
- **Integration:** {current delivery-unit reference}
- **Validation:** {current delivery-unit evidence reference}
- **Final Review:** {pending or final Review reference}

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
- **Final-validation execution owner:** {designated owner}
#### Deterministic tests/checks
#### Behavioral/integration or other evidence
#### Source-corpus validation (when applicable)
- **Claimed source scope:**
- **Semantic item-level ground-truth baseline:** {parent-recorded contextual expected results}
- **Mechanically specified transformations:** {exact rules and expected-result basis}
- **Population/statistical claim basis:** {population and independent sampling/estimation or exhaustive support}
- **Automation scope:**
- **Mismatch status:**
#### Baseline Validation Evidence
| Revision | Snapshot ID | Owner | Check/scenario or command | Expected | Actual | Status (PASS/FAIL/BLOCKED) | Exit status | Raw reference (when material) |
|---|---|---|---|---|---|---|---|---|

## Sprint Records
{Sprint blocks with their original snapshot bindings. Sprints sharing a contract, invariants,
or validation may share one batched delivery Review and its single Evaluation Verdict; record
that verdict under the covering sprint block and reference the covered sprint IDs.}

## Review Coverage Log
{Optional when batching: list each Review dispatch with its reviewed sprint IDs and verdict
reference, so the batching of sprints into Reviews is auditable without a verdict per sprint.}

## Final Validation Evidence
| Revision | Snapshot ID | Owner | Check/scenario or command | Expected | Actual | Status (PASS/FAIL/BLOCKED) | Exit status | Raw reference (when material) | Findings |
|---|---|---|---|---|---|---|---|---|---|

## Final Whole-State Review
- **Review revision:**
- **Review owner:**
- **Snapshot ID:** {final snapshot ID; binding reference under canonical snapshot rules}
- **Verdict:** PASS / FAIL
- **Reason code (when precondition fails):** REVIEW_PRECONDITION_NOT_MET
- **Review evidence reference:**
- **Findings:**

## Final Review Readiness
- **Exact delivery unit / contract / snapshot:** {references; canonical snapshot rules in SKILL.md}
- **Pre-Review acceptance and required validation:** {satisfied or outstanding; evidence references}
- **Readiness blockers:** {none or material blockers and evidence}
- **Todo reconciliation:** {revision and settlement references; designated Review-action todo ID/status}
- **Non-superseded results integrated:** {yes/no; ledger references}
- **Pending tasks:** {none or ledger references}
- **Every required validation ran against snapshot:** {all PASS or outstanding; evidence references}
- **Prior actionable Review findings:** {resolved and revalidated or outstanding; references}
- **Known actionable in-scope defect:** {none or listed}
- **Gate:** {REVIEW_READY or unmet readiness; BLOCKED_REVIEW is non-delivery, never approval}
- **Remaining authorized actions:** {actions or none; blocker evidence}

## Terminal Decision Record
- **Closure candidate ID / candidate revision:** {ID / revision or none}
- **Proposed Outcome:** {delivered / conclusively blocked or none}
- **Oracle logical task ID / generation:** {ledger identity or none}
- **Closure assessment:** {CONTINUE_REQUIRED / USER_INPUT_REQUIRED / TERMINAL_PREMISE_SUPPORTED or none; authoritative assessment reference}
- **Closure basis:** {coincident final whole-state Review or bound assessment reference}
- **Reconciliation:** {baseline/criteria, sprints, generations/supersession, integration, validation, findings, blockers/recovery, remaining actions, complete todo list}
- **Authoritative evidence references:**
- **Unmet criteria:** {none or criteria and evidence}
- **Recovery attempts:** {materially distinct attempts, results and evidence}
- **Remaining authorized actions:** {none or actions}
- **Todo settlement:** {satisfied references; explicit evidence-backed unmet/blocked dependencies; designated assessment todo settlement revision/reference}
- **Orchestrator decision:** {Outcome; execution disposition; rationale; atomic integration revision}

## History
{Semantic/recovery-significant entries with revision and authoritative references.}
