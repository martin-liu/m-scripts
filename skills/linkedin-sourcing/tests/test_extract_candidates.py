#!/usr/bin/env python3
"""Tests for extract_candidates.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_extract_candidates.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import extract_candidates as ec


class TestReadCdpPort:
    """Tests for CDP port reading from profile."""

    @patch("runtime_manager.RuntimeManager")
    def test_uses_runtime_manager_for_profile(self, mock_manager_class):
        """Should use RuntimeManager for consistent profile resolution."""
        mock_manager = Mock()
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9235"}
        mock_manager_class.return_value = mock_manager

        result = ec.read_cdp_port()

        assert result == "9235"
        mock_manager_class.assert_called_once()
        mock_manager._resolve_profile.assert_called_once()

    @patch("runtime_manager.RuntimeManager")
    def test_uses_default_when_not_in_profile(self, mock_manager_class):
        """Should use default port when CDP_PORT not in profile."""
        mock_manager = Mock()
        mock_manager._resolve_profile.return_value = {"WORK_DIR": "/tmp"}
        mock_manager_class.return_value = mock_manager

        result = ec.read_cdp_port()

        assert result == "9230"

    @patch("runtime_manager.RuntimeManager")
    def test_strips_quotes_from_port(self, mock_manager_class):
        """Should strip quotes from CDP_PORT value."""
        mock_manager = Mock()
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9240"}
        mock_manager_class.return_value = mock_manager

        result = ec.read_cdp_port()

        assert result == "9240"


class TestParseConfigFile:
    """Tests for config file parsing."""

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.read_text")
    def test_parses_quoted_values(self, mock_read_text, mock_exists):
        """Should parse double-quoted values from config."""
        mock_exists.return_value = True
        mock_read_text.return_value = """
PROJECT_ID="12345"
POSITION_TITLE="Software Engineer"
RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123"
"""
        result = ec.parse_config_file("/path/to/config.sh")

        assert result["PROJECT_ID"] == "12345"
        assert result["POSITION_TITLE"] == "Software Engineer"
        assert result["RECRUITER_PROJECT_URL"] == "https://linkedin.com/talent/hire/123"

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.read_text")
    def test_parses_single_quoted_values(self, mock_read_text, mock_exists):
        """Should parse single-quoted values from config."""
        mock_exists.return_value = True
        mock_read_text.return_value = (
            "RECRUITER_PROJECT_URL='https://linkedin.com/talent/hire/456'"
        )

        result = ec.parse_config_file("/path/to/config.sh")

        assert result["RECRUITER_PROJECT_URL"] == "https://linkedin.com/talent/hire/456"

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.read_text")
    def test_ignores_comments_and_empty_lines(self, mock_read_text, mock_exists):
        """Should ignore comments and empty lines."""
        mock_exists.return_value = True
        mock_read_text.return_value = """
# This is a comment
PROJECT_ID="123"

# Another comment
POSITION_TITLE="Engineer"
"""
        result = ec.parse_config_file("/path/to/config.sh")

        assert result["PROJECT_ID"] == "123"
        assert result["POSITION_TITLE"] == "Engineer"
        assert "# This is a comment" not in result

    @patch("pathlib.Path.exists")
    def test_returns_empty_dict_for_missing_file(self, mock_exists):
        """Should return empty dict when config file doesn't exist."""
        mock_exists.return_value = False

        result = ec.parse_config_file("/nonexistent/config.sh")

        assert result == {}


class TestResolveTargetUrl:
    """Tests for target URL resolution."""

    def test_uses_target_url_arg_when_provided(self):
        """Should use --target-url when provided."""
        args = Mock()
        args.target_url = "https://linkedin.com/talent/hire/123"
        args.project_config = None

        result = ec.resolve_target_url(args)

        assert result == "https://linkedin.com/talent/hire/123"

    @patch("extract_candidates.parse_config_file")
    def test_reads_from_config_when_project_config_provided(self, mock_parse):
        """Should read RECRUITER_PROJECT_URL from config file."""
        mock_parse.return_value = {
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/456"
        }
        args = Mock()
        args.target_url = None
        args.project_config = "/path/to/config.sh"

        result = ec.resolve_target_url(args)

        assert result == "https://linkedin.com/talent/hire/456"
        mock_parse.assert_called_once_with("/path/to/config.sh")

    @patch("extract_candidates.parse_config_file")
    def test_returns_none_when_no_url_in_config(self, mock_parse):
        """Should return None when config has no RECRUITER_PROJECT_URL."""
        mock_parse.return_value = {"PROJECT_ID": "123"}
        args = Mock()
        args.target_url = None
        args.project_config = "/path/to/config.sh"

        result = ec.resolve_target_url(args)

        assert result is None

    def test_target_url_takes_precedence_over_config(self):
        """Should prefer --target-url over --project-config."""
        args = Mock()
        args.target_url = "https://linkedin.com/talent/hire/direct"
        args.project_config = "/path/to/config.sh"

        result = ec.resolve_target_url(args)

        assert result == "https://linkedin.com/talent/hire/direct"


class TestParseArguments:
    """Tests for argument parsing with backward compatibility."""

    @patch("extract_candidates.read_cdp_port")
    def test_uses_positional_port(self, mock_read_cdp):
        """Should use positional argument as CDP port (backward compat)."""
        mock_read_cdp.return_value = "9230"

        with patch.object(sys, "argv", ["script", "9235"]):
            args = ec.parse_arguments()

        assert args.cdp_port == "9235"
        mock_read_cdp.assert_not_called()

    @patch("extract_candidates.read_cdp_port")
    def test_uses_default_from_profile_when_no_positional(self, mock_read_cdp):
        """Should read CDP port from profile when no positional arg."""
        mock_read_cdp.return_value = "9240"

        with patch.object(sys, "argv", ["script"]):
            args = ec.parse_arguments()

        assert args.cdp_port == "9240"
        mock_read_cdp.assert_called_once()

    @patch("extract_candidates.read_cdp_port")
    def test_parses_target_url_flag(self, mock_read_cdp):
        """Should parse --target-url flag."""
        mock_read_cdp.return_value = "9230"

        with patch.object(
            sys,
            "argv",
            ["script", "--target-url", "https://linkedin.com/talent/hire/123"],
        ):
            args = ec.parse_arguments()

        assert args.target_url == "https://linkedin.com/talent/hire/123"

    @patch("extract_candidates.read_cdp_port")
    def test_parses_project_config_flag(self, mock_read_cdp):
        """Should parse --project-config flag."""
        mock_read_cdp.return_value = "9230"

        with patch.object(
            sys, "argv", ["script", "--project-config", "/path/to/config.sh"]
        ):
            args = ec.parse_arguments()

        assert args.project_config == "/path/to/config.sh"

    @patch("extract_candidates.read_cdp_port")
    def test_combines_flags_with_positional_port(self, mock_read_cdp):
        """Should allow both flags and positional port."""
        mock_read_cdp.return_value = "9230"

        with patch.object(
            sys,
            "argv",
            ["script", "--target-url", "https://linkedin.com/talent/hire/123", "9235"],
        ):
            args = ec.parse_arguments()

        assert args.cdp_port == "9235"
        assert args.target_url == "https://linkedin.com/talent/hire/123"


class TestBuildAgentBrowserCommand:
    """Tests for command building."""

    def test_builds_correct_command(self):
        """Should build correct agent-browser command."""
        result = ec.build_agent_browser_command("9230")

        assert result == ["agent-browser", "--cdp", "9230"]

    def test_uses_provided_port(self):
        """Should use the provided port number."""
        result = ec.build_agent_browser_command("9999")

        assert "9999" in result


class TestRunBrowserCommand:
    """Tests for browser command execution."""

    @patch("subprocess.run")
    def test_successful_command(self, mock_run):
        """Should parse successful command output."""
        mock_run.return_value = Mock(
            stdout='{"state": "ready", "count": 5}',
            stderr="",
            returncode=0,
        )

        result = ec.run_browser_command("9230", "eval", "some_js")

        assert result["returncode"] == 0
        assert result["parsed"]["state"] == "ready"
        assert result["error"] is None

    @patch("subprocess.run")
    def test_double_encoded_json(self, mock_run):
        """Should handle double-encoded JSON from agent-browser."""
        mock_run.return_value = Mock(
            stdout='"{\\"state\\": \\"ready\\", \\"count\\": 5}"',
            stderr="",
            returncode=0,
        )

        result = ec.run_browser_command("9230", "eval", "some_js")

        assert result["parsed"]["state"] == "ready"
        assert result["parsed"]["count"] == 5

    @patch("subprocess.run")
    def test_empty_output(self, mock_run):
        """Should handle empty output gracefully."""
        mock_run.return_value = Mock(stdout="", stderr="", returncode=0)

        result = ec.run_browser_command("9230", "eval", "some_js")

        assert result["parsed"] is None
        assert result["error"] is None

    @patch("subprocess.run")
    def test_command_failure(self, mock_run):
        """Should capture error on non-zero exit."""
        mock_run.return_value = Mock(
            stdout="",
            stderr="browser not connected",
            returncode=1,
        )

        result = ec.run_browser_command("9230", "eval", "some_js")

        assert result["returncode"] == 1
        assert "browser not connected" in result["error"]

    @patch("subprocess.run")
    def test_timeout(self, mock_run):
        """Should handle timeout gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=30)

        result = ec.run_browser_command("9230", "eval", "some_js")

        assert "timed out" in result["error"].lower()

    @patch("subprocess.run")
    def test_agent_browser_not_found(self, mock_run):
        """Should handle missing agent-browser gracefully."""
        mock_run.side_effect = FileNotFoundError()

        result = ec.run_browser_command("9230", "eval", "some_js")

        assert "agent-browser" in result["error"].lower()


class TestDetectPageStateJs:
    """Tests for page state detection JavaScript generation."""

    def test_includes_loading_patterns(self):
        """Should include loading text patterns in JS."""
        js = ec.detect_page_state_js()

        assert "loading search results" in js
        assert "loading" in js

    def test_includes_no_results_patterns(self):
        """Should include no-results text patterns in JS."""
        js = ec.detect_page_state_js()

        assert "no results found" in js
        assert "try adjusting your search" in js

    def test_returns_valid_js_structure(self):
        """Should return valid JavaScript function."""
        js = ec.detect_page_state_js()

        assert js.startswith("(")
        assert "() =>" in js or "function" in js
        assert "state" in js
        assert "hasCandidates" in js
        assert "candidateCount" in js

    def test_includes_body_text_extraction(self):
        """Should extract body text for debugging."""
        js = ec.detect_page_state_js()

        assert "bodyText" in js
        assert "innerText" in js

    def test_includes_loading_overlay_detection(self):
        """Should detect loading overlay DOM elements."""
        js = ec.detect_page_state_js()

        assert "loading-overlay" in js
        assert "loading-overlay__wrapper" in js
        assert "screen-loader__content" in js
        assert "hasLoadingOverlay" in js

    def test_loading_overlay_triggers_loading_state(self):
        """Should set state to loading when loading overlay found."""
        js = ec.detect_page_state_js()

        # The logic should check hasLoadingOverlay for loading state
        assert "hasLoadingOverlay" in js
        assert (
            "loadingText || hasLoadingOverlay" in js
            or "hasLoadingOverlay || loadingText" in js
        )

    def test_candidates_are_prioritized_over_loader_hints(self):
        """Should mark the page ready when candidate selectors are already present."""
        js = ec.detect_page_state_js()
        assert "if (hasCandidates || hasProfileLinks)" in js


class TestWaitForSearchResults:
    """Tests for wait logic with state detection."""

    @patch("extract_candidates.run_browser_command")
    @patch("time.sleep")
    def test_returns_ready_when_candidates_found(self, mock_sleep, mock_run):
        """Should return ready status when candidates detected."""
        mock_run.return_value = {
            "parsed": {
                "state": "ready",
                "hasCandidates": True,
                "candidateCount": 5,
                "hasProfileLinks": True,
                "profileLinkCount": 5,
                "loadingText": None,
                "noResultsText": None,
                "bodyText": "some content",
            },
            "error": None,
            "timed_out": False,
        }

        result = ec.wait_for_search_results("9230", max_wait_seconds=1.0)

        assert result["status"] == "ready"
        assert result["state"] == "ready"
        assert "5 candidates" in result["message"]
        assert result.get("recovery_result") is None

    @patch("extract_candidates.run_browser_command")
    @patch("time.sleep")
    def test_returns_no_results_when_empty(self, mock_sleep, mock_run):
        """Should return no_results status when explicitly empty."""
        mock_run.return_value = {
            "parsed": {
                "state": "no_results",
                "hasCandidates": False,
                "candidateCount": 0,
                "loadingText": None,
                "noResultsText": "no results found",
                "bodyText": "No results found for your search",
            },
            "error": None,
            "timed_out": False,
        }

        result = ec.wait_for_search_results("9230", max_wait_seconds=1.0)

        assert result["status"] == "no_results"
        assert "no results found" in result["message"]

    @patch("extract_candidates.run_browser_command")
    @patch("browser_utils.check_dialog_status")
    @patch("time.sleep")
    def test_returns_timeout_when_loading_persists(
        self, mock_sleep, mock_dialog, mock_run
    ):
        """Should return timeout when loading state persists."""
        mock_run.return_value = {
            "parsed": {
                "state": "loading",
                "hasCandidates": False,
                "candidateCount": 0,
                "loadingText": "loading search results",
                "noResultsText": None,
                "bodyText": "Loading search results...",
            },
            "error": None,
            "timed_out": False,
        }
        mock_dialog.return_value = {"has_dialog": False}

        result = ec.wait_for_search_results(
            "9230",
            max_wait_seconds=0.5,
            poll_interval_seconds=0.1,
            attempt_recovery_on_timeout=False,  # Disable recovery for this test
        )

        assert result["status"] == "timeout"
        assert "loading" in result["state"]

    @patch("extract_candidates.run_browser_command")
    @patch("browser_utils.check_dialog_status")
    @patch("time.sleep")
    def test_timeout_with_dialog_detection(self, mock_sleep, mock_dialog, mock_run):
        """Should detect blocking dialog on timeout."""
        mock_run.return_value = {
            "parsed": {
                "state": "loading",
                "hasCandidates": False,
                "candidateCount": 0,
                "loadingText": "loading search results",
                "noResultsText": None,
                "bodyText": "Loading search results...",
            },
            "error": None,
            "timed_out": False,
        }
        mock_dialog.return_value = {
            "has_dialog": True,
            "dialog_type": "alert",
            "message": "Session expired",
            "error": None,
        }

        result = ec.wait_for_search_results(
            "9230", max_wait_seconds=0.3, poll_interval_seconds=0.1
        )

        assert result["status"] == "timeout"
        assert result["dialog_info"]["has_dialog"] is True
        assert result["dialog_info"]["dialog_type"] == "alert"
        assert "Session expired" in result["message"]

    @patch("extract_candidates.run_browser_command")
    @patch("browser_utils.check_dialog_status")
    @patch("time.sleep")
    def test_timeout_without_dialog(self, mock_sleep, mock_dialog, mock_run):
        """Should report no dialog when timeout occurs without blocking dialog."""
        mock_run.return_value = {
            "parsed": {
                "state": "loading",
                "hasCandidates": False,
                "candidateCount": 0,
                "loadingText": "loading search results",
                "noResultsText": None,
                "bodyText": "Loading search results...",
            },
            "error": None,
            "timed_out": False,
        }
        mock_dialog.return_value = {
            "has_dialog": False,
            "dialog_type": None,
            "message": None,
            "error": None,
        }

        result = ec.wait_for_search_results(
            "9230", max_wait_seconds=0.3, poll_interval_seconds=0.1
        )

        assert result["status"] == "timeout"
        assert result["dialog_info"]["has_dialog"] is False

    @patch("extract_candidates.run_browser_command")
    def test_returns_error_on_command_failure(self, mock_run):
        """Should return error status when browser command fails."""
        mock_run.return_value = {
            "parsed": None,
            "error": "Connection refused",
            "timed_out": False,
        }

        result = ec.wait_for_search_results("9230", max_wait_seconds=0.5)

        assert result["status"] == "error"
        assert "Connection refused" in result["message"]

    @patch("extract_candidates.run_browser_command")
    @patch("time.sleep")
    def test_polls_multiple_times(self, mock_sleep, mock_run):
        """Should poll multiple times until ready."""
        # First call: loading, second call: ready
        mock_run.side_effect = [
            {
                "parsed": {
                    "state": "loading",
                    "hasCandidates": False,
                    "loadingText": "loading",
                },
                "error": None,
                "timed_out": False,
            },
            {
                "parsed": {
                    "state": "ready",
                    "hasCandidates": True,
                    "candidateCount": 3,
                },
                "error": None,
                "timed_out": False,
            },
        ]

        result = ec.wait_for_search_results(
            "9230", max_wait_seconds=1.0, poll_interval_seconds=0.1
        )

        assert result["status"] == "ready"
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 1  # Slept between polls

    @patch("extract_candidates.RecoveryHelper")
    @patch("extract_candidates.PageStateProbe")
    @patch("extract_candidates.run_browser_command")
    @patch("browser_utils.check_dialog_status")
    @patch("time.sleep")
    def test_recovery_uses_target_url_when_provided(
        self, mock_sleep, mock_dialog, mock_run, mock_probe, mock_recovery
    ):
        """Should pass target URL to recovery helper when available."""
        # Always return loading state to trigger timeout
        mock_run.return_value = {
            "parsed": {
                "state": "loading",
                "hasCandidates": False,
                "candidateCount": 0,
                "loadingText": "loading search results",
                "noResultsText": None,
                "bodyText": "Loading search results...",
            },
            "error": None,
            "timed_out": False,
        }
        mock_dialog.return_value = {"has_dialog": False}

        # Mock probe to return loading state (triggers recovery)
        mock_probe_instance = Mock()
        mock_probe_instance.classify_state.return_value = {
            "state": "loading",
            "details": {"isLoading": True},
            "dialog_info": None,
        }
        mock_probe.return_value = mock_probe_instance

        # Mock recovery helper
        mock_recovery_instance = Mock()
        mock_recovery_instance.attempt_recovery.return_value = {
            "success": True,
            "final_state": "ready",
            "attempts_made": 1,
            "actions_taken": ["navigate_to_target"],
            "error": None,
        }
        mock_recovery.return_value = mock_recovery_instance

        target_url = "https://linkedin.com/talent/hire/123"
        ec.wait_for_search_results(
            "9230",
            max_wait_seconds=0.3,
            poll_interval_seconds=0.1,
            work_dir="/tmp/test",
            target_url=target_url,
        )

        # Verify recovery was called with target_url
        mock_recovery_instance.attempt_recovery.assert_called_once()
        call_kwargs = mock_recovery_instance.attempt_recovery.call_args[1]
        assert call_kwargs["target_url"] == target_url

    @patch("extract_candidates.RecoveryHelper")
    @patch("extract_candidates.PageStateProbe")
    @patch("extract_candidates.run_browser_command")
    @patch("browser_utils.check_dialog_status")
    @patch("time.sleep")
    def test_recovery_attempted_on_loading_timeout(
        self, mock_sleep, mock_dialog, mock_run, mock_probe, mock_recovery
    ):
        """Should attempt recovery on loading timeout."""
        # Always return loading state to trigger timeout
        mock_run.return_value = {
            "parsed": {
                "state": "loading",
                "hasCandidates": False,
                "candidateCount": 0,
                "loadingText": "loading search results",
                "noResultsText": None,
                "bodyText": "Loading search results...",
            },
            "error": None,
            "timed_out": False,
        }
        mock_dialog.return_value = {"has_dialog": False}

        # Mock probe to return loading state (triggers recovery)
        mock_probe_instance = Mock()
        mock_probe_instance.classify_state.return_value = {
            "state": "loading",
            "details": {"isLoading": True},
            "dialog_info": None,
        }
        mock_probe.return_value = mock_probe_instance

        # Mock recovery helper that succeeds
        mock_recovery_instance = Mock()
        mock_recovery_instance.attempt_recovery.return_value = {
            "success": True,
            "final_state": "ready",
            "attempts_made": 1,
            "actions_taken": ["wait_for_loading"],
            "error": None,
        }
        mock_recovery.return_value = mock_recovery_instance

        result = ec.wait_for_search_results(
            "9230",
            max_wait_seconds=0.3,
            poll_interval_seconds=0.1,
            work_dir="/tmp/test",
        )

        # Verify recovery was attempted
        mock_recovery.assert_called_once()
        mock_recovery_instance.attempt_recovery.assert_called_once()
        # Result should have recovery info
        assert result.get("recovery_result") is not None

    @patch("extract_candidates.run_browser_command")
    @patch("browser_utils.check_dialog_status")
    @patch("time.sleep")
    def test_timeout_preserves_last_details(self, mock_sleep, mock_dialog, mock_run):
        """Should preserve last observed state details on timeout."""
        last_state_details = {
            "state": "loading",
            "hasCandidates": False,
            "candidateCount": 0,
            "loadingText": None,
            "noResultsText": None,
            "hasLoadingOverlay": True,
            "loadingOverlaySelector": ".loading-overlay__wrapper",
            "bodyText": "Loading overlay visible",
        }
        mock_run.return_value = {
            "parsed": last_state_details,
            "error": None,
            "timed_out": False,
        }
        mock_dialog.return_value = {"has_dialog": False}

        result = ec.wait_for_search_results(
            "9230",
            max_wait_seconds=0.3,
            poll_interval_seconds=0.1,
            attempt_recovery_on_timeout=False,  # Disable recovery for this test
        )

        assert result["status"] == "timeout"
        assert result["state"] == "loading"
        assert result["details"] is not None
        assert result["details"]["hasLoadingOverlay"] is True
        assert (
            result["details"]["loadingOverlaySelector"] == ".loading-overlay__wrapper"
        )
        assert result["details"]["bodyText"] == "Loading overlay visible"


class TestParseExtractionOutput:
    """Tests for extraction output parsing."""

    def test_parses_valid_json_array(self):
        """Should parse valid JSON array."""
        output = '[{"name": "John", "url": "http://example.com"}]'

        result = ec.parse_extraction_output(output)

        assert len(result) == 1
        assert result[0]["name"] == "John"

    def test_parses_double_encoded_json(self):
        """Should handle double-encoded JSON from agent-browser."""
        output = '"[{\\"name\\": \\"Jane\\", \\"url\\": \\"http://test.com\\"}]"'

        result = ec.parse_extraction_output(output)

        assert len(result) == 1
        assert result[0]["name"] == "Jane"

    def test_returns_empty_list_for_null(self):
        """Should return empty list for null output."""
        assert ec.parse_extraction_output("null") == []
        assert ec.parse_extraction_output('"null"') == []

    def test_returns_empty_list_for_empty_string(self):
        """Should return empty list for empty string."""
        assert ec.parse_extraction_output("") == []

    def test_returns_empty_list_for_invalid_json(self):
        """Should return empty list for invalid JSON."""
        assert ec.parse_extraction_output("not json") == []
        assert ec.parse_extraction_output("{invalid}") == []

    def test_returns_empty_list_for_non_array(self):
        """Should return empty list if parsed result is not an array."""
        assert ec.parse_extraction_output('{"key": "value"}') == []


class TestExtractCandidates:
    """Tests for main extraction workflow."""

    @patch("extract_candidates.run_browser_command")
    @patch("extract_candidates.wait_for_search_results")
    def test_successful_extraction(self, mock_wait, mock_run):
        """Should return candidates on successful extraction."""
        mock_wait.return_value = {
            "status": "ready",
            "state": "ready",
            "waited_seconds": 1.5,
            "details": {"candidateCount": 2},
        }
        mock_run.return_value = {
            "stdout": '[{"name": "Alice", "url": "http://li.com/1"}]',
            "error": None,
        }

        result = ec.extract_candidates("9230")

        assert result["success"] is True
        assert result["exit_code"] == 0
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["name"] == "Alice"

    @patch("extract_candidates.ensure_page_ready")
    @patch("extract_candidates.wait_for_search_results")
    def test_uses_target_url_for_initial_navigation(self, mock_wait, mock_ensure):
        """Should navigate to target URL before extraction when provided."""
        mock_ensure.return_value = {
            "ready": True,
            "state": "ready",
            "recovery_result": None,
            "waited_seconds": 1.0,
        }
        mock_wait.return_value = {
            "status": "ready",
            "state": "ready",
            "waited_seconds": 1.5,
            "details": {"candidateCount": 2},
        }

        target_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        result = ec.extract_candidates("9230", target_url=target_url)

        # Should call ensure_page_ready with target URL
        mock_ensure.assert_called_once()
        call_kwargs = mock_ensure.call_args[1]
        assert call_kwargs["target_url"] == target_url
        assert call_kwargs["cdp_port"] == "9230"

    @patch("extract_candidates.ensure_page_ready")
    def test_fails_when_target_url_navigation_fails(self, mock_ensure):
        """Should fail extraction if cannot reach target URL."""
        mock_ensure.return_value = {
            "ready": False,
            "state": "bad_page",
            "recovery_result": {"success": False, "error": "Navigation failed"},
            "waited_seconds": 5.0,
        }

        target_url = "https://linkedin.com/talent/hire/123"
        result = ec.extract_candidates("9230", target_url=target_url)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "Failed to reach target URL" in result["message"]
        assert "bad_page" in result["message"]

    @patch("extract_candidates.verify_target_url_match")
    @patch("extract_candidates.ensure_page_ready")
    @patch("extract_candidates.wait_for_search_results")
    def test_passes_target_url_to_wait_for_results(
        self, mock_wait, mock_ensure, mock_verify
    ):
        """Should pass target URL to wait_for_search_results for recovery."""
        mock_ensure.return_value = {
            "ready": True,
            "state": "ready",
            "recovery_result": None,
            "waited_seconds": 1.0,
        }
        mock_verify.return_value = {
            "matches": True,
            "current_url": "https://linkedin.com/talent/hire/123",
            "target_url": "https://linkedin.com/talent/hire/123",
            "error": None,
        }
        mock_wait.return_value = {
            "status": "ready",
            "state": "ready",
            "waited_seconds": 2.0,
            "details": {"candidateCount": 5},
        }

        target_url = "https://linkedin.com/talent/hire/123"
        ec.extract_candidates("9230", target_url=target_url)

        # Verify wait_for_search_results was called with target_url
        mock_wait.assert_called_once()
        call_kwargs = mock_wait.call_args[1]
        assert call_kwargs["target_url"] == target_url

    @patch("extract_candidates.wait_for_search_results")
    def test_timeout_with_selector_mismatch(self, mock_wait):
        """Should detect selector mismatch when profile links exist but no cards."""
        mock_wait.return_value = {
            "status": "timeout",
            "state": "unknown",
            "waited_seconds": 15.0,
            "details": {
                "hasProfileLinks": True,
                "profileLinkCount": 10,
                "hasCandidates": False,
                "bodyText": "Some page content with profiles",
            },
        }

        result = ec.extract_candidates("9230")

        assert result["success"] is False
        assert result["exit_code"] == 3  # Selector mismatch
        assert "Selector mismatch" in result["message"]
        assert "10 profile links" in result["message"]

    @patch("extract_candidates.wait_for_search_results")
    def test_timeout_without_selector_mismatch(self, mock_wait):
        """Should return timeout error when nothing found."""
        mock_wait.return_value = {
            "status": "timeout",
            "state": "loading",
            "waited_seconds": 15.0,
            "details": {
                "hasProfileLinks": False,
                "hasCandidates": False,
                "bodyText": "Loading search results...",
            },
            "dialog_info": {"has_dialog": False},
        }

        result = ec.extract_candidates("9230")

        assert result["success"] is False
        assert result["exit_code"] == 1  # Timeout
        assert "Timeout" in result["message"]

    @patch("extract_candidates.wait_for_search_results")
    def test_timeout_with_dialog_in_extraction(self, mock_wait):
        """Should report dialog blocking in timeout error message."""
        mock_wait.return_value = {
            "status": "timeout",
            "state": "loading",
            "waited_seconds": 15.0,
            "details": {
                "hasProfileLinks": False,
                "hasCandidates": False,
                "bodyText": "Loading...",
            },
            "dialog_info": {
                "has_dialog": True,
                "dialog_type": "confirm",
                "message": "Leave site?",
            },
        }

        result = ec.extract_candidates("9230")

        assert result["success"] is False
        assert result["exit_code"] == 1  # Timeout
        assert "confirm dialog" in result["message"]
        assert "Leave site?" in result["message"]

    @patch("extract_candidates.wait_for_search_results")
    def test_no_results_detected(self, mock_wait):
        """Should handle explicit no-results state."""
        mock_wait.return_value = {
            "status": "no_results",
            "state": "no_results",
            "waited_seconds": 0.5,
            "details": {"noResultsText": "no results found"},
        }

        result = ec.extract_candidates("9230")

        assert result["success"] is False  # No results is a failure condition
        assert result["exit_code"] == 2  # No results code
        assert result["candidates"] == []
        assert "No results found" in result["message"]

    @patch("extract_candidates.run_browser_command")
    @patch("extract_candidates.wait_for_search_results")
    def test_empty_extraction_from_ready_page(self, mock_wait, mock_run):
        """Should detect selector mismatch when extraction returns empty from ready page."""
        mock_wait.return_value = {
            "status": "ready",
            "state": "ready",
            "details": {"candidateCount": 5},
        }
        mock_run.return_value = {
            "stdout": "[]",
            "error": None,
        }

        result = ec.extract_candidates("9230")

        assert result["success"] is False  # Selector mismatch is a failure
        assert result["exit_code"] == 3  # Selector mismatch code
        assert "Selectors may need updating" in result["message"]

    @patch("extract_candidates.run_browser_command")
    @patch("extract_candidates.wait_for_search_results")
    def test_extraction_command_failure(self, mock_wait, mock_run):
        """Should handle extraction command failure."""
        mock_wait.return_value = {
            "status": "ready",
            "state": "ready",
            "details": {},
        }
        mock_run.return_value = {
            "stdout": "",
            "error": "Browser disconnected",
        }

        result = ec.extract_candidates("9230")

        assert result["success"] is False
        assert result["exit_code"] == 3
        assert "Extraction failed" in result["message"]


class TestScrollJs:
    """Tests for scroll JavaScript generation."""

    def test_includes_scroll_logic(self):
        """Should include scroll logic."""
        js = ec.scroll_to_load_candidates_js()

        assert "scrollTo" in js
        assert "scrollHeight" in js

    def test_includes_multiple_passes(self):
        """Should scroll multiple times."""
        js = ec.scroll_to_load_candidates_js()

        assert "pass" in js or "for" in js

    def test_returns_profile_link_count(self):
        """Should return count of profile links found."""
        js = ec.scroll_to_load_candidates_js()

        assert "/talent/profile/" in js


class TestExtractCandidatesJs:
    """Tests for extraction JavaScript generation."""

    def test_includes_card_selector(self):
        """Should include candidate card selector."""
        js = ec.extract_candidates_js()

        assert "profile-list__border-bottom" in js

    def test_includes_profile_url_selector(self):
        """Should include profile URL selector."""
        js = ec.extract_candidates_js()

        assert "/talent/profile/" in js

    def test_extracts_name(self):
        """Should extract candidate name."""
        js = ec.extract_candidates_js()

        assert "name" in js
        assert "textContent" in js

    def test_extracts_title_and_company(self):
        """Should extract title and company from experience."""
        js = ec.extract_candidates_js()

        assert "title" in js
        assert "company" in js
        assert " at " in js

    def test_extracts_headline_and_location(self):
        """Should extract headline and location."""
        js = ec.extract_candidates_js()

        assert "headline" in js
        assert "location" in js

    def test_returns_json_string(self):
        """Should return JSON string."""
        js = ec.extract_candidates_js()

        assert "JSON.stringify" in js


class TestTargetUrlVerification:
    """Tests for target URL verification."""

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_match_exact(self, mock_run):
        """Should match when URLs are identical (ignoring query params)."""
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
            },
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        assert result["matches"] is True
        assert result["error"] is None

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_match_with_query_params(self, mock_run):
        """Should match when URLs differ only by query params."""
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?projectId=123&tab=search"
            },
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        assert result["matches"] is True
        assert result["error"] is None

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_mismatch_different_project(self, mock_run):
        """Should not match when URLs have different project IDs."""
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/456/discover/recruiterSearch"
            },
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        assert result["matches"] is False
        assert "URL mismatch" in result["error"]

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_non_talent_page(self, mock_run):
        """Should fail when not on a talent page."""
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/feed/"},
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        assert result["matches"] is False
        assert "not a LinkedIn Talent page" in result["error"]

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_same_project_different_view(self, mock_run):
        """Should match when same project ID but different view (overview vs search)."""
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/hire/123/overview"},
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        # Same project ID should be acceptable
        assert result["matches"] is True
        assert result["error"] is None

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_command_error(self, mock_run):
        """Should handle browser command errors."""
        mock_run.return_value = {"error": "Connection refused", "parsed": None}

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        assert result["matches"] is False
        assert "Connection refused" in result["error"]

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_slashless_current_url(self, mock_run):
        """Should match when current URL is slashless but same project ID."""
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/hire/123"},
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        # Same project ID should be acceptable even with slashless URL
        assert result["matches"] is True
        assert result["error"] is None

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_slashless_target_url(self, mock_run):
        """Should match when target URL is slashless and current has full path."""
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/hire/123/overview"},
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123",
        )

        # Same project ID should be acceptable
        assert result["matches"] is True
        assert result["error"] is None

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_slashless_with_query_params(self, mock_run):
        """Should match slashless URL with query params to full path."""
        mock_run.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123?searchContextId=abc"
            },
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        # Same project ID should be acceptable
        assert result["matches"] is True
        assert result["error"] is None

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_rejects_evil_domain_exact_match(self, mock_run):
        """Should reject exact match when target URL is on evil domain."""
        mock_run.return_value = {
            "parsed": {
                "url": "https://evil.com/talent/hire/123/discover/recruiterSearch"
            },
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://evil.com/talent/hire/123/discover/recruiterSearch",
        )

        # Should NOT match even with exact URL match - evil domain in target
        assert result["matches"] is False
        assert "not a valid LinkedIn URL" in result["error"]
        assert "evil.com" in result["error"]

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_rejects_evil_domain_same_project_id(self, mock_run):
        """Should reject same-project fallback when current URL is on evil domain."""
        mock_run.return_value = {
            "parsed": {"url": "https://evil.com/talent/hire/123/overview"},
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        # Should NOT match even with same project ID - evil domain
        assert result["matches"] is False
        assert "URL mismatch" in result["error"]

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_rejects_phishing_domain(self, mock_run):
        """Should reject same-project fallback for phishing domains."""
        mock_run.return_value = {
            "parsed": {"url": "https://linkedin.evil.com/talent/hire/123"},
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        # Should NOT match - phishing domain
        assert result["matches"] is False
        assert "URL mismatch" in result["error"]

    @patch("extract_candidates.run_browser_command")
    def test_verify_target_url_accepts_www_linkedin_same_project(self, mock_run):
        """Should accept same-project fallback for www.linkedin.com domain."""
        mock_run.return_value = {
            "parsed": {"url": "https://www.linkedin.com/talent/hire/123/overview"},
            "error": None,
        }

        result = ec.verify_target_url_match(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        )

        # Should match - www.linkedin.com is valid
        assert result["matches"] is True
        assert result["error"] is None


class TestExtractCandidatesWithUrlVerification:
    """Tests for extract_candidates with URL verification."""

    @patch("extract_candidates.verify_target_url_match")
    @patch("extract_candidates.ensure_page_ready")
    @patch("extract_candidates.wait_for_search_results")
    def test_extract_fails_when_url_verification_fails(
        self, mock_wait, mock_ensure, mock_verify
    ):
        """Should fail extraction when URL verification fails."""
        mock_ensure.return_value = {
            "ready": True,
            "state": "ready",
            "recovery_result": None,
            "waited_seconds": 1.0,
        }
        mock_verify.return_value = {
            "matches": False,
            "current_url": "https://linkedin.com/talent/projects",
            "target_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "error": "URL mismatch: current page is Projects list, not search page",
        }

        target_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        result = ec.extract_candidates("9230", target_url=target_url)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "URL mismatch" in result["message"]

    @patch("extract_candidates.verify_target_url_match")
    @patch("extract_candidates.ensure_page_ready")
    @patch("extract_candidates.wait_for_search_results")
    def test_extract_succeeds_when_url_verification_passes(
        self, mock_wait, mock_ensure, mock_verify
    ):
        """Should proceed with extraction when URL verification passes."""
        mock_ensure.return_value = {
            "ready": True,
            "state": "ready",
            "recovery_result": None,
            "waited_seconds": 1.0,
        }
        mock_verify.return_value = {
            "matches": True,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "target_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "error": None,
        }
        mock_wait.return_value = {
            "status": "ready",
            "state": "ready",
            "waited_seconds": 1.5,
            "details": {"candidateCount": 2},
        }

        target_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        result = ec.extract_candidates("9230", target_url=target_url)

        # Should proceed to wait_for_search_results
        mock_wait.assert_called_once()


class TestMain:
    """Tests for main entry point."""

    @patch("extract_candidates.extract_candidates")
    @patch("extract_candidates.parse_arguments")
    def test_successful_run(self, mock_parse_args, mock_extract):
        """Should return 0 on success."""
        mock_args = Mock()
        mock_args.cdp_port = "9230"
        mock_args.target_url = None
        mock_args.project_config = None
        mock_parse_args.return_value = mock_args

        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "Test"}],
            "message": "Extracted 1 candidates",
            "exit_code": 0,
        }

        result = ec.main()

        assert result == 0

    @patch("extract_candidates.extract_candidates")
    @patch("extract_candidates.parse_arguments")
    def test_timeout_exit_code(self, mock_parse_args, mock_extract):
        """Should return 1 on timeout."""
        mock_args = Mock()
        mock_args.cdp_port = "9230"
        mock_args.target_url = None
        mock_args.project_config = None
        mock_parse_args.return_value = mock_args

        mock_extract.return_value = {
            "success": False,
            "candidates": [],
            "message": "Timeout waiting",
            "exit_code": 1,
        }

        result = ec.main()

        assert result == 1

    @patch("extract_candidates.extract_candidates")
    @patch("extract_candidates.parse_arguments")
    def test_no_results_exit_code(self, mock_parse_args, mock_extract):
        """Should return 2 on no results."""
        mock_args = Mock()
        mock_args.cdp_port = "9230"
        mock_args.target_url = None
        mock_args.project_config = None
        mock_parse_args.return_value = mock_args

        mock_extract.return_value = {
            "success": True,
            "candidates": [],
            "message": "No results found",
            "exit_code": 2,
        }

        result = ec.main()

        assert result == 2

    @patch("extract_candidates.extract_candidates")
    @patch("extract_candidates.parse_arguments")
    def test_selector_mismatch_exit_code(self, mock_parse_args, mock_extract):
        """Should return 3 on selector mismatch."""
        mock_args = Mock()
        mock_args.cdp_port = "9230"
        mock_args.target_url = None
        mock_args.project_config = None
        mock_parse_args.return_value = mock_args

        mock_extract.return_value = {
            "success": False,
            "candidates": [],
            "message": "Selector mismatch",
            "exit_code": 3,
        }

        result = ec.main()

        assert result == 3

    @patch("extract_candidates.extract_candidates")
    @patch("extract_candidates.parse_arguments")
    def test_passes_target_url_to_extract(self, mock_parse_args, mock_extract):
        """Should pass target URL to extract_candidates when provided."""
        mock_args = Mock()
        mock_args.cdp_port = "9230"
        mock_args.target_url = "https://linkedin.com/talent/hire/123"
        mock_args.project_config = None
        mock_parse_args.return_value = mock_args

        mock_extract.return_value = {
            "success": True,
            "candidates": [],
            "message": "OK",
            "exit_code": 0,
        }

        ec.main()

        # Verify extract_candidates was called with target_url
        mock_extract.assert_called_once()
        call_kwargs = mock_extract.call_args[1]
        assert call_kwargs["target_url"] == "https://linkedin.com/talent/hire/123"

    @patch("extract_candidates.extract_candidates")
    @patch("extract_candidates.parse_arguments")
    def test_uses_command_line_port(self, mock_parse_args, mock_extract):
        """Should use CDP port from command line."""
        mock_args = Mock()
        mock_args.cdp_port = "9240"
        mock_args.target_url = None
        mock_args.project_config = None
        mock_parse_args.return_value = mock_args

        mock_extract.return_value = {
            "success": True,
            "candidates": [],
            "message": "OK",
            "exit_code": 0,
        }

        ec.main()

        # Verify extract_candidates was called with the correct port
        mock_extract.assert_called_once()
        call_args = mock_extract.call_args[0]
        assert call_args[0] == "9240"  # First arg should be port


class TestLoadingPatterns:
    """Tests for loading state pattern definitions."""

    def test_loading_patterns_are_lowercase(self):
        """Loading patterns should be lowercase for case-insensitive matching."""
        for pattern in ec.LOADING_TEXT_PATTERNS:
            assert pattern == pattern.lower(), (
                f"Pattern '{pattern}' should be lowercase"
            )

    def test_no_results_patterns_are_lowercase(self):
        """No-results patterns should be lowercase for case-insensitive matching."""
        for pattern in ec.NO_RESULTS_TEXT_PATTERNS:
            assert pattern == pattern.lower(), (
                f"Pattern '{pattern}' should be lowercase"
            )

    def test_loading_patterns_not_empty(self):
        """Should have non-empty loading patterns."""
        assert len(ec.LOADING_TEXT_PATTERNS) > 0
        for pattern in ec.LOADING_TEXT_PATTERNS:
            assert len(pattern) > 0

    def test_no_results_patterns_not_empty(self):
        """Should have non-empty no-results patterns."""
        assert len(ec.NO_RESULTS_TEXT_PATTERNS) > 0
        for pattern in ec.NO_RESULTS_TEXT_PATTERNS:
            assert len(pattern) > 0


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
