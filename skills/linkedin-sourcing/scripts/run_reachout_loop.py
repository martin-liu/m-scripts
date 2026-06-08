#!/usr/bin/env python3
"""End-to-end loop runner for LinkedIn sourcing reachout workflow.

Repeatedly runs: status -> check stop conditions -> run one phase -> repeat.

Stop conditions (clean stops):
    - action_required blockers
    - Human review boundary (review phase)
    - Confirm search boundary (unless --confirm-search flag given)
    - Send boundary (unless --confirm-send flag given)
    - Workflow complete (no more work)

Usage:
    # Run the loop with automatic stops at boundaries
    python3 run_reachout_loop.py --project "{PROJECT_ID}"

    # Confirm search filters and proceed to extraction
    python3 run_reachout_loop.py --project "{PROJECT_ID}" --confirm-search

    # Include send phase (requires explicit confirmation)
    python3 run_reachout_loop.py --project "{PROJECT_ID}" --confirm-send

    # Dry run (show what would happen without executing)
    python3 run_reachout_loop.py --project "{PROJECT_ID}" --dry-run

    # Single iteration (status + one phase)
    python3 run_reachout_loop.py --project "{PROJECT_ID}" --once

Exit codes:
    0 - Workflow complete or stopped cleanly at a boundary
    1 - Unexpected error or phase failure
    2 - action_required blocker present
    3 - Configuration error
"""

from __future__ import annotations

import argparse
import shlex
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


def get_loop_command(project_ref: str) -> str:
    """Get a path-safe loop command for the given project reference."""
    script_path = shlex.quote(str(SCRIPT_DIR / "run_reachout_loop.py"))
    quoted_project_ref = shlex.quote(project_ref)
    return f"python3 {script_path} --project {quoted_project_ref}"


def get_resume_command(project_ref: str) -> str:
    """Get the best canonical loop command available for a project reference."""
    if project_ref == "<project>":
        return get_loop_command(project_ref)

    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_ref_utils import resolve_project_ref

        resolution = resolve_project_ref(project_ref)
        if resolution.get("success") and resolution.get("local_project_id"):
            return get_loop_command(resolution["local_project_id"])
    except Exception:
        pass
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))

    return get_loop_command(project_ref)


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
    confirm_search: bool = False,
    retry_failed: bool = False,
) -> tuple[bool, str, int]:
    """Check if the loop should stop based on current status.

    Stop conditions:
        1. action_required blockers
        2. Workbook errors (unreadable/missing)
        3. Current phase failed
        4. Current phase still running
        5. Not ready (blocked state)
        6. Workflow complete (no next_phase and ready=True)
        7. Confirm search boundary (unless confirm_search=True)
        8. Send boundary (unless confirm_send=True)

    Args:
        status_result: Result from status.get_status()
        confirm_send: Whether to proceed past send boundary
        confirm_search: Whether to proceed past confirm_search boundary

    Returns:
        Tuple of (should_stop, reason, exit_code)
    """
    action_required = status_result.get("action_required")
    next_phase = status_result.get("next_phase")
    phase_to_run = next_phase or status_result.get("current_phase")
    current_phase = status_result.get("current_phase")
    phase_status = status_result.get("status")
    ready = status_result.get("ready", False)
    message = status_result.get("message", "")
    workbook_summary = status_result.get("workbook_summary") or {}

    # Stop 1: action_required blocker
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
        if retry_failed:
            retry_phase = next_phase or current_phase
            return (False, f"Retrying failed phase: {retry_phase}", 0)
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

    # Stop 7: Confirm search boundary (USER must verify filters before extraction)
    if next_phase == "confirm_search" and not confirm_search:
        return (
            True,
            "Stopped at confirm_search boundary - USER must verify search filters in Recruiter before extraction",
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
    reset_retry_count: bool = False,
) -> dict[str, Any]:
    """Run a single phase using run_phase module.

    Args:
        project_ref: Project reference
        phase: Phase name to run
        dry_run: If True, don't actually execute
        reset_retry_count: If True, clear previous retry state before running

    Returns:
        Phase result dict with phase_result details
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from run_phase import run_phase

        return run_phase(project_ref, phase, dry_run=dry_run, reset_retry_count=reset_retry_count)
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def classify_phase_result(phase_result: dict[str, Any]) -> tuple[bool, str, int]:
    """Classify phase result to determine loop continuation.

    Maps phase results to loop control decisions:
        - Success: continue loop
        - action_required blocker: stop with exit code 2
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

    # Check for action_required in state_after
    action_required = state_after.get("action_required") if state_after else None
    if action_required:
        code = action_required.get("code", "unknown")
        return (
            False,
            f"Phase '{phase}' blocked: {action_required.get('summary', 'Action required before continuing')}",
            2,
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


def format_stop_guidance(
    status_result: dict[str, Any],
    reason: str,
    exit_code: int,
    confirm_send: bool = False,
    confirm_search: bool = False,
) -> str:
    """Format clear guidance for what to do after loop stops.

    Args:
        status_result: Result from status.get_status()
        reason: Stop reason
        exit_code: Exit code
        confirm_send: Whether --confirm-send was used

    Returns:
        Formatted guidance string
    """
    lines = [f"\n⏹️  Stop: {reason}"]

    # Get the loop command from status
    fallback_loop_cmd = get_loop_command("<project>")
    loop_cmd = status_result.get("loop_command", fallback_loop_cmd)
    next_phase = status_result.get("next_phase")
    action_required = status_result.get("action_required")

    if action_required:
        # Blocker state - tell user to resolve then loop
        guidance = status_result.get("loop_resume_guidance", {})
        resolve_now = guidance.get("resolve_now", "Resolve the blocker")
        actor_label = (
            "User must resolve now"
            if guidance.get("actor") == "user"
            else "Agent should resolve now"
        )
        lines.append(f"\n{actor_label}:")
        lines.append(f"  {resolve_now}")
        for step in guidance.get("steps", []):
            lines.append(f"  - {step}")
        lines.append(f"\nThen resume with:")
        lines.append(f"  {loop_cmd}")
    elif next_phase == "confirm_search":
        # Confirm search boundary - USER must create and verify search
        lines.append(f"\n🛑 USER CONFIRMATION REQUIRED: Create and verify search")
        lines.append(f"  The USER must create the candidate search in LinkedIn Recruiter:")
        lines.append(f"    - Open the Recruiter project")
        lines.append(f"    - Use the AI Copilot to create a search (or configure filters manually)")
        lines.append(f"    - Verify Job Titles, Companies, and Keywords filters look correct")
        lines.append(f"    - Confirm candidate results are visible")
        # Show search creation guidance if available
        search_summary = status_result.get("create_search_summary")
        if search_summary:
            copilot_query = search_summary.get("copilot_query", "")
            if copilot_query:
                lines.append(f"\n  Copilot query (copy and paste into Recruiter):")
                lines.append(f"    {copilot_query[:200]}...")
        lines.append(f"\nAfter USER confirms the search is ready, resume with:")
        lines.append(f"  {loop_cmd} --confirm-search")
        lines.append(f"\n⚠️  Only use --confirm-search after the USER has created and verified the search")
    elif next_phase == "send":
        # Send boundary
        if confirm_send:
            # This shouldn't happen if confirm_send is True, but handle gracefully
            lines.append(f"\nTo send messages, run:")
            lines.append(f"  {loop_cmd} --confirm-send")
        else:
            lines.append(f"\nTo proceed with sending:")
            lines.append(f"  {loop_cmd} --confirm-send")
    elif exit_code == 0 and next_phase is None:
        # Workflow complete
        lines.append(f"\nWorkflow complete. No further action needed.")
    else:
        # Other stop conditions - always suggest loop
        lines.append(f"\nTo resume:")
        lines.append(f"  {loop_cmd}")

    return "\n".join(lines)


# Phase 1: Pre-flight check is warning-only (does not block)
# Phase 2: Set to True to enable blocking
PREFLIGHT_ENFORCED = True


def pre_flight_check(cdp_port: str) -> tuple[bool, dict | None]:
    """Check browser readiness before running a browser phase.

    Phase 1: Logs warnings only, returns (True, None) regardless.
    Phase 2: Returns (False, blocker) if checks fail.

    Args:
        cdp_port: Chrome DevTools Protocol port number

    Returns:
        Tuple of (ok, blocker_dict_or_none)
    """
    from browser_utils import check_cdp_available, probe_recruiter_auth, check_dialog_status
    from recruiter_url_utils import is_linkedin_domain

    issues = []

    # 1. CDP reachable?
    if not check_cdp_available(cdp_port):
        issues.append("CDP not available")
        if PREFLIGHT_ENFORCED:
            return False, {
                "code": "browser_unavailable",
                "summary": f"Chrome/CDP not available on port {cdp_port}",
                "steps": ["Run connect_browser.sh to establish connection"],
                "actor": "agent",
            }

    # 2. Auth valid? (read-only: don't navigate away from current page)
    if check_cdp_available(cdp_port):
        auth = probe_recruiter_auth(cdp_port, navigate=False)
        if not auth["authenticated"]:
            current_url = auth.get("url", "")
            is_linkedin = is_linkedin_domain(current_url) if current_url else False
            has_auth_indicators = any(
                indicator in (current_url or "").lower()
                for indicator in ["/login", "/checkpoint", "/challenge", "/cap", "/signin"]
            )

            if is_linkedin and has_auth_indicators:
                issues.append(f"Auth required (on {current_url})")
                if PREFLIGHT_ENFORCED:
                    return False, {
                        "code": "auth_required",
                        "summary": "LinkedIn auth required",
                        "steps": ["Log in to LinkedIn Recruiter in the browser"],
                        "actor": "user",
                    }

    # 3. Dialog blocking?
    if check_cdp_available(cdp_port):
        dialog_check = check_dialog_status(cdp_port)
        if dialog_check.get("has_dialog"):
            issues.append(f"Dialog blocking: {dialog_check.get('dialog_type')}")
            if PREFLIGHT_ENFORCED:
                return False, {
                    "code": "dialog_blocked",
                    "summary": "Browser dialog is blocking automation",
                    "steps": ["Dismiss the dialog in the browser"],
                    "actor": "agent",
                }

    # Phase 1: log warnings but don't block
    if issues and not PREFLIGHT_ENFORCED:
        print(f"[pre_flight] WARNINGS: {', '.join(issues)}")

    return True, None


def resolve_cdp_port(project_ref: str) -> str:
    """Resolve CDP port from project configuration."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_ref_utils import resolve_project_ref
        from config_utils import parse_config_file

        resolution = resolve_project_ref(project_ref)
        if resolution.get("success") and resolution.get("config_path"):
            config = parse_config_file(resolution["config_path"])
            return config.get("CDP_PORT", "9230")
    except Exception:
        pass
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))

    return "9230"


def run_loop_iteration(
    project_ref: str,
    confirm_send: bool = False,
    dry_run: bool = False,
    confirm_search: bool = False,
    retry_failed: bool = False,
) -> tuple[bool, str, int]:
    """Run one iteration of the loop: status check + phase execution.

    Args:
        project_ref: Project reference
        confirm_send: Whether to proceed past send boundary
        dry_run: If True, don't actually execute phases
        confirm_search: Whether to proceed past confirm_search boundary

    Returns:
        Tuple of (should_continue, message, exit_code)
    """
    # Step 1: Get status
    status_result = load_status(project_ref)
    next_phase = status_result.get("next_phase")
    phase_to_run = next_phase or status_result.get("current_phase")

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
    should_stop, reason, exit_code = check_stop_conditions(
        status_result,
        confirm_send,
        confirm_search,
        retry_failed,
    )
    if should_stop:
        guidance = format_stop_guidance(status_result, reason, exit_code, confirm_send, confirm_search)
        print(guidance)
        return (False, reason, exit_code)

    print(f"\n▶️  {reason}")

    if dry_run:
        print("  (dry-run mode - not executing)")
        return (True, "Dry run - would continue", 0)

    # Step 3: Pre-flight check ONLY for browser phases
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from phase_registry import get_phase_metadata

        phase_meta = get_phase_metadata(phase_to_run) if phase_to_run else {}
        if phase_meta.get("requires_browser"):
            cdp_port = resolve_cdp_port(project_ref)
            ok, blocker = pre_flight_check(cdp_port)
            if not ok:
                # Persist action_required so status shows the blocker
                from project_state import update_project_state
                from project_ref_utils import resolve_project_ref

                resolution = resolve_project_ref(project_ref)
                if resolution.get("success"):
                    project_dir = resolution["config_path"].parent
                    update_project_state(
                        project_dir,
                        current_phase=phase_to_run,
                        status="action_required",
                        action_required=blocker,
                        last_error=blocker.get("summary", "Pre-flight check failed"),
                    )
                return False, blocker["summary"], 2
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))

    # Step 4: Run the phase
    if not phase_to_run:
        return (False, "No phase available to run", 1)

    print(f"\nRunning phase: {phase_to_run}")
    phase_result = run_single_phase(
        project_ref, phase_to_run, dry_run=dry_run, reset_retry_count=retry_failed
    )

    # Step 4: Classify result
    should_continue, message, result_exit_code = classify_phase_result(phase_result)

    # Print phase result summary
    phase_success = phase_result.get("success", False)
    if phase_success:
        print(f"✅ Phase completed: {message}")
    else:
        print(f"❌ Phase issue: {message}")

    if not should_continue:
        try:
            refreshed_status = load_status(project_ref)
        except Exception:
            refreshed_status = {"loop_command": get_resume_command(project_ref)}
        guidance = format_stop_guidance(
            refreshed_status, message, result_exit_code, confirm_send
        )
        print(guidance)

    return (should_continue, message, result_exit_code)


def run_reachout_loop(
    project_ref: str,
    confirm_send: bool = False,
    dry_run: bool = False,
    once: bool = False,
    max_iterations: int = 100,
    confirm_search: bool = False,
    retry_failed: bool = False,
) -> int:
    """Run the reachout workflow loop.

    Args:
        project_ref: Project reference (ID, URL, or config path)
        confirm_send: Whether to proceed past send boundary
        dry_run: If True, show what would happen without executing
        once: If True, run only one iteration
        max_iterations: Safety limit to prevent infinite loops
        confirm_search: Whether to proceed past confirm_search boundary

    Returns:
        Exit code (0 for clean stop, non-zero for errors)
    """
    print(f"Starting reachout loop for project: {project_ref}")
    print(f"Options: confirm_send={confirm_send}, confirm_search={confirm_search}, dry_run={dry_run}, once={once}")

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
                confirm_search=confirm_search,
                retry_failed=retry_failed,
            )

            if not should_continue:
                print(f"\n{'=' * 60}")
                print(f"Loop stopped: {message}")
                # Resume guidance was already printed by run_loop_iteration
                return exit_code

            if once:
                print(f"\n{'=' * 60}")
                print("Single iteration complete (--once specified)")
                print(f"\nTo continue, run:")
                print(f"  {get_resume_command(project_ref)}")
                return 0

            # Brief pause between iterations
            time.sleep(0.5)

        except LoopConfigError as e:
            print(f"\n❌ Configuration error: {e}")
            print(f"\nTo retry, run:")
            print(f"  {get_resume_command(project_ref)}")
            return e.exit_code
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            print(f"\nTo retry, run:")
            print(f"  {get_resume_command(project_ref)}")
            return 1

    # Max iterations reached
    print(f"\n⚠️  Max iterations ({max_iterations}) reached - stopping")
    print(f"\nTo resume, run:")
    print(f"  {get_resume_command(project_ref)}")
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
        "--confirm-search",
        action="store_true",
        help="Proceed past confirm_search boundary to extraction",
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
        help="Run only one iteration (debug only)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry the current failed phase instead of stopping immediately",
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
        confirm_search=args.confirm_search,
        retry_failed=args.retry_failed,
    )


if __name__ == "__main__":
    sys.exit(main())
