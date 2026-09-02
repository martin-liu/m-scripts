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
        let timer = null;
        let notified = false;
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
        const clearTimer = () => { if (timer) clearTimeout(timer); timer = null; };
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
        const notify = (message) => {
            if (closed || notified) return;
            notified = true;
            flagTab();
            try {
                void Promise.resolve(ctx.attention.notify({ message })).catch(() => {});
            } catch (_) {}
        };
        const subscribe = (name, action, identify = sessionIdentifier) => {
            try {
                const unsubscribe = data.on(name, (event) => {
                    const sessionID = identify(event?.data);
                    record(debug, "event", { type: name, session: Boolean(sessionID) });
                    if (!isRoot(sessionID)) return;
                    action();
                });
                if (typeof unsubscribe === "function") listeners.push(unsubscribe);
            } catch (_) { record(debug, "listener-error", { type: name }); }
        };
        const reset = () => { clearTimer(); notified = false; };
        subscribe("session.execution.started", reset);
        subscribe("session.execution.succeeded", () => {
            clearTimer();
            if (!notified) timer = setTimeout(() => { timer = null; notify("Waiting for your input"); }, 3000);
        });
        subscribe("session.execution.interrupted", () => { clearTimer(); notify("Agent stopped"); });
        subscribe("session.execution.failed", () => { clearTimer(); notify("Agent failed"); });
        subscribe("permission.asked", () => { clearTimer(); notify("Waiting for your input"); });
        const formCreatedAction = () => { clearTimer(); notify("Waiting for your input"); };
        subscribe("form.created", formCreatedAction, formSessionIdentifier);
        return () => {
            closed = true;
            clearTimer();
            for (const unsubscribe of listeners.splice(0)) { try { unsubscribe(); } catch (_) {} }
        };
    },
});
