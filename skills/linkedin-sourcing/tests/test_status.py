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

    def test_follows_phase_order_when_no_workbook_work(self):
        """Should follow phase order when no specific workbook work found."""
        workbook_summary = {
            "total_rows": 0,
            "by_next_action": {},
        }

        next_phase, message, ready = status.determine_next_phase(
            "create_search", "completed", workbook_summary, "reachout"
        )

        assert next_phase == "extract"

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
        from excel_utils import create, append

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
        from excel_utils import create, append

        workbook_path = tmp_path / "test.xlsx"
        create(str(workbook_path))

        # Add rows with different next_actions
        append(str(workbook_path), {"name": "Alice", "next_action": "filter"})
        append(str(workbook_path), {"name": "Bob", "next_action": "filter"})
        append(str(workbook_path), {"name": "Charlie", "next_action": "enrich"})

        summary = status.get_workbook_summary(workbook_path)

        assert summary["by_next_action"].get("filter") == 2
        assert summary["by_next_action"].get("enrich") == 1


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

        from project_state import save_project_state, create_initial_state

        state = create_initial_state(
            "test_project", current_phase="filter", status="completed"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        assert result["project_id"] == "test_project"
        assert result["current_phase"] == "filter"
        assert result["status"] == "completed"

    def test_includes_next_command(self, tmp_path):
        """Should include next_command in result."""
        project_dir = tmp_path / "projects" / "test_project"
        project_dir.mkdir(parents=True)
        config_file = project_dir / "config.sh"
        config_file.write_text('PROJECT_ID="test_project"\n')

        # Create workbook with rows waiting for filter
        workbook_path = project_dir / "workbook.xlsx"
        from excel_utils import create, append

        create(str(workbook_path))
        append(
            str(workbook_path),
            {"name": "John", "next_action": "filter", "status": "Extracted"},
        )

        from project_state import save_project_state, create_initial_state

        state = create_initial_state(
            "test_project", current_phase="filter", status="completed"
        )
        save_project_state(project_dir, state)

        result = status.get_status("test_project", tmp_path)

        assert result.get("next_command") is not None


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
        from project_state import save_project_state, create_initial_state

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
