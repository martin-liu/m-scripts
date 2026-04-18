#!/usr/bin/env python3
"""Authoritative status command for LinkedIn sourcing projects.

Given a project reference, returns the current phase, status, and exactly
what command to run next. Uses observable state from project_state.json
plus workbook next_action rows to determine the next phase.

The loop is the primary workflow. Always use the loop command to resume.

Usage:
    python3 status.py <project_ref>
    python3 status.py my_project
    python3 status.py 12345
    python3 status.py https://linkedin.com/talent/hire/12345/...

Output (JSON):
    {
        "project_ref": "my_project",
        "project_id": "my_project",
        "project_dir": "/path/to/project",
        "current_phase": "filter",
        "status": "completed",
        "workflow_mode": "reachout",
        "next_phase": "enrich",
        "loop_command": "python3 scripts/run_reachout_loop.py --project my_project",
        "action_required": null,
        "workbook_summary": {
            "total_rows": 10,
            "by_next_action": {"enrich": 5, "done": 5}
        },
        "ready": true,
        "message": "Project is ready to run: enrich"
    }
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from project_ref_utils import resolve_project_ref
from project_state import load_project_state
from phase_registry import (
    get_next_phase,
    get_phase_metadata,
)


def get_loop_command(project_ref: str, confirm_send: bool = False) -> str:
    """Get the canonical loop command to resume workflow.

    The loop is the primary workflow driver. Always use this command
    to resume after resolving blockers or boundaries.

    Args:
        project_ref: Project reference (ID, URL, or config path)
        confirm_send: Whether to include --confirm-send flag

    Returns:
        Command string to run the loop
    """
    script_path = shlex.quote(str(SCRIPT_DIR / "run_reachout_loop.py"))
    quoted_project_ref = shlex.quote(project_ref)
    base_cmd = f"python3 {script_path} --project {quoted_project_ref}"
    if confirm_send:
        return f"{base_cmd} --confirm-send"
    return base_cmd


def get_loop_resume_guidance(
    action_required: dict[str, Any] | None,
    project_ref: str,
) -> dict[str, Any] | None:
    """Generate guidance for resuming the loop after resolving a blocker.

    The loop is the primary workflow. After resolving any blocker,
    always rerun the loop command - it will pick up where it left off.

    Args:
        action_required: The action_required dict from project state
        project_ref: Project reference for command generation

    Returns:
        Guidance dict with resolution steps and resume command, or None
    """
    if action_required is None:
        return None

    code = action_required.get("code", "unknown")
    summary = action_required.get("summary", "Manual intervention needed")
    details = action_required.get("details", "")
    steps = action_required.get("steps", [])
    actor = action_required.get("actor", "agent")

    # Build guidance based on blocker type
    # Mental model: resolve it, then rerun the loop
    guidance = {
        "code": code,
        "summary": summary,
        "details": details,
        "steps": steps,
        "actor": actor,
        "resolve_now": "",
        "then_run": get_loop_command(project_ref),
    }

    if code == "search_not_configured":
        guidance["resolve_now"] = (
            "Open the Recruiter search page in Chrome and configure the candidate search using the provided search brief"
        )
    elif code in {"browser_manual_intervention", "browser_blocked"}:
        guidance["resolve_now"] = "Complete the browser task in Chrome"
    elif code == "auth_required":
        guidance["resolve_now"] = "Log in to LinkedIn Recruiter in the browser"
    elif code == "create_search_failed":
        guidance["resolve_now"] = "Fix the search configuration issue"
    elif actor == "user":
        guidance["resolve_now"] = (
            "Resolve the blocker in the browser, then rerun the loop"
        )
    else:
        guidance["resolve_now"] = "Resolve the blocker using the steps above"

    return guidance


def get_workbook_summary(workbook_path: Path) -> dict[str, Any]:
    """Get summary of workbook state by next_action.

    Args:
        workbook_path: Path to workbook.xlsx

    Returns:
        Dict with total rows and counts by next_action
    """
    try:
        from excel_utils import read

        rows = read(str(workbook_path))

        by_next_action: dict[str, int] = {}
        for row in rows:
            action = row.get("next_action") or "(none)"
            by_next_action[action] = by_next_action.get(action, 0) + 1

        return {
            "total_rows": len(rows),
            "by_next_action": by_next_action,
        }
    except Exception:
        return {
            "total_rows": 0,
            "by_next_action": {},
            "error": "Failed to read workbook",
        }


def determine_next_phase(
    current_phase: str,
    phase_status: str,
    workbook_summary: dict[str, Any],
    workflow_mode: str = "reachout",
    action_required: dict[str, Any] | None = None,
) -> tuple[str | None, str, bool]:
    """Determine the next phase based on state and workbook content.

    Uses observable state from workbook next_action rows to determine
    what should happen next, not just persisted phase.

    Args:
        current_phase: Current phase from project_state
        phase_status: Current status from project_state
        workbook_summary: Workbook summary from get_workbook_summary
        workflow_mode: Workflow mode ("reachout" or "review")
        action_required: Optional action_required dict from project_state

    Returns:
        Tuple of (next_phase, message, ready)
    """
    # Block if workbook is unreadable - status must be authoritative
    if workbook_summary.get("error"):
        return None, f"Workbook unreadable: {workbook_summary['error']}", False

    by_action = workbook_summary.get("by_next_action", {})

    # If there's an action_required field present, we're blocked regardless of status value
    # This handles cases like create_search persisting status='search_not_configured' with action_required
    if action_required is not None:
        return None, "Action required before proceeding", False

    # Bootstrap handoff: freshly bootstrapped projects should proceed to create_search
    if current_phase == "bootstrap" and phase_status == "completed":
        return "create_search", "Bootstrap complete; proceed to create_search", True

    # If current phase failed, stay there
    if phase_status == "failed":
        return current_phase, f"Phase '{current_phase}' failed - needs attention", False

    # If current phase is running, we're not ready for next
    if phase_status == "running":
        return None, f"Phase '{current_phase}' is currently running", False

    # Check workbook next_action to determine actual next work
    # This is the "observable state" that takes precedence over persisted phase

    # If there are rows waiting for filter
    if by_action.get("filter", 0) > 0:
        return "filter", f"{by_action['filter']} rows ready for filter", True

    # If there are rows waiting for enrichment
    if by_action.get("enrich", 0) > 0:
        return "enrich", f"{by_action['enrich']} rows ready for enrich", True

    # If there are rows waiting for draft
    if by_action.get("draft", 0) > 0:
        return "draft", f"{by_action['draft']} rows ready for draft", True

    # If there are rows waiting for review (human stop boundary)
    if by_action.get("review", 0) > 0:
        return "review", f"{by_action['review']} rows ready for human review", True

    # If there are rows waiting to be sent
    if by_action.get("send", 0) > 0:
        return "send", f"{by_action['send']} rows ready to send", True

    # If all rows are done, we're at the end
    total_rows = workbook_summary.get("total_rows", 0)
    done_count = by_action.get("done", 0)
    if total_rows > 0 and done_count == total_rows:
        return None, "All rows completed", True

    # Empty successful extraction is a terminal state - no work to do
    if current_phase == "extract" and phase_status == "completed" and total_rows == 0:
        return None, "Extraction complete - no candidates found", True

    # No specific work found - follow phase order from current phase
    next_in_sequence = get_next_phase(current_phase, workflow_mode)
    if next_in_sequence:
        meta = get_phase_metadata(next_in_sequence)
        if meta.get("is_automated", True):
            return next_in_sequence, f"Proceed to {next_in_sequence}", True
        else:
            # Human stop boundary (like review)
            return next_in_sequence, f"Human action required: {next_in_sequence}", True

    return None, "Workflow complete", True


def get_status(project_ref: str, work_dir: Path | None = None) -> dict[str, Any]:
    """Get comprehensive status for a project reference.

    Args:
        project_ref: Project reference (ID, URL, or config path)
        work_dir: Optional WORK_DIR override

    Returns:
        Status dict with phase, loop command, and readiness
    """
    result: dict[str, Any] = {
        "project_ref": project_ref,
        "project_id": None,
        "project_dir": None,
        "config_path": None,
        "workbook_path": None,
        "current_phase": None,
        "status": None,
        "workflow_mode": "reachout",
        "next_phase": None,
        "loop_command": None,
        "loop_resume_guidance": None,
        "action_required": None,
        "workbook_summary": None,
        "ready": False,
        "message": "",
        "error": None,
    }

    # Resolve project reference
    resolution = resolve_project_ref(project_ref, work_dir)

    if not resolution["success"]:
        result["error"] = resolution.get("error", "Failed to resolve project reference")
        result["message"] = f"Error: {result['error']}"
        return result

    result["config_path"] = str(resolution["config_path"])
    result["project_id"] = resolution["local_project_id"]
    result["project_dir"] = str(resolution["config_path"].parent)
    result["workbook_path"] = str(resolution["workbook_path"])
    result["project_dir_name"] = resolution.get(
        "project_dir_name", resolution["local_project_id"]
    )

    # Load project state
    project_dir = Path(result["project_dir"])
    state = load_project_state(project_dir)

    if state is None:
        result["error"] = "No project state found - project may need bootstrap"
        result["message"] = "Error: Project state not found"
        return result

    result["current_phase"] = state.get("current_phase")
    result["status"] = state.get("status")
    result["workflow_mode"] = state.get("workflow_mode", "reachout")
    result["action_required"] = state.get("action_required")

    # Get workbook summary
    workbook_path = Path(result["workbook_path"])
    if workbook_path.exists():
        result["workbook_summary"] = get_workbook_summary(workbook_path)
    else:
        # Missing workbook is a blocker - extraction hasn't run yet
        result["workbook_summary"] = {
            "total_rows": 0,
            "by_next_action": {},
            "error": "Workbook not found - project may need extraction",
        }

    # Determine next phase
    next_phase, message, ready = determine_next_phase(
        result["current_phase"] or "create_search",
        result["status"] or "unknown",
        result["workbook_summary"],
        result["workflow_mode"],
        result["action_required"],
    )

    result["next_phase"] = next_phase
    result["ready"] = ready
    result["message"] = message

    # Generate loop command - the primary way to resume workflow
    if result["project_id"]:
        result["loop_command"] = get_loop_command(result["project_id"])

    # Generate loop resume guidance when blocked
    if result["action_required"]:
        result["loop_resume_guidance"] = get_loop_resume_guidance(
            result["action_required"],
            result["project_id"] or project_ref,
        )

    # Compatibility shim: next_command for existing JSON consumers
    # Points to the canonical loop command as the primary workflow path
    result["next_command"] = result["loop_command"]

    return result


def main():
    """CLI entry point."""
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]) or len(sys.argv) < 2:
        print(
            f"Normal workflow: python3 {SCRIPT_DIR / 'run_reachout_loop.py'} --project <project_ref>",
            file=sys.stderr,
        )
        print("Usage: python3 status.py <project_ref>", file=sys.stderr)
        print(
            "  project_ref: PROJECT_ID, Recruiter URL, or config.sh path",
            file=sys.stderr,
        )
        sys.exit(0 if any(arg in ("-h", "--help") for arg in sys.argv[1:]) else 1)

    project_ref = sys.argv[1]

    # Optional: --json flag for JSON output (default)
    # --pretty for human-readable output
    pretty = "--pretty" in sys.argv

    status = get_status(project_ref)

    if pretty:
        # Human-readable output
        if status.get("error"):
            print(f"Error: {status['error']}")
            sys.exit(1)

        print(f"Project: {status['project_id']}")
        print(f"Directory: {status['project_dir']}")
        print(f"Current Phase: {status['current_phase']}")
        print(f"Status: {status['status']}")
        print(f"Workflow Mode: {status['workflow_mode']}")

        summary = status.get("workbook_summary", {})
        print(f"\nWorkbook: {summary.get('total_rows', 0)} total rows")
        by_action = summary.get("by_next_action", {})
        if by_action:
            print("By next_action:")
            for action, count in sorted(by_action.items()):
                print(f"  - {action}: {count}")

        print(f"\nNext Phase: {status['next_phase'] or 'None'}")
        print(f"Ready: {'Yes' if status['ready'] else 'No'}")
        print(f"Message: {status['message']}")

        # Show blocker guidance if action_required
        if status.get("action_required"):
            guidance = status.get("loop_resume_guidance", {})
            actor_label = (
                "User must resolve now"
                if guidance.get("actor") == "user"
                else "Agent should resolve now"
            )
            print(
                f"\n⚠️  Action Required: {guidance.get('summary', 'Manual intervention needed')}"
            )
            if guidance.get("details"):
                print(f"  {guidance['details']}")
            if guidance.get("steps"):
                print(f"\nSteps:")
                for step in guidance["steps"]:
                    print(f"  - {step}")
            if guidance.get("resolve_now"):
                print(f"\n{actor_label}:")
                print(f"  {guidance['resolve_now']}")
            if status.get("loop_command"):
                print(f"\nThen run:")
                print(f"  {status['loop_command']}")
        elif status.get("next_phase") in ("review", "send"):
            # Boundary guidance with explicit loop resume command
            next_phase = status["next_phase"]
            if next_phase == "review":
                print(f"\n🛑 Boundary: Review required")
                print(f"  Open the workbook and review drafted messages")
                print(f"\nAfter review, run:")
                print(f"  {status['loop_command']}")
            elif next_phase == "send":
                print(f"\n🛑 Boundary: Send confirmation required")
                print(f"  Review messages in workbook, then run with --confirm-send:")
                print(f"  {status['loop_command']} --confirm-send")
        elif status.get("loop_command"):
            # Normal operation - show loop command
            print(f"\nRun the loop:")
            print(f"  {status['loop_command']}")
    else:
        # JSON output
        print(json.dumps(status, indent=2, default=str))

        if status.get("error"):
            sys.exit(1)


if __name__ == "__main__":
    main()
