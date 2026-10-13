=== RPC / LIFECYCLE FIXTURE PROVENANCE RECORD ===
recorded_at_utc: 2026-10-10T07:49:13Z
updated_utc:     2026-10-11 (R7-4 repair: status is now runtime-produced)
objective: continuation-restructure-for-multi-day-operation (CORR4, TODO-RPCFIX)

--- CAPTURED (real runtime) ---
file: tests/fixtures/subagents-rpc-captured.json
  what: 8 CORRELATED RPC REPLY ENVELOPES emitted by the INSTALLED
        pi-subagents 0.76.1 bridge itself, keyed by `requestId`.
  how:  The real exported `registerSubagentRpcBridge` (src/extension/rpc.js:690)
        was driven with a real event bus whose `on()` returns a disposer (matching
        Pi's `createEventBus`), then the REAL request topic
        `subagents:rpc:v1:request` was emitted and every reply on
        `subagents:rpc:v1:reply:<requestId>` was recorded VERBATIM.
  how the STATUS is produced (R7-4 repair):
        The bridge's `execute` is wired to the REAL exported status renderer
        `inspectSubagentStatus` (`src/runs/background/run-status.js:351`), which
        reads a REAL on-disk async-run tree written by the recipe. The
        `Run:`/`State:` headers are therefore produced by pi-subagents' OWN status
        code over real run state, NOT synthesized by the recipe.
        HISTORY: the FIRST version of this recipe injected a mock `execute` that
        hand-wrote `Run: ${runId}\nState: ${state}` from a lookup table. Review
        `b6728c5e` (R7-4) correctly rejected that: it proved only the
        wrapper/envelope SHAPE, with invented status text. The mock is GONE.
  recipe: tests/fixtures/capture/capture-rpc-envelopes.mjs
          tests/fixtures/capture/peer-dep-hooks.mjs  (resolves `typebox`,
          `pi-subagents`, and the `@earendil-works/*` runtime packages Pi
          provides; non-invasive, no writes to any installed package)
          tests/fixtures/capture/peer-dep-register.mjs  (installs the hook)
        Run:  node --import ./tests/fixtures/capture/peer-dep-register.mjs \
                     ./tests/fixtures/capture/capture-rpc-envelopes.mjs
              (the leading `./` on BOTH paths is REQUIRED: bare `tests/...` is
              resolved as a package name and fails with
              `ERR_MODULE_NOT_FOUND: Cannot find package 'tests'`)
  coverage: active (running, queued), FINALIZED-PAUSED, terminal
            (complete, failed, stopped), an ABSENT run id, and a no-target
            request.
  KEY CONFIRMATION: a REAL targeted status reply carries `text` (with the
    `Run:`/`State:` header) AND `fleet` AND `asyncSnapshot` TOGETHER. This is the
    fact PG3/F2 depend on, and it is confirmed from a real envelope rather than
    inferred from source: the projected `asyncSnapshot` rides alongside the
    authoritative `text`, which is exactly why the snapshot must not be trusted
    as liveness.
  REAL ERROR CASE: an absent run yields `success: false` with
    `error.code === "execution_failed"` (NOT the invented `success: true` the
    previous mock produced).
  REPRODUCIBILITY NOTE: the captured bytes are NOT byte-identical between runs.
    The only field that varies is `data.asyncSnapshot.generatedAt`, a real
    runtime timestamp produced by the genuine snapshot projection. Everything
    the fixture is used to assert (the `Run:`/`State:` text, `success`, `error`,
    `details`, `fleet`/`asyncSnapshot` presence, and all correlation ids) is
    stable. Re-running the recipe therefore yields an equivalent, not identical,
    file - which is expected for a RUNTIME capture and is not a defect. The
    hash below pins the specific captured revision used for validation.

--- SOURCE-DERIVED (NOT runtime-captured) ---
file: tests/fixtures/subagents-child-status-derived.json
  what: `subagent.child-status` payloads for the lifecycle statuses
        started / stopping / stopped.
  how:  Built field-for-field from the REAL emit site
        `src/runs/background/async-job-tracker.js:283-301`, INCLUDING its guard
        (`status` must be one of started/stopping/stopped) and its optional
        `childRunId`.
  HONEST LIMIT: these are NOT captured from a running tracker. The tracker
    reads child-status records out of a job's `events.jsonl` control file and
    requires substantial live job state to drive; that harness was not built.
    The SHAPE is authoritative (taken from the emitter), but the events
    themselves were not observed at runtime.
  The emit site itself is real evidence for PG4's premise: the tracker emits
  all three lifecycle statuses on the SAME topic this extension observes, so
  treating every event on it as terminal would retire live provenance.

--- HASHES ---
699ef3ece649783d1712dfdcd5c5e4df61f9ef280cfa6f15f660dac547d306c8  tests/fixtures/subagents-rpc-captured.json
b0500ce37ede31a931fce855255328c763f13d0025803590d11643e0932de3b6  tests/fixtures/subagents-child-status-derived.json
6a012cf7d5d058956cfc7e60bf73c3ca4417bf70bd28ffa7e2ee92060fc2aa9e  tests/fixtures/capture/capture-rpc-envelopes.mjs
604d697fd56e3cb4345612d14fc4f96c2d6e7bbe16dcea50063a49e258a1b5c8  tests/fixtures/capture/peer-dep-hooks.mjs
e9e47d1c6d39cebac673e2ed4616fbcd46983df868a84e5249a0723837200414  tests/fixtures/capture/peer-dep-register.mjs

NOTE (R8-5): the recorded RPC-fixture hash was STALE at `47c90c3b…` (R7-era) and
then written as `b5af6214…`; BOTH were wrong. The root cause was that the
recipe OVERWROTE this tracked fixture on every run, so the committed bytes were
never stable and three different hash claims drifted apart. The recipe is now
NON-MUTATING by default: it writes the capture to a temp path
(`tests/fixtures/.capture-<pid>.json`) and leaves `subagents-rpc-captured.json`
untouched. Regenerate the tracked fixture DELIBERATELY with
`node --import ./tests/fixtures/capture/peer-dep-register.mjs \
   ./tests/fixtures/capture/capture-rpc-envelopes.mjs --update-fixture`
(or `SUBAGENTS_CAPTURE_UPDATE_FIXTURE=1`), and update this table afterwards.
All hashes above are the ACTUAL committed values (`shasum -a 256 <path>`).

CORRECTION (Oracle Review 56, R2): the `capture-rpc-envelopes.mjs` row read
`0070baa5…` until this correction. That value was the CORR36-era hash; the file
legitimately changed at CORR37 to `6a012cf7…` (the R15 comment-only scope note,
syntax-checked, not imported by the suite) and the canonical manifests have
declared `6a012cf7…` since `manifest-s1s2-corr37.txt`. This table was not updated
in the same pass, so it contradicted the manifest while still calling itself
current — exactly the drift class the note below describes. Measured live now:
`6a012cf7d5d058956cfc7e60bf73c3ca4417bf70bd28ffa7e2ee92060fc2aa9e`.
The `child-status` row is unaffected.
The child-status fixture hash is CORRECT as `b0500ce3…` — an earlier revision of
this file mis-recorded it as `b02bfe56…`.