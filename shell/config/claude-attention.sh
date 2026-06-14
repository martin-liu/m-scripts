#!/usr/bin/env bash
# Claude Code Stop + Notification hook.
# Flags the owning zellij tab with ⚡ and fires a macOS notification + sound.
#
# Stop hook:         always fires (turn complete or waiting for plain-text reply).
# Notification hook: fires for elicitation dialogs (AskUserQuestion, plan approval).
#                    Skipped for permission_prompt (shown in-terminal) and
#                    idle_prompt (already covered by Stop).

# Debounce: only notify if no new event arrives within 3 seconds.
# This prevents subagent turns from triggering false notifications.
# Per-pane temp files so multiple panes debounce independently.
_flag_and_notify() {
    local req_file="/tmp/claude-attention-request-${ZELLIJ_PANE_ID:-none}.time"
    local pid_file="/tmp/claude-attention-debounce-${ZELLIJ_PANE_ID:-none}.pid"

    # Update request timestamp
    date +%s > "$req_file"

    # Start background debounce monitor if not already running
    if ! kill -0 "$(cat "$pid_file" 2>/dev/null)" 2>/dev/null; then
        (
            sleep 3
            REQUEST_TIME=$(cat "$req_file" 2>/dev/null || echo 0)
            NOW=$(date +%s)
            if [ $((NOW - REQUEST_TIME)) -ge 2 ]; then
                # No new event for 2+ seconds — agent is truly idle
                [ -n "$ZELLIJ_PANE_ID" ] && \
                    zellij pipe --name "zellij-attention::waiting::$ZELLIJ_PANE_ID"
                osascript -e 'display notification "Waiting for your input" with title "Claude Code"'
                afplay /System/Library/Sounds/Ping.aiff
                rm -f "$req_file"
            fi
            rm -f "$pid_file"
        ) >/dev/null 2>&1 &
        disown
        echo $! > "$pid_file"
    fi
}

PAYLOAD=$(cat)
HOOK=$(printf '%s' "$PAYLOAD" | jq -r '.hook_event_name // "Stop"')
NOTIF_TYPE=$(printf '%s' "$PAYLOAD" | jq -r '.notification_type // ""')

# Temporary debug: set CLAUDE_ATTENTION_DEBUG=1 to log all hook events.
# Use this to identify which event fires for "choose an option" prompts.
if [ "${CLAUDE_ATTENTION_DEBUG:-}" = "1" ]; then
    printf '%s %s\n' "$(date -Iseconds)" "$(printf '%s' "$PAYLOAD" | jq -c .)" >> /tmp/claude-attention-hooks.log
fi

if [ "$HOOK" = "Stop" ]; then
    _flag_and_notify
elif [ "$HOOK" = "Notification" ]; then
    case "$NOTIF_TYPE" in
        idle_prompt) ;;  # Recurring reminder every ~60s; skip to avoid resetting debounce
        *) _flag_and_notify ;;
    esac
fi
