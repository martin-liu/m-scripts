#!/usr/bin/env python3
"""Tests for config_utils.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_config_utils.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import config_utils as cu


class TestParseConfigFile:
    """Tests for parse_config_file function."""

    def test_parses_double_quoted_values(self, tmp_path):
        """Should parse double-quoted values from config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123"\n'
            'POSITION_TITLE="Software Engineer"'
        )

        result = cu.parse_config_file(config_file)

        assert result["PROJECT_ID"] == "12345"
        assert result["RECRUITER_PROJECT_URL"] == "https://linkedin.com/talent/hire/123"
        assert result["POSITION_TITLE"] == "Software Engineer"

    def test_parses_single_quoted_values(self, tmp_path):
        """Should parse single-quoted values from config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            "RECRUITER_PROJECT_URL='https://linkedin.com/talent/hire/456'"
        )

        result = cu.parse_config_file(config_file)

        assert result["RECRUITER_PROJECT_URL"] == "https://linkedin.com/talent/hire/456"

    def test_parses_unquoted_values(self, tmp_path):
        """Should parse unquoted values from config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID=my_project\nDAILY_LIMIT=200")

        result = cu.parse_config_file(config_file)

        assert result["PROJECT_ID"] == "my_project"
        assert result["DAILY_LIMIT"] == "200"

    def test_ignores_comments_and_empty_lines(self, tmp_path):
        """Should ignore comments and empty lines."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            "# This is a comment\n"
            'PROJECT_ID="123"\n'
            "\n"
            "# Another comment\n"
            'POSITION_TITLE="Engineer"'
        )

        result = cu.parse_config_file(config_file)

        assert result["PROJECT_ID"] == "123"
        assert result["POSITION_TITLE"] == "Engineer"
        assert "# This is a comment" not in result

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        """Should return empty dict when config file doesn't exist."""
        result = cu.parse_config_file(tmp_path / "nonexistent.sh")
        assert result == {}

    def test_quoted_takes_precedence_over_unquoted(self, tmp_path):
        """Quoted values should take precedence over unquoted for same key."""
        config_file = tmp_path / "config.sh"
        # This shouldn't happen in practice, but test the behavior
        config_file.write_text('PROJECT_ID="quoted_value"\n')

        result = cu.parse_config_file(config_file)

        assert result["PROJECT_ID"] == "quoted_value"

    def test_handles_values_with_spaces(self, tmp_path):
        """Should handle values with spaces correctly."""
        config_file = tmp_path / "config.sh"
        config_file.write_text('LOCATION="San Francisco, CA"\nTEAM_NAME="AI Platform"')

        result = cu.parse_config_file(config_file)

        assert result["LOCATION"] == "San Francisco, CA"
        assert result["TEAM_NAME"] == "AI Platform"

    def test_handles_special_characters_in_values(self, tmp_path):
        """Should handle values with special characters."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            'CORE_FUNCTION="building AI/ML systems"\n'
            'DESCRIPTION="Role: Engineer (Senior)"'
        )

        result = cu.parse_config_file(config_file)

        assert result["CORE_FUNCTION"] == "building AI/ML systems"
        assert result["DESCRIPTION"] == "Role: Engineer (Senior)"

    def test_handles_quoted_inline_comments(self, tmp_path):
        """Quoted values should ignore trailing inline comments."""
        config_file = tmp_path / "config.sh"
        config_file.write_text('PROJECT_ID="live" # note\n')

        result = cu.parse_config_file(config_file)

        assert result["PROJECT_ID"] == "live"

    def test_last_assignment_wins(self, tmp_path):
        """Later assignments should override earlier ones like shell sourcing."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID=stale\nPROJECT_ID=live\n")

        result = cu.parse_config_file(config_file)

        assert result["PROJECT_ID"] == "live"

    def test_accepts_string_path(self, tmp_path):
        """Should accept string path as well as Path object."""
        config_file = tmp_path / "config.sh"
        config_file.write_text('PROJECT_ID="test"')

        result = cu.parse_config_file(str(config_file))

        assert result["PROJECT_ID"] == "test"

    def test_handles_io_errors_gracefully(self, tmp_path):
        """Should handle IO errors gracefully."""
        # Create a directory with the same name to cause read error
        config_file = tmp_path / "not_a_file"
        config_file.mkdir()

        result = cu.parse_config_file(config_file)

        assert result == {}


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
