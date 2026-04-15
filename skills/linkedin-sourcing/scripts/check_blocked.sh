#!/bin/bash
# Check if LinkedIn is showing a CAPTCHA or block page.
# Prints BLOCKED or OK.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

source ~/.config/linkedin-sourcing/profile.sh

# Fail closed if CDP is not available - do not allow implicit browser launch
if ! curl -s "http://localhost:${CDP_PORT}/json/version" >/dev/null 2>&1; then
    echo "ERROR: Chrome DevTools Protocol not available on port ${CDP_PORT}" >&2
    echo 'Run the canonical connect script: bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh" (or "$SKILL_DIR/scripts/connect_browser.sh" before runtime init)' >&2
    exit 1
fi

agent-browser --cdp "$CDP_PORT" eval "
    (document.body.textContent.includes('verify') ||
     document.body.textContent.includes('CAPTCHA') ||
     document.body.textContent.includes('unusual traffic') ||
     location.href.includes('checkpoint')) ? 'BLOCKED' : 'OK'
"
