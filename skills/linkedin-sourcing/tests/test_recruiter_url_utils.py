#!/usr/bin/env python3
"""Tests for recruiter_url_utils.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_recruiter_url_utils.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import recruiter_url_utils as ruu


class TestExtractRecruiterIdFromUrl:
    """Tests for extract_recruiter_id_from_url function."""

    def test_extracts_from_search_url(self):
        """Should extract ID from recruiterSearch URL."""
        url = "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        assert ruu.extract_recruiter_id_from_url(url) == "12345"

    def test_extracts_from_overview_url(self):
        """Should extract ID from overview URL."""
        url = "https://linkedin.com/talent/hire/67890/overview"
        assert ruu.extract_recruiter_id_from_url(url) == "67890"

    def test_extracts_from_projects_url(self):
        """Should extract ID from projects URL."""
        url = "https://linkedin.com/talent/hire/11111/projects"
        assert ruu.extract_recruiter_id_from_url(url) == "11111"

    def test_extracts_from_url_with_params(self):
        """Should extract ID from URL with query parameters."""
        url = "https://linkedin.com/talent/hire/54321/discover/recruiterSearch?searchContextId=abc"
        assert ruu.extract_recruiter_id_from_url(url) == "54321"

    def test_extracts_from_url_without_trailing_slash(self):
        """Should extract ID from URL without trailing slash."""
        url = "https://linkedin.com/talent/hire/12345"
        assert ruu.extract_recruiter_id_from_url(url) == "12345"

    def test_extracts_from_url_with_query_no_trailing_slash(self):
        """Should extract ID from URL with query params but no trailing slash."""
        url = "https://linkedin.com/talent/hire/12345?searchContextId=abc"
        assert ruu.extract_recruiter_id_from_url(url) == "12345"

    def test_extracts_from_url_with_hash_no_trailing_slash(self):
        """Should extract ID from URL with hash fragment but no trailing slash."""
        url = "https://linkedin.com/talent/hire/12345#tab"
        assert ruu.extract_recruiter_id_from_url(url) == "12345"

    def test_extracts_from_www_subdomain(self):
        """Should extract ID from www.linkedin.com subdomain."""
        url = "https://www.linkedin.com/talent/hire/54321"
        assert ruu.extract_recruiter_id_from_url(url) == "54321"

    def test_returns_none_for_invalid_url(self):
        """Should return None for URLs without talent/hire pattern."""
        assert ruu.extract_recruiter_id_from_url("https://linkedin.com/feed/") is None
        assert ruu.extract_recruiter_id_from_url("https://example.com") is None
        assert ruu.extract_recruiter_id_from_url("not-a-url") is None
        assert ruu.extract_recruiter_id_from_url("") is None

    def test_returns_none_for_non_numeric_id(self):
        """Should return None for non-numeric IDs in URL."""
        url = "https://linkedin.com/talent/hire/abc123/overview"
        assert ruu.extract_recruiter_id_from_url(url) is None

    def test_returns_none_for_malformed_talent_url(self):
        """Should return None for malformed talent URLs."""
        # Missing numeric ID
        assert (
            ruu.extract_recruiter_id_from_url("https://linkedin.com/talent/hire/")
            is None
        )
        # Wrong path
        assert (
            ruu.extract_recruiter_id_from_url(
                "https://linkedin.com/talent/search/12345"
            )
            is None
        )


class TestIsRecruiterUrl:
    """Tests for is_recruiter_url function."""

    def test_true_for_recruiter_search_url(self):
        """Should return True for recruiterSearch URL."""
        assert ruu.is_recruiter_url(
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )

    def test_true_for_overview_url(self):
        """Should return True for overview URL."""
        assert ruu.is_recruiter_url("https://linkedin.com/talent/hire/123/overview")

    def test_true_for_slashless_url(self):
        """Should return True for URL without trailing slash."""
        assert ruu.is_recruiter_url("https://linkedin.com/talent/hire/12345")

    def test_false_for_regular_linkedin_url(self):
        """Should return False for regular LinkedIn URLs."""
        assert not ruu.is_recruiter_url("https://linkedin.com/in/profile")

    def test_false_for_random_string(self):
        """Should return False for random strings."""
        assert not ruu.is_recruiter_url("my_project_id")
        assert not ruu.is_recruiter_url("")


class TestIsContextualSearchUrl:
    """Tests for is_contextual_search_url function."""

    def test_bare_url_is_not_contextual(self):
        """Bare /discover/recruiterSearch URL without params is not contextual."""
        bare_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        assert ruu.is_contextual_search_url(bare_url) is False

    def test_url_with_search_context_id_is_contextual(self):
        """URL with searchContextId is contextual."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123"
        assert ruu.is_contextual_search_url(url) is True

    def test_url_with_search_history_id_is_contextual(self):
        """URL with searchHistoryId is contextual."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchHistoryId=def456"
        assert ruu.is_contextual_search_url(url) is True

    def test_url_with_search_request_id_is_contextual(self):
        """URL with searchRequestId is contextual."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchRequestId=ghi789"
        assert ruu.is_contextual_search_url(url) is True

    def test_url_with_project_id_is_contextual(self):
        """URL with projectId in query params is contextual."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?projectId=456"
        assert ruu.is_contextual_search_url(url) is True

    def test_url_with_multiple_context_params_is_contextual(self):
        """URL with multiple context params is contextual."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&searchHistoryId=def&start=25"
        assert ruu.is_contextual_search_url(url) is True

    def test_non_search_url_is_not_contextual(self):
        """Non-recruiterSearch URLs are not contextual."""
        url = "https://linkedin.com/talent/hire/123/overview"
        assert ruu.is_contextual_search_url(url) is False

    def test_with_project_id_validation(self):
        """Should validate project ID when provided."""
        # Same project ID - should be contextual
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        assert ruu.is_contextual_search_url(url, project_id="123") is True

        # Different project ID - should not be contextual
        url = "https://linkedin.com/talent/hire/456/discover/recruiterSearch?searchContextId=abc"
        assert ruu.is_contextual_search_url(url, project_id="123") is False

    def test_bare_url_with_project_id_validation(self):
        """Bare URL should fail even with matching project_id."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        assert ruu.is_contextual_search_url(url, project_id="123") is False


class TestIsLinkedinDomain:
    """Tests for is_linkedin_domain function."""

    def test_accepts_linkedin_com(self):
        """Should accept linkedin.com."""
        assert ruu.is_linkedin_domain("https://linkedin.com/talent/hire/123") is True

    def test_accepts_www_linkedin_com(self):
        """Should accept www.linkedin.com."""
        assert (
            ruu.is_linkedin_domain("https://www.linkedin.com/talent/hire/123") is True
        )

    def test_accepts_subdomains(self):
        """Should accept subdomains like talent.linkedin.com."""
        assert ruu.is_linkedin_domain("https://talent.linkedin.com/hire/123") is True

    def test_rejects_evil_domain(self):
        """Should reject evil.com even with matching path."""
        assert ruu.is_linkedin_domain("https://evil.com/talent/hire/123") is False

    def test_rejects_phishing_domain(self):
        """Should reject phishing domains like linkedin.evil.com."""
        assert (
            ruu.is_linkedin_domain("https://linkedin.evil.com/talent/hire/123") is False
        )

    def test_rejects_fake_linkedin_subdomain(self):
        """Should reject fake linkedin subdomains."""
        assert (
            ruu.is_linkedin_domain("https://fake-linkedin.com/talent/hire/123") is False
        )


class TestBuildProjectOverviewUrl:
    """Tests for build_project_overview_url function."""

    def test_builds_overview_url_from_project_id(self):
        """Should build correct overview URL from project ID."""
        result = ruu.build_project_overview_url("123456")
        assert result == "https://www.linkedin.com/talent/hire/123456/overview"

    def test_builds_url_with_different_project_id(self):
        """Should build URL with different project ID."""
        result = ruu.build_project_overview_url("999999")
        assert result == "https://www.linkedin.com/talent/hire/999999/overview"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
