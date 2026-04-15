#!/usr/bin/env python3
"""Tests for project_ref_utils.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_project_ref_utils.py -v
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import project_ref_utils as pru


class TestExtractRecruiterIdFromUrl:
    """Tests for extract_recruiter_id_from_url function."""

    def test_extracts_from_search_url(self):
        """Should extract ID from recruiterSearch URL."""
        url = "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        assert pru.extract_recruiter_id_from_url(url) == "12345"

    def test_extracts_from_overview_url(self):
        """Should extract ID from overview URL."""
        url = "https://linkedin.com/talent/hire/67890/overview"
        assert pru.extract_recruiter_id_from_url(url) == "67890"

    def test_extracts_from_url_with_params(self):
        """Should extract ID from URL with query parameters."""
        url = "https://linkedin.com/talent/hire/54321/discover/recruiterSearch?searchContextId=abc"
        assert pru.extract_recruiter_id_from_url(url) == "54321"

    def test_returns_none_for_invalid_url(self):
        """Should return None for URLs without talent/hire pattern."""
        url = "https://linkedin.com/feed/"
        assert pru.extract_recruiter_id_from_url(url) is None

    def test_returns_none_for_non_numeric_id(self):
        """Should return None for non-numeric IDs in URL."""
        url = "https://linkedin.com/talent/hire/abc123/overview"
        assert pru.extract_recruiter_id_from_url(url) is None

    def test_extracts_from_url_without_trailing_slash(self):
        """Should extract ID from URL without trailing slash (slashless)."""
        url = "https://linkedin.com/talent/hire/12345"
        assert pru.extract_recruiter_id_from_url(url) == "12345"

    def test_extracts_from_url_with_query_no_trailing_slash(self):
        """Should extract ID from URL with query params but no trailing slash."""
        url = "https://linkedin.com/talent/hire/12345?searchContextId=abc"
        assert pru.extract_recruiter_id_from_url(url) == "12345"

    def test_extracts_from_url_with_hash_no_trailing_slash(self):
        """Should extract ID from URL with hash fragment but no trailing slash."""
        url = "https://linkedin.com/talent/hire/12345#tab"
        assert pru.extract_recruiter_id_from_url(url) == "12345"

    def test_extracts_from_www_subdomain(self):
        """Should extract ID from www.linkedin.com subdomain."""
        url = "https://www.linkedin.com/talent/hire/54321"
        assert pru.extract_recruiter_id_from_url(url) == "54321"


class TestIsRecruiterUrl:
    """Tests for is_recruiter_url function."""

    def test_true_for_recruiter_search_url(self):
        """Should return True for recruiterSearch URL."""
        assert pru.is_recruiter_url(
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )

    def test_true_for_overview_url(self):
        """Should return True for overview URL."""
        assert pru.is_recruiter_url("https://linkedin.com/talent/hire/123/overview")

    def test_false_for_regular_linkedin_url(self):
        """Should return False for regular LinkedIn URLs."""
        assert not pru.is_recruiter_url("https://linkedin.com/in/profile")

    def test_false_for_random_string(self):
        """Should return False for random strings."""
        assert not pru.is_recruiter_url("my_project_id")

    def test_true_for_slashless_url(self):
        """Should return True for URL without trailing slash."""
        assert pru.is_recruiter_url("https://linkedin.com/talent/hire/12345")

    def test_true_for_slashless_with_query(self):
        """Should return True for slashless URL with query params."""
        assert pru.is_recruiter_url(
            "https://linkedin.com/talent/hire/12345?searchContextId=abc"
        )

    def test_true_for_slashless_with_hash(self):
        """Should return True for slashless URL with hash fragment."""
        assert pru.is_recruiter_url("https://linkedin.com/talent/hire/12345#tab")


class TestIsBareNumericId:
    """Tests for is_bare_numeric_id function."""

    def test_true_for_numeric_string(self):
        """Should return True for numeric strings."""
        assert pru.is_bare_numeric_id("12345")

    def test_false_for_alphanumeric(self):
        """Should return False for alphanumeric strings."""
        assert not pru.is_bare_numeric_id("abc123")

    def test_false_for_empty_string(self):
        """Should return False for empty string."""
        assert not pru.is_bare_numeric_id("")

    def test_false_for_url(self):
        """Should return False for URLs."""
        assert not pru.is_bare_numeric_id("https://linkedin.com/talent/hire/123")


class TestIsConfigPath:
    """Tests for is_config_path function."""

    def test_true_for_config_sh(self):
        """Should return True for paths ending in config.sh."""
        assert pru.is_config_path("/path/to/config.sh")

    def test_true_for_path_with_separator(self):
        """Should return True for paths with separators."""
        assert pru.is_config_path("projects/my_project/config.sh")

    def test_false_for_simple_id(self):
        """Should return False for simple project IDs."""
        assert not pru.is_config_path("my_project")


class TestScanProjectsForProjectId:
    """Tests for scan_projects_for_project_id function."""

    def test_finds_matching_project_id(self, tmp_path):
        """Should find config containing matching PROJECT_ID."""
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "some_folder_name"
        project_dir.mkdir(parents=True)

        config_content = 'PROJECT_ID="my_project"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"'
        config_file = project_dir / "config.sh"
        config_file.write_text(config_content)

        matches = pru.scan_projects_for_project_id(tmp_path, "my_project")

        assert len(matches) == 1
        assert matches[0] == config_file

    def test_returns_empty_for_no_match(self, tmp_path):
        """Should return empty list when no config matches PROJECT_ID."""
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "my_project"
        project_dir.mkdir(parents=True)

        config_content = 'PROJECT_ID="other_project"'
        config_file = project_dir / "config.sh"
        config_file.write_text(config_content)

        matches = pru.scan_projects_for_project_id(tmp_path, "nonexistent")

        assert len(matches) == 0

    def test_finds_multiple_matches_same_project_id(self, tmp_path):
        """Should find multiple configs with same PROJECT_ID."""
        projects_dir = tmp_path / "projects"

        for name in ["folder_a", "folder_b"]:
            project_dir = projects_dir / name
            project_dir.mkdir(parents=True)
            config_content = 'PROJECT_ID="shared_id"'
            (project_dir / "config.sh").write_text(config_content)

        matches = pru.scan_projects_for_project_id(tmp_path, "shared_id")

        assert len(matches) == 2

    def test_skips_nonexistent_projects_dir(self, tmp_path):
        """Should return empty list when projects dir doesn't exist."""
        matches = pru.scan_projects_for_project_id(tmp_path, "my_project")
        assert len(matches) == 0

    def test_matches_numeric_project_id(self, tmp_path):
        """Should match numeric PROJECT_ID values."""
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "12345_some_slug"
        project_dir.mkdir(parents=True)

        config_content = 'PROJECT_ID="12345"'
        config_file = project_dir / "config.sh"
        config_file.write_text(config_content)

        matches = pru.scan_projects_for_project_id(tmp_path, "12345")

        assert len(matches) == 1
        assert matches[0] == config_file

    def test_ignores_folder_name(self, tmp_path):
        """Should match by PROJECT_ID, not folder name."""
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "folder_name"
        project_dir.mkdir(parents=True)

        # PROJECT_ID differs from folder name
        config_content = 'PROJECT_ID="actual_project_id"'
        config_file = project_dir / "config.sh"
        config_file.write_text(config_content)

        # Searching by folder name should NOT match
        matches_by_folder = pru.scan_projects_for_project_id(tmp_path, "folder_name")
        assert len(matches_by_folder) == 0

        # Searching by PROJECT_ID should match
        matches_by_id = pru.scan_projects_for_project_id(tmp_path, "actual_project_id")
        assert len(matches_by_id) == 1


class TestScanProjectsForRecruiterId:
    """Tests for scan_projects_for_recruiter_id function."""

    def test_finds_matching_config(self, tmp_path):
        """Should find config containing recruiter ID in URL."""
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "my_project"
        project_dir.mkdir(parents=True)

        config_content = 'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\nPROJECT_ID="my_project"'
        config_file = project_dir / "config.sh"
        config_file.write_text(config_content)

        matches = pru.scan_projects_for_recruiter_id(tmp_path, "12345")

        assert len(matches) == 1
        assert matches[0] == config_file

    def test_returns_empty_for_no_match(self, tmp_path):
        """Should return empty list when no config matches."""
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "my_project"
        project_dir.mkdir(parents=True)

        config_content = (
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/99999/overview"'
        )
        config_file = project_dir / "config.sh"
        config_file.write_text(config_content)

        matches = pru.scan_projects_for_recruiter_id(tmp_path, "12345")

        assert len(matches) == 0

    def test_finds_multiple_matches(self, tmp_path):
        """Should find multiple configs with same recruiter ID."""
        projects_dir = tmp_path / "projects"

        for name in ["project_a", "project_b"]:
            project_dir = projects_dir / name
            project_dir.mkdir(parents=True)
            config_content = 'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"'
            (project_dir / "config.sh").write_text(config_content)

        matches = pru.scan_projects_for_recruiter_id(tmp_path, "12345")

        assert len(matches) == 2

    def test_skips_nonexistent_projects_dir(self, tmp_path):
        """Should return empty list when projects dir doesn't exist."""
        matches = pru.scan_projects_for_recruiter_id(tmp_path, "12345")
        assert len(matches) == 0

    def test_requires_exact_recruiter_id_match(self, tmp_path):
        """Should NOT match substring - only exact recruiter ID match."""
        projects_dir = tmp_path / "projects"
        project_dir = projects_dir / "my_project"
        project_dir.mkdir(parents=True)

        # Config has recruiter ID 12345, but we're searching for 123
        config_content = (
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"'
        )
        config_file = project_dir / "config.sh"
        config_file.write_text(config_content)

        # Searching for "123" should NOT match "12345"
        matches = pru.scan_projects_for_recruiter_id(tmp_path, "123")
        assert len(matches) == 0

    def test_exact_match_different_ids_same_prefix(self, tmp_path):
        """Should distinguish between IDs with same prefix (e.g., 123 vs 12345)."""
        projects_dir = tmp_path / "projects"

        # Create project with ID 123
        project_dir_123 = projects_dir / "project_123"
        project_dir_123.mkdir(parents=True)
        (project_dir_123 / "config.sh").write_text(
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123/overview"'
        )

        # Create project with ID 12345
        project_dir_12345 = projects_dir / "project_12345"
        project_dir_12345.mkdir(parents=True)
        (project_dir_12345 / "config.sh").write_text(
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"'
        )

        # Searching for 123 should only find project_123
        matches_123 = pru.scan_projects_for_recruiter_id(tmp_path, "123")
        assert len(matches_123) == 1
        assert matches_123[0].parent.name == "project_123"

        # Searching for 12345 should only find project_12345
        matches_12345 = pru.scan_projects_for_recruiter_id(tmp_path, "12345")
        assert len(matches_12345) == 1
        assert matches_12345[0].parent.name == "project_12345"


class TestParseConfigFile:
    """Tests for parse_config_file function."""

    def test_parses_double_quoted_values(self, tmp_path):
        """Should parse double-quoted values."""
        config_file = tmp_path / "config.sh"
        config_file.write_text('PROJECT_ID="my_project"\nURL="https://example.com"')

        config = pru.parse_config_file(config_file)

        assert config["PROJECT_ID"] == "my_project"
        assert config["URL"] == "https://example.com"

    def test_parses_single_quoted_values(self, tmp_path):
        """Should parse single-quoted values."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID='my_project'")

        config = pru.parse_config_file(config_file)

        assert config["PROJECT_ID"] == "my_project"

    def test_ignores_comments_and_empty_lines(self, tmp_path):
        """Should ignore comments and empty lines."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            '# Comment\nPROJECT_ID="my_project"\n\n# Another comment'
        )

        config = pru.parse_config_file(config_file)

        assert config["PROJECT_ID"] == "my_project"
        assert "# Comment" not in config

    def test_returns_empty_for_missing_file(self, tmp_path):
        """Should return empty dict for missing file."""
        config = pru.parse_config_file(tmp_path / "nonexistent.sh")
        assert config == {}


class TestResolveProjectRef:
    """Tests for resolve_project_ref function."""

    @patch("project_ref_utils.RuntimeManager")
    def test_resolves_config_path_directly(self, mock_manager_class, tmp_path):
        """Should resolve direct config.sh path."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        config_file = tmp_path / "my_project" / "config.sh"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            'PROJECT_ID="my_project"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123/overview"'
        )

        result = pru.resolve_project_ref(str(config_file))

        assert result["success"] is True
        assert result["config_path"] == config_file.resolve()
        assert result["local_project_id"] == "my_project"
        assert result["recruiter_project_id"] == "123"

    @patch("project_ref_utils.RuntimeManager")
    def test_error_for_missing_config_file(self, mock_manager_class, tmp_path):
        """Should return error for non-existent config path."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        result = pru.resolve_project_ref("/nonexistent/config.sh")

        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("project_ref_utils.RuntimeManager")
    def test_resolves_local_project_id(self, mock_manager_class, tmp_path):
        """Should resolve local PROJECT_ID to config by scanning configs."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        projects_dir = tmp_path / "projects" / "my_project"
        projects_dir.mkdir(parents=True)
        config_file = projects_dir / "config.sh"
        config_file.write_text(
            'PROJECT_ID="my_project"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123/overview"'
        )

        result = pru.resolve_project_ref("my_project")

        assert result["success"] is True
        assert result["config_path"] == config_file
        assert result["local_project_id"] == "my_project"

    @patch("project_ref_utils.RuntimeManager")
    def test_resolves_project_id_when_folder_name_differs(
        self, mock_manager_class, tmp_path
    ):
        """Should resolve PROJECT_ID even when folder name differs."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        # Folder name is different from PROJECT_ID
        projects_dir = tmp_path / "projects" / "12345_engineering_role"
        projects_dir.mkdir(parents=True)
        config_file = projects_dir / "config.sh"
        config_file.write_text(
            'PROJECT_ID="eng_role_2024"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"'
        )

        # Reference by PROJECT_ID, not folder name
        result = pru.resolve_project_ref("eng_role_2024")

        assert result["success"] is True
        assert result["config_path"] == config_file
        assert result["local_project_id"] == "eng_role_2024"

    @patch("project_ref_utils.RuntimeManager")
    def test_resolves_numeric_project_id_in_slug_folder(
        self, mock_manager_class, tmp_path
    ):
        """Should resolve numeric PROJECT_ID in <id>_<slug> folder format."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        # Folder uses <id>_<slug> format
        projects_dir = tmp_path / "projects" / "67890_senior_pm"
        projects_dir.mkdir(parents=True)
        config_file = projects_dir / "config.sh"
        config_file.write_text(
            'PROJECT_ID="67890"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/67890/overview"'
        )

        # Reference by numeric PROJECT_ID
        result = pru.resolve_project_ref("67890")

        assert result["success"] is True
        assert result["config_path"] == config_file
        assert result["local_project_id"] == "67890"

    @patch("project_ref_utils.RuntimeManager")
    def test_ambiguous_project_id_fails_closed(self, mock_manager_class, tmp_path):
        """Should fail when multiple projects have same PROJECT_ID."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        # Create two projects with same PROJECT_ID
        for folder in ["project_a", "project_b"]:
            projects_dir = tmp_path / "projects" / folder
            projects_dir.mkdir(parents=True)
            config_file = projects_dir / "config.sh"
            config_file.write_text(
                'PROJECT_ID="shared_id"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"'
            )

        result = pru.resolve_project_ref("shared_id")

        assert result["success"] is False
        assert "Ambiguous" in result["error"]
        assert "shared_id" in result["error"]

    @patch("project_ref_utils.RuntimeManager")
    def test_non_numeric_project_id_in_arbitrary_folder(
        self, mock_manager_class, tmp_path
    ):
        """Should resolve non-numeric PROJECT_ID in arbitrary folder name."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        # Arbitrary folder name
        projects_dir = tmp_path / "projects" / "some_random_folder"
        projects_dir.mkdir(parents=True)
        config_file = projects_dir / "config.sh"
        config_file.write_text(
            'PROJECT_ID="my_custom_project"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/99999/overview"'
        )

        result = pru.resolve_project_ref("my_custom_project")

        assert result["success"] is True
        assert result["config_path"] == config_file
        assert result["local_project_id"] == "my_custom_project"

    @patch("project_ref_utils.RuntimeManager")
    def test_error_for_missing_local_project(self, mock_manager_class, tmp_path):
        """Should return error when no project has the given PROJECT_ID."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        result = pru.resolve_project_ref("nonexistent_project")

        assert result["success"] is False
        assert "not found" in result["error"]
        assert "PROJECT_ID" in result["error"]

    @patch("project_ref_utils.RuntimeManager")
    def test_defaults_to_new_layout_for_new_projects(
        self, mock_manager_class, tmp_path
    ):
        """Should default to new layout path when no workbook exists."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        projects_dir = tmp_path / "projects" / "12345_new-project"
        projects_dir.mkdir(parents=True)
        config_file = projects_dir / "config.sh"
        config_file.write_text(
            'PROJECT_ID="12345"\nRECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"'
        )
        # No workbook exists

        # Reference by PROJECT_ID, not folder name
        result = pru.resolve_project_ref("12345")

        # Should default to new layout path
        expected_workbook = projects_dir / "workbook.xlsx"
        assert result["workbook_path"] == expected_workbook

    @patch("project_ref_utils.RuntimeManager")
    def test_project_without_project_id_not_found_by_name(
        self, mock_manager_class, tmp_path
    ):
        """Project without PROJECT_ID cannot be found by ID lookup."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        projects_dir = tmp_path / "projects" / "my_project"
        projects_dir.mkdir(parents=True)
        config_file = projects_dir / "config.sh"
        # No PROJECT_ID defined
        config_file.write_text(
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123/overview"'
        )

        # Cannot find by folder name anymore - must use direct config path
        result = pru.resolve_project_ref("my_project")

        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("project_ref_utils.RuntimeManager")
    def test_project_without_project_id_found_by_direct_path(
        self, mock_manager_class, tmp_path
    ):
        """Project without PROJECT_ID can still be accessed via direct config path."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path
        mock_manager_class.return_value = mock_manager

        projects_dir = tmp_path / "projects" / "my_project"
        projects_dir.mkdir(parents=True)
        config_file = projects_dir / "config.sh"
        # No PROJECT_ID defined
        config_file.write_text(
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123/overview"'
        )

        # Can still access via direct config path
        result = pru.resolve_project_ref(str(config_file))

        assert result["success"] is True
        # Falls back to directory name when PROJECT_ID not in config
        assert result["local_project_id"] == "my_project"

    def test_error_for_runtime_manager_failure(self):
        """Should return error when RuntimeManager fails."""
        with patch("project_ref_utils.RuntimeManager") as mock_manager_class:
            mock_manager_class.side_effect = Exception("Config error")

            result = pru.resolve_project_ref("my_project")

            assert result["success"] is False
            assert "WORK_DIR" in result["error"]

    @patch("project_ref_utils.RuntimeManager")
    def test_accepts_explicit_work_dir(self, mock_manager_class, tmp_path):
        """Should use provided work_dir instead of RuntimeManager."""
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager

        projects_dir = tmp_path / "projects" / "my_project"
        projects_dir.mkdir(parents=True)
        config_file = projects_dir / "config.sh"
        config_file.write_text('PROJECT_ID="my_project"')

        result = pru.resolve_project_ref("my_project", work_dir=tmp_path)

        assert result["success"] is True
        assert result["config_path"] == config_file
        # RuntimeManager should not be called for work_dir
        mock_manager.work_dir.assert_not_called()
