// Extracted verbatim from session-supervisor.ts (mechanical split; no logic edits).
/**
 * Marker prefix every protocol line starts with, at column zero.
/**
 * The five declared statuses, in the order the protocol lists them.
 *
 * `unknown` is not part of the grammar: it is the value this extension computes
 * when there is no usable marker, and it behaves like "tell the user".
 */
export type DeclaredStatus = "continue" | "wait" | "done" | "blocked" | "failed" | "unknown";

/** Payload-free statuses: nothing may follow the name. */
export const PAYLOAD_FREE_STATUSES = new Set(["done"]);
/** Payload-bearing statuses: a nonempty payload is REQUIRED. */
export const PAYLOAD_REQUIRED_STATUSES = new Set(["continue", "wait", "blocked", "failed"]);

/** One protocol line: `STATUS:` + name + optional payload, no indentation. */
export const PROTOCOL_LINE = /^STATUS:([A-Za-z]+)(?:[ \t]+(.*))?$/i;

/**
 * A single `STATUS:<NAME>` occurrence with no payload and nothing after the
 * name. A prose line that merely shows the options ("STATUS:DONE or
 * STATUS:CONTINUE") is documentation rather than a declaration.
 */
export const LONE_STATUS_WORD = /^STATUS:[A-Za-z]+$/i;

/**
 * Prose that may JOIN two payload-free status words: "STATUS:DONE or
 * STATUS:CONTINUE". Punctuation joiners are handled as token boundaries; these
 * word joiners are the remaining prose forms.
 */
export const PROSE_JOINER = /^(?:or|and|vs\.?|then|else|or else|etc\.?)$/i;

/**
 * Build a mention matcher for ONE declaration token.
 *
 * The declaration-eligibility path needs the narrow question "is THIS token
 * quoted?", so the token is regex-escaped and anchored to its own name.
 */
export function QUOTED_STATUS_MENTION_FOR(token: string): RegExp {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(\`|"|\u201c)${escaped}(\`|"|\u201d)`, "i");
}

/** OSC 777 notification; the transport the surrounding terminal understands. */
export const OSC_NOTIFY = "\x1b]777;notify;Pi;Session needs attention\x07";

/**
 * The macOS sound played for every notification this extension emits.
 *
 * ONE shared sound for every cause, deliberately. Each cause already carries a
 * distinct banner, and an audible tone can only mean "inspect Pi" to someone
 * away from the screen: a code of four tones would demand learning without
 * conveying anything actionable. The causes stay distinguishable in the
 * notification text, where they can actually be read.
 */
export const NOTIFICATION_SOUND = "/System/Library/Sounds/Ping.aiff";

/** Absolute path, so the sound never depends on the caller's `PATH`. */
export const AFPLAY_PATH = "/usr/bin/afplay";

/**
 * OSC 777 notification for a WAIT this extension could not verify.
 *
 * Distinct from the generic notice because the remedy differs: the marker
 * asserted that something would wake the session, and nothing did. A caller
 * reading the generic notice would look for a question to answer; here there is
 * none, and the run is stalled on a claim that did not hold.
 */
export const OSC_NOTIFY_UNVERIFIED_WAIT =
  "\x1b]777;notify;Pi;Unverified WAIT - no confirmed automatic wake path\x07";

/**
 * OSC 777 notification for a user escalation this extension could not verify.
 *
 * Distinct from the generic notice because the remedy differs: the marker
 * ASSERTED that a user owed an answer, and nothing this extension witnessed
 * supports that. A caller reading the generic notice would look for a question
 * to answer; here there may be none, and the stop was a claim that did not hold.
 * The wording deliberately does NOT imply the user owes an option selection.
 */
export const OSC_NOTIFY_UNVERIFIED_ESCALATION =
  "\x1b]777;notify;Pi;Unverified user escalation - no confirmed user dependency\x07";

/**
 * Replace every character that could break out of an OSC 777 payload.
 *
 * The OSC 777 sequence is `ESC ] 777 ; notify ; <text> BEL`. `<text>` is
 * terminated ONLY by BEL (`\x07`), so any control byte (BEL, ESC, CR, LF, ...)
 * or non-ASCII byte inside model-authored text could terminate the sequence early
 * and let the model inject terminal control. The task id is model-chosen
 * (`parseTaskAdd` accepts any nonempty trimmed string), so it MUST be sanitized
 * before it reaches an escape sequence: keep printable ASCII (`\x20`-`\x7e`),
 * replace everything else with `?`. Printable ASCII cannot terminate the
 * sequence and cannot begin a new escape.
 */
export function sanitizeOscField(value: string): string {
  return value.replace(/[^\x20-\x7e]/g, "?");
}

/**
 * How long a completed WAIT may stay silent while its wake proof is checked.
 *
 * Bounded and short by design: this delays the notification, never the
 * continuation, and a wake path that has not reported in within this window is
 * unverified rather than assumed. One second is comfortably longer than an
 * in-process check and far shorter than a user would notice as latency.
 */
export const WAIT_VERIFICATION_MS = 1000;

/**
 * CORR10/NEW-2: how many times a `no_active_session` reply is retried before it
 * is treated as a genuine failure, and how long to wait between attempts.
 *
 * In the supported `-e` load order this extension's `session_start` handler runs
 * BEFORE pi-subagents' own, so its bridge context (`state.lastUiContext`) is not
 * yet set and an immediate `status` request is answered `no_active_session`
 * (`rpc.js:582-587`) even though the run is genuinely live. That reply is a
 * "bridge not yet initialised" signal, NOT evidence about the run, so a bounded
 * deferral gives the peer bridge time to initialise instead of falsely rejecting
 * a valid WAIT. `not_found`/`invalid_state`/terminal answers are decisive and are
 * NEVER retried - only the not-ready code is.
 */
export const WAIT_BRIDGE_NOT_READY_RETRIES = 3;
export const WAIT_BRIDGE_NOT_READY_RETRY_MS = 200;

/**
 * How long after a VERIFIED WAIT the owner is rechecked for liveness.
 *
 * Verification proves the owner is live NOW; it says nothing about the next
 * minute. One observational recheck confirms the same run is still active, and
 * a recheck that finds the owner gone fires the unverified notice instead of
 * leaving the run silently stalled. Long enough not to fire on ordinary
 * scheduling jitter, short enough to catch a child that died quietly.
 */
export const WAIT_RECHECK_MS = 60_000;

/**
 * The pi-subagents RPC transport this extension uses to prove a WAIT.
 *
 * These are the plugin's own v1 RPC topics. A request is emitted on the request
 * topic and the correlated answer arrives on a per-request reply topic, so a
 * reply can be matched to the exact request rather than raced against a shared
 * channel. `status` is a READ-ONLY method: it reports what the owner already
 * knows and never launches, resumes, or cancels a run.
 */
export const SUBAGENT_RPC_REQUEST_TOPIC = "subagents:rpc:v1:request";
export const SUBAGENT_RPC_READY_TOPIC = "subagents:rpc:v1:ready";
export const SUBAGENT_RPC_REPLY_PREFIX = "subagents:rpc:v1:reply:";
export const SUBAGENT_RPC_VERSION = 1;

/**
 * The versioned customType under which OBSERVED-RUN PROVENANCE is persisted.
 *
 * Only provenance is persisted: which session/epoch a run was witnessed under,
 * never a verification result, a timer, or an execution permit. A persisted
 * permit would outlive the run it described and silence a later, genuinely
 * unverified WAIT; provenance merely lets a resumed session re-evaluate the
 * SAME run against the owner again.
 */
export const PROVENANCE_CUSTOM_TYPE = "session-supervisor:provenance:v1";

/**
 * A durable REQUEST-GENERATION marker (protocol version 1).
 *
 * R6-6: `observationEpoch` is a local counter that restarts at 0 whenever the
 * module is re-evaluated by a reload, so after a reload it cannot tell whether
 * the request in progress is the one that witnessed a given run. Comparing a
 * restored record to a reset counter therefore made a run from an EARLIER
 * request eligible again, with no new START - exactly the corroboration a
 * request replacement had already rejected.
 *
 * This marker is persisted on every request boundary (`observationEpoch`
 * advance) so the LATEST generation that occurred is durable, independent of
 * any run. A restored record is admitted only when its own generation matches
 * the latest persisted generation; a reload during a LATER request restores the
 * later generation and the older record stays ineligible.
 */
export const REQUEST_GENERATION_CUSTOM_TYPE = "session-supervisor:request-generation:v1";

/** customType identifying the hidden bridge entry this extension appends. */
export const BRIDGE_CUSTOM_TYPE = "session-supervisor:auto-continuation";

/**
 * customType identifying a DECISION-REPAIR bridge entry.
 *
 * A distinct type from `BRIDGE_CUSTOM_TYPE` so a reader (and the tests) can
 * tell an ordinary continuation from a repair of an unsupported stop, even
 * though both are charged to the SAME continuation budget.
 */
export const REPAIR_CUSTOM_TYPE = "session-supervisor:decision-repair";

/** Title line of the bridge message, kept for readability in transcripts. */
export const BRIDGE_HEADER = "[session-supervisor:continue]";

/** Title line of the decision-repair bridge message. */
export const REPAIR_HEADER = "[session-supervisor:decision-repair]";

/** Default: no automatic-continuation count limit for a genuine request. */
export const DEFAULT_MAX_CONTINUATIONS = Number.POSITIVE_INFINITY;

/**
 * Largest accepted opt-in finite budget, keeping decimal parsing and decrement
 * exact. This is a numeric representation limit, not the default continuation
 * policy: the default is unlimited. Larger decimal values clamp here with a
 * warning.
 */
export const HARD_MAX_CONTINUATIONS = Number.MAX_SAFE_INTEGER;

/**
 * Resolve the continuation policy once per extension registration. Unset or
 * blank means unlimited; `0` disables automatic continuation. Exact
 * nonnegative decimal integers configure a finite per-request allowance.
 * Malformed values warn once and use the unlimited default. Values above
 * `HARD_MAX_CONTINUATIONS` warn once and clamp to that numeric
 * representation limit.
 */
export function resolveMaxContinuations(
  raw: string | undefined,
  warn: (message: string) => void = () => {},
): number {
  if (raw === undefined || raw.trim() === "") return DEFAULT_MAX_CONTINUATIONS;
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    warn(
      `PI_MAX_CONTINUATIONS=${JSON.stringify(raw)} is not a plain integer; using unlimited continuation (the default)`,
    );
    return DEFAULT_MAX_CONTINUATIONS;
  }
  const value = Number(trimmed);
  if (value > HARD_MAX_CONTINUATIONS) {
    warn(
      `PI_MAX_CONTINUATIONS=${trimmed} exceeds the largest exact finite budget ${HARD_MAX_CONTINUATIONS}; clamping to ${HARD_MAX_CONTINUATIONS}`,
    );
    return HARD_MAX_CONTINUATIONS;
  }
  return value;
}

/** Minimal shape of the handler context Pi passes as the second argument. */
export interface SupervisorContext {
  hasUI: boolean;
  mode: "tui" | "rpc" | "json" | "print";
  /** Read-only session view, used to read the final projected message. */
  sessionManager?: ReadonlySessionView;
  /** Host idle check; absent in minimal test contexts, so always optional. */
  isIdle?: () => boolean;
  /** Optional session identity, used to bind wake proof to THIS session. */
  sessionFile?: string;
  sessionId?: string;
  /**
   * Terminal UI surface, read ONLY to observe a raw interrupt for the idle
   * auto-continue user-stop latch.
   *
   * Optional: a minimal host or a headless context simply exposes no
   * `onTerminalInput`, so no interrupt can be observed. That fails CLOSED for
   * abort precedence (the latch stays unset) - the cooldown still bounds
   * nudging, so an unobservable interrupt can never wedge the feature.
   */
  ui?: {
    onTerminalInput?: (handler: TerminalInputHandler) => unknown;
  };
};

/**
 * The raw terminal-input handler shape the installed TUI exposes.
 *
 * `TerminalInputHandler = (data: string) => { consume?: boolean; data?: string }
 * | undefined`. Returning `undefined` leaves the input COMPLETELY untouched
 * (neither consumed nor rewritten), which is exactly what an OBSERVATIONAL
 * interrupt listener must do: this extension reads a subset of interrupt bytes
 * to set the user-stop latch and must never alter or swallow any input.
 */
export type TerminalInputHandler = (data: string) => { consume?: boolean; data?: string } | undefined;

/** Minimal shape of `ReadonlySessionManager` this extension reads. */
export interface ReadonlySessionView {
  /** Real-host identity accessors. `createContext()` supplies no direct fields. */
  getSessionFile?: () => string | undefined;
  getSessionId?: () => string | undefined;
  buildSessionProjection?: () => { messages?: unknown[] };
  /**
   * The session's persisted ENTRIES, read on reload to restore provenance.
   *
   * Custom entries written by this extension are filtered out of the model
   * context, so recovering them is the only way a reloaded session can remember
   * WHICH runs it once witnessed. Optional: an absent reader simply restores
   * nothing, which can only make a WAIT unverified - never silence one.
   */
  getEntries?: () => unknown[];
  getBranch?: (fromId?: string | null) => unknown[];
}

/** Result a boundary handler may return; `continue` requests one more request. */
export interface SupervisorHandlerResult {
  entries?: unknown[];
  continue?: boolean;
}

/** Minimal shape of the Pi extension API passed to the default factory. */
export interface SupervisorApi {
  on: (
    event: string,
    handler: (
      event: unknown,
      ctx: SupervisorContext,
    ) => SupervisorHandlerResult | void | Promise<SupervisorHandlerResult | void>,
  ) => void;
  /**
   * Optional: used for the Zellij flag pipe AND best-effort notification audio.
   *
   * Both uses are fire-and-forget and failure-isolated from each other and from
   * the OSC write. A host that omits it still notifies visually and silently.
   */
  exec?: (command: string, args: string[]) => unknown;
  /**
   * Optional event bus, used ONLY to ask a wake-path owner whether it still owns
   * pending work. Never used to launch, resume, or cancel anything.
   */
  events?: SupervisorEventBus;
  /**
   * Persist a hidden extension entry into the session (NOT sent to the LLM).
   *
   * Used solely to record OBSERVED-RUN PROVENANCE across a reload. Optional: a
   * host without it keeps provenance in memory only, which can make a reloaded
   * WAIT unverified - never silently verified.
   */
  appendEntry?: (customType: string, data?: unknown) => void;
  /**
   * Deliver a user message that drives a turn in THIS session.
   *
   * The scheduled-task dispatcher (FEATURE 3) fires through this, not through
   * `sendMessage({triggerTurn:true})`: the confirmed real host surface is a
   * plain text delivery. Optional so a minimal host or test API can omit it, in
   * which case a due task simply does not inject.
   *
   * `deliverAs` maps to the host's `streamingBehavior`. It is declared because a
   * send must carry a delivery mode while the session is streaming or compacting,
   * or the host REJECTS it - see `pumpTask`.
   */
  sendUserMessage?: (text: string, options?: { deliverAs?: "steer" | "followUp" | "nextTurn" }) => unknown;
  /**
   * Register a tool. Optional: a host without it registers no scheduler tools, so
   * the scheduler stays inert (the safe degradation for a minimal host).
   */
  registerTool?: ToolRegistrationApi["registerTool"];
}


// --- Scheduled tasks (FEATURE 3) -----------------------------------------
//
// A session-local, REMINDER-ONLY scheduler. The model creates reminders through
// three registered tools (`schedule_task`, `cancel_task`, `list_tasks`), and
// this extension fires `api.sendUserMessage` into the SAME session when a
// reminder comes due. The design (settled) is CLAIM-BEFORE-SEND with at-most-one
// automatic submission per occurrence:
//
//   * structural invariant: an occurrence with a durable claim (`occurrenceId`
//     set) is NEVER automatically eligible again;
//   * the claim is persisted BEFORE the send, with NO await between the final
//     eligibility check, the claim write, and the submission;
//   * uncertainty never clears a claim - a claimed occurrence is inert until
//     POSITIVE transcript evidence reconciles it;
//   * storage is a per-session snapshot plus an exclusive ownership lock.

/**
 * The minimal shape of the `registerTool` surface this extension reads.
 *
 * A host that does not expose it simply registers no task tools (the scheduler
 * remains inert), which is the safe degradation for a minimal host.
 */
export interface ToolRegistrationApi {
  registerTool?: (definition: {
    name: string;
    description?: string;
    parameters?: unknown;
    exposure?: "direct";
    annotations?: {
      readOnlyHint?: boolean;
      destructiveHint?: boolean;
      idempotentHint?: boolean;
      openWorldHint?: boolean;
    };
    execute?: (
      // The real host calls `execute(toolCallId, params, signal, onUpdate, ctx)`
      // (1.2.0 `core/extensions/types.d.ts`, forwarded positionally by
      // `core/tools/tool-definition-wrapper.js`), so parameters are the SECOND
      // argument. Reading argument 1 as params would pass a string tool call id
      // to the tool. `toolCallId` is accepted first and ignored.
      toolCallId: unknown,
      args: unknown,
      ctx?: unknown,
    ) =>
      | { content: { type: "text"; text: string }[]; details: Record<string, unknown>; isError?: true }
      | Promise<{ content: { type: "text"; text: string }[]; details: Record<string, unknown>; isError?: true }>;
  }) => unknown;
}

/**
 * Minimal event-bus shape for owner-attested wake proof AND observed-run
 * evidence.
 *
 * Two surfaces, both optional so a minimal host or test bus may omit either:
 *
 *   `request` is the narrow owner-attestation pair keyed by a caller-chosen id.
 *   A missing bus, an unsupported topic, a throwing subscriber, or a reply that
 *   never arrives all resolve to "unverified", which notifies - never to an
 *   assumption of wake ownership.
 *
 *   `on` subscribes to SETTLED lifecycle topics so this extension can build a
 *   request-scoped ledger of async runs it personally WITNESSED start. The two
 *   topics are registered exactly once per registration; a missing `on`, a
 *   throwing subscriber, or an unknown topic shape leaves the ledger empty,
 *   which can only make an escalation unverified - never authorize one.
 */
export interface SupervisorEventBus {
  request?: (topic: string, payload: unknown) => unknown;
  emit?: (topic: string, payload: unknown) => unknown;
  on?: (topic: string, listener: (event: unknown) => void) => void;
  off?: (topic: string, listener: (event: unknown) => void) => void;
  removeListener?: (topic: string, listener: (event: unknown) => void) => void;
}

/**
 * Tokens accepted as the terminal transition of a start form, so a model that
 * binds a completion event (rather than a status) is still self-describing.
 */
export const START_FORM_EVENTS = new Set(["started", "start", "launched", "running", "queued"]);

/** Cap on a bounded completion artifact, so one huge log cannot wedge a settle. */
export const MAX_RESULT_ARTIFACT_BYTES = 2 * 1024 * 1024;

