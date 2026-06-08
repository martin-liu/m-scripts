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

# Phase 1: URL guard is warning-only (enforce=False)
# Phase 2: Set to True to enable blocking and recovery
URL_GUARD_ENFORCED = True


class GuardResult:
    """Result of URL guard check."""

    def __init__(
        self,
        ok: bool,
        current_url: str | None = None,
        expected_url: str | None = None,
        failure_code: str | None = None,
        action_required: dict | None = None,
    ):
        self.ok = ok
        self.current_url = current_url
        self.expected_url = expected_url
        self.failure_code = failure_code
        self.action_required = action_required


class ResolveResult:
    """Result of URL resolution for a phase."""

    def __init__(
        self,
        ok: bool,
        url: str | None = None,
        failure_code: str | None = None,
        action_required: dict | None = None,
    ):
        self.ok = ok
        self.url = url
        self.failure_code = failure_code
        self.action_required = action_required


def _get_current_url(cdp_port: str) -> str:
    """Get current URL using the standard agent-browser eval pattern."""
    from browser_utils import run_browser_command

    result = run_browser_command(cdp_port, "eval", "({ url: window.location.href })")
    if result.get("error"):
        return ""
    return result.get("parsed", {}).get("url", "")


def classify_timeout(cdp_port: str, expected_url_pattern: str | None = None) -> str:
    """Determine if timeout is due to wrong page or slow load.

    Args:
        cdp_port: Chrome DevTools Protocol port
        expected_url_pattern: Regex pattern for expected URL (optional)

    Returns:
        Failure code: "wrong_page" if URL doesn't match, "timeout" otherwise
    """
    import re
    from browser_utils import FailureCode

    current_url = _get_current_url(cdp_port)

    if expected_url_pattern and not re.search(expected_url_pattern, current_url):
        return FailureCode.WRONG_PAGE.value

    return FailureCode.TIMEOUT.value


def resolve_extract_search_url(cdp_port: str, config: dict[str, str]) -> ResolveResult:
    """Resolve the expected search URL for the extract phase.

    Wraps resolve_fresh_search_context() to provide a stable contract.
    """
    from run_extraction import resolve_fresh_search_context
    from recruiter_url_utils import extract_recruiter_id_from_url

    configured_url = config.get("RECRUITER_PROJECT_URL", "")
    if not configured_url:
        return ResolveResult(ok=False, failure_code="ambiguous_state")

    result = resolve_fresh_search_context(cdp_port, configured_url)

    if result.get("success"):
        fresh_url = result.get("fresh_url")
        if fresh_url:
            return ResolveResult(ok=True, url=fresh_url)

    # Resolution failed — return structured failure
    return ResolveResult(
        ok=False,
        failure_code=result.get("failure_code", "ambiguous_state"),
        action_required=result.get("action_required"),
    )


def url_guard(
    cdp_port: str,
    phase: str,
    config: dict[str, str],
    enforce: bool = False,
) -> GuardResult:
    """Ensure browser is on the expected page for this phase.

    When enforce=False: only inspects current URL, logs warnings, never navigates.
    When enforce=True: validates URL, attempts recovery if wrong page.
    """
    meta = get_phase_metadata(phase)

    # Phase doesn't need browser
    if not meta.get("requires_browser"):
        return GuardResult(ok=True)

    # Phase manages its own URLs (enrich, send)
    if not meta.get("expected_url_pattern"):
        return GuardResult(ok=True)

    # Get expected URL (only when enforcing)
    expected_url = None
    if enforce:
        resolver = meta.get("url_resolver")
        if resolver == "extract_search_url":
            resolve_result = resolve_extract_search_url(cdp_port, config)
            if not resolve_result.ok:
                # Resolution failed with actionable blocker
                return GuardResult(
                    ok=False,
                    failure_code=resolve_result.failure_code,
                    action_required=resolve_result.action_required
                    or {
                        "code": "wrong_page",
                        "summary": "Failed to resolve expected URL for extract phase",
                        "steps": ["Check browser state and project configuration"],
                        "actor": "agent",
                    },
                )
            expected_url = resolve_result.url

        if not expected_url:
            return GuardResult(ok=True)  # Can't guard without URL

    # Check current URL
    current_url = _get_current_url(cdp_port)

    import re

    pattern = meta["expected_url_pattern"]
    url_matches = bool(re.search(pattern, current_url))

    # For extract, also validate contextual search params
    if url_matches and phase == "extract" and expected_url:
        from recruiter_url_utils import is_contextual_search_url, extract_recruiter_id_from_url

        project_id = extract_recruiter_id_from_url(expected_url)
        if not is_contextual_search_url(current_url, project_id):
            url_matches = False

    if url_matches:
        return GuardResult(ok=True, current_url=current_url)

    # Wrong page — log warning (Phase 1) or recover (Phase 2)
    if not enforce:
        # Phase 1: log only, don't block
        print(
            f"[url_guard] WARNING: {phase} expected URL matching {pattern}, got {current_url}"
        )
        return GuardResult(ok=True, current_url=current_url)

    # Phase 2: attempt recovery
    max_recovery = meta.get("max_wrong_page_recovery", 0)
    if max_recovery <= 0 or not meta.get("can_recover_from_wrong_page", False):
        from browser_utils import ActionRequired, FailureCode

        return GuardResult(
            ok=False,
            current_url=current_url,
            expected_url=expected_url,
            failure_code=FailureCode.WRONG_PAGE.value,
            action_required=ActionRequired.wrong_page(
                expected_url=expected_url or "",
                actual_url=current_url,
            ).to_dict(),
        )

    # Attempt recovery: navigate to expected URL
    from browser_utils import run_browser_command
    from recruiter_page_utils import ensure_page_ready

    for attempt in range(max_recovery):
        run_browser_command(cdp_port, "open", expected_url, timeout=30)

        # Wait for page ready
        ready = ensure_page_ready(
            cdp_port=cdp_port,
            target_url=expected_url,
            max_wait_seconds=15.0,
        )
        if ready.get("ready"):
            # Re-check URL
            current_url = _get_current_url(cdp_port)
            url_matches = bool(re.search(pattern, current_url))

            # For extract, also validate contextual search params
            if url_matches and phase == "extract":
                from recruiter_url_utils import is_contextual_search_url, extract_recruiter_id_from_url

                project_id = extract_recruiter_id_from_url(expected_url)
                if not is_contextual_search_url(current_url, project_id):
                    url_matches = False

            if url_matches:
                return GuardResult(ok=True, current_url=current_url)

    # Recovery failed
    from browser_utils import ActionRequired, FailureCode

    return GuardResult(
        ok=False,
        current_url=current_url,
        expected_url=expected_url,
        failure_code=FailureCode.WRONG_PAGE.value,
        action_required=ActionRequired.wrong_page(
            expected_url=expected_url or "",
            actual_url=current_url,
        ).to_dict(),
    )


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
    cdp_port: str | None = None,
    expected_url_pattern: str | None = None,
) -> dict[str, Any]:
    """Run subprocess and parse JSON output.

    Args:
        cmd: Command to run
        timeout: Timeout in seconds
        success_code: Exit code indicating success
        blocked_code: Exit code indicating an action_required blocker
        blocked_reason: Reason string for blocked state
        cdp_port: Optional CDP port for timeout classification
        expected_url_pattern: Optional URL pattern for timeout classification

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
        # Classify timeout: wrong_page vs actual timeout
        failure_code = "timeout"
        if cdp_port and expected_url_pattern:
            try:
                failure_code = classify_timeout(cdp_port, expected_url_pattern)
            except Exception:
                pass  # Keep default on classification error

        return {
            "success": False,
            "error": f"Timeout after {timeout} seconds",
            "failure_code": failure_code,
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


def _merge_project_state_into_result(
    result: dict[str, Any],
    project_dir: Path,
) -> dict[str, Any]:
    """Supplement subprocess result with fields from project state.

    Subprocess scripts that don't output JSON still update project state
    with structured failure fields. This helper loads project state and
    merges any missing action_required, failure_code, etc.
    """
    try:
        state = load_project_state(project_dir)
        if not state:
            return result

        # Merge missing structured fields from project state
        if not result.get("action_required") and state.get("action_required"):
            result["action_required"] = state["action_required"]
        if not result.get("failure_code") and state.get("failure_code"):
            result["failure_code"] = state["failure_code"]
        # Derive failure_code from action_required.code if still missing
        if not result.get("failure_code") and result.get("action_required"):
            result["failure_code"] = result["action_required"].get("code")

        # If state shows action_required but result doesn't, mark as blocked
        if state.get("action_required") and not result.get("blocked"):
            result["blocked"] = True
            result["block_reason"] = result.get("failure_code", "action_required")
    except Exception:
        pass  # Best effort - don't fail if state read fails

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

    # Load config for CDP port and expected URL pattern for timeout classification
    from config_utils import parse_config_file

    config = parse_config_file(config_path)
    cdp_port = config.get("CDP_PORT", "9230")
    meta = get_phase_metadata("extract")
    expected_url_pattern = meta.get("expected_url_pattern")

    result = _run_subprocess_with_json_output(
        cmd,
        timeout=600,
        cdp_port=cdp_port,
        expected_url_pattern=expected_url_pattern,
    )

    # Preserve structured failure fields from JSON stdout
    parsed = result.get("parsed", {})
    if parsed.get("action_required"):
        result["action_required"] = parsed["action_required"]
    if parsed.get("failure_code"):
        result["failure_code"] = parsed["failure_code"]

    # Fallback: supplement from project state if subprocess didn't output JSON
    result = _merge_project_state_into_result(result, project_dir)

    # Treat extraction with action_required as blocked
    if not result["success"] and result.get("action_required"):
        result["blocked"] = True
        result["block_reason"] = result.get("failure_code", "extraction_blocked")

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

    from config_utils import parse_config_file

    config = parse_config_file(config_path)
    cdp_port = config.get("CDP_PORT", "9230")

    result = _run_subprocess_with_json_output(
        cmd,
        timeout=600,
        success_code=0,
        blocked_code=2,
        blocked_reason="browser_blocked",
        cdp_port=cdp_port,
    )

    # Fallback: supplement from project state if subprocess didn't output JSON
    result = _merge_project_state_into_result(result, project_dir)

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

    from config_utils import parse_config_file

    config = parse_config_file(config_path)
    cdp_port = config.get("CDP_PORT", "9230")

    result = _run_subprocess_with_json_output(
        cmd,
        timeout=600,
        success_code=0,
        blocked_code=2,
        blocked_reason="send_blocked",
        cdp_port=cdp_port,
    )

    # Fallback: supplement from project state if subprocess didn't output JSON
    result = _merge_project_state_into_result(result, project_dir)

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

    # Load config for URL guard
    from config_utils import parse_config_file

    config = parse_config_file(config_path)

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

    # NEW: URL guard before running phase (Phase 1: warning-only)
    meta = get_phase_metadata(phase)
    if meta.get("requires_browser") and meta.get("expected_url_pattern"):
        cdp_port = config.get("CDP_PORT", "9230")
        guard = url_guard(cdp_port, phase, config, enforce=URL_GUARD_ENFORCED)
        if not guard.ok:
            # Persist action_required so loop classification detects blocker
            state_after = update_project_state(
                project_dir,
                current_phase=phase,
                status="action_required",
                action_required=guard.action_required,
                last_error=guard.action_required.get("summary", "URL guard failed"),
            )
            return {
                "success": False,
                "phase": phase,
                "failure_code": guard.failure_code,
                "action_required": guard.action_required,
                "state_after": state_after,
            }

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
                # BUT: retry_exhausted is a failure, not a blocker - treat as failed
                if phase_result.get("failure_code") == "retry_exhausted":
                    result["error"] = phase_result.get("error", "Phase failed")
                    if phase_result.get("failure_code"):
                        result["failure_code"] = phase_result["failure_code"]
                    if phase_result.get("can_retry"):
                        result["can_retry"] = phase_result["can_retry"]
                    result["state_after"] = update_project_state(
                        project_dir,
                        status="failed",
                        last_error=result["error"],
                    )
                else:
                    result["error"] = phase_result.get("error", "Phase blocked")
                    # Preserve failure_code and can_retry for loop retry handling
                    if phase_result.get("failure_code"):
                        result["failure_code"] = phase_result["failure_code"]
                    if phase_result.get("can_retry"):
                        result["can_retry"] = phase_result["can_retry"]
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
