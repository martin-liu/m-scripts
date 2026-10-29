/**
 * Identity helpers: session UUID normalisation and lineage-token minting.
 *
 * These are deliberately dependency-free leaves. `mintLineageToken` is required
 * by registration-token minting and `sessionUuid` by provenance parsing; keeping
 * them together in a leaf module is what breaks the
 * `tasks -> provenance -> transcript -> tasks` import cycle.
 */

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
export function mintLineageToken(): string {
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
 * The scheduler-owned correlation envelope for one claimed occurrence.
 *
 * The injected message carries a FIXED, machine-recognizable line naming the task
 * and the OPAQUE `occurrenceId`. Reconciliation requires this EXACT line in a
 * `role: "user"` PERSISTED transcript row, so an assistant that merely ECHOES the
 * text can never settle a claim.
 */
export function taskOccurrenceEnvelope(taskId: string, occurrenceId: string): string {
  return `[task ${taskId} occurrence ${occurrenceId}]`;
}
