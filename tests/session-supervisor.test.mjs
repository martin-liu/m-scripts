// Tests for the marker-declared session supervisor extension.
//
// The design under test has no classifier, no background-work liveness probe,
// and no interrupt grammar: the model DECLARES its status on the final line of
// its final assistant message, and the extension reads it synchronously. Every
// assertion below therefore drives the real factory through `pi.on` and reads
// the proposal or the OSC notification it produces.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, chmodSync, appendFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const tsPath = fileURLToPath(
  new URL("../shell/config/pi/extensions/session-supervisor.ts", import.meta.url),
);

// Peek at the installed Node's type-stripping support without failing the run.
function supportProbe() {
  const probe = spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "-e",
      'import(process.argv[1]).then(()=>console.log("ok"))',
      tsPath,
    ],
    { encoding: "utf8" },
  );
  return probe.status === 0 && probe.stdout.includes("ok");
}

async function loadSupervisor() {
  const loaded = await import(tsPath).catch((error) => ({ __error: error }));
  if (loaded && typeof loaded.default === "function") return loaded;
  throw loaded.__error ?? new Error("session-supervisor.ts did not expose a factory");
}

const mod = await loadSupervisor();

/**
 * The pi-subagents bus topic constants, read from the INSTALLED package.
 *
 * R6-1 was a single-character error (`subagent.child-status` instead of
 * `subagent:child-status`) that subscribed the terminal-observation feature to a
 * channel the runtime never emits on - and every test masked it by emitting
 * through our OWN constant. Binding our constants to the runtime's real exports
 * makes that class of typo impossible to reintroduce silently.
 *
 * Resolved best-effort: if the package is not present the pin is skipped rather
 * than failing the suite for an environment reason.
 */
const realTopics = await (async () => {
  const candidates = [
    process.env.PI_SUBAGENTS_TYPES_PATH,
    "/Users/martinliu/.pi/agent/npm/node_modules/pi-subagents/src/shared/types.js",
  ].filter((value) => typeof value === "string" && value.length > 0);
  for (const candidate of candidates) {
    try {
      const loaded = await import(candidate);
      return {
        asyncStarted: loaded.SUBAGENT_ASYNC_STARTED_EVENT,
        childStatus: loaded.SUBAGENT_CHILD_STATUS_EVENT,
      };
    } catch {
      // try the next candidate
    }
  }
  return null;
})();

test("R6-1: our observed-run topics equal pi-subagents' real bus constants", () => {
  if (realTopics === null) {
    // Environment cannot supply the package; skip rather than assert against a
    // guess. The literal pin below still guards the exact strings.
    return;
  }
  assert.equal(
    mod.OBSERVED_RUN_START_TOPIC,
    realTopics.asyncStarted,
    "the START topic must be pi-subagents' real async-started channel",
  );
  assert.equal(
    mod.OBSERVED_RUN_TERMINAL_TOPIC,
    realTopics.childStatus,
    "the TERMINAL topic must be pi-subagents' real child-status channel",
  );
});

test("R6-1: the observed-run topics are COLON-separated channels, not dotted payload types", () => {
  // The dotted spelling is the event payload's `type`, never the bus channel.
  // Pinned as literals so the guard holds even where the package is absent.
  assert.equal(mod.OBSERVED_RUN_START_TOPIC, "subagent:async-started");
  assert.equal(mod.OBSERVED_RUN_TERMINAL_TOPIC, "subagent:child-status");
  assert.ok(
    !mod.OBSERVED_RUN_TERMINAL_TOPIC.includes("subagent."),
    "the terminal topic must not use the dotted payload-type spelling",
  );
});
const { DEFAULT_MAX_CONTINUATIONS, HARD_MAX_CONTINUATIONS, resolveMaxContinuations } = mod;
const WAIT_VERIFICATION_MS = mod.WAIT_VERIFICATION_MS;
const WAIT_RECHECK_MS = mod.WAIT_RECHECK_MS;
const WAIT_BRIDGE_NOT_READY_RETRY_MS = mod.WAIT_BRIDGE_NOT_READY_RETRY_MS;
const TASK_CONFIRM_RETRY_MS = mod.TASK_CONFIRM_RETRY_MS;
const MAX_CONTINUATIONS = 2; // Finite fixture for exhaustion tests; not the runtime default.

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

/** Fake Pi API: records handlers from `pi.on` and `pi.exec` calls. */
function makePi(exec) {
  const handlers = new Map();
  const calls = [];
  return {
    handlers,
    calls,
    on(event, handler) {
      const list = handlers.get(event) ?? [];
      list.push(handler);
      handlers.set(event, list);
    },
    exec(...args) {
      calls.push(args);
      if (exec) return exec(...args);
      return undefined;
    },
    emit(event, payload, ctx) {
      const returned = [];
      for (const handler of handlers.get(event) ?? []) returned.push(handler(payload, ctx));
      return returned;
    },
  };
}

const UI = { hasUI: true, mode: "tui" };
const HEADLESS = { hasUI: false, mode: "print" };
const RPC = { hasUI: true, mode: "rpc" };
const OSC_NOTIFY = "\x1b]777;notify;Pi;Session needs attention\x07";
const OSC_INVALID_PLACEMENT =
  "\x1b]777;notify;Pi;Marker ignored - use a final column-zero STATUS line after a blank line, outside quotes/code\x07";
const OSC_EMPTY_PAYLOAD =
  "\x1b]777;notify;Pi;Marker ignored - put the payload on the SAME line as the status word\x07";
const OSC_AMBIGUOUS =
  "\x1b]777;notify;Pi;Marker ignored - conflicting STATUS declarations; emit one marker\x07";
const OSC_BUDGET_EXHAUSTED =
  "\x1b]777;notify;Pi;Automatic continuation budget exhausted - work remains\x07";

// Capture stdout writes made by the extension.
//
// The node:test reporter emits its own TAP records through
// `process.stdout.write`. A stub that swallowed every write would capture those
// reporter records too, so a test's own result could vanish from the report. The
// stub therefore records the chunk and forwards it to the original write.
function captureStdout(write) {
  const original = process.stdout.write.bind(process.stdout);
  const chunks = [];
  process.stdout.write = (chunk) => {
    chunks.push(String(chunk));
    if (write) return write(chunk);
    return original(chunk);
  };
  return {
    chunks,
    restore() {
      process.stdout.write = original;
    },
  };
}

// Drive registration through the actual default factory, honoring the
// ZELLIJ_PANE_ID environment fallback used by the extension.
function registerViaDefault(write, env) {
  const previous = process.env.ZELLIJ_PANE_ID;
  if (env && "ZELLIJ_PANE_ID" in env) {
    if (env.ZELLIJ_PANE_ID === undefined) delete process.env.ZELLIJ_PANE_ID;
    else process.env.ZELLIJ_PANE_ID = env.ZELLIJ_PANE_ID;
  }
  const pi = makePi();
  mod.default(pi);
  const out = captureStdout(write);
  const restore = () => {
    out.restore();
    if (previous === undefined) delete process.env.ZELLIJ_PANE_ID;
    else process.env.ZELLIJ_PANE_ID = previous;
  };
  return { pi, out, restore };
}

/** The registered handler for one event. */
const handlerFor = (pi, event) => pi.handlers.get(event)[0];

// ---------------------------------------------------------------------------
// Message and event builders
// ---------------------------------------------------------------------------

/** An assistant message whose text is exactly `text`. */
const assistant = (text) => ({ role: "assistant", content: [{ type: "text", text }] });
/** A user message with `text`. */
const user = (text) => ({ role: "user", content: [{ type: "text", text }] });
/** An assistant message carrying only thinking, as extended thinking produces. */
const thinking = (text) => ({ role: "assistant", content: [{ type: "thinking", text }] });
/** An assistant message with no content parts at all. */
const assistantWithParts = (parts) => ({ role: "assistant", content: parts });
/** An assistant message that also made a tool call: metadata, not a declaration.
 *
 * The canonical Pi shape is `{type:"toolCall", id, name, arguments}` — the
 * installed host 1.1.0 persists exactly this and never the `tool_call` alias.
 * Building the fixture with the NON-native spelling previously masked the
 * product defect where only `tool_call` was excluded. */
const toolCall = (text) => ({
  role: "assistant",
  content: [
    { type: "text", text },
    { type: "toolCall", id: "call_1", name: "bash", arguments: "{}" },
  ],
});

toolCall._name = "toolCall";

/**
 * An assistant message with a text part plus a tool-call part in EITHER
 * spelling. Used to prove the product excludes the canonical `toolCall` shape
 * as well as the legacy `tool_call` alias.
 */
const toolCallWithSpelling = (text, spelling) => ({
  role: "assistant",
  content: [
    { type: "text", text },
    { type: spelling, id: "call_1", name: "bash", arguments: "{}" },
  ],
});

/**
 * A boundary event whose projection is the shared user request followed by
 * `tail` (the messages under test).
 */
function boundaryEvent(tail, over = {}) {
  return {
    type: "agent_before_settle",
    outcome: "completed",
    continue: false,
    entries: [],
    context: { contextMessages: [user("do it"), ...tail], canContinue: false },
    ...over,
  };
}

const sessionView = (messages) => ({ buildSessionProjection: () => ({ messages }) });
const settleEvent = () => ({ type: "agent_settled" });

/** Run one boundary call and report whether it proposed a continuation. */
async function proposes(pi, branch, over = {}) {
  return handlerFor(pi, "agent_before_settle")(boundaryEvent(branch, over), UI);
}

// ---------------------------------------------------------------------------
// Registration and the notification transport (unchanged behaviour)
// ---------------------------------------------------------------------------

test("module exposes a default-exported extension factory", () => {
  assert.equal(supportProbe(), true, "installed Node must strip types for this suite");
  assert.equal(typeof mod.default, "function");
});

test("default factory registers every lifecycle handler via pi.on", () => {
  const pi = makePi();
  mod.default(pi);
  assert.deepEqual(
    [...pi.handlers.keys()].sort(),
    [
      "agent_before_settle",
      "agent_settled",
      "before_agent_start",
      "input",
      "message_start",
      "session_before_compact",
      "session_compact",
      "session_compact_failed",
      "session_shutdown",
      "session_start",
      "session_tree",
      "ui_prompt_start",
    ],
  );
  // Exactly one handler per event: a duplicate would double-charge the budget
  // or emit two notifications for one settlement.
  for (const event of pi.handlers.keys()) {
    assert.equal(pi.handlers.get(event).length, 1, event);
  }
});

test("the two observed-run topics are subscribed exactly once, and only when a bus supports it", () => {
  // The ledger that verifies a user escalation is fed by observing async run
  // lifecycle. Each topic must be registered ONCE: a duplicate would record a
  // run twice and, worse, a second listener is a second place for divergence.
  const bus = makeBus(() => undefined);
  const pi = makePi();
  pi.events = bus;
  mod.registerSessionSupervisor(pi, {});
  assert.deepEqual(
    bus.subscriptions.sort(),
    [mod.OBSERVED_RUN_START_TOPIC, mod.OBSERVED_RUN_TERMINAL_TOPIC].sort(),
    "exactly the two observed-run topics, once each",
  );
  assert.equal(bus.listeners.get(mod.OBSERVED_RUN_START_TOPIC).length, 1);
  assert.equal(bus.listeners.get(mod.OBSERVED_RUN_TERMINAL_TOPIC).length, 1);

  // A bus without `on`, or one that refuses a subscription, must not throw and
  // must leave the ledger empty - which can only make an escalation unverified.
  const busless = makePi();
  busless.events = { request: () => undefined };
  assert.doesNotThrow(() => mod.registerSessionSupervisor(busless, {}));
  const refusing = makePi();
  refusing.events = {
    on() {
      throw new Error("no such topic");
    },
  };
  assert.doesNotThrow(() => mod.registerSessionSupervisor(refusing, {}));
});

test("the notification transport emits the exact OSC payload and zellij args", () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "pane-7" });
  try {
    pi.emit("agent_settled", settleEvent(), UI);
    assert.deepEqual(out.chunks, [OSC_NOTIFY]);
    assert.deepEqual(pi.calls, [
      ["zellij", ["pipe", "--name", "zellij-attention::waiting::pane-7"]],
    ]);
  } finally {
    restore();
  }
});

test("the notification fires at most once per settle epoch and input resets it", () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    pi.emit("agent_settled", settleEvent(), UI);
    pi.emit("ui_prompt_start", {}, UI);
    assert.equal(out.chunks.length, 1, "one notification per epoch");

    pi.emit("input", {}, UI);
    pi.emit("ui_prompt_start", {}, UI);
    assert.equal(out.chunks.length, 2, "a new request opens a new epoch");
  } finally {
    restore();
  }
});

test("outside zellij no pipe runs but the OSC notification still fires", () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    pi.emit("agent_settled", settleEvent(), UI);
    assert.deepEqual(out.chunks, [OSC_NOTIFY]);
    assert.deepEqual(pi.calls, []);
  } finally {
    restore();
  }
});

test("a pane id in the event payload overrides the environment", () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "env-pane" });
  try {
    pi.emit("agent_settled", { paneId: "event-pane" }, UI);
    assert.deepEqual(out.chunks, [OSC_NOTIFY]);
    assert.deepEqual(pi.calls, [
      ["zellij", ["pipe", "--name", "zellij-attention::waiting::event-pane"]],
    ]);
  } finally {
    restore();
  }
});

test("a malformed event payload still notifies without a pane id", () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    for (const payload of [undefined, null, "text", 42]) {
      pi.emit("agent_settled", payload, UI);
    }
    assert.equal(out.chunks.length, 1, "dedupe still holds across malformed payloads");
    assert.deepEqual(pi.calls, []);
  } finally {
    restore();
  }
});

/**
 * Standardout and exec are isolated from each other: the panic of one must not
 * suppress the other, and neither may escape to the caller.
 */
test("stdout and exec failures are isolated from each other and from the caller", () => {
  // stdout.write throws: exec must still run.
  {
    const { pi, restore } = registerViaDefault(() => {
      throw new Error("stdout closed");
    }, { ZELLIJ_PANE_ID: "pane-a" });
    try {
      assert.doesNotThrow(() => pi.emit("agent_settled", {}, UI));
      assert.deepEqual(pi.calls, [
        ["zellij", ["pipe", "--name", "zellij-attention::waiting::pane-a"]],
      ]);
    } finally {
      restore();
    }
  }

  // exec throws synchronously: no exception escapes and the OSC was written.
  {
    const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "pane-b" });
    pi.exec = () => {
      throw new Error("exec failed");
    };
    try {
      assert.doesNotThrow(() => pi.emit("agent_settled", {}, UI));
      assert.deepEqual(out.chunks, [OSC_NOTIFY]);
    } finally {
      restore();
    }
  }

  // A host without `exec` at all must not throw.
  {
    const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "pane-c" });
    delete pi.exec;
    try {
      assert.doesNotThrow(() => pi.emit("agent_settled", {}, UI));
      assert.deepEqual(out.chunks, [OSC_NOTIFY]);
    } finally {
      restore();
    }
  }
});

test("a rejected exec promise is caught without an unhandled rejection", async () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "pane-r" });
  const unhandled = [];
  const onUnhandled = (reason) => {
    unhandled.push(reason);
  };
  process.on("unhandledRejection", onUnhandled);
  try {
    pi.exec = (...args) => {
      pi.calls.push(args);
      return Promise.reject(new Error("exec rejected"));
    };
    assert.doesNotThrow(() => pi.emit("agent_settled", {}, UI));
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(unhandled, [], "rejected exec promise must not go unhandled");
    assert.ok(out.chunks.includes(OSC_NOTIFY), "the OSC notification still fires");
  } finally {
    process.off("unhandledRejection", onUnhandled);
    restore();
  }
});

/**
 * Headless suppression is decided by `mode`, not by `hasUI`.
 *
 * Pi sets `hasUI` on the RPC surface too, where a terminal notification is
 * meaningless; `mode === "tui"` is the only honest test. It also fixes the old
 * `hasUI`-based leak that notified over RPC.
 */
test("notification needs ctx.mode === 'tui' and never sets the dedupe flag otherwise", () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "pane-9" });
  try {
    for (const ctx of [HEADLESS, RPC, { hasUI: true, mode: "json" }, undefined, {}]) {
      pi.emit("agent_settled", settleEvent(), ctx);
      pi.emit("ui_prompt_start", {}, ctx);
    }
    assert.deepEqual(out.chunks, [], "no notification outside a TUI");
    assert.deepEqual(pi.calls, []);

    // The dedupe flag must still be clear, so a later TUI settle notifies.
    pi.emit("agent_settled", settleEvent(), UI);
    assert.deepEqual(out.chunks, [OSC_NOTIFY]);
    assert.equal(pi.calls.length, 1);
  } finally {
    restore();
  }
});

// ---------------------------------------------------------------------------
// Marker detection: the narrowed contract
//
// A status line declares only when it is the FINAL NON-BLANK LINE of the final
// assistant message, starts at COLUMN ZERO, is not code, and is preceded by a
// BLANK LINE (or opens the message). Anything else is `unknown`, which the
// plugin answers by NOTIFYING. The blank-line rule replaces Markdown container
// analysis: after a blank line a column-zero line is always top level, and
// without one it is always container content. Both halves were verified against
// a reference CommonMark parser.
// ---------------------------------------------------------------------------

const CONTINUE = "Work remains.\n\nSTATUS:CONTINUE add the missing tests";
const WAIT = "I dispatched the child run.\n\nSTATUS:WAIT subagent 3c1 complete";
const DONE = "Everything the request asked for is in place.\n\nSTATUS:DONE";
const BLOCKED = "I cannot proceed.\n\nSTATUS:BLOCKED repository write access";
const FAILED = "The build is broken.\n\nSTATUS:FAILED cargo test exits 101";

test("each status word in its payload shape is recognized", () => {
  assert.deepEqual(mod.readDeclaredMarker(assistant(CONTINUE)), {
    status: "continue",
    payload: "add the missing tests",
  });
  assert.deepEqual(mod.readDeclaredMarker(assistant(WAIT)), {
    status: "wait",
    payload: "subagent 3c1 complete",
  });
  assert.deepEqual(mod.readDeclaredMarker(assistant(DONE)), { status: "done", payload: "" });
  assert.deepEqual(mod.readDeclaredMarker(assistant(BLOCKED)), {
    status: "blocked",
    payload: "repository write access",
  });
  assert.deepEqual(mod.readDeclaredMarker(assistant(FAILED)), {
    status: "failed",
    payload: "cargo test exits 101",
  });
});

test("a status line opening the message needs no preceding blank line", () => {
  assert.equal(mod.declaredStatusOf(assistant("STATUS:DONE")), "done");
  assert.equal(mod.declaredStatusOf(assistant("STATUS:CONTINUE next step")), "continue");
});

test("a status line directly beneath prose does not declare", () => {
  // The safe loss: a genuine-looking declaration inside a paragraph is read as
  // "not sure" so the user is notified rather than auto-continued.
  assert.equal(mod.declaredStatusOf(assistant("Work remains.\nSTATUS:CONTINUE x")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("Done here.\nSTATUS:DONE")), "unknown");
});

test("a status line after a blank line declares even below a container", () => {
  // This is the whole point of the blank-line rule: a blank line closes every
  // open Markdown container, so the line after it is always top level.
  assert.equal(mod.declaredStatusOf(assistant("> Example:\n\nSTATUS:CONTINUE x")), "continue");
  assert.equal(mod.declaredStatusOf(assistant("1. item\n\nSTATUS:DONE")), "done");
  assert.equal(mod.declaredStatusOf(assistant("- item\n\nSTATUS:DONE")), "done");
  assert.equal(mod.declaredStatusOf(assistant("> a\n> b\n\nSTATUS:DONE")), "done");
  assert.equal(mod.declaredStatusOf(assistant("prose\n\n\nSTATUS:DONE")), "done");
});

test("a status line continuing a container is not a declaration", () => {
  // Without a blank line the line is container content: quoted, listed, nested,
  // or a lazy continuation. All of these are `unknown`, never `continue`.
  const container = [
    "> Example:\nSTATUS:CONTINUE x",
    "> > Example:\nSTATUS:CONTINUE x",
    "> - Example:\nSTATUS:CONTINUE x",
    "> foo\nbar\nSTATUS:CONTINUE x",
    "> Example:\n1. prose\nSTATUS:CONTINUE x",
    "> Example:\n- item\nSTATUS:CONTINUE x",
    "1. item\nSTATUS:DONE",
    "- item\nSTATUS:DONE",
    "> Example:\n    # indented\nSTATUS:DONE",
    "> Example:\n<span>\nSTATUS:DONE",
    // CORR33 false-negative correction (DEFECT A12). This row USED to assert
    // `unknown`, which the A12 rule proves WRONG. The `---` at column zero
    // cannot re-enter the quoted paragraph, so it has no heading text to absorb:
    // CommonMark emits a THEMATIC BREAK, which EXITS the blockquote and leaves
    // the declaration DOCUMENT-LEVEL. AST:
    //   document>block_quote>paragraph "Example:"  |  document>thematic_break
    //   |  document>paragraph "STATUS:DONE"
    // So `done` is the correct status. The `===` sibling below is NOT symmetric:
    // with no heading text `===` has no thematic-break reading and is ABSORBED
    // into the quoted paragraph, keeping its declaration DEAD - the
    // discriminating control that a naive "treat both runs alike" fix fails.
    "> Example:\n===\nSTATUS:DONE",
    // CORR34 false-negative correction (DEFECT A13). This row USED to assert
    // `unknown`, which the abandoned-leaf rule proves WRONG. An ATX heading is a
    // leaf block, so an unmarked column-zero line cannot LAZILY continue it: the
    // container is closed and the declaration is DOCUMENT-LEVEL. AST:
    //   document>block_quote>heading "Next"  |  document>paragraph "STATUS:DONE"
    // This is the SAME decisive structure as the `---` row above (a container
    // leaf block abandoned at column zero => the next column-zero line is
    // document-level); A11 taught the rule only for a heading ABOVE a fence, not
    // for a heading that is ITSELF the abandoned leaf inside the container, so
    // this row was missed. The `> more` sibling below is the genuine DEAD
    // discriminator: the extra quoted line RE-OPENS the quote with a PARAGRAPH
    // leaf, which the unmarked declaration CAN lazily continue.
    "> # Next\n> more\nSTATUS:DONE",
  ];
  for (const text of container) {
    assert.equal(mod.declaredStatusOf(assistant(text)), "unknown", JSON.stringify(text));
  }
  // The corrected rows above, asserted on their own terms as LIVE.
  assert.equal(mod.declaredStatusOf(assistant("> Example:\n---\nSTATUS:DONE")), "done", "--- is a thematic break exiting the container");
  assert.equal(mod.declaredStatusOf(assistant("> # Next\nSTATUS:DONE")), "done", "an ATX heading leaf abandoned at column zero is document-level");
});

test("A13: an ATX heading leaf abandoned at column zero makes the declaration document-level", async () => {
  // DEFECT A13 (CORR34). An ATX heading is a LEAF block, and CommonMark lets
  // only a PARAGRAPH be continued lazily. So when a container's leaf is a
  // heading (not a paragraph), an unmarked column-zero line CLOSES the container
  // and is DOCUMENT-LEVEL. `> # Next` / `STATUS:DONE` has AST
  //   document>block_quote>heading "Next"  |  document>paragraph "STATUS:DONE"
  // exactly like the A12 thematic-break shape. Before this fix the heading was
  // classified as a paragraph leaf and the declaration was swallowed as a lazy
  // continuation (status `unknown`, no proposal) - the false negative A13.
  assert.equal(
    mod.declaredStatusOf(assistant("> # Next\nSTATUS:DONE")),
    "done",
    "ATX heading leaf abandoned at column zero => STATUS:DONE is document-level",
  );
  // The REAL settle-time surface: a column-zero CONTINUE beneath an abandoned
  // heading leaf must produce an `agent_before_settle` PROPOSAL, not silence.
  // This is the exact "STATUS:CONTINUE ... but stop" failure the objective
  // forbids; the parser surface alone would not prove the run actually continues.
  for (const [label, text] of [
    ["backtick-family", "> # Next\nSTATUS:CONTINUE p"],
    ["deeper-atx", "> ### Next\nSTATUS:CONTINUE p"],
  ]) {
    const pi = makePi();
    mod.registerSessionSupervisor(pi, {});
    const ctx = { ...UI, isIdle: () => true };
    pi.emit("input", { type: "input", text: "request", source: "interactive", streamingBehavior: undefined }, ctx);
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "request" }, ctx);
    pi.emit("message_start", { type: "message_start", message: { role: "user", content: "request" } }, ctx);
    const proposal = await proposes(pi, [assistant(text)]);
    assert.equal(proposal?.continue, true, `${label}: CONTINUE beneath an abandoned heading leaf must propose`);
    assert.equal((proposal?.entries ?? []).length, 1, `${label}: exactly one continuation entry`);
  }
  // The same rule on the `USER_QUESTION` sibling surface.
  assert.deepEqual(
    mod.userQuestionLines("> # Next\nUSER_QUESTION: q"),
    ["q"],
    "a document-level USER_QUESTION beneath an abandoned heading leaf is the parent's question",
  );
});

test("A13 discriminator: a re-opened quoted PARAGRAPH keeps the declaration DEAD", () => {
  // The load-bearing control: adding `> more` RE-OPENS the blockquote with a
  // PARAGRAPH leaf, which the unmarked declaration below CAN lazily continue.
  //   document>block_quote>heading "Next"  |  document>block_quote>paragraph
  //   "more" + softbreak "STATUS:DONE"
  // A blanket "any heading above the declaration makes it live" fix fails HERE.
  assert.equal(
    mod.declaredStatusOf(assistant("> # Next\n> more\nSTATUS:DONE")),
    "unknown",
    "`> more` restores a paragraph leaf inside the quote => still DEAD",
  );
  assert.equal(
    mod.declaredStatusOf(assistant("> # Next\n> STATUS:DONE")),
    "unknown",
    "a declaration that stays quoted is not a declaration",
  );
  // A SECOND quoted heading is still an abandoned heading leaf => the unmarked
  // line below it is document-level again.
  assert.equal(
    mod.declaredStatusOf(assistant("> # Next\n> # Again\nSTATUS:DONE")),
    "done",
    "a second quoted heading leaf re-establishes the abandoned-leaf rule",
  );
});

test("A14: an abandoned HTML-block or indented-code leaf at column zero makes the declaration document-level", async () => {
  // DEFECT A14 (CORR35). The abandoned-leaf rule (a leaf block a column-zero
  // line cannot lazily continue => that line is document-level) was applied to
  // paragraphs (A12), thematic breaks (A12), headings (A13) and fenced code, but
  // NOT to the OTHER two leaf-block types whose column-zero abandonment the
  // parent confirmed by AST: an HTML block and an indented code block. Two
  // independent CommonMark parsers (commonmark@0.31.2 and markdown-it's
  // commonmark preset) agree on every AST cited here; each row is the parser's
  // OWN first-text-node verdict.
  //
  // HTML block: `> <div>` / `STATUS:DONE` has AST
  //   document>block_quote>html_block "<div>" | document>paragraph "STATUS:DONE"
  // The declaration is DOCUMENT-LEVEL and MUST be live. Before this fix the
  // `<div>` line was classified as a PARAGRAPH leaf, so the unmarked line was
  // swallowed as a lazy continuation (status `unknown`) - the false negative.
  assert.equal(
    mod.declaredStatusOf(assistant("> <div>\nSTATUS:DONE")),
    "done",
    "HTML block abandoned at column zero => STATUS:DONE is document-level",
  );
  // Indented code: `> text` / `>` / `>     code` / `STATUS:DONE` has AST
  //   document>block_quote>[paragraph "text", code_block "code\\n"]
  //   | document>paragraph "STATUS:DONE"
  // The `>` line is a BLANK content line that ENDS the paragraph; the indented
  // `code` is then a code-block leaf, abandoned by the column-zero declaration.
  assert.equal(
    mod.declaredStatusOf(assistant("> text\n>\n>     code\nSTATUS:DONE")),
    "done",
    "an indented code block abandoned at column zero => document-level",
  );
  // The REAL settle-time surface for the CONTINUE input: a column-zero CONTINUE
  // beneath an abandoned HTML-block leaf must PROPOSE, not go silent. This is
  // the exact "STATUS:CONTINUE ... but stop" failure the objective forbids.
  for (const [label, text] of [
    ["html block", "> <div>\nSTATUS:CONTINUE p"],
    ["indented code", "> text\n>\n>     code\nSTATUS:CONTINUE p"],
  ]) {
    const pi = makePi();
    mod.registerSessionSupervisor(pi, {});
    const ctx = { ...UI, isIdle: () => true };
    pi.emit("input", { type: "input", text: "request", source: "interactive", streamingBehavior: undefined }, ctx);
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "request" }, ctx);
    pi.emit("message_start", { type: "message_start", message: { role: "user", content: "request" } }, ctx);
    const proposal = await proposes(pi, [assistant(text)]);
    assert.equal(proposal?.continue, true, `${label}: CONTINUE beneath an abandoned leaf must propose`);
    assert.equal((proposal?.entries ?? []).length, 1, `${label}: exactly one continuation entry`);
  }
  // The same rule on the `USER_QUESTION` sibling surface.
  assert.deepEqual(
    mod.userQuestionLines("> <div>\nUSER_QUESTION: q"),
    ["q"],
    "a document-level USER_QUESTION beneath an abandoned HTML-block leaf is the parent's question",
  );
});

test("A14 greedy: an HTML block ABSORBS container-continued lines, so the declaration below it is document-level (LIVE)", async () => {
  // The GREEDY half of the HTML-block leaf, and a PARENT CONTRACT DEFECT #15
  // corrected by ruling: the contract asserted `> <div>` / `> more` /
  // `STATUS:DONE` DEAD, but a type-6 HTML block continues (inside the open
  // quote) until a blank line, so `> more` is BLOCK CONTENT, not a re-opened
  // paragraph. AST (both parsers agree):
  //   document>block_quote>html_block "<div>\nmore" | document>paragraph "STATUS:DONE"
  // The declaration is DOCUMENT-LEVEL => LIVE. Leaving it DEAD would be the
  // `STATUS:CONTINUE ... but stop` failure the user forbids.
  for (const [label, text, expected] of [
    ["<div> single line", "> <div>\n> more\nSTATUS:DONE", "done"],
    ["<div> type-6", "> <div>\nSTATUS:DONE", "done"],
    ["<table> type-6", "> <table>\n> more\nSTATUS:DONE", "done"],
    ["<x> type-7", "> <x>\n> more\nSTATUS:DONE", "done"],
  ]) {
    assert.equal(mod.declaredStatusOf(assistant(text)), expected, label);
  }
  // The REAL settle-time surface for the greedy CONTINUE row.
  for (const [label, text] of [
    ["html block greedy", "> <div>\n> more\nSTATUS:CONTINUE p"],
    ["table type-6 greedy", "> <table>\n> more\nSTATUS:CONTINUE p"],
  ]) {
    const pi = makePi();
    mod.registerSessionSupervisor(pi, {});
    const ctx = { ...UI, isIdle: () => true };
    pi.emit("input", { type: "input", text: "request", source: "interactive", streamingBehavior: undefined }, ctx);
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "request" }, ctx);
    pi.emit("message_start", { type: "message_start", message: { role: "user", content: "request" } }, ctx);
    const proposal = await proposes(pi, [assistant(text)]);
    assert.equal(proposal?.continue, true, `${label}: CONTINUE must propose`);
    assert.equal((proposal?.entries ?? []).length, 1, `${label}: exactly one continuation entry`);
  }
});

test("A14 controls: a declaration INSIDE an open HTML block, or a container still owning the line, stays DEAD", () => {
  // GENUINELY-DEAD controls (each verified against the parser): the declaration
  // is INSIDE the container or INSIDE the still-open HTML block.
  const dead = [
    // `> more` after an indented code block opens a PARAGRAPH (code blocks are
    // not greedy) => AST document>block_quote>[paragraph, code_block, paragraph
    // "more"+STATUS:DONE] => INSIDE the quote => DEAD.
    "> text\n>\n>     code\n> more\nSTATUS:DONE",
    // `# H` is single-line, so `> more` re-opens the quote with a paragraph =>
    // AST document>block_quote>[heading, paragraph "more"+STATUS:DONE] => DEAD.
    "> # H\n> more\nSTATUS:DONE",
    // The declaration is ITSELF `>`-marked, i.e. INSIDE the still-open HTML
    // block => AST document>block_quote>html_block "<div>\nSTATUS:DONE" => DEAD.
    "> <div>\n> STATUS:DONE",
    "> <div>\n> more\n> STATUS:DONE",
    // A BLANK `>` line ends the HTML block; `> more` then opens a paragraph and
    // the column-zero declaration is its lazy continuation => DEAD.
    "> <div>\n>\n> more\nSTATUS:DONE",
    // A type-2 comment block ends at `-->` on its OWN line, so `> more` is a
    // NEW quoted paragraph => the declaration is a lazy continuation => DEAD.
    "> <!-- c -->\n> more\nSTATUS:DONE",
  ];
  for (const text of dead) {
    assert.equal(mod.declaredStatusOf(assistant(text)), "unknown", JSON.stringify(text));
  }
});

test("A15: an abandoned container leaf that is the LAST OF SEVERAL leaves makes the declaration document-level (all shapes, all statuses)", async () => {
  // DEFECT A15 (CORR36). A13/A14 taught the abandoned-leaf rule only when the
  // non-paragraph leaf was the container's ONLY content. When a PARAGRAPH
  // PRECEDES it, the leaf line (`> # H2`) was read as a LAZY continuation of the
  // paragraph, so the container's real LAST leaf was never established and the
  // column-zero declaration below it was swallowed. AST for every shape:
  //   document>block_quote>[paragraph, heading "H2"] | document>paragraph "STATUS:..."
  // The declaration is DOCUMENT-LEVEL, so it MUST be live for all three statuses.
  // The `a < b` / `1 < 2` shapes prove the rule does not depend on the
  // paragraph's CONTENT: they are ordinary paragraphs, NOT HTML blocks (the
  // parser confirms `document>block_quote>paragraph`), and the interrupt rule
  // for a following ATX heading applies regardless.
  const shapes = [
    ["text", "> text\n> # H2"],
    ["a < b", "> a < b\n> # H2"],
    ["1 < 2", "> 1 < 2\n> # H2"],
  ];
  for (const [label, head] of shapes) {
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:DONE`)),
      "done",
      `${label}: abandoned heading leaf last-of-several => STATUS:DONE document-level`,
    );
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:CONTINUE p`)),
      "continue",
      `${label}: abandoned heading leaf last-of-several => STATUS:CONTINUE document-level`,
    );
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:WAIT subagent x complete`)),
      "wait",
      `${label}: abandoned heading leaf last-of-several => STATUS:WAIT document-level`,
    );
    // The REAL settle-time surface: the CONTINUE row must PROPOSE, not go silent - the
    // exact "STATUS:CONTINUE ... but stop" failure the user objective forbids.
    const pi = makePi();
    mod.registerSessionSupervisor(pi, {});
    const ctx = { ...UI, isIdle: () => true };
    pi.emit("input", { type: "input", text: "request", source: "interactive", streamingBehavior: undefined }, ctx);
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "request" }, ctx);
    pi.emit("message_start", { type: "message_start", message: { role: "user", content: "request" } }, ctx);
    const proposal = await proposes(pi, [assistant(`${head}\nSTATUS:CONTINUE p`)]);
    assert.equal(proposal?.continue, true, `${label}: CONTINUE beneath an abandoned last leaf must propose`);
    assert.equal((proposal?.entries ?? []).length, 1, `${label}: exactly one continuation entry`);
  }
});

test("A15 analogous: an abandoned HTML-block last leaf of several also makes the declaration document-level", () => {
  // The SAME abandoned-last-leaf rule for a non-paragraph leaf of ANOTHER type:
  // a type-6 HTML block that is the container's LAST leaf, preceded by a
  // paragraph. AST: document>block_quote>[paragraph "text", html_block "<div>"]
  // | document>paragraph "STATUS:DONE" => LIVE. Before the fix the `<div>` line
  // was a lazy paragraph continuation, so the declaration was swallowed.
  assert.equal(
    mod.declaredStatusOf(assistant("> text\n> <div>\nSTATUS:DONE")),
    "done",
    "an HTML-block leaf last-of-several => document-level",
  );
  // An indented code block that is the last of several already resolves (the
  // blank `>` line ends the paragraph first); confirm it stays LIVE.
  assert.equal(
    mod.declaredStatusOf(assistant("> text\n>\n>     code\n> \n>     code2\nSTATUS:DONE")),
    "done",
    "an indented-code leaf last-of-several => document-level",
  );
});

test("A15 discriminator: a leaf that FOLLOWS the abandoned leaf INSIDE the container keeps the declaration DEAD", () => {
  // The load-bearing control: the rule fires only when the non-paragraph leaf is
  // the container's LAST leaf. If ANOTHER leaf or content FOLLOWS inside the
  // container, the declaration is still INSIDE the quote => DEAD.
  //   document>block_quote>[heading, paragraph "more"+STATUS:DONE] => DEAD
  //   document>block_quote>[paragraph, code_block, paragraph "more"+STATUS:DONE] => DEAD
  //   document>block_quote>[paragraph, html_block "<div>\nmore"] then the greedy
  //     block absorbs `> more`; declaration is document-level => LIVE (ruling A).
  assert.equal(
    mod.declaredStatusOf(assistant("> # H\n> more\nSTATUS:DONE")),
    "unknown",
    "a leaf FOLLOWS the quoted heading INSIDE the quote => still DEAD",
  );
  assert.equal(
    mod.declaredStatusOf(assistant("> text\n>\n>     code\n> more\nSTATUS:DONE")),
    "unknown",
    "a leaf FOLLOWS the quoted code block INSIDE the quote => still DEAD",
  );
  assert.equal(
    mod.declaredStatusOf(assistant("> <div>\n> more\nSTATUS:DONE")),
    "done",
    "a greedy HTML block absorbs `> more`, so the declaration is document-level (LIVE)",
  );
  // A paragraph followed by a SECOND quoted paragraph is still a paragraph leaf,
  // which the unmarked declaration CAN lazily continue => DEAD.
  assert.equal(
    mod.declaredStatusOf(assistant("> text\n> more\nSTATUS:DONE")),
    "unknown",
    "a quoted paragraph-followed-by-paragraph => lazy continuation => DEAD",
  );
});

test("CORR37 A16: an EMPTY list item as the container's last leaf makes the declaration document-level (both lists, all statuses)", async () => {
  // DEFECT A16 (CORR37). A bare list marker (`-`, `1.`) is a real EMPTY list item
  // in CommonMark, not the line's own prose. The parser treated the bare marker
  // as content (`spaces.length === 0` => break), so no item was recorded and the
  // column-zero declaration below was swallowed as if the marker line were a
  // paragraph. AST for every shape:
  //   document>list>item>paragraph "text" | document>list>item "" | document>paragraph "STATUS:..."
  // The declaration is DOCUMENT-LEVEL, so it MUST be live for all three statuses.
  for (const [label, head] of [
    ["bullet", "- text\n-"],
    ["ordered", "1. text\n1."],
    ["ordered-10", "10. text\n10."],
  ]) {
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:DONE`)),
      "done",
      `${label}: empty list item last leaf => STATUS:DONE document-level`,
    );
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:CONTINUE p`)),
      "continue",
      `${label}: empty list item last leaf => STATUS:CONTINUE document-level`,
    );
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:WAIT subagent x complete`)),
      "wait",
      `${label}: empty list item last leaf => STATUS:WAIT document-level`,
    );
    // The REAL settle-time surface: the CONTINUE row must PROPOSE, not go silent.
    const pi = armed();
    const proposal = await proposes(pi, [assistant(`${head}\nSTATUS:CONTINUE p`)]);
    assert.equal(proposal?.continue, true, `${label}: CONTINUE beneath an empty item must propose`);
    assert.equal((proposal?.entries ?? []).length, 1, `${label}: exactly one continuation entry`);
  }
  // A bare marker alone (no preceding item) is the same shape.
  assert.equal(
    mod.declaredStatusOf(assistant("-\nSTATUS:DONE")),
    "done",
    "a lone bare marker opens an empty item => declaration document-level",
  );
});

test("CORR37 A16 discriminator: a bare marker that CONTINUES the list keeps the declaration DEAD", () => {
  // The rule fires only when the empty item CLOSES the list. If the marker opens
  // an item that still holds the following content, the declaration stays INSIDE
  // the list => DEAD.
  //   document>list>item>paragraph "textSTATUS:DONE" => DEAD (STATUS in the item)
  //   document>list>item>[paragraph, paragraph "moreSTATUS:DONE"] => DEAD
  assert.equal(
    mod.declaredStatusOf(assistant("- text\n- STATUS:DONE")),
    "unknown",
    "a marker whose item holds the STATUS line stays DEAD",
  );
  assert.equal(
    mod.declaredStatusOf(assistant("- text\n- more\nSTATUS:DONE")),
    "unknown",
    "an unmarked line continues the empty item's paragraph => still DEAD",
  );
  // A marker line whose item is indented into is NOT a document-level brake.
  assert.equal(
    mod.declaredStatusOf(assistant("- text\n-\n- STATUS:DONE")),
    "unknown",
    "a further item holding the STATUS line stays DEAD",
  );
});

test("CORR37 A17: a HEADING with 1-3 content-indent columns (or a tab) after a quote/list marker makes the declaration document-level", async () => {
  // DEFECT A17 (CORR37). `leafBlockOf` tested the ATX-heading regex against
  // UNTRIMMED content, so a heading carrying its own 1-3 columns of indentation
  // (`>  # H`, `>\t# H`, `- text` / `   # H`) was misclassified as a paragraph
  // leaf and the document-level declaration below was swallowed. AST:
  //   document>block_quote>heading "H" | document>paragraph "STATUS:..."
  //   document>list>item>[paragraph, heading "H"] | document>paragraph "STATUS:..."
  for (const [label, head] of [
    ["quote-1sp", ">  # H"],
    ["quote-tab", ">\t# H"],
    ["quote-2sp", ">   # H"],
    ["list-3sp", "- text\n   # H"],
  ]) {
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:DONE`)),
      "done",
      `${label}: indented ATX heading leaf => STATUS:DONE document-level`,
    );
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:CONTINUE p`)),
      "continue",
      `${label}: indented ATX heading leaf => STATUS:CONTINUE document-level`,
    );
    assert.equal(
      mod.declaredStatusOf(assistant(`${head}\nSTATUS:WAIT subagent x complete`)),
      "wait",
      `${label}: indented ATX heading leaf => STATUS:WAIT document-level`,
    );
    const pi = armed();
    const proposal = await proposes(pi, [assistant(`${head}\nSTATUS:CONTINUE p`)]);
    assert.equal(proposal?.continue, true, `${label}: CONTINUE beneath an indented heading must propose`);
    assert.equal((proposal?.entries ?? []).length, 1, `${label}: exactly one continuation entry`);
  }
});

test("CORR37 A17 discriminator: a heading that is NOT the container's last leaf keeps the declaration DEAD", () => {
  // Only an ABANDONED heading leaf is the brake. A heading FOLLOWED by more
  // content inside the quote leaves the declaration inside => DEAD.
  assert.equal(
    mod.declaredStatusOf(assistant(">  # H\n> more\nSTATUS:DONE")),
    "unknown",
    "a heading followed by quoted content => declaration still DEAD",
  );
  // A 5-column-indented `#` is INDENTED CODE that is the container's LAST leaf:
  // the document-level declaration below is therefore LIVE (done), proving the
  // heading rule does not fire on code. AST: document>block_quote>code_block |
  // document>paragraph "STATUS:DONE".
  assert.equal(
    mod.declaredStatusOf(assistant(">      # H\nSTATUS:DONE")),
    "done",
    "a 5-column `#` is code, not a heading; the declaration is document-level => LIVE",
  );
});

test("CORR37 A18: a FOUR-space fence after a quoted paragraph must NOT interrupt (both delimiters)", async () => {
  // DEFECT A18 (CORR37). `startsBlockAfterParagraph` stripped up to three indent
  // columns and then `fenceDelimiterAt` stripped them AGAIN, so a FOUR-column
  // line was dedented to a legal fence and wrongly interrupted the quoted
  // paragraph. CommonMark reads four columns as INDENTED CODE, which cannot
  // interrupt. AST: document>block_quote>paragraph "p```textSTATUS:CONTINUE p"
  // => the declaration is ABSORBED => DEAD.
  for (const delim of ["```", "~~~"]) {
    assert.equal(
      mod.declaredStatusOf(assistant(`> p\n>     ${delim}text\nSTATUS:CONTINUE p`)),
      "unknown",
      `${delim}: 4-space fence after a quoted paragraph cannot interrupt => DEAD`,
    );
    const pi = armed();
    const proposal = await proposes(pi, [assistant(`> p\n>     ${delim}text\nSTATUS:CONTINUE p`)]);
    assert.ok(proposal === null || proposal?.continue !== true, `${delim}: no proposal for the absorbed declaration`);
  }
});

test("CORR37 A18 discriminator: a REAL 1-3 column fence after a quoted paragraph still interrupts (both delimiters)", () => {
  // The boundary the fix must preserve: a fence at the grammar's own 1-3 column
  // indent DOES interrupt, so the declaration below is document-level => LIVE.
  // AST: document>block_quote>code_block | document>paragraph "STATUS:..."
  for (const delim of ["```", "~~~"]) {
    for (const [label, indent] of [["1sp", " "], ["2sp", "  "], ["3sp", "   "]]) {
      assert.equal(
        mod.declaredStatusOf(assistant(`> p\n> ${indent}${delim}text\nSTATUS:CONTINUE p`)),
        "continue",
        `${delim} ${label}: a real fence after a quoted paragraph interrupts => LIVE`,
      );
    }
  }
});

test("CORR37 A19: HTML-block blank and terminator rules (types 1-5 ignore blanks; type 1 ends on any of the four closing tags)", async () => {
  // DEFECT A19 (CORR37). TWO mechanisms:
  //  (a) a blank line terminates types 6/7 ONLY, but the supervisor cleared HTML
  //      state on every physical blank AND every container-only blank;
  //  (b) CommonMark type 1 ends on a COMPLETE closing tag of ANY of
  //      script/pre/textarea/style, but the supervisor matched a PREFIX of the
  //      OPENING element.
  // Each row's expected status is the CommonMark AST (verified by parent chain).
  for (const [label, input, expected] of [
    // (a) container-only blank inside a type-2 comment is content, not a terminator
    ["comment-container-blank", "> <!--\n>\n> more\nSTATUS:CONTINUE p", "continue"],
    // (b) a NON-terminator closing tag leaves the block open and absorbs the declaration
    ["script-nonterminator", "<script>\n</scriptx>\nSTATUS:CONTINUE p", "unknown"],
    // (b) a COMPLETE closing tag of a DIFFERENT raw-text element ends the block
    ["script-closed-by-pre", "<script>\n</pre>\nSTATUS:CONTINUE p", "continue"],
    ["script-closed-by-style", "<script>\n</style>\nSTATUS:CONTINUE p", "continue"],
    ["pre-closed-by-script", "<pre>\n</script>\nSTATUS:CONTINUE p", "continue"],
    // quoted type-1 block terminated inside the quote, then quoted content holds the declaration
    ["quoted-script-pre-more", "> <script>\n> </pre>\n> more\nSTATUS:CONTINUE p", "unknown"],
    ["quoted-script-blank-pre", "> <script>\n>\n> </pre>\n> more\nSTATUS:CONTINUE p", "unknown"],
    // (a) a TOP-LEVEL type-2 block ignores a physical blank and absorbs the declaration
    ["toplevel-comment-blank", "<!--\n\nSTATUS:CONTINUE p", "unknown"],
    ["toplevel-cdata-blank", "<![CDATA[\n\nSTATUS:CONTINUE p", "unknown"],
    // a quoted type-2 block ends WITH its quote at a truly blank line => LIVE
    ["quoted-comment-trulyblank", "> <!--\n\nSTATUS:CONTINUE p", "continue"],
    // a list-item type-2 block SURVIVES a blank (list items do) => absorbs => DEAD
    ["list-comment-blank", "- <!--\n\n  STATUS:CONTINUE p", "unknown"],
    // types 2-5 terminators
    ["cdata-terminator", "<![CDATA[\n]]>\nSTATUS:CONTINUE p", "continue"],
    // type 6 is blank-terminated
    ["div-blank", "<div>\n\nSTATUS:CONTINUE p", "continue"],
  ]) {
    assert.equal(mod.declaredStatusOf(assistant(input)), expected, `${label}`);
    if (expected === "continue") {
      const pi = armed();
      const proposal = await proposes(pi, [assistant(input)]);
      assert.equal(proposal?.continue, true, `${label}: must propose`);
      assert.equal((proposal?.entries ?? []).length, 1, `${label}: exactly one entry`);
    }
  }
});

test("CORR37 A19 discriminator: a still-OPEN type-6 block absorbs the declaration, and a greedy block keeps control", () => {
  // The preserved controls: a type-6 block runs to a blank, so a NON-blank
  // following line is CONTENT and the declaration stays swallowed => DEAD, while
  // the greedy `> <div>` / `> more` shape stays LIVE (ruling A) because the
  // column-zero line below is a document paragraph.
  assert.equal(
    mod.declaredStatusOf(assistant("<div>\nmore\nSTATUS:DONE")),
    "unknown",
    "a still-open type-6 block absorbs the declaration => DEAD",
  );
  assert.equal(
    mod.declaredStatusOf(assistant("> <div>\n> more\nSTATUS:DONE")),
    "done",
    "a greedy type-6 block sets up a document-level declaration => LIVE",
  );
});

test("P1: a protocol example quoted INSIDE an actionable payload still declares", () => {
  // The real defect: `isDocumentationLine` applied the quoted-status detector to
  // the WHOLE line, so a backticked protocol example in the PAYLOAD demoted a
  // genuine column-zero CONTINUE to `unknown`. That emitted no bridge and STOPPED
  // the run - the exact "STATUS:CONTINUE ... but stop" failure this extension
  // exists to prevent. Every decoration style must keep declaring.
  for (const [label, text] of [
    ["backtick", "Work remains.\n\nSTATUS:CONTINUE add a regression for `STATUS:WAIT subagent x complete`"],
    ["backtick DONE", "Work remains.\n\nSTATUS:CONTINUE fix the `STATUS:DONE` diagnostic"],
    ["straight quote", 'Work remains.\n\nSTATUS:CONTINUE fix the "STATUS:WAIT" parser'],
    ["curly quote", "Work remains.\n\nSTATUS:CONTINUE fix the \u201cSTATUS:WAIT\u201d parser"],
  ]) {
    assert.equal(mod.declaredStatusOf(assistant(text)), "continue", label);
  }

  // The genuinely QUOTED declaration is still documentation: the mention rule
  // applies to the declaration token itself, which is where it belongs.
  assert.equal(mod.declaredStatusOf(assistant("Work remains.\n\n`STATUS:CONTINUE an example`")), "unknown");
  assert.equal(
    mod.declaredStatusOf(assistant('Work remains.\n\n"STATUS:CONTINUE an example"')),
    "unknown",
  );
});

test("P1 case-token: a lower-/mixed-case declaration with an uppercase mention in its payload declares", () => {
  // The residual silent-stop path: `mentionsQuotedStatus` built an UPPERCASE
  // token and searched case-SENSITIVELY, so a line typed `status:continue`
  // skipped its OWN declaration and found a later uppercase spelling inside the
  // payload, expanding the head over an earlier quoted mention and demoting the
  // declaration to documentation. Exact confirmations from cycle 45.
  for (const [label, text] of [
    ["lower + upper mention", "status:continue compare `status:continue` with `STATUS:continue` fixtures"],
    ["mixed + upper mention", "Status:CONTINUE compare `status:continue` with `STATUS:CONTINUE` fixtures"],
    ["upper control", "STATUS:CONTINUE compare `status:continue` with `STATUS:CONTINUE` fixtures"],
    ["lower only", "status:continue compare `status:continue` fixtures"],
    ["lower, upper in payload", "status:continue compare `STATUS:continue` fixtures"],
  ]) {
    assert.equal(mod.declaredStatusOf(assistant(text)), "continue", label);
  }
});

test("P3 indentation counts COLUMNS: space+tab is code depth, not a fence opener", () => {
  // Markdown counts columns; a space then a tab reaches column four. Counting
  // characters treated it as two and let its backticks open a fence that
  // swallowed the genuine declaration below.
  const declaration = "STATUS:CONTINUE add the regression";
  for (const [label, prefix] of [
    ["space+tab", " \t"],
    ["four spaces", "    "],
    ["tab", "\t"],
  ]) {
    const text = `${prefix}\`\`\`\n\n${declaration}`;
    // Every one of these prefixes is indented code, so the fence never opens
    // and the final declaration is reached.
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(text)),
      { status: "continue", payload: "add the regression" },
      label,
    );
    assert.equal(mod.declaredStatusOf(assistant(text)), "continue", label);
  }
});

// --- CORR30: ONE container-relative model (both delimiters everywhere) --------

/** The two CommonMark fence delimiters, so every case runs for BOTH. */
const DELIMS = [
  ["backtick", "```"],
  ["tilde", "~~~"],
];

/** A real settle-time proposal (or null) for a text body, via the factory. */
async function settleProposalFor(pi, text) {
  const result = await proposes(pi, [assistant(text)]);
  if (result === undefined || result === null) return null;
  return { continue: result.continue, entries: (result.entries ?? []).length };
}

/** LIVE = `continue` marker AND a one-entry continuation proposal. */
async function isLive(pi, text) {
  const marker = mod.readDeclaredMarker(assistant(text));
  const proposal = await settleProposalFor(pi, text);
  return (
    marker?.status === "continue" &&
    proposal !== null &&
    proposal.continue === true &&
    proposal.entries === 1
  );
}

/** EXCLUDED = no continuation proposal AND no `continue` marker. */
async function isExcluded(pi, text) {
  const marker = mod.readDeclaredMarker(assistant(text));
  const proposal = await settleProposalFor(pi, text);
  const notContinue = marker === null || marker.status !== "continue";
  return notContinue && proposal === null;
}

test("CORR30 A1: a fence opener after prose, an ATX heading, or a setext heading INTERRUPTS the paragraph (excluded)", async () => {
  // CommonMark fences interrupt paragraphs, so a fenced example after prose is
  // REAL fence content and the `STATUS:` inside it must never declare. Reading
  // the fence as a lazy paragraph continuation let it never open and the
  // example stayed live - the exact `STATUS:CONTINUE ... but stop` shape.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    for (const [kind, head] of [
      ["prose", ["prose"]],
      ["atx heading", ["# H"]],
      ["setext heading", ["H", "==="]],
    ]) {
      const text = [...head, `${d}${d}${d}text`, "", "STATUS:CONTINUE p"].join("\n");
      assert.equal(await isExcluded(pi, text), true, `${kind} ${label}`);
      assert.deepEqual(
        mod.userQuestionLines(text.replace("STATUS:CONTINUE p", "USER_QUESTION: q")),
        [],
        `${kind} ${label}: a fenced USER_QUESTION is excluded`,
      );
    }
  }
});

test("CORR30 A2: a closer followed by NBSP does NOT close the fence (excluded)", async () => {
  // CommonMark's closing grammar admits only spaces and TABS after the run;
  // `trim()` accepted a trailing NBSP and closed a fence whose tail is illegal,
  // so the declaration below read as live inside a fence CommonMark kept open.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const text = [`${d}${d}${d}text`, "code", `${d}${d}${d}\u00a0`, "", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isExcluded(pi, text), true, label);
  }
});

test("CORR30 A6: ordered-marker interruption requires the START VALUE to be exactly 1", async () => {
  // `10.`/`11)` cannot interrupt a paragraph, so the fence stays inside the
  // quoted paragraph and the declaration is NOT document-level (excluded).
  // `01.`/`0001.` DO start at 1, so they interrupt and the fence-exit
  // declaration below is a real, top-level continuation (live).
  const pi = armed();
  for (const [label, d] of DELIMS) {
    for (const marker of ["10.", "11)"]) {
      const text = ["> paragraph", `> ${marker} ${d}${d}${d}text`, "STATUS:CONTINUE p"].join("\n");
      assert.equal(await isExcluded(pi, text), true, `${marker} ${label}`);
    }
    for (const marker of ["01.", "0001."]) {
      const text = ["> paragraph", `> ${marker} ${d}${d}${d}text`, "STATUS:CONTINUE p"].join("\n");
      assert.equal(await isLive(pi, text), true, `${marker} ${label}`);
    }
  }
});

test("CORR30 A7: `USER_QUESTION` ownership is the SAME container fact the marker uses", () => {
  const bt = "```";
  // A genuine question directly beneath a CLOSED quote-fence is document level.
  assert.deepEqual(
    mod.userQuestionLines([`> ${bt}text`, "> content", "USER_QUESTION: q"].join("\n")),
    ["q"],
  );
  // A question inside a still-open quoted paragraph (the `2.` cannot interrupt)
  // belongs to the example and is NOT the parent's question.
  assert.deepEqual(
    mod.userQuestionLines(["> paragraph", `> 2. ${bt}text`, "USER_QUESTION: q"].join("\n")),
    [],
  );
  // A question lazily continuing an open quoted paragraph is equally owned.
  assert.deepEqual(
    mod.userQuestionLines(["> paragraph", "STATUS:CONTINUE example", "USER_QUESTION: q"].join("\n")),
    [],
  );
  // ADJACENT genuine questions both stay eligible, so their disagreement is
  // caught instead of silently resolving to the first.
  assert.deepEqual(
    mod.userQuestionLines(["I need a decision.", "", "USER_QUESTION: A?", "USER_QUESTION: B?"].join("\n")),
    ["A?", "B?"],
  );
});

test("CORR30 B1: a genuine declaration after a closed or exited fence is LIVE", async () => {
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const closed = ["prose", `${d}${d}${d}text`, "code", `${d}${d}${d}`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, closed), true, `closed ${label}`);
    const quoteExit = ["> paragraph", `> ${d}${d}${d}text`, "> code", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, quoteExit), true, `quote-exit ${label}`);
  }
});

test("CORR30 B3: the container stack has NO depth cap (8 AND 9 AND deeper stay LIVE)", async () => {
  // The eight-container cap silently returned a partial view, so the ninth
  // container was dropped and every line beneath read as top level. Depth 8 must
  // keep working (boundary) and 9/16/32/64 must ALSO work.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    for (const depth of [1, 2, 3, 4, 5, 8, 9, 16, 32, 64]) {
      const pfx = "> ".repeat(depth);
      const text = [`${pfx}${d}${d}${d}text`, `${pfx}content`, "STATUS:CONTINUE p"].join("\n");
      assert.equal(await isLive(pi, text), true, `depth ${depth} ${label}`);
    }
    // MIXED nesting (quote/list alternating) is EXCLUDED: the declaration never
    // leaves the alternating containers, so reading it as top level would be a
    // false positive - the discriminating companion to the depth cases.
    const mixed = ["> - > - > - " + `${d}${d}${d}text`, "> - > - > - content", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isExcluded(pi, mixed), true, `mixed ${label}`);
  }
});

test("CORR30 B4: a list item retains ownership of a later continuation-line fence", async () => {
  // The scanner used to derive containers only from the CURRENT line's markers,
  // so it forgot the list item before a later indented fence and lost the
  // declaration below it. The carried stack now keeps the item open.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const a = ["- intro", "", `  ${d}${d}${d}text`, "  content", "STATUS:CONTINUE p"].join("\n");
    const b = [`-     ${d}${d}${d}text`, "  content", `  ${d}${d}${d}`, "STATUS:CONTINUE p"].join("\n");
    const c = [`-      ${d}${d}${d}text`, "  content", `  ${d}${d}${d}`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, a), true, `B4a ${label}`);
    assert.equal(await isLive(pi, b), true, `B4b ${label}`);
    assert.equal(await isLive(pi, c), true, `B4c ${label}`);
    // CONTROL: 1-4 separator siblings still work, and an over-wide separator's
    // own indented content stays inside the item (excluded, not promoted).
    const inside = [`- ${d}${d}${d}text`, "  STATUS:CONTINUE inside", `  ${d}${d}${d}`].join("\n");
    assert.equal(await isExcluded(pi, inside), true, `B4-inside ${label}`);
  }
});

test("CORR30 B5: list columns are CONTAINER-RELATIVE, so changing quote indentation still resolves", async () => {
  // The saved list column used to include the opener's outer quote indentation;
  // re-entry compared that ABSOLUTE column against later lines whose quote
  // prefix occupied fewer columns, so the item (and its fence) were lost.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const wide = ["   > - " + `${d}${d}${d}text`, ">   content", ">   " + `${d}${d}${d}`, "STATUS:CONTINUE p"].join("\n");
    const narrow = [" > - " + `${d}${d}${d}text`, ">  content", ">  " + `${d}${d}${d}`, "STATUS:CONTINUE p"].join("\n");
    const tabbed = ["> -\t" + `${d}${d}${d}text`, ">\tcontent", ">\t" + `${d}${d}${d}`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, wide), true, `B5 wide ${label}`);
    assert.equal(await isLive(pi, narrow), true, `B5 narrow ${label}`);
    assert.equal(await isLive(pi, tabbed), true, `B5 tab ${label}`);
    // DISCRIMINATING: a top-level ordered item whose continuation lines carry an
    // extra quote prefix. The old independent per-line view measured the item's
    // column out of the line's own (shifted) prefix and LOST the declaration;
    // the carried, container-relative stack keeps the item and closes the fence.
    const shifted = ["10. " + `${d}${d}${d}text`, "    > content", "    > " + `${d}${d}${d}`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, shifted), true, `B5 shifted ${label}`);
  }
});

test("CORR30 CONTROLS: every fenced/indented/non-interrupting declaration stays EXCLUDED", async () => {
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const neverClosed = [`${d}${d}${d}text`, "code", "STATUS:CONTINUE p"].join("\n");
    const reopened = [`${d}${d}${d}text`, "code", `${d}${d}${d}`, `${d}${d}${d}text`, "STATUS:CONTINUE p"].join("\n");
    const trulyFenced = ["prose", `${d}${d}${d}`, "STATUS:CONTINUE p", `${d}${d}${d}`].join("\n");
    const stillOpen = [`${d}${d}${d}text`, "code", "", "STATUS:CONTINUE p"].join("\n");
    for (const [name, text] of [
      ["never-closed", neverClosed],
      ["reopened", reopened],
      ["truly-fenced", trulyFenced],
      ["still-open-then-blank", stillOpen],
    ]) {
      assert.equal(await isExcluded(pi, text), true, `${name} ${label}`);
    }
    for (const marker of ["2.", "10.", "11)"]) {
      const text = ["> quoted paragraph", `> ${marker} ${d}${d}${d}text`, "STATUS:CONTINUE p", ""].join("\n");
      assert.equal(await isExcluded(pi, text), true, `non-interrupt ${marker} ${label}`);
    }
  }
  assert.equal(await isExcluded(pi, "    STATUS:CONTINUE p"), true, "four-space indented code");
  // CONTROL E-live: a fence CLOSED before a blank line leaves the declaration
  // at document level - a real continuation, distinguishing a true close from
  // an accidental one.
  assert.equal(await isLive(pi, ["```text", "code", "```", "", "STATUS:CONTINUE p"].join("\n")), true);
});

// --- CORR31: false positives (A8) and false negatives (A10) in the ONE model --

test("CORR31 A8: a fenced example whose container lifetime/indent is misread stays EXCLUDED (both delimiters)", async () => {
  // A8a: `> - ``` ` opens a fence inside quote>list; the BLANK ends the quote,
  // so CommonMark ends the nested list with it. Retaining the orphaned list
  // width re-entered the list on the next line and opened a fence that swallowed
  // the following declaration - a REAL false positive
  // (`document>code_block`). A8b: the item's saved width OMITTED the marker's
  // own leading indentation, so `  ``` ` (2 spaces) re-entered an item whose
  // content begins at column 3 and inverted close-vs-open, again opening a
  // document-level fence over the declaration. Both must stay EXCLUDED.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const a8a = [`> - ${d}text`, "", `  ${d}text`, "STATUS:CONTINUE p"].join("\n");
    const a8b = [` - ${d}text`, `  ${d}`, "", "STATUS:CONTINUE p"].join("\n");
    for (const [name, text] of [
      ["A8a-quote-list-blank-fresh-opener", a8a],
      ["A8b-leading-indent-list-closer", a8b],
    ]) {
      assert.equal(await isExcluded(pi, text), true, `${name} ${label}`);
      assert.deepEqual(
        mod.userQuestionLines(text.replace("STATUS:CONTINUE p", "USER_QUESTION: q")),
        [],
        `${name} ${label}: a fenced USER_QUESTION is excluded`,
      );
    }
  }
});

test("CORR31 A10: a declaration after an UNCLOSED fence exited by a heading/wide item is LIVE (both delimiters)", async () => {
  // A10 is the false NEGATIVE mirror of A8: an unclosed container fence is
  // exited by a document-level block, so CommonMark places the declaration in a
  // `document>paragraph` and it MUST be LIVE. `10000. intro` opens a wide
  // ordered item; the item-content fence opens and closes, then the col-0
  // declaration is document level. `> ```text` is exited by the heading `# H`,
  // itself `document>heading`. The former domino was read as a lazy paragraph
  // continuation (the raw 7-space line failed the local 3-space strip) and the
  // latter because a heading leaf was misclassified as a continuable paragraph.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const wide = ["10000. intro", `       ${d}text`, "       code", `       ${d}`, "STATUS:CONTINUE p"].join("\n");
    const heading = [`> ${d}text`, "# H", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, wide), true, `wide-ordered ${label}`);
    assert.equal(await isLive(pi, heading), true, `container-exit-heading ${label}`);
    // The companion class-boundary controls keep passing: a heading (or setext
    // heading) BEFORE a CLOSED fence is handled, so the close - not the heading
    // - is what made the declaration document level.
    const atxClosed = ["## H", `${d}text`, "code", `${d}`, "STATUS:CONTINUE p"].join("\n");
    const setextClosed = ["H", "===", `${d}text`, "code", `${d}`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, atxClosed), true, `atx-then-closed ${label}`);
    assert.equal(await isLive(pi, setextClosed), true, `setext-then-closed ${label}`);
  }
});

test("CORR32 A11: a SETEXT heading exiting an unclosed container fence is a real heading, so the declaration below is LIVE (both delimiters)", async () => {
  // A11 is the SETEXT sibling of the A10 ATX case, and the two CommonMark ASTs
  // are byte-identical in shape:
  //   document > block_quote > code_block | (exit) document > heading | paragraph
  // The A10 fix recognised only an ATX heading (`# H`), so the SAME container
  // exit written as a setext heading (`H` then `===`/`---`, which SPANS TWO
  // LINES) left the declaration read as a lazy paragraph continuation of the
  // heading text and the genuine `STATUS:CONTINUE` was LOST - the exact
  // "CONTINUE ... but stop" failure. The rule must be heading-AGNOSTIC.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    // `=` and `-` setext underlines, each exiting the fence's container.
    for (const [underline, kind] of [["===", "level-1"], ["---", "level-2"]]) {
      const text = [`> ${d}text`, "H", underline, "STATUS:CONTINUE p"].join("\n");
      assert.equal(
        await isLive(pi, text),
        true,
        `A11 setext ${kind} exit ${label}`,
      );
      // The declaration is the SAME fact for the sibling `USER_QUESTION`
      // surface: a question in that position must be seen as top level.
      assert.deepEqual(
        mod.userQuestionLines(text.replace("STATUS:CONTINUE p", "USER_QUESTION: q")),
        ["q"],
        `A11 setext ${kind} exit ${label}: USER_QUESTION is document level`,
      );
    }
  }
});

test("CORR32 A11 contrast: only a heading that RE-ENTERS the paragraph's containers is a setext heading", async () => {
  // The two shapes below have IDENTICAL surface syntax but OPPOSITE CommonMark
  // results, so they are the discriminating controls that keep the heading-
  // agnostic rule honest:
  //   - `> paragraph` / `H` / `===` - `H` is an UNMARKED lazy continuation, so
  //     the paragraph still lives inside the quote and `===` cannot re-enter it;
  //     the whole thing is ONE `block_quote>paragraph` => DEAD (correct).
  //   - `> H` / `> ===` / `<dedented STATUS>` - the underline RE-ENTERS the quote
  //     and forms a heading INSIDE it; the dedented declaration is then a NEW
  //     top-level block => LIVE.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const absorbed = ["> paragraph", "H", "===", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isExcluded(pi, absorbed), true, `setext-absorbed ${label}`);
    const quotedHeading = ["> H", "> ===", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, quotedHeading), true, `quoted setext heading dedented ${label}`);
    const quotedHeadingThenQuoted = ["> H", "> ===", "> STATUS:CONTINUE p"].join("\n");
    assert.equal(await isExcluded(pi, quotedHeadingThenQuoted), true, `quoted setext heading then quoted ${label}`);
    // The prior fix's ATX exit and the list-inside-quote control must not
    // regress: the heading-agnostic rule must leave both exactly as they were.
    assert.equal(await isLive(pi, ["> " + d + "text", "# H", "STATUS:CONTINUE p"].join("\n")), true, `ATX exit still live ${label}`);
    assert.equal(await isExcluded(pi, ["> " + d + "text", "- item", "STATUS:CONTINUE p"].join("\n")), true, `list-inside-quote still dead ${label}`);
  }
  // A setext underline needs a PARAGRAPH above it: the same characters with no
  // preceding line are one paragraph, and `= =` (interior space) is never an
  // underline. Both therefore remain DEAD - the guards against over-reach.
  assert.equal(await isExcluded(pi, ["===", "STATUS:CONTINUE p"].join("\n")), true, "bare === is a paragraph, not a heading");
  assert.equal(await isExcluded(pi, ["H", "= =", "STATUS:CONTINUE p"].join("\n")), true, "interior space is not a setext underline");
  assert.equal(await isLive(pi, ["H", "===", "STATUS:CONTINUE p"].join("\n")), true, "standalone setext heading then paragraph is live");
  assert.equal(await isLive(pi, ["===", "===", "STATUS:CONTINUE p"].join("\n")), true, "=== over a === paragraph forms a setext heading");
});

test("CORR33 A12: a BARE `---` thematic break exiting a container leaves the declaration LIVE (both delimiters)", async () => {
  // A12 is a FALSE NEGATIVE. A `---` line is a SETEXT UNDERLINE only when a
  // preceding PARAGRAPH with heading text can absorb it; otherwise it is a
  // THEMATIC BREAK, which EXITS the container and leaves the declaration below
  // it DOCUMENT-LEVEL. Before the fix the walk classified the `---` as a
  // paragraph leaf, so the following `STATUS:` line was swallowed as a lazy
  // continuation and the genuine `STATUS:CONTINUE` was LOST - the exact
  // "CONTINUE ... but stop" failure. CommonMark ancestry (commonmark@0.31.2):
  //   `> ``` / --- / STATUS`  = block_quote>code_block | thematic_break
  //                             | document>paragraph "STATUS:CONTINUE p"
  //   `> paragraph / H / --- / STATUS` = block_quote>paragraph "paragraphH"
  //                             | thematic_break | document>paragraph
  //     "STATUS:CONTINUE p"
  // Both are DOCUMENT-LEVEL => LIVE.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    // A12-1: the `---` follows an unclosed container FENCE (previous leaf is a
    // code_block, not a paragraph), so nothing can absorb it.
    const afterFence = ["> " + d + "text", "---", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, afterFence), true, `A12 after-fence ${label}`);
    // A12-2: the `---` dedents out of a quoted paragraph that already consumed
    // `H` as a lazy continuation, so it cannot re-enter the quote either.
    const afterQuotePara = ["> paragraph", "H", "---", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, afterQuotePara), true, `A12 after-quoted-paragraph ${label}`);
    // The declaration is the SAME fact for the sibling `USER_QUESTION` surface:
    // a question in that position is document level.
    assert.deepEqual(
      mod.userQuestionLines(afterFence.replace("STATUS:CONTINUE p", "USER_QUESTION: q")),
      ["q"],
      `A12 after-fence USER_QUESTION is document level ${label}`,
    );
    assert.deepEqual(
      mod.userQuestionLines(afterQuotePara.replace("STATUS:CONTINUE p", "USER_QUESTION: q")),
      ["q"],
      `A12 after-quoted-paragraph USER_QUESTION is document level ${label}`,
    );
  }
});

test("CORR33 A12 contrast: `===` with no heading text is ABSORBED into a container paragraph and stays DEAD (both delimiters)", async () => {
  // This is the DISCRIMINATING property that forbids a "treat both runs alike"
  // fix: `===` is NEVER a thematic break (a run of `=` is only a setext
  // underline or paragraph text), so with no heading text it does not exit the
  // container - it is ABSORBED as lazy paragraph continuation, and the
  // declaration inside that paragraph is DEAD. CommonMark ancestry:
  //   `> ``` / === / STATUS` = block_quote>code_block | document>paragraph
  //                             "===STATUS:CONTINUE p"   <-- decl INSIDE
  //   `> paragraph / H / === / STATUS` = block_quote>paragraph
  //                             "paragraphH===STATUS:CONTINUE p"  <-- INSIDE
  // Both DEAD is CORRECT.
  const pi = armed();
  for (const [label, d] of DELIMS) {
    const absorbedAfterFence = ["> " + d + "text", "===", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isExcluded(pi, absorbedAfterFence), true, `=== absorbed after-fence ${label}`);
    const absorbedAfterQuotePara = ["> paragraph", "H", "===", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isExcluded(pi, absorbedAfterQuotePara), true, `=== absorbed after-quoted-paragraph ${label}`);
    // A one-line quoted paragraph has the same asymmetry: `---` exits (LIVE),
    // `===` is absorbed (DEAD). The external AST check confirms this shape.
    // A one-line quoted paragraph has the same asymmetry: `---` exits the
    // quote, exposing a DOCUMENT-LEVEL declaration; `===` is absorbed. `DONE`
    // proposes no continuation, so these are asserted on `declaredStatusOf`
    // rather than the settle-time proposal.
    assert.equal(mod.declaredStatusOf(assistant(["> Example:", "---", "STATUS:DONE"].join("\n"))), "done", `bare --- exits quote ${label}`);
    assert.equal(mod.declaredStatusOf(assistant(["> Example:", "===", "STATUS:DONE"].join("\n"))), "unknown", `bare === absorbed into quote ${label}`);
  }
});

test("CORR33 A12 guards: a short dash run or a dash list-marked line is NOT a thematic break", async () => {
  // The new thematic-break predicate must admit ONLY a genuine break, so the
  // guards against over-reach stay DEAD: `--` (fewer than three markers) is
  // ordinary paragraph text, and `- item` is a LIST, not a break.
  const pi = armed();
  assert.equal(await isExcluded(pi, ["> ```text", "--", "STATUS:CONTINUE p"].join("\n")), true, "two dashes are paragraph text");
  assert.equal(await isExcluded(pi, ["> ```text", "- item", "STATUS:CONTINUE p"].join("\n")), true, "dash list item is not a break");
});

test("CORR31 A9: a USER_QUESTION example owned by a container lazy continuation is NOT the parent's question", async () => {
  // A9: `> USER_QUESTION: example` opens a blockquote paragraph; the unmarked
  // following line is a LAZY continuation of that example paragraph
  // (CommonMark: ONE `block_quote>paragraph`), NOT a document-level question.
  // The former rule promoted every `USER_QUESTION:` line to a sibling
  // declaration regardless of container, so the example text counted as the
  // parent's question. Sibling status is a TOP-LEVEL fact only.
  assert.deepEqual(
    mod.userQuestionLines(["> USER_QUESTION: example", "USER_QUESTION: q"].join("\n")),
    [],
    "quoted example lazy continuation",
  );
  assert.deepEqual(
    mod.userQuestionLines(["- USER_QUESTION: example", "USER_QUESTION: q"].join("\n")),
    [],
    "list example lazy continuation",
  );
  // Adjacent TOP-LEVEL questions remain siblings, so their disagreement is
  // caught; a genuine question after a container-fence CLOSE stays eligible.
  assert.deepEqual(
    mod.userQuestionLines(["I need a decision.", "", "USER_QUESTION: A?", "USER_QUESTION: B?"].join("\n")),
    ["A?", "B?"],
    "adjacent top-level questions",
  );
  assert.deepEqual(
    mod.userQuestionLines(["> \u0060\u0060\u0060text", "> content", "> \u0060\u0060\u0060", "USER_QUESTION: q"].join("\n")),
    ["q"],
    "question after a closed quoted fence is document level",
  );
});

test("P4 backtick stripping never crosses the token/payload boundary", () => {
  // A payload's closing backtick is executable content, not decoration.
  assert.deepEqual(mod.readDeclaredMarker(assistant("STATUS:CONTINUE fix `STATUS:DONE`")), {
    status: "continue",
    payload: "fix `STATUS:DONE`",
  });
  // A payload-bearing DONE must be REJECTED, not accepted as payload-free.
  const done = mod.readDeclaredMarker(assistant("STATUS:DONE ```"));
  assert.equal(done.status, "unknown");
  assert.equal(done.problem, "unexpected-payload");
  // Genuine decoration still parses: one closing backtick after the word.
  assert.deepEqual(mod.readDeclaredMarker(assistant("STATUS:DONE`")), { status: "done", payload: "" });
  assert.deepEqual(mod.readDeclaredMarker(assistant("`STATUS:DONE`")), null);
});

test("P5: a fence opener sharing a list-marker line is recognized, so a real closer closes it", async () => {
  // The opener shares the item's marker line (`- ```text`), the closing fence is
  // a REAL closer (not another opener), and the declaration below the blank line
  // is therefore OUTSIDE every fence. Reading the opener as prose left the real
  // closer to be misread as an opener, placing the final declaration inside a
  // phantom fence: `ineligible-line` and a null proposal - the exact
  // "CONTINUE then stop" failure.
  const text = ["- ```text", "  example", "  ```", "", "STATUS:CONTINUE add a regression"].join("\n");
  assert.deepEqual(mod.readDeclaredMarker(assistant(text)), {
    status: "continue",
    payload: "add a regression",
  });
  // DISCRIMINATING COMPANION: a marker genuinely INSIDE the same list-nested
  // fence is still excluded, so the fix did not simply stop tracking fences.
  const fenced = ["- ```text", "  STATUS:CONTINUE inside", "  ```"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(fenced)), "unknown");
  // A tilde fence opened on a list-marker line behaves identically.
  const tildeFenced = ["- ~~~text", "  STATUS:CONTINUE inside", "  ~~~"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(tildeFenced)), "unknown");
  // And the recognized declaration produces a RUNNABLE bridge, not just a
  // status word: the fix must reach the continuation proposal the user needs.
  const pi = armed();
  const proposal = await proposes(pi, [assistant(text)]);
  assert.ok(proposal, "a CONTINUE outside the fence must propose a continuation");
  assert.equal(proposal.continue, true);
  assert.equal(proposal.entries.length, 1);
  assert.match(proposal.entries[0].content, /STATUS:CONTINUE add a regression/);
});

test("P6: a backtick fence with a backtick in its info string opens no phantom fence", async () => {
  // CommonMark forbids a backtick in a BACKTICK fence's info string, so
  // ```` ```bad`info ```` is not a fence opener at all. Accepting it opened a
  // phantom fence that swallowed the genuine declaration below.
  const text = "```bad`info\n\nSTATUS:CONTINUE add a regression";
  assert.deepEqual(mod.readDeclaredMarker(assistant(text)), {
    status: "continue",
    payload: "add a regression",
  });
  // DISCRIMINATING COMPANION: VALID openers still open. A backtick fence whose
  // info string has no backtick swallows the marker below it...
  assert.equal(
    mod.declaredStatusOf(assistant("```text\n\nSTATUS:CONTINUE inside")),
    "unknown",
  );
  // ...a bare run still opens...
  assert.equal(mod.declaredStatusOf(assistant("```\nSTATUS:CONTINUE inside")), "unknown");
  // ...and a TILDE fence MAY carry a backtick in its info string, so it still
  // opens (the constraint is specific to backtick fences).
  assert.equal(
    mod.declaredStatusOf(assistant("~~~bad`info\n\nSTATUS:CONTINUE inside")),
    "unknown",
  );
  // The recognized declaration produces a runnable bridge.
  const pi = armed();
  const proposal = await proposes(pi, [assistant(text)]);
  assert.ok(proposal, "a CONTINUE below an invalid fence must propose a continuation");
  assert.equal(proposal.continue, true);
  assert.equal(proposal.entries.length, 1);
  assert.match(proposal.entries[0].content, /STATUS:CONTINUE add a regression/);
});

test("P7: a literal container prefix INSIDE an open fence never CLOSES it", async () => {
  // The mirror image of the user's bug. While a fence is OPEN, every later line
  // is CONTENT until a closer valid FOR THAT OPEN FENCE appears. A content line
  // may legitimately begin with a container marker (`- ``` `, `> ~~~ `); those
  // markers are literal TEXT, not a delimiter, and reading them as a closer ends
  // the region early and promotes a fenced EXAMPLE below into a live continuation
  // - a false positive that is as wrong as a missed one.
  const cases = [
    [
      "list-marker line inside a top-level backtick fence",
      ["```text", "- ```", "", "STATUS:CONTINUE must remain fenced"].join("\n"),
    ],
    [
      "quote-marker line inside a top-level tilde fence",
      ["~~~bad`info", "> ~~~  ", "", "STATUS:CONTINUE must remain fenced"].join("\n"),
    ],
  ];
  for (const [label, text] of cases) {
    // The declaration is STILL inside the unterminated fence: it must never
    // declare, so no continuation may be proposed.
    assert.notEqual(mod.declaredStatusOf(assistant(text)), "continue", label);
    const pi = armed();
    const proposal = await proposes(pi, [assistant(text)]);
    assert.ok(!proposal, `${label}: a fence-interior prefix must not propose`);
  }
});

test("P8: a CONTAINER-RELATIVE closer still closes, and the declaration below is seen", async () => {
  // The inverse discrimination: a fence nested in a container is indented to
  // that container's CONTENT COLUMN, and an absolute four-column code threshold
  // wrongly rejected the closer as indented code before the fence grammar was
  // read. Each case below has a REAL closer positioned relative to its container.
  const cases = [
    [
      "two-digit ordered marker (content column 4)",
      ["10. ```text", "    example", "    ```", "", "STATUS:CONTINUE add a regression"].join("\n"),
    ],
    [
      "stacked list markers (content column 4)",
      ["- - ```text", "    example", "    ```", "", "STATUS:CONTINUE add a regression"].join("\n"),
    ],
    [
      "quote container closed at a blank line (fence does not extend past it)",
      ["> ```text", "> example", "", "STATUS:CONTINUE add a regression"].join("\n"),
    ],
  ];
  for (const [label, text] of cases) {
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(text)),
      { status: "continue", payload: "add a regression" },
      label,
    );
    const pi = armed();
    const proposal = await proposes(pi, [assistant(text)]);
    assert.ok(proposal, `${label}: the visible declaration must propose a continuation`);
    assert.equal(proposal.continue, true);
  }
});

test("P9: a fence's enclosing CONTAINER identity and lifetime decide closure (both directions)", async () => {
  // Nine rounds found a neighbour of the fence fix: the model still lacked
  // CONTAINER IDENTITY and LIFETIME. A closer was matched against an absolute
  // content column and ANY blank line closed a nested fence. Both are wrong.
  // The model now records, per open fence, the CONTAINER STACK it was opened
  // inside, and a closer must RE-ENTER every one of those containers.
  //
  // (a) A QUOTED closer is genuine for a fence opened inside a quote, and the
  // top-level opener that follows opens a NEW fence that swallows the line
  // below it - so the declaration must NOT be seen. The old model rejected the
  // `> ``` ` closer outright and let the blank close the obsolete fence.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const quoted = [
      `> ${delim}${delim}${delim}text`,
      "> example",
      `> ${delim}${delim}${delim}`,
      `${delim}${delim}${delim}text`,
      "",
      "STATUS:CONTINUE must remain fenced",
    ].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(quoted)), "unknown", `${label}: the quoted closer must close and the new top-level fence must swallow the line`);
    const pi = armed();
    assert.ok(!(await proposes(pi, [assistant(quoted)])), `${label}: a fenced declaration must not propose`);
  }

  // (b) A blank line INSIDE a list item does NOT end the item, so it does NOT
  // close the fence opened there; the genuine closer still closes it and the
  // declaration below is therefore live. The old model closed the fence at the
  // blank, misread the genuine closer as an opener, and reported `unknown`.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const blank = [
      `- ${delim}${delim}${delim}text`,
      "  example",
      "",
      `  ${delim}${delim}${delim}`,
      "",
      "STATUS:CONTINUE add a regression",
    ].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(blank)),
      { status: "continue", payload: "add a regression" },
      `${label}: a blank inside a list item must not close the fence`,
    );
    const pi = armed();
    const proposal = await proposes(pi, [assistant(blank)]);
    assert.ok(proposal, `${label}: the live declaration must propose a continuation`);
    assert.equal(proposal.continue, true);
  }

  // (c) A fence closed by CONTAINER END exposes NOTHING below: an unquoted line
  // ends the quote, which ends the fence with its container, so a marker that
  // follows an UNCLOSED quoted fence is still outside every fence.
  const containerEnd = [
    "> ```text",
    "> example",
    "",
    "STATUS:CONTINUE add a regression",
  ].join("\n");
  assert.deepEqual(
    mod.readDeclaredMarker(assistant(containerEnd)),
    { status: "continue", payload: "add a regression" },
    "the blank ends the quote and the fence with it, so the declaration is live",
  );

  // (d) NESTED QUOTE-IN-LIST: the fence is enclosed by a list item AND a quote,
  // so its closer needs BOTH containers. A marker inside is excluded; a genuine
  // declaration after the closer is seen.
  const nestedInside = ["- > ```text", "  > STATUS:CONTINUE inside", "  > ```"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(nestedInside)), "unknown", "a marker inside the nested fence is excluded");
  const nestedBelow = [
    "- > ```text",
    "  > example",
    "  > ```",
    "",
    "STATUS:CONTINUE add a regression",
  ].join("\n");
  assert.deepEqual(
    mod.readDeclaredMarker(assistant(nestedBelow)),
    { status: "continue", payload: "add a regression" },
    "the quote-prefixed closer closes the quote-in-list fence",
  );

  // (e) A closer LONGER than its opener still closes a container-nested fence;
  // a closer SHORTER than its opener does not (the length rule is unchanged).
  const longerCloser = [
    "- ````text",
    "  example",
    "  `````",
    "",
    "STATUS:CONTINUE add a regression",
  ].join("\n");
  assert.deepEqual(
    mod.readDeclaredMarker(assistant(longerCloser)),
    { status: "continue", payload: "add a regression" },
    "a longer container-relative closer closes the fence",
  );
  // CORRECTED at CORR27 (rev 83), REQUIRED BY THE GENERAL H1/H2 COORDINATE FIX -
  // the previous assertion here read
  //   assert.notEqual(mod.declaredStatusOf(assistant(shorterCloser)), "continue")
  // on the input `- ````text` / `  example` / `  ``` ` / blank / declaration.
  // That `notEqual` passed ONLY because the old model left the fence open past
  // its CONTAINER, so it encoded the very DEFECT H2 this revision fixes: the
  // reference CommonMark parser (python-commonmark; independently reproduced by
  // the parent on commonmark@0.31.2) parses that input as a list-item code block
  // ending at the container exit, with `STATUS:CONTINUE x` a TOP-LEVEL PARAGRAPH
  // - a live declaration. The length rule ITSELF is unchanged and is still
  // covered below on an input whose fence is genuinely still OPEN at the marker;
  // no check was removed. The container-exit declaration is asserted live in
  // the CORR27 regression below for BOTH delimiters.
  const shorterCloserOpenFence = ["````text", "example", "```", "", "STATUS:CONTINUE x"].join(
    "\n",
  );
  assert.notEqual(
    mod.declaredStatusOf(assistant(shorterCloserOpenFence)),
    "continue",
    "a shorter closer must not close a longer fence that is genuinely still open",
  );
});

test("P10: a container-ending line that is ALSO a fresh opener OPENS that new fence (both directions)", async () => {
  // DEFECT F: when a container-held fence ends, the SAME line must be
  // re-classified as a possible fresh opener. The old scan did `open = null;
  // changes.set(index,false); continue;`, so a line such as ``` at top level
  // BOTH ended the still-open quoted fence AND was itself an unquoted
  // top-level fence opener - but the opener was skipped, no new fence opened,
  // and the `STATUS:` line beneath it was (wrongly) accepted as live. Every
  // case below must EXCLUDE the trailing declaration: it is inside the NEW
  // fence the terminating line opens.
  //
  // Build the cases EXPLICITLY per delimiter so nothing can drift.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const quoteEnd = [
      `> ${delim}${delim}${delim}text`,
      "> example",
      `${delim}${delim}${delim}text`,
      "",
      "STATUS:CONTINUE must remain fenced",
    ].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(quoteEnd)),
      "unknown",
      `${label}: the terminating line opens a new fence that swallows the declaration`,
    );
    const pi = armed();
    assert.ok(!(await proposes(pi, [assistant(quoteEnd)])), `${label}: no bridge may be proposed`);

    // LIST-container termination has the SAME skipped-line defect: the line
    // that dedents out of the list item is also a fresh top-level opener.
    const listEnd = [
      `- ${delim}${delim}${delim}text`,
      "  example",
      `${delim}${delim}${delim}text`,
      "",
      "STATUS:CONTINUE must remain fenced",
    ].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(listEnd)),
      "unknown",
      `${label}: a dedent out of a list item that is also an opener must open the new fence`,
    );
    const piList = armed();
    assert.ok(!(await proposes(piList, [assistant(listEnd)])), `${label}: no bridge may be proposed`);
  }

  // DISCRIMINATING COMPANION: a container-ending line that is NOT an opener
  // leaves the declaration below genuinely live, so the fix did not simply stop
  // classifying container ends.
  const notAnOpener = [
    "> ```text",
    "> example",
    "plain paragraph that ends the quote",
    "",
    "STATUS:CONTINUE add a regression",
  ].join("\n");
  assert.deepEqual(
    mod.readDeclaredMarker(assistant(notAnOpener)),
    { status: "continue", payload: "add a regression" },
    "an ordinary container-ending line leaves the declaration live",
  );
});

test("P11: an over-wide list separator keeps its excess as CONTENT indent, so it is not a fence opener (both directions)", async () => {
  // DEFECT G: CommonMark retains FOUR columns of code indentation after a list
  // separator. `-     ```` ` (five spaces) is therefore INDENTED CODE, not a
  // fence opener - and the declaration below it is live. The old scan sliced
  // ALL matched whitespace away while collapsing the advance to one column,
  // discarding the line's own indent: a phantom fence opened, the blank line
  // preserved it, and the declaration was rejected as `ineligible-line` with no
  // bridge. Both delimiter types follow the same path.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const overWide = [
      `-     ${delim}${delim}${delim}text`,
      "",
      "STATUS:CONTINUE add a regression",
    ].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(overWide)),
      { status: "continue", payload: "add a regression" },
      `${label}: an over-wide separator is indented code, not a fence`,
    );
    const pi = armed();
    const proposal = await proposes(pi, [assistant(overWide)]);
    assert.ok(proposal, `${label}: the live declaration must propose a continuation`);
    assert.equal(proposal.continue, true);
    assert.equal(proposal.entries.length, 1);

    // DISCRIMINATING COMPANION: a REAL 0-3 column list-nested fence still IS a
    // fence. The declaration below it is INSIDE the fence and must stay
    // excluded, so the fix did not simply stop recognizing list-nested fences.
    const realFence = [
      `- ${delim}${delim}${delim}text`,
      "  example",
      `  ${delim}${delim}${delim}`,
      "",
      "STATUS:CONTINUE add a regression",
    ].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(realFence)),
      { status: "continue", payload: "add a regression" },
      `${label}: a real list-nested fence still closes and the declaration below is seen`,
    );
    const stillFenced = [
      `- ${delim}${delim}${delim}text`,
      `  STATUS:CONTINUE inside`,
      `  ${delim}${delim}${delim}`,
    ].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(stillFenced)),
      "unknown",
      `${label}: a marker inside a real list-nested fence is still excluded`,
    );
  }
});

test("P12: a list MARKER's own width is part of the content column, so the item's fence and its declaration are located (both delimiters)", async () => {
  // DEFECT H1: `advance` measured only the SEPARATOR whitespace, so the list
  // marker's own width was omitted from BOTH the content column and the text
  // slice. For `3) ~~~audit` the opener's remainder became `") ~~~audit"` (no
  // fence opened), the real closer opened a phantom top-level fence, and the
  // genuine column-zero declaration below was rejected (`unknown` /
  // `ineligible-line`, no bridge) - the user's "CONTINUE ... but stop" failure.
  // CommonMark places the item's content column AFTER the marker + separator,
  // so `3)` + one space is column 3 and the three-space-indented fence is INSIDE
  // the item. Both delimiter types share the one coordinate path.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const text = [
      `3) ${delim}${delim}${delim}audit`,
      "   sample",
      `   ${delim}${delim}${delim}`,
      "",
      "STATUS:CONTINUE implement owner tests",
    ].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(text)),
      { status: "continue", payload: "implement owner tests" },
      `${label}: the item's fence must close and the declaration below is seen`,
    );
    const pi = armed();
    const proposal = await proposes(pi, [assistant(text)]);
    assert.ok(proposal, `${label}: the live declaration must propose a continuation`);
    assert.equal(proposal.continue, true);
    assert.equal(proposal.entries.length, 1);
    assert.match(proposal.entries[0].content, /STATUS:CONTINUE implement owner tests/);
  }

  // DISCRIMINATING COMPANION (negative direction): a declaration GENUINELY
  // INSIDE an open fence must STILL be excluded - the fix must not simply stop
  // tracking fences. A top-level unterminated fence swallows the column-zero
  // declaration for both delimiter types.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const control = [
      `${delim}${delim}${delim}text`,
      "example",
      "",
      "STATUS:CONTINUE must remain fenced",
    ].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(control)),
      "unknown",
      `${label}: a genuinely-fenced declaration is still excluded`,
    );
    const pi = armed();
    assert.ok(!(await proposes(pi, [assistant(control)])), `${label}: no bridge may be proposed for a fenced declaration`);
  }
  // ...and the same control nested on a list-marker line, for both delimiters.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const nested = [
      `- ${delim}${delim}${delim}text`,
      "  STATUS:CONTINUE inside",
      `  ${delim}${delim}${delim}`,
    ].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(nested)),
      "unknown",
      `${label}: a marker inside a list-nested fence is still excluded`,
    );
  }

  // MULTI-DIGIT ORDERED MARKERS: the marker width is 3 for `10)`/`10.` and 2 for
  // `1.`; every width must locate the item's four-/three-column fence correctly.
  for (const [label, marker, indent] of [
    ["10) ordered marker, content column 4", "10)", "    "],
    ["10. ordered marker, content column 4", "10.", "    "],
    ["1. ordered marker, content column 3", "1.", "   "],
  ]) {
    for (const [dlabel, delim] of [
      ["backtick", "`"],
      ["tilde", "~"],
    ]) {
      const text = [
        `${marker} ${delim}${delim}${delim}text`,
        `${indent}example`,
        `${indent}${delim}${delim}${delim}`,
        "",
        "STATUS:CONTINUE add a regression",
      ].join("\n");
      assert.deepEqual(
        mod.readDeclaredMarker(assistant(text)),
        { status: "continue", payload: "add a regression" },
        `${label} (${dlabel})`,
      );
    }
  }

  // 0-3 COLUMN LIST-NESTED FENCES: the list item's content column is 2 (`- `),
  // and the fence DELIMITER may carry 0..3 columns of its own indent relative to
  // that content column; each still opens and closes, and the declaration below
  // is live.
  for (const indent of [0, 1, 2, 3]) {
    const itemPad = `  ${" ".repeat(indent)}`;
    const openerPad = " ".repeat(indent);
    const text = [
      `- ${openerPad}\`\`\`text`,
      `${itemPad}example`,
      `${itemPad}\`\`\``,
      "",
      "STATUS:CONTINUE ok",
    ].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(text)),
      "continue",
      `a list-nested fence indented ${indent} column(s) still closes and the declaration is seen`,
    );
  }

  // CONTINUED INDENTED CODE: an over-wide separator leaves an indented code
  // block INSIDE the item; a continued code line must stay code (never a fence
  // opener) and the declaration below is live.
  const continued = [
    "-     ```text",
    "      more indented code",
    "",
    "STATUS:CONTINUE implement continued code",
  ].join("\n");
  assert.deepEqual(
    mod.readDeclaredMarker(assistant(continued)),
    { status: "continue", payload: "implement continued code" },
    "continued indented code is not a fence opener",
  );
});

test("P13: a declaration that EXITS its container is evaluated AFTER that exit, so it is OUTSIDE the fence it closed (both delimiters)", async () => {
  // DEFECT H2: the scanner recorded the fence's end AT the declaration's index,
  // but `isInsideFence` processed only changes with `cursor < index`, so a line
  // whose OWN transition ends the container (and therefore the fence) was judged
  // INSIDE the fence it simultaneously closed: `unknown` / `ineligible-line`, no
  // bridge - silently losing a GENUINE declaration (the user's complaint #1).
  // A line that ends the enclosing container/fence must be evaluated after that
  // transition, i.e. as OUTSIDE it. This holds for list-container exits AND
  // quote-container exits, and for both delimiter types.
  const cases = [
    [
      "list-container exit",
      (d) => [`- ${d}${d}${d}trace`, "  content", "", "STATUS:CONTINUE implement marker checks"],
    ],
    [
      "quote-container exit",
      (d) => [`> ${d}${d}${d}trace`, "> content", "", "STATUS:CONTINUE implement marker checks"],
    ],
    [
      "list-in-blockquote exit",
      (d) => [`> - ${d}${d}${d}trace`, ">   content", "", "STATUS:CONTINUE implement marker checks"],
    ],
    [
      "blockquote-in-list exit",
      (d) => [`- > ${d}${d}${d}trace`, "  > content", "", "STATUS:CONTINUE implement marker checks"],
    ],
  ];
  for (const [setLabel, build] of cases) {
    for (const [dlabel, delim] of [
      ["backtick", "`"],
      ["tilde", "~"],
    ]) {
      const text = build(delim).join("\n");
      assert.deepEqual(
        mod.readDeclaredMarker(assistant(text)),
        { status: "continue", payload: "implement marker checks" },
        `${setLabel} (${dlabel}): the declaration leaves the container and must be live`,
      );
      const pi = armed();
      const proposal = await proposes(pi, [assistant(text)]);
      assert.ok(proposal, `${setLabel} (${dlabel}): the live declaration must propose a continuation`);
      assert.equal(proposal.continue, true);
      assert.equal(proposal.entries.length, 1);
      assert.match(proposal.entries[0].content, /STATUS:CONTINUE implement marker checks/);
    }
  }

  // DISCRIMINATING COMPANION (negative direction): the container-exit rule must
  // NOT make the scanner permissive. A declaration still INSIDE the container
  // (its fence open, the declaration line still held by the container) stays
  // excluded - here the fence's containers are still open at the marker.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const stillInside = [
      `- ${delim}${delim}${delim}trace`,
      "  content",
      "  more content",
      "  STATUS:CONTINUE inside",
      `  ${delim}${delim}${delim}`,
    ].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(stillInside)),
      "unknown",
      `${label}: a marker held inside the container's fence is still excluded`,
    );
  }
});

test("P14: a declaration NO LONGER beneath a blank line is still live when its OWN line EXITS the container that held the fence (both delimiters)", async () => {
  // DEFECT J (CORR28): the eligibility rule required a BLANK line before the
  // declaration (`isPrecededByBlank`). That is exact whenever a blank is
  // present, but it is WRONG for the one remaining shape: a declaration whose
  // OWN line EXITS the container that held the fence, with NO blank between the
  // fence content and the declaration. The container's leaf was FENCED CODE,
  // which CommonMark never continues lazily, so the unmarked line ENDS the
  // container and is ordinary TOP-LEVEL text - and a genuine declaration there
  // was silently lost (`unknown` / `ineligible-line`, no bridge), the user's
  // "CONTINUE ... but stop" failure. Verified against the reference CommonMark
  // parser (commonmark@0.31.2), which parses each input below with the trailing
  // STATUS line a TOP-LEVEL PARAGRAPH.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    // QUOTE container exit: the declaration line drops the `>`. The fence closed
    // on the quoted closer line immediately above, with NO blank after it.
    const quoteExit = [
      `> ${delim}${delim}${delim}trace`,
      "> fenced content",
      `> ${delim}${delim}${delim}`,
      "STATUS:CONTINUE implement marker checks",
    ].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(quoteExit)),
      { status: "continue", payload: "implement marker checks" },
      `${label}: a declaration on the quote-exit line must be live`,
    );
    const piQuote = armed();
    const quoteProposal = await proposes(piQuote, [assistant(quoteExit)]);
    assert.ok(quoteProposal, `${label}: the quote-exit declaration must propose`);
    assert.equal(quoteProposal.continue, true);
    assert.equal(quoteProposal.entries.length, 1);

    // LIST container exit: the declaration line dedents below the item content.
    const listExit = [
      `- ${delim}${delim}${delim}trace`,
      "  fenced",
      `  ${delim}${delim}${delim}`,
      "STATUS:CONTINUE implement marker checks",
    ].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(listExit)),
      { status: "continue", payload: "implement marker checks" },
      `${label}: a declaration on the list-exit line must be live`,
    );
    const piList = armed();
    const listProposal = await proposes(piList, [assistant(listExit)]);
    assert.ok(listProposal, `${label}: the list-exit declaration must propose`);
    assert.equal(listProposal.continue, true);
    assert.equal(listProposal.entries.length, 1);
  }
});

test("P15: a declaration on a NESTED-container exit line is live (quote-in-list and list-in-quote, both delimiters)", async () => {
  // DEFECT J across NESTING: the same container-exit declaration may leave TWO
  // containers at once (a quote inside a list item, or a list item inside a
  // quote). The leaf is fenced code in every case, so the unmarked declaration
  // line ends BOTH containers and is top level.
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const quoteInList = [
      `- > ${delim}${delim}${delim}trace`,
      "  > fenced",
      "  > content",
      "STATUS:CONTINUE nested quote-in-list exit",
    ].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(quoteInList)),
      { status: "continue", payload: "nested quote-in-list exit" },
      `${label}: a quote-in-list exit declaration must be live`,
    );
    const piQ = armed();
    const qProposal = await proposes(piQ, [assistant(quoteInList)]);
    assert.ok(qProposal, `${label}: the nested quote-in-list declaration must propose`);
    assert.equal(qProposal.continue, true);
    assert.equal(qProposal.entries.length, 1);

    const listInQuote = [
      `> - ${delim}${delim}${delim}trace`,
      ">   fenced",
      ">   content",
      "STATUS:CONTINUE nested list-in-quote exit",
    ].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(listInQuote)),
      { status: "continue", payload: "nested list-in-quote exit" },
      `${label}: a list-in-quote exit declaration must be live`,
    );
    const piL = armed();
    const lProposal = await proposes(piL, [assistant(listInQuote)]);
    assert.ok(lProposal, `${label}: the nested list-in-quote declaration must propose`);
    assert.equal(lProposal.continue, true);
    assert.equal(lProposal.entries.length, 1);
  }
});

test("P16: a same-line container EXIT that does NOT declare stays excluded, and prose beneath prose stays excluded (negative direction)", async () => {
  // DISCRIMINATING COMPANION for the P14/P15 fix: the container-exit rule must
  // NOT make the scanner permissive. A same-line container exit carrying only
  // FENCE syntax (a bare closer/reopener) leaves the declaration INSIDE the new
  // fence and stays excluded; and a status line directly beneath ordinary PROSE
  // still does not declare (a paragraph is never ended by an unmarked line).
  for (const [label, delim] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    // Container exits on a line that is a FRESH top-level fence OPENER, so the
    // declaration below is inside the NEW fence.
    const reopen = [
      `> ${delim}${delim}${delim}text`,
      "> example",
      `> ${delim}${delim}${delim}`,
      `${delim}${delim}${delim}`,
      "STATUS:CONTINUE must remain fenced",
    ].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(reopen)),
      "unknown",
      `${label}: a bare re-opener on the exit line must swallow the declaration`,
    );
    const piReopen = armed();
    assert.ok(!(await proposes(piReopen, [assistant(reopen)])), `${label}: no bridge may be proposed`);
  }
  // Prose beneath prose: a paragraph is NEVER ended by an unmarked line, so the
  // container-exit exception must not leak into the ordinary paragraph case.
  assert.equal(mod.declaredStatusOf(assistant("Work remains.\nSTATUS:CONTINUE x")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("> Example:\nSTATUS:CONTINUE x")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("> foo\nbar\nSTATUS:CONTINUE x")), "unknown");
});

test("CORR29/F1: consecutive list items each hold their own fence, so the list-exit declaration is LIVE (both delimiters)", async () => {
  // The stacked-fence-state defect: a fence opened in item1 was wrongly held
  // open when item2's identical opener was scanned, so the list-exit
  // declaration below was read `unknown`. CommonMark parses TWO sibling
  // `code_block`s then a top-level paragraph (commonmark@0.31.2), so the
  // declaration is live. BOTH forms - item1 closed and item1 unclosed - are
  // covered, for both delimiter types.
  for (const [dl, d] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    for (const [formLabel, text] of [
      [
        "item1 closed",
        [
          `1. ${d}${d}${d}text`,
          "   fenced content",
          `   ${d}${d}${d}`,
          `2. ${d}${d}${d}text`,
          "   more content",
          `   ${d}${d}${d}`,
          "STATUS:CONTINUE implement owner tests",
        ].join("\n"),
      ],
      [
        "item1 unclosed",
        [
          `1. ${d}${d}${d}text`,
          "   fenced content",
          `2. ${d}${d}${d}text`,
          "   item2 content",
          "STATUS:CONTINUE implement owner tests",
        ].join("\n"),
      ],
    ]) {
      assert.deepEqual(
        mod.readDeclaredMarker(assistant(text)),
        { status: "continue", payload: "implement owner tests" },
        `${dl} ${formLabel}: the list-exit declaration must be live`,
      );
      const pi = armed();
      const proposal = await proposes(pi, [assistant(text)]);
      assert.ok(proposal, `${dl} ${formLabel}: must propose a continuation`);
      assert.equal(proposal.continue, true);
      assert.equal(proposal.entries.length, 1);
      assert.match(proposal.entries[0].content, /STATUS:CONTINUE implement owner tests/);
    }
  }
});

test("CORR29/F2 (DEFECT K): list content column >= 4 still continues the item, so a four-column closer closes and the declaration is LIVE (both delimiters)", async () => {
  // Continuation stripped at most THREE leading columns, so a fourteen-space
  // `10. ` item's four-column closer was falsely read as leaving the item; the
  // 4-space closer was then unrecognised and the declaration below was lost.
  // CommonMark's continuation indent is the item's CONTENT COLUMN (marker +
  // separator), which is 4 for `10. ` and for `-   `.
  for (const [dl, d] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    for (const [formLabel, lines] of [
      ["10. ordered (content column 4)", [`10. ${d}${d}${d}text`, "    fenced content", `    ${d}${d}${d}`, "STATUS:CONTINUE p"]],
      ["-   bullet (content column 4)", [`-   ${d}${d}${d}text`, "    fenced content", `    ${d}${d}${d}`, "STATUS:CONTINUE p"]],
    ]) {
      const text = lines.join("\n");
      assert.deepEqual(
        mod.readDeclaredMarker(assistant(text)),
        { status: "continue", payload: "p" },
        `${dl} ${formLabel}: the four-column closer must close and the declaration must be live`,
      );
      const pi = armed();
      const proposal = await proposes(pi, [assistant(text)]);
      assert.ok(proposal, `${dl} ${formLabel}: must propose a continuation`);
      assert.equal(proposal.continue, true);
      assert.equal(proposal.entries.length, 1);
    }
  }
});

test("CORR29/F3: a USER_QUESTION after a container-fence exit is recovered (both delimiters)", async () => {
  // The question line's nearest non-blank predecessor was a container-fence
  // CLOSER (`> ``` `), whose CONTAINER had ENDED there. Reading it as a
  // still-open container made the question a lazy continuation, so it was
  // dropped. The recovered question is the surface `verifyUserEscalation`
  // reads when it matches the Oracle assessment.
  for (const [dl, d] of [
    ["backtick", "```"],
    ["tilde", "~~~"],
  ]) {
    const text = [`> ${d}text`, "> fenced content", `> ${d}`, "USER_QUESTION: q"].join("\n");
    assert.deepEqual(mod.userQuestionLines(text), ["q"], `${dl}: the question after the container-fence exit must be recovered`);
    // DISCRIMINATING COMPANION: a question that GENUINELY sits inside a lazily
    // continued quoted paragraph is still owned by the example, so the fix did
    // not simply stop classifying lazy continuations.
    const lazy = ["> Example:", "explanatory continuation", "USER_QUESTION: Pick one."].join("\n");
    assert.deepEqual(mod.userQuestionLines(lazy), [], `${dl}: a lazy quoted continuation still owns its question`);
    const lazyList = ["- Example:", "explanatory continuation", "USER_QUESTION: Pick one."].join("\n");
    assert.deepEqual(mod.userQuestionLines(lazyList), [], `${dl}: a lazy list continuation still owns its question`);
  }
});

test("CORR29/F4: NESTED-container exits are visible to the declaration gate (both delimiters)", async () => {
  // A declaration leaving TWO containers at once (a quote inside a list item, or
  // a list item inside a quote) was lost because only single-level sites were
  // handled. The leaf is fenced code, so the unmarked declaration ends both
  // containers and is top level.
  for (const [dl, d] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    for (const [formLabel, text] of [
      [
        "quote-in-list",
        [`- > ${d}${d}${d}text`, "  > fenced content", `  > ${d}${d}${d}`, "STATUS:CONTINUE implement owner tests"].join("\n"),
      ],
      [
        "list-in-quote",
        [`> - ${d}${d}${d}text`, ">   fenced content", `>   ${d}${d}${d}`, "STATUS:CONTINUE implement owner tests"].join("\n"),
      ],
    ]) {
      assert.deepEqual(
        mod.readDeclaredMarker(assistant(text)),
        { status: "continue", payload: "implement owner tests" },
        `${dl} ${formLabel}: the nested-exit declaration must be live`,
      );
      const pi = armed();
      const proposal = await proposes(pi, [assistant(text)]);
      assert.ok(proposal, `${dl} ${formLabel}: must propose a continuation`);
      assert.equal(proposal.continue, true);
      assert.equal(proposal.entries.length, 1);
      assert.match(proposal.entries[0].content, /STATUS:CONTINUE implement owner tests/);
    }
  }
});

test("CORR29/F5: an empty list item closes the fence exactly where the item ends, so the declaration is LIVE (both delimiters)", async () => {
  // The fence was closed one item early: the empty `- ` item that ENDS the list
  // was not recognised as ending the block, so the following declaration was
  // read `unknown`.
  for (const [dl, d] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const text = [`- ${d}${d}${d}text`, "  fenced", `  ${d}${d}${d}`, "- ", "STATUS:CONTINUE p"].join("\n");
    assert.deepEqual(
      mod.readDeclaredMarker(assistant(text)),
      { status: "continue", payload: "p" },
      `${dl}: the declaration after the empty item must be live`,
    );
    const pi = armed();
    const proposal = await proposes(pi, [assistant(text)]);
    assert.ok(proposal, `${dl}: must propose a continuation`);
    assert.equal(proposal.continue, true);
    assert.equal(proposal.entries.length, 1);
  }
});

test("CORR29/F6: a marker that cannot interrupt a paragraph opens NO phantom fence, so the declaration stays EXCLUDED (both delimiters)", async () => {
  // FALSE POSITIVE (mirror of the user's bug): `2.` may not interrupt a
  // paragraph (ordered lists interrupt only when starting at 1), so
  // `> quoted paragraph` then `> 2. ```text` is ONE quoted paragraph and the
  // declaration below stays inside it. A phantom fence opened there accepted a
  // genuinely fenced declaration.
  for (const [dl, d] of [
    ["backtick", "`"],
    ["tilde", "~"],
  ]) {
    const text = ["> quoted paragraph", `> 2. ${d}${d}${d}text`, "STATUS:CONTINUE p", ""].join("\n");
    assert.equal(
      mod.declaredStatusOf(assistant(text)),
      "unknown",
      `${dl}: a non-interrupting ordered marker must not open a phantom fence`,
    );
    const pi = armed();
    assert.ok(!(await proposes(pi, [assistant(text)])), `${dl}: no bridge may be proposed`);
  }
  // DISCRIMINATING COMPANION: a marker that CAN interrupt (`1.`) opens a fresh
  // block, so a real top-level declaration following an exited fence stays live
  // (the gate did not simply stop opening fences after paragraphs).
  const interrupting = ["> quoted paragraph", "", "1. ```text", "   fenced", "   ```", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(interrupting)), "continue", "a start-at-1 ordered marker interrupts and the declaration is live");
});

test("status words are case-insensitive and payloads are trimmed", () => {
  assert.deepEqual(mod.readDeclaredMarker(assistant("status:continue   spaced step  ")), {
    status: "continue",
    payload: "spaced step",
  });
  assert.deepEqual(mod.readDeclaredMarker(assistant("Status:Done")), {
    status: "done",
    payload: "",
  });
});

test("CONTINUE without a nonempty payload is unknown, not a continuation", () => {
  for (const text of ["STATUS:CONTINUE", "STATUS:CONTINUE   ", "STATUS:WAIT"]) {
    const result = mod.readDeclaredMarker(assistant(text));
    assert.equal(result.status, "unknown", text);
    assert.equal(result.problem, "empty-payload");
  }
});

test("a payload after DONE is a malformed line and therefore unknown", () => {
  const result = mod.readDeclaredMarker(assistant("STATUS:DONE now"));
  assert.equal(result.status, "unknown");
  assert.equal(result.problem, "unexpected-payload");
});

test("an unrecognized status word is unknown", () => {
  const result = mod.readDeclaredMarker(assistant("STATUS:TERMINATED"));
  assert.equal(result.status, "unknown");
  assert.equal(result.problem, "unknown-status");
});

test("only the FINAL non-blank line is a declaration", () => {
  // Two competing declarations are ambiguous, not a decision.
  assert.equal(mod.declaredStatusOf(assistant("STATUS:CONTINUE x\n\nSTATUS:DONE")), "unknown");
  // Trailing blank lines do not displace the final line.
  assert.equal(mod.declaredStatusOf(assistant("Deploy verified.\n\nSTATUS:DONE\n\n")), "done");
  // An earlier non-protocol line does not compete.
  assert.equal(
    mod.declaredStatusOf(assistant("I ran the tests.\n\nSTATUS:CONTINUE fix the failure")),
    "continue",
  );
});

test("a marker inside a code fence is not recognized", () => {
  assert.equal(mod.declaredStatusOf(assistant("```\nSTATUS:DONE\n```")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("~~~\nSTATUS:DONE\n~~~")), "unknown");
  // A tagged fence opens too, and an unterminated fence never closes.
  assert.equal(mod.declaredStatusOf(assistant("```text\nSTATUS:DONE\n```")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("~~~\nSTATUS:DONE")), "unknown");
  // A fence that closed before the marker leaves it eligible.
  assert.equal(mod.declaredStatusOf(assistant("```\nx\n```\n\nSTATUS:DONE")), "done");
});

test("a fence closes only on a delimiter of the same character and length", () => {
  assert.equal(mod.declaredStatusOf(assistant("````\nSTATUS:DONE\n```")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("````\nx\n````\n\nSTATUS:DONE")), "done");
  assert.equal(mod.declaredStatusOf(assistant("~~~\nSTATUS:DONE\n~~~\n\nSTATUS:WAIT x")), "wait");
});

test("an indented line is not recognized", () => {
  assert.equal(mod.declaredStatusOf(assistant("    STATUS:DONE")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("\tSTATUS:DONE")), "unknown");
});

test("two conflicting protocol lines make the message ambiguous", () => {
  // Two DIFFERENT declared statuses: the model said two things, so the
  // supervisor must not pick one. A blank line separates them so that BOTH are
  // eligible declarations and the conflict is what makes it ambiguous.
  const conflicting = mod.readDeclaredMarker(assistant("STATUS:DONE\n\nSTATUS:CONTINUE x"));
  assert.equal(conflicting.status, "unknown");
  assert.equal(conflicting.problem, "ambiguous");
  // Two lines declaring the SAME status agree, so the normal contract applies.
  assert.equal(mod.declaredStatusOf(assistant("STATUS:CONTINUE a\n\nSTATUS:CONTINUE b")), "continue");
  // Without a blank line the second line is not a declaration at all, so the
  // final line is ineligible rather than the message being ambiguous. It still
  // reads `unknown`, which notifies - the same safe outcome by another route.
  const stacked = mod.readDeclaredMarker(assistant("STATUS:DONE\nSTATUS:CONTINUE x"));
  assert.equal(stacked.status, "unknown");
});

test("a payload-free menu of protocol names is documentation, not ambiguity", () => {
  // Two bare words joined by a separator document the protocol; they do not
  // compete as declarations. EVERY separator style must behave the same way, in
  // ANY spacing: an earlier revision tokenized on whitespace alone, so a comma
  // stayed glued to its word and that one form became a competing declaration.
  const separators = ["or", "and", "vs.", ",", "/", "|"];
  for (const separator of separators) {
    assert.equal(
      mod.declaredStatusOf(
        assistant(`The protocol is STATUS:DONE ${separator} STATUS:CONTINUE.\n\nSTATUS:WAIT x`),
      ),
      "wait",
      `the ${separator} separator is a menu`,
    );
  }
  // Punctuation separators are token boundaries even when glued to both words;
  // a prose joiner needs space, because it is a word.
  for (const separator of [",", "/", "|", ";"]) {
    assert.equal(
      mod.declaredStatusOf(assistant(`STATUS:DONE${separator}STATUS:CONTINUE\n\nSTATUS:CONTINUE x`)),
      "continue",
      `an unspaced ${separator} separator is still a token boundary`,
    );
  }
  // A separator may also be SPACED on both sides, which is how a semicolon or
  // colon-joined menu is usually written.
  for (const separator of [";", "then"]) {
    assert.equal(
      mod.declaredStatusOf(
        assistant(`The protocol is STATUS:DONE ${separator} STATUS:WAIT.\n\nSTATUS:CONTINUE x`),
      ),
      "continue",
      `a spaced ${separator} separator is a menu`,
    );
  }
  // A payload may itself contain separator punctuation or a colon.
  assert.equal(mod.declaredStatusOf(assistant("STATUS:CONTINUE run tests; then deploy")), "continue");
  assert.equal(mod.declaredStatusOf(assistant("STATUS:BLOCKED waiting: need creds")), "blocked");
  // A menu alone is documentation, so it declares nothing rather than picking a
  // word out of the list.
  assert.equal(mod.declaredStatusOf(assistant("STATUS:DONE or STATUS:CONTINUE")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("STATUS:DONE, STATUS:CONTINUE")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("STATUS:DONE/STATUS:CONTINUE")), "unknown");
});

test("a quoted example declares nothing even when it names a payload", () => {
  // The quoted form is documentation in every position: the payload belongs to
  // the EXAMPLE, not to a decision. A quoted mention must not compete with the
  // real declaration that follows it.
  const quoted = [
    "`STATUS:WAIT child`",
    '"STATUS:WAIT child"',
    "`STATUS:DONE`",
    "`STATUS:CONTINUE x`",
    // The opener may follow a letter directly: "or`STATUS:WAIT child`".
    "or`STATUS:WAIT child`",
    // A quoted payload may itself contain the other delimiter.
    '"STATUS:WAIT `child`"',
  ];
  for (const example of quoted) {
    assert.equal(
      mod.declaredStatusOf(
        assistant(`The protocol is STATUS:CONTINUE or ${example}\n\nSTATUS:CONTINUE run tests`),
      ),
      "continue",
      `${example} must not compete with the real declaration`,
    );
    // A quoted example by itself declares nothing, so the plugin notifies.
    assert.equal(mod.declaredStatusOf(assistant(example)), "unknown", `${example} alone`);
  }
});

test("a backticked marker is documentation in every position", () => {
  // A mention INSIDE prose is documentation, so the real declaration wins.
  assert.equal(
    mod.declaredStatusOf(assistant('The protocol says `STATUS:DONE` is final.\n\nSTATUS:CONTINUE x')),
    "continue",
  );
  // A line wrapped in backticks QUOTES the protocol, so it declares nothing.
  // Reporting `unknown` (rather than nothing at all) makes the plugin notify,
  // which is the safe direction: an example must never drive a continuation.
  assert.equal(mod.declaredStatusOf(assistant("`STATUS:DONE`")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("`STATUS:WAIT`")), "unknown");
  assert.equal(mod.declaredStatusOf(assistant("`STATUS:CONTINUE x`")), "unknown");
  // The plain forms are unaffected.
  assert.equal(mod.declaredStatusOf(assistant("STATUS:DONE")), "done");
  assert.equal(mod.declaredStatusOf(assistant("STATUS:CONTINUE x")), "continue");
  // A backticked documentation line must not COMPETE with a real declaration.
  assert.equal(
    mod.declaredStatusOf(assistant("`STATUS:DONE`\n\nSTATUS:CONTINUE run tests")),
    "continue",
  );
});

test("a marker in a tool result or a non-final message is not recognized", () => {
  assert.equal(mod.declaredStatusOf({ role: "toolResult", content: [{ type: "text", text: "STATUS:DONE" }] }), "unknown");
  assert.equal(mod.declaredStatusOf(user("STATUS:DONE")), "unknown");
});

test("an assistant message with thinking only, no text, does not declare", () => {
  assert.equal(mod.declaredStatusOf(thinking("about STATUS:DONE")), "unknown");
  assert.equal(mod.declaredStatusOf(assistantWithParts([])), "unknown");
});

test("an assistant message that also made a tool call declares nothing", () => {
  // A mid-run text block that happens to end with a marker is metadata: the
  // turn is not over, so the marker is not a settle-time declaration.
  assert.equal(mod.declaredStatusOf(toolCall("Running the tests.\n\nSTATUS:DONE")), "unknown");
});

// CORR14 / C1-C2: the canonical Pi 1.1.0 shape is `toolCall`, NOT `tool_call`.
// A native assistant message carrying BOTH text and a tool call must not be
// read as a status declaration in EITHER spelling, or a text ending in
// `STATUS:CONTINUE next` would wrongly declare a continuation.
test("CORR14: isToolCallPart recognizes both the canonical and alias tool-call spellings", () => {
  assert.equal(typeof mod.isToolCallPart, "function", "isToolCallPart must be exported");
  assert.equal(mod.isToolCallPart({ type: "toolCall", id: "c", name: "bash", arguments: "{}" }), true);
  assert.equal(mod.isToolCallPart({ type: "tool_call", name: "bash", arguments: "{}" }), true);
  assert.equal(mod.isToolCallPart({ type: "text", text: "hi" }), false);
  assert.equal(mod.isToolCallPart(null), false);
  assert.equal(mod.isToolCallPart("toolCall"), false);
});

for (const spelling of ["toolCall", "tool_call"]) {
  test(`CORR14: a text+tool-call message declares nothing at the native spelling "${spelling}"`, () => {
    // The real defect: text ending in STATUS:CONTINUE with a tool-call part.
    // Pre-fix this returned a continuation-declaring marker for "toolCall".
    const message = toolCallWithSpelling("Done for now.\n\nSTATUS:CONTINUE next", spelling);
    assert.equal(
      mod.readDeclaredMarker(message),
      null,
      `readDeclaredMarker must return null for a ${spelling} tool-call part`,
    );
    assert.equal(mod.declaredStatusOf(message), "unknown");
    // And with a WAIT payload, to guard the other continuation-direction marker.
    assert.equal(
      mod.readDeclaredMarker(toolCallWithSpelling("Pausing.\n\nSTATUS:WAIT subagent x complete", spelling)),
      null,
    );
  });

  test(`CORR14: the CANONICAL spelling "${spelling}" is exercised by the fixture helper too`, () => {
    // Belt-and-braces: the shared `toolCall` builder must use the canonical
    // shape so its existing test cannot silently mask the defect again.
    const parts = toolCall("x").content;
    assert.equal(parts.some((p) => p.type === "toolCall"), true);
  });
}

// ---------------------------------------------------------------------------
// The decision table
// ---------------------------------------------------------------------------

/** Complete the genuine-request handshake so the ledger grants a budget. */
function handshake(
  pi,
  { text = "request", source = "interactive", steering = false, ctx = { ...UI, isIdle: () => true } } = {},
) {
  pi.emit(
    "input",
    { type: "input", text, source, streamingBehavior: steering ? "steer" : undefined },
    ctx,
  );
  pi.emit("before_agent_start", { type: "before_agent_start", prompt: text }, ctx);
  pi.emit("message_start", { type: "message_start", message: { role: "user", content: text } }, ctx);
}

/** A registered pi whose budget was earned by a delivered genuine request. */
function armed(modOverride = mod, env = {}) {
  const pi = makePi();
  modOverride.registerSessionSupervisor(pi, env);
  handshake(pi);
  return pi;
}

/**
 * An armed pi whose registration exposes an owner event bus.
 *
 * The bus is attached to the same `pi` object the factory closed over, which is
 * how a real host injects `api.events` before registration.
 */
function armedWithBus(reply, rpc) {
  const bus = makeBus(reply, rpc);
  const pi = makePi();
  pi.events = bus;
  // A SYNCHRONOUS scheduler: the deferred notice runs inside the settle call, so
  // these tests never race node:test's shared stdout capture. Timers are bucketed
  // by delay so a test can flush ONLY the short verification window without also
  // firing the long idle recheck (and vice versa).
  const pending = [];
  const timers = [];
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      timers.push(handle);
      pending.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = pending.indexOf(handle);
      if (index >= 0) pending.splice(index, 1);
    },
  });
  handshake(pi);
  return {
    pi,
    bus,
    timers,
    // Run every deferred callback (verification window AND recheck).
    flush: () => pending.splice(0).forEach((handle) => handle.run()),
    // Run only callbacks scheduled at `ms`, leaving longer timers pending.
    flushMs: (ms) => {
      const due = pending.filter((handle) => handle.ms === ms);
      for (const handle of due) {
        const index = pending.indexOf(handle);
        if (index >= 0) pending.splice(index, 1);
        handle.run();
      }
    },
  };
}

/** Arm with an explicit PI_MAX_CONTINUATIONS value. */
function armedWithBudget(budget) {
  return armed(mod, { PI_MAX_CONTINUATIONS: String(budget) });
}

// --- WAIT verification harness --------------------------------------------

const OSC_UNVERIFIED_WAIT =
  "\x1b]777;notify;Pi;Unverified WAIT - no confirmed automatic wake path\x07";

/** The session identity wake proof must be bound to. */
const SESSION_FILE = "/sessions/current.jsonl";

/** A context that reports the agent idle, as a fresh genuine request requires. */
const IDLE_UI = { ...UI, isIdle: () => true };

/**
 * A fake owner event bus.
 *
 * `reply(topic, request)` answers a PROVIDER owner's synchronous `request` pair;
 * returning `undefined` models a provider that never answers.
 *
 * `rpc(request)` answers a pi-subagents RPC request: it receives the emitted
 * request envelope and returns the `data` payload for a SUCCESSFUL correlated
 * reply (or `null` to model an owner that never answers). The bus wraps it in
 * the plugin's real reply envelope on `subagents:rpc:v1:reply:<requestId>`, so
 * tests exercise the exact transport the extension now depends on.
 *
 * `on` records topic subscriptions, so a test can drive the observed-run ledger
 * exactly as a host would (emit `subagent:async-started` /
 * `subagent.child-status`) AND let the extension await an RPC reply. Emits are
 * delivered synchronously, so a settle's RPC round-trip completes inside the
 * test without real timers.
 */
function makeBus(reply, rpc = () => null) {
  const requests = [];
  const rpcRequests = [];
  const listeners = new Map();
  const subscriptions = [];
  const bus = {
    requests,
    rpcRequests,
    listeners,
    subscriptions,
    request(topic, payload) {
      requests.push({ topic, ...payload });
      return reply ? reply(topic, payload) : undefined;
    },
    on(topic, listener) {
      subscriptions.push(topic);
      const list = listeners.get(topic) ?? [];
      list.push(listener);
      listeners.set(topic, list);
      // The REAL bus (`createEventBus`) RETURNS A DISPOSER FUNCTION and exposes
      // neither `off` nor `removeListener`. Returning it here is what makes a
      // listener-leak assertion exercise the real disposal path instead of the
      // compatibility fallback that would mask a leak.
      return () => {
        const current = listeners.get(topic) ?? [];
        const index = current.indexOf(listener);
        if (index >= 0) current.splice(index, 1);
      };
    },
    off(topic, listener) {
      const list = listeners.get(topic) ?? [];
      const index = list.indexOf(listener);
      if (index >= 0) list.splice(index, 1);
    },
    /** Emit an event to every subscriber of `topic`, synchronously. */
    emit(topic, event) {
      // The extension uses `emit` for its RPC REQUEST; answer on the correlated
      // reply topic exactly as the real plugin bridge does.
      if (topic === mod.SUBAGENT_RPC_REQUEST_TOPIC) {
        rpcRequests.push(event);
        const data = rpc(event);
        if (data !== null && data !== undefined) {
          const replyEvent = `${mod.SUBAGENT_RPC_REPLY_PREFIX}${event.requestId}`;
          for (const listener of listeners.get(replyEvent) ?? []) {
            listener({
              version: mod.SUBAGENT_RPC_VERSION,
              requestId: event.requestId,
              method: event.method,
              success: true,
              data,
            });
          }
        }
        return;
      }
      for (const listener of listeners.get(topic) ?? []) listener(event);
    },
  };
  return bus;
}

/**
 * An async-status snapshot payload naming one run, for an RPC reply.
 *
 * This mirrors the projection the real bridge returns: run nodes carry the
 * exact async run id in `id` and a normalized `state`.
 *
 * PG3: the projected snapshot ALONE is NOT a faithful TARGETED reply. The real
 * targeted request (`{runId}`) always goes through `dataFromToolResult`
 * (`rpc.js:240-250`), so its `data` always carries the human-readable `text`
 * transcript with `Run:`/`State:` (`run-status.js:80-86`) IN ADDITION to
 * `asyncSnapshot`. A reply carrying only a snapshot is a shape the targeted path
 * never produces, and trusting it is exactly the bypass PG3 closed: a finalized
 * run keeps earning silence from a lagging display cache. Use
 * `rpcTargetedStatus` for targeted replies; this helper remains for the few
 * cases that deliberately model a snapshot-only body.
 */
function rpcSnapshot(runId, state) {
  return {
    asyncSnapshot: {
      kind: "pi-subagents.async-status-snapshot",
      version: 1,
      runs: [{ id: runId, kind: "subagent", label: "child", state }],
    },
  };
}

/**
 * The REAL-SHAPED TARGETED status body: `text` + `details` (+ optional snapshot).
 *
 * PG3 made this the default reply for the targeted RPC path, because the real
 * runtime always includes the `Run:`/`State:` transcript for a targeted request.
 * A body that omits `text` is not an authoritative inspection and no longer
 * proves ownership on its own.
 */
function rpcTargetedReply(runId, state) {
  return {
    text: `Run: ${runId}\nState: ${state}`,
    details: { mode: "single", results: [] },
    ...rpcSnapshot(runId, state),
  };
}

/**
 * The REAL-SHAPED targeted status body, as installed pi-subagents builds it.
 *
 * `dataFromToolResult` (`rpc.js:240-250`) produces `{ text, details? }` and the
 * single-run `details` is `{ mode: "single", results: [] }` - there is NO
 * machine-readable `state`. The authoritative state is the `State:` line of the
 * human-readable transcript (`run-status.js:80-86`). Modelling this shape is
 * what lets a test prove the terminal-text-vs-lagging-snapshot precedence;
 * `rpcSnapshot` alone cannot, because it omits `text` entirely.
 *
 * `details` carries `lifecycleStatus.processTerminal` when the runtime has
 * process-exit evidence, so tests can also exercise that surface.
 */
function rpcTargetedStatus(runId, state, { snapshotState = undefined, processTerminal = undefined } = {}) {
  return {
    text: `Run: ${runId}\nState: ${state}`,
    details: {
      mode: "single",
      results: [],
      ...(processTerminal !== undefined ? { lifecycleStatus: { processTerminal } } : {}),
    },
    ...(snapshotState !== undefined
      ? { asyncSnapshot: { kind: "pi-subagents.async-status-snapshot", version: 1, runs: [{ id: runId, kind: "subagent", label: "child", state: snapshotState }] } }
      : {}),
  };
}

/** A context carrying the session identity wake proof binds to. */
const sessionCtx = (messages) => ({
  ...UI,
  sessionFile: SESSION_FILE,
  sessionManager: sessionView(messages),
});

/**
 * Armed pi whose WAIT proof comes from the REAL pi-subagents RPC transport.
 *
 * The extension now accepts a subagent WAIT only on CURRENT-OWNER evidence: the
 * run must carry PROVENANCE bound to this session (an observed START under the
 * current epoch) AND the correlated RPC reply must report the exact run active.
 * This harness supplies both, so a test varies only the variable under test:
 *
 *   runId/state  - the exact run the WAIT names and the state the bridge returns.
 *   rpc          - override the reply payload (or return null to model no reply).
 *   observe=false - skip the START event, modelling a run this session never saw.
 *
 * A run START is fed through the SAME subscription a host uses, so provenance is
 * built exactly as in production rather than poked into place.
 */
function armedRpcWait({ runId = "3c1", state = "running", rpc, observe = true } = {}) {
  // Provenance and the WAIT context must agree on the session identity, so both
  // use SESSION_FILE (which `sessionCtx` also uses).
  const sessionFile = SESSION_FILE;
  const responder = rpc ?? (() => rpcTargetedReply(runId, state));
  const bus = makeBus(undefined, responder);
  const pi = makePi();
  pi.events = bus;
  const pending = [];
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      pending.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = pending.indexOf(handle);
      if (index >= 0) pending.splice(index, 1);
    },
  });
  const ctx = { ...UI, isIdle: () => true, sessionFile, sessionId: sessionFile };
  pi.emit("input", { type: "input", text: "go", source: "interactive" }, ctx);
  pi.emit("before_agent_start", { type: "before_agent_start", prompt: "go" }, ctx);
  pi.emit("message_start", { type: "message_start", message: { role: "user", content: "go" } }, ctx);
  if (observe) {
    bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
      type: "subagent:async-started",
      version: 1,
      runId,
      id: runId,
      agent: "oracle",
      sessionFile,
      sessionId: sessionFile,
    });
  }
  return {
    pi,
    bus,
    ctx: { ...ctx, sessionManager: sessionView([assistant(WAIT)]) },
    flush: () => pending.splice(0).forEach((handle) => handle.run()),
    flushMs: (ms) => {
      const due = pending.filter((handle) => handle.ms === ms);
      for (const handle of due) {
        const index = pending.indexOf(handle);
        if (index >= 0) pending.splice(index, 1);
        handle.run();
      }
    },
  };
}

test("CONTINUE with budget proposes a bridge continuation and does NOT notify", async () => {
  const pi = armed();
  const capture = captureStdout();
  try {
    const result = await proposes(pi, [assistant(CONTINUE)]);
    assert.equal(result.continue, true);
    assert.deepEqual(capture.chunks, [], "an accepted continuation must not notify");
    const bridge = result.entries[result.entries.length - 1];
    assert.equal(bridge.type, "custom_message");
    assert.equal(bridge.customType, mod.BRIDGE_CUSTOM_TYPE);
    assert.equal(bridge.display, false);
    assert.ok(bridge.content.includes("STATUS:CONTINUE add the missing tests"), "restates the step");
    assert.ok(/NO new authorization/.test(bridge.content), "grants no new authorization");
  } finally {
    capture.restore();
  }
});

test("CONTINUE preserves entries another handler already drafted", async () => {
  const pi = armed();
  const prior = { type: "custom_message", customType: "other:handler", content: "keep me", display: true };
  const result = await proposes(pi, [assistant(CONTINUE)], { entries: [prior] });
  assert.equal(result.continue, true);
  assert.deepEqual(result.entries[0], prior, "must not drop another handler's entry");
  assert.equal(result.entries.length, 2);
});

test("a prior continue request from another handler is supplied a runnable bridge", async () => {
  // S1 contract change: another handler's bare `continue: true` sets Pi's flag
  // but carries NO runnable message, and Pi computes `canContinue` from the
  // COMMITTED context. This extension must therefore still append its bridge -
  // otherwise the continuation Pi was asked for is refused as invalid. The old
  // expectation (return `undefined`) encoded the withdrawn allowance rule.
  const pi = armed();
  const result = await proposes(pi, [assistant(CONTINUE)], { continue: true });
  assert.equal(result?.continue, true, "the flag is set alongside the bridge");
  assert.equal(
    result.entries.at(-1).customType,
    mod.BRIDGE_CUSTOM_TYPE,
    "a runnable bridge is appended even though another handler already asked to continue",
  );
});

test("another handler's owned continuation is still given a runnable bridge", async () => {
  // Regression preserved conceptually: ownership elsewhere must NOT be
  // misreported as a resource-limited stop. Under S1 there is no allowance at
  // all, so the outcome is simply that this extension supplies the bridge that
  // makes the other handler's continuation runnable, and emits no notice.
  const pi = armed();
  const capture = captureStdout();
  try {
    const result = await proposes(pi, [assistant(CONTINUE)], { continue: true });
    assert.equal(result?.continue, true, "continuation is proposed, never vetoed");
    assert.deepEqual(capture.chunks, [], "an owned continuation is not a resource stop");
  } finally {
    capture.restore();
  }
});

test("a well-formed CONTINUE is never a resource-limited stop", async () => {
  // Counterpart to the test above: with no allowance to exhaust, an otherwise
  // proposable boundary always proposes, regardless of how many rounds came
  // before. `budget exhausted` no longer exists as a stop cause.
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
    const result = await proposes(pi, [assistant(CONTINUE)]);
    assert.equal(result?.continue, true, "a second round is still proposed under F1");
    assert.deepEqual(capture.chunks, [], "no resource-limited stop is reported");
  } finally {
    capture.restore();
  }
});

test("WAIT never continues, and its silence must be EARNED by wake proof", async () => {
  // The fixture names a subagent run, but this registration has no event bus, so
  // no owner can attest that the run exists. An unverifiable claim must not
  // suppress the user, and it must never propose a continuation either.
  const { pi, flush } = armedWithBus(() => undefined);
  const capture = captureStdout();
  try {
    assert.equal(await proposes(pi, [assistant(WAIT)]), undefined);
    pi.emit("agent_settled", settleEvent(), sessionCtx([assistant(WAIT)]));
    assert.deepEqual(capture.chunks, [], "the verification window has not expired yet");
    flush();
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "an unproven wake path must report itself as unverified",
    );
  } finally {
    capture.restore();
  }
});

// ---------------------------------------------------------------------------
// WAIT verification: silence is earned, never assumed
// ---------------------------------------------------------------------------

test("an exact current-session active async run keeps WAIT silent", async () => {
  // CURRENT-OWNER proof: the run was witnessed by this session (provenance) AND
  // the live RPC bridge reports it active in the exact run id.
  const { pi, bus, flushMs } = armedRpcWait({ runId: "3c1", state: "running" });
  const capture = captureStdout();
  try {
    const ctx = sessionCtx([assistant(WAIT)]);
    pi.emit("agent_settled", settleEvent(), ctx);
    flushMs(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "a proven wake path is not a wait for the user");
    assert.equal(bus.rpcRequests.length, 1, "exactly one bounded RPC query per settle");
    assert.equal(bus.rpcRequests[0].method, "status", "uses the read-only status method");
  } finally {
    capture.restore();
  }
});

test("a prior-turn async launch is verified only with matching provenance", async () => {
  // Proof requires BOTH provenance (this session witnessed the run) AND a live
  // RPC reply. Here both hold, so the WAIT stays silent.
  const { pi, flushMs } = armedRpcWait({ runId: "3c1", state: "queued" });
  const capture = captureStdout();
  try {
    pi.emit("agent_settled", settleEvent(), {
      ...UI,
      sessionFile: SESSION_FILE,
      sessionManager: sessionView([assistant(WAIT)]),
    });
    flushMs(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("terminal, mismatched, malformed, and missing runs all fail visibly", async () => {
  // Every case still carries valid provenance for `3c1`; the RPC reply alone
  // fails to prove CURRENT ownership. Terminal states, a mismatched id, a
  // malformed body, a missing reply, and a fleet-only reply must all notice.
  const cases = [
    ["a completed run", () => rpcSnapshot("3c1", "complete")],
    ["a failed run", () => rpcSnapshot("3c1", "failed")],
    ["a stopped run", () => rpcSnapshot("3c1", "stopped")],
    ["the wrong item", () => rpcSnapshot("other", "running")],
    ["a prefix, not the full id", () => rpcSnapshot("3", "running")],
    ["a fleet row with no run id", () => ({ fleet: { version: 1, entries: [{ key: "fleet-1", agent: "oracle" }], totalActive: 1 } })],
    ["a malformed reply", () => 42],
    ["no reply at all", () => null],
  ];
  for (const [label, rpc] of cases) {
    const { pi, flushMs } = armedRpcWait({ runId: "3c1", state: "running", rpc });
    const capture = captureStdout();
    try {
      pi.emit("agent_settled", settleEvent(), sessionCtx([assistant(WAIT)]));
      flushMs(WAIT_VERIFICATION_MS);
      assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT], label);
    } finally {
      capture.restore();
    }
  }
});

test("an observed START alone no longer proves a WAIT (past != current)", async () => {
  // Regression for the S2 contract change: the run IS in the ledger (witnessed
  // start, bound to this session, not terminal), but the live bridge does NOT
  // report it active. Observed START proves PAST existence, so the WAIT must
  // notice rather than believe the stale ledger row.
  const { pi, flushMs } = armedRpcWait({ runId: "3c1", state: "running", rpc: () => null });
  const capture = captureStdout();
  try {
    pi.emit("agent_settled", settleEvent(), sessionCtx([assistant(WAIT)]));
    flushMs(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT], "an observed START is not current liveness");
  } finally {
    capture.restore();
  }
});

test("a run with no provenance at all cannot be proven, even if the bridge is live", async () => {
  // The mirror of the previous case: the live bridge reports an active run, but
  // THIS session never witnessed it, so it is a foreign run and the WAIT fails.
  const { pi, flushMs } = armedRpcWait({ observe: false, runId: "3c1", state: "running" });
  const capture = captureStdout();
  try {
    pi.emit("agent_settled", settleEvent(), sessionCtx([assistant(WAIT)]));
    flushMs(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT], "foreign evidence must not silence");
  } finally {
    capture.restore();
  }
});

test("a throwing or unsupported event bus is unverified, not silent", async () => {
  for (const events of [
    undefined,
    {},
    {
      request() {
        throw new Error("no such owner");
      },
    },
  ]) {
    const { pi, flush } = armedWithBus(events);
    const capture = captureStdout();
    try {
      pi.emit("agent_settled", settleEvent(), sessionCtx([assistant(WAIT)]));
      flush();
      assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT]);
    } finally {
      capture.restore();
    }
  }
});

test("a provider-owned automatic wake proof keeps WAIT silent", async () => {
  const { pi, bus, flush } = armedWithBus((topic, request) => ({
    session: SESSION_FILE,
    id: request.id,
    pending: true,
    willWake: true,
  }));
  const capture = captureStdout();
  try {
    const marker = assistant("Waiting on the job.\n\nSTATUS:WAIT provider queue build-42 complete");
    pi.emit("agent_settled", settleEvent(), {
      ...UI,
      sessionFile: SESSION_FILE,
      sessionManager: sessionView([marker]),
    });
    flush();
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("an unsupported provider WAIT is unverified but never disturbed", async () => {
  const { pi, bus, flush } = armedWithBus(() => ({ session: SESSION_FILE, id: "build-42", pending: true }));
  const capture = captureStdout();
  try {
    const marker = assistant("Waiting.\n\nSTATUS:WAIT provider queue build-42 complete");
    pi.emit("agent_settled", settleEvent(), {
      ...UI,
      sessionFile: SESSION_FILE,
      sessionManager: sessionView([marker]),
    });
    flush();
    // `willWake` is absent, so the installed automatic wake path is NOT attested.
    assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT]);
    // The extension must not cancel, resume, or otherwise touch the provider's work.
    assert.equal(bus.requests.length, 1);
  } finally {
    capture.restore();
  }
});

test("new input, session change, and shutdown cancel a pending WAIT check", async () => {
  for (const supersede of [
    ["input", (pi) => pi.emit("input", { source: "interactive" }, IDLE_UI)],
    ["session_start", (pi) => pi.emit("session_start", {})],
    ["session_tree", (pi) => pi.emit("session_tree", {})],
  ]) {
    const [label, act] = supersede;
    const { pi, bus, flush } = armedWithBus(() => null);
    const capture = captureStdout();
    try {
      pi.emit("agent_settled", settleEvent(), sessionCtx([assistant(WAIT)]));
      act(pi);
      flush();
      assert.deepEqual(capture.chunks, [], `${label} must cancel the stale check`);
    } finally {
      capture.restore();
    }
  }
});

// ---------------------------------------------------------------------------
// Budget arming without `before_agent_start`
// ---------------------------------------------------------------------------

test("delivered genuine input arms the budget without before_agent_start", async () => {
  // The regression this fix exists for: `before_agent_start` is not guaranteed
  // to fire between `input` and the delivered user message, and when it did not,
  // a legitimate CONTINUE arrived with zero slots and stopped silently.
  const pi = makePi();
  mod.default(pi);
  pi.emit("input", { source: "interactive" }, IDLE_UI);
  pi.emit("message_start", { message: user("do it") }, IDLE_UI);
  const result = await proposes(pi, [assistant(CONTINUE)]);
  assert.equal(result?.continue, true, "a delivered user message must arm the allowance");
});

test("a late before_agent_start does not revoke an armed budget", async () => {
  const pi = makePi();
  mod.default(pi);
  pi.emit("input", { source: "interactive" }, IDLE_UI);
  pi.emit("before_agent_start", {}, IDLE_UI);
  pi.emit("message_start", { message: user("do it") }, IDLE_UI);
  // A SECOND start must not zero the allowance the delivered message granted.
  pi.emit("before_agent_start", {}, IDLE_UI);
  const result = await proposes(pi, [assistant(CONTINUE)]);
  assert.equal(result?.continue, true);
});

test("unconsumed input does not gate a well-formed CONTINUE", async () => {
  // S1 contract change: the request handshake was bound to the ALLOWANCE. With
  // the allowance gone it gates nothing, and it was never part of the S1
  // decision order. A well-formed CONTINUE therefore proposes (the invariant:
  // no silent stop for a valid marker).
  const pi = makePi();
  mod.default(pi);
  pi.emit("input", { source: "interactive" }, IDLE_UI);
  assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
  // Our own bridge is `custom`, which is not a user delivery and so changes
  // nothing either way.
  pi.emit("message_start", { message: { role: "custom", content: [] } }, IDLE_UI);
  assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
});

test("CONTINUE payloads containing waiting terminology remain SYNTACTICALLY valid", () => {
  // Classification is syntactic on purpose: rejecting a payload for using a
  // loaded word would also reject legitimate test and implementation steps.
  // The ONLY repair trigger is a LEADING human-wait CLAUSE ("awaiting your
  // pick", "waiting for your answer", "waiting on the user"); a bare "wait",
  // "await", or the word "WAIT" is never a blacklist keyword.
  for (const payload of [
    "STATUS:CONTINUE await the fixture and then launch the child",
    "STATUS:CONTINUE wait for the build, then run the tests",
    "STATUS:CONTINUE implement the WAIT branch",
  ]) {
    assert.equal(mod.declaredStatusOf(assistant(payload)), "continue", payload);
  }
});

test("DONE, BLOCKED, and FAILED notify without continuing", async () => {
  // A STRUCTURED external BLOCKED is a supported nonhuman dependency: it
  // notifies and never continues. (The legacy unstructured repository-write
  // BLOCKED now receives decision repair instead - see the repair suite below,
  // where it is an intentional behavior change.)
  const externalBlocked =
    "I cannot reach the migration host.\n\nSTATUS:BLOCKED external owner=ci-runner migration host unreachable";
  for (const text of [DONE, externalBlocked, FAILED]) {
    const pi = armed();
    const capture = captureStdout();
    try {
      assert.equal(await proposes(pi, [assistant(text)]), undefined);
      assert.deepEqual(capture.chunks, [OSC_NOTIFY], text);
      // The settle repeats the decision through `agent_settled`; the dedupe flag
      // means it does not double-notify within one epoch.
      pi.emit("agent_settled", settleEvent(), { ...UI, sessionManager: sessionView([assistant(text)]) });
      assert.deepEqual(capture.chunks, [OSC_NOTIFY], `${text} must not notify twice`);
    } finally {
      capture.restore();
    }
  }
});

test("marker near-misses still stop, but name the formatting cause", async () => {
  // The reported defect: a status one space off column zero, or one whose
  // payload wraps to the next line, parses to `null` exactly like a message
  // that declares nothing. The parser result MUST stay null (no continuation),
  // while the notice names the formatting problem.
  const fixtures = [
    ["leading space only", "Work remains.\n\n STATUS:CONTINUE do X"],
    ["wrapped payload", "Work remains.\n\nSTATUS:CONTINUE do X\n and also Y"],
    [
      "the exact reported fixture",
      "Next: the list-path defect, then LanceDB over the flat account.\n\n" +
        " STATUS:CONTINUE fix the FileManager child-URI authority-dropping defect " +
        "(filemanager.py list_files/list_children), then validate\n LanceDB " +
        "create/append/reopen/query on the flat account.",
    ],
  ];
  for (const [label, text] of fixtures) {
    // Parser level: the message still declares nothing.
    assert.equal(mod.readDeclaredMarker(assistant(text)), null, `parse: ${label}`);
    // Pipeline level: no continuation, and a placement-specific notice.
    const pi = armed();
    const capture = captureStdout();
    try {
      assert.equal(await proposes(pi, [assistant(text)]), undefined, `propose: ${label}`);
      assert.deepEqual(capture.chunks, [OSC_INVALID_PLACEMENT], `notice: ${label}`);
    } finally {
      capture.restore();
    }
  }

  // The canonical form of the SAME declaration still continues.
  assert.deepEqual(mod.readDeclaredMarker(assistant("Work remains.\n\nSTATUS:CONTINUE do X")), {
    status: "continue",
    payload: "do X",
  });
});

test("no marker keeps the generic notice - the hint never fabricates a cause", async () => {
  const pi = armed();
  const capture = captureStdout();
  try {
    assert.equal(await proposes(pi, [assistant("I did some work, but did not say what is next.")]), undefined);
    assert.deepEqual(capture.chunks, [OSC_NOTIFY]);
  } finally {
    capture.restore();
  }
});

test("a column-zero marker whose payload wrapped reports the EMPTY-payload cause, not placement", async () => {
  // The reported defect: the marker IS at column zero, but its payload sits on
  // the next physical line, so the line parses to an empty payload. Telling the
  // reader to "use a final column-zero STATUS line" is false - the line is
  // already there - and sends them to fix formatting that was correct. The stop
  // itself is unchanged: a wrapped marker still declares nothing.
  for (const [label, text] of [
    ["WAIT payload wrapped", "Work remains.\n\nSTATUS:WAIT\nsubagent a1b2c3d4 complete"],
    ["CONTINUE payload wrapped", "Work remains.\n\nSTATUS:CONTINUE\ndo the thing"],
    ["BLOCKED payload wrapped", "Work remains.\n\nSTATUS:BLOCKED\nowner=ci waiting"],
  ]) {
    assert.equal(mod.readDeclaredMarker(assistant(text)), null, `parse: ${label}`);
    const pi = armed();
    const capture = captureStdout();
    try {
      assert.equal(await proposes(pi, [assistant(text)]), undefined, `propose: ${label}`);
      assert.deepEqual(capture.chunks, [OSC_EMPTY_PAYLOAD], `notice: ${label}`);
    } finally {
      capture.restore();
    }
  }

  // A DONE whose payload wrapped is a payload-free status, so it must NOT be
  // reported as a missing payload; it simply does not declare as DONE either.
  assert.equal(
    mod.readDeclaredMarker(assistant("Done.\n\nSTATUS:DONE\ntrailing prose")),
    null,
  );
});

test("a payload-free status that does not declare never gets the payload-placement hint", async () => {
  // C41-1. `STATUS:DONE` FORBIDS a payload, so `STATUS:DONE` followed by a
  // wrapped `trailing prose` line is a genuinely ineligible/ignored marker - not
  // a missing payload. The old `markerProblemFor` returned `empty-payload` for
  // ANY column-zero candidate with an empty payload, so the emitted notice told
  // the reader to add a payload to DONE, which is invalid advice.
  const text = "Done.\n\nSTATUS:DONE\ntrailing prose";

  // Parser is unchanged: the message declares nothing.
  assert.equal(mod.readDeclaredMarker(assistant(text)), null, "parse: declares nothing");

  // The notice is the real observable. It must NOT carry payload-placement
  // advice; the line is simply ineligible as a marker.
  const pi = armed();
  const capture = captureStdout();
  try {
    assert.equal(await proposes(pi, [assistant(text)]), undefined, "propose: no continuation");
    assert.deepEqual(capture.chunks, [OSC_INVALID_PLACEMENT], "notice: placement cause, not payload");
    assert.equal(
      capture.chunks.some((chunk) => chunk.includes("put the payload on the SAME line")),
      false,
      "payload-placement advice must not appear",
    );
  } finally {
    capture.restore();
  }
});

test("a payload-bearing status with a wrapped payload keeps the same-line hint", async () => {
  // Complementary case: CONTINUE/WAIT DO require a payload, so a column-zero
  // line whose payload wrapped onto the next line is a genuine empty-payload
  // problem and MUST still receive the same-line hint.
  for (const [label, text] of [
    ["CONTINUE payload wrapped", "Work remains.\n\nSTATUS:CONTINUE\ndo the thing"],
    ["WAIT payload wrapped", "Work remains.\n\nSTATUS:WAIT\nsubagent a1b2c3d4 complete"],
  ]) {
    assert.equal(mod.readDeclaredMarker(assistant(text)), null, `parse: ${label}`);
    const pi = armed();
    const capture = captureStdout();
    try {
      assert.equal(await proposes(pi, [assistant(text)]), undefined, `propose: ${label}`);
      assert.deepEqual(capture.chunks, [OSC_EMPTY_PAYLOAD], `notice: ${label}`);
    } finally {
      capture.restore();
    }
  }
});

test("quoted, fenced and list examples never propose a continuation", async () => {
  // Widening acceptance to these was considered and rejected: each would grant
  // an unwarranted continuation. They must not continue.
  for (const [label, text] of [
    ["a fenced example", "Here is the protocol:\n\n```\nSTATUS:CONTINUE x\n```"],
    ["a quoted example", 'The agent said "STATUS:CONTINUE x" in its reply.'],
    ["a list item", "Example:\n\n  STATUS:CONTINUE x"],
    ["prose beneath prose", "Next steps:\nSTATUS:CONTINUE x"],
  ]) {
    const pi = armed();
    assert.equal(await proposes(pi, [assistant(text)]), undefined, label);
  }
});

test("the canonical acceptance boundary is unchanged", () => {
  // Verified against the real parser: a blank line makes preceding prose
  // irrelevant, its absence makes the status content of the line above.
  assert.equal(
    mod.readDeclaredMarker(assistant("Done.\n\nSTATUS:CONTINUE x"))?.status,
    "continue",
  );
  // NOT null: the line parses but is ineligible, so it resolves to `unknown`
  // with a problem. Safety is identical - `unknown` never continues.
  const inline = mod.readDeclaredMarker(assistant("Done.\nSTATUS:CONTINUE x"));
  assert.equal(inline?.status, "unknown");
  assert.equal(inline?.problem, "ineligible-line");
});

test("a malformed marker notifies once across boundary and settlement", async () => {
  const text = "Work remains.\n\n STATUS:CONTINUE do X";
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    const view = sessionView([assistant(text)]);
    pi.emit("agent_before_settle", boundaryEvent([assistant(text)]), { ...UI, sessionManager: view });
    pi.emit("agent_settled", settleEvent(), { ...UI, sessionManager: view });
    assert.deepEqual(out.chunks, [OSC_INVALID_PLACEMENT], "notified exactly once");
  } finally {
    restore();
  }
});

test("the settlement-only path also names a malformed marker", async () => {
  // The boundary call and the settlement call are INDEPENDENT paths. This
  // exercises settlement alone, so a regression that drops the hint from the
  // settlement branch cannot hide behind the boundary assertion above.
  for (const [label, text, notice] of [
    ["a near-miss", "Work remains.\n\n STATUS:CONTINUE do X", OSC_INVALID_PLACEMENT],
    ["no marker", "nothing declared", OSC_NOTIFY],
    ["a true ambiguous pair", "STATUS:DONE x\n\nSTATUS:CONTINUE x", OSC_AMBIGUOUS],
  ]) {
    const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
    try {
      pi.emit("agent_settled", settleEvent(), {
        ...UI,
        sessionManager: sessionView([assistant(text)]),
      });
      assert.deepEqual(out.chunks, [notice], label);
    } finally {
      restore();
    }
  }
});

test("an unknown status notifies: 'notify when not sure'", async () => {
  const cases = [
    ["no marker at all", assistant("I did some work, but did not say what is next.")],
    ["a table", assistant("| a | b |\n|---|---|\n| 1 | 2 |")],
    ["empty text", assistant("")],
    ["thinking only", thinking("STATUS:DONE")],
    ["a tool result as the final message", { role: "toolResult", content: [{ type: "text", text: DONE }] }],
    ["a user message as the final message", user("what now?")],
    ["an ambiguous pair", assistant("STATUS:DONE\nSTATUS:CONTINUE x"), OSC_INVALID_PLACEMENT],
    ["a malformed status", assistant("hn\nSTATUS:CONTINUE"), OSC_INVALID_PLACEMENT],
    // Near-misses are still REFUSED; their notice now names the formatting
    // cause instead of the generic "needs attention". Acceptance is unchanged:
    // every case here still proposes no continuation. The two fixtures above
    // changed notice text only - both are `ineligible-line` (a status with no
    // blank line above it), which the placement hint describes more precisely
    // than the generic notice did. A TRUE `ambiguous` (blank line between two
    // conflicting statuses) is asserted separately below.
    ["a truly ambiguous pair", assistant("STATUS:DONE x\n\nSTATUS:CONTINUE x"), OSC_AMBIGUOUS],
  ];
  for (const [label, message, notice = OSC_NOTIFY] of cases) {
    const pi = armed();
    const capture = captureStdout();
    try {
      assert.equal(await proposes(pi, [message]), undefined, label);
      assert.deepEqual(capture.chunks, [notice], label);
    } finally {
      capture.restore();
    }
  }
});

test("a missing marker notifies at actual settlement", async () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    pi.emit("agent_settled", settleEvent(), { ...UI, sessionManager: sessionView([assistant("nothing declared")]) });
    assert.deepEqual(out.chunks, [OSC_NOTIFY]);
  } finally {
    restore();
  }
});

test("WAIT from the session view is READ, and an unprovable one notifies", async () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    // Notification events carry no context: the branch is read from the session
    // view, which is the only surface that survives the event boundary. Under
    // S2 a WAIT with NO provable owner must NOTIFY rather than silence, and this
    // path proves the view's FINAL message was read at all.
    pi.emit("agent_settled", settleEvent(), { ...UI, sessionManager: sessionView([assistant(WAIT)]) });
    assert.deepEqual(out.chunks, [OSC_UNVERIFIED_WAIT], "an unprovable WAIT must notify");
    // An absent or throwing view fails toward NOTIFYING, never to silence.
    pi.emit("input", {}, UI);
    pi.emit("agent_settled", settleEvent(), UI);
    assert.deepEqual(out.chunks, [OSC_UNVERIFIED_WAIT, OSC_NOTIFY], "an unavailable view must notify");
  } finally {
    restore();
  }
});

test("the settled path reads only the FINAL message, never an older declaration", async () => {
  // Counterexample from independent review: a textless trailing entry used to be
  // skipped, letting an older WAIT resurrect itself and suppress a notification
  // the user genuinely needed. Each case gets a fresh registration because the
  // notification is deduped per session.
  const cases = [
    ["an older WAIT then a textless assistant tail", [assistant(WAIT), { role: "assistant", content: [] }]],
    ["an older WAIT then a tool tail", [assistant(WAIT), { role: "toolResult", content: [] }]],
    ["an older WAIT then thinking only", [assistant(WAIT), thinking("still working")]],
    ["an older CONTINUE then a textless tail", [assistant(CONTINUE), { role: "assistant", content: [] }]],
  ];
  for (const [label, messages] of cases) {
    const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
    try {
      pi.emit("agent_settled", settleEvent(), { ...UI, sessionManager: sessionView(messages) });
      assert.deepEqual(out.chunks, [OSC_NOTIFY], label);
    } finally {
      restore();
    }
  }
  // And a genuine final declaration is what the view reads: a final WAIT with no
  // proof notifies (the older CONTINUE does NOT win), demonstrating the settled
  // path reads the FINAL message rather than an older one.
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    pi.emit("agent_settled", settleEvent(), {
      ...UI,
      sessionManager: sessionView([assistant(CONTINUE), assistant(WAIT)]),
    });
    assert.deepEqual(out.chunks, [OSC_UNVERIFIED_WAIT], "the FINAL declaration still wins");
  } finally {
    restore();
  }
});

// ---------------------------------------------------------------------------
// Boundary gates
// ---------------------------------------------------------------------------

test("an aborted or errored boundary outcome never continues and notifies", async () => {
  for (const outcome of ["aborted", "error"]) {
    const pi = armed();
    const capture = captureStdout();
    try {
      const result = await proposes(pi, [assistant(CONTINUE)], { outcome });
      assert.equal(result, undefined, outcome);
      assert.deepEqual(capture.chunks, [OSC_NOTIFY], outcome);
    } finally {
      capture.restore();
    }
  }
});

test("a headless boundary never proposes and never notifies", async () => {
  for (const ctx of [HEADLESS, RPC, { hasUI: true, mode: "json" }, undefined, {}]) {
    const pi = armed();
    const handler = handlerFor(pi, "agent_before_settle");
    const result = await handler(boundaryEvent([assistant(CONTINUE)]), ctx);
    assert.equal(result, undefined, "no continuation outside a TUI");
  }
});

// ---------------------------------------------------------------------------
// Budget
// ---------------------------------------------------------------------------

/** Let the runtime commit an accepted proposal into the branch. */
function commit(branch, result) {
  if (!result || result.continue !== true) return branch;
  return [
    ...branch,
    ...result.entries.map((entry) => ({
      role: "custom",
      customType: entry.customType,
      content: entry.content,
      display: entry.display,
    })),
  ];
}

/**
 * Drive the boundary loop the way Pi's prompt runner does.
 *
 * Each round models one full request: the model prints an assistant message (the
 * one under test), the boundary runs, and an accepted proposal is committed as a
 * `custom` bridge on top of the branch - exactly the shape Pi projects before
 * the next assistant message replaces it as the final element.
 */
async function settleRounds(pi, tail, { rounds = 6, declared = CONTINUE } = {}) {
  const handler = handlerFor(pi, "agent_before_settle");
  let accepted = 0;
  let current = [user("do it"), ...tail];
  // Each round drives the boundary with the EVOLVING projection: an accepted
  // proposal commits its bridge, and the next round's final message is a FRESH
  // assistant declaration on top of it. Passing the static `tail` every round
  // would leave the saved branch ending in a custom bridge and test an unknown
  // marker instead of genuine budget exhaustion.
  for (let round = 0; round < rounds; round += 1) {
    const result = await handler(boundaryEvent([...current, assistant(declared)]), UI);
    if (result?.continue !== true) break;
    accepted += 1;
    current = commit(current.concat(assistant(declared)), result);
  }
  return { accepted, branch: current };
}

test("a compaction boundary before the declaration does not hide it", async () => {
  // Pi compacts BEFORE the before-settle boundary runs: `_handlePostAgentRun()`
  // calls `_checkCompaction()` and only then does the loop reach
  // `_runBeforeSettleBoundary()` (agent-session.js:1355-1367). The projected
  // context therefore contains a compaction entry when the boundary fires.
  //
  // `buildContextEntries()` (session-manager.js:201) projects that entry as a
  // USER-role compaction summary message, kept entries follow it, and the
  // assistant message that declared is still the FINAL projected message. A
  // naive `messages.at(-1)`-style read that mistook the summary for the last
  // message would notify instead of continuing, so this pins the real shape.
  const compactionSummary = user("[summary of earlier conversation]");
  const keptTail = [assistant("earlier work"), user("earlier prompt")];
  const declared = assistant("Compaction is context management, not a decision.\n\n" + CONTINUE);

  const pi = armed();
  const capture = captureStdout();
  try {
    const result = await proposes(pi, [compactionSummary, ...keptTail, declared]);
    assert.equal(result?.continue, true, "a declaration after compaction still proposes");
    assert.equal(
      result.entries.at(-1).customType,
      mod.BRIDGE_CUSTOM_TYPE,
      "the bridge entry is appended on top of the compacted projection",
    );
    assert.deepEqual(capture.chunks, [], "a granted continuation does not notify");
  } finally {
    capture.restore();
  }
});

test("a compaction entry is never mistaken for a declaration", async () => {
  // A compaction summary is a user-role message, so it can never declare: the
  // detector requires the assistant role. These cases pin that a compacted
  // projection with no assistant declaration notifies rather than silently
  // continuing, including when the summary text itself mentions the protocol.
  const summaryMentioning = user("Earlier we discussed STATUS:CONTINUE and STATUS:DONE.");
  const pi = armed();
  const capture = captureStdout();
  try {
    // Compaction summary as the final projected message: no declaration, notify.
    const bare = await proposes(pi, [summaryMentioning], {
      context: { contextMessages: [summaryMentioning], canContinue: false },
    });
    assert.equal(bare, undefined, "a user-role summary cannot grant a continuation");
    assert.deepEqual(capture.chunks, [OSC_NOTIFY], "no declaration after compaction must notify");
  } finally {
    capture.restore();
  }

  // A WAIT that survives compaction stays silent, exactly as without compaction.
  const pi2 = armed();
  const capture2 = captureStdout();
  try {
    const waited = await proposes(pi2, [
      user("[summary of earlier conversation]"),
      assistant("Waiting on the background child.\n\n" + WAIT),
    ]);
    assert.equal(waited, undefined, "a WAIT after compaction does not continue");
    assert.deepEqual(capture2.chunks, [], "and does not notify either");
  } finally {
    capture2.restore();
  }
});

test("compaction is not a user request: the handshake governs, not a counter", async () => {
  // Context management is not a new user request. Under F1 there is no
  // allowance for compaction to replenish - and none to exhaust - so an
  // interleaved compaction summary changes nothing: the handshake already
  // completed, so each well-formed CONTINUE still proposes.
  const pi = armedWithBudget(MAX_CONTINUATIONS);
  const capture = captureStdout();
  try {
    const first = await proposes(pi, [assistant(CONTINUE)]);
    assert.equal(first?.continue, true, "a well-formed declaration proposes");

    // Interleave a compaction summary, then propose again.
    const second = await proposes(pi, [
      user("[summary of earlier conversation]"),
      assistant(CONTINUE),
    ]);
    assert.equal(second?.continue, true, "compaction neither replenishes nor exhausts anything");

    const third = await proposes(pi, [
      user("[summary of earlier conversation]"),
      assistant(CONTINUE),
    ]);
    assert.equal(third?.continue, true, "and repeated compaction still cannot stop a CONTINUE");
    assert.deepEqual(capture.chunks, [], "no resource-limited stop is ever reported");
  } finally {
    capture.restore();
  }
});

test("a named CONTINUE step proposes on every round and never exhausts", async () => {
  const pi = armedWithBudget(MAX_CONTINUATIONS);
  const capture = captureStdout();
  try {
    const { accepted, branch } = await settleRounds(pi, [], { rounds: MAX_CONTINUATIONS });
    assert.equal(accepted, MAX_CONTINUATIONS, "each round proposed");
    assert.equal(
      branch.filter((m) => m.customType === mod.BRIDGE_CUSTOM_TYPE).length,
      MAX_CONTINUATIONS,
      "one bridge per accepted proposal",
    );
    assert.deepEqual(capture.chunks, [], "no notification is emitted");

    // A further FRESH declaration on top of the committed bridges still has no
    // counter to spend: it proposes exactly as the first one did.
    const third = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([...branch, assistant(CONTINUE)]),
      UI,
    );
    assert.equal(third?.continue, true, "round one more still proposes");
    assert.deepEqual(capture.chunks, [], "no exhaustion notice exists under F1");
    assert.equal(
      (await proposes(pi, [...branch, assistant(CONTINUE)]))?.continue,
      true,
      "and the round after that as well",
    );
  } finally {
    capture.restore();
  }
});

test("a fresh session proposes on a well-formed CONTINUE", async () => {
  // S1 contract change: an unarmed session is no longer a stop. The handshake
  // was an allowance concept and is not part of the S1 decision order, so a
  // well-formed CONTINUE proposes and no notice is emitted.
  const pi = makePi();
  mod.registerSessionSupervisor(pi, {});
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
    assert.deepEqual(capture.chunks, [], "a valid marker is not a stop");
  } finally {
    capture.restore();
  }
});

test("a positive PI_MAX_CONTINUATIONS value no longer imposes a finite allowance", async () => {
  // S1 contract change: a cumulative counter is exactly what made well-formed
  // CONTINUEs stop silently. Positive values (including explicit finite ones)
  // now mean continuation is permitted; the warn-once treatment of a finite
  // value lands in S3. No round may be refused for want of a counter.
  const pi = armedWithBudget(4);
  const capture = captureStdout();
  try {
    const { accepted, branch } = await settleRounds(pi, [], { rounds: 4 });
    assert.equal(accepted, 4, "every round proposed");
    assert.deepEqual(capture.chunks, [], "no notification while work continues");
    const fifth = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([...branch, assistant(CONTINUE)]),
      UI,
    );
    assert.equal(fifth?.continue, true, "the configured value does not cap ordinary continuation");
    assert.deepEqual(capture.chunks, [], "and it is never reported as exhausted");
  } finally {
    capture.restore();
  }
});

test("PI_MAX_CONTINUATIONS=0 disables automatic continuation", async () => {
  const pi = armedWithBudget(0);
  const capture = captureStdout();
  try {
    assert.equal(await proposes(pi, [assistant(CONTINUE)]), undefined);
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY],
      "a disabled budget is a configuration, not an exhausted one",
    );
  } finally {
    capture.restore();
  }
});

test("resolveMaxContinuations parses, bounds, and rejects invalid values", () => {
  assert.equal(
    resolveMaxContinuations(undefined),
    Number.POSITIVE_INFINITY,
    "unset is unlimited by default",
  );
  assert.equal(
    resolveMaxContinuations("  "),
    Number.POSITIVE_INFINITY,
    "blank is unlimited by default",
  );
  assert.equal(resolveMaxContinuations("0"), 0, "zero is a valid explicit value");
  assert.equal(resolveMaxContinuations("4"), 4);
  const noWarn = (message) => {
    throw new Error(`unexpected warning: ${message}`);
  };
  assert.equal(resolveMaxContinuations("64", noWarn), 64, "no longer the ceiling");
  assert.equal(resolveMaxContinuations("65", noWarn), 65, "above the former ceiling, no warning");
  assert.equal(resolveMaxContinuations("100", noWarn), 100);
  assert.equal(
    resolveMaxContinuations(String(Number.MAX_SAFE_INTEGER), noWarn),
    Number.MAX_SAFE_INTEGER,
    "the exact finite ceiling is accepted",
  );

  const warned = [];
  const warn = (message) => warned.push(message);
  assert.equal(
    resolveMaxContinuations("2abc", warn),
    Number.POSITIVE_INFINITY,
    "no parseInt",
  );
  assert.equal(resolveMaxContinuations("-1", warn), Number.POSITIVE_INFINITY);
  assert.equal(resolveMaxContinuations("1.5", warn), Number.POSITIVE_INFINITY);
  assert.equal(
    resolveMaxContinuations("9007199254740992", warn),
    HARD_MAX_CONTINUATIONS,
    "above the ceiling clamps, not falls back",
  );
  assert.equal(
    resolveMaxContinuations("9".repeat(400), warn),
    HARD_MAX_CONTINUATIONS,
    "a numeric conversion to Infinity still clamps",
  );
  assert.equal(warned.length, 5, "every invalid value warned exactly once");
});

test("the unlimited default crosses the former ceiling without a resource stop", async () => {
  // The runtime default is unlimited: a genuine request must never be stopped
  // by a count. 100 exceeds every former finite ceiling (64 and 2), so this
  // pins that the default no longer behaves like a small fuse.
  const pi = armed();
  const capture = captureStdout();
  try {
    const { accepted, branch } = await settleRounds(pi, [], { rounds: 100 });
    assert.equal(accepted, 100, "the unlimited default accepted all 100 rounds");
    assert.deepEqual(capture.chunks, [], "an unlimited allowance never notifies about exhaustion");

    // A fresh CONTINUE on top of the committed bridges still earns a slot.
    const beyond = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([...branch, assistant(CONTINUE)]),
      UI,
    );
    assert.equal(beyond?.continue, true, "a fresh declaration past the former ceiling still proposes");
    assert.deepEqual(capture.chunks, [], "and still does not report exhaustion");
  } finally {
    capture.restore();
  }
});

test("the unlimited default governs decision repair as well as ordinary continuation", async () => {
  // Repair draws from the SAME policy. A sequence that mixes ordinary
  // continuations and repairs and exceeds the former two-slot allowance must be
  // fully accepted under the default.
  const pi = armed();
  const capture = captureStdout();
  try {
    let branch = [user("do it")];
    const handler = handlerFor(pi, "agent_before_settle");
    for (let i = 0; i < 4; i += 1) {
      const declaration = i % 2 === 0 ? CONTINUE : BLOCKED;
      const result = await handler(boundaryEvent([...branch, assistant(declaration)]), UI);
      assert.equal(result?.continue, true, `round ${i} (${i % 2 === 0 ? "continue" : "repair"}) proposed`);
      const expectedType = i % 2 === 0 ? mod.BRIDGE_CUSTOM_TYPE : mod.REPAIR_CUSTOM_TYPE;
      assert.equal(result.entries.at(-1).customType, expectedType, `round ${i} used the expected bridge`);
      branch = commit(branch.concat(assistant(declaration)), result);
    }
    assert.deepEqual(capture.chunks, [], "unlimited mixed continuation and repair never notifies");
  } finally {
    capture.restore();
  }
});

test("continuation and repair share one proposal path with no shared counter", async () => {
  // S1 contract change: repair and ordinary continuation are consolidated into
  // ONE path, so there is no shared finite ledger to spend. A finite configured
  // value must not cap either kind of proposal.
  const pi = armedWithBudget(2);
  const capture = captureStdout();
  try {
    const handler = handlerFor(pi, "agent_before_settle");
    let branch = [user("do it")];

    const first = await handler(boundaryEvent([...branch, assistant(CONTINUE)]), UI);
    assert.equal(first?.continue, true, "the ordinary continuation proposes");
    branch = commit(branch.concat(assistant(CONTINUE)), first);

    const repair = await handler(boundaryEvent([...branch, assistant(BLOCKED)]), UI);
    assert.equal(repair?.continue, true, "a decision repair proposes");
    assert.equal(repair.entries.at(-1).customType, mod.REPAIR_CUSTOM_TYPE, "the second proposal was a repair");
    branch = commit(branch.concat(assistant(BLOCKED)), repair);

    const third = await handler(boundaryEvent([...branch, assistant(CONTINUE)]), UI);
    assert.equal(third?.continue, true, "neither kind of proposal is capped");
    assert.deepEqual(capture.chunks, [], "no exhaustion notice is ever emitted");
  } finally {
    capture.restore();
  }
});

test("unlimited continuation remains interruptible by abort", async () => {
  const pi = armed();
  const capture = captureStdout();
  try {
    const { accepted, branch } = await settleRounds(pi, [], { rounds: 5 });
    assert.equal(accepted, 5, "several continuations were accepted under the default");

    // An aborted boundary prohibits continuation for its own reason - this is
    // step (1) of the decision order and survives F1 unchanged.
    const aborted = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([...branch, assistant(CONTINUE)], { outcome: "aborted" }),
      UI,
    );
    assert.equal(aborted, undefined, "an aborted boundary proposes nothing");
    assert.deepEqual(capture.chunks, [OSC_NOTIFY], "and it notifies");
  } finally {
    capture.restore();
  }
});

test("no counter is established or raised: the handshake alone governs", async () => {
  // S1 contract change: with no cumulative allowance, the old "resolved once per
  // registration" defence has nothing to defend. Three rounds always propose,
  // whatever the configured value and whatever happens to the environment later.
  const env = { PI_MAX_CONTINUATIONS: "2" };
  const pi = makePi();
  mod.registerSessionSupervisor(pi, env);
  handshake(pi);
  const capture = captureStdout();
  try {
    env.PI_MAX_CONTINUATIONS = "64";
    const { accepted, branch } = await settleRounds(pi, [], { rounds: 3 });
    assert.equal(accepted, 3, "every round proposes regardless of the configured value");
    const fourth = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([...branch, assistant(CONTINUE)]),
      UI,
    );
    assert.equal(fourth?.continue, true, "and still proposes");
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("steering input does not gate a well-formed CONTINUE", async () => {
  // S1 contract change: steering used to revoke the allowance. With no
  // allowance it gates nothing, and it is not in the S1 decision order.
  const pi = armedWithBudget(4);
  const capture = captureStdout();
  try {
    pi.emit(
      "input",
      { type: "input", text: "steer", source: "interactive", streamingBehavior: "steer" },
      tuiCtx(),
    );
    assert.equal(
      (await proposes(pi, [assistant(CONTINUE)]))?.continue,
      true,
      "steering does not stop a valid marker",
    );
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("a replacement request proposes on a well-formed CONTINUE", async () => {
  // S1 contract change: an unfinished replacement handshake is not a stop. The
  // first request proposed; the replacement proposes too - there is no counter
  // to inherit or exhaust.
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
    pi.emit("input", { type: "input", text: "again", source: "interactive" }, tuiCtx());
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "again" }, tuiCtx());
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("a spent budget on an aborted boundary reports attention, not exhaustion", async () => {
  // `outcome !== \"completed\"` independently prohibits continuation. Reporting a
  // spent budget there would name the wrong cause.
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true, "the slot is spent");
    const aborted = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(CONTINUE)], { outcome: "aborted" }),
      UI,
    );
    assert.equal(aborted, undefined, "an aborted boundary never proposes");
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY],
      "an aborted boundary is attention, not budget exhaustion",
    );
  } finally {
    capture.restore();
  }
});

test("a spent budget on an error boundary reports attention, not exhaustion", async () => {
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true, "the slot is spent");
    const errored = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(CONTINUE)], { outcome: "error" }),
      UI,
    );
    assert.equal(errored, undefined, "an error boundary never proposes");
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY],
      "an error boundary is attention, not budget exhaustion",
    );
  } finally {
    capture.restore();
  }
});

test("a spent budget on a boundary with no entries reports attention, not exhaustion", async () => {
  // No draft array means the declaration could not have been acted on, so a
  // resource limit is not the operative cause.
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true, "the slot is spent");
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(CONTINUE)], { entries: undefined }),
      UI,
    );
    assert.equal(result, undefined, "a boundary without entries cannot carry a bridge");
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY],
      "a missing entries array is attention, not budget exhaustion",
    );
  } finally {
    capture.restore();
  }
});

test("a bare settle proposes on a well-formed CONTINUE with no prior input", async () => {
  // S1 contract change: with no allowance there is nothing to arm, and the
  // handshake is not in the decision order. A valid marker proposes even with no
  // prior input, and emits no notice.
  const pi = makePi();
  mod.registerSessionSupervisor(pi, {});
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
    assert.deepEqual(capture.chunks, [], "no stop is reported for a valid marker");

    // A genuine request changes nothing about that.
    handshake(pi, { text: "please continue" });
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
  } finally {
    capture.restore();
  }
});

test("no handshake step gates a well-formed CONTINUE", async () => {
  // S1 contract change: every case below used to leave the request unconsumed
  // and so block continuation. The handshake is not in the S1 decision order, so
  // none of these is a stop; the invariant is that a valid marker always
  // proposes. (The abort/error/disable vetoes live in step (1) and are covered
  // separately.)
  const cases = [
    ["input without a delivered message", (pi) => pi.emit("input", { source: "interactive" }, tuiCtx())],
    ["a user message with no handshake", (pi) => pi.emit("message_start", { message: { role: "user" } }, tuiCtx())],
    ["extension-origin input", (pi) => handshake(pi, { source: "extension" })],
    ["steering input", (pi) => handshake(pi, { source: "interactive", steering: true })],
    ["a non-idle host", (pi) => handshake(pi, { ctx: { ...UI, isIdle: () => false } })],
    ["a throwing isIdle", (pi) => handshake(pi, { ctx: { ...UI, isIdle: () => { throw new Error("boom"); } } })],
  ];
  for (const [label, step] of cases) {
    const pi = makePi();
    mod.registerSessionSupervisor(pi, {});
    step(pi);
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true, label);
  }
});

const tuiCtx = () => ({ ...UI, isIdle: () => true });

test("our own bridge continuation does not stop the next CONTINUE", async () => {
  const pi = armedWithBudget(MAX_CONTINUATIONS);
  const { accepted, branch } = await settleRounds(pi, []);
  assert.equal(accepted, 6, "every round proposes (no counter stops it)");
  assert.equal(
    branch.filter((m) => m.customType === mod.BRIDGE_CUSTOM_TYPE).length,
    accepted,
    "one bridge per accepted proposal",
  );
  // The bridge is projected as a `custom` message, which is not a user
  // delivery. Under F1 there is no counter for it to arm or disarm, so the
  // property that matters is simply that continuation keeps working.
  pi.emit("message_start", { message: { role: "custom", customType: mod.BRIDGE_CUSTOM_TYPE } }, tuiCtx());
  assert.equal(
    (await proposes(pi, [assistant(CONTINUE)]))?.continue,
    true,
    "a custom message neither arms nor disarms anything",
  );
});

test("session change and tree navigation do not stop a well-formed CONTINUE", async () => {
  // S1 contract change: there is no allowance to disarm, and these lifecycle
  // events are not in the S1 decision order. A valid marker keeps proposing.
  for (const event of ["session_start", "session_tree"]) {
    const pi = armed();
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);

    pi.emit(event, { type: event }, UI);
    assert.equal(
      (await proposes(pi, [assistant(CONTINUE)]))?.continue,
      true,
      `${event} does not gate continuation`,
    );
  }
});

test("a well-formed CONTINUE never returns a negative continuation", async () => {
  // Returning `undefined` leaves another handler's `continue` untouched;
  // returning `continue: false` would cancel unrelated work. Under F1 a
  // well-formed CONTINUE always returns a positive proposal.
  const pi = armedWithBudget(MAX_CONTINUATIONS);
  await settleRounds(pi, []);
  const result = await proposes(pi, [assistant(CONTINUE)]);
  assert.equal(result?.continue, true, "continuation is proposed, never vetoed negatively");
});

test("a proposal is never refunded: every round proposes", async () => {
  // S1 contract change: the ledger that made "no refund" observable is gone.
  // Uncommitted proposals no longer exist, so the property becomes the stronger
  // one the contract now requires - a marker keeps proposing.
  const pi = armedWithBudget(MAX_CONTINUATIONS);
  assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
  assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
  assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
});

test("a malformed entries surface cannot be spread", async () => {
  const pi = armed();
  assert.equal(await proposes(pi, [assistant(CONTINUE)], { entries: null }), undefined);
});

// ---------------------------------------------------------------------------
// Projection fallback for a trailing non-assistant entry
// ---------------------------------------------------------------------------

test("a trailing draft with no text never resurrects an older declaration", async () => {
  const pi = armed();
  const capture = captureStdout();
  try {
    // A `custom_message` ENTRY (not a projected message) another handler
    // drafted: it appears in `boundary.entries` and must be preserved, but it is
    // not a projection entry and so cannot change what the model declared. The
    // declaration is read from the final PROJECTED message, not from `entries`.
    const draft = { type: "custom_message", customType: "context7", content: "", display: false };
    // A WAIT settle stays silent and the draft is not disturbed.
    assert.equal(await proposes(pi, [assistant(WAIT)], { entries: [draft] }), undefined);
    assert.deepEqual(capture.chunks, []);

    const continued = await proposes(pi, [assistant(CONTINUE)], { entries: [draft] });
    assert.equal(continued?.continue, true);
    assert.equal(continued.entries[0], draft, "the trailing entry is preserved");
    assert.equal(continued.entries[1].customType, mod.BRIDGE_CUSTOM_TYPE);
  } finally {
    capture.restore();
  }
});

test("the fallback never overrides a final message that has text and no marker", async () => {
  // Each case gets a FRESH registered instance: `notify` is deduped per session,
  // so reusing one instance would swallow the second notification.
  const cases = [
    ["prose with no marker", [assistant(WAIT), assistant("Still thinking about it.")]],
    ["a text-free assistant tail", [assistant(CONTINUE), assistantWithParts([])]],
    ["a text-free tool tail", [assistant(WAIT), { role: "toolResult", content: [] }]],
  ];
  for (const [label, tail] of cases) {
    const pi = armed();
    const capture = captureStdout();
    try {
      // An absent FINAL declaration means "unknown", never "fall back to an
      // older declaration": a stale WAIT would wrongly stay silent and a stale
      // CONTINUE would restart work the model did not ask for.
      assert.equal(await proposes(pi, tail), undefined, label);
      assert.deepEqual(capture.chunks, [OSC_NOTIFY], `${label} notifies`);
    } finally {
      capture.restore();
    }
  }
});

// ---------------------------------------------------------------------------
// Decision repair, observed-run ledger, and the verified user-escalation gate
//
// Oracle Option D. A `STATUS:BLOCKED user oracle=<run-id> dependency=<id>` is a
// user escalation ONLY when the extension witnessed the referenced async run
// start as Oracle in this parent session during the current request epoch, that
// run COMPLETED SUCCESSFULLY, and its actual final result carries a versioned
// `USER_INPUT_REQUIRED` assessment with a matching dependency id and a matching
// `USER_QUESTION:` line. Everything else repairs or notifies; nothing here
// grants authorization.
// ---------------------------------------------------------------------------

const OSC_UNVERIFIED_ESCALATION =
  "\x1b]777;notify;Pi;Unverified user escalation - no confirmed user dependency\x07";

/** A session file path whose trailing UUID matches `uuid`. */
const sessionFileFor = (uuid) => `/sessions/tui/2026-10-07T22-18-46-115Z_${uuid}.jsonl`;
const PARENT_UUID = "bbbbbbbb-1111-2222-3333-444444444444";
const PARENT_SESSION = sessionFileFor(PARENT_UUID);
const OTHER_UUID = "cccccccc-9999-8888-7777-666666666666";
const OTHER_SESSION = sessionFileFor(OTHER_UUID);

/**
 * A fake filesystem: an async dir laid out the way a real run writes it
 * (`status.json` + `outputFile`), with the run's final structured result.
 *
 * The result always ends in the same fenced json block a real Oracle result
 * would carry; callers override `statusOver`/`result` to model each failure.
 */
function makeAsyncDir({
  dir,
  state = "complete",
  result,
  outputName = "output-0.log",
  exitCode = state === "complete" ? 0 : 1,
} = {}) {
  const outputFile = `${dir}/${outputName}`;
  const status = {
    runId: dir,
    state,
    outputFile,
    sessionFile: PARENT_SESSION,
    sessionId: PARENT_SESSION,
    processTerminal: { instances: [{ exitCode }] },
    outputs: {},
  };
  const files = new Map([
    [`${dir}/status.json`, JSON.stringify(status)],
    [outputFile, result ?? ""],
  ]);
  return {
    dir,
    outputFile,
    status,
    files,
    readFile(path) {
      return files.has(path) ? files.get(path) : null;
    },
  };
}

/**
 * A structured Oracle result carrying exactly one assessment record.
 *
 * The result carries NO `USER_QUESTION:` line: the protocol requires the PARENT
 * to repeat the question in its own final message (see `parentBlockedMessage`),
 * while Oracle's artifact carries only the assessment. The `question` here is
 * the assessment's own `question` field, which the parent's line must match.
 */
function oracleResult({ dependencyId = "dep-1", question = "Which of the three options?", outcome = "USER_INPUT_REQUIRED", version = 1, extraAssessments = [], kind = "product-intent" } = {}) {
  const blocks = [
    `\`\`\`oracle-input-assessment\n${JSON.stringify({ version, dependencyId, outcome, kind, question })}\n\`\`\``,
    ...extraAssessments.map((record) => `\`\`\`oracle-input-assessment\n${JSON.stringify(record)}\n\`\`\``),
  ].join("\n\n");
  return `${blocks}\n`;
}

/**
 * Armed pi + observing bus + reader, with the observed-run ledger seeded.
 *
 * `runs` is a list of `{ runId, agent, asyncDir }`; the harness feeds a START
 * event for each (through the same subscription a host would use) and installs
 * the async-dir filesystem in the injected reader.
 */
function armedObserved({
  uuid = PARENT_UUID,
  sessionFile = sessionFileFor(uuid),
  runs = [],
  reply = () => undefined,
  rpc = () => null,
  budget = undefined,
} = {}) {
  const bus = makeBus(reply, rpc);
  const dirs = runs.map((run) => run.asyncDir).filter((dir) => dir !== undefined && dir !== null);
  const filesystem = new Map();
  for (const dir of dirs) {
    for (const [path, content] of dir.files) filesystem.set(path, content);
  }
  const pi = makePi();
  pi.events = bus;
  mod.registerSessionSupervisor(pi, {
    PI_MAX_CONTINUATIONS: budget === undefined ? undefined : String(budget),
    readFile: (path) => (filesystem.has(path) ? filesystem.get(path) : null),
    // A synchronous scheduler keeps a driven WAIT from arming REAL timers, so a
    // test that settles a WAIT does not leave a live 60s recheck behind.
    schedule: () => null,
    cancel: () => {},
  });
  const ctx = { ...UI, isIdle: () => true, sessionFile, sessionId: uuid };
  pi.emit("input", { type: "input", text: "go", source: "interactive" }, ctx);
  pi.emit("before_agent_start", { type: "before_agent_start", prompt: "go" }, ctx);
  pi.emit("message_start", { type: "message_start", message: { role: "user", content: "go" } }, ctx);
  // Observe each run start exactly as a host would deliver it.
  for (const run of runs) {
    bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
      type: "subagent:async-started",
      version: 1,
      runId: run.runId,
      id: run.runId,
      asyncDir: run.asyncDir?.dir,
      agent: run.agent,
      sessionFile: run.sessionFile ?? PARENT_SESSION,
      sessionId: run.sessionId ?? PARENT_SESSION,
    });
  }
  return { pi, bus, ctx, filesystem };
}

/**
 * A `STATUS:BLOCKED user` parent message.
 *
 * The PARENT's final message carries the unique eligible `USER_QUESTION:` line -
 * exactly as the protocol requires - and the BLOCKED marker line. `questionLines`
 * overrides the line set (to model zero, one, or two lines); `extra` appends
 * prose after the dependency id.
 */
const parentBlockedMessage = (
  runId,
  depId,
  { questionLines = ["Which of the three options?"], question = null, extra = "" } = {},
) => {
  const lines = questionLines ?? (question === null ? ["Which of the three options?"] : [question]);
  const questionBlock = lines.length === 0 ? "" : lines.map((line) => `USER_QUESTION: ${line}`).join("\n") + "\n\n";
  return `I need a user decision.\n\n${questionBlock}STATUS:BLOCKED user oracle=${runId} dependency=${depId}${extra ? " " + extra : ""}`;
};

const BLOCKED_USER = (runId, depId, extra = "") =>
  parentBlockedMessage(runId, depId, { extra });

const boundaryCtx = (uuid, sessionFile, messages) => ({
  ...UI,
  sessionFile,
  sessionId: uuid,
  sessionManager: sessionView(messages),
});

// --- 1. Valid user escalations: question accepted, no continuation, one notice --

test("a verified user escalation notifies once and never continues", async () => {
  const dir = makeAsyncDir({ dir: "/async/oracle-1", result: oracleResult({ dependencyId: "dep-1" }) });
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-1", agent: "oracle", asyncDir: dir }] });
  const capture = captureStdout();
  try {
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-1", "dep-1"))]),
      ctx,
    );
    assert.equal(result, undefined, "a verified escalation grants no continuation");
    assert.deepEqual(capture.chunks, [OSC_NOTIFY]);
    // The settle repeats it; dedupe keeps it to one notice per epoch.
    pi.emit("agent_settled", settleEvent(), ctx);
    assert.deepEqual(capture.chunks, [OSC_NOTIFY], "one notice per epoch");
  } finally {
    capture.restore();
  }
});

// --- 2. An agent-decision Oracle result cannot authorize a user question ------ -

test("an Oracle result that recommends an agent decision cannot authorize a user question", async () => {
  // Use the bare ```json compatibility path, which has no type tag to fall back
  // on, so the outcome check itself is what must reject this record.
  const agentDecision = `\`\`\`json\n${JSON.stringify({
    version: 1,
    dependencyId: "dep-1",
    outcome: "AGENT_DECISION",
    selectedOption: "option-b",
    rationale: "reversible",
  })}\n\`\`\`\nUSER_QUESTION: Which option?\n`;
  const dir = makeAsyncDir({ dir: "/async/oracle-2", result: agentDecision });
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-2", agent: "oracle", asyncDir: dir }] });
  const capture = captureStdout();
  try {
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-2", "dep-1"))]),
      ctx,
    );
    assert.equal(result?.continue, true, "an unverified escalation is repaired");
    assert.equal(result.entries.at(-1).customType, mod.REPAIR_CUSTOM_TYPE);
    assert.deepEqual(capture.chunks, [], "a successful repair does not notify");
  } finally {
    capture.restore();
  }
});

// --- 3. Wrong provenance: fabricated id, wrong session, previous epoch --------

test("a fabricated run id cannot authorize a question", async () => {
  const dir = makeAsyncDir({ dir: "/async/oracle-3", result: oracleResult({ dependencyId: "dep-1" }) });
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-3", agent: "oracle", asyncDir: dir }] });
  const capture = captureStdout();
  try {
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("does-not-exist", "dep-1"))]),
      ctx,
    );
    assert.equal(result?.continue, true, "an unknown id repairs");
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("a run observed under a different parent session cannot authorize a question", async () => {
  const dir = makeAsyncDir({ dir: "/async/oracle-4", result: oracleResult({ dependencyId: "dep-1" }) });
  const { pi, ctx } = armedObserved({
    runs: [
      { runId: "oracle-4", agent: "oracle", asyncDir: dir, sessionFile: OTHER_SESSION, sessionId: OTHER_SESSION },
    ],
  });
  const capture = captureStdout();
  try {
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-4", "dep-1"))]),
      ctx,
    );
    assert.equal(result?.continue, true, "a run from another parent repairs");
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("a run from a previous request epoch cannot authorize a question", async () => {
  // The extension can only attribute an observation to the request epoch that
  // was active when it observed the START. A new request clears the ledger, so
  // the same run id observed earlier is no longer present.
  const dir = makeAsyncDir({ dir: "/async/oracle-5", result: oracleResult({ dependencyId: "dep-1" }) });
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-5", agent: "oracle", asyncDir: dir }] });
  const capture = captureStdout();
  try {
    // A genuine NEW request: input + delivered message (the boundary event is
    // not enough to open a request epoch, so the harness drives the handshake).
    pi.emit("input", { type: "input", text: "next", source: "interactive" }, ctx);
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "next" }, ctx);
    pi.emit("message_start", { type: "message_start", message: { role: "user", content: "next" } }, ctx);
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-5", "dep-1"))]),
      ctx,
    );
    assert.equal(result?.continue, true, "the cleared ledger cannot authorize");
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("a marker-supplied result path is never read: only the observed async dir is", async () => {
  // The marker carries no path at all in the supported grammar; even if a model
  // smuggles a path into the description, the verifier reads ONLY the observed
  // async dir. A fabricated file elsewhere must not be consulted.
  const dir = makeAsyncDir({ dir: "/async/oracle-6", result: "no assessment here\n" });
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-6", agent: "oracle", asyncDir: dir }] });
  const capture = captureStdout();
  try {
    const forged = "/tmp/forged-output.log with a perfect assessment";
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-6", "dep-1", forged))]),
      ctx,
    );
    assert.equal(result?.continue, true, "a marker path cannot substitute for observation");
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

// --- 4. Wrong completion ------------------------------------------------------ -

test("started, stopping, stopped alone, failed, cancelled, and missing results all fail", async () => {
  // Each referenced run is in the observed-run ledger but its evidence is not
  // `state === "complete"`, so no USER question may be authorized. Under S2 the
  // ledger row alone is NOT current-owner proof, so unless the live bridge
  // confirms the run active these BLOCKEDs proceed on the ordinary repair path
  // (`continue === true`) rather than being absorbed as a wake owner. The
  // property under test is unchanged: the escalation never authorizes a
  // question.
  const cases = [
    ["state=started", { state: "started" }],
    ["state=stopping", { state: "stopping" }],
    ["state=stopped (no success)", { state: "stopped" }],
    ["state=failed", { state: "failed" }],
    ["state=cancelled", { state: "cancelled" }],
  ];
  for (const [label, over] of cases) {
    const dir = makeAsyncDir({
      dir: `/async/oracle-${label}`,
      state: over.state,
      result: oracleResult({ dependencyId: "dep-1" }),
    });
    const { pi, ctx } = armedObserved({
      runs: [{ runId: "oracle-x", agent: "oracle", asyncDir: dir }],
    });
    const capture = captureStdout();
    try {
      const result = await handlerFor(pi, "agent_before_settle")(
        boundaryEvent([assistant(BLOCKED_USER("oracle-x", "dep-1"))]),
        ctx,
      );
      assert.equal(result?.continue, true, `${label} is repaired, never a user question`);
      assert.deepEqual(capture.chunks, [], `${label} grants no user escalation notice`);
    } finally {
      capture.restore();
    }
  }

  // A COMPLETED run whose output file is missing entirely is NOT a pending wake
  // owner, so this stays on the ordinary repair path: unverified, and repaired.
  const missing = makeAsyncDir({ dir: "/async/oracle-missing", result: "" });
  missing.files.delete(missing.outputFile);
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-m", agent: "oracle", asyncDir: missing }] });
  const capture = captureStdout();
  try {
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-m", "dep-1"))]),
      ctx,
    );
    assert.equal(result?.continue, true, "a missing result cannot authorize and is repaired");
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("F4 coverage: an incomplete TERMINAL run with no pending wake owner is rejected for incompleteness", async () => {
  // The block above asserts only `continue !== true` + notify, which would ALSO
  // pass if the verifier's completeness check were removed - because the run is
  // a PENDING wake owner under F4 and is suppressed by wake-owner ownership.
  // This test removes that confound: each run is marked TERMINAL (so it is NOT a
  // wake owner) and is therefore forced onto the ordinary evidence path, where
  // INCOMPLETENESS must reject the escalation specifically. The `stopped` run
  // with exit code ZERO pins that completion is `state === "complete"`, never a
  // zero process exit code: it is terminal-yet-incomplete, so it must be
  // rejected. Every case yields the repair bridge (`continue === true`), proving
  // the rejection is the evidence gate and not a wake-owner suppression.
  const cases = [
    ["state=started", { state: "started" }],
    ["state=stopping", { state: "stopping" }],
    ["state=stopped with exit code zero", { state: "stopped", exitCode: 0 }],
    ["state=stopped with nonzero exit code", { state: "stopped", exitCode: 1 }],
    ["state=failed", { state: "failed" }],
    ["state=cancelled", { state: "cancelled" }],
  ];
  for (const [label, over] of cases) {
    const dir = makeAsyncDir({
      dir: `/async/oracle-term-${label.length}-${over.state}`,
      state: over.state,
      exitCode: over.exitCode,
      result: oracleResult({ dependencyId: "dep-1" }),
    });
    const { pi, bus, ctx } = armedObserved({
      runs: [{ runId: "oracle-term", agent: "oracle", asyncDir: dir }],
    });
    // Retire the run from the wake-owner set: a terminal observation means this
    // child will not wake the parent, so the suppression confound is gone.
    bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
      type: "subagent.child-status",
      version: 1,
      runId: "oracle-term",
      childId: "oracle-term",
      status: "stopped",
      source: "async",
    });
    const capture = captureStdout();
    try {
      const result = await handlerFor(pi, "agent_before_settle")(
        boundaryEvent([assistant(BLOCKED_USER("oracle-term", "dep-1"))]),
        ctx,
      );
      assert.equal(
        result?.continue,
        true,
        `${label}: an incomplete terminal run must be repaired for incompleteness`,
      );
      assert.deepEqual(capture.chunks, [], `${label}: no notification, it is repaired`);
    } finally {
      capture.restore();
    }
  }
});

// --- 5. Wrong assessment: review output, absent, duplicate, wrong dep, mismatch -

test("an Oracle Review result, an absent record, duplicates, a wrong dependency, and a mismatched question all fail", async () => {
  const cases = [
    ["a Review-shaped result with no assessment", "## Verdict: PASS\n\nNo blockers found.\n", BLOCKED_USER("oracle-a", "dep-1")],
    ["two assessment records", oracleResult({ dependencyId: "dep-1", extraAssessments: [{ version: 1, dependencyId: "dep-1", outcome: "USER_INPUT_REQUIRED", kind: "fact", question: "Which of the three options?" }] }), BLOCKED_USER("oracle-a", "dep-1")],
    ["a different dependency id", oracleResult({ dependencyId: "dep-other" }), BLOCKED_USER("oracle-a", "dep-1")],
    ["a mismatched question line", oracleResult({ dependencyId: "dep-1" }), parentBlockedMessage("oracle-a", "dep-1", { questionLines: ["A totally different question?"] })],
    ["zero question lines", oracleResult({ dependencyId: "dep-1" }), parentBlockedMessage("oracle-a", "dep-1", { questionLines: [] })],
    ["two question lines", oracleResult({ dependencyId: "dep-1" }), parentBlockedMessage("oracle-a", "dep-1", { questionLines: ["Which of the three options?", "Or this one?"] })],
    ["a wrong record version", oracleResult({ dependencyId: "dep-1", version: 2 }), BLOCKED_USER("oracle-a", "dep-1")],
  ];
  for (const [label, result, parent] of cases) {
    const dir = makeAsyncDir({ dir: `/async/oracle-a-${label.length}`, result });
    const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-a", agent: "oracle", asyncDir: dir }] });
    const capture = captureStdout();
    try {
      const outcome = await handlerFor(pi, "agent_before_settle")(
        boundaryEvent([assistant(parent)]),
        ctx,
      );
      assert.equal(outcome?.continue, true, `${label} must repair, not authorize`);
      assert.deepEqual(capture.chunks, [], label);
    } finally {
      capture.restore();
    }
  }
});

// --- 5b. F1: the question is read from the PARENT's final message ------------ -

test("the USER_QUESTION line is read from the parent message, not the Oracle artifact", async () => {
  // The Oracle result carries the assessment only, with NO question line. The
  // parent's final message repeats the question, exactly as the protocol
  // requires, so the escalation verifies.
  const dir = makeAsyncDir({ dir: "/async/oracle-parent-q", result: oracleResult({ dependencyId: "dep-1" }) });
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-parent-q", agent: "oracle", asyncDir: dir }] });
  const capture = captureStdout();
  try {
    const outcome = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(parentBlockedMessage("oracle-parent-q", "dep-1"))]),
      ctx,
    );
    assert.equal(outcome, undefined, "the verified escalation grants no continuation");
    assert.deepEqual(capture.chunks, [OSC_NOTIFY], "a verified escalation notifies");
  } finally {
    capture.restore();
  }
});

test("optionally fenced parent question lines are ignored, and missing/two parent questions are unverified", async () => {
  const cases = [
    [
      // A fenced EXAMPLE does not count; the one real line makes it unique.
      "a fenced example alongside the real line still verifies",
      ["A heading.", "", "```text", "USER_QUESTION: a fenced example?", "```", "", "USER_QUESTION: Which of the three options?", "", "STATUS:BLOCKED user oracle=oracle-fq dependency=dep-1"].join("\n"),
      false,
    ],
    [
      // No question line at all cannot verify.
      "a missing parent question is unverified",
      "I need a user decision.\n\nSTATUS:BLOCKED user oracle=oracle-fq dependency=dep-1",
      true,
    ],
    [
      // Two eligible question lines are ambiguous.
      "two parent question lines are unverified",
      parentBlockedMessage("oracle-fq", "dep-1", { questionLines: ["Which of the three options?", "Or this one?"] }),
      true,
    ],
  ];
  for (const [label, text, expectRepair] of cases) {
    const dir = makeAsyncDir({ dir: "/async/oracle-fq", result: oracleResult({ dependencyId: "dep-1" }) });
    const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-fq", agent: "oracle", asyncDir: dir }] });
    const capture = captureStdout();
    try {
      const outcome = await handlerFor(pi, "agent_before_settle")(
        boundaryEvent([assistant(text)]),
        ctx,
      );
      if (expectRepair) {
        assert.equal(outcome?.continue, true, `${label}: repaired`);
        assert.deepEqual(capture.chunks, [], label);
      } else {
        assert.equal(outcome, undefined, `${label}: verified, no continuation`);
        assert.deepEqual(capture.chunks, [OSC_NOTIFY], label);
      }
    } finally {
      capture.restore();
    }
  }
});

// --- 6. Ungated BLOCKED: one repair bridge, no immediate notification --------- -

test("an ungated BLOCKED yields one repair bridge and no notification", async () => {
  const pi = armed();
  const capture = captureStdout();
  try {
    const result = await proposes(pi, [assistant(BLOCKED)]);
    assert.equal(result?.continue, true);
    assert.equal(result.entries.length, 1);
    assert.equal(result.entries[0].customType, mod.REPAIR_CUSTOM_TYPE);
    assert.deepEqual(capture.chunks, [], "a successful proposal stays silent");
    assert.match(result.entries[0].content, /Do not wait for a technical option selection/);
    assert.match(result.entries[0].content, /Missing assessment evidence grants no authorization/);
  } finally {
    capture.restore();
  }
});

// --- 7. THE reported regression ------------------------------------------------

test("a CONTINUE whose payload leads with a human-wait clause receives decision repair, never 'Act on that step now.'", async () => {
  const pi = armed();
  const capture = captureStdout();
  try {
    const result = await proposes(pi, [assistant("Waiting on you.\n\nSTATUS:CONTINUE awaiting your pick among the three fix options")]);
    assert.equal(result?.continue, true, "the human-wait CONTINUE is repaired, not executed");
    const bridge = result.entries.at(-1);
    assert.equal(bridge.customType, mod.REPAIR_CUSTOM_TYPE);
    assert.ok(!bridge.content.includes("Act on that step now."), "never re-issues the wait as an action");
    assert.match(bridge.content, /Do not wait for a technical option selection/);
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("the reported regression end-to-end through the default factory", async () => {
  // The exact reported case, driven through the REAL default factory (not the
  // module helper): a human-waiting CONTINUE must be repaired, and its bridge
  // must not carry the ordinary "Act on that step now." line.
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    const ctx = { ...UI, isIdle: () => true };
    pi.emit("input", { type: "input", text: "go", source: "interactive" }, ctx);
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "go" }, ctx);
    pi.emit("message_start", { type: "message_start", message: { role: "user", content: "go" } }, ctx);
    const results = pi.emit(
      "agent_before_settle",
      boundaryEvent([assistant("STATUS:CONTINUE awaiting your pick among the three fix options")]),
      ctx,
    );
    const result = results[0];
    assert.equal(result?.continue, true);
    assert.equal(result.entries.at(-1).customType, mod.REPAIR_CUSTOM_TYPE);
    assert.ok(!result.entries.at(-1).content.includes("Act on that step now."));
    assert.deepEqual(out.chunks, []);
  } finally {
    restore();
  }
});

test("the leading human-wait clause is narrow: only the three exact phrases", () => {
  const cases = [
    ["awaiting your pick among the three fix options", true],
    ["waiting for your answer before I proceed", true],
    ["waiting on the user to choose", true],
    ["implement the WAIT branch", false],
    ["await the fixture and then launch the child", false],
    ["agent_before_settle", false],
    ["please proceed with the default", false],
  ];
  for (const [payload, expected] of cases) {
    assert.equal(mod.humanWaitingLeadingClause(payload), expected, payload);
  }
});

// --- 8. Harmless waiting terminology still gets ordinary handling -------------- -

test("harmless waiting terminology still proposes an ordinary continuation", async () => {
  const pi = armedWithBudget(4);
  const capture = captureStdout();
  try {
    for (const payload of [
      "STATUS:CONTINUE implement the WAIT branch",
      "STATUS:CONTINUE await the fixture and then launch the child",
      "STATUS:CONTINUE wait for the build, then run the tests",
    ]) {
      const result = await proposes(pi, [assistant(payload)]);
      assert.equal(result?.continue, true, payload);
      assert.equal(result.entries.at(-1).customType, mod.BRIDGE_CUSTOM_TYPE, "the ORDINARY bridge, not repair");
    }
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

// --- 9. Real wake ownership is preserved ---------------------------------------

test("a repair still supplies a runnable bridge when another handler asked to continue", async () => {
  // S1 contract change: `boundary.continue === true` is no longer a reason to
  // bail out. Pi computes `canContinue` from the committed context, so this
  // handler must append its repair bridge even when another handler already set
  // the flag. The old expectation (`undefined` + notify) encoded the withdrawn
  // allowance rule.
  const pi = armed();
  const capture = captureStdout();
  try {
    const result = await proposes(pi, [assistant(BLOCKED)], { continue: true });
    assert.equal(result?.continue, true, "the repair proposes");
    assert.equal(result.entries.at(-1).customType, mod.REPAIR_CUSTOM_TYPE, "a repair bridge is appended");
    assert.deepEqual(capture.chunks, [], "an owned continuation is not a stop");
  } finally {
    capture.restore();
  }
});

test("a verified pending Oracle wake owner is unaffected by repair of another BLOCKED", async () => {
  // A pending verified WAIT (current-owner attested via RPC) keeps its silence;
  // a separate repair decision elsewhere must not disturb it.
  const { pi, flushMs } = armedRpcWait({ runId: "3c1", state: "running" });
  const capture = captureStdout();
  try {
    pi.emit("agent_settled", settleEvent(), sessionCtx([assistant(WAIT)]));
    flushMs(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "the verified wake owner stays silent");
  } finally {
    capture.restore();
  }
});

test("a BLOCKED naming a still-running Oracle keeps its wake owner once the bridge confirms it", async () => {
  // Under S2, ownership requires the live bridge to confirm the run active. When
  // it does, the child owns the automatic wake and a premature BLOCKED must NOT
  // spawn a second continuation - the same rule as before, now on current-owner
  // evidence rather than mere ledger membership.
  const dir = makeAsyncDir({ dir: "/async/pending", state: "running", result: oracleResult({ dependencyId: "dep-1" }) });
  const { pi, ctx } = armedObserved({
    runs: [{ runId: "oracle-p", agent: "oracle", asyncDir: dir }],
    rpc: () => rpcTargetedReply("oracle-p", "running"),
  });
  const capture = captureStdout();
  try {
    // The registered run must be confirmed active by the bridge BEFORE the
    // boundary reads the wake-owner predicate, so drive one WAIT settle that
    // NAMES this run first. The settle uses the harness ctx so provenance and
    // the WAIT share an identity.
    const waitMarker = assistant("I dispatched the child run.\n\nSTATUS:WAIT subagent oracle-p complete");
    pi.emit("agent_settled", settleEvent(), { ...ctx, sessionManager: sessionView([waitMarker]) });
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-p", "dep-1"))]),
      ctx,
    );
    assert.notEqual(result?.continue, true, "a confirmed wake owner suppresses the repair continuation");
  } finally {
    capture.restore();
  }
});

test("ledger membership alone no longer suppresses a repair continuation", async () => {
  // The S2 semantic change: a run witnessed START but NOT confirmed current by
  // the bridge is not a wake owner, so a premature BLOCKED proceeds on the
  // ordinary repair path rather than being silently absorbed.
  const dir = makeAsyncDir({ dir: "/async/pending", state: "running", result: oracleResult({ dependencyId: "dep-1" }) });
  const { pi, ctx } = armedObserved({
    runs: [{ runId: "oracle-q", agent: "oracle", asyncDir: dir }],
    rpc: () => null,
  });
  const result = await handlerFor(pi, "agent_before_settle")(
    boundaryEvent([assistant(BLOCKED_USER("oracle-q", "dep-1"))]),
    ctx,
  );
  assert.equal(result?.continue, true, "without current-owner proof the repair proceeds");
});

// --- 10. Budget and boundary limits still bound repair ------------------------ -

test("repair is never bounded by a continuation allowance", async () => {
  // S1 contract change: repair and ordinary continuation share ONE proposal path
  // with no shared finite ledger, so a configured finite value cannot cap repair.
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(BLOCKED)]))?.continue, true);
    // A second ungated BLOCKED still proposes: there is no allowance to spend.
    const second = await proposes(pi, [assistant(BLOCKED)]);
    assert.equal(second?.continue, true, "repair is not bounded by a counter");
    assert.equal(second.entries.at(-1).customType, mod.REPAIR_CUSTOM_TYPE);
    assert.deepEqual(capture.chunks, [], "no resource-limited stop exists");
  } finally {
    capture.restore();
  }
});

test("disabled, error, aborted, and entry-less boundaries cannot repair", async () => {
  // Operator disable: repair cannot act and the fallback is generic attention.
  {
    const pi = armedWithBudget(0);
    const capture = captureStdout();
    try {
      assert.equal(await proposes(pi, [assistant(BLOCKED)]), undefined);
      assert.deepEqual(capture.chunks, [OSC_NOTIFY], "a disabled continuation cannot repair");
    } finally {
      capture.restore();
    }
  }
  // A fresh session DOES repair: the handshake is not in the decision order, so
  // an unarmed session is not a stop for an ungated BLOCKED.
  {
    const pi = makePi();
    mod.registerSessionSupervisor(pi, {});
    const capture = captureStdout();
    try {
      assert.equal((await proposes(pi, [assistant(BLOCKED)]))?.continue, true);
      assert.deepEqual(capture.chunks, []);
    } finally {
      capture.restore();
    }
  }
  // An ERROR boundary prohibits continuation for its own reason.
  {
    const pi = armed();
    const capture = captureStdout();
    try {
      const result = await handlerFor(pi, "agent_before_settle")(
        boundaryEvent([assistant(BLOCKED)], { outcome: "error" }),
        UI,
      );
      assert.equal(result, undefined, "an error boundary cannot repair");
      assert.deepEqual(capture.chunks, [OSC_NOTIFY]);
    } finally {
      capture.restore();
    }
  }
  // An ABORTED boundary likewise.
  {
    const pi = armed();
    const capture = captureStdout();
    try {
      const result = await handlerFor(pi, "agent_before_settle")(
        boundaryEvent([assistant(BLOCKED)], { outcome: "aborted" }),
        UI,
      );
      assert.equal(result, undefined, "an aborted boundary cannot repair");
      assert.deepEqual(capture.chunks, [OSC_NOTIFY]);
    } finally {
      capture.restore();
    }
  }
  // No entries array: the repair bridge cannot be carried, so it notifies.
  {
    const pi = armed();
    const capture = captureStdout();
    try {
      const result = await handlerFor(pi, "agent_before_settle")(
        boundaryEvent([assistant(BLOCKED)], { entries: undefined }),
        UI,
      );
      assert.equal(result, undefined, "no entries means no bridge");
      assert.deepEqual(capture.chunks, [OSC_NOTIFY]);
    } finally {
      capture.restore();
    }
  }
});

// --- 11. Notification dedup and epoch ---------------------------------------- -

test("a rejected escalation plus settlement emits exactly one notice, and new input opens a new epoch", async () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    const uuid = PARENT_UUID;
    const sessionFile = sessionFileFor(uuid);
    const ctx = { ...UI, sessionFile, sessionId: uuid, sessionManager: sessionView([assistant(BLOCKED_USER("nope", "dep-1"))]) };
    pi.emit("agent_before_settle", boundaryEvent([assistant(BLOCKED_USER("nope", "dep-1"))]), ctx);
    pi.emit("agent_settled", settleEvent(), ctx);
    assert.equal(out.chunks.length, 1, "one notice for the rejected escalation + settlement");

    pi.emit("input", {}, UI);
    pi.emit("agent_settled", settleEvent(), { ...UI, sessionManager: sessionView([assistant("nothing")]) });
    assert.equal(out.chunks.length, 2, "a new epoch notifies again");
  } finally {
    restore();
  }
});

// --- 12. Safety UI prompts keep notifying independently ----------------------- -

test("a safety UI prompt notifies without any marker or assessment", async () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    // No observation, no bus, no marker: the host opened a blocking prompt.
    pi.emit("ui_prompt_start", {}, UI);
    assert.deepEqual(out.chunks, [OSC_NOTIFY]);
  } finally {
    restore();
  }
});

test("the unverified-escalation notice is a distinct transport from attention", async () => {
  // The notice must NOT imply the user owes an option selection, so it uses its
  // own OSC payload rather than the generic attention one.
  assert.equal(mod.OSC_NOTIFY_UNVERIFIED_ESCALATION, OSC_UNVERIFIED_ESCALATION);
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    const uuid = PARENT_UUID;
    const ctx = { ...UI, sessionFile: sessionFileFor(uuid), sessionId: uuid, sessionManager: sessionView([assistant(BLOCKED_USER("nope", "dep-1"))]) };
    pi.emit("agent_settled", settleEvent(), ctx);
    assert.deepEqual(out.chunks, [OSC_UNVERIFIED_ESCALATION]);
  } finally {
    restore();
  }
});

// --- Supplementary: parser-level coverage for the structured grammar --------- -

test("parseBlockedDeclaration recognizes the two structured forms and rejects botched ones", () => {
  assert.deepEqual(mod.parseBlockedDeclaration("user oracle=run-1 dependency=dep-1 needs a grant"), {
    form: "user",
    oracleRunId: "run-1",
    dependencyId: "dep-1",
    description: "user oracle=run-1 dependency=dep-1 needs a grant",
  });
  assert.deepEqual(mod.parseBlockedDeclaration("external owner=ci-runner host down"), {
    form: "external",
    owner: "ci-runner",
    description: "external owner=ci-runner host down",
  });
  // Key order is irrelevant; a missing value is invalid.
  assert.equal(mod.parseBlockedDeclaration("user dependency=dep-1 oracle=run-1 x").form, "user");
  assert.equal(mod.parseBlockedDeclaration("user oracle= dependency=dep-1").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("user oracle=run-1").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("external owner=").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("repository write access").form, "unstructured");
  assert.equal(mod.parseBlockedDeclaration("").form, "unstructured");
});

test("parseBlockedDeclaration requires the explicit form discriminator, not bare key presence", () => {
  // F5: a leading `user` with only an `owner=` key is a botched USER form and is
  // INVALID - it must NOT be silently reclassified as an external dependency,
  // which would bypass the user-proof gate entirely.
  assert.equal(mod.parseBlockedDeclaration("user owner=ci-runner awaiting authorization").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("user something").form, "invalid");

  // A leading `user` requires BOTH proof fields, exactly once each.
  assert.equal(mod.parseBlockedDeclaration("user oracle=run-1 dependency=dep-1").form, "user");
  assert.equal(mod.parseBlockedDeclaration("user oracle=run-1").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("user dependency=dep-1").form, "invalid");
  // Duplicate or conflicting proof fields are invalid.
  assert.equal(mod.parseBlockedDeclaration("user oracle=run-1 oracle=run-2 dependency=dep-1").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("user oracle=run-1 dependency=dep-1 dependency=dep-2").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("user oracle=run-1 dependency=dep-1 owner=someone").form, "invalid");

  // A leading `external` requires `owner=`, exactly once, and rejects user keys.
  assert.equal(mod.parseBlockedDeclaration("external owner=ci-runner host down").form, "external");
  assert.equal(mod.parseBlockedDeclaration("external oracle=run-1").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("external dependency=dep-1").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("external owner=a owner=b").form, "invalid");
  assert.equal(mod.parseBlockedDeclaration("external owner=a oracle=run-1").form, "invalid");

  // Genuinely unstructured prose stays unstructured (no form word, no proof key).
  assert.equal(mod.parseBlockedDeclaration("the database is unreachable").form, "unstructured");
  // A stray proof key without a form word remains a botched structured form.
  assert.equal(mod.parseBlockedDeclaration("oracle=run-1 justification").form, "invalid");
});

test("F5: no form discriminator + any proof key is invalid, never an accepted blocker", () => {
  // The exact bypass: a BARE `owner=` with no leading `external` discriminator
  // must NOT be classified as an accepted `external` blocker (that would skip
  // the user-proof gate). It is a botched structured declaration.
  assert.equal(mod.parseBlockedDeclaration("owner=ci-runner awaiting authorization").form, "invalid");
  assert.notEqual(mod.parseBlockedDeclaration("owner=ci-runner awaiting authorization").form, "external");

  // A complete bare `oracle=`/`dependency=` pair with no `user` discriminator is
  // likewise a botched USER form, NOT an accepted `user` escalation.
  assert.equal(mod.parseBlockedDeclaration("oracle=r1 dependency=d1 done").form, "invalid");
  assert.notEqual(mod.parseBlockedDeclaration("oracle=r1 dependency=d1 done").form, "user");

  // A lone bare `oracle=` key is botched too.
  assert.equal(mod.parseBlockedDeclaration("oracle=r1").form, "invalid");

  // A duplicate bare `owner=` is botched.
  assert.equal(mod.parseBlockedDeclaration("owner=a owner=b").form, "invalid");
});

test("F5: well-formed forms and key-less prose keep their forms", () => {
  // The explicit discriminators are unchanged and still accepted.
  assert.equal(mod.parseBlockedDeclaration("user oracle=r1 dependency=d1 desc").form, "user");
  assert.equal(mod.parseBlockedDeclaration("external owner=ci-runner desc").form, "external");
  // Prose with no proof key at all stays unstructured.
  assert.equal(mod.parseBlockedDeclaration("please run the migration for me").form, "unstructured");
});

test("F5: an invalid declaration never authorizes a question, only repair", async () => {
  // The INVARIANT: an `invalid` (or `unstructured`) BLOCKED routes to the
  // decision-repair/unverified path and never to an accepted user escalation.
  // A bare `owner=` must NOT be quietly accepted as an `external` blocker
  // (which would notify and end the turn without a proof gate).
  const pi = armed();
  const capture = captureStdout();
  try {
    const result = await proposes(pi, [assistant("blocked\n\nSTATUS:BLOCKED owner=ci-runner awaiting authorization")]);
    assert.equal(result?.continue, true, "a bare owner= declaration is repaired, not accepted");
    assert.equal(result.entries.at(-1).customType, mod.REPAIR_CUSTOM_TYPE);
    assert.deepEqual(capture.chunks, [], "no notification is emitted for a repaired declaration");
  } finally {
    capture.restore();
  }
});

test("parseUserInputAssessment accepts version 1 only and exactly one record", () => {
  const good = oracleResult({ dependencyId: "dep-1" });
  const parsed = mod.parseUserInputAssessment(good);
  assert.equal(parsed.dependencyId, "dep-1");
  assert.equal(parsed.outcome, "USER_INPUT_REQUIRED");
  // The version may also be the string "1".
  assert.notEqual(mod.parseUserInputAssessment(oracleResult({ version: "1" })), null);
  // A `json oracle-input-assessment` info string is an accepted equivalent.
  assert.notEqual(
    mod.parseUserInputAssessment("```json oracle-input-assessment\n{\n  \"version\": 1,\n  \"outcome\": \"USER_INPUT_REQUIRED\",\n  \"dependencyId\": \"dep-1\",\n  \"question\": \"Which?\"\n}\n```"),
    null,
  );
  // A bare ```json fence carrying the assessment shape is the compatibility path.
  assert.notEqual(
    mod.parseUserInputAssessment("```json\n{\n  \"version\": 1,\n  \"outcome\": \"USER_INPUT_REQUIRED\",\n  \"dependencyId\": \"dep-1\",\n  \"question\": \"Which?\"\n}\n```"),
    null,
  );
  // A bare ```json fence with an unrelated object is NOT an assessment.
  assert.equal(mod.parseUserInputAssessment("```json\n{\n  \"verdict\": \"PASS\"\n}\n```"), null);
  // An AGENT_DECISION record is NOT a user-input assessment on EITHER fence form.
  // The info-string form is additionally filtered by the type tag, so it must be
  // pinned separately on the bare ```json compatibility path, which has no tag to
  // rely on. Regression: a mutated outcome check once let AGENT_DECISION through
  // this path and silently relabelled it USER_INPUT_REQUIRED.
  assert.equal(
    mod.parseUserInputAssessment("```json\n{\n  \"version\": 1,\n  \"outcome\": \"AGENT_DECISION\",\n  \"dependencyId\": \"dep-1\",\n  \"selectedOption\": \"option-b\"\n}\n```"),
    null,
    "a bare-fenced AGENT_DECISION must not parse as a user-input assessment",
  );
  const decisionWithInfo = "```oracle-input-assessment\n" + JSON.stringify({
    version: 1,
    outcome: "AGENT_DECISION",
    dependencyId: "dep-1",
    selectedOption: "option-b",
  }) + "\n```";
  assert.equal(
    mod.parseUserInputAssessment(decisionWithInfo),
    null,
    "a tagged AGENT_DECISION must not parse as a user-input assessment",
  );
  // Two assessment records are ambiguous, so unusable.
  assert.equal(
    mod.parseUserInputAssessment(oracleResult({ extraAssessments: [{ version: 1, dependencyId: "dep-1", outcome: "USER_INPUT_REQUIRED", question: "Which?" }] })),
    null,
  );
});

test("parseUserInputAssessment counts tagged and bare records together", () => {
  // F2: a valid TAGGED assessment plus a competing BARE-JSON assessment is TWO
  // records and therefore ambiguous - the two formats are counted TOGETHER, not
  // selected between by a ternary.
  const tagged = "```oracle-input-assessment\n" + JSON.stringify({
    version: 1,
    outcome: "USER_INPUT_REQUIRED",
    dependencyId: "dep-1",
    question: "Which?",
  }) + "\n```";
  const bare = "```json\n" + JSON.stringify({
    version: 1,
    outcome: "USER_INPUT_REQUIRED",
    dependencyId: "dep-2",
    question: "Or this?",
  }) + "\n```";
  assert.equal(mod.parseUserInputAssessment(`${tagged}\n\n${bare}`), null, "tagged + competing bare is ambiguous");
  assert.equal(mod.parseUserInputAssessment(`${bare}\n\n${tagged}`), null, "order does not matter");
  // Two bare assessments are ambiguous.
  assert.equal(mod.parseUserInputAssessment(`${bare}\n\n${bare}`), null, "two bare records are ambiguous");
  // Exactly one bare record is still accepted (existing compatibility path).
  assert.notEqual(mod.parseUserInputAssessment(bare), null, "a single bare record is accepted");
  // An UNRELATED bare json block does not compete with a single tagged record.
  const unrelated = '```json\n{\n  "verdict": "PASS"\n}\n```';
  assert.notEqual(
    mod.parseUserInputAssessment(`${tagged}\n\n${unrelated}`),
    null,
    "unrelated json does not compete",
  );
  // A single `json oracle-input-assessment` fence must not be double-counted.
  assert.notEqual(
    mod.parseUserInputAssessment("```json oracle-input-assessment\n" + JSON.stringify({
      version: 1,
      outcome: "USER_INPUT_REQUIRED",
      dependencyId: "dep-1",
      question: "Which?",
    }) + "\n```"),
    null,
    "one physical fence is one candidate even though it matches both tags",
  );
});

test("userQuestionLines excludes fenced examples and indented code", () => {
  // F1b: a `USER_QUESTION:` line inside a fence is an EXAMPLE, not an eligible
  // line. A closed example must not count; an UNTERMINATED fence swallows
  // everything after it, exactly like the renderer.
  const fenced = [
    "Prose.",
    "",
    "```text",
    "USER_QUESTION: a fenced example?",
    "```",
    "USER_QUESTION: the real one?",
  ].join("\n");
  assert.deepEqual(mod.userQuestionLines(fenced), ["the real one?"]);

  const unterminated = ["USER_QUESTION: real?", "", "```", "USER_QUESTION: hidden?"].join("\n");
  assert.deepEqual(mod.userQuestionLines(unterminated), ["real?"]);

  // An indented line is code, not a question. A fence-decorated line is an
  // example in disguise.
  const indented = ["USER_QUESTION: real?", "    USER_QUESTION: indented?"].join("\n");
  assert.deepEqual(mod.userQuestionLines(indented), ["real?"]);
  const decorated = ["USER_QUESTION: real?", "```USER_QUESTION: wrapped?```"].join("\n");
  assert.deepEqual(mod.userQuestionLines(decorated), ["real?"]);

  // P2: a LAZY blockquote/list continuation is a quoted EXAMPLE, so its
  // question is not the parent's. A blank line closes the container and makes
  // the line top-level again.
  const lazyQuote = ["USER_QUESTION: real?", "", "> Quoted example:", "USER_QUESTION: from the example?"].join("\n");
  assert.deepEqual(mod.userQuestionLines(lazyQuote), ["real?"]);
  const lazyList = ["USER_QUESTION: real?", "", "- Example:", "USER_QUESTION: from the list?"].join("\n");
  assert.deepEqual(mod.userQuestionLines(lazyList), ["real?"]);
  const closedQuote = ["USER_QUESTION: real?", "", "> Quoted example:", "", "USER_QUESTION: after the quote?"].join("\n");
  assert.deepEqual(mod.userQuestionLines(closedQuote), ["real?", "after the quote?"]);

  // P2 (cycle 45): an ordinary line UNDER the opener is itself a lazy
  // continuation, so the container stays open and the question belongs to the
  // example. Stopping the upward search at that line admitted it wrongly.
  const lazyContinuationQuote = ["> Example:", "explanatory continuation", "USER_QUESTION: Pick one."].join("\n");
  assert.deepEqual(mod.userQuestionLines(lazyContinuationQuote), []);
  const lazyContinuationList = ["- Example:", "explanatory continuation", "USER_QUESTION: Pick one."].join("\n");
  assert.deepEqual(mod.userQuestionLines(lazyContinuationList), []);
  // A blank line still closes the container, so the question is the parent's.
  const closedByBlank = ["> Example:", "", "USER_QUESTION: Pick one."].join("\n");
  assert.deepEqual(mod.userQuestionLines(closedByBlank), ["Pick one."]);

  // Non-string input yields nothing.
  assert.deepEqual(mod.userQuestionLines(null), []);
});

test("an earlier valid assessment plus a later duplicate makes the result unusable", async () => {
  // The result may contain an earlier assessment-shaped block, but a SECOND one
  // makes the record set ambiguous, so the whole result is unusable. (A trailing
  // UNRELATED json block is not an assessment and does not compete - see the
  // parser test below.)
  const result = `${oracleResult({ dependencyId: "dep-early" })}\nLater prose.\n\n${'```oracle-input-assessment\n{\n  "version": 1,\n  "outcome": "USER_INPUT_REQUIRED",\n  "dependencyId": "dep-early",\n  "question": "Which of the three options?"\n}\n```'}\n`;
  const dir = makeAsyncDir({ dir: "/async/oracle-last", result });
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-last", agent: "oracle", asyncDir: dir }] });
  const capture = captureStdout();
  try {
    const outcome = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-last", "dep-early"))]),
      ctx,
    );
    assert.equal(outcome?.continue, true, "a duplicate assessment makes the result unusable");
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("the result is read by scanning the whole artifact, and a trailing bare json fence does not compete", async () => {
  // A real output log carries prose plus several fenced blocks; the assessment
  // is found by scanning, and an UNRELATED trailing json block (which is not an
  // assessment record) neither competes nor disqualifies it.
  const result = `prose before\n\n${oracleResult({ dependencyId: "dep-1" })}\nprose after\n\n\`\`\`json\n{\n  "verdict": "PASS"\n}\n\`\`\`\n`;
  const dir = makeAsyncDir({ dir: "/async/oracle-scan", result });
  const { pi, ctx } = armedObserved({ runs: [{ runId: "oracle-scan", agent: "oracle", asyncDir: dir }] });
  const capture = captureStdout();
  try {
    const outcome = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-scan", "dep-1"))]),
      ctx,
    );
    assert.equal(outcome, undefined, "the single assessment verifies despite unrelated prose and fences");
    assert.deepEqual(capture.chunks, [OSC_NOTIFY], "a verified escalation notifies");
  } finally {
    capture.restore();
  }
});

test("readObservedRunEvidence uses state=complete, not the process exit code", () => {
  // The pinned real shape: completion is `status.json.state === "complete"`;
  // there is NO boolean success field, and the process exit code is separate.
  const completed = makeAsyncDir({ dir: "/async/e-1", state: "complete", result: "r\n" });
  const evidence = mod.readObservedRunEvidence("/async/e-1", completed.readFile);
  assert.equal(evidence.completed, true, "state=complete is the completion fact");
  assert.equal(evidence.resultPath, completed.outputFile);

  // A NON-`complete` state is rejected regardless of its exit code: a stopped
  // run carries exit code 1 in this fixture, but the state is what decides.
  const stopped = makeAsyncDir({ dir: "/async/e-2", state: "stopped", result: "r\n" });
  assert.equal(stopped.status.processTerminal.instances[0].exitCode, 1, "a stopped run is exit 1 here");
  assert.equal(mod.readObservedRunEvidence("/async/e-2", stopped.readFile).completed, false);

  // Completion comes from `state`, NEVER the exit status: `state: complete` with
  // a NONZERO exit code still counts as complete.
  const completeNonzero = makeAsyncDir({ dir: "/async/e-nz", state: "complete", result: "r\n", exitCode: 7 });
  assert.equal(
    mod.readObservedRunEvidence("/async/e-nz", completeNonzero.readFile).completed,
    true,
    "state=complete wins over a nonzero exit code",
  );

  // A missing async dir yields the honest empty shape.
  const absent = mod.readObservedRunEvidence("/async/does-not-exist", () => null);
  assert.deepEqual(absent, { asyncDir: "/async/does-not-exist", resultPath: null, result: null, completed: false });

  // A malformed status.json is not evidence either.
  const broken = (path) => (path === "/async/e-3/status.json" ? "{not json" : null);
  assert.equal(mod.readObservedRunEvidence("/async/e-3", broken).completed, false);
});

test("an oversize or short-read result artifact yields unusable evidence (fail closed)", () => {
  // F3: a truncated prefix cannot prove whole-result uniqueness, so an oversized
  // file must FAIL CLOSED rather than expose a usable prefix.
  const dir = makeAsyncDir({ dir: "/async/oversize", state: "complete", result: oracleResult({ dependencyId: "dep-1" }) });
  const oversized = (path) =>
    path === "/async/oversize/status.json"
      ? dir.files.get(path)
      : path.endsWith("output-0.log")
        ? "prefix with one assessment"
        : null;
  const evidence = mod.readObservedRunEvidence(
    "/async/oversize",
    oversized,
    () => 2 * 1024 * 1024 + 1,
  );
  assert.equal(evidence.result, null, "an oversize artifact exposes no result");
  assert.equal(evidence.completed, true, "the completion fact is still reported");
  assert.equal(evidence.truncated, true, "oversize is a distinct diagnostic");

  // A SHORT read (fewer bytes than the file holds) is equally unusable.
  const shortDir = makeAsyncDir({ dir: "/async/short", state: "complete", result: "one assessment only" });
  const short = mod.readObservedRunEvidence(
    "/async/short",
    (path) => (path === "/async/short/status.json" ? shortDir.files.get(path) : "only part"),
    () => 4096,
  );
  assert.equal(short.result, null, "a short read exposes no result");
  assert.equal(short.truncated, true, "a short read is a truncated read");

  // A normal-size file, read whole, still verifies.
  const normal = makeAsyncDir({ dir: "/async/normal", state: "complete", result: oracleResult({ dependencyId: "dep-1" }) });
  const normalEvidence = mod.readObservedRunEvidence(
    "/async/normal",
    normal.readFile,
    () => normal.files.get(normal.outputFile).length,
  );
  assert.equal(normalEvidence.result, normal.files.get(normal.outputFile), "a whole read is usable");
  assert.equal(normalEvidence.truncated, undefined, "a whole read is not truncated");
});

test("the production reader fails closed on a real oversize artifact", () => {
  // Exercise the real `defaultReadFile` against a real file: a >2 MiB artifact
  // whose PREFIX holds a perfectly valid assessment must still be unusable, so
  // no prefix can authorize an escalation.
  const root = mkdtempSync(join(tmpdir(), "supervisor-oversize-"));
  try {
    const dir = join(root, "run");
    mkdirSync(dir);
    const outputFile = join(dir, "output-0.log");
    const status = {
      runId: dir,
      state: "complete",
      outputFile,
      sessionFile: PARENT_SESSION,
      sessionId: PARENT_SESSION,
      processTerminal: { instances: [{ exitCode: 0 }] },
      outputs: {},
    };
    writeFileSync(join(dir, "status.json"), JSON.stringify(status));
    // A valid assessment in the PREFIX, padded past the 2 MiB cap.
    const prefix = oracleResult({ dependencyId: "dep-1" });
    writeFileSync(outputFile, prefix + "\n" + "x".repeat(2 * 1024 * 1024 + 16));

    const evidence = mod.readObservedRunEvidence(dir);
    assert.equal(evidence.completed, true, "completion is still reported");
    assert.equal(evidence.result, null, "an oversize artifact exposes no usable prefix");
    assert.equal(evidence.truncated, true, "oversize is diagnosed distinctly");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("sessionUuid normalizes a session FILE PATH and a bare UUID to the same value", () => {
  // status.json.sessionId is a session file PATH; ctx.sessionId is a bare UUID.
  // Comparing the two directly would never match, so both normalize to a UUID.
  const path = "/Users/x/2026-10-07T22-18-46-115Z_01a11872-99e3-734c-a2b6-8d25818cd1e8.jsonl";
  assert.equal(mod.sessionUuid(path), "01a11872-99e3-734c-a2b6-8d25818cd1e8");
  assert.equal(mod.sessionUuid("01a11872-99e3-734c-a2b6-8d25818cd1e8"), "01a11872-99e3-734c-a2b6-8d25818cd1e8");
  assert.equal(mod.sessionUuid(""), "");
});

test("a subagent:child-status terminal transition retires an observed run for WAIT proof", () => {
  // The terminal observation is load-bearing for WAIT: once the child the marker
  // names has reported terminal, an observed-run WAIT may no longer lean on it,
  // so the notice must fire rather than assuming the wake path still holds.
  //
  // `states: () => null` makes the RPC bridge UNABLE to confirm the run, so
  // provenance is the ONLY thing that can silence this WAIT. With the default
  // `() => "running"` bridge the test would pass whether or not the run was
  // retired, which is exactly why the previous "nothing notified yet" form
  // proved nothing.
  const h = fakeClockHarness({ states: () => null });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
      type: "subagent.child-status",
      version: 1,
      runId: "oracle-1",
      childId: "oracle-1",
      status: "stopped",
      source: "async",
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "a terminal transition retires the run, so the WAIT is unverified",
    );
  } finally {
    capture.restore();
  }
});

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// S2 scenarios: provenance persistence, reload, idle recheck, cleanup
// ---------------------------------------------------------------------------

/**
 * A fake-clock harness for the long-horizon S2 scenarios.
 *
 * Time is simulated: every `schedule(run, ms)` records an absolute due time on a
 * monotonic fake clock, and `advance(ms)` runs only the callbacks that come due,
 * in order. A 72-hour scenario therefore executes in microseconds and never
 * touches a real timer. Provenance persistence is modelled with an entry array
 * that `appendEntry` appends to and a `getBranch()` reader returns from, exactly
 * as Pi's session store behaves.
 */
function fakeClockHarness({ runId = "oracle-1", states = () => "running", entries = [], deferReplies = false, files = new Map(), envelope = undefined } = {}) {
  const persisted = [...entries];
  const timers = [];
  let now = 0;
  let seq = 0;
  // ASYNC MODE: when `deferReplies` is set the bus records each request instead
  // of answering it, so a test can advance the clock while a reply is IN FLIGHT
  // and deliver it afterwards. This is the only way to exercise the original
  // async failure (an expiry armed before the reply, re-testing proof with null
  // inputs). The synchronous `makeBus` path cannot reach it.
  const held = [];
  const rpcListeners = new Map();
  const answer = (request, state) => {
    const data = state === null ? null : rpcTargetedReply(runId, state);
    if (data === null) return;
    const replyTopic = `${mod.SUBAGENT_RPC_REPLY_PREFIX}${request.requestId}`;
    for (const listener of rpcListeners.get(replyTopic) ?? []) {
      listener({
        version: mod.SUBAGENT_RPC_VERSION,
        requestId: request.requestId,
        method: request.method,
        success: true,
        data,
      });
    }
  };
  const baseBus = makeBus(undefined, (request) => {
    // CORR10/NEW-2: an `envelope` responder returns a FULL reply envelope, so a
    // test can drive an error reply (e.g. `no_active_session`) that the
    // success-wrapping `makeBus` rpc responder cannot produce. It is emitted
    // verbatim from the request-topic override below.
    if (envelope !== undefined) return null;
    const state = typeof states === "function" ? states(request) : states;
    if (!deferReplies) return state === null ? null : rpcTargetedReply(runId, state);
    held.push({ request, state });
    return null; // never answers synchronously
  });
  const withEnvelope = envelope === undefined
    ? baseBus
    : {
        ...baseBus,
        emit(topic, event) {
          if (topic === mod.SUBAGENT_RPC_REQUEST_TOPIC) {
            const env = envelope(event);
            if (env === null || env === undefined) return;
            const replyTopic = `${mod.SUBAGENT_RPC_REPLY_PREFIX}${event.requestId}`;
            for (const listener of baseBus.listeners.get(replyTopic) ?? []) listener(env);
            return;
          }
          return baseBus.emit(topic, event);
        },
      };
  const bus = deferReplies
    ? {
        ...withEnvelope,
        // Track reply subscriptions so a held reply can be delivered later.
        on(topic, listener) {
          // Delegate to the base bus FIRST and keep whatever disposer it returns:
          // the counter below must be driven by the SAME registration the
          // disposer removes, or a correctly-disposed listener would still be
          // counted and a leak assertion would be meaningless.
          const dispose = baseBus.on(topic, listener);
          if (topic.startsWith(mod.SUBAGENT_RPC_REPLY_PREFIX)) {
            const list = rpcListeners.get(topic) ?? [];
            list.push(listener);
            rpcListeners.set(topic, list);
            return () => {
              const current = rpcListeners.get(topic) ?? [];
              const index = current.indexOf(listener);
              if (index >= 0) current.splice(index, 1);
              dispose?.();
            };
          }
          return dispose;
        },
      }
    : withEnvelope;
  const branch = () => persisted;
  const pi = makePi();
  pi.events = bus;
  pi.appendEntry = (customType, data) => {
    const entry = { type: "custom", customType, data };
    persisted.push(entry);
    return `entry-${persisted.length}`;
  };
  const filesystem = new Map(files);
  mod.registerSessionSupervisor(pi, {
    readFile: (path) => (filesystem.has(path) ? filesystem.get(path) : null),
    schedule: (run, ms) => {
      const handle = { run, due: now + ms, id: ++seq };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  const sessionFile = sessionFileFor(PARENT_UUID);
  const ctx = {
    ...UI,
    isIdle: () => true,
    sessionFile,
    sessionId: PARENT_UUID,
    sessionManager: { buildSessionProjection: () => ({ messages: [] }), getBranch: branch },
  };
  return {
    pi,
    bus,
    ctx,
    persisted,
    sessionFile,
    branch,
    now: () => now,
    pendingTimers: () => timers.length,
    /**
     * Total live RPC reply subscriptions across the bus.
     *
     * A leaked listener shows up here after a lifecycle path, which is the only
     * assertion that actually proves cleanup; "no notice fired" does not, because
     * the generation/epoch guards suppress notification while leaving the
     * subscription (and its timer) alive.
     */
    liveRpcListeners: () => {
      let total = 0;
      for (const [topic, list] of rpcListeners) {
        if (topic.startsWith(mod.SUBAGENT_RPC_REPLY_PREFIX)) total += list.length;
      }
      return total;
    },
    /** Live subscriptions on EVERY bus topic (reply + request + observations). */
    liveBusListeners: () => {
      let total = 0;
      for (const list of bus.listeners.values()) total += list.length;
      return total;
    },
    /** Requests whose replies are still IN FLIGHT (async mode only). */
    heldReplies: () => [...held],
    /** Deliver a held reply, modelling an async answer arriving now. */
    deliver: (entry) => {
      const index = held.indexOf(entry);
      if (index >= 0) held.splice(index, 1);
      answer(entry.request, entry.state);
    },
    /** Advance the fake clock by `ms`, running every timer that comes due. */
    advance: (ms) => {
      const target = now + ms;
      for (;;) {
        const due = timers.filter((t) => t.due <= target).sort((a, b) => a.due - b.due || a.id - b.id);
        if (due.length === 0) break;
        const handle = due[0];
        const index = timers.indexOf(handle);
        if (index >= 0) timers.splice(index, 1);
        now = handle.due;
        handle.run();
      }
      now = target;
    },
    /** Deliver a `subagent:async-started` observation for a run. */
    observeStart: (id, agent = "oracle", dir = undefined, extra = undefined) =>
      bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
        type: "subagent:async-started",
        version: 1,
        runId: id,
        id,
        asyncDir: dir,
        agent,
        sessionFile,
        sessionId: sessionFile,
        ...(extra ?? {}),
      }),
  };
}

const WAIT_ON = (runId) => assistant(`Waiting on the child.\n\nSTATUS:WAIT subagent ${runId} complete`);

test("S2: provenance is PERSISTED for an observed START, and records no permit", () => {
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  const records = h.persisted.filter((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
  assert.equal(records.length, 1, "one provenance record is persisted per observed START");
  const data = records[0].data;
  // CORR12/NEW-1: provenance records are REVISION 2 - they carry the per-
  // registration `lineage` token alongside the request epoch, so restoration can
  // bind a record to the registration that wrote it. This assertion previously
  // pinned revision 1; the revision bump is the correction, not a weakening.
  assert.equal(data.version, 2);
  assert.equal(typeof data.lineage, "string", "the record carries its registration lineage");
  assert.ok(data.lineage.length > 0, "a live registration mints a non-empty lineage token");
  assert.equal(data.runId, "oracle-1");
  assert.equal(data.sessionUuid, PARENT_UUID, "bound to this session");
  assert.equal(typeof data.requestEpoch, "number");
  // No verification outcome, timer, or execution permit is ever persisted.
  const serialized = JSON.stringify(data);
  assert.ok(!/verified|permit|wake/i.test(serialized), "provenance carries no permit/verification field");
});

test("S2: parseProvenanceRecord and restoreProvenance are fail-closed", () => {
  const good = { version: 1, runId: "r", agent: "oracle", asyncDir: null, sessionUuid: "u", requestEpoch: 2, runtimeInstanceId: "rt-a" };
  // CORR12/NEW-1: a version-1 record is LEGACY. It still parses (backward
  // compatibility) but with an EMPTY lineage, which can never equal a live
  // registration's token - so it is corroboration-incapable as current-lineage
  // provenance. This deepEqual now includes `lineage: ""` for that reason.
  assert.deepEqual(mod.parseProvenanceRecord(good), {
    runId: "r",
    agent: "oracle",
    asyncDir: null,
    sessionUuid: "u",
    requestEpoch: 2,
    runtimeInstanceId: "rt-a",
    terminal: false,
    deliveryCapable: true,
    lineage: "",
  });
  // CORR12/NEW-1: a version-2 (current) record parses WITH its lineage token.
  const current = { version: 2, runId: "r", agent: "oracle", asyncDir: null, sessionUuid: "u", requestEpoch: 2, runtimeInstanceId: "rt-a", lineage: "ln-abc" };
  assert.equal(mod.parseProvenanceRecord(current).lineage, "ln-abc", "a version-2 record keeps its lineage");
  // A version-2 record with a malformed token collapses to empty, never trusted.
  assert.equal(mod.parseProvenanceRecord({ ...current, lineage: 42 }).lineage, "", "a malformed token is fail-closed");
  // F3: a LEGACY record carrying no runtime instance id parses with an EMPTY
  // id. That is deliberate and fail-closed: an empty id can never equal this
  // process's id, so a pre-upgrade or tampered record is corroboration-
  // incapable rather than silently trusted.
  const legacy = { version: 1, runId: "r", agent: "oracle", asyncDir: null, sessionUuid: "u", requestEpoch: 2 };
  assert.equal(mod.parseProvenanceRecord(legacy).runtimeInstanceId, "", "legacy record parses with an empty instance id");
  // A malformed (non-string) instance id must also collapse to empty, never to
  // a value that could match.
  assert.equal(mod.parseProvenanceRecord({ ...good, runtimeInstanceId: 42 }).runtimeInstanceId, "");
  // PG4/AC-F2-2: a TERMINAL marking must SURVIVE the persisted round-trip. If it
  // were dropped on restore, a run this session watched finish would parse back
  // as merely-observed and could corroborate a WAIT again after a reload.
  assert.equal(
    mod.parseProvenanceRecord({ ...good, terminal: true }).terminal,
    true,
    "a terminal marking survives persistence",
  );
  // Absent (pre-upgrade) or malformed markings are NOT terminal: such a record
  // must be re-evaluated against the live bridge, never presumed dead.
  assert.equal(mod.parseProvenanceRecord(good).terminal, false, "absent marking is not terminal");
  assert.equal(mod.parseProvenanceRecord({ ...good, terminal: "yes" }).terminal, false, "malformed marking is not terminal");
  // R6-5: an explicitly INCAPABLE record stays incapable across a reload, so the
  // delivery rejection is not lost. Absent (pre-upgrade) parses as capable,
  // preserving prior behaviour for records written before this field existed.
  assert.equal(
    mod.parseProvenanceRecord({ ...good, deliveryCapable: false }).deliveryCapable,
    false,
    "an incapable marking survives persistence",
  );
  assert.equal(mod.parseProvenanceRecord(good).deliveryCapable, true, "absent marking is delivery-capable");
  assert.equal(
    mod.parseProvenanceRecord({ ...good, deliveryCapable: false }).deliveryCapable,
    false,
    "an explicit false is preserved (not truthy-coerced)",
  );
  for (const bad of [
    null,
    "x",
    // CORR12/NEW-1: version 2 is now a VALID revision (it adds `lineage`), so the
    // malformed-revision control moves to 3.
    { ...good, version: 3 },
    { ...good, runId: "" },
    { ...good, sessionUuid: "" },
    { ...good, requestEpoch: undefined },
    { ...good, requestEpoch: 1.5 },
  ]) {
    assert.equal(mod.parseProvenanceRecord(bad), null, JSON.stringify(bad));
  }
  // restoreProvenance ignores foreign customTypes and malformed payloads.
  const index = mod.restoreProvenance([
    { type: "custom", customType: "other:thing", data: good },
    { type: "custom", customType: mod.PROVENANCE_CUSTOM_TYPE, data: { version: 9 } },
    { type: "custom", customType: mod.PROVENANCE_CUSTOM_TYPE, data: good },
  ]);
  assert.equal(index.size, 1, "only the valid provenance entry is restored");
  assert.equal(index.get("r").sessionUuid, "u");
});

test("S2: a same-session reload restores provenance and re-verifies via the bridge", () => {
  // Start a run, persist its provenance, then build a SECOND registration whose
  // session branch carries that persisted entry - modelling a reload/resume.
  const first = fakeClockHarness();
  first.observeStart("oracle-1");
  const carried = first.persisted;

  const reloaded = fakeClockHarness({ entries: carried });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  reloaded.pi.emit("agent_settled", settleEvent(), {
    ...reloaded.ctx,
    sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: reloaded.branch },
  });
  const capture = captureStdout();
  try {
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "restored provenance plus a live bridge re-verifies the WAIT");
  } finally {
    capture.restore();
  }
});

test("S2: restored provenance from a FOREIGN session is rejected", () => {
  const foreignUuid = "aaaaaaaa-9999-8888-7777-666666666666";
  const entry = {
    type: "custom",
    customType: mod.PROVENANCE_CUSTOM_TYPE,
    data: {
      version: 1,
      runId: "oracle-1",
      agent: "oracle",
      asyncDir: null,
      sessionUuid: foreignUuid,
      requestEpoch: 1,
    },
  };
  const h = fakeClockHarness({ entries: [entry] });
  h.pi.emit("session_start", { type: "session_start", reason: "reload" }, h.ctx);
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT], "foreign provenance must not silence a WAIT");
  } finally {
    capture.restore();
  }
});

test("S2: the idle recheck keeps a still-live owner silent across 72 fake hours", () => {
  // A long-horizon scenario: verify once, then advance 72 hours. The single
  // recheck fires at ~60s, finds the owner live, and does NOT notify. Later
  // rechecks are not re-armed (exactly one), so the 72h advance produces no
  // notice and no runaway timers.
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    // Short verification window resolves; the recheck is now armed.
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "the initial verification stays silent");
    h.advance(72 * 60 * 60 * 1000);
    assert.deepEqual(capture.chunks, [], "a continuously-live owner stays silently waited on");
    assert.equal(h.pendingTimers(), 0, "no timer leaks across the long advance");
  } finally {
    capture.restore();
  }
});

test("S2: worker disappearance at the idle recheck fires the unverified notice", () => {
  // The owner is live at verification, then GONE by the recheck: the scenario
  // sweeps the clock past the recheck window and expects exactly one notice.
  let live = true;
  const h = fakeClockHarness({ states: () => (live ? "running" : null) });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "live owner is silent at verification");
    live = false;
    h.advance(WAIT_RECHECK_MS + WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT], "a disappeared worker must notify");
  } finally {
    capture.restore();
  }
});

test("S2: a stale reply cannot resurrect a superseded verification", () => {
  // New input supersedes the pending check; its epoch guard makes any late
  // resolution a no-op. This advances well past the window AFTER supersession
  // and asserts no notice fires for the abandoned turn.
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    // Supersede with fresh genuine input BEFORE the window expires.
    h.pi.emit("input", { type: "input", text: "carry on", source: "interactive" }, h.ctx);
    h.advance(60 * 60 * 1000);
    assert.deepEqual(capture.chunks, [], "a superseded verification never notifies");
  } finally {
    capture.restore();
  }
});

test("S2: a sibling stopping does not retire a parallel verified run", () => {
  // Two parallel runs are witnessed. One reports terminal; the OTHER remains
  // verified and silent, proving the retirement is per-run and not global.
  const h = fakeClockHarness({ runId: "oracle-a" });
  h.observeStart("oracle-a");
  h.observeStart("oracle-b");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-a")] }), getBranch: h.branch },
    });
    // A SIBLING run reports terminal; it is not the run this WAIT names.
    h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
      type: "subagent.child-status",
      version: 1,
      runId: "oracle-b",
      childId: "oracle-b",
      status: "stopped",
      source: "async",
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "the named parallel run keeps its silence");
  } finally {
    capture.restore();
  }
});

test("S2: shutdown cancels pending timers and no notice fires afterwards", () => {
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    h.pi.emit("session_shutdown", { type: "session_shutdown" }, h.ctx);
    assert.equal(h.pendingTimers(), 0, "shutdown cancels every pending timer");
    h.advance(72 * 60 * 60 * 1000);
    assert.deepEqual(capture.chunks, [], "no notice fires after shutdown");
  } finally {
    capture.restore();
  }
});

test("S2: a synthetic extension wake does NOT disarm allowance or replace the epoch", () => {
  // AS-4: the pi-subagents bridge delivers a wake as a user message with
  // source "extension". It must not open a new observation epoch, or the wake a
  // verified WAIT is waiting for would itself cancel the wait.
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "verified and silent");
    // The synthetic wake arrives; it must not cancel the armed recheck.
    h.pi.emit("input", { type: "input", text: "child finished", source: "extension" }, h.ctx);
    h.advance(WAIT_RECHECK_MS);
    assert.deepEqual(capture.chunks, [], "an extension wake leaves the verified WAIT undisturbed");
  } finally {
    capture.restore();
  }
});

// ---------------------------------------------------------------------------
// S1 REAL-HOST INTEGRATION HARNESS (AC-F1-2 / AC-F1-3)
//
// The tests above drive the boundary handler in isolation, which proves what it
// RETURNS but not that the continuation Pi was asked for is actually RUNNABLE.
// Pi's own decision does not read the returned flag for that: `_runBeforeSettleBoundary`
// commits the returned drafts FIRST, recomputes the boundary context from the
// COMMITTED branch, and only then refuses an unbacked continuation:
//
//   const result = await emitBoundary({type:"agent_before_settle", outcome}, (entries) =>
//     buildBoundaryContext(entries, "agent_before_settle"));
//   this._commitBoundaryDrafts(result.entries);
//   this._flushPendingCustomMessages();
//   const finalContext = this._buildBoundaryContext([], "agent_before_settle");
//   if (this._abortDuringBeforeSettle) return false;
//   const shouldContinue = result.continue || this.agent.hasQueuedMessages();
//   if (shouldContinue && !finalContext.canContinue) {
//     if (result.continue) this._reportInvalidBoundaryContinuation("agent_before_settle");
//     return false;
//   }
//   return shouldContinue;
//
// and `emitBoundary` accumulates handler results, rebuilding the context after
// each one:
//
//   for (const { ext, handlers } of ...) for (const handler of handlers) {
//     const handlerResult = await handler({...baseEvent, entries, continue: shouldContinue, context}, ctx);
//     if (handlerResult?.entries !== undefined) entries = handlerResult.entries;
//     if (handlerResult?.continue !== undefined) shouldContinue = handlerResult.continue;
//     context = await buildContext(entries);
//   }
//   return valid ? {entries, continue: shouldContinue, context, valid: true} : {...};
//
// This harness reproduces exactly those two functions at the seam that matters:
// its ANSWER ("did the host continue?") is derived from the same `canContinue`
// rule the real host uses, so a test cannot pass on a flag the host would reject.
// Reference: pi-coding-agent 1.1.0 `dist/core/agent-session.js:613-637,:1452-1475`
// and `dist/core/extensions/runner.js:759-805`.
// ---------------------------------------------------------------------------

/** The draft union a boundary handler may append. */
const draftIsCustomMessage = (d) => d !== null && typeof d === "object" && d.type === "custom_message";

/**
 * `_buildBoundaryContext` at the seam the continuation decision depends on.
 *
 * The committed drafts are projected as context messages, and Pi's rule is:
 *   contextCanContinue = hasNonSystemContext && finalRole !== "assistant"
 *   canContinue = contextCanContinue || pendingCustomContext || <queued fallback>
 * A `custom_message` draft projects as a non-system message, so appending one
 * makes `canContinue` true. That is why the bridge is load-bearing rather than
 * decorative.
 */
function hostBuildBoundaryContext(drafts, pendingMessages, options = {}) {
  const { boundary = "agent_before_settle", priorMessages = [] } = options;
  const projected = [...priorMessages];
  for (const draft of drafts) {
    if (draftIsCustomMessage(draft)) {
      projected.push({ role: "custom", customType: draft.customType, content: draft.content });
    }
  }
  const finalRole = projected[projected.length - 1]?.role;
  const hasNonSystemContext = projected.some((m) => m.role !== "system");
  const contextCanContinue = hasNonSystemContext && finalRole !== "assistant";
  const pendingCustomContext = drafts.some(draftIsCustomMessage);
  const queued = Array.isArray(pendingMessages) && pendingMessages.length > 0;
  return {
    contextMessages: projected,
    pendingMessages,
    canContinue:
      contextCanContinue ||
      pendingCustomContext ||
      (boundary === "turn_end" ? queued : finalRole === "assistant" && queued),
  };
}

/**
 * `emitBoundary` + `_runBeforeSettleBoundary` at the seam that decides whether
 * the host runs another request. Returns the host's answer, not the handler's.
 */
async function hostRunBoundary({ handlers, outcome = "completed", entries, pendingMessages = [], priorMessages = [] }) {
  const buildContext = (drafts) =>
    hostBuildBoundaryContext(drafts, pendingMessages, { boundary: "agent_before_settle", priorMessages });

  // --- emitBoundary: accumulate results across handlers, rebuilding context.
  let accEntries = Array.isArray(entries) ? entries : [];
  let shouldContinue = false;
  let context = buildContext(accEntries);
  let valid = true;
  for (const handler of handlers) {
    const event = { type: "agent_before_settle", outcome, entries: accEntries, continue: shouldContinue, context };
    let handlerResult;
    try {
      handlerResult = await handler(event);
    } catch {
      continue; // the real runner reports and keeps going
    }
    if (handlerResult?.entries !== undefined) accEntries = handlerResult.entries;
    if (handlerResult?.continue !== undefined) shouldContinue = handlerResult.continue;
    context = buildContext(accEntries);
    valid = true;
  }
  const result = valid ? { entries: accEntries, continue: shouldContinue, context, valid: true } : { entries: [], continue: false, context, valid: false };

  // --- _runBeforeSettleBoundary: commit drafts, then apply the canContinue veto.
  const finalContext = buildContext(result.entries);
  const hostShouldContinue = result.continue || pendingMessages.length > 0;
  if (hostShouldContinue && !finalContext.canContinue) {
    return { continued: false, invalidContinuation: result.continue === true, entries: result.entries, finalContext };
  }
  return { continued: hostShouldContinue, invalidContinuation: false, entries: result.entries, finalContext };
}

/** The extension's own `agent_before_settle` handler, bound to a live-ish pi. */
const supervisorBoundaryHandler = (pi) => handlerFor(pi, "agent_before_settle");

test("AC-F1-2: a fresh CONTINUE produces a runnable continuation on the host", async () => {
  // The end-to-end claim under test: the bridge the handler returns is COMMITTED
  // into context, the host recomputes `canContinue` from that committed branch,
  // and the host then proceeds to another request. Isolation tests cannot show
  // this, because they never run Pi's veto.
  const pi = armed();
  const result = await hostRunBoundary({
    handlers: [(event) => supervisorBoundaryHandler(pi)(event, UI)],
    priorMessages: [user("do it"), assistant(CONTINUE)],
  });
  assert.equal(result.continued, true, "the host runs another request");
  assert.equal(result.invalidContinuation, false, "and does not report an unbacked continuation");
  assert.equal(
    result.finalContext.canContinue,
    true,
    "canContinue is true because the bridge draft committed a non-assistant context message",
  );
  assert.ok(
    result.entries.some((e) => e.customType === mod.BRIDGE_CUSTOM_TYPE),
    "the committed drafts carry the bridge",
  );
});

test("AC-F1-3: another handler's bare continue:true still gets a runnable bridge", async () => {
  // The failure this guards: a bare `continue: true` sets the flag but commits no
  // message, so `finalContext.canContinue` stays false and Pi refuses the
  // continuation as invalid. Because `emitBoundary` accumulates, OUR handler must
  // still append the runnable bridge even though the flag is already set.
  const pi = armed();
  const otherHandler = () => ({ continue: true }); // no entries: the bare case
  const result = await hostRunBoundary({
    handlers: [otherHandler, (event) => supervisorBoundaryHandler(pi)(event, UI)],
    priorMessages: [user("do it"), assistant(CONTINUE)],
  });
  assert.equal(result.invalidContinuation, false, "the continuation is not refused as invalid");
  assert.equal(result.continued, true, "the host runs another request");
  assert.equal(result.finalContext.canContinue, true, "our bridge supplied the runnable context");
  assert.ok(result.entries.some((e) => e.customType === mod.BRIDGE_CUSTOM_TYPE), "the bridge was committed");
});

test("AC-F1-3: a bare continue:true ALONE is refused by the host (control)", async () => {
  // Negative control proving the harness's ANSWER is faithful: with no runnable
  // message supplied by anyone, the identical host logic refuses the bare
  // continuation. If this control ever passes as `continued`, the harness has
  // stopped modelling Pi and the AC-F1-3 result above would be meaningless.
  const result = await hostRunBoundary({
    handlers: [() => ({ continue: true })],
    priorMessages: [assistant("I am done.")],
  });
  assert.equal(result.continued, false, "an unbacked continuation does not run");
  assert.equal(result.invalidContinuation, true, "and the host reports it as invalid");
  assert.equal(result.finalContext.canContinue, false, "because nothing runnable was committed");
});

test("AC-F1-4: an aborted boundary is not run by the host", async () => {
  const pi = armed();
  const result = await hostRunBoundary({
    handlers: [(event) => supervisorBoundaryHandler(pi)(event, UI)],
    outcome: "aborted",
    priorMessages: [user("do it"), assistant(CONTINUE)],
  });
  assert.equal(result.continued, false, "an aborted run does not continue");
  assert.equal(result.invalidContinuation, false, "and no invalid continuation is reported");
});

test("AC-F1-4: an errored boundary is not run by the host", async () => {
  const pi = armed();
  const result = await hostRunBoundary({
    handlers: [(event) => supervisorBoundaryHandler(pi)(event, UI)],
    outcome: "error",
    priorMessages: [user("do it"), assistant(CONTINUE)],
  });
  assert.equal(result.continued, false, "an errored run does not continue");
});

test("AC-F1-4: PI_MAX_CONTINUATIONS=0 leaves the host with nothing to run", async () => {
  const pi = armedWithBudget(0);
  const result = await hostRunBoundary({
    handlers: [(event) => supervisorBoundaryHandler(pi)(event, UI)],
    priorMessages: [user("do it"), assistant(CONTINUE)],
  });
  assert.equal(result.continued, false, "an explicit operator disable stops automatic continuation");
  assert.equal(result.invalidContinuation, false, "the handler proposed nothing to refuse");
});

test("step (3): real queued messages own the next request, so no bridge is added", async () => {
  // Pi continues on `hasQueuedMessages()` regardless of the handler's flag. When
  // real queued work already owns the next request, this handler must add NO
  // bridge, or its prompt would be delivered on top of the queued work.
  const pi = armed();
  const result = await hostRunBoundary({
    handlers: [(event) => supervisorBoundaryHandler(pi)(event, UI)],
    priorMessages: [user("do it"), assistant(CONTINUE)],
    pendingMessages: [user("queued follow-up")],
  });
  assert.equal(result.continued, true, "the host continues because real work is queued");
  assert.equal(
    result.entries.some((e) => e.customType === mod.BRIDGE_CUSTOM_TYPE),
    false,
    "no bridge was appended alongside the queued work",
  );
});

// ---------------------------------------------------------------------------
// Correction batch: five Review-found defects (Oracle ef11d0a6)
//
// Each test drives the REAL factory through the registered handlers. The D2
// test deliberately uses the REAL Pi context shape (`sessionManager` accessors,
// NO direct `sessionFile`/`sessionId`), because a fixture that invents the
// direct fields is exactly what concealed that defect.
// ---------------------------------------------------------------------------

test("D1: a context-only pending message does NOT suppress the runnable bridge", async () => {
  // Pi's pending array mixes genuine queued user work with context-only custom
  // messages (added with `triggerTurn:false`) that are flushed to context but do
  // NOT drive a further turn: continuation is `result.continue ||
  // agent.hasQueuedMessages()`, and `hasQueuedMessages()` covers only the
  // steering/follow-up queues. Treating every pending entry as ownership
  // therefore stopped a valid CONTINUE - the user's original complaint #1.
  const pi = armed();
  const result = await proposes(pi, [assistant(CONTINUE)], {
    context: {
      contextMessages: [user("do it"), assistant(CONTINUE)],
      canContinue: false,
      pendingMessages: [{ type: "custom_message", customType: "other:note", content: "context only" }],
    },
  });
  assert.equal(result?.continue, true, "a valid CONTINUE must still continue");
  assert.equal(
    result.entries.at(-1).customType,
    mod.BRIDGE_CUSTOM_TYPE,
    "the runnable bridge is supplied despite a context-only pending message",
  );
});

test("D1: a genuine queued user message still suppresses the bridge", async () => {
  // The counterpart: real queued work DOES own the next request, so no bridge is
  // added (a second prompt would duplicate it). This preserves the original
  // duplicate-suppression intent while fixing the context-only case above.
  const pi = armed();
  const result = await proposes(pi, [assistant(CONTINUE)], {
    context: {
      contextMessages: [user("do it"), assistant(CONTINUE)],
      canContinue: false,
      pendingMessages: [{ role: "user", content: [{ type: "text", text: "queued" }] }],
    },
  });
  assert.equal(result, undefined, "genuine queued work owns the next request");
});

test("D2: session identity is read through the REAL context (sessionManager)", async () => {
  // The real `ExtensionRunner.createContext()` exposes NO direct
  // `sessionFile`/`sessionId`; identity lives on `ctx.sessionManager`. Reading
  // only the direct fields yielded an EMPTY identity on a live host, so
  // provenance never matched and every genuine WAIT was rejected. This context
  // models the host faithfully: sessionManager accessors, no direct fields.
  const sessionFile = sessionFileFor(PARENT_UUID);
  const bus = makeBus(undefined, () => rpcSnapshot("oracle-1", "running"));
  const pi = makePi();
  pi.events = bus;
  const timers = [];
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  // REAL-SHAPED context: no `sessionFile`, no `sessionId` at the top level.
  const ctx = {
    ...UI,
    isIdle: () => true,
    sessionManager: {
      getSessionFile: () => sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [] }),
    },
  };
  pi.emit("input", { type: "input", text: "go", source: "interactive" }, ctx);
  pi.emit("before_agent_start", { type: "before_agent_start", prompt: "go" }, ctx);
  pi.emit("message_start", { type: "message_start", message: { role: "user", content: "go" } }, ctx);
  // Observe the run START through the SAME subscription a host uses, so
  // provenance is built from the identity the manager supplied.
  bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
    type: "subagent:async-started",
    version: 1,
    runId: "oracle-1",
    id: "oracle-1",
    agent: "oracle",
    sessionFile,
    sessionId: sessionFile,
  });
  const waitCtx = {
    ...ctx,
    sessionManager: {
      getSessionFile: () => sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: () => [],
    },
  };
  pi.emit("agent_settled", settleEvent(), waitCtx);
  const capture = captureStdout();
  try {
    timers.filter((t) => t.ms === WAIT_VERIFICATION_MS).forEach((t) => t.run());
    assert.deepEqual(
      capture.chunks,
      [],
      "a live owner bound through sessionManager verifies the WAIT (no unverified notice)",
    );
  } finally {
    capture.restore();
  }
});

test("D2: an ABSENT identity still fails closed (never a match)", () => {
  // Fail-closed control: with no identity reachable at all, provenance cannot
  // bind and the WAIT must be reported unverified rather than silently trusted.
  const bus = makeBus(undefined, () => rpcSnapshot("oracle-1", "running"));
  const pi = makePi();
  pi.events = bus;
  const timers = [];
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  const bare = { ...UI, isIdle: () => true };
  pi.emit("input", { type: "input", text: "go", source: "interactive" }, bare);
  pi.emit("before_agent_start", { type: "before_agent_start", prompt: "go" }, bare);
  pi.emit("message_start", { type: "message_start", message: { role: "user", content: "go" } }, bare);
  bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
    type: "subagent:async-started",
    version: 1,
    runId: "oracle-1",
    id: "oracle-1",
    agent: "oracle",
  });
  // Capture BEFORE the settle: the notice is written during the expiry callback,
  // so installing the stub afterwards would miss it and mask the assertion.
  const capture = captureStdout();
  try {
    pi.emit("agent_settled", settleEvent(), {
      ...bare,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }) },
    });
    timers.filter((t) => t.ms === WAIT_VERIFICATION_MS).forEach((t) => t.run());
    assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT], "no identity can never prove a WAIT");
  } finally {
    capture.restore();
  }
});

test("D3: a successful recheck does NOT emit an unverified notice", () => {
  // The recheck's expiry used to be scheduled before the async reply arrived and
  // re-tested proof with null inputs (always false), so a SUCCESSFUL recheck
  // still notified. The expiry is now a pure no-answer guard that a valid reply
  // cancels.
  const h = fakeClockHarness({ states: () => "running" });
  h.observeStart("oracle-1");
  h.pi.emit("session_start", { type: "session_start", reason: "reload" }, h.ctx);
  h.pi.emit("agent_settled", settleEvent(), {
    ...h.ctx,
    sessionManager: {
      getSessionFile: () => h.sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: h.branch,
    },
  });
  const capture = captureStdout();
  try {
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "the initial verification is silent while the owner is live");
    // Fire the recheck; the owner answers live, so no notice may follow.
    h.advance(WAIT_RECHECK_MS);
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "a successful recheck must stay silent");
  } finally {
    capture.restore();
  }
});

test("D3: a recheck whose reply NEVER arrives still emits the unverified notice", () => {
  // Counterpart: an owner that stopped answering is exactly the disappeared
  // worker. The no-answer guard must still fire, or a dead child could leave the
  // run stalled forever.
  let answers = 0;
  const h = fakeClockHarness({
    states: () => {
      answers += 1;
      return answers <= 1 ? "running" : null; // live at first, silent at recheck
    },
  });
  h.observeStart("oracle-1");
  h.pi.emit("session_start", { type: "session_start", reason: "reload" }, h.ctx);
  h.pi.emit("agent_settled", settleEvent(), {
    ...h.ctx,
    sessionManager: {
      getSessionFile: () => h.sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: h.branch,
    },
  });
  const capture = captureStdout();
  try {
    h.advance(WAIT_VERIFICATION_MS);
    h.advance(WAIT_RECHECK_MS);
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [OSC_UNVERIFIED_WAIT], "a silent owner must be reported");
  } finally {
    capture.restore();
  }
});

test("D4: a NEW WAIT on the SAME run cannot inherit the PREVIOUS WAIT's silence", () => {
  // A second WAIT naming the same run, with no intervening input/session reset,
  // used to be suppressed by a stale `recheckRunId` from the first verification -
  // so its own fresh RPC could never answer and it stayed silent forever.
  let answers = 0;
  const h = fakeClockHarness({
    states: () => {
      answers += 1;
      return answers <= 1 ? "running" : null; // first WAIT verified; second never answers
    },
  });
  h.observeStart("oracle-1");
  h.pi.emit("session_start", { type: "session_start", reason: "reload" }, h.ctx);
  const waitCtx = {
    ...h.ctx,
    sessionManager: {
      getSessionFile: () => h.sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: h.branch,
    },
  };
  h.pi.emit("agent_settled", settleEvent(), waitCtx);
  h.advance(WAIT_VERIFICATION_MS);
  // A second WAIT on the SAME run: its fresh check must NOT be granted silence.
  h.pi.emit("agent_settled", settleEvent(), waitCtx);
  const capture = captureStdout();
  try {
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "a new unproven WAIT must be reported, not silenced by the previous verification",
    );
  } finally {
    capture.restore();
  }
});

test("D5: the disposer returned by events.on() is invoked (no listener leak)", async () => {
  // The REAL Pi bus returns a disposer FUNCTION from `on()` and exposes neither
  // `off` nor `removeListener`. Ignoring it leaked one listener per request - a
  // real problem for multi-day operation.
  let disposals = 0;
  const listeners = new Map();
  const bus = {
    emit(topic, event) {
      if (topic !== mod.SUBAGENT_RPC_REQUEST_TOPIC) return;
      const replyTopic = `${mod.SUBAGENT_RPC_REPLY_PREFIX}${event.requestId}`;
      // Answer successfully, exactly as the bridge does.
      for (const listener of listeners.get(replyTopic) ?? []) {
        listener({
          version: mod.SUBAGENT_RPC_VERSION,
          requestId: event.requestId,
          method: event.method,
          success: true,
          data: rpcSnapshot("oracle-1", "running"),
        });
      }
    },
    on(topic, listener) {
      (listeners.get(topic) ?? listeners.set(topic, []).get(topic)).push(listener);
      // The REAL contract: returning a disposer, and NO off/removeListener.
      return () => {
        disposals += 1;
        const list = listeners.get(topic) ?? [];
        const index = list.indexOf(listener);
        if (index >= 0) list.splice(index, 1);
      };
    },
  };
  const pi = makePi();
  pi.events = bus;
  const timers = [];
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  const sessionFile = sessionFileFor(PARENT_UUID);
  const ctx = {
    ...UI,
    isIdle: () => true,
    sessionManager: {
      getSessionFile: () => sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [] }),
    },
  };
  pi.emit("input", { type: "input", text: "go", source: "interactive" }, ctx);
  pi.emit("before_agent_start", { type: "before_agent_start", prompt: "go" }, ctx);
  pi.emit("message_start", { type: "message_start", message: { role: "user", content: "go" } }, ctx);
  bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
    type: "subagent:async-started",
    version: 1,
    runId: "oracle-1",
    id: "oracle-1",
    agent: "oracle",
    sessionFile,
    sessionId: sessionFile,
  });
  pi.emit("agent_settled", settleEvent(), {
    ...ctx,
    sessionManager: {
      getSessionFile: () => sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: () => [],
    },
  });
  timers.filter((t) => t.ms === WAIT_VERIFICATION_MS).forEach((t) => t.run());
  assert.ok(disposals >= 1, "the disposer returned by on() must be invoked after the reply");
});

test("D5: an unanswered request frees its listener at expiry", () => {
  // The listener must also be disposed when NO reply ever arrives, or unanswered
  // requests retain state forever.
  let disposals = 0;
  const listeners = new Map();
  const bus = {
    emit() {
      // Never answers.
    },
    on(topic, listener) {
      (listeners.get(topic) ?? listeners.set(topic, []).get(topic)).push(listener);
      return () => {
        disposals += 1;
      };
    },
  };
  const pi = makePi();
  pi.events = bus;
  const timers = [];
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  const sessionFile = sessionFileFor(PARENT_UUID);
  const ctx = {
    ...UI,
    isIdle: () => true,
    sessionManager: {
      getSessionFile: () => sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [] }),
    },
  };
  pi.emit("input", { type: "input", text: "go", source: "interactive" }, ctx);
  pi.emit("before_agent_start", { type: "before_agent_start", prompt: "go" }, ctx);
  pi.emit("message_start", { type: "message_start", message: { role: "user", content: "go" } }, ctx);
  bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
    type: "subagent:async-started",
    version: 1,
    runId: "oracle-1",
    id: "oracle-1",
    agent: "oracle",
    sessionFile,
    sessionId: sessionFile,
  });
  pi.emit("agent_settled", settleEvent(), {
    ...ctx,
    sessionManager: {
      getSessionFile: () => sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: () => [],
    },
  });
  timers.filter((t) => t.ms === WAIT_VERIFICATION_MS).forEach((t) => t.run());
  assert.ok(disposals >= 1, "an unanswered request must free its listener at expiry");
});

// ---------------------------------------------------------------------------
// CORR2 (C1-C6): native-shape pending classification, superseded-wait
// invalidation, listener cleanup, and authoritative status precedence.
// ---------------------------------------------------------------------------

test("C1: a genuinely queued CUSTOM message still yields a runnable bridge (never a stop)", async () => {
  // Pi routes the SAME `role:"custom"` shape to BOTH the steering/followUp
  // queues (`agent.steer`/`agent.followUp`) and `_pendingCustomMessages`. The
  // pending array therefore cannot prove queue ownership by shape. Claiming
  // ownership wrongly returns no bridge AND no flag, so a valid CONTINUE STOPS.
  // The asymmetric failure decides the ambiguous case: supply the bridge.
  const pi = armed();
  const result = await proposes(pi, [assistant(CONTINUE)], {
    context: {
      contextMessages: [user("do it"), assistant(CONTINUE)],
      canContinue: false,
      pendingMessages: [{ role: "custom", customType: "steer:msg", content: [] }],
    },
  });
  assert.equal(result?.continue, true, "an ambiguous custom entry must NOT stop the run");
  assert.equal(result.entries.at(-1).customType, mod.BRIDGE_CUSTOM_TYPE, "the bridge is supplied");
});

test("C2: a context-only custom message with an EMPTY customType still continues", async () => {
  // Pi does not reject an empty `customType`, and a context-only entry with one
  // used to be classified as queued ownership - so the run stopped with neither
  // bridge nor flag even though Pi would not continue on its own.
  const pi = armed();
  const result = await proposes(pi, [assistant(CONTINUE)], {
    context: {
      contextMessages: [user("do it"), assistant(CONTINUE)],
      canContinue: false,
      pendingMessages: [{ role: "custom", customType: "", content: [] }],
    },
  });
  assert.equal(result?.continue, true, "an empty customType must not be mistaken for queued work");
});

test("C3: a bare {} is NOT treated as PROVEN queued ownership (run must continue)", async () => {
  // The old classifier returned true when `role` was absent, so `{}` was
  // labelled "context-only" while the documented fallback said an unknown shape
  // must stay conservative. Under the C1 design the only sound rule is the
  // asymmetry: ownership must be POSITIVE, so an unrecognized entry never
  // suppresses the bridge and never stops the run. `{}` therefore continues.
  const pi = armed();
  const result = await proposes(pi, [assistant(CONTINUE)], {
    context: {
      contextMessages: [user("do it"), assistant(CONTINUE)],
      canContinue: false,
      pendingMessages: [{}],
    },
  });
  assert.equal(result?.continue, true, "an unrecognized entry must not stop the run");
  assert.equal(
    result.entries.at(-1).customType,
    mod.BRIDGE_CUSTOM_TYPE,
    "only POSITIVELY identified queued work may suppress the bridge",
  );
});

test("C4: a superseded WAIT's DELAYED reply cannot silence the new WAIT", async () => {
  // Genuinely ASYNCHRONOUS: the first verification's reply is held and delivered
  // only AFTER a second WAIT has started (no intervening input or navigation, so
  // `waitEpoch` is unchanged). The old code let the stale callback pass the
  // epoch guard, cancel the timer now belonging to the second WAIT, and arm a
  // recheck for the first - leaving the second WAIT silent forever.
  const delivered = [];
  const listeners = new Map();
  const bus = {
    emit(topic, event) {
      if (topic !== mod.SUBAGENT_RPC_REQUEST_TOPIC) return;
      const replyTopic = `${mod.SUBAGENT_RPC_REPLY_PREFIX}${event.requestId}`;
      // Queue the reply for explicit delivery; do NOT answer synchronously.
      delivered.push({ replyTopic, requestId: event.requestId, method: event.method });
    },
    on(topic, listener) {
      (listeners.get(topic) ?? listeners.set(topic, []).get(topic)).push(listener);
      return () => {
        const list = listeners.get(topic) ?? [];
        const index = list.indexOf(listener);
        if (index >= 0) list.splice(index, 1);
      };
    },
  };
  const timers = [];
  const pi = makePi();
  pi.events = bus;
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  const sessionFile = sessionFileFor(PARENT_UUID);
  const sessionManager = {
    getSessionFile: () => sessionFile,
    getSessionId: () => PARENT_UUID,
    buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
    getBranch: () => [],
  };
  const ctx = { ...UI, isIdle: () => true, sessionManager };
  // Establish provenance for the run this session witnessed start.
  bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
    type: "subagent:async-started",
    version: 1,
    runId: "oracle-1",
    id: "oracle-1",
    agent: "oracle",
    sessionFile,
    sessionId: sessionFile,
  });
  // WAIT A starts an unanswered RPC (reply held).
  pi.emit("agent_settled", settleEvent(), ctx);
  const heldA = delivered.splice(0);
  assert.equal(heldA.length, 1, "WAIT A issued one RPC request");
  // WAIT B replaces it with NO intervening input/navigation (epoch unchanged).
  pi.emit("agent_settled", settleEvent(), ctx);
  const heldB = delivered.splice(0);
  assert.equal(heldB.length, 1, "WAIT B issued its own RPC request");
  const capture = captureStdout();
  try {
    // Deliver A's LATE reply now that B is the current verification.
    const deliver = (held, state) => {
      for (const listener of listeners.get(held.replyTopic) ?? []) {
        listener({
          version: mod.SUBAGENT_RPC_VERSION,
          requestId: held.requestId,
          method: held.method,
          success: true,
          data: rpcSnapshot("oracle-1", state),
        });
      }
    };
    deliver(heldA, "running");
    assert.deepEqual(capture.chunks, [], "a superseded reply must not notify");
    // B never answers: its no-answer guard must still fire.
    timers.filter((t) => t.ms === WAIT_VERIFICATION_MS).forEach((t) => t.run());
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "WAIT B must not be silenced by WAIT A's late reply",
    );
  } finally {
    capture.restore();
  }
});

test("C5: supersession frees the superseded request's listener (no leak)", () => {
  // The RPC cancellation handle used to be reachable ONLY from inside the expiry
  // callback, so input/replacement/navigation/shutdown cancelled the timer while
  // leaving the listener subscribed. Each superseded WAIT therefore leaked one.
  let disposeCount = 0;
  const listeners = new Map();
  const bus = {
    emit(topic) {
      if (topic === mod.SUBAGENT_RPC_REQUEST_TOPIC) return; // never answers
    },
    on(topic, listener) {
      (listeners.get(topic) ?? listeners.set(topic, []).get(topic)).push(listener);
      return () => {
        disposeCount += 1;
        const list = listeners.get(topic) ?? [];
        const index = list.indexOf(listener);
        if (index >= 0) list.splice(index, 1);
      };
    },
  };
  const live = () => [...listeners.values()].reduce((n, list) => n + list.length, 0);
  const timers = [];
  const pi = makePi();
  pi.events = bus;
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  const sessionFile = sessionFileFor(PARENT_UUID);
  const ctx = {
    ...UI,
    isIdle: () => true,
    sessionManager: {
      getSessionFile: () => sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: () => [],
    },
  };
  bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
    type: "subagent:async-started",
    version: 1,
    runId: "oracle-1",
    id: "oracle-1",
    agent: "oracle",
    sessionFile,
    sessionId: sessionFile,
  });
  const baseline = live();
  // Supersede the same WAIT several times without input/navigation.
  for (let i = 0; i < 4; i += 1) pi.emit("agent_settled", settleEvent(), ctx);
  assert.ok(disposeCount >= 3, "each superseded request's listener must be freed");
  assert.equal(live(), baseline + 1, "only the CURRENT verification may retain a listener");
});

test("C5: shutdown frees an unanswered request's listener", () => {
  // The shutdown path must reach the RPC handle too, not just the timers.
  let disposeCount = 0;
  const listeners = new Map();
  const bus = {
    emit(topic) {
      if (topic === mod.SUBAGENT_RPC_REQUEST_TOPIC) return; // never answers
    },
    on(topic, listener) {
      (listeners.get(topic) ?? listeners.set(topic, []).get(topic)).push(listener);
      return () => {
        disposeCount += 1;
        const list = listeners.get(topic) ?? [];
        const index = list.indexOf(listener);
        if (index >= 0) list.splice(index, 1);
      };
    },
  };
  const timers = [];
  const pi = makePi();
  pi.events = bus;
  mod.registerSessionSupervisor(pi, {
    schedule: (run, ms) => {
      const handle = { run, ms };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  const sessionFile = sessionFileFor(PARENT_UUID);
  const ctx = {
    ...UI,
    isIdle: () => true,
    sessionManager: {
      getSessionFile: () => sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: () => [],
    },
  };
  bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
    type: "subagent:async-started",
    version: 1,
    runId: "oracle-1",
    id: "oracle-1",
    agent: "oracle",
    sessionFile,
    sessionId: sessionFile,
  });
  pi.emit("agent_settled", settleEvent(), ctx);
  const rpcListeners = () =>
    [...listeners.entries()]
      .filter(([topic]) => topic.startsWith(mod.SUBAGENT_RPC_REPLY_PREFIX))
      .reduce((n, [, list]) => n + list.length, 0);
  assert.ok(rpcListeners() >= 1, "an unanswered request is subscribed");
  pi.emit("session_shutdown", { type: "session_shutdown" }, ctx);
  assert.ok(disposeCount >= 1, "shutdown must free an unanswered request's listener");
  assert.equal(
    rpcListeners(),
    0,
    "no RPC reply listener may survive shutdown (ledger subscriptions are long-lived by design)",
  );
});

test("C6: a terminal targeted status DEFEATS a stale running snapshot", async () => {
  // The `status` RPC returns the executor's INSPECTED status AND a separately
  // projected `asyncSnapshot` that can lag. Correlation proves which request was
  // answered, not that every fact in it is fresh, so a terminal inspection must
  // win over a snapshot still claiming `running`.
  const { rpcReplyProvesCurrentOwner } = mod;
  const request = { requestId: "r-1", method: "status" };
  const envelope = (data) => ({
    version: mod.SUBAGENT_RPC_VERSION,
    requestId: "r-1",
    method: "status",
    success: true,
    data,
  });
  const staleRunning = {
    runId: "oracle-1",
    state: "complete", // authoritative: terminal
    asyncSnapshot: { runs: [{ id: "oracle-1", state: "running" }] }, // stale projection
  };
  assert.equal(
    rpcReplyProvesCurrentOwner(envelope(staleRunning), request, "oracle-1"),
    false,
    "a terminal inspected status must not be overridden by a stale running snapshot",
  );
  // The converse still verifies: an active inspection is proof.
  const live = {
    runId: "oracle-1",
    state: "running",
    asyncSnapshot: { runs: [{ id: "oracle-1", state: "running" }] },
  };
  assert.equal(rpcReplyProvesCurrentOwner(envelope(live), request, "oracle-1"), true);
});

test("C6: a terminal details.runs inspection also defeats a stale snapshot", async () => {
  const { rpcReplyProvesCurrentOwner } = mod;
  const request = { requestId: "r-2", method: "status" };
  const envelope = (data) => ({
    version: mod.SUBAGENT_RPC_VERSION,
    requestId: "r-2",
    method: "status",
    success: true,
    data,
  });
  const contradicted = {
    details: { runs: [{ runId: "oracle-1", state: "failed" }] },
    asyncSnapshot: { runs: [{ id: "oracle-1", state: "running" }] },
  };
  assert.equal(
    rpcReplyProvesCurrentOwner(envelope(contradicted), request, "oracle-1"),
    false,
    "an inspection under details.runs outranks the projected snapshot",
  );
});

test("C6: a failed recheck retires the cached owner so repair is not suppressed", () => {
  // A recheck that discovers the run is gone must remove it from
  // `currentOwnerRuns`; otherwise `verifiedWakeOwnerExists()` keeps suppressing
  // decision repair from a run we have just learned is not alive.
  let answers = 0;
  const h = fakeClockHarness({
    states: () => {
      answers += 1;
      return answers <= 1 ? "running" : "complete"; // live, then terminal at recheck
    },
  });
  h.observeStart("oracle-1");
  h.pi.emit("session_start", { type: "session_start", reason: "reload" }, h.ctx);
  h.pi.emit("agent_settled", settleEvent(), {
    ...h.ctx,
    sessionManager: {
      getSessionFile: () => h.sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: h.branch,
    },
  });
  const capture = captureStdout();
  try {
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "the owner is live at first");
    // The recheck finds the run terminal: it must notify.
    h.advance(WAIT_RECHECK_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "a recheck that finds the run terminal must report the WAIT unverified",
    );
  } finally {
    capture.restore();
  }
});

// ---------------------------------------------------------------------------
// CORR2 D3 (ASYNC): the existing D3 regressions drive SYNCHRONOUS replies, so
// they never exercised the original failure - the recheck armed its expiry
// BEFORE the async reply arrived and re-tested proof with null inputs (always
// false), notifying even on success. These tests hold the reply, advance the
// clock past the point where the expiry is armed, and only then deliver it.
// ---------------------------------------------------------------------------

test("D3 (async): a recheck whose SUCCESSFUL reply arrives LATE still stays silent", () => {
  const h = fakeClockHarness({ states: () => "running", deferReplies: true });
  h.observeStart("oracle-1");
  h.pi.emit("session_start", { type: "session_start", reason: "reload" }, h.ctx);
  const waitCtx = {
    ...h.ctx,
    sessionManager: {
      getSessionFile: () => h.sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: h.branch,
    },
  };
  h.pi.emit("agent_settled", settleEvent(), waitCtx);
  // Answer the INITIAL verification so the WAIT is accepted and a recheck armed.
  const initial = h.heldReplies().splice(0);
  for (const entry of initial) h.deliver(entry);
  const capture = captureStdout();
  try {
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "the initial verification is silent while live");
    // Fire the RECHECK timer only. Its expiry is armed 1000ms later, and the
    // reply is deliberately left IN FLIGHT. Advancing by RECHECK-1 runs the
    // recheck itself while stopping just short of its armed expiry.
    h.advance(WAIT_RECHECK_MS - 1);
    const inFlight = h.heldReplies();
    assert.equal(inFlight.length, 1, "the recheck issued one RPC request");
    assert.deepEqual(capture.chunks, [], "the recheck has not expired yet");
    // Deliver the valid reply NOW - after the expiry was ARMED, but BEFORE it is
    // due. This is exactly the async window the old code got wrong: it armed the
    // expiry and then re-tested proof with null inputs, so even a timely success
    // notified. A timely reply is the case that must stay silent.
    h.deliver(inFlight[0]);
    assert.deepEqual(capture.chunks, [], "a timely reply must not notify");
    // Advancing past the armed deadline must still produce no notice, because the
    // successful reply cancelled the expiry.
    h.advance(2);
    assert.deepEqual(
      capture.chunks,
      [],
      "a TIMELY successful reply must cancel the armed expiry (no notice)",
    );
  } finally {
    capture.restore();
  }
});

test("D3 (async): a recheck whose reply NEVER arrives still notifies", () => {
  // Negative control for the async path: holding the reply forever must still
  // produce the unverified notice, or a dead child would stall the run.
  const h = fakeClockHarness({ states: () => "running", deferReplies: true });
  h.observeStart("oracle-1");
  h.pi.emit("session_start", { type: "session_start", reason: "reload" }, h.ctx);
  const waitCtx = {
    ...h.ctx,
    sessionManager: {
      getSessionFile: () => h.sessionFile,
      getSessionId: () => PARENT_UUID,
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: h.branch,
    },
  };
  h.pi.emit("agent_settled", settleEvent(), waitCtx);
  const initial = h.heldReplies().splice(0);
  for (const entry of initial) h.deliver(entry);
  const capture = captureStdout();
  try {
    h.advance(WAIT_VERIFICATION_MS);
    h.advance(WAIT_RECHECK_MS);
    // The recheck's reply is never delivered.
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "a recheck with no reply must still report the WAIT unverified",
    );
  } finally {
    capture.restore();
  }
});

// ---------------------------------------------------------------------------
// CORR3 scenarios: real targeted-status shape (F2), cross-process provenance
// (F3), stale owner cache (F4), and timer/listener lifecycle (F5)
// ---------------------------------------------------------------------------

test("F2: the REAL targeted-status shape is authoritative over a lagging snapshot", () => {
  // The exact assertion from the Review, as a permanent regression. The reply
  // carries the installed runtime's real shape: state in the human-readable
  // `text`, `details` with no machine `state`, and a snapshot that still says
  // `running`. A terminal authoritative report must REJECT the run.
  const request = { requestId: "review-terminal", method: "status" };
  const reply = {
    version: 1,
    ...request,
    success: true,
    data: {
      text: "Run: oracle-1\nState: complete",
      details: { mode: "single", results: [] },
      asyncSnapshot: {
        kind: "pi-subagents.async-status-snapshot",
        version: 1,
        runs: [{ id: "oracle-1", state: "running" }],
      },
    },
  };
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(reply, request, "oracle-1"),
    false,
    "a terminal targeted status defeats a stale running snapshot",
  );
});

test("F2: every real terminal state rejects, and only active states accept", () => {
  const request = { requestId: "f2-vocab", method: "status" };
  const at = (text, snapshotState) => ({
    version: 1,
    ...request,
    success: true,
    data: { text, details: { mode: "single", results: [] }, ...(snapshotState ? { asyncSnapshot: { runs: [{ id: "r", state: snapshotState }] } } : {}) },
  });
  // Active per the runtime's own `isTerminalAsyncState`: queued, running, paused.
  // PG2: ONLY queued/running are wake-capable. `paused` is deliberately NOT here:
  // an interrupted paused run is FINALIZED (`docs/extension-api.md:595`), the
  // active-run index counts only queued/running (`active-run-index.js:34-35`),
  // and `run-status.js:791-795` renders `State: paused` from a finalized
  // interrupted result. Accepting it would let an already-delivered run earn
  // silence with no future automatic wake.
  for (const active of ["queued", "running"]) {
    assert.equal(
      mod.rpcReplyProvesCurrentOwner(at(`Run: r\nState: ${active}`), request, "r"),
      true,
      `${active} is active`,
    );
  }
  // Terminal: the AsyncStatus union's terminal members, PLUS `paused`, PLUS the
  // default rule for anything unrecognized.
  for (const terminal of ["complete", "completed", "partial", "failed", "stopped", "rejected", "cancelled", "canceled", "error", "interrupted", "paused"]) {
    assert.equal(
      mod.rpcReplyProvesCurrentOwner(at(`Run: r\nState: ${terminal}`, "running"), request, "r"),
      false,
      `${terminal} is terminal and defeats a running snapshot`,
    );
  }
  // An UNRECOGNIZED state is terminal by default, so a future runtime state
  // cannot silently become an acceptance path.
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(at("Run: r\nState: brand-new-state", "running"), request, "r"),
    false,
    "an unknown state fails closed",
  );
});

test("F2: the run id in the targeted report must match EXACTLY, never by prefix", () => {
  const request = { requestId: "f2-prefix", method: "status" };
  // No snapshot at all: the targeted report is the ONLY evidence, so a
  // non-matching id must leave the run unproven rather than matching by prefix.
  const reply = (runLine, state) => ({
    version: 1,
    ...request,
    success: true,
    data: { text: `Run: ${runLine}\nState: ${state}`, details: { mode: "single", results: [] } },
  });
  assert.equal(mod.rpcReplyProvesCurrentOwner(reply("oracle-1", "running"), request, "oracle-1"), true, "exact id accepts");
  assert.equal(mod.rpcReplyProvesCurrentOwner(reply("oracle", "running"), request, "oracle-1"), false, "a shorter targeted id is not a prefix match");
  assert.equal(mod.rpcReplyProvesCurrentOwner(reply("oracle-1-extra", "running"), request, "oracle-1"), false, "a longer targeted id is not a prefix match");
  // A longer id that IS terminal must also not veto the requested run.
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(reply("oracle-1-extra", "complete"), request, "oracle-1"),
    false,
    "without any report for the requested run, the reply stays unproven",
  );
});

test("F2: a targeted report naming a DIFFERENT run does not become proof via the snapshot", () => {
  // PG3: a reply produced by an EXACT-TARGET verification (`{runId}`) that fails
  // to name the requested run is an UNINFORMATIVE answer. Consulting the
  // projected snapshot here is precisely how a finalized run kept earning
  // silence: its targeted inspection stopped reporting it, the answer named some
  // other run, and the display cache still said `running`. Absence of an
  // authoritative ACTIVE report is never proof, so this fails closed.
  const request = { requestId: "f2-other", method: "status" };
  const reply = {
    version: 1,
    ...request,
    success: true,
    data: {
      text: "Run: some-other-run\nState: complete",
      details: { mode: "single", results: [] },
      asyncSnapshot: { runs: [{ id: "oracle-1", state: "running" }] },
    },
  };
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(reply, request, "oracle-1"),
    false,
    "a report for a DIFFERENT run leaves the requested run unproven (the lagging snapshot is not proof)",
  );
  // The mirror case: the reply names ANOTHER run actively. That is still not
  // proof for the requested run either.
  const otherActive = {
    version: 1,
    ...request,
    success: true,
    data: {
      text: "Run: some-other-run\nState: running",
      details: { mode: "single", results: [] },
    },
  };
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(otherActive, request, "oracle-1"),
    false,
    "another run being active says nothing about the requested run",
  );
});

test("PG3: the reviewer's four bypass cases all fail closed", () => {
  // The exact assertion from Oracle `2d5dfda0`, kept as a permanent regression
  // test. Each case previously returned `true`.
  const request = { requestId: "corr3-review", method: "status" };
  const cases = [
    { text: "Run: r\nState: paused", details: { mode: "single", results: [] } },
    { text: "Run: other\nState: complete", asyncSnapshot: { runs: [{ id: "r", state: "running" }] } },
    { text: "Run: r\nState: complete", runId: "r", state: "running" },
    { text: "Run: r\nState: complete", details: { runs: [{ id: "r", state: "running" }] } },
  ];
  assert.deepEqual(
    cases.map((data) => mod.rpcReplyProvesCurrentOwner({ version: 1, ...request, success: true, data }, request, "r")),
    [false, false, false, false],
    "paused is not liveness, and a terminal report is never overridden by an active field",
  );
});

test("F2: an active targeted report outranks a stale terminal snapshot", () => {
  const request = { requestId: "f2-active-first", method: "status" };
  const reply = {
    version: 1,
    ...request,
    success: true,
    data: {
      text: "Run: r\nState: running",
      details: { mode: "single", results: [] },
      asyncSnapshot: { runs: [{ id: "r", state: "stopped" }] },
    },
  };
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(reply, request, "r"),
    true,
    "the authoritative targeted report is consulted before the projection",
  );
});

test("F3: a provenance record from a FOREIGN runtime instance cannot corroborate a WAIT", () => {
  // The CORE cross-process case. Same session file, same uuid, reopened in
  // another process: the uuid matches and restoration re-stamps the current
  // epoch, so ONLY the runtime-instance binding can refuse the inherited trust.
  const first = fakeClockHarness();
  first.observeStart("oracle-1");
  const carried = first.persisted;
  assert.equal(carried.filter((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE).length, 1);
  assert.equal(
    typeof carried.find((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE).data.runtimeInstanceId,
    "string",
    "the witnessing instance id is persisted",
  );

  // A reload in a DIFFERENT process: same entries, different runtime instance.
  const reloaded = fakeClockHarness({ entries: carried });
  const original = mod.currentRuntimeInstanceId();
  try {
    mod.setRuntimeInstanceIdForTests("rt-different-process");
    reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  } finally {
    mod.setRuntimeInstanceIdForTests(original);
  }
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "restored provenance from another process must NOT earn silence",
    );
  } finally {
    capture.restore();
  }
});

test("F3: a SAME-process reload still corroborates, so the binding is not a blanket block", () => {
  const first = fakeClockHarness();
  first.observeStart("oracle-1");
  const carried = first.persisted;

  // Same process: the harness inherits the live runtime instance id, so the
  // restore admits the record and the live bridge reply proves the WAIT.
  const reloaded = fakeClockHarness({ entries: carried });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "a same-process reload with a live owner stays silent");
  } finally {
    capture.restore();
  }
});

test("R6-6: a reload during a LATER request does not revive previous-request corroboration", () => {
  // The exact R6-6 attack. Request A witnesses run `oracle-1` and persists a
  // provenance record. A NEW request B then opens a fresh generation WITHOUT
  // witnessing any run. A `/reload` landing during B used to re-stamp A's record
  // into the current epoch, making it eligible again with no new START - silently
  // restoring WAIT corroboration the user's own new request had already rejected.
  //
  // DISCRIMINATING LIMIT (R7-6, disclosed by the fixer): at the PIPELINE level
  // this pair is not independently discriminating - the live-epoch check inside
  // `provenanceBelongsToSession` masks the restore gate, so this test can pass
  // even if the restore gate alone were broken. The gate's own negative/current/
  // absent-marker assertions are what make the R6-6 proof real; see the
  // `latestPersistedGeneration` / `provenanceAdmissibleForRequest` unit tests.
  const first = fakeClockHarness();
  first.observeStart("oracle-1");
  const record = first.persisted.find((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
  assert.ok(record !== undefined, "A persisted a provenance record");
  const witnessedEpoch = record.data.requestEpoch;

  // Request B on the SAME harness: a genuine interactive input opens the NEXT
  // request generation and persists it, with no run witnessed in B.
  first.pi.emit("input", { type: "input", text: "new ask", source: "interactive" }, first.ctx);
  const latestGeneration = mod.latestPersistedGeneration(first.persisted, mod.currentRuntimeInstanceId());
  assert.ok(latestGeneration !== null, "a request generation is persisted");
  assert.ok(
    latestGeneration > witnessedEpoch,
    "request B opens a generation BEYOND the one that witnessed the run",
  );

  // The persisted evidence now DISCRIMINATES: the record belongs to the OLDER
  // request, so it must not be admissible for the current one.
  assert.notEqual(
    record.data.requestEpoch,
    latestGeneration,
    "the superseded record's epoch differs from the request now in progress",
  );

  // Reload during B. `states: () => "running"` makes the bridge report the run
  // as CURRENTLY LIVE, so liveness alone would accept this WAIT.
  const reloaded = fakeClockHarness({ entries: first.persisted, states: () => "running" });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "a superseded request's record must not corroborate a WAIT after a reload",
    );
  } finally {
    capture.restore();
  }
});

test("R6-6 control: a SAME-request reload keeps its record eligible (pipeline-level companion; see the note on the test above)", () => {
  // The positive control for the test above. Identical setup and identical LIVE
  // bridge, but NO intervening request B - so the persisted generation still
  // matches the record. The WAIT must stay SILENT. Together the pair isolates the
  // generation gate: same bridge, same record shape, opposite outcome decided
  // only by whether a later request superseded the record.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  const latestGeneration = mod.latestPersistedGeneration(first.persisted, mod.currentRuntimeInstanceId());
  const record = first.persisted.find((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
  assert.equal(
    record.data.requestEpoch,
    latestGeneration,
    "without a later request the record still belongs to the current generation",
  );

  const reloaded = fakeClockHarness({ entries: first.persisted, states: () => "running" });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [],
      "a same-request reload with a live owner stays silent",
    );
  } finally {
    capture.restore();
  }
});

test("R6-6: the restore gate rejects a record from a superseded request generation", () => {
  // The gate itself, via the SHARED predicate the handler uses, so removing the
  // production check makes this test fail. The pipeline-level pair above proves
  // the observable consequence.
  const domain = mod.currentRuntimeInstanceId();
  const entries = [
    { type: "custom", customType: mod.PROVENANCE_CUSTOM_TYPE, data: { version: 1, runId: "R", agent: "oracle", asyncDir: null, sessionUuid: "u", requestEpoch: 1, runtimeInstanceId: domain, terminal: false, deliveryCapable: true } },
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 2, domain } },
  ];
  const latest = mod.latestPersistedGeneration(entries, domain);
  assert.equal(latest, 2, "the persisted generation is the LATER request");
  const restored = [...mod.restoreProvenance(entries).values()];
  assert.equal(restored.length, 1, "the raw record is still parsed");
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration(restored[0], latest),
    false,
    "a superseded-generation record must NOT be admissible",
  );

  // Control: a record carrying the CURRENT generation IS admissible. This
  // isolates the gate from every other condition (session uuid, instance id).
  const current = { ...restored[0], requestEpoch: 2 };
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration(current, latest),
    true,
    "a current-generation record IS admissible",
  );

  // Fail-closed: with no generation marker nothing is admissible, so legacy or
  // truncated evidence cannot claim a wake path.
  assert.equal(
    mod.latestPersistedGeneration([{ ...entries[0] }], domain),
    null,
    "no marker means no admissible generation",
  );
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration(restored[0], null),
    false,
    "an absent generation marker is fail-closed",
  );
});

test("CORR10/NEW-1: a fresh process's generation is not displaced by a historical counter from another process", () => {
  // The exact reviewer probe. A persisted branch holds generation 100 from an
  // EARLIER process; reopening it restarts the local counter at 1; a genuine new
  // request records generation 2; a reload must select the CURRENT "domain"'s
  // latest (2), not the historical maximum (100), or a valid generation-2
  // provenance is falsely rejected and 100 is adopted.
  const domain = mod.currentRuntimeInstanceId();
  const entries = [
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 100, domain: "foreign-process" } },
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 1, domain } },
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 2, domain } },
  ];
  const latest = mod.latestPersistedGeneration(entries, domain);
  assert.equal(latest, 2, "the current domain's latest generation wins over a foreign historical maximum");
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration({ requestEpoch: 2 }, latest),
    true,
    "a genuinely fresh run's generation-2 provenance IS admitted",
  );
  // Previous-request invalidation is PRESERVED within the current domain: an
  // older same-domain generation stays ineligible.
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration({ requestEpoch: 1 }, latest),
    false,
    "an older same-domain generation is still rejected (invalidation preserved)",
  );
  // A marker with no domain (legacy/truncated) is fail-closed, exactly like an
  // absent generation marker.
  assert.equal(
    mod.latestPersistedGeneration([{ type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 5 } }], domain),
    null,
    "a marker with no domain cannot claim this process's latest generation",
  );
});

test("CORR10/NEW-1: an end-to-end reload admits a fresh run despite a foreign historical generation", () => {
  // Pipeline-level companion: the persisted branch carries a FOREIGN generation
  // 100 marker. A live bridge confirms the run, so ONLY the wrong generation
  // selection would falsely reject it. The WAIT must stay silent.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  const carried = [
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 100, domain: "foreign-process" } },
    ...first.persisted,
  ];
  const reloaded = fakeClockHarness({ entries: carried, states: () => "running" });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: reloaded.branch },
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [],
      "a foreign historical generation must not falsely reject a fresh, live run's WAIT",
    );
  } finally {
    capture.restore();
  }
});

test("CORR11/NEW-1: a same-process COUNTER RESTART is a new lineage; a stale higher generation does not outrank it", () => {
  // The CORR11 defect: the counter is REGISTRATION-local and resets to 0 on
  // every module re-evaluation, so a SINGLE process/domain can persist more than
  // one counter lineage. An earlier registration wrote generation 100; a later
  // registration (a fresh non-continuing `session_start` on an already-used
  // branch, which resets the counter WITHOUT restoring) wrote 1 then 2. A plain
  // same-domain maximum selects 100 and rejects the genuinely current
  // generation-2 run - the exact failure CORR10 fixed, one level in.
  const domain = mod.currentRuntimeInstanceId();
  const entries = [
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 100, domain } },
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 1, domain } },
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 2, domain } },
  ];
  const latest = mod.latestPersistedGeneration(entries, domain);
  assert.equal(latest, 2, "the CURRENT counter lineage's latest generation wins over the stale higher one");
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration({ requestEpoch: 2 }, latest),
    true,
    "a genuinely live run witnessed by the CURRENT lineage IS admitted",
  );
  // R2: within the current lineage the counter still strictly increases and the
  // latest generation still invalidates earlier requests.
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration({ requestEpoch: 1 }, latest),
    false,
    "an older generation in the SAME lineage is still rejected (invalidation preserved)",
  );
  assert.equal(
    mod.latestPersistedGeneration(
      [
        { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 1, domain } },
        { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 2, domain } },
        { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 3, domain } },
      ],
      domain,
    ),
    3,
    "a single strictly-increasing lineage still selects its maximum",
  );
  // R3 control: a FOREIGN process's high marker still cannot outrank this
  // process's lineage, and the restart rule is applied WITHIN this domain only.
  assert.equal(
    mod.latestPersistedGeneration(
      [
        { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 100, domain: "foreign-process" } },
        { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 1, domain } },
        { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 2, domain } },
      ],
      domain,
    ),
    2,
    "a foreign domain marker is ignored entirely, not treated as a restart",
  );
  // Multiple restarts: only the LAST lineage counts.
  assert.equal(
    mod.latestPersistedGeneration(
      [1, 2, 3].map((g) => ({ type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: g, domain } })).concat(
        [1, 2].map((g) => ({ type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: g, domain } })),
      ),
      domain,
    ),
    2,
    "with multiple restarts only the newest lineage's maximum is selected",
  );
});

test("CORR11/NEW-1: an end-to-end reload admits a live run after a same-process counter restart", () => {
  // Pipeline-level companion to the unit test above. The persisted branch carries
  // a STALE same-domain generation 100 from an EARLIER registration, then the
  // current registration's generations 1 and 2. A live bridge confirms the run,
  // so ONLY the wrong lineage selection would falsely reject it. The WAIT must
  // stay silent.
  const domain = mod.currentRuntimeInstanceId();
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  const stale = [
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 100, domain } },
    ...first.persisted,
  ];
  const reloaded = fakeClockHarness({ entries: stale, states: () => "running" });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: reloaded.branch },
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [],
      "a stale same-process generation must not falsely reject a fresh, live run's WAIT",
    );
  } finally {
    capture.restore();
  }
});

test("CORR11/NEW-1 (R4): the R9-2 non-continuing scope gate is unchanged by the lineage fix", async () => {
  // R4 guard: the lineage fix must NOT be implemented by rejecting/suppressing
  // same-UUID NON-CONTINUING startups. A `startup` resets the counter (writes a
  // NEW, LOWER lineage) and inherits nothing; a genuine BLOCKED escalation on
  // that branch still runs through decision repair, exactly as R9-2 requires.
  const dir = makeAsyncDir({ dir: "/async/oracle-corr11", result: oracleResult({ dependencyId: "dep-1" }) });
  const files = new Map(dir.files);
  // A witness registration crosses a request boundary, then a stale HIGHER
  // same-domain generation from an earlier registration is present in the
  // branch, followed by the current registration's fresh generations.
  const first = fakeClockHarness({ states: () => "complete", files });
  first.pi.emit("input", { type: "input", text: "go", source: "interactive" }, first.ctx);
  first.observeStart("oracle-1", "oracle", dir.dir);
  const domain = mod.currentRuntimeInstanceId();
  const branch = [
    { type: "custom", customType: mod.REQUEST_GENERATION_CUSTOM_TYPE, data: { version: 1, generation: 100, domain } },
    ...first.persisted,
  ];
  const h = fakeClockHarness({ states: () => "complete", entries: branch, files });
  h.pi.emit("session_start", { type: "session_start", reason: "startup" }, h.ctx);
  const result = await handlerFor(h.pi, "agent_before_settle")(
    boundaryEvent([assistant(BLOCKED_USER("oracle-1", "dep-1"))]),
    h.ctx,
  );
  assert.equal(result?.continue, true, "a non-continuing session_start must still repair");
  assert.equal(
    result?.entries?.at(-1)?.customType,
    mod.REPAIR_CUSTOM_TYPE,
    "the escalation is a decision repair, never silent acceptance",
  );
});

test("CORR12/NEW-1: a superseded registration's numerically equal epoch cannot resurrect provenance across a reload", async () => {
  // AC-CORR12-1: the EXACT handler-level probe sequence from cycle-15 P1.
  //
  //   A witnesses `oracle-1` at epoch 1, then a genuine replacement advances A
  //   to epoch 2 (the numeric stream becomes [1,1,2]).
  //   B starts NON-CONTINUINGLY on the carried branch and writes epoch 1 - a
  //   counter RESTART - so the stream is [1,1,2,1] and the old epoch-1 record is
  //   numerically indistinguishable from B's epoch-1 scope.
  //   B correctly REPAIRS the escalation.
  //   C RELOADS B's branch. Under the old value-stream heuristic
  //   `latestPersistedGeneration` selects 1, re-admits A's old epoch-1 record,
  //   and the SAME escalation is silently ACCEPTED. With an explicit lineage
  //   token the old record belongs to A's token, is NOT admitted, and the repair
  //   STILL fires.
  const dir = makeAsyncDir({ dir: "/async/oracle-corr12", result: oracleResult({ dependencyId: "dep-1" }) });
  const files = new Map(dir.files);
  const b = () => boundaryEvent([assistant(BLOCKED_USER("oracle-1", "dep-1"))]);

  // A: witness the run at epoch 1, then a genuine interrupt advances to epoch 2.
  const first = fakeClockHarness({ states: () => "complete", files });
  first.pi.emit("input", { type: "input", text: "go", source: "interactive" }, first.ctx);
  first.observeStart("oracle-1", "oracle", dir.dir);
  first.pi.emit("input", { type: "input", text: "new ask", source: "interactive" }, first.ctx);

  // B: non-continuing startup on the carried branch, writing epoch 1 again.
  const fresh = fakeClockHarness({ states: () => "complete", entries: first.persisted, files });
  fresh.pi.emit("session_start", { type: "session_start", reason: "startup" }, fresh.ctx);
  const before = await handlerFor(fresh.pi, "agent_before_settle")(b(), fresh.ctx);
  assert.equal(
    before?.entries?.at(-1)?.customType,
    mod.REPAIR_CUSTOM_TYPE,
    "B repairs the escalation on the non-continuing branch",
  );

  // The numeric stream is exactly the probe's [1,1,2,1] - the collision case.
  const generations = fresh.persisted
    .filter((e) => e.customType === mod.REQUEST_GENERATION_CUSTOM_TYPE)
    .map((e) => e.data.generation);
  assert.deepEqual(generations, [1, 1, 2, 1], "the persisted generation stream is the probe's [1,1,2,1]");

  // C: reload B's branch. The old epoch-1 record must NOT be admitted.
  const after = fakeClockHarness({ states: () => "complete", entries: fresh.persisted, files });
  after.pi.emit("session_start", { type: "session_start", reason: "reload" }, after.ctx);
  const result = await handlerFor(after.pi, "agent_before_settle")(b(), after.ctx);
  assert.equal(
    result?.entries?.at(-1)?.customType,
    mod.REPAIR_CUSTOM_TYPE,
    "after the reload the SAME escalation STILL repairs (superseded epoch-1 provenance is not resurrected)",
  );
});

test("CORR12/NEW-1: the lineage token excludes a numerically equal superseded epoch (unit)", () => {
  // AC-CORR12-1 at the selection/predicate level, using the REAL persisted shape
  // (records and markers carry a lineage token). Two registrations share the SAME
  // process domain and the SAME numeric epoch 1; only the token distinguishes
  // them.
  const domain = mod.currentRuntimeInstanceId();
  const marker = (generation, lineage) => ({
    type: "custom",
    customType: mod.REQUEST_GENERATION_CUSTOM_TYPE,
    data: { version: 1, generation, domain, lineage },
  });
  const record = (epoch, lineage) => ({
    type: "custom",
    customType: mod.PROVENANCE_CUSTOM_TYPE,
    data: { version: 2, runId: "oracle-1", agent: "oracle", asyncDir: null, sessionUuid: "u", requestEpoch: epoch, runtimeInstanceId: domain, terminal: false, deliveryCapable: true, lineage },
  });
  const entries = [
    record(1, "ln-A"),
    marker(1, "ln-A"),
    marker(2, "ln-A"),
    marker(1, "ln-B"),
  ];
  const current = mod.currentLineageGeneration(entries, domain);
  assert.deepEqual(
    current,
    { lineage: "ln-B", generation: 1 },
    "the LAST marker's lineage is current; its generation is the max within that lineage",
  );
  const restored = [...mod.restoreProvenance(entries).values()];
  assert.equal(restored.length, 1, "the record is still parsed");
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration(restored[0], current.generation, current.lineage),
    false,
    "the superseded registration's epoch-1 record is NOT admitted",
  );
  // Control: a record carrying the CURRENT lineage and epoch IS admitted.
  const currentRecord = { requestEpoch: 1, lineage: "ln-B" };
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration(currentRecord, current.generation, current.lineage),
    true,
    "a current-lineage, current-epoch record IS admitted",
  );
  // R2 within the current lineage: an older epoch of the SAME token is rejected.
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration({ requestEpoch: 2, lineage: "ln-B" }, 1, "ln-B"),
    false,
    "previous-request invalidation within a lineage is preserved",
  );
});

test("CORR12/NEW-1 (AC-CORR12-3): a genuine new registration gets a distinct lineage and inherits nothing", () => {
  // A record persisted by one registration must not be admitted by a genuinely
  // new registration - neither a new PROCESS (different domain, R3) nor a
  // non-continuing startup on the same branch (different lineage token).
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  const record = first.persisted.find((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
  assert.ok(record, "A persisted a provenance record");
  const tokenA = record.data.lineage;
  assert.equal(typeof tokenA, "string");
  assert.ok(tokenA.length > 0, "A wrote a non-empty lineage token");

  // A distinct NEW PROCESS re-reads the branch: a different domain yields no
  // current lineage, so nothing is admissible and the freshly-minted token is
  // kept.
  const original = mod.currentRuntimeInstanceId();
  mod.setRuntimeInstanceIdForTests("rt-corr12-new-process");
  try {
    const current = mod.currentLineageGeneration(first.persisted, mod.currentRuntimeInstanceId());
    assert.equal(current, null, "a new process's domain matches no persisted marker");
  } finally {
    mod.setRuntimeInstanceIdForTests(original);
  }

  // A non-continuing startup on the SAME branch: the branch's last marker still
  // names A's lineage, but a NON-continuing start must not adopt it - and the
  // new registration mints a token distinct from A's.
  const h = fakeClockHarness({ states: () => "running", entries: first.persisted });
  h.pi.emit("session_start", { type: "session_start", reason: "startup" }, h.ctx);
  const newMarker = h.persisted[h.persisted.length - 1];
  assert.equal(newMarker.customType, mod.REQUEST_GENERATION_CUSTOM_TYPE);
  assert.notEqual(newMarker.data.lineage, tokenA, "a non-continuing startup opens a distinct lineage");
});

test("CORR12/NEW-1 (AC-CORR12-4): LEGACY records without a lineage do not resurrect superseded provenance", () => {
  // A version-1 provenance record (no `lineage`) must never be admitted as
  // current-lineage provenance. Documented behaviour: it parses with an EMPTY
  // lineage, which cannot equal a live token, so it is fail-closed.
  const domain = mod.currentRuntimeInstanceId();
  const legacyRecord = {
    type: "custom",
    customType: mod.PROVENANCE_CUSTOM_TYPE,
    data: { version: 1, runId: "oracle-1", agent: "oracle", asyncDir: null, sessionUuid: "u", requestEpoch: 1, runtimeInstanceId: domain, terminal: false, deliveryCapable: true },
  };
  const tokenMarker = {
    type: "custom",
    customType: mod.REQUEST_GENERATION_CUSTOM_TYPE,
    data: { version: 1, generation: 1, domain, lineage: "ln-current" },
  };
  const current = mod.currentLineageGeneration([legacyRecord, tokenMarker], domain);
  assert.deepEqual(current, { lineage: "ln-current", generation: 1 }, "a token marker sets the current lineage");
  const restored = [...mod.restoreProvenance([legacyRecord, tokenMarker]).values()];
  assert.equal(restored[0].lineage, "", "a version-1 legacy record parses with an empty lineage");
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration(restored[0], current.generation, current.lineage),
    false,
    "a legacy record cannot be admitted as current-lineage provenance",
  );
  // CORR13/NEW-1: on a PURE-legacy branch (no token anywhere) the numeric
  // fallback no longer uses `""` as an identity token. It reports the explicit
  // `LEGACY_NO_LINEAGE_SENTINEL`, which a legacy record (parsed lineage `""`)
  // never equals, so NO legacy record is admitted. This CORRECTS the cycle-16
  // P1-legacy defect: the old `"" === ""` equality re-admitted a SUPERSEDED
  // registration's legacy record after a same-process reload, because a
  // restarted counter makes its epoch numerically indistinguishable from the
  // current registration's. With no token and a restarted counter there is no
  // sound narrower set, so the admissible set on a legacy branch is EMPTY.
  const legacyMarker = {
    type: "custom",
    customType: mod.REQUEST_GENERATION_CUSTOM_TYPE,
    data: { version: 1, generation: 1, domain },
  };
  const legacyCurrent = mod.currentLineageGeneration([legacyRecord, legacyMarker], domain);
  assert.deepEqual(
    legacyCurrent,
    { lineage: mod.LEGACY_NO_LINEAGE_SENTINEL, generation: 1 },
    "a legacy-only branch yields the explicit, non-empty legacy sentinel (never `\"\"`)",
  );
  assert.notEqual(legacyCurrent.lineage, "", "the legacy sentinel is NOT the empty string");
  assert.equal(
    mod.provenanceBelongsToCurrentGeneration(restored[0], legacyCurrent.generation, legacyCurrent.lineage),
    false,
    "a legacy record is NOT admitted even on a pure-legacy branch (fail-closed against superseded resurrection)",
  );
});

test("CORR13: a pre-CORR12 (legacy) branch reload does not resurrect superseded provenance", async () => {
  // REGRESSION for cycle-16 P1-legacy, driven through the REAL exported handlers
  // (no native run), reusing the CORR12 handler-test harness EXACTLY.
  //
  //   A witnesses `oracle-1` at epoch 1, then a genuine interrupt advances A to
  //   epoch 2 - the numeric stream becomes [1,1,2].
  //   B starts NON-CONTINUINGLY on the carried branch and writes epoch 1 (a
  //   counter restart), so the stream is [1,1,2,1] and A's old epoch-1 record is
  //   numerically indistinguishable from B's epoch-1 scope. B correctly REPAIRS
  //   the escalation.
  //   C RELOADS the branch, but the branch is CLONED to PRE-CORR12 shape: every
  //   marker and provenance record has its `lineage` removed (records drop to
  //   version 1).
  //
  // On the DEFECTIVE code, `currentLineageGeneration` returned the empty-string
  // sentinel for this legacy branch and a legacy record parses with lineage
  // `""`, so `"" === ""` re-admitted A's SUPERSEDED epoch-1 record. The escalation
  // was then silently ACCEPTED (`undefined`) instead of repaired. With the
  // explicit `LEGACY_NO_LINEAGE_SENTINEL`, no legacy record is admissible and the
  // repair STILL fires after the reload.
  const dir = makeAsyncDir({ dir: "/async/oracle-corr13", result: oracleResult({ dependencyId: "dep-1" }) });
  const files = new Map(dir.files);
  const b = () => boundaryEvent([assistant(BLOCKED_USER("oracle-1", "dep-1"))]);

  // A: witness the run at epoch 1, then a genuine interrupt advances to epoch 2.
  const first = fakeClockHarness({ states: () => "complete", files });
  first.pi.emit("input", { type: "input", text: "go", source: "interactive" }, first.ctx);
  first.observeStart("oracle-1", "oracle", dir.dir);
  first.pi.emit("input", { type: "input", text: "new ask", source: "interactive" }, first.ctx);

  // B: non-continuing startup on the carried branch, writing epoch 1 again.
  const fresh = fakeClockHarness({ states: () => "complete", entries: first.persisted, files });
  fresh.pi.emit("session_start", { type: "session_start", reason: "startup" }, fresh.ctx);
  const before = await handlerFor(fresh.pi, "agent_before_settle")(b(), fresh.ctx);
  assert.equal(
    before?.entries?.at(-1)?.customType,
    mod.REPAIR_CUSTOM_TYPE,
    "B repairs the escalation on the non-continuing branch",
  );

  // The numeric stream is the probe's [1,1,2,1] - the collision case.
  const generations = fresh.persisted
    .filter((e) => e.customType === mod.REQUEST_GENERATION_CUSTOM_TYPE)
    .map((e) => e.data.generation);
  assert.deepEqual(generations, [1, 1, 2, 1], "the persisted generation stream is the probe's [1,1,2,1]");

  // Clone B's branch to PRE-CORR12 shape: drop `lineage` from every marker, and
  // downgrade provenance records to version 1 with `lineage` removed. NOTE the
  // spread order: `rest` still carries the source record's `version: 2`, so the
  // downgrade MUST come last or the fixture silently stays version 2 (T1).
  const legacyBranch = fresh.persisted.map((entry) => {
    if (entry.customType === mod.PROVENANCE_CUSTOM_TYPE) {
      const { lineage: _dropRecord, ...rest } = entry.data;
      return { ...entry, data: { ...rest, version: 1 } };
    }
    if (entry.customType === mod.REQUEST_GENERATION_CUSTOM_TYPE) {
      const { lineage: _dropMarker, ...rest } = entry.data;
      return { ...entry, data: rest };
    }
    return entry;
  });
  assert.ok(
    legacyBranch.every(
      (e) =>
        e.customType !== mod.REQUEST_GENERATION_CUSTOM_TYPE ||
        !("lineage" in e.data),
    ),
    "the cloned branch is genuinely pre-CORR12: no marker carries a lineage",
  );

  // T1 GUARD: assert the fixture's OWN shape, not merely the marker lineage.
  // The provenance downgrade must actually be version 1 with no lineage; the
  // spread order above is easy to get backwards (see the comment there).
  const clonedProvenance = legacyBranch.filter(
    (e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE,
  );
  assert.ok(
    clonedProvenance.length > 0,
    "the cloned branch still carries provenance records to downgrade",
  );
  assert.ok(
    clonedProvenance.every((e) => e.data.version === 1),
    "T1: every cloned provenance record is genuinely VERSION 1 (pre-CORR12)",
  );
  assert.ok(
    clonedProvenance.every((e) => !("lineage" in e.data)),
    "T1: every cloned provenance record genuinely has NO lineage field",
  );

  // C: reload the LEGACY branch. A's superseded epoch-1 record must NOT be
  // admitted, so the SAME escalation STILL repairs.
  const after = fakeClockHarness({ states: () => "complete", entries: legacyBranch, files });
  after.pi.emit("session_start", { type: "session_start", reason: "reload" }, after.ctx);
  const result = await handlerFor(after.pi, "agent_before_settle")(b(), after.ctx);
  assert.equal(
    result?.entries?.at(-1)?.customType,
    mod.REPAIR_CUSTOM_TYPE,
    "after the legacy-branch reload the SAME escalation STILL repairs (superseded legacy provenance is not resurrected)",
  );
});

test("CORR12: a same-process reload RECOVERS its registration lineage, so the reloaded registration's own WAIT survives a LATER reload", () => {
  // LOAD-BEARING COVERAGE for the reload-survival recovery ASSIGNMENT itself
  // (`session-supervisor.ts:4086`):
  //   `if (current !== null && current.lineage !== LEGACY_NO_LINEAGE_SENTINEL) lineageToken = current.lineage;`
  //
  // It is NOT covered by the CORR12 predicate tests (which call
  // `currentLineageGeneration` / `provenanceBelongsToCurrentGeneration` DIRECTLY)
  // nor by the single-reload pipeline tests: at the pipeline level the ONE
  // reload's own restoration admits the record via `current?.lineage` directly,
  // so a fresh (unrecovered) token never has to match anything yet. Delete the
  // assignment above and those tests stay green.
  //
  // This test reaches the assignment through the REAL registration path. A
  // native `/reload` re-evaluates the module with `moduleCache:false`, minting a
  // FRESH token per registration; the recovery rebinds the reloaded registration
  // to the PERSISTED lineage. The discriminating consequence only shows up on a
  // SECOND reload: the reloaded registration has by then STAMPED its token on a
  // new marker, and only a RECOVERED token keeps the earlier record's lineage
  // current. If the recovery is missing, the second reload's current lineage is
  // the fresh token, the earlier record is excluded, and the live WAIT is
  // wrongly reported unverified.

  // Registration A witnesses `oracle-1` and persists provenance under A's token.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  const recordA = first.persisted.find((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
  assert.ok(recordA, "A persisted provenance for oracle-1");
  const persistedToken = recordA.data.lineage;
  assert.equal(typeof persistedToken, "string", "A's record carries its registration lineage");
  assert.ok(persistedToken.length > 0, "A's lineage token is non-empty");

  // Reload #1 = registration B. The `sessionManager` must provide BOTH the
  // WAIT projection (`buildSessionProjection`) AND the persisted branch
  // (`getBranch`), or the restore path reads no entries and recovers nothing -
  // the restart-only `sessionView` helper is deliberately insufficient here.
  const reload1 = fakeClockHarness({ states: () => "running", entries: first.persisted });
  reload1.pi.emit("session_start", { type: "session_start", reason: "reload" }, {
    ...reload1.ctx,
    sessionManager: {
      buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
      getBranch: reload1.branch,
    },
  });
  // B witnesses a SECOND run AFTER the reload, stamping its (recovered) token on
  // the new provenance record and generation marker.
  reload1.observeStart("oracle-2");
  const recordB2 = reload1.persisted
    .filter((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE)
    .find((e) => e.data.runId === "oracle-2");
  assert.ok(recordB2, "B witnessed oracle-2");
  // THE LOAD-BEARING ASSERTION: the reloaded registration's token must EQUAL the
  // persisted lineage. A freshly-minted token (the value `moduleCache:false`
  // would produce without recovery) is astronomically unlikely to collide and
  // would differ here, so this assertion is what pins the recovery.
  assert.equal(
    recordB2.data.lineage,
    persistedToken,
    "the reloaded registration RECOVERED the persisted lineage token rather than keeping its fresh mint",
  );
  const lastMarker = reload1.persisted
    .filter((e) => e.customType === mod.REQUEST_GENERATION_CUSTOM_TYPE)
    .at(-1);
  assert.equal(
    lastMarker?.data.lineage,
    persistedToken,
    "the post-reload marker also carries the RECOVERED token (so the persisted lineage stays current)",
  );

  // Reload #2 = registration C, WAIT on the run A witnessed (`oracle-1`). The
  // branch's LAST marker now names the token B used. Only when B RECOVERED the
  // token does C's current lineage equal `oracle-1`'s record token, so the
  // restored provenance corroborates the live bridge and the WAIT stays SILENT.
  // With the recovery deleted, B kept its fresh token, C's current lineage is
  // that fresh token, oracle-1's record is excluded, and the WAIT is wrongly
  // reported unverified.
  const reload2 = fakeClockHarness({ states: () => "running", entries: reload1.persisted });
  const capture = captureStdout();
  try {
    reload2.pi.emit("session_start", { type: "session_start", reason: "reload" }, {
      ...reload2.ctx,
      sessionManager: {
        buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }),
        getBranch: reload2.branch,
      },
    });
    reload2.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [],
      "a later reload still corroborates the original WAIT because the recovered lineage survived",
    );
  } finally {
    capture.restore();
  }
});

test("CORR10/NEW-3: matching OBSERVED process termination rejects; pending does NOT", () => {
  // The liveness predicate must consume the runtime's independently observed
  // process-exit evidence: a reply can name the exact run, report `State:
  // running`, AND carry `details.lifecycleStatus.processTerminal` observed
  // termination for that SAME run. That is terminal evidence and must reject.
  const { rpcReplyProvesCurrentOwner } = mod;
  const request = { requestId: "r-pt", method: "status" };
  const envelope = (data) => ({
    version: mod.SUBAGENT_RPC_VERSION,
    requestId: "r-pt",
    method: "status",
    success: true,
    data,
  });
  const observed = {
    version: 1,
    state: "observed",
    runId: "oracle-1",
    runnerProcessInstanceId: "runner-9",
    observedAt: 123,
    instances: [{ kind: "runner", processInstanceId: "runner-9", exitCode: 0 }],
  };
  assert.equal(
    rpcReplyProvesCurrentOwner(
      envelope(rpcTargetedStatus("oracle-1", "running", { processTerminal: observed })),
      request,
      "oracle-1",
    ),
    false,
    "matching observed process termination must REJECT a run reported running",
  );
  // CRITICAL control: `pending` is the valid live case and must stay accepted.
  assert.equal(
    rpcReplyProvesCurrentOwner(
      envelope(rpcTargetedStatus("oracle-1", "running", { processTerminal: { version: 1, state: "pending", runId: "oracle-1", runnerProcessInstanceId: "runner-9" } })),
      request,
      "oracle-1",
    ),
    true,
    "a pending process-terminal field must NOT reject a live run",
  );
  // An observed termination for a DIFFERENT run must not reject this one.
  assert.equal(
    rpcReplyProvesCurrentOwner(
      envelope(rpcTargetedStatus("oracle-1", "running", { processTerminal: { ...observed, runId: "other-run" } })),
      request,
      "oracle-1",
    ),
    true,
    "observed termination for a different run must not reject this run",
  );
  // `unknown`/`not-started` are inconclusive and must not reject either.
  assert.equal(
    rpcReplyProvesCurrentOwner(
      envelope(rpcTargetedStatus("oracle-1", "running", { processTerminal: { version: 1, state: "unknown", runId: "oracle-1", runnerProcessInstanceId: "runner-9", reason: "verification-failed" } })),
      request,
      "oracle-1",
    ),
    true,
    "an inconclusive unknown process-terminal state must not reject",
  );
  assert.equal(
    rpcReplyProvesCurrentOwner(
      envelope(rpcTargetedStatus("oracle-1", "running", { processTerminal: { version: 1, state: "not-started", runId: "oracle-1", runnerProcessInstanceId: "runner-9" } })),
      request,
      "oracle-1",
    ),
    true,
    "a not-started process-terminal state must not reject",
  );
});

test("CORR16 C39-1: a matching runner-close inside an UNKNOWN proof rejects; pending/unknown-without-close do not", () => {
  // The runtime RETAINS a directly observed runner exit in `instances` even when
  // whole-tree verification stays unknown (`process-terminal.js:211-213`), and
  // `run-status.js:759` returns that evidence at `details.lifecycleStatus`.
  // Therefore an aggregate `state === "unknown"` proof can POSITIVELY prove the
  // runner is GONE. The predicate must consume `instances`, binding the close to
  // BOTH the exact runId AND the exact runnerProcessInstanceId the reply carries.
  const { rpcReplyProvesCurrentOwner } = mod;
  const request = { requestId: "c39-runner-close", method: "status" };
  const base = { version: 1, runId: "r", runnerProcessInstanceId: "runner-a" };
  const runnerClose = { kind: "runner", processInstanceId: "runner-a", closeObservedAt: 1700000000000, exitCode: 1, signal: null };
  const evaluate = (processTerminal) =>
    rpcReplyProvesCurrentOwner(
      {
        version: mod.SUBAGENT_RPC_VERSION,
        ...request,
        success: true,
        data: {
          text: "Run: r\nState: running",
          details: { mode: "single", runId: "r", results: [], lifecycleStatus: { processTerminal } },
        },
      },
      request,
      "r",
    );
  // LIVE CASE CONTROL: `pending` (still starting) must STAY accepted.
  assert.equal(
    evaluate({ version: 1, state: "pending", runId: "r", runnerProcessInstanceId: "runner-a" }),
    true,
    "a pending proof with no close evidence must remain accepted",
  );
  // INCONCLUSIVE CONTROL: `unknown` with NO close evidence must STAY accepted.
  assert.equal(
    evaluate({ version: 1, state: "unknown", runId: "r", runnerProcessInstanceId: "runner-a", reason: "writer-close-unverified" }),
    true,
    "an unknown proof with no close evidence must remain accepted",
  );
  // THE DEFECT: a matching runner-close inside an `unknown` proof must REJECT.
  assert.equal(
    evaluate({ ...base, state: "unknown", reason: "writer-close-unverified", instances: [runnerClose] }),
    false,
    "a matching runner-close inside an unknown proof must reject",
  );
  // NEAR-MISS: a close for a DIFFERENT run must not reject this one.
  assert.equal(
    evaluate({ ...base, runId: "other", state: "unknown", reason: "x", instances: [runnerClose] }),
    true,
    "a close bound to a different run must not reject this run",
  );
  // NEAR-MISS: a close for a DIFFERENT runner instance must not reject.
  assert.equal(
    evaluate({ ...base, state: "unknown", reason: "x", instances: [{ ...runnerClose, processInstanceId: "runner-b" }] }),
    true,
    "a close bound to a different runner instance must not reject",
  );
  // NEAR-MISS: a close on an unrelated CHILD inside this run's instances must not reject.
  assert.equal(
    evaluate({ ...base, state: "unknown", reason: "x", instances: [{ kind: "pi-writer", processInstanceId: "runner-a", closeObservedAt: 1, exitCode: 1, signal: null }] }),
    true,
    "a child close (not the runner) must not reject",
  );
  // The pre-existing `observed` rejection is preserved.
  assert.equal(
    evaluate({ version: 1, state: "observed", runId: "r", runnerProcessInstanceId: "runner-a", observedAt: 1, instances: [runnerClose] }),
    false,
    "matching observed termination must still reject",
  );
});

test("CORR16 C39-1 e2e: a reply carrying a matching runner-close does NOT produce verified silent WAIT", () => {
  // Downstream of the predicate: when the correlated reply carries a valid
  // runner-close bound to this exact run and runner instance, the WAIT must NOT
  // reach the silent branch (`session-supervisor.ts` silent-WAIT path). The
  // unverified notice must fire instead of the run masquerading as live.
  const runnerClose = {
    version: 1,
    state: "unknown",
    runId: "oracle-1",
    runnerProcessInstanceId: "runner-9",
    reason: "writer-close-unverified",
    instances: [{ kind: "runner", processInstanceId: "runner-9", closeObservedAt: 1700000000000, exitCode: 1, signal: null }],
  };
  const h = fakeClockHarness({
    envelope: (request) => ({
      version: mod.SUBAGENT_RPC_VERSION,
      requestId: request.requestId,
      method: "status",
      success: true,
      data: rpcTargetedStatus("oracle-1", "running", { processTerminal: runnerClose }),
    }),
  });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "a matching runner-close must defeat verified silence, not preserve it",
    );
  } finally {
    capture.restore();
  }
});

test("CORR16 C39-1 e2e: the recheck path is not silenced by a matching runner-close either", () => {
  // The idle recheck uses the SAME predicate, so contradictory evidence must not
  // be able to preserve silence indefinitely: the first verification is genuinely
  // live (silent), then at the recheck the reply carries a matching runner-close
  // and the unverified notice must fire.
  let phase = "verify";
  const runnerClose = {
    version: 1,
    state: "unknown",
    runId: "oracle-1",
    runnerProcessInstanceId: "runner-9",
    reason: "writer-close-unverified",
    instances: [{ kind: "runner", processInstanceId: "runner-9", closeObservedAt: 1700000000000, exitCode: 1, signal: null }],
  };
  const h = fakeClockHarness({
    envelope: (request) => ({
      version: mod.SUBAGENT_RPC_VERSION,
      requestId: request.requestId,
      method: "status",
      success: true,
      data: rpcTargetedStatus("oracle-1", "running", {
        ...(phase === "recheck" ? { processTerminal: runnerClose } : {}),
      }),
    }),
  });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: h.branch },
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "the initial live verification stays silent");
    phase = "recheck";
    h.advance(WAIT_RECHECK_MS + WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_UNVERIFIED_WAIT],
      "the recheck must refuse verified silence when the reply carries a matching runner-close",
    );
  } finally {
    capture.restore();
  }
});

test("CORR10/NEW-2: a restored live WAIT survives a momentarily uninitialised peer bridge", () => {
  // In the supported `-e` load order this extension's `session_start` handler
  // runs BEFORE pi-subagents' own, so the bridge context is not yet set and the
  // first `status` request is answered `no_active_session`. That is a
  // bridge-readiness signal, NOT evidence about the run, so a restored, live
  // WAIT must be retried rather than falsely rejected.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  const carried = first.persisted;

  let attempts = 0;
  const reloaded = fakeClockHarness({
    entries: carried,
    envelope: (request) => {
      attempts += 1;
      if (attempts <= mod.WAIT_BRIDGE_NOT_READY_RETRIES) {
        // Bridge not yet initialised: an error reply that says NOTHING about
        // the run.
        return {
          version: mod.SUBAGENT_RPC_VERSION,
          requestId: request.requestId,
          method: "status",
          success: false,
          error: { code: "no_active_session", message: "No active extension context for subagent RPC." },
        };
      }
      return {
        version: mod.SUBAGENT_RPC_VERSION,
        requestId: request.requestId,
        method: "status",
        success: true,
        data: rpcTargetedStatus("oracle-1", "running"),
      };
    },
  });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: reloaded.branch },
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.ok(attempts > mod.WAIT_BRIDGE_NOT_READY_RETRIES, "the bridge was re-asked after not-ready refusals");
    assert.deepEqual(
      capture.chunks,
      [],
      "a live restored WAIT must not be falsely rejected while the bridge is still initialising",
    );
    // A deferred re-ask must not leak the previous request's listener: the
    // consuming request already freed it, and exactly one verified recheck
    // listener may remain.
    assert.ok(
      reloaded.liveRpcListeners() <= 1,
      "deferred bridge re-asks must not accumulate RPC listeners",
    );
  } finally {
    capture.restore();
  }
});

test("CORR10/NEW-2 control: a persistently un-ready bridge still resolves to the unverified notice", () => {
  // The retry must be BOUNDED: a bridge that never becomes ready cannot leave a
  // WAIT silently stalled forever. After the retries are exhausted the racing
  // expiry must fire the unverified notice.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  let attempts = 0;
  const reloaded = fakeClockHarness({
    entries: first.persisted,
    envelope: (request) => {
      attempts += 1;
      return {
        version: mod.SUBAGENT_RPC_VERSION,
        requestId: request.requestId,
        method: "status",
        success: false,
        error: { code: "no_active_session", message: "No active extension context for subagent RPC." },
      };
    },
  });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: reloaded.branch },
    });
    reloaded.advance(WAIT_VERIFICATION_MS + mod.WAIT_BRIDGE_NOT_READY_RETRIES * mod.WAIT_BRIDGE_NOT_READY_RETRY_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "a bridge that never becomes ready must still resolve to the unverified notice",
    );
    assert.ok(attempts <= mod.WAIT_BRIDGE_NOT_READY_RETRIES + 1, "the retry count is bounded");
  } finally {
    capture.restore();
  }
});

test("CORR10/NEW-2 control: a genuine not_found reply is NOT retried and rejects immediately", () => {
  // Only the bridge-not-ready code is deferred. A decisive negative answer about
  // the run (e.g. `not_found`) must reject on the FIRST reply - the fix must not
  // weaken genuine rejection.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  let attempts = 0;
  const reloaded = fakeClockHarness({
    entries: first.persisted,
    envelope: (request) => {
      attempts += 1;
      return {
        version: mod.SUBAGENT_RPC_VERSION,
        requestId: request.requestId,
        method: "status",
        success: false,
        error: { code: "not_found", message: "Async run was not found in the active session." },
      };
    },
  });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: { buildSessionProjection: () => ({ messages: [WAIT_ON("oracle-1")] }), getBranch: reloaded.branch },
    });
    reloaded.advance(WAIT_BRIDGE_NOT_READY_RETRY_MS + WAIT_VERIFICATION_MS);
    assert.equal(attempts, 1, "a not_found reply must not be retried");
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "a decisive not_found reply must reject the WAIT",
    );
  } finally {
    capture.restore();
  }
});

test("F4: an UNANSWERED fresh verification retires the cached owner (asserts NOTIFIED OUTPUT only - the repair ENTRY itself is covered by PG6)", () => {
  // D4/F4: WAIT A verifies (owner cached). WAIT B for the SAME run replaces it
  // with NO intervening input/reset, and B's request is never answered. B's
  // expiry must retire the cached owner, so `verifiedWakeOwnerExists()` can no
  // longer suppress decision repair on stale evidence.
  //
  // DISCRIMINATING LIMIT (R7-6): this test observes that NO user-contact notice
  // is emitted. That is necessarily a WEAKER claim than "a repair entry was
  // returned" - the empty output could in principle also come from notification
  // deduplication. The strong form (asserting the ACTUAL repair entry) is the
  // PG6 test; this one is retained deliberately as the notice-level companion.
  const h = fakeClockHarness({ deferReplies: true });
  h.observeStart("oracle-1");

  // WAIT A: hold its reply, then deliver a valid one so A verifies and caches
  // the owner.
  h.pi.emit("agent_settled", settleEvent(), {
    ...h.ctx,
    sessionManager: sessionView([WAIT_ON("oracle-1")]),
  });
  const heldA = h.heldReplies();
  assert.equal(heldA.length, 1, "A's request is in flight");
  h.deliver(heldA[0]);

  // WAIT B for the same run, with no intervening input. Nothing answers it.
  h.pi.emit("agent_settled", settleEvent(), {
    ...h.ctx,
    sessionManager: sessionView([WAIT_ON("oracle-1")]),
  });
  h.advance(WAIT_VERIFICATION_MS);

  const capture = captureStdout();
  try {
    // A BLOCKED escalation naming that same run is now genuinely actionable: the
    // cached owner is gone, so the repair path may propose a continuation.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([
        assistant("I cannot proceed.\n\nSTATUS:BLOCKED user oracle=oracle-1 choose one"),
      ]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [],
      "repair is proposed (no user-contact notice) because the stale owner no longer suppresses it",
    );
  } finally {
    capture.restore();
  }
});

test("F5: an UNANSWERED recheck leaves no timer and no RPC listener after shutdown", () => {
  const h = fakeClockHarness({ deferReplies: true });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    // Verify a WAIT so the idle recheck arms.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    const heldFirst = h.heldReplies();
    assert.equal(heldFirst.length, 1, "verification request in flight");
    h.deliver(heldFirst[0]);

    // Advance to the recheck, which fires an UNANSWERED inner request.
    h.advance(WAIT_RECHECK_MS);
    assert.ok(h.pendingTimers() > 0, "the recheck's expiry window is armed");
    assert.ok(h.liveRpcListeners() > 0, "the recheck's RPC listener is subscribed");

    // Shutdown DURING the unanswered recheck window.
    h.pi.emit("session_shutdown", { type: "session_shutdown" }, h.ctx);

    assert.equal(h.liveRpcListeners(), 0, "no RPC listener survives shutdown");
    assert.equal(h.pendingTimers(), 0, "no timer survives shutdown");
    // And nothing may notify afterwards.
    h.advance(WAIT_RECHECK_MS + WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "nothing notifies after shutdown");
  } finally {
    capture.restore();
  }
});

test("F5: input, navigation and settlement each free the recheck timer and listener", () => {
  // These three are genuine CANCELLATION boundaries: nothing new is armed, so
  // any surviving timer or listener is a leak.
  const lifecycle = [
    ["input", (h) => h.pi.emit("input", { type: "input", source: "interactive" }, h.ctx)],
    ["navigation", (h) => h.pi.emit("session_tree", { type: "session_tree" }, h.ctx)],
    ["settlement", (h) => h.pi.emit("agent_settled", settleEvent(), { ...h.ctx, sessionManager: sessionView([assistant("done\n\nSTATUS:DONE")]) })],
  ];
  for (const [label, act] of lifecycle) {
    const h = fakeClockHarness({ deferReplies: true });
    h.observeStart("oracle-1");
    const capture = captureStdout();
    try {
      h.pi.emit("agent_settled", settleEvent(), {
        ...h.ctx,
        sessionManager: sessionView([WAIT_ON("oracle-1")]),
      });
      const first = h.heldReplies();
      h.deliver(first[0]);
      h.advance(WAIT_RECHECK_MS);
      assert.ok(h.pendingTimers() > 0, `${label}: recheck window armed`);

      act(h);
      // The DONE settlement legitimately emits its OWN attention notice, so the
      // cleanup assertion is scoped to the WAIT artifacts rather than to an
      // empty output stream.
      const afterAct = capture.chunks.length;

      assert.equal(h.liveRpcListeners(), 0, `${label}: no RPC listener survives`);
      assert.equal(h.pendingTimers(), 0, `${label}: no timer survives`);
      h.advance(WAIT_RECHECK_MS * 4);
      assert.equal(
        capture.chunks.length,
        afterAct,
        `${label}: no LATE WAIT notice fires after the boundary`,
      );
    } finally {
      capture.restore();
    }
  }
});

test("F5: a REPLACEMENT WAIT frees the OLD recheck artifacts and arms exactly one new check", () => {
  // Replacement is not a pure cancellation: the new WAIT legitimately subscribes
  // its own request. The invariant is therefore that the OLD recheck's timer and
  // listener are gone and only the NEW verification's single subscription (and
  // single window) remain - not that everything drops to zero.
  const h = fakeClockHarness({ deferReplies: true });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.deliver(h.heldReplies()[0]);
    h.advance(WAIT_RECHECK_MS);
    const recheckTimers = h.pendingTimers();
    const recheckListeners = h.liveRpcListeners();
    assert.ok(recheckTimers > 0 && recheckListeners > 0, "the recheck is armed and subscribed");

    // A SECOND WAIT replaces it, with no intervening input.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });

    // The LIVE-SUBSCRIPTION count is the authoritative measure: `heldReplies()`
    // also retains the OLD cancelled request in this harness, so it would
    // over-count even when disposal worked correctly.
    assert.equal(h.liveRpcListeners(), 1, "only the NEW verification is subscribed");
    assert.equal(h.pendingTimers(), 1, "only the NEW verification's window is armed");

    // Answering the new request releases the remaining listener.
    h.deliver(h.heldReplies()[h.heldReplies().length - 1]);
    assert.equal(h.liveRpcListeners(), 0, "answering the new request releases its listener");
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "no spurious notice from the superseded recheck");
  } finally {
    capture.restore();
  }
});

test("F5: before_agent_start and a delivered user message also free WAIT artifacts", () => {
  for (const [label, fire] of [
    ["before_agent_start", (h) => h.pi.emit("before_agent_start", { type: "before_agent_start" }, h.ctx)],
    ["user message_start", (h) => h.pi.emit("message_start", { type: "message_start", message: { role: "user", content: "hello" } }, h.ctx)],
  ]) {
    const h = fakeClockHarness({ deferReplies: true });
    h.observeStart("oracle-1");
    const capture = captureStdout();
    try {
      h.pi.emit("agent_settled", settleEvent(), {
        ...h.ctx,
        sessionManager: sessionView([WAIT_ON("oracle-1")]),
      });
      const first = h.heldReplies();
      h.deliver(first[0]);
      h.advance(WAIT_RECHECK_MS);
      assert.ok(h.pendingTimers() > 0, `${label}: recheck window armed`);

      fire(h);

      assert.equal(h.pendingTimers(), 0, `${label}: no timer survives`);
      assert.equal(h.liveRpcListeners(), 0, `${label}: no RPC listener survives`);
      h.advance(WAIT_RECHECK_MS * 4);
      assert.deepEqual(capture.chunks, [], `${label}: nothing notifies afterwards`);
    } finally {
      capture.restore();
    }
  }
});

// ---------------------------------------------------------------------------
// CORR4 regressions: PG2-PG7
// ---------------------------------------------------------------------------

test("PG2: a finalized PAUSED run cannot earn silent waiting", async () => {
  // `paused` is NOT wake-capable: an interrupted paused run is finalized
  // (`docs/extension-api.md:595`), only queued/running count as active
  // (`active-run-index.js:34-35`), and `run-status.js:791-795` renders
  // `State: paused` from an already-delivered interrupted result. Accepting it
  // would silence a WAIT with no future automatic wake.
  const request = { requestId: "pg2-paused", method: "status" };
  const pausedReply = {
    version: 1,
    ...request,
    success: true,
    data: { text: "Run: oracle-1\nState: paused", details: { mode: "single", results: [] } },
  };
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(pausedReply, request, "oracle-1"),
    false,
    "a paused state is not current-owner proof",
  );

  // End to end: a WAIT whose ONLY bridge reply says `paused` must NOT stay silent.
  const h = fakeClockHarness({ states: () => "paused" });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "an unproven (paused) WAIT notifies instead of waiting silently",
    );
  } finally {
    capture.restore();
  }
});

test("PG4: a child 'started'/'stopping' event does NOT retire the run's provenance", () => {
  // The topic carries lifecycle transitions, not only endings: the real tracker
  // emits started/stopping/stopped (`async-job-tracker.js:278-295`). Only the
  // TERMINAL transition may retire provenance.
  const h = fakeClockHarness({ runId: "oracle-1" });
  h.observeStart("oracle-1");
  const before = h.persisted.filter((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE).length;
  assert.equal(before, 1, "the START persists provenance");

  for (const status of ["started", "stopping"]) {
    h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
      type: "subagent.child-status",
      version: 1,
      runId: "oracle-1",
      childId: "child-1",
      childRunId: "oracle-child-1",
      status,
      ts: 1,
    });
  }
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    assert.deepEqual(capture.chunks, [], "non-terminal child events do not invalidate the WAIT");
  } finally {
    capture.restore();
  }
});


/**
 * The REAL-SHAPED child-status fixture, loaded so it drives assertions instead of
 * sitting decoratively (the reviewer's R6-1/R6-4 note). Its field set is taken
 * from the runtime emit site (`async-job-tracker.js:283-301`); the values are
 * SOURCE-DERIVED, not runtime-captured - see `tests/fixtures/README-provenance.txt`.
 */
const CHILD_STATUS_FIXTURE = JSON.parse(
  readFileSync(new URL("./fixtures/subagents-child-status-derived.json", import.meta.url), "utf8"),
);

test("R6-4: a fixture CHILD-scoped stop does NOT retire the aggregate root", () => {
  // Driven from the fixture: `stopped_child` names childId != runId, which is a
  // child's ending and must leave the root's provenance intact.
  const event = CHILD_STATUS_FIXTURE.stopped_child;
  assert.notEqual(event.childId, event.runId, "fixture precondition: child-scoped event");
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, { ...event, runId: "oracle-1", childId: "oracle-1-child" });
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "a child's stop must not retire the root");
  } finally {
    capture.restore();
  }
});

test("R6-4: a fixture ROOT stop DOES retire the run", () => {
  // The genuine root termination, driven from the fixture's `stopped_root`
  // (childId == runId).
  const event = CHILD_STATUS_FIXTURE.stopped_root;
  assert.equal(event.childId, event.runId, "fixture precondition: root-scoped event");
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, { ...event, runId: "oracle-1", childId: "oracle-1" });
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "the root's own stop must retire it",
    );
  } finally {
    capture.restore();
  }
});

test("R6-1: the fixture's child-status events carry a DOTTED payload type, while the topic is COLON-separated", () => {
  // The exact confusion R6-1 recorded: `subagent.child-status` (dotted) is the
  // payload `type`, not the bus channel. The fixture preserves both facts.
  for (const key of ["started", "stopping", "stopped", "stopped_child", "stopped_root"]) {
    assert.equal(
      CHILD_STATUS_FIXTURE[key].type,
      "subagent.child-status",
      `${key} carries the dotted payload type`,
    );
  }
  assert.equal(
    mod.OBSERVED_RUN_TERMINAL_TOPIC,
    "subagent:child-status",
    "the CHANNEL is colon-separated",
  );
  assert.notEqual(
    mod.OBSERVED_RUN_TERMINAL_TOPIC,
    CHILD_STATUS_FIXTURE.stopped.type,
    "the channel must never equal the payload type",
  );
});

test("PG4: only a TERMINAL status retires, driven from the fixture lifecycle", () => {
  // The fixture's started/stopping/stopped trio proves the topic carries
  // LIFECYCLE transitions, not only endings.
  assert.deepEqual(
    [CHILD_STATUS_FIXTURE.started.status, CHILD_STATUS_FIXTURE.stopping.status],
    ["started", "stopping"],
    "fixture precondition: non-terminal transitions exist",
  );
  for (const key of ["started", "stopping"]) {
    const h = fakeClockHarness({ states: () => "running" });
    h.observeStart("oracle-1");
    h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, { ...CHILD_STATUS_FIXTURE[key], runId: "oracle-1", childId: "oracle-1" });
    const capture = captureStdout();
    try {
      h.pi.emit("agent_settled", settleEvent(), {
        ...h.ctx,
        sessionManager: sessionView([WAIT_ON("oracle-1")]),
      });
      h.advance(WAIT_VERIFICATION_MS);
      assert.deepEqual(capture.chunks, [], `a \`${key}\` event must not retire the run`);
    } finally {
      capture.restore();
    }
  }
});

test("PG4: one child's TERMINAL event does not retire aggregate root ownership", () => {
  // Identity must prefer `childRunId`, so a single child ending cannot drop the
  // ROOT run's provenance while siblings are still active. The child event names
  // the root in `runId` and a DIFFERENT id in `childRunId`; only the child id may
  // be retired.
  const h = fakeClockHarness({ runId: "oracle-1" });
  h.observeStart("oracle-1");
  h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
    type: "subagent.child-status",
    version: 1,
    runId: "oracle-1",
    childId: "child-1",
    childRunId: "oracle-child-1",
    status: "stopped",
    ts: 1,
  });
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    assert.deepEqual(
      capture.chunks,
      [],
      "the ROOT run keeps its provenance when only a child ended",
    );
  } finally {
    capture.restore();
  }
});

test("PG4/R6-4: a CHILD-scoped terminal event does NOT retire the aggregate root", () => {
  // R6-4: `childId: "child-1"` (or a `step:N`) is NOT the aggregate root. The
  // real runner emits `childId` always but spreads `childRunId` only
  // conditionally (`subagent-runner.js:1950-1963`), and emits stopped child
  // events for individual steps while siblings stay active (`:2006`). Falling
  // back to the aggregate id would retire a LIVE root, so the root must keep its
  // provenance and the WAIT must stay SILENT.
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
    type: "subagent.child-status",
    version: 1,
    runId: "oracle-1",
    childId: "child-1",
    status: "stopped",
    ts: 1,
  });
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [],
      "a child's end does not establish the root's end, so the WAIT stays silent",
    );
  } finally {
    capture.restore();
  }
});

test("PG4: the ROOT run's own terminal event DOES retire its provenance", () => {
  // The genuine root-termination case: the event is about the run THIS session
  // observed start (`childId` absent or equal to `runId`). Terminal evidence is
  // positive proof the wake path is gone, so the WAIT must be reported.
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
    type: "subagent.child-status",
    version: 1,
    runId: "oracle-1",
    childId: "oracle-1",
    status: "stopped",
    ts: 1,
  });
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "a genuinely terminal run cannot corroborate a WAIT",
    );
  } finally {
    capture.restore();
  }
});

test("PG5: the runtime instance id is PROCESS-stable across a simulated /reload", async () => {
  // A native `/reload` re-evaluates this module in the SAME process through Jiti
  // with `moduleCache: false` (`resource-loader.js:352-355`, `loader.js:477-481`),
  // so a module-scoped initializer would MINT A NEW ID and the process would
  // reject the provenance it had just persisted. The module cannot be re-imported
  // in isolation here, so the reload is simulated at the level that actually
  // distinguishes the two designs: the id is read through a PROCESS anchor.
  //
  // Deleting the anchor must therefore change the id; if the implementation kept
  // only a module-local value, the anchor would be absent and this test would
  // fail.
  const first = mod.currentRuntimeInstanceId();
  assert.equal(typeof first, "string");
  assert.ok(first.length > 0, "a process id exists");

  const anchorKey = "__sessionSupervisorRuntimeInstanceId__";
  const anchored = globalThis[anchorKey];
  assert.equal(
    anchored,
    first,
    "the id is stored on a PROCESS-scoped anchor, not merely module-local (this is what survives a reload)",
  );

  // Simulate the reload's effect at the anchor level: clear the anchor and
  // force the module to re-derive its id. A PROCESS-stable design re-publishes
  // the SAME value it reads through the anchor; a module-scoped design has no
  // anchor at all, so `anchored` above would be undefined and this fails.
  delete globalThis[anchorKey];
  const afterReload = mod.currentRuntimeInstanceId();
  assert.ok(
    typeof globalThis[anchorKey] === "string" && globalThis[anchorKey].length > 0,
    "re-reading re-establishes the process anchor (the id is process-owned, not module-owned)",
  );
  assert.equal(afterReload, globalThis[anchorKey], "the reported id matches the process anchor");
});


test("R6-2: a terminal observation RETIRES an already-verified WAIT (silent waiting ends)", () => {
  // R6-2: verification caches an owner, and the recheck then asks only whether
  // the bridge still reports liveness. If the awaited run is OBSERVED terminal
  // after verification, that positive evidence must retire the trust - otherwise
  // silent waiting persists on evidence this extension has just contradicted.
  const h = fakeClockHarness({ states: () => "running" });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    // Verify the WAIT with a live reply.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "a live owner verifies the WAIT");

    // Now the exact run is observed terminal.
    h.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
      type: "subagent.child-status",
      version: 1,
      runId: "oracle-1",
      childId: "oracle-1",
      status: "stopped",
      ts: 2,
    });
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "terminal evidence must end silent waiting",
    );
    // And the trust is torn down: no recheck artifacts remain armed.
    assert.equal(h.pendingTimers(), 0, "the recheck timer is cancelled");
  } finally {
    capture.restore();
  }
});

test("R6-3: a terminal observation retires provenance RESTORED by a reload (empty ledger)", () => {
  // R6-3: after a reload the observed-run LEDGER is empty while PROVENANCE is
  // restored. The old implementation bailed out when the ledger row was absent,
  // silently discarding every terminal observation that arrived post-reload.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  const carried = first.persisted;

  const reloaded = fakeClockHarness({ entries: carried, states: () => "running" });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    // Terminal WITHOUT any ledger row in this process: only provenance exists.
    reloaded.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
      type: "subagent.child-status",
      version: 1,
      runId: "oracle-1",
      childId: "oracle-1",
      status: "stopped",
      ts: 3,
    });
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "a restored record retired by a terminal event cannot corroborate a WAIT",
    );
  } finally {
    capture.restore();
  }
});

test("R6-3: a REPLAYED START does not clear a restored terminal tombstone", () => {
  // R6-3 second half: `observeStart` used to take `terminal` from the LEDGER
  // only, so a duplicate/replayed START after a reload overwrote a restored
  // terminal record with `terminal: false` - resurrecting a run already known
  // dead. The tombstone must survive.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  // Retire it, so the persisted record carries terminal: true.
  first.bus.emit(mod.OBSERVED_RUN_TERMINAL_TOPIC, {
    type: "subagent.child-status",
    version: 1,
    runId: "oracle-1",
    childId: "oracle-1",
    status: "stopped",
    ts: 4,
  });
  const retired = first.persisted.filter((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
  assert.equal(retired[retired.length - 1].data.terminal, true, "the tombstone is persisted");

  const reloaded = fakeClockHarness({ entries: first.persisted, states: () => "running" });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  // A replayed START for the SAME run must NOT revive it.
  reloaded.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    reloaded.pi.emit("agent_settled", settleEvent(), {
      ...reloaded.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    reloaded.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "a replayed START must not clear a restored terminal tombstone",
    );
  } finally {
    capture.restore();
  }
});

test("R6-5: a workflow-awaited run cannot corroborate a WAIT (no independent delivery wake)", () => {
  // R6-5/AC-F2-1: an async child launched under a parent workflow publishes its
  // result to a workflow-owned path, and its completion is skipped by the
  // notifier (`notify.js:725-728`). It therefore has no independent completion
  // wake to THIS parent, so it must never earn a verified WAIT - fail closed.
  const h = fakeClockHarness({ states: () => "running" });
  h.bus.emit(mod.OBSERVED_RUN_START_TOPIC, {
    type: "subagent:async-started",
    version: 1,
    runId: "oracle-1",
    id: "oracle-1",
    agent: "oracle",
    sessionFile: h.sessionFile,
    sessionId: h.sessionFile,
    parentWorkflowRunId: "workflow-9",
  });
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "a workflow-awaited run has no independent wake, so the WAIT is unverified",
    );
  } finally {
    capture.restore();
  }
});

test("R6-5: an ordinary (non-workflow) START still corroborates with a live owner", () => {
  // The control: without `parentWorkflowRunId` the run IS delivery-capable, so a
  // live owner must still verify the WAIT. This isolates the delivery gate.
  const h = fakeClockHarness({ states: () => "running" });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "an ordinary run with a live owner stays silent");
  } finally {
    capture.restore();
  }
});

test("R7-1: a workflow ROOT cannot corroborate a WAIT (quiet scheduled roots share its START shape)", () => {
  // R7-1/AC-F2-1: a workflow root emits `mode: "workflow"`, `agent: "workflow"`
  // with NEITHER `parentWorkflowRunId` NOR `scheduleOrigin`
  // (subagent-executor.js:5148-5160). A QUIET SCHEDULED root has the IDENTICAL
  // START shape, but `scheduledCompletionTriggersTurn` (notify.js:226-227) forces
  // `triggerTurn: false` for a quiet schedule's successful completion. Keying
  // delivery on `parentWorkflowRunId` alone therefore let a wake-incapable root
  // sit SILENTLY - the exact false WAIT the user reported.
  //
  // This is the reviewer's probe, driven through the test harness. It must NOT
  // be silently accepted as delivery-capable.
  const h = fakeClockHarness({ states: () => "running" });
  h.observeStart("quiet-workflow-root", "workflow", "/tmp/quiet-workflow-root", {
    mode: "workflow",
  });
  // The run is recorded, but with its wake path UNPROVEN (fail closed).
  const record = h.persisted.find(
    (e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE && e.data.runId === "quiet-workflow-root",
  );
  assert.ok(record, "the workflow root is still observed and persisted");
  assert.equal(
    record.data.deliveryCapable,
    false,
    "a workflow ROOT has an unproven wake path, so it is not delivery-capable",
  );
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("quiet-workflow-root")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [mod.OSC_NOTIFY_UNVERIFIED_WAIT],
      "a workflow root cannot deliver an independent wake, so the WAIT is unverified rather than silent",
    );
  } finally {
    capture.restore();
  }
});

test("R7-1: an ordinary single-run START still corroborates (the over-rejection is scoped to workflow mode)", () => {
  // The control guarding against OVER-BROAD rejection: an ordinary `mode:
  // "single"` run (async-execution.js:1986) must still be delivery-capable, so
  // the R7-1 fix cannot simply reject everything.
  const h = fakeClockHarness({ states: () => "running" });
  h.observeStart("oracle-1", "oracle", undefined, { mode: "single" });
  const record = h.persisted.find((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
  assert.equal(record.data.deliveryCapable, true, "an ordinary single run remains delivery-capable");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [], "an ordinary run with a live owner stays silent");
  } finally {
    capture.restore();
  }
});

test("R8-1: a SAME-process reload re-establishes an OUTSTANDING WAIT", () => {
  // R8-1/AC-F2-3: Pi's reload path emits ONLY `session_start` - never a fresh
  // `agent_settled`. The handler cancelled the WAIT artifacts and restored
  // provenance, but never re-established the WAIT's verification obligation, so
  // a reloaded session went silent: NO verification, NO notice, NO timer.
  // Provenance surviving is NOT sufficient - it records only that a run was
  // witnessed, not that this session is still OWED a wake.
  const first = fakeClockHarness();
  first.observeStart("oracle-1");

  const reloaded = fakeClockHarness({ entries: first.persisted });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, {
    ...reloaded.ctx,
    sessionManager: sessionView([WAIT_ON("oracle-1")]),
  });
  // The reload itself must leave an ACTIVE obligation behind: a fresh RPC
  // request or an armed verification window. Nothing pending is the R8-1 defect.
  assert.ok(
    reloaded.pendingTimers() > 0,
    "a reloaded idle WAIT must establish a fresh verification window, not vanish",
  );
});

test("R8-2: a valid escalation is not falsely repaired after a reload", async () => {
  // R8-2: restoration populated `provenance` but left `observedRuns` EMPTY, and
  // `verifyUserEscalation` reads only the ledger - so a valid, already-completed
  // `STATUS:BLOCKED user` escalation that verified BEFORE the reload was
  // re-classified as unknown and forced through decision repair. That is a FALSE
  // repair on genuine user-owned dependency evidence.
  const dir = makeAsyncDir({ dir: "/async/oracle-r82", result: oracleResult({ dependencyId: "dep-1" }) });
  const files = new Map(dir.files);
  // First load: observe the run so provenance is PERSISTED to the branch.
  const first = fakeClockHarness({ states: () => "complete", files });
  first.observeStart("oracle-1", "oracle", dir.dir);
  assert.ok(
    first.persisted.some((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE),
    "the first load persisted provenance for the observed run",
  );

  // Reload: a fresh module in the same process, inheriting ONLY the persisted
  // branch. Before R8-2 the ledger stayed empty, so the escalation was
  // mis-classified as unknown and falsely repaired.
  const reloaded = fakeClockHarness({ states: () => "complete", entries: first.persisted, files });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const capture = captureStdout();
  try {
    const result = await handlerFor(reloaded.pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-1", "dep-1"))]),
      reloaded.ctx,
    );
    const entryType = result?.entries?.at(-1)?.customType ?? null;
    assert.notEqual(
      entryType,
      mod.REPAIR_CUSTOM_TYPE,
      "a restored valid escalation must not be repaired as if the run were unknown",
    );
  } finally {
    capture.restore();
  }
});

test("R8-3: a FAILED child cannot suppress repair via stale owner evidence", async () => {
  // R8-3: `cancelWaitVerification()` cleared timers/listeners but NOT
  // `currentOwnerRuns`, and `verifiedWakeOwnerExists()` excluded only
  // successfully-completed artifacts - not `failed` ones. After activity plus a
  // child transition to `failed`, repair was suppressed on an ownership that was
  // never freshly checked.
  //
  // Sequence (mirrors the reviewer's probe): verify a WAIT so the owner is
  // cached, cross an activity boundary, then present a BLOCKED naming that run
  // while its on-disk state is `failed`. The escalation must NOT be silenced by
  // the stale owner - it must be repaired.
  const dir = makeAsyncDir({ dir: "/async/oracle-r83", state: "failed", result: oracleResult({ dependencyId: "dep-1" }) });
  const files = new Map(dir.files);
  const h = fakeClockHarness({ states: () => "running", files });
  h.observeStart("oracle-1", "oracle", dir.dir);
  // Verify the WAIT so the owner is cached, then advance past the verification.
  h.pi.emit("agent_settled", settleEvent(), {
    ...h.ctx,
    sessionManager: sessionView([WAIT_ON("oracle-1")]),
  });
  h.advance(WAIT_VERIFICATION_MS);
  // Activity boundary: a new turn begins.
  h.pi.emit("before_agent_start", { type: "before_agent_start", prompt: "go" }, h.ctx);

  const capture = captureStdout();
  try {
    const result = await handlerFor(h.pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-1", "dep-1"))]),
      h.ctx,
    );
    // A `failed` run is not a live wake owner, so it must not silence the
    // escalation: the boundary should propose decision repair.
    assert.notEqual(
      result,
      undefined,
      "a failed child must not suppress repair through stale owner evidence",
    );
    assert.equal(result?.entries?.at(-1)?.customType, mod.REPAIR_CUSTOM_TYPE, "the escalation is repaired");
    assert.deepEqual(capture.chunks, [], "a successful repair does not notify");
  } finally {
    capture.restore();
  }
});

test("R8-4: an ABORTED settlement never earns silent WAIT", () => {
  // R8-4: the projected WAIT must not override the host's interruption evidence.
  const h = fakeClockHarness({ states: () => "running" });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    h.pi.emit("agent_settled", { type: "agent_settled", aborted: true }, {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    assert.equal(
      h.pendingTimers(),
      0,
      "an aborted settle must not arm a WAIT recheck as if the WAIT were corroborated",
    );
    assert.notDeepEqual(capture.chunks, [], "an aborted settle must notify");
  } finally {
    capture.restore();
  }
});

test("PG5: a SAME-process register still corroborates persisted provenance", () => {
  // Regression for the reload lifecycle: provenance written by this process must
  // be recognised on a later restore in the SAME process.
  const h = fakeClockHarness();
  h.observeStart("oracle-1");
  const record = h.persisted.find((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
  assert.ok(record, "provenance was persisted");
  assert.equal(
    record.data.runtimeInstanceId,
    mod.currentRuntimeInstanceId(),
    "the persisted record carries the CURRENT process id, not a stale module-local one",
  );
});

test("PG7: a BLOCKED settlement cancels an in-flight unanswered recheck", () => {
  const h = fakeClockHarness({ deferReplies: true });
  h.observeStart("oracle-1");
  const capture = captureStdout();
  try {
    // Verify a WAIT so the idle recheck arms.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("oracle-1")]),
    });
    h.deliver(h.heldReplies()[0]);
    h.advance(WAIT_RECHECK_MS);
    assert.ok(h.pendingTimers() > 0, "the recheck window is armed");
    assert.ok(h.liveRpcListeners() > 0, "the recheck listener is subscribed");

    // A BLOCKED settlement must clean up exactly like DONE/unknown.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([assistant("I cannot proceed.\n\nSTATUS:BLOCKED repository write access")]),
    });

    assert.equal(h.pendingTimers(), 0, "no timer survives a BLOCKED settlement");
    assert.equal(h.liveRpcListeners(), 0, "no RPC listener survives a BLOCKED settlement");
    h.advance(WAIT_RECHECK_MS + WAIT_VERIFICATION_MS);
    assert.deepEqual(capture.chunks, [mod.OSC_NOTIFY], "only the BLOCKED attention notice fires");
  } finally {
    capture.restore();
  }
});

test("PG6: the cache-retirement regression asserts the ACTUAL repair entry", async () => {
  // The previous version of this test only checked that no notice fired, which
  // notification dedup alone could satisfy. This asserts the returned REPAIR
  // ENTRY, so removing the cache-retirement fix makes it fail.
  const h = fakeClockHarness({ deferReplies: true });
  h.observeStart("oracle-1");

  // WAIT A verifies, caching the owner.
  h.pi.emit("agent_settled", settleEvent(), {
    ...h.ctx,
    sessionManager: sessionView([WAIT_ON("oracle-1")]),
  });
  h.deliver(h.heldReplies()[0]);

  // WAIT B for the same run is never answered.
  h.pi.emit("agent_settled", settleEvent(), {
    ...h.ctx,
    sessionManager: sessionView([WAIT_ON("oracle-1")]),
  });
  h.advance(WAIT_VERIFICATION_MS);

  // A well-formed USER BLOCKED naming that same run must now be REPAIRED: the
  // stale cached owner was retired by B's unanswered expiry.
  const result = await handlerFor(h.pi, "agent_before_settle")(
    boundaryEvent([assistant("I cannot proceed.\n\nSTATUS:BLOCKED user oracle=oracle-1 dependency=dep-1 choose one")]),
    h.ctx,
  );
  assert.equal(result?.continue, true, "the repair continuation is proposed");
  assert.equal(
    result?.entries?.at(-1)?.customType,
    mod.REPAIR_CUSTOM_TYPE,
    "an actual repair bridge entry is returned, not merely 'no notice'",
  );
});

// ---------------------------------------------------------------------------
// CORR4: captured-runtime fixtures (TODO-RPCFIX)
// ---------------------------------------------------------------------------

test("RPCFIX: the predicate handles CAPTURED runtime envelopes (real bridge output)", () => {
  // These envelopes were recorded VERBATIM from the installed pi-subagents 0.76.1
  // bridge (see tests/fixtures/README-provenance.txt). The `Run:`/`State:` text
  // is produced by the REAL `inspectSubagentStatus` over REAL on-disk run state,
  // not a mock executor - so the predicate is exercised against genuine runtime
  // output, including `text` + `fleet` + `asyncSnapshot` riding together.
  const captured = JSON.parse(
    readFileSync(new URL("./fixtures/subagents-rpc-captured.json", import.meta.url), "utf8"),
  );
  const envelope = (id) => captured[id].event;
  const request = (id) => ({ requestId: id, method: "status" });

  // Active runs are accepted.
  for (const [id, runId] of [["real-0", "run-active"], ["real-1", "run-queued"]]) {
    assert.equal(
      mod.rpcReplyProvesCurrentOwner(envelope(id), request(id), runId),
      true,
      `${runId} is active in the REAL envelope`,
    );
  }
  // FINALIZED-PAUSED and terminal runs are rejected, even though the captured
  // envelope ALSO carries a projected `asyncSnapshot`.
  for (const [id, runId] of [
    ["real-2", "run-paused"],
    ["real-3", "run-complete"],
    ["real-4", "run-failed"],
    ["real-5", "run-stopped"],
  ]) {
    assert.equal(
      mod.rpcReplyProvesCurrentOwner(envelope(id), request(id), runId),
      false,
      `${runId} is not wake-capable in the REAL envelope`,
    );
  }
  // A mismatched run id is never proof.
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(envelope("real-0"), request("real-0"), "some-other-run"),
    false,
    "a real envelope for a different run is not proof",
  );
  // A run the real status code could NOT find is a FAILED reply, and a failed
  // reply is never proof. This is the real error case (the previous fixture
  // invented a `success: true` here).
  assert.equal(envelope("real-6").success, false, "an absent run yields a failed real reply");
  assert.equal(
    mod.rpcReplyProvesCurrentOwner(envelope("real-6"), request("real-6"), "run-absent"),
    false,
    "a failed real reply is not proof",
  );
  // The captured active envelope REALLY does carry a snapshot alongside the
  // authoritative text - the structural fact PG3 relies on.
  assert.ok(envelope("real-0").data.asyncSnapshot, "the real active envelope carries a snapshot");
  assert.ok(envelope("real-0").data.text.includes("State: running"), "and an authoritative text header");
});

test("RPCFIX: captured envelopes confirm the real targeted reply shape", () => {
  const captured = JSON.parse(
    readFileSync(new URL("./fixtures/subagents-rpc-captured.json", import.meta.url), "utf8"),
  );
  const env = captured["real-3"].event; // run-complete
  // The authoritative state lives in `text`; `details` is the single-run shape
  // with NO machine-readable state. Both were observed, not assumed.
  assert.equal(env.version, mod.SUBAGENT_RPC_VERSION, "protocol version matches");
  assert.equal(env.requestId, "real-3", "the envelope is correlated to its request id");
  assert.equal(env.method, "status", "the envelope names the method");
  // `details` hangs off the reply PAYLOAD (`data`), not the envelope root. The
  // captured envelope has no top-level `details` — asserting one there would be
  // reading a field the real bridge never emits.
  assert.equal(env.details, undefined, "the envelope root carries no details");
  assert.deepEqual(env.data.details, { mode: "single", results: [] }, "real single-run details shape");
  assert.equal(typeof env.data.text, "string", "the real reply carries a text transcript");
  assert.ok(env.data.text.includes("State: complete"), "with the authoritative state in the header");
  // The reply channel is the correlated per-request topic, recorded verbatim.
  assert.equal(captured["real-3"].channel, "subagents:rpc:v1:reply:real-3");
});

// ---------------------------------------------------------------------------
// CORR9: TUI-only reload verification, continue-scope restoration, and the
// session_start notification-epoch reset (review cycle 9)
// ---------------------------------------------------------------------------

test("R9-1: a reload/resume carried-WAIT verification is a TUI-ONLY effect", () => {
  // A reload in print/rpc/json mode used to run `verifyWait` from
  // `handleSessionStart`: one RPC request, one timer, and a possible OSC notice
  // - contaminating a noninteractive stdout. The verification EFFICIENT must be
  // gated by `isTui(ctx)`; provenance restoration is unaffected.
  const first = fakeClockHarness({ states: () => "running" });
  first.observeStart("oracle-1");
  const carried = first.persisted;

  // Non-TUI surfaces: NO RPC, NO timer, NO OSC. The `session_start` handler is
  // the only path that could verify here (`handleSettled` is TUI-gated), so a
  // bare reload emit is sufficient to expose the leak.
  for (const [label, mode] of [
    ["print", { hasUI: false, mode: "print" }],
    ["rpc", { hasUI: true, mode: "rpc" }],
    ["json", { hasUI: true, mode: "json" }],
  ]) {
    const h = fakeClockHarness({ entries: carried, states: () => "running" });
    const ctx = { ...mode, isIdle: () => true, sessionFile: h.sessionFile, sessionId: PARENT_UUID };
    const capture = captureStdout();
    try {
      h.pi.emit(
        "session_start",
        { type: "session_start", reason: "reload" },
        { ...ctx, sessionManager: sessionView([WAIT_ON("oracle-1")]) },
      );
      assert.equal(h.bus.rpcRequests.length, 0, `${label}: no RPC request outside a TUI`);
      assert.equal(h.pendingTimers(), 0, `${label}: no timer outside a TUI`);
      h.advance(WAIT_VERIFICATION_MS);
      assert.deepEqual(capture.chunks, [], `${label}: no OSC notice outside a TUI`);
    } finally {
      capture.restore();
    }
  }

  // TUI positive control: the verification still runs - one bounded RPC query.
  const tui = fakeClockHarness({ entries: carried, states: () => "running" });
  tui.pi.emit(
    "session_start",
    { type: "session_start", reason: "reload" },
    { ...tui.ctx, sessionManager: sessionView([WAIT_ON("oracle-1")]) },
  );
  assert.equal(tui.bus.rpcRequests.length, 1, "a TUI reload still verifies the carried WAIT");
  assert.equal(tui.bus.rpcRequests[0].method, "status", "via the read-only status method");
});

test("R9-2: restoration is continue-scope only; a non-continuing session_start repairs", async () => {
  // A same-UUID control at a persisted epoch: a foreign request's completed
  // Oracle assessment used to be accepted as verified after a `startup`/`new`/
  // `fork` (or omitted) `session_start`, because the restoration block ran
  // unconditionally. After the fix those reasons open a DIFFERENT scope and
  // inherit nothing, so the BLOCKED must run through decision repair.
  //
  // DISCRIMINATING SETUP: the witness session must have crossed ONE request
  // boundary before observing the run, so its persisted record lands on epoch 1
  // and generation 1. A non-continuing `session_start` then runs
  // `clearObservedRuns()` (epoch 0 -> 1), which persists the SAME generation 1 -
  // so the record passes the R6-6 generation gate and, with the scope gate
  // removed, is restored. This is the exact collision the defect needs; without
  // the intervening boundary the generation gate alone masks it.
  const build = () => {
    const dir = makeAsyncDir({ dir: "/async/oracle-r92", result: oracleResult({ dependencyId: "dep-1" }) });
    const files = new Map(dir.files);
    const first = fakeClockHarness({ states: () => "complete", files });
    first.pi.emit("input", { type: "input", text: "go", source: "interactive" }, first.ctx);
    first.observeStart("oracle-1", "oracle", dir.dir);
    const record = first.persisted.find((e) => e.customType === mod.PROVENANCE_CUSTOM_TYPE);
    assert.ok(record, "the first load persisted provenance for the observed run");
    assert.equal(record.data.requestEpoch, 1, "the witness crossed one boundary (epoch 1)");
    return { first, files };
  };

  for (const [label, reason] of [
    ["startup", "startup"],
    ["new", "new"],
    ["fork", "fork"],
    ["omitted", undefined],
  ]) {
    const { first, files } = build();
    const h = fakeClockHarness({ states: () => "complete", entries: first.persisted, files });
    const event = reason === undefined ? {} : { type: "session_start", reason };
    h.pi.emit("session_start", event, h.ctx);
    const result = await handlerFor(h.pi, "agent_before_settle")(
      boundaryEvent([assistant(BLOCKED_USER("oracle-1", "dep-1"))]),
      h.ctx,
    );
    assert.equal(result?.continue, true, `${label}: a non-continuing session_start must repair`);
    assert.equal(
      result?.entries?.at(-1)?.customType,
      mod.REPAIR_CUSTOM_TYPE,
      `${label}: the escalation is a decision repair, never silent acceptance`,
    );
  }

  // Positive control: a `reload` DOES continue the scope, so the same valid
  // escalation verifies and is NOT repaired.
  const { first, files } = build();
  const reloaded = fakeClockHarness({ states: () => "complete", entries: first.persisted, files });
  reloaded.pi.emit("session_start", { type: "session_start", reason: "reload" }, reloaded.ctx);
  const result = await handlerFor(reloaded.pi, "agent_before_settle")(
    boundaryEvent([assistant(BLOCKED_USER("oracle-1", "dep-1"))]),
    reloaded.ctx,
  );
  assert.notEqual(
    result?.entries?.at(-1)?.customType ?? null,
    mod.REPAIR_CUSTOM_TYPE,
    "a same-request reload control must NOT repair a valid escalation",
  );
});

test("R9-3: a prior stop's notification does not suppress a resumed WAIT's failure notice", () => {
  // A generic prior stop sets `notified`. A resume into an unowned WAIT whose
  // bounded verification fails must emit its OWN unverified notice; the dedup is
  // per session/verification epoch, and `session_start` opens a new one.
  const h = fakeClockHarness({ states: () => "running" });
  const capture = captureStdout();
  try {
    // A generic prior stop (e.g. a DONE boundary) emits the attention notice.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([assistant("All done.\n\nSTATUS:DONE")]),
    });
    assert.deepEqual(capture.chunks, [OSC_NOTIFY], "the prior stop notifies once");

    // Resume: a continuing session_start opens a new epoch.
    h.pi.emit("session_start", { type: "session_start", reason: "resume" }, h.ctx);

    // An unowned WAIT: no provenance, so the bounded verification never proves
    // the wake path and must emit its own notice.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("orphan-1")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY, OSC_UNVERIFIED_WAIT],
      "the resumed unverified WAIT gets its own notice after the epoch reset",
    );

    // Dedup still holds WITHIN the epoch: a second burst in the same session does
    // not emit another notice.
    h.pi.emit("agent_settled", settleEvent(), {
      ...h.ctx,
      sessionManager: sessionView([WAIT_ON("orphan-2")]),
    });
    h.advance(WAIT_VERIFICATION_MS);
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY, OSC_UNVERIFIED_WAIT],
      "dedup still holds within the resulting session epoch",
    );
  } finally {
    capture.restore();
  }
});

// ---------------------------------------------------------------------------
// CORR38 (TODO-S1S2-CORR38): the F1-F8 whole-unit batch. Each test pins ONE
// distinct container-relative root cause fixed together, and fails on the
// frozen s1s2-corr37 baseline:
//   R1 Markdown blankness is NOT JS `trim()`                  (F8)
//   R2 interruption indent is CONTAINER-RELATIVE              (F1a/F1b)
//   R3 the list-interrupt bar needs content + start 1, and a
//      NEW marker on a line is CONTENT, not a blank line       (F4a/F4b)
//   R4 a DEDENTED list marker starts a block regardless of bar (F7a/F7b)
//   R5 the HTML type-4 terminator reads container-stripped text (F6)
//   R6 an EMPTY list item's content column is marker width + 1  (F5)
//   R7 a PHANTOM container's fence closes on a dedenting closer (F2b/F2d/F3b)
// Every live row asserts `{continue:true, entries:1}` through the REAL
// settle-time proposal; every dead row asserts no marker and no proposal.
// ---------------------------------------------------------------------------

test("CORR38 R1: a NON-ASCII whitespace line is paragraph CONTENT, not a blank line (both directions)", async () => {
  // Markdown blankness is spaces/tabs only; U+00A0 NO-BREAK SPACE is content.
  // A `trim()`-based test read the NBSP line as blank, ended the quoted
  // paragraph, and promoted the column-zero declaration to document level.
  const pi = armed();
  const nb = "\u00a0";
  for (const [label, body] of [
    ["nbsp", nb],
    ["nbsp-run", `${nb}${nb}`],
    ["nbsp-para", `x${nb}x`],
  ]) {
    const dead = ["> p", body, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(dead)), "unknown", `${label}: NBSP continues the quote => DEAD`);
    assert.equal(await isExcluded(pi, dead), true, `${label}: no proposal for a swallowed declaration`);
  }
  // DISCRIMINATING COMPANION: a genuinely blank line still ends the quote.
  const blank = ["> p", "", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(blank)), "continue", "a real blank line ends the quote");
  assert.equal(await isLive(pi, blank), true, "a real blank line leaves the declaration live");
});

test("CORR38 R2: FOUR-column indentation after a quoted paragraph is INDENTED CODE, so it cannot interrupt (both directions)", async () => {
  // The indent is measured RELATIVE to the open container: `>     <div>` and
  // `>     ---` are four columns of content (indented code), which CommonMark
  // never lets interrupt a paragraph. A double `^ {0,3}` strip dedented them to
  // a legal marker and made the declaration below live.
  const pi = armed();
  for (const [label, tag] of [["html", "<div>"], ["thematic", "---"], ["heading", "# H"]]) {
    const dead = ["> p", `>     ${tag}`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(dead)), "unknown", `${label}: 4-col indent is code => DEAD`);
    assert.equal(await isExcluded(pi, dead), true, `${label}: no proposal`);
  }
  // DISCRIMINATING COMPANION: up to THREE columns still interrupts.
  const live = ["> p", ">    # H", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(live)), "continue", "<=3 columns of heading interrupts");
  assert.equal(await isLive(pi, live), true, "the heading exit leaves the declaration live");
});

test("CORR38 R3: an EMPTY or start!=1 list marker cannot interrupt, and a NEW marker is content not a blank line (both directions)", async () => {
  // `> p` then `> +` / `> 2.` stays ONE quoted paragraph: a bullet with no
  // content and an ordered marker not starting at 1 cannot interrupt. Reading
  // the new marker as a blank content line ended the paragraph and made the
  // declaration live.
  const pi = armed();
  for (const [label, marker] of [["bare-bullet", "+"], ["ordered-2", "2."], ["ordered-2-space", "2. "]]) {
    const dead = ["> p", `> ${marker}`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(dead)), "unknown", `${label}: cannot interrupt => DEAD`);
    assert.equal(await isExcluded(pi, dead), true, `${label}: no proposal`);
  }
  // DISCRIMINATING COMPANION: a start-at-1 ordered marker WITH content DOES
  // interrupt the paragraph, so the heading it opens leaves the declaration
  // document level (the bar was not simply removed).
  const live = ["text", "1. # H", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(live)), "continue", "a start-1 non-empty marker interrupts");
  assert.equal(await isLive(pi, live), true, "the interrupt leaves the declaration live");
});

test("CORR38 R4: block-start eligibility is RELATIVE to the paragraph's containers - a DEDENTED marker starts a block (both directions)", async () => {
  // A list marker that DEDENTS out of the paragraph's own container has already
  // left the paragraph's block, so it starts a new block even though it could
  // not interrupt a top-level paragraph: `1. text` / `2. # H` and `> p` /
  // `2. # H` leave the declaration document-level.
  const pi = armed();
  for (const [label, text] of [
    ["list-then-new-item-heading", "1. text\n2. # H\nSTATUS:CONTINUE p"],
    ["quote-then-dedented-marker-heading", "> p\n2. # H\nSTATUS:CONTINUE p"],
  ]) {
    assert.equal(mod.declaredStatusOf(assistant(text)), "continue", `${label}: dedent starts a block => LIVE`);
    assert.equal(await isLive(pi, text), true, `${label}: the declaration proposes a continuation`);
  }
  // DISCRIMINATING COMPANION: a TOP-LEVEL paragraph keeps the strict bar, so a
  // bare/start!=1 marker is still a lazy continuation (DEAD).
  const dead = ["text", "5. x", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(dead)), "unknown", "a top-level paragraph is not interrupted by 5.");
  assert.equal(await isExcluded(pi, dead), true, "no proposal");
});

test("CORR38 R5: an HTML type-4 terminator is read on CONTAINER-STRIPPED content, not the raw line", async () => {
  // `<![...` ends at a line containing `>`. In `> <!DOCTYPE` the terminator `>`
  // is the BLOCKQUOTE's own marker (empty content), so the block keeps
  // absorbing `> more` and the declaration below is document level. Testing the
  // raw line matched `>` and closed the block early, losing the declaration.
  const pi = armed();
  const live = ["> <!DOCTYPE", ">", "> more", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(live)), "continue", "the quote's own marker is not the terminator");
  assert.equal(await isLive(pi, live), true, "the declaration proposes a continuation");
  // DISCRIMINATING COMPANION: a terminator IN the content still ends the block.
  const tb = ["<!DOCTYPE", ">", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(tb)), "continue", "a real content `>` terminator closes the block");
  assert.equal(await isLive(pi, tb), true, "the closed block leaves the declaration live");
});

test("CORR38 R6: an EMPTY list item's content column is marker width + 1, not the separator width (both directions)", async () => {
  // `-  ` (two trailing spaces) is an EMPTY item whose content column is 2, so
  // `  ```text` still belongs to the item. Using the separator width made it 3,
  // the fence dedented to document level, and the declaration was lost.
  const pi = armed();
  for (const [dl, d] of DELIMS) {
    const live = ["-  ", `  ${d}text`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(live)), "continue", `${dl}: empty item width is marker+1`);
    assert.equal(await isLive(pi, live), true, `${dl}: the declaration proposes a continuation`);
  }
  // DISCRIMINATING COMPANION: a NON-empty over-wide separator keeps its content
  // indent, so `-     ```text` is indented code and no fence opens.
  for (const [dl, d] of DELIMS) {
    const over = ["-     " + d + "text", "", "STATUS:CONTINUE p"].join("\n");
    assert.equal(await isLive(pi, over), true, `${dl}: over-wide separator is indented code, declaration live`);
  }
});

test("CORR38 R7: a BLANK after a thematic break / setext underline / empty item leaves their fence at document level, so a dedenting closer CLOSES it", async () => {
  // A `* * *` thematic break and a setext `-` underline are NOT list items at
  // all (CommonMark 4.1/4.3), and an INITIALLY EMPTY item is ended by the blank
  // that follows its marker (CommonMark 5.1). In every case the fence on the
  // next line opens at DOCUMENT level, so a closer-only delimiter that dedents
  // out simply CLOSES it and the unmarked declaration below is a document-level
  // paragraph (LIVE). The BLANK is what makes these shapes document level: see
  // CORR42 R1/R2 for the same heads WITHOUT a blank, where a surviving real item
  // owns the fence and the closer RE-OPENS it instead. (This test previously
  // described the heads as "phantom containers with no lifetime"; that model was
  // replaced by the CORR42 normalization, but these expectations were already
  // correct and are unchanged.)
  const pi = armed();
  for (const [dl, d] of DELIMS) {
    for (const [label, head] of [
      ["thematic-break", "* * *"],
      ["setext-underline", "H\n-"],
      ["empty-item", "-"],
    ]) {
      const headLines = head.split("\n");
      const closed = [...headLines, "", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
      // The empty-item shape carries an extra blank line, as in the defect.
      const text = label === "empty-item"
        ? ["-", "", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n")
        : closed;
      assert.equal(mod.declaredStatusOf(assistant(text)), "continue", `${label} ${dl}: the blank puts the fence at document level, so the closer closes it`);
      assert.equal(await isLive(pi, text), true, `${label} ${dl}: the declaration proposes a continuation`);
    }
  }
  // DISCRIMINATING COMPANION: a fence held by a REAL container still re-opens on
  // a dedenting opener line, so the declaration stays excluded.
  for (const [dl, d] of DELIMS) {
    const real = ["- " + d + "text", "  example", d + d + d + "text", "", "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(real)), "unknown", `${dl}: a real container re-opens the fence`);
    assert.equal(await isExcluded(pi, real), true, `${dl}: no proposal`);
  }
});

// --- CORR39: the leaf walk's blankness test is `markdownBlank`, not `trim()` --

test("CORR39 R1: an NBSP-only QUOTED leaf is paragraph CONTENT, so a declaration beneath it is DEAD (both directions)", async () => {
  // DEFECT A20. A blockquote whose first leaf line is a single U+00A0 NO-BREAK
  // SPACE is `document>block_quote>paragraph` per CommonMark@0.31.2, so the
  // column-zero declaration below is INSIDE the quote and DEAD. `leafBlockOf`
  // used `content.trim()`, which strips U+00A0, classified the leaf `"none"`,
  // ended the paragraph, and promoted the declaration to document level - the
  // `trim()` regression of DEFECT F8 in the leaf walk. The single blankness
  // predicate `markdownBlank` (spaces/tabs only) restores the invariant.
  const pi = armed();
  const nb = "\u00a0";
  // A20: NBSP as the FIRST quoted leaf.
  const dead = [">" + nb, "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(dead)), "unknown", "an NBSP-only quoted leaf is a paragraph => DEAD");
  assert.equal(await isExcluded(pi, dead), true, "no proposal for a swallowed declaration");
  // COMPANION 1 (the asymmetry that is the whole point): an ordinary SPACE as
  // the first leaf is BLANK, so no paragraph opens and the declaration is
  // document level => LIVE.
  const spaceLive = ["> ", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(spaceLive)), "continue", "a space-only quoted leaf is blank => LIVE");
  assert.equal(await isLive(pi, spaceLive), true, "the declaration proposes a continuation");
  // COMPANION 2 (the existing F8/R1 row): an NBSP on a CONTINUATION line is
  // paragraph content, so the declaration stays DEAD.
  const deadCont = ["> p", nb, "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(deadCont)), "unknown", "an NBSP continuation line keeps the quote open => DEAD");
  assert.equal(await isExcluded(pi, deadCont), true, "no proposal");
  // COMPANION 3: a genuinely blank line ends the quote => LIVE.
  const blankLive = ["> p", "", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(blankLive)), "continue", "a real blank line ends the quote => LIVE");
  assert.equal(await isLive(pi, blankLive), true, "the declaration proposes a continuation");
  // COMPANION 4: a fence opened inside an empty list item that sits INSIDE a
  // real quote (DEFECT A22). The dedented delimiter ends BOTH the quote and the
  // fence, then re-opens a DOCUMENT-LEVEL fence (CommonMark@0.31.2 AST:
  // `document>block_quote>list>item>code_block` (empty) followed by
  // `document>code_block "STATUS:CONTINUE p\n"`), so the declaration is FENCED
  // CODE and DEAD, not a continuation. The phantom-closer path must NOT consume
  // the delimiter when a REAL container also held the fence; it must fall
  // through to the fresh-opener path so the same line is reclassified.
  for (const [dl, d] of DELIMS) {
    const fenced = ["> -", `>   ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(fenced)), "unknown", `${dl}: the quote/list fence re-opens at document level => DEAD`);
    assert.equal(await isExcluded(pi, fenced), true, `${dl}: no proposal for a declaration inside a document-level fence`);
  }
});

// --- CORR41: HTML-block type-1/type-6 boundaries accept ANY `\s` (DEFECT A21) --
test("CORR41 R1: an HTML tag name followed by Unicode whitespace still opens the block, so a declaration beneath it is LIVE (both directions)", async () => {
  // DEFECT A21. CommonMark@0.31.2 recognises an HTML block of type 1
  // (`script|pre|textarea|style`) when the tag name is followed by `\s`, `>`, or
  // EOL, and of type 6 when a block tag name is followed by `\s`, `[/]?[>]`, or
  // EOL (reference grammar: /private/tmp/node_modules/commonmark/lib/blocks.js
  // lines 18 and 23). The product required only `[ \t]`, so a tag name followed
  // by U+00A0 NO-BREAK SPACE did NOT open the block: the quoted line stayed a
  // PARAGRAPH, the quote stayed open, and the column-zero declaration beneath it
  // was swallowed as a lazy continuation - a FALSE NEGATIVE. The ordinary-SPACE
  // variants were already correct, so only the Unicode-whitespace boundary is
  // covered here (prod risk: an editor or model emitting NBSP inside HTML).
  //
  // This row is APPEND-ONLY suite coverage for A21, which the CORR40 batch
  // proved load-bearing by PROBE only (reverting the `\s` restoration left the
  // suite green at 303/303). Without this test a future refactor could restore
  // the `[ \t]` boundary silently.
  const pi = armed();
  const nb = "\u00a0";
  // Type 1 (`script`): the NBSP-terminated tag opens the HTML block, which is the
  // quote's LAST leaf, so the unmarked declaration below is document level.
  const script = ["> <script" + nb, "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(script)), "continue", "an NBSP after a type-1 tag name opens the block => LIVE");
  assert.equal(await isLive(pi, script), true, "the declaration proposes a continuation");
  // Type 6 (`div`): interrupts the quoted paragraph, then the quote ends.
  const div = ["> p", "> <div" + nb + ">", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(div)), "continue", "an NBSP after a type-6 tag name interrupts the paragraph => LIVE");
  assert.equal(await isLive(pi, div), true, "the declaration proposes a continuation");
  // COMPANION 1: the ordinary-SPACE variants are the SAME answer, which is what
  // makes the NBSP case a defect rather than an intentional distinction.
  const scriptSpace = ["> <script ", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(scriptSpace)), "continue", "the SPACE variant stays LIVE");
  const divSpace = ["> p", "> <div >", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(divSpace)), "continue", "the SPACE variant stays LIVE");
  // COMPANION 2 (the A20/F8 asymmetry, preserved): an NBSP is ordinary paragraph
  // CONTENT on a CONTINUATION line, and as the FIRST quoted leaf. Routing A21
  // through `markdownBlank` would have broken BOTH of these.
  const cont = ["> p", nb, "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(cont)), "unknown", "an NBSP continuation keeps the quote open => DEAD");
  assert.equal(await isExcluded(pi, cont), true, "no proposal");
  const firstLeaf = [">" + nb, "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(firstLeaf)), "unknown", "an NBSP-only first leaf is a paragraph => DEAD");
  assert.equal(await isExcluded(pi, firstLeaf), true, "no proposal");
  // COMPANION 3 (type-7 must NOT interrupt): a COMPLETE tag line is not a type-6
  // block, so the `\s` restoration must not have widened the type-7 case.
  const type7 = ["> p", "> <x>", "STATUS:CONTINUE p"].join("\n");
  assert.equal(mod.declaredStatusOf(assistant(type7)), "unknown", "a type-7 tag line stays a lazy continuation => DEAD");
  assert.equal(await isExcluded(pi, type7), true, "no proposal");
});

// --- CORR42: container lifetime normalization (DEFECTS A23, A24) --------------
test("CORR42 R1: an initially empty REAL item OWNS its fence, so a dedenting closer RE-OPENS it (A23)", async () => {
  // DEFECT A23. `-` with NO blank after it is a REAL CommonMark list item that
  // is still CHILDLESS. The indented fence becomes its child, so the item owns
  // it; the column-zero delimiter then exits the item, ends the item-held fence,
  // and OPENS A FRESH DOCUMENT-LEVEL FENCE. The declaration beneath it is
  // therefore FENCED CODE. CommonMark@0.31.2 AST:
  //   document>list[1:1-2:9]>item[1:1-2:9]>code_block[2:3-2:9]
  //   document>code_block[3:1-4:17]  "STATUS:CONTINUE p\n"
  // => DEAD. The product used to treat the empty item as a fictitious "phantom"
  // container with no lifetime, consume the delimiter as a bare closer, and
  // admit the declaration (false positive). Contrast CORR38 R7: the SAME head
  // WITH a blank leaves the fence document level, so the closer merely closes it
  // and the declaration is a paragraph (LIVE).
  const pi = armed();
  for (const [dl, d] of DELIMS) {
    const text = ["-", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(text)), "unknown", `${dl}: the item owns the fence, the closer re-opens it => DEAD`);
    assert.equal(await isExcluded(pi, text), true, `${dl}: no proposal inside the re-opened document fence`);
    // COMPANION A: the width-2 empty item `-  ` behaves identically.
    const wide = ["-  ", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(wide)), "unknown", `${dl}: \`-  \` is still an initially empty real item => DEAD`);
    assert.equal(await isExcluded(pi, wide), true, `${dl}: no proposal`);
    // COMPANION B (the F5 false negative this must not regress): the same head
    // with NO closer line leaves the fence OPEN across the item's exit, so the
    // declaration dedents out and IS a document paragraph.
    const open = ["-", `  ${d}text`, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(open)), "continue", `${dl}: no closer => the declaration exits the unclosed fence => LIVE`);
    assert.equal(await isLive(pi, open), true, `${dl}: the declaration proposes a continuation`);
    // COMPANION C: with the blank, the item is already dead, the fence is at
    // document level, and the closer simply ends it (the R7 row).
    const blanked = ["-", "", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(blanked)), "continue", `${dl}: a blank ends the childless item => the closer just closes => LIVE`);
  }
});

test("CORR42 R2: a thematic break and a setext underline open NO item, so their fence is at document level (A24/A25/A26)", async () => {
  // A `* * *` THEMATIC BREAK (CommonMark 4.1) and a `H`/`-` SETEXT UNDERLINE
  // (4.3) are leaves, not containers: recognizing them through the list-marker
  // grammar created FICTITIOUS items (`* * *` -> `* *` -> `*`), so a fence
  // beneath them looked item-owned and a dedenting closer re-opened a document
  // fence that swallowed the declaration. With the normalization the fence is
  // already at document level and the closer just CLOSES it. Note the
  // discriminating contrast with CORR42 R1: there a REAL childless item owns the
  // fence, so the same closer re-opens it instead.
  const pi = armed();
  for (const [dl, d] of DELIMS) {
    // No closer: the document-level fence stays open over the declaration.
    for (const [label, head] of [["thematic-break", "* * *"], ["setext-underline", "H\n-"]]) {
      const openText = [...head.split("\n"), `  ${d}text`, "STATUS:CONTINUE p"].join("\n");
      assert.equal(mod.declaredStatusOf(assistant(openText)), "unknown", `${label} ${dl}: no item => the document fence holds the declaration => DEAD`);
      assert.equal(await isExcluded(pi, openText), true, `${label} ${dl}: no proposal`);
      // With a closer the document-level fence closes and the declaration is a
      // document paragraph.
      const closedText = [...head.split("\n"), `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
      assert.equal(mod.declaredStatusOf(assistant(closedText)), "continue", `${label} ${dl}: the closer ends the document fence => LIVE`);
      assert.equal(await isLive(pi, closedText), true, `${label} ${dl}: the declaration proposes a continuation`);
    }
    // A quoted thematic break: the real QUOTE never ends. Its fence closes, then
    // `> more` opens a quoted paragraph whose unmarked declaration line is a
    // LAZY CONTINUATION of that paragraph => DEAD.
    const quoted = ["> * * *", `>   ${d}text`, `> ${d}`, "> more", "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(quoted)), "unknown", `${dl}: the real quote survives and lazily continues => DEAD`);
    assert.equal(await isExcluded(pi, quoted), true, `${dl}: no proposal for a lazy continuation of a quoted paragraph`);
  }
});

test("CORR43 R1: an initially empty item that ACQUIRES a child is real for good, so a later blank does not end it (A28)", async () => {
  // DEFECT A28. An initially EMPTY item (`-`) is ended by a blank only WHILE it
  // is still childless (CommonMark 5.1). Once a child block begins inside it the
  // item is permanent, so a LATER blank no longer ends it - and a fence opened
  // after that blank is still item-held, making a dedenting closer re-open a
  // document-level fence that swallows the declaration. CommonMark@0.31.2 AST:
  //   document>list[1:1-4:9]>item[1:1-4:9]>paragraph[2:3-2:7] "child"
  //                                   >item>code_block[4:3-4:9] ""
  //   document>code_block[5:1-6:17] "STATUS:CONTINUE p\n"   => DEAD
  // The product kept `childless:true` from the marker forever, so the blank
  // discarded the surviving item and the declaration read as LIVE.
  const pi = armed();
  for (const [dl, d] of DELIMS) {
    const acquired = ["-", "  child", "", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(acquired)), "unknown", `${dl}: the acquired-child item survives the blank => DEAD`);
    assert.equal(await isExcluded(pi, acquired), true, `${dl}: no proposal inside the re-opened document fence`);
    // COMPANION A (the discriminating contrast): an item that was NEVER empty
    // has the SAME AST shape and must agree.
    const nonEmpty = ["- child", "", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(nonEmpty)), "unknown", `${dl}: a never-empty item => DEAD`);
    assert.equal(await isExcluded(pi, nonEmpty), true, `${dl}: no proposal`);
    // COMPANION B (the A23/R7 control this must not regress): an item that stays
    // CHILDLESS is still ended by the blank, so the fence is document level and
    // the closer merely closes it.
    const stillEmpty = ["-", "", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(stillEmpty)), "continue", `${dl}: a still-childless item dies at the blank => LIVE`);
    assert.equal(await isLive(pi, stillEmpty), true, `${dl}: the declaration proposes a continuation`);
    // COMPANION C: a CHILDLESS item with no blank still OWNS its fence, so the
    // closer re-opens it (the CORR42 R1 row, unchanged by this fix).
    const owns = ["-", `  ${d}text`, d + d + d, "STATUS:CONTINUE p"].join("\n");
    assert.equal(mod.declaredStatusOf(assistant(owns)), "unknown", `${dl}: no blank => the item owns the fence => DEAD`);
    assert.equal(await isExcluded(pi, owns), true, `${dl}: no proposal`);
  }
});

test("CORR44 R1: a CONTAINER-RELATIVE blank ends a still-childless item but not a child-bearing one (A29/A30)", async () => {
  // DEFECTS A29 and A30 - ONE wrong blank test, wrong in BOTH directions.
  // `>   ` (container-content blank) and `>` (physically blank) are both BLANK
  // LINES in CommonMark's sense once the quote marker is stripped; the physical
  // `markdownBlank` answered a different question. A29: `>   ` is physically
  // nonblank, so a CHILDLESS item survived a line that must end it and a DEAD
  // quoted paragraph was read LIVE (false positive). A30: `>` is physically
  // blank but the item had a child, which CommonMark keeps open
  // (`item.continue`'s `parser.blank` branch runs BEFORE the indent test), so a
  // LIVE document paragraph was read DEAD (false negative). Both fix at the one
  // container-relative blank rule in `resolveLine`.
  const pi = armed();
  // The declaration sits in a QUOTED paragraph (block_quote>paragraph), so it
  // is DEAD whatever the fence delimiting does.
  const deadQuoted = (d) => ["> -", ">   ", `>   ${d}text`, `> ${d}`, "> more", "STATUS:CONTINUE p"].join("\n");
  const deadQuotedBlank = (d) => ["> -", ">", `>   ${d}text`, `> ${d}`, "> more", "STATUS:CONTINUE p"].join("\n");
  // The child-bearing item survives, the fact is document-level => LIVE.
  const liveDoc = (d) => ["> - child", ">", `>   ${d}text`, `> ${d}`, "> more", "STATUS:CONTINUE p"].join("\n");
  const liveDocSpaces = (d) => ["> - child", ">   ", `>   ${d}text`, `> ${d}`, "> more", "STATUS:CONTINUE p"].join("\n");
  for (const [dl, d] of DELIMS) {
    for (const [label, text] of [["A29 `>   `", deadQuoted(d)], ["A29 `>`", deadQuotedBlank(d)]]) {
      assert.equal(mod.declaredStatusOf(assistant(text)), "unknown", `${dl} ${label}: the empty item ends => the declaration is a QUOTED paragraph => DEAD`);
      assert.equal(await isExcluded(pi, text), true, `${dl} ${label}: no proposal`);
    }
    for (const [label, text] of [["A30 `>`", liveDoc(d)], ["A30 `>   `", liveDocSpaces(d)]]) {
      assert.equal(mod.declaredStatusOf(assistant(text)), "continue", `${dl} ${label}: a child-bearing item survives => the declaration is DOCUMENT level => LIVE`);
      assert.equal(await isLive(pi, text), true, `${dl} ${label}: the declaration proposes a continuation`);
    }
  }
});

test("CORR51 R1: a THOUSANDS-deep quoted nesting still resolves a genuine CONTINUE (no call-stack overflow)", async () => {
  // DEFECT (found by independent Review, confirmed by parent execution): the
  // block walk was RECURSIVE (`rec(node) { ... rec(child) ... }`), consuming one
  // JavaScript stack frame per nesting level. A message nested 20,000 levels deep
  // threw `RangeError: Maximum call stack size exceeded` BEFORE marker extraction
  // returned, so `handleBeforeSettle` never reached its bridge or its notice and a
  // genuine printed CONTINUE stopped silently - user complaint #1. The walk is now
  // ITERATIVE; its depth is bounded only by input, never by the host stack.
  //
  // The input is the parent-reproduced shape: N `> ` quote levels, a fenced
  // example, then an unmarked final line. The final line exits the quoted fence
  // and begins a DOCUMENT-level paragraph, so the declaration is genuinely LIVE
  // with payload `p`. Both the public marker surface and the real settle-time
  // proposal must agree, at every depth.
  const pi = armed();
  for (const depth of [2000, 10000, 20000]) {
    const text = "> ".repeat(depth) + "```text\nSTATUS:CONTINUE p";
    const marker = mod.readDeclaredMarker(assistant(text));
    assert.deepEqual(
      { status: marker?.status, payload: marker?.payload },
      { status: "continue", payload: "p" },
      `${depth}-deep: the unmarked final line exits the fence => LIVE`,
    );
    assert.equal(await isLive(pi, text), true, `${depth}-deep: the declaration proposes a continuation`);
  }
});

test("CORR51 R2: a declaration genuinely INSIDE an open fence at comparable depth is still EXCLUDED", async () => {
  // The fix must not trade the false negative above for a FALSE POSITIVE. A
  // declaration that sits INSIDE an open fence at the same nesting depth is not a
  // declaration at all; it must read `unknown` and propose no continuation. This
  // is the direction that a too-eager traversal could break.
  const pi = armed();
  for (const depth of [2000, 10000, 20000]) {
    // The final line stays INSIDE the tailored fence (no closer), so it is fence
    // CONTENT at document level and must never declare.
    const text = "> ".repeat(depth) + "```text\nSTATUS:CONTINUE p";
    const open = "> ".repeat(depth) + "```text\n> STATUS:CONTINUE p";
    const marker = mod.readDeclaredMarker(assistant(open));
    assert.notEqual(marker?.status, "continue", `${depth}-deep: an inside-fence line is not a declaration`);
    assert.equal(await isExcluded(pi, open), true, `${depth}-deep: no proposal inside the open fence`);
    // Control: the same depth with the fence EXITED is LIVE (the R1 direction),
    // so the two rows discriminate rather than both reading the same answer.
    assert.equal(await isLive(pi, text), true, `${depth}-deep control: exiting the fence is LIVE`);
  }
});

test("CORR51 R3: a parser failure at the boundary NOTIFIES the user instead of throwing out of the handler", async () => {
  // DEFENSIVE, same root cause. `handleBeforeSettle` reads the marker BEFORE it
  // can emit a bridge or a notice. An UNCAUGHT parser failure therefore produced
  // NEITHER - an unhandled error the host swallows, with no continuation proposal
  // and no notice, which is a DIFFERENT silent stop from the one R1 fixes. The
  // boundary now degrades a parser throw to the safe documented default: no
  // proposal, and the attention notice fires.
  //
  // Reachability: drive a REAL registered handler through a TEMP copy of the
  // product whose `lineStructure` throws (a parser failure), so the guard is
  // exercised end-to-end rather than asserted from its source text.
  const src = readFileSync(tsPath, "utf8");
  const marker = "function lineStructure(text: string): LineStructure {";
  assert.ok(src.includes(marker), "the parser entry point exists to mutate");
  const mutated = src.replace(marker, `${marker}\n  throw new RangeError("injected parser failure");`);
  assert.notEqual(mutated, src, "the mutation must apply");
  const root = mkdtempSync(join(tmpdir(), "supervisor-corr51-"));
  try {
    const mutantPath = join(root, "session-supervisor-mutant.ts");
    writeFileSync(mutantPath, mutated);
    const mutant = await import(mutantPath);
    const pi = makePi();
    mutant.registerSessionSupervisor(pi, {});
    // A genuine handshake so the boundary is armed.
    pi.emit("input", { type: "input", text: "request", source: "interactive" }, UI);
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "request" }, UI);
    pi.emit("message_start", { type: "message_start", message: { role: "user", content: "request" } }, UI);

    const capture = captureStdout();
    let result;
    let threw = null;
    try {
      result = handlerFor(pi, "agent_before_settle")(
        boundaryEvent([assistant("STATUS:CONTINUE p")]),
        UI,
      );
    } catch (error) {
      threw = error;
    } finally {
      capture.restore();
    }
    assert.equal(threw, null, "a parser failure must NOT throw out of the boundary handler");
    assert.equal(result ?? null, null, "no continuation proposal is made on a parser failure");
    assert.ok(capture.chunks.includes(OSC_NOTIFY), "the user IS notified - no silent stop");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// FEATURE 3: scheduled tasks
//
// A durable, session-owned timer. The model declares a task on a `TASK:ADD`
// action line; this extension fires `api.sendUserMessage` into the SAME session
// when the task comes due. The tests below drive the REAL factory through
// `registerSessionSupervisor` with an injected clock, scheduler and temp store.
// ---------------------------------------------------------------------------

/**
 * A deterministic FEATURE3 harness.
 *
 * `now` is a mutable fake clock; `schedule` records absolute due times and
 * `advance` runs only the callbacks that come due, in order. Every registration
 * gets a fresh temp `tasks.json`, so no test touches the real store. The fake
 * `pi` records each `sendUserMessage` in `injected`.
 */
function feature3Harness({ sessionId = PARENT_UUID, tasksPath = null, streaming = false, compacting = false } = {}) {
  let now = 1_000_000;
  let seq = 0;
  const timers = [];
  const injected = [];
  const sentOptions = [];
  let compactingNow = compacting;
  const dir = mkdtempSync(join(tmpdir(), "supervisor-f3-"));
  const path = tasksPath ?? join(dir, "session-supervisor", "tasks.json");
  // Oracle OPTION D: the commit point is the PERSISTED TRANSCRIPT, so the harness
  // models an ACCEPTING host by appending the delivered message to a per-session
  // session JSONL. `getSessionFile` is deliberately NOT set on the manager
  // (identity must stay the sid); the direct `sessionFile` is the real host's
  // fixture fallback and leaves `sessionIdentity` unchanged because
  // `manager.getSessionId()` still wins.
  const sessionFiles = new Map();
  // The session whose transcript a delivered message is persisted to. Updated
  // every time a context is built for an emitted event, which is exactly when the
  // live session is (re)established.
  let lastSid = sessionId ?? PARENT_UUID;
  const sessionFileFor = (sid) => {
    const existing = sessionFiles.get(sid);
    if (existing !== undefined) return existing;
    const file = join(dir, "sessions", `${sid}.jsonl`);
    mkdirSync(dirname(file), { recursive: true });
    sessionFiles.set(sid, file);
    return file;
  };
  /** Append one delivered user message to a session's persisted transcript. */
  const persistUserMessage = (sid, text) => {
    const file = sessionFileFor(sid);
    mkdirSync(dirname(file), { recursive: true });
    const row = {
      type: "message",
      id: `m${++seq}`,
      message: { role: "user", content: [{ type: "text", text }], timestamp: now },
    };
    appendFileSync(file, `${JSON.stringify(row)}\n`);
  };
  const pi = makePi();
  pi.sendUserMessage = (text, options) => {
    injected.push(text);
    sentOptions.push(options);
    // An ACCEPTING host persists the message into the LIVE session's transcript;
    // a refusing host does not persist at all.
    persistUserMessage(lastSid, text);
    return undefined;
  };
  mod.registerSessionSupervisor(pi, {
    tasksPath: path,
    now: () => now,
    schedule: (run, ms) => {
      // Faithful to Node: a delay above 2^31-1 ms is CLAMPED TO 1 MS with a
      // `TimeoutOverflowWarning`, not saturated to the cap. Reproduced here so a
      // task booked beyond ~24.855 days fires almost immediately unless the
      // product clamps and re-arms. Measured on Node: requesting 2592000000 ms
      // yields `_idleTimeout === 1`.
      const effective = ms > 2147483647 ? 1 : ms;
      const handle = { run, due: now + effective, id: ++seq, requested: ms, effective };
      timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      const index = timers.indexOf(handle);
      if (index >= 0) timers.splice(index, 1);
    },
  });
  const ctxFor = (sid) => {
    lastSid = sid;
    return {
      ...UI,
      isIdle: () => !streaming && !compactingNow,
      sessionId: sid,
      sessionFile: sessionFileFor(sid),
      sessionManager: { getSessionId: () => sid, buildSessionProjection: () => ({ messages: [] }) },
    };
  };
  // The host exposes ONLY `isIdle()` on the extension surface
  // (`extensions/types.d.ts:236`) and `isCompacting` is an `AgentSession` getter
  // (`agent-session.js:1204`) that is NOT reachable from a plugin, so the product
  // CANNOT read either one to detect compaction. The only production-observable
  // signal is the compaction EVENT PAIR (`extensions/types.d.ts:587-610`), so this
  // harness drives compaction by EMITTING those events - the same way the host
  // does - rather than by installing an invented API surface.
  const emitCompactionStart = () => {
    compactingNow = true;
    pi.emit("session_before_compact", { type: "session_before_compact", reason: "threshold" }, ctxFor(PARENT_UUID));
  };
  const emitCompactionEnd = (ok = true) => {
    compactingNow = false;
    const name = ok ? "session_compact" : "session_compact_failed";
    pi.emit(name, { type: name, fromExtension: false, reason: "threshold", willRetry: false }, ctxFor(PARENT_UUID));
  };
  // Review 79 R79-P1: the host AWAITS `session_compact` and only THEN clears its
  // compaction abort controller (`agent-session.js:2239` vs `:2253`), so a send
  // is still refused when that event fires; the extension gets no
  // `compaction_end`, so the first send-ready boundary it can observe is a
  // settle. This drives that boundary the same way the host does.
  const emitSettleAfterCompaction = () => {
    pi.emit("agent_settled", { type: "agent_settled" }, ctxFor(PARENT_UUID));
  };
  const advance = (ms) => {
    const target = now + ms;
    let guard = 0;
    for (;;) {
      let next = null;
      for (const handle of timers) {
        if (handle.due <= target && (next === null || handle.due < next.due)) next = handle;
      }
      if (next === null || guard++ > 100000) break;
      now = Math.max(now, next.due);
      timers.splice(timers.indexOf(next), 1);
      next.run();
    }
    now = target;
  };
  const sessionStart = (sid, reason = "startup") =>
    pi.emit("session_start", { type: "session_start", reason }, ctxFor(sid));
  const declare = (sid, text) => {
    // The boundary handler notifies in TUI mode; capture that OSC output so the
    // FEATURE3 cases do not pollute the reporter stream.
    const capture = captureStdout();
    try {
      pi.emit("agent_before_settle", boundaryEvent([assistant(text)]), ctxFor(sid));
    } finally {
      capture.restore();
    }
  };
  const settle = (sid) => {
    const capture = captureStdout();
    try {
      pi.emit("agent_settled", settleEvent(), ctxFor(sid));
    } finally {
      capture.restore();
    }
  };
  const store = () => {
    try {
      return JSON.parse(readFileSync(path, "utf8"));
    } catch {
      return { tasks: [] };
    }
  };
  return {
    pi,
    injected,
    sentOptions,
    advance,
    sessionStart,
    declare,
    settle,
    // FINAL REVIEW F1: the compaction release is deferred with `queueMicrotask`,
    // so it lands just AFTER the terminal compaction handler returns - the point
    // at which the host runs `_clearManualCompactionState()`. Tests must drain
    // microtasks instead of manufacturing a settlement the manual `/compact`
    // path never emits (`agent-session.js:2242-2261`).
    flushMicrotasks: async () => {
      await Promise.resolve();
      await Promise.resolve();
    },
    store,
    ctxFor,
    path,
    // The harness clock, so a test can compare a task's schedule against "now".
    nowValue: () => now,
    tasksNow: () => now,
    timers,
    persistUserMessage,
    sessionFileFor,
    isCompactingNow: () => compactingNow,
    emitCompactionStart,
    emitCompactionEnd,
    emitSettleAfterCompaction,
  };
}

/** The parsed task array currently persisted. */
const persistedTasks = (h) => h.store().tasks ?? [];

/**
 * The exact injected text for a task, with its OPAQUE occurrence id matched.
 *
 * Oracle OPTION D folds the correlation envelope into the first line, so the
 * occurrence id is not knowable to the test in advance; this asserts the fixed
 * shape while still requiring the exact prompt body.
 */
const envelopePrompt = (taskId, prompt) =>
  new RegExp(`^\\[task ${taskId} occurrence oc-[0-9a-z-]+\\]\\n${prompt.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);

test("FEATURE3: a one-shot task fires sendUserMessage once with the task id, then is removed from the store", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"t1","prompt":"check the build","delayMs":1000}`);
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["t1"], "the task is persisted on declaration");

  h.advance(999);
  assert.equal(h.injected.length, 0, "not due yet");
  h.advance(1);
  assert.equal(h.injected.length, 1, "fires exactly once when due");
  assert.match(h.injected[0], envelopePrompt("t1", "check the build"), "the firing prompt names the task id, carries the occurrence envelope, and carries the prompt");
  assert.deepEqual(persistedTasks(h), [], "a one-shot is REMOVED from the store before/at dispatch");
});

test("FEATURE3: an interval task fires, then advances its due time rather than re-firing immediately", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"r1","prompt":"poll","delayMs":0,"intervalMs":1000}`);
  h.advance(0);
  assert.equal(h.injected.length, 1, "fires once when due");
  h.settle(PARENT_UUID); // release the handoff guard for the next occurrence
  const afterFirst = persistedTasks(h).find((t) => t.id === "r1");
  assert.ok(afterFirst, "the interval task is retained");
  assert.ok(afterFirst.nextRunAtMs > h.tasksNow(), "its due time is advanced into the future, not left in the past");

  h.advance(500);
  assert.equal(h.injected.length, 1, "no tight loop: no second firing within the interval");
  h.advance(600);
  assert.equal(h.injected.length, 2, "it fires again after the interval elapses");
});

test("FEATURE3: an overdue interval (144 missed intervals) fires EXACTLY ONCE", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"od","prompt":"reconcile","delayMs":1000,"intervalMs":1000}`);
  // Rewrite the persisted due time to 144 intervals in the past, then reload.
  const overdue = h.tasksNow() - 144 * 1000;
  const raw = h.store();
  raw.tasks = raw.tasks.map((t) => (t.id === "od" ? { ...t, nextRunAtMs: overdue } : t));
  writeFileSync(h.path, JSON.stringify(raw));
  h.sessionStart(PARENT_UUID, "resume");

  h.advance(0);
  assert.equal(h.injected.length, 1, "all missed occurrences coalesce into ONE immediate check (not 144, not 0)");
  assert.match(h.injected[0], envelopePrompt("od", "reconcile"), "the single firing carries the task id and occurrence envelope");
  // COALESCING: the due cursor is advanced to the FIRST FUTURE slot, not left in
  // the past - that is what prevents a backlog.
  const advanced = persistedTasks(h).find((t) => t.id === "od");
  assert.ok(advanced, "the interval task is retained");
  assert.ok(advanced.nextRunAtMs > h.tasksNow(), "the missed occurrences are coalesced into one future slot");
  h.settle(PARENT_UUID);
  h.advance(0);
  assert.equal(h.injected.length, 1, "no backlog: nothing further fires immediately");
});

test("FEATURE3: a task whose session is NOT active does not fire, and fires once when that session resumes", () => {
  const h = feature3Harness({ sessionId: PARENT_SESSION });
  h.sessionStart(PARENT_SESSION);
  h.declare(PARENT_SESSION, `TASK:ADD {"id":"own","prompt":"owned","delayMs":1000}`);
  // The owning session is no longer active; another session takes over.
  h.sessionStart(OTHER_SESSION, "startup");
  h.advance(10_000);
  assert.equal(h.injected.length, 0, "a task owned by an inactive session does NOT fire");
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["own"], "the due task is RETAINED, not dropped");

  // The owning session resumes: the retained task fires ONCE.
  h.sessionStart(PARENT_SESSION, "resume");
  h.advance(10_000);
  assert.equal(h.injected.length, 1, "it fires once when its exact session becomes active again");
  assert.match(h.injected[0], envelopePrompt("own", "owned"), "delivered into the owning session with the task id");
});

test("FEATURE3: a task armed under a superseded registration token does NOT inject", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"fence","prompt":"stale","delayMs":1000}`);
  // Capture the callback armed under the CURRENT registration.
  const stale = h.timers.find((handle) => handle.due === h.tasksNow() + 1000);
  assert.ok(stale, "a callback was armed for the task");
  // A re-registration re-mints the transient fence.
  h.sessionStart(PARENT_UUID, "reload");
  // Invoke the superseded callback directly: the fence must reject it.
  stale.run();
  assert.equal(h.injected.length, 0, "a callback armed under a superseded registration does not inject");
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["fence"], "the task is retained, not consumed by the stale callback");
});

test("FEATURE3: TASK:CANCEL removes the task and stops future firing; an unknown id is a harmless no-op", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"c1","prompt":"later","delayMs":5000}`);
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["c1"]);

  // Cancelling an unknown id is a no-op, not an error.
  assert.doesNotThrow(() => h.declare(PARENT_UUID, "TASK:CANCEL nope\nSTATUS:DONE"));
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["c1"], "an unknown id leaves the store unchanged");

  // Cancelling the real id removes the task and stops the future firing.
  h.declare(PARENT_UUID, "TASK:CANCEL c1\nSTATUS:DONE");
  assert.deepEqual(persistedTasks(h), [], "the cancelled task is removed from the store");
  h.advance(20_000);
  assert.equal(h.injected.length, 0, "a cancelled task never fires");
});

test("FEATURE3: TASK:CANCEL does not cancel when the id does not match the task's own id", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"real","prompt":"keep me","delayMs":5000}`);
  h.declare(PARENT_UUID, "TASK:CANCEL other\nSTATUS:DONE");
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["real"], "a mismatched id cancels nothing");
  h.advance(10_000);
  assert.equal(h.injected.length, 1, "the retained task still fires on its own schedule");
});

// COVERAGE GAP CLOSED (parent, rev 110): `cancelTask` guards
// `task.sessionId !== currentSessionId` at `session-supervisor.ts:4351`, so only the
// session that OWNS a task may cancel it. Its disable-and-rerun mutation (M6b) removed
// that guard and NO test failed - this test supplies the missing discriminator.
test("FEATURE3: TASK:CANCEL from a session that does NOT own the task is a no-op", () => {
  const h = feature3Harness({ sessionId: PARENT_SESSION });
  h.sessionStart(PARENT_SESSION);
  h.declare(PARENT_SESSION, `TASK:ADD {"id":"mine","prompt":"owned by parent","delayMs":5000}`);
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["mine"], "the owning session created the task");

  // A DIFFERENT session tries to cancel a task it does not own.
  h.sessionStart(OTHER_SESSION, "startup");
  h.declare(OTHER_SESSION, "TASK:CANCEL mine\nSTATUS:DONE");
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["mine"],
    "a FOREIGN session may not cancel another session's task",
  );

  // The owning session resumes and the retained task still fires exactly once.
  h.sessionStart(PARENT_SESSION, "resume");
  h.advance(10_000);
  assert.equal(h.injected.length, 1, "the foreign cancel did not suppress the owner's task");
  assert.match(h.injected[0], envelopePrompt("mine", "owned by parent"), "it fires into its owning session");
});

// COVERAGE NOTE (parent, rev 110) - THIS TEST IS NOT LOAD-BEARING. It is retained as a
// behavioural regression only, and its limitation is recorded rather than hidden.
// The session-ownership rule is enforced at TWO layers: an arm-time filter
// (`session-supervisor.ts:4269`, `armCurrentSessionTasks` clears the timer of any task not
// owned by the current session) and a pump-time re-check (`:4287`). Disable-and-rerun
// MEASURED: removing the pump-time guard ALONE leaves this suite GREEN 320/320 - because
// `sessionStart` re-arms through `armCurrentSessionTasks`, which CLEARS the old timer, so
// invoking the captured `armed` handle in this scenario either hits an already-disarmed
// timer or is covered by the arm-time filter. The pump-time guard is therefore reachable
// defensively only; a test that genuinely isolates it would have to deliver a pump call
// through a path that bypasses `armCurrentSessionTasks` entirely.
test("FEATURE3: a task's timer is disarmed when another session takes over ownership", () => {
  const h = feature3Harness({ sessionId: PARENT_SESSION });
  h.sessionStart(PARENT_SESSION);
  h.declare(PARENT_SESSION, `TASK:ADD {"id":"pump","prompt":"pump guard","delayMs":1000}`);
  const armed = h.timers.find((handle) => handle.due === h.tasksNow() + 1000);
  assert.ok(armed, "a callback was armed while the owning session was active");

  // Ownership moves to another session: the owner's timer must be cleared, so a stale
  // occurrence cannot be delivered even if its callback were invoked.
  h.sessionStart(OTHER_SESSION, "startup");
  assert.ok(
    !h.timers.includes(armed),
    "armCurrentSessionTasks DISARMS the non-owner's timer on ownership change",
  );
  armed.run();
  assert.equal(h.injected.length, 0, "a disarmed owner timer injects nothing");
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["pump"],
    "the task is RETAINED for its owning session, not consumed",
  );
});


// REVIEW 78 / FEATURE3 R1 (parent, rev 111): `injectTask` must pass a delivery
// mode. `api.sendUserMessage` delegates to the host's `sendCustomMessage`, which
// REJECTS a send while the session is streaming unless `streamingBehavior` is
// supplied (Pi 1.1.0 `dist/core/agent-session.js:1552-1555`), and rejects during
// compaction (`:1534-1535`). Without it a due firing throws AFTER the duplicate
// guard has consumed the occurrence, so the run is silently LOST.
test("FEATURE3: an injected prompt carries a delivery mode so a streaming session does not reject it", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"dm","prompt":"needs a mode","delayMs":1000}`);
  h.advance(2000);
  assert.equal(h.injected.length, 1, "the task fired once");
  assert.equal(h.sentOptions.length, 1, "the send carried an options argument");
  // Assert the EXACT mode, not merely that some string was supplied: any other
  // value (or a missing one) is the rejection path the host enforces.
  assert.deepEqual(
    h.sentOptions[0],
    { deliverAs: "followUp" },
    "the send must carry deliverAs: followUp so a streaming session queues it",
  );
});

// REVIEW 78-R3 (parent, rev 114): the delivery mode must survive a session that is
// ACTUALLY streaming - the host rejects a send while streaming UNLESS it carries a
// `streamingBehavior` (`agent-session.js:1552-1559`). NOTE the guard retains an
// occurrence whenever the host is not idle, and `isIdle` is false while streaming
// too (`:1053-1054`), so a due task is delivered on a later retry tick rather than
// instantly. The HOST rejection path is what this test pins: with the mode present
// the send is never refused.
test("FEATURE3: a due firing during an in-flight turn is queued as a follow-up, not rejected", () => {
  const h = feature3Harness({ streaming: true });
  const rejects = [];
  // Model the host exactly: while streaming, a send WITHOUT a delivery mode is
  // REJECTED; with one it is queued (a resolved promise).
  h.pi.sendUserMessage = (text, options) => {
    if (options?.deliverAs === undefined) {
      rejects.push(text);
      return Promise.reject(
        new Error(
          "Agent is already processing. Specify streamingBehavior ('steer' or 'followUp') to queue the message.",
        ),
      );
    }
    h.injected.push(text);
    h.sentOptions.push(options);
    // Oracle OPTION D: an accepting host PERSISTS the queued message, so the
    // confirmation read can positively correlate it. Without this the harness
    // would model a host that accepts but never records, which no real host does.
    h.persistUserMessage(PARENT_UUID, text);
    return Promise.resolve();
  };
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"busy","prompt":"queue me","delayMs":1000}`);
  h.advance(600_000);
  assert.deepEqual(rejects, [], "the send must not hit the host's streaming rejection");
  assert.equal(h.injected.length, 1, "the occurrence is QUEUED, not lost");
  assert.equal(h.sentOptions[0]?.deliverAs, "followUp", "carrying the delivery mode");
});

// REVIEW 78 / FEATURE3 R2 (parent, rev 111): when the store cannot be written the
// occurrence must NOT be delivered. The duplicate guard only prevents replay if
// the write LANDED; delivering on an unpersisted advance would let a restart
// re-fire the same occurrence. The task must be RETAINED instead.
// The write is forced to fail by making the store's PARENT path an existing file,
// so `mkdirSync(dirname(tasksPath), {recursive:true})` cannot succeed.
test("FEATURE3: a task is NOT consumed when the store write fails (interval)", () => {
  const parentBlocker = join(mkdtempSync(join(tmpdir(), "supervisor-f3-ro-")), "blocker");
  writeFileSync(parentBlocker, "not a directory");
  const tasksPath = join(parentBlocker, "tasks.json");
  const h = feature3Harness({ tasksPath });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"ro","prompt":"must not fire","delayMs":1000,"intervalMs":1000}`);
  const dueBefore = persistedTasks(h).find((t) => t.id === "ro")?.nextRunAtMs;
  const dueArmed = h.timers[0]?.due;
  h.advance(3000);
  assert.equal(h.injected.length, 0, "an unpersisted occurrence must not be delivered");
  // ROLLBACK: the store is still UNWRITABLE, so the retained record is observed
  // through the harness timer + the pre-failure due time, and the retry must be
  // re-armed rather than the occurrence silently dropped.
  assert.ok(
    h.timers.some((handle) => handle.due > h.tasksNow()),
    "ROLLBACK: the occurrence is RETAINED and re-armed for retry",
  );
  assert.equal(dueBefore, undefined, "nothing was ever persisted while the path was blocked");

  // RESTORE WRITABILITY and prove the retained occurrence is eventually delivered
  // - the retry path must complete, not spin forever or drop the occurrence.
  //
  // Oracle OPTION D: the commit point is now the confirmed persisted transcript,
  // and confirmation RELEASES the handoff (STEP 7), so an interval task resumes
  // its own cadence instead of being pinned until a settle. This window therefore
  // legitimately contains several interval firings; what must hold is that the
  // RETAINED occurrence is delivered and the task keeps its schedule.
  rmSync(parentBlocker, { force: true });
  h.advance(120_000);
  assert.ok(h.injected.length >= 1, "the retained occurrence is delivered once the store is writable");
  assert.match(h.injected[0], envelopePrompt("ro", "must not fire"), "the FIRST delivery is the retained occurrence");
  assert.equal(persistedTasks(h).find((t) => t.id === "ro")?.intervalMs, 1000, "the interval task survives with its schedule");
  assert.ok(dueArmed !== undefined, "a timer had been armed for the task");
});

test("FEATURE3: a one-shot task is NOT consumed when the store write fails", () => {
  const parentBlocker = join(mkdtempSync(join(tmpdir(), "supervisor-f3-ro2-")), "blocker");
  writeFileSync(parentBlocker, "not a directory");
  const tasksPath = join(parentBlocker, "tasks.json");
  const h = feature3Harness({ tasksPath });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"ro2","prompt":"one shot","delayMs":1000}`);
  h.advance(3000);
  assert.equal(h.injected.length, 0, "the one-shot is not delivered on an unpersisted removal");
  assert.ok(
    h.timers.some((handle) => handle.due > h.tasksNow()),
    "ROLLBACK: the one-shot is restored and re-armed, not dropped",
  );

  rmSync(parentBlocker, { force: true });
  h.advance(120_000);
  assert.equal(h.injected.length, 1, "the one-shot is delivered once the store is writable");
  assert.ok(
    !persistedTasks(h).some((t) => t.id === "ro2"),
    "and it is consumed exactly once",
  );
});

// REVIEW 78-R2 (parent, rev 111): durable CANCELLATION. `cancelTask` dropped the
// persist result, so a failed write could let a restart revive a cancellation the
// user already made. Asserts the rollback AND that the task keeps firing.
test("FEATURE3: TASK:CANCEL is retried until it lands, and the task never fires", () => {
  const parentBlocker = join(mkdtempSync(join(tmpdir(), "supervisor-f3-ro3-")), "blocker");
  writeFileSync(parentBlocker, "not a directory");
  const tasksPath = join(parentBlocker, "tasks.json");
  const h = feature3Harness({ tasksPath });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"keep","prompt":"keep me","delayMs":5000}`);
  h.declare(PARENT_UUID, "TASK:CANCEL keep\nSTATUS:DONE");
  assert.ok(
    h.timers.some((handle) => handle.due > h.tasksNow()),
    "ROLLBACK: a cancellation that did not reach disk is undone in memory",
  );

  // A failed cancellation must be RETRIED, so the task must NOT fire while the
  // cancellation is outstanding - even though its due time passes.
  rmSync(parentBlocker, { force: true });
  h.advance(120_000);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    [],
    "the retried cancellation lands on disk once the store is writable",
  );
  assert.equal(h.injected.length, 0, "a cancelled task NEVER fires");
});

// BOUNDED RE-REVIEW F2 (the NEW defect this round was about): a stale cancellation
// retry must never delete a REPLACEMENT task that reuses the same id.
//
// Sequence: (1) a task exists and its cancellation fails to persist, so retry R is
// armed; (2) the store becomes writable and the task is cancelled SUCCESSFULLY - R
// is dropped from `cancelRetries`; (3) a NEW task is added under the SAME id;
// (4) R fires. If R's handle was merely forgotten rather than CANCELLED, R still
// runs, finds a task with that id and deletes the NEW task the user just created.
// The registration token does not help: it is still current. This is why every
// removal from `cancelRetries` goes through `dropCancelRetry`.
test("FEATURE3 F2: a superseded cancellation retry never deletes a task that reuses its id", () => {
  const parentBlocker = join(mkdtempSync(join(tmpdir(), "supervisor-f2-stale-")), "blocker");
  writeFileSync(parentBlocker, "not a directory");
  const tasksPath = join(parentBlocker, "tasks.json");
  const h = feature3Harness({ tasksPath });
  h.sessionStart(PARENT_UUID);

  // (1) Create `reuse`, then fail its cancellation so retry R is armed.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"reuse","prompt":"first","delayMs":600000}`);
  h.declare(PARENT_UUID, "TASK:CANCEL reuse\nSTATUS:DONE");
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    [],
    "precondition: the failed cancellation is rolled back out of the store",
  );

  // (2) The store becomes writable; cancel again so the retry R is dropped.
  rmSync(parentBlocker, { force: true });
  h.declare(PARENT_UUID, "TASK:CANCEL reuse\nSTATUS:DONE");

  // (3) A NEW task reuses the id, with its own far-future due time.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"reuse","prompt":"SECOND","delayMs":600000}`);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["reuse"],
    "precondition: the replacement task is durably stored",
  );

  // (4) Fire any stale retry, then confirm the replacement survived.
  h.advance(120_000);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["reuse"],
    "a stale cancellation retry must NOT delete the replacement task",
  );
  assert.deepEqual(
    persistedTasks(h).map((t) => t.prompt),
    ["SECOND"],
    "and the surviving task is the REPLACEMENT definition, not the cancelled one",
  );
});

// REVIEW 78-R3 (parent, rev 113): CANCELLATION must SURVIVE a store reload. A
// cancellation that cannot reach disk is rolled back in memory and retried, and
// `restoreTasks()` re-reads the store and RE-ARMS every task it finds. Without
// reading `pendingCancels` there, a reload resurrects a task the user already
// cancelled - the cancellation is lost precisely in the failure case it exists
// for. `armTask`, `armCurrentSessionTasks` and `pumpTask` therefore all consult
// `pendingCancels` before arming or delivering.
test("FEATURE3: a cancellation that has not reached disk survives a store reload and never fires", () => {
  const dir = mkdtempSync(join(tmpdir(), "supervisor-f3-rl-"));
  const tasksPath = join(dir, "tasks.json");
  // FINAL REVIEW F2: the task MUST be durably persisted BEFORE the store is made
  // unwritable, so the reload has something real to restore. The earlier revision
  // broke the store FIRST, declared the task anyway, and so never wrote it: reload
  // read nothing, and `timers.every(...)` below passed vacuously on an EMPTY
  // array. That test could not fail, and the reviewer proved it.
  const h = feature3Harness({ tasksPath });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"ghost","prompt":"must not run","delayMs":3000}`);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["ghost"],
    "precondition: the task is durably persisted BEFORE the store breaks",
  );

  // Now model a store that is READABLE BUT STALE - the realistic failure. The
  // task is already on disk (asserted above), the store stays READABLE so a
  // reload WILL restore `ghost` into `tasks`, and the directory is made
  // read-only so the cancellation cannot land (`persistTasks` writes a sibling
  // `.tmp` then renames, so a read-only DIRECTORY blocks it with EACCES - a
  // read-only file would not, because the write goes to the sibling first).
  // Reload restoring `ghost` is exactly the state in which the
  // cancellation-intent guards are load-bearing: without them the restored task
  // is re-armed and fires.
  chmodSync(dirname(tasksPath), 0o555);
  h.declare(PARENT_UUID, "TASK:CANCEL ghost\nSTATUS:DONE");

  // The cancellation could not reach disk, so it is rolled back in memory and a
  // retry is armed. A session reload MINTS A NEW REGISTRATION TOKEN, which
  // invalidates that retry callback - so the reload path is what actually has to
  // honour the outstanding cancellation. The store stays UNWRITABLE across the
  // reload (the blocker is still in place), which is the case that matters: the
  // cancellation is still outstanding, and the task must not be re-armed from
  // the in-memory copy during the reload.
  h.sessionStart(PARENT_UUID);
  // The discriminator is FIRING, not the mere existence of a timer: a pending
  // cancellation legitimately keeps a 1s RETRY timer armed (TASK_BUSY_RETRY_MS),
  // so asserting "no timer is due soon" would reject the correct behaviour. What
  // must NOT happen is delivery. Advance well past the task's original due time
  // (3000ms) and past several retry intervals and assert nothing was injected.
  assert.deepEqual(h.injected, [], "no delivery while the cancellation is outstanding");
  h.advance(600_000);
  assert.deepEqual(h.injected, [], "a task with an outstanding cancellation must NEVER fire");

  // Once the store becomes writable the retried cancellation lands for good.
  chmodSync(dirname(tasksPath), 0o755);
  h.sessionStart(PARENT_UUID);
  h.advance(600_000);
  assert.deepEqual(h.injected, [], "still never fires after the store recovers");
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    [],
    "the cancellation lands on disk and the task is gone for good",
  );
});

  // REVIEW 78-R2 (parent, rev 112) + REVIEW 79 R79-P1 (rev 115): COMPACTION loss.
  // Pi rejects a send while COMPACTING before it inspects the delivery mode
  // (`agent-session.js:1534-1535`), and that rejection is asynchronous - the
  // runtime only reports it (`:2712-2718`) so the scheduler gets no failure
  // acknowledgement. A fire-and-forget send would therefore LOSE the occurrence,
  // which the duplicate guard had already committed as consumed.
  //
  // R79-P1: `session_compact` is NOT a send-ready boundary. The host awaits it at
  // `agent-session.js:2239` and clears its abort controller only at `:2253`, so a
  // send is still refused when that event fires. The re-pump therefore happens at
  // the settle boundary, and this test emits BOTH so the premature-pump regression
  // cannot come back.
  test("FEATURE3: a task due during compaction is RETAINED and fires once compaction truly ends", async () => {
  const h = feature3Harness();
  // Compaction must be opened through the REAL event pair, not a harness flag:
  // the product learns about compaction only from these events.
  h.emitCompactionStart();
  const refused = [];
  h.pi.sendUserMessage = (text, options) => {
    // Model the host: a send while compacting is REJECTED regardless of mode
    // (`agent-session.js:1534-1535`, thrown before the delivery mode is read).
    if (h.isCompactingNow()) {
      refused.push(text);
      return Promise.reject(new Error("Cannot submit a prompt while compaction is in progress."));
    }
    h.injected.push(text);
    return undefined;
  };
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"compact","prompt":"survive compaction","delayMs":1000}`);
  h.advance(3000);
  assert.deepEqual(refused, [], "the guard must not attempt a send the host will refuse");
  assert.equal(h.injected.length, 0, "nothing is delivered while compacting");  assert.equal(
    persistedTasks(h).map((t) => t.id).join(","),
    "compact",
    "the occurrence is RETAINED, not consumed, during compaction",
  );

  // Compaction ends. A send is STILL refused DURING the `session_compact` emit
  // (R79-P1), because the host clears its abort controller only after that
  // awaited emit returns. Assert the state change WITHOUT advancing the clock, so
  // the task's OWN timer cannot be what delivers it.
  h.emitCompactionEnd(true);
  assert.deepEqual(
    refused,
    [],
    "R79-P1: `session_compact` is not send-ready - the host clears its abort controller afterwards",
  );
  assert.equal(h.injected.length, 0, "nothing is delivered at the terminal-event instant");

  // FINAL REVIEW F1 (corrected by the bounded re-review): the release is DEFERRED
  // past the handler return, which is where `_clearManualCompactionState()` runs -
  // and the manual `/compact` path emits NO settle afterwards. So the retained
  // occurrence must land WITHOUT any manufactured settlement.
  //
  // The deferral is a RETRY TIMER on the macrotask queue, not a microtask: a
  // microtask queued inside this handler drains before the runner's
  // `await handler(...)` continuation (`dist/extensions/runner.js:819`), i.e.
  // while the host's abort controller is STILL present, and the send would be
  // refused. A timer cannot run until the emit and the host's cleanup have both
  // completed.
  await h.flushMicrotasks();
  assert.equal(
    h.injected.length,
    0,
    "no microtask-only release: the occurrence is not send-ready while the emit is in flight",
  );
  h.advance(1000);
  assert.equal(
    h.injected.length,
    1,
    "the retained occurrence is delivered once the host can accept, with no settlement",
  );
});

// REVIEW 79 R79-P2 (rev 115): EARLY FIRING. The compaction-window re-pump must
// only pump tasks that are actually DUE. Pumping every timer id fired a task
// scheduled well into the future the instant compaction ended - a silent
// schedule violation. This is the DISCRIMINATOR: re-introducing the
// pump-everything loop makes it fail.
test("FEATURE3: compaction end does NOT fire a task whose due time has not arrived", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  // Due in one hour - far beyond anything this test advances.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"later","prompt":"much later","delayMs":3600000}`);
  h.emitCompactionStart();
  h.emitCompactionEnd(true);
  h.emitSettleAfterCompaction();
  h.advance(600_000); // only ten minutes
  assert.deepEqual(h.injected, [], "a task due in an hour must not fire when compaction ends");
  assert.equal(
    persistedTasks(h).map((t) => t.id).join(","),
    "later",
    "the not-yet-due task stays pending",
  );
});

// REVIEW 81 R81-P1 (rev 116): the SEND-READY BOUNDARY. `compacting` must NOT be
// cleared inside the `session_compact` / `session_compact_failed` handlers.
// The host AWAITS the `session_compact` emit at `agent-session.js:2246-2253` and
// calls `_clearManualCompactionState()` only at `:2258`, so a send attempted
// from within or immediately after that handler is still refused
// (`:1534-1535`) and the refusal is swallowed (`:2711-2718`): the occurrence is
// lost with no failure acknowledgement.
//
// This test models that ordering EXACTLY. `session_compact` is emitted and,
// INSIDE the emit (as the host's queued-prompt logic would), the task's own
// timer is fired. The host refusal predicate is driven ONLY by the host's own
// abort-controller lifetime - never by a harness flag the product cannot read -
// so the test genuinely fails if the product clears `compacting` at the wrong
// boundary: the probe send would be attempted and the host would refuse it.
test("FEATURE3 R82-P1: a task booked past the 2^31-1 ms timer cap does NOT fire early and still fires when due", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  const THIRTY_DAYS = 2592000000;
  const CAP = 2147483647;
  h.declare(PARENT_UUID, `TASK:ADD {"id":"far","prompt":"monthly check","delayMs":${THIRTY_DAYS}}`);

  // The very first arm must not request an unrepresentable delay. Before the
  // clamp, `schedule` received 2592000000 and Node clamped it to 1 ms, so the
  // task fired ~immediately AND the one-shot removed itself from the store.
  assert.equal(h.timers.length, 1, "one timer armed");
  assert.ok(
    h.timers[0].requested <= CAP,
    `armed delay must be clamped to the 2^31-1 cap, got ${h.timers[0].requested}`,
  );

  // Just past the cap the timer wakes, but the task is NOT yet due, so the
  // due-time re-check must re-arm instead of delivering early.
  h.advance(CAP + 1);
  assert.equal(h.injected.length, 0, "must NOT fire early after the capped wake");
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["far"],
    "the task must survive the intermediate hop (an early one-shot would have removed itself)",
  );

  // Advance the remainder of the horizon: the task fires once, exactly at due time.
  h.advance(THIRTY_DAYS - CAP + 1000);
  assert.equal(h.injected.length, 1, "fires exactly once when actually due");
  assert.match(h.injected[0], /^\[task far occurrence oc-[0-9a-z-]+\]/, "the firing names the task id and occurrence envelope");
  assert.deepEqual(persistedTasks(h).map((t) => t.id), [], "the one-shot is removed after firing");
});

test("FEATURE3 R81-P1: a task due DURING the `session_compact` emit is retained, then delivered once the handler returns", async () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"probe","prompt":"due mid-emit","delayMs":1000}`);

  // Model the host: a send is refused while the host's compaction abort
  // controller is alive. It is cleared ONLY after the `session_compact` emit
  // returns (`agent-session.js:2246-2253` vs `:2258`).
  let hostRefusesSend = true;
  const refused = [];
  h.pi.sendUserMessage = (text, options) => {
    if (hostRefusesSend) {
      refused.push(text);
      throw new Error("Cannot submit a prompt while compaction is in progress.");
    }
    h.injected.push(text);
    h.persistUserMessage(PARENT_UUID, text);
    return undefined;
  };

  // A listener registered AFTER the product's: on the terminal compaction event
  // it fires the probe's timer AT THAT INSTANT. This is the exact defect window -
  // the timer callback runs while the awaited `session_compact` emit is still in
  // flight, i.e. while the host still refuses the send.
  h.pi.on("session_compact", () => {
    h.advance(1000);
  });

  h.emitCompactionStart();
  h.advance(1000); // the probe becomes due, but the window is open: it is retained
  assert.deepEqual(refused, [], "no send is attempted while the window is open");

  h.emitCompactionEnd(true); // the probe's timer fires DURING this emit
  hostRefusesSend = false; // the host clears its abort controller only now
  // R81-P1: the occurrence must NOT be DELIVERED at the terminal-event boundary.
  // The host still refuses the send here, so an attempted send is rejected (the
  // occurrence is retained and retried, not consumed) - what would be fatal is a
  // COMMITTED delivery or a DESTROYED occurrence. Both are asserted below.
  assert.equal(
    h.injected.length,
    0,
    "R81-P1: nothing may be DELIVERED while the host still refuses the send",
  );
  assert.equal(
    persistedTasks(h).map((t) => t.id).includes("probe"),
    true,
    "and the occurrence is retained (not consumed) by the refused attempt",
  );

  // FINAL REVIEW F1: the manual `/compact` path emits NO `agent_settled`
  // (`agent-session.js:2242-2261` returns after `_clearManualCompactionState()`),
  // so the release must NOT wait for a settlement - it is deferred to just after
  // the handler returns, which is exactly where the controller is cleared. The
  // old expectation (`emitSettleAfterCompaction()` required) is what let manual
  // compaction suppress scheduled work indefinitely.
  //
  // BOUNDED RE-REVIEW F1: the release is a RETRY TIMER on the macrotask queue,
  // NOT a microtask. A microtask queued inside this handler drains BEFORE the
  // runner's `await handler(...)` continuation (`dist/extensions/runner.js:819`),
  // i.e. while the host's abort controller is STILL present - the exact unsafe
  // boundary this test is about. A timer cannot run until both the emit and the
  // host's cleanup have completed, which is the real send-ready point.
  await h.flushMicrotasks();
  assert.equal(
    h.injected.length,
    0,
    "no microtask-only release: the occurrence is not send-ready while the emit is in flight",
  );
  h.advance(1000); // the retry lands, now that the host accepts
  assert.equal(h.injected.length, 1, "the retained occurrence lands without any settlement");
  assert.match(h.injected[0], envelopePrompt("probe", "due mid-emit"), "the firing carries the task id and prompt");
});

test("FEATURE3 F1: a refusal the host SWALLOWS (void return, no throw) never consumes the occurrence", () => {
  // This is the REAL host behaviour and the reason the synchronous try/catch in
  // `injectTask` is not sufficient on its own. `api.sendUserMessage` is an async
  // wrapper returning `void` (`extensions/types.d.ts:1243-1246`) and the host
  // CATCHES its own rejection internally (`agent-session.js:2711-2718`), so a
  // compaction refusal produces NO throw and NO return value. Any design that
  // treats "the call returned" as "the host accepted" loses the occurrence.
  //
  // The harness models that faithfully: the stub returns `undefined` WITHOUT
  // throwing while the host is refusing, exactly as the real wrapper does. The
  // only signals available to the product are its own compaction tracking and
  // the fact that no turn subsequently settles.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"swallowed","prompt":"must survive","delayMs":1000}`);

  // Swallowed refusal: no throw, no delivery, no return value.
  h.pi.sendUserMessage = () => undefined;

  h.emitCompactionStart();
  h.advance(1000);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["swallowed"],
    "a one-shot must still exist while the window is open (nothing consumed)",
  );
  h.emitCompactionEnd(true);
  h.advance(1000);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["swallowed"],
    "a SWALLOWED refusal must not consume the one-shot: the task is still deliverable",
  );
});

test("FEATURE3 F6: a `TASK:ADD` inside a fenced code block does NOT create a task; the same line at top level does", () => {
  // Final-review F6: task parsing scanned every column-zero `TASK:` line with no
  // Markdown ownership check, so an assistant DOCUMENTING the syntax inside a
  // fenced example silently mutated the scheduler. `structure.inside` is the same
  // container test that guards `STATUS:`, and this row pins BOTH directions so
  // the guard cannot be satisfied by rejecting everything.
  const fenced = feature3Harness();
  fenced.sessionStart(PARENT_UUID);
  fenced.declare(
    PARENT_UUID,
    ["Here is how to schedule a task:", "```text", 'TASK:ADD {"id":"doc","prompt":"p","delayMs":1000}', "```"].join("\n"),
  );
  assert.deepEqual(
    persistedTasks(fenced).map((t) => t.id),
    [],
    "a documented TASK: line inside a fence must NOT create a task",
  );

  const topLevel = feature3Harness();
  topLevel.sessionStart(PARENT_UUID);
  topLevel.declare(PARENT_UUID, 'TASK:ADD {"id":"real","prompt":"p","delayMs":1000}');
  assert.deepEqual(
    persistedTasks(topLevel).map((t) => t.id),
    ["real"],
    "the identical line at top level MUST still create a task (the guard must not over-reject)",
  );
});

test("FEATURE3 F6: a `TASK:CANCEL` inside a fence does NOT cancel a real task", () => {
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, 'TASK:ADD {"id":"keep","prompt":"p","delayMs":1000}');
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["keep"], "precondition: task exists");

  h.declare(PARENT_UUID, ["Documenting cancellation:", "```text", "TASK:CANCEL keep", "```"].join("\n"));
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["keep"],
    "a fenced TASK:CANCEL must not cancel a real task",
  );

  h.declare(PARENT_UUID, "TASK:CANCEL keep");
  assert.deepEqual(persistedTasks(h), [], "a top-level TASK:CANCEL still cancels");
});

test("FEATURE3 F3: persisting merges a FOREIGN session's records instead of deleting them", () => {
  // Final-review F3: persistTasks serialized this process's whole map over the
  // file, so a second Pi process's task was silently deleted by any later write.
  // The merge keeps records this registration does not own.
  const shared = join(mkdtempSync(join(tmpdir(), "supervisor-f3-shared-")), "session-supervisor", "tasks.json");
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, 'TASK:ADD {"id":"mine","prompt":"p","delayMs":1000}');

  // A DIFFERENT owner writes a task into the same store behind this process.
  const foreign = {
    id: "theirs",
    sessionId: "some-other-session-uuid",
    prompt: "other",
    nextRunAtMs: 9_999_999_999,
  };
  writeFileSync(shared, JSON.stringify({ version: 1, tasks: [foreign] }));

  // Now this process writes again (adding a second owned task).
  h.declare(PARENT_UUID, 'TASK:ADD {"id":"mine2","prompt":"p","delayMs":1000}');

  const onDisk = JSON.parse(readFileSync(shared, "utf8"));
  const ids = onDisk.tasks.map((t) => t.id).sort();
  assert.ok(ids.includes("theirs"), `a foreign session's record must survive this process's write, got ${ids}`);
  assert.ok(ids.includes("mine") && ids.includes("mine2"), `this session's records are present, got ${ids}`);
});

test("F5: every notify() event symbol in the product is declared (no undefinable OSC constant)", () => {
  // Final-review F5: the scheduled-task delivery-failure branches called
  // `notify(UNVERIFIED_ESCALATION, ...)` while the export is
  // `OSC_NOTIFY_UNVERIFIED_ESCALATION`. The module still LOADS, because a
  // ReferenceError is deferred to branch execution - so the failure notice threw
  // exactly when it was needed, and a green suite could not see it. This is a
  // whole-class static check rather than a row per site.
  const src = readFileSync(
    new URL("../shell/config/pi/extensions/session-supervisor.ts", import.meta.url),
    "utf8",
  );
  const declared = new Set(
    [...src.matchAll(/^(?:export )?const ([A-Z][A-Z0-9_]+)/gm)].map((m) => m[1]),
  );
  const used = [...new Set([...src.matchAll(/notify\(\s*([A-Z][A-Z0-9_]+)\s*,/g)].map((m) => m[1]))];
  assert.ok(used.length > 0, "the scan must find notify() call sites (guard against a vacuous pass)");
  const undeclared = used.filter((symbol) => !declared.has(symbol));
  assert.deepEqual(undeclared, [], `notify() event symbols must be declared constants, undeclared: ${undeclared}`);
});

// ---------------------------------------------------------------------------
// FEATURE 3 / Oracle OPTION D (tagged durable outbox): positive-correlation
// commit. The pre-OPTION-D design advanced/removed the due cursor BEFORE the
// send and relied on `canAcceptNow()` to PREDICT acceptance. Because
// `sendUserMessage` returns `void` and the host swallows its own rejection
// (`agent-session.js:2711-2718`), a refused-but-predicted-ready send destroyed
// the occurrence. The outbox design commits ONLY on a positively correlated,
// PERSISTED transcript row, with at-least-once semantics and a documented
// duplicate window.
// ---------------------------------------------------------------------------

/** The occurrence id carried by an injected prompt's envelope line. */
const occurrenceIdOf = (text) => {
  const match = /^\[task [^\]]*? occurrence (oc-[0-9a-z-]+)\]/.exec(text);
  return match === null ? null : match[1];
};

/** A PERSISTED transcript row for a role, with one text part. */
const transcriptRow = (role, text) => ({
  type: "message",
  id: `row-${role}`,
  message: { role, content: [{ type: "text", text }] },
});

test("FEATURE3 OPTION-D: a CONFIRMED send (persisted transcript row) COMMITS the one-shot", () => {
  // The positive control for the commit: the host persists the delivered row, so
  // the scheduler must observe it and REMOVE the one-shot. Without the
  // confirmation read this never happens and the task would be re-attempted
  // forever (an unbounded duplicate storm); with it, the occurrence is consumed.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"c1","prompt":"commit me","delayMs":1000}`);
  h.advance(1000);
  assert.equal(h.injected.length, 1, "the occurrence is delivered once");
  assert.deepEqual(
    persistedTasks(h),
    [],
    "a CONFIRMED one-shot is durably REMOVED",
  );
});

test("FEATURE3 OPTION-D: a CONFIRMED interval advances to the cursor computed AT ARM TIME, not now()", () => {
  // STEP 5 requires the cursor to advance to the value computed when the
  // occurrence was ARMED. Using `now()` instead would let a long stall skip
  // occurrences beyond the designed coalescing rule. The first attempt is a
  // SWALLOWED refusal, so confirmation is delayed by the whole bounded window;
  // the committed cursor must still be the FIRST arm-time slot, not a slot
  // derived from the much later retry time.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"arm","prompt":"cadence","delayMs":1000,"intervalMs":1000}`);
  const declaredAt = h.tasksNow();
  const firstArmCursor = declaredAt + 1000 + 1000; // due at declare+1000, next slot +1000
  let attempts = 0;
  h.pi.sendUserMessage = (text) => {
    attempts += 1;
    h.injected.push(text);
    // Confirm ONLY the retry of the first occurrence; later occurrences stay
    // unconfirmed so the FIRST committed cursor is the one observed.
    if (attempts === 2) h.persistUserMessage(PARENT_UUID, text);
    return undefined;
  };
  // Run past the bounded confirmation window and the retry so the commit lands
  // at a time far later than the arm.
  h.advance(10_000);
  const committed = persistedTasks(h).find((t) => t.id === "arm")?.nextRunAtMs;
  assert.ok(attempts >= 2, `the refused attempt must be retried, saw ${attempts}`);
  assert.equal(
    committed,
    firstArmCursor,
    "the cursor is the ARM-TIME slot, not one recomputed from the late retry time",
  );
  assert.notEqual(committed, h.tasksNow() + 1000, "the cursor is NOT recomputed from now()");
});

test("FEATURE3 OPTION-D: an ASSISTANT message echoing the envelope does NOT confirm delivery", () => {
  // Correlation MUST require the exact envelope AND `role: \"user\"`. A model that
  // restates the envelope text in its own reply must never be mistaken for the
  // persisted delivery, or a refused send would be silently committed.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"echo","prompt":"must survive echo","delayMs":1000}`);
  // The host never persists the user row, but the assistant ECHOES an envelope
  // that happens to name the armed occurrence id.
  h.pi.sendUserMessage = (text) => {
    h.injected.push(text);
    const occurrenceId = occurrenceIdOf(text);
    assert.ok(occurrenceId, "the injected prompt carries the envelope");
    h.persistUserMessage(PARENT_UUID, text);
    h.persistUserMessage(PARENT_UUID, "I saw the trigger.");
    // Rewrite the persisted rows so ONLY an ASSISTANT row carries the envelope.
    const file = h.sessionFileFor(PARENT_UUID);
    writeFileSync(file, `${JSON.stringify(transcriptRow("assistant", text))}\n`);
    return undefined;
  };
  h.advance(1000);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["echo"],
    "an ASSISTANT echo of the envelope must NOT consume the one-shot",
  );
});

test("FEATURE3 OPTION-D: an envelope for a DIFFERENT occurrence id does NOT confirm this occurrence", () => {
  // The opaque id is the whole point of the correlation: a row naming ANOTHER
  // occurrence (a stale delivery, a different task run) must not commit THIS one.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"diff","prompt":"other id","delayMs":1000}`);
  h.pi.sendUserMessage = (text) => {
    h.injected.push(text);
    const occurrenceId = occurrenceIdOf(text);
    assert.ok(occurrenceId, "the injected prompt carries the envelope");
    // Persist a USER row whose envelope names a DIFFERENT occurrence id.
    const foreign = text.replace(occurrenceId, "oc-0000000000000000");
    assert.notEqual(foreign, text, "the substituted envelope differs");
    const file = h.sessionFileFor(PARENT_UUID);
    writeFileSync(file, `${JSON.stringify(transcriptRow("user", foreign))}\n`);
    return undefined;
  };
  h.advance(1000);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["diff"],
    "an envelope for a DIFFERENT occurrence id must NOT consume this one",
  );
});

test("FEATURE3 OPTION-D: a retry reuses the SAME occurrence id and advances the interval exactly once", () => {
  // At-least-once retry must NOT mint a new id per attempt; otherwise the first
  // (possibly delivered) attempt could never be correlated, and the duplicate
  // window would be unobservable. This stub refuses to persist the first TWO
  // attempts and persists the third, so the id is stable across retries.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"retry","prompt":"retry me","delayMs":0,"intervalMs":1000}`);
  let attempts = 0;
  const envelopes = [];
  h.pi.sendUserMessage = (text) => {
    attempts += 1;
    h.injected.push(text);
    envelopes.push(occurrenceIdOf(text));
    if (attempts >= 3) h.persistUserMessage(PARENT_UUID, text);
    return undefined;
  };
  // Long enough for the confirmation window (25 x 200ms) to exhaust, the handoff
  // to release, and two retries to be re-attempted.
  h.advance(20_000);
  assert.ok(attempts >= 3, `at-least-once retry must re-attempt, saw ${attempts}`);
  const firstOccurrence = envelopes.slice(0, 3);
  assert.equal(
    new Set(firstOccurrence).size,
    1,
    `every retry of one occurrence must reuse the SAME id, saw ${firstOccurrence}`,
  );
  assert.ok(firstOccurrence.every((id) => id !== null), "each attempt carries a well-formed envelope id");
});

test("FEATURE3 OPTION-D: a DELAYED transcript persistence is confirmed by the poll, not assumed from the send", () => {
  // Oracle OPTION D requires positive correlation, and the host appends to the
  // transcript AFTER `message_start`/`message_end` (`agent-session.js:748-763`).
  // The existing tests persist SYNCHRONOUSLY inside `sendUserMessage`, so they
  // only ever exercise the immediate post-send check and never the poll. This test
  // persists LATE: the send returns with an EMPTY transcript, so the immediate
  // post-send check at `pumpTask` MUST fail and the row can only be observed by a
  // later poll.
  //
  // The window must be tight or the test is VACUOUS. Two traps were proved out
  // against the product:
  //   * Persisting and then advancing past the whole bounded window lets the
  //     exhausted poll re-pump the SAME occurrence, and that RETRY's immediate
  //     post-send check sees the row - so the removal would be proved by the next
  //     attempt, never by a poll. (`attempts` reached 2 in a probe.)
  //   * Asserting only "task removed" cannot tell those apart.
  // The discriminator is therefore `h.injected.length === 1`: the row is persisted
  // strictly after the immediate check and BEFORE the first poll tick, and the
  // clock advances by exactly one poll interval, so ONLY the poll tick can commit
  // it. Disabling `confirmedInTranscript` at the poll site fails this test: no
  // commit happens at the tick, the window exhausts, and a SECOND attempt is made
  // (whose immediate check would then remove the task) - observable as
  // `injected.length === 2`.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"late","prompt":"delayed","delayMs":0}`);

  let pending = null;
  let sends = 0;
  h.pi.sendUserMessage = (text) => {
    h.injected.push(text);
    sends += 1;
    // Deliberately do NOT persist now: the host has not written the row yet, so
    // the immediate post-send check must fail.
    pending = text;
    return undefined;
  };

  // Run the timer that delivers the occurrence, but ONLY far enough for the send
  // and its immediate check to happen - NOT far enough for the first poll tick.
  h.advance(1);
  assert.equal(sends, 1, "precondition: exactly one attempt was sent");
  assert.ok(pending !== null, "precondition: an attempt was made");
  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["late"],
    "precondition: the unconfirmed one-shot is retained, not consumed",
  );

  // The transcript row lands in the gap between the immediate check and the first
  // poll tick. From here, ONLY a poll can see it.
  h.persistUserMessage(PARENT_UUID, pending);
  h.advance(TASK_CONFIRM_RETRY_MS);

  assert.deepEqual(
    persistedTasks(h),
    [],
    "the late-persisted occurrence is confirmed by the POLL and the one-shot is removed",
  );
  // No retry was ever needed: the poll - not a later attempt's send-time check -
  // observed the row. This is what fails when the poll's re-check is disabled.
  assert.equal(
    h.injected.length,
    1,
    "confirmation came from the poll, not from a later attempt's immediate check",
  );
});

test("FEATURE3 OPTION-D: superseded confirmation work cannot corrupt the REPLACEMENT record", () => {
  // HIGH-1's sibling: when a task is replaced mid-confirmation, the superseded
  // occurrence must not later commit against the replacement. The replacement's
  // prompt and schedule are the operator's new intent and must survive intact.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);

  let withheld = null;
  h.pi.sendUserMessage = (text) => {
    h.injected.push(text);
    withheld = text; // never persisted: keeps occurrence A unconfirmed
    return undefined;
  };
  h.declare(PARENT_UUID, `TASK:ADD {"id":"y","prompt":"old intent","delayMs":0}`);
  h.advance(1000);

  // Replace while A is still unconfirmed, with a distinct new schedule.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"y","prompt":"new intent","delayMs":5000}`);
  // Now let the superseded occurrence's row land and run pending polls.
  h.persistUserMessage(PARENT_UUID, withheld);
  h.advance(1000);

  const after = persistedTasks(h).filter((t) => t.id === "y");
  assert.equal(after.length, 1, "exactly one replacement record exists");
  assert.equal(after[0].prompt, "new intent", "the replacement prompt is intact");
  assert.ok(
    after[0].nextRunAtMs > h.nowValue(),
    "and the replacement keeps its OWN future schedule, not a superseded cursor",
  );
});

test("FEATURE3 HIGH-1: replacing a task while its occurrence is UNCONFIRMED retires the old poll and handoff", () => {
  // Oracle final Review HIGH-1. `addTask` replaces the record with
  // `tasks.set(task.id, task)` and then calls `armTask`, which clears only the
  // FIRING timer (`clearTaskTimer`). The superseded occurrence's confirmation poll
  // (`confirmTimers`) and the task handoff (`taskHandoff`) survive. The old poll
  // then finds a replacement whose `occurrenceId` is undefined, hits the stale
  // return at the `task.occurrenceId !== occurrenceId` check, and returns WITHOUT
  // releasing the handoff or clearing the poll. Every later pump of that id then
  // defers forever at the `taskHandoff !== null` gate, stalling the replacement
  // and all subsequent work - a multi-day liveness failure.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);

  // The task is due immediately, but the host never persists, so occurrence A
  // stays UNCONFIRMED and its confirmation poll remains pending.
  h.pi.sendUserMessage = (text) => {
    h.injected.push(text);
    return undefined;
  };
  h.declare(PARENT_UUID, `TASK:ADD {"id":"x","prompt":"first","delayMs":0}`);
  h.advance(1000);
  assert.ok(
    h.injected.some((t) => /first/.test(t)),
    "precondition: the first occurrence was attempted and left unconfirmed",
  );

  // Replace `x` under the SAME id while A's confirmation poll is still pending.
  // The replacement is due in the future so only the RETIREMENT of A's handoff is
  // under test here, not a new delivery.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"x","prompt":"replacement","delayMs":600000}`);
  assert.deepEqual(
    persistedTasks(h).map((t) => t.prompt),
    ["replacement"],
    "precondition: the replacement replaced the record",
  );

  // Add an unrelated, independently due task. With the handoff properly retired it
  // must be delivered; while the superseded handoff pins the slot, it never is.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"later","prompt":"later task","delayMs":0}`);
  h.advance(30_000);

  assert.ok(
    h.injected.some((t) => /later task/.test(t)),
    "a later task must be delivered: the superseded handoff did not pin the slot",
  );

  // And once the replacement comes due it must actually be delivered, proving the
  // task itself is not permanently stalled behind the stale handoff.
  h.pi.sendUserMessage = (text) => {
    h.injected.push(text);
    h.persistUserMessage(PARENT_UUID, text);
    return undefined;
  };
  h.advance(700_000);
  assert.ok(
    h.injected.some((t) => /replacement/.test(t)),
    "the replacement must be delivered once due, not deferred forever",
  );
});

test("FEATURE3 OPTION-D: repeated unconfirmed attempts across an interval advance leave the task consistent", () => {
  // The `task.occurrenceId !== occurrenceId` guard in `commitOccurrence` defends
  // against a stale poll (armed for A, running after the task advanced to B).
  // Instrumenting the product showed that path is not reachable through the
  // public API: an id is minted only when `task.occurrenceId === undefined`, and
  // the only other mint (`commitOccurrence` advancing an interval) clears the
  // confirm timer first. So the guard is defence-in-depth, not a live path.
  //
  // This test pins the INVARIANT that makes it unreachable, which is the property
  // that actually protects the design. It exercises the interleaving that would
  // violate it - unconfirmed attempts that exhaust and re-attempt while the
  // interval keeps advancing - and asserts the observable consequences hold.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(
    PARENT_UUID,
    `TASK:ADD {"id":"inv","prompt":"payload","delayMs":0,"intervalMs":200}`,
  );

  const envelopes = [];
  let persist = false;
  h.pi.sendUserMessage = (text) => {
    h.injected.push(text);
    envelopes.push(occurrenceIdOf(text));
    if (persist) h.persistUserMessage(PARENT_UUID, text);
    return undefined;
  };

  // Phase 1: unconfirmed attempts; each poll pends and then exhausts.
  h.advance(6000);
  // Phase 2: confirmation resumes, so the interval advances and mints new ids.
  persist = true;
  h.advance(20_000);

  const ids = envelopes.filter((id) => id !== null);
  assert.ok(
    new Set(ids).size >= 2,
    `precondition: the interval advanced to new occurrence ids, saw ${new Set(ids).size}`,
  );
  // The run must end in a consistent state: the task survives, keeps its
  // definition, and is armed for a real occurrence. A stale-poll commit would
  // have corrupted exactly these fields.
  const remaining = persistedTasks(h);
  assert.deepEqual(remaining.map((t) => t.id), ["inv"], "the interval task survives");
  assert.equal(remaining[0].intervalMs, 200, "its interval definition is unchanged");
  assert.ok(
    typeof remaining[0].occurrenceId === "string" && remaining[0].occurrenceId.length > 0,
    "and it is armed for a real occurrence, never left with a corrupt id",
  );
  // Retries of one occurrence deliberately REUSE its id (at-least-once), and an
  // id can legitimately be ARMED but not yet SENT when the run ends at a due
  // boundary. This test asserts only what is observable through the public API.
  //
  // NOTE (MEDIUM-1, final Review): an earlier version of this test was named for
  // an invariant about confirmation-poll REGISTRATION that the public API cannot
  // observe, and backed it with `new Set(x).size <= x.length` - a tautology, since
  // a Set built from an array is never larger than that array. Poll registration is
  // now covered as real behaviour by the HIGH-1 replacement regression above; this
  // test asserts delivery-level consistency only.
  const sentIds = ids.filter((id) => id !== null);
  assert.ok(
    sentIds.every((id) => /^oc-[0-9a-f]+$/.test(id)),
    "every delivered occurrence carries a well-formed id",
  );
  // The interval advances by confirmation, so at least one new occurrence must
  // have been minted after the first - a stale commit would have skipped this.
  assert.ok(
    new Set(sentIds).size >= 2,
    `confirmation must have advanced to a fresh occurrence, saw ${new Set(sentIds).size}`,
  );
  assert.ok(
    remaining[0].nextRunAtMs > 0,
    "and the task carries a real next-run cursor",
  );
});

test("FEATURE3 OPTION-D: exhausted confirmation attempts RELEASE the handoff so a later task is not stalled", () => {
  // Review 78 HIGH-1: a task pinned behind a never-settling handoff stalled every
  // later task. Exhaustion must release the slot. Task `first` is due earlier and
  // never confirms (swallowed refusal); task `second` becomes due afterwards and
  // must still be delivered.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"first","prompt":"never confirms","delayMs":0}`);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"second","prompt":"must not stall","delayMs":5000}`);
  const refused = [];
  h.pi.sendUserMessage = (text) => {
    if (/occurrence .*\]\nnever confirms/.test(text)) {
      refused.push(text);
      return undefined; // swallowed refusal: no throw, no persisted row
    }
    h.injected.push(text);
    h.persistUserMessage(PARENT_UUID, text);
    return undefined;
  };
  // The first attempt is swallowed; its bounded confirmation window (25 x 200ms)
  // must exhaust, releasing the handoff before `second` comes due at 5000ms.
  h.advance(20_000);
  assert.ok(refused.length >= 1, "the first task's send was attempted");
  assert.ok(
    h.injected.some((text) => /must not stall/.test(text)),
    "the later task is delivered once the stalled task's handoff is released",
  );
});

test("FEATURE3 OPTION-D: a restart re-attempts an armed, unconfirmed occurrence with the SAME id (at-least-once)", () => {
  // STEP 8: the pending record is the outbox. A task whose `nextRunAtMs` is in
  // the past and whose `occurrenceId` was never confirmed must be re-attempted on
  // restart, reusing the SAME id, so a delivered-but-unrecorded occurrence is at
  // worst duplicated (the documented at-least-once duplicate window) and never
  // lost. This models the store left behind by a process that armed and sent but
  // was killed before the transcript read could confirm.
  const dir = mkdtempSync(join(tmpdir(), "supervisor-f3-restart-"));
  const tasksPath = join(dir, "session-supervisor", "tasks.json");
  const armed = {
    id: "resume",
    sessionId: PARENT_UUID,
    prompt: "survive restart",
    nextRunAtMs: 1, // long past
    occurrenceId: "oc-fixedrestart0000000000000000",
  };
  mkdirSync(join(dir, "session-supervisor"), { recursive: true });
  writeFileSync(tasksPath, JSON.stringify({ version: 1, tasks: [armed] }, null, 2));
  const h = feature3Harness({ tasksPath });
  const envelopes = [];
  h.pi.sendUserMessage = (text) => {
    h.injected.push(text);
    envelopes.push(occurrenceIdOf(text));
    h.persistUserMessage(PARENT_UUID, text);
    return undefined;
  };
  h.sessionStart(PARENT_UUID, "reload");
  h.advance(1000);
  assert.ok(h.injected.length >= 1, "the past-due unconfirmed occurrence is re-attempted after restart");
  assert.equal(
    envelopes[0],
    "oc-fixedrestart0000000000000000",
    "the re-attempt reuses the SAME persisted occurrence id",
  );
  assert.deepEqual(
    persistedTasks(h),
    [],
    "once confirmed, the one-shot is durably removed",
  );
});

// ---------------------------------------------------------------------------
// FEATURE 3 g2 corrections: review-correction regressions.
//
// Blocker 1: an UNCONFIRMABLE oversized `TASK:ADD` prompt must be REJECTED at
// `addTask` BEFORE it is accepted/persisted, because delivery is confirmed only
// by positively correlating the persisted transcript row and the confirmation
// read sees just the last `TRANSCRIPT_TAIL_BYTES` of the transcript. Blocker 2:
// `persistTasks` must let the CURRENT on-disk copy of a FOREIGN record win
// (replacements AND deletions), rather than re-serializing a stale cached copy.
// ---------------------------------------------------------------------------

/** Drive one `agent_before_settle` declaration and return the captured OSC chunks. */
function declareCapturing(h, sid, text) {
  const capture = captureStdout();
  try {
    h.pi.emit("agent_before_settle", boundaryEvent([assistant(text)]), h.ctxFor(sid));
  } finally {
    capture.restore();
  }
  return capture.chunks;
}

// The g3 rejection notice is a DISTINCT OSC 777 payload that NAMES the refusal,
// the model-chosen id, and the limit. `mod.taskRejectionNotice` is the product's
// own builder, so the test asserts the product's actual diagnostic bytes rather
// than the generic `OSC_NOTIFY` constant (which an ordinary marker-less settle
// emits even when the size guard is disabled - the non-discriminating assertion
// the independent Review flagged).
const rejectionNotice = (reason, taskId) => mod.taskRejectionNotice(reason, taskId);

test("FEATURE3 g2 B1: an oversized TASK:ADD prompt is REJECTED (notified, not persisted, never armed)", () => {
  // The worst-case serialized-row bound is `6 * codeUnits + overhead`, so a
  // prompt whose worst case exceeds the 512 KiB confirmation tail can NEVER be
  // positively correlated; re-sending it forever is the failure mode. A 200_000
  // code-unit ASCII prompt is under the tail size in raw chars (so a naive
  // `prompt.length > TRANSCRIPT_TAIL_BYTES` guard would ACCEPT it) yet its
  // worst-case row (6 * 200_000 = 1_200_000) exceeds the tail and must be refused.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  const body = JSON.stringify({ id: "big", prompt: "x".repeat(200_000), delayMs: 1000 });

  const chunks = declareCapturing(h, PARENT_UUID, `TASK:ADD ${body}`);

  // g3 blocker 2: assert the ACTUAL diagnostic, not just "some notice". The
  // refusal, the id, and the limit must all be present in the emitted bytes.
  const notice = chunks.find((chunk) => chunk.includes("rejected:"));
  assert.ok(notice !== undefined, `the rejection must emit a diagnostic notice, got ${JSON.stringify(chunks)}`);
  assert.ok(notice.includes("big"), "the diagnostic NAMES the rejected task id");
  assert.ok(notice.includes("too large to confirm delivery"), "the diagnostic NAMES the refusal reason");
  assert.ok(
    notice.includes(String(mod.TRANSCRIPT_TAIL_BYTES)),
    `the diagnostic NAMES the confirmation-tail limit (${mod.TRANSCRIPT_TAIL_BYTES})`,
  );
  assert.equal(
    notice,
    rejectionNotice(
      `prompt too large to confirm delivery (worst-case ${mod.worstCaseTaskRowBytes("big", "x".repeat(200_000))} bytes exceeds the ${mod.TRANSCRIPT_TAIL_BYTES}-byte confirmation tail)`,
      "big",
    ),
    "the refusal notice is the product's exact diagnostic payload",
  );
  assert.deepEqual(
    persistedTasks(h),
    [],
    "an unconfirmable task is NOT persisted (no unconfirmable outbox record)",
  );
  // The rejected task must not be armed either: advancing past its due time must
  // produce no injection.
  h.advance(60_000);
  assert.equal(h.injected.length, 0, "a rejected task is never armed and never fires");
});

test("FEATURE3 g2 B1: a multibyte/escaping prompt is bounded by serialized BYTES, not char count", () => {
  // The bound must account for JSON escaping and multibyte expansion, not just
  // the character count. A prompt of 50_000 astral code points is 100_000 UTF-16
  // code units and only 200_000 UTF-8 bytes, but its serialized worst case is
  // 6 * 100_000 = 600_000 > the tail, so it must be rejected - whereas a naive
  // UTF-8-byte-length or code-point-count check would accept it.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  const body = JSON.stringify({ id: "emoji", prompt: "\u{1F600}".repeat(50_000), delayMs: 1000 });

  const chunks = declareCapturing(h, PARENT_UUID, `TASK:ADD ${body}`);

  const notice = chunks.find((chunk) => chunk.includes("rejected:"));
  assert.ok(notice !== undefined, `a multibyte-over-bound prompt is visibly rejected, got ${JSON.stringify(chunks)}`);
  assert.ok(notice.includes("emoji"), "the diagnostic NAMES the rejected task id");
  assert.ok(
    notice.includes(String(mod.TRANSCRIPT_TAIL_BYTES)),
    "the diagnostic NAMES the confirmation-tail limit",
  );
  assert.deepEqual(persistedTasks(h), [], "and is not persisted");
  h.advance(60_000);
  assert.equal(h.injected.length, 0, "and is never armed");
});

test("FEATURE3 g2 B1: a comfortably small prompt is still accepted and commits EXACTLY ONCE", () => {
  // The rejection must not disturb the accepted path: a prompt comfortably under
  // the limit (the size used throughout this suite) is accepted, persisted, fires
  // once, is confirmed by the transcript, and is removed - no duplicate, no loss.
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"ok","prompt":"check the build","delayMs":1000}`);

  assert.deepEqual(
    persistedTasks(h).map((t) => t.id),
    ["ok"],
    "a small prompt is accepted and persisted",
  );
  h.advance(1000);
  assert.equal(h.injected.length, 1, "it fires exactly once");
  assert.match(h.injected[0], envelopePrompt("ok", "check the build"), "with the exact envelope + prompt");
  assert.deepEqual(persistedTasks(h), [], "a confirmed one-shot is durably removed");
  h.advance(60_000);
  assert.equal(h.injected.length, 1, "and never re-sends: exactly one delivery in total");
});

test("FEATURE3 g2 B2: owner B's write does NOT resurrect a foreign task owner A CANCELLED", () => {
  // SEQUENTIAL two-owner case. Owner B caches foreign task `a` when it first
  // persists (the merge imports it). Owner A then CANCELS `a`, so disk becomes
  // `["b"]`. When B writes `b2`, the OLD code saw `tasks.has("a") === true`,
  // skipped the disk copy, and re-serialized the stale cached `a` - resurrecting a
  // task the user cancelled. The current on-disk copy must win: `a` stays deleted.
  const shared = join(mkdtempSync(join(tmpdir(), "supervisor-f3-g2-a-")), "session-supervisor", "tasks.json");
  mkdirSync(dirname(shared), { recursive: true });
  // Disk starts with owner A's task `a` (a foreign session for B).
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [{ id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 }],
    }),
  );
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  // B declares `b`, which persists and (correctly) imports foreign `a` into B's map.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"b","prompt":"owner B task","delayMs":1000}`);
  assert.ok(
    JSON.parse(readFileSync(shared, "utf8")).tasks.some((t) => t.id === "a"),
    "precondition: B imported the foreign `a` into the shared store",
  );

  // Owner A CANCELS `a`: A's own write drops `a` and keeps `b` (foreign to A).
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [{ id: "b", sessionId: PARENT_UUID, prompt: "owner B task", nextRunAtMs: 1_001_000 }],
    }),
  );

  // B now writes again (adds `b2`).
  h.declare(PARENT_UUID, `TASK:ADD {"id":"b2","prompt":"owner B second","delayMs":1000}`);

  const ids = JSON.parse(readFileSync(shared, "utf8")).tasks.map((t) => t.id).sort();
  assert.deepEqual(ids, ["b", "b2"], `a cancelled foreign task must NOT be resurrected, got ${ids}`);
});

test("FEATURE3 g2 B2: a foreign REPLACEMENT on disk is preserved (B does not restore its stale copy)", () => {
  // Owner B caches foreign task `c` (prompt "old"). The owner of `c` then REPLACES
  // it on disk (prompt "new"). When B writes another task, the OLD code skipped
  // the disk copy (`tasks.has("c")`) and re-serialized B's stale cached "old",
  // discarding the foreign update. The current on-disk record must win.
  const shared = join(mkdtempSync(join(tmpdir(), "supervisor-f3-g2-b-")), "session-supervisor", "tasks.json");
  mkdirSync(dirname(shared), { recursive: true });
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [{ id: "c", sessionId: "owner-c-session-uuid", prompt: "old", nextRunAtMs: 9_000_000 }],
    }),
  );
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"d","prompt":"owner B task","delayMs":1000}`);
  assert.equal(
    JSON.parse(readFileSync(shared, "utf8")).tasks.find((t) => t.id === "c").prompt,
    "old",
    "precondition: B cached the foreign `c` with prompt \"old\"",
  );

  // The owner of `c` replaces it on disk (a NEW prompt) while keeping B's task.
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [
        { id: "c", sessionId: "owner-c-session-uuid", prompt: "new", nextRunAtMs: 9_500_000 },
        { id: "d", sessionId: PARENT_UUID, prompt: "owner B task", nextRunAtMs: 1_001_000 },
      ],
    }),
  );

  h.declare(PARENT_UUID, `TASK:ADD {"id":"d2","prompt":"owner B second","delayMs":1000}`);

  const onDisk = JSON.parse(readFileSync(shared, "utf8")).tasks;
  const c = onDisk.find((t) => t.id === "c");
  assert.ok(c, "the foreign `c` is still present");
  assert.equal(c.prompt, "new", "the CURRENT on-disk foreign replacement wins over B's stale cached copy");
  assert.deepEqual(
    onDisk.map((t) => t.id).sort(),
    ["c", "d", "d2"],
    "B's own tasks are present and the foreign record is not lost",
  );
});

// ---------------------------------------------------------------------------
// FEATURE 3 g3 corrections: a second Review round (run 2209950b) failed two
// delivery blockers. Blocker 1: an UNREADABLE/OVERSIZED store was treated as an
// authoritative EMPTY foreign snapshot, so a successful rename PRUNED every
// cached foreign record. Blocker 2: the oversize refusal passed its diagnostic
// into `notify`'s `why` enum, discarding it (and notification dedup could
// suppress even the generic notice).
// ---------------------------------------------------------------------------

test("FEATURE3 g3 B1: an oversized/unreadable store is NOT treated as an empty foreign snapshot", () => {
  // The production read path: `readFile` is `defaultReadFile`, whose 2 MiB
  // artifact cap makes a large-but-WRITABLE store read as `null`. The old code
  // conflated "unreadable" with "empty": `foreign = []`, then a successful
  // rename re-serialized the map WITHOUT the foreign records - DELETING another
  // owner's tasks. This test uses the REAL fs reader (no injected readFile), so it
  // exercises the actual 2 MiB rejection at `defaultReadFile`.
  const shared = join(mkdtempSync(join(tmpdir(), "supervisor-f3-g3-a-")), "session-supervisor", "tasks.json");
  mkdirSync(dirname(shared), { recursive: true });
  // A small, READABLE store: owner A's foreign `a` (cached by B) plus B's `b`.
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [
        { id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 },
        { id: "b", sessionId: PARENT_UUID, prompt: "owner B task", nextRunAtMs: 1_001_000 },
      ],
    }),
  );
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  // B re-persists, importing foreign `a` into B's in-memory map (precondition).
  h.declare(PARENT_UUID, `TASK:ADD {"id":"b2","prompt":"owner B second","delayMs":1000}`);
  assert.ok(
    JSON.parse(readFileSync(shared, "utf8")).tasks.some((t) => t.id === "a"),
    "precondition: B cached the foreign `a` and it is on disk",
  );

  // The store GROWS past the 2 MiB artifact cap. It still holds foreign `a` AND a
  // foreign `z` that B has NEVER read into memory.
  const huge = {
    version: 1,
    tasks: [
      { id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 },
      { id: "z", sessionId: "owner-z-session-uuid", prompt: "z".repeat(2_500_000), nextRunAtMs: 9_000_000 },
      { id: "b", sessionId: PARENT_UUID, prompt: "owner B task", nextRunAtMs: 1_001_000 },
      { id: "b2", sessionId: PARENT_UUID, prompt: "owner B second", nextRunAtMs: 1_001_000 },
    ],
  };
  writeFileSync(shared, JSON.stringify(huge));
  assert.ok(readFileSync(shared, "utf8").length > 2 * 1024 * 1024, "the store now exceeds the 2 MiB artifact cap");

  // B writes again. The store exists but is unreadable THROUGH THE ARTIFACT
  // READER; the store's own (uncapped) reader must still yield an authoritative
  // snapshot so no foreign record is pruned.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"b3","prompt":"owner B third","delayMs":1000}`);

  const ids = JSON.parse(readFileSync(shared, "utf8")).tasks.map((t) => t.id).sort();
  assert.ok(ids.includes("a"), `the cached foreign \`a\` must NOT be pruned when the store is unreadable, got ${ids}`);
  assert.ok(ids.includes("z"), `the uncached foreign \`z\` must survive an authoritative store read, got ${ids}`);
  assert.ok(ids.includes("b") && ids.includes("b2") && ids.includes("b3"), `B's owned tasks must all persist, got ${ids}`);
});

test("FEATURE3 g3 B1 control: a genuinely ABSENT store is still a valid first write", () => {
  // The gate must NOT turn a first write into a failure: a store that does not
  // exist yet is confirmed absent, so the owned ADD persists normally.
  const shared = join(mkdtempSync(join(tmpdir(), "supervisor-f3-g3-empty-")), "session-supervisor", "tasks.json");
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"first","prompt":"first write","delayMs":1000}`);
  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["first"], "a first write still persists");
  h.advance(1000);
  assert.equal(h.injected.length, 1, "and the task still fires exactly once");
});

test("FEATURE3 g3 B2: the refusal diagnostic is emitted VERBATIM and is NOT suppressed by notification dedup", () => {
  // The old code called `notify(OSC_NOTIFY, "<diagnostic>")`, passing the text
  // into the `why` ENUM so it was discarded; the generic notice may also be
  // suppressed by the `notified` dedupe. This drives a settle FIRST (which sets
  // the dedupe flag), then an oversized declaration, and requires the diagnostic
  // to still be observable - which fails on the old code (no output at all).
  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  // An in-TUI settle sets `notified`, so a plain `notify` would now be a no-op.
  const settleChunks = declareCapturing(h, PARENT_UUID, "STATUS:DONE");
  assert.ok(settleChunks.length > 0, "the settle emitted at least one notice (dedupe flag set)");

  const id = "big-dedup";
  const prompt = "x".repeat(200_000);
  const body = JSON.stringify({ id, prompt, delayMs: 1000 });
  const chunks = declareCapturing(h, PARENT_UUID, `TASK:ADD ${body}`);

  assert.ok(
    chunks.includes(
      rejectionNotice(
        `prompt too large to confirm delivery (worst-case ${mod.worstCaseTaskRowBytes(id, prompt)} bytes exceeds the ${mod.TRANSCRIPT_TAIL_BYTES}-byte confirmation tail)`,
        id,
      ),
    ),
    `the refusal diagnostic must be emitted verbatim even after dedupe, got ${JSON.stringify(chunks)}`,
  );
  assert.deepEqual(persistedTasks(h), [], "and the rejected task is not persisted");
});

test("FEATURE3 g3 B2: a model-authored id cannot inject control bytes into the refusal escape sequence", () => {
  // The task id is model-chosen, so the refusal notice MUST sanitize it: BEL
  // (`\x07`) terminates the OSC payload and ESC (`\x1b`) could begin a new
  // sequence. A poisoned id must appear only as printable ASCII, never raw.
  const sanitized = mod.sanitizeOscField("evil\x07\x1b]2;owned\x07");
  assert.ok(!sanitized.includes("\x07"), "no BEL survives sanitization");
  assert.ok(!sanitized.includes("\x1b"), "no ESC survives sanitization");
  assert.equal(sanitized, "evil??]2;owned?", "each non-printable byte becomes `?` (BEL and ESC are two bytes)");

  const h = feature3Harness();
  h.sessionStart(PARENT_UUID);
  const id = "evil\x07\x1b]2;pwn";
  const body = JSON.stringify({ id, prompt: "x".repeat(200_000), delayMs: 1000 });
  const chunks = declareCapturing(h, PARENT_UUID, `TASK:ADD ${body}`);
  const notice = chunks.find((chunk) => chunk.includes("rejected:"));
  assert.ok(notice !== undefined, "the refusal is emitted");
  // Exactly one BEL, at the very end: the id did not terminate the sequence early.
  assert.equal(notice.split("\x07").length - 1, 1, "the payload contains exactly one BEL terminator");
  assert.ok(notice.endsWith("\x07"), "the BEL terminator is last");
  assert.ok(!notice.includes("\x1b]2;pwn"), "the raw model id never reaches the escape sequence");
});

// ---------------------------------------------------------------------------
// FEATURE 3 g4 corrections (run 4d9ba907, B1 completion): the authoritative-store
// gate in `persistTasks` was still INCOMPLETE on two SEQUENTIAL paths that both
// replaced an EXISTING store nobody had actually read:
//   (1) BOTH readers fail -> `authoritative` stays false but the temp write and
//       rename still ran unconditionally, replacing an unreadable store from a
//       stale in-memory map and deleting foreign records this process never
//       cached.
//   (2) The store reads non-null but does NOT parse to `{tasks: [...]}` -> the
//       old `parseTaskStore` returned `[]`, so a PARSE FAILURE masqueraded as an
//       authoritative EMPTY snapshot, licensing a prune-and-replace.
// These tests pin the corrected semantics: an existing store is replaced ONLY on
// a successfully READ and successfully PARSED authoritative snapshot. A failed
// read or a malformed/foreign-shaped store returns false BEFORE any reconcile,
// prune, temp serialization, or rename, leaving the on-disk bytes byte-identical.
// ---------------------------------------------------------------------------

/**
 * Read the store bytes back after a test made the file unreadable.
 *
 * The `chmod 000` that models "both readers fail" also blocks the TEST process
 * from reading its own fixture, so permissions are restored first. This only
 * changes the mode, never the content, so it cannot mask a byte change.
 */
const readBytesRestoringMode = (path) => {
  chmodSync(path, 0o644);
  return readFileSync(path, "utf8");
};

test("FEATURE3 g4 B1 both readers fail: an existing unreadable store is NOT replaced from a stale map", () => {
  const dir = mkdtempSync(join(tmpdir(), "supervisor-f3-g4-a-"));
  const shared = join(dir, "tasks.json");
  // Disk starts with owner A's foreign task `a`.
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [{ id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 }],
    }),
  );
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  // B persists `b2`, which imports the foreign `a` into B's in-memory map.
  h.declare(PARENT_UUID, `TASK:ADD {"id":"b2","prompt":"owner B task","delayMs":3000}`);
  assert.ok(
    JSON.parse(readFileSync(shared, "utf8")).tasks.some((t) => t.id === "a"),
    "precondition: B cached the foreign `a` (it is re-serialized on B's write)",
  );

  // A foreign owner writes another record `z` that B has NEVER read into memory.
  // The on-disk bytes are captured EXACTLY so equality can be asserted verbatim.
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [
        { id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 },
        { id: "z", sessionId: "owner-z-session-uuid", prompt: "Z task never cached by B", nextRunAtMs: 9_000_000 },
        { id: "b2", sessionId: PARENT_UUID, prompt: "owner B task", nextRunAtMs: 1_003_000 },
      ],
    }),
  );
  const before = readFileSync(shared, "utf8");

  // BOTH readers now fail: the artifact reader's `openSync` throws EACCES and so
  // does the uncapped `readFileSync`. The directory stays writable, so a rename
  // would still be possible - that is exactly the unsafe path under test.
  chmodSync(shared, 0o000);

  // Drive a write attempt through the FIRING path, which GATES on the persist
  // result: a false persist means the occurrence is NOT delivered (it is retried).
  h.advance(3000);

  assert.equal(h.injected.length, 0, "a failed authoritative read must make the write attempt return false (no delivery)");
  const after = readBytesRestoringMode(shared);
  assert.equal(after, before, "the on-disk bytes must be EXACTLY unchanged when neither reader could read the store");
  const ids = JSON.parse(after).tasks.map((t) => t.id).sort();
  assert.ok(ids.includes("z"), `a foreign record never cached by B must survive, got ${ids}`);
});

test("FEATURE3 g4 B1 corrupt store: malformed JSON is NOT an authoritative empty snapshot", () => {
  const dir = mkdtempSync(join(tmpdir(), "supervisor-f3-g4-b-"));
  const shared = join(dir, "tasks.json");
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [
        { id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 },
        { id: "b2", sessionId: PARENT_UUID, prompt: "owner B task", nextRunAtMs: 1_003_000 },
      ],
    }),
  );
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"b3","prompt":"owner B second","delayMs":3000}`);
  assert.ok(
    JSON.parse(readFileSync(shared, "utf8")).tasks.some((t) => t.id === "a"),
    "precondition: B cached the foreign `a`",
  );

  // The store becomes MALFORMED. It is still small and read by the artifact
  // reader, so `raw` is non-null - the old code then treated the parse failure as
  // an authoritative EMPTY snapshot and pruned `a` on the next write.
  const corrupt = "{ this is not valid json";
  writeFileSync(shared, corrupt);

  h.advance(3000);

  assert.equal(h.injected.length, 0, "a malformed store must make the write attempt return false (no delivery)");
  assert.equal(readFileSync(shared, "utf8"), corrupt, "a malformed store must be left byte-identical");
});

test("FEATURE3 g4 B1 invalid top-level shape: a non-`{tasks:[...]}` JSON store is NOT authoritative", () => {
  const dir = mkdtempSync(join(tmpdir(), "supervisor-f3-g4-c-"));
  const shared = join(dir, "tasks.json");
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [
        { id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 },
        { id: "b2", sessionId: PARENT_UUID, prompt: "owner B task", nextRunAtMs: 1_003_000 },
      ],
    }),
  );
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"b3","prompt":"owner B second","delayMs":3000}`);
  assert.ok(
    JSON.parse(readFileSync(shared, "utf8")).tasks.some((t) => t.id === "a"),
    "precondition: B cached the foreign `a`",
  );

  // Valid JSON, but `tasks` is NOT an array: `parseTaskStore` yields `[]`, which
  // the old code mistook for an authoritative empty store.
  const wrongShape = JSON.stringify({ version: 1, tasks: 5 });
  writeFileSync(shared, wrongShape);

  h.advance(3000);

  assert.equal(h.injected.length, 0, "an invalid top-level shape must make the write attempt return false (no delivery)");
  assert.equal(readFileSync(shared, "utf8"), wrongShape, "an invalid top-level shape must be left byte-identical");
});

test("FEATURE3 g4 B1 valid empty store: `{\"version\":1,\"tasks\":[]}` IS authoritative and a write proceeds", () => {
  // The discriminating CONTROL: an empty-but-VALID store is a real authoritative
  // snapshot, so the gate must NOT turn a legitimate first-ish write into a
  // failure. This is what separates "malformed" from "legitimately empty".
  const dir = mkdtempSync(join(tmpdir(), "supervisor-f3-g4-d-"));
  const shared = join(dir, "tasks.json");
  writeFileSync(shared, JSON.stringify({ version: 1, tasks: [] }));

  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  h.declare(PARENT_UUID, `TASK:ADD {"id":"fresh","prompt":"into a valid empty store","delayMs":1000}`);

  assert.deepEqual(persistedTasks(h).map((t) => t.id), ["fresh"], "a write into a valid empty store must persist");
  h.advance(1000);
  assert.equal(h.injected.length, 1, "and the task must still fire exactly once");
});

test("FEATURE3 g4 B1 recovery after readability returns: a failed attempt is retried and succeeds", () => {
  const dir = mkdtempSync(join(tmpdir(), "supervisor-f3-g4-e-"));
  const shared = join(dir, "tasks.json");
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [{ id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 }],
    }),
  );
  const h = feature3Harness({ tasksPath: shared });
  h.sessionStart(PARENT_UUID);
  // An INTERVAL task is retained after a confirmed firing, so the recovered run
  // can assert the owned intent is PRESENT on disk (a one-shot would be removed
  // by design once delivered).
  h.declare(PARENT_UUID, `TASK:ADD {"id":"b2","prompt":"owner B task","delayMs":3000,"intervalMs":10000}`);
  assert.ok(
    JSON.parse(readFileSync(shared, "utf8")).tasks.some((t) => t.id === "a"),
    "precondition: B cached the foreign `a`",
  );

  // A foreign owner adds `z` (never cached by B); capture the exact bytes.
  writeFileSync(
    shared,
    JSON.stringify({
      version: 1,
      tasks: [
        { id: "a", sessionId: "owner-a-session-uuid", prompt: "A task", nextRunAtMs: 9_000_000 },
        { id: "z", sessionId: "owner-z-session-uuid", prompt: "Z task never cached by B", nextRunAtMs: 9_000_000 },
        { id: "b2", sessionId: PARENT_UUID, prompt: "owner B task", nextRunAtMs: 1_003_000 },
      ],
    }),
  );
  const before = readFileSync(shared, "utf8");

  // Unreadable store: the attempt fails closed and the bytes survive.
  chmodSync(shared, 0o000);
  h.advance(3000);
  assert.equal(h.injected.length, 0, "the first attempt must fail closed while unreadable");
  assert.equal(readBytesRestoringMode(shared), before, "the failed attempt must leave the store byte-identical");

  // Readability returns; the bounded retry (`TASK_BUSY_RETRY_MS`) must now land.
  h.advance(2000);
  assert.equal(h.injected.length, 1, "the retry must deliver once the store is readable again");

  const ids = JSON.parse(readFileSync(shared, "utf8")).tasks.map((t) => t.id).sort();
  assert.ok(ids.includes("b2"), `B's owned intent must persist after recovery, got ${ids}`);
  assert.ok(ids.includes("a") && ids.includes("z"), `foreign records must be preserved across recovery, got ${ids}`);
});
