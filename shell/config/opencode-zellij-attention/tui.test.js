import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readlink, rm, symlink, writeFile, lstat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import tuiModule from "./tui.js";
import indexModule from "./index.js";

const source = await readFile(new URL("./tui.js", import.meta.url), "utf8");
const cliConfigSource = await readFile(new URL("../opencode-cli.json", import.meta.url), "utf8");
const opencodeConfigSource = await readFile(new URL("../opencode.json", import.meta.url), "utf8");
const configScriptPath = new URL("../../config.sh", import.meta.url);

function loadTui(spawn) {
    const body = source
        .replace(/^import .*$/gm, "")
        .replace("export default", "return");
    return new Function("spawn", "appendFileSync", body)(spawn, () => {});
}

test("real module imports expose the plain OpenCode TUI contract and index re-export", () => {
    assert.equal(tuiModule.id, "zellij-attention");
    assert.equal(typeof tuiModule.setup, "function");
    assert.equal(indexModule, tuiModule);
    assert.doesNotMatch(source, /@opencode-ai\/plugin\/tui/);
    assert.doesNotMatch(source, /Plugin\.define/);
});

function harness() {
    const listeners = new Map();
    const timers = new Map();
    let nextTimer = 1;
    let now = 0;
    const realSetTimeout = globalThis.setTimeout;
    const realClearTimeout = globalThis.clearTimeout;
    const hadPaneID = Object.hasOwn(process.env, "ZELLIJ_PANE_ID");
    const realPaneID = process.env.ZELLIJ_PANE_ID;
    const flags = [];
    const spawn = (command, args, options) => {
        flags.push({ command, args, options });
        return { on: () => {}, unref: () => {} };
    };
    globalThis.setTimeout = (callback, delay) => {
        const id = nextTimer++;
        timers.set(id, { callback, delay, due: now + delay });
        return id;
    };
    globalThis.clearTimeout = (id) => timers.delete(id);
    const on = (name, callback) => {
        const callbacks = listeners.get(name) ?? [];
        callbacks.push(callback);
        listeners.set(name, callbacks);
        return () => listeners.set(name, callbacks.filter((item) => item !== callback));
    };
    const emit = (name, data) => (listeners.get(name) ?? []).forEach((callback) => callback({ data }));
    const runNext = () => {
        const next = [...timers.entries()].sort((a, b) => a[1].due - b[1].due)[0];
        if (!next) return false;
        const [id, timer] = next;
        timers.delete(id);
        now = Math.max(now, timer.due);
        timer.callback();
        return true;
    };
    const advanceBy = (milliseconds) => {
        const target = now + milliseconds;
        while (true) {
            const next = [...timers.entries()]
                .filter(([, timer]) => timer.due <= target)
                .sort((a, b) => a[1].due - b[1].due)[0];
            if (!next) break;
            const [id, timer] = next;
            timers.delete(id);
            now = Math.max(now, timer.due);
            timer.callback();
        }
        now = target;
    };
    const sessions = new Map([
        ["A", { parentID: undefined }], ["B", { parentID: undefined }],
        ["child", { parentID: "A" }],
        ["grandchild", { parentID: "child" }],
    ]);
    process.env.ZELLIJ_PANE_ID = "test-pane";
    const tui = loadTui(spawn);
    const makeContext = (sessionID) => {
        const attention = [];
        attention.notify = (notification) => {
            attention.push(notification);
            const { message } = notification;
            context.messages.push(message);
        };
        const context = {
            data: { on, session: { get: (id) => sessions.get(id) } },
            attention,
            messages: [],
        };
        context.routeState = { type: "session", sessionID };
        context.ui = { router: { current: () => context.routeState } };
        context.cleanup = tui.setup(context);
        return context;
    };
    const contexts = { A: makeContext("A"), B: makeContext("B") };
    return {
        contexts, emit, advanceBy, runNext, timers, flags, sessions, listeners,
        restore: () => {
            globalThis.setTimeout = realSetTimeout;
            globalThis.clearTimeout = realClearTimeout;
            if (hadPaneID) process.env.ZELLIJ_PANE_ID = realPaneID;
            else delete process.env.ZELLIJ_PANE_ID;
        },
    };
}

test("attention events are scoped to the dynamically displayed root session", () => {
    const h = harness();
    try {
        h.emit("permission.asked", { sessionID: "A" });
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input"]);
        assert.deepEqual(h.contexts.A.attention.slice(), [{
            message: "Waiting for your input",
            sound: { name: "default", when: "always" },
        }]);
        assert.deepEqual(h.contexts.B.messages, []);

        h.emit("permission.asked", { sessionID: "B" });
        assert.deepEqual(h.contexts.B.messages, ["Waiting for your input"]);

        h.contexts.A.routeState = { type: "session", sessionID: "B" };
        h.emit("session.execution.interrupted", { sessionID: "B" });
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input", "Agent stopped"]);

        for (const route of [
            { name: "home", params: { sessionID: "A" } },
            { name: "session", params: {} },
            { name: "session", params: { sessionID: 42 } },
        ]) {
            h.contexts.A.routeState = route.type === "session"
                ? route : { type: route.name === "session" ? "session" : route.name, sessionID: route.params?.sessionID };
            h.emit("permission.asked", { sessionID: "A" });
        }
        h.contexts.A.routeState = { type: "session", sessionID: "A" };
        h.emit("permission.asked", { sessionID: "A" });
        h.emit("permission.asked", { sessionID: "child" });
        h.emit("permission.asked", {});
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input", "Agent stopped"]);

        h.emit("session.execution.started", { sessionID: "A" });
        h.emit("form.created", { form: { sessionID: "A" } });
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input", "Agent stopped", "Waiting for your input"]);
        h.emit("form.created", { sessionID: "A" });
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input", "Agent stopped", "Waiting for your input"]);
    } finally { h.restore(); }
});

test("success debounce and started events cannot cross session state", () => {
    const h = harness();
    const a = h.contexts.A;
    const b = h.contexts.B;
    try {
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        h.emit("session.execution.started", { sessionID: "B" });
        a.routeState = { type: "session", sessionID: "A" };
        h.advanceBy(3000);
        assert.equal(a.attention.length, 1);
        assert.deepEqual(a.attention[0], {
            message: "Waiting for your input",
            sound: { name: "default", when: "always" },
        });
        assert.equal(b.attention.length, 0);

        h.emit("session.execution.started", { sessionID: "A" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        a.routeState = { type: "home" };
        h.advanceBy(3000);
        assert.equal(a.attention.length, 1);
        assert.equal(b.attention.length, 0);
    } finally { h.restore(); }
});

test("malformed events cannot disturb a pending root-session debounce", () => {
    const h = harness();
    const a = h.contexts.A;
    const b = h.contexts.B;
    try {
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        const [timerID, originalTimer] = h.timers.entries().next().value;
        const malformedEvents = [
            ["permission.asked", {}],
            ["session.execution.started", {}],
            ["session.execution.succeeded", {}],
            ["session.execution.interrupted", {}],
            ["session.execution.failed", {}],
            ["form.created", {}],
            ["form.created", { form: {} }],
            ["form.created", { form: { sessionID: 42 } }],
            ["form.created", { sessionID: "A" }],
        ];
        for (const [name, data] of malformedEvents) {
            h.emit(name, data);
            assert.equal(h.timers.size, 1);
            assert.equal(h.timers.get(timerID), originalTimer);
            assert.equal(a.attention.length, 0);
            assert.equal(b.attention.length, 0);
            assert.equal(h.flags.length, 0);
        }
    } finally { h.restore(); }
});

test("matching child-session events do not notify or flag its root", () => {
    const h = harness();
    const a = h.contexts.A;
    const b = h.contexts.B;
    try {
        a.routeState = { type: "session", sessionID: "child" };
        h.emit("permission.asked", { sessionID: "child" });
        h.emit("session.execution.succeeded", { sessionID: "child" });
        assert.equal(h.timers.size, 0);
        assert.equal(a.attention.length, 0);
        assert.equal(b.attention.length, 0);
        assert.equal(h.flags.length, 0);
    } finally { h.restore(); }
});

test("an active child suppresses the root debounce until the child succeeds", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        h.emit("session.execution.started", { sessionID: "child" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 0);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);

        h.emit("session.execution.succeeded", { sessionID: "child" });
        assert.equal(h.timers.size, 1);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);
        h.advanceBy(3000);
        assert.equal(a.attention.length, 1);
        assert.equal(h.flags.length, 1);
        assert.equal(h.contexts.B.attention.length, 0);
    } finally { h.restore(); }
});

test("child direct events stay suppressed across all execution outcomes", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        for (const name of [
            "permission.asked", "form.created", "session.execution.interrupted",
            "session.execution.failed", "session.execution.succeeded",
        ]) {
            h.emit(name, name === "form.created"
                ? { form: { sessionID: "child" } }
                : { sessionID: "child" });
        }
        assert.equal(h.timers.size, 0);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);
    } finally { h.restore(); }
});

test("nested grandchild completion releases the root only after the lineage is idle", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        h.emit("session.execution.started", { sessionID: "grandchild" });
        h.emit("session.execution.started", { sessionID: "child" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 0);
        h.emit("session.execution.succeeded", { sessionID: "grandchild" });
        assert.equal(h.timers.size, 0);
        h.emit("session.execution.succeeded", { sessionID: "child" });
        assert.equal(h.timers.size, 1);
        h.advanceBy(3000);
        assert.equal(a.attention.length, 1);
        assert.equal(h.flags.length, 1);
    } finally { h.restore(); }
});

test("unknown, orphan, malformed, and cyclic ancestry cannot disturb a root timer", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        h.emit("session.execution.succeeded", { sessionID: "A" });
        const [timerID, timer] = h.timers.entries().next().value;
        h.sessions.set("orphan", { parentID: "missing" });
        h.sessions.set("cycle-a", { parentID: "cycle-b" });
        h.sessions.set("cycle-b", { parentID: "cycle-a" });
        for (const data of [
            { sessionID: "unknown" }, { sessionID: "orphan" },
            { sessionID: "cycle-a" }, {}, { sessionID: 42 },
        ]) {
            h.emit("session.execution.succeeded", data);
            assert.equal(h.timers.size, 1);
            assert.equal(h.timers.get(timerID), timer);
            assert.equal(a.attention.length, 0);
            assert.equal(h.flags.length, 0);
        }
    } finally { h.restore(); }
});

test("root restart cancels a delayed post-child notification", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        h.emit("session.execution.started", { sessionID: "child" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        h.emit("session.execution.succeeded", { sessionID: "child" });
        assert.equal(h.timers.size, 1);
        h.emit("session.execution.started", { sessionID: "A" });
        assert.equal(h.timers.size, 0);
        h.advanceBy(3000);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);
    } finally { h.restore(); }
});

test("cleanup clears timers and listeners and blocks later side effects", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        const listenerCount = [...h.listeners.values()].reduce((count, items) => count + items.length, 0);
        assert.ok(listenerCount > 0);
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        a.cleanup();
        assert.equal(h.timers.size, 0);
        const remaining = [...h.listeners.values()].reduce((count, items) => count + items.length, 0);
        assert.equal(remaining, listenerCount / 2);
        h.emit("permission.asked", { sessionID: "A" });
        h.advanceBy(3000);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);
    } finally { h.restore(); }
});

test("legacy route is ignored by the beta router contract", () => {
    const h = harness();
    h.contexts.A.ui = { router: {} };
    h.contexts.A.route = { current: { name: "session", params: { sessionID: "A" } } };
    try {
        h.emit("permission.asked", { sessionID: "A" });
        assert.deepEqual(h.contexts.A.messages, []);
        assert.equal(h.flags.length, 0);
    } finally { h.restore(); }
});

test("absent and noncallable primary routers do not use the legacy session route", () => {
    for (const primary of ["absent", "noncallable"]) {
        const h = harness();
        const a = h.contexts.A;
        const b = h.contexts.B;
        try {
            a.ui = { router: primary === "absent" ? {} : { current: null } };
            a.route = { current: { name: "session", params: { sessionID: "A" } } };
            h.emit("permission.asked", { sessionID: "A" });
            assert.deepEqual(a.messages, []);
            assert.deepEqual(b.messages, []);
            assert.equal(h.flags.length, 0);
        } finally { h.restore(); }
    }
});

test("throwing primary router does not use the legacy route or leak", () => {
    const h = harness();
    const a = h.contexts.A;
    const b = h.contexts.B;
    try {
        a.ui = { router: { current: () => { throw new Error("router unavailable"); } } };
        a.route = { current: { name: "session", params: { sessionID: "A" } } };
        assert.doesNotThrow(() => h.emit("permission.asked", { sessionID: "A" }));
        assert.deepEqual(a.messages, []);
        assert.deepEqual(b.messages, []);
        assert.equal(h.timers.size, 0);
        assert.equal(h.flags.length, 0);
    } finally { h.restore(); }
});

test("a callable primary route never falls back to a valid legacy route", () => {
    for (const route of [{ type: "home" }, { type: "session", sessionID: 42 }]) {
        const h = harness();
        const a = h.contexts.A;
        try {
            a.route = { current: { name: "session", params: { sessionID: "A" } } };
            a.ui = { router: { current: () => route } };
            h.emit("session.execution.succeeded", { sessionID: "A" });
            assert.equal(h.timers.size, 0);
            assert.deepEqual(a.messages, []);
            assert.equal(h.flags.length, 0);
        } finally { h.restore(); }
    }
});

test("primary router current preserves its receiver", () => {
    const h = harness();
    const a = h.contexts.A;
    const router = { calls: 0, current() {
        this.calls += 1;
        assert.equal(this, router);
        return { type: "session", sessionID: "A" };
    } };
    try {
        a.ui = { router };
        h.emit("permission.asked", { sessionID: "A" });
        assert.equal(router.calls, 1);
        assert.deepEqual(a.messages, ["Waiting for your input"]);
        assert.equal(h.flags.length, 1);
    } finally { h.restore(); }
});

test("completion after route appears can notify, while another tab cannot reset it", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        a.routeState = { type: "home" };
        h.emit("session.execution.started", { sessionID: "A" });
        a.routeState = { type: "session", sessionID: "A" };
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        h.contexts.B.routeState = { type: "session", sessionID: "B" };
        h.emit("session.execution.started", { sessionID: "B" });
        h.advanceBy(3000);
        assert.deepEqual(a.messages, ["Waiting for your input"]);
    } finally { h.restore(); }
});

test("successful completion is debounced and notifies and flags only once per cycle", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        h.emit("session.execution.succeeded", { sessionID: "A" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);

        h.advanceBy(3000);
        assert.equal(h.timers.size, 0);
        assert.equal(h.flags.length, 1);
        assert.deepEqual(a.attention.slice(), [{
            message: "Waiting for your input",
            sound: { name: "default", when: "always" },
        }]);

        h.emit("session.execution.succeeded", { sessionID: "A" });
        h.emit("session.execution.interrupted", { sessionID: "A" });
        h.emit("session.execution.failed", { sessionID: "A" });
        assert.equal(h.timers.size, 0);
        assert.equal(h.flags.length, 1);
        assert.equal(a.attention.length, 1);
    } finally { h.restore(); }
});

test("V2 config disables the built-in notification plugin without changing attention settings", async () => {
    const config = JSON.parse(cliConfigSource);
    assert.deepEqual(config.plugins, ["-opencode.notifications", "./plugins/zellij-attention"]);
    assert.deepEqual(config.attention, {
        enabled: true,
        notifications: true,
        sound: true,
        volume: 0.4,
        sound_pack: "opencode.default",
    });
    assert.deepEqual(config.tabs, { enabled: false });
    assert.deepEqual(config.session, { sidebar: "hide" });
});

test("OpenCode config omits unsupported legacy settings and preserves supported settings", () => {
    const config = JSON.parse(opencodeConfigSource);
    assert.equal(Object.hasOwn(config.compaction, "prune"), false);
    assert.equal(Object.hasOwn(config, "logLevel"), false);

    const models = config.provider.litellm.models;
    for (const model of Object.values(models)) {
        assert.equal(Object.hasOwn(model, "reasoning"), false);
    }
    assert.deepEqual(config.compaction, {
        auto: true,
        keep: { tokens: 50000 },
        buffer: 20000,
    });
    assert.deepEqual(Object.keys(models), [
        "DeepSeek-V4-Flash",
        "DeepSeek-V4-Pro",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
    ]);
    assert.deepEqual(Object.keys(models["DeepSeek-V4-Flash"].variants), ["max"]);
    for (const model of ["gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"]) {
        assert.deepEqual(Object.keys(models[model].variants), ["none", "low", "medium", "high", "xhigh", "max"]);
    }
    assert.deepEqual(config.agents, {
        general: { disabled: true },
        explore: { disabled: true },
    });
    assert.equal(config.default_agent, "orchestrator");
    assert.equal(config.share, "manual");
});

const migrationCases = [
    ["exact matching symlink", "exact"],
    ["regular file", "regular"],
    ["real directory with sentinel", "directory"],
    ["different symlink", "different-link"],
    ["broken symlink", "broken-link"],
];

async function makeConfigFixture() {
    const root = await mkdtemp(join(tmpdir(), "m-config-test-"));
    const repoSource = join(root, "repo", "shell", "config", "opencode-zellij-attention");
    const legacyRepoSource = join(root, "repo", "shell", "config", "opencode2-zellij-attention");
    await mkdir(join(root, "repo", "shell", "config"), { recursive: true });
    await symlink(new URL(".", import.meta.url), repoSource);
    await symlink(new URL(".", import.meta.url), legacyRepoSource);
    return { root, home: join(root, "home"), repo: join(root, "repo") };
}

function runConfig(fixture, script, extraEnv = {}) {
    const result = spawnSync("/bin/zsh", ["-f", "-c", script, "--", configScriptPath.pathname], {
        env: { HOME: fixture.home, DIR: fixture.repo, PATH: "/usr/bin:/bin", LC_ALL: "C", ...extraEnv },
        encoding: "utf8",
    });
    assert.equal(result.status, 0, result.stderr);
}

async function assertLink(path, expected) {
    assert.equal((await lstat(path)).isSymbolicLink(), true);
    assert.equal(await readlink(path), expected);
}

test("config install migrates only the exact legacy plugin link", async () => {
    for (const [name, kind] of migrationCases) {
        const fixture = await makeConfigFixture();
        const legacy = join(fixture.home, ".config/opencode2/opencode/plugins/zellij-attention");
        const target = join(fixture.home, ".config/opencode/plugins/zellij-attention");
        try {
            await mkdir(join(fixture.home, ".config/opencode2/opencode/plugins"), { recursive: true });
            if (kind === "regular") await writeFile(legacy, "preserve");
            if (kind === "directory") {
                await mkdir(legacy);
                await writeFile(join(legacy, "sentinel"), "preserve");
            }
            if (kind === "different-link") {
                const other = join(fixture.root, "other");
                await writeFile(other, "other");
                await symlink(other, legacy);
            }
            if (kind === "broken-link") await symlink(join(fixture.root, "missing"), legacy);
            if (kind === "exact") await symlink(`${fixture.repo}/shell/config/opencode2-zellij-attention`, legacy);
            runConfig(fixture, 'source "$1"');
            assert.equal(name.length > 0, true);
            await assertLink(target, `${fixture.repo}/shell/config/opencode-zellij-attention`);
            if (kind === "exact") await assert.rejects(lstat(legacy));
            if (kind === "regular") assert.equal(await (await readFile(legacy, "utf8")), "preserve");
            if (kind === "directory") assert.equal(await readFile(join(legacy, "sentinel"), "utf8"), "preserve");
            if (kind === "different-link") assert.equal(await readlink(legacy), join(fixture.root, "other"));
            if (kind === "broken-link") assert.equal(await readlink(legacy), join(fixture.root, "missing"));
        } finally { await rm(fixture.root, { recursive: true, force: true }); }
    }
});

test("config uninstall removes managed links and preserves unrelated legacy objects", async () => {
    for (const [name, kind] of migrationCases) {
        const fixture = await makeConfigFixture();
        const legacy = join(fixture.home, ".config/opencode2/opencode/plugins/zellij-attention");
        const target = join(fixture.home, ".config/opencode/plugins/zellij-attention");
        try {
            runConfig(fixture, `source "$1"
mkdir -p "$HOME/.config/opencode2/opencode/plugins"
case "$CASE" in
  exact) ln -s "$DIR/shell/config/opencode2-zellij-attention" "$HOME/.config/opencode2/opencode/plugins/zellij-attention" ;;
  regular) printf preserve > "$HOME/.config/opencode2/opencode/plugins/zellij-attention" ;;
  directory) mkdir "$HOME/.config/opencode2/opencode/plugins/zellij-attention"; printf preserve > "$HOME/.config/opencode2/opencode/plugins/zellij-attention/sentinel" ;;
  different-link) printf other > "$HOME/other"; ln -s "$HOME/other" "$HOME/.config/opencode2/opencode/plugins/zellij-attention" ;;
  broken-link) ln -s "$HOME/missing" "$HOME/.config/opencode2/opencode/plugins/zellij-attention" ;;
esac
_m_config_uninstall`, { CASE: kind });
            assert.equal(name.length > 0, true);
            await assert.rejects(lstat(target));
            if (kind === "exact") await assert.rejects(lstat(legacy));
            if (kind === "regular") { assert.equal((await lstat(legacy)).isFile(), true, name); assert.equal(await readFile(legacy, "utf8"), "preserve", name); }
            if (kind === "directory") assert.equal(await readFile(join(legacy, "sentinel"), "utf8"), "preserve", name);
            if (kind === "different-link") assert.equal(await readlink(legacy), join(fixture.home, "other"), name);
            if (kind === "broken-link") assert.equal(await readlink(legacy), join(fixture.home, "missing"), name);
        } finally { await rm(fixture.root, { recursive: true, force: true }); }
    }
});

test("completed roots give unknown started sessions a mandatory two-phase liveness path", () => {
    const h = harness();
    try {
        h.emit("session.execution.started", { sessionID: "unknown" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        h.advanceBy(3000);
        assert.equal(h.timers.size, 1, "grace must not drain the newly scheduled debounce");
        h.advanceBy(3000);
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input"]);
    } finally { h.restore(); }
});

test("exact unknown terminal outcomes settle provisionals without immediate notifications", () => {
    for (const outcome of ["succeeded", "interrupted", "failed"]) {
        const h = harness();
        try {
            h.emit("session.execution.started", { sessionID: "unknown" });
            h.emit("session.execution.succeeded", { sessionID: "A" });
            h.emit(`session.execution.${outcome}`, { sessionID: "unknown" });
            assert.deepEqual(h.contexts.A.messages, [], outcome);
            h.advanceBy(3000);
            assert.deepEqual(h.contexts.A.messages, ["Waiting for your input"], outcome);
        } finally { h.restore(); }
    }
});

test("unknown lineage cache reconciles related sessions and stays active until terminal", () => {
    const h = harness();
    try {
        h.emit("session.execution.started", { sessionID: "cached" });
        h.sessions.set("cached", { parentID: "A" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        h.advanceBy(3000);
        assert.equal(h.timers.size, 0);
        h.advanceBy(3000);
        assert.deepEqual(h.contexts.A.messages, []);
        h.emit("session.execution.succeeded", { sessionID: "cached" });
        h.advanceBy(3000);
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input"]);
    } finally { h.restore(); }
});

test("unknown lineage cache reconciles unrelated sessions and releases them", () => {
    const h = harness();
    try {
        h.emit("session.execution.started", { sessionID: "other" });
        h.sessions.set("other", { parentID: "B" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        h.advanceBy(3000);
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input"]);
    } finally { h.restore(); }
});

test("multiple provisional IDs settle independently and root restart rejects stale terminals", () => {
    const h = harness();
    try {
        h.emit("session.execution.started", { sessionID: "one" });
        h.emit("session.execution.started", { sessionID: "two" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        h.emit("session.execution.succeeded", { sessionID: "one" });
        h.emit("session.execution.started", { sessionID: "A" });
        h.emit("session.execution.failed", { sessionID: "two" });
        assert.deepEqual(h.contexts.A.messages, []);
        h.emit("session.execution.succeeded", { sessionID: "A" });
        h.advanceBy(3000);
        h.advanceBy(3000);
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input"]);
    } finally { h.restore(); }
});

test("unknown start replaces the root debounce with grace and then a fresh debounce", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        h.emit("session.execution.succeeded", { sessionID: "A" });
        const [normalTimerID, normalTimer] = h.timers.entries().next().value;
        assert.equal(normalTimer.delay, 3000);

        h.emit("session.execution.started", { sessionID: "unknown" });
        assert.equal(h.timers.size, 1);
        const [graceTimerID, graceTimer] = h.timers.entries().next().value;
        assert.notEqual(graceTimerID, normalTimerID);
        assert.notEqual(graceTimer, normalTimer);
        assert.equal(graceTimer.delay, 3000);

        h.advanceBy(2999);
        assert.equal(h.timers.size, 1);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);
        h.advanceBy(1);
        assert.equal(h.timers.size, 1);
        const [freshTimerID, freshTimer] = h.timers.entries().next().value;
        assert.notEqual(freshTimerID, graceTimerID);
        assert.notEqual(freshTimer, graceTimer);
        assert.equal(freshTimer.delay, 3000);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);

        h.advanceBy(2999);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);
        h.advanceBy(1);
        assert.equal(a.attention.length, 1);
        assert.equal(h.flags.length, 1);
        assert.deepEqual(a.messages, ["Waiting for your input"]);
    } finally { h.restore(); }
});

test("multiple unresolved IDs keep grace pending until the last terminal outcome", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        h.emit("session.execution.started", { sessionID: "one" });
        h.emit("session.execution.started", { sessionID: "two" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        const [graceTimerID, graceTimer] = h.timers.entries().next().value;

        h.emit("session.execution.succeeded", { sessionID: "one" });
        assert.equal(h.timers.size, 1);
        assert.equal(h.timers.get(graceTimerID), graceTimer);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);

        h.advanceBy(3000);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);
        assert.equal(h.timers.size, 1);
        const [normalTimerID, normalTimer] = h.timers.entries().next().value;
        assert.notEqual(normalTimerID, graceTimerID);
        assert.equal(normalTimer.delay, 3000);

        h.advanceBy(2999);
        assert.equal(a.attention.length, 0);
        assert.equal(h.flags.length, 0);
        h.advanceBy(1);
        assert.equal(a.attention.length, 1);
        assert.equal(h.flags.length, 1);
        assert.deepEqual(a.messages, ["Waiting for your input"]);
    } finally { h.restore(); }
});

test("cleanup blocks stale unknown grace callbacks and terminal outcomes", () => {
    const h = harness();
    const a = h.contexts.A;
    try {
        h.emit("session.execution.started", { sessionID: "unknown" });
        h.emit("session.execution.succeeded", { sessionID: "A" });
        assert.equal(h.timers.size, 1);
        const graceCallback = h.timers.values().next().value.callback;
        const listenerCount = [...h.listeners.values()].reduce((count, items) => count + items.length, 0);

        a.cleanup();
        assert.equal(h.timers.size, 0);
        const remaining = [...h.listeners.values()].reduce((count, items) => count + items.length, 0);
        assert.equal(remaining, listenerCount / 2);
        assert.equal(h.contexts.B.attention.length, 0);

        graceCallback();
        for (const outcome of ["succeeded", "interrupted", "failed"]) {
            h.emit(`session.execution.${outcome}`, { sessionID: "unknown" });
        }
        h.advanceBy(6000);
        assert.equal(h.timers.size, 0);
        assert.equal(a.attention.length, 0);
        assert.equal(a.messages.length, 0);
        assert.equal(h.flags.length, 0);
    } finally { h.restore(); }
});
