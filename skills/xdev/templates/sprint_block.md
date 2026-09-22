### Sprint N: {Title}

**schema_version:** 1.2

Create this block only after reading this exact template; preserve all required
fields. Bootstrap, migration, or malformed recovery rereads this template;
ordinary resume uses the recorded schema version and durable fields and fails
closed when required fields cannot be migrated. Use the snapshot ID from its
validation evidence in Review.

#### Contract
The authoritative checkbox todo list in `plan_and_track.md` is maintained only
by the Orchestrator; this sprint records references to its stable todo IDs.

- **Logical Task ID:**
- **Generation:**
- **Runtime ID (transport metadata):**
- **Scope:**
- **Allowed files:**
- **Target/baseline references:**
- **Acceptance criteria:**
  | Criterion ID | Acceptance criterion | Todo ID(s) | Result |
  |---|---|---|---|
- **Required validation commands, scenarios, or other faithful evidence:**
- **Expected results:**
- **Out-of-scope:**
- **Assumptions:**

#### Completion Report
- **Files changed:** exact paths
- **Status:** pending / running / completed / failed / blocked / cancelled / superseded
- **Validation evidence:**
  | Revision | Snapshot ID | Owner | Check/scenario | Expected | Actual | Status | Exit status | Raw reference (when material) |
  |---|---|---|---|---|---|---|---|---|
- **Criteria status:** one result per acceptance criterion
- **Assigned todo IDs:** {IDs from the authoritative list}
- **Per-todo result / proposed follow-up:** {Orchestrator reconciliation records discharge; Fixer/Oracle proposals only}
- **Durable evidence reference(s):** {repo path + hash, immutable artifact/URL, or inline material evidence; transport-only references cannot discharge todos}
- **Deviations/blockers:** none, or exact details

#### Review Readiness
- **Exact unit / contract / snapshot:**
- **Snapshot manifest contents:** {repository root/base; sorted relevant paths/status/modes/byte hashes; manifest hash; explicit exclusions}
- **Acceptance criteria:** all satisfied / not satisfied (criterion results above)
- **Todo reconciliation:** consistent at revision {revision}; implementation/correction/integration/required-validation todos discharged; Review-action todo {ID/status}
- **Non-superseded results integrated:** yes / no
- **Pending implementation, correction, or integration tasks:** none / listed
- **Required validation against snapshot:** all `PASS` / not ready (evidence above)
- **Prior actionable findings:** resolved and revalidated / outstanding
- **Known actionable in-scope defect:** none / listed
- **Gate:** `REVIEW_READY` / `NOT_REVIEW_READY` / `BLOCKED_REVIEW` (explicit non-delivery only)
- **Remaining actions / blocker evidence:**

#### Evaluation Verdict
- **Review revision:**
- **Review owner:**
- **Snapshot identity:** {same immutable snapshot ID used by required validation}
- **Expected:**
- **Actual:**
- **Verdict:** PASS / FAIL
- **Reason code (when precondition fails):** REVIEW_PRECONDITION_NOT_MET
- **Exit status:**
- **Review evidence reference (when material):**
- **Review findings:**
