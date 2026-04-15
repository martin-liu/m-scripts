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
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Import auth_bootstrap for auto-bootstrap functionality
sys.path.insert(0, str(Path(__file__).parent))
import auth_bootstrap
from runtime_manager import RuntimeManager


CONNECT_BROWSER_GUIDANCE = (
    'To connect, run: bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh" '
    '(or "$SKILL_DIR/scripts/connect_browser.sh" before runtime init). '
    "This will automatically check for saved auth or start the authentication flow."
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
            return args
        else:
            raise RuntimeError(f"Unknown browser mode: {self.mode}")


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


def check_dialog_status(mode: BrowserMode | str) -> dict[str, Any]:
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
    # Fail closed if browser is not available
    if not check_browser_available(mode):
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


def run_browser_command(
    mode: BrowserMode | str,
    *args: str,
    timeout: float = 30.0,
    check_dialog_on_timeout: bool = True,
) -> dict[str, Any]:
    """Run an agent-browser command with timeout and optional dialog detection.

    This helper runs agent-browser commands and provides enriched error information
    when timeouts occur, including whether a browser dialog may be blocking progress.

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
        - timed_out: bool - whether the command timed out
    """
    # Normalize string cdp_port to BrowserMode for backward compatibility
    if isinstance(mode, str):
        mode = BrowserMode(mode="cdp", cdp_port=mode)
    # Fail closed if browser is not available
    if not check_browser_available(mode):
        return {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "parsed": None,
            "error": (
                f"Browser not available in {mode.mode} mode. "
                + CONNECT_BROWSER_GUIDANCE
            ),
            "dialog_info": None,
            "timed_out": False,
        }

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
            "timed_out": False,
        }

    except subprocess.TimeoutExpired as e:
        # Command timed out - check for blocking dialog if enabled
        dialog_info = None
        if check_dialog_on_timeout:
            dialog_info = check_dialog_status(mode)

        error_msg = f"Command timed out after {timeout}s"
        if dialog_info and dialog_info.get("has_dialog"):
            dialog_type = dialog_info.get("dialog_type", "unknown")
            dialog_msg = dialog_info.get("message", "")
            error_msg += (
                f"; blocking {dialog_type} dialog detected"
                f"{f': {dialog_msg}' if dialog_msg else ''}"
            )
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
            "timed_out": False,
        }


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
        base_msg += ". Please handle the dialog manually and retry"
    else:
        base_msg += "; no blocking dialog detected"

    return base_msg


def _check_auth_from_url(current_url: str | None) -> bool:
    """Check if current URL indicates authenticated Recruiter access.

    Args:
        current_url: The current browser URL after navigation

    Returns:
        True if authenticated to Recruiter, False otherwise
    """
    if not current_url:
        return False

    parsed = urlparse(current_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if host.endswith("linkedin.com") and path.startswith("/talent/"):
        if not any(indicator in path for indicator in RECRUITER_LOGIN_INDICATORS):
            return True
    return False


def probe_recruiter_auth(cdp_port: str, navigate: bool = True) -> dict[str, Any]:
    """Probe whether the CDP browser is authenticated to LinkedIn Recruiter.

    This checks whether the browser is currently authenticated to Recruiter.
    In navigational mode it opens the Recruiter home page first; in read-only
    mode it only inspects the current URL.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        navigate: Whether to navigate to the Recruiter home page before
            checking the current URL

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

        # Get current URL after navigation
        url_result = subprocess.run(
            ["agent-browser", "--cdp", cdp_port, "get", "url"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        current_url = url_result.stdout.strip() if url_result.returncode == 0 else None

        is_authenticated = _check_auth_from_url(current_url)

        return {
            "authenticated": is_authenticated,
            "url": current_url,
            "error": None,
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

    This checks if the session can access the Recruiter home page without
    being redirected to a login page.

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
        result = subprocess.run(
            ["agent-browser", "--session", session_name, "open", RECRUITER_HOME_URL],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Get current URL after navigation
        url_result = subprocess.run(
            ["agent-browser", "--session", session_name, "get", "url"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        current_url = url_result.stdout.strip() if url_result.returncode == 0 else None

        is_authenticated = _check_auth_from_url(current_url)

        return {
            "authenticated": is_authenticated,
            "url": current_url,
            "error": None,
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
