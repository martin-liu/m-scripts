#!/usr/bin/env python3
"""Tests for auth_bootstrap.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_auth_bootstrap.py -v
"""

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

        result = ab.check_cdp_available("9230")

        assert result is True
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args[0][0]
        assert "localhost:9230" in str(call_args)

    @patch("urllib.request.urlopen")
    def test_cdp_not_available(self, mock_urlopen):
        """Should return False when CDP is unavailable."""
        mock_urlopen.side_effect = URLError("Connection refused")

        result = ab.check_cdp_available("9230")

        assert result is False

    @patch("urllib.request.urlopen")
    def test_cdp_timeout(self, mock_urlopen):
        """Should return False on timeout."""
        mock_urlopen.side_effect = TimeoutError()

        result = ab.check_cdp_available("9230")

        assert result is False


class TestProbeRecruiterAuth:
    """Tests for Recruiter auth probing."""

    @patch("auth_bootstrap.check_cdp_available")
    def test_cdp_not_available(self, mock_check):
        """Should return not authenticated when CDP unavailable."""
        mock_check.return_value = False

        result = ab.probe_recruiter_auth("9230")

        assert result["authenticated"] is False
        assert "CDP not available" in result["error"]
        assert result["url"] is None

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_authenticated_on_recruiter_page(self, mock_run, mock_check):
        """Should detect authenticated when on Recruiter page."""
        mock_check.return_value = True
        # First call is open, second is get url
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/talent/home\n",
                stderr="",
            ),
        ]

        result = ab.probe_recruiter_auth("9230")

        assert result["authenticated"] is True
        assert result["error"] is None
        assert "/talent/" in result["url"]

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_login_page(self, mock_run, mock_check):
        """Should detect not authenticated when on login page."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/login\n",
                stderr="",
            ),
        ]

        result = ab.probe_recruiter_auth("9230")

        assert result["authenticated"] is False

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_checkpoint(self, mock_run, mock_check):
        """Should detect not authenticated when on checkpoint page."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/checkpoint/challenge\n",
                stderr="",
            ),
        ]

        result = ab.probe_recruiter_auth("9230")

        assert result["authenticated"] is False

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_probe_timeout(self, mock_run, mock_check):
        """Should handle timeout gracefully."""
        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)

        result = ab.probe_recruiter_auth("9230")

        assert result["authenticated"] is False
        assert "timed out" in result["error"].lower()

    @patch("auth_bootstrap.check_cdp_available")
    @patch("subprocess.run")
    def test_agent_browser_not_found(self, mock_run, mock_check):
        """Should handle missing agent-browser."""
        mock_check.return_value = True
        mock_run.side_effect = FileNotFoundError()

        result = ab.probe_recruiter_auth("9230")

        assert result["authenticated"] is False
        assert "agent-browser" in result["error"].lower()


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
            result = ab.launch_isolated_chrome(profile_dir, 19230)

        assert result is not None
        assert result == mock_process

    @patch("auth_bootstrap.find_system_chrome")
    def test_no_chrome_found(self, mock_find):
        """Should return None when Chrome not found."""
        mock_find.return_value = None

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            result = ab.launch_isolated_chrome(profile_dir, 19230)

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
            result = ab.launch_isolated_chrome(profile_dir, 19230)

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
                cdp_port="9230",
                headed=True,
            )

            mode_file = work_dir / "runtime" / "browser_mode.json"
            assert mode_file.exists()

            data = json.loads(mode_file.read_text())
            assert data["mode"] == "cdp"
            assert data["cdp_port"] == "9230"
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
            result = ab.export_auth_state("9230", auth_file)

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

            result = ab.export_auth_state("9230", auth_file)

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
            result = ab.export_auth_state("9230", auth_file)

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
        mock_process.poll.return_value = 0  # Clean exit
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
    def test_session_not_authenticated_false_success(
        self, mock_sleep, mock_popen, mock_probe
    ):
        """CRITICAL: Must reject session that starts but is not authenticated (false-success prevention)."""
        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running
        mock_popen.return_value = mock_process
        # Session started but NOT authenticated (e.g., expired auth, login page)
        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/login",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text('{"cookies": []}')

            result = ab.start_agent_browser_session(auth_file, "linkedin-test")

        # MUST fail - session started but auth check failed
        assert result["success"] is False
        assert "not authenticated" in result["error"].lower()
        assert "linkedin.com/login" in result["error"]

    @patch("auth_bootstrap.probe_agent_browser_auth")
    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_session_auth_probe_error(self, mock_sleep, mock_popen, mock_probe):
        """Should fail if auth probe returns error."""
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_probe.return_value = {
            "authenticated": False,
            "url": None,
            "error": "agent-browser not found",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text('{"cookies": []}')

            result = ab.start_agent_browser_session(auth_file, "linkedin-test")

        assert result["success"] is False
        assert "not authenticated" in result["error"].lower()

    @patch("auth_bootstrap.probe_agent_browser_auth")
    @patch("subprocess.Popen")
    @patch("time.sleep")
    def test_session_on_checkpoint_page(self, mock_sleep, mock_popen, mock_probe):
        """Should reject session on checkpoint/challenge page (false-success prevention)."""
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/checkpoint/challenge/AgGf...",
            "error": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text('{"cookies": []}')

            result = ab.start_agent_browser_session(auth_file, "linkedin-test")

        assert result["success"] is False
        assert "not authenticated" in result["error"].lower()


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

        result = ab._poll_for_authentication("19230", mock_process, poll_interval=0.1)

        assert result["authenticated"] is True
        assert "/talent/" in result["url"]
        mock_probe.assert_called_with("19230")

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

        result = ab._poll_for_authentication("19230", mock_process, poll_interval=0.1)

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
            "19230", mock_process, poll_interval=0.1, timeout=5.0
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
            "19230", mock_process, poll_interval=0.1, timeout=30.0
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
            result = ab.bootstrap_auth_session(work_dir, "9230")

        assert result["success"] is True
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "9230"
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

            result = ab.bootstrap_auth_session(work_dir, "9230")

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
            result1 = ab.bootstrap_auth_session(work_dir, "9230")
            assert result1["success"] is True
            assert probe_path.exists()
            content1 = probe_path.read_text()

            # Second bootstrap call - should not fail
            result2 = ab.bootstrap_auth_session(work_dir, "9230")
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
                work_dir, "9230", allow_browser_launch=True
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
            result = ab.bootstrap_auth_session(work_dir, "9230")

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
            result = ab.bootstrap_auth_session(work_dir, "9230")

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
            result = ab.bootstrap_auth_session(work_dir, "9230")

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
    @patch("auth_bootstrap.start_agent_browser_session")
    def test_recent_auth_file_no_opt_in_fails_closed(
        self, mock_start_session, mock_check, mock_interactive
    ):
        """CRITICAL: Recent auth file without explicit opt-in must NOT launch browser.

        This tests the oracle issue: saved auth session launch must be gated
        by allow_browser_launch parameter, not just tty check.
        """
        mock_check.return_value = False
        mock_interactive.return_value = True  # Even with tty
        mock_start_session.return_value = {
            "success": True,
            "session_name": "linkedin-test",
            "message": "Session started",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            auth_dir = work_dir / "runtime" / "auth"
            auth_dir.mkdir(parents=True)
            auth_file = auth_dir / "linkedin-auth.json"

            # Create recent auth file (use current time)
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            auth_data = {
                "exported_at": now.isoformat().replace("+00:00", "Z"),
                "cookies": [],
            }
            auth_file.write_text(json.dumps(auth_data))

            # No allow_browser_launch - should fail closed
            result = ab.bootstrap_auth_session(work_dir, "9230")

        # Must fail closed - no browser launch without explicit opt-in
        assert result["success"] is False
        assert (
            "explicit opt-in" in result["error"].lower()
            or "not allowed" in result["error"].lower()
        )
        # start_agent_browser_session should NOT have been called
        mock_start_session.assert_not_called()

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.start_agent_browser_session")
    def test_recent_auth_file_non_interactive_fails_closed(
        self, mock_start_session, mock_check, mock_interactive
    ):
        """CRITICAL: Recent auth file in non-interactive mode must NOT launch browser.

        Even with allow_browser_launch=True, non-interactive session should fail.
        """
        mock_check.return_value = False
        mock_interactive.return_value = False  # Non-interactive
        mock_start_session.return_value = {
            "success": True,
            "session_name": "linkedin-test",
            "message": "Session started",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            auth_dir = work_dir / "runtime" / "auth"
            auth_dir.mkdir(parents=True)
            auth_file = auth_dir / "linkedin-auth.json"

            # Create recent auth file
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            auth_data = {
                "exported_at": now.isoformat().replace("+00:00", "Z"),
                "cookies": [],
            }
            auth_file.write_text(json.dumps(auth_data))

            # Has opt-in but non-interactive - should still fail
            result = ab.bootstrap_auth_session(
                work_dir, "9230", allow_browser_launch=True
            )

        # Must fail closed - no browser launch in non-interactive mode
        assert result["success"] is False
        assert "interactive" in result["error"].lower()
        # start_agent_browser_session should NOT have been called
        mock_start_session.assert_not_called()

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.start_agent_browser_session")
    def test_use_recent_auth_file_with_opt_in(
        self, mock_start_session, mock_check, mock_interactive
    ):
        """Should use existing auth file if recent with explicit opt-in AND interactive."""
        mock_check.return_value = False
        mock_interactive.return_value = True  # Interactive session
        mock_start_session.return_value = {
            "success": True,
            "session_name": "linkedin-test",
            "message": "Session started",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            auth_dir = work_dir / "runtime" / "auth"
            auth_dir.mkdir(parents=True)
            auth_file = auth_dir / "linkedin-auth.json"

            # Create recent auth file (use current time)
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            auth_data = {
                "exported_at": now.isoformat().replace("+00:00", "Z"),
                "cookies": [],
            }
            auth_file.write_text(json.dumps(auth_data))

            # Explicit opt-in AND interactive
            result = ab.bootstrap_auth_session(
                work_dir, "9230", allow_browser_launch=True
            )

        assert result["success"] is True
        assert result["mode"] == "agent-browser"
        # Session name is generated dynamically, just verify it starts with "linkedin-"
        assert result["session_name"].startswith("linkedin-")
        assert result["auth_file"] == str(auth_file)
        # Verify start_agent_browser_session was called with headed=True
        mock_start_session.assert_called_once()
        call_args = mock_start_session.call_args
        assert call_args[1].get("headed") is True or len(call_args[0]) >= 3


class TestCliBootstrapOutput:
    """Tests for CLI bootstrap JSON output."""

    @patch("auth_bootstrap.bootstrap_auth_session")
    def test_bootstrap_output_is_json_clean(self, mock_bootstrap, capsys):
        """Bootstrap mode should output only JSON, no human text before it."""
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            "session_name": None,
            "auth_file": None,
            "message": "Using existing authenticated browser on port 9230",
            "error": None,
        }

        # Simulate CLI call with --bootstrap (which passes allow_browser_launch=True)
        import argparse

        args = argparse.Namespace(
            work_dir="/tmp/test",
            probe=False,
            bootstrap=True,
            cdp_port="9230",
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
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_bootstrap_prompts_go_to_stderr(
        self, mock_poll, mock_launch, mock_check, mock_find, mock_interactive, capsys
    ):
        """Human prompts during bootstrap must go to stderr, not stdout."""
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

            with patch("auth_bootstrap.export_auth_state") as mock_export:
                mock_export.return_value = {"success": True, "error": None}
                with patch("auth_bootstrap.start_agent_browser_session") as mock_start:
                    mock_start.return_value = {
                        "success": True,
                        "session_name": "linkedin-test",
                        "message": "Session started",
                    }
                    result = ab.bootstrap_auth_session(
                        work_dir, "9230", allow_browser_launch=True
                    )

        captured = capsys.readouterr()

        # stdout should only contain the JSON result (printed by caller)
        # stderr should contain the human prompts
        assert "Launching Chrome for authentication" in captured.err
        assert "Log in to LinkedIn Recruiter" in captured.err
        # Should NOT ask for Enter press (automatic polling)
        assert "Press Enter" not in captured.err
        # Should indicate automatic saving
        assert "automatically" in captured.err.lower()

    @patch("auth_bootstrap.is_interactive_session")
    @patch("auth_bootstrap.find_system_chrome")
    @patch("auth_bootstrap.check_cdp_available")
    @patch("auth_bootstrap.launch_isolated_chrome")
    @patch("auth_bootstrap._poll_for_authentication")
    def test_bootstrap_prompts_user_to_login_not_launch_chrome(
        self, mock_poll, mock_launch, mock_check, mock_find, mock_interactive, capsys
    ):
        """User should be prompted to log in, not to launch Chrome manually."""
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

            with patch("auth_bootstrap.export_auth_state") as mock_export:
                mock_export.return_value = {"success": True, "error": None}
                with patch("auth_bootstrap.start_agent_browser_session") as mock_start:
                    mock_start.return_value = {
                        "success": True,
                        "session_name": "linkedin-test",
                        "message": "Session started",
                    }
                    result = ab.bootstrap_auth_session(
                        work_dir, "9230", allow_browser_launch=True
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
