/**
 * Run provenance: which async runs this parent actually witnessed, and which
 * registration lineage they belong to.
 *
 * A witnessed START is only an OBSERVATION, never a grant. This module records
 * what was seen (`ObservedRunEvidence`, `ProvenanceRecord`) and answers one
 * narrow question: does a claimed owner belong to the CURRENT lineage? A stale
 * record from a superseded registration must never be able to silence the user,
 * so lineage is compared explicitly (`provenanceBelongsToCurrentGeneration`)
 * rather than inferred from a numeric counter that restarts per registration.
 */
import { join } from "node:path";

import {
  asRecord,
  MAX_RESULT_ARTIFACT_BYTES,
  PROVENANCE_CUSTOM_TYPE,
  REQUEST_GENERATION_CUSTOM_TYPE,
  START_FORM_EVENTS,
} from "./protocol.ts";
import { sessionUuid } from "./ids.ts";
import { messageText } from "./marker.ts";
import { defaultReadFile, isAbsolutePath, readJsonArtifact, readTranscriptTail } from "./transcript.ts";
import type { ObservedRun, ProvenanceRecord, ReadFile } from "./transcript.ts";

export interface ObservedRunEvidence {
  /** Absolute async directory the START event named, or null when unknown. */
  asyncDir: string | null;
  /** Host-recorded Pi child transcript, never the mixed progress log. */
  resultPath: string | null;
  /** All text parts of the terminal assistant message, or null without proof. */
  result: string | null;
  /** True when the witnessed run's status is complete. */
  completed: boolean;
}

/** Read only the final JSONL record: searching backward could accept a superseded ask. */
function terminalReply(tail: string | null, runId: string): string | null {
  if (!tail?.endsWith("\n")) return null;
  const end = tail.length - 1;
  const start = tail.lastIndexOf("\n", end - 1) + 1;
  // The native writer prepends an initial prompt. Require the actual record boundary
  // even at the start of our bounded tail; a suffix of an oversized row is not proof.
  if (start === 0) return null;
  const line = tail.slice(start, end);
  if (Buffer.byteLength(line, "utf8") > MAX_RESULT_ARTIFACT_BYTES) return null;
  try {
    const row = JSON.parse(line);
    if (row?.version !== 1 || row.source !== "async" || row.runId !== runId || row.agent !== "oracle" || row.childIndex !== 0 ||
        row.recordType !== "message" || row.sourceEventType !== "message_end" || row.role !== "assistant") return null;
    const msg = row.message;
    if (msg?.role !== "assistant" || msg.stopReason !== "stop" || msg.errorMessage || !Array.isArray(msg.content)) return null;
    return messageText(msg) || null;
  } catch {
    return null;
  }
}

/** Read the raw final reply of one witnessed native Oracle, not tool output or the host's stripped display copy. */
export function readObservedRunEvidence(
  { asyncDir, runId, sessionUuid: parentUuid }: Pick<ObservedRun, "asyncDir" | "runId" | "sessionUuid">,
  readFile: ReadFile = defaultReadFile,
  readTail: ReadFile = (path) => readTranscriptTail(path, MAX_RESULT_ARTIFACT_BYTES + 2),
): ObservedRunEvidence {
  const empty: ObservedRunEvidence = { asyncDir, resultPath: null, result: null, completed: false };
  if (!asyncDir || !runId || !parentUuid) return empty;
  const status = readJsonArtifact(join(asyncDir, "status.json"), readFile);
  if (status?.state !== "complete" || status.runId !== runId || typeof status.sessionId !== "string" ||
      sessionUuid(status.sessionId) !== parentUuid) return empty;

  const step = status.mode === "single" && Array.isArray(status.steps) && status.steps.length === 1
    ? asRecord(status.steps[0]) : undefined;
  if (step?.agent !== "oracle" || step.status !== "complete" || step.transcriptError || !isAbsolutePath(step.transcriptPath)) {
    return { ...empty, completed: true };
  }
  const resultPath = step.transcriptPath;
  return { asyncDir, completed: true, resultPath, result: terminalReply(readTail(resultPath), runId) };
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
  const entry = asRecord(value);
  if (!entry) return null;
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

/** The last valid marker in this process's domain selects the lineage. Only
 * that token's highest generation counts, even if its markers are interleaved.
 */
export function currentLineageGeneration(entries: unknown[], domain: string): CurrentLineageGeneration | null {
  const highest = new Map<string, number>();
  let lastLineage = "";
  let legacyEpoch: number | null = null;
  for (const raw of entries) {
    const entry = asRecord(raw);
    if (entry?.type !== "custom" || entry.customType !== REQUEST_GENERATION_CUSTOM_TYPE) continue;
    const data = asRecord(entry.data);
    if (data?.version !== 1 || typeof data.domain !== "string" || data.domain !== domain) continue;
    const { lineage, generation } = data;
    if (typeof generation !== "number" || !Number.isSafeInteger(generation)) continue;

    // Without tokens, a rise advances the cursor, a drop restarts it, and an
    // equal epoch is a duplicate. A tokenless last marker confers no identity.
    if (generation !== legacyEpoch) legacyEpoch = generation;
    lastLineage = typeof lineage === "string" ? lineage : "";
    if (!lastLineage) continue;
    const previous = highest.get(lastLineage);
    if (previous === undefined || generation > previous) highest.set(lastLineage, generation);
  }
  if (legacyEpoch === null) return null;
  return lastLineage ? { lineage: lastLineage, generation: highest.get(lastLineage)! }
    : { lineage: LEGACY_NO_LINEAGE_SENTINEL, generation: legacyEpoch };
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
  if (latestGeneration === null || record.requestEpoch !== latestGeneration) return false;
  const recordLineage = typeof record.lineage === "string" ? record.lineage : "";
  return currentLineage === undefined || recordLineage === currentLineage;
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
