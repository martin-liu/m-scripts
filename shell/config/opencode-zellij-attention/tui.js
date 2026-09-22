import { spawn } from "node:child_process";
import { appendFileSync } from "node:fs";

const EVENT_LOG = "/tmp/opencode-attention-events.log";
const UNKNOWN_LINEAGE_GRACE_MS = 3000;
const NORMAL_DEBOUNCE_MS = 3000;
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

export default {
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
            const sessionID = route?.type === "session"
                ? route.sessionID
                : null;
            return {
                source,
                sessionID: typeof sessionID === "string" && sessionID ? sessionID : null,
            };
        };
        const stateFor = (rootID) => {
            let state = states.get(rootID);
            if (!state) {
                state = { timer: null, graceTimer: null, notified: false, rootCompleted: false, active: new Set(), provisional: new Set(), cycle: 0 };
                states.set(rootID, state);
            }
            return state;
        };
        const clearTimer = (rootID) => {
            const state = states.get(rootID);
            if (state?.timer) clearTimeout(state.timer);
            if (state) state.timer = null;
        };
        const clearGraceTimer = (rootID) => {
            const state = states.get(rootID);
            if (state?.graceTimer) clearTimeout(state.graceTimer);
            if (state) state.graceTimer = null;
        };
        const provisionalOwners = new Map();
        const releaseProvisional = (rootID, sessionID, reason) => {
            const state = states.get(rootID);
            if (provisionalOwners.get(sessionID)?.rootID === rootID) provisionalOwners.delete(sessionID);
            state?.provisional.delete(sessionID);
            if (state && !state.provisional.size) clearGraceTimer(rootID);
            record(debug, reason === "exact" ? "provisional-exact-settlement" : "provisional-release", { rootID, sessionID, reason });
        };
        const reconcileProvisional = (rootID) => {
            const state = states.get(rootID);
            if (!state) return;
            for (const sessionID of [...state.provisional]) {
                const owner = provisionalOwners.get(sessionID);
                if (!owner || owner.cycle !== state.cycle) { releaseProvisional(rootID, sessionID, "stale"); continue; }
                const family = familyFor(sessionID);
                if (!family) { record(debug, "provisional-reconcile", { rootID, sessionID, result: "unresolved" }); continue; }
                if (family.rootID === rootID && !family.isRoot) {
                    releaseProvisional(rootID, sessionID, "related");
                    state.active.add(sessionID);
                    record(debug, "provisional-reconcile", { rootID, sessionID, result: "known-active" });
                } else releaseProvisional(rootID, sessionID, "unrelated");
            }
        };
        // Resolve the complete ancestry.  A missing, malformed, or cyclic
        // ancestry is deliberately not treated as a root (or a child).
        const familyFor = (sessionID) => {
            if (!sessionID) return null;
            const seen = new Set();
            let currentID = sessionID;
            try {
                while (currentID) {
                    if (seen.has(currentID)) return null;
                    seen.add(currentID);
                    const session = sessionApi.get(currentID);
                    if (!session || typeof session !== "object") return null;
                    const parentID = session.parentID;
                    if (parentID === undefined || parentID === null) {
                        return { rootID: currentID, isRoot: currentID === sessionID };
                    }
                    if (typeof parentID !== "string" || !parentID) return null;
                    currentID = parentID;
                }
                return null;
            } catch (_) { return null; }
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
        const notify = (rootID, message) => {
            const state = stateFor(rootID);
            if (closed || state.notified) return;
            state.notified = true;
            flagTab();
            try {
                record(debug, "notify", {
                    rootID,
                    message,
                    activeCount: state.active.size,
                    rootCompleted: state.rootCompleted,
                    timerPending: Boolean(state.timer),
                });
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
                    const eventFamily = familyFor(sessionID);
                    const routeFamily = familyFor(displayed.sessionID);
                    const eventSessionPresent = Boolean(sessionID);
                    const routeSessionPresent = Boolean(displayed.sessionID);
                    const match = Boolean(eventFamily && routeFamily && routeFamily.isRoot && eventFamily.rootID === routeFamily.rootID);
                    const rejection = !eventSessionPresent ? "no route"
                        : !routeSessionPresent ? "no route"
                            : !eventFamily || !routeFamily ? "unknown lineage"
                                : !match ? "mismatch" : null;
                    record(debug, "event", {
                        routeSource: displayed.source,
                        routeSessionPresent,
                        eventSessionPresent,
                        match,
                        rejection,
                        eventName: name,
                        eventSessionID: sessionID,
                        displayedSessionID: displayed.sessionID,
                        resolvedRootID: eventFamily?.rootID ?? routeFamily?.rootID ?? null,
                        eventIsRoot: eventFamily?.isRoot ?? null,
                    });
                    const provisionalOwner = sessionID ? provisionalOwners.get(sessionID) : null;
                    if (provisionalOwner && (name.endsWith(".succeeded") || name.endsWith(".interrupted") || name.endsWith(".failed"))) {
                        const ownerState = states.get(provisionalOwner.rootID);
                        if (ownerState?.cycle === provisionalOwner.cycle) {
                            releaseProvisional(provisionalOwner.rootID, sessionID, "exact");
                            if (ownerState.rootCompleted && !ownerState.active.size && !ownerState.provisional.size && !ownerState.notified) schedule(provisionalOwner.rootID);
                        }
                        return;
                    }
                    if (name === "session.execution.started" && !eventFamily && provisionallyStart(sessionID, routeFamily)) return;
                    if (rejection) return;
                    action(sessionID, eventFamily);
                    const state = stateFor(eventFamily.rootID);
                    record(debug, "action", {
                        eventName: name,
                        eventSessionID: sessionID,
                        rootID: eventFamily.rootID,
                        activeCount: state.active.size,
                        rootCompleted: state.rootCompleted,
                        notified: state.notified,
                        timerPending: Boolean(state.timer),
                    });
                });
                if (typeof unsubscribe === "function") listeners.push(unsubscribe);
            } catch (_) { record(debug, "listener-error", { type: name }); }
        };
        const reset = (sessionID, family) => {
            const state = stateFor(family.rootID);
            clearTimer(family.rootID);
            clearGraceTimer(family.rootID);
            for (const provisionalID of [...state.provisional]) releaseProvisional(family.rootID, provisionalID, "root-restart");
            state.notified = false;
            state.rootCompleted = false;
            state.active.clear();
            state.cycle += 1;
        };
        const settleChild = (sessionID, family) => {
            const state = stateFor(family.rootID);
            state.active.delete(sessionID);
            if (state.rootCompleted && !state.active.size && !state.provisional.size && !state.notified && !state.timer) schedule(family.rootID);
        };
        const beginGrace = (rootID) => {
            const state = stateFor(rootID);
            if (state.graceTimer || !state.provisional.size) return;
            const cycle = state.cycle;
            state.graceTimer = setTimeout(() => {
                state.graceTimer = null;
                if (closed || state.cycle !== cycle || !state.rootCompleted) return;
                reconcileProvisional(rootID);
                for (const id of [...state.provisional]) releaseProvisional(rootID, id, "grace-expiry");
                record(debug, "unknown-lineage-grace-expired", { rootID });
                schedule(rootID);
            }, UNKNOWN_LINEAGE_GRACE_MS);
            record(debug, "unknown-lineage-grace-scheduled", { rootID });
        };
        const schedule = (rootID) => {
            const state = stateFor(rootID);
            reconcileProvisional(rootID);
            if (state.provisional.size) beginGrace(rootID);
            if (state.notified || state.timer || !state.rootCompleted || state.active.size || state.provisional.size) {
                record(debug, "timer-skipped", {
                    rootID,
                    reason: state.notified ? "notified" : state.timer ? "timer-pending" : !state.rootCompleted ? "root-incomplete" : "active-descendants",
                    activeCount: state.active.size,
                    rootCompleted: state.rootCompleted,
                    notified: state.notified,
                    timerPending: Boolean(state.timer),
                });
                return;
            }
            record(debug, "timer-scheduled", {
                rootID,
                activeCount: state.active.size,
                rootCompleted: state.rootCompleted,
                notified: state.notified,
                timerPending: true,
            });
            const cycle = state.cycle;
            state.timer = setTimeout(() => {
                state.timer = null;
                if (closed || state.cycle !== cycle) return;
                reconcileProvisional(rootID);
                if (state.provisional.size) { beginGrace(rootID); return; }
                const displayed = displayedSession();
                const routeFamily = familyFor(displayed.sessionID);
                record(debug, "timer-fired", {
                    rootID,
                    displayedSessionID: displayed.sessionID,
                    resolvedRootID: routeFamily?.rootID ?? null,
                    activeCount: state.active.size,
                    rootCompleted: state.rootCompleted,
                    notified: state.notified,
                    timerPending: Boolean(state.timer),
                });
                if (routeFamily?.rootID === rootID && routeFamily.isRoot) {
                    notify(rootID, "Waiting for your input");
                }
            }, NORMAL_DEBOUNCE_MS);
        };
        const provisionallyStart = (sessionID, routeFamily) => {
            if (!sessionID || !routeFamily?.isRoot) return false;
            const state = stateFor(routeFamily.rootID);
            clearTimer(routeFamily.rootID);
            state.provisional.add(sessionID);
            provisionalOwners.set(sessionID, { rootID: routeFamily.rootID, cycle: state.cycle });
            record(debug, "provisional-track", { rootID: routeFamily.rootID, sessionID });
            if (state.rootCompleted) beginGrace(routeFamily.rootID);
            return true;
        };
        subscribe("session.execution.started", (sessionID, family) => {
            const state = stateFor(family.rootID);
            if (family.isRoot) reset(sessionID, family);
            else { clearTimer(family.rootID); state.active.add(sessionID); }
        });
        subscribe("session.execution.succeeded", (sessionID, family) => {
            const state = stateFor(family.rootID);
            if (family.isRoot) {
                    clearTimer(family.rootID);
                    state.rootCompleted = true;
                    reconcileProvisional(family.rootID);
                    schedule(family.rootID);
            } else settleChild(sessionID, family);
        });
        const immediateRoot = (message, childSettles = true) => (sessionID, family) => {
            if (!family.isRoot) { if (childSettles) settleChild(sessionID, family); return; }
            clearTimer(family.rootID);
            notify(family.rootID, message);
        };
        subscribe("session.execution.interrupted", immediateRoot("Agent stopped"));
        subscribe("session.execution.failed", immediateRoot("Agent failed"));
        subscribe("permission.asked", immediateRoot("Waiting for your input", false));
        const formCreatedAction = immediateRoot("Waiting for your input", false);
        subscribe("form.created", formCreatedAction, formSessionIdentifier);
        return () => {
            closed = true;
            record(debug, "cleanup", {
                roots: states.size,
                listenerCount: listeners.length,
                timerPending: [...states.values()].some((state) => Boolean(state.timer || state.graceTimer)),
            });
            for (const sessionID of states.keys()) { clearTimer(sessionID); clearGraceTimer(sessionID); }
            provisionalOwners.clear();
            states.clear();
            for (const unsubscribe of listeners.splice(0)) { try { unsubscribe(); } catch (_) {} }
        };
    },
};
