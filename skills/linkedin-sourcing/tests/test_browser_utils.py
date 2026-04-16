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

        result = bu.check_cdp_available("9234")

        assert result is True

    @patch("urllib.request.urlopen")
    def test_cdp_not_available(self, mock_urlopen):
        """Should return False when CDP is unavailable."""
        mock_urlopen.side_effect = URLError("Connection refused")

        result = bu.check_cdp_available("9234")

        assert result is False

    @patch("urllib.request.urlopen")
    def test_cdp_timeout(self, mock_urlopen):
        """Should return False on timeout."""
        mock_urlopen.side_effect = TimeoutError()

        result = bu.check_cdp_available("9234")

        assert result is False


class TestRequireCdp:
    """Tests for CDP requirement enforcement."""

    @patch("browser_utils.check_cdp_available")
    def test_cdp_available_passes(self, mock_check):
        """Should not raise when CDP is available."""
        mock_check.return_value = True

        bu.require_cdp("9234")  # Should not raise

    @patch("browser_utils.check_cdp_available")
    def test_cdp_unavailable_raises(self, mock_check):
        """Should raise RuntimeError with guidance when CDP unavailable."""
        mock_check.return_value = False

        with pytest.raises(RuntimeError) as exc_info:
            bu.require_cdp("9234")

        assert "connect_browser.sh" in str(exc_info.value)
        assert "9234" in str(exc_info.value)


class TestBrowserMode:
    """Tests for BrowserMode dataclass."""

    def test_cdp_mode(self):
        """Should create CDP mode."""
        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")

        assert mode.is_cdp() is True
        assert mode.is_agent_browser() is False
        assert mode.cdp_port == "9234"

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
        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        args = mode.build_agent_browser_args()

        assert args == ["--cdp", "9234"]

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
        # Default headed=True should include --headed
        assert "--headed" in args

    def test_build_agent_browser_args_session_headed_false(self):
        """Should not include --headed when headed=False."""
        mode = bu.BrowserMode(
            mode="agent-browser",
            session_name="linkedin-test",
            auth_file="/auth.json",
            headed=False,
        )
        args = mode.build_agent_browser_args()

        assert "--session" in args
        assert "--headed" not in args

    def test_build_agent_browser_args_session_headed_true(self):
        """Should include --headed when headed=True."""
        mode = bu.BrowserMode(
            mode="agent-browser",
            session_name="linkedin-test",
            auth_file="/auth.json",
            headed=True,
        )
        args = mode.build_agent_browser_args()

        assert "--session" in args
        assert "--headed" in args

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
        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")

        result = bu.check_browser_available(mode)

        assert result is True

    @patch("browser_utils.check_cdp_available")
    def test_cdp_not_available(self, mock_check_cdp):
        """Should return False when CDP not available."""
        mock_check_cdp.return_value = False
        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")

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

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
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
        result = bu.check_dialog_status("9234")

        assert result["has_dialog"] is False
        # Verify the command was built with --cdp
        cmd = mock_run.call_args[0][0]
        assert "--cdp" in cmd
        assert "9234" in cmd

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

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
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

    @patch("subprocess.run")
    def test_raw_execution_no_precheck(self, mock_run):
        """Should execute command without prechecking browser availability.

        The new design keeps run_browser_command as a low-level executor.
        Browser availability checks should happen at phase boundaries
        via classify_browser_readiness or attempt_browser_action.
        """
        # subprocess.run is called directly without checking browser availability first
        mock_run.return_value = Mock(
            stdout='{"state": "ready"}',
            stderr="",
            returncode=0,
        )

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        result = bu.run_browser_command(mode, "eval", "some_js")

        # Command should execute without precheck
        assert result["returncode"] == 0
        assert result["parsed"]["state"] == "ready"
        mock_run.assert_called_once()

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

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        result = bu.run_browser_command(mode, "eval", "some_js")

        assert result["returncode"] == 0
        assert result["parsed"]["state"] == "ready"
        assert result["error"] is None

        # Check the command was built correctly
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "agent-browser"
        assert "--cdp" in cmd
        assert "9234" in cmd

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
        result = bu.run_browser_command("9234", "eval", "some_js")

        assert result["returncode"] == 0
        # Check the command was built correctly with --cdp
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "agent-browser"
        assert "--cdp" in cmd
        assert "9234" in cmd

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

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
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

    @patch("browser_utils.check_cdp_available")
    def test_cdp_not_available(self, mock_check):
        """Should return not authenticated when CDP unavailable."""
        mock_check.return_value = False

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is False
        assert "CDP not available" in result["error"]

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_authenticated_on_recruiter(self, mock_run, mock_check):
        """Should detect authenticated on Recruiter page via JS."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # open
            _make_js_result("https://www.linkedin.com/talent/home"),  # JS eval
        ]

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is True
        assert result["error"] is None

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_authenticated_on_talent_root_no_trailing_slash(self, mock_run, mock_check):
        """Should detect authenticated on /talent (no trailing slash) via JS."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result("https://www.linkedin.com/talent"),
        ]

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is True
        assert result["error"] is None
        assert result["url"] == "https://www.linkedin.com/talent"

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_login_cap(self, mock_run, mock_check):
        """Should reject login-cap URLs via JS detection."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/uas/login-cap?session_redirect=/talent/home",
                is_talent=False,
                has_login_form=True,
            ),
        ]

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is False

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_generic_linkedin(self, mock_run, mock_check):
        """Should reject generic linkedin.com pages not under /talent/."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/feed/",
                is_talent=False,
            ),
        ]

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is False

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_login_page(self, mock_run, mock_check):
        """Should reject explicit login pages via JS."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/login?fromSignIn=true",
                is_talent=False,
                has_login_form=True,
            ),
        ]

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is False

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_on_checkpoint(self, mock_run, mock_check):
        """Should reject checkpoint/challenge pages via JS."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/checkpoint/challenge/AgGf...",
                is_talent=False,
                has_checkpoint=True,
            ),
        ]

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is False

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_not_authenticated_login_form_on_talent(self, mock_run, mock_check):
        """Should reject when login form present on talent path."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/talent",
                is_talent=True,
                has_login_form=True,
            ),
        ]

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is False

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_authenticated_on_talent_project(self, mock_run, mock_check):
        """Should detect authenticated on talent project page."""
        mock_check.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/talent/hire/123456789/projects/987654321"
            ),
        ]

        result = bu.probe_recruiter_auth("9234")

        assert result["authenticated"] is True

    @patch("browser_utils.check_cdp_available")
    @patch("subprocess.run")
    def test_readonly_probe_does_not_navigate(self, mock_run, mock_check):
        """Should only inspect current page in readonly mode."""
        mock_check.return_value = True
        mock_run.return_value = _make_js_result("https://www.linkedin.com/talent/home")

        result = bu.probe_recruiter_auth("9234", navigate=False)

        assert result["authenticated"] is True
        # Should only call eval, not open
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "eval" in cmd


class TestProbeAgentBrowserAuth:
    """Tests for agent-browser session auth probing with JS-based detection."""

    @patch("subprocess.run")
    def test_authenticated_on_recruiter(self, mock_run):
        """Should detect authenticated on Recruiter page via session."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # open command
            _make_js_result("https://www.linkedin.com/talent/home"),  # JS eval
        ]

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is True
        assert result["error"] is None
        # Verify session args were used
        cmd = mock_run.call_args[0][0]
        assert "--session" in cmd
        assert "test-session" in cmd

    @patch("subprocess.run")
    def test_authenticated_on_talent_root_no_trailing_slash(self, mock_run):
        """Should detect authenticated on /talent (no trailing slash) via session."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result("https://www.linkedin.com/talent"),
        ]

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is True
        assert result["error"] is None
        assert result["url"] == "https://www.linkedin.com/talent"

    @patch("subprocess.run")
    def test_not_authenticated_on_login_page(self, mock_run):
        """Should reject login page via session (false-success prevention)."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/login?fromSignIn=true",
                is_talent=False,
                has_login_form=True,
            ),
        ]

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False

    @patch("subprocess.run")
    def test_not_authenticated_on_login_cap(self, mock_run):
        """Should reject login-cap URLs via session (false-success prevention)."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/uas/login-cap?session_redirect=/talent/home",
                is_talent=False,
                has_login_form=True,
            ),
        ]

        result = bu.probe_agent_browser_auth("test-session")

        assert result["authenticated"] is False

    @patch("subprocess.run")
    def test_not_authenticated_on_checkpoint(self, mock_run):
        """Should reject checkpoint/challenge pages via session."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            _make_js_result(
                "https://www.linkedin.com/checkpoint/challenge/AgGf...",
                is_talent=False,
                has_checkpoint=True,
            ),
        ]

        result = bu.probe_agent_browser_auth("test-session")

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

        result = bu.resolve_browser_mode(tmp_path, "9234")

        assert result.cdp_port == "9222"

    def test_use_saved_session_mode(self, tmp_path):
        """Should use session from saved mode."""
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()
        mode_file = runtime_dir / "browser_mode.json"
        mode_file.write_text(
            '{"mode": "agent-browser", "session_name": "test", "auth_file": "/auth.json"}'
        )

        result = bu.resolve_browser_mode(tmp_path, "9234")

        assert result.mode == "agent-browser"
        assert result.session_name == "test"

    def test_fallback_to_preferred(self, tmp_path):
        """Should fallback to preferred port."""
        result = bu.resolve_browser_mode(tmp_path, "9234")

        assert result.mode == "cdp"
        assert result.cdp_port == "9234"


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

        with bu.BrowserContext(tmp_path, "9234") as ctx:
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

        with bu.BrowserContext(tmp_path, "9234") as ctx:
            assert ctx.mode.session_name == "test"

    @patch("browser_utils.check_cdp_available")
    def test_enter_cdp_not_available(self, mock_check, tmp_path):
        """Should raise when CDP not available."""
        mock_check.return_value = False

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9234") as ctx:
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
        mock_get_mode.return_value = bu.BrowserMode(mode="cdp", cdp_port="9234")
        mock_check.return_value = True
        mock_probe.return_value = {"authenticated": True}  # Already authenticated
        mock_run.return_value = {"returncode": 0, "parsed": {"title": "Test"}}

        with bu.BrowserContext(tmp_path, "9234") as ctx:
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

    def test_guidance_contains_canonical_script_path(self):
        """Guidance should reference the canonical connect script path."""
        guidance = bu.CONNECT_BROWSER_GUIDANCE

        assert "$WORK_DIR" not in guidance, (
            "Guidance should not require runtime script copies"
        )
        assert 'bash "' in guidance, "Guidance should include a runnable bash command"
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
            "cdp_port": "9234",
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
                bu.BrowserMode(mode="cdp", cdp_port="9234"),
                bu.BrowserMode(mode="cdp", cdp_port="9234"),
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
                        tmp_path, "9234", auto_bootstrap=True
                    ) as ctx:
                        assert ctx.mode.mode == "cdp"
                        assert ctx.mode.cdp_port == "9234"

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
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=False) as ctx:
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
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
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
        mock_get_mode.side_effect = [None, bu.BrowserMode(mode="cdp", cdp_port="9234")]
        mock_check_cdp.return_value = False  # CDP not available initially
        mock_check_available.return_value = True  # Available after bootstrap
        mock_probe.return_value = {
            "authenticated": True
        }  # Authenticated after bootstrap
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9234",
            "session_name": None,
            "auth_file": None,
            "message": "Using existing authenticated browser on port 9234",
            "error": None,
        }

        with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
            assert ctx.mode.mode == "cdp"
            assert ctx.mode.cdp_port == "9234"

        # Verify bootstrap was called with explicit opt-in
        mock_bootstrap.assert_called_once()
        call_kwargs = mock_bootstrap.call_args[1]
        assert call_kwargs["allow_browser_launch"] is True
        assert call_kwargs["chrome_profile"] == tmp_path / "chrome-profile"

    @patch("browser_utils.auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.get_browser_mode")
    @patch("browser_utils.check_cdp_available")
    def test_auto_bootstrap_success_cdp_mode(
        self, mock_check_cdp, mock_get_mode, mock_bootstrap, tmp_path
    ):
        """Should auto-bootstrap successfully into CDP mode."""
        # Provide multiple values for get_browser_mode calls:
        # 1. Initial check (None)
        # 2. After bootstrap reload (CDP mode)
        # 3. Additional calls if any
        mock_get_mode.side_effect = [
            None,
            bu.BrowserMode(mode="cdp", cdp_port="9234"),
            bu.BrowserMode(mode="cdp", cdp_port="9234"),
        ]
        mock_check_cdp.return_value = False
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9234",
            "session_name": None,
            "auth_file": None,
            "message": "Chrome running on port 9234",
            "error": None,
        }

        with patch("browser_utils.check_browser_available", return_value=True):
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
                assert ctx.mode.mode == "cdp"
                assert ctx.mode.cdp_port == "9234"

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
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
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
        mock_get_mode.side_effect = [None, bu.BrowserMode(mode="cdp", cdp_port="9234")]
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
            "cdp_port": "9234",
            "session_name": None,
            "auth_file": None,
            "message": "Using existing authenticated browser on port 9234",
            "error": None,
        }

        with mock_check_available:
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
                assert ctx.mode.cdp_port == "9234"

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
            "cdp_port": "9234",
            "message": "Success",
            "error": None,
        }

        with pytest.raises(RuntimeError) as exc_info:
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
                pass

        assert "Bootstrap succeeded but failed to save browser mode" in str(
            exc_info.value
        )

    def test_auto_bootstrap_false_by_default(self, tmp_path):
        """Should have auto_bootstrap=False by default."""
        ctx = bu.BrowserContext(tmp_path, "9234")
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
            bu.BrowserMode(mode="cdp", cdp_port="9234"),  # After bootstrap reload
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
            "cdp_port": "9234",
            "session_name": None,
            "auth_file": None,
            "message": "Bootstrap succeeded",
            "error": None,
        }

        with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
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
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=False) as ctx:
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
        # Bootstrap now returns CDP mode, not agent-browser mode
        mock_get_mode.side_effect = [
            bu.BrowserMode(
                mode="agent-browser",
                session_name="test-session",
                auth_file="/path/to/auth.json",
            ),  # Initial saved mode
            bu.BrowserMode(
                mode="cdp",
                cdp_port="9234",
            ),  # After bootstrap reload (now CDP mode)
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
            "cdp_port": "9234",
            "session_name": None,
            "auth_file": None,
            "message": "Bootstrap succeeded",
            "error": None,
        }

        with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
            assert ctx.mode.mode == "cdp"
            assert ctx.mode.cdp_port == "9234"

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
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=False) as ctx:
                pass

        # Should fail with clear guidance (backward compat: still mentions agent-browser)
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
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
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
            with bu.BrowserContext(tmp_path, "9234", auto_bootstrap=True) as ctx:
                pass

        # Should fail with guidance including bootstrap error
        assert "Saved agent-browser mode reachable but not authenticated" in str(
            exc_info.value
        )
        assert "auth bootstrap failed" in str(exc_info.value)
        assert "Auth file not found" in str(exc_info.value)
        assert "connect_browser.sh" in str(exc_info.value)


class TestFailureCode:
    """Tests for FailureCode enum."""

    def test_failure_code_values(self):
        """Should have expected failure code values."""
        assert bu.FailureCode.BROWSER_UNAVAILABLE == "browser_unavailable"
        assert bu.FailureCode.AUTH_REQUIRED == "auth_required"
        assert bu.FailureCode.DIALOG_BLOCKED == "dialog_blocked"
        assert bu.FailureCode.BLOCKED_OR_CAPTCHA == "blocked_or_captcha"
        assert bu.FailureCode.WRONG_PAGE == "wrong_page"
        assert bu.FailureCode.ELEMENT_MISSING == "element_missing"
        assert bu.FailureCode.TIMEOUT == "timeout"
        assert bu.FailureCode.VERIFICATION_FAILED == "verification_failed"
        assert bu.FailureCode.AMBIGUOUS_STATE == "ambiguous_state"


class TestActionRequired:
    """Tests for ActionRequired dataclass."""

    def test_to_dict(self):
        """Should convert to dictionary."""
        ar = bu.ActionRequired(
            code="test_code",
            summary="Test summary",
            steps=["Step 1", "Step 2"],
            can_retry=True,
            context={"key": "value"},
        )
        data = ar.to_dict()

        assert data["code"] == "test_code"
        assert data["summary"] == "Test summary"
        assert data["steps"] == ["Step 1", "Step 2"]
        assert data["can_retry"] is True
        assert data["context"] == {"key": "value"}

    def test_browser_unavailable_factory(self):
        """Should create browser_unavailable action_required."""
        ar = bu.ActionRequired.browser_unavailable(cdp_port="9234")

        assert ar.code == "browser_unavailable"
        assert "Chrome browser is not available" in ar.summary
        assert len(ar.steps) >= 3
        assert ar.can_retry is True
        assert ar.context["cdp_port"] == "9234"

    def test_auth_required_factory(self):
        """Should create auth_required action_required."""
        ar = bu.ActionRequired.auth_required(current_url="https://linkedin.com/login")

        assert ar.code == "auth_required"
        assert "authentication required" in ar.summary.lower()
        assert len(ar.steps) >= 4
        assert ar.can_retry is True
        assert ar.context["current_url"] == "https://linkedin.com/login"

    def test_dialog_blocked_factory(self):
        """Should create dialog_blocked action_required."""
        ar = bu.ActionRequired.dialog_blocked(
            dialog_type="confirm",
            message="Are you sure?",
        )

        assert ar.code == "dialog_blocked"
        assert "dialog is blocking" in ar.summary.lower()
        assert len(ar.steps) >= 3
        assert ar.can_retry is True
        assert ar.context["dialog_type"] == "confirm"
        assert ar.context["message"] == "Are you sure?"

    def test_blocked_or_captcha_factory(self):
        """Should create blocked_or_captcha action_required."""
        ar = bu.ActionRequired.blocked_or_captcha(
            current_url="https://linkedin.com/checkpoint"
        )

        assert ar.code == "blocked_or_captcha"
        assert "security check" in ar.summary.lower()
        assert len(ar.steps) >= 3
        assert ar.can_retry is True
        assert ar.context["current_url"] == "https://linkedin.com/checkpoint"

    def test_wrong_page_factory(self):
        """Should create wrong_page action_required."""
        ar = bu.ActionRequired.wrong_page(
            expected_url="https://linkedin.com/talent/home",
            actual_url="https://linkedin.com/feed",
        )

        assert ar.code == "wrong_page"
        assert "unexpected page" in ar.summary.lower()
        assert len(ar.steps) >= 2
        assert ar.can_retry is True
        assert ar.context["expected_url"] == "https://linkedin.com/talent/home"
        assert ar.context["actual_url"] == "https://linkedin.com/feed"

    def test_element_missing_factory(self):
        """Should create element_missing action_required."""
        ar = bu.ActionRequired.element_missing(
            selector="button.send-button",
            page_url="https://linkedin.com/talent/profile/123",
        )

        assert ar.code == "element_missing"
        assert "element not found" in ar.summary.lower()
        assert len(ar.steps) >= 3
        assert ar.can_retry is True
        assert ar.context["selector"] == "button.send-button"
        assert ar.context["page_url"] == "https://linkedin.com/talent/profile/123"

    def test_timeout_factory(self):
        """Should create timeout action_required."""
        ar = bu.ActionRequired.timeout(operation="click send button")

        assert ar.code == "timeout"
        assert "timed out" in ar.summary.lower()
        assert len(ar.steps) >= 3
        assert ar.can_retry is True
        assert ar.context["operation"] == "click send button"

    def test_verification_failed_factory(self):
        """Should create verification_failed action_required."""
        ar = bu.ActionRequired.verification_failed(
            verification_type="field_content",
            details="Subject field is empty",
        )

        assert ar.code == "verification_failed"
        assert "verification" in ar.summary.lower()
        assert len(ar.steps) >= 3
        assert ar.can_retry is True
        assert ar.context["verification_type"] == "field_content"
        assert ar.context["details"] == "Subject field is empty"

    def test_ambiguous_state_factory(self):
        """Should create ambiguous_state action_required."""
        ar = bu.ActionRequired.ambiguous_state(details="Unknown error occurred")

        assert ar.code == "ambiguous_state"
        assert "ambiguous" in ar.summary.lower()
        assert len(ar.steps) >= 4
        assert ar.can_retry is True
        assert ar.context["details"] == "Unknown error occurred"


class TestAttemptBrowserAction:
    """Tests for attempt_browser_action wrapper."""

    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.run_browser_command")
    def test_successful_action(self, mock_run, mock_check):
        """Should return success=True for successful command."""
        mock_check.return_value = True
        mock_run.return_value = {
            "stdout": '{"result": "ok"}',
            "stderr": "",
            "returncode": 0,
            "parsed": {"result": "ok"},
            "error": None,
            "dialog_info": None,
            "timed_out": False,
        }

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        result = bu.attempt_browser_action(
            mode, "test operation", "eval", "document.title"
        )

        assert result["success"] is True
        assert result["failure_code"] is None
        assert result["action_required"] is None
        assert result["parsed"]["result"] == "ok"

    @patch("browser_utils.check_browser_available")
    def test_browser_unavailable_failure(self, mock_check):
        """Should return browser_unavailable action_required."""
        mock_check.return_value = False
        # run_browser_command not called when browser unavailable

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        result = bu.attempt_browser_action(
            mode, "test operation", "eval", "document.title"
        )

        assert result["success"] is False
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "browser_unavailable"
        # Verify the action_required has the expected structure
        assert "Chrome" in result["action_required"]["summary"]
        assert len(result["action_required"]["steps"]) >= 3

    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.run_browser_command")
    def test_timeout_failure(self, mock_run, mock_check):
        """Should return timeout action_required."""
        mock_check.return_value = True
        mock_run.return_value = {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "parsed": None,
            "error": "Command timed out after 30s",
            "dialog_info": None,
            "timed_out": True,
        }

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        result = bu.attempt_browser_action(
            mode, "test operation", "eval", "document.title"
        )

        assert result["success"] is False
        assert result["failure_code"] == "timeout"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "timeout"

    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.run_browser_command")
    def test_dialog_blocked_failure(self, mock_run, mock_check):
        """Should return dialog_blocked action_required when dialog on timeout."""
        mock_check.return_value = True
        mock_run.return_value = {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "parsed": None,
            "error": "Command timed out after 30s; blocking alert dialog detected",
            "dialog_info": {
                "has_dialog": True,
                "dialog_type": "alert",
                "message": "Session expired",
            },
            "timed_out": True,
        }

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        result = bu.attempt_browser_action(
            mode, "test operation", "eval", "document.title"
        )

        assert result["success"] is False
        assert result["failure_code"] == "dialog_blocked"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "dialog_blocked"
        assert result["action_required"]["context"]["dialog_type"] == "alert"

    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.run_browser_command")
    def test_generic_failure(self, mock_run, mock_check):
        """Should return ambiguous_state for generic failures."""
        mock_check.return_value = True
        mock_run.return_value = {
            "stdout": "",
            "stderr": "Some error",
            "returncode": 1,
            "parsed": None,
            "error": "Command failed",
            "dialog_info": None,
            "timed_out": False,
        }

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        result = bu.attempt_browser_action(
            mode, "test operation", "eval", "document.title"
        )

        assert result["success"] is False
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "ambiguous_state"


class TestClassifyBrowserReadiness:
    """Tests for classify_browser_readiness helper."""

    @patch("browser_utils.check_browser_available")
    def test_browser_unavailable(self, mock_check):
        """Should classify as browser_unavailable when browser not available."""
        mock_check.return_value = False

        result = bu.classify_browser_readiness("9234")

        assert result.readiness == bu.BrowserReadiness.BROWSER_UNAVAILABLE
        assert result.action_required is not None
        assert result.action_required.code == bu.FailureCode.BROWSER_UNAVAILABLE

    @patch("browser_utils.check_browser_available")
    def test_ready_state(self, mock_check):
        """Should classify as ready when browser available and no issues."""
        mock_check.return_value = True

        result = bu.classify_browser_readiness("9234")

        assert result.readiness == bu.BrowserReadiness.READY
        assert result.action_required is None

    @patch("browser_utils.check_browser_available")
    def test_dialog_blocked(self, mock_check):
        """Should classify as dialog_blocked when dialog detected."""
        mock_check.return_value = True
        dialog_info = {
            "has_dialog": True,
            "dialog_type": "alert",
            "message": "Session expired",
        }

        result = bu.classify_browser_readiness("9234", dialog_info=dialog_info)

        assert result.readiness == bu.BrowserReadiness.DIALOG_BLOCKED
        assert result.action_required is not None
        assert result.action_required.code == bu.FailureCode.DIALOG_BLOCKED

    @patch("browser_utils.check_browser_available")
    def test_auth_required_from_url(self, mock_check):
        """Should classify as auth_required from login URL."""
        mock_check.return_value = True

        result = bu.classify_browser_readiness(
            "9234", current_url="https://www.linkedin.com/login?fromSignIn=true"
        )

        assert result.readiness == bu.BrowserReadiness.AUTH_REQUIRED
        assert result.action_required is not None
        assert result.action_required.code == bu.FailureCode.AUTH_REQUIRED

    @patch("browser_utils.check_browser_available")
    def test_blocked_or_captcha_from_url(self, mock_check):
        """Should classify as blocked_or_captcha from checkpoint URL."""
        mock_check.return_value = True

        result = bu.classify_browser_readiness(
            "9234", current_url="https://www.linkedin.com/checkpoint/challenge"
        )

        assert result.readiness == bu.BrowserReadiness.BLOCKED_OR_CAPTCHA
        assert result.action_required is not None
        assert result.action_required.code == bu.FailureCode.BLOCKED_OR_CAPTCHA

    @patch("browser_utils.check_browser_available")
    def test_auth_required_from_error(self, mock_check):
        """Should classify as auth_required from error message."""
        mock_check.return_value = True

        result = bu.classify_browser_readiness(
            "9234", error="Not authenticated to LinkedIn Recruiter"
        )

        assert result.readiness == bu.BrowserReadiness.AUTH_REQUIRED

    def test_to_dict(self):
        """Should convert BrowserReadinessResult to dict."""
        result = bu.BrowserReadinessResult(
            readiness=bu.BrowserReadiness.READY,
            action_required=None,
            context={"current_url": "https://example.com"},
        )

        data = result.to_dict()

        assert data["readiness"] == "ready"
        assert data["action_required"] is None
        assert data["context"]["current_url"] == "https://example.com"


class TestSafeGetParsed:
    """Tests for safe_get_parsed helper."""

    def test_returns_parsed_dict(self):
        """Should return parsed dict when valid."""
        result = {"parsed": {"url": "https://example.com"}, "returncode": 0}

        parsed = bu.safe_get_parsed(result)

        assert parsed == {"url": "https://example.com"}

    def test_returns_default_when_parsed_none(self):
        """Should return default when parsed is None."""
        result = {"parsed": None, "returncode": 0}

        parsed = bu.safe_get_parsed(result, default={})

        assert parsed == {}

    def test_returns_default_when_parsed_missing(self):
        """Should return default when parsed key missing."""
        result = {"returncode": 0}

        parsed = bu.safe_get_parsed(result, default={})

        assert parsed == {}

    def test_returns_default_when_not_dict(self):
        """Should return default when result is not a dict."""
        parsed = bu.safe_get_parsed("not a dict", default={})

        assert parsed == {}

    def test_returns_non_dict_when_require_dict_false(self):
        """Should return non-dict parsed when require_dict=False."""
        result = {"parsed": "https://example.com", "returncode": 0}

        parsed = bu.safe_get_parsed(result, require_dict=False)

        assert parsed == "https://example.com"

    def test_returns_default_for_non_dict_when_require_dict_true(self):
        """Should return default when parsed is non-dict and require_dict=True."""
        result = {"parsed": "string value", "returncode": 0}

        parsed = bu.safe_get_parsed(result, default={}, require_dict=True)

        assert parsed == {}


class TestRunBrowserCommandNoPrecheck:
    """Tests that run_browser_command no longer pre-checks browser availability."""

    @patch("browser_utils.check_browser_available")
    @patch("subprocess.run")
    def test_runs_command_without_precheck(self, mock_run, mock_check):
        """Should run command even if browser check would fail (no precheck)."""
        # Note: check_browser_available is NOT called in run_browser_command anymore
        mock_run.return_value = Mock(
            stdout='{"state": "ready"}',
            stderr="",
            returncode=0,
        )

        mode = bu.BrowserMode(mode="cdp", cdp_port="9234")
        result = bu.run_browser_command(mode, "eval", "document.title")

        # Command should run without pre-checking browser availability
        assert result["returncode"] == 0
        assert result["parsed"]["state"] == "ready"
        # check_browser_available should NOT be called by run_browser_command
        mock_check.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
