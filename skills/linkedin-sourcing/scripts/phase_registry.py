#!/usr/bin/env python3
"""Phase registry for LinkedIn sourcing workflow.

Provides canonical phase ordering and phase metadata without persisting
workflow structure in project_state.json. Phase order is computed at runtime
based on workflow_mode.

Usage:
    from phase_registry import get_phase_order, get_next_phase, get_phase_metadata

    phases = get_phase_order("reachout")
    next_phase = get_next_phase("filter", "reachout")
    meta = get_phase_metadata("draft")
"""

from __future__ import annotations

from typing import Any

# Standard workflow phases for reachout mode (loop starts at create_search)
# bootstrap is a pre-loop entrypoint, not a runnable loop phase
REACHOUT_PHASES = [
    "create_search",
    "confirm_search",
    "extract",
    "filter",
    "enrich",
    "draft",
    "review",
    "send",
]

# Standard workflow phases for review mode
REVIEW_PHASES = [
    "draft",
    "review",
    "send",
]

# Phase metadata: human-readable names and whether phase requires browser
PHASE_METADATA: dict[str, dict[str, Any]] = {
    "bootstrap": {
        "name": "Bootstrap",
        "description": "Initialize project structure and configuration",
        "requires_browser": False,
        "is_automated": True,
    },
    "create_search": {
        "name": "Create Search",
        "description": "Create LinkedIn Recruiter search from config",
        "requires_browser": True,
        "is_automated": True,
    },
    "confirm_search": {
        "name": "Confirm Search",
        "description": "Human confirmation of search filters before extraction",
        "requires_browser": False,
        "is_automated": False,
    },
    "extract": {
        "name": "Extract",
        "description": "Extract candidates from LinkedIn Recruiter",
        "requires_browser": True,
        "is_automated": True,
    },
    "filter": {
        "name": "Filter",
        "description": "Filter candidates by title exclusion rules",
        "requires_browser": False,
        "is_automated": True,
    },
    "enrich": {
        "name": "Enrich",
        "description": "Enrich candidate profiles with additional data",
        "requires_browser": True,
        "is_automated": True,
    },
    "draft": {
        "name": "Draft",
        "description": "Generate personalized inmail drafts",
        "requires_browser": False,
        "is_automated": True,
    },
    "review": {
        "name": "Review",
        "description": "Approve drafted messages for sending",
        "requires_browser": False,
        "is_automated": True,
    },
    "send": {
        "name": "Send",
        "description": "Send inmails to approved candidates",
        "requires_browser": True,
        "is_automated": True,
    },
}


def get_phase_order(workflow_mode: str = "reachout") -> list[str]:
    """Get the ordered list of phases for a workflow mode.

    Args:
        workflow_mode: Workflow mode ("reachout" or "review")

    Returns:
        List of phase names in execution order
    """
    if workflow_mode == "review":
        return REVIEW_PHASES.copy()
    return REACHOUT_PHASES.copy()


def get_next_phase(current_phase: str, workflow_mode: str = "reachout") -> str | None:
    """Get the next phase in the workflow sequence.

    Args:
        current_phase: Current phase name
        workflow_mode: Workflow mode ("reachout" or "review")

    Returns:
        Next phase name or None if at end
    """
    phases = get_phase_order(workflow_mode)
    try:
        idx = phases.index(current_phase)
        if idx + 1 < len(phases):
            return phases[idx + 1]
    except ValueError:
        pass
    return None


def get_phase_metadata(phase: str) -> dict[str, Any]:
    """Get metadata for a phase.

    Args:
        phase: Phase name

    Returns:
        Phase metadata dict, or default metadata if phase unknown
    """
    return PHASE_METADATA.get(
        phase,
        {
            "name": phase.capitalize(),
            "description": f"Phase: {phase}",
            "requires_browser": False,
            "is_automated": True,
        },
    )


def is_valid_phase(phase: str, workflow_mode: str = "reachout") -> bool:
    """Check if a phase name is valid for a workflow mode.

    Args:
        phase: Phase name to check
        workflow_mode: Workflow mode ("reachout" or "review")

    Returns:
        True if phase is valid for the workflow mode
    """
    return phase in get_phase_order(workflow_mode)
