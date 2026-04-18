#!/usr/bin/env python3
"""Extraction phase runner for LinkedIn Recruiter (internal/advanced use only).

This script is used internally by the reachout loop. For normal workflow,
use the loop command which handles phase sequencing automatically:
    python3 scripts/run_reachout_loop.py --project <PROJECT_ID>

Performs page-by-page extraction into the workbook with deduplication
and resumability.

Features:
    - Config-driven invocation from config.sh
    - Workbook creation if missing
    - Deduplication by candidate profile URL
    - Appends/updates workbook rows with status=Extracted, next_action=filter
    - Resumable after interruption (safe to rerun on same page)
    - Idempotent: rerunning on same page won't create duplicates

Exit codes:
    0 - Success (all pages processed or no more results)
    1 - Configuration error or browser failure
    2 - Workbook I/O error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from zipfile import BadZipFile

# Runtime resolution: add current scripts dir to path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from runtime_manager import RuntimeManager
from excel_utils import upsert, get_existing_keys, create
from browser_utils import run_browser_command, safe_get_parsed
from project_ref_utils import resolve_project_ref
from config_utils import parse_config_file
from recruiter_url_utils import (
    extract_recruiter_id_from_url,
    is_contextual_search_url,
    build_project_overview_url,
)


def _copy_action_required_fields(
    result: dict[str, Any],
    source: dict[str, Any] | None,
) -> dict[str, Any]:
    """Copy structured manual-fallback fields from a nested result."""
    if not source:
        return result

    if source.get("action_required") is not None:
        result["action_required"] = source.get("action_required")
    if source.get("failure_code") is not None:
        result["failure_code"] = source.get("failure_code")

    return result


def _ok_result(**kwargs: Any) -> dict[str, Any]:
    """Build a success result dict with common fields.

    Args:
        **kwargs: Additional fields to include (e.g., current_url, is_last_page).

    Returns:
        Dict with success=True and provided fields.
    """
    result: dict[str, Any] = {"success": True}
    result.update(kwargs)
    return result


def _err_result(
    error: str,
    failure_code: str | None = None,
    action_required: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build an error result dict with structured failure fields.

    Args:
        error: Error message.
        failure_code: Optional stable failure code.
        action_required: Optional structured fallback dict.
        **kwargs: Additional fields to include.

    Returns:
        Dict with success=False and provided fields.
    """
    result: dict[str, Any] = {"success": False, "error": error}
    if failure_code is not None:
        result["failure_code"] = failure_code
    if action_required is not None:
        result["action_required"] = action_required
    result.update(kwargs)
    return result


def _nav_result(
    success: bool,
    url: str,
    state: str,
    method: str,
    error: str | None = None,
    is_last_page: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a navigation result dict with standard fields.

    Args:
        success: Whether navigation succeeded.
        url: The resulting URL.
        state: Page state classification.
        method: Navigation method used.
        error: Optional error message.
        is_last_page: Whether this is the last page (clean stop).
        **kwargs: Additional fields to include.

    Returns:
        Dict with navigation result fields.
    """
    result: dict[str, Any] = {
        "success": success,
        "url": url,
        "state": state,
        "method": method,
        "is_last_page": is_last_page,
    }
    if error is not None:
        result["error"] = error
    result.update(kwargs)
    return result


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    loop_script = SCRIPT_DIR / "run_reachout_loop.py"
    parser = argparse.ArgumentParser(
        description="Extract candidates from LinkedIn Recruiter to workbook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Normal workflow:
    python3 {loop_script} --project <PROJECT_ID>

Advanced/debug only:
Examples:
    # Project reference (local PROJECT_ID, Recruiter URL, or numeric ID)
    python3 run_extraction.py --project my_project
    python3 run_extraction.py --project https://linkedin.com/talent/hire/12345/...
    python3 run_extraction.py --project 12345

    # Config path (legacy/debug only)
    python3 run_extraction.py --config /path/to/config.sh

    # With explicit workbook override
    python3 run_extraction.py --project my_project --workbook /path/to/workbook.xlsx

    # Dry run (extract without writing)
    python3 run_extraction.py --project my_project --dry-run

    # Resume from page 3
    python3 run_extraction.py --project my_project --start-page 3

    # Resume from persisted state
    python3 run_extraction.py --project my_project --resume
        """,
    )

    # Mutually exclusive: --config or --project (exactly one required)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--config",
        help="Path to config.sh file containing RECRUITER_PROJECT_URL",
    )
    source_group.add_argument(
        "--project",
        help="Project reference: local PROJECT_ID, Recruiter URL, or numeric ID",
    )
    parser.add_argument(
        "--workbook",
        help="Path to workbook (default: resolved from the project)",
    )
    parser.add_argument(
        "--cdp-port",
        help="Chrome DevTools Protocol port (default: from profile or 9234)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract without writing to workbook (for testing)",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Start from page N (default: 1, disables auto-resume if provided)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Maximum pages to process (0 = unlimited, default: 0)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from persisted state (overrides --start-page)",
    )

    return parser.parse_args()


# Resume state version for compatibility checking
RESUME_STATE_VERSION = 1


def _coerce_path(value: Path | str | os.PathLike[str], label: str) -> Path:
    """Convert a path-like value to Path and reject non-path mocks.

    Args:
        value: Path-like value to normalize.
        label: Human-readable field name for errors.

    Returns:
        Normalized Path instance.

    Raises:
        TypeError: If value is not a supported path-like type.
    """
    if isinstance(value, Path):
        return value
    if isinstance(value, Mock):
        raise TypeError(
            f"Invalid {label}: expected path-like value, got {type(value).__name__}"
        )

    try:
        coerced = os.fspath(value)
    except TypeError as e:
        raise TypeError(
            f"Invalid {label}: expected path-like value, got {type(value).__name__}"
        ) from e

    if not isinstance(coerced, (str, bytes)):
        raise TypeError(
            f"Invalid {label}: expected path-like value, got {type(value).__name__}"
        )

    return Path(coerced)


def _get_workbook_state_key(workbook_path: Path, project_id: str) -> str:
    """Generate a unique state key for a workbook and project combination.

    Combines the workbook stem with a short stable hash of the resolved
    path and project_id to ensure:
    - Different workbooks with the same basename do not collide
    - Same workbook with different project_ids do not collide

    Args:
        workbook_path: Path to the workbook
        project_id: The Recruiter project ID

    Returns:
        A unique key string for state file naming
    """
    resolved = workbook_path.resolve()
    stem = resolved.stem
    # Include project_id in the hash to prevent cross-project collisions
    identity = f"{resolved}:{project_id}"
    # Short stable hash (8 hex chars) of the identity
    path_hash = hashlib.sha256(identity.encode()).hexdigest()[:8]
    return f"{stem}-{path_hash}"


def get_extraction_state_path(
    work_dir: Path, project_id: str, workbook_path: Path
) -> dict[str, Any]:
    """Get the path to the extraction state file for a project/workbook.

    State files are stored under WORK_DIR/runtime/extraction-state/ and are
    keyed by a stable identifier derived from the workbook path and project_id.

    Args:
        work_dir: The working directory (WORK_DIR)
        project_id: The Recruiter project ID
        workbook_path: Path to the workbook

    Returns:
        Dict with:
            - success: bool - whether path resolution succeeded
            - path: Path | None - the state file path if successful
            - error: str | None - error message if failed
    """
    try:
        normalized_work_dir = _coerce_path(work_dir, "work_dir")
        normalized_workbook_path = _coerce_path(workbook_path, "workbook_path")
    except TypeError as e:
        return {
            "success": False,
            "path": None,
            "error": str(e),
        }

    workbook_key = _get_workbook_state_key(normalized_workbook_path, project_id)
    state_dir = normalized_work_dir / "runtime" / "extraction-state"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, IOError) as e:
        return {
            "success": False,
            "path": None,
            "error": f"Failed to create state directory {state_dir}: {e}",
        }
    return {
        "success": True,
        "path": state_dir / f"{workbook_key}.json",
        "error": None,
    }


def load_extraction_state(state_path: Path) -> dict[str, Any] | None:
    """Load extraction state from file.

    Args:
        state_path: Path to the state file

    Returns:
        State dict if valid, None if file doesn't exist or is invalid
    """
    if not state_path.exists():
        return None

    try:
        content = state_path.read_text()
        state = json.loads(content)

        # Basic validation: must be a dict with required fields
        if not isinstance(state, dict):
            return None

        required_fields = {
            "version",
            "project_id",
            "workbook_path",
            "status",
            "updated_at",
        }
        if not required_fields.issubset(state.keys()):
            return None

        # Version check
        if state.get("version") != RESUME_STATE_VERSION:
            return None

        return state
    except (json.JSONDecodeError, OSError, IOError):
        return None


def save_extraction_state(
    state_path: Path,
    project_id: str,
    workbook_path: Path,
    config_path: str,
    status: str,
    last_completed_page: int | None,
    next_start_page: int | None,
    error: str | None = None,
    fresh_url: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Save extraction state to file atomically.

    Uses temp file + rename pattern for atomic writes. Preserves old
    valid state if write fails or is interrupted.

    Args:
        state_path: Path to the state file
        project_id: The Recruiter project ID
        workbook_path: Path to the workbook
        config_path: Path to the config file
        status: One of 'running', 'failed', 'completed'
        last_completed_page: The last page that was successfully processed
        next_start_page: The page to start from on resume (null if completed)
        error: Optional error message for failed state
        fresh_url: The actual fresh contextual URL used for extraction
        dry_run: Whether this state was created during a dry-run

    Returns:
        True if saved successfully, False otherwise
    """
    state = {
        "version": RESUME_STATE_VERSION,
        "project_id": project_id,
        "workbook_path": str(workbook_path),
        "config_path": str(config_path),
        "status": status,
        "last_completed_page": last_completed_page,
        "next_start_page": next_start_page,
        "dry_run": dry_run,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if error:
        state["error"] = error
    if fresh_url:
        state["fresh_url"] = fresh_url

    # Atomic write: temp file + rename
    # This ensures old state is preserved if write fails or is interrupted
    temp_path = state_path.with_suffix(".tmp")
    try:
        # Write to temp file first
        temp_path.write_text(json.dumps(state, indent=2))
        # Atomic rename (POSIX guarantees this is atomic)
        temp_path.replace(state_path)
        return True
    except (OSError, IOError):
        # Clean up temp file if it exists
        try:
            if temp_path.exists():
                temp_path.unlink()
        except (OSError, IOError):
            pass  # Best effort cleanup
        return False


def is_resumable_state(state: dict[str, Any] | None) -> tuple[bool, int | None, str]:
    """Check if a state is resumable and return the next start page.

    Args:
        state: The loaded state dict or None

    Returns:
        Tuple of (is_resumable, next_start_page, reason)
        - is_resumable: True if state can be used for resume
        - next_start_page: The page to resume from (if resumable)
        - reason: Human-readable reason if not resumable
    """
    if state is None:
        return False, None, "No persisted state found"

    # Status must be running or failed (not completed)
    status = state.get("status")
    if status == "completed":
        return False, None, "Extraction already completed"

    if status not in ("running", "failed"):
        return False, None, f"Invalid status: {status}"

    # Must have a valid next_start_page >= 1
    next_start_page = state.get("next_start_page")
    if next_start_page is None:
        return False, None, "No resume page available"

    try:
        page = int(next_start_page)
        if page < 1:
            return False, None, f"Invalid resume page: {page}"
        return True, page, ""
    except (ValueError, TypeError):
        return False, None, f"Invalid resume page value: {next_start_page}"


def resolve_workbook_path(
    config: dict[str, str], cli_path: str | None, config_path: Path | None = None
) -> Path:
    """Resolve workbook path from CLI arg or config.

    Supports both new layout (workbook.xlsx in project dir) and legacy layout
    ({PROJECT_ID}.xlsx at projects root).

    Args:
        config: Parsed config dict
        cli_path: Optional CLI-provided path
        config_path: Optional path to config.sh for new layout resolution

    Returns:
        Resolved Path to workbook
    """
    if cli_path:
        return Path(cli_path).expanduser().resolve()

    # Derive from PROJECT_ID and WORK_DIR
    project_id = config.get("PROJECT_ID")
    if not project_id:
        raise ValueError("PROJECT_ID not found in config and no --workbook provided")

    # Use RuntimeManager to get work_dir
    manager = RuntimeManager()
    work_dir = manager.work_dir

    # Check new layout first: workbook.xlsx in same dir as config.sh
    if config_path is not None:
        new_layout_path = config_path.parent / "workbook.xlsx"
        if new_layout_path.exists():
            return new_layout_path

    # Check legacy layout: {PROJECT_ID}.xlsx at projects root
    legacy_path = work_dir / "projects" / f"{project_id}.xlsx"
    if legacy_path.exists():
        return legacy_path

    # Default to new layout for new projects (config_path parent)
    if config_path is not None:
        return config_path.parent / "workbook.xlsx"

    # Fallback to legacy path if no config_path provided
    return legacy_path


def ensure_workbook(workbook_path: Path) -> bool:
    """Ensure workbook exists, creating if necessary.

    Args:
        workbook_path: Path to workbook

    Returns:
        True if workbook exists or was created, False on error
    """
    if workbook_path.exists():
        return True

    try:
        workbook_path.parent.mkdir(parents=True, exist_ok=True)
        create(workbook_path)
        return True
    except Exception as e:
        print(f"Error creating workbook: {e}", file=sys.stderr)
        return False


def extract_project_id_from_url(url: str) -> str | None:
    """Extract project ID from a LinkedIn Recruiter URL.

    Args:
        url: LinkedIn Recruiter URL

    Returns:
        Project ID string if found, None otherwise
    """
    from urllib.parse import urlparse

    # Validate URL is from LinkedIn domain
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not (hostname == "linkedin.com" or hostname.endswith(".linkedin.com")):
        return None

    # Use shared implementation for ID extraction
    return extract_recruiter_id_from_url(url)


def is_contextual_recruiter_search_url(url: str, project_id: str) -> bool:
    """Check if URL is a contextual recruiterSearch URL for the given project.

    A contextual URL has search context parameters and belongs to the
    specified project. This prevents accepting bare /discover/recruiterSearch
    URLs that would hang on "Loading search results".

    Args:
        url: The URL to check
        project_id: The expected project ID

    Returns:
        True if URL is a contextual recruiterSearch URL for the project
    """
    # Use shared implementation with project_id validation
    return is_contextual_search_url(url, project_id)


def check_current_page_ready_for_extraction(
    cdp_port: str,
    project_id: str,
) -> dict[str, Any]:
    """Check if current browser page is ready for extraction.

    Validates that the current page is:
    1. A contextual recruiterSearch URL for the project
    2. In ready state (not loading)
    3. Has actual search results content

    Args:
        cdp_port: Chrome DevTools Protocol port number
        project_id: The expected project ID

    Returns:
        Dict with:
            - ready: bool - whether page is ready for extraction
            - current_url: str - the current URL
            - state: str - page state classification
    """
    from recruiter_page_utils import PageStateProbe
    from browser_utils import run_browser_command, safe_get_parsed

    # Get current URL
    result = run_browser_command(cdp_port, "eval", "({ url: window.location.href })")
    # Use safe_get_parsed to avoid AttributeError when parsed is None or not a dict
    current_url = safe_get_parsed(result, default={}).get("url", "")

    # Check if already on contextual search page for this project
    if not is_contextual_recruiter_search_url(current_url, project_id):
        return {
            "ready": False,
            "current_url": current_url,
            "state": "not_contextual_search",
        }

    # Check page state
    probe = PageStateProbe(cdp_port)
    state_result = probe.classify_state()
    state = state_result.get("state", "unknown")
    details = state_result.get("details", {})

    if state != "ready":
        return {
            "ready": False,
            "current_url": current_url,
            "state": state,
        }

    # Fail closed when the project is still on Recruiter's search-creation UI.
    if details.get("hasSearchCreationPrompt"):
        return {
            "ready": False,
            "current_url": current_url,
            "state": "search_not_configured",
        }

    # Keep failing closed on generic/stale ready states that still look like an
    # overview or non-results shell even though the URL is contextual.
    if not details.get("hasSearchResultsContent") and details.get("hasOverviewContent"):
        return {
            "ready": False,
            "current_url": current_url,
            "state": "no_search_results_content",
        }

    return {
        "ready": True,
        "current_url": current_url,
        "state": "ready",
    }


# Maximum time to wait for contextual search URL to appear after navigation.
# LinkedIn Recruiter can take significant time to generate search context params.
CONTEXTUAL_URL_WAIT_SECONDS = 60


def resolve_fresh_search_context(
    cdp_port: str,
    configured_url: str,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """Resolve a fresh contextual search URL for this run.

    Starting from a configured URL that may be stale or bare,
    navigate to the project overview and use resolve_search_url()
    to obtain a fresh contextual page-1 URL.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        configured_url: The URL from config (may be stale or bare)
        work_dir: Optional working directory for incident reporting

    Returns:
        Dict with:
            - success: bool - whether resolution succeeded
            - fresh_url: str | None - the fresh contextual URL if successful
            - error: str | None - error message if failed
            - action_required: dict | None - structured fallback if manual intervention needed
            - failure_code: str | None - stable failure code if failed
    """
    # Import here to avoid circular imports
    from ensure_recruiter_project import (
        resolve_search_url,
        validate_project_context,
        is_contextual_search_url,
    )
    from recruiter_page_utils import RecoveryHelper, ensure_page_ready
    from urllib.parse import urlparse
    from browser_utils import safe_get_parsed, FailureCode, ActionRequired

    # Extract project ID from configured URL
    project_id = extract_project_id_from_url(configured_url)
    if not project_id:
        return {
            "success": False,
            "fresh_url": None,
            "error": f"Could not extract project ID from URL: {configured_url}",
            "failure_code": FailureCode.WRONG_PAGE,
            "action_required": ActionRequired.wrong_page(
                expected_url="/talent/hire/{numeric_id}",
                actual_url=configured_url,
            ).to_dict(),
        }

    # OPTIMIZATION: Check if browser is already on a valid contextual search page
    # for the same project. This avoids unnecessary navigation when the user has
    # manually navigated to the search results or a previous run left the browser
    # on a valid page.
    current_check = check_current_page_ready_for_extraction(cdp_port, project_id)
    if current_check["ready"]:
        return {
            "success": True,
            "fresh_url": current_check["current_url"],
            "error": None,
            "action_required": None,
            "failure_code": None,
        }

    # Build stable project overview URL
    overview_url = build_project_overview_url(project_id)

    # Navigate to project overview with explicit validation
    recovery = RecoveryHelper(cdp_port, work_dir)
    recovery._navigate_to_url(overview_url)
    time.sleep(2)  # Allow page to load

    # CRITICAL: Verify we are actually on the overview page before proceeding.
    # This prevents accepting a stale contextual search URL from a previous run.
    # Retry with patience: overview page may take time to stabilize after navigation.
    max_wait_attempts = 5
    wait_delay_seconds = 2
    ensure_result = None

    for attempt in range(1, max_wait_attempts + 1):
        ensure_result = ensure_page_ready(
            cdp_port=cdp_port,
            work_dir=work_dir,
            target_url=overview_url,
            context="resolve_fresh_search_context_overview",
            expected_url_patterns=[f"/talent/hire/{project_id}/overview"],
        )

        if ensure_result["ready"]:
            break

        # If still loading, wait and retry (fail-closed on non-loading failures)
        if ensure_result.get("state") == "loading" and attempt < max_wait_attempts:
            time.sleep(wait_delay_seconds)
            continue

        # Not loading or max attempts reached - fail closed
        break

    if not ensure_result or not ensure_result["ready"]:
        result = {
            "success": False,
            "fresh_url": None,
            "error": (
                f"Failed to navigate to stable project overview page: {ensure_result.get('state', 'unknown state')}. "
                f"Identity check: {ensure_result.get('identity_check', {})}. "
                "Cannot resolve fresh search context without confirmed project context."
            ),
            "failure_code": FailureCode.WRONG_PAGE,
            "action_required": ActionRequired.wrong_page(
                expected_url=overview_url,
                actual_url=ensure_result.get("current_url") if ensure_result else None,
            ).to_dict(),
        }
        return _copy_action_required_fields(result, ensure_result)

    # Validate we're on the correct project
    context_validation = validate_project_context(
        browser_mode=cdp_port,
        project_name="",  # We don't have the project name here, skip name validation
        expected_project_id=project_id,
    )

    if not context_validation["valid"]:
        return {
            "success": False,
            "fresh_url": None,
            "error": f"Project context validation failed: {context_validation.get('error', 'Unknown error')}",
            "failure_code": FailureCode.VERIFICATION_FAILED,
            "action_required": ActionRequired.verification_failed(
                verification_type="project_context",
                details=context_validation.get("error"),
            ).to_dict(),
        }

    # Get current URL after confirmed navigation to overview
    current_url = context_validation.get("current_url", overview_url)

    # Verify we're actually on the overview page, not a stale search page
    if f"/talent/hire/{project_id}/overview" not in current_url:
        return {
            "success": False,
            "fresh_url": None,
            "error": (
                f"Navigation landed on unexpected page: {current_url}. "
                f"Expected project {project_id} overview. "
                "Cannot resolve fresh search context from non-overview page."
            ),
            "failure_code": FailureCode.WRONG_PAGE,
            "action_required": ActionRequired.wrong_page(
                expected_url=overview_url,
                actual_url=current_url,
            ).to_dict(),
        }

    # Use canonical resolve_search_url to get fresh contextual URL
    # This will navigate from overview to search and return the contextual URL
    fresh_url = resolve_search_url(cdp_port, current_url)

    # ROBUSTNESS: If resolve_search_url returns None, it may be due to delayed
    # context appearance. Poll with bounded wait before failing (fail-closed).
    if fresh_url is None:
        poll_interval_seconds = 3
        start_time = time.time()
        elapsed = 0.0

        while elapsed < CONTEXTUAL_URL_WAIT_SECONDS:
            # Wait for potential delayed context transition
            time.sleep(poll_interval_seconds)
            elapsed = time.time() - start_time

            # Check if context has appeared on current page
            result = run_browser_command(
                cdp_port, "eval", "({ url: window.location.href })"
            )
            # Use safe_get_parsed to avoid AttributeError when parsed is None
            check_url = safe_get_parsed(result, default={}).get("url", "")

            if is_contextual_search_url(check_url):
                return {
                    "success": True,
                    "fresh_url": check_url,
                    "error": None,
                    "action_required": None,
                    "failure_code": None,
                }

            # Try resolve_search_url again
            fresh_url = resolve_search_url(cdp_port, current_url)
            if fresh_url is not None:
                break

    if fresh_url is None:
        return {
            "success": False,
            "fresh_url": None,
            "error": (
                f"Could not resolve fresh search context from {current_url}. "
                "The configured URL may be stale or the project may not have active search context. "
                "Try visiting the project in LinkedIn Recruiter and performing a search first."
            ),
            "failure_code": FailureCode.AMBIGUOUS_STATE,
            "action_required": ActionRequired.ambiguous_state(
                details=f"Could not resolve contextual search URL from {current_url}"
            ).to_dict(),
        }

    readiness = check_current_page_ready_for_extraction(cdp_port, project_id)
    if not readiness.get("ready") and readiness.get("state") == "search_not_configured":
        current_url = readiness.get("current_url") or fresh_url
        return {
            "success": False,
            "fresh_url": None,
            "error": (
                "Recruiter project does not have a candidate search yet. "
                "Create a search from the JD or boolean query, review the generated filters, "
                "and make sure candidates are visible before extraction."
            ),
            "failure_code": FailureCode.WRONG_PAGE,
            "action_required": {
                "code": FailureCode.WRONG_PAGE,
                "summary": "Recruiter project is still on the search-creation screen",
                "steps": [
                    "Open the Recruiter project in Chrome",
                    "Use Create a search from a job description, Boolean search, or profile",
                    "Review and fix the generated filters, including titles, companies, locations, and excludes",
                    "Confirm candidate cards or a real results count are visible in Recruiter",
                    "Retry extraction after the search is configured",
                ],
                "can_retry": True,
                "context": {
                    "current_url": current_url,
                    "project_id": project_id,
                },
                "actor": "agent",
            },
        }

    return {
        "success": True,
        "fresh_url": fresh_url,
        "error": None,
        "action_required": None,
        "failure_code": None,
    }


def click_next_page_pagination(
    cdp_port: str,
    expected_start: int | None = None,
    max_wait_seconds: float = 10.0,
    poll_interval: float = 0.5,
) -> dict[str, Any]:
    """Click the live pagination control to navigate to next page.

    Uses UI pagination controls from the loaded current page rather than
    synthesizing a stale paginated URL. For page > 1, polls the URL until
    the expected start offset appears or timeout is reached.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        expected_start: Expected start offset in URL (e.g., 25 for page 2)
        max_wait_seconds: Maximum time to wait for URL transition
        poll_interval: Seconds between URL checks

    Returns:
        Dict with:
            - success: bool - whether click succeeded (or clean end-of-results)
            - is_last_page: bool - True if disabled/missing next button detected
            - previous_url: str - URL before click
            - current_url: str - URL after click
            - error: str | None - error message if failed (not for last page)
            - failure_code: str | None - stable failure code if failed
            - action_required: dict | None - structured fallback if manual intervention needed
    """
    # JavaScript to click pagination and return URL change info
    # CRITICAL: Restrict matching to actual Recruiter pagination controls.
    # LinkedIn pages can contain unrelated carousel/buttons with text like "Next"
    # that do not paginate the search results. Prefer result-list pagination
    # controls, then fall back to mini-pagination in the header.
    CLICK_NEXT_PAGE_JS = r"""
    (function() {
        const previousUrl = window.location.href;

        function isDisabled(el) {
            return el.disabled ||
                   el.getAttribute('disabled') ||
                   el.classList.contains('artdeco-button--disabled');
        }

        function getPaginationRoot(el) {
            return el.closest(
                '[data-test-ts-pagination], ' +
                '.profile-list-container__pagination, ' +
                '.pagination, ' +
                '.mini-pagination, ' +
                '[data-test-mini-pagination-next], ' +
                '[data-test-pagination-next]'
            );
        }

        function getPaginationScore(el) {
            const root = getPaginationRoot(el);
            const rootClass = root ? (root.className || '') : '';
            const elClass = el.className || '';
            let score = 0;

            if (!root && !elClass.includes('artdeco-pagination__button--next')) {
                return -1;
            }

            if (root && root.matches('.profile-list-container__pagination, .pagination')) score += 100;
            if (root && root.matches('.mini-pagination')) score += 50;
            if (root && root.hasAttribute('data-test-ts-pagination')) score += 25;
            if (el.hasAttribute('data-test-pagination-next') || elClass.includes('pagination__quick-link--next')) score += 20;
            if (el.hasAttribute('data-test-mini-pagination-next') || elClass.includes('mini-pagination__quick-link')) score += 10;
            if ((el.getAttribute('rel') || '').toLowerCase() === 'next') score += 5;
            // Live UI pattern: artdeco-pagination__button--next
            if (elClass.includes('artdeco-pagination__button--next')) score += 15;
            if (rootClass.includes('artdeco-carousel')) score -= 200;

            return score;
        }

        function isPaginationCandidate(el) {
            const elClass = el.className || '';
            // Allow artdeco pagination buttons even without traditional pagination root
            if (elClass.includes('artdeco-pagination__button--next')) return true;
            return getPaginationScore(el) >= 0;
        }

        function getEnabledPaginationCandidates() {
            return Array.from(document.querySelectorAll('a, button'))
                .filter(el => !isDisabled(el))
                .filter(isPaginationCandidate)
                .filter(el => {
                    const text = (el.textContent || '').trim();
                    const aria = (el.getAttribute('aria-label') || '').trim();
                    const title = (el.getAttribute('title') || '').trim();
                    const rel = (el.getAttribute('rel') || '').trim().toLowerCase();
                    return /Go to next page\\s+\\d+/i.test(text) ||
                           /Go to next page\\s+\\d+/i.test(aria) ||
                           /Go to next page\\s+\\d+/i.test(title) ||
                           rel === 'next' ||
                           el.hasAttribute('data-test-pagination-next') ||
                           el.hasAttribute('data-test-mini-pagination-next') ||
                           text.toLowerCase() === 'next' ||
                           aria.toLowerCase().includes('next');
                })
                .sort((a, b) => getPaginationScore(b) - getPaginationScore(a));
        }

        // Strategy 1: Look for ENABLED "Go to next page N" link with specific text pattern
        // This must come BEFORE disabled button check to handle the case where page 1
        // has both a disabled "Next" button AND enabled page-2 anchor controls.
        const nextLinks = getEnabledPaginationCandidates();
        const nextLink = nextLinks[0];

        if (nextLink) {
            nextLink.scrollIntoView({ block: 'center' });
            nextLink.click();
            return {
                clicked: true,
                isLastPage: false,
                method: 'next_link',
                text: nextLink.textContent.trim(),
                previousUrl: previousUrl
            };
        }

        // Strategy 2: Look for ENABLED pagination button with chevron/right arrow
        // Exclude both attribute-disabled and class-disabled elements
        // Includes live UI pattern: button.artdeco-pagination__button--next[aria-label="Next"]
        const enabledPaginationButtons = Array.from(document.querySelectorAll(
            '[data-test-ts-pagination] a[rel="next"]:not([disabled]):not(.artdeco-button--disabled), ' +
            '[data-test-ts-pagination] a[data-test-pagination-next]:not([disabled]):not(.artdeco-button--disabled), ' +
            '[data-test-ts-pagination] a[data-test-mini-pagination-next]:not([disabled]):not(.artdeco-button--disabled), ' +
            '.profile-list-container__pagination a[rel="next"]:not([disabled]):not(.artdeco-button--disabled), ' +
            '.profile-list-container__pagination [data-test-pagination-next]:not([disabled]):not(.artdeco-button--disabled), ' +
            '.mini-pagination a[rel="next"]:not([disabled]):not(.artdeco-button--disabled), ' +
            '.mini-pagination [data-test-mini-pagination-next]:not([disabled]):not(.artdeco-button--disabled), ' +
            'button.artdeco-pagination__button--next:not([disabled]):not(.artdeco-button--disabled)'
        )).filter(isPaginationCandidate).sort((a, b) => getPaginationScore(b) - getPaginationScore(a));

        // CRITICAL: Before clicking artdeco header button, verify we're NOT on the last page.
        // On the last page, the header may show an enabled "Next" button that leads to 404.
        // Trust explicit numbered page links over the header button when in doubt.
        if (enabledPaginationButtons.length > 0) {
            const btn = enabledPaginationButtons[0];
            const btnClass = btn.className || '';
            const isArtdecoHeaderButton = btnClass.includes('artdeco-pagination__button--next');

            if (isArtdecoHeaderButton) {
                // Check for evidence of another page: look for numbered links higher than current
                const pageLinks = Array.from(document.querySelectorAll(
                    'nav a, nav button, nav li, [aria-current="page"], [role="listitem"]'
                ));
                const currentPageMatch = previousUrl.match(/[?&]start=(\d+)/);
                const currentStart = currentPageMatch ? parseInt(currentPageMatch[1], 10) : 0;
                const currentPageNum = Math.floor(currentStart / 25) + 1;

                // Find the highest page number visible in pagination
                let highestVisiblePage = currentPageNum;
                let hasForwardPageLink = false;
                let hasVisiblePageEvidence = false;
                let hasCurrentPageMarker = false;

                for (const link of pageLinks) {
                    const text = (link.textContent || '').replace(/\s+/g, ' ').trim();
                    const aria = (link.getAttribute('aria-label') || '').trim();
                    const ariaCurrent = (link.getAttribute('aria-current') || '').trim();
                    const pageTextMatch = text.match(/(?:^|\b)Page\s+(\d+)(?:\b|\s*\(current\))/i) ||
                                          text.match(/^(\d+)$/);
                    const pageAriaMatch = aria.match(/page\s+(\d+)/i);
                    const pageNum = pageTextMatch ? parseInt(pageTextMatch[1], 10) :
                                    pageAriaMatch ? parseInt(pageAriaMatch[1], 10) : 0;
                    if (pageNum > 0) {
                        hasVisiblePageEvidence = true;
                    }
                    if (pageNum > highestVisiblePage) {
                        highestVisiblePage = pageNum;
                    }
                    if (pageNum > currentPageNum) {
                        hasForwardPageLink = true;
                    }
                    if (
                        pageNum == currentPageNum &&
                        (text.toLowerCase().includes('(current)') || ariaCurrent.toLowerCase() == 'page')
                    ) {
                        hasCurrentPageMarker = true;
                    }
                }

                // Only infer last page on positive pagination evidence.
                if (
                    hasVisiblePageEvidence &&
                    hasCurrentPageMarker &&
                    currentPageNum >= highestVisiblePage &&
                    !hasForwardPageLink
                ) {
                    return {
                        clicked: false,
                        isLastPage: true,
                        method: 'last_page_inferred',
                        previousUrl: previousUrl,
                        error: null,
                        debug: {
                            currentPageNum,
                            highestVisiblePage,
                            hasForwardPageLink,
                            hasVisiblePageEvidence,
                            hasCurrentPageMarker,
                        }
                    };
                }
            }

            btn.scrollIntoView({ block: 'center' });
            btn.click();
            return {
                clicked: true,
                isLastPage: false,
                method: 'pagination_button',
                previousUrl: previousUrl
            };
        }

        // Strategy 3: Check for disabled next button (last page detection)
        // Only check for disabled buttons if NO enabled controls were found.
        // This handles the clean end-of-results case where there truly is no next page.
        // Includes live UI pattern: button.artdeco-pagination__button--next.artdeco-button--disabled
        const disabledSelectors = [
            '[data-test-ts-pagination] button[disabled][aria-label*="next" i]',
            '[data-test-ts-pagination] button[disabled][data-test-pagination-next]',
            '[data-test-ts-pagination] a[disabled][rel="next"]',
            '[data-test-ts-pagination] button.artdeco-button--disabled[aria-label*="next" i]',
            '[data-test-ts-pagination] button.artdeco-button--disabled[data-test-pagination-next]',
            '.profile-list-container__pagination button[disabled][aria-label*="next" i]',
            '.profile-list-container__pagination button[disabled][data-test-pagination-next]',
            '.profile-list-container__pagination a[disabled][rel="next"]',
            '.profile-list-container__pagination button.artdeco-button--disabled[aria-label*="next" i]',
            '.profile-list-container__pagination button.artdeco-button--disabled[data-test-pagination-next]',
            '.mini-pagination button[disabled][aria-label*="next" i]',
            '.mini-pagination button[disabled][data-test-mini-pagination-next]',
            '.mini-pagination a[disabled][rel="next"]',
            '.mini-pagination button.artdeco-button--disabled[aria-label*="next" i]',
            '.mini-pagination button.artdeco-button--disabled[data-test-mini-pagination-next]',
            'button.artdeco-pagination__button--next.artdeco-button--disabled',
            'button.artdeco-pagination__button--next[disabled]'
        ];
        for (const selector of disabledSelectors) {
            const disabledNext = document.querySelector(selector);
            if (disabledNext) {
                return {
                    clicked: false,
                    isLastPage: true,
                    method: 'last_page_detected',
                    previousUrl: previousUrl,
                    error: null  // Not an error - clean end of results
                };
            }
        }

        // Strategy 4: No enabled next button found - FAIL CLOSED
        // This could be due to DOM drift, selector mismatch, or transiently missing control.
        // Only a positively verified disabled button indicates last page (handled in Strategy 3).
        // Missing button is a failure condition, not a clean end-of-results.
        return {
            clicked: false,
            isLastPage: false,
            method: 'no_next_button',
            previousUrl: previousUrl,
            error: 'Next page button not found - possible DOM drift or selector mismatch'
        };
    })()
    """

    from browser_utils import safe_get_parsed, FailureCode, ActionRequired

    pagination_state_js = r"""
    (() => {
        const currentUrl = window.location.href;
        const currentPageMatch = currentUrl.match(/[?&]start=(\d+)/);
        const currentStart = currentPageMatch ? parseInt(currentPageMatch[1], 10) : 0;
        const currentPageNum = Math.floor(currentStart / 25) + 1;
        const pageLinks = Array.from(document.querySelectorAll(
            'nav a, nav button, nav li, [aria-current="page"], [role="listitem"]'
        ));
        let highestVisiblePage = currentPageNum;
        let hasForwardPageLink = false;
        let hasVisiblePageEvidence = false;
        let hasCurrentPageMarker = false;

        for (const link of pageLinks) {
            const text = (link.textContent || '').replace(/\s+/g, ' ').trim();
            const aria = (link.getAttribute('aria-label') || '').trim();
            const ariaCurrent = (link.getAttribute('aria-current') || '').trim();
            const pageTextMatch = text.match(/(?:^|\b)Page\s+(\d+)(?:\b|\s*\(current\))/i) ||
                                  text.match(/^(\d+)$/);
            const pageAriaMatch = aria.match(/page\s+(\d+)/i);
            const pageNum = pageTextMatch ? parseInt(pageTextMatch[1], 10) :
                            pageAriaMatch ? parseInt(pageAriaMatch[1], 10) : 0;
            if (pageNum > 0) {
                hasVisiblePageEvidence = true;
            }
            if (pageNum > highestVisiblePage) {
                highestVisiblePage = pageNum;
            }
            if (pageNum > currentPageNum) {
                hasForwardPageLink = true;
            }
            if (
                pageNum == currentPageNum &&
                (text.toLowerCase().includes('(current)') || ariaCurrent.toLowerCase() == 'page')
            ) {
                hasCurrentPageMarker = true;
            }
        }

        const disabledNext = !!document.querySelector(
            'button.artdeco-pagination__button--next[disabled], ' +
            'button.artdeco-pagination__button--next.artdeco-button--disabled, ' +
            '[data-test-ts-pagination] button[disabled][aria-label*="next" i], ' +
            '.profile-list-container__pagination button[disabled][aria-label*="next" i], ' +
            '.mini-pagination button[disabled][aria-label*="next" i]'
        );

        return {
            isLastPage: disabledNext || (
                hasVisiblePageEvidence &&
                hasCurrentPageMarker &&
                !hasForwardPageLink &&
                currentPageNum >= highestVisiblePage
            ),
            currentPageNum,
            highestVisiblePage,
            hasForwardPageLink,
            disabledNext,
            hasVisiblePageEvidence,
            hasCurrentPageMarker,
        };
    })()
    """

    result = run_browser_command(cdp_port, "eval", CLICK_NEXT_PAGE_JS)

    if result.get("error"):
        return _err_result(
            error=f"Browser command failed: {result['error']}",
            failure_code=FailureCode.TIMEOUT
            if result.get("timed_out")
            else FailureCode.AMBIGUOUS_STATE,
            action_required=ActionRequired.ambiguous_state(
                details=f"Pagination click failed: {result['error']}"
            ).to_dict()
            if not result.get("timed_out")
            else None,
            is_last_page=False,
            previous_url="",
            current_url="",
        )

    parsed = safe_get_parsed(result, default={})

    if parsed.get("isLastPage"):
        return _ok_result(
            is_last_page=True,
            previous_url=parsed.get("previousUrl", ""),
            current_url=parsed.get("previousUrl", ""),
            error=None,
            failure_code=None,
            action_required=None,
        )

    if not parsed.get("clicked"):
        pagination_state = safe_get_parsed(
            run_browser_command(cdp_port, "eval", pagination_state_js),
            default={},
        )
        if pagination_state.get("isLastPage"):
            return _ok_result(
                is_last_page=True,
                previous_url=parsed.get("previousUrl", ""),
                current_url=parsed.get("previousUrl", ""),
                error=None,
                failure_code=None,
                action_required=None,
            )

        error_msg = parsed.get("error", "Next page pagination control not found")
        return _err_result(
            error=error_msg,
            failure_code=FailureCode.ELEMENT_MISSING,
            action_required=ActionRequired.element_missing(
                selector="next page pagination control",
                page_url=parsed.get("previousUrl", ""),
            ).to_dict(),
            is_last_page=False,
            previous_url=parsed.get("previousUrl", ""),
            current_url=parsed.get("previousUrl", ""),
        )

    # Wait for navigation to complete with bounded polling
    # For page > 1, we expect the URL to contain the specific start offset
    expected_start_param = f"start={expected_start}" if expected_start else None
    current_url = ""
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        url_result = run_browser_command(
            cdp_port, "eval", "({ url: window.location.href })"
        )
        url_parsed = safe_get_parsed(url_result, default={})
        current_url = url_parsed.get("url", "")

        if not current_url:
            return _err_result(
                error="Failed to read current URL from browser during pagination",
                failure_code=FailureCode.BROWSER_UNAVAILABLE,
                action_required=ActionRequired.browser_unavailable(
                    cdp_port=cdp_port
                ).to_dict(),
                is_last_page=False,
                previous_url=parsed.get("previousUrl", ""),
                current_url="",
            )

        # If we have an expected start parameter, wait for it to appear
        if expected_start_param:
            if expected_start_param in current_url:
                break
        else:
            # No expected start - just check URL changed from previous
            if current_url != parsed.get("previousUrl", ""):
                break

        time.sleep(poll_interval)
    else:
        # Timeout reached - still return the current URL for validation to handle
        pass

    previous_url = parsed.get("previousUrl", "")

    if expected_start_param and current_url == previous_url:
        pagination_state = safe_get_parsed(
            run_browser_command(cdp_port, "eval", pagination_state_js),
            default={},
        )
        if pagination_state.get("isLastPage"):
            return _ok_result(
                is_last_page=True,
                previous_url=previous_url,
                current_url=current_url,
                error=None,
                failure_code=None,
                action_required=None,
            )

        return _err_result(
            error="Pagination click did not reach the expected next page",
            failure_code=FailureCode.AMBIGUOUS_STATE,
            action_required=ActionRequired.ambiguous_state(
                details=(
                    f"Pagination click did not change URL from {previous_url} "
                    f"while waiting for {expected_start_param}"
                )
            ).to_dict(),
            is_last_page=False,
            previous_url=previous_url,
            current_url=current_url,
        )

    return _ok_result(
        is_last_page=False,
        previous_url=previous_url,
        current_url=current_url,
        error=None,
        failure_code=None,
        action_required=None,
    )


def validate_pagination_result(
    pagination_result: dict[str, Any],
    expected_page: int,
    project_id: str,
) -> dict[str, Any]:
    """Validate that pagination landed on the expected page.

    Args:
        pagination_result: Result from click_next_page_pagination
        expected_page: The expected page number (1-indexed)
        project_id: The expected project ID

    Returns:
        Dict with:
            - valid: bool - whether validation passed
            - is_last_page: bool - True if this is the last page (clean stop)
            - error: str | None - error message if failed
    """
    # Handle clean end-of-results (last page) - this is NOT a failure
    if pagination_result.get("is_last_page"):
        return {
            "valid": True,  # Valid - just no more pages
            "is_last_page": True,
            "error": None,
        }

    if not pagination_result.get("success"):
        return {
            "valid": False,
            "is_last_page": False,
            "error": pagination_result.get("error", "Pagination failed"),
        }

    current_url = pagination_result.get("current_url", "")

    # Validate same project
    current_project_id = extract_project_id_from_url(current_url)
    if current_project_id != project_id:
        return {
            "valid": False,
            "is_last_page": False,
            "error": (
                f"Project ID mismatch after pagination: "
                f"expected {project_id}, got {current_project_id}"
            ),
        }

    # Validate we're on a search page
    if "discover/recruiterSearch" not in current_url:
        return {
            "valid": False,
            "is_last_page": False,
            "error": f"Not on search page after pagination: {current_url}",
        }

    # Validate expected start offset for the page
    expected_start = (expected_page - 1) * 25
    expected_start_param = f"start={expected_start}"

    if expected_start > 0 and expected_start_param not in current_url:
        # For page > 1, we expect the start parameter
        return {
            "valid": False,
            "is_last_page": False,
            "error": (
                f"Pagination landed on wrong page: expected {expected_start_param} "
                f"in URL, got: {current_url}"
            ),
        }

    return {"valid": True, "is_last_page": False, "error": None}


def get_page_number_from_url(url: str) -> int:
    """Extract page number from a LinkedIn Recruiter URL.

    LinkedIn uses ?start=N parameter where N = (page-1) * 25.
    Page 1 has no start parameter or start=0.

    Args:
        url: The URL to parse

    Returns:
        Page number (1-indexed), defaults to 1 if no start param
    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    start_param = params.get("start", ["0"])[0]
    try:
        start = int(start_param)
    except (ValueError, TypeError):
        start = 0

    # start=0 -> page 1, start=25 -> page 2, etc.
    return (start // 25) + 1


def get_current_page_from_browser(cdp_port: str, project_id: str) -> dict[str, Any]:
    """Get the actual current page number from browser state.

    Checks if browser is on a contextual search page for the project
    and extracts the current page number from the URL.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        project_id: The expected project ID

    Returns:
        Dict with:
            - success: bool - whether browser state was read successfully
            - current_page: int - detected page number (1 if unknown)
            - current_url: str - the current URL
            - is_contextual: bool - whether on valid contextual search page
            - same_project: bool - whether on same project
            - error: str | None - error message if browser state could not be read
            - failure_code: str | None - stable failure code if failed
            - action_required: dict | None - structured fallback if failed
    """
    from urllib.parse import urlparse

    from browser_utils import safe_get_parsed, FailureCode, ActionRequired

    result = run_browser_command(cdp_port, "eval", "({ url: window.location.href })")
    if result.get("error"):
        return _err_result(
            error=f"Failed to read current URL from browser: {result['error']}",
            failure_code=FailureCode.AMBIGUOUS_STATE,
            action_required=ActionRequired.ambiguous_state(
                details=f"Could not read current URL from browser: {result['error']}"
            ).to_dict(),
            current_page=1,
            current_url="",
            is_contextual=False,
            same_project=False,
        )

    parsed = safe_get_parsed(result, default={})
    current_url = parsed.get("url", "")
    if not isinstance(current_url, str) or not current_url:
        return _err_result(
            error="Failed to read current URL from browser",
            failure_code=FailureCode.AMBIGUOUS_STATE,
            action_required=ActionRequired.ambiguous_state(
                details="Could not read current URL from browser"
            ).to_dict(),
            current_page=1,
            current_url="",
            is_contextual=False,
            same_project=False,
        )

    parsed_url = urlparse(current_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        return _err_result(
            error=f"Browser returned malformed current URL: {current_url}",
            failure_code=FailureCode.AMBIGUOUS_STATE,
            action_required=ActionRequired.ambiguous_state(
                details=f"Browser returned malformed current URL: {current_url}"
            ).to_dict(),
            current_page=1,
            current_url=current_url,
            is_contextual=False,
            same_project=False,
        )

    is_contextual = is_contextual_recruiter_search_url(current_url, project_id)
    current_project_id = extract_project_id_from_url(current_url)
    same_project = current_project_id == project_id
    current_page = get_page_number_from_url(current_url) if is_contextual else 1

    return _ok_result(
        current_page=current_page,
        current_url=current_url,
        is_contextual=is_contextual,
        same_project=same_project,
        error=None,
        failure_code=None,
        action_required=None,
    )


def build_paginated_url(base_url: str, page: int, page_size: int = 25) -> str:
    """Build a paginated URL for the given page number.

    LinkedIn Recruiter uses ?start=N parameter where N = (page-1) * page_size.
    Preserves existing query parameters.

    This is now a FALLBACK method - prefer live UI pagination controls.

    Args:
        base_url: The base URL (may already have query params)
        page: Page number (1-indexed)
        page_size: Number of results per page (default: 25)

    Returns:
        URL with appropriate pagination parameter
    """
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    parsed = urlparse(base_url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    # Remove any existing start parameter
    params.pop("start", None)

    # Add start parameter for pages > 1
    if page > 1:
        start = (page - 1) * page_size
        params["start"] = [str(start)]

    # Rebuild query string
    query = urlencode(params, doseq=True)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            query,
            parsed.fragment,
        )
    )


def navigate_to_page(
    cdp_port: str,
    base_url: str,
    page: int,
    work_dir: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Navigate to a specific page using live UI pagination controls.

    For page > 1, uses sequential live UI pagination clicks to reach the
    target page, validating at each step. Falls back to synthesized URL
    only if UI pagination is not available.

    CRITICAL: Detects actual current page from browser state to handle
    resumed runs (--start-page N) and multi-page extraction correctly.
    Does NOT assume starting from page 1.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        base_url: The base URL for the project (fresh contextual URL)
        page: Page number to navigate to (1-indexed)
        work_dir: Optional working directory for incident reporting
        project_id: Optional project ID for validation

    Returns:
        Dict with navigation result:
            - success: bool - whether navigation succeeded
            - is_last_page: bool - True if reached end of results (clean stop)
            - url: str - the URL to extract from
            - state: str - page state
            - method: str - navigation method used
            - error: str | None - error message if failed
    """
    from recruiter_page_utils import ensure_page_ready

    if page == 1:
        ensure_result = ensure_page_ready(
            cdp_port=cdp_port,
            work_dir=work_dir,
            target_url=base_url,
            context=f"navigate_to_page_{page}",
        )
        return _copy_action_required_fields(
            _nav_result(
                success=ensure_result["ready"],
                url=base_url,
                state=ensure_result["state"],
                method="direct",
            ),
            ensure_result,
        )

    if project_id:
        browser_state = get_current_page_from_browser(cdp_port, project_id)
        if not browser_state.get("success", True):
            return _copy_action_required_fields(
                _nav_result(
                    success=False,
                    url=browser_state.get("current_url", ""),
                    state="browser_state_read_failed",
                    method="browser_state",
                    error=browser_state.get(
                        "error", "Failed to read current page from browser"
                    ),
                ),
                browser_state,
            )
        current_page = browser_state["current_page"]
        current_url = browser_state["current_url"]
        is_contextual = browser_state["is_contextual"]
        same_project = browser_state["same_project"]

        if current_page == page and is_contextual:
            ensure_result = ensure_page_ready(
                cdp_port=cdp_port,
                work_dir=work_dir,
                target_url=current_url,
                context=f"navigate_to_page_{page}_already_there",
            )
            return _copy_action_required_fields(
                _nav_result(
                    success=ensure_result["ready"],
                    url=current_url,
                    state=ensure_result["state"],
                    method="already_on_page",
                ),
                ensure_result,
            )

        if is_contextual and same_project and current_page < page:
            ensure_result = ensure_page_ready(
                cdp_port=cdp_port,
                work_dir=work_dir,
                target_url=current_url,
                context=f"navigate_to_page_{current_page}_resume_ready",
            )
            if not ensure_result["ready"]:
                return _copy_action_required_fields(
                    _nav_result(
                        success=False,
                        url=current_url,
                        state=f"page_{current_page}_not_ready",
                        method="ui_pagination",
                        error=f"Resumed page {current_page} not ready: {ensure_result['state']}",
                    ),
                    ensure_result,
                )
        else:
            current_page = 1
            current_url = base_url
            ensure_result = ensure_page_ready(
                cdp_port=cdp_port,
                work_dir=work_dir,
                target_url=base_url,
                context=f"navigate_to_page_{page}_realign",
            )
            if not ensure_result["ready"]:
                return _copy_action_required_fields(
                    _nav_result(
                        success=False,
                        url=base_url,
                        state=ensure_result["state"],
                        method="realign_failed",
                        error=f"Failed to realign to page 1: {ensure_result['state']}",
                    ),
                    ensure_result,
                )
    else:
        # No project_id for validation - start from page 1 (legacy behavior)
        current_page = 1
        current_url = base_url

    # Use sequential live UI pagination to reach target page
    # Starting from detected current_page, click next until we reach target
    while current_page < page:
        next_page = current_page + 1
        expected_start = (next_page - 1) * 25

        pagination_result = click_next_page_pagination(
            cdp_port, expected_start=expected_start
        )

        if pagination_result.get("is_last_page"):
            return _nav_result(
                success=True,
                url=pagination_result.get("current_url", current_url),
                state="last_page",
                method="ui_pagination",
                is_last_page=True,
            )

        if not pagination_result.get("success"):
            error_msg = pagination_result.get("error", "Unknown pagination error")

            if pagination_result.get("failure_code") or pagination_result.get(
                "action_required"
            ):
                return _copy_action_required_fields(
                    _nav_result(
                        success=False,
                        url=pagination_result.get("current_url", current_url),
                        state="pagination_failed",
                        method="ui_pagination",
                        error=error_msg,
                    ),
                    pagination_result,
                )

            if "DOM drift" in error_msg or "selector mismatch" in error_msg:
                return _nav_result(
                    success=False,
                    url=pagination_result.get("current_url", current_url),
                    state="pagination_failed",
                    method="ui_pagination",
                    error=error_msg,
                )

            print(
                f"  UI pagination failed at page {next_page}: {error_msg}. "
                f"Falling back to synthesized URL.",
                file=sys.stderr,
            )

            paginated_url = build_paginated_url(base_url, page)

            ensure_result = ensure_page_ready(
                cdp_port=cdp_port,
                work_dir=work_dir,
                target_url=paginated_url,
                context=f"navigate_to_page_{page}_fallback",
            )

            return _copy_action_required_fields(
                _nav_result(
                    success=ensure_result["ready"],
                    url=paginated_url,
                    state=ensure_result["state"],
                    method="synthesized_fallback",
                ),
                ensure_result,
            )

        if project_id:
            validation = validate_pagination_result(
                pagination_result, next_page, project_id
            )
            if not validation["valid"]:
                return _nav_result(
                    success=False,
                    url=pagination_result.get("current_url", ""),
                    state="pagination_validation_failed",
                    method="ui_pagination",
                    error=validation["error"],
                )

        # Successfully advanced to next_page
        current_page = next_page
        current_url = pagination_result.get("current_url", current_url)

        # After each successful step, ensure the page is ready before next click
        # This prevents race conditions during sequential pagination
        if current_page < page:
            ensure_result = ensure_page_ready(
                cdp_port=cdp_port,
                work_dir=work_dir,
                target_url=current_url,
                context=f"navigate_to_page_{current_page}_ready",
            )
            if not ensure_result["ready"]:
                return _copy_action_required_fields(
                    _nav_result(
                        success=False,
                        url=current_url,
                        state=f"page_{current_page}_not_ready",
                        method="ui_pagination",
                        error=f"Page {current_page} not ready: {ensure_result['state']}",
                    ),
                    ensure_result,
                )

    ensure_result = ensure_page_ready(
        cdp_port=cdp_port,
        work_dir=work_dir,
        target_url=current_url,
        context=f"navigate_to_page_{page}_ui",
    )

    return _copy_action_required_fields(
        _nav_result(
            success=ensure_result["ready"],
            url=current_url,
            state=ensure_result["state"],
            method="ui_pagination",
        ),
        ensure_result,
    )


def extract_candidates_from_page(
    cdp_port: str,
    target_url: str,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """Extract candidates from the current page.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        target_url: LinkedIn Recruiter URL to extract from
        work_dir: Optional working directory for incident reporting

    Returns:
        Dict with extraction results
    """
    # Import here to avoid circular imports
    from extract_candidates import extract_candidates

    return extract_candidates(cdp_port, work_dir=work_dir, target_url=target_url)


def process_candidates(
    candidates: list[dict],
    workbook_path: Path,
    existing_urls: set[str],
    dry_run: bool = False,
) -> dict[str, int] | dict[str, Any]:
    """Process extracted candidates and update workbook.

    Uses upsert semantics: new candidates are inserted, existing candidates
    are updated in place. This ensures reruns refresh data without creating
    duplicates.

    Args:
        candidates: List of candidate dicts from extraction
        workbook_path: Path to workbook
        existing_urls: Set of already-extracted profile URLs (used for dry-run)
        dry_run: If True, don't actually write to workbook

    Returns:
        Dict with counts: total, new, updated, skipped
        Or dict with error info on workbook failure: {"error": True, "message": str}
    """
    stats = {"total": 0, "new": 0, "updated": 0, "skipped": 0}

    for candidate in candidates:
        stats["total"] += 1
        # Support both new schema (profile_url) and legacy schema (url) for backward compatibility
        profile_url = candidate.get("profile_url") or candidate.get("url", "")

        if dry_run:
            # In dry-run mode, track as new if not seen, skipped if seen
            if profile_url and profile_url in existing_urls:
                stats["skipped"] += 1
            else:
                stats["new"] += 1
                if profile_url:
                    existing_urls.add(profile_url)
            continue

        # Prepare row data
        row_data = {
            "name": candidate.get("name", ""),
            "title": candidate.get("title", ""),
            "company": candidate.get("company", ""),
            "profile_url": profile_url,
            "headline": candidate.get("headline", ""),
            "location": candidate.get("location", ""),
            "status": "Extracted",
            "next_action": "filter",
        }

        # Upsert to workbook - updates existing, inserts new
        # Workbook failures are fatal - return error for stable handling
        try:
            result = upsert(workbook_path, row_data, key_column="profile_url")
        except (PermissionError, OSError, IOError, BadZipFile) as e:
            return {"error": True, "message": f"Workbook write failed: {e}"}
        if result["action"] == "updated":
            stats["updated"] += 1
        else:
            stats["new"] += 1
        # Track URL for session-level deduplication
        if profile_url:
            existing_urls.add(profile_url)

    return stats


def run_preflight(
    config: dict[str, str],
    args: argparse.Namespace,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Run preflight checks before extraction.

    Validates configuration, workbook, and browser state to catch
    issues early before attempting fresh context resolution.

    Args:
        config: Parsed configuration dictionary
        args: Command line arguments
        config_path: Optional path to config.sh for workbook resolution

    Returns:
        Dict with:
            - success: bool - whether all preflight checks passed
            - exit_code: int | None - exit code if failed (1 for config/browser, 2 for workbook)
            - message: str - error message if failed
            - workbook_path: Path | None - resolved workbook path
            - existing_urls: set[str] - loaded existing URLs (empty if dry-run or new workbook)
            - project_id: str | None - extracted project ID
            - cdp_port: str | None - resolved CDP port
            - work_dir: str | None - working directory for incident reporting
    """
    from recruiter_page_utils import PageStateProbe
    from browser_utils import ActionRequired, FailureCode

    result: dict[str, Any] = {
        "success": False,
        "exit_code": None,
        "message": "",
        "workbook_path": None,
        "existing_urls": set(),
        "project_id": None,
        "cdp_port": None,
        "work_dir": None,
        "failure_code": None,
        "action_required": None,
    }

    # Verify RECRUITER_PROJECT_URL is set
    configured_url = config.get("RECRUITER_PROJECT_URL")
    if not configured_url:
        result["message"] = "RECRUITER_PROJECT_URL not set in config"
        result["exit_code"] = 1
        return result

    # Extract project ID from URL
    project_id = extract_project_id_from_url(configured_url)
    if not project_id:
        result["message"] = f"Could not extract project ID from URL: {configured_url}"
        result["exit_code"] = 1
        return result
    result["project_id"] = project_id

    # Config sanity: only compare PROJECT_ID when it looks like a Recruiter
    # project ID. In live configs PROJECT_ID is often a workbook/project slug.
    config_project_id = config.get("PROJECT_ID")
    if (
        config_project_id
        and config_project_id.isdigit()
        and config_project_id != project_id
    ):
        result["message"] = (
            f"Config project ID mismatch: PROJECT_ID={config_project_id} "
            f"but URL contains project {project_id}"
        )
        result["exit_code"] = 1
        return result

    manager = RuntimeManager()

    # Resolve CDP port
    cdp_port = args.cdp_port
    if not cdp_port:
        cdp_port = config.get("CDP_PORT")
        if not cdp_port:
            profile = manager._resolve_profile()
            cdp_port = profile.get("CDP_PORT", "9234")
    result["cdp_port"] = cdp_port

    # Get work_dir for incident reporting
    work_dir = str(manager.work_dir)
    result["work_dir"] = work_dir

    # Resolve workbook path early (pass config_path for new layout support)
    try:
        workbook_path = resolve_workbook_path(config, args.workbook, config_path)
    except ValueError as e:
        result["message"] = str(e)
        result["exit_code"] = 1
        return result
    result["workbook_path"] = workbook_path

    # Workbook preflight (skip for dry-run)
    if not args.dry_run:
        # Ensure workbook exists
        if not ensure_workbook(workbook_path):
            result["message"] = f"Could not create workbook: {workbook_path}"
            result["exit_code"] = 2
            return result

        # Load existing URLs early to catch corrupt/missing-sheet/read errors
        if workbook_path.exists():
            try:
                existing_urls = get_existing_keys(
                    workbook_path, key_column="profile_url"
                )
                result["existing_urls"] = existing_urls
                print(
                    f"Preflight: loaded {len(existing_urls)} existing candidates from workbook"
                )
            except (BadZipFile, KeyError, OSError, PermissionError) as e:
                result["message"] = f"Workbook read failed: {e}"
                result["exit_code"] = 2
                return result

    # Browser/CDP preflight using PageStateProbe
    probe = PageStateProbe(cdp_port)
    state_result = probe.classify_state()
    state = state_result.get("state", "unknown")

    # Fail on obviously bad browser states
    failing_states = {
        "bad_page",
        "dialog_blocked",
        "logged_out_or_wrong_product",
        "blocked_or_captcha",
    }
    if state in failing_states:
        details = state_result.get("details", {})
        current_url = details.get("url") or details.get("current_url")
        dialog_info = state_result.get("dialog_info") or details.get("dialog") or {}
        if state == "dialog_blocked":
            result["failure_code"] = FailureCode.DIALOG_BLOCKED
            result["action_required"] = ActionRequired.dialog_blocked(
                dialog_type=dialog_info.get("dialog_type"),
                message=dialog_info.get("message"),
            ).to_dict()
        elif state == "logged_out_or_wrong_product":
            result["failure_code"] = FailureCode.AUTH_REQUIRED
            result["action_required"] = ActionRequired.auth_required(
                current_url=current_url
            ).to_dict()
        elif state == "blocked_or_captcha":
            result["failure_code"] = FailureCode.BLOCKED_OR_CAPTCHA
            result["action_required"] = ActionRequired.blocked_or_captcha(
                current_url=current_url
            ).to_dict()
        else:
            result["failure_code"] = FailureCode.WRONG_PAGE
            result["action_required"] = ActionRequired.wrong_page(
                actual_url=current_url
            ).to_dict()
        result["message"] = f"Browser preflight failed: page state is '{state}'"
        result["exit_code"] = 1
        return result

    # Fail on unknown state with browser/CDP error
    if state == "unknown":
        details = state_result.get("details", {})
        error_text = details.get("error", "Unknown browser/CDP error")
        result["failure_code"] = details.get(
            "failure_code", FailureCode.AMBIGUOUS_STATE
        )
        result["action_required"] = ActionRequired.ambiguous_state(
            details=error_text
        ).to_dict()
        result["message"] = f"Browser preflight failed: {error_text}"
        result["exit_code"] = 1
        return result

    # Note: Search-not-configured detection happens later during fresh search
    # context resolution so we can distinguish it from ordinary preflight.

    result["success"] = True
    return result


def run_extraction(args: argparse.Namespace) -> dict[str, Any]:
    """Main extraction workflow.

    Args:
        args: Parsed command line arguments

    Returns:
        Dict with extraction results and statistics
    """
    result = {
        "success": False,
        "pages_processed": 0,
        "candidates_total": 0,
        "candidates_new": 0,
        "candidates_updated": 0,
        "candidates_skipped": 0,
        "message": "",
    }

    # Parse config file
    config = parse_config_file(args.config)
    if not config:
        result["message"] = f"Could not parse config file: {args.config}"
        return result

    # Resolve config_path for workbook location
    config_path = Path(args.config).expanduser().resolve() if args.config else None

    # Run preflight checks before fresh context resolution
    preflight = run_preflight(config, args, config_path)
    if not preflight["success"]:
        result["message"] = preflight["message"]
        result["exit_code"] = preflight["exit_code"]
        _copy_action_required_fields(result, preflight)
        # Update project state for preflight failure
        try:
            from project_state import update_project_state

            project_dir = config_path.parent if config_path else Path(".")
            update_project_state(
                project_dir=project_dir,
                current_phase="extract",
                status="failed",
                last_result_summary="Preflight checks failed",
                last_error=preflight.get("message", "Unknown preflight error"),
            )
        except Exception:
            pass
        return result

    # Extract preflight results
    project_id = preflight["project_id"]
    cdp_port = preflight["cdp_port"]
    work_dir = preflight["work_dir"]
    workbook_path = preflight["workbook_path"]
    existing_urls = preflight["existing_urls"]
    configured_url = config.get("RECRUITER_PROJECT_URL", "")

    # Determine start page: --resume takes precedence over --start-page
    state_path_result = get_extraction_state_path(
        Path(work_dir), project_id, workbook_path
    )
    if not state_path_result["success"]:
        result["message"] = state_path_result["error"]
        result["exit_code"] = 2
        return result
    state_path = state_path_result["path"]

    # Check if resume is explicitly requested (handle Mock objects in tests)
    resume_requested = getattr(args, "resume", False)
    # Check if --project was used (vs --config) - auto-resume only applies to --project
    project_ref_used = getattr(args, "_project_ref_used", False)
    if isinstance(resume_requested, bool) and resume_requested:
        # Load persisted state and validate it
        persisted_state = load_extraction_state(state_path)
        is_resumable, resume_page, reason = is_resumable_state(persisted_state)

        if not is_resumable:
            result["message"] = f"Cannot resume: {reason}"
            result["exit_code"] = 1
            return result

        # Validate identity: persisted state must match current run context
        # This ensures --resume only applies to the exact same extraction/search context
        persisted_project_id = persisted_state.get("project_id")
        persisted_workbook_path = persisted_state.get("workbook_path")
        persisted_config_path = persisted_state.get("config_path")

        if persisted_project_id != project_id:
            result["message"] = (
                f"Cannot resume: state file belongs to different project "
                f"(expected: {project_id}, found: {persisted_project_id})"
            )
            result["exit_code"] = 1
            return result
        if persisted_workbook_path != str(workbook_path):
            result["message"] = (
                f"Cannot resume: state file belongs to different workbook "
                f"(expected: {workbook_path}, found: {persisted_workbook_path})"
            )
            result["exit_code"] = 1
            return result
        if persisted_config_path != str(args.config):
            result["message"] = (
                f"Cannot resume: state file belongs to different config "
                f"(expected: {args.config}, found: {persisted_config_path})"
            )
            result["exit_code"] = 1
            return result

        # Validate dry-run mode matches - fail closed on mismatch
        persisted_dry_run = persisted_state.get("dry_run", False)
        if persisted_dry_run != args.dry_run:
            mode_persisted = "dry-run" if persisted_dry_run else "real"
            mode_current = "dry-run" if args.dry_run else "real"
            result["message"] = (
                f"Cannot resume: state file was created during {mode_persisted} run, "
                f"but current run is {mode_current}. "
                f"Dry-run state cannot be used for real extraction and vice versa."
            )
            result["exit_code"] = 1
            return result

        # Validate fresh URL (actual extraction identity) matches persisted context
        # This prevents resuming when the actual search context has changed
        persisted_fresh_url = persisted_state.get("fresh_url")
        if persisted_fresh_url:
            # Extract project ID from persisted fresh URL
            persisted_fresh_project_id = extract_project_id_from_url(
                persisted_fresh_url
            )
            # The fresh URL should be for the same project
            if persisted_fresh_project_id != project_id:
                result["message"] = (
                    f"Cannot resume: state file belongs to different project "
                    f"(fresh URL project mismatch: expected {project_id}, "
                    f"found {persisted_fresh_project_id})"
                )
                result["exit_code"] = 1
                return result

        # Use persisted page instead of args.start_page
        current_page = resume_page
        print(f"Resuming from persisted state: page {current_page}")
    else:
        # Auto-resume logic: only when using --project (not --config),
        # and no explicit --resume, and no explicit --start-page provided
        # Note: argparse default start_page=1 means we must check if user explicitly provided it
        # We detect explicit --start-page by checking if args has the attribute set via parse_args
        explicit_start_page_provided = (
            hasattr(args, "_explicit_start_page") and args._explicit_start_page
        )
        if project_ref_used and not explicit_start_page_provided:
            # Check for resumable state
            persisted_state = load_extraction_state(state_path)
            is_resumable, resume_page, _ = is_resumable_state(persisted_state)

            if is_resumable and persisted_state:
                # Validate identity matches before auto-resuming
                persisted_project_id = persisted_state.get("project_id")
                persisted_workbook_path = persisted_state.get("workbook_path")
                persisted_config_path = persisted_state.get("config_path")
                persisted_dry_run = persisted_state.get("dry_run", False)

                identity_matches = (
                    persisted_project_id == project_id
                    and persisted_workbook_path == str(workbook_path)
                    and persisted_config_path == str(args.config)
                    and persisted_dry_run == args.dry_run
                )

                if identity_matches:
                    current_page = resume_page
                    print(f"Auto-resuming from persisted state: page {current_page}")
                else:
                    current_page = args.start_page
            else:
                current_page = args.start_page
        else:
            current_page = args.start_page

    # Resolve fresh search context for this run
    # This handles stale/bare configured URLs by navigating to project overview
    # and using resolve_search_url() to get a fresh contextual URL
    print(f"Resolving fresh search context for project {project_id}...")
    context_result = resolve_fresh_search_context(
        cdp_port=cdp_port,
        configured_url=configured_url,
        work_dir=work_dir,
    )

    if not context_result["success"]:
        result["message"] = context_result["error"]
        result["exit_code"] = 1
        _copy_action_required_fields(result, context_result)
        # Update project state for context resolution failure
        try:
            from project_state import update_project_state

            project_dir = config_path.parent if config_path else Path(work_dir)
            update_project_state(
                project_dir=project_dir,
                current_phase="extract",
                status="failed",
                action_required=context_result.get("action_required"),
                last_result_summary="Failed to resolve fresh search context",
                last_error=context_result.get("error"),
            )
        except Exception:
            pass
        return result

    target_url = context_result["fresh_url"]
    print(f"Fresh search context resolved: {target_url}")

    pages_to_process = args.max_pages if args.max_pages > 0 else float("inf")
    pages_processed_count = 0
    total_stats = {"total": 0, "new": 0, "updated": 0, "skipped": 0}
    max_pages_reached = False

    print(f"Starting extraction from page {current_page}")
    print(f"Target URL: {target_url}")
    print(f"Workbook: {workbook_path}")
    if args.dry_run:
        print("DRY RUN: No changes will be written to workbook")
    print()

    def _persist_state(
        status: str,
        last_completed_page: int | None,
        next_start_page: int | None,
        error: str | None = None,
    ) -> bool:
        """Persist extraction state with common fields bound."""
        return save_extraction_state(
            state_path=state_path,
            project_id=project_id,
            workbook_path=workbook_path,
            config_path=args.config,
            status=status,
            last_completed_page=last_completed_page,
            next_start_page=next_start_page,
            error=error,
            fresh_url=target_url,
            dry_run=args.dry_run,
        )

    try:
        while pages_processed_count < pages_to_process:
            print(f"Processing page {current_page}...")

            # Determine the URL to extract from
            # Page 1: use the fresh contextual URL
            # Page > 1: use live UI pagination to get the actual resulting URL
            page_url = target_url
            if current_page > 1:
                nav_result = navigate_to_page(
                    cdp_port=cdp_port,
                    base_url=target_url,
                    page=current_page,
                    work_dir=work_dir,
                    project_id=project_id,
                )
                # Handle clean end-of-results (last page) - this is NOT a failure
                if nav_result.get("is_last_page"):
                    print(
                        f"  Reached last page after page {current_page - 1}. Extraction complete."
                    )
                    break

                if not nav_result["success"]:
                    error_msg = nav_result.get("error", nav_result["state"])
                    print(f"  Failed to navigate to page {current_page}: {error_msg}")
                    state_saved = _persist_state(
                        status="failed",
                        last_completed_page=current_page - 1
                        if current_page > 1
                        else None,
                        next_start_page=current_page,
                        error=f"Navigation failed: {error_msg}",
                    )
                    if not state_saved:
                        result["message"] = (
                            f"Navigation failed on page {current_page}: {error_msg}; "
                            f"additionally, failed to persist state to {state_path}"
                        )
                        result["exit_code"] = 2
                        _copy_action_required_fields(result, nav_result)
                        return result
                    result["message"] = (
                        f"Navigation failed on page {current_page}: {error_msg}"
                    )
                    result["exit_code"] = 1
                    _copy_action_required_fields(result, nav_result)
                    return result

                # Use the actual URL from pagination (not a synthesized one)
                page_url = nav_result.get("url", target_url)
                print(
                    f"  Navigated via {nav_result.get('method', 'unknown')}: {page_url}"
                )

            # Extract candidates from current page
            extraction_result = extract_candidates_from_page(
                cdp_port=cdp_port,
                target_url=page_url,
                work_dir=work_dir,
            )

            if not extraction_result["success"]:
                exit_code = extraction_result.get("exit_code", 1)
                if exit_code == 2:  # No results - this is expected on final page
                    print(f"No results on page {current_page}. Extraction complete.")
                    break
                else:
                    state_saved = _persist_state(
                        status="failed",
                        last_completed_page=current_page - 1
                        if current_page > 1
                        else None,
                        next_start_page=current_page,
                        error=f"Extraction failed: {extraction_result.get('message', 'Unknown error')}",
                    )
                    if not state_saved:
                        result["message"] = (
                            f"Extraction failed on page {current_page}: {extraction_result['message']}; "
                            f"additionally, failed to persist state to {state_path}"
                        )
                        result["exit_code"] = 2
                        return result
                    result["message"] = (
                        f"Extraction failed on page {current_page}: {extraction_result['message']}"
                    )
                    result["exit_code"] = exit_code
                    return result

            candidates = extraction_result.get("candidates", [])
            if not candidates:
                print(
                    f"No candidates found on page {current_page}. Extraction complete."
                )
                break

            print(f"  Extracted {len(candidates)} candidates")

            # Process candidates (upsert to workbook)
            page_stats = process_candidates(
                candidates=candidates,
                workbook_path=workbook_path,
                existing_urls=existing_urls,
                dry_run=args.dry_run,
            )

            if page_stats.get("error"):
                state_saved = _persist_state(
                    status="failed",
                    last_completed_page=current_page - 1 if current_page > 1 else None,
                    next_start_page=current_page,
                    error=f"Workbook write failed: {page_stats['message']}",
                )
                if not state_saved:
                    result["message"] = (
                        f"{page_stats['message']}; additionally, failed to persist state to {state_path}"
                    )
                    result["exit_code"] = 2
                    return result
                result["message"] = page_stats["message"]
                result["exit_code"] = 2
                return result

            print(
                f"  New: {page_stats['new']}, Updated: {page_stats['updated']}, Skipped: {page_stats['skipped']}"
            )

            # Accumulate stats
            for key in total_stats:
                total_stats[key] += page_stats[key]

            result["pages_processed"] += 1

            # Move to next page
            current_page += 1
            pages_processed_count += 1

            state_saved = _persist_state(
                status="running",
                last_completed_page=current_page - 1,
                next_start_page=current_page,
            )
            if not state_saved:
                result["message"] = f"Failed to persist running state to {state_path}"
                result["exit_code"] = 2
                return result

            if pages_processed_count < pages_to_process:
                time.sleep(1)
            else:
                max_pages_reached = True

    except KeyboardInterrupt:
        print(f"\n  Interrupted during page {current_page}. Persisting state...")
        state_saved = _persist_state(
            status="running",
            last_completed_page=current_page - 1 if current_page > 1 else None,
            next_start_page=current_page,
        )
        if not state_saved:
            print(
                f"  Warning: failed to persist state to {state_path}",
                file=sys.stderr,
            )
        else:
            print(f"  State persisted. Resume with: --resume")
        raise

    # Determine final status:
    # - Resume state: remains "running" when max-pages stops before exhaustion
    #   (so extraction can be resumed to process remaining pages)
    # - Project state: reflects "completed" for bounded success (clean outcome)
    bounded_extraction_complete = (
        args.max_pages > 0 and pages_processed_count >= args.max_pages
    )
    reached_end_of_results = not max_pages_reached

    if bounded_extraction_complete:
        # Resume state stays running/resumable; project state shows clean completion
        resume_final_status = "running"
        resume_next_start_page = current_page
        project_final_status = "completed"
        completion_message = f"Extraction complete: {result['pages_processed']} pages processed (bounded extraction finished)"
    elif reached_end_of_results:
        # True completion - no more results available
        resume_final_status = "completed"
        resume_next_start_page = None
        project_final_status = "completed"
        completion_message = f"Extraction complete: {result['pages_processed']} pages (reached end of results)"
    else:
        # Partial extraction (should not happen in normal flow)
        resume_final_status = "running"
        resume_next_start_page = current_page
        project_final_status = "running"
        completion_message = (
            f"Partial extraction: {result['pages_processed']} pages processed"
        )

    # Persist resume state (for --resume functionality)
    state_saved = _persist_state(
        status=resume_final_status,
        last_completed_page=current_page - 1 if current_page > 1 else None,
        next_start_page=resume_next_start_page,
    )
    if not state_saved:
        result["message"] = f"Failed to persist completed state to {state_path}"
        result["exit_code"] = 2
        return result

    # Build result
    result["success"] = True
    result["candidates_total"] = total_stats["total"]
    result["candidates_new"] = total_stats["new"]
    result["candidates_updated"] = total_stats["updated"]
    result["candidates_skipped"] = total_stats["skipped"]
    result["message"] = (
        f"{completion_message}, "
        f"{total_stats['new']} new, {total_stats['updated']} updated, "
        f"{total_stats['skipped']} skipped"
    )

    # Update project state (user-facing status)
    try:
        from project_state import update_project_state

        project_dir = config_path.parent if config_path else Path(work_dir)
        update_project_state(
            project_dir=project_dir,
            current_phase="extract",
            status=project_final_status,
            action_required=False,
            last_result_summary=result["message"],
            last_error=False,
        )
    except Exception:
        # Project state update is best-effort; don't fail extraction
        pass

    return result


def main() -> int:
    """Main entry point."""
    # Check if --start-page was explicitly provided before parsing
    raw_args = sys.argv[1:]
    explicit_start_page = any(
        arg == "--start-page" or arg.startswith("--start-page=") for arg in raw_args
    )

    args = parse_args()
    args._explicit_start_page = explicit_start_page

    # Resolve project reference if --project was provided
    if args.project:
        resolution = resolve_project_ref(args.project)
        if not resolution["success"]:
            print(f"Error: {resolution['error']}", file=sys.stderr)
            return 1
        # Set the resolved config path
        args.config = str(resolution["config_path"])
        # If workbook not explicitly provided, use resolved workbook path
        if not args.workbook and resolution.get("workbook_path"):
            args.workbook = str(resolution["workbook_path"])
        # Mark that --project was used (for auto-resume logic)
        args._project_ref_used = True
    else:
        args._project_ref_used = False

    try:
        result = run_extraction(args)

        # Print results
        print()
        print("=" * 60)
        if result["success"]:
            print("EXTRACTION COMPLETE")
        else:
            print("EXTRACTION FAILED")
        print("=" * 60)
        print(result["message"])
        print()
        print(f"Pages processed: {result['pages_processed']}")
        print(f"Total candidates: {result['candidates_total']}")
        print(f"New candidates: {result['candidates_new']}")
        print(f"Updated candidates: {result['candidates_updated']}")
        print(f"Skipped (duplicates): {result['candidates_skipped']}")

        # Return appropriate exit code
        if result["success"]:
            return 0
        else:
            return result.get("exit_code", 1)

    except KeyboardInterrupt:
        project_ref = args.project or "<PROJECT_ID>"
        loop_command = (
            f"python3 {shlex.quote(str(SCRIPT_DIR / 'run_reachout_loop.py'))} "
            f"--project {shlex.quote(project_ref)}"
        )
        print("\n\nExtraction interrupted by user", file=sys.stderr)
        print(
            f"Rerun the loop to resume: {loop_command}",
            file=sys.stderr,
        )
        return 130
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
