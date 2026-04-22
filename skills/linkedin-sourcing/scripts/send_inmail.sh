#!/bin/bash
# Send one InMail via browser automation.
# Usage: send_inmail.sh [--json] <profile_url> <subject> <body>
# Prints SENT on successful send, ALREADY_CONTACTED when prior contact is detected,
# FAILED on failure.
# Use --json for structured output with cleanup state and failure reasons.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source config for CDP_PORT when available
if [[ -f ~/.config/linkedin-sourcing/profile.sh ]]; then
    source ~/.config/linkedin-sourcing/profile.sh
fi

if [[ -n "${WORK_DIR:-}" ]]; then
    export WORK_DIR
fi

CDP_PORT="${CDP_PORT:-9234}"
export CDP_PORT

# Parse arguments
VERIFY_ONLY=""
JSON_OUTPUT=""
URL=""
SUBJECT=""
BODY=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --verify-only)
            VERIFY_ONLY="--verify-only"
            shift
            ;;
        --json)
            JSON_OUTPUT="--json"
            shift
            ;;
        *)
            if [[ -z "$URL" ]]; then
                URL="$1"
            elif [[ -z "$SUBJECT" ]]; then
                SUBJECT="$1"
            elif [[ -z "$BODY" ]]; then
                BODY="$1"
            fi
            shift
            ;;
    esac
done

if [[ -z "$URL" || -z "$SUBJECT" || -z "$BODY" ]]; then
    echo "Usage: send_inmail.sh [--json] <profile_url> <subject> <body>" >&2
    exit 1
fi

if [[ -n "$VERIFY_ONLY" ]]; then
    if [[ -n "$JSON_OUTPUT" ]]; then
        printf '%s\n' '{"status":"FAILED","reason":"verify_only_disabled","failure_code":"verify_only_disabled","clean_state":true,"verify_only":true}'
    else
        echo "verify-only mode is disabled because LinkedIn discard dialogs make it unreliable" >&2
    fi
    exit 3
fi

# Delegate to Python helper for robust automation
python3 "$SCRIPT_DIR/inmail_sender.py" \
    --cdp-port "$CDP_PORT" \
    $JSON_OUTPUT \
    "$URL" \
    "$SUBJECT" \
    "$BODY"
