#!/usr/bin/env python3
"""Runtime manager for linkedin-sourcing skill.

Handles runtime environment setup, dependency tracking, and canonical script resolution.
Provides a canonical init/preflight that other workflows can rely on.

Responsibilities:
- Resolve profile/config (WORK_DIR, CDP_PORT, CHROME_PROFILE, etc.)
- Compute bundle version/hash from canonical scripts/ + templates/ + SKILL.md
- Ensure $WORK_DIR/.permission_probe (one-time permission trigger)
- Ensure runtime directory structure (incidents/, auth/)
- Write runtime_state.json and dependency_state.json
- Return structured runtime context dict

Script/Template Resolution:
- WORK_DIR/scripts or WORK_DIR/templates overrides (if present)
- Canonical SKILL_DIR/scripts or SKILL_DIR/templates (default)

Usage:
    from runtime_manager import RuntimeManager
    ctx = RuntimeManager().initialize()
    print(ctx["canonical_paths"]["scripts_dir"])  # Path to canonical scripts
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

DEFAULT_PROFILE_PATH = Path.home() / ".config" / "linkedin-sourcing" / "profile.sh"
DEFAULT_WORK_DIR = Path.home() / "Desktop" / "linkedin-sourcing"
DEFAULT_CDP_PORT = "9230"

RUNTIME_SUBDIRS = ["incidents", "auth"]
BUNDLE_SOURCE_DIRS = ["scripts", "templates"]
BUNDLE_SOURCE_FILES = ["SKILL.md"]

# Transient artifacts to ignore when hashing
BUNDLE_IGNORE_PATTERNS = {"__pycache__", ".pyc"}


def _should_ignore_path(path: Path) -> bool:
    """Check if a path should be ignored during bundle operations.

    Args:
        path: Path to check

    Returns:
        True if the path should be ignored (e.g., __pycache__, .pyc files)
    """
    name = path.name
    if name == "__pycache__" or name.endswith(".pyc"):
        return True
    # Also check any parent component for __pycache__
    for part in path.parts:
        if part == "__pycache__":
            return True
    return False


class RuntimeManager:
    """Manages the runtime environment for linkedin-sourcing skill.

    This class handles all aspects of runtime initialization:
    - Profile resolution from config files
    - Permission probe creation
    - Bundle hash computation for version visibility
    - Dependency state tracking
    - Structured context provision for downstream workflows

    The runtime layout:
        $WORK_DIR/
          .permission_probe          # One-time permission trigger file
          runtime/
            incidents/               # Runtime incident logs
            auth/                    # Auth state files
          runtime_state.json         # Current runtime state
          dependency_state.json      # Dependency availability state

    Script/Template Resolution Order:
        1. $WORK_DIR/scripts or $WORK_DIR/templates (user overrides)
        2. $SKILL_DIR/scripts or $SKILL_DIR/templates (canonical)
    """

    def __init__(
        self,
        profile_path: Path | str | None = None,
        work_dir: Path | str | None = None,
        skill_dir: Path | str | None = None,
    ):
        """Initialize the runtime manager.

        Args:
            profile_path: Path to profile.sh (default: ~/.config/linkedin-sourcing/profile.sh)
            work_dir: Override WORK_DIR (default: from profile or ~/Desktop/linkedin-sourcing)
            skill_dir: Override SKILL_DIR (default: resolved from this script)
        """
        self._profile_path = (
            Path(profile_path) if profile_path else DEFAULT_PROFILE_PATH
        )
        self._skill_dir = Path(skill_dir) if skill_dir else SKILL_DIR
        self._work_dir: Path | None = Path(work_dir) if work_dir else None
        self._profile: dict[str, str] | None = None
        self._runtime_state: dict[str, Any] | None = None
        self._dependency_state: dict[str, Any] | None = None

    def _resolve_profile(self) -> dict[str, str]:
        """Resolve profile configuration from profile.sh or defaults.

        Constructor-provided work_dir takes precedence over profile file.

        Returns:
            Dict with configuration values (WORK_DIR, CDP_PORT, etc.)
        """
        if self._profile is not None:
            return self._profile

        # Start with defaults
        profile: dict[str, str] = {
            "WORK_DIR": str(DEFAULT_WORK_DIR),
            "CDP_PORT": DEFAULT_CDP_PORT,
            "CHROME_PROFILE": "",
            "USER_EMAIL": "",
            "USER_NAME": "",
            "ACCOUNT_NAME": "",
        }

        # Load from profile file if exists
        if self._profile_path.exists():
            content = self._profile_path.read_text()
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Expand environment variables
                    value = os.path.expandvars(value)
                    profile[key] = value

        # Constructor-provided work_dir takes precedence
        if self._work_dir is not None:
            profile["WORK_DIR"] = str(self._work_dir)

        # Ensure CHROME_PROFILE defaults to $WORK_DIR/chrome-profile if not set
        if not profile.get("CHROME_PROFILE"):
            profile["CHROME_PROFILE"] = str(
                Path(profile["WORK_DIR"]) / "chrome-profile"
            )

        self._profile = profile
        return profile

    @property
    def work_dir(self) -> Path:
        """Resolved WORK_DIR path."""
        return Path(self._resolve_profile()["WORK_DIR"])

    @property
    def runtime_dir(self) -> Path:
        """Runtime directory path ($WORK_DIR/runtime)."""
        return self.work_dir / "runtime"

    @property
    def incidents_dir(self) -> Path:
        """Incidents directory path."""
        return self.runtime_dir / "incidents"

    @property
    def runtime_state_path(self) -> Path:
        """Path to runtime_state.json."""
        return self.work_dir / "runtime_state.json"

    @property
    def dependency_state_path(self) -> Path:
        """Path to dependency_state.json."""
        return self.work_dir / "dependency_state.json"

    @property
    def permission_probe_path(self) -> Path:
        """Path to .permission_probe file."""
        return self.work_dir / ".permission_probe"

    @property
    def browser_mode_path(self) -> Path:
        """Path to browser_mode.json."""
        return self.runtime_dir / "browser_mode.json"

    @property
    def auth_dir(self) -> Path:
        """Auth state directory path."""
        return self.runtime_dir / "auth"

    def ensure_permission_probe(self) -> bool:
        """Ensure the permission probe file exists in WORK_DIR.

        This file triggers the one-time permission request for WORK_DIR.
        After WORK_DIR is approved, subpaths do not need separate permission.

        Returns:
            True if probe was created, False if it already existed
        """
        self.work_dir.mkdir(parents=True, exist_ok=True)

        if self.permission_probe_path.exists():
            return False

        # Create probe file with timestamp
        probe_content = f"# Permission probe for linkedin-sourcing\n# Created: {datetime.now(timezone.utc).isoformat()}\n"
        self.permission_probe_path.write_text(probe_content)
        return True

    def ensure_runtime_dirs(self) -> None:
        """Ensure runtime directory structure exists."""
        for subdir in RUNTIME_SUBDIRS:
            (self.runtime_dir / subdir).mkdir(parents=True, exist_ok=True)

    def compute_bundle_hash(self) -> str:
        """Compute a content hash of the canonical bundle sources.

        Hashes the contents of scripts/, templates/, and SKILL.md to provide
        version visibility for tracking purposes. This hash is informational
        only - scripts are resolved directly from canonical paths.

        Returns:
            Hex digest of the bundle hash (first 16 chars for readability)
        """
        hasher = hashlib.sha256()

        # Hash directory contents (sorted for stability)
        for dir_name in BUNDLE_SOURCE_DIRS:
            dir_path = self._skill_dir / dir_name
            if dir_path.exists():
                files = sorted(dir_path.rglob("*"))
                for file_path in files:
                    if file_path.is_file() and not _should_ignore_path(file_path):
                        # Include relative path in hash
                        rel_path = file_path.relative_to(self._skill_dir)
                        hasher.update(str(rel_path).encode())
                        hasher.update(file_path.read_bytes())

        # Hash individual files
        for file_name in BUNDLE_SOURCE_FILES:
            file_path = self._skill_dir / file_name
            if file_path.exists():
                hasher.update(file_name.encode())
                hasher.update(file_path.read_bytes())

        return hasher.hexdigest()[:16]

    def _check_dependencies(self) -> dict[str, Any]:
        """Check runtime dependencies and return their state.

        Returns:
            Dict with dependency status information
        """
        deps: dict[str, Any] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "python": {
                "executable": sys.executable,
                "version": sys.version,
            },
            "agent_browser": {
                "available": False,
                "version": None,
                "error": None,
            },
            "openpyxl": {
                "available": False,
                "version": None,
                "error": None,
            },
        }

        # Check agent-browser
        try:
            result = subprocess.run(
                ["agent-browser", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            deps["agent_browser"]["available"] = result.returncode == 0
            if result.stdout:
                deps["agent_browser"]["version"] = result.stdout.strip()
        except FileNotFoundError:
            deps["agent_browser"]["error"] = "agent-browser not found in PATH"
        except subprocess.TimeoutExpired:
            deps["agent_browser"]["error"] = "agent-browser --version timed out"
        except Exception as e:
            deps["agent_browser"]["error"] = str(e)

        # Check openpyxl
        try:
            import openpyxl

            deps["openpyxl"]["available"] = True
            deps["openpyxl"]["version"] = openpyxl.__version__
        except ImportError:
            deps["openpyxl"]["error"] = "openpyxl not installed"
        except Exception as e:
            deps["openpyxl"]["error"] = str(e)

        return deps

    def _write_runtime_state(
        self,
        bundle_hash: str,
        sync_happened: bool = False,
    ) -> None:
        """Write runtime_state.json with current state.

        Args:
            bundle_hash: The bundle hash for version visibility
        """
        state = {
            "version": "2.0.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "work_dir": str(self.work_dir),
            "skill_dir": str(self._skill_dir),
            "bundle_hash": bundle_hash,
            "profile": self._resolve_profile(),
            "sync_happened": sync_happened,
            "canonical_paths": {
                "scripts_dir": str(self._skill_dir / "scripts"),
                "templates_dir": str(self._skill_dir / "templates"),
                "skill_md": str(self._skill_dir / "SKILL.md"),
            },
        }

        self.runtime_state_path.write_text(json.dumps(state, indent=2))
        self._runtime_state = state

    def _write_dependency_state(self, deps: dict[str, Any]) -> None:
        """Write dependency_state.json with dependency information.

        Args:
            deps: Dependency state dict from _check_dependencies()
        """
        self.dependency_state_path.write_text(json.dumps(deps, indent=2))
        self._dependency_state = deps

    def initialize(self, force_sync: bool = False) -> dict[str, Any]:
        """Initialize the runtime environment.

        This is the main entry point for runtime initialization. It:
        1. Ensures permission probe exists
        2. Ensures runtime directory structure
        3. Computes bundle hash for version visibility
        4. Writes runtime_state.json and dependency_state.json
        5. Returns structured context dict

        Args:
            force_sync: Ignored (kept for API compatibility)

        Returns:
            Structured runtime context dict with paths and states
        """
        # Step 1: Permission probe
        probe_created = self.ensure_permission_probe()

        # Step 2: Ensure directory structure
        self.ensure_runtime_dirs()

        previous_state = self.get_runtime_context()

        # Step 3: Compute bundle hash (for version visibility)
        bundle_hash = self.compute_bundle_hash()
        sync_happened = force_sync or previous_state is None
        if (
            previous_state is not None
            and previous_state.get("bundle_hash") != bundle_hash
        ):
            sync_happened = True

        # Step 4: Check dependencies
        deps = self._check_dependencies()

        # Step 5: Write state files
        self._write_runtime_state(bundle_hash, sync_happened)
        self._write_dependency_state(deps)

        # Build and return context
        profile = self._resolve_profile()
        context = {
            "work_dir": str(self.work_dir),
            "runtime_dir": str(self.runtime_dir),
            "bundle_hash": bundle_hash,
            "canonical_paths": {
                "scripts_dir": str(self._skill_dir / "scripts"),
                "templates_dir": str(self._skill_dir / "templates"),
                "skill_md": str(self._skill_dir / "SKILL.md"),
            },
            "incidents_dir": str(self.incidents_dir),
            "runtime_state_path": str(self.runtime_state_path),
            "dependency_state_path": str(self.dependency_state_path),
            "permission_probe_created": probe_created,
            "sync_happened": sync_happened,
            "profile": profile,
            "dependencies": deps,
        }

        return context

    def get_runtime_context(self) -> dict[str, Any] | None:
        """Get the current runtime context without initializing.

        Returns:
            Runtime context dict if runtime_state.json exists, else None
        """
        if not self.runtime_state_path.exists():
            return None

        try:
            state = json.loads(self.runtime_state_path.read_text())
            deps = (
                json.loads(self.dependency_state_path.read_text())
                if self.dependency_state_path.exists()
                else {}
            )

            return {
                "work_dir": state.get("work_dir"),
                "runtime_dir": str(Path(state["work_dir"]) / "runtime"),
                "bundle_hash": state.get("bundle_hash"),
                "canonical_paths": state.get("canonical_paths", {}),
                "incidents_dir": str(Path(state["work_dir"]) / "runtime" / "incidents"),
                "runtime_state_path": str(self.runtime_state_path),
                "dependency_state_path": str(self.dependency_state_path),
                "sync_happened": False,
                "profile": state.get("profile", {}),
                "dependencies": deps,
            }
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def resolve_script(self, script_name: str) -> Path | None:
        """Resolve a script path using the runtime resolution rules.

        Resolution order:
        1. $WORK_DIR/scripts/{name} (user override)
        2. $SKILL_DIR/scripts/{name} (canonical)

        Args:
            script_name: Name of the script to resolve

        Returns:
            Path to the script if found, None otherwise
        """
        # Check user override first
        override_path = self.work_dir / "scripts" / script_name
        if override_path.exists():
            return override_path

        # Fall back to canonical
        canonical_path = self._skill_dir / "scripts" / script_name
        if canonical_path.exists():
            return canonical_path

        return None

    def resolve_template(self, template_name: str) -> Path | None:
        """Resolve a template path using the runtime resolution rules.

        Resolution order:
        1. $WORK_DIR/templates/{name} (user override)
        2. $SKILL_DIR/templates/{name} (canonical)

        Args:
            template_name: Name of the template to resolve

        Returns:
            Path to the template if found, None otherwise
        """
        # Check user override first
        override_path = self.work_dir / "templates" / template_name
        if override_path.exists():
            return override_path

        # Fall back to canonical
        canonical_path = self._skill_dir / "templates" / template_name
        if canonical_path.exists():
            return canonical_path

        return None

    def get_browser_mode(self) -> dict[str, Any] | None:
        """Get the current browser mode configuration.

        Returns:
            Browser mode dict if configured, None otherwise
        """
        if not self.browser_mode_path.exists():
            return None

        try:
            return json.loads(self.browser_mode_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def save_browser_mode(
        self,
        mode: str,
        cdp_port: str | None = None,
        session_name: str | None = None,
        auth_file: str | None = None,
        headed: bool = True,
    ) -> None:
        """Save browser mode configuration.

        Args:
            mode: "cdp" or "agent-browser"
            cdp_port: CDP port to use (CDP mode)
            session_name: Session name for agent-browser managed session
            auth_file: Path to auth state file (for agent-browser mode)
            headed: Whether browser runs in headed mode
        """
        self.auth_dir.mkdir(parents=True, exist_ok=True)

        mode_data = {
            "mode": mode,
            "cdp_port": cdp_port,
            "session_name": session_name,
            "auth_file": auth_file,
            "headed": headed,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        self.browser_mode_path.write_text(json.dumps(mode_data, indent=2))

    def clear_browser_mode(self) -> None:
        """Clear saved browser mode configuration."""
        if self.browser_mode_path.exists():
            self.browser_mode_path.unlink()

    def get_auth_file_path(self) -> Path:
        """Get the path to the LinkedIn auth state file.

        Returns:
            Path to linkedin-auth.json
        """
        return self.auth_dir / "linkedin-auth.json"
