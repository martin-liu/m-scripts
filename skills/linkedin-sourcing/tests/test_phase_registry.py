#!/usr/bin/env python3
"""Tests for phase_registry.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_phase_registry.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import phase_registry as pr


class TestGetPhaseOrder:
    """Tests for get_phase_order function."""

    def test_returns_reachout_phases_by_default(self):
        """Should return reachout phases by default (loop starts at create_search)."""
        phases = pr.get_phase_order()

        # bootstrap is a pre-loop entrypoint, not a runnable loop phase
        assert phases == [
            "create_search",
            "extract",
            "filter",
            "enrich",
            "draft",
            "review",
            "send",
        ]

    def test_returns_review_phases_when_requested(self):
        """Should return review phases when specified."""
        phases = pr.get_phase_order("review")

        assert phases == ["draft", "review", "send"]

    def test_returns_copy_not_reference(self):
        """Should return a copy, not the original list."""
        phases1 = pr.get_phase_order()
        phases2 = pr.get_phase_order()

        phases1.append("extra")

        assert "extra" not in phases2


class TestGetNextPhase:
    """Tests for get_next_phase function."""

    def test_returns_next_phase_in_reachout_sequence(self):
        """Should return the next phase in reachout workflow."""
        # bootstrap is not in the loop phases - it's a pre-loop entrypoint
        assert pr.get_next_phase("create_search", "reachout") == "extract"
        assert pr.get_next_phase("extract", "reachout") == "filter"
        assert pr.get_next_phase("filter", "reachout") == "enrich"
        assert pr.get_next_phase("enrich", "reachout") == "draft"
        assert pr.get_next_phase("draft", "reachout") == "review"
        assert pr.get_next_phase("review", "reachout") == "send"

    def test_returns_next_phase_in_review_sequence(self):
        """Should return the next phase in review workflow."""
        assert pr.get_next_phase("draft", "review") == "review"
        assert pr.get_next_phase("review", "review") == "send"

    def test_returns_none_at_end_of_reachout(self):
        """Should return None when at final phase of reachout."""
        assert pr.get_next_phase("send", "reachout") is None

    def test_returns_none_at_end_of_review(self):
        """Should return None when at final phase of review."""
        assert pr.get_next_phase("send", "review") is None

    def test_returns_none_for_unknown_phase(self):
        """Should return None for phase not in workflow."""
        assert pr.get_next_phase("unknown", "reachout") is None
        assert pr.get_next_phase("unknown", "review") is None

    def test_defaults_to_reachout_mode(self):
        """Should default to reachout mode if not specified."""
        assert pr.get_next_phase("filter") == "enrich"


class TestGetPhaseMetadata:
    """Tests for get_phase_metadata function."""

    def test_returns_metadata_for_known_phases(self):
        """Should return metadata for known phases."""
        meta = pr.get_phase_metadata("filter")

        assert meta["name"] == "Filter"
        assert "description" in meta
        assert meta["requires_browser"] is False
        assert meta["is_automated"] is True

    def test_draft_is_not_browser_heavy(self):
        """Draft phase should not require browser."""
        meta = pr.get_phase_metadata("draft")

        assert meta["requires_browser"] is False
        assert meta["is_automated"] is True

    def test_review_is_human_stop_boundary(self):
        """Review phase should not be automated."""
        meta = pr.get_phase_metadata("review")

        assert meta["is_automated"] is False

    def test_send_requires_browser(self):
        """Send phase should require browser."""
        meta = pr.get_phase_metadata("send")

        assert meta["requires_browser"] is True

    def test_returns_default_for_unknown_phase(self):
        """Should return default metadata for unknown phase."""
        meta = pr.get_phase_metadata("unknown_phase")

        assert meta["name"] == "Unknown_phase"
        assert "description" in meta
        assert meta["requires_browser"] is False
        assert meta["is_automated"] is True


class TestIsValidPhase:
    """Tests for is_valid_phase function."""

    def test_validates_reachout_phases(self):
        """Should validate phases for reachout mode."""
        # bootstrap is a pre-loop entrypoint, not a runnable loop phase
        assert pr.is_valid_phase("bootstrap", "reachout") is False
        assert pr.is_valid_phase("create_search", "reachout") is True
        assert pr.is_valid_phase("filter", "reachout") is True
        assert pr.is_valid_phase("send", "reachout") is True

    def test_validates_review_phases(self):
        """Should validate phases for review mode."""
        assert pr.is_valid_phase("draft", "review") is True
        assert pr.is_valid_phase("send", "review") is True

    def test_invalid_for_wrong_mode(self):
        """Should invalidate phases not in the workflow mode."""
        assert pr.is_valid_phase("bootstrap", "review") is False
        assert pr.is_valid_phase("extract", "review") is False
        assert pr.is_valid_phase("create_search", "review") is False

    def test_invalid_for_unknown_phase(self):
        """Should invalidate unknown phases."""
        assert pr.is_valid_phase("unknown", "reachout") is False
        assert pr.is_valid_phase("unknown", "review") is False

    def test_defaults_to_reachout(self):
        """Should default to reachout mode."""
        assert pr.is_valid_phase("filter") is True
        assert pr.is_valid_phase("scan") is False


class TestGetCommandForPhase:
    """Tests for get_command_for_phase function."""

    def test_returns_command_for_filter(self):
        """Should return command for filter phase."""
        cmd = pr.get_command_for_phase("filter", "my_project")

        assert "run_filter.py" in cmd
        assert "my_project" in cmd

    def test_extract_command_uses_project_not_config_path(self):
        """Extract command should use --project for slugged folder compatibility.

        This tests the fix for the gap where status.py suggested an invalid
        command with --config $WORK_DIR/projects/{PROJECT_ID}/config.sh for
        slugged project folders (e.g., 1692252652_linkedin-sourcing-live-verification).
        """
        cmd = pr.get_command_for_phase("extract", "my_project")

        assert "run_extraction.py" in cmd
        assert "--project my_project" in cmd
        assert "--config" not in cmd  # Should not use hardcoded config path

    def test_returns_command_for_draft(self):
        """Should return command for draft phase."""
        cmd = pr.get_command_for_phase("draft", "my_project")

        assert "run_draft.py" in cmd
        assert "my_project" in cmd

    def test_returns_command_for_send(self):
        """Should return command for send phase."""
        cmd = pr.get_command_for_phase("send", "my_project")

        assert "run_send.py" in cmd

    def test_uses_placeholder_when_no_project_ref(self):
        """Should use placeholder when no project ref provided."""
        cmd = pr.get_command_for_phase("filter")

        assert "<project_ref>" in cmd

    def test_review_is_human_action(self):
        """Review phase command should indicate human action."""
        cmd = pr.get_command_for_phase("review", "my_project")

        assert "#" in cmd  # Comment indicating human action
        assert "workbook" in cmd


class TestGetPhaseFromCommand:
    """Tests for get_phase_from_command function."""

    def test_extracts_filter_from_command(self):
        """Should extract filter phase from command."""
        phase = pr.get_phase_from_command("python3 run_filter.py my_project")

        assert phase == "filter"

    def test_extracts_draft_from_command(self):
        """Should extract draft phase from command."""
        phase = pr.get_phase_from_command("python3 run_draft.py my_project")

        assert phase == "draft"

    def test_extracts_send_from_command(self):
        """Should extract send phase from command."""
        phase = pr.get_phase_from_command("python3 run_send.py --config config.sh")

        assert phase == "send"

    def test_returns_none_for_unknown_command(self):
        """Should return None for unrecognized command."""
        phase = pr.get_phase_from_command("python3 unknown_script.py")

        assert phase is None


class TestPhaseConstants:
    """Tests for phase constants."""

    def test_reachout_phases_includes_all_expected(self):
        """REACHOUT_PHASES should include all loop phases (starts at create_search)."""
        # bootstrap is a pre-loop entrypoint, not a runnable loop phase
        expected = [
            "create_search",
            "extract",
            "filter",
            "enrich",
            "draft",
            "review",
            "send",
        ]

        assert pr.REACHOUT_PHASES == expected

    def test_review_phases_includes_all_expected(self):
        """REVIEW_PHASES should include all expected phases."""
        expected = ["draft", "review", "send"]

        assert pr.REVIEW_PHASES == expected

    def test_all_phases_have_metadata(self):
        """All phases in both workflows should have metadata."""
        all_phases = set(pr.REACHOUT_PHASES) | set(pr.REVIEW_PHASES)

        for phase in all_phases:
            meta = pr.get_phase_metadata(phase)
            assert "name" in meta
            assert "description" in meta
            assert "requires_browser" in meta
            assert "is_automated" in meta


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
