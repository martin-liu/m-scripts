// R7-4 REPAIR: capture GENUINELY runtime-produced targeted-status envelopes.
//
// The PREVIOUS version of this recipe injected a MOCK `execute` that hand-wrote
// `Run: ${runId}\nState: ${state}` from a lookup table. That proved only the
// wrapper/envelope SHAPE; the status TEXT was invented, so it did not satisfy
// the requirement for runtime-produced status. This version removes the mock:
// it drives the REAL exported status renderer (`inspectSubagentStatus`,
// `runs/background/run-status.js:351`) over REAL on-disk run state written by
// this script, and captures the REAL correlated replies emitted by the REAL
// installed RPC bridge (`src/extension/rpc.js`).
//
// Protocol: this recipe is the "executor" side of the RPC bridge, exactly as the
// real extension is. It wires the real bridge's `execute` to the REAL
// `inspectSubagentStatus`, so every `Run:`/`State:` header in the captured
// envelopes is produced by pi-subagents' own status code from real run state -
// not synthesized here. The value under test is the ENVELOPE + STATUS contract
// between the bridge and the supervisor, which is what the supervisor parses.
//
// SCOPE (R15, CORR37): NO CHILD IS LAUNCHED BY THIS CAPTURE. The recipe SEEDS a
// minimal async-run tree on disk (`seedRun`) and drives the bridge/renderer over
// that seeded state; it starts no `pi`/`pi-subagents` child process and executes
// no agent work. The capture therefore proves the BRIDGE + status-RENDERER
// PROTOCOL (request/response correlation and the `Run:`/`State:`/`fleet` shape)
// over seeded state - it is NOT, and must not be promoted to, evidence of
// live-child execution. Anything needing real child lifecycle must be captured
// from a real child separately.

import { writeFileSync, mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { registerSubagentRpcBridge } from "pi-subagents/src/extension/rpc.js";
import { inspectSubagentStatus } from "pi-subagents/src/runs/background/run-status.js";
import { SUBAGENT_ASYNC_STARTED_EVENT } from "pi-subagents/src/shared/types.js";

function createEventBus() {
  const listeners = new Map();
  return {
    listeners,
    on(channel, handler) {
      const list = listeners.get(channel) ?? [];
      list.push(handler);
      listeners.set(channel, list);
      return () => {
        const cur = listeners.get(channel) ?? [];
        const i = cur.indexOf(handler);
        if (i >= 0) cur.splice(i, 1);
      };
    },
    emit(channel, event) {
      for (const h of [...(listeners.get(channel) ?? [])]) {
        try { h(event); } catch {}
      }
    },
  };
}

// A REAL async-run directory tree on disk, so `inspectSubagentStatus` reads real
// state. Each run gets the minimal on-disk shape the status code inspects.
const ASYNC_ROOT = "/tmp/r7-4-real-async";
mkdirSync(ASYNC_ROOT, { recursive: true });

/** Write a minimal real run directory for `status` to inspect. */
function seedRun(id, state) {
  const dir = join(ASYNC_ROOT, id);
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, "status.json"),
    JSON.stringify({
      runId: id,
      state,
      agent: "oracle",
      sessionId: "sess-1",
      startedAt: 1_700_000_000_000,
      updatedAt: 1_700_000_000_000,
    }),
  );
  return dir;
}

const RUN_STATES = [
  ["run-active", "running"],
  ["run-queued", "queued"],
  ["run-paused", "paused"],
  ["run-complete", "complete"],
  ["run-failed", "failed"],
  ["run-stopped", "stopped"],
];
const DIRS_BY_ID = new Map();
for (const [id, state] of RUN_STATES) DIRS_BY_ID.set(id, seedRun(id, state));

const events = createEventBus();
// Captured replies, keyed by `requestId` so consumers can address them
// directly (e.g. `captured["real-3"]`). Each entry records the channel it
// arrived on plus the reply ENVELOPE, verbatim as the real bridge emitted it.
const captured = {};
const origEmit = events.emit.bind(events);
events.emit = (channel, event) => {
  if (typeof channel === "string" && channel.startsWith("subagents:rpc:v1:reply:")) {
    captured[event?.requestId ?? channel] = { channel, event };
  }
  return origEmit(channel, event);
};

const realState = {
  asyncJobs: new Map(),
  fleetJobs: new Map(),
  foregroundControls: new Map(),
  currentSessionId: "sess-1",
};

registerSubagentRpcBridge({
  events,
  getContext: () => ({
    sessionManager: {
      getSessionFile: () => "/tmp/r7-4-real-session.jsonl",
      getSessionId: () => "sess-1",
    },
  }),
  // The REAL executor contract: (toolCallId, params, signal, onUpdate, ctx).
  // It returns the REAL renderer's result, so the `Run:`/`State:` text is
  // produced by pi-subagents' own status code over the real on-disk state above.
  execute: async (toolCallId, params) => {
    const target = params?.runId ?? params?.id ?? params?.dir;
    return inspectSubagentStatus(
      { action: "status", runId: params?.runId ?? params?.id, dir: DIRS_BY_ID.get(target) },
      { state: realState, asyncDirRoot: ASYNC_ROOT },
    );
  },
  state: realState,
  disabledFeatures: new Set(),
});

// Emit the REAL start event so the bridge's fleet/snapshot projections have a
// real observed run to work with.
events.emit(SUBAGENT_ASYNC_STARTED_EVENT, {
  lifecycleArtifactVersion: 3,
  id: "run-active",
  pid: process.pid,
  sessionId: "sess-1",
  completionOwnerId: "owner-1",
  mode: "single",
  agent: "oracle",
  asyncDir: DIRS_BY_ID.get("run-active"),
});

const REQUESTS = [
  ...RUN_STATES.map(([id]) => ({ runId: id })),
  // A genuinely UNKNOWN run id: the real renderer decides the outcome, rather
  // than a lookup defaulting it to "running".
  { runId: "run-absent" },
];
for (const [i, params] of REQUESTS.entries()) {
  events.emit("subagents:rpc:v1:request", {
    version: 1,
    requestId: `real-${i}`,
    method: "status",
    params,
  });
}
// A malformed request, to capture the REAL error envelope shape.
events.emit("subagents:rpc:v1:request", {
  version: 1,
  requestId: "real-bad",
  method: "status",
  params: {},
});

await new Promise((r) => setTimeout(r, 400));
// R8-5: the capture is NON-MUTATING by default. It previously OVERWROTE the
// tracked fixture `../subagents-rpc-captured.json` on every run, so each
// reproduction mutated a RELEVANT (tracked) file and the frozen snapshot was
// never byte-stable: the manifest, the README, and the committed fixture drifted
// to three different hashes. The default now writes to a TEMP path and leaves the
// tracked fixture untouched, so the documented reproduction is safe to run
// against a frozen snapshot. Pass `--update-fixture` (or set
// SUPPGENTS_CAPTURE_UPDATE_FIXTURE=1) only when deliberately regenerating the
// committed fixture, and then expect to update the recorded hashes.
const updateFixture =
  process.argv.includes("--update-fixture") ||
  process.env.SUBAGENTS_CAPTURE_UPDATE_FIXTURE === "1";
const trackedFixture = new URL("../subagents-rpc-captured.json", import.meta.url);
const outPath = updateFixture
  ? trackedFixture
  : new URL(`../.capture-${process.pid}.json`, import.meta.url);
writeFileSync(outPath, JSON.stringify(captured, null, 2));
const all = Object.values(captured);
console.log(
  "captured:", all.length,
  "success:", all.filter((c) => c.event?.success === true).length,
  "failure:", all.filter((c) => c.event?.success !== true).length,
  "->", updateFixture ? "UPDATED tracked fixture" : `wrote ${outPath.pathname} (tracked fixture unchanged)`,
);
// R8-5: leave NO artifact behind on the default path, so a reproduction run
// cannot perturb the working tree at all. The temp capture is removed after the
// summary is printed; the tracked fixture is never written unless opted in.
if (!updateFixture) {
  try {
    rmSync(outPath);
  } catch {
    // best-effort: a failure to remove the temp file is not fatal
  }
}