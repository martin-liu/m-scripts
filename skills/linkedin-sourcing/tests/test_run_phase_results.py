#!/usr/bin/env python3
"""Tests for run_phase.py result handling (Sprint 3).

Tests that phase results are properly classified and state is updated correctly,
especially for action_required blockers vs generic failures.

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_run_phase_results.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_phase as rp


class TestCreateSearchResultHandling:
    """Tests for create_search phase result handling."""

    def test_preserves_structured_result_on_success(self):
        """Should preserve parsed JSON result on success."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"success": true, "next_phase": "extract", "search_brief": "test"}',
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_create_search_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is True
            assert result["next_phase"] == "extract"
            assert "parsed" in result
            assert result["parsed"]["search_brief"] == "test"

    def test_preserves_action_required_on_exit_code_2(self):
        """Should preserve action_required when exit code is 2."""
        action_required = {
            "code": "search_not_configured",
            "summary": "Search needs configuration",
            "steps": ["Open Recruiter", "Create search"],
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=2,
                stdout=f'{{"success": false, "action_required": {str(action_required).replace(chr(39), chr(34))}}}',
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_create_search_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is False
            assert result["blocked"] is True
            assert result["block_reason"] == "action_required"
            assert "action_required" in result

    def test_preserves_next_phase_on_failure(self):
        """Should preserve next_phase even on failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=2,
                stdout='{"success": false, "next_phase": "create_search"}',
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_create_search_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["next_phase"] == "create_search"


class TestEnrichResultHandling:
    """Tests for enrich phase result handling."""

    def test_success_on_exit_code_0(self):
        """Should report success when exit code is 0."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Enrichment complete",
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_enrich_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is True
            assert result["error"] is None

    def test_blocked_on_exit_code_2(self):
        """Should report blocked when exit code is 2 (browser blocker)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=2,
                stdout="Browser intervention required",
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_enrich_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is False
            assert result["blocked"] is True
            assert result["block_reason"] == "browser_blocked"
            assert "action required" in result["error"].lower()

    def test_failure_on_exit_code_1(self):
        """Should report failure when exit code is 1 (generic failure)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Some enrichments failed",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_enrich_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is False
            assert result.get("blocked") is None  # Not a blocker


class TestSendResultHandling:
    """Tests for send phase result handling."""

    def test_success_on_exit_code_0(self):
        """Should report success when exit code is 0."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Send complete",
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_send_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is True
            assert result["error"] is None

    def test_blocked_on_exit_code_2(self):
        """Should report blocked when exit code is 2 (browser state not clean)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=2,
                stdout="Browser state not clean",
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_send_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is False
            assert result["blocked"] is True
            assert result["block_reason"] == "browser_state_not_clean"
            assert "browser state" in result["error"].lower()

    def test_failure_on_exit_code_1(self):
        """Should report failure when exit code is 1 (some sends failed)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Some sends failed",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_send_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is False
            assert result.get("blocked") is None  # Not a blocker


class TestRunPhaseStateUpdates:
    """Tests for run_phase state update behavior."""

    def test_updates_state_to_action_required_on_blocker(self):
        """Should update state to action_required when phase is blocked."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    with patch("run_phase.PHASE_RUNNERS") as mock_runners:
                        mock_resolve.return_value = {
                            "success": True,
                            "config_path": Path("/tmp/test/config.sh"),
                            "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        }
                        mock_state.return_value = {"workflow_mode": "reachout"}

                        # Mock runner that returns blocked result
                        mock_runner = MagicMock()
                        mock_runner.return_value = {
                            "success": False,
                            "blocked": True,
                            "block_reason": "browser_blocked",
                            "action_required": {
                                "code": "auth_required",
                                "summary": "Login required",
                            },
                            "error": "Browser intervention required",
                        }
                        mock_runners.get.return_value = mock_runner

                        rp.run_phase("test_project", "enrich")

                        # Check that state was updated to action_required
                        call_args = mock_update.call_args_list
                        # Last call should have action_required
                        last_call = call_args[-1]
                        assert last_call[1]["status"] == "action_required"
                        assert last_call[1]["action_required"] is not None

    def test_updates_state_to_completed_on_success(self):
        """Should update state to completed when phase succeeds."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    with patch("run_phase.PHASE_RUNNERS") as mock_runners:
                        mock_resolve.return_value = {
                            "success": True,
                            "config_path": Path("/tmp/test/config.sh"),
                            "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        }
                        mock_state.return_value = {"workflow_mode": "reachout"}

                        # Mock runner that returns success
                        mock_runner = MagicMock()
                        mock_runner.return_value = {
                            "success": True,
                            "kept": 5,
                            "filtered": 2,
                        }
                        mock_runners.get.return_value = mock_runner

                        rp.run_phase("test_project", "filter")

                        # Check that state was updated to completed
                        call_args = mock_update.call_args_list
                        last_call = call_args[-1]
                        assert last_call[1]["status"] == "completed"

    def test_creates_action_required_when_not_present(self):
        """Should create action_required when blocked but none provided."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    with patch("run_phase.PHASE_RUNNERS") as mock_runners:
                        mock_resolve.return_value = {
                            "success": True,
                            "config_path": Path("/tmp/test/config.sh"),
                            "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        }
                        mock_state.return_value = {"workflow_mode": "reachout"}

                        # Mock runner that returns blocked without action_required
                        mock_runner = MagicMock()
                        mock_runner.return_value = {
                            "success": False,
                            "blocked": True,
                            "block_reason": "browser_blocked",
                            "error": "Browser intervention required",
                        }
                        mock_runners.get.return_value = mock_runner

                        rp.run_phase("test_project", "enrich")

                        # Check that action_required was created
                        call_args = mock_update.call_args_list
                        last_call = call_args[-1]
                        assert last_call[1]["status"] == "action_required"
                        assert (
                            last_call[1]["action_required"]["code"] == "browser_blocked"
                        )


class TestReviewPhaseHandling:
    """Tests for review phase as human stop boundary."""

    def test_review_phase_is_not_blocked(self):
        """Review phase should succeed but be treated as stop boundary by loop."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    mock_resolve.return_value = {
                        "success": True,
                        "config_path": Path("/tmp/test/config.sh"),
                        "workbook_path": Path("/tmp/test/workbook.xlsx"),
                    }
                    mock_state.return_value = {"workflow_mode": "reachout"}

                    result = rp.run_phase("test_project", "review")

                    assert result["success"] is True
                    assert "review" in result["phase_result"]["message"].lower()
                    assert "human" in result["phase_result"]["message"].lower()

    def test_review_phase_does_not_create_sticky_blocker(self):
        """Review phase should not set action_required to avoid sticky blocker."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    mock_resolve.return_value = {
                        "success": True,
                        "config_path": Path("/tmp/test/config.sh"),
                        "workbook_path": Path("/tmp/test/workbook.xlsx"),
                    }
                    mock_state.return_value = {"workflow_mode": "reachout"}

                    rp.run_phase("test_project", "review")

                    # Check that state was updated with completed status, not action_required
                    call_args = mock_update.call_args_list
                    last_call = call_args[-1]
                    assert last_call[1]["status"] == "completed"
                    assert last_call[1]["action_required"] is False


class TestActionRequiredClearing:
    """Tests for clearing stale action_required on retry/success."""

    def test_clears_action_required_when_starting_phase(self):
        """Should clear stale action_required when starting a phase (retry)."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    with patch("run_phase.PHASE_RUNNERS") as mock_runners:
                        mock_resolve.return_value = {
                            "success": True,
                            "config_path": Path("/tmp/test/config.sh"),
                            "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        }
                        mock_state.return_value = {"workflow_mode": "reachout"}

                        # Mock runner that returns success
                        mock_runner = MagicMock()
                        mock_runner.return_value = {"success": True, "kept": 5}
                        mock_runners.get.return_value = mock_runner

                        rp.run_phase("test_project", "filter")

                        # Check that running state update clears action_required
                        call_args = mock_update.call_args_list
                        # First call should be "running" state
                        first_call = call_args[0]
                        assert first_call[1]["status"] == "running"
                        assert first_call[1]["action_required"] is False

    def test_clears_action_required_on_success(self):
        """Should clear action_required when phase completes successfully."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    with patch("run_phase.PHASE_RUNNERS") as mock_runners:
                        mock_resolve.return_value = {
                            "success": True,
                            "config_path": Path("/tmp/test/config.sh"),
                            "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        }
                        mock_state.return_value = {"workflow_mode": "reachout"}

                        # Mock runner that returns success
                        mock_runner = MagicMock()
                        mock_runner.return_value = {"success": True, "kept": 5}
                        mock_runners.get.return_value = mock_runner

                        rp.run_phase("test_project", "filter")

                        # Check that completed state update clears action_required
                        call_args = mock_update.call_args_list
                        last_call = call_args[-1]
                        assert last_call[1]["status"] == "completed"
                        assert last_call[1]["action_required"] is False
                        assert last_call[1]["last_error"] is False


class TestExtractPhaseBlockerPreservation:
    """Tests for extraction phase preserving blockers."""

    def test_preserves_action_required_from_extraction(self):
        """Should preserve action_required from extraction subprocess."""
        action_required = {
            "code": "search_not_configured",
            "summary": "Recruiter project needs search configuration",
            "steps": ["Create a search in Recruiter"],
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout=f'{{"success": false, "message": "Extraction failed", "failure_code": "search_not_configured", "action_required": {str(action_required).replace(chr(39), chr(34))}}}',
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_extract_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is False
            assert result["blocked"] is True
            assert result["action_required"] == action_required
            assert result["failure_code"] == "search_not_configured"

    def test_preserves_failure_code_from_extraction(self):
        """Should preserve failure_code from extraction subprocess."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout='{"success": false, "message": "Browser not ready", "failure_code": "wrong_page"}',
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_extract_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["success"] is False
            assert result["failure_code"] == "wrong_page"

    def test_treats_action_required_as_blocked(self):
        """Should treat extraction with action_required as blocked."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout='{"success": false, "message": "Auth required", "failure_code": "auth_required", "action_required": {"code": "auth_required", "summary": "Login needed"}}',
                stderr="",
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "test_project"

            result = rp.run_extract_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            assert result["blocked"] is True
            assert result["block_reason"] == "auth_required"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
