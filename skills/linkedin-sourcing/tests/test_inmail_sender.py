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

    def test_provided_port_creates_cdp_mode(self):
        """Should create CDP mode when port provided."""
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
    def test_fallback_to_env_var(self, mock_get_mode):
        """Should fallback to environment variable."""
        mock_get_mode.return_value = None

        mode = sender.resolve_browser_mode_with_fallback(work_dir=Path("/tmp"))

        assert mode.mode == "cdp"
        assert mode.cdp_port == "9333"

    @patch("inmail_sender.get_browser_mode")
    def test_fallback_to_default(self, mock_get_mode):
        """Should fallback to default port."""
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
    def test_successful_send(
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
    @patch("inmail_sender.check_recent_contact")
    @patch("inmail_sender.navigate_to_profile")
    @patch("inmail_sender.verify_fields_filled")
    @patch("inmail_sender.clear_and_fill_body")
    @patch("inmail_sender.clear_and_fill_subject")
    @patch("inmail_sender.wait_for_composer")
    @patch("inmail_sender.wait_for_message_button")
    @patch("inmail_sender.click_message_button")
    @patch("inmail_sender.cleanup_open_composer")
    def test_verify_only_mode(
        self,
        mock_cleanup,
        mock_click_msg,
        mock_wait_message,
        mock_wait_composer,
        mock_fill_subj,
        mock_fill_body,
        mock_verify,
        mock_navigate,
        mock_check_recent_contact,
        mock_guard,
    ):
        mock_cleanup.return_value = True
        mock_navigate.return_value = True
        mock_check_recent_contact.return_value = (False, "no_recent_contact_detected")
        mock_wait_message.return_value = True
        mock_click_msg.return_value = True
        mock_wait_composer.return_value = True
        mock_fill_subj.return_value = True
        mock_fill_body.return_value = True
        mock_verify.return_value = True
        mock_guard.return_value = True

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail(
            mode,
            "http://linkedin.com/in/test",
            "Subject",
            "Body",
            verify_only=True,
        )

        assert result == "VERIFIED"

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
            verify_only=False,
            profile_url="https://linkedin.com/profile",
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "click_send_button_failed"
        assert result["failure_code"] == "element_missing"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "element_missing"
        assert result["clean_state"] is True
        assert result["verify_only"] is False
        assert result["profile_url"] == "https://linkedin.com/profile"


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

    @patch("inmail_sender.probe_page_state")
    def test_fails_fast_when_composer_already_open(self, mock_probe):
        """Should fail fast with action_required if composer is already open."""
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
        assert result["clean_state"] is False

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
    def test_wait_for_send_complete_failure_preserves_dirty_state(
        self,
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

        mode = BrowserMode(mode="cdp", cdp_port="9234")
        result = sender.send_inmail_with_result(
            mode, "https://linkedin.com/in/test", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "wait_for_send_complete_failed"
        assert result["clean_state"] is False  # State unknown after send failure


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
    def test_navigation_failure_returns_action_required(
        self, mock_navigate, mock_cleanup, mock_guard
    ):
        """Navigation failure should return structured action_required."""
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
    def test_recent_contact_check_failure_returns_action_required(
        self, mock_check, mock_navigate, mock_cleanup, mock_guard
    ):
        """Recent contact check failure should return structured action_required."""
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
    def test_message_button_missing_returns_action_required(
        self, mock_wait, mock_check, mock_navigate, mock_cleanup, mock_guard
    ):
        """Message button not appearing should return structured action_required."""
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
    def test_click_message_button_failure_returns_action_required(
        self, mock_click, mock_wait, mock_check, mock_navigate, mock_cleanup, mock_guard
    ):
        """Click message button failure should return structured action_required."""
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
    def test_wait_for_composer_failure_returns_action_required(
        self,
        mock_wait_composer,
        mock_click,
        mock_wait_btn,
        mock_check,
        mock_navigate,
        mock_cleanup,
        mock_guard,
    ):
        """Composer not appearing should return structured action_required."""
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
    def test_fill_subject_failure_returns_action_required(
        self,
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
    def test_fill_body_failure_returns_action_required(
        self,
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
    def test_verify_fields_failure_returns_action_required(
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
        mock_cleanup,
        mock_guard,
    ):
        """Verify fields failure should return structured action_required."""
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
    def test_click_send_button_failure_returns_action_required(
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
        mock_cleanup,
        mock_guard,
    ):
        """Click send button failure should return structured action_required."""
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
    def test_wait_for_send_complete_failure_returns_action_required(
        self,
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
