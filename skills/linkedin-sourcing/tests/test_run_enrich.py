#!/usr/bin/env python3
"""Tests for run_enrich.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_run_enrich.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_enrich


class TestEnrichErrorClasses:
    """Tests for EnrichError exception classes."""

    def test_enrich_error_default_exit_code(self):
        error = run_enrich.EnrichError("Test error")
        assert error.exit_code == 1
        assert error.row_id is None

    def test_enrich_error_with_row_id(self):
        error = run_enrich.EnrichError("Test error", row_id=5)
        assert error.row_id == 5

    def test_browser_state_error_default_exit_code(self):
        error = run_enrich.BrowserStateError("Browser not clean")
        assert error.exit_code == 2
        assert error.action_required is None

    def test_browser_state_error_with_action_required(self):
        action = {"code": "test", "steps": ["Fix it"]}
        error = run_enrich.BrowserStateError(
            "Browser issue", row_id=3, action_required=action
        )
        assert error.exit_code == 2
        assert error.row_id == 3
        assert error.action_required == action

    def test_config_error_default_exit_code(self):
        error = run_enrich.ConfigError("Config missing")
        assert error.exit_code == 3


class TestLoadRuntimeContext:
    """Tests for load_runtime_context function."""

    @patch("runtime_manager.RuntimeManager")
    def test_loads_existing_context(self, mock_manager_class):
        mock_manager = MagicMock()
        mock_manager.get_runtime_context.return_value = {"work_dir": "/test"}
        mock_manager_class.return_value = mock_manager

        ctx = run_enrich.load_runtime_context()

        assert ctx["work_dir"] == "/test"

    @patch("runtime_manager.RuntimeManager")
    def test_initializes_when_no_context(self, mock_manager_class):
        mock_manager = MagicMock()
        mock_manager.get_runtime_context.return_value = None
        mock_manager.initialize.return_value = {"work_dir": "/test"}
        mock_manager_class.return_value = mock_manager

        ctx = run_enrich.load_runtime_context()

        assert ctx["work_dir"] == "/test"
        mock_manager.initialize.assert_called_once()


class TestResolveProjectAndWorkbook:
    """Tests for resolve_project_and_workbook function."""

    @patch("project_ref_utils.resolve_project_ref")
    def test_resolves_successfully(self, mock_resolve):
        mock_resolve.return_value = {
            "success": True,
            "config_path": "/test/config.sh",
            "workbook_path": "/test/workbook.xlsx",
        }

        config_path, workbook_path = run_enrich.resolve_project_and_workbook(
            "my_project"
        )

        assert config_path == Path("/test/config.sh")
        assert workbook_path == Path("/test/workbook.xlsx")

    @patch("project_ref_utils.resolve_project_ref")
    def test_raises_config_error_on_failure(self, mock_resolve):
        mock_resolve.return_value = {
            "success": False,
            "error": "Project not found",
        }

        with pytest.raises(run_enrich.ConfigError) as exc_info:
            run_enrich.resolve_project_and_workbook("bad_project")

        assert "Project not found" in str(exc_info.value)


class TestReadEnrichableRows:
    """Tests for read_enrichable_rows function."""

    @patch("excel_utils.read")
    def test_reads_enrichable_rows(self, mock_read, tmp_path):
        mock_read.return_value = [
            {"row_id": 1, "name": "Test", "next_action": "enrich"},
        ]

        rows = run_enrich.read_enrichable_rows(tmp_path / "test.xlsx")

        assert len(rows) == 1
        assert rows[0]["row_id"] == 1
        mock_read.assert_called_once()

    @patch("excel_utils.read")
    def test_filters_by_row_ids(self, mock_read, tmp_path):
        mock_read.return_value = [
            {"row_id": 1, "name": "Test 1", "next_action": "enrich"},
            {"row_id": 2, "name": "Test 2", "next_action": "enrich"},
            {"row_id": 3, "name": "Test 3", "next_action": "enrich"},
        ]

        rows = run_enrich.read_enrichable_rows(
            tmp_path / "test.xlsx",
            row_ids=[1, 3],
        )

        assert len(rows) == 2
        assert rows[0]["row_id"] == 1
        assert rows[1]["row_id"] == 3

    @patch("excel_utils.read")
    def test_applies_resume_from_row_id_and_limit(self, mock_read, tmp_path):
        mock_read.return_value = [
            {"row_id": 1, "name": "Test 1", "next_action": "enrich"},
            {"row_id": 2, "name": "Test 2", "next_action": "enrich"},
            {"row_id": 3, "name": "Test 3", "next_action": "enrich"},
        ]

        rows = run_enrich.read_enrichable_rows(
            tmp_path / "test.xlsx",
            resume_from_row_id=2,
            limit=1,
        )

        assert [row["row_id"] for row in rows] == [2]

    def test_rejects_negative_limit(self, tmp_path):
        with pytest.raises(run_enrich.EnrichError) as exc_info:
            run_enrich.read_enrichable_rows(tmp_path / "test.xlsx", limit=-1)

        assert "limit must be >= 0" in str(exc_info.value)


class TestEnrichSingleRow:
    """Tests for enrich_single_row function."""

    @patch("profile_enricher.enrich_profile")
    def test_successful_enrichment(self, mock_enrich):
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.enrichment_notes = "Skills: Python"
        mock_result.action_required = None
        mock_enrich.return_value = mock_result

        row = {"row_id": 1, "profile_url": "https://linkedin.com/in/test"}
        success, notes, action = run_enrich.enrich_single_row(row, "9234")

        assert success is True
        assert notes == "Skills: Python"
        assert action is None

    @patch("profile_enricher.enrich_profile")
    def test_failed_enrichment(self, mock_enrich):
        action = {"code": "browser_error", "steps": ["Fix it"]}
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.partial_result = None
        mock_result.action_required = action
        mock_enrich.return_value = mock_result

        row = {"row_id": 1, "profile_url": "https://linkedin.com/in/test"}
        success, notes, action_result = run_enrich.enrich_single_row(row, "9234")

        assert success is False
        assert action_result == action

    def test_missing_profile_url(self):
        row = {"row_id": 1, "profile_url": ""}
        success, notes, action = run_enrich.enrich_single_row(row, "9234")

        assert success is False
        assert action is not None
        assert action["code"] == "missing_profile_url"

    def test_dry_run_mode(self):
        row = {"row_id": 1, "profile_url": "https://linkedin.com/in/test"}
        success, notes, action = run_enrich.enrich_single_row(row, "9234", dry_run=True)

        assert success is True
        assert "DRY RUN" in notes
        assert action is None


class TestRunEnrichPhase:
    """Integration tests for run_enrich_phase function."""

    @patch("run_enrich.load_runtime_context")
    @patch("run_enrich.resolve_project_and_workbook")
    @patch("run_enrich.read_enrichable_rows")
    @patch("run_enrich.enrich_single_row")
    @patch("run_enrich.update_row_after_enrichment")
    def test_successful_enrichment_all_rows(
        self,
        mock_update,
        mock_enrich,
        mock_read,
        mock_resolve,
        mock_ctx,
    ):
        mock_ctx.return_value = {
            "work_dir": "/test",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_resolve.return_value = (
            Path("/test/config.sh"),
            Path("/test/workbook.xlsx"),
        )
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "https://linkedin.com/in/test",
            }
        ]
        mock_enrich.return_value = (True, "Skills: Python", None)

        result = run_enrich.run_enrich_phase("test_project")

        assert result == 0
        mock_enrich.assert_called_once()
        mock_update.assert_called_once()

    @patch("run_enrich.load_runtime_context")
    @patch("run_enrich.resolve_project_and_workbook")
    @patch("run_enrich.read_enrichable_rows")
    def test_no_enrichable_rows_returns_success(
        self,
        mock_read,
        mock_resolve,
        mock_ctx,
    ):
        mock_ctx.return_value = {"work_dir": "/test", "profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            Path("/test/config.sh"),
            Path("/test/workbook.xlsx"),
        )
        mock_read.return_value = []

        result = run_enrich.run_enrich_phase("test_project")

        assert result == 0

    @patch("run_enrich.load_runtime_context")
    @patch("run_enrich.resolve_project_and_workbook")
    @patch("run_enrich.read_enrichable_rows")
    @patch("run_enrich.enrich_single_row")
    @patch("run_enrich.update_row_after_enrichment")
    def test_passes_resume_and_limit_to_reader(
        self,
        mock_update,
        mock_enrich,
        mock_read,
        mock_resolve,
        mock_ctx,
    ):
        mock_ctx.return_value = {"work_dir": "/test", "profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            Path("/test/config.sh"),
            Path("/test/workbook.xlsx"),
        )
        mock_read.return_value = [
            {"row_id": 5, "name": "Test User", "profile_url": "https://linkedin.com/in/test"}
        ]
        mock_enrich.return_value = (True, "Skills: Python", None)

        result = run_enrich.run_enrich_phase(
            "test_project",
            resume_from_row_id=5,
            limit=1,
        )

        assert result == 0
        mock_read.assert_called_once_with(
            Path("/test/workbook.xlsx"),
            row_ids=None,
            resume_from_row_id=5,
            limit=1,
        )
        mock_update.assert_called_once()

    @patch("run_enrich.load_runtime_context")
    @patch("run_enrich.resolve_project_and_workbook")
    @patch("run_enrich.read_enrichable_rows")
    @patch("run_enrich.enrich_single_row")
    def test_browser_intervention_returns_exit_code_2(
        self,
        mock_enrich,
        mock_read,
        mock_resolve,
        mock_ctx,
    ):
        mock_ctx.return_value = {"work_dir": "/test", "profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            Path("/test/config.sh"),
            Path("/test/workbook.xlsx"),
        )
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test",
                "profile_url": "https://linkedin.com/in/test",
            },
        ]
        # Simulate browser failure that can be retried (use valid browser failure code)
        mock_enrich.return_value = (
            False,
            None,
            {
                "code": "auth_required",  # Valid browser failure code
                "summary": "LinkedIn authentication required",
                "steps": ["Log in to LinkedIn", "Retry enrichment"],
                "can_retry": True,
            },
        )

        result = run_enrich.run_enrich_phase("test_project")

        assert result == 2  # BrowserStateError exit code

    @patch("run_enrich.load_runtime_context")
    @patch("run_enrich.resolve_project_and_workbook")
    @patch("run_enrich.read_enrichable_rows")
    @patch("run_enrich.enrich_single_row")
    def test_non_retryable_failure_returns_exit_code_1(
        self,
        mock_enrich,
        mock_read,
        mock_resolve,
        mock_ctx,
    ):
        mock_ctx.return_value = {"work_dir": "/test", "profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            Path("/test/config.sh"),
            Path("/test/workbook.xlsx"),
        )
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test",
                "profile_url": "https://linkedin.com/in/test",
            },
        ]
        # Simulate failure that cannot be retried (non-browser failure)
        mock_enrich.return_value = (
            False,
            None,
            {
                "code": "invalid_profile",
                "summary": "Profile not found",
                "steps": ["Check URL"],
                "can_retry": False,
            },
        )

        result = run_enrich.run_enrich_phase("test_project")

        assert result == 1  # Regular failure exit code

    @patch("run_enrich.load_runtime_context")
    @patch("run_enrich.resolve_project_and_workbook")
    @patch("run_enrich.read_enrichable_rows")
    @patch("run_enrich.enrich_single_row")
    def test_non_retryable_browser_failure_returns_exit_code_2(
        self,
        mock_enrich,
        mock_read,
        mock_resolve,
        mock_ctx,
    ):
        """Browser/manual failures must return exit 2 regardless of can_retry.

        This tests the fix for: browser/manual failures are keyed off the failure
        code set itself, not retryability. agent_browser_not_found has can_retry=False
        but must still result in exit code 2.
        """
        mock_ctx.return_value = {"work_dir": "/test", "profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            Path("/test/config.sh"),
            Path("/test/workbook.xlsx"),
        )
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test",
                "profile_url": "https://linkedin.com/in/test",
            },
        ]
        # Simulate agent_browser_not_found (browser failure with can_retry=False)
        mock_enrich.return_value = (
            False,
            None,
            {
                "code": "agent_browser_not_found",
                "summary": "agent-browser command not found in PATH",
                "steps": ["Install agent-browser", "Retry"],
                "can_retry": False,  # Non-retryable but still browser-related
            },
        )

        result = run_enrich.run_enrich_phase("test_project")

        assert result == 2  # Browser intervention exit code, NOT 1

    @patch("run_enrich.load_runtime_context")
    @patch("run_enrich.resolve_project_and_workbook")
    @patch("run_enrich.read_enrichable_rows")
    @patch("run_enrich.enrich_single_row")
    def test_missing_profile_url_returns_exit_code_1_not_2(
        self,
        mock_enrich,
        mock_read,
        mock_resolve,
        mock_ctx,
    ):
        """Data validation failures (missing_profile_url) should return exit 1, not exit 2.

        Exit code 2 is reserved for browser/manual intervention only.
        Missing profile_url is a data validation issue, not a browser issue.
        """
        mock_ctx.return_value = {"work_dir": "/test", "profile": {"CDP_PORT": "9234"}}
        mock_resolve.return_value = (
            Path("/test/config.sh"),
            Path("/test/workbook.xlsx"),
        )
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test",
                "profile_url": "",  # Empty profile URL
            },
        ]
        # Simulate missing_profile_url failure (can_retry=False, not a browser code)
        mock_enrich.return_value = (
            False,
            None,
            {
                "code": "missing_profile_url",
                "summary": "Row 1 has no profile_url",
                "steps": ["Add profile_url to candidate row", "Retry enrichment"],
                "can_retry": False,  # Data issue, not transient browser issue
            },
        )

        result = run_enrich.run_enrich_phase("test_project")

        assert result == 1  # Regular failure, NOT exit 2 (browser intervention)

    @patch("run_enrich.load_runtime_context")
    def test_config_error_returns_exit_code_3(self, mock_ctx):
        mock_ctx.side_effect = run_enrich.ConfigError("Test config error")

        result = run_enrich.run_enrich_phase("test_project")

        assert result == 3


# Import pytest for exception testing
try:
    import pytest
except ImportError:

    class pytest:
        @staticmethod
        def raises(exc_type):
            class ContextManager:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_val, exc_tb):
                    if exc_val is None:
                        raise AssertionError(
                            f"Expected {exc_type} but no exception raised"
                        )
                    if not isinstance(exc_val, exc_type):
                        return False
                    self.value = exc_val
                    return True

            return ContextManager()


if __name__ == "__main__":
    try:
        import pytest

        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not available, running basic smoke tests...")
        test_class = TestEnrichErrorClasses()
        test_class.test_enrich_error_default_exit_code()
        test_class.test_browser_state_error_with_action_required()
        print("Basic tests passed")
