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

        # Human-only phases don't need runners
        human_phases = {"review"}
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


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
