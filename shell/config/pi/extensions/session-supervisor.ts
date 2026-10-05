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
// GOVERNING PRINCIPLE: notify when not sure. Every branch in which this
// extension cannot determine whether Pi is idle defaults to notifying the user,
// never to silence.
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

/** The `>` introducing a block quote, with the optional space after it. */
const FENCE_LINE = /^(`{3,}|~{3,})(.*)$/;

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

/** OSC 777 notification; the transport the surrounding terminal understands. */
export const OSC_NOTIFY = "\x1b]777;notify;Pi;Session needs attention\x07";

/**
 * OSC 777 notification for a spent automatic-continuation budget. Distinct from
 * the generic notice so an unattended run reports a resource-limited stop rather
 * than implying it is waiting on a human answer.
 */
export const OSC_NOTIFY_BUDGET_EXHAUSTED =
  "\x1b]777;notify;Pi;Automatic continuation budget exhausted - work remains\x07";

/** customType identifying the hidden bridge entry this extension appends. */
export const BRIDGE_CUSTOM_TYPE = "session-supervisor:auto-continuation";

/** Title line of the bridge message, kept for readability in transcripts. */
export const BRIDGE_HEADER = "[session-supervisor:continue]";

/** Consecutive automatic continuations allowed before settling visibly. */
export const DEFAULT_MAX_CONTINUATIONS = 2;

/**
 * Upper bound accepted from `PI_MAX_CONTINUATIONS`. The budget is a resource
 * fuse, not an authorization boundary: it exists to stop an unbounded
 * self-continuation loop, so it stays finite. This ceiling is deliberately
 * generous because reservations are charged per settled turn, not per tool call.
 */
export const HARD_MAX_CONTINUATIONS = 64;

/**
 * Resolve the per-launch continuation budget from the environment.
 *
 * Unset means `DEFAULT_MAX_CONTINUATIONS`; `0` disables automatic continuation.
 * Only exact decimal integers inside `0..HARD_MAX_CONTINUATIONS` are accepted -
 * permissive parsing (`parseInt`) would silently accept `"2abc"`, so it is not
 * used. An invalid value falls back to the default and warns once, because
 * silently granting either 0 or 64 would be a worse failure than the default.
 */
export function resolveMaxContinuations(
  raw: string | undefined,
  warn: (message: string) => void = () => {},
): number {
  if (raw === undefined || raw.trim() === "") return DEFAULT_MAX_CONTINUATIONS;
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    warn(
      `PI_MAX_CONTINUATIONS=${JSON.stringify(raw)} is not a plain integer; using ${DEFAULT_MAX_CONTINUATIONS}`,
    );
    return DEFAULT_MAX_CONTINUATIONS;
  }
  const value = Number(trimmed);
  if (value > HARD_MAX_CONTINUATIONS) {
    warn(
      `PI_MAX_CONTINUATIONS=${trimmed} exceeds the maximum ${HARD_MAX_CONTINUATIONS}; using ${DEFAULT_MAX_CONTINUATIONS}`,
    );
    return DEFAULT_MAX_CONTINUATIONS;
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
}

/** Minimal shape of `ReadonlySessionManager` this extension reads. */
export interface ReadonlySessionView {
  buildSessionProjection?: () => { messages?: unknown[] };
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
  /** Optional: used only for the zellij flag pipe, never for notification. */
  exec?: (command: string, args: string[]) => unknown;
}

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
 *   or inside a fence), and is preceded by a BLANK LINE or opens the message.
 *
 * Everything else resolves to `unknown` (or null when no protocol line exists at
 * all), and the plugin answers "unknown" by NOTIFYING - never by continuing.
 *
 * WHY A BLANK-LINE RULE INSTEAD OF MARKDOWN ANALYSIS: deciding whether a bare
 * line is top-level Markdown requires parsing arbitrary CommonMark containers
 * (quotes, list items, lazy continuations, and their nesting). A local line
 * heuristic cannot do that correctly; an earlier revision that tried failed
 * every review round on a fresh container interaction. The blank-line rule is
 * EXACT instead, in both directions, and both halves were verified against a
 * reference CommonMark parser:
 *
 *   - after a blank line, a column-zero line is ALWAYS a top-level paragraph;
 *   - without one, it is ALWAYS content of the container above it.
 *
 * The cost is that a status line written inline directly beneath prose does not
 * declare. That loss is SAFE: the consequence is a notification the user acts
 * on, not an unwarranted automatic continuation.
 */
export function readDeclaredMarker(message: unknown): DeclaredMarker | null {
  if (!isAssistantMessage(message)) return null;
  const text = messageText(message);
  const lastLine = finalNonBlankLine(text);
  if (lastLine === null) return null;

  const fenced = fencedLineIndexes(text);
  const lines = text.split("\n");

  // A message declaring two DIFFERENT statuses has not declared one.
  const candidates = countProtocolLines(text, fenced);
  if (candidates.ambiguous) {
    return { status: "unknown", payload: "", problem: "ambiguous" };
  }

  const declared = protocolLine(lastLine.text);
  if (declared === null) return null;

  // The SAME predicate the counting path used, so the two cannot disagree.
  // An ineligible final line is reported as `unknown` rather than null so the
  // plugin notifies instead of doing nothing.
  if (!lineDeclares(lines, lastLine.index, fenced)) {
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

/**
 * True when the marker line is preceded by a blank line, or opens the message.
 *
 * This is the ENTIRE container decision: a blank line closes every open Markdown
 * container, so a column-zero line after one is always top level.
 */
function isPrecededByBlank(lines: string[], index: number): boolean {
  if (index === 0) return true;
  return lines[index - 1].trim().length === 0;
}

/** Null unless the message's role is exactly `assistant`. */
function isAssistantMessage(message: unknown): boolean {
  if (message === null || typeof message !== "object") return false;
  return (message as { role?: unknown }).role === "assistant";
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
  if (content.some((part) => (part as { type?: unknown } | null)?.type === "tool_call")) return "";
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
 * Map every line index to whether the fence state CHANGES at that line.
 *
 * Value `true` means the line OPENED a fence (it is then fenced for the rest of
 * the scan); `false` means it CLOSED one. Implemented as an explicit toggle so
 * an unterminated fence behaves exactly like the renderer's: everything after it
 * is inside, and nothing before it is.
 */
function fencedLineIndexes(text: string): Map<number, boolean> {
  const changes = new Map<number, boolean>();
  let open: string | null = null;
  const lines = text.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    // An indented fence delimiter is itself Markdown code, so it neither opens
    // nor closes a fence - the same rule that makes an indented marker prose.
    if (isIndentedCodeLine(line)) continue;
    // Use the full classifier so an info string on an OPENER is recognised:
    // a tagged ```text fence must still open a region, or its contents would be
    // read as live declarations.
    const marker = fenceDelimiter(line.trimStart());
    if (marker === null) continue;
    if (open === null) {
      // Only a line that can OPEN a fence does so; a bare run always can.
      open = marker.run;
      changes.set(index, true);
      continue;
    }
    // CommonMark: a closer uses the SAME character and is at least as long as
    // the opener, and carries nothing but whitespace after the run. A shorter,
    // different, or info-string-bearing line is content inside the fence.
    if (marker.closerOnly && marker.run[0] === open[0] && marker.run.length >= open.length) {
      open = null;
      changes.set(index, false);
    }
  }
  return changes;
}

/**
 * True when `index` sits strictly inside a fenced region.
 *
 * A fence OPENER is fenced for everything after it but is not itself "inside" a
 * fence: the opener is the delimiter, so it is evaluated on its own (and
 * rejected by `isFenceDecorated` instead). A fence CLOSER likewise ends the
 * region on the line it occupies, so a marker sharing that line is still inside.
 */
function isInsideFence(changes: Map<number, boolean>, index: number): boolean {
  let inside = false;
  for (let cursor = 0; cursor < index; cursor += 1) {
    const change = changes.get(cursor);
    if (change === undefined) continue;
    if (change) inside = true;
    else inside = false;
  }
  return inside;
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
 *   - preceded by a blank line (or the message start), which is the whole
 *     Markdown-container decision
 *   - not documentation (a prose menu, or a status word quoted as an example)
 */
function lineDeclares(
  lines: string[],
  index: number,
  fenced: Map<number, boolean>,
): boolean {
  const line = lines[index].replace(/\s+$/, "");
  if (protocolLine(line) === null) return false;
  if (isIndentedCodeLine(line)) return false;
  if (isFenceDecorated(line)) return false;
  if (isInsideFence(fenced, index)) return false;
  if (!isPrecededByBlank(lines, index)) return false;
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
  fenced: Map<number, boolean>,
): { count: number; ambiguous: boolean } {
  const lines = text.split("\n");
  const names: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (!lineDeclares(lines, index, fenced)) continue;
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

/** True for a line indented four spaces or a tab: Markdown code, never a marker. */
function isIndentedCodeLine(line: string): boolean {
  // A tab advances to the next four-column stop, so it is code on its own.
  if (line.startsWith("\t")) return true;
  const leading = line.length - line.trimStart().length;
  return leading >= 4;
}

/**
 * True when a line is a fence delimiter, opener or closer.
 *
 * Closing delimiters may carry only whitespace; opening delimiters may carry an
 * info string, which is what makes a tagged ``` ```text ``` fence open.
 */
function isFenceDelimiter(line: string): boolean {
  return fenceDelimiter(line) !== null;
}

/**
 * Classify a fence delimiter line, or null when the line is not one.
 *
 * Returns the delimiter run and whether this line can only CLOSE a fence (a
 * bare run with nothing but whitespace after it).
 */
function fenceDelimiter(line: string): { run: string; closerOnly: boolean } | null {
  const match = FENCE_LINE.exec(line);
  if (match === null) return null;
  const rest = match[2] ?? "";
  return { run: match[1], closerOnly: rest.trim().length === 0 };
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
  // is stripped before parsing. A FULLY backticked line is documentation and is
  // rejected by the caller via `mentionsQuotedStatus`, which reports `unknown`
  // so the plugin notifies instead of mistaking documentation for a decision.
  const trailing = candidate.replace(/`+$/, "");
  const match = PROTOCOL_LINE.exec(trailing);
  if (match !== null) {
    return { name: match[1], payload: (match[2] ?? "").trim() };
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
 */
function mentionsQuotedStatus(text: string): boolean {
  return text.match(QUOTED_STATUS_MENTION) !== null;
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
  context?: { contextMessages?: unknown[]; canContinue?: boolean };
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
 * Register handlers against a Pi API. Kept as a pure helper so tests can drive
 * it with fake contexts without importing Pi itself.
 */
export function registerSessionSupervisor(
  api: SupervisorApi,
  env: { ZELLIJ_PANE_ID?: string; PI_MAX_CONTINUATIONS?: string } = process.env,
): void {
  let notified = false;

  // Resolved ONCE per registration. Re-reading the environment later could let a
  // value change mid-session raise the allowance, which would defeat the ledger.
  const maxContinuations = resolveMaxContinuations(env.PI_MAX_CONTINUATIONS, (message) => {
    try {
      console.warn(`[session-supervisor] ${message}`);
    } catch {
      // best-effort only
    }
  });

  // --- Continuation budget -------------------------------------------------
  // A LOCAL reservation ledger:
  //
  //   let slots = 0, phase: RequestPhase = "none"
  //
  // `slots` never increases within an established request, and each successful
  // proposal reserves one IMMEDIATELY and irrevocably. Only a confirmed new
  // genuine request replenishes them. Pi exposes no atomic acknowledgement that
  // a proposal was accepted, so charging at proposal time is the honest choice:
  // a vetoed or overwritten proposal leaves the slot consumed (conservative
  // under-utilisation) rather than allowing an unbounded loop. Nothing the model
  // emits - least of all a marker - can refill the ledger.
  let slots = 0;
  let phase: RequestPhase = "none";
  // Tracks whether allowance was ever genuinely granted for the current request,
  // so "spent budget" can be told apart from an unarmed reload/resume/fork. Only
  // a genuinely established budget earns the resource-exhaustion notice.
  let budgetEstablished = false;

  /** True only when the host reports an idle agent; unknown means not idle. */
  const isIdle = (ctx: SupervisorContext): boolean => {
    try {
      return ctx?.isIdle?.() === true;
    } catch {
      return false;
    }
  };

  /**
   * Revoke allowance and cancel any pending handshake.
   *
   * Disarming (rather than replenishing) is the fail-closed default for every
   * ambiguous transition: reload/resume/fork, tree navigation, steering or
   * follow-up input, and overlapping submissions all land here.
   */
  const disarm = () => {
    slots = 0;
    phase = "none";
    budgetEstablished = false;
  };

  /** Emit the OSC notification, then flag the pane when a pane id is known. */
  const notify = (event: unknown, why: "attention" | "budget-exhausted" = "attention") => {
    if (notified) return;
    notified = true;

    try {
      process.stdout.write(why === "budget-exhausted" ? OSC_NOTIFY_BUDGET_EXHAUSTED : OSC_NOTIFY);
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
    const marker = markerForBoundary(boundary);
    const status = marker?.status ?? "unknown";
    // `WAIT` is the one status with neither outcome: an established wake-up path
    // already owns the resume, so there is nothing to continue and nobody to
    // notify.
    if (status === "wait") return;
    // A declaration this extension cannot act on is a resource-limited stop only
    // when the allowance is the reason it cannot act. Four conditions qualify:
    // the marker asked to continue, a budget was actually established for this
    // request, no slot remains, the boundary is otherwise proposable - an
    // aborted or error boundary already prohibits continuation for its own
    // reason, and a missing entries array cannot carry the bridge, so naming the
    // budget in those cases would report the wrong cause - and no other handler
    // already owns the continuation. Ownership is part of the predicate here
    // because `canPropose` is false once the allowance is spent, so an owned
    // continuation arrives through this branch, not the ownership branch below.
    const exhaustionCandidate =
      status === "continue" &&
      budgetEstablished &&
      slots <= 0 &&
      boundary.outcome === "completed" &&
      Array.isArray(boundary.entries) &&
      boundary.continue !== true;
    if (marker === null || status !== "continue" || !canPropose(boundary)) {
      // Everything else - including an absent or malformed marker - tells the
      // user. "Notify when not sure."
      notify(event, exhaustionCandidate ? "budget-exhausted" : "attention");
      return;
    }
    // Respect a continuation another handler already requested rather than
    // emitting a duplicate; the budget is still charged, exactly as a vetoed or
    // overwritten proposal would be. The user is still told, because this
    // extension is not the participant that will resume the work and the
    // decision table maps this row to "notify".
    if (boundary.continue === true) {
      slots -= 1;
      notify(event);
      return;
    }
    // A boundary with no draft array cannot carry the bridge entry, so the
    // declaration cannot be acted on: notify rather than silently swallowing it.
    if (!Array.isArray(boundary.entries)) {
      slots -= 1;
      notify(event);
      return;
    }
    slots -= 1;
    return {
      entries: [...boundary.entries, buildBridgeEntry(marker)],
      continue: true,
    };
  };

  /** True when a declared CONTINUE may actually be proposed to Pi. */
  const canPropose = (boundary: AgentBeforeSettleLike): boolean => {
    if (boundary.outcome !== "completed") return false;
    return slots > 0;
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
  // require a fresh handshake. Returning `undefined` from `input` is required -
  // Pi swallows the user's prompt on `{action:"handled"}`.
  const handleSessionStart = () => disarm();
  const handleSessionTree = () => disarm();

  const resetForInput = (event: unknown, ctx: SupervisorContext) => {
    notified = false;
    // Never replenish directly on `input`: it fires before later handlers can
    // consume the input and before queued input is delivered, so it does not
    // establish that a request was delivered. Revoke and start the handshake.
    slots = 0;
    // Revoking allowance also revokes the *establishment* fact: this request no
    // longer has a budget, so it must not later be reported as exhausted.
    budgetEstablished = false;
    const source = (event as { source?: unknown } | null)?.source;
    const genuine = source === "interactive" || source === "rpc";
    const steering = (event as { streamingBehavior?: unknown } | null)?.streamingBehavior !== undefined;
    phase = phase === "none" && genuine && !steering && isIdle(ctx) ? "submitted" : "blocked";
  };

  const handleBeforeAgentStart = (event: unknown, ctx: SupervisorContext) => {
    slots = 0;
    // A replacement start inherits no prior establishment; the flag is set only
    // again by a fresh handshake that actually grants an allowance.
    budgetEstablished = false;
    phase = phase === "submitted" && isIdle(ctx) ? "starting" : "blocked";
    return undefined;
  };

  const handleMessageStart = (event: unknown) => {
    const message = (event as { message?: { role?: unknown } } | null)?.message;
    if (message?.role !== "user") return;
    // Only a user message that completed the handshake replenishes the budget.
    // Our own bridge is a `custom_message` (role `custom`), so it can never
    // re-arm the cap through this path.
    const fresh = phase === "starting";
    slots = fresh ? maxContinuations : 0;
    budgetEstablished = fresh && maxContinuations > 0;
    phase = fresh ? "none" : "blocked";
  };

  const handleSettled = (event: unknown, ctx: SupervisorContext) => {
    if (!isTui(ctx)) return;
    // A settle is when the user-visible outcome is decided. The declared marker
    // on the last assistant message says whether the settle is real: `WAIT`
    // means an established wake-up path exists, so stay silent. Every other
    // outcome - including an absent marker - notifies.
    const marker = lastAssistantMarker(projectedFromView(ctx));
    if ((marker?.status ?? "unknown") !== "wait") notify(event);
    // Settlement clears pending handshake state but does NOT replenish slots.
    phase = "none";
  };

  api.on("session_start", handleSessionStart);
  api.on("session_tree", handleSessionTree);
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