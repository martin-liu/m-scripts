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
        "description": "Human review of drafted messages",
        "requires_browser": False,
        "is_automated": False,
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


def get_command_for_phase(phase: str, project_ref: str | None = None) -> str:
    """Get the command to run a specific phase.

    Args:
        phase: Phase name
        project_ref: Optional project reference for context

    Returns:
        Command string to run the phase
    """
    ref = project_ref or "<project_ref>"

    command_map = {
        "bootstrap": f"python3 scripts/bootstrap_project.py --project-id {ref}",
        "create_search": f"python3 scripts/run_create_search.py --project {ref}",
        "extract": f"python3 scripts/run_extraction.py --project {ref}",
        "filter": f"python3 scripts/run_filter.py {ref}",
        "enrich": f"python3 scripts/run_enrich.py --project {ref}",
        "draft": f"python3 scripts/run_draft.py {ref}",
        "review": f"# Open workbook and review drafted messages: $WORK_DIR/projects/{ref}/workbook.xlsx",
        "send": f"python3 scripts/run_send.py --project {ref}",
    }

    return command_map.get(phase, f"# Unknown phase: {phase}")


def get_phase_from_command(command: str) -> str | None:
    """Extract phase name from a command string.

    Args:
        command: Command string

    Returns:
        Phase name if recognized, None otherwise
    """
    # Map of script names to phases
    script_phase_map = {
        "bootstrap_project": "bootstrap",
        "run_create_search": "create_search",
        "run_extraction": "extract",
        "run_filter": "filter",
        "run_enrich": "enrich",
        "run_draft": "draft",
        "run_send": "send",
    }

    for script, phase in script_phase_map.items():
        if script in command:
            return phase

    return None
