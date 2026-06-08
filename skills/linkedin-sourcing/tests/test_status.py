#!/usr/bin/env python3
"""Tests for status.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_status.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import status


class TestGetLoopCommand:
    """Tests for get_loop_command function."""

    def test_returns_basic_loop_command(self):
        """Should return basic loop command without confirm-send."""
        cmd = status.get_loop_command("my_project")
        assert "run_reachout_loop.py" in cmd
        assert "--project my_project" in cmd
        assert "--confirm-send" not in cmd

    def test_returns_confirm_send_command(self):
        """Should return loop command with confirm-send when requested."""
        cmd = status.get_loop_command("my_project", confirm_send=True)
        assert "run_reachout_loop.py" in cmd
        assert "--project my_project" in cmd
        assert "--confirm-send" in cmd


class TestGetLoopResumeGuidance:
    """Tests for get_loop_resume_guidance function."""

    def test_returns_none_when_no_action_required(self):
        """Should return None when action_required is None."""
        guidance = status.get_loop_resume_guidance(None, "my_project")
        assert guidance is None

    def test_includes_code_and_summary(self):
        """Should include code and summary from action_required."""
        action_required = {
            "code": "search_not_configured",
            "summary": "Search needs configuration",
        }
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert guidance is not None
        assert guidance["code"] == "search_not_configured"
        assert guidance["summary"] == "Search needs configuration"

    def test_includes_loop_command(self):
        """Should include loop command to resume."""
        action_required = {"code": "auth_required", "summary": "Login required"}
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert guidance is not None
        assert "run_reachout_loop.py" in guidance["then_run"]
        assert "--project my_project" in guidance["then_run"]

    def test_search_not_configured_guidance(self):
        """Should provide specific guidance for search_not_configured."""
        action_required = {
            "code": "search_not_configured",
            "summary": "Search needs configuration",
            "actor": "agent",
        }
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert "configure the candidate search" in guidance["resolve_now"].lower()
        assert "manually" not in guidance["resolve_now"].lower()
        assert guidance["actor"] == "agent"

    def test_preserves_user_actor_in_guidance(self):
        """Should preserve actor so callers can distinguish user-only blockers."""
        action_required = {
            "code": "auth_required",
            "summary": "Login required",
            "actor": "user",
        }
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert guidance is not None
        assert guidance["actor"] == "user"

    def test_auth_required_guidance(self):
        """Should provide specific guidance for auth_required."""
        action_required = {"code": "auth_required", "summary": "Login required"}
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert "Log in to LinkedIn Recruiter" in guidance["resolve_now"]

    def test_generic_guidance_for_unknown_code(self):
        """Should provide generic guidance for unknown blocker codes."""
        action_required = {"code": "unknown_blocker", "summary": "Something is wrong"}
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert "Resolve the blocker" in guidance["resolve_now"]

    def test_project_messaging_incomplete_guidance(self):
        """Should provide specific guidance for unresolved project messaging fields."""
        action_required = {
            "code": "project_messaging_incomplete",
            "summary": "Project messaging fields must be finalized before drafting",
            "context": {"fields": ["CORE_FUNCTION", "BUSINESS_IMPACT"]},
        }
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert "CORE_FUNCTION" in guidance["resolve_now"]
        assert "BUSINESS_IMPACT" in guidance["resolve_now"]

    def test_browser_unavailable_guidance_with_recovery_command(self):
        """Should provide specific guidance with recovery command for browser_unavailable."""
        action_required = {
            "code": "browser_unavailable",
            "summary": "Chrome browser is not available",
            "context": {
                "recovery_command": 'bash "/path/to/connect_browser.sh"',
                "cdp_port": "9230",
            },
        }
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert "Chrome/CDP is not connected" in guidance["resolve_now"]
        assert "connect_browser.sh" in guidance["resolve_now"]
        assert "bash" in guidance["resolve_now"]

    def test_browser_unavailable_guidance_without_recovery_command(self):
        """Should provide generic guidance when recovery_command not in context."""
        action_required = {
            "code": "browser_unavailable",
            "summary": "Chrome browser is not available",
            "context": {"cdp_port": "9230"},
        }
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert "Chrome/CDP is not connected" in guidance["resolve_now"]
        assert "connect_browser.sh" in guidance["resolve_now"]

    def test_includes_steps_from_action_required(self):
        """Should include steps from action_required in guidance."""
        action_required = {
            "code": "auth_required",
            "summary": "Login required",
            "steps": ["Open Chrome", "Log in to LinkedIn", "Retry"],
        }
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert guidance is not None
        assert "steps" in guidance
        assert guidance["steps"] == ["Open Chrome", "Log in to LinkedIn", "Retry"]

    def test_steps_defaults_to_empty_list(self):
        """Should default to empty list when steps not provided."""
        action_required = {"code": "auth_required", "summary": "Login required"}
        guidance = status.get_loop_resume_guidance(action_required, "my_project")
        assert guidance is not None
        assert "steps" in guidance
        assert guidance["steps"] == []


class TestDetermineNextPhase:
    """Tests for determine_next_phase function."""

    def test_filter_when_rows_waiting_for_filter(self):
        """Should suggest filter when rows have next_action=filter."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"filter": 3, "done": 2},
        }

        next_phase, message, ready = status.determine_next_phase(
            "extract", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "filter"
        assert "3 rows ready for filter" in message
        assert ready is True

    def test_enrich_when_rows_waiting_for_enrich(self):
        """Should suggest enrich when rows have next_action=enrich."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"enrich": 3, "done": 2},
        }

        next_phase, message, ready = status.determine_next_phase(
            "filter", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "enrich"
        assert "3 rows ready for enrich" in message

    def test_draft_when_rows_waiting_for_draft(self):
        """Should suggest draft when rows have next_action=draft."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"draft": 3, "done": 2},
        }

        next_phase, message, ready = status.determine_next_phase(
            "filter", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "draft"
        assert "3 rows ready for draft" in message

    def test_review_when_rows_waiting_for_review(self):
        """Should suggest review when rows have next_action=review."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"review": 3, "done": 2},
        }

        next_phase, message, ready = status.determine_next_phase(
            "draft", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "review"
        assert "3 rows ready for human review" in message
        assert ready is True

    def test_send_when_rows_waiting_for_send(self):
        """Should suggest send when rows have next_action=send."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"send": 3, "done": 2},
        }

        next_phase, message, ready = status.determine_next_phase(
            "review", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "send"
        assert "3 rows ready to send" in message

    def test_none_when_all_done(self):
        """Should return None when all rows are done."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"done": 5},
        }

        next_phase, message, ready = status.determine_next_phase(
            "send", "completed", workbook_summary, "reachout"
        )

        assert next_phase is None
        assert "All rows completed" in message

    def test_blocked_when_action_required(self):
        """Should be blocked when action_required field is present."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"filter": 5},
        }

        next_phase, message, ready = status.determine_next_phase(
            "extract",
            "completed",
            workbook_summary,
            "reachout",
            action_required={
                "code": "search_not_configured",
                "summary": "Search needs configuration",
            },
        )

        assert next_phase is None
        assert "Action required" in message
        assert ready is False

    def test_blocked_when_action_required_with_different_status(self):
        """Should be blocked when action_required exists even if status is not 'action_required'."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"filter": 5},
        }

        # create_search can persist status='search_not_configured' with action_required
        next_phase, message, ready = status.determine_next_phase(
            "create_search",
            "search_not_configured",
            workbook_summary,
            "reachout",
            action_required={
                "code": "create_search_failed",
                "summary": "Failed to create search",
            },
        )

        assert next_phase is None
        assert "Action required" in message
        assert ready is False

    def test_blocked_when_failed(self):
        """Should stay at failed phase when status is failed."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"filter": 5},
        }

        next_phase, message, ready = status.determine_next_phase(
            "extract", "failed", workbook_summary, "reachout"
        )

        assert next_phase == "extract"
        assert "failed" in message.lower()
        assert ready is False

    def test_blocked_when_running(self):
        """Should be blocked when status is running."""
        workbook_summary = {
            "total_rows": 5,
            "by_next_action": {"filter": 5},
        }

        next_phase, message, ready = status.determine_next_phase(
            "extract", "running", workbook_summary, "reachout"
        )

        assert next_phase is None
        assert "running" in message.lower()
        assert ready is False

    def test_routes_to_confirm_search_after_create_search_completed(self):
        """Should route to confirm_search when create_search completes and no workbook rows."""
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
        }

        next_phase, message, ready = status.determine_next_phase(
            "create_search", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "confirm_search"
        assert "confirm filters" in message.lower()

    def test_follows_phase_order_when_no_workbook_work(self):
        """Should follow phase order when no specific workbook work found."""
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
        }

        # For phases other than create_search, should follow normal phase order
        next_phase, message, ready = status.determine_next_phase(
            "filter", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "enrich"

    def test_review_is_stop_boundary(self):
        """Review should be identified as a stop boundary."""
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
        }

        next_phase, message, ready = status.determine_next_phase(
            "draft", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "review"

    def test_blocks_when_workbook_unreadable(self):
        """Should block with error when workbook is unreadable."""
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
            "error": "Failed to read workbook",
        }

        next_phase, message, ready = status.determine_next_phase(
            "filter", "completed", workbook_summary, "reachout"
        )

        assert next_phase is None
        assert "Workbook unreadable" in message
        assert ready is False

    def test_bootstrap_handoff_to_create_search(self):
        """Freshly bootstrapped projects should hand off to create_search."""
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
        }

        next_phase, message, ready = status.determine_next_phase(
            "bootstrap", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "create_search"
        assert "Bootstrap complete" in message
        assert ready is True

    def test_empty_extraction_is_terminal_state(self):
        """REGRESSION TEST: Empty successful extraction should be terminal, not suggest filter.

        Bug: After extract completed with 0 rows, status fell through to phase-order
        progression and recommended filter/review work that does not exist.
        """
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
        }

        next_phase, message, ready = status.determine_next_phase(
            "extract", "completed", workbook_summary, "reachout"
        )

        assert next_phase is None
        assert "no candidates found" in message.lower()
        assert ready is True

    def test_empty_extraction_not_terminal_if_not_completed(self):
        """Empty extraction should not be terminal if status is not completed."""
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
        }

        # If extract is running with 0 rows, it's not terminal
        next_phase, message, ready = status.determine_next_phase(
            "extract", "running", workbook_summary, "reachout"
        )

        assert next_phase is None
        assert "running" in message.lower()
        assert ready is False


class TestGetWorkbookSummary:
    """Tests for get_workbook_summary function."""

    def test_returns_summary_for_existing_workbook(self, tmp_path):
        """Should return summary for existing workbook."""
        # Create a test workbook
        from excel_utils import append, create

        workbook_path = tmp_path / "test.xlsx"
        create(str(workbook_path))

        # Add some test rows
        append(
            str(workbook_path),
            {"name": "John", "next_action": "filter", "status": "Extracted"},
        )

        summary = status.get_workbook_summary(workbook_path)

        assert summary["total_rows"] == 1
        assert summary["by_next_action"].get("filter") == 1

    def test_handles_missing_workbook(self, tmp_path):
        """Should handle missing workbook gracefully."""
        missing_path = tmp_path / "nonexistent.xlsx"

        summary = status.get_workbook_summary(missing_path)

        assert "error" in summary
        assert summary["total_rows"] == 0

    def test_missing_workbook_is_error_not_empty(self):
        """Missing workbook should be treated as error, not empty workbook."""
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
            "error": "Workbook not found - project may need extraction",
        }

        next_phase, message, ready = status.determine_next_phase(
            "extract", "completed", workbook_summary, "reachout"
        )

        assert next_phase is None
        assert "Workbook unreadable" in message
        assert ready is False

    def test_counts_by_next_action(self, tmp_path):
        """Should correctly count rows by next_action."""
        from excel_utils import append, create

        workbook_path = tmp_path / "test.xlsx"
        create(str(workbook_path))

        # Add rows with different next_actions
        append(str(workbook_path), {"name": "Alice", "next_action": "filter"})
        append(str(workbook_path), {"name": "Bob", "next_action": "filter"})
        append(str(workbook_path), {"name": "Charlie", "next_action": "enrich"})

        summary = status.get_workbook_summary(workbook_path)

        assert summary["by_next_action"].get("filter") == 2
        assert summary["by_next_action"].get("enrich") == 1


class TestConfirmSearchFilterSummary:
    """Tests for confirm_search filter analysis summary in status."""

    def test_status_includes_last_result_summary(self, tmp_path):
        """Status should include last_result_summary from project state."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="create_search", status="completed"
        )
        state["last_result_summary"] = (
            "Recruiter search verified; Issue: Missing companies: amazon; Malformed titles: EngineerManager"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        assert result["last_result_summary"] is not None
        assert "Missing companies: amazon" in result["last_result_summary"]

    def test_confirm_search_loop_command_includes_flag(self):
        """Loop command for confirm_search should include --confirm-search flag."""
        cmd = status.get_loop_command("my_project", confirm_search=True)
        assert "--confirm-search" in cmd
        assert "--confirm-send" not in cmd

    def test_confirm_search_summary_exposed_at_boundary(self, tmp_path):
        """Status should expose confirm_search_summary when at confirm_search boundary."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        # Create empty workbook (extraction hasn't run yet)
        workbook_path = project_dir / "workbook.xlsx"
        from excel_utils import create

        create(str(workbook_path))

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="create_search", status="completed"
        )
        state["last_result_summary"] = (
            "Recruiter search verified; Issue: Missing companies: amazon; Malformed titles: EngineerManager"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        # Should be at confirm_search boundary
        assert result["next_phase"] == "confirm_search"
        # Should expose confirm_search_summary derived from last_result_summary
        assert result.get("confirm_search_summary") is not None
        assert "Missing companies: amazon" in result["confirm_search_summary"]
        assert "Malformed titles: EngineerManager" in result["confirm_search_summary"]

    def test_confirm_search_summary_not_exposed_when_not_at_boundary(self, tmp_path):
        """Status should not expose confirm_search_summary when not at confirm_search boundary."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        # Create workbook with rows to move past confirm_search
        workbook_path = project_dir / "workbook.xlsx"
        from excel_utils import append, create

        create(str(workbook_path))
        append(
            str(workbook_path),
            {"name": "John", "next_action": "filter", "status": "Extracted"},
        )

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="extract", status="completed"
        )
        state["last_result_summary"] = "Extraction complete: 1 candidates"
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        # Should NOT be at confirm_search boundary
        assert result["next_phase"] != "confirm_search"
        # Should NOT expose confirm_search_summary
        assert result.get("confirm_search_summary") is None

    def test_confirm_search_summary_includes_reconciliation_results(self, tmp_path):
        """Status should include reconciliation results in confirm_search_summary."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        # Create empty workbook (extraction hasn't run yet)
        workbook_path = project_dir / "workbook.xlsx"
        from excel_utils import create

        create(str(workbook_path))

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="create_search", status="completed"
        )
        # Summary with reconciliation results
        state["last_result_summary"] = (
            "Recruiter search verified with visible candidates; "
            "Auto-added companies: Amazon; "
            "Failed to add companies: Netflix; "
            "Auto-removed malformed titles: EngineerManager; "
            "Missing companies: netflix; "
            "Malformed titles: DeveloperEngineer"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        # Should be at confirm_search boundary
        assert result["next_phase"] == "confirm_search"
        # Should expose confirm_search_summary with reconciliation results
        assert result.get("confirm_search_summary") is not None
        assert "Auto-added companies: Amazon" in result["confirm_search_summary"]
        assert "Failed to add companies: Netflix" in result["confirm_search_summary"]
        assert (
            "Auto-removed malformed titles: EngineerManager"
            in result["confirm_search_summary"]
        )

    def test_confirm_search_summary_uses_structured_data_when_available(self, tmp_path):
        """Structured confirm-search summary should include copilot query and search brief."""
        from openpyxl import Workbook
        from project_state import create_initial_state, save_project_state

        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        (project_dir / "config.sh").write_text(
            'PROJECT_ID="test_project"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123/discover"\n',
            encoding="utf-8",
        )
        wb = Workbook()
        wb.save(project_dir / "workbook.xlsx")
        state = create_initial_state(
            "test_project", current_phase="create_search", status="completed"
        )
        state["create_search_summary"] = {
            "recruiter_url": "https://linkedin.com/talent/hire/123/discover",
            "copilot_query": "Create a search for Software Engineer in San Francisco",
            "search_brief": "Search for Software Engineer candidates",
        }
        state["last_result_summary"] = "Legacy string summary"
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        # Should be at confirm_search boundary
        assert result["next_phase"] == "confirm_search"
        # Should build summary from structured data, not use legacy string
        confirm_summary = result.get("confirm_search_summary", "")
        assert "Software Engineer" in confirm_summary
        assert "Legacy string summary" not in confirm_summary
        # Should expose normalized entries for pretty rendering
        entries = result.get("confirm_search_entries") or []
        assert any("Copilot query" in text for kind, text in entries)

    def test_confirm_search_summary_includes_keyword_results(self, tmp_path):
        """Structured confirm-search summary should include copilot query and search brief."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        from excel_utils import create

        workbook_path = project_dir / "workbook.xlsx"
        create(str(workbook_path))

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="create_search", status="completed"
        )
        state["create_search_summary"] = {
            "copilot_query": "Create a search for Software Engineer with Python skills",
            "search_brief": "Search for Software Engineer candidates",
        }
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        confirm_summary = result.get("confirm_search_summary", "")
        assert "Software Engineer" in confirm_summary
        assert "Python" in confirm_summary


class TestCreateSearchToConfirmSearchRouting:
    """REGRESSION TESTS: create_search->confirm_search routing with missing workbook."""

    def test_routes_to_confirm_search_when_workbook_missing(self, tmp_path):
        """Missing workbook should not block valid post-create_search handoff to confirm_search."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        # NO workbook created - extraction hasn't run yet

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="create_search", status="completed"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        # Should route to confirm_search even without workbook
        assert result["next_phase"] == "confirm_search"
        assert result["ready"] is True
        assert "confirm filters" in result["message"].lower()
        assert "error" not in result["workbook_summary"], (
            "Workbook summary should be normalized for confirm_search handoff"
        )

    def test_blocks_on_missing_workbook_for_other_phases(self, tmp_path):
        """Missing workbook should still block phases other than create_search->confirm_search."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        # NO workbook created

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="extract", status="completed"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        # Should block with workbook error for extract phase
        assert result["next_phase"] is None
        assert result["ready"] is False
        assert "Workbook unreadable" in result["message"]

    def test_structured_confirm_search_summary_keeps_issue_and_error_details(
        self, tmp_path
    ):
        """Structured confirm-search summary should show copilot query and search brief."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        from excel_utils import create

        workbook_path = project_dir / "workbook.xlsx"
        create(str(workbook_path))

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="create_search", status="completed"
        )
        state["create_search_summary"] = {
            "copilot_query": "Create a search for Software Engineer in San Francisco",
            "search_brief": "Search for Software Engineer candidates",
        }
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        entries = result.get("confirm_search_entries") or []
        assert any("Copilot query" in text for kind, text in entries)
        assert any("Software Engineer" in text for kind, text in entries)


class TestGetStatus:
    """Tests for get_status function."""

    def test_returns_error_for_invalid_project_ref(self, tmp_path):
        """Should return error for invalid project reference."""
        # Use a work_dir with no projects
        result = status.get_status("nonexistent_project", tmp_path)

        assert result["error"] is not None
        assert result["ready"] is False

    def test_returns_error_when_no_state(self, tmp_path):
        """Should return error when project exists but no state file."""
        # Create project directory structure without state
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        result = status.get_status("test_project", tmp_path)

        assert "state" in result.get("error", "").lower() or result["error"] is not None

    def test_returns_status_with_valid_project(self, tmp_path):
        """Should return complete status for valid project."""
        # Create project with state
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="filter", status="completed"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        assert result["project_id"] == "test_project"
        assert result["current_phase"] == "filter"
        assert result["status"] == "completed"

    def test_includes_loop_resume_guidance_when_blocked(self, tmp_path):
        """Should include loop_resume_guidance when action_required is present."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project",
            current_phase="create_search",
            status="search_not_configured",
        )
        state["action_required"] = {
            "code": "search_not_configured",
            "summary": "Search needs configuration",
        }
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        assert result["action_required"] is not None
        assert result["loop_resume_guidance"] is not None
        assert result["loop_resume_guidance"]["code"] == "search_not_configured"
        assert "run_reachout_loop.py" in result["loop_resume_guidance"]["then_run"]

    def test_includes_loop_command(self, tmp_path):
        """Should include loop_command in result."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        # Create workbook with rows waiting for filter
        workbook_path = project_dir / "workbook.xlsx"
        from excel_utils import append, create

        create(str(workbook_path))
        append(
            str(workbook_path),
            {"name": "John", "next_action": "filter", "status": "Extracted"},
        )

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="filter", status="completed"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        assert result.get("loop_command") is not None
        assert "run_reachout_loop.py" in result["loop_command"]

    def test_includes_next_command_for_backward_compatibility(self, tmp_path):
        """Should include next_command as compatibility shim for existing consumers."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        # Create workbook with rows waiting for filter
        workbook_path = project_dir / "workbook.xlsx"
        from excel_utils import append, create

        create(str(workbook_path))
        append(
            str(workbook_path),
            {"name": "John", "next_action": "filter", "status": "Extracted"},
        )

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="filter", status="completed"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        # next_command should exist and point to loop_command for compatibility
        assert result.get("next_command") is not None
        assert result["next_command"] == result["loop_command"]
        assert "run_reachout_loop.py" in result["next_command"]

    def test_blocks_draft_when_project_messaging_is_unresolved(self, tmp_path):
        """Draft should be blocked until project-level messaging placeholders are resolved."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text(
            'PROJECT_ID="test_project"\nCORE_FUNCTION="[AGENT: infer from JD - what does this team do?]"\nBUSINESS_IMPACT="[AGENT: infer from JD - why does this work matter?]"\n'
        )

        workbook_path = project_dir / "workbook.xlsx"
        from excel_utils import append, create

        create(str(workbook_path))
        append(
            str(workbook_path),
            {"name": "John", "next_action": "draft", "status": "Enriched"},
        )

        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "test_project", current_phase="enrich", status="completed"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        assert result["next_phase"] is None
        assert result["ready"] is False
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "project_messaging_incomplete"
        assert result["unresolved_project_messaging_fields"] == [
            "CORE_FUNCTION",
            "BUSINESS_IMPACT",
        ]
        assert "before drafting" in result["message"].lower()


class TestStatusIntegration:
    """Integration tests for status module."""

    def test_end_to_end_status_flow(self, tmp_path):
        """Test complete status flow from project creation to status check."""
        # Setup project
        project_dir = tmp_path / "projects" / "my_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text(
            'PROJECT_ID="my_project"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/projects"'
        )

        workbook_path = project_dir / "workbook.xlsx"
        from excel_utils import create

        create(str(workbook_path))

        # Create state
        from project_state import create_initial_state, save_project_state

        state = create_initial_state(
            "my_project", current_phase="extract", status="completed"
        )
        save_project_state(project_dir, state)

        # Get status
        result = status.get_status("my_project", tmp_path)

        # Verify structure
        assert result["project_ref"] == "my_project"
        assert result["project_id"] == "my_project"
        assert result["current_phase"] == "extract"
        assert result["status"] == "completed"
        assert "workbook_summary" in result
        assert "next_phase" in result
        assert "ready" in result


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
