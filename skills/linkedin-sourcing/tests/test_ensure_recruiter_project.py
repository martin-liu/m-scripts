#!/usr/bin/env python3
"""Tests for ensure_recruiter_project.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_ensure_recruiter_project.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch, call, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import ensure_recruiter_project as erp


class TestParseArgs:
    """Tests for argument parsing."""

    def test_requires_project_name(self):
        """Should require --project-name argument."""
        with patch.object(sys, "argv", ["script"]):
            try:
                erp.parse_args()
                assert False, "Should have raised SystemExit"
            except SystemExit as e:
                assert e.code != 0

    def test_accepts_project_name(self):
        """Should accept --project-name argument."""
        with patch.object(sys, "argv", ["script", "--project-name", "Test Project"]):
            args = erp.parse_args()
            assert args.project_name == "Test Project"

    def test_accepts_all_arguments(self):
        """Should accept all optional arguments."""
        argv = [
            "script",
            "--project-name",
            "SoC Engineer Search",
            "--description",
            "Hardware design role",
            "--cdp-port",
            "9231",
        ]
        with patch.object(sys, "argv", argv):
            args = erp.parse_args()
            assert args.project_name == "SoC Engineer Search"
            assert args.description == "Hardware design role"
            assert args.cdp_port == "9231"

    def test_uses_defaults(self):
        """Should use default values for optional args."""
        with patch.object(sys, "argv", ["script", "--project-name", "Test"]):
            args = erp.parse_args()
            assert args.cdp_port == "9230"
            assert args.description == ""


class TestRunBrowserCommand:
    """Tests for browser command execution."""

    @patch("ensure_recruiter_project._run_browser_command")
    def test_successful_command(self, mock_run_browser):
        """Should parse successful command output."""
        mock_run_browser.return_value = {
            "stdout": '{"found": true, "url": "https://example.com"}',
            "stderr": "",
            "returncode": 0,
            "parsed": {"found": True, "url": "https://example.com"},
            "error": None,
            "dialog_info": None,
            "timed_out": False,
        }

        result = erp.run_browser_command("9230", "eval", "some_js")

        assert result["found"] is True
        assert result["url"] == "https://example.com"

    @patch("ensure_recruiter_project._run_browser_command")
    def test_double_encoded_json(self, mock_run_browser):
        """Should handle double-encoded JSON from agent-browser."""
        mock_run_browser.return_value = {
            "stdout": '"{\\"found\\": true}"',
            "stderr": "",
            "returncode": 0,
            "parsed": {"found": True},
            "error": None,
            "dialog_info": None,
            "timed_out": False,
        }

        result = erp.run_browser_command("9230", "eval", "some_js")

        assert result["found"] is True

    @patch("ensure_recruiter_project._run_browser_command")
    def test_empty_output(self, mock_run_browser):
        """Should handle empty output gracefully."""
        mock_run_browser.return_value = {
            "stdout": "",
            "stderr": "error",
            "returncode": 0,
            "parsed": None,
            "error": None,
            "dialog_info": None,
            "timed_out": False,
        }

        result = erp.run_browser_command("9230", "eval", "some_js")

        assert "error" in result

    @patch("ensure_recruiter_project._run_browser_command")
    def test_timeout(self, mock_run_browser):
        """Should handle timeout gracefully with dialog info."""
        mock_run_browser.return_value = {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "parsed": None,
            "error": "Command timed out after 30s; blocking alert dialog detected",
            "dialog_info": {
                "has_dialog": True,
                "dialog_type": "alert",
                "message": "Session expired",
            },
            "timed_out": True,
        }

        result = erp.run_browser_command("9230", "eval", "some_js")

        assert "error" in result
        assert "timed out" in result["error"].lower()
        assert result["timed_out"] is True
        assert result["dialog_info"]["has_dialog"] is True

    @patch("ensure_recruiter_project._run_browser_command")
    def test_agent_browser_not_found(self, mock_run_browser):
        """Should handle missing agent-browser gracefully."""
        mock_run_browser.return_value = {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "parsed": None,
            "error": "agent-browser not found in PATH",
            "dialog_info": None,
            "timed_out": False,
        }

        result = erp.run_browser_command("9230", "eval", "some_js")

        assert "error" in result
        assert "agent-browser" in result["error"].lower()


class TestNavigateToProjects:
    """Tests for navigation to Projects page."""

    @patch("ensure_recruiter_project.PageStateProbe")
    @patch("ensure_recruiter_project._run_browser_command")
    @patch("time.sleep")
    def test_successful_navigation(self, mock_sleep, mock_run_browser, mock_probe):
        """Should return success=True on successful navigation."""
        mock_run_browser.return_value = {
            "stdout": "",
            "stderr": "",
            "returncode": 0,
            "error": None,
            "timed_out": False,
        }
        # Mock probe to return ready state
        mock_probe_instance = MagicMock()
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {"hasRecruiterContent": True},
            "dialog_info": None,
        }
        mock_probe.return_value = mock_probe_instance

        result = erp.navigate_to_projects("9230")

        assert result["success"] is True
        assert result["error"] is None
        mock_run_browser.assert_called_once()
        # Check that goto command was used
        args = mock_run_browser.call_args[0]
        assert "goto" in args
        assert any("projects" in str(arg) for arg in args)

    @patch("ensure_recruiter_project.PageStateProbe")
    @patch("ensure_recruiter_project._run_browser_command")
    def test_failed_navigation(self, mock_run_browser, mock_probe):
        """Should return success=False on failed navigation."""
        mock_run_browser.return_value = {
            "stdout": "",
            "stderr": "connection refused",
            "returncode": 1,
            "error": "connection refused",
            "timed_out": False,
        }
        # Mock probe to return ready state (navigation fails before probe)
        mock_probe_instance = MagicMock()
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {},
            "dialog_info": None,
        }
        mock_probe.return_value = mock_probe_instance

        result = erp.navigate_to_projects("9230")

        assert result["success"] is False
        assert "connection refused" in result["error"]

    @patch("ensure_recruiter_project.PageStateProbe")
    @patch("ensure_recruiter_project._run_browser_command")
    def test_timeout_with_dialog(self, mock_run_browser, mock_probe):
        """Should detect blocking dialog on timeout."""
        mock_run_browser.return_value = {
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": "Command timed out after 30s; blocking alert dialog detected: Session expired",
            "timed_out": True,
            "dialog_info": {
                "has_dialog": True,
                "dialog_type": "alert",
                "message": "Session expired",
            },
        }
        # Mock probe
        mock_probe_instance = MagicMock()
        mock_probe_instance.classify_state.return_value = {
            "state": "ready",
            "details": {},
            "dialog_info": None,
        }
        mock_probe.return_value = mock_probe_instance

        result = erp.navigate_to_projects("9230")

        assert result["success"] is False
        assert result["dialog_info"]["has_dialog"] is True
        assert "alert dialog" in result["error"]
        assert "Session expired" in result["error"]

    @patch("ensure_recruiter_project.RecoveryHelper")
    @patch("ensure_recruiter_project.PageStateProbe")
    @patch("ensure_recruiter_project._run_browser_command")
    @patch("time.sleep")
    def test_recovery_on_bad_page(
        self, mock_sleep, mock_run_browser, mock_probe, mock_recovery
    ):
        """Should attempt recovery when page is not ready."""
        mock_run_browser.return_value = {
            "stdout": "",
            "stderr": "",
            "returncode": 0,
            "error": None,
            "timed_out": False,
        }
        # Mock probe to return bad_page then ready
        mock_probe_instance = MagicMock()
        mock_probe_instance.classify_state.side_effect = [
            {"state": "bad_page", "details": {"is404": True}, "dialog_info": None},
            {
                "state": "ready",
                "details": {"hasRecruiterContent": True},
                "dialog_info": None,
            },
        ]
        mock_probe.return_value = mock_probe_instance

        # Mock recovery helper
        mock_recovery_instance = MagicMock()
        mock_recovery_instance.attempt_recovery.return_value = {
            "success": True,
            "final_state": "ready",
            "attempts_made": 1,
            "actions_taken": ["navigate_to_target"],
            "error": None,
        }
        mock_recovery.return_value = mock_recovery_instance

        result = erp.navigate_to_projects("9230", work_dir="/tmp/test")

        assert result["success"] is True
        assert result["recovery_attempted"] is True
        mock_recovery_instance.attempt_recovery.assert_called_once()


class TestWaitForPageLoad:
    """Tests for page load waiting."""

    @patch("ensure_recruiter_project.run_browser_command")
    @patch("time.sleep")
    def test_page_loads_quickly(self, mock_sleep, mock_run_browser):
        """Should return True when page loads quickly."""
        mock_run_browser.return_value = {"ready": True, "state": "complete"}

        result = erp.wait_for_page_load("9230")

        assert result is True

    @patch("ensure_recruiter_project.run_browser_command")
    @patch("time.sleep")
    def test_page_never_loads(self, mock_sleep, mock_run_browser):
        """Should return False when page never loads."""
        mock_run_browser.return_value = {"ready": False, "state": "loading"}

        result = erp.wait_for_page_load("9230", max_wait=1)

        assert result is False


class TestSearchForProject:
    """Tests for project search."""

    @patch("ensure_recruiter_project.run_browser_command")
    def test_search_executed(self, mock_run_browser):
        """Should execute search and return result."""
        mock_run_browser.return_value = {"found": True, "action": "searched"}

        result = erp.search_for_project("9230", "Test Project")

        assert result["found"] is True
        assert result["action"] == "searched"


class TestCheckProjectExists:
    """Tests for project existence check."""

    @patch("ensure_recruiter_project.run_browser_command")
    def test_project_found(self, mock_run_browser):
        """Should return found=True when project exists."""
        mock_run_browser.return_value = {
            "found": True,
            "url": "https://linkedin.com/talent/hire/123/projects",
            "name": "Test Project",
        }

        result = erp.check_project_exists("9230", "Test Project")

        assert result["found"] is True
        assert "url" in result

    @patch("ensure_recruiter_project.run_browser_command")
    def test_project_not_found(self, mock_run_browser):
        """Should return found=False when project doesn't exist."""
        mock_run_browser.return_value = {"found": False}

        result = erp.check_project_exists("9230", "Nonexistent Project")

        assert result["found"] is False


class TestClickCreateProject:
    """Tests for Create Project button click."""

    @patch("ensure_recruiter_project.run_browser_command")
    def test_button_clicked(self, mock_run_browser):
        """Should return clicked=True when button found."""
        mock_run_browser.return_value = {"clicked": True, "text": "Create Project"}

        result = erp.click_create_project("9230")

        assert result["clicked"] is True

    @patch("ensure_recruiter_project.run_browser_command")
    def test_button_not_found(self, mock_run_browser):
        """Should return clicked=False when button not found."""
        mock_run_browser.return_value = {"clicked": False, "error": "Not found"}

        result = erp.click_create_project("9230")

        assert result["clicked"] is False


class TestFillCreateForm:
    """Tests for form filling."""

    @patch("ensure_recruiter_project.run_browser_command")
    def test_form_filled(self, mock_run_browser):
        """Should fill name and description fields."""
        mock_run_browser.return_value = {
            "nameFilled": True,
            "descFilled": True,
            "projectName": "Test Project",
        }

        result = erp.fill_create_form("9230", "Test Project", "Description")

        assert result["nameFilled"] is True
        assert result["projectName"] == "Test Project"

    @patch("ensure_recruiter_project.run_browser_command")
    def test_name_only_filled(self, mock_run_browser):
        """Should handle case where only name field exists."""
        mock_run_browser.return_value = {
            "nameFilled": True,
            "descFilled": False,
            "projectName": "Test Project",
        }

        result = erp.fill_create_form("9230", "Test Project", "")

        assert result["nameFilled"] is True


class TestSubmitForm:
    """Tests for form submission."""

    @patch("ensure_recruiter_project.run_browser_command")
    @patch("time.sleep")
    def test_direct_submit(self, mock_sleep, mock_run_browser):
        """Should submit form directly when possible."""
        mock_run_browser.return_value = {"submitted": True, "text": "Create"}

        result = erp.submit_form("9230")

        assert result["submitted"] is True

    @patch("ensure_recruiter_project.run_browser_command")
    @patch("time.sleep")
    def test_submit_with_fallback(self, mock_sleep, mock_run_browser):
        """Should try click-outside fallback when direct submit fails."""
        # First call fails, second succeeds after fallback
        mock_run_browser.side_effect = [
            {"submitted": False},  # First attempt
            {"clicked": True},  # Click outside
            {"submitted": True},  # Second attempt
        ]

        result = erp.submit_form("9230")

        assert result["submitted"] is True
        assert mock_run_browser.call_count == 3


class TestCheckUntitled:
    """Tests for untitled project detection."""

    @patch("ensure_recruiter_project.run_browser_command")
    def test_is_untitled(self, mock_run_browser):
        """Should detect untitled project."""
        mock_run_browser.return_value = {
            "isUntitled": True,
            "title": "Untitled Project",
        }

        result = erp.check_untitled("9230")

        assert result["isUntitled"] is True

    @patch("ensure_recruiter_project.run_browser_command")
    def test_is_titled(self, mock_run_browser):
        """Should detect titled project."""
        mock_run_browser.return_value = {"isUntitled": False, "title": "My Project"}

        result = erp.check_untitled("9230")

        assert result["isUntitled"] is False


class TestGetCurrentUrl:
    """Tests for URL retrieval."""

    @patch("ensure_recruiter_project.run_browser_command")
    def test_url_retrieved(self, mock_run_browser):
        """Should return current URL and title."""
        mock_run_browser.return_value = {
            "url": "https://linkedin.com/talent/hire/123/projects",
            "title": "Test Project",
        }

        result = erp.get_current_url("9230")

        assert result["url"] == "https://linkedin.com/talent/hire/123/projects"
        assert result["title"] == "Test Project"


class TestEnsureProjectExists:
    """Integration tests for the main ensure_project_exists function."""

    @patch("ensure_recruiter_project.validate_project_context")
    @patch("ensure_recruiter_project.validate_navigation_result")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.check_untitled")
    @patch("ensure_recruiter_project.submit_form")
    @patch("ensure_recruiter_project.fill_create_form")
    @patch("ensure_recruiter_project.click_create_project")
    @patch("ensure_recruiter_project.check_project_exists")
    @patch("ensure_recruiter_project.search_for_project")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.navigate_to_projects")
    @patch("time.sleep")
    def test_existing_project_found(
        self,
        mock_sleep,
        mock_navigate,
        mock_wait,
        mock_search,
        mock_check_exists,
        mock_click_create,
        mock_fill,
        mock_submit,
        mock_untitled,
        mock_get_url,
        mock_resolve,
        mock_validate_nav,
        mock_validate_context,
    ):
        """Should return existing project when found with search URL."""
        mock_navigate.return_value = {
            "success": True,
            "error": None,
            "dialog_info": None,
        }
        mock_wait.return_value = True
        mock_search.return_value = {"found": True}
        mock_check_exists.return_value = {
            "found": True,
            "url": "https://linkedin.com/talent/hire/123/projects",
            "name": "Test Project",
        }
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/123/overview",
            "title": "Test Project",
        }
        # resolve_search_url should convert overview to contextual search URL
        mock_resolve.return_value = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123"
        # Validation mocks
        mock_validate_nav.return_value = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "error": None,
        }
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }

        result = erp.ensure_project_exists("Test Project", "Description", "9230")

        assert result["status"] == "existing"
        assert result["project_id"] == "123"
        assert "discover/recruiterSearch" in result["url"], (
            f"URL must be search-ready, got: {result['url']}"
        )
        assert "Found existing" in result["message"]
        mock_resolve.assert_called_once_with(
            "9230", "https://linkedin.com/talent/hire/123/overview"
        )
        # Should not try to create
        mock_click_create.assert_not_called()

    @patch("ensure_recruiter_project.validate_project_context")
    @patch("ensure_recruiter_project.validate_navigation_result")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.check_untitled")
    @patch("ensure_recruiter_project.submit_form")
    @patch("ensure_recruiter_project.fill_create_form")
    @patch("ensure_recruiter_project.click_create_project")
    @patch("ensure_recruiter_project.check_project_exists")
    @patch("ensure_recruiter_project.search_for_project")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.navigate_to_projects")
    @patch("time.sleep")
    def test_create_new_project(
        self,
        mock_sleep,
        mock_navigate,
        mock_wait,
        mock_search,
        mock_check_exists,
        mock_click_create,
        mock_fill,
        mock_submit,
        mock_untitled,
        mock_get_url,
        mock_resolve,
        mock_validate_nav,
        mock_validate_context,
    ):
        """Should create new project and return search URL."""
        mock_navigate.return_value = {
            "success": True,
            "error": None,
            "dialog_info": None,
        }
        mock_wait.return_value = True
        mock_search.return_value = {"found": True}
        mock_check_exists.return_value = {"found": False}  # Not found
        mock_click_create.return_value = {"clicked": True}
        mock_fill.return_value = {"nameFilled": True, "descFilled": True}
        mock_submit.return_value = {"submitted": True}
        mock_untitled.return_value = {"isUntitled": False}
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/456/overview",
            "title": "Test Project",
        }
        # resolve_search_url should convert overview to contextual search URL
        mock_resolve.return_value = "https://linkedin.com/talent/hire/456/discover/recruiterSearch?searchContextId=abc123"
        # Validation mocks
        mock_validate_nav.return_value = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/456/overview",
            "error": None,
        }
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/456/overview",
            "project_id": "456",
            "error": None,
        }

        result = erp.ensure_project_exists("Test Project", "Description", "9230")

        assert result["status"] == "created"
        assert result["project_id"] == "456"
        assert "discover/recruiterSearch" in result["url"], (
            f"URL must be search-ready, got: {result['url']}"
        )
        assert "Created new" in result["message"]
        mock_click_create.assert_called_once()
        mock_resolve.assert_called_once_with(
            "9230", "https://linkedin.com/talent/hire/456/overview"
        )

    @patch("ensure_recruiter_project.validate_project_context")
    @patch("ensure_recruiter_project.validate_navigation_result")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.rename_project")
    @patch("ensure_recruiter_project.check_untitled")
    @patch("ensure_recruiter_project.submit_form")
    @patch("ensure_recruiter_project.fill_create_form")
    @patch("ensure_recruiter_project.click_create_project")
    @patch("ensure_recruiter_project.check_project_exists")
    @patch("ensure_recruiter_project.search_for_project")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.navigate_to_projects")
    @patch("time.sleep")
    def test_rename_untitled_project(
        self,
        mock_sleep,
        mock_navigate,
        mock_wait,
        mock_search,
        mock_check_exists,
        mock_click_create,
        mock_fill,
        mock_submit,
        mock_untitled,
        mock_rename,
        mock_get_url,
        mock_resolve,
        mock_validate_nav,
        mock_validate_context,
    ):
        """Should rename project when it lands as untitled and return search URL."""
        mock_navigate.return_value = {
            "success": True,
            "error": None,
            "dialog_info": None,
        }
        mock_wait.return_value = True
        mock_search.return_value = {"found": True}
        mock_check_exists.return_value = {"found": False}
        mock_click_create.return_value = {"clicked": True}
        mock_fill.return_value = {"nameFilled": True}
        mock_submit.return_value = {"submitted": True}
        mock_untitled.return_value = {"isUntitled": True, "title": "Untitled Project"}
        mock_rename.return_value = {"attempted": True}
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/789/overview",
            "title": "Test Project",
        }
        mock_resolve.return_value = "https://linkedin.com/talent/hire/789/discover/recruiterSearch?searchContextId=abc123"
        # Validation mocks
        mock_validate_nav.return_value = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/789/overview",
            "error": None,
        }
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/789/overview",
            "project_id": "789",
            "error": None,
        }

        result = erp.ensure_project_exists("Test Project", "Description", "9230")

        assert result["status"] == "created"
        assert result["project_id"] == "789"
        assert "discover/recruiterSearch" in result["url"], (
            f"URL must be search-ready, got: {result['url']}"
        )
        mock_rename.assert_called_once()

    @patch("ensure_recruiter_project.navigate_to_projects")
    def test_navigation_failure(self, mock_navigate):
        """Should return error when navigation fails."""
        mock_navigate.return_value = {
            "success": False,
            "error": "Connection refused",
            "dialog_info": None,
        }

        result = erp.ensure_project_exists("Test Project", "Description", "9230")

        assert result["status"] == "error"
        assert "Connection refused" in result["message"]

    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.navigate_to_projects")
    def test_page_load_timeout(self, mock_navigate, mock_wait):
        """Should return error when page doesn't load."""
        mock_navigate.return_value = {
            "success": True,
            "error": None,
            "dialog_info": None,
        }
        mock_wait.return_value = False

        result = erp.ensure_project_exists("Test Project", "Description", "9230")

        assert result["status"] == "error"
        assert "did not load" in result["message"]

    @patch("ensure_recruiter_project.navigate_to_projects")
    def test_navigation_timeout_with_dialog(self, mock_navigate):
        """Should report dialog blocking when navigation times out."""
        mock_navigate.return_value = {
            "success": False,
            "error": "Timeout while trying to navigate to Projects page; a confirm dialog may be blocking progress: 'Are you sure?'",
            "dialog_info": {
                "has_dialog": True,
                "dialog_type": "confirm",
                "message": "Are you sure?",
            },
        }

        result = erp.ensure_project_exists("Test Project", "Description", "9230")

        assert result["status"] == "error"
        assert "confirm dialog" in result["message"]
        assert "Are you sure?" in result["message"]


class TestMain:
    """Tests for main entry point."""

    @patch("ensure_recruiter_project.ensure_project_exists")
    @patch("runtime_manager.RuntimeManager")
    @patch.object(sys, "argv", ["script", "--project-name", "Test"])
    def test_successful_run(self, mock_manager_class, mock_ensure):
        """Should return 0 on success."""
        mock_manager = Mock()
        mock_manager._resolve_profile.return_value = {"WORK_DIR": "/tmp/test"}
        mock_manager_class.return_value = mock_manager

        mock_ensure.return_value = {
            "status": "created",
            "project_name": "Test",
            "url": "https://example.com",
            "message": "Created",
        }

        result = erp.main()

        assert result == 0
        # Verify RuntimeManager was used to get work_dir
        mock_manager_class.assert_called()

    @patch("ensure_recruiter_project.ensure_project_exists")
    @patch("runtime_manager.RuntimeManager")
    @patch.object(sys, "argv", ["script", "--project-name", "Test"])
    def test_failed_run(self, mock_manager_class, mock_ensure):
        """Should return 1 on failure."""
        mock_manager = Mock()
        mock_manager._resolve_profile.return_value = {"WORK_DIR": "/tmp/test"}
        mock_manager_class.return_value = mock_manager

        mock_ensure.return_value = {
            "status": "error",
            "project_name": "Test",
            "url": None,
            "message": "Failed",
        }

        result = erp.main()

        assert result == 1


class TestRuntimeManagerIntegration:
    """Tests for RuntimeManager integration."""

    @patch("runtime_manager.RuntimeManager")
    def test_main_uses_runtime_manager_for_work_dir(self, mock_manager_class):
        """Should use RuntimeManager to resolve work_dir."""
        mock_manager = Mock()
        mock_manager._resolve_profile.return_value = {"WORK_DIR": "/custom/work/dir"}
        mock_manager_class.return_value = mock_manager

        with patch("ensure_recruiter_project.ensure_project_exists") as mock_ensure:
            mock_ensure.return_value = {
                "status": "created",
                "project_name": "Test",
                "url": "https://example.com",
                "message": "Created",
            }

            with patch.object(sys, "argv", ["script", "--project-name", "Test"]):
                erp.main()

            # Verify ensure_project_exists was called with work_dir from RuntimeManager
            call_kwargs = mock_ensure.call_args[1]
            assert call_kwargs["work_dir"] == "/custom/work/dir"


class TestJavaScriptTemplates:
    """Tests for JavaScript template formatting."""

    def test_search_project_js_formatting(self):
        """SEARCH_PROJECT_JS should format project name correctly."""
        project_name = "Test Project"
        js = erp.SEARCH_PROJECT_JS.format(project_name=project_name)

        assert project_name in js
        assert "searchInput" in js
        # Verify braces are properly escaped (should see single braces in output)
        assert "{ found: false" in js or "{{ found: false" in js

    def test_check_project_exists_js_formatting(self):
        """CHECK_PROJECT_EXISTS_JS should format project name correctly."""
        project_name = "My Project"
        js = erp.CHECK_PROJECT_EXISTS_JS.format(project_name=project_name)

        assert project_name in js
        assert "projectLinks" in js

    def test_fill_create_form_js_formatting(self):
        """FILL_CREATE_FORM_JS should format name and description."""
        project_name = "New Project"
        description = "Project Description"
        js = erp.FILL_CREATE_FORM_JS.format(
            project_name=project_name, description=description
        )

        assert project_name in js
        assert description in js

    def test_rename_project_js_formatting(self):
        """RENAME_PROJECT_JS should format project name correctly."""
        project_name = "Renamed Project"
        js = erp.RENAME_PROJECT_JS.format(project_name=project_name)

        assert project_name in js


class TestNavigateToSearchPage:
    """Tests for navigate_to_search_page function."""

    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.run_browser_command")
    def test_already_on_search_page(self, mock_run_browser, mock_wait, mock_get_url):
        """Should detect when already on search page."""
        mock_run_browser.return_value = {
            "clicked": False,
            "alreadyOnSearch": True,
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
        }

        result = erp.navigate_to_search_page("9230")

        assert result["success"] is True
        assert "discover/recruiterSearch" in result["url"]
        assert result["method"] == "already_there"

    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.run_browser_command")
    def test_click_navigates_to_search(self, mock_run_browser, mock_wait, mock_get_url):
        """Should click tab/link and return contextual search URL."""
        mock_run_browser.side_effect = [
            {"clicked": True, "method": "tab", "text": "Recruiter search"},
            {"derived": False},  # Fallback not needed
        ]
        mock_wait.return_value = True
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123",
            "title": "Search",
        }

        result = erp.navigate_to_search_page("9230")

        assert result["success"] is True
        assert "discover/recruiterSearch" in result["url"]
        assert "searchContextId" in result["url"]
        assert result["method"] == "click"

    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.run_browser_command")
    @patch("time.sleep")
    def test_delayed_url_transition_polls_until_contextual_url(
        self, mock_sleep, mock_run_browser, mock_wait, mock_get_url
    ):
        """Should poll for URL change when recruiterSearch URL updates after page load.

        Regression test for: URL transition to contextual recruiterSearch often
        completes after wait_for_page_load() returns true.
        """
        mock_run_browser.side_effect = [
            {"clicked": True, "method": "specific_button", "testId": "recruiterSearch"},
            {"derived": False},  # Fallback not needed
        ]
        mock_wait.return_value = True
        # URL transitions from overview to contextual recruiterSearch after delay
        mock_get_url.side_effect = [
            {
                "url": "https://linkedin.com/talent/hire/123/overview",
                "title": "Overview",
            },
            {
                "url": "https://linkedin.com/talent/hire/123/overview",
                "title": "Overview",
            },
            {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123&searchHistoryId=def456",
                "title": "Recruiter Search",
            },
        ]

        result = erp.navigate_to_search_page("9230")

        assert result["success"] is True
        assert "discover/recruiterSearch" in result["url"]
        assert "searchContextId" in result["url"]
        assert result["method"] == "click"
        # Should have polled multiple times
        assert mock_get_url.call_count >= 3

    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.run_browser_command")
    @patch("time.sleep")
    def test_bare_recruiter_search_then_contextual(
        self, mock_sleep, mock_run_browser, mock_wait, mock_get_url
    ):
        """Should keep polling past bare recruiterSearch URL until contextual appears.

        Regression test for: bare /discover/recruiterSearch (no params) was accepted
        as success, but resolve_search_url() rejected it and returned None.
        Realistic sequence: overview -> bare recruiterSearch -> contextual recruiterSearch.
        """
        mock_run_browser.side_effect = [
            {"clicked": True, "method": "specific_button", "testId": "recruiterSearch"},
            {"derived": False},  # Fallback not needed
        ]
        mock_wait.return_value = True
        # Realistic URL sequence: overview -> bare -> contextual
        mock_get_url.side_effect = [
            {
                "url": "https://linkedin.com/talent/hire/123/overview",
                "title": "Overview",
            },
            {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
                "title": "Recruiter Search",
            },  # Bare URL - should NOT stop here
            {
                "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123",
                "title": "Recruiter Search",
            },  # Contextual URL - should stop here
        ]

        result = erp.navigate_to_search_page("9230")

        assert result["success"] is True
        assert "discover/recruiterSearch" in result["url"]
        assert "searchContextId=abc123" in result["url"]
        assert result["method"] == "click"
        # Should have polled past the bare URL to get the contextual one
        assert mock_get_url.call_count >= 3

    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.run_browser_command")
    @patch("time.sleep")
    def test_delayed_url_transition_with_context_params(
        self, mock_sleep, mock_run_browser, mock_wait, mock_get_url
    ):
        """Should capture contextual URL with all search params when transition is delayed.

        Verifies the fix for: manual click produces contextual URL with
        searchContextId, searchHistoryId, searchRequestId, start params,
        but script was reading URL too early.
        """
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123&searchHistoryId=def456&searchRequestId=ghi789&start=0"
        mock_run_browser.side_effect = [
            {"clicked": True, "method": "specific_button", "testId": "recruiterSearch"},
            {"derived": False},
        ]
        mock_wait.return_value = True
        # Simulate delayed transition: first reads are overview, then contextual
        mock_get_url.side_effect = [
            {
                "url": "https://linkedin.com/talent/hire/123/overview",
                "title": "Project",
            },
            {
                "url": "https://linkedin.com/talent/hire/123/overview",
                "title": "Project",
            },
            {
                "url": "https://linkedin.com/talent/hire/123/overview",
                "title": "Project",
            },
            {"url": contextual_url, "title": "Recruiter Search"},
        ]

        result = erp.navigate_to_search_page("9230")

        assert result["success"] is True
        assert result["url"] == contextual_url
        assert "searchContextId=abc123" in result["url"]
        assert "searchHistoryId=def456" in result["url"]
        assert "searchRequestId=ghi789" in result["url"]

    @patch("ensure_recruiter_project._run_browser_command")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.run_browser_command")
    @patch("time.sleep")
    def test_polling_timeout_falls_back_to_derive(
        self, mock_sleep, mock_run_browser, mock_wait, mock_get_url, mock_run_goto
    ):
        """Should fall back to derive strategy when polling times out without URL change."""
        mock_run_browser.side_effect = [
            {"clicked": True, "method": "specific_button"},
            {
                "derived": True,
                "projectId": "123",
                "searchUrl": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
        ]
        mock_wait.return_value = True
        # _run_browser_command is used for goto in the derive fallback
        mock_run_goto.return_value = {"stdout": "", "stderr": "", "error": None}

        # Polling loop calls get_current_url up to 10 times, then after derived
        # navigation it calls once more. Total: 11 calls.
        overview_response = {
            "url": "https://linkedin.com/talent/hire/123/overview",
            "title": "Overview",
        }
        search_response = {
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "title": "Search",
        }
        mock_get_url.side_effect = [
            *([overview_response] * 10),  # Polling loops (10 iterations, all overview)
            search_response,  # After derived navigation
        ]

        result = erp.navigate_to_search_page("9230")

        # Should succeed via derived method since polling didn't find it
        assert result["success"] is True
        assert result["method"] == "derived"
        mock_run_goto.assert_called_once()

    @patch("ensure_recruiter_project._run_browser_command")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.run_browser_command")
    def test_derive_search_url_fallback(
        self, mock_run_browser, mock_wait, mock_get_url, mock_run_goto
    ):
        """Should derive and navigate to search URL when click fails."""
        mock_run_browser.side_effect = [
            {"clicked": False, "error": "Not found"},  # Click fails
            {
                "derived": True,
                "projectId": "123",
                "searchUrl": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            },
        ]
        mock_wait.return_value = True
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "title": "Search",
        }
        # _run_browser_command is used for goto in the derive fallback
        mock_run_goto.return_value = {"stdout": "", "stderr": "", "error": None}

        result = erp.navigate_to_search_page("9230")

        assert result["success"] is True
        assert "discover/recruiterSearch" in result["url"]
        assert result["method"] == "derived"

    def test_navigate_to_search_js_prefers_specific_button(self):
        """NAVIGATE_TO_SEARCH_JS should prioritize specific button selector first."""
        # The JS should check for the specific button selector before generic text heuristics
        js = erp.NAVIGATE_TO_SEARCH_JS

        # Should contain the specific button selector as first strategy
        assert 'button[data-test-collapsible-menu-link="recruiterSearch"]' in js, (
            "JS must prioritize specific button selector"
        )

        # Should have the specific selector before text fallback
        specific_idx = js.find(
            'button[data-test-collapsible-menu-link="recruiterSearch"]'
        )
        text_fallback_idx = js.find("text_fallback")
        assert specific_idx < text_fallback_idx, (
            "Specific button selector must come before text fallback"
        )

    def test_navigate_to_search_js_avoids_wrapper_div(self):
        """NAVIGATE_TO_SEARCH_JS should not target the non-functional wrapper div."""
        js = erp.NAVIGATE_TO_SEARCH_JS

        # Should NOT contain the wrapper div selector that does nothing on click
        assert 'data-test-sourcing-channels-tab="recruiterSearch"' not in js, (
            "JS must NOT target the non-functional wrapper div"
        )

        # Should NOT target generic div elements
        assert "div.collapsible-layout__panel-link-wrapper" not in js, (
            "JS must NOT target wrapper divs"
        )

    def test_navigate_to_search_js_has_fallback_chain(self):
        """NAVIGATE_TO_SEARCH_JS should have readable fallback chain."""
        js = erp.NAVIGATE_TO_SEARCH_JS

        # Should have multiple strategies
        strategies = [
            "specific_button",
            "role_link_button",
            "link",
            "text_fallback",
            "alreadyOnSearch",
        ]
        for strategy in strategies:
            assert strategy in js, f"JS should include {strategy} strategy"

    def test_navigate_to_search_js_returns_contextual_url(self):
        """NAVIGATE_TO_SEARCH_JS click should navigate to contextual URL with params."""
        # This documents the expected behavior from CDP findings:
        # Clicking the specific button navigates to a URL like:
        # /talent/hire/<id>/discover/recruiterSearch?searchContextId=...&searchHistoryId=...
        js = erp.NAVIGATE_TO_SEARCH_JS

        # The JS should be structured to succeed when the specific button is clicked
        assert "specificButton.click()" in js, (
            "JS must click the specific button when found"
        )
        assert "{ clicked: true, method: 'specific_button'" in js, (
            "JS must return specific_button method on success"
        )


class TestIsContextualSearchUrl:
    """Tests for is_contextual_search_url function."""

    def test_bare_url_is_not_contextual(self):
        """Bare /discover/recruiterSearch URL without params is not contextual."""
        bare_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        assert erp.is_contextual_search_url(bare_url) is False

    def test_url_with_search_context_id_is_contextual(self):
        """URL with searchContextId is contextual."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123"
        assert erp.is_contextual_search_url(contextual_url) is True

    def test_url_with_search_history_id_is_contextual(self):
        """URL with searchHistoryId is contextual."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchHistoryId=def456"
        assert erp.is_contextual_search_url(contextual_url) is True

    def test_url_with_search_request_id_is_contextual(self):
        """URL with searchRequestId is contextual."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchRequestId=ghi789"
        assert erp.is_contextual_search_url(contextual_url) is True

    def test_url_with_project_id_is_contextual(self):
        """URL with projectId in query params is contextual."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?projectId=456"
        assert erp.is_contextual_search_url(contextual_url) is True

    def test_url_with_multiple_context_params_is_contextual(self):
        """URL with multiple context params is contextual."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc&searchHistoryId=def&start=25"
        assert erp.is_contextual_search_url(contextual_url) is True

    def test_non_search_url_is_not_contextual(self):
        """Non-recruiterSearch URLs are not contextual."""
        overview_url = "https://linkedin.com/talent/hire/123/overview"
        assert erp.is_contextual_search_url(overview_url) is False

    def test_pagination_only_url_is_not_contextual(self):
        """URL with only start param is not contextual (would hang)."""
        pagination_only = (
            "https://linkedin.com/talent/hire/123/discover/recruiterSearch?start=25"
        )
        assert erp.is_contextual_search_url(pagination_only) is False


class TestResolveSearchUrl:
    """Tests for resolve_search_url function."""

    def test_already_contextual_search_url(self):
        """Should return URL as-is if already has context params."""
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123&searchHistoryId=def456"

        result = erp.resolve_search_url("9230", contextual_url)

        assert result == contextual_url

    def test_bare_search_url_returns_none(self):
        """Bare search URL without context should return None (fail closed)."""
        bare_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"

        result = erp.resolve_search_url("9230", bare_url)

        # Should fail closed - bare URLs hang on "Loading search results"
        assert result is None

    @patch("ensure_recruiter_project.navigate_to_search_page")
    def test_navigates_to_contextual_search(self, mock_navigate):
        """Should navigate and return URL if it has context params."""
        overview_url = "https://linkedin.com/talent/hire/123/overview"
        contextual_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch?searchContextId=abc123"
        mock_navigate.return_value = {
            "success": True,
            "url": contextual_url,
            "method": "click",
        }

        result = erp.resolve_search_url("9230", overview_url)

        assert result == contextual_url
        mock_navigate.assert_called_once()

    @patch("ensure_recruiter_project.navigate_to_search_page")
    def test_navigation_without_context_returns_none(self, mock_navigate):
        """Should return None if navigation only yields bare URL (fail closed)."""
        overview_url = "https://linkedin.com/talent/hire/123/overview"
        bare_url = "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        mock_navigate.return_value = {
            "success": True,
            "url": bare_url,
            "method": "derived",
        }

        result = erp.resolve_search_url("9230", overview_url)

        # Should fail closed - don't return bare URLs
        assert result is None
        mock_navigate.assert_called_once()

    @patch("ensure_recruiter_project.navigate_to_search_page")
    def test_fail_closed_when_navigation_fails(self, mock_navigate):
        """Should return None if navigation fails (fail closed, not fallback)."""
        overview_url = "https://linkedin.com/talent/hire/123/overview"
        mock_navigate.return_value = {"success": False, "error": "Navigation failed"}

        result = erp.resolve_search_url("9230", overview_url)

        # Should fail closed - return None instead of original URL
        assert result is None


class TestNavigationValidation:
    """Tests for navigation result validation functions."""

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_navigation_result_success(self, mock_get_url):
        """Should return success when URL matches expected patterns."""
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "title": "Search",
        }

        result = erp.validate_navigation_result(
            "9230",
            expected_url_patterns=["/talent/hire/", "/discover/recruiterSearch"],
            context="Test navigation",
        )

        assert result["success"] is True
        assert (
            result["current_url"]
            == "https://linkedin.com/talent/hire/123/discover/recruiterSearch"
        )
        assert result["error"] is None

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_navigation_result_wrong_page(self, mock_get_url):
        """Should return failure when URL doesn't match expected patterns."""
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/projects",
            "title": "Projects",
        }

        result = erp.validate_navigation_result(
            "9230",
            expected_url_patterns=["/discover/recruiterSearch"],
            context="Open project",
        )

        assert result["success"] is False
        assert "Open project" in result["error"]
        assert "/discover/recruiterSearch" in result["error"]

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_navigation_result_non_talent_page(self, mock_get_url):
        """Should return failure when not on a talent page."""
        mock_get_url.return_value = {
            "url": "https://linkedin.com/feed/",
            "title": "Feed",
        }

        result = erp.validate_navigation_result(
            "9230",
            expected_url_patterns=["/talent/hire/"],
            context="Navigate to project",
        )

        assert result["success"] is False
        assert "non-talent page" in result["error"]

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_navigation_result_empty_url(self, mock_get_url):
        """Should return failure when URL cannot be retrieved."""
        mock_get_url.return_value = {"url": "", "title": ""}

        result = erp.validate_navigation_result(
            "9230",
            expected_url_patterns=["/talent/"],
            context="Test",
        )

        assert result["success"] is False
        assert "Could not retrieve current URL" in result["error"]


class TestProjectContextValidation:
    """Tests for project context validation."""

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_project_context_success(self, mock_get_url):
        """Should validate project context successfully."""
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/123/discover/recruiterSearch",
            "title": "Search",
        }

        result = erp.validate_project_context(
            "9230",
            project_name="Test Project",
        )

        assert result["valid"] is True
        assert result["project_id"] == "123"
        assert result["error"] is None

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_project_context_with_expected_id(self, mock_get_url):
        """Should validate when expected project ID matches."""
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/456/overview",
            "title": "Project",
        }

        result = erp.validate_project_context(
            "9230",
            project_name="Test Project",
            expected_project_id="456",
        )

        assert result["valid"] is True
        assert result["project_id"] == "456"

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_project_context_id_mismatch(self, mock_get_url):
        """Should fail when project ID doesn't match expected."""
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/789/overview",
            "title": "Project",
        }

        result = erp.validate_project_context(
            "9230",
            project_name="Test Project",
            expected_project_id="456",
        )

        assert result["valid"] is False
        assert "Project ID mismatch" in result["error"]
        assert "expected 456, got 789" in result["error"]

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_project_context_invalid_url(self, mock_get_url):
        """Should fail when URL is not a valid project page."""
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/projects",
            "title": "Projects",
        }

        result = erp.validate_project_context(
            "9230",
            project_name="Test Project",
        )

        assert result["valid"] is False
        assert "does not appear to be a valid project page" in result["error"]

    @patch("ensure_recruiter_project.get_current_url")
    def test_validate_project_context_empty_url(self, mock_get_url):
        """Should fail when URL cannot be retrieved."""
        mock_get_url.return_value = {"url": "", "title": ""}

        result = erp.validate_project_context(
            "9230",
            project_name="Test Project",
        )

        assert result["valid"] is False
        assert "Could not retrieve current URL" in result["error"]


class TestEnsureProjectExistsRelaxedMode:
    """Tests for ensure_project_exists with require_contextual_url=False (bootstrap mode)."""

    @patch("ensure_recruiter_project.validate_project_context")
    @patch("ensure_recruiter_project.validate_navigation_result")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.check_untitled")
    @patch("ensure_recruiter_project.submit_form")
    @patch("ensure_recruiter_project.fill_create_form")
    @patch("ensure_recruiter_project.click_create_project")
    @patch("ensure_recruiter_project.check_project_exists")
    @patch("ensure_recruiter_project.search_for_project")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.navigate_to_projects")
    @patch("time.sleep")
    def test_returns_project_id_without_contextual_url(
        self,
        mock_sleep,
        mock_navigate,
        mock_wait,
        mock_search,
        mock_check_exists,
        mock_click_create,
        mock_fill,
        mock_submit,
        mock_untitled,
        mock_get_url,
        mock_resolve,
        mock_validate_nav,
        mock_validate_context,
    ):
        """Should return project_id even without contextual search URL when require_contextual_url=False."""
        mock_navigate.return_value = {
            "success": True,
            "error": None,
            "dialog_info": None,
        }
        mock_wait.return_value = True
        mock_search.return_value = {"found": True}
        mock_check_exists.return_value = {
            "found": True,
            "url": "https://linkedin.com/talent/hire/123/projects",
            "name": "Test Project",
        }
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/123/overview",
            "title": "Test Project",
        }
        # resolve_search_url returns None (no contextual URL available)
        mock_resolve.return_value = None
        # Validation mocks
        mock_validate_nav.return_value = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "error": None,
        }
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }

        result = erp.ensure_project_exists(
            "Test Project", "Description", "9230", require_contextual_url=False
        )

        # Should succeed even without contextual URL
        assert result["status"] == "existing"
        assert result["project_id"] == "123"
        assert result["url"] == "https://linkedin.com/talent/hire/123/overview"

    @patch("ensure_recruiter_project.validate_project_context")
    @patch("ensure_recruiter_project.validate_navigation_result")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.check_untitled")
    @patch("ensure_recruiter_project.submit_form")
    @patch("ensure_recruiter_project.fill_create_form")
    @patch("ensure_recruiter_project.click_create_project")
    @patch("ensure_recruiter_project.check_project_exists")
    @patch("ensure_recruiter_project.search_for_project")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.navigate_to_projects")
    @patch("time.sleep")
    def test_fails_without_contextual_url_in_strict_mode(
        self,
        mock_sleep,
        mock_navigate,
        mock_wait,
        mock_search,
        mock_check_exists,
        mock_click_create,
        mock_fill,
        mock_submit,
        mock_untitled,
        mock_get_url,
        mock_resolve,
        mock_validate_nav,
        mock_validate_context,
    ):
        """Should fail without contextual URL when require_contextual_url=True (default)."""
        mock_navigate.return_value = {
            "success": True,
            "error": None,
            "dialog_info": None,
        }
        mock_wait.return_value = True
        mock_search.return_value = {"found": True}
        mock_check_exists.return_value = {
            "found": True,
            "url": "https://linkedin.com/talent/hire/123/projects",
            "name": "Test Project",
        }
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/123/overview",
            "title": "Test Project",
        }
        # resolve_search_url returns None (no contextual URL available)
        mock_resolve.return_value = None
        # Validation mocks
        mock_validate_nav.return_value = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "error": None,
        }
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }

        result = erp.ensure_project_exists(
            "Test Project", "Description", "9230", require_contextual_url=True
        )

        # Should fail in strict mode
        assert result["status"] == "error"
        assert "Could not resolve contextual search URL" in result["message"]


class TestEnsureProjectExistsValidation:
    """Tests for ensure_project_exists with validation."""

    @patch("ensure_recruiter_project.validate_project_context")
    @patch("ensure_recruiter_project.validate_navigation_result")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.check_untitled")
    @patch("ensure_recruiter_project.submit_form")
    @patch("ensure_recruiter_project.fill_create_form")
    @patch("ensure_recruiter_project.click_create_project")
    @patch("ensure_recruiter_project.check_project_exists")
    @patch("ensure_recruiter_project.search_for_project")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.navigate_to_projects")
    @patch("time.sleep")
    def test_create_validates_submit_result(
        self,
        mock_sleep,
        mock_navigate,
        mock_wait,
        mock_search,
        mock_check_exists,
        mock_click_create,
        mock_fill,
        mock_submit,
        mock_untitled,
        mock_get_url,
        mock_resolve,
        mock_validate_nav,
        mock_validate_context,
    ):
        """Should validate submit result and fail if not on talent page."""
        # Setup mocks for navigation and search
        mock_navigate.return_value = {
            "success": True,
            "error": None,
            "dialog_info": None,
        }
        mock_wait.return_value = True
        mock_search.return_value = {"found": True}
        mock_check_exists.return_value = {"found": False}  # Not found, will create
        mock_click_create.return_value = {"clicked": True}
        mock_fill.return_value = {"nameFilled": True}
        mock_submit.return_value = {"submitted": True}
        mock_untitled.return_value = {"isUntitled": False}

        # First validation (projects page) succeeds
        # Second validation (after submit) fails - not on talent page
        mock_validate_nav.side_effect = [
            {
                "success": True,
                "current_url": "https://linkedin.com/talent/projects",
                "error": None,
            },
            {
                "success": False,
                "current_url": "https://linkedin.com/talent/projects",
                "error": "Still on projects page after submit",
            },
        ]

        result = erp.ensure_project_exists("Test Project", "Description", "9230")

        assert result["status"] == "error"
        assert "Form submission failed" in result["message"]

    @patch("ensure_recruiter_project.validate_project_context")
    @patch("ensure_recruiter_project.validate_navigation_result")
    @patch("ensure_recruiter_project.resolve_search_url")
    @patch("ensure_recruiter_project.get_current_url")
    @patch("ensure_recruiter_project.check_untitled")
    @patch("ensure_recruiter_project.submit_form")
    @patch("ensure_recruiter_project.fill_create_form")
    @patch("ensure_recruiter_project.click_create_project")
    @patch("ensure_recruiter_project.check_project_exists")
    @patch("ensure_recruiter_project.search_for_project")
    @patch("ensure_recruiter_project.wait_for_page_load")
    @patch("ensure_recruiter_project.navigate_to_projects")
    @patch("time.sleep")
    def test_create_validates_final_url_is_search_ready(
        self,
        mock_sleep,
        mock_navigate,
        mock_wait,
        mock_search,
        mock_check_exists,
        mock_click_create,
        mock_fill,
        mock_submit,
        mock_untitled,
        mock_get_url,
        mock_resolve,
        mock_validate_nav,
        mock_validate_context,
    ):
        """Should fail if final URL is not search-ready."""
        mock_navigate.return_value = {
            "success": True,
            "error": None,
            "dialog_info": None,
        }
        mock_wait.return_value = True
        mock_search.return_value = {"found": True}
        mock_check_exists.return_value = {"found": False}
        mock_click_create.return_value = {"clicked": True}
        mock_fill.return_value = {"nameFilled": True}
        mock_submit.return_value = {"submitted": True}
        mock_untitled.return_value = {"isUntitled": False}

        # Validations pass
        mock_validate_nav.return_value = {
            "success": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "error": None,
        }
        mock_validate_context.return_value = {
            "valid": True,
            "current_url": "https://linkedin.com/talent/hire/123/overview",
            "project_id": "123",
            "error": None,
        }

        # But resolve_search_url returns None (fail closed - no contextual URL available)
        mock_resolve.return_value = None
        mock_get_url.return_value = {
            "url": "https://linkedin.com/talent/hire/123/overview"
        }

        result = erp.ensure_project_exists("Test Project", "Description", "9230")

        assert result["status"] == "error"
        assert "Could not resolve contextual search URL" in result["message"]


class TestLiveExposedBugs:
    """Tests for bugs exposed during live validation that mocks missed."""

    def test_projects_url_is_stable_not_hardcoded(self):
        """PROJECTS_URL must use stable /projects path, not hardcoded account ID."""
        # Bug 1: Hardcoded URL caused 404 for different accounts
        assert "1932600" not in erp.PROJECTS_URL, (
            "URL must not contain hardcoded account ID"
        )
        assert erp.PROJECTS_URL == "https://www.linkedin.com/talent/projects", (
            f"Expected stable URL, got: {erp.PROJECTS_URL}"
        )

    def test_unformatted_js_snippets_have_single_braces(self):
        """JS snippets not using .format() must have single braces for valid JS."""
        # Bug 2: Doubled braces {{ }} in unformatted snippets cause syntax errors in agent-browser eval
        unformatted_snippets = [
            ("CLICK_CREATE_PROJECT_JS", erp.CLICK_CREATE_PROJECT_JS),
            ("SUBMIT_FORM_JS", erp.SUBMIT_FORM_JS),
            ("CLICK_OUTSIDE_JS", erp.CLICK_OUTSIDE_JS),
            ("CHECK_UNTITLED_JS", erp.CHECK_UNTITLED_JS),
            ("GET_CURRENT_URL_JS", erp.GET_CURRENT_URL_JS),
            ("WAIT_FOR_LOAD_JS", erp.WAIT_FOR_LOAD_JS),
            ("NAVIGATE_TO_SEARCH_JS", erp.NAVIGATE_TO_SEARCH_JS),
            ("DERIVE_SEARCH_URL_JS", erp.DERIVE_SEARCH_URL_JS),
        ]

        for name, js in unformatted_snippets:
            # These should NOT have {{ or }} since they're not Python-formatted
            # They should have valid single braces for JS object literals
            assert "{{" not in js, (
                f"{name} contains {{ which is invalid for unformatted JS"
            )
            assert "}}" not in js, (
                f"{name} contains }} which is invalid for unformatted JS"
            )
            # Should have valid single-brace JS object syntax (may have newline after {)
            assert (
                "{ clicked:" in js
                or "{ submitted:" in js
                or "{\n        url:" in js  # GET_CURRENT_URL_JS format
                or "{\n        ready:" in js  # WAIT_FOR_LOAD_JS format
                or "{ isUntitled:" in js
                or "{ found:" in js
                or " bubbles: true }" in js
                or "{ success:" in js  # NAVIGATE_TO_SEARCH_JS
                or "{ derived:" in js  # DERIVE_SEARCH_URL_JS
            ), f"{name} should contain valid single-brace JS object literals"

    def test_formatted_js_snippets_have_escaped_braces(self):
        """JS snippets using .format() must have doubled braces for JS literals."""
        # These ARE formatted, so they need {{ and }} for JS object literals
        formatted_snippets = [
            ("SEARCH_PROJECT_JS", erp.SEARCH_PROJECT_JS),
            ("CHECK_PROJECT_EXISTS_JS", erp.CHECK_PROJECT_EXISTS_JS),
            ("FILL_CREATE_FORM_JS", erp.FILL_CREATE_FORM_JS),
            ("RENAME_PROJECT_JS", erp.RENAME_PROJECT_JS),
        ]

        for name, js in formatted_snippets:
            # After .format(), these should result in valid JS with single braces
            test_js = js.format(project_name="Test", description="Desc")
            # Should NOT have remaining {{ or }} after formatting
            assert "{{" not in test_js, f"{name} still contains {{ after .format()"
            assert "}}" not in test_js, f"{name} still contains }} after .format()"

    def test_check_project_exists_handles_recruiter_search_urls(self):
        """CHECK_PROJECT_EXISTS_JS must detect /discover/recruiterSearch URLs."""
        # Bug 3: Real project URLs look like /talent/hire/<id>/discover/recruiterSearch?...
        js = erp.CHECK_PROJECT_EXISTS_JS.format(project_name="Test Project")

        # Should include selector for recruiterSearch URLs
        assert "recruiterSearch" in js, (
            "JS must include selector for /discover/recruiterSearch URLs"
        )
        # Should still include /projects/ selector for backward compatibility
        assert "/projects/" in js, "JS must still include selector for /projects/ URLs"

    def test_returned_url_is_search_ready_not_overview(self):
        """Returned URL must be extraction-ready (search page), not overview.

        This test catches the bug where ensure_project_exists returns:
        https://www.linkedin.com/talent/hire/1687654572/overview
        instead of:
        https://www.linkedin.com/talent/hire/1687654572/discover/recruiterSearch
        """
        # The resolve_search_url function must exist and handle overview URLs
        assert hasattr(erp, "resolve_search_url"), (
            "resolve_search_url function must exist"
        )

        # The navigate_to_search_page function must exist
        assert hasattr(erp, "navigate_to_search_page"), (
            "navigate_to_search_page function must exist"
        )

        # NAVIGATE_TO_SEARCH_JS must exist and contain search detection
        assert hasattr(erp, "NAVIGATE_TO_SEARCH_JS"), "NAVIGATE_TO_SEARCH_JS must exist"
        assert "recruiterSearch" in erp.NAVIGATE_TO_SEARCH_JS, (
            "NAVIGATE_TO_SEARCH_JS must reference recruiterSearch"
        )

        # DERIVE_SEARCH_URL_JS must exist for fallback
        assert hasattr(erp, "DERIVE_SEARCH_URL_JS"), "DERIVE_SEARCH_URL_JS must exist"
        assert "discover/recruiterSearch" in erp.DERIVE_SEARCH_URL_JS, (
            "DERIVE_SEARCH_URL_JS must reference discover/recruiterSearch"
        )


if __name__ == "__main__":
    import pytest
    import subprocess

    pytest.main([__file__, "-v"])
