#!/usr/bin/env python3
"""LinkedIn InMail sender with robust browser automation.

Handles navigation, composer interaction, field clearing/filling,
and send confirmation.

Supports both CDP mode (direct Chrome connection) and agent-browser mode
(managed session with saved auth state).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

CONNECT_BROWSER_SCRIPT = Path(__file__).resolve().with_name("connect_browser.sh")
CONNECT_BROWSER_GUIDANCE = f'Run: bash "{CONNECT_BROWSER_SCRIPT}" to connect Chrome'


# Import browser_utils for mode-aware operations
sys.path.insert(0, str(Path(__file__).parent))
from browser_utils import (
    ActionRequired,
    BrowserMode,
    FailureCode,
    attempt_timeout_dialog_recovery,
    check_cdp_available,
    check_dialog_status,
    get_browser_mode,
    resolve_browser_mode,
)


def _is_dialog_resolution_command(args: tuple[str, ...]) -> bool:
    """Return whether the command is resolving a pending JavaScript dialog."""
    return len(args) >= 2 and args[0] == "dialog" and args[1] in {"accept", "dismiss"}


def check_browser_available(mode: BrowserMode) -> bool:
    """Check if browser is available for the given mode.

    Args:
        mode: Browser mode configuration

    Returns:
        True if browser is available, False otherwise
    """
    if mode.is_cdp():
        if not mode.cdp_port:
            return False
        return check_cdp_available(mode.cdp_port)
    elif mode.is_agent_browser():
        # For agent-browser mode, check by trying a simple command
        try:
            cmd = ["agent-browser"] + mode.build_agent_browser_args() + ["get", "url"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False
    return False


def resolve_browser_mode_with_fallback(
    provided_port: str | None = None,
    work_dir: Path | None = None,
) -> BrowserMode:
    """Resolve browser mode from provided value, saved mode, or default.

    Args:
        provided_port: Explicitly provided port (used only if no saved agent-browser mode)
        work_dir: Working directory to check for browser mode

    Returns:
        BrowserMode to use
    """
    # Priority 1: Determine work_dir
    if work_dir is None:
        work_dir_str = os.environ.get("WORK_DIR")
        if work_dir_str:
            work_dir = Path(work_dir_str)
        else:
            work_dir = Path.home() / "Desktop" / "linkedin-sourcing"

    # Priority 2: Saved browser mode from runtime (wins over provided_port for agent-browser)
    saved_mode = get_browser_mode(work_dir)
    if saved_mode:
        # If saved mode is agent-browser, it takes precedence over provided_port
        # This allows session mode to work even when scripts pass --cdp-port
        if saved_mode.is_agent_browser():
            return saved_mode
        # If saved mode is CDP and no port provided, use saved port
        if saved_mode.is_cdp() and not provided_port:
            return saved_mode
        # If saved mode is CDP and port is provided, use provided port (allows override)
        if saved_mode.is_cdp() and provided_port:
            return BrowserMode(mode="cdp", cdp_port=provided_port)

    # Priority 3: Explicitly provided port -> CDP mode (when no saved agent-browser mode)
    if provided_port:
        return BrowserMode(mode="cdp", cdp_port=provided_port)

    # Priority 4: Environment variable -> CDP mode
    env_port = os.environ.get("CDP_PORT")
    if env_port:
        return BrowserMode(mode="cdp", cdp_port=env_port)

    # Priority 5: Default CDP mode
    return BrowserMode(mode="cdp", cdp_port="9230")


SUBJECT_SELECTOR = (
    'input[aria-label="Message subject"], '
    'textarea[aria-label="Message subject"], '
    "input[required], textarea[required]"
)
BODY_SELECTOR = "div.ql-editor[role=textbox]"


DEFAULT_SUBPROCESS_TIMEOUT = 5
DEFAULT_DIALOG_TIMEOUT = 2
POST_SEND_RECOVERY_TIMEOUT = 12.0
MAX_SEND_ATTEMPTS = 2
SEND_RETRY_WAIT_SEC = 1.0

BLOCKING_CONTACT_SIGNALS = {
    "recent_activity_inmail",
    "existing_conversation",
    "continue_conversation_button",
    "message_history",
}

# Success signals that indicate a message was actually sent
# NOTE: Only strong, explicit signals are included. Weak signals like
# "conversation_updated" are intentionally excluded to prevent false positives.
SEND_SUCCESS_SIGNALS = {
    "toast_notification",  # LinkedIn shows "Message sent" toast
    "sent_confirmation",  # Explicit sent confirmation text
}

LAST_NAVIGATION_FAILURE_CODE: str | None = None


def _is_browser_unavailable_message(error_text: str | None) -> bool:
    """Return whether an error string indicates the browser is unavailable."""
    if not error_text:
        return False

    lowered = error_text.lower()
    return "browser not available" in lowered or "agent-browser not found" in lowered


RECENT_CONTACT_CHECK_JS = r"""
(function() {
    var signals = [];

    function textOf(node) {
        return ((node && node.textContent) || '').replace(/\s+/g, ' ').trim();
    }

    function attrText(node) {
        if (!node || !node.getAttribute) return '';
        return [
            node.getAttribute('aria-label') || '',
            node.getAttribute('title') || '',
            node.getAttribute('data-control-name') || '',
        ].join(' ');
    }

    function looksLikeContactActivity(text) {
        var lower = text.toLowerCase();
        if (/candidate accepted .*inmail/.test(lower)) return true;
        if (/replied to .*inmail/.test(lower)) return true;
        if (/sent .*inmail/.test(lower)) return true;
        if (/continue conversation|view message|see message|message history/.test(lower)) return true;
        return false;
    }

    // Recruiter profile page: "Most recent activity" is a strong source of truth.
    var activityAnchors = Array.from(document.querySelectorAll('button, [role="button"], h2, h3, h4, section, div, region'))
        .filter(function(node) {
            var combined = (textOf(node) + ' ' + attrText(node)).toLowerCase();
            return combined.includes('most recent activity');
        });

    for (var anchor of activityAnchors) {
        var candidates = [
            anchor,
            anchor.parentElement,
            anchor.nextElementSibling,
            anchor.parentElement && anchor.parentElement.nextElementSibling,
            anchor.closest('[role="region"]'),
            anchor.closest('section'),
            anchor.closest('main'),
        ].filter(Boolean);

        var activityText = candidates.map(textOf).join(' | ');
        if (looksLikeContactActivity(activityText)) {
            signals.push('recent_activity_inmail');
            break;
        }
    }

    // Existing conversation affordances outside the activity module.
    var conversationIndicators = document.querySelectorAll('button, a, [role="button"], [aria-label]');
    for (var el of conversationIndicators) {
        var text = (textOf(el) + ' ' + attrText(el)).toLowerCase();
        if (/continue conversation|view message|see message|message history|replied to your inmail/i.test(text)) {
            signals.push('existing_conversation');
            break;
        }
    }

    // Message tab with thread count often accompanies prior contact.
    var messageTabs = Array.from(document.querySelectorAll('a, button')).filter(function(node) {
        return /messages?\s*\(\d+\)/i.test(textOf(node));
    });
    if (messageTabs.some(function(node) { return /messages?\s*\(([1-9]\d*)\)/i.test(textOf(node)); })) {
        signals.push('message_history');
    }

    return {
        hasSignals: signals.length > 0,
        signals: Array.from(new Set(signals)),
        reason: signals.length > 0 ? Array.from(new Set(signals)).join(', ') : 'no_recent_contact_detected'
    };
})()
"""


def run_agent_browser(
    mode: BrowserMode,
    *args: str,
    timeout_sec: int = DEFAULT_SUBPROCESS_TIMEOUT,
    retry_after_alert_recovery: bool = False,
) -> tuple[int, str, str]:
    """Run agent-browser command and return (returncode, stdout, stderr).

    Args:
        mode: Browser mode configuration (CDP or agent-browser)
        *args: Additional arguments for agent-browser
        timeout_sec: Subprocess timeout in seconds (default: 5)
        retry_after_alert_recovery: Whether to retry once after auto-accepting
            a blocking alert dialog. Keep False for non-idempotent actions.

    Returns:
        Tuple of (returncode, stdout, stderr). On timeout, returns (-1, "", "timeout").
    """
    # Fail closed if browser is not available
    if not check_browser_available(mode):
        return (
            -1,
            "",
            (f"Browser not available in {mode.mode} mode. " + CONNECT_BROWSER_GUIDANCE),
        )

    cmd = ["agent-browser"] + mode.build_agent_browser_args() + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_sec
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        if _is_dialog_resolution_command(args):
            dialog_info = check_dialog_status(mode, skip_availability_check=True)
            if not dialog_info.get("has_dialog"):
                return 0, "", ""

        recovery = attempt_timeout_dialog_recovery(mode)
        if retry_after_alert_recovery and recovery.get("recovered"):
            return run_agent_browser(
                mode,
                *args,
                timeout_sec=timeout_sec,
                retry_after_alert_recovery=False,
            )

        if recovery.get("auto_accept_succeeded"):
            return -1, "", "timeout; auto-accepted blocking alert dialog"
        return -1, "", "timeout"


def run_agent_browser_probe(
    mode: BrowserMode,
    *args: str,
    timeout_sec: int = DEFAULT_SUBPROCESS_TIMEOUT,
) -> tuple[int, str, str]:
    """Run a read-only/idempotent browser command with alert recovery retry."""
    return run_agent_browser(
        mode,
        *args,
        timeout_sec=timeout_sec,
        retry_after_alert_recovery=True,
    )


def probe_page_state(
    mode: BrowserMode, timeout_sec: int = DEFAULT_DIALOG_TIMEOUT
) -> dict:
    """Probe the current page state for composer, dialogs, and success signals.

    Returns a comprehensive state snapshot for reliable cleanup and verification.
    Fast by design - should complete in under 500ms.

    Args:
        mode: Browser mode configuration
        timeout_sec: Timeout for each individual check

    Returns:
        Dict with keys:
        - composer_open: bool - whether message composer is visible
        - dialog_open: bool - whether a JavaScript dialog is open
        - dialog_state: str - 'open', 'closed', or 'unknown'
        - has_send_button: bool - whether send button is present
        - has_success_toast: bool - whether success toast is visible
        - has_discard_dialog: bool - whether discard confirmation is showing
        - timestamp: float - time of probe
    """
    state = {
        "composer_open": False,
        "dialog_open": False,
        "dialog_state": "unknown",
        "has_send_button": False,
        "has_success_toast": False,
        "has_discard_dialog": False,
        "timestamp": time.time(),
    }

    # Check dialog state
    dialog_state = get_dialog_state(mode, timeout_sec=timeout_sec)
    state["dialog_state"] = dialog_state
    state["dialog_open"] = dialog_state == "open"

    # Check composer open (body field presence)
    js_composer = f"document.querySelector('{BODY_SELECTOR}') !== null"
    success, result = eval_js(
        mode,
        js_composer,
        timeout_sec=timeout_sec,
        retry_after_alert_recovery=True,
    )
    state["composer_open"] = success and result is True

    # Check for send button (only meaningful if composer is open)
    if state["composer_open"]:
        js_send_btn = r"""
        (function() {
            var btn = Array.from(document.querySelectorAll("button"))
                .find(b => /Send this message/i.test((b.textContent || "").replace(/\s+/g, ' ').trim()));
            return btn !== undefined;
        })()
        """
        success, result = eval_js(
            mode,
            js_send_btn,
            timeout_sec=timeout_sec,
            retry_after_alert_recovery=True,
        )
        state["has_send_button"] = success and result is True

    # Check for success toast/confirmation
    js_toast = r"""
    (function() {
        var signals = [];
        // Check for toast notifications
        var toasts = document.querySelectorAll('[role="alert"], .artdeco-toast-item, .toast-item');
        for (var toast of toasts) {
            var text = (toast.textContent || "").toLowerCase();
            if (/message sent|sent successfully|inmail sent/.test(text)) {
                signals.push("toast_notification");
            }
        }
        // Check for sent confirmation in conversation (strong signal)
        var sentIndicators = document.querySelectorAll('.msg-s-event-listitem--sent, [data-test-conversation-status="sent"]');
        if (sentIndicators.length > 0) {
            signals.push("sent_confirmation");
        }
        // NOTE: We intentionally do NOT check for conversation_updated here.
        // That signal is too weak - it can appear from merely viewing conversations.
        // Only strong, explicit signals (toast, sent_confirmation) count as proof of send.
        return signals;
    })()
    """
    success, result = eval_js(
        mode,
        js_toast,
        timeout_sec=timeout_sec,
        retry_after_alert_recovery=True,
    )
    if success and isinstance(result, list):
        state["has_success_toast"] = any(sig in SEND_SUCCESS_SIGNALS for sig in result)
        state["success_signals"] = result

    # Check for discard confirmation dialog text
    js_discard = r"""
    (function() {
        // Check for discard dialog text in visible elements
        var elements = document.querySelectorAll('div, span, p');
        for (var el of elements) {
            var text = (el.textContent || "").toLowerCase();
            if (/discard your message|discard without sending|this will discard/.test(text)) {
                return true;
            }
        }
        return false;
    })()
    """
    success, result = eval_js(
        mode,
        js_discard,
        timeout_sec=timeout_sec,
        retry_after_alert_recovery=True,
    )
    state["has_discard_dialog"] = success and result is True

    return state


def eval_js(
    mode: BrowserMode,
    js_code: str,
    timeout_sec: int = DEFAULT_SUBPROCESS_TIMEOUT,
    retry_after_alert_recovery: bool = False,
) -> tuple[bool, Any]:
    """Evaluate JavaScript in the browser and parse JSON result.

    Returns (success, result) where result is the parsed JSON response.
    """
    returncode, stdout, stderr = run_agent_browser(
        mode,
        "eval",
        js_code,
        timeout_sec=timeout_sec,
        retry_after_alert_recovery=retry_after_alert_recovery,
    )

    if returncode != 0:
        return False, stderr.strip()

    # Try to parse as JSON, handling agent-browser double encoding when present.
    try:
        parsed = json.loads(stdout.strip())
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except json.JSONDecodeError:
                pass
        return True, parsed
    except json.JSONDecodeError:
        return True, stdout.strip()


def wait_for_element(
    mode: BrowserMode,
    selector_js: str,
    timeout_sec: float = 10.0,
    poll_interval: float = 0.5,
) -> tuple[bool, Any]:
    """Wait for an element to appear using the provided JS selector function.

    selector_js should be a JS expression that returns the element or null.
    Returns (found, element_or_error).
    """
    start = time.time()
    while time.time() - start < timeout_sec:
        success, result = eval_js(mode, selector_js, retry_after_alert_recovery=True)
        if success and result and result != "null" and result != "undefined":
            return True, result
        time.sleep(poll_interval)
    return False, None


def get_current_url(
    mode: BrowserMode, timeout_sec: int = DEFAULT_SUBPROCESS_TIMEOUT
) -> tuple[bool, str]:
    """Return the current browser URL when available."""
    returncode, stdout, stderr = run_agent_browser_probe(
        mode, "get", "url", timeout_sec=timeout_sec
    )
    if returncode != 0:
        return False, (stderr or "").strip()
    return True, stdout.strip()


def urls_match(current_url: str, expected_url: str) -> bool:
    """Return whether the current browser URL matches the target profile URL."""
    if not current_url or not expected_url:
        return False
    current_base = current_url.split("?", 1)[0].rstrip("/")
    expected_base = expected_url.split("?", 1)[0].rstrip("/")
    return current_base == expected_base


def navigate_to_profile(
    mode: BrowserMode,
    profile_url: str,
    timeout_sec: int = 10,
    recovery_wait_sec: float = 3.0,
) -> bool:
    """Navigate to a Recruiter profile, tolerating transient open timeouts.

    agent-browser open can occasionally time out even when Chrome has already landed
    on the requested profile. Treat that as success only when the final URL matches.
    """
    global LAST_NAVIGATION_FAILURE_CODE
    LAST_NAVIGATION_FAILURE_CODE = None

    returncode, _, stderr = run_agent_browser(
        mode, "open", profile_url, timeout_sec=timeout_sec
    )
    if returncode == 0:
        return True
    if _is_browser_unavailable_message(stderr):
        LAST_NAVIGATION_FAILURE_CODE = FailureCode.BROWSER_UNAVAILABLE
        return False
    if returncode == -1 and stderr.strip() == "timeout":
        deadline = time.time() + recovery_wait_sec
        while time.time() < deadline:
            success, current_url = get_current_url(mode, timeout_sec=3)
            if success and urls_match(current_url, profile_url):
                return True
            time.sleep(0.3)
    return False


def get_dialog_status(
    mode: BrowserMode, timeout_sec: int = DEFAULT_DIALOG_TIMEOUT
) -> tuple[int, str]:
    """Return raw dialog status output and exit code."""
    returncode, stdout, stderr = run_agent_browser_probe(
        mode, "dialog", "status", timeout_sec=timeout_sec
    )
    return returncode, (stdout or stderr).strip()


def get_dialog_state(
    mode: BrowserMode, timeout_sec: int = DEFAULT_DIALOG_TIMEOUT
) -> str:
    """Return dialog state as open, closed, or unknown."""
    returncode, status = get_dialog_status(mode, timeout_sec=timeout_sec)
    status_lower = status.lower()

    if returncode != 0:
        return "unknown"
    if "dialog is open" in status_lower:
        return "open"
    if "no dialog is currently open" in status_lower:
        return "closed"
    return "unknown"


def has_pending_dialog(
    mode: BrowserMode, timeout_sec: int = DEFAULT_DIALOG_TIMEOUT
) -> bool:
    """Check whether a JavaScript dialog is open."""
    return get_dialog_state(mode, timeout_sec=timeout_sec) == "open"


def accept_pending_dialog(
    mode: BrowserMode, timeout_sec: int = DEFAULT_DIALOG_TIMEOUT
) -> bool:
    """Accept a pending JavaScript dialog when present."""
    state = get_dialog_state(mode, timeout_sec=timeout_sec)
    if state == "closed":
        return True
    if state == "unknown":
        return False
    returncode, _, _ = run_agent_browser(
        mode, "dialog", "accept", timeout_sec=timeout_sec
    )
    return returncode == 0


def guard_dialogs(mode: BrowserMode, timeout_sec: float = 2.0) -> bool:
    """Fast dialog guard: check and resolve pending dialogs without hanging.

    Checks for pending confirm/prompt dialogs and accepts them intentionally.
    Safe to call before/after browser actions to prevent hangs on pending dialogs.

    Args:
        mode: Browser mode configuration
        timeout_sec: Max time to spend resolving dialogs (default: 2.0)

    Returns:
        True if no dialogs remain (either accepted or never existed)
    """
    start = time.time()
    while time.time() - start < timeout_sec:
        state = get_dialog_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
        if state == "closed":
            return True
        if state == "unknown":
            time.sleep(0.2)
            continue
        run_agent_browser(
            mode,
            "dialog",
            "accept",
            timeout_sec=DEFAULT_DIALOG_TIMEOUT,
        )
        time.sleep(0.2)
    return get_dialog_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT) == "closed"


def should_skip_recent_contact(signals: list[str]) -> bool:
    """Return whether recent-contact signals are strong enough to skip sending."""
    return any(signal in BLOCKING_CONTACT_SIGNALS for signal in signals)


def click_message_button(mode: BrowserMode) -> bool:
    """Click the 'Message {Name}' button using multi-strategy approach."""
    # Strategy 1: Find by regex pattern on text content
    js = """
    (function() {
        var btn = Array.from(document.querySelectorAll("button"))
            .find(b => /^Message\\s/.test(b.textContent.trim()));
        if (btn && !btn.disabled) {
            btn.click();
            return {success: true, strategy: "regex"};
        }
        return {success: false, error: "Message button not found"};
    })()
    """
    success, result = eval_js(mode, js)
    if success and isinstance(result, dict) and result.get("success"):
        return True

    # Strategy 2: Try aria-label containing "Message"
    js = """
    (function() {
        var btn = Array.from(document.querySelectorAll('button[aria-label*="Message"], button[aria-label*="message"]'))
            .find(b => !b.disabled);
        if (btn) {
            btn.click();
            return {success: true, strategy: "aria-label"};
        }
        return {success: false, error: "Message button not found via aria-label"};
    })()
    """
    success, result = eval_js(mode, js)
    if success and isinstance(result, dict) and result.get("success"):
        return True

    return False


def wait_for_message_button(mode: BrowserMode, timeout_sec: float = 10.0) -> bool:
    """Wait for a clickable Message button on the candidate profile."""
    js = r"""
    (function() {
        return !!Array.from(document.querySelectorAll("button")).find(
            b => !b.disabled && (/^Message\s/.test((b.textContent || "").trim()) || /message/i.test(b.getAttribute("aria-label") || ""))
        );
    })()
    """
    found, _ = wait_for_element(mode, js, timeout_sec)
    return found


def wait_for_composer(mode: BrowserMode, timeout_sec: float = 10.0) -> bool:
    """Wait for the message composer to appear."""
    # Check for subject field
    js = f"document.querySelector('{SUBJECT_SELECTOR}') !== null"
    found, _ = wait_for_element(mode, js, timeout_sec)
    if not found:
        return False

    # Check for body field
    js = f"document.querySelector('{BODY_SELECTOR}') !== null"
    found, _ = wait_for_element(mode, js, timeout_sec)
    return found


def dismiss_inline_banners(mode: BrowserMode) -> bool:
    """Dismiss best-effort Recruiter composer coachmarks and banners."""
    js = """
    (function() {
        var labels = ["Got it", "Close the banner", "Dismiss banner", "Not now"];
        var clicked = [];
        for (const label of labels) {
            var btn = Array.from(document.querySelectorAll("button"))
                .find(b => (b.textContent || "").trim() === label || (b.getAttribute("aria-label") || "").trim() === label);
            if (btn && !btn.disabled) {
                btn.click();
                clicked.push(label);
            }
        }
        return {success: true, clicked: clicked};
    })()
    """
    success, _ = eval_js(mode, js)
    return success


def _get_composer_content(mode: BrowserMode) -> tuple[str | None, str | None]:
    """Read current subject and body content from the composer.

    Returns (subject, body) tuple where values may be None if fields not found.
    """
    js = f"""
    (function() {{
        var s = document.querySelector({json.dumps(SUBJECT_SELECTOR)});
        var b = document.querySelector({json.dumps(BODY_SELECTOR)});
        return {{
            subject: s ? (s.value || '') : null,
            body: b ? (b.innerText || '') : null
        }};
    }})()
    """
    success, result = eval_js(mode, js, retry_after_alert_recovery=True)
    if success and isinstance(result, dict):
        return result.get("subject"), result.get("body")
    return None, None


def wait_for_composer_content_stability(
    mode: BrowserMode,
    poll_interval: float = 0.3,
    min_observation_sec: float = 4.0,
    stability_window_sec: float = 1.0,
    overall_timeout_sec: float = 8.0,
) -> bool:
    """Wait for LinkedIn's auto-prefill behavior to settle before filling.

    LinkedIn Recruiter can auto-write/prefill InMail content a few seconds after
    the composer opens. This helper observes subject/body content over time and
    waits until it stops changing for a stability window.

    Args:
        mode: Browser mode configuration
        poll_interval: Seconds between content polls (default: 0.3s)
        min_observation_sec: Minimum time to observe before proceeding (default: 4.0s)
            Increased to ~4s to cover LinkedIn's delayed auto-prefill which can
            start after ~2.5-3s. Prevents race where early return lets LinkedIn
            overwrite the workbook draft.
        stability_window_sec: Required duration of content stability (default: 1.0s)
        overall_timeout_sec: Maximum total wait time (default: 8.0s)

    Returns:
        True if content stabilized or timed out conservatively, False on error.
        If content cannot be read reliably, waits min_observation_sec and returns True.
    """
    start_time = time.time()
    last_change_time = start_time
    last_subject: str | None = None
    last_body: str | None = None

    while time.time() - start_time < overall_timeout_sec:
        subject, body = _get_composer_content(mode)

        # If we cannot read content, fail open conservatively after minimum observation
        if subject is None or body is None:
            elapsed = time.time() - start_time
            if elapsed >= min_observation_sec:
                return True
            time.sleep(poll_interval)
            continue

        # Check if content changed
        if subject != last_subject or body != last_body:
            last_change_time = time.time()
            last_subject = subject
            last_body = body

        elapsed = time.time() - start_time
        stable_for = time.time() - last_change_time

        # Proceed if we've observed long enough and content is stable
        if elapsed >= min_observation_sec and stable_for >= stability_window_sec:
            return True

        time.sleep(poll_interval)

    # Timeout reached - return True conservatively (fail open)
    return True


def clear_and_fill_subject(mode: BrowserMode, subject: str) -> bool:
    """Clear any prefilled content and fill the subject field."""
    js = f"""
    (function() {{
        var s = document.querySelector({json.dumps(SUBJECT_SELECTOR)});
        if (!s) return {{success: false, error: "Subject field not found"}};
        s.focus();
        s.value = '';
        s.dispatchEvent(new Event('input', {{bubbles: true}}));
        s.value = {json.dumps(subject)};
        s.dispatchEvent(new Event('input', {{bubbles: true}}));
        s.dispatchEvent(new Event('change', {{bubbles: true}}));
        return {{success: s.value === {json.dumps(subject)}, value: s.value}};
    }})()
    """
    success, result = eval_js(mode, js)
    return success and isinstance(result, dict) and result.get("success") is True


def clear_and_fill_body(mode: BrowserMode, body: str) -> bool:
    """Clear any prefilled content and fill the body field."""
    js = f"""
    (function() {{
        var b = document.querySelector({json.dumps(BODY_SELECTOR)});
        if (!b) return {{success: false, error: "Body field not found"}};
        var escapeHtml = function(value) {{
            return value
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }};
        var lines = {json.dumps(body.splitlines())};
        b.focus();
        b.innerHTML = lines.map(line => `<p>${{line ? escapeHtml(line) : '<br>'}}</p>`).join('');
        b.dispatchEvent(new Event('input', {{bubbles: true}}));
        return {{success: true, body: b.innerText}};
    }})()
    """
    success, result = eval_js(mode, js)
    return success and isinstance(result, dict) and result.get("success") is True


def verify_fields_filled(
    mode: BrowserMode, expected_subject: str, expected_body: str
) -> bool:
    """Verify that subject and body fields contain expected content."""
    # Check subject
    js = (
        """
    (function() {
        var s = document.querySelector('"""
        + SUBJECT_SELECTOR
        + """');
        return s ? s.value : null;
    })()
    """
    )
    success, actual_subject = eval_js(mode, js, retry_after_alert_recovery=True)
    if not success or actual_subject != expected_subject:
        return False

    # Check body
    js = (
        """
    (function() {
        var b = document.querySelector('"""
        + BODY_SELECTOR
        + """');
        return b ? b.innerText : null;
    })()
    """
    )
    success, actual_body = eval_js(mode, js, retry_after_alert_recovery=True)
    if not success:
        return False

    # Body comparison: normalize whitespace
    expected_normalized = " ".join(expected_body.split())
    actual_normalized = " ".join(str(actual_body).split()) if actual_body else ""
    return (
        expected_normalized in actual_normalized
        or actual_normalized in expected_normalized
    )


def click_send_button(mode: BrowserMode) -> bool:
    """Click the 'Send this message' button."""
    js = r"""
    (function() {
        var btn = Array.from(document.querySelectorAll("button"))
            .find(b => /Send this message/i.test((b.textContent || "").replace(/\s+/g, ' ').trim()));
        if (btn && !btn.disabled) {
            btn.click();
            return {success: true};
        }
        return {success: false, error: "Send button not found or disabled"};
    })()
    """
    success, result = eval_js(mode, js)
    return bool(success and isinstance(result, dict) and result.get("success"))


def dismiss_composer(mode: BrowserMode) -> bool:
    """Dismiss the message composer using multi-strategy approach."""
    # Strategy 1: Find by text/aria-label containing "Dismiss"
    js = """
    (function() {
        var btn = Array.from(document.querySelectorAll("button"))
            .find(b => /Dismiss/.test(b.textContent.trim()) ||
                      (b.getAttribute('aria-label') && /Dismiss/.test(b.getAttribute('aria-label'))));
        if (btn) {
            btn.click();
            return {success: true, strategy: "text"};
        }
        return {success: false};
    })()
    """
    success, result = eval_js(mode, js)
    if success and isinstance(result, dict) and result.get("success"):
        return True

    # Strategy 2: Try aria-label only
    js = """
    (function() {
        var btn = document.querySelector('button[aria-label*="Dismiss"]');
        if (btn) {
            btn.click();
            return {success: true, strategy: "aria-label"};
        }
        return {success: false};
    })()
    """
    success, result = eval_js(mode, js)
    if success and isinstance(result, dict) and result.get("success"):
        return True

    # Strategy 3: Press Escape key
    js = """
    (function() {
        document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', keyCode: 27}));
        return {success: true, strategy: "escape"};
    })()
    """
    eval_js(mode, js)
    return True  # Best effort


def wait_for_composer_closed(mode: BrowserMode, timeout_sec: float = 10.0) -> bool:
    """Wait for the composer to disappear."""
    start = time.time()
    while time.time() - start < timeout_sec:
        js = f"document.querySelector('{BODY_SELECTOR}') === null"
        success, result = eval_js(
            mode,
            js,
            timeout_sec=DEFAULT_DIALOG_TIMEOUT,
            retry_after_alert_recovery=True,
        )
        if success and result is True:
            return True
        if has_pending_dialog(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT):
            if not accept_pending_dialog(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT):
                return False
        time.sleep(0.5)
    return False


def cleanup_dialogs(mode: BrowserMode, timeout_sec: float = 5.0) -> bool:
    """Accept any pending JavaScript dialogs with retry logic.

    Handles browser confirm dialogs like "This will discard your message without sending."
    Returns True when no dialogs remain (either accepted or never existed).
    """
    start = time.time()
    while time.time() - start < timeout_sec:
        state = get_dialog_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
        if state == "closed":
            return True
        if state == "unknown":
            time.sleep(0.3)
            continue
        if not accept_pending_dialog(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT):
            return False
        time.sleep(0.3)
    return get_dialog_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT) == "closed"


def cleanup_open_composer(mode: BrowserMode, max_attempts: int = 3) -> bool:
    """Close any open composer and confirm discard if prompted.

    Ensures clean state before navigation with explicit verification:
    - Accept any existing dialogs first (using fast guard)
    - Close composer if open
    - Accept discard confirmation dialog
    - Verify final clean state (no composer, no dialogs, no discard UI)

    Args:
        mode: Browser mode configuration
        max_attempts: Maximum number of cleanup attempts (default: 3)

    Returns:
        True if clean state is verified, False on ambiguous/unrecoverable state
    """
    for attempt in range(max_attempts):
        # Get initial state
        state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)

        # If already clean, verify and return
        if (
            not state["composer_open"]
            and not state["dialog_open"]
            and not state["has_discard_dialog"]
        ):
            # Double-check after short delay to ensure stability
            time.sleep(0.2)
            verify_state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
            if (
                not verify_state["composer_open"]
                and not verify_state["dialog_open"]
                and not verify_state["has_discard_dialog"]
            ):
                return True
            # State changed, continue to next attempt
            continue

        # Handle any open dialogs first
        if state["dialog_open"]:
            if not guard_dialogs(mode, timeout_sec=2.0):
                if not cleanup_dialogs(mode, timeout_sec=3.0):
                    # Cannot clear dialogs - ambiguous state
                    return False
            time.sleep(0.2)
            continue

        # Handle discard dialog UI (non-JS dialog)
        if state["has_discard_dialog"]:
            # Try to accept/dismiss the discard dialog
            # Only click buttons with discard/close/dismiss semantics - NEVER send
            js_confirm = r"""
            (function() {
                var buttons = Array.from(document.querySelectorAll('button'));
                for (var btn of buttons) {
                    var text = (btn.textContent || "").toLowerCase();
                    // Only match discard/close/dismiss buttons - explicitly exclude send
                    if (/discard|close|dismiss/i.test(text) && !/send/i.test(text) && !btn.disabled) {
                        btn.click();
                        return {success: true, action: "clicked_discard_button"};
                    }
                }
                // Try Escape key as fallback
                document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', keyCode: 27}));
                return {success: true, action: "escape_key"};
            })()
            """
            eval_js(mode, js_confirm, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
            time.sleep(0.3)
            continue

        # Composer is open - close it
        if state["composer_open"]:
            if not dismiss_composer(mode):
                # Dismiss failed - try escape key directly
                js_escape = """
                document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', keyCode: 27}));
                """
                eval_js(mode, js_escape, timeout_sec=DEFAULT_DIALOG_TIMEOUT)

            time.sleep(0.3)

            # Handle discard dialog that may appear
            post_dismiss_state = probe_page_state(
                mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT
            )

            if post_dismiss_state["dialog_open"]:
                if not guard_dialogs(mode, timeout_sec=2.0):
                    if not cleanup_dialogs(mode, timeout_sec=3.0):
                        return False
                time.sleep(0.2)
                continue

            if post_dismiss_state["has_discard_dialog"]:
                # Click discard button
                js_discard = r"""
                (function() {
                    var buttons = Array.from(document.querySelectorAll('button'));
                    for (var btn of buttons) {
                        var text = (btn.textContent || "").toLowerCase();
                        if (/discard/i.test(text) && !btn.disabled) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                })()
                """
                eval_js(mode, js_discard, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
                time.sleep(0.3)
                continue

    # Max attempts reached - final verification
    final_state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)

    # Accept any lingering dialogs as last resort
    if final_state["dialog_open"]:
        accept_pending_dialog(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
        time.sleep(0.2)
        final_state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)

    # Explicit clean state verification
    is_clean = (
        not final_state["composer_open"]
        and not final_state["dialog_open"]
        and not final_state["has_discard_dialog"]
    )

    return is_clean


def confirm_clean_browser_state(
    mode: BrowserMode,
    settle_timeout_sec: float = 3.0,
    poll_interval: float = 0.3,
) -> bool:
    """Verify that the browser has actually settled into a clean state.

    Post-send navigation can briefly leave the DOM in transition even when Chrome
    has already returned to a usable page. Poll for a short window before treating
    cleanup as a hard failure.
    """
    if cleanup_open_composer(mode):
        return True

    deadline = time.time() + settle_timeout_sec
    while time.time() < deadline:
        state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
        if (
            not state.get("composer_open")
            and not state.get("dialog_open")
            and not state.get("has_discard_dialog")
        ):
            return True
        time.sleep(poll_interval)

    return False


def can_retry_send_from_state(state: dict[str, Any] | None) -> bool:
    """Return whether the current browser state supports another send attempt."""
    if not state:
        return False
    return (
        bool(state.get("composer_open"))
        and bool(state.get("has_send_button"))
        and not bool(state.get("dialog_open"))
        and not bool(state.get("has_discard_dialog"))
        and not bool(state.get("has_success_toast"))
    )


def build_manual_send_action_required(
    profile_url: str,
    send_attempts: int,
    reason: str,
) -> ActionRequired:
    """Build explicit fallback guidance for a manual send click."""
    return ActionRequired(
        code=FailureCode.VERIFICATION_FAILED,
        summary="Automation could not finish the final send step",
        steps=[
            "Read draft_subject and draft_body from the workbook row via excel_utils.py read (do NOT rewrite/regenerate content)",
            "Compare the open composer subject/body against the exact workbook values; if different, clear and fill with workbook values",
            "Use agent-browser on the current browser session to click the visible 'Send this message' button exactly once",
            "If agent-browser still cannot complete the click, ask the user to send it manually in Chrome to unblock",
            "Rerun run_send for the same row to reconcile the outcome",
        ],
        can_retry=True,
        context={
            "page_url": profile_url,
            "manual_send_required": True,
            "button_text": "Send this message",
            "send_attempts": send_attempts,
            "details": reason,
            "draft_source": "workbook_only",
            "draft_rule": "Use workbook draft_subject and draft_body exactly as-is; do NOT rewrite or regenerate InMail content",
        },
        actor="agent",
    )


def wait_for_send_complete(mode: BrowserMode, timeout_sec: float = 10.0) -> bool:
    """Wait for send to complete with strong success verification.

    Verifies that a send actually succeeded by looking for explicit
    success signals ONLY (toast notification or sent confirmation).

    Does NOT report success merely because composer disappeared or closed.
    A clean composer close without explicit success signals is treated as failure.

    Args:
        mode: Browser mode configuration
        timeout_sec: Maximum time to wait for completion

    Returns:
        True if send completed successfully (explicit signal detected), False otherwise
    """
    start = time.time()
    poll_interval = 0.3

    while time.time() - start < timeout_sec:
        state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)

        # Success case: Explicit success signal detected ONLY
        # We do NOT accept "composer closed" as success - it could be dismissal, error, etc.
        if state["has_success_toast"]:
            return True

        # Handle any pending dialogs first
        if state["dialog_open"]:
            if not accept_pending_dialog(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT):
                return False
            time.sleep(0.2)
            continue

        # Composer closed without success signal is NOT success
        # This could be: user dismissed, error occurred, network timeout, etc.
        if not state["composer_open"]:
            if state["has_discard_dialog"]:
                # Discard dialog showing - send was definitely not completed
                return False
            # Composer closed but no success signal - ambiguous, treat as failure
            # Do NOT return True here - we need explicit confirmation of send
            return False

        time.sleep(poll_interval)

    # Timeout reached - final state check
    final_state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)

    # Accept any pending dialog as last resort
    if final_state["dialog_open"]:
        accept_pending_dialog(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
        time.sleep(0.2)
        final_state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)

    # Final success check: ONLY explicit signals count
    if final_state["has_success_toast"]:
        return True

    # Composer closed or timeout without explicit success signal = failure
    return False


def check_recent_contact(mode: BrowserMode) -> tuple[bool, str]:
    """Check if candidate has recent InMail activity.

    Inspects the profile page for signals of existing contact:
    - "Most recent activity" panel showing recent InMail
    - Existing message history indicators
    - Message count badges

    Returns:
        (should_skip, reason) where should_skip is True if sending should be skipped
        and reason describes what was found.
        If the check itself fails (cannot determine state), returns (True, "check_failed")
        to fail safe - the caller should treat this as a blocking condition.
    """
    success, result = eval_js(
        mode,
        RECENT_CONTACT_CHECK_JS,
        timeout_sec=3,
        retry_after_alert_recovery=True,
    )
    if not success or not isinstance(result, dict):
        # If check fails, fail safe: treat as blocking condition
        # This prevents sending when we cannot verify it's safe to do so
        return True, "check_failed"

    signals = [str(signal) for signal in result.get("signals", [])]
    if should_skip_recent_contact(signals):
        return True, result.get("reason", "recent_contact_detected")
    if result.get("hasSignals"):
        return False, result.get("reason", "non_blocking_recent_contact_signal")
    return False, result.get("reason", "no_recent_contact")


def reconcile_send_outcome_with_recent_contact(
    mode: BrowserMode,
    profile_url: str,
    timeout_sec: float = POST_SEND_RECOVERY_TIMEOUT,
    poll_interval: float = 1.0,
) -> tuple[bool, str]:
    """Treat post-send recent-contact evidence as source of truth.

    LinkedIn can occasionally close or navigate away from the composer before the
    explicit send confirmation becomes observable. When that happens, navigate back
    to the profile and re-check the strong recent-contact signals before deciding
    the send failed.
    """
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        guard_dialogs(mode, timeout_sec=1.0)

        current_url_ok, current_url = get_current_url(mode, timeout_sec=3)
        if not (current_url_ok and urls_match(current_url, profile_url)):
            navigate_to_profile(mode, profile_url, timeout_sec=10)
            time.sleep(0.5)

        has_recent_contact, reason = check_recent_contact(mode)
        if has_recent_contact and reason != "check_failed":
            return True, reason

        time.sleep(poll_interval)

    return False, "recent_contact_not_detected_after_send"


def _build_failure_result(
    reason: str,
    failure_code: str,
    action_required: ActionRequired,
    clean_state: bool = False,
    profile_url: str = "",
    browser_state: dict | None = None,
) -> dict:
    """Build a standardized failure result with action_required payload.

    This helper ensures consistent failure result structure across all
    failure points in send_inmail_with_result.
    """
    return {
        "status": "FAILED",
        "reason": reason,
        "failure_code": failure_code,
        "action_required": action_required.to_dict(),
        "clean_state": clean_state,
        "profile_url": profile_url,
        "browser_state": browser_state,
    }


def send_inmail_with_result(
    mode: BrowserMode,
    profile_url: str,
    subject: str,
    body: str,
) -> dict:
    """Send an InMail to a candidate with structured result.

    Args:
        mode: Browser mode configuration
        profile_url: LinkedIn profile URL
        subject: Message subject
        body: Message body
    Returns:
        Dict with keys:
        - status: "SENT", "ALREADY_CONTACTED", or "FAILED"
        - reason: Description of result or failure cause
        - failure_code: Stable failure code (for FAILED status)
        - action_required: Structured manual steps (for FAILED status)
        - clean_state: True if browser is in clean state after operation
        - profile_url: The profile URL that was processed
        - browser_state: Optional compact browser state summary
    """
    result = {
        "status": "FAILED",
        "reason": "unknown",
        "failure_code": None,
        "action_required": None,
        "clean_state": False,
        "profile_url": profile_url,
        "browser_state": None,
    }

    # Fail-fast: Check initial browser state before any operations.
    # Attempt same-tab recovery for stale composer/discard state before failing.
    initial_state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
    if initial_state["dialog_open"]:
        return _build_failure_result(
            reason="browser_dialog_blocking_send",
            failure_code=FailureCode.DIALOG_BLOCKED,
            action_required=ActionRequired.dialog_blocked(),
            clean_state=False,
            profile_url=profile_url,
            browser_state=initial_state,
        )

    if initial_state["composer_open"] or initial_state.get("has_discard_dialog"):
        # Attempt same-tab recovery using existing cleanup helper
        recovery_succeeded = cleanup_open_composer(mode)
        if recovery_succeeded:
            # Re-probe state to confirm clean state before continuing
            post_recovery_state = probe_page_state(
                mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT
            )
            # Full clean-state predicate: no composer, no dialog, no discard dialog
            if (
                not post_recovery_state["composer_open"]
                and not post_recovery_state["dialog_open"]
                and not post_recovery_state.get("has_discard_dialog")
            ):
                # Recovery successful - continue with normal flow
                pass
            else:
                # Recovery incomplete - still dirty
                return _build_failure_result(
                    reason="browser_state_not_clean",
                    failure_code=FailureCode.AMBIGUOUS_STATE,
                    action_required=ActionRequired.ambiguous_state(
                        details="Browser has an open composer or discard confirmation that could not be auto-resolved. "
                        "Please close any open message composers or dialogs in Chrome before retrying."
                    ),
                    clean_state=False,
                    profile_url=profile_url,
                    browser_state=post_recovery_state,
                )
        else:
            # Recovery failed - return ambiguous state failure
            return _build_failure_result(
                reason="browser_state_not_clean",
                failure_code=FailureCode.AMBIGUOUS_STATE,
                action_required=ActionRequired.ambiguous_state(
                    details="Browser has an open composer or discard confirmation that could not be auto-resolved. "
                    "Please close any open message composers or dialogs in Chrome before retrying."
                ),
                clean_state=False,
                profile_url=profile_url,
                browser_state=initial_state,
            )

    global LAST_NAVIGATION_FAILURE_CODE
    LAST_NAVIGATION_FAILURE_CODE = None
    if not navigate_to_profile(mode, profile_url, timeout_sec=10):
        if LAST_NAVIGATION_FAILURE_CODE == FailureCode.BROWSER_UNAVAILABLE:
            return _build_failure_result(
                reason="browser_unavailable",
                failure_code=FailureCode.BROWSER_UNAVAILABLE,
                action_required=ActionRequired.browser_unavailable(
                    cdp_port=mode.cdp_port if mode.is_cdp() else None
                ),
                clean_state=False,
                profile_url=profile_url,
            )
        return _build_failure_result(
            reason="navigation_failed",
            failure_code=FailureCode.WRONG_PAGE,
            action_required=ActionRequired.wrong_page(
                expected_url=profile_url,
                actual_url=None,
            ),
            clean_state=True,
            profile_url=profile_url,
        )

    # Guard after navigation
    guard_dialogs(mode, timeout_sec=1.0)

    # Check for recent contact before proceeding
    has_recent_contact, contact_reason = check_recent_contact(mode)
    if has_recent_contact:
        # Check failed - fail safe by not sending
        if contact_reason == "check_failed":
            # No composer opened yet, state is still clean
            return _build_failure_result(
                reason="recent_contact_check_failed",
                failure_code=FailureCode.VERIFICATION_FAILED,
                action_required=ActionRequired.verification_failed(
                    verification_type="recent_contact_check",
                    details="Could not verify if candidate has been recently contacted",
                ),
                clean_state=True,  # No composer opened yet
                profile_url=profile_url,
            )
        # Recent contact detected - skip sending (not a failure)
        result["status"] = "ALREADY_CONTACTED"
        result["reason"] = contact_reason
        result["clean_state"] = True  # No composer opened
        return result

    if not wait_for_message_button(mode, timeout_sec=10):
        # No composer opened yet, state is clean
        return _build_failure_result(
            reason="message_button_never_appeared",
            failure_code=FailureCode.ELEMENT_MISSING,
            action_required=ActionRequired.element_missing(
                selector="Message button (button with text matching /^Message\\s/)",
                page_url=profile_url,
            ),
            clean_state=True,
            profile_url=profile_url,
        )

    # Click Message button
    if not click_message_button(mode):
        # No composer opened yet, state is clean
        return _build_failure_result(
            reason="click_message_button_failed",
            failure_code=FailureCode.ELEMENT_MISSING,
            action_required=ActionRequired.element_missing(
                selector="Message button (button with text matching /^Message\\s/)",
                page_url=profile_url,
            ),
            clean_state=True,
            profile_url=profile_url,
        )

    # Wait for composer to appear
    if not wait_for_composer(mode, timeout_sec=10):
        # Composer may have partially opened - state is dirty
        return _build_failure_result(
            reason="wait_for_composer_failed",
            failure_code=FailureCode.ELEMENT_MISSING,
            action_required=ActionRequired.element_missing(
                selector="Message composer (subject input or body editor)",
                page_url=profile_url,
            ),
            clean_state=False,  # Composer may be partially open
            profile_url=profile_url,
        )

    dismiss_inline_banners(mode)

    # Small delay for composer animation
    time.sleep(0.5)

    # Wait for LinkedIn's auto-prefill to settle before filling
    # This prevents LinkedIn's later auto-write from overwriting our draft
    wait_for_composer_content_stability(mode)

    # Clear and fill subject
    if not clear_and_fill_subject(mode, subject):
        # Composer is open with drafted content - preserve state
        return _build_failure_result(
            reason="fill_subject_failed",
            failure_code=FailureCode.ELEMENT_MISSING,
            action_required=ActionRequired.element_missing(
                selector=f"Subject field (matching: {SUBJECT_SELECTOR})",
                page_url=profile_url,
            ),
            clean_state=False,  # Composer has drafted content
            profile_url=profile_url,
        )

    # Clear and fill body
    if not clear_and_fill_body(mode, body):
        # Composer is open with drafted content - preserve state
        return _build_failure_result(
            reason="fill_body_failed",
            failure_code=FailureCode.ELEMENT_MISSING,
            action_required=ActionRequired.element_missing(
                selector=f"Body field (matching: {BODY_SELECTOR})",
                page_url=profile_url,
            ),
            clean_state=False,  # Composer has drafted content
            profile_url=profile_url,
        )

    # Verify fields are filled correctly
    if not verify_fields_filled(mode, subject, body):
        # Composer is open with drafted content - preserve state
        return _build_failure_result(
            reason="verify_fields_failed",
            failure_code=FailureCode.VERIFICATION_FAILED,
            action_required=ActionRequired.verification_failed(
                verification_type="field_content",
                details="Subject or body field content does not match expected values",
            ),
            clean_state=False,  # Composer has drafted content
            profile_url=profile_url,
        )

    send_attempts = 0
    last_state: dict[str, Any] | None = None

    while send_attempts < MAX_SEND_ATTEMPTS:
        send_attempts += 1

        if not click_send_button(mode):
            last_state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
            if send_attempts < MAX_SEND_ATTEMPTS and can_retry_send_from_state(
                last_state
            ):
                time.sleep(SEND_RETRY_WAIT_SEC)
                continue
            if can_retry_send_from_state(last_state):
                return _build_failure_result(
                    reason="manual_send_required_after_retry",
                    failure_code=FailureCode.VERIFICATION_FAILED,
                    action_required=build_manual_send_action_required(
                        profile_url,
                        send_attempts,
                        "Automation could not click the visible send button reliably",
                    ),
                    clean_state=False,
                    profile_url=profile_url,
                    browser_state=last_state,
                )
            return _build_failure_result(
                reason="click_send_button_failed",
                failure_code=FailureCode.ELEMENT_MISSING,
                action_required=ActionRequired.element_missing(
                    selector="Send button (button with text matching /Send this message/i)",
                    page_url=profile_url,
                ),
                clean_state=False,
                profile_url=profile_url,
                browser_state=last_state,
            )

        if wait_for_send_complete(mode, timeout_sec=10):
            result["status"] = "SENT"
            result["reason"] = (
                "message_sent_successfully"
                if send_attempts == 1
                else "message_sent_successfully_after_retry"
            )
            result["clean_state"] = confirm_clean_browser_state(mode)
            result["browser_state"] = probe_page_state(
                mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT
            )
            return result

        recovered, recovery_reason = reconcile_send_outcome_with_recent_contact(
            mode,
            profile_url,
        )
        if recovered:
            result["status"] = "SENT"
            result["reason"] = f"message_sent_reconciled_from_{recovery_reason}"
            result["clean_state"] = confirm_clean_browser_state(mode)
            result["browser_state"] = probe_page_state(
                mode,
                timeout_sec=DEFAULT_DIALOG_TIMEOUT,
            )
            return result

        last_state = probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT)
        if send_attempts < MAX_SEND_ATTEMPTS and can_retry_send_from_state(last_state):
            time.sleep(SEND_RETRY_WAIT_SEC)
            continue
        if can_retry_send_from_state(last_state):
            return _build_failure_result(
                reason="manual_send_required_after_retry",
                failure_code=FailureCode.VERIFICATION_FAILED,
                action_required=build_manual_send_action_required(
                    profile_url,
                    send_attempts,
                    "Automation clicked send but could not verify completion after retry",
                ),
                clean_state=False,
                profile_url=profile_url,
                browser_state=last_state,
            )

        clean_after_failure = cleanup_open_composer(mode)
        return _build_failure_result(
            reason="wait_for_send_complete_failed",
            failure_code=FailureCode.VERIFICATION_FAILED,
            action_required=ActionRequired.verification_failed(
                verification_type="send_confirmation",
                details="Send completed but no success confirmation detected (toast notification or sent indicator)",
            ),
            clean_state=clean_after_failure,
            profile_url=profile_url,
            browser_state=probe_page_state(mode, timeout_sec=DEFAULT_DIALOG_TIMEOUT),
        )

    return result


def send_inmail(
    mode: BrowserMode,
    profile_url: str,
    subject: str,
    body: str,
) -> str:
    """Send an InMail to a candidate.

    Legacy compatibility wrapper that returns only the status string.
    For structured results with cleanup tracking, use send_inmail_with_result().

    Args:
        mode: Browser mode configuration
        profile_url: LinkedIn profile URL
        subject: Message subject
        body: Message body
    Returns:
        "SENT" on successful send,
        "ALREADY_CONTACTED" if recent contact detected (skip sending),
        "FAILED" on failure
    """
    result = send_inmail_with_result(
        mode=mode,
        profile_url=profile_url,
        subject=subject,
        body=body,
    )
    return result["status"]


def main():
    parser = argparse.ArgumentParser(
        description="Send LinkedIn InMail via browser automation"
    )
    parser.add_argument("profile_url", help="LinkedIn profile URL")
    parser.add_argument("subject", help="Message subject")
    parser.add_argument("body", help="Message body")
    parser.add_argument(
        "--cdp-port",
        default=None,
        help="Chrome DevTools Protocol port (default: from browser mode or 9230)",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Working directory for browser mode resolution",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output structured JSON result instead of legacy status line",
    )

    args = parser.parse_args()

    # Resolve work_dir
    work_dir = None
    if args.work_dir:
        work_dir = Path(args.work_dir)
    else:
        work_dir_str = os.environ.get("WORK_DIR")
        if work_dir_str:
            work_dir = Path(work_dir_str)

    # Resolve browser mode with fallback
    mode = resolve_browser_mode_with_fallback(args.cdp_port, work_dir)

    result = send_inmail_with_result(
        mode=mode,
        profile_url=args.profile_url,
        subject=args.subject,
        body=args.body,
    )

    if args.json_output:
        # Output structured JSON for workflow integration
        print(json.dumps(result, indent=None, separators=(",", ":")))
    else:
        # Legacy output: just the status string
        print(result["status"])

    return 0 if result["status"] in ("SENT", "ALREADY_CONTACTED") else 1


if __name__ == "__main__":
    sys.exit(main())
