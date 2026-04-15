#!/usr/bin/env python3
"""LinkedIn authentication bootstrap for safer auth flow.

This module provides functionality to:
1. Check if a CDP browser is authenticated to LinkedIn Recruiter
2. Launch isolated Chrome for manual login when needed
3. Keep the authenticated Chrome running for subsequent operations (CDP-persistent mode)

The auth flow:
- If configured CDP browser is reachable AND Recruiter-authenticated: use it
- Otherwise: launch headed Chrome with CDP, let user login, keep Chrome running
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


# LinkedIn Recruiter home URL for auth probing
RECRUITER_HOME_URL = "https://www.linkedin.com/talent/home"

# Timeout constants
CDP_CHECK_TIMEOUT = 2  # seconds
AUTH_PROBE_TIMEOUT = 10  # seconds
CHROME_LAUNCH_TIMEOUT = 30  # seconds
CHROME_SHUTDOWN_TIMEOUT = 5  # seconds

# Agent-browser session startup constants
SESSION_STARTUP_POLL_INTERVAL = 0.5  # seconds
SESSION_STARTUP_MAX_WAIT = 5  # seconds
AUTH_PROBE_RETRY_INTERVAL = 1.0  # seconds
AUTH_PROBE_MAX_RETRIES = 10  # ~10 seconds total

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


def check_cdp_available(cdp_port: str) -> bool:
    """Check if Chrome DevTools Protocol is available on the given port.

    Args:
        cdp_port: Chrome DevTools Protocol port number

    Returns:
        True if CDP is available, False otherwise
    """
    try:
        with urllib.request.urlopen(
            f"http://localhost:{cdp_port}/json/version", timeout=CDP_CHECK_TIMEOUT
        ):
            return True
    except Exception:
        return False


def is_port_in_use(port: int) -> bool:
    """Check if a TCP port is already in use by any process.

    This checks for any TCP listener on the port, regardless of whether
    it's a CDP process or not. Used for port selection before launching
    Chrome to avoid "address already in use" errors.

    Args:
        port: Port number to check

    Returns:
        True if the port is occupied by any process, False otherwise
    """
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(("localhost", port))
            return result == 0  # Port is in use if connection succeeds
    except Exception:
        return False


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


def probe_recruiter_auth(cdp_port: str) -> dict[str, Any]:
    """Probe whether the CDP browser is authenticated to LinkedIn Recruiter.

    Uses JS-based page state detection to determine authentication status
    without requiring exact URL matching. Checks for login forms, checkpoint
    pages, and recruiter shell presence.

    Args:
        cdp_port: Chrome DevTools Protocol port number

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

    # Use agent-browser to navigate to Recruiter home
    cmd = [
        "agent-browser",
        "--cdp",
        cdp_port,
        "open",
        RECRUITER_HOME_URL,
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=AUTH_PROBE_TIMEOUT)

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


def find_system_chrome() -> str | None:
    """Find the path to system Chrome executable.

    Returns:
        Path to Chrome executable, or None if not found
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chrome.app/Contents/MacOS/Chrome",
        ]
    elif system == "Windows":
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    else:  # Linux
        paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chrome",
            "/snap/bin/chromium",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]

    for path in paths:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # Try which/where command as fallback
    try:
        if system == "Windows":
            result = subprocess.run(
                ["where", "chrome"], capture_output=True, text=True, timeout=5
            )
        else:
            result = subprocess.run(
                ["which", "google-chrome"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    return None


def launch_isolated_chrome(
    user_data_dir: Path,
    cdp_port: int,
    chrome_path: str | None = None,
) -> subprocess.Popen | None:
    """Launch Chrome with isolated profile for manual login.

    Args:
        user_data_dir: Path to temporary user data directory
        cdp_port: Port for Chrome DevTools Protocol
        chrome_path: Optional path to Chrome executable (auto-detected if None)

    Returns:
        subprocess.Popen for the Chrome process, or None if launch failed
    """
    if chrome_path is None:
        chrome_path = find_system_chrome()
        if chrome_path is None:
            return None

    # Ensure user data directory exists
    user_data_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome_path,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        RECRUITER_HOME_URL,
    ]

    try:
        # Launch Chrome detached from our process group
        if platform.system() == "Windows":
            process = subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            process = subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Wait a moment for Chrome to start and CDP to become available
        deadline = time.time() + CHROME_LAUNCH_TIMEOUT
        while time.time() < deadline:
            if check_cdp_available(str(cdp_port)):
                return process
            if process.poll() is not None:
                # Chrome exited early
                return None
            time.sleep(0.5)

        # Timeout - Chrome didn't start properly
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            pass
        return None

    except Exception:
        return None


def export_auth_state(
    cdp_port: str,
    auth_file: Path,
) -> dict[str, Any]:
    """Export authentication state from CDP browser to file using official agent-browser.

    Uses: agent-browser --cdp <port> state save <auth.json>

    Args:
        cdp_port: Chrome DevTools Protocol port
        auth_file: Path to save auth state JSON

    Returns:
        Dict with export result:
        - success: bool
        - error: str | None
    """
    result = {
        "success": False,
        "error": None,
    }

    if not check_cdp_available(cdp_port):
        result["error"] = f"CDP not available on port {cdp_port}"
        return result

    try:
        # Ensure auth directory exists
        auth_file.parent.mkdir(parents=True, exist_ok=True)

        # Use official agent-browser state save command
        cmd = [
            "agent-browser",
            "--cdp",
            cdp_port,
            "state",
            "save",
            str(auth_file),
        ]

        save_result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if save_result.returncode == 0:
            # Add metadata to the saved auth file
            if auth_file.exists():
                auth_data = json.loads(auth_file.read_text())
                auth_data["exported_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                auth_data["source_url"] = RECRUITER_HOME_URL
                auth_file.write_text(json.dumps(auth_data, indent=2))

            result["success"] = True
        else:
            result["error"] = f"State save failed: {save_result.stderr}"

    except subprocess.TimeoutExpired:
        result["error"] = "Export timed out"
    except Exception as e:
        result["error"] = f"Export failed: {e}"

    return result


def close_chrome(process: subprocess.Popen, timeout: int = 5) -> bool:
    """Gracefully close Chrome process.

    Args:
        process: Chrome subprocess
        timeout: Seconds to wait for graceful shutdown

    Returns:
        True if Chrome closed, False otherwise
    """
    if process.poll() is not None:
        return True  # Already closed

    try:
        # Try graceful termination first
        process.terminate()
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        # Force kill
        try:
            process.kill()
            process.wait(timeout=2)
            return True
        except Exception:
            return False
    except Exception:
        return False


def save_browser_mode(
    work_dir: Path,
    mode: str,
    cdp_port: str | None = None,
    session_name: str | None = None,
    auth_file: str | None = None,
    headed: bool = True,
) -> None:
    """Save browser mode configuration to runtime state.

    Args:
        work_dir: Working directory for runtime data
        mode: "cdp" or "agent-browser"
        cdp_port: CDP port (for CDP mode)
        session_name: Session name (for agent-browser mode)
        auth_file: Path to auth state file
        headed: Whether browser runs in headed mode
    """
    runtime_dir = work_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    mode_file = runtime_dir / "browser_mode.json"

    mode_data = {
        "mode": mode,
        "cdp_port": cdp_port,
        "session_name": session_name,
        "auth_file": auth_file,
        "headed": headed,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    mode_file.write_text(json.dumps(mode_data, indent=2))


def start_agent_browser_session(
    auth_file: Path,
    session_name: str,
    headed: bool = True,
) -> dict[str, Any]:
    """Start an agent-browser managed session from saved auth state.

    Uses official agent-browser capabilities:
    - agent-browser --session <name> --state <auth.json> --headed open <url>

    After starting, verifies Recruiter authentication before returning success.
    Uses bounded retry to allow restored session state to settle.

    Args:
        auth_file: Path to exported auth state JSON
        session_name: Name for the managed session
        headed: Whether to run in headed mode (visible browser)

    Returns:
        Dict with session start result:
        - success: bool
        - session_name: str - name of the session
        - message: str
        - error: str | None
    """
    result = {
        "success": False,
        "session_name": session_name,
        "message": "",
        "error": None,
    }

    if not auth_file.exists():
        result["error"] = f"Auth file not found: {auth_file}"
        return result

    try:
        # Build agent-browser launch command with official flags
        cmd = [
            "agent-browser",
            "--session",
            session_name,
            "--state",
            str(auth_file),
        ]

        if headed:
            cmd.append("--headed")

        cmd.extend(["open", RECRUITER_HOME_URL])

        # Launch agent-browser session
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Phase 1: Wait for session startup to settle (watch for early exit)
        startup_deadline = time.time() + SESSION_STARTUP_MAX_WAIT
        while time.time() < startup_deadline:
            poll_result = process.poll()
            if poll_result is not None:
                # Process exited - check if clean (0) or error
                if poll_result != 0:
                    stderr = process.stderr.read().decode() if process.stderr else ""
                    result["error"] = (
                        f"agent-browser exited with code {poll_result}: {stderr}"
                    )
                    return result
                # Clean exit (0) - proceed to auth probe
                break
            time.sleep(SESSION_STARTUP_POLL_INTERVAL)

        # Phase 2: Probe Recruiter auth with bounded retry
        # Restored cookies/session may need time to settle
        last_url = "unknown"
        last_error = None

        for attempt in range(AUTH_PROBE_MAX_RETRIES):
            auth_check = probe_agent_browser_auth(session_name)

            if auth_check["authenticated"]:
                result["success"] = True
                result["message"] = f"Agent-browser session '{session_name}' started"
                return result

            # Capture last known state for error reporting
            last_url = auth_check.get("url", "unknown")
            last_error = auth_check.get("error")

            # Check if process died during probe
            poll_result = process.poll()
            if poll_result is not None and poll_result != 0:
                stderr = process.stderr.read().decode() if process.stderr else ""
                result["error"] = (
                    f"agent-browser exited during auth probe (code {poll_result}): {stderr}"
                )
                return result

            # Wait before next retry (unless this was the last attempt)
            if attempt < AUTH_PROBE_MAX_RETRIES - 1:
                time.sleep(AUTH_PROBE_RETRY_INTERVAL)

        # All retries exhausted - session never became authenticated
        error_detail = (
            f"Error: {last_error}"
            if last_error
            else "Auth probe returned not authenticated"
        )
        result["error"] = (
            f"Session started but not authenticated to Recruiter after {AUTH_PROBE_MAX_RETRIES} attempts. "
            f"URL: {last_url}, {error_detail}"
        )

    except FileNotFoundError:
        result["error"] = "agent-browser not found in PATH"
    except Exception as e:
        result["error"] = f"Failed to start agent-browser: {e}"

    return result


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


def _poll_for_authentication(
    cdp_port: str,
    chrome_process: subprocess.Popen,
    poll_interval: float = 2.0,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Poll for successful LinkedIn Recruiter authentication.

    Continuously checks if the user has completed login by probing
    the Recruiter home page. Returns immediately when authenticated
    or when Chrome closes (user cancelled).

    Args:
        cdp_port: Chrome DevTools Protocol port
        chrome_process: The Chrome subprocess to monitor
        poll_interval: Seconds between auth checks (default 2.0)
        timeout: Maximum seconds to wait for auth (default 300 = 5 min)

    Returns:
        Dict with auth status:
        - authenticated: bool - True if successfully authenticated
        - url: str | None - current URL
        - error: str | None - error message if failed
    """
    start_time = time.time()
    last_status_print = 0.0

    while time.time() - start_time < timeout:
        # Check if Chrome was closed by user (cancelled)
        if chrome_process.poll() is not None:
            return {
                "authenticated": False,
                "url": None,
                "error": "Bootstrap cancelled (Chrome closed)",
            }

        # Check for authentication
        auth_check = probe_recruiter_auth(cdp_port)

        if auth_check["authenticated"]:
            print("\nAuthentication detected!", file=sys.stderr)
            return auth_check

        # Print status update every 10 seconds
        elapsed = time.time() - start_time
        if elapsed - last_status_print >= 10.0:
            print(
                f"  Still waiting... ({int(elapsed)}s elapsed)",
                file=sys.stderr,
            )
            last_status_print = elapsed

        time.sleep(poll_interval)

    # Timeout reached
    return {
        "authenticated": False,
        "url": None,
        "error": f"Authentication timeout after {int(timeout)} seconds",
    }


def is_interactive_session() -> bool:
    """Check if running in an interactive terminal session.

    Returns:
        True if stdin is a TTY (interactive terminal), False otherwise.
        This is used to prevent accidental Chrome launches in CI/test environments.

    Note: This is a safety check but not sufficient alone - explicit opt-in
    via allow_browser_launch is required for any browser launch.
    """
    try:
        return sys.stdin.isatty()
    except (AttributeError, OSError):
        # stdin may be missing or closed in some environments
        return False


def _ensure_permission_probe(work_dir: Path) -> bool:
    """Ensure the permission probe file exists in WORK_DIR.

    This file triggers the one-time macOS permission request for WORK_DIR.
    After WORK_DIR is approved, subpaths do not need separate permission.
    Must be called before accessing subfolders like runtime/auth or chrome-profile.

    Args:
        work_dir: Working directory for runtime data

    Returns:
        True if probe was created, False if it already existed
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    probe_path = work_dir / ".permission_probe"

    if probe_path.exists():
        return False

    # Create probe file with timestamp
    probe_content = f"# Permission probe for linkedin-sourcing\n# Created: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
    probe_path.write_text(probe_content)
    return True


def _load_saved_browser_mode(work_dir: Path) -> dict[str, Any] | None:
    """Load saved browser mode from runtime state file.

    Args:
        work_dir: Working directory for runtime data

    Returns:
        Dict with browser mode data if file exists and is valid, None otherwise
    """
    mode_file = work_dir / "runtime" / "browser_mode.json"
    if not mode_file.exists():
        return None

    try:
        data = json.loads(mode_file.read_text())
        if data.get("mode") == "cdp" and data.get("cdp_port"):
            return data
        return None
    except (json.JSONDecodeError, OSError):
        return None


def bootstrap_auth_session(
    work_dir: Path,
    preferred_cdp_port: str = "9230",
    chrome_profile: Path | str | None = None,
    allow_browser_launch: bool = False,
) -> dict[str, Any]:
    """Bootstrap an authenticated browser session.

    This is the main entry point for the auth bootstrap flow:
    1. Ensure permission probe file exists at WORK_DIR root (macOS permission trigger)
    2. Check saved browser mode for existing CDP port (fallback reuse)
    3. Check if preferred CDP port is available and authenticated
    4. If yes, return success with that port
    5. If no, launch Chrome with configured profile for manual login
       (only with explicit allow_browser_launch=True AND interactive session)
    6. After user completes login, save CDP mode metadata
    7. Keep Chrome running for subsequent operations (CDP-persistent mode)

    Args:
        work_dir: Working directory for runtime data
        preferred_cdp_port: Preferred CDP port (default "9230")
        chrome_profile: Path to Chrome profile directory (default: $WORK_DIR/chrome-profile)
        allow_browser_launch: Explicit opt-in required for ANY browser launch.
            Must be True AND running in interactive session to launch browsers.
            Default False ensures tests/CI cannot accidentally launch Chrome.

    Returns:
        Dict with bootstrap result:
        - success: bool
        - mode: "cdp" | "failed"
        - cdp_port: str | None - port to use for browser operations (CDP mode)
        - session_name: str | None - session name (legacy, always None now)
        - auth_file: str | None - path to exported auth state (legacy, always None now)
        - message: str - human-readable status message
        - error: str | None - error details if failed
    """
    # Step 0: Ensure permission probe file exists before any subfolder access
    # This triggers macOS permission approval at WORK_DIR root
    _ensure_permission_probe(work_dir)

    result = {
        "success": False,
        "mode": "failed",
        "cdp_port": None,
        "session_name": None,
        "auth_file": None,
        "headed": None,
        "message": "",
        "error": None,
    }

    # Step 1: Check saved browser mode for existing CDP port (fallback reuse)
    # This handles the case where bootstrap previously launched Chrome on a non-preferred port
    saved_mode = _load_saved_browser_mode(work_dir)
    if saved_mode:
        saved_port = saved_mode.get("cdp_port")
        if saved_port and check_cdp_available(saved_port):
            auth_check = probe_recruiter_auth(saved_port)
            if auth_check["authenticated"]:
                # Update timestamp on saved mode
                save_browser_mode(
                    work_dir,
                    mode="cdp",
                    cdp_port=saved_port,
                    headed=True,
                )

                result["success"] = True
                result["mode"] = "cdp"
                result["cdp_port"] = saved_port
                result["headed"] = True
                result["message"] = (
                    f"Using existing authenticated browser on saved port {saved_port}"
                )
                return result

    # Step 2: Check if preferred CDP is available and authenticated
    if check_cdp_available(preferred_cdp_port):
        auth_check = probe_recruiter_auth(preferred_cdp_port)
        if auth_check["authenticated"]:
            # Save CDP mode
            save_browser_mode(
                work_dir,
                mode="cdp",
                cdp_port=preferred_cdp_port,
                headed=True,
            )

            result["success"] = True
            result["mode"] = "cdp"
            result["cdp_port"] = preferred_cdp_port
            result["headed"] = True
            result["message"] = (
                f"Using existing authenticated browser on port {preferred_cdp_port}"
            )
            return result

    # Step 2: Check for existing auth file (legacy - no longer used for normal flow)
    # Note: Saved auth files are no longer used to start agent-browser sessions.
    # The canonical flow is now CDP-first and CDP-persistent.
    # We keep the auth file for reference but don't depend on it.

    # Step 3: Check for explicit opt-in before ANY browser launch
    if not allow_browser_launch:
        result["error"] = "Browser launch not allowed without explicit opt-in"
        result["message"] = (
            "Cannot launch Chrome for manual login without explicit opt-in. "
            "Use --bootstrap flag for explicit opt-in, or provide a pre-authenticated "
            "CDP browser on the preferred port, or a valid auth file."
        )
        return result

    # Step 4: Check for interactive session before manual login
    if not is_interactive_session():
        result["error"] = "Manual login requires an interactive terminal session"
        result["message"] = (
            "Cannot launch Chrome for manual login in non-interactive environment. "
            "Please run from an interactive terminal, or provide a pre-authenticated "
            "CDP browser on the preferred port, or a valid auth file."
        )
        return result

    # Step 5: Launch Chrome with configured profile for manual login
    chrome_path = find_system_chrome()
    if chrome_path is None:
        result["error"] = "Could not find system Chrome installation"
        result["message"] = "Chrome not found - please install Google Chrome"
        return result

    # Determine which port to use for Chrome launch
    # Prefer the user's requested port, fall back to temp port range if occupied
    preferred_port_int = int(preferred_cdp_port)
    if not is_port_in_use(preferred_port_int):
        # Preferred port is free - use it for the login browser
        actual_cdp_port = preferred_port_int
    else:
        # Preferred port is occupied - search for an available fallback port
        actual_cdp_port = 19230
        while is_port_in_use(actual_cdp_port) and actual_cdp_port < 19300:
            actual_cdp_port += 1

        if actual_cdp_port >= 19300:
            result["error"] = "Could not find available port for Chrome"
            return result

    # Use configured profile directory (persistent, not temp)
    profile_dir = (
        Path(chrome_profile) if chrome_profile else work_dir / "chrome-profile"
    )
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Launching Chrome for authentication on port {actual_cdp_port}",
        file=sys.stderr,
    )
    print(f"Profile directory: {profile_dir}", file=sys.stderr)
    print("", file=sys.stderr)
    print("=== Authentication Instructions ===", file=sys.stderr)
    print("1. A Chrome window has opened (or will open shortly)", file=sys.stderr)
    print(
        "2. Log in to LinkedIn Recruiter in that window (complete any SSO/2FA)",
        file=sys.stderr,
    )
    print(
        "3. This Chrome window will remain open and be reused for subsequent operations",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("Waiting for you to log in...", file=sys.stderr)

    # Launch Chrome
    chrome_process = launch_isolated_chrome(profile_dir, actual_cdp_port, chrome_path)

    if chrome_process is None:
        result["error"] = "Failed to launch Chrome for manual login"
        result["message"] = "Chrome launch failed - check Chrome installation"
        return result

    # Step 4: Poll for authentication (automatic, no user input required)
    auth_check = _poll_for_authentication(str(actual_cdp_port), chrome_process)
    if not auth_check["authenticated"]:
        result["error"] = (
            f"Auth check failed: {auth_check.get('error', 'Not authenticated')}"
        )
        result["message"] = "Login verification failed - please try again"
        close_chrome(chrome_process)
        return result

    # Step 5: Save browser mode as CDP (Chrome stays running)
    save_browser_mode(
        work_dir,
        mode="cdp",
        cdp_port=str(actual_cdp_port),
        headed=True,
    )

    result["success"] = True
    result["mode"] = "cdp"
    result["cdp_port"] = str(actual_cdp_port)
    result["session_name"] = None
    result["auth_file"] = None
    result["headed"] = True
    result["message"] = (
        f"Auth bootstrap complete. Chrome is running on port {actual_cdp_port} and will be reused for subsequent operations."
    )

    return result


if __name__ == "__main__":
    # Simple CLI for testing
    import argparse

    # Import runtime_manager to resolve default CHROME_PROFILE
    sys.path.insert(0, str(Path(__file__).parent))
    from runtime_manager import RuntimeManager

    parser = argparse.ArgumentParser(description="LinkedIn auth bootstrap")
    parser.add_argument(
        "--work-dir",
        default=str(Path.home() / "Desktop" / "linkedin-sourcing"),
        help="Working directory",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Probe auth status on preferred port",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Run full bootstrap flow",
    )
    parser.add_argument(
        "--cdp-port",
        default="9230",
        help="Preferred CDP port",
    )
    parser.add_argument(
        "--chrome-profile",
        default=None,
        help="Chrome profile directory (default: $WORK_DIR/chrome-profile)",
    )

    args = parser.parse_args()

    work_dir = Path(args.work_dir)

    # Resolve chrome_profile: use provided value, or get from RuntimeManager
    if args.chrome_profile:
        chrome_profile = Path(args.chrome_profile)
    else:
        # Use RuntimeManager to get the configured CHROME_PROFILE
        manager = RuntimeManager(work_dir=work_dir)
        profile = manager._resolve_profile()
        chrome_profile = Path(
            profile.get("CHROME_PROFILE", work_dir / "chrome-profile")
        )

    if args.probe:
        print(f"Probing auth on port {args.cdp_port}...")
        result = probe_recruiter_auth(args.cdp_port)
        print(json.dumps(result, indent=2))
    elif args.bootstrap:
        # CLI --bootstrap is the explicit opt-in path for browser launch
        result = bootstrap_auth_session(
            work_dir, args.cdp_port, chrome_profile, allow_browser_launch=True
        )
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
