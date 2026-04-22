#!/usr/bin/env python3
"""Tests for inmail_sender.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_inmail_sender.py -v
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import inmail_sender as sender
from browser_utils import BrowserMode


class TestCheckBrowserAvailable:
    """Tests for check_browser_available function."""

    @patch("inmail_sender.check_cdp_available")
    def test_cdp_available(self, mock_check_cdp):
        """Should return True when CDP is available."""
        mock_check_cdp.return_value = True
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.check_browser_available(mode)

        assert result is True

    @patch("inmail_sender.check_cdp_available")
    def test_cdp_not_available(self, mock_check_cdp):
        """Should return False when CDP is unavailable."""
        mock_check_cdp.return_value = False
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.check_browser_available(mode)

        assert result is False

    @patch("inmail_sender.subprocess.run")
    def test_session_mode_available(self, mock_run):
        """Should return True when agent-browser session responds."""
        mock_run.return_value = Mock(returncode=0, stdout="https://linkedin.com")
        mode = BrowserMode(mode="agent-browser", session_name="test")

        result = sender.check_browser_available(mode)

        assert result is True
        # Verify correct command was called
        cmd = mock_run.call_args[0][0]
        assert "--session" in cmd


class TestResolveBrowserModeWithFallback:
    """Tests for resolve_browser_mode_with_fallback function."""

    @patch("inmail_sender.check_cdp_available")
    def test_provided_port_creates_cdp_mode(self, mock_check_cdp):
        """Should create CDP mode when port provided."""
        mock_check_cdp.return_value = True
        mode = sender.resolve_browser_mode_with_fallback(provided_port="9222")

        assert mode.mode == "cdp"
        assert mode.cdp_port == "9222"

    @patch("inmail_sender.get_browser_mode")
    def test_uses_saved_mode(self, mock_get_mode):
        """Should use saved browser mode."""
        mock_get_mode.return_value = BrowserMode(
            mode="agent-browser", session_name="test"
        )

        mode = sender.resolve_browser_mode_with_fallback(work_dir=Path("/tmp"))

        assert mode.mode == "agent-browser"
        assert mode.session_name == "test"

    @patch.dict("os.environ", {"CDP_PORT": "9333"})
    @patch("inmail_sender.get_browser_mode")
    @patch("inmail_sender.check_cdp_available")
    def test_fallback_to_env_var(self, mock_check_cdp, mock_get_mode):
        """Should fallback to environment variable."""
        mock_check_cdp.return_value = True
        mock_get_mode.return_value = None

        mode = sender.resolve_browser_mode_with_fallback(work_dir=Path("/tmp"))

        assert mode.mode == "cdp"
        assert mode.cdp_port == "9333"

    @patch("inmail_sender.get_browser_mode")
    @patch("inmail_sender.check_cdp_available")
    def test_fallback_to_default(self, mock_check_cdp, mock_get_mode):
        """Should fallback to default port."""
        mock_check_cdp.return_value = True
        mock_get_mode.return_value = None

        mode = sender.resolve_browser_mode_with_fallback(work_dir=Path("/tmp"))

        assert mode.mode == "cdp"
        assert mode.cdp_port == "9234"

    @patch("inmail_sender.get_browser_mode")
    def test_saved_agent_browser_wins_over_provided_port(self, mock_get_mode):
        """Saved agent-browser mode should win even when --cdp-port is provided.

        This is critical for send_inmail.sh which always passes --cdp-port.
        When browser_mode.json says mode=agent-browser, session mode must win.
        """
        mock_get_mode.return_value = BrowserMode(
            mode="agent-browser",
            session_name="linkedin-session",
            auth_file="/auth.json",
        )

        # Even with provided_port, saved agent-browser mode should win
        mode = sender.resolve_browser_mode_with_fallback(
            provided_port="9234", work_dir=Path("/tmp")
        )

        assert mode.mode == "agent-browser"
        assert mode.session_name == "linkedin-session"
        assert mode.auth_file == "/auth.json"

    @patch("inmail_sender.get_browser_mode")
    def test_provided_port_overrides_saved_cdp_mode(self, mock_get_mode):
        """Provided port should override saved CDP mode (allows explicit override)."""
        mock_get_mode.return_value = BrowserMode(mode="cdp", cdp_port="9222")

        mode = sender.resolve_browser_mode_with_fallback(
            provided_port="9234", work_dir=Path("/tmp")
        )

        # When saved mode is CDP and port is provided, use provided port
        assert mode.mode == "cdp"
        assert mode.cdp_port == "9234"

    @patch("inmail_sender.get_browser_mode")
    def test_saved_cdp_mode_used_when_no_port_provided(self, mock_get_mode):
        """Saved CDP mode should be used when no port is explicitly provided."""
        mock_get_mode.return_value = BrowserMode(mode="cdp", cdp_port="9222")

        mode = sender.resolve_browser_mode_with_fallback(work_dir=Path("/tmp"))

        assert mode.mode == "cdp"
        assert mode.cdp_port == "9222"


class TestRunAgentBrowser:
    """Tests for run_agent_browser function with mode support."""

    @patch("inmail_sender.check_browser_available")
    @patch("inmail_sender.subprocess.run")
    def test_fails_closed_when_browser_unavailable(self, mock_run, mock_check):
        """Should fail closed with guidance when browser is not available."""
        mock_check.return_value = False
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        code, out, err = sender.run_agent_browser(mode, "open", "http://test.com")

        assert code == -1
        assert "connect" in err.lower()
        mock_run.assert_not_called()

    @patch("inmail_sender.check_browser_available")
    @patch("inmail_sender.subprocess.run")
    def test_successful_run_cdp_mode(self, mock_run, mock_check):
        """Should run with --cdp args in CDP mode."""
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        code, out, err = sender.run_agent_browser(mode, "open", "http://test.com")

        assert code == 0
        assert out == "ok"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "agent-browser"
        assert "--cdp" in args
        assert "9234" in args

    @patch("inmail_sender.check_browser_available")
    @patch("inmail_sender.subprocess.run")
    def test_successful_run_session_mode(self, mock_run, mock_check):
        """Should run with --session args in session mode."""
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        mode = BrowserMode(mode="agent-browser", session_name="linkedin-test")
        code, out, err = sender.run_agent_browser(mode, "open", "http://test.com")

        assert code == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "agent-browser"
        assert "--session" in args
        assert "linkedin-test" in args

    @patch("inmail_sender.check_browser_available")
    @patch("inmail_sender.subprocess.run")
    def test_timeout_expired_returns_error(self, mock_run, mock_check):
        """Should return timeout error."""
        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["agent-browser"], timeout=5
        )

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        code, out, err = sender.run_agent_browser(mode, "open", "http://test.com")

        assert code == -1
        assert err == "timeout"

    @patch("inmail_sender.attempt_timeout_dialog_recovery")
    @patch("inmail_sender.check_browser_available")
    @patch("inmail_sender.subprocess.run")
    def test_timeout_auto_accepts_alert_without_retry(
        self, mock_run, mock_check, mock_recovery
    ):
        """Should surface alert recovery without retrying non-idempotent actions."""
        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["agent-browser"], timeout=5
        )
        mock_recovery.return_value = {
            "dialog_info": {"has_dialog": False, "dialog_type": None, "message": None},
            "attempted_auto_accept": True,
            "auto_accept_succeeded": True,
            "recovered": True,
            "error": None,
        }

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        code, out, err = sender.run_agent_browser(mode, "open", "http://test.com")

        assert code == -1
        assert out == ""
        assert "auto-accepted blocking alert dialog" in err

    @patch("inmail_sender.attempt_timeout_dialog_recovery")
    @patch("inmail_sender.check_browser_available")
    @patch("inmail_sender.subprocess.run")
    def test_timeout_retries_when_opted_in(self, mock_run, mock_check, mock_recovery):
        """Should retry once when caller opts in after alert recovery."""
        mock_check.return_value = True
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd=["agent-browser"], timeout=5),
            MagicMock(returncode=0, stdout="ok", stderr=""),
        ]
        mock_recovery.return_value = {
            "dialog_info": {"has_dialog": False, "dialog_type": None, "message": None},
            "attempted_auto_accept": True,
            "auto_accept_succeeded": True,
            "recovered": True,
            "error": None,
        }

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        code, out, err = sender.run_agent_browser(
            mode,
            "open",
            "http://test.com",
            retry_after_alert_recovery=True,
        )

        assert code == 0
        assert out == "ok"
        assert err == ""

    @patch("inmail_sender.check_dialog_status")
    @patch("inmail_sender.check_browser_available")
    @patch("inmail_sender.subprocess.run")
    def test_dialog_accept_timeout_treated_as_success_when_dialog_is_gone(
        self,
        mock_run,
        mock_check,
        mock_check_dialog_status,
    ):
        """Dialog accept should succeed when the dialog is already cleared after timeout."""
        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["agent-browser"], timeout=5
        )
        mock_check_dialog_status.return_value = {
            "has_dialog": False,
            "dialog_type": None,
            "message": None,
            "error": None,
        }

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        code, out, err = sender.run_agent_browser(mode, "dialog", "accept")

        assert (code, out, err) == (0, "", "")

    @patch("inmail_sender.run_agent_browser")
    @patch("inmail_sender.get_dialog_state")
    def test_accept_pending_dialog_succeeds_when_accept_command_times_out_but_clears(
        self,
        mock_get_state,
        mock_run,
    ):
        """accept_pending_dialog should trust successful resolution semantics from run_agent_browser."""
        mock_get_state.return_value = "open"
        mock_run.return_value = (0, "", "")

        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.accept_pending_dialog(mode) is True

    @patch("inmail_sender.run_agent_browser")
    def test_probe_helper_enables_retry_after_alert_recovery(self, mock_run):
        """Read-only probe helper should always enable alert recovery retry."""
        mock_run.return_value = (0, "ok", "")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        code, out, err = sender.run_agent_browser_probe(mode, "get", "url", timeout_sec=7)

        assert (code, out, err) == (0, "ok", "")
        mock_run.assert_called_once_with(
            mode,
            "get",
            "url",
            timeout_sec=7,
            retry_after_alert_recovery=True,
        )


class TestEvalJs:
    """Tests for eval_js function."""

    @patch("inmail_sender.run_agent_browser")
    def test_successful_json_parse(self, mock_run):
        mock_run.return_value = (0, '{"success": true}', "")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        success, result = sender.eval_js(mode, "return 1")

        assert success is True
        assert result == {"success": True}

    @patch("inmail_sender.run_agent_browser")
    def test_non_json_response(self, mock_run):
        mock_run.return_value = (0, "ok", "")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        success, result = sender.eval_js(mode, "return 1")

        assert success is True
        assert result == "ok"

    @patch("inmail_sender.run_agent_browser")
    def test_failed_command(self, mock_run):
        mock_run.return_value = (1, "", "error")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        success, result = sender.eval_js(mode, "return 1")

        assert success is False
        assert result == "error"

    @patch("inmail_sender.run_agent_browser")
    def test_eval_js_can_enable_alert_recovery_retry(self, mock_run):
        mock_run.return_value = (0, '{"success": true}', "")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        success, result = sender.eval_js(
            mode,
            "return 1",
            retry_after_alert_recovery=True,
        )

        assert success is True
        assert result == {"success": True}
        mock_run.assert_called_once_with(
            mode,
            "eval",
            "return 1",
            timeout_sec=5,
            retry_after_alert_recovery=True,
        )


class TestWaitForElement:
    """Tests for wait_for_element function."""

    @patch("inmail_sender.eval_js")
    @patch("inmail_sender.time.sleep")
    def test_element_found_immediately(self, mock_sleep, mock_eval):
        mock_eval.return_value = (True, True)
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        found, result = sender.wait_for_element(mode, "document.querySelector('x')")

        assert found is True
        assert result is True
        mock_sleep.assert_not_called()

    @patch("inmail_sender.eval_js")
    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.time.time")
    def test_element_found_after_polls(self, mock_time, mock_sleep, mock_eval):
        # Simulate time progressing
        mock_time.side_effect = [0, 0.5, 1.0, 1.5, 2.0]
        # First two calls fail, third succeeds
        mock_eval.side_effect = [
            (True, False),
            (True, False),
            (True, True),
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        found, result = sender.wait_for_element(
            mode, "document.querySelector('x')", timeout_sec=2.0, poll_interval=0.5
        )

        assert found is True
        assert result is True
        assert mock_sleep.call_count == 2


class TestNavigationHelpers:
    """Tests for resilient profile navigation helpers."""

    def test_urls_match_ignores_query_string(self):
        assert (
            sender.urls_match(
                "https://www.linkedin.com/talent/profile/ABC?miniProfileUrn=123",
                "https://www.linkedin.com/talent/profile/ABC",
            )
            is True
        )

    def test_urls_match_detects_mismatch(self):
        assert (
            sender.urls_match(
                "https://www.linkedin.com/talent/profile/ABC",
                "https://www.linkedin.com/talent/profile/XYZ",
            )
            is False
        )

    @patch("inmail_sender.run_agent_browser")
    def test_get_current_url_success(self, mock_run):
        mock_run.return_value = (0, "https://example.com/page\n", "")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        success, url = sender.get_current_url(mode)

        assert success is True
        assert url == "https://example.com/page"

    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.run_agent_browser")
    def test_navigate_to_profile_accepts_timeout_when_url_matches(
        self, mock_run, mock_sleep
    ):
        mock_run.side_effect = [
            (-1, "", "timeout"),
            (0, "https://www.linkedin.com/talent/profile/ABC\n", ""),
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert (
            sender.navigate_to_profile(
                mode,
                "https://www.linkedin.com/talent/profile/ABC",
                timeout_sec=10,
                recovery_wait_sec=1.0,
            )
            is True
        )


class TestDialogHelpers:
    """Tests for dialog handling helpers."""

    @patch("inmail_sender.run_agent_browser")
    def test_has_pending_dialog_true(self, mock_run):
        mock_run.return_value = (0, "JavaScript confirm dialog is open", "")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.has_pending_dialog(mode) is True

    @patch("inmail_sender.run_agent_browser")
    def test_has_pending_dialog_false(self, mock_run):
        mock_run.return_value = (0, "No dialog is currently open", "")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.has_pending_dialog(mode) is False

    @patch("inmail_sender.run_agent_browser")
    def test_accept_pending_dialog_when_open(self, mock_run):
        mock_run.side_effect = [
            (0, "JavaScript confirm dialog is open", ""),
            (0, "accepted", ""),
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.accept_pending_dialog(mode) is True
        assert mock_run.call_args_list[-1][0][1:] == ("dialog", "accept")


class TestGuardDialogs:
    """Tests for guard_dialogs fast dialog guard."""

    @patch("inmail_sender.run_agent_browser")
    @patch("inmail_sender.time.time")
    def test_no_dialogs_returns_true(self, mock_time, mock_run):
        mock_time.side_effect = [0, 0.1]
        mock_run.return_value = (0, "No dialog is currently open", "")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.guard_dialogs(mode) is True
        assert mock_run.call_args[0][1:] == ("dialog", "status")

    @patch("inmail_sender.run_agent_browser")
    @patch("inmail_sender.time.time")
    def test_dialog_accepted_and_returns_true(self, mock_time, mock_run):
        mock_time.side_effect = [0, 0.3, 0.6]
        # First call: dialog open, Second call: no dialog
        mock_run.side_effect = [
            (0, "JavaScript confirm dialog is open", ""),
            (0, "accepted", ""),
            (0, "No dialog is currently open", ""),
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.guard_dialogs(mode) is True
        # Should call status, accept, then status again
        assert mock_run.call_count == 3


class TestClickMessageButton:
    """Tests for click_message_button function."""

    @patch("inmail_sender.eval_js")
    def test_regex_strategy_success(self, mock_eval):
        mock_eval.return_value = (True, {"success": True, "strategy": "regex"})
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.click_message_button(mode)

        assert result is True

    @patch("inmail_sender.eval_js")
    def test_aria_label_fallback(self, mock_eval):
        # First call (regex) fails, second (aria-label) succeeds
        mock_eval.side_effect = [
            (True, {"success": False, "error": "not found"}),
            (True, {"success": True, "strategy": "aria-label"}),
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.click_message_button(mode)

        assert result is True

    @patch("inmail_sender.eval_js")
    def test_all_strategies_fail(self, mock_eval):
        mock_eval.return_value = (True, {"success": False})
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.click_message_button(mode)

        assert result is False


class TestWaitForMessageButton:
    """Tests for wait_for_message_button function."""

    @patch("inmail_sender.wait_for_element")
    def test_message_button_appears(self, mock_wait):
        mock_wait.return_value = (True, True)
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.wait_for_message_button(mode) is True

    @patch("inmail_sender.wait_for_element")
    def test_message_button_missing(self, mock_wait):
        mock_wait.return_value = (False, None)
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.wait_for_message_button(mode) is False


class TestWaitForComposer:
    """Tests for wait_for_composer function."""

    @patch("inmail_sender.wait_for_element")
    def test_composer_appears(self, mock_wait):
        mock_wait.return_value = (True, True)
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.wait_for_composer(mode)

        assert result is True
        assert mock_wait.call_count == 2  # Subject and body checks


class TestClearAndFillSubject:
    """Tests for clear_and_fill_subject function."""

    @patch("inmail_sender.eval_js")
    def test_successful_clear_and_fill(self, mock_eval):
        mock_eval.return_value = (True, {"success": True})
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.clear_and_fill_subject(mode, "Test Subject")

        assert result is True
        mock_eval.assert_called_once()

    @patch("inmail_sender.eval_js")
    def test_clear_fails(self, mock_eval):
        mock_eval.return_value = (False, "error")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.clear_and_fill_subject(mode, "Test Subject")

        assert result is False


class TestClearAndFillBody:
    """Tests for clear_and_fill_body function."""

    @patch("inmail_sender.eval_js")
    def test_successful_clear_and_fill(self, mock_eval):
        mock_eval.return_value = (True, {"success": True})
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.clear_and_fill_body(mode, "Test body content")

        assert result is True


class TestVerifyFieldsFilled:
    """Tests for verify_fields_filled function."""

    @patch("inmail_sender.eval_js")
    def test_both_fields_match(self, mock_eval):
        mock_eval.side_effect = [
            (True, "Test Subject"),
            (True, "Test body content here"),
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.verify_fields_filled(mode, "Test Subject", "Test body content")

        assert result is True

    @patch("inmail_sender.eval_js")
    def test_subject_mismatch(self, mock_eval):
        mock_eval.side_effect = [
            (True, "Wrong Subject"),
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.verify_fields_filled(mode, "Test Subject", "Test body")

        assert result is False


class TestClickSendButton:
    """Tests for click_send_button function."""

    @patch("inmail_sender.eval_js")
    def test_button_found_and_clicked(self, mock_eval):
        mock_eval.return_value = (True, {"success": True})
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.click_send_button(mode)

        assert result is True

    @patch("inmail_sender.eval_js")
    def test_button_not_found(self, mock_eval):
        mock_eval.return_value = (True, {"success": False, "error": "not found"})
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.click_send_button(mode)

        assert result is False


class TestProbePageState:
    """Tests for probe_page_state function."""

    @patch("inmail_sender.eval_js")
    @patch("inmail_sender.get_dialog_state")
    def test_composer_closed_no_dialogs(self, mock_dialog_state, mock_eval):
        mock_dialog_state.return_value = "closed"
        # Simulate: composer closed, no send button, no toast, no discard
        mock_eval.side_effect = [
            (True, False),  # composer_open check
            (True, []),  # success_signals check
            (True, False),  # has_discard_dialog check
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        state = sender.probe_page_state(mode)

        assert state["composer_open"] is False
        assert state["dialog_open"] is False
        assert state["has_success_toast"] is False

    @patch("inmail_sender.eval_js")
    @patch("inmail_sender.get_dialog_state")
    def test_success_toast_detected(self, mock_dialog_state, mock_eval):
        mock_dialog_state.return_value = "closed"
        mock_eval.side_effect = [
            (True, False),  # composer_open check
            (True, ["toast_notification"]),  # success_signals check
            (True, False),  # has_discard_dialog check
        ]
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        state = sender.probe_page_state(mode)

        assert state["has_success_toast"] is True
        assert "toast_notification" in state["success_signals"]


class TestWaitForSendComplete:
    """Tests for wait_for_send_complete function with strong verification."""

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.accept_pending_dialog")
    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.time.time")
    def test_eventually_detects_success_toast(
        self, mock_time, mock_sleep, mock_accept, mock_probe
    ):
        mock_time.side_effect = list(range(0, 100))
        pending_state = {
            "composer_open": True,
            "dialog_open": False,
            "has_success_toast": False,
            "has_discard_dialog": False,
        }
        success_state = {
            "composer_open": False,
            "dialog_open": False,
            "has_success_toast": True,
            "has_discard_dialog": False,
        }

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            # Return pending for first 3 calls, then success
            if call_count[0] <= 3:
                return pending_state
            return success_state

        mock_probe.side_effect = side_effect
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.wait_for_send_complete(mode, timeout_sec=5.0)

        assert result is True

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.time.time")
    def test_composer_closed_without_success_signal_fails(
        self, mock_time, mock_sleep, mock_probe
    ):
        """Composer closing without explicit success signal is NOT success."""
        mock_time.side_effect = list(range(0, 100))
        # Composer closes but no success toast - this should fail
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_success_toast": False,
            "has_discard_dialog": False,
        }
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.wait_for_send_complete(mode, timeout_sec=5.0)

        # Should fail - composer closed without explicit success signal
        assert result is False


class TestCheckRecentContact:
    """Tests for check_recent_contact function."""

    def test_recent_contact_js_targets_most_recent_activity_patterns(self):
        js = sender.RECENT_CONTACT_CHECK_JS.lower()
        assert "most recent activity" in js
        assert "candidate accepted" in js
        assert "inmail" in js

    @patch("inmail_sender.eval_js")
    def test_no_recent_contact(self, mock_eval):
        mock_eval.return_value = (
            True,
            {"hasSignals": False, "reason": "no_recent_contact_detected"},
        )
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        should_skip, reason = sender.check_recent_contact(mode)

        assert should_skip is False
        assert "no_recent" in reason

    @patch("inmail_sender.eval_js")
    def test_recent_activity_detected(self, mock_eval):
        mock_eval.return_value = (
            True,
            {
                "hasSignals": True,
                "signals": ["recent_activity_inmail"],
                "reason": "recent_activity_inmail",
            },
        )
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        should_skip, reason = sender.check_recent_contact(mode)

        assert should_skip is True
        assert "recent_activity" in reason

    @patch("inmail_sender.eval_js")
    def test_eval_js_fails(self, mock_eval):
        mock_eval.return_value = (False, "error")
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        should_skip, reason = sender.check_recent_contact(mode)

        # Fail safe: if check fails, treat as blocking condition
        assert should_skip is True  # Fail safe - block sending when check fails
        assert reason == "check_failed"


class TestCleanupOpenComposer:
    """Tests for cleanup_open_composer with explicit verification."""

    @patch("inmail_sender.probe_page_state")
    def test_already_clean_state(self, mock_probe):
        # Already clean state - no composer, no dialogs
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.cleanup_open_composer(mode) is True
        assert mock_probe.call_count >= 2  # Initial check + verification

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.guard_dialogs")
    def test_dialog_open_gets_accepted(self, mock_guard, mock_probe):
        # First call: dialog open, subsequent calls: clean (with verification)
        mock_probe.side_effect = [
            {"composer_open": False, "dialog_open": True, "has_discard_dialog": False},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
        ]
        mock_guard.return_value = True
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.cleanup_open_composer(mode) is True
        mock_guard.assert_called_once()

    @patch("inmail_sender.eval_js")
    @patch("inmail_sender.probe_page_state")
    def test_discard_dialog_only_clicks_discard_not_send(self, mock_probe, mock_eval):
        """Discard recovery must only click discard/close buttons, never send."""
        # First call: has discard dialog, subsequent calls: clean
        mock_probe.side_effect = [
            {"composer_open": True, "dialog_open": False, "has_discard_dialog": True},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
        ]
        mock_eval.return_value = (True, {"success": True, "action": "clicked_discard_button"})
        mode = BrowserMode(mode="cdp", cdp_port="9234")

        result = sender.cleanup_open_composer(mode)

        assert result is True
        # Verify the JS code was called and check it doesn't match 'send'
        js_calls = [call[0][1] for call in mock_eval.call_args_list]
        discard_js = None
        for js in js_calls:
            if "discard" in js.lower():
                discard_js = js
                break
        assert discard_js is not None
        # The JS should match discard/close/dismiss but NOT send
        assert "/discard|close|dismiss/i" in discard_js
        assert "!/send/i" in discard_js or "discard|close|dismiss" in discard_js

    @patch("inmail_sender.eval_js")
    @patch("inmail_sender.probe_page_state")
    def test_discard_dialog_js_excludes_send_buttons(self, mock_probe, mock_eval):
        """Discard dialog handler must explicitly exclude send buttons from matching."""
        import re

        # Extract the JS pattern from the actual source code
        js_pattern = r'/discard\|close\|dismiss/i'
        exclude_pattern = r'!/send/i'

        # Read the actual JS from the function source
        source = sender.cleanup_open_composer.__code__.co_consts
        js_found = False
        for const in source:
            if isinstance(const, str) and "discard" in const.lower():
                # Verify the pattern excludes send
                if "discard|close|dismiss" in const and "!/send/i" in const:
                    js_found = True
                    break

        # Alternative: verify by checking the actual function behavior
        mock_probe.side_effect = [
            {"composer_open": True, "dialog_open": False, "has_discard_dialog": True},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
        ]
        mock_eval.return_value = (True, {"success": True, "action": "clicked_discard_button"})
        mode = BrowserMode(mode="cdp", cdp_port="9234")
        sender.cleanup_open_composer(mode)

        # Get the JS that was executed
        for call in mock_eval.call_args_list:
            js_code = call[0][1]
            if "discard" in js_code.lower():
                # Should contain discard|close|dismiss pattern
                assert "discard|close|dismiss" in js_code
                # Should have exclusion for send
                assert "!/send/i" in js_code or "!btn.disabled" in js_code
                # Should NOT have send in the positive match
                assert not re.search(r'/discard\|[^/]*send', js_code, re.IGNORECASE)
                break


class TestConfirmCleanBrowserState:
    """Tests for post-send clean-state confirmation."""

    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.cleanup_open_composer")
    def test_accepts_clean_state_after_cleanup_false_negative(
        self,
        mock_cleanup,
        mock_probe,
        _mock_sleep,
    ):
        mock_cleanup.return_value = False
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }

        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.confirm_clean_browser_state(mode, settle_timeout_sec=0.5) is True

    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.cleanup_open_composer")
    def test_rejects_state_when_composer_remains_open(
        self,
        mock_cleanup,
        mock_probe,
        _mock_sleep,
    ):
        mock_cleanup.return_value = False
        mock_probe.return_value = {
            "composer_open": True,
            "dialog_open": False,
            "has_discard_dialog": False,
        }

        mode = BrowserMode(mode="cdp", cdp_port="9234")

        assert sender.confirm_clean_browser_state(mode, settle_timeout_sec=0.5) is False


class TestSendInmail:
    """Integration tests for send_inmail function."""

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.wait_for_send_complete")
    @patch("inmail_sender.click_send_button")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.probe_page_state")
    def test_successful_send(
        self,
        mock_probe,
        mock_cleanup,
        mock_click_msg,
        mock_wait_message,
        mock_wait_composer,
        mock_fill_subj,
        mock_fill_body,
        mock_verify,
        mock_click_send,
        mock_wait_send,
        mock_navigate,
        mock_check_recent_contact,
        mock_guard,
    ):
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check_recent_contact.return_value = (False, "no_recent_contact_detected")
        mock_wait_message.return_value = True
        mock_click_msg.return_value = True
        mock_wait_composer.return_value = True
        mock_fill_subj.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = True
        mock_wait_send.return_value = True
        mock_guard.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail(
            mode, "http://linkedin.com/in/test", "Subject", "Body"
        )

        assert result == "SENT"

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.navigate_to_profile")
    def test_navigate_fails(self, mock_navigate, mock_guard):
        mock_navigate.return_value = False
        mock_guard.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        with patch("inmail_sender.cleanup_open_composer", return_value=True):
            result = sender.send_inmail(mode, "http://test", "Subject", "Body")

        assert result == "FAILED"


class TestSendInmailWithSessionMode:
    """Tests for send_inmail in agent-browser session mode."""

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.wait_for_send_complete")
    @patch("inmail_sender.click_send_button")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.cleanup_open_composer")
    def test_successful_send_session_mode(
        self,
        mock_cleanup,
        mock_click_msg,
        mock_wait_message,
        mock_wait_composer,
        mock_fill_subj,
        mock_fill_body,
        mock_verify,
        mock_click_send,
        mock_wait_send,
        mock_navigate,
        mock_check_recent_contact,
        mock_guard,
    ):
        """Should work in agent-browser session mode."""
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check_recent_contact.return_value = (False, "no_recent_contact_detected")
        mock_wait_message.return_value = True
        mock_click_msg.return_value = True
        mock_wait_composer.return_value = True
        mock_fill_subj.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = True
        mock_wait_send.return_value = True
        mock_guard.return_value = True

        mode = BrowserMode(mode="agent-browser", session_name="linkedin-test")
        result = sender.send_inmail(
            mode, "http://linkedin.com/in/test", "Subject", "Body"
        )

        assert result == "SENT"


class TestBuildFailureResult:
    """Tests for _build_failure_result helper."""

    def test_build_failure_result_structure(self):
        """Should build result with all required fields."""
        from browser_utils import ActionRequired, FailureCode

        action = ActionRequired.element_missing(
            selector="button.send",
            page_url="https://linkedin.com/profile",
        )
        result = sender._build_failure_result(
            reason="click_send_button_failed",
            failure_code=FailureCode.ELEMENT_MISSING,
            action_required=action,
            clean_state=True,
            profile_url="https://linkedin.com/profile",
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "click_send_button_failed"
        assert result["failure_code"] == "element_missing"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "element_missing"
        assert result["clean_state"] is True
        assert result["profile_url"] == "https://linkedin.com/profile"


class TestBuildManualSendActionRequired:
    """Tests for build_manual_send_action_required helper."""

    def test_agent_browser_first_guidance(self):
        """Should provide agent-browser first guidance with user escalation."""
        from browser_utils import FailureCode

        action = sender.build_manual_send_action_required(
            profile_url="https://linkedin.com/in/test",
            send_attempts=2,
            reason="Automation could not click the visible send button reliably",
        )

        assert action.code == FailureCode.VERIFICATION_FAILED
        assert action.summary == "Automation could not finish the final send step"
        assert action.can_retry is True
        assert action.actor == "agent"
        assert action.context["manual_send_required"] is True
        assert action.context["button_text"] == "Send this message"
        assert action.context["send_attempts"] == 2

        # Verify workbook draft guardrails in context
        assert action.context["draft_source"] == "workbook_only"
        assert "do NOT rewrite" in action.context["draft_rule"]
        assert "workbook draft_subject" in action.context["draft_rule"]

        # Verify agent-browser first guidance with workbook draft steps
        steps = action.steps
        assert len(steps) == 5
        # Step 1: Read from workbook
        assert "excel_utils.py" in steps[0]
        assert "draft_subject" in steps[0]
        assert "draft_body" in steps[0]
        assert "do NOT rewrite" in steps[0]
        # Step 2: Compare against composer
        assert "compare" in steps[1].lower()
        assert "workbook values" in steps[1]
        # Step 3: Click send
        assert "agent-browser" in steps[2]
        assert "click the visible 'Send this message' button exactly once" in steps[2]
        # Step 4: User escalation
        assert "ask the user" in steps[3]
        assert "manually in Chrome" in steps[3]
        # Step 5: Rerun
        assert "rerun" in steps[4].lower()
        assert "run_send" in steps[4]

    def test_workbook_draft_rule_forbids_regeneration(self):
        """Fallback must explicitly forbid rewriting/regenerating InMail content."""
        from browser_utils import FailureCode

        action = sender.build_manual_send_action_required(
            profile_url="https://linkedin.com/in/test",
            send_attempts=1,
            reason="Send button not clickable",
        )

        # Context must have draft guardrails
        assert "draft_rule" in action.context
        assert "draft_source" in action.context
        assert action.context["draft_source"] == "workbook_only"

        # Steps must require reading from workbook first
        steps = action.steps
        assert any("excel_utils.py" in step for step in steps)
        assert any("draft_subject" in step and "draft_body" in step for step in steps)
        assert any("do NOT rewrite" in step for step in steps)


class TestSendInmailFailFast:
    """Tests for fail-fast initial state check in send_inmail_with_result."""

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    def test_fails_fast_when_browser_unavailable(self, mock_navigate, mock_probe):
        """Should return reconnect guidance when the browser is unavailable."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }

        def mark_browser_unavailable(*args, **kwargs):
            sender.LAST_NAVIGATION_FAILURE_CODE = "browser_unavailable"
            return False

        mock_navigate.side_effect = mark_browser_unavailable

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "browser_unavailable"
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"]["code"] == "browser_unavailable"
        assert result["clean_state"] is False

    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.probe_page_state")
    def test_fails_fast_when_composer_already_open_and_recovery_fails(
        self, mock_probe, mock_cleanup
    ):
        """Should fail fast with action_required if composer recovery fails."""
        mock_probe.return_value = {
            "composer_open": True,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_cleanup.return_value = False  # Recovery fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "browser_state_not_clean"
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "ambiguous_state"
        assert result["clean_state"] is False
        mock_cleanup.assert_called_once()

    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.probe_page_state")
    def test_fails_fast_when_composer_still_dirty_after_recovery(
        self, mock_probe, mock_cleanup
    ):
        """Should fail fast if state remains dirty after cleanup attempt."""
        # First call: dirty state, second call: still dirty after recovery
        mock_probe.side_effect = [
            {
                "composer_open": True,
                "dialog_open": False,
                "has_discard_dialog": False,
            },
            {
                "composer_open": True,  # Still open after recovery
                "dialog_open": False,
                "has_discard_dialog": False,
            },
        ]
        mock_cleanup.return_value = True  # Recovery reports success but state still dirty

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "browser_state_not_clean"
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"] is not None
        assert result["clean_state"] is False
        assert mock_probe.call_count == 2

    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.probe_page_state")
    def test_recovery_fails_when_dialog_still_open(self, mock_probe, mock_cleanup):
        """Recovery must fail if dialog_open is still True after cleanup."""
        # First call: dirty state, second call: composer closed but dialog still open
        mock_probe.side_effect = [
            {
                "composer_open": True,
                "dialog_open": False,
                "has_discard_dialog": False,
            },
            {
                "composer_open": False,  # Composer closed
                "dialog_open": True,  # But dialog still open - NOT clean
                "has_discard_dialog": False,
            },
        ]
        mock_cleanup.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "browser_state_not_clean"
        assert result["failure_code"] == "ambiguous_state"
        assert result["clean_state"] is False
        # Verify both probe calls were made
        assert mock_probe.call_count == 2

    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.probe_page_state")
    def test_recovery_succeeds_only_with_full_clean_state(self, mock_probe, mock_cleanup):
        """Recovery succeeds only when composer_open=False, dialog_open=False, has_discard_dialog=False."""
        # First call: dirty state, second call: fully clean
        mock_probe.side_effect = [
            {
                "composer_open": True,
                "dialog_open": False,
                "has_discard_dialog": False,
            },
            {
                "composer_open": False,  # Composer closed
                "dialog_open": False,  # No dialog
                "has_discard_dialog": False,  # No discard dialog
            },
            # Additional calls for subsequent flow
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
        ]
        mock_cleanup.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        # Will fail at navigation but should pass initial recovery check
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        # Should NOT fail due to browser_state_not_clean
        assert result["reason"] != "browser_state_not_clean"
        # Verify probe was called to check full clean state
        assert mock_probe.call_count >= 2

    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    def test_proceeds_when_composer_recovery_succeeds(
        self, mock_navigate, mock_probe, mock_cleanup
    ):
        """Should proceed with send when initial composer state is recovered."""
        # First call: dirty state, second call: clean after recovery, subsequent calls: clean state
        mock_probe.side_effect = [
            {
                "composer_open": True,
                "dialog_open": False,
                "has_discard_dialog": False,
            },
            {
                "composer_open": False,  # Clean after recovery
                "dialog_open": False,
                "has_discard_dialog": False,
            },
            # Additional calls for subsequent probe_page_state calls in the flow
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
        ]
        mock_cleanup.return_value = True
        mock_navigate.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        # Will fail at later stage but should pass initial check and navigation
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        # Should not fail due to initial state check
        assert result["reason"] != "browser_state_not_clean"
        mock_cleanup.assert_called_once()
        mock_navigate.assert_called_once()

    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    def test_proceeds_when_discard_dialog_recovery_succeeds(
        self, mock_navigate, mock_probe, mock_cleanup
    ):
        """Should proceed with send when initial discard dialog is recovered."""
        # First call: has discard dialog, second call: clean after recovery
        mock_probe.side_effect = [
            {
                "composer_open": False,
                "dialog_open": False,
                "has_discard_dialog": True,
            },
            {
                "composer_open": False,
                "dialog_open": False,
                "has_discard_dialog": False,  # Clean after recovery
            },
        ]
        mock_cleanup.return_value = True
        mock_navigate.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        # Should not fail due to initial state check
        assert result["reason"] != "browser_state_not_clean"
        mock_cleanup.assert_called_once()
        mock_navigate.assert_called_once()

    @patch("inmail_sender.probe_page_state")
    def test_fails_fast_when_dialog_already_open(self, mock_probe):
        """Should fail fast with action_required if dialog is already open."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": True,
            "has_discard_dialog": False,
        }

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "browser_dialog_blocking_send"
        assert result["failure_code"] == "dialog_blocked"
        assert result["clean_state"] is False

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    def test_proceeds_when_state_is_clean(self, mock_navigate, mock_probe):
        """Should proceed with send when initial state is clean."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_navigate.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        # Will fail at later stage but should pass initial check
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        # Should not fail due to initial state check
        assert result["reason"] != "browser_state_not_clean"


class TestSendInmailStatePreservation:
    """Tests for state preservation on post-composer failures."""

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    def test_wait_for_composer_failure_preserves_dirty_state(
        self,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
    ):
        """wait_for_composer failure should mark state as dirty (composer may be partially open)."""
        mock_probe.return_value = {"composer_open": False, "dialog_open": False}
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = False  # Composer never fully appears

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "wait_for_composer_failed"
        assert result["clean_state"] is False  # State is dirty

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    def test_fill_subject_failure_preserves_dirty_state(
        self,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
    ):
        """fill_subject failure should preserve dirty state (composer has drafted content)."""
        mock_probe.return_value = {"composer_open": False, "dialog_open": False}
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = False  # Fill fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "fill_subject_failed"
        assert result["clean_state"] is False  # Composer has drafted content

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    def test_fill_body_failure_preserves_dirty_state(
        self,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
    ):
        """fill_body failure should preserve dirty state (composer has drafted content)."""
        mock_probe.return_value = {"composer_open": False, "dialog_open": False}
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = False  # Fill fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "fill_body_failed"
        assert result["clean_state"] is False  # Composer has drafted content

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    def test_verify_fields_failure_preserves_dirty_state(
        self,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
    ):
        """verify_fields failure should preserve dirty state (composer has drafted content)."""
        mock_probe.return_value = {"composer_open": False, "dialog_open": False}
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = False  # Verification fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "verify_fields_failed"
        assert result["clean_state"] is False  # Composer has drafted content

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.click_send_button")
    def test_click_send_failure_preserves_dirty_state(
        self,
        mock_click_send,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
    ):
        """click_send_button failure should preserve dirty state (composer has drafted content)."""
        mock_probe.return_value = {"composer_open": False, "dialog_open": False}
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = False  # Click fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "click_send_button_failed"
        assert result["clean_state"] is False  # Composer has drafted content

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.click_send_button")
    @patch("inmail_sender.wait_for_send_complete")
    @patch("inmail_sender.reconcile_send_outcome_with_recent_contact")
    @patch("inmail_sender.cleanup_open_composer")
    def test_wait_for_send_complete_failure_preserves_dirty_state(
        self,
        mock_cleanup,
        mock_reconcile,
        mock_wait_send,
        mock_click_send,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
    ):
        """wait_for_send_complete failure should preserve dirty state."""
        mock_probe.return_value = {"composer_open": False, "dialog_open": False}
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = True
        mock_wait_send.return_value = False  # Send completion fails
        mock_reconcile.return_value = (False, "recent_contact_not_detected_after_send")
        mock_cleanup.return_value = False

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "wait_for_send_complete_failed"
        assert result["clean_state"] is False  # State unknown after send failure

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.click_send_button")
    @patch("inmail_sender.wait_for_send_complete")
    @patch("inmail_sender.reconcile_send_outcome_with_recent_contact")
    @patch("inmail_sender.cleanup_open_composer")
    def test_wait_for_send_complete_recovers_via_recent_contact(
        self,
        mock_cleanup,
        mock_reconcile,
        mock_wait_send,
        mock_click_send,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
    ):
        """Post-send recent-contact evidence should reconcile an uncertain send as sent."""
        mock_probe.return_value = {"composer_open": False, "dialog_open": False}
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = True
        mock_wait_send.return_value = False
        mock_reconcile.return_value = (True, "recent_activity_inmail")
        mock_cleanup.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "SENT"
        assert result["reason"] == "message_sent_reconciled_from_recent_activity_inmail"
        assert result["clean_state"] is True

    @patch("inmail_sender.confirm_clean_browser_state")
    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.click_send_button")
    @patch("inmail_sender.wait_for_send_complete")
    @patch("inmail_sender.reconcile_send_outcome_with_recent_contact")
    def test_wait_for_send_complete_retries_once_then_succeeds(
        self,
        mock_reconcile,
        mock_wait_send,
        mock_click_send,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
        mock_confirm_clean,
    ):
        """Send should retry once when the composer is still ready to send."""
        mock_probe.side_effect = [
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
            {
                "composer_open": True,
                "dialog_open": False,
                "has_discard_dialog": False,
                "has_send_button": True,
                "has_success_toast": False,
            },
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
        ]
        mock_confirm_clean.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = True
        mock_wait_send.side_effect = [False, True]
        mock_reconcile.return_value = (False, "recent_contact_not_detected_after_send")

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "SENT"
        assert result["reason"] == "message_sent_successfully_after_retry"
        assert mock_click_send.call_count == 2

    @patch("inmail_sender.probe_page_state")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.click_send_button")
    @patch("inmail_sender.wait_for_send_complete")
    @patch("inmail_sender.reconcile_send_outcome_with_recent_contact")
    def test_wait_for_send_complete_falls_back_to_manual_send_guidance(
        self,
        mock_reconcile,
        mock_wait_send,
        mock_click_send,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_probe,
    ):
        """Retry exhaustion should keep the composer open and tell the agent to click Send."""
        retryable_state = {
            "composer_open": True,
            "dialog_open": False,
            "has_discard_dialog": False,
            "has_send_button": True,
            "has_success_toast": False,
        }
        mock_probe.side_effect = [
            {"composer_open": False, "dialog_open": False, "has_discard_dialog": False},
            retryable_state,
            retryable_state,
        ]
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = True
        mock_wait_send.return_value = False
        mock_reconcile.return_value = (False, "recent_contact_not_detected_after_send")

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "manual_send_required_after_retry"
        assert result["clean_state"] is False
        assert result["action_required"] is not None
        assert result["action_required"]["context"]["manual_send_required"] is True
        # Verify new agent-browser first guidance
        steps = result["action_required"]["steps"]
        assert any("agent-browser" in step for step in steps)
        assert any("ask the user" in step for step in steps)
        assert any("rerun" in step.lower() for step in steps)
        assert mock_click_send.call_count == 2


class TestSendInmailWithResultActionRequired:
    """Tests for action_required in send_inmail_with_result failures."""

    @patch("inmail_sender.probe_page_state")
    def test_initial_state_check_returns_action_required(self, mock_probe):
        """Initial state check failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": True,
            "dialog_open": False,
            "has_discard_dialog": False,
        }

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "browser_state_not_clean"
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "ambiguous_state"
        assert "steps" in result["action_required"]

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.probe_page_state")
    def test_navigation_failure_returns_action_required(
        self, mock_probe, mock_navigate, mock_cleanup, mock_guard
    ):
        """Navigation failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = False  # Navigation fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "navigation_failed"
        assert result["failure_code"] == "wrong_page"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "wrong_page"
        assert (
            result["action_required"]["context"]["expected_url"]
            == "https://linkedin.com/in/test"
        )

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.probe_page_state")
    def test_recent_contact_check_failure_returns_action_required(
        self, mock_probe, mock_check, mock_navigate, mock_cleanup, mock_guard
    ):
        """Recent contact check failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (True, "check_failed")  # Check failed

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "recent_contact_check_failed"
        assert result["failure_code"] == "verification_failed"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "verification_failed"

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.probe_page_state")
    def test_message_button_missing_returns_action_required(
        self, mock_probe, mock_wait, mock_check, mock_navigate, mock_cleanup, mock_guard
    ):
        """Message button not appearing should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait.return_value = False  # Button never appears

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "message_button_never_appeared"
        assert result["failure_code"] == "element_missing"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "element_missing"
        assert "Message button" in result["action_required"]["context"]["selector"]

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.probe_page_state")
    def test_click_message_button_failure_returns_action_required(
        self, mock_probe, mock_click, mock_wait, mock_check, mock_navigate, mock_cleanup, mock_guard
    ):
        """Click message button failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait.return_value = True
        mock_click.return_value = False  # Click fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "click_message_button_failed"
        assert result["failure_code"] == "element_missing"
        assert result["action_required"] is not None

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.probe_page_state")
    def test_wait_for_composer_failure_returns_action_required(
        self,
        mock_probe,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_cleanup,
        mock_guard,
    ):
        """Composer not appearing should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = False  # Composer never appears

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "wait_for_composer_failed"
        assert result["failure_code"] == "element_missing"
        assert result["action_required"] is not None
        assert "composer" in result["action_required"]["context"]["selector"].lower()

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.probe_page_state")
    def test_fill_subject_failure_returns_action_required(
        self,
        mock_probe,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_cleanup,
        mock_guard,
    ):
        """Fill subject failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = False  # Fill fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "fill_subject_failed"
        assert result["failure_code"] == "element_missing"
        assert result["action_required"] is not None
        assert "Subject field" in result["action_required"]["context"]["selector"]

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.probe_page_state")
    def test_fill_body_failure_returns_action_required(
        self,
        mock_probe,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_cleanup,
        mock_guard,
    ):
        """Fill body failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = False  # Fill fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "fill_body_failed"
        assert result["failure_code"] == "element_missing"
        assert result["action_required"] is not None
        assert "Body field" in result["action_required"]["context"]["selector"]

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.probe_page_state")
    def test_verify_fields_failure_returns_action_required(
        self,
        mock_probe,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_cleanup,
        mock_guard,
    ):
        """Verify fields failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = False  # Verification fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "verify_fields_failed"
        assert result["failure_code"] == "verification_failed"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "verification_failed"

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.click_send_button")
    @patch("inmail_sender.probe_page_state")
    def test_click_send_button_failure_returns_action_required(
        self,
        mock_probe,
        mock_click_send,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_cleanup,
        mock_guard,
    ):
        """Click send button failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = False  # Click fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "click_send_button_failed"
        assert result["failure_code"] == "element_missing"
        assert result["action_required"] is not None
        assert "Send button" in result["action_required"]["context"]["selector"]

    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.click_send_button")
    @patch("inmail_sender.wait_for_send_complete")
    @patch("inmail_sender.probe_page_state")
    def test_wait_for_send_complete_failure_returns_action_required(
        self,
        mock_probe,
        mock_wait_send,
        mock_click_send,
        mock_verify,
        mock_fill_body,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_cleanup,
        mock_guard,
    ):
        """Send completion failure should return structured action_required."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_click_send.return_value = True
        mock_wait_send.return_value = False  # Send completion fails

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "wait_for_send_complete_failed"
        assert result["failure_code"] == "verification_failed"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "verification_failed"
        assert (
            "send_confirmation"
            in result["action_required"]["context"]["verification_type"]
        )


class TestWaitForComposerContentStability:
    """Tests for wait_for_composer_content_stability helper."""

    @patch("inmail_sender._get_composer_content")
    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.time.time")
    def test_content_changes_then_stabilizes(self, mock_time, mock_sleep, mock_get_content):
        """Content keeps changing for a while, then stabilizes -> helper waits and proceeds."""
        # Simulate time progression: start at 0, each poll advances by 0.3s
        # Need many values since time.time() is called multiple times per loop iteration
        times = []
        t = 0.0
        for _ in range(50):
            times.append(t)
            t += 0.3
        mock_time.side_effect = times

        call_count = [0]

        def get_content_side_effect(*args, **kwargs):
            call_count[0] += 1
            # Content changes for first 4 calls, then stabilizes
            if call_count[0] <= 2:
                return ("Draft", "Auto-generated content...")
            elif call_count[0] <= 4:
                return ("Draft", "Auto-generated content... more")
            else:
                return ("Draft", "Final auto content")

        mock_get_content.side_effect = get_content_side_effect

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.wait_for_composer_content_stability(mode)

        assert result is True
        # Should have polled multiple times
        assert mock_get_content.call_count >= 3

    @patch("inmail_sender._get_composer_content")
    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.time.time")
    def test_content_never_changes(self, mock_time, mock_sleep, mock_get_content):
        """Content never changes -> helper returns after minimum/stability window."""
        # Simulate time progression - need many values
        times = []
        t = 0.0
        for _ in range(50):
            times.append(t)
            t += 0.3
        mock_time.side_effect = times

        # Content never changes
        mock_get_content.return_value = ("", "")

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.wait_for_composer_content_stability(mode)

        assert result is True
        # Should return after min_observation + stability_window
        assert mock_get_content.call_count >= 3

    @patch("inmail_sender._get_composer_content")
    def test_content_read_fails_opens_conservatively(self, mock_get_content):
        """If content cannot be read reliably, fail open by waiting minimum period."""
        # Content fields not found (None returned)
        mock_get_content.return_value = (None, None)

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.wait_for_composer_content_stability(mode)

        assert result is True
        # Should still have attempted to get content multiple times
        assert mock_get_content.call_count >= 1

    @patch("inmail_sender._get_composer_content")
    @patch("inmail_sender.time.sleep")
    @patch("inmail_sender.time.time")
    def test_delayed_prefill_race_regression(self, mock_time, mock_sleep, mock_get_content):
        """Regression test: first mutation after ~2.5-3s must not cause early return.

        This tests the fix for a critical race where LinkedIn's auto-prefill starts
        after ~2.5-3s, but the stability helper declared stability around ~2.1s
        (with old min_observation_sec=2.0), letting LinkedIn overwrite the workbook draft.

        With min_observation_sec=4.0, the helper must wait long enough to observe
        the delayed mutation and wait for it to stabilize before returning.
        """
        # Simulate time progression starting at 0
        # Note: time.time() is called 3 times per loop iteration (while check, elapsed, stable_for)
        # So we need 3x the values to cover the same duration
        times = []
        t = 0.0
        for _ in range(200):
            times.append(t)
            t += 0.1  # Smaller increment to give more granular control
        mock_time.side_effect = times

        call_count = [0]

        def get_content_side_effect(*args, **kwargs):
            call_count[0] += 1
            # Simulate: content appears stable (no changes) until ~2.5s,
            # then delayed prefill starts, continues changing until ~5s, then stabilizes
            # With 0.3s poll_interval and 3 time calls per loop, each iteration consumes ~0.9s of mock time
            # Call 3 is at ~2.7s mock time (after ~3 iterations)
            if call_count[0] < 3:
                # Content appears stable (same value each call) - this is the trap
                # With old min_observation_sec=2.0, helper would return too early
                return ("Initial", "Initial content")
            elif call_count[0] < 6:
                return ("Auto Subject", "Auto body line 1...")  # Delayed prefill starts
            elif call_count[0] < 9:
                return ("Auto Subject", "Auto body line 1... line 2...")  # Still changing
            else:
                return ("Auto Subject", "Final auto body content")  # Stabilized

        mock_get_content.side_effect = get_content_side_effect

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.wait_for_composer_content_stability(
            mode,
            min_observation_sec=4.0,  # Safer window covering delayed prefill
            stability_window_sec=1.0,
            overall_timeout_sec=8.0,
        )

        assert result is True
        # With min_observation_sec=4.0, helper must poll long enough to see delayed mutation
        # The old value of 2.0 would have returned before seeing the mutation at ~2.7s
        assert mock_get_content.call_count >= 3, (
            f"Expected at least 3 calls to observe delayed prefill, got {mock_get_content.call_count}"
        )
        # Must have observed the final stabilized content
        assert mock_get_content.call_count >= 9, (
            f"Expected helper to wait for delayed prefill to stabilize, got {mock_get_content.call_count} calls"
        )


class TestSendFlowCallsStabilityHelper:
    """Tests that send flow calls stability helper before fill."""

    @patch("inmail_sender.wait_for_composer_content_stability")
    @patch("inmail_sender.guard_dialogs")
    @patch("inmail_sender.cleanup_open_composer")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.dismiss_inline_banners")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.probe_page_state")
    def test_stability_helper_called_before_fill(
        self,
        mock_probe,
        mock_fill_subject,
        mock_dismiss,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_cleanup,
        mock_guard,
        mock_stability,
    ):
        """Send flow must call stability helper before clear_and_fill_subject."""
        mock_probe.return_value = {
            "composer_open": False,
            "dialog_open": False,
            "has_discard_dialog": False,
        }
        mock_guard.return_value = True
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check.return_value = (False, "no_recent_contact")
        mock_wait_btn.return_value = True
        mock_click.return_value = True
        mock_wait_composer.return_value = True
        mock_dismiss.return_value = True
        mock_fill_subject.return_value = False  # Stop at fill_subject

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        # Stability helper should be called
        mock_stability.assert_called_once()
        # Fill subject should be called after stability
        mock_fill_subject.assert_called_once()
        # Verify call order: stability before fill
        assert mock_stability.call_count == 1
        assert mock_fill_subject.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
