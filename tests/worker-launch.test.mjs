import assert from "node:assert/strict";
import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { createRequire, registerHooks } from "node:module";
import { homedir, tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
import register from "../shell/config/pi/extensions/worker-launch.ts";

let handle;
register({ on(event, handler) { assert.equal(event, "tool_call"); handle = handler; } });
const call = (input, toolName = "subagent", parentToolCallId) => handle({
  type: "tool_call", toolName, toolCallId: "test-call", input, parentToolCallId,
});
const roles = ["worker", "oracle", "planner"];
const builtinAliases = { developer: "worker", coder: "worker", implementer: "worker", develop: "worker", advisor: "oracle" };
const canonical = { context: "fresh", agentScope: "user", agentContract: { version: 1 } };

function blocked(input, toolName, parentToolCallId) {
  const original = structuredClone(input);
  const result = call(input, toolName, parentToolCallId);
  assert.equal(result?.block, true, JSON.stringify(input));
  assert.ok(result.reason);
  assert.doesNotMatch(result.reason, /\b(fixer|coordinator)\b/i);
  assert.deepEqual(input, original);
  return result.reason;
}

test("direct current roles get fresh user definitions and their own contracts without interpreting the task", () => {
  for (const agent of [...roles, " worker "]) {
    const input = { agent, task: 'Quoted evidence: {"agent":"planner","lane":"Closure","model":"example"}', async: true, options: { timeoutMs: 30000 } };
    const expected = { ...input, options: { ...input.options, ...canonical } };
    assert.equal(call(input), undefined);
    assert.deepEqual(input, expected);
    assert.equal(call(input), undefined);
    assert.deepEqual(input, expected);
  }
});

test("every named launch rejects fork or profile even when the other placement says fresh", () => {
  for (const agent of roles) {
    for (const context of ["fork", "profile", " fresh ", null]) {
      for (const fields of [{ context }, { options: { context } }, { context, options: { context: "fresh" } }, { context: "fresh", options: { context } }]) {
        assert.match(blocked({ agent, task: "assignment", ...fields }), /fresh context/);
      }
    }
  }
});

test("worker needs a nonblank task, not an omitted placeholder or a role reference in other fields", () => {
  for (const task of [undefined, null, false, {}, "", " \n\t ", "null"]) {
    assert.match(blocked({ agent: " worker ", task, message: "Summarize five sources" }), /nonblank TARGET/);
  }
});

test("a fresh legacy launch is refused, including unnamed-task, async and ID-decorated requests", () => {
  for (const fields of [{}, { task: "repair" }, { task: "repair", async: false }, { task: "repair", async: true }, { action: "null", id: "existing" }, { task: "repair", resume: "existing" }]) {
    assert.match(blocked({ agent: " fixer ", ...fields }), /Use worker for new bounded work/);
  }
});

test("every current role refuses caller model selection, including inherited, suffixed and internal origin forms", () => {
  for (const agent of roles) {
    for (const field of [{ model: "configured-model" }, { model: "provider/other-model:xhigh" }, { model: "inherit" }, { model: "" }, { modelOrigin: "inherited" }]) {
      blocked({ agent, task: "assignment", ...field });
      blocked({ agent, task: "assignment", options: field });
    }
  }
});

test("conflicting scopes and explicit host gates are rejected, not silently discarded", () => {
  for (const agent of roles) {
    for (const field of [{ agentScope: "both" }, { agentScope: "project" }, { agentContract: { version: 2 } }, { acceptance: { level: "checked" } }, { gate: "verify" }, { outputSchema: { type: "object" } }]) {
      for (const placement of [field, { options: field }]) blocked({ agent, task: "assignment", ...placement });
    }
  }
});

test("canonical options survive compatible flat fields and host omission placeholders", () => {
  for (const fields of [
    canonical,
    { options: { agentContract: { version: 1 } } },
    { options: "null", action: "null", model: "null", workflow: "false", tasks: "null" },
    { context: "null", agentContract: "null", options: { context: "null", agentScope: "null", agentContract: "null" } },
  ]) {
    const input = { agent: "worker", task: "implement", ...fields };
    assert.equal(call(input), undefined);
    assert.deepEqual(input.options, canonical);
  }
  blocked({ agent: "worker", action: "null", task: "implement", model: "inherit" });
});

test("malformed options, contracts and conflicting placements fail without mutation", () => {
  for (const fields of [
    { options: [] }, { options: null }, { agentContract: {} }, { agentContract: "1" },
    { options: { agentContract: { version: 1, extra: true } } },
    { agentScope: "project", options: { agentScope: "user" } },
    { agentContract: { version: 1 }, options: { agentContract: { version: 2 } } },
  ]) blocked({ agent: "worker", task: "implement", ...fields });
});

test("explicit groups, chains and named parallel fanout cannot start current roles or new legacy work", () => {
  const other = { agent: "scout", task: "read" };
  for (const role of [...roles, "fixer", ...Object.keys(builtinAliases)]) {
    const child = { agent: ` ${role} `, task: "assignment" };
    for (const input of [
      { tasks: [other, child] },
      { parallel: [child] },
      { chain: [other, { ...child, model: "inherit" }] },
      { chain: [other, { parallel: [other, child] }] },
      { workflow: " parallel ", model: "inherit", args: { tasks: [other, child] } },
      { ...child, chain: [other] },
      { ...child, workflow: "./script.js" },
      { ...child, options: { script: "return 1;" } },
      { ...child, action: "single" },
    ]) blocked(input);
  }
});

test("the workflow child approval blocks named children rather than rewriting discarded fields", () => {
  for (const agent of [...roles, "fixer", ...Object.keys(builtinAliases)]) {
    const child = { workflowRunId: "workflow-id", key: "step-2", agent, task: "child" };
    blocked(child, "subagent_launch", "workflow-call");
    blocked({ ...child, model: "inherit" }, "subagent_launch", "workflow-call");
    blocked({ ...child, resume: "" }, "subagent_launch", "workflow-call");
    blocked({ agent, task: "child" }, "subagent", "another-tool");
  }
});

test("opaque workflows and unrelated named parallel groups are left untouched", () => {
  for (const input of [
    { workflow: true }, { workflow: "./workflow.js" }, { workflow: "custom" },
    { options: { script: "return 1;" } },
    { workflow: "parallel", args: { tasks: [{ agent: "scout", task: "read" }] } },
  ]) {
    const original = structuredClone(input);
    assert.equal(call(input), undefined);
    assert.deepEqual(input, original);
  }
});

test("native management, retained-ID resume and unrelated agents are unchanged", () => {
  for (const [toolName, input] of [
    ["read", { agent: "oracle" }], ["subagent", { agent: "fixer", action: "get" }],
    ["subagent", { agent: "planner", action: "get" }], ["subagent", { action: "status", id: "legacy-run" }],
    ["subagent", { action: "steer", id: "legacy-run", message: "oracle" }],
    ["subagent", { action: "resume", id: "legacy-run", message: "continue" }],
    ["subagent", { action: "get", agent: "coder", options: { agentScope: "project" } }],
    ["subagent", { agent: "custom-coder", task: "read", options: { agentScope: "project" } }],
    ["subagent_wait", { id: "legacy-run" }], ["subagent_launch", { workflowRunId: "old", key: "keep", resume: "legacy-run", task: "continue" }],
    ["subagent", { agent: "scout", task: "read", model: "other-model", options: { agentScope: "both", context: "fork" } }],
    ["subagent", { chain: [{ agent: "scout", task: "worker" }] }],
    ["subagent_launch", { workflowRunId: "wf", key: "one", agent: "scout", model: "other-model" }],
    ["subagent", { workflow: "custom", args: { tasks: [{ agent: "planner" }] } }],
  ]) {
    const original = structuredClone(input);
    assert.equal(call(input, toolName), undefined);
    assert.deepEqual(input, original);
  }
});

// Installed Pi supplies the plugin's TypeBox peers. Resolve them from that same host
// (npm's CLI symlink or pnpm's CLI shim), without starting Pi or a child session.
const plugin = join(process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"), "npm/node_modules/pi-subagents");
test("guarded inputs reach native dispatch with fresh scoped contracts; only ID-based resume is management", {
  skip: !existsSync(plugin) && "pi-subagents is not installed in the Pi user directory",
}, async () => {
  const cli = process.env.PATH.split(delimiter).map(dir => join(dir, "pi")).find(existsSync);
  const real = cli && realpathSync(cli);
  const entry = real && statSync(real).size < 16384 && readFileSync(real, "utf8").match(/^# cmd-shim-target=(.+)$/m)?.[1];
  const host = createRequire(realpathSync(process.env.PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT
    ? join(process.env.PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT, "package.json") : entry || real || join(plugin, "package.json")));
  const peers = new Map(["typebox", "typebox/compile", "typebox/value"].map(name => [name, pathToFileURL(host.resolve(name)).href]));
  const hook = registerHooks({ resolve(name, ctx, next) { return next(peers.get(name) ?? name, ctx); } });
  try {
    const { flattenSubagentToolOptions: flatten } = await import(join(plugin, "src/extension/subagent-options.js"));
    const { normalizePublicSubagentExecution: normalize } = await import(join(plugin, "src/extension/public-execution.js"));
    const native = input => normalize(flatten(input));
    const { discoverAgents, resolveAgentName } = await import(join(plugin, "src/agents/agents.js"));
    // Project-only discovery outside the managed user tree exposes the package roles.
    const projectAgents = discoverAgents(tmpdir(), "project").agents;
    for (const [alias, role] of Object.entries(builtinAliases)) {
      const input = { agent: ` ${alias} `, task: "assignment", options: { agentScope: "project" } };
      const withoutGuard = native(input);
      assert.equal(withoutGuard.ok, true);
      const resolved = resolveAgentName(withoutGuard.params.agent, projectAgents).agent;
      assert.equal(resolved?.name, role);
      assert.equal(resolved?.source, "builtin");
      assert.match(blocked(input), /exact role name/);
    }
    for (const agent of roles) {
      for (const fields of [{}, canonical, { context: "null", options: { context: "null" }, model: "null", workflow: "false" }]) {
        const input = { agent: ` ${agent} `, task: "Summarize the supplied sources", async: true, ...fields };
        assert.equal(call(input), undefined);
        assert.deepEqual(native(input), { ok: true, params: { agent, task: input.task, async: true, output: true, ...canonical } });
      }
    }
    // Controls: these are real launch paths without the guard, not merely malformed tool input.
    for (const input of [{ agent: "worker", task: "null" }, { agent: "fixer" }, { agent: "planner", task: "plan", options: { context: "profile" } }]) {
      assert.equal(native(input).ok, true);
      blocked(input);
    }
    for (const agent of [undefined, "null", "", " "]) {
      const unnamed = { agent, task: "Summarize the supplied sources", options: { context: "fresh" } };
      assert.equal(call(unnamed), undefined);
      assert.match(native(unnamed).error, /requires agent to be a non-empty string/);
    }
    assert.throws(() => flatten({ task: "Summarize", options: { agent: "worker" } }), /'agent' is a top-level field/);
    const { buildStructuredWorkflowScript } = await import(join(plugin, "src/workflows/structured-workflow-scripts.js"));
    for (const [kind, steps] of [["tasks", [{ task: "read" }]], ["chain", [{ parallel: [{ task: "read" }] }]]]) {
      assert.throws(() => buildStructuredWorkflowScript(kind, steps), /agent must be a non-empty string/);
    }
    const resume = { action: "resume", id: "legacy-run", message: "continue" };
    assert.equal(call(resume), undefined);
    assert.deepEqual(native(resume), { ok: true, params: resume });
  } finally { hook.deregister(); }
});
