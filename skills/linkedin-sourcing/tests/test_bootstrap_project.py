#!/usr/bin/env python3
"""Tests for bootstrap_project.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_bootstrap_project.py -v
"""

from __future__ import annotations

import json
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


class TestExtractKeywordsFromText:
    """Tests for shared keyword extraction from text."""

    def test_extracts_python_keyword(self):
        """Should extract Python from text."""
        result = bp.extract_keywords_from_text("Senior Python Engineer")
        assert "Python" in result

    def test_extracts_multiple_keywords(self):
        """Should extract multiple matching keywords."""
        result = bp.extract_keywords_from_text(
            "Python Kubernetes Engineer with AWS experience"
        )
        assert "Python" in result
        assert "Kubernetes" in result
        assert "AWS" in result

    def test_uses_word_boundaries(self):
        """Should use word boundaries to avoid false matches."""
        # "go" as standalone word should match
        result = bp.extract_keywords_from_text("Go Developer")
        assert "Go" in result

    def test_does_not_treat_go_as_common_verb(self):
        """Should not infer Go from ordinary prose usage."""
        result = bp.extract_keywords_from_text("We go deep on reliability")
        assert "Go" not in result

    def test_does_not_treat_go_to_market_as_go_language(self):
        """Should not infer Go from hyphenated non-language phrases."""
        result = bp.extract_keywords_from_text("Lead go-to-market strategy")
        assert "Go" not in result

    def test_extracts_golang_keyword(self):
        """Should still infer Go from Golang."""
        result = bp.extract_keywords_from_text("Senior Golang engineer")
        assert "Go" in result

    def test_deduplicates_keywords(self):
        """Should deduplicate keywords while preserving order."""
        result = bp.extract_keywords_from_text("Python Python Kubernetes")
        # Python should appear only once
        assert result.count("Python") == 1
        assert result.index("Python") < result.index("Kubernetes")

    def test_uses_jd_text_fallback(self):
        """Should use jd_text for additional keyword inference."""
        result = bp.extract_keywords_from_text(
            "Software Engineer",
            jd_text="Experience with Kubernetes and Docker required",
        )
        assert "Kubernetes" in result
        assert "Docker" in result

    def test_extracts_infrastructure_keywords(self):
        """Should extract infrastructure-related keywords."""
        result = bp.extract_keywords_from_text(
            "Infrastructure Engineer with Terraform and AWS"
        )
        assert "Terraform" in result
        assert "AWS" in result
        assert "Infrastructure" in result

    def test_extracts_ml_keywords(self):
        """Should extract ML/AI keywords."""
        result = bp.extract_keywords_from_text("ML Engineer with PyTorch and CUDA")
        assert "PyTorch" in result
        assert "CUDA" in result
        assert "Machine Learning" in result

    def test_returns_empty_for_no_matches(self):
        """Should return empty list for text with no keyword matches."""
        result = bp.extract_keywords_from_text("General Office Manager")
        assert result == []

    def test_handles_empty_text(self):
        """Should handle empty text gracefully."""
        assert bp.extract_keywords_from_text("") == []
        assert bp.extract_keywords_from_text(None) == []


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

    def test_uses_jd_text_for_fallback(self):
        """Should use jd_text for additional keyword inference."""
        result = bp.infer_keywords("Software Engineer", jd_text="Kubernetes Docker AWS")
        assert "Kubernetes" in result
        assert "Docker" in result
        assert "AWS" in result

    def test_precedence_title_over_jd(self):
        """Title keywords should appear before JD keywords in result."""
        result = bp.infer_keywords("Python Engineer", jd_text="Kubernetes")
        # Python from title should come before Kubernetes from JD
        assert result.index("Python") < result.index("Kubernetes")

    def test_does_not_infer_go_from_general_jd_prose(self):
        """JD fallback should remain conservative for ambiguous words."""
        result = bp.infer_keywords(
            "Software Engineer", jd_text="We go deep on reliability"
        )
        assert "Go" not in result


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

    def test_keyword_fallback_uses_description_and_core_function_text(self):
        """Keyword fallback should use broader JD-derived text when metadata keywords are absent."""
        inferred = {
            "position_title": "Software Engineer",
            "team_name": "Infrastructure Platform",
            "location": "San Francisco",
            "core_function": "Build Kubernetes control planes",
            "business_impact": "Improve cloud infrastructure reliability",
            "description": "Experience with Terraform and AWS required",
            "keywords": "",
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

        assert "Kubernetes" in config["KEYWORDS"]
        assert "Terraform" in config["KEYWORDS"]
        assert "AWS" in config["KEYWORDS"]

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
        assert "[AGENT: infer from JD" in config["CORE_FUNCTION"]

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


class TestParseConfigFile:
    """Tests for parse_config_file function (via config_utils)."""

    def test_parses_double_quoted_values(self, tmp_path):
        """Should parse double-quoted values from config file."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            'PROJECT_ID="my_project"\n'
            'POSITION_TITLE="Senior Engineer"\n'
            'TEAM_NAME="AI Team"\n'
        )

        from config_utils import parse_config_file

        result = parse_config_file(config_file)

        assert result["PROJECT_ID"] == "my_project"
        assert result["POSITION_TITLE"] == "Senior Engineer"
        assert result["TEAM_NAME"] == "AI Team"

    def test_parses_single_quoted_values(self, tmp_path):
        """Should parse single-quoted values from config file."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID='my_project'\nPOSITION_TITLE='Engineer'")

        from config_utils import parse_config_file

        result = parse_config_file(config_file)

        assert result["PROJECT_ID"] == "my_project"
        assert result["POSITION_TITLE"] == "Engineer"

    def test_parses_unquoted_values(self, tmp_path):
        """Should parse unquoted values from config file."""
        config_file = tmp_path / "config.sh"
        config_file.write_text("PROJECT_ID=my_project\nDAILY_LIMIT=200")

        from config_utils import parse_config_file

        result = parse_config_file(config_file)

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

        from config_utils import parse_config_file

        result = parse_config_file(config_file)

        assert result["PROJECT_ID"] == "my_project"
        assert result["POSITION_TITLE"] == "Engineer"
        assert "# This is a comment" not in result

    def test_returns_empty_for_missing_file(self, tmp_path):
        """Should return empty dict for missing file."""
        from config_utils import parse_config_file

        result = parse_config_file(tmp_path / "nonexistent.sh")
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


class TestFetchJdUrl:
    """Tests for JD URL fetching strategy."""

    @patch("bootstrap_project.fetch_url_via_agent_browser")
    @patch("bootstrap_project.fetch_url")
    def test_tiktok_url_prefers_agent_browser(self, mock_fetch_url, mock_browser_fetch):
        """TikTok job pages should prefer agent-browser for dynamic content."""
        mock_browser_fetch.return_value = (200, "<html>dynamic jd</html>")

        status, content = bp.fetch_jd_url(
            "https://lifeattiktok.com/search/7619156093767485701"
        )

        assert status == 200
        assert content == "<html>dynamic jd</html>"
        mock_browser_fetch.assert_called_once()
        mock_fetch_url.assert_not_called()

    @patch("bootstrap_project.fetch_url_via_agent_browser")
    @patch("bootstrap_project.fetch_url")
    def test_tiktok_url_falls_back_to_static_fetch(
        self, mock_fetch_url, mock_browser_fetch
    ):
        """TikTok job pages should fall back to static fetch if agent-browser fails."""
        mock_browser_fetch.return_value = (0, "agent-browser not found")
        mock_fetch_url.return_value = (200, "<html>fallback jd</html>")

        status, content = bp.fetch_jd_url(
            "https://lifeattiktok.com/search/7619156093767485701"
        )

        assert status == 200
        assert content == "<html>fallback jd</html>"
        mock_browser_fetch.assert_called_once()
        mock_fetch_url.assert_called_once()

    @patch("subprocess.run")
    def test_fetch_url_via_agent_browser_returns_html(self, mock_run):
        """agent-browser fetch should return evaluated page HTML."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(
                returncode=0,
                stdout='{"html":"<html>jd</html>","title":"JD"}',
                stderr="",
            ),
        ]

        status, content = bp.fetch_url_via_agent_browser("https://example.com/job")

        assert status == 200
        assert content == "<html>jd</html>"


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

    def test_handles_spaced_assignment_in_config(self, tmp_path):
        """Should use shared config parsing for spaced assignments."""
        projects_dir = tmp_path / "projects" / "project2"
        projects_dir.mkdir(parents=True)
        config_path = projects_dir / "config.sh"
        config_path.write_text(
            'RECRUITER_PROJECT_URL = "https://linkedin.com/talent/hire/24680/overview"\n'
        )

        result = bp.check_existing_project_by_recruiter_id(tmp_path, "24680")

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
            browser_mode="9230",  # Can pass string CDP port for backward compatibility
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
            browser_mode="9230",  # Can pass string CDP port for backward compatibility
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
            browser_mode="9230",  # Can pass string CDP port for backward compatibility
            work_dir=tmp_path,
        )

        call_kwargs = mock_ensure.call_args[1]
        assert call_kwargs["require_contextual_url"] is False

    @patch("ensure_recruiter_project.ensure_project_exists")
    def test_accepts_browser_mode_instance(self, mock_ensure, tmp_path):
        """Should accept BrowserMode instance for agent-browser mode."""
        mock_ensure.return_value = {
            "status": "created",
            "project_id": "67890",
            "url": "https://linkedin.com/talent/hire/67890/overview",
            "message": "Created new project",
        }

        # Import BrowserMode for the test
        from browser_utils import BrowserMode

        browser_mode = BrowserMode(
            mode="agent-browser",
            session_name="test-session",
            auth_file="/path/to/auth.json",
        )

        result = bp.ensure_recruiter_project_and_get_id(
            project_name="Test Project",
            description="Test description",
            browser_mode=browser_mode,  # Pass BrowserMode instance
            work_dir=tmp_path,
        )

        assert result["success"] is True
        assert result["project_id"] == "67890"
        # Verify the BrowserMode was passed through to ensure_project_exists
        call_args = mock_ensure.call_args[1]
        assert call_args["browser_mode"] is browser_mode

    @patch("ensure_recruiter_project.ensure_project_exists")
    def test_preserves_failure_code_and_action_required(self, mock_ensure, tmp_path):
        """Should preserve failure_code and action_required from ensure_project_exists.

        Regression test: The wrapper was stripping failure_code and action_required fields,
        causing the agent to receive generic fallback text instead of structured guidance.
        """
        mock_ensure.return_value = {
            "status": "error",
            "project_id": None,
            "url": None,
            "message": "Failed to navigate to Projects page",
            "failure_code": "browser_unavailable",
            "action_required": {
                "code": "browser_unavailable",
                "summary": "Chrome is not running or not accessible",
                "steps": [
                    "Start Chrome with: google-chrome --remote-debugging-port=9230",
                    "Ensure Chrome is accessible on port 9230",
                    "Retry the operation",
                ],
                "can_retry": True,
            },
        }

        result = bp.ensure_recruiter_project_and_get_id(
            project_name="Test Project",
            description="Test description",
            browser_mode="9230",
            work_dir=tmp_path,
        )

        # Should preserve structured failure info for agent manual guidance
        assert result["success"] is False
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "browser_unavailable"
        assert "Chrome is not running" in result["action_required"]["summary"]


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
    @patch("bootstrap_project.ensure_browser_auth")
    def test_creates_recruiter_project_when_no_url_provided(
        self, mock_ensure_browser, mock_ensure_project, tmp_path, monkeypatch
    ):
        """Should create Recruiter project and derive PROJECT_ID when no URL provided."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Mock browser auth to succeed
        mock_ensure_browser.return_value = {
            "success": True,
            "mode": None,
            "error": None,
        }

        mock_ensure_project.return_value = {
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
        mock_ensure_project.assert_called_once()

        # Check the project name was passed correctly
        call_args = mock_ensure_project.call_args[1]
        assert call_args["project_name"] == "ML Engineer"

    def test_explicit_project_id_reuses_existing_project(self, tmp_path, monkeypatch):
        """Should reuse existing project when explicit --project-id matches."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with custom_id
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "custom_id"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="custom_id"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
        args.cdp_port = "9230"
        args.project_id = "custom_id"  # Explicit override matching existing
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse existing project with custom_id
        assert result["project_id"] == "custom_id"
        assert result["reused"] is True
        assert result["match_type"] == "explicit_project_id"

    @patch("run_create_search.inspect_search_state")
    def test_reuse_clears_stale_search_blocker_when_search_is_visible(
        self, mock_inspect_search_state, tmp_path, monkeypatch
    ):
        """Bootstrap reuse should clear stale create-search blocker when search is already ready."""
        from project_state import (
            create_initial_state,
            load_project_state,
            save_project_state,
        )

        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        work_dir = tmp_path / "work"
        existing_project = (
            work_dir / "projects" / "1693735164_tiktok-engineering-position"
        )
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="1693735164"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/1693735164/discover/recruiterSearch"\n'
        )

        stale_state = create_initial_state(
            "1693735164", current_phase="bootstrap", status="completed"
        )
        stale_state["action_required"] = {
            "code": "search_not_configured",
            "summary": "The Recruiter project needs a candidate search configured",
            "steps": ["Open Recruiter"],
            "can_retry": True,
            "context": {},
            "actor": "agent",
        }
        stale_state["last_error"] = (
            "Open the Recruiter project and create the candidate search"
        )
        save_project_state(existing_project, stale_state)

        mock_inspect_search_state.return_value = {
            "success": True,
            "status": "ready",
            "current_url": "https://linkedin.com/talent/hire/1693735164/discover/recruiterSearch",
            "failure_code": None,
            "action_required": None,
        }

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/1693735164/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = "1693735164"
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        assert result["reused"] is True
        updated_state = load_project_state(existing_project)
        assert updated_state["current_phase"] == "create_search"
        assert updated_state["status"] == "completed"
        assert updated_state["action_required"] is None
        assert updated_state["last_error"] is None

    def test_explicit_project_id_missing_fails_clearly(self, tmp_path, monkeypatch):
        """Should fail clearly when explicit --project-id does not exist."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
        args.cdp_port = "9230"
        args.project_id = "nonexistent_id"  # Explicit override not matching any project
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
            assert "nonexistent_id" in str(e)
            assert "not found" in str(e)
            assert "--project-id" in str(e)

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

    def test_explicit_project_id_takes_precedence_over_recruiter_url(
        self, tmp_path, monkeypatch
    ):
        """Explicit project_id should be checked first, before validating recruiter URL.

        If explicit project_id is provided but doesn't exist, fail immediately
        without validating other parameters.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = "https://invalid-url.com/no-project-id"
        args.cdp_port = "9230"
        args.project_id = (
            "nonexistent_override_id"  # Override provided but doesn't exist
        )
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
            # Should fail on missing project_id first
            assert "nonexistent_override_id" in str(e)
            assert "not found" in str(e)

        # Verify no files were written
        work_dir = tmp_path / "work"
        assert not (work_dir / "projects").exists() or not any(
            (work_dir / "projects").iterdir()
        )

    @patch("bootstrap_project.ensure_recruiter_project_and_get_id")
    @patch("bootstrap_project.ensure_browser_auth")
    def test_fails_closed_when_recruiter_creation_fails(
        self, mock_ensure_browser, mock_ensure_project, tmp_path, monkeypatch
    ):
        """Should fail closed when ensure_recruiter_project fails."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Mock browser auth to succeed
        mock_ensure_browser.return_value = {
            "success": True,
            "mode": None,
            "error": None,
        }

        mock_ensure_project.return_value = {
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

    def test_explicit_project_id_fails_when_not_found_even_with_matching_recruiter_id(
        self, tmp_path, monkeypatch
    ):
        """Explicit --project-id that doesn't exist should fail, even if recruiter_id matches.

        The new behavior requires explicit project_id to exist. If the user wants to
        reuse by recruiter_id, they should omit --project-id.
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
        args.project_id = "different_id"  # Explicit but doesn't exist
        args.position_title = "New Title"
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
            assert "different_id" in str(e)
            assert "not found" in str(e)

    def test_creates_new_project_when_no_jd_match_even_with_recruiter_id_match(
        self, tmp_path, monkeypatch
    ):
        """Should create new project when no exact JD match, even if recruiter_id matches existing.

        The new contract: reuse ONLY on exact JD_URL or exact JD-content match.
        No auto-reuse by recruiter_id alone.
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
        args.jd_text = "Different JD content"  # Different from existing
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None  # No explicit override
        args.position_title = "New Title"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should create NEW project (not reuse) because no exact JD match
        assert result["project_id"] == "12345"  # Derived from recruiter_url
        assert result["reused"] is False
        # Should be a new directory, not the existing one
        assert "existing_proj" not in result["project_dir"]
        assert "12345" in result["project_dir"]

    def test_reuses_existing_project_by_exact_jd_content_match(
        self, tmp_path, monkeypatch
    ):
        """Should reuse existing project when JD content matches exactly."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "Senior ML Engineer\n\nWe are looking for an experienced ML engineer."
        )

        # Create existing project with JD content
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_existing-title"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
        )
        # Save JD content for matching
        jd_path = existing_project / "job_description.txt"
        jd_path.write_text(jd_content)

        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content
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

        # Should reuse same project (found by exact JD content match)
        assert result["project_id"] == "12345"
        assert "12345_existing-title" in result["project_dir"]
        assert result["reused"] is True
        assert result["match_type"] == "jd_content"
        # Config should be updated
        config_content = Path(result["config_path"]).read_text()
        assert "Updated Title" in config_content

    def test_preserves_existing_workbook_when_reusing_by_jd_match(
        self, tmp_path, monkeypatch
    ):
        """Should preserve existing workbook data when reusing a project by JD match.

        Regression test: Previously, bootstrap would recreate the workbook on every run,
        wiping out existing candidate data. Now it should only create if missing.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "Senior ML Engineer\n\nWe are looking for an experienced ML engineer."
        )

        # Create existing project with JD content and existing workbook
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_existing-title"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
        )
        # Save JD content for matching
        jd_path = existing_project / "job_description.txt"
        jd_path.write_text(jd_content)

        # Create an existing workbook inside project dir
        workbook_path = existing_project / "workbook.xlsx"
        workbook_path.write_text("existing workbook data")

        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content - should match
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

        # Should reuse same project (found by exact JD content match)
        assert result["project_id"] == "12345"
        assert result["reused"] is True
        # Workbook should still contain original data (not be overwritten)
        assert workbook_path.read_text() == "existing workbook data"
        # Result should point to the existing workbook
        assert result["workbook_path"] == str(workbook_path)

    def test_preserves_workbook_for_legacy_project_reuse_by_jd_match(
        self, tmp_path, monkeypatch
    ):
        """Should preserve workbook when reusing a legacy project by JD content match."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "SoC Design Engineer\n\nWe are looking for an experienced SoC designer."
        )

        # Create existing LEGACY project with JD content
        work_dir = tmp_path / "work"
        legacy_project = work_dir / "projects" / "soc-design-engineer-2024"
        legacy_project.mkdir(parents=True)
        config_path = legacy_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="soc-design-engineer-2024"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
        )
        # Save JD content for matching
        jd_path = legacy_project / "job_description.txt"
        jd_path.write_text(jd_content)

        # Create an existing workbook for the legacy project
        workbook_path = work_dir / "projects" / "soc-design-engineer-2024.xlsx"
        workbook_path.write_text("legacy workbook with candidate data")

        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content - should match
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

        # Should reuse the LEGACY project directory (found by JD content match)
        assert result["project_id"] == "soc-design-engineer-2024"
        assert result["reused"] is True
        # Workbook should still contain original data
        assert workbook_path.read_text() == "legacy workbook with candidate data"
        # Verify NO new numeric directory or workbook was created
        numeric_workbook = work_dir / "projects" / "12345.xlsx"
        assert not numeric_workbook.exists()

    def test_creates_new_project_when_no_jd_match_even_with_legacy_recruiter_id(
        self, tmp_path, monkeypatch
    ):
        """Should create new project when no exact JD match, even if legacy recruiter_id matches.

        The new contract: reuse ONLY on exact JD_URL or exact JD-content match.
        No auto-reuse by recruiter_id alone, even for legacy projects.
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
        args.jd_text = "Different JD content"  # Different from existing
        args.work_dir = str(work_dir)
        # Same recruiter ID but different JD
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

        # Should create NEW project (not reuse legacy) because no exact JD match
        assert result["project_id"] == "12345"  # Derived from recruiter_url
        assert result["reused"] is False
        # Should be a new directory, not the legacy one
        assert "soc-design-engineer-2024" not in result["project_dir"]
        assert "12345" in result["project_dir"]

        # Verify legacy project still exists unchanged
        assert config_path.exists()
        legacy_content = config_path.read_text()
        assert "Old Title" in legacy_content

    def test_creates_new_project_when_no_jd_match_with_timestamp_legacy(
        self, tmp_path, monkeypatch
    ):
        """Should create new project when no exact JD match, even with timestamp legacy project.

        The new contract: reuse ONLY on exact JD_URL or exact JD-content match.
        """
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
        args.jd_text = "Different JD content"  # Different from existing
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

        # Should create NEW project because no exact JD match
        assert result["project_id"] == "67890"  # Derived from recruiter_url
        assert result["reused"] is False
        # Should be a new directory, not the legacy one
        assert "project-20240115-143022" not in result["project_dir"]
        assert "67890" in result["project_dir"]

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

    def test_creates_new_project_no_jd_match_same_recruiter_url(
        self, tmp_path, monkeypatch
    ):
        """Should create new project when no JD match even with same recruiter URL.

        This is the key test for the new contract: recruiter_id alone does NOT trigger reuse.
        Only exact JD_URL or exact JD-content match triggers reuse.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with specific JD content
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_existing"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'POSITION_TITLE="Original Title"\n'
        )
        # Save original JD content
        jd_path = existing_project / "job_description.txt"
        jd_path.write_text("Original JD content")

        args = Mock()
        args.jd_url = None
        args.jd_text = "Different JD content"  # Different JD - no match
        args.work_dir = str(work_dir)
        # Same recruiter URL as existing project
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/overview"
        args.cdp_port = "9230"
        args.project_id = None  # No explicit project_id
        args.position_title = "New Title"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should create NEW project (not reuse) - no JD match, no explicit project_id
        assert result["project_id"] == "12345"  # Derived from recruiter_url
        assert result["reused"] is False
        # Should be a new directory
        assert "existing" not in result["project_dir"]

        # Original project should still exist with original content
        assert config_path.exists()
        original_content = config_path.read_text()
        assert "Original Title" in original_content

    @patch("run_create_search.inspect_search_state")
    def test_next_steps_with_ready_search_url(
        self, mock_inspect_search_state, tmp_path, monkeypatch
    ):
        """Should point to status/loop when the search is already visible."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        mock_inspect_search_state.return_value = {
            "success": True,
            "status": "ready",
            "current_url": "https://linkedin.com/talent/hire/12345/discover/recruiterSearch",
            "failure_code": None,
            "action_required": None,
        }

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
        assert "recruiter search already shows candidates" in next_steps_text.lower()
        assert "status.py 12345 --pretty" in next_steps_text
        assert "run_reachout_loop.py --project 12345" in next_steps_text

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

    def test_next_steps_call_out_unresolved_project_messaging(
        self, tmp_path, monkeypatch
    ):
        """Bootstrap should call out unresolved project-level messaging fields early."""
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

        assert result["unresolved_project_messaging_fields"] == [
            "CORE_FUNCTION",
            "BUSINESS_IMPACT",
        ]
        next_steps_text = "\n".join(result["next_steps"])
        assert "Finalize project messaging fields before drafting" in next_steps_text
        assert "CORE_FUNCTION, BUSINESS_IMPACT" in next_steps_text

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

    def test_preserves_existing_config_when_reusing_by_jd_match(
        self, tmp_path, monkeypatch
    ):
        """Should preserve existing curated config values when reusing by JD match.

        When bootstrap reuses an existing project (exact JD content match), it should
        preserve existing curated values like TEAM_NAME, LOCATION, CORE_FUNCTION,
        BUSINESS_IMPACT, KEYWORDS, COMPANIES, EXCLUDE_TITLES unless the user
        explicitly provides overrides.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "Senior ML Engineer\n\nWe are looking for an experienced ML engineer."
        )

        # Create existing project with curated config values and JD content
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
        # Save JD content for matching
        jd_path = existing_project / "job_description.txt"
        jd_path.write_text(jd_content)

        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content - should match and reuse
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

        # Should reuse same project (found by JD content match)
        assert result["project_id"] == "12345"
        assert result["reused"] is True

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

    def test_overrides_preserve_existing_config_when_reusing_by_jd_match(
        self, tmp_path, monkeypatch
    ):
        """CLI overrides should take precedence over existing config when reusing by JD match."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "Senior ML Engineer\n\nWe are looking for an experienced ML engineer."
        )

        # Create existing project with curated config values and JD content
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
        # Save JD content for matching
        jd_path = existing_project / "job_description.txt"
        jd_path.write_text(jd_content)

        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content - should match and reuse
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

        # Should reuse project by JD match
        assert result["reused"] is True

        # Config should have overrides for specified fields, existing for others
        config_content = Path(result["config_path"]).read_text()
        assert "POSITION_TITLE='Override Title'" in config_content  # overridden
        assert "TEAM_NAME='Existing Team'" in config_content  # preserved
        assert "LOCATION='Override Location'" in config_content  # overridden

    def test_preserves_existing_config_for_legacy_project_reuse_by_jd_match(
        self, tmp_path, monkeypatch
    ):
        """Should preserve existing config when reusing a legacy project by JD match."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "SoC Design Engineer\n\nWe are looking for an experienced SoC designer."
        )

        # Create existing LEGACY project with curated config and JD content
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
        # Save JD content for matching
        jd_path = legacy_project / "job_description.txt"
        jd_path.write_text(jd_content)

        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content - should match and reuse
        args.work_dir = str(work_dir)
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

        # Should reuse legacy project (found by JD content match)
        assert result["project_id"] == "soc-design-2024"
        assert result["reused"] is True

        # Config should preserve existing curated values (shell_escape uses single quotes for values with spaces)
        config_content = Path(result["config_path"]).read_text()
        assert "TEAM_NAME='Hardware Team'" in config_content
        assert "LOCATION='San Jose, CA'" in config_content
        assert "CORE_FUNCTION='Designing SoC components'" in config_content
        assert "BUSINESS_IMPACT='Powering next-gen hardware'" in config_content
        assert "KEYWORDS='Verilog, SystemVerilog, ASIC'" in config_content

    def test_does_not_overwrite_existing_folder_on_new_project_creation(
        self, tmp_path, monkeypatch
    ):
        """Regression test: Non-matching existing folder should NOT be overwritten.

        When creating a new project, if a folder already exists at the derived path
        (from a non-matching old project), bootstrap should create a new unique folder
        instead of overwriting the existing one.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project at the path that would be derived for new project
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_engineer"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="old_project_id"\n'  # Different PROJECT_ID
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/99999/overview"\n'
            'POSITION_TITLE="Old Title"\n'
        )
        # Save different JD content (so no match)
        jd_path = existing_project / "job_description.txt"
        jd_path.write_text("Old JD content that does not match")

        # New bootstrap with same recruiter_id (12345) but different JD
        args = Mock()
        args.jd_url = None
        args.jd_text = "New JD content that is different from existing"
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Engineer"  # Same title slug as existing folder
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should create NEW project (not reuse) - no JD match
        assert result["project_id"] == "12345"
        assert result["reused"] is False

        # Should create a NEW directory with unique name, not overwrite existing
        assert "12345_engineer_1" in result["project_dir"]
        assert result["project_dir"] != str(existing_project)

        # Original project should still exist unchanged
        assert config_path.exists()
        original_content = config_path.read_text()
        assert "old_project_id" in original_content
        assert "Old Title" in original_content

        # New project should be in a different directory
        new_project_dir = Path(result["project_dir"])
        assert new_project_dir.exists()
        assert new_project_dir != existing_project

    def test_generates_unique_folder_name_for_multiple_collisions(
        self, tmp_path, monkeypatch
    ):
        """Should generate unique folder names when multiple collisions exist.

        If projects/12345_engineer, projects/12345_engineer_1, etc. all exist,
        bootstrap should create projects/12345_engineer_2, etc.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        work_dir = tmp_path / "work"

        # Create multiple existing projects that would collide
        for i in range(3):
            if i == 0:
                folder_name = "12345_engineer"
            else:
                folder_name = f"12345_engineer_{i}"
            existing_project = work_dir / "projects" / folder_name
            existing_project.mkdir(parents=True)
            config_path = existing_project / "config.sh"
            config_path.write_text(
                f'PROJECT_ID="old_project_{i}"\n'
                'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/99999/overview"\n'
            )
            jd_path = existing_project / "job_description.txt"
            jd_path.write_text(f"Old JD content {i}")

        # New bootstrap with same recruiter_id and title
        args = Mock()
        args.jd_url = None
        args.jd_text = "New unique JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
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

        # Should create NEW project with unique folder name
        assert result["project_id"] == "12345"
        assert result["reused"] is False

        # Should use the next available suffix (_3 since _0, _1, _2 exist via base + _1, _2)
        # Actually base is 12345_engineer, then _1, _2, so next is _3
        assert "12345_engineer_3" in result["project_dir"]

        # All original projects should still exist
        for i in range(3):
            if i == 0:
                folder_name = "12345_engineer"
            else:
                folder_name = f"12345_engineer_{i}"
            assert (work_dir / "projects" / folder_name).exists()

    def test_reuse_still_works_when_folder_exists_with_matching_project(
        self, tmp_path, monkeypatch
    ):
        """Reuse should still work when the folder exists and matches.

        This verifies the fix doesn't break the normal reuse case.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = "Senior ML Engineer\n\nWe are looking for an ML engineer."

        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_senior-ml-engineer"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'POSITION_TITLE="Existing Title"\n'
        )
        jd_path = existing_project / "job_description.txt"
        jd_path.write_text(jd_content)

        # Bootstrap with same JD content - should reuse
        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Senior ML Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should reuse existing project
        assert result["project_id"] == "12345"
        assert result["reused"] is True
        assert result["project_dir"] == str(existing_project)


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


class TestEnsureBrowserAuth:
    """Tests for ensure_browser_auth function."""

    @patch("bootstrap_project.auth_bootstrap.bootstrap_auth_session")
    def test_returns_success_when_auth_succeeds(self, mock_bootstrap, tmp_path):
        """Should return success when bootstrap_auth_session succeeds."""
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            "message": "Using existing authenticated browser",
        }

        result = bp.ensure_browser_auth(tmp_path, "9230")

        assert result["success"] is True
        assert result["error"] is None
        mock_bootstrap.assert_called_once_with(
            work_dir=tmp_path,
            preferred_cdp_port="9230",
            allow_browser_launch=True,
        )

    @patch("bootstrap_project.auth_bootstrap.bootstrap_auth_session")
    def test_returns_failure_when_auth_fails(self, mock_bootstrap, tmp_path):
        """Should return failure when bootstrap_auth_session fails."""
        mock_bootstrap.return_value = {
            "success": False,
            "error": "Browser launch not allowed without explicit opt-in",
            "message": "Cannot launch Chrome for manual login",
        }

        result = bp.ensure_browser_auth(tmp_path, "9230")

        assert result["success"] is False
        assert "Browser launch not allowed" in result["error"]

    @patch("bootstrap_project.auth_bootstrap.bootstrap_auth_session")
    def test_preserves_headed_from_bootstrap_result_cdp(self, mock_bootstrap, tmp_path):
        """Should preserve headed from bootstrap result for CDP mode."""
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            "headed": True,
            "message": "Using existing authenticated browser",
        }

        result = bp.ensure_browser_auth(tmp_path, "9230")

        assert result["success"] is True
        assert result["mode"].mode == "cdp"
        assert result["mode"].headed is True

    @patch("bootstrap_project.auth_bootstrap.bootstrap_auth_session")
    def test_preserves_headed_from_bootstrap_result_agent_browser(
        self, mock_bootstrap, tmp_path
    ):
        """Should preserve headed from bootstrap result for agent-browser mode."""
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "agent-browser",
            "session_name": "test-session",
            "auth_file": "/path/to/auth.json",
            "headed": True,
            "message": "Session started",
        }

        result = bp.ensure_browser_auth(tmp_path, "9230")

        assert result["success"] is True
        assert result["mode"].mode == "agent-browser"
        assert result["mode"].session_name == "test-session"
        assert result["mode"].headed is True

    @patch("bootstrap_project.auth_bootstrap.bootstrap_auth_session")
    def test_defaults_to_headed_true_when_not_in_result(self, mock_bootstrap, tmp_path):
        """Should default to headed=True when not present in bootstrap result."""
        mock_bootstrap.return_value = {
            "success": True,
            "mode": "cdp",
            "cdp_port": "9230",
            # headed not included - should default to True
            "message": "Using existing authenticated browser",
        }

        result = bp.ensure_browser_auth(tmp_path, "9230")

        assert result["success"] is True
        assert result["mode"].headed is True


class TestBootstrapProjectBrowserAuth:
    """Tests for bootstrap_project browser authentication integration."""

    @patch("bootstrap_project.ensure_browser_auth")
    @patch("bootstrap_project.ensure_recruiter_project_and_get_id")
    def test_triggers_browser_bootstrap_when_no_recruiter_url(
        self, mock_ensure_project, mock_ensure_browser, tmp_path, monkeypatch
    ):
        """Should trigger browser bootstrap before ensure_recruiter_project when no URL provided."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Browser auth succeeds
        mock_ensure_browser.return_value = {"success": True, "error": None}
        # Project creation succeeds
        mock_ensure_project.return_value = {
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
        args.recruiter_url = None  # No URL provided - should trigger browser bootstrap
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

        # Should call browser auth first
        mock_ensure_browser.assert_called_once_with(tmp_path / "work", "9230")
        # Then call ensure_recruiter_project
        mock_ensure_project.assert_called_once()
        # Project should be created successfully
        assert result["project_id"] == "67890"

    @patch("bootstrap_project.ensure_browser_auth")
    @patch("bootstrap_project.ensure_recruiter_project_and_get_id")
    def test_skips_browser_bootstrap_when_recruiter_url_provided(
        self, mock_ensure_project, mock_ensure_browser, tmp_path, monkeypatch
    ):
        """Should NOT trigger browser bootstrap when --recruiter-url is provided."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
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

        # Should NOT call browser auth when recruiter_url is provided
        mock_ensure_browser.assert_not_called()
        # Should NOT call ensure_recruiter_project
        mock_ensure_project.assert_not_called()
        # Project ID should be derived from recruiter_url
        assert result["project_id"] == "12345"

    @patch("bootstrap_project.ensure_browser_auth")
    @patch("bootstrap_project.ensure_recruiter_project_and_get_id")
    def test_skips_browser_bootstrap_when_explicit_project_id_exists(
        self, mock_ensure_project, mock_ensure_browser, tmp_path, monkeypatch
    ):
        """Should NOT trigger browser bootstrap when --project-id matches existing project."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "custom_override_id"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="custom_override_id"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/"\n'
        )

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(work_dir)
        args.recruiter_url = None
        args.cdp_port = "9230"
        args.project_id = "custom_override_id"  # Explicit override matching existing
        args.position_title = "Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should NOT call browser auth when existing project_id is provided
        mock_ensure_browser.assert_not_called()
        # Should NOT call ensure_recruiter_project
        mock_ensure_project.assert_not_called()
        # Project ID should use the override
        assert result["project_id"] == "custom_override_id"
        assert result["reused"] is True

    @patch("bootstrap_project.ensure_browser_auth")
    def test_raises_clear_error_when_browser_auth_fails(
        self, mock_ensure_browser, tmp_path, monkeypatch
    ):
        """Should raise RuntimeError with clear message when browser auth fails."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Browser auth fails
        mock_ensure_browser.return_value = {
            "success": False,
            "error": "Browser launch not allowed without explicit opt-in",
        }

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = None  # No URL - needs browser
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
            assert "Browser authentication required but failed" in str(e)
            assert "Browser launch not allowed" in str(e)
            assert "--recruiter-url" in str(e)


class TestBootstrapProjectFreshAuthBootstrap:
    """Tests for fresh auth bootstrap success path with agent-browser mode."""

    @patch("bootstrap_project.ensure_recruiter_project_and_get_id")
    @patch("bootstrap_project.ensure_browser_auth")
    def test_fresh_bootstrap_with_agent_browser_mode(
        self, mock_ensure_browser, mock_ensure_project, tmp_path, monkeypatch
    ):
        """Should pass BrowserMode to project creation after fresh auth bootstrap.

        This tests the success path where:
        1. No existing browser is available
        2. Auth bootstrap succeeds and returns agent-browser mode
        3. Project creation proceeds using the agent-browser mode
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        from browser_utils import BrowserMode

        # Simulate fresh auth bootstrap returning agent-browser mode
        browser_mode = BrowserMode(
            mode="agent-browser",
            session_name="linkedin-1234567890",
            auth_file="/path/to/auth.json",
            headed=True,
        )
        mock_ensure_browser.return_value = {
            "success": True,
            "mode": browser_mode,
            "error": None,
        }

        mock_ensure_project.return_value = {
            "success": True,
            "project_id": "54321",
            "url": "https://linkedin.com/talent/hire/54321/overview",
            "status": "created",
            "message": "Created new project",
        }

        args = Mock()
        args.jd_url = None
        args.jd_text = "JD content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = None  # No URL - triggers browser bootstrap
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Senior ML Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Should succeed with project created via agent-browser mode
        assert result["project_id"] == "54321"

        # Verify browser auth was called
        mock_ensure_browser.assert_called_once()

        # Verify project creation was called with BrowserMode (not just cdp_port string)
        mock_ensure_project.assert_called_once()
        call_kwargs = mock_ensure_project.call_args[1]
        passed_mode = call_kwargs["browser_mode"]

        # The mode should be the BrowserMode instance returned from auth
        assert passed_mode is browser_mode
        assert passed_mode.mode == "agent-browser"
        assert passed_mode.session_name == "linkedin-1234567890"

    @patch("bootstrap_project.ensure_recruiter_project_and_get_id")
    @patch("bootstrap_project.ensure_browser_auth")
    def test_fresh_bootstrap_with_cdp_mode(
        self, mock_ensure_browser, mock_ensure_project, tmp_path, monkeypatch
    ):
        """Should pass BrowserMode (CDP) to project creation when CDP mode returned."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        from browser_utils import BrowserMode

        # Simulate auth bootstrap returning CDP mode
        browser_mode = BrowserMode(
            mode="cdp",
            cdp_port="9230",
            headed=True,
        )
        mock_ensure_browser.return_value = {
            "success": True,
            "mode": browser_mode,
            "error": None,
        }

        mock_ensure_project.return_value = {
            "success": True,
            "project_id": "98765",
            "url": "https://linkedin.com/talent/hire/98765/overview",
            "status": "created",
            "message": "Created new project",
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

        result = bp.bootstrap_project(args)

        assert result["project_id"] == "98765"

        # Verify project creation was called with BrowserMode
        call_kwargs = mock_ensure_project.call_args[1]
        passed_mode = call_kwargs["browser_mode"]
        assert passed_mode is browser_mode
        assert passed_mode.mode == "cdp"
        assert passed_mode.cdp_port == "9230"


class TestNormalizeToPlainText:
    """Tests for HTML to plain text normalization."""

    def test_returns_plain_text_unchanged(self):
        """Should return plain text with minimal normalization."""
        text = "This is a plain text job description."
        result = bp.normalize_to_plain_text(text)

        assert result == text

    def test_normalizes_whitespace_in_plain_text(self):
        """Should normalize excessive whitespace in plain text."""
        text = "This   has   extra   spaces\n\n\nand newlines"
        result = bp.normalize_to_plain_text(text)

        assert result == "This has extra spaces and newlines"

    def test_strips_html_tags(self):
        """Should strip HTML tags from content."""
        html = "<p>This is a <strong>job</strong> description.</p>"
        result = bp.normalize_to_plain_text(html)

        assert "<p>" not in result
        assert "<strong>" not in result
        assert "job" in result

    def test_removes_script_tags(self):
        """Should remove script tags and their content."""
        html = '<p>Job description</p><script>alert("xss")</script><p>More content</p>'
        result = bp.normalize_to_plain_text(html)

        assert "<script>" not in result
        assert "alert" not in result
        assert "Job description" in result
        assert "More content" in result

    def test_removes_style_tags(self):
        """Should remove style tags and their content."""
        html = "<p>Job</p><style>body { color: red; }</style><p>Description</p>"
        result = bp.normalize_to_plain_text(html)

        assert "<style>" not in result
        assert "color: red" not in result
        assert "Job" in result
        assert "Description" in result

    def test_decodes_html_entities(self):
        """Should decode HTML entities to plain text."""
        html = "<p>Job &amp; Description &lt;test&gt;</p>"
        result = bp.normalize_to_plain_text(html)

        assert "&amp;" not in result
        assert "&lt;" not in result
        assert "Job & Description <test>" in result

    def test_preserves_paragraph_structure(self):
        """Should preserve paragraph breaks as double newlines."""
        html = "<p>First paragraph</p><p>Second paragraph</p>"
        result = bp.normalize_to_plain_text(html)

        assert "First paragraph" in result
        assert "Second paragraph" in result
        # Should have paragraph separation
        assert "\n\n" in result or result.index("Second") > result.index("First") + 20

    def test_handles_div_blocks(self):
        """Should treat divs as block elements."""
        html = "<div>First section</div><div>Second section</div>"
        result = bp.normalize_to_plain_text(html)

        assert "First section" in result
        assert "Second section" in result

    def test_handles_headings(self):
        """Should treat headings as block elements."""
        html = "<h1>Title</h1><h2>Subtitle</h2><p>Content</p>"
        result = bp.normalize_to_plain_text(html)

        assert "Title" in result
        assert "Subtitle" in result
        assert "Content" in result

    def test_handles_list_items(self):
        """Should treat list items as block elements."""
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        result = bp.normalize_to_plain_text(html)

        assert "Item 1" in result
        assert "Item 2" in result

    def test_handles_br_tags(self):
        """Should convert br tags to newlines."""
        html = "Line 1<br>Line 2<br/>Line 3"
        result = bp.normalize_to_plain_text(html)

        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_handles_empty_content(self):
        """Should handle empty content gracefully."""
        assert bp.normalize_to_plain_text("") == ""
        assert bp.normalize_to_plain_text(None) == ""

    def test_handles_complex_html(self):
        """Should handle complex real-world HTML."""
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Job Posting</title></head>
        <body>
            <h1>Senior Engineer</h1>
            <div class="content">
                <p>We are looking for a <strong>talented</strong> engineer.</p>
                <ul>
                    <li>5+ years experience</li>
                    <li>Python expertise</li>
                </ul>
            </div>
            <script>console.log('test');</script>
        </body>
        </html>
        """
        result = bp.normalize_to_plain_text(html)

        # Should contain visible content
        assert "Senior Engineer" in result
        assert "talented" in result
        assert "engineer" in result
        assert "5+ years experience" in result
        assert "Python expertise" in result

        # Should not contain HTML/script
        assert "<script>" not in result
        assert "console.log" not in result
        assert "<html>" not in result
        assert "<body>" not in result

    def test_handles_tiktok_html_structure(self):
        """Should handle TikTok job page HTML structure."""
        html = """
        <div class="job-description">
            <h1>SoC Digital Design Engineer</h1>
            <p>Location: San Jose</p>
            <div class="about">
                <p>About the team: We build hardware.</p>
            </div>
        </div>
        """
        result = bp.normalize_to_plain_text(html)

        assert "SoC Digital Design Engineer" in result
        assert "Location: San Jose" in result
        assert "About the team" in result
        assert "<div" not in result


class TestProjectStateIntegration:
    """Tests for project_state.json creation during bootstrap."""

    def test_creates_project_state_on_bootstrap(self, tmp_path, monkeypatch):
        """Should create project_state.json during bootstrap."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "Job description content"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Senior Engineer"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Check project_state.json was created
        project_dir = Path(result["project_dir"])
        state_file = project_dir / "project_state.json"
        assert state_file.exists()

        # Verify state content
        state = json.loads(state_file.read_text())
        assert state["project_id"] == "12345"
        assert state["workflow_mode"] == "reachout"
        assert state["current_phase"] == "bootstrap"
        assert state["status"] == "completed"

    def test_saves_normalized_jd_not_html(self, tmp_path, monkeypatch):
        """Should save normalized plain text JD, not raw HTML."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = None
        args.jd_text = "<p>Job description with <strong>HTML</strong> tags</p>"
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        )
        args.cdp_port = "9230"
        args.project_id = None
        args.position_title = "Test Position"
        args.team_name = None
        args.location = None
        args.core_function = None
        args.business_impact = None
        args.keywords = None
        args.companies = None
        args.exclude_titles = None

        result = bp.bootstrap_project(args)

        # Check JD was normalized
        jd_path = Path(result["jd_path"])
        jd_content = jd_path.read_text()

        assert "<p>" not in jd_content
        assert "<strong>" not in jd_content
        assert "Job description with HTML tags" in jd_content


class TestProjectDeduplication:
    """Tests for project deduplication/reuse behavior."""

    def test_reuses_project_by_exact_jd_url(self, tmp_path, monkeypatch):
        """Should reuse existing project when JD URL matches exactly."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with JD_URL
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_engineer"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'JD_URL="https://example.com/jobs/123"\n'
            'POSITION_TITLE="Existing Engineer"\n'
        )

        args = Mock()
        args.jd_url = "https://example.com/jobs/123"  # Same JD URL
        args.jd_text = None
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
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

        # Should reuse by JD URL
        assert result["project_id"] == "12345"
        assert result["reused"] is True
        assert result["match_type"] == "jd_url"

    def test_reuses_project_by_exact_jd_content(self, tmp_path, monkeypatch):
        """Should reuse existing project when JD content matches exactly."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "Senior ML Engineer\n\nWe are looking for an experienced ML engineer."
        )

        # Create existing project with JD content
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_engineer"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            'POSITION_TITLE="Existing Engineer"\n'
        )
        # Write JD content
        jd_path = existing_project / "job_description.txt"
        jd_path.write_text(jd_content)

        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
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

        # Should reuse by JD content
        assert result["project_id"] == "12345"
        assert result["reused"] is True
        assert result["match_type"] == "jd_content"

    def test_ambiguous_matches_raise_error_with_candidates(self, tmp_path, monkeypatch):
        """Should raise error with candidate list when multiple projects match."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "Senior ML Engineer\n\nWe are looking for an experienced ML engineer."
        )

        # Create TWO existing projects with same JD content
        work_dir = tmp_path / "work"

        # First project
        project1 = work_dir / "projects" / "11111_first"
        project1.mkdir(parents=True)
        (project1 / "config.sh").write_text(
            'PROJECT_ID="11111"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/11111/overview"\n'
            'POSITION_TITLE="First Project"\n'
        )
        (project1 / "job_description.txt").write_text(jd_content)

        # Second project
        project2 = work_dir / "projects" / "22222_second"
        project2.mkdir(parents=True)
        (project2 / "config.sh").write_text(
            'PROJECT_ID="22222"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/22222/overview"\n'
            'POSITION_TITLE="Second Project"\n'
        )
        (project2 / "job_description.txt").write_text(jd_content)

        args = Mock()
        args.jd_url = None
        args.jd_text = jd_content  # Same JD content as both projects
        args.work_dir = str(work_dir)
        args.recruiter_url = (
            "https://linkedin.com/talent/hire/33333/"  # Different recruiter
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

        try:
            bp.bootstrap_project(args)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            error_msg = str(e)
            assert "Multiple existing projects match" in error_msg
            assert "11111" in error_msg
            assert "22222" in error_msg
            assert "First Project" in error_msg
            assert "Second Project" in error_msg
            assert "--project-id" in error_msg

    def test_no_fuzzy_match_creates_new_project(self, tmp_path, monkeypatch):
        """Should create new project when JD content is similar but not exact match."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create existing project with specific JD content
        work_dir = tmp_path / "work"
        existing_project = work_dir / "projects" / "12345_engineer"
        existing_project.mkdir(parents=True)
        config_path = existing_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
        )
        (existing_project / "job_description.txt").write_text(
            "Senior ML Engineer\n\nWe are looking for an experienced ML engineer."
        )

        # Different JD content (not exact match)
        new_jd_content = "Senior ML Engineer\n\nWe are looking for a senior ML engineer with 5+ years experience."

        args = Mock()
        args.jd_url = None
        args.jd_text = new_jd_content  # Similar but not exact
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/67890/"
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

        # Should create new project, not reuse
        assert result["project_id"] == "67890"
        assert result["reused"] is False

    def test_jd_url_persisted_in_config(self, tmp_path, monkeypatch):
        """Should persist JD_URL in config for future deduplication."""
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        args = Mock()
        args.jd_url = "https://example.com/jobs/unique-123"
        args.jd_text = None
        args.work_dir = str(tmp_path / "work")
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
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

        # Check JD_URL is persisted in config (shell_escape may use single quotes)
        config_content = Path(result["config_path"]).read_text()
        assert "JD_URL=" in config_content
        assert "https://example.com/jobs/unique-123" in config_content

    def test_no_reuse_for_old_projects_without_jd_match(self, tmp_path, monkeypatch):
        """Old projects without JD_URL or JD content match should NOT be auto-reused.

        New contract: reuse ONLY on exact JD_URL or exact JD-content match.
        No auto-reuse by recruiter_id alone, even for legacy projects.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        # Create old project without JD_URL and without matching JD content
        work_dir = tmp_path / "work"
        old_project = work_dir / "projects" / "legacy_project"
        old_project.mkdir(parents=True)
        config_path = old_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="legacy_project"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/12345/overview"\n'
            # No JD_URL - simulating old project
        )
        # No job_description.txt or different content

        # New bootstrap with same recruiter_id but different JD
        args = Mock()
        args.jd_url = "https://example.com/jobs/new-job"
        args.jd_text = None
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/12345/"
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

        # Should create NEW project (not reuse) - no JD match
        assert result["project_id"] == "12345"  # Derived from recruiter_url
        assert result["reused"] is False
        # Should be a new directory, not the legacy one
        assert "legacy_project" not in result["project_dir"]

    @patch("bootstrap_project.fetch_url")
    def test_reuses_legacy_project_by_jd_content_when_jd_url_provided(
        self, mock_fetch, tmp_path, monkeypatch
    ):
        """Regression test: Legacy project without JD_URL should be reused by JD content match even when --jd-url is provided.

        Issue: When bootstrapping with --jd-url, the old code disabled JD-content matching,
        breaking backward compatibility for legacy projects that don't have JD_URL persisted.
        Fix: Always pass jd_content for matching, allowing legacy projects to be found by
        exact normalized job_description.txt content even when current input comes via --jd-url.
        """
        monkeypatch.setattr(bp.Path, "home", lambda: tmp_path)

        jd_content = (
            "Senior ML Engineer\n\nWe are looking for an experienced ML engineer."
        )

        # Create legacy project WITHOUT JD_URL but WITH matching job_description.txt
        work_dir = tmp_path / "work"
        legacy_project = work_dir / "projects" / "legacy_project"
        legacy_project.mkdir(parents=True)
        config_path = legacy_project / "config.sh"
        config_path.write_text(
            'PROJECT_ID="legacy_project"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/99999/overview"\n'
            'POSITION_TITLE="Legacy Position"\n'
            # No JD_URL - simulating legacy project created before JD_URL persistence
        )
        # Write JD content that will match
        jd_path = legacy_project / "job_description.txt"
        jd_path.write_text(jd_content)

        # Mock fetch_url to return the same JD content
        mock_fetch.return_value = (200, f"<html><body>{jd_content}</body></html>")

        # Bootstrap with --jd-url where fetched content matches existing job_description.txt
        args = Mock()
        args.jd_url = (
            "https://example.com/jobs/123"  # Different URL than legacy project
        )
        args.jd_text = None
        args.work_dir = str(work_dir)
        args.recruiter_url = "https://linkedin.com/talent/hire/99999/"
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

        # Should reuse the legacy project by JD content match (not by JD URL since it doesn't have one)
        assert result["project_id"] == "legacy_project"
        assert result["reused"] is True
        assert result["match_type"] == "jd_content"

        # Config should be updated
        config_content = Path(result["config_path"]).read_text()
        assert "Updated Title" in config_content
        # JD_URL should now be persisted for future deduplication
        assert "JD_URL=" in config_content
        assert "https://example.com/jobs/123" in config_content


class TestCreateSearchMessaging:
    """Tests for agent-actionable create_search messaging."""

    def test_action_required_is_agent_actionable(self):
        """Action required message should direct the agent, not the user."""
        # Import run_create_search functions
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import run_create_search as rcs

        action = rcs.build_action_required(
            recruiter_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            search_brief="Test search brief",
        )

        # Should have agent-actionable summary
        assert "needs a candidate search" in action["summary"]
        # Should NOT use "You need to" phrasing
        assert "You need to" not in action.get("message", "")
        # Should have clear message for agent
        assert "Open the Recruiter project" in action["message"]
        assert "copilot" in action["message"].lower()

    def test_action_required_steps_are_agent_focused(self):
        """Action required steps should be clear for agent execution."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import run_create_search as rcs

        action = rcs.build_action_required(
            recruiter_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            search_brief="Test search brief",
        )

        steps = action["steps"]
        # Steps should be actionable by agent
        assert any("Open the Recruiter project" in step for step in steps)
        assert any("search brief" in step.lower() for step in steps)
        # Should include retry instruction
        assert any("re-run" in step.lower() for step in steps)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
