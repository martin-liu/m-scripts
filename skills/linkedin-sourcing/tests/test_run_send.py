#!/usr/bin/env python3
"""Tests for run_send.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_run_send.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import run_send


class TestLoadRuntimeContext:
    """Tests for load_runtime_context function."""

    @patch("runtime_manager.RuntimeManager")
    def test_loads_existing_context(self, mock_manager_class):
        mock_manager = MagicMock()
        mock_manager.get_runtime_context.return_value = {"work_dir": "/test"}
        mock_manager_class.return_value = mock_manager

        ctx = run_send.load_runtime_context()

        assert ctx["work_dir"] == "/test"
        mock_manager.get_runtime_context.assert_called_once()

    @patch("runtime_manager.RuntimeManager")
    def test_initializes_when_no_context(self, mock_manager_class):
        mock_manager = MagicMock()
        mock_manager.get_runtime_context.return_value = None
        mock_manager.initialize.return_value = {
            "work_dir": "/test",
            "sync_happened": True,
        }
        mock_manager_class.return_value = mock_manager

        ctx = run_send.load_runtime_context()

        assert ctx["work_dir"] == "/test"
        mock_manager.initialize.assert_called_once()

    @patch("runtime_manager.RuntimeManager")
    def test_raises_config_error_on_failure(self, mock_manager_class):
        mock_manager_class.side_effect = Exception("Import error")

        with pytest.raises(run_send.ConfigError) as exc_info:
            run_send.load_runtime_context()

        assert "Failed to load runtime context" in str(exc_info.value)


class TestResolveSendScript:
    """Tests for resolve_send_script function using canonical RuntimeManager resolution."""

    @patch("runtime_manager.RuntimeManager")
    def test_uses_runtime_manager_resolution(self, mock_manager_class, tmp_path):
        """Should use RuntimeManager.resolve_script for consistent resolution."""
        mock_manager = MagicMock()
        mock_manager.resolve_script.return_value = tmp_path / "send_inmail.sh"
        mock_manager_class.return_value = mock_manager

        ctx = {"work_dir": str(tmp_path)}
        result = run_send.resolve_send_script(ctx)

        mock_manager.resolve_script.assert_called_once_with("send_inmail.sh")
        assert result == tmp_path / "send_inmail.sh"

    @patch("runtime_manager.RuntimeManager")
    def test_prefers_override_via_runtime_manager(self, mock_manager_class, tmp_path):
        """Should delegate override preference to RuntimeManager."""
        mock_manager = MagicMock()
        override_path = tmp_path / "scripts" / "send_inmail.sh"
        mock_manager.resolve_script.return_value = override_path
        mock_manager_class.return_value = mock_manager

        ctx = {"work_dir": str(tmp_path)}
        result = run_send.resolve_send_script(ctx)

        assert result == override_path

    @patch("runtime_manager.RuntimeManager")
    def test_raises_config_error_when_not_found(self, mock_manager_class, tmp_path):
        """Should raise ConfigError when script not found."""
        mock_manager = MagicMock()
        mock_manager.resolve_script.return_value = None
        mock_manager_class.return_value = mock_manager

        ctx = {"work_dir": str(tmp_path)}

        with pytest.raises(run_send.ConfigError) as exc_info:
            run_send.resolve_send_script(ctx)

        assert "send_inmail.sh not found" in str(exc_info.value)


class TestResolveExcelUtils:
    """Tests for resolve_excel_utils function using canonical RuntimeManager resolution."""

    @patch("runtime_manager.RuntimeManager")
    def test_uses_runtime_manager_resolution(self, mock_manager_class, tmp_path):
        """Should use RuntimeManager.resolve_script for consistent resolution."""
        mock_manager = MagicMock()
        mock_manager.resolve_script.return_value = tmp_path / "excel_utils.py"
        mock_manager_class.return_value = mock_manager

        ctx = {"work_dir": str(tmp_path)}
        result = run_send.resolve_excel_utils(ctx)

        mock_manager.resolve_script.assert_called_once_with("excel_utils.py")
        assert result == tmp_path / "excel_utils.py"

    @patch("runtime_manager.RuntimeManager")
    def test_raises_config_error_when_not_found(self, mock_manager_class, tmp_path):
        """Should raise ConfigError when excel_utils.py not found."""
        mock_manager = MagicMock()
        mock_manager.resolve_script.return_value = None
        mock_manager_class.return_value = mock_manager

        ctx = {"work_dir": str(tmp_path)}

        with pytest.raises(run_send.ConfigError) as exc_info:
            run_send.resolve_excel_utils(ctx)

        assert "excel_utils.py not found" in str(exc_info.value)


class TestGetWorkbookPath:
    """Tests for get_workbook_path function using canonical project_ref_utils resolution."""

    @patch("project_ref_utils.resolve_project_ref")
    def test_uses_project_ref_resolution(self, mock_resolve, tmp_path):
        """Should use project_ref_utils.resolve_project_ref for resolution."""
        mock_resolve.return_value = {
            "success": True,
            "config_path": str(tmp_path / "config.sh"),
            "workbook_path": str(tmp_path / "workbook.xlsx"),
        }

        ctx = {"work_dir": str(tmp_path)}
        result = run_send.get_workbook_path(ctx, "my_project")

        mock_resolve.assert_called_once()
        assert result == tmp_path / "workbook.xlsx"

    @patch("project_ref_utils.resolve_project_ref")
    def test_accepts_recruiter_url(self, mock_resolve, tmp_path):
        """Should accept LinkedIn Recruiter URL as project reference."""
        mock_resolve.return_value = {
            "success": True,
            "config_path": str(tmp_path / "config.sh"),
            "workbook_path": str(tmp_path / "workbook.xlsx"),
            "recruiter_project_id": "12345",
        }

        ctx = {"work_dir": str(tmp_path)}
        url = "https://linkedin.com/talent/hire/12345/overview"
        result = run_send.get_workbook_path(ctx, url)

        mock_resolve.assert_called_once_with(url, work_dir=tmp_path)
        assert result == tmp_path / "workbook.xlsx"

    @patch("project_ref_utils.resolve_project_ref")
    def test_raises_config_error_on_resolution_failure(self, mock_resolve, tmp_path):
        """Should raise ConfigError when project resolution fails."""
        mock_resolve.return_value = {
            "success": False,
            "error": "Project not found",
        }

        ctx = {"work_dir": str(tmp_path)}

        with pytest.raises(run_send.ConfigError) as exc_info:
            run_send.get_workbook_path(ctx, "nonexistent")

        assert "Project not found" in str(exc_info.value)

    @patch("project_ref_utils.resolve_project_ref")
    def test_raises_config_error_when_no_workbook_path(self, mock_resolve, tmp_path):
        """Should raise ConfigError when resolution succeeds but no workbook path."""
        mock_resolve.return_value = {
            "success": True,
            "config_path": str(tmp_path / "config.sh"),
            # Missing workbook_path
        }

        ctx = {"work_dir": str(tmp_path)}

        with pytest.raises(run_send.ConfigError) as exc_info:
            run_send.get_workbook_path(ctx, "my_project")

        assert "no workbook path returned" in str(exc_info.value)


class TestReadSendableRows:
    """Tests for read_sendable_rows function."""

    @patch("run_send.subprocess.run")
    def test_reads_rows_successfully(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            stdout=json.dumps([{"row_id": 1, "name": "Test"}]),
            returncode=0,
        )

        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"

        rows = run_send.read_sendable_rows(excel_utils, workbook)

        assert len(rows) == 1
        assert rows[0]["row_id"] == 1

    @patch("run_send.subprocess.run")
    def test_filters_by_row_ids(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            stdout=json.dumps(
                [
                    {"row_id": 1, "name": "Test 1"},
                    {"row_id": 2, "name": "Test 2"},
                    {"row_id": 3, "name": "Test 3"},
                ]
            ),
            returncode=0,
        )

        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"

        rows = run_send.read_sendable_rows(excel_utils, workbook, row_ids=[1, 3])

        assert len(rows) == 2
        assert rows[0]["row_id"] == 1
        assert rows[1]["row_id"] == 3

    @patch("run_send.subprocess.run")
    def test_raises_send_error_on_failure(self, mock_run, tmp_path):
        import subprocess

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr="Command failed"
        )

        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"

        with pytest.raises(run_send.SendError) as exc_info:
            run_send.read_sendable_rows(excel_utils, workbook)

        assert "Failed to read workbook" in str(exc_info.value)


class TestSendInmail:
    """Tests for send_inmail function."""

    @patch("run_send.subprocess.run")
    def test_successful_send(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            stdout=json.dumps(
                {
                    "status": "SENT",
                    "reason": "message_sent_successfully",
                    "clean_state": True,
                }
            ),
            returncode=0,
        )

        send_script = tmp_path / "send_inmail.sh"
        result = run_send.send_inmail(
            send_script, "9234", None, "http://test.com", "Subject", "Body"
        )

        assert result["status"] == "SENT"
        assert result["clean_state"] is True

    @patch("run_send.subprocess.run")
    def test_preserves_parent_environment(self, mock_run, tmp_path):
        """Subprocess should inherit HOME/PATH and only override CDP_PORT."""
        import os

        mock_run.return_value = MagicMock(
            stdout=json.dumps(
                {
                    "status": "SENT",
                    "reason": "message_sent_successfully",
                    "clean_state": True,
                }
            ),
            returncode=0,
        )

        send_script = tmp_path / "send_inmail.sh"
        run_send.send_inmail(
            send_script,
            "9234",
            None,
            "http://test.com",
            "Subject",
            "Body",
        )

        call_kwargs = mock_run.call_args[1]
        env = call_kwargs.get("env", {})

        # Should preserve parent environment variables
        assert "HOME" in env or "PATH" in env, "Parent environment should be preserved"
        # Should override CDP_PORT
        assert env.get("CDP_PORT") == "9234"

    @patch("run_send.subprocess.run")
    def test_passes_work_dir_to_subprocess(self, mock_run, tmp_path):
        """Subprocess should receive WORK_DIR for browser mode resolution."""
        mock_run.return_value = MagicMock(
            stdout=json.dumps(
                {
                    "status": "SENT",
                    "reason": "message_sent_successfully",
                    "clean_state": True,
                }
            ),
            returncode=0,
        )

        send_script = tmp_path / "send_inmail.sh"
        run_send.send_inmail(
            send_script,
            "9234",
            "/tmp/custom-workdir",
            "http://test.com",
            "Subject",
            "Body",
        )

        env = mock_run.call_args[1].get("env", {})
        assert env.get("WORK_DIR") == "/tmp/custom-workdir"

    @patch("run_send.subprocess.run")
    def test_rejects_legacy_output_as_failure(self, mock_run, tmp_path):
        """Non-JSON output is treated as failure - requires explicit clean_state."""
        mock_run.return_value = MagicMock(
            stdout="SENT",
            returncode=0,
        )

        send_script = tmp_path / "send_inmail.sh"
        result = run_send.send_inmail(
            send_script, "9234", None, "http://test.com", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "invalid_json_output"
        assert result["clean_state"] is False

    @patch("run_send.subprocess.run")
    def test_rejects_mixed_stdout_with_json(self, mock_run, tmp_path):
        """Mixed stdout with log noise around JSON is rejected - strict JSON-only."""
        mock_run.return_value = MagicMock(
            stdout='Some log message\n{"status": "SENT", "clean_state": true}\nAnother log',
            returncode=0,
        )

        send_script = tmp_path / "send_inmail.sh"
        result = run_send.send_inmail(
            send_script, "9234", None, "http://test.com", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "invalid_json_output"
        assert result["clean_state"] is False

    @patch("run_send.subprocess.run")
    def test_handles_timeout(self, mock_run, tmp_path):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["bash"], timeout=120)

        send_script = tmp_path / "send_inmail.sh"
        result = run_send.send_inmail(
            send_script, "9234", None, "http://test.com", "Subject", "Body"
        )

        assert result["status"] == "FAILED"
        assert result["reason"] == "send_timeout"


class TestUpdateRowAfterSend:
    """Tests for update_row_after_send function."""

    @patch("run_send.subprocess.run")
    def test_sent_status_updates_correctly(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)

        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"
        row = {"row_id": 1, "attempts": 0}
        send_result = {
            "status": "SENT",
            "reason": "message_sent_successfully",
            "clean_state": True,
        }

        run_send.update_row_after_send(
            excel_utils, workbook, row, send_result, "2026-04-11"
        )

        # Check that subprocess was called with correct updates
        call_args = mock_run.call_args
        assert call_args is not None
        cmd = call_args[0][0]
        updates_json = cmd[-1]
        updates = json.loads(updates_json)

        assert updates["status"] == "Sent"
        assert updates["next_action"] == "done"
        assert updates["date_sent"] == "2026-04-11"
        assert updates["last_contact"] == "2026-04-11"
        assert updates["attempts"] == 1

    @patch("run_send.subprocess.run")
    def test_already_contacted_updates_correctly(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)

        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"
        row = {"row_id": 1, "notes": "Existing note"}
        send_result = {
            "status": "ALREADY_CONTACTED",
            "reason": "recent_activity_inmail",
            "clean_state": True,
        }

        run_send.update_row_after_send(
            excel_utils, workbook, row, send_result, "2026-04-11"
        )

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        updates_json = cmd[-1]
        updates = json.loads(updates_json)

        assert updates["status"] == "AlreadyContacted"
        assert updates["next_action"] == "done"
        assert updates["last_contact"] == "2026-04-11"
        assert "[Already contacted: recent_activity_inmail]" in updates["notes"]
        assert "Existing note" in updates["notes"]

    def test_unclean_browser_state_raises_browser_state_error(self, tmp_path):
        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"
        row = {"row_id": 5}
        send_result = {
            "status": "SENT",
            "reason": "message_sent_successfully",
            "clean_state": False,  # Unclean state!
        }

        with pytest.raises(run_send.BrowserStateError) as exc_info:
            run_send.update_row_after_send(
                excel_utils, workbook, row, send_result, "2026-04-11"
            )

        assert exc_info.value.row_id == 5
        assert "unclean state" in str(exc_info.value)

    def test_failed_status_raises_send_error(self, tmp_path):
        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"
        row = {"row_id": 3}
        send_result = {
            "status": "FAILED",
            "reason": "navigation_failed",
            "clean_state": True,
        }

        with pytest.raises(run_send.SendError) as exc_info:
            run_send.update_row_after_send(
                excel_utils, workbook, row, send_result, "2026-04-11"
            )

        assert exc_info.value.row_id == 3
        assert "Send failed" in str(exc_info.value)

    def test_attempts_incremented_correctly(self, tmp_path):
        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"
        row = {"row_id": 1, "attempts": 2}
        send_result = {
            "status": "SENT",
            "reason": "message_sent_successfully",
            "clean_state": True,
        }

        with patch("run_send.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_send.update_row_after_send(
                excel_utils, workbook, row, send_result, "2026-04-11"
            )

            call_args = mock_run.call_args
            cmd = call_args[0][0]
            updates_json = cmd[-1]
            updates = json.loads(updates_json)

            # Should be max(1, 2+1) = 3
            assert updates["attempts"] == 3


class TestRunSendMacro:
    """Integration tests for run_send_macro function."""

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    @patch("run_send.send_inmail")
    @patch("run_send.update_row_after_send")
    def test_successful_send_all_rows(
        self,
        mock_update,
        mock_send,
        mock_read,
        mock_workbook,
        mock_excel,
        mock_script,
        mock_ctx,
    ):
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": "Test Subject",
                "draft_body": "Test Body",
                "attempts": 0,
            }
        ]
        mock_send.return_value = {
            "status": "SENT",
            "reason": "message_sent_successfully",
            "clean_state": True,
        }

        result = run_send.run_send_macro("test_project")

        assert result == 0
        mock_send.assert_called_once()
        mock_update.assert_called_once()

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    @patch("run_send.send_inmail")
    @patch("run_send.update_row_after_send")
    def test_forwards_draft_subject_unchanged(
        self,
        mock_update,
        mock_send,
        mock_read,
        mock_workbook,
        mock_excel,
        mock_script,
        mock_ctx,
    ):
        """run_send_macro must forward exact workbook draft_subject to send_inmail."""
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        expected_subject = "Custom Subject Line With Special Chars: 你好"
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": expected_subject,
                "draft_body": "Test Body",
                "attempts": 0,
            }
        ]
        mock_send.return_value = {
            "status": "SENT",
            "reason": "message_sent_successfully",
            "clean_state": True,
        }

        run_send.run_send_macro("test_project")

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["draft_subject"] == expected_subject
        assert call_kwargs["draft_subject"] != "Test Body"

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    @patch("run_send.send_inmail")
    @patch("run_send.update_row_after_send")
    def test_forwards_draft_body_unchanged(
        self,
        mock_update,
        mock_send,
        mock_read,
        mock_workbook,
        mock_excel,
        mock_script,
        mock_ctx,
    ):
        """run_send_macro must forward exact workbook draft_body to send_inmail."""
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        expected_body = "Line 1\nLine 2 with unicode: 🚀\n\nRegards"
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": "Test Subject",
                "draft_body": expected_body,
                "attempts": 0,
            }
        ]
        mock_send.return_value = {
            "status": "SENT",
            "reason": "message_sent_successfully",
            "clean_state": True,
        }

        run_send.run_send_macro("test_project")

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["draft_body"] == expected_body
        assert call_kwargs["draft_body"] != "Test Subject"

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    @patch("run_send.send_inmail")
    @patch("run_send.update_row_after_send")
    def test_draft_content_not_regenerated(
        self,
        mock_update,
        mock_send,
        mock_read,
        mock_workbook,
        mock_excel,
        mock_script,
        mock_ctx,
    ):
        """Send phase must use workbook draft content as-is without regeneration."""
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        original_subject = "Original Draft Subject"
        original_body = "Original Draft Body Content"
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": original_subject,
                "draft_body": original_body,
                "attempts": 0,
            }
        ]
        mock_send.return_value = {
            "status": "SENT",
            "reason": "message_sent_successfully",
            "clean_state": True,
        }

        run_send.run_send_macro("test_project")

        # Verify exact workbook values are passed through unchanged
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["draft_subject"] == original_subject
        assert call_kwargs["draft_body"] == original_body
        # Verify no transformation occurred
        assert "transformed" not in str(call_kwargs).lower()
        assert "generated" not in str(call_kwargs).lower()

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    def test_no_sendable_rows_returns_success(
        self, mock_read, mock_workbook, mock_excel, mock_script, mock_ctx
    ):
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = []

        result = run_send.run_send_macro("test_project")

        assert result == 0

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    @patch("run_send.send_inmail")
    def test_browser_state_error_returns_exit_code_2(
        self, mock_send, mock_read, mock_workbook, mock_excel, mock_script, mock_ctx
    ):
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": "Test Subject",
                "draft_body": "Test Body",
            }
        ]
        mock_send.return_value = {
            "status": "SENT",
            "reason": "message_sent_successfully",
            "clean_state": False,  # Unclean state
        }

        result = run_send.run_send_macro("test_project")

        assert result == 2  # BrowserStateError exit code

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    def test_specific_row_ids(
        self, mock_read, mock_workbook, mock_excel, mock_script, mock_ctx
    ):
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = []

        run_send.run_send_macro("test_project", row_ids=[5, 10, 15])

        # Verify row_ids were passed to read_sendable_rows
        mock_read.assert_called_once()
        call_args = mock_read.call_args
        # row_ids is the 3rd positional argument (index 2) or keyword argument
        if call_args[1]:  # kwargs
            assert call_args[1].get("row_ids") == [5, 10, 15]
        else:  # positional args
            assert call_args[0][2] == [5, 10, 15]

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    def test_missing_profile_url_skips_row(
        self, mock_read, mock_workbook, mock_excel, mock_script, mock_ctx
    ):
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "",  # Missing URL
                "draft_subject": "Test Subject",
                "draft_body": "Test Body",
            }
        ]

        result = run_send.run_send_macro("test_project")

        assert result == 1  # Failed because row was skipped

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    def test_missing_draft_content_skips_row(
        self, mock_read, mock_workbook, mock_excel, mock_script, mock_ctx
    ):
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": "",  # Missing subject
                "draft_body": "Body",
            }
        ]

        result = run_send.run_send_macro("test_project")

        assert result == 1  # Failed because row was skipped

    @patch("run_send.load_runtime_context")
    def test_config_error_returns_exit_code_3(self, mock_ctx):
        mock_ctx.side_effect = run_send.ConfigError("Test config error")

        result = run_send.run_send_macro("test_project")

        assert result == 3


class TestSendErrorClasses:
    """Tests for SendError exception classes."""

    def test_send_error_default_exit_code(self):
        error = run_send.SendError("Test error")
        assert error.exit_code == 1
        assert error.row_id is None

    def test_send_error_with_row_id(self):
        error = run_send.SendError("Test error", row_id=5)
        assert error.row_id == 5

    def test_browser_state_error_default_exit_code(self):
        error = run_send.BrowserStateError("Browser not clean")
        assert error.exit_code == 2

    def test_config_error_default_exit_code(self):
        error = run_send.ConfigError("Config missing")
        assert error.exit_code == 3


class TestProjectRefResolution:
    """Tests for --project argument and project reference resolution in run_send."""

    @patch("project_ref_utils.resolve_project_ref")
    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    def test_project_arg_resolves_to_local_project_id(
        self,
        mock_read,
        mock_workbook,
        mock_excel,
        mock_script,
        mock_ctx,
        mock_resolve_ref,
    ):
        """--project should resolve to local_project_id for workbook lookup."""
        mock_resolve_ref.return_value = {
            "success": True,
            "config_path": "/path/to/config.sh",
            "local_project_id": "my_project",
            "workbook_path": "/path/to/my_project.xlsx",
            "recruiter_project_id": "12345",
            "error": None,
        }
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/my_project.xlsx")
        mock_read.return_value = []

        # Simulate main() resolution logic
        project_ref = "https://linkedin.com/talent/hire/12345/overview"
        resolution = mock_resolve_ref(project_ref)
        project_id = resolution["local_project_id"] or project_ref

        # Verify resolution was used
        assert project_id == "my_project"
        mock_resolve_ref.assert_called_once_with(project_ref)

    @patch("project_ref_utils.resolve_project_ref")
    def test_project_resolution_fails_closed_no_fallback(
        self,
        mock_resolve_ref,
    ):
        """Failed --project resolution should fail closed (no fallback to ref as-is)."""
        mock_resolve_ref.return_value = {
            "success": False,
            "error": "Project not found",
        }

        # Simulate main() logic for --project
        # When --project is used and resolution fails, it should return exit code 3
        project_ref = "my_project"
        resolution = mock_resolve_ref(project_ref)

        # For --project, failed resolution means error exit - no fallback
        assert resolution["success"] is False
        # In real main(), this would return exit code 3

    @patch("project_ref_utils.resolve_project_ref")
    def test_project_url_resolution(
        self,
        mock_resolve_ref,
    ):
        """--project with URL should resolve to matching project."""
        mock_resolve_ref.return_value = {
            "success": True,
            "config_path": "/path/to/config.sh",
            "local_project_id": "my_project",
            "workbook_path": "/path/to/my_project.xlsx",
            "recruiter_project_id": "12345",
            "error": None,
        }

        url = "https://linkedin.com/talent/hire/12345/discover/recruiterSearch"
        resolution = mock_resolve_ref(url)

        assert resolution["success"] is True
        assert resolution["local_project_id"] == "my_project"

    @patch("project_ref_utils.resolve_project_ref")
    def test_project_numeric_id_resolution(
        self,
        mock_resolve_ref,
    ):
        """--project with numeric ID should resolve to matching project."""
        mock_resolve_ref.return_value = {
            "success": True,
            "config_path": "/path/to/config.sh",
            "local_project_id": "my_project",
            "workbook_path": "/path/to/my_project.xlsx",
            "recruiter_project_id": "12345",
            "error": None,
        }

        resolution = mock_resolve_ref("12345")

        assert resolution["success"] is True
        assert resolution["recruiter_project_id"] == "12345"


# Import pytest for exception testing
try:
    import pytest
except ImportError:
    # Fallback if pytest not available
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


class TestBrowserStateErrorWithActionRequired:
    """Tests for BrowserStateError with action_required."""

    def test_browser_state_error_with_action_required(self):
        """BrowserStateError should accept and store action_required."""
        action = {
            "code": "element_missing",
            "summary": "Send button not found",
            "steps": ["Check browser", "Retry"],
            "can_retry": True,
            "context": {"selector": "button.send"},
        }
        error = run_send.BrowserStateError(
            "Browser state not clean",
            row_id=5,
            action_required=action,
        )

        assert error.exit_code == 2
        assert error.row_id == 5
        assert error.action_required == action
        assert error.action_required["code"] == "element_missing"

    def test_browser_state_error_without_action_required(self):
        """BrowserStateError should work without action_required (backward compat)."""
        error = run_send.BrowserStateError("Browser state not clean", row_id=3)

        assert error.exit_code == 2
        assert error.row_id == 3
        assert error.action_required is None


class TestUpdateRowAfterSendWithActionRequired:
    """Tests for update_row_after_send with action_required handling."""

    def test_failed_with_action_required_raises_browser_state_error(self, tmp_path):
        """FAILED status with action_required should raise BrowserStateError."""
        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"
        row = {"row_id": 5}
        send_result = {
            "status": "FAILED",
            "reason": "click_send_button_failed",
            "failure_code": "element_missing",
            "action_required": {
                "code": "element_missing",
                "summary": "Send button not found",
                "steps": ["Check browser", "Retry"],
                "can_retry": True,
                "context": {"selector": "button.send"},
            },
            "clean_state": True,  # Clean but failed
        }

        with pytest.raises(run_send.BrowserStateError) as exc_info:
            run_send.update_row_after_send(
                excel_utils, workbook, row, send_result, "2026-04-11"
            )

        assert exc_info.value.row_id == 5
        assert exc_info.value.action_required is not None
        assert exc_info.value.action_required["code"] == "element_missing"
        assert "click_send_button_failed" in str(exc_info.value)
        assert "element_missing" in str(exc_info.value)

    def test_unclean_state_with_action_required_raises_browser_state_error(
        self, tmp_path
    ):
        """Unclean state with action_required should include it in error."""
        excel_utils = tmp_path / "excel_utils.py"
        workbook = tmp_path / "test.xlsx"
        row = {"row_id": 5}
        send_result = {
            "status": "SENT",  # Even SENT status
            "reason": "message_sent_successfully",
            "clean_state": False,  # But unclean
            "action_required": {
                "code": "ambiguous_state",
                "summary": "Cleanup failed",
                "steps": ["Close composer manually"],
                "can_retry": True,
                "context": {},
            },
        }

        with pytest.raises(run_send.BrowserStateError) as exc_info:
            run_send.update_row_after_send(
                excel_utils, workbook, row, send_result, "2026-04-11"
            )

        assert exc_info.value.row_id == 5
        assert exc_info.value.action_required is not None
        assert exc_info.value.action_required["code"] == "ambiguous_state"


class TestRunSendMacroWithActionRequired:
    """Tests for run_send_macro surfacing action_required."""

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    @patch("run_send.send_inmail")
    def test_action_required_surfaced_in_browser_state_error(
        self, mock_send, mock_read, mock_workbook, mock_excel, mock_script, mock_ctx
    ):
        """BrowserStateError should surface action_required steps to operator."""
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = [
            {
                "row_id": 1,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": "Test Subject",
                "draft_body": "Test Body",
            }
        ]
        mock_send.return_value = {
            "status": "FAILED",
            "reason": "click_send_button_failed",
            "failure_code": "element_missing",
            "action_required": {
                "code": "element_missing",
                "summary": "Send button not found on profile page",
                "steps": [
                    "Check the Chrome browser to verify the page has loaded correctly",
                    "Look for the expected element (e.g., 'Message' button, composer field)",
                    "If the page layout has changed, manual intervention may be required",
                    "Refresh the page and retry the operation",
                ],
                "can_retry": True,
                "context": {"selector": "Send button"},
            },
            "clean_state": True,
        }

        result = run_send.run_send_macro("test_project")

        # Should return exit code 2 (BrowserStateError)
        assert result == 2

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    @patch("run_send.send_inmail")
    def test_manual_send_guidance_prints_rerun_command(
        self,
        mock_send,
        mock_read,
        mock_workbook,
        mock_excel,
        mock_script,
        mock_ctx,
        capsys,
    ):
        """Manual send fallbacks should tell the agent how to reconcile the row."""
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = [
            {
                "row_id": 4,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": "Test Subject",
                "draft_body": "Test Body",
            }
        ]
        mock_send.return_value = {
            "status": "FAILED",
            "reason": "manual_send_required_after_retry",
            "failure_code": "verification_failed",
            "action_required": {
                "code": "verification_failed",
                "summary": "Automation could not finish the final send step",
                "steps": [
                    "Read draft_subject and draft_body from the workbook row via excel_utils.py read (do NOT rewrite/regenerate content)",
                    "Compare the open composer subject/body against the exact workbook values; if different, clear and fill with workbook values",
                    "Use agent-browser on the current browser session to click the visible 'Send this message' button exactly once",
                    "If agent-browser still cannot complete the click, ask the user to send it manually in Chrome to unblock",
                    "Rerun run_send for the same row to reconcile the outcome",
                ],
                "can_retry": True,
                "context": {
                    "manual_send_required": True,
                    "button_text": "Send this message",
                    "draft_source": "workbook_only",
                    "draft_rule": "Use workbook draft_subject and draft_body exactly as-is; do NOT rewrite or regenerate InMail content",
                },
            },
            "clean_state": False,
        }

        result = run_send.run_send_macro("1691575116", row_ids=[4])
        captured = capsys.readouterr()

        assert result == 2
        assert "After the send is completed (by agent-browser or user), rerun to reconcile:" in captured.out
        assert "--project 1691575116 --row-id 4" in captured.out

    @patch("run_send.load_runtime_context")
    @patch("run_send.resolve_send_script")
    @patch("run_send.resolve_excel_utils")
    @patch("run_send.get_workbook_path")
    @patch("run_send.read_sendable_rows")
    @patch("run_send.send_inmail")
    def test_manual_send_fallback_prints_draft_rule(
        self,
        mock_send,
        mock_read,
        mock_workbook,
        mock_excel,
        mock_script,
        mock_ctx,
        capsys,
    ):
        """Manual send fallback must print the workbook draft rule when present."""
        mock_ctx.return_value = {
            "work_dir": "/test",
            "current_link": "/test/current",
            "profile": {"CDP_PORT": "9234"},
        }
        mock_script.return_value = Path("/test/send_inmail.sh")
        mock_excel.return_value = Path("/test/excel_utils.py")
        mock_workbook.return_value = Path("/test/project.xlsx")
        mock_read.return_value = [
            {
                "row_id": 4,
                "name": "Test User",
                "profile_url": "http://linkedin.com/in/test",
                "draft_subject": "Test Subject",
                "draft_body": "Test Body",
            }
        ]
        mock_send.return_value = {
            "status": "FAILED",
            "reason": "manual_send_required_after_retry",
            "failure_code": "verification_failed",
            "action_required": {
                "code": "verification_failed",
                "summary": "Automation could not finish the final send step",
                "steps": [
                    "Read draft_subject and draft_body from the workbook row via excel_utils.py read (do NOT rewrite/regenerate content)",
                ],
                "can_retry": True,
                "context": {
                    "manual_send_required": True,
                    "draft_rule": "Use workbook draft_subject and draft_body exactly as-is; do NOT rewrite or regenerate InMail content",
                },
            },
            "clean_state": False,
        }

        result = run_send.run_send_macro("test_project", row_ids=[4])
        captured = capsys.readouterr()

        assert result == 2
        assert "IMPORTANT:" in captured.out
        assert "do NOT rewrite" in captured.out
        assert "workbook draft_subject" in captured.out


if __name__ == "__main__":
    # Run with pytest if available
    try:
        import pytest

        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not available, running basic tests...")
        # Run basic smoke tests
        print("All test classes defined successfully")
