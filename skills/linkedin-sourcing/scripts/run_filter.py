#!/usr/bin/env python3
"""Filter phase runner for LinkedIn sourcing (internal/advanced use only).

This script is used internally by the reachout loop. For normal workflow,
use the loop command which handles phase sequencing automatically:
    python3 scripts/run_reachout_loop.py --project <PROJECT_ID>

Wraps reachout_automation.py filter functionality with a clean interface.

Returns:
    JSON result with counts and status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from project_ref_utils import resolve_project_ref
from project_state import update_project_state


def run_filter(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    use_enrichment: bool = True,
) -> dict[str, Any]:
    """Run the filter phase for a project.

    Filters candidates by title exclusion rules from config.
    Kept rows are routed to enrich (or draft if use_enrichment=False).
    Filtered rows are marked as done.

    Args:
        project_dir: Path to project directory
        config_path: Path to config.sh
        workbook_path: Path to workbook.xlsx
        use_enrichment: If True, route to enrich; else route to draft

    Returns:
        Result dict with success status and counts
    """
    result: dict[str, Any] = {
        "success": False,
        "phase": "filter",
        "project_dir": str(project_dir),
        "workbook_path": str(workbook_path),
        "kept": 0,
        "filtered": 0,
        "skipped": 0,
        "target_phase": "enrich" if use_enrichment else "draft",
        "error": None,
    }

    # Validate paths
    if not config_path.exists():
        result["error"] = f"Config file not found: {config_path}"
        update_project_state(
            project_dir,
            current_phase="filter",
            status="failed",
            last_error=result["error"],
        )
        return result

    if not workbook_path.exists():
        result["error"] = f"Workbook not found: {workbook_path}"
        update_project_state(
            project_dir,
            current_phase="filter",
            status="failed",
            last_error=result["error"],
        )
        return result

    # Import and run filter from reachout_automation
    try:
        from reachout_automation import cmd_filter

        filter_result = cmd_filter(
            str(workbook_path),
            str(config_path),
            use_enrichment=use_enrichment,
        )

        # cmd_filter returns a dict with kept, filtered, skipped, target_phase
        result["kept"] = filter_result.get("kept", 0)
        result["filtered"] = filter_result.get("filtered", 0)
        result["skipped"] = filter_result.get("skipped", 0)
        result["target_phase"] = filter_result.get("target_phase", "enrich")
        result["success"] = True

        # Update project state
        update_project_state(
            project_dir,
            current_phase="filter",
            status="completed",
            last_result_summary=f"Kept: {result['kept']}, Filtered: {result['filtered']}",
        )

    except Exception as e:
        result["error"] = str(e)
        update_project_state(
            project_dir,
            current_phase="filter",
            status="failed",
            last_error=result["error"],
        )

    return result


def main():
    """CLI entry point."""
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]) or len(sys.argv) < 2:
        print(
            f"Advanced/debug only. Normal workflow: python3 {SCRIPT_DIR / 'run_reachout_loop.py'} --project <project_ref>",
            file=sys.stderr,
        )
        print(
            "Usage: python3 run_filter.py <project_ref> [--no-enrichment]",
            file=sys.stderr,
        )
        print(
            "  project_ref: PROJECT_ID, Recruiter URL, or config.sh path",
            file=sys.stderr,
        )
        sys.exit(0 if any(arg in ("-h", "--help") for arg in sys.argv[1:]) else 1)

    project_ref = sys.argv[1]
    use_enrichment = "--no-enrichment" not in sys.argv

    # Resolve project reference
    resolution = resolve_project_ref(project_ref)
    if not resolution["success"]:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": resolution.get(
                        "error", "Failed to resolve project reference"
                    ),
                },
                indent=2,
            )
        )
        sys.exit(1)

    config_path = resolution["config_path"]
    project_dir = config_path.parent
    workbook_path = resolution["workbook_path"]

    result = run_filter(project_dir, config_path, workbook_path, use_enrichment)

    print(json.dumps(result, indent=2, default=str))

    if not result.get("success", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
