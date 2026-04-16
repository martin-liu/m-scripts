#!/usr/bin/env python3
"""Canonical enrichment phase runner for LinkedIn sourcing.

Processes rows with next_action=enrich, extracts compact profile enrichment,
and updates workbook on success. Fails closed on structured browser/manual
failures with actionable guidance.

Usage:
    # Enrich all rows with next_action=enrich
    python3 run_enrich.py --project "{PROJECT_ID}"

    # Enrich specific rows
    python3 run_enrich.py --project "{PROJECT_ID}" --row-id 5,6,7

    # With custom CDP port
    python3 run_enrich.py --project "{PROJECT_ID}" --cdp-port 9231

    # Dry run (show what would be enriched)
    python3 run_enrich.py --project "{PROJECT_ID}" --dry-run

Exit codes:
    0 - All enrichments completed successfully
    1 - One or more enrichments failed (check output for details)
    2 - Browser/manual intervention required (structured action_required provided)
    3 - Configuration error
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


class EnrichError(Exception):
    """Raised when enrichment operation fails."""

    def __init__(self, message: str, exit_code: int = 1, row_id: int | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.row_id = row_id


class BrowserStateError(EnrichError):
    """Raised when browser state requires operator intervention."""

    def __init__(
        self,
        message: str,
        row_id: int | None = None,
        action_required: dict[str, Any] | None = None,
    ):
        super().__init__(message, exit_code=2, row_id=row_id)
        self.action_required = action_required


class ConfigError(EnrichError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=3)


def load_runtime_context() -> dict[str, Any]:
    """Load runtime context from runtime_manager."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from runtime_manager import RuntimeManager

        manager = RuntimeManager()
        ctx = manager.get_runtime_context()
        if ctx is None:
            ctx = manager.initialize()
        return ctx
    except Exception as e:
        raise ConfigError(f"Failed to load runtime context: {e}")
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def resolve_project_and_workbook(project_ref: str) -> tuple[Path, Path]:
    """Resolve project reference to config and workbook paths.

    Uses canonical project_ref_utils resolution.

    Args:
        project_ref: Project reference (ID, URL, or config path)

    Returns:
        Tuple of (config_path, workbook_path)

    Raises:
        ConfigError: If resolution fails
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_ref_utils import resolve_project_ref

        resolution = resolve_project_ref(project_ref)
        if not resolution["success"]:
            raise ConfigError(resolution.get("error", "Project resolution failed"))

        config_path = resolution.get("config_path")
        workbook_path = resolution.get("workbook_path")

        if not config_path or not workbook_path:
            raise ConfigError("Resolution returned incomplete paths")

        return Path(config_path), Path(workbook_path)
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def read_enrichable_rows(
    workbook_path: Path,
    row_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Read rows with next_action=enrich from workbook.

    Args:
        workbook_path: Path to workbook file
        row_ids: Optional list of specific row IDs to process

    Returns:
        List of row dicts with next_action=enrich

    Raises:
        EnrichError: If read fails
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from excel_utils import read

        rows = read(workbook_path, filters={"next_action": "enrich"})

        # Filter to specific row IDs if provided
        if row_ids:
            rows = [r for r in rows if r.get("row_id") in row_ids]

        return rows
    except Exception as e:
        raise EnrichError(f"Failed to read workbook: {e}")
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def update_row_after_enrichment(
    workbook_path: Path,
    row_id: int,
    enrichment_notes: str,
    today: str,
) -> None:
    """Update workbook row after successful enrichment.

    Args:
        workbook_path: Path to workbook
        row_id: Row ID to update
        enrichment_notes: Compact enrichment facts
        today: Today's date string

    Raises:
        EnrichError: If update fails
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from excel_utils import update

        updates = {
            "enrichment_notes": enrichment_notes,
            "enriched_at": today,
            "next_action": "draft",  # Route to draft phase
        }

        update(workbook_path, row_id, updates)
    except Exception as e:
        raise EnrichError(f"Failed to update row {row_id}: {e}", row_id=row_id)
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def enrich_single_row(
    row: dict[str, Any],
    cdp_port: str,
    dry_run: bool = False,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Enrich a single candidate row.

    Args:
        row: Row dict with candidate data
        cdp_port: Chrome DevTools Protocol port
        dry_run: If True, don't actually enrich

    Returns:
        Tuple of (success, enrichment_notes, action_required)
    """
    profile_url = row.get("profile_url", "")
    row_id = row.get("row_id")

    if not profile_url:
        # Data validation failure - NOT a browser/manual intervention issue
        # Return as normal row failure (will result in exit code 1, not 2)
        return (
            False,
            None,
            {
                "code": "missing_profile_url",
                "summary": f"Row {row_id} has no profile_url",
                "steps": ["Add profile_url to candidate row", "Retry enrichment"],
                "can_retry": False,  # Data issue, not transient browser issue
            },
        )

    if dry_run:
        return (
            True,
            f"[DRY RUN] Would enrich: {profile_url}",
            None,
        )

    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from profile_enricher import enrich_profile

        result = enrich_profile(profile_url, cdp_port=cdp_port)

        if result.success:
            return (True, result.enrichment_notes, None)
        else:
            return (
                False,
                result.partial_result,
                result.action_required,
            )
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def run_enrich_phase(
    project_ref: str,
    cdp_port: str | None = None,
    dry_run: bool = False,
    row_ids: list[int] | None = None,
) -> int:
    """Run the enrichment phase for workbook rows.

    Args:
        project_ref: Project reference (ID, URL, or config path)
        cdp_port: Optional CDP port (defaults to profile value or 9234)
        dry_run: If True, show what would be enriched without doing it
        row_ids: Optional list of specific row IDs to process

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        # Load runtime context
        ctx = load_runtime_context()

        # Get CDP port from context if not provided
        if cdp_port is None:
            cdp_port = ctx.get("profile", {}).get("CDP_PORT", "9234")

        # Resolve project and workbook
        config_path, workbook_path = resolve_project_and_workbook(project_ref)
        project_dir = config_path.parent

        print(f"Config: {config_path}")
        print(f"Workbook: {workbook_path}")
        print(f"CDP Port: {cdp_port}")
        print(f"Mode: {'dry-run' if dry_run else 'enrich'}")
        print()

        # Read enrichable rows
        rows = read_enrichable_rows(workbook_path, row_ids)

        if not rows:
            print("No enrichable rows found (next_action=enrich)")
            return 0

        print(f"Found {len(rows)} row(s) to enrich")
        print()

        # Process each row
        success_count = 0
        failed_rows: list[tuple[int, str]] = []
        browser_intervention_required: list[tuple[int, dict[str, Any]]] = []

        for i, row in enumerate(rows, 1):
            row_id = row.get("row_id")
            name = row.get("name", "Unknown")
            profile_url = row.get("profile_url", "")

            print(f"[{i}/{len(rows)}] Row {row_id}: {name}")
            print(f"  URL: {profile_url}")

            success, enrichment_notes, action_required = enrich_single_row(
                row, cdp_port, dry_run
            )

            if success:
                if not dry_run:
                    update_row_after_enrichment(
                        workbook_path, row_id, enrichment_notes or "", today
                    )
                print(f"  Result: ENRICHED")
                if enrichment_notes:
                    # Truncate long notes for display
                    display_notes = (
                        enrichment_notes[:100] + "..."
                        if len(enrichment_notes) > 100
                        else enrichment_notes
                    )
                    print(f"  Notes: {display_notes}")
                success_count += 1
            else:
                print(f"  Result: FAILED")
                if action_required:
                    print(f"  Issue: {action_required.get('summary', 'Unknown')}")
                    print(f"  Code: {action_required.get('code', 'unknown')}")

                    # Check if this is a browser/manual intervention case (exit 2)
                    # vs a data validation failure (exit 1)
                    failure_code = action_required.get("code", "unknown")

                    # Browser/manual intervention codes that warrant exit code 2
                    # NOTE: Exit code 2 is keyed off the failure code set itself,
                    # NOT retryability. Retryability only affects operator guidance.
                    browser_failure_codes = {
                        "auth_required",
                        "browser_exception",
                        "extraction_timeout",
                        "extraction_failed",
                        "navigation_timeout",
                        "navigation_failed",
                        "extraction_parse_error",
                        "agent_browser_not_found",
                    }

                    is_browser_failure = failure_code in browser_failure_codes

                    if is_browser_failure:
                        browser_intervention_required.append((row_id, action_required))

                    failed_rows.append(
                        (row_id, action_required.get("summary", "failed"))
                    )
                else:
                    failed_rows.append((row_id, "unknown failure"))

            print()

        # Summary
        print("=" * 50)
        print(f"Processed: {len(rows)} row(s)")
        print(f"Successful: {success_count}")
        print(f"Failed: {len(failed_rows)}")

        # Update project state based on results
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            from project_state import update_project_state

            if browser_intervention_required:
                update_project_state(
                    project_dir=project_dir,
                    current_phase="enrich",
                    status="action_required",
                    action_required={
                        "code": "browser_intervention",
                        "summary": f"Browser intervention required for {len(browser_intervention_required)} row(s)",
                        "steps": [
                            "Resolve browser issues",
                            f"Retry with: python3 run_enrich.py --project '{project_ref}' --row-id {','.join(str(r[0]) for r in browser_intervention_required)}",
                        ],
                        "can_retry": True,
                    },
                    last_result_summary=f"Enrichment: {success_count} succeeded, {len(failed_rows)} failed, {len(browser_intervention_required)} need intervention",
                )
            elif failed_rows:
                update_project_state(
                    project_dir=project_dir,
                    current_phase="enrich",
                    status="failed",
                    last_result_summary=f"Enrichment: {success_count} succeeded, {len(failed_rows)} failed",
                    last_error=f"Failed rows: {', '.join(str(r[0]) for r in failed_rows)}",
                )
            else:
                update_project_state(
                    project_dir=project_dir,
                    current_phase="enrich",
                    status="completed",
                    action_required=False,
                    last_result_summary=f"Enrichment complete: {success_count} row(s) enriched",
                    last_error=False,
                )
        finally:
            if str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))

        # If browser intervention required, surface structured guidance
        if browser_intervention_required:
            print()
            print("BROWSER/MANUAL INTERVENTION REQUIRED")
            print("-" * 50)
            for row_id, action in browser_intervention_required:
                print(f"\nRow {row_id}:")
                print(f"  Issue: {action.get('summary', 'Unknown')}")
                print(f"  Code: {action.get('code', 'unknown')}")
                print("  Steps to resolve:")
                for step in action.get("steps", []):
                    print(f"    - {step}")
                if action.get("context"):
                    print(f"  Context: {action['context']}")
            print()
            print("After resolving the issues, retry with:")
            print(
                f"  python3 run_enrich.py --project '{project_ref}' --row-id {','.join(str(r[0]) for r in browser_intervention_required)}"
            )
            return 2

        if failed_rows:
            print()
            print("Failed rows:")
            for row_id, reason in failed_rows:
                print(f"  Row {row_id}: {reason}")
            return 1

        return 0

    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 3
    except EnrichError as e:
        print(f"Enrichment error: {e}", file=sys.stderr)
        return e.exit_code
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich candidate profiles for workbook rows with next_action=enrich"
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project reference: local PROJECT_ID, Recruiter URL, or numeric ID",
    )
    parser.add_argument(
        "--cdp-port",
        help="Chrome DevTools Protocol port (default: from profile or 9234)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be enriched without doing it",
    )
    parser.add_argument(
        "--row-id",
        help="Specific row ID(s) to process (comma-separated for multiple)",
    )

    args = parser.parse_args()

    # Parse row IDs if provided
    row_ids: list[int] | None = None
    if args.row_id:
        try:
            row_ids = [int(x.strip()) for x in args.row_id.split(",")]
        except ValueError:
            print("Error: --row-id must be comma-separated integers", file=sys.stderr)
            return 3

    return run_enrich_phase(
        project_ref=args.project,
        cdp_port=args.cdp_port,
        dry_run=args.dry_run,
        row_ids=row_ids,
    )


if __name__ == "__main__":
    sys.exit(main())
