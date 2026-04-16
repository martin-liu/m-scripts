#!/usr/bin/env python3
"""Canonical project state management for LinkedIn sourcing workflow.

Provides a per-project project_state.json that tracks workflow checkpoint info
without persisting workflow metadata like phase order. Phase order is computed
at runtime via phase_registry. Excel remains the row-level source of truth.

Simplified state (Sprint 2):
    - project_id: Project identifier
    - workflow_mode: Workflow mode (reachout, review) - optional
    - current_phase: Current phase name
    - status: Current status (initialized, running, completed, failed, action_required)
    - action_required: Structured action required dict or None
    - updated_at: ISO timestamp
    - last_result_summary: Summary of last operation
    - last_error: Last error message or None

Usage:
    from project_state import load_project_state, save_project_state, update_project_state

    # Load or initialize state
    state = load_project_state(project_dir)

    # Update state
    update_project_state(project_dir, current_phase="extract", status="running")

    # Save explicit state
    save_project_state(project_dir, state)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


# State file version for compatibility checking
# Version 2: Simplified state without workflow_phases/next_phase (Sprint 2)
STATE_VERSION = 2


def get_state_path(project_dir: Path | str) -> Path:
    """Get the path to the project state file.

    Args:
        project_dir: Path to the project directory

    Returns:
        Path to project_state.json
    """
    return Path(project_dir) / "project_state.json"


def create_initial_state(
    project_id: str,
    workflow_mode: str = "reachout",
    current_phase: str = "bootstrap",
    status: str = "initialized",
) -> dict[str, Any]:
    """Create initial project state structure.

    Args:
        project_id: The project identifier
        workflow_mode: Workflow mode (reachout, review, etc.)
        current_phase: Initial phase name
        status: Initial status

    Returns:
        Initial state dictionary (simplified, no workflow_phases/next_phase)
    """
    return {
        "version": STATE_VERSION,
        "project_id": project_id,
        "workflow_mode": workflow_mode,
        "current_phase": current_phase,
        "status": status,
        "action_required": None,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_result_summary": None,
        "last_error": None,
    }


def load_project_state(project_dir: Path | str) -> dict[str, Any] | None:
    """Load project state from file.

    Args:
        project_dir: Path to the project directory

    Returns:
        State dict if valid, None if file doesn't exist or is invalid
    """
    state_path = get_state_path(project_dir)

    if not state_path.exists():
        return None

    try:
        content = state_path.read_text(encoding="utf-8")
        state = json.loads(content)

        # Basic validation: must be a dict with required fields
        if not isinstance(state, dict):
            return None

        required_fields = {"version", "project_id", "current_phase"}
        if not required_fields.issubset(state.keys()):
            return None

        # Version check (allow same major version)
        state_version = state.get("version", 0)
        if state_version != STATE_VERSION:
            # In future, could implement migration logic here
            # For now, try to load anyway if it has required fields
            pass

        # Sprint 2: Remove legacy fields if present (workflow_phases, next_phase)
        # These are now computed at runtime via phase_registry
        state.pop("workflow_phases", None)
        state.pop("next_phase", None)

        return state
    except (json.JSONDecodeError, OSError, IOError):
        return None


def save_project_state(
    project_dir: Path | str,
    state: dict[str, Any],
) -> bool:
    """Save project state to file atomically.

    Uses temp file + rename pattern for atomic writes. Preserves old
    valid state if write fails or is interrupted.

    Args:
        project_dir: Path to the project directory
        state: State dictionary to save

    Returns:
        True if saved successfully, False otherwise
    """
    state_path = get_state_path(project_dir)

    # Ensure parent directory exists
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, IOError):
        return False

    # Update timestamp
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Sprint 2: Ensure we don't persist computed fields
    state.pop("workflow_phases", None)
    state.pop("next_phase", None)

    # Atomic write: temp file + rename
    temp_path = state_path.with_suffix(".tmp")
    try:
        temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp_path.replace(state_path)
        return True
    except (OSError, IOError):
        # Clean up temp file if it exists
        try:
            if temp_path.exists():
                temp_path.unlink()
        except (OSError, IOError):
            pass
        return False


def update_project_state(
    project_dir: Path | str,
    project_id: str | None = None,
    current_phase: str | None = None,
    status: str | None = None,
    action_required: dict[str, Any] | None = None,
    last_result_summary: str | None = None,
    last_error: str | None = None,
    workflow_mode: str | None = None,
) -> dict[str, Any]:
    """Update project state with new values.

    Loads existing state or creates new if none exists, applies updates,
    and saves back to file.

    Args:
        project_dir: Path to the project directory
        project_id: Project identifier (optional, used when creating new state)
        current_phase: New current phase (optional)
        status: New status (optional)
        action_required: Structured action required dict (optional)
        last_result_summary: Summary of last operation result (optional)
        last_error: Last error message (optional)
        workflow_mode: Workflow mode (optional, only used when creating new state)

    Returns:
        Updated state dictionary
    """
    project_dir = Path(project_dir)

    # Load existing or create new
    state = load_project_state(project_dir)
    if state is None:
        # Use provided project_id, or try to get from config.sh, or default to "unknown"
        resolved_project_id = (
            project_id or _extract_project_id_from_config(project_dir) or "unknown"
        )
        state = create_initial_state(
            project_id=resolved_project_id,
            workflow_mode=workflow_mode or "reachout",
        )

    # Apply updates
    if current_phase is not None:
        state["current_phase"] = current_phase

    if status is not None:
        state["status"] = status

    if action_required is False:
        # Explicit clear
        state["action_required"] = None
    elif action_required is not None:
        state["action_required"] = action_required

    if last_result_summary is not None:
        state["last_result_summary"] = last_result_summary

    if last_error is False:
        # Explicit clear
        state["last_error"] = None
    elif last_error is not None:
        state["last_error"] = last_error

    # Save updated state
    save_project_state(project_dir, state)

    return state


def _extract_project_id_from_config(project_dir: Path) -> str | None:
    """Extract PROJECT_ID from config.sh in project directory.

    Args:
        project_dir: Path to the project directory

    Returns:
        Project ID string if found, None otherwise
    """
    config_path = project_dir / "config.sh"
    if not config_path.exists():
        return None

    try:
        content = config_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("PROJECT_ID="):
                # Extract value, handling quotes
                value = line[len("PROJECT_ID=") :]
                value = value.strip().strip('"').strip("'")
                return value if value else None
    except (OSError, IOError):
        pass

    return None


def get_project_state_summary(project_dir: Path | str) -> dict[str, Any]:
    """Get a summary of project state for display/logging.

    Args:
        project_dir: Path to the project directory

    Returns:
        Summary dict with key state fields
    """
    state = load_project_state(project_dir)

    if state is None:
        return {
            "exists": False,
            "project_id": None,
            "current_phase": None,
            "status": None,
        }

    return {
        "exists": True,
        "project_id": state.get("project_id"),
        "current_phase": state.get("current_phase"),
        "status": state.get("status"),
        "action_required": state.get("action_required") is not None,
        "updated_at": state.get("updated_at"),
    }


# Legacy compatibility: These constants are kept for backward compatibility
# but should not be used in new code. Use phase_registry instead.
REACHOUT_WORKFLOW_PHASES = [
    "bootstrap",
    "create_search",
    "extract",
    "filter",
    "enrich",
    "draft",
    "review",
    "send",
]

REVIEW_WORKFLOW_PHASES = [
    "scan",
    "draft",
    "review",
    "send",
]


def _get_next_phase(current_phase: str, workflow_phases: list[str]) -> str | None:
    """Get the next phase in the workflow sequence.

    DEPRECATED: Use phase_registry.get_next_phase() instead.
    Kept for backward compatibility with existing tests.

    Args:
        current_phase: Current phase name
        workflow_phases: List of workflow phases in order

    Returns:
        Next phase name or None if at end
    """
    try:
        idx = workflow_phases.index(current_phase)
        if idx + 1 < len(workflow_phases):
            return workflow_phases[idx + 1]
    except ValueError:
        pass
    return None
