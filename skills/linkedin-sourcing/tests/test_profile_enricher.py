#!/usr/bin/env python3
"""Tests for profile_enricher.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_profile_enricher.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import profile_enricher as pe


class TestEnrichmentResult:
    """Tests for EnrichmentResult dataclass."""

    def test_success_result(self):
        """Successful enrichment result."""
        result = pe.EnrichmentResult(
            success=True,
            enrichment_notes="Skills: Python, ML | Experience: 5y at Google",
            resume_hint="Enrichment complete - proceed to draft",
        )

        assert result.success is True
        assert result.phase == "enrich"
        assert (
            result.enrichment_notes == "Skills: Python, ML | Experience: 5y at Google"
        )
        assert result.failure_code is None
        assert result.action_required is None

    def test_failure_result(self):
        """Failed enrichment result with action_required."""
        action = {
            "code": "browser_not_found",
            "summary": "Chrome not accessible",
            "steps": ["Start Chrome with CDP", "Retry"],
            "can_retry": True,
            "context": {},
        }
        result = pe.EnrichmentResult(
            success=False,
            failure_code="browser_not_found",
            action_required=action,
            safe_to_retry=True,
            resume_hint="Start Chrome, then retry",
        )

        assert result.success is False
        assert result.failure_code == "browser_not_found"
        assert result.action_required == action
        assert result.safe_to_retry is True

    def test_to_dict(self):
        """Convert result to dictionary."""
        result = pe.EnrichmentResult(
            success=True,
            enrichment_notes="Test notes",
        )
        d = result.to_dict()

        assert d["success"] is True
        assert d["phase"] == "enrich"
        assert d["enrichment_notes"] == "Test notes"

    def test_from_dict(self):
        """Create result from dictionary."""
        data = {
            "success": False,
            "phase": "enrich",
            "failure_code": "timeout",
            "action_required": None,
            "safe_to_retry": True,
            "partial_result": None,
            "enrichment_notes": None,
            "resume_hint": "Retry later",
        }
        result = pe.EnrichmentResult.from_dict(data)

        assert result.success is False
        assert result.failure_code == "timeout"
        assert result.resume_hint == "Retry later"


class TestBuildActionRequired:
    """Tests for _build_action_required helper."""

    def test_basic_action(self):
        """Build basic action_required structure."""
        action = pe._build_action_required(
            code="test_error",
            summary="Something went wrong",
            steps=["Step 1", "Step 2"],
        )

        assert action["code"] == "test_error"
        assert action["summary"] == "Something went wrong"
        assert action["steps"] == ["Step 1", "Step 2"]
        assert action["can_retry"] is True
        assert action["context"] == {}

    def test_action_with_context(self):
        """Build action with context."""
        action = pe._build_action_required(
            code="element_missing",
            summary="Button not found",
            steps=["Check page"],
            context={"selector": "button.send", "url": "http://example.com"},
            can_retry=False,
        )

        assert action["context"]["selector"] == "button.send"
        assert action["can_retry"] is False

    def test_action_default_actor(self):
        """Build action with default actor=agent."""
        action = pe._build_action_required(
            code="test_error",
            summary="Something went wrong",
            steps=["Step 1"],
        )

        assert action["actor"] == "agent"

    def test_action_with_explicit_actor(self):
        """Build action with explicit actor override."""
        action = pe._build_action_required(
            code="auth_required",
            summary="Login required",
            steps=["Log in"],
            actor="user",
        )

        assert action["actor"] == "user"


class TestExtractCompactFacts:
    """Tests for _extract_compact_facts helper."""

    def test_skills_extraction(self):
        """Extract skills from page data."""
        page_data = {
            "skills": [
                "Python",
                "Machine Learning",
                "PyTorch",
                "CUDA",
                "Deep Learning",
            ],
        }
        result = pe._extract_compact_facts(page_data)

        assert "Skills:" in result
        assert "Python" in result
        assert "Machine Learning" in result

    def test_experience_extraction(self):
        """Extract experience from page data."""
        page_data = {
            "experience": [
                {"company": "Google", "duration": "3 years"},
                {"company": "Meta", "duration": "2 years"},
            ],
        }
        result = pe._extract_compact_facts(page_data)

        assert "Experience:" in result
        assert "Google" in result
        assert "Meta" in result

    def test_headline_included(self):
        """Include headline in facts."""
        page_data = {
            "headline": "Senior ML Engineer at Tech Co",
            "skills": [],
            "experience": [],
        }
        result = pe._extract_compact_facts(page_data)

        assert "Headline:" in result
        assert "Senior ML Engineer" in result

    def test_education_included(self):
        """Include education in facts."""
        page_data = {
            "education": [
                {"school": "Stanford University"},
                {"school": "MIT"},
            ],
            "skills": [],
            "experience": [],
        }
        result = pe._extract_compact_facts(page_data)

        assert "Education:" in result
        assert "Stanford" in result

    def test_combined_facts(self):
        """Combine multiple fact types."""
        page_data = {
            "skills": ["Python", "ML"],
            "experience": [{"company": "Google", "duration": "5 years"}],
            "headline": "Engineer",
        }
        result = pe._extract_compact_facts(page_data)

        assert "Skills:" in result
        assert "Experience:" in result
        assert "|" in result  # Separator between fact types

    def test_empty_data_fallback(self):
        """Fallback for empty data."""
        page_data = {}
        result = pe._extract_compact_facts(page_data)

        assert "Profile viewed" in result or result == ""

    def test_top_lines_fallback_extracts_visible_profile_context(self):
        """Fallback should use visible recruiter top-card lines when structured fields are empty."""
        page_data = {
            "name": "Upasana Wadhwa",
            "top_lines": [
                "Upasana Wadhwa",
                "Second degree connection",
                "\u00b7\u00a02nd",
                "Software Engineer at NetApp| Ex-Nutanix | NIT K Surathkal | Expertise in Machine Learning, Backend Development, Distributed Systems",
                "National Institute of Technology Karnataka \u00b7 San Jose, California, United States \u00b7 Software Development \u00b7 500+",
                "500+ connections",
                "Message Upasana",
                "Top Skills: Agentic Gen AI Containerization Kubernetes",
            ],
        }

        result = pe._extract_compact_facts(page_data)

        assert "Headline:" in result
        assert "Software Engineer at NetApp" in result
        assert "Top card:" in result
        assert "National Institute of Technology Karnataka" in result
        assert "Top Skills:" in result


class TestEnrichProfile:
    """Tests for enrich_profile function."""

    def test_empty_url_returns_failure(self):
        """Empty profile URL should return structured failure."""
        result = pe.enrich_profile("", use_browser=False)

        assert result.success is False
        assert result.failure_code == "invalid_input"
        assert result.action_required is not None
        assert result.safe_to_retry is False

    def test_mock_mode_success(self):
        """Mock mode should return simulated success."""
        result = pe.enrich_profile(
            "https://linkedin.com/in/test",
            use_browser=False,
        )

        assert result.success is True
        assert result.enrichment_notes is not None
        assert (
            "mock" in result.resume_hint.lower()
            or "complete" in result.resume_hint.lower()
        )


class TestEnrichViaBrowser:
    """Tests for _enrich_via_browser function with open+eval commands."""

    @patch("subprocess.run")
    def test_browser_open_success_eval_success(self, mock_run):
        """Successful open + eval returns enrichment notes."""
        # Mock successful open command
        open_result = MagicMock()
        open_result.returncode = 0
        open_result.stdout = ""
        open_result.stderr = ""

        # Mock successful eval command with profile data
        eval_result = MagicMock()
        eval_result.returncode = 0
        eval_result.stdout = json.dumps(
            {
                "skills": ["Python", "Machine Learning"],
                "experience": [{"company": "Google", "duration": "3 years"}],
                "education": [{"school": "Stanford"}],
                "headline": "Senior Engineer",
            }
        )
        eval_result.stderr = ""

        mock_run.side_effect = [open_result, eval_result]

        result = pe._enrich_via_browser("https://linkedin.com/in/test", "9234", 60)

        assert result.success is True
        assert result.enrichment_notes is not None
        assert "Skills:" in result.enrichment_notes

        # Verify correct commands were called
        calls = mock_run.call_args_list
        assert len(calls) == 2
        # First call should be 'open' command
        assert calls[0][0][0][3] == "open"
        # Second call should be 'eval' command
        assert calls[1][0][0][3] == "eval"

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_browser_retries_when_profile_is_still_loading(self, mock_run, mock_sleep):
        """Should retry eval when the profile page is still in a loading shell."""
        open_result = MagicMock(returncode=0, stdout="", stderr="")
        loading_eval = MagicMock(
            returncode=0,
            stdout=json.dumps({"headline": "Loading.", "top_lines": ["Loading."]}),
            stderr="",
        )
        empty_eval = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "headline": "",
                    "top_lines": [],
                    "skills": [],
                    "experience": [],
                    "education": [],
                }
            ),
            stderr="",
        )
        ready_eval = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "top_lines": [
                        "Upasana Wadhwa",
                        "Software Engineer at NetApp| Ex-Nutanix | NIT K Surathkal",
                        "National Institute of Technology Karnataka \u00b7 San Jose, California, United States \u00b7 Software Development \u00b7 500+",
                        "Top Skills: Agentic Gen AI Containerization Kubernetes",
                    ]
                }
            ),
            stderr="",
        )

        mock_run.side_effect = [open_result, loading_eval, empty_eval, ready_eval]

        result = pe._enrich_via_browser("https://linkedin.com/in/test", "9234", 60)

        assert result.success is True
        assert "Software Engineer at NetApp" in result.enrichment_notes
        assert mock_run.call_count == 4
        assert mock_sleep.call_count == 2

    @patch("subprocess.run")
    def test_browser_open_failure_auth_required(self, mock_run):
        """Auth error during open returns structured failure with auth_required code."""
        open_result = MagicMock()
        open_result.returncode = 1
        open_result.stdout = ""
        open_result.stderr = "Authentication required or login page detected"

        mock_run.return_value = open_result

        result = pe._enrich_via_browser("https://linkedin.com/in/test", "9234", 60)

        assert result.success is False
        assert result.failure_code == "auth_required"
        assert result.action_required is not None
        assert result.action_required["code"] == "auth_required"
        assert result.safe_to_retry is True

    @patch("subprocess.run")
    def test_browser_open_failure_navigation_failed(self, mock_run):
        """Navigation failure returns structured failure with navigation_failed code."""
        open_result = MagicMock()
        open_result.returncode = 1
        open_result.stdout = ""
        open_result.stderr = "Page load failed"

        mock_run.return_value = open_result

        result = pe._enrich_via_browser("https://linkedin.com/in/test", "9234", 60)

        assert result.success is False
        assert result.failure_code == "navigation_failed"
        assert result.action_required is not None
        assert result.action_required["code"] == "navigation_failed"

    @patch("subprocess.run")
    def test_browser_eval_parse_error(self, mock_run):
        """Non-JSON eval output returns extraction_parse_error."""
        open_result = MagicMock()
        open_result.returncode = 0
        open_result.stdout = ""
        open_result.stderr = ""

        eval_result = MagicMock()
        eval_result.returncode = 0
        eval_result.stdout = "not valid json"
        eval_result.stderr = ""

        mock_run.side_effect = [open_result, eval_result]

        result = pe._enrich_via_browser("https://linkedin.com/in/test", "9234", 60)

        assert result.success is False
        assert result.failure_code == "extraction_parse_error"

    @patch("subprocess.run")
    def test_browser_eval_failure_returns_extraction_failed(self, mock_run):
        """Eval command failure (returncode != 0) returns extraction_failed, not parse_error.

        This tests the fix for: returncode must be checked BEFORE parsing stdout,
        so JS/runtime failures are properly labeled as extraction_failed.
        """
        open_result = MagicMock()
        open_result.returncode = 0
        open_result.stdout = ""
        open_result.stderr = ""

        eval_result = MagicMock()
        eval_result.returncode = 1  # Command failed
        eval_result.stdout = (
            "some non-json error output"  # Would cause parse error if checked first
        )
        eval_result.stderr = "JavaScript runtime error: undefined is not a function"

        mock_run.side_effect = [open_result, eval_result]

        result = pe._enrich_via_browser("https://linkedin.com/in/test", "9234", 60)

        assert result.success is False
        assert result.failure_code == "extraction_failed"  # NOT extraction_parse_error
        assert "JavaScript runtime error" in result.action_required["context"]["error"]

    @patch("subprocess.run")
    def test_browser_agent_not_found(self, mock_run):
        """FileNotFoundError returns agent_browser_not_found."""
        mock_run.side_effect = FileNotFoundError("agent-browser not found")

        result = pe._enrich_via_browser("https://linkedin.com/in/test", "9234", 60)

        assert result.success is False
        assert result.failure_code == "agent_browser_not_found"
        assert result.safe_to_retry is False

    @patch("subprocess.run")
    def test_browser_timeout_during_open(self, mock_run):
        """Timeout during open returns navigation_timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 60)

        result = pe._enrich_via_browser("https://linkedin.com/in/test", "9234", 60)

        assert result.success is False
        assert result.failure_code == "navigation_timeout"
        assert result.safe_to_retry is True


class TestEnrichProfileBatch:
    """Tests for enrich_profile_batch function."""

    def test_batch_processes_all(self):
        """Batch should process all URLs."""
        urls = [
            "https://linkedin.com/in/user1",
            "https://linkedin.com/in/user2",
        ]
        results = pe.enrich_profile_batch(urls, use_browser=False)

        assert len(results) == 2
        assert all(r.success for r in results)

    def test_batch_continue_on_failure(self):
        """Batch should continue after individual failures."""
        # Mix of valid and invalid URLs
        urls = [
            "",  # Invalid - will fail
            "https://linkedin.com/in/valid",  # Valid
        ]
        results = pe.enrich_profile_batch(
            urls, use_browser=False, continue_on_failure=True
        )

        assert len(results) == 2
        assert results[0].success is False  # First one fails
        assert results[1].success is True  # Second one succeeds

    def test_batch_stop_on_failure(self):
        """Batch should stop on failure when continue_on_failure=False."""
        urls = [
            "",  # Invalid - will fail
            "https://linkedin.com/in/valid",  # Won't be processed
        ]
        results = pe.enrich_profile_batch(
            urls, use_browser=False, continue_on_failure=False
        )

        assert len(results) == 2
        assert results[0].success is False
        # Second result should be batch_aborted
        assert results[1].failure_code == "batch_aborted"


if __name__ == "__main__":
    try:
        import pytest

        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not available, running basic smoke tests...")
        # Run basic tests
        test_class = TestEnrichmentResult()
        test_class.test_success_result()
        test_class.test_failure_result()
        print("Basic tests passed")
