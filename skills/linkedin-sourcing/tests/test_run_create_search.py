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

    def test_excludes_tiktok_for_lifeattiktok_jd(self):
        """TikTok and ByteDance should be excluded from target companies for TikTok JDs."""
        config = {
            "POSITION_TITLE": "Software Engineer",
            "COMPANIES": "TikTok, ByteDance, Google, Meta",
        }
        jd_text = "Join our team at TikTok! Visit lifeattiktok.com for more info."
        jd_url = "https://lifeattiktok.com/jobs/123"

        brief = rcs.build_search_brief(config, jd_text, jd_url)

        # Should NOT include TikTok or ByteDance as target companies
        if "Target companies:" in brief:
            companies_section = brief.split("Target companies:")[1].split("\n")[0]
            assert "TikTok" not in companies_section, (
                f"TikTok should be excluded from target companies in: {companies_section}"
            )
            assert "ByteDance" not in companies_section, (
                f"ByteDance should be excluded from target companies in: {companies_section}"
            )
        # Should include other companies
        assert "Google" in brief
        assert "Meta" in brief

    def test_excludes_bytedance_aliases_for_tiktok_jd(self):
        """All ByteDance/TikTok aliases should be excluded for TikTok JDs."""
        config = {
            "POSITION_TITLE": "Engineer",
            "COMPANIES": "TikTok, Byte Dance, Google",
        }
        jd_url = "https://tiktok.com/careers"

        brief = rcs.build_search_brief(config, "", jd_url)

        # Should exclude both TikTok and Byte Dance
        companies_section = (
            brief.split("Target companies:")[1] if "Target companies:" in brief else ""
        )
        assert "TikTok" not in companies_section
        assert "Byte Dance" not in companies_section
        assert "Google" in brief


class TestRunCreateSearchPhase:
    """Tests for the Create Search phase runner."""

    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_returns_success_with_copilot_query(self, mock_resolve, mock_ctx, tmp_path):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        (tmp_path / "job_description.txt").write_text("Focus on CV", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
                "POSITION_TITLE": "Research Engineer",
            },
            "123",
        )

        result = rcs.run_create_search_phase("proj-1")

        assert result["success"] is True
        assert result["phase"] == "create_search"
        assert result["status"] == "completed"
        assert result["next_phase"] == "confirm_search"
        assert "Research Engineer" in result["search_brief"]
        assert "copilot_query" in result
        assert "Create a LinkedIn Recruiter candidate search" in result["copilot_query"]

    @patch("project_state.update_project_state")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_updates_project_state_correctly(
        self, mock_resolve, mock_ctx, mock_update, tmp_path
    ):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        (tmp_path / "job_description.txt").write_text("Test JD", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
                "POSITION_TITLE": "Engineer",
            },
            "123",
        )
        mock_update.return_value = {}

        result = rcs.run_create_search_phase("proj-1")

        assert result["success"] is True
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs["current_phase"] == "create_search"
        assert call_kwargs["status"] == "completed"
        assert call_kwargs["action_required"] is False
        assert call_kwargs["last_error"] is False
        summary = call_kwargs["create_search_summary"]
        assert summary["recruiter_url"] == "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        assert "copilot_query" in summary
        assert "search_brief" in summary

    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_raises_config_error_when_recruiter_url_missing(
        self, mock_resolve, mock_ctx, tmp_path
    ):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (config_path, {"PROJECT_ID": "proj-1"}, "123")

        with pytest.raises(rcs.CreateSearchError) as exc_info:
            rcs.run_create_search_phase("proj-1")

        assert "RECRUITER_PROJECT_URL" in str(exc_info.value)


class TestEffectiveTargetCompanies:
    """Tests for effective target companies computation (hiring company exclusion)."""

    def test_returns_all_companies_for_non_tiktok_jd(self):
        """Should return all companies when JD is not from TikTok/ByteDance."""
        config = {"COMPANIES": "Google, Meta, TikTok, ByteDance"}

        result = rcs.get_effective_target_companies(config, "Some generic JD", "")

        assert "Google" in result
        assert "Meta" in result
        assert "TikTok" in result
        assert "ByteDance" in result

    def test_excludes_tiktok_for_lifeattiktok_url(self):
        """Should exclude TikTok/ByteDance when JD URL is lifeattiktok.com."""
        config = {"COMPANIES": "TikTok, ByteDance, Google, Meta"}

        result = rcs.get_effective_target_companies(
            config, "", "https://lifeattiktok.com/jobs/123"
        )

        assert "TikTok" not in result
        assert "ByteDance" not in result
        assert "Google" in result
        assert "Meta" in result

    def test_excludes_tiktok_for_tiktok_com_url(self):
        """Should exclude TikTok/ByteDance when JD URL is tiktok.com."""
        config = {"COMPANIES": "TikTok, Google"}

        result = rcs.get_effective_target_companies(
            config, "", "https://tiktok.com/careers"
        )

        assert "TikTok" not in result
        assert "Google" in result

    def test_excludes_tiktok_for_bytedance_com_url(self):
        """Should exclude TikTok/ByteDance when JD URL is bytedance.com."""
        config = {"COMPANIES": "ByteDance, Google"}

        result = rcs.get_effective_target_companies(
            config, "", "https://bytedance.com/jobs"
        )

        assert "ByteDance" not in result
        assert "Google" in result

    def test_excludes_tiktok_for_lifeattiktok_in_jd_text(self):
        """Should exclude TikTok/ByteDance when lifeattiktok appears in JD text."""
        config = {"COMPANIES": "TikTok, ByteDance, Google"}
        jd_text = "Visit LifeAtTikTok for more information about our culture"

        result = rcs.get_effective_target_companies(config, jd_text, "")

        assert "TikTok" not in result
        assert "ByteDance" not in result
        assert "Google" in result

    def test_handles_empty_companies_config(self):
        """Should handle empty COMPANIES config gracefully."""
        config = {}

        result = rcs.get_effective_target_companies(
            config, "", "https://lifeattiktok.com"
        )

        assert result == []

    def test_preserves_original_case_for_non_excluded_companies(self):
        """Should preserve original case for companies that are not excluded."""
        config = {"COMPANIES": "Google, Meta, ByteDance"}

        result = rcs.get_effective_target_companies(
            config, "", "https://lifeattiktok.com"
        )

        assert "Google" in result
        assert "Meta" in result
        # ByteDance should be excluded
        assert "ByteDance" not in result

    def test_does_not_over_exclude_similar_names(self):
        """REGRESSION: Should use exact matching, not substring matching for exclusions.

        Issue: Substring matching like 'tiktok' in 'TikTokAnalytics' would incorrectly
        exclude unrelated companies. Should only exclude exact alias matches.
        """
        config = {
            "COMPANIES": "TikTok, TikTokAnalytics, ByteDance, ByteDanceResearch, Google"
        }

        result = rcs.get_effective_target_companies(
            config, "", "https://lifeattiktok.com"
        )

        # Exact matches should be excluded
        assert "TikTok" not in result
        assert "ByteDance" not in result
        # Similar names should NOT be excluded (not exact matches)
        assert "TikTokAnalytics" in result, (
            "TikTokAnalytics should NOT be excluded - not an exact match"
        )
        assert "ByteDanceResearch" in result, (
            "ByteDanceResearch should NOT be excluded - not an exact match"
        )
        # Unrelated companies should be preserved
        assert "Google" in result

    def test_does_not_exclude_companies_containing_tiktok_substring(self):
        """Companies containing 'tiktok' as substring but not exact match should be kept."""
        config = {"COMPANIES": "MyTikTokTool, TikTok, TikTokHelper"}

        result = rcs.get_effective_target_companies(
            config, "", "https://tiktok.com/careers"
        )

        # Only exact "TikTok" should be excluded
        assert "TikTok" not in result
        # Substring matches should be preserved
        assert "MyTikTokTool" in result
        assert "TikTokHelper" in result


class TestBuildActionRequired:
    """Tests for build_action_required."""

    def test_includes_copilot_query_when_provided(self):
        result = rcs.build_action_required(
            recruiter_url="https://example.com",
            search_brief="brief",
            copilot_query="query text",
        )

        assert result["code"] == "search_not_configured"
        assert result["context"]["copilot_query"] == "query text"
        assert any("copilot_query" in step for step in result["steps"])

    def test_omits_copilot_query_when_empty(self):
        result = rcs.build_action_required(
            recruiter_url="https://example.com",
            search_brief="brief",
            copilot_query="",
        )

        assert "copilot_query" not in result["context"]

    def test_steps_are_present(self):
        result = rcs.build_action_required(
            recruiter_url="https://example.com",
            search_brief="brief",
            copilot_query="query",
        )

        assert len(result["steps"]) == 6
        assert result["can_retry"] is True
        assert result["actor"] == "agent"


class TestBuildCopilotSearchQuery:
    """Tests for build_copilot_search_query."""

    def test_includes_all_config_fields(self):
        config = {
            "POSITION_TITLE": "Software Engineer",
            "LOCATION": "Bay Area",
            "KEYWORDS": "Python, Kubernetes",
            "COMPANIES": "Google, Meta",
            "EXCLUDE_TITLES": "recruiter",
        }

        query = rcs.build_copilot_search_query(config)

        assert "Software Engineer" in query
        assert "Bay Area" in query
        assert "Python" in query
        assert "Google" in query
        assert "recruiter" in query

    def test_excludes_hiring_company_for_tiktok_jd(self):
        config = {
            "POSITION_TITLE": "Engineer",
            "COMPANIES": "TikTok, ByteDance, Google",
        }

        query = rcs.build_copilot_search_query(config, jd_url="https://lifeattiktok.com")

        assert "TikTok" not in query
        assert "ByteDance" not in query
        assert "Google" in query

    def test_handles_empty_config(self):
        query = rcs.build_copilot_search_query({})

        assert "Create a LinkedIn Recruiter candidate search" in query
        assert "Job title filter" not in query
