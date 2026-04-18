#!/usr/bin/env python3
"""Reconcile workflow checkpoint state from workbook truth.

This is a recovery command for cases where project_state.json or extraction
resume state are stale, missing, or inconsistent with workbook progress.

Normal workflow still uses the loop:
    python3 run_reachout_loop.py --project <PROJECT_ID>

Use this command only when workflow state looks wrong.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from phase_registry import get_phase_order
from project_ref_utils import resolve_project_ref
from project_state import create_initial_state, load_project_state, save_project_state
from run_extraction import get_extraction_state_path, load_extraction_state
from runtime_manager import RuntimeManager
from status import determine_next_phase, get_loop_command, get_workbook_summary


VALID_PHASES = {"bootstrap"}
VALID_PHASES.update(get_phase_order("reachout"))
VALID_PHASES.update(get_phase_order("review"))


def normalize_phase(phase: str | None) -> str:
    """Normalize unknown phases to a safe bootstrap fallback."""
    if phase in VALID_PHASES:
        return str(phase)
    return "bootstrap"


def infer_reconciled_state(
    project_id: str,
    existing_state: dict[str, Any] | None,
    workbook_summary: dict[str, Any],
) -> dict[str, Any]:
    """Infer a safe checkpoint state from workbook truth."""
    workflow_mode = (existing_state or {}).get("workflow_mode", "reachout")
    current_phase = normalize_phase((existing_state or {}).get("current_phase"))
    total_rows = workbook_summary.get("total_rows", 0)
    by_action = workbook_summary.get("by_next_action", {})
    done_count = by_action.get("done", 0)

    if total_rows == 0 and not by_action:
        if (
            current_phase == "extract"
            and (existing_state or {}).get("status") == "completed"
        ):
            reconciled_phase = "extract"
            summary = "State reconciled: extraction completed with no candidates"
        else:
            reconciled_phase = "bootstrap"
            summary = "State reconciled: no workbook progress found; loop will resume at create_search"
    else:
        next_phase, message, _ready = determine_next_phase(
            current_phase=current_phase,
            phase_status="completed",
            workbook_summary=workbook_summary,
            workflow_mode=workflow_mode,
            action_required=None,
        )
        if next_phase is not None:
            reconciled_phase = next_phase
        elif total_rows > 0 and done_count == total_rows:
            reconciled_phase = "send"
        else:
            reconciled_phase = current_phase
        summary = f"State reconciled from workbook truth: {message}"

    reconciled_state = create_initial_state(
        project_id=project_id,
        workflow_mode=workflow_mode,
        current_phase=reconciled_phase,
        status="completed",
    )
    reconciled_state["action_required"] = None
    reconciled_state["last_error"] = None
    reconciled_state["last_result_summary"] = summary
    return reconciled_state


def should_clear_extraction_state(
    extraction_state_path: Path,
    extraction_state: dict[str, Any] | None,
    workbook_summary: dict[str, Any],
    reconciled_state: dict[str, Any],
) -> bool:
    """Return whether extraction resume state should be cleared."""
    if not extraction_state_path.exists():
        return False

    total_rows = workbook_summary.get("total_rows", 0)
    if extraction_state is None:
        return True

    if extraction_state.get("status") != "completed":
        return False

    if total_rows > 0:
        return True

    return reconciled_state.get("current_phase") != "extract"


def states_match(
    existing_state: dict[str, Any] | None,
    reconciled_state: dict[str, Any],
) -> bool:
    """Compare persisted state fields relevant to reconciliation."""
    if existing_state is None:
        return False

    keys = {
        "version",
        "project_id",
        "workflow_mode",
        "current_phase",
        "status",
        "action_required",
        "last_result_summary",
        "last_error",
    }
    return {key: existing_state.get(key) for key in keys} == {
        key: reconciled_state.get(key) for key in keys
    }


def reconcile_project(
    project_ref: str,
    apply: bool = False,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Reconcile project checkpoint state from workbook truth."""
    if work_dir is None:
        manager = RuntimeManager()
        work_dir = manager.work_dir

    resolution = resolve_project_ref(project_ref, work_dir=work_dir)
    if not resolution.get("success"):
        return {
            "success": False,
            "error": resolution.get("error", "Failed to resolve project"),
        }

    project_id = resolution["local_project_id"]
    project_dir = resolution["config_path"].parent
    workbook_path = Path(resolution["workbook_path"])
    state_path = project_dir / "project_state.json"

    workbook_summary = get_workbook_summary(workbook_path)
    if workbook_summary.get("error"):
        return {
            "success": False,
            "project_id": project_id,
            "project_dir": str(project_dir),
            "state_path": str(state_path),
            "workbook_path": str(workbook_path),
            "error": workbook_summary["error"],
        }

    existing_state = load_project_state(project_dir)
    reconciled_state = infer_reconciled_state(
        project_id, existing_state, workbook_summary
    )

    extraction_state_result = get_extraction_state_path(
        work_dir, project_id, workbook_path
    )
    if not extraction_state_result.get("success"):
        return {
            "success": False,
            "project_id": project_id,
            "project_dir": str(project_dir),
            "state_path": str(state_path),
            "workbook_path": str(workbook_path),
            "error": extraction_state_result.get(
                "error", "Failed to resolve extraction resume state"
            ),
            "loop_command": get_loop_command(project_id),
        }

    extraction_state_path = extraction_state_result.get("path")
    extraction_state = None
    clear_extraction_state = False
    if extraction_state_path is not None:
        extraction_state = load_extraction_state(extraction_state_path)
        if extraction_state_path.exists() and extraction_state is None:
            return {
                "success": False,
                "project_id": project_id,
                "project_dir": str(project_dir),
                "state_path": str(state_path),
                "workbook_path": str(workbook_path),
                "error": (
                    "Extraction resume state is unreadable. Inspect it before "
                    "running reconcile."
                ),
                "loop_command": get_loop_command(project_id),
            }
        if extraction_state and extraction_state.get("status") in {"running", "failed"}:
            return {
                "success": False,
                "project_id": project_id,
                "project_dir": str(project_dir),
                "state_path": str(state_path),
                "workbook_path": str(workbook_path),
                "error": (
                    "Extraction resume state is still active. Do not reconcile yet. "
                    "Finish or inspect extraction recovery first."
                ),
                "loop_command": get_loop_command(project_id),
            }
        clear_extraction_state = should_clear_extraction_state(
            extraction_state_path,
            extraction_state,
            workbook_summary,
            reconciled_state,
        )

    state_changed = not states_match(existing_state, reconciled_state)
    changed = state_changed or clear_extraction_state

    if apply and state_changed:
        if not save_project_state(project_dir, reconciled_state):
            return {
                "success": False,
                "project_id": project_id,
                "project_dir": str(project_dir),
                "state_path": str(state_path),
                "error": f"Failed to save state to {state_path}",
            }

    if apply and clear_extraction_state and extraction_state_path is not None:
        extraction_state_path.unlink(missing_ok=True)

    return {
        "success": True,
        "applied": apply,
        "changed": changed,
        "project_id": project_id,
        "project_dir": str(project_dir),
        "state_path": str(state_path),
        "workbook_path": str(workbook_path),
        "workbook_summary": workbook_summary,
        "existing_state": existing_state,
        "reconciled_state": reconciled_state,
        "cleared_extraction_state": clear_extraction_state and apply,
        "would_clear_extraction_state": clear_extraction_state and not apply,
        "loop_command": get_loop_command(project_id),
        "message": (
            "State reconciled"
            if apply and changed
            else "State already consistent"
            if apply
            else "Reconciliation preview ready"
        ),
    }


def format_pretty(result: dict[str, Any]) -> str:
    """Format a human-readable reconciliation summary."""
    if not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"

    lines = []
    if result.get("applied"):
        lines.append("Reconcile applied")
    else:
        lines.append("Reconcile preview")
    lines.append(f"Project: {result['project_id']}")
    lines.append(f"State file: {result['state_path']}")
    lines.append(f"Workbook: {result['workbook_path']}")
    lines.append(f"Changed: {'yes' if result.get('changed') else 'no'}")
    if result.get("would_clear_extraction_state"):
        lines.append("Extraction resume state: would clear")
    if result.get("cleared_extraction_state"):
        lines.append("Extraction resume state: cleared")
    state = result["reconciled_state"]
    lines.append(
        f"Reconciled checkpoint: phase={state['current_phase']} status={state['status']}"
    )
    lines.append(f"Summary: {state.get('last_result_summary', '')}")
    if not result.get("applied") and result.get("changed"):
        lines.append("Apply: rerun with --apply")
    lines.append(f"Next loop command: {result['loop_command']}")
    return "\n".join(lines)


def main() -> int:
    """CLI entry point."""
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]) or len(sys.argv) < 2:
        print("Usage: python3 reconcile_state.py <project_ref> [--apply] [--pretty]")
        print("  project_ref: PROJECT_ID, Recruiter URL, or config.sh path")
        print("  --apply: write the reconciled checkpoint state")
        print("  --pretty: human-readable output")
        return 0 if len(sys.argv) >= 2 else 1

    project_ref = sys.argv[1]
    apply = "--apply" in sys.argv
    pretty = "--pretty" in sys.argv

    result = reconcile_project(project_ref, apply=apply)
    if pretty:
        print(format_pretty(result))
    else:
        print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
