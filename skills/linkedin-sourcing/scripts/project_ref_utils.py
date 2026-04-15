#!/usr/bin/env python3
"""Project reference resolution utilities for linkedin-sourcing.

Provides safe resolution of project references (local PROJECT_ID, LinkedIn Recruiter URL,
or bare numeric ID) to canonical project paths and configuration.

Fail-closed semantics:
- No match => clear error
- Multiple matches => clear ambiguity error
- Never guess
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from runtime_manager import RuntimeManager


def extract_recruiter_id_from_url(url: str) -> str | None:
    """Extract numeric recruiter project ID from a LinkedIn Recruiter URL.

    Args:
        url: LinkedIn Recruiter URL (e.g., https://linkedin.com/talent/hire/12345/...)

    Returns:
        Recruiter project ID string if found, None otherwise
    """
    # Match /talent/hire/{numeric_id} followed by /, ?, #, or end of string
    # This accepts URLs with or without trailing slash, and with query params or hash
    match = re.search(r"/talent/hire/(\d+)(?:/|$|\?|#)", url)
    return match.group(1) if match else None


def is_recruiter_url(ref: str) -> bool:
    """Check if reference looks like a LinkedIn Recruiter URL.

    Args:
        ref: Project reference string

    Returns:
        True if ref appears to be a LinkedIn Recruiter URL
    """
    return "/talent/hire/" in ref and extract_recruiter_id_from_url(ref) is not None


def is_bare_numeric_id(ref: str) -> bool:
    """Check if reference is a bare numeric ID.

    Args:
        ref: Project reference string

    Returns:
        True if ref is a numeric string only
    """
    return ref.isdigit()


def is_config_path(ref: str) -> bool:
    """Check if reference looks like a config file path.

    Args:
        ref: Project reference string

    Returns:
        True if ref ends with config.sh or is a local path (not URL)
    """
    # URLs should not be treated as config paths
    if ref.startswith("http://") or ref.startswith("https://"):
        return False
    return ref.endswith("config.sh") or "/" in ref or "\\" in ref


def scan_projects_for_recruiter_id(work_dir: Path, recruiter_id: str) -> list[Path]:
    """Scan $WORK_DIR/projects/*/config.sh for configs matching recruiter_id.

    Args:
        work_dir: The working directory (WORK_DIR)
        recruiter_id: The LinkedIn Recruiter project ID to search for

    Returns:
        List of config file paths that contain the recruiter_id in their RECRUITER_PROJECT_URL
    """
    matches: list[Path] = []
    projects_dir = work_dir / "projects"

    if not projects_dir.exists():
        return matches

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        config_path = project_dir / "config.sh"
        if not config_path.exists():
            continue

        try:
            content = config_path.read_text()
            # Look for RECRUITER_PROJECT_URL containing the recruiter_id
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("RECRUITER_PROJECT_URL="):
                    # Extract URL value
                    url_match = re.search(
                        r'RECRUITER_PROJECT_URL=["\']?([^"\'\n]+)', line
                    )
                    if url_match:
                        url = url_match.group(1)
                        # Extract the recruiter ID from the URL and compare exactly
                        url_recruiter_id = extract_recruiter_id_from_url(url)
                        if url_recruiter_id == recruiter_id:
                            matches.append(config_path)
                            break
        except (OSError, IOError):
            continue

    return matches


def scan_projects_for_project_id(work_dir: Path, project_id: str) -> list[Path]:
    """Scan $WORK_DIR/projects/*/config.sh for configs matching PROJECT_ID.

    Args:
        work_dir: The working directory (WORK_DIR)
        project_id: The PROJECT_ID value to search for

    Returns:
        List of config file paths that have PROJECT_ID matching the given value
    """
    matches: list[Path] = []
    projects_dir = work_dir / "projects"

    if not projects_dir.exists():
        return matches

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        config_path = project_dir / "config.sh"
        if not config_path.exists():
            continue

        try:
            content = config_path.read_text()
            # Look for PROJECT_ID= line
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("PROJECT_ID="):
                    # Extract PROJECT_ID value
                    id_match = re.search(r'PROJECT_ID=["\']?([^"\'\n]+)', line)
                    if id_match:
                        config_project_id = id_match.group(1)
                        if config_project_id == project_id:
                            matches.append(config_path)
                            break
        except (OSError, IOError):
            continue

    return matches


def parse_config_file(config_path: Path) -> dict[str, str]:
    """Parse a shell config file and extract key-value pairs.

    Args:
        config_path: Path to config.sh file

    Returns:
        Dict of config key-value pairs
    """
    config: dict[str, str] = {}

    if not config_path.exists():
        return config

    try:
        for line in config_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                config[key] = value
    except (OSError, IOError):
        pass

    return config


def resolve_project_ref(
    ref: str,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Resolve a project reference to canonical paths and IDs.

    Accepts:
    - Direct config.sh path (e.g., /path/to/project/config.sh)
    - Local PROJECT_ID (e.g., "my_project" -> $WORK_DIR/projects/my_project/config.sh)
    - LinkedIn Recruiter URL (e.g., https://linkedin.com/talent/hire/12345/...)
    - Bare numeric Recruiter project ID (e.g., "12345")

    Args:
        ref: Project reference string
        work_dir: Optional WORK_DIR override (default: from RuntimeManager)

    Returns:
        Dict with:
            - success: bool - whether resolution succeeded
            - config_path: Path | None - path to config.sh
            - local_project_id: str | None - local PROJECT_ID from config
            - workbook_path: Path | None - path to workbook
            - recruiter_project_id: str | None - LinkedIn Recruiter project ID
            - error: str | None - error message if failed
    """
    result: dict[str, Any] = {
        "success": False,
        "config_path": None,
        "local_project_id": None,
        "workbook_path": None,
        "recruiter_project_id": None,
        "error": None,
    }

    # Resolve work_dir
    if work_dir is None:
        try:
            manager = RuntimeManager()
            work_dir = manager.work_dir
        except Exception as e:
            result["error"] = f"Failed to resolve WORK_DIR: {e}"
            return result

    config_path: Path | None = None
    recruiter_id: str | None = None

    # Case 1: Direct config path
    if is_config_path(ref):
        config_path = Path(ref).expanduser().resolve()
        if not config_path.exists():
            result["error"] = f"Config file not found: {config_path}"
            return result

    # Case 2: LinkedIn Recruiter URL
    elif is_recruiter_url(ref):
        recruiter_id = extract_recruiter_id_from_url(ref)
        assert recruiter_id is not None  # Guaranteed by is_recruiter_url
        matches = scan_projects_for_recruiter_id(work_dir, recruiter_id)

        if len(matches) == 0:
            result["error"] = (
                f"No project found for Recruiter URL (ID: {recruiter_id}). "
                f"Run bootstrap to create a project for this Recruiter project."
            )
            return result
        elif len(matches) > 1:
            match_list = ", ".join(str(m.parent.name) for m in matches)
            result["error"] = (
                f"Ambiguous reference: multiple projects match Recruiter ID {recruiter_id}: "
                f"{match_list}. Use explicit --config with the desired project config."
            )
            return result
        else:
            config_path = matches[0]

    # Case 3: Bare numeric ID - try to match by Recruiter ID first
    # Note: We check local PROJECT_ID after this to allow numeric project names
    # Only process this case if config_path wasn't already set in Case 1 or 2
    if config_path is None and is_bare_numeric_id(ref):
        recruiter_id = ref
        matches = scan_projects_for_recruiter_id(work_dir, recruiter_id)

        # Check for ambiguity: numeric ID matches both a local PROJECT_ID directory
        # and a recruiter ID in config URLs
        local_project_path = work_dir / "projects" / ref / "config.sh"
        local_project_exists = local_project_path.exists()
        recruiter_matches_count = len(matches)

        # Fail closed if ambiguous: local project exists AND recruiter ID matches config(s)
        if local_project_exists and recruiter_matches_count > 0:
            # Check if the local project is already in the matches
            local_in_matches = any(m == local_project_path for m in matches)
            if local_in_matches and recruiter_matches_count == 1:
                # Local project is the only match - use it
                config_path = matches[0]
            else:
                # Ambiguous: local project exists and recruiter ID matches (different) config(s)
                match_list = ", ".join(str(m.parent.name) for m in matches)
                result["error"] = (
                    f"Ambiguous reference: numeric ID '{ref}' matches local project "
                    f"directory and Recruiter ID {recruiter_id} in config(s): "
                    f"{match_list}. Use explicit --config with the desired project config."
                )
                return result
        elif recruiter_matches_count == 1:
            # Exactly one match by recruiter ID - use it
            config_path = matches[0]
        elif recruiter_matches_count > 1:
            # Multiple matches by recruiter ID - ambiguous
            match_list = ", ".join(str(m.parent.name) for m in matches)
            result["error"] = (
                f"Ambiguous reference: multiple projects match Recruiter ID {recruiter_id}: "
                f"{match_list}. Use explicit --config with the desired project config."
            )
            return result
        # If no recruiter matches, fall through to check local PROJECT_ID

    # Case 4: Local PROJECT_ID (also handles numeric IDs that didn't match recruiter IDs)
    # Scan all project configs and match by PROJECT_ID value (folder name is cosmetic)
    if config_path is None:
        matches = scan_projects_for_project_id(work_dir, ref)

        if len(matches) == 1:
            config_path = matches[0]
        elif len(matches) > 1:
            # Ambiguous: multiple projects have the same PROJECT_ID
            match_list = ", ".join(str(m.parent.name) for m in matches)
            result["error"] = (
                f"Ambiguous reference: multiple projects have PROJECT_ID '{ref}': "
                f"{match_list}. Use explicit --config with the desired project config."
            )
            return result
        elif is_bare_numeric_id(ref):
            # Numeric ID that didn't match recruiter ID or PROJECT_ID
            result["error"] = (
                f"No project found for Recruiter ID {ref}. "
                f"Run bootstrap to create a project for this Recruiter project."
            )
            return result
        else:
            result["error"] = (
                f"Project not found: {ref}. No project with PROJECT_ID='{ref}' found"
            )
            return result

    # Parse config to extract IDs and derive workbook path
    if config_path is None:
        result["error"] = "Internal error: config_path is None after resolution"
        return result

    config = parse_config_file(config_path)
    local_project_id = config.get("PROJECT_ID")

    # Extract recruiter_id from config if not already known
    if recruiter_id is None:
        recruiter_url = config.get("RECRUITER_PROJECT_URL", "")
        recruiter_id = extract_recruiter_id_from_url(recruiter_url)

    # Derive workbook path - prefer new layout (workbook in project dir), fallback to legacy
    # New layout: $WORK_DIR/projects/<folder>/workbook.xlsx
    new_layout_workbook = config_path.parent / "workbook.xlsx"

    # Legacy layout: $WORK_DIR/projects/{PROJECT_ID}.xlsx
    legacy_workbook = (
        work_dir / "projects" / f"{local_project_id or config_path.parent.name}.xlsx"
    )

    if new_layout_workbook.exists():
        workbook_path = new_layout_workbook
    elif legacy_workbook.exists():
        workbook_path = legacy_workbook
    else:
        # Default to new layout for new projects
        workbook_path = new_layout_workbook

    result["success"] = True
    result["config_path"] = config_path
    result["local_project_id"] = local_project_id or config_path.parent.name
    result["workbook_path"] = workbook_path
    result["recruiter_project_id"] = recruiter_id

    return result
