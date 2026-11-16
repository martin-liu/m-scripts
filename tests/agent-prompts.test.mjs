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
    P6: /^A bounded target names output\/behavior, authoritative basis, allowed scope, criterion IDs and observable expectations, evidence, validation owner\/commands, material cases and invariants/,
    P8: /^Required deterministic behavior uses faithful input\/output, boundary, error and regression checks;.*never weaken authoritative expected results\./,
    P9: /^Durable evidence is repository path plus content hash, immutable artifact\/URL or inline material evidence; runtime IDs, notifications, temporary paths and task reports alone establish nothing\./,
    P10: /^Bind validation and assessment to root\/base.*tracked\/staged\/untracked.*material modes.*deletions.*manifest-lines hash/,
    P11: /^Exclude mutable plans.*Product mutation stales evidence; bookkeeping-only edits do not/,
    P12: /^Disclose inspection\/execution owners.*never claim computations.*unless independent execution was arranged/,
    P13: /^Artifact identity, access, modality capability and evidence owner are distinct.*workers do not inherit attachments/,
    P14: /^Parent-recorded criterion-level media inspection can support Oracle assessment.*that lack alone is no blocker or extra-call reason.*Explicit independent media verification requires exact access and capability/,
    P15: /^With inaccessible media, Fixer proceeds only from independently sufficient textual\/structured requirements.*artifact-independent deterministic implementation remains allowed/,
    P16: /^Keep corpus claims separate: semantic item-level truth.*every claimed item before identical-scope automation.*exact-rule transformation.*population claims/,
    P17: /^Samples support discovery or sample-scoped claims, never unprocessed items.*Scripts, fixtures, presets, generated data, prior outputs and summaries are not corpus truth/,
    P18: /^A worker result or terminal operation does not close an objective.*failed prerequisites block only dependents/,
    P19: /^Negative\/blocked conclusions requiring material semantic inference.*separate Planning premise assessment.*Different-path controls do not prove normal outcomes/,
    P20: /^Stop unfinished work only for.*ordinary Review-cap non-delivery is also permitted under its reference, never an impossibility claim, waiver of delivery requirements, route evasion or automatic contact\.$/,
    P21: /^Inspect Reviewed\/xdev background children only on completion or transport resume, never poll.*Never revive superseded work/,
    P23: /^Ordinary Reviewed tasks durably bind logical task ID plus generation before dispatch.*material conflicts fail closed/,
    P24: /^Reviewed completion requires a clear final independent delivery assessment.*zero pending work.*Before those conditions hold, the parent must not describe the Reviewed\/xdev outcome or current snapshot as done, complete or ready; report 'implemented, unassessed', 'assessment deficient' or the exact outstanding condition\. Defined task\/transport statuses and factual completed substeps are unchanged\.$/,
    I3: /^Technical, implementation, strategy, architecture and ordinary product\/UI choices.*Exactly three user-owned kinds exist:.*indispensable user-only access\/fact.*genuinely incompatible product-intent/,
    I4: /^Before any user question.*actual fenced matching `USER_INPUT_REQUIRED`.*current request epoch.*Only this record permits asking/,
    I5: /^Finish other feasible authorized work.*ask only when no authorized work remains ready/,
    I6: /^Record objective ID.*A clear goal proceeds without ratification or specified implementation/,
    I7: /^Initial goal clarification is one question in one user turn per objective, only for irreconcilable outcome readings after proportionate discovery and independent authorized preparation\..*never a menu\/questionnaire\. .*do not reset it; only a materially replaced objective does\./,
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
    R10: /^Every blocking issue has a stable finding ID and current-state evidence\. Every requiredAction has a falsifiable acceptance predicate\. Deterministic claims require a mechanical predicate naming fixed inputs, a repeatable executable or rule-based static check and its expected result; where judgment is indispensable, name the authoritative criterion, concrete scenario\/evidence and observable resolving condition, and explain why a mechanical check alone is insufficient\. Oracle repairs incomplete predicates before returning; a non-conforming return is malformed, not delivery evidence, and the parent preserves it rather than inventing or weakening its predicate\./,
    R11: /^A clear delivery assessment means DELIVERY mode, met preconditions, every material criterion satisfied and no blocking finding/,
    R12: /^Decisions use the shared structured rationale.*with deficiencies allows remedy only.*clear DELIVERY allows reconcile only/,
    R13: /^Findings use.*Reuse the prior ID for the same root cause.*Allocate new IDs after the highest historical suffix/,
    R14: /^Turn the whole findings batch into one corrective contract\. Before every redispatch, name each prior finding's defect class \(shared failure mechanism, not instance\/location\), identify and inspect equivalent in-scope paths\/stages, and record how corrections or evidence-backed rebuttals and class-level checks cover them; justify inapplicability\..*rerun affected checks and every required validation, preserving applicable unchanged-input evidence\. Never interleave assessment with partial corrections\.$/,
    R15: /^On recurrence of a defect class, even under a new finding ID, or after a second deficient whole-unit delivery assessment, stabilize before redispatch\..*materially change the repair or validation mechanism.*alone is not a changed strategy\..*Recheck root causes, equivalent affected paths, induced defects and test adequacy\. Executable regressions must execute the intended path and fail with the guard\/feature disabled, isolating prior state\/retries; static\/evidence\/judgment repairs must demonstrate detection of the prior failure by repeatable comparison or criterion-grounded adverse scenario\. Recurring findings retain history\.$/,
    R16: /^Ordinary Reviewed units default to at most six DELIVERY\/BLOCKED_REVIEW dispatches; STATIC\/DESIGN, Planning and xdev are excluded\. Commit expenditure before call start: preflight rejection spends none; every started DELIVERY\/BLOCKED_REVIEW call spends one, including cancelled, replacement, malformed and precondition-failed calls\. No generation\/snapshot\/rename resets expenditure\. Only the repository owner, or a human explicitly designated by that owner for this decision, may extend a named unit's limit by an explicit finite added allowance\. Before using it, record the exact instruction, authority, unit, added allowance and resulting cumulative limit in the unit's existing assessment history\. The parent cannot self-grant, infer or generalize an extension; it changes effort only, not eligibility, findings, validation or independent assessment, and grants no user contact\. Later and extended dispatches still require eligibility and R15 stabilization\.$/,
    R17: /^Assess the complete current unit.*genuine new material findings remain required.*rebuttals are not re-litigated/,
    R18: /^Bind baseline and shipping scope.*subordinate clauses.*owner\/load applicability.*reader/,
    R19: /^Compare actor, condition, prohibition and exception.*restore losses unless actual instructions authorize them/,
    R20: /^Supported coverage\/dispositions.*bounded assurance, not exhaustive equivalence.*never extra completeness Reviews/,
  },
  xdev: {
    X1: /^Resolve one exact state locator per objective.*never overwrite an existing plan/,
    X5: /^Each durable semantic write increments State revision exactly once.*atomically R to N=R\+1.*Runtime-ID.*neutral/,
    X6: /^Every authorized dispatch has a pre-dispatch ledger entry.*Logical ID\/generation is identity/,
    X8: /^Todo IDs are stable and never reused.*Never silently delete\/reopen/,
    X9: /^Reconcile the complete todo list on resume.*one designated Review-action todo stays open/,
    X10: /^Outcome is active\/delivered\/conclusively blocked.*Local results never replace Outcome/,
    X12: /^Baseline, sprint and final checks\/scenarios record revision, snapshot, execution owner.*material raw evidence/,
    X14: /^Before ending an active root turn, reread the exact plan.*complete todo list.*automatic resume/,
    X16: /^Batch consecutive sprints sharing contract, invariants or validation.*not sprint boundaries/,
    X17: /^A last\/only sprint assessment serves final whole-state assessment.*every non-closure todo satisfied/,
    X18: /^Routine active recovery needs no closure assessment.*Negative\/blocked closure.*revision-bound Oracle assessment/,
    X19: /^Before dispatch at N, atomically record candidate ID\/revision N.*Oracle reads the entire exact plan/,
    X20: /^Bind assessment to candidate ID\/revision\/proposed Outcome\/task\/generation.*Conclusions are advisory/,
    X21: /^Atomic assessment integration.*N to N\+1.*Only a substantive premise-changing event/,
    X22: /^Delivered settlement satisfies every non-closure todo.*never falsely discharged/,
    X23: /^At delivered candidate N only the designated assessment todo may remain open.*active Outcome permits no terminal user-facing claim/,
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
    ["review", "R16", "No generation/snapshot/rename resets expenditure", "A new generation resets expenditure"],
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
  for (const key of ["unit", "plan", "sprint"])
    assert.match(files[key], /schema_version:\*?\*? 3\.0|schema_version: 3\.0/);
  for (const key of ["plan", "sprint"]) {
    assert.match(files[key], /agent-review\/references\/review\.md/);
    assert.match(files[key], /oracle-review-result/);
    assert.match(files[key], /Snapshot/);
  }
  for (const field of ["State revision", "Outcome", "Execution disposition", "Task Ledger",
    "Authoritative Todo List", "Initial clarification used", "Terminal Decision Record",
    "Oracle logical task ID / generation", "Todo settlement"])
    assert.ok(files.plan.includes(field));
  assert.match(files.unit, /Initial clarification|initial clarification/);
  assert.match(files.unit, /Second-deficiency changed strategy/);
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
