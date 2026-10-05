// Tests for the marker-declared session supervisor extension.
//
// The design under test has no classifier, no background-work liveness probe,
// and no interrupt grammar: the model DECLARES its status on the final line of
// its final assistant message, and the extension reads it synchronously. Every
// assertion below therefore drives the real factory through `pi.on` and reads
// the proposal or the OSC notification it produces.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
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
const { DEFAULT_MAX_CONTINUATIONS, HARD_MAX_CONTINUATIONS, resolveMaxContinuations } = mod;
const MAX_CONTINUATIONS = DEFAULT_MAX_CONTINUATIONS;

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
/** An assistant message that also made a tool call: metadata, not a declaration. */
const toolCall = (text) => ({
  role: "assistant",
  content: [
    { type: "text", text },
    { type: "tool_call", name: "bash", arguments: "{}" },
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
    "> Example:\n---\nSTATUS:DONE",
    "> # Next\nSTATUS:DONE",
  ];
  for (const text of container) {
    assert.equal(mod.declaredStatusOf(assistant(text)), "unknown", JSON.stringify(text));
  }
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

/** Arm with an explicit PI_MAX_CONTINUATIONS value. */
function armedWithBudget(budget) {
  return armed(mod, { PI_MAX_CONTINUATIONS: String(budget) });
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

test("a prior continue request from another handler is respected, not duplicated", async () => {
  const pi = armed();
  const result = await proposes(pi, [assistant(CONTINUE)], { continue: true });
  assert.equal(result, undefined, "must not add a second continuation request");
});

test("a spent allowance does not report exhaustion when another handler owns continuation", async () => {
  // Regression: the exhaustion branch previously ran before the ownership check,
  // so a boundary another handler had already marked `continue: true` was
  // misreported as a budget-limited stop even though continuation was owned
  // elsewhere. The stop cause must stay distinct.
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true, "the one slot is spent");
    const result = await proposes(pi, [assistant(CONTINUE)], { continue: true });
    assert.equal(result, undefined, "must not add a second continuation request");
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY],
      "another handler's continuation is reported as attention, not budget exhaustion",
    );
  } finally {
    capture.restore();
  }
});

test("a spent allowance still reports exhaustion when no other handler owns continuation", async () => {
  // Counterpart to the test above: with ownership NOT taken elsewhere, a spent
  // allowance on an otherwise proposable boundary is a genuine resource stop.
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true, "the one slot is spent");
    const result = await proposes(pi, [assistant(CONTINUE)]);
    assert.equal(result, undefined, "a spent allowance cannot propose");
    assert.match(
      capture.chunks.join(""),
      /budget exhausted/i,
      "an unowned spent allowance is still a resource-limited stop",
    );
  } finally {
    capture.restore();
  }
});

test("WAIT neither continues nor notifies", async () => {
  const pi = armed();
  const capture = captureStdout();
  try {
    assert.equal(await proposes(pi, [assistant(WAIT)]), undefined);
    assert.deepEqual(capture.chunks, [], "an established wake-up path is not a wait for the user");
    // The same settle seen through `agent_settled` must stay silent too.
    pi.emit("agent_settled", settleEvent(), { ...UI, sessionManager: sessionView([assistant(WAIT)]) });
    assert.deepEqual(capture.chunks, []);
  } finally {
    capture.restore();
  }
});

test("DONE, BLOCKED, and FAILED notify without continuing", async () => {
  for (const text of [DONE, BLOCKED, FAILED]) {
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

test("an unknown status notifies: 'notify when not sure'", async () => {
  const cases = [
    ["no marker at all", assistant("I did some work, but did not say what is next.")],
    ["a table", assistant("| a | b |\n|---|---|\n| 1 | 2 |")],
    ["empty text", assistant("")],
    ["thinking only", thinking("STATUS:DONE")],
    ["a tool result as the final message", { role: "toolResult", content: [{ type: "text", text: DONE }] }],
    ["a user message as the final message", user("what now?")],
    ["an ambiguous pair", assistant("STATUS:DONE\nSTATUS:CONTINUE x")],
    ["a malformed status", assistant("hn\nSTATUS:CONTINUE")],
  ];
  for (const [label, message] of cases) {
    const pi = armed();
    const capture = captureStdout();
    try {
      assert.equal(await proposes(pi, [message]), undefined, label);
      assert.deepEqual(capture.chunks, [OSC_NOTIFY], label);
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

test("WAIT from the session view suppresses settlement, as other paths do not have to", async () => {
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    // Notification events carry no context: the branch is read from the session
    // view, which is the only surface that survives the event boundary.
    pi.emit("agent_settled", settleEvent(), { ...UI, sessionManager: sessionView([assistant(WAIT)]) });
    assert.deepEqual(out.chunks, [], "a declared WAIT must not notify");
    // An absent or throwing view fails toward NOTIFYING, never to silence.
    pi.emit("input", {}, UI);
    pi.emit("agent_settled", settleEvent(), UI);
    assert.deepEqual(out.chunks, [OSC_NOTIFY], "an unavailable view must notify");
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
  // And a genuine final WAIT still suppresses, so the repair did not over-tighten.
  const { pi, out, restore } = registerViaDefault(undefined, { ZELLIJ_PANE_ID: "" });
  try {
    pi.emit("agent_settled", settleEvent(), {
      ...UI,
      sessionManager: sessionView([assistant(CONTINUE), assistant(WAIT)]),
    });
    assert.deepEqual(out.chunks, [], "the FINAL declaration still wins");
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

test("compaction does not replenish the continuation budget", async () => {
  // Context management is not a new user request: compaction must not refill
  // the allowance, or a session near the threshold could loop indefinitely by
  // compacting between each accepted proposal.
  const pi = armed();
  const capture = captureStdout();
  try {
    const first = await proposes(pi, [assistant(CONTINUE)]);
    assert.equal(first?.continue, true, "the declaration earned the first slot");

    // Interleave a compaction summary, then try again with budget remaining.
    const second = await proposes(pi, [
      user("[summary of earlier conversation]"),
      assistant(CONTINUE),
    ]);
    assert.equal(second?.continue, true, "the second slot is still available");

    // Budget is now spent. A further compaction must NOT re-arm it.
    const third = await proposes(pi, [
      user("[summary of earlier conversation]"),
      assistant(CONTINUE),
    ]);
    assert.equal(third, undefined, "compaction must not replenish the budget");
    assert.deepEqual(
      capture.chunks,
      [OSC_BUDGET_EXHAUSTED],
      "spent budget after compaction reports exhaustion, not a pending question",
    );
  } finally {
    capture.restore();
  }
});

test("a named CONTINUE step proposes exactly MAX_CONTINUATIONS times, then notifies", async () => {
  const pi = armed();
  const capture = captureStdout();
  try {
    const { accepted, branch } = await settleRounds(pi, [], { rounds: MAX_CONTINUATIONS });
    assert.equal(accepted, MAX_CONTINUATIONS, "the marker earned the full allowance");
    assert.equal(
      branch.filter((m) => m.customType === mod.BRIDGE_CUSTOM_TYPE).length,
      MAX_CONTINUATIONS,
      "one bridge per accepted proposal",
    );
    assert.deepEqual(capture.chunks, [], "both proposals were accepted, so no notification");

    // One more FRESH declaration on top of the committed bridges has no budget:
    // it must stop and report a resource-limited stop, not a pending question.
    const third = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([...branch, assistant(CONTINUE)]),
      UI,
    );
    assert.equal(third, undefined);
    assert.deepEqual(
      capture.chunks,
      [OSC_BUDGET_EXHAUSTED],
      "spent budget with unresolved work must report exhaustion",
    );
    assert.equal(
      await proposes(pi, [...branch, assistant(CONTINUE)]),
      undefined,
      "and stay silent afterwards",
    );
  } finally {
    capture.restore();
  }
});

test("a reload before any exhaustion reports attention, not budget exhaustion", async () => {
  // An unarmed session has no established budget, so a spent allowance is not
  // the reason it is stopping. It must not claim a resource limit it never had.
  const pi = makePi();
  mod.registerSessionSupervisor(pi, {});
  const capture = captureStdout();
  try {
    assert.equal(await proposes(pi, [assistant(CONTINUE)]), undefined);
    assert.deepEqual(capture.chunks, [OSC_NOTIFY], "unarmed settles as ordinary attention");
  } finally {
    capture.restore();
  }
});

test("PI_MAX_CONTINUATIONS raises the allowance to the configured budget", async () => {
  const pi = armedWithBudget(4);
  const capture = captureStdout();
  try {
    const { accepted, branch } = await settleRounds(pi, [], { rounds: 4 });
    assert.equal(accepted, 4, "the configured budget, not the default, was granted");
    assert.deepEqual(capture.chunks, [], "an unspent configured budget does not notify");
    const fifth = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([...branch, assistant(CONTINUE)]),
      UI,
    );
    assert.equal(fifth, undefined);
    assert.deepEqual(capture.chunks, [OSC_BUDGET_EXHAUSTED], "exhaustion reports the resource stop");
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
  assert.equal(resolveMaxContinuations(undefined), DEFAULT_MAX_CONTINUATIONS, "unset uses the default");
  assert.equal(resolveMaxContinuations("  "), DEFAULT_MAX_CONTINUATIONS, "blank uses the default");
  assert.equal(resolveMaxContinuations("0"), 0, "zero is a valid explicit value");
  assert.equal(resolveMaxContinuations("4"), 4);
  assert.equal(resolveMaxContinuations("64"), HARD_MAX_CONTINUATIONS, "the ceiling is accepted");

  const warned = [];
  const warn = (message) => warned.push(message);
  assert.equal(resolveMaxContinuations("2abc", warn), DEFAULT_MAX_CONTINUATIONS, "no parseInt");
  assert.equal(resolveMaxContinuations("-1", warn), DEFAULT_MAX_CONTINUATIONS);
  assert.equal(resolveMaxContinuations("1.5", warn), DEFAULT_MAX_CONTINUATIONS);
  assert.equal(resolveMaxContinuations("65", warn), DEFAULT_MAX_CONTINUATIONS, "above the ceiling");
  assert.equal(warned.length, 4, "every invalid value warned exactly once");
});

test("the budget is resolved once per registration and cannot be raised later", async () => {
  const env = { PI_MAX_CONTINUATIONS: "2" };
  const pi = makePi();
  mod.registerSessionSupervisor(pi, env);
  handshake(pi);
  const capture = captureStdout();
  try {
    // Mutating the environment after registration must not re-arm the ledger.
    env.PI_MAX_CONTINUATIONS = "64";
    const { accepted, branch } = await settleRounds(pi, [], { rounds: 3 });
    assert.equal(accepted, 2, "the registered budget still governs");
    const third = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([...branch, assistant(CONTINUE)]),
      UI,
    );
    assert.equal(third, undefined);
    assert.deepEqual(capture.chunks, [OSC_BUDGET_EXHAUSTED]);
  } finally {
    capture.restore();
  }
});

test("revoking an UNSPENT allowance reports attention, not budget exhaustion", async () => {
  // Regression: `resetForInput` and `handleBeforeAgentStart` zero the slots
  // without consuming them. Revoking a never-spent allowance must not later be
  // reported as an exhausted one, or steering/new input would make an unattended
  // session claim a resource limit it never reached.
  const pi = armedWithBudget(4);
  const capture = captureStdout();
  try {
    // Revoke via steering input WITHOUT spending any reservation.
    pi.emit(
      "input",
      { type: "input", text: "steer", source: "interactive", streamingBehavior: "steer" },
      tuiCtx(),
    );
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(CONTINUE)]),
      UI,
    );
    assert.equal(result, undefined, "a revoked allowance cannot propose");
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY],
      "an unspent revoked allowance is ordinary attention, never exhaustion",
    );
  } finally {
    capture.restore();
  }
});

test("a replacement handshake does not inherit the previous request's exhaustion", async () => {
  // Spend a real budget, then begin a NEW request whose handshake never
  // completes. The unfinished replacement must not inherit the old flag.
  const pi = armedWithBudget(1);
  const capture = captureStdout();
  try {
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true, "the one slot is spent");
    // An incomplete replacement handshake: input arrives, the agent starts, but
    // no user message is delivered.
    pi.emit("input", { type: "input", text: "again", source: "interactive" }, tuiCtx());
    pi.emit("before_agent_start", { type: "before_agent_start", prompt: "again" }, tuiCtx());
    const result = await handlerFor(pi, "agent_before_settle")(
      boundaryEvent([assistant(CONTINUE)]),
      UI,
    );
    assert.equal(result, undefined);
    assert.deepEqual(
      capture.chunks,
      [OSC_NOTIFY],
      "the unfinished replacement reports attention, not the previous exhaustion",
    );
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

test("the budget starts at zero until a genuine request is handshaked", async () => {
  const pi = makePi();
  mod.registerSessionSupervisor(pi, {});
  const capture = captureStdout();
  try {
    // No input at all: a bare settle must not propose.
    assert.equal(await proposes(pi, [assistant(CONTINUE)]), undefined);
    assert.deepEqual(capture.chunks, [OSC_NOTIFY], "and it must notify, since nothing is known");

    // Completing the handshake grants the budget.
    handshake(pi, { text: "please continue" });
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
  } finally {
    capture.restore();
  }
});

test("only a delivered genuine user message completes the handshake", async () => {
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
    assert.equal(await proposes(pi, [assistant(CONTINUE)]), undefined, label);
  }
});

const tuiCtx = () => ({ ...UI, isIdle: () => true });

test("our own bridge continuation does not re-arm the budget", async () => {
  const pi = armed();
  const exhausted = await settleRounds(pi, []);
  assert.equal(exhausted.accepted, MAX_CONTINUATIONS);
  assert.equal(await proposes(pi, [assistant(CONTINUE)]), undefined, "the allowance is spent");

  // The bridge is projected as a `custom` message, so even a `message_start`
  // naming `custom` must not replenish the ledger.
  pi.emit("message_start", { message: { role: "custom", customType: mod.BRIDGE_CUSTOM_TYPE } }, tuiCtx());
  assert.equal(await proposes(pi, [assistant(CONTINUE)]), undefined, "a custom message never re-arms");

  // A genuine NEW request does replenish it.
  handshake(pi, { text: "now also add d.txt" });
  assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true, "a genuine request re-arms");
});

test("session change and tree navigation disarm an existing budget", async () => {
  for (const event of ["session_start", "session_tree"]) {
    const pi = armed();
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);

    // Re-arm, then disarm through the lifecycle event.
    handshake(pi, { text: "again" });
    assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
    pi.emit(event, { type: event }, UI);
    assert.equal(await proposes(pi, [assistant(CONTINUE)]), undefined, `${event} must disarm`);
  }
});

test("a spent budget stays silent instead of vetoing another handler", async () => {
  const pi = armed();
  await settleRounds(pi, []);
  // Returning `undefined` leaves another handler's `continue` untouched;
  // returning `continue: false` would cancel unrelated work.
  const result = await proposes(pi, [assistant(CONTINUE)]);
  assert.equal(result, undefined);
});

test("a vetoed or overwritten proposal still charges its slot", async () => {
  const pi = armed();
  // The proposal is made but never committed into the branch, exactly as a
  // last-writer-wins veto leaves it: the ledger is local, so it must not refund.
  assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
  assert.equal((await proposes(pi, [assistant(CONTINUE)]))?.continue, true);
  assert.equal(await proposes(pi, [assistant(CONTINUE)]), undefined);
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
// Small helpers
// ---------------------------------------------------------------------------