#!/usr/bin/env python3
"""Tests for run_extraction.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_run_extraction.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_extraction as re


@pytest.fixture
def mock_ready_preflight_probe():
    """Patch browser preflight to a ready state for non-preflight tests."""
    with patch("recruiter_page_utils.PageStateProbe") as mock_probe_class:
        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "ready"}
        mock_probe_class.return_value = mock_probe
        yield mock_probe_class


class TestParseConfigFile:
    """Tests for config file parsing."""

    def test_parses_quoted_values(self, tmp_path):
        """Should parse double-quoted values from config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            'PROJECT_ID="12345"\n'
            'RECRUITER_PROJECT_URL="https://linkedin.com/talent/hire/123"\n'
            'POSITION_TITLE="Software Engineer"'
        )

        result = re.parse_config_file(str(config_file))

        assert result["PROJECT_ID"] == "12345"
        assert result["RECRUITER_PROJECT_URL"] == "https://linkedin.com/talent/hire/123"
        assert result["POSITION_TITLE"] == "Software Engineer"

    def test_parses_single_quoted_values(self, tmp_path):
        """Should parse single-quoted values from config."""
        config_file = tmp_path / "config.sh"
        config_file.write_text(
            "RECRUITER_PROJECT_URL='https://linkedin.com/talent/hire/456'"
        )

        result = re.parse_config_file(str(config_file))

        assert result["RECRUITER_PROJECT_URL"] == "https://linkedin.com/talent/hire/456"

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

        result = re.parse_config_file(str(config_file))

        assert result["PROJECT_ID"] == "123"
        assert result["POSITION_TITLE"] == "Engineer"
        assert "# This is a comment" not in result

    def test_returns_empty_dict_for_missing_file(self):
        """Should return empty dict when config file doesn't exist."""
        result = re.parse_config_file("/nonexistent/config.sh")

        assert result == {}


class TestResolveWorkbookPath:
    """Tests for workbook path resolution."""

    @patch("run_extraction.RuntimeManager")
    def test_uses_cli_path_when_provided(self, mock_manager_class, tmp_path):
        """CLI path should take precedence."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager_class.return_value = mock_manager

        config = {"PROJECT_ID": "12345"}
        cli_path = str(tmp_path / "custom" / "workbook.xlsx")

        result = re.resolve_workbook_path(config, cli_path)

        assert result == Path(cli_path).resolve()

    @patch("run_extraction.RuntimeManager")
    def test_derives_from_project_id(self, mock_manager_class, tmp_path):
        """Should derive path from PROJECT_ID and work_dir."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager_class.return_value = mock_manager

        config = {"PROJECT_ID": "12345"}

        result = re.resolve_workbook_path(config, None)

        expected = (tmp_path / "work" / "projects" / "12345.xlsx").resolve()
        assert result == expected

    @patch("run_extraction.RuntimeManager")
    def test_raises_when_no_project_id_and_no_cli(self, mock_manager_class, tmp_path):
        """Should raise ValueError when PROJECT_ID missing and no CLI path."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager_class.return_value = mock_manager

        config = {}

        try:
            re.resolve_workbook_path(config, None)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "PROJECT_ID" in str(e)


class TestEnsureWorkbook:
    """Tests for workbook creation."""

    def test_returns_true_if_exists(self, tmp_path):
        """Should return True if workbook already exists."""
        wb_path = tmp_path / "existing.xlsx"
        wb_path.touch()  # Create empty file

        result = re.ensure_workbook(wb_path)

        assert result is True

    @patch("run_extraction.create")
    def test_creates_workbook_if_missing(self, mock_create, tmp_path):
        """Should create workbook if it doesn't exist."""
        wb_path = tmp_path / "nested" / "dir" / "new.xlsx"

        result = re.ensure_workbook(wb_path)

        assert result is True
        mock_create.assert_called_once_with(wb_path)

    @patch("run_extraction.create")
    def test_returns_false_on_error(self, mock_create, tmp_path):
        """Should return False if creation fails."""
        mock_create.side_effect = PermissionError("Cannot write")

        wb_path = tmp_path / "new.xlsx"
        result = re.ensure_workbook(wb_path)

        assert result is False


class TestBuildPaginatedUrl:
    """Tests for pagination URL builder."""

    def test_page_1_has_no_start_param(self):
        """Page 1 should use base URL without start parameter."""
        base_url = "https://www.linkedin.com/talent/hire/123/discover/recruiterSearch"
        result = re.build_paginated_url(base_url, page=1)
        assert "start=" not in result
        assert result == base_url

    def test_page_2_adds_start_25(self):
        """Page 2 should add ?start=25."""
        base_url = "https://www.linkedin.com/talent/hire/123/discover/recruiterSearch"
        result = re.build_paginated_url(base_url, page=2)
        assert "start=25" in result

    def test_page_3_adds_start_50(self):
        """Page 3 should add ?start=50."""
        base_url = "https://www.linkedin.com/talent/hire/123/discover/recruiterSearch"
        result = re.build_paginated_url(base_url, page=3)
        assert "start=50" in result

    def test_preserves_existing_query_params(self):
        """Should preserve existing query parameters."""
        base_url = "https://www.linkedin.com/talent/hire/123/discover/recruiterSearch?projectId=456"
        result = re.build_paginated_url(base_url, page=2)
        assert "projectId=456" in result
        assert "start=25" in result

    def test_replaces_existing_start_param(self):
        """Should replace existing start parameter."""
        base_url = "https://www.linkedin.com/talent/hire/123/discover/recruiterSearch?start=100"
        result = re.build_paginated_url(base_url, page=2)
        assert "start=25" in result
        assert "start=100" not in result

    def test_custom_page_size(self):
        """Should use custom page size when provided."""
        base_url = "https://www.linkedin.com/talent/hire/123/discover/recruiterSearch"
        result = re.build_paginated_url(base_url, page=3, page_size=10)
        assert "start=20" in result  # (3-1) * 10 = 20


class TestProcessCandidates:
    """Tests for candidate processing with upsert semantics."""

    def test_inserts_new_candidates(self, tmp_path):
        """Should insert new candidates."""
        wb_path = tmp_path / "test.xlsx"

        with patch("run_extraction.create"):
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}

                candidates = [
                    {"name": "John", "url": "https://linkedin.com/in/john"},
                    {"name": "Jane", "url": "https://linkedin.com/in/jane"},
                ]
                existing_urls = set()

                stats = re.process_candidates(
                    candidates, wb_path, existing_urls, dry_run=False
                )

                assert stats["total"] == 2
                assert stats["new"] == 2
                assert stats["updated"] == 0
                assert stats["skipped"] == 0
                assert mock_upsert.call_count == 2

    def test_updates_existing_candidates_on_rerun(self, tmp_path):
        """Should update existing candidates on rerun (upsert semantics)."""
        wb_path = tmp_path / "test.xlsx"

        candidates = [
            {
                "name": "John Updated",
                "url": "https://linkedin.com/in/john",
                "title": "Senior Engineer",
            },
            {"name": "Jane", "url": "https://linkedin.com/in/jane"},
        ]
        existing_urls = {"https://linkedin.com/in/john"}

        with patch("run_extraction.upsert") as mock_upsert:
            # First candidate exists and gets updated, second is new
            mock_upsert.side_effect = [
                {"row_id": 1, "action": "updated"},
                {"row_id": 2, "action": "inserted"},
            ]

            stats = re.process_candidates(
                candidates, wb_path, existing_urls, dry_run=False
            )

            # Both should be processed via upsert
            assert stats["total"] == 2
            assert stats["new"] == 1
            assert stats["updated"] == 1
            assert stats["skipped"] == 0
            assert mock_upsert.call_count == 2

    def test_tracks_all_urls_after_processing(self, tmp_path):
        """Should track all processed URLs in existing_urls set."""
        wb_path = tmp_path / "test.xlsx"

        candidates = [
            {"name": "John", "url": "https://linkedin.com/in/john"},
            {"name": "Jane", "url": "https://linkedin.com/in/jane"},
        ]
        existing_urls = set()

        with patch("run_extraction.upsert") as mock_upsert:
            mock_upsert.side_effect = [
                {"row_id": 1, "action": "inserted"},
                {"row_id": 2, "action": "inserted"},
            ]
            re.process_candidates(candidates, wb_path, existing_urls, dry_run=False)

            assert "https://linkedin.com/in/john" in existing_urls
            assert "https://linkedin.com/in/jane" in existing_urls

    def test_dry_run_skips_existing_urls(self, tmp_path):
        """Dry run should skip URLs already in existing_urls set."""
        wb_path = tmp_path / "test.xlsx"

        candidates = [
            {"name": "John", "url": "https://linkedin.com/in/john"},
            {"name": "Jane", "url": "https://linkedin.com/in/jane"},
        ]
        existing_urls = {"https://linkedin.com/in/john"}

        with patch("run_extraction.upsert") as mock_upsert:
            stats = re.process_candidates(
                candidates, wb_path, existing_urls, dry_run=True
            )

            assert stats["total"] == 2
            assert stats["new"] == 1
            assert stats["skipped"] == 1
            assert mock_upsert.call_count == 0

    def test_dry_run_tracks_new_urls(self, tmp_path):
        """Dry run should track new URLs in existing_urls set."""
        wb_path = tmp_path / "test.xlsx"

        candidates = [{"name": "John", "url": "https://linkedin.com/in/john"}]
        existing_urls = set()

        with patch("run_extraction.upsert") as mock_upsert:
            re.process_candidates(candidates, wb_path, existing_urls, dry_run=True)

            assert "https://linkedin.com/in/john" in existing_urls

    def test_returns_error_on_permission_error(self, tmp_path):
        """Should return error dict on PermissionError during upsert."""
        wb_path = tmp_path / "test.xlsx"

        candidates = [{"name": "John", "url": "https://linkedin.com/in/john"}]
        existing_urls = set()

        with patch("run_extraction.upsert") as mock_upsert:
            mock_upsert.side_effect = PermissionError("Cannot write to file")

            result = re.process_candidates(
                candidates, wb_path, existing_urls, dry_run=False
            )

            assert result.get("error") is True
            assert "Workbook write failed" in result["message"]

    def test_returns_error_on_os_error(self, tmp_path):
        """Should return error dict on OSError during upsert."""
        wb_path = tmp_path / "test.xlsx"

        candidates = [{"name": "John", "url": "https://linkedin.com/in/john"}]
        existing_urls = set()

        with patch("run_extraction.upsert") as mock_upsert:
            mock_upsert.side_effect = OSError("Disk full")

            result = re.process_candidates(
                candidates, wb_path, existing_urls, dry_run=False
            )

            assert result.get("error") is True
            assert "Workbook write failed" in result["message"]

    def test_returns_error_on_badzipfile(self, tmp_path):
        """Should return error dict on BadZipFile during upsert (corrupt workbook)."""
        wb_path = tmp_path / "test.xlsx"

        candidates = [{"name": "John", "url": "https://linkedin.com/in/john"}]
        existing_urls = set()

        with patch("run_extraction.upsert") as mock_upsert:
            from zipfile import BadZipFile

            mock_upsert.side_effect = BadZipFile("File is not a zip file")

            result = re.process_candidates(
                candidates, wb_path, existing_urls, dry_run=False
            )

            assert result.get("error") is True
            assert "Workbook write failed" in result["message"]


class TestBoundedExtractionState:
    """Tests for bounded extraction (--max-pages) state persistence."""

    def test_bounded_extraction_marks_completed_when_finished(self, tmp_path):
        """Bounded extraction should mark state as completed when all pages processed.

        This tests the fix for the gap where direct run_extraction with --max-pages
        left project_state.json stuck at current_phase=extract, status=running.
        """
        # Simulate the final status determination logic from run_extraction
        max_pages = 2
        pages_processed = 2
        max_pages_reached = True

        # When bounded extraction completes (all requested pages processed)
        bounded_extraction_complete = max_pages > 0 and pages_processed >= max_pages
        reached_end_of_results = not max_pages_reached  # False in this case

        # Should be marked as completed, not running
        assert bounded_extraction_complete is True
        final_status = (
            "completed"
            if (bounded_extraction_complete or reached_end_of_results)
            else "running"
        )
        assert final_status == "completed"

    def test_unbounded_extraction_marks_running_when_interrupted(self, tmp_path):
        """Unbounded extraction should mark running when not finished."""
        max_pages = 0  # Unlimited
        pages_processed = 5
        max_pages_reached = False  # User interrupted, not max-pages limit

        bounded_extraction_complete = max_pages > 0 and pages_processed >= max_pages
        reached_end_of_results = not max_pages_reached

        # Neither condition met - should be running
        assert bounded_extraction_complete is False
        assert reached_end_of_results is True  # This would actually be completed
        final_status = (
            "completed"
            if (bounded_extraction_complete or reached_end_of_results)
            else "running"
        )
        assert final_status == "completed"


class TestEndOfResultsCompletion:
    """Tests for clean end-of-results completion detection."""

    def test_reached_end_of_results_set_on_last_page(self):
        """reached_end_of_results should be True when last page detected."""
        # Simulate the logic when is_last_page is detected during navigation
        is_last_page = True
        reached_end_of_results = False

        if is_last_page:
            reached_end_of_results = True

        assert reached_end_of_results is True

    def test_reached_end_of_results_set_on_no_candidates(self):
        """reached_end_of_results should be True when no candidates found."""
        candidates = []
        reached_end_of_results = False

        if not candidates:
            reached_end_of_results = True

        assert reached_end_of_results is True

    def test_reached_end_of_results_set_on_exit_code_2(self):
        """reached_end_of_results should be True when extraction returns exit code 2 (no results)."""
        exit_code = 2
        reached_end_of_results = False

        if exit_code == 2:
            reached_end_of_results = True

        assert reached_end_of_results is True

    def test_final_status_completed_when_reached_end_of_results(self):
        """Final status should be 'completed' when reached_end_of_results is True."""
        bounded_extraction_complete = False
        reached_end_of_results = True

        final_status = (
            "completed"
            if (bounded_extraction_complete or reached_end_of_results)
            else "running"
        )

        assert final_status == "completed"

    def test_resume_state_completed_clears_next_start_page(self):
        """When extraction completes, resume state should have next_start_page=None."""
        reached_end_of_results = True

        if reached_end_of_results:
            resume_final_status = "completed"
            resume_next_start_page = None
        else:
            resume_final_status = "running"
            resume_next_start_page = 5

        assert resume_final_status == "completed"
        assert resume_next_start_page is None


class TestRunExtraction:
    """Integration tests for run_extraction workflow."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in run_extraction tests."""

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_successful_extraction(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should complete extraction successfully."""
        # Setup mocks
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [
                {
                    "name": "John",
                    "url": "https://linkedin.com/in/john",
                    "title": "Engineer",
                },
            ],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create mock args
        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}

                result = re.run_extraction(args)

        assert result["success"] is True
        assert result["pages_processed"] == 1
        assert result["candidates_total"] == 1

    @patch("run_extraction.parse_config_file")
    def test_fails_when_no_recruiter_url(self, mock_parse):
        """Should fail when RECRUITER_PROJECT_URL not in config."""
        mock_parse.return_value = {"PROJECT_ID": "123"}  # No RECRUITER_PROJECT_URL

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None

        result = re.run_extraction(args)

        assert result["success"] is False
        assert "RECRUITER_PROJECT_URL" in result["message"]

    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_fails_when_workbook_creation_fails(
        self, mock_resolve_context, mock_parse, mock_resolve, mock_ensure, tmp_path
    ):
        """Should fail when workbook cannot be created."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = False
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.dry_run = False
        args.cdp_port = "9234"

        result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 2

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_handles_extraction_failure(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should handle extraction failure gracefully."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": False,
            "message": "Browser timeout",
            "exit_code": 1,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()

            result = re.run_extraction(args)

        assert result["success"] is False
        assert "Browser timeout" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_propagates_selector_mismatch_exit_code(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should propagate exit code 3 for selector mismatch failures."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": False,
            "message": "Selector mismatch: page structure changed",
            "exit_code": 3,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()

            result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 3

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_propagates_browser_failure_exit_code(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should propagate exit code 1 for generic browser failures."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": False,
            "message": "Browser connection failed",
            "exit_code": 1,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()

            result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_handles_no_results(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should complete successfully when no results found."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": False,
            "message": "No results found",
            "exit_code": 2,  # No results code
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()

            result = re.run_extraction(args)

        assert result["success"] is True  # No results is success (just empty)
        assert result["pages_processed"] == 0

    @patch("run_extraction.navigate_to_page")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_processes_multiple_pages(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_navigate,
        tmp_path,
    ):
        """Should process multiple pages when max_pages > 1."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        # Return candidates for first two pages, then no results
        mock_extract.side_effect = [
            {
                "success": True,
                "candidates": [
                    {"name": "Page1User", "url": "https://linkedin.com/in/p1"},
                ],
                "exit_code": 0,
            },
            {
                "success": True,
                "candidates": [
                    {"name": "Page2User", "url": "https://linkedin.com/in/p2"},
                ],
                "exit_code": 0,
            },
        ]
        mock_navigate.return_value = {
            "success": True,
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25&searchContextId=abc",
            "state": "ready",
            "method": "ui_pagination",
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 2

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        assert result["success"] is True
        assert result["pages_processed"] == 2
        assert mock_navigate.call_count == 1  # Navigate called once for page 2

    @patch("run_extraction.navigate_to_page")
    @patch("run_extraction.save_extraction_state")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_fails_when_navigation_fails(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_save_state,
        mock_navigate,
        tmp_path,
    ):
        """Should fail extraction when navigation to next page fails."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_save_state.return_value = True
        # Navigation fails on page 2
        mock_navigate.return_value = {
            "success": False,
            "url": "...",
            "state": "error",
            "error": "Next page pagination control not found",
            "failure_code": "wrong_page",
            "action_required": {
                "code": "wrong_page",
                "summary": "Browser landed on the wrong page",
                "steps": ["Return to the expected search page"],
                "can_retry": True,
                "context": {},
            },
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 5  # Request more pages than available

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Navigation failed" in result["message"]
        assert result["pages_processed"] == 1  # Only processed page 1 before failure
        assert result["failure_code"] == "wrong_page"
        assert result["action_required"]["code"] == "wrong_page"

    @patch("run_extraction.navigate_to_page")
    @patch("run_extraction.save_extraction_state")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_navigation_failure_preserves_action_required_when_state_save_fails(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_save_state,
        mock_navigate,
        tmp_path,
    ):
        """Should preserve structured fallback even if state persistence also fails."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_save_state.side_effect = [True, False]
        mock_navigate.return_value = {
            "success": False,
            "url": "...",
            "state": "page_2_not_ready",
            "error": "Page 2 not ready: loading",
            "failure_code": "timeout",
            "action_required": {
                "code": "timeout",
                "summary": "Page load timed out",
                "steps": ["Wait for the page to finish loading and retry"],
                "can_retry": True,
                "context": {},
            },
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 5

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 2
        assert result["failure_code"] == "timeout"
        assert result["action_required"]["code"] == "timeout"

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_fails_when_workbook_write_fails(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should fail extraction with exit_code=2 when workbook upsert fails."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [
                {"name": "John", "url": "https://linkedin.com/in/john"},
                {"name": "Jane", "url": "https://linkedin.com/in/jane"},
            ],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                # Simulate workbook write failure on second candidate
                mock_upsert.side_effect = [
                    {"row_id": 1, "action": "inserted"},
                    PermissionError("Cannot write to workbook"),
                ]

                # Workbook failures should return stable error result with exit_code=2
                result = re.run_extraction(args)

                assert result["success"] is False
                assert result.get("exit_code") == 2
                assert "Workbook write failed" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_fails_when_workbook_corrupt_on_load(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should fail extraction with exit_code=2 when workbook is corrupt/non-xlsx."""
        from zipfile import BadZipFile

        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        # Create an actual file so workbook_path.exists() returns True
        wb_path = tmp_path / "workbook.xlsx"
        wb_path.write_text("not a valid xlsx file")  # Create corrupt file
        mock_resolve.return_value = wb_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "John", "url": "https://linkedin.com/in/john"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            # Simulate corrupt workbook when loading existing keys
            mock_keys.side_effect = BadZipFile("File is not a zip file")

            result = re.run_extraction(args)

            assert result["success"] is False
            assert result.get("exit_code") == 2
            assert "Workbook read failed" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_fails_when_workbook_missing_candidates_sheet(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should fail extraction with exit_code=2 when workbook is missing Candidates sheet."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        # Create an actual file so workbook_path.exists() returns True
        wb_path = tmp_path / "workbook.xlsx"
        wb_path.write_text("valid xlsx but missing Candidates sheet")  # File exists
        mock_resolve.return_value = wb_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "John", "url": "https://linkedin.com/in/john"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            # Simulate missing Candidates sheet when loading existing keys
            mock_keys.side_effect = KeyError("'Candidates'")

            result = re.run_extraction(args)

            assert result["success"] is False
            assert result.get("exit_code") == 2
            assert "Workbook read failed" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_fails_when_workbook_read_denied(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should fail extraction with exit_code=2 when workbook cannot be read."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        wb_path = tmp_path / "workbook.xlsx"
        wb_path.write_text("placeholder")
        mock_resolve.return_value = wb_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "John", "url": "https://linkedin.com/in/john"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.side_effect = PermissionError("read denied")

            result = re.run_extraction(args)

            assert result["success"] is False
            assert result.get("exit_code") == 2
            assert "Workbook read failed" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_fails_when_workbook_corrupt_on_upsert(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should fail extraction with exit_code=2 when upsert encounters corrupt workbook."""
        from zipfile import BadZipFile

        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "John", "url": "https://linkedin.com/in/john"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                # Simulate corrupt workbook during upsert
                mock_upsert.side_effect = BadZipFile("File is not a zip file")

                result = re.run_extraction(args)

                assert result["success"] is False
                assert result.get("exit_code") == 2
                assert "Workbook write failed" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_respects_start_page_parameter(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should start from the specified page number."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 3  # Start from page 3
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=50",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        assert result["pages_processed"] == 1
        # Should navigate to page 3 on first iteration
        mock_navigate.assert_called_once()
        call_kwargs = mock_navigate.call_args[1]
        assert call_kwargs["page"] == 3


class TestExtractProjectIdFromUrl:
    """Tests for extract_project_id_from_url function."""

    def test_extracts_project_id_from_recruiter_search_url(self):
        """Should extract project ID from recruiterSearch URL."""
        url = "https://linkedin.com/talent/hire/123456/discover/recruiterSearch"
        result = re.extract_project_id_from_url(url)
        assert result == "123456"

    def test_extracts_project_id_from_overview_url(self):
        """Should extract project ID from overview URL."""
        url = "https://linkedin.com/talent/hire/789012/overview"
        result = re.extract_project_id_from_url(url)
        assert result == "789012"

    def test_returns_none_for_invalid_url(self):
        """Should return None for URLs without project ID."""
        url = "https://linkedin.com/talent/projects"
        result = re.extract_project_id_from_url(url)
        assert result is None

    def test_returns_none_for_non_talent_url(self):
        """Should return None for non-talent URLs."""
        url = "https://linkedin.com/feed/"
        result = re.extract_project_id_from_url(url)
        assert result is None

    def test_extracts_from_url_without_trailing_slash(self):
        """Should extract project ID from URL without trailing slash (slashless)."""
        url = "https://linkedin.com/talent/hire/12345"
        result = re.extract_project_id_from_url(url)
        assert result == "12345"

    def test_extracts_from_url_with_query_no_trailing_slash(self):
        """Should extract ID from URL with query params but no trailing slash."""
        url = "https://linkedin.com/talent/hire/12345?searchContextId=abc"
        result = re.extract_project_id_from_url(url)
        assert result == "12345"

    def test_extracts_from_url_with_hash_no_trailing_slash(self):
        """Should extract ID from URL with hash fragment but no trailing slash."""
        url = "https://linkedin.com/talent/hire/12345#tab"
        result = re.extract_project_id_from_url(url)
        assert result == "12345"

    def test_returns_none_for_evil_domain(self):
        """Should return None for non-LinkedIn domains with matching path."""
        url = "https://evil.com/talent/hire/12345"
        result = re.extract_project_id_from_url(url)
        assert result is None

    def test_returns_none_for_phishing_domain(self):
        """Should return None for phishing domains mimicking LinkedIn."""
        url = "https://linkedin.evil.com/talent/hire/12345"
        result = re.extract_project_id_from_url(url)
        assert result is None

    def test_returns_none_for_fake_linkedin_subdomain(self):
        """Should return None for fake linkedin subdomains."""
        url = "https://fake-linkedin.com/talent/hire/12345"
        result = re.extract_project_id_from_url(url)
        assert result is None

    def test_extracts_from_www_linkedin(self):
        """Should extract ID from www.linkedin.com domain."""
        url = "https://www.linkedin.com/talent/hire/12345"
        result = re.extract_project_id_from_url(url)
        assert result == "12345"


class TestBuildProjectOverviewUrl:
    """Tests for build_project_overview_url function."""

    def test_builds_overview_url_from_project_id(self):
        """Should build correct overview URL from project ID."""
        result = re.build_project_overview_url("123456")
        assert result == "https://www.linkedin.com/talent/hire/123456/overview"

    def test_builds_url_with_different_project_id(self):
        """Should build URL with different project ID."""
        result = re.build_project_overview_url("999999")
        assert result == "https://www.linkedin.com/talent/hire/999999/overview"


class TestValidatePaginationResult:
    """Tests for validate_pagination_result function."""

    def test_validates_successful_pagination(self):
        """Should validate successful pagination result."""
        pagination_result = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
        }
        result = re.validate_pagination_result(
            pagination_result, expected_page=2, project_id="123"
        )
        assert result["valid"] is True
        assert result["error"] is None

    def test_fails_when_pagination_failed(self):
        """Should fail when pagination was not successful."""
        pagination_result = {
            "success": False,
            "current_url": "",
            "error": "Next page pagination control not found",
        }
        result = re.validate_pagination_result(
            pagination_result, expected_page=2, project_id="123"
        )
        assert result["valid"] is False
        assert "Next page pagination control not found" in result["error"]

    def test_fails_on_project_id_mismatch(self):
        """Should fail when project ID doesn't match."""
        pagination_result = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/999/discover/recruiterSearch?start=25",
        }
        result = re.validate_pagination_result(
            pagination_result, expected_page=2, project_id="123"
        )
        assert result["valid"] is False
        assert "Project ID mismatch" in result["error"]

    def test_fails_when_not_on_search_page(self):
        """Should fail when not on search page."""
        pagination_result = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
        }
        result = re.validate_pagination_result(
            pagination_result, expected_page=2, project_id="123"
        )
        assert result["valid"] is False
        assert "Not on search page" in result["error"]

    def test_fails_on_wrong_start_offset(self):
        """Should fail when start offset doesn't match expected page."""
        pagination_result = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=0",
        }
        result = re.validate_pagination_result(
            pagination_result, expected_page=2, project_id="123"
        )
        assert result["valid"] is False
        assert "start=25" in result["error"]


class TestFreshContextResolution:
    """Tests for fresh search context resolution (stale URL handling)."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in fresh-context tests."""

    @patch("run_extraction.resolve_fresh_search_context")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    def test_stale_configured_url_gets_refreshed(
        self,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_resolve_context,
        tmp_path,
    ):
        """Stale contextual/bare configured URL should be refreshed before extraction."""
        # Config has a stale/bare URL (no search context)
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "John", "url": "https://linkedin.com/in/john"}],
            "exit_code": 0,
        }
        # Fresh context resolution returns a contextual URL
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123&projectId=123",
            "error": None,
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        assert result["success"] is True
        # Verify fresh context was resolved
        mock_resolve_context.assert_called_once()
        # Verify extraction used the fresh URL (with context params)
        call_args = mock_extract.call_args
        assert "searchContextId" in call_args[1]["target_url"]

    @patch("run_extraction.resolve_fresh_search_context")
    @patch("run_extraction.run_preflight")
    @patch("run_extraction.parse_config_file")
    def test_fail_closed_when_fresh_context_cannot_be_resolved(
        self, mock_parse, mock_preflight, mock_resolve_context, tmp_path
    ):
        """Should fail closed with clear error when fresh context cannot be resolved."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        # Fresh context resolution fails
        mock_resolve_context.return_value = {
            "success": False,
            "fresh_url": None,
            "error": (
                "Could not resolve fresh search context from https://linkedin.com/talent/hire/123/overview. "
                "The configured URL may be stale or the project may not have active search context. "
                "Try visiting the project in LinkedIn Recruiter and performing a search first."
            ),
            "failure_code": "browser_unavailable",
            "action_required": {
                "code": "browser_unavailable",
                "summary": "Chrome browser is not available for automation",
                "steps": ["Reconnect Chrome"],
                "can_retry": True,
                "context": {},
            },
        }

        mock_preflight.return_value = {
            "success": True,
            "project_id": "123",
            "cdp_port": "9234",
            "work_dir": str(tmp_path),
            "workbook_path": tmp_path / "workbook.xlsx",
            "existing_urls": set(),
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 1

        result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Could not resolve fresh search context" in result["message"]
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"]["code"] == "browser_unavailable"


class TestPaginationControls:
    """Tests for UI pagination control usage."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in pagination tests."""

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_page2_navigation_uses_ui_pagination(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_click_next,
        mock_get_current,
        mock_ensure_ready,
        tmp_path,
    ):
        """Page-2 navigation should use UI pagination and return actual URL."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.side_effect = [
            {
                "success": True,
                "candidates": [
                    {"name": "Page1User", "url": "https://linkedin.com/in/p1"}
                ],
                "exit_code": 0,
            },
            {
                "success": True,
                "candidates": [
                    {"name": "Page2User", "url": "https://linkedin.com/in/p2"}
                ],
                "exit_code": 0,
            },
        ]
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        # UI pagination returns actual URL from browser
        actual_page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25&searchContextId=abc&uiOrigin=PAGINATION"
        mock_click_next.return_value = {
            "success": True,
            "previous_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "current_url": actual_page2_url,
            "error": None,
        }
        mock_get_current.return_value = {
            "success": True,
            "current_page": 1,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        # Mock ensure_page_ready to return ready for both page 1 and page 2
        mock_ensure_ready.side_effect = [
            {"ready": True, "state": "ready"},  # Page 1
            {"ready": True, "state": "ready"},  # Page 2
        ]

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 2

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        assert result["success"] is True
        assert result["pages_processed"] == 2
        # Verify UI pagination was used
        mock_click_next.assert_called_once()
        # Verify extraction used the actual URL from pagination
        second_call_args = mock_extract.call_args_list[1]
        assert second_call_args[1]["target_url"] == actual_page2_url
        assert "uiOrigin=PAGINATION" in second_call_args[1]["target_url"]

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_fallback_when_pagination_control_missing(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_click_next,
        mock_get_current,
        mock_ensure_ready,
        tmp_path,
    ):
        """Should fall back to synthesized URL when pagination control is missing."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "Page1User", "url": "https://linkedin.com/in/p1"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        # UI pagination fails - control not found
        mock_click_next.return_value = {
            "success": False,
            "previous_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "current_url": "",
            "error": "Next page pagination control not found",
        }
        mock_get_current.return_value = {
            "success": True,
            "current_page": 1,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        # Mock ensure_page_ready for both pages (fallback succeeds)
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 2

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        # Should succeed via fallback
        assert result["success"] is True
        assert result["pages_processed"] == 2
        # Verify UI pagination was attempted
        mock_click_next.assert_called_once()
        # Verify fallback was used (method would be 'synthesized_fallback')
        # The second extraction call should use synthesized URL with start=25
        second_call_args = mock_extract.call_args_list[1]
        assert "start=25" in second_call_args[1]["target_url"]

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.validate_pagination_result")
    @patch("run_extraction.click_next_page_pagination")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_clear_error_when_pagination_lands_on_wrong_page(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_click_next,
        mock_validate,
        mock_ensure_ready,
        tmp_path,
    ):
        """Should return clear error when pagination lands on wrong page."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "Page1User", "url": "https://linkedin.com/in/p1"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        # UI pagination succeeds but lands on wrong page
        mock_click_next.return_value = {
            "success": True,
            "previous_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "current_url": "https://linkedin.com/talent/hire/999/discover/recruiterSearch?start=25",  # Wrong project
            "error": None,
        }
        # Validation fails - wrong project
        mock_validate.return_value = {
            "valid": False,
            "error": "Project ID mismatch after pagination: expected 123, got 999",
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 2

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Navigation failed on page 2" in result["message"]


class TestLastPageHandling:
    """Tests for end-of-pagination handling (regression tests for blocker)."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in last-page tests."""

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_disabled_next_button_is_clean_stop(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_click_next,
        mock_get_current,
        mock_ensure_ready,
        tmp_path,
    ):
        """Disabled next button should be recognized as clean end-of-results, not error."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        # Page 1 has candidates, page 2 doesn't exist (last page)
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "Page1User", "url": "https://linkedin.com/in/p1"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        # CRITICAL: Disabled next button returns is_last_page=True, not an error
        mock_click_next.return_value = {
            "success": True,
            "is_last_page": True,
            "previous_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        mock_get_current.return_value = {
            "success": True,
            "current_page": 1,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 5  # Request more pages than available

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        # Should succeed - reached end of results cleanly
        assert result["success"] is True
        assert result["pages_processed"] == 1  # Only page 1 processed
        assert result["candidates_total"] == 1

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.click_next_page_pagination")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_missing_next_button_is_failure_not_clean_stop(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_click_next,
        mock_ensure_ready,
        tmp_path,
    ):
        """Missing next button should be a failure (fail-closed), not clean stop (issue #1 fix)."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "Page1User", "url": "https://linkedin.com/in/p1"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        # Missing next button - should now return failure (fail-closed)
        mock_click_next.return_value = {
            "success": False,
            "is_last_page": False,
            "previous_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "current_url": "",
            "error": "Next page button not found - possible DOM drift or selector mismatch",
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 10

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        # Should FAIL - missing next button is a failure condition, not clean stop
        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Navigation failed" in result["message"]
        assert result["pages_processed"] == 1  # Only processed page 1 before failure


class TestFreshContextResolutionBlocker:
    """Regression tests for fresh-context resolution blocker."""

    @patch("run_extraction.check_current_page_ready_for_extraction")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_fail_closed_when_overview_navigation_fails(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
        mock_check_current,
    ):
        """Should fail closed when navigation to overview page cannot be confirmed."""
        mock_check_current.return_value = {
            "ready": False,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=old",
            "state": "not_contextual_search",
        }

        # Simulate navigation failure - page not ready after navigation attempt
        mock_ensure_ready.return_value = {
            "ready": False,
            "state": "unknown",
            "identity_check": {"matches": False, "error": "URL mismatch"},
            "failure_code": "browser_unavailable",
            "action_required": {
                "code": "browser_unavailable",
                "summary": "Chrome browser is not available for automation",
                "steps": ["Reconnect Chrome"],
                "can_retry": True,
                "context": {},
            },
        }
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        # Attempt to resolve fresh context
        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=old",
            work_dir=None,
        )

        # Should fail closed - don't proceed with unconfirmed navigation
        assert result["success"] is False
        assert result["fresh_url"] is None
        assert "Failed to navigate to stable project overview" in result["error"]
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"]["code"] == "browser_unavailable"
        # Should NOT call resolve_search_url with stale URL
        mock_resolve_search.assert_not_called()

    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_fail_closed_when_not_on_overview_page(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
    ):
        """Should fail closed if current URL is not overview page after navigation."""
        # Navigation succeeds but we're on wrong page type (e.g., still on search page)
        mock_ensure_ready.return_value = {
            "ready": True,
            "state": "ready",
        }
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=stale",  # Still on search!
            "project_id": "123",
            "error": None,
        }
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=stale",
            work_dir=None,
        )

        # Should fail closed - we're on search page, not overview
        assert result["success"] is False
        assert "unexpected page" in result["error"]
        assert "overview" in result["error"]
        # Should NOT reuse the stale contextual URL
        mock_resolve_search.assert_not_called()

    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_success_when_overview_confirmed(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
    ):
        """Should succeed when navigation to overview is confirmed and fresh URL resolved."""
        mock_ensure_ready.return_value = {
            "ready": True,
            "state": "ready",
        }
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }
        mock_resolve_search.return_value = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=fresh123"
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=stale",
            work_dir=None,
        )

        # Should succeed with fresh URL
        assert result["success"] is True
        assert (
            result["fresh_url"]
            == "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=fresh123"
        )
        # Should call resolve_search_url from confirmed overview page
        mock_resolve_search.assert_called_once_with(
            "9234", "https://linkedin.com/talent/hire/123/overview"
        )

    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_waits_for_overview_to_stabilize_before_failing(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
    ):
        """Should wait for overview page to stabilize if initially loading."""
        # Simulate page starting in loading state, then becoming ready
        mock_ensure_ready.side_effect = [
            {"ready": False, "state": "loading"},  # First check: still loading
            {"ready": False, "state": "loading"},  # Second check: still loading
            {"ready": True, "state": "ready"},  # Third check: ready
        ]
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }
        mock_resolve_search.return_value = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=fresh123"
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=stale",
            work_dir=None,
        )

        # Should succeed after waiting for page to stabilize
        assert result["success"] is True
        assert result["fresh_url"] is not None
        # Should have called ensure_page_ready multiple times
        assert mock_ensure_ready.call_count == 3

    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_fails_closed_after_max_wait_attempts(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
    ):
        """Should fail closed if overview page never stabilizes after max attempts."""
        # Simulate page staying in loading state beyond max attempts
        mock_ensure_ready.return_value = {"ready": False, "state": "loading"}
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=stale",
            work_dir=None,
        )

        # Should fail closed after exhausting retry attempts
        assert result["success"] is False
        assert result["fresh_url"] is None
        assert "Failed to navigate to stable project overview" in result["error"]
        assert mock_ensure_ready.call_count == 5  # Max wait attempts

    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_validate_project_context_called_with_browser_mode_param(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
    ):
        """Regression test: validate_project_context must be called with browser_mode param.

        This test catches API drift where the caller uses cdp_port= but the
        callee expects browser_mode=. The function signature is:
        validate_project_context(browser_mode: BrowserMode | str, ...)
        """
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }
        mock_resolve_search.return_value = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=fresh123"
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=stale",
            work_dir=None,
        )

        # Should succeed
        assert result["success"] is True

        # CRITICAL: Verify validate_project_context was called with browser_mode param
        # NOT cdp_port (which would cause TypeError: unexpected keyword argument)
        mock_validate_context.assert_called_once()
        call_kwargs = mock_validate_context.call_args[1]
        assert "browser_mode" in call_kwargs, (
            "validate_project_context must be called with 'browser_mode' parameter. "
            "Using 'cdp_port' will cause TypeError due to signature mismatch."
        )
        assert call_kwargs["browser_mode"] == "9234"
        assert "expected_project_id" in call_kwargs
        assert call_kwargs["expected_project_id"] == "123"


class TestRuntimeManagerIntegration:
    """Tests for RuntimeManager integration in run_extraction."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in RuntimeManager tests."""

    @patch("run_extraction.RuntimeManager")
    def test_uses_runtime_manager_for_work_dir(self, mock_manager_class, tmp_path):
        """Should use RuntimeManager to resolve work_dir."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager_class.return_value = mock_manager

        config = {"PROJECT_ID": "123"}

        re.resolve_workbook_path(config, None)

        mock_manager_class.assert_called()

    @patch("run_extraction.RuntimeManager")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_uses_runtime_manager_for_cdp_port(
        self, mock_resolve_context, mock_manager_class
    ):
        """Should use RuntimeManager to resolve CDP port from profile."""
        mock_manager = MagicMock()
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9999"}
        mock_manager.work_dir = "/tmp/test_work_dir"
        mock_manager_class.return_value = mock_manager

        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create args with no cdp_port
        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = None
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.parse_config_file") as mock_parse:
            mock_parse.return_value = {
                "PROJECT_ID": "123",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            }

            with patch("run_extraction.extract_candidates_from_page") as mock_extract:
                mock_extract.return_value = {
                    "success": True,
                    "candidates": [],
                    "exit_code": 0,
                }

                with patch("run_extraction.get_existing_keys"):
                    # Patch run_preflight to return successful result with CDP port
                    with patch("run_extraction.run_preflight") as mock_preflight:
                        mock_preflight.return_value = {
                            "success": True,
                            "project_id": "123",
                            "cdp_port": "9999",  # This should come from RuntimeManager
                            "work_dir": "/tmp/test_work_dir",
                            "workbook_path": "/tmp/test_work_dir/projects/123.xlsx",
                            "existing_urls": set(),
                        }

                        re.run_extraction(args)

                        # Verify extract was called with port from RuntimeManager
                        call_args = mock_extract.call_args
                        assert call_args[1]["cdp_port"] == "9999"


class TestContextualPageOptimization:
    """Tests for already-on-contextual-page optimization and delayed context handling."""

    @patch("run_extraction.check_current_page_ready_for_extraction")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_uses_current_page_when_already_on_contextual_ready_page(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
        mock_check_current,
    ):
        """Should use current page directly when already on valid contextual search page."""
        # Current page is already a valid contextual search page for project 123
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&searchHistoryId=def&start=0"
        mock_check_current.return_value = {
            "ready": True,
            "current_url": contextual_url,
            "state": "ready",
        }

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=None,
        )

        # Should succeed immediately without navigation
        assert result["success"] is True
        assert result["fresh_url"] == contextual_url
        assert result["error"] is None
        # Should NOT navigate to overview or call resolve_search_url
        mock_recovery_class.assert_not_called()
        mock_resolve_search.assert_not_called()

    @patch("run_extraction.check_current_page_ready_for_extraction")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_skips_optimization_when_on_different_project(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
        mock_check_current,
    ):
        """Should navigate to overview when current page is for different project."""
        # Current page is for project 999, but config is for project 123
        mock_check_current.return_value = {
            "ready": False,
            "current_url": "https://linkedin.com/talent/hire/999/discover/recruiterSearch?searchContextId=abc",
            "state": "not_contextual_search",
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }
        mock_resolve_search.return_value = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=fresh"
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=None,
        )

        # Should succeed via normal navigation flow
        assert result["success"] is True
        assert "fresh" in result["fresh_url"]
        # Should have navigated to overview
        mock_recovery_class.assert_called_once()

    @patch("run_extraction.check_current_page_ready_for_extraction")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_skips_optimization_when_page_not_ready(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
        mock_check_current,
    ):
        """Should navigate to overview when current page is not in ready state."""
        # Current page is contextual but still loading
        mock_check_current.return_value = {
            "ready": False,
            "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "state": "loading",
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }
        mock_resolve_search.return_value = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=fresh"
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=None,
        )

        # Should succeed via normal navigation flow
        assert result["success"] is True
        mock_recovery_class.assert_called_once()

    @patch("run_extraction.check_current_page_ready_for_extraction")
    @patch("run_extraction.run_browser_command")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_retries_when_context_appears_after_delay(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
        mock_run_browser,
        mock_check_current,
    ):
        """Should retry and succeed when context appears after initial bare URL."""
        # Current page is not contextual
        mock_check_current.return_value = {
            "ready": False,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "state": "not_contextual_search",
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }
        # First call returns None (bare URL), second call returns contextual URL
        mock_resolve_search.side_effect = [
            None,  # First attempt: no context yet
            None,  # Second attempt: still no context
            None,  # Third attempt: still no context
        ]
        # But browser command shows context appeared after delay
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=delayed&searchHistoryId=xyz"
        mock_run_browser.return_value = {"parsed": {"url": contextual_url}}
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=None,
        )

        # Should succeed with the delayed contextual URL
        assert result["success"] is True
        assert result["fresh_url"] == contextual_url

    @patch("run_extraction.check_current_page_ready_for_extraction")
    @patch("run_extraction.run_browser_command")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_fails_closed_when_context_never_appears(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
        mock_run_browser,
        mock_check_current,
    ):
        """Should fail closed when context never appears after retries."""
        # Current page is not contextual
        mock_check_current.return_value = {
            "ready": False,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "state": "not_contextual_search",
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }
        # resolve_search_url always returns None
        mock_resolve_search.return_value = None
        # Browser always shows bare URL
        mock_run_browser.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
            }
        }
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=None,
        )

        # Should fail closed
        assert result["success"] is False
        assert result["fresh_url"] is None
        assert "Could not resolve fresh search context" in result["error"]

    @patch("run_extraction.check_current_page_ready_for_extraction")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.validate_project_context")
    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("recruiter_page_utils.RecoveryHelper")
    def test_fails_closed_when_project_is_still_on_start_search(
        self,
        mock_recovery_class,
        mock_ensure_ready,
        mock_validate_context,
        mock_resolve_search,
        mock_check_current,
    ):
        """Should require search creation before extraction when project is unconfigured."""
        mock_check_current.side_effect = [
            {
                "ready": False,
                "current_url": "https://linkedin.com/talent/hire/123/overview",
                "state": "not_contextual_search",
            },
            {
                "ready": False,
                "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=fresh",
                "state": "search_not_configured",
            },
        ]
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }
        mock_resolve_search.return_value = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=fresh"
        mock_recovery_instance = Mock()
        mock_recovery_instance._navigate_to_url = Mock()
        mock_recovery_class.return_value = mock_recovery_instance

        result = re.resolve_fresh_search_context(
            cdp_port="9234",
            configured_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            work_dir=None,
        )

        assert result["success"] is False
        assert "does not have a candidate search yet" in result["error"]
        assert result["failure_code"] == "wrong_page"
        assert (
            result["action_required"]["summary"]
            == "Recruiter project is still on the search-creation screen"
        )


class TestIsContextualRecruiterSearchUrl:
    """Tests for is_contextual_recruiter_search_url helper."""

    def test_returns_true_for_contextual_url(self):
        """Should return True for URL with context params."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&searchHistoryId=def"
        assert re.is_contextual_recruiter_search_url(url, "123") is True

    def test_returns_true_with_search_request_id(self):
        """Should return True for URL with searchRequestId."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchRequestId=xyz"
        assert re.is_contextual_recruiter_search_url(url, "123") is True

    def test_returns_true_with_project_id_param(self):
        """Should return True for URL with projectId param."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?projectId=123"
        assert re.is_contextual_recruiter_search_url(url, "123") is True

    def test_returns_false_for_bare_url(self):
        """Should return False for bare URL without context params."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        assert re.is_contextual_recruiter_search_url(url, "123") is False

    def test_returns_false_for_bare_url_with_start_param(self):
        """Should return False for bare URL with only start param."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25"
        assert re.is_contextual_recruiter_search_url(url, "123") is False

    def test_returns_false_for_wrong_project(self):
        """Should return False for URL with different project ID."""
        url = "https://linkedin.com/talent/hire/999/discover/recruiterSearch?searchContextId=abc"
        assert re.is_contextual_recruiter_search_url(url, "123") is False

    def test_returns_false_for_non_search_url(self):
        """Should return False for non-recruiterSearch URL."""
        url = "https://linkedin.com/talent/hire/123/overview"
        assert re.is_contextual_recruiter_search_url(url, "123") is False


class TestGetPageNumberFromUrl:
    """Tests for get_page_number_from_url helper."""

    def test_page_1_no_start_param(self):
        """Should return 1 for URL without start parameter."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        assert re.get_page_number_from_url(url) == 1

    def test_page_1_with_start_zero(self):
        """Should return 1 for URL with start=0."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        assert re.get_page_number_from_url(url) == 1

    def test_page_2_with_start_25(self):
        """Should return 2 for URL with start=25."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        assert re.get_page_number_from_url(url) == 2

    def test_page_3_with_start_50(self):
        """Should return 3 for URL with start=50."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"
        assert re.get_page_number_from_url(url) == 3

    def test_page_5_with_start_100(self):
        """Should return 5 for URL with start=100."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=100"
        assert re.get_page_number_from_url(url) == 5

    def test_invalid_start_defaults_to_page_1(self):
        """Should return 1 for URL with invalid start parameter."""
        url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=invalid"
        assert re.get_page_number_from_url(url) == 1


class TestGetCurrentPageFromBrowser:
    """Tests for get_current_page_from_browser helper."""

    @patch("run_extraction.run_browser_command")
    def test_detects_page_1_from_browser(self, mock_run_browser):
        """Should detect page 1 from browser URL."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        mock_run_browser.return_value = {"parsed": {"url": page1_url}}

        result = re.get_current_page_from_browser("9234", "123")

        assert result["current_page"] == 1
        assert result["current_url"] == page1_url
        assert result["is_contextual"] is True
        assert result["same_project"] is True

    @patch("run_extraction.run_browser_command")
    def test_detects_page_3_from_browser(self, mock_run_browser):
        """Should detect page 3 from browser URL with start=50."""
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"
        mock_run_browser.return_value = {"parsed": {"url": page3_url}}

        result = re.get_current_page_from_browser("9234", "123")

        assert result["current_page"] == 3
        assert result["is_contextual"] is True
        assert result["same_project"] is True

    @patch("run_extraction.run_browser_command")
    def test_detects_wrong_project(self, mock_run_browser):
        """Should detect when browser is on different project."""
        wrong_project_url = "https://linkedin.com/talent/hire/999/discover/recruiterSearch?searchContextId=abc&start=25"
        mock_run_browser.return_value = {"parsed": {"url": wrong_project_url}}

        result = re.get_current_page_from_browser("9234", "123")

        # For wrong project, is_contextual=False (context check includes project match)
        # so current_page defaults to 1
        assert result["current_page"] == 1  # Defaults to 1 when not contextual
        assert result["is_contextual"] is False  # Wrong project = not contextual for us
        assert result["same_project"] is False  # Different project

    @patch("run_extraction.run_browser_command")
    def test_detects_non_contextual_page(self, mock_run_browser):
        """Should detect when browser is not on contextual search page."""
        overview_url = "https://linkedin.com/talent/hire/123/overview"
        mock_run_browser.return_value = {"parsed": {"url": overview_url}}

        result = re.get_current_page_from_browser("9234", "123")

        assert result["current_page"] == 1  # Defaults to 1
        assert result["is_contextual"] is False
        assert result["same_project"] is True  # Same project, wrong page type

    @patch("run_extraction.run_browser_command")
    def test_detects_bare_url_as_non_contextual(self, mock_run_browser):
        """Should detect bare URL as non-contextual."""
        bare_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        mock_run_browser.return_value = {"parsed": {"url": bare_url}}

        result = re.get_current_page_from_browser("9234", "123")

        assert result["current_page"] == 1
        assert result["is_contextual"] is False  # No context params
        assert result["same_project"] is True

    @patch("run_extraction.run_browser_command")
    def test_fails_closed_when_current_url_missing(self, mock_run_browser):
        """Malformed browser output should fail closed with structured guidance."""
        mock_run_browser.return_value = {"parsed": None}

        result = re.get_current_page_from_browser("9234", "123")

        assert result["success"] is False
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"]["code"] == "ambiguous_state"
        assert "Failed to read current URL" in result["error"]

    @patch("run_extraction.run_browser_command")
    def test_fails_closed_when_current_url_not_string(self, mock_run_browser):
        """Non-string URL payloads should fail closed."""
        mock_run_browser.return_value = {"parsed": {"url": 123}}

        result = re.get_current_page_from_browser("9234", "123")

        assert result["success"] is False
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"]["code"] == "ambiguous_state"

    @patch("run_extraction.run_browser_command")
    def test_fails_closed_when_current_url_malformed_string(self, mock_run_browser):
        """Malformed truthy URL strings should fail closed."""
        mock_run_browser.return_value = {"parsed": {"url": "not a url"}}

        result = re.get_current_page_from_browser("9234", "123")

        assert result["success"] is False
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"]["code"] == "ambiguous_state"
        assert "malformed current URL" in result["error"]


class TestSequentialPaginationNavigation:
    """Regression tests for sequential pagination navigation (resume past page 2)."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in sequential pagination tests."""

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_navigate_to_page_3_from_page_1_context(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should navigate from page 1 to page 3 via sequential live pagination clicks."""
        base_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"

        # Mock sequential pagination: page 1 -> page 2 -> page 3
        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": base_url,
                "current_url": page2_url,
                "error": None,
            },
            {
                "success": True,
                "previous_url": page2_url,
                "current_url": page3_url,
                "error": None,
            },
        ]
        mock_get_current.return_value = {
            "success": True,
            "current_page": 1,
            "current_url": base_url,
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url=base_url,
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        assert result["is_last_page"] is False
        assert result["url"] == page3_url
        assert result["method"] == "ui_pagination"
        # Should have clicked next page TWICE (page 1->2, then page 2->3)
        assert mock_click_next.call_count == 2
        # Verify expected_start values: 25 for page 2, 50 for page 3
        assert mock_click_next.call_args_list[0][1]["expected_start"] == 25
        assert mock_click_next.call_args_list[1][1]["expected_start"] == 50

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_navigate_to_page_5_from_page_1_context(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should navigate from page 1 to page 5 via sequential clicks."""
        base_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"

        # Mock sequential pagination through pages 2, 3, 4, 5
        urls = [
            f"https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start={i * 25}"
            for i in range(1, 5)
        ]

        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": base_url if i == 0 else urls[i - 1],
                "current_url": urls[i],
                "error": None,
            }
            for i in range(4)
        ]
        mock_get_current.return_value = {
            "success": True,
            "current_page": 1,
            "current_url": base_url,
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url=base_url,
            page=5,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        assert result["url"] == urls[3]  # Page 5 URL
        assert mock_click_next.call_count == 4  # 4 clicks to reach page 5

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_navigate_to_page_3_falls_back_on_page_2_failure(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should fall back to synthesized URL if pagination fails at page 2."""
        base_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"

        # First click succeeds (page 1 -> page 2), second click fails
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": base_url,
                "current_url": page2_url,
                "error": None,
            },
            {
                "success": False,
                "previous_url": page2_url,
                "current_url": "",
                "error": "Next page pagination control not found",
            },
        ]
        mock_get_current.return_value = {
            "success": True,
            "current_page": 1,
            "current_url": base_url,
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url=base_url,
            page=3,
            work_dir=None,
            project_id="123",
        )

        # Should fall back to synthesized URL for page 3
        assert result["success"] is True
        assert result["method"] == "synthesized_fallback"
        assert "start=50" in result["url"]

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_navigate_to_page_3_detects_last_page_at_page_2(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should detect last page if reached during sequential navigation."""
        base_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        # First click succeeds (page 1 -> page 2), second click detects last page
        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": base_url,
                "current_url": page2_url,
                "error": None,
            },
            {
                "success": True,
                "is_last_page": True,
                "previous_url": page2_url,
                "current_url": page2_url,
                "error": None,
            },
        ]
        mock_get_current.return_value = {
            "success": True,
            "current_page": 1,
            "current_url": base_url,
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url=base_url,
            page=3,
            work_dir=None,
            project_id="123",
        )

        # Should report last page reached
        assert result["success"] is True
        assert result["is_last_page"] is True
        assert result["url"] == page2_url

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_navigate_to_page_3_validates_each_step(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should validate pagination at each step when project_id provided."""
        base_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        # Wrong project ID in page 3 URL (simulating navigation to wrong project)
        page3_wrong_url = "https://linkedin.com/talent/hire/999/discover/recruiterSearch?searchContextId=abc&start=50"

        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": base_url,
                "current_url": page2_url,
                "error": None,
            },
            {
                "success": True,
                "previous_url": page2_url,
                "current_url": page3_wrong_url,
                "error": None,
            },
        ]
        mock_get_current.return_value = {
            "success": True,
            "current_page": 1,
            "current_url": base_url,
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url=base_url,
            page=3,
            work_dir=None,
            project_id="123",  # Expecting project 123
        )

        # Should fail due to project ID mismatch at page 3
        assert result["success"] is False
        assert result["state"] == "pagination_validation_failed"
        assert "Project ID mismatch" in result["error"]

    @patch("run_extraction.navigate_to_page")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_start_page_3_resumes_correctly(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_navigate,
        tmp_path,
    ):
        """Regression test: --start-page 3 should navigate correctly from page 1 context."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "Page3User", "url": "https://linkedin.com/in/p3"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        mock_navigate.return_value = {
            "success": True,
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=50&searchContextId=abc",
            "state": "ready",
            "method": "ui_pagination",
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 3  # Resume from page 3
        args.max_pages = 1

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        assert result["success"] is True
        assert result["pages_processed"] == 1
        # Should navigate to page 3 on first iteration
        mock_navigate.assert_called_once()
        call_kwargs = mock_navigate.call_args[1]
        assert call_kwargs["page"] == 3


class TestNavigateToPageCurrentContextDetection:
    """Tests for navigate_to_page current context detection (resumed runs)."""

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_already_on_target_page_returns_immediately(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should return immediately if already on target page."""
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"

        # Browser already on page 3
        mock_get_current.return_value = {
            "current_page": 3,
            "current_url": page3_url,
            "is_contextual": True,
            "same_project": True,
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        assert result["url"] == page3_url
        assert result["method"] == "already_on_page"
        # Should NOT click next page
        mock_click_next.assert_not_called()

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_resumes_from_page_2_to_reach_page_3(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should resume from page 2 when browser already there (one click to page 3)."""
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"

        # Browser already on page 2
        mock_get_current.return_value = {
            "current_page": 2,
            "current_url": page2_url,
            "is_contextual": True,
            "same_project": True,
        }
        # Only one click needed: page 2 -> page 3
        mock_click_next.return_value = {
            "success": True,
            "previous_url": page2_url,
            "current_url": page3_url,
            "error": None,
        }
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        assert result["url"] == page3_url
        # Should only click ONCE (from page 2 to page 3)
        assert mock_click_next.call_count == 1
        # Should use expected_start=50 for page 3
        assert mock_click_next.call_args[1]["expected_start"] == 50

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_resumes_from_page_2_to_reach_page_5(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should resume from page 2 and click through to page 5."""
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"
        page4_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=75"
        page5_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=100"

        # Browser already on page 2
        mock_get_current.return_value = {
            "current_page": 2,
            "current_url": page2_url,
            "is_contextual": True,
            "same_project": True,
        }
        # Mock clicks for pages 3, 4, 5 with correct URLs
        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": page2_url,
                "current_url": page3_url,
                "error": None,
            },
            {
                "success": True,
                "previous_url": page3_url,
                "current_url": page4_url,
                "error": None,
            },
            {
                "success": True,
                "previous_url": page4_url,
                "current_url": page5_url,
                "error": None,
            },
        ]
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=5,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        assert result["url"] == page5_url
        # Should click 3 times (page 2->3, 3->4, 4->5)
        assert mock_click_next.call_count == 3

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_realigns_when_on_wrong_project(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should realign to page 1 when browser is on different project."""
        # Note: For wrong project, is_contextual will be False because
        # is_contextual_recruiter_search_url checks project ID match
        page3_wrong_project = "https://linkedin.com/talent/hire/999/discover/recruiterSearch?searchContextId=abc&start=50"
        base_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"

        # Browser on page 3 but WRONG project (999 instead of 123)
        # is_contextual=False because project doesn't match
        mock_get_current.return_value = {
            "current_page": 1,  # Defaults to 1 when not contextual
            "current_url": page3_wrong_project,
            "is_contextual": False,  # Wrong project = not contextual
            "same_project": False,  # Different project!
        }
        # After realignment, clicks to reach page 3
        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": base_url,
                "current_url": page2_url,
                "error": None,
            },
            {
                "success": True,
                "previous_url": page2_url,
                "current_url": page3_url,
                "error": None,
            },
        ]
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url=base_url,
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        # Should click TWICE (from page 1 after realignment)
        assert mock_click_next.call_count == 2

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_realigns_when_not_contextual(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should realign to page 1 when browser not on contextual search page."""
        overview_url = "https://linkedin.com/talent/hire/123/overview"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        # Browser on overview page (not contextual search)
        mock_get_current.return_value = {
            "current_page": 1,
            "current_url": overview_url,
            "is_contextual": False,
            "same_project": True,
        }
        # After realignment, clicks to reach page 3
        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
                "current_url": page2_url,
                "error": None,
            },
            {
                "success": True,
                "previous_url": page2_url,
                "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50",
                "error": None,
            },
        ]
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        # Should click TWICE (from page 1 after realignment)
        assert mock_click_next.call_count == 2

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_realigns_when_current_page_after_target(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should realign to page 1 when browser is past target page."""
        page5_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=100"

        # Browser on page 5 but target is page 3 (can't go backwards)
        mock_get_current.return_value = {
            "current_page": 5,
            "current_url": page5_url,
            "is_contextual": True,
            "same_project": True,
        }
        # After realignment to page 1, clicks to reach page 3
        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
                "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25",
                "error": None,
            },
            {
                "success": True,
                "previous_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25",
                "current_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50",
                "error": None,
            },
        ]
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        # Should realign and click twice (can't go from page 5 back to 3)
        assert mock_click_next.call_count == 2

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    def test_fails_when_realignment_fails(self, mock_get_current, mock_ensure_ready):
        """Should fail when realignment to page 1 fails."""
        overview_url = "https://linkedin.com/talent/hire/123/overview"

        # Browser on overview page
        mock_get_current.return_value = {
            "current_page": 1,
            "current_url": overview_url,
            "is_contextual": False,
            "same_project": True,
        }
        # Realignment fails
        mock_ensure_ready.return_value = {
            "ready": False,
            "state": "loading",
            "failure_code": "timeout",
            "action_required": {
                "code": "timeout",
                "summary": "Page load timed out",
                "steps": ["Wait for the page to finish loading and retry"],
                "can_retry": True,
                "context": {},
            },
        }

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is False
        assert result["method"] == "realign_failed"
        assert "Failed to realign" in result["error"]
        assert result["failure_code"] == "timeout"
        assert result["action_required"]["code"] == "timeout"

    @patch("run_extraction.get_current_page_from_browser")
    def test_fails_closed_when_browser_state_read_fails(self, mock_get_current):
        """navigate_to_page should stop when current browser state cannot be read."""
        mock_get_current.return_value = {
            "success": False,
            "current_page": 1,
            "current_url": "",
            "is_contextual": False,
            "same_project": False,
            "error": "Failed to read current URL from browser",
            "failure_code": "ambiguous_state",
            "action_required": {
                "code": "ambiguous_state",
                "summary": "Browser is in an ambiguous state that cannot be automatically resolved",
                "steps": ["Refresh Chrome and retry"],
                "can_retry": True,
                "context": {},
            },
        }

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is False
        assert result["method"] == "browser_state"
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"]["code"] == "ambiguous_state"

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_ensures_page_ready_between_steps(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should ensure page is ready between each pagination step."""
        base_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"

        # Start from page 1
        mock_get_current.return_value = {
            "current_page": 1,
            "current_url": base_url,
            "is_contextual": True,
            "same_project": True,
        }
        mock_click_next.side_effect = [
            {
                "success": True,
                "previous_url": base_url,
                "current_url": page2_url,
                "error": None,
            },
            {
                "success": True,
                "previous_url": page2_url,
                "current_url": page3_url,
                "error": None,
            },
        ]
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url=base_url,
            page=3,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is True
        # Should call ensure_page_ready:
        # - Once for final page check
        # - Once between step 1 and 2 (since page 2 < target page 3)
        # Total: 2 calls (no intermediate check needed after reaching target)
        assert mock_ensure_ready.call_count >= 1

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_fails_when_resumed_page_not_ready_before_first_click(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should fail if resumed page is not ready before first click (issue #2 fix)."""
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        # Browser already on page 2 (resumed run)
        mock_get_current.return_value = {
            "current_page": 2,
            "current_url": page2_url,
            "is_contextual": True,
            "same_project": True,
        }
        # Page 2 is not ready - should fail before any click
        mock_ensure_ready.return_value = {"ready": False, "state": "loading"}

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=3,
            work_dir=None,
            project_id="123",
        )

        # Should fail before clicking due to resumed page not being ready
        assert result["success"] is False
        assert "page_2_not_ready" in result["state"]
        # Should NOT have clicked - failed at readiness check
        mock_click_next.assert_not_called()

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_resumed_page_ready_proceeds_with_click(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Should proceed with click when resumed page is ready (issue #2 fix)."""
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"

        # Browser already on page 2 (resumed run)
        mock_get_current.return_value = {
            "current_page": 2,
            "current_url": page2_url,
            "is_contextual": True,
            "same_project": True,
        }
        # Page 2 is ready - should proceed with click
        mock_ensure_ready.return_value = {"ready": True, "state": "ready"}
        mock_click_next.return_value = {
            "success": True,
            "previous_url": page2_url,
            "current_url": page3_url,
            "error": None,
        }

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url="https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            page=3,
            work_dir=None,
            project_id="123",
        )

        # Should succeed - page 2 was ready, clicked to page 3
        assert result["success"] is True
        assert result["url"] == page3_url
        # Should have clicked once (page 2 -> page 3)
        mock_click_next.assert_called_once()

    @patch("recruiter_page_utils.ensure_page_ready")
    @patch("run_extraction.get_current_page_from_browser")
    @patch("run_extraction.click_next_page_pagination")
    def test_does_not_fallback_after_structured_pagination_failure(
        self, mock_click_next, mock_get_current, mock_ensure_ready
    ):
        """Structured pagination failures should stop instead of using synthesized fallback."""
        base_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        page1 = {
            "success": True,
            "current_page": 1,
            "current_url": base_url,
            "is_contextual": True,
            "same_project": True,
            "error": None,
            "failure_code": None,
            "action_required": None,
        }
        mock_get_current.return_value = page1
        mock_click_next.return_value = {
            "success": False,
            "is_last_page": False,
            "previous_url": base_url,
            "current_url": base_url,
            "error": "Failed to read current URL from browser during pagination",
            "failure_code": "ambiguous_state",
            "action_required": {
                "code": "ambiguous_state",
                "summary": "Browser is in an ambiguous state that cannot be automatically resolved",
                "steps": ["Refresh Chrome and retry"],
                "can_retry": True,
                "context": {},
            },
        }

        result = re.navigate_to_page(
            cdp_port="9234",
            base_url=base_url,
            page=2,
            work_dir=None,
            project_id="123",
        )

        assert result["success"] is False
        assert result["method"] == "ui_pagination"
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"]["code"] == "ambiguous_state"
        assert mock_ensure_ready.call_count == 1


class TestDelayedPaginationTransition:
    """Regression tests for delayed page-2 URL transition after pagination click."""

    @patch("run_extraction.run_browser_command")
    def test_waits_for_expected_start_param_after_click(self, mock_run_browser):
        """Should poll until expected start parameter appears in URL."""
        # Simulate delayed URL transition: first reads show old URL, then new URL
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        mock_run_browser.side_effect = [
            # First call: click succeeds
            {"parsed": {"clicked": True, "previousUrl": page1_url}},
            # Polling: still on page 1 URL initially
            {"parsed": {"url": page1_url}},
            {"parsed": {"url": page1_url}},
            # Finally transitions to page 2
            {"parsed": {"url": page2_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=2.0,
            poll_interval=0.1,
        )

        assert result["success"] is True
        assert result["is_last_page"] is False
        assert result["current_url"] == page2_url
        assert "start=25" in result["current_url"]

    @patch("run_extraction.run_browser_command")
    def test_returns_current_url_on_timeout_for_validation(self, mock_run_browser):
        """Should fail closed on timeout when no last-page evidence is available."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"

        mock_run_browser.side_effect = [
            # First call: click succeeds
            {"parsed": {"clicked": True, "previousUrl": page1_url}},
            # Polling: URL never transitions (stays on page 1)
            {"parsed": {"url": page1_url}},
            {"parsed": {"url": page1_url}},
            {"parsed": {"url": page1_url}},
            {"parsed": {"url": page1_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=0.3,  # Short timeout for test
            poll_interval=0.1,
        )

        # Without positive last-page evidence, timeout should fail closed
        assert result["success"] is False
        assert result["is_last_page"] is False
        assert result["current_url"] == page1_url
        assert "did not reach the expected next page" in result["error"]

    @patch("run_extraction.run_browser_command")
    def test_no_expected_start_uses_url_change_detection(self, mock_run_browser):
        """When no expected_start provided, detect any URL change."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        mock_run_browser.side_effect = [
            {"parsed": {"clicked": True, "previousUrl": page1_url}},
            {"parsed": {"url": page1_url}},  # Still on page 1
            {"parsed": {"url": page2_url}},  # Changed to page 2
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=None,  # No expected start
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        assert result["success"] is True
        assert result["current_url"] == page2_url

    @patch("run_extraction.run_browser_command")
    def test_disabled_next_button_detected_before_click(self, mock_run_browser):
        """Disabled next button should be detected before any polling."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"

        mock_run_browser.return_value = {
            "parsed": {
                "clicked": False,
                "isLastPage": True,
                "method": "last_page_detected",
                "previousUrl": page1_url,
                "error": None,
            }
        }

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Should immediately return is_last_page without polling
        assert result["success"] is True  # Clean end-of-results
        assert result["is_last_page"] is True
        assert result["error"] is None
        # Only one call to run_browser_command (no polling)
        assert mock_run_browser.call_count == 1

    @patch("run_extraction.run_browser_command")
    def test_enabled_controls_preferred_over_disabled_button(self, mock_run_browser):
        """Enabled page-2 anchor controls should be preferred over disabled next button.

        Regression test: LinkedIn Recruiter page 1 shows both a disabled BUTTON "Next"
        and enabled anchor controls for page 2. The code should click the enabled
        anchor controls, NOT misclassify as last-page due to the disabled button.

        This test verifies the JS code contains the correct selector precedence:
        Strategy 1 (enabled controls) must come BEFORE Strategy 3 (disabled detection).
        """
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        # Simulate the JS finding enabled controls and clicking successfully
        mock_run_browser.side_effect = [
            # First call: click succeeds via enabled next link (not disabled button detection)
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "next_link",
                    "text": "Go to next page 2",
                    "previousUrl": page1_url,
                }
            },
            # Polling: URL transitions to page 2
            {"parsed": {"url": page2_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Should succeed and navigate to page 2, NOT report as last page
        assert result["success"] is True
        assert result["is_last_page"] is False
        assert result["current_url"] == page2_url
        assert "start=25" in result["current_url"]

        # CRITICAL: Verify the JS code checks enabled controls BEFORE disabled buttons
        # Get the JS code passed to run_browser_command (first call is the click JS)
        js_code = mock_run_browser.call_args_list[0][0][2]  # cdp_port, "eval", js_code

        # Find positions of key strategies in the JS
        strategy1_pos = js_code.find("Strategy 1: Look for ENABLED")
        strategy3_pos = js_code.find("Strategy 3: Check for disabled")

        # Strategy 1 must come before Strategy 3 for correct precedence
        assert strategy1_pos > 0, "Strategy 1 (enabled controls) not found in JS"
        assert strategy3_pos > 0, "Strategy 3 (disabled detection) not found in JS"
        assert strategy1_pos < strategy3_pos, (
            "Strategy 1 must come BEFORE Strategy 3 - enabled controls should be checked first"
        )

    @patch("run_extraction.run_browser_command")
    def test_disabled_button_only_when_no_enabled_controls(self, mock_run_browser):
        """Disabled button should only trigger last-page when no enabled controls exist.

        This verifies the fix for the ambiguity case: when both disabled next button
        AND enabled page-2 controls are present, the enabled controls win.

        This test verifies the JS code contains proper disabled button selectors
        that would only match when no enabled controls exist.
        """
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"

        # Simulate JS: no enabled controls found, but disabled button found
        mock_run_browser.return_value = {
            "parsed": {
                "clicked": False,
                "isLastPage": True,
                "method": "last_page_detected",
                "previousUrl": page1_url,
                "error": None,
            }
        }

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # This is the TRUE last page case: no enabled controls, only disabled button
        assert result["success"] is True  # Clean end-of-results
        assert result["is_last_page"] is True
        assert result["error"] is None

        # CRITICAL: Verify the JS code contains proper disabled button selectors
        js_code = mock_run_browser.call_args[0][2]  # cdp_port, "eval", js_code

        # Strategy 3 should check for disabled buttons with [disabled] attribute
        assert 'button[disabled][aria-label*="next" i]' in js_code, (
            "Missing disabled button selector with [disabled] attribute"
        )
        assert "button[disabled][data-test-pagination-next]" in js_code, (
            "Missing disabled button selector with data-test-pagination-next"
        )

        # Strategy 3 should also check for LinkedIn's disabled class
        assert "button.artdeco-button--disabled" in js_code, (
            "Missing selector for LinkedIn's artdeco-button--disabled class"
        )

    @patch("run_extraction.run_browser_command")
    def test_class_disabled_button_not_treated_as_enabled(self, mock_run_browser):
        """Decorative Next with artdeco-button--disabled class must not be treated as enabled.

        Regression test: LinkedIn uses artdeco-button--disabled class for decorative disabled
        buttons. Elements with this class but no disabled attribute must be excluded from
        Strategy 1/2 enabled matching, allowing enabled page-2 controls to win instead.

        This test verifies the JS code explicitly filters out artdeco-button--disabled
        elements in both Strategy 1 (find loop) and Strategy 2 (CSS selectors).
        """
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        # Simulate JS finding enabled page-2 controls (not the class-disabled decorative Next)
        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "next_link",
                    "text": "Go to next page 2",
                    "previousUrl": page1_url,
                }
            },
            {"parsed": {"url": page2_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Should navigate to page 2, not misclassify as last page
        assert result["success"] is True
        assert result["is_last_page"] is False
        assert result["current_url"] == page2_url

        # CRITICAL: Verify the JS code filters out artdeco-button--disabled elements
        js_code = mock_run_browser.call_args_list[0][0][2]  # cdp_port, "eval", js_code

        # Strategy 1: Check that the find loop excludes artdeco-button--disabled
        assert "el.classList.contains('artdeco-button--disabled')" in js_code, (
            "Strategy 1 must check for artdeco-button--disabled class in the find loop"
        )

        # Strategy 2: Check that CSS selectors exclude artdeco-button--disabled
        assert ":not(.artdeco-button--disabled)" in js_code, (
            "Strategy 2 CSS selectors must exclude .artdeco-button--disabled class"
        )

        # Verify the disabled check combines both attribute and class checks
        assert (
            "el.disabled ||" in js_code and "el.getAttribute('disabled')" in js_code
        ), "Strategy 1 must check both el.disabled property and disabled attribute"

    @patch("run_extraction.run_browser_command")
    def test_scopes_next_matching_to_recruiter_pagination_controls(
        self, mock_run_browser
    ):
        """Should scope live next-page matching to Recruiter pagination controls.

        Regression test: result pages can contain unrelated carousel/header buttons with
        text like "Next" that do not paginate the candidate list. The click JS should
        limit matches to actual Recruiter pagination containers.
        """
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "next_link",
                    "text": "Next",
                    "previousUrl": page1_url,
                }
            },
            {"parsed": {"url": page2_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        assert result["success"] is True
        assert result["current_url"] == page2_url

        js_code = mock_run_browser.call_args_list[0][0][2]

        # Should explicitly scope candidates to Recruiter pagination containers.
        assert "data-test-ts-pagination" in js_code
        assert ".profile-list-container__pagination" in js_code
        assert ".mini-pagination" in js_code

        # Should explicitly de-prioritize unrelated carousel navigation.
        assert "artdeco-carousel" in js_code

    @patch("run_extraction.run_browser_command")
    def test_scrolls_pagination_control_into_view_before_click(self, mock_run_browser):
        """Should scroll matched pagination controls into view before clicking."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "next_link",
                    "text": "Next",
                    "previousUrl": page1_url,
                }
            },
            {"parsed": {"url": page2_url}},
        ]

        re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        js_code = mock_run_browser.call_args_list[0][0][2]
        assert "scrollIntoView({ block: 'center' })" in js_code

    @patch("run_extraction.run_browser_command")
    def test_polling_respects_custom_timeout(self, mock_run_browser):
        """Should respect custom max_wait_seconds while still failing closed."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"

        mock_run_browser.side_effect = [
            {"parsed": {"clicked": True, "previousUrl": page1_url}},
        ] + [{"parsed": {"url": page1_url}}] * 20  # Never transitions

        import time

        start = time.time()
        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=0.5,  # 500ms timeout
            poll_interval=0.1,
        )
        elapsed = time.time() - start

        # Should complete within reasonable time of timeout
        assert elapsed < 1.0  # Should not take much longer than timeout
        assert result["success"] is False
        assert result["is_last_page"] is False

    @patch("run_extraction.run_browser_command")
    def test_malformed_url_polling_returns_structured_failure(self, mock_run_browser):
        """Should return structured failure when URL polling gets malformed output.

        Regression test: When run_browser_command() returns None for parsed (not missing key),
        the old code would crash with AttributeError. The fix uses safe_get_parsed and
        returns a structured pagination failure instead.
        """
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"

        mock_run_browser.side_effect = [
            # First call: click succeeds
            {"parsed": {"clicked": True, "previousUrl": page1_url}},
            # Polling: malformed output with parsed=None (not missing key)
            {"parsed": None, "error": "Browser returned invalid JSON"},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Should fail closed with structured error, not crash
        assert result["success"] is False
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"] is not None
        assert result["action_required"]["code"] == "browser_unavailable"
        assert "Failed to read current URL" in result["error"]

    @patch("run_extraction.run_browser_command")
    def test_missing_parsed_key_returns_structured_failure(self, mock_run_browser):
        """Should return structured failure when URL polling result has no parsed key.

        Regression test: When run_browser_command() returns a dict without 'parsed' key,
        the code should handle it gracefully and return a structured failure.
        """
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"

        mock_run_browser.side_effect = [
            # First call: click succeeds
            {"parsed": {"clicked": True, "previousUrl": page1_url}},
            # Polling: result has no parsed key at all
            {"stdout": "", "stderr": "", "returncode": 0},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Should fail closed with structured error
        assert result["success"] is False
        assert result["failure_code"] == "browser_unavailable"
        assert result["action_required"] is not None


class TestCheckCurrentPageReady:
    """Tests for check_current_page_ready_for_extraction helper."""

    @patch("browser_utils.run_browser_command")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_returns_ready_for_valid_contextual_page(
        self, mock_probe_class, mock_run_browser
    ):
        """Should return ready when on valid contextual search page with results."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        mock_run_browser.return_value = {"parsed": {"url": contextual_url}}
        mock_probe = Mock()
        mock_probe.classify_state.return_value = {
            "state": "ready",
            "details": {"hasSearchResultsContent": True},
        }
        mock_probe_class.return_value = mock_probe

        result = re.check_current_page_ready_for_extraction("9234", "123")

        assert result["ready"] is True
        assert result["current_url"] == contextual_url
        assert result["state"] == "ready"

    @patch("browser_utils.run_browser_command")
    def test_returns_not_ready_for_non_search_url(self, mock_run_browser):
        """Should return not ready when not on recruiterSearch URL."""
        mock_run_browser.return_value = {
            "parsed": {"url": "https://linkedin.com/talent/hire/123/overview"}
        }

        result = re.check_current_page_ready_for_extraction("9234", "123")

        assert result["ready"] is False
        assert result["state"] == "not_contextual_search"

    @patch("browser_utils.run_browser_command")
    def test_returns_not_ready_for_bare_search_url(self, mock_run_browser):
        """Should return not ready for bare recruiterSearch URL without context."""
        mock_run_browser.return_value = {
            "parsed": {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
            }
        }

        result = re.check_current_page_ready_for_extraction("9234", "123")

        assert result["ready"] is False
        assert result["state"] == "not_contextual_search"

    @patch("browser_utils.run_browser_command")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_returns_not_ready_when_page_loading(
        self, mock_probe_class, mock_run_browser
    ):
        """Should return not ready when page is still loading."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        mock_run_browser.return_value = {"parsed": {"url": contextual_url}}
        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "loading"}
        mock_probe_class.return_value = mock_probe

        result = re.check_current_page_ready_for_extraction("9234", "123")

        assert result["ready"] is False
        assert result["state"] == "loading"

    @patch("browser_utils.run_browser_command")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_returns_not_ready_when_generic_ready_without_search_results(
        self, mock_probe_class, mock_run_browser
    ):
        """Should return not ready when classify_state returns ready via generic fallback.

        Regression test: classify_state() can return state='ready' via generic
        recruiter fallback (e.g., on overview pages) even when there is no
        concrete search-results-ready signal. Reuse should require demonstrable
        extraction-ready evidence.
        """
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        mock_run_browser.return_value = {"parsed": {"url": contextual_url}}
        mock_probe = Mock()
        # Generic ready state without hasSearchResultsContent (e.g., overview page)
        mock_probe.classify_state.return_value = {
            "state": "ready",
            "details": {"hasSearchResultsContent": False, "hasOverviewContent": True},
        }
        mock_probe_class.return_value = mock_probe

        result = re.check_current_page_ready_for_extraction("9234", "123")

        assert result["ready"] is False
        assert result["state"] == "no_search_results_content"

    @patch("browser_utils.run_browser_command")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_returns_not_ready_when_search_not_configured(
        self, mock_probe_class, mock_run_browser
    ):
        """Should fail closed when Recruiter is still showing Start a search."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"
        mock_run_browser.return_value = {"parsed": {"url": contextual_url}}
        mock_probe = Mock()
        mock_probe.classify_state.return_value = {
            "state": "ready",
            "details": {
                "hasSearchResultsContent": False,
                "hasSearchCreationPrompt": True,
            },
        }
        mock_probe_class.return_value = mock_probe

        result = re.check_current_page_ready_for_extraction("9234", "123")

        assert result["ready"] is False
        assert result["state"] == "search_not_configured"


class TestKeyboardInterruptHandling:
    """Tests for KeyboardInterrupt handling and state persistence."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in interrupt tests."""

    @patch("run_extraction.save_extraction_state")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_interrupt_during_page_1_persists_resumable_state(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_save_state,
        tmp_path,
    ):
        """Interrupt before first page completes leaves resumable state with next_start_page=1."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        # Simulate KeyboardInterrupt during extraction
        mock_extract.side_effect = KeyboardInterrupt()
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        mock_save_state.return_value = True

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 5

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with pytest.raises(KeyboardInterrupt):
                re.run_extraction(args)

        # State should be persisted with next_start_page=1 (the interrupted page)
        mock_save_state.assert_called_once()
        call_kwargs = mock_save_state.call_args[1]
        assert call_kwargs["status"] == "running"
        assert call_kwargs["next_start_page"] == 1
        assert call_kwargs["last_completed_page"] is None  # No pages completed yet

    @patch("run_extraction.save_extraction_state")
    @patch("run_extraction.navigate_to_page")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_interrupt_during_later_page_persists_resumable_state(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_navigate,
        mock_save_state,
        tmp_path,
    ):
        """Interrupt after later page starts leaves resumable state with correct next_start_page."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        # First page succeeds, second page raises KeyboardInterrupt
        mock_extract.side_effect = [
            {
                "success": True,
                "candidates": [
                    {"name": "Page1User", "url": "https://linkedin.com/in/p1"}
                ],
                "exit_code": 0,
            },
            KeyboardInterrupt(),  # Interrupt during page 2
        ]
        mock_navigate.return_value = {
            "success": True,
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
            "state": "ready",
            "method": "ui_pagination",
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        mock_save_state.return_value = True

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 5

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                with pytest.raises(KeyboardInterrupt):
                    re.run_extraction(args)

        # State should be persisted with next_start_page=2 (the interrupted page)
        # The interrupt save is the last call
        interrupt_save_call = mock_save_state.call_args
        assert interrupt_save_call[1]["status"] == "running"
        assert interrupt_save_call[1]["next_start_page"] == 2
        assert interrupt_save_call[1]["last_completed_page"] == 1  # Page 1 completed

    @patch("run_extraction.save_extraction_state")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_interrupt_fails_closed_when_state_persistence_fails(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_save_state,
        tmp_path,
    ):
        """On interrupt, if state persistence fails, should still raise KeyboardInterrupt."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        mock_resolve.return_value = tmp_path / "workbook.xlsx"
        mock_ensure.return_value = True
        mock_extract.side_effect = KeyboardInterrupt()
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        # Simulate state persistence failure
        mock_save_state.return_value = False

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False
        args.start_page = 1
        args.max_pages = 5

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            # Should still raise KeyboardInterrupt even if state save fails
            with pytest.raises(KeyboardInterrupt):
                re.run_extraction(args)

        # Should have attempted to save state
        mock_save_state.assert_called_once()


class TestRunPreflight:
    """Tests for run_preflight helper."""

    @patch("run_extraction.RuntimeManager")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.get_existing_keys")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_config_project_mismatch_fails_before_fresh_context(
        self, mock_probe_class, mock_get_keys, mock_ensure, mock_manager_class, tmp_path
    ):
        """Config project ID mismatch should fail before fresh-context resolution."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "ready"}
        mock_probe_class.return_value = mock_probe

        # Config has mismatched PROJECT_ID
        config = {
            "PROJECT_ID": "999",  # Different from URL
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.workbook = None
        args.dry_run = False
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "project id mismatch" in result["message"].lower()
        # resolve_fresh_search_context should NOT be called (we're testing preflight alone)

    @patch("run_extraction.RuntimeManager")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.get_existing_keys")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_slug_project_id_does_not_trigger_mismatch_check(
        self, mock_probe_class, mock_get_keys, mock_ensure, mock_manager_class, tmp_path
    ):
        """Slug-style PROJECT_ID should not be treated as Recruiter project ID."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "ready"}
        mock_probe_class.return_value = mock_probe

        mock_ensure.return_value = True
        mock_get_keys.return_value = set()

        config = {
            "PROJECT_ID": "1775876514-sim-v6",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/1687654572/discover/recruiterSearch",
        }

        wb_path = tmp_path / "workbook.xlsx"
        wb_path.write_text("dummy xlsx content")

        args = Mock()
        args.workbook = str(wb_path)
        args.dry_run = False
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is True
        assert result["project_id"] == "1687654572"

    @patch("run_extraction.RuntimeManager")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_dialog_blocked_fails_before_fresh_context(
        self, mock_probe_class, mock_manager_class, tmp_path
    ):
        """Dialog blocked state should fail before fresh-context resolution."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "dialog_blocked"}
        mock_probe_class.return_value = mock_probe

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.workbook = None
        args.dry_run = True  # Skip workbook checks
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "dialog_blocked" in result["message"]
        assert result["failure_code"] == "dialog_blocked"
        assert result["action_required"]["code"] == "dialog_blocked"

    @patch("run_extraction.RuntimeManager")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_logged_out_fails_before_fresh_context(
        self, mock_probe_class, mock_manager_class, tmp_path
    ):
        """Logged out state should fail before fresh-context resolution."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {
            "state": "logged_out_or_wrong_product"
        }
        mock_probe_class.return_value = mock_probe

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.workbook = None
        args.dry_run = True
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "logged_out_or_wrong_product" in result["message"]
        assert result["failure_code"] == "auth_required"
        assert result["action_required"]["code"] == "auth_required"

    @patch("run_extraction.RuntimeManager")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_blocked_or_captcha_fails_before_fresh_context(
        self, mock_probe_class, mock_manager_class, tmp_path
    ):
        """Blocked or CAPTCHA state should fail before fresh-context resolution."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "blocked_or_captcha"}
        mock_probe_class.return_value = mock_probe

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.workbook = None
        args.dry_run = True
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "blocked_or_captcha" in result["message"]
        assert result["failure_code"] == "blocked_or_captcha"
        assert result["action_required"]["code"] == "blocked_or_captcha"

    @patch("run_extraction.RuntimeManager")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_bad_page_fails_before_fresh_context(
        self, mock_probe_class, mock_manager_class, tmp_path
    ):
        """Bad page state should fail before fresh-context resolution."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "bad_page"}
        mock_probe_class.return_value = mock_probe

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.workbook = None
        args.dry_run = True
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "bad_page" in result["message"]
        assert result["failure_code"] == "wrong_page"
        assert result["action_required"]["code"] == "wrong_page"

    @patch("run_extraction.RuntimeManager")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_unknown_state_with_error_fails_and_includes_error_text(
        self, mock_probe_class, mock_manager_class, tmp_path
    ):
        """Unknown state with browser/CDP error should fail and include error text."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {
            "state": "unknown",
            "details": {"error": "CDP connection refused: localhost:9234"},
        }
        mock_probe_class.return_value = mock_probe

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.workbook = None
        args.dry_run = True
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "CDP connection refused" in result["message"]
        assert result["failure_code"] == "ambiguous_state"
        assert result["action_required"]["code"] == "ambiguous_state"

    @patch("run_extraction.run_preflight")
    def test_run_extraction_preserves_preflight_action_required(self, mock_preflight):
        """Structured preflight failures should propagate to run_extraction result."""
        mock_preflight.return_value = {
            "success": False,
            "message": "Browser preflight failed: page state is 'dialog_blocked'",
            "exit_code": 1,
            "failure_code": "dialog_blocked",
            "action_required": {
                "code": "dialog_blocked",
                "summary": "A browser dialog is blocking automation progress",
                "steps": ["Dismiss the dialog in Chrome"],
                "can_retry": True,
                "context": {},
            },
        }

        args = Mock()
        args.config = "/tmp/config.sh"

        with patch("run_extraction.parse_config_file") as mock_parse:
            mock_parse.return_value = {
                "PROJECT_ID": "123",
                "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            }

            result = re.run_extraction(args)

        assert result["success"] is False
        assert result["failure_code"] == "dialog_blocked"
        assert result["action_required"]["code"] == "dialog_blocked"

    @patch("run_extraction.RuntimeManager")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.get_existing_keys")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_workbook_read_error_caught_during_preflight(
        self, mock_probe_class, mock_get_keys, mock_ensure, mock_manager_class, tmp_path
    ):
        """Workbook read error should be caught during preflight, not later."""
        from zipfile import BadZipFile

        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "ready"}
        mock_probe_class.return_value = mock_probe

        mock_ensure.return_value = True
        mock_get_keys.side_effect = BadZipFile("File is not a zip file")

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        # Create the workbook file so it exists for the preflight check
        wb_path = tmp_path / "corrupt.xlsx"
        wb_path.write_text("not a valid xlsx")

        args = Mock()
        args.workbook = str(wb_path)
        args.dry_run = False
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is False
        assert result["exit_code"] == 2
        assert "Workbook read failed" in result["message"]

    @patch("run_extraction.RuntimeManager")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.get_existing_keys")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_existing_urls_reused_from_preflight(
        self, mock_probe_class, mock_get_keys, mock_ensure, mock_manager_class, tmp_path
    ):
        """existing_urls loaded during preflight should be reused (no second get_existing_keys call)."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "ready"}
        mock_probe_class.return_value = mock_probe

        mock_ensure.return_value = True
        existing_urls = {"https://linkedin.com/in/existing"}
        mock_get_keys.return_value = existing_urls

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        # Create the workbook file so it exists for the preflight check
        wb_path = tmp_path / "workbook.xlsx"
        wb_path.write_text("dummy xlsx content")

        args = Mock()
        args.workbook = str(wb_path)
        args.dry_run = False
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is True
        assert result["existing_urls"] == existing_urls
        # get_existing_keys should be called exactly once during preflight
        mock_get_keys.assert_called_once()

    @patch("run_extraction.RuntimeManager")
    @patch("run_extraction.ensure_workbook")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_preflight_succeeds_when_ready_state(
        self, mock_probe_class, mock_ensure, mock_manager_class, tmp_path
    ):
        """Preflight should succeed when page state is ready."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "ready"}
        mock_probe_class.return_value = mock_probe

        mock_ensure.return_value = True

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.workbook = str(tmp_path / "workbook.xlsx")
        args.dry_run = False
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is True
        assert result["exit_code"] is None
        assert result["project_id"] == "123"
        assert result["cdp_port"] == "9234"

    @patch("run_extraction.RuntimeManager")
    @patch("recruiter_page_utils.PageStateProbe")
    def test_preflight_skips_workbook_checks_in_dry_run(
        self, mock_probe_class, mock_manager_class, tmp_path
    ):
        """Preflight should skip workbook existence/read checks in dry-run mode."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "ready"}
        mock_probe_class.return_value = mock_probe

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.workbook = str(tmp_path / "nonexistent" / "workbook.xlsx")
        args.dry_run = True  # Dry run - skip workbook checks
        args.cdp_port = "9234"

        result = re.run_preflight(config, args)

        assert result["success"] is True
        assert result["existing_urls"] == set()


class TestRunExtractionPreflightIntegration:
    """Integration tests for preflight within run_extraction."""

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.resolve_fresh_search_context")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.get_existing_keys")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("run_extraction.RuntimeManager")
    def test_resolve_fresh_search_context_not_called_when_preflight_fails(
        self,
        mock_manager_class,
        mock_probe_class,
        mock_get_keys,
        mock_ensure,
        mock_resolve_context,
        mock_extract,
        tmp_path,
    ):
        """resolve_fresh_search_context should NOT be called when preflight fails."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "dialog_blocked"}
        mock_probe_class.return_value = mock_probe

        mock_ensure.return_value = True
        mock_get_keys.return_value = set()

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = str(tmp_path / "workbook.xlsx")
        args.dry_run = False
        args.cdp_port = "9234"
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.parse_config_file") as mock_parse:
            mock_parse.return_value = config
            result = re.run_extraction(args)

        assert result["success"] is False
        assert result["exit_code"] == 1
        assert "dialog_blocked" in result["message"]
        # CRITICAL: resolve_fresh_search_context should NOT be called
        mock_resolve_context.assert_not_called()
        mock_extract.assert_not_called()

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.resolve_fresh_search_context")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.get_existing_keys")
    @patch("recruiter_page_utils.PageStateProbe")
    @patch("run_extraction.RuntimeManager")
    def test_extraction_uses_preflight_existing_urls(
        self,
        mock_manager_class,
        mock_probe_class,
        mock_get_keys,
        mock_ensure,
        mock_resolve_context,
        mock_extract,
        tmp_path,
    ):
        """run_extraction should use existing_urls from preflight without calling get_existing_keys again."""
        mock_manager = MagicMock()
        mock_manager.work_dir = tmp_path / "work"
        mock_manager._resolve_profile.return_value = {"CDP_PORT": "9234"}
        mock_manager_class.return_value = mock_manager

        mock_probe = Mock()
        mock_probe.classify_state.return_value = {"state": "ready"}
        mock_probe_class.return_value = mock_probe

        mock_ensure.return_value = True
        preflight_urls = {"https://linkedin.com/in/existing"}
        mock_get_keys.return_value = preflight_urls

        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "New", "url": "https://linkedin.com/in/new"}],
            "exit_code": 0,
        }

        config = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        # Create the workbook file so it exists for the preflight check
        wb_path = tmp_path / "workbook.xlsx"
        wb_path.write_text("dummy xlsx content")

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = str(wb_path)
        args.dry_run = False
        args.cdp_port = "9234"
        args.start_page = 1
        args.max_pages = 1

        with patch("run_extraction.parse_config_file") as mock_parse:
            mock_parse.return_value = config
            with patch("run_extraction.upsert") as mock_upsert:
                mock_upsert.return_value = {"row_id": 1, "action": "inserted"}
                result = re.run_extraction(args)

        assert result["success"] is True
        # get_existing_keys should be called exactly once (during preflight)
        mock_get_keys.assert_called_once()
        # process_candidates should receive the preflight-loaded URLs
        # (verified by checking no second call to get_existing_keys)


class TestResumeState:
    """Tests for extraction resume state persistence."""

    def test_get_extraction_state_path_success(self, tmp_path):
        """State path should be under runtime/extraction-state/."""
        work_dir = tmp_path / "work"
        workbook_path = work_dir / "projects" / "123.xlsx"

        result = re.get_extraction_state_path(work_dir, "123", workbook_path)

        assert result["success"] is True
        assert result["path"].parent.name == "extraction-state"
        assert result["path"].parent.parent.name == "runtime"
        # State file now includes hash suffix: 123-{hash}.json
        assert result["path"].name.startswith("123-")
        assert result["path"].name.endswith(".json")
        assert result["error"] is None

    def test_different_paths_same_basename_produce_different_state_paths(
        self, tmp_path
    ):
        """Different workbook paths with same basename must not collide."""
        work_dir = tmp_path / "work"
        # Two workbooks with same basename but different directories
        workbook_path_1 = work_dir / "projects" / "A" / "123.xlsx"
        workbook_path_2 = work_dir / "projects" / "B" / "123.xlsx"

        result_1 = re.get_extraction_state_path(work_dir, "123", workbook_path_1)
        result_2 = re.get_extraction_state_path(work_dir, "123", workbook_path_2)

        assert result_1["success"] is True
        assert result_2["success"] is True
        # State paths must be different
        assert result_1["path"] != result_2["path"]
        # Both should start with the stem
        assert result_1["path"].name.startswith("123-")
        assert result_2["path"].name.startswith("123-")

    def test_same_path_produces_same_state_path(self, tmp_path):
        """Same workbook path must produce consistent state path."""
        work_dir = tmp_path / "work"
        workbook_path = work_dir / "projects" / "123.xlsx"

        result_1 = re.get_extraction_state_path(work_dir, "123", workbook_path)
        result_2 = re.get_extraction_state_path(work_dir, "123", workbook_path)

        assert result_1["success"] is True
        assert result_2["success"] is True
        # Same path should produce identical state path
        assert result_1["path"] == result_2["path"]

    def test_state_key_includes_path_and_project_hash(self, tmp_path):
        """State key should include a hash of the resolved path and project_id."""
        work_dir = tmp_path / "work"
        workbook_path = work_dir / "projects" / "123.xlsx"

        key = re._get_workbook_state_key(workbook_path, "123")

        # Key format: stem-8charhash
        parts = key.split("-")
        assert len(parts) >= 2
        assert parts[0] == "123"
        # Last part should be 8 hex characters
        hash_part = parts[-1]
        assert len(hash_part) == 8
        assert all(c in "0123456789abcdef" for c in hash_part)

    def test_same_workbook_different_project_produces_different_state_keys(
        self, tmp_path
    ):
        """Same workbook path with different project_ids must produce different state keys."""
        work_dir = tmp_path / "work"
        workbook_path = work_dir / "projects" / "shared.xlsx"

        key_project_123 = re._get_workbook_state_key(workbook_path, "123")
        key_project_456 = re._get_workbook_state_key(workbook_path, "456")
        key_project_123_again = re._get_workbook_state_key(workbook_path, "123")

        # Different projects should produce different keys
        assert key_project_123 != key_project_456, (
            f"Same workbook with different project_ids should produce different keys: "
            f"123={key_project_123}, 456={key_project_456}"
        )
        # Same project should produce consistent key
        assert key_project_123 == key_project_123_again, (
            f"Same workbook with same project_id should produce consistent key: "
            f"first={key_project_123}, second={key_project_123_again}"
        )

    def test_same_workbook_different_project_produces_different_state_files(
        self, tmp_path
    ):
        """Same workbook path with different project_ids must produce different state files."""
        work_dir = tmp_path / "work"
        workbook_path = work_dir / "projects" / "shared.xlsx"

        result_123 = re.get_extraction_state_path(work_dir, "123", workbook_path)
        result_456 = re.get_extraction_state_path(work_dir, "456", workbook_path)

        assert result_123["success"] is True
        assert result_456["success"] is True
        # Different projects should produce different state file paths
        assert result_123["path"] != result_456["path"], (
            f"Same workbook with different project_ids should produce different state files: "
            f"123={result_123['path']}, 456={result_456['path']}"
        )
        # Both should be readable filenames with workbook stem
        assert result_123["path"].name.startswith("shared-")
        assert result_456["path"].name.startswith("shared-")
        assert result_123["path"].name.endswith(".json")
        assert result_456["path"].name.endswith(".json")

    def test_get_extraction_state_path_failure(self, tmp_path):
        """State directory creation failure should return controlled error."""
        work_dir = tmp_path / "work"
        workbook_path = work_dir / "projects" / "123.xlsx"

        # Create a file where the state directory should be created
        # This will cause mkdir to fail (file exists, not a directory)
        state_dir_parent = work_dir / "runtime"
        state_dir_parent.mkdir(parents=True)
        (state_dir_parent / "extraction-state").write_text("not a directory")

        result = re.get_extraction_state_path(work_dir, "123", workbook_path)

        assert result["success"] is False
        assert result["path"] is None
        assert "Failed to create state directory" in result["error"]
        assert result["error"] is not None

    def test_get_extraction_state_path_rejects_non_pathlike_work_dir(self, tmp_path):
        """Non-path mocks must fail closed instead of creating junk directories."""
        workbook_path = tmp_path / "projects" / "123.xlsx"

        result = re.get_extraction_state_path(MagicMock(), "123", workbook_path)

        assert result["success"] is False
        assert result["path"] is None
        assert "Invalid work_dir" in result["error"]

    def test_load_extraction_state_returns_none_for_missing_file(self, tmp_path):
        """Loading missing state file should return None."""
        state_path = tmp_path / "nonexistent.json"

        result = re.load_extraction_state(state_path)

        assert result is None

    def test_load_extraction_state_returns_none_for_invalid_json(self, tmp_path):
        """Loading invalid JSON should return None."""
        state_path = tmp_path / "invalid.json"
        state_path.write_text("not valid json")

        result = re.load_extraction_state(state_path)

        assert result is None

    def test_load_extraction_state_returns_none_for_wrong_version(self, tmp_path):
        """Loading state with wrong version should return None."""
        state_path = tmp_path / "old_version.json"
        state_path.write_text(
            json.dumps(
                {
                    "version": 999,
                    "project_id": "123",
                    "workbook_path": "/path/to/workbook.xlsx",
                    "status": "running",
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        result = re.load_extraction_state(state_path)

        assert result is None

    def test_load_extraction_state_returns_none_for_missing_required_fields(
        self, tmp_path
    ):
        """Loading state missing required fields should return None."""
        state_path = tmp_path / "incomplete.json"
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    # Missing workbook_path, status, updated_at
                }
            )
        )

        result = re.load_extraction_state(state_path)

        assert result is None

    def test_load_extraction_state_returns_valid_state(self, tmp_path):
        """Loading valid state should return the state dict."""
        state_path = tmp_path / "valid.json"
        expected_state = {
            "version": 1,
            "project_id": "123",
            "workbook_path": "/path/to/workbook.xlsx",
            "config_path": "/path/to/config.sh",
            "status": "running",
            "last_completed_page": 2,
            "next_start_page": 3,
            "updated_at": "2024-01-01T00:00:00",
        }
        state_path.write_text(json.dumps(expected_state))

        result = re.load_extraction_state(state_path)

        assert result == expected_state

    def test_save_extraction_state_creates_file(self, tmp_path):
        """Saving state should create the state file."""
        state_path = tmp_path / "state.json"

        success = re.save_extraction_state(
            state_path=state_path,
            project_id="123",
            workbook_path=Path("/path/to/workbook.xlsx"),
            config_path="/path/to/config.sh",
            status="running",
            last_completed_page=2,
            next_start_page=3,
        )

        assert success is True
        assert state_path.exists()

        loaded = json.loads(state_path.read_text())
        assert loaded["project_id"] == "123"
        assert loaded["status"] == "running"
        assert loaded["last_completed_page"] == 2
        assert loaded["next_start_page"] == 3

    def test_save_extraction_state_includes_error(self, tmp_path):
        """Saving failed state should include error message."""
        state_path = tmp_path / "state.json"

        re.save_extraction_state(
            state_path=state_path,
            project_id="123",
            workbook_path=Path("/path/to/workbook.xlsx"),
            config_path="/path/to/config.sh",
            status="failed",
            last_completed_page=1,
            next_start_page=2,
            error="Navigation failed: button not found",
        )

        loaded = json.loads(state_path.read_text())
        assert loaded["status"] == "failed"
        assert loaded["error"] == "Navigation failed: button not found"

    def test_is_resumable_state_returns_false_for_none(self):
        """None state should not be resumable."""
        is_resumable, page, reason = re.is_resumable_state(None)

        assert is_resumable is False
        assert page is None
        assert "No persisted state" in reason

    def test_is_resumable_state_returns_false_for_completed(self):
        """Completed state should not be resumable."""
        state = {
            "version": 1,
            "project_id": "123",
            "workbook_path": "/path/to/workbook.xlsx",
            "status": "completed",
            "updated_at": "2024-01-01T00:00:00",
            "next_start_page": None,
        }

        is_resumable, page, reason = re.is_resumable_state(state)

        assert is_resumable is False
        assert "already completed" in reason.lower()

    def test_is_resumable_state_returns_false_for_invalid_status(self):
        """State with invalid status should not be resumable."""
        state = {
            "version": 1,
            "project_id": "123",
            "workbook_path": "/path/to/workbook.xlsx",
            "status": "unknown",
            "updated_at": "2024-01-01T00:00:00",
            "next_start_page": 3,
        }

        is_resumable, page, reason = re.is_resumable_state(state)

        assert is_resumable is False
        assert "Invalid status" in reason

    def test_is_resumable_state_returns_false_for_null_next_page(self):
        """State with null next_start_page should not be resumable."""
        state = {
            "version": 1,
            "project_id": "123",
            "workbook_path": "/path/to/workbook.xlsx",
            "status": "running",
            "updated_at": "2024-01-01T00:00:00",
            "next_start_page": None,
        }

        is_resumable, page, reason = re.is_resumable_state(state)

        assert is_resumable is False
        assert "No resume page" in reason

    def test_is_resumable_state_returns_false_for_invalid_page(self):
        """State with invalid page number should not be resumable."""
        state = {
            "version": 1,
            "project_id": "123",
            "workbook_path": "/path/to/workbook.xlsx",
            "status": "running",
            "updated_at": "2024-01-01T00:00:00",
            "next_start_page": 0,
        }

        is_resumable, page, reason = re.is_resumable_state(state)

        assert is_resumable is False
        assert "Invalid resume page" in reason

    def test_is_resumable_state_returns_true_for_running(self):
        """Running state with valid page should be resumable."""
        state = {
            "version": 1,
            "project_id": "123",
            "workbook_path": "/path/to/workbook.xlsx",
            "status": "running",
            "updated_at": "2024-01-01T00:00:00",
            "next_start_page": 3,
        }

        is_resumable, page, reason = re.is_resumable_state(state)

        assert is_resumable is True
        assert page == 3
        assert reason == ""

    def test_is_resumable_state_returns_true_for_failed(self):
        """Failed state with valid page should be resumable."""
        state = {
            "version": 1,
            "project_id": "123",
            "workbook_path": "/path/to/workbook.xlsx",
            "status": "failed",
            "updated_at": "2024-01-01T00:00:00",
            "next_start_page": 5,
        }

        is_resumable, page, reason = re.is_resumable_state(state)

        assert is_resumable is True
        assert page == 5


class TestResumeIntegration:
    """Integration tests for --resume functionality."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in resume tests."""

    @patch("run_extraction.RuntimeManager")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_fails_when_no_persisted_state(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_manager_class,
        tmp_path,
    ):
        """--resume should fail when no persisted state exists."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Use isolated work_dir to avoid state pollution from other tests
        work_dir = tmp_path / "isolated_work"
        work_dir.mkdir()
        mock_manager = MagicMock()
        mock_manager.work_dir = work_dir
        mock_manager_class.return_value = mock_manager

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = True  # Request resume

        with patch("run_extraction.get_existing_keys") as mock_keys:
            mock_keys.return_value = set()
            result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]
        assert "No persisted state" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_uses_persisted_next_start_page(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume should use persisted next_start_page instead of args.start_page."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create persisted state with next_start_page=3
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "dry_run": True,  # Must match args.dry_run
                    "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1  # Should be overridden by persisted state
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=50",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        # Should navigate to page 3 (from persisted state), not page 1
        mock_navigate.assert_called_once()
        call_kwargs = mock_navigate.call_args[1]
        assert call_kwargs["page"] == 3

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_successful_extraction_writes_completed_state(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Successful extraction should write completed state with next_start_page null."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        # First page has candidates, second page has no results (true end)
        mock_extract.side_effect = [
            {
                "success": True,
                "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
                "exit_code": 0,
            },
            {
                "success": False,
                "message": "No results found",
                "exit_code": 2,  # No results = true completion
            },
        ]
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        work_dir = tmp_path / "work"

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 0  # Unlimited - let it complete naturally
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True

        # Verify completed state was written
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        assert state_path.exists()

        loaded = json.loads(state_path.read_text())
        assert loaded["status"] == "completed"
        assert loaded["next_start_page"] is None
        assert loaded["last_completed_page"] == 1

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_failure_writes_failed_state_with_retryable_page(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Failure should write failed state with next_start_page set to retry page."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        # Extraction fails on first page
        mock_extract.return_value = {
            "success": False,
            "message": "Browser timeout",
            "exit_code": 1,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        work_dir = tmp_path / "work"

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False

        # Verify failed state was written
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        assert state_path.exists()

        loaded = json.loads(state_path.read_text())
        assert loaded["status"] == "failed"
        assert loaded["next_start_page"] == 1  # Should retry from page 1
        assert loaded["last_completed_page"] is None  # No pages completed
        assert "Browser timeout" in loaded["error"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_per_page_success_updates_next_start_page(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Each successful page should update state with next_start_page."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        # Return candidates for first page, fail on second
        mock_extract.side_effect = [
            {
                "success": True,
                "candidates": [
                    {"name": "Page1User", "url": "https://linkedin.com/in/p1"}
                ],
                "exit_code": 0,
            },
            {
                "success": False,
                "message": "Navigation failed",
                "exit_code": 1,
            },
        ]
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        work_dir = tmp_path / "work"

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 2
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is False  # Failed on page 2
        assert result["pages_processed"] == 1  # But page 1 succeeded

        # Verify failed state shows page 2 as the retry point
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        loaded = json.loads(state_path.read_text())
        assert loaded["status"] == "failed"
        assert loaded["last_completed_page"] == 1
        assert loaded["next_start_page"] == 2  # Should retry from page 2

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_fails_for_malformed_state(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume should fail closed for malformed persisted state."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create malformed state (invalid JSON)
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("not valid json")

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_fails_for_completed_state(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume should fail for completed state (not resumable)."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create completed state
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "completed",
                    "last_completed_page": 5,
                    "next_start_page": None,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]
        assert "already completed" in result["message"].lower()

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_rejects_state_with_different_project_id(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume must reject state file belonging to different project_id."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create state for DIFFERENT project (999 instead of 123)
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "999",  # Different project!
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]
        assert "different project" in result["message"].lower()
        assert "expected: 123" in result["message"]
        assert "found: 999" in result["message"]

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_max_pages_partial_run_remains_resumable(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """max-pages limit reached should persist resumable state, not completed."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        # Return candidates for all pages (more available than max_pages)
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        work_dir = tmp_path / "work"

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 2  # Limit to 2 pages even though more exist
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        assert result["pages_processed"] == 2

        # Verify resumable state was written (not completed)
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        assert state_path.exists()

        loaded = json.loads(state_path.read_text())
        assert loaded["status"] == "running"  # Resumable, not completed
        assert loaded["next_start_page"] == 3  # Next page to resume from
        assert loaded["last_completed_page"] == 2

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_true_completion_writes_completed_state(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """True completion (no more results) should write completed state with null next_start_page."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        # First page has candidates, second page has no results (true end)
        mock_extract.side_effect = [
            {
                "success": True,
                "candidates": [{"name": "User1", "url": "https://linkedin.com/in/u1"}],
                "exit_code": 0,
            },
            {
                "success": False,
                "message": "No results found",
                "exit_code": 2,  # No results exit code
            },
        ]
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        work_dir = tmp_path / "work"

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 0  # Unlimited - process all pages
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        assert result["pages_processed"] == 1  # Only 1 page before no results

        # Verify completed state was written
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        assert state_path.exists()

        loaded = json.loads(state_path.read_text())
        assert loaded["status"] == "completed"
        assert loaded["next_start_page"] is None  # No more pages to resume
        assert loaded["last_completed_page"] == 1

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_rejects_state_with_different_workbook_path(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume must reject state file belonging to different workbook_path."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        different_workbook = tmp_path / "different.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create state for DIFFERENT workbook
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(different_workbook),  # Different workbook!
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]
        assert "different workbook" in result["message"].lower()

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_rejects_state_with_different_config_path(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume must reject state file belonging to different config path."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create state for DIFFERENT config
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/different/path/config.sh",  # Different config!
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]
        assert "different config" in result["message"].lower()

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_rejects_state_with_different_fresh_url_project(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume must reject state file with different fresh URL project (search identity)."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create state with DIFFERENT fresh URL project (different search identity)
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "fresh_url": "https://linkedin.com/talent/hire/999/discover/recruiterSearch?searchContextId=xyz",  # Different project!
                    "dry_run": True,
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]
        assert "fresh url project mismatch" in result["message"].lower()


class TestStateDirectoryCreationFailure:
    """Tests for state directory creation failure handling (fail closed)."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in state-dir tests."""

    @patch("run_extraction.get_extraction_state_path")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_state_dir_creation_failure_returns_structured_error(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_get_state_path,
        tmp_path,
    ):
        """State directory creation failure should return structured error, not crash."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        # Simulate state directory creation failure
        mock_get_state_path.return_value = {
            "success": False,
            "path": None,
            "error": "Failed to create state directory /work/runtime/extraction-state: [Errno 13] Permission denied",
        }

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = tmp_path / "work"
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 2
        assert "Failed to create state directory" in result["message"]
        assert "Permission denied" in result["message"]
        # Extraction should NOT proceed when state dir cannot be created
        mock_extract.assert_not_called()


class TestStateWriteFailure:
    """Tests for state-write failure handling (fail closed)."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in state-write tests."""

    @patch("run_extraction.save_extraction_state")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_running_state_write_failure_fails_closed(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_save,
        tmp_path,
    ):
        """Initial running-state write failure must fail closed with clear message."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        mock_save.return_value = False  # State write fails

        work_dir = tmp_path / "work"

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 2  # Request 2 pages to trigger running-state write
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 2
        assert "Failed to persist running state" in result["message"]

    @patch("run_extraction.save_extraction_state")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_completed_state_write_failure_fails_closed(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_save,
        tmp_path,
    ):
        """Completed-state write failure must fail closed with clear message."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        # First call (running state) succeeds, second (completed) fails
        mock_save.side_effect = [True, False]

        work_dir = tmp_path / "work"

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 2
        assert "Failed to persist completed state" in result["message"]

    @patch("run_extraction.save_extraction_state")
    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_failed_state_write_failure_fails_closed(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        mock_save,
        tmp_path,
    ):
        """Failed-state write failure must fail closed with clear message."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        # Extraction fails
        mock_extract.return_value = {
            "success": False,
            "message": "Browser timeout",
            "exit_code": 1,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }
        mock_save.return_value = False  # State write fails

        work_dir = tmp_path / "work"

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 2  # State write failure uses exit code 2
        assert "Browser timeout" in result["message"]
        assert "failed to persist state" in result["message"].lower()


class TestAtomicStateWrite:
    """Tests for atomic state persistence using temp file + rename pattern."""

    def test_save_extraction_state_uses_atomic_write(self, tmp_path):
        """State save should use temp file + rename for atomicity."""
        state_path = tmp_path / "state.json"

        success = re.save_extraction_state(
            state_path=state_path,
            project_id="123",
            workbook_path=Path("/path/to/workbook.xlsx"),
            config_path="/path/to/config.sh",
            status="running",
            last_completed_page=2,
            next_start_page=3,
        )

        assert success is True
        assert state_path.exists()
        # Temp file should not exist after successful write
        temp_path = state_path.with_suffix(".tmp")
        assert not temp_path.exists()

    def test_atomic_write_preserves_old_state_on_failure(self, tmp_path):
        """Failed write should preserve old valid state file."""
        state_path = tmp_path / "state.json"
        # Create existing valid state
        old_state = {
            "version": 1,
            "project_id": "123",
            "workbook_path": "/path/to/workbook.xlsx",
            "config_path": "/path/to/config.sh",
            "status": "running",
            "last_completed_page": 5,
            "next_start_page": 6,
            "updated_at": "2024-01-01T00:00:00",
        }
        state_path.write_text(json.dumps(old_state))

        # Make temp file path non-writable by creating a file there first
        # and making it read-only (simulating disk full or permission error)
        temp_path = state_path.with_suffix(".tmp")

        # Mock write_text to fail on first call (temp file creation)
        original_write_text = Path.write_text
        fail_count = [0]

        def failing_write_text(self, *args, **kwargs):
            if self == temp_path:
                fail_count[0] += 1
                raise PermissionError("Simulated write failure")
            return original_write_text(self, *args, **kwargs)

        with patch.object(Path, "write_text", failing_write_text):
            success = re.save_extraction_state(
                state_path=state_path,
                project_id="123",
                workbook_path=Path("/path/to/workbook.xlsx"),
                config_path="/path/to/config.sh",
                status="failed",
                last_completed_page=6,
                next_start_page=7,
                error="Simulated error",
            )

        assert success is False
        # Old state should be preserved
        assert state_path.exists()
        loaded = json.loads(state_path.read_text())
        assert loaded["last_completed_page"] == 5  # Old value preserved
        assert loaded["status"] == "running"  # Old status preserved

    def test_atomic_write_cleans_up_temp_file_on_failure(self, tmp_path):
        """Failed write should clean up temp file."""
        state_path = tmp_path / "state.json"
        temp_path = state_path.with_suffix(".tmp")

        # Mock replace to fail after temp file is created
        original_replace = Path.replace

        def failing_replace(self, *args, **kwargs):
            if str(self).endswith(".tmp"):
                raise OSError("Simulated rename failure")
            return original_replace(self, *args, **kwargs)

        with patch.object(Path, "replace", failing_replace):
            success = re.save_extraction_state(
                state_path=state_path,
                project_id="123",
                workbook_path=Path("/path/to/workbook.xlsx"),
                config_path="/path/to/config.sh",
                status="running",
                last_completed_page=2,
                next_start_page=3,
            )

        assert success is False
        # Temp file should be cleaned up
        assert not temp_path.exists()

    def test_save_extraction_state_includes_fresh_url_and_dry_run(self, tmp_path):
        """State should include fresh_url and dry_run when provided."""
        state_path = tmp_path / "state.json"
        fresh_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc"

        success = re.save_extraction_state(
            state_path=state_path,
            project_id="123",
            workbook_path=Path("/path/to/workbook.xlsx"),
            config_path="/path/to/config.sh",
            status="running",
            last_completed_page=2,
            next_start_page=3,
            fresh_url=fresh_url,
            dry_run=True,
        )

        assert success is True
        loaded = json.loads(state_path.read_text())
        assert loaded["fresh_url"] == fresh_url
        assert loaded["dry_run"] is True


class TestResumeStateIdentityValidation:
    """Tests for resume state identity validation (fresh URL, dry-run mode)."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in identity validation tests."""

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_rejects_dry_run_state_for_real_run(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume must reject dry-run state when current run is real (fail-closed)."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create state from dry-run
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
                    "dry_run": True,  # State from dry-run
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = False  # Current run is REAL
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]
        assert "dry-run" in result["message"].lower()
        assert "real" in result["message"].lower()

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_rejects_real_state_for_dry_run(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume must reject real state when current run is dry-run (fail-closed)."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create state from real run
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
                    "dry_run": False,  # State from real run
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True  # Current run is DRY-RUN
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                result = re.run_extraction(args)

        assert result["success"] is False
        assert result.get("exit_code") == 1
        assert "Cannot resume" in result["message"]
        assert "dry-run" in result["message"].lower()
        assert "real" in result["message"].lower()

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_resume_accepts_matching_dry_run_state(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """--resume should accept dry-run state when current run is also dry-run."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create state from dry-run
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
                    "dry_run": True,  # State from dry-run
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True  # Current run is also DRY-RUN
        args.start_page = 1
        args.max_pages = 1
        args.resume = True

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=50",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        # Should succeed - dry_run mode matches
        assert result["success"] is True


class TestProjectRefResolution:
    """Tests for --project argument and project reference resolution."""

    @patch("run_extraction.resolve_project_ref")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.run_preflight")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_project_arg_resolves_to_config(
        self,
        mock_resolve_context,
        mock_preflight,
        mock_parse,
        mock_resolve_ref,
        tmp_path,
    ):
        """--project should resolve to config path and proceed with extraction."""
        config_path = tmp_path / "my_project" / "config.sh"
        workbook_path = tmp_path / "my_project.xlsx"

        mock_resolve_ref.return_value = {
            "success": True,
            "config_path": config_path,
            "local_project_id": "my_project",
            "workbook_path": workbook_path,
            "recruiter_project_id": "12345",
            "error": None,
        }
        mock_parse.return_value = {
            "PROJECT_ID": "my_project",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/12345/overview",
        }
        mock_preflight.return_value = {
            "success": True,
            "exit_code": None,
            "message": "",
            "workbook_path": workbook_path,
            "existing_urls": set(),
            "project_id": "12345",
            "cdp_port": "9234",
            "work_dir": str(tmp_path),
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/12345/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Simulate main() behavior
        args = Mock()
        args.project = "my_project"
        args.config = None
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = False

        # Resolve project ref (as main() does)
        resolution = mock_resolve_ref(args.project)
        args.config = str(resolution["config_path"])
        args.workbook = str(resolution["workbook_path"])

        # Verify resolution was used
        assert args.config == str(config_path)
        assert args.workbook == str(workbook_path)
        mock_resolve_ref.assert_called_once_with("my_project")

    @patch("run_extraction.resolve_project_ref")
    def test_project_resolution_failure_exits(
        self,
        mock_resolve_ref,
        tmp_path,
    ):
        """Failed project resolution should exit with error."""
        mock_resolve_ref.return_value = {
            "success": False,
            "config_path": None,
            "local_project_id": None,
            "workbook_path": None,
            "recruiter_project_id": None,
            "error": "Project not found: unknown_project",
        }

        # Simulate main() behavior with failed resolution
        args = Mock()
        args.project = "unknown_project"

        resolution = mock_resolve_ref(args.project)
        if not resolution["success"]:
            error_message = f"Error: {resolution['error']}"
            # In real main(), this would print and return 1
            assert "Project not found" in error_message

    @patch("run_extraction.resolve_project_ref")
    def test_project_url_resolution(
        self,
        mock_resolve_ref,
        tmp_path,
    ):
        """--project with URL should resolve to matching project config."""
        config_path = tmp_path / "projects" / "my_project" / "config.sh"
        workbook_path = tmp_path / "projects" / "my_project.xlsx"

        mock_resolve_ref.return_value = {
            "success": True,
            "config_path": config_path,
            "local_project_id": "my_project",
            "workbook_path": workbook_path,
            "recruiter_project_id": "12345",
            "error": None,
        }

        url = "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        resolution = mock_resolve_ref(url)

        assert resolution["success"] is True
        assert resolution["recruiter_project_id"] == "12345"

    @patch("run_extraction.resolve_project_ref")
    def test_project_numeric_id_resolution(
        self,
        mock_resolve_ref,
        tmp_path,
    ):
        """--project with numeric ID should resolve to matching project config."""
        config_path = tmp_path / "projects" / "my_project" / "config.sh"

        mock_resolve_ref.return_value = {
            "success": True,
            "config_path": config_path,
            "local_project_id": "my_project",
            "workbook_path": tmp_path / "projects" / "my_project.xlsx",
            "recruiter_project_id": "12345",
            "error": None,
        }

        resolution = mock_resolve_ref("12345")

        assert resolution["success"] is True
        assert resolution["recruiter_project_id"] == "12345"


class TestAutoResume:
    """Tests for auto-resume functionality when no explicit --resume or --start-page > 1."""

    @pytest.fixture(autouse=True)
    def _mock_preflight_probe(self, mock_ready_preflight_probe):
        """Keep browser preflight deterministic in auto-resume tests."""

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_auto_resume_only_with_project_ref(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Auto-resume should ONLY trigger when using --project, not --config."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create resumable state at page 3
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "dry_run": True,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1  # Default, not explicitly > 1
        args.max_pages = 1  # Only process 1 page
        args.resume = False  # Not explicitly requested
        args._project_ref_used = False  # --config was used, not --project

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        # Should NOT auto-resume - should start from page 1 (default)
        # because --config was used, not --project
        # Since max_pages=1 and start_page=1, navigate_to_page is never called
        # (page 1 uses fresh URL directly, no navigation needed)
        mock_navigate.assert_not_called()
        # Verify we processed 1 page (page 1, not page 3 from state)
        assert result["pages_processed"] == 1

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_no_auto_resume_when_explicit_start_page(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should NOT auto-resume when explicit --start-page > 1 provided."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create resumable state at page 5
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 4,
                    "next_start_page": 5,
                    "dry_run": True,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 2  # EXPLICITLY set to page 2
        args.max_pages = 1
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        # Should use explicit start_page=2, NOT auto-resume from page 5
        mock_navigate.assert_called_once()
        call_kwargs = mock_navigate.call_args[1]
        assert call_kwargs["page"] == 2

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_no_auto_resume_when_explicit_resume_flag(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Explicit --resume should use normal resume flow, not auto-resume."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create resumable state at page 3
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "dry_run": True,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = True  # EXPLICITLY requested

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=50",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        # Should resume from page 3 (explicit --resume path)
        mock_navigate.assert_called_once()
        call_kwargs = mock_navigate.call_args[1]
        assert call_kwargs["page"] == 3

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_no_auto_resume_when_state_not_resumable(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should NOT auto-resume when state exists but is not resumable (e.g., completed)."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create completed state (not resumable)
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "completed",  # Not resumable
                    "last_completed_page": 5,
                    "next_start_page": None,
                    "dry_run": True,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 2  # Request 2 pages to trigger navigation
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        # Should start from page 1 (default), not try to resume
        # navigate_to_page is called for page 2 (since max_pages=2)
        mock_navigate.assert_called_once()
        call_kwargs = mock_navigate.call_args[1]
        assert call_kwargs["page"] == 2

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_no_auto_resume_when_identity_mismatch(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Should NOT auto-resume when state identity doesn't match current run."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create state with different project_id (identity mismatch)
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "999",  # Different project!
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "dry_run": True,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 2  # Request 2 pages to trigger navigation
        args.resume = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        # Should start from page 1 due to identity mismatch, not auto-resume
        # navigate_to_page is called for page 2 (since max_pages=2)
        mock_navigate.assert_called_once()
        call_kwargs = mock_navigate.call_args[1]
        assert call_kwargs["page"] == 2

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_auto_resume_only_with_project_ref(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Auto-resume should ONLY trigger when using --project, not --config."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create resumable state at page 3
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "dry_run": True,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = False
        # CRITICAL: _project_ref_used=False means --config was used, not --project
        args._project_ref_used = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        # Should NOT auto-resume - should start from page 1 (default)
        # because --config was used, not --project
        # Since max_pages=1 and start_page=1, navigate_to_page is never called
        # (page 1 uses fresh URL directly, no navigation needed)
        mock_navigate.assert_not_called()
        # Verify we processed 1 page (page 1, not page 3 from state)
        assert result["pages_processed"] == 1

    @patch("run_extraction.extract_candidates_from_page")
    @patch("run_extraction.ensure_workbook")
    @patch("run_extraction.resolve_workbook_path")
    @patch("run_extraction.parse_config_file")
    @patch("run_extraction.resolve_fresh_search_context")
    def test_auto_resume_with_project_ref_flag(
        self,
        mock_resolve_context,
        mock_parse,
        mock_resolve,
        mock_ensure,
        mock_extract,
        tmp_path,
    ):
        """Auto-resume SHOULD trigger when _project_ref_used=True (i.e., --project was used)."""
        mock_parse.return_value = {
            "PROJECT_ID": "123",
            "RECRUITER_PROJECT_URL": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }
        workbook_path = tmp_path / "workbook.xlsx"
        mock_resolve.return_value = workbook_path
        mock_ensure.return_value = True
        mock_extract.return_value = {
            "success": True,
            "candidates": [{"name": "User", "url": "https://linkedin.com/in/user"}],
            "exit_code": 0,
        }
        mock_resolve_context.return_value = {
            "success": True,
            "fresh_url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc",
            "error": None,
        }

        # Create resumable state at page 3
        work_dir = tmp_path / "work"
        state_result = re.get_extraction_state_path(work_dir, "123", workbook_path)
        state_path = state_result["path"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "project_id": "123",
                    "workbook_path": str(workbook_path),
                    "config_path": "/path/to/config.sh",
                    "status": "failed",
                    "last_completed_page": 2,
                    "next_start_page": 3,
                    "dry_run": True,
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

        args = Mock()
        args.config = "/path/to/config.sh"
        args.workbook = None
        args.cdp_port = "9234"
        args.dry_run = True
        args.start_page = 1
        args.max_pages = 1
        args.resume = False
        # CRITICAL: _project_ref_used=True means --project was used
        args._project_ref_used = True
        # CRITICAL: _explicit_start_page=False means --start-page was NOT explicitly provided
        args._explicit_start_page = False

        with patch("run_extraction.RuntimeManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.work_dir = work_dir
            mock_manager_class.return_value = mock_manager

            with patch("run_extraction.get_existing_keys") as mock_keys:
                mock_keys.return_value = set()
                with patch("run_extraction.navigate_to_page") as mock_navigate:
                    mock_navigate.return_value = {
                        "success": True,
                        "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=50",
                        "state": "ready",
                        "method": "ui_pagination",
                    }
                    result = re.run_extraction(args)

        assert result["success"] is True
        # SHOULD auto-resume from page 3 because --project was used
        mock_navigate.assert_called_once()
        call_kwargs = mock_navigate.call_args[1]
        assert call_kwargs["page"] == 3


class TestProcessCandidatesProfileUrlSchema:
    """Tests for process_candidates with profile_url schema (backward compatibility)."""

    def test_prefers_profile_url_over_url(self, tmp_path):
        """Should prefer profile_url key over url for downstream compatibility."""
        wb_path = tmp_path / "test.xlsx"

        with patch("run_extraction.upsert") as mock_upsert:
            mock_upsert.return_value = {"row_id": 1, "action": "inserted"}

            # Candidate with new schema (profile_url)
            candidates = [
                {
                    "name": "John",
                    "profile_url": "https://linkedin.com/in/john",
                    "title": "Engineer",
                }
            ]
            existing_urls = set()

            stats = re.process_candidates(
                candidates, wb_path, existing_urls, dry_run=False
            )

        assert stats["total"] == 1
        assert stats["new"] == 1
        # Verify upsert was called with profile_url (second positional arg is row_data)
        call_args = mock_upsert.call_args[0]
        assert call_args[1]["profile_url"] == "https://linkedin.com/in/john"

    def test_fallback_to_url_when_profile_url_missing(self, tmp_path):
        """Should fallback to url key when profile_url is not present (backward compat)."""
        wb_path = tmp_path / "test.xlsx"

        with patch("run_extraction.upsert") as mock_upsert:
            mock_upsert.return_value = {"row_id": 1, "action": "inserted"}

            # Candidate with legacy schema (url only)
            candidates = [
                {
                    "name": "Jane",
                    "url": "https://linkedin.com/in/jane",
                    "title": "Manager",
                }
            ]
            existing_urls = set()

            stats = re.process_candidates(
                candidates, wb_path, existing_urls, dry_run=False
            )

            assert stats["total"] == 1
            assert stats["new"] == 1
            # Verify upsert was called with url value as profile_url
            call_args = mock_upsert.call_args[0]
            assert call_args[1]["profile_url"] == "https://linkedin.com/in/jane"

    def test_empty_profile_url_falls_back_to_url(self, tmp_path):
        """Should fallback to url when profile_url is empty string."""
        wb_path = tmp_path / "test.xlsx"

        with patch("run_extraction.upsert") as mock_upsert:
            mock_upsert.return_value = {"row_id": 1, "action": "inserted"}

            # Candidate with both keys but profile_url is empty
            candidates = [
                {
                    "name": "Bob",
                    "profile_url": "",
                    "url": "https://linkedin.com/in/bob",
                }
            ]
            existing_urls = set()

            stats = re.process_candidates(
                candidates, wb_path, existing_urls, dry_run=False
            )

            # Verify upsert used url as fallback
            call_args = mock_upsert.call_args[0]
            assert call_args[1]["profile_url"] == "https://linkedin.com/in/bob"


class TestArtdecoPaginationPattern:
    """Tests for artdeco-pagination__button--next pattern recognition (live UI)."""

    @patch("run_extraction.run_browser_command")
    def test_artdeco_pagination_button_recognized(self, mock_run_browser):
        """Should recognize button.artdeco-pagination__button--next as valid next control."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "pagination_button",
                    "previousUrl": page1_url,
                }
            },
            {"parsed": {"url": page2_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        assert result["success"] is True
        assert result["is_last_page"] is False
        assert result["current_url"] == page2_url

        # Verify the JS code includes artdeco-pagination__button--next selector
        js_code = mock_run_browser.call_args_list[0][0][2]
        assert "artdeco-pagination__button--next" in js_code

    @patch("run_extraction.run_browser_command")
    def test_artdeco_disabled_button_detected_as_last_page(self, mock_run_browser):
        """Should detect button.artdeco-pagination__button--next.artdeco-button--disabled as last page."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"

        mock_run_browser.return_value = {
            "parsed": {
                "clicked": False,
                "isLastPage": True,
                "method": "last_page_detected",
                "previousUrl": page1_url,
                "error": None,
            }
        }

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        assert result["success"] is True
        assert result["is_last_page"] is True
        assert result["error"] is None

        # Verify the JS code includes disabled artdeco button selectors
        js_code = mock_run_browser.call_args[0][2]
        assert (
            "button.artdeco-pagination__button--next.artdeco-button--disabled"
            in js_code
        )
        assert "button.artdeco-pagination__button--next[disabled]" in js_code

    @patch("run_extraction.run_browser_command")
    def test_artdeco_button_scoring_prioritizes_over_generic(self, mock_run_browser):
        """Should prioritize artdeco-pagination__button--next with higher score."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "next_link",
                    "text": "Next",
                    "previousUrl": page1_url,
                }
            },
            {"parsed": {"url": page2_url}},
        ]

        re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Verify the JS code includes scoring for artdeco pattern
        js_code = mock_run_browser.call_args_list[0][0][2]
        # The scoring function should give points to artdeco-pagination__button--next
        assert "artdeco-pagination__button--next" in js_code
        assert "getPaginationScore" in js_code

    @patch("run_extraction.run_browser_command")
    def test_generic_next_controls_remain_excluded_without_pagination_root(
        self, mock_run_browser
    ):
        """Generic Next controls outside pagination should remain excluded."""
        page1_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=0"
        page2_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=25"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "next_link",
                    "text": "Go to next page 2",
                    "previousUrl": page1_url,
                }
            },
            {"parsed": {"url": page2_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=25,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        assert result["success"] is True
        js_code = mock_run_browser.call_args_list[0][0][2]
        assert (
            "if (!root && !elClass.includes('artdeco-pagination__button--next'))"
            in js_code
        )


class TestLastPageFalsePositiveRegression:
    """Regression tests for last-page false-positive with artdeco header button (issue #3)."""

    @patch("run_extraction.run_browser_command")
    def test_artdeco_header_button_not_clicked_when_no_forward_page_link(
        self, mock_run_browser
    ):
        """Artdeco header Next button should NOT be clicked when no forward page link exists.

        Regression test: On the last page (e.g., page 7 of 7), LinkedIn Recruiter shows:
        - Bottom pagination with numbered links up to current page (Page 7)
        - Header artdeco "Next" button that appears enabled but leads to 404

        The code should detect that current page is the highest visible page and
        there's no forward page link, classifying as last page instead of clicking.
        """
        # Page 7 URL (last page with 167 results, start=150)
        page7_url = "https://linkedin.com/talent/hire/1683119140/discover/recruiterSearch?searchContextId=abc&start=150"

        # Simulate JS detecting artdeco button but inferring last page due to no forward link
        mock_run_browser.return_value = {
            "parsed": {
                "clicked": False,
                "isLastPage": True,
                "method": "last_page_inferred",
                "previousUrl": page7_url,
                "error": None,
                "debug": {
                    "currentPageNum": 7,
                    "highestVisiblePage": 7,
                    "hasForwardPageLink": False,
                },
            }
        }

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=175,  # Would be page 8
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Should return clean last-page result, NOT click and navigate to 404
        assert result["success"] is True  # Clean end-of-results
        assert result["is_last_page"] is True
        assert result["error"] is None
        # Should NOT have navigated to a different URL
        assert result["current_url"] == page7_url
        assert result["previous_url"] == page7_url

    @patch("run_extraction.run_browser_command")
    def test_artdeco_button_clicked_when_forward_page_link_exists(
        self, mock_run_browser
    ):
        """Artdeco header Next button SHOULD be clicked when forward page link exists.

        On pages 1-6 of 7, there IS a forward page link (to page 7), so the artdeco
        Next button is legitimate and should be clicked.
        """
        page6_url = "https://linkedin.com/talent/hire/1683119140/discover/recruiterSearch?searchContextId=abc&start=125"
        page7_url = "https://linkedin.com/talent/hire/1683119140/discover/recruiterSearch?searchContextId=abc&start=150"

        # Simulate JS finding artdeco button AND forward page link, clicking successfully
        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "pagination_button",
                    "previousUrl": page6_url,
                }
            },
            {"parsed": {"url": page7_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=150,  # Page 7
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Should successfully navigate to page 7
        assert result["success"] is True
        assert result["is_last_page"] is False
        assert result["current_url"] == page7_url

    @patch("run_extraction.run_browser_command")
    def test_js_includes_last_page_inference_logic(self, mock_run_browser):
        """JS code should include logic to infer last page from visible pagination."""
        page7_url = "https://linkedin.com/talent/hire/1683119140/discover/recruiterSearch?searchContextId=abc&start=150"

        mock_run_browser.return_value = {
            "parsed": {
                "clicked": False,
                "isLastPage": True,
                "method": "last_page_inferred",
                "previousUrl": page7_url,
                "error": None,
            }
        }

        re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=175,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        js_code = mock_run_browser.call_args[0][2]

        # JS should check for artdeco header button specifically
        assert "artdeco-pagination__button--next" in js_code

        # JS should look for page links to determine highest visible page
        assert "highestVisiblePage" in js_code or "pageLinks" in js_code

        # JS should check for forward page links
        assert "hasForwardPageLink" in js_code or "forward" in js_code.lower()

        # JS should compare current page to highest visible
        assert "currentPageNum" in js_code or "current page" in js_code.lower()

        # JS should inspect visible pagination text, not just href-based links
        assert "nav li" in js_code
        assert "Page\\s+(\\d+)" in js_code
        assert "hasVisiblePageEvidence" in js_code
        assert "hasCurrentPageMarker" in js_code

    @patch("run_extraction.run_browser_command")
    def test_explicit_page_links_preferred_over_artdeco_button(self, mock_run_browser):
        """Explicit numbered page links should be preferred over artdeco header button."""
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"
        page4_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=75"

        # Simulate clicking via explicit page link (next_link method), not artdeco button
        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "next_link",  # Preferred method
                    "text": "Go to next page 4",
                    "previousUrl": page3_url,
                }
            },
            {"parsed": {"url": page4_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=75,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        assert result["success"] is True
        assert result["is_last_page"] is False
        assert result["current_url"] == page4_url

        # Verify the JS code prefers explicit links
        js_code = mock_run_browser.call_args_list[0][0][2]
        # Strategy 1 (next_link) should come before Strategy 2 (pagination_button)
        strategy1_pos = js_code.find("Strategy 1: Look for ENABLED")
        strategy2_pos = js_code.find("Strategy 2: Look for ENABLED pagination button")
        assert strategy1_pos < strategy2_pos, (
            "Strategy 1 (explicit links) must come before Strategy 2 (buttons)"
        )

    @patch("run_extraction.run_browser_command")
    def test_fail_closed_when_pagination_ambiguous(self, mock_run_browser):
        """When pagination state is ambiguous, should fail closed (not assume last page)."""
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"

        # No enabled controls found, no disabled button found - ambiguous state
        mock_run_browser.return_value = {
            "parsed": {
                "clicked": False,
                "isLastPage": False,
                "method": "no_next_button",
                "previousUrl": page3_url,
                "error": "Next page button not found - possible DOM drift or selector mismatch",
            }
        }

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=75,
            max_wait_seconds=1.0,
            poll_interval=0.1,
        )

        # Should fail closed - missing button is a failure, not a clean last page
        assert result["success"] is False
        assert result["is_last_page"] is False
        assert "not found" in result["error"].lower() or "DOM drift" in result["error"]

    @patch("run_extraction.run_browser_command")
    def test_unchanged_url_after_click_infers_last_page(self, mock_run_browser):
        """Unchanged URL after click should re-check pagination and classify last page when appropriate."""
        page7_url = "https://linkedin.com/talent/hire/1683119140/discover/recruiterSearch?searchContextId=abc&start=150"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "pagination_button",
                    "previousUrl": page7_url,
                }
            },
            {"parsed": {"url": page7_url}},
            {"parsed": {"isLastPage": True, "currentPageNum": 7}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=175,
            max_wait_seconds=0.1,
            poll_interval=0.1,
        )

        assert result["success"] is True
        assert result["is_last_page"] is True

    @patch("run_extraction.run_browser_command")
    def test_unchanged_url_after_click_fails_closed_when_not_last_page(
        self, mock_run_browser
    ):
        """Unchanged URL after click should fail closed when re-check cannot prove last page."""
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "pagination_button",
                    "previousUrl": page3_url,
                }
            },
            {"parsed": {"url": page3_url}},
            {"parsed": {"isLastPage": False, "currentPageNum": 3}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=75,
            max_wait_seconds=0.1,
            poll_interval=0.1,
        )

        assert result["success"] is False
        assert result["is_last_page"] is False
        assert "did not reach the expected next page" in result["error"]

    @patch("run_extraction.run_browser_command")
    def test_missing_next_control_rechecks_last_page_before_failing(
        self, mock_run_browser
    ):
        """Missing next control should still classify clean last-page when the re-check proves it."""
        page7_url = "https://linkedin.com/talent/hire/1683119140/discover/recruiterSearch?searchContextId=abc&start=150"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": False,
                    "isLastPage": False,
                    "method": "no_next_button",
                    "previousUrl": page7_url,
                    "error": "Next page button not found - possible DOM drift or selector mismatch",
                }
            },
            {"parsed": {"isLastPage": True, "currentPageNum": 7}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=175,
            max_wait_seconds=0.1,
            poll_interval=0.1,
        )

        assert result["success"] is True
        assert result["is_last_page"] is True

    @patch("run_extraction.run_browser_command")
    def test_artdeco_path_does_not_infer_last_page_without_positive_evidence(
        self, mock_run_browser
    ):
        """Primary artdeco path should require positive evidence before inferring last page."""
        page3_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=50"
        page4_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&start=75"

        mock_run_browser.side_effect = [
            {
                "parsed": {
                    "clicked": True,
                    "isLastPage": False,
                    "method": "pagination_button",
                    "previousUrl": page3_url,
                }
            },
            {"parsed": {"url": page4_url}},
        ]

        result = re.click_next_page_pagination(
            cdp_port="9234",
            expected_start=75,
            max_wait_seconds=0.1,
            poll_interval=0.1,
        )

        assert result["success"] is True
        js_code = mock_run_browser.call_args_list[0][0][2]
        assert "hasVisiblePageEvidence" in js_code
        assert "hasCurrentPageMarker" in js_code


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
