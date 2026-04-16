#!/usr/bin/env python3
"""Canonical send macro for LinkedIn InMail workbook rows.

Resolves scripts from canonical skill paths with optional WORK_DIR overrides.
Handles send outcomes and updates workbook with proper reconciliation.

Usage:
    # Send all rows with next_action=send
    python3 run_send.py --project <PROJECT_ID>

    # Verify-only mode for one or more rows
    python3 run_send.py --project <PROJECT_ID> --verify-only --row-id 5
    python3 run_send.py --project <PROJECT_ID> --verify-only --row-id 5,6,7

    # With custom CDP port
    python3 run_send.py --project <PROJECT_ID> --cdp-port 9231

Exit codes:
    0 - All sends completed successfully (or verify-only passed)
    1 - One or more sends failed (check output for details)
    2 - Browser state not clean (fatal - operator intervention required)
    3 - Configuration or setup error
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


class SendError(Exception):
    """Raised when a send operation fails."""

    def __init__(self, message: str, exit_code: int = 1, row_id: int | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.row_id = row_id


class BrowserStateError(SendError):
    """Raised when browser state is not clean - requires operator intervention."""

    def __init__(
        self,
        message: str,
        row_id: int | None = None,
        action_required: dict[str, Any] | None = None,
    ):
        super().__init__(message, exit_code=2, row_id=row_id)
        self.action_required = action_required


class ConfigError(SendError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=3)


def load_runtime_context() -> dict[str, Any]:
    """Load runtime context from runtime_manager.

    Returns:
        Runtime context dict with paths and configuration.

    Raises:
        ConfigError: If runtime is not initialized.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from runtime_manager import RuntimeManager

        manager = RuntimeManager()
        ctx = manager.get_runtime_context()
        if ctx is None:
            # Try to initialize
            ctx = manager.initialize()
        return ctx
    except Exception as e:
        raise ConfigError(f"Failed to load runtime context: {e}")
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def resolve_send_script(ctx: dict[str, Any]) -> Path:
    """Resolve the send_inmail.sh script path using canonical resolution.

    Uses RuntimeManager.resolve_script for consistent resolution:
    1. WORK_DIR/scripts/send_inmail.sh (user override)
    2. SKILL_DIR/scripts/send_inmail.sh (canonical)

    Args:
        ctx: Runtime context dict.

    Returns:
        Path to send_inmail.sh.

    Raises:
        ConfigError: If script cannot be found.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from runtime_manager import RuntimeManager

        manager = RuntimeManager()
        # Use work_dir from context if available
        if ctx.get("work_dir"):
            manager._work_dir = Path(ctx["work_dir"])

        script_path = manager.resolve_script("send_inmail.sh")
        if script_path is None:
            raise ConfigError(
                "send_inmail.sh not found in WORK_DIR/scripts or SKILL_DIR/scripts"
            )
        return script_path
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def resolve_excel_utils(ctx: dict[str, Any]) -> Path:
    """Resolve the excel_utils.py script path using canonical resolution.

    Uses RuntimeManager.resolve_script for consistent resolution:
    1. WORK_DIR/scripts/excel_utils.py (user override)
    2. SKILL_DIR/scripts/excel_utils.py (canonical)

    Args:
        ctx: Runtime context dict.

    Returns:
        Path to excel_utils.py.

    Raises:
        ConfigError: If script cannot be found.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from runtime_manager import RuntimeManager

        manager = RuntimeManager()
        # Use work_dir from context if available
        if ctx.get("work_dir"):
            manager._work_dir = Path(ctx["work_dir"])

        script_path = manager.resolve_script("excel_utils.py")
        if script_path is None:
            raise ConfigError(
                "excel_utils.py not found in WORK_DIR/scripts or SKILL_DIR/scripts"
            )
        return script_path
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def get_workbook_path(ctx: dict[str, Any], project_ref: str) -> Path:
    """Get the workbook path for a project using canonical resolution.

    Uses project_ref_utils.resolve_project_ref for consistent resolution
    of project references (local ID, Recruiter URL, or numeric ID).

    Args:
        ctx: Runtime context dict.
        project_ref: Project reference (ID, URL, or config path).

    Returns:
        Path to the workbook file.

    Raises:
        ConfigError: If workbook cannot be resolved.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_ref_utils import resolve_project_ref

        resolution = resolve_project_ref(
            project_ref,
            work_dir=Path(ctx["work_dir"]) if ctx.get("work_dir") else None,
        )

        if not resolution["success"]:
            raise ConfigError(
                f"Failed to resolve project '{project_ref}': {resolution.get('error', 'Unknown error')}"
            )

        workbook_path = resolution.get("workbook_path")
        if not workbook_path:
            raise ConfigError(
                f"Resolution succeeded but no workbook path returned for '{project_ref}'"
            )

        return Path(workbook_path)
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def read_sendable_rows(
    excel_utils: Path, workbook_path: Path, row_ids: list[int] | None = None
) -> list[dict[str, Any]]:
    """Read rows with next_action=send from workbook.

    Args:
        excel_utils: Path to excel_utils.py.
        workbook_path: Path to workbook file.
        row_ids: Optional list of specific row IDs to send.

    Returns:
        List of row dicts with next_action=send.

    Raises:
        SendError: If read fails.
    """
    cmd = [
        sys.executable,
        str(excel_utils),
        "read",
        str(workbook_path),
        "--filter",
        "next_action=send",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=30
        )
        rows = json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        raise SendError(f"Failed to read workbook: {e.stderr}")
    except json.JSONDecodeError as e:
        raise SendError(f"Invalid JSON from excel_utils: {e}")
    except subprocess.TimeoutExpired:
        raise SendError("Timeout reading workbook")

    # Filter to specific row IDs if provided
    if row_ids:
        rows = [r for r in rows if r.get("row_id") in row_ids]

    return rows


def send_inmail(
    send_script: Path,
    cdp_port: str,
    work_dir: str | None,
    profile_url: str,
    subject: str,
    body: str,
    verify_only: bool = False,
) -> dict[str, Any]:
    """Execute send_inmail.sh and return structured result.

    Args:
        send_script: Path to send_inmail.sh.
        cdp_port: Chrome DevTools Protocol port.
        work_dir: Runtime work directory for browser mode resolution.
        profile_url: LinkedIn profile URL.
        subject: Message subject.
        body: Message body.
        verify_only: If True, only verify without sending.

    Returns:
        Dict with status, reason, clean_state, etc.

    Raises:
        SendError: If send fails unexpectedly.
    """
    cmd = [
        "bash",
        str(send_script),
        "--json",
    ]
    if verify_only:
        cmd.append("--verify-only")
    cmd.extend([profile_url, subject, body])

    # Set CDP_PORT environment variable while preserving parent environment
    env = {**os.environ, "CDP_PORT": cdp_port}
    if work_dir:
        env["WORK_DIR"] = work_dir

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, env=env
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "FAILED",
            "reason": "send_timeout",
            "clean_state": False,
            "verify_only": verify_only,
        }
    except Exception as e:
        return {
            "status": "FAILED",
            "reason": f"send_exception: {e}",
            "clean_state": False,
            "verify_only": verify_only,
        }

    # Parse JSON output - strict JSON-only, no mixed stdout tolerated
    try:
        output = result.stdout.strip()
        send_result = json.loads(output)
    except json.JSONDecodeError:
        # Non-JSON output is a failure - require explicit clean_state in JSON
        return {
            "status": "FAILED",
            "reason": "invalid_json_output",
            "clean_state": False,
            "verify_only": verify_only,
        }

    send_result["verify_only"] = verify_only
    return send_result


def update_row_after_send(
    excel_utils: Path,
    workbook_path: Path,
    row: dict[str, Any],
    send_result: dict[str, Any],
    today: str,
) -> None:
    """Update workbook row based on send outcome.

    Handles reconciliation per acceptance criteria:
    - SENT -> status=Sent, next_action=done, date_sent=today, last_contact=today, attempts=max(1, attempts+1)
    - ALREADY_CONTACTED -> status=AlreadyContacted, next_action=done, last_contact=today, append note
    - VERIFIED -> keep row sendable, append note like "verify-only passed YYYY-MM-DD"
    - FAILED or clean_state=false -> raise SendError

    Args:
        excel_utils: Path to excel_utils.py.
        workbook_path: Path to workbook file.
        row: Row dict with current values.
        send_result: Result dict from send_inmail.
        today: Today's date string (YYYY-MM-DD).

    Raises:
        SendError: If update fails or result requires failure.
        BrowserStateError: If browser state is not clean or manual intervention required.
    """
    row_id = row.get("row_id")
    status = send_result.get("status", "FAILED")
    clean_state = send_result.get("clean_state", False)
    reason = send_result.get("reason", "")
    verify_only = send_result.get("verify_only", False)
    action_required = send_result.get("action_required")
    failure_code = send_result.get("failure_code")

    # Check for unclean browser state - this is fatal
    if not clean_state:
        raise BrowserStateError(
            f"Browser state not clean after send: {reason}",
            row_id=row_id,
            action_required=action_required,
        )

    # Check for structured action_required in FAILED status - raise BrowserStateError
    # for browser/manual-intervention lane failures
    if status == "FAILED" and action_required:
        # Browser/manual intervention required - exit code 2
        error_msg = f"Send failed for row {row_id}: {reason}"
        if failure_code:
            error_msg += f" (code: {failure_code})"
        raise BrowserStateError(
            error_msg,
            row_id=row_id,
            action_required=action_required,
        )

    # Fail-closed: verify-only mode must not accept real-send statuses
    if verify_only and status == "SENT":
        raise SendError(
            f"Verify-only mode returned SENT for row {row_id}: possible script error",
            exit_code=1,
            row_id=row_id,
        )

    # Get current attempts
    current_attempts = row.get("attempts") or 0
    try:
        current_attempts = int(current_attempts) if current_attempts else 0
    except (ValueError, TypeError):
        current_attempts = 0

    # Build updates based on outcome
    updates: dict[str, Any] = {}
    note_addition = ""

    if status == "SENT":
        updates = {
            "status": "Sent",
            "next_action": "done",
            "date_sent": today,
            "last_contact": today,
            "attempts": max(1, current_attempts + 1),
        }
    elif status == "ALREADY_CONTACTED":
        # Append note with reason
        existing_notes = row.get("notes") or ""
        note_addition = f"[Already contacted: {reason}]"
        new_notes = (
            f"{existing_notes} {note_addition}".strip()
            if existing_notes
            else note_addition
        )
        updates = {
            "status": "AlreadyContacted",
            "next_action": "done",
            "last_contact": today,
            "notes": new_notes,
        }
    elif status == "VERIFIED":
        # Keep row sendable, append verification note
        existing_notes = row.get("notes") or ""
        note_addition = f"[verify-only passed {today}]"
        new_notes = (
            f"{existing_notes} {note_addition}".strip()
            if existing_notes
            else note_addition
        )
        updates = {
            "notes": new_notes,
            # Keep next_action=send so row remains sendable
        }
    elif status == "FAILED":
        raise SendError(
            f"Send failed for row {row_id}: {reason}",
            exit_code=1,
            row_id=row_id,
        )
    else:
        raise SendError(
            f"Unknown send status '{status}' for row {row_id}",
            exit_code=1,
            row_id=row_id,
        )

    # Execute update
    cmd = [
        sys.executable,
        str(excel_utils),
        "update",
        str(workbook_path),
        str(row_id),
        json.dumps(updates),
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
    except subprocess.CalledProcessError as e:
        raise SendError(f"Failed to update row {row_id}: {e.stderr}", row_id=row_id)
    except subprocess.TimeoutExpired:
        raise SendError(f"Timeout updating row {row_id}", row_id=row_id)


def run_send_macro(
    project_ref: str,
    cdp_port: str | None = None,
    verify_only: bool = False,
    row_ids: list[int] | None = None,
) -> int:
    """Run the send macro for workbook rows.

    Args:
        project_ref: Project reference (local ID, Recruiter URL, or numeric ID).
        cdp_port: Optional CDP port (defaults to profile value or 9234).
        verify_only: If True, only verify without sending.
        row_ids: Optional list of specific row IDs to process.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        # Load runtime context
        ctx = load_runtime_context()

        # Resolve paths using canonical resolvers
        send_script = resolve_send_script(ctx)
        excel_utils = resolve_excel_utils(ctx)
        workbook_path = get_workbook_path(ctx, project_ref)

        # Resolve project directory for state updates
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            from project_ref_utils import resolve_project_ref

            resolution = resolve_project_ref(project_ref)
            project_dir = (
                Path(resolution["config_path"]).parent
                if resolution.get("success") and resolution.get("config_path")
                else None
            )
        finally:
            if str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))

        # Get CDP port from context if not provided
        if cdp_port is None:
            cdp_port = ctx.get("profile", {}).get("CDP_PORT", "9234")

        print(f"Workbook: {workbook_path}")
        print(f"CDP Port: {cdp_port}")
        print(f"Mode: {'verify-only' if verify_only else 'send'}")
        print()

        # Read sendable rows
        rows = read_sendable_rows(excel_utils, workbook_path, row_ids)

        if not rows:
            print("No sendable rows found (next_action=send)")
            return 0

        print(f"Found {len(rows)} row(s) to process")
        print()

        # Process each row
        success_count = 0
        failed_rows: list[tuple[int, str]] = []

        for i, row in enumerate(rows, 1):
            row_id = row.get("row_id")
            name = row.get("name", "Unknown")
            profile_url = row.get("profile_url", "")
            subject = row.get("draft_subject", "")
            body = row.get("draft_body", "")

            print(f"[{i}/{len(rows)}] Row {row_id}: {name}")
            print(f"  URL: {profile_url}")

            if not profile_url:
                print(f"  ERROR: No profile_url, skipping")
                failed_rows.append((row_id, "missing profile_url"))
                continue

            if not subject or not body:
                print(f"  ERROR: Missing draft_subject or draft_body, skipping")
                failed_rows.append((row_id, "missing draft content"))
                continue

            try:
                # Execute send
                result = send_inmail(
                    send_script=send_script,
                    cdp_port=cdp_port,
                    work_dir=ctx.get("work_dir"),
                    profile_url=profile_url,
                    subject=subject,
                    body=body,
                    verify_only=verify_only,
                )

                # Update workbook based on result
                update_row_after_send(excel_utils, workbook_path, row, result, today)

                status = result.get("status", "FAILED")
                print(f"  Result: {status}")

                if status in ("SENT", "VERIFIED", "ALREADY_CONTACTED"):
                    success_count += 1
                else:
                    failed_rows.append((row_id, result.get("reason", "unknown")))

            except BrowserStateError as e:
                print(f"  FATAL: {e}")
                print()
                print("Browser state is not clean. Operator intervention required.")
                print()
                # Surface structured action_required if available
                if e.action_required:
                    ar = e.action_required
                    print(f"Issue: {ar.get('summary', 'Unknown issue')}")
                    print(f"Code: {ar.get('code', 'unknown')}")
                    print()
                    print("Manual steps to resolve:")
                    for i, step in enumerate(ar.get("steps", []), 1):
                        print(f"  {i}. {step}")
                    print()
                    if ar.get("context"):
                        print(f"Context: {ar['context']}")
                else:
                    print(
                        "Please check the browser and resolve any open dialogs or composers."
                    )
                if project_dir:
                    sys.path.insert(0, str(SCRIPT_DIR))
                    try:
                        from project_state import update_project_state

                        update_project_state(
                            project_dir=project_dir,
                            current_phase="send",
                            status="action_required",
                            action_required=e.action_required
                            or {
                                "code": "browser_state_not_clean",
                                "summary": str(e),
                                "steps": [
                                    "Check the browser and resolve the visible issue before retrying"
                                ],
                            },
                            last_result_summary="Send blocked by browser/manual intervention",
                            last_error=str(e),
                        )
                    finally:
                        if str(SCRIPT_DIR) in sys.path:
                            sys.path.remove(str(SCRIPT_DIR))
                return e.exit_code
            except SendError as e:
                print(f"  ERROR: {e}")
                failed_rows.append((row_id, str(e)))

            print()

        # Summary
        print("=" * 50)
        print(f"Processed: {len(rows)} row(s)")
        print(f"Successful: {success_count}")
        print(f"Failed: {len(failed_rows)}")

        # Update project state based on results
        if project_dir:
            sys.path.insert(0, str(SCRIPT_DIR))
            try:
                from project_state import update_project_state

                if failed_rows:
                    update_project_state(
                        project_dir=project_dir,
                        current_phase="send",
                        status="failed",
                        last_result_summary=f"Send: {success_count} succeeded, {len(failed_rows)} failed",
                        last_error=f"Failed rows: {', '.join(str(r[0]) for r in failed_rows)}",
                    )
                else:
                    update_project_state(
                        project_dir=project_dir,
                        current_phase="send",
                        status="completed",
                        action_required=False,
                        last_result_summary=f"Send complete: {success_count} row(s) processed",
                        last_error=False,
                    )
            finally:
                if str(SCRIPT_DIR) in sys.path:
                    sys.path.remove(str(SCRIPT_DIR))

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
    except SendError as e:
        print(f"Send error: {e}", file=sys.stderr)
        return e.exit_code
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send InMails for workbook rows with next_action=send"
    )
    parser.add_argument(
        "--project",
        dest="project_ref",
        required=True,
        help="Project reference: local PROJECT_ID, Recruiter URL, or numeric ID",
    )
    parser.add_argument(
        "--cdp-port",
        help="Chrome DevTools Protocol port (default: from profile or 9234)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify the flow without actually sending",
    )
    parser.add_argument(
        "--row-id",
        help="Specific row ID(s) to process (comma-separated for multiple)",
    )

    args = parser.parse_args()

    project_ref: str = args.project_ref

    # Parse row IDs if provided
    row_ids: list[int] | None = None
    if args.row_id:
        try:
            row_ids = [int(x.strip()) for x in args.row_id.split(",")]
        except ValueError:
            print("Error: --row-id must be comma-separated integers", file=sys.stderr)
            return 3

    # run_send_macro now uses canonical resolution via get_workbook_path
    # which internally calls project_ref_utils.resolve_project_ref
    return run_send_macro(
        project_ref=project_ref,
        cdp_port=args.cdp_port,
        verify_only=args.verify_only,
        row_ids=row_ids,
    )


if __name__ == "__main__":
    sys.exit(main())
