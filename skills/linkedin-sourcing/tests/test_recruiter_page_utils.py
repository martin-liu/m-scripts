#!/usr/bin/env python3
"""Tests for recruiter_page_utils.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_recruiter_page_utils.py -v
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import recruiter_page_utils as rpu
from recruiter_page_utils import PageState, PageStateProbe, RecoveryHelper


class TestPageStateEnum:
    """Tests for PageState enum."""

    def test_enum_values(self):
        """Should have expected state values."""
        assert PageState.READY.value == "ready"
        assert PageState.LOADING.value == "loading"
        assert PageState.BAD_PAGE.value == "bad_page"
        assert (
            PageState.LOGGED_OUT_OR_WRONG_PRODUCT.value == "logged_out_or_wrong_product"
        )
        assert PageState.BLOCKED_OR_CAPTCHA.value == "blocked_or_captcha"
        assert PageState.DIALOG_BLOCKED.value == "dialog_blocked"
        assert PageState.CONTRACT_CHOOSER.value == "contract_chooser"
        assert PageState.UNKNOWN.value == "unknown"


class TestPageStateProbe:
    """Tests for PageStateProbe class."""

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_classify_ready_state(self, mock_run, mock_dialog):
        """Should classify ready state correctly."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
                "title": "Recruiter Search",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": True,
                "readyState": "complete",
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "ready"
        assert result["dialog_info"] is None
        assert "timestamp" in result

    @patch("recruiter_page_utils.check_dialog_status")
    def test_classify_dialog_blocked(self, mock_dialog):
        """Should detect dialog blocked state."""
        mock_dialog.return_value = {
            "has_dialog": True,
            "dialog_type": "alert",
            "message": "Session expired",
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "dialog_blocked"
        assert result["dialog_info"]["has_dialog"] is True
        assert result["dialog_info"]["dialog_type"] == "alert"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_classify_404_state(self, mock_run, mock_dialog):
        """Should classify 404/bad page state."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/404",
                "title": "Page not found",
                "is404": True,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "bad_page"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_classify_blocked_state(self, mock_run, mock_dialog):
        """Should classify CAPTCHA/blocked state."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/",
                "title": "Security Check",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": True,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "blocked_or_captcha"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_classify_logged_out_state(self, mock_run, mock_dialog):
        """Should classify logged out state."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/login",
                "title": "Login",
                "is404": False,
                "isLoginPage": True,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "logged_out_or_wrong_product"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_classify_loading_state(self, mock_run, mock_dialog):
        """Should classify loading state."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
                "title": "Recruiter",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": True,
                "hasRecruiterContent": False,
                "readyState": "interactive",
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "loading"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_classify_error_state(self, mock_run, mock_dialog):
        """Should handle browser command errors."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {"error": "Connection refused", "parsed": None}

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "unknown"
        assert "error" in result["details"]

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_is_ready_quick_check(self, mock_run, mock_dialog):
        """Should provide quick ready check."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        assert probe.is_ready() is True

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_is_blocked_quick_check(self, mock_run, mock_dialog):
        """Should provide quick blocked check."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "is404": False,
                "isLoginPage": True,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        assert probe.is_blocked() is True


class TestRecoveryHelper:
    """Tests for RecoveryHelper class."""

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_recovery_already_ready(self, mock_run, mock_dialog):
        """Should return success if already ready."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }

        helper = RecoveryHelper("9230")
        result = helper.attempt_recovery()

        assert result["success"] is True
        assert result["final_state"] == "ready"
        assert result["attempts_made"] == 0

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.time.sleep")
    def test_recovery_from_bad_page_with_navigate(
        self, mock_sleep, mock_run, mock_dialog
    ):
        """Should recover from bad page by navigating to target URL."""
        # Recovery loop makes exactly 6 calls to run_browser_command:
        # 1. Initial classify_state, 2. Loop check (attempt 1),
        # 3. _navigate_to_url (goto), 4. Loop check (attempt 2),
        # 5. _refresh_page (eval), 6. Final classify_state
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.side_effect = [
            # 1. Initial classify_state (bad page)
            {
                "parsed": {
                    "url": "https://linkedin.com/404",
                    "is404": True,
                    "isLoginPage": False,
                    "isWrongProduct": False,
                    "isBlocked": False,
                    "isLoading": False,
                    "hasRecruiterContent": False,
                },
                "error": None,
            },
            # 2. Loop attempt 1, classify_state (still bad)
            {
                "parsed": {
                    "url": "https://linkedin.com/404",
                    "is404": True,
                    "isLoginPage": False,
                    "isWrongProduct": False,
                    "isBlocked": False,
                    "isLoading": False,
                    "hasRecruiterContent": False,
                },
                "error": None,
            },
            # 3. _navigate_to_url now uses run_browser_command (goto)
            {"stdout": "", "stderr": "", "returncode": 0, "error": None},
            # 4. Loop attempt 2, classify_state (still bad, triggers refresh)
            {
                "parsed": {
                    "url": "https://linkedin.com/404",
                    "is404": True,
                    "isLoginPage": False,
                    "isWrongProduct": False,
                    "isBlocked": False,
                    "isLoading": False,
                    "hasRecruiterContent": False,
                },
                "error": None,
            },
            # 5. _refresh_page now uses run_browser_command (eval)
            {"stdout": "", "stderr": "", "returncode": 0, "error": None},
            # 6. Final classify_state (ready after recovery)
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/projects",
                    "is404": False,
                    "isLoginPage": False,
                    "isWrongProduct": False,
                    "isBlocked": False,
                    "isLoading": False,
                    "hasRecruiterContent": True,
                },
                "error": None,
            },
        ]

        helper = RecoveryHelper("9230", max_attempts=2)
        result = helper.attempt_recovery(
            target_url="https://linkedin.com/talent/projects"
        )

        assert result["success"] is True
        assert result["final_state"] == "ready"
        assert len(result["actions_taken"]) > 0
        assert any("navigate" in a for a in result["actions_taken"])

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_non_recoverable_blocked(self, mock_run, mock_dialog):
        """Should not attempt recovery for blocked states."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": True,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        helper = RecoveryHelper("9230")
        result = helper.attempt_recovery()

        assert result["success"] is False
        assert "blocked_or_captcha" in result["error"]
        assert result["attempts_made"] == 0

    @patch("recruiter_page_utils.check_dialog_status")
    def test_non_recoverable_dialog(self, mock_dialog):
        """Should not attempt recovery for dialog blocked state."""
        mock_dialog.return_value = {
            "has_dialog": True,
            "dialog_type": "confirm",
            "message": "Are you sure?",
        }

        helper = RecoveryHelper("9230")
        result = helper.attempt_recovery()

        assert result["success"] is False
        assert result["final_state"] == "dialog_blocked"
        assert "dialog" in result["error"].lower()

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.subprocess.run")
    @patch("recruiter_page_utils.time.sleep")
    def test_recovery_max_attempts_exceeded(
        self, mock_sleep, mock_subprocess, mock_run, mock_dialog
    ):
        """Should fail after max attempts."""
        mock_dialog.return_value = {"has_dialog": False}
        # Always return bad page
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/404",
                "is404": True,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }
        mock_subprocess.return_value = Mock(returncode=0)

        helper = RecoveryHelper("9230", max_attempts=2)
        result = helper.attempt_recovery()

        assert result["success"] is False
        assert result["attempts_made"] == 2
        assert "failed after 2 attempts" in result["error"]

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_browser_unavailable_returns_connect_guidance(self, mock_run, mock_dialog):
        """Should return browser_unavailable with reconnect guidance."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": None,
            "error": "Browser not available in cdp mode",
        }

        helper = RecoveryHelper("9230")
        result = helper.attempt_recovery()

        assert result["success"] is False
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"]["code"] == "browser_unavailable"


class TestBrowserUnavailableReadiness:
    """Tests for browser unavailable readiness failures."""

    @patch("recruiter_page_utils.PageStateProbe.is_ready")
    @patch("recruiter_page_utils.PageStateProbe.is_blocked")
    @patch("recruiter_page_utils.RecoveryHelper.attempt_recovery")
    @patch("recruiter_page_utils.PageStateProbe.classify_state")
    def test_ensure_page_ready_surfaces_browser_unavailable(
        self,
        mock_classify,
        mock_recovery,
        mock_is_blocked,
        mock_is_ready,
    ):
        """ensure_page_ready should preserve browser_unavailable failure details."""
        mock_is_ready.return_value = False
        mock_is_blocked.return_value = False
        mock_recovery.return_value = {
            "success": False,
            "action_required": {
                "code": "browser_unavailable",
                "summary": "Chrome browser is not available for automation",
                "steps": ["reconnect"],
                "can_retry": True,
                "context": {},
            },
            "failure_code": "browser_unavailable",
        }
        mock_classify.return_value = {
            "state": "unknown",
            "details": {
                "error": "Browser not available in cdp mode",
                "failure_code": "browser_unavailable",
            },
        }

        result = rpu.ensure_page_ready("9230")

        assert result["ready"] is False
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"]["code"] == "browser_unavailable"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.time.sleep")
    def test_recovery_from_loading_state(self, mock_sleep, mock_run, mock_dialog):
        """Should handle loading state recovery."""
        mock_dialog.return_value = {"has_dialog": False}
        loading_state = {
            "parsed": {
                "url": "https://linkedin.com/talent/",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": True,
                "hasRecruiterContent": False,
                "readyState": "loading",
            },
            "error": None,
        }
        ready_state = {
            "parsed": {
                "url": "https://linkedin.com/talent/",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }
        # Need more side effects for the recovery loop
        mock_run.side_effect = [
            loading_state,  # Initial check
            loading_state,  # Check in loop
            loading_state,  # After wait
            ready_state,  # Final check
        ]

        helper = RecoveryHelper("9230", max_attempts=2)
        result = helper.attempt_recovery()

        assert result["success"] is True
        assert result["final_state"] == "ready"
        assert len(result["actions_taken"]) > 0

    def test_incident_writing(self, tmp_path):
        """Should write incident on unrecoverable state."""
        with (
            patch("recruiter_page_utils.check_dialog_status") as mock_dialog,
            patch("recruiter_page_utils.run_browser_command") as mock_run,
        ):
            mock_dialog.return_value = {"has_dialog": False}
            mock_run.return_value = {
                "parsed": {
                    "url": "https://linkedin.com/talent/",
                    "is404": False,
                    "isLoginPage": False,
                    "isWrongProduct": False,
                    "isBlocked": True,
                    "isLoading": False,
                    "hasRecruiterContent": False,
                },
                "error": None,
            }

            helper = RecoveryHelper("9230", work_dir=tmp_path)
            result = helper.attempt_recovery(context="test_context")

            # Check incident was written
            incidents_dir = tmp_path / "runtime" / "incidents"
            assert incidents_dir.exists()
            incident_files = list(incidents_dir.glob("*.json"))
            assert len(incident_files) == 1

            incident = json.loads(incident_files[0].read_text())
            # Check browser_mode is recorded (can be string or dict)
            assert "browser_mode" in incident
            assert incident["context"] == "test_context"
            assert incident["state"] == "blocked_or_captcha"


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_with_recovery_function(self, mock_run, mock_dialog):
        """Should work as convenience function."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }

        result = rpu.with_recovery("9230")

        assert result["success"] is True
        assert result["final_state"] == "ready"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_ensure_page_ready_already_ready(self, mock_run, mock_dialog):
        """Should return quickly if page already ready."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }

        result = rpu.ensure_page_ready("9230")

        assert result["ready"] is True
        assert result["state"] == "ready"
        assert result["recovery_result"] is None

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_ensure_page_ready_blocked(self, mock_run, mock_dialog):
        """Should detect blocked state without recovery."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "is404": False,
                "isLoginPage": True,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        result = rpu.ensure_page_ready("9230")

        assert result["ready"] is False
        assert result["state"] == "logged_out_or_wrong_product"
        assert result["recovery_result"] is None


class TestContractChooserDetection:
    """Tests for contract chooser page detection and recovery."""

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_contract_chooser_classification_beats_loading(self, mock_run, mock_dialog):
        """Contract chooser detection should take precedence over loading state.

        Issue: LinkedIn contract chooser page has loading wrappers present,
        but should be classified as CONTRACT_CHOOSER, not LOADING.
        """
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/contract-chooser?destUrl=%2Ftalent%2Fhome",
                "title": "Choose a Contract - LinkedIn Recruiter",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isContractChooser": True,
                "hasCorporateContract": True,
                "contractCardCount": 2,
                "isLoading": True,  # Loading wrappers present
                "hasLoadingIndicator": True,
                "hasExplicitLoadingText": False,
                "hasRecruiterContent": False,
                "hasProjectsListContent": False,
                "hasOverviewContent": False,
                "hasSearchResultsContent": False,
                "readyState": "complete",
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "contract_chooser", (
            f"Expected CONTRACT_CHOOSER for contract chooser page with loading wrappers, "
            f"got {result['state']}. Details: {result['details']}"
        )

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_contract_chooser_by_url_path(self, mock_run, mock_dialog):
        """Should detect contract chooser by URL path."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/contract-chooser",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isContractChooser": True,
                "hasCorporateContract": False,
                "contractCardCount": 1,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "contract_chooser"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_contract_chooser_by_body_text(self, mock_run, mock_dialog):
        """Should detect contract chooser by body text heuristics."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/contract-chooser",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isContractChooser": True,  # Detected via "choose a contract" text
                "hasCorporateContract": False,
                "contractCardCount": 3,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "contract_chooser"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.time.sleep")
    def test_recovery_prefers_corporate_contract(
        self, mock_sleep, mock_run, mock_dialog
    ):
        """Recovery should prefer corporate contract when available."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_sleep.return_value = None

        contract_chooser_state = {
            "parsed": {
                "url": "https://linkedin.com/talent/contract-chooser",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isContractChooser": True,
                "hasCorporateContract": True,
                "contractCardCount": 2,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        ready_state = {
            "parsed": {
                "url": "https://linkedin.com/talent/home",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isContractChooser": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }

        # Recovery flow with max_attempts=2:
        # 1. Initial classify_state (before loop)
        # 2. Loop attempt 1: classify_state (contract chooser)
        # 3. _select_contract JS execution
        # 4. Loop attempt 1: classify_state (check after selection - now ready)
        # 5. Final classify_state (after loop)
        mock_run.side_effect = [
            contract_chooser_state,  # Initial check
            contract_chooser_state,  # Loop check (attempt 1)
            {
                "parsed": {"success": True, "selected": "Corporate Contract"},
                "error": None,
            },  # Select
            ready_state,  # Check after selection - now ready
            ready_state,  # Final check
        ]

        helper = RecoveryHelper("9230", max_attempts=2)
        result = helper.attempt_recovery()

        assert result["success"] is True
        assert result["final_state"] == "ready"
        assert any("select_contract" in a for a in result["actions_taken"])

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.time.sleep")
    def test_recovery_fallback_to_first_contract(
        self, mock_sleep, mock_run, mock_dialog
    ):
        """Recovery should fallback to first contract when no corporate option."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_sleep.return_value = None

        contract_chooser_state = {
            "parsed": {
                "url": "https://linkedin.com/talent/contract-chooser",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isContractChooser": True,
                "hasCorporateContract": False,  # No corporate option
                "contractCardCount": 2,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        ready_state = {
            "parsed": {
                "url": "https://linkedin.com/talent/home",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isContractChooser": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }

        # Recovery flow with max_attempts=2:
        # 1. Initial classify_state (before loop)
        # 2. Loop attempt 1: classify_state (contract chooser)
        # 3. _select_contract JS execution
        # 4. Loop attempt 1: classify_state (check after selection - now ready)
        # 5. Final classify_state (after loop)
        mock_run.side_effect = [
            contract_chooser_state,  # Initial check
            contract_chooser_state,  # Loop check (attempt 1)
            {
                "parsed": {"success": True, "selected": "Professional Contract"},
                "error": None,
            },  # Select
            ready_state,  # Check after selection - now ready
            ready_state,  # Final check
        ]

        helper = RecoveryHelper("9230", max_attempts=2)
        result = helper.attempt_recovery()

        assert result["success"] is True
        assert result["final_state"] == "ready"


class TestJavaScriptProbe:
    """Tests for the JavaScript probe code."""

    def test_classify_js_includes_404_detection(self):
        """JS should include 404 detection."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "404" in js or "not found" in js.lower()
        assert "is404" in js

    def test_classify_js_includes_login_detection(self):
        """JS should include login page detection."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "login" in js.lower() or "sign in" in js.lower()
        assert "isLoginPage" in js

    def test_classify_js_includes_captcha_detection(self):
        """JS should include CAPTCHA detection."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "captcha" in js.lower() or "security check" in js.lower()
        assert "isBlocked" in js

    def test_classify_js_includes_loading_detection(self):
        """JS should include loading detection."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "loading search results" in js.lower()
        assert "isLoading" in js

    def test_classify_js_avoids_generic_loading_false_positive(self):
        """JS should not rely on a generic bodyText.includes('loading') check."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "bodyText.includes('loading')" not in js
        assert "hasExplicitLoadingText" in js
        assert '[class*="loading"]' not in js
        assert '[class*="spinner"]' not in js
        assert "isVisible" in js

    def test_classify_js_includes_recruiter_content(self):
        """JS should include recruiter content detection."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "hasRecruiterContent" in js
        assert "hasProjectsListContent" in js
        assert "/talent/" in js or "recruiter" in js.lower()

    def test_classify_js_returns_object(self):
        """JS should return a structured object."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "url:" in js
        assert "title:" in js
        assert "bodyPreview:" in js

    def test_classify_js_avoids_escaped_apostrophe_literals(self):
        """JS should avoid fragile escaped apostrophes in string literals."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "doesn't exist" in js
        assert "doesn\\'t exist" not in js

    def test_classify_js_includes_overview_content_detection(self):
        """JS should include overview page content detection."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "hasOverviewContent" in js
        assert "data-test-project-name-name" in js or "data-test-project-overview" in js

    def test_classify_js_includes_contract_chooser_detection(self):
        """JS should include contract chooser detection."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "isContractChooser" in js
        assert "contract-chooser" in js
        assert (
            "choose a contract" in js.lower()
            or "you have multiple contracts" in js.lower()
        )

    def test_classify_js_includes_corporate_contract_detection(self):
        """JS should detect corporate contract option."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "hasCorporateContract" in js
        assert "corporate" in js.lower()

    def test_classify_js_includes_contract_card_count(self):
        """JS should count contract cards."""
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "contractCardCount" in js
        assert "data-test-contract-card" in js or "contract-card" in js

    def test_classify_js_includes_live_overview_selectors(self):
        """JS should include live DOM selectors observed on real overview pages.

        Regression test for live project 1687654572 overview page selectors:
        - h1[data-test-project-name-name]
        - [data-test-project-overview-layout]
        - [data-test-overview-header]
        - [data-test-project-overview-modules]
        - [data-test-project-overview-sidebar]
        - [data-test-overview-about-project-module]
        - [data-test-title-bar-project-title]
        - [data-test-project-meta-dropdown-trigger]
        - button[data-test-collapsible-menu-link="overview"]
        """
        js = rpu.CLASSIFY_PAGE_STATE_JS
        assert "hasOverviewContent" in js
        # Live selectors from observed DOM
        assert "data-test-project-name-name" in js
        assert "data-test-project-overview-layout" in js
        assert "data-test-overview-header" in js
        assert "data-test-project-overview-modules" in js
        assert "data-test-project-overview-sidebar" in js
        assert "data-test-overview-about-project-module" in js
        assert "data-test-title-bar-project-title" in js
        assert "data-test-project-meta-dropdown-trigger" in js
        assert 'data-test-collapsible-menu-link="overview"' in js


class TestLoadingWrapperRegression:
    """REGRESSION TESTS: Loading wrapper false positives on loaded pages.

    Issue: LinkedIn keeps .loading-overlay__wrapper and .screen-loader__content
    classes in the DOM even on fully loaded pages, causing false LOADING detection.

    Fix: Overview content detection takes precedence over loading indicators.
    """

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_overview_page_with_loading_wrappers_is_ready(self, mock_run, mock_dialog):
        """REGRESSION: Loaded overview page with wrapper classes => READY.

        Simulates the live validation failure where:
        - URL is /talent/hire/123/overview
        - hasLoadingIndicator=true (wrapper classes present)
        - hasOverviewContent=true (actual content visible)
        - Should return READY, not LOADING
        """
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/overview",
                "title": "Project Overview - LinkedIn Recruiter",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": True,  # Wrapper classes present
                "hasLoadingIndicator": True,  # .loading-overlay__wrapper visible
                "hasExplicitLoadingText": False,
                "hasRecruiterContent": True,
                "hasProjectsListContent": False,
                "hasOverviewContent": True,  # Project header visible
                "hasSearchResultsContent": False,
                "readyState": "complete",
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "ready", (
            f"Expected READY for loaded overview page with wrappers, "
            f"got {result['state']}. Details: {result['details']}"
        )

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_actual_loading_search_page_is_loading(self, mock_run, mock_dialog):
        """REGRESSION: Actual loading search page without content => LOADING.

        Ensures we don't break real loading detection:
        - URL is /discover/recruiterSearch
        - isLoading=true
        - hasSearchResultsContent=false (no results yet)
        - hasOverviewContent=false (not an overview page)
        - Should return LOADING
        """
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
                "title": "LinkedIn Recruiter",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": True,  # Actually loading
                "hasLoadingIndicator": True,
                "hasExplicitLoadingText": True,  # "Loading search results"
                "hasRecruiterContent": False,  # No content yet
                "hasProjectsListContent": False,
                "hasOverviewContent": False,  # Not an overview page
                "hasSearchResultsContent": False,  # No results loaded
                "candidateCardCount": 0,
                "profileLinkCount": 0,
                "readyState": "interactive",
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "loading", (
            f"Expected LOADING for actual loading search page, "
            f"got {result['state']}. Details: {result['details']}"
        )

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_overview_page_without_content_is_loading(self, mock_run, mock_dialog):
        """Overview page URL without actual content => LOADING.

        Safety check: if we're on /overview but no content detected yet,
        we should still report LOADING until content appears.
        """
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/overview",
                "title": "LinkedIn Recruiter",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": True,
                "hasLoadingIndicator": True,
                "hasExplicitLoadingText": False,
                "hasRecruiterContent": False,  # No recruiter content yet
                "hasProjectsListContent": False,
                "hasOverviewContent": False,  # No overview content yet
                "hasSearchResultsContent": False,
                "readyState": "interactive",
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "loading", (
            f"Expected LOADING for overview page without content, got {result['state']}"
        )

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_live_overview_page_with_live_selectors_is_ready(
        self, mock_run, mock_dialog
    ):
        """REGRESSION: Live overview page with observed selectors => READY.

        Simulates the live validation failure on project 1687654572 where:
        - URL is /talent/hire/1687654572/overview
        - hasLoadingIndicator=true (wrapper classes present in DOM)
        - hasOverviewContent=true (live selectors like data-test-project-name-name visible)
        - Should return READY, not LOADING
        """
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/1687654572/overview",
                "title": "Project Overview - LinkedIn Recruiter",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": True,  # Wrapper classes present
                "hasLoadingIndicator": True,  # .loading-overlay__wrapper visible
                "hasExplicitLoadingText": False,
                "hasRecruiterContent": True,
                "hasProjectsListContent": False,
                "hasOverviewContent": True,  # Live selectors detected
                "hasSearchResultsContent": False,
                "readyState": "complete",
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        result = probe.classify_state()

        assert result["state"] == "ready", (
            f"Expected READY for live overview page with observed selectors, "
            f"got {result['state']}. Details: {result['details']}"
        )


class TestPageIdentityAssertions:
    """Tests for page identity assertion functions."""

    def test_normalize_url_for_comparison(self):
        """Should normalize URLs by removing query params and fragments."""
        from recruiter_page_utils import normalize_url_for_comparison

        assert (
            normalize_url_for_comparison(
                "https://linkedin.com/talent/hire/123/discover/recruiterSearch?projectId=123"
            )
            == "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )
        assert (
            normalize_url_for_comparison(
                "https://linkedin.com/talent/hire/123/discover/recruiterSearch#tab"
            )
            == "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )
        assert (
            normalize_url_for_comparison(
                "https://linkedin.com/talent/projects?filter=active"
            )
            == "https://linkedin.com/talent/projects"
        )

    def test_urls_match_allowing_params(self):
        """Should match URLs ignoring query parameters."""
        from recruiter_page_utils import urls_match_allowing_params

        assert urls_match_allowing_params(
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch?projectId=123",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )
        assert urls_match_allowing_params(
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch?a=1",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch?b=2",
        )
        assert not urls_match_allowing_params(
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "https://linkedin.com/talent/hire/456/discover/recruiterSearch",
        )

    @patch("recruiter_page_utils.run_browser_command")
    def test_validate_target_url_match_success(self, mock_run):
        """Should match when current URL has all target params plus extras."""
        from recruiter_page_utils import _validate_target_url_match

        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/search/results/people/?keywords=python&start=25&trackingId=abc"
            },
            "error": None,
        }

        result = _validate_target_url_match(
            "9230",
            target_url="https://linkedin.com/search/results/people/?keywords=python&start=25",
        )

        assert result["matches"] is True
        assert result["error"] is None

    @patch("recruiter_page_utils.run_browser_command")
    def test_validate_target_url_match_missing_param(self, mock_run):
        """Should fail when current URL is missing a target query param."""
        from recruiter_page_utils import _validate_target_url_match

        # Current URL is page 1 (no start param)
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/search/results/people/?keywords=python"
            },
            "error": None,
        }

        result = _validate_target_url_match(
            "9230",
            target_url="https://linkedin.com/search/results/people/?keywords=python&start=25",
        )

        assert result["matches"] is False
        assert "start=25" in result["error"]

    @patch("recruiter_page_utils.run_browser_command")
    def test_validate_target_url_match_wrong_path(self, mock_run):
        """Should fail when paths don't match."""
        from recruiter_page_utils import _validate_target_url_match

        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/projects"},
            "error": None,
        }

        result = _validate_target_url_match(
            "9230",
            target_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        assert result["matches"] is False
        assert "path mismatch" in result["error"]

    @patch("recruiter_page_utils.run_browser_command")
    def test_validate_target_url_match_no_params(self, mock_run):
        """Should match when target has no query params."""
        from recruiter_page_utils import _validate_target_url_match

        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/projects?filter=active"},
            "error": None,
        }

        result = _validate_target_url_match(
            "9230",
            target_url="https://linkedin.com/talent/projects",
        )

        assert result["matches"] is True
        assert result["error"] is None

    @patch("recruiter_page_utils.run_browser_command")
    def test_validate_target_url_match_ignores_volatile_search_params(self, mock_run):
        """REGRESSION: Should ignore volatile Recruiter search params like searchRequestId.

        Issue: run_create_search.py returned wrong_page because URLs differed only in
        volatile params like searchRequestId, searchContextId, searchHistoryId.
        Both URLs were the same project and same /discover/recruiterSearch page.

        Fix: _validate_target_url_match now filters out volatile params before comparison.
        """
        from recruiter_page_utils import _validate_target_url_match

        # Current URL has volatile params that differ from target
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch?searchRequestId=abc123&searchContextId=xyz789"
            },
            "error": None,
        }

        # Target URL doesn't have the volatile params (they're generated per-session)
        result = _validate_target_url_match(
            "9230",
            target_url="https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch",
        )

        assert result["matches"] is True, (
            f"Expected match for same page with different volatile params, "
            f"got error: {result.get('error')}"
        )
        assert result["error"] is None

    @patch("recruiter_page_utils.run_browser_command")
    def test_validate_target_url_match_ignores_tracking_id(self, mock_run):
        """Should ignore trackingId parameter when comparing URLs."""
        from recruiter_page_utils import _validate_target_url_match

        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25&trackingId=abc123&trk=xyz"
            },
            "error": None,
        }

        result = _validate_target_url_match(
            "9230",
            target_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
        )

        assert result["matches"] is True
        assert result["error"] is None

    @patch("recruiter_page_utils.run_browser_command")
    def test_validate_target_url_match_still_requires_non_volatile_params(
        self, mock_run
    ):
        """Should still fail when non-volatile params like pagination are missing."""
        from recruiter_page_utils import _validate_target_url_match

        # Current URL is page 1 (no start param)
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchRequestId=abc"
            },
            "error": None,
        }

        # Target URL is page 2 (has start=25)
        result = _validate_target_url_match(
            "9230",
            target_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
        )

        assert result["matches"] is False
        assert "start=25" in result["error"]

    @patch("recruiter_page_utils.run_browser_command")
    def test_assert_page_identity_matches(self, mock_run):
        """Should return matches=True when URL contains expected patterns."""
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
            },
            "error": None,
        }

        result = rpu.assert_page_identity(
            "9230",
            expected_url_patterns=["/talent/hire/", "/discover/recruiterSearch"],
        )

        assert result["matches"] is True
        assert (
            result["current_url"]
            == "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )
        assert result["error"] is None

    @patch("recruiter_page_utils.run_browser_command")
    def test_assert_page_identity_mismatch(self, mock_run):
        """Should return matches=False when URL doesn't match expected patterns."""
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/projects"},
            "error": None,
        }

        result = rpu.assert_page_identity(
            "9230",
            expected_url_patterns=["/discover/recruiterSearch"],
            context="test_context",
        )

        assert result["matches"] is False
        assert "test_context" in result["error"]
        assert "/discover/recruiterSearch" in result["error"]

    @patch("recruiter_page_utils.run_browser_command")
    def test_assert_page_identity_command_error(self, mock_run):
        """Should handle browser command errors gracefully."""
        mock_run.return_value = {"error": "Connection refused", "parsed": None}

        result = rpu.assert_page_identity(
            "9230",
            expected_url_patterns=["/talent/"],
        )

        assert result["matches"] is False
        assert "Connection refused" in result["error"]

    @patch("recruiter_page_utils.run_browser_command")
    def test_assert_page_identity_path_patterns(self, mock_run):
        """Should validate path patterns separately from URL patterns."""
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/hire/123/overview"},
            "error": None,
        }

        result = rpu.assert_page_identity(
            "9230",
            expected_path_patterns=["/talent/hire/"],
        )

        assert result["matches"] is True

    @patch("recruiter_page_utils.run_browser_command")
    def test_ensure_page_ready_with_identity_check(self, mock_run, mock_dialog=None):
        """Should validate page identity when require_page_identity=True."""
        # This test will be run with proper mocks in the method below
        pass


class TestEnsurePageReadyWithIdentity:
    """Tests for ensure_page_ready with identity validation."""

    @patch("recruiter_page_utils.assert_page_identity")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    def test_identity_validation_on_ready(
        self, mock_dialog, mock_run, mock_probe, mock_identity
    ):
        """Should validate identity when page is already ready."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
            },
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # Mock identity check to succeed
        mock_identity.return_value = {
            "matches": True,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "expected_patterns": ["/discover/recruiterSearch"],
            "error": None,
        }

        result = rpu.ensure_page_ready(
            "9230",
            target_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            require_page_identity=True,
        )

        assert result["ready"] is True
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is True

    @patch("recruiter_page_utils.assert_page_identity")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    def test_identity_validation_failure(
        self, mock_dialog, mock_run, mock_probe, mock_identity
    ):
        """Should return ready=False when identity validation fails."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/projects"},
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # Mock identity check to fail
        mock_identity.return_value = {
            "matches": False,
            "current_url": "https://linkedin.com/talent/projects",
            "expected_patterns": ["/discover/recruiterSearch"],
            "error": "Page identity mismatch: URL does not contain expected patterns",
        }

        result = rpu.ensure_page_ready(
            "9230",
            target_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            require_page_identity=True,
        )

        assert result["ready"] is False
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is False

    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    def test_identity_validation_ignores_extra_query_params(
        self, mock_dialog, mock_run, mock_probe
    ):
        """Should pass identity check when LinkedIn adds extra query params.

        This is the regression test for the page-2 pagination bug where
        LinkedIn injects extra query params (like trackingId) causing
        the identity check to fail when using full URL substring matching.
        """
        mock_dialog.return_value = {"has_dialog": False}
        # Simulate LinkedIn adding extra params to the URL
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25&trackingId=abc123"
            },
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # Target URL is page 2 without the extra params LinkedIn adds
        target_url = (
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25"
        )

        result = rpu.ensure_page_ready(
            "9230",
            target_url=target_url,
            require_page_identity=True,
        )

        # Should be ready because path matches, ignoring extra query params
        assert result["ready"] is True
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is True
        assert result["identity_check"]["current_url"] == (
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25&trackingId=abc123"
        )

    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    def test_identity_validation_fails_on_wrong_path(
        self, mock_dialog, mock_run, mock_probe
    ):
        """Should fail identity check when on completely wrong page."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/projects"},
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # Target URL is a specific search page
        target_url = (
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25"
        )

        result = rpu.ensure_page_ready(
            "9230",
            target_url=target_url,
            require_page_identity=True,
        )

        # Should NOT be ready because path doesn't match
        assert result["ready"] is False
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is False

    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    def test_explicit_url_patterns_take_precedence(
        self, mock_dialog, mock_run, mock_probe
    ):
        """Should use expected_url_patterns when explicitly provided."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
            },
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # When explicit patterns are provided, they should be used
        result = rpu.ensure_page_ready(
            "9230",
            target_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            expected_url_patterns=["/discover/recruiterSearch"],
            require_page_identity=True,
        )

        assert result["ready"] is True
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is True

    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    def test_expected_url_patterns_mismatch_on_ready_path(
        self, mock_dialog, mock_run, mock_probe
    ):
        """REGRESSION TEST: expected_url_patterns mismatch must fail on is_ready() fast path.

        Issue: When probe.is_ready() returned True and expected_url_patterns was provided,
        the code checked identity but ignored a mismatch, returning ready=True regardless.
        """
        mock_dialog.return_value = {"has_dialog": False}
        # Browser is on projects page
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/projects"},
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # But we expect to be on recruiterSearch page
        result = rpu.ensure_page_ready(
            "9230",
            target_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            expected_url_patterns=["/discover/recruiterSearch"],
            require_page_identity=True,
        )

        # Should NOT be ready because we're on the wrong page
        assert result["ready"] is False
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is False
        assert "/discover/recruiterSearch" in result["identity_check"]["error"]

    @patch("recruiter_page_utils.RecoveryHelper")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.time.sleep")
    def test_pagination_distinguishes_page1_from_page2(
        self, mock_sleep, mock_dialog, mock_run, mock_probe, mock_recovery
    ):
        """REGRESSION TEST: Page 1 and Page 2 must be distinguished when using target_url.

        Issue: When target_url was provided without expected_url_patterns, the code used
        path-only matching. For pagination, page 1 and page 2 have the same path but
        different query params (?start=25), so the check incorrectly passed.

        Fix: When ready but on wrong page with target_url provided, navigate to target
        and re-validate. If navigation doesn't change the URL (mocked), eventually fail.
        """
        mock_dialog.return_value = {"has_dialog": False}
        mock_sleep.return_value = None  # Speed up test

        # Browser always reports page 1 (simulates navigation not working or mocked)
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/search/results/people/?keywords=python"
            },
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # Mock recovery helper to track navigation attempts
        mock_recovery_instance = MagicMock()
        mock_recovery_instance._navigate_to_url = MagicMock()
        mock_recovery.return_value = mock_recovery_instance

        # We want to navigate to page 2 (has start=25)
        result = rpu.ensure_page_ready(
            "9230",
            target_url="https://linkedin.com/search/results/people/?keywords=python&start=25",
            require_page_identity=True,
        )

        # Should NOT be ready because we're still on page 1 after navigation attempts
        assert result["ready"] is False
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is False
        assert "start=25" in result["identity_check"]["error"]
        # Navigation should have been attempted (up to recursion limit)
        assert mock_recovery_instance._navigate_to_url.call_count >= 1

    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    def test_pagination_page2_matches_with_extra_params(
        self, mock_dialog, mock_run, mock_probe
    ):
        """Page 2 with extra LinkedIn params should match target_url.

        When we're on page 2 and LinkedIn adds tracking params, it should still match.
        """
        mock_dialog.return_value = {"has_dialog": False}
        # Browser is on page 2 with extra tracking params
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/search/results/people/?keywords=python&start=25&trackingId=abc123"
            },
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # Target URL is page 2 without the extra params
        result = rpu.ensure_page_ready(
            "9230",
            target_url="https://linkedin.com/search/results/people/?keywords=python&start=25",
            require_page_identity=True,
        )

        # Should be ready because we're on page 2 (extra params allowed)
        assert result["ready"] is True
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is True

    @patch("recruiter_page_utils.RecoveryHelper")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.time.sleep")
    def test_ready_but_wrong_page_navigates_and_retries(
        self, mock_sleep, mock_dialog, mock_run, mock_probe, mock_recovery
    ):
        """REGRESSION TEST: Ready but wrong page should navigate to target and re-validate.

        Issue: When probe.is_ready() returned True but identity check failed (wrong page),
        the code returned ready=False without attempting navigation. This caused pagination
        to fail when going from page 1 to page 2 - the browser stayed on page 1.

        Fix: When ready but on wrong page with target_url provided, navigate to target
        and re-validate instead of failing immediately.
        """
        mock_dialog.return_value = {"has_dialog": False}
        mock_sleep.return_value = None  # Speed up test

        # First call: on page 1, ready but wrong page
        # Second call: after navigation, on page 2, ready and correct
        mock_run.side_effect = [
            {"parsed": {"url": "https://linkedin.com/search?start=0"}, "error": None},
            {"parsed": {"url": "https://linkedin.com/search?start=25"}, "error": None},
        ]

        # Mock probe: first ready, then ready again after navigation
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.side_effect = [True, True]
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # Mock recovery helper for navigation
        mock_recovery_instance = MagicMock()
        mock_recovery_instance._navigate_to_url = MagicMock()
        mock_recovery.return_value = mock_recovery_instance

        # Target is page 2, but we're on page 1
        result = rpu.ensure_page_ready(
            "9230",
            target_url="https://linkedin.com/search?start=25",
            require_page_identity=True,
        )

        # Should eventually succeed after navigation
        assert result["ready"] is True
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is True
        # Navigation should have been called
        mock_recovery_instance._navigate_to_url.assert_called_once_with(
            "https://linkedin.com/search?start=25"
        )

    @patch("recruiter_page_utils.RecoveryHelper")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.time.sleep")
    def test_ready_but_wrong_page_no_target_url_fails(
        self, mock_sleep, mock_dialog, mock_run, mock_probe, mock_recovery
    ):
        """Ready but wrong page without target_url should fail (no navigation possible)."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_sleep.return_value = None
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/projects"},
            "error": None,
        }

        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        # No target_url provided, so can't navigate
        result = rpu.ensure_page_ready(
            "9230",
            expected_url_patterns=["/discover/recruiterSearch"],
            require_page_identity=True,
            target_url=None,  # Explicitly no target URL
        )

        # Should fail because we can't navigate to fix it
        assert result["ready"] is False
        assert result["identity_check"] is not None
        assert result["identity_check"]["matches"] is False


class TestIntegrationPatterns:
    """Integration-style tests for common scenarios."""

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.subprocess.run")
    @patch("recruiter_page_utils.time.sleep")
    def test_full_recovery_scenario_404_to_ready(
        self, mock_sleep, mock_subprocess, mock_run, mock_dialog
    ):
        """Should recover from 404 to ready state."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.side_effect = [
            # Initial classification: 404
            {
                "parsed": {
                    "url": "https://linkedin.com/404",
                    "title": "Page not found",
                    "is404": True,
                    "isLoginPage": False,
                    "isWrongProduct": False,
                    "isBlocked": False,
                    "isLoading": False,
                    "hasRecruiterContent": False,
                },
                "error": None,
            },
            # After navigation: ready
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/projects",
                    "title": "Projects",
                    "is404": False,
                    "isLoginPage": False,
                    "isWrongProduct": False,
                    "isBlocked": False,
                    "isLoading": False,
                    "hasRecruiterContent": True,
                },
                "error": None,
            },
        ]
        mock_subprocess.return_value = Mock(returncode=0)

        helper = RecoveryHelper("9230")
        result = helper.attempt_recovery(
            target_url="https://linkedin.com/talent/projects",
            context="test_recovery",
        )

        assert result["success"] is True
        assert result["final_state"] == "ready"
        assert result["attempts_made"] == 1

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_session_drift_detection(self, mock_run, mock_dialog):
        """Should detect session drift to login page."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/login?from=talent",
                "title": "Login",
                "is404": False,
                "isLoginPage": True,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        probe = PageStateProbe("9230")
        state = probe.classify_state()

        assert state["state"] == "logged_out_or_wrong_product"
        assert state["details"]["isLoginPage"] is True


class TestBackwardsCompatibility:
    """Tests for backwards compatibility with cdp_port parameter."""

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_ensure_page_ready_accepts_cdp_port_keyword(self, mock_run, mock_dialog):
        """ensure_page_ready should accept cdp_port= as alias for browser_mode=."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }

        # Using cdp_port= as keyword argument (old API)
        result = rpu.ensure_page_ready(cdp_port="9230")

        assert result["ready"] is True
        assert result["state"] == "ready"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_ensure_page_ready_browser_mode_takes_precedence(
        self, mock_run, mock_dialog
    ):
        """browser_mode= should take precedence over cdp_port= when both provided."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": True,
            },
            "error": None,
        }

        # Both provided - browser_mode should be used
        result = rpu.ensure_page_ready(browser_mode="9230", cdp_port="9999")

        assert result["ready"] is True

    def test_ensure_page_ready_requires_one_argument(self):
        """ensure_page_ready should raise TypeError if neither argument provided."""
        with pytest.raises(TypeError, match="requires either browser_mode or cdp_port"):
            rpu.ensure_page_ready()


class TestActionRequiredInRecovery:
    """Tests for action_required payloads in recovery results."""

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_blocked_state_returns_action_required(self, mock_run, mock_dialog):
        """Blocked/CAPTCHA state should return structured action_required."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/checkpoint/challenge",
                "title": "Security Check",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": True,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        helper = RecoveryHelper("9230")
        result = helper.attempt_recovery()

        assert result["success"] is False
        assert result["final_state"] == "blocked_or_captcha"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "blocked_or_captcha"
        assert result["failure_code"] == "blocked_or_captcha"
        assert "steps" in result["action_required"]
        assert len(result["action_required"]["steps"]) >= 3

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_logged_out_state_returns_action_required(self, mock_run, mock_dialog):
        """Logged out state should return structured action_required."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/login",
                "title": "Login",
                "is404": False,
                "isLoginPage": True,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        helper = RecoveryHelper("9230")
        result = helper.attempt_recovery()

        assert result["success"] is False
        assert result["final_state"] == "logged_out_or_wrong_product"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "auth_required"
        assert result["failure_code"] == "auth_required"
        assert "steps" in result["action_required"]

    @patch("recruiter_page_utils.check_dialog_status")
    def test_dialog_blocked_returns_action_required(self, mock_dialog):
        """Dialog blocked state should return structured action_required."""
        mock_dialog.return_value = {
            "has_dialog": True,
            "dialog_type": "confirm",
            "message": "Are you sure you want to leave?",
        }

        helper = RecoveryHelper("9230")
        result = helper.attempt_recovery()

        assert result["success"] is False
        assert result["final_state"] == "dialog_blocked"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "dialog_blocked"
        assert result["failure_code"] == "dialog_blocked"
        assert result["action_required"]["context"]["dialog_type"] == "confirm"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.subprocess.run")
    @patch("recruiter_page_utils.time.sleep")
    def test_recovery_failure_returns_action_required(
        self, mock_sleep, mock_subprocess, mock_run, mock_dialog
    ):
        """Failed recovery should return structured action_required."""
        mock_dialog.return_value = {"has_dialog": False}
        # Always return bad page
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/404",
                "is404": True,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }
        mock_subprocess.return_value = Mock(returncode=0)

        helper = RecoveryHelper("9230", max_attempts=2)
        result = helper.attempt_recovery(target_url="https://linkedin.com/talent/home")

        assert result["success"] is False
        assert result["action_required"] is not None
        assert result["failure_code"] is not None


class TestActionRequiredInEnsurePageReady:
    """Tests for action_required in ensure_page_ready results."""

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_blocked_in_ensure_page_ready_returns_action_required(
        self, mock_run, mock_dialog
    ):
        """ensure_page_ready should return action_required for blocked state."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/checkpoint",
                "is404": False,
                "isLoginPage": False,
                "isWrongProduct": False,
                "isBlocked": True,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        result = rpu.ensure_page_ready("9230")

        assert result["ready"] is False
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "blocked_or_captcha"
        assert result["failure_code"] == "blocked_or_captcha"

    @patch("recruiter_page_utils.check_dialog_status")
    @patch("recruiter_page_utils.run_browser_command")
    def test_logged_out_in_ensure_page_ready_returns_action_required(
        self, mock_run, mock_dialog
    ):
        """ensure_page_ready should return action_required for logged out state."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/login",
                "is404": False,
                "isLoginPage": True,
                "isWrongProduct": False,
                "isBlocked": False,
                "isLoading": False,
                "hasRecruiterContent": False,
            },
            "error": None,
        }

        result = rpu.ensure_page_ready("9230")

        assert result["ready"] is False
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "auth_required"
        assert result["failure_code"] == "auth_required"

    @patch("recruiter_page_utils.PageStateProbe")
    @patch("recruiter_page_utils.run_browser_command")
    @patch("recruiter_page_utils.check_dialog_status")
    def test_wrong_page_returns_action_required(
        self, mock_dialog, mock_run, mock_probe
    ):
        """ensure_page_ready should return action_required for wrong page."""
        mock_dialog.return_value = {"has_dialog": False}
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/projects"},
            "error": None,
        }

        # Mock probe to return ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.is_ready.return_value = True
        mock_probe_instance.is_blocked.return_value = False
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
        }
        mock_probe.return_value = mock_probe_instance

        result = rpu.ensure_page_ready(
            "9230",
            target_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            require_page_identity=True,
        )

        assert result["ready"] is False
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "wrong_page"
        assert result["failure_code"] == "wrong_page"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
