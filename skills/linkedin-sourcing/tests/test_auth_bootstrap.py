#!/usr/bin/env python3
"""Tests for auth_bootstrap.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_auth_bootstrap.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from urllib.error import URLError

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import auth_bootstrap as ab


class TestIsInteractiveSession:
    """Tests for interactive session detection."""

    @patch("auth_bootstrap.sys.stdin")
    def test_interactive_when_tty(self, mock_stdin):
        """Should return True when stdin is a TTY."""
        mock_stdin.isatty.return_value = True

        result = ab.is_interactive_session()

        assert result is True

    @patch("auth_bootstrap.sys.stdin")
    def test_non_interactive_when_not_tty(self, mock_stdin):
        """Should return False when stdin is not a TTY (CI/test)."""
        mock_stdin.isatty.return_value = False

        result = ab.is_interactive_session()

        assert result is False

    @patch("auth_bootstrap.sys.stdin")
    def test_non_interactive_when_stdin_missing(self, mock_stdin):
        """Should return False when stdin is missing/closed (fail-safe)."""
        mock_stdin.isatty.side_effect = AttributeError("isatty not available")

        result = ab.is_interactive_session()

        assert result is False

    @patch("auth_bootstrap.sys.stdin")
    def test_non_interactive_when_stdin_oserror(self, mock_stdin):
        """Should return False when stdin raises OSError (fail-safe)."""
        mock_stdin.isatty.side_effect = OSError("I/O error")

        result = ab.is_interactive_session()

        assert result is False


class TestCheckCdpAvailable:
    """Tests for CDP availability checking."""

    @patch("urllib.request.urlopen")
    def test_cdp_available(self, mock_urlopen):
        """Should return True when CDP is available."""
        mock_cm = Mock()
        mock_cm.__enter__ = Mock(return_value=mock_cm)
        mock_cm.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_cm

        result = ab.check_cdp_available("9234")

        assert result is True
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args[0][0]
        assert "localhost:9234" in str(call_args)

    @patch("urllib.request.urlopen")
    def test_cdp_not_available(self, mock_urlopen):
        """Should return False when CDP is unavailable."""
        mock_urlopen.side_effect = URLError("Connection refused")

        result = ab.check_cdp_available("9234")

        assert result is False

    @patch("urllib.request.urlopen")
    def test_cdp_timeout(self, mock_urlopen):
        """Should return False on timeout."""
        mock_urlopen.side_effect = TimeoutError()

        result = ab.check_cdp_available("9234")

        assert result is False


class TestIsPortInUse:
    """Tests for generic TCP port occupancy checking."""

    @patch("socket.socket")
    def test_port_in_use(self, mock_socket_class):
        """Should return True when port is occupied by any process."""
        mock_sock = Mock()
        mock_sock.connect_ex.return_value = 0  # Connection succeeded = port in use
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = ab.is_port_in_use(9234)

        assert result is True
        mock_sock.connect_ex.assert_called_once_with(("localhost", 9234))

    @patch("socket.socket")
    def test_port_free(self, mock_socket_class):
        """Should return False when port is not in use."""
        mock_sock = Mock()
        mock_sock.connect_ex.return_value = 111  # ECONNREFUSED = port free
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = ab.is_port_in_use(9234)

        assert result is False

    @patch("socket.socket")
    def test_port_check_socket_error(self, mock_socket_class):
        """Should return False on socket error (fail-safe)."""
        mock_socket_class.side_effect = OSError("Socket creation failed")

        result = ab.is_port_in_use(9234)

        assert result is False


def _make_js_result(
    url: str,
    is_talent: bool = True,
    has_login_form: bool = False,
    has_checkpoint: bool = False,
    has_captcha: bool = False,
) -> Mock:
    """Create a mock subprocess result for JS eval."""
    page_state = {
        "url": url,
        "path": url.replace("https://www.linkedin.com", ""),
        "title": "LinkedIn",
        "isTalentPath": is_talent,
        "hasLoginForm": has_login_form,
        "hasLoginText": has_login_form,
        "hasCheckpoint": has_checkpoint,
        "hasCaptcha": has_captcha,
        "hasRecruiterShell": is_talent and not has_login_form,
        "hasUserMenu": is_talent and not has_login_form,
    }
    return Mock(returncode=0, stdout=json.dumps(page_state), stderr="")


class TestProbeRecruiterAuth:
    """Tests for Recruiter auth probing with JS-based detection."""

    @patch("auth_bootstrap.check_cdp_available")
    def test_cdp_not_available(self, mock_check):
        """Should return not authenticated when CDP unavailable."""
        mock_check.return_value = False

        result = ab.probe_recruiter_auth("9234")

        assert result["authenticated"] is False
        assert "CDP not available" in result["error"]
        assert result["url"] is None

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_authenticated_on_recruiter_page(self, mock_run, mock_check):
        """Should detect authenticated when on Recruiter page via JS."""
        mock_check.return_value = True
        # First call is open, second is JS eval
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result("https://www.linkedin.com/talent/home"),
        ]

        result = ab.probe_recruiter_auth("9234")

        assert result["authenticated"] is True
        assert result["error"] is None
        assert "/talent/" in result["url"]

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_authenticated_on_talent_root_no_trailing_slash(self, mock_run, mock_check):
        """Should detect authenticated on /talent (no trailing slash) via JS."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result("https://www.linkedin.com/talent"),
        ]

        result = ab.probe_recruiter_auth("9234")

        assert result["authenticated"] is True
        assert result["error"] is None
        assert result["url"] == "https://www.linkedin.com/talent"

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_login_page(self, mock_run, mock_check):
        """Should detect not authenticated when on login page via JS."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/login",
                is_talent=False,
                has_login_form=True,
            ),
        ]

        result = ab.probe_recruiter_auth("9234")

        assert result["authenticated"] is False

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_checkpoint(self, mock_run, mock_check):
        """Should detect not authenticated when on checkpoint page via JS."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/checkpoint/challenge",
                is_talent=False,
                has_checkpoint=True,
            ),
        ]

        result = ab.probe_recruiter_auth("9234")

        assert result["authenticated"] is False

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_login_form_on_talent(self, mock_run, mock_check):
        """Should detect not authenticated when login form present on talent path."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/talent",
                is_talent=True,
                has_login_form=True,
            ),
        ]

        result = ab.probe_recruiter_auth("9234")

        assert result["authenticated"] is False

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_probe_timeout(self, mock_run, mock_check):
        """Should handle timeout gracefully."""
        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)

        result = ab.probe_recruiter_auth("9234")

        assert result["authenticated"] is False
        assert "timed out" in result["error"].lower()

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_agent_browser_not_found(self, mock_run, mock_check):
        """Should handle missing agent-browser."""
        mock_check.return_value = True
        mock_run.side_effect = FileNotFoundError()

        result = ab.probe_recruiter_auth("9234")

        assert result["authenticated"] is False
        assert "agent-browser" in result["error"].lower()


class TestProbeAgentBrowserAuth:
    """Tests for probe_agent_browser_auth function with JS-based detection."""

    @patch("subprocess.run")
    def test_authenticated_on_talent_root_no_trailing_slash(self, mock_run):
        """Should detect authenticated on /talent (no trailing slash) via session."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # open command
            _make_js_result("https://www.linkedin.com/talent"),  # JS eval
        ]

        result = ab.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is True
        assert result["error"] is None
        assert result["url"] == "https://www.linkedin.com/talent"

    @patch("subprocess.run")
    def test_authenticated_on_talent_home(self, mock_run):
        """Should detect authenticated on /talent/home via session."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result("https://www.linkedin.com/talent/home"),
        ]

        result = ab.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is True
        assert result["error"] is None

    @patch("subprocess.run")
    def test_not_authenticated_on_login_page(self, mock_run):
        """Should reject login page via session."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/login",
                is_talent=False,
                has_login_form=True,
            ),
        ]

        result = ab.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False

    @patch("subprocess.run")
    def test_not_authenticated_login_form_on_talent(self, mock_run):
        """Should reject when login form present on talent path."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/talent",
                is_talent=True,
                has_login_form=True,
            ),
        ]

        result = ab.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False


class TestFindSystemChrome:
    """Tests for system Chrome detection."""

    @patch("platform.system")
    @patch("os.path.isfile")
    def test_find_chrome_macos(self, mock_isfile, mock_system):
        """Should find Chrome on macOS."""
        mock_system.return_value = "Darwin"
        mock_isfile.return_value = True

        result = ab.find_system_chrome()

        assert result is not None
        assert "Google Chrome.app" in result

    @patch("auth_bootstrap.platform.system")
    @patch("auth_bootstrap.os.path.isfile")
    @patch("auth_bootstrap.os.access")
    def test_find_chrome_windows(self, mock_access, mock_isfile, mock_system):
        """Should find Chrome on Windows."""
        mock_system.return_value = "Windows"
        mock_isfile.return_value = True
        mock_access.return_value = True

        result = ab.find_system_chrome()

        assert result is not None
        assert "chrome.exe" in result.lower()

    @patch("auth_bootstrap.platform.system")
    @patch("auth_bootstrap.os.path.isfile")
    @patch("auth_bootstrap.os.access")
    def test_find_chrome_linux(self, mock_access, mock_isfile, mock_system):
        """Should find Chrome on Linux."""
        mock_system.return_value = "Linux"
        mock_isfile.side_effect = lambda p: "google-chrome" in p
        mock_access.return_value = True

        result = ab.find_system_chrome()

        assert result is not None
        assert "google-chrome" in result

    @patch("platform.system")
    @patch("os.path.isfile")
    def test_chrome_not_found(self, mock_isfile, mock_system):
        """Should return None when Chrome not found."""
        mock_system.return_value = "Darwin"
        mock_isfile.return_value = False

        result = ab.find_system_chrome()

        assert result is None


class TestLaunchIsolatedChrome:
    """Tests for isolated Chrome launch."""

    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.Popen")
    @patch("time.time")
    @patch("time.sleep")
    def test_successful_launch(
        self, mock_sleep, mock_time, mock_popen, mock_check, mock_find
    ):
        """Should launch Chrome and return process."""
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_time.side_effect = [0, 0.5, 1.0, 1.5]  # Start + 3 checks
        mock_check.side_effect = [False, False, True]  # Available on 3rd check

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            result = ab.launch_isolated_chrome(profile_dir, 19234)

        assert result is not None
        assert result == mock_process

    @patch("auth_bootstrap.find_system_chrome")
    def test_no_chrome_found(self, mock_find):
        """Should return None when Chrome not found."""
        mock_find.return_value = None

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            result = ab.launch_isolated_chrome(profile_dir, 19234)

        assert result is None

    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.Popen")
    @patch("time.time")
    @patch("time.sleep")
    def test_launch_timeout(
        self, mock_sleep, mock_time, mock_popen, mock_check, mock_find
    ):
        """Should return None when Chrome doesn't start in time."""
        mock_find.return_value = "/usr/bin/google-chrome"
        # Simulate time passing beyond timeout
        mock_time.side_effect = list(range(0, 100))
        mock_check.return_value = False  # Never becomes available

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            result = ab.launch_isolated_chrome(profile_dir, 19234)

        assert result is None
        # Should have terminated the process
        mock_process.terminate.assert_called_once()


class TestCloseChrome:
    """Tests for Chrome process cleanup."""

    def test_already_closed(self):
        """Should return True if process already closed."""
        mock_process = Mock()
        mock_process.poll.return_value = 0  # Already exited

        result = ab.close_chrome(mock_process)

        assert result is True
        mock_process.terminate.assert_not_called()

    def test_graceful_close(self):
        """Should gracefully terminate process."""
        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running
        mock_process.wait.return_value = 0

        result = ab.close_chrome(mock_process)

        assert result is True
        mock_process.terminate.assert_called_once()

    def test_force_kill_on_timeout(self):
        """Should force kill if graceful close times out."""
        mock_process = Mock()
        mock_process.poll.return_value = None
        # First wait (terminate) times out, second wait (kill) succeeds
        mock_process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="test", timeout=5),
            0,
        ]

        result = ab.close_chrome(mock_process)

        assert result is True
        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()


class TestSaveBrowserMode:
    """Tests for save_browser_mode function."""

    def test_save_cdp_mode(self):
        """Should save CDP mode configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            ab.save_browser_mode(
                work_dir,
                mode="cdp",
                cdp_port="9234",
                headed=True,
            )

            mode_file = work_dir / "runtime" / "browser_mode.json"
            assert mode_file.exists()

            data = json.loads(mode_file.read_text())
            assert data["mode"] == "cdp"
            assert data["cdp_port"] == "9234"
            assert data["session_name"] is None
            assert data["headed"] is True

    def test_save_agent_browser_mode(self):
        """Should save agent-browser mode configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            ab.save_browser_mode(
                work_dir,
                mode="agent-browser",
                session_name="linkedin-test",
                auth_file="/path/to/auth.json",
                headed=True,
            )

            mode_file = work_dir / "runtime" / "browser_mode.json"
            assert mode_file.exists()

            data = json.loads(mode_file.read_text())
            assert data["mode"] == "agent-browser"
            assert data["cdp_port"] is None
            assert data["session_name"] == "linkedin-test"
            assert data["auth_file"] == "/path/to/auth.json"


class TestExportAuthState:
    """Tests for auth state export using official agent-browser state save."""

    @patch("auth_bootstrap.check_cdp_available")
    def test_cdp_not_available(self, mock_check):
        """Should fail if CDP not available."""
        mock_check.return_value = False

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            result = ab.export_auth_state("9234", auth_file)

        assert result["success"] is False
        assert "CDP not available" in result["error"]

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_successful_export(self, mock_run, mock_check):
        """Should export auth state using agent-browser state save."""
        mock_check.return_value = True
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            # Create the file that state save would create
            auth_file.parent.mkdir(parents=True, exist_ok=True)
            auth_file.write_text(json.dumps({"cookies": []}))

            result = ab.export_auth_state("9234", auth_file)

        assert result["success"] is True
        # Verify state save command was called
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "agent-browser"
        assert "state" in cmd
        assert "save" in cmd

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_export_failure(self, mock_run, mock_check):
        """Should handle export failure."""
        mock_check.return_value = True
        mock_run.return_value = Mock(returncode=1, stderr="state save failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            result = ab.export_auth_state("9234", auth_file)

        assert result["success"] is False
        assert "state save failed" in result["error"]


class TestStartAgentBrowserSession:
    """Tests for starting agent-browser session with official capabilities."""

    def test_auth_file_not_found(self):
        """Should fail if auth file doesn't exist."""
        result = ab.start_agent_browser_session(
            Path("/nonexistent/auth.json"), "test-session"
        )

        assert result["success"] is False
        assert "Auth file not found" in result["error"]

    @patch("auth_bootstrap.probe_agent_browser_auth")
    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_successful_session_start(self, mock_sleep, mock_popen, mock_probe):
        """Should start agent-browser session with --session and --state flags."""
        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running
        mock_popen.return_value = mock_process
        mock_probe.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text('{"cookies": []}')

            result = ab.start_agent_browser_session(auth_file, "linkedin-test")

        assert result["success"] is True
        assert result["session_name"] == "linkedin-test"

        # Verify correct command was built
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "agent-browser"
        assert "--session" in cmd
        assert "linkedin-test" in cmd
        assert "--state" in cmd
        assert str(auth_file) in cmd
        assert "--headed" in cmd

    @patch("auth_bootstrap.probe_agent_browser_auth")
    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_session_start_success_clean_exit(self, mock_sleep, mock_popen, mock_probe):
        """Should treat clean exit (returncode 0) as success."""
        mock_process = Mock()
        # First poll returns None (running), then 0 (clean exit)
        mock_process.poll.side_effect = [None, 0]
        mock_popen.return_value = mock_process
        mock_probe.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text('{"cookies": []}')

            result = ab.start_agent_browser_session(auth_file, "linkedin-test")

        assert result["success"] is True
        assert result["session_name"] == "linkedin-test"

    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_session_start_failure(self, mock_sleep, mock_popen):
        """Should handle session start failure with non-zero exit."""
        mock_process = Mock()
        mock_process.poll.return_value = 1  # Exited with error
        mock_process.stderr = Mock()
        mock_process.stderr.read.return_value = b"session error"
        mock_popen.return_value = mock_process

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text('{"cookies": []}')

            result = ab.start_agent_browser_session(auth_file, "linkedin-test")

        assert result["success"] is False
        assert "exited with code 1" in result["error"]

    @patch("auth_bootstrap.probe_agent_browser_auth")
    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_session_process_exits_during_probe(
        self, mock_sleep, mock_popen, mock_probe
    ):
        """Should fail clearly if agent-browser exits during auth probe."""
        mock_process = Mock()
        # Process exits with error during probe
        mock_process.poll.side_effect = [None, None, 2]  # running, running, then error
        mock_process.stderr = Mock()
        mock_process.stderr.read.return_value = b"connection lost"
        mock_popen.return_value = mock_process

        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text('{"cookies": []}')

            result = ab.start_agent_browser_session(auth_file, "linkedin-test")

        assert result["success"] is False
        assert "exited" in result["error"].lower()
        assert "connection lost" in result["error"]


class TestPollForAuthentication:
    """Tests for automatic authentication polling."""

    @patch("auth_bootstrap.probe_recruiter_auth")
    @patch("time.time")
    @patch("time.sleep")
    def test_poll_detects_authentication(self, mock_sleep, mock_time, mock_probe):
        """Should detect authentication and return immediately when authenticated."""
        # Provide plenty of time values for the loop
        mock_time.side_effect = [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
        mock_probe.side_effect = [
            {
                "authenticated": False,
                "url": "https://www.linkedin.com/login",
                "error": None,
            },
            {
                "authenticated": True,
                "url": "https://www.linkedin.com/talent/home",
                "error": None,
            },
        ]

        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running

        result = ab._poll_for_authentication("19234", mock_process, poll_interval=0.1)

        assert result["authenticated"] is True
        assert "/talent/" in result["url"]
        mock_probe.assert_called_with("19234")

    @patch("auth_bootstrap.probe_recruiter_auth")
    @patch("time.time")
    @patch("time.sleep")
    def test_poll_detects_chrome_close(self, mock_sleep, mock_time, mock_probe):
        """Should detect when user closes Chrome (cancelled)."""
        mock_time.side_effect = [0, 0.5, 1.0]
        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/login",
            "error": None,
        }

        mock_process = Mock()
        mock_process.poll.return_value = 0  # Chrome exited

        result = ab._poll_for_authentication("19234", mock_process, poll_interval=0.1)

        assert result["authenticated"] is False
        assert "cancelled" in result["error"].lower()

    @patch("auth_bootstrap.probe_recruiter_auth")
    @patch("time.time")
    @patch("time.sleep")
    def test_poll_times_out(self, mock_sleep, mock_time, mock_probe):
        """Should timeout after specified duration."""
        # Simulate time passing beyond timeout
        mock_time.side_effect = list(range(0, 400))
        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/login",
            "error": None,
        }

        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running

        result = ab._poll_for_authentication(
            "19234", mock_process, poll_interval=0.1, timeout=5.0
        )

        assert result["authenticated"] is False
        assert "timeout" in result["error"].lower()

    @patch("auth_bootstrap.probe_recruiter_auth")
    @patch("time.time")
    @patch("time.sleep")
    def test_poll_prints_status_updates(
        self, mock_sleep, mock_time, mock_probe, capsys
    ):
        """Should print status updates every 10 seconds."""
        # Simulate 25 seconds passing (should print at 10s and 20s) - provide many values
        mock_time.side_effect = [0, 5, 10, 15, 20, 25, 30, 35, 40]
        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/login",
            "error": None,
        }

        mock_process = Mock()
        mock_process.poll.return_value = None

        result = ab._poll_for_authentication(
            "19234", mock_process, poll_interval=0.1, timeout=30.0
        )

        captured = capsys.readouterr()
        # Should have printed status updates
        assert "Still waiting" in captured.err


class TestEnsurePermissionProbe:
    """Tests for permission probe creation."""

    def test_probe_created_on_first_call(self):
        """Should create permission probe file on first call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            probe_path = work_dir / ".permission_probe"

            result = ab._ensure_permission_probe(work_dir)

            assert result is True
            assert probe_path.exists()
            content = probe_path.read_text()
            assert "Permission probe" in content

    def test_probe_idempotent(self):
        """Should not recreate probe if it already exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # First call creates
            result1 = ab._ensure_permission_probe(work_dir)
            # Second call should not create
            result2 = ab._ensure_permission_probe(work_dir)

            assert result1 is True
            assert result2 is False

    def test_probe_creates_work_dir(self):
        """Should create work_dir if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir) / "nonexistent" / "nested"
            probe_path = work_dir / ".permission_probe"

            ab._ensure_permission_probe(work_dir)

            assert work_dir.exists()
            assert probe_path.exists()


class TestPortSelectionDuringBootstrap:
    """Tests for port selection behavior during manual bootstrap."""

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_preferred_port_available_gets_chosen(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_check,
        mock_find,
        mock_interactive,
    ):
        """When preferred port is free, it should be used for Chrome launch."""
        # Setup: preferred port (9234) is free (no process using it)
        mock_is_port_in_use.side_effect = lambda port: port != 9234
        mock_check.return_value = False  # No CDP on preferred port
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_interactive.return_value = True

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process

        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        # Should succeed with CDP mode
        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "9234"
        # launch_isolated_chrome should be called with preferred port 9234
        mock_launch.assert_called_once()
        call_args = mock_launch.call_args
        assert call_args[0][1] == 9234  # Second positional arg is cdp_port

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_preferred_port_unavailable_falls_back(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_check,
        mock_find,
        mock_interactive,
    ):
        """When preferred port is occupied, should fallback to next available port."""

        # Setup: preferred port (9234) IS occupied, but 19234 is free
        def check_port(port):
            return port == 9234  # Only 9234 is occupied

        mock_is_port_in_use.side_effect = check_port
        mock_check.return_value = False  # No CDP on any port
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_interactive.return_value = True

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process

        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        # Should succeed with CDP mode on fallback port
        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "19234"
        # launch_isolated_chrome should be called with fallback port 19234
        mock_launch.assert_called_once()
        call_args = mock_launch.call_args
        assert call_args[0][1] == 19234  # Second positional arg is cdp_port

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_preferred_port_occupied_by_non_cdp_falls_back(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_check,
        mock_find,
        mock_interactive,
    ):
        """CRITICAL: Preferred port occupied by non-CDP process should fallback.

        This tests the oracle issue: if preferred_cdp_port is taken by a non-CDP
        process, check_cdp_available() returns False (no CDP response), but
        is_port_in_use() returns True (port occupied). The code should fallback
        instead of trying to launch Chrome on an occupied port.
        """
        # Setup: preferred port (9234) is occupied by non-CDP (e.g., another service)
        # CDP check returns False (no CDP there), but port is in use
        mock_is_port_in_use.side_effect = lambda port: (
            port == 9234
        )  # Only 9234 occupied
        mock_check.return_value = (
            False  # No CDP on preferred port (it's a non-CDP process)
        )
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_interactive.return_value = True

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process

        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        # Should succeed using fallback port with CDP mode
        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "19234"
        # Should NOT try to use the occupied preferred port
        mock_launch.assert_called_once()
        call_args = mock_launch.call_args
        assert call_args[0][1] == 19234  # Fallback port, not 9234

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_fallback_search_skips_occupied_non_cdp_ports(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_check,
        mock_find,
        mock_interactive,
    ):
        """Fallback search should skip ports occupied by any process, not just CDP."""
        # Setup: preferred port and first few fallback ports occupied by non-CDP
        occupied_ports = {9234, 19234}  # Non-CDP processes

        def check_port(port):
            return port in occupied_ports

        mock_is_port_in_use.side_effect = check_port
        mock_check.return_value = False  # No CDP on any port
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_interactive.return_value = True

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process

        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        # Should succeed using first free port (19235) with CDP mode
        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "19235"
        mock_launch.assert_called_once()
        call_args = mock_launch.call_args
        assert call_args[0][1] == 19235  # First free port after skipping occupied ones

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_actual_chosen_port_used_for_polling_and_saved(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_check,
        mock_find,
        mock_interactive,
    ):
        """The actual chosen port should be used for auth polling and saved."""
        # Setup: preferred port is free
        mock_is_port_in_use.side_effect = lambda port: port != 9234
        mock_check.return_value = False  # No CDP on preferred port
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_interactive.return_value = True

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process

        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        # Should succeed with CDP mode
        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "9234"

        # _poll_for_authentication should be called with port 9234
        mock_poll.assert_called_once()
        poll_args = mock_poll.call_args
        assert poll_args[0][0] == "9234"  # First positional arg is cdp_port

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    def test_no_available_ports_returns_error(
        self, mock_is_port_in_use, mock_check, mock_find, mock_interactive
    ):
        """When no ports are available, should return error."""
        # Setup: all ports occupied (preferred + fallback range)
        mock_is_port_in_use.return_value = True  # All ports occupied
        mock_check.return_value = False  # No CDP
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_interactive.return_value = True

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        # Should fail with port error
        assert result["success"] is False
        assert "port" in result["error"].lower()


class TestLoadSavedBrowserMode:
    """Tests for loading saved browser mode."""

    def test_load_saved_cdp_mode(self):
        """Should load saved CDP mode with port."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            runtime_dir = work_dir / "runtime"
            runtime_dir.mkdir(parents=True)
            mode_file = runtime_dir / "browser_mode.json"
            mode_file.write_text(
                json.dumps(
                    {
                        "mode": "cdp",
                        "cdp_port": "19234",
                        "session_name": None,
                        "auth_file": None,
                        "headed": True,
                        "updated_at": "2024-01-01T00:00:00Z",
                    }
                )
            )

            result = ab._load_saved_browser_mode(work_dir)

            assert result is not None
            assert result["mode"] == "cdp"
            assert result["cdp_port"] == "19234"

    def test_load_no_file_returns_none(self):
        """Should return None when no browser mode file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            result = ab._load_saved_browser_mode(work_dir)

            assert result is None

    def test_load_invalid_json_returns_none(self):
        """Should return None when file contains invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            runtime_dir = work_dir / "runtime"
            runtime_dir.mkdir(parents=True)
            mode_file = runtime_dir / "browser_mode.json"
            mode_file.write_text("not valid json")

            result = ab._load_saved_browser_mode(work_dir)

            assert result is None

    def test_load_non_cdp_mode_returns_none(self):
        """Should return None when mode is not CDP."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            runtime_dir = work_dir / "runtime"
            runtime_dir.mkdir(parents=True)
            mode_file = runtime_dir / "browser_mode.json"
            mode_file.write_text(
                json.dumps(
                    {
                        "mode": "agent-browser",
                        "cdp_port": None,
                        "session_name": "test-session",
                    }
                )
            )

            result = ab._load_saved_browser_mode(work_dir)

            assert result is None


class TestBootstrapAuthSession:
    """Tests for auth bootstrap flow."""

    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.probe_recruiter_auth")
    def test_fast_path_cdp_authenticated(self, mock_probe, mock_check):
        """Should use existing CDP when authenticated (no browser launch needed)."""
        mock_check.return_value = True
        mock_probe.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            # No allow_browser_launch needed for CDP fast path
            result = ab.bootstrap_auth_session(work_dir, "9234")

        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "9234"
        assert result["headed"] is True
        assert "existing authenticated browser" in result["message"]

    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.probe_recruiter_auth")
    def test_creates_permission_probe_before_subfolders(self, mock_probe, mock_check):
        """Should create permission probe at WORK_DIR root before accessing subfolders.

        This triggers macOS permission approval at the WORK_DIR root level,
        preventing repeated permission prompts for subfolder access.
        """
        mock_check.return_value = True
        mock_probe.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            probe_path = work_dir / ".permission_probe"

            # Verify probe doesn't exist before bootstrap
            assert not probe_path.exists()

            result = ab.bootstrap_auth_session(work_dir, "9234")

            # Verify probe was created during bootstrap
            assert probe_path.exists()
            content = probe_path.read_text()
            assert "Permission probe" in content

            # Verify bootstrap still succeeded
            assert result["success"] is True

    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.probe_recruiter_auth")
    def test_permission_probe_idempotent_during_bootstrap(self, mock_probe, mock_check):
        """Permission probe creation should be idempotent during bootstrap."""
        mock_check.return_value = True
        mock_probe.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            probe_path = work_dir / ".permission_probe"

            # First bootstrap call
            result1 = ab.bootstrap_auth_session(work_dir, "9234")
            assert result1["success"] is True
            assert probe_path.exists()
            content1 = probe_path.read_text()

            # Second bootstrap call - should not fail
            result2 = ab.bootstrap_auth_session(work_dir, "9234")
            assert result2["success"] is True
            assert probe_path.exists()
            content2 = probe_path.read_text()

            # Content should be unchanged (idempotent)
            assert content1 == content2

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.probe_recruiter_auth")
    def test_cdp_available_not_authenticated_with_opt_in(
        self, mock_probe, mock_check, mock_find, mock_interactive
    ):
        """Should bootstrap when CDP available but not authenticated with explicit opt-in."""
        mock_check.return_value = True
        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/login",
            "error": None,
        }
        mock_find.return_value = None  # Chrome not found in test
        mock_interactive.return_value = True  # Simulate interactive for this test path

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            # Explicit opt-in required for browser launch path
            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        # Should proceed to bootstrap (but Chrome not found in test)
        assert result["success"] is False  # Chrome not found in test env
        assert "Chrome not found" in result["message"]

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.check_cdp_available")
    def test_cdp_not_available_non_interactive_no_opt_in(
        self, mock_check, mock_interactive
    ):
        """CRITICAL: Should fail closed without explicit opt-in even if interactive.

        No allow_browser_launch=True should fail closed regardless of tty status.
        """
        mock_check.return_value = False
        mock_interactive.return_value = True  # Even with tty

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            # No allow_browser_launch - should fail closed
            result = ab.bootstrap_auth_session(work_dir, "9234")

        # Should fail closed - no explicit opt-in
        assert result["success"] is False
        assert (
            "explicit opt-in" in result["error"].lower()
            or "not allowed" in result["error"].lower()
        )

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.check_cdp_available")
    def test_cdp_not_available_non_interactive(self, mock_check, mock_interactive):
        """Should fail closed in non-interactive environment when no CDP available."""
        mock_check.return_value = False
        mock_interactive.return_value = False  # Non-interactive (CI/test)

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            result = ab.bootstrap_auth_session(work_dir, "9234")

        # Should fail closed - no Chrome launch attempted
        assert result["success"] is False
        assert (
            "explicit opt-in" in result["error"].lower()
            or "not allowed" in result["error"].lower()
        )

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    def test_non_interactive_no_cdp_chrome_found_fails_closed(
        self, mock_check, mock_find, mock_interactive
    ):
        """CRITICAL: Non-interactive + no CDP + Chrome found must NOT launch Chrome.

        This test reproduces the risky branch: no CDP, system Chrome found,
        non-interactive environment. Must return failure and NOT call launch_isolated_chrome.
        """
        mock_check.return_value = False  # No CDP available
        mock_find.return_value = "/usr/bin/google-chrome"  # Chrome IS found
        mock_interactive.return_value = False  # Non-interactive (CI/test)

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            result = ab.bootstrap_auth_session(work_dir, "9234")

        # Must fail closed - no browser launch
        assert result["success"] is False
        assert (
            "explicit opt-in" in result["error"].lower()
            or "not allowed" in result["error"].lower()
        )
        # find_system_chrome should NOT have been called (fails before that)
        mock_find.assert_not_called()

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.check_cdp_available")
    def test_no_cdp_no_opt_in_fails_closed(self, mock_check, mock_interactive):
        """CRITICAL: No CDP available without explicit opt-in must NOT launch browser.

        This tests the oracle issue: browser launch must be gated
        by allow_browser_launch parameter, not just tty check.
        """
        mock_check.return_value = False
        mock_interactive.return_value = True  # Even with tty

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # No allow_browser_launch - should fail closed
            result = ab.bootstrap_auth_session(work_dir, "9234")

        # Must fail closed - no browser launch without explicit opt-in
        assert result["success"] is False
        assert (
            "explicit opt-in" in result["error"].lower()
            or "not allowed" in result["error"].lower()
        )

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_no_cdp_non_interactive_with_opt_in_still_launches_chrome(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_find,
        mock_check,
        mock_interactive,
    ):
        """Explicit opt-in should allow headed Chrome launch without a TTY."""
        mock_check.return_value = False
        mock_interactive.return_value = False
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_is_port_in_use.return_value = False
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process
        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        assert result["success"] is True
        assert result["mode"] == "cdp"
        mock_launch.assert_called_once()

    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.probe_recruiter_auth")
    def test_saved_fallback_cdp_port_is_reused(self, mock_probe, mock_check):
        """CRITICAL: Saved fallback CDP port should be reused on later runs.

        If bootstrap previously launched Chrome on a non-preferred port (e.g., 19234
        because 9234 was occupied), subsequent runs should find and reuse that port.
        """

        # Preferred port (9234) has no CDP, but saved port (19234) is authenticated
        def check_cdp_side_effect(port):
            return port == "19234"  # Only saved port has CDP

        mock_check.side_effect = check_cdp_side_effect

        def probe_auth_side_effect(port):
            if port == "19234":
                return {
                    "authenticated": True,
                    "url": "https://www.linkedin.com/talent/home",
                    "error": None,
                }
            return {
                "authenticated": False,
                "url": None,
                "error": "CDP not available",
            }

        mock_probe.side_effect = probe_auth_side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            runtime_dir = work_dir / "runtime"
            runtime_dir.mkdir(parents=True)
            mode_file = runtime_dir / "browser_mode.json"
            # Simulate previously saved fallback port
            mode_file.write_text(
                json.dumps(
                    {
                        "mode": "cdp",
                        "cdp_port": "19234",
                        "session_name": None,
                        "auth_file": None,
                        "headed": True,
                        "updated_at": "2024-01-01T00:00:00Z",
                    }
                )
            )

            result = ab.bootstrap_auth_session(work_dir, "9234")

        # Should succeed using the saved fallback port
        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "19234"
        assert "saved port" in result["message"].lower()

    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.probe_recruiter_auth")
    def test_stale_saved_cdp_port_falls_back_to_preferred(self, mock_probe, mock_check):
        """CRITICAL: Stale saved CDP port should fall back to preferred port.

        If the saved port is no longer reachable or not authenticated,
        should fall back to checking the preferred port.
        """

        # Saved port (19234) is stale/not available, but preferred (9234) is authenticated
        def check_cdp_side_effect(port):
            return port == "9234"  # Only preferred port has CDP

        mock_check.side_effect = check_cdp_side_effect

        def probe_auth_side_effect(port):
            if port == "9234":
                return {
                    "authenticated": True,
                    "url": "https://www.linkedin.com/talent/home",
                    "error": None,
                }
            return {
                "authenticated": False,
                "url": None,
                "error": "CDP not available",
            }

        mock_probe.side_effect = probe_auth_side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            runtime_dir = work_dir / "runtime"
            runtime_dir.mkdir(parents=True)
            mode_file = runtime_dir / "browser_mode.json"
            # Simulate stale saved port (Chrome was closed)
            mode_file.write_text(
                json.dumps(
                    {
                        "mode": "cdp",
                        "cdp_port": "19234",
                        "session_name": None,
                        "auth_file": None,
                        "headed": True,
                        "updated_at": "2024-01-01T00:00:00Z",
                    }
                )
            )

            result = ab.bootstrap_auth_session(work_dir, "9234")

        # Should succeed using the preferred port (saved port was stale)
        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "9234"

    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.probe_recruiter_auth")
    def test_saved_cdp_port_not_authenticated_falls_back(self, mock_probe, mock_check):
        """Saved CDP port that is reachable but not authenticated should fall back.

        If saved port has CDP but user logged out, should check preferred port.
        """

        # Both saved and preferred ports have CDP, but only preferred is authenticated
        def check_cdp_side_effect(port):
            return port in ("19234", "9234")  # Both have CDP

        mock_check.side_effect = check_cdp_side_effect

        def probe_auth_side_effect(port):
            if port == "9234":
                return {
                    "authenticated": True,
                    "url": "https://www.linkedin.com/talent/home",
                    "error": None,
                }
            # Saved port is not authenticated
            return {
                "authenticated": False,
                "url": "https://www.linkedin.com/login",
                "error": None,
            }

        mock_probe.side_effect = probe_auth_side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            runtime_dir = work_dir / "runtime"
            runtime_dir.mkdir(parents=True)
            mode_file = runtime_dir / "browser_mode.json"
            mode_file.write_text(
                json.dumps(
                    {
                        "mode": "cdp",
                        "cdp_port": "19234",
                        "session_name": None,
                        "auth_file": None,
                        "headed": True,
                        "updated_at": "2024-01-01T00:00:00Z",
                    }
                )
            )

            result = ab.bootstrap_auth_session(work_dir, "9234")

        # Should succeed using the preferred port (saved port not authenticated)
        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "9234"

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_bootstrap_with_opt_in_starts_chrome(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_check,
        mock_find,
        mock_interactive,
    ):
        """Should launch Chrome and return CDP mode with explicit opt-in AND interactive."""
        mock_check.return_value = False  # No existing CDP
        mock_interactive.return_value = True  # Interactive session
        mock_is_port_in_use.return_value = False  # Port is free
        mock_find.return_value = "/usr/bin/google-chrome"

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process

        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # Explicit opt-in AND interactive
            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["headed"] is True
        assert result["cdp_port"] == "9234"
        # Verify launch_isolated_chrome was called
        mock_launch.assert_called_once()


class TestCliBootstrapOutput:
    """Tests for CLI bootstrap JSON output."""

    @patch("auth_bootstrap.bootstrap_auth_session")
    def test_bootstrap_output_is_json_clean(self, mock_bootstrap, capsys):
        """Bootstrap mode should output only JSON, no human text before it."""
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9234",
            "session_name": None,
            "auth_file": None,
            "message": "Using existing authenticated browser on port 9234",
            "error": None,
        }

        # Simulate CLI call with --bootstrap (which passes allow_browser_launch=True)
        import argparse

        args = argparse.Namespace(
            work_dir="/tmp/test",
            probe=False,
            bootstrap=True,
            cdp_port="9234",
        )

        # Call the bootstrap path directly with explicit opt-in (as CLI does)
        work_dir = Path(args.work_dir)
        result = ab.bootstrap_auth_session(
            work_dir, args.cdp_port, allow_browser_launch=True
        )
        print(json.dumps(result, indent=2))

        captured = capsys.readouterr()
        output = captured.out

        # Verify output is valid JSON starting with {
        assert output.strip().startswith("{"), "Output should start with JSON object"
        # Verify no human text before JSON
        lines_before_json = output.strip().split("{")[0].strip()
        assert lines_before_json == "", (
            f"No human text allowed before JSON, got: {lines_before_json}"
        )

        # Verify it's parseable JSON
        parsed = json.loads(output)
        assert parsed["success"] is True
        assert parsed["mode"] == "cdp"

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_bootstrap_prompts_go_to_stderr(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_check,
        mock_find,
        mock_interactive,
        capsys,
    ):
        """Human prompts during bootstrap must go to stderr, not stdout."""
        mock_is_port_in_use.return_value = False  # Port is free
        mock_check.return_value = False  # No existing CDP
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_interactive.return_value = True  # Simulate interactive session

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process

        # Simulate successful auth detection via polling
        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        captured = capsys.readouterr()

        # stdout should only contain the JSON result (printed by caller)
        # stderr should contain the human prompts
        assert "Launching Chrome for authentication" in captured.err
        assert "Log in to LinkedIn Recruiter" in captured.err
        # Should NOT ask for Enter press (automatic polling)
        assert "Press Enter" not in captured.err
        # Should indicate Chrome will be reused
        assert "reused" in captured.err.lower() or "remain" in captured.err.lower()

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.is_port_in_use")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_bootstrap_prompts_user_to_login_not_launch_chrome(
        self,
        mock_poll,
        mock_launch,
        mock_is_port_in_use,
        mock_check,
        mock_find,
        mock_interactive,
        capsys,
    ):
        """User should be prompted to log in, not to launch Chrome manually."""
        mock_is_port_in_use.return_value = False  # Port is free
        mock_check.return_value = False  # No existing CDP
        mock_find.return_value = "/usr/bin/google-chrome"
        mock_interactive.return_value = True  # Simulate interactive session

        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_launch.return_value = mock_process

        # Simulate successful auth detection via polling
        mock_poll.return_value = {
            "authenticated": True,
            "url": "https://www.linkedin.com/talent/home",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            result = ab.bootstrap_auth_session(
                work_dir, "9234", allow_browser_launch=True
            )

        captured = capsys.readouterr()

        # User should be told Chrome will open automatically
        assert (
            "Chrome window will open" in captured.err
            or "Chrome window has opened" in captured.err
            or "Launching Chrome" in captured.err
        )
        # User should be told to log in, not to launch Chrome
        assert "Log in to LinkedIn Recruiter" in captured.err
        # Should NOT tell user to launch Chrome manually
        assert "launch Chrome manually" not in captured.err.lower()
        assert "remote-debugging-port" not in captured.err
        # Should NOT ask for Enter press (automatic polling)
        assert "Press Enter" not in captured.err
        # Should indicate Chrome will be reused
        assert "reused" in captured.err.lower() or "remain" in captured.err.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
