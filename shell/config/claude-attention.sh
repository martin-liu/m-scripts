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
    local pid_file="/tmp/claude-attention-debounce-${ZELLIJ_PANE_ID:-none}.pid"

    # Cancel any pending notification and restart the timer.
    # This is a proper reset-debounce: each new event pushes the notification
    # further out, so we only notify after the last Stop in a burst.
    local old_pid
    old_pid=$(cat "$pid_file" 2>/dev/null)
    [ -n "$old_pid" ] && kill "$old_pid" 2>/dev/null

    (
        # 13s window: long enough to outlast the ~11s gap between an intermediate
        # subagent-continuation Stop and the true final Stop.
        sleep 13
        [ -n "$ZELLIJ_PANE_ID" ] && \
            zellij pipe --name "zellij-attention::waiting::$ZELLIJ_PANE_ID"
        osascript -e 'display notification "Waiting for your input" with title "Claude Code"'
        afplay /System/Library/Sounds/Ping.aiff
        rm -f "$pid_file"
    ) >/dev/null 2>&1 &
    disown
    echo $! > "$pid_file"
}

PAYLOAD=$(cat)
HOOK=$(printf '%s' "$PAYLOAD" | jq -r '.hook_event_name // "Stop"')
NOTIF_TYPE=$(printf '%s' "$PAYLOAD" | jq -r '.notification_type // ""')

# Temporary debug: set CLAUDE_ATTENTION_DEBUG=1 to log all hook events.
# Use this to identify which event fires for "choose an option" prompts.
if [ "${CLAUDE_ATTENTION_DEBUG:-}" = "1" ]; then
    printf '%s %s\n' "$(date -Iseconds)" "$(printf '%s' "$PAYLOAD" | jq -c .)" >> /tmp/claude-attention-hooks.log
fi

RUNNING_TASKS=$(printf '%s' "$PAYLOAD" | jq '[.background_tasks[]? | select(.status == "running")] | length')

if [ "$HOOK" = "Stop" ] || [ "$HOOK" = "StopFailure" ]; then
    # Don't notify when Claude is just paused waiting for subagents to finish
    [ "${RUNNING_TASKS:-0}" -eq 0 ] && _flag_and_notify
elif [ "$HOOK" = "Notification" ]; then
    case "$NOTIF_TYPE" in
        idle_prompt) ;;  # Recurring reminder every ~60s; skip to avoid resetting debounce
        *) _flag_and_notify ;;
    esac
fi
