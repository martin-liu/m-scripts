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
 *
 * Extracted from `session-supervisor.ts` (formerly lines ~370-740) as a PURE
 * MOVE: no behavior changed.
 */
import { join } from "node:path";

import {
  MAX_RESULT_ARTIFACT_BYTES,
  PROVENANCE_CUSTOM_TYPE,
  REQUEST_GENERATION_CUSTOM_TYPE,
  START_FORM_EVENTS,
} from "./protocol.ts";
import { sessionUuid } from "./ids.ts";
import { defaultReadFile, defaultStatSize, isAbsolutePath, readJsonArtifact } from "./transcript.ts";
import type { ProvenanceRecord, ReadFile } from "./transcript.ts";

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
