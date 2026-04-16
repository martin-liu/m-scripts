#!/usr/bin/env python3
"""Tests for run_create_search.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_create_search as rcs


class TestBuildSearchBrief:
    """Tests for search brief generation."""

    def test_includes_config_and_jd_context(self):
        config = {
            "POSITION_TITLE": "Research Engineer",
            "TEAM_NAME": "Vision",
            "LOCATION": "Bay Area",
            "KEYWORDS": "computer vision, multimodal, pytorch",
            "COMPANIES": "Google, Meta",
            "EXCLUDE_TITLES": "recruiter, manager",
        }

        brief = rcs.build_search_brief(
            config, "Need hands-on ICs building video understanding systems"
        )

        assert "Research Engineer - Vision" in brief
        assert "Preferred locations: Bay Area" in brief
        assert "Target companies: Google, Meta" in brief
        assert "Exclude titles: recruiter, manager" in brief
        assert "JD context:" in brief

    def test_strips_html_noise_from_jd_context(self):
        config = {"POSITION_TITLE": "Platform Engineer"}
        html_jd = (
            "<!DOCTYPE html><html><head><title>Job</title><style>.x{}</style></head>"
            "<body><nav>LifeAtTikTok Jobs Locations</nav>"
            "<p>Responsibilities</p><ul><li>Build CDN systems</li></ul>"
            "<p>Qualifications</p><p>Go Python HTTP DNS</p></body></html>"
        )

        brief = rcs.build_search_brief(config, html_jd)

        assert "<!DOCTYPE html>" not in brief
        assert "<html>" not in brief
        assert "LifeAtTikTok" not in brief
        assert "Build CDN systems" in brief
        assert "Go Python HTTP DNS" in brief


class TestRunCreateSearchPhase:
    """Tests for the Create Search phase runner."""

    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_brief_only_returns_search_brief(self, mock_resolve, mock_ctx, tmp_path):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        (tmp_path / "job_description.txt").write_text("Test JD", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
                "POSITION_TITLE": "Engineer",
            },
            "123",
        )

        result = rcs.run_create_search_phase("proj-1", brief_only=True)

        assert result["success"] is True
        assert result["status"] == "brief_only"
        assert result["phase"] == "create_search"
        assert result["next_phase"] == "create_search"
        assert result["cdp_port"] == "9234"
        assert "Engineer" in result["search_brief"]

    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_returns_ready_when_candidates_already_visible(
        self, mock_resolve, mock_ctx, mock_inspect, tmp_path
    ):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        mock_inspect.return_value = {
            "success": True,
            "status": "ready",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "failure_code": None,
        }

        result = rcs.run_create_search_phase("proj-1")

        assert result["success"] is True
        assert result["phase"] == "create_search"
        assert result["status"] == "ready"
        assert result["next_phase"] == "extract"
        assert "visible candidates" in result["message"]

    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_returns_manual_action_when_search_not_configured(
        self, mock_resolve, mock_ctx, mock_inspect, tmp_path
    ):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        (tmp_path / "job_description.txt").write_text("Focus on CV", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
                "POSITION_TITLE": "Research Engineer",
            },
            "123",
        )
        mock_inspect.return_value = {
            "success": False,
            "status": "search_not_configured",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "failure_code": "search_not_configured",
            "action_required": None,
        }

        result = rcs.run_create_search_phase("proj-1")

        assert result["success"] is False
        assert result["phase"] == "create_search"
        assert result["status"] == "search_not_configured"
        assert result["next_phase"] == "create_search"
        assert result["action_required"]["code"] == "search_not_configured"
        assert "search_brief" in result["action_required"]["context"]

    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_raises_config_error_when_recruiter_url_missing(
        self, mock_resolve, mock_ctx, tmp_path
    ):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (config_path, {"PROJECT_ID": "proj-1"}, "123")

        with pytest.raises(rcs.CreateSearchError) as exc_info:
            rcs.run_create_search_phase("proj-1")

        assert "RECRUITER_PROJECT_URL" in str(exc_info.value)


class TestInspectSearchState:
    """Tests for browser inspection logic."""

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("browser_utils.run_browser_command")
    def test_detects_search_creation_prompt(
        self, mock_run_browser, mock_probe_class, mock_ensure_ready
    ):
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_run_browser.side_effect = [
            {"error": None},
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
                }
            },
        ]
        mock_probe = MagicMock()
        mock_probe.classify_state.return_value = {
            "state": "ready",
            "details": {
                "hasSearchCreationPrompt": True,
                "hasSearchResultsContent": False,
            },
        }
        mock_probe_class.return_value = mock_probe

        result = rcs.inspect_search_state(
            "9234", "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )

        assert result["success"] is False
        assert result["status"] == "search_not_configured"

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("browser_utils.run_browser_command")
    def test_returns_not_ready_when_page_never_settles(
        self, mock_run_browser, mock_ensure_ready
    ):
        mock_run_browser.return_value = {"error": None}
        mock_ensure_ready.return_value = {
            "ready": False,
            "state": "loading",
            "failure_code": "timeout",
            "action_required": {"code": "timeout"},
        }

        result = rcs.inspect_search_state(
            "9234", "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )

        assert result["success"] is False
        assert result["status"] == "loading"
        assert result["failure_code"] == "timeout"

    @patch("browser_utils.classify_browser_readiness")
    @patch("browser_utils.run_browser_command")
    def test_returns_action_required_on_open_error(
        self, mock_run_browser, mock_classify
    ):
        mock_run_browser.return_value = {"error": "connection refused"}
        mock_readiness = MagicMock()
        mock_readiness.action_required = MagicMock()
        mock_readiness.action_required.code = "browser_unavailable"
        mock_readiness.action_required.to_dict.return_value = {
            "code": "browser_unavailable"
        }
        mock_classify.return_value = mock_readiness

        result = rcs.inspect_search_state(
            "9234", "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )

        assert result["success"] is False
        assert result["failure_code"] == "browser_unavailable"

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("browser_utils.run_browser_command")
    def test_not_ready_when_search_creation_prompt_visible(
        self, mock_run_browser, mock_probe_class, mock_ensure_ready
    ):
        """Should NOT report ready when hasSearchResultsContent=True but hasSearchCreationPrompt also True.

        This tests the fix for the false-positive gap where the script reported
        status=ready when the Recruiter page still showed 'Start a search'.
        """
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_run_browser.side_effect = [
            {"error": None},
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
                }
            },
        ]
        mock_probe = MagicMock()
        # Simulate the problematic state: hasSearchResultsContent=True BUT also hasSearchCreationPrompt=True
        mock_probe.classify_state.return_value = {
            "state": "ready",
            "details": {
                "hasSearchCreationPrompt": True,
                "hasSearchResultsContent": True,  # This was causing false positive
            },
        }
        mock_probe_class.return_value = mock_probe

        result = rcs.inspect_search_state(
            "9234", "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )

        # Should NOT be ready when search creation prompt is visible
        assert result["success"] is False
        assert result["status"] != "ready"

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("browser_utils.run_browser_command")
    def test_fails_on_cross_project_mismatch(
        self, mock_run_browser, mock_probe_class, mock_ensure_ready
    ):
        """Should NOT report ready when browser is on a different project than intended.

        This tests the fix for the cross-project false positive where the script
        reported success/ready for project 1692252652 but the browser was actually
        on project 1691575116.
        """
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        # Browser is on WRONG project (1691575116 instead of 1692252652)
        mock_run_browser.side_effect = [
            {"error": None},
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/hire/1691575116/discover/recruiterSearch"
                }
            },
        ]
        mock_probe = MagicMock()
        mock_probe.classify_state.return_value = {
            "state": "ready",
            "details": {
                "hasSearchCreationPrompt": False,
                "hasSearchResultsContent": True,
            },
        }
        mock_probe_class.return_value = mock_probe

        result = rcs.inspect_search_state(
            "9234",
            "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch",
        )

        # Should NOT be ready when on wrong project
        assert result["success"] is False
        assert result["status"] == "wrong_project"
        assert result["failure_code"] == "wrong_page"
        assert "1691575116" in result["current_url"]
        assert result["action_required"] is not None


class TestExtractProjectIdFromUrl:
    """Tests for project ID extraction from URLs."""

    def test_extracts_project_id_from_standard_url(self):
        url = "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch"
        assert rcs._extract_project_id_from_url(url) == "1692252652"

    def test_extracts_project_id_with_query_params(self):
        url = "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch?searchContextId=abc"
        assert rcs._extract_project_id_from_url(url) == "1692252652"

    def test_returns_none_for_non_recruiter_url(self):
        url = "https://linkedin.com/feed/"
        assert rcs._extract_project_id_from_url(url) is None

    def test_returns_none_for_invalid_url(self):
        url = "not-a-url"
        assert rcs._extract_project_id_from_url(url) is None


class TestVolatileParamRegression:
    """REGRESSION TESTS: Volatile query params should not cause wrong_page failure.

    Issue: run_create_search.py --project 1692252652 returned wrong_page because
    the actual URL differed from expected only in volatile Recruiter query params
    like searchRequestId, searchContextId, searchHistoryId.

    Both URLs were the same project and same /discover/recruiterSearch page.
    The fix ensures these volatile params are ignored in URL comparison.
    """

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("browser_utils.run_browser_command")
    def test_same_project_with_volatile_params_not_wrong_page(
        self, mock_run_browser, mock_probe_class, mock_ensure_ready
    ):
        """REGRESSION: Same project with different volatile params should proceed to state check.

        Simulates the live failure where:
        - Expected URL: /talent/hire/1692252652/discover/recruiterSearch (from config)
        - Actual URL: /talent/hire/1692252652/discover/recruiterSearch?searchRequestId=...
        - Should NOT return wrong_page, should proceed to search_not_configured check
        """
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        # Browser returns URL with volatile params
        mock_run_browser.side_effect = [
            {"error": None},
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch?searchRequestId=abc123&searchContextId=xyz789"
                }
            },
        ]
        mock_probe = MagicMock()
        # Page shows search creation prompt (no results yet)
        mock_probe.classify_state.return_value = {
            "state": "ready",
            "details": {
                "hasSearchCreationPrompt": True,
                "hasSearchResultsContent": False,
            },
        }
        mock_probe_class.return_value = mock_probe

        result = rcs.inspect_search_state(
            "9234",
            "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch",
        )

        # Should NOT be wrong_page - should be search_not_configured
        assert result["success"] is False
        assert result["status"] == "search_not_configured"
        assert result["failure_code"] == "search_not_configured"
        assert "wrong_page" not in result.get("status", "")

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("browser_utils.run_browser_command")
    def test_same_project_with_searchhistoryid_not_wrong_page(
        self, mock_run_browser, mock_probe_class, mock_ensure_ready
    ):
        """Same project with searchHistoryId param should not be wrong_page."""
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_run_browser.side_effect = [
            {"error": None},
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch?searchHistoryId=history123"
                }
            },
        ]
        mock_probe = MagicMock()
        mock_probe.classify_state.return_value = {
            "state": "ready",
            "details": {
                "hasSearchCreationPrompt": True,
                "hasSearchResultsContent": False,
            },
        }
        mock_probe_class.return_value = mock_probe

        result = rcs.inspect_search_state(
            "9234",
            "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch",
        )

        # Should NOT be wrong_page
        assert result["status"] == "search_not_configured"
        assert result.get("failure_code") != "wrong_page"
