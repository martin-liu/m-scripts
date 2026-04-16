#!/usr/bin/env python3
"""Tests for run_reachout_loop.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_run_reachout_loop.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_reachout_loop as loop


class TestCheckStopConditions:
    """Tests for check_stop_conditions function."""

    def test_stops_when_action_required_present(self):
        """Should stop when action_required is present."""
        status_result = {
            "action_required": {
                "code": "search_not_configured",
                "summary": "Search needs configuration",
            },
            "next_phase": "extract",
            "current_phase": "create_search",
            "status": "completed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert "Action required" in reason
        assert exit_code == 2

    def test_stops_when_workflow_complete(self):
        """Should stop when next_phase is None and ready=True (workflow complete)."""
        status_result = {
            "action_required": None,
            "next_phase": None,
            "current_phase": "send",
            "status": "completed",
            "ready": True,
            "message": "All rows completed",
            "workbook_summary": {"total_rows": 5, "by_next_action": {"done": 5}},
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert "complete" in reason.lower()
        assert exit_code == 0

    def test_stops_cleanly_on_empty_extraction(self):
        """REGRESSION TEST: Loop should stop cleanly when extract completes with 0 rows.

        Bug: Empty successful extraction fell through to phase-order progression,
        suggesting filter work that does not exist.
        """
        status_result = {
            "action_required": None,
            "next_phase": None,
            "current_phase": "extract",
            "status": "completed",
            "ready": True,
            "message": "Extraction complete - no candidates found",
            "workbook_summary": {"total_rows": 0, "by_next_action": {}},
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert exit_code == 0
        assert "complete" in reason.lower() or "no candidates" in reason.lower()

    def test_blocked_not_ready_with_none_next_phase_exits_error(self):
        """REGRESSION TEST: next_phase=None with ready=False should exit error, not 0.

        Bug: Previously, any next_phase=None was treated as workflow complete (exit 0),
        even when the workflow was actually blocked due to workbook issues,
        running phase, or other not-ready states.
        """
        status_result = {
            "action_required": None,
            "next_phase": None,
            "current_phase": "extract",
            "status": "completed",
            "ready": False,
            "message": "Workbook unreadable: Failed to read",
            "workbook_summary": {
                "total_rows": 0,
                "by_next_action": {},
                "error": "Failed to read",
            },
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert exit_code == 1  # NOT 0 - this was the bug
        assert "blocked" in reason.lower() or "workbook" in reason.lower()

    def test_running_phase_with_none_next_phase_exits_error(self):
        """REGRESSION TEST: Phase running with next_phase=None should exit error, not 0.

        When a phase is running, determine_next_phase returns (None, message, False).
        This should NOT be treated as workflow complete.
        """
        status_result = {
            "action_required": None,
            "next_phase": None,
            "current_phase": "extract",
            "status": "running",
            "ready": False,
            "message": "Phase 'extract' is currently running",
            "workbook_summary": {"total_rows": 5, "by_next_action": {"filter": 5}},
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert exit_code == 1  # NOT 0 - this was the bug
        assert "running" in reason.lower()

    def test_workbook_error_exits_before_status_check(self):
        """Workbook errors should stop with exit code 1."""
        status_result = {
            "action_required": None,
            "next_phase": "filter",
            "current_phase": "extract",
            "status": "completed",
            "ready": False,
            "message": "Workbook unreadable",
            "workbook_summary": {
                "total_rows": 0,
                "by_next_action": {},
                "error": "Workbook not found",
            },
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert exit_code == 1
        assert "workbook" in reason.lower()

    def test_stops_when_phase_failed(self):
        """Should stop when current phase failed."""
        status_result = {
            "action_required": None,
            "next_phase": "filter",
            "current_phase": "extract",
            "status": "failed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert "failed" in reason.lower()
        assert exit_code == 1

    def test_stops_when_phase_running(self):
        """Should stop when current phase is running."""
        status_result = {
            "action_required": None,
            "next_phase": "filter",
            "current_phase": "extract",
            "status": "running",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert "running" in reason.lower()
        assert exit_code == 0

    def test_stops_at_review_boundary(self):
        """Should stop at review phase (human boundary)."""
        status_result = {
            "action_required": None,
            "next_phase": "review",
            "current_phase": "draft",
            "status": "completed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert "review" in reason.lower()
        assert exit_code == 0

    def test_stops_at_send_boundary_without_confirm(self):
        """Should stop at send boundary without --confirm-send."""
        status_result = {
            "action_required": None,
            "next_phase": "send",
            "current_phase": "review",
            "status": "completed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(
            status_result, confirm_send=False
        )

        assert should_stop is True
        assert "send" in reason.lower()
        assert exit_code == 0

    def test_continues_at_send_boundary_with_confirm(self):
        """Should continue at send boundary with --confirm-send."""
        status_result = {
            "action_required": None,
            "next_phase": "send",
            "current_phase": "review",
            "status": "completed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(
            status_result, confirm_send=True
        )

        assert should_stop is False
        assert "send" in reason.lower()

    def test_continues_for_automated_phases(self):
        """Should continue for automated phases like filter, draft."""
        for phase in ["filter", "draft", "enrich", "extract", "create_search"]:
            status_result = {
                "action_required": None,
                "next_phase": phase,
                "current_phase": "previous",
                "status": "completed",
            }

            should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

            assert should_stop is False, f"Should continue for phase {phase}"
            assert phase in reason.lower()


class TestClassifyPhaseResult:
    """Tests for classify_phase_result function."""

    def test_continues_on_success(self):
        """Should continue when phase succeeds."""
        phase_result = {
            "success": True,
            "phase": "filter",
        }

        should_continue, message, exit_code = loop.classify_phase_result(phase_result)

        assert should_continue is True
        assert exit_code == 0

    def test_stops_at_review_boundary(self):
        """Should stop at review phase even on success."""
        phase_result = {
            "success": True,
            "phase": "review",
        }

        should_continue, message, exit_code = loop.classify_phase_result(phase_result)

        assert should_continue is False
        assert "review" in message.lower()
        assert exit_code == 0

    def test_stops_on_browser_blocker(self):
        """Should stop with exit code 2 when browser/manual blocker present."""
        phase_result = {
            "success": False,
            "phase": "enrich",
            "blocked": True,
            "block_reason": "browser_manual_intervention",
            "state_after": {
                "action_required": {
                    "code": "auth_required",
                    "summary": "Login required",
                }
            },
        }

        should_continue, message, exit_code = loop.classify_phase_result(phase_result)

        assert should_continue is False
        assert exit_code == 2
        assert "blocked" in message.lower() or "intervention" in message.lower()

    def test_stops_on_failure(self):
        """Should stop with exit code 1 on generic failure."""
        phase_result = {
            "success": False,
            "phase": "filter",
            "error": "Something went wrong",
            "state_after": {},
        }

        should_continue, message, exit_code = loop.classify_phase_result(phase_result)

        assert should_continue is False
        assert exit_code == 1
        assert "failed" in message.lower()

    def test_stops_on_create_search_action_required(self):
        """Should stop with exit code 2 when create_search has action_required."""
        phase_result = {
            "success": False,
            "phase": "create_search",
            "blocked": True,
            "action_required": {
                "code": "search_not_configured",
                "summary": "Search needs manual configuration",
            },
            "state_after": {
                "action_required": {
                    "code": "search_not_configured",
                    "summary": "Search needs manual configuration",
                }
            },
        }

        should_continue, message, exit_code = loop.classify_phase_result(phase_result)

        assert should_continue is False
        assert exit_code == 2


class TestRunLoopIteration:
    """Tests for run_loop_iteration function."""

    def test_stops_when_status_has_action_required(self):
        """Should stop immediately when status has action_required."""
        with patch.object(loop, "load_status") as mock_load:
            mock_load.return_value = {
                "current_phase": "create_search",
                "status": "completed",
                "next_phase": "extract",
                "action_required": {
                    "code": "search_not_configured",
                    "summary": "Search needs configuration",
                },
                "workbook_summary": {"total_rows": 0, "by_next_action": {}},
            }

            should_continue, message, exit_code = loop.run_loop_iteration(
                "test_project", confirm_send=False, dry_run=False
            )

            assert should_continue is False
            assert exit_code == 2
            assert "Action required" in message

    def test_runs_phase_when_ready(self):
        """Should run phase when ready."""
        with patch.object(loop, "load_status") as mock_load:
            with patch.object(loop, "run_single_phase") as mock_run:
                mock_load.return_value = {
                    "current_phase": "extract",
                    "status": "completed",
                    "next_phase": "filter",
                    "action_required": None,
                    "workbook_summary": {
                        "total_rows": 5,
                        "by_next_action": {"filter": 5},
                    },
                }
                mock_run.return_value = {
                    "success": True,
                    "phase": "filter",
                }

                should_continue, message, exit_code = loop.run_loop_iteration(
                    "test_project", confirm_send=False, dry_run=False
                )

                mock_run.assert_called_once_with(
                    "test_project", "filter", dry_run=False
                )
                assert should_continue is True
                assert exit_code == 0

    def test_dry_run_does_not_execute(self):
        """Should not execute phase in dry-run mode."""
        with patch.object(loop, "load_status") as mock_load:
            with patch.object(loop, "run_single_phase") as mock_run:
                mock_load.return_value = {
                    "current_phase": "extract",
                    "status": "completed",
                    "next_phase": "filter",
                    "action_required": None,
                    "workbook_summary": {"total_rows": 0, "by_next_action": {}},
                }

                should_continue, message, exit_code = loop.run_loop_iteration(
                    "test_project", confirm_send=False, dry_run=True
                )

                mock_run.assert_not_called()
                assert should_continue is True  # Dry run continues


class TestRunReachoutLoop:
    """Tests for run_reachout_loop function."""

    def test_exits_cleanly_on_stop_condition(self):
        """Should exit cleanly when stop condition met."""
        with patch.object(loop, "run_loop_iteration") as mock_iter:
            mock_iter.return_value = (False, "Workflow complete", 0)

            exit_code = loop.run_reachout_loop("test_project")

            assert exit_code == 0

    def test_exits_with_code_2_on_browser_blocker(self):
        """Should exit with code 2 on browser/manual blocker."""
        with patch.object(loop, "run_loop_iteration") as mock_iter:
            mock_iter.return_value = (
                False,
                "Action required: auth_required",
                2,
            )

            exit_code = loop.run_reachout_loop("test_project")

            assert exit_code == 2

    def test_runs_multiple_iterations(self):
        """Should run multiple iterations until stopped."""
        with patch.object(loop, "run_loop_iteration") as mock_iter:
            # First two iterations continue, third stops
            mock_iter.side_effect = [
                (True, "Phase 1 complete", 0),
                (True, "Phase 2 complete", 0),
                (False, "Workflow complete", 0),
            ]

            exit_code = loop.run_reachout_loop("test_project")

            assert exit_code == 0
            assert mock_iter.call_count == 3

    def test_respects_once_flag(self):
        """Should run only one iteration with --once flag."""
        with patch.object(loop, "run_loop_iteration") as mock_iter:
            mock_iter.return_value = (True, "Phase complete", 0)

            exit_code = loop.run_reachout_loop("test_project", once=True)

            assert exit_code == 0
            assert mock_iter.call_count == 1

    def test_respects_max_iterations(self):
        """Should stop after max_iterations."""
        with patch.object(loop, "run_loop_iteration") as mock_iter:
            # Always continue (should hit max)
            mock_iter.return_value = (True, "Phase complete", 0)

            exit_code = loop.run_reachout_loop("test_project", max_iterations=3)

            assert exit_code == 0
            assert mock_iter.call_count == 3


class TestIntegrationScenarios:
    """Integration-style tests for common scenarios."""

    def test_full_workflow_to_review_boundary(self):
        """Test loop runs through phases until review boundary."""
        status_sequence = [
            # Initial: extract complete, filter ready
            {
                "current_phase": "extract",
                "status": "completed",
                "next_phase": "filter",
                "action_required": None,
                "workbook_summary": {"total_rows": 5, "by_next_action": {"filter": 5}},
            },
            # After filter: enrich ready
            {
                "current_phase": "filter",
                "status": "completed",
                "next_phase": "enrich",
                "action_required": None,
                "workbook_summary": {"total_rows": 5, "by_next_action": {"enrich": 5}},
            },
            # After enrich: draft ready
            {
                "current_phase": "enrich",
                "status": "completed",
                "next_phase": "draft",
                "action_required": None,
                "workbook_summary": {"total_rows": 5, "by_next_action": {"draft": 5}},
            },
            # After draft: review boundary (should stop)
            {
                "current_phase": "draft",
                "status": "completed",
                "next_phase": "review",
                "action_required": None,
                "workbook_summary": {"total_rows": 5, "by_next_action": {"review": 5}},
            },
        ]

        phase_results = [
            {"success": True, "phase": "filter"},
            {"success": True, "phase": "enrich"},
            {"success": True, "phase": "draft"},
        ]

        with patch.object(loop, "load_status") as mock_load:
            with patch.object(loop, "run_single_phase") as mock_run:
                mock_load.side_effect = status_sequence
                mock_run.side_effect = phase_results

                exit_code = loop.run_reachout_loop("test_project")

                assert exit_code == 0
                assert mock_run.call_count == 3  # filter, enrich, draft

    def test_stops_at_send_without_confirm(self):
        """Test loop stops at send boundary without --confirm-send."""
        status = {
            "current_phase": "review",
            "status": "completed",
            "next_phase": "send",
            "action_required": None,
            "workbook_summary": {"total_rows": 5, "by_next_action": {"send": 5}},
        }

        with patch.object(loop, "load_status") as mock_load:
            mock_load.return_value = status

            exit_code = loop.run_reachout_loop("test_project", confirm_send=False)

            assert exit_code == 0

    def test_proceeds_to_send_with_confirm(self):
        """Test loop proceeds to send with --confirm-send."""
        status_sequence = [
            {
                "current_phase": "review",
                "status": "completed",
                "next_phase": "send",
                "action_required": None,
                "ready": True,
                "workbook_summary": {"total_rows": 5, "by_next_action": {"send": 5}},
            },
            {
                "current_phase": "send",
                "status": "completed",
                "next_phase": None,
                "action_required": None,
                "ready": True,
                "message": "All rows completed",
                "workbook_summary": {"total_rows": 5, "by_next_action": {"done": 5}},
            },
        ]

        with patch.object(loop, "load_status") as mock_load:
            with patch.object(loop, "run_single_phase") as mock_run:
                mock_load.side_effect = status_sequence
                mock_run.return_value = {"success": True, "phase": "send"}

                exit_code = loop.run_reachout_loop("test_project", confirm_send=True)

                assert exit_code == 0
                mock_run.assert_called_once_with("test_project", "send", dry_run=False)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
