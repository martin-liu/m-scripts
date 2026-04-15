#!/bin/bash
# Connect to LinkedIn Recruiter browser with automatic auth bootstrap.
#
# This script implements the auth flow:
# 1. Check if configured CDP browser is reachable AND Recruiter-authenticated
# 2. If yes: use it (fast path)
# 3. Check for saved auth state (< 7 days old)
# 4. If yes: start agent-browser session from saved auth
# 5. If no: auto-bootstrap - launch Chrome, prompt for login, export auth, close Chrome
#
# Usage:
#   bash connect_browser.sh                    # Connect with auto-bootstrap (default)
#   bash connect_browser.sh --check-only       # Check only, no side effects
#   bash connect_browser.sh --status           # Output JSON status, no side effects
#   bash connect_browser.sh --no-bootstrap     # Fail closed if no auth (no browser launch)
#
# Exit codes:
#   0 - Connected successfully (CDP or agent-browser mode)
#   1 - Not connected / auth required
#   2 - Chrome not found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

# Load profile first so it can set defaults like CDP_PORT
if [[ -f ~/.config/linkedin-sourcing/profile.sh ]]; then
    source ~/.config/linkedin-sourcing/profile.sh
fi

# Default values
CHECK_ONLY=false
JSON_OUTPUT=false
AUTO_BOOTSTRAP=true
PREFERRED_PORT="${CDP_PORT:-9230}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --check-only)
            CHECK_ONLY=true
            shift
            ;;
        --status)
            JSON_OUTPUT=true
            CHECK_ONLY=true
            shift
            ;;
        --no-bootstrap)
            AUTO_BOOTSTRAP=false
            shift
            ;;
        --bootstrap)
            # Legacy flag - now default behavior, keep for compatibility
            AUTO_BOOTSTRAP=true
            shift
            ;;
        --port)
            PREFERRED_PORT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Determine WORK_DIR
WORK_DIR="${WORK_DIR:-$HOME/Desktop/linkedin-sourcing}"
RUNTIME_DIR="$WORK_DIR/runtime"
AUTH_DIR="$RUNTIME_DIR/auth"
AUTH_FILE="$AUTH_DIR/linkedin-auth.json"
BROWSER_MODE_FILE="$RUNTIME_DIR/browser_mode.json"

# CHROME_PROFILE from profile.sh or default
CHROME_PROFILE="${CHROME_PROFILE:-$WORK_DIR/chrome-profile}"

# Helper: check if CDP is available
check_cdp() {
    local port="$1"
    curl -s "http://localhost:${port}/json/version" >/dev/null 2>&1
}

# Helper: probe Recruiter auth via Python (more reliable)
probe_auth() {
    local port="$1"
    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from browser_utils import probe_recruiter_auth
import json
result = probe_recruiter_auth('$port')
print(json.dumps(result))
" 2>/dev/null
}

# Helper: probe Recruiter auth without navigating (for read-only checks)
probe_auth_readonly() {
    local port="$1"
    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from browser_utils import probe_recruiter_auth
import json
result = probe_recruiter_auth('$port', navigate=False)
print(json.dumps(result))
" 2>/dev/null
}

# Helper: probe Recruiter auth via session (for agent-browser mode)
probe_auth_via_session() {
    local session_name="$1"
    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from browser_utils import probe_agent_browser_auth
import json
result = probe_agent_browser_auth('$session_name')
print(json.dumps(result))
" 2>/dev/null
}

# Helper: output JSON status
output_json() {
    local status="$1"
    local mode="${2:-unknown}"
    local port="${3:-$PREFERRED_PORT}"
    local message="${4:-}"
    local error="${5:-}"

    cat <<EOF
{
  "status": "$status",
  "mode": "$mode",
  "cdp_port": "$port",
  "authenticated": $( [[ "$status" == "connected" ]] && echo "true" || echo "false" ),
  "message": "$message",
  "error": "$error"
}
EOF
}

# Helper: run Python bootstrap flow
run_bootstrap() {
    python3 "$SCRIPT_DIR/auth_bootstrap.py" --bootstrap --work-dir "$WORK_DIR" --cdp-port "$PREFERRED_PORT" --chrome-profile "$CHROME_PROFILE"
}

# Main logic
main() {
    # Step 1: Check if preferred CDP port is available
    if check_cdp "$PREFERRED_PORT"; then
        # Step 2: Check if authenticated to Recruiter
        if [[ "$CHECK_ONLY" == "true" ]]; then
            auth_result=$(probe_auth_readonly "$PREFERRED_PORT")
        else
            auth_result=$(probe_auth "$PREFERRED_PORT")
        fi
        authenticated=$(echo "$auth_result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('authenticated', False))")

        if [[ "$authenticated" == "True" ]]; then
            # Fast path: CDP available and authenticated
            if [[ "$JSON_OUTPUT" == "true" ]]; then
                output_json "connected" "cdp" "$PREFERRED_PORT" "Using existing authenticated browser"
            else
                echo "CONNECTED (CDP mode, port $PREFERRED_PORT)"
            fi

            # Save browser mode only for side-effecting connect flows
            if [[ "$JSON_OUTPUT" != "true" && "$CHECK_ONLY" != "true" ]]; then
                mkdir -p "$RUNTIME_DIR"
                cat > "$BROWSER_MODE_FILE" <<EOF
{
  "mode": "cdp",
  "cdp_port": "$PREFERRED_PORT",
  "session_name": null,
  "auth_file": null,
  "headed": true,
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
            fi
            exit 0
        else
            # CDP available but not authenticated
            current_url=$(echo "$auth_result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url', 'unknown'))")

            if [[ "$CHECK_ONLY" == "true" ]]; then
                if [[ "$JSON_OUTPUT" == "true" ]]; then
                    output_json "auth_required" "cdp" "$PREFERRED_PORT" "CDP available but not authenticated to Recruiter" "Current URL: $current_url"
                else
                    echo "AUTH_REQUIRED: CDP on port $PREFERRED_PORT is not authenticated to LinkedIn Recruiter"
                    echo "Current URL: $current_url"
                fi
                exit 1
            fi

            # Not in auto-bootstrap mode: fail closed with guidance
            if [[ "$AUTO_BOOTSTRAP" != "true" ]]; then
                if [[ "$JSON_OUTPUT" == "true" ]]; then
                    output_json "auth_required" "cdp" "$PREFERRED_PORT" "CDP available but not authenticated to Recruiter" "Current URL: $current_url"
                else
                    echo "AUTH_REQUIRED: CDP on port $PREFERRED_PORT is not authenticated to LinkedIn Recruiter"
                    echo "Current URL: $current_url"
                    echo ""
                    echo "Run without --no-bootstrap to automatically start authentication flow"
                fi
                exit 1
            fi

            # Fall through to bootstrap flow
            if [[ "$JSON_OUTPUT" != "true" ]]; then
                echo "CDP available on port $PREFERRED_PORT but not authenticated to Recruiter."
                echo "Current URL: $current_url"
                echo ""
                echo "Starting authentication bootstrap..."
                echo ""
            fi
        fi
    else
        # CDP not available
        if [[ "$CHECK_ONLY" == "true" ]]; then
            if [[ "$JSON_OUTPUT" == "true" ]]; then
                output_json "not_connected" "none" "$PREFERRED_PORT" "CDP not available" "No browser found on port $PREFERRED_PORT"
            else
                echo "NOT_CONNECTED: No browser on CDP port $PREFERRED_PORT"
            fi
            exit 1
        fi

        # Not in auto-bootstrap mode: fail closed with guidance
        if [[ "$AUTO_BOOTSTRAP" != "true" ]]; then
            if [[ "$JSON_OUTPUT" == "true" ]]; then
                output_json "not_connected" "none" "$PREFERRED_PORT" "CDP not available" "No browser found on port $PREFERRED_PORT"
            else
                echo "NOT_CONNECTED: No browser on CDP port $PREFERRED_PORT"
                echo ""
                echo "Run without --no-bootstrap to automatically start authentication flow"
            fi
            exit 1
        fi

        if [[ "$JSON_OUTPUT" != "true" ]]; then
            echo "No browser found on CDP port $PREFERRED_PORT."
            echo ""
            echo "Starting authentication bootstrap..."
            echo ""
        fi
    fi

    # Step 3: Bootstrap mode - Check for existing auth file (agent-browser mode)
    if [[ "$AUTO_BOOTSTRAP" == "true" && -f "$AUTH_FILE" ]]; then
        # Validate auth file is recent (< 7 days)
        auth_age_days=$(python3 -c "
import json
import os
from datetime import datetime, timezone
try:
    with open('$AUTH_FILE') as f:
        data = json.load(f)
    exported = data.get('exported_at', '')
    if exported:
        exp_time = datetime.fromisoformat(exported.replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - exp_time).days
        print(age)
    else:
        print(999)
except:
    print(999)
" 2>/dev/null || echo "999")

        if [[ "$auth_age_days" -lt 7 ]]; then
            # Start agent-browser session from saved auth
            if [[ "$JSON_OUTPUT" != "true" ]]; then
                echo "Starting agent-browser session from saved auth ($auth_age_days days old)..."
            fi

            # Generate session name
            session_name="linkedin-$(date +%s)"

            # Start headed agent-browser session
            # CRITICAL: We must verify actual Recruiter authentication, not just process success
            if agent-browser --session "$session_name" --state "$AUTH_FILE" --headed open "https://www.linkedin.com/talent/home" >/dev/null 2>&1; then
                # Process started - now verify Recruiter authentication
                # Session may have started but auth might be invalid/expired
                auth_check=$(probe_auth_via_session "$session_name")
                auth_check_exit_code=$?

                # Handle probe failure (e.g., agent-browser not found)
                if [[ $auth_check_exit_code -ne 0 ]] || [[ -z "$auth_check" ]]; then
                    if [[ "$JSON_OUTPUT" != "true" ]]; then
                        echo "WARNING: Failed to verify session authentication (probe failed)"
                    fi
                    # Continue to bootstrap flow - don't treat as success
                else
                    authenticated=$(echo "$auth_check" | python3 -c "import sys,json; print(json.load(sys.stdin).get('authenticated', False))")

                    if [[ "$authenticated" == "True" ]]; then
                        if [[ "$JSON_OUTPUT" == "true" ]]; then
                            output_json "connected" "agent-browser" "$PREFERRED_PORT" "Using saved auth state ($auth_age_days days old)"
                        else
                            echo "CONNECTED (agent-browser mode, session: $session_name)"
                        fi

                        # Save browser mode with session info (skip in status-only mode)
                        if [[ "$JSON_OUTPUT" != "true" ]]; then
                            mkdir -p "$RUNTIME_DIR"
                            cat > "$BROWSER_MODE_FILE" <<EOF
{
  "mode": "agent-browser",
  "cdp_port": null,
  "session_name": "$session_name",
  "auth_file": "$AUTH_FILE",
  "headed": true,
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
                        fi
                        exit 0
                    else
                        # Session started but not authenticated - auth expired/invalid
                        current_url=$(echo "$auth_check" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url', 'unknown'))")
                        if [[ "$JSON_OUTPUT" != "true" ]]; then
                            echo "Session started but not authenticated to Recruiter (URL: $current_url)"
                            echo "Saved auth may be expired or invalid."
                        fi
                        # Continue to bootstrap flow
                    fi
                fi
            else
                # agent-browser command failed (non-zero exit or not found)
                if [[ "$JSON_OUTPUT" != "true" ]]; then
                    echo "Failed to start agent-browser session from saved auth (command failed)."
                fi
            fi
        else
            if [[ "$JSON_OUTPUT" != "true" ]]; then
                echo "Saved auth state is $auth_age_days days old (max 7 days)."
            fi
        fi
    fi

    # Step 4: Auto-bootstrap disabled and no valid auth found
    if [[ "$AUTO_BOOTSTRAP" != "true" ]]; then
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            output_json "bootstrap_required" "none" "$PREFERRED_PORT" "Auth bootstrap required" "No valid auth found"
        else
            echo "BOOTSTRAP_REQUIRED: No valid authentication found"
            echo "Run without --no-bootstrap to automatically start authentication flow"
        fi
        exit 1
    fi

    # Step 5: Interactive bootstrap flow
    if [[ "$JSON_OUTPUT" != "true" ]]; then
        echo ""
        echo "=== LinkedIn Auth Bootstrap ==="
        echo ""
        echo "No authenticated browser found."
        echo ""
        echo "Launching Chrome for LinkedIn Recruiter login..."
        echo "Please log in to LinkedIn Recruiter in the Chrome window (complete any SSO/2FA)."
        echo "Your authentication will be saved automatically when login completes."
        echo ""
    fi

    # Run the Python bootstrap flow
    bootstrap_result=$(run_bootstrap)
    bootstrap_success=$(echo "$bootstrap_result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))")
    bootstrap_mode=$(echo "$bootstrap_result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('mode', 'failed'))")

    if [[ "$bootstrap_success" == "True" && "$bootstrap_mode" == "cdp" ]]; then
        # Using existing CDP
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            output_json "connected" "cdp" "$PREFERRED_PORT" "Using existing authenticated browser"
        else
            echo "CONNECTED (CDP mode, port $PREFERRED_PORT)"
        fi
        exit 0
    elif [[ "$bootstrap_success" == "True" && "$bootstrap_mode" == "agent-browser" ]]; then
        session_name=$(echo "$bootstrap_result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_name', ''))")
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            output_json "connected" "agent-browser" "$PREFERRED_PORT" "Agent-browser session started"
        else
            echo "CONNECTED (agent-browser mode, session: $session_name)"
        fi
        exit 0
    else
        # Bootstrap failed
        error_msg=$(echo "$bootstrap_result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error', 'Unknown error'))")
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            output_json "bootstrap_failed" "none" "$PREFERRED_PORT" "Auth bootstrap failed" "$error_msg"
        else
            echo "BOOTSTRAP_FAILED: $error_msg"
            echo ""
            echo "Please ensure Chrome is installed and try again."
            echo "If the problem persists, check that your Chrome profile directory is writable:"
            echo "  $CHROME_PROFILE"
        fi
        exit 1
    fi
}

main "$@"
