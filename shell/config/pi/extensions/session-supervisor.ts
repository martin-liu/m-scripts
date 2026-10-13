// Pi extension: notify the surrounding terminal when the agent settles without
// having said what happens next, and continue automatically when the agent
// DECLARED that concrete work remains.
//
// The design is marker-declared, not classifier-guessed. The model ends its
// final assistant message with one line naming its own status
// (`STATUS:CONTINUE <next step>`, `WAIT`, `DONE`, `BLOCKED`, `FAILED`), and
// this extension reads that line synchronously at the settle boundary. There is
// no extra model call, no plan file, and no host-specific bookkeeping.
//
// Marker PARSING is syntactic; EVIDENCE VERIFICATION is separate and applies
// only where a marker tries to take something from the user. This extension
// does NOT classify natural-language prose to decide ownership, scope, or
// whether a dependency is agent- or user-owned: general NL ownership
// classification is explicitly rejected. Instead it reads two structured
// marker grammars and verifies them against artifacts it observed directly.
//
//   * `STATUS:WAIT` silences the user only when the named wake path is proven to
//     exist AND to be CURRENTLY live (see "WAIT IS VERIFIED, NOT TRUSTED"
//     below). A witnessed START is not enough: provenance records only that the
//     run was seen to begin, and a live owner must confirm it is still active.
//
//   * `STATUS:BLOCKED user oracle=<run-id> dependency=<dependency-id> <desc>`
//     permits a user question only when the referenced async run was witnessed
//     to START as Oracle in THIS parent session during the CURRENT request
//     epoch, COMPLETED SUCCESSFULLY, and its actual final result carries a
//     versioned `USER_INPUT_REQUIRED` assessment whose dependency ID matches and
//     whose `question` is repeated by a unique eligible `USER_QUESTION:` line.
//     A completed Oracle run alone is insufficient: it may be a Review, a
//     technical recommendation, a failed assessment, or about another
//     dependency.
//
//   * `STATUS:BLOCKED external owner=<nonhuman-owner> <desc>` names a nonhuman
//     external dependency and needs no Oracle proof. It is never an ungated
//     question.
//
// Anything else - an unstructured `BLOCKED`, an invalid user proof, or a
// `CONTINUE` whose payload leads with a human-wait clause - is stopped at the
// settle boundary and offered a decision-repair bridge governed by the SAME
// continuation policy. Missing evidence never authorizes an effect and
// never establishes that the dependency is agent-owned.
//
// GOVERNING PRINCIPLE: notify when not sure. Every branch in which this
// extension cannot determine whether Pi is idle defaults to notifying the user,
// never to silence.
//
// WAIT IS VERIFIED, NOT TRUSTED. `STATUS:WAIT` claims that an established
// automatic wake-up path already owns the resume, and a claim that silences the
// user is the one claim this extension must not take on faith: a model that
// declares WAIT and merely stops - naming work it never started - would
// otherwise stall an unattended run permanently and silently. So a completed
// WAIT defers notification through a short verification window; permanent
// silence requires CURRENT-OWNER proof that the named run exists, belongs to
// THIS session, and is still active or genuinely queued with an automatic
// completion-delivery path. Absent, malformed, expired, ignored, terminal, or
// foreign evidence resolves to UNVERIFIED and notifies; a verified owner is
// rechecked once after a bounded idle interval, and a worker that has
// disappeared by then notifies too. Verification never launches, resumes, or
// cancels anything: the `status` RPC method is read-only.
//
// Notification scope: TUI sessions only. A settle caused by launching detached
// background work used to need a disk-forensics liveness check; under this
// design the model simply declares `STATUS:WAIT <pending event>` instead, so a
// detached child never has to be discovered from the outside.
//
// Continuation scope: `agent_before_settle` is the only boundary that can ask
// for one more model request; `agent_settled` is notification-only. Because the
// marker line leaves the final projected role as `assistant`, Pi would refuse a
// bare `continue: true` (`contextCanContinue = hasNonSystemContext &&
// finalRole !== "assistant"`), so the proposal appends a hidden bridge message
// that restates the declared next step and grants NO new authorization.

/**
 * Marker prefix every protocol line starts with, at column zero.
 *
 * Build prompt text from this constant so the documented grammar and the parsed
 * grammar can never drift apart.
 */
export const STATUS_PREFIX = "STATUS:";

/**
 * The five declared statuses, in the order the protocol lists them.
 *
 * `unknown` is not part of the grammar: it is the value this extension computes
 * when there is no usable marker, and it behaves like "tell the user".
 */
export type DeclaredStatus = "continue" | "wait" | "done" | "blocked" | "failed" | "unknown";

/** Payload-free statuses: nothing may follow the name. */
const PAYLOAD_FREE_STATUSES = new Set(["done"]);
/** Payload-bearing statuses: a nonempty payload is REQUIRED. */
const PAYLOAD_REQUIRED_STATUSES = new Set(["continue", "wait", "blocked", "failed"]);
/** Every grammar word, payload-free and payload-bearing alike. */
const KNOWN_STATUSES = new Set([...PAYLOAD_FREE_STATUSES, ...PAYLOAD_REQUIRED_STATUSES]);

/** One protocol line: `STATUS:` + name + optional payload, no indentation. */
const PROTOCOL_LINE = /^STATUS:([A-Za-z]+)(?:[ \t]+(.*))?$/i;

/**
 * A single `STATUS:<NAME>` occurrence with no payload and nothing after the
 * name. A prose line that merely shows the options ("STATUS:DONE or
 * STATUS:CONTINUE") is documentation rather than a declaration.
 */
const LONE_STATUS_WORD = /^STATUS:[A-Za-z]+$/i;

/**
 * Prose that may JOIN two payload-free status words: "STATUS:DONE or
 * STATUS:CONTINUE". Punctuation joiners are handled as token boundaries; these
 * word joiners are the remaining prose forms.
 */
const PROSE_JOINER = /^(?:or|and|vs\.?|then|else|or else|etc\.?)$/i;

/**
 * A status word wrapped in quotation marks: an EXAMPLE, not a declaration.
 *
 * The opener may follow any character (`or`STATUS:WAIT child``) and the closing
 * quote may be the opener or a closing curly quote. The payload, if any, may
 * itself contain the OTHER delimiter ("STATUS:WAIT `child`"), so the payload is
 * matched non-greedily up to the closing quote rather than by an allow-list of
 * characters.
 */
const QUOTED_STATUS_MENTION = /(`|"|\u201c)STATUS:[A-Za-z]+(?:[ \t][^]*?)?(?:\1|\u201d)/gi;

/**
 * Build a mention matcher for ONE declaration token.
 *
 * `QUOTED_STATUS_MENTION` matches any quoted status word and is used where a
 * whole-line scan is correct. The declaration-eligibility path needs the narrower
 * question "is THIS token quoted?", so the token is regex-escaped and anchored to
 * its own name. Keeping both derived from the same shape avoids the duplicated
 * -rule drift that caused most defects in this unit.
 */
function QUOTED_STATUS_MENTION_FOR(token: string): RegExp {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(\`|"|\u201c)${escaped}(\`|"|\u201d)`, "i");
}

/** OSC 777 notification; the transport the surrounding terminal understands. */
export const OSC_NOTIFY = "\x1b]777;notify;Pi;Session needs attention\x07";

/**
 * OSC 777 notification for a spent automatic-continuation budget. Distinct from
 * the generic notice so an unattended run reports a resource-limited stop rather
 * than implying it is waiting on a human answer.
 */
export const OSC_NOTIFY_BUDGET_EXHAUSTED =
  "\x1b]777;notify;Pi;Automatic continuation budget exhausted - work remains\x07";

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
 * The OSC 777 notice for a REJECTED scheduled task.
 *
 * g3 blocker 2: the oversize refusal passed its diagnostic text into `notify`'s
 * `why` ENUM argument, so the text was discarded and the only observable output
 * was the generic "Session needs attention" (which notification dedup could also
 * suppress). A refusal must be observable and must name the refusal, the id and
 * the limit - without inserting RAW model-authored bytes into the escape
 * sequence, which `sanitizeOscField` enforces. `reason` is caller-constructed
 * static text plus numbers, never model bytes.
 */
export function taskRejectionNotice(reason: string, taskId: string): string {
  return `\x1b]777;notify;Pi;scheduled task id ${sanitizeOscField(taskId)} rejected: ${reason}\x07`;
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
};

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

/** The hidden draft appended to make a declared CONTINUE or a repair runnable. */
type BridgeEntry = ReturnType<typeof buildBridgeEntry> | ReturnType<typeof buildRepairEntry>;

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
  /** Optional: used only for the zellij flag pipe, never for notification. */
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
   * or the host REJECTS it - see `injectTask`.
   */
  sendUserMessage?: (text: string, options?: { deliverAs?: "steer" | "followUp" | "nextTurn" }) => unknown;
}

import { closeSync, mkdirSync, openSync, readFileSync, readSync, renameSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

// --- Scheduled tasks (FEATURE 3) -----------------------------------------
//
// A durable, session-owned timer: the model declares a task on an action line,
// and this extension fires `api.sendUserMessage` into the SAME session when the
// task comes due. Persistence is one atomically replaced JSON file of task
// records; the sole durable owner field is `sessionId`. The design (settled):
// re-armed `setTimeout`s driven by a persisted due time, a TRANSIENT per-
// registration fence checked immediately before injection, a due cursor that is
// advanced/removed DURABLY before dispatch (so a crash cannot re-fire), overdue
// occurrences coalesced into ONE immediate check, and `TASK:CANCEL` consumed at
// the settle boundary.

/** The action-line prefix for a scheduling statement, at column zero. */
export const TASK_ACTION_PREFIX = "TASK:";

/**
 * One task record as persisted (and read back).
 *
 * FEATURE 3 / Oracle OPTION D (tagged durable outbox): the record ITSELF is the
 * outbox. `occurrenceId` names the one occurrence currently ARMED (attempted but
 * not yet POSITIVELY confirmed as persisted). It is persisted so a restart can
 * re-attempt the SAME occurrence at least once rather than losing it or firing a
 * fresh one. `nextRunAtMs` is NOT moved until confirmation: an interval's new
 * cursor is held in `pendingAdvanceTo` (computed when the occurrence was armed)
 * and committed only once the transcript row for `occurrenceId` is seen. Every
 * retry reuses the SAME `occurrenceId`; a fresh id is minted only when an
 * interval cursor actually advances or a task is created/replaced.
 */
export interface ScheduledTask {
  id: string;
  sessionId: string;
  prompt: string;
  nextRunAtMs: number;
  intervalMs?: number;
  /** The occurrence currently armed (attempted, not yet confirmed). */
  occurrenceId?: string;
  /** The interval cursor to commit when `occurrenceId` is confirmed. */
  pendingAdvanceTo?: number;
}

/**
 * The resolved Pi agent directory.
 *
 * Resolved the same way the surrounding Pi ecosystem does: the `PI_CODING_AGENT_DIR`
 * override (with `~` expansion) when set, else `~/.pi/agent`. There is no
 * in-repo helper for this, so the extension mirrors the host convention rather
 * than hard-coding a home path.
 */
export function resolvePiAgentDir(env: { PI_CODING_AGENT_DIR?: string } = process.env): string {
  const override = env.PI_CODING_AGENT_DIR;
  if (typeof override === "string" && override.length > 0) {
    if (override === "~") return homedir();
    if (override.startsWith("~/")) return join(homedir(), override.slice(2));
    return override;
  }
  return join(homedir(), ".pi", "agent");
}

/** The default path of the scheduled-task store. */
export function defaultTasksPath(env: { PI_CODING_AGENT_DIR?: string } = process.env): string {
  return join(resolvePiAgentDir(env), "session-supervisor", "tasks.json");
}

/**
 * Advance an interval due time to the first occurrence STRICTLY after `nowMs`.
 *
 * Coalesces any number of missed occurrences into the single next future slot,
 * so an overdue interval task fires once and then resumes its cadence from the
 * actual firing - never a backlog. A non-positive interval is treated as a
 * one-shot by the caller, so this is only reached with a positive interval.
 */
export function advanceDuePast(intervalMs: number, fromMs: number, nowMs: number): number {
  if (intervalMs <= 0) return nowMs;
  let next = fromMs;
  while (next <= nowMs) next += intervalMs;
  return next;
}

/** A parsed `TASK:` action line. */
export interface TaskAction {
  verb: "add" | "cancel";
  /** For `add`: the JSON body. For `cancel`: the raw id token. */
  body: string;
}

/**
 * Extract `TASK:` action lines from a final assistant message.
 *
 * Only a line whose FIRST characters are `TASK:` at column zero is an action
 * line, matching how `STATUS:` declarations are recognized. This keeps a
 * `TASK:CANCEL` mention inside a `STATUS:` payload (same line) from being read
 * as an action, and realizes the artifact's "action line ABOVE the final STATUS
 * marker" - the parser simply scans every line and the marker line is not a
 * `TASK:` line.
 */
export function parseTaskActions(
  text: string,
  structure?: LineStructure,
): TaskAction[] {
  const actions: TaskAction[] = [];
  // CR NORMALIZATION (bounded re-review F6): `lineStructure` normalizes bare CRs
  // before parsing, but this scanner splits the raw string on LF only, so a CR
  // shifted every subsequent index and the ownership lookup read the WRONG line.
  // `"intro\r```yaml\nTASK:CANCEL keep\n```"` consulted the fence OPENER's index
  // for the fenced action. Normalize identically here so the indices agree.
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].replace(/\s+$/, "");
    if (!/^TASK:/i.test(line)) continue;
    // MARKDOWN OWNERSHIP (final review F6, corrected here). `inside` is FENCE
    // membership only, so the first fix still executed a `TASK:` line inside an
    // HTML block or a LAZY block-quote/list continuation. The right distinction
    // is DOCUMENT-LEVEL content versus container/code content, which is exactly
    // `topLevel` - the line's innermost block is a document-level paragraph.
    //
    // Note this deliberately does NOT reuse the `paragraphStart` policy that
    // guards `STATUS:`: that policy exists because a declaration must not sit
    // beneath prose, but a `TASK:` action is a command, not a declaration, and
    // legitimate adjacent top-level actions need not each begin a paragraph.
    //
    // When no structure is supplied (raw unit tests of the scanner) the check is
    // skipped; every production caller supplies it.
    if (structure !== undefined) {
      if (structure.inside[index]) continue;
      if (!structure.topLevel[index]) continue;
    }
    const rest = line.slice(TASK_ACTION_PREFIX.length).trim();
    const space = rest.search(/\s/);
    const verb = (space < 0 ? rest : rest.slice(0, space)).toLowerCase();
    const body = space < 0 ? "" : rest.slice(space + 1).trim();
    if (verb === "add" || verb === "cancel") actions.push({ verb, body });
  }
  return actions;
}

/**
 * Validate one `TASK:ADD` JSON body into a task record, or null when malformed.
 *
 * Required: a nonempty string `id` and `prompt`, and a finite non-negative
 * numeric `delayMs`. Optional `intervalMs` must be a positive finite number.
 * `sessionId` and the absolute due time are supplied by the caller (which owns
 * the live session and the clock), never by the model's body.
 */
export function parseTaskAdd(body: string): { id: string; prompt: string; delayMs: number; intervalMs?: number } | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const candidate = parsed as { id?: unknown; prompt?: unknown; delayMs?: unknown; intervalMs?: unknown };
  if (typeof candidate.id !== "string" || candidate.id.trim().length === 0) return null;
  if (typeof candidate.prompt !== "string" || candidate.prompt.length === 0) return null;
  if (typeof candidate.delayMs !== "number" || !Number.isFinite(candidate.delayMs) || candidate.delayMs < 0) return null;
  const result: { id: string; prompt: string; delayMs: number; intervalMs?: number } = {
    id: candidate.id.trim(),
    prompt: candidate.prompt,
    delayMs: candidate.delayMs,
  };
  if (candidate.intervalMs !== undefined) {
    if (typeof candidate.intervalMs !== "number" || !Number.isFinite(candidate.intervalMs) || candidate.intervalMs <= 0) return null;
    result.intervalMs = candidate.intervalMs;
  }
  return result;
}

/**
 * Parse the persisted store, returning `null` when the TEXT is not a valid store
 * (malformed JSON, a non-object top level, or a non-array `tasks`) and the
 * validated task list otherwise.
 *
 * The null/PARSED distinction is load-bearing in `persistTasks` (g4 B1): a
 * malformed store must NOT be mistaken for an authoritative EMPTY snapshot,
 * because that mistake licenses a prune-and-replace of a store whose contents
 * were never actually read. A legitimately empty `{"tasks": []}` store parses
 * to `[]` and IS authoritative. Individual records that fail validation are
 * still skipped; their absence does not make the whole store invalid.
 */
export function parseTaskStoreStrict(text: string): ScheduledTask[] | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object") return null;
  const raw = (parsed as { tasks?: unknown }).tasks;
  if (!Array.isArray(raw)) return null;
  const tasks: ScheduledTask[] = [];
  for (const entry of raw) {
    if (entry === null || typeof entry !== "object") continue;
    const candidate = entry as { id?: unknown; sessionId?: unknown; prompt?: unknown; nextRunAtMs?: unknown; intervalMs?: unknown; occurrenceId?: unknown; pendingAdvanceTo?: unknown };
    if (typeof candidate.id !== "string" || candidate.id.length === 0) continue;
    if (typeof candidate.sessionId !== "string") continue;
    if (typeof candidate.prompt !== "string") continue;
    if (typeof candidate.nextRunAtMs !== "number" || !Number.isFinite(candidate.nextRunAtMs)) continue;
    const task: ScheduledTask = {
      id: candidate.id,
      sessionId: candidate.sessionId,
      prompt: candidate.prompt,
      nextRunAtMs: candidate.nextRunAtMs,
    };
    if (typeof candidate.intervalMs === "number" && Number.isFinite(candidate.intervalMs) && candidate.intervalMs > 0) {
      task.intervalMs = candidate.intervalMs;
    }
    // The outbox fields round-trip so an armed-but-unconfirmed occurrence
    // survives a restart; an invalid value is dropped (the occurrence is simply
    // re-armed with a fresh id, which is the safe at-least-once direction).
    if (typeof candidate.occurrenceId === "string" && candidate.occurrenceId.length > 0) {
      task.occurrenceId = candidate.occurrenceId;
    }
    if (typeof candidate.pendingAdvanceTo === "number" && Number.isFinite(candidate.pendingAdvanceTo)) {
      task.pendingAdvanceTo = candidate.pendingAdvanceTo;
    }
    tasks.push(task);
  }
  return tasks;
}

/** Parse the persisted store, ignoring any record that does not validate. */
export function parseTaskStore(text: string): ScheduledTask[] {
  return parseTaskStoreStrict(text) ?? [];
}

/** Serialize the store in its persisted shape. */
export function serializeTaskStore(tasks: ScheduledTask[]): string {
  return JSON.stringify({ version: 1, tasks }, null, 2);
}

/**
 * The scheduler-owned correlation envelope for one armed occurrence.
 *
 * Oracle OPTION D: the injected message carries a FIXED, machine-recognizable
 * line naming the task and the OPAQUE `occurrenceId`. Confirmation requires this
 * EXACT line in a `role: "user"` PERSISTED transcript row, so an assistant that
 * merely ECHOES the text can never confirm delivery. The envelope folds in the
 * former `[task <id>]` prefix convention, so the line remains the first line of
 * the injected message.
 */
export function taskOccurrenceEnvelope(taskId: string, occurrenceId: string): string {
  return `[task ${taskId} occurrence ${occurrenceId}]`;
}

/**
 * The model-visible firing prompt: the correlation envelope line then the
 * declared prompt. The STORED `task.prompt` is never modified; only the injected
 * copy is prefixed.
 */
export function taskFiringPrompt(task: ScheduledTask): string {
  const occurrenceId = task.occurrenceId ?? "";
  return `${taskOccurrenceEnvelope(task.id, occurrenceId)}\n${task.prompt}`;
}

/** Bounded retry while an injected turn is still in flight, so a busy handoff
 * defers without a tight loop and without dropping the occurrence. */
export const TASK_BUSY_RETRY_MS = 1000;

/**
 * Bounded confirmation schedule (Oracle OPTION D).
 *
 * After a send is ATTEMPTED the scheduler polls the PERSISTED TRANSCRIPT for the
 * matching envelope. The host emits `message_start`/`message_end` BEFORE it
 * appends to the transcript (`agent-session.js:748-763`), so no event or microtask
 * proves persistence - only a later read does. Poll at `TASK_CONFIRM_RETRY_MS`
 * for at most `TASK_CONFIRM_MAX_ATTEMPTS` times; on exhaustion the handoff is
 * released (so later tasks are never stalled) and the occurrence stays armed, so
 * a later pump RE-ATTEMPTS it with the SAME id (at-least-once).
 */
export const TASK_CONFIRM_RETRY_MS = 200;
export const TASK_CONFIRM_MAX_ATTEMPTS = 25;

/**
 * A fresh OPAQUE occurrence id.
 *
 * Minted when an occurrence is ARMED and re-minted only when an interval cursor
 * advances or a task is created/replaced. It is random so it cannot collide
 * across a restart or a second process, and it is never derived from the clock
 * or the task id.
 */
export function mintOccurrenceId(): string {
  return mintLineageToken().replace(/^ln-/, "oc-");
}

/**
 * A fresh TRANSIENT registration token, never persisted.
 *
 * Minted per registration and captured by every armed callback; re-checking it
 * against the live token immediately before injection excludes a callback armed
 * under a superseded registration. It is not a durable identity: a restart
 * legitimately re-loads the same session's tasks.
 */
export function mintRegistrationToken(): string {
  return mintLineageToken().replace(/^ln-/, "rg-");
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
 * The async subagent lifecycle topics observed for the run ledger.
 *
 * One START topic and one TERMINAL topic. `subagent:async-started` carries the
 * authoritative `runId`/`id`, `asyncDir`, `agent`, and session identity;
 * `subagent:child-status` is an ADDITIONAL terminal observation used when it is
 * the only thing a host emits. `subagent:async-complete` is deliberately NOT
 * consulted: it has no single documented interface, so depending on its fields
 * would be guessing.
 *
 * R6-1: BOTH topics are COLON-separated and MUST match pi-subagents' exported
 * constants verbatim (`pi-subagents/src/shared/types.js:11,18`). The dotted
 * `subagent.child-status` spelling is the event PAYLOAD `type`, not the bus
 * channel; subscribing to it silently observed nothing in production. A test
 * asserts these equal the runtime's own constants so the class cannot recur.
 */
export const OBSERVED_RUN_START_TOPIC = "subagent:async-started";
export const OBSERVED_RUN_TERMINAL_TOPIC = "subagent:child-status";

/**
 * Tokens accepted as the terminal transition of a start form, so a model that
 * binds a completion event (rather than a status) is still self-describing.
 */
const START_FORM_EVENTS = new Set(["started", "start", "launched", "running", "queued"]);

/** Cap on a bounded completion artifact, so one huge log cannot wedge a settle. */
const MAX_RESULT_ARTIFACT_BYTES = 2 * 1024 * 1024;

/**
 * The last fenced ```json block in a completion artifact.
 *
 * The final structured result is the LAST such block; the file may contain
 * several (or non-JSON prose), so every match is scanned and the last is used.
 */
const FENCED_JSON_BLOCK = /```json[ \t]*\r?\n([\s\S]*?)```/gi;

/**
 * True only for a real terminal UI session.
 *
 * `mode` is the honest test, not `hasUI`: Pi also sets `hasUI` on the RPC
 * surface, where an OSC notification and a zellij pane flag are meaningless. An
 * unknown or absent context is not a TUI, so it stays silent.
 */
function isTui(ctx: SupervisorContext | undefined): boolean {
  return ctx?.mode === "tui";
}

/**
 * A status the model declared on the final line of its final message.
 *
 * `ambiguous` is distinct from a missing marker only for diagnostics; both
 * resolve to `unknown` and both notify.
 */
export interface DeclaredMarker {
  status: DeclaredStatus;
  /** Trimmed payload: the next step, pending event, dependency, or reason. */
  payload: string;
  /** Present only when the line parsed but the protocol was violated. */
  problem?:
    | "empty-payload"
    | "unexpected-payload"
    | "unknown-status"
    | "ambiguous"
    | "ineligible-line";
}

/**
 * Read the status line a message declares, or null when it declares nothing.
 *
 * THE CONTRACT (deliberately narrow):
 *
 *   A status line declares only when it is the FINAL NON-BLANK LINE of the
 *   message, starts at COLUMN ZERO, is not code (indented or fence-decorated,
 *   or inside a fence), and is TOP LEVEL - i.e. preceded by a BLANK LINE, opens
 *   the message, or is a line an enclosing container does NOT continue lazily
 *   because that container's leaf is FENCED CODE rather than a paragraph.
 *
 * Everything else resolves to `unknown` (or null when no protocol line exists at
 * all), and the plugin answers "unknown" by NOTIFYING - never by continuing.
 *
 * WHY A BLANK-LINE RULE AS THE PRIMARY DECISION: deciding whether a bare
 * line is top-level Markdown requires parsing arbitrary CommonMark containers
 * (quotes, list items, lazy continuations, and their nesting). The blank-line
 * rule is EXACT whenever a blank line is present, and the ONE remaining
 * ambiguous shape - a column-zero line directly beneath a container - is decided
 * by container LIFETIME: a line continues a container lazily only while that
 * container's leaf is a PARAGRAPH, never beneath fenced code, which is where an
 * unmarked line ENDS the container and is passed through as ordinary top-level
 * text. Both halves were verified against a reference CommonMark parser:
 *
 *   - after a blank line, a column-zero line is ALWAYS a top-level paragraph;
 *   - without one, it is content of the container above it UNLESS that
 *     container's leaf is fenced code, in which case the line ENDS the
 *     container and is itself top-level.
 *
 * The residual cost is that a status line written inline directly beneath
 * PROSE does not declare. That loss is SAFE: the consequence is a notification
 * the user acts on, not an unwarranted automatic continuation.
 */
const MARKER_PROBLEM_NOTICE: Record<NonNullable<DeclaredMarker["problem"]>, string> = {
  "empty-payload": "Marker ignored - put the payload on the SAME line as the status word",
  "unexpected-payload": "Marker ignored - STATUS:DONE must have no payload",
  "unknown-status": "Marker ignored - use CONTINUE, WAIT, DONE, BLOCKED, or FAILED",
  "ambiguous": "Marker ignored - conflicting STATUS declarations; emit one marker",
  "ineligible-line": "Marker ignored - use a final column-zero STATUS line after a blank line, outside quotes/code",
};

/**
 * Diagnose rejected near-miss marker text without changing what the message
 * declares.
 *
 * WHY THIS EXISTS, AND WHY IT IS DIAGNOSTIC-ONLY: a status line one space off
 * column zero, or one whose payload wraps onto the next line, parses to `null`
 * exactly like a message that declares nothing. The extension still notifies in
 * both cases, but the notice read "session needs attention" and named no cause,
 * so a formatting near-miss was indistinguishable from an agent that simply
 * stopped. This recovers the cause for the NOTICE TEXT ONLY.
 *
 * Its result must never feed declaration, continuation, repair, or WAIT logic.
 * Acceptance is deliberately unchanged: a near-miss still stops. Making the
 * parser tolerant here was considered and rejected - normalizing leading
 * whitespace lets a list item's content (`- Example:` then an indented status)
 * declare, and looking back for a wrapped status promotes an example followed
 * by prose into a declaration. Neither is distinguishable locally, and both
 * would grant an unwarranted continuation.
 *
 * The window is the final two physical lines: the malformed status and the one
 * wrapped tail line that follows it. A longer wrapped tail keeps the generic
 * notice - a formatting hint is never worth widening the match set.
 *
 * A column-zero PAYLOAD-BEARING status whose payload wrapped onto the next line
 * is reported as `empty-payload`, not as a placement problem. The line did not
 * miss column zero; it is missing its payload, and naming the wrong cause sends
 * the reader to fix formatting that was already correct.
 *
 * A payload-FREE status (e.g. `DONE`) at column zero must NOT be reported as
 * `empty-payload`: DONE takes no payload, so telling the reader to put one on the
 * same line would be invalid advice. The membership test is derived from the
 * parser's OWN `PAYLOAD_REQUIRED_STATUSES` set - the single source of truth for
 * which statuses require a payload - so a future grammar change cannot leave this
 * diagnostic diverging from what the parser enforces.
 */
function markerProblemFor(
  message: unknown,
  marker: DeclaredMarker | null,
): DeclaredMarker["problem"] {
  if (marker !== null) return marker.problem;
  if (!isAssistantMessage(message)) return undefined;

  const text = messageText(message);
  const last = finalNonBlankLine(text);
  if (last === null) return undefined;
  const lines = text.split("\n");
  const structure = lineStructure(text);

  for (let index = Math.max(0, last.index - 1); index <= last.index; index += 1) {
    const line = lines[index].replace(/\s+$/, "");
    const candidate = line.trimStart();
    // `protocolLine` itself rejects leading whitespace, so a near-miss is
    // detected by asking a trimmed copy. Every exclusion below is the SAME
    // predicate the real parser uses, so this cannot recognize text the parser
    // would refuse to accept as anything but a formatting hint.
    if (
      protocolLine(candidate) === null ||
      isIndentedCodeLine(line) ||
      isFenceDecorated(line) ||
      structure.inside[index] ||
      isDocumentationLine(candidate)
    ) continue;
    // A marker that STARTS at column zero and whose payload wrapped onto the
    // next line is NOT a placement problem, and saying so would be a lie: the
    // line that failed is exactly where it should be. It is an EMPTY-payload
    // problem, so report that instead. Only a line that genuinely missed column
    // zero (or another eligibility rule) keeps the placement notice.
    const atColumnZero = candidate === line;
    const declared = protocolLine(candidate);
    if (
      atColumnZero &&
      declared !== null &&
      declared.payload.length === 0 &&
      PAYLOAD_REQUIRED_STATUSES.has(declared.name.toLowerCase())
    ) {
      return "empty-payload";
    }
    return "ineligible-line";
  }
  return undefined;
}

export function readDeclaredMarker(message: unknown): DeclaredMarker | null {
  if (!isAssistantMessage(message)) return null;
  const text = messageText(message);
  const lastLine = finalNonBlankLine(text);
  if (lastLine === null) return null;

  const structure = lineStructure(text);
  const lines = text.split("\n");

  // A message declaring two DIFFERENT statuses has not declared one.
  const candidates = countProtocolLines(text, structure);
  if (candidates.ambiguous) {
    return { status: "unknown", payload: "", problem: "ambiguous" };
  }

  const declared = protocolLine(lastLine.text);
  if (declared === null) return null;

  // The SAME predicate the counting path used, so the two cannot disagree.
  // An ineligible final line is reported as `unknown` rather than null so the
  // plugin notifies instead of doing nothing.
  if (!lineDeclares(lines, lastLine.index, structure)) {
    return { status: "unknown", payload: "", problem: "ineligible-line" };
  }

  const { name, payload } = declared;
  const lowered = name.toLowerCase();

  if (PAYLOAD_FREE_STATUSES.has(lowered)) {
    // A payload after DONE is a malformed line, not a declaration.
    return payload.length > 0
      ? { status: "unknown", payload, problem: "unexpected-payload" }
      : { status: lowered as DeclaredStatus, payload: "" };
  }
  if (PAYLOAD_REQUIRED_STATUSES.has(lowered)) {
    // An empty payload leaves the extension unable to tell what happens next.
    return payload.length === 0
      ? { status: "unknown", payload: "", problem: "empty-payload" }
      : { status: lowered as DeclaredStatus, payload };
  }
  return { status: "unknown", payload, problem: "unknown-status" };
}

/** Null unless the message's role is exactly `assistant`. */
function isAssistantMessage(message: unknown): boolean {
  if (message === null || typeof message !== "object") return false;
  return (message as { role?: unknown }).role === "assistant";
}

/**
 * True when a pending-array entry is POSITIVELY genuine queued user work.
 *
 * Only an entry that is clearly a user turn qualifies. Everything else -
 * including every `role:"custom"` shape, which Pi routes to BOTH the queues
 * and the context-only list - is treated as NOT providing queue ownership, so
 * the caller supplies the bridge rather than risking a stopped run.
 */
function isGenuineQueuedWork(entry: unknown): boolean {
  if (entry === null || typeof entry !== "object") return false;
  const candidate = entry as { type?: unknown; customType?: unknown; role?: unknown };
  // A custom-message shape is never unambiguous queue ownership.
  if (candidate.type === "custom" || candidate.type === "custom_message") return false;
  if (candidate.role === "custom") return false;
  if (typeof candidate.customType === "string") return false;
  // A user turn is the one shape Pi's `hasQueuedMessages()` certainly reports.
  return candidate.role === "user";
}

/**
 * True when a pending-array entry is a CONTEXT-ONLY custom message.
 *
 * BACKGROUND (verified against Pi 1.1.0 source). `getPendingMessages()` returns
 * `[...agent.peekQueuedMessages(), ...this._pendingCustomMessages]`. Both kinds
 * of entry can be `role: "custom"` with a `customType`, because
 * `sendCustomMessage()` builds ONE shape and then routes it by DESTINATION:
 *   - `deliverAs: "followUp"` -> `agent.followUp(msg)`  (steering/followUp queue)
 *   - otherwise, streaming   -> `agent.steer(msg)`      (steering queue)
 *   - `triggerTurn: false`   -> `_pendingCustomMessages` (context-only)
 * The two queued destinations are what `agent.hasQueuedMessages()` reports, and
 * they are exactly what Pi uses to continue on its own
 * (`shouldContinue = result.continue || agent.hasQueuedMessages()`).
 *
 * CONSEQUENCE: the pending ARRAY cannot distinguish the two cases by message
 * shape - the same shape reaches both destinations. A shape-based classifier is
 * therefore unsound in BOTH directions. The maintainers' decision (see
 * `hasQueuedOwnership`) is to treat every ambiguous custom shape as NOT queued
 * ownership, because the asymmetric failure mode of guessing "queued" is a
 * STOPPED run, while guessing "context-only" can at worst add a redundant
 * bridge that step (4) of `proposeContinuation` suppresses.
 *
 * This helper exists so tests and callers can still ask the narrow
 * context-only question. It is the exact complement of `isGenuineQueuedWork`
 * for every recognized custom shape.
 */
function isContextOnlyPendingMessage(entry: unknown): boolean {
  if (entry === null || typeof entry !== "object") return false;
  const candidate = entry as { type?: unknown; customType?: unknown; role?: unknown };
  // Any recognized custom shape is context-only for our purposes. This is
  // checked BEFORE the empty-string case, so a context-only native custom
  // message with `customType: ""` (which Pi does not reject) is recognized
  // instead of being mistaken for queued ownership.
  if (candidate.type === "custom" || candidate.type === "custom_message") return true;
  if (candidate.role === "custom") return true;
  if (typeof candidate.customType === "string") return true;
  // A bare `{}` or any other unrecognized shape is NOT asserted to be
  // context-only here; ownership is decided positively by `isGenuineQueuedWork`.
  return false;
}

/**
 * True when a content part is a tool call in either the canonical Pi shape
 * (`toolCall`) or the legacy/alias spelling (`tool_call`).
 *
 * WHY BOTH SPELLINGS: the installed Pi 1.1.0 host persists tool calls as
 * `{type:"toolCall", id, name, arguments}` (canonical; observed in a real
 * host-written assistant message), while an earlier revision of this extension
 * only recognized `"tool_call"`. That narrow spelling let a native assistant
 * message carrying BOTH text and a tool call be treated as a status
 * declaration, so a text ending in `STATUS:CONTINUE …` wrongly declared a
 * continuation. Excluding BOTH spellings keeps the tolerant alias without
 * losing the canonical shape.
 */
export function isToolCallPart(part: unknown): boolean {
  if (part === null || typeof part !== "object") return false;
  const type = (part as { type?: unknown }).type;
  return type === "toolCall" || type === "tool_call";
}

/**
 * Concatenate the text parts of one message, ignoring thinking and tool calls.
 *
 * A message that ALSO carries tool calls is metadata, not a declaration, and
 * reports no text.
 */
function messageText(message: unknown): string {
  if (message === null || typeof message !== "object") return "";
  const content = (message as { content?: unknown }).content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  if (content.some((part) => isToolCallPart(part))) return "";
  const parts: string[] = [];
  for (const part of content) {
    if (part === null || typeof part !== "object") continue;
    const candidate = part as { type?: unknown; text?: unknown };
    if (candidate.type === "text" && typeof candidate.text === "string") {
      parts.push(candidate.text);
    }
  }
  return parts.join("\n").replace(/\r\n?/g, "\n");
}

/** The final non-blank line of `text`, with its index and trailing space removed. */
function finalNonBlankLine(text: string): { text: string; index: number } | null {
  const lines = text.split("\n");
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index].replace(/\s+$/, "");
    if (line.trim().length > 0) return { text: line, index };
  }
  return null;
}

/**
 * BLOCK-STRUCTURE ENGINE — a dependency-free transcription of CommonMark
 * 0.31.2's block parser.
 *
 * WHY THIS EXISTS. The structure behind `lineStructure` was hand-written as a
 * container/leaf state machine. Six consecutive reviews each found a real defect
 * in the SAME continuation rule (A23, A24, A28, A29, A30, A31/A32, A33), because
 * the file held TWO competing continuation implementations — one that retained
 * the whole active stack on a container-relative blank, and a second path for
 * fences/HTML whose list-width test lacked the reference item's
 * blank-before-indent branch. Patching the sixth did not close the family. This
 * module replaces the model wholesale: it transcribes the reference algorithm so
 * there is exactly ONE continuation operation per block, evaluated at each
 * block's CURRENT offset with blankness recomputed from the parse state.
 *
 * PROVENANCE. Transcribed from commonmark.js 0.31.2 `lib/blocks.js` and the
 * block-relevant helpers of `lib/inlines.js` (reference-label parsing used only
 * to decide whether a paragraph's leading text is a link reference definition —
 * a fact that changes whether the paragraph exists and which lines it owns).
 * Only the block-level algorithm is transcribed: inline parsing, rendering, and
 * the destination/title VALUES of reference definitions are omitted, because
 * none of them change block ownership. No `commonmark` module is imported at
 * runtime.
 *
 * REV66-P3 - BSD-2-Clause requires the copyright notice, conditions and
 * disclaimer to be retained with source redistribution. The repository has no
 * separate LICENSE file, so the notice is reproduced here in full:
 *
 *   commonmark.js
 *   Copyright (c) 2014, John MacFarlane
 *   All rights reserved.
 *
 *   Redistribution and use in source and binary forms, with or without
 *   modification, are permitted provided that the following conditions are met:
 *
 *       * Redistributions of source code must retain the above copyright
 *         notice, this list of conditions and the following disclaimer.
 *
 *       * Redistributions in binary form must reproduce the above
 *         copyright notice, this list of conditions and the following
 *         disclaimer in the documentation and/or other materials provided
 *         with the distribution.
 *
 *   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *   "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *   LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 *   A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 *   OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 *   SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 *   LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 *   DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 *   THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 *   (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 *   OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 * THE REFERENCE'S MODEL, IN ONE PARAGRAPH. A line is incorporated by walking the
 * open-block chain from the document downward. Each open block's `continue`
 * returns MATCHED (0), UNMATCHED (1), or LINE-CONSUMED (2). The walk stops at
 * the FIRST failure: `container` backs up to the last matching block and every
 * unmatched descendant is closed (`closeUnmatchedBlocks`). The surviving level
 * is then offered the line as a sequence of block STARTS (block quote, ATX
 * heading, fence, HTML, setext, thematic break, list item, indented code) in the
 * reference's order; a container start keeps the loop going, a leaf start ends
 * it. What remains at the parser offset is text: a lazy paragraph continuation
 * when an as-yet-unclosed paragraph still tips the stack, otherwise a new
 * paragraph (or content appended to the accepting leaf). Blankness is recomputed
 * by `findNextNonspace` from the CURRENT offset on every block, never once per
 * line. This single loop is the whole continuation semantics.
 *
 * WHAT WE READ OFF THE PARSE. `lineStructure` consumes the finalized block tree
 * and reports, per input line: the fence membership (`changes` / `inside`) and
 * the two ownership facts consumers need (`topLevel`, `paragraphStart`). It never
 * re-derives containers from strings, so the marker, counting, and question
 * surfaces cannot drift apart again.
 */
type BlockType =
  | "document"
  | "block_quote"
  | "list"
  | "item"
  | "paragraph"
  | "heading"
  | "thematic_break"
  | "code_block"
  | "html_block";

/** One node of the parsed block tree. Mirrors the reference `Node` subset. */
interface BlockNode {
  type: BlockType;
  parent: BlockNode | null;
  firstChild: BlockNode | null;
  lastChild: BlockNode | null;
  prev: BlockNode | null;
  next: BlockNode | null;
  /** [startLine, startCol] .. [endLine, endCol], 1-based like the reference. */
  sourcepos: [[number, number], [number, number]];
  open: boolean;
  stringContent: string | null;
  /** Fenced code block bookkeeping (the reference's `_isFenced` family). */
  isFenced: boolean;
  fenceChar: string;
  fenceLength: number;
  fenceOffset: number;
  /** HTML block type 1-7. */
  htmlBlockType: number;
  /** List data (`_listData` in the reference): type, start, delimiter, padding. */
  listData: {
    type: string | null;
    tight: boolean;
    bulletChar: string | null;
    start: number | null;
    delimiter: string | null;
    padding: number | null;
    markerOffset: number;
  };
}

/** Allocate a fresh block node, exactly as the reference `Node` does. */
function makeBlock(type: BlockType, sourcepos: [[number, number], [number, number]]): BlockNode {
  return {
    type,
    parent: null,
    firstChild: null,
    lastChild: null,
    prev: null,
    next: null,
    sourcepos,
    open: true,
    stringContent: null,
    isFenced: false,
    fenceChar: "",
    fenceLength: 0,
    fenceOffset: 0,
    htmlBlockType: 0,
    listData: {
      type: null,
      tight: true,
      bulletChar: null,
      start: null,
      delimiter: null,
      padding: null,
      markerOffset: 0,
    },
  };
}

/** Detach a node from its parent and siblings (reference `unlink`). */
function unlinkBlock(node: BlockNode): void {
  if (node.prev !== null) {
    node.prev.next = node.next;
  } else if (node.parent !== null) {
    node.parent.firstChild = node.next;
  }
  if (node.next !== null) {
    node.next.prev = node.prev;
  } else if (node.parent !== null) {
    node.parent.lastChild = node.prev;
  }
  node.parent = null;
  node.next = null;
  node.prev = null;
}

/** Append a child to a parent (reference `appendChild`). */
function appendChild(parent: BlockNode, child: BlockNode): void {
  unlinkBlock(child);
  child.parent = parent;
  if (parent.lastChild !== null) {
    parent.lastChild.next = child;
    child.prev = parent.lastChild;
    parent.lastChild = child;
  } else {
    parent.firstChild = child;
    parent.lastChild = child;
  }
}

/** Insert `sibling` directly after `node` (reference `insertAfter`). */
function insertAfter(node: BlockNode, sibling: BlockNode): void {
  unlinkBlock(sibling);
  sibling.next = node.next;
  if (sibling.next !== null) sibling.next.prev = sibling;
  sibling.prev = node;
  node.next = sibling;
  sibling.parent = node.parent;
  if (sibling.next === null && sibling.parent !== null) {
    sibling.parent.lastChild = sibling;
  }
}

/** The CommonMark "accepts lines" predicate (canContain is false for leaves). */
function acceptsLines(type: BlockType): boolean {
  return type === "code_block" || type === "html_block" || type === "paragraph";
}

/** CommonMark `canContain`: whether a block of `type` may contain `child`. */
function canContain(type: BlockType, child: BlockType): boolean {
  switch (type) {
    case "document":
    case "block_quote":
    case "item":
      return child !== "item";
    case "list":
      return child === "item";
    default:
      return false;
  }
}

const CODE_INDENT = 4;

// --- the reference's block-level regular expressions -----------------------
// The HTML tag grammar (common.js OPENTAG/CLOSETAG). Built with `new RegExp`
// rather than a literal because the type-7 alternation below is long enough that
// the type-stripping loader misreads the literal as a division/JSX token.
const HTML_TAGNAME = "[A-Za-z][A-Za-z0-9-]*";
const HTML_ATTRIBUTENAME = "[a-zA-Z_:][a-zA-Z0-9:._-]*";
const HTML_UNQUOTEDVALUE = "[^\"'=<>`\\x00-\\x20]+";
const HTML_ATTRIBUTEVALUE =
  "(?:" + HTML_UNQUOTEDVALUE + "|'[^']*'|\"[^\"]*\")";
const HTML_ATTRIBUTEVALUESPEC = "(?:\\s*=\\s*" + HTML_ATTRIBUTEVALUE + ")";
const HTML_ATTRIBUTE = "(?:\\s+" + HTML_ATTRIBUTENAME + HTML_ATTRIBUTEVALUESPEC + "?)";
const HTML_OPENTAG = "<" + HTML_TAGNAME + HTML_ATTRIBUTE + "*\\s*/?>";
const HTML_CLOSETAG = "</" + HTML_TAGNAME + "\\s*[>]";

const reHtmlBlockOpen: (RegExp | null)[] = [
  null,
  /^<(?:script|pre|textarea|style)(?:\s|>|$)/i,
  /^<!--/,
  /^<[?]/,
  /^<![A-Za-z]/,
  /^<!\[CDATA\[/,
  /^<[/]?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[123456]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|section|search|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:\s|[/]?[>]|$)/i,
  // type 7 is checked separately below (it needs the paragraph "maybe lazy"
  // guard the reference applies at the call site).
  new RegExp("^(?:" + HTML_OPENTAG + "|" + HTML_CLOSETAG + ")\\s*$", "i"),
];

const reHtmlBlockClose: (RegExp | null)[] = [
  null,
  /<\/(?:script|pre|textarea|style)>/i,
  /-->/,
  /\?>/,
  />/,
  /\]\]>/,
];

const reThematicBreak = /^(?:\*[ \t]*){3,}$|^(?:_[ \t]*){3,}$|^(?:-[ \t]*){3,}$/;
const reMaybeSpecial = /^[#`~*+_=<>0-9-]/;
const reNonSpace = /[^ \t\f\v\r\n]/;
const reBulletListMarker = /^[*+-]/;
const reOrderedListMarker = /^(\d{1,9})([.)])/;
const reATXHeadingMarker = /^#{1,6}(?:[ \t]+|$)/;
const reCodeFence = /^`{3,}(?!.*`)|^~{3,}/;
const reClosingCodeFence = /^(?:`{3,}|~{3,})(?=[ \t]*$)/;
const reSetextHeadingLine = /^(?:=+|-+)[ \t]*$/;
const reLineEnding = /\r\n|\n|\r/;

/**
 * True when a string contains only Markdown blank characters.
 *
 * Markdown blankness is NOT JavaScript `String.prototype.trim()`: `trim()`
 * strips the whole Unicode whitespace class, including U+00A0 NO-BREAK SPACE and
 * other non-ASCII spaces that Markdown treats as ORDINARY PARAGRAPH CONTENT. A
 * line holding only an NBSP is therefore NOT blank - it continues the open
 * paragraph - but a `trim()`-based test read it as blank, ended the paragraph,
 * and promoted the declaration beneath it to document level (DEFECT F8, the
 * harmful false positive). `isBlank` is the reference's own predicate for this
 * question and the single blankness rule the whole walk uses.
 */
function isBlank(s: string): boolean {
  return !reNonSpace.test(s);
}

/** True for space/tab (the reference `isSpaceOrTab`). */
function isSpaceOrTab(c: number): boolean {
  return c === 32 || c === 9;
}

/** Character code at `pos`, or -1 past the end (reference `peek`). */
function peekChar(ln: string, pos: number): number {
  return pos < ln.length ? ln.charCodeAt(pos) : -1;
}

// --- reference-definition recognition (block ownership only) ----------------
//
// A paragraph's leading text may be one or more link reference definitions
// (CommonMark 4.7). If every line of the paragraph is consumed that way, the
// paragraph does not exist; the lines it absorbed are NOT a document paragraph,
// which changes the ownership answer for anything beneath them. We therefore
// transcribe `parseReference`'s CONSUMPTION logic. The destination/title values
// are discarded: they never affect which block owns a line.

const reLinkLabel = /^\[(?:[^\\[\]]|\\.){0,1000}\]/s;
const reLinkDestinationBraces = /^(?:<(?:[^<>\n\\\x00]|\\.)*>)/;
const ESCAPABLE = "[!\"#$%&'()*+,./:;<=>?@[\\\\\\]^_`{|}~-]";
// REV66-P2: the reference builds the title body from ESCAPED_CHAR (a BACKSLASH
// followed by an escapable character) - NOT from bare ESCAPABLE. Substituting
// ESCAPABLE let a raw delimiter character occur inside its own title, so
// `[a]: /x "t" junk "u"` was greedily read as ONE title `"t" junk "u"` and the
// definition was consumed, when the reference rejects it (the valid short title
// `"t"` is followed by non-whitespace) and keeps the paragraph alive.
const ESCAPED_CHAR = "\\\\" + ESCAPABLE;
const reEscapable = new RegExp("^" + ESCAPABLE);
// Verbatim transcription of the reference's reLinkTitle body. Each of the three
// delimiter forms is built as:
//
//     ESCAPED_CHAR | '\\[^\\]' | '[^\\<delim>\\x00]'
//
// The second alternative is written in the reference as the SINGLE-quoted JS
// literal '\\[^\\]', which decodes to the four-character regex source \[^\] -
// i.e. a LITERAL BACKSLASH followed by any NON-BACKSLASH. Both halves of that
// decoding matter, and a previous revision got both wrong (REV67-P1): as a
// double-quoted "\\\\[^\\\\]" it decoded to \\[^\\] (two backslashes = an
// escaped-backslash regex, matching one backslash, then a class that still
// admitted a backslash), and the ordinary classes below were written with two
// backslashes where the reference has four. The result excluded the delimiter
// but NOT a literal backslash, so the regex could backtrack - consuming a
// backslash via the permissive ordinary alternative and then closing the title
// on an ESCAPED delimiter. Input `[a]: /x "t\"` therefore wrongly consumed the
// definition (emptied-setext path -> paragraph continues -> `unknown`) where the
// reference keeps it as heading text and yields `continue`.
//
// Built from concatenation so the JS escaping is auditable against the
// reference source rather than hidden in one literal.
const ESC_BACKSLASH = "\\\\"; // regex source: a single literal backslash
const ESC_NONBACKSLASH = "[^\\\\]"; // regex source: any NON-backslash char
const ANY_ESCAPE = ESC_BACKSLASH + ESC_NONBACKSLASH; // regex source: \[^\]
const classExcluding = (chars: string) => "[^" + ESC_BACKSLASH + chars + "\\x00]";
const reLinkTitle = new RegExp(
  '^(?:"(' +
    ESCAPED_CHAR +
    "|" +
    ANY_ESCAPE +
    "|" +
    classExcluding('"') +
    ')*"' +
    "|" +
    "'(" +
    ESCAPED_CHAR +
    "|" +
    ANY_ESCAPE +
    "|" +
    classExcluding("'") +
    ")*'" +
    "|" +
    "\\(" +
    "(" +
    ESCAPED_CHAR +
    "|" +
    ANY_ESCAPE +
    "|" +
    classExcluding("()") +
    ")*\\)" +
    ")",
);
const reSpnl = /^ *(?:\n *)?/;
const reSpaceAtEndOfLine = /^ *(?:\n|$)/;
const reWhitespaceChar = /^[ \t\n\x0b\x0c\x0d]/;

/** Convert a code point to its string, dependency-free. */
function fromCodePoint(code: number): string {
  return String.fromCodePoint(code);
}

/** The subject/position scanner `parseReference` needs. */
interface RefScanner {
  subject: string;
  pos: number;
}

function refMatch(sc: RefScanner, re: RegExp): string | null {
  const m = re.exec(sc.subject.slice(sc.pos));
  if (m === null) return null;
  sc.pos += m.index + m[0].length;
  return m[0];
}

function refPeek(sc: RefScanner): number {
  return sc.pos < sc.subject.length ? sc.subject.charCodeAt(sc.pos) : -1;
}

function refParseLinkLabel(sc: RefScanner): number {
  const m = refMatch(sc, reLinkLabel);
  if (m === null || m.length > 1001) return 0;
  return m.length;
}

function refParseLinkDestination(sc: RefScanner): string | null {
  let res = refMatch(sc, reLinkDestinationBraces);
  if (res === null) {
    if (refPeek(sc) === 60 /* < */) return null;
    const savepos = sc.pos;
    let openparens = 0;
    let c = refPeek(sc);
    while (c !== -1) {
      if (c === 92 /* \ */ && reEscapable.test(sc.subject.charAt(sc.pos + 1))) {
        sc.pos += 1;
        if (refPeek(sc) !== -1) sc.pos += 1;
      } else if (c === 40 /* ( */) {
        sc.pos += 1;
        openparens += 1;
      } else if (c === 41 /* ) */) {
        if (openparens < 1) break;
        sc.pos += 1;
        openparens -= 1;
      } else if (reWhitespaceChar.exec(fromCodePoint(c)) !== null) {
        break;
      } else {
        sc.pos += 1;
      }
      c = refPeek(sc);
    }
    if (sc.pos === savepos && c !== 41) return null;
    if (openparens !== 0) return null;
    res = sc.subject.slice(savepos, sc.pos);
    return res;
  }
  return res;
}

function refParseLinkTitle(sc: RefScanner): string | null {
  const title = refMatch(sc, reLinkTitle);
  return title === null ? null : title.slice(1, -1);
}

function normalizeReference(str: string): string {
  return str.slice(1, str.length - 1).trim().replace(/[ \t\r\n]+/g, " ").toLowerCase().toUpperCase();
}

/**
 * Consume one leading link reference definition from `s`, returning the number
 * of characters consumed (0 when `s` does not begin with one).
 */
function parseReferenceDefinition(s: string): number {
  const sc: RefScanner = { subject: s, pos: 0 };
  const startpos = sc.pos;
  const matchChars = refParseLinkLabel(sc);
  if (matchChars === 0) return 0;
  const rawlabel = sc.subject.slice(0, matchChars);
  if (refPeek(sc) === 58 /* : */) {
    sc.pos += 1;
  } else {
    return 0;
  }
  refMatch(sc, reSpnl);
  if (refParseLinkDestination(sc) === null) return 0;
  const beforetitle = sc.pos;
  refMatch(sc, reSpnl);
  let title: string | null = null;
  if (sc.pos !== beforetitle) title = refParseLinkTitle(sc);
  if (title === null) sc.pos = beforetitle;
  let atLineEnd = true;
  if (refMatch(sc, reSpaceAtEndOfLine) === null) {
    if (title === null) {
      atLineEnd = false;
    } else {
      title = null;
      sc.pos = beforetitle;
      atLineEnd = refMatch(sc, reSpaceAtEndOfLine) !== null;
    }
  }
  if (!atLineEnd) return 0;
  if (normalizeReference(rawlabel) === "") return 0;
  return sc.pos - startpos;
}

/**
 * Strip leading link reference definitions from `content`, returning the
 * remainder, exactly as the reference does at paragraph finalize / setext time.
 */
function stripReferenceDefinitions(content: string): string {
  let rest = content;
  while (rest.length > 0 && rest.charCodeAt(0) === 91 /* [ */) {
    const consumed = parseReferenceDefinition(rest);
    if (consumed === 0) break;
    rest = rest.slice(consumed);
  }
  return rest;
}

// --- parser state ----------------------------------------------------------
interface BlockParser {
  doc: BlockNode;
  tip: BlockNode;
  oldtip: BlockNode;
  currentLine: string;
  lineNumber: number;
  offset: number;
  column: number;
  nextNonspace: number;
  nextNonspaceColumn: number;
  indent: number;
  indented: boolean;
  blank: boolean;
  partiallyConsumedTab: boolean;
  allClosed: boolean;
  lastMatchedContainer: BlockNode;
  refmap: Record<string, { destination: string; title: string }>;
  lastLineLength: number;
  /** Trace recorded while incorporating lines (0-based line index keys). */
  trace: {
    /** True when this line created a fresh paragraph (its first content line). */
    paragraphStarted: boolean[];
    /** One entry per FENCED code block, in opener order. */
    fences: { open: number; end: number; closerLine: number | null }[];
    /** Set while a fenced closer is being finalized, so the fence records its closer. */
    closingFence: boolean;
  };
}

function makeParser(): BlockParser {
  const doc = makeBlock("document", [
    [1, 1],
    [0, 0],
  ]);
  return {
    doc,
    tip: doc,
    oldtip: doc,
    currentLine: "",
    lineNumber: 0,
    offset: 0,
    column: 0,
    nextNonspace: 0,
    nextNonspaceColumn: 0,
    indent: 0,
    indented: false,
    blank: false,
    partiallyConsumedTab: false,
    allClosed: true,
    lastMatchedContainer: doc,
    refmap: {},
    lastLineLength: 0,
    trace: { paragraphStarted: [], fences: [], closingFence: false },
  };
}

/** Reference `advanceOffset`, including the partially-consumed-tab rule. */
function advanceOffset(p: BlockParser, count: number, columns: boolean): void {
  const currentLine = p.currentLine;
  let charsToTab: number;
  let charsToAdvance: number;
  let c: string;
  while (count > 0 && (c = currentLine[p.offset])) {
    if (c === "\t") {
      charsToTab = 4 - (p.column % 4);
      if (columns) {
        p.partiallyConsumedTab = charsToTab > count;
        charsToAdvance = charsToTab > count ? count : charsToTab;
        p.column += charsToAdvance;
        p.offset += p.partiallyConsumedTab ? 0 : 1;
        count -= charsToAdvance;
      } else {
        p.partiallyConsumedTab = false;
        p.column += charsToTab;
        p.offset += 1;
        count -= 1;
      }
    } else {
      p.partiallyConsumedTab = false;
      p.offset += 1;
      p.column += 1;
      count -= 1;
    }
  }
}

function advanceNextNonspace(p: BlockParser): void {
  p.offset = p.nextNonspace;
  p.column = p.nextNonspaceColumn;
  p.partiallyConsumedTab = false;
}

/** Reference `findNextNonspace`: recomputes blankness at the current offset. */
function findNextNonspace(p: BlockParser): void {
  const currentLine = p.currentLine;
  let i = p.offset;
  let cols = p.column;
  let c: string;
  while ((c = currentLine.charAt(i)) !== "") {
    if (c === " ") {
      i++;
      cols++;
    } else if (c === "\t") {
      i++;
      cols += 4 - (cols % 4);
    } else {
      break;
    }
  }
  p.blank = c === "\n" || c === "\r" || c === "";
  p.nextNonspace = i;
  p.nextNonspaceColumn = cols;
  p.indent = p.nextNonspaceColumn - p.column;
  p.indented = p.indent >= CODE_INDENT;
}

/** Reference `addLine`: append the current line's tail to the tip's content. */
function addLine(p: BlockParser): void {
  if (p.tip.stringContent === null) p.tip.stringContent = "";
  if (p.partiallyConsumedTab) {
    p.offset += 1;
    const charsToTab = 4 - (p.column % 4);
    p.tip.stringContent += " ".repeat(charsToTab);
  }
  p.tip.stringContent += p.currentLine.slice(p.offset) + "\n";
}

/** Reference `addChild`: descend to a block that can contain `tag`, then add. */
function addChild(p: BlockParser, tag: BlockType, offset: number): BlockNode {
  while (!canContain(p.tip.type, tag)) {
    finalizeBlock(p, p.tip, p.lineNumber - 1);
  }
  const columnNumber = offset + 1;
  const newBlock = makeBlock(tag, [
    [p.lineNumber, columnNumber],
    [0, 0],
  ]);
  newBlock.stringContent = "";
  appendChild(p.tip, newBlock);
  p.tip = newBlock;
  return newBlock;
}

/** Reference `finalize`: close a block and run its type-specific finalizer. */
function finalizeBlock(p: BlockParser, block: BlockNode, lineNumber: number): void {
  const above = block.parent;
  block.open = false;
  block.sourcepos[1] = [lineNumber, p.lastLineLength];
  switch (block.type) {
    case "document":
      removeLinkReferenceDefinitions(p, block);
      break;
    case "list": {
      let item = block.firstChild;
      while (item !== null) {
        if (item.next !== null && endsWithBlankLine(item)) {
          block.listData.tight = false;
          break;
        }
        let subitem = item.firstChild;
        while (subitem !== null) {
          if (subitem.next !== null && endsWithBlankLine(subitem)) {
            block.listData.tight = false;
            break;
          }
          subitem = subitem.next;
        }
        item = item.next;
      }
      if (block.lastChild !== null) block.sourcepos[1] = block.lastChild.sourcepos[1];
      break;
    }
    case "item":
      if (block.lastChild !== null) {
        block.sourcepos[1] = block.lastChild.sourcepos[1];
      } else {
        block.sourcepos[1][0] = block.sourcepos[0][0];
        block.sourcepos[1][1] =
          block.listData.markerOffset + (block.listData.padding ?? 0);
      }
      break;
    case "code_block":
      if (block.isFenced) {
        // Record the fence's CONTENT range for `inside`. A fence closed by a
        // closer ends on the line BEFORE that closer; a fence ended by its
        // container (or EOF) ends on its last content line, which finalize has
        // already recorded as `sourcepos[1][0]`.
        const closerLine = p.trace.closingFence ? block.sourcepos[1][0] : null;
        p.trace.closingFence = false;
        p.trace.fences.push({
          open: block.sourcepos[0][0],
          end: closerLine === null ? block.sourcepos[1][0] : closerLine - 1,
          closerLine,
        });
        block.stringContent = null;
      } else {
        const lines = (block.stringContent ?? "").split("\n");
        while (/^[ \t]*$/.test(lines[lines.length - 1])) lines.pop();
        block.sourcepos[1][0] = block.sourcepos[0][0] + lines.length - 1;
        block.sourcepos[1][1] = block.sourcepos[0][1] + (lines[lines.length - 1] ?? "").length - 1;
        block.stringContent = null;
      }
      break;
    case "html_block":
      block.stringContent = null;
      break;
    default:
      break;
  }
  p.tip = above ?? p.doc; // document's parent is null; `lineStructure` stops there
}

/** Reference `endsWithBlankLine`: does `block` end on a line before its next? */
function endsWithBlankLine(block: BlockNode): boolean {
  return (
    block.next !== null &&
    block.sourcepos[1][0] !== block.next.sourcepos[0][0] - 1
  );
}

/** Reference `closeUnmatchedBlocks`: close every block past the last match. */
function closeUnmatchedBlocks(p: BlockParser): void {
  if (!p.allClosed) {
    while (p.oldtip !== p.lastMatchedContainer) {
      const parent = p.oldtip.parent;
      finalizeBlock(p, p.oldtip, p.lineNumber - 1);
      p.oldtip = parent ?? p.doc;
    }
    p.allClosed = true;
  }
}

/**
 * Reference `removeLinkReferenceDefinitions`: strip leading reference
 * definitions from every paragraph; unlink paragraphs left empty. A removed
 * paragraph no longer owns its lines, so ownership must read the tree AFTER
 * this runs.
 */
function removeLinkReferenceDefinitions(p: BlockParser, tree: BlockNode): void {
  const emptyNodes: BlockNode[] = [];
  walkBlocks(tree, (node, entering) => {
    if (!entering || node.type !== "paragraph") return;
    let content = node.stringContent ?? "";
    let hasReferenceDefs = false;
    while (content.length > 0 && content.charCodeAt(0) === 91 /* [ */) {
      const consumed = parseReferenceDefinition(content);
      if (consumed === 0) break;
      const removedText = content.slice(0, consumed);
      content = content.slice(consumed);
      hasReferenceDefs = true;
      node.sourcepos[0][0] += removedText.split("\n").length - 1;
    }
    node.stringContent = content;
    if (hasReferenceDefs && isBlank(content)) emptyNodes.push(node);
  });
  for (const node of emptyNodes) unlinkBlock(node);
}

/**
 * Pre-order block walk with an entering/exiting flag.
 *
 * ITERATIVE, with an explicit stack. The block tree's depth is bounded only by
 * the input's nesting, and a recursive walk consumed one JavaScript stack frame
 * per level: a deeply nested message (thousands of `> ` levels) overflowed the
 * finite call stack with `RangeError: Maximum call stack size exceeded` before
 * marker extraction returned. That threw out of `readDeclaredMarker`, out of
 * `handleBeforeSettle`, and out of the settlement path, so a genuine printed
 * CONTINUE stopped silently with no bridge and no notice. The traversal must
 * therefore never depend on the host's call-stack depth.
 *
 * Order is preserved EXACTLY as the former recursion emitted it: `visit(node,
 * true)` pre-order, then each child in `firstChild..next` order, then
 * `visit(node, false)`. A frame's exit is scheduled BEFORE its children are
 * pushed, and the children are pushed in REVERSE so they pop forward, keeping
 * the entering/exiting sequence identical for every consumer.
 */
function walkBlocks(
  root: BlockNode,
  visit: (node: BlockNode, entering: boolean) => void,
): void {
  // `entering` distinguishes the two passes over a frame. Children are gathered
  // into a reusable scratch array only to reverse them; no recursion, no
  // host-stack use regardless of nesting depth.
  const stack: Array<{ node: BlockNode; entering: boolean }> = [
    { node: root, entering: true },
  ];
  while (stack.length > 0) {
    const frame = stack.pop() as { node: BlockNode; entering: boolean };
    const node = frame.node;
    if (frame.entering) {
      visit(node, true);
      // Schedule this node's exit to run AFTER every descendant.
      stack.push({ node, entering: false });
      const children: BlockNode[] = [];
      for (let child = node.firstChild; child !== null; child = child.next) {
        children.push(child);
      }
      for (let i = children.length - 1; i >= 0; i -= 1) {
        stack.push({ node: children[i], entering: true });
      }
    } else {
      visit(node, false);
    }
  }
}

/** Reference `parseListMarker`: returns marker data, or null. */
function parseListMarker(p: BlockParser, container: BlockNode): BlockNode["listData"] | null {
  const rest = p.currentLine.slice(p.nextNonspace);
  let match: RegExpMatchArray | null;
  let nextc: number;
  let spacesStartCol: number;
  let spacesStartOffset: number;
  const data = {
    type: null as string | null,
    tight: true,
    bulletChar: null as string | null,
    start: null as number | null,
    delimiter: null as string | null,
    padding: null as number | null,
    markerOffset: p.indent,
  };
  if (p.indent >= 4) return null;
  if ((match = rest.match(reBulletListMarker))) {
    data.type = "bullet";
    data.bulletChar = match[0][0];
  } else if (
    (match = rest.match(reOrderedListMarker)) &&
    (container.type !== "paragraph" || parseInt(match[1] ?? "0", 10) === 1)
  ) {
    data.type = "ordered";
    data.start = parseInt(match[1] ?? "0", 10);
    data.delimiter = match[2] ?? "";
  } else {
    return null;
  }
  nextc = peekChar(p.currentLine, p.nextNonspace + match[0].length);
  if (!(nextc === -1 || nextc === 9 || nextc === 32)) return null;
  if (
    container.type === "paragraph" &&
    !reNonSpace.test(p.currentLine.slice(p.nextNonspace + match[0].length))
  ) {
    return null;
  }
  advanceNextNonspace(p);
  advanceOffset(p, match[0].length, true);
  spacesStartCol = p.column;
  spacesStartOffset = p.offset;
  do {
    advanceOffset(p, 1, true);
    nextc = peekChar(p.currentLine, p.offset);
  } while (p.column - spacesStartCol < 5 && isSpaceOrTab(nextc));
  const blankItem = peekChar(p.currentLine, p.offset) === -1;
  const spacesAfterMarker = p.column - spacesStartCol;
  if (spacesAfterMarker >= 5 || spacesAfterMarker < 1 || blankItem) {
    data.padding = match[0].length + 1;
    p.column = spacesStartCol;
    p.offset = spacesStartOffset;
    if (isSpaceOrTab(peekChar(p.currentLine, p.offset))) {
      advanceOffset(p, 1, true);
    }
  } else {
    data.padding = match[0].length + spacesAfterMarker;
  }
  return data;
}

/** Reference `listsMatch`: do two list data records agglomerate? */
function listsMatch(listData: BlockNode["listData"], itemData: BlockNode["listData"]): boolean {
  return (
    listData.type === itemData.type &&
    listData.delimiter === itemData.delimiter &&
    listData.bulletChar === itemData.bulletChar
  );
}

/**
 * Run the block `continue` for one open block. Returns MATCHED (0),
 * UNMATCHED (1), or LINE-CONSUMED (2). This is the ONE continuation operation:
 * each block answers for its CURRENT offset, and the caller stops at the first
 * non-zero.
 */
function continueBlock(p: BlockParser, container: BlockNode): number {
  switch (container.type) {
    case "document":
      return 0;
    case "list":
      return 0;
    case "block_quote": {
      const ln = p.currentLine;
      if (!p.indented && peekChar(ln, p.nextNonspace) === 62 /* > */) {
        advanceNextNonspace(p);
        advanceOffset(p, 1, false);
        if (isSpaceOrTab(peekChar(ln, p.offset))) advanceOffset(p, 1, true);
        return 0;
      }
      return 1;
    }
    case "item": {
      if (p.blank) {
        if (container.firstChild === null) {
          return 1;
        }
        advanceNextNonspace(p);
      } else if (
        p.indent >=
        container.listData.markerOffset + (container.listData.padding ?? 0)
      ) {
        advanceOffset(
          p,
          container.listData.markerOffset + (container.listData.padding ?? 0),
          true,
        );
      } else {
        return 1;
      }
      return 0;
    }
    case "heading":
    case "thematic_break":
      return 1;
    case "code_block": {
      const ln = p.currentLine;
      const indent = p.indent;
      if (container.isFenced) {
        const match =
          indent <= 3 &&
          ln.charAt(p.nextNonspace) === container.fenceChar &&
          ln.slice(p.nextNonspace).match(reClosingCodeFence);
        if (match && match[0].length >= container.fenceLength) {
          p.lastLineLength = p.offset + indent + match[0].length;
          p.trace.closingFence = true;
          finalizeBlock(p, container, p.lineNumber);
          return 2;
        }
        let i = container.fenceOffset;
        while (i > 0 && isSpaceOrTab(peekChar(ln, p.offset))) {
          advanceOffset(p, 1, true);
          i--;
        }
      } else {
        if (indent >= CODE_INDENT) {
          advanceOffset(p, CODE_INDENT, true);
        } else if (p.blank) {
          advanceNextNonspace(p);
        } else {
          return 1;
        }
      }
      return 0;
    }
    case "html_block":
      return p.blank && (container.htmlBlockType === 6 || container.htmlBlockType === 7)
        ? 1
        : 0;
    case "paragraph":
      return p.blank ? 1 : 0;
    default:
      return 1;
  }
}

/**
 * Run the reference's block-start list in order. Returns:
 *   0 = no match, 1 = matched container (keep going), 2 = matched leaf (stop).
 */
function runBlockStarts(
  p: BlockParser,
  containerRef: { node: BlockNode },
): number {
  const container = containerRef.node;
  // 1. block quote
  if (
    !p.indented &&
    peekChar(p.currentLine, p.nextNonspace) === 62 /* > */
  ) {
    advanceNextNonspace(p);
    advanceOffset(p, 1, false);
    if (isSpaceOrTab(peekChar(p.currentLine, p.offset))) advanceOffset(p, 1, true);
    closeUnmatchedBlocks(p);
    addChild(p, "block_quote", p.nextNonspace);
    containerRef.node = p.tip;
    return 1;
  }
  // 2. ATX heading
  {
    let match: RegExpMatchArray | null;
    if (
      !p.indented &&
      (match = p.currentLine.slice(p.nextNonspace).match(reATXHeadingMarker))
    ) {
      const marker = match[0];
      advanceNextNonspace(p);
      advanceOffset(p, marker.length, false);
      closeUnmatchedBlocks(p);
      const heading = addChild(p, "heading", p.nextNonspace);
      heading.stringContent = p.currentLine
        .slice(p.offset)
        .replace(/^[ \t]*#+[ \t]*$/, "")
        .replace(/[ \t]+#+[ \t]*$/, "");
      advanceOffset(p, p.currentLine.length - p.offset, false);
      containerRef.node = p.tip;
      return 2;
    }
  }
  // 3. fenced code block
  {
    let match: RegExpMatchArray | null;
    if (
      !p.indented &&
      (match = p.currentLine.slice(p.nextNonspace).match(reCodeFence))
    ) {
      const fenceLength = match[0].length;
      closeUnmatchedBlocks(p);
      const code = addChild(p, "code_block", p.nextNonspace);
      code.isFenced = true;
      code.fenceLength = fenceLength;
      code.fenceChar = match[0][0] ?? "";
      code.fenceOffset = p.indent;
      advanceNextNonspace(p);
      advanceOffset(p, fenceLength, false);
      containerRef.node = p.tip;
      return 2;
    }
  }
  // 4. HTML block
  if (!p.indented && peekChar(p.currentLine, p.nextNonspace) === 60 /* < */) {
    const s = p.currentLine.slice(p.nextNonspace);
    for (let blockType = 1; blockType <= 7; blockType++) {
      const open = reHtmlBlockOpen[blockType];
      const matched = open !== null && open.test(s);
      if (
        matched &&
        (blockType < 7 ||
          (container.type !== "paragraph" &&
            !(!p.allClosed && !p.blank && p.tip.type === "paragraph")))
      ) {
        closeUnmatchedBlocks(p);
        const b = addChild(p, "html_block", p.offset);
        b.htmlBlockType = blockType;
        containerRef.node = p.tip;
        return 2;
      }
    }
  }
  // 5. setext heading
  {
    let match: RegExpMatchArray | null;
    if (
      !p.indented &&
      container.type === "paragraph" &&
      (match = p.currentLine.slice(p.nextNonspace).match(reSetextHeadingLine))
    ) {
      closeUnmatchedBlocks(p);
      // Strip leading reference definitions from the paragraph before deciding
      // whether any heading TEXT remains (reference: a paragraph that is only
      // reference definitions does NOT become a setext heading).
      container.stringContent = stripReferenceDefinitions(container.stringContent ?? "");
      if ((container.stringContent ?? "").length > 0) {
        const heading = makeBlock("heading", [
          container.sourcepos[0],
          container.sourcepos[1],
        ]);
        heading.stringContent = container.stringContent;
        insertAfter(container, heading);
        unlinkBlock(container);
        p.tip = heading;
        advanceOffset(p, p.currentLine.length - p.offset, false);
        containerRef.node = p.tip;
        return 2;
      }
      // REV66-P1: the paragraph was EMPTIED by reference-definition stripping,
      // so no setext heading is produced. That is NOT "no block start matched" -
      // the reference parser simply moves on to the REMAINING block-start rules,
      // and this line may still open a thematic break (or a list item, etc.).
      // Returning 0 here made the caller append the line to the paragraph and
      // stop, so `[a]: /x` + `---` + STATUS kept a paragraph spanning all three
      // lines and misread the declaration as DEAD. Fall through instead; the
      // paragraph has already been emptied, so nothing is left to continue.
    }
  }
  // 6. thematic break
  if (!p.indented && reThematicBreak.test(p.currentLine.slice(p.nextNonspace))) {
    closeUnmatchedBlocks(p);
    addChild(p, "thematic_break", p.nextNonspace);
    advanceOffset(p, p.currentLine.length - p.offset, false);
    containerRef.node = p.tip;
    return 2;
  }
  // 7. list item
  {
    let data: BlockNode["listData"] | null;
    if (
      (!p.indented || container.type === "list") &&
      (data = parseListMarker(p, container))
    ) {
      closeUnmatchedBlocks(p);
      if (p.tip.type !== "list" || !listsMatch(container.listData, data)) {
        const list = addChild(p, "list", p.nextNonspace);
        list.listData = data;
        containerRef.node = list;
      }
      const item = addChild(p, "item", p.nextNonspace);
      item.listData = data;
      containerRef.node = p.tip;
      return 1;
    }
  }
  // 8. indented code block
  if (p.indented && p.tip.type !== "paragraph" && !p.blank) {
    advanceOffset(p, CODE_INDENT, true);
    closeUnmatchedBlocks(p);
    addChild(p, "code_block", p.offset);
    containerRef.node = p.tip;
    return 2;
  }
  return 0;
}

/** Reference `incorporateLine`, with per-line ownership recorded by the caller. */
function incorporateLine(p: BlockParser, ln: string): void {
  let allMatched = true;
  let container = p.doc;
  p.oldtip = p.tip;
  p.offset = 0;
  p.column = 0;
  p.blank = false;
  p.partiallyConsumedTab = false;
  p.lineNumber += 1;
  if (ln.indexOf("\u0000") !== -1) ln = ln.replace(/\0/g, "\uFFFD");
  p.currentLine = ln;

  // 1. Re-enter open containers from the document downward. Stop at the FIRST
  //    failure; the caller preserves the last matched block.
  let lastChild: BlockNode | null;
  while ((lastChild = container.lastChild) && lastChild.open) {
    container = lastChild;
    findNextNonspace(p);
    const res = continueBlock(p, container);
    if (res === 2) return; // line consumed (a fence closer closed its block)
    if (res === 1) {
      allMatched = false;
    }
    if (!allMatched) {
      container = container.parent ?? p.doc;
      break;
    }
  }

  p.allClosed = container === p.oldtip;
  p.lastMatchedContainer = container;

  let matchedLeaf = container.type !== "paragraph" && acceptsLines(container.type);
  // 2. Offer the surviving level block starts, in the reference order.
  const containerRef = { node: container };
  while (!matchedLeaf) {
    findNextNonspace(p);
    if (!p.indented && !reMaybeSpecial.test(ln.slice(p.nextNonspace))) {
      advanceNextNonspace(p);
      break;
    }
    const res = runBlockStarts(p, containerRef);
    if (res === 1) {
      container = containerRef.node;
      continue;
    } else if (res === 2) {
      container = containerRef.node;
      matchedLeaf = true;
      break;
    } else {
      advanceNextNonspace(p);
      break;
    }
  }

  // 3. Append the remaining text to the appropriate container.
  if (!p.allClosed && !p.blank && p.tip.type === "paragraph") {
    // lazy paragraph continuation
    addLine(p);
  } else {
    closeUnmatchedBlocks(p);
    const t = container.type;
    if (acceptsLines(t)) {
      addLine(p);
      if (
        t === "html_block" &&
        container.htmlBlockType >= 1 &&
        container.htmlBlockType <= 5
      ) {
        const close = reHtmlBlockClose[container.htmlBlockType];
        if (close !== null && close.test(p.currentLine.slice(p.offset))) {
          p.lastLineLength = ln.length;
          finalizeBlock(p, container, p.lineNumber);
        }
      }
    } else if (p.offset < ln.length && !p.blank) {
      container = addChild(p, "paragraph", p.offset);
      p.trace.paragraphStarted[p.lineNumber - 1] = true;
      advanceNextNonspace(p);
      addLine(p);
    }
  }
  p.lastLineLength = ln.length;
}

/**
 * The block tree a line belongs to, plus the two ownership facts consumers read.
 *
 * `changes` / `inside` describe fence membership (an opener line is not
 * "inside"; a closer line is not either — the region strictly between them is).
 *
 * `topLevel` is the STRUCTURAL ownership fact (ENGINE REQUIREMENT 6): true when
 * the line's innermost containing block is a PARAGRAPH whose parent is the
 * document. It is read off the FINALIZED tree, so a paragraph that a reference
 * definition emptied (and the parser unlinked) owns nothing.
 *
 * `paragraphStart` is the PARAGRAPH-START fact: true when the line is the first
 * content line the parser appended to a paragraph. It is recorded DURING the
 * parse (before reference definitions are retroactively stripped), which is what
 * keeps `[a]: /x` + `STATUS:DONE` on ONE paragraph: the declaration did not begin
 * the paragraph, so it is not a declaration. This is the whole of the "a status
 * line directly beneath prose does not declare" policy, kept as a DISTINCT,
 * documented predicate rather than by falsifying the block structure.
 */
type LineStructure = {
  /** Fence-state CHANGES keyed by line index (true opens, false closes). */
  changes: Map<number, boolean>;
  /** True when a line sits strictly inside an open fenced region. */
  inside: boolean[];
  /** True when a line's innermost block is a document-level paragraph. */
  topLevel: boolean[];
  /** True when a line is the first content line of its paragraph. */
  paragraphStart: boolean[];
};

/** The deepest block whose source span covers `line` (1-based), or null. */
function innermostBlockAtLine(root: BlockNode, line: number): BlockNode | null {
  let best: BlockNode | null = null;
  let bestDepth = -1;
  walkBlocks(root, (node, entering) => {
    if (!entering) return;
    const startLine = node.sourcepos[0][0];
    const endLine = node.sourcepos[1][0];
    if (startLine <= line && line <= endLine) {
      let depth = 0;
      for (let n: BlockNode | null = node; n !== null; n = n.parent) depth += 1;
      if (depth > bestDepth) {
        bestDepth = depth;
        best = node;
      }
    }
  });
  return best;
}

/**
 * Derive the per-line structure from ONE transcription of the reference block
 * parser. Every consumer reads this single result, so the container model cannot
 * be implemented twice and drift again.
 */
function lineStructure(text: string): LineStructure {
  const normalized = text.replace(/\r\n?/g, "\n");
  const p = makeParser();
  const lines = normalized.split(reLineEnding);
  let len = lines.length;
  if (normalized.charCodeAt(normalized.length - 1) === 10 /* \n */) len -= 1;
  for (let i = 0; i < len; i++) incorporateLine(p, lines[i]);
  let closing: BlockNode | null = p.tip;
  while (closing !== null) {
    const above: BlockNode | null = closing.parent;
    finalizeBlock(p, closing, len);
    closing = above;
  }
  const doc = p.doc;

  const inside = new Array<boolean>(lines.length).fill(false);
  const topLevel = new Array<boolean>(lines.length).fill(false);
  const paragraphStart = new Array<boolean>(lines.length).fill(false);
  const changes = new Map<number, boolean>();

  // Fence membership from each fenced block's CONTENT range. An opener line is
  // NOT inside; the line ENDING the region (an explicit closer, or the first
  // line after a container-held fence ends) is NOT inside either — the region
  // strictly between them is. `changes` records the opener (true) and the
  // explicit closer (false) for any consumer that reads it.
  for (const fence of p.trace.fences) {
    changes.set(fence.open - 1, true);
    if (fence.closerLine !== null) changes.set(fence.closerLine - 1, false);
    for (let lineNo = fence.open + 1; lineNo <= fence.end; lineNo += 1) {
      if (lineNo - 1 < inside.length) inside[lineNo - 1] = true;
    }
  }

  // Structural ownership from the FINALIZED tree, plus the parse-time
  // paragraph-start fact.
  for (let index = 0; index < lines.length; index += 1) {
    paragraphStart[index] = p.trace.paragraphStarted[index] === true;
    const block = innermostBlockAtLine(doc, index + 1);
    topLevel[index] =
      block !== null && block.type === "paragraph" && block.parent !== null &&
      block.parent.type === "document";
  }

  return { changes, inside, topLevel, paragraphStart };
}

/**
 * True when a line looks like a fence delimiter decorated with trailing
 * backticks, the shape a careless nested fence produces.
 *
 * ```` ```STATUS:CONTINUE x``` ```` must not be read as a declaration: it is
 * prose wrapping the protocol line in backticks, exactly as `` `STATUS:DONE` ``
 * is, and honoring it would let a fenced EXAMPLE in disguise trigger a real
 * continuation. An opening fence therefore never counts as a marker, no matter
 * how many trailing backticks decorate it.
 */
function isFenceDecorated(line: string): boolean {
  const trimmed = line.trimStart();
  if (!trimmed.startsWith("```") && !trimmed.startsWith("~~~")) return false;
  return trimmed.length > 3;
}

/**
 * Walk the message classifying every `STATUS:` line outside fences.
 *
 * Counting is by STATUS-WORD OCCURRENCE, not by line: a single line carrying two
 * words ("STATUS:CONTINUE x or STATUS:DONE") is already two declarations that
 * disagree, and treating it as one line would silently promote documentation or
 * hedging into action.
 */
/**
 * True when a line, considered on its own, would DECLARE a status.
 *
 * This is the single predicate behind both counting and final-line eligibility.
 * Every defect in this unit's history came from one rule implemented twice and
 * drifting apart, so both paths must ask exactly this question:
 *
 *   - column zero (an indented line is prose or an example, never a decision)
 *   - not code (indented, fence-decorated, or inside a fence)
 *   - structurally OWNED: the line's innermost block is a document-level
 *     paragraph (`structure.topLevel`), and
 *   - the PARAGRAPH-START protocol policy: the line must BEGIN that paragraph
 *     (`structure.paragraphStart`). A declaration directly beneath prose is a
 *     continuation of the paragraph above it, not a declaration - the safe loss
 *     the whole container model exists to honour. This is a POLICY about the
 *     `STATUS:` protocol, deliberately SEPARATE from the structural containment
 *     fact: `Work remains.\nSTATUS:CONTINUE p` IS structurally
 *     `document>paragraph`, and it is the paragraph-start rule that reads it
 *     `unknown`. It is never encoded by falsifying the block structure.
 *   - not documentation (a prose menu, or a status word quoted as an example)
 */
function lineDeclares(
  lines: string[],
  index: number,
  structure: LineStructure,
): boolean {
  const line = lines[index].replace(/\s+$/, "");
  if (protocolLine(line) === null) return false;
  if (isIndentedCodeLine(line)) return false;
  if (isFenceDecorated(line)) return false;
  if (structure.inside[index]) return false;
  if (!structure.topLevel[index]) return false;
  if (!structure.paragraphStart[index]) return false;
  if (isDocumentationLine(line)) return false;
  return true;
}

/**
 * Count the lines that would declare a status, and report whether they DISAGREE.
 *
 * Ambiguity means two or more declared statuses that are not the same word: the
 * model said two different things, so the supervisor must not pick one. A line
 * that merely documents the protocol is not a declaration and never competes.
 * Two lines that declare the SAME status agree, and the final one is used.
 */
function countProtocolLines(
  text: string,
  structure: LineStructure,
): { count: number; ambiguous: boolean } {
  const lines = text.split("\n");
  const names: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (!lineDeclares(lines, index, structure)) continue;
    const parsed = protocolLine(lines[index].replace(/\s+$/, ""));
    if (parsed === null) continue;
    names.push(parsed.name.toLowerCase());
  }
  const unique = new Set(names);
  return { count: names.length, ambiguous: unique.size > 1 };
}

/**
 * True when a line only DOCUMENTS the protocol rather than declaring it.
 *
 * One predicate, used by BOTH the counting path and the final-line eligibility
 * path. Keeping it single is deliberate: every defect in this unit's history
 * came from one rule implemented twice and drifting apart.
 */
function isDocumentationLine(line: string): boolean {
  return isProseMenu(line) || mentionsQuotedStatus(line);
}

/**
 * Separator punctuation treated as a MENU JOINER between protocol words.
 *
 * A separator is a token BOUNDARY, in any spacing: "STATUS:DONE or
 * STATUS:WAIT", "STATUS:DONE, STATUS:WAIT", and "STATUS:DONE/STATUS:WAIT" are
 * the same documentation line. Treating them alike is what keeps counting and
 * eligibility from drifting apart.
 *
 * `:` is deliberately NOT here: it is the protocol's own delimiter, so splitting
 * on it would shred `STATUS:` into two tokens.
 */
const MENU_BOUNDARY = /[\s/|,;]+/;

/**
 * True when a line only SHOWS the protocol rather than declaring it.
 *
 * A menu is TWO OR MORE payload-free status words joined by separator
 * punctuation or prose ("STATUS:DONE or STATUS:CONTINUE", "STATUS:WAIT /
 * STATUS:BLOCKED"). A single lone word is a declaration, not a menu:
 * `STATUS:DONE` carries no payload by design, so skipping it would hide a real
 * declaration and defeat ambiguity detection. A payload-bearing word is never a
 * menu either: "STATUS:CONTINUE run tests" declares.
 */
function isProseMenu(line: string): boolean {
  let words = 0;
  for (const part of splitAroundSeparators(line)) {
    if (LONE_STATUS_WORD.test(part)) {
      words += 1;
      continue;
    }
    // Prose joining the words is also a boundary; anything else is not a menu.
    if (PROSE_JOINER.test(part)) continue;
    return false;
  }
  // Two or more bare words joined by separators is the documented house style
  // for announcing the protocol; a lone word is a real declaration.
  return words > 1;
}

/** Split a line on separator punctuation, dropping empty fields. */
function splitAroundSeparators(line: string): string[] {
  return line
    .split(MENU_BOUNDARY)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

/** True for a line indented to Markdown code depth (four COLUMNS): never a marker. */
function isIndentedCodeLine(line: string): boolean {
  // Markdown counts COLUMNS, not characters: a tab advances to the next
  // four-column stop. Counting `length - trimStart().length` treated " \t" as
  // two characters (not code) even though it reaches column four, so its
  // backticks wrongly opened a fence and swallowed the declaration below.
  let column = 0;
  for (const char of line) {
    if (char === " ") column += 1;
    else if (char === "\t") column += 4 - (column % 4);
    else break;
  }
  return column >= 4;
}

/**
 * Parse one candidate protocol line into its lowercase name and payload.
 *
 * A line starting with `STATUS:` that is not a well-formed grammar line still
 * returns a result (`unknown` name) so the caller can distinguish "no protocol
 * line here" (`null`) from "a malformed protocol line here".
 */
function protocolLine(line: string): { name: string; payload: string } | null {
  // Leading whitespace is rejected outright: the marker must be at column zero.
  if (line !== line.trimStart()) return null;
  const candidate = line;
  if (!/^status:/i.test(candidate)) return null;
  // A closing backtick is a typographic decoration (`` `STATUS:DONE` ``), so it
  // is stripped before parsing. The strip must apply ONLY to a pure decoration,
  // never across the token/payload boundary: stripping unconditionally removed
  // the closing backtick of real payload content (`STATUS:CONTINUE fix
  // `STATUS:DONE``) and turned a payload-bearing `STATUS:DONE ``` ` into a
  // payload-free DONE. Match the RAW line first; only if that fails, retry on
  // the backtick-stripped form so genuine decoration still parses.
  const rawMatch = PROTOCOL_LINE.exec(candidate);
  if (rawMatch !== null) {
    return { name: rawMatch[1], payload: (rawMatch[2] ?? "").trim() };
  }
  const trailing = candidate.replace(/`+$/, "");
  if (trailing !== candidate) {
    const match = PROTOCOL_LINE.exec(trailing);
    if (match !== null) {
      return { name: match[1], payload: (match[2] ?? "").trim() };
    }
  }
  return { name: "", payload: "" };
}

/**
 * True when a line quotes a `STATUS:` word: documentation, not a declaration.
 *
 * A backticked status word is ALWAYS a mention. This is the plain form wrapped in
 * one decoration pair, but a status line is an instruction to the supervisor and
 * wrapping it in code spans reads as a quotation of the protocol. Treating the
 * wrapped form as a declaration also produced an inconsistent rule: a payload-free
 * `DONE` declares while a payload-free `WAIT` cannot, because WAIT requires a
 * payload. Documentation must never compete with a real declaration, and the
 * failure direction is the safe one - the line reads as `unknown`, which notifies.
 *
 * SCOPE (a defect fixed here): the mention test applies to the DECLARATION TOKEN
 * AND ITS DECORATION ONLY - never to the executable payload body. A protocol
 * example quoted INSIDE an actionable payload (`STATUS:CONTINUE add a regression
 * for `STATUS:WAIT subagent x complete``) is part of the instruction, not
 * documentation of it. Testing the whole line demoted such a declaration to
 * `unknown`, emitted no bridge, and STOPPED the run - reproducing the very
 * "STATUS:CONTINUE ... but stop" failure this extension exists to prevent. The
 * documented safe direction ("reads as unknown, which notifies") is only safe for
 * payload-free ambiguity; for a payload-bearing CONTINUE it is a silent stop.
 */
function mentionsQuotedStatus(text: string): boolean {
  // Compare only against the declaration token, so a payload body cannot
  // demote its own declaration. `protocolLine` yields the parsed token, and the
  // bare `STATUS:<WORD>` prefix is what a quoted mention must wrap.
  const declared = protocolLine(text);
  if (declared === null) return false;
  // The declaration is CASE-INSENSITIVE, and `declared.name` is lowercased by
  // the parser, so a case-sensitive `indexOf("STATUS:continue")` skips the
  // line's OWN declaration (typed `status:continue`) and lands on a later
  // uppercase spelling inside the payload. The head then includes an earlier
  // quoted mention and the declaration is demoted to documentation - a silent
  // stop. Locate the declaration case-insensitively instead.
  const index = text.toLowerCase().indexOf(`status:${declared.name}`);
  if (index < 0) return false;
  const head = text.slice(0, index + "status:".length + declared.name.length);
  const quoted = QUOTED_STATUS_MENTION_FOR(`STATUS:${declared.name}`);
  return quoted.test(head);
}

/**
 * The five statuses plus `unknown`: the declared status, or `unknown` when there
 * is no usable marker on the final line of the final projected message.
 */
export function declaredStatusOf(message: unknown): DeclaredStatus {
  return readDeclaredMarker(message)?.status ?? "unknown";
}

/**
 * The final message the boundary already projected.
 *
 * The rule deliberately reads the projection rather than the session view: this
 * is the exact list Pi will continue from, and an empty or malformed projection
 * yields `[]`, which the decision table reads as "unknown" and therefore
 * notifies.
 */
function finalProjectedMessage(event: unknown): unknown {
  if (event === null || typeof event !== "object") return undefined;
  const context = (event as { context?: unknown }).context;
  if (context === null || typeof context !== "object") return undefined;
  const messages = (context as { contextMessages?: unknown }).contextMessages;
  if (!Array.isArray(messages) || messages.length === 0) return undefined;
  return messages[messages.length - 1];
}

/** Extract a zellij pane id from the event payload, then from the environment. */
function extractPaneId(payload: unknown, env: { ZELLIJ_PANE_ID?: string }): string {
  const fromEvent =
    payload !== null && typeof payload === "object"
      ? (payload as { paneId?: unknown }).paneId
      : undefined;
  if (typeof fromEvent === "string" && fromEvent.length > 0) return fromEvent;
  const fromEnv = env.ZELLIJ_PANE_ID;
  return typeof fromEnv === "string" ? fromEnv : "";
}

/** Boundary event shape this extension reads. */
interface AgentBeforeSettleLike {
  entries?: unknown[];
  continue: boolean;
  outcome: "completed" | "aborted" | "error";
  context?: { contextMessages?: unknown[]; canContinue?: boolean; pendingMessages?: unknown[] };
}

/**
 * A wake-proof reference parsed out of a WAIT payload.
 *
 * Recognized forms, each a `STATUS:WAIT` payload naming work that will wake this
 * session:
 *
 *   subagent <id> <event>          - a pi-subagents async run
 *   provider <owner> <id> <event>  - a provider-owned pending item
 *
 * Anything else is an UNVERIFIED claim. Parsing is deliberately syntactic: this
 * extension never classifies English prose, because rejecting a WAIT for using
 * a loaded word ("await", "launch") would also reject legitimate test and
 * implementation payloads that merely describe such a step.
 */
export type WakeProof =
  | { kind: "subagent"; id: string; event: string }
  | { kind: "provider"; owner: string; id: string; event: string };

/** Parse a WAIT payload into a wake-proof reference, or null when it names none. */
export function parseWakeProof(payload: string): WakeProof | null {
  const tokens = payload.trim().split(/\s+/).filter((token) => token.length > 0);
  if (tokens.length === 0) return null;

  if (tokens[0].toLowerCase() === "subagent" && tokens.length >= 3) {
    const [, id, ...rest] = tokens;
    const event = rest.join(" ").trim();
    return id.length > 0 && event.length > 0 ? { kind: "subagent", id, event } : null;
  }

  if (tokens[0].toLowerCase() === "provider" && tokens.length >= 4) {
    const [, owner, id, ...rest] = tokens;
    const event = rest.join(" ").trim();
    return owner.length > 0 && id.length > 0 && event.length > 0
      ? { kind: "provider", owner, id, event }
      : null;
  }

  return null;
}

/**
 * The structured form of a `STATUS:BLOCKED` payload.
 *
 * `user` names an Oracle run and a dependency id; `external` names a nonhuman
 * owner. Anything else is `unstructured` (or `invalid` when a form was clearly
 * attempted but its required fields are absent), which routes to decision
 * repair rather than to a user question.
 */
export type BlockedDeclaration =
  | { form: "user"; oracleRunId: string; dependencyId: string; description: string }
  | { form: "external"; owner: string; description: string }
  | { form: "unstructured"; description: string }
  | { form: "invalid"; description: string };

/**
 * Parse a `STATUS:BLOCKED` payload into one of the two STRUCTURED forms.
 *
 * The grammar is fixed and token-based; free prose is never interpreted for
 * ownership:
 *
 *   user oracle=<run-id> dependency=<dependency-id> <description>
 *   external owner=<nonhuman-owner> <description>
 *
 * The FORM DISCRIMINATOR is the LEADING token, and each form's proof fields are
 * REQUIRED by that discriminator - not inferred from whichever keys happen to be
 * present:
 *
 *   - a leading `user` requires BOTH `oracle=` and `dependency=`, each exactly
 *     once, and rejects an `owner=` key (a `user owner=...` payload is a botched
 *     USER form and is `invalid`, never silently reclassified as `external`);
 *   - a leading `external` requires `owner=`, each exactly once, and rejects
 *     `oracle=`/`dependency=` keys.
 *
 * Duplicate or conflicting proof fields (two `oracle=` keys, both `user` and
 * `owner=`) and a missing/empty proof value are all `invalid`, so a botched
 * structured form can never slip through a weaker gate by accident. A payload
 * with NO recognized leading form discriminator is unstructured only when it
 * carries no proof key at all: the presence of ANY `owner=`, `oracle=`, or
 * `dependency=` token without a form word is a BOTCHED structured declaration
 * and is `invalid` - `external` is never an accepted ungated blocker, so a bare
 * `owner=...` cannot bypass the user-proof gate by looking like an external
 * dependency. Genuinely unstructured prose (no proof keys) stays `unstructured`.
 */
export function parseBlockedDeclaration(payload: string): BlockedDeclaration {
  const tokens = payload.trim().split(/\s+/).filter((token) => token.length > 0);
  if (tokens.length === 0) return { form: "unstructured", description: "" };
  const description = tokens.join(" ");

  const oracleTokens = tokens.filter((t) => /^oracle=/i.test(t));
  const dependencyTokens = tokens.filter((t) => /^dependency=/i.test(t));
  const ownerTokens = tokens.filter((t) => /^owner=/i.test(t));
  const leading = tokens[0].toLowerCase();

  if (leading === "user") {
    // A user proof is exactly `user` plus one `oracle=`/`dependency=` pair; any
    // owner key, duplicate, or missing value is INVALID (never external).
    if (oracleTokens.length !== 1 || dependencyTokens.length !== 1 || ownerTokens.length !== 0) {
      return { form: "invalid", description };
    }
    const run = tokenValue(tokens, "oracle");
    const dep = tokenValue(tokens, "dependency");
    if (run === null || dep === null) return { form: "invalid", description };
    return { form: "user", oracleRunId: run, dependencyId: dep, description };
  }

  if (leading === "external") {
    // An external dependency is exactly `external` plus one `owner=` value; a
    // user proof key here is a conflict and is INVALID.
    if (ownerTokens.length !== 1 || oracleTokens.length !== 0 || dependencyTokens.length !== 0) {
      return { form: "invalid", description };
    }
    const owner = tokenValue(tokens, "owner");
    if (owner === null) return { form: "invalid", description };
    return { form: "external", owner, description };
  }

  // No recognized leading form discriminator. Any proof key here is a BOTCHED
  // structured declaration: a bare `owner=` must NOT be classified as an
  // `external` dependency (that would bypass the user-proof gate), and a bare
  // `oracle=`/`dependency=` pair must NOT be classified as `user` without the
  // `user` discriminator. Only prose with no proof keys at all is unstructured.
  if (oracleTokens.length > 0 || dependencyTokens.length > 0 || ownerTokens.length > 0) {
    return { form: "invalid", description };
  }

  return { form: "unstructured", description };
}

/** The value of the first `key=value` token, or null when absent/empty. */
function tokenValue(tokens: string[], key: string): string | null {
  const prefix = `${key.toLowerCase()}=`;
  for (const token of tokens) {
    const lowered = token.toLowerCase();
    if (!lowered.startsWith(prefix)) continue;
    const value = token.slice(prefix.length);
    return value.length > 0 ? value : null;
  }
  return null;
}

/**
 * Narrow LEADING human-wait clauses: an idempotent repair of a CONTINUE whose
 * payload states the model is waiting on the user rather than acting now.
 *
 * Only the payload's LEADING clause is examined, and only these exact phrases
 * (case-insensitive): "awaiting your pick", "waiting for your answer",
 * "waiting on the user". This is deliberately NOT a keyword blacklist:
 * "wait", "await", and "WAIT" appear all over legitimate implementation and
 * test steps ("implement the WAIT branch", "await the fixture") and none of
 * those are human-wait clauses. Only a payload that OPENS with one of the
 * phrases above is rejected.
 */
export function humanWaitingLeadingClause(payload: string): boolean {
  const text = payload.trim().toLowerCase();
  return (
    text.startsWith("awaiting your pick") ||
    text.startsWith("waiting for your answer") ||
    text.startsWith("waiting on the user")
  );
}

/**
 * One versioned `USER_INPUT_REQUIRED` assessment parsed out of a result.
 *
 * `question` is kept raw so the caller can compare it to a `USER_QUESTION:`
 * line without normalization surprises.
 */
export interface UserInputAssessment {
  dependencyId: string;
  outcome: string;
  kind: string;
  question: string;
  requestEpoch?: string;
}

/**
 * Parse EXACTLY ONE unambiguous, correctly-versioned Oracle assessment record.
 *
 * Rules, all of which must hold for a record to be usable:
 *
 *   * exactly one `oracle-input-assessment` fenced json block may be present;
 *     zero blocks, a block that is not valid JSON, or two or more such blocks
 *     resolve to null (an ambiguous result is not evidence);
 *   * `version` must be the number 1 (or the string "1");
 *   * `outcome` must be exactly `USER_INPUT_REQUIRED`;
 *   * `dependencyId` must be nonempty.
 *
 * A record with `outcome: "AGENT_DECISION"` therefore parses as null, which is
 * what makes referencing an agent-decision Oracle result unable to authorize a
 * user question.
 */
export function parseUserInputAssessment(result: unknown): UserInputAssessment | null {
  if (typeof result !== "string") return null;
  // The documented record lives in an `oracle-input-assessment` fence. As a
  // compatibility path, a bare ```json fence whose object carries the
  // assessment shape is also accepted, so a host that strips the info string
  // still works. BOTH forms are counted TOGETHER into one candidate list: a
  // tagged assessment plus a competing bare-JSON assessment is TWO records and
  // therefore ambiguous. Each PHYSICAL fence is classified exactly once, so a
  // single `json oracle-input-assessment` block is never double-counted.
  const candidates = assessmentFenceBodies(result);
  if (candidates.length !== 1) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(candidates[0]);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object") return null;
  const record = parsed as Record<string, unknown>;

  if (!isAssessmentVersionOne(record.version)) return null;
  if (record.outcome !== "USER_INPUT_REQUIRED") return null;
  const dependencyId = typeof record.dependencyId === "string" ? record.dependencyId.trim() : "";
  if (dependencyId.length === 0) return null;

  return {
    dependencyId,
    outcome: "USER_INPUT_REQUIRED",
    kind: typeof record.kind === "string" ? record.kind : "",
    question: typeof record.question === "string" ? record.question.trim() : "",
    requestEpoch: typeof record.requestEpoch === "string" ? record.requestEpoch : undefined,
  };
}

/**
 * Collect the bodies of every fence that could be an assessment record.
 *
 * A single pass classifies each PHYSICAL fence exactly once so a fence that
 * matches both tags (`json oracle-input-assessment`) cannot be counted twice:
 *
 *   * a fence whose info string names `oracle-input-assessment` is a candidate
 *     unconditionally (the documented record survives a shape check later);
 *   * a bare ```json fence is a candidate ONLY when its object already has the
 *     assessment shape, which keeps an unrelated structured block (a Review
 *     verdict, say) from competing;
 *   * anything else is not a candidate.
 */
function assessmentFenceBodies(text: string): string[] {
  const candidates: string[] = [];
  const fence = /```([^\n`]*)\r?\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  while ((match = fence.exec(text)) !== null) {
    const info = match[1];
    const body = match[2];
    if (fenceTagMatches(info, "oracle-input-assessment")) {
      candidates.push(body);
      continue;
    }
    if (fenceTagMatches(info, "json") && looksLikeAssessment(body)) {
      candidates.push(body);
    }
  }
  return candidates;
}

/** True when a parsed json block carries the assessment record's shape. */
function looksLikeAssessment(block: string): boolean {
  try {
    const parsed = JSON.parse(block);
    if (parsed === null || typeof parsed !== "object") return false;
    const record = parsed as Record<string, unknown>;
    return typeof record.outcome === "string" && typeof record.dependencyId === "string";
  } catch {
    return false;
  }
}

/** Version 1 is accepted as the JSON number `1` or the string `"1"`. */
function isAssessmentVersionOne(version: unknown): boolean {
  return version === 1 || version === "1";
}

/**
 * True when an info string names `tag` as its first token, or as the token
 * after a leading `json`.
 *
 * Oracle's documented info string is exactly `oracle-input-assessment`, and the
 * `json <tag>` form is accepted as an equivalent. A bare ```json fence (empty
 * info string, or `json` alone) matches only the `json` tag, which the caller
 * uses as its compatibility path.
 */
function fenceTagMatches(info: string, tag: string): boolean {
  const tokens = info
    .trim()
    .split(/\s+/)
    .filter((token) => token.length > 0)
    .map((token) => token.toLowerCase());
  const lowered = tag.toLowerCase();
  if (tokens[0] === lowered) return true;
  return tokens[0] === "json" && tokens[1] === lowered;
}

/**
 * Extract every ELIGIBLE `USER_QUESTION:` line from a message, trimmed.
 *
 * The scan is over the PARENT's projected final message - the same source that
 * declares the marker - never over the Oracle artifact: the protocol requires
 * the PARENT to repeat the question, while Oracle's own artifact carries only
 * the assessment record. Eligibility mirrors the marker's container rules so a
 * fenced EXAMPLE (` ```\nUSER_QUESTION: ...\n``` `), an indented code line, or a
 * fence-decorated line is documentation, not a question:
 *
 *   - the literal prefix must start at column zero;
 *   - the line must not be indented code;
 *   - the line must not be fence-decorated (a backtick-wrapped example);
 *   - the line must not sit INSIDE a fenced region;
 *   - the line must not sit in a LAZY continuation of an OPEN container, where
 *     a quoted example (`> Example:` then an unmarked following line) would
 *     otherwise count as the parent's own question.
 *
 * Every one of those rules - fence membership, indentation, decoration, AND
 * container ownership - is read from the ONE `lineStructure` walk: the last rule
 * is exactly the line's `topLevel` flag, which is "the line carries no container
 * at document level and is not a lazy paragraph continuation". A column-zero
 * question directly beneath a container-fence CLOSER (whose block ENDED there)
 * is therefore top level, while one beneath an open quoted/list PARAGRAPH is
 * not. Reading a SEPARATE container scan here (the former `isInLazyContainer`)
 * let question ownership drift from marker ownership and admit/refuse questions
 * inconsistently with the marker (DEFECT A7).
 *
 * Only zero or a single eligible line can ever satisfy the caller's
 * "unique eligible question" requirement; two-or-more is ambiguous and
 * unusable.
 */
export function userQuestionLines(result: unknown): string[] {
  if (typeof result !== "string") return [];
  const text = result.replace(/\r\n?/g, "\n");
  const lines = text.split("\n");
  const structure = lineStructure(text);
  const found: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].replace(/\s+$/, "");
    if (!line.startsWith("USER_QUESTION:")) continue;
    if (isIndentedCodeLine(line)) continue;
    if (isFenceDecorated(line)) continue;
    if (structure.inside[index]) continue;
    if (!structure.topLevel[index]) continue;
    // The question's OWN line must either BEGIN its document paragraph, or be a
    // SIBLING of an immediately preceding eligible question line. Two adjacent
    // TOP-LEVEL questions are BOTH declarations whose disagreement must be
    // caught, and the second is formally a continuation of the first paragraph;
    // any OTHER kind of paragraph continuation (prose beneath prose) is not the
    // parent's question. This mirrors the marker's paragraph-start policy while
    // keeping the sibling rule the tests require.
    const sibling = questionSiblingAt(lines, index - 1, structure);
    if (!structure.paragraphStart[index] && !sibling) continue;
    found.push(line.slice("USER_QUESTION:".length).trim());
  }
  return found;
}

/**
 * True when line `index` is part of a run of consecutive top-level
 * `USER_QUESTION:` lines whose FIRST line begins its document paragraph. Such a
 * line is a SIBLING declaration: the protocol lets adjacent top-level questions
 * all compete, so their disagreement is caught instead of silently resolving to
 * the first. A question beneath ordinary prose fails this test (the run breaks
 * on the prose line before it reaches a paragraph-start question).
 */
function questionSiblingAt(
  lines: string[],
  index: number,
  structure: LineStructure,
): boolean {
  let cursor = index;
  while (cursor >= 0) {
    const line = lines[cursor].replace(/\s+$/, "");
    if (!line.startsWith("USER_QUESTION:")) return false;
    if (isIndentedCodeLine(line)) return false;
    if (isFenceDecorated(line)) return false;
    if (structure.inside[cursor]) return false;
    if (!structure.topLevel[cursor]) return false;
    if (structure.paragraphStart[cursor]) return true; // run starts here
    cursor -= 1;
  }
  return false;
}

/**
 * The verifiable facts this extension can require of an Oracle run it witnessed.
 */
export interface ObservedRunEvidence {
  /** Absolute async directory the START event named, or null when unknown. */
  asyncDir: string | null;
  /** Absolute path to the final structured result, or null when unavailable. */
  resultPath: string | null;
  /** The raw result text, or null when it could not be read. */
  result: string | null;
  /** True when `status.json.state === "complete"`. */
  completed: boolean;
  /**
   * True only when a result artifact EXISTS but could not be read IN FULL - it
   * exceeds `MAX_RESULT_ARTIFACT_BYTES`, or the read returned fewer bytes than
   * the file holds. A truncated read can never establish whole-result
   * uniqueness (an unread suffix may hold a second assessment or a competing
   * question), so the evidence is unusable and the caller fails closed with
   * this distinct diagnostic. Absent when the result was read whole or is
   * simply missing.
   */
  truncated?: boolean;
}

/**
 * Read one bounded completion/result artifact from an ALREADY-OBSERVED async
 * dir.
 *
 * `asyncDir` must come from an observed START event; this function never
 * accepts a caller/model-supplied path. Within that dir it reads `status.json`
 * for the completion fact (`state === "complete"`) and the authoritative result
 * path (`outputFile`), then reads that file. Every failure mode - a missing dir,
 * unreadable status, a state other than `complete`, a missing result, an
 * oversized artifact - yields the honest shape: `completed: false` and/or a
 * null `result`, which the caller treats as unverified.
 *
 * The process exit code is NOT consulted: completion is `state === "complete"`,
 * never a process signal, exactly as pinned by the real run shape.
 */
export function readObservedRunEvidence(
  asyncDir: string,
  readFile: ReadFile = defaultReadFile,
  statSize: (path: string) => number | null = defaultStatSize,
): ObservedRunEvidence {
  const empty: ObservedRunEvidence = { asyncDir, resultPath: null, result: null, completed: false };
  if (typeof asyncDir !== "string" || asyncDir.length === 0) return empty;

  const status = readJsonArtifact(join(asyncDir, "status.json"), readFile);
  if (status === null) return empty;

  const state = typeof status.state === "string" ? status.state : "";
  const completed = state === "complete";

  const outputs = status.outputs;
  const outputFile =
    typeof status.outputFile === "string" && status.outputFile.length > 0
      ? status.outputFile
      : outputs !== null && typeof outputs === "object" && typeof (outputs as { path?: unknown }).path === "string"
        ? ((outputs as { path: string }).path ?? null)
        : null;

  const resultPath = isAbsolutePath(outputFile) ? outputFile : outputFile === null ? null : join(asyncDir, outputFile);
  const size = resultPath === null ? null : statSize(resultPath);
  let result = resultPath === null ? null : readFile(resultPath) ?? null;

  // Whole-result uniqueness cannot be established from a partial read: a
  // truncated prefix could hold one valid assessment while the unread suffix
  // holds a competing one, or a conflicting question line. Oversize and
  // short-read artifacts therefore yield UNUSABLE evidence (fail closed).
  const oversize = size !== null && size > MAX_RESULT_ARTIFACT_BYTES;
  const shortRead = result !== null && size !== null && Buffer.byteLength(result, "utf8") < size;
  const truncated = oversize || shortRead;
  if (truncated) result = null;

  return truncated
    ? { asyncDir, resultPath, result, completed, truncated: true }
    : { asyncDir, resultPath, result, completed };
}

/** One injected read function so tests can supply a fixture map. */
export type ReadFile = (path: string) => string | null;

/**
 * The size of a file, or null when it cannot be stat-ed.
 *
 * Injected alongside `readFile` so a test can model an artifact whose declared
 * size disagrees with what the reader returned (a short read) without needing a
 * real multi-megabyte fixture.
 */
function defaultStatSize(path: string): number | null {
  try {
    return statSync(path).size;
  } catch {
    return null;
  }
}

/** The most-recent bytes of a session transcript read for confirmation. */
export const TRANSCRIPT_TAIL_BYTES = 512 * 1024;

/**
 * Worst-case serialized bytes one UTF-16 code unit of transcript text can cost.
 *
 * `JSON.stringify` escapes a control character (and `"`/`\\`) to `\uXXXX`, which
 * is SIX bytes per code unit; a valid non-ASCII code unit is emitted raw and
 * UTF-8 encodes to at most three bytes (an astral pair, two code units, to four).
 * SIX is therefore the per-code-unit worst case, so `6 * text.length` is a
 * conservative upper bound on the serialized row's UTF-8 byte length.
 */
export const TRANSCRIPT_ROW_WORST_CASE_BYTES_PER_CODE_UNIT = 6;

/** Fixed JSON key/framing overhead of one persisted transcript row. */
const TRANSCRIPT_ROW_FIXED_OVERHEAD_BYTES = 512;

/**
 * A conservative WORST-CASE bound on the serialized transcript-row bytes for a
 * candidate `TASK:ADD` prompt.
 *
 * The host persists a delivered message as a JSONL row that wraps the injected
 * text in a JSON object (`{type:"message", message:{role:"user", content:[{
 * type:"text", text:<injected>}]}}`), so the row can expand well beyond the
 * prompt's own length: every code unit may escape to six bytes and the row adds
 * fixed key framing. `transcriptConfirmsDelivery` reads only the last
 * `TRANSCRIPT_TAIL_BYTES` of the transcript and SKIPS a line it cannot
 * `JSON.parse`, so a delivery row that begins BEFORE the tail window can NEVER be
 * positively correlated and its occurrence would re-send forever. This bound is
 * therefore computed at `TASK:ADD` time to REJECT an oversized task BEFORE it is
 * accepted, persisted, or armed (see `addTask`).
 */
export function worstCaseTaskRowBytes(taskId: string, prompt: string): number {
  // The injected text is the correlation envelope + "\n" + the prompt. The
  // occurrence id is opaque but bounded (`oc-` + 32 hex), so use its maximum
  // width to stay conservative regardless of the id minted at arm time.
  const envelope = taskOccurrenceEnvelope(taskId, `oc-${"f".repeat(32)}`);
  const text = `${envelope}\n${prompt}`;
  return (
    text.length * TRANSCRIPT_ROW_WORST_CASE_BYTES_PER_CODE_UNIT +
    TRANSCRIPT_ROW_FIXED_OVERHEAD_BYTES
  );
}

/**
 * Read the TAIL of a persisted session transcript, or null when unreadable.
 *
 * Oracle OPTION D: confirmation reads the PERSISTED transcript, not an event.
 * A session JSONL grows for the life of the session and can exceed the 2 MiB
 * whole-artifact cap `defaultReadFile` enforces, so this reads only the most
 * recent `TRANSCRIPT_TAIL_BYTES`. The just-appended delivery row is one of the
 * LAST lines, so a tail is sufficient; a partial first line is simply ignored by
 * the line parser (an unparseable JSON line is skipped). The read is
 * FAIL-CLOSED: any error resolves to null (no confirmation), so an unreadable
 * transcript can never fabricate a commit.
 */
function readTranscriptTail(path: string): string | null {
  let fd: number | null = null;
  try {
    const size = statSync(path).size;
    if (size <= 0) return "";
    const length = Math.min(size, TRANSCRIPT_TAIL_BYTES);
    const start = size - length;
    const buffer = Buffer.alloc(length);
    fd = openSync(path, "r");
    let offset = 0;
    while (offset < length) {
      const read = readSync(fd, buffer, offset, length - offset, start + offset);
      if (read <= 0) break;
      offset += read;
    }
    if (offset < length) return null;
    return buffer.toString("utf8");
  } catch {
    return null;
  } finally {
    if (fd !== null) {
      try {
        closeSync(fd);
      } catch {
        // best-effort only
      }
    }
  }
}

/**
 * Whether a transcript tail contains a `role: "user"` row carrying `envelope`.
 *
 * Correlation requires BOTH the exact envelope string AND `role: "user"`: an
 * assistant message that merely echoes the envelope text (a quoted example, a
 * restatement) MUST NOT confirm delivery. Rows are the host's persisted JSONL
 * entries (`{type:"message", message:{role, content:[{type:"text",text}]}}`);
 * a line that does not parse, or carries no text, is skipped rather than
 * interpreted. The check is a substring match on the exact envelope, which the
 * opaque occurrence id makes unambiguous.
 */
export function transcriptConfirmsDelivery(transcript: string | null, envelope: string): boolean {
  if (transcript === null || transcript.length === 0) return false;
  for (const line of transcript.split("\n")) {
    if (line.length === 0) continue;
    let entry: unknown;
    try {
      entry = JSON.parse(line);
    } catch {
      continue; // a partial tail line cannot confirm anything
    }
    if (entry === null || typeof entry !== "object") continue;
    const message = (entry as { message?: unknown }).message;
    if (message === null || typeof message !== "object") continue;
    if ((message as { role?: unknown }).role !== "user") continue;
    const content = (message as { content?: unknown }).content;
    if (!Array.isArray(content)) continue;
    for (const part of content) {
      if (part === null || typeof part !== "object") continue;
      const text = (part as { text?: unknown }).text;
      if (typeof text === "string" && text.includes(envelope)) return true;
    }
  }
  return false;
}

/**
 * Filesystem reader used in production; any failure resolves to null.
 *
 * The read is BOUNDED to `MAX_RESULT_ARTIFACT_BYTES` so a runaway log cannot
 * allocate unbounded memory or wedge a settle. The bound is a FAIL-CLOSED gate,
 * not a truncation: an artifact larger than the cap resolves to null rather than
 * exposing a usable prefix, because a prefix can hide a second assessment or a
 * conflicting question in its unread suffix and so cannot prove
 * whole-result uniqueness. A read that returns fewer bytes than the file holds
 * (a short/incomplete read) resolves to null for the same reason.
 */
function defaultReadFile(path: string): string | null {
  let fd: number | null = null;
  try {
    const size = statSync(path).size;
    // Fail closed on an oversized artifact: a prefix is not whole-result proof.
    if (size > MAX_RESULT_ARTIFACT_BYTES) return null;
    const buffer = Buffer.alloc(size);
    fd = openSync(path, "r");
    let offset = 0;
    // `readSync` may legitimately return fewer bytes than requested; keep
    // filling so a genuine shortfall (truncation/error) is distinguishable.
    while (offset < size) {
      const read = readSync(fd, buffer, offset, size - offset, offset);
      if (read <= 0) break;
      offset += read;
    }
    // A short read cannot prove the whole artifact was seen: fail closed.
    if (offset < size) return null;
    return buffer.toString("utf8");
  } catch {
    return null;
  } finally {
    if (fd !== null) {
      try {
        closeSync(fd);
      } catch {
        // best-effort only
      }
    }
  }
}

/** Read and parse one JSON artifact, or null when absent or malformed. */
function readJsonArtifact(path: string, readFile: ReadFile): Record<string, unknown> | null {
  const raw = readFile(path);
  if (raw === null) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed !== null && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** True for an absolute POSIX path; the async dir layout is always absolute. */
function isAbsolutePath(path: string | null): path is string {
  return typeof path === "string" && path.startsWith("/");
}

/**
 * The bare parent session UUID (not a path), used to bind observed runs.
 *
 * `status.json.sessionId` is a session FILE PATH whose basename ends in the
 * UUID, while `ctx.sessionId` is the bare UUID. Both are normalized to this
 * form before comparison so a UUID is never compared directly to a path.
 */
export function sessionUuid(value: string | undefined): string {
  if (typeof value !== "string" || value.length === 0) return "";
  const base = value.split("/").pop() ?? value;
  const withoutExt = base.replace(/\.jsonl$/i, "");
  // Session file basenames are `<timestamp>_<uuid>`; take the trailing UUID.
  const uuidMatch = /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.exec(
    withoutExt,
  );
  if (uuidMatch !== null) return uuidMatch[1].toLowerCase();
  return withoutExt.toLowerCase();
}

/**
 * An async run this extension personally witnessed start, kept in the ledger.
 */
export interface ObservedRun {
  runId: string;
  agent: string;
  asyncDir: string | null;
  /** The parent session path observed on the START event, or the ledger's. */
  session: string;
  /** Bare parent session UUID; used to bind the run to this session. */
  sessionUuid: string;
  /** Epoch (ledger counter) current when the run was observed. */
  requestEpoch: number;
  /** True only when the child reached a terminal state before this turn. */
  terminal: boolean;
  /**
   * R6-5: false when this run's START can NEVER produce an independent
   * completion wake to THIS parent. A workflow-awaited async child publishes to
   * a workflow-owned path and its completion carries `triggerTurn: false` +
   * `awaitedByWorkflow: true`, which the notifier explicitly SKIPS
   * (`runs/background/notify.js:725-728`). Such a run must never corroborate a
   * WAIT: silent waiting would end only when some OTHER run happened to settle,
   * which is exactly the false-WAIT the user reported.
   *
   * Fail-CLOSED default is true only for a witnessed non-workflow START; any
   * START whose delivery cannot be established records false.
   */
  deliveryCapable: boolean;
}

/**
 * One persisted OBSERVED-RUN PROVENANCE record (protocol version 2).
 *
 * This is what a reloaded session may remember: that THIS session witnessed the
 * named run START, under which request epoch and agent. It deliberately records
 * NO verification outcome, no timer, and no execution permit - provenance lets a
 * resumed session RE-EVALUATE the same run against the live bridge, never
 * inherit a decision to stay silent.
 *
 * CORR12/NEW-1: version 2 adds `lineage`, the per-registration identity that
 * produced this record. The request epoch alone is numerically ambiguous - a
 * later registration resets the counter and can reuse an earlier epoch value -
 * so `requestEpoch` cannot by itself say WHICH registration witnessed the run.
 * A version-1 record predates `lineage` and parses with an EMPTY lineage, which
 * can never equal a version-2 registration's token, so legacy records are never
 * admitted as current-lineage provenance.
 */
export interface ProvenanceRecord {
  runId: string;
  agent: string;
  asyncDir: string | null;
  /** Bare parent session UUID the observation was bound to. */
  sessionUuid: string;
  /** Request epoch (ledger counter) current when the run was witnessed. */
  requestEpoch: number;
  /**
   * CORR12/NEW-1: the per-registration LINEAGE token that witnessed this run.
   *
   * Restoration admits a record only when its lineage equals the CURRENT
   * registration's lineage, so a numerically equal epoch from a SUPERSEDED
   * registration cannot resurrect provenance. Absent (a version-1 legacy
   * record) parses as `""`, which never equals a live registration's token.
   */
  lineage: string;
  /**
   * F3: the RUNTIME INSTANCE that witnessed the start.
   *
   * Session uuid + epoch are NOT sufficient to bind wake trust: reopening the
   * same session in another process yields the same uuid, and restoration
   * re-stamps every record into the CURRENT epoch, so a foreign process would
   * otherwise inherit a wake it cannot honour. pi-subagents gates result
   * delivery on `completionOwnerId` and rejects a foreign owner, but that value
   * is absent from the status payload, so this extension cannot verify the
   * lease directly. It therefore binds provenance to its OWN runtime instance:
   * a record witnessed by a DIFFERENT instance can only be corroborated after
   * this process re-witnesses the run itself.
   */
  runtimeInstanceId: string;
  /**
   * PG4/AC-F2-2: true once a GENUINELY terminal observation retired this run.
   *
   * MUST be materialised here rather than deleting the record. A terminal
   * observation is POSITIVE evidence that the wake path is gone, and AC-F2-2
   * requires it to produce the static unverified notice. Deleting the record
   * would erase that evidence and leave the run looking merely UNKNOWN, which
   * is a weaker signal than "we watched it finish". A record with `terminal`
   * set therefore never corroborates a WAIT, on this load or after a reload.
   */
  terminal: boolean;
  /**
   * R6-5: persisted delivery capability. False when the START could not
   * establish an independent completion wake to this parent (see
   * `ObservedRun.deliveryCapable`). Persisted so the rejection survives a
   * reload, exactly like `terminal`.
   */
  deliveryCapable: boolean;
}

/**
 * A per-PROCESS runtime instance id.
 *
 * Deliberately NOT persisted: it exists to distinguish THIS process from any
 * other process that opens the same session file. A reader that reuses this id
 * across processes would defeat the binding.
 *
 * PG5 - PROCESS-STABLE, NOT MODULE-STABLE. The id is anchored on a process-wide
 * global (`globalThis`), so a native `/reload` that re-evaluates this module
 * KEEPS the id. Pi's reload clears its extension cache and re-loads through
 * Jiti with `moduleCache: false` (`resource-loader.js:352-355`,
 * `loader.js:477-481`), so a module-scoped initializer would mint a NEW id on
 * every reload and reject the provenance that very process had just persisted-
 * a same-process reload would look like a foreign process.
 *
 * WHAT IT ATTEST: "this process witnessed the run start". It is a PROXY for
 * ownership, not pi-subagents' `completionOwnerId` delivery lease, which the
 * `status` payload never carries. It is therefore sufficient to reject a
 * DIFFERENT process's restored provenance, and NOT sufficient to prove that
 * this process owns result delivery for the run.
 */
const RUNTIME_INSTANCE_GLOBAL = "__sessionSupervisorRuntimeInstanceId__";

function mintRuntimeInstanceId(): string {
  try {
    const bytes = new Uint8Array(16);
    if (typeof globalThis.crypto?.getRandomValues === "function") {
      globalThis.crypto.getRandomValues(bytes);
      return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    }
  } catch {
    // fall through to the time-based id below
  }
  return `rt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const runtimeIdHost = globalThis as unknown as Record<string, unknown>;

/**
 * CORR12/NEW-1: mint a fresh REGISTRATION LINEAGE token.
 *
 * A random, collision-free string that is DELIBERATELY independent of the
 * numeric request counter: the counter is registration-local and restarts, so
 * its VALUE cannot tell a genuine new registration from a reused epoch. The
 * token is minted once per `registerSessionSupervisor` call (in production,
 * once per module load) and is persisted alongside the generation. A native
 * same-process `/reload` re-evaluates this module with `moduleCache:false`, so
 * the freshly-minted token would NOT survive it on its own; the current
 * lineage is therefore RECOVERED from the persisted branch on a continuing
 * `reload`/`resume` (see `currentLineageGeneration`). A genuine new process or
 * non-continuing `startup` mints a token that no persisted marker carries, so
 * it opens a distinct lineage and inherits nothing.
 */
function mintLineageToken(): string {
  try {
    const bytes = new Uint8Array(16);
    if (typeof globalThis.crypto?.getRandomValues === "function") {
      globalThis.crypto.getRandomValues(bytes);
      return `ln-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
    }
  } catch {
    // fall through to the time-based id below
  }
  return `ln-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Process-stable id storage.
 *
 * A non-enumerable property keeps this out of casual enumeration while still
 * surviving module re-evaluation within the same process. If the host refuses
 * the definition (a frozen global), the module-local fallback below still
 * yields a stable id for THIS module load.
 */
function processRuntimeInstanceId(): string {
  const existing = runtimeIdHost[RUNTIME_INSTANCE_GLOBAL];
  if (typeof existing === "string" && existing.length > 0) return existing;
  const minted = mintRuntimeInstanceId();
  try {
    Object.defineProperty(runtimeIdHost, RUNTIME_INSTANCE_GLOBAL, {
      value: minted,
      enumerable: false,
      configurable: true,
      writable: true,
    });
  } catch {
    // A frozen host cannot carry the anchor; the load-local value still works.
  }
  return minted;
}

let runtimeInstanceId: string = processRuntimeInstanceId();

/**
 * The runtime instance id of THIS process, stable across module re-evaluation.
 */
export function currentRuntimeInstanceId(): string {
  // Re-read through the process anchor so a test seam that rebinds the global
  // (or a reload that kept the anchor) is reflected here. If the anchor is
  // MISSING - a test cleared it, or the host could not define it - the module
  // re-establishes it from the load-local value, because the id is
  // PROCESS-owned: it must never silently become module-local again.
  const anchored = runtimeIdHost[RUNTIME_INSTANCE_GLOBAL];
  if (typeof anchored === "string" && anchored.length > 0) {
    runtimeInstanceId = anchored;
    return anchored;
  }
  try {
    Object.defineProperty(runtimeIdHost, RUNTIME_INSTANCE_GLOBAL, {
      value: runtimeInstanceId,
      enumerable: false,
      configurable: true,
      writable: true,
    });
  } catch {
    // A frozen host cannot carry the anchor; the load-local value still works.
  }
  return runtimeInstanceId;
}

/** Test seam: rebind the PROCESS instance id so cross-process behaviour is testable. */
export function setRuntimeInstanceIdForTests(value: string): void {
  runtimeInstanceId = value;
  try {
    Object.defineProperty(runtimeIdHost, RUNTIME_INSTANCE_GLOBAL, {
      value,
      enumerable: false,
      configurable: true,
      writable: true,
    });
  } catch {
    // best-effort only
  }
}

/** The in-memory provenance index, keyed by exact run id. */
export type ProvenanceIndex = Map<string, ProvenanceRecord>;

/**
 * Parse a persisted provenance entry back into a record, or null when it is not
 * one.
 *
 * Fail closed on ANY malformed shape: a wrong version, a missing run id, or a
 * non-string session uuid yields null rather than a partially-trusted record. A
 * record whose `requestEpoch` is absent is also null - provenance without an
 * epoch cannot be bound to the current request.
 */
export function parseProvenanceRecord(value: unknown): ProvenanceRecord | null {
  if (value === null || typeof value !== "object") return null;
  const entry = value as {
    version?: unknown;
    runId?: unknown;
    agent?: unknown;
    asyncDir?: unknown;
    sessionUuid?: unknown;
    requestEpoch?: unknown;
    terminal?: unknown;
    deliveryCapable?: unknown;
    lineage?: unknown;
  };
  // CORR12/NEW-1: version 2 is the current shape (adds `lineage`). Version 1 is
  // still parsed for backward compatibility and is treated as LEGACY: it has no
  // lineage, so it can never be admitted as current-lineage provenance.
  if (entry.version !== 1 && entry.version !== 2) return null;
  if (typeof entry.runId !== "string" || entry.runId.length === 0) return null;
  if (typeof entry.sessionUuid !== "string" || entry.sessionUuid.length === 0) return null;
  if (typeof entry.requestEpoch !== "number" || !Number.isSafeInteger(entry.requestEpoch)) return null;
  return {
    runId: entry.runId,
    agent: typeof entry.agent === "string" ? entry.agent : "",
    asyncDir: typeof entry.asyncDir === "string" && entry.asyncDir.length > 0 ? entry.asyncDir : null,
    sessionUuid: entry.sessionUuid,
    requestEpoch: entry.requestEpoch,
    // CORR12/NEW-1: a version-1 (legacy) record, or one with a malformed token,
    // parses with an EMPTY lineage. An empty lineage can never equal a live
    // registration's token, so a pre-upgrade or tampered record is
    // corroboration-incapable rather than silently trusted as current-lineage.
    lineage: entry.version === 2 && typeof entry.lineage === "string" ? entry.lineage : "",
    // F3: a record written before this field existed, or with a malformed one,
    // parses as an EMPTY instance id. That can never equal this process's id, so
    // a legacy or tampered record is corroboration-incapable rather than
    // silently trusted.
    runtimeInstanceId: typeof entry.runtimeInstanceId === "string" ? entry.runtimeInstanceId : "",
    // PG4/AC-F2-2: a record written before this field existed was never marked
    // terminal, so absent parses as NOT terminal - it must still be re-evaluated
    // against the live bridge rather than presumed dead. A record that WAS
    // marked terminal stays terminal across a reload, so the positive evidence
    // "this session watched the run finish" is not silently lost by restoring.
    terminal: entry.terminal === true,
    // R6-5: absent (pre-upgrade) parses as DELIVERY-CAPABLE, preserving the
    // behaviour of records written before this field existed; a record explicitly
    // marked incapable stays incapable across a reload, so the rejection holds.
    deliveryCapable: entry.deliveryCapable !== false,
  };
}

/**
 * Rebuild a provenance index from persisted session entries.
 *
 * Only entries carrying this extension's provenance `customType` are read, and
 * each is re-parsed fail-closed. A foreign `customType`, a malformed payload, or
 * a later duplicate for the same run id simply does not produce a record (the
 * later one wins when valid, so a re-witnessed run keeps its newest binding).
 */
export function restoreProvenance(entries: unknown[]): ProvenanceIndex {
  const index: ProvenanceIndex = new Map();
  for (const raw of entries) {
    if (raw === null || typeof raw !== "object") continue;
    const entry = raw as { type?: unknown; customType?: unknown; data?: unknown };
    if (entry.type !== "custom" || entry.customType !== PROVENANCE_CUSTOM_TYPE) continue;
    const record = parseProvenanceRecord(entry.data);
    if (record !== null) index.set(record.runId, record);
  }
  return index;
}

/**
 * R6-6/CORR12-NEW-1: the CURRENT registration lineage and its latest generation.
 *
 * `lineage` is the per-registration identity token that produced the current
 * request scope; `generation` is the highest request epoch persisted WITHIN that
 * lineage. Restoration admits a provenance record only when BOTH match.
 */
export interface CurrentLineageGeneration {
  lineage: string;
  generation: number;
}

/**
 * CORR13/NEW-1: the lineage identity reported for a PURE-LEGACY branch (every
 * marker lacks a `lineage` field - a branch written entirely before CORR12).
 *
 * This is NOT a live registration token and can never be minted by
 * `mintLineageToken()` (which always emits `ln-...`). It exists so the legacy
 * branch never reuses the empty string - the value a genuine legacy/pending
 * provenance record parses to - as an IDENTITY token. Reusing `""` made
 * `"" === ""` admit a SUPERSEDED registration's legacy record (whose numeric
 * epoch a restarted counter reuses) after a same-process reload, silently
 * accepting an escalation that should have been repaired (cycle-16 P1-legacy).
 *
 * Fail-closed consequence: on a legacy branch a legacy provenance record parses
 * with lineage `""`, which does NOT equal this sentinel, so NO legacy record is
 * ever admitted. That is deliberate - with no token and a restarted counter,
 * epoch equality cannot distinguish the current registration's record from a
 * superseded one, so the admissible set must be empty rather than unsound.
 */
export const LEGACY_NO_LINEAGE_SENTINEL = "legacy:no-lineage";

/**
 * CORR11/NEW-1 LEGACY fallback: the newest generation of a domain stream that
 * carries NO lineage identity at all (a branch written entirely before CORR12).
 *
 * With no lineage tokens, a DROP in the same-domain generation is the only
 * available signal of a counter RESTART - the first boundary of a new
 * registration's lineage. This scans the markers in stream order, opens a NEW
 * lineage whenever the generation drops, and returns the maximum of the LAST
 * lineage only. It preserves the exact CORR11 behaviour for pure-legacy
 * branches; every CORR12-aware branch instead uses the unambiguous lineage
 * token and never reaches this path.
 */
function legacyDropRestartGeneration(generations: number[]): number | null {
  let latest: number | null = null;
  let previous: number | null = null;
  for (const generation of generations) {
    if (previous !== null && generation < previous) {
      latest = generation;
      previous = generation;
      continue;
    }
    previous = generation;
    if (latest === null || generation > latest) latest = generation;
  }
  return latest;
}

/**
 * CORR12/NEW-1: select THIS process's CURRENT LINEAGE and its latest generation.
 *
 * The defect CORR11 could not close: the numeric epoch alone is ambiguous
 * because the counter is registration-local and RESTARTS, so a superseded
 * registration and a live one can share numerically equal epochs. Inferring a
 * lineage boundary from the VALUE stream (a drop) cannot distinguish a genuine
 * new-registration restart from a non-monotone write. CORR12 therefore makes
 * lineage EXPLICIT: each generation marker carries the per-registration token
 * that produced it.
 *
 * Selection is POSITIONAL, not numeric: the LAST domain-matched marker in the
 * branch names the current lineage (Pi appends entries in branch order, so the
 * most recent writer is the current registration), and the current generation is
 * the maximum epoch among markers carrying THAT token. A marker from a
 * SUPERSEDED registration carries a different token and is discarded entirely,
 * even when its numeric epoch equals or exceeds the current one.
 *
 * R3 is preserved by the domain filter: a marker from another process's counter
 * domain is skipped, exactly as before.
 *
 * LEGACY branches (every marker lacks a `lineage` field) have no token to select
 * on, so they fall back to the CORR11 drop-restart heuristic rather than losing
 * their previous-request invalidation. CORR13/NEW-1: such a branch reports the
 * explicit `LEGACY_NO_LINEAGE_SENTINEL` identity (NOT the empty string). The
 * caller therefore admits NO legacy record on this path - the sentinel can never
 * equal the `""` a genuine legacy record parses to - which is required because a
 * restarted counter makes a superseded legacy record numerically
 * indistinguishable from the current one (cycle-16 P1-legacy).
 */
export function currentLineageGeneration(entries: unknown[], domain: string): CurrentLineageGeneration | null {
  const markers: { lineage: string; generation: number }[] = [];
  for (const raw of entries) {
    if (raw === null || typeof raw !== "object") continue;
    const entry = raw as { type?: unknown; customType?: unknown; data?: unknown };
    if (entry.type !== "custom" || entry.customType !== REQUEST_GENERATION_CUSTOM_TYPE) continue;
    const data = entry.data as { version?: unknown; generation?: unknown; domain?: unknown; lineage?: unknown } | null;
    if (data === null || typeof data !== "object") continue;
    if (data.version !== 1) continue;
    // CORR10/NEW-1: a marker from a DIFFERENT counter domain says nothing about
    // this process's request boundaries.
    if (typeof data.domain !== "string" || data.domain !== domain) continue;
    if (typeof data.generation !== "number" || !Number.isSafeInteger(data.generation)) continue;
    markers.push({
      lineage: typeof data.lineage === "string" ? data.lineage : "",
      generation: data.generation,
    });
  }
  if (markers.length === 0) return null;
  // The LAST domain-matched marker names the current lineage.
  const lineage = markers[markers.length - 1].lineage;
  if (lineage === "") {
    // Pure-legacy branch: no token identity exists, so keep the CORR11 numeric
    // drop-restart selection. CORR13/NEW-1: report the EXPLICIT legacy sentinel
    // rather than `""`, so `""` is never used as an identity token and a
    // superseded legacy record (parsed lineage `""`) cannot compare equal.
    const generation = legacyDropRestartGeneration(markers.map((marker) => marker.generation));
    return generation === null ? null : { lineage: LEGACY_NO_LINEAGE_SENTINEL, generation };
  }
  // Token lineage: the maximum epoch among markers sharing the CURRENT token.
  // A superseded registration's token is never equal to it, so its markers
  // cannot contribute a maximum.
  let generation: number | null = null;
  for (const marker of markers) {
    if (marker.lineage !== lineage) continue;
    if (generation === null || marker.generation > generation) generation = marker.generation;
  }
  return generation === null ? null : { lineage, generation };
}

/**
 * R6-6: the LATEST persisted request generation FOR THIS PROCESS'S CURRENT
 * counter lineage, or null when none was recorded.
 *
 * Thin numeric view over `currentLineageGeneration`, retained for callers and
 * tests that need only the epoch. CORR12/NEW-1: lineage is now EXPLICIT (a
 * per-registration token on each marker), so selection is positional rather than
 * inferred from the value stream; see `currentLineageGeneration` for the full
 * rule. Legacy branches with no token fall back to the CORR11 drop-restart rule.
 */
export function latestPersistedGeneration(entries: unknown[], domain: string): number | null {
  return currentLineageGeneration(entries, domain)?.generation ?? null;
}

/**
 * R6-6/CORR12-NEW-1: is a persisted provenance record admissible for the request
 * NOW in progress?
 *
 * Extracted as a pure predicate so the restore gate and its tests share ONE
 * implementation. A record is admissible only when it belongs to the CURRENT
 * request: its epoch must equal the current lineage's latest generation, and -
 * when a `currentLineage` is supplied - its own lineage token must equal that
 * lineage. The lineage comparison is what CORR11 could not express: a record
 * from a SUPERSEDED registration must not be revived merely because its numeric
 * epoch equals the current one. An absent generation marker is fail-closed
 * (legacy/truncated evidence cannot claim a wake path).
 *
 * `currentLineage` is optional so pre-existing two-argument callers/tests keep
 * the numeric-only rule; production restoration ALWAYS supplies it. CORR13/NEW-1:
 * a pure-legacy branch supplies `LEGACY_NO_LINEAGE_SENTINEL`, NOT `""`, so a
 * legacy record (parsed lineage `""`) is never admitted even on that branch.
 */
export function provenanceBelongsToCurrentGeneration(
  record: { requestEpoch: number; lineage?: string },
  latestGeneration: number | null,
  currentLineage?: string,
): boolean {
  if (latestGeneration === null) return false;
  if (record.requestEpoch !== latestGeneration) return false;
  if (currentLineage !== undefined) {
    // CORR12/NEW-1: a version-2 record carries its registration token; a
    // version-1 legacy record (or one with a malformed token) parses as `""`.
    // CORR13/NEW-1: the only lineage that is never a live token is the explicit
    // `LEGACY_NO_LINEAGE_SENTINEL`, so an exact match is required and `""` can
    // never match it. This is what keeps a SUPERSEDED registration's legacy
    // record out after a same-process reload.
    const recordLineage = typeof record.lineage === "string" ? record.lineage : "";
    if (recordLineage !== currentLineage) return false;
  }
  return true;
}

/**
 * R6-5: the request generation is only a corroboration aid; see
 * `provenanceBelongsToCurrentGeneration` for the admissibility rule.
 *
 * The model-supplied half of `STATUS:WAIT subagent <run-id> <event>`.
 *
 * The event token states what the model EXPECTS to wake it. For a start form it
 * is terminal completion; for a form it labels as terminal it is the terminal
 * transition itself.
 */
export function waitEventIsTerminal(event: string): boolean {
  return /^(complete|completed|finished|done|stopped|terminal)\b/i.test(event.trim());
}

/** True when the WAIT event token is a start form the START event already met. */
export function waitEventIsStartForm(event: string): boolean {
  return START_FORM_EVENTS.has(event.trim().toLowerCase().split(/\s+/)[0] ?? "");
}

/**
 * The identity of the session a piece of wake proof must belong to.
 *
 * The REAL Pi context object does not carry `sessionFile`/`sessionId` directly:
 * `ExtensionRunner.createContext()` exposes session identity only through
 * `ctx.sessionManager.getSessionFile()` / `getSessionId()`. Reading the direct
 * fields alone therefore yields an EMPTY identity on a live host, which fails
 * provenance matching closed and rejects every genuine WAIT.
 *
 * The direct fields are kept as a fallback for minimal/fixture contexts, but
 * the manager is consulted first because that is what a real host provides.
 * An absent identity still returns "", and callers treat that as "matches
 * nothing" - never as a match.
 */
function sessionIdentity(ctx: SupervisorContext | undefined): string {
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
function sessionTranscriptPath(ctx: SupervisorContext | undefined): string {
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
function replyProvesWake(body: unknown, proof: WakeProof, identity: string): boolean {
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
function ownerStateIsActive(state: unknown): boolean {
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
function ownerStateIsTerminal(state: unknown): boolean {
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
  if (sawActiveTargeted) {
    // A reported-active run is accepted ONLY when no authoritative source
    // contradicts it; contradiction was handled above.
  } else {
    const hasExactTargetInspection =
      (targeted !== null && targeted.runId === runId) ||
      (payload.runId === runId && typeof payload.state === "string") ||
      (Array.isArray((details as { runs?: unknown } | null)?.runs) &&
        ((details as { runs: unknown[] }).runs).some((node) => {
          if (node === null || typeof node !== "object") return false;
          const run = node as { runId?: unknown; id?: unknown };
          const id = typeof run.runId === "string" ? run.runId : run.id;
          return id === runId;
        }));
    if (hasExactTargetInspection) return false;

    // PG3: NO targeted report for this run at all. The reply was produced by an
    // EXACT-TARGET verification (this extension always asks `{runId}`), so a
    // targeted body that fails to name the run is an uninformative answer, not
    // an invitation to consult the lagging display cache. Treating the cached
    // snapshot as proof here is precisely how a completed or finalized run
    // keeps earning silence after its targeted inspection stopped reporting it.
    // The cache is therefore NOT consulted: absence of an authoritative ACTIVE
    // report is never proof of liveness, so this fails closed.
    return false;
  }

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

/**
 * Extract the run id an observed-run ledger row is keyed by, for exact matching.
 *
 * `observedRuns` is keyed by the exact run id, so a WAIT whose id is only a
 * PREFIX must never match a longer observed run: the map lookup is exact by
 * construction, and this helper documents that invariant at the call site.
 */
function observedRunExists(observedRuns: Map<string, ObservedRun>, runId: string): boolean {
  return runId.length > 0 && observedRuns.has(runId);
}

/** Notification event shape this extension reads. */
interface SettleEventLike {
  type?: unknown;
  paneId?: unknown;
}

/** The fresh-request handshake phase; see `registerSessionSupervisor`. */
type RequestPhase = "none" | "submitted" | "starting" | "blocked";
/** The bridge draft appended to make a declared CONTINUE runnable. */
export function buildBridgeEntry(marker: DeclaredMarker): {
  type: "custom_message";
  customType: string;
  content: string;
  display: false;
} {
  const step = marker.payload.length > 0 ? marker.payload : "(the next step you named)";
  const content = [
    BRIDGE_HEADER,
    `You declared: STATUS:CONTINUE ${step}`,
    "Act on that step now.",
    "This message grants NO new authorization: the permissions, scope, and",
    "approvals that applied to your previous turn still apply unchanged.",
    "If the step is no longer actionable, reconcile it under the existing decision,",
    "user-contact, and continuation rules rather than stopping unconditionally.",
  ].join("\n");
  return {
    type: "custom_message",
    customType: BRIDGE_CUSTOM_TYPE,
    content,
    display: false,
  };
}

/**
 * The bridge draft appended to turn an UNSUPPORTED stop into decision repair.
 *
 * Used for an unstructured `BLOCKED`, an invalid user proof, and an explicit
 * human-waiting `CONTINUE`. Its whole purpose is to stop the model waiting for
 * a technical option selection it is not owed, while granting NO new
 * authorization and never implying the user owes a choice. `reason` names the
 * rejected claim for the transcript; it never changes the bridge's meaning.
 */
export function buildRepairEntry(reason: string): {
  type: "custom_message";
  customType: string;
  content: string;
  display: false;
} {
  const content = [
    REPAIR_HEADER,
    `Rejected claim: ${reason}`,
    "The attempted user escalation is unverified. Do not wait for a technical option selection. Proceed on a defensible ordinary authorized default, or request bounded Oracle Planning advice/user-input assessment as appropriate. Missing assessment evidence grants no authorization. Keep protected effects blocked and finish independent authorized work. Do not duplicate work whose verified wake owner already exists.",
  ].join("\n");
  return {
    type: "custom_message",
    customType: REPAIR_CUSTOM_TYPE,
    content,
    display: false,
  };
}

/**
 * Register handlers against a Pi API. Kept as a pure helper so tests can drive
 * it with fake contexts without importing Pi itself.
 */
export function registerSessionSupervisor(
  api: SupervisorApi,
  env: {
    ZELLIJ_PANE_ID?: string;
    PI_MAX_CONTINUATIONS?: string;
    /**
     * Timer injection point. Real hosts get `setTimeout`; tests pass a
     * synchronous scheduler so a deferred notice can be asserted without racing
     * the shared stdout capture.
     */
    schedule?: (run: () => void, ms: number) => unknown;
    cancel?: (handle: unknown) => void;
    /**
     * Filesystem reader injected for tests; production reads the real disk so
     * an observed async dir can be inspected without the test suite creating
     * fixtures on disk.
     */
    readFile?: ReadFile;
    /**
     * Path of the scheduled-task store (FEATURE 3). Defaults to the resolved Pi
     * agent dir's `session-supervisor/tasks.json`; tests inject a temp path so no
     * fixture touches the real store.
     */
    tasksPath?: string;
    /**
     * Injected clock, so a test can drive due-time arithmetic without real time.
     * Defaults to `Date.now`.
     */
    now?: () => number;
  } = process.env,
): void {
  let notified = false;
  const schedule = env.schedule ?? ((run, ms) => setTimeout(run, ms));
  const cancelScheduled = env.cancel ?? ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>));
  const readFile = env.readFile ?? defaultReadFile;
  const tasksPath = env.tasksPath ?? defaultTasksPath();
  const now = env.now ?? (() => Date.now());

  // Resolved ONCE per registration. Re-reading the environment later could let a
  // value change mid-session raise the allowance, which would defeat the ledger.
  const maxContinuations = resolveMaxContinuations(env.PI_MAX_CONTINUATIONS, (message) => {
    try {
      console.warn(`[session-supervisor] ${message}`);
    } catch {
      // best-effort only
    }
  });

  // Continuation is intent, not an allowance: only an explicit operator disable
  // (`PI_MAX_CONTINUATIONS=0`) prohibits it. Any positive value - including a
  // finite one, whose warn-once treatment lands in S3 - means continuation is
  // permitted, because a cumulative counter is exactly what made well-formed
  // CONTINUEs stop silently. The parse is retained so the S3 warn can key off it.
  const continuationDisabled = maxContinuations === 0;

  // --- Continuation policy -------------------------------------------------
  // Continuation is INTENT, not an allowance. A fresh, well-formed
  // `STATUS:CONTINUE` on a completed boundary of an enabled, compatible, live
  // host produces a runnable continuation with no cumulative counter anywhere.
  // Pi exposes no atomic acknowledgement of acceptance, so a count-based
  // allowance could only ever be an approximation that turns host quirks into
  // silent budget exhaustion; the guarantee is instead structural - there is no
  // allowance left to exhaust. Only `PI_MAX_CONTINUATIONS=0` disables
  // continuation outright; a positive value is parsed and warned about in S3.
  let phase: RequestPhase = "none";

  // --- Observed-run ledger -------------------------------------------------
  // A REQUEST-SCOPED record of async runs this extension personally witnessed
  // start, keyed by run id. It exists SOLELY to verify a `STATUS:BLOCKED user`
  // escalation: the referenced Oracle run must be in this ledger, bound to this
  // session, and belong to the CURRENT request epoch. Nothing the model emits
  // can replenish it - a marker or a repair bridge only ever READS it - and it
  // is cleared on input/session/tree replacement so a run from a previous
  // request cannot underwrite a new question. The ledger stores no result text
  // beyond what an inspected artifact yields on demand.
  let observedRuns = new Map<string, ObservedRun>();

  // --- Provenance index ----------------------------------------------------
  // The persistent half of the observed-run record: WITHOUT result text, and
  // WITHOUT any verification outcome, timer, or execution permit. It exists so
  // a SAME-SESSION reload can still re-evaluate a run it once witnessed against
  // the live bridge. Persisted through the host session store under
  // `PROVENANCE_CUSTOM_TYPE`; foreign session uuids and previous-request epochs
  // are rejected on every read, so provenance can never authorize a WAIT by
  // itself - only corroborate a CURRENT-owner reply.
  let provenance: ProvenanceIndex = new Map();

  // Run ids the live RPC bridge last attested as CURRENTLY active. Cleared with
  // the observation epoch so a run confirmed in a previous request can never be
  // treated as currently active in this one. This is a corroborating in-memory
  // cache, NEVER a persisted permit.
  let currentOwnerRuns = new Set<string>();

  // CORR12/NEW-1: the LINEAGE token for THIS registration. Minted fresh at
  // register time and stamped on every generation marker and provenance record
  // written from here. A native same-process `/reload` re-evaluates the module
  // with `moduleCache:false`, so this value does NOT survive it by itself; on a
  // continuing `reload`/`resume`, `handleSessionStart` RECOVERS the current
  // lineage from the persisted branch (the token on the LAST domain marker) and
  // rebinds this variable to it, which is exactly what keeps a same-request
  // reload working while a superseded registration stays excluded. A genuine
  // new process or non-continuing `startup` keeps its freshly-minted token and
  // therefore opens a distinct lineage.
  let lineageToken = mintLineageToken();

  // --- Scheduled tasks (FEATURE 3) ---------------------------------------
  //
  // `tasks` is the in-memory mirror of the persisted store; `taskTimers` holds
  // the one armed callback per task id. `registrationToken` is the TRANSIENT
  // fence: minted fresh per registration, captured by each armed callback, and
  // re-checked against this live value IMMEDIATELY before injection, so a timer
  // armed under a superseded registration can never deliver. It is deliberately
  // NOT persisted: it distinguishes live registrations, not turns, and a restart
  // legitimately restores the same session's tasks. `currentSessionId` tracks the
  // live session (updated by the lifecycle handlers) so a task whose owner is not
  // the active session is RETAINED rather than fired into the wrong session.
  let tasks = new Map<string, ScheduledTask>();
  const taskTimers = new Map<string, unknown>();
  // Tasks whose CANCELLATION the user requested but whose deletion has not yet
  // reached disk. Retained so a failed cancellation is RETRIED rather than
  // silently rolled back into "the task keeps firing" (Review 78 round 2, HIGH-2).
  const pendingCancels = new Set<string>();
  /**
   * Cancellation-retry timers, kept SEPARATE from `taskTimers`.
   *
   * FINAL REVIEW F2: sharing the firing map let a pump or arm overwrite the
   * cancellation retry, so a failed cancellation could be replaced by an ordinary
   * firing retry and never land. Cancellation retries live only here.
   */
  const cancelRetries = new Map<string, unknown>();
  // True between `session_before_compact` and the settle that follows the
  // matching terminal compaction event. The host exposes no compaction
  // predicate to extensions, so the EVENT PAIR is the only production-observable
  // signal (see `canAcceptNow`). R81-P1: it is cleared at the SEND-READY
  // boundary (`agent_settled`), NOT at `session_compact`/`session_compact_failed`,
  // because the host awaits those events while still refusing a send.
  let compacting = false;
  // Armed by `session_compact` / `session_compact_failed` and consumed by the
  // next `agent_settled`. It makes a terminal compaction event SAFE against the
  // "no settle follows" case: a settle is only allowed to close the window once
  // compaction has actually ended, while the window stays OPEN across the awaited
  // terminal emit itself. Guarded (see `session_before_compact`) so a second
  // concurrent compaction cannot arm a close on the still-open first window.
  let compactionClosable = false;
  let registrationToken = mintRegistrationToken();
  let currentSessionId = "";
  // The persisted session transcript path for the CURRENT session, captured from
  // the session context. The confirmation read needs it because the commit point
  // is the PERSISTED transcript, not an event. In production this comes from
  // `ctx.sessionManager.getSessionFile()`; a minimal/fixture context supplies the
  // direct `ctx.sessionFile` fallback. Empty means "no transcript to read", in
  // which case confirmation can never happen and the occurrence stays armed.
  let currentSessionFile = "";
  // The task whose injected turn is still in flight, if any. One handoff guard:
  // a second firing for the same (or any) task is deferred until the resulting
  // turn settles, so an injected turn is never overlapped.
  let taskHandoff: string | null = null;
  /**
   * Bounded confirmation polls, kept SEPARATE from `taskTimers`.
   *
   * Oracle OPTION D: after a send is ATTEMPTED, the occurrence is confirmed only
   * when its envelope is seen in the persisted transcript. Until then `taskHandoff`
   * holds the scheduler's single in-flight slot, so the poll MUST be able to
   * release it on exhaustion without colliding with a firing/cancel retry keyed by
   * the same task id. A dedicated map guarantees that (the same reasoning as
   * `cancelRetries`).
   */
  const confirmTimers = new Map<string, unknown>();

  /**
   * Deliver a due task's prompt as a user message in this session.
   *
   * `deliverAs: "followUp"` handles the STREAMING case: the host queues a send
   * that carries a delivery mode (`agent-session.js:1552-1559`) instead of
   * rejecting it.
   *
   * It does NOT handle COMPACTION. The host rejects a send during compaction
   * BEFORE it ever inspects the delivery mode (`agent-session.js:1534-1535`),
   * and that rejection is ASYNCHRONOUS - the runtime merely reports the error
   * (`:2712-2718`) and the scheduler receives no acknowledgement. A fire-and-
   * forget send therefore LOSES the occurrence, which the duplicate guard has
   * already committed as consumed (Review 78 round 2, HIGH-1).
   *
   * So delivery is conditional on the host being able to ACCEPT it. The caller
   * checks `canAcceptNow()` first and retains the occurrence when it cannot.
   */
  /**
   * Attempt delivery. Returns `true` only when the send was ACCEPTED.
   *
   * A `try/catch` cannot see the host's real refusal: `sendUserMessage` is an
   * `async` wrapper that returns `void` (`extensions/types.d.ts:1243-1246`) and
   * the host CATCHES its own rejection internally (`agent-session.js:2711-2718`,
   * `runner.emitError`). A synchronous throw only happens for a few early
   * guard failures. So a `void` return means ATTEMPTED, never ACCEPTED.
   *
   * Oracle OPTION D inversion: this function only SENDS. It never advances or
   * removes the durable cursor and never treats its own return as proof of
   * delivery. The caller persists the pending occurrence record BEFORE calling
   * here and commits only after the transcript confirms the envelope.
   */
  const injectTask = (task: ScheduledTask): boolean => {
    if (typeof api.sendUserMessage !== "function") return false;
    if (!canAcceptNow()) return false;
    try {
      api.sendUserMessage(taskFiringPrompt(task), { deliverAs: "followUp" });
      return true;
    } catch {
      // A synchronous throw is a refusal we CAN observe; treat it as not sent.
      return false;
    }
  };

  /** Whether the persisted transcript currently proves this occurrence landed. */
  const confirmedInTranscript = (task: ScheduledTask): boolean => {
    if (task.occurrenceId === undefined) return false;
    if (currentSessionFile.length === 0) return false;
    return transcriptConfirmsDelivery(
      readTranscriptTail(currentSessionFile),
      taskOccurrenceEnvelope(task.id, task.occurrenceId),
    );
  };

  /** Clear one task's armed confirmation poll, if any. */
  const clearConfirmTimer = (id: string) => {
    const handle = confirmTimers.get(id);
    if (handle === undefined) return;
    confirmTimers.delete(id);
    try {
      cancelScheduled(handle);
    } catch {
      // best-effort only
    }
  };

  /**
   * Whether the host can currently ACCEPT an injected user message.
   *
   * Oracle OPTION D: this is NO LONGER the commit gate. Correctness cannot rest
   * on predicting whether the host will accept a send, because a refusal is
   * swallowed (`agent-session.js:2711-2718`) and the prediction can be wrong when
   * a later async handler suspends the compact emit across timer turns. The gate
   * is now the PERSISTED TRANSCRIPT (`confirmedInTranscript`); this predicate is
   * retained only to DEFER a pointless attempt while compaction is observably in
   * flight, which avoids burning a confirmation window on a send the host will
   * drop. It is kept (rather than removed) because the compaction-event tests
   * assert that no send is even ATTEMPTED while the window is open.
   *
   * Pi THROWS on a send while compacting, before it inspects the delivery mode
   * (`agent-session.js:1534-1535`), and the host swallows that rejection
   * internally (`:2711-2718` emits an error and discards it). The public
   * `api.sendUserMessage` therefore returns `void` (`extensions/types.d.ts:1243-
   * 1246`), so NO acknowledgement of a refusal is available to the caller.
   *
   * Neither `api.isCompacting()` nor `api.isIdle()` can help. `isCompacting` is
   * a getter on `AgentSession` (`:1204`) and is NOT exposed to extensions; and
   * `isIdle()` is supplied on the EVENT CONTEXT (`extensions/runner.js:654-656`),
   * not on `api`. Incidentally `isIdle` would also be the wrong predicate: it is
   * false during streaming too (`:1053-1054`), where a `followUp` send is
   * perfectly acceptable.
   *
   * The correct signal is the compaction EVENT PAIR, which the host does expose
   * (`extensions/types.d.ts:587-610`): `session_before_compact` fires before
   * compaction and `session_compact` / `session_compact_failed` fire when it ends
   * or fails. Tracking that pair gives a real, production-observable answer, so
   * this defer is keyed on it rather than on a surface that does not exist.
   */
  const canAcceptNow = (): boolean => !compacting;

  /**
   * Atomically replace the persisted store, reporting whether it SUCCEEDED.
   *
   * The write is a temp file plus a same-directory `rename`, so a crash during
   * the temp write never truncates the existing store. `rename` alone is not a
   * power-loss barrier; this is crash-atomic, not fsync-durable, which is the
   * documented bound (see the design's storage section).
   *
   * The RESULT MATTERS: the duplicate guard and durable cancellation both rely on
   * this write having landed. A swallowed failure would let a restart replay an
   * already-consumed occurrence or revive a cancellation, so callers must not
   * proceed as if persistence succeeded.
   */
  const persistTasks = (): boolean => {
    try {
      mkdirSync(dirname(tasksPath), { recursive: true });
      const tmp = `${tasksPath}.${process.pid}.tmp`;
      // MERGE-BEFORE-WRITE (final review F3): several Pi processes may own this
      // store, and a whole-file replace from this process's map silently deletes
      // another process's tasks. Re-read the file, keep records this process does
      // not own, and let only this process's OWNED records win. This narrows the
      // lost-update window to a concurrent write between the read and the rename;
      // it does not make the store a transaction, because there is no lock.
      //
      // CURRENT-ON-DISK-WINS FOR FOREIGN RECORDS (g2 blocker 2): the previous rule
      // imported a foreign record only when its id was ABSENT from local memory,
      // then re-serialized the whole map. That resurrects a foreign task another
      // process CANCELLED (its id is still cached locally) and discards a foreign
      // UPDATE (the stale cached copy is re-written). For every record this
      // process does NOT own, the CURRENT on-disk copy is authoritative: an
      // on-disk foreign record REPLACES the local copy, and a foreign id cached
      // locally but ABSENT from disk is DELETED rather than re-written. Records
      // this process owns are untouched and still win. This fixes the SEQUENTIAL
      // two-owner case; the no-lock concurrent window remains the documented bound.
      //
      // AUTHORITATIVE-SNAPSHOT GATE (g3 blocker 1): a `null` read is NOT proof
      // that the store is EMPTY. `readFile` is the artifact reader, whose 2 MiB
      // cap (see `defaultReadFile`) makes a large-but-writable task store read as
      // `null`; a throw/corruption does the same. The previous code conflated
      // "unreadable" with "empty", so a successful rename then PRUNED every
      // cached foreign record and replaced the file with the pruned map - silently
      // DELETING another owner's tasks. A first write (no file yet) is genuinely
      // empty and may proceed. An existing store must be read with a store
      // reader that is NOT artifact-capped before any foreign record is pruned or
      // the store is replaced; only a confirmed absent store or a successful,
      // authoritative snapshot justifies a write that drops records.
      //
      // g4 B1 completion: the gate above was still INCOMPLETE on two SEQUENTIAL
      // paths, both of which replaced a store nobody had actually read:
      //   (1) BOTH readers fail (`readFile` refuses it and the uncapped
      //       `readFileSync` throws). `authoritative` stayed false, but the temp
      //       serialization and rename below still ran unconditionally, replacing
      //       an existing unreadable store from a stale in-memory map.
      //   (2) The store reads non-null but does NOT parse to `{tasks: [...]}`.
      //       The old `parseTaskStore` returned `[]` for malformed JSON, so a
      //       PARSE FAILURE looked like an authoritative EMPTY foreign snapshot,
      //       enabling pruning AND replacement.
      // Both paths now `return false` BEFORE reconciliation, pruning, temp
      // serialization, or rename. Existence itself is established with `statSync`
      // so an access/stat error is NOT mistaken for a confirmed absence.
      let storeExists: boolean;
      try {
        statSync(tasksPath);
        storeExists = true;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") {
          // Confirmed absent: nothing to merge, first write proceeds.
          storeExists = false;
        } else {
          // Existence could not be established (e.g. EACCES on the parent
          // directory). Fail closed rather than treating it as a first write,
          // which would clobber whatever the store actually holds.
          return false;
        }
      }
      let authoritative = false;
      let foreign: ScheduledTask[] = [];
      if (!storeExists) {
        authoritative = true;
      } else {
        let raw: string | null = null;
        try {
          raw = readFile(tasksPath);
        } catch {
          raw = null;
        }
        if (raw === null) {
          // The store exists but the (artifact-capped) reader refused it. Read
          // the store itself, which is not an artifact and has no such cap, so a
          // legitimate >2 MiB store still yields an authoritative snapshot.
          try {
            raw = readFileSync(tasksPath, "utf8");
          } catch {
            raw = null;
          }
        }
        if (raw === null) {
          // An existing store neither reader could read is NOT an authoritative
          // empty snapshot. Refuse the write so the on-disk bytes survive.
          return false;
        }
        const snapshot = parseTaskStoreStrict(raw);
        if (snapshot === null) {
          // The text parsed (or did not) but is NOT a `{tasks: [...]}` store.
          // A malformed store must never look like an authoritative empty one.
          return false;
        }
        foreign = snapshot;
        authoritative = true;
      }
      const onDiskForeignIds = new Set<string>();
      for (const other of foreign) {
        // An on-disk record owned by THIS process, or an on-disk id this process
        // owns in memory, is not foreign: this process's owned copy wins.
        if (other.sessionId === currentSessionId) continue;
        const local = tasks.get(other.id);
        if (local !== undefined && local.sessionId === currentSessionId) continue;
        tasks.set(other.id, other);
        onDiskForeignIds.add(other.id);
      }
      if (authoritative) {
        // A foreign id this process cached but that is ABSENT from disk reflects a
        // landed foreign change (typically a cancellation); do NOT re-serialize
        // it. Without an authoritative snapshot this prune is UNSOUND (absence is
        // unobserved, not established), so it is SKIPPED - an unreadable store
        // must never delete a cached foreign record.
        for (const [id, local] of [...tasks.entries()]) {
          if (local.sessionId === currentSessionId) continue;
          if (onDiskForeignIds.has(id)) continue;
          tasks.delete(id);
        }
      }
      if (!authoritative) {
        // No authoritative snapshot was established (only reachable if a future
        // edit reintroduces a non-returning path): do not replace the store.
        return false;
      }
      writeFileSync(tmp, serializeTaskStore([...tasks.values()]));
      renameSync(tmp, tasksPath);
      return true;
    } catch {
      return false;
    }
  };

  /** Clear one task's armed timer, if any. */
  const clearTaskTimer = (id: string) => {
    const handle = taskTimers.get(id);
    if (handle === undefined) return;
    taskTimers.delete(id);
    try {
      cancelScheduled(handle);
    } catch {
      // best-effort only
    }
  };

  /**
   * Longest delay `setTimeout` can represent.
   *
   * A delay above 2^31-1 ms does not merely saturate: Node emits
   * `TimeoutOverflowWarning` and clamps the timer to **1 ms**, so a task booked
   * ~25+ days out would fire almost immediately. Measured: requesting
   * 2592000000 ms (30 days) yields `_idleTimeout === 1`. A one-shot then
   * consumes its occurrence durably and deletes itself, executing at the wrong
   * time with no notification (delivery succeeds; only the timing is wrong).
   *
   * The clamp is therefore paired with the due-time re-check in `pumpTask`: a
   * horizon longer than this re-arms in bounded hops instead of firing early.
   * 2^31-1 ms is ≈ 24.855 days.
   */
  const MAX_TIMER_DELAY_MS = 2147483647;

  /** Arm one task's callback against the CURRENT registration fence. */
  const armTask = (task: ScheduledTask) => {
    // FINAL REVIEW F2 CORRECTION: the earlier NOTE here claimed a task with an
    // outstanding cancellation could never reach this point. THE FINAL REVIEW
    // DISPROVED THAT and the claim was never established - failed deletion
    // RESTORES the task into `tasks` (see `cancelTaskNow`), so it is present and
    // armable while `persistTasks()` keeps failing. A cancellation intent
    // therefore outranks ownership and due time here.
    if (pendingCancels.has(task.id)) return;
    clearTaskTimer(task.id);
    const token = registrationToken;
    // Clamp: an unclamped horizon > 2^31-1 ms is silently CLAMPED BY NODE TO 1 MS,
    // which would fire the task immediately. Re-arming at the cap makes a long
    // horizon a sequence of bounded waits rather than an early fire.
    const delay = Math.min(MAX_TIMER_DELAY_MS, Math.max(0, task.nextRunAtMs - now()));
    const handle = schedule(() => pumpTask(task.id, token), delay);
    taskTimers.set(task.id, handle);
  };

  /** Arm every task owned by the CURRENT session, and nothing else. */
  const armCurrentSessionTasks = () => {
    for (const task of tasks.values()) {
      if (pendingCancels.has(task.id)) continue; // F2: cancellation intent outranks ownership
      if (task.sessionId === currentSessionId) armTask(task);
      else clearTaskTimer(task.id);
    }
  };

  /**
   * Fire one due task, if it is still eligible.
   *
   * The transient fence is re-checked here, IMMEDIATELY before injection: a
   * callback armed under a superseded registration is dropped before it can
   * deliver. Ownership is re-checked too - a task whose session is not the
   * active one is RETAINED for its exact session to resume, never delivered into
   * a different one and never run through a hidden runner. A busy handoff defers
   * with a bounded retry rather than overlapping turns.
   *
   * Oracle OPTION D: this pump only ARMS and ATTEMPTS. It persists the pending
   * occurrence record BEFORE sending (so the record is the outbox), then confirms
   * by reading the PERSISTED transcript on a bounded timer. It never advances or
   * removes the durable cursor on the strength of a `void` send.
   */
  const pumpTask = (id: string, token: string) => {
    if (token !== registrationToken) return;
    const task = tasks.get(id);
    if (task === undefined) return;
    // FINAL REVIEW F2: a pending cancellation outranks a due time. Without this a
    // settlement that pumped a due task could deliver it AFTER the user cancelled,
    // which is the "cancelled then revived" defect.
    if (pendingCancels.has(id)) return;
    if (task.sessionId !== currentSessionId) return; // retained until its session resumes
    // DUE-TIME RE-CHECK: a timer armed at the 2^31-1 ms cap wakes before the task
    // is actually due (the cap is ≈ 24.855 days, so a multi-year horizon needs
    // many hops). Without this gate the capped wake would deliver EARLY. Re-arm
    // for the remaining time instead of proceeding.
    if (task.nextRunAtMs > now()) {
      armTask(task);
      return;
    }
    if (taskHandoff !== null) {
      // One occurrence per task, one handoff: defer past the in-flight turn.
      clearTaskTimer(id);
      const handle = schedule(() => pumpTask(id, token), TASK_BUSY_RETRY_MS);
      taskTimers.set(id, handle);
      return;
    }
    if (typeof api.sendUserMessage !== "function") {
      // No delivery surface: retain the task unarmed rather than dropping it.
      clearTaskTimer(id);
      return;
    }
    if (!canAcceptNow()) {
      // Host cannot accept a send right now (compaction). DEFER the attempt - this
      // avoids burning a confirmation window on a send the host will drop - and
      // retry. Correctness no longer depends on this predicate: a wrong prediction
      // now costs a delayed attempt, never a lost occurrence.
      clearTaskTimer(id);
      const handle = schedule(() => pumpTask(id, token), TASK_BUSY_RETRY_MS);
      taskTimers.set(id, handle);
      return;
    }

    // STEP 3 (persist the pending record and establish the handoff BEFORE the
    // send). Mint the occurrence id and, for an interval, the cursor to commit on
    // confirmation. `nextRunAtMs` is deliberately LEFT ALONE: it is the durable
    // re-derivation key, so a restart re-attempts the SAME overdue occurrence.
    //
    // If the store cannot be written the occurrence must NOT be attempted: the
    // pending record would not have landed, so a restart could not re-attempt it
    // and the at-least-once guarantee would be broken. Retain the task and retry.
    if (task.occurrenceId === undefined) {
      task.occurrenceId = mintOccurrenceId();
      if (task.intervalMs !== undefined) {
        task.pendingAdvanceTo = advanceDuePast(task.intervalMs, task.nextRunAtMs, now());
      }
      if (!persistTasks()) {
        // Undo the in-memory arming; nothing has been sent.
        delete task.occurrenceId;
        delete task.pendingAdvanceTo;
        clearTaskTimer(id);
        const handle = schedule(() => pumpTask(id, token), TASK_BUSY_RETRY_MS);
        taskTimers.set(id, handle);
        return;
      }
    } else if (task.pendingAdvanceTo === undefined && task.intervalMs !== undefined) {
      // A record restored from disk may carry an armed id but not the target
      // cursor (e.g. an older store). Re-derive and persist it so confirmation
      // has a cursor to commit.
      task.pendingAdvanceTo = advanceDuePast(task.intervalMs, task.nextRunAtMs, now());
      if (!persistTasks()) {
        delete task.pendingAdvanceTo;
        clearTaskTimer(id);
        const handle = schedule(() => pumpTask(id, token), TASK_BUSY_RETRY_MS);
        taskTimers.set(id, handle);
        return;
      }
    }

    // STEP 3 (cont.): establish the handoff, then ATTEMPT the send. A `void`
    // return means ATTEMPTED, never ACCEPTED.
    clearTaskTimer(id);
    taskHandoff = id;
    if (!injectTask(task)) {
      // The send could not even be attempted (a synchronous throw or an absent
      // surface). Release the handoff so later tasks are not suppressed, and
      // retry the SAME occurrence later - the pending record stays armed.
      taskHandoff = null;
      const handle = schedule(() => pumpTask(id, token), TASK_BUSY_RETRY_MS);
      taskTimers.set(id, handle);
      return;
    }

    // STEP 4: confirm from the PERSISTED TRANSCRIPT, never from the send. Check
    // once immediately (a host that persisted before returning confirms at once),
    // then poll on a bounded timer. The occurrence id is captured here so the
    // poll can only ever commit THIS occurrence.
    const occurrenceId = task.occurrenceId;
    if (confirmedInTranscript(task)) {
      commitOccurrence(id, token, occurrenceId);
      return;
    }
    scheduleConfirmation(id, token, occurrenceId);
  };

  /**
   * Commit a CONFIRMED occurrence durably (STEP 5).
   *
   * By the time this runs the transcript has been seen to contain the exact
   * envelope for `task.occurrenceId` in a `role: "user"` row, which is the only
   * positive-correlation proof of delivery available. An interval advances to the
   * cursor computed at ARM TIME (`pendingAdvanceTo`) and gets a FRESH occurrence
   * id; a one-shot is removed. The handoff is always released, so a later task is
   * never stalled behind a confirmed one.
   *
   * CONFIRMATION IS INDEPENDENT OF THE HANDOFF: a settle legitimately releases the
   * handoff while a confirmation poll is still pending, and the poll must still be
   * able to commit the occurrence it was armed for. The commit therefore keys on
   * `task.occurrenceId === occurrenceId` (the SAME occurrence still armed), not on
   * the handoff slot. If the task has since advanced to a different occurrence,
   * this commit is stale and is a safe no-op.
   *
   * On a persist failure the in-memory state is rolled back and retried, using
   * the same idiom as the rest of this scheduler: a commit that did not reach
   * disk must not be treated as having landed.
   */
  const commitOccurrence = (id: string, token: string, occurrenceId: string | undefined) => {
    const task = tasks.get(id);
    if (task === undefined) {
      if (taskHandoff === id) taskHandoff = null;
      clearConfirmTimer(id);
      return;
    }
    if (occurrenceId === undefined || task.occurrenceId !== occurrenceId) {
      // The occurrence this poll was armed for is no longer the armed one (a
      // later occurrence replaced it): this is a stale poll, not a commit.
      clearConfirmTimer(id);
      return;
    }
    clearConfirmTimer(id);
    // Capture the pre-commit state so a failed persist can be undone exactly.
    const previousDue = task.nextRunAtMs;
    const previousOccurrence = task.occurrenceId;
    const previousAdvance = task.pendingAdvanceTo;
    if (task.intervalMs !== undefined) {
      // Advance to the cursor computed at ARM time, NOT `now()`: a long stall must
      // not skip occurrences beyond the designed coalescing rule.
      task.nextRunAtMs = task.pendingAdvanceTo ?? advanceDuePast(task.intervalMs, task.nextRunAtMs, now());
      delete task.pendingAdvanceTo;
      task.occurrenceId = mintOccurrenceId();
    } else {
      tasks.delete(id);
    }
    if (!persistTasks()) {
      // Roll back the durable-commit attempt and retry it.
      if (task.intervalMs !== undefined) {
        task.nextRunAtMs = previousDue;
        if (previousOccurrence !== undefined) task.occurrenceId = previousOccurrence;
        else delete task.occurrenceId;
        if (previousAdvance !== undefined) task.pendingAdvanceTo = previousAdvance;
        else delete task.pendingAdvanceTo;
      } else {
        tasks.set(id, task);
      }
      if (taskHandoff === id) taskHandoff = null;
      const handle = schedule(() => pumpTask(id, token), TASK_BUSY_RETRY_MS);
      taskTimers.set(id, handle);
      return;
    }
    if (taskHandoff === id) taskHandoff = null;
    if (task.intervalMs !== undefined) armTask(task);
  };

  /**
   * Poll the persisted transcript for the armed occurrence (STEP 4, bounded).
   *
   * The host appends to the transcript AFTER it emits `message_start`/`
   * message_end` (`agent-session.js:748-763`), so no event handler or microtask
   * proves persistence; only a later read does. Poll up to
   * `TASK_CONFIRM_MAX_ATTEMPTS` times at `TASK_CONFIRM_RETRY_MS`. On exhaustion the
   * handoff is RELEASED (so later tasks are not stalled - Review 78 HIGH-1) and a
   * retry pump re-ATTEMPTS the SAME occurrence id (at-least-once).
   */
  const scheduleConfirmation = (
    id: string,
    token: string,
    occurrenceId: string | undefined,
    attempt = 1,
  ) => {
    clearConfirmTimer(id);
    const handle = schedule(() => {
      if (token !== registrationToken) return;
      const task = tasks.get(id);
      // A task that has advanced to a different occurrence (or vanished) makes
      // this poll stale; committing is a no-op guarded inside `commitOccurrence`.
      if (task !== undefined && confirmedInTranscript(task)) {
        commitOccurrence(id, token, occurrenceId);
        return;
      }
      if (task === undefined || task.occurrenceId !== occurrenceId) return;
      if (attempt >= TASK_CONFIRM_MAX_ATTEMPTS) {
        // Bounded exhaustion: release the handoff and re-attempt the occurrence
        // later with the SAME id. The pending record is persisted, so a restart
        // would re-attempt it too.
        if (taskHandoff === id) taskHandoff = null;
        clearTaskTimer(id);
        const retry = schedule(() => pumpTask(id, token), TASK_BUSY_RETRY_MS);
        taskTimers.set(id, retry);
        return;
      }
      scheduleConfirmation(id, token, occurrenceId, attempt + 1);
    }, TASK_CONFIRM_RETRY_MS);
    confirmTimers.set(id, handle);
  };

  /** Register one validated `TASK:ADD`, owned by the current session. */
  const addTask = (body: string) => {
    const parsed = parseTaskAdd(body);
    if (parsed === null || currentSessionId.length === 0) return;
    // UNCONFIRMABLE-PROMPT REJECTION (g2 blocker 1): delivery is confirmed ONLY by
    // positively correlating the persisted transcript row, and the confirmation
    // read sees just the last `TRANSCRIPT_TAIL_BYTES` of the transcript. A prompt
    // whose serialized row could begin before that window can NEVER be confirmed,
    // so the occurrence would re-send forever. REJECT it here - before it is
    // accepted, persisted, or armed - with a visible notice naming the id and the
    // limit. The bound is a conservative WORST CASE (see `worstCaseTaskRowBytes`),
    // so this only ever refuses a prompt that could plausibly exceed the window.
    const worstCaseBytes = worstCaseTaskRowBytes(parsed.id, parsed.prompt);
    if (worstCaseBytes > TRANSCRIPT_TAIL_BYTES) {
      notifyTaskRejection(
        `prompt too large to confirm delivery ` +
          `(worst-case ${worstCaseBytes} bytes exceeds the ${TRANSCRIPT_TAIL_BYTES}-byte confirmation tail)`,
        parsed.id,
      );
      return;
    }
    // CROSS-SESSION ID COLLISION (final review F3): ids are model-chosen, so a
    // second session can pick an id this store already holds for ANOTHER session.
    // Silently overwriting would delete that session's task. Refuse instead; the
    // instruction to re-issue under a free id is a notice, not a silent mutation.
    const existing = tasks.get(parsed.id);
    if (existing !== undefined && existing.sessionId !== currentSessionId) {
      notifyTaskRejection("id is already owned by another session", parsed.id);
      return;
    }
    // HIGH-1 (final Review): REPLACING a same-session task under the same id must
    // retire the superseded occurrence's confirmation poll AND handoff. `armTask`
    // below clears only the FIRING timer, so without this the old poll survives,
    // then hits the stale return in `scheduleConfirmation` (the replacement has no
    // `occurrenceId` yet) and returns WITHOUT releasing `taskHandoff`. Every later
    // pump of this id would then defer forever at the handoff gate, permanently
    // stalling the replacement and every task queued behind it.
    //
    // The superseded occurrence's delivery is deliberately NOT committed and NOT
    // re-attempted: the operator replaced it, so the old prompt is withdrawn. This
    // only retires the lifecycle state that would otherwise leak.
    if (existing !== undefined) {
      clearConfirmTimer(parsed.id);
      if (taskHandoff === parsed.id) taskHandoff = null;
      clearTaskTimer(parsed.id);
    }
    const task: ScheduledTask = {
      id: parsed.id,
      sessionId: currentSessionId,
      prompt: parsed.prompt,
      nextRunAtMs: now() + parsed.delayMs,
    };
    if (parsed.intervalMs !== undefined) task.intervalMs = parsed.intervalMs;
    tasks.set(task.id, task);
    // BOUNDED RE-REVIEW F3: the persist result is deliberately NOT treated as a
    // success gate here. An unsaved ADD is recoverable - the FIRING path re-checks
    // `persistTasks()` before consuming an occurrence, so a task that never
    // reached disk simply cannot be delivered as a committed occurrence. Refusing
    // the ADD outright would also break the tested contract that a task created
    // while the store is unwritable still exists in memory and is retried (see
    // `TASK:CANCEL is retried until it lands`, which creates its subject under an
    // unwritable store). What must never happen is a SILENT overwrite of another
    // session's record, which the collision check above prevents.
    persistTasks();
    armTask(task);
  };

  /**
   * Cancel one task by id, idempotently.
   *
   * Only the CURRENT session's own record may be cancelled; deleting an unknown
   * or foreign id is a no-op, never an error. Cancelling never aborts a turn
   * that has already started - it only clears the future firing.
   *
   * DURABILITY (Review 78 round 2, HIGH-2): a cancellation that does not reach
   * disk must be RETRIED, not merely rolled back. Rolling back alone left the
   * task armed and firing later, which is "the task keeps running", not "the
   * cancellation failed". So on a failed write the deletion is undone, the timer
   * is re-armed, and a retry is scheduled until the deletion lands (or the task
   * is gone). `pendingCancels` records the intent so the retry survives an
   * unrelated re-arm.
   */
  const cancelTask = (id: string) => {
    if (id.length === 0) return;
    const task = tasks.get(id);
    if (task === undefined || task.sessionId !== currentSessionId) return;
    pendingCancels.add(id);
    cancelTaskNow(id);
  };

  /**
   * Attempt the durable deletion for `id`; retry while the write keeps failing.
   *
   * FINAL REVIEW F2: the retry handle must NOT live in `taskTimers`, because that
   * map is shared with ordinary firing timers. `armTask` and `pumpTask` both call
   * `clearTaskTimer(id)` then set their own handle under the same key, so a
   * settlement that pumped this task could REPLACE the cancellation retry with an
   * ordinary firing retry and the cancellation would be silently forgotten. The
   * retry is therefore kept in a dedicated `cancelRetries` map keyed by id, and
   * `pendingCancels` - the durable INTENT - is consulted by `armTask`,
   * `armCurrentSessionTasks` and the pump path so no other code can resurrect or
   * fire a task whose cancellation has not yet landed.
   */
  /**
   * Drop a pending cancellation retry AND cancel its handle.
   *
   * BOUNDED RE-REVIEW F2: every path that removed a `cancelRetries` entry was
   * deleting the MAP ENTRY ONLY, leaving the scheduled callback alive. A stale
   * callback then ran later against a REUSED id and deleted the replacement
   * task: (1) persist `x`, fail the delete, arm retry R; (2) make the store
   * writable and cancel `x` successfully - R disappears from the map but stays
   * scheduled; (3) add a NEW task with id `x`; (4) R fires and deletes it. The
   * registration-token check does not help, because the token is still current.
   * Untracked handles could also outlive shutdown.
   */
  const dropCancelRetry = (id: string) => {
    const handle = cancelRetries.get(id);
    if (handle !== undefined) {
      try {
        cancelScheduled(handle);
      } catch {
        // best-effort only
      }
      cancelRetries.delete(id);
    }
  };

  const cancelTaskNow = (id: string) => {
    const task = tasks.get(id);
    if (task === undefined) {
      pendingCancels.delete(id);
      dropCancelRetry(id);
      // Oracle OPTION D: a cancelled task must not keep the scheduler's single
      // handoff slot pinned by a poll for it.
      clearConfirmTimer(id);
      if (taskHandoff === id) taskHandoff = null;
      return;
    }
    tasks.delete(id);
    clearTaskTimer(id);
    if (persistTasks()) {
      pendingCancels.delete(id);
      dropCancelRetry(id);
      // Oracle OPTION D (STEP 7): a cancellation releases the handoff too, so a
      // task cancelled mid-confirmation cannot stall later tasks.
      clearConfirmTimer(id);
      if (taskHandoff === id) taskHandoff = null;
      return;
    }
    tasks.set(id, task); // undo: the deletion did not land on disk
    clearTaskTimer(id);
    const token = registrationToken;
    // Re-arm nothing for FIRING; only the cancellation is retried. Keying this in
    // `cancelRetries` keeps it out of reach of the firing machinery. The previous
    // handle (if any) is cancelled first, so a repeated cancellation attempt
    // cannot leave an untracked timer behind.
    dropCancelRetry(id);
    const handle = schedule(() => {
      if (token !== registrationToken) return;
      cancelTaskNow(id);
    }, TASK_BUSY_RETRY_MS);
    cancelRetries.set(id, handle);
  };

  /** Consume every `TASK:` action line from a boundary's final message. */
  const consumeTaskActions = (boundary: AgentBeforeSettleLike) => {
    const text = messageText(finalProjectedMessage(boundary));
    if (text.length === 0) return;
    // A parser failure here must degrade to the SAFE default - consume NO
    // actions - rather than throwing out of the settlement handler. This mirrors
    // the guarded marker read below, and CORR51 R3 pins that a parser fault at
    // the boundary notifies instead of escaping. Structure is derived inside the
    // guard so the ownership check cannot itself become the throw site.
    let actions: TaskAction[];
    try {
      actions = parseTaskActions(text, lineStructure(text));
    } catch {
      return;
    }
    for (const action of actions) {
      if (action.verb === "add") addTask(action.body);
      else cancelTask(action.body);
    }
  };

  /** Load the persisted store and arm the current session's tasks. */
  const restoreTasks = () => {
    for (const handle of taskTimers.values()) {
      try {
        cancelScheduled(handle);
      } catch {
        // best-effort only
      }
    }
    taskTimers.clear();
    // FINAL REVIEW F2: a cancellation whose write never landed is STILL INTENT.
    // A reload must not silently forget it and re-arm the task from the store,
    // which is the "reload restores a cancelled task" defect. Retries are
    // cancelled and rebuilt; the intent set survives, and `armTask` honors it.
    for (const handle of cancelRetries.values()) {
      try {
        cancelScheduled(handle);
      } catch {
        // best-effort only
      }
    }
    cancelRetries.clear();
    // Oracle OPTION D: pending confirmation polls hold the handoff slot, so a
    // reload must cancel them too (a task restored from disk is re-armed below).
    for (const handle of confirmTimers.values()) {
      try {
        cancelScheduled(handle);
      } catch {
        // best-effort only
      }
    }
    confirmTimers.clear();
    // A reload opens a new registration scope: any prior in-flight handoff is
    // void, and `handleSessionStart` already nulls it. Assert it here too so the
    // two entry points cannot diverge.
    taskHandoff = null;
    let text: string | null = null;
    try {
      text = readFileSync(tasksPath, "utf8");
    } catch {
      text = null;
    }
    tasks = new Map();
    if (text !== null) {
      for (const task of parseTaskStore(text)) tasks.set(task.id, task);
    }
    // A task whose cancellation is still pending must be deleted again rather
    // than resumed; `cancelTaskNow` retries the write and clears the intent only
    // once it lands.
    for (const id of [...pendingCancels]) {
      if (tasks.has(id)) cancelTaskNow(id);
      else pendingCancels.delete(id);
    }
    armCurrentSessionTasks();
  };

  /**
   * Track the live session for the scheduler.
   *
   * When the active session changes, tasks owned by the NEW session are armed and
   * tasks owned by any other session are disarmed but RETAINED, so a task fires
   * when its exact owning session becomes active again - never into a different
   * session.
   */
  const noteSession = (ctx: SupervisorContext) => {
    const identity = sessionIdentity(ctx);
    if (identity.length === 0) return;
    if (identity === currentSessionId) return;
    currentSessionId = identity;
    // Oracle OPTION D: keep the confirmation transcript bound to the live
    // session, so a task pumped for THIS session is confirmed against THIS
    // session's transcript.
    currentSessionFile = sessionTranscriptPath(ctx);
    armCurrentSessionTasks();
  };

  /**
   * Persist one provenance record, best-effort.
   *
   * Absent `appendEntry` is not an error: provenance is CORROBORATION, so a host
   * that cannot persist it simply restores nothing on reload, which can only
   * make a later WAIT unverified. Nothing here persists liveness or a permit.
   */
  const persistProvenance = (record: ProvenanceRecord) => {
    if (typeof api.appendEntry !== "function") return;
    try {
      api.appendEntry(PROVENANCE_CUSTOM_TYPE, { version: 2, ...record });
      // R6-6: also record the request generation alongside the record, so the
      // durable marker is never absent when a record exists. Without this a
      // record written in a session that had not yet crossed a boundary would
      // have no generation marker to compare against, and the gate would have to
      // fall back to admitting it - reopening R6-6 for exactly that record.
      // CORR10/NEW-1: the marker is stamped with the counter DOMAIN that produced
      // it, so a later process's restoration never reads a foreign counter as its
      // own latest generation.
      // CORR12/NEW-1: the marker carries the registration LINEAGE token, so
      // restoration can bind the record to the registration that wrote it.
      api.appendEntry(REQUEST_GENERATION_CUSTOM_TYPE, { version: 1, generation: record.requestEpoch, domain: currentRuntimeInstanceId(), lineage: record.lineage });
    } catch {
      // best-effort only: an unwritable store loses corroboration, not safety.
    }
  };

  // The request epoch is a LOCAL MONOTONIC COUNTER, not a value derived from a
  // session path: `status.json.sessionId` is a file path while `ctx.sessionId`
  // is a bare UUID, so deriving an epoch from either would make the two compare
  // unequal. The counter increments on every ledger clear, which IS the request
  // boundary, and each observed run records the counter value current when it
  // was witnessed. A run stamped with an older epoch can never underwrite a
  // question in the current one.
  let observationEpoch = 0;

  /**
   * Persist the CURRENT request generation so a reload can tell which request
   * was in progress. Best-effort, like provenance: an unwritable store simply
   * restores nothing, which can only make a later WAIT unverified.
   */
  const persistRequestGeneration = (generation: number) => {
    if (typeof api.appendEntry !== "function") return;
    try {
      // CORR10/NEW-1: the domain records WHICH counter domain this generation
      // belongs to, so restoration only compares generations from a compatible
      // domain (see `latestPersistedGeneration`).
      // CORR12/NEW-1: the lineage records WHICH registration wrote the marker,
      // so a superseded registration's numerically equal epoch is excluded.
      api.appendEntry(REQUEST_GENERATION_CUSTOM_TYPE, { version: 1, generation, domain: currentRuntimeInstanceId(), lineage: lineageToken });
    } catch {
      // best-effort only
    }
  };
  /** Wipe the observed-run ledger and open a new request epoch. */
  const clearObservedRuns = () => {
    observedRuns = new Map();
    provenance = new Map();
    currentOwnerRuns = new Set();
    observationEpoch += 1;
    // R6-6: record the new generation durably, so a reload during THIS request
    // knows the request in progress and does not mistake an older request's
    // provenance for the current one.
    persistRequestGeneration(observationEpoch);
  };

  /**
   * R6-5/R7-1: can a witnessed async START produce an INDEPENDENT completion
   * wake to THIS parent?
   *
   * The real `subagent:async-started` payload (`types.d.ts:1604-1638`, emitted
   * at `runs/background/async-execution.js:1409,1986` and
   * `runs/foreground/subagent-executor.js:5148`) carries `completionOwnerId`
   * and, conditionally, `parentWorkflowRunId`.
   *
   * TWO shapes fail to deliver an independent wake:
   *
   *  1. A workflow-AWAITED async child publishes its result to a WORKFLOW-OWNED
   *     path (`async-execution.js:1865-1867`) and its completion carries
   *     `triggerTurn: false` + `awaitedByWorkflow: true`
   *     (`subagent-executor.js:2914-2935`), which the notifier explicitly SKIPS
   *     (`notify.js:725-728`).
   *
   *  2. R7-1: a workflow ROOT. This was the missed case. A workflow root emits
   *     `mode: "workflow"`, `agent: "workflow"`
   *     (`subagent-executor.js:5148-5160`) with NEITHER `parentWorkflowRunId` NOR
   *     `scheduleOrigin`. A QUIET SCHEDULED root has the IDENTICAL START shape,
   *     but `scheduledCompletionTriggersTurn` (`notify.js:226-227`) forces
   *     `triggerTurn: false` for a quiet schedule's successful completion, so no
   *     turn is ever requested. Keying only on `parentWorkflowRunId` therefore
   *     let a wake-incapable root earn SILENT verified waiting.
   *
   * HONEST LIMIT (fail-closed, deliberately OVER-REJECTING): NO emitted
   * workflow-root START field distinguishes a quiet scheduled root from an
   * ordinary one - the quiet flag lives in LAUNCH params
   * (`scheduled-runs.js:481-489`) and is never echoed on the START event. This
   * extension therefore CANNOT positively establish delivery for a workflow
   * root, so it fails CLOSED: every `mode: "workflow"` root is treated as
   * delivery-UNPROVEN and can never corroborate a WAIT.
   *
   * This deliberately over-rejects ORDINARY workflow roots that could in fact
   * wake. That is a KNOWN, DISCLOSED cost, chosen because the failure mode is
   * asymmetric: a false rejection only makes a WAIT unverified (the agent
   * announces instead of sitting silently), whereas a false acceptance lets the
   * agent wait forever on a wake that will never arrive - exactly the false
   * WAIT the user reported. This does NOT claim workflow roots are incapable of
   * waking; it records that their wake path is UNPROVEN at START. Lifting the
   * over-rejection requires positive exact-run delivery evidence (the real wake
   * policy and delivery owner), which completion-time evidence is too late to
   * provide for a PRIOR indefinite silence.
   *
   * Also accounted for as non-waking paths: recovery priming uses
   * `triggerTurn: false` explicitly, and successful incremental child notices
   * can be non-waking while their workflow remains running. (`parent-wake.js`'s
   * context-only notice is NOT a gap - it accompanies a real `sendUserMessage`
   * wake.) Note none of these can be distinguished FROM the START payload
   * either, which is why the conservative rule below is the safe one.
   */
  const deliveryCapableFromStart = (event: Record<string, unknown>): boolean => {
    const parentWorkflowRunId =
      typeof event.parentWorkflowRunId === "string" && event.parentWorkflowRunId.length > 0
        ? event.parentWorkflowRunId
        : "";
    // A child that names a parent workflow publishes to the workflow's path.
    if (parentWorkflowRunId.length > 0) return false;
    // R7-1: a workflow ROOT has no `parentWorkflowRunId` to key on, so it is
    // identified by its own mode. Its wake path is unproven (a quiet scheduled
    // root is indistinguishable here and never triggers a turn).
    if (event.mode === "workflow") return false;
    return true;
  };

  /**
   * Record one observed async START.
   *
   * Only events that name a run id AND an agent are recorded; everything else
   * (a malformed payload, a missing id) is ignored rather than guessed at. The
   * run's epoch is stamped with the ledger's current counter, which is the only
   * epoch this extension can honestly attribute the observation to.
   */
  const observeStart = (payload: unknown, source: "event" | "request" = "event") => {
    if (payload === null || typeof payload !== "object") return;
    const event = payload as Record<string, unknown>;
    const runId =
      typeof event.runId === "string" && event.runId.length > 0
        ? event.runId
        : typeof event.id === "string" && event.id.length > 0
          ? event.id
          : typeof event.childRunId === "string" && event.childRunId.length > 0
            ? event.childRunId
            : "";
    const agent = typeof event.agent === "string" ? event.agent : "";
    if (runId.length === 0 || agent.length === 0) return;

    const session =
      typeof event.sessionFile === "string" && event.sessionFile.length > 0
        ? event.sessionFile
        : typeof event.sessionId === "string"
          ? event.sessionId
          : ledgerSession;

    const prior = observedRuns.get(runId);
    const asyncDir =
      typeof event.asyncDir === "string" && event.asyncDir.length > 0 ? event.asyncDir : prior?.asyncDir ?? null;
    // R6-3: `terminal` is a TOMBSTONE taken from the LEDGER *or* the restored
    // PROVENANCE. A replayed/duplicate START after a reload finds an empty
    // ledger but populated provenance, so reading only the ledger would let it
    // clear a terminal marking that had already been established.
    const restoredPrior = provenance.get(runId);
    const alreadyTerminal = (prior?.terminal ?? false) || (restoredPrior?.terminal ?? false);
    // R6-5: delivery capability is decided ONCE, at START, from the real payload.
    // A run whose wake path cannot be established stays delivery-incapable even
    // if a later duplicate START omits the marker, so this is sticky-OR: it can
    // only ever go true->true, never true->false. Deliberately NOT defaulted to
    // `true` for an unknown prior: the fail-closed direction is `false`.
    const deliveryCapable = prior?.deliveryCapable ?? true;
    observedRuns.set(runId, {
      runId,
      agent,
      asyncDir,
      session,
      sessionUuid: sessionUuid(session),
      requestEpoch: observationEpoch,
      terminal: alreadyTerminal,
      deliveryCapable: deliveryCapable && deliveryCapableFromStart(event),
    });

    // Persist PROVENANCE for a witnessed START so a same-session reload can still
    // re-evaluate this run. Only provenance is written - never liveness, a timer,
    // or a permit. A run witnessed without a resolvable session uuid persists
    // nothing, because unbound provenance could never be accepted on reload.
    const uuid = sessionUuid(session);
    if (uuid.length > 0) {
      const record: ProvenanceRecord = {
        runId,
        agent,
        asyncDir,
        sessionUuid: uuid,
        requestEpoch: observationEpoch,
        // CORR12/NEW-1: stamp the witnessing registration's LINEAGE token, so
        // restoration can bind this record to the registration that wrote it
        // rather than to a numerically equal epoch in a superseded scope.
        lineage: lineageToken,
        // PG5: write through the process anchor so a reload persists the SAME id
        // it will later check against.
        runtimeInstanceId: currentRuntimeInstanceId(),
        terminal: alreadyTerminal,
        deliveryCapable: (restoredPrior?.deliveryCapable ?? true) && deliveryCapableFromStart(event),
      };
      provenance.set(runId, record);
      persistProvenance(record);
    }
  };

  /**
   * Apply a `subagent.child-status` event to the observed-run ledger.
   *
   * PG4 - ONLY A GENUINELY TERMINAL STATUS RETIRES PROVENANCE. The topic carries
   * LIFECYCLE transitions, not just endings: the real tracker emits `"started"`,
   * `"stopping"`, and `"stopped"` (`async-job-tracker.js:278-295`). The previous
   * implementation treated every event on this topic as terminal, so a newly
   * STARTED chain step retired an otherwise live ROOT run's provenance. Fresh
   * live RPC evidence then failed `ownedHere` and a legitimate WAIT was rejected.
   *
   * `"stopping"` is also NOT terminal: the run is still winding down and its
   * completion has not been delivered, so it must keep its provenance until the
   * terminal transition actually arrives.
   *
   * Identity: a child event names BOTH the aggregate `runId` and the specific
   * `childRunId`. The CHILD id is preferred when present, so one child's end
   * cannot retire aggregate ownership while siblings are still active. The
   * aggregate id is used only when no child id is supplied.
   *
   * Never CREATES a run: an event for a run this extension did not witness start
   * is not evidence and must not enter the ledger.
   */
  const observeTerminal = (payload: unknown) => {
    if (payload === null || typeof payload !== "object") return;
    const event = payload as Record<string, unknown>;
    // PG4: only the terminal transition retires provenance. Any other lifecycle
    // status on this topic (started / stopping / unknown) is IGNORED rather than
    // treated as an ending.
    if (event.status !== "stopped") return;

    const aggregateRunId = typeof event.runId === "string" && event.runId.length > 0 ? event.runId : "";
    const childRunId = typeof event.childRunId === "string" && event.childRunId.length > 0 ? event.childRunId : "";
    const childId = typeof event.childId === "string" && event.childId.length > 0 ? event.childId : "";

    // R6-4: an event that names a CHILD identity which is NOT the aggregate root
    // does not establish ROOT termination. A real runner emits `childId: "step:N"`
    // (or a `workflowKey`) and spreads `childRunId` only CONDITIONALLY
    // (`runs/background/subagent-runner.js:1950-1963`), emitting stopped child
    // events for individual steps (`:2006`) while siblings stay active. Falling
    // back to the aggregate id on a missing `childRunId` would retire a LIVE
    // root. So: a child-scoped event retires only the CHILD's own entry; the
    // aggregate root is retired only by an event that is genuinely about it.
    const childScoped =
      childRunId.length > 0
        ? childRunId
        : childId.length > 0 && childId !== aggregateRunId
          ? childId
          : "";
    const runId = childScoped.length > 0 ? childScoped : aggregateRunId;
    if (runId.length === 0) return;

    // R6-3: do NOT require an `observedRuns` row. After a reload the ledger is
    // empty while PROVENANCE is restored, so bailing here would silently discard
    // every terminal observation that arrives post-reload. The provenance record
    // is the authority for whether this run was witnessed by this session.
    const record = provenance.get(runId);
    const prior = observedRuns.get(runId);
    if (record === undefined && prior === undefined) return;

    // Mark the ledger tombstone when the run is known to it.
    if (prior !== undefined) {
      observedRuns.set(runId, {
        ...prior,
        terminal: true,
        asyncDir: typeof event.asyncDir === "string" && event.asyncDir.length > 0 ? event.asyncDir : prior.asyncDir,
      });
    }
    // AC-F2-2: a terminal run must never corroborate a WAIT again. Mark the
    // record TERMINAL rather than deleting it, so the rejection is grounded in
    // POSITIVE evidence ("we watched it finish") instead of the weaker "unknown
    // run" that a deletion would leave behind. The persisted record is updated
    // too, so the same conclusion survives a reload.
    if (record !== undefined) {
      const retired: ProvenanceRecord = { ...record, terminal: true };
      provenance.set(runId, retired);
      persistProvenance(retired);
    }

    // R6-2: terminal evidence must REVOKE an already-verified WAIT, not merely
    // annotate the ledger. A verified WAIT has a live recheck whose test is RPC
    // liveness only; without this the run could stop, the bridge could still
    // report an active owner, and silent waiting would persist on evidence this
    // extension has just contradicted. `retireVerifiedWaitFor` retires the cached
    // owner and cancels the recheck when it names this run.
    retireVerifiedWaitFor(runId);
  };

  /** The active parent session path, for events that carry no identity. */
  let ledgerSession = "";

  /**
   * Register the two SETTLED observation topics ONCE per registration.
   *
   * A missing `on`, an unsupported topic, or a throwing subscriber leaves the
   * ledger empty, which can only make an escalation unverified. Nothing here
   * launches, resumes, or cancels a run.
   */
  const observeRunEvents = () => {
    const bus = api.events;
    if (bus === undefined || typeof bus.on !== "function") return;
    for (const topic of [OBSERVED_RUN_START_TOPIC, OBSERVED_RUN_TERMINAL_TOPIC]) {
      try {
        bus.on(topic, (event: unknown) => {
          if (topic === OBSERVED_RUN_START_TOPIC) observeStart(event);
          else observeTerminal(event);
        });
      } catch {
        // A bus that refuses a subscription simply cannot attest anything.
      }
    }
  };

  /** True only when the host reports an idle agent; unknown means not idle. */
  const isIdle = (ctx: SupervisorContext): boolean => {
    try {
      return ctx?.isIdle?.() === true;
    } catch {
      return false;
    }
  };

  /**
   * Revoke any pending handshake.
   *
   * Disarming (rather than replenishing) is the fail-closed default for every
   * ambiguous transition: reload/resume/fork, tree navigation, steering or
   * follow-up input, and overlapping submissions all land here.
   */
  const disarm = () => {
    phase = "none";
  };

  /**
   * Emit the OSC notification, then flag the pane when a pane id is known.
   *
   * `why` selects the distinct transport so an unattended run reports the right
   * cause: an unverified WAIT is a claim that did not hold, an unverified
   * escalation attempted a user contact that failed, malformed markers receive a
   * static protocol hint, and other stops retain the generic notice. There is no
   * budget-exhaustion transport: continuation is intent, not an allowance, so no
   * stop can be attributed to a spent counter.
   *
   * `problem` narrows only the `attention` case. The verification causes keep
   * precedence, and the notice text is a STATIC constant chosen by key - never
   * the message or payload - so no model-authored bytes reach the OSC escape
   * sequence.
   */
  const notify = (
    event: unknown,
    why: "attention" | "unverified-wait" | "unverified-escalation" = "attention",
    problem?: DeclaredMarker["problem"],
  ) => {
    if (notified) return;
    notified = true;

    try {
      process.stdout.write(
        why === "attention" && problem !== undefined
          ? `\x1b]777;notify;Pi;${MARKER_PROBLEM_NOTICE[problem]}\x07`
          : why === "unverified-wait"
            ? OSC_NOTIFY_UNVERIFIED_WAIT
            : why === "unverified-escalation"
              ? OSC_NOTIFY_UNVERIFIED_ESCALATION
              : OSC_NOTIFY,
      );
    } catch {
      // best-effort only
    }

    const paneId = extractPaneId(event, env);
    if (paneId.length === 0) return;
    const exec = api.exec;
    if (typeof exec !== "function") return;
    try {
      void Promise.resolve(
        exec("zellij", ["pipe", "--name", `zellij-attention::waiting::${paneId}`]),
      ).catch(() => {
        // best-effort only
      });
    } catch {
      // best-effort only
    }
  };

  /**
   * Report a REJECTED scheduled task as a visible, self-describing notice.
   *
   * g3 blocker 2: the refusals used to call `notify(OSC_NOTIFY, "<diagnostic>")`,
   * which passed the diagnostic as the `why` ENUM argument, so the text was
   * discarded and only the generic notice - suppressible by the `notified` dedupe
   * - could be observed. This emits the diagnostic on its OWN notice, BEFORE the
   * dedupe is consulted, so the refusal, id and limit are ALWAYS observable, and
   * then marks the epoch notified so no second generic notice follows. The id is
   * sanitized by `taskRejectionNotice`; `reason` is caller-owned static text.
   */
  const notifyTaskRejection = (reason: string, taskId: string) => {
    try {
      process.stdout.write(taskRejectionNotice(reason, taskId));
    } catch {
      // best-effort only: a closed stdout must not swallow the rejection
    }
    notified = true;
  };

  // --- WAIT verification ---------------------------------------------------
  // A completed WAIT defers notification through one bounded window. Silence is
  // granted only by CURRENT-OWNER proof; every other outcome notifies exactly
  // once. The window is NONBLOCKING - `agent_settled` must return promptly so
  // Pi's own deferred wake actions are not delayed by our check.
  //
  // Two timers exist and they are distinct:
  //   waitTimer    - the short bounded verification window above.
  //   recheckTimer - a SINGLE observational recheck of an already-verified
  //                  owner, which re-fires the unverified notice if the owner
  //                  has since died. Never a verification of its own.
  let waitEpoch = 0;
  let waitTimer: unknown = null;
  // CORR10/NEW-2: the deferred re-ask armed when the peer bridge answers
  // `no_active_session` (not yet initialised). Tracked here so every lifecycle
  // path can cancel it alongside the other WAIT artifacts.
  let waitRetryTimer: unknown = null;
  let recheckTimer: unknown = null;
  // The exact run a VERIFIED WAIT is currently trusting, so a recheck can ask
  // about the same run. Cleared whenever the wait is superseded.
  let recheckRunId: string | null = null;
  // R6-2: the settle event of the WAIT currently being trusted. A terminal
  // observation arriving AFTER verification must be able to end silent waiting,
  // which means it needs the same `event` the recheck would notify with.
  let recheckEvent: unknown = null;
  let rpcRequestSeq = 0;
  // C4: a PER-VERIFICATION generation. `waitEpoch` alone is advanced only by
  // input/navigation/replacement/shutdown, so starting WAIT B does NOT
  // invalidate WAIT A's in-flight callback: A's late reply would still satisfy
  // the shared `waitEpoch` guard, cancel the timer now belonging to B, and
  // leave B silent forever. This token is advanced at the START of every
  // verification so a callback from a superseded verification is a no-op.
  let waitGeneration = 0;
  // C5: the live RPC cancellation handles. Cancelling an unanswered request's
  // TIMER is not enough - the listener is only freed by these handles, so
  // lifecycle cleanup must be able to reach them.
  let waitRequestCancel: (() => void) | null = null;
  let recheckRequestCancel: (() => void) | null = null;
  // F5: the recheck's SHORT expiry window. It is created inside the recheck
  // timer's callback, so it was previously reachable only through that local
  // closure - lifecycle cleanup could cancel the recheck timer itself while this
  // one stayed pending until its deadline. Publishing it here makes it
  // cancellable from `clearWaitArtifacts()` on EVERY exit path.
  let recheckExpiryTimer: unknown = null;

  /**
   * Drop every in-flight WAIT artifact, including RPC listeners.
   *
   * C5: the previous implementation only nulled the TIMERS. An unanswered
   * request's listener lives behind the handle returned by `askSubagentOwner`, 
   * which was reachable exclusively from inside the expiry closure, so input,
   * replacement, navigation, and shutdown all cancelled the timer while leaving
   * the listener subscribed - one leaked listener per superseded WAIT, which 
   * accumulates over exactly the multi-day operation this extension supports.
   * Both handles are invoked here on EVERY exit path.
   */
  const clearWaitArtifacts = () => {
    if (waitRequestCancel !== null) {
      const cancel = waitRequestCancel;
      waitRequestCancel = null;
      try {
        cancel();
      } catch {
        // best-effort only
      }
    }
    if (recheckRequestCancel !== null) {
      const cancel = recheckRequestCancel;
      recheckRequestCancel = null;
      try {
        cancel();
      } catch {
        // best-effort only
      }
    }
    if (waitTimer !== null) {
      try {
        cancelScheduled(waitTimer);
      } catch {
        // best-effort only
      }
      waitTimer = null;
    }
    // CORR10/NEW-2: a pending bridge-readiness retry is a WAIT artifact too; it
    // must not survive an input/replacement/navigation/shutdown boundary.
    if (waitRetryTimer !== null) {
      try {
        cancelScheduled(waitRetryTimer);
      } catch {
        // best-effort only
      }
      waitRetryTimer = null;
    }
    if (recheckTimer !== null) {
      try {
        cancelScheduled(recheckTimer);
      } catch {
        // best-effort only
      }
      recheckTimer = null;
    }
    // F5: the recheck's inner expiry window is cancelled here too. Without this,
    // input/replacement/navigation/shutdown during an unanswered recheck left it
    // pending until its deadline even though its RPC listener was freed.
    if (recheckExpiryTimer !== null) {
      try {
        cancelScheduled(recheckExpiryTimer);
      } catch {
        // best-effort only
      }
      recheckExpiryTimer = null;
    }
  };

  /** Cancel any in-flight WAIT verification or recheck without notifying. */
  const cancelWaitVerification = () => {
    // Advance BOTH tokens: `waitEpoch` invalidates work across an input /
    // replacement / navigation / shutdown boundary, and `waitGeneration`
    // invalidates a superseded VERIFICATION even when the epoch is unchanged.
    waitEpoch += 1;
    waitGeneration += 1;
    recheckRunId = null;
    recheckEvent = null;
    // R8-3: cancellation must ALSO retire cached owner evidence. Timers and RPC
    // listeners are torn down here, but `currentOwnerRuns` was left intact, so a
    // run that a completed verification had cached as live stayed "usable" for
    // `verifiedWakeOwnerExists()` even after activity boundaries - suppressing
    // decision repair on an ownership that was never re-checked. Dropping the
    // cache forces the next WAIT/escalation to re-prove liveness from the bridge.
    currentOwnerRuns = new Set<string>();
    clearWaitArtifacts();
  };

  /**
   * R6-2: retire a VERIFIED WAIT when its awaited run is observed terminal.
   *
   * A verified WAIT is trusted, and its recheck asks only whether the bridge
   * still reports a live owner. Terminal evidence therefore used to be invisible
   * to it: the run could stop, the bridge could still answer active, and silent
   * waiting would persist on evidence this extension had already contradicted.
   *
   * This retires the trust: it cancels the recheck artifacts, drops the cached
   * owner, and emits the UNVERIFIED notice so silent waiting actually ends. It is
   * a no-op for any other run, so a terminal event about a sibling cannot disturb
   * a different run's valid WAIT.
   *
   * Advancing `waitGeneration` is what makes the cancellation stick: the recheck
   * in flight was bound to the previous generation and becomes a no-op.
   */
  const retireVerifiedWaitFor = (runId: string) => {
    if (recheckRunId !== runId) return;
    const event = recheckEvent;
    // Drop the cached owner BEFORE notifying, so `verifiedWakeOwnerExists()`
    // cannot keep suppressing decision repair on the strength of a run we have
    // just watched stop.
    rememberCurrentOwner(runId, false);
    recheckRunId = null;
    recheckEvent = null;
    // Invalidate any in-flight verification/recheck bound to this trust.
    waitGeneration += 1;
    clearWaitArtifacts();
    if (event !== undefined) notify(event, "unverified-wait");
  };

  /**
   * Ask a PROVIDER owner whether it still owns pending work.
   *
   * Providers attest through a narrow documented synchronous request pair; only
   * the named owner's channel is consulted. A missing bus, a throwing
   * subscriber, or a reply that never arrives all resolve to null (unverified),
   * never to an assumption of wake ownership.
   */
  const askProviderOwner = (proof: WakeProof & { kind: "provider" }, ctx: SupervisorContext): unknown => {
    const bus = api.events;
    if (bus === undefined || typeof bus.request !== "function") return null;
    try {
      return bus.request(`session-supervisor:wake-proof:v1:${proof.owner}`, {
        version: 1,
        id: proof.id,
        owner: proof.owner,
        session: sessionIdentity(ctx),
      });
    } catch {
      // A throwing subscriber is exactly the unsupported case.
      return null;
    }
  };

  /**
   * Query the pi-subagents RPC bridge for CURRENT owner state of one run.
   *
   * This uses the plugin's real correlated transport: a versioned request is
   * EMITTED on `subagents:rpc:v1:request` and the answer arrives on the
   * per-request reply topic `subagents:rpc:v1:reply:<requestId>`. The reply is
   * delivered ASYNCHRONOUSLY, so the caller passes a callback and the settle
   * boundary is never blocked. The subscription is removed as soon as the first
   * correlated reply arrives (or the request throws), so no listener leaks.
   *
   * DISPOSAL: the REAL Pi event bus returns a disposer FUNCTION from `on()` and
   * exposes NEITHER `off` nor `removeListener`. Ignoring the returned disposer
   * therefore leaks one listener per request for the life of the process - a
   * real problem for the multi-day operation this extension exists to support.
   * The disposer is captured and invoked; the older method lookups remain only
   * as a defensive fallback for buses that do not return one.
   *
   * The caller also receives a `cancel` handle so an UNSWERED request can free
   * its listener at expiry instead of retaining it forever.
   *
   * A bus without `emit`/`on`, a request that throws, or a reply that never
   * arrives all resolve to "unverified" through the ordinary window expiry.
   * Nothing here launches, resumes, or cancels a run.
   */
  const askSubagentOwner = (
    runId: string,
    onReply: (reply: unknown, request: unknown) => void,
  ): (() => void) => {
    const bus = api.events;
    if (bus === undefined || typeof bus.emit !== "function" || typeof bus.on !== "function") {
      onReply(null, null);
      return () => {};
    }
    const requestId = `session-supervisor-${++rpcRequestSeq}`;
    const request = { version: SUBAGENT_RPC_VERSION, requestId, method: "status", params: { runId } };
    const replyTopic = `${SUBAGENT_RPC_REPLY_PREFIX}${requestId}`;
    let settled = false;
    // The disposer the REAL bus hands back. Captured so disposal never depends
    // on methods the host does not implement.
    let returnedDisposer: unknown = null;
    const unsubscribe = () => {
      try {
        if (typeof returnedDisposer === "function") {
          (returnedDisposer as () => void)();
          returnedDisposer = null;
          return;
        }
        if (typeof bus.off === "function") bus.off(replyTopic, listener);
        else if (typeof bus.removeListener === "function") bus.removeListener(replyTopic, listener);
      } catch {
        // best-effort only
      }
    };
    const listener = (reply: unknown) => {
      if (settled) return;
      settled = true;
      unsubscribe();
      onReply(reply, request);
    };
    try {
      returnedDisposer = bus.on(replyTopic, listener);
      bus.emit(SUBAGENT_RPC_REQUEST_TOPIC, request);
    } catch {
      if (!settled) {
        settled = true;
        unsubscribe();
        onReply(null, request);
      }
    }
    // An unanswered request must be able to free its listener at expiry.
    return () => {
      if (settled) return;
      settled = true;
      unsubscribe();
    };
  };

  /**
   * Decide whether a completed WAIT has proven its wake path.
   *
   * Defer at most one window; expire into the unverified notice. The epoch guard
   * makes a stale reply a no-op after new input, session replacement, or
   * shutdown, so a resumed session is never silenced by an old check.
   *
   * PROOF STANDARD: a subagent WAIT survives ONLY on fresh correlated
   * current-owner evidence from the live RPC bridge. An observed START is NOT
   * proof (it attests PAST existence, not CURRENT liveness), a cached ledger row
   * is NOT proof, and an old "verified" flag does not exist. Absent, malformed,
   * terminal, foreign, or unreachable evidence all fall through to the notice.
   */
  const verifyWait = (event: unknown, ctx: SupervisorContext, proof: WakeProof | null, provenance: ProvenanceIndex) => {
    const epoch = waitEpoch;
    // C4: capture THIS verification's generation and advance it immediately, so
    // starting this verification invalidates every callback belonging to the
    // previous one even when `waitEpoch` is unchanged (a second WAIT with no
    // intervening input/navigation). A late reply from the superseded
    // verification therefore fails BOTH guards below and cannot cancel this
    // verification's timer nor arm a recheck on its behalf.
    waitGeneration += 1;
    const generation = waitGeneration;
    const stillCurrent = () => epoch === waitEpoch && generation === waitGeneration;
    const settleUnverified = () => {
      if (!stillCurrent()) return;
      notify(event, "unverified-wait");
    };

    // A NEW verification must not inherit the PREVIOUS one's state. `recheckRunId`
    // is set when a WAIT is verified and cleared when it is not; if a second WAIT
    // names the SAME run with no intervening input/session reset, a stale
    // `recheckRunId` would otherwise make this new check look already-verified
    // and suppress its expiry forever. Clear the prior verification identity and
    // ALL prior artifacts (timers AND RPC listeners) so every WAIT is judged on
    // its OWN fresh evidence.
    recheckRunId = null;
    clearWaitArtifacts();

    // No named wake path: nothing can be proven, so this is unverified on its
    // face. Still deferred through the window so a burst of settles cannot emit
    // more than one notice.
    if (proof === null) {
      waitTimer = schedule(settleUnverified, WAIT_VERIFICATION_MS);
      return;
    }

    const identity = sessionIdentity(ctx);

    // A provider owner attests through its own narrow request pair.
    if (proof.kind === "provider") {
      if (replyProvesWake(askProviderOwner(proof, ctx), proof, identity)) return;
      waitTimer = schedule(settleUnverified, WAIT_VERIFICATION_MS);
      return;
    }

    // A subagent WAIT: ask the live RPC bridge about the EXACT run. The reply is
    // asynchronous, so the bound is enforced by a racing window timer rather
    // than by blocking the settle.
    //
    // The expiry must NOT decide for itself whether the reply proved anything.
    // It is a pure "no answer arrived in time" guard: a valid reply cancels it,
    // and an absent/invalid reply leaves it to fire. Re-testing the proof at
    // expiry with null inputs would always report "unproven" and notify even
    // after a successful verification.
    let answered = false;
    // CORR10/NEW-2: how many times a `no_active_session` refusal may be deferred
    // before it becomes decisive. Only the not-ready code is ever retried.
    let bridgeRetriesLeft = WAIT_BRIDGE_NOT_READY_RETRIES;

    const onReply = (reply: unknown, request: unknown) => {
      // C4: a reply from a SUPERSEDED verification must be a complete no-op. It
      // may not touch this verification's timer, arm a recheck, or notify.
      if (!stillCurrent()) return;
      // CORR10/NEW-2: a `no_active_session` refusal is a bridge-readiness signal,
      // not evidence about the run. Defer and re-ask a bounded number of times so
      // a restored, genuinely live WAIT is not falsely rejected merely because
      // pi-subagents' bridge context is not yet set in the `-e` load order. The
      // racing expiry keeps running throughout, so the deferral stays bounded.
      if (bridgeRetriesLeft > 0 && rpcReplyIsBridgeNotReady(reply, request)) {
        bridgeRetriesLeft -= 1;
        // The old request is spent; free its listener and hold the answer open.
        waitRequestCancel = null;
        if (waitRetryTimer !== null) {
          try {
            cancelScheduled(waitRetryTimer);
          } catch {
            // best-effort only
          }
          waitRetryTimer = null;
        }
        waitRetryTimer = schedule(() => {
          waitRetryTimer = null;
          if (!stillCurrent()) return;
          askBridge();
        }, WAIT_BRIDGE_NOT_READY_RETRY_MS);
        return;
      }
      answered = true;
      // The answer arrived: retire the racing expiry so it cannot notify over a
      // successful verification, and release the request handle.
      waitRequestCancel = null;
      if (waitTimer !== null) {
        try {
          cancelScheduled(waitTimer);
        } catch {
          // best-effort only
        }
        waitTimer = null;
      }
      // Proven only by the exact full run id, alive, in this session. The
      // provenance index is consulted so a run this session genuinely witnessed
      // under the CURRENT request epoch corroborates ownership - it never
      // substitutes for liveness.
      const ownedHere = provenanceBelongsToSession(provenance, proof.id, identity);
      const live = rpcReplyProvesCurrentOwner(reply, request, proof.id);
      rememberCurrentOwner(proof.id, live);
      if (ownedHere && live) {
        scheduleRecheck(event, proof.id);
        return;
      }
      notify(event, "unverified-wait");
    };
    // C5/NEW-2: publish the CURRENT handle so lifecycle cleanup (and a retry)
    // can always free the live request's listener, not just the first one's.
    const askBridge = () => {
      waitRequestCancel = askSubagentOwner(proof.id, onReply);
    };
    askBridge();
    // A reply that never arrives must still resolve to a notice. The guards
    // prevent a late double-notify and a superseded verification's expiry. This
    // is the OVERALL bound: it spans every retry attempt, so a bridge that never
    // becomes ready still resolves to the unverified notice.
    waitTimer = schedule(() => {
      if (!stillCurrent()) return;
      if (answered) return;
      // Free the unanswered request's listener at expiry.
      if (waitRequestCancel !== null) {
        const cancel = waitRequestCancel;
        waitRequestCancel = null;
        cancel();
      }
      if (waitRetryTimer !== null) {
        try {
          cancelScheduled(waitRetryTimer);
        } catch {
          // best-effort only
        }
        waitRetryTimer = null;
      }
      // F4: an UNANSWERED fresh verification must retire any owner cached by a
      // PREVIOUS verification of the same run. Leaving it cached would let
      // `verifiedWakeOwnerExists()` keep suppressing decision repair on the
      // strength of an owner we have just failed to re-confirm.
      rememberCurrentOwner(proof.id, false);
      settleUnverified();
    }, WAIT_VERIFICATION_MS);
  };

  /**
   * Arm ONE observational recheck for an already-verified owner.
   *
   * The recheck asks the same run again; if the bridge no longer reports it
   * active, the unverified notice fires, so a child that died quietly cannot
   * leave the run stalled forever. Exactly one timer exists per verified WAIT;
   * a new verification cancels the prior one through `cancelWaitVerification`.
   */
  const scheduleRecheck = (event: unknown, runId: string) => {
    const epoch = waitEpoch;
    // C4: bind the recheck to the generation that produced it too. A recheck is
    // only meaningful while the verification that scheduled it is still current;
    // a superseded verification's recheck must not notify on the new one's
    // behalf.
    const generation = waitGeneration;
    const stillCurrent = () => epoch === waitEpoch && generation === waitGeneration;
    recheckRunId = runId;
    recheckEvent = event;
    if (recheckTimer !== null) {
      try {
        cancelScheduled(recheckTimer);
      } catch {
        // best-effort only
      }
      recheckTimer = null;
    }
    recheckTimer = schedule(() => {
      recheckTimer = null;
      if (!stillCurrent()) return;
      // A recheck whose reply never arrives must ALSO notice: an owner that
      // stopped answering is exactly the disappeared worker this recheck exists
      // to catch. The expiry is a pure no-answer guard - a valid reply cancels
      // it - rather than a proof re-test that always fails on null inputs.
      let answered = false;
      let expiry: unknown = null;
      const cancelExpiry = askSubagentOwner(runId, (reply, request) => {
        answered = true;
        // C5: this request is resolved; drop the published handle so cleanup
        // does not double-cancel it.
        recheckRequestCancel = null;
        if (expiry !== null) {
          try {
            cancelScheduled(expiry);
          } catch {
            // best-effort only
          }
          expiry = null;
          recheckExpiryTimer = null;
        }
        if (!stillCurrent()) return;
        if (!rpcReplyProvesCurrentOwner(reply, request, runId)) {
          recheckRunId = null;
          // C6: a FAILED recheck must also retire the cached owner, otherwise
          // `verifiedWakeOwnerExists()` can keep suppressing decision repair
          // from a run we have just learned is not alive.
          rememberCurrentOwner(runId, false);
          notify(event, "unverified-wait");
        }
      });
      // C5: register the handle so lifecycle cleanup frees this listener even
      // when the recheck timer itself is cancelled by supersession.
      recheckRequestCancel = cancelExpiry;
      expiry = schedule(() => {
        recheckExpiryTimer = null;
        if (!stillCurrent()) return;
        if (answered) return;
        // Free the unanswered request's listener at expiry.
        recheckRequestCancel = null;
        cancelExpiry();
        recheckRunId = null;
        rememberCurrentOwner(runId, false);
        notify(event, "unverified-wait");
      }, WAIT_VERIFICATION_MS);
      // F5: publish the inner expiry timer as well, so cleanup between the
      // recheck firing and its expiry can cancel it on every lifecycle path.
      recheckExpiryTimer = expiry;
    }, WAIT_RECHECK_MS);
  };

  /**
   * True when the provenance index binds this run to THIS session.
   *
   * Provenance is CORROBORATION only: it records that this session witnessed the
   * run START under the current request epoch. It never proves liveness, so the
   * RPC reply must still attest the run is active. A foreign session, a previous
   * request epoch, or an unknown run all fail closed. An empty session identity
   * can bind nothing, so it fails closed too.
   */
  const provenanceBelongsToSession = (provenance: ProvenanceIndex, runId: string, identity: string): boolean => {
    const uuid = sessionUuid(identity);
    if (uuid.length === 0) return false;
    const record = provenance.get(runId);
    if (record === undefined) return false;
    if (record.sessionUuid !== uuid) return false;
    // PG4/AC-F2-2: a run this session watched reach a terminal state is
    // POSITIVE proof the wake path is gone, so it can never corroborate a WAIT.
    // This must be checked here (not by deleting the record) so the terminal
    // rejection also holds for provenance restored by a reload.
    if (record.terminal) return false;
    // R6-5/AC-F2-1: the run must be able to DELIVER an independent completion
    // wake to this parent. A workflow-awaited async child publishes to a
    // workflow-owned path and its completion is skipped by the notifier, so it
    // can never end silent waiting on its own. Fail closed: a record without an
    // established delivery path cannot corroborate a WAIT.
    if (!record.deliveryCapable) return false;
    // F3: the record must belong to THIS runtime instance. A reload in another
    // process shares the session uuid and is re-stamped into the current epoch,
    // so without this check it would inherit wake trust it cannot honour (the
    // status payload cannot attest `completionOwnerId`, and pi-subagents refuses
    // delivery to a non-owner). A foreign or empty instance id fails closed.
    //
    // PG5: the id is PROCESS-stable (anchored on a global), so a same-process
    // `/reload` keeps it and still recognises its own provenance. Reading it
    // through `currentRuntimeInstanceId()` keeps this comparison aligned with
    // the process anchor rather than a stale module-local copy.
    if (record.runtimeInstanceId !== currentRuntimeInstanceId()) return false;
    // The record must belong to the CURRENT request epoch; a reload restores
    // provenance at the CURRENT epoch, so a run witnessed before this request
    // cannot corroborate a WAIT in it.
    return record.requestEpoch === observationEpoch;
  };

  /**
   * Retire a run from the provenance index once it is known terminal.
   *
   * Called from the terminal observation. Terminal provenance can never
   * corroborate a WAIT again, and dropping it keeps the index bounded by live
   * runs.
   */
  const retireProvenance = (runId: string) => {
    provenance.delete(runId);
  };

  /**
   * True when a BLOCKED declaration names a run that CURRENTLY owns the wake.
   *
   * The SAME current-owner standard the WAIT path uses, reused rather than
   * re-derived: the run must be bound to this session by provenance at the
   * current request epoch AND be confirmed CURRENTLY active by the live RPC
   * bridge. An observed START alone is deliberately insufficient - it attests
   * past existence, not present liveness - so the ledger cannot stand in for the
   * bridge. The answer comes from `currentOwnerActive`, the cache the RPC reply
   * path populates, whose entries expire with the request epoch.
   *
   * Only the `user` form names a run (its `oracle=` id); `external` and
   * unstructured declarations name none, so no wake owner can be attributed and
   * the ordinary repair path applies. A run whose inspected evidence shows
   * `state === "complete"` is not a PENDING wake owner.
   */
  const verifiedWakeOwnerExists = (declaration: BlockedDeclaration | null, identity: string): boolean => {
    if (declaration === null || declaration.form !== "user") return false;
    const runId = declaration.oracleRunId;
    if (!provenanceBelongsToSession(provenance, runId, identity)) return false;
    const run = observedRuns.get(runId);
    if (run === undefined) return false;
    // A completed run is not a PENDING wake owner: it will not wake this parent.
    if (inspectObservedRun(run).completed) return false;
    // R8-3: neither is a run that reached a terminal state WITHOUT succeeding.
    // A `failed`/`stopped`/`interrupted` run can no longer wake anyone, so
    // excluding only `completed` left a dead run able to suppress decision
    // repair. Read the authoritative on-disk state (the same source
    // `inspectObservedRun` uses) rather than inferring from `completed` alone.
    const state = observedRunDiskState(run);
    if (state !== null && ownerStateIsTerminal(state)) return false;
    // Current liveness must have been attested by the bridge itself.
    return currentOwnerActive(runId);
  };

  /**
   * The set of run ids the live RPC bridge last reported as CURRENTLY active.
   *
   * Populated only by a proven `rpcReplyProvesCurrentOwner` result, and cleared
   * with the observation epoch so a run confirmed in a PREVIOUS request can
   * never be treated as currently active in this one. This is a corroborating
   * cache, NOT a persisted permit: it lives in memory and is never written to
   * the session store.
   */
  const currentOwnerActive = (runId: string): boolean => currentOwnerRuns.has(runId);
  const rememberCurrentOwner = (runId: string, active: boolean) => {
    if (active) currentOwnerRuns.add(runId);
    else currentOwnerRuns.delete(runId);
  };
  /**
   * The verification facts an observed run yields on demand.
   *
   * `completed` is `status.json.state === "complete"`; the process exit code is
   * never consulted. `result` is the text of the authoritative output file, from
   * which the assessment and the question line are parsed.
   */
  const inspectObservedRun = (run: ObservedRun): ObservedRunEvidence => {
    if (run.asyncDir === null) return { asyncDir: null, resultPath: null, result: null, completed: false };
    return readObservedRunEvidence(run.asyncDir, readFile);
  };

  /**
   * R8-3: the authoritative on-disk `status.json` state for an observed run, or
   * null when it cannot be read.
   *
   * Read from the SAME `status.json` that backs `inspectObservedRun`, so the
   * terminal judgement uses one consistent source of truth. Returns the raw
   * state string; the caller decides terminality. A run with no async dir or an
   * unreadable status yields null (the caller treats that as "cannot establish"
   * and does NOT infer a terminal state from it).
   */
  const observedRunDiskState = (run: ObservedRun): string | null => {
    if (run.asyncDir === null) return null;
    const status = readJsonArtifact(join(run.asyncDir, "status.json"), readFile);
    if (status === null) return null;
    return typeof status.state === "string" && status.state.length > 0 ? status.state : null;
  };

  /**
   * Verify a `STATUS:BLOCKED user` escalation against everything that must hold.
   *
   * ALL of these must pass, or the escalation is unverified:
   *
   *   1. the run id is in the observed-run ledger (witnessed start);
   *   2. it is bound to THIS parent session by UUID;
   *   3. it belongs to the CURRENT request epoch (the ledger's epoch);
   *   4. it completed successfully (`state === "complete"`);
   *   5. its actual final result carries exactly one versioned
   *      `USER_INPUT_REQUIRED` assessment;
   *   6. the assessment's dependency id matches the marker's;
   *   7. the PARENT's own projected final message carries a UNIQUE eligible
   *      `USER_QUESTION:` line matching the assessment question. Oracle's own
   *      artifact is NOT scanned for the question: the protocol requires the
   *      PARENT to repeat it.
   *
   * The async dir comes ONLY from the observed ledger, never from the marker; a
   * marker-supplied path is therefore unusable by construction.
   */
  const verifyUserEscalation = (
    declaration: Extract<BlockedDeclaration, { form: "user" }>,
    ctx: SupervisorContext,
    parentText: string,
  ): { verified: boolean; reason: string } => {
    const run = observedRuns.get(declaration.oracleRunId);
    if (run === undefined) {
      return { verified: false, reason: "no observed Oracle run with that id in this session" };
    }
    if (run.agent.trim().toLowerCase() !== "oracle") {
      return { verified: false, reason: "the referenced run was not launched as Oracle" };
    }
    const uuid = sessionUuid(sessionIdentity(ctx));
    if (uuid.length === 0 || run.sessionUuid !== uuid) {
      return { verified: false, reason: "the referenced run belongs to another parent session" };
    }
    if (run.requestEpoch !== observationEpoch) {
      return { verified: false, reason: "the referenced run belongs to a previous request epoch" };
    }

    // The async dir comes ONLY from the observed ledger. A run observed without
    // one cannot produce a readable result, so it is unverified outright.
    if (run.asyncDir === null) {
      return { verified: false, reason: "the observed run exposes no result artifact" };
    }
    const evidence = inspectObservedRun(run);
    if (!evidence.completed) {
      return { verified: false, reason: "the referenced Oracle run did not complete successfully" };
    }
    if (evidence.result === null) {
      return {
        verified: false,
        reason: evidence.truncated
          ? "the referenced Oracle run's result artifact could not be read in full (oversize or incomplete)"
          : "the referenced Oracle run has no readable result",
      };
    }

    const assessment = parseUserInputAssessment(evidence.result);
    if (assessment === null) {
      return { verified: false, reason: "the result carries no single eligible USER_INPUT_REQUIRED assessment" };
    }
    if (assessment.dependencyId !== declaration.dependencyId) {
      return { verified: false, reason: "the assessment names a different dependency" };
    }

    // The question line lives in the PARENT's projected final message - the same
    // source that declares the marker - exactly as the protocol requires. Oracle's
    // own artifact is not consulted for it.
    const questions = userQuestionLines(parentText).filter((line) => line.length > 0);
    if (questions.length !== 1) {
      return { verified: false, reason: "the final message does not carry exactly one USER_QUESTION line" };
    }
    if (questions[0] !== assessment.question) {
      return { verified: false, reason: "the USER_QUESTION line does not match the assessment question" };
    }

    return { verified: true, reason: "verified" };
  };

  /**
   * The whole behaviour: turn a declared status into (continue?, notify?).
   *
   * | declared            | continue | notify |
   * |---------------------|----------|--------|
   * | CONTINUE + budget   | yes      | no     |
   * | CONTINUE, no budget | no       | yes    |
   * | WAIT                | no       | no     |
   * | DONE/BLOCKED/FAILED | no       | yes    |
   * | unknown             | no       | yes    |
   *
   * "notify when not sure": the last row is the default for everything this
   * extension cannot establish, including a missing marker.
   */
  const handleBeforeSettle = (
    event: unknown,
    ctx: SupervisorContext,
  ): SupervisorHandlerResult | void => {
    const boundary = event as AgentBeforeSettleLike | null;
    if (!isTui(ctx) || boundary === null || typeof boundary !== "object") return;
    // Every boundary refreshes the ledger's notion of the active session, so a
    // run observed without an explicit identity is attributed to THIS session
    // and to THIS request's epoch.
    ledgerSession = sessionIdentity(ctx) || ledgerSession;
    noteSession(ctx);
    // FEATURE 3: consume `TASK:ADD` / `TASK:CANCEL` action lines from this
    // boundary's final message at the settle boundary. Cancellation is
    // idempotent and never aborts a turn that has already begun.
    consumeTaskActions(boundary);
    // A parser failure while reading the boundary must degrade to the SAFE
    // documented default - no bridge, notify the user - rather than throwing
    // out of this handler. The marker is read here, BEFORE any bridge or
    // notification is emitted; an uncaught throw would therefore produce
    // NEITHER, and Pi would receive no continuation proposal while also
    // emitting no notice. That is the silent-stop failure mode the objective
    // forbids. Swallowing the error into "attention" keeps the meaning of every
    // other failure in this handler: when the declaration cannot be
    // established, the user is told.
    let marker: DeclaredMarker | null;
    try {
      marker = markerForBoundary(boundary);
    } catch {
      notify(event, "attention");
      return;
    }
    const status = marker?.status ?? "unknown";
    // `WAIT` is verified, not trusted. A completed WAIT never asks for
    // continuation, but its silence is deferred to `agent_settled`, where the
    // named wake path is proven. This handler therefore only declines to
    // continue; it does not decide the notification.
    if (status === "wait") return;

    // --- Decision repair boundary -----------------------------------------
    // An UNSUPPORTED stop - an unstructured BLOCKED, an invalid user proof, or
    // a CONTINUE whose payload leads with a human-wait clause - is not a user
    // contact. Before falling through to the ordinary notify path, offer a
    // decision-repair bridge governed by the SAME continuation policy. A
    // verified user escalation is handled below, where it earns the
    // notification rather than a repair.
    const declaration = status === "blocked" ? parseBlockedDeclaration(marker?.payload ?? "") : null;
    const parentText = messageText(finalProjectedMessage(boundary));
    const userEscalation =
      declaration !== null && declaration.form === "user"
        ? verifyUserEscalation(declaration, ctx, parentText)
        : null;
    const verifiedUserEscalation = userEscalation !== null && userEscalation.verified;

    // The repair predicate. `external` BLOCKED is a supported nonhuman dependency
    // and is NOT repaired (it notifies); a verified `user` escalation notifies;
    // everything else with a marker is a candidate for repair when the boundary
    // can carry a bridge and a slot remains.
    const repairable =
      marker !== null &&
      !verifiedUserEscalation &&
      (status !== "blocked" ||
        declaration?.form === "unstructured" ||
        declaration?.form === "invalid" ||
        (declaration?.form === "user" && userEscalation !== null && !userEscalation.verified));
    const humanWaitingContinue =
      status === "continue" && marker !== null && humanWaitingLeadingClause(marker.payload);
    const repairCandidate = (repairable && status === "blocked") || humanWaitingContinue;

    // A verified automatic wake owner already owns the continuation: an observed
    // run the declaration names is still pending in the ledger, so a premature
    // BLOCKED must NOT spawn a second continuation while that child owns the
    // A verified automatic wake owner already owns the continuation: an
    // observed run the declaration names is still pending in the ledger, so a
    // premature BLOCKED must NOT spawn a second continuation while that child
    // owns the wake. This reuses the WAIT path's verified-wake-owner condition
    // rather than inventing a parallel rule.
    //
    // When the OTHER owner is an extension handler that already asked Pi to
    // continue, that is NOT a reason for this extension to stay silent: Pi
    // computes `canContinue` from the committed context, and a bare
    // `continue: true` carries no runnable message. Supplying the bridge here is
    // what makes that continuation real (see `proposeContinuation`).
    const wakeOwnerOwnsContinuation =
      repairCandidate && verifiedWakeOwnerExists(declaration, sessionIdentity(ctx));

    if (repairCandidate && wakeOwnerOwnsContinuation) {
      notify(event);
      return;
    }

    // --- Continuation policy --------------------------------------------
    // There is no cumulative allowance. A well-formed declaration proposes
    // whenever the boundary permits it; the only vetoes are the boundary's own
    // (outcome, missing draft array) and an operator disable.

    // An unverified user escalation reports the DISTINCT unverified-escalation
    // cause so the notice never implies the user owes an option selection.
    const notifyCause = isUnverifiedEscalation(status, userEscalation, verifiedUserEscalation)
      ? "unverified-escalation"
      : "attention";

    // Step (1): the boundary's own vetoes run over EVERY continuation, including
    // decision repair. An operator disable and a non-completed outcome (aborted
    // or error) each prohibit continuation for their own reason; repair is a
    // continuation too, so letting it through would make `PI_MAX_CONTINUATIONS=0`
    // disable only the ordinary path, and would repair an aborted or errored run.
    if (continuationDisabled || boundary.outcome !== "completed") {
      notify(event, notifyCause, markerProblemFor(finalProjectedMessage(boundary), marker));
      return;
    }

    // Decision repair and ordinary CONTINUE share ONE proposal path so they can
    // never drift. Repair is decided FIRST because a repairable declaration is by
    // definition not an ordinary CONTINUE (`BLOCKED`, or a human-waiting
    // CONTINUE): the ordinary-continue guard below would otherwise swallow it.
    if (repairCandidate) {
      const repaired = proposeContinuation(
        boundary,
        buildRepairEntry(repairReason(status, declaration, userEscalation)),
      );
      if (repaired === null) {
        // A boundary with no draft array cannot carry the bridge entry.
        notify(event, notifyCause, markerProblemFor(finalProjectedMessage(boundary), marker));
        return;
      }
      return repaired;
    }

    if (marker === null || status !== "continue" || !canPropose(boundary)) {
      // Everything else - including an absent or malformed marker - tells the
      // user. "Notify when not sure."
      notify(event, notifyCause, markerProblemFor(finalProjectedMessage(boundary), marker));
      return;
    }

    // Ordinary CONTINUE. NOTE: `boundary.continue === true` is NOT a reason to
    // bail out - another handler may have set the flag with no runnable message,
    // and a later handler may set it after this one. Appending the bridge is what
    // supplies `canContinue`; the flag is set alongside it for clarity.
    const proposed = proposeContinuation(boundary, buildBridgeEntry(marker));
    if (proposed === null) {
      // A boundary with no draft array cannot carry the bridge entry, so the
      // declaration cannot be acted on: notify rather than silently swallowing it.
      notify(event, notifyCause, markerProblemFor(finalProjectedMessage(boundary), marker));
      return;
    }
    return proposed;
  };

  /**
   * The transcript reason for a repair bridge.
   *
   * Purely descriptive; it never changes what the bridge MEANS. An invalid user
   * proof names the failed verification; an unstructured BLOCKED or a
   * human-waiting CONTINUE names the marker itself.
   */
  const repairReason = (
    status: DeclaredStatus,
    declaration: BlockedDeclaration | null,
    userEscalation: { verified: boolean; reason: string } | null,
  ): string => {
    if (status === "continue") return "a CONTINUE payload that leads with a human-waiting clause";
    if (declaration === null) return "an unstructured BLOCKED declaration";
    if (declaration.form === "user") {
      return userEscalation !== null ? userEscalation.reason : "an unverified user escalation";
    }
    if (declaration.form === "invalid") return "a malformed structured BLOCKED declaration";
    return "an unstructured BLOCKED declaration";
  };

  /**
   * True when this settle should report the DISTINCT unverified-escalation
   * cause: an attempted user escalation that did not verify. An `external
   * BLOCKED`, an ordinary stop, and a verified user escalation all report the
   * generic attention cause instead.
   */
  const isUnverifiedEscalation = (
    status: DeclaredStatus,
    userEscalation: { verified: boolean; reason: string } | null,
    verified: boolean,
  ): boolean => {
    return status === "blocked" && userEscalation !== null && !verified;
  };

  /**
   * True when a declared CONTINUE may actually be proposed to Pi.
   *
   * Only the boundary can veto: an aborted or errored run, a boundary that
   * cannot carry entries, and an operator disable (`PI_MAX_CONTINUATIONS=0`)
   * all prohibit continuation. There is deliberately NO cumulative allowance
   * here - a well-formed CONTINUE on a completed boundary always proposes.
   */
  const canPropose = (boundary: AgentBeforeSettleLike): boolean => {
    if (boundary.outcome !== "completed") return false;
    return !continuationDisabled;
  };

  /**
   * Step (3) of the continuation decision order: real queued messages own the
   * next request.
   *
   * Pi's `_getPendingBoundaryMessages()` exposes `peekQueuedMessages() +
   * _pendingCustomMessages` as `boundary.context.pendingMessages`, and Pi's
   * `_runBeforeSettleBoundary` continues on `hasQueuedMessages()` regardless of
   * any handler's flag. When that array is non-empty, the next request is
   * already owned, so this handler must add NO bridge - otherwise its prompt is
   * delivered on top of the queued work and the model answers a duplicated ask.
   */
  /**
   * True when the pending array holds work that GENUINELY owns the next request.
   *
   * The pending array is NOT a reliable "another request is coming" signal. Pi
   * builds it from `peekQueuedMessages()` PLUS `_pendingCustomMessages`
   * (`agent-session.js:614`), and the latter holds context-only custom messages
   * (submitted with `triggerTurn:false`) that are flushed into the model context
   * WITHOUT driving a further turn. Pi's own continuation decision is
   * `result.continue || agent.hasQueuedMessages()` (`agent-session.js:1464`), and
   * `hasQueuedMessages()` covers ONLY the steering/follow-up queues - it excludes
   * `_pendingCustomMessages`.
   *
   * Treating every pending entry as ownership therefore suppresses the bridge for
   * a request Pi will NOT continue, which stops a valid CONTINUE silently - the
   * exact failure this extension exists to prevent. Only a pending entry that
   * represents real queued USER work may suppress the bridge; a context-only
   * custom message is not such work.
   *
   * A custom message is recognized by the marker Pi itself puts on it
   * (`customType`/`custom_message`), which is how these entries arrive on the
   * pending array; everything else counts as genuine queued work, so the
   * conservative default preserves the original duplicate-suppression intent.
   */
  /**
   * True when the pending array POSITIVELY identifies genuine queued work.
   *
   * Only entries this extension can affirmatively recognize as queued user work
   * count. A `role:"custom"` entry is AMBIGUOUS: Pi routes the same shape to
   * the steering/followUp queues (genuine work) and to `_pendingCustomMessages`
   * (context-only), so its presence is not evidence of queue ownership.
   *
   * FAILURE ASYMMETRY decides the ambiguous case. If we wrongly claim queue
   * ownership we return no bridge and NO continuation flag, so a valid
   * `STATUS:CONTINUE` STOPS - the exact bug this extension exists to prevent.
   * If we wrongly decline it, the worst case is one redundant bridge, and step
   * (4) below already suppresses that whenever the host's own continuation is
   * runnable. The bridge is therefore supplied for every ambiguous entry.
   *
   * A plain user message (`role:"user"`) is unambiguous: Pi's
   * `hasQueuedMessages()` reports it, so Pi continues by itself and our bridge
   * would duplicate the queued prompt.
   */
  const hasQueuedOwnership = (boundary: AgentBeforeSettleLike): boolean => {
    const pending = boundary.context?.pendingMessages;
    if (!Array.isArray(pending) || pending.length === 0) return false;
    return pending.some((entry) => isGenuineQueuedWork(entry));
  };

  /**
   * The ONE continuation proposal path.
   *
   * Ordinary CONTINUE and decision repair both flow through here so the two can
   * never drift. `entry` is the runnable bridge that makes the continuation
   * real: Pi computes `canContinue` from the COMMITTED context, so returning
   * bare `continue: true` with no draft is not enough - a later-settled
   * `agent_before_settle` handler may set the flag while this extension supplies
   * the only runnable message. The flag is set unconditionally; the entry is the
   * load-bearing part.
   *
   * Returns null when the boundary cannot carry entries, so the caller can
   * notify with the cause that applies to ITS path.
   */
  const proposeContinuation = (
    boundary: AgentBeforeSettleLike,
    entry: BridgeEntry,
  ): SupervisorHandlerResult | null => {
    // Step (3): real queued messages already own the next request. Pi continues
    // on `hasQueuedMessages()` regardless of what this handler returns, so
    // appending our bridge would deliver a SECOND, redundant prompt alongside
    // the queued work. Declining to add anything is the correct "no bridge".
    if (hasQueuedOwnership(boundary)) return undefined;

    // Step (4): another handler already requested continuation AND its context is
    // already runnable. Nothing needs supplying, so the continuation is left
    // untouched rather than duplicated with a second bridge.
    if (boundary.continue === true && boundary.context?.canContinue === true) return undefined;

    if (!Array.isArray(boundary.entries)) return null;
    return { entries: [...boundary.entries, entry], continue: true };
  };

  /**
   * Read the declared marker for this boundary.
   *
   * The projected final message is the authority; a final message with no text
   * declares nothing. Walking backward would let an appended textless draft
   * resurrect an OLDER declaration - a stale CONTINUE would restart work, and a
   * stale WAIT would wrongly stay silent.
   */
  const markerForBoundary = (boundary: AgentBeforeSettleLike): DeclaredMarker | null => {
    // Contract: only the FINAL projected message may declare. Walking backward
    // would let an appended textless draft (custom entry, tool result, or a
    // thinking-only assistant message) resurrect an OLDER declaration - a stale
    // CONTINUE would restart work, and a stale WAIT would wrongly stay silent.
    // A final message with no text simply declares nothing.
    const last = finalProjectedMessage(boundary);
    if (last === undefined) return null;
    return readDeclaredMarker(last);
  };

  /**
   * A blocking UI prompt always needs the user, so it always notifies.
   *
   * This is the only notification that does not consult a declared marker: a
   * prompt is opened by the host, not by the model's final message, and it may
   * be asking for authorization the run cannot proceed without. Only a TUI
   * session gets a terminal notification at all.
   */
  const handleAttention = (event: unknown, ctx: SupervisorContext) => {
    if (!isTui(ctx)) return;
    notify(event);
  };

  // A new session (startup/reload/new/resume/fork) or tree navigation means any
  // retained history is not this extension's allowance: start from zero and
  // require a fresh handshake. Any pending WAIT check is stale for the same
  // reason. Returning `undefined` from `input` is required - Pi swallows the
  // user's prompt on `{action:"handled"}`.
  const handleSessionStart = (event: unknown, ctx: SupervisorContext) => {
    // R9-3: a session_start opens a new session/verification epoch, so the
    // notification dedup must NOT carry over from the session that just ended.
    // Without this, a generic stop before the restart left `notified` set, and a
    // resumed unowned WAIT whose bounded verification later failed produced NO
    // notice at all - the previous stop's notification swallowed it. Dedup still
    // holds WITHIN this new epoch (a burst of settles emits one notice).
    notified = false;
    // R8-1: capture any OUTSTANDING WAIT obligation BEFORE cancelling its
    // artifacts. `cancelWaitVerification()` tears down the timers/listeners, and
    // for a same-session reload the obligation they represent is still owed: Pi
    // emits ONLY `session_start` on reload (never a fresh `agent_settled`), so
    // without re-establishing it the session would go silent with no
    // verification, no notice, and no timer.
    cancelWaitVerification();
    disarm();
    // FEATURE 3: a session start opens a new registration scope for the
    // scheduler. The transient fence is re-minted, the in-flight handoff is
    // dropped, and the persisted store is reloaded so THIS session's tasks are
    // armed while a task owned by a DIFFERENT session stays retained until its
    // exact session resumes. The JSON is preserved across shutdown/re-registration.
    registrationToken = mintRegistrationToken();
    taskHandoff = null;
    currentSessionId = sessionIdentity(ctx);
    // Oracle OPTION D: capture the persisted transcript path for the CURRENT
    // session so confirmation can read it. Captured here (every session_start)
    // rather than inside `sessionIdentity`, whose value may be a bare uuid.
    currentSessionFile = sessionTranscriptPath(ctx);
    restoreTasks();
    // Pi distinguishes WHY a session start fired
    // (`dist/core/extensions/types.d.ts:562-569`): `startup` | `reload` |
    // `new` | `resume` | `fork`. Only `reload`/`resume` continue the session
    // whose provenance was persisted; `startup`/`new`/`fork` open a different
    // scope and must inherit nothing.
    const reason = (event as { reason?: unknown } | null)?.reason;
    const continuesSameSession = reason === "reload" || reason === "resume";

    // R6-6/AC-P-2: a same-session reload must NOT re-stamp restored records into
    // a fresh epoch. `clearObservedRuns()` would advance the counter past them, so
    // a reloaded session's own records became ineligible - and the previous code
    // compensated by re-stamping them, which conversely revived records a REQUEST
    // REPLACEMENT had already rejected. Neither is correct. Instead a continuing
    // session keeps its epoch and its records; anything else starts fresh.
    if (continuesSameSession) {
      observedRuns = new Map();
      provenance = new Map();
      currentOwnerRuns = new Set<string>();
    } else {
      // A replacement session starts a fresh request scope: nothing observed
      // under the old one can underwrite an escalation here.
      clearObservedRuns();
    }
    ledgerSession = "";
    // Restore PROVENANCE for a same-session reload/resume from the current
    // branch. This restores only WHICH runs were witnessed and their binding;
    // liveness must still be re-proven by the bridge. A missing reader restores
    // nothing, which can only make a later WAIT unverified.
    //
    // R9-2: this ENTIRE restoration - reading, provenance repopulation, the
    // observed-run ledger repopulation, and the generation adoption below - is a
    // CONTINUE-scope operation. A `startup`/`new`/`fork` (or omitted reason)
    // opens a DIFFERENT scope and inherits NOTHING: the branch was persisted by
    // the session that is now gone, so treating it as this session's own
    // provenance let a foreign request's completed assessment be accepted as
    // verified. Only `reload`/`resume` may restore.
    if (continuesSameSession) {
      const view = ctx?.sessionManager;
      const entries = readSessionEntries(view);
      if (entries.length > 0) {
        const restored = restoreProvenance(entries);
        provenance = new Map();
        // R6-6/AC-P-2: the request generation is DURABLE, not the local counter.
        // `clearObservedRuns()` has already opened a new scope here, so the
        // in-memory counter is meaningless for judging a persisted record. The
        // LATEST persisted generation says which request was actually in progress
        // when this process went away; only records carrying THAT generation are
        // eligible. A record from an earlier request stays ineligible even though
        // it was persisted, and even when the later request witnessed no run at
        // all - the generation marker records the request boundary itself.
        // CORR10/NEW-1: judged in THIS process's counter DOMAIN. A marker written
        // by an earlier process belongs to a different (restarted-at-1) counter,
        // so its historical maximum must not displace this process's own latest
        // generation and reject a genuinely fresh run's provenance.
        // CORR11/NEW-1: judged within this process's CURRENT counter LINEAGE. A
        // single process can persist MORE THAN ONE lineage in the same domain
        // (each module re-registration resets the counter), so the lookup also
        // discards any lineage superseded by a counter restart.
        // CORR12/NEW-1: the lineage is now EXPLICIT. Selection is positional: the
        // token on the LAST domain marker names the current lineage, and only
        // records carrying THAT token are admissible - a superseded registration
        // with a numerically equal (or higher) epoch is excluded regardless of
        // value. The freshly-minted token for this load is REPLACED by the
        // recovered token, which is what lets a same-process `/reload` keep its
        // current lineage. CORR13/NEW-1: a legacy-only branch (no token anywhere)
        // yields the explicit `LEGACY_NO_LINEAGE_SENTINEL`, which is NOT a live
        // token and is never adopted below; no legacy record is admissible on
        // that path.
        const current = currentLineageGeneration(entries, currentRuntimeInstanceId());
        const latestGeneration = current?.generation ?? null;
        if (current !== null && current.lineage !== LEGACY_NO_LINEAGE_SENTINEL) lineageToken = current.lineage;
        for (const [runId, record] of restored) {
          // F3: restoring is a RE-EVALUATION, not a transfer of trust. A record is
          // admitted only when it was written by THIS runtime instance, so a
          // reopened session in another process inherits no wake trust. The
          // session uuid check is retained as a second, independent bound.
          if (record.sessionUuid !== sessionUuid(sessionIdentity(ctx))) continue;
          // PG5: compare through the process anchor so a same-process reload
          // recognises the provenance it persisted.
          if (record.runtimeInstanceId !== currentRuntimeInstanceId()) continue;
          // R6-6/CORR12-NEW-1: the record must belong to the request that was in
          // progress AND to the CURRENT registration LINEAGE. See
          // `provenanceBelongsToCurrentGeneration` for the rule and why an absent
          // marker (or an absent/legacy lineage) is fail-closed.
          if (!provenanceBelongsToCurrentGeneration(record, latestGeneration, current?.lineage)) continue;
          provenance.set(runId, record);
          // R8-2: restoration must repopulate the OBSERVED-RUN LEDGER too, not just
          // provenance. `verifyUserEscalation()` reads the ledger (and the run's
          // `asyncDir`) to reach the run's result artifact; with the ledger left
          // EMPTY, a valid, already-completed `STATUS:BLOCKED user` escalation that
          // verified correctly BEFORE the reload was re-classified as unknown after
          // it and wrongly forced through decision repair. The restored record
          // carries every field the ledger row needs (agent, asyncDir, session
          // uuid, epoch), and `terminal`/`deliveryCapable` are carried across so a
          // retired or delivery-incapable run stays that way.
          //
          // This restores only WHICH runs were witnessed and their binding; it
          // conveys no liveness and no decision to stay silent. A restored row still
          // has to satisfy the live bridge / artifact checks on its own merits.
          observedRuns.set(runId, {
            runId: record.runId,
            agent: record.agent,
            asyncDir: record.asyncDir,
            session: ledgerSession,
            sessionUuid: record.sessionUuid,
            requestEpoch: record.requestEpoch,
            terminal: record.terminal,
            deliveryCapable: record.deliveryCapable,
          });
        }
        // Adopt the durable generation as the live one, so a run witnessed AFTER
        // this reload is stamped with the SAME request generation and stays
        // consistent with records already restored for this request.
        if (latestGeneration !== null) observationEpoch = latestGeneration;
      }
    }

    // R8-1: re-establish a carried WAIT obligation after a SAME-SESSION reload.
    //
    // A true reload RE-EVALUATES this module (`moduleCache:false`), so NO
    // in-memory obligation can survive it - the probe models that by rebuilding
    // the harness from persisted entries only. In-memory state therefore CANNOT
    // satisfy this; the obligation must be re-derived from what actually
    // persists: the RESTORED PROVENANCE (a run was witnessed) plus the projected
    // final marker (the session still declares WAIT). Pi's reload path emits ONLY
    // `session_start` - never a fresh `agent_settled` - so without this the
    // reloaded session goes silent with no verification, no notice, no timer.
    //
    // Only `reload`/`resume` continue the session that was owed the wake; a
    // `startup`/`new`/`fork` opens a different scope and inherits nothing. The
    // marker is re-verified from scratch through `verifyWait`, which re-asks the
    // live bridge (or re-arms the bounded window for an unprovable proof): this
    // restores the OBLIGATION to verify, never a decision to stay silent.
    //
    // R9-1: re-verification is a TUI-ONLY EFFECT. `verifyWait` opens an RPC
    // round-trip, arms a timer, and can emit an OSC notice - all of which are
    // meaningless (and contaminating) in the print/rpc/json surfaces, where a
    // session_start is never a user-visible terminal. Outside a TUI the
    // verification is skipped ENTIRELY - not merely its notification - while the
    // provenance restoration above still happens for a continuing session.
    if (continuesSameSession && isTui(ctx)) {
      const messages = projectedFromView(ctx);
      const marker = lastAssistantMarker(messages);
      if (marker !== null && (marker.status ?? "") === "wait") {
        verifyWait(event, ctx, parseWakeProof(marker.payload ?? ""), provenance);
      }
    }
  };
  const handleSessionTree = () => {
    cancelWaitVerification();
    disarm();
    // Tree navigation lands on a DIFFERENT branch: provenance from the branch
    // left behind must never corroborate a WAIT on the branch entered.
    clearObservedRuns();
    ledgerSession = "";
  };

  /**
   * Cancel every pending timer on host shutdown.
   *
   * A verification window or an idle recheck must not outlive the session it
   * belongs to: a timer firing after shutdown could notify into a torn-down
   * transport, and a recheck could re-open an RPC round-trip for a session that
   * no longer exists. Cancelling leaves any un-notified WAIT un-notified, which
   * is correct - there is no longer a user-visible session to stall.
   */
  const handleSessionShutdown = () => {
    cancelWaitVerification();
    disarm();
    observedRuns = new Map();
    provenance = new Map();
    currentOwnerRuns = new Set<string>();
    ledgerSession = "";
    // FEATURE 3: invalidate outstanding callbacks and clear every timer, but
    // PRESERVE the persisted JSON so the tasks survive the restart. Re-minting
    // the fence means a callback that escaped the clear cannot deliver.
    registrationToken = mintRegistrationToken();
    taskHandoff = null;
    for (const handle of taskTimers.values()) {
      try {
        cancelScheduled(handle);
      } catch {
        // best-effort only
      }
    }
    taskTimers.clear();
    // FINAL REVIEW F2: cancellation retries hold real timers too. Clearing only
    // `taskTimers` left them armed past shutdown, so a callback could outlive the
    // session it belonged to. The INTENT set is preserved deliberately - a
    // cancellation that never reached disk is still intended, and the next
    // registration completes it via `restoreTasks`.
    for (const handle of cancelRetries.values()) {
      try {
        cancelScheduled(handle);
      } catch {
        // best-effort only
      }
    }
    cancelRetries.clear();
    // Oracle OPTION D: confirmation polls hold real timers and pin the handoff
    // slot. Clear them so no callback outlives the session it belonged to; the
    // persisted occurrence record makes the task re-attemptable after restart.
    for (const handle of confirmTimers.values()) {
      try {
        cancelScheduled(handle);
      } catch {
        // best-effort only
      }
    }
    confirmTimers.clear();
  };

  const resetForInput = (event: unknown, ctx: SupervisorContext) => {
    notified = false;
    // A new request supersedes any pending WAIT check: its notice would describe
    // a turn the user has already moved past.
    cancelWaitVerification();
    // A synthetic wake the pi-subagents bridge delivers as a user message is NOT
    // a new request: it must not disarm allowance or replace the epoch, or the
    // very wake a verified WAIT is waiting for would itself cancel the wait.
    // Only a genuine user/rpc request opens a new epoch.
    const source = (event as { source?: unknown } | null)?.source;
    const internalWake = source === "extension";
    if (internalWake) {
      // Preserve the observation scope; a wake continues the SAME request the
      // WAIT was verified under. There is no allowance to revoke - continuation
      // is intent under the current policy - so only the handshake phase is
      // preserved and provenance and the epoch stay intact.
      const identity = sessionIdentity(ctx);
      if (identity.length > 0) ledgerSession = identity;
      noteSession(ctx);
      return;
    }
    // A new request also opens a new observation epoch: runs witnessed for the
    // PREVIOUS request must not underwrite a question in this one.
    clearObservedRuns();
    const identity = sessionIdentity(ctx);
    if (identity.length > 0) ledgerSession = identity;
    noteSession(ctx);
    // `input` fires before later handlers can consume the input and before
    // queued input is delivered, so it does not establish that a request was
    // delivered: start the handshake rather than trusting this event alone.
    const genuine = source === "interactive" || source === "rpc";
    const steering = (event as { streamingBehavior?: unknown } | null)?.streamingBehavior !== undefined;
    phase = phase === "none" && genuine && !steering && isIdle(ctx) ? "submitted" : "blocked";
  };

  const handleBeforeAgentStart = (event: unknown, ctx: SupervisorContext) => {
    // `before_agent_start` must NOT be load-bearing for the continuation. It is
    // not guaranteed to fire between `input` and the delivered user message, and
    // when it did not, a legitimate CONTINUE could arrive with the handshake
    // unadvanced and stop silently. The delivered user `message_start` settles
    // the handshake; this handler therefore preserves a submitted request
    // instead of revoking it. A request that never left `submitted` is genuinely
    // unconsumed input, and that - not this event's absence - is what blocks it.
    if (phase === "submitted") phase = "starting";
    // F5: a run that is demonstrably starting has no pending WAIT to verify.
    // Any window/expiry/recheck artifact still armed here belongs to a turn the
    // session has moved past, and leaving it armed would keep timers and RPC
    // listeners alive across the activity boundary.
    cancelWaitVerification();
    return undefined;
  };

  const handleMessageStart = (event: unknown, ctx: SupervisorContext) => {
    const message = (event as { message?: { role?: unknown } } | null)?.message;
    if (message?.role !== "user") return;
    // FEATURE 3: a delivered (possibly injected) user message is delivered in the
    // live session, so keep the scheduler's owner current before any timer fires.
    noteSession(ctx);
    // F5: a delivered user message ends any pending WAIT window - the notice it
    // might emit would describe a turn the user has already replaced. Cancel it
    // (timers AND RPC listeners) here as well as at `input`, because `input` is
    // not guaranteed to precede delivery.
    cancelWaitVerification();
    // A delivered user message settles the handshake. `submitted` (no
    // `before_agent_start` observed) and `starting` (observed) are BOTH genuine
    // deliveries now: the run has demonstrably started, so requiring the idle
    // check here would reject exactly the case this fix exists for. No counters
    // are armed - continuation is intent, not an allowance.
    const fresh = phase === "submitted" || phase === "starting";
    phase = fresh ? "none" : "blocked";
  };

  const handleSettled = (event: unknown, ctx: SupervisorContext) => {
    // FEATURE 3: the injected turn has settled, so the scheduler's single handoff
    // guard is released and any due occurrence may now be pumped. This runs
    // before the TUI-only notification path so the guard is released in every
    // surface that can receive an injected turn.
    noteSession(ctx);
    taskHandoff = null;
    // FEATURE 3 / Review 79 R79-P1 (boundary corrected by R81-P1): `agent_settled`
    // is the first host signal at which a send is genuinely accepted again after
    // compaction, so the compaction window is CLOSED here - not in the compaction
    // event handlers - and the tasks it RETAINED are then re-pumped (due ones
    // only - R79-P2). The ordering is load-bearing: `pumpRetainedAfterCompaction`
    // must see the window already closed, or every task it pumps would be refused
    // by `canAcceptNow()` and re-armed instead of delivered.
    // This must precede the `isTui` early return below: the handoff and the
    // retained tasks are scheduler state, not a TUI-only concern.
    //
    // The close is gated on `compactionClosable` (armed by a terminal compaction
    // event): a settle that did NOT follow `session_compact`/`_failed` must not
    // silently open the send window while the host is still mid-compaction. When
    // no compaction is in flight the gate is irrelevant - `compacting` is already
    // false, so leaving it untouched is a no-op.
    if (compactionClosable) {
      compacting = false;
      compactionClosable = false;
    }
    pumpRetainedAfterCompaction();
    if (!isTui(ctx)) return;
    ledgerSession = sessionIdentity(ctx) || ledgerSession;
    // A settle is when the user-visible outcome is decided. A WAIT suppresses
    // nothing on its own: it opens a bounded verification window, and silence
    // must be earned by proof of the named wake path. Every other outcome - an
    // absent marker, a malformed one, a stale one - notifies. A BLOCKED user
    // escalation, too, notifies only when its evidence verified at the boundary;
    // the notification itself never re-derives the question.
    const messages = projectedFromView(ctx);
    // The same defensive default as `handleBeforeSettle`: a parser failure while
    // reading the settled marker must notify rather than throw. A thrown error
    // here suppresses the notice the user needs, and a settlement is exactly the
    // moment the user-visible outcome is decided.
    let marker: DeclaredMarker | null;
    try {
      marker = lastAssistantMarker(messages);
    } catch {
      cancelWaitVerification();
      notify(event, "attention");
      phase = "none";
      return;
    }
    const status = marker?.status ?? "unknown";
    // R8-4: an explicitly ABORTED settlement must never earn silent waiting. The
    // host sets `aborted` when the turn was interrupted rather than completed, so
    // a projected WAIT is NOT corroborated evidence - it is an intent the host
    // positively contradicts. Honouring it produced silent waiting AND an armed
    // recheck on a turn that never completed. Treat the abort as an authoritative
    // non-WAIT outcome: cancel any WAIT artifact and notify.
    const aborted = (event as { aborted?: unknown } | null)?.aborted === true;
    if (aborted) {
      cancelWaitVerification();
      notify(event, "attention");
      phase = "none";
      return;
    }
    if (status === "wait") {
      verifyWait(event, ctx, parseWakeProof(marker?.payload ?? ""), provenance);
    } else if (status === "blocked") {
      // PG7: a BLOCKED settlement is still a SETTLEMENT. Any WAIT artifact armed
      // by an earlier turn belongs to that turn, not this one, so it is cancelled
      // here exactly as on the DONE/unknown branch. Without this, an unanswered
      // recheck followed by a BLOCKED settlement retained its expiry timer and
      // RPC listener until their deadlines.
      cancelWaitVerification();
      const declaration = parseBlockedDeclaration(marker?.payload ?? "");
      const parentText = messageText(messages[messages.length - 1]);
      const userEscalation =
        declaration.form === "user" ? verifyUserEscalation(declaration, ctx, parentText) : null;
      notify(
        event,
        userEscalation !== null && !userEscalation.verified ? "unverified-escalation" : "attention",
      );
    } else {
      // F5: a NON-WAIT settlement carries no wake path to verify, so any WAIT
      // artifact still armed belongs to an earlier turn. Cancel it here so its
      // timers and listeners cannot outlive the settlement that superseded it.
      cancelWaitVerification();
      notify(
        event,
        "attention",
        markerProblemFor(messages[messages.length - 1], marker),
      );
    }
    // Settlement clears pending handshake state; there is no allowance to
    // replenish because continuation is intent under the current policy.
    phase = "none";
  };

  // Subscribe to the two observed-run topics ONCE. Doing it before the handler
  // registrations below keeps the ledger fed from the very first event a host
  // emits, and doing it through the same `api` object keeps it authoritative.
  observeRunEvents();

  /**
   * Mark the compaction window as CLOSABLE at the next settle.
   *
   * Review 79 R79-P1: the host emits and AWAITS `session_compact` at
   * `dist/core/agent-session.js:2246-2253` and only afterwards calls
   * `_clearManualCompactionState()` at `:2258` (whose comment, "compaction_end
   * listeners may submit queued prompts, so expose idle state before notifying
   * them", shows the ordering is deliberate). `prompt()` still rejects while
   * `_compactionAbortController !== undefined` (`:1534-1535`), and the
   * extension-facing wrapper swallows that rejection and returns void
   * (`:2712-2718`). Pumping from here therefore fired into a window whose send
   * was refused: the occurrence was already consumed durably and `injectTask`
   * still reported success, so a one-shot vanished and other tasks could stall
   * behind a handoff that never settled.
   *
   * Review 81 R81-P1 (this fix): the SAME host ordering also means `compacting`
   * must NOT be cleared here. A timer that fires inside our `session_compact`
   * handler - the emit is awaited, so the host is still mid-compaction - would
   * otherwise observe `compacting === false`, pass `canAcceptNow()`, consume the
   * occurrence durably though the send is refused, and lose it silently. The
   * window therefore stays OPEN until `agent_settled`, the send-ready boundary
   * `handleSettled` already receives; that is where the flag is cleared.
   *
   * `compaction_end` is NOT exposed to extensions (the only compaction events in
   * `dist/core/extensions/types.d.ts:1169-1171` are `session_before_compact`,
   * `session_compact` and `session_compact_failed`).
   *
   * FINAL REVIEW F1 (this fix): the earlier settle-based release was WRONG for
   * MANUAL compaction. In that path the host runs `await emit(session_compact)`
   * at `:2242`, then `_clearManualCompactionState()` at `:2259`, then an INTERNAL
   * `_emit(compaction_end)` at `:2261`, and returns - it emits NO `agent_settled`.
   * So a retained task waited for a settlement that manual `/compact` never
   * produces, suppressing scheduled work indefinitely; the suite hid this by
   * MANUFACTURING the settlement (`tests/session-supervisor.test.mjs:10189-10197`).
   *
   * The correct boundary is therefore this handler: `session_compact` is emitted
   * one statement BEFORE `_clearManualCompactionState()`, so when our handler
   * returns, the controller IS cleared and `prompt()` accepts again. Clearing
   * here is safe - and it is why the close must stay tied to the terminal event
   * rather than to a settlement. The flag is cleared directly, and retained due
   * tasks are pumped; any still-future task is left to its own timer.
   *
   * `session_compact_failed` takes the SAME path: the host clears its controller
   * on that path too, so a later settle is not required.
   *
   * THE ORDERING THAT DECIDES THE MECHANISM (verified at
   * `dist/core/agent-session.js:2242-2261`):
   *   await emit(session_compact)      // our handler runs HERE
   *   _clearManualCompactionState()    // controller cleared only AFTER we return
   *   _emit(compaction_end)            // internal only
   *   return                           // NO agent_settled on the manual path
   *
   * So pumping SYNCHRONOUSLY inside this handler is unsafe (the controller is
   * still alive, `prompt()` is refused - that was R81-P1, and it was correct),
   * BOUNDED RE-REVIEW F1: this handler is REMOVED. An earlier revision armed a
   * sticky `compactionClosable` flag here so the next settle would release the
   * window, but `markCompactionClosable` was then unregistered, leaving the flag
   * set by nothing and the backstop effectively dead. The settle path still
   * consults the flag (harmlessly), and `closeCompactionWindow` now both marks
   * the window closable and schedules the retained tasks on the real event loop.
   */

  /**
   * Retry the retained tasks shortly, on the REAL event loop.
   *
   * BOUNDED RE-REVIEW F1: a `queueMicrotask` here was WRONG. The runner AWAITS
   * each handler (`dist/core/extensions/runner.js:819`, `await handler(event, ctx)`),
   * and the host clears its compaction controller only after the whole emit
   * resolves (`agent-session.js:2259`). A microtask queued inside the handler is
   * drained BEFORE that awaiting continuation resumes, so it pumped while the
   * controller was still present and the send was refused - exactly the R81-P1
   * loss the deferral was meant to avoid. A microtask cannot express "after the
   * host's await chain has resumed".
   *
   * A timer can. `TASK_BUSY_RETRY_MS` runs on the macrotask queue, so it lands
   * after both the emit and the controller cleanup, and `canAcceptNow()` still
   * guards delivery if some host ordering differs. This reuses the SAME
   * retain-and-retry path `pumpTask` already takes when it cannot accept, so
   * there is one mechanism rather than a second, subtly-different one.
   */
  const pumpRetainedSoon = () => {
    for (const id of [...taskTimers.keys()]) {
      const task = tasks.get(id);
      if (task === undefined || task.sessionId !== currentSessionId) continue;
      if (task.nextRunAtMs > now()) continue; // not due: leave its own timer armed
      // Schedule the actual pump on the next macrotask. This does NOT re-arm a
      // `TASK_BUSY_RETRY_MS` delay: the compaction window has already closed, so
      // the occurrence is deliverable now. Deferring to a macrotask (rather than
      // calling `pumpTask` inline) keeps the call off the emit's synchronous
      // stack - the same boundary F1 requires - while delivering on THIS
      // wake-up instead of waiting out another retry interval.
      clearTaskTimer(id);
      const handle = schedule(() => pumpTask(id, registrationToken), 0);
      taskTimers.set(id, handle);
    }
  };

  /**
   * Close the compaction window at the terminal compaction event.
   *
   * FINAL REVIEW F1: replaces a settle-only release that never fired for a manual
   * `/compact`, because the host emits no `agent_settled` on that path. The window
   * is marked closable here and the retained tasks are SCHEDULED for a retry on
   * the real event loop (`pumpRetainedSoon`), which is the first point after the
   * host's await chain and controller cleanup. An earlier revision used a
   * microtask, which drained too early and was itself unsafe.
   */
  const closeCompactionWindow = () => {
    compactionClosable = true;
    // Clear the flag and schedule the retained tasks on the REAL event loop.
    //
    // The flag is cleared HERE rather than in a queued callback because the host
    // clears its abort controller one statement after this emit resolves
    // (`agent-session.js:2259`). The retry below cannot run until the macrotask
    // queue is reached, which is necessarily after that cleanup, so the window is
    // genuinely closed by the time anything is pumped. `canAcceptNow()` still
    // guards the send, so a host with a different ordering refuses rather than
    // loses the occurrence.
    compacting = false;
    pumpRetainedSoon();
    return undefined;
  };

  /**
   * Re-pump tasks that were RETAINED by the compaction window. Called from
   * `agent_settled`, the first host signal at which a send is genuinely
   * accepted again (Review 79 R79-P1).
   *
   * Review 79 R79-P2: only tasks that are actually DUE are pumped. The previous
   * implementation pumped every timer id, so a task scheduled to run fifteen
   * minutes later could fire immediately after a compaction failed or completed
   * automatically - an early firing that silently violated the schedule. Each
   * task is left to its own timer when it is not yet due.
   */
  const pumpRetainedAfterCompaction = () => {
    for (const id of [...taskTimers.keys()]) {
      const task = tasks.get(id);
      if (task === undefined || task.sessionId !== currentSessionId) continue;
      if (task.nextRunAtMs > now()) continue; // not due yet: leave its timer armed
      pumpTask(id, registrationToken);
    }
  };

  api.on("session_start", handleSessionStart);
  api.on("session_tree", handleSessionTree);
  api.on("session_shutdown", handleSessionShutdown);
  // FEATURE 3: the compaction window. These events are the ONLY production-
  // observable compaction signal available to an extension - there is no
  // `isCompacting` on the API and `ctx.isIdle()` cannot distinguish compaction
  // from streaming. `session_before_compact` opens the window; the two TERMINAL
  // events (`session_compact`, `session_compact_failed`) mark it closable and
  // arm the settle-close in BOTH directions, so a throw or an abort can never
  // leave the scheduler permanently believing compaction is on. NEITHER clears
  // the flag: R81-P1 corrected the boundary, because the host still refuses a
  // send while it awaits the `session_compact` emit.
  api.on("session_before_compact", () => {
    compacting = true;
    compactionClosable = false;
    return undefined;
  });
  api.on("session_compact", closeCompactionWindow);
  api.on("session_compact_failed", closeCompactionWindow);
  api.on("input", resetForInput);
  api.on("before_agent_start", handleBeforeAgentStart);
  api.on("message_start", handleMessageStart);
  api.on("agent_before_settle", handleBeforeSettle);
  api.on("ui_prompt_start", handleAttention);
  api.on("agent_settled", handleSettled);
}

/** Read the session branch, for events that carry no context of their own. */
function projectedFromView(ctx: SupervisorContext | undefined): unknown[] {
  try {
    const projection = ctx?.sessionManager?.buildSessionProjection?.();
    const messages = projection?.messages;
    return Array.isArray(messages) ? messages : [];
  } catch {
    return [];
  }
}

/**
 * Read the persisted session entries, for restoring provenance on reload.
 *
 * Prefers the current BRANCH so a reloaded session recovers only what its own
 * branch records, falling back to the whole entry list when no branch reader
 * exists. A throwing or absent reader yields an empty list, which restores
 * nothing and so can only make a later WAIT unverified.
 */
function readSessionEntries(view: ReadonlySessionView | undefined): unknown[] {
  try {
    if (typeof view?.getBranch === "function") {
      const branch = view.getBranch();
      if (Array.isArray(branch)) return branch;
    }
    if (typeof view?.getEntries === "function") {
      const entries = view.getEntries();
      if (Array.isArray(entries)) return entries;
    }
    return [];
  } catch {
    return [];
  }
}

/**
 * The status declared by the FINAL projected message of a branch, if any.
 *
 * Notification events carry no projection of their own, so the branch comes from
 * the session view. Only the final message may declare, exactly as on the
 * boundary path: walking backward past a textless tail would let an older
 * declaration resurrect itself, so a stale WAIT would suppress notification for
 * a session that is genuinely idle, and a stale CONTINUE would misreport one.
 * A final message with no text declares nothing, which reads as "unknown" and
 * therefore notifies.
 */
function lastAssistantMarker(messages: unknown[]): DeclaredMarker | null {
  const last = messages[messages.length - 1];
  if (last === undefined) return null;
  return readDeclaredMarker(last);
}

/** Pi extension factory (default export). */
export default function sessionSupervisorExtension(pi: SupervisorApi): void {
  registerSessionSupervisor(pi);
}