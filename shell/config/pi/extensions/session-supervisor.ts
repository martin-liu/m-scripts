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
// for one more model request. `agent_settled` cannot return a continuation, but
// it is NOT notification-only: when the session has genuinely gone idle with an
// unfinished declared status, it submits the idle-continue nudge described
// below. Because the marker line leaves the final projected role as `assistant`,
// Pi would refuse a bare `continue: true` (`contextCanContinue =
// hasNonSystemContext && finalRole !== "assistant"`), so a before-settle
// proposal appends a hidden bridge message that restates the declared next step
// and grants NO new authorization.
//
// Idle-continue scope: a settlement is the point at which an idle, unfinished
// session is nudged once (rate-limited by a cooldown) with a static "continue if
// not finished" prompt. The nudge is idempotent by construction, so duplicates
// are acceptable and no exactly-once bookkeeping is kept.


import { createHash } from "node:crypto";
import { closeSync, mkdirSync, openSync, readFileSync, readSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { AFPLAY_PATH, BRIDGE_CUSTOM_TYPE, BRIDGE_HEADER, LONE_STATUS_WORD, MAX_RESULT_ARTIFACT_BYTES, NOTIFICATION_SOUND, OSC_NOTIFY, OSC_NOTIFY_UNVERIFIED_ESCALATION, OSC_NOTIFY_UNVERIFIED_WAIT, PAYLOAD_FREE_STATUSES, PAYLOAD_REQUIRED_STATUSES, PROSE_JOINER, PROTOCOL_LINE, PROVENANCE_CUSTOM_TYPE, QUOTED_STATUS_MENTION_FOR, REPAIR_CUSTOM_TYPE, REPAIR_HEADER, REQUEST_GENERATION_CUSTOM_TYPE, START_FORM_EVENTS, SUBAGENT_RPC_REPLY_PREFIX, SUBAGENT_RPC_REQUEST_TOPIC, SUBAGENT_RPC_VERSION, WAIT_BRIDGE_NOT_READY_RETRIES, WAIT_BRIDGE_NOT_READY_RETRY_MS, WAIT_RECHECK_MS, WAIT_VERIFICATION_MS, resolveMaxContinuations } from "./session-supervisor/protocol.ts";
import type { DeclaredStatus, ReadonlySessionView, SupervisorApi, SupervisorContext, SupervisorHandlerResult, TerminalInputHandler, ToolRegistrationApi } from "./session-supervisor/protocol.ts";

export { AFPLAY_PATH, BRIDGE_CUSTOM_TYPE, BRIDGE_HEADER, DEFAULT_MAX_CONTINUATIONS, HARD_MAX_CONTINUATIONS, NOTIFICATION_SOUND, OSC_NOTIFY, OSC_NOTIFY_UNVERIFIED_ESCALATION, OSC_NOTIFY_UNVERIFIED_WAIT, PROVENANCE_CUSTOM_TYPE, REPAIR_CUSTOM_TYPE, REPAIR_HEADER, REQUEST_GENERATION_CUSTOM_TYPE, SUBAGENT_RPC_READY_TOPIC, SUBAGENT_RPC_REPLY_PREFIX, SUBAGENT_RPC_REQUEST_TOPIC, SUBAGENT_RPC_VERSION, WAIT_BRIDGE_NOT_READY_RETRIES, WAIT_BRIDGE_NOT_READY_RETRY_MS, WAIT_RECHECK_MS, WAIT_VERIFICATION_MS, resolveMaxContinuations, sanitizeOscField } from "./session-supervisor/protocol.ts";
export type { DeclaredStatus, ReadonlySessionView, SupervisorApi, SupervisorContext, SupervisorEventBus, SupervisorHandlerResult, TerminalInputHandler, ToolRegistrationApi } from "./session-supervisor/protocol.ts";
import { markerProblemFor, readDeclaredMarker, isToolCallPart, messageText, finalNonBlankLine, isAssistantMessage, isFenceDecorated, isIndentedCodeLine, protocolLine, declaredStatusOf, countProtocolLines, mentionsQuotedStatus, lineDeclares, isGenuineQueuedWork, MARKER_PROBLEM_NOTICE } from "./session-supervisor/marker.ts";
import { mintLineageToken, sessionUuid, taskOccurrenceEnvelope } from "./session-supervisor/ids.ts";
import { currentRuntimeInstanceId, defaultReadFile, defaultStatSize, isAbsolutePath, readJsonArtifact, readTranscriptTail, runtimeInstanceId, transcriptConfirmsDeliveryEither, worstCaseTaskRowBytes } from "./session-supervisor/transcript.ts";
import type { ObservedRun, ProvenanceRecord, ReadFile } from "./session-supervisor/transcript.ts";
export { sessionUuid, taskOccurrenceEnvelope };

// Re-exported so existing consumers (and the test suite) keep importing these off the
// extension entry point after they moved into `session-supervisor/transcript.ts`.
export { currentRuntimeInstanceId, defaultReadFile, defaultStatSize, isAbsolutePath, readJsonArtifact, readTranscriptTail, setRuntimeInstanceIdForTests, transcriptConfirmsDelivery, transcriptConfirmsDeliveryEither, worstCaseTaskRowBytes, TRANSCRIPT_ROW_WORST_CASE_BYTES_PER_CODE_UNIT, TRANSCRIPT_TAIL_BYTES } from "./session-supervisor/transcript.ts";
export type { ObservedRun, ProvenanceRecord, ReadFile } from "./session-supervisor/transcript.ts";
export { markerProblemFor, readDeclaredMarker, isToolCallPart, messageText, finalNonBlankLine, isAssistantMessage, isFenceDecorated, isIndentedCodeLine, protocolLine, declaredStatusOf, countProtocolLines, mentionsQuotedStatus, lineDeclares, isDocumentationLine, isProseMenu, splitAroundSeparators, MENU_BOUNDARY, isGenuineQueuedWork, MARKER_PROBLEM_NOTICE } from "./session-supervisor/marker.ts";
export type { DeclaredMarker } from "./session-supervisor/marker.ts";
import { lineStructure } from "./session-supervisor/markdown.ts";
export { lineStructure } from "./session-supervisor/markdown.ts";
export type { LineStructure, BlockNode, BlockType } from "./session-supervisor/markdown.ts";

/** The hidden draft appended to make a declared CONTINUE or a repair runnable. */
type BridgeEntry = ReturnType<typeof buildBridgeEntry> | ReturnType<typeof buildRepairEntry>;

import type { ScheduledTask } from "./session-supervisor/tasks.ts";
import {
  TASK_MAX_COUNT,
  advanceDuePast,
  exactIntervalCursor,
  intervalCursorAdvanced,
  mintOccurrenceId,
  mintRegistrationToken,
  parseCancelTaskParams,
  parseTaskSnapshotStrict,
  parseTaskToolParams,
  serializeTaskSnapshot,
  taskFiringPrompt,
  legacyTaskFiringPrompt,
  taskSnapshotKey,
  taskStatus,
  defaultTasksDir,
  taskToolError,
  taskToolResult,
  taskView,
  SCHEDULE_TASK_SCHEMA,
  CANCEL_TASK_SCHEMA,
  LIST_TASKS_SCHEMA,
  SCHEDULE_TASK_DESCRIPTION,
  CANCEL_TASK_DESCRIPTION,
  LIST_TASKS_DESCRIPTION,
} from "./session-supervisor/tasks.ts";
export type { ScheduledTask, SessionTaskSnapshot, ScheduledTaskStatus, TaskView } from "./session-supervisor/tasks.ts";
export {
  TASK_ID_PATTERN,
  TASK_ID_MAX_LENGTH,
  TASK_PROMPT_MAX_BYTES,
  TASK_MAX_COUNT,
  OCCURRENCE_ID_PATTERN,
  taskStatus,
  resolvePiAgentDir,
  defaultTasksDir,
  taskSnapshotKey,
  advanceDuePast,
  intervalCursorAdvanced,
  exactIntervalCursor,
  parseTaskToolParams,
  parseCancelTaskParams,
  validateStoredTask,
  parseTaskSnapshotStrict,
  serializeTaskSnapshot,
  taskFiringPrompt,
  CONTINUATION_INSTRUCTION,
  MARKER_INSTRUCTION,
  legacyTaskFiringPrompt,
  mintOccurrenceId,
  SCHEDULE_TASK_SCHEMA,
  CANCEL_TASK_SCHEMA,
  LIST_TASKS_SCHEMA,
  SCHEDULE_TASK_DESCRIPTION,
  CANCEL_TASK_DESCRIPTION,
  LIST_TASKS_DESCRIPTION,
  taskView,
  taskToolResult,
  taskToolError,
  mintRegistrationToken,
} from "./session-supervisor/tasks.ts";

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
 * True when a raw terminal-input chunk is a conservative INTERRUPT sequence.
 *
 * The installed TUI exposes no queryable binding table, so the only production
 * surface that sees a genuine interrupt is the raw byte stream. The matcher is
 * deliberately CONSERVATIVE and fails closed:
 *
 *   - `\x03` (Ctrl+C) is the canonical interrupt byte, wherever it appears in
 *     the chunk.
 *   - A BARE `\x1b` (Escape) counts ONLY when it is the ENTIRE chunk, so an
 *     arrow-key / Alt sequence (`\x1b[A`) or a partial escape never sets the
 *     latch.
 *
 * Remap support is NOT attempted: without a binding table there is nothing to
 * remap against, and guessing would risk latching a stop on ordinary input.
 * Conservative false-NEGATIVES are the safe direction - they merely leave the
 * latch unset, so the cooldown still bounds nudging.
 */
export function terminalInputMatchesInterrupt(data: unknown): boolean {
  if (typeof data !== "string" || data.length === 0) return false;
  if (data.includes("\x03")) return true;
  return data === "\x1b";
}

/**
 * The ONLY rate limit the idle auto-continue uses: a cooldown between nudges.
 *
 * This is deliberately NOT a one-shot tombstone. After the cooldown a session
 * that still declares unfinished work is nudged AGAIN - the design relies on the
 * nudge being idempotent by construction (it says "continue if not finished"),
 * so duplicates are harmless and self-correcting. Exactly-once machinery is
 * explicitly out of scope.
 */
export const IDLE_NUDGE_COOLDOWN_MS = 60_000;

/**
 * Hidden session-entry type recording the last idle nudge for a session.
 *
 * It persists ONLY `{ sessionId, nudgedAt }` so a reload can restore the
 * cooldown. Custom entries are filtered out of the model context, so this is
 * invisible to the model. A missing or malformed entry simply permits a nudge.
 */
export const IDLE_NUDGE_CUSTOM_TYPE = "session-supervisor:idle-nudge:v1";

/**
 * The static idle-continue nudge. Nothing is substituted into it.
 *
 * It is idempotent BY CONSTRUCTION: a nudge that lands on finished work instructs
 * the agent to report completion without repeating any tool action, so a
 * duplicate delivery cannot cause harm - which is exactly why no attempt ledger
 * or exactly-once guard exists. The text also grants no new authorization and
 * preserves user abort/steering precedence.
 */
export const IDLE_CONTINUE_PROMPT = [
  "[session-supervisor:idle-continue]",
  "",
  "You appear to be idle with unfinished work (your last declared status was not DONE, BLOCKED, or FAILED).",
  "",
  "Continue if not finished. This is an automatic nudge, not a new task.",
  "",
  "Reconcile the current objective and todo state, then continue only the unfinished, already-authorized work. If everything is already finished, do not repeat any tool action - report completion with STATUS:DONE.",
  "",
  "Before any non-idempotent action, establish from authoritative state that it has not already occurred. If uncertain, inspect rather than repeat.",
  "",
  "Respect user abort and steering, existing scope, permissions, and approvals. This message grants NO new authorization.",
  "",
  "End your final message with the applicable final, column-zero STATUS line after a blank line.",
].join("\n");

/**
 * Declared statuses for which a nudge is NOT sent.
 *
 * `blocked`/`done`/`failed` are terminal or user-gated outcomes, and `unknown`
 * (no marker / malformed) must never nudge without a POSITIVE declaration. Every
 * OTHER status - including `continue` and `wait` - is unfinished work and is
 * nudged. `disabled` is not a grammar status and never reaches here.
 */
const IDLE_NUDGE_EXCLUDED_STATUSES: ReadonlySet<string> = new Set(["blocked", "done", "failed", "unknown"]);




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
import {
  parseWakeProof,
  parseBlockedDeclaration,
  humanWaitingLeadingClause,
  parseUserInputAssessment,
  userQuestionLines,
} from "./session-supervisor/wake.ts";
export type { WakeProof, BlockedDeclaration, UserInputAssessment } from "./session-supervisor/wake.ts";
export {
  parseWakeProof,
  parseBlockedDeclaration,
  humanWaitingLeadingClause,
  parseUserInputAssessment,
  userQuestionLines,
} from "./session-supervisor/wake.ts";

import {
  readObservedRunEvidence,
  parseProvenanceRecord,
  restoreProvenance,
  currentLineageGeneration,
  latestPersistedGeneration,
  provenanceBelongsToCurrentGeneration,
  waitEventIsTerminal,
  waitEventIsStartForm,
  LEGACY_NO_LINEAGE_SENTINEL,
} from "./session-supervisor/provenance.ts";
export type { ObservedRunEvidence, ProvenanceIndex, CurrentLineageGeneration } from "./session-supervisor/provenance.ts";
export {
  readObservedRunEvidence,
  parseProvenanceRecord,
  restoreProvenance,
  currentLineageGeneration,
  latestPersistedGeneration,
  provenanceBelongsToCurrentGeneration,
  waitEventIsTerminal,
  waitEventIsStartForm,
  LEGACY_NO_LINEAGE_SENTINEL,
} from "./session-supervisor/provenance.ts";

import {
  rpcReplyProvesCurrentOwner,
  rpcReplyIsBridgeNotReady,
  sessionIdentity,
  sessionTranscriptPath,
  replyProvesWake,
  ownerStateIsTerminal,
} from "./session-supervisor/rpc-verify.ts";
export { rpcReplyProvesCurrentOwner, rpcReplyIsBridgeNotReady } from "./session-supervisor/rpc-verify.ts";

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
     * DIRECTORY of per-session scheduled-task snapshots (FEATURE 3). Defaults to
     * the resolved Pi agent dir's `session-supervisor/tasks`; tests inject a temp
     * directory so no fixture touches the real store. Each session's snapshot is
     * derived from its identity, so a single-path override would undermine the
     * ownership contract and is deliberately not offered.
     */
    tasksDir?: string;
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
  const tasksDir = env.tasksDir ?? defaultTasksDir();
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

  // --- Idle auto-continue (SIMPLE poll-and-nudge) --------------------------
  //
  // A genuinely-idle session whose last declared status is not DONE/BLOCKED/
  // FAILED gets ONE static "continue if not finished" nudge. The nudge is
  // idempotent by construction and duplicates are ACCEPTABLE, so there is NO
  // attempt ledger, NO generation fence, and NO per-run verification here - just
  // a cooldown that bounds how often a still-unfinished session is nudged.
  //
  // User-stop latch: set by a conservative raw-interrupt observation and cleared
  // ONLY by a genuine new interactive/rpc request. It blocks nudging so an
  // automatic nudge can never override a user's stop.
  let userStopLatched = false;
  // Cooldown marker: the last nudge's wall-clock time (`Date.now()`) and the
  // session it was for. The clock is NOT monotonic, so a system clock adjustment
  // can lengthen or shorten the cooldown; that only affects how soon a still-
  // unfinished session is nudged again, never whether it can be. Restored
  // best-effort from a durable entry on a same-session reload.
  let lastIdleNudgeAt = 0;
  let idleNudgeSession = "";
  // The installed raw terminal-input observer and its host-returned disposer, so
  // a shutdown/session-replacement can DROP the listener rather than leak it.
  let terminalInputHandler: TerminalInputHandler | null = null;
  let terminalInputDisposer: (() => void) | null = null;
  let terminalInputSurface: object | null = null;

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

  // --- Subagent-idleness evidence ------------------------------------------
  // "Real idle" needs BOTH the main agent idle AND no child still running, and
  // the second half is only knowable from lifecycle evidence. `observationTopicsReady`
  // records that both START/terminal subscriptions were actually installed. When it
  // is false the inventory is not usable, and because "unknown" must never become
  // "idle", the idle gate refuses to nudge. See `subagentsKnownIdle`.
  let observationTopicsReady = false;

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
  // `tasks` mirrors the CURRENT owner session's snapshot; `taskTimers` holds the
  // one armed callback per UNCLAIMED task id. `registrationToken` is the
  // TRANSIENT fence: minted fresh per registration, captured by each armed
  // callback, and re-checked against this live value IMMEDIATELY before
  // submission, so a callback armed under a superseded registration can never
  // deliver. `currentSessionId` tracks the live session (updated by the lifecycle
  // handlers) so a reminder whose owner is not the active session is RETAINED
  // rather than fired into the wrong session.
  //
  // STORAGE OWNERSHIP: `ownedStore` is set once the active registration has
  // ACQUIRED the per-session lock. It carries the exact authoritative bytes last
  // observed, so a mutation can detect an UNEXPECTED change and stop rather than
  // merge or overwrite. A crashed owner's lock intentionally blocks automation;
  // there is no automatic stale-lock reclamation.
  interface OwnedTaskStore {
    sessionId: string;
    snapshotPath: string;
    lockPath: string;
    ownerToken: string;
    /** The exact authoritative snapshot bytes last observed (UTF-8 string). */
    bytes: string;
  }
  let tasks = new Map<string, ScheduledTask>();
  const taskTimers = new Map<string, unknown>();
  let ownedStore: OwnedTaskStore | null = null;
  /** Why task automation is currently unavailable for the active session. */
  let ownershipState: "active" | "no_session" | "store_locked" | "store_owner_lost" | "store_unreadable" | "store_invalid" =
    "no_session";
  // True between `session_before_compact` and the send-ready boundary. The host
  // exposes no compaction predicate to extensions, so the EVENT PAIR is the only
  // production-observable signal. Cleared only after the terminal compaction
  // event's handler returns AND the host has cleared its own abort controller.
  let compacting = false;
  let registrationToken = mintRegistrationToken();
  let currentSessionId = "";
  // The persisted session transcript path for the CURRENT session. Positive
  // reconciliation reads it because the commit point is the PERSISTED transcript,
  // not an event. Empty means "no transcript to read", in which case a claim is
  // never reconciled and stays inert.
  let currentSessionFile = "";

/**
   * Whether the host can currently ACCEPT an injected user message.
   *
   * Pi THROWS on a send while compacting, before it inspects the delivery mode
   * (`agent-session.js:1534-1535`), and the host swallows that rejection
   * internally (`:2711-2718` emits an error and discards it). The correct signal
   * is the compaction EVENT PAIR, which the host does expose. This predicate only
   * DEFERS a pointless attempt while compaction is observably in flight; a wrong
   * prediction costs a delayed attempt, never a lost occurrence.
   */
  const canAcceptNow = (): boolean => !compacting;

  /** The per-session snapshot path within the tasks directory. */
  const snapshotPathFor = (sessionId: string): string =>
    join(tasksDir, `${taskSnapshotKey(sessionId)}.json`);

  /** The per-session ownership lock path. */
  const lockPathFor = (sessionId: string): string => `${snapshotPathFor(sessionId)}.lock`;

  /**
   * Read the authoritative snapshot bytes for the active owner, or null when the
   * file is confirmed ABSENT. Any other error returns `undefined` (unreadable),
   * which callers treat as fail-closed - never as an authoritative empty store.
   * Uses the plain filesystem reader, NOT the artifact-capped `readFile`.
   */
  const readSnapshotBytes = (path: string): string | null | undefined => {
    try {
      return readFileSync(path, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      return undefined;
    }
  };

  /**
   * Acquire the ownership lock for a session. Uses exclusive creation (`wx`) so
   * a second owner fails closed rather than sharing the snapshot. An existing
   * lock is NEVER automatically reclaimed.
   */
  const acquireOwnership = (sessionId: string):
    | { ok: true; store: OwnedTaskStore }
    | { ok: false; code: "store_locked" | "store_unreadable" | "store_invalid" } => {
    const snapshotPath = snapshotPathFor(sessionId);
    const lockPath = lockPathFor(sessionId);
    const ownerToken = mintRegistrationToken();
    try {
      mkdirSync(tasksDir, { recursive: true });
    } catch {
      return { ok: false, code: "store_locked" };
    }
    try {
      const fd = openSync(lockPath, "wx", 0o600);
      try {
        writeFileSync(fd, JSON.stringify({ version: 1, ownerToken }));
      } finally {
        closeSync(fd);
      }
    } catch {
      // An existing lock (or an unwritable directory) blocks ownership.
      return { ok: false, code: "store_locked" };
    }
    // Establish the last-authoritative bytes: absent => the canonical empty
    // snapshot serialization; unreadable/invalid => do not claim ownership.
    const raw = readSnapshotBytes(snapshotPath);
    if (raw === undefined) {
      releaseOwnership({ sessionId, snapshotPath, lockPath, ownerToken, bytes: "" });
      return { ok: false, code: "store_unreadable" };
    }
    let bytes: string;
    if (raw === null) {
      bytes = serializeTaskSnapshot({ version: 2, sessionId, tasks: [] });
    } else {
      const snapshot = parseTaskSnapshotStrict(raw, sessionId);
      if (snapshot === null) {
        // An existing but invalid snapshot is NOT adopted; ownership is released
        // so the store is left byte-identical.
        releaseOwnership({ sessionId, snapshotPath, lockPath, ownerToken, bytes: "" });
        return { ok: false, code: "store_invalid" };
      }
      bytes = raw;
    }
    return { ok: true, store: { sessionId, snapshotPath, lockPath, ownerToken, bytes } };
  };

  /** Release an ownership lock ONLY when this registration still owns it. */
  const releaseOwnership = (store: OwnedTaskStore | null) => {
    if (store === null) return;
    try {
      const raw = readFileSync(store.lockPath, "utf8");
      const parsed = JSON.parse(raw) as { ownerToken?: unknown };
      if (parsed !== null && typeof parsed === "object" && parsed.ownerToken === store.ownerToken) {
        unlinkSync(store.lockPath);
      }
    } catch {
      // Best-effort only: a missing or foreign lock is left untouched.
    }
  };

  /**
   * Persist the in-memory tasks for the owned session. Returns a discriminated
   * result so callers can map a failure to the right tool error code.
   *
   * The write boundary is deliberately strict:
   *   * no ownership => `store_owner_lost`;
   *   * a concurrent lock that no longer names us => `store_owner_lost`;
   *   * an UNEXPECTED authoritative-byte change => `store_changed` (pause, never
   *     merge or overwrite);
   *   * a read/parse failure => `store_unreadable` / `store_invalid`;
   *   * a write/rename failure => `store_write_failed` (bytes preserved).
   */
  const persistSnapshot = (): { ok: true } | { ok: false; code: string; message: string } => {
    // A FAILED reconcile marks the store unreadable to stop ALL mutation until a
    // successful reload lands. Ownership may still survive that failure, so this
    // state must be checked HERE and not only in `requireOwnership`: otherwise a
    // tool write would overwrite the intact snapshot from a stale in-memory map.
    if (ownershipState === "store_unreadable") {
      return { ok: false, code: "store_unreadable", message: "the task store could not be read" };
    }
    const store = ownedStore;
    if (store === null || store.sessionId !== currentSessionId) {
      return { ok: false, code: "store_owner_lost", message: "this registration no longer owns the task store" };
    }
    // Verify ownership is still ours.
    try {
      const rawLock = readFileSync(store.lockPath, "utf8");
      const parsed = JSON.parse(rawLock) as { ownerToken?: unknown };
      if (parsed === null || typeof parsed !== "object" || parsed.ownerToken !== store.ownerToken) {
        return { ok: false, code: "store_owner_lost", message: "the task store lock is held by another owner" };
      }
    } catch {
      return { ok: false, code: "store_owner_lost", message: "the task store lock could not be verified" };
    }
    // Re-read and compare to the last authoritative bytes.
    const raw = readSnapshotBytes(store.snapshotPath);
    if (raw === undefined) {
      return { ok: false, code: "store_unreadable", message: "the task store could not be read" };
    }
    const currentBytes = raw === null ? serializeTaskSnapshot({ version: 2, sessionId: store.sessionId, tasks: [] }) : raw;
    if (currentBytes !== store.bytes) {
      const snapshot = raw === null ? null : parseTaskSnapshotStrict(raw, store.sessionId);
      if (raw !== null && snapshot === null) {
        return { ok: false, code: "store_invalid", message: "the task store is not a valid snapshot" };
      }
      return { ok: false, code: "store_changed", message: "the task store changed unexpectedly" };
    }
    const tasksList = [...tasks.values()];
    const serialized = serializeTaskSnapshot({ version: 2, sessionId: store.sessionId, tasks: tasksList });
    const tmp = `${store.snapshotPath}.tmp-${process.pid}-${mintOccurrenceId().slice(3, 11)}`;
    try {
      writeFileSync(tmp, serialized);
      renameSync(tmp, store.snapshotPath);
    } catch {
      try {
        unlinkSync(tmp);
      } catch {
        // best-effort only
      }
      return { ok: false, code: "store_write_failed", message: "the task store could not be written" };
    }
    store.bytes = serialized;
    return { ok: true };
  };

  /** Load the owned session's snapshot into memory, fail-closed. */
  const loadOwnedSnapshot = (store: OwnedTaskStore): { ok: true; tasks: ScheduledTask[] } | { ok: false; code: string; message: string } => {
    const raw = readSnapshotBytes(store.snapshotPath);
    if (raw === undefined) {
      return { ok: false, code: "store_unreadable", message: "the task store could not be read" };
    }
    if (raw === null) {
      store.bytes = serializeTaskSnapshot({ version: 2, sessionId: store.sessionId, tasks: [] });
      return { ok: true, tasks: [] };
    }
    const snapshot = parseTaskSnapshotStrict(raw, store.sessionId);
    if (snapshot === null) {
      return { ok: false, code: "store_invalid", message: "the task store is not a valid snapshot" };
    }
    store.bytes = raw;
    return { ok: true, tasks: snapshot.tasks };
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

  /** Cancel every armed task timer. */
  const clearAllTaskTimers = () => {
    for (const handle of taskTimers.values()) {
      try {
        cancelScheduled(handle);
      } catch {
        // best-effort only
      }
    }
    taskTimers.clear();
  };

  /**
   * Longest delay `setTimeout` can represent.
   *
   * A delay above 2^31-1 ms does not merely saturate: Node emits
   * `TimeoutOverflowWarning` and clamps the timer to **1 ms**. The clamp is
   * therefore paired with the due-time re-check in `pumpTask`: a horizon longer
   * than this re-arms in bounded hops instead of firing early.
   */
  const MAX_TIMER_DELAY_MS = 2147483647;

  /**
   * Whether a task is automatically eligible: it is owned by the current session,
   * DUE, and UNCLAIMED. The structural invariant is the `occurrenceId` check -
   * this SAME predicate is used by arming and pumping.
   */
  const taskEligible = (task: ScheduledTask): boolean =>
    task.occurrenceId === undefined;

  /** Arm one UNCLAIMED task's callback against the CURRENT registration fence. */
  const armTask = (task: ScheduledTask) => {
    if (!taskEligible(task)) {
      // A claimed occurrence is never automatically eligible: disarm only.
      clearTaskTimer(task.id);
      return;
    }
    clearTaskTimer(task.id);
    const token = registrationToken;
    const delay = Math.min(MAX_TIMER_DELAY_MS, Math.max(0, task.nextRunAtMs - now()));
    const handle = schedule(() => pumpTask(task.id, token), delay);
    taskTimers.set(task.id, handle);
  };

  /** Arm every UNCLAIMED task in memory (ownership already scoped to it). */
  const armCurrentSessionTasks = () => {
    for (const task of tasks.values()) armTask(task);
  };

  /**
   * Fire one due task, if it is still eligible. The transient fence is re-checked
   * here, IMMEDIATELY before submission. An UNCLAIMED due occurrence is CLAIMED
   * and PERSISTED before the send, with NO await between the final eligibility
   * check, the claim write, and the submission.
   */
  const pumpTask = (id: string, token: string) => {
    if (token !== registrationToken) return;
    const task = tasks.get(id);
    if (task === undefined) return;
    // STRUCTURAL INVARIANT: a claimed occurrence is never automatically eligible.
    if (!taskEligible(task)) {
      clearTaskTimer(id);
      return;
    }
    // DUE-TIME RE-CHECK: a capped wake must re-arm rather than deliver early.
    if (task.nextRunAtMs > now()) {
      armTask(task);
      return;
    }
    if (typeof api.sendUserMessage !== "function") {
      clearTaskTimer(id);
      return;
    }
    if (!canAcceptNow()) {
      // Host cannot accept a send right now (compaction). The occurrence stays
      // DUE and UNCLAIMED, so it is not lost - it is simply not sent yet.
      //
      // STRUCTURAL INVARIANT (no polling): disarm and DO NOT re-arm a timer.
      // A `schedule(() => pumpTask(...), 0)` here would re-run on the very next
      // macrotask; while compaction persists every pass re-schedules another
      // zero-delay callback, which is unbounded busy-polling and violates the
      // contract's "one callback ... no idle/busy polling". The window is closed
      // by `closeCompactionWindow`, whose fenced readiness check calls
      // `reconcileAndArm()`, which pumps every DUE UNCLAIMED task exactly once.
      // So the delivery path is preserved by event-driven reopen alone, with no
      // timer and therefore no polling.
      clearTaskTimer(id);
      return;
    }

    // CLAIM-BEFORE-SEND. Synchronously: mint the claim, verify ownership and
    // unchanged bytes, WRITE the claim, publish it, disarm the firing timer, and
    // ONLY THEN submit. No await anywhere in this span.
    const previousOccurrence = task.occurrenceId;
    task.occurrenceId = mintOccurrenceId();
    const persisted = persistSnapshot();
    if (!persisted.ok) {
      // The claim did not land. Restore the exact pre-claim state (which was
      // unclaimed by the eligibility check above) and retry later - nothing was
      // sent, so no claim needs clearing.
      task.occurrenceId = previousOccurrence;
      clearTaskTimer(id);
      const handle = schedule(() => pumpTask(id, token), TASK_PUMP_RETRY_MS);
      taskTimers.set(id, handle);
      return;
    }
    clearTaskTimer(id);
    // SUBMIT exactly once. The claim is already durable, so a throw/rejection here
    // can only ever pause the occurrence, never re-enable it.
    try {
      api.sendUserMessage(taskFiringPrompt(task), { deliverAs: "followUp" });
    } catch {
      // A synchronous throw is an observable refusal; the claim STANDS.
    }
    // The occurrence is now inert. It is reconciled ONLY by positive transcript
    // evidence on a later settlement or lifecycle event, never by a timer.
  };

  /** Map an extension error code and message into a tool failure result. */
  const toolError = (code: string, message: string) =>
    taskToolError(code, message);

  /** Guard shared by every tool: refuse with the precise reason automation is off. */
  const requireOwnership = () => {
    if (ownedStore !== null && ownedStore.sessionId === currentSessionId) return null;
    if (ownershipState === "store_locked") return toolError("store_locked", "the task store is owned by another registration");
    if (ownershipState === "store_unreadable") return toolError("store_unreadable", "the task store could not be read");
    if (ownershipState === "store_invalid") return toolError("store_invalid", "the task store is not a valid snapshot");
    if (ownershipState === "store_owner_lost") return toolError("store_owner_lost", "this registration no longer owns the task store");
    return toolError("session_unavailable", "no active Pi session owns the task store");
  };

  /**
   * Reconcile CLAIMED occurrences against POSITIVE transcript evidence. Only a
   * persisted `role: "user"` row carrying the COMPLETE generated firing prompt
   * settles a claim:
   * a one-shot is durably removed; an interval advances to a safe future cursor
   * (computed exactly) and is persisted WITHOUT the old claim, then re-armed.
   * A failed persistence pauses automation; there is no retry loop or resend.
   */
  const reconcileClaims = () => {
    const store = ownedStore;
    if (store === null || store.sessionId !== currentSessionId) return;
    if (currentSessionFile.length === 0) return;
    const tail = readTranscriptTail(currentSessionFile);
    let changed = false;
    for (const task of [...tasks.values()]) {
      if (task.occurrenceId === undefined) continue;
      const expectedPrompt = taskFiringPrompt(task);
      const legacyPrompt = legacyTaskFiringPrompt(task);
      if (!transcriptConfirmsDeliveryEither(tail, expectedPrompt, legacyPrompt)) continue;
      if (task.intervalMs !== undefined) {
        const advanced = advanceDuePast(task.intervalMs, task.nextRunAtMs, now());
        // `advanced` is only usable when it is the EXACT cursor. `advanceDuePast`
        // signals overflow by returning `nowMs`, which can satisfy
        // `advanced > nextRunAtMs` while being no advance at all.
        const exact = exactIntervalCursor(task.intervalMs, task.nextRunAtMs, now());
        if (exact === null || !intervalCursorAdvanced(advanced, task.nextRunAtMs) || advanced !== exact) {
          // Could not safely complete the arithmetic: keep the claim.
          continue;
        }
        task.nextRunAtMs = advanced;
        delete task.occurrenceId;
      } else {
        tasks.delete(task.id);
      }
      changed = true;
    }
    if (!changed) return;
    const persisted = persistSnapshot();
    if (!persisted.ok) {
      // Reconciliation could not land: the authoritative bytes could not be
      // rewritten FROM MEMORY. Do NOT adopt whatever is now on disk: an
      // unexpected valid-byte change is precisely the case the cut-off rule
      // covers (`store_changed`), and adopting it would let an externally
      // introduced due reminder be armed and submitted on the next arm pass.
      // Keep the last known in-memory state, stop mutating, and mark the store
      // unreadable so no tool writes over the snapshot until a reload lands.
      //
      // A FAILED reload must not blank the map either: replacing a known-good
      // state with `new Map()` made list_tasks report nothing and let a later
      // schedule overwrite the intact on-disk snapshot, silently deleting
      // unrelated reminders (including unaccepted claims).
      clearAllTaskTimers();
      ownershipState = "store_unreadable";
      return;
    }
    armCurrentSessionTasks();
  };

  /** Small bounded retry for a pump that could not claim (write blocked). */
  const TASK_PUMP_RETRY_MS = 1000;

  /** The `schedule_task` tool. */
  const scheduleTaskTool = (args: unknown) => {
    const guard = requireOwnership();
    if (guard !== null) return guard;
    const parsed = parseTaskToolParams(args);
    if ("error" in parsed) return toolError(parsed.error, parsed.message);
    if (tasks.has(parsed.id)) {
      return toolError("task_exists", `a reminder with id ${JSON.stringify(parsed.id)} already exists`);
    }
    if (tasks.size >= TASK_MAX_COUNT) {
      return toolError(
        "task_limit",
        `the session already holds ${TASK_MAX_COUNT} reminders; cancel one before scheduling another`,
      );
    }
    const due = now() + parsed.delayMs;
    if (!Number.isSafeInteger(due)) {
      return toolError("time_overflow", "the computed due time is outside the safe integer range");
    }
    const task: ScheduledTask = {
      id: parsed.id,
      prompt: parsed.prompt,
      nextRunAtMs: due,
    };
    if (parsed.intervalMs !== undefined) task.intervalMs = parsed.intervalMs;
    tasks.set(task.id, task);
    const persisted = persistSnapshot();
    if (!persisted.ok) {
      tasks.delete(task.id);
      return toolError(persisted.code, persisted.message);
    }
    // Only now publish the in-memory record and arm its timer.
    armTask(task);
    return taskToolResult({ status: "scheduled", task: taskView(task) });
  };

  /** The `cancel_task` tool. */
  const cancelTaskTool = (args: unknown) => {
    const guard = requireOwnership();
    if (guard !== null) return guard;
    const parsed = parseCancelTaskParams(args);
    if ("error" in parsed) return toolError(parsed.error, parsed.message);
    const task = tasks.get(parsed.id);
    if (task === undefined) {
      return taskToolResult({ status: "not_found", id: parsed.id });
    }
    const previousStatus = taskStatus(task);
    // Persist BEFORE disarming the timer. Cancelling first and restoring only the
    // record on failure left a surviving task listed as scheduled with a dead
    // timer, so a transient write failure silently disarmed a live reminder.
    tasks.delete(parsed.id);
    const persisted = persistSnapshot();
    if (!persisted.ok) {
      // The deletion did not land: restore memory to the authoritative state and
      // keep the timer armed exactly as it was.
      tasks.set(task.id, task);
      return toolError(persisted.code, persisted.message);
    }
    clearTaskTimer(parsed.id);
    return taskToolResult({ status: "cancelled", id: parsed.id, previousStatus });
  };

  /** The `list_tasks` tool. Read-only: it never reconciles or reactivates. */
  const listTasksTool = (args: unknown) => {
    const guard = requireOwnership();
    if (guard !== null) return guard;
    if (args !== null && (typeof args !== "object" || Array.isArray(args))) {
      return toolError("invalid_arguments", "arguments must be an object");
    }
    if (args !== null && typeof args === "object") {
      for (const key of Object.keys(args)) {
        return toolError("invalid_arguments", `unknown argument ${JSON.stringify(key)}`);
      }
    }
    const views = [...tasks.values()]
      .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
      .map(taskView);
    return taskToolResult({ status: "listed", tasks: views });
  };

  /**
   * Reconcile claims against positive evidence, then SUBMIT every due UNCLAIMED
   * reminder owned by the current session. This is the settlement boundary's
   * action: the claim arm handles uncertainty (never a submission), the pump arm
   * handles eligible work. It never arms a retry loop.
   */
  const reconcileAndArm = () => {
    reconcileClaims();
    for (const task of [...tasks.values()]) {
      if (task.occurrenceId !== undefined) continue; // claimed: never automatically eligible
      if (task.nextRunAtMs > now()) continue; // not due: leave its own timer armed
      pumpTask(task.id, registrationToken);
    }
  };

  /**
   * Register the three `direct` scheduler tools ONCE per factory invocation.
   *
   * A host without `registerTool` registers nothing (the scheduler stays inert),
   * which is the safe degradation for a minimal host. There is no active-set
   * toggling, unregister workaround, or `terminate`.
   */
  const registerTaskTools = () => {
    const register = (api as ToolRegistrationApi).registerTool;
    if (typeof register !== "function") return;
    register({
      name: "schedule_task",
      description: SCHEDULE_TASK_DESCRIPTION,
      parameters: SCHEDULE_TASK_SCHEMA,
      exposure: "direct",
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
      execute: (_toolCallId: unknown, args: unknown) => scheduleTaskTool(args),
    });
    register({
      name: "cancel_task",
      description: CANCEL_TASK_DESCRIPTION,
      parameters: CANCEL_TASK_SCHEMA,
      exposure: "direct",
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
      execute: (_toolCallId: unknown, args: unknown) => cancelTaskTool(args),
    });
    register({
      name: "list_tasks",
      description: LIST_TASKS_DESCRIPTION,
      parameters: LIST_TASKS_SCHEMA,
      exposure: "direct",
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      execute: (_toolCallId: unknown, args: unknown) => listTasksTool(args),
    });
  };
  registerTaskTools();

  /**
   * Activate a session: acquire ownership, strictly load its snapshot, and arm
   * its UNCLAIMED reminders. Claimed occurrences are restored INERT. A failure to
   * acquire or load leaves the scheduler inert (no automation) rather than
   * running over an unowned or unreadable store.
   */
  const noteSession = (ctx: SupervisorContext) => {
    const identity = sessionIdentity(ctx);
    if (identity.length === 0) return;
    if (identity === currentSessionId && ownedStore !== null) return;
    // Leave the previous session's ownership and timers behind.
    clearAllTaskTimers();
    releaseOwnership(ownedStore);
    ownedStore = null;
    tasks = new Map();
    currentSessionId = identity;
    currentSessionFile = sessionTranscriptPath(ctx);
    const acquired = acquireOwnership(identity);
    if (!acquired.ok) {
      ownershipState = acquired.code;
      return;
    }
    ownedStore = acquired.store;
    const loaded = loadOwnedSnapshot(acquired.store);
    if (!loaded.ok) {
      // Fail closed: an unreadable/invalid snapshot pauses automation.
      releaseOwnership(acquired.store);
      ownedStore = null;
      ownershipState = loaded.code === "store_invalid" ? "store_invalid" : "store_unreadable";
      return;
    }
    ownershipState = "active";
    tasks = new Map();
    for (const task of loaded.tasks) tasks.set(task.id, task);
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
   *
   * `observationTopicsReady` records that BOTH subscriptions were installed. The
   * idle gate depends on it: without a working ledger we cannot prove any
   * subagent is idle, and "unknown" must mean "do not nudge". Checking only
   * whether `api.events.on` EXISTS would miss a subscriber that throws, so the
   * flag is set from the actual subscribe attempts.
   */
  const observeRunEvents = () => {
    const bus = api.events;
    if (bus === undefined || typeof bus.on !== "function") return;
    let installed = 0;
    for (const topic of [OBSERVED_RUN_START_TOPIC, OBSERVED_RUN_TERMINAL_TOPIC]) {
      try {
        bus.on(topic, (event: unknown) => {
          if (topic === OBSERVED_RUN_START_TOPIC) observeStart(event);
          else observeTerminal(event);
        });
        installed += 1;
      } catch {
        // A bus that refuses a subscription cannot attest anything, so the
        // ledger is not usable and the idle gate must fail closed.
      }
    }
    if (installed === 2) observationTopicsReady = true;
  };

  /**
   * True only when the host reports an idle agent; unknown means not idle.
   *
   * This is the MAIN agent's idleness ONLY. It says nothing about subagents: a
   * settle while a child still runs reports `true` here. See
   * `subagentsKnownIdle` for the other half of "real idle".
   */
  const isIdle = (ctx: SupervisorContext): boolean => {
    try {
      return ctx?.isIdle?.() === true;
    } catch {
      return false;
    }
  };

  /**
   * Play the notification sound, best-effort, on macOS only.
   *
   * A notification the user cannot hear is the failure this exists to fix, but
   * audio is never allowed to become the thing that can break notification: it
   * cannot throw, cannot be awaited, cannot print, and cannot retry. Playback is
   * dispatched and forgotten exactly like the pane flag, and it does NOT depend
   * on Zellij, a pane id, or successful stdout delivery - the sound must fire in
   * any TUI session, paned or not.
   *
   * Guarded by `process.platform` because `afplay` is macOS-only; on any other
   * platform this is a no-op rather than a spawn that fails every settle. A
   * `fulfilled` result with a nonzero `code` is ignored: the attempt is already
   * made, and one failed playback must not become a retry storm.
   */
  const playNotificationSound = () => {
    if (process.platform !== "darwin") return;
    const exec = api.exec;
    if (typeof exec !== "function") return;
    try {
      void Promise.resolve(exec(AFPLAY_PATH, [NOTIFICATION_SOUND])).catch(() => {
        // best-effort only: a rejected spawn must not surface
      });
    } catch {
      // best-effort only: a synchronously throwing exec must not escape
    }
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

    // BEFORE the pane check below: the sound must fire in any TUI session, not
    // only inside Zellij, so it must not sit behind the empty-pane `return`.
    playNotificationSound();

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

  // --- Idle auto-continue (SIMPLE poll-and-nudge) --------------------------

  /**
   * Set the user-stop latch from a raw interrupt observation.
   *
   * Set SYNCHRONOUSLY so the next settlement observes it, and cleared ONLY by a
   * genuine new interactive/rpc request (`resetForInput`). An automatic nudge is
   * NOT genuine input, so a nudge cannot clear its own block.
   */
  const latchUserStop = () => {
    userStopLatched = true;
  };

  /**
   * Bind the raw terminal-input observer for interrupt detection.
   *
   * The real `ExtensionUIContext` exposes no queryable binding table, so only the
   * raw byte stream sees a genuine interrupt. The listener is OBSERVATIONAL - it
   * returns `undefined` so the bytes are never consumed or rewritten - and
   * matches only the conservative interrupt set. A host without the surface, or
   * one whose install throws, leaves NO listener: an unobservable interrupt
   * simply does not latch, and the cooldown still bounds nudging.
   *
   * Only installed once per live UI surface: a re-install on the SAME surface
   * would double-register the observer, while a rebind on a DIFFERENT surface
   * first drops the old listener so the observer never outlives its surface.
   */
  const bindTerminalAbortListener = (ctx: SupervisorContext) => {
    const ui = ctx?.ui;
    if (ui === null || ui === undefined || typeof ui.onTerminalInput !== "function") {
      if (terminalInputDisposer !== null || terminalInputHandler !== null) unbindTerminalAbortListener();
      return;
    }
    if (terminalInputSurface === ui && terminalInputHandler !== null) return;
    if (terminalInputHandler !== null) unbindTerminalAbortListener();
    const handler: TerminalInputHandler = (data: string) => {
      if (terminalInputMatchesInterrupt(data)) latchUserStop();
      // Observational only: leave the input COMPLETELY untouched.
      return undefined;
    };
    try {
      const returned = ui.onTerminalInput(handler);
      terminalInputHandler = handler;
      // RETAIN the host's unsubscribe disposer (the installed host returns one).
      terminalInputDisposer = typeof returned === "function" ? (returned as () => void) : null;
      terminalInputSurface = ui;
    } catch {
      // A host that refuses the listener leaves NO observer (fails closed).
      terminalInputHandler = null;
      terminalInputDisposer = null;
      terminalInputSurface = null;
    }
  };

  /**
   * Drop the raw terminal-input observer on shutdown/session replacement.
   *
   * The host RETURNS an unsubscribe function, so the listener is genuinely
   * REMOVED by invoking it; merely clearing the local reference would leak one
   * observer per torn-down surface. A throwing disposer is swallowed.
   */
  const unbindTerminalAbortListener = () => {
    const disposer = terminalInputDisposer;
    terminalInputHandler = null;
    terminalInputDisposer = null;
    terminalInputSurface = null;
    if (disposer !== null) {
      try {
        disposer();
      } catch {
        // best-effort only: a refusing disposer must not break teardown.
      }
    }
  };

  /**
   * Restore the idle-nudge cooldown from the branch's durable entry, best-effort.
   *
   * Only a same-session reload resumes the cooldown; a `startup`/`new`/`fork`
   * opens a different scope and inherits nothing. A missing/malformed entry or a
   * throwing reader simply permits a nudge - it never blocks one.
   */
  const restoreIdleNudgeCooldown = (ctx: SupervisorContext) => {
    const entries = readSessionEntries(ctx?.sessionManager);
    let latest = 0;
    let session = "";
    for (const raw of entries) {
      if (raw === null || typeof raw !== "object") continue;
      const entry = raw as { type?: unknown; customType?: unknown; data?: unknown };
      if (entry.type !== "custom" || entry.customType !== IDLE_NUDGE_CUSTOM_TYPE) continue;
      const data = entry.data as { sessionId?: unknown; nudgedAt?: unknown } | null;
      const at = data?.nudgedAt;
      if (typeof at !== "number" || !Number.isFinite(at)) continue;
      if (at >= latest) {
        latest = at;
        session = typeof data?.sessionId === "string" ? data.sessionId : "";
      }
    }
    if (session.length > 0) {
      idleNudgeSession = session;
      lastIdleNudgeAt = latest;
    }
  };

  /**
   * Whether a child's on-disk status proves the run has CLOSED.
   *
   * The accepted set is pi-subagents' OWN terminal vocabulary, taken from the
   * installed package so the two cannot drift:
   *   - `TERMINAL_STATES = new Set(["complete", "failed", "stopped", "rejected"])`
   *     (`bundle/chunk-5YIITCPD.js:1227`)
   * `partial` is additionally treated as closed because it IS in the package's
   * `isTerminalJobStatus` predicate (`:447`) - a partial run has ended, even
   * though its result is incomplete.
   *
   * Deliberately NOT `ownerStateIsTerminal`: that function treats `paused` as
   * non-terminal because a paused run is not a proven automatic wake OWNER, which
   * is the right question for AUTHORIZING a silent wait. Here the question is the
   * opposite one - does this child still occupy the session? - and a `paused` run
   * is retained by the runtime and may still hold live descendants, so for
   * ACTIVITY it stays unresolved. Blocking a nudge grants no authority, so the
   * asymmetry is safe.
   */
  const childStatusClosed = (state: string | null): boolean =>
    state === "complete" ||
    state === "failed" ||
    state === "stopped" ||
    state === "rejected" ||
    state === "partial";

  /**
   * Whether available lifecycle evidence establishes that NO relevant subagent
   * remains unresolved - i.e. "real idle" also holds for children.
   *
   * The whole-point inversion: this returns `false` (do not nudge) both when a
   * child is known to be running AND when the evidence is UNKNOWN. Unknown must
   * never degrade into permission, because nudging into live work is the defect
   * this exists to fix.
   *
   * Inventory is the UNION of the live ledger and the provenance index. Input or
   * tree replacement CLEARS both (`clearObservedRuns`), but a new request does
   * not terminate an earlier child, so a reload/restore path that recovers the
   * prior rows still blocks. Records from a PREVIOUS request epoch therefore
   * still count: an outstanding child does not stop mattering because we started
   * a new turn. This is a deliberately broader scope than the ownership checks
   * use - and that is safe precisely because blocking a nudge confers nothing.
   *
   * Only rows bound to THIS session (by bare UUID) are considered. A positively
   * foreign session's row is excluded.
   *
   * FAIL DIRECTION (user decision, m02697): when a child's state cannot be
   * DETERMINED AT ALL - no lifecycle view, no usable identity, no readable
   * `status.json` - the run is treated as DEAD rather than live. The user's
   * reasoning: a main agent waiting on a child that can never be observed would
   * otherwise stall FOREVER, and a stall is unbounded while a spurious nudge is
   * cheap and self-correcting (the nudge says "continue if not finished", so it
   * is harmless against finished work).
   *
   * This does NOT override POSITIVE evidence of life. A readable `running` or
   * `paused` state is proof the child occupies the session, so it still blocks.
   * The rule applies only to genuinely undeterminable cases - "unknown" is not
   * the same as "known not to be terminal".
   */
  const subagentsKnownIdle = (ctx: SupervisorContext): boolean => {
    // No lifecycle view at all: nothing can be determined, so treat every child
    // as dead and allow the nudge (see FAIL DIRECTION above).
    if (!observationTopicsReady) return true;
    const uuid = sessionUuid(sessionIdentity(ctx));
    const candidates = new Map<string, { run: ObservedRun | null; record: ProvenanceRecord | null }>();
    for (const run of observedRuns.values()) {
      candidates.set(run.runId, { run, record: provenance.get(run.runId) ?? null });
    }
    for (const record of provenance.values()) {
      if (!candidates.has(record.runId)) candidates.set(record.runId, { run: null, record });
    }
    for (const candidate of candidates.values()) {
      const bound = candidate.run?.sessionUuid ?? candidate.record?.sessionUuid ?? "";
      if (bound.length > 0 && uuid.length > 0 && bound !== uuid) continue; // foreign session
      // An unbound row cannot be attributed: undeterminable, so treat as dead.
      if (bound.length === 0) continue;
      if (uuid.length === 0) continue; // cannot bind at all: undeterminable
      // A terminal TOMBSTONE retires the run even if no disk state is readable.
      if (candidate.run?.terminal === true) continue;
      const asyncDir = candidate.run?.asyncDir ?? candidate.record?.asyncDir ?? null;
      // No async dir to inspect means the state cannot be determined: dead.
      if (asyncDir === null) continue;
      const state = readChildStatusState(asyncDir);
      // Unreadable/missing/absent `status.json` cannot be determined: dead. A
      // child whose artifacts are gone has no observable process to wait for.
      if (state === null) continue;
      if (childStatusClosed(state)) continue;
      // POSITIVE evidence of life: the child demonstrably occupies the session,
      // so we must not nudge into it.
      return false;
    }
    return true;
  };

  /** Read a child's `status.json` state through the same seam as the WAIT paths. */
  const readChildStatusState = (asyncDir: string): string | null => {
    const status = readJsonArtifact(join(asyncDir, "status.json"), readFile);
    if (status === null) return null;
    return typeof status.state === "string" && status.state.length > 0 ? status.state : null;
  };

  /**
   * Send ONE static continue-nudge when the session is genuinely idle with
   * unfinished declared work.
   *
   * This is the WHOLE feature. Every gate is a plain early return, and the only
   * state it touches is the cooldown marker - there is no attempt ledger, no
   * generation fence, no per-run verification, and no boundary draft. The nudge
   * is idempotent by construction, so duplicates are acceptable by design.
   *
   * Returns whether the nudge was actually SENT (a nonthrowing
   * `sendUserMessage` submission). The settlement uses that outcome as its
   * policy boundary: continue automatically if we can, otherwise ask for
   * attention. Returning the action's own outcome is deliberate - duplicating
   * the eligibility conditions into a second predicate is how the two drift
   * apart. Note that a gate declining (including the cooldown) returns `false`,
   * so the ordinary notification still fires when nothing was auto-continued.
   */
  const maybeNudgeIdleContinue = (ctx: SupervisorContext, status: DeclaredStatus): boolean => {
    if (continuationDisabled) return false; // PI_MAX_CONTINUATIONS=0 disables entirely
    if (userStopLatched) return false; // a user stop outranks any automatic nudge
    if (!isIdle(ctx)) return false; // nothing will happen unless we interact
    // "Real idle" also requires that no child is still running. A live subagent
    // means work IS happening, so nudging here would inject a message into a
    // session that is already busy - the reported defect.
    if (!subagentsKnownIdle(ctx)) return false;
    if (IDLE_NUDGE_EXCLUDED_STATUSES.has(status)) return false; // DONE/BLOCKED/FAILED/unknown
    if (typeof api.sendUserMessage !== "function") return false; // fail closed: no send surface
    const session = sessionIdentity(ctx);
    const sentAt = now();
    if (session.length > 0 && session === idleNudgeSession && sentAt - lastIdleNudgeAt < IDLE_NUDGE_COOLDOWN_MS) {
      return false; // cooldown: a nudge was already sent recently for THIS session
    }
    let sent = false;
    try {
      api.sendUserMessage(IDLE_CONTINUE_PROMPT, { deliverAs: "followUp" });
      sent = true;
    } catch {
      // A synchronous refusal is observable here. `sent` stays false so the
      // settlement still asks for attention - a refused send is NOT an
      // auto-continuation. The cooldown is recorded regardless so a refusing
      // host is not hammered once per settlement.
    }
    lastIdleNudgeAt = sentAt;
    idleNudgeSession = session;
    if (typeof api.appendEntry === "function") {
      try {
        api.appendEntry(IDLE_NUDGE_CUSTOM_TYPE, { version: 1, sessionId: session, nudgedAt: sentAt });
      } catch {
        // best-effort: an unwritten entry only means a reload permits a nudge.
        // A persistence failure must NOT turn an accepted send into a notice.
      }
    }
    return sent;
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
   * | CONTINUE            | yes      | no     |
   * | WAIT                | no       | no     |
   * | DONE/BLOCKED/FAILED | no       | yes    |
   * | unknown             | no       | yes    |
   *
   * There is no continuation allowance, so there is no budget row: a fresh,
   * well-formed CONTINUE always produces a runnable continuation unless
   * `PI_MAX_CONTINUATIONS=0` disables continuation outright.
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
    // FEATURE 3: a boundary is a settlement point at which a CLAIMED occurrence
    // may be reconciled against positive transcript evidence. There is no text
    // command interface: reminders are created only through the registered tools.
    reconcileAndArm();
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
    // FEATURE 3: a session start opens a new registration scope for the
    // scheduler. The transient fence is re-minted, this registration's timers
    // and ownership are released, and the persisted snapshot is reloaded so THIS
    // session's reminders are armed while a reminder owned by a DIFFERENT session
    // stays retained until its exact session resumes. The snapshot survives.
    registrationToken = mintRegistrationToken();
    clearAllTaskTimers();
    releaseOwnership(ownedStore);
    ownedStore = null;
    ownershipState = "no_session";
    tasks = new Map();
    currentSessionId = "";
    currentSessionFile = sessionTranscriptPath(ctx);
    // Activate the session: acquire ownership and load its snapshot. Claimed
    // occurrences are restored INERT.
    noteSession(ctx);
    // SIMPLE IDLE AUTO-CONTINUE: observe raw interrupts for the user-stop latch,
    // and restore the nudge cooldown only when this start CONTINUES the same
    // session (a different scope inherits nothing). Both are best-effort.
    bindTerminalAbortListener(ctx);
    userStopLatched = false;
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
      // SIMPLE IDLE AUTO-CONTINUE: a continuing session resumes its nudge
      // cooldown so a reload cannot immediately re-nudge; a fresh scope inherits
      // nothing and permits a nudge immediately.
      restoreIdleNudgeCooldown(ctx);
    }
  };
  const handleSessionTree = () => {
    cancelWaitVerification();
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
    // SIMPLE IDLE AUTO-CONTINUE: drop the raw terminal observer and reset the
    // cooldown so nothing leaks past the session it belonged to.
    unbindTerminalAbortListener();
    userStopLatched = false;
    lastIdleNudgeAt = 0;
    idleNudgeSession = "";
    observedRuns = new Map();
    provenance = new Map();
    currentOwnerRuns = new Set<string>();
    ledgerSession = "";
    // FEATURE 3: invalidate outstanding callbacks, clear every timer, and release
    // only THIS registration's verified lock. The persisted snapshot is preserved
    // so the reminders survive the restart; re-minting the fence means a callback
    // that escaped the clear cannot submit.
    registrationToken = mintRegistrationToken();
    clearAllTaskTimers();
    releaseOwnership(ownedStore);
    ownedStore = null;
    ownershipState = "no_session";
    tasks = new Map();
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
      // is intent under the current policy.
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
    // delivered: a genuine, non-steering request is intent under the current
    // policy, which is all this handler needs to know.
    const genuine = source === "interactive" || source === "rpc";
    // A GENUINE new request releases the user-stop latch; an automatic nudge or
    // an extension-origin wake is NOT genuine input and must NOT clear it.
    if (genuine) userStopLatched = false;
  };

  const handleBeforeAgentStart = (event: unknown, ctx: SupervisorContext) => {
    // `before_agent_start` must NOT be load-bearing for the continuation. It is
    // not guaranteed to fire between `input` and the delivered user message, and
    // when it did not, a legitimate CONTINUE could arrive with the handshake
    // unadvanced and stop silently. The delivered user `message_start` is what
    // establishes that the request was consumed; this handler has nothing of its
    // own to record.
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
  };

  const handleSettled = (event: unknown, ctx: SupervisorContext) => {
    // FEATURE 3: a settlement is a point at which a CLAIMED occurrence may be
    // reconciled against positive transcript evidence, and any UNCLAIMED due
    // reminder may be submitted. This runs before the TUI-only notification path
    // so it happens in every surface that can receive an injected turn.
    noteSession(ctx);
    // The compaction window is genuinely closed once a settlement arrives - the
    // send-ready boundary. Clearing it here (a settle that did not follow a
    // terminal compaction event is a harmless no-op) lets a retained due reminder
    // be submitted by the reconciliation arm below.
    compacting = false;
    reconcileAndArm();
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
    }
    // IDLE AUTO-CONTINUE, and the notification precedence it decides.
    //
    // The rule is `idle -> auto-continue ? no-notification : notification`: try
    // to continue the work automatically, and only ask for attention when we did
    // NOT. That is why the nudge is attempted BEFORE the ordinary notification
    // and its outcome gates it - the notification is the fallback, not a
    // parallel event.
    //
    // Scope matters: only the ORDINARY settlement attention is suppressed. The
    // WAIT branch above is nudge-eligible too, but its notices are independent
    // evidence about an unverified wake path (and may be emitted later by a
    // verification/recheck callback), so they are deliberately untouched. A
    // BLOCKED escalation is likewise a real escalation, never a fallback for a
    // nudge.
    //
    // `notified` is consequently NOT consumed by a successful nudge, so any
    // genuinely independent notice still lands exactly once. Every gate lives
    // in `maybeNudgeIdleContinue`; this site only obeys its verdict.
    const nudged = maybeNudgeIdleContinue(ctx, status);
    if (!nudged && status !== "wait" && status !== "blocked") {
      notify(
        event,
        "attention",
        markerProblemFor(messages[messages.length - 1], marker),
      );
    }
  };

  // Subscribe to the two observed-run topics ONCE. Doing it before the handler
  // registrations below keeps the ledger fed from the very first event a host
  // emits, and doing it through the same `api` object keeps it authoritative.
  observeRunEvents();

  /**
   * Open the compaction window at `session_before_compact`.
   *
   * The host exposes no compaction predicate to extensions; the event PAIR is the
   * only production-observable signal. The window stays OPEN across the awaited
   * terminal compaction event (a send is still refused while the host awaits that
   * emit), and is only reopened after the handler returns AND the host has
   * cleared its own abort controller.
   */
  let compactionGeneration = 0;

  /**
   * Reopen the window after a terminal compaction event, one macrotask later.
   *
   * `compacting` is deliberately NOT cleared synchronously in the terminal-event
   * handler, nor in a microtask: the runner AWAITS each handler and the host
   * clears its compaction abort controller only after that await resolves, so a
   * microtask queued inside the handler drains too early and a send would be
   * refused. A macrotask runs after the emit and the host's cleanup.
   *
   * At the check, the window is reopened ONLY when the live context's idle
   * predicate reports ready (the host can accept a send). If readiness is
   * unavailable or false, the window stays OPEN and the reminder is retained
   * until a later real settlement or lifecycle reactivation - never polled. The
   * captured generation fences a superseded check so it cannot reopen a window
   * opened by a newer compaction.
   */
  const closeCompactionWindow = (event: unknown, ctx: SupervisorContext) => {
    const generation = compactionGeneration;
    const capturedRegistration = registrationToken;
    // A REAL macrotask (not the injected timer seam): the readiness check must
    // land after the awaited emit and the host's own `_clearManualCompactionState`
    // continuation, both of which are on the microtask/await chain. A fake-clock
    // timer would be runnable inside the emit by a test that drives the clock.
    setTimeout(() => {
      if (generation !== compactionGeneration) return; // superseded by a newer window
      if (capturedRegistration !== registrationToken) return; // superseded registration
      // READINESS GATE (fail-closed). The contract requires a LIVE idle predicate
      // before reopening: "require live idle predicate before reopening". If the
      // host exposes no `isIdle`, we cannot PROVE the host can accept a send, so
      // the window must stay OPEN rather than fall through and deliver into a
      // context we never verified. Falling through here was a fail-OPEN defect:
      // a context without `isIdle` reopened the gate and submitted the reminder
      // anyway. Retaining is the safe direction - a later real settlement or
      // lifecycle reactivation reopens the window (no polling, no loss).
      if (typeof ctx?.isIdle !== "function") return; // retain: no live predicate to prove readiness
      let idle = false;
      try {
        idle = ctx.isIdle();
      } catch {
        idle = false;
      }
      if (!idle) return; // retain: a real settlement or lifecycle reactivation reopens
      compacting = false;
      reconcileAndArm();
    }, 0);
    return undefined;
  };

  api.on("session_start", handleSessionStart);
  api.on("session_tree", handleSessionTree);
  api.on("session_shutdown", handleSessionShutdown);
  // FEATURE 3: the compaction window. These events are the ONLY production-
  // observable compaction signal available to an extension - there is no
  // `isCompacting` on the API and `ctx.isIdle()` cannot distinguish compaction
  // from streaming. `session_before_compact` opens the window (and advances the
  // generation, so a deferred reopen from a superseded window cannot fire); the
  // two TERMINAL events arm a fenced, macrotask-deferred reopen that requires a
  // live idle predicate, so a throw or an abort can never leave the scheduler
  // permanently believing compaction is on.
  api.on("session_before_compact", () => {
    compacting = true;
    compactionGeneration += 1;
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
