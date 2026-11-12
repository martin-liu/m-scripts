// Non-writing policy checks for the agent prompt surface.
//
// These guard structure and selected drift signals only: role-applicable policy
// anchors, the mandatory Review hooks, removed stale semantics, unchanged
// backend frontmatter, and schema-example consistency. They cannot prove semantic
// equivalence or agent compliance.
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = (rel) => readFileSync(new URL(rel, new URL("..", import.meta.url)), "utf8");

const PI_PARENT = "shell/config/pi/APPEND_SYSTEM.md";
const PI_ORACLE = "shell/config/pi/agents/oracle.md";
const PI_FIXER = "shell/config/pi/agents/fixer.md";
const OC_PARENT = "shell/config/opencode-agents/orchestrator.md";
const OC_ORACLE = "shell/config/opencode-agents/oracle.md";
const OC_FIXER = "shell/config/opencode-agents/fixer.md";
const REVIEW_SKILL = "skills/agent-review/SKILL.md";
const REVIEW_REFERENCE = "skills/agent-review/references/review.md";
const XDEV_SKILL = "skills/xdev/SKILL.md";

const PRESERVED_ANCHORS = [
  "STATUS:CONTINUE",
  "STATUS:WAIT",
  "STATUS:DONE",
  "STATUS:BLOCKED user",
  "STATUS:FAILED",
  "PI_MAX_CONTINUATIONS",
];

test("review entry loads the canonical assignment and result reference", () => {
  assert.ok(existsSync(new URL(`../${REVIEW_REFERENCE}`, import.meta.url)));
  assert.match(read(REVIEW_SKILL), /references\/review\.md/);
  const s = read(REVIEW_REFERENCE);
  assert.match(s, /REVIEW_ASSIGNMENT v1/);
  assert.match(s, /COMPLETE PRIOR-FINDINGS BATCH/);
  assert.match(s, /"oracle-review-result"|oracle-review-result/);
  assert.match(s, /REVIEW_PRECONDITION_NOT_MET/);
  assert.match(s, /BLOCKED_REVIEW/);
  // Result enum fields present.
  for (const f of ["\"findings\"", "\"priorFindingResolutions\"", "\"requiredAction\"", "\"acceptancePredicate\""]) {
    assert.ok(s.includes(f), `review skill missing result field ${f}`);
  }
  // Allowed-alternatives note must be explicit so pipe strings are not read literally.
  assert.match(s, /allowed alternatives/i);
});

test("canonical Review JSON example parses and carries the Review shape", () => {
  const s = read(REVIEW_REFERENCE);
  const m = s.match(/```json\n([\s\S]*?)\n```/);
  assert.ok(m, "review skill has a fenced json example");
  const obj = JSON.parse(m[1]);
  assert.equal(obj.version, 1);
  assert.ok(["PASS", "FAIL"].includes(obj.verdict));
  assert.ok(Array.isArray(obj.criteria));
  assert.ok(Array.isArray(obj.findings));
  assert.ok(Array.isArray(obj.priorFindingResolutions));
  const f = obj.findings[0];
  assert.ok(f.id && f.requiredAction && f.requiredAction.acceptancePredicate);
  assert.ok(Array.isArray(f.locations));
  assert.ok(Array.isArray(f.evidenceRefs));
});

test("Planning has its own reachable advisory example, not a Review envelope", () => {
  const s = read(REVIEW_SKILL);
  const match = s.match(/```json\n([\s\S]*?)\n```/);
  assert.ok(match, "Planning entry contains its advisory example");
  const result = JSON.parse(match[1]);
  assert.equal(result.version, 1);
  assert.ok(result.dependencyId);
  assert.ok(!Object.hasOwn(result, "verdict"));
  const brief = result.orchestratorBrief;
  assert.equal(brief.stage, "ADVISORY");
  assert.equal(brief.judgment.qualityLevel, "NOT_ASSESSED");
  const decisionIds = new Set(brief.judgment.authorDecisionItems.map((item) => item.id));
  assert.ok(decisionIds.size > 0);
  for (const action of brief.nextActions) {
    assert.ok(["execute", "discover", "validate"].includes(action.kind));
    assert.ok(action.instruction && action.acceptancePredicate);
    assert.equal(action.findingIds.length, 0);
    assert.ok(action.decisionIds.length > 0);
    for (const id of action.decisionIds) assert.ok(decisionIds.has(id));
  }
});

test("pi parent carries the goal-understanding checkpoint and canonical dispatch hook", () => {
  const s = read(PI_PARENT);
  assert.match(s, /### Goal understanding/);
  assert.match(s, /goal-clarification/);
  assert.match(s, /one necessary concise question/);
  assert.match(s, /agent-review\/SKILL\.md/);
  assert.match(s, /agent-review\/references\/review\.md/);
  assert.match(s, /USER_INPUT_ASSESSMENT/);
  for (const a of PRESERVED_ANCHORS) assert.ok(s.includes(a), `pi parent missing ${a}`);
  const reference = read(REVIEW_REFERENCE).replace(/\s+/g, " ");
  assert.match(reference, /at most three DELIVERY\/`BLOCKED_REVIEW` dispatches/);
  assert.match(reference, /every started DELIVERY\/`BLOCKED_REVIEW` call spends one/);
  assert.match(reference, /After a second whole-unit FAIL/);
});

test("local self-review needs no Oracle permission and cannot supply independent PASS", () => {
  const parent = read(PI_PARENT).replace(/\s+/g, " ");
  const local = /Implement, self-review and validate locally without Oracle permission/;
  assertObligation(parent, local, /Implement, self-review/i, "local execution");
  assert.throws(() => assertObligation(`Do not ${local.source}.`, local,
    /Implement, self-review/i, "negated local execution"));
  const reference = read(REVIEW_REFERENCE).replace(/\s+/g, " ");
  assert.match(reference, /Independence concerns authorship, not model choice: parent self-review cannot supply independent delivery PASS/);
  assert.match(parent, /Reviewed\/xdev completion requires final delivery Review PASS/);
});

test("Oracle supplies clear plans while the parent repairs one whole corrective batch locally", () => {
  const parent = read(PI_PARENT).replace(/\s+/g, " ");
  const skill = read(REVIEW_SKILL).replace(/\s+/g, " ");
  const reference = read(REVIEW_REFERENCE).replace(/\s+/g, " ");
  const primary = /\*\*oracle\*\* supplies critical plans, judgment and guidance/;
  const planning = /Planning returns a clear bounded plan or decision with rationale and ordered actions/;
  const batch = /Turn Oracle's whole findings batch into one corrective contract; repair and validate locally/;
  assertObligation(parent, primary, /\*\*oracle\*\*/, "primary intelligence");
  assertObligation(skill, planning, /Planning returns/, "actionable plan");
  assertObligation(reference, batch, /Turn Oracle's whole findings batch/, "batched local correction");
  assert.throws(() => assertObligation(`Do not ${parent.match(primary)[0]}.`, primary,
    /\*\*oracle\*\*/, "negated primary intelligence"));
  assert.throws(() => assertObligation(reference.replace("repair and validate locally",
    "request Oracle approval for each fix"), batch, /Turn Oracle's whole findings batch/,
    "per-fix approval is not local correction"));
});

test("child protection stays inline and Fixer retains the sufficient media fallback", () => {
  const parent = read(PI_PARENT).replace(/\s+/g, " ");
  assert.match(parent, /retain child policy definitions until shared loading is verified/);
  for (const file of [PI_ORACLE, PI_FIXER]) {
    const s = read(file).replace(/\s+/g, " ");
    for (const pattern of [/identified staging\/production actions/, /privileged actions/,
      /deploy\/publish/, /machine-wide changes/, /destructive local database operations/,
      /affirmatively disposable development\/test state/,
      /unknown or potentially valuable local databases (?:stay|remain) protected/,
      /not protected merely for state or network use/]) {
      assert.match(s, pattern, `${file}: inline protected-effect definition`);
    }
  }
  const fixer = read(PI_FIXER).replace(/\s+/g, " ");
  const sufficient = /Otherwise use independently sufficient textual\/structured requirements only/;
  assert.match(fixer, sufficient);
  assert.match(fixer, /Contract-supported artifact-independent deterministic implementation remains allowed/);
  assert.throws(() => assert.match(fixer.replace("independently sufficient", "available"), sufficient));
  assert.match(read(PI_ORACLE).replace(/\s+/g, " "),
    /Use `bash` only if the bound parent contract permits shell inspection; the READ-ONLY whitelist is a limit, not a grant/);
});

test("goal clarification: clear proceeds silently, ambiguous resolves once, then closed", () => {
  // Behavioral guards for the required outcomes of problem 1.
  // Each guard asserts a PROHIBITION or an OBLIGATION together with its polarity:
  // a nearby negator must be absent, so a sign-reversed sentence cannot satisfy it.
  const cases = [
    { f: PI_PARENT,
      clear: /a clear requested outcome is recorded and acted on without ratification/i,
      clearSubject: /a clear requested outcome/i,
      allowanceSubject: /The allowance/i,
      ambiguous: /resolve it only when the goal admits irreconcilable readings/i,
      menu: /never a menu, questionnaire, or "which valid implementation/i,
      allowance: /allowance is one question in one user turn per objective\./i,
      durable: /Resume, compaction, task generations, and Review failures reuse this record and never reset it/i,
      noGuess: /neither authorizes guessing nor repeats the unchanged question/i },
    { f: OC_PARENT,
      clear: /clear, record it and proceed[^-]*never ask for confirmation/i,
      ambiguous: /only when the goal is genuinely ambiguous or admits irreconcilable readings/i,
      menu: /never a menu or a choice among valid implementations/i,
      allowance: /initial allowance is one question per objective/i,
      durable: /resume, compaction, or new task generations reuse it instead of re-asking/i,
      noGuess: /neither authorizes guessing nor repeats the unchanged question/i },
  ];
  for (const c of cases) {
    const s = read(c.f).replace(/\s+/g, " ");
    assert.match(s, c.clear, `${c.f}: a clear goal must proceed without asking for confirmation`);
    assert.match(s, c.ambiguous, `${c.f}: only genuine ambiguity/irreconcilable readings may trigger clarification`);
    assert.match(s, c.menu, `${c.f}: clarification must yield a question, never a menu`);
    assert.match(s, c.allowance, `${c.f}: initial allowance is one question per objective`);
    assert.match(s, c.durable, `${c.f}: the allowance must survive resume/compaction/generations and never reset`);
    assert.match(s, c.noGuess, `${c.f}: an inadequate reply must neither authorize guessing nor repeat the unchanged question`);
    // Polarity guards: obligations must not be sign-reversed (prefix or suffix).
    assertObligation(s, c.allowance, c.allowanceSubject ?? /(?:initial|clarification) allowance/i,
      `${c.f}: allowance obligation`);
    assertObligation(s, c.noGuess, /inadequate(?: or partial)? reply/i, `${c.f}: no-guess/no-repeat prohibition`);
    assertObligation(s, c.clear, c.clearSubject ?? /clear/i, `${c.f}: clear-goal proceed obligation`);
  }
});

// Assert an OBLIGATION is genuinely asserted, not sign-reversed. `obligation` must match the
// full positive obligation text. `subject` must match that obligation's clause subject, so a
// negator placed EITHER before the clause ("It is not true that ...", "Do not ...") OR between
// the subject and the rest of the obligation ("... allowance is not ...") is rejected.
// This closes both the suffix gap and the prefix gap that a suffix-only check leaves open.
//
// Negation scope is the SENTENCE, not the comma-delimited clause: a parenthetical comma must
// not hide a leading negator ("Do not, under any circumstances, reuse the prior ID ..."). The
// lead therefore runs from the last sentence-terminator (`.` `;` `!` `?`) before the
// obligation to the obligation match, and EVERY negator in that span is rejected.
const NEG = /\b(?:not|never|cannot|may\s+not|must\s+not|does\s+not|do\s+not|isn't|aren't|won't|no\s+longer|prohibited|optional)\b/i;
function assertObligation(haystack, obligation, subject, message) {
  const m = haystack.match(obligation);
  assert.ok(m, `${message}: obligation text absent`);
  // Suffix: text immediately following the clause subject (e.g. "allowance is NOT one ...").
  const sm = haystack.match(subject);
  assert.ok(sm, `${message}: clause subject absent`);
  const after = haystack.slice(sm.index + sm[0].length, sm.index + sm[0].length + 16);
  const suffixNeg = new RegExp('^\\s*(?:is|are|was|were|shall|should|will|would|may|must|can|could|does|do|did|be)?\\s*' + NEG.source.slice(2, -2), 'i');
  assert.ok(!suffixNeg.test(after), `${message}: obligation negated after subject ("${after.trim()}")`);
  // Prefix: any negator from the sentence start up to the obligation. Sentence terminals only,
  // so an intervening parenthetical comma never truncates the inspected lead.
  let leadStart = 0;
  for (const ch of ['.', ';', '!', '?']) {
    const i = haystack.lastIndexOf(ch, m.index);
    if (i > leadStart) leadStart = i;
  }
  leadStart += 1;
  const lead = haystack.slice(leadStart, m.index);
  assert.ok(!NEG.test(lead), `${message}: obligation negated in lead-in ("${lead.trim()}")`);
}

test("goal-clarification guards are falsifiable (negative controls)", () => {
  // In-memory sign-reversed sentences must FAIL their guard. These exercise the
  // same predicates the file guards use, so the guards cannot be vacuous.
  const allowance = /allowance is one question in one user turn per objective\./i;
  const clear = /clear, record it and proceed[^-]*do not ask for confirmation/i;
  const noGuess = /neither authorizes guessing nor repeats the unchanged question/i;
  const menu = /never a menu/i;
  const reversedAllowance =
    "The initial clarification allowance is not one question in one user turn per objective.";
  const prefixedAllowance =
    "It is not true that the initial clarification allowance is one question in one user turn per objective.";
  const obligation = /allowance is one question in one user turn per objective\./i;
  // The naive substring guard is satisfied by the reversed sentence (the words after "allowance"
  // still contain the obligation text), which is exactly why the polarity helper is required.
  assert.match(reversedAllowance, /one question in one user turn per objective\./i,
    "precondition: naive substring guard would match the reversed sentence");
  assert.throws(() => assertObligation(reversedAllowance, obligation, /initial clarification allowance/i, "allowance"),
    "helper must reject a subject-adjacent sign-reversed allowance sentence");
  assert.throws(() => assertObligation(prefixedAllowance, obligation, /initial clarification allowance/i, "allowance"),
    "helper must reject a PREFIX-negated allowance sentence");
  // Negation scope must span an intervening parenthetical comma: the comma-clause negated forms
  // of the shared-helper obligations must also be rejected (dispatch-8 F010 residual).
  const commaPrefixedReuse = "Do not, under any circumstances, reuse the prior ID for the same root-cause finding";
  const commaPrefixedClear = "Do not, when the requested outcome is clear, record it and proceed";
  assert.throws(() => assertObligation(commaPrefixedReuse, /Reuse the prior ID for the same root-cause finding/i,
      /Reuse the prior ID/i, "comma-scope reuse"),
    "helper must reject a comma-clause prefix-negated reuse obligation");
  assert.throws(() => assertObligation(commaPrefixedClear, /clear, record it and proceed/i,
      /clear/i, "comma-scope clear-goal"),
    "helper must reject a comma-clause prefix-negated clear-goal obligation");
  assert.throws(() => assertObligation("It is not true that, under this policy, only the existing `USER_INPUT_REQUIRED` assessment gate permits asking",
      /Only the existing `USER_INPUT_REQUIRED` assessment gate permits asking/i,
      /assessment gate/i, "comma-scope gate"),
    "helper must reject a comma-clause prefix-negated assessment-gate binding");
  // Sanity: the helper accepts the genuine obligation.
  assertObligation("The initial clarification allowance is one question in one user turn per objective.",
    obligation, /initial clarification allowance/i, "allowance (genuine)");
  assert.ok(!clear.test("clear, pause and proceed; do ask for confirmation"), "clear guard must bite when reversed");
  assert.ok(!noGuess.test("it authorizes guessing and may repeat the unchanged question"), "noGuess guard must bite when reversed");
  assert.ok(!menu.test("offer the user a menu of valid implementations"), "menu guard must bite when reversed");
});

test("xdev state-revision guard is falsifiable (negative control)", () => {
  const mustCarry = /An xdev unit must carry a `stateRevision` reproducing its assigned xdev state revision verbatim/i;
  const demoted = "xdev units may add a `stateRevision` string; it is otherwise omitted.";
  const prefixed = "It is not required that an xdev unit must carry a `stateRevision` reproducing its assigned xdev state revision verbatim.";
  assert.throws(() => assertObligation(prefixed, mustCarry, /An xdev unit must carry/i, "revision"),
    "revision guard must bite on a prefix-negated must-carry obligation");
  assert.ok(!mustCarry.test(demoted), "revision guard must bite when the binding is demoted");
  assertObligation(mustCarry.source.replace(/^\//, '').replace(/\/i$/, ''), mustCarry, /An xdev unit must carry/i, "revision (genuine)");
});

test("pi oracle requires the review result contract and bounded product-intent predicate", () => {
  const s = read(PI_ORACLE);
  assert.match(s, /oracle-review-result/);
  assert.match(s, /agent-review\/SKILL\.md/);
  assert.match(s, /agent-review\/references\/review\.md/);
  assert.match(s, /goal-clarification/);
  assert.match(s, /top-level ambiguity is indispensable/);
  assert.match(s, /for any Review\s+lane `agent-review\/references\/review\.md`/);
  assert.match(read(REVIEW_REFERENCE), /REVIEW_PRECONDITION_NOT_MET/);
});

test("pi fixer keeps implementation/validation and protected-effect boundaries", () => {
  const s = read(PI_FIXER);
  assert.match(s, /ordinary in-scope implementation choices/);
  assert.match(s, /never execute protected effects/i);
});

test("opencode parent mirrors goal understanding, review dispatch, and existing gates", () => {
  const s = read(OC_PARENT);
  assert.match(s, /goal understanding is a distinct, bounded intake/i);
  assert.match(s, /agent-review contract/);
  assert.match(s, /three unit-associated Review dispatches/);
  assert.match(s, /second whole-unit `FAIL`/);
  assert.match(s, /user-owned dependency/);
});

test("opencode oracle drops the APPROVED alias and requires the review contract", () => {
  const s = read(OC_ORACLE);
  assert.ok(!/\bAPPROVED\b/.test(s), "opencode oracle must not mention APPROVED");
  assert.match(s, /oracle-review-result/);
  assert.match(s, /agent-review contract/);
  assert.match(s, /does not itself\s+authorize contact/);
});

test("opencode fixer permits ordinary in-scope implementation choices", () => {
  const s = read(OC_FIXER);
  assert.match(s, /ordinary in-scope implementation choices/);
  assert.match(s, /protected effect/i);
});

test("both fixers permit only assigned implementation documentation lookup", () => {
  for (const f of [PI_FIXER, OC_FIXER]) {
    const s = read(f).replace(/\s+/g, " ");
    assert.match(s, /[Dd]ocumentation lookup is limited to assigned implementation needs/, `${f} must scope documentation lookup`);
    assert.match(s, /no open-ended\s+research/, `${f} must forbid open-ended research`);
  }
});

test("opencode fixer carries self-contained protected-effect classification", () => {
  const s = read(OC_FIXER);
  assert.match(s, /staging\/production mutations/);
  assert.match(s, /consequential\s+external or shared-resource mutations/);
  assert.match(s, /privileged or machine-wide actions/);
  assert.match(s, /deploy\/publish/);
  assert.match(s, /Unknown or potentially valuable\s+local databases remain protected/);
  assert.match(s, /affirmatively disposable development\/test state/);
  assert.match(s, /requires missing information, escalate before execution/);
  assert.match(s, /restrict diagnostics and\s+build output to authorized repository or affirmatively disposable test scope/);
});

test("xdev skill and templates route Review through the shared contract", () => {
  const s = read(XDEV_SKILL);
  assert.match(s, /agent-review\/references\/review\.md/);
  assert.match(s, /oracle-review-result/);
  assert.match(s, /initial-clarification-used/);
  const t = read("skills/xdev/templates/plan_and_track.md");
  assert.match(t, /### Goal Understanding/);
  assert.match(t, /Initial clarification used/);
  const b = read("skills/xdev/templates/sprint_block.md");
  assert.match(b, /agent-review\/references\/review\.md/);
  assert.match(b, /oracle-review-result/);
});

test("canonical reference defines binding agreement and the complete prior-findings batch", () => {
  const s = read(REVIEW_REFERENCE).replace(/\s+/g, " ");
  assert.match(s, /### Field types, alternatives, and binding agreement/);
  assert.match(s, /echo assigned `Review ID`, `Unit ID`, and `Snapshot ID` verbatim/);
  assert.match(s, /Review dispatch ordinal/);
  assert.match(s, /### Deterministic IDs/);
  assert.match(s, /COMPLETE PRIOR-FINDINGS BATCH/);
});

test("review contract keeps stable IDs while dropping redundant bookkeeping", () => {
  const s = read(REVIEW_REFERENCE).replace(/\s+/g, " ");
  // Stable identity is the mechanism: the ID form AND the reuse/non-reset/allocation rules.
  assert.match(s, /`<unitId>-F001`/, "stable ID form present");
  assert.match(s, /Reuse the prior ID for the same root cause/i, "same root cause reuses its prior ID");
  assert.match(s, /never renumber, reuse, or reset IDs after snapshot or generation changes/i, "IDs are not reset across snapshots/generations");
  assert.match(s, /Allocate new IDs sequentially after the highest historical suffix/i, "new IDs allocate after the highest historical suffix");
  // Polarity guards: the reuse/allocation obligations must not be sign-reversed (prefix or suffix).
  assertObligation(s, /Reuse the prior ID for the same root cause/i,
    /Reuse the prior ID/i, "stable-ID reuse obligation");
  assertObligation(s, /Allocate new IDs sequentially after the highest historical suffix/i,
    /Allocate new IDs/i, "ID-allocation obligation");
  // Counterexample: the rules must forbid the harmful behavior, not merely say 'stable'.
  assert.ok(!/may reset (?:IDS|finding IDs)/i.test(s), "resetting IDs must not be permitted");
  assert.ok(!/never renumber, reuse, or reset IDs/i.test("findings may reset IDs when a snapshot changes"), "non-reset guard must bite when reversed");
  // Optional classifications must not be mandatory schema.
  assert.ok(!/"origin":\s*"/.test(s), "mandatory origin taxonomy should be removed");
  assert.ok(!/"key":\s*"/.test(s), "mandatory root-cause key should be removed");
  assert.ok(!/\bmappedFindingIds\b/.test(s), "mappedFindingIds bookkeeping should be removed");
});

// The clarification-permission gate must be bound to the assessment in BOTH parents, and
// must not be replaceable by a blanket permission-to-ask. `assertUnnegated` alone is not
// enough here: the risk is a SUBSTITUTED sentence that drops the assessment binding while
// still containing the words, so we assert the binding phrase itself and its polarity.
test("both parents bind clarification permission to the assessment gate", () => {
  const cases = [
    { f: PI_PARENT,
      binding: /Only `USER_INPUT_REQUIRED` permits asking/i,
      bindingText: "Only `USER_INPUT_REQUIRED` permits asking",
      subject: /Only `USER_INPUT_REQUIRED`/i },
    { f: OC_PARENT,
      binding: /Only that explicit determination permits the Orchestrator to ask/i,
      bindingText: "only that explicit determination permits the Orchestrator to ask",
      subject: /Only that explicit determination/i },
  ];
  for (const c of cases) {
    const s = read(c.f).replace(/\s+/g, " ");
    assert.match(s, c.binding, `${c.f}: clarification permission must be bound to the assessment gate`);
    if (c.f === PI_PARENT) {
      assert.match(s, /Require the actual fenced `oracle-input-assessment` record with outcome `USER_INPUT_REQUIRED` and matching `dependencyId`/);
      assert.match(s, /from a completed run the parent witnessed starting in the current request epoch/);
    }
    assertObligation(s, c.binding, c.subject, `${c.f}: the assessment binding`);
    // A blanket permission-to-ask sentence must fail this binding.
    const bypass = "Any unresolved question permits asking the user directly, bypassing the assessment gate";
    assert.ok(!c.binding.test(bypass), `${c.f}: bypass sentence must not satisfy the binding guard`);
    // A prefix-negated restriction retaining the binding substring must be rejected.
    const prefixNegated = "It is not true that " + c.bindingText + ".";
    assert.ok(c.binding.test(prefixNegated), `${c.f}: precondition: prefix-negated form retains the substring`);
    assert.throws(() => assertObligation(prefixNegated, c.binding, c.subject, `${c.f}: prefix-negated binding`),
      `${c.f}: prefix-negated gate restriction must be rejected`);
  }
});

test("xdev results must bind the assigned state revision; others omit it", () => {
  const s = read(REVIEW_REFERENCE).replace(/\s+/g, " ");
  const binding = /xdev results must carry the assigned `stateRevision` verbatim/i;
  assertObligation(s, binding, /xdev results must carry/i, "xdev revision must-carry obligation");
  assert.match(s, /non-xdev results omit it/i, "non-xdev results omit the field");
  assert.match(s, /Product bytes cannot identify semantic state/i, "snapshot bytes cannot stand in for state revision");
  // Demotion and prefix-negation counterexamples must fail the binding guard.
  const demoted = "xdev units may add a `stateRevision` string; it is otherwise omitted.";
  assert.ok(!binding.test(demoted), "revision guard must bite when the binding is demoted");
  const prefixed = "It is not true that xdev results must carry the assigned `stateRevision` verbatim.";
  assert.throws(() => assertObligation(prefixed, binding, /xdev results must carry/i, "revision"),
    "revision guard must bite on a prefix-negated must-carry obligation");
});

test("shared contract states the full BLOCKED_REVIEW admission predicate", () => {
  const s = read(REVIEW_REFERENCE).replace(/\s+/g, " ");
  assert.match(s, /`BLOCKED_REVIEW` \| Feasible checks run, blocked checks evidenced, no viable authorized in-scope remedy\./);
  assert.match(s, /Readiness, approval, or relaxation of xdev closure; returns only `Verdict: FAIL`/);
  assert.match(s, /Never dispatch `BLOCKED_REVIEW` to find a remedy or spend a capped slot early/);
});

test("both parents resolve the contract path independently of working directory", () => {
  for (const f of [PI_PARENT, OC_PARENT]) {
    const s = read(f);
    assert.match(s, /agent-review\/SKILL\.md/, `${f} must name the exact contract path`);
    const cwdGuard = f === PI_PARENT
      ? /never assuming the working directory is the repository/i
      : /never assume the caller[\s\S]{1,3}s[\s\S]{1,3}s?working directory/i;
    assert.match(s, cwdGuard, `${f} must warn against cwd assumptions`);
  }
});

test("opencode oracle carries concrete read-only boundary and protected-effect definitions", () => {
  const s = read(OC_ORACLE);
  assert.match(s, /READ-ONLY inspection only/);
  assert.match(s, /run builds or\s+tests/);
  assert.match(s, /not an enforced sandbox/);
  assert.match(s, /staging\/production mutations/);
  assert.match(s, /Unknown or potentially valuable\s+local databases remain protected/);
  assert.match(s, /DELIVERY` Review only/);
  assert.match(s, /STATIC\/DESIGN` Review requires identified sources/);
});

test("opencode mirrors the structured user-input assessment contract", () => {
  const o = read(OC_ORACLE);
  assert.match(o, /## User-input assessments/);
  assert.match(o, /oracle-input-assessment/);
  assert.match(o, /USER_INPUT_ASSESSMENT/);
  assert.match(o, /goal-clarification` purpose uses `kind: "product-intent"/);
  const p = read(OC_PARENT);
  assert.match(p, /matching `USER_INPUT_REQUIRED` record with that `dependencyId`/);
});

test("opencode oracle loads the authoritative xdev skill for closure", () => {
  const s = read(OC_ORACLE);
  assert.match(s, /Load `skills\/xdev\/SKILL\.md`/);
  assert.match(s, /SOLE\s+authority for xdev lifecycle/);
  assert.match(s, /subordinate to that skill/);
});

test("backend frontmatter is preserved (no accidental mode/tools drift)", () => {
  // Pi role prompts declare a frontmatter block; opencode uses mode: subagent.
  const piOracle = read(PI_ORACLE);
  assert.match(piOracle, /^---\n/);
  const ocOracle = read(OC_ORACLE);
  assert.match(ocOracle, /^---\n/);
  assert.match(ocOracle, /mode: subagent/);
  const review = read(REVIEW_SKILL);
  assert.match(review, /^---\nname: agent-review\n/);
});

test("root sanity: paths resolve", () => {
  for (const rel of [PI_PARENT, PI_ORACLE, PI_FIXER, OC_PARENT, OC_ORACLE, OC_FIXER, REVIEW_SKILL, REVIEW_REFERENCE, XDEV_SKILL]) {
    assert.ok(existsSync(new URL(`../${rel}`, import.meta.url)), `missing ${rel}`);
  }
  assert.ok(root.length > 0);
});