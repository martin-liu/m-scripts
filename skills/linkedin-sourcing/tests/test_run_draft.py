#!/usr/bin/env python3
"""Tests for run_draft.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_run_draft.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_draft as rd
from excel_utils import create as create_workbook, update as update_row


class TestFindTemplate:
    """Tests for find_template function."""

    def test_finds_template_in_project_dir(self, tmp_path):
        """Should find template in project directory."""
        template_path = tmp_path / "inmail_template.txt"
        template_path.write_text("Subject: Test\n\nBody")

        config = {}
        found = rd.find_template(tmp_path, config)

        assert found == template_path

    def test_uses_template_path_from_config(self, tmp_path):
        """Should use TEMPLATE_PATH from config when provided."""
        custom_template = tmp_path / "custom.txt"
        custom_template.write_text("Subject: Custom\n\nBody")

        config = {"TEMPLATE_PATH": str(custom_template)}
        found = rd.find_template(tmp_path, config)

        assert found == custom_template

    def test_returns_default_template_when_no_project_template(self, tmp_path):
        """Should return default skill template when no project template exists."""
        config = {}
        found = rd.find_template(tmp_path, config)

        # Should find the default template in skill templates directory
        assert found is not None
        assert found.name == "inmail_template.txt"
        assert found.exists()

    def test_prefers_config_over_project_dir(self, tmp_path):
        """Should prefer config TEMPLATE_PATH over project dir template."""
        project_template = tmp_path / "inmail_template.txt"
        project_template.write_text("Subject: Project\n\nBody")

        custom_template = tmp_path / "custom.txt"
        custom_template.write_text("Subject: Custom\n\nBody")

        config = {"TEMPLATE_PATH": str(custom_template)}
        found = rd.find_template(tmp_path, config)

        assert found == custom_template


class TestRunDraft:
    """Tests for run_draft function."""

    def create_test_workbook(self, tmp_path, rows_data):
        """Helper to create a test workbook with candidate data."""
        from excel_utils import create, append

        wb_path = tmp_path / "workbook.xlsx"
        create(str(wb_path))

        for row_data in rows_data:
            append(str(wb_path), row_data)

        return wb_path

    def test_generates_drafts_for_ready_candidates(self, tmp_path):
        """Should generate drafts for candidates with next_action=draft."""
        # Create config
        config_path = tmp_path / "config.sh"
        config_path.write_text("""
PROJECT_ID="test"
POSITION_TITLE="ML Engineer"
TEAM_NAME="AI Platform"
LOCATION="SF"
CORE_FUNCTION="building ML systems"
BUSINESS_IMPACT="improving products"
USER_EMAIL="test@example.com"
""")

        # Create template
        template_path = tmp_path / "inmail_template.txt"
        template_path.write_text("""Subject: {FirstName}, {POSITION_TITLE} Opportunity

Hi {FirstName},

Your work at {Company} caught my eye.

Best,
Team""")

        # Create workbook
        rows = [
            {
                "name": "John Smith",
                "title": "Engineer",
                "company": "Google",
                "status": "Extracted",
                "next_action": "draft",
                "headline": "ML Expert",
            },
        ]
        workbook_path = self.create_test_workbook(tmp_path, rows)

        result = rd.run_draft(tmp_path, config_path, workbook_path, template_path)

        assert result["success"] is True
        assert result["drafted"] == 1
        assert result["skipped"] == 0

    def test_returns_error_for_missing_config(self, tmp_path):
        """Should return error when config file is missing."""
        config_path = tmp_path / "nonexistent.sh"
        workbook_path = tmp_path / "workbook.xlsx"
        create_workbook(str(workbook_path))

        result = rd.run_draft(tmp_path, config_path, workbook_path)

        assert result["success"] is False
        assert "config" in result["error"].lower()

    def test_returns_error_for_missing_workbook(self, tmp_path):
        """Should return error when workbook is missing."""
        config_path = tmp_path / "config.sh"
        config_path.write_text('PROJECT_ID="test"')
        workbook_path = tmp_path / "nonexistent.xlsx"

        result = rd.run_draft(tmp_path, config_path, workbook_path)

        assert result["success"] is False
        assert "workbook" in result["error"].lower()

    def test_uses_default_template_when_no_project_template(self, tmp_path):
        """Should use default skill template when no project template exists."""
        config_path = tmp_path / "config.sh"
        config_path.write_text('PROJECT_ID="test"')
        workbook_path = tmp_path / "workbook.xlsx"
        create_workbook(str(workbook_path))

        result = rd.run_draft(tmp_path, config_path, workbook_path)

        # Should succeed using the default template (though no rows to draft)
        assert result["success"] is True
        assert result["template_path"] is not None
        assert "inmail_template.txt" in result["template_path"]

    def test_skips_already_drafted_rows(self, tmp_path):
        """Should skip rows already in Drafted status."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("""
PROJECT_ID="test"
POSITION_TITLE="Engineer"
TEAM_NAME="AI"
LOCATION="SF"
CORE_FUNCTION="building"
BUSINESS_IMPACT="impact"
USER_EMAIL="test@example.com"
""")

        template_path = tmp_path / "inmail_template.txt"
        template_path.write_text("Subject: Test\n\nBody for {FirstName}")

        rows = [
            {
                "name": "John",
                "title": "Engineer",
                "status": "Drafted",
                "next_action": "review",
                "draft_subject": "Existing",
            },
            {
                "name": "Jane",
                "title": "Engineer",
                "status": "Extracted",
                "next_action": "draft",
            },
        ]
        workbook_path = self.create_test_workbook(tmp_path, rows)

        result = rd.run_draft(tmp_path, config_path, workbook_path, template_path)

        assert result["success"] is True
        assert result["drafted"] == 1
        assert result["skipped"] == 1

    def test_updates_project_state_on_success(self, tmp_path):
        """Should update project state after successful draft."""
        from project_state import (
            load_project_state,
            create_initial_state,
            save_project_state,
        )

        # Setup
        config_path = tmp_path / "config.sh"
        config_path.write_text("""
PROJECT_ID="test"
POSITION_TITLE="Engineer"
TEAM_NAME="AI"
LOCATION="SF"
CORE_FUNCTION="building"
BUSINESS_IMPACT="impact"
USER_EMAIL="test@example.com"
""")

        template_path = tmp_path / "inmail_template.txt"
        template_path.write_text("Subject: Test\n\nBody")

        rows = [
            {
                "name": "John",
                "title": "Engineer",
                "status": "Extracted",
                "next_action": "draft",
            }
        ]
        workbook_path = self.create_test_workbook(tmp_path, rows)

        # Create initial state
        state = create_initial_state("test", current_phase="enrich", status="completed")
        save_project_state(tmp_path, state)

        # Run draft
        result = rd.run_draft(tmp_path, config_path, workbook_path, template_path)

        # Verify state updated
        assert result["success"] is True
        updated_state = load_project_state(tmp_path)
        assert updated_state["current_phase"] == "draft"
        assert updated_state["status"] == "completed"

    def test_clears_last_error_on_success(self, tmp_path):
        """Should clear stale last_error after a successful draft rerun."""
        from project_state import (
            create_initial_state,
            load_project_state,
            save_project_state,
        )

        config_path = tmp_path / "config.sh"
        config_path.write_text(
            'PROJECT_ID="test"\nPOSITION_TITLE="Engineer"\nTEAM_NAME="AI"\nLOCATION="SF"\nCORE_FUNCTION="building"\nBUSINESS_IMPACT="impact"\nUSER_EMAIL="test@example.com"\n'
        )

        template_path = tmp_path / "inmail_template.txt"
        template_path.write_text("Subject: Test\n\nBody")

        workbook_path = self.create_test_workbook(
            tmp_path,
            [
                {
                    "name": "John",
                    "title": "Engineer",
                    "status": "Extracted",
                    "next_action": "draft",
                }
            ],
        )

        state = create_initial_state("test", current_phase="draft", status="failed")
        state["last_error"] = "Template file not found"
        save_project_state(tmp_path, state)

        result = rd.run_draft(tmp_path, config_path, workbook_path, template_path)

        assert result["success"] is True
        updated_state = load_project_state(tmp_path)
        assert updated_state["last_error"] is None

    def test_can_draft_specific_row_ids(self, tmp_path):
        """Should support drafting only the requested row IDs."""
        config_path = tmp_path / "config.sh"
        config_path.write_text(
            'PROJECT_ID="test"\nPOSITION_TITLE="Engineer"\nTEAM_NAME="AI"\nLOCATION="SF"\nCORE_FUNCTION="building"\nBUSINESS_IMPACT="impact"\nUSER_EMAIL="test@example.com"\n'
        )

        template_path = tmp_path / "inmail_template.txt"
        template_path.write_text("Subject: Test\n\nBody for {FirstName}")

        workbook_path = self.create_test_workbook(
            tmp_path,
            [
                {
                    "name": "Jane",
                    "title": "Engineer",
                    "company": "Meta",
                    "status": "Extracted",
                    "next_action": "draft",
                },
                {
                    "name": "John",
                    "title": "Engineer",
                    "company": "Google",
                    "status": "Extracted",
                    "next_action": "draft",
                },
            ],
        )

        result = rd.run_draft(
            tmp_path,
            config_path,
            workbook_path,
            template_path,
            row_ids=[2],
        )

        assert result["success"] is True
        assert result["drafted"] == 1
        assert result["skipped"] == 1

        from excel_utils import read

        rows = {row["row_id"]: row for row in read(str(workbook_path))}
        assert rows[1]["status"] == "Extracted"
        assert rows[1]["next_action"] == "draft"
        assert rows[2]["status"] == "Drafted"
        assert rows[2]["next_action"] == "review"

    def test_uses_enrichment_notes_when_available(self, tmp_path):
        """Should use enrichment_notes for personalization."""
        config_path = tmp_path / "config.sh"
        config_path.write_text("""
PROJECT_ID="test"
POSITION_TITLE="ML Engineer"
TEAM_NAME="AI"
LOCATION="SF"
CORE_FUNCTION="building ML"
BUSINESS_IMPACT="impact"
USER_EMAIL="test@example.com"
""")

        template_path = tmp_path / "inmail_template.txt"
        template_path.write_text("""Subject: {FirstName}, Opportunity

Hi {FirstName},
{1 personalized sentence on why their background impressed you}
Best""")

        rows = [
            {
                "name": "John Smith",
                "title": "Engineer",
                "company": "Google",
                "status": "Extracted",
                "next_action": "draft",
                "headline": "",
                "enrichment_notes": "PyTorch expert with CUDA experience",
            },
        ]
        workbook_path = self.create_test_workbook(tmp_path, rows)

        result = rd.run_draft(tmp_path, config_path, workbook_path, template_path)

        assert result["success"] is True
        assert result["drafted"] == 1

        # Verify the draft was created with enrichment data
        from excel_utils import read

        rows = read(str(workbook_path))
        john_row = [r for r in rows if r["name"] == "John Smith"][0]
        assert john_row["status"] == "Drafted"
        assert john_row["next_action"] == "review"
        assert john_row["draft_body"] is not None


class TestRunDraftIntegration:
    """Integration tests for run_draft module."""

    def test_end_to_end_draft_workflow(self, tmp_path):
        """Test complete draft workflow with project resolution."""
        from project_ref_utils import resolve_project_ref
        from project_state import create_initial_state, save_project_state
        from excel_utils import create, append

        # Setup project structure
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "test_draft"
        project_dir.mkdir(parents=True)

        config_path = project_dir / "config.sh"
        config_path.write_text("""
PROJECT_ID="test_draft"
POSITION_TITLE="Engineer"
TEAM_NAME="AI"
LOCATION="SF"
CORE_FUNCTION="building"
BUSINESS_IMPACT="impact"
USER_EMAIL="test@example.com"
""")

        # Create template in project dir
        template_path = project_dir / "inmail_template.txt"
        template_path.write_text("Subject: Hello {FirstName}\n\nBody text")

        # Create workbook
        wb_path = project_dir / "workbook.xlsx"
        create(str(wb_path))
        append(
            str(wb_path),
            {
                "name": "Alice",
                "title": "Engineer",
                "company": "Google",
                "status": "Extracted",
                "next_action": "draft",
            },
        )

        # Create state
        state = create_initial_state(
            "test_draft", current_phase="enrich", status="completed"
        )
        save_project_state(project_dir, state)

        # Resolve and run
        resolution = resolve_project_ref("test_draft", tmp_path)
        assert resolution["success"] is True

        result = rd.run_draft(
            resolution["config_path"].parent,
            resolution["config_path"],
            resolution["workbook_path"],
        )

        assert result["success"] is True
        assert result["drafted"] == 1
        assert result["template_path"] is not None


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
