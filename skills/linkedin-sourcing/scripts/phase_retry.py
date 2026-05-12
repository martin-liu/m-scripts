#!/usr/bin/env python3
"""Centralized retry + manual fallback for workflow phases.

Wraps any phase runner with bounded retries. After max retries,
returns a structured action_required asking the user to resolve manually.

Usage:
    from phase_retry import run_phase_with_retries

    result = run_phase_with_retries(
        phase="create_search",
        project_ref="1712545148",
        project_dir=Path("/path/to/project"),
        runner=lambda: run_create_search_phase(...),
    )
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_MAX_RETRIES = 3

PHASE_MAX_RETRIES: dict[str, int] = {
    "create_search": 3,
    "extract": 3,
    "filter": 2,
    "enrich": 3,
    "draft": 2,
    "send": 2,
}

RETRYABLE_FAILURE_CODES = {
    "timeout",
    "element_missing",
    "ambiguous_state",
    "verification_failed",
    "browser_unavailable",
    "wrong_page",
}


def _with_project_state(func: Callable, *args, **kwargs) -> Any:
    """Run func with project_state module temporarily on sys.path."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_state import load_project_state, save_project_state

        return func(load_project_state, save_project_state, *args, **kwargs)
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def get_max_retries(phase: str) -> int:
    return PHASE_MAX_RETRIES.get(phase, DEFAULT_MAX_RETRIES)


def should_retry(result: dict[str, Any]) -> bool:
    """Check if a failed result warrants a retry."""
    if result.get("success"):
        return False

    action_required = result.get("action_required")
    if action_required:
        if action_required.get("actor") == "user":
            return False
        if action_required.get("can_retry") is False:
            return False

    failure_code = result.get("failure_code") or result.get("block_reason")
    if failure_code in RETRYABLE_FAILURE_CODES:
        return True

    if result.get("can_retry") is True:
        return True

    return False


def _update_retry_state(
    load_project_state, save_project_state,
    project_dir: Path, phase: str, attempts: int, max_retries: int,
    result: dict[str, Any], exhausted: bool = False,
) -> None:
    state = load_project_state(project_dir) or {}
    retries = state.setdefault("phase_retries", {})
    retries[phase] = {
        "attempts": attempts,
        "max_retries": max_retries,
        "last_failure_code": result.get("failure_code") or result.get("block_reason"),
        "last_error": result.get("error") or result.get("message"),
        "exhausted": exhausted,
    }
    save_project_state(project_dir, state)


def _clear_retry_state(
    load_project_state, save_project_state,
    project_dir: Path, phase: str,
) -> None:
    state = load_project_state(project_dir) or {}
    state.setdefault("phase_retries", {}).pop(phase, None)
    save_project_state(project_dir, state)


def _load_retry_state(
    load_project_state, _save_project_state,
    project_dir: Path, phase: str,
) -> dict[str, Any]:
    state = load_project_state(project_dir) or {}
    return state.get("phase_retries", {}).get(phase) or {"attempts": 0}


def build_retry_exhausted_action_required(
    phase: str,
    project_ref: str,
    result: dict[str, Any],
    attempts: int,
    max_retries: int,
) -> dict[str, Any]:
    failure_code = result.get("failure_code") or result.get("block_reason") or "retry_exhausted"
    error = result.get("error") or result.get("message") or "Unknown failure"

    phase_steps = {
        "create_search": [
            "Open the LinkedIn Recruiter search page in Chrome",
            "If the AI Copilot widget is visible, create/refine the search manually",
            "Verify job title, location, company, keyword, and exclusion filters",
            "Confirm candidate results are visible",
        ],
        "extract": [
            "Open the Recruiter search results page in Chrome",
            "Confirm candidate cards are visible and the page is not loading",
            "Resolve any login, CAPTCHA, dialog, or wrong-page issue",
        ],
        "filter": [
            "Open the workbook and config.sh",
            "Check candidate rows and title exclusion rules",
            "Fix malformed workbook data if present",
        ],
        "enrich": [
            "Open LinkedIn Recruiter in Chrome",
            "Confirm candidate profile pages can be opened",
            "Resolve any login, CAPTCHA, or page blocking issue",
        ],
        "draft": [
            "Check config.sh messaging fields",
            "Ensure workbook rows have enough candidate data for drafting",
            "Fix missing project messaging fields if needed",
        ],
        "send": [
            "Open LinkedIn Recruiter in Chrome",
            "Close any open message composers or dialogs",
            "Confirm reviewed messages are approved for sending",
        ],
    }

    return {
        "code": "retry_exhausted",
        "summary": f"{phase} failed after {attempts}/{max_retries} attempts",
        "steps": phase_steps.get(
            phase,
            ["Check the project state and latest error", "Resolve the visible issue", "Retry the workflow"],
        ),
        "can_retry": True,
        "actor": "agent",
        "context": {
            "phase": phase,
            "project_ref": project_ref,
            "attempts": attempts,
            "max_retries": max_retries,
            "last_failure_code": failure_code,
            "last_error": error,
            "resume_command": f"python3 scripts/run_reachout_loop.py --project {project_ref} --retry-failed",
        },
    }


def run_phase_with_retries(
    *,
    phase: str,
    project_ref: str,
    project_dir: Path,
    runner: Callable[[], dict[str, Any]],
    reset_retry_count: bool = False,
) -> dict[str, Any]:
    """Run a phase with bounded retries and manual fallback."""
    max_retries = get_max_retries(phase)

    if reset_retry_count:
        _with_project_state(_clear_retry_state, project_dir, phase)

    retry_state = _with_project_state(_load_retry_state, project_dir, phase)
    attempts = int(retry_state.get("attempts", 0))
    last_result: dict[str, Any] = {}

    while attempts < max_retries:
        attempts += 1

        try:
            result = runner()
        except Exception as exc:
            result = {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "failure_code": "exception",
                "can_retry": True,
            }

        last_result = result

        if result.get("success"):
            _with_project_state(_clear_retry_state, project_dir, phase)
            return result

        _with_project_state(
            _update_retry_state, project_dir, phase, attempts, max_retries, result,
        )

        if not should_retry(result):
            return result

        if attempts < max_retries:
            time.sleep(min(2 * attempts, 10))

    action_required = build_retry_exhausted_action_required(
        phase=phase, project_ref=project_ref, result=last_result,
        attempts=attempts, max_retries=max_retries,
    )

    exhausted_result = {
        **last_result,
        "success": False,
        "blocked": True,
        "block_reason": "retry_exhausted",
        "failure_code": "retry_exhausted",
        "action_required": action_required,
        "error": action_required["summary"],
    }

    _with_project_state(
        _update_retry_state, project_dir, phase, attempts, max_retries,
        exhausted_result, exhausted=True,
    )

    return exhausted_result
