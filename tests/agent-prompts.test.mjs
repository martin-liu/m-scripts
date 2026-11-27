// Non-writing drift guards: parsed protocol examples, adverse-record scenarios,
// selected canonical obligations, backend adapters and exact frontmatter.
// These do not prove semantic equivalence, runtime loading or agent compliance.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const paths = {
  pp: "shell/config/pi/APPEND_SYSTEM.md",
  planner: "shell/config/pi/agents/planner.md",
  po: "shell/config/pi/agents/oracle.md",
  pw: "shell/config/pi/agents/worker.md",
  op: "shell/config/opencode-agents/orchestrator.md",
  oo: "shell/config/opencode-agents/oracle.md",
  of: "shell/config/opencode-agents/fixer.md",
  entry: "skills/agent-review/SKILL.md",
  execution: "shell/config/pi/agents/references/execution.md",
  coordination: "shell/config/pi/agents/references/coordination.md",
  preservation: "shell/config/pi/agents/references/prompt-preservation.md",
  advisory: "shell/config/pi/agents/references/advisory.md",
  review: "skills/agent-review/references/review.md",
  unit: "shell/config/pi/agents/templates/reviewed_unit.md",
  xdev: "skills/xdev/SKILL.md",
  plan: "skills/xdev/templates/plan_and_track.md",
  sprint: "skills/xdev/templates/sprint_block.md",
};
const files = Object.fromEntries(Object.entries(paths).map(([k, p]) => [k, read(p)]));
// The P/I/V guard set spans two references; tests below separately verify which actors load each.
files.skill = files.execution + "\n" + files.coordination;
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
  const [a, p, i] = examples(files.advisory);
  assignment(a); advisory(p); input(i);
  const [r] = examples(files.review);
  review(r, r, ["C1"]);
  assert.equal(clear(r, ["C1"]), false);
});

test("a Pi Planning handoff binds one unresolved decision; it is not a selected plan or assessment", () => {
  const records = [...files.advisory.matchAll(/^```pi-planning-handoff\n([^`]+)\n```$/gm)];
  assert.equal(records.length, 1);
  const h = JSON.parse(records[0][1]);
  keys(h, ["version", "outcome", "dependencyId", "assignmentRef", "decision", "consequence", "cheapChecks", "evidenceRefs"]);
  assert.equal(h.version, 1); assert.equal(h.outcome, "PLANNER_NEEDED");
  for (const k of ["dependencyId", "assignmentRef", "decision", "consequence"]) nonempty(h[k]);
  for (const k of ["cheapChecks", "evidenceRefs"]) { array(h[k]); assert.ok(h[k].length); h[k].forEach(nonempty); }
  assert.throws(() => advisory(h)); assert.throws(() => input(h));
  const policy = flat(files.advisory);
  assert.match(policy, /Only `oracle` assigned Planning may return.*instead of.*a completed plan/);
  assert.match(policy, /reject stale, mixed, malformed or consumed handoffs/);
  assert.match(policy, /Planner returns the ordinary plan or a concrete blocker, never a second handoff/);
  const legacy = clone(examples(files.advisory)[1]);
  legacy.nextActions[0].owner = "fixer"; advisory(legacy); // historical v2, not a Pi role to launch
  for (const owner of ["worker", "planner"]) {
    legacy.nextActions[0].owner = owner; assert.throws(() => advisory(legacy));
  }
});

test("assignments reject ballot, shortlist, missing basis and lane mismatch", () => {
  const [a] = examples(files.advisory);
  for (const mutate of [
    (v) => { v.request.verdict = "PASS"; },
    (v) => { v.basis.shortlist = ["A", "B"]; },
    (v) => { v.basis.preferredSolution = "A"; },
    (v) => { delete v.basis.contraryEvidence; },
    (v) => { v.request.kind = "assess-current"; },
    (v) => { v.identity.generation = 0; },
  ]) { const v = clone(a); mutate(v); assert.throws(() => assignment(v)); }
});

test("Oracle's v2 handoff carries the finish line independently of route and Review mode", () => {
  const [a] = examples(files.advisory);
  assignment(a);
  assert.match(a.basis.intendedOutcome, /^working: .*freshly migrated dev database/);
  const handoff = flat(files.advisory);
  assert.match(handoff, /`basis.intendedOutcome`.*`working: <observable outcome and context>` or `readiness: <candidate and decision>`/);
  assert.match(handoff, /permission in `basis.authorizations`; a request to assess does not authorize repair/);
  assert.match(handoff, /original instructions and binding policy.*not from the route, lane or Review mode/);
  assert.match(handoff, /older assignments.*clear from the bound basis.*material conflict.*parent/);
  const submission = files.review.split("REVIEW_SUBMISSION v2\n")[1].split("```\n")[0];
  assert.match(flat(submission), /CONTRACT AND CRITERIA.*`basis.intendedOutcome`.*checks due for that target/);
  const policy = flat(files.review);
  assert.match(policy, /working `DELIVERY` Review judges local acceptance and binding invariants/i);
  assert.match(policy, /`residualRisks`, not blocking findings or required `nextActions`/);
  for (const key of ["po", "oo"]) assert.match(flat(files[key]), /acceptance target in `basis.intendedOutcome`/);
});

test("intelligence rationale rejects ratification-only and anonymous advice", () => {
  const [, p] = examples(files.advisory);
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
  const [, , i] = examples(files.advisory);
  const mixed = clone(i); mixed.selectedOption = "A";
  assert.throws(() => input(mixed));
  const missing = clone(i); delete missing.whyAgentCannotResolve;
  assert.throws(() => input(missing));
  input({ version: 1, dependencyId: "D", outcome: "AGENT_DECISION",
    selectedOption: "Reversible default", rationale: "Evidence-backed",
    assumptions: [], reconsiderationTrigger: "Changed requirement" });
});

test("a missing profile can be a user input; producing the attributed comparison is agent work", () => {
  const ownership = rule(files.coordination, "I3");
  assert.match(ownership, /for a user-only input, ask only for the missing original fact, source or permitted reference/i);
  assert.match(ownership, /the agent owns the investigation and evidence write-up/i);
  assert.match(ownership, /if no user-owned input is missing, report the evidence gap rather than asking/i);
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

test("Review findings distinguish impact, coverage and regression attribution", () => {
  const guidance = flat(files.review.split("## Result\n")[1].split("\n## IDs, correction and effort")[0]);
  const check = (text) => {
    assert.match(text, /triggering condition, expected and actual behavior, and the consequence for the assigned criterion or invariant/);
    assert.match(text, /missing check or evidence, not an unobserved defect/);
    assert.match(text, /trace it from its authoritative source to affected consumers within the permitted scope/);
    assert.match(text, /passing samples establish only the cases inspected/);
    assert.match(text, /A pre-existing failure still blocks if it defeats the named target/);
    assert.match(text, /Attribute introduction or worsening to the change only with comparative evidence/);
  };
  check(guidance);
  for (const [before, after] of [
    ["only the cases inspected", "compatibility for every consumer"],
    ["only with comparative evidence", "even without comparative evidence"],
  ]) assert.throws(() => check(guidance.replace(before, after)), assert.AssertionError);
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
    P2: /^Protected effects:/, // The four effects and their recipients are checked separately below.
    P4: /^Only the parent executes protected effects with sufficient explicit authorization covering the exact effect, target and limits; reuse a still-valid grant/,
    P5: /^Broad goals, routes, advice, assessment evidence and worker contracts grant no protected authorization; missing authorization blocks only that effect/,
    P6: /^A bounded target names output\/behavior, authoritative basis, allowed scope\/non-goals, criterion IDs and observable expectations, evidence, validation owner\/commands\/cadence, material cases and invariants/,
    P8: /^Required deterministic behavior uses faithful input\/output, boundary, error and regression checks;.*never weaken authoritative expected results\./,
    P9: /^Durable evidence is repository path plus content hash, immutable artifact\/URL or inline material evidence; runtime IDs, notifications, temporary paths and task reports alone establish nothing\./,
    P10: /^For a Direct local check or iteration-only xdev feedback, report target, owner, inputs, command\/scenario, exit and observed result inline; no snapshot manifest\. Bind Reviewed validation, xdev acceptance, formal assessment, readiness and reused evidence to root\/base.*tracked\/staged\/untracked.*material modes.*deletions.*manifest-lines hash.*Rerun an unbound check on the candidate before counting it toward acceptance that requires a snapshot/,
    P11: /^Exclude mutable plans.*Product mutation stales whole-snapshot assessment, not every check automatically; bookkeeping-only edits stale neither\. Reuse a check only when its complete relevant inputs, dependency\/configuration\/environment and freshness requirements are demonstrably unchanged; unknown applicability requires rerun\. Preserve its original execution snapshot and evidence, record applicability to the current snapshot, and rerun affected checks\..*final validation and assessment share one final snapshot/,
    P12: /^Disclose inspection\/execution owners.*never claim computations.*unless independent execution was arranged/,
    P13: /^Artifact identity, access, modality capability and evidence owner are distinct.*workers do not inherit attachments/,
    P14: /^Parent-recorded criterion-level media inspection can support Oracle assessment.*that lack alone is no blocker or extra-call reason.*Explicit independent media verification requires exact access and capability/,
    P15: /^With inaccessible media, Worker proceeds only from independently sufficient textual\/structured requirements.*artifact-independent deterministic implementation remains allowed/,
    P16: /^Keep corpus claims separate: semantic item-level truth.*every claimed item before identical-scope automation.*exact-rule transformation.*population claims/,
    P17: /^Samples support discovery or sample-scoped claims, never unprocessed items.*Scripts, fixtures, presets, generated data, prior outputs and summaries are not corpus truth/,
    P18: /^A worker result or terminal operation does not close an objective.*failed prerequisites block only dependents.*On every route, completing a turn, phase, plan or readiness report is not objective completion while required in-scope work remains\. A plan\/report-only objective may complete with clearly optional or out-of-scope follow-up; never relabel required work as optional\.$/,
    P19: /^Negative\/blocked conclusions requiring material semantic inference.*separate Planning premise assessment.*Different-path controls do not prove normal outcomes/,
    P20: /^Stop unfinished work only for.*ordinary Reviewed additionally permits Review-cap non-delivery under R16\. xdev uses its progress\/recovery and settlement rules, never a lifetime Review count as a stop reason\. Neither route permits an impossibility claim, waiver of delivery requirements, route evasion or automatic contact\.$/,
    P21: /^Inspect Reviewed\/xdev background children only on completion or transport resume, never poll.*Never revive superseded work/,
    P23: /^Ordinary Reviewed tasks durably bind logical task ID plus generation before dispatch.*material conflicts fail closed/,
    P24: /^Reviewed product delivery requires a clear final independent delivery assessment.*zero pending work.*Before those conditions hold, the parent must not describe the Reviewed\/xdev product or current snapshot as done, complete or ready; report 'implemented, unassessed', 'assessment deficient' or the exact outstanding condition\. Defined task\/transport statuses and factual completed substeps are unchanged\.$/,
    V1: /^Before implementation, assign checks to iteration, milestone or final validation.*criterion, exact command\/scenario, inputs, owner, expected result, cost\/duration.*due point and rerun trigger.*broad builds, image creation and long integration suites normally wait.*not every edit, Worker dispatch or Review correction.*may require an early expensive check.*Never weaken required final checks or expected outputs/,
    V2: /^Complete the coherent implementation\/correction batch.*Do not duplicate a check across workers and parent.*deferred, not passed, waived or a blocker.*exceeds its expected duration or yields no useful progress.*bounded diagnostics.*avoid unbounded waits.*not a pass for the required check.*not child polling/,
    I2: /^On Reviewed\/xdev, obtain or reuse source-first Planning before dependent implementation when substantive goal interpretation, architecture, strategy, decomposition or validation design remains unsettled.*Group related questions into one coherent plan.*a valid existing Planning result suffices, but a parent-authored design\/default alone does not settle substantive work.*routine implementations.*need no call.*not every fix\/snapshot/,
    I3: /^Technical, implementation, strategy, architecture and ordinary product\/UI choices.*Exactly three user-owned kinds exist:.*indispensable user-only access\/fact.*genuinely incompatible product-intent/,
    I4: /^Before any user question.*actual fenced matching `USER_INPUT_REQUIRED`.*current request epoch.*Only this record permits asking, never execution or closure\. Do not defer required work behind implied or future\/conditional confirmation, readiness ratification or a go-ahead; such a dependency uses this gate just like an explicit question\.$/,
    I5: /^For ordinary indispensable blockers, finish other feasible authorized work.*ask only when no authorized work remains ready.*Initial outcome alignment follows I7 before dependent implementation/,
    I6: /^Before dependent implementation, record objective ID\/goal revision, verbatim original basis.*non-goals, observable acceptance, material assumptions.*a clear goal proceeds without ratification or specified implementation.*outcome\/acceptance changes require authoritative instruction or clarification.*never silent drift/,
    I7: /^Initial goal clarification is one question in one user turn per objective, only for irreconcilable outcome readings after proportionate discovery and bounded intake preparation\..*at intake, before dependent implementation or long-running work.*I4 input assessment is still required.*never a menu\/questionnaire or a choice among valid implementations\..*do not reset it; only a materially replaced objective does\./,
    I8: /^Never reopen a clear goal.*neither authorizes guessing nor repeats the unchanged question.*materially new grounds or a narrower item/,
    I9: /^Only the parent emits `USER_QUESTION: <exact question>` once, verbatim/,
  },
  advisory: {
    A1: /^Parent preflight checks the typed core.*no requested answer, verdict, approval, preferred solution, shortlist or leaning is an input field/,
    A2: /^Supply original instructions.*without a preferred solution or shortlist.*Historical choices\/artifacts are evidence, not constraints.*Do not omit/,
    A3: /^Parent interpretations may appear only as labelled non-authoritative historical evidence.*after its own source-first framing/,
    B1: /^The assigned adviser independently reconstructs.*before evaluating parent conclusions.*Planning originates.*simpler\/no-change/,
    B2: /^For unresolved material decisions, derive decisive levers.*exclusion reasons.*beyond the parent frame.*settled work needs basis and bounded action/,
    B3: /^Planning and Review judge necessity.*never an invented|^Planning and Review judge necessity.*advice never relaxes criteria/,
    B4: /^Actions are ordered and concrete.*Every action cites a real finding or decision/,
  },
  review: {
    R1: /^DELIVERY requires the exact complete unit.*all required validation passing on that snapshot.*only the designated Review-action todo open/,
    R2: /^STATIC\/DESIGN requires identified sources.*one usable pass per coherent unit across snapshots\/generations\. Never return to a usable pass or substitute it for delivery assessment/,
    R3: /^BLOCKED_REVIEW requires all feasible checks run.*no viable authorized in-scope remedy.*always has blocking findings/,
    R5: /^Missing\/contradictory context preventing judgment.*unestablished evidence provenance.*Cosmetic record defects/,
    R7: /^For DELIVERY, finish accepted scope, whole corrections batch and integration.*parent self-review cannot supply independent delivery evidence/,
    R8: /^Echo assigned mode, Review ID, Unit ID and Snapshot ID verbatim.*stateRevision verbatim.*non-xdev results omit it/,
    R9: /^Preconditions status is MET or REVIEW_PRECONDITION_NOT_MET.*unmet material criteria have blocking finding IDs.*Every prior finding/,
    R10: /^Every blocking issue has a stable finding ID and current-state evidence tied to a material assigned criterion or required invariant; no demonstrated material consequence means observation\/advice, not a blocker\. Missing required material validation\/evidence or assessment preconditions is itself a material evidence failure, without needing a proven implementation bug\. Every requiredAction has a falsifiable acceptance predicate\. Deterministic claims require a mechanical predicate naming fixed inputs, a repeatable executable or rule-based static check and its expected result; where judgment is indispensable, name the authoritative criterion, concrete scenario\/evidence and observable resolving condition, and explain why a mechanical check alone is insufficient\. Oracle repairs incomplete predicates before returning; a non-conforming return is malformed, not delivery evidence, and the parent preserves it rather than inventing or weakening its predicate\./,
    R11: /^A clear delivery assessment means DELIVERY mode, met preconditions, every material criterion satisfied and no blocking finding/,
    R12: /^Decisions use the shared structured rationale.*with deficiencies allows remedy only.*clear DELIVERY allows reconcile only/,
    R13: /^Findings use.*Reuse the prior ID for the same root cause.*Allocate new IDs after the highest historical suffix/,
    R14: /^For authorized repair, turn the whole blocking-findings batch into one corrective contract; record optional advice dispositions without mandatory implementation\. Before every redispatch, name each prior finding's defect class \(shared failure mechanism, not instance\/location\), identify and inspect equivalent in-scope paths\/stages, and record how corrections or evidence-backed rebuttals and class-level checks cover them; justify inapplicability\..*due affected checks under V1–V2.*every required delivery check on the current snapshot by execution or P11 unchanged-input applicability\. Do not rerun expensive unaffected checks merely for another correction or dispatch\. Never interleave assessment with partial corrections\.$/,
    R15: /^On recurrence of a defect class, even under a new finding ID, or after a second deficient whole-unit delivery assessment, stabilize before redispatch\..*materially change the repair or validation mechanism.*alone is not a changed strategy\..*Recheck root causes, equivalent affected paths, induced defects and test adequacy\. Executable regressions must execute the intended path and fail with the guard\/feature disabled, isolating prior state\/retries; static\/evidence\/judgment repairs must demonstrate detection of the prior failure by repeatable comparison or criterion-grounded adverse scenario\. Recurring findings retain history\.$/,
    R16: /^Ordinary Reviewed units default to at most six DELIVERY\/BLOCKED_REVIEW dispatches\b/,
    R17: /^Assess the complete current unit.*genuine new material findings remain required.*rebuttals are not re-litigated/,
  },
  preservation: {
    R18: /^Bind baseline and shipping scope.*subordinate clauses.*owner\/load applicability.*reader/,
    R19: /^Compare actor, condition, prohibition and exception.*restore losses unless actual instructions authorize them/,
    R20: /^Supported coverage\/dispositions.*bounded assurance, not exhaustive equivalence.*never extra completeness Reviews/,
  },
  xdev: {
    X1: /^Resolve one exact state locator per objective.*never overwrite an existing plan/,
    X2: /^Resume reads the recorded locator before dispatch.*another-objective default collision stop\/escalate.*bootstrap, migration or malformed-state recovery, read `xdev\/templates\/plan_and_track\.md` and applicable versioned templates.*search matching existing plans before creation; ambiguity or unsafe migration fails closed.*Preserve IDs, revisions, goal\/clarification history, validation, findings and complete Review history; never invent authority or reset history/i,
    X5: /^Each durable semantic write increments State revision exactly once.*atomically R to N=R\+1.*Runtime-ID.*neutral/,
    X6: /^Every authorized dispatch has a pre-dispatch ledger entry.*Logical ID\/generation is identity/,
    X8: /^Todo IDs are stable and never reused.*Never silently delete\/reopen/,
    X9: /^Reconcile the complete todo list on resume.*one designated Review-action todo stays open/,
    X10: /^Outcome is active\/delivered\/conclusively blocked\/unsuccessful.*Local results never replace Outcome.*Unsuccessful records genuinely exhausted proportionate materially distinct authorized recovery under X18\/X22, not a lifetime Review count, elapsed days, technical impossibility or lack of authorization/,
    X12: /^Iteration-only feedback needs no snapshot: return owner, inputs, command, exit and observed result inline\. It cannot discharge an acceptance check\..*for acceptance, assessment or reuse, bind revision, product snapshot, execution owner, expected\/actual, PASS\/FAIL\/BLOCKED.*material raw evidence/,
    X14: /^Before ending an active root turn, reread the exact plan.*complete todo list.*automatic resume\. A completed turn, sprint or readiness report does not establish delivered Outcome; unfinished required work or its unresolved dependencies rule out DONE\.$/,
    X16: /^Batch consecutive sprints sharing contract, invariants or validation.*not sprint boundaries.*preserve dispatch\/finding history.*xdev has no hard lifetime delivery-Review cap; R16's ordinary Reviewed allowance does not apply\. Continue while meaningful in-scope progress or viable materially distinct authorized recovery remains\..*record criterion or defect-class improvement, decisive new evidence or a supported next recovery action against the original-outcome anchor.*Cosmetic edits, renamed findings, new snapshots, repeated commands and narrowed goals are not progress\..*A failed causal correction or recurring class requires root-cause analysis and a materially changed repair\/validation mechanism, not an unchanged retry\. Obtain or reuse grouped recovery Planning under I2 when that substantive strategy remains unsettled; then execute through the next coherent boundary without per-edit consultations\. No fresh Review of a usable assessment without required new correction\/evidence; optional advice creates no mandatory cycle\. A confirmed-terminal generation with no usable result may be replaced under X7 on the unchanged eligible candidate; retain history, not a duplicate judgment\.$/,
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
  assert.match(p7, /including ones the parent settles by default without consulting an adviser/);
  assert.match(p7, /compare causal mechanisms, coupling and reversibility/);
  assert.match(p7, /stress-check the rationale under plausible evidence-supported changes in conditions/);
  assert.throws(() => assert.match(p7.replace(/compare causal mechanisms, coupling and reversibility/, ""),
    /compare causal mechanisms, coupling and reversibility/));
  assert.doesNotMatch(flat(files.op), /For material choices, compare causal mechanisms/,
    "restored duty lives in shared policy, not duplicated backend prose");
  // F003: Review submission is scoped to Review; Fixer keeps its TARGET.
  const x13 = rule(files.xdev, "X13");
  assert.match(x13, /Review adds `REVIEW_SUBMISSION v2`/);
  assert.match(x13, /Worker dispatches use their bounded TARGET only/);
  assert.throws(() => assert.match(x13.replace("Worker dispatches use their bounded TARGET only.", ""),
    /Worker dispatches use their bounded TARGET only\./));
  // The broadening defect F003 named: Review submission imposed on every dispatch.
  const broadenedX13 = x13.replace("Review adds `REVIEW_SUBMISSION v2`,",
    "Every dispatch uses `REVIEW_SUBMISSION v2`,");
  assert.throws(() => assert.match(broadenedX13,
    /Advisory dispatches use `ORACLE_ASSIGNMENT v2` plus the bound record their lane requires: Review adds `REVIEW_SUBMISSION v2`/));
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

test("Pi's complete authorization exceptions agree before any policy load; OpenCode keeps its read boundary", () => {
  const effects = [
    'mutating or disrupting staging/production or other shared operational resources, provisioning paid capacity, or exceeding a stated budget',
    'any publication or deployment, or sending data outside its permitted audience',
    'changing privileges or persistent settings that take effect user-wide or machine-wide',
    'destroying shared data, irreversibly deleting or overwriting retained data, or acting destructively on an unidentified target',
  ];
  const expected = `Protected effects: ${effects.join('; ')}.`;
  const p2 = rule(files.execution, 'P2'), p3 = rule(files.execution, 'P3');
  for (const [role, text] of [['parent', files.pp], ['Worker', files.pw], ['P2', p2]]) {
    assert.equal(text.match(/Protected effects:[^.]*\./)?.[0], expected, role);
  }
  for (const [role, prompt] of [['parent', files.pp], ['Worker', files.pw]]) {
    assert.match(prompt, /Act within the request and its access, disclosure and cost limits\. No separate authorization unless an action has a protected effect/i, role);
    assert.doesNotMatch(prompt, /staging\/production operations \(including reads\)|repo(?:sitory)? edits, local scratch writes|protected or uncertain effects\/targets/i, role);
  }
  assert.match(files.pp, /Only you execute a protected effect[^.]*grant covering its target and limits\. A missing grant blocks only that effect/);
  assert.match(files.pw, /Only the parent executes those effects, even with a grant\. Hand back that step; continue unaffected work/);
  assert.match(p2, /OpenCode additionally reserves identified staging\/production reads for its parent/);
  assert.match(p3, /In Pi, an ordinary read on existing authorized compute does not by itself require a new grant or cost check/);
  assert.match(p3, /For destructive database work, use existing project config or specific user instruction.*localhost alone is not evidence.*contrary restriction or sign of retained data.*may migrate, reset, rebuild and reseed.*without a separate grant/);
  assert.match(flat(files.of), /Never execute protected effects[^.]*even with a command or grant/);
});

test("a named source needs the configured client and actual evidence, not invented data", () => {
  assert.match(files.pp, /Give Worker the actual source, compute, limits and observation needed/);
  assert.match(files.pw, /use the named source and compute through the configured client or CLI/i);
  for (const [role, prompt] of [['parent', files.pp], ['Worker', files.pw]]) {
    assert.match(prompt, /observed result or actual error/i, role);
    assert.match(prompt, /never substitute synthetic data|synthetic data is not a substitute/i, role);
    assert.match(prompt, /don't inspect credentials or ask for sign-in before trying/i, role);
  }
  assert.match(files.pp, /only you have the configured client, retrieve the result yourself/i);
  assert.match(files.pw, /only the parent has the client, return the exact retrieval needed/i);
  assert.match(files.pw, /material cases and binding invariants/);
});

test("a fixable pre-launch rejection calls for action, not objective failure or duplicate dispatch", () => {
  const dispatch = files.pp.split("## Route and dispatch")[1].split("## When to load more")[0];
  assert.match(dispatch, /launcher confirms no child started[^.]*correct the rejected argument[^.]*dispatch the same assignment, role and lane now/i);
  assert.match(dispatch, /omit an optional override[^.]*only if the defaults preserve all required limits/i);
  assert.match(dispatch, /if launch is uncertain, reconcile before retrying/i);
});

test('only a named readiness decision binds the on-demand reference, including for a fresh reviewer', () => {
  const ref = 'agents/references/readiness.md';
  const trigger = text => flat(text.split('\n').find(line => line.includes(ref)) ?? '');
  const parent = trigger(files.pp.split('## When to load more')[1]);
  assert.match(parent, /only for a named readiness decision, read .*bind it in `policyRefs` for the corresponding reviewer/i);
  assert.match(parent, /not for working development, local `DELIVERY` or xdev Closure alone/i);
  assert.match(trigger(files.review), /only for a named readiness decision[^.]*`basis\.intendedOutcome`.*read `agents\/references\/readiness\.md`.*bound `policyRefs`/i);
  assert.match(trigger(files.execution), /only for a named readiness decision, the parent reads .*binds it for the corresponding independent assessment/i);
  assert.match(trigger(files.execution), /working Review or xdev Closure is not that trigger/i);
  for (const key of ['pw', 'planner', 'coordination', 'advisory', 'entry', 'xdev', 'unit', 'plan', 'sprint']) assert.ok(!files[key].includes(ref), `${key}: leave readiness binding to its owners`);
  for (const key of ['pp', 'op']) {
    const reviewed = files[key].split('\n').find(line => line.startsWith('| Reviewed |'));
    assert.match(reviewed, /requested readiness assessment.*material risk to the intended target.*assess and report, or make ready, as actually requested/i);
  }
  assert.match(flat(files.execution), /focused check.*requested behavior.*explicitly required checks.*not PR-ready/);
  assert.match(flat(files.xdev), /one final whole-state Review.*local acceptance.*not production readiness/);
  assert.match(flat(files.xdev), /do not open local todos for a hypothetical later release/i);
  assert.match(flat(files.review), /one grouped STATIC\/DESIGN pass.*without a delivery gate/i);
});

test("the gate follows the next action; a future claim or one unsuitable reader cannot stop unrelated work", () => {
  for (const [scenario, source, expected] of [
    ["authorized local edit", files.execution, /future release condition is not a prerequisite for development/i],
    ["edit explicitly gated", files.execution, /restriction on the current action still binds/i],
    ["keep values out of PR", files.xdev, /PR-only disclosure ban does not itself bar a permitted internal reload/],
    ["keep values out of tool output", files.xdev, /raw tool output is forbidden, never open the old plan through that tool.*same exact revision.*full reconciliation state.*no compliant view exists, leave dependent integration pending and continue independent authorized work/],
    ["not an external blocker yet", files.pp, /resumption condition.*no compliant alternative or other ready authorized work; never for future proof, one unsuitable tool/],
  ]) assert.match(flat(source), expected, scenario);
});

test('a bounded Pi Direct brief stays short when a real source restriction requires a reference', () => {
  assert.match(files.execution, /Reading a reference does not expand a bounded Pi Direct brief or change its finish line/);
  for (const id of ['P6', 'V1', 'I6']) assert.match(rule(files.execution, id), /bounded Pi Direct/i, id);
  for (const prompt of [files.pp, files.pw]) assert.match(prompt, /An exact permitted path alone needs no policy read/);
  assert.match(files.pp, /Before an advisory dispatch/); // Not every Worker dispatch.
  assert.doesNotMatch(files.pp, /Apply Review preflight before accessing restricted material or/);
});

test('xdev iteration feedback cannot stand in for assessment or reused evidence', () => {
  for (const text of [rule(files.execution, 'P10'), rule(files.xdev, 'X12'), files.plan]) {
    assert.match(text, /iteration.only/i);
    assert.match(text, /no snapshot/i);
  }
  assert.match(rule(files.execution, 'P10'), /rerun an unbound check on the candidate before counting it toward acceptance/i);
  assert.match(rule(files.xdev, 'X12'), /assessment and final validation share one final snapshot/i);
  assert.match(rule(files.xdev, 'X16'), /Apply R14 to every correction batch; R15 only for a recurring defect class or a second deficient whole-unit assessment/);
});

test('the execution reference handles a real source restriction; it does not preempt an ordinary read', () => {
  const exec = flat(files.execution);
  for (const [condition, duty] of [
    ['scope vs enforced isolation', /exact allowed source doesn't require proof of confinement\. If enforcement is required for this access, verify the actual boundary before reading/i],
    ['concrete credentials', /concrete reason to expect credentials[^.]*permitted view that omits values before they enter the model or logs/i],
    ['no safe view', /no such view exists, skip that read, not independent work/i],
    ['unknown exclusion', /recover a lost exclusion from permitted sources, not by probing[^.]*continue independent work/i],
    ['accidental read', /accidental out-of-scope read[^.]*without using or relaying its contents/i],
  ]) assert.match(exec, duty, condition);
  for (const source of [files.pp, files.pw]) {
    assert.match(source, /required confinement or concrete reason to expect credentials[^.]*execution before access/i);
    assert.match(source, /speculation alone isn't a trigger|speculation about secrets does not block/i);
  }
  assert.match(files.pp, /confirmed credential exposure.*stop the exposing action and tell the user promptly.*without repeating the value/i);
  assert.match(files.pw, /confirmed credential exposure.*stop the exposing action and alert the parent promptly without repeating the value/i);
});

test('the cold parent answers a known result, delegates discovery first and integrates partial evidence', () => {
  const core = flat(files.pp.split('## Choose the next action')[1].split('## Route and dispatch')[0]);
  assert.match(core, /report, change or operate.*working result unless readiness for a named decision is due/i);
  assert.match(core, /answer directly if the requested result is already in context/i);
  assert.match(core, /first work call is `subagent\(\{ agent: "worker", task: target \}\)`, not your own search, query, edit or test/i);
  assert.match(core, /Worker owns discovery through the focused check/i);
  assert.match(core, /partial results keep the evidence, assign the gap or take the next independent action/i);
  assert.match(core, /terminal error, fix a known cause or try a materially different permitted path; don't repeat an unchanged denial/i);
  assert.match(core, /don't repeat usable checks or consultations on unchanged grounds; required independent checks still run/i);
  assert.match(core, /for a report[^.]*not unasked repairs; for a change, repair and check; for an operation, report its outcome/i);
  assert.doesNotMatch(core, /\| Situation \| Action \||A protected check is due and known unstarted/);
});

test('a covered unstarted effect is submitted once; a receipt or an unknown grant is not a reason to resubmit', () => {
  const exec = flat(files.execution);
  for (const [condition, duty] of [
    ['covered', /due, known-unstarted protected action, submit now if the grant covers its actual effect, destination and limits even on failure/i],
    ['no predictive preflight', /don't require a sample, dry run or Planning to predict success/i],
    ['uncovered', /binding limit is unresolved, withhold only that attempt/i],
    ['bounded slice', /permitted slice proves only slice coverage; a row limit isn't a scan cap/i],
    ['uncertain receipt', /reconcile uncertain or acknowledged nonterminal submissions before retrying/i],
    ['terminal receipt', /terminal result \(success or error\) without another lookup unless evidence conflicts or independent verification is due/i],
  ]) assert.match(exec, duty, condition);
  assert.match(files.coordination, /Integrate a usable recovery plan and take its first applicable action\./);
  const failed = files.pp.split('\n').find(line => line.startsWith('| `STATUS:FAILED'));
  assert.match(failed, /unsuccessful-settlement conditions hold; name the evidence and why no authorized recovery remains\. An unattempted check is pending, not failed/);
});

test("a missing optional Review can be replaced, but cannot spin on the same failure", () => {
  const staticReview = rule(files.review, "R2");
  assert.match(staticReview, /one usable pass per coherent unit across snapshots\/generations/);
  assert.match(staticReview, /After a terminal no-result call, allow at most one unchanged replacement under P21\. If it also yields no result, change the mechanism that failed or disclose the missing feedback and continue other work\./);
  assert.match(staticReview, /Never return to a usable pass or substitute it for delivery assessment/);
});

test("local change → requested merge readiness → authorized draft PR does not authorize production changes", () => {
  const [original] = examples(files.advisory), promoted = clone(original);
  promoted.identity.goalRevision++;
  promoted.basis.originalInstructions.push("Assess merge readiness; open a draft PR for this branch, no production operations.");
  promoted.basis.intendedOutcome = "readiness: assess this branch for merge";
  promoted.basis.authorizations.push("Publish the permitted diff as a draft PR to the named repository and branch");
  assignment(promoted); // no new mode field or route needed for the new target
  assert.match(flat(files.xdev), /changes to readiness for a named decision, add only the checks due for that decision; retain history and reuse applicable bound evidence/);
  const readiness = flat(read('shell/config/pi/agents/references/readiness.md'));
  assert.match(readiness, /later rollout gate is not a merge requirement/i);
  assert.match(readiness, /failed required check means not ready; missing proof means readiness is not demonstrated/i);
  assert.match(readiness, /assessing does not authorize fixing, publishing, deploying or changing production/i);
  assert.match(flat(files.review), /failed required check supports \*\*not ready\*\*; missing required proof supports \*\*readiness not demonstrated\*\*.*without editing.*affirmative readiness claim requires clear DELIVERY/);
  assert.match(flat(files.coordination), /finish the report.*does not deliver the product, authorize repair or close a separate open implementation objective/);
  const [local] = examples(files.review);
  local.criteria = [{ id: "local", status: "satisfied", evidenceRefs: ["dev-test"], findingIds: [] }];
  local.preconditions.status = "MET"; local.findings = []; local.nextActions = [];
  review(local, local, ["local"]);
  assert.equal(clear(local, ["local"]), true);
  assert.equal(clear(local, ["local", "merge-check"]), false, "a locally clear result isn't merge evidence");
  assert.match(readiness, /grant for its actual effect and destination; a staging grant does not cover a production write/i);
});

test("xdev reconciles a returned assessment on cold resume without replaying it or starting a competing writer", () => {
  const candidate = { mode: "DELIVERY", reviewId: "rev-2", unitId: "api", snapshotId: "tree-a", stateRevision: 8 };
  const checkpoint = JSON.stringify({ candidate, todo: "integrate-rev-2", pendingCheck: "staging-validation" });
  const returned = { ...examples(files.review)[0], ...candidate };
  // Separate resume input: reconcile against the durable binding, not the notification.
  const resumed = JSON.parse(checkpoint);
  review(returned, resumed.candidate, ["C1"]);
  assert.throws(() => review(returned, { ...resumed.candidate, stateRevision: 9 }, ["C1"]));
  assert.throws(() => review({ ...returned, reviewId: "rev-1" }, resumed.candidate, ["C1"]));
  assert.match(rule(files.xdev, "X3"), /task generations\/status and integration, complete todos, prior findings, evidence and next due check/);
  assert.match(rule(files.xdev, "X21"), /N to N\+1.*match the current candidate\/revision\/task\/generation and do not integrate an already settled result twice/);
  assert.match(rule(files.skill, "P21"), /missing dispatch receipt is not proof of termination.*never start a competing writer/);
  assert.match(flat(files.review), /do not repeat a usable assessment for advice or unchanged evidence.*confirmed-terminal call with no usable result may be replaced on the same eligible candidate.*retaining history and expenditure/);
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
  const piWorker = flat(files.pw);
  assert.match(piWorker, /Run checks at assigned iteration\/milestone\/final cadence, by default once at completion/);
  assert.match(piWorker, /never change scope, acceptance/);
  assert.match(piWorker, /Keep required evidence and expectations intact/);
  const deferred = /Report deferred parent-owned checks with owner\/due point, never as passed or waived/;
  assert.match(piWorker, deferred);
  assert.doesNotMatch(piWorker.replace("never as passed or waived", "as passed"), deferred);

  const fixer = flat(files.of);
  for (const phrase of ["checks when due", "deferred parent-owned final checks with owner/due point",
    "never as passed or waived", "Do not change check scope, cadence, acceptance",
    "missing cadence defaults to running each assigned check once at completion"])
    assert.ok(fixer.includes(phrase), `of: ${phrase}`);
  assert.match(rule(files.review, "R1"), /all required validation passing.*unchanged-input applicability/);
  assert.match(rule(files.review, "R1"), /nonblocking advice has a recorded disposition, not mandatory repair/);
});

test("outcome anchor and Planning ownership prevent intake guessing and resume drift", () => {
  const checks = [
    ["skill", "I2", "obtain or reuse source-first Planning before dependent implementation", "consult Oracle after each edit"],
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
  assert.match(flat(files.advisory), /actions sufficient for autonomous execution.*not a plan that depends on routine intermediate consultations/);
  assert.match(flat(files.xdev), /clear goal needs no user ratification/);
  assert.match(files.pp, /Resolve indispensable outcome ambiguity before dependent long-running work/);
  assert.match(files.pp, /Compare milestones and resumed work with the original outcome, not a narrowed substitute/);
  for (const key of ["unit", "plan", "sprint"])
    assert.match(files[key], /[Oo]riginal-outcome anchor/);
  assert.match(files.unit, /Goal revision\/source history/);
  assert.match(files.plan, /sources for authoritative goal revisions only, not work iterations/);
  for (const key of ["unit", "plan"]) {
    assert.match(files[key], /Planning result\/decisions/);
    assert.match(files[key], /3\.0/);
    assert.match(files[key], /[Rr]etain.*history|identity\/history/s);
  }
});

test("delivery batches preserve materiality and route-specific recovery without self-approval", () => {
  // Check the decisions independently; an editorial change between clauses is immaterial.
  const limit = rule(files.review, "R16");
  for (const [obligation, before, after] of [
    [guards.review.R16, "Ordinary Reviewed", "Reviewed and xdev"],
    [/preflight rejection spends none; every started DELIVERY\/BLOCKED_REVIEW call spends one/, "every started", "only a successful"],
    [/No generation\/snapshot\/rename\/sprint\/regrouping\/route change resets expenditure/, "No generation", "A generation"],
    [/retain spent history for the same unfinished outcome/, "same unfinished outcome", "same file name"],
    [/route label alone cannot evade/, "cannot evade", "resets"],
    [/xdev escalation requires durable coordination/, "requires durable coordination", "only requires renaming"],
    [/allowance and extension policy does not govern xdev/, "does not govern", "governs"],
    [/Only the repository owner, or a human explicitly designated by that owner/, "Only the repository owner", "Only the parent"],
    [/named ordinary Reviewed unit[^.]*explicit finite added allowance/, "explicit finite", "unlimited"],
    [/record the exact instruction, authority, unit, added allowance and resulting cumulative limit/, "instruction, authority, unit, added allowance and resulting cumulative limit", "new limit only"],
    [/changes effort only, not eligibility, findings, validation or independent assessment/, "not eligibility", "and waives eligibility"],
    [/exhaustion without a clear delivery assessment[^.]*unsuccessful non-delivery/, "without a clear", "even with a clear"],
  ]) {
    assert.match(limit, obligation);
    assert.doesNotMatch(limit.replace(before, after), obligation, after);
  }
  for (const obligation of [
    /STATIC\/DESIGN, Planning, Input and Closure are not delivery calls and cannot substitute/,
    /ceiling, not a target[^.]*earlier proportionate unsuccessful settlement when materially distinct recovery is exhausted/,
    /Commit expenditure before call start/, /including cancelled, replacement, malformed and precondition-failed calls/,
    /preserves complete dispatch\/finding history/, /grants no user contact/,
    /Never loop through advice\/closure[^.]*self-approve, request an extension automatically or call the unresolved outcome impossible/,
  ]) assert.match(limit, obligation);
  const checks = [
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
  for (const key of ["unit", "plan"]) assert.match(files[key], /[Oo]ptional advice disposition/);
  for (const key of ["unit", "plan", "sprint"]) assert.match(files[key], /[Dd]eferred.*[Oo]wner.*[Dd]ue point/s);
  assert.match(files.plan, /Outcome:\*\* active \/ delivered \/ conclusively blocked \/ unsuccessful/);
  assert.match(files.pp, /Ordinary Reviewed uses R16; xdev continues meaningful progress or materially distinct recovery.*never a lifetime Review cap/);
});

test("xdev continues distinct recovery, rejects cosmetic progress and preserves cold-resume history", () => {
  const checks = [
    ["xdev", "X16", "xdev has no hard lifetime delivery-Review cap", "xdev stops after six delivery Reviews"],
    ["xdev", "X16", "Continue while meaningful in-scope progress or viable materially distinct authorized recovery remains", "Stop once six Reviews have started"],
    ["xdev", "X16", "against the original-outcome anchor", "against a narrowed agent-defined outcome"],
    ["xdev", "X16", "Cosmetic edits, renamed findings, new snapshots, repeated commands and narrowed goals are not progress", "A new snapshot alone is progress"],
    ["xdev", "X16", "root-cause analysis and a materially changed repair/validation mechanism, not an unchanged retry", "another unchanged retry"],
    ["xdev", "X16", "Obtain or reuse grouped recovery Planning under I2 when that substantive strategy remains unsettled", "Ask Oracle after every edit"],
    ["xdev", "X16", "No fresh Review of a usable assessment without required new correction/evidence", "Review unchanged deficiencies again"],
    ["xdev", "X16", "confirmed-terminal generation with no usable result", "still-active reviewer"],
    ["xdev", "X18", "Review count, elapsed days, context pressure or an unchanged failed attempt do not establish exhaustion", "Six Reviews establish exhaustion"],
    ["xdev", "X20", "even after many Reviews", "unless six Reviews have started"],
  ];
  for (const [file, id, before, after] of checks) {
    const text = rule(files[file], id);
    assert.ok(text.includes(before), `${file}/${id} control target`);
    assert.throws(() => assert.match(text.replace(before, after), guards[file][id]));
  }
  // Ordinary resume uses the live plan; setup-only details remain reachable on the exceptional paths.
  assert.match(rule(files.xdev, "X3"), /Ordinary resume reads the live plan, not template prose:.*original outcome.*task generations\/status and integration.*prior findings.*next due check.*`xdev\/templates\/sprint_block.md` when creating or updating a sprint/);
  assert.doesNotMatch(files.xdev, /non-alphanumeric|For a 3\.0\/3\.1 plan/i);
  const setup = flat(files.plan.split("## Goal")[0]);
  assert.match(setup, /trim and lowercase.*non-alphanumeric characters with one hyphen.*trim leading and trailing hyphens/);
  assert.match(setup, /reconstruct changed anchor\/cadence\/recovery fields from authoritative instructions and evidence before dependent work/);
  assert.match(setup, /3\.0\/3\.1 plan.*retain policy-derived spent calls\/limits as history, not xdev stop authority.*Explicit user\/host constraints remain binding.*preserve the complete Review history/i);
  assert.match(flat(files.plan), /Recovery, if needed:.*criterion\/class improvement or decisive new evidence.*failed mechanism, changed repair\/check, remaining alternatives and next action/);
  assert.match(files.plan, /Preserve complete dispatch\/finding lineage/);
  for (const key of ["plan", "sprint"])
    assert.doesNotMatch(files[key], /cumulative limit|explicit finite extension|inherited spent allowance|Spent delivery-unit allowance/);
});

test("first-principles reminders stay explicit, grounded and within role boundaries", () => {
  const reminders = [
    ["skill", /Apply first-principles thinking throughout assigned work: start from the requested outcome, verified facts and binding constraints; distinguish assumptions from facts and reason about causal mechanisms, not habit or analogy alone\./],
    ["planner", /Use first-principles thinking \(P7\): test the premise and causal mechanism against the simplest sufficient alternative, including no change\. User-mandated designs are binding constraints; prior advice is not\./],
    ["po", /Use first-principles thinking \(P7\): derive expectations from original instructions and binding constraints before testing the author's conclusions against evidence\. Prefer the simplest sufficient course\./],
    ["oo", /Use first-principles thinking in every lane: start from the original outcome, verified facts and binding constraints; distinguish assumptions from facts and judge causal mechanisms rather than merely endorsing the parent's framing\. This reasoning remains within your read-only advisory role\./],
    ["pw", /Use first-principles thinking \(P7\): choose the simplest sufficient method within the TARGET's binding constraints\. Repair causes, not symptoms\. Report evidence contradicting the TARGET; never change scope, acceptance/],
    ["of", /Use first-principles thinking throughout implementation, debugging and validation: reason from the TARGET's intended behavior, verified facts, binding constraints and causal mechanisms; within assigned scope, repair causes rather than merely hiding symptoms\. Report contradicted contract assumptions to the parent; do not change the contract or take over Planning\./],
    ["xdev", /Apply P7's first-principles thinking throughout xdev: choose the simplest sufficient course from the original outcome, evidence and binding constraints\. On resume and recovery, revisit changed assumptions and reuse still-supported plans under I2\./],
  ];
  for (const [key, pattern] of reminders) {
    const text = key === "skill" ? rule(files.skill, "P7") : flat(files[key]);
    assert.match(text, pattern, key);
    for (const [before, after] of [
      ["first-principles thinking", "habit-based thinking"],
      ["binding constraints", "optional constraints"],
      ["first-principles thinking", "no first-principles thinking"],
    ]) {
      assert.ok(text.includes(before));
      assert.throws(() => assert.match(text.replace(before, after), pattern), `${key}: ${after}`);
    }
  }
});

test("first-principles balance rejects both speculative complexity and insufficient shortcuts", () => {
  const balance = /^Avoid both overengineering and oversimplification: choose the simplest sufficient solution,/;
  const preservation = /preserving required behavior, material failure handling and maintainability\./;
  // Pi role cues apply the same mandatory P7 balance; OpenCode retains its local wording.
  for (const key of ["planner", "po", "pw", "xdev"]) {
    const cue = flat(files[key].split(/\n\s*\n/).find((p) => p.includes("first-principles thinking")) ?? "");
    for (const phrase of ["P7", "simplest sufficient", "binding constraints"]) {
      assert.ok(cue.includes(phrase), `${key}: ${phrase}`);
    }
    assert.ok(files[key].includes("agents/references/execution.md"), `${key} must load P7`);
  }
  for (const key of ["oo", "of"]) {
    const reminder = flat(files[key].match(/^Avoid both overengineering[^\n]*\n[^\n]*/m)?.[0] ?? "");
    assert.match(reminder, balance, key);
    assert.match(reminder, preservation, key);
    for (const [before, after, pattern] of [
      ["both overengineering and oversimplification", "overengineering only", balance],
      ["both overengineering and oversimplification", "oversimplification only", balance],
      ["simplest sufficient solution", "fewest-lines solution", balance],
      ["preserving required behavior", "omitting required behavior", preservation],
    ]) {
      assert.ok(reminder.includes(before));
      assert.throws(() => assert.match(reminder.replace(before, after), pattern));
    }
  }
  const p7 = rule(files.skill, "P7");
  const sufficiency = /Avoid both overengineering and oversimplification: choose the simplest sufficient solution\./;
  const proportionality = /Complexity must earn its cost through concrete requirements or evidence; fewer lines or layers never justify omitting required behavior, material failure handling or maintainability\./;
  assert.match(p7, sufficiency);
  assert.match(p7, proportionality);
  assert.throws(() => assert.match(p7.replace("both overengineering and oversimplification", "overengineering only"), sufficiency));
  for (const [before, after] of [
    ["must earn its cost", "needs no justification"],
    ["never justify omitting", "justify omitting"],
  ]) assert.throws(() => assert.match(p7.replace(before, after), proportionality));
  assert.match(p7, /preserve correctness, security, integrity, operational invariants and manageable lifetime maintenance/);
  assert.match(p7, /reuse only when assumptions fit/);
  assert.match(p7, /Add no abstraction, optimization, refactoring or hardening without requirements\/evidence/);
});

test("the advisory contract is bound by parents and read by advisers, not execution workers", () => {
  const ref = paths.advisory.slice("shell/config/pi/".length);
  assert.match(flat(files.skill), /The parent reads `agents\/references\/advisory.md` before dispatching, integrating or reusing advice or assessments, including on resume\. Bind it in each advisory assignment; the adviser reads that exact reference in every lane\. Execution TARGETs need no advisory reference/);
  for (const key of ["pp", "op"]) assert.ok(flat(files[key]).includes(`read and bind \`${ref}\``), key);
  for (const key of ["planner", "po", "oo"]) assert.ok(flat(files[key]).includes(`\`agents/references/coordination.md\` and \`${ref}\``), key);
  assert.equal(examples(files.skill).length, 0);
  assert.doesNotMatch(files.skill, /^```pi-planning-handoff/m);
  for (const key of ["pw", "of"]) assert.ok(!files[key].includes(ref), key);
});

test("both hosts use managed references without installing a separate policy directory", () => {
  const links = read("shell/config.sh").split("_M_CONFIG_LINKS=(")[1].split("\n)")[0];
  assert.ok(links.includes('"$DIR/shell/config/pi/agents|$HOME/.pi/agent/agents"'));
  assert.doesNotMatch(links, /agent-prompts/);
  for (const [name, text] of Object.entries(files)) assert.doesNotMatch(text, /\bagent-prompts\//, name);
});

test("agent-review ships only the formal Review protocol; execution roles never load the package", () => {
  const dir = new URL("../skills/agent-review/", import.meta.url);
  const docs = readdirSync(dir, { recursive: true }).filter(name => name.endsWith(".md")).sort();
  assert.deepEqual(docs, ["SKILL.md", "references/review.md"]);
  for (const [key, text] of Object.entries(files)) {
    for (const [, ref] of text.matchAll(/`(agents\/(?:references|templates)\/[\w/-]+\.md)`/g)) assert.ok(read("shell/config/pi/" + ref).trim(), `${key}: ${ref}`);
  }
  for (const doc of docs) assert.doesNotMatch(read("skills/agent-review/" + doc), /^- \*\*(?:[PIVAB]\d+|R(?:18|19|20))\*\*/m);
  for (const key of ["pw", "planner", "of", "execution", "preservation"]) assert.doesNotMatch(files[key], /agent-review\//, key);
});

test("Review is opt-in; execution, contact, recovery and prompt preservation are not", () => {
  assert.match(files.entry, /^description: Prepare, perform or integrate a formal independent Review of a bound unit\. Not for ordinary implementation, planning, self-checks or repairs\.$/m);
  for (const key of ["pw", "planner", "of", "execution", "xdev", "unit", "plan", "preservation"]) {
    assert.doesNotMatch(files[key], /agent-review\/SKILL\.md/);
  }
  for (const key of ["pp", "op"]) assert.match(flat(files[key]), /Only for a formal Review, read and bind `agent-review\/SKILL.md` and `agent-review\/references\/review.md` before dispatch, integration or reuse/);
  assert.match(flat(files.pp), /approved absolute paths and hashes in the Review assignment; omit `options\.skill`/);
  assert.match(flat(files.po), /Only for a formal Review, also read `agent-review\/SKILL.md` and `agent-review\/references\/review.md`/);
  assert.match(flat(files.oo), /`agent-review\/SKILL.md` and `agent-review\/references\/review.md` only for a formal Review/);
  assert.match(flat(files.execution), /before entering Reviewed\/xdev, preparing, integrating or reusing advice or assessments, deciding whether ambiguity or another dependency requires user input, waiting, recovery, resume or stopping unfinished work/);
  assert.match(flat(files.execution), /For a prompt or skill rewrite on \*\*any route\*\*, the parent first reads and applies `agents\/references\/prompt-preservation.md`.*supplies that procedure and its bound evidence in assignments/);
  assert.match(flat(files.execution), /Missing or unreadable required policy stops dependent work/);
  assert.match(flat(files.coordination), /Only when preparing, performing, integrating or reusing a formal Review, read `agent-review\/SKILL.md`/);
  assert.match(flat(files.execution), /stale assignment whose bound prompt moved, the parent must reissue the applicable paths and revisions before dependent work; advisers also need the bound coordination and advisory prompts/);
  // Verify placement, not just the union of rule text: a Worker does not read coordination.
  const ids = (s) => [...s.matchAll(/^- \*\*(\w+\d+)\*\*/gm)].map(m => m[1]);
  assert.deepEqual(ids(files.execution), [...Array.from({ length: 19 }, (_, i) => `P${i + 1}`), "V1", "V2", "I1", "I6"]);
  assert.deepEqual(ids(files.coordination), ["P20", "P21", "P22", "P23", "P24", "I2", "I3", "I4", "I5", "I7", "I8", "I9"]);
  assert.deepEqual(ids(files.preservation), ["R18", "R19", "R20"]);
});

test('ordinary Pi Direct needs no broad read; specialist triggers are visible to each recipient', () => {
  const triggers = ['a protected effect or a concrete indication that the target/effect could be protected', 'restricted sources/disclosure or required isolation',
    'attachments/media or corpus claims (including P19)', 'prompt/skill rewrites', 'evidence reuse/readiness', 'Reviewed/xdev'];
  for (const [key, start, end] of [['pp', '**Execution:**', '**Coordination:**'], ['pw', 'Check the actual work', 'Outside that shortcut']]) {
    const list = files[key].split(start)[1].split(end)[0]; // No union with sources this recipient might never load.
    for (const trigger of triggers) assert.ok(list.includes(trigger), `${key}: missing ${trigger}`);
  }
  assert.match(files.pp, /parent and Worker prompts suffice for ordinary Direct work/);
  assert.match(files.pp, /routine Direct result or a confirmed-live Direct wait with automatic wake needs no policy read/);
  assert.match(files.pw, /explicitly identified as Direct in the TARGET, use this role and the TARGET alone unless a trigger or explicit policy requirement applies/);
  assert.match(files.pw, /complete, attributable, current content already available to \*\*you\*\*; otherwise read it before dependent work/i);
  assert.match(files.execution, /only for the default Pi parent with its managed append and the managed Pi Worker/);
  assert.match(files.execution, /OpenCode and advisory roles keep their full loading duties/);
  assert.match(rule(files.execution, 'P6'), /For bounded Pi Direct.*applicable policy binding.*assigned check suffice without separate IDs/);
  assert.match(rule(files.execution, 'V1'), /Worker runs the focused check and any other required checks at completion unless specified otherwise; no separate cost or cadence worksheet/);
  assert.match(rule(files.execution, 'I6'), /original request in conversation and the bounded TARGET stand instead of these intake fields or a separate paraphrase/);
});

test("Pi applies the actual protected-path restriction before launching or withholding Review", () => {
  assert.match(files.pp, /Use Review preflight for that assessment \(including a test of Review capability\) before inspecting its restricted inputs or deciding whether it can run/);
  const preflight = flat(files.review.split('## Pi parent: Review preflight')[1].split('## Modes and eligibility')[0]);
  for (const [scenario, rule] of [
    ["write ban alone", /A write ban does not block an otherwise authorized read-only Review or grant permission to read or disclose/],
    ["no reads", /exclude the paths and their contents from the assignment and inherited context.*inspect only the bound, permitted sources/],
    ["enforced exclusion", /must be technically unreachable, verify the enforced boundary for the actual child before launch.*Neither a prompt, fresh context, read-only tools nor a separate worktree proves isolation/],
    ["eligible Review", /Dispatch the eligible Review once all restrictions are met and permitted evidence covers the full requested scope/],
    ["blocked Review", /name the controlling restriction and missing boundary or evidence; continue other authorized work without narrowing the Review/],
    ["capability only", /authorized non-sensitive fixture under the same restrictions.*not as a project Review.*skipped launch leaves capability untested, not failed/],
  ]) assert.match(preflight, rule, scenario);
});

test("backend adapters require loading, bounded roles and read-only boundaries", () => {
  for (const key of ["pp", "op", "planner", "po", "oo", "pw", "of"])
    assert.match(files[key], /agents\/references\/execution\.md/);
  for (const key of ["pp", "op"]) {
    const s = flat(files[key]);
    assert.match(s, key === "pp" ? /Before an advisory dispatch or integration\/reuse of advice, read and bind `agents\/references\/advisory.md`/ : /Before any Oracle dispatch/);
    assert.match(s, /never assume the working directory is the repository/i);
    assert.match(s, /ORACLE_ASSIGNMENT v2.*never a shortlist or requested verdict/);
    assert.match(s, key === "pp"
      ? /integrate and self-review without adviser permission: verify coverage and material claims without redoing the task/
      : /Implement, self-review and validate locally without Oracle permission/);
    for (const route of ["Direct", "Reviewed", "xdev"]) assert.ok(s.includes(`| ${route} |`));
  }
  for (const key of ["planner", "po"]) {
    const s = flat(files[key]);
    assert.match(s, /no shell, edits, check execution or delegation/);
    assert.match(s, /Tool allowlists are not an OS sandbox/);
    assert.match(s, /never execute or authorize protected effects/);
  }
  assert.match(flat(files.advisory), /Never delegate, execute validation, edit state, ask the user, approve delivery or emit lifecycle markers/);
  const oc = flat(files.oo);
  for (const phrase of ["Do not edit files, spawn agents", "never execute it yourself", "run builds/tests/package managers",
    "not an enforced sandbox", "whitelist is a limit, not a grant", "git diff", "git rev-parse", "jj diff", "gh pr diff", "gh api"])
    assert.ok(oc.includes(phrase), phrase);
  for (const key of ["po", "oo"]) {
    for (const phrase of ["oracle-review-result", "oracle-input-assessment", "xdev/SKILL.md"])
      assert.ok(files[key].includes(phrase), phrase);
  }
  for (const key of ["pw", "of"]) {
    const s = flat(files[key]);
    if (key === "of") {
      assert.match(s, /Before target-dependent inspection, validation or mutation read the entire TARGET/);
      assert.match(s, /ordinary in-scope implementation choices/);
      assert.match(s, /Documentation lookup is limited to assigned implementation needs; no open-ended research/);
      assert.match(s, /Never modify\/discharge todo checkboxes/);
    } else {
      assert.match(s, /Deliver the TARGET, including discovery and its focused check/);
      assert.match(s, /Outside that shortcut, use the exact managed `agents\/references\/execution.md` and applicable policies bound by path and revision in the TARGET/);
      assert.match(s, /choose the simplest sufficient method within the TARGET's binding constraints/);
      assert.match(s, /read-only assignment means no edits, generated files or unrequested experiments/);
      assert.match(s, /Never edit lifecycle records or discharge todos/);
    }
    assert.match(s, key === 'of' ? /Never execute protected effects/ : /Only the parent executes those effects, even with a grant/);
    assert.match(s, /Do not broaden validation/);
    for (const status of [key === "of" ? "IMPLEMENTED_AND_VALIDATED" : "COMPLETED", "INCOMPLETE_REMEDIABLE", "BLOCKED"])
      assert.ok(s.includes(status));
  }
  assert.match(files.pp, /Neither adviser executes shell commands or grants permission/);
});

test("Pi launches independent Workers before waiting, but not at the expense of isolation or context", () => {
  const prompt = flat(files.pp), coordination = flat(files.coordination);
  assert.match(prompt, /handoff and integration costs justify it, launch one Worker per independently verifiable deliverable before waiting; don't split dependent work by file or step/);
  assert.match(prompt, /Read execution and `agents\/references\/coordination.md` before parallel\/long dispatch/);
  assert.match(coordination, /readers can share stable inputs, even in a dirty checkout/i);
  assert.match(coordination, /concurrent writers on a clean source, use `worktree: true`/i);
  assert.match(coordination, /dirty source, serialize writers unless each can use a distinct already-provisioned checkout containing the intended bytes/i);
  assert.match(coordination, /do not commit or stash just to fan out.*verify its checkout path and starting inputs/i);
  assert.match(coordination, /Assign separate ports, test databases and output paths where needed\. If isolation is uncertain, serialize the affected work\. Only you integrate results and write lifecycle records/);
  assert.match(prompt, /self-contained assignment; include applicable non-goals, invariants, contrary evidence, decisions and failures\. Don't assume inherited chat, tools or attachments/);
  assert.match(prompt, /For Reviewed bind the unit path\/hash; for xdev the exact plan path\/revision.*child-readable immutable copy of permitted material/);
});

test("Worker budgets cover a verifiable slice; a checkpoint or timeout does not close the objective", () => {
  assert.match(files.pp, /Read execution and `agents\/references\/coordination.md` before parallel\/long dispatch/);
  const parent = flat(files.coordination.split('## Pi parent: parallel work, long runs and recovery')[1]), worker = flat(files.pw);
  assert.match(files.pp, /pushed blocking request from a live child needs a reply, not another wait/i);
  assert.match(parent, /blocking supervisor request.*replyTo: requestId.*permitted facts or an in-scope decision.*same child to return partial work.*not a new dispatch, WAIT or user escalation/i);
  assert.match(parent, /30-minute default.*whole run, not idle time.*deadline and its checkpoint timer both pause.*resume when the blocking call ends.*headless parent's wait is separate/);
  assert.match(parent, /split oversized work at verifiable handoff points/);
  assert.match(parent, /indivisible.*options\.timeoutMs.*expected duration plus setup and handoff/);
  assert.match(parent, /options\.checkpointBeforeDeadlineMs.*best-effort.*not an extension/);
  assert.match(parent, /timeout ends the child run, not the objective.*confirm the previous writer stopped before replacement/);
  assert.match(parent, /only the unfinished scope.*do not retry the same scope and budget unchanged/);
  assert.match(worker, /deadline checkpoint.*start no new work.*INCOMPLETE_REMEDIABLE.*unchecked criteria/);
});

test("the default agent answers immediate questions and delegates bounded work without duplication", () => {
  const prompt = flat(files.pp), followup = flat(files.coordination);
  assert.match(prompt, /You are the orchestrator, Pi's default agent, not a subagent/);
  assert.match(prompt, /choose the route from the requested outcome and known scope before dispatch or mutation/i);
  assert.match(prompt, /unknown filename, cause or implementation belongs in the Worker assignment/i);
  assert.doesNotMatch(files.pp, /non-mutating inspection needed to establish scope|non-mutating discovery may precede it/i);
  assert.match(prompt, /Don't duplicate a child's task; do other ready authorized work/);
  assert.match(prompt, /verify coverage and material claims without redoing the task\. Partial coverage is not completion/);
  assert.match(prompt, /coordination.md` before parallel\/long dispatch, nonroutine follow-up, recovery\/resume/);
  assert.match(followup, /only the parent can retrieve a missing authorized source, pass the material to Worker for analysis and credit retrieval accurately/);
  assert.match(followup, /same-task follow-up, use the eligible, non-superseded Worker run by ID if supported\. Send only the gap and what it needs: new material and relevant accepted evidence, inline or at child-readable references/);
  assert.match(followup, /If the prior run can't be used, reconcile under P21 before giving a fresh Worker a self-contained TARGET for just the gap\. Independent assessments always start fresh/);
  assert.match(followup, /Only if inline recovery is necessary, name one authorized action and its exit condition/);
  assert.match(flat(files.pw), /Missing required coverage is not completion/);
  assert.match(followup, /reconcile partial work.*confirm the previous writer stopped before replacement/);
  assert.match(followup, /next safe, separable unit goes back to Worker unless the same concrete blocker still applies/);
  assert.match(files.pp, /^\| Direct \| Bounded work with understood coupling, an observable outcome and a focused check\. Conversation TARGET; Worker by default, no strategic Planning or final Review/m);
});

test("a routine code change goes to one Worker, not inline or through Planning", () => {
  const routing = flat(files.pp);
  assert.match(routing, /if delegation is forbidden, do the work yourself/i);
  assert.match(routing, /If `subagent` is unavailable, call `subagents_enable\(\{\}\)` once if offered, then launch/i);
  assert.match(routing, /\bKeep Worker async\b/);
  for (const brief of [routing, files.execution]) {
    assert.match(brief, /deliverable (?:and|\+) finish line[^\n]*working directory, needed inputs and actual restrictions[^\n]*evidence to return/i);
    assert.doesNotMatch(brief, /permitted scope, limits and sources/i);
  }
  assert.match(routing, /the working directory is where to run, not a file-access allowlist/i);
  assert.match(routing, /No plan file, intake form or confirmation\. Read a reference only for an applicable trigger; bind it without expanding the brief/);
});

test("an independent Direct follow-up doesn't inherit or discharge an open project's lifecycle", () => {
  const route = flat(files.pp.split('## Route and dispatch')[1].split('## When to load more')[0]);
  assert.match(route, /independent Direct follow-up doesn't inherit or close an open unit: respect its constraints, staged changes and writers; report the focused check and limits inline/);
  assert.match(route, /If the change affects or fulfills the open unit's acceptance, retain its route, checks and findings/);
  assert.match(route, /If Direct stops fitting, stop mutation and carry evidence into the proper route\. Repair first; delivery Review follows integration and validation/);
});

test("a failed Planning run is not a proxy for Review eligibility", () => {
  assert.match(files.pp, /Use Review preflight for that assessment \(including a test of Review capability\) before inspecting its restricted inputs or deciding whether it can run/);
  const preflight = flat(files.review.split('## Pi parent: Review preflight')[1].split('## Modes and eligibility')[0]);
  assert.match(preflight, /failed Planning run is not a failed Review/i);
  assert.match(preflight, /requested Review.*own prerequisites.*shared blocker/);
  assert.match(preflight, /If eligible, dispatch a fresh Review Oracle without retrying Planning or repeating an unchanged probe/);
});

test("Worker returns the cited deliverable even when named-source coverage is partial", () => {
  // Guard the order and substance, not the section labels or numbering. No model call here.
  const record = flat(files.pw.split("Return one concise record")[1]);
  assert.match(record, /deliverable or its usable part.*summary inline.*citations.*each criterion or named source.*specific gap and next action.*what you inspected.*bulky logs.*bound reference/i);
  assert.match(record, /TARGET asks for a file.*exact reference/i);
});

test("Pi validation accountability preserves evidence reuse and required execution", () => {
  const text = flat(files.pp.split('## Route and dispatch')[1].split('\n## ')[0]);
  const controls = [
    [/verify coverage and material claims without redoing the task\./,
      [["without redoing the task", "by redoing the task"]]],
    [/Assign one execution owner per check; inspect bound results and apply P11 to final inputs\./,
      [["one execution owner", "multiple execution owners"], ["inspect bound results", "accept its summary"], ["apply P11 to final inputs", "ignore final-input applicability"]]],
    [/Rerun affected, uncertain, contradicted or explicitly independent checks—not for a parent signature or bookkeeping alone\./,
      [["Rerun affected, uncertain, contradicted", "Skip uncertain or contradicted"], ["or explicitly independent checks", "but not independent checks"], ["not for a parent signature", "always for a parent signature"]]],
    [/Required final checks and independent delivery assessment still apply\./,
      [["still apply", "are waived"]]],
  ];
  for (const [pattern, mutations] of controls) {
    assert.match(text, pattern);
    for (const [before, after] of mutations) {
      assert.ok(text.includes(before));
      assert.throws(() => assert.match(text.replace(before, after), pattern));
    }
  }
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

test("a saved next action is recoverable, not a wake or evidence that a writer stopped", () => {
  const transport = flat(files.pp);
  assert.match(transport, /live TUI automatically continues/);
  assert.match(transport, /after a cold restart, the marker and saved plan do not start a turn/);
  assert.doesNotMatch(transport, /`provider <owner> <id> <event>`/);
  assert.match(rule(files.skill, "P21"), /confirm it stopped.*missing dispatch receipt is not proof of termination/);
  assert.match(rule(files.xdev, "X6"), /Attach the runtime transport ID when the launch receipt arrives/);
  assert.match(rule(files.xdev, "X15"), /next supplied turn.*Do not replay/);
  assert.match(rule(files.review, "R1"), /later-sprint work open and explicitly outside this assessment/);
  assert.match(rule(files.xdev, "X24"), /Each task returns only its own lane's record/);
});

test("objective-level completion rejects premature DONE and implied confirmation stops", () => {
  const weakenings = [
    ["skill", "P18", "On every route", "Only on Reviewed"],
    ["skill", "P18", "is not objective completion while required in-scope work remains", "is objective completion despite remaining work"],
    ["skill", "P18", "A plan/report-only objective may complete with clearly optional or out-of-scope follow-up", "Every follow-up prevents completion"],
    ["skill", "P18", "never relabel required work as optional", "relabel required work as optional"],
    ["skill", "I4", "Do not defer required work behind implied or future/conditional confirmation", "Defer required work behind informal confirmation"],
    ["skill", "I4", "such a dependency uses this gate just like an explicit question", "such a dependency bypasses this gate"],
    ["xdev", "X14", "does not establish delivered Outcome", "establishes delivered Outcome"],
    ["xdev", "X14", "unfinished required work or its unresolved dependencies rule out DONE", "unfinished required work permits DONE"],
  ];
  for (const [file, id, before, after] of weakenings) {
    const text = rule(files[file], id);
    assert.ok(text.includes(before), `${file}/${id}: ${before}`);
    assert.throws(() => assert.match(text.replace(before, after), guards[file][id]));
  }
  const transport = flat(files.pp.split("## Response transport\n")[1]);
  assert.match(transport, /original objective, not a finished phase/);
  for (const [obligation, before, after] of [
    [/never defer it for an implied go-ahead/, "never defer", "defer"],
    [/may name optional follow-up, not reclassify required work/, "not reclassify", "reclassify"],
    [/\| `STATUS:DONE` \|[^|]*no required work or unresolved dependency/, "no required work or unresolved dependency", "required work may remain"],
  ]) {
    assert.match(transport, obligation);
    assert.doesNotMatch(transport.replace(before, after), obligation, after);
  }
});

test("xdev maintains one current plan instead of appending iteration history", () => {
  assert.deepEqual([...files.plan.matchAll(/^## (.+)$/gm)].map(m => m[1]),
    ["Goal", "Requirements", "Principles", "Environment Details", "Key Learnings", "Todo List", "Latest State"]);
  assert.doesNotMatch(files.plan, /^#{2,4} (?:History|Sprint Records|.*Coverage Log|.*Iteration Log)$/im);
  const update = rule(files.xdev, "X11");
  assert.match(update, /on each state write, replace superseded facts in place/i);
  assert.match(update, /no state change means no write/i);
  assert.match(update, /never write iteration logs, even temporarily/i);
  assert.match(update, /never copy a transcript or keep a sidecar journal/i);
  assert.match(files.xdev, /keep live or uncertain runs, unsettled todos and findings explicit/i);
  assert.match(update, /on each state write, replace superseded facts in place and compact Key Learnings: merge rules with the same action; remove those that no longer change remaining work/i);
  assert.match(files.xdev, /If no such reference exists, keep the required evidence inline where permitted; an inaccessible pointer is not evidence/);
  assert.match(files.xdev, /defer compaction until that reader is reconciled unless it already has the immutable bound copy/);
  assert.match(rule(files.xdev, "X3"), /pre-3\.4 plan, use X2 at the next safe state write; do not rewrite just to resume/);
  assert.match(flat(files.plan), /Migrate 3\.2\/3\.3 at the next safe state write, in the same file:.*keep every todo.*discard the chronology.*if a binding or necessary fact would be lost, retain the original/);
  assert.match(files.plan, /keep unmet\/blocked work unchecked/);
  assert.match(files.plan, /Show the current result or pending check, not an older PASS/);
  assert.match(flat(files.sprint), /replace this block in place; do not append one per sprint/i);
});

test("repeat attempts update decisions, not the size of the handoff", () => {
  const [env, rest] = files.plan.split("## Environment Details\n")[1].split("## Key Learnings\n");
  const [lessons, todos] = rest.split("## Latest State\n")[0].split("## Todo List\n");
  assert.match(rule(files.xdev, "X11"), /only if it guides remaining work, prevents a repeat mistake, or is needed to reconcile or prove an obligation/);
  assert.match(env, /verified setup facts that change how to run, test or resume.*source of truth.*no secrets.*Replace stale values/);
  assert.match(lessons, /Optional\. Only a supported condition → action that changes remaining work and isn't already in a requirement, environment fact or todo/);
  assert.match(lessons, /On each state write, combine overlapping rules and remove obsolete ones\. No attempt notes/);
  assert.match(files.sprint, /A completed sprint needs no narrative or lesson by default/);
  assert.match(rule(files.xdev, "X16"), /existing todo or Latest State field it changes, never a milestone entry/);
  assert.match(rule(files.xdev, "X8"), /a retry updates the existing todo/);
  assert.match(todos, /settled ID or group of IDs.*evidence mapping each ID to its discharge revision/);
  assert.match(files.plan, /Once reconciled, keep required bindings with the settled todo, not a second task report/);
});

test("records preserve lifecycle fields and reference canonical assessment", () => {
  assert.match(files.unit, /schema_version: 3\.1/);
  const liveTemplate = files.plan.replace(/<!--[\s\S]*?-->/g, "");
  assert.match(liveTemplate, /^\*\*schema_version:\*\* 3\.4$/m);
  assert.match(files.sprint, /<!-- xdev schema_version: 3\.4\./);
  for (const key of ["plan", "sprint"]) assert.match(files[key], /snapshot/i);
  assert.match(files.xdev, /`agent-review\/references\/review.md` alone owns Review eligibility/);
  const latest = files.plan.split("## Latest State\n")[1];
  const assessment = latest.split("**Review, when due:**")[1].split("\n")[0];
  for (const field of ["Review ID/ordinal", "covered unit/sprints", "revision/owner/snapshot", "raw oracle-review-result", "criterion evidence", "stable findings, prior resolutions", "integration/corrective batch/class strategy", "optional advice disposition"]) assert.ok(assessment.includes(field), field);
  assert.match(files.sprint, /link the covering Review once under Latest State/);
  assert.match(latest, /Final assessment.*pending or exact whole-state Review ref; reuse a sprint only when scope and evidence coincide/);
  assert.match(files.sprint, /reference the Requirements schedule; record only authorized sprint-specific differences.*Deferred checks keep their owner and due point/);
  const schedule = files.plan.split("## Requirements\n")[1].split("\n## ")[0];
  for (const field of ["name/ID", "criterion", "command/scenario", "inputs", "expected result", "owner", "cadence/due point", "cost/duration", "rerun trigger", "why cheaper evidence is insufficient"]) assert.ok(schedule.includes(field), field);
  assert.match(latest, /update by check ID, not by run.*execution revision\/snapshot.*material raw evidence ref; justify reuse under P11 or rerun/);
  assert.match(files.sprint, /reuse only with P11 applicability/);
  for (const field of ["State revision", "Outcome", "Execution disposition", "logical ID/generation", "status, run ID", "supersession/reason", "integration/result", "candidate ID/revision/proposed Outcome", "Oracle task/generation", "reconciled todo settlement"]) assert.ok(latest.includes(field), field);
  assert.match(files.plan, /initial clarification used/i);
  assert.match(files.unit, /Initial clarification|initial clarification/);
  assert.match(files.unit, /Recurring-class\/second-deficiency changed strategy/);
  assert.match(files.xdev, /oracle-closure-assessment/);
  for (const key of ["skill", "advisory", "review", "xdev", "unit", "plan", "sprint"])
    assert.doesNotMatch(files[key], /REVIEW_READY|Verdict: PASS|Verdict: FAIL|"verdict"|"orchestratorBrief"/);
});

const piAdviserFront = (name, description) => `---
name: ${name}
description: ${description}
tools: read, grep, find, ls, contact_supervisor
acceptanceRole: read-only
async: true
advertise: true
systemPromptMode: replace
inheritProjectContext: true
inheritGlobalContext: false
inheritSkills: true
---`;
const piWorkerFront = `---
name: worker
description: Delivers bounded research, summaries, investigation, implementation and validation.
tools: read, grep, find, ls, bash, edit, write, resolve-library-id, query-docs, contact_supervisor
async: true
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
test("configured Pi reasoning models support their advertised inputs and effort levels", () => {
  const models = JSON.parse(read("shell/config/pi/models.json")).providers.litellm.models;
  for (const [id, name] of [["gpt-6.2-astra", "GPT-6.2 Astra"], ["gpt-6.2-sol", "GPT-6.2 Sol"], ["gpt-6.1-terra", "GPT-6.1 Terra"]]) {
    const matching = models.filter((model) => model.id === id);
    assert.equal(matching.length, 1, `${id} must be registered exactly once`);
    assert.deepEqual(matching[0], { id, name, api: "openai-responses", reasoning: true,
      thinkingLevelMap: { off: null, minimal: null, low: "low", medium: "medium", high: "high", xhigh: "xhigh", max: "max" },
      contextWindow: 320000, maxTokens: 32000, input: ["text", "image"] });
  }
});

test("Pi selects registered Terra for the parent and keeps worker model pins", () => {
  const settings = JSON.parse(read("shell/config/pi/settings.json"));
  const models = JSON.parse(read("shell/config/pi/models.json")).providers.litellm.models;
  assert.equal(settings.defaultProvider, "litellm");
  assert.equal(settings.defaultModel, "gpt-6.1-terra");
  assert.equal(settings.defaultThinkingLevel, "xhigh");
  assert.equal(settings.subagents.disableBuiltins, true);
  for (const [key, model, thinking] of [
    ["planner", "gpt-6.2-astra", "xhigh"], ["po", "gpt-6.2-sol", "xhigh"], ["pw", "DeepSeek-V4.1-Flash", "max"],
  ]) {
    assert.equal(files[key].match(/^model: (.+)$/m)[1], model);
    assert.equal(files[key].match(/^thinking: (.+)$/m)[1], thinking);
    assert.ok(models.some((entry) => entry.id === model));
  }
});

test("Pi exposes three child roles and uses role names throughout its active prompts and shared skills", () => {
  const dir = "shell/config/pi/agents/";
  const settings = JSON.parse(read("shell/config/pi/settings.json")).subagents;
  const definitions = readdirSync(new URL(`../${dir}`, import.meta.url)).filter((f) => f.endsWith(".md"));
  // Only the exact retained definition may be hidden. Retirement removes both it and the override.
  const retained = definitions.includes("fixer.md");
  assert.deepEqual(settings.agentOverrides ?? {}, retained ? { fixer: { advertise: false } } : {});
  if (retained) {
    const role = read(dir + "fixer.md");
    assert.doesNotMatch(role, /agent-review/);
    assert.match(role, /exact bound `agents\/references\/execution\.md`/);
    assert.equal(createHash("sha256").update(role).digest("hex"), "0365666ec9098d4f01a5bc184267117848896ec39bba8013f9e0c73aa49a451f");
  }
  const active = definitions.filter((f) => settings.agentOverrides?.[f.slice(0, -3)]?.advertise !== false);
  assert.deepEqual(active.sort(), ["oracle.md", "planner.md", "worker.md"]);
  const sources = [paths.pp, ...active.map((f) => dir + f)];
  for (const root of [dir + "references/", dir + "templates/", "skills/agent-review/", "skills/xdev/"]) {
    for (const f of readdirSync(new URL(`../${root}`, import.meta.url), { recursive: true }))
      if (f.endsWith(".md")) sources.push(root + f);
  }
  for (const path of sources) {
    const text = read(path).replace(/^---\n[\s\S]*?\n---\n/, (header) =>
      path.startsWith(dir) ? header.replace(/^model: .*$/m, "") : header);
    assert.doesNotMatch(text, /(?<![a-z0-9])(?:fixers?|coordinators?|terra|sol|astra|deepseek)(?![a-z0-9])/i, path);
  }
});

test("Pi routes by the decision needed, not by difficulty or the name of a wire record", () => {
  const parent = flat(files.pp);
  assert.match(parent, /\buse reversible in-scope defaults for routine choices without advice/i);
  assert.match(parent, /material choices[^.]*mechanism, coupling and reversibility[^.]*assumptions and reconsideration triggers/i);
  assert.match(parent, /(?:cheapest|affordable) decisive observation first/i);
  assert.match(parent, /\breuse valid Planning\b/i);
  assert.match(parent, /group (?:unresolved substantive|substantive unsettled) choices or P19 premises for `oracle`/i);
  assert.match(parent, /On Reviewed\/xdev, call `planner` first[^.]*strategic choice/i);
  assert.match(parent, /consequence of choosing wrongly[^.]*neither current evidence nor an affordable check/i);
  assert.match(parent, /valid Oracle handoff, a current recorded escalation or an explicit user request for Planner/i);
  assert.match(parent, /missing fact or permission, difficulty, delay or a failed check alone is not a strategic choice/i);
  assert.match(parent, /fresh `oracle` for each Review, Input or Closure/);
  assert.match(parent, /Worker owns discovery through the focused check/);
  assert.match(parent, /for a report[^.]*not unasked repairs; for a change, repair and check/i);
  const policy = flat(files.advisory);
  assert.match(policy, /one linked Planner task before launch/);
  assert.match(policy, /first call[^.]*`basis\.openQuestions`/);
  assert.match(policy, /on referral[^.]*Oracle's exact unresolved question/i);
  assert.match(policy, /handoff alone leaves Planning outstanding/i);
  assert.match(policy, /Use Planner's plan without Oracle ratification/);
  assert.match(flat(files.planner), /Oracle referral is optional[^.]*evidence, not a shortlist/);
  assert.match(parent, /never override its model or return contract/);
  assert.match(flat(files.coordination), /reuse supported plans and bounded results under their recorded role, lane, assignment and generation.*previously consumed handoffs/);
  assert.match(flat(files.coordination), /prior run is terminal or cancelled and stopped.*same lane and a linked new generation under P21; preserve lineage, findings and Review expenditure/);
  assert.match(parent, /Input lane[^.]*match the recorded assignment to its completed assistant reply/);
  assert.match(parent, /Planning[^.]*cannot authorize contact/);
  assert.match(flat(files.skill), /OpenCode's `oracle` serves all four/);
  assert.match(files.planner, /Accept only the Planning lane of `ORACLE_ASSIGNMENT v2`/);
  assert.deepEqual(files.planner.match(/`oracle-[\w-]+`/g), ["`oracle-advisory-result`"]);
  assert.deepEqual(files.po.match(/`oracle-[\w-]+`/g), ["`oracle-advisory-result`", "`oracle-review-result`", "`oracle-input-assessment`", "`oracle-closure-assessment`"]);
});

test("backend roles have the expected discovery metadata and tool boundaries", () => {
  const expected = {
    planner: piAdviserFront("planner", "Read-only Planning specialist for exceptional unresolved strategic choices."),
    po: piAdviserFront("oracle", "Read-only adviser for ordinary Planning and independent Review, Input and Closure assessments."),
    pw: piWorkerFront, op: ocParentFront,
    oo: permissionFront("Decision adviser, strategic technical advisor, and read-only code reviewer.", "litellm/gpt-6.1-sol#max", false),
    of: permissionFront("Bounded implementation specialist for clear, assigned work.", "litellm/DeepSeek-V4.1-Flash#max", true),
  };
  for (const [key, value] of Object.entries(expected)) {
    const header = files[key].match(/^---\n[\s\S]*?\n---/)[0];
    // Pi pins are tested separately; changing models cannot change the role contract.
    assert.equal(key.startsWith("p") ? header.replace(/^(?:model|thinking): .*\n/gm, "") : header, value);
  }
});

test("OpenCode retains its execution role, original completion record and all four advisory lanes", () => {
  assert.match(files.of, /You are Fixer\. Implement the complete assigned TARGET/);
  assert.match(files.of, /`IMPLEMENTED_AND_VALIDATED`, `INCOMPLETE_REMEDIABLE` or `BLOCKED`/);
  for (const lane of ["Planning returns its bounded target", "Review returns exactly one", "Input assessment returns only", "Closure reads the entire exact plan"])
    assert.ok(files.oo.includes(lane), lane);
});
