#!/usr/bin/env python3
"""Tests for project_state.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_project_state.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import project_state as ps


class TestCreateInitialState:
    """Tests for create_initial_state function."""

    def test_creates_reachout_state_by_default(self):
        """Should create reachout workflow state by default."""
        state = ps.create_initial_state("12345")

        assert state["version"] == ps.STATE_VERSION
        assert state["project_id"] == "12345"
        assert state["workflow_mode"] == "reachout"
        assert state["current_phase"] == "bootstrap"
        assert state["status"] == "initialized"
        # Sprint 2: workflow_phases and next_phase not persisted
        assert "workflow_phases" not in state
        assert "next_phase" not in state

    def test_creates_review_state_when_requested(self):
        """Should create review workflow state when specified."""
        state = ps.create_initial_state("12345", workflow_mode="review")

        assert state["workflow_mode"] == "review"
        # Sprint 2: workflow_phases not persisted
        assert "workflow_phases" not in state

    def test_simplified_state_structure(self):
        """Should create simplified state without computed fields."""
        state = ps.create_initial_state("12345", current_phase="send")

        assert state["current_phase"] == "send"
        # Sprint 2: next_phase not persisted (computed at runtime)
        assert "next_phase" not in state
        # Required checkpoint fields
        assert "project_id" in state
        assert "current_phase" in state
        assert "status" in state
        assert "updated_at" in state


class TestGetNextPhase:
    """Tests for _get_next_phase helper (deprecated, kept for compatibility)."""

    def test_returns_next_phase_in_sequence(self):
        """Should return the next phase in workflow sequence."""
        phases = ["bootstrap", "create_search", "extract", "filter"]

        assert ps._get_next_phase("bootstrap", phases) == "create_search"
        assert ps._get_next_phase("create_search", phases) == "extract"
        assert ps._get_next_phase("extract", phases) == "filter"

    def test_returns_none_at_end(self):
        """Should return None when at final phase."""
        phases = ["bootstrap", "create_search"]

        assert ps._get_next_phase("create_search", phases) is None

    def test_returns_none_for_unknown_phase(self):
        """Should return None for phase not in workflow."""
        phases = ["bootstrap", "create_search"]

        assert ps._get_next_phase("unknown", phases) is None


class TestLoadProjectState:
    """Tests for load_project_state function."""

    def test_loads_valid_state(self, tmp_path):
        """Should load valid state file."""
        state_file = tmp_path / "project_state.json"
        state_data = {
            "version": ps.STATE_VERSION,
            "project_id": "12345",
            "workflow_mode": "reachout",
            "current_phase": "extract",
            "status": "running",
        }
        state_file.write_text(json.dumps(state_data))

        result = ps.load_project_state(tmp_path)

        assert result is not None
        assert result["project_id"] == "12345"
        assert result["current_phase"] == "extract"

    def test_strips_legacy_fields_on_load(self, tmp_path):
        """Should strip legacy workflow_phases and next_phase on load."""
        state_file = tmp_path / "project_state.json"
        state_data = {
            "version": 1,  # Old version with legacy fields
            "project_id": "12345",
            "workflow_mode": "reachout",
            "current_phase": "extract",
            "status": "running",
            "workflow_phases": ["bootstrap", "extract"],  # Legacy
            "next_phase": "filter",  # Legacy
        }
        state_file.write_text(json.dumps(state_data))

        result = ps.load_project_state(tmp_path)

        # Sprint 2: Legacy fields should be stripped
        assert "workflow_phases" not in result
        assert "next_phase" not in result

    def test_returns_none_for_missing_file(self, tmp_path):
        """Should return None when state file doesn't exist."""
        result = ps.load_project_state(tmp_path)

        assert result is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        """Should return None for invalid JSON."""
        state_file = tmp_path / "project_state.json"
        state_file.write_text("not valid json")

        result = ps.load_project_state(tmp_path)

        assert result is None

    def test_returns_none_for_missing_required_fields(self, tmp_path):
        """Should return None when required fields are missing."""
        state_file = tmp_path / "project_state.json"
        state_file.write_text(json.dumps({"version": ps.STATE_VERSION}))

        result = ps.load_project_state(tmp_path)

        assert result is None


class TestSaveProjectState:
    """Tests for save_project_state function."""

    def test_saves_state_to_file(self, tmp_path):
        """Should save state to project_state.json."""
        state = ps.create_initial_state("12345")

        result = ps.save_project_state(tmp_path, state)

        assert result is True
        state_file = tmp_path / "project_state.json"
        assert state_file.exists()

        loaded = json.loads(state_file.read_text())
        assert loaded["project_id"] == "12345"

    def test_strips_computed_fields_on_save(self, tmp_path):
        """Should strip computed fields (workflow_phases, next_phase) on save."""
        state = ps.create_initial_state("12345")
        # Add legacy fields that might have been added externally
        state["workflow_phases"] = ["bootstrap", "extract"]
        state["next_phase"] = "filter"

        ps.save_project_state(tmp_path, state)

        state_file = tmp_path / "project_state.json"
        loaded = json.loads(state_file.read_text())

        # Sprint 2: Computed fields should not be persisted
        assert "workflow_phases" not in loaded
        assert "next_phase" not in loaded

    def test_updates_timestamp(self, tmp_path):
        """Should update the updated_at timestamp."""
        state = ps.create_initial_state("12345")
        original_timestamp = state["updated_at"]

        # Small delay to ensure timestamp changes
        import time

        time.sleep(1.1)

        ps.save_project_state(tmp_path, state)

        state_file = tmp_path / "project_state.json"
        loaded = json.loads(state_file.read_text())
        assert loaded["updated_at"] != original_timestamp

    def test_creates_parent_directories(self, tmp_path):
        """Should create parent directories if needed."""
        nested_dir = tmp_path / "nested" / "project"
        state = ps.create_initial_state("12345")

        result = ps.save_project_state(nested_dir, state)

        assert result is True
        assert (nested_dir / "project_state.json").exists()

    def test_atomic_write(self, tmp_path):
        """Should use atomic write (temp file + rename)."""
        state = ps.create_initial_state("12345")

        ps.save_project_state(tmp_path, state)

        # Temp file should not exist after successful write
        temp_file = tmp_path / "project_state.tmp"
        assert not temp_file.exists()


class TestUpdateProjectState:
    """Tests for update_project_state function."""

    def test_creates_new_state_if_none_exists(self, tmp_path):
        """Should create new state if no existing state."""
        # Create config.sh for project_id extraction
        config_file = tmp_path / "config.sh"
        config_file.write_text('PROJECT_ID="67890"\n')

        result = ps.update_project_state(
            tmp_path,
            current_phase="extract",
            status="running",
        )

        assert result["project_id"] == "67890"
        assert result["current_phase"] == "extract"
        assert result["status"] == "running"

    def test_updates_existing_state(self, tmp_path):
        """Should update existing state file."""
        # Create initial state
        initial_state = ps.create_initial_state("12345")
        ps.save_project_state(tmp_path, initial_state)

        result = ps.update_project_state(
            tmp_path,
            current_phase="filter",
            status="completed",
        )

        assert result["current_phase"] == "filter"
        assert result["status"] == "completed"
        # Sprint 2: next_phase not persisted
        assert "next_phase" not in result

    def test_clears_action_required_with_false(self, tmp_path):
        """Should clear action_required when passed False."""
        initial_state = ps.create_initial_state("12345")
        initial_state["action_required"] = {"code": "test", "summary": "Test"}
        ps.save_project_state(tmp_path, initial_state)

        result = ps.update_project_state(
            tmp_path,
            action_required=False,
        )

        assert result["action_required"] is None

    def test_clears_last_error_with_false(self, tmp_path):
        """Should clear last_error when passed False."""
        initial_state = ps.create_initial_state("12345")
        initial_state["last_error"] = "Some error"
        ps.save_project_state(tmp_path, initial_state)

        result = ps.update_project_state(
            tmp_path,
            last_error=False,
        )

        assert result["last_error"] is None

    def test_sets_action_required_dict(self, tmp_path):
        """Should set action_required to provided dict."""
        action_req = {
            "code": "browser_unavailable",
            "summary": "Chrome not running",
            "steps": ["Start Chrome"],
        }

        result = ps.update_project_state(
            tmp_path,
            current_phase="create_search",
            status="action_required",
            action_required=action_req,
        )

        assert result["action_required"] == action_req

    def test_does_not_auto_compute_next_phase(self, tmp_path):
        """Should not auto-compute next_phase (Sprint 2 simplification)."""
        # Create config.sh for project_id extraction
        config_file = tmp_path / "config.sh"
        config_file.write_text('PROJECT_ID="12345"\n')

        result = ps.update_project_state(
            tmp_path,
            current_phase="bootstrap",
        )

        # Sprint 2: next_phase not persisted
        assert "next_phase" not in result

    def test_accepts_project_id_parameter(self, tmp_path):
        """Should accept project_id parameter when creating new state.

        Regression test: bootstrap_project.py calls update_project_state with
        project_id parameter, which must be accepted and used.
        """
        result = ps.update_project_state(
            tmp_path,
            project_id="bootstrap_123",
            workflow_mode="reachout",
            current_phase="bootstrap",
            status="completed",
        )

        assert result["project_id"] == "bootstrap_123"
        assert result["workflow_mode"] == "reachout"
        assert result["current_phase"] == "bootstrap"
        assert result["status"] == "completed"

        # Verify state was saved to file
        state_file = tmp_path / "project_state.json"
        assert state_file.exists()
        loaded = json.loads(state_file.read_text())
        assert loaded["project_id"] == "bootstrap_123"

    def test_project_id_parameter_takes_precedence_over_config(self, tmp_path):
        """project_id parameter should take precedence over config.sh extraction."""
        # Create config.sh with different project_id
        config_file = tmp_path / "config.sh"
        config_file.write_text('PROJECT_ID="from_config"\n')

        result = ps.update_project_state(
            tmp_path,
            project_id="from_parameter",
            current_phase="bootstrap",
        )

        # Parameter should win over config extraction
        assert result["project_id"] == "from_parameter"

    def test_falls_back_to_config_when_no_project_id_parameter(self, tmp_path):
        """Should fall back to config.sh extraction when no project_id parameter."""
        config_file = tmp_path / "config.sh"
        config_file.write_text('PROJECT_ID="from_config"\n')

        result = ps.update_project_state(
            tmp_path,
            current_phase="bootstrap",
        )

        assert result["project_id"] == "from_config"


class TestExtractProjectIdFromConfig:
    """Tests for _extract_project_id_from_config helper."""

    def test_extracts_from_double_quoted_value(self, tmp_path):
        """Should extract PROJECT_ID from double-quoted config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text('PROJECT_ID="12345"\n')

        result = ps._extract_project_id_from_config(tmp_path)

        assert result == "12345"

    def test_extracts_from_single_quoted_value(self, tmp_path):
        """Should extract PROJECT_ID from single-quoted config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID='12345'\n")

        result = ps._extract_project_id_from_config(tmp_path)

        assert result == "12345"

    def test_extracts_from_unquoted_value(self, tmp_path):
        """Should extract PROJECT_ID from unquoted config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID=12345\n")

        result = ps._extract_project_id_from_config(tmp_path)

        assert result == "12345"

    def test_returns_none_for_missing_config(self, tmp_path):
        """Should return None when config.sh doesn't exist."""
        result = ps._extract_project_id_from_config(tmp_path)

        assert result is None

    def test_returns_none_for_missing_project_id(self, tmp_path):
        """Should return None when PROJECT_ID not in config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text('POSITION_TITLE="Engineer"\n')

        result = ps._extract_project_id_from_config(tmp_path)

        assert result is None


class TestGetProjectStateSummary:
    """Tests for get_project_state_summary function."""

    def test_returns_summary_for_existing_state(self, tmp_path):
        """Should return summary for existing state."""
        state = ps.create_initial_state("12345", current_phase="extract")
        ps.save_project_state(tmp_path, state)

        summary = ps.get_project_state_summary(tmp_path)

        assert summary["exists"] is True
        assert summary["project_id"] == "12345"
        assert summary["current_phase"] == "extract"
        # Sprint 2: next_phase not in summary
        assert "next_phase" not in summary

    def test_returns_not_exists_for_missing_state(self, tmp_path):
        """Should indicate state doesn't exist."""
        summary = ps.get_project_state_summary(tmp_path)

        assert summary["exists"] is False
        assert summary["project_id"] is None

    def test_indicates_action_required(self, tmp_path):
        """Should indicate when action is required."""
        state = ps.create_initial_state("12345")
        state["action_required"] = {"code": "test"}
        ps.save_project_state(tmp_path, state)

        summary = ps.get_project_state_summary(tmp_path)

        assert summary["action_required"] is True


class TestGetStatePath:
    """Tests for get_state_path function."""

    def test_returns_correct_path(self, tmp_path):
        """Should return path to project_state.json."""
        result = ps.get_state_path(tmp_path)

        assert result == tmp_path / "project_state.json"

    def test_handles_string_path(self):
        """Should handle string path input."""
        result = ps.get_state_path("/some/path")

        assert result == Path("/some/path") / "project_state.json"


class TestSimplifiedStateStructure:
    """Tests for Sprint 2 simplified state structure."""

    def test_state_has_only_checkpoint_fields(self, tmp_path):
        """State should only contain checkpoint fields, not workflow metadata."""
        state = ps.create_initial_state(
            "test_project",
            workflow_mode="reachout",
            current_phase="filter",
            status="completed",
        )
        ps.save_project_state(tmp_path, state)

        # Load raw file and verify structure
        state_file = tmp_path / "project_state.json"
        raw = json.loads(state_file.read_text())

        # Required checkpoint fields
        assert "version" in raw
        assert "project_id" in raw
        assert "workflow_mode" in raw
        assert "current_phase" in raw
        assert "status" in raw
        assert "action_required" in raw
        assert "updated_at" in raw
        assert "last_result_summary" in raw
        assert "last_error" in raw

        # Should NOT have workflow metadata (computed at runtime)
        assert "workflow_phases" not in raw
        assert "next_phase" not in raw

    def test_legacy_constants_still_available(self):
        """Legacy constants should still be available for compatibility."""
        # These constants are kept for backward compatibility
        assert hasattr(ps, "REACHOUT_WORKFLOW_PHASES")
        assert hasattr(ps, "REVIEW_WORKFLOW_PHASES")
        assert "bootstrap" in ps.REACHOUT_WORKFLOW_PHASES
        assert "send" in ps.REACHOUT_WORKFLOW_PHASES


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
