/** Session identity and read-only pi-subagents status verification for WAIT. */
import { asRecord, SUBAGENT_RPC_VERSION } from "./protocol.ts";
import type { SupervisorContext } from "./protocol.ts";

/** Prefer the host session manager; minimal hosts can supply direct fields. */
export function sessionIdentity(ctx: SupervisorContext | undefined): string {
  const manager = ctx?.sessionManager;
  if (manager !== null && manager !== undefined && typeof manager === "object") {
    try {
      const fromManager = manager.getSessionFile?.();
      if (typeof fromManager === "string" && fromManager.length > 0) return fromManager;
    } catch {
      // A throwing accessor is not an identity; fall through to the id.
    }
    try {
      const idFromManager = manager.getSessionId?.();
      if (typeof idFromManager === "string" && idFromManager.length > 0) return idFromManager;
    } catch {
      // Fall through to the direct fields.
    }
  }
  const file = ctx?.sessionFile;
  if (typeof file === "string" && file.length > 0) return file;
  const id = ctx?.sessionId;
  return typeof id === "string" ? id : "";
}

/** A transcript read needs a file path: a bare session id is not a fallback. */
export function sessionTranscriptPath(ctx: SupervisorContext | undefined): string {
  try {
    const fromManager = ctx?.sessionManager?.getSessionFile?.();
    if (typeof fromManager === "string" && fromManager.length > 0) return fromManager;
  } catch {
    // A throwing accessor yields no path; fall through to the direct field.
  }
  const file = ctx?.sessionFile;
  return typeof file === "string" && file.length > 0 ? file : "";
}

/** A paused workflow may retain descendants, but promises no automatic wake. */
export function ownerStateIsActive(state: unknown): boolean {
  return state === "running" || state === "queued";
}

/** Positive evidence the wake is gone. An *unknown* state is not such evidence. */
export function ownerStateIsTerminal(state: unknown): boolean {
  return (
    state === "complete" ||
    state === "completed" ||
    state === "partial" ||
    state === "failed" ||
    state === "stopped" ||
    state === "rejected" ||
    state === "cancelled" ||
    state === "canceled" ||
    state === "error" ||
    state === "interrupted" ||
    state === "paused"
  );
}

/** Both success and not-ready replies must answer the exact status request. */
function correlatedStatusReply(reply: unknown, request: unknown): Record<string, unknown> | undefined {
  const env = asRecord(reply);
  const req = asRecord(request);
  if (env?.version !== SUBAGENT_RPC_VERSION || env.method !== "status" || req?.method !== "status") return;
  if (typeof env.requestId !== "string" || !env.requestId || env.requestId !== req.requestId) return;
  return env;
}

/** Native single-run replies carry state in the display header, not `details`.
 * Use the first nonempty `Run:` and the first `State:` after it, never later
 * transcript text that happens to look like a second header.
 */
function parseTargetedStatusText(text: unknown): { runId: string; state: string } | null {
  if (typeof text !== "string") return null;
  let runId = "";
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!runId && line.startsWith("Run:")) runId = line.slice(4).trim();
    else if (runId && line.startsWith("State:")) {
      const state = line.slice(6).trim();
      return state ? { runId, state } : null;
    }
  }
  return null;
}

/** Only exact-target inspections count; `asyncSnapshot` and fleet rows are
 * display projections that can lag behind the executor's authoritative state.
 */
function* targetedStates(data: Record<string, unknown>, details: Record<string, unknown> | undefined, runId: string) {
  const header = parseTargetedStatusText(data.text);
  if (header !== null && header.runId === runId) yield header.state;
  if (data.runId === runId && typeof data.state === "string") yield data.state;
  if (!Array.isArray(details?.runs)) return;
  for (const node of details.runs) {
    const run = asRecord(node);
    if (run && (typeof run.runId === "string" ? run.runId : run.id) === runId) yield run.state;
  }
}

/** Even if whole-tree termination is unknown, a directly observed exit of
 * this run's own runner defeats an active status. A sibling's exit does not.
 */
function runnerHasExited(details: Record<string, unknown> | undefined, runId: string): boolean {
  const terminal = asRecord(asRecord(details?.lifecycleStatus)?.processTerminal);
  if (!terminal || terminal.runId !== runId) return false;
  if (terminal.state === "observed") return true;
  const id = terminal.runnerProcessInstanceId;
  return typeof id === "string" && id.length > 0 && Array.isArray(terminal.instances) &&
    terminal.instances.some((entry) => {
      const instance = asRecord(entry);
      return instance?.kind === "runner" && instance.processInstanceId === id;
    });
}

/** Require at least one active report and no contrary evidence for this run.
 * Liveness is not a delivery lease: the caller separately binds provenance to
 * the witnessing session and process. The RPC does not expose completionOwnerId.
 */
export function rpcReplyProvesCurrentOwner(reply: unknown, request: unknown, runId: string): boolean {
  const env = correlatedStatusReply(reply, request);
  if (env?.success !== true) return false;
  const data = asRecord(env.data);
  if (!data) return false;
  const details = asRecord(data.details);
  if (runnerHasExited(details, runId)) return false;
  let sawActive = false;
  for (const state of targetedStates(data, details, runId)) {
    if (!ownerStateIsActive(state)) return false;
    sawActive = true;
  }
  return sawActive;
}

/** Only `no_active_session` denotes a bridge still initializing; do not retry other failures. */
export function rpcReplyIsBridgeNotReady(reply: unknown, request: unknown): boolean {
  const env = correlatedStatusReply(reply, request);
  return env?.success === false && asRecord(env.error)?.code === "no_active_session";
}
