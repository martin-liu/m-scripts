#!/usr/bin/env python3
"""Tests for run_create_search.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import auth_bootstrap
import run_create_search as rcs


@pytest.fixture(autouse=True)
def block_real_browser_bootstrap(monkeypatch):
    """Fail fast if a unit test tries to launch a real browser bootstrap."""

    def _unexpected_bootstrap(*args, **kwargs):
        raise AssertionError(
            "Unexpected real browser bootstrap in test_run_create_search.py; "
            "mock auth_bootstrap.bootstrap_auth_session or run_create_search._ensure_browser_ready"
        )

    monkeypatch.setattr(auth_bootstrap, "bootstrap_auth_session", _unexpected_bootstrap)


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
    def test_brief_only_returns_search_brief(self, mock_resolve, mock_ctx, tmp_path):
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

        result = rcs.run_create_search_phase("proj-1", brief_only=True)

        assert result["success"] is True
        assert result["status"] == "brief_only"
        assert result["phase"] == "create_search"
        assert result["next_phase"] == "create_search"
        assert result["cdp_port"] == "9230"
        assert "Engineer" in result["search_brief"]

    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_returns_ready_when_candidates_already_visible(
        self, mock_resolve, mock_ctx, mock_ensure_ready, mock_inspect, tmp_path
    ):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        mock_ensure_ready.return_value = ("9230", None)  # Browser ready
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
        assert result["next_phase"] == "confirm_search"
        assert "awaiting confirmation" in result["message"]

    @patch("run_create_search.create_initial_search_with_copilot")
    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_attempts_copilot_when_search_not_configured(
        self, mock_resolve, mock_ctx, mock_ensure_ready, mock_inspect, mock_copilot, tmp_path
    ):
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
        mock_ensure_ready.return_value = ("9230", None)  # Browser ready
        mock_inspect.return_value = {
            "success": False,
            "status": "search_not_configured",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "failure_code": "search_not_configured",
            "action_required": None,
        }
        mock_copilot.return_value = {
            "success": False,
            "status": "copilot_widget_missing",
            "failure_code": "ELEMENT_MISSING",
            "action_required": {
                "code": "ELEMENT_MISSING",
                "summary": "Copilot widget not found",
            },
        }

        result = rcs.run_create_search_phase("proj-1")

        # Should have attempted Copilot
        mock_copilot.assert_called_once()
        assert result["success"] is False
        assert result["phase"] == "create_search"
        assert "copilot" in result["status"] or result["status"] == "copilot_widget_missing"

    @patch("run_create_search.create_initial_search_with_copilot")
    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_attempts_copilot_when_search_unverified(
        self, mock_resolve, mock_ctx, mock_ensure_ready, mock_inspect, mock_copilot, tmp_path
    ):
        """Copilot should also be attempted when status is 'unverified' (widget still loading)."""
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
        mock_ensure_ready.return_value = ("9230", None)
        mock_inspect.return_value = {
            "success": False,
            "status": "unverified",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "failure_code": "search_not_configured",
            "action_required": None,
        }
        mock_copilot.return_value = {
            "success": False,
            "status": "copilot_timeout",
            "failure_code": "TIMEOUT",
            "action_required": {
                "code": "TIMEOUT",
                "summary": "Copilot timed out",
            },
        }

        result = rcs.run_create_search_phase("proj-1")

        mock_copilot.assert_called_once()
        assert result["success"] is False
        assert "copilot" in result["status"] or result["status"] == "copilot_timeout"

    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_raises_config_error_when_recruiter_url_missing(
        self, mock_resolve, mock_ctx, mock_ensure_ready, tmp_path
    ):
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (config_path, {"PROJECT_ID": "proj-1"}, "123")
        mock_ensure_ready.return_value = ("9230", None)  # Browser ready

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
            "9230", "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
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
            "9230", "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
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
            "9230", "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
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
            "9230", "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
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
            "9230",
            "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch",
        )

        # Should NOT be ready when on wrong project
        assert result["success"] is False
        assert result["status"] == "wrong_project"
        assert result["failure_code"] == "wrong_page"
        assert "1691575116" in result["current_url"]
        assert result["action_required"] is not None

    @patch("browser_utils.classify_browser_readiness")
    @patch("browser_utils.run_browser_command")
    def test_enriches_browser_unavailable_with_recovery_details(
        self, mock_run_browser, mock_classify
    ):
        """REGRESSION: inspect_search_state should enrich browser_unavailable blockers.

        Issue: inspect_search_state() was forwarding browser-unavailable blockers from
        classify_browser_readiness() unchanged, but those blockers lacked recovery details
        like work_dir, chrome_profile, connect_browser.sh path, and exact recovery command.
        """
        mock_run_browser.return_value = {"error": "connection refused"}
        mock_readiness = MagicMock()
        mock_readiness.action_required = MagicMock()
        mock_readiness.action_required.code = "browser_unavailable"
        # Return a minimal blocker without recovery details (simulating the old behavior)
        mock_readiness.action_required.to_dict.return_value = {
            "code": "browser_unavailable",
            "summary": "Browser not available",
            "steps": ["Start Chrome"],
            "context": {"cdp_port": "9230"},  # Missing recovery_command
            "actor": "agent",
        }
        mock_classify.return_value = mock_readiness

        result = rcs.inspect_search_state(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=Path("/tmp/test"),
        )

        assert result["failure_code"] == "browser_unavailable"
        action_required = result["action_required"]
        # Should be enriched with recovery details
        assert "work_dir" in action_required["context"]
        assert "chrome_profile" in action_required["context"]
        assert "connect_browser_script" in action_required["context"]
        assert "recovery_command" in action_required["context"]
        assert "agent_browser_command" in action_required["context"]
        # Recovery command should be runnable
        assert "bash" in action_required["context"]["recovery_command"]
        assert "connect_browser.sh" in action_required["context"]["recovery_command"]

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("browser_utils.run_browser_command")
    def test_enriches_browser_unavailable_from_ensure_page_ready(
        self, mock_run_browser, mock_ensure_ready
    ):
        """REGRESSION: ensure_page_ready browser_unavailable should be enriched."""
        mock_run_browser.return_value = {"error": None}
        # Simulate ensure_page_ready returning browser_unavailable
        mock_ensure_ready.return_value = {
            "ready": False,
            "state": "browser_unavailable",
            "failure_code": "browser_unavailable",
            "action_required": {
                "code": "browser_unavailable",
                "summary": "Browser disconnected",
                "steps": ["Check Chrome"],
                "context": {},  # Missing recovery details
                "actor": "agent",
            },
        }

        result = rcs.inspect_search_state(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=Path("/tmp/test"),
        )

        assert result["failure_code"] == "browser_unavailable"
        action_required = result["action_required"]
        # Should be enriched with recovery details
        assert "recovery_command" in action_required["context"]
        assert "connect_browser.sh" in action_required["context"]["recovery_command"]


class TestEnsureBrowserReady:
    """Tests for the proactive browser bootstrap helper."""

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_returns_port_when_browser_ready(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """Should return port with no blocker when browser is ready."""
        mock_check_available.return_value = True
        mock_probe.return_value = {"authenticated": True}

        ctx = {"work_dir": "/tmp/test", "profile": {"CDP_PORT": "9230"}}
        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        assert port == "9230"
        assert blocker is None
        mock_bootstrap.assert_not_called()

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_attempts_bootstrap_when_browser_unavailable(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """Should attempt bootstrap when browser is not available."""
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {
            "success": True,
            "cdp_port": "9230",
            "message": "Bootstrap succeeded",
        }

        ctx = {"work_dir": "/tmp/test", "profile": {"CDP_PORT": "9230"}}
        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        assert port == "9230"
        assert blocker is None
        mock_bootstrap.assert_called_once()

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_returns_rich_blocker_when_bootstrap_fails(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """Should return structured blocker with recovery details when bootstrap fails."""
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {
            "success": False,
            "error": "Chrome not found",
        }

        ctx = {"work_dir": "/tmp/test", "profile": {"CDP_PORT": "9230"}}
        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        assert port == "9230"
        assert blocker is not None
        assert blocker["code"] == "browser_unavailable"
        assert "work_dir" in blocker["context"]
        assert "cdp_port" in blocker["context"]
        assert "chrome_profile" in blocker["context"]
        assert "recovery_command" in blocker["context"]
        assert "agent_browser_command" in blocker["context"]
        assert any("connect_browser.sh" in step for step in blocker["steps"])

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_blocker_includes_exact_recovery_command(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """Blocker should include exact runnable recovery command."""
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {"success": False, "error": "Failed"}

        ctx = {"work_dir": "/tmp/test", "profile": {"CDP_PORT": "9230"}}
        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        recovery_cmd = blocker["context"]["recovery_command"]
        assert "bash" in recovery_cmd
        assert "connect_browser.sh" in recovery_cmd
        # Should be copy-paste runnable
        assert recovery_cmd.startswith('bash "')

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_preserves_auth_required_actor_on_auth_failure(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """REGRESSION: Auth failures should preserve user actor, not convert to agent.

        Issue: _ensure_browser_ready() was converting all bootstrap failures into
        browser_unavailable/agent blockers, even when the failure was actually
        auth/login related after Chrome was up.
        """
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {
            "success": False,
            "error": "Authentication timeout after 300 seconds",
        }

        ctx = {"work_dir": "/tmp/test", "profile": {"CDP_PORT": "9230"}}
        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        # Should be auth_required, not browser_unavailable
        assert blocker["code"] == "auth_required"
        # Should be user blocker, not agent
        assert blocker["actor"] == "user"
        # Should include bootstrap error context
        assert "bootstrap_error" in blocker["context"]

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_returns_browser_unavailable_for_chrome_launch_failure(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """Chrome launch failures should return browser_unavailable, not auth_required."""
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {
            "success": False,
            "error": "Could not find system Chrome installation",
        }

        ctx = {"work_dir": "/tmp/test", "profile": {"CDP_PORT": "9230"}}
        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        # Should be browser_unavailable for Chrome not found
        assert blocker["code"] == "browser_unavailable"
        # Should be agent blocker
        assert blocker["actor"] == "agent"

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_no_skill_dir_fallback_when_work_dir_missing(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """REGRESSION: Missing ctx['work_dir'] must not derive skill-dir path.

        Issue: _ensure_browser_ready was using SCRIPT_DIR.parent.parent as fallback,
        which resolves to the skill directory. This test proves that when work_dir
        is missing from context, the function uses canonical default (Desktop/linkedin-sourcing)
        instead of skill-dir-derived paths.
        """
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {"success": False, "error": "Failed"}

        # Context WITHOUT work_dir - should use canonical default, not skill dir
        ctx = {"profile": {"CDP_PORT": "9230"}}  # No work_dir key
        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        # Verify the work_dir in blocker is NOT skill-dir-derived
        work_dir_in_blocker = blocker["context"]["work_dir"]
        assert "skills/linkedin-sourcing" not in work_dir_in_blocker, (
            f"work_dir contains skill dir path: {work_dir_in_blocker}"
        )
        assert "/scripts" not in work_dir_in_blocker, (
            f"work_dir contains scripts path: {work_dir_in_blocker}"
        )
        # Should use canonical default location
        assert (
            "Desktop" in work_dir_in_blocker
            or "linkedin-sourcing" in work_dir_in_blocker
        ), f"work_dir should be canonical default, got: {work_dir_in_blocker}"

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_no_skill_dir_fallback_when_work_dir_empty_string(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """REGRESSION: Empty work_dir string must not derive skill-dir path."""
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {"success": False, "error": "Failed"}

        # Context with empty work_dir - should use canonical default
        ctx = {"work_dir": "", "profile": {"CDP_PORT": "9230"}}
        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        # Verify the work_dir in blocker is NOT skill-dir-derived
        work_dir_in_blocker = blocker["context"]["work_dir"]
        assert "skills/linkedin-sourcing" not in work_dir_in_blocker
        assert "/scripts" not in work_dir_in_blocker

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_bootstrap_expands_work_dir_variable_in_chrome_profile(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """Bootstrap should receive CHROME_PROFILE with $WORK_DIR expanded."""
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {
            "success": True,
            "cdp_port": "9230",
        }

        ctx = {
            "work_dir": "/tmp/runtime-work",
            "profile": {
                "CDP_PORT": "9230",
                "CHROME_PROFILE": "$WORK_DIR/custom-profile",
            },
        }

        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        assert port == "9230"
        assert blocker is None
        assert mock_bootstrap.call_args.kwargs["chrome_profile"] == Path(
            "/tmp/runtime-work/custom-profile"
        )

    @patch("auth_bootstrap.bootstrap_auth_session")
    @patch("browser_utils.check_browser_available")
    @patch("browser_utils.probe_recruiter_auth")
    def test_bootstrap_expands_brace_work_dir_variable_in_chrome_profile(
        self, mock_probe, mock_check_available, mock_bootstrap
    ):
        """Bootstrap should receive CHROME_PROFILE with ${WORK_DIR} expanded."""
        mock_check_available.return_value = False
        mock_bootstrap.return_value = {
            "success": True,
            "cdp_port": "9230",
        }

        ctx = {
            "work_dir": "/tmp/runtime-work",
            "profile": {
                "CDP_PORT": "9230",
                "CHROME_PROFILE": "${WORK_DIR}/custom-profile",
            },
        }

        port, blocker = rcs._ensure_browser_ready(ctx, "9230")

        assert port == "9230"
        assert blocker is None
        assert mock_bootstrap.call_args.kwargs["chrome_profile"] == Path(
            "/tmp/runtime-work/custom-profile"
        )


class TestRunCreateSearchPhaseBrowserBootstrap:
    """Tests for browser bootstrap integration in run_create_search_phase."""

    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_skips_bootstrap_in_brief_only_mode(
        self, mock_resolve, mock_ctx, mock_ensure_ready, tmp_path
    ):
        """brief_only mode should not attempt browser bootstrap."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
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

        result = rcs.run_create_search_phase("proj-1", brief_only=True)

        assert result["success"] is True
        assert result["status"] == "brief_only"
        mock_ensure_ready.assert_not_called()

    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_proactively_bootstrap_in_normal_mode(
        self, mock_resolve, mock_ctx, mock_ensure_ready, mock_inspect, tmp_path
    ):
        """Normal mode should proactively ensure browser is ready."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        mock_ensure_ready.return_value = ("9230", None)  # Browser ready
        mock_inspect.return_value = {
            "success": True,
            "status": "ready",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "failure_code": None,
        }

        result = rcs.run_create_search_phase("proj-1")

        assert result["success"] is True
        mock_ensure_ready.assert_called_once()

    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_returns_blocker_immediately_when_browser_unavailable(
        self, mock_resolve, mock_ctx, mock_ensure_ready, tmp_path
    ):
        """Should return blocker immediately if browser cannot be made ready."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        blocker = {
            "code": "browser_unavailable",
            "summary": "Chrome browser is not available",
            "context": {
                "work_dir": "/tmp/test",
                "cdp_port": "9230",
                "recovery_command": 'bash "/path/to/connect_browser.sh"',
            },
        }
        mock_ensure_ready.return_value = ("9230", blocker)

        result = rcs.run_create_search_phase("proj-1")

        assert result["success"] is False
        assert result["status"] == "browser_unavailable"
        assert result["action_required"] == blocker
        assert result["next_phase"] == "create_search"


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


class TestFilterInspectionHelpers:
    """Tests for filter inspection and analysis helpers."""

    def test_detect_malformed_title_chips_finds_concatenated_titles(self):
        """Should detect concatenated title chips like 'Platform EngineerInfrastructure Engineer'."""
        title_chips = [
            "CDN Engineer",
            "Platform Engineer",
            "Platform EngineerInfrastructure Engineer",
            "Platform EngineerInfrastructure EngineerCloud Engineer",
            "Software Engineer",
        ]

        malformed = rcs._detect_malformed_title_chips(title_chips)

        assert "Platform EngineerInfrastructure Engineer" in malformed
        assert "Platform EngineerInfrastructure EngineerCloud Engineer" in malformed
        assert "CDN Engineer" not in malformed
        assert "Platform Engineer" not in malformed
        assert "Software Engineer" not in malformed

    def test_detect_malformed_title_chips_returns_empty_for_valid_titles(self):
        """Should return empty list when all titles are properly formatted."""
        title_chips = [
            "CDN Engineer",
            "Platform Engineer",
            "Software Engineer",
            "Senior Backend Developer",
        ]

        malformed = rcs._detect_malformed_title_chips(title_chips)

        assert malformed == []

    def test_analyze_filter_state_detects_missing_companies(self):
        """Should detect when expected companies from config are missing from filter."""
        config = {
            "COMPANIES": "Google, Meta, Amazon",
            "POSITION_TITLE": "Software Engineer",
        }
        company_chips = ["Google", "Meta"]  # Amazon is missing
        title_chips = ["Software Engineer"]

        analysis = rcs._analyze_filter_state(config, company_chips, title_chips)

        assert "amazon" in analysis["missing_companies"]
        assert len(analysis["issues"]) > 0
        assert any("missing" in issue.lower() for issue in analysis["issues"])

    def test_analyze_filter_state_detects_malformed_titles(self):
        """Should detect malformed title chips."""
        config = {
            "COMPANIES": "Google",
            "POSITION_TITLE": "Platform Engineer",
        }
        company_chips = ["Google"]
        title_chips = [
            "Platform Engineer",
            "Platform EngineerInfrastructure Engineer",  # Malformed
        ]

        analysis = rcs._analyze_filter_state(config, company_chips, title_chips)

        assert len(analysis["malformed_titles"]) > 0
        assert (
            "Platform EngineerInfrastructure Engineer" in analysis["malformed_titles"]
        )
        assert len(analysis["issues"]) > 0
        assert any("malformed" in issue.lower() for issue in analysis["issues"])

    def test_analyze_filter_state_no_issues_when_all_good(self):
        """Should report no issues when filters match config."""
        config = {
            "COMPANIES": "Google, Meta",
            "POSITION_TITLE": "Software Engineer",
        }
        company_chips = ["Google", "Meta"]
        title_chips = ["Software Engineer"]

        analysis = rcs._analyze_filter_state(config, company_chips, title_chips)

        assert analysis["missing_companies"] == []
        assert analysis["malformed_titles"] == []
        assert analysis["issues"] == []

    def test_analyze_filter_state_handles_empty_config(self):
        """Should handle empty config gracefully."""
        config = {}
        company_chips = ["Some Company"]
        title_chips = ["Some Title"]

        analysis = rcs._analyze_filter_state(config, company_chips, title_chips)

        assert analysis["expected_companies"] == []
        assert analysis["missing_companies"] == []

    def test_analyze_uses_effective_companies_excluding_hiring_company(self):
        """Should use effective target companies, excluding hiring company for TikTok JDs."""
        config = {
            "COMPANIES": "TikTok, ByteDance, Google, Meta",
        }
        company_chips = [
            "Google",
            "Meta",
        ]  # TikTok and ByteDance not expected for TikTok JD
        title_chips = []
        jd_text = "Join us at TikTok!"
        jd_url = "https://lifeattiktok.com/jobs"

        analysis = rcs._analyze_filter_state(
            config, company_chips, title_chips, jd_text, jd_url
        )

        # Should NOT report TikTok/ByteDance as missing since they're excluded for TikTok JDs
        assert "tiktok" not in analysis["missing_companies"]
        assert "bytedance" not in analysis["missing_companies"]
        # Google and Meta should be in expected companies
        assert "google" in analysis["expected_companies"]
        assert "meta" in analysis["expected_companies"]
        # Should have no issues since Google and Meta are present
        assert analysis["issues"] == []

    def test_analyze_reports_missing_non_hiring_companies_for_tiktok_jd(self):
        """Should still report missing companies that are not the hiring company for TikTok JDs."""
        config = {
            "COMPANIES": "TikTok, Google, Meta, Amazon",
        }
        company_chips = ["Google"]  # Meta and Amazon missing, TikTok excluded
        title_chips = []
        jd_url = "https://tiktok.com/careers"

        analysis = rcs._analyze_filter_state(
            config, company_chips, title_chips, jd_url=jd_url
        )

        # Should report Meta and Amazon as missing (not TikTok)
        assert "meta" in analysis["missing_companies"]
        assert "amazon" in analysis["missing_companies"]
        assert "tiktok" not in analysis["missing_companies"]
        assert len(analysis["issues"]) > 0

    def test_normalize_chip_text_handles_whitespace(self):
        """Should normalize chip text by removing extra whitespace."""
        assert rcs._normalize_chip_text("  Google  ") == "Google"
        assert rcs._normalize_chip_text("Google\n\nMeta") == "Google Meta"
        assert rcs._normalize_chip_text("  Multiple   Spaces  ") == "Multiple Spaces"


class TestFilterReconciliation:
    """Tests for filter reconciliation helpers."""

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._add_company_filters")
    def test_reconcile_adds_missing_companies(
        self, mock_add_companies, mock_click_button
    ):
        """Reconciliation should attempt to add missing companies."""
        mock_click_button.return_value = True
        mock_add_companies.return_value = {"added": ["Amazon"], "failed": []}

        config = {"COMPANIES": "Google, Meta, Amazon"}
        current_analysis = {
            "missing_companies": ["amazon"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)

        assert result["attempted"] is True
        mock_click_button.assert_called_once_with("9230", "companies")
        mock_add_companies.assert_called_once_with("9230", ["amazon"])
        assert result["companies_added"] == ["Amazon"]
        assert result["companies_failed"] == []

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._remove_malformed_title_chips")
    def test_reconcile_removes_malformed_titles(
        self, mock_remove_titles, mock_click_button
    ):
        """Reconciliation should attempt to remove malformed title chips."""
        mock_click_button.return_value = True
        mock_remove_titles.return_value = {"removed": ["EngineerManager"], "failed": []}

        config = {"COMPANIES": "Google"}
        current_analysis = {
            "missing_companies": [],
            "malformed_titles": ["EngineerManager"],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)

        assert result["attempted"] is True
        mock_click_button.assert_called_once_with("9230", "titles")
        mock_remove_titles.assert_called_once_with("9230", ["EngineerManager"])
        assert result["titles_removed"] == ["EngineerManager"]
        assert result["titles_failed"] == []

    @patch("run_create_search._click_filter_button")
    def test_reconcile_skips_when_no_issues(self, mock_click_button):
        """Reconciliation should not attempt anything when there are no issues."""
        config = {"COMPANIES": "Google, Meta"}
        current_analysis = {
            "missing_companies": [],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)

    @patch("run_create_search._click_filter_button")
    def test_reconcile_records_failed_companies(self, mock_click_button):
        """Reconciliation should record companies that failed to add."""
        mock_click_button.return_value = False  # Could not open filter

        config = {"COMPANIES": "Google, Meta, Amazon"}
        current_analysis = {
            "missing_companies": ["amazon"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)

        assert result["attempted"] is True
        assert result["companies_failed"] == ["amazon"]
        assert "Could not open Companies filter" in result["errors"]

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._add_company_filters")
    def test_reconcile_handles_partial_company_add(
        self, mock_add_companies, mock_click_button
    ):
        """Reconciliation should handle partial success when adding companies."""
        mock_click_button.return_value = True
        mock_add_companies.return_value = {"added": ["Amazon"], "failed": ["Netflix"]}

        config = {"COMPANIES": "Google, Meta, Amazon, Netflix"}
        current_analysis = {
            "missing_companies": ["amazon", "netflix"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        assert result["attempted"] is True
        assert "Amazon" in result["companies_added"]
        assert "Netflix" in result["companies_failed"]


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
            "9230",
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
            "9230",
            "https://linkedin.com/talent/hire/1692252652/discover/recruiterSearch",
        )

        # Should NOT be wrong_page
        assert result["status"] == "search_not_configured"
        assert result.get("failure_code") != "wrong_page"


class TestChromeProfilePathRegression:
    """REGRESSION TESTS: CHROME_PROFILE and WORK_DIR path resolution.

    Issue: _enrich_browser_unavailable_blocker() was falling back to
    SCRIPT_DIR.parent.parent for work_dir and hardcoding chrome_profile path,
    ignoring the configured CHROME_PROFILE from profile/runtime context.

    Additionally, run_create_search_phase passed project_dir.parent (the projects
    directory) instead of the actual runtime WORK_DIR.
    """

    def test_enrich_uses_provided_chrome_profile_from_runtime(self):
        """REGRESSION: Configured CHROME_PROFILE from runtime context must be preserved."""
        action_required = {
            "code": "browser_unavailable",
            "summary": "Browser not available",
            "steps": ["Start Chrome"],
            "context": {"cdp_port": "9230"},
            "actor": "agent",
        }

        # Simulate runtime context with custom CHROME_PROFILE
        custom_work_dir = Path("/custom/work/dir")
        custom_chrome_profile = Path("/custom/chrome/profile")

        result = rcs._enrich_browser_unavailable_blocker(
            action_required, "9230", custom_work_dir, custom_chrome_profile
        )

        # Must use the provided chrome_profile from runtime, not a derived path
        assert result["context"]["chrome_profile"] == str(custom_chrome_profile)
        assert result["context"]["work_dir"] == str(custom_work_dir)

    def test_enrich_defaults_chrome_profile_to_work_dir_subdir(self):
        """Default CHROME_PROFILE should resolve from provided WORK_DIR, not skill dir."""
        action_required = {
            "code": "browser_unavailable",
            "summary": "Browser not available",
            "steps": ["Start Chrome"],
            "context": {"cdp_port": "9230"},
            "actor": "agent",
        }

        custom_work_dir = Path("/my/work/dir")

        # Call without providing chrome_profile - should default to $WORK_DIR/chrome-profile
        result = rcs._enrich_browser_unavailable_blocker(
            action_required, "9230", custom_work_dir, None
        )

        # Default should be based on provided work_dir
        expected_profile = custom_work_dir / "chrome-profile"
        assert result["context"]["chrome_profile"] == str(expected_profile)
        assert result["context"]["work_dir"] == str(custom_work_dir)

    def test_enrich_never_uses_script_dir_parent_fallback(self):
        """REGRESSION: _enrich_browser_unavailable_blocker must never use SCRIPT_DIR.parent.parent."""
        action_required = {
            "code": "browser_unavailable",
            "summary": "Browser not available",
            "steps": ["Start Chrome"],
            "context": {"cdp_port": "9230"},
            "actor": "agent",
        }

        # Even when work_dir is None, should use a sensible default (not skill dir)
        result = rcs._enrich_browser_unavailable_blocker(
            action_required, "9230", None, None
        )

        # Should NOT contain "skills/linkedin-sourcing" or SCRIPT_DIR-derived paths
        assert "skills/linkedin-sourcing" not in result["context"]["work_dir"]
        assert "scripts" not in result["context"]["work_dir"]
        # Should use the default work_dir location
        assert "linkedin-sourcing" in result["context"]["work_dir"]

    @patch("browser_utils.classify_browser_readiness")
    @patch("browser_utils.run_browser_command")
    def test_inspect_search_state_passes_chrome_profile_to_enrich(
        self, mock_run_browser, mock_classify
    ):
        """inspect_search_state should pass chrome_profile through to enrichment."""
        mock_run_browser.return_value = {"error": "connection refused"}
        mock_readiness = MagicMock()
        mock_readiness.action_required = MagicMock()
        mock_readiness.action_required.code = "browser_unavailable"
        mock_readiness.action_required.to_dict.return_value = {
            "code": "browser_unavailable",
            "context": {"cdp_port": "9230"},
        }
        mock_classify.return_value = mock_readiness

        custom_work_dir = Path("/runtime/work/dir")
        custom_chrome_profile = Path("/runtime/chrome-profile")

        result = rcs.inspect_search_state(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=custom_work_dir,
            chrome_profile=custom_chrome_profile,
        )

        # Should preserve the provided chrome_profile in the enriched blocker
        assert result["action_required"]["context"]["chrome_profile"] == str(
            custom_chrome_profile
        )
        assert result["action_required"]["context"]["work_dir"] == str(custom_work_dir)

    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_run_create_search_uses_runtime_work_dir_not_projects_dir(
        self, mock_resolve, mock_ctx, mock_ensure_ready, mock_inspect, tmp_path
    ):
        """REGRESSION: run_create_search_phase must use runtime WORK_DIR, not project_dir.parent.

        Issue: The code was passing work_dir=project_dir.parent which resolves to
        $WORK_DIR/projects instead of the actual $WORK_DIR.
        """
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")

        # Runtime context with specific work_dir and chrome_profile
        runtime_work_dir = Path("/my/runtime/work/dir")
        runtime_chrome_profile = "/my/runtime/chrome-profile"
        mock_ctx.return_value = {
            "work_dir": str(runtime_work_dir),
            "profile": {
                "CDP_PORT": "9230",
                "CHROME_PROFILE": runtime_chrome_profile,
            },
        }
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        mock_ensure_ready.return_value = ("9230", None)
        mock_inspect.return_value = {
            "success": False,
            "status": "search_not_configured",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "failure_code": "search_not_configured",
            "action_required": None,
        }

        result = rcs.run_create_search_phase("proj-1")

        # Verify inspect_search_state was called with runtime work_dir, not project_dir.parent
        mock_inspect.assert_called_once()
        call_kwargs = mock_inspect.call_args.kwargs

        # work_dir should be the runtime work_dir, not the projects directory
        assert "work_dir" in call_kwargs
        actual_work_dir = call_kwargs["work_dir"]
        assert actual_work_dir == runtime_work_dir, (
            f"Expected work_dir={runtime_work_dir}, got {actual_work_dir}"
        )

        # chrome_profile should be passed from runtime context
        assert call_kwargs.get("chrome_profile") == runtime_chrome_profile

    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_no_skill_dir_paths_in_recovery_context(
        self, mock_resolve, mock_ctx, mock_ensure_ready, mock_inspect, tmp_path
    ):
        """REGRESSION: Recovery context must never contain skill-dir-derived paths."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")

        runtime_work_dir = Path("/clean/work/dir")
        mock_ctx.return_value = {
            "work_dir": str(runtime_work_dir),
            "profile": {"CDP_PORT": "9230"},
        }
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        mock_ensure_ready.return_value = ("9230", None)

        # Simulate browser_unavailable response from inspect_search_state
        mock_inspect.return_value = {
            "success": False,
            "status": "browser_unavailable",
            "failure_code": "browser_unavailable",
            "action_required": {
                "code": "browser_unavailable",
                "context": {
                    "work_dir": str(runtime_work_dir),
                    "chrome_profile": str(runtime_work_dir / "chrome-profile"),
                },
            },
        }

        result = rcs.run_create_search_phase("proj-1")

        # Verify no skill directory paths in the result
        action_required = result.get("action_required", {})
        context = action_required.get("context", {})

        work_dir_in_context = context.get("work_dir", "")
        chrome_profile_in_context = context.get("chrome_profile", "")

        # Must NOT contain skill directory paths
        assert "skills/linkedin-sourcing" not in work_dir_in_context, (
            f"work_dir contains skill dir path: {work_dir_in_context}"
        )
        assert "skills/linkedin-sourcing" not in chrome_profile_in_context, (
            f"chrome_profile contains skill dir path: {chrome_profile_in_context}"
        )
        assert "/scripts" not in work_dir_in_context, (
            f"work_dir contains scripts path: {work_dir_in_context}"
        )

    def test_enrich_expands_work_dir_variable_in_chrome_profile(self):
        """REGRESSION: CHROME_PROFILE with $WORK_DIR must be fully resolved in blocker context.

        Issue: _enrich_browser_unavailable_blocker() was accepting chrome_profile from
        runtime/profile context but not expanding $WORK_DIR/${WORK_DIR} variables,
        while _ensure_browser_ready() does. This caused inspection-time blockers to
        emit literal paths like "$WORK_DIR/custom-profile" instead of resolved paths.
        """
        action_required = {
            "code": "browser_unavailable",
            "summary": "Browser not available",
            "steps": ["Start Chrome"],
            "context": {"cdp_port": "9230"},
            "actor": "agent",
        }

        runtime_work_dir = Path("/my/runtime/work/dir")
        # Runtime/profile provides CHROME_PROFILE with $WORK_DIR variable
        runtime_chrome_profile = "$WORK_DIR/custom-profile"

        result = rcs._enrich_browser_unavailable_blocker(
            action_required, "9230", runtime_work_dir, runtime_chrome_profile
        )

        # Must resolve $WORK_DIR to the actual path
        expected_resolved_profile = str(runtime_work_dir / "custom-profile")
        actual_profile = result["context"]["chrome_profile"]

        assert "$WORK_DIR" not in actual_profile, (
            f"chrome_profile still contains unresolved $WORK_DIR: {actual_profile}"
        )
        assert actual_profile == expected_resolved_profile, (
            f"Expected {expected_resolved_profile}, got {actual_profile}"
        )

    def test_enrich_expands_brace_work_dir_variable_in_chrome_profile(self):
        """REGRESSION: CHROME_PROFILE with ${WORK_DIR} brace syntax must be resolved."""
        action_required = {
            "code": "browser_unavailable",
            "summary": "Browser not available",
            "steps": ["Start Chrome"],
            "context": {"cdp_port": "9230"},
            "actor": "agent",
        }

        runtime_work_dir = Path("/my/runtime/work/dir")
        # Runtime/profile provides CHROME_PROFILE with ${WORK_DIR} brace syntax
        runtime_chrome_profile = "${WORK_DIR}/custom-profile"

        result = rcs._enrich_browser_unavailable_blocker(
            action_required, "9230", runtime_work_dir, runtime_chrome_profile
        )

        # Must resolve ${WORK_DIR} to the actual path
        expected_resolved_profile = str(runtime_work_dir / "custom-profile")
        actual_profile = result["context"]["chrome_profile"]

        assert "${WORK_DIR}" not in actual_profile, (
            f"chrome_profile still contains unresolved ${{WORK_DIR}}: {actual_profile}"
        )
        assert actual_profile == expected_resolved_profile, (
            f"Expected {expected_resolved_profile}, got {actual_profile}"
        )

    def test_enrich_expands_tilde_in_chrome_profile(self):
        """REGRESSION: CHROME_PROFILE with ~ must be expanded via expanduser()."""
        action_required = {
            "code": "browser_unavailable",
            "summary": "Browser not available",
            "steps": ["Start Chrome"],
            "context": {"cdp_port": "9230"},
            "actor": "agent",
        }

        runtime_work_dir = Path("/my/runtime/work/dir")
        # Profile path with tilde
        runtime_chrome_profile = "~/my-chrome-profile"

        result = rcs._enrich_browser_unavailable_blocker(
            action_required, "9230", runtime_work_dir, runtime_chrome_profile
        )

        actual_profile = result["context"]["chrome_profile"]

        # Tilde should be expanded to home directory
        assert not actual_profile.startswith("~/"), (
            f"chrome_profile still contains unexpanded tilde: {actual_profile}"
        )
        assert actual_profile.endswith("/my-chrome-profile"), (
            f"chrome_profile should end with /my-chrome-profile: {actual_profile}"
        )


class TestFacetSpecificChipExtraction:
    """Tests for facet-specific chip extraction from Recruiter DOM."""

    @patch("browser_utils.run_browser_command")
    def test_extracts_companies_from_facet_wrapper(self, mock_run_browser):
        """Should extract companies from .search-facet-wrapper.facet-companies using Remove buttons."""
        # Simulate DOM with companies in the facet wrapper
        mock_run_browser.return_value = {
            "parsed": {
                "companies": ["Google", "Meta"],
                "titles": [],
            }
        }

        result = rcs._extract_filter_chips_from_page("9230")

        assert "Google" in result["companies"]
        assert "Meta" in result["companies"]
        # Verify the JS targets facet-specific selectors
        js_code = mock_run_browser.call_args[0][2]
        assert "facet-companies" in js_code
        assert 'button[aria-label^="Remove"]' in js_code

    @patch("browser_utils.run_browser_command")
    def test_extracts_titles_from_facet_wrapper(self, mock_run_browser):
        """Should extract titles from .search-facet-wrapper.facet-titles using Remove buttons."""
        mock_run_browser.return_value = {
            "parsed": {
                "companies": [],
                "titles": ["Software Engineer", "Senior Developer"],
            }
        }

        result = rcs._extract_filter_chips_from_page("9230")

        assert "Software Engineer" in result["titles"]
        assert "Senior Developer" in result["titles"]
        js_code = mock_run_browser.call_args[0][2]
        assert "facet-titles" in js_code or "facet-title" in js_code

    @patch("browser_utils.run_browser_command")
    def test_extracts_chips_from_remove_button_aria_labels(self, mock_run_browser):
        """Should parse chip names from 'Remove <chip>' aria-label pattern."""
        mock_run_browser.return_value = {
            "parsed": {
                "companies": ["Google DeepMind", "Salesforce"],
                "titles": ["Platform Engineer"],
            }
        }

        result = rcs._extract_filter_chips_from_page("9230")

        # Multi-word company names should be extracted correctly
        assert "Google DeepMind" in result["companies"]
        assert "Salesforce" in result["companies"]
        assert "Platform Engineer" in result["titles"]

    @patch("browser_utils.run_browser_command")
    def test_returns_empty_on_extraction_failure(self, mock_run_browser):
        """Should return empty lists when browser command fails."""
        mock_run_browser.side_effect = Exception("Connection failed")

        result = rcs._extract_filter_chips_from_page("9230")

        assert result["companies"] == []
        assert result["titles"] == []


class TestCompanyAddExactMatch:
    """Tests for company add helper with exact match logic."""

    @staticmethod
    def _snapshot_output(*option_lines: str) -> dict[str, str]:
        return {"stdout": "\n".join(option_lines), "error": None}

    @patch("browser_utils.run_browser_command")
    def test_adds_company_with_exact_match(self, mock_run_browser):
        """Should use snapshot + explicit click on exact match option for reliable selection."""
        # Sequence: focus success -> keyboard inserttext -> snapshot with ref -> click @ref -> verify success
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "Google"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Google" [ref=e123]'),
            {"error": None},  # Click @e123 (explicit click on exact match)
            {"parsed": {"success": True, "verified": True, "chip": "Google"}},  # Verify
        ]

        result = rcs._add_company_filters("9230", ["Google"])

        assert "Google" in result["added"]
        assert result["failed"] == []

        # Verify keyboard inserttext was used (not just input.value)
        keyboard_call = mock_run_browser.call_args_list[1]
        assert keyboard_call[0][1] == "keyboard"
        assert keyboard_call[0][2] == "inserttext"
        assert keyboard_call[0][3] == "Google"

        # Verify explicit click on the exact match option via ref
        click_call = mock_run_browser.call_args_list[3]
        assert click_call[0][1] == "click", (
            f"Expected 'click' command, got {click_call[0][1]}"
        )
        assert click_call[0][2] == "@e123", (
            f"Expected '@e123' ref, got {click_call[0][2]}"
        )

        # Verify the snapshot command is scoped to the Companies facet
        snapshot_call = mock_run_browser.call_args_list[2]
        assert snapshot_call[0][1:5] == (
            "snapshot",
            "-i",
            "-s",
            ".search-facet-wrapper.facet-companies",
        )

    @patch("browser_utils.run_browser_command")
    def test_fails_when_no_exact_match(self, mock_run_browser):
        """Should fail company when no exact match in suggestions (no click attempted)."""
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "NonExistentCorp"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output(
                '- option "Google" [ref=e1]',
                '- option "Meta" [ref=e2]',
                '- option "Amazon" [ref=e3]',
            ),
        ]

        result = rcs._add_company_filters("9230", ["NonExistentCorp"])

        assert "NonExistentCorp" in result["failed"]
        assert result["added"] == []
        # Should NOT have clicked since no exact match was found
        # Only 3 calls: focus, inserttext, snapshot
        assert mock_run_browser.call_count == 3

    @patch("browser_utils.run_browser_command")
    def test_handles_case_insensitive_exact_match(self, mock_run_browser):
        """Should match company case-insensitively and click exact match."""
        mock_run_browser.side_effect = [
            {
                "parsed": {"success": True, "company": "google"}
            },  # Focus (lowercase input)
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Google" [ref=e456]'),
            {"error": None},  # Click @e456
            {"parsed": {"success": True, "verified": True}},  # Verify
        ]

        result = rcs._add_company_filters("9230", ["google"])

        assert "google" in result["added"]

    @patch("browser_utils.run_browser_command")
    def test_matches_add_to_list_option_when_exact_label_not_present(
        self, mock_run_browser
    ):
        """Should click Recruiter's add-to-list option for the target company."""
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "Amazon"}},
            {"error": None},
            self._snapshot_output(
                '- option " , Add Amazon to list of filters" [ref=e654]'
            ),
            {"error": None},
            {"parsed": {"success": True, "verified": True, "chip": "Amazon"}},
        ]

        result = rcs._add_company_filters("9230", ["Amazon"])

        assert result["added"] == ["Amazon"]
        assert result["failed"] == []
        click_call = mock_run_browser.call_args_list[3]
        assert click_call[0][1:3] == ("click", "@e654")

    @patch("browser_utils.run_browser_command")
    def test_opens_closed_facet_before_adding(self, mock_run_browser):
        """Should click facet button to open if initially closed."""
        mock_run_browser.side_effect = [
            {
                "parsed": {"success": False, "reason": "facet_closed", "retry": True}
            },  # First attempt - closed
            {"parsed": {"success": True, "company": "Meta"}},  # Retry - success
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Meta" [ref=e789]'),
            {"error": None},  # Click @e789
            {"parsed": {"success": True, "verified": True}},  # Verify
        ]

        result = rcs._add_company_filters("9230", ["Meta"])

        assert "Meta" in result["added"]
        assert (
            mock_run_browser.call_count == 6
        )  # Initial + retry + keyboard + snapshot + click + verify

    @patch("browser_utils.run_browser_command")
    def test_handles_multiple_companies_mixed_results(self, mock_run_browser):
        """Should handle mix of successful and failed company adds."""
        # Google succeeds, NonExistent fails
        mock_run_browser.side_effect = [
            # Google
            {"parsed": {"success": True, "company": "Google"}},
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Google" [ref=e111]'),
            {"error": None},  # Click @e111
            {"parsed": {"success": True, "verified": True}},  # Verify
            # NonExistentCorp
            {"parsed": {"success": True, "company": "NonExistentCorp"}},
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Google" [ref=e1]'),
        ]

        result = rcs._add_company_filters("9230", ["Google", "NonExistentCorp"])

        assert "Google" in result["added"]
        assert "NonExistentCorp" in result["failed"]

    @patch("browser_utils.run_browser_command")
    def test_verification_failure_reports_as_failed_not_added(self, mock_run_browser):
        """REGRESSION: Company should be in failed list if verification fails after click.

        Issue: _add_company_filters() was counting companies as 'added' even when
        post-click verification failed, leading to false success reporting.
        """
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "Airbnb"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Airbnb" [ref=e222]'),
            {"error": None},  # Click @e222
            {
                "parsed": {"success": False, "reason": "chip_not_found_after_add"}
            },  # Verify FAILS
        ]

        result = rcs._add_company_filters("9230", ["Airbnb"])

        # Should be in failed, NOT in added
        assert "Airbnb" in result["failed"], (
            "Company with failed verification should be in failed list"
        )
        assert "Airbnb" not in result["added"], (
            "Company with failed verification should NOT be in added list"
        )

    @patch("browser_utils.run_browser_command")
    def test_uses_explicit_click_on_exact_match_option(self, mock_run_browser):
        """Should use explicit click on exact match option instead of synthetic DOM click or Enter press.

        Synthetic DOM clicks (element.click() in JS eval) are not reliable for
        React-controlled inputs. Pressing Enter is unsafe when multiple suggestions
        exist - the wrong option might be selected.

        The correct approach: capture scoped snapshot, find exact match ref, click @ref directly.
        """
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "Amazon"}},  # Focus
            {"error": None},  # Keyboard inserttext success
            self._snapshot_output('- option "Amazon" [ref=e333]'),
            {"error": None},  # Click @e333 (explicit click on exact match)
            {"parsed": {"success": True, "verified": True}},  # Verify
        ]

        result = rcs._add_company_filters("9230", ["Amazon"])

        assert "Amazon" in result["added"]

        # Verify the sequence uses explicit click on the exact match option
        calls = mock_run_browser.call_args_list
        # Call 3 should be: run_browser_command(cdp_port, "click", "@e333")
        click_call = calls[3]
        assert click_call[0][1] == "click", (
            f"Expected 'click' command, got {click_call[0][1]}"
        )
        assert click_call[0][2] == "@e333", (
            f"Expected '@e333' ref, got {click_call[0][2]}"
        )
        # Should be exactly 3 args (cdp_port, "click", "@ref")
        assert len(click_call[0]) == 3, (
            f"Expected 3 args (cdp, 'click', '@ref'), got {len(click_call[0])}: {click_call[0]}"
        )

    @patch("browser_utils.run_browser_command")
    def test_falls_back_to_keyboard_type_if_inserttext_fails(self, mock_run_browser):
        """Should fallback to keyboard type if inserttext fails."""
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "Netflix"}},  # Focus
            {"error": "inserttext not supported"},  # Keyboard inserttext fails
            {"error": None},  # Keyboard type succeeds
            self._snapshot_output('- option "Netflix" [ref=e444]'),
            {"error": None},  # Click @e444
            {"parsed": {"success": True, "verified": True}},  # Verify
        ]

        result = rcs._add_company_filters("9230", ["Netflix"])

        assert "Netflix" in result["added"]

        # Verify both keyboard commands were attempted
        calls = mock_run_browser.call_args_list
        assert calls[1][0][1:3] == ("keyboard", "inserttext")
        assert calls[2][0][1:3] == ("keyboard", "type")
        # Verify click uses correct format
        assert calls[4][0][1] == "click" and calls[4][0][2] == "@e444"

    @patch("browser_utils.run_browser_command")
    def test_typed_text_without_chip_does_not_count_as_added(self, mock_run_browser):
        """REGRESSION: Typed text or suggestion text without a real chip must NOT count as added.

        Issue: The verification fallback checked wrapper.textContent.includes(targetLower),
        which caused typed text or suggestion text to count as successful add even when
        no chip was actually added. Only real chip evidence (Remove button) should count.
        """
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "FakeCorp"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "FakeCorp" [ref=e555]'),
            {"error": None},  # Click @e555
            # Verify returns failure - no Remove button found (no text_check fallback)
            {"parsed": {"success": False, "reason": "chip_not_found_after_add"}},
        ]

        result = rcs._add_company_filters("9230", ["FakeCorp"])

        # Should be in failed, NOT in added - no false positive from text content
        assert "FakeCorp" in result["failed"], (
            "Company without real chip evidence should be in failed list"
        )
        assert "FakeCorp" not in result["added"], (
            "Company without real chip evidence should NOT be in added list"
        )

    @patch("browser_utils.run_browser_command")
    def test_suggestion_text_without_click_does_not_count_as_added(
        self, mock_run_browser
    ):
        """REGRESSION: Suggestion text visible in dropdown must NOT count as added without click.

        Issue: If suggestion text appeared in the dropdown but the click failed or the
        option was not actually selected, the old text_check fallback would still count
        it as added. Only a real chip with Remove button evidence should count.
        """
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "Google"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Google" [ref=e666]'),
            {"error": None},  # Click @e666
            # Verify returns failure - no Remove button (chip not actually added)
            {"parsed": {"success": False, "reason": "chip_not_found_after_add"}},
        ]

        result = rcs._add_company_filters("9230", ["Google"])

        # Even for a real company name, if no chip was added it should fail
        assert "Google" in result["failed"]
        assert "Google" not in result["added"]

    @patch("browser_utils.run_browser_command")
    def test_click_failure_reports_as_failed(self, mock_run_browser):
        """Should report company as failed if explicit click fails."""
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "Uber"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Uber" [ref=e777]'),
            {"error": "Click failed"},  # Click @e777 FAILS
        ]

        result = rcs._add_company_filters("9230", ["Uber"])

        assert "Uber" in result["failed"]
        assert "Uber" not in result["added"]

    @patch("browser_utils.run_browser_command")
    def test_explicit_click_when_different_option_highlighted(self, mock_run_browser):
        """REGRESSION: Must click exact match option even when different option is highlighted.

        Issue: When multiple suggestions exist, pressing Enter would select the currently
        highlighted option, which may not be the exact match we want. The implementation
        must explicitly click the exact match option by ref, not rely on Enter press.

        Scenario: User types "Google", suggestions show ["Google", "Google Cloud", "Google DeepMind"],
        but "Google Cloud" is currently highlighted. Pressing Enter would select the wrong company.
        The fix: explicitly click the "Google" option by its ref.
        """
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "company": "Google"}},  # Focus
            {"error": None},  # Keyboard inserttext
            # Snapshot finds exact match "Google" with ref e123
            # (even if a different option like "Google Cloud" is highlighted)
            self._snapshot_output(
                '- option "Google Cloud" [ref=e999]',
                '- option "Google" [ref=e123]',
                '- option "Google DeepMind" [ref=e124]',
            ),
            {
                "error": None
            },  # Explicit click @e123 (the exact match, not highlighted one)
            {"parsed": {"success": True, "verified": True, "chip": "Google"}},  # Verify
        ]

        result = rcs._add_company_filters("9230", ["Google"])

        assert "Google" in result["added"]
        assert result["failed"] == []

        # Verify we clicked the exact match option by ref, not just pressed Enter
        calls = mock_run_browser.call_args_list
        click_call = calls[3]
        assert click_call[0][1] == "click"
        assert click_call[0][2] == "@e123"
        # CRITICAL: Should NOT use "press" command which would select highlighted option
        assert "press" not in [c[0][1] for c in calls if len(c[0]) >= 2], (
            "Should NOT use 'press' command - must explicitly click exact match option"
        )


class TestReconciliationSummaryReporting:
    """Tests for reconciliation summary with added/failed companies."""

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._add_company_filters")
    def test_summary_reports_added_companies(
        self, mock_add_companies, mock_click_button
    ):
        """Reconciliation summary should list successfully added companies."""
        mock_click_button.return_value = True
        mock_add_companies.return_value = {"added": ["Amazon", "Netflix"], "failed": []}

        config = {"COMPANIES": "Google, Meta, Amazon, Netflix"}
        current_analysis = {
            "missing_companies": ["amazon", "netflix"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        assert result["attempted"] is True
        assert result["companies_added"] == ["Amazon", "Netflix"]
        assert result["companies_failed"] == []

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._add_company_filters")
    def test_summary_reports_failed_companies(
        self, mock_add_companies, mock_click_button
    ):
        """Reconciliation summary should list companies that failed to add."""
        mock_click_button.return_value = True
        mock_add_companies.return_value = {"added": [], "failed": ["UnknownStartup"]}

        config = {"COMPANIES": "Google, UnknownStartup"}
        current_analysis = {
            "missing_companies": ["unknownstartup"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        assert result["companies_failed"] == ["UnknownStartup"]
        assert "UnknownStartup" in result["companies_failed"]

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._add_company_filters")
    def test_summary_reports_partial_success(
        self, mock_add_companies, mock_click_button
    ):
        """Reconciliation summary should handle partial success correctly."""
        mock_click_button.return_value = True
        mock_add_companies.return_value = {
            "added": ["Amazon"],
            "failed": ["NonExistentCorp"],
        }

        config = {"COMPANIES": "Google, Amazon, NonExistentCorp"}
        current_analysis = {
            "missing_companies": ["amazon", "nonexistentcorp"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        assert "Amazon" in result["companies_added"]
        assert "NonExistentCorp" in result["companies_failed"]
        assert result["attempted"] is True

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._add_company_filters")
    def test_summary_does_not_claim_unverified_companies(
        self, mock_add_companies, mock_click_button
    ):
        """REGRESSION: Summary must not claim auto-added companies that failed verification.

        Issue: When _add_company_filters reported companies in 'added' that were not
        actually verified on the page, the summary would falsely claim they were added.
        With truthful accounting, only verified companies appear in companies_added.
        """
        mock_click_button.return_value = True
        # All companies failed verification (truthful accounting)
        mock_add_companies.return_value = {
            "added": [],
            "failed": ["airbnb", "akamai", "amazon", "anthropic", "apple"],
        }

        config = {"COMPANIES": "airbnb, akamai, amazon, anthropic, apple, google"}
        current_analysis = {
            "missing_companies": ["airbnb", "akamai", "amazon", "anthropic", "apple"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        # Should report empty added list when verification fails for all
        assert result["companies_added"] == [], (
            "Should not claim companies that failed verification"
        )
        assert len(result["companies_failed"]) == 5, (
            "All failed companies should be recorded"
        )
        assert "airbnb" in result["companies_failed"]
        assert "amazon" in result["companies_failed"]


class TestSharedFacetHelpers:
    """Tests for shared facet-driven helpers."""

    def test_normalize_facet_option_text_removes_non_alphanumeric(self):
        """Shared normalizer should remove non-alphanumeric characters."""
        assert rcs._normalize_facet_option_text("Google Inc.") == "googleinc"
        assert rcs._normalize_facet_option_text("C++") == "c"
        assert rcs._normalize_facet_option_text("AWS / GCP") == "awsgcp"

    def test_normalize_facet_option_text_lowercases(self):
        """Shared normalizer should lowercase text."""
        assert rcs._normalize_facet_option_text("Google") == "google"
        assert rcs._normalize_facet_option_text("PyTorch") == "pytorch"

    def test_normalize_company_option_text_is_alias(self):
        """Company normalizer should be alias to shared normalizer."""
        # Both should produce same results
        company_result = rcs._normalize_company_option_text("Google Inc.")
        facet_result = rcs._normalize_facet_option_text("Google Inc.")
        assert company_result == facet_result

    def test_normalize_keyword_option_text_is_alias(self):
        """Keyword normalizer should be alias to shared normalizer."""
        keyword_result = rcs._normalize_keyword_option_text("C++")
        facet_result = rcs._normalize_facet_option_text("C++")
        assert keyword_result == facet_result

    @patch("run_create_search._find_facet_option_ref")
    def test_find_company_option_ref_uses_shared_helper(self, mock_find_facet):
        """Company finder should delegate to shared facet helper."""
        mock_find_facet.return_value = {
            "success": True,
            "matched": "Google",
            "ref": "e123",
        }

        result = rcs._find_company_option_ref("9230", "Google")

        mock_find_facet.assert_called_once_with(
            "9230", "Google", ".search-facet-wrapper.facet-companies"
        )
        assert result["success"] is True

    @patch("run_create_search._find_facet_option_ref")
    def test_find_keyword_option_ref_uses_shared_helper(self, mock_find_facet):
        """Keyword finder should delegate to shared facet helper."""
        mock_find_facet.return_value = {
            "success": True,
            "matched": "Python",
            "ref": "e456",
        }

        result = rcs._find_keyword_option_ref("9230", "Python")

        mock_find_facet.assert_called_once_with(
            "9230",
            "Python",
            ".search-facet-wrapper.facet-skills, .search-facet-wrapper.facet-skill",
        )
        assert result["success"] is True

    @patch("run_create_search._add_facet_filters")
    def test_add_company_filters_uses_shared_helper(self, mock_add_facet):
        """Company add should delegate to shared facet helper."""
        mock_add_facet.return_value = {"added": ["Google"], "failed": []}

        result = rcs._add_company_filters("9230", ["Google"])

        mock_add_facet.assert_called_once()
        call_args = mock_add_facet.call_args[0]
        assert call_args[0] == "9230"
        assert call_args[1] == ["Google"]
        assert "facet-companies" in call_args[2]
        assert result["added"] == ["Google"]

    @patch("run_create_search._add_facet_filters")
    def test_add_keyword_filters_uses_shared_helper(self, mock_add_facet):
        """Keyword add should delegate to shared facet helper."""
        mock_add_facet.return_value = {"added": ["Python"], "failed": []}

        result = rcs._add_keyword_filters("9230", ["Python"])

        mock_add_facet.assert_called_once()
        call_args = mock_add_facet.call_args[0]
        assert call_args[0] == "9230"
        assert call_args[1] == ["Python"]
        assert "facet-skills" in call_args[2]
        assert result["added"] == ["Python"]


class TestKeywordFilterHelpers:
    """Tests for keyword filter extraction and addition helpers."""

    @patch("browser_utils.run_browser_command")
    def test_extracts_keywords_from_skills_facet_wrapper(self, mock_run_browser):
        """Should extract keywords from .search-facet-wrapper.facet-skills using Remove buttons."""
        mock_run_browser.return_value = {
            "parsed": {
                "companies": [],
                "titles": [],
                "keywords": ["Kubernetes", "Python", "AWS"],
            }
        }

        result = rcs._extract_filter_chips_from_page("9230")

        assert "Kubernetes" in result["keywords"]
        assert "Python" in result["keywords"]
        assert "AWS" in result["keywords"]
        # Verify the JS targets facet-specific selectors
        js_code = mock_run_browser.call_args[0][2]
        assert "facet-skills" in js_code or "facet-skill" in js_code
        assert 'button[aria-label^="Remove"]' in js_code

    @patch("browser_utils.run_browser_command")
    def test_extracts_keywords_from_facet_skill_wrapper(self, mock_run_browser):
        """Should extract keywords from .search-facet-wrapper.facet-skill (singular) as fallback."""
        mock_run_browser.return_value = {
            "parsed": {
                "companies": [],
                "titles": [],
                "keywords": ["Docker", "Terraform"],
            }
        }

        result = rcs._extract_filter_chips_from_page("9230")

        assert "Docker" in result["keywords"]
        assert "Terraform" in result["keywords"]

    def test_analyze_filter_state_detects_missing_keywords(self):
        """Should detect when expected keywords from config are missing from filter."""
        config = {
            "KEYWORDS": "Kubernetes, Python, AWS",
            "POSITION_TITLE": "Platform Engineer",
        }
        company_chips = []
        title_chips = ["Platform Engineer"]
        keyword_chips = ["Kubernetes"]  # Python and AWS missing

        analysis = rcs._analyze_filter_state(
            config, company_chips, title_chips, keyword_chips
        )

        assert "python" in analysis["missing_keywords"]
        assert "aws" in analysis["missing_keywords"]
        assert "kubernetes" not in analysis["missing_keywords"]
        assert any(
            "missing" in issue.lower() and "keyword" in issue.lower()
            for issue in analysis["issues"]
        )

    def test_analyze_filter_state_no_keyword_issues_when_all_present(self):
        """Should report no keyword issues when all expected keywords are present."""
        config = {
            "KEYWORDS": "Kubernetes, Python",
            "POSITION_TITLE": "Engineer",
        }
        company_chips = []
        title_chips = []
        keyword_chips = ["Kubernetes", "Python"]

        analysis = rcs._analyze_filter_state(
            config, company_chips, title_chips, keyword_chips
        )

        assert analysis["missing_keywords"] == []
        assert not any("keyword" in issue.lower() for issue in analysis["issues"])

    def test_analyze_filter_state_handles_empty_keywords_config(self):
        """Should handle empty KEYWORDS config gracefully."""
        config = {
            "POSITION_TITLE": "Engineer",
        }
        company_chips = []
        title_chips = []
        keyword_chips = []

        analysis = rcs._analyze_filter_state(
            config, company_chips, title_chips, keyword_chips
        )

        assert analysis["expected_keywords"] == []
        assert analysis["observed_keywords"] == []
        assert analysis["missing_keywords"] == []

    @staticmethod
    def _snapshot_output(*option_lines: str) -> dict[str, str]:
        return {"stdout": "\n".join(option_lines), "error": None}

    @patch("browser_utils.run_browser_command")
    def test_adds_keyword_with_exact_match(self, mock_run_browser):
        """Should use snapshot + explicit click on exact match option for reliable keyword selection."""
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "keyword": "Kubernetes"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "Kubernetes" [ref=e123]'),
            {"error": None},  # Click @e123
            {
                "parsed": {"success": True, "verified": True, "chip": "Kubernetes"}
            },  # Verify
        ]

        result = rcs._add_keyword_filters("9230", ["Kubernetes"])

        assert "Kubernetes" in result["added"]
        assert result["failed"] == []

        # Verify keyboard inserttext was used
        keyboard_call = mock_run_browser.call_args_list[1]
        assert keyboard_call[0][1] == "keyboard"
        assert keyboard_call[0][2] == "inserttext"

        # Verify explicit click on the exact match option via ref
        click_call = mock_run_browser.call_args_list[3]
        assert click_call[0][1] == "click"
        assert click_call[0][2] == "@e123"

    @patch("browser_utils.run_browser_command")
    def test_keyword_fails_when_no_exact_match(self, mock_run_browser):
        """Should fail keyword when no exact match in suggestions."""
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "keyword": "NonExistentSkill"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output(
                '- option "Python" [ref=e1]',
                '- option "Java" [ref=e2]',
            ),
        ]

        result = rcs._add_keyword_filters("9230", ["NonExistentSkill"])

        assert "NonExistentSkill" in result["failed"]
        assert result["added"] == []

    @patch("browser_utils.run_browser_command")
    def test_keyword_matches_add_to_list_option(self, mock_run_browser):
        """Should click Recruiter's add-to-list option for the target keyword."""
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "keyword": "Docker"}},
            {"error": None},
            self._snapshot_output(
                '- option " , Add Docker to list of filters" [ref=e654]'
            ),
            {"error": None},
            {"parsed": {"success": True, "verified": True, "chip": "Docker"}},
        ]

        result = rcs._add_keyword_filters("9230", ["Docker"])

        assert result["added"] == ["Docker"]
        assert result["failed"] == []

    @patch("browser_utils.run_browser_command")
    def test_keyword_verification_failure_reports_as_failed(self, mock_run_browser):
        """Keyword should be in failed list if verification fails after click."""
        mock_run_browser.side_effect = [
            {"parsed": {"success": True, "keyword": "AWS"}},  # Focus
            {"error": None},  # Keyboard inserttext
            self._snapshot_output('- option "AWS" [ref=e222]'),
            {"error": None},  # Click @e222
            {
                "parsed": {"success": False, "reason": "chip_not_found_after_add"}
            },  # Verify FAILS
        ]

        result = rcs._add_keyword_filters("9230", ["AWS"])

        assert "AWS" in result["failed"]
        assert "AWS" not in result["added"]

    @patch("browser_utils.run_browser_command")
    def test_handles_multiple_keywords_mixed_results(self, mock_run_browser):
        """Should handle mix of successful and failed keyword adds."""
        mock_run_browser.side_effect = [
            # Kubernetes succeeds
            {"parsed": {"success": True, "keyword": "Kubernetes"}},
            {"error": None},
            self._snapshot_output('- option "Kubernetes" [ref=e111]'),
            {"error": None},
            {"parsed": {"success": True, "verified": True}},
            # NonExistent fails
            {"parsed": {"success": True, "keyword": "NonExistent"}},
            {"error": None},
            self._snapshot_output('- option "Python" [ref=e1]'),
        ]

        result = rcs._add_keyword_filters("9230", ["Kubernetes", "NonExistent"])

        assert "Kubernetes" in result["added"]
        assert "NonExistent" in result["failed"]


class TestKeywordReconciliation:
    """Tests for keyword reconciliation in filter state."""

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._add_keyword_filters")
    def test_reconcile_adds_missing_keywords(
        self, mock_add_keywords, mock_click_button
    ):
        """Reconciliation should attempt to add missing keywords."""
        mock_click_button.return_value = True
        mock_add_keywords.return_value = {"added": ["Python", "AWS"], "failed": []}

        config = {"KEYWORDS": "Kubernetes, Python, AWS"}
        current_analysis = {
            "missing_companies": [],
            "missing_keywords": ["python", "aws"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        assert result["attempted"] is True
        mock_click_button.assert_called_once_with("9230", "skills")
        mock_add_keywords.assert_called_once_with("9230", ["python", "aws"])
        assert result["keywords_added"] == ["Python", "AWS"]
        assert result["keywords_failed"] == []

    @patch("run_create_search._click_filter_button")
    @patch("run_create_search._add_keyword_filters")
    def test_reconcile_records_failed_keywords(
        self, mock_add_keywords, mock_click_button
    ):
        """Reconciliation should record keywords that failed to add."""
        mock_click_button.return_value = True
        mock_add_keywords.return_value = {"added": [], "failed": ["RareSkill"]}

        config = {"KEYWORDS": "Python, RareSkill"}
        current_analysis = {
            "missing_companies": [],
            "missing_keywords": ["rareskill"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        assert result["keywords_failed"] == ["RareSkill"]
        assert "RareSkill" in result["keywords_failed"]

    @patch("run_create_search._click_filter_button")
    def test_reconcile_skips_keywords_when_no_missing(self, mock_click_button):
        """Reconciliation should not attempt keyword add when no keywords missing."""
        config = {"KEYWORDS": "Python, AWS"}
        current_analysis = {
            "missing_companies": [],
            "missing_keywords": [],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        assert result["attempted"] is False
        mock_click_button.assert_not_called()

    @patch("run_create_search._click_filter_button")
    def test_reconcile_records_failed_keywords_when_filter_closed(
        self, mock_click_button
    ):
        """Reconciliation should record keywords as failed when cannot open filter."""
        mock_click_button.return_value = False  # Could not open filter

        config = {"KEYWORDS": "Python, Kubernetes"}
        current_analysis = {
            "missing_companies": [],
            "missing_keywords": ["kubernetes"],
            "malformed_titles": [],
        }

        result = rcs._reconcile_filter_state("9230", current_analysis)
        assert result["attempted"] is True
        assert result["keywords_failed"] == ["kubernetes"]
        assert "Could not open Skills filter" in result["errors"]


class TestReconciliationDefensiveGuard:
    """Tests for defensive guard that aligns reconciliation summary with observed state."""

    @patch("run_create_search._extract_filter_chips_from_page")
    @patch("run_create_search._reconcile_filter_state")
    @patch("run_create_search._analyze_filter_state")
    @patch("run_create_search._click_filter_button")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("browser_utils.run_browser_command")
    def test_defensive_guard_moves_falsely_claimed_to_failed(
        self,
        mock_run_browser,
        mock_probe_class,
        mock_ensure_ready,
        mock_click_button,
        mock_analyze,
        mock_reconcile,
        mock_extract_chips,
    ):
        """REGRESSION: Companies claimed as added but not observed must move to failed.

        Issue: After reconciliation re-extract/re-analyze, companies_added might contain
        companies that are not actually present in the final observed_companies. The
        defensive guard should detect this mismatch and move them to companies_failed.
        """
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_run_browser.side_effect = [
            {"error": None},
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
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

        # First analysis: missing companies detected
        mock_analyze.side_effect = [
            {
                "expected_companies": ["google", "meta", "amazon"],
                "observed_companies": ["google"],  # meta and amazon missing
                "missing_companies": ["meta", "amazon"],
                "malformed_titles": [],
                "issues": ["Missing expected companies: meta, amazon"],
            },
            # After reconciliation re-analysis: only meta was actually added
            {
                "expected_companies": ["google", "meta", "amazon"],
                "observed_companies": ["google", "meta"],  # amazon still missing
                "missing_companies": ["amazon"],
                "malformed_titles": [],
                "issues": ["Missing expected companies: amazon"],
            },
        ]

        # Reconciliation claims both were added (but amazon was not actually added)
        mock_reconcile.return_value = {
            "attempted": True,
            "companies_added": ["Meta", "Amazon"],  # False claim for Amazon
            "companies_failed": [],
            "titles_removed": [],
            "titles_failed": [],
            "errors": [],
        }

        # Filter chips after reconciliation (only meta actually added)
        mock_extract_chips.return_value = {
            "companies": ["Google", "Meta"],  # Amazon NOT actually present
            "titles": [],
        }

        config = {"COMPANIES": "Google, Meta, Amazon"}

        result = rcs.inspect_search_state(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            config=config,
        )

        # The reconciliation result should have been corrected by defensive guard
        reconciliation = result.get("reconciliation", {})
        # Amazon should be moved to failed since it's not in observed_companies
        assert "Amazon" not in reconciliation.get("companies_added", []), (
            "Amazon should not be in companies_added since it was not observed"
        )
        assert "Amazon" in reconciliation.get("companies_failed", []), (
            "Amazon should be in companies_failed since it was claimed but not observed"
        )
        assert "Meta" in reconciliation.get("companies_added", []), (
            "Meta should remain in companies_added since it was observed"
        )

    @patch("run_create_search._extract_filter_chips_from_page")
    @patch("run_create_search._reconcile_filter_state")
    @patch("run_create_search._analyze_filter_state")
    @patch("run_create_search._click_filter_button")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("browser_utils.run_browser_command")
    def test_defensive_guard_preserves_actually_added_companies(
        self,
        mock_run_browser,
        mock_probe_class,
        mock_ensure_ready,
        mock_click_button,
        mock_analyze,
        mock_reconcile,
        mock_extract_chips,
    ):
        """Defensive guard should preserve companies that are actually observed."""
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_run_browser.side_effect = [
            {"error": None},
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
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

        mock_analyze.side_effect = [
            {
                "expected_companies": ["google", "meta"],
                "observed_companies": ["google"],
                "missing_companies": ["meta"],
                "malformed_titles": [],
                "issues": [],
            },
            {
                "expected_companies": ["google", "meta"],
                "observed_companies": ["google", "meta"],  # meta now present
                "missing_companies": [],
                "malformed_titles": [],
                "issues": [],
            },
        ]

        mock_reconcile.return_value = {
            "attempted": True,
            "companies_added": ["Meta"],
            "companies_failed": [],
        }

        mock_extract_chips.return_value = {
            "companies": ["Google", "Meta"],
            "titles": [],
        }

        config = {"COMPANIES": "Google, Meta"}

        result = rcs.inspect_search_state(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            config=config,
        )

        reconciliation = result.get("reconciliation", {})
        # Meta should remain in added since it was actually observed
        assert "Meta" in reconciliation.get("companies_added", [])
        assert reconciliation.get(
            "companies_failed"
        ) == [] or "Meta" not in reconciliation.get("companies_failed", [])

    @patch("run_create_search._extract_filter_chips_from_page")
    @patch("run_create_search._reconcile_filter_state")
    @patch("run_create_search._analyze_filter_state")
    @patch("run_create_search._click_filter_button")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("browser_utils.run_browser_command")
    def test_defensive_guard_moves_falsely_claimed_keywords_to_failed(
        self,
        mock_run_browser,
        mock_probe_class,
        mock_ensure_ready,
        mock_click_button,
        mock_analyze,
        mock_reconcile,
        mock_extract_chips,
    ):
        """REGRESSION: Keywords claimed as added but not observed must move to failed.

        This tests the defensive guard that aligns reconciliation summary with
        final observed state for keywords, similar to the company guard.
        """
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_run_browser.side_effect = [
            {"error": None},
            {
                "parsed": {
                    "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
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

        mock_analyze.side_effect = [
            {
                "expected_keywords": ["kubernetes", "python", "aws"],
                "observed_keywords": ["kubernetes"],
                "missing_keywords": ["python", "aws"],
                "missing_companies": [],
                "malformed_titles": [],
                "issues": [],
            },
            {
                "expected_keywords": ["kubernetes", "python", "aws"],
                "observed_keywords": ["kubernetes", "python"],  # aws still missing
                "missing_keywords": ["aws"],
                "missing_companies": [],
                "malformed_titles": [],
                "issues": [],
            },
        ]

        # Reconciliation claims both were added (but aws was not actually added)
        mock_reconcile.return_value = {
            "attempted": True,
            "companies_added": [],
            "companies_failed": [],
            "keywords_added": ["Python", "AWS"],  # False claim for AWS
            "keywords_failed": [],
            "titles_removed": [],
            "titles_failed": [],
            "errors": [],
        }

        mock_extract_chips.return_value = {
            "companies": [],
            "titles": [],
            "keywords": ["Kubernetes", "Python"],  # AWS NOT actually present
        }

        result = rcs.inspect_search_state(
            "9230",
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            config={"KEYWORDS": "Kubernetes, Python, AWS"},
        )

        # The reconciliation result should have been corrected by defensive guard
        reconciliation = result.get("reconciliation", {})
        # AWS should be moved to failed since it's not in observed_keywords
        assert "AWS" not in reconciliation.get("keywords_added", []), (
            "AWS should not be in keywords_added since it was not observed"
        )
        assert "AWS" in reconciliation.get("keywords_failed", []), (
            "AWS should be in keywords_failed since it was claimed but not observed"
        )
        assert "Python" in reconciliation.get("keywords_added", []), (
            "Python should remain in keywords_added since it was observed"
        )


class TestStaleBlockerClearing:
    """REGRESSION TESTS: Successful create_search must clear stale blocker/error state.

    Issue: When create_search succeeded, it was passing action_required=None and
    last_error=None to update_project_state(), but the contract requires False
    to explicitly clear these fields.
    """

    @patch("project_state.update_project_state")
    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_success_clears_stale_action_required_with_false(
        self,
        mock_resolve,
        mock_ctx,
        mock_ensure_ready,
        mock_inspect,
        mock_update,
        tmp_path,
    ):
        """Successful create_search must use action_required=False to clear stale blockers."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        mock_ensure_ready.return_value = ("9230", None)
        mock_inspect.return_value = {
            "success": True,
            "status": "ready",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "failure_code": None,
            "filter_analysis": {
                "expected_companies": ["google"],
                "observed_companies": ["google"],
                "missing_companies": [],
                "malformed_titles": [],
                "issues": [],
            },
            "reconciliation": {"attempted": False},
        }
        mock_update.return_value = {}

        rcs.run_create_search_phase("proj-1")

        # Find the call that sets status="completed"
        completed_calls = [
            call
            for call in mock_update.call_args_list
            if call.kwargs.get("status") == "completed"
        ]
        assert len(completed_calls) == 1, "Expected one call with status=completed"
        call_kwargs = completed_calls[0].kwargs

        # Must use False (not None) to clear stale action_required per contract
        assert call_kwargs.get("action_required") is False, (
            "action_required must be False to clear stale blockers, not None"
        )
        assert call_kwargs.get("last_error") is False, (
            "last_error must be False to clear stale errors, not None"
        )

    @patch("project_state.update_project_state")
    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_success_persists_structured_create_search_summary(
        self,
        mock_resolve,
        mock_ctx,
        mock_ensure_ready,
        mock_inspect,
        mock_update,
        tmp_path,
    ):
        """Successful create_search must persist structured summary for confirm_search handoff."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        mock_ensure_ready.return_value = ("9230", None)

        filter_analysis = {
            "expected_companies": ["google", "meta"],
            "observed_companies": ["google"],
            "missing_companies": ["meta"],
            "malformed_titles": ["EngineerManager"],
            "issues": ["Missing expected companies: meta"],
        }
        reconciliation = {
            "attempted": True,
            "companies_added": ["Meta"],
            "companies_failed": [],
            "titles_removed": ["EngineerManager"],
            "titles_failed": [],
        }

        mock_inspect.return_value = {
            "success": True,
            "status": "ready",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "failure_code": None,
            "filter_analysis": filter_analysis,
            "reconciliation": reconciliation,
        }
        mock_update.return_value = {}

        rcs.run_create_search_phase("proj-1")

        completed_calls = [
            call
            for call in mock_update.call_args_list
            if call.kwargs.get("status") == "completed"
        ]
        assert len(completed_calls) == 1
        call_kwargs = completed_calls[0].kwargs

        # Must persist structured create_search_summary
        structured = call_kwargs.get("create_search_summary")
        assert structured is not None, "create_search_summary must be persisted"
        assert structured.get("filter_analysis") == filter_analysis
        assert structured.get("reconciliation") == reconciliation

    @patch("run_create_search.create_initial_search_with_copilot")
    @patch("project_state.update_project_state")
    @patch("run_create_search.inspect_search_state")
    @patch("run_create_search._ensure_browser_ready")
    @patch("run_create_search.load_runtime_context")
    @patch("run_create_search.resolve_project")
    def test_failure_clears_stale_structured_create_search_summary(
        self,
        mock_resolve,
        mock_ctx,
        mock_ensure_ready,
        mock_inspect,
        mock_update,
        mock_copilot,
        tmp_path,
    ):
        """Blocked create_search must clear any stale structured summary."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("", encoding="utf-8")
        mock_ctx.return_value = {"profile": {"CDP_PORT": "9230"}}
        mock_resolve.return_value = (
            config_path,
            {
                "PROJECT_ID": "proj-1",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
            "123",
        )
        mock_ensure_ready.return_value = ("9230", None)
        mock_copilot.return_value = {
            "success": False,
            "status": "copilot_widget_missing",
            "failure_code": "ELEMENT_MISSING",
            "action_required": {
                "code": "ELEMENT_MISSING",
                "summary": "Copilot widget not found",
            },
        }
        mock_inspect.return_value = {
            "success": False,
            "status": "loading",
            "failure_code": "timeout",
            "action_required": {
                "code": "timeout",
                "summary": "Timed out",
                "steps": [],
                "actor": "agent",
            },
        }
        mock_update.return_value = {}

        rcs.run_create_search_phase("proj-1")

        blocked_calls = [
            call
            for call in mock_update.call_args_list
            if call.kwargs.get("status") == "action_required"
        ]
        assert len(blocked_calls) == 1
        assert blocked_calls[0].kwargs.get("create_search_summary") is False
