#!/usr/bin/env python3
"""Draft phase runner for LinkedIn sourcing (internal/advanced use only).

This script is used internally by the reachout loop. For normal workflow,
use the loop command which handles phase sequencing automatically:
    python3 scripts/run_reachout_loop.py --project <PROJECT_ID>

Wraps reachout_automation.py draft functionality with a clean interface.

Returns:
    JSON result with counts and status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from project_ref_utils import resolve_project_ref
from project_state import update_project_state


def find_template(project_dir: Path, config: dict[str, str]) -> Path | None:
    """Find the inmail template for a project.

    Looks for template in this order:
    1. Template path from config (TEMPLATE_PATH)
    2. Project directory: inmail_template.txt
    3. Skill templates directory

    Args:
        project_dir: Path to project directory
        config: Project configuration dict

    Returns:
        Path to template file if found, None otherwise
    """
    # Check config for explicit template path
    if "TEMPLATE_PATH" in config:
        template_path = Path(config["TEMPLATE_PATH"]).expanduser()
        if template_path.exists():
            return template_path

    # Check project directory
    project_template = project_dir / "inmail_template.txt"
    if project_template.exists():
        return project_template

    # Check skill templates directory
    skill_dir = SCRIPT_DIR.parent
    skill_template = skill_dir / "templates" / "inmail_template.txt"
    if skill_template.exists():
        return skill_template

    return None


def run_draft(
    project_dir: Path,
    config_path: Path,
    workbook_path: Path,
    template_path: Path | None = None,
    row_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Run the draft phase for a project.

    Generates personalized inmail drafts for candidates ready for drafting.
    Processes rows where next_action=draft or (next_action=enrich with enrichment_notes).

    Args:
        project_dir: Path to project directory
        config_path: Path to config.sh
        workbook_path: Path to workbook.xlsx
        template_path: Optional explicit template path
        row_ids: Optional row IDs to draft

    Returns:
        Result dict with success status and counts
    """
    result: dict[str, Any] = {
        "success": False,
        "phase": "draft",
        "project_dir": str(project_dir),
        "workbook_path": str(workbook_path),
        "template_path": None,
        "drafted": 0,
        "skipped": 0,
        "error": None,
    }

    # Validate paths
    if not config_path.exists():
        result["error"] = f"Config file not found: {config_path}"
        update_project_state(
            project_dir,
            current_phase="draft",
            status="failed",
            last_error=result["error"],
        )
        return result

    if not workbook_path.exists():
        result["error"] = f"Workbook not found: {workbook_path}"
        update_project_state(
            project_dir,
            current_phase="draft",
            status="failed",
            last_error=result["error"],
        )
        return result

    # Load config to find template if not provided
    if template_path is None:
        try:
            from config_utils import parse_config_file

            config = parse_config_file(config_path)
            template_path = find_template(project_dir, config)
        except Exception as e:
            result["error"] = f"Failed to load config: {e}"
            update_project_state(
                project_dir,
                current_phase="draft",
                status="failed",
                last_error=result["error"],
            )
            return result

    if template_path is None or not template_path.exists():
        result["error"] = (
            "Template file not found. Expected inmail_template.txt in project directory or templates/"
        )
        update_project_state(
            project_dir,
            current_phase="draft",
            status="failed",
            last_error=result["error"],
        )
        return result

    result["template_path"] = str(template_path)

    # Import and run draft from reachout_automation
    try:
        from reachout_automation import cmd_draft

        draft_result = cmd_draft(
            str(workbook_path),
            str(config_path),
            str(template_path),
            row_ids=row_ids,
        )

        if draft_result.get("error"):
            result["error"] = str(draft_result["error"])
            update_project_state(
                project_dir,
                current_phase="draft",
                status="failed",
                last_error=result["error"],
            )
            return result

        # cmd_draft returns a dict with drafted, skipped
        result["drafted"] = draft_result.get("drafted", 0)
        result["skipped"] = draft_result.get("skipped", 0)
        result["success"] = True

        # Update project state
        update_project_state(
            project_dir,
            current_phase="draft",
            status="completed",
            last_result_summary=f"Drafted: {result['drafted']}, Skipped: {result['skipped']}",
            last_error=False,
        )

    except Exception as e:
        result["error"] = str(e)
        update_project_state(
            project_dir,
            current_phase="draft",
            status="failed",
            last_error=result["error"],
        )

    return result


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Draft InMails (internal/advanced use only)"
    )
    parser.add_argument(
        "project_ref",
        help="Project reference: local PROJECT_ID, Recruiter URL, or config.sh path",
    )
    parser.add_argument(
        "template_path",
        nargs="?",
        help="Optional explicit template file path",
    )
    parser.add_argument(
        "--row-id",
        help="Specific row ID(s) to draft (comma-separated for multiple)",
    )

    if len(sys.argv) < 2:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    project_ref = args.project_ref
    template_path = Path(args.template_path) if args.template_path else None
    row_ids = None
    if args.row_id:
        row_ids = [int(item.strip()) for item in args.row_id.split(",") if item.strip()]

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

    result = run_draft(
        project_dir,
        config_path,
        workbook_path,
        template_path,
        row_ids=row_ids,
    )

    print(json.dumps(result, indent=2, default=str))

    if not result.get("success", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
