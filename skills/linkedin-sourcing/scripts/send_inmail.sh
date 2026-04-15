#!/bin/bash
# Send one InMail via browser automation.
# Usage: send_inmail.sh [--verify-only] [--json] <profile_url> <subject> <body>
# Prints SENT on successful send, VERIFIED on verify-only success,
# ALREADY_CONTACTED when prior contact is detected, FAILED on failure.
# Use --json for structured output with cleanup state and failure reasons.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source config for CDP_PORT when available
if [[ -f ~/.config/linkedin-sourcing/profile.sh ]]; then
    source ~/.config/linkedin-sourcing/profile.sh
fi

CDP_PORT="${CDP_PORT:-9230}"

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
    echo "Usage: send_inmail.sh [--verify-only] [--json] <profile_url> <subject> <body>" >&2
    exit 1
fi

# Delegate to Python helper for robust automation
python3 "$SCRIPT_DIR/inmail_sender.py" \
    --cdp-port "$CDP_PORT" \
    $VERIFY_ONLY \
    $JSON_OUTPUT \
    "$URL" \
    "$SUBJECT" \
    "$BODY"
