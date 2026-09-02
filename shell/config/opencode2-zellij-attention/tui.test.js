import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const source = await readFile(new URL("./tui.js", import.meta.url), "utf8");

function loadPlugin(spawn) {
    const body = source
        .replace(/^import .*$/gm, "")
        .replace("export default Plugin.define", "return Plugin.define");
    return new Function("Plugin", "spawn", "appendFileSync", body)({
        define: (definition) => definition,
    }, spawn, () => {});
}

function harness({ fallback = false } = {}) {
    const listeners = new Map();
    const timers = new Map();
    let nextTimer = 1;
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
        timers.set(id, { callback, delay });
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
    const runTimers = () => {
        for (const [id, timer] of timers) {
            timers.delete(id);
            timer.callback();
        }
    };
    const sessions = new Map([
        ["A", { parentID: undefined }], ["B", { parentID: undefined }],
        ["child", { parentID: "A" }],
    ]);
    process.env.ZELLIJ_PANE_ID = "test-pane";
    const plugin = loadPlugin(spawn);
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
        if (fallback) {
            context.route = { current: { name: "session", params: { sessionID } } };
        } else {
            context.routeState = { type: "session", sessionID };
            context.ui = { router: { current: () => context.routeState } };
        }
        context.cleanup = plugin.setup(context);
        return context;
    };
    const contexts = { A: makeContext("A"), B: makeContext("B") };
    return {
        contexts, emit, runTimers, timers, flags,
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
        h.runTimers();
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
        h.runTimers();
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

test("legacy route is used only when the primary router is unavailable", () => {
    const h = harness({ fallback: true });
    try {
        h.emit("permission.asked", { sessionID: "A" });
        assert.deepEqual(h.contexts.A.messages, ["Waiting for your input"]);
    } finally { h.restore(); }
});

test("absent and noncallable primary routers use the legacy session route", () => {
    for (const primary of ["absent", "noncallable"]) {
        const h = harness({ fallback: true });
        const a = h.contexts.A;
        const b = h.contexts.B;
        try {
            a.ui = { router: primary === "absent" ? {} : { current: null } };
            h.emit("permission.asked", { sessionID: "A" });
            assert.deepEqual(a.messages, ["Waiting for your input"]);
            assert.deepEqual(b.messages, []);
            assert.equal(h.flags.length, 1);
            assert.equal(h.flags[0].args[2], "zellij-attention::waiting::test-pane");
        } finally { h.restore(); }
    }
});

test("throwing primary router uses the legacy route without leaking", () => {
    const h = harness({ fallback: true });
    const a = h.contexts.A;
    const b = h.contexts.B;
    try {
        a.ui = { router: { current: () => { throw new Error("router unavailable"); } } };
        assert.doesNotThrow(() => h.emit("permission.asked", { sessionID: "A" }));
        assert.deepEqual(a.messages, ["Waiting for your input"]);
        assert.deepEqual(b.messages, []);
        assert.equal(h.timers.size, 0);
        assert.equal(h.flags.length, 1);
    } finally { h.restore(); }
});

test("a callable primary route never falls back to a valid legacy route", () => {
    for (const route of [{ type: "home" }, { type: "session", sessionID: 42 }]) {
        const h = harness({ fallback: true });
        const a = h.contexts.A;
        try {
            a.ui = { router: { current: () => route } };
            h.emit("session.execution.succeeded", { sessionID: "A" });
            assert.equal(h.timers.size, 0);
            assert.deepEqual(a.messages, []);
            assert.equal(h.flags.length, 0);
        } finally { h.restore(); }
    }
});

test("primary router current preserves its receiver", () => {
    const h = harness({ fallback: true });
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
        h.runTimers();
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

        h.runTimers();
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
    const config = JSON.parse(await readFile(new URL("../opencode2-cli.json", import.meta.url), "utf8"));
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
