/**
 * Verification that a WAIT's claimed wake path is CURRENTLY live.
 *
 * A `STATUS:WAIT` is a CLAIM that an automatic wake already owns the resume.
 * Silence is granted only when this module can confirm the named owner from the
 * subagent RPC bridge: the run exists, belongs to THIS session, and is still
 * active in THIS process. Everything else fails closed - an unknown run, a
 * terminal run, a bridge that is not ready, a `fleet` row (whose public `key` is
 * an opaque handle that cannot attest a named run), cached state, or a stale
 * observation all refuse to silence the user.
 *
 * Extracted from `session-supervisor.ts` (formerly lines ~394-849) as a PURE
 * MOVE: no behavior changed.
 */
import { isAbsolutePath, readTranscriptTail, transcriptConfirmsDeliveryEither } from "./transcript.ts";
import { SUBAGENT_RPC_VERSION } from "./protocol.ts";
import type { SupervisorContext } from "./protocol.ts";
import type { WakeProof } from "./wake.ts";

/**
 * The session identity used to bind observed runs.
 *
 * The session MANAGER is consulted first because that is what a real host
 * provides; the direct fields are kept as a fallback for minimal/fixture
 * contexts. An absent identity returns "", and callers treat that as "matches
 * nothing" - never as a match.
 */
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
      // best-effort only
    }
  }
  const file = ctx?.sessionFile;
  if (typeof file === "string" && file.length > 0) return file;
  const id = ctx?.sessionId;
  return typeof id === "string" ? id : "";
}

/**
 * The persisted session transcript path, for the scheduled-task confirmation
 * read (Oracle OPTION D).
 *
 * The REAL host exposes session identity only through
 * `ctx.sessionManager.getSessionFile()`, so that is tried first. A
 * minimal/fixture context supplies the direct `ctx.sessionFile` fallback. This
 * is deliberately SEPARATE from `sessionIdentity`: the identity may legitimately
 * be a bare uuid (as a fixture context supplies), which is not a file path, so
 * the two must not be conflated. An absent path returns "", which makes
 * confirmation impossible and leaves the occurrence ARMED rather than wrongly
 * committed.
 */
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

/**
 * Interpret one owner reply as witnessed-wake proof for THIS session.
 *
 * The reply must (1) name the same item, (2) belong to this session, and
 * (3) report an actively pending state. Anything else - a mismatch, a terminal
 * run, a fleet total, a prefix, an omitted row, a malformed body - is not proof.
 * A fleet count in particular is never evidence about a named item.
 *
 * A PROVIDER owner still attests through this same documented synchronous
 * contract, so the provider shape is preserved. A SUBAGENT owner is proven
 * through the pi-subagents RPC envelope instead; see
 * `rpcReplyProvesCurrentOwner`, which is the only path that can accept it.
 */
export function replyProvesWake(body: unknown, proof: WakeProof, identity: string): boolean {
  if (body === null || typeof body !== "object") return false;
  const reply = body as {
    session?: unknown;
    sessionFile?: unknown;
    id?: unknown;
    item?: unknown;
    state?: unknown;
    status?: unknown;
    pending?: unknown;
    willWake?: unknown;
  };

  const replyIdentity =
    typeof reply.sessionFile === "string"
      ? reply.sessionFile
      : typeof reply.session === "string"
        ? reply.session
        : "";
  // Bind to THIS session: a reply about another session proves nothing about
  // whether this one will ever wake.
  if (identity.length === 0 || replyIdentity !== identity) return false;

  const replyId = typeof reply.id === "string" ? reply.id : typeof reply.item === "string" ? reply.item : "";
  if (replyId !== proof.id) return false;

  if (proof.kind === "provider") {
    // Providers attest through the documented synchronous contract, so the
    // affirmative flags are the proof.
    return reply.pending === true && reply.willWake === true;
  }

  // A subagent reply is NEVER proven through the legacy shape: a `state` string
  // on an unversioned body could come from any emitter. Subagent proof requires
  // the correlated RPC envelope (see `rpcReplyProvesCurrentOwner`).
  return false;
}

/**
 * True for a state in which the run is CURRENTLY active (or genuinely queued).
 *
 * `queued` counts because a queued run has a real scheduling owner that will
 * deliver completion.
 *
 * PG2 - `paused` does NOT count. The runtime's `isTerminalAsyncState`
 * (`workflow-terminal-proof.js:5`) treats `paused` as non-terminal because a
 * paused WORKFLOW may retain live descendants, but that is CAPACITY retention,
 * not automatic-wake liveness. For THIS extension's purpose the two come apart:
 *
 *   - `active-run-index.js:34-35` counts only `queued`/`running` as active;
 *   - `docs/extension-api.md:595` - an interrupted paused run is FINALIZED;
 *   - `run-status.js:791-795` renders `State: paused` from a finalized
 *     interrupted result.
 *
 * So a previously observed run whose paused result was already delivered would,
 * if `paused` counted, earn silence again with NO future automatic wake - the
 * exact silent stall this extension exists to catch. State alone cannot prove a
 * live owner here, so `paused` fails closed and callers must supply separate
 * evidence of current ownership.
 */
export function ownerStateIsActive(state: unknown): boolean {
  return state === "running" || state === "queued";
}

/**
 * PG2: a state that is definitively NOT wake-capable, and therefore a terminal
 * authoritative report.
 *
 * `paused` belongs here (see `ownerStateIsActive`), together with every member
 * of the runtime's `AsyncStatus` union outside the active set. An UNRECOGNIZED
 * state is handled by the caller's default-terminal rule, not by this helper.
 */
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

/**
 * The status line a pi-subagents targeted `status` reply carries in its `text`.
 *
 * The authoritative run state in a targeted reply is NOT a machine field:
 * `dataFromToolResult` (`rpc.js:240-250`) builds `{ text, details?, isError? }`
 * from a tool result, and the single-run `details` is `{ mode: "single",
 * results: [] }` with no `state`/`runId`/`runs[]`. The state lives in the
 * human-readable transcript, formatted as (`run-status.js:80-86`, `:590-593`):
 *
 *     Run: <runId>
 *     State: <state>
 *
 * Both lines are required and BOTH must be present for the body to count as an
 * authoritative report. The state vocabulary is the runtime's own `AsyncStatus`
 * union (`types.d.ts:1825`): `queued | running | complete | failed | partial |
 * paused | stopped | rejected`, and anything the runtime emits outside the
 * active set is terminal by `isTerminalAsyncState`
 * (`workflow-terminal-proof.js:5`) - `state !== "queued" && state !== "running"
 * && state !== "paused"`. Terminal is therefore the DEFAULT: an unrecognized
 * state is terminal, never active, so a new runtime state cannot silently
 * become an acceptance path.
 */
interface TargetedStatusReport {
  runId: string;
  state: string;
}

/**
 * Parse the authoritative `Run:`/`State:` lines out of a targeted status `text`.
 *
 * Returns null when either line is absent, so a reply that merely mentions the
 * run cannot be mistaken for an authoritative report. The FIRST `Run:`/`State:`
 * pair wins; a later identical pair would be part of the transcript below the
 * header, not a second status.
 */
function parseTargetedStatusText(text: unknown): TargetedStatusReport | null {
  if (typeof text !== "string" || text.length === 0) return null;
  let runId: string | null = null;
  let state: string | null = null;
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (runId === null && line.startsWith("Run:")) {
      const value = line.slice("Run:".length).trim();
      if (value.length > 0) runId = value;
      continue;
    }
    if (runId !== null && state === null && line.startsWith("State:")) {
      const value = line.slice("State:".length).trim();
      if (value.length > 0) state = value;
      break;
    }
  }
  if (runId === null || state === null) return null;
  return { runId, state };
}

/**
 * Interpret a pi-subagents RPC reply as CURRENT-OWNER proof for one run.
 *
 * This is the ONLY accepted subagent proof, and it is deliberately narrow. The
 * envelope must be the plugin's own versioned reply, correlated to the exact
 * request this extension sent, and SUCCESSFUL. The `status` payload must then
 * name the exact FULL run id (no prefixes, no normalization).
 *
 * C6 - AUTHORITATIVE STATUS OUTRANKS THE PROJECTED SNAPSHOT. The `status` RPC
 * returns BOTH the executor's own inspected status AND `asyncSnapshot`, which is
 * a SEPARATE display projection built by `buildAsyncStatusSnapshotForState`
 * from `state.asyncJobs`/`fleetJobs`. The projection can lag: it can still say
 * `running` while the authoritative inspected status already reports a terminal
 * run. Correlation proves WHICH request was answered - it does NOT prove every
 * fact inside the reply is fresh. A terminal inspected status therefore DEFEATS
 * a stale `running` snapshot, and the run is not accepted.
 *
 * C6 - DELIVERY-OWNERSHIP CANNOT BE ATTESTED HERE, SO IT FAILS CLOSED.
 * pi-subagents gates result delivery on `completionOwnerId`
 * (`resultDeliveryOwnership.owns(job.sessionId, job.completionOwnerId)`), which
 * is NOT part of the `status` payload this extension receives. After reopening
 * the same session in another process, restored provenance plus an active
 * snapshot could otherwise accept a WAIT even though that runtime does not own
 * result delivery. Since the reply cannot attest the lease, this predicate is
 * documented as NOT attesting it, and callers must not treat it as sufficient
 * on its own for cross-process resumption. liveness within THIS process is what
 * it establishes.
 *
 * A `fleet` entry is NEVER proof: its public `key` is an opaque `fleet-N`
 * handle and its `internalKey` (which embeds the run id) is not part of the
 * public payload, so a fleet row cannot attest a named run. Cached state, an
 * omitted run, an unknown id, and a terminal run all fail closed.
 */
export function rpcReplyProvesCurrentOwner(reply: unknown, request: unknown, runId: string): boolean {
  if (reply === null || typeof reply !== "object" || request === null || typeof request !== "object") {
    return false;
  }
  const env = reply as {
    version?: unknown;
    requestId?: unknown;
    method?: unknown;
    success?: unknown;
    data?: unknown;
  };
  const req = request as { requestId?: unknown; method?: unknown };

  // Correlation: the reply MUST answer THIS request, for THIS method, under the
  // plugin's own protocol version, and MUST have succeeded.
  if (env.version !== SUBAGENT_RPC_VERSION) return false;
  if (env.method !== "status" || req.method !== "status") return false;
  if (typeof env.requestId !== "string" || env.requestId.length === 0) return false;
  if (env.requestId !== req.requestId) return false;
  if (env.success !== true) return false;

  const data = env.data;
  if (data === null || typeof data !== "object") return false;
  const payload = data as {
    asyncSnapshot?: unknown;
    runs?: unknown;
    runId?: unknown;
    state?: unknown;
    details?: unknown;
  };

  // PG3: gather EVERY authoritative targeted observation for THIS run FIRST,
  // and only decide afterwards. The previous shape returned `true` as soon as a
  // compatibility branch saw an active machine field, which let an active
  // `runId`/`details.runs` entry SHORT-CIRCUIT past a terminal report that had
  // already been observed. Two rules are enforced below:
  //
  //   (a) A terminal authoritative report is NEVER overridden by an active one.
  //   (b) An exact-target inspection that reports nothing usable is NOT replaced
  //       by the lagging display snapshot - absence of an authoritative ACTIVE
  //       report is not proof of liveness.
  let sawActiveTargeted = false;
  let sawTerminalTargeted = false;

  // (1) The executor's own inspection, whose state lives in the human-readable
  // `Run:`/`State:` transcript rather than a machine field.
  const targeted = parseTargetedStatusText((payload as { text?: unknown }).text);
  if (targeted !== null && targeted.runId === runId) {
    if (ownerStateIsActive(targeted.state)) sawActiveTargeted = true;
    else sawTerminalTargeted = true;
  }

  // (2) A machine-readable targeted body for the SAME run. Its presence makes
  // this an exact-target inspection, so a terminal report here is authoritative.
  if (payload.runId === runId && typeof payload.state === "string") {
    if (ownerStateIsActive(payload.state)) sawActiveTargeted = true;
    else sawTerminalTargeted = true;
  }

  // (3) A targeted body may nest its inspected run under `details.runs`.**NOTE**
  // this is the TARGETED (`details`) container, not the projected snapshot.
  const details = payload.details;
  if (details !== null && typeof details === "object") {
    const detailRuns = (details as { runs?: unknown }).runs;
    if (Array.isArray(detailRuns)) {
      for (const node of detailRuns) {
        if (node === null || typeof node !== "object") continue;
        const run = node as { runId?: unknown; id?: unknown; state?: unknown };
        const id = typeof run.runId === "string" ? run.runId : run.id;
        if (id !== runId) continue;
        if (ownerStateIsActive(run.state)) sawActiveTargeted = true;
        else sawTerminalTargeted = true;
      }
    }

    // (4) CORR10/NEW-3: the runtime attaches its independently OBSERVED
    // process-exit evidence as `details.lifecycleStatus.processTerminal`
    // (`run-status.js:759`; `state === "observed"` carries `observedAt` and the
    // exited `instances`). A reply can therefore name this exact run, report
    // `State: running`, YET carry observed process termination for that same
    // run - a liveness answer this predicate previously accepted. Matching
    // OBSERVED termination for THIS run is therefore REJECTING evidence.
    //
    // CRITICAL boundary: this is NOT a blanket rejection of the field. `pending`
    // is the valid live-case control (the runner is still starting), and
    // `not-started`/`unknown` WITHOUT close evidence are inconclusive, so none
    // of those rejects. Evidence for a DIFFERENT run never rejects this one.
    const lifecycle = (details as { lifecycleStatus?: unknown }).lifecycleStatus;
    if (lifecycle !== null && typeof lifecycle === "object") {
      const processTerminal = (lifecycle as { processTerminal?: unknown }).processTerminal;
      if (processTerminal !== null && typeof processTerminal === "object") {
        const terminal = processTerminal as {
          state?: unknown;
          runId?: unknown;
          runnerProcessInstanceId?: unknown;
          instances?: unknown;
        };
        // (4a) matched-run `observed` termination remains terminal (unchanged).
        if (terminal.state === "observed" && terminal.runId === runId) {
          sawTerminalTargeted = true;
        }

        // (4b) CORR16 C39-1: an UNKNOWN whole-tree proof retains the directly
        // observed runner exit in `instances` (`process-terminal.js:211-213`,
        // "An unverified process tree still has a directly observed runner exit;
        // keep it for failure reports"). The aggregate `state` is therefore NOT a
        // reliable proxy for run liveness: a reply whose `state` is `"unknown"`
        // can still POSITIVELY prove the runner is GONE. The predicate must
        // consume `instances` so that a valid runner-close record - bound to BOTH
        // this exact `runId` AND the exact `runnerProcessInstanceId` the reply
        // carries - rejects regardless of the aggregate `state`.
        //
        // Strict binding, so only genuine matching provenance inverts the result:
        // the proof must name THIS run; the close must be a `kind: "runner"`
        // record whose `processInstanceId` equals the proof's
        // `runnerProcessInstanceId`; a close belonging to another runner instance
        // or an unrelated child does NOT count. Without BOTH bindings the reply
        // stays accepted (`pending` / `unknown` with no close evidence -> true),
        // so a still-starting runner is never mistaken for a terminated one.
        else if (
          terminal.runId === runId &&
          typeof terminal.runnerProcessInstanceId === "string" &&
          terminal.runnerProcessInstanceId.length > 0 &&
          Array.isArray(terminal.instances) &&
          terminal.instances.some((entry) => {
            if (entry === null || typeof entry !== "object") return false;
            const record = entry as { kind?: unknown; processInstanceId?: unknown };
            return record.kind === "runner" && record.processInstanceId === terminal.runnerProcessInstanceId;
          })
        ) {
          sawTerminalTargeted = true;
        }
      }
    }
  }

  // PG3(a): terminal evidence is authoritative. A run reported terminal by ANY
  // targeted source cannot be re-accepted by a lagging `running` snapshot.
  if (sawTerminalTargeted) return false;

  // PG3(b): an exact-target report that is present but NOT active is a failed
  // inspection, never a fallback. The projected snapshot is a weaker source, and
  // using it here is exactly how a finalized run keeps earning silence.
  //
  // PG3: NO targeted report for this run at all. The reply was produced by an
  // EXACT-TARGET verification (this extension always asks `{runId}`), so a
  // targeted body that fails to name the run is an uninformative answer, not an
  // invitation to consult the lagging display cache. Treating the cached
  // snapshot as proof here is precisely how a completed or finalized run keeps
  // earning silence after its targeted inspection stopped reporting it. The
  // cache is therefore NOT consulted: absence of an authoritative ACTIVE report
  // is never proof of liveness, so this fails closed.
  //
  // Both the "present but inactive" and "absent" cases therefore answer the same
  // way, and liveness is decided SOLELY by `sawActiveTargeted`.
  return sawActiveTargeted;
}

/**
 * CORR10/NEW-2: was this reply a "bridge not yet initialised" refusal?
 *
 * pi-subagents answers `no_active_session` (`rpc.js:582-587`) when its bridge
 * context (`state.lastUiContext`) is not yet set - which is exactly the case
 * during `session_start` in the supported `-e` load order, where this
 * extension's handler runs BEFORE pi-subagents' own registration of that
 * context. Such a reply says NOTHING about the run: it is a transient readiness
 * signal, so `verifyWait` defers and re-asks instead of treating the first
 * refusal as decisive.
 *
 * The check is deliberately NARROW and correlated: it requires the plugin's own
 * versioned envelope, an exact request-id match, `success: false`, and EXACTLY
 * the `no_active_session` error code. Every other failure - `not_found`,
 * `invalid_state`, a malformed or uncorrelated reply - remains decisive and is
 * NOT retried, so genuine rejection is never weakened.
 */
export function rpcReplyIsBridgeNotReady(reply: unknown, request: unknown): boolean {
  if (reply === null || typeof reply !== "object" || request === null || typeof request !== "object") {
    return false;
  }
  const env = reply as {
    version?: unknown;
    requestId?: unknown;
    method?: unknown;
    success?: unknown;
    error?: unknown;
  };
  const req = request as { requestId?: unknown; method?: unknown };
  if (env.version !== SUBAGENT_RPC_VERSION) return false;
  if (env.method !== "status" || req.method !== "status") return false;
  if (typeof env.requestId !== "string" || env.requestId.length === 0) return false;
  if (env.requestId !== req.requestId) return false;
  if (env.success !== false) return false;
  const error = env.error;
  if (error === null || typeof error !== "object") return false;
  return (error as { code?: unknown }).code === "no_active_session";
}

