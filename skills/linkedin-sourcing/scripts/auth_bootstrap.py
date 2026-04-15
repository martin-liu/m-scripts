#!/usr/bin/env python3
"""LinkedIn authentication bootstrap for safer auth flow.

This module provides functionality to:
1. Check if a CDP browser is authenticated to LinkedIn Recruiter
2. Launch isolated Chrome for manual login when needed
3. Export and import auth state for agent-browser managed sessions using official capabilities:
   - Export auth with `agent-browser --cdp <port> state save <auth.json>`
   - Start managed session with `agent-browser --session <name> --state <auth.json> --headed open <url>`

The auth flow:
- If configured CDP browser is reachable AND Recruiter-authenticated: use it
- Otherwise: launch temp Chrome, let user login, export auth, bootstrap agent-browser session
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


def probe_recruiter_auth(cdp_port: str) -> dict[str, Any]:
    """Probe whether the CDP browser is authenticated to LinkedIn Recruiter.

    This checks if the browser can access the Recruiter home page without
    being redirected to a login page.

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

    # Use agent-browser to navigate to Recruiter home and check result
    cmd = [
        "agent-browser",
        "--cdp",
        cdp_port,
        "open",
        RECRUITER_HOME_URL,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=AUTH_PROBE_TIMEOUT
        )

        # Get current URL after navigation
        url_cmd = ["agent-browser", "--cdp", cdp_port, "get", "url"]
        url_result = subprocess.run(url_cmd, capture_output=True, text=True, timeout=5)
        current_url = url_result.stdout.strip() if url_result.returncode == 0 else None

        # Check actual URL path, not query params like session_redirect=/talent/...
        is_authenticated = False
        if current_url:
            parsed = urlparse(current_url)
            host = parsed.netloc.lower()
            path = parsed.path.lower()
            auth_indicators = [
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
            if host.endswith("linkedin.com") and path.startswith("/talent/"):
                if not any(indicator in path for indicator in auth_indicators):
                    is_authenticated = True

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

        # Wait a moment for session to initialize
        time.sleep(2)

        # Check if process is still running or exited cleanly (returncode 0)
        poll_result = process.poll()
        if poll_result is not None and poll_result != 0:
            stderr = process.stderr.read().decode() if process.stderr else ""
            result["error"] = f"agent-browser exited with code {poll_result}: {stderr}"
            return result

        # CRITICAL: Verify Recruiter authentication before returning success
        # Process may be running but session might not be authenticated
        auth_check = probe_agent_browser_auth(session_name)
        if not auth_check["authenticated"]:
            current_url = auth_check.get("url", "unknown")
            error_msg = auth_check.get("error", "Not authenticated")
            result["error"] = (
                f"Session started but not authenticated to Recruiter. "
                f"URL: {current_url}, Error: {error_msg}"
            )
            return result

        result["success"] = True
        result["message"] = f"Agent-browser session '{session_name}' started"

    except FileNotFoundError:
        result["error"] = "agent-browser not found in PATH"
    except Exception as e:
        result["error"] = f"Failed to start agent-browser: {e}"

    return result


def probe_agent_browser_auth(session_name: str) -> dict[str, Any]:
    """Probe whether an agent-browser session is authenticated to LinkedIn Recruiter.

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

        # Check actual URL path for auth indicators
        is_authenticated = False
        if current_url:
            parsed = urlparse(current_url)
            host = parsed.netloc.lower()
            path = parsed.path.lower()
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
            if host.endswith("linkedin.com") and path.startswith("/talent/"):
                if not any(indicator in path for indicator in auth_indicators):
                    is_authenticated = True

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


def bootstrap_auth_session(
    work_dir: Path,
    preferred_cdp_port: str = "9230",
    chrome_profile: Path | str | None = None,
    allow_browser_launch: bool = False,
) -> dict[str, Any]:
    """Bootstrap an authenticated browser session.

    This is the main entry point for the auth bootstrap flow:
    1. Ensure permission probe file exists at WORK_DIR root (macOS permission trigger)
    2. Check if preferred CDP port is available and authenticated
    3. If yes, return success with that port
    4. If no, launch Chrome with configured profile for manual login
       (only with explicit allow_browser_launch=True AND interactive session)
    5. After user completes login, export auth state using agent-browser state save
    6. Close Chrome
    7. Start headed agent-browser session from auth.json
    8. Persist browser mode metadata

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
        - mode: "cdp" | "agent-browser" | "failed"
        - cdp_port: str | None - port to use for browser operations (CDP mode)
        - session_name: str | None - session name (agent-browser mode)
        - auth_file: str | None - path to exported auth state
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
        "message": "",
        "error": None,
    }

    # Step 1: Check if preferred CDP is available and authenticated
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
            result["message"] = (
                f"Using existing authenticated browser on port {preferred_cdp_port}"
            )
            return result

    # Step 2: Need to bootstrap - check for existing auth file
    auth_dir = work_dir / "runtime" / "auth"
    auth_file = auth_dir / "linkedin-auth.json"

    if auth_file.exists():
        # Try to validate the auth file is recent and usable
        try:
            auth_data = json.loads(auth_file.read_text())
            exported_at = auth_data.get("exported_at", "")
            # Check if auth is less than 7 days old
            if exported_at:
                from datetime import datetime, timezone

                export_time = datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - export_time).days
                if age_days < 7:
                    # CRITICAL: Starting a headed agent-browser session from saved auth
                    # requires explicit opt-in AND interactive session (same as manual login)
                    if not allow_browser_launch:
                        result["error"] = (
                            "Browser launch not allowed without explicit opt-in"
                        )
                        result["message"] = (
                            "Saved auth file exists but starting a browser session "
                            "requires allow_browser_launch=True. "
                            "Use --bootstrap flag for explicit opt-in."
                        )
                        return result

                    if not is_interactive_session():
                        result["error"] = (
                            "Browser launch requires an interactive terminal session"
                        )
                        result["message"] = (
                            "Saved auth file exists but starting a headed browser "
                            "requires an interactive terminal. "
                            "Please run from an interactive terminal."
                        )
                        return result

                    # Start agent-browser session from saved auth
                    session_name = f"linkedin-{int(time.time())}"
                    session_result = start_agent_browser_session(
                        auth_file, session_name, headed=True
                    )

                    if session_result["success"]:
                        # Save agent-browser mode
                        save_browser_mode(
                            work_dir,
                            mode="agent-browser",
                            session_name=session_name,
                            auth_file=str(auth_file),
                            headed=True,
                        )

                        result["success"] = True
                        result["mode"] = "agent-browser"
                        result["session_name"] = session_name
                        result["auth_file"] = str(auth_file)
                        result["message"] = (
                            f"Using saved auth state ({age_days} days old)"
                        )
                        return result
                    else:
                        # Session start failed, will proceed with fresh login
                        result["message"] = (
                            f"Saved auth session failed: {session_result.get('error')}"
                        )
        except Exception:
            pass  # Auth file invalid, will proceed with fresh login

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

    # Find an available port for Chrome
    temp_cdp_port = 19230
    while check_cdp_available(str(temp_cdp_port)) and temp_cdp_port < 19300:
        temp_cdp_port += 1

    if temp_cdp_port >= 19300:
        result["error"] = "Could not find available port for Chrome"
        return result

    # Use configured profile directory (persistent, not temp)
    profile_dir = (
        Path(chrome_profile) if chrome_profile else work_dir / "chrome-profile"
    )
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Launching Chrome for authentication on port {temp_cdp_port}", file=sys.stderr
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
        "3. Your authentication will be saved automatically when login completes",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("Waiting for you to log in...", file=sys.stderr)

    # Launch Chrome
    chrome_process = launch_isolated_chrome(profile_dir, temp_cdp_port, chrome_path)

    if chrome_process is None:
        result["error"] = "Failed to launch Chrome for manual login"
        result["message"] = "Chrome launch failed - check Chrome installation"
        return result

    # Step 4: Poll for authentication (automatic, no user input required)
    auth_check = _poll_for_authentication(str(temp_cdp_port), chrome_process)
    if not auth_check["authenticated"]:
        result["error"] = (
            f"Auth check failed: {auth_check.get('error', 'Not authenticated')}"
        )
        result["message"] = "Login verification failed - please try again"
        close_chrome(chrome_process)
        return result

    # Export auth state using official agent-browser state save
    export_result = export_auth_state(str(temp_cdp_port), auth_file)
    if not export_result["success"]:
        result["error"] = f"Auth export failed: {export_result.get('error')}"
        result["message"] = "Failed to save authentication state"
        close_chrome(chrome_process)
        return result

    # Step 5: Close Chrome
    close_chrome(chrome_process)

    # Step 6: Start agent-browser session from saved auth
    session_name = f"linkedin-{int(time.time())}"
    session_result = start_agent_browser_session(auth_file, session_name, headed=True)

    if not session_result["success"]:
        result["error"] = (
            f"Failed to start agent-browser session: {session_result.get('error')}"
        )
        result["message"] = "Auth saved but session start failed"
        return result

    # Step 7: Save browser mode metadata
    save_browser_mode(
        work_dir,
        mode="agent-browser",
        session_name=session_name,
        auth_file=str(auth_file),
        headed=True,
    )

    result["success"] = True
    result["mode"] = "agent-browser"
    result["session_name"] = session_name
    result["auth_file"] = str(auth_file)
    result["message"] = (
        f"Auth bootstrap complete. Session '{session_name}' started with saved auth."
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
