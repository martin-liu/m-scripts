#!/usr/bin/env python3
"""Shared utilities for agent-browser automation with dialog detection.

This module provides helpers for running agent-browser commands with
timeout handling and dialog detection to diagnose blocking issues.

It also provides a unified browser abstraction that supports both:
- CDP mode: connecting to an existing Chrome instance via --cdp <port>
- Agent-browser mode: managed session with saved auth state via --session <name>
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class FailureCode(str, Enum):
    """Standardized failure codes for browser automation failures.

    These codes provide stable identifiers for failure classification
    that can be used by callers to determine appropriate responses.
    """

    BROWSER_UNAVAILABLE = "browser_unavailable"
    AUTH_REQUIRED = "auth_required"
    DIALOG_BLOCKED = "dialog_blocked"
    BLOCKED_OR_CAPTCHA = "blocked_or_captcha"
    WRONG_PAGE = "wrong_page"
    ELEMENT_MISSING = "element_missing"
    TIMEOUT = "timeout"
    VERIFICATION_FAILED = "verification_failed"
    AMBIGUOUS_STATE = "ambiguous_state"
    PARSE_ERROR = "parse_error"


class BrowserReadiness(str, Enum):
    """Browser readiness classification for phase boundary decisions."""

    READY = "ready"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    AUTH_REQUIRED = "auth_required"
    DIALOG_BLOCKED = "dialog_blocked"
    BLOCKED_OR_CAPTCHA = "blocked_or_captcha"
    UNKNOWN = "unknown"


@dataclass
class BrowserReadinessResult:
    """Structured result from browser readiness classification.

    Attributes:
        readiness: The readiness classification
        action_required: Structured manual fallback if not ready
        context: Additional context (URL, error details, etc.)
    """

    readiness: str
    action_required: ActionRequired | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "readiness": self.readiness,
            "action_required": self.action_required.to_dict()
            if self.action_required
            else None,
            "context": self.context,
        }


@dataclass
class ActionRequired:
    """Structured payload for required follow-up actions.

    This dataclass provides a standardized way to communicate when
    automation cannot complete and follow-up steps are required.

    Attributes:
        code: Stable failure code from FailureCode enum
        summary: Human-readable summary of the issue
        steps: List of concrete steps to resolve
        can_retry: Whether retrying the operation may succeed after intervention
        context: Optional additional context (e.g., URL, element selector)
        actor: Who should perform the action - "agent" (default) or "user"
            Use "user" only for genuine user blockers (captcha, login/auth,
            permissions/account issues). Use "agent" for all other cases.
    """

    code: str
    summary: str
    steps: list[str] = field(default_factory=list)
    can_retry: bool = True
    context: dict[str, Any] = field(default_factory=dict)
    actor: str = "agent"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "code": self.code,
            "summary": self.summary,
            "steps": self.steps,
            "can_retry": self.can_retry,
            "context": self.context,
            "actor": self.actor,
        }

    @classmethod
    def browser_unavailable(cls, cdp_port: str | None = None) -> "ActionRequired":
        """Create action_required for browser unavailable situation."""
        context = {}
        if cdp_port:
            context["cdp_port"] = cdp_port
        return cls(
            code=FailureCode.BROWSER_UNAVAILABLE,
            summary="Chrome browser is not available for automation",
            steps=[
                "DO NOT kill or quit any existing Chrome windows",
                "Run connect_browser.sh to launch a new Chrome with CDP and the correct profile",
                "Wait for the new Chrome window to open and load LinkedIn Recruiter",
                "Confirm the Recruiter interface is fully loaded",
                "Retry the operation once Chrome is ready",
            ],
            can_retry=True,
            context=context,
            actor="agent",
        )

    @classmethod
    def auth_required(cls, current_url: str | None = None) -> "ActionRequired":
        """Create action_required for authentication required situation."""
        context = {}
        if current_url:
            context["current_url"] = current_url
        return cls(
            code=FailureCode.AUTH_REQUIRED,
            summary="LinkedIn authentication required - not logged in to Recruiter",
            steps=[
                "Navigate to https://www.linkedin.com/talent/home in Chrome",
                "Log in with LinkedIn credentials if prompted",
                "Complete any CAPTCHA or security verification if presented",
                "Ensure the LinkedIn Recruiter interface is visible (not a login page)",
                "Retry the operation once authenticated",
            ],
            can_retry=True,
            context=context,
            actor="user",
        )

    @classmethod
    def dialog_blocked(
        cls, dialog_type: str | None = None, message: str | None = None
    ) -> "ActionRequired":
        """Create action_required for blocking dialog situation."""
        context = {}
        if dialog_type:
            context["dialog_type"] = dialog_type
        if message:
            context["message"] = message
        return cls(
            code=FailureCode.DIALOG_BLOCKED,
            summary="A browser dialog is blocking automation progress",
            steps=[
                "Look at the Chrome browser window for any open dialogs (alert, confirm, prompt)",
                "Handle the dialog in Chrome by clicking the appropriate buttons",
                "Common dialogs: 'Session expired', 'Confirm navigation', 'Save changes'",
                "Once the dialog is dismissed, retry the operation",
            ],
            can_retry=True,
            context=context,
            actor="agent",
        )

    @classmethod
    def blocked_or_captcha(cls, current_url: str | None = None) -> "ActionRequired":
        """Create action_required for CAPTCHA or security check situation."""
        context = {}
        if current_url:
            context["current_url"] = current_url
        return cls(
            code=FailureCode.BLOCKED_OR_CAPTCHA,
            summary="LinkedIn security check or CAPTCHA is blocking access",
            steps=[
                "Check the Chrome browser for any CAPTCHA challenges",
                "Complete the security verification in the browser",
                "Wait a few minutes before retrying if rate-limited",
                "Consider reducing automation frequency to avoid future blocks",
            ],
            can_retry=True,
            context=context,
            actor="user",
        )

    @classmethod
    def wrong_page(
        cls, expected_url: str | None = None, actual_url: str | None = None
    ) -> "ActionRequired":
        """Create action_required for wrong page situation."""
        context = {}
        if expected_url:
            context["expected_url"] = expected_url
        if actual_url:
            context["actual_url"] = actual_url
        return cls(
            code=FailureCode.WRONG_PAGE,
            summary="Browser is on an unexpected page",
            steps=[
                "Check the Chrome browser to see what page is currently loaded",
                "Navigate to the correct LinkedIn Recruiter page if needed",
                "Ensure the page has fully loaded before retrying",
            ],
            can_retry=True,
            context=context,
            actor="agent",
        )

    @classmethod
    def element_missing(
        cls, selector: str | None = None, page_url: str | None = None
    ) -> "ActionRequired":
        """Create action_required for missing element situation."""
        context = {}
        if selector:
            context["selector"] = selector
        if page_url:
            context["page_url"] = page_url
        return cls(
            code=FailureCode.ELEMENT_MISSING,
            summary="Required page element not found - page structure may have changed",
            steps=[
                "Check the Chrome browser to verify the page has loaded correctly",
                "Look for the expected element (e.g., 'Message' button, composer field)",
                "If the page layout has changed, adjust in Chrome before retrying",
                "Refresh the page and retry the operation",
            ],
            can_retry=True,
            context=context,
            actor="agent",
        )

    @classmethod
    def timeout(cls, operation: str | None = None) -> "ActionRequired":
        """Create action_required for timeout situation."""
        context = {}
        if operation:
            context["operation"] = operation
        return cls(
            code=FailureCode.TIMEOUT,
            summary="Operation timed out - page may be loading slowly or stuck",
            steps=[
                "Check the Chrome browser to see the current page state",
                "Wait for any loading indicators to complete",
                "If the page appears stuck, refresh it in Chrome",
                "Retry the operation once the page is responsive",
            ],
            can_retry=True,
            context=context,
            actor="agent",
        )

    @classmethod
    def verification_failed(
        cls, verification_type: str | None = None, details: str | None = None
    ) -> "ActionRequired":
        """Create action_required for verification failure situation."""
        context = {}
        if verification_type:
            context["verification_type"] = verification_type
        if details:
            context["details"] = details
        return cls(
            code=FailureCode.VERIFICATION_FAILED,
            summary="Verification check failed - expected state not achieved",
            steps=[
                "Check the Chrome browser to verify the current state",
                "Look for any error messages or notifications",
                "Ensure all required fields are filled correctly",
                "Retry the operation after addressing any visible issues",
            ],
            can_retry=True,
            context=context,
            actor="agent",
        )

    @classmethod
    def ambiguous_state(cls, details: str | None = None) -> "ActionRequired":
        """Create action_required for ambiguous/unrecoverable state."""
        context = {}
        if details:
            context["details"] = details
        return cls(
            code=FailureCode.AMBIGUOUS_STATE,
            summary="Browser is in an ambiguous state that cannot be automatically resolved",
            steps=[
                "Check the Chrome browser for any open dialogs, composers, or error messages",
                "Close any open message composers or dialogs in Chrome",
                "Navigate to a known good LinkedIn Recruiter page",
                "Refresh the page if it appears stuck",
                "Retry the operation once the browser is in a clean state",
            ],
            can_retry=True,
            context=context,
            actor="agent",
        )


# Import auth_bootstrap for auto-bootstrap functionality
sys.path.insert(0, str(Path(__file__).parent))
import auth_bootstrap
from runtime_manager import RuntimeManager

CONNECT_BROWSER_SCRIPT = Path(__file__).resolve().with_name("connect_browser.sh")
AUTO_ACCEPTABLE_DIALOG_TYPES = {"alert"}

# Agent-oriented guidance with runnable bash command for automatic auth bootstrap
CONNECT_BROWSER_GUIDANCE = (
    "Chrome browser connection required. "
    'Run: bash "${WORK_DIR}/scripts/connect_browser.sh" to automatically establish CDP connection with auth bootstrap.'
)

# End-user facing guidance for manual fallback (agent helps user, not shell commands)
MANUAL_BROWSER_GUIDANCE = (
    "Please open Chrome and navigate to LinkedIn Recruiter. "
    "Ensure you are logged in and can see the Recruiter interface."
)

# LinkedIn Recruiter URLs for auth probing
RECRUITER_HOME_URL = "https://www.linkedin.com/talent/home"
# URL paths that indicate unauthenticated state (must be lowercase for comparison)
RECRUITER_LOGIN_INDICATORS = [
    "/login",
    "/login-cap",
    "/signin",
    "/challenge",
    "/checkpoint",
    "/uas/login",  # LinkedIn's unified auth system login paths
    "/uas/checkpoint",
    "/auth",
    "/cap",  # captcha/challenge pages
]

# JavaScript snippet for generic auth detection
# Returns page state signals without requiring exact URL matching
AUTH_DETECTION_JS = r"""
(() => {
    const url = window.location.href;
    const path = window.location.pathname;
    const title = document.title;
    const html = document.body.innerHTML.toLowerCase();

    // Login/unauthenticated indicators
    const hasLoginForm = !!document.querySelector('form[action*="login"], input[name="session_key"], input[name="password"]');
    const hasLoginText = /sign\s*in|log\s*in|enter\s*password/i.test(title) ||
                         html.includes('sign in') || html.includes('log in');
    const hasCheckpoint = path.includes('/checkpoint') || path.includes('/challenge');
    const hasCaptcha = path.includes('/cap') || html.includes('captcha');

    // Recruiter/talent authenticated indicators
    const isTalentPath = path.startsWith('/talent');
    const hasRecruiterShell = !!document.querySelector('[data-test-id="recruiter-nav"], .recruiter-nav, [class*="talent"], nav[role="navigation"]');
    const hasUserMenu = !!document.querySelector('[data-test-id="user-menu"], .global-nav__me, [class*="profile-menu"]');

    return {
        url: url,
        path: path,
        title: title,
        isTalentPath: isTalentPath,
        hasLoginForm: hasLoginForm,
        hasLoginText: hasLoginText,
        hasCheckpoint: hasCheckpoint,
        hasCaptcha: hasCaptcha,
        hasRecruiterShell: hasRecruiterShell,
        hasUserMenu: hasUserMenu
    };
})()
"""


@dataclass
class BrowserMode:
    """Browser mode configuration.

    Attributes:
        mode: "cdp" for direct CDP connection, "agent-browser" for managed session
        cdp_port: The CDP port to use for browser operations (CDP mode)
        session_name: The session name for agent-browser managed session
        auth_file: Path to auth state file (for agent-browser mode)
        headed: Whether browser runs in headed mode (visible)
    """

    mode: str  # "cdp" or "agent-browser"
    cdp_port: str | None = None
    session_name: str | None = None
    auth_file: str | None = None
    headed: bool = True

    def is_cdp(self) -> bool:
        """Check if this is CDP mode."""
        return self.mode == "cdp"

    def is_agent_browser(self) -> bool:
        """Check if this is agent-browser mode."""
        return self.mode == "agent-browser"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "mode": self.mode,
            "cdp_port": self.cdp_port,
            "session_name": self.session_name,
            "auth_file": self.auth_file,
            "headed": self.headed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrowserMode":
        """Create from dictionary."""
        return cls(
            mode=data.get("mode", "cdp"),
            cdp_port=data.get("cdp_port"),
            session_name=data.get("session_name"),
            auth_file=data.get("auth_file"),
            headed=data.get("headed", True),
        )

    def build_agent_browser_args(self) -> list[str]:
        """Build agent-browser base arguments for this mode.

        Returns:
            List of command-line arguments for agent-browser
        """
        if self.is_cdp():
            if not self.cdp_port:
                raise RuntimeError("CDP mode requires cdp_port")
            return ["--cdp", self.cdp_port]
        elif self.is_agent_browser():
            if not self.session_name:
                raise RuntimeError("Agent-browser mode requires session_name")
            args = ["--session", self.session_name]
            if self.auth_file:
                args.extend(["--state", self.auth_file])
            if self.headed:
                args.append("--headed")
            return args
        else:
            raise RuntimeError(f"Unknown browser mode: {self.mode}")


def classify_browser_readiness(
    mode: BrowserMode | str,
    current_url: str | None = None,
    error: str | None = None,
    dialog_info: dict[str, Any] | None = None,
) -> BrowserReadinessResult:
    """Classify browser readiness at phase boundaries.

    This helper provides a shared contract for deciding whether to proceed
    with browser automation or request manual fallback. It reuses the
    existing ActionRequired and FailureCode enums.

    Args:
        mode: Browser mode configuration or CDP port string
        current_url: Current browser URL if available
        error: Error message from previous operation if any
        dialog_info: Dialog status info from check_dialog_status if available

    Returns:
        BrowserReadinessResult with classification and optional action_required
    """
    context: dict[str, Any] = {}
    if current_url:
        context["current_url"] = current_url
    if error:
        context["error"] = error

    # Normalize mode to BrowserMode
    if isinstance(mode, str):
        mode = BrowserMode(mode="cdp", cdp_port=mode)

    # Check for blocking dialog
    if dialog_info and dialog_info.get("has_dialog"):
        return BrowserReadinessResult(
            readiness=BrowserReadiness.DIALOG_BLOCKED,
            action_required=ActionRequired.dialog_blocked(
                dialog_type=dialog_info.get("dialog_type"),
                message=dialog_info.get("message"),
            ),
            context=context,
        )

    # Check browser availability after explicit dialog detection so timeout
    # scenarios preserve the more actionable blocker classification.
    if not check_browser_available(mode):
        return BrowserReadinessResult(
            readiness=BrowserReadiness.BROWSER_UNAVAILABLE,
            action_required=ActionRequired.browser_unavailable(
                cdp_port=mode.cdp_port if mode.is_cdp() else None
            ),
            context=context,
        )

    # Check for auth required from URL
    if current_url:
        parsed = urlparse(current_url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()

        # Check for non-talent LinkedIn pages
        is_linkedin = host.endswith("linkedin.com")
        is_talent = path.startswith("/talent")

        # Check for CAPTCHA/security pages FIRST (before general auth indicators)
        # This ensures checkpoint/challenge pages are classified as BLOCKED_OR_CAPTCHA
        if (
            "/cap" in path
            or "captcha" in path.lower()
            or "/checkpoint" in path
            or "/challenge" in path
        ):
            return BrowserReadinessResult(
                readiness=BrowserReadiness.BLOCKED_OR_CAPTCHA,
                action_required=ActionRequired.blocked_or_captcha(
                    current_url=current_url
                ),
                context=context,
            )

        # Check for login indicators in URL (excluding checkpoint/challenge already handled)
        auth_indicators = [
            "/login",
            "/login-cap",
            "/signin",
            "/uas/login",
            "/uas/checkpoint",
            "/auth",
        ]
        has_auth_indicator = any(ind in path for ind in auth_indicators)

        if is_linkedin and not is_talent and has_auth_indicator:
            return BrowserReadinessResult(
                readiness=BrowserReadiness.AUTH_REQUIRED,
                action_required=ActionRequired.auth_required(current_url=current_url),
                context=context,
            )

    # Check for errors that indicate auth issues
    if error:
        error_lower = error.lower()
        if any(
            x in error_lower
            for x in [
                "connection refused",
                "econnrefused",
                "err_connection_refused",
                "failed to fetch browser websocket",
            ]
        ):
            return BrowserReadinessResult(
                readiness=BrowserReadiness.BROWSER_UNAVAILABLE,
                action_required=ActionRequired.browser_unavailable(
                    cdp_port=mode.cdp_port if mode.is_cdp() else None
                ),
                context=context,
            )
        if any(
            x in error_lower
            for x in ["not authenticated", "login required", "auth required"]
        ):
            return BrowserReadinessResult(
                readiness=BrowserReadiness.AUTH_REQUIRED,
                action_required=ActionRequired.auth_required(current_url=current_url),
                context=context,
            )
        if any(x in error_lower for x in ["captcha", "blocked", "security check"]):
            return BrowserReadinessResult(
                readiness=BrowserReadiness.BLOCKED_OR_CAPTCHA,
                action_required=ActionRequired.blocked_or_captcha(
                    current_url=current_url
                ),
                context=context,
            )

    return BrowserReadinessResult(
        readiness=BrowserReadiness.READY,
        action_required=None,
        context=context,
    )


def safe_get_parsed(
    result: dict[str, Any],
    default: Any = None,
    require_dict: bool = True,
) -> Any:
    """Safely extract parsed result from run_browser_command output.

    This helper prevents AttributeError when parsed is None or not a dict.
    Use it in extraction/browser callers instead of direct .get() chaining.

    Args:
        result: The result dict from run_browser_command
        default: Default value if parsed is missing or invalid
        require_dict: If True, require parsed to be a dict (returns default otherwise)

    Returns:
        The parsed value if valid, otherwise default
    """
    if not isinstance(result, dict):
        return default

    parsed = result.get("parsed")
    if parsed is None:
        return default

    if require_dict and not isinstance(parsed, dict):
        return default

    return parsed


def check_cdp_available(cdp_port: str) -> bool:
    """Check if Chrome DevTools Protocol is available on the given port.

    Args:
        cdp_port: Chrome DevTools Protocol port number

    Returns:
        True if CDP is available, False otherwise
    """
    try:
        with urllib.request.urlopen(
            f"http://localhost:{cdp_port}/json/version", timeout=2
        ):
            return True
    except Exception:
        return False


def require_cdp(cdp_port: str) -> None:
    """Require CDP to be available, raise RuntimeError with guidance if not.

    Args:
        cdp_port: Chrome DevTools Protocol port number

    Raises:
        RuntimeError: If CDP is not available, with instructions to run
            connect_browser.sh
    """
    if not check_cdp_available(cdp_port):
        raise RuntimeError(
            f"Chrome DevTools Protocol not available on port {cdp_port}. "
            + CONNECT_BROWSER_GUIDANCE
        )


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
        # For agent-browser mode, we assume session is managed externally
        # and check by trying a simple command
        try:
            cmd = ["agent-browser"] + mode.build_agent_browser_args() + ["get", "url"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False
    return False


def check_dialog_status(
    mode: BrowserMode | str,
    skip_availability_check: bool = False,
) -> dict[str, Any]:
    """Check if a browser dialog/alert is currently open.

    Args:
        mode: Browser mode configuration or CDP port string for backward compatibility

    Returns:
        Dict with dialog status information:
        - has_dialog: bool - whether a dialog is open
        - dialog_type: str | None - type of dialog (alert, confirm, prompt, beforeunload)
        - message: str | None - dialog message text if available
        - error: str | None - error message if check failed
    """
    # Normalize string cdp_port to BrowserMode for backward compatibility
    if isinstance(mode, str):
        mode = BrowserMode(mode="cdp", cdp_port=mode)
    # Fail closed if browser is not available, unless we're explicitly probing
    # after a timeout where a blocking dialog may itself prevent normal checks.
    if not skip_availability_check and not check_browser_available(mode):
        return {
            "has_dialog": False,
            "dialog_type": None,
            "message": None,
            "error": (
                f"Browser not available in {mode.mode} mode. "
                + CONNECT_BROWSER_GUIDANCE
            ),
        }

    cmd = ["agent-browser"] + mode.build_agent_browser_args() + ["dialog", "status"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode != 0:
            return {
                "has_dialog": False,
                "dialog_type": None,
                "message": None,
                "error": result.stderr or "dialog status command failed",
            }

        output = result.stdout.strip()
        if not output:
            return {
                "has_dialog": False,
                "dialog_type": None,
                "message": None,
                "error": None,
            }

        # Try to parse JSON output
        try:
            parsed = json.loads(output)
            # Handle double-encoded JSON
            if isinstance(parsed, str):
                parsed = json.loads(parsed)

            # agent-browser dialog status returns different formats
            # Common format: {"type": "alert", "message": "..."} or {"exists": false}
            if isinstance(parsed, dict):
                has_dialog = parsed.get("exists", parsed.get("type") is not None)
                return {
                    "has_dialog": has_dialog,
                    "dialog_type": parsed.get("type"),
                    "message": parsed.get("message"),
                    "error": None,
                }

            return {
                "has_dialog": False,
                "dialog_type": None,
                "message": None,
                "error": f"Unexpected dialog status format: {parsed}",
            }

        except json.JSONDecodeError:
            # Non-JSON output - treat as no dialog detected
            return {
                "has_dialog": False,
                "dialog_type": None,
                "message": None,
                "error": f"Non-JSON dialog status output: {output[:100]}",
            }

    except subprocess.TimeoutExpired:
        return {
            "has_dialog": False,
            "dialog_type": None,
            "message": None,
            "error": "Dialog status check timed out",
        }
    except FileNotFoundError:
        return {
            "has_dialog": False,
            "dialog_type": None,
            "message": None,
            "error": "agent-browser not found",
        }
    except Exception as e:
        return {
            "has_dialog": False,
            "dialog_type": None,
            "message": None,
            "error": f"Dialog status check failed: {e}",
        }


def attempt_timeout_dialog_recovery(
    mode: BrowserMode | str,
    auto_accept_dialog_types: set[str] | None = None,
) -> dict[str, Any]:
    """Check for a blocking dialog after timeout and auto-accept safe alerts.

    Returns structured metadata describing whether a dialog was found, whether
    auto-accept was attempted, and whether recovery appears to have succeeded.
    """
    # Normalize string cdp_port to BrowserMode for backward compatibility
    if isinstance(mode, str):
        mode = BrowserMode(mode="cdp", cdp_port=mode)

    dialog_info = check_dialog_status(mode, skip_availability_check=True)
    recovery = {
        "dialog_info": dialog_info,
        "detected_dialog_info": dialog_info,
        "post_recovery_dialog_info": None,
        "attempted_auto_accept": False,
        "auto_accept_succeeded": False,
        "recovered": False,
        "error": dialog_info.get("error"),
    }

    if not dialog_info.get("has_dialog"):
        return recovery

    allowed_types = auto_accept_dialog_types or AUTO_ACCEPTABLE_DIALOG_TYPES
    dialog_type = (dialog_info.get("dialog_type") or "").lower()
    if dialog_type not in allowed_types:
        return recovery

    recovery["attempted_auto_accept"] = True
    cmd = ["agent-browser"] + mode.build_agent_browser_args() + ["dialog", "accept"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        recovery["error"] = "Dialog accept timed out"
        return recovery
    except FileNotFoundError:
        recovery["error"] = "agent-browser not found"
        return recovery
    except Exception as e:
        recovery["error"] = f"Dialog accept failed: {e}"
        return recovery

    if result.returncode != 0:
        recovery["error"] = result.stderr or "dialog accept command failed"
        return recovery

    recovery["auto_accept_succeeded"] = True
    post_dialog_info = check_dialog_status(mode, skip_availability_check=True)
    recovery["post_recovery_dialog_info"] = post_dialog_info
    recovery["recovered"] = not post_dialog_info.get("has_dialog", False)
    recovery["error"] = post_dialog_info.get("error")
    return recovery


def run_browser_command(
    mode: BrowserMode | str,
    *args: str,
    timeout: float = 30.0,
    check_dialog_on_timeout: bool = True,
    retry_after_alert_recovery: bool = False,
) -> dict[str, Any]:
    """Run an agent-browser command with timeout and optional dialog detection.

    This helper runs agent-browser commands and provides enriched error information
    when timeouts occur, including whether a browser dialog may be blocking progress.

    Note: This function does NOT pre-check browser availability. Callers should
    use classify_browser_readiness() at phase boundaries for readiness decisions.
    Raw execution/parsing errors are reported as-is.

    Args:
        mode: Browser mode configuration or CDP port string for backward compatibility
        *args: Command arguments to pass to agent-browser (e.g., "eval", "js_code")
        timeout: Maximum time to wait for command completion in seconds
        check_dialog_on_timeout: Whether to check for blocking dialogs on timeout

    Returns:
        Dict with command results:
        - stdout: str - raw stdout from the command
        - stderr: str - raw stderr from the command
        - returncode: int - process return code (-1 for timeout)
        - parsed: Any - parsed JSON output if valid JSON, else None
        - error: str | None - error message if command failed
        - dialog_info: dict | None - dialog status if timeout occurred and checked
        - dialog_recovery: dict | None - dialog recovery metadata after timeout
        - timed_out: bool - whether the command timed out
    """
    # Normalize string cdp_port to BrowserMode for backward compatibility
    if isinstance(mode, str):
        mode = BrowserMode(mode="cdp", cdp_port=mode)

    cmd = ["agent-browser"] + mode.build_agent_browser_args() + list(args)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        output = result.stdout.strip()

        # Try to parse as JSON
        parsed = None
        if output:
            try:
                parsed = json.loads(output)
                # Handle double-encoded JSON from agent-browser
                if isinstance(parsed, str):
                    parsed = json.loads(parsed)
            except json.JSONDecodeError:
                pass

        return {
            "stdout": output,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "parsed": parsed,
            "error": None
            if result.returncode == 0
            else (result.stderr or "Command failed"),
            "dialog_info": None,
            "dialog_recovery": None,
            "timed_out": False,
        }

    except subprocess.TimeoutExpired as e:
        # Command timed out - check for blocking dialog if enabled
        dialog_info = None
        dialog_recovery = None
        if check_dialog_on_timeout:
            dialog_recovery = attempt_timeout_dialog_recovery(mode)
            dialog_info = dialog_recovery.get("dialog_info")

        if (
            retry_after_alert_recovery
            and dialog_recovery
            and dialog_recovery.get("recovered")
        ):
            retry_result = run_browser_command(
                mode,
                *args,
                timeout=timeout,
                check_dialog_on_timeout=False,
                retry_after_alert_recovery=False,
            )
            retry_result["dialog_recovery"] = dialog_recovery
            retry_result["dialog_info"] = dialog_recovery.get("detected_dialog_info")
            return retry_result

        error_msg = f"Command timed out after {timeout}s"
        if dialog_info and dialog_info.get("has_dialog"):
            dialog_type = dialog_info.get("dialog_type", "unknown")
            dialog_msg = dialog_info.get("message", "")
            error_msg += (
                f"; blocking {dialog_type} dialog detected"
                f"{f': {dialog_msg}' if dialog_msg else ''}"
            )
            if dialog_recovery and dialog_recovery.get("auto_accept_succeeded"):
                error_msg += "; auto-accepted it"
        elif dialog_recovery and dialog_recovery.get("auto_accept_succeeded"):
            error_msg += "; auto-accepted blocking alert dialog"
        elif dialog_info and dialog_info.get("error"):
            # Dialog check itself failed - mention this
            error_msg += f"; dialog status check failed: {dialog_info['error']}"

        return {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "parsed": None,
            "error": error_msg,
            "dialog_info": dialog_info,
            "dialog_recovery": dialog_recovery,
            "timed_out": True,
        }

    except FileNotFoundError:
        return {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "parsed": None,
            "error": "agent-browser not found in PATH",
            "dialog_info": None,
            "dialog_recovery": None,
            "timed_out": False,
        }

    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "parsed": None,
            "error": f"Unexpected error: {e}",
            "dialog_info": None,
            "dialog_recovery": None,
            "timed_out": False,
        }


def run_browser_probe(
    mode: BrowserMode | str,
    *args: str,
    timeout: float = 30.0,
    check_dialog_on_timeout: bool = True,
) -> dict[str, Any]:
    """Run a read-only/idempotent browser command with alert recovery retry.

    Use this helper only for browser reads like URL probes, snapshots, and state
    inspection where retrying once after clearing a blocking alert is safe.
    """
    return run_browser_command(
        mode,
        *args,
        timeout=timeout,
        check_dialog_on_timeout=check_dialog_on_timeout,
        retry_after_alert_recovery=True,
    )


def format_timeout_error(
    operation: str,
    timeout_result: dict[str, Any],
    context: str | None = None,
) -> str:
    """Format a user-friendly error message for timeout scenarios.

    Args:
        operation: Description of what was being attempted (e.g., "navigate to projects")
        timeout_result: The result dict from run_browser_command that timed out
        context: Optional additional context about the operation

    Returns:
        Formatted error message string
    """
    base_msg = f"Timeout while trying to {operation}"
    if context:
        base_msg += f" ({context})"

    dialog_info = timeout_result.get("dialog_info")
    if dialog_info and dialog_info.get("has_dialog"):
        dialog_type = dialog_info.get("dialog_type", "unknown")
        dialog_msg = dialog_info.get("message", "")
        base_msg += f"; a {dialog_type} dialog may be blocking progress"
        if dialog_msg:
            base_msg += f": '{dialog_msg}'"
        base_msg += ". Please handle the dialog in Chrome and retry"
    else:
        base_msg += "; no blocking dialog detected"

    return base_msg


def attempt_browser_action(
    mode: BrowserMode | str,
    operation_name: str,
    *args: str,
    timeout: float = 30.0,
    check_dialog_on_timeout: bool = True,
) -> dict[str, Any]:
    """Attempt a browser action with structured result including action_required on failure.

    This wrapper builds on run_browser_command and adds structured failure classification
    with actionable manual steps when automation cannot complete. It checks browser
    availability at the boundary before attempting the action.

    Args:
        mode: Browser mode configuration or CDP port string for backward compatibility
        operation_name: Human-readable name of the operation (e.g., "click send button")
        *args: Command arguments to pass to agent-browser
        timeout: Maximum time to wait for command completion
        check_dialog_on_timeout: Whether to check for blocking dialogs on timeout

    Returns:
        Dict with command results plus structured failure info:
        - All fields from run_browser_command (stdout, stderr, returncode, parsed, etc.)
        - success: bool - whether the operation succeeded
        - action_required: ActionRequired | None - structured manual steps if failed
        - failure_code: str | None - stable failure code if failed
    """
    # Normalize mode to BrowserMode for availability check
    if isinstance(mode, str):
        mode = BrowserMode(mode="cdp", cdp_port=mode)

    # Check browser availability at the boundary
    if not check_browser_available(mode):
        cdp_port = mode.cdp_port if mode.is_cdp() else None
        action_required = ActionRequired.browser_unavailable(cdp_port=cdp_port)
        return {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "parsed": None,
            "error": f"Browser not available in {mode.mode} mode",
            "dialog_info": None,
            "timed_out": False,
            "success": False,
            "action_required": action_required.to_dict(),
            "failure_code": FailureCode.BROWSER_UNAVAILABLE,
        }

    result = run_browser_command(
        mode,
        *args,
        timeout=timeout,
        check_dialog_on_timeout=check_dialog_on_timeout,
    )

    # Determine success based on returncode
    success = result.get("returncode") == 0 and result.get("error") is None

    # Build structured failure info if needed
    action_required = None
    failure_code = None

    if not success:
        # Classify the failure
        if result.get("timed_out"):
            failure_code = FailureCode.TIMEOUT
            dialog_info = result.get("dialog_info")
            if dialog_info and dialog_info.get("has_dialog"):
                failure_code = FailureCode.DIALOG_BLOCKED
                action_required = ActionRequired.dialog_blocked(
                    dialog_type=dialog_info.get("dialog_type"),
                    message=dialog_info.get("message"),
                )
            else:
                action_required = ActionRequired.timeout(operation=operation_name)
        elif "browser not available" in (result.get("error") or "").lower():
            failure_code = FailureCode.BROWSER_UNAVAILABLE
            cdp_port = mode.cdp_port if isinstance(mode, BrowserMode) else str(mode)
            action_required = ActionRequired.browser_unavailable(cdp_port=cdp_port)
        else:
            # Generic failure - provide ambiguous state guidance
            failure_code = FailureCode.AMBIGUOUS_STATE
            action_required = ActionRequired.ambiguous_state(
                details=f"Operation '{operation_name}' failed: {result.get('error')}"
            )

    return {
        **result,
        "success": success,
        "action_required": action_required.to_dict() if action_required else None,
        "failure_code": failure_code,
    }


def _evaluate_auth_js(cdp_port: str | None, session_name: str | None) -> dict[str, Any]:
    """Evaluate auth detection JS and return parsed result.

    Args:
        cdp_port: CDP port (for CDP mode) - mutually exclusive with session_name
        session_name: Session name (for agent-browser mode) - mutually exclusive with cdp_port

    Returns:
        Dict with page state and auth determination:
        - url: str | None - current URL
        - page_state: dict | None - raw JS evaluation result
        - is_authenticated: bool - determined auth status
        - error: str | None - error message if evaluation failed
    """
    if cdp_port:
        cmd = ["agent-browser", "--cdp", cdp_port, "eval", AUTH_DETECTION_JS]
    elif session_name:
        cmd = ["agent-browser", "--session", session_name, "eval", AUTH_DETECTION_JS]
    else:
        return {
            "url": None,
            "page_state": None,
            "is_authenticated": False,
            "error": "Either cdp_port or session_name required",
        }

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode != 0:
            return {
                "url": None,
                "page_state": None,
                "is_authenticated": False,
                "error": f"JS eval failed: {result.stderr}",
            }

        # Parse JSON output
        try:
            page_state = json.loads(result.stdout.strip())
            # Handle double-encoded JSON
            if isinstance(page_state, str):
                page_state = json.loads(page_state)
        except json.JSONDecodeError:
            return {
                "url": None,
                "page_state": None,
                "is_authenticated": False,
                "error": f"Invalid JSON from eval: {result.stdout[:200]}",
            }

        url = page_state.get("url")
        path = page_state.get("path", "")

        # Determine authentication status
        # Authenticated if on talent path AND no unauthenticated indicators
        is_talent = page_state.get("isTalentPath", False)
        has_login_form = page_state.get("hasLoginForm", False)
        has_login_text = page_state.get("hasLoginText", False)
        has_checkpoint = page_state.get("hasCheckpoint", False)
        has_captcha = page_state.get("hasCaptcha", False)

        # URL-based fallback check for non-talent paths
        parsed = urlparse(url) if url else None
        host = parsed.netloc.lower() if parsed else ""
        path_lower = parsed.path.lower() if parsed else ""

        # Auth indicators in URL path
        auth_indicators = [
            "/login",
            "/login-cap",
            "/signin",
            "/challenge",
            "/checkpoint",
            "/uas/login",
            "/uas/checkpoint",
            "/auth",
            "/cap",
        ]
        has_auth_in_url = any(ind in path_lower for ind in auth_indicators)

        # Determine auth status
        is_authenticated = False
        if is_talent and not (has_login_form or has_checkpoint or has_captcha):
            # On talent path without obvious login indicators
            is_authenticated = True
        elif host.endswith("linkedin.com") and path_lower.startswith("/talent"):
            # URL-based check as fallback
            if not has_auth_in_url and not has_login_form:
                is_authenticated = True

        return {
            "url": url,
            "page_state": page_state,
            "is_authenticated": is_authenticated,
            "error": None,
        }

    except subprocess.TimeoutExpired:
        return {
            "url": None,
            "page_state": None,
            "is_authenticated": False,
            "error": "JS eval timed out",
        }
    except Exception as e:
        return {
            "url": None,
            "page_state": None,
            "is_authenticated": False,
            "error": f"JS eval error: {e}",
        }


def probe_recruiter_auth(cdp_port: str, navigate: bool = True) -> dict[str, Any]:
    """Probe whether the CDP browser is authenticated to LinkedIn Recruiter.

    Uses JS-based page state detection to determine authentication status
    without requiring exact URL matching. In navigational mode it opens the
    Recruiter home page first; in read-only mode it only inspects the current page.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        navigate: Whether to navigate to the Recruiter home page before
            checking the current page state

    Returns:
        Dict with auth status:
        - authenticated: bool - True if Recruiter is accessible
        - url: str | None - current URL after navigation attempt
        - error: str | None - error message if check failed
    """
    if not check_cdp_available(cdp_port):
        return {
            "authenticated": False,
            "url": None,
            "error": f"CDP not available on port {cdp_port}",
        }

    try:
        if navigate:
            subprocess.run(
                ["agent-browser", "--cdp", cdp_port, "open", RECRUITER_HOME_URL],
                capture_output=True,
                text=True,
                timeout=10,
            )

        # Use JS-based detection for auth status
        eval_result = _evaluate_auth_js(cdp_port=cdp_port, session_name=None)

        return {
            "authenticated": eval_result["is_authenticated"],
            "url": eval_result["url"],
            "error": eval_result["error"],
        }

    except subprocess.TimeoutExpired:
        return {
            "authenticated": False,
            "url": None,
            "error": "Auth probe timed out",
        }
    except FileNotFoundError:
        return {
            "authenticated": False,
            "url": None,
            "error": "agent-browser not found",
        }
    except Exception as e:
        return {
            "authenticated": False,
            "url": None,
            "error": f"Auth probe failed: {e}",
        }


def probe_agent_browser_auth(session_name: str) -> dict[str, Any]:
    """Probe whether an agent-browser session is authenticated to LinkedIn Recruiter.

    Uses JS-based page state detection to determine authentication status
    without requiring exact URL matching.

    Args:
        session_name: The agent-browser session name

    Returns:
        Dict with auth status:
        - authenticated: bool - True if Recruiter is accessible
        - url: str | None - current URL after navigation attempt
        - error: str | None - error message if check failed
    """
    try:
        # Navigate to Recruiter home
        subprocess.run(
            ["agent-browser", "--session", session_name, "open", RECRUITER_HOME_URL],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Use JS-based detection for auth status
        eval_result = _evaluate_auth_js(cdp_port=None, session_name=session_name)

        return {
            "authenticated": eval_result["is_authenticated"],
            "url": eval_result["url"],
            "error": eval_result["error"],
        }

    except subprocess.TimeoutExpired:
        return {
            "authenticated": False,
            "url": None,
            "error": "Auth probe timed out",
        }
    except FileNotFoundError:
        return {
            "authenticated": False,
            "url": None,
            "error": "agent-browser not found",
        }
    except Exception as e:
        return {
            "authenticated": False,
            "url": None,
            "error": f"Auth probe failed: {e}",
        }


def get_browser_mode(work_dir: Path) -> BrowserMode | None:
    """Get the current browser mode from runtime state.

    Args:
        work_dir: Working directory for runtime data

    Returns:
        BrowserMode if configured, None otherwise
    """
    mode_file = work_dir / "runtime" / "browser_mode.json"
    if not mode_file.exists():
        return None

    try:
        data = json.loads(mode_file.read_text())
        return BrowserMode.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_browser_mode(work_dir: Path, mode: BrowserMode) -> None:
    """Save browser mode to runtime state.

    Args:
        work_dir: Working directory for runtime data
        mode: BrowserMode to save
    """
    mode_file = work_dir / "runtime" / "browser_mode.json"
    mode_file.parent.mkdir(parents=True, exist_ok=True)
    mode_file.write_text(json.dumps(mode.to_dict(), indent=2))


def resolve_browser_mode(work_dir: Path, preferred_port: str = "9230") -> BrowserMode:
    """Resolve the browser mode to use, considering saved state.

    Args:
        work_dir: Working directory for runtime data
        preferred_port: Preferred CDP port (default "9230")

    Returns:
        BrowserMode to use for browser operations
    """
    mode = get_browser_mode(work_dir)
    if mode:
        return mode
    # Default to CDP mode with preferred port
    return BrowserMode(mode="cdp", cdp_port=preferred_port)


class BrowserContext:
    """Context manager for browser operations with unified mode support.

    This provides a consistent interface for browser operations regardless
    of whether using direct CDP or agent-browser managed session.

    Usage:
        with BrowserContext(work_dir) as ctx:
            result = ctx.run_command("eval", "document.title")
            if result["returncode"] == 0:
                print(result["parsed"])
    """

    def __init__(
        self,
        work_dir: Path,
        preferred_port: str = "9230",
        auto_bootstrap: bool = False,
    ):
        """Initialize browser context.

        Args:
            work_dir: Working directory for runtime data
            preferred_port: Preferred CDP port
            auto_bootstrap: Whether to auto-bootstrap auth if needed
        """
        self.work_dir = Path(work_dir)
        self.preferred_port = preferred_port
        self.auto_bootstrap = auto_bootstrap
        self.mode: BrowserMode | None = None

    def _chrome_profile(self) -> Path:
        """Resolve the configured Chrome profile for bootstrap launches."""
        manager = RuntimeManager(work_dir=self.work_dir)
        profile = manager._resolve_profile()
        chrome_profile = profile["CHROME_PROFILE"]
        chrome_profile = chrome_profile.replace("$WORK_DIR", str(self.work_dir))
        chrome_profile = chrome_profile.replace("${WORK_DIR}", str(self.work_dir))
        return Path(chrome_profile).expanduser()

    def __enter__(self) -> "BrowserContext":
        """Enter context - resolve browser mode and ensure connectivity."""
        self.mode = get_browser_mode(self.work_dir)

        if self.mode is None:
            # No saved mode - check preferred port
            if check_cdp_available(self.preferred_port):
                auth_check = probe_recruiter_auth(self.preferred_port)
                if auth_check["authenticated"]:
                    self.mode = BrowserMode(
                        mode="cdp",
                        cdp_port=self.preferred_port,
                        headed=True,
                    )
                elif self.auto_bootstrap:
                    # Trigger bootstrap flow with explicit opt-in
                    bootstrap_result = auth_bootstrap.bootstrap_auth_session(
                        work_dir=self.work_dir,
                        preferred_cdp_port=self.preferred_port,
                        chrome_profile=self._chrome_profile(),
                        allow_browser_launch=True,
                    )
                    if bootstrap_result["success"]:
                        # Reload the saved mode after successful bootstrap
                        self.mode = get_browser_mode(self.work_dir)
                        if self.mode is None:
                            raise RuntimeError(
                                "Bootstrap succeeded but failed to save browser mode"
                            )
                    else:
                        raise RuntimeError(
                            f"Auth bootstrap failed: {bootstrap_result.get('error', 'Unknown error')}. "
                            + CONNECT_BROWSER_GUIDANCE
                        )
                else:
                    raise RuntimeError(
                        f"CDP available on port {self.preferred_port} but not authenticated. "
                        + CONNECT_BROWSER_GUIDANCE
                    )
            elif self.auto_bootstrap:
                # Trigger bootstrap flow with explicit opt-in
                bootstrap_result = auth_bootstrap.bootstrap_auth_session(
                    work_dir=self.work_dir,
                    preferred_cdp_port=self.preferred_port,
                    chrome_profile=self._chrome_profile(),
                    allow_browser_launch=True,
                )
                if bootstrap_result["success"]:
                    # Reload the saved mode after successful bootstrap
                    self.mode = get_browser_mode(self.work_dir)
                    if self.mode is None:
                        raise RuntimeError(
                            "Bootstrap succeeded but failed to save browser mode"
                        )
                else:
                    raise RuntimeError(
                        f"Auth bootstrap failed: {bootstrap_result.get('error', 'Unknown error')}. "
                        + CONNECT_BROWSER_GUIDANCE
                    )
            else:
                raise RuntimeError(
                    f"CDP not available on port {self.preferred_port}. "
                    + CONNECT_BROWSER_GUIDANCE
                )

        # Verify browser is available (handles stale saved state)
        if not check_browser_available(self.mode):
            if self.auto_bootstrap:
                # Stale saved state - attempt bootstrap recovery
                bootstrap_result = auth_bootstrap.bootstrap_auth_session(
                    work_dir=self.work_dir,
                    preferred_cdp_port=self.preferred_port,
                    chrome_profile=self._chrome_profile(),
                    allow_browser_launch=True,
                )
                if bootstrap_result["success"]:
                    # Reload the saved mode after successful bootstrap
                    self.mode = get_browser_mode(self.work_dir)
                    if self.mode is None:
                        raise RuntimeError(
                            "Bootstrap succeeded but failed to save browser mode"
                        )
                else:
                    raise RuntimeError(
                        f"Browser not available in {self.mode.mode} mode and auth bootstrap failed: {bootstrap_result.get('error', 'Unknown error')}. "
                        + CONNECT_BROWSER_GUIDANCE
                    )
            else:
                raise RuntimeError(
                    f"Browser not available in {self.mode.mode} mode. "
                    + CONNECT_BROWSER_GUIDANCE
                )

        # CRITICAL: Probe auth status for saved modes when browser is reachable
        # but may no longer be authenticated to Recruiter
        if self.mode.is_cdp():
            auth_check = probe_recruiter_auth(self.mode.cdp_port or self.preferred_port)
            if not auth_check["authenticated"]:
                if self.auto_bootstrap:
                    # Attempt bootstrap flow to re-authenticate
                    bootstrap_result = auth_bootstrap.bootstrap_auth_session(
                        work_dir=self.work_dir,
                        preferred_cdp_port=self.preferred_port,
                        chrome_profile=self._chrome_profile(),
                        allow_browser_launch=True,
                    )
                    if bootstrap_result["success"]:
                        # Reload the saved mode after successful bootstrap
                        self.mode = get_browser_mode(self.work_dir)
                        if self.mode is None:
                            raise RuntimeError(
                                "Bootstrap succeeded but failed to save browser mode"
                            )
                    else:
                        raise RuntimeError(
                            f"Saved CDP mode reachable but not authenticated, and auth bootstrap failed: {bootstrap_result.get('error', 'Unknown error')}. "
                            + CONNECT_BROWSER_GUIDANCE
                        )
                else:
                    raise RuntimeError(
                        f"Saved CDP mode reachable on port {self.mode.cdp_port} but not authenticated to Recruiter. "
                        + CONNECT_BROWSER_GUIDANCE
                    )
        elif self.mode.is_agent_browser():
            auth_check = probe_agent_browser_auth(self.mode.session_name or "")
            if not auth_check["authenticated"]:
                if self.auto_bootstrap:
                    # Attempt bootstrap flow to re-authenticate
                    bootstrap_result = auth_bootstrap.bootstrap_auth_session(
                        work_dir=self.work_dir,
                        preferred_cdp_port=self.preferred_port,
                        chrome_profile=self._chrome_profile(),
                        allow_browser_launch=True,
                    )
                    if bootstrap_result["success"]:
                        # Reload the saved mode after successful bootstrap
                        self.mode = get_browser_mode(self.work_dir)
                        if self.mode is None:
                            raise RuntimeError(
                                "Bootstrap succeeded but failed to save browser mode"
                            )
                    else:
                        raise RuntimeError(
                            f"Saved agent-browser mode reachable but not authenticated, and auth bootstrap failed: {bootstrap_result.get('error', 'Unknown error')}. "
                            + CONNECT_BROWSER_GUIDANCE
                        )
                else:
                    raise RuntimeError(
                        f"Saved agent-browser mode reachable but not authenticated to Recruiter. "
                        + CONNECT_BROWSER_GUIDANCE
                    )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context - cleanup if needed."""
        # Cleanup handled by individual modes if necessary
        pass

    def run_command(
        self,
        *args: str,
        timeout: float = 30.0,
        check_dialog_on_timeout: bool = True,
    ) -> dict[str, Any]:
        """Run an agent-browser command through this context.

        Args:
            *args: Command arguments for agent-browser
            timeout: Timeout in seconds
            check_dialog_on_timeout: Whether to check for dialogs on timeout

        Returns:
            Result dict from run_browser_command
        """
        if self.mode is None:
            raise RuntimeError("Browser context not initialized")
        return run_browser_command(
            self.mode,
            *args,
            timeout=timeout,
            check_dialog_on_timeout=check_dialog_on_timeout,
        )

    def check_dialog(self) -> dict[str, Any]:
        """Check dialog status through this context."""
        if self.mode is None:
            raise RuntimeError("Browser context not initialized")
        return check_dialog_status(self.mode)

    def is_authenticated(self) -> bool:
        """Check if browser is authenticated to Recruiter."""
        if self.mode is None:
            raise RuntimeError("Browser context not initialized")
        if self.mode.is_cdp():
            result = probe_recruiter_auth(self.mode.cdp_port or "9230")
            return result["authenticated"]
        elif self.mode.is_agent_browser():
            # For agent-browser mode, check by navigating to Recruiter
            result = self.run_command("open", RECRUITER_HOME_URL, timeout=10)
            if result["returncode"] != 0:
                return False
            url_result = self.run_command("get", "url", timeout=5)
            if url_result["returncode"] != 0:
                return False
            current_url = url_result["stdout"].strip().lower()
            return "/talent/" in current_url and not any(
                indicator in current_url for indicator in RECRUITER_LOGIN_INDICATORS
            )
        return False
