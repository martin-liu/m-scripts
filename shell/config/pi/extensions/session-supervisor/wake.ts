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
 */
import { documentFences, lineStructure } from "./markdown.ts";

export type WakeProof = { kind: "subagent"; id: string; event: string };

/** Parse a WAIT payload into a wake-proof reference, or null when it names none. */
export function parseWakeProof(payload: string): WakeProof | null {
  const [kind, id, ...event] = payload.trim().split(/\s+/);
  if (kind.toLowerCase() !== "subagent" || !id || !event.length) return null;
  return { kind: "subagent", id, event: event.join(" ") };
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

/** User-owned branch of the Input v1 contract in agents/references/advisory.md. */
export interface UserInputAssessment {
  version: 1;
  outcome: "USER_INPUT_REQUIRED";
  dependencyId: string;
  kind: "authorization" | "access" | "fact" | "product-intent";
  dependency: string;
  question: string;
  whyAgentCannotResolve: string;
}

const nonblank = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;

/** Parse one complete user-owned assessment; the supervisor separately verifies its provenance. */
export function parseUserInputAssessment(result: unknown): UserInputAssessment | null {
  if (typeof result !== "string") return null;
  // The documented record lives in an `oracle-input-assessment` fence. As a
  // compatibility path, a bare ```json fence whose object carries the
  // assessment shape is also accepted, so a host that strips the info string
  // still works. Both forms count toward the same uniqueness check.
  const body = singleAssessmentBody(result);
  if (body === null) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object") return null;
  const record = parsed as Record<string, unknown>;

  const { version, outcome, dependencyId, kind, dependency, question, whyAgentCannotResolve } = record;
  if (version !== 1 || outcome !== "USER_INPUT_REQUIRED") return null;
  if (kind !== "authorization" && kind !== "access" && kind !== "fact" && kind !== "product-intent") return null;
  if (!nonblank(dependencyId) || !nonblank(dependency) || !nonblank(question) || !nonblank(whyAgentCannotResolve)) return null;
  // All seven required fields are present. Any other field (including an agent decision) is incompatible.
  if (Object.keys(record).length !== 7) return null;
  return { version, outcome, dependencyId, kind, dependency, question, whyAgentCannotResolve };
}

/** A competing named return or unfinished assessment makes the whole result unusable. */
function singleAssessmentBody(text: string): string | null {
  let candidate: string | null = null;
  for (const { info, body, closed } of documentFences(text)) {
    const tag = info.trim().toLowerCase().replace(/\s+/g, " ");
    const name = tag.replace(/^json /, "");
    if (["oracle-closure-assessment", "oracle-review-result", "oracle-advisory-result", "pi-planning-handoff", "acceptance-report"].includes(name)) return null;
    if (name !== "oracle-input-assessment" && !(tag === "json" && looksLikeAssessment(body))) continue;
    if (!closed || candidate !== null) return null;
    candidate = body;
  }
  return candidate;
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

/**
 * Read questions from the parent's own document paragraphs, never examples or
 * Oracle's artifact. A question must start a paragraph or immediately follow
 * another eligible question. Return all siblings so ambiguity is not lost.
 */
export function userQuestionLines(result: unknown): string[] {
  if (typeof result !== "string") return [];
  const text = result.replace(/\r\n?/g, "\n");
  const lines = text.split("\n");
  const { topLevel, paragraphStart, inside } = lineStructure(text);
  const found: string[] = [];
  let previousWasQuestion = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    previousWasQuestion = line.startsWith("USER_QUESTION:") && topLevel[i] && !inside[i] &&
      (paragraphStart[i] || previousWasQuestion);
    if (previousWasQuestion) found.push(line.slice("USER_QUESTION:".length).trim());
  }
  return found;
}
