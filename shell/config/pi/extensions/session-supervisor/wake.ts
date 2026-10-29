/**
 * Wake-proof and declaration parsing for the settle-boundary supervisor.
 *
 * Three marker grammars are parsed here, all SYNTACTICALLY:
 *
 *   * `WakeProof` — the value of a `STATUS:WAIT <pending event>` marker. It is
 *     only a CLAIM that an automatic wake path exists; `rpc-verify.ts` decides
 *     whether the claim is backed by a currently-live owner.
 *   * `BlockedDeclaration` — `BLOCKED user oracle=<run-id> dependency=<id>` or
 *     `BLOCKED external owner=<...>`, naming what the agent is waiting on and
 *     who owns it. Parsing does NOT authorize a question.
 *   * `UserInputAssessment` — the versioned fenced JSON an Oracle run must carry
 *     for a user-owned dependency to become askable. This module reads the
 *     assessment and its fence; the supervisor still verifies provenance,
 *     completion, and the `USER_QUESTION:` sibling line before anything is asked.
 *
 * Extracted from `session-supervisor.ts` (formerly lines ~354-722) as a PURE
 * MOVE: no behavior changed. Nothing here reads live session state, so the whole
 * module is testable without a session.
 */
import { isFenceDecorated, isIndentedCodeLine } from "./marker.ts";
import { lineStructure } from "./markdown.ts";
import type { LineStructure } from "./markdown.ts";

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
