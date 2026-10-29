import { closeSync, openSync, readFileSync, readSync, statSync } from "node:fs";
import { join } from "node:path";
import { MAX_RESULT_ARTIFACT_BYTES } from "./protocol.ts";
import { taskOccurrenceEnvelope } from "./ids.ts";

/**
 * Persisted-transcript reading and the process-wide runtime instance identity.
 *
 * Delivery confirmation reads the PERSISTED session transcript (fail-closed: an
 * unreadable transcript can never fabricate a commit). This module also owns the
 * single MUTABLE module binding `runtimeInstanceId`, together with its accessors.
 */

/** One injected read function so tests can supply a fixture map. */
export type ReadFile = (path: string) => string | null;

/**
 * The size of a file, or null when it cannot be stat-ed.
 *
 * Injected alongside `readFile` so a test can model an artifact whose declared
 * size disagrees with what the reader returned (a short read) without needing a
 * real multi-megabyte fixture.
 */
export function defaultStatSize(path: string): number | null {
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
 * A conservative WORST-CASE bound on the serialized transcript-row bytes for an
 * injected reminder prompt.
 *
 * The host persists a delivered message as a JSONL row that wraps the injected
 * text in a JSON object (`{type:"message", message:{role:"user", content:[{
 * type:"text", text:<injected>}]}}`), so the row can expand well beyond the
 * prompt's own length: every code unit may escape to six bytes and the row adds
 * fixed key framing. `transcriptConfirmsDelivery` reads only the last
 * `TRANSCRIPT_TAIL_BYTES` of the transcript and SKIPS a line it cannot
 * `JSON.parse`, so a delivery row that begins BEFORE the tail window can NEVER be
 * positively correlated and its occurrence would re-send forever. This bound is
 * therefore computed when a reminder is created to REJECT an oversized task
 * BEFORE it is accepted, persisted, or armed (see the `schedule_task` tool).
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
export function readTranscriptTail(path: string): string | null {
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
 * interpreted. `expected` is the COMPLETE generated firing text. The match is an
 * EXACT equality, not a substring or prefix test: the correlation envelope is
 * only the first line of `taskFiringPrompt`, so accepting a prefix (or any
 * `includes` match) would let a row that merely echoes the envelope - a truncated
 * or partially persisted line, or unrelated prose quoting it - settle a claim.
 * That would advance an interval or delete a one-shot without proof the full
 * reminder ever reached the model.
 */
export function transcriptConfirmsDelivery(transcript: string | null, expected: string): boolean {
  if (transcript === null || transcript.length === 0 || expected.length === 0) return false;
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
      if (typeof text === "string" && text === expected) return true;
    }
  }
  return false;
}

/**
 * Confirm delivery of an occurrence against EITHER accepted envelope rendering:
 * the current one, or the immediately previous one retained for upgrade
 * compatibility.
 *
 * Both renderings are built from the SAME task id, occurrence id, and stored
 * prompt, so accepting the legacy form cannot confirm a different occurrence or a
 * different payload. Only these two COMPLETE renderings qualify; a prefix,
 * substring, quoted copy, or appended text still fails, because each check is the
 * existing exact-equality matcher. Confirmation remains proof of DELIVERY, not of
 * work completion: a historical occurrence that was delivered but merely echoed
 * must not automatically execute again.
 */
export function transcriptConfirmsDeliveryEither(
  transcript: string | null,
  current: string,
  legacy: string,
): boolean {
  return transcriptConfirmsDelivery(transcript, current) || transcriptConfirmsDelivery(transcript, legacy);
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
export function defaultReadFile(path: string): string | null {
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
export function readJsonArtifact(path: string, readFile: ReadFile): Record<string, unknown> | null {
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
export function isAbsolutePath(path: string | null): path is string {
  return typeof path === "string" && path.startsWith("/");
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

export let runtimeInstanceId: string = processRuntimeInstanceId();

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
