// zellij-attention opencode plugin
// Marks the correct zellij tab with ⚡ when the agent is waiting for input.
// Tab clears automatically when you focus it (handled by the wasm plugin).
// No-ops silently when not running inside zellij.
//
// Signal format (broadcast pipe — must use --name, never --plugin):
//   zellij pipe --name "zellij-attention::waiting::<pane_id>"

import { spawn, spawnSync } from "node:child_process";
import { appendFileSync } from "node:fs";

const pane = process.env.ZELLIJ_PANE_ID;

function flagTab() {
    if (!pane) return;
    spawn("zellij", ["pipe", "--name", `zellij-attention::waiting::${pane}`], {
        stdio: "ignore",
        detached: true,
    }).unref();
}

function notify(message) {
    spawnSync("osascript", [
        "-e", `display notification "${message}" with title "opencode"`,
    ], { stdio: "ignore", timeout: 3000 });
    spawnSync("afplay", ["/System/Library/Sounds/Ping.aiff"], { stdio: "ignore", timeout: 3000 });
}

function logEvent(event) {
    if (process.env.OPENCODE_ATTENTION_DEBUG !== "1") return;
    try {
        appendFileSync("/tmp/opencode-events.log",
            JSON.stringify({ t: Date.now(), type: event.type, properties: event.properties }) + "\n");
    } catch (_) {}
}

// Capture the first session ID — this is the main agent.
// All subsequent sessions are subagents and ignored.
let mainSessionID = null;

// Dedup: session.status(idle) and session.idle often fire together
// for the same session. Track which sessions we've already notified.
const notifiedSessions = new Set();

// Debounce timer: wait 3 seconds before notifying.
// If busy arrives during the window, cancel the notification.
let debounceTimer = null;

function onIdle(sessionID) {
    if (!sessionID || sessionID !== mainSessionID) return;
    if (notifiedSessions.has(sessionID)) return;

    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        debounceTimer = null;
        notifiedSessions.add(sessionID);
        flagTab();
        notify("Waiting for your input");
    }, 3000);
}

function onBusy(sessionID) {
    if (debounceTimer) {
        clearTimeout(debounceTimer);
        debounceTimer = null;
    }
    if (sessionID) {
        notifiedSessions.delete(sessionID);
    }
}

export default {
    id: "zellij-attention",
    server: async (_input, _options) => ({
        event: async ({ event }) => {
            logEvent(event);

            const sessionID = event.properties?.sessionID;

            if (event.type === "session.created") {
                if (!mainSessionID && sessionID) {
                    mainSessionID = sessionID;
                }
                return;
            }

            if (event.type === "session.status") {
                const statusType = event.properties?.status?.type;
                if (statusType === "idle") {
                    onIdle(sessionID);
                } else if (statusType === "busy" || statusType === "active") {
                    onBusy(sessionID);
                }
            } else if (event.type === "session.idle") {
                onIdle(sessionID);
            } else if (event.type === "session.busy" || event.type === "session.active") {
                onBusy(sessionID);
            } else if (event.type === "question.asked" || event.type === "permission.asked") {
                flagTab();
                notify("Waiting for your input");
            } else if (event.type === "session.error") {
                if (!sessionID || sessionID === mainSessionID) {
                    flagTab();
                    notify("Session error");
                }
            }
        },
    }),
};
