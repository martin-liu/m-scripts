#!/usr/bin/env python3
"""Generic one-phase runner for LinkedIn sourcing workflow (advanced/debug only).

This script is for debugging and advanced use only. For normal workflow,
use the loop command which handles phase sequencing automatically:
    python3 scripts/run_reachout_loop.py --project <PROJECT_ID>

Runs exactly one phase, not the whole workflow. Updates project state
before and after execution.

Phases:
    create_search  - Create LinkedIn Recruiter search
    confirm_search - Confirm search filters (human boundary, use --confirm-search to proceed)
    extract        - Extract candidates from Recruiter
    filter         - Filter candidates by title
    enrich         - Enrich candidate profiles
    draft          - Generate inmail drafts
    review         - Human review (marks state only)
    send           - Send inmails

Note: Bootstrap is a pre-loop entrypoint; use bootstrap_project.py directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from project_ref_utils import resolve_project_ref
from project_state import update_project_state, load_project_state
from phase_registry import (
    get_phase_metadata,
    is_valid_phase,
)
from status import get_status
from phase_retry import run_phase_with_retries


def run_filter_phase(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    local_project_id: str,
) -> dict[str, Any]:
    """Run the filter phase using run_filter module."""
    try:
        from run_filter import run_filter

        return run_filter(project_dir, config_path, workbook_path)
    except Exception as e:
        return {"success": False, "error": str(e), "kept": 0, "filtered": 0}


def run_review_phase(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    local_project_id: str,
) -> dict[str, Any]:
    """Run the review phase: auto-approve drafted rows for sending."""
    try:
        from reachout_automation import cmd_approve

        result = cmd_approve(str(workbook_path))
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e), "approved": 0}


def run_draft_phase(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    local_project_id: str,
) -> dict[str, Any]:
    """Run the draft phase using run_draft module."""
    try:
        from run_draft import run_draft

        return run_draft(project_dir, config_path, workbook_path)
    except Exception as e:
        return {"success": False, "error": str(e), "drafted": 0}


def _run_subprocess_with_json_output(
    cmd: list[str],
    timeout: int,
    success_code: int = 0,
    blocked_code: int | None = None,
    blocked_reason: str = "action_required",
) -> dict[str, Any]:
    """Run subprocess and parse JSON output.

    Args:
        cmd: Command to run
        timeout: Timeout in seconds
        success_code: Exit code indicating success
        blocked_code: Exit code indicating an action_required blocker
        blocked_reason: Reason string for blocked state

    Returns:
        Dict with success, parsed JSON, stdout, stderr, error fields
    """
    import subprocess
    import json

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = {}

        if result.returncode == success_code:
            return {
                "success": True,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "parsed": parsed,
                "error": None,
            }
        elif blocked_code is not None and result.returncode == blocked_code:
            return {
                "success": False,
                "blocked": True,
                "block_reason": blocked_reason,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "parsed": parsed,
                "action_required": parsed.get("action_required"),
                "error": parsed.get("message", "Action required before continuing"),
            }
        else:
            return {
                "success": False,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "parsed": parsed,
                "error": parsed.get("message", result.stderr or "Command failed"),
            }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Timeout after {timeout} seconds",
            "failure_code": "timeout",
            "can_retry": True,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_create_search_phase(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    local_project_id: str,
) -> dict[str, Any]:
    """Run create_search phase via subprocess to existing script.

    Preserves structured result including action_required and next_phase
    for proper loop handling.
    """
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_create_search.py"),
        "--project",
        local_project_id,
    ]

    result = _run_subprocess_with_json_output(
        cmd, timeout=300, success_code=0, blocked_code=2
    )

    # Add phase-specific fields
    if result["success"]:
        result["next_phase"] = result["parsed"].get("next_phase", "extract")
    elif result.get("blocked"):
        result["next_phase"] = result["parsed"].get("next_phase", "create_search")

    # Preserve timeout failure_code for retry handling
    if result.get("failure_code") == "timeout":
        result["can_retry"] = True

    return result


def run_extract_phase(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    local_project_id: str,
) -> dict[str, Any]:
    """Run extract phase via subprocess to existing script.

    Preserves structured failure fields (action_required, failure_code) from
    extraction results to ensure blockers are properly surfaced to the loop.
    """
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_extraction.py"),
        "--config",
        str(config_path),
    ]

    result = _run_subprocess_with_json_output(cmd, timeout=600)

    # Preserve structured failure fields for blocker handling
    parsed = result.get("parsed", {})
    if parsed.get("action_required"):
        result["action_required"] = parsed["action_required"]
    if parsed.get("failure_code"):
        result["failure_code"] = parsed["failure_code"]

    # Treat extraction with action_required as blocked
    if not result["success"] and result.get("action_required"):
        result["blocked"] = True
        result["block_reason"] = parsed.get("failure_code", "extraction_blocked")

    return result


def run_enrich_phase(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    local_project_id: str,
) -> dict[str, Any]:
    """Run enrich phase via subprocess to existing script.

    Exit code 2 indicates an action_required browser blocker.
    """
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_enrich.py"),
        "--project",
        local_project_id,
    ]

    result = _run_subprocess_with_json_output(
        cmd,
        timeout=600,
        success_code=0,
        blocked_code=2,
        blocked_reason="browser_blocked",
    )

    # Add enrich-specific error message for blocked state
    if result.get("blocked"):
        result["error"] = (
            "Browser action required before continuing (see output for steps)"
        )

    return result


def run_send_phase(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    local_project_id: str,
) -> dict[str, Any]:
    """Run send phase via subprocess to existing script.

    Exit code 2 indicates the send phase is blocked and needs follow-up.
    """
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_send.py"),
        "--project",
        local_project_id,
    ]

    result = _run_subprocess_with_json_output(
        cmd,
        timeout=600,
        success_code=0,
        blocked_code=2,
        blocked_reason="send_blocked",
    )

    # Add send-specific error message for blocked state
    if result.get("blocked"):
        result["error"] = "Send is blocked - operator intervention required"

    return result


# Phase runner registry
# Note: bootstrap is a pre-loop entrypoint, not a runnable loop phase
# Note: confirm_search is a human stop boundary handled inline in run_phase()
PHASE_RUNNERS: dict[str, callable] = {
    "create_search": run_create_search_phase,
    "extract": run_extract_phase,
    "filter": run_filter_phase,
    "enrich": run_enrich_phase,
    "draft": run_draft_phase,
    "review": run_review_phase,
    "send": run_send_phase,
}


def run_phase(
    project_ref: str,
    phase: str,
    dry_run: bool = False,
    reset_retry_count: bool = False,
) -> dict[str, Any]:
    """Run a single phase for a project.

    Args:
        project_ref: Project reference (ID, URL, or config path)
        phase: Phase name to run
        dry_run: If True, don't actually execute, just report what would happen
        reset_retry_count: If True, clear previous retry state before running

    Returns:
        Result dict with success status and details
    """
    result: dict[str, Any] = {
        "project_ref": project_ref,
        "phase": phase,
        "success": False,
        "dry_run": dry_run,
        "error": None,
        "state_before": None,
        "state_after": None,
        "phase_result": None,
    }

    # Resolve project reference
    resolution = resolve_project_ref(project_ref)
    if not resolution["success"]:
        result["error"] = resolution.get("error", "Failed to resolve project reference")
        return result

    config_path = resolution["config_path"]
    project_dir = config_path.parent
    workbook_path = resolution["workbook_path"]
    local_project_id = resolution.get("local_project_id") or project_dir.name

    # Reject bootstrap - it's a pre-loop entrypoint, not a runnable loop phase
    if phase == "bootstrap":
        result["error"] = (
            "Bootstrap phase is not runnable via run_phase; use bootstrap_project.py directly"
        )
        return result

    # Validate phase
    state = load_project_state(project_dir)
    workflow_mode = state.get("workflow_mode", "reachout") if state else "reachout"

    if not is_valid_phase(phase, workflow_mode):
        result["error"] = f"Invalid phase '{phase}' for workflow mode '{workflow_mode}'"
        return result

    # Get phase metadata
    meta = get_phase_metadata(phase)

    # Check if phase is automated
    if not meta.get("is_automated", True):
        result["success"] = True
        result["phase_result"] = {
            "message": f"Phase '{phase}' requires human action",
            "workbook_path": str(workbook_path),
        }
        # confirm_search is a non-sticky human stop boundary -
        # don't set action_required to avoid creating a stale blocker.
        # The workbook's next_action rows are the source of truth for state.
        if phase == "confirm_search":
            result["state_after"] = update_project_state(
                project_dir,
                current_phase=phase,
                status="completed",  # Mark as completed, not blocked
                action_required=False,  # Explicitly clear any stale action_required
                last_error=False,
            )
            result["phase_result"]["next_phase"] = "extract"
        else:
            result["state_after"] = update_project_state(
                project_dir,
                current_phase=phase,
                status="action_required",
                action_required={
                    "code": "human_review",
                    "summary": f"Human action required for {phase} phase",
                    "steps": [f"Open workbook: {workbook_path}"],
                    "actor": "agent",
                },
            )
        return result

    # Update state to running
    if not dry_run:
        result["state_before"] = update_project_state(
            project_dir,
            current_phase=phase,
            status="running",
            last_error=False,  # Clear previous error
            action_required=False,  # Clear stale action_required when retrying
        )

    # Get the runner
    runner = PHASE_RUNNERS.get(phase)
    if not runner:
        result["error"] = f"No runner available for phase '{phase}'"
        if not dry_run:
            update_project_state(
                project_dir,
                status="failed",
                last_error=result["error"],
            )
        return result

    # Run the phase
    if dry_run:
        result["success"] = True
        result["phase_result"] = {"message": f"Would run {phase} phase (dry-run)"}
    else:
        try:
            phase_result = run_phase_with_retries(
                phase=phase,
                project_ref=project_ref,
                project_dir=project_dir,
                reset_retry_count=reset_retry_count,
                runner=lambda: runner(
                    project_dir, config_path, workbook_path, local_project_id
                ),
            )
            result["phase_result"] = phase_result

            if phase_result.get("success", False):
                result["success"] = True
                state_update_kwargs = {
                    "current_phase": phase,
                    "status": "completed",
                    "action_required": False,  # Clear action_required on success
                    "last_error": False,  # Clear any previous error
                }

                # Preserve create_search's richer summary written by the subprocess.
                # For other phases, keep the existing compact fallback summary.
                if phase != "create_search":
                    state_update_kwargs["last_result_summary"] = str(phase_result)[:200]

                # Update state to completed - clear any stale action_required
                result["state_after"] = update_project_state(
                    project_dir,
                    **state_update_kwargs,
                )
            elif phase_result.get("blocked"):
                # action_required blocker - preserve action_required if present
                result["error"] = phase_result.get("error", "Phase blocked")
                action_required = phase_result.get("action_required")
                if action_required:
                    result["state_after"] = update_project_state(
                        project_dir,
                        current_phase=phase,
                        status="action_required",
                        action_required=action_required,
                        last_error=result["error"],
                    )
                else:
                    result["state_after"] = update_project_state(
                        project_dir,
                        current_phase=phase,
                        status="action_required",
                        action_required={
                            "code": phase_result.get("block_reason", "action_required"),
                            "summary": result["error"],
                            "steps": ["Check the output above for resolution steps"],
                            "actor": "agent",
                        },
                        last_error=result["error"],
                    )
            else:
                result["error"] = phase_result.get("error", "Phase failed")
                # Preserve timeout failure_code for loop retry handling
                if phase_result.get("failure_code"):
                    result["failure_code"] = phase_result["failure_code"]
                if phase_result.get("can_retry"):
                    result["can_retry"] = phase_result["can_retry"]
                result["state_after"] = update_project_state(
                    project_dir,
                    status="failed",
                    last_error=result["error"],
                )
        except Exception as e:
            result["error"] = str(e)
            result["state_after"] = update_project_state(
                project_dir,
                status="failed",
                last_error=result["error"],
            )

    return result


def main():
    """CLI entry point."""
    if len(sys.argv) < 3:
        print(
            f"Advanced/debug only. Normal workflow: python3 {SCRIPT_DIR / 'run_reachout_loop.py'} --project <project_ref>",
            file=sys.stderr,
        )
        print(
            "Usage: python3 run_phase.py <project_ref> <phase> [--dry-run]",
            file=sys.stderr,
        )
        print(
            "  project_ref: PROJECT_ID, Recruiter URL, or config.sh path",
            file=sys.stderr,
        )
        print(
            "  phase: create_search|confirm_search|extract|filter|enrich|draft|review|send",
            file=sys.stderr,
        )
        sys.exit(1)

    project_ref = sys.argv[1]
    phase = sys.argv[2]
    dry_run = "--dry-run" in sys.argv

    result = run_phase(project_ref, phase, dry_run)

    print(json.dumps(result, indent=2, default=str))

    if not result.get("success", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
