#!/usr/bin/env python3
"""Tests for run_filter.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_run_filter.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_filter as rf
from excel_utils import create as create_workbook, update as update_row


class TestRunFilter:
    """Tests for run_filter function."""

    def create_test_workbook(self, tmp_path, rows_data):
        """Helper to create a test workbook with candidate data."""
        from excel_utils import create, append

        wb_path = tmp_path / "workbook.xlsx"
        create(str(wb_path))

        for row_data in rows_data:
            append(str(wb_path), row_data)

        return wb_path

    def test_filters_candidates_by_title(self, tmp_path):
        """Should filter candidates based on EXCLUDE_TITLES."""
        # Create config
        config_path = tmp_path / "config.sh"
        config_path.write_text('EXCLUDE_TITLES="Manager,Director"\nPROJECT_ID="test"')

        # Create workbook with candidates
        rows = [
            {
                "name": "John",
                "title": "Software Engineer",
                "status": "Extracted",
                "next_action": "filter",
            },
            {
                "name": "Jane",
                "title": "Engineering Manager",
                "status": "Extracted",
                "next_action": "filter",
            },
            {
                "name": "Bob",
                "title": "Senior Director",
                "status": "Extracted",
                "next_action": "filter",
            },
        ]
        workbook_path = self.create_test_workbook(tmp_path, rows)

        result = rf.run_filter(tmp_path, config_path, workbook_path)

        assert result["success"] is True
        assert result["kept"] == 1
        assert result["filtered"] == 2
        assert result["target_phase"] == "enrich"

    def test_routes_to_draft_when_no_enrichment(self, tmp_path):
        """Should route to draft when use_enrichment=False."""
        config_path = tmp_path / "config.sh"
        config_path.write_text('EXCLUDE_TITLES="Manager"\nPROJECT_ID="test"')

        rows = [
            {
                "name": "John",
                "title": "Engineer",
                "status": "Extracted",
                "next_action": "filter",
            },
        ]
        workbook_path = self.create_test_workbook(tmp_path, rows)

        result = rf.run_filter(
            tmp_path, config_path, workbook_path, use_enrichment=False
        )

        assert result["success"] is True
        assert result["target_phase"] == "draft"

    def test_returns_error_for_missing_config(self, tmp_path):
        """Should return error when config file is missing."""
        config_path = tmp_path / "nonexistent.sh"
        workbook_path = tmp_path / "workbook.xlsx"
        create_workbook(str(workbook_path))

        result = rf.run_filter(tmp_path, config_path, workbook_path)

        assert result["success"] is False
        assert "config" in result["error"].lower()

    def test_returns_error_for_missing_workbook(self, tmp_path):
        """Should return error when workbook is missing."""
        config_path = tmp_path / "config.sh"
        config_path.write_text('PROJECT_ID="test"')
        workbook_path = tmp_path / "nonexistent.xlsx"

        result = rf.run_filter(tmp_path, config_path, workbook_path)

        assert result["success"] is False
        assert "workbook" in result["error"].lower()

    def test_updates_project_state_on_success(self, tmp_path):
        """Should update project state after successful filter."""
        from project_state import (
            load_project_state,
            create_initial_state,
            save_project_state,
        )

        # Setup
        config_path = tmp_path / "config.sh"
        config_path.write_text('EXCLUDE_TITLES="Manager"\nPROJECT_ID="test"')

        rows = [
            {
                "name": "John",
                "title": "Engineer",
                "status": "Extracted",
                "next_action": "filter",
            }
        ]
        workbook_path = self.create_test_workbook(tmp_path, rows)

        # Create initial state
        state = create_initial_state(
            "test", current_phase="extract", status="completed"
        )
        save_project_state(tmp_path, state)

        # Run filter
        result = rf.run_filter(tmp_path, config_path, workbook_path)

        # Verify state updated
        assert result["success"] is True
        updated_state = load_project_state(tmp_path)
        assert updated_state["current_phase"] == "filter"
        assert updated_state["status"] == "completed"

    def test_updates_project_state_on_failure(self, tmp_path):
        """Should update project state after failed filter."""
        from project_state import (
            load_project_state,
            create_initial_state,
            save_project_state,
        )

        # Setup with missing workbook to cause failure
        config_path = tmp_path / "config.sh"
        config_path.write_text('PROJECT_ID="test"')
        workbook_path = tmp_path / "nonexistent.xlsx"

        # Create initial state
        state = create_initial_state("test")
        save_project_state(tmp_path, state)

        # Run filter (will fail)
        result = rf.run_filter(tmp_path, config_path, workbook_path)

        # Verify state updated with failure
        assert result["success"] is False
        updated_state = load_project_state(tmp_path)
        assert updated_state["current_phase"] == "filter"
        assert updated_state["status"] == "failed"
        assert updated_state["last_error"] is not None

    def test_skips_already_processed_rows(self, tmp_path):
        """Should skip rows that don't need filtering."""
        config_path = tmp_path / "config.sh"
        config_path.write_text('EXCLUDE_TITLES="Manager"\nPROJECT_ID="test"')

        rows = [
            {
                "name": "John",
                "title": "Engineer",
                "status": "Extracted",
                "next_action": "filter",
            },
            {
                "name": "Jane",
                "title": "Engineer",
                "status": "Drafted",
                "next_action": "review",
            },  # Already drafted
        ]
        workbook_path = self.create_test_workbook(tmp_path, rows)

        result = rf.run_filter(tmp_path, config_path, workbook_path)

        assert result["success"] is True
        assert result["kept"] == 1
        assert result["skipped"] == 1


class TestRunFilterIntegration:
    """Integration tests for run_filter module."""

    def test_end_to_end_filter_workflow(self, tmp_path):
        """Test complete filter workflow with project resolution."""
        from project_ref_utils import resolve_project_ref
        from project_state import create_initial_state, save_project_state
        from excel_utils import create, append

        # Setup project structure
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "test_filter"
        project_dir.mkdir(parents=True)

        config_path = project_dir / "config.sh"
        config_path.write_text('PROJECT_ID="test_filter"\nEXCLUDE_TITLES="VP,Director"')

        # Create workbook
        wb_path = project_dir / "workbook.xlsx"
        create(str(wb_path))
        append(
            str(wb_path),
            {
                "name": "Alice",
                "title": "Engineer",
                "status": "Extracted",
                "next_action": "filter",
            },
        )
        append(
            str(wb_path),
            {
                "name": "Bob",
                "title": "VP Engineering",
                "status": "Extracted",
                "next_action": "filter",
            },
        )

        # Create state
        state = create_initial_state(
            "test_filter", current_phase="extract", status="completed"
        )
        save_project_state(project_dir, state)

        # Resolve and run
        resolution = resolve_project_ref("test_filter", tmp_path)
        assert resolution["success"] is True

        result = rf.run_filter(
            resolution["config_path"].parent,
            resolution["config_path"],
            resolution["workbook_path"],
        )

        assert result["success"] is True
        assert result["kept"] == 1
        assert result["filtered"] == 1


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
