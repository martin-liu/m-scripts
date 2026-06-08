#!/usr/bin/env python3
"""Tests for run_phase.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_run_phase.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_phase as rp


class TestPhaseRunnersRegistry:
    """Tests for PHASE_RUNNERS registry."""

    def test_all_phases_have_runners(self):
        """Every runnable phase must have a runner registered."""
        from phase_registry import REACHOUT_PHASES, REVIEW_PHASES

        # Human stop boundaries are handled inline in run_phase(), not via registry
        human_phases = {"review", "confirm_search"}
        # Bootstrap is a pre-loop entrypoint, not a runnable loop phase
        excluded_phases = {"bootstrap"}

        all_phases = set(REACHOUT_PHASES) | set(REVIEW_PHASES)
        expected_runnable = all_phases - human_phases - excluded_phases

        for phase in expected_runnable:
            assert phase in rp.PHASE_RUNNERS, (
                f"Phase '{phase}' missing from PHASE_RUNNERS"
            )

    def test_no_scan_phase_in_runners(self):
        """Scan phase should not have a runner (no implementation)."""
        assert "scan" not in rp.PHASE_RUNNERS


class TestCLIContracts:
    """Tests that phase runners use correct CLI contracts."""

    def test_main_does_not_exit_when_valid_args_provided(self, capsys):
        """CLI should not print usage or exit early when valid args are provided."""
        with patch.object(sys, "argv", ["run_phase.py", "proj-1", "create_search"]):
            with patch("run_phase.run_phase") as mock_run_phase:
                mock_run_phase.return_value = {"success": True, "phase": "create_search"}

                rp.main()

        captured = capsys.readouterr()
        assert "Usage:" not in captured.err
        mock_run_phase.assert_called_once_with("proj-1", "create_search", False)

    def test_create_search_uses_project_flag(self):
        """create_search phase should use --project flag."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"success": true}', stderr=""
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"

            rp.run_create_search_phase(
                project_dir, config_path, workbook_path, "test_project"
            )

            # Check that --project was used, not --config
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert "--project" in cmd
            assert "--config" not in cmd

    def test_enrich_uses_project_flag(self):
        """enrich phase should use --project flag."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"success": true}', stderr=""
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"

            rp.run_enrich_phase(project_dir, config_path, workbook_path, "test_project")

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert "--project" in cmd
            assert "--config" not in cmd

    def test_send_uses_project_flag(self):
        """send phase should use --project flag."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"success": true}', stderr=""
            )

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"

            rp.run_send_phase(project_dir, config_path, workbook_path, "test_project")

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            assert "--project" in cmd
            assert "--config" not in cmd


class TestProjectRefBugFix:
    """Regression tests for project-ref bug where project_dir.name was used instead of local_project_id."""

    def test_create_search_uses_local_project_id_not_folder_name(self):
        """create_search phase should use local_project_id, not project_dir.name.

        This is a regression test for the bug where folders named {PROJECT_ID}_{slug}
        would pass the wrong value to subprocess.
        """
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"success": true}', stderr=""
            )

            # Folder name differs from PROJECT_ID (e.g., 12345_my_project vs 12345)
            project_dir = Path("/tmp/12345_my_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "12345"  # The canonical PROJECT_ID from config

            rp.run_create_search_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            project_idx = cmd.index("--project") + 1
            assert cmd[project_idx] == "12345", (
                f"Expected local_project_id '12345', got '{cmd[project_idx]}'"
            )

    def test_enrich_uses_local_project_id_not_folder_name(self):
        """enrich phase should use local_project_id, not project_dir.name."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"success": true}', stderr=""
            )

            project_dir = Path("/tmp/12345_my_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "12345"

            rp.run_enrich_phase(
                project_dir, config_path, workbook_path, local_project_id
            )

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            project_idx = cmd.index("--project") + 1
            assert cmd[project_idx] == "12345"

    def test_send_uses_local_project_id_not_folder_name(self):
        """send phase should use local_project_id, not project_dir.name."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"success": true}', stderr=""
            )

            project_dir = Path("/tmp/12345_my_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"
            local_project_id = "12345"

            rp.run_send_phase(project_dir, config_path, workbook_path, local_project_id)

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            project_idx = cmd.index("--project") + 1
            assert cmd[project_idx] == "12345"

    def test_run_phase_passes_local_project_id_to_runner(self):
        """run_phase should extract local_project_id from resolution and pass to runner."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.update_project_state") as mock_update:
                with patch("run_phase.load_project_state") as mock_state:
                    mock_resolve.return_value = {
                        "success": True,
                        "config_path": Path("/tmp/12345_my_project/config.sh"),
                        "workbook_path": Path("/tmp/12345_my_project/workbook.xlsx"),
                        "local_project_id": "12345",  # Canonical ID from config
                    }
                    mock_state.return_value = {"workflow_mode": "reachout"}
                    mock_update.return_value = {}

                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(
                            returncode=0, stdout='{"success": true}', stderr=""
                        )

                        rp.run_phase("12345_my_project", "enrich")

                        # Verify the subprocess was called with canonical ID
                        call_args = mock_run.call_args
                        cmd = call_args[0][0]
                        project_idx = cmd.index("--project") + 1
                        assert cmd[project_idx] == "12345", (
                            f"Expected canonical PROJECT_ID '12345', got '{cmd[project_idx]}'"
                        )


class TestRunPhaseIntegration:
    """Integration tests for run_phase module."""

    def test_invalid_phase_rejected(self):
        """Invalid phase should be rejected before running."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            mock_resolve.return_value = {
                "success": True,
                "config_path": Path("/tmp/test/config.sh"),
                "workbook_path": Path("/tmp/test/workbook.xlsx"),
            }

            result = rp.run_phase("test_project", "invalid_phase")

            assert result["success"] is False
            assert "Invalid phase" in result.get("error", "")

    def test_scan_phase_not_valid(self):
        """Scan phase should not be valid for running."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                mock_resolve.return_value = {
                    "success": True,
                    "config_path": Path("/tmp/test/config.sh"),
                    "workbook_path": Path("/tmp/test/workbook.xlsx"),
                }
                mock_state.return_value = {"workflow_mode": "review"}

                result = rp.run_phase("test_project", "scan")

                assert result["success"] is False
                assert "Invalid phase" in result.get("error", "")

    def test_bootstrap_phase_rejected(self):
        """Bootstrap phase should be rejected as it's a pre-loop entrypoint."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            mock_resolve.return_value = {
                "success": True,
                "config_path": Path("/tmp/test/config.sh"),
                "workbook_path": Path("/tmp/test/workbook.xlsx"),
            }

            result = rp.run_phase("test_project", "bootstrap")

            assert result["success"] is False
            assert (
                "not runnable" in result.get("error", "").lower()
                or "bootstrap" in result.get("error", "").lower()
            )


class TestConfirmSearchPhase:
    """Tests for confirm_search phase behavior."""

    def test_confirm_search_does_not_persist_action_required(self):
        """Confirm search phase should NOT persist a blocking action_required.

        This is critical for resumability: confirm_search should be a non-sticky
        boundary that allows the loop to proceed with --confirm-search flag.
        """
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    mock_resolve.return_value = {
                        "success": True,
                        "config_path": Path("/tmp/test/config.sh"),
                        "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        "local_project_id": "test_project",
                    }
                    mock_state.return_value = {"workflow_mode": "reachout"}
                    mock_update.return_value = {"current_phase": "confirm_search", "status": "completed"}

                    result = rp.run_phase("test_project", "confirm_search")

                    assert result["success"] is True
                    # Should have called update_project_state with action_required=False
                    # to clear any stale blocker
                    mock_update.assert_called()
                    call_kwargs = mock_update.call_args.kwargs
                    assert call_kwargs.get("action_required") is False
                    assert call_kwargs.get("status") == "completed"

    def test_confirm_search_returns_extract_next_phase(self):
        """Confirm search phase should indicate extract is the next phase."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    mock_resolve.return_value = {
                        "success": True,
                        "config_path": Path("/tmp/test/config.sh"),
                        "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        "local_project_id": "test_project",
                    }
                    mock_state.return_value = {"workflow_mode": "reachout"}
                    mock_update.return_value = {"current_phase": "confirm_search", "status": "completed"}

                    result = rp.run_phase("test_project", "confirm_search")

                    assert result["success"] is True
                    assert result["phase_result"]["next_phase"] == "extract"


class TestCreateSearchSummaryPreservation:
    """Regression tests for preserving create_search inspection summaries."""

    def test_create_search_does_not_clobber_inner_summary(self):
        """run_phase should preserve the summary already written by run_create_search."""
        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    mock_resolve.return_value = {
                        "success": True,
                        "config_path": Path("/tmp/test/config.sh"),
                        "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        "local_project_id": "test_project",
                    }
                    mock_state.return_value = {"workflow_mode": "reachout"}
                    mock_update.return_value = {
                        "current_phase": "create_search",
                        "status": "completed",
                    }

                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(
                            returncode=0,
                            stdout='{"success": true, "phase": "create_search", "next_phase": "confirm_search", "message": "Recruiter search has visible candidates - awaiting confirmation"}',
                            stderr="",
                        )

                        result = rp.run_phase("test_project", "create_search")

                    assert result["success"] is True
                    assert mock_update.call_count == 2
                    completed_call_kwargs = mock_update.call_args_list[1].kwargs
                    assert completed_call_kwargs["current_phase"] == "create_search"
                    assert completed_call_kwargs["status"] == "completed"
                    assert completed_call_kwargs.get("last_result_summary") is None


class TestTimeoutHandling:
    """Tests for timeout recovery in phase execution."""

    def test_subprocess_timeout_returns_retryable_error(self):
        """Timeout should return failure_code='timeout' and can_retry=True."""
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["test"], timeout=300)

            result = rp._run_subprocess_with_json_output(
                ["test"], timeout=300, success_code=0
            )

            assert result["success"] is False
            assert result["failure_code"] == "timeout"
            assert result["can_retry"] is True
            assert "Timeout after 300 seconds" in result["error"]

    def test_create_search_timeout_preserves_failure_code(self):
        """create_search phase should preserve timeout failure_code for retry."""
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["test"], timeout=300)

            project_dir = Path("/tmp/test_project")
            config_path = project_dir / "config.sh"
            workbook_path = project_dir / "workbook.xlsx"

            result = rp.run_create_search_phase(
                project_dir, config_path, workbook_path, "test_project"
            )

            assert result["success"] is False
            assert result["failure_code"] == "timeout"
            assert result["can_retry"] is True

    def test_run_phase_preserves_timeout_failure_code(self):
        """run_phase should preserve timeout failure_code in result."""
        import subprocess

        with patch("run_phase.resolve_project_ref") as mock_resolve:
            with patch("run_phase.load_project_state") as mock_state:
                with patch("run_phase.update_project_state") as mock_update:
                    mock_resolve.return_value = {
                        "success": True,
                        "config_path": Path("/tmp/test/config.sh"),
                        "workbook_path": Path("/tmp/test/workbook.xlsx"),
                        "local_project_id": "test_project",
                    }
                    mock_state.return_value = {"workflow_mode": "reachout"}
                    mock_update.return_value = {}

                    with patch("subprocess.run") as mock_run:
                        mock_run.side_effect = subprocess.TimeoutExpired(
                            cmd=["test"], timeout=300
                        )

                        result = rp.run_phase("test_project", "create_search")

                        assert result["success"] is False
                        # Retry layer converts exhausted timeouts to retry_exhausted
                        assert result["failure_code"] == "retry_exhausted"
                        assert result["can_retry"] is True
                        # State should be "failed" to allow retry, not "action_required"
                        failed_calls = [
                            c for c in mock_update.call_args_list
                            if c.kwargs.get("status") == "failed"
                        ]
                        assert len(failed_calls) >= 1


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
