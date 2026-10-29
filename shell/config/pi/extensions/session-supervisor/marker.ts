/**
 * Marker and message-text leaf.
 *
 * WHY THIS MODULE IS A LEAF. `readDeclaredMarker` and `markerProblemFor` are pure
 * functions over one message, and the text helpers they need
 * (`isAssistantMessage`, `messageText`, `isToolCallPart`, `finalNonBlankLine`)
 * are pure too. This module imports the block-structure engine in `markdown.ts`
 * and nothing else from the supervisor, so the dependency stays one-way and the
 * module graph remains acyclic rather than a set of mutually dependent files.
 */
import { LONE_STATUS_WORD, PROSE_JOINER, PROTOCOL_LINE, PAYLOAD_FREE_STATUSES, PAYLOAD_REQUIRED_STATUSES, QUOTED_STATUS_MENTION_FOR } from "./protocol.ts";
import type { DeclaredStatus } from "./protocol.ts";
import type { LineStructure } from "./markdown.ts";
import { lineStructure } from "./markdown.ts";

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
export const MARKER_PROBLEM_NOTICE: Record<NonNullable<DeclaredMarker["problem"]>, string> = {
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
export function markerProblemFor(
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
export function isAssistantMessage(message: unknown): boolean {
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
export function isGenuineQueuedWork(entry: unknown): boolean {
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
 */

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
export function messageText(message: unknown): string {
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
export function finalNonBlankLine(text: string): { text: string; index: number } | null {
  const lines = text.split("\n");
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index].replace(/\s+$/, "");
    if (line.trim().length > 0) return { text: line, index };
  }
  return null;
}

export function isFenceDecorated(line: string): boolean {
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
export function lineDeclares(
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
export function countProtocolLines(
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
export function isDocumentationLine(line: string): boolean {
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
export const MENU_BOUNDARY = /[\s/|,;]+/;

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
export function isProseMenu(line: string): boolean {
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
export function splitAroundSeparators(line: string): string[] {
  return line
    .split(MENU_BOUNDARY)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

/** True for a line indented to Markdown code depth (four COLUMNS): never a marker. */
export function isIndentedCodeLine(line: string): boolean {
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
export function protocolLine(line: string): { name: string; payload: string } | null {
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
export function mentionsQuotedStatus(text: string): boolean {
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
