// Non-writing drift guards: parsed protocol examples, adverse-record scenarios,
// selected canonical obligations, backend adapters and exact frontmatter.
// These do not prove semantic equivalence, runtime loading or agent compliance.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const paths = {
  pp: "shell/config/pi/APPEND_SYSTEM.md",
  po: "shell/config/pi/agents/oracle.md",
  pf: "shell/config/pi/agents/fixer.md",
  op: "shell/config/opencode-agents/orchestrator.md",
  oo: "shell/config/opencode-agents/oracle.md",
  of: "shell/config/opencode-agents/fixer.md",
  skill: "skills/agent-review/SKILL.md",
  review: "skills/agent-review/references/review.md",
  unit: "skills/agent-review/templates/reviewed_unit.md",
  xdev: "skills/xdev/SKILL.md",
  plan: "skills/xdev/templates/plan_and_track.md",
  sprint: "skills/xdev/templates/sprint_block.md",
};
const files = Object.fromEntries(Object.entries(paths).map(([k, p]) => [k, read(p)]));
const flat = (s) => s.replace(/\s+/g, " ").trim();
const examples = (s) => [...s.matchAll(/```json\n([\s\S]*?)\n```/g)].map((m) => JSON.parse(m[1]));
const clone = (v) => JSON.parse(JSON.stringify(v));
const nonempty = (s) => assert.ok(typeof s === "string" && s.trim().length > 0);
const keys = (o, required, optional = []) => {
  assert.ok(o && typeof o === "object" && !Array.isArray(o));
  for (const k of required) assert.ok(Object.hasOwn(o, k), `missing ${k}`);
  for (const k of Object.keys(o)) assert.ok([...required, ...optional].includes(k), `unknown ${k}`);
};
const array = (v) => assert.ok(Array.isArray(v));
const positive = (v) => assert.ok(Number.isInteger(v) && v > 0);
const enumValue = (v, allowed) => assert.ok(allowed.includes(v), `invalid enum ${v}`);

function assignment(v) {
  keys(v, ["version", "lane", "identity", "policyRefs", "basis", "state", "request"]);
  assert.equal(v.version, 2);
  const requests = { Planning: "originate", Input: "assess-ownership", Review: "assess-current", Closure: "assess-candidate" };
  assert.ok(Object.hasOwn(requests, v.lane));
  keys(v.request, ["kind"]);
  assert.equal(v.request.kind, requests[v.lane]);
  keys(v.identity, ["objectiveId", "goalRevision", "subjectId", "taskId", "generation", "route"]);
  for (const k of ["objectiveId", "subjectId", "taskId"]) nonempty(v.identity[k]);
  positive(v.identity.goalRevision); positive(v.identity.generation);
  enumValue(v.identity.route, ["Direct", "Reviewed", "xdev"]);
  array(v.policyRefs); assert.ok(v.policyRefs.length); v.policyRefs.forEach(nonempty);
  keys(v.basis, ["originalInstructions", "intendedOutcome", "userConstraints", "authorizations",
    "sources", "observations", "contraryEvidence", "gaps", "openQuestions", "priorChoices"]);
  nonempty(v.basis.intendedOutcome);
  for (const [k, value] of Object.entries(v.basis)) if (k !== "intendedOutcome") array(value);
  assert.ok(v.basis.originalInstructions.length); assert.ok(v.basis.sources.length);
  keys(v.state, ["contextRef", "root", "base", "snapshotRef", "integration", "pendingWork", "historyRefs"]);
  for (const k of ["contextRef", "root", "base", "snapshotRef", "integration"]) nonempty(v.state[k]);
  array(v.state.pendingWork); array(v.state.historyRefs);
}

function decision(v) {
  keys(v, ["id", "owner", "state", "decision", "selectedOption", "rationale",
    "assumptions", "reconsiderationTrigger", "evidenceRefs"]);
  for (const k of ["id", "decision", "selectedOption", "reconsiderationTrigger"]) nonempty(v[k]);
  assert.equal(v.owner, "parent");
  array(v.assumptions); array(v.evidenceRefs);
  enumValue(v.state, ["unresolved", "settled"]);
  if (v.state === "settled") {
    keys(v.rationale, ["basis", "boundedAction"]);
    nonempty(v.rationale.basis); nonempty(v.rationale.boundedAction);
  } else {
    keys(v.rationale, ["levers", "courses", "frameCheck", "selectionBasis"]);
    array(v.rationale.levers); assert.ok(v.rationale.levers.length);
    v.rationale.levers.forEach(nonempty);
    array(v.rationale.courses); assert.ok(v.rationale.courses.length);
    let selected = 0;
    for (const course of v.rationale.courses) {
      keys(course, ["course", "disposition", "basis"]);
      nonempty(course.course); nonempty(course.basis);
      enumValue(course.disposition, ["selected", "rejected"]);
      if (course.disposition === "selected") selected += 1;
    }
    assert.equal(selected, 1);
    nonempty(v.rationale.frameCheck); nonempty(v.rationale.selectionBasis);
  }
}

function actions(v, allowed) {
  const decisions = new Set(v.authorDecisionItems.map((d) => d.id));
  const findings = new Set((v.findings ?? []).map((f) => f.id));
  assert.equal(decisions.size, v.authorDecisionItems.length);
  assert.equal(findings.size, (v.findings ?? []).length);
  array(v.nextActions);
  for (const action of v.nextActions) {
    keys(action, ["kind", "owner", "instruction", "acceptancePredicate", "findingIds", "decisionIds"]);
    enumValue(action.kind, allowed); enumValue(action.owner, ["parent", "fixer"]);
    nonempty(action.instruction); nonempty(action.acceptancePredicate);
    array(action.findingIds); array(action.decisionIds);
    assert.ok(action.findingIds.length + action.decisionIds.length > 0);
    action.findingIds.forEach((id) => assert.ok(findings.has(id)));
    action.decisionIds.forEach((id) => assert.ok(decisions.has(id)));
  }
}

function advisory(v) {
  keys(v, ["version", "dependencyId", "authorDecisionItems", "nextActions"]);
  assert.equal(v.version, 2); nonempty(v.dependencyId);
  array(v.authorDecisionItems); assert.ok(v.authorDecisionItems.length);
  v.authorDecisionItems.forEach(decision);
  actions(v, ["execute", "discover", "validate"]);
}

function input(v) {
  assert.equal(v.version, 1); nonempty(v.dependencyId);
  if (v.outcome === "AGENT_DECISION") {
    keys(v, ["version", "dependencyId", "outcome", "selectedOption", "rationale",
      "assumptions", "reconsiderationTrigger"]);
    for (const k of ["selectedOption", "rationale", "reconsiderationTrigger"]) nonempty(v[k]);
    array(v.assumptions);
  } else {
    assert.equal(v.outcome, "USER_INPUT_REQUIRED");
    keys(v, ["version", "dependencyId", "outcome", "kind", "dependency", "question", "whyAgentCannotResolve"]);
    enumValue(v.kind, ["authorization", "access", "fact", "product-intent"]);
    for (const k of ["dependency", "question", "whyAgentCannotResolve"]) nonempty(v[k]);
  }
}

const clear = (v, materialIds) => v.mode === "DELIVERY" &&
  v.preconditions.status === "MET" &&
  materialIds.every((id) => v.criteria.some((c) => c.id === id && c.status === "satisfied")) &&
  !v.findings.some((f) => f.blocking);

function review(v, assigned, materialIds, priorIds = []) {
  keys(v, ["version", "mode", "reviewId", "unitId", "snapshotId", "reasonCodes", "preconditions",
    "criteria", "findings", "priorFindingResolutions", "coverage", "residualRisks",
    "authorDecisionItems", "nextActions"], assigned.stateRevision === undefined ? [] : ["stateRevision"]);
  assert.equal(v.version, 2);
  enumValue(v.mode, ["DELIVERY", "STATIC/DESIGN", "BLOCKED_REVIEW"]);
  for (const k of ["mode", "reviewId", "unitId", "snapshotId"]) assert.equal(v[k], assigned[k]);
  if (assigned.stateRevision !== undefined) assert.equal(v.stateRevision, assigned.stateRevision);
  for (const k of ["reasonCodes", "criteria", "findings", "priorFindingResolutions",
    "residualRisks", "authorDecisionItems"]) array(v[k]);
  keys(v.preconditions, ["status", "evidenceRefs"]); array(v.preconditions.evidenceRefs);
  enumValue(v.preconditions.status, ["MET", "REVIEW_PRECONDITION_NOT_MET"]);
  keys(v.coverage, ["inspectedRefs", "executionOwners", "limitations"]);
  Object.values(v.coverage).forEach(array);
  const ids = new Set(v.findings.map((f) => f.id));
  assert.equal(ids.size, v.findings.length);
  for (const f of v.findings) {
    keys(f, ["id", "blocking", "criterionIds", "locations", "defect", "evidenceRefs", "requiredAction"]);
    nonempty(f.id); assert.equal(typeof f.blocking, "boolean"); nonempty(f.defect);
    array(f.criterionIds); array(f.locations); array(f.evidenceRefs);
    if (f.blocking) assert.ok(f.evidenceRefs.length);
    for (const loc of f.locations) {
      keys(loc, ["path", "lineStart", "lineEnd"]); nonempty(loc.path);
      positive(loc.lineStart); positive(loc.lineEnd); assert.ok(loc.lineEnd >= loc.lineStart);
    }
    keys(f.requiredAction, ["instruction", "acceptancePredicate"], ["type"]);
    nonempty(f.requiredAction.instruction); nonempty(f.requiredAction.acceptancePredicate);
    if (f.requiredAction.type !== undefined)
      enumValue(f.requiredAction.type, ["implementation", "validation", "evidence", "decision"]);
  }
  const criteria = new Set(v.criteria.map((c) => c.id));
  assert.equal(criteria.size, v.criteria.length);
  for (const c of v.criteria) {
    keys(c, ["id", "status", "evidenceRefs", "findingIds"]);
    nonempty(c.id); enumValue(c.status, ["satisfied", "not-satisfied", "not-assessed"]);
    array(c.evidenceRefs); array(c.findingIds);
    c.findingIds.forEach((id) => assert.ok(ids.has(id)));
    if (materialIds.includes(c.id) && c.status !== "satisfied")
      assert.ok(c.findingIds.some((id) => v.findings.some((f) => f.id === id && f.blocking)));
  }
  materialIds.forEach((id) => assert.ok(criteria.has(id)));
  for (const p of v.priorFindingResolutions) {
    keys(p, ["id", "status", "evidenceRefs"]);
    nonempty(p.id); enumValue(p.status, ["resolved", "unresolved", "withdrawn", "superseded"]);
    array(p.evidenceRefs);
  }
  priorIds.forEach((id) => assert.ok(v.priorFindingResolutions.some((p) => p.id === id)));
  if (v.preconditions.status !== "MET") {
    assert.ok(v.reasonCodes.includes("REVIEW_PRECONDITION_NOT_MET"));
    assert.ok(v.findings.some((f) => f.blocking));
  }
  if (v.mode === "BLOCKED_REVIEW") assert.ok(v.findings.some((f) => f.blocking));
  v.authorDecisionItems.forEach(decision);
  const allowed = v.mode === "STATIC/DESIGN" ? ["remedy", "validate", "discover"] :
    clear(v, materialIds) ? ["reconcile"] : ["remedy"];
  actions(v, allowed);
  if (v.mode !== "STATIC/DESIGN" && !clear(v, materialIds)) assert.ok(v.nextActions.length);
}

test("v2 examples parse and satisfy their distinct contracts", () => {
  const [a, p, i] = examples(files.skill);
  assignment(a); advisory(p); input(i);
  const [r] = examples(files.review);
  review(r, r, ["C1"]);
  assert.equal(clear(r, ["C1"]), false);
});

test("assignments reject ballot, shortlist, missing basis and lane mismatch", () => {
  const [a] = examples(files.skill);
  for (const mutate of [
    (v) => { v.request.verdict = "PASS"; },
    (v) => { v.basis.shortlist = ["A", "B"]; },
    (v) => { v.basis.preferredSolution = "A"; },
    (v) => { delete v.basis.contraryEvidence; },
    (v) => { v.request.kind = "assess-current"; },
    (v) => { v.identity.generation = 0; },
  ]) { const v = clone(a); mutate(v); assert.throws(() => assignment(v)); }
});

test("intelligence rationale rejects ratification-only and anonymous advice", () => {
  const [, p] = examples(files.skill);
  for (const mutate of [
    (v) => { v.authorDecisionItems[0].rationale = "Pick the parent option"; },
    (v) => { delete v.authorDecisionItems[0].rationale.frameCheck; },
    (v) => { v.authorDecisionItems[0].rationale.levers = []; },
    (v) => { v.nextActions[0].decisionIds = ["missing"]; },
    (v) => { v.nextActions[0].decisionIds = []; },
    (v) => { v.nextActions[0].acceptancePredicate = ""; },
    (v) => { v.verdict = "PASS"; },
  ]) { const v = clone(p); mutate(v); assert.throws(() => advisory(v)); }
  const settled = clone(p);
  settled.authorDecisionItems[0].state = "settled";
  settled.authorDecisionItems[0].rationale = { basis: "Recorded requirement", boundedAction: "Implement it" };
  advisory(settled);
});

test("input ownership keeps user and agent fields disjoint", () => {
  const [, , i] = examples(files.skill);
  const mixed = clone(i); mixed.selectedOption = "A";
  assert.throws(() => input(mixed));
  const missing = clone(i); delete missing.whyAgentCannotResolve;
  assert.throws(() => input(missing));
  input({ version: 1, dependencyId: "D", outcome: "AGENT_DECISION",
    selectedOption: "Reversible default", rationale: "Evidence-backed",
    assumptions: [], reconsiderationTrigger: "Changed requirement" });
});

test("delivery condition is derived, including stale evidence and non-delivery", () => {
  const [r] = examples(files.review);
  const good = clone(r);
  good.criteria[0].status = "satisfied"; good.criteria[0].findingIds = [];
  good.findings = []; good.nextActions = [];
  review(good, good, ["C1"]); assert.equal(clear(good, ["C1"]), true);
  const unassessed = clone(good); unassessed.criteria[0].status = "not-assessed";
  assert.throws(() => review(unassessed, unassessed, ["C1"]));
  const stale = clone(r); stale.preconditions.status = "REVIEW_PRECONDITION_NOT_MET";
  stale.reasonCodes = ["REVIEW_PRECONDITION_NOT_MET"];
  review(stale, stale, ["C1"]); assert.equal(clear(stale, ["C1"]), false);
  const blocked = clone(r); blocked.mode = "BLOCKED_REVIEW";
  review(blocked, blocked, ["C1"]); assert.equal(clear(blocked, ["C1"]), false);
  const noBlock = clone(good); noBlock.mode = "BLOCKED_REVIEW";
  assert.throws(() => review(noBlock, noBlock, ["C1"]));
});

test("optional observations do not force repair while material failures remain blocking", () => {
  const [r] = examples(files.review);
  const optional = clone(r);
  optional.criteria[0] = { id: "C1", status: "satisfied", evidenceRefs: ["verified outcome"], findingIds: [] };
  optional.findings[0].blocking = false;
  optional.findings[0].criterionIds = [];
  optional.findings[0].defect = "Optional maintainability observation, deferred with rationale";
  optional.nextActions = [];
  optional.priorFindingResolutions = [{ id: optional.findings[0].id, status: "unresolved",
    evidenceRefs: ["Nonblocking; deferred outside required delivery scope"] }];
  review(optional, optional, ["C1"], [optional.findings[0].id]);
  assert.equal(clear(optional, ["C1"]), true);

  const materialFailure = clone(optional);
  materialFailure.criteria[0].status = "not-satisfied";
  materialFailure.criteria[0].findingIds = [materialFailure.findings[0].id];
  assert.throws(() => review(materialFailure, materialFailure, ["C1"]),
    "a material failed criterion cannot be disguised as optional advice");
  const realBlocker = clone(r);
  realBlocker.findings[0].defect = "Demonstrated data-integrity failure on the intended path";
  review(realBlocker, realBlocker, ["C1"]);
  assert.equal(clear(realBlocker, ["C1"]), false);
});

test("review binding, batch references and conditional action legality bite", () => {
  const [r] = examples(files.review);
  for (const mutate of [
    (v) => { v.snapshotId = "other"; },
    (v) => { v.findings[0].evidenceRefs = []; },
    (v) => { v.nextActions[0].kind = "validate"; },
    (v) => { v.nextActions[0].findingIds = []; },
    (v) => { v.findings[0].requiredAction.acceptancePredicate = ""; },
    (v) => { v.stateRevision = 4; },
  ]) { const v = clone(r); mutate(v); assert.throws(() => review(v, r, ["C1"])); }
  assert.throws(() => review(r, r, ["C1"], ["old-F001"]));
  const x = clone(r); x.stateRevision = 4;
  review(x, x, ["C1"]);
  const wrong = clone(x); wrong.stateRevision = 5;
  assert.throws(() => review(wrong, x, ["C1"]));
});

// Stable canonical rules, not duplicated backend sentences.
// Each guard starts at the normative clause, so prefix negation cannot satisfy it.
const guards = {
  skill: {
    P1: /^The parent alone owns effects, state, routing, delegation, integration, recovery, user contact, continuation and closure/,
    P2: /^Protected effects include identified staging\/production actions, consequential external\/shared mutations, privileged actions, deploy\/publish, machine-wide changes and destructive local database operations unless affirmatively disposable development\/test state; unknown or potentially valuable local databases remain protected\./,
    P3: /^Ordinary repository work, local containers\/processes, tests and local dependency installation are not protected merely for state or network use\./,
    P4: /^Only the parent executes protected effects with sufficient explicit authorization covering the exact effect, target and limits; reuse a still-valid grant/,
    P5: /^Broad goals, routes, advice, assessment evidence and worker contracts grant no protected authorization; missing authorization blocks only that effect/,
    P6: /^A bounded target names output\/behavior, authoritative basis, allowed scope\/non-goals, criterion IDs and observable expectations, evidence, validation owner\/commands\/cadence, material cases and invariants/,
    P8: /^Required deterministic behavior uses faithful input\/output, boundary, error and regression checks;.*never weaken authoritative expected results\./,
    P9: /^Durable evidence is repository path plus content hash, immutable artifact\/URL or inline material evidence; runtime IDs, notifications, temporary paths and task reports alone establish nothing\./,
    P10: /^Bind validation and assessment to root\/base.*tracked\/staged\/untracked.*material modes.*deletions.*manifest-lines hash/,
    P11: /^Exclude mutable plans.*Product mutation stales whole-snapshot assessment, not every check automatically; bookkeeping-only edits stale neither\. Reuse a check only when its complete relevant inputs, dependency\/configuration\/environment and freshness requirements are demonstrably unchanged; unknown applicability requires rerun\. Preserve its original execution snapshot and evidence, record applicability to the current snapshot, and rerun affected checks\..*final validation and assessment share one final snapshot/,
    P12: /^Disclose inspection\/execution owners.*never claim computations.*unless independent execution was arranged/,
    P13: /^Artifact identity, access, modality capability and evidence owner are distinct.*workers do not inherit attachments/,
    P14: /^Parent-recorded criterion-level media inspection can support Oracle assessment.*that lack alone is no blocker or extra-call reason.*Explicit independent media verification requires exact access and capability/,
    P15: /^With inaccessible media, Fixer proceeds only from independently sufficient textual\/structured requirements.*artifact-independent deterministic implementation remains allowed/,
    P16: /^Keep corpus claims separate: semantic item-level truth.*every claimed item before identical-scope automation.*exact-rule transformation.*population claims/,
    P17: /^Samples support discovery or sample-scoped claims, never unprocessed items.*Scripts, fixtures, presets, generated data, prior outputs and summaries are not corpus truth/,
    P18: /^A worker result or terminal operation does not close an objective.*failed prerequisites block only dependents/,
    P19: /^Negative\/blocked conclusions requiring material semantic inference.*separate Planning premise assessment.*Different-path controls do not prove normal outcomes/,
    P20: /^Stop unfinished work only for.*ordinary Reviewed additionally permits Review-cap non-delivery under R16\. xdev uses its progress\/recovery and settlement rules, never a lifetime Review count as a stop reason\. Neither route permits an impossibility claim, waiver of delivery requirements, route evasion or automatic contact\.$/,
    P21: /^Inspect Reviewed\/xdev background children only on completion or transport resume, never poll.*Never revive superseded work/,
    P23: /^Ordinary Reviewed tasks durably bind logical task ID plus generation before dispatch.*material conflicts fail closed/,
    P24: /^Reviewed completion requires a clear final independent delivery assessment.*zero pending work.*Before those conditions hold, the parent must not describe the Reviewed\/xdev outcome or current snapshot as done, complete or ready; report 'implemented, unassessed', 'assessment deficient' or the exact outstanding condition\. Defined task\/transport statuses and factual completed substeps are unchanged\.$/,
    V1: /^Before implementation, assign checks to iteration, milestone or final validation.*criterion, exact command\/scenario, inputs, owner, expected result, cost\/duration.*due point and rerun trigger.*broad builds, image creation and long integration suites normally wait.*not every edit, Fixer dispatch or Review correction.*may require an early expensive check.*Never weaken required final checks or expected outputs/,
    V2: /^Complete the coherent implementation\/correction batch.*Do not duplicate a check across workers and parent.*deferred, not passed, waived or a blocker.*exceeds its expected duration or yields no useful progress.*bounded diagnostics.*avoid unbounded waits.*not a pass for the required check.*not child polling/,
    I2: /^On Reviewed\/xdev, obtain or reuse source-first Oracle Planning before dependent implementation when substantive goal interpretation, architecture, strategy, decomposition or validation design remains unsettled.*Group related questions into one coherent plan.*a valid existing Oracle plan suffices, but a parent-authored design\/default alone does not settle substantive work.*routine implementations.*need no call.*not every fix\/snapshot/,
    I3: /^Technical, implementation, strategy, architecture and ordinary product\/UI choices.*Exactly three user-owned kinds exist:.*indispensable user-only access\/fact.*genuinely incompatible product-intent/,
    I4: /^Before any user question.*actual fenced matching `USER_INPUT_REQUIRED`.*current request epoch.*Only this record permits asking/,
    I5: /^For ordinary indispensable blockers, finish other feasible authorized work.*ask only when no authorized work remains ready.*Initial outcome alignment follows I7 before dependent implementation/,
    I6: /^Before dependent implementation, record objective ID\/goal revision, verbatim original basis.*non-goals, observable acceptance, material assumptions.*a clear goal proceeds without ratification or specified implementation.*outcome\/acceptance changes require authoritative instruction or clarification.*never silent drift/,
    I7: /^Initial goal clarification is one question in one user turn per objective, only for irreconcilable outcome readings after proportionate discovery and bounded intake preparation\..*at intake, before dependent implementation or long-running work.*I4 input assessment is still required.*never a menu\/questionnaire or a choice among valid implementations\..*do not reset it; only a materially replaced objective does\./,
    I8: /^Never reopen a clear goal.*neither authorizes guessing nor repeats the unchanged question.*materially new grounds or a narrower item/,
    I9: /^Only the parent emits `USER_QUESTION: <exact question>` once, verbatim/,
    A1: /^Parent preflight checks the typed core.*no requested answer, verdict, approval, preferred solution, shortlist or leaning is an input field/,
    A2: /^Supply original instructions.*without a preferred solution or shortlist.*Historical choices\/artifacts are evidence, not constraints.*Do not omit/,
    A3: /^Parent interpretations may appear only as labelled non-authoritative historical evidence.*after its own source-first framing/,
    B1: /^Oracle independently reconstructs.*before evaluating parent conclusions.*Planning originates.*simpler\/no-change/,
    B2: /^For unresolved material decisions, derive decisive levers.*exclusion reasons.*beyond the parent frame.*settled work needs basis and bounded action/,
    B3: /^Planning and Review judge necessity.*never an invented|^Planning and Review judge necessity.*advice never relaxes criteria/,
    B4: /^Actions are ordered and concrete.*Every action cites a real finding or decision/,
  },
  review: {
    R1: /^DELIVERY requires the exact complete unit.*all required validation passing on that snapshot.*only the designated Review-action todo open/,
    R2: /^STATIC\/DESIGN requires identified sources.*once per coherent unit.*never return/,
    R3: /^BLOCKED_REVIEW requires all feasible checks run.*no viable authorized in-scope remedy.*always has blocking findings/,
    R5: /^Missing\/contradictory context preventing judgment.*unestablished evidence provenance.*Cosmetic record defects/,
    R7: /^Finish accepted scope, whole corrections batch and integration.*parent self-review cannot supply independent delivery evidence/,
    R8: /^Echo assigned mode, Review ID, Unit ID and Snapshot ID verbatim.*stateRevision verbatim.*non-xdev results omit it/,
    R9: /^Preconditions status is MET or REVIEW_PRECONDITION_NOT_MET.*unmet material criteria have blocking finding IDs.*Every prior finding/,
    R10: /^Every blocking issue has a stable finding ID and current-state evidence tied to a material assigned criterion or required invariant; no demonstrated material consequence means observation\/advice, not a blocker\. Missing required material validation\/evidence or assessment preconditions is itself a material evidence failure, without needing a proven implementation bug\. Every requiredAction has a falsifiable acceptance predicate\. Deterministic claims require a mechanical predicate naming fixed inputs, a repeatable executable or rule-based static check and its expected result; where judgment is indispensable, name the authoritative criterion, concrete scenario\/evidence and observable resolving condition, and explain why a mechanical check alone is insufficient\. Oracle repairs incomplete predicates before returning; a non-conforming return is malformed, not delivery evidence, and the parent preserves it rather than inventing or weakening its predicate\./,
    R11: /^A clear delivery assessment means DELIVERY mode, met preconditions, every material criterion satisfied and no blocking finding/,
    R12: /^Decisions use the shared structured rationale.*with deficiencies allows remedy only.*clear DELIVERY allows reconcile only/,
    R13: /^Findings use.*Reuse the prior ID for the same root cause.*Allocate new IDs after the highest historical suffix/,
    R14: /^Turn the whole blocking-findings batch into one corrective contract; record optional advice dispositions without mandatory implementation\. Before every redispatch, name each prior finding's defect class \(shared failure mechanism, not instance\/location\), identify and inspect equivalent in-scope paths\/stages, and record how corrections or evidence-backed rebuttals and class-level checks cover them; justify inapplicability\..*due affected checks under V1–V2.*every required delivery check on the current snapshot by execution or P11 unchanged-input applicability\. Do not rerun expensive unaffected checks merely for another correction or dispatch\. Never interleave assessment with partial corrections\.$/,
    R15: /^On recurrence of a defect class, even under a new finding ID, or after a second deficient whole-unit delivery assessment, stabilize before redispatch\..*materially change the repair or validation mechanism.*alone is not a changed strategy\..*Recheck root causes, equivalent affected paths, induced defects and test adequacy\. Executable regressions must execute the intended path and fail with the guard\/feature disabled, isolating prior state\/retries; static\/evidence\/judgment repairs must demonstrate detection of the prior failure by repeatable comparison or criterion-grounded adverse scenario\. Recurring findings retain history\.$/,
    R16: /^Ordinary Reviewed units default to at most six DELIVERY\/BLOCKED_REVIEW dispatches; STATIC\/DESIGN, Planning, Input and Closure are not delivery calls and cannot substitute for them\. Treat six as a ceiling, not a target: R15 and P20 permit earlier proportionate unsuccessful settlement when materially distinct recovery is exhausted\. Commit expenditure before call start: preflight rejection spends none; every started DELIVERY\/BLOCKED_REVIEW call spends one, including cancelled, replacement, malformed and precondition-failed calls\. No generation\/snapshot\/rename\/sprint\/regrouping\/route change resets expenditure; replacements or overlapping\/repartitioned units retain spent history for the same unfinished outcome\. A route label alone cannot evade this allowance\. Genuine xdev escalation requires durable coordination under its route criteria, preserves complete dispatch\/finding history and follows xdev progress\/recovery rather than inheriting this lifetime numeric limit\. This allowance and extension policy does not govern xdev\..*Only the repository owner.*named ordinary Reviewed unit.*an explicit finite added allowance.*record the exact instruction, authority, unit, added allowance and resulting cumulative limit.*it changes effort only, not eligibility, findings, validation or independent assessment, and grants no user contact\..*At exhaustion without a clear delivery assessment.*unsuccessful non-delivery.*Never loop through advice\/closure.*self-approve, request an extension automatically or call the unresolved outcome impossible\.$/,
    R17: /^Assess the complete current unit.*genuine new material findings remain required.*rebuttals are not re-litigated/,
    R18: /^Bind baseline and shipping scope.*subordinate clauses.*owner\/load applicability.*reader/,
    R19: /^Compare actor, condition, prohibition and exception.*restore losses unless actual instructions authorize them/,
    R20: /^Supported coverage\/dispositions.*bounded assurance, not exhaustive equivalence.*never extra completeness Reviews/,
  },
  xdev: {
    X1: /^Resolve one exact state locator per objective.*never overwrite an existing plan/,
    X2: /^Resume reads the recorded locator before dispatch.*Existing records retain IDs, revisions, goal\/clarification history, validation, findings and complete Review history.*reconstruct changed anchor\/cadence\/recovery fields from authoritative instructions\/evidence.*never invent authority or reset history.*For 3\.0\/3\.1 records, retain policy-derived spent calls\/limits as history, not xdev stop authority; explicit user\/host constraints remain binding/,
    X5: /^Each durable semantic write increments State revision exactly once.*atomically R to N=R\+1.*Runtime-ID.*neutral/,
    X6: /^Every authorized dispatch has a pre-dispatch ledger entry.*Logical ID\/generation is identity/,
    X8: /^Todo IDs are stable and never reused.*Never silently delete\/reopen/,
    X9: /^Reconcile the complete todo list on resume.*one designated Review-action todo stays open/,
    X10: /^Outcome is active\/delivered\/conclusively blocked\/unsuccessful.*Local results never replace Outcome.*Unsuccessful records genuinely exhausted proportionate materially distinct authorized recovery under X18\/X22, not a lifetime Review count, elapsed days, technical impossibility or lack of authorization/,
    X12: /^Baseline, sprint and final checks\/scenarios record revision, snapshot, execution owner.*material raw evidence/,
    X14: /^Before ending an active root turn, reread the exact plan.*complete todo list.*automatic resume/,
    X16: /^Batch consecutive sprints sharing contract, invariants or validation.*not sprint boundaries.*preserve dispatch\/finding history.*xdev has no hard lifetime delivery-Review cap; R16's ordinary Reviewed allowance does not apply\. Continue while meaningful in-scope progress or viable materially distinct authorized recovery remains\..*record criterion or defect-class improvement, decisive new evidence or a supported next recovery action against the original-outcome anchor.*Cosmetic edits, renamed findings, new snapshots, repeated commands and narrowed goals are not progress\..*A failed causal correction or recurring class requires root-cause analysis and a materially changed repair\/validation mechanism, not an unchanged retry\. Obtain or reuse grouped Oracle recovery Planning under I2 when that substantive strategy remains unsettled; then execute through the next coherent boundary without per-edit consultations\. No fresh Review without required new correction\/evidence; optional advice creates no mandatory cycle\.$/,
    X17: /^A last\/only sprint assessment serves final whole-state assessment.*every non-closure todo satisfied/,
    X18: /^Routine active recovery needs no closure assessment.*Negative\/blocked\/unsuccessful closure.*revision-bound Oracle assessment.*Before proposing unsuccessful settlement, record supported proportionate materially distinct recovery courses, their attempted results or evidence-backed exclusions and why no viable authorized recovery remains.*finish other ready authorized work\. Review count, elapsed days, context pressure or an unchanged failed attempt do not establish exhaustion\..*identify viable materially distinct recovery or missing premise evidence as CONTINUE_REQUIRED\. It cannot prescribe unchanged repetition, waive independent delivery assessment or infer technical impossibility\.$/,
    X19: /^Before dispatch at N, atomically record candidate ID\/revision N.*Oracle reads the entire exact plan/,
    X20: /^Bind assessment to candidate ID\/revision\/proposed Outcome\/task\/generation.*Conclusions are advisory: CONTINUE_REQUIRED retains active and identifies concrete ready authorized progress\/recovery or missing settlement evidence, even after many Reviews/,
    X21: /^Atomic assessment integration.*N to N\+1.*Only a substantive premise-changing event/,
    X22: /^Delivered settlement satisfies every non-closure todo.*Unsuccessful settlement records genuinely exhausted proportionate materially distinct authorized recovery, attempted results\/evidence-backed exclusions, unresolved criteria\/findings and why no viable next recovery remains; a lifetime Review count alone never supports it\. It grants no waiver, contact or impossible-outcome claim.*exhausted-recovery basis, never falsely discharged/,
    X23: /^At delivered candidate N only the designated assessment todo may remain open.*blocked\/unsuccessful candidates.*active Outcome permits no terminal user-facing claim.*Unsuccessful settlement reports unsuccessful non-delivery \(Pi STATUS:FAILED\), never DONE or an automatic user question/,
    X24: /^Awaiting_user is execution disposition, not Outcome.*does not permit contact/,
  },
};
function rule(text, id) {
  const m = text.match(new RegExp(`^- \\*\\*${id}\\*\\* (.*)$`, "m"));
  assert.ok(m, `missing rule ${id}`);
  return flat(m[1]);
}
test("critical canonical duties and polarity controls remain load-bearing", () => {
  for (const [file, rules] of Object.entries(guards)) {
    for (const [id, pattern] of Object.entries(rules)) {
      const text = rule(files[file], id);
      assert.match(text, pattern, `${file}/${id}`);
      assert.throws(() => assert.match(`It is not true that ${text}`, pattern));
      assert.throws(() => rule(files[file].replace(`- **${id}**`, "- **REMOVED**"), id));
    }
  }
});

// F001/F002/F003/F004 repairs: each restored duty and corrected guard gets its own
// falsifiable control, so a later narrowing fails here rather than passing silently.
test("restored any-route, material-choice, dispatch-scope and clarification duties bite", () => {
  const skill = flat(files.skill);
  // F001: prompt/skill rewrites load and apply preservation on ANY route.
  const anyRoute = /For a prompt or skill rewrite on \*\*any route\*\*, the parent first reads and applies/;
  assert.match(skill, anyRoute);
  assert.match(skill, /R18–R20/);
  assert.match(skill, /not a Review requirement/);
  assert.throws(() => assert.match(skill.replace("any route", "Review dispatches only"), anyRoute));
  // F002: parent-settled material choices compare mechanism/coupling/reversibility and stress-check.
  const p7 = rule(files.skill, "P7");
  assert.match(p7, /including ones the parent settles by default without consulting Oracle/);
  assert.match(p7, /compare causal mechanisms, coupling and reversibility/);
  assert.match(p7, /stress-check the rationale under plausible evidence-supported changes in conditions/);
  assert.throws(() => assert.match(p7.replace(/compare causal mechanisms, coupling and reversibility/, ""),
    /compare causal mechanisms, coupling and reversibility/));
  assert.doesNotMatch(flat(files.op), /For material choices, compare causal mechanisms/,
    "restored duty lives in shared policy, not duplicated backend prose");
  // F003: Review submission is scoped to Review; Fixer keeps its TARGET.
  const x13 = rule(files.xdev, "X13");
  assert.match(x13, /Review adds `REVIEW_SUBMISSION v2`/);
  assert.match(x13, /Fixer dispatches use their bounded TARGET only/);
  assert.throws(() => assert.match(x13.replace("Fixer dispatches use their bounded TARGET only.", ""),
    /Fixer dispatches use their bounded TARGET only\./));
  // The broadening defect F003 named: Review submission imposed on every dispatch.
  const broadenedX13 = x13.replace("Review adds `REVIEW_SUBMISSION v2`,",
    "Every dispatch uses `REVIEW_SUBMISSION v2`,");
  assert.throws(() => assert.match(broadenedX13,
    /Oracle dispatches use `ORACLE_ASSIGNMENT v2` plus the bound record their lane requires: Review adds `REVIEW_SUBMISSION v2`/));
  // F004: I7's outcome-only condition cannot be broadened to valid implementation choices.
  const i7 = rule(files.skill, "I7");
  assert.match(i7, /only for irreconcilable outcome readings/);
  const broadened = i7.replace("only for irreconcilable outcome readings",
    "also for implementation choices with a clear goal");
  assert.throws(() => assert.match(broadened, guards.skill.I7),
    "broadening I7 to clear-goal implementation choices must fail its guard");
  assert.throws(() => assert.match("It is not true that " + i7, guards.skill.I7));

  // ANTI-LOOP-01: these control canonical wording, not runtime agent compliance.
  const weakenings = [
    ["skill", "P20", "waiver of delivery requirements", "waiver"],
    ["skill", "P24", "must not describe", "may describe"],
    ["skill", "P24", "Defined task/transport statuses and factual completed substeps are unchanged.", ""],
    ["review", "R10", "Deterministic claims require a mechanical predicate", "Deterministic claims may use any observable predicate"],
    ["review", "R10", "where judgment is indispensable", "even when judgment is unnecessary"],
    ["review", "R10", "is malformed, not delivery evidence", "is usable delivery evidence"],
    ["review", "R14", "Before every redispatch", "After the second deficient assessment"],
    ["review", "R14", "identify and inspect equivalent in-scope paths/stages", "inspect the cited instance only"],
    ["review", "R15", "On recurrence of a defect class, even under a new finding ID, or after a second", "After a second"],
    ["review", "R15", "materially change the repair or validation mechanism", "patch another instance"],
    ["review", "R15", "static/evidence/judgment repairs must demonstrate detection of the prior failure", "static/evidence/judgment repairs need no detection evidence"],
    ["review", "R16", "Only the repository owner", "Only the parent"],
    ["review", "R16", "an explicit finite added allowance", "an unlimited allowance"],
    ["review", "R16", "record the exact instruction, authority, unit, added allowance and resulting cumulative limit", "record only the new limit"],
    ["review", "R16", "No generation/snapshot/rename/sprint/regrouping/route change resets expenditure", "A new generation resets expenditure"],
    ["review", "R16", "it changes effort only, not eligibility, findings, validation or independent assessment", "it waives independent assessment"],
  ];
  for (const [file, id, before, after] of weakenings) {
    const text = rule(files[file], id);
    assert.ok(text.includes(before), `missing ${file}/${id} mutation target`);
    const weakened = text.replace(before, after);
    assert.notEqual(weakened, text);
    assert.throws(() => assert.match(weakened, guards[file][id]),
      `${file}/${id} weakening must fail its guard`);
  }
});

test("validation cadence controls costly loops without waiving final evidence", () => {
  const checks = [
    ["skill", "V1", "broad builds, image creation and long integration suites normally wait", "broad builds run after every edit"],
    ["skill", "V1", "may require an early expensive check", "never permits an early expensive check"],
    ["skill", "V1", "Never weaken required final checks or expected outputs", "Weaken required final checks"],
    ["skill", "V2", "deferred, not passed, waived or a blocker", "deferred and considered passed"],
    ["skill", "V2", "avoid unbounded waits", "wait indefinitely"],
    ["skill", "V2", "not a pass for the required check", "a pass for the required check"],
    ["skill", "P11", "complete relevant inputs, dependency/configuration/environment and freshness requirements", "changed source file only"],
    ["skill", "P11", "unknown applicability requires rerun", "unknown applicability permits reuse"],
    ["skill", "P11", "Preserve its original execution snapshot and evidence", "Replace its original execution snapshot"],
    ["review", "R14", "every required delivery check on the current snapshot by execution or P11 unchanged-input applicability", "only a cheap smoke check"],
    ["review", "R14", "Do not rerun expensive unaffected checks", "Rerun expensive unaffected checks"],
  ];
  for (const [file, id, before, after] of checks) {
    const text = rule(files[file], id);
    assert.ok(text.includes(before), `${file}/${id} control target`);
    assert.throws(() => assert.match(text.replace(before, after), guards[file][id]),
      `${file}/${id} weakening must be detected`);
  }
  for (const key of ["pf", "of"]) {
    const s = flat(files[key]);
    for (const phrase of ["checks when due", "deferred parent-owned final checks with owner/due point",
      "never as passed or waived", "Do not change check scope, cadence, acceptance",
      "missing cadence defaults to running each assigned check once at completion"])
      assert.ok(s.includes(phrase), `${key}: ${phrase}`);
  }
  assert.match(rule(files.review, "R1"), /all required validation passing.*unchanged-input applicability/);
  assert.match(rule(files.review, "R1"), /nonblocking advice has a recorded disposition, not mandatory repair/);
});

test("outcome anchor and Oracle ownership prevent intake guessing and resume drift", () => {
  const checks = [
    ["skill", "I2", "obtain or reuse source-first Oracle Planning before dependent implementation", "consult Oracle after each edit"],
    ["skill", "I2", "Group related questions into one coherent plan", "Ask each question separately"],
    ["skill", "I2", "a parent-authored design/default alone does not settle substantive work", "a parent guess settles substantive work"],
    ["skill", "I6", "non-goals, observable acceptance, material assumptions", "implementation preferences"],
    ["skill", "I6", "outcome/acceptance changes require authoritative instruction or clarification", "outcome changes require only agent preference"],
    ["skill", "I7", "at intake, before dependent implementation or long-running work", "after all independent sprints finish"],
    ["skill", "I7", "I4 input assessment is still required", "I4 input assessment is optional"],
    ["xdev", "X2", "never invent authority or reset history", "reset history on migration"],
  ];
  for (const [file, id, before, after] of checks) {
    const text = rule(files[file], id);
    assert.ok(text.includes(before));
    assert.throws(() => assert.match(text.replace(before, after), guards[file][id]));
  }
  assert.match(rule(files.skill, "I5"), /Initial outcome alignment follows I7 before dependent implementation/);
  assert.match(flat(files.skill), /actions sufficient for autonomous execution.*not a plan that depends on routine intermediate Oracle consultations/);
  assert.match(flat(files.xdev), /clear goal needs no user ratification/);
  assert.match(flat(files.pp), /original outcome\/non-goals.*before dependent long-running work/);
  for (const key of ["unit", "plan", "sprint"])
    assert.match(files[key], /[Oo]riginal-outcome anchor/);
  for (const key of ["unit", "plan"]) {
    assert.match(files[key], /Goal revision\/source history/);
    assert.match(files[key], /[Oo]racle plan\/decisions/);
    assert.match(files[key], /3\.0/);
    assert.match(files[key], /[Rr]etain.*history|identity\/history/s);
  }
});

test("delivery batches preserve materiality and route-specific recovery without self-approval", () => {
  const checks = [
    ["review", "R16", "Ordinary Reviewed units default to at most six", "Reviewed and xdev delivery units default to at most six"],
    ["review", "R16", "every started DELIVERY/BLOCKED_REVIEW call spends one", "only well-formed completed calls spend one"],
    ["review", "R16", "same unfinished outcome", "same file name"],
    ["review", "R16", "A route label alone cannot evade this allowance", "A route label resets this allowance"],
    ["review", "R16", "Genuine xdev escalation requires durable coordination under its route criteria", "Renaming the route to xdev is sufficient"],
    ["review", "R16", "This allowance and extension policy does not govern xdev", "This allowance and extension policy governs xdev"],
    ["review", "R16", "At exhaustion without a clear delivery assessment", "At exhaustion even with a clear delivery assessment"],
    ["review", "R10", "no demonstrated material consequence means observation/advice, not a blocker", "any preference is a blocker"],
    ["review", "R10", "Missing required material validation/evidence or assessment preconditions is itself a material evidence failure", "Missing validation is always optional advice"],
    ["review", "R14", "record optional advice dispositions without mandatory implementation", "implement every optional suggestion"],
    ["xdev", "X10", "not a lifetime Review count, elapsed days", "because six Reviews or multiple days elapsed"],
    ["xdev", "X18", "their attempted results or evidence-backed exclusions and why no viable authorized recovery remains", "the total Review count"],
    ["xdev", "X18", "identify viable materially distinct recovery or missing premise evidence as CONTINUE_REQUIRED", "stop after six Reviews despite viable recovery"],
    ["xdev", "X18", "It cannot prescribe unchanged repetition, waive independent delivery assessment or infer technical impossibility", "It may waive independent delivery assessment"],
    ["xdev", "X22", "a lifetime Review count alone never supports it", "a lifetime Review count alone supports it"],
    ["xdev", "X22", "never falsely discharged", "mark unfinished todos complete"],
    ["xdev", "X23", "never DONE or an automatic user question", "emit DONE"],
  ];
  for (const [file, id, before, after] of checks) {
    const text = rule(files[file], id);
    assert.ok(text.includes(before), `${file}/${id} control target`);
    assert.throws(() => assert.match(text.replace(before, after), guards[file][id]));
  }
  assert.match(rule(files.review, "R7"), /working intended end-to-end path and complete material acceptance, not fragment polish/);
  assert.match(flat(files.review), /Real in-scope security and edge-case failures still block/);
  assert.match(flat(files.review), /optional advice; that advice neither obliges another repair cycle/);
  assert.match(files.unit, /spent dispatches \/ cumulative limit \/ explicit finite extension basis/);
  for (const key of ["unit", "plan", "sprint"]) {
    assert.match(files[key], /[Oo]ptional advice disposition/);
    assert.match(files[key], /[Dd]eferred.*[Oo]wner.*[Dd]ue point/s);
  }
  assert.match(files.plan, /Outcome:\*\* active \/ delivered \/ conclusively blocked \/ unsuccessful/);
  assert.match(flat(files.pp), /six-dispatch allowance applies only to ordinary Reviewed.*xdev has no lifetime numeric Review cap/);
});

test("xdev continues distinct recovery, rejects cosmetic progress and preserves cold-resume history", () => {
  const checks = [
    ["xdev", "X16", "xdev has no hard lifetime delivery-Review cap", "xdev stops after six delivery Reviews"],
    ["xdev", "X16", "Continue while meaningful in-scope progress or viable materially distinct authorized recovery remains", "Stop once six Reviews have started"],
    ["xdev", "X16", "against the original-outcome anchor", "against a narrowed agent-defined outcome"],
    ["xdev", "X16", "Cosmetic edits, renamed findings, new snapshots, repeated commands and narrowed goals are not progress", "A new snapshot alone is progress"],
    ["xdev", "X16", "root-cause analysis and a materially changed repair/validation mechanism, not an unchanged retry", "another unchanged retry"],
    ["xdev", "X16", "Obtain or reuse grouped Oracle recovery Planning under I2 when that substantive strategy remains unsettled", "Ask Oracle after every edit"],
    ["xdev", "X16", "No fresh Review without required new correction/evidence", "Review unchanged deficiencies again"],
    ["xdev", "X18", "Review count, elapsed days, context pressure or an unchanged failed attempt do not establish exhaustion", "Six Reviews establish exhaustion"],
    ["xdev", "X20", "even after many Reviews", "unless six Reviews have started"],
    ["xdev", "X2", "retain policy-derived spent calls/limits as history, not xdev stop authority", "retain legacy limits as active xdev stop authority"],
    ["xdev", "X2", "explicit user/host constraints remain binding", "explicit user/host constraints are discarded"],
  ];
  for (const [file, id, before, after] of checks) {
    const text = rule(files[file], id);
    assert.ok(text.includes(before), `${file}/${id} control target`);
    assert.throws(() => assert.match(text.replace(before, after), guards[file][id]));
  }
  assert.match(flat(files.plan), /3\.0\/3\.1 plan.*complete Review history.*history, not xdev stop authority.*Explicit user\/host constraints remain binding/);
  assert.match(flat(files.plan), /Latest coherent-boundary progress\/recovery.*criterion\/class improvement or decisive new evidence.*failed mechanism and changed repair\/validation.*viable materially distinct next action/);
  assert.match(files.sprint, /complete dispatch history \/ inherited unit\/finding lineage/);
  for (const key of ["plan", "sprint"])
    assert.doesNotMatch(files[key], /cumulative limit|explicit finite extension|inherited spent allowance|Spent delivery-unit allowance/);
});

test("backend adapters require loading, bounded roles and read-only boundaries", () => {
  for (const key of ["pp", "op", "po", "oo", "pf", "of"])
    assert.match(files[key], /agent-review\/SKILL\.md/);
  for (const key of ["pp", "op"]) {
    const s = flat(files[key]);
    assert.match(s, /Before any Oracle dispatch/);
    assert.match(s, /never assume the working directory is the repository/);
    assert.match(s, /ORACLE_ASSIGNMENT v2.*never a shortlist or requested verdict/);
    assert.match(s, /Implement, self-review and validate locally without Oracle permission/);
    for (const route of ["Direct", "Reviewed", "xdev"]) assert.ok(s.includes(`| ${route} |`));
  }
  for (const key of ["po", "oo"]) {
    const s = flat(files[key]);
    assert.match(s, /Do not edit files, spawn agents/);
    assert.match(s, /never execute it yourself/);
    assert.match(s, /run builds\/tests\/package managers/);
    assert.match(s, /not an enforced sandbox/);
    assert.match(s, /whitelist is a limit, not a grant/);
    for (const cmd of ["git diff", "git rev-parse", "jj diff", "gh pr diff", "gh api"])
      assert.ok(s.includes(cmd));
    assert.match(s, /oracle-review-result/);
    assert.match(s, /oracle-input-assessment/);
    assert.match(s, /xdev\/SKILL\.md/);
  }
  for (const key of ["pf", "of"]) {
    const s = flat(files[key]);
    assert.match(s, /Before mutation read the entire TARGET/);
    assert.match(s, /ordinary in-scope implementation choices/);
    assert.match(s, /Never execute protected effects/);
    assert.match(s, /Documentation lookup is limited to assigned implementation needs; no open-ended research/);
    assert.match(s, /Never modify\/discharge todo checkboxes/);
    assert.match(s, /Do not broaden validation/);
    for (const status of ["IMPLEMENTED_AND_VALIDATED", "INCOMPLETE_REMEDIABLE", "BLOCKED"])
      assert.ok(s.includes(status));
  }
  assert.match(files.pp, /For pi dispatches, Oracle performs no shell execution/);
});

test("pi transport preserves exact payload semantics and diagram presentation", () => {
  const s = flat(files.pp);
  for (const marker of ["STATUS:CONTINUE <next step>", "STATUS:WAIT <pending event>",
    "STATUS:DONE", "STATUS:BLOCKED user oracle=<run-id> dependency=<dependency-id> <description>",
    "STATUS:BLOCKED external owner=<nonhuman-owner> <description>", "STATUS:FAILED <reason>"])
    assert.ok(s.includes(marker));
  for (const phrase of ["final line at column zero", "same physical line",
    "launching unstarted work is CONTINUE, not WAIT", "start nothing else while waiting",
    "Human replies require user BLOCKED", "PI_MAX_CONTINUATIONS=0", "Measure rendered width"])
    assert.ok(s.includes(phrase));
});

test("records preserve lifecycle fields and reference canonical assessment", () => {
  assert.match(files.unit, /schema_version: 3\.1/);
  for (const key of ["plan", "sprint"])
    assert.match(files[key], /schema_version:\*\* 3\.2/);
  for (const key of ["plan", "sprint"]) {
    assert.match(files[key], /agent-review\/references\/review\.md/);
    assert.match(files[key], /oracle-review-result/);
    assert.match(files[key], /snapshot/i);
  }
  for (const field of ["State revision", "Outcome", "Execution disposition", "Task Ledger",
    "Authoritative Todo List", "Initial clarification used", "Terminal Decision Record",
    "Oracle logical task ID / generation", "Todo settlement"])
    assert.ok(files.plan.includes(field));
  assert.match(files.unit, /Initial clarification|initial clarification/);
  assert.match(files.unit, /Recurring-class\/second-deficiency changed strategy/);
  assert.match(files.xdev, /oracle-closure-assessment/);
  for (const key of ["skill", "review", "xdev", "unit", "plan", "sprint"])
    assert.doesNotMatch(files[key], /REVIEW_READY|Verdict: PASS|Verdict: FAIL|"verdict"|"orchestratorBrief"/);
});

const piOracleFront = `---
name: oracle
description: Decision adviser, strategic technical advisor, and read-only code reviewer.
tools: read, grep, find, ls, bash, contact_supervisor
skills: agent-review
async: true
model: gpt-6.1-sol
thinking: xhigh
advertise: true
systemPromptMode: replace
inheritProjectContext: true
inheritGlobalContext: false
inheritSkills: true
---`;
const piFixerFront = `---
name: fixer
description: Bounded implementation specialist for clear, assigned work.
tools: read, grep, find, ls, bash, edit, write, resolve-library-id, query-docs, contact_supervisor
skills: agent-review
async: true
model: DeepSeek-V4.1-Flash
thinking: max
advertise: true
systemPromptMode: replace
inheritProjectContext: true
inheritGlobalContext: false
inheritSkills: true
---`;
const ocParentFront = `---
description: AI coding orchestrator that delegates bounded work, resolves ordinary decisions at agent level, and reconciles results.
mode: primary
model: litellm/DeepSeek-V4.1-Flash#max
---`;
const permissionFront = (description, model, editing) => `---
description: ${description}
mode: subagent
model: ${model}
permissions:
  - action: "*"
    resource: "*"
    effect: deny
  - action: read
    resource: "*"
    effect: allow
  - action: glob
    resource: "*"
    effect: allow
  - action: grep
    resource: "*"
    effect: allow
${editing ? `  - action: edit
    resource: "*"
    effect: allow
` : ""}  - action: shell
    resource: "*"
    effect: allow
---`;
test("all backend frontmatter remains byte-identical", () => {
  const expected = {
    po: piOracleFront, pf: piFixerFront, op: ocParentFront,
    oo: permissionFront("Decision adviser, strategic technical advisor, and read-only code reviewer.", "litellm/gpt-6.1-sol#max", false),
    of: permissionFront("Bounded implementation specialist for clear, assigned work.", "litellm/DeepSeek-V4.1-Flash#max", true),
  };
  for (const [key, value] of Object.entries(expected))
    assert.equal(files[key].match(/^---\n[\s\S]*?\n---/)[0], value);
});

test("backend worker bodies remain consistent except documented shell wording", () => {
  const body = (s) => s.replace(/^---\n[\s\S]*?\n---\n/, "").trim();
  assert.equal(body(files.pf), body(files.of));
  const normalize = (s) => flat(body(s)).replace(
    "Shell is for READ-ONLY inspection only, forbidden before bootstrap and unless the bound parent contract expressly permits inspection. The whitelist is a limit, not a grant:",
    "Shell is forbidden before bootstrap and unless the bound parent contract expressly permits inspection. The whitelist is a limit, not a grant. Only these commands are allowed:");
  assert.equal(normalize(files.po), normalize(files.oo));
});
