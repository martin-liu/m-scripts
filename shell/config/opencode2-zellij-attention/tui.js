import { spawn } from "node:child_process";
import { appendFileSync } from "node:fs";
import { Plugin } from "@opencode-ai/plugin/tui";

const EVENT_LOG = "/tmp/opencode2-attention-events.log";
function record(debug, kind, fields = {}) {
    if (!debug) return;
    try { appendFileSync(EVENT_LOG, `${JSON.stringify({ t: Date.now(), kind, ...fields })}\n`); } catch (_) {}
}
function sessionIdentifier(data) {
    if (!data || typeof data !== "object") return null;
    return typeof data.sessionID === "string" && data.sessionID ? data.sessionID : null;
}
function formSessionIdentifier(data) {
    if (!data || typeof data !== "object") return null;
    const form = data.form;
    if (!form || typeof form !== "object") return null;
    return typeof form.sessionID === "string" && form.sessionID ? form.sessionID : null;
}

export default Plugin.define({
    id: "zellij-attention",
    setup(ctx) {
        const debug = process.env.OPENCODE_ATTENTION_DEBUG === "1";
        const paneId = process.env.ZELLIJ_PANE_ID;
        const listeners = [];
        const states = new Map();
        let closed = false;
        record(debug, "setup", { pane: Boolean(paneId) });
        const data = ctx?.data;
        const sessionApi = data?.session;
        const canListen = typeof data?.on === "function";
        const canFindSession = typeof sessionApi?.get === "function";
        const canNotify = typeof ctx?.attention?.notify === "function";
        if (!canListen || !canFindSession || !canNotify) {
            record(debug, "capability", { on: canListen, session: canFindSession, attention: canNotify });
            return () => {};
        }
        const displayedSession = () => {
            let route;
            let source = "none";
            const current = ctx?.ui?.router?.current;
            if (typeof current === "function") {
                try {
                    // Keep the router as the receiver: documented APIs may rely on it.
                    route = ctx.ui.router.current();
                    source = "primary";
                } catch (_) {
                    route = undefined;
                }
            }
            if (source === "none" && ctx?.route && Object.hasOwn(ctx.route, "current")) {
                try {
                    const legacy = ctx?.route?.current;
                    if (typeof ctx?.route?.current === "function") route = ctx.route.current();
                    else route = legacy;
                    source = "fallback";
                } catch (_) { route = undefined; }
            }
            const sessionID = route?.type === "session"
                ? route.sessionID
                : source === "fallback" && route?.name === "session"
                    ? route.params?.sessionID
                    : null;
            return {
                source,
                sessionID: typeof sessionID === "string" && sessionID ? sessionID : null,
            };
        };
        const stateFor = (sessionID) => {
            let state = states.get(sessionID);
            if (!state) {
                state = { timer: null, notified: false };
                states.set(sessionID, state);
            }
            return state;
        };
        const clearTimer = (sessionID) => {
            const state = states.get(sessionID);
            if (state?.timer) clearTimeout(state.timer);
            if (state) state.timer = null;
        };
        const isRoot = (sessionID) => {
            if (!sessionID) return false;
            try {
                const session = sessionApi.get(sessionID);
                if (!session) return false;
                return session.parentID === undefined;
            } catch (_) { return false; }
        };
        const flagTab = () => {
            if (!paneId) return;
            try {
                const child = spawn("zellij", ["pipe", "--name", `zellij-attention::waiting::${paneId}`], {
                    stdio: "ignore", detached: true,
                });
                child.on("error", () => {});
                child.unref();
            } catch (_) {}
        };
        const notify = (sessionID, message) => {
            const state = stateFor(sessionID);
            if (closed || state.notified) return;
            state.notified = true;
            flagTab();
            try {
                void Promise.resolve(ctx.attention.notify({
                    message,
                    sound: {
                        name: "default",
                        when: "always",
                    },
                })).catch(() => {});
            } catch (_) {}
        };
        const subscribe = (name, action, identify = sessionIdentifier) => {
            try {
                const unsubscribe = data.on(name, (event) => {
                    const sessionID = identify(event?.data);
                    const displayed = displayedSession();
                    const eventSessionPresent = Boolean(sessionID);
                    const routeSessionPresent = Boolean(displayed.sessionID);
                    const match = eventSessionPresent && routeSessionPresent && sessionID === displayed.sessionID;
                    const rejection = !eventSessionPresent ? "no route"
                        : !routeSessionPresent ? "no route"
                            : !match ? "mismatch"
                                : !isRoot(sessionID) ? "not root" : null;
                    record(debug, "event", {
                        routeSource: displayed.source,
                        routeSessionPresent,
                        eventSessionPresent,
                        match,
                        rejection,
                    });
                    if (rejection) return;
                    action(sessionID);
                });
                if (typeof unsubscribe === "function") listeners.push(unsubscribe);
            } catch (_) { record(debug, "listener-error", { type: name }); }
        };
        const reset = (sessionID) => {
            const state = stateFor(sessionID);
            clearTimer(sessionID);
            state.notified = false;
        };
        subscribe("session.execution.started", reset);
        subscribe("session.execution.succeeded", (sessionID) => {
            const state = stateFor(sessionID);
            clearTimer(sessionID);
            if (!state.notified) state.timer = setTimeout(() => {
                state.timer = null;
                const displayed = displayedSession();
                if (displayed.sessionID === sessionID && isRoot(sessionID)) {
                    notify(sessionID, "Waiting for your input");
                }
            }, 3000);
        });
        subscribe("session.execution.interrupted", (sessionID) => { clearTimer(sessionID); notify(sessionID, "Agent stopped"); });
        subscribe("session.execution.failed", (sessionID) => { clearTimer(sessionID); notify(sessionID, "Agent failed"); });
        subscribe("permission.asked", (sessionID) => { clearTimer(sessionID); notify(sessionID, "Waiting for your input"); });
        const formCreatedAction = (sessionID) => { clearTimer(sessionID); notify(sessionID, "Waiting for your input"); };
        subscribe("form.created", formCreatedAction, formSessionIdentifier);
        return () => {
            closed = true;
            for (const sessionID of states.keys()) clearTimer(sessionID);
            states.clear();
            for (const unsubscribe of listeners.splice(0)) { try { unsubscribe(); } catch (_) {} }
        };
    },
});
