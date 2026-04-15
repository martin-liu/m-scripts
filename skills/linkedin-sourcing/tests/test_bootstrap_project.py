#!/usr/bin/env python3
"""Tests for bootstrap_project.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_bootstrap_project.py -v
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import bootstrap_project as bp


class TestExtractRecruiterIdFromUrl:
    """Tests for recruiter ID extraction from URLs."""

    def test_extracts_id_from_standard_url(self):
        """Should extract numeric ID from standard Recruiter URL."""
        url = "https://www.linkedin.com/talent/hire/12345/discover/recruiterSearch"
        result = bp.extract_recruiter_id_from_url(url)
        assert result == "12345"

    def test_extracts_id_from_overview_url(self):
        """Should extract numeric ID from overview URL."""
        url = "https://www.linkedin.com/talent/hire/67890/overview"
        result = bp.extract_recruiter_id_from_url(url)
        assert result == "67890"

    def test_extracts_id_from_projects_url(self):
        """Should extract numeric ID from projects URL."""
        url = "https://www.linkedin.com/talent/hire/11111/projects"
        result = bp.extract_recruiter_id_from_url(url)
        assert result == "11111"

    def test_returns_none_for_invalid_url(self):
        """Should return None for non-Recruiter URLs."""
        assert bp.extract_recruiter_id_from_url("https://example.com") is None
        assert bp.extract_recruiter_id_from_url("not-a-url") is None
        assert bp.extract_recruiter_id_from_url("") is None

    def test_extracts_id_with_query_params(self):
        """Should extract ID from URL with query parameters."""
        url = "https://www.linkedin.com/talent/hire/99999/discover/recruiterSearch?searchContextId=abc"
        result = bp.extract_recruiter_id_from_url(url)
        assert result == "99999"

    def test_extracts_id_without_trailing_slash(self):
        """Should extract ID from URL without trailing slash."""
        url = "https://linkedin.com/talent/hire/12345"
        result = bp.extract_recruiter_id_from_url(url)
        assert result == "12345"

    def test_extracts_id_with_query_params_no_trailing_slash(self):
        """Should extract ID from URL with query params but no trailing slash."""
        url = "https://linkedin.com/talent/hire/12345?searchContextId=abc"
        result = bp.extract_recruiter_id_from_url(url)
        assert result == "12345"

    def test_extracts_id_with_fragment_no_trailing_slash(self):
        """Should extract ID from URL with fragment but no trailing slash."""
        url = "https://linkedin.com/talent/hire/12345#tab"
        result = bp.extract_recruiter_id_from_url(url)
        assert result == "12345"

    def test_extracts_id_from_www_subdomain(self):
        """Should extract ID from www.linkedin.com subdomain."""
        url = "https://www.linkedin.com/talent/hire/54321"
        result = bp.extract_recruiter_id_from_url(url)
        assert result == "54321"

    def test_returns_none_for_malformed_talent_url(self):
        """Should return None for malformed talent URLs (fail-closed)."""
        # Missing numeric ID
        assert (
            bp.extract_recruiter_id_from_url("https://linkedin.com/talent/hire/")
            is None
        )
        # Non-numeric ID
        assert (
            bp.extract_recruiter_id_from_url("https://linkedin.com/talent/hire/abc123")
            is None
        )
        # Wrong path
        assert (
            bp.extract_recruiter_id_from_url("https://linkedin.com/talent/search/12345")
            is None
        )


class TestGetWorkDir:
    """Tests for work directory resolution."""

    def test_uses_cli_value_when_provided(self, tmp_path):
        """CLI value should take precedence."""
        custom_dir = tmp_path / "custom"
        result = bp.get_work_dir(str(custom_dir))
        assert result == custom_dir.resolve()

    @patch("runtime_manager.RuntimeManager")
    def test_uses_runtime_manager_when_no_cli(self, mock_manager_class, tmp_path):
        """Should use RuntimeManager for consistent profile resolution."""
        mock_manager = Mock()
        mock_manager.work_dir = tmp_path / "from_runtime"
        mock_manager_class.return_value = mock_manager

        result = bp.get_work_dir(None)

        assert result == tmp_path / "from_runtime"
        mock_manager_class.assert_called_once()

    @patch("runtime_manager.RuntimeManager")
    def test_runtime_manager_uses_profile_defaults(self, mock_manager_class, tmp_path):
        """RuntimeManager should provide default work_dir when not in profile."""
        mock_manager = Mock()
        mock_manager.work_dir = tmp_path / "Desktop" / "linkedin-sourcing"
        mock_manager_class.return_value = mock_manager

        result = bp.get_work_dir(None)

        assert result == tmp_path / "Desktop" / "linkedin-sourcing"


class TestExtractTiktokMetadata:
    """Tests for TikTok job page metadata extraction."""

    def test_extracts_title_from_h1(self):
        """Should extract title from h1 tag."""
        html = "<html><body><h1>Senior ML Engineer</h1></body></html>"
        result = bp.extract_tiktok_metadata(html)
        assert result["position_title"] == "Senior ML Engineer"

    def test_extracts_title_from_json_ld(self):
        """Should extract title from JSON-LD jobTitle."""
        html = '<script>{"jobTitle": "Staff Engineer - AI Platform"}</script>'
        result = bp.extract_tiktok_metadata(html)
        assert result["position_title"] == "Staff Engineer - AI Platform"

    def test_cleans_title_suffixes(self):
        """Should remove TikTok/ByteDance/Careers suffixes from title."""
        html = "<h1>Engineer - TikTok</h1>"
        result = bp.extract_tiktok_metadata(html)
        assert result["position_title"] == "Engineer"

    def test_extracts_location_from_json_ld(self):
        """Should extract location from JSON-LD address."""
        html = '{"jobLocation": {"address": {"addressLocality": "San Jose"}}}'
        result = bp.extract_tiktok_metadata(html)
        assert result["location"] == "San Jose"

    def test_extracts_location_from_visible_label_text(self):
        """Should extract location from visible page text when JSON-LD is absent."""
        html = "Location: San Jose Employment Type: Regular Job Code: A231202"
        result = bp.extract_tiktok_metadata(html)
        assert result["location"] == "San Jose"

    def test_extracts_location_from_raw_nextjs_payload(self):
        """Should extract location from the raw Next.js payload structure."""
        html = '\\"Location\\",{\\"className\\":\\"flex gap-1\\",\\"children\\":[{\\"children\\":[\\"Location\\",\\":\\"]},{\\"children\\":\\"San Jose\\"}]}'
        result = bp.extract_tiktok_metadata(html)
        assert result["location"] == "San Jose"

    def test_extracts_job_code_from_url_pattern(self):
        """Should extract job code from TikTok URL pattern."""
        html = "some content with /search/7623929928426277125 in it"
        result = bp.extract_tiktok_metadata(html)
        assert result["job_code"] == "7623929928426277125"

    def test_extracts_job_code_from_requisition(self):
        """Should extract job code from requisition ID pattern."""
        html = 'requisition_id: "REQ-12345"'
        result = bp.extract_tiktok_metadata(html)
        assert result["job_code"] == "REQ-12345"

    def test_extracts_job_code_from_visible_label_text(self):
        """Should extract job code from visible page labels."""
        html = "Location: San Jose Employment Type: Regular Job Code: A231202"
        result = bp.extract_tiktok_metadata(html)
        assert result["job_code"] == "A231202"

    def test_extracts_job_code_from_raw_nextjs_payload(self):
        """Should extract job code from the raw Next.js payload structure."""
        html = '\\"Job Code\\",{\\"className\\":\\"flex gap-1\\",\\"children\\":[{\\"children\\":[\\"Job Code\\",\\":\\"]},{\\"children\\":\\"A231202\\"}]}'
        result = bp.extract_tiktok_metadata(html)
        assert result["job_code"] == "A231202"

    def test_extracts_team_name_from_page_category(self):
        """Should extract team name from the page category heading."""
        html = "Technology ## SoC Digital Design Engineer, Multimedia Lab"
        result = bp.extract_tiktok_metadata(html)
        assert result["team_name"] == "Technology"

    def test_extracts_core_function_business_impact_and_keywords(self):
        """Should infer richer defaults from the About the team section."""
        html = (
            "About the team: Our team is building scalable video codec hardware solutions "
            "(FPGA and ASIC) from the ground up to better serve billions of users. "
            "Responsibilities - RTL Implementation with Verilog/SystemVerilog and CDC checks."
        )
        result = bp.extract_tiktok_metadata(html)
        assert "video codec hardware solutions" in result["core_function"].lower()
        assert "billions of users" in result["business_impact"].lower()
        assert "Verilog" in result["keywords"]
        assert "SystemVerilog" in result["keywords"]
        assert "FPGA" in result["keywords"]
        assert "ASIC" in result["keywords"]

    def test_extracts_description_from_meta(self):
        """Should extract description from meta tag."""
        html = '<meta name="description" content="This is a job description that is long enough to pass the minimum length check of fifty characters">'
        result = bp.extract_tiktok_metadata(html)
        assert "job description" in result["description"]

    def test_returns_empty_for_missing_fields(self):
        """Should return empty strings for fields not found."""
        html = "<html><body>minimal content</body></html>"
        result = bp.extract_tiktok_metadata(html)
        assert result["position_title"] == ""
        assert result["location"] == ""
        assert result["job_code"] == ""


class TestInferTeamName:
    """Tests for team name inference from position title."""

    def test_infers_ai_ml_team(self):
        """Should infer AI/ML team for ML-related titles."""
        assert bp.infer_team_name("ML Engineer") == "AI/ML Platform"
        assert bp.infer_team_name("Machine Learning Scientist") == "AI/ML Platform"
        assert bp.infer_team_name("AI Research Engineer") == "AI/ML Platform"

    def test_infers_infrastructure_team(self):
        """Should infer Infrastructure for infra-related titles."""
        assert (
            bp.infer_team_name("Infrastructure Engineer") == "Infrastructure Platform"
        )
        assert bp.infer_team_name("Platform Engineer") == "Infrastructure Platform"

    def test_infers_hardware_team(self):
        """Should infer Engineering & Technology for hardware design titles."""
        assert (
            bp.infer_team_name("SoC Digital Design Engineer")
            == "Engineering & Technology"
        )
        assert bp.infer_team_name("ASIC RTL Engineer") == "Engineering & Technology"

    def test_infers_data_team(self):
        """Should infer Data Platform for data-related titles."""
        assert bp.infer_team_name("Data Engineer") == "Data Platform"
        assert bp.infer_team_name("Analytics Engineer") == "Data Platform"

    def test_infers_search_team(self):
        """Should infer Search & Recommendations for search-related titles."""
        assert bp.infer_team_name("Search Engineer") == "Search & Recommendations"
        assert (
            bp.infer_team_name("Recommendation Engineer") == "Search & Recommendations"
        )

    def test_defaults_to_engineering(self):
        """Should default to Engineering for unknown titles."""
        assert bp.infer_team_name("Software Engineer") == "Engineering"
        assert bp.infer_team_name("") == ""


class TestInferKeywords:
    """Tests for keyword inference from position title."""

    def test_infers_pytorch_keywords(self):
        """Should infer PyTorch-related keywords."""
        result = bp.infer_keywords("PyTorch Engineer")
        assert "PyTorch" in result
        assert "Deep Learning" in result

    def test_infers_cuda_keywords(self):
        """Should infer CUDA-related keywords."""
        result = bp.infer_keywords("CUDA Kernel Engineer")
        assert "CUDA" in result
        assert "GPU Optimization" in result

    def test_infers_distributed_keywords(self):
        """Should infer distributed training keywords."""
        result = bp.infer_keywords("Distributed Training Engineer")
        assert "Distributed Training" in result

    def test_returns_empty_for_no_match(self):
        """Should return empty string for unmatched titles."""
        assert bp.infer_keywords("General Engineer") == ""


class TestReadJdText:
    """Tests for JD text reading."""

    def test_reads_raw_text(self):
        """Should return text as-is when not prefixed with @."""
        text = "This is a job description"
        result = bp.read_jd_text(text)
        assert result == text

    def test_reads_from_file(self, tmp_path):
        """Should read from file when prefixed with @."""
        jd_file = tmp_path / "jd.txt"
        jd_file.write_text("Job description from file")
        result = bp.read_jd_text(f"@{jd_file}")
        assert result == "Job description from file"

    def test_raises_for_missing_file(self, tmp_path):
        """Should raise FileNotFoundError for missing files."""
        try:
            bp.read_jd_text("@/nonexistent/file.txt")
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass


class TestBuildConfig:
    """Tests for configuration building."""

    def test_uses_inferred_values(self):
        """Should use inferred values when no overrides."""
        inferred = {
            "position_title": "Senior Engineer",
            "team_name": "AI Team",
            "location": "San Francisco",
            "core_function": "building AI systems",
            "business_impact": "powering global products",
            "keywords": "PyTorch, CUDA",
        }
        overrides = {
            k: None
            for k in [
                "position_title",
                "team_name",
                "location",
                "core_function",
                "business_impact",
                "keywords",
                "companies",
                "exclude_titles",
                "recruiter_url",
            ]
        }

        config = bp.build_config("123", inferred, overrides)

        assert config["PROJECT_ID"] == "123"
        assert config["POSITION_TITLE"] == "Senior Engineer"
        assert config["TEAM_NAME"] == "AI Team"
        assert config["LOCATION"] == "San Francisco"
        assert config["CORE_FUNCTION"] == "building AI systems"
        assert config["BUSINESS_IMPACT"] == "powering global products"
        assert config["KEYWORDS"] == "PyTorch, CUDA"

    def test_overrides_take_precedence(self):
        """Override values should take precedence over inferred."""
        inferred = {"position_title": "Inferred Title"}
        overrides = {
            "position_title": "Override Title",
            "team_name": None,
            "location": None,
            "core_function": None,
            "business_impact": None,
            "keywords": None,
            "companies": None,
            "exclude_titles": None,
            "recruiter_url": None,
        }

        config = bp.build_config("123", inferred, overrides)

        assert config["POSITION_TITLE"] == "Override Title"

    def test_adds_recruiter_url_when_provided(self):
        """Should add RECRUITER_PROJECT_URL when provided."""
        inferred = {}
        overrides = {
            "position_title": None,
            "team_name": None,
            "location": None,
            "core_function": None,
            "business_impact": None,
            "keywords": None,
            "companies": None,
            "exclude_titles": None,
            "recruiter_url": "https://linkedin.com/talent/hire/123",
        }

        config = bp.build_config("123", inferred, overrides)

        assert config["RECRUITER_PROJECT_URL"] == "https://linkedin.com/talent/hire/123"

    def test_uses_placeholders_for_missing_fields(self):
        """Should use placeholder text for required fields not provided."""
        inferred = {}
        overrides = {
            k: None
            for k in [
                "position_title",
                "team_name",
                "location",
                "core_function",
                "business_impact",
                "keywords",
                "companies",
                "exclude_titles",
                "recruiter_url",
            ]
        }

        config = bp.build_config("123", inferred, overrides)

        assert "[POSITION TITLE - PLEASE UPDATE]" in config["POSITION_TITLE"]
        assert "[LOCATION - PLEASE UPDATE]" in config["LOCATION"]
        assert "[CORE FUNCTION - PLEASE UPDATE]" in config["CORE_FUNCTION"]

    def test_preserves_existing_config_values(self):
        """Should preserve existing config values when reusing a project."""
        inferred = {"position_title": "Inferred Title"}
        overrides = {
            "position_title": None,
            "team_name": None,
            "location": None,
            "core_function": None,
            "business_impact": None,
            "keywords": None,
            "companies": None,
            "exclude_titles": None,
            "recruiter_url": None,
        }
        existing = {
            "POSITION_TITLE": "Existing Title",
            "TEAM_NAME": "Existing Team",
            "LOCATION": "Existing Location",
            "CORE_FUNCTION": "Existing Function",
            "BUSINESS_IMPACT": "Existing Impact",
            "KEYWORDS": "Existing Keywords",
            "COMPANIES": "Existing Companies",
            "EXCLUDE_TITLES": "Existing Titles",
        }

        config = bp.build_config("123", inferred, overrides, existing)

        # Existing values should be preserved
        assert config["POSITION_TITLE"] == "Existing Title"
        assert config["TEAM_NAME"] == "Existing Team"
        assert config["LOCATION"] == "Existing Location"
        assert config["CORE_FUNCTION"] == "Existing Function"
        assert config["BUSINESS_IMPACT"] == "Existing Impact"
        assert config["KEYWORDS"] == "Existing Keywords"
        assert config["COMPANIES"] == "Existing Companies"
        assert config["EXCLUDE_TITLES"] == "Existing Titles"

    def test_overrides_take_precedence_over_existing(self):
        """CLI overrides should take precedence over existing config values."""
        inferred = {}
        overrides = {
            "position_title": "Override Title",
            "team_name": None,
            "location": None,
            "core_function": None,
            "business_impact": None,
            "keywords": None,
            "companies": None,
            "exclude_titles": None,
            "recruiter_url": None,
        }
        existing = {
            "POSITION_TITLE": "Existing Title",
            "TEAM_NAME": "Existing Team",
        }

        config = bp.build_config("123", inferred, overrides, existing)

        # Override should win
        assert config["POSITION_TITLE"] == "Override Title"
        # Existing should be preserved when no override
        assert config["TEAM_NAME"] == "Existing Team"

    def test_inferred_used_when_no_existing_or_override(self):
        """Inferred values should be used when no existing or override."""
        inferred = {
            "position_title": "Inferred Title",
            "team_name": "Inferred Team",
        }
        overrides = {
            "position_title": None,
            "team_name": None,
            "location": None,
            "core_function": None,
            "business_impact": None,
            "keywords": None,
            "companies": None,
            "exclude_titles": None,
            "recruiter_url": None,
        }
        existing = {}  # No existing values

        config = bp.build_config("123", inferred, overrides, existing)

        assert config["POSITION_TITLE"] == "Inferred Title"
        assert config["TEAM_NAME"] == "Inferred Team"

    def test_skips_placeholder_existing_values(self):
        """Should skip existing values that are placeholders."""
        inferred = {"position_title": "Inferred Title"}
        overrides = {
            "position_title": None,
            "team_name": None,
            "location": None,
            "core_function": None,
            "business_impact": None,
            "keywords": None,
            "companies": None,
            "exclude_titles": None,
            "recruiter_url": None,
        }
        existing = {
            "POSITION_TITLE": "[POSITION TITLE - PLEASE UPDATE]",
            "TEAM_NAME": "[TEAM NAME - PLEASE UPDATE]",
        }

        config = bp.build_config("123", inferred, overrides, existing)

        # Placeholders should be skipped, use inferred instead
        assert config["POSITION_TITLE"] == "Inferred Title"
        # Team name uses inference function when placeholder
        assert config["TEAM_NAME"] != "[TEAM NAME - PLEASE UPDATE]"

    def test_preserves_rate_limit_settings(self):
        """Should preserve existing rate limit settings."""
        inferred = {}
        overrides = {
            "position_title": "Title",
            "team_name": None,
            "location": None,
            "core_function": None,
            "business_impact": None,
            "keywords": None,
            "companies": None,
            "exclude_titles": None,
            "recruiter_url": None,
        }
        existing = {
            "DAILY_LIMIT": "500",
            "CANDIDATE_DELAY_SEC": "5",
        }

        config = bp.build_config("123", inferred, overrides, existing)

        assert config["DAILY_LIMIT"] == "500"
        assert config["CANDIDATE_DELAY_SEC"] == "5"

    def test_uses_defaults_when_no_existing_rate_limits(self):
        """Should use default rate limits when no existing values."""
        inferred = {}
        overrides = {
            "position_title": "Title",
            "team_name": None,
            "location": None,
            "core_function": None,
            "business_impact": None,
            "keywords": None,
            "companies": None,
            "exclude_titles": None,
            "recruiter_url": None,
        }
        existing = {}

        config = bp.build_config("123", inferred, overrides, existing)

        assert config["DAILY_LIMIT"] == "200"
        assert config["CANDIDATE_DELAY_SEC"] == "10"


class TestParseExistingConfig:
    """Tests for parse_existing_config function."""

    def test_parses_double_quoted_values(self, tmp_path):
        """Should parse double-quoted values from existing config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            'PROJECT_ID="my_project"\n'
            'POSITION_TITLE="Senior Engineer"\n'
            'TEAM_NAME="AI Team"\n'
        )

        result = bp.parse_existing_config(config_file)

        assert result["PROJECT_ID"] == "my_project"
        assert result["POSITION_TITLE"] == "Senior Engineer"
        assert result["TEAM_NAME"] == "AI Team"

    def test_parses_single_quoted_values(self, tmp_path):
        """Should parse single-quoted values from existing config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID='my_project'\nPOSITION_TITLE='Engineer'")

        result = bp.parse_existing_config(config_file)

        assert result["PROJECT_ID"] == "my_project"
        assert result["POSITION_TITLE"] == "Engineer"

    def test_parses_unquoted_values(self, tmp_path):
        """Should parse unquoted values from existing config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID=my_project\nDAILY_LIMIT=200")

        result = bp.parse_existing_config(config_file)

        assert result["PROJECT_ID"] == "my_project"
        assert result["DAILY_LIMIT"] == "200"

    def test_ignores_comments_and_empty_lines(self, tmp_path):
        """Should ignore comments and empty lines."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            "# This is a comment\n"
            'PROJECT_ID="my_project"\n'
            "\n"
            "# Another comment\n"
            'POSITION_TITLE="Engineer"'
        )

        result = bp.parse_existing_config(config_file)

        assert result["PROJECT_ID"] == "my_project"
        assert result["POSITION_TITLE"] == "Engineer"
        assert "# This is a comment" not in result

    def test_returns_empty_for_missing_file(self, tmp_path):
        """Should return empty dict for missing file."""
        result = bp.parse_existing_config(tmp_path / "nonexistent.sh")
        assert result == {}


class TestShellEscape:
    """Tests for shell escaping function."""

    def test_escapes_quotes(self):
        """Should escape double quotes in values using single quotes."""
        result = bp.shell_escape('Engineer "AI" Role')
        # shlex.quote wraps the whole string in single quotes when it contains special chars
        assert result == "'Engineer \"AI\" Role'"

    def test_escapes_newlines(self):
        """Should escape newlines in values."""
        result = bp.shell_escape("Line 1\nLine 2")
        # Newlines require $'' quoting in bash
        assert "Line 1" in result
        assert "Line 2" in result

    def test_escapes_backslashes(self):
        """Should escape backslashes in values."""
        result = bp.shell_escape("path\\to\\file")
        # Backslashes in single-quoted strings need special handling
        assert "path" in result
        assert "to" in result
        assert "file" in result

    def test_simple_value_no_quotes_needed(self):
        """Simple alphanumeric values don't need quotes."""
        result = bp.shell_escape("Engineer")
        # shlex.quote only adds quotes when necessary
        assert result == "Engineer"

    def test_empty_string(self):
        """Empty string should be handled."""
        result = bp.shell_escape("")
        assert result == "''"

    def test_value_with_spaces_gets_quoted(self):
        """Values with spaces should be single-quoted."""
        result = bp.shell_escape("San Francisco")
        assert result == "'San Francisco'"


class TestWriteConfig:
    """Tests for config file writing."""

    def test_creates_config_file(self, tmp_path):
        """Should create config.sh with correct content."""
        config = {
            "PROJECT_ID": "123",
            "POSITION_TITLE": "Engineer",
            "TEAM_NAME": "AI",
            "LOCATION": "SF",
            "CORE_FUNCTION": "building AI",
            "BUSINESS_IMPACT": "improving products",
            "KEYWORDS": "ML, AI",
            "COMPANIES": "Google, Meta",
            "EXCLUDE_TITLES": "Manager",
            "DAILY_LIMIT": "200",
            "CANDIDATE_DELAY_SEC": "10",
        }
        config_path = tmp_path / "config.sh"

        bp.write_config(config, config_path)

        assert config_path.exists()
        content = config_path.read_text()
        # Simple values don't need quotes, values with spaces get single-quoted
        assert "PROJECT_ID=123" in content
        assert "POSITION_TITLE=Engineer" in content
        assert "TEAM_NAME=AI" in content
        assert "LOCATION=SF" in content
        assert "CORE_FUNCTION='building AI'" in content
        assert "KEYWORDS='ML, AI'" in content
        assert "COMPANIES='Google, Meta'" in content

    def test_escapes_special_characters(self, tmp_path):
        """Should properly escape special shell characters."""
        config = {
            "PROJECT_ID": "123",
            "POSITION_TITLE": 'Engineer "AI/ML" Role',
            "TEAM_NAME": "AI",
            "LOCATION": "SF",
            "CORE_FUNCTION": "building AI",
            "BUSINESS_IMPACT": "improving products",
            "KEYWORDS": "ML, AI",
            "COMPANIES": "Google, Meta",
            "EXCLUDE_TITLES": "Manager",
            "DAILY_LIMIT": "200",
            "CANDIDATE_DELAY_SEC": "10",
        }
        config_path = tmp_path / "config.sh"

        bp.write_config(config, config_path)

        content = config_path.read_text()
        # Value should be properly escaped with single quotes
        assert "POSITION_TITLE='Engineer \"AI/ML\" Role'" in content

    def test_includes_recruiter_url_when_present(self, tmp_path):
        """Should include RECRUITER_PROJECT_URL when in config."""
        config = {
            "PROJECT_ID": "123",
            "POSITION_TITLE": "Engineer",
            "TEAM_NAME": "AI",
            "LOCATION": "SF",
            "CORE_FUNCTION": "building AI",
            "BUSINESS_IMPACT": "improving products",
            "KEYWORDS": "ML",
            "COMPANIES": "Google",
            "EXCLUDE_TITLES": "Manager",
            "DAILY_LIMIT": "200",
            "CANDIDATE_DELAY_SEC": "10",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123",
        }
        config_path = tmp_path / "config.sh"

        bp.write_config(config, config_path)

        content = config_path.read_text()
        assert "RECRUITER_PROJECT_URL" in content
        assert "https://linkedin.com/talent/hire/123" in content

    def test_creates_parent_directory(self, tmp_path):
        """Should create parent directories if they don't exist."""
        config = {
            "PROJECT_ID": "123",
            "POSITION_TITLE": "Engineer",
            "TEAM_NAME": "AI",
            "LOCATION": "SF",
            "CORE_FUNCTION": "building AI",
            "BUSINESS_IMPACT": "improving products",
            "KEYWORDS": "ML",
            "COMPANIES": "Google",
            "EXCLUDE_TITLES": "Manager",
            "DAILY_LIMIT": "200",
            "CANDIDATE_DELAY_SEC": "10",
        }
        config_path = tmp_path / "nested" / "dir" / "config.sh"

        bp.write_config(config, config_path)

        assert config_path.exists()


class TestFetchUrl:
    """Tests for URL fetching."""

    @patch("urllib.request.urlopen")
    def test_successful_fetch(self, mock_urlopen):
        """Should return 200 and content on success."""
        mock_response = Mock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b"<html>content</html>"
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        status, content = bp.fetch_url("https://example.com")

        assert status == 200
        assert content == "<html>content</html>"

    @patch("urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        """Should return error status on HTTP error."""
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://example.com",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )

        status, content = bp.fetch_url("https://example.com")

        assert status == 404
        assert "Not Found" in content


class TestCheckExistingProjectByRecruiterId:
    """Tests for checking existing projects by recruiter ID."""

    def test_finds_existing_project(self, tmp_path):
        """Should find existing project with matching recruiter ID."""
        # Create existing project structure
        projects_dir = tmp_path / "projects" / "existing_project"
        projects_dir.mkdir(parents=True)
        config_path = projects_dir / "config.sh"
        config_path.write_text(
            'PROJECT_ID="existing_project"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/discover/recruiterSearch"\n'
        )

        result = bp.check_existing_project_by_recruiter_id(tmp_path, "12345")

        assert result == config_path

    def test_returns_none_for_nonexistent_project(self, tmp_path):
        """Should return None when no project matches recruiter ID."""
        result = bp.check_existing_project_by_recruiter_id(tmp_path, "99999")
        assert result is None

    def test_returns_none_when_no_projects_dir(self, tmp_path):
        """Should return None when projects directory doesn't exist."""
        result = bp.check_existing_project_by_recruiter_id(tmp_path, "12345")
        assert result is None

    def test_handles_different_url_formats(self, tmp_path):
        """Should match various Recruiter URL formats."""
        projects_dir = tmp_path / "projects" / "project1"
        projects_dir.mkdir(parents=True)
        config_path = projects_dir / "config.sh"
        config_path.write_text(
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/67890/overview"\n'
        )

        result = bp.check_existing_project_by_recruiter_id(tmp_path, "67890")

        assert result == config_path


class TestEnsureRecruiterProjectAndGetId:
    """Tests for ensure_recruiter_project integration."""

    @patch("ensure_recruiter_project.ensure_project_exists")
    def test_returns_project_id_on_success(self, mock_ensure, tmp_path):
        """Should return project_id when ensure_project succeeds."""
        mock_ensure.return_value = {
            "status": "created",
            "project_id": "12345",
            "url": "https://linkedin.com/talent/hire/12345/overview",
            "message": "Created new project",
        }

        result = bp.ensure_recruiter_project_and_get_id(
            project_name="Test Project",
            description="Test description",
            cdp_port="9230",
            work_dir=tmp_path,
        )

        assert result["success"] is True
        assert result["project_id"] == "12345"
        assert result["url"] == "https://linkedin.com/talent/hire/12345/overview"

    @patch("ensure_recruiter_project.ensure_project_exists")
    def test_returns_failure_on_error(self, mock_ensure, tmp_path):
        """Should return failure when ensure_project fails."""
        mock_ensure.return_value = {
            "status": "error",
            "project_id": None,
            "url": None,
            "message": "Navigation failed",
        }

        result = bp.ensure_recruiter_project_and_get_id(
            project_name="Test Project",
            description="Test description",
            cdp_port="9230",
            work_dir=tmp_path,
        )

        assert result["success"] is False
        assert result["project_id"] is None
        assert "Navigation failed" in result["message"]

    @patch("ensure_recruiter_project.ensure_project_exists")
    def test_uses_require_contextual_url_false(self, mock_ensure, tmp_path):
        """Should call ensure_project_exists with require_contextual_url=False."""
        mock_ensure.return_value = {
            "status": "created",
            "project_id": "12345",
            "url": "https://linkedin.com/talent/hire/12345/overview",
            "message": "Created",
        }

        bp.ensure_recruiter_project_and_get_id(
            project_name="Test",
            description="",
            cdp_port="9230",
            work_dir=tmp_path,
        )

        call_kwargs = mock_ensure.call_args[1]
        assert call_kwargs["require_contextual_url"] is False


class TestBootstrapProject:
    """Integration tests for full bootstrap flow with Recruiter-derived PROJECT_ID."""

    def test_uses_provided_recruiter_url_to_derive_project_id(
        self, tmp_path, monkeypatch
    ):
        """Should extract PROJECT_ID from provided --recruiter-url."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "This is a job description"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None  # Not overriding
        args.position_title = "Senior Engineer"
        args.team_name = None
        args.location = "San Francisco"
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # PROJECT_ID should be derived from Recruiter URL
        assert result["project_id"] == "12345"
        # New layout: folder name includes title slug
        assert "12345" in result["project_dir"]
        assert "senior-engineer" in result["project_dir"].lower()
        # Workbook should be inside project dir (new layout)
        assert result["workbook_path"].endswith("workbook.xlsx")
        assert Path(result["workbook_path"]).parent.name.startswith("12345_")
        assert result["recruiter_url"] == args.recruiter_url

        # Check files were created
        assert Path(result["config_path"]).exists()
        assert Path(result["jd_path"]).exists()
        assert Path(result["workbook_path"]).exists()

    @patch("bootstrap_project.ensure_recruiter_project_and_get_id")
    def test_creates_recruiter_project_when_no_url_provided(
        self, mock_ensure, tmp_path, monkeypatch
    ):
        """Should create Recruiter project and derive PROJECT_ID when no URL provided."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        mock_ensure.return_value = {
            "success": True,
            "project_id": "67890",
            "url": "https://linkedin.com/talent/hire/67890/overview",
            "status": "created",
            "message": "Created new project",
        }

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = None  # No URL provided
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "ML Engineer"
        args.team_name = "AI Team"
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # PROJECT_ID should be derived from created Recruiter project
        assert result["project_id"] == "67890"
        mock_ensure.assert_called_once()

        # Check the project name was passed correctly
        call_args = mock_ensure.call_args[1]
        assert call_args["project_name"] == "ML Engineer"

    def test_allows_explicit_project_id_override(self, tmp_path, monkeypatch):
        """Should allow --project-id override for advanced use cases."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
        args.cdp_port = "9230"
        args.project_id = "custom_id"  # Explicit override
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should use explicit project_id
        assert result["project_id"] == "custom_id"

    def test_fails_closed_on_invalid_recruiter_url(self, tmp_path, monkeypatch):
        """Should fail closed when recruiter URL doesn't contain valid project ID."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = "https://invalid-url.com/no-project-id"
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        try:
            bp.bootstrap_project(args)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Could not extract project ID" in str(e)

    def test_fails_closed_on_invalid_recruiter_url_even_with_project_id_override(
        self, tmp_path, monkeypatch
    ):
        """Should fail closed when recruiter URL is invalid even if --project-id is provided.

        This is a security measure: if the user provides a recruiter URL, it must be valid
        before any local files are written, regardless of other overrides.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = "https://invalid-url.com/no-project-id"
        args.cdp_port = "9230"
        args.project_id = "custom_override_id"  # Override provided
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        try:
            bp.bootstrap_project(args)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Could not extract project ID" in str(e)

        # Verify no files were written
        work_dir = tmp_path / "work"
        assert not (work_dir / "projects").exists() or not any(
            (work_dir / "projects").iterdir()
        )

    @patch("bootstrap_project.ensure_recruiter_project_and_get_id")
    def test_fails_closed_when_recruiter_creation_fails(
        self, mock_ensure, tmp_path, monkeypatch
    ):
        """Should fail closed when ensure_recruiter_project fails."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        mock_ensure.return_value = {
            "success": False,
            "project_id": None,
            "url": None,
            "status": "error",
            "message": "Chrome not running with CDP",
        }

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = None
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        try:
            bp.bootstrap_project(args)
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "Failed to ensure Recruiter project" in str(e)

    def test_reuses_existing_project_when_explicit_override_conflicts_with_recruiter_id(
        self, tmp_path, monkeypatch
    ):
        """Should reuse existing project when explicit --project-id conflicts with existing Recruiter ID.

        The Recruiter ID is authoritative. If an existing project already maps to the same
        Recruiter ID, reuse it regardless of the requested project_id override.
        This prevents duplicate projects for the same Recruiter search.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with recruiter ID 12345
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "existing_proj"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="existing_proj"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'POSITION_TITLE="Old Title"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = "different_id"  # Would prefer different local ID
        args.position_title = "New Title"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse existing project (Recruiter ID is authoritative)
        assert result["project_id"] == "existing_proj"
        assert "existing_proj" in result["project_dir"]

        # Config should be updated
        config_content = Path(result["config_path"]).read_text()
        assert "New Title" in config_content

        # Should NOT create the requested "different_id" project
        different_project = work_dir / "projects" / "different_id"
        assert not different_project.exists()

    def test_reuses_existing_project_with_same_id(self, tmp_path, monkeypatch):
        """Should reuse existing project when same PROJECT_ID and Recruiter ID."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with recruiter ID 12345 (new layout)
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_updated-title"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "Updated JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Updated Title"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse same project (found by scanning config.sh for PROJECT_ID)
        assert result["project_id"] == "12345"
        assert "12345_updated-title" in result["project_dir"]
        # Config should be updated
        config_content = Path(result["config_path"]).read_text()
        assert "Updated Title" in config_content

    def test_preserves_existing_workbook_when_reusing_project(
        self, tmp_path, monkeypatch
    ):
        """Should preserve existing workbook data when reusing a project.

        Regression test: Previously, bootstrap would recreate the workbook on every run,
        wiping out existing candidate data. Now it should only create if missing.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with recruiter ID 12345 and existing workbook (new layout)
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_updated-title"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
        )

        # Create an existing workbook inside project dir (new layout)
        workbook_path = existing_project / "workbook.xlsx"
        workbook_path.write_text("existing workbook data")

        args = Mock()
        args.jd_url = None
        args.jd_text = "Updated JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Updated Title"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse same project (found by scanning config.sh for PROJECT_ID)
        assert result["project_id"] == "12345"
        # Workbook should still contain original data (not be overwritten)
        assert workbook_path.read_text() == "existing workbook data"
        # Result should point to the existing workbook
        assert result["workbook_path"] == str(workbook_path)

    def test_preserves_workbook_for_legacy_project_reuse(self, tmp_path, monkeypatch):
        """Should preserve workbook when reusing a legacy project (different directory name)."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing LEGACY project with slug-based name but recruiter ID 12345
        work_dir = tmp_path / "work"
        legacy_project = work_dir / "projects" / "soc-design-engineer-2024"
        legacy_project.mkdir(parents=True)
        config_path = legacy_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="soc-design-engineer-2024"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
        )

        # Create an existing workbook for the legacy project
        workbook_path = work_dir / "projects" / "soc-design-engineer-2024.xlsx"
        workbook_path.write_text("legacy workbook with candidate data")

        args = Mock()
        args.jd_url = None
        args.jd_text = "Updated JD content"
        args.work_dir = str(work_dir)
        # New bootstrap with same recruiter ID but would derive different numeric ID
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Updated Title"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse the LEGACY project directory
        assert result["project_id"] == "soc-design-engineer-2024"
        # Workbook should still contain original data
        assert workbook_path.read_text() == "legacy workbook with candidate data"
        # Verify NO new numeric directory or workbook was created
        numeric_workbook = work_dir / "projects" / "12345.xlsx"
        assert not numeric_workbook.exists()

    def test_reuses_legacy_project_with_same_recruiter_id(self, tmp_path, monkeypatch):
        """Should reuse/update legacy project when it maps to same Recruiter ID.

        This supports backward compatibility for existing projects that use
        slug-based or timestamp-based directory names instead of numeric IDs.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing LEGACY project with slug-based name but recruiter ID 12345
        work_dir = tmp_path / "work"
        legacy_project = work_dir / "projects" / "soc-design-engineer-2024"
        legacy_project.mkdir(parents=True)
        config_path = legacy_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="soc-design-engineer-2024"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'POSITION_TITLE="Old Title"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "Updated JD content"
        args.work_dir = str(work_dir)
        # New bootstrap with same recruiter ID but would derive different numeric ID
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None  # Would derive "12345" but legacy project exists
        args.position_title = "Updated Title"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse the LEGACY project directory, not create new numeric one
        assert result["project_id"] == "soc-design-engineer-2024"
        assert "soc-design-engineer-2024" in result["project_dir"]
        # Config should be updated with new values
        config_content = Path(result["config_path"]).read_text()
        assert "Updated Title" in config_content
        assert "12345" in config_content  # Recruiter URL should be preserved/updated

        # Verify NO new numeric directory was created
        numeric_project = work_dir / "projects" / "12345"
        assert not numeric_project.exists(), (
            "Should not create numeric directory when legacy exists"
        )

    def test_reuses_legacy_project_with_timestamp_name(self, tmp_path, monkeypatch):
        """Should reuse legacy project with timestamp-based directory name."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with timestamp-based name
        work_dir = tmp_path / "work"
        legacy_project = work_dir / "projects" / "project-20240115-143022"
        legacy_project.mkdir(parents=True)
        config_path = legacy_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="project-20240115-143022"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/67890/overview"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "New JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/67890/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "New Title"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse timestamp-based project
        assert result["project_id"] == "project-20240115-143022"
        assert "project-20240115-143022" in result["project_dir"]

    def test_creates_new_project_when_no_legacy_conflict(self, tmp_path, monkeypatch):
        """Should create new project with title slug when no legacy project has same recruiter ID."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with DIFFERENT recruiter ID
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "legacy-project"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="legacy-project"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/99999/overview"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(work_dir)
        # Different recruiter ID - should create new project
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/11111/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "ML Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should create new project with title slug (new canonical layout)
        assert result["project_id"] == "11111"
        assert "11111" in result["project_dir"]
        assert "ml-engineer" in result["project_dir"].lower()
        # Workbook should be inside project directory
        assert result["workbook_path"].endswith("workbook.xlsx")
        assert Path(result["workbook_path"]).parent.name.startswith("11111_")

    def test_next_steps_with_search_url(self, tmp_path, monkeypatch):
        """Should indicate ready for extraction when search URL is available."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/discover/recruiterSearch?searchContextId=abc"
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        next_steps_text = "\n".join(result["next_steps"])
        assert "ready for extraction" in next_steps_text.lower()

    def test_next_steps_without_search_url(self, tmp_path, monkeypatch):
        """Should indicate need for ensure_recruiter_project when only overview URL."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/overview"
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        next_steps_text = "\n".join(result["next_steps"])
        assert "ensure_recruiter_project" in next_steps_text

    def test_jd_text_derives_title_from_content_no_explicit_title(
        self, tmp_path, monkeypatch
    ):
        """JD-text bootstrap should derive title from content when no --position-title.

        Instead of creating a folder named 'extract-from-jd', it should extract
        the title from the first line of JD content.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = (
            "LLM Training Engineer\n\nWe are looking for an experienced engineer..."
        )
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = None  # No explicit title
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should derive title from JD content
        assert result["project_id"] == "12345"
        # Folder should contain the derived title slug, not "extract-from-jd"
        assert "llm-training-engineer" in result["project_dir"].lower()
        assert "extract-from-jd" not in result["project_dir"].lower()
        # Inferred position_title should be the extracted title
        assert result["inferred"]["position_title"] == "LLM Training Engineer"

    def test_jd_text_with_title_prefix_derives_clean_title(self, tmp_path, monkeypatch):
        """Should strip 'Title:' prefix when deriving title from JD content."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "Title: Senior ML Engineer\n\nDescription..."
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = None
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should strip the prefix and use clean title
        assert "senior-ml-engineer" in result["project_dir"].lower()
        assert result["inferred"]["position_title"] == "Senior ML Engineer"

    @patch("bootstrap_project.fetch_url")
    def test_generic_jd_url_derives_title_from_html(
        self, mock_fetch, tmp_path, monkeypatch
    ):
        """Generic JD URLs should derive a clean title from HTML content."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)
        mock_fetch.return_value = (
            200,
            """
            <!doctype html>
            <html>
              <head><title>LLM Training Engineer | Example Company</title></head>
              <body>
                <h1>LLM Training Engineer</h1>
                <p>We are looking for an experienced engineer...</p>
              </body>
            </html>
            """,
        )

        args = Mock()
        args.jd_url = "https://example.com/jobs/123"
        args.jd_text = None
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = None
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        assert result["project_id"] == "12345"
        assert "llm-training-engineer" in result["project_dir"].lower()
        assert "extract-from-jd" not in result["project_dir"].lower()
        assert result["inferred"]["position_title"] == "LLM Training Engineer"

    def test_jd_text_explicit_title_takes_precedence(self, tmp_path, monkeypatch):
        """Explicit --position-title should take precedence over JD content."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "LLM Training Engineer\n\nDescription..."
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Custom Title"  # Explicit override
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should use explicit title, not derived from JD
        assert "custom-title" in result["project_dir"].lower()
        assert result["inferred"]["position_title"] == "Custom Title"

    def test_jd_text_fallback_when_no_meaningful_title(self, tmp_path, monkeypatch):
        """Should use safe fallback when JD content has no meaningful title."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        # JD with only URLs and markers, no real title
        args.jd_text = "https://example.com/job\n---\n\n#\n\nSome description here"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = None
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should still create project with project_id
        assert result["project_id"] == "12345"
        # Folder should use project_id with "project" fallback slug
        assert (
            "12345_project" in result["project_dir"] or "12345" in result["project_dir"]
        )
        # Position title should be placeholder
        assert "[EXTRACT FROM JD]" in result["inferred"]["position_title"]

    def test_preserves_existing_config_when_reusing_project(
        self, tmp_path, monkeypatch
    ):
        """Should preserve existing curated config values when reusing a project.

        When bootstrap reuses an existing project (same Recruiter ID), it should
        preserve existing curated values like TEAM_NAME, LOCATION, CORE_FUNCTION,
        BUSINESS_IMPACT, KEYWORDS, COMPANIES, EXCLUDE_TITLES unless the user
        explicitly provides overrides.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with curated config values
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'POSITION_TITLE="Existing Title"\n'
            'TEAM_NAME="Existing Team"\n'
            'LOCATION="Existing Location"\n'
            'CORE_FUNCTION="Existing Function"\n'
            'BUSINESS_IMPACT="Existing Impact"\n'
            'KEYWORDS="Existing Keywords"\n'
            'COMPANIES="Existing Companies"\n'
            'EXCLUDE_TITLES="Existing Titles"\n'
            'DAILY_LIMIT="500"\n'
            'CANDIDATE_DELAY_SEC="5"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "New JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        # No overrides - should preserve all existing values
        args.position_title = None
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse same project
        assert result["project_id"] == "12345"

        # Config should preserve existing curated values (shell_escape uses single quotes for values with spaces)
        config_content = Path(result["config_path"]).read_text()
        assert "POSITION_TITLE='Existing Title'" in config_content
        assert "TEAM_NAME='Existing Team'" in config_content
        assert "LOCATION='Existing Location'" in config_content
        assert "CORE_FUNCTION='Existing Function'" in config_content
        assert "BUSINESS_IMPACT='Existing Impact'" in config_content
        assert "KEYWORDS='Existing Keywords'" in config_content
        assert "COMPANIES='Existing Companies'" in config_content
        assert "EXCLUDE_TITLES='Existing Titles'" in config_content
        assert "DAILY_LIMIT=500" in config_content
        assert "CANDIDATE_DELAY_SEC=5" in config_content

    def test_overrides_preserve_existing_config_when_reusing_project(
        self, tmp_path, monkeypatch
    ):
        """CLI overrides should take precedence over existing config when reusing."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with curated config values
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'POSITION_TITLE="Existing Title"\n'
            'TEAM_NAME="Existing Team"\n'
            'LOCATION="Existing Location"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "New JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        # Override some values
        args.position_title = "Override Title"
        args.team_name = None  # Should preserve existing
        args.location = "Override Location"
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Config should have overrides for specified fields, existing for others
        config_content = Path(result["config_path"]).read_text()
        assert "POSITION_TITLE='Override Title'" in config_content  # overridden
        assert "TEAM_NAME='Existing Team'" in config_content  # preserved
        assert "LOCATION='Override Location'" in config_content  # overridden

    def test_preserves_existing_config_for_legacy_project_reuse(
        self, tmp_path, monkeypatch
    ):
        """Should preserve existing config when reusing a legacy project."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing LEGACY project with curated config
        work_dir = tmp_path / "work"
        legacy_project = work_dir / "projects" / "soc-design-2024"
        legacy_project.mkdir(parents=True)
        config_path = legacy_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="soc-design-2024"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'POSITION_TITLE="SoC Design Engineer"\n'
            'TEAM_NAME="Hardware Team"\n'
            'LOCATION="San Jose, CA"\n'
            'CORE_FUNCTION="Designing SoC components"\n'
            'BUSINESS_IMPACT="Powering next-gen hardware"\n'
            'KEYWORDS="Verilog, SystemVerilog, ASIC"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "New JD content"
        args.work_dir = str(work_dir)
        # Same recruiter ID - should reuse legacy project
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        # No overrides
        args.position_title = None
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse legacy project
        assert result["project_id"] == "soc-design-2024"

        # Config should preserve existing curated values (shell_escape uses single quotes for values with spaces)
        config_content = Path(result["config_path"]).read_text()
        assert "TEAM_NAME='Hardware Team'" in config_content
        assert "LOCATION='San Jose, CA'" in config_content
        assert "CORE_FUNCTION='Designing SoC components'" in config_content
        assert "BUSINESS_IMPACT='Powering next-gen hardware'" in config_content
        assert "KEYWORDS='Verilog, SystemVerilog, ASIC'" in config_content


class TestParseArgs:
    """Tests for argument parsing."""

    def test_requires_jd_url_or_text(self):
        """Should require either --jd-url or --jd-text."""
        try:
            bp.parse_args()
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass

    def test_accepts_jd_url(self):
        """Should accept --jd-url argument."""
        with patch.object(sys, "argv", ["script", "--jd-url", "https://example.com"]):
            args = bp.parse_args()
            assert args.jd_url == "https://example.com"
            assert args.jd_text is None

    def test_accepts_jd_text(self):
        """Should accept --jd-text argument."""
        with patch.object(sys, "argv", ["script", "--jd-text", "Job description"]):
            args = bp.parse_args()
            assert args.jd_text == "Job description"
            assert args.jd_url is None

    def test_accepts_recruiter_url(self):
        """Should accept --recruiter-url argument."""
        argv = [
            "script",
            "--jd-url",
            "https://example.com",
            "--recruiter-url",
            "https://linkedin.com/talent/hire/123",
        ]
        with patch.object(sys, "argv", argv):
            args = bp.parse_args()
            assert args.recruiter_url == "https://linkedin.com/talent/hire/123"

    def test_accepts_cdp_port(self):
        """Should accept --cdp-port argument."""
        argv = ["script", "--jd-url", "https://example.com", "--cdp-port", "9231"]
        with patch.object(sys, "argv", argv):
            args = bp.parse_args()
            assert args.cdp_port == "9231"

    def test_uses_default_cdp_port(self):
        """Should use default CDP port when not specified."""
        with patch.object(sys, "argv", ["script", "--jd-url", "https://example.com"]):
            args = bp.parse_args()
            assert args.cdp_port == "9230"

    def test_accepts_all_overrides(self):
        """Should accept all override arguments."""
        argv = [
            "script",
            "--jd-url",
            "https://example.com",
            "--position-title",
            "Senior Engineer",
            "--team-name",
            "AI Platform",
            "--location",
            "Remote",
            "--core-function",
            "Building ML infra",
            "--business-impact",
            "Improving products",
            "--keywords",
            "PyTorch, CUDA",
            "--companies",
            "Google, Meta",
            "--exclude-titles",
            "Manager",
            "--recruiter-url",
            "https://linkedin.com/talent/hire/123",
            "--cdp-port",
            "9231",
        ]
        with patch.object(sys, "argv", argv):
            args = bp.parse_args()
            assert args.position_title == "Senior Engineer"
            assert args.team_name == "AI Platform"
            assert args.location == "Remote"
            assert args.recruiter_url == "https://linkedin.com/talent/hire/123"
            assert args.cdp_port == "9231"


class TestExtractTitleFromJdContent:
    """Tests for extract_title_from_jd_content function."""

    def test_extracts_first_line_as_title(self):
        """Should extract first non-empty line as title."""
        jd = "LLM Training Engineer\n\nWe are looking for..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "LLM Training Engineer"

    def test_strips_title_prefix(self):
        """Should strip 'Title:' prefix."""
        jd = "Title: Senior ML Engineer\n\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Senior ML Engineer"

    def test_strips_job_title_prefix(self):
        """Should strip 'Job Title:' prefix."""
        jd = "Job Title: Staff Engineer - AI Platform\n\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Staff Engineer - AI Platform"

    def test_strips_position_prefix(self):
        """Should strip 'Position:' prefix."""
        jd = "Position: Software Engineer\n\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Software Engineer"

    def test_strips_role_prefix(self):
        """Should strip 'Role:' prefix."""
        jd = "Role: Data Scientist\n\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Data Scientist"

    def test_strips_markdown_header(self):
        """Should strip markdown header markers."""
        jd = "# Senior Backend Engineer\n\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Senior Backend Engineer"

    def test_skips_empty_lines(self):
        """Should skip leading empty lines."""
        jd = "\n\n\nML Engineer\n\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "ML Engineer"

    def test_skips_urls(self):
        """Should skip lines that are URLs."""
        jd = "https://example.com/job\n\nSenior Engineer\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Senior Engineer"

    def test_skips_markdown_markers(self):
        """Should skip markdown marker lines."""
        jd = "---\n\nStaff Engineer\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Staff Engineer"

    def test_skips_short_lines(self):
        """Should skip lines that are too short."""
        jd = "Hi\n\nSenior Software Engineer\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Senior Software Engineer"

    def test_handles_case_insensitive_prefix(self):
        """Should handle prefixes case-insensitively."""
        jd = "TITLE: Senior Engineer\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result == "Senior Engineer"

    def test_limits_title_length(self):
        """Should limit title length to reasonable size."""
        jd = "A" * 200 + "\nDescription..."
        result = bp.extract_title_from_jd_content(jd)
        assert result is not None
        assert len(result) <= 100

    def test_returns_none_for_empty_content(self):
        """Should return None for empty content."""
        assert bp.extract_title_from_jd_content("") is None
        assert bp.extract_title_from_jd_content("   \n\n   ") is None

    def test_extracts_title_from_html_h1(self):
        """Should extract a clean title from HTML content."""
        jd = """
        <!doctype html>
        <html>
          <head><title>LLM Training Engineer | Example Company</title></head>
          <body><h1>LLM Training Engineer</h1></body>
        </html>
        """
        result = bp.extract_title_from_jd_content(jd)
        assert result == "LLM Training Engineer"

    def test_extracts_title_from_html_title_only(self):
        """Should treat title-only HTML pages as HTML, not raw tagged text."""
        jd = """
        <title>LLM Training Engineer | Example Company</title>
        <meta name="description" content="Role details">
        """
        result = bp.extract_title_from_jd_content(jd)
        assert result == "LLM Training Engineer"

    def test_returns_none_for_no_meaningful_lines(self):
        """Should return None when no meaningful lines found."""
        jd = "https://example.com\n---\n\n#\n\n"
        assert bp.extract_title_from_jd_content(jd) is None


class TestSlugifyTitle:
    """Tests for slugify_title function."""

    def test_converts_title_to_slug(self):
        """Should convert title to lowercase hyphenated slug."""
        assert bp.slugify_title("Senior Engineer") == "senior-engineer"
        assert bp.slugify_title("ML Engineer") == "ml-engineer"

    def test_handles_special_characters(self):
        """Should remove special characters."""
        assert bp.slugify_title("Engineer (AI/ML)") == "engineer-aiml"
        assert bp.slugify_title("C++ Developer") == "c-developer"

    def test_handles_multiple_spaces(self):
        """Should collapse multiple spaces to single hyphen."""
        assert bp.slugify_title("Senior   Engineer") == "senior-engineer"

    def test_handles_empty_title(self):
        """Should return default for empty title."""
        assert bp.slugify_title("") == "project"
        assert bp.slugify_title(None) == "project"

    def test_limits_length(self):
        """Should limit slug length to 50 chars."""
        long_title = "A" * 100
        slug = bp.slugify_title(long_title)
        assert len(slug) <= 50

    def test_trims_hyphens(self):
        """Should trim leading/trailing hyphens."""
        assert bp.slugify_title("-Engineer-") == "engineer"


class TestFindProjectByProjectId:
    """Tests for find_project_by_project_id function."""

    def test_finds_project_by_reading_config(self, tmp_path):
        """Should find project by reading PROJECT_ID from config.sh."""
        # Create project with specific PROJECT_ID
        project_dir = tmp_path / "projects" / "12345_some-title"
        project_dir.mkdir(parents=True)
        config_path = project_dir / "config.sh"
        config_path.write_text('PROJECT_ID="12345"\nPOSITION_TITLE="Engineer"\n')

        result = bp.find_project_by_project_id(tmp_path, "12345")

        assert result == project_dir

    def test_returns_none_when_not_found(self, tmp_path):
        """Should return None when no project has matching PROJECT_ID."""
        # Create project with different PROJECT_ID
        project_dir = tmp_path / "projects" / "99999_other"
        project_dir.mkdir(parents=True)
        config_path = project_dir / "config.sh"
        config_path.write_text('PROJECT_ID="99999"\n')

        result = bp.find_project_by_project_id(tmp_path, "12345")

        assert result is None

    def test_ignores_folder_name(self, tmp_path):
        """Should not trust folder name - only config.sh PROJECT_ID."""
        # Create folder with misleading name
        project_dir = tmp_path / "projects" / "12345_wrong-id"
        project_dir.mkdir(parents=True)
        config_path = project_dir / "config.sh"
        # Actual PROJECT_ID is different from folder name
        config_path.write_text('PROJECT_ID="99999"\n')

        # Should NOT find it when searching for 12345
        result = bp.find_project_by_project_id(tmp_path, "12345")
        assert result is None

        # Should find it when searching for 99999
        result = bp.find_project_by_project_id(tmp_path, "99999")
        assert result == project_dir

    def test_skips_nonexistent_projects_dir(self, tmp_path):
        """Should return None when projects directory doesn't exist."""
        result = bp.find_project_by_project_id(tmp_path, "12345")
        assert result is None


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
