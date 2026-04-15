#!/usr/bin/env python3
"""Tests for runtime_manager.py

Run with: python3 -m pytest skills/linkedin-sourcing/tests/test_runtime_manager.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from runtime_manager import RuntimeManager


class TestProfileResolution:
    """Tests for profile resolution and defaults."""

    def test_default_profile_values(self, tmp_path):
        """Should use default values when no profile exists."""
        manager = RuntimeManager(skill_dir=tmp_path)
        profile = manager._resolve_profile()

        assert "WORK_DIR" in profile
        assert "CDP_PORT" in profile
        assert profile["CDP_PORT"] == "9230"
        assert "CHROME_PROFILE" in profile

    def test_profile_from_file(self, tmp_path):
        """Should read profile from profile.sh."""
        profile_dir = tmp_path / ".config" / "linkedin-sourcing"
        profile_dir.mkdir(parents=True)
        profile_file = profile_dir / "profile.sh"
        profile_file.write_text(
            'WORK_DIR="/custom/workdir"\n'
            'CDP_PORT="9999"\n'
            'USER_EMAIL="test@example.com"\n'
        )

        manager = RuntimeManager(profile_path=profile_file, skill_dir=tmp_path)
        profile = manager._resolve_profile()

        assert profile["WORK_DIR"] == "/custom/workdir"
        assert profile["CDP_PORT"] == "9999"
        assert profile["USER_EMAIL"] == "test@example.com"

    def test_work_dir_override(self, tmp_path):
        """Should allow WORK_DIR override via constructor."""
        custom_work = tmp_path / "custom_work"
        manager = RuntimeManager(work_dir=custom_work, skill_dir=tmp_path)

        assert manager.work_dir == custom_work

    def test_chrome_profile_default(self, tmp_path):
        """Should default CHROME_PROFILE to $WORK_DIR/chrome-profile."""
        work_dir = tmp_path / "workdir"
        # Use a non-existent profile path to avoid reading real profile
        fake_profile = tmp_path / "nonexistent_profile.sh"
        manager = RuntimeManager(
            work_dir=work_dir, profile_path=fake_profile, skill_dir=tmp_path
        )
        profile = manager._resolve_profile()

        assert profile["CHROME_PROFILE"] == str(work_dir / "chrome-profile")

    def test_profile_caching(self, tmp_path):
        """Should cache profile after first resolution."""
        manager = RuntimeManager(skill_dir=tmp_path)

        # First call
        profile1 = manager._resolve_profile()
        # Second call should return same object
        profile2 = manager._resolve_profile()

        assert profile1 is profile2


class TestPermissionProbe:
    """Tests for permission probe creation."""

    def test_probe_creation(self, tmp_path):
        """Should create permission probe on first run."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        created = manager.ensure_permission_probe()

        assert created is True
        assert manager.permission_probe_path.exists()
        content = manager.permission_probe_path.read_text()
        assert "Permission probe" in content

    def test_probe_idempotent(self, tmp_path):
        """Should not recreate probe if it exists."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        # First call creates
        created1 = manager.ensure_permission_probe()
        # Second call should not create
        created2 = manager.ensure_permission_probe()

        assert created1 is True
        assert created2 is False

    def test_probe_creates_work_dir(self, tmp_path):
        """Should create work_dir if it doesn't exist."""
        work_dir = tmp_path / "nonexistent" / "nested"
        manager = RuntimeManager(work_dir=work_dir, skill_dir=tmp_path)

        manager.ensure_permission_probe()

        assert work_dir.exists()


class TestBundleHash:
    """Tests for bundle hash computation."""

    def test_empty_skill_dir(self, tmp_path):
        """Should handle empty skill directory."""
        manager = RuntimeManager(skill_dir=tmp_path)
        hash1 = manager.compute_bundle_hash()

        assert len(hash1) == 16
        assert all(c in "0123456789abcdef" for c in hash1)

    def test_hash_stability(self, tmp_path):
        """Should produce stable hash for same content."""
        # Create scripts and templates
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "test.py").write_text("print('hello')")

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "test.txt").write_text("template content")

        (tmp_path / "SKILL.md").write_text("# Skill doc")

        manager = RuntimeManager(skill_dir=tmp_path)
        hash1 = manager.compute_bundle_hash()
        hash2 = manager.compute_bundle_hash()

        assert hash1 == hash2

    def test_hash_changes_with_content(self, tmp_path):
        """Should produce different hash when content changes."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        test_file = scripts_dir / "test.py"
        test_file.write_text("print('hello')")

        manager = RuntimeManager(skill_dir=tmp_path)
        hash1 = manager.compute_bundle_hash()

        # Modify content
        test_file.write_text("print('world')")
        hash2 = manager.compute_bundle_hash()

        assert hash1 != hash2

    def test_hash_includes_all_sources(self, tmp_path):
        """Should hash all bundle sources."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "script.py").write_text("script")

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "template.txt").write_text("template")

        (tmp_path / "SKILL.md").write_text("skill doc")

        manager = RuntimeManager(skill_dir=tmp_path)
        hash_full = manager.compute_bundle_hash()

        # Remove SKILL.md
        (tmp_path / "SKILL.md").unlink()
        hash_no_skill = manager.compute_bundle_hash()

        assert hash_full != hash_no_skill

    def test_hash_ignores_pycache(self, tmp_path):
        """Should ignore __pycache__ and .pyc files in hash."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "script.py").write_text("script")

        # Create __pycache__ directory with .pyc files
        pycache_dir = scripts_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "script.cpython-311.pyc").write_bytes(b"pyc content")
        (scripts_dir / "script.pyc").write_bytes(b"orphaned pyc")

        manager = RuntimeManager(skill_dir=tmp_path)
        hash_with_pycache = manager.compute_bundle_hash()

        # Remove pycache files and recompute
        (pycache_dir / "script.cpython-311.pyc").unlink()
        pycache_dir.rmdir()
        (scripts_dir / "script.pyc").unlink()

        hash_clean = manager.compute_bundle_hash()
        assert hash_with_pycache == hash_clean

    def test_copy_ignores_pycache(self, tmp_path):
        """Should not copy __pycache__ or .pyc files to staging."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "script.py").write_text("script")

        # Create __pycache__ directory
        pycache_dir = scripts_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "script.cpython-311.pyc").write_bytes(b"pyc content")
        (scripts_dir / "script.pyc").write_bytes(b"orphaned pyc")

        manager = RuntimeManager(skill_dir=tmp_path)
        staging = tmp_path / "staging"
        staging.mkdir()

        manager._copy_bundle_to_staging(staging)

        # Should copy the .py file
        assert (staging / "scripts" / "script.py").exists()
        # Should NOT copy __pycache__ or .pyc files
        assert not (staging / "scripts" / "__pycache__").exists()
        assert not (staging / "scripts" / "script.pyc").exists()


class TestRuntimeDirectories:
    """Tests for runtime directory structure."""

    def test_creates_runtime_dirs(self, tmp_path):
        """Should create runtime subdirectories."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)
        manager.ensure_runtime_dirs()

        assert (tmp_path / "runtime" / "releases").exists()
        assert (tmp_path / "runtime" / "current").exists()
        assert (tmp_path / "runtime" / "incidents").exists()

    def test_idempotent_dir_creation(self, tmp_path):
        """Should be idempotent for directory creation."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        manager.ensure_runtime_dirs()
        # Add a file to verify it doesn't get deleted
        test_file = tmp_path / "runtime" / "releases" / "test.txt"
        test_file.write_text("test")

        manager.ensure_runtime_dirs()

        assert test_file.exists()


class TestBundleCopyAndLayout:
    """Tests for bundle copy and layout."""

    def test_copy_bundle_to_staging(self, tmp_path):
        """Should copy bundle sources to staging directory."""
        # Setup skill dir structure
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "test_script.py").write_text("# test script")

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "test_template.txt").write_text("test template")

        (tmp_path / "SKILL.md").write_text("# Skill")

        manager = RuntimeManager(skill_dir=tmp_path)
        staging = tmp_path / "staging"
        staging.mkdir()

        manager._copy_bundle_to_staging(staging)

        assert (staging / "scripts" / "test_script.py").exists()
        assert (staging / "templates" / "test_template.txt").exists()
        assert (staging / "SKILL.md").exists()

    def test_atomic_install_release(self, tmp_path):
        """Should atomically install release bundle."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)
        manager.ensure_runtime_dirs()

        # Create staging dir
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "test.txt").write_text("test content")

        release_dir = manager._atomic_install_release("abc123", staging)

        assert release_dir.exists()
        assert (release_dir / "test.txt").read_text() == "test content"
        assert release_dir.name == "abc123"

    def test_atomic_install_skips_existing(self, tmp_path):
        """Should skip installation if release already exists."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)
        manager.ensure_runtime_dirs()

        # Pre-create release
        existing = manager.releases_dir / "abc123"
        existing.mkdir()
        (existing / "existing.txt").write_text("existing")

        # Try to install over it
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "new.txt").write_text("new")

        release_dir = manager._atomic_install_release("abc123", staging)

        # Should return existing, not install new
        assert release_dir == existing
        assert (existing / "existing.txt").exists()
        assert not (existing / "new.txt").exists()


class TestSymlinkManagement:
    """Tests for current symlink management."""

    def test_create_symlink(self, tmp_path):
        """Should create current symlink to release."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)
        manager.ensure_runtime_dirs()

        release = manager.releases_dir / "test_release"
        release.mkdir()

        updated = manager._update_current_symlink(release)

        assert updated is True
        assert manager.current_link.is_symlink()
        assert manager.current_link.resolve() == release.resolve()

    def test_symlink_idempotent(self, tmp_path):
        """Should not update if already pointing to correct release."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)
        manager.ensure_runtime_dirs()

        release = manager.releases_dir / "test_release"
        release.mkdir()

        # First update
        manager._update_current_symlink(release)
        # Second update should return False
        updated = manager._update_current_symlink(release)

        assert updated is False

    def test_symlink_switch_release(self, tmp_path):
        """Should switch symlink when release changes."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)
        manager.ensure_runtime_dirs()

        release1 = manager.releases_dir / "release1"
        release1.mkdir()
        release2 = manager.releases_dir / "release2"
        release2.mkdir()

        manager._update_current_symlink(release1)
        updated = manager._update_current_symlink(release2)

        assert updated is True
        assert manager.current_link.resolve() == release2.resolve()


class TestDependencyChecking:
    """Tests for dependency state checking."""

    @patch("subprocess.run")
    def test_agent_browser_available(self, mock_run, tmp_path):
        """Should detect agent-browser availability."""
        mock_run.return_value = Mock(returncode=0, stdout="1.0.0", stderr="")

        manager = RuntimeManager(skill_dir=tmp_path)
        deps = manager._check_dependencies()

        assert deps["agent_browser"]["available"] is True
        assert deps["agent_browser"]["version"] == "1.0.0"

    @patch("subprocess.run")
    def test_agent_browser_not_found(self, mock_run, tmp_path):
        """Should handle missing agent-browser."""
        mock_run.side_effect = FileNotFoundError()

        manager = RuntimeManager(skill_dir=tmp_path)
        deps = manager._check_dependencies()

        assert deps["agent_browser"]["available"] is False
        assert "not found" in deps["agent_browser"]["error"].lower()

    def test_openpyxl_detection(self, tmp_path):
        """Should detect openpyxl availability."""
        manager = RuntimeManager(skill_dir=tmp_path)
        deps = manager._check_dependencies()

        # openpyxl should be available (we use it in tests)
        assert deps["openpyxl"]["available"] is True
        assert "version" in deps["openpyxl"]

    @patch.dict("sys.modules", {"openpyxl": None})
    def test_openpyxl_missing(self, tmp_path):
        """Should handle missing openpyxl."""
        manager = RuntimeManager(skill_dir=tmp_path)
        deps = manager._check_dependencies()

        assert deps["openpyxl"]["available"] is False

    def test_dependency_timestamp(self, tmp_path):
        """Should include checked_at timestamp."""
        manager = RuntimeManager(skill_dir=tmp_path)
        deps = manager._check_dependencies()

        assert "checked_at" in deps
        assert len(deps["checked_at"]) > 0


class TestStateFileWriting:
    """Tests for runtime_state.json and dependency_state.json writing."""

    def test_write_runtime_state(self, tmp_path):
        """Should write runtime_state.json correctly."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        release_dir = tmp_path / "release"
        release_dir.mkdir()

        manager._write_runtime_state("abc123", release_dir, sync_happened=True)

        assert manager.runtime_state_path.exists()
        state = json.loads(manager.runtime_state_path.read_text())

        assert state["version"] == "1.0.0"
        assert state["current_release"]["hash"] == "abc123"
        assert state["sync_happened"] is True
        assert "updated_at" in state

    def test_write_dependency_state(self, tmp_path):
        """Should write dependency_state.json correctly."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        deps = {"agent_browser": {"available": True}, "openpyxl": {"available": True}}
        manager._write_dependency_state(deps)

        assert manager.dependency_state_path.exists()
        written = json.loads(manager.dependency_state_path.read_text())

        assert written["agent_browser"]["available"] is True


class TestInitialization:
    """Tests for the main initialize() method."""

    def test_full_initialization(self, tmp_path):
        """Should perform full initialization."""
        # Setup skill dir
        scripts_dir = tmp_path / "skill" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "test.py").write_text("# test")

        templates_dir = tmp_path / "skill" / "templates"
        templates_dir.mkdir()
        (templates_dir / "test.txt").write_text("template")

        (tmp_path / "skill" / "SKILL.md").write_text("# Skill")

        manager = RuntimeManager(
            work_dir=tmp_path / "work",
            skill_dir=tmp_path / "skill",
        )

        ctx = manager.initialize()

        # Check context structure
        assert "work_dir" in ctx
        assert "current_release" in ctx
        assert "dependencies" in ctx
        assert "sync_happened" in ctx

        # Check files created
        assert manager.permission_probe_path.exists()
        assert manager.runtime_state_path.exists()
        assert manager.dependency_state_path.exists()

        # Check release installed
        assert ctx["sync_happened"] is True
        release_path = Path(ctx["current_release"]["path"])
        assert release_path.exists()

    def test_idempotent_reinitialization(self, tmp_path):
        """Should not resync when hash hasn't changed."""
        # Setup skill dir
        scripts_dir = tmp_path / "skill" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "test.py").write_text("# test")

        templates_dir = tmp_path / "skill" / "templates"
        templates_dir.mkdir()
        (templates_dir / "test.txt").write_text("template")

        (tmp_path / "skill" / "SKILL.md").write_text("# Skill")

        manager = RuntimeManager(
            work_dir=tmp_path / "work",
            skill_dir=tmp_path / "skill",
        )

        # First initialization
        ctx1 = manager.initialize()
        assert ctx1["sync_happened"] is True

        # Second initialization (same hash)
        ctx2 = manager.initialize()
        assert ctx2["sync_happened"] is False

    def test_force_sync(self, tmp_path):
        """Should force resync when requested."""
        # Setup skill dir
        scripts_dir = tmp_path / "skill" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "test.py").write_text("# test")

        templates_dir = tmp_path / "skill" / "templates"
        templates_dir.mkdir()
        (templates_dir / "test.txt").write_text("template")

        (tmp_path / "skill" / "SKILL.md").write_text("# Skill")

        manager = RuntimeManager(
            work_dir=tmp_path / "work",
            skill_dir=tmp_path / "skill",
        )

        # First initialization
        manager.initialize()

        # Force sync
        ctx = manager.initialize(force_sync=True)
        assert ctx["sync_happened"] is True


class TestScriptResolution:
    """Tests for script and template resolution."""

    def test_resolve_from_override(self, tmp_path):
        """Should resolve from WORK_DIR/scripts override first."""
        work_dir = tmp_path / "work"
        work_scripts = work_dir / "scripts"
        work_scripts.mkdir(parents=True)
        (work_scripts / "test.py").write_text("override")

        skill_dir = tmp_path / "skill"
        skill_scripts = skill_dir / "scripts"
        skill_scripts.mkdir(parents=True)
        (skill_scripts / "test.py").write_text("canonical")

        manager = RuntimeManager(work_dir=work_dir, skill_dir=skill_dir)
        resolved = manager.resolve_script("test.py")

        assert resolved == work_scripts / "test.py"
        assert resolved.read_text() == "override"

    def test_resolve_from_current_release(self, tmp_path):
        """Should resolve from current release if no override."""
        work_dir = tmp_path / "work"
        runtime_scripts = work_dir / "runtime" / "current" / "scripts"
        runtime_scripts.mkdir(parents=True)
        (runtime_scripts / "test.py").write_text("release")

        skill_dir = tmp_path / "skill"
        skill_scripts = skill_dir / "scripts"
        skill_scripts.mkdir(parents=True)
        (skill_scripts / "test.py").write_text("canonical")

        manager = RuntimeManager(work_dir=work_dir, skill_dir=skill_dir)
        resolved = manager.resolve_script("test.py")

        assert resolved == runtime_scripts / "test.py"
        assert resolved.read_text() == "release"

    def test_resolve_from_canonical(self, tmp_path):
        """Should fall back to canonical if no override or release."""
        work_dir = tmp_path / "work"

        skill_dir = tmp_path / "skill"
        skill_scripts = skill_dir / "scripts"
        skill_scripts.mkdir(parents=True)
        (skill_scripts / "test.py").write_text("canonical")

        manager = RuntimeManager(work_dir=work_dir, skill_dir=skill_dir)
        resolved = manager.resolve_script("test.py")

        assert resolved == skill_scripts / "test.py"

    def test_resolve_not_found(self, tmp_path):
        """Should return None if script not found."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)
        resolved = manager.resolve_script("nonexistent.py")

        assert resolved is None

    def test_resolve_template(self, tmp_path):
        """Should resolve templates using same rules."""
        work_dir = tmp_path / "work"
        work_templates = work_dir / "templates"
        work_templates.mkdir(parents=True)
        (work_templates / "test.txt").write_text("override")

        skill_dir = tmp_path / "skill"

        manager = RuntimeManager(work_dir=work_dir, skill_dir=skill_dir)
        resolved = manager.resolve_template("test.txt")

        assert resolved == work_templates / "test.txt"


class TestGetRuntimeContext:
    """Tests for get_runtime_context() method."""

    def test_returns_none_when_no_state(self, tmp_path):
        """Should return None when runtime_state.json doesn't exist."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)
        ctx = manager.get_runtime_context()

        assert ctx is None

    def test_returns_context_when_state_exists(self, tmp_path):
        """Should return context when runtime_state.json exists."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        # Create a runtime state
        state = {
            "work_dir": str(tmp_path),
            "current_release": {
                "hash": "abc123",
                "path": str(tmp_path / "release"),
            },
            "profile": {"WORK_DIR": str(tmp_path)},
        }
        manager.runtime_state_path.write_text(json.dumps(state))

        ctx = manager.get_runtime_context()

        assert ctx is not None
        assert ctx["current_release"]["hash"] == "abc123"


class TestBrowserMode:
    """Tests for browser mode management."""

    def test_get_browser_mode_not_exists(self, tmp_path):
        """Should return None when no browser mode file."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        result = manager.get_browser_mode()

        assert result is None

    def test_save_and_get_browser_mode(self, tmp_path):
        """Should save and retrieve browser mode."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        manager.save_browser_mode(
            mode="cdp",
            cdp_port="9230",
            auth_file=None,
            headed=True,
        )

        result = manager.get_browser_mode()

        assert result is not None
        assert result["mode"] == "cdp"
        assert result["cdp_port"] == "9230"
        assert result["headed"] is True
        assert "updated_at" in result

    def test_save_browser_mode_creates_auth_dir(self, tmp_path):
        """Should create auth directory when saving mode."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        manager.save_browser_mode(
            mode="agent-browser",
            cdp_port="9230",
            auth_file=str(tmp_path / "auth.json"),
        )

        assert manager.auth_dir.exists()

    def test_clear_browser_mode(self, tmp_path):
        """Should clear browser mode."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        manager.save_browser_mode(mode="cdp", cdp_port="9230")
        assert manager.get_browser_mode() is not None

        manager.clear_browser_mode()
        assert manager.get_browser_mode() is None

    def test_get_auth_file_path(self, tmp_path):
        """Should return auth file path."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        auth_path = manager.get_auth_file_path()

        assert auth_path == tmp_path / "runtime" / "auth" / "linkedin-auth.json"

    def test_browser_mode_properties(self, tmp_path):
        """Should have correct path properties."""
        manager = RuntimeManager(work_dir=tmp_path, skill_dir=tmp_path)

        assert manager.browser_mode_path == tmp_path / "runtime" / "browser_mode.json"
        assert manager.auth_dir == tmp_path / "runtime" / "auth"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
