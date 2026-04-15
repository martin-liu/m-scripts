#!/usr/bin/env python3
"""Tests for browser_utils.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_browser_utils.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import browser_utils as bu


class TestCheckCdpAvailable:
    """Tests for CDP availability checking."""

    @patch("urllib.request.urlopen")
    def test_cdp_available(self, mock_urlopen):
        """Should return True when CDP is available."""
        mock_cm = Mock()
        mock_cm.__enter__ = Mock(return_value=mock_cm)
        mock_cm.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_cm

        result = bu.check_cdp_available("9230")

        assert result is True

    @patch("urllib.request.urlopen")
    def test_cdp_not_available(self, mock_urlopen):
        """Should return False when CDP is unavailable."""
        mock_urlopen.side_effect = URLError("Connection refused")

        result = bu.check_cdp_available("9230")

        assert result is False

    @patch("urllib.request.urlopen")
    def test_cdp_timeout(self, mock_urlopen):
        """Should return False on timeout."""
        mock_urlopen.side_effect = TimeoutError()

        result = bu.check_cdp_available("9230")

        assert result is False


class TestRequireCdp:
    """Tests for CDP requirement enforcement."""

    @patch("browser_utils.check_cdp_available")
    def test_cdp_available_passes(self, mock_check):
        """Should not raise when CDP is available."""
        mock_check.return_value = True

        bu.require_cdp("9230")  # Should not raise

    @patch("browser_utils.check_cdp_available")
    def test_cdp_unavailable_raises(self, mock_check):
        """Should raise RuntimeError with guidance when CDP unavailable."""
        mock_check.return_value = False

        with pytest.raises(RuntimeError) as exc_info:
            bu.require_cdp("9230")

        assert "connect_browser.sh" in str(exc_info.value)
        assert "9230" in str(exc_info.value)


class TestBrowserMode:
    """Tests for BrowserMode dataclass."""

    def test_cdp_mode(self):
        """Should create CDP mode."""
        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")

        assert mode.is_cdp() is True
        assert mode.is_agent_browser() is False
        assert mode.cdp_port == "9230"

    def test_agent_browser_mode(self):
        """Should create agent-browser mode."""
        mode = bu.BrowserMode(
            mode="agent-browser",
            session_name="linkedin-test",
            auth_file="/path/to/auth.json",
        )

        assert mode.is_cdp() is False
        assert mode.is_agent_browser() is True
        assert mode.session_name == "linkedin-test"
        assert mode.auth_file == "/path/to/auth.json"

    def test_to_dict(self):
        """Should convert to dict."""
        mode = bu.BrowserMode(
            mode="agent-browser",
            session_name="test",
            cdp_port=None,
            headed=False,
        )
        data = mode.to_dict()

        assert data["mode"] == "agent-browser"
        assert data["session_name"] == "test"
        assert data["cdp_port"] is None
        assert data["headed"] is False

    def test_from_dict(self):
        """Should create from dict."""
        data = {
            "mode": "agent-browser",
            "cdp_port": None,
            "session_name": "linkedin-test",
            "auth_file": "/auth.json",
            "headed": True,
        }
        mode = bu.BrowserMode.from_dict(data)

        assert mode.mode == "agent-browser"
        assert mode.session_name == "linkedin-test"
        assert mode.auth_file == "/auth.json"

    def test_build_agent_browser_args_cdp(self):
        """Should build CDP args."""
        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")
        args = mode.build_agent_browser_args()

        assert args == ["--cdp", "9230"]

    def test_build_agent_browser_args_session(self):
        """Should build session args."""
        mode = bu.BrowserMode(
            mode="agent-browser",
            session_name="linkedin-test",
            auth_file="/auth.json",
        )
        args = mode.build_agent_browser_args()

        assert "--session" in args
        assert "linkedin-test" in args
        assert "--state" in args
        assert "/auth.json" in args

    def test_build_agent_browser_args_cdp_missing_port(self):
        """Should raise error when CDP mode missing port."""
        mode = bu.BrowserMode(mode="cdp")

        with pytest.raises(RuntimeError) as exc_info:
            mode.build_agent_browser_args()

        assert "cdp_port" in str(exc_info.value)

    def test_build_agent_browser_args_session_missing_name(self):
        """Should raise error when session mode missing name."""
        mode = bu.BrowserMode(mode="agent-browser")

        with pytest.raises(RuntimeError) as exc_info:
            mode.build_agent_browser_args()

        assert "session_name" in str(exc_info.value)


class TestCheckBrowserAvailable:
    """Tests for check_browser_available function."""

    @patch("browser_utils.check_cdp_available")
    def test_cdp_available(self, mock_check_cdp):
        """Should return True when CDP available."""
        mock_check_cdp.return_value = True
        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")

        result = bu.check_browser_available(mode)

        assert result is True

    @patch("browser_utils.check_cdp_available")
    def test_cdp_not_available(self, mock_check_cdp):
        """Should return False when CDP not available."""
        mock_check_cdp.return_value = False
        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")

        result = bu.check_browser_available(mode)

        assert result is False

    @patch("subprocess.run")
    def test_agent_browser_available(self, mock_run):
        """Should return True when agent-browser session responds."""
        mock_run.return_value = Mock(returncode=0, stdout="https://linkedin.com")
        mode = bu.BrowserMode(mode="agent-browser", session_name="test")

        result = bu.check_browser_available(mode)

        assert result is True
        # Verify correct command was called
        cmd = mock_run.call_args[0][0]
        assert "--session" in cmd
        assert "test" in cmd

    @patch("subprocess.run")
    def test_agent_browser_not_available(self, mock_run):
        """Should return False when agent-browser session fails."""
        mock_run.return_value = Mock(returncode=1)
        mode = bu.BrowserMode(mode="agent-browser", session_name="test")

        result = bu.check_browser_available(mode)

        assert result is False


class TestCheckDialogStatus:
    """Tests for dialog status checking with mode support."""

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_no_dialog_detected(self, mock_run, mock_check):
        """Should return no dialog when none exists."""
        mock_check.return_value = True
        mock_run.return_value = Mock(
            stdout='{"exists": false}',
            stderr="",
            returncode=0,
        )

        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")
        result = bu.check_dialog_status(mode)

        assert result["has_dialog"] is False
        assert result["dialog_type"] is None
        assert result["error"] is None

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_backward_compatibility_with_string_port(self, mock_run, mock_check):
        """Should accept string cdp_port for backward compatibility."""
        mock_check.return_value = True
        mock_run.return_value = Mock(
            stdout='{"exists": false}',
            stderr="",
            returncode=0,
        )

        # Pass string directly instead of BrowserMode
        result = bu.check_dialog_status("9230")

        assert result["has_dialog"] is False
        # Verify the command was built with --cdp
        cmd = mock_run.call_args[0][0]
        assert "--cdp" in cmd
        assert "9230" in cmd

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_alert_dialog_detected(self, mock_run, mock_check):
        """Should detect alert dialog."""
        mock_check.return_value = True
        mock_run.return_value = Mock(
            stdout='{"type": "alert", "message": "Session expired"}',
            stderr="",
            returncode=0,
        )

        mode = bu.BrowserMode(mode="agent-browser", session_name="test")
        result = bu.check_dialog_status(mode)

        assert result["has_dialog"] is True
        assert result["dialog_type"] == "alert"
        assert result["message"] == "Session expired"

    @patch("browser_utils.check_browser_available")
    def test_fails_closed_when_browser_unavailable(self, mock_check):
        """Should fail closed with guidance when browser is not available."""
        mock_check.return_value = False

        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")
        result = bu.check_dialog_status(mode)

        assert result["has_dialog"] is False
        assert result["error"] is not None
        assert "connect_browser.sh" in result["error"]

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_session_mode_uses_correct_args(self, mock_run, mock_check):
        """Should use --session args in session mode."""
        mock_check.return_value = True
        mock_run.return_value = Mock(
            stdout='{"exists": false}', stderr="", returncode=0
        )

        mode = bu.BrowserMode(mode="agent-browser", session_name="linkedin-test")
        bu.check_dialog_status(mode)

        cmd = mock_run.call_args[0][0]
        assert "--session" in cmd
        assert "linkedin-test" in cmd
        assert "dialog" in cmd
        assert "status" in cmd


class TestRunBrowserCommand:
    """Tests for browser command execution with mode support."""

    @patch("browser_utils.check_browser_available")
    def test_fails_closed_when_browser_unavailable(self, mock_check):
        """Should fail closed with guidance when browser is not available."""
        mock_check.return_value = False

        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")
        result = bu.run_browser_command(mode, "eval", "some_js")

        assert result["returncode"] == -1
        assert "connect_browser.sh" in result["error"]
        assert result["timed_out"] is False

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_successful_command_cdp_mode(self, mock_run, mock_check):
        """Should parse successful command output in CDP mode."""
        mock_check.return_value = True
        mock_run.return_value = Mock(
            stdout='{"state": "ready", "count": 5}',
            stderr="",
            returncode=0,
        )

        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")
        result = bu.run_browser_command(mode, "eval", "some_js")

        assert result["returncode"] == 0
        assert result["parsed"]["state"] == "ready"
        assert result["error"] is None

        # Check the command was built correctly
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "agent-browser"
        assert "--cdp" in cmd
        assert "9230" in cmd

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_backward_compatibility_with_string_port(self, mock_run, mock_check):
        """Should accept string cdp_port for backward compatibility."""
        mock_check.return_value = True
        mock_run.return_value = Mock(
            stdout='{"state": "ready"}',
            stderr="",
            returncode=0,
        )

        # Pass string directly instead of BrowserMode
        result = bu.run_browser_command("9230", "eval", "some_js")

        assert result["returncode"] == 0
        # Check the command was built correctly with --cdp
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "agent-browser"
        assert "--cdp" in cmd
        assert "9230" in cmd

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_successful_command_session_mode(self, mock_run, mock_check):
        """Should parse successful command output in session mode."""
        mock_check.return_value = True
        mock_run.return_value = Mock(
            stdout='{"state": "ready"}',
            stderr="",
            returncode=0,
        )

        mode = bu.BrowserMode(mode="agent-browser", session_name="test")
        result = bu.run_browser_command(mode, "eval", "some_js")

        assert result["returncode"] == 0

        # Check the command was built correctly
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "agent-browser"
        assert "--session" in cmd
        assert "test" in cmd

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_timeout_with_dialog(self, mock_run, mock_check):
        """Should detect blocking dialog on timeout."""
        mock_check.return_value = True
        # First call times out, second call (dialog check) finds alert
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd=["agent-browser"], timeout=30),
            Mock(
                stdout='{"type": "alert", "message": "Please log in"}',
                stderr="",
                returncode=0,
            ),
        ]

        mode = bu.BrowserMode(mode="cdp", cdp_port="9230")
        result = bu.run_browser_command(mode, "eval", "some_js", timeout=30)

        assert result["timed_out"] is True
        assert result["dialog_info"]["has_dialog"] is True
        assert result["dialog_info"]["dialog_type"] == "alert"
        assert "alert dialog detected" in result["error"]


class TestFormatTimeoutError:
    """Tests for timeout error message formatting."""

    def test_basic_timeout_no_dialog(self):
        """Should format basic timeout message without dialog."""
        timeout_result = {
            "dialog_info": {"has_dialog": False},
        }

        result = bu.format_timeout_error("navigate to page", timeout_result)

        assert "Timeout while trying to navigate to page" in result
        assert "no blocking dialog detected" in result

    def test_timeout_with_dialog(self):
        """Should format timeout message with dialog info."""
        timeout_result = {
            "dialog_info": {
                "has_dialog": True,
                "dialog_type": "confirm",
                "message": "Are you sure?",
            },
        }

        result = bu.format_timeout_error("submit form", timeout_result)

        assert "Timeout while trying to submit form" in result
        assert "confirm dialog may be blocking progress" in result
        assert "Are you sure?" in result


class TestProbeRecruiterAuth:
    """Tests for Recruiter auth probing."""

    @patch("browser_utils.check_cdp_available")
    def test_cdp_not_available(self, mock_check):
        """Should return not authenticated when CDP unavailable."""
        mock_check.return_value = False

        result = bu.probe_recruiter_auth("9230")

        assert result["authenticated"] is False
        assert "CDP not available" in result["error"]

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_authenticated_on_recruiter(self, mock_run, mock_check):
        """Should detect authenticated on Recruiter page."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/talent/home\n",
                stderr="",
            ),
        ]

        result = bu.probe_recruiter_auth("9230")

        assert result["authenticated"] is True
        assert result["error"] is None

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_login_cap(self, mock_run, mock_check):
        """Should reject login-cap URLs (false positive fix)."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/uas/login-cap?session_redirect=/talent/home\n",
                stderr="",
            ),
        ]

        result = bu.probe_recruiter_auth("9230")

        assert result["authenticated"] is False
        assert "login-cap" in result["url"]

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_generic_linkedin(self, mock_run, mock_check):
        """Should reject generic linkedin.com pages not under /talent/."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/feed/\n",
                stderr="",
            ),
        ]

        result = bu.probe_recruiter_auth("9230")

        assert result["authenticated"] is False

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_login_page(self, mock_run, mock_check):
        """Should reject explicit login pages."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/login?fromSignIn=true\n",
                stderr="",
            ),
        ]

        result = bu.probe_recruiter_auth("9230")

        assert result["authenticated"] is False

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_checkpoint(self, mock_run, mock_check):
        """Should reject checkpoint/challenge pages."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/checkpoint/challenge/AgGf...\n",
                stderr="",
            ),
        ]

        result = bu.probe_recruiter_auth("9230")

        assert result["authenticated"] is False

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_authenticated_on_talent_project(self, mock_run, mock_check):
        """Should detect authenticated on talent project page."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/talent/hire/123456789/projects/987654321\n",
                stderr="",
            ),
        ]

        result = bu.probe_recruiter_auth("9230")

        assert result["authenticated"] is True

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_readonly_probe_does_not_navigate(self, mock_run, mock_check):
        """Should only inspect current URL in readonly mode."""
        mock_check.return_value = True
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://www.linkedin.com/talent/home\n",
            stderr="",
        )

        result = bu.probe_recruiter_auth("9230", navigate=False)

        assert result["authenticated"] is True
        mock_run.assert_called_once_with(
            ["agent-browser", "--cdp", "9230", "get", "url"],
            capture_output=True,
            text=True,
            timeout=5,
        )


class TestProbeAgentBrowserAuth:
    """Tests for agent-browser session auth probing (false-success prevention)."""

    @patch("subprocess.run")
    def test_authenticated_on_recruiter(self, mock_run):
        """Should detect authenticated on Recruiter page via session."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # open command
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/talent/home\n",
                stderr="",
            ),  # get url command
        ]

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is True
        assert result["error"] is None
        # Verify session args were used
        cmd = mock_run.call_args[0][0]
        assert "--session" in cmd
        assert "test-session" in cmd

    @patch("subprocess.run")
    def test_not_authenticated_on_login_page(self, mock_run):
        """Should reject login page via session (false-success prevention)."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/login?fromSignIn=true\n",
                stderr="",
            ),
        ]

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False

    @patch("subprocess.run")
    def test_not_authenticated_on_login_cap(self, mock_run):
        """Should reject login-cap URLs via session (false-success prevention)."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/uas/login-cap?session_redirect=/talent/home\n",
                stderr="",
            ),
        ]

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False

    @patch("subprocess.run")
    def test_not_authenticated_on_checkpoint(self, mock_run):
        """Should reject checkpoint/challenge pages via session."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout="https://www.linkedin.com/checkpoint/challenge/AgGf...\n",
                stderr="",
            ),
        ]

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False

    @patch("subprocess.run")
    def test_probe_timeout(self, mock_run):
        """Should handle timeout gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False
        assert "timed out" in result["error"].lower()

    @patch("subprocess.run")
    def test_agent_browser_not_found(self, mock_run):
        """Should handle missing agent-browser."""
        mock_run.side_effect = FileNotFoundError()

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False
        assert "agent-browser" in result["error"].lower()


class TestGetBrowserMode:
    """Tests for get_browser_mode function."""

    def test_no_mode_file(self, tmp_path):
        """Should return None when no mode file."""
        result = bu.get_browser_mode(tmp_path)

        assert result is None

    def test_valid_cdp_mode_file(self, tmp_path):
        """Should read CDP mode from file."""
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()
        mode_file = runtime_dir / "browser_mode.json"
        mode_file.write_text('{"mode": "cdp", "cdp_port": "9222"}')

        result = bu.get_browser_mode(tmp_path)

        assert result is not None
        assert result.mode == "cdp"
        assert result.cdp_port == "9222"

    def test_valid_session_mode_file(self, tmp_path):
        """Should read session mode from file."""
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()
        mode_file = runtime_dir / "browser_mode.json"
        mode_file.write_text(
            '{"mode": "agent-browser", "session_name": "linkedin-test", "auth_file": "/auth.json"}'
        )

        result = bu.get_browser_mode(tmp_path)

        assert result is not None
        assert result.mode == "agent-browser"
        assert result.session_name == "linkedin-test"
        assert result.auth_file == "/auth.json"


class TestSaveBrowserMode:
    """Tests for save_browser_mode function."""

    def test_save_session_mode(self, tmp_path):
        """Should save session mode to file."""
        mode = bu.BrowserMode(
            mode="agent-browser",
            session_name="linkedin-test",
            auth_file="/path/to/auth.json",
        )

        bu.save_browser_mode(tmp_path, mode)

        mode_file = tmp_path / "runtime" / "browser_mode.json"
        assert mode_file.exists()

        data = json.loads(mode_file.read_text())
        assert data["mode"] == "agent-browser"
        assert data["session_name"] == "linkedin-test"
        assert data["auth_file"] == "/path/to/auth.json"


class TestResolveBrowserMode:
    """Tests for resolve_browser_mode function."""

    def test_use_saved_mode(self, tmp_path):
        """Should use port from saved mode."""
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()
        mode_file = runtime_dir / "browser_mode.json"
        mode_file.write_text('{"mode": "cdp", "cdp_port": "9222"}')

        result = bu.resolve_browser_mode(tmp_path, "9230")

        assert result.cdp_port == "9222"

    def test_use_saved_session_mode(self, tmp_path):
        """Should use session from saved mode."""
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()
        mode_file = runtime_dir / "browser_mode.json"
        mode_file.write_text(
            '{"mode": "agent-browser", "session_name": "test", "auth_file": "/auth.json"}'
        )

        result = bu.resolve_browser_mode(tmp_path, "9230")

        assert result.mode == "agent-browser"
        assert result.session_name == "test"

    def test_fallback_to_preferred(self, tmp_path):
        """Should fallback to preferred port."""
        result = bu.resolve_browser_mode(tmp_path, "9230")

        assert result.mode == "cdp"
        assert result.cdp_port == "9230"


class TestBrowserContext:
    """Tests for BrowserContext."""

    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_cdp_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_enter_with_saved_cdp_mode(
        self, mock_probe, mock_check, mock_get_mode, tmp_path
    ):
        """Should use saved CDP mode on enter."""
        mock_get_mode.return_value = bu.BrowserMode(mode="cdp", cdp_port="9222")
        mock_check.return_value = True
        mock_probe.return_value = {"authenticated": True}

        with bu.BrowserContext(tmp_path, "9230") as ctx:
            assert ctx.mode.cdp_port == "9222"

    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_agent_browser_auth")
    def test_enter_with_saved_session_mode(
        self, mock_probe, mock_check, mock_get_mode, tmp_path
    ):
        """Should use saved session mode on enter."""
        mock_get_mode.return_value = bu.BrowserMode(
            mode="agent-browser", session_name="test"
        )
        mock_check.return_value = True
        mock_probe.return_value = {"authenticated": True}  # Already authenticated

        with bu.BrowserContext(tmp_path, "9230") as ctx:
            assert ctx.mode.session_name == "test"

    @patch("browser_utils.check_cdp_available")
    def test_enter_cdp_not_available(self, mock_check, tmp_path):
        """Should raise when CDP not available."""
        mock_check.return_value = False

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230") as ctx:
                pass

        assert "CDP not available" in str(exc_info.value)

    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    @patch("browser_utils.run_browser_command")
    def test_run_command(
        self, mock_run, mock_probe, mock_check, mock_get_mode, tmp_path
    ):
        """Should run commands through context."""
        mock_get_mode.return_value = bu.BrowserMode(mode="cdp", cdp_port="9230")
        mock_check.return_value = True
        mock_probe.return_value = {"authenticated": True}  # Already authenticated
        mock_run.return_value = {"returncode": 0, "parsed": {"title": "Test"}}

        with bu.BrowserContext(tmp_path, "9230") as ctx:
            result = ctx.run_command("eval", "document.title")

        assert result["returncode"] == 0
        mock_run.assert_called_once()


class TestConnectBrowserGuidance:
    """Tests for CONNECT_BROWSER_GUIDANCE command validity."""

    def test_guidance_command_format(self):
        """Guidance command should be copy-paste valid shell syntax."""
        # The guidance should NOT have --bootstrap since auto-bootstrap is now default
        # Correct: bash "$WORK_DIR/.../connect_browser.sh"
        guidance = bu.CONNECT_BROWSER_GUIDANCE

        # Verify the correct format without --bootstrap (auto-bootstrap is default)
        assert 'connect_browser.sh"' in guidance, (
            "Guidance should reference connect_browser.sh script"
        )

        # Verify --bootstrap is NOT required (auto-bootstrap is now default)
        assert "--bootstrap" not in guidance, (
            "Guidance should NOT require --bootstrap since auto-bootstrap is default"
        )

    def test_guidance_contains_both_paths(self):
        """Guidance should reference both WORK_DIR and SKILL_DIR paths."""
        guidance = bu.CONNECT_BROWSER_GUIDANCE

        assert "$WORK_DIR" in guidance, "Guidance should reference WORK_DIR path"
        assert "$SKILL_DIR" in guidance, "Guidance should reference SKILL_DIR path"
        assert "connect_browser.sh" in guidance, (
            "Guidance should reference connect_browser.sh"
        )

    def test_guidance_describes_auto_flow(self):
        """Guidance should describe the automatic auth flow."""
        guidance = bu.CONNECT_BROWSER_GUIDANCE

        assert "automatically" in guidance.lower(), (
            "Guidance should mention automatic auth check/flow"
        )


class TestBrowserContextStaleStateRecovery:
    """Tests for BrowserContext stale saved state recovery."""

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    def test_stale_saved_mode_auto_bootstrap_attempts_recovery(
        self, mock_bootstrap, tmp_path
    ):
        """Stale saved mode + auto_bootstrap=True should attempt bootstrap."""
        # Setup: saved mode exists but browser is unavailable (stale state)
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            "session_name": None,
            "auth_file": None,
            "message": "Recovered from stale state",
            "error": None,
        }

        # Mock get_browser_mode to return stale mode first, then new mode after bootstrap
        # Note: get_browser_mode is called:
        # 1. Initial check in __enter__
        # 2. After bootstrap success (to reload mode)
        # 3. After auth check bootstrap (if triggered) - but in this test we skip auth check since browser unavailable initially
        with patch(
            "browser_utils.get_browser_mode",
            side_effect=[
                bu.BrowserMode(mode="agent-browser", session_name="stale-session"),
                bu.BrowserMode(mode="cdp", cdp_port="9230"),
                bu.BrowserMode(mode="cdp", cdp_port="9230"),
            ],
        ):
            with patch(
                "browser_utils.check_browser_available",
                side_effect=[
                    False,
                    True,
                ],  # First call: stale, Second call: after bootstrap
            ):
                # No auth probe needed since browser is unavailable (stale state path)
                with patch("browser_utils.probe_recruiter_auth") as mock_probe:
                    mock_probe.return_value = {"authenticated": True}
                    with bu.BrowserContext(
                        tmp_path, "9230", auto_bootstrap=True
                    ) as ctx:
                        assert ctx.mode.mode == "cdp"
                        assert ctx.mode.cdp_port == "9230"

        # Verify bootstrap was called to recover from stale state
        mock_bootstrap.assert_called_once()
        call_kwargs = mock_bootstrap.call_args[1]
        assert call_kwargs["allow_browser_launch"] is True

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    def test_stale_saved_mode_auto_bootstrap_false_raises_with_guidance(
        self, mock_check_available, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Stale saved mode + auto_bootstrap=False should fail with guidance."""
        # Setup: saved mode exists but browser is unavailable (stale state)
        mock_get_mode.return_value = bu.BrowserMode(
            mode="agent-browser", session_name="stale-session"
        )
        mock_check_available.return_value = False  # Stale state - browser unavailable

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=False) as ctx:
                pass

        # Should fail with guidance message
        assert "Browser not available" in str(exc_info.value)
        assert "connect_browser.sh" in str(exc_info.value)
        # Bootstrap should NOT have been called
        mock_bootstrap.assert_not_called()

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    def test_stale_saved_mode_auto_bootstrap_failure_raises_with_guidance(
        self, mock_check_available, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Stale saved mode + auto_bootstrap=True with failed bootstrap should raise with guidance."""
        # Setup: saved mode exists but browser is unavailable (stale state)
        mock_get_mode.return_value = bu.BrowserMode(
            mode="agent-browser", session_name="stale-session"
        )
        mock_check_available.return_value = False  # Stale state - browser unavailable
        mock_bootstrap.return_value = {
            "success": False,
            "mode": "failed",
            "cdp_port": None,
            "session_name": None,
            "auth_file": None,
            "message": "Bootstrap failed",
            "error": "Chrome not found",
        }

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
                pass

        # Should fail with guidance message including bootstrap error
        assert "Browser not available" in str(exc_info.value)
        assert "auth bootstrap failed" in str(exc_info.value)
        assert "Chrome not found" in str(exc_info.value)
        assert "connect_browser.sh" in str(exc_info.value)


class TestBrowserContextAutoBootstrap:
    """Tests for BrowserContext auto-bootstrap functionality."""

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_cdp_available")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_auto_bootstrap_success_cdp_mode(
        self,
        mock_probe,
        mock_check_available,
        mock_check_cdp,
        mock_get_mode,
        mock_bootstrap,
        tmp_path,
    ):
        """Should auto-bootstrap successfully when CDP not available initially."""
        # First call: no saved mode, CDP not available
        mock_get_mode.side_effect = [None, bu.BrowserMode(mode="cdp", cdp_port="9230")]
        mock_check_cdp.return_value = False  # CDP not available initially
        mock_check_available.return_value = True  # Available after bootstrap
        mock_probe.return_value = {
            "authenticated": True
        }  # Authenticated after bootstrap
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            "session_name": None,
            "auth_file": None,
            "message": "Using existing authenticated browser on port 9230",
            "error": None,
        }

        with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
            assert ctx.mode.mode == "cdp"
            assert ctx.mode.cdp_port == "9230"

        # Verify bootstrap was called with explicit opt-in
        mock_bootstrap.assert_called_once()
        call_kwargs = mock_bootstrap.call_args[1]
        assert call_kwargs["allow_browser_launch"] is True
        assert call_kwargs["chrome_profile"] == tmp_path / "chrome-profile"

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_cdp_available")
    def test_auto_bootstrap_success_agent_browser_mode(
        self, mock_check_cdp, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Should auto-bootstrap successfully into agent-browser mode."""
        mock_get_mode.side_effect = [
            None,
            bu.BrowserMode(
                mode="agent-browser",
                session_name="linkedin-test",
                auth_file=str(tmp_path / "runtime" / "auth" / "linkedin-auth.json"),
            ),
        ]
        mock_check_cdp.return_value = False
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "agent-browser",
            "cdp_port": None,
            "session_name": "linkedin-test",
            "auth_file": str(tmp_path / "runtime" / "auth" / "linkedin-auth.json"),
            "message": "Agent-browser session started",
            "error": None,
        }

        with patch("browser_utils.check_browser_available", return_value=True):
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
                assert ctx.mode.mode == "agent-browser"
                assert ctx.mode.session_name == "linkedin-test"

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_cdp_available")
    def test_auto_bootstrap_failure_raises(
        self, mock_check_cdp, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Should raise RuntimeError when auto-bootstrap fails."""
        mock_get_mode.return_value = None
        mock_check_cdp.return_value = False
        mock_bootstrap.return_value = {
            "success": False,
            "mode": "failed",
            "cdp_port": None,
            "session_name": None,
            "auth_file": None,
            "message": "Browser launch not allowed without explicit opt-in",
            "error": "Browser launch not allowed without explicit opt-in",
        }

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
                pass

        assert "Auth bootstrap failed" in str(exc_info.value)
        assert "connect_browser.sh" in str(exc_info.value)
        # --bootstrap no longer needed since auto-bootstrap is default
        assert "automatically" in str(exc_info.value).lower()

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_cdp_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_auto_bootstrap_when_cdp_available_not_authenticated(
        self, mock_probe, mock_check_cdp, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Should auto-bootstrap when CDP available but not authenticated."""
        # First probe (no saved mode path): not authenticated
        # Second probe (after bootstrap reload): authenticated
        mock_get_mode.side_effect = [None, bu.BrowserMode(mode="cdp", cdp_port="9230")]
        mock_check_cdp.return_value = True  # CDP available
        mock_probe.side_effect = [
            {
                "authenticated": False,
                "url": "https://linkedin.com/login",
            },  # First check
            {
                "authenticated": True,
                "url": "https://linkedin.com/talent/home",
            },  # After bootstrap
        ]
        mock_check_available = patch(
            "browser_utils.check_browser_available", return_value=True
        )
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            "session_name": None,
            "auth_file": None,
            "message": "Using existing authenticated browser on port 9230",
            "error": None,
        }

        with mock_check_available:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
                assert ctx.mode.cdp_port == "9230"

        # Verify bootstrap was called
        mock_bootstrap.assert_called_once()
        call_kwargs = mock_bootstrap.call_args[1]
        assert call_kwargs["chrome_profile"] == tmp_path / "chrome-profile"

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_cdp_available")
    def test_auto_bootstrap_no_saved_mode_after_success(
        self, mock_check_cdp, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Should raise if bootstrap succeeds but mode not saved."""
        mock_get_mode.return_value = None  # Always returns None (mode not saved)
        mock_check_cdp.return_value = False
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            "message": "Success",
            "error": None,
        }

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
                pass

        assert "Bootstrap succeeded but failed to save browser mode" in str(
            exc_info.value
        )

    def test_auto_bootstrap_false_by_default(self, tmp_path):
        """Should have auto_bootstrap=False by default."""
        ctx = bu.BrowserContext(tmp_path, "9230")
        assert ctx.auto_bootstrap is False


class TestBrowserContextSavedModeAuthCheck:
    """Tests for BrowserContext auth probing on saved modes (reachable but unauthenticated)."""

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_saved_cdp_mode_unauthenticated_auto_bootstrap_true_attempts_bootstrap(
        self, mock_probe, mock_check_available, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Saved CDP mode available but unauthenticated + auto_bootstrap=True => bootstrap attempted."""
        # Setup: saved CDP mode exists, browser reachable, but NOT authenticated
        mock_get_mode.side_effect = [
            bu.BrowserMode(mode="cdp", cdp_port="9222"),  # Initial saved mode
            bu.BrowserMode(mode="cdp", cdp_port="9230"),  # After bootstrap reload
        ]
        mock_check_available.return_value = True  # Browser is reachable
        mock_probe.return_value = {
            "authenticated": False,  # But NOT authenticated to Recruiter
            "url": "https://www.linkedin.com/login",
            "error": None,
        }
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            "session_name": None,
            "auth_file": None,
            "message": "Bootstrap succeeded",
            "error": None,
        }

        with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
            assert ctx.mode.mode == "cdp"

        # Verify bootstrap was called to recover from unauthenticated state
        mock_bootstrap.assert_called_once()
        call_kwargs = mock_bootstrap.call_args[1]
        assert call_kwargs["allow_browser_launch"] is True
        assert call_kwargs["chrome_profile"] == tmp_path / "chrome-profile"

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_saved_cdp_mode_unauthenticated_auto_bootstrap_false_raises_guidance(
        self, mock_probe, mock_check_available, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Saved CDP mode available but unauthenticated + auto_bootstrap=False => raises with guidance."""
        # Setup: saved CDP mode exists, browser reachable, but NOT authenticated
        mock_get_mode.return_value = bu.BrowserMode(mode="cdp", cdp_port="9222")
        mock_check_available.return_value = True  # Browser is reachable
        mock_probe.return_value = {
            "authenticated": False,  # But NOT authenticated to Recruiter
            "url": "https://www.linkedin.com/login",
            "error": None,
        }

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=False) as ctx:
                pass

        # Should fail with clear guidance
        assert "Saved CDP mode reachable on port 9222 but not authenticated" in str(
            exc_info.value
        )
        assert "connect_browser.sh" in str(exc_info.value)
        # Bootstrap should NOT have been called
        mock_bootstrap.assert_not_called()

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_agent_browser_auth")
    def test_saved_agent_browser_mode_unauthenticated_auto_bootstrap_true_attempts_bootstrap(
        self, mock_probe, mock_check_available, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Saved agent-browser mode available but unauthenticated + auto_bootstrap=True => bootstrap attempted."""
        # Setup: saved agent-browser mode exists, browser reachable, but NOT authenticated
        mock_get_mode.side_effect = [
            bu.BrowserMode(
                mode="agent-browser",
                session_name="test-session",
                auth_file="/path/to/auth.json",
            ),  # Initial saved mode
            bu.BrowserMode(
                mode="agent-browser",
                session_name="new-session",
                auth_file="/path/to/new-auth.json",
            ),  # After bootstrap reload
        ]
        mock_check_available.return_value = True  # Browser is reachable
        mock_probe.return_value = {
            "authenticated": False,  # But NOT authenticated to Recruiter
            "url": "https://www.linkedin.com/login",
            "error": None,
        }
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "agent-browser",
            "cdp_port": None,
            "session_name": "new-session",
            "auth_file": "/path/to/new-auth.json",
            "message": "Bootstrap succeeded",
            "error": None,
        }

        with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
            assert ctx.mode.mode == "agent-browser"
            assert ctx.mode.session_name == "new-session"

        # Verify bootstrap was called to recover from unauthenticated state
        mock_bootstrap.assert_called_once()
        call_kwargs = mock_bootstrap.call_args[1]
        assert call_kwargs["allow_browser_launch"] is True

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_agent_browser_auth")
    def test_saved_agent_browser_mode_unauthenticated_auto_bootstrap_false_raises_guidance(
        self, mock_probe, mock_check_available, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Saved agent-browser mode available but unauthenticated + auto_bootstrap=False => raises with guidance."""
        # Setup: saved agent-browser mode exists, browser reachable, but NOT authenticated
        mock_get_mode.return_value = bu.BrowserMode(
            mode="agent-browser",
            session_name="test-session",
            auth_file="/path/to/auth.json",
        )
        mock_check_available.return_value = True  # Browser is reachable
        mock_probe.return_value = {
            "authenticated": False,  # But NOT authenticated to Recruiter
            "url": "https://www.linkedin.com/login",
            "error": None,
        }

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=False) as ctx:
                pass

        # Should fail with clear guidance
        assert "Saved agent-browser mode reachable but not authenticated" in str(
            exc_info.value
        )
        assert "connect_browser.sh" in str(exc_info.value)
        # Bootstrap should NOT have been called
        mock_bootstrap.assert_not_called()

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_saved_cdp_mode_unauthenticated_bootstrap_failure_raises_guidance(
        self, mock_probe, mock_check_available, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Saved CDP mode unauthenticated + auto_bootstrap=True with failed bootstrap => raises with guidance."""
        mock_get_mode.return_value = bu.BrowserMode(mode="cdp", cdp_port="9222")
        mock_check_available.return_value = True
        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/login",
            "error": None,
        }
        mock_bootstrap.return_value = {
            "success": False,
            "mode": "failed",
            "cdp_port": None,
            "session_name": None,
            "auth_file": None,
            "message": "Bootstrap failed",
            "error": "Chrome not found",
        }

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
                pass

        # Should fail with guidance including bootstrap error
        assert "Saved CDP mode reachable but not authenticated" in str(exc_info.value)
        assert "auth bootstrap failed" in str(exc_info.value)
        assert "Chrome not found" in str(exc_info.value)
        assert "connect_browser.sh" in str(exc_info.value)

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_agent_browser_auth")
    def test_saved_agent_browser_mode_unauthenticated_bootstrap_failure_raises_guidance(
        self, mock_probe, mock_check_available, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Saved agent-browser mode unauthenticated + auto_bootstrap=True with failed bootstrap => raises with guidance."""
        mock_get_mode.return_value = bu.BrowserMode(
            mode="agent-browser",
            session_name="test-session",
            auth_file="/path/to/auth.json",
        )
        mock_check_available.return_value = True
        mock_probe.return_value = {
            "authenticated": False,
            "url": "https://www.linkedin.com/login",
            "error": None,
        }
        mock_bootstrap.return_value = {
            "success": False,
            "mode": "failed",
            "cdp_port": None,
            "session_name": None,
            "auth_file": None,
            "message": "Bootstrap failed",
            "error": "Auth file not found",
        }

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9230", auto_bootstrap=True) as ctx:
                pass

        # Should fail with guidance including bootstrap error
        assert "Saved agent-browser mode reachable but not authenticated" in str(
            exc_info.value
        )
        assert "auth bootstrap failed" in str(exc_info.value)
        assert "Auth file not found" in str(exc_info.value)
        assert "connect_browser.sh" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
