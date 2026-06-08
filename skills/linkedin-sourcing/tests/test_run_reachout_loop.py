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

    def test_retries_failed_phase_when_flag_is_set(self):
        """Should continue when retry_failed is enabled."""
        status_result = {
            "action_required": None,
            "next_phase": "create_search",
            "current_phase": "create_search",
            "status": "failed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(
            status_result,
            retry_failed=True,
        )

        assert should_stop is False
        assert "retrying failed phase" in reason.lower()
        assert exit_code == 0

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

    def test_does_not_stop_at_review_phase(self):
        """Review phase is automated - loop should not stop."""
        status_result = {
            "action_required": None,
            "next_phase": "review",
            "current_phase": "draft",
            "status": "completed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is False
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

    def test_stops_at_confirm_search_boundary(self):
        """Should stop at confirm_search boundary for human filter verification."""
        status_result = {
            "action_required": None,
            "next_phase": "confirm_search",
            "current_phase": "create_search",
            "status": "completed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(status_result)

        assert should_stop is True
        assert "confirm_search" in reason.lower()
        assert "verify" in reason.lower() or "filter" in reason.lower()
        assert exit_code == 0

    def test_continues_at_confirm_search_boundary_with_confirm_flag(self):
        """Should continue past confirm_search boundary when --confirm-search flag is used."""
        status_result = {
            "action_required": None,
            "next_phase": "confirm_search",
            "current_phase": "create_search",
            "status": "completed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(
            status_result, confirm_search=True
        )

        assert should_stop is False
        assert "confirm_search" in reason.lower()
        assert exit_code == 0

    def test_confirm_search_flag_does_not_affect_other_boundaries(self):
        """--confirm-search flag should only affect confirm_search boundary."""
        # Should still stop at send boundary without --confirm-send
        status_result = {
            "action_required": None,
            "next_phase": "send",
            "current_phase": "review",
            "status": "completed",
        }

        should_stop, reason, exit_code = loop.check_stop_conditions(
            status_result, confirm_search=True, confirm_send=False
        )

        assert should_stop is True
        assert "send" in reason.lower()


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

    def test_continues_after_review_phase(self):
        """Review phase is automated - loop should continue on success."""
        phase_result = {
            "success": True,
            "phase": "review",
        }

        should_continue, message, exit_code = loop.classify_phase_result(phase_result)

        assert should_continue is True
        assert exit_code == 0

    def test_stops_on_browser_blocker(self):
        """Should stop with exit code 2 when an action_required blocker is present."""
        phase_result = {
            "success": False,
            "phase": "enrich",
            "blocked": True,
            "block_reason": "browser_blocked",
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


class TestFormatStopGuidance:
    """Tests for format_stop_guidance function."""

    def test_confirm_search_guidance_includes_copilot_query(self):
        """Confirm search guidance should include copilot query if available."""
        status_result = {
            "next_phase": "confirm_search",
            "loop_command": "python3 run_reachout_loop.py --project test",
            "create_search_summary": {
                "copilot_query": "Create a LinkedIn Recruiter candidate search for Software Engineer in San Francisco",
                "search_brief": "Search for Software Engineer candidates",
            },
        }

        guidance = loop.format_stop_guidance(status_result, "Stopped at boundary", 0)

        assert "--confirm-search" in guidance
        assert "Copilot query" in guidance

    def test_confirm_search_guidance_without_search_summary(self):
        """Confirm search guidance should work even without search summary."""
        status_result = {
            "next_phase": "confirm_search",
            "loop_command": "python3 run_reachout_loop.py --project test",
        }

        guidance = loop.format_stop_guidance(status_result, "Stopped at boundary", 0)

        assert "--confirm-search" in guidance
        assert "Create and verify search" in guidance

    def test_confirm_search_guidance_emphasizes_user_confirmation(self):
        """Confirm search guidance must emphasize USER confirmation, not agent self-approval."""
        status_result = {
            "next_phase": "confirm_search",
            "loop_command": "python3 run_reachout_loop.py --project test",
        }

        guidance = loop.format_stop_guidance(status_result, "Stopped at boundary", 0)

        # Should emphasize USER confirmation
        assert "USER" in guidance
        assert "USER CONFIRMATION REQUIRED" in guidance
        assert "USER must create" in guidance or "USER has created" in guidance
        # Should warn about using --confirm-search only after user verification
        assert "Only use --confirm-search after the USER has created" in guidance

    def test_confirm_search_guidance_shows_copilot_query(self):
        """Confirm search guidance should show copilot query if available."""
        status_result = {
            "next_phase": "confirm_search",
            "loop_command": "python3 run_reachout_loop.py --project test",
            "create_search_summary": {
                "copilot_query": "Create a LinkedIn Recruiter candidate search for Software Engineer",
                "search_brief": "Search for Software Engineer candidates",
            },
        }

        guidance = loop.format_stop_guidance(status_result, "Stopped at boundary", 0)

        # Should show copilot query
        assert "Copilot query" in guidance
        assert "Software Engineer" in guidance


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
                    "test_project", "filter", dry_run=False, reset_retry_count=False
                )
                assert should_continue is True
                assert exit_code == 0

    def test_runs_failed_phase_when_retry_flag_is_set(self):
        """Retry flag should let the loop rerun the failed phase."""
        with patch.object(loop, "load_status") as mock_load:
            with patch.object(loop, "run_single_phase") as mock_run:
                mock_load.return_value = {
                    "current_phase": "create_search",
                    "status": "failed",
                    "next_phase": "create_search",
                    "action_required": None,
                    "workbook_summary": {"total_rows": 0, "by_next_action": {}},
                }
                mock_run.return_value = {
                    "success": True,
                    "phase": "create_search",
                }

                should_continue, message, exit_code = loop.run_loop_iteration(
                    "test_project",
                    confirm_send=False,
                    dry_run=False,
                    retry_failed=True,
                )

                mock_run.assert_called_once_with(
                    "test_project", "create_search", dry_run=False, reset_retry_count=True
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

    def test_prints_guidance_after_phase_blocker(self, capsys):
        """Blocked phases should print loop-first guidance before stopping."""
        initial_status = {
            "current_phase": "bootstrap",
            "status": "completed",
            "next_phase": "create_search",
            "action_required": None,
            "workbook_summary": {"total_rows": 0, "by_next_action": {}},
        }
        refreshed_status = {
            "current_phase": "create_search",
            "status": "action_required",
            "next_phase": None,
            "action_required": {
                "code": "timeout",
                "summary": "Operation timed out - page may be loading slowly or stuck",
            },
            "loop_resume_guidance": {"resolve_now": "Check the Chrome window"},
            "loop_command": "python3 /tmp/run_reachout_loop.py --project test_project",
            "workbook_summary": {"total_rows": 0, "by_next_action": {}},
        }
        phase_result = {
            "success": False,
            "phase": "create_search",
            "state_after": {
                "action_required": {
                    "code": "timeout",
                    "summary": "Operation timed out - page may be loading slowly or stuck",
                }
            },
        }

        with patch.object(loop, "load_status") as mock_load:
            with patch.object(loop, "run_single_phase") as mock_run:
                mock_load.side_effect = [initial_status, refreshed_status]
                mock_run.return_value = phase_result

                should_continue, _message, exit_code = loop.run_loop_iteration(
                    "test_project", confirm_send=False, dry_run=False
                )

        output = capsys.readouterr().out
        assert should_continue is False
        assert exit_code == 2
        assert "Agent should resolve now:" in output
        assert "Then resume with:" in output
        assert "python3 /tmp/run_reachout_loop.py --project test_project" in output

    def test_prints_agent_actionable_guidance_for_create_search(self, capsys):
        """Create-search blockers should read as agent work, not user/manual work."""
        initial_status = {
            "current_phase": "bootstrap",
            "status": "completed",
            "next_phase": "create_search",
            "action_required": None,
            "workbook_summary": {"total_rows": 0, "by_next_action": {}},
        }
        refreshed_status = {
            "current_phase": "create_search",
            "status": "action_required",
            "next_phase": None,
            "action_required": {
                "code": "search_not_configured",
                "summary": "The Recruiter project needs a candidate search configured",
                "actor": "agent",
            },
            "loop_resume_guidance": {
                "actor": "agent",
                "resolve_now": "Open the Recruiter search page in Chrome and configure the candidate search using the provided search brief",
                "steps": [
                    "Open the Recruiter project search page in Chrome",
                    "Use the search brief provided in context.search_brief",
                ],
            },
            "loop_command": "python3 /tmp/run_reachout_loop.py --project test_project",
            "workbook_summary": {"total_rows": 0, "by_next_action": {}},
        }
        phase_result = {
            "success": False,
            "phase": "create_search",
            "state_after": {
                "action_required": {
                    "code": "search_not_configured",
                    "summary": "The Recruiter project needs a candidate search configured",
                    "actor": "agent",
                }
            },
        }

        with patch.object(loop, "load_status") as mock_load:
            with patch.object(loop, "run_single_phase") as mock_run:
                mock_load.side_effect = [initial_status, refreshed_status]
                mock_run.return_value = phase_result

                should_continue, _message, exit_code = loop.run_loop_iteration(
                    "test_project", confirm_send=False, dry_run=False
                )

        output = capsys.readouterr().out
        assert should_continue is False
        assert exit_code == 2
        assert "Agent should resolve now:" in output
        assert "Use the search brief provided in context.search_brief" in output
        assert "manual" not in output.lower()

    def test_prints_user_actionable_guidance_for_auth_blocker(self, capsys):
        """User-only blockers should be labeled explicitly so agents do not improvise."""
        status = {
            "current_phase": "extract",
            "status": "action_required",
            "next_phase": None,
            "action_required": {
                "code": "auth_required",
                "summary": "LinkedIn authentication required - not logged in to Recruiter",
                "actor": "user",
            },
            "loop_resume_guidance": {
                "actor": "user",
                "resolve_now": "Log in to LinkedIn Recruiter in the browser",
                "steps": ["Navigate to https://www.linkedin.com/talent/home in Chrome"],
            },
            "loop_command": "python3 /tmp/run_reachout_loop.py --project test_project",
            "workbook_summary": {"total_rows": 0, "by_next_action": {}},
        }

        with patch.object(loop, "load_status") as mock_load:
            mock_load.return_value = status

            should_continue, _message, exit_code = loop.run_loop_iteration(
                "test_project", confirm_send=False, dry_run=False
            )

        output = capsys.readouterr().out
        assert should_continue is False
        assert exit_code == 2
        assert "User must resolve now:" in output
        assert "Log in to LinkedIn Recruiter in the browser" in output


class TestRunReachoutLoop:
    """Tests for run_reachout_loop function."""

    def test_exits_cleanly_on_stop_condition(self):
        """Should exit cleanly when stop condition met."""
        with patch.object(loop, "run_loop_iteration") as mock_iter:
            mock_iter.return_value = (False, "Workflow complete", 0)

            exit_code = loop.run_reachout_loop("test_project")

            assert exit_code == 0

    def test_exits_with_code_2_on_browser_blocker(self):
        """Should exit with code 2 on an action_required blocker."""
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

    def test_full_workflow_to_send_boundary(self):
        """Test loop runs through phases until send boundary."""
        with patch.object(loop, "pre_flight_check") as mock_preflight:
            mock_preflight.return_value = (True, None)
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
                # After draft: review ready (automated)
                {
                    "current_phase": "draft",
                    "status": "completed",
                    "next_phase": "review",
                    "action_required": None,
                    "workbook_summary": {"total_rows": 5, "by_next_action": {"review": 5}},
                },
                # After review: send boundary (should stop)
                {
                    "current_phase": "review",
                    "status": "completed",
                    "next_phase": "send",
                    "action_required": None,
                    "workbook_summary": {"total_rows": 5, "by_next_action": {"send": 5}},
                },
            ]

            phase_results = [
                {"success": True, "phase": "filter"},
                {"success": True, "phase": "enrich"},
                {"success": True, "phase": "draft"},
                {"success": True, "phase": "review"},
            ]

            with patch.object(loop, "load_status") as mock_load:
                with patch.object(loop, "run_single_phase") as mock_run:
                    mock_load.side_effect = status_sequence
                    mock_run.side_effect = phase_results

                    exit_code = loop.run_reachout_loop("test_project")

                    assert exit_code == 0
                    assert mock_run.call_count == 4  # filter, enrich, draft, review

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
        with patch.object(loop, "pre_flight_check") as mock_preflight:
            mock_preflight.return_value = (True, None)
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
                    mock_run.assert_called_once_with("test_project", "send", dry_run=False, reset_retry_count=False)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
