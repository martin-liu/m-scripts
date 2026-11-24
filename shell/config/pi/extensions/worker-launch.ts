import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Project-only discovery omits user settings; these pi-subagents aliases can select bundled roles.
const bundledAliases = new Set(["developer", "coder", "implementer", "develop", "advisor"]);
// Reject the retired name on fresh tool launches; leave ID-based management untouched.
const workers = new Set(["worker", "oracle", "planner", "fixer", ...bundledAliases]);
const isWorker = (name: unknown) => typeof name === "string" && workers.has(name.trim());
// pi-subagents drops this exact string before dispatch (not whitespace variants).
const specified = (value: unknown) => value !== undefined && value !== "null";
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const directOnly = { block: true, reason: "Launch worker, oracle and planner directly with subagent({ agent, task }); not in a workflow, group or chain." };

/** Inspect only pi-subagents' child slots, never tasks, script text or arbitrary workflow data. */
function groupHasWorker(group: unknown): boolean {
  return Array.isArray(group) && group.some(child => record(child) &&
    (isWorker(child.agent) || groupHasWorker(child.parallel)));
}

/** Bind new orchestrator assignments to fresh context, user roles, model pins and return contracts. */
export default function workerLaunch(pi: ExtensionAPI) {
  pi.on("tool_call", (event) => {
    if (event.toolName !== "subagent" && event.toolName !== "subagent_launch") return;
    const input = event.input as Record<string, unknown>;
    if (event.toolName === "subagent_launch") {
      // runs.run/runs.all exposes the resolved child here. Only a refusal or a task edit
      // reaches execution; adding scope/contract to this event would do nothing.
      // A native retained-ID resume has no agent; a named child is a new launch.
      if (isWorker(input.agent)) return directOnly;
      return;
    }
    const action = specified(input.action);
    const workflow = typeof input.workflow === "string" ? input.workflow.trim() : input.workflow;
    const hasWorkflow = (specified(input.workflow) && input.workflow !== "false") ||
      (record(input.options) && specified(input.options.script));
    if (groupHasWorker(input.tasks) || groupHasWorker(input.chain) || groupHasWorker(input.parallel) ||
        (workflow === "parallel" && record(input.args) && groupHasWorker(input.args.tasks))) return directOnly;
    const role = typeof input.agent === "string" ? input.agent.trim() : "";
    if (!isWorker(role) || (action && !specified(input.task))) return; // management, including retained runs
    if (role === "fixer") return { block: true, reason: "Use worker for new bounded work; manage retained runs by ID." };
    if (bundledAliases.has(role)) return { block: true, reason: "Use the exact role name worker, oracle or planner; omit bundled aliases." };
    if (action || event.parentToolCallId || hasWorkflow || [input.tasks, input.chain, input.parallel].some(specified)) return directOnly;
    if (role === "worker" && (!specified(input.task) || typeof input.task !== "string" || !input.task.trim())) {
      return { block: true, reason: "Give worker a nonblank TARGET in task." };
    }
    const raw = specified(input.options) ? input.options : undefined;
    if (raw !== undefined && !record(raw)) {
      return { block: true, reason: "Worker launch options must be an object." };
    }
    const options = raw ?? {};
    // Older declarations also accept flat options. Reject conflicts rather than dropping them.
    for (const fields of [input, options]) {
      if (specified(fields.model) || specified(fields.modelOrigin)) {
        return { block: true, reason: `Omit the model override for ${role}; its user role pins the model.` };
      }
      if (specified(fields.context) && fields.context !== "fresh") {
        return { block: true, reason: `Launch ${role} with fresh context; pass the assignment and readable sources in task.` };
      }
      if (specified(fields.agentScope) && fields.agentScope !== "user") {
        return { block: true, reason: `Launch ${role} with user scope; project roles can shadow it.` };
      }
      const contract = fields.agentContract;
      if (specified(contract) && (!record(contract) || contract.version !== 1 || Object.keys(contract).length !== 1)) {
        return { block: true, reason: `Launch ${role} with agentContract version 1.` };
      }
      if ([fields.acceptance, fields.gate, fields.outputSchema].some(specified)) {
        return { block: true, reason: `Launch ${role} with its canonical return; do not substitute a host gate or output schema.` };
      }
    }
    input.options = { ...options, context: "fresh", agentScope: "user", agentContract: { version: 1 } };
  });
}
