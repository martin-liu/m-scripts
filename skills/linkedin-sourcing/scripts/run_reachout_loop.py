#!/usr/bin/env python3
"""End-to-end loop runner for LinkedIn sourcing reachout workflow.

Repeatedly runs: status -> check stop conditions -> run one phase -> repeat.

Stop conditions (clean stops):
    - Browser/manual blockers (persisted action_required)
    - Human review boundary (review phase)
    - Send boundary (unless --confirm-send flag given)
    - Workflow complete (no more work)

Usage:
    # Run the loop with automatic stops at boundaries
    python3 run_reachout_loop.py --project "{PROJECT_ID}"

    # Include send phase (requires explicit confirmation)
    python3 run_reachout_loop.py --project "{PROJECT_ID}" --confirm-send

    # Dry run (show what would happen without executing)
    python3 run_reachout_loop.py --project "{PROJECT_ID}" --dry-run

    # Single iteration (status + one phase)
    python3 run_reachout_loop.py --project "{PROJECT_ID}" --once

Exit codes:
    0 - Workflow complete or stopped cleanly at a boundary
    1 - Unexpected error or phase failure
    2 - Browser/manual intervention required (action_required persisted)
    3 - Configuration error
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


class LoopConfigError(Exception):
    """Raised when loop configuration is invalid."""

    def __init__(self, message: str):
        super().__init__(message)
        self.exit_code = 3


def load_status(project_ref: str) -> dict[str, Any]:
    """Get current project status using status module.

    Args:
        project_ref: Project reference (ID, URL, or config path)

    Returns:
        Status dict from status.get_status()

    Raises:
        LoopConfigError: If status cannot be loaded
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from status import get_status

        status_result = get_status(project_ref)
        if status_result.get("error"):
            raise LoopConfigError(f"Status error: {status_result['error']}")
        return status_result
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def check_stop_conditions(
    status_result: dict[str, Any],
    confirm_send: bool = False,
) -> tuple[bool, str, int]:
    """Check if the loop should stop based on current status.

    Stop conditions:
        1. Browser/manual blockers (action_required present)
        2. Workbook errors (unreadable/missing)
        3. Current phase failed
        4. Current phase still running
        5. Not ready (blocked state)
        6. Workflow complete (no next_phase and ready=True)
        7. Human review boundary (review phase)
        8. Send boundary (unless confirm_send=True)

    Args:
        status_result: Result from status.get_status()
        confirm_send: Whether to proceed past send boundary

    Returns:
        Tuple of (should_stop, reason, exit_code)
    """
    action_required = status_result.get("action_required")
    next_phase = status_result.get("next_phase")
    current_phase = status_result.get("current_phase")
    phase_status = status_result.get("status")
    ready = status_result.get("ready", False)
    message = status_result.get("message", "")
    workbook_summary = status_result.get("workbook_summary") or {}

    # Stop 1: Browser/manual blocker (action_required present)
    if action_required is not None:
        code = action_required.get("code", "unknown")
        return (
            True,
            f"Action required ({code}): {action_required.get('summary', 'Manual intervention needed')}",
            2,
        )

    # Stop 2: Workbook errors (unreadable/missing)
    workbook_error = workbook_summary.get("error")
    if workbook_error:
        return (
            True,
            f"Workbook issue: {workbook_error}",
            1,
        )

    # Stop 3: Current phase failed
    if phase_status == "failed":
        return (
            True,
            f"Phase '{current_phase}' failed - needs attention before continuing",
            1,
        )

    # Stop 4: Current phase still running
    # If next_phase is None while running, we're blocked (not ready for next)
    if phase_status == "running":
        if next_phase is None:
            # Blocked state - phase running, not ready for next
            return (
                True,
                f"Phase '{current_phase}' is currently running - wait for completion",
                1,
            )
        else:
            # Clean wait state - phase running but next is determined
            return (
                True,
                f"Phase '{current_phase}' is currently running - wait for completion",
                0,
            )

    # Stop 5: Not ready (blocked state) - only when next_phase is None
    # This handles cases like workbook unreadable, action required, etc.
    if next_phase is None and not ready:
        return (
            True,
            f"Workflow blocked: {message or 'Not ready to proceed'}",
            1,
        )

    # Stop 6: Workflow complete (no next phase and ready=True)
    if next_phase is None and ready:
        return (True, "Workflow complete - no more phases to run", 0)

    # Stop 7: Human review boundary
    if next_phase == "review":
        return (
            True,
            "Stopped at review boundary - human review required before proceeding",
            0,
        )

    # Stop 8: Send boundary (unless confirmed)
    if next_phase == "send" and not confirm_send:
        return (
            True,
            "Stopped at send boundary - use --confirm-send to proceed with sending",
            0,
        )

    # Continue running
    return (False, f"Proceeding to phase: {next_phase}", 0)


def run_single_phase(
    project_ref: str,
    phase: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run a single phase using run_phase module.

    Args:
        project_ref: Project reference
        phase: Phase name to run
        dry_run: If True, don't actually execute

    Returns:
        Phase result dict with phase_result details
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from run_phase import run_phase

        return run_phase(project_ref, phase, dry_run=dry_run)
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def classify_phase_result(phase_result: dict[str, Any]) -> tuple[bool, str, int]:
    """Classify phase result to determine loop continuation.

    Maps phase results to loop control decisions:
        - Success: continue loop
        - Browser/manual blocked: stop with exit code 2
        - Review boundary: stop cleanly (exit code 0)
        - Failure: stop with exit code 1

    Args:
        phase_result: Result dict from run_phase

    Returns:
        Tuple of (should_continue, message, exit_code)
    """
    success = phase_result.get("success", False)
    phase = phase_result.get("phase", "unknown")
    error = phase_result.get("error")
    state_after = phase_result.get("state_after", {})

    # Check for action_required in state_after (browser/manual blocker)
    action_required = state_after.get("action_required") if state_after else None
    if action_required:
        code = action_required.get("code", "unknown")
        return (
            False,
            f"Phase '{phase}' blocked: {action_required.get('summary', 'Manual intervention required')}",
            2,
        )

    # Check for review phase (human stop boundary)
    if phase == "review" and success:
        return (
            False,
            "Review phase reached - human review required before proceeding",
            0,
        )

    # Check for explicit failure
    if not success:
        error_msg = error or "Unknown error"
        return (
            False,
            f"Phase '{phase}' failed: {error_msg}",
            1,
        )

    # Success - continue loop
    return (True, f"Phase '{phase}' completed successfully", 0)


def run_loop_iteration(
    project_ref: str,
    confirm_send: bool = False,
    dry_run: bool = False,
) -> tuple[bool, str, int]:
    """Run one iteration of the loop: status check + phase execution.

    Args:
        project_ref: Project reference
        confirm_send: Whether to proceed past send boundary
        dry_run: If True, don't actually execute phases

    Returns:
        Tuple of (should_continue, message, exit_code)
    """
    # Step 1: Get status
    status_result = load_status(project_ref)
    next_phase = status_result.get("next_phase")

    print(f"\n{'=' * 60}")
    print(f"Current phase: {status_result.get('current_phase', 'unknown')}")
    print(f"Status: {status_result.get('status', 'unknown')}")
    print(f"Next phase: {next_phase or 'None (complete)'}")

    # Show workbook summary if available
    workbook_summary = status_result.get("workbook_summary", {})
    by_action = workbook_summary.get("by_next_action", {})
    if by_action:
        print("\nWorkbook state:")
        for action, count in sorted(by_action.items()):
            print(f"  - {action}: {count}")

    # Step 2: Check stop conditions
    should_stop, reason, exit_code = check_stop_conditions(status_result, confirm_send)
    if should_stop:
        print(f"\n⏹️  Stop: {reason}")
        return (False, reason, exit_code)

    print(f"\n▶️  {reason}")

    if dry_run:
        print("  (dry-run mode - not executing)")
        return (True, "Dry run - would continue", 0)

    # Step 3: Run the phase
    print(f"\nRunning phase: {next_phase}")
    phase_result = run_single_phase(project_ref, next_phase, dry_run=dry_run)

    # Step 4: Classify result
    should_continue, message, result_exit_code = classify_phase_result(phase_result)

    # Print phase result summary
    phase_success = phase_result.get("success", False)
    if phase_success:
        print(f"✅ Phase completed: {message}")
    else:
        print(f"❌ Phase issue: {message}")

    return (should_continue, message, result_exit_code)


def run_reachout_loop(
    project_ref: str,
    confirm_send: bool = False,
    dry_run: bool = False,
    once: bool = False,
    max_iterations: int = 100,
) -> int:
    """Run the reachout workflow loop.

    Args:
        project_ref: Project reference (ID, URL, or config path)
        confirm_send: Whether to proceed past send boundary
        dry_run: If True, show what would happen without executing
        once: If True, run only one iteration
        max_iterations: Safety limit to prevent infinite loops

    Returns:
        Exit code (0 for clean stop, non-zero for errors)
    """
    print(f"Starting reachout loop for project: {project_ref}")
    print(f"Options: confirm_send={confirm_send}, dry_run={dry_run}, once={once}")

    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n{'=' * 60}")
        print(f"Iteration {iteration}")

        try:
            should_continue, message, exit_code = run_loop_iteration(
                project_ref,
                confirm_send=confirm_send,
                dry_run=dry_run,
            )

            if not should_continue:
                print(f"\n{'=' * 60}")
                print(f"Loop stopped: {message}")
                return exit_code

            if once:
                print(f"\n{'=' * 60}")
                print("Single iteration complete (--once specified)")
                return 0

            # Brief pause between iterations
            time.sleep(0.5)

        except LoopConfigError as e:
            print(f"\n❌ Configuration error: {e}")
            return e.exit_code
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            return 1

    # Max iterations reached
    print(f"\n⚠️  Max iterations ({max_iterations}) reached - stopping")
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="End-to-end loop runner for LinkedIn sourcing reachout workflow"
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project reference: local PROJECT_ID, Recruiter URL, or numeric ID",
    )
    parser.add_argument(
        "--confirm-send",
        action="store_true",
        help="Proceed past send boundary (required for sending)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without executing",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run only one iteration (status + one phase)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=100,
        help="Maximum loop iterations (safety limit)",
    )

    args = parser.parse_args()

    return run_reachout_loop(
        project_ref=args.project,
        confirm_send=args.confirm_send,
        dry_run=args.dry_run,
        once=args.once,
        max_iterations=args.max_iterations,
    )


if __name__ == "__main__":
    sys.exit(main())
