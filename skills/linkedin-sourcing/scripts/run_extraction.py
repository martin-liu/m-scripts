#!/usr/bin/env python3
"""Canonical operator-facing extraction macro for LinkedIn Recruiter.

Runs from $WORK_DIR/runtime/current and performs page-by-page extraction
into the workbook with deduplication and resumability.

Usage:
    # From runtime/current (config-driven)
    python3 run_extraction.py --config $WORK_DIR/projects/{PROJECT_ID}/config.sh

    # With explicit workbook path
    python3 run_extraction.py --config config.sh --workbook /path/to/workbook.xlsx

    # Dry run (extract without writing to workbook)
    python3 run_extraction.py --config config.sh --dry-run

    # Resume from specific page
    python3 run_extraction.py --config config.sh --start-page 3

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

import argparse
import hashlib
import json
import os
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
from browser_utils import run_browser_command
from project_ref_utils import resolve_project_ref


def parse_config_file(config_path: str) -> dict[str, str]:
    """Parse a shell config file and extract key-value pairs.

    Handles simple VAR="value" or VAR='value' syntax.
    """
    config: dict[str, str] = {}
    path = Path(config_path)
    if not path.exists():
        return config

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            config[key] = value

    return config


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract candidates from LinkedIn Recruiter to workbook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Config-driven extraction
    python3 run_extraction.py --config $WORK_DIR/projects/123/config.sh

    # Project reference (local PROJECT_ID, Recruiter URL, or numeric ID)
    python3 run_extraction.py --project my_project
    python3 run_extraction.py --project https://linkedin.com/talent/hire/12345/...
    python3 run_extraction.py --project 12345

    # With explicit workbook
    python3 run_extraction.py --config config.sh --workbook /path/to/123.xlsx

    # Dry run (extract without writing)
    python3 run_extraction.py --config config.sh --dry-run

    # Resume from page 3
    python3 run_extraction.py --config config.sh --start-page 3

    # Resume from persisted state
    python3 run_extraction.py --config config.sh --resume
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
        help="Path to workbook (default: $WORK_DIR/projects/{PROJECT_ID}.xlsx)",
    )
    parser.add_argument(
        "--cdp-port",
        help="Chrome DevTools Protocol port (default: from profile or 9230)",
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
    import re
    from urllib.parse import urlparse

    # Validate URL is from LinkedIn domain
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not (hostname == "linkedin.com" or hostname.endswith(".linkedin.com")):
        return None

    # Match /talent/hire/{numeric_id} followed by /, ?, #, or end of string
    # This accepts URLs with or without trailing slash, and with query params or hash
    match = re.search(r"/talent/hire/(\d+)(?:/|$|\?|#)", url)
    return match.group(1) if match else None


def build_project_overview_url(project_id: str) -> str:
    """Build a stable project overview URL from project ID.

    Args:
        project_id: The project ID

    Returns:
        Project overview URL
    """
    return f"https://www.linkedin.com/talent/hire/{project_id}/overview"


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
    if "discover/recruiterSearch" not in url:
        return False

    # Must contain the project ID in the path
    if f"/talent/hire/{project_id}/" not in url:
        return False

    # Must have at least one contextual search parameter
    context_params = [
        "searchContextId=",
        "searchHistoryId=",
        "searchRequestId=",
        "projectId=",
    ]
    return any(param in url for param in context_params)


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
    from browser_utils import run_browser_command

    # Get current URL
    result = run_browser_command(cdp_port, "eval", "({ url: window.location.href })")
    current_url = result.get("parsed", {}).get("url", "")

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

    # Require concrete evidence of search results content, not just generic ready
    # classify_state() can return ready via generic recruiter fallback even when
    # no search results are present (e.g., on overview pages)
    if not details.get("hasSearchResultsContent"):
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
    """
    # Import here to avoid circular imports
    from ensure_recruiter_project import (
        resolve_search_url,
        validate_project_context,
        is_contextual_search_url,
    )
    from recruiter_page_utils import RecoveryHelper, ensure_page_ready

    # Extract project ID from configured URL
    project_id = extract_project_id_from_url(configured_url)
    if not project_id:
        return {
            "success": False,
            "fresh_url": None,
            "error": f"Could not extract project ID from URL: {configured_url}",
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
        return {
            "success": False,
            "fresh_url": None,
            "error": (
                f"Failed to navigate to stable project overview page: {ensure_result.get('state', 'unknown state')}. "
                f"Identity check: {ensure_result.get('identity_check', {})}. "
                "Cannot resolve fresh search context without confirmed project context."
            ),
        }

    # Validate we're on the correct project
    context_validation = validate_project_context(
        cdp_port=cdp_port,
        project_name="",  # We don't have the project name here, skip name validation
        expected_project_id=project_id,
    )

    if not context_validation["valid"]:
        return {
            "success": False,
            "fresh_url": None,
            "error": f"Project context validation failed: {context_validation.get('error', 'Unknown error')}",
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
            check_url = result.get("parsed", {}).get("url", "")

            if is_contextual_search_url(check_url):
                return {
                    "success": True,
                    "fresh_url": check_url,
                    "error": None,
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
        }

    return {
        "success": True,
        "fresh_url": fresh_url,
        "error": None,
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
    """
    # JavaScript to click pagination and return URL change info
    # CRITICAL: Restrict matching to actual Recruiter pagination controls.
    # LinkedIn pages can contain unrelated carousel/buttons with text like "Next"
    # that do not paginate the search results. Prefer result-list pagination
    # controls, then fall back to mini-pagination in the header.
    CLICK_NEXT_PAGE_JS = """
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
            if (!root) return -1;

            const rootClass = root.className || '';
            const elClass = el.className || '';
            let score = 0;

            if (root.matches('.profile-list-container__pagination, .pagination')) score += 100;
            if (root.matches('.mini-pagination')) score += 50;
            if (root.hasAttribute('data-test-ts-pagination')) score += 25;
            if (el.hasAttribute('data-test-pagination-next') || elClass.includes('pagination__quick-link--next')) score += 20;
            if (el.hasAttribute('data-test-mini-pagination-next') || elClass.includes('mini-pagination__quick-link')) score += 10;
            if ((el.getAttribute('rel') || '').toLowerCase() === 'next') score += 5;
            if (rootClass.includes('artdeco-carousel')) score -= 200;

            return score;
        }

        function isPaginationCandidate(el) {
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
        const enabledPaginationButtons = Array.from(document.querySelectorAll(
            '[data-test-ts-pagination] a[rel="next"]:not([disabled]):not(.artdeco-button--disabled), ' +
            '[data-test-ts-pagination] a[data-test-pagination-next]:not([disabled]):not(.artdeco-button--disabled), ' +
            '[data-test-ts-pagination] a[data-test-mini-pagination-next]:not([disabled]):not(.artdeco-button--disabled), ' +
            '.profile-list-container__pagination a[rel="next"]:not([disabled]):not(.artdeco-button--disabled), ' +
            '.profile-list-container__pagination [data-test-pagination-next]:not([disabled]):not(.artdeco-button--disabled), ' +
            '.mini-pagination a[rel="next"]:not([disabled]):not(.artdeco-button--disabled), ' +
            '.mini-pagination [data-test-mini-pagination-next]:not([disabled]):not(.artdeco-button--disabled)'
        )).filter(isPaginationCandidate).sort((a, b) => getPaginationScore(b) - getPaginationScore(a));

        if (enabledPaginationButtons.length > 0) {
            enabledPaginationButtons[0].scrollIntoView({ block: 'center' });
            enabledPaginationButtons[0].click();
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
            '.mini-pagination button.artdeco-button--disabled[data-test-mini-pagination-next]'
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

    result = run_browser_command(cdp_port, "eval", CLICK_NEXT_PAGE_JS)

    if result.get("error"):
        return {
            "success": False,
            "is_last_page": False,
            "previous_url": "",
            "current_url": "",
            "error": f"Browser command failed: {result['error']}",
        }

    parsed = result.get("parsed", {})

    # Handle clean end-of-results (last page)
    if parsed.get("isLastPage"):
        return {
            "success": True,  # Success - just no more pages
            "is_last_page": True,
            "previous_url": parsed.get("previousUrl", ""),
            "current_url": parsed.get(
                "previousUrl", ""
            ),  # URL doesn't change on last page
            "error": None,
        }

    if not parsed.get("clicked"):
        return {
            "success": False,
            "is_last_page": False,
            "previous_url": parsed.get("previousUrl", ""),
            "current_url": parsed.get("previousUrl", ""),
            "error": parsed.get("error", "Next page pagination control not found"),
        }

    # Wait for navigation to complete with bounded polling
    # For page > 1, we expect the URL to contain the specific start offset
    expected_start_param = f"start={expected_start}" if expected_start else None
    current_url = ""
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        url_result = run_browser_command(
            cdp_port, "eval", "({ url: window.location.href })"
        )
        current_url = url_result.get("parsed", {}).get("url", "")

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

    return {
        "success": True,
        "is_last_page": False,
        "previous_url": parsed.get("previousUrl", ""),
        "current_url": current_url,
        "error": None,
    }


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
            - current_page: int - detected page number (1 if unknown)
            - current_url: str - the current URL
            - is_contextual: bool - whether on valid contextual search page
            - same_project: bool - whether on same project
    """
    result = run_browser_command(cdp_port, "eval", "({ url: window.location.href })")
    current_url = result.get("parsed", {}).get("url", "")

    # Check if on contextual search page for this project
    is_contextual = is_contextual_recruiter_search_url(current_url, project_id)

    # Check if same project (even if not on search page)
    current_project_id = extract_project_id_from_url(current_url)
    same_project = current_project_id == project_id

    # Extract page number if contextual, otherwise default to 1
    current_page = get_page_number_from_url(current_url) if is_contextual else 1

    return {
        "current_page": current_page,
        "current_url": current_url,
        "is_contextual": is_contextual,
        "same_project": same_project,
    }


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

    # Page 1: use base URL directly (it's already a fresh contextual URL)
    if page == 1:
        ensure_result = ensure_page_ready(
            cdp_port=cdp_port,
            work_dir=work_dir,
            target_url=base_url,
            context=f"navigate_to_page_{page}",
        )
        return {
            "success": ensure_result["ready"],
            "is_last_page": False,
            "url": base_url,
            "state": ensure_result["state"],
            "method": "direct",
        }

    # Page > 1: Determine actual current page from browser state
    # This handles resumed runs where browser may already be on page 2+
    if project_id:
        browser_state = get_current_page_from_browser(cdp_port, project_id)
        current_page = browser_state["current_page"]
        current_url = browser_state["current_url"]
        is_contextual = browser_state["is_contextual"]
        same_project = browser_state["same_project"]

        # If already on target page and contextual, ensure ready and return
        if current_page == page and is_contextual:
            ensure_result = ensure_page_ready(
                cdp_port=cdp_port,
                work_dir=work_dir,
                target_url=current_url,
                context=f"navigate_to_page_{page}_already_there",
            )
            return {
                "success": ensure_result["ready"],
                "is_last_page": False,
                "url": current_url,
                "state": ensure_result["state"],
                "method": "already_on_page",
            }

        # If on same project and contextual but different page, start from there
        # Only do this if current page is before target (can't go backwards via next)
        if is_contextual and same_project and current_page < page:
            # Start from detected current page
            # CRITICAL: Verify the detected page is ready before first click
            # This prevents clicking from a still-loading page which could misroute
            ensure_result = ensure_page_ready(
                cdp_port=cdp_port,
                work_dir=work_dir,
                target_url=current_url,
                context=f"navigate_to_page_{current_page}_resume_ready",
            )
            if not ensure_result["ready"]:
                return {
                    "success": False,
                    "is_last_page": False,
                    "url": current_url,
                    "state": f"page_{current_page}_not_ready",
                    "method": "ui_pagination",
                    "error": f"Resumed page {current_page} not ready: {ensure_result['state']}",
                }
        else:
            # Not safe to continue from current state - realign to base_url page 1
            current_page = 1
            current_url = base_url
            # Ensure page 1 is ready before starting pagination sequence
            ensure_result = ensure_page_ready(
                cdp_port=cdp_port,
                work_dir=work_dir,
                target_url=base_url,
                context=f"navigate_to_page_{page}_realign",
            )
            if not ensure_result["ready"]:
                return {
                    "success": False,
                    "is_last_page": False,
                    "url": base_url,
                    "state": ensure_result["state"],
                    "method": "realign_failed",
                    "error": f"Failed to realign to page 1: {ensure_result['state']}",
                }
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

        # Handle clean end-of-results (last page) - this is NOT a failure
        if pagination_result.get("is_last_page"):
            return {
                "success": True,
                "is_last_page": True,
                "url": pagination_result.get("current_url", current_url),
                "state": "last_page",
                "method": "ui_pagination",
            }

        # Check for pagination failure
        if not pagination_result.get("success"):
            error_msg = pagination_result.get("error", "Unknown pagination error")

            # FAIL CLOSED: Missing next button indicates DOM drift or selector mismatch
            # This is NOT a candidate for fallback - it's a structural failure
            if "DOM drift" in error_msg or "selector mismatch" in error_msg:
                return {
                    "success": False,
                    "is_last_page": False,
                    "url": pagination_result.get("current_url", current_url),
                    "state": "pagination_failed",
                    "method": "ui_pagination",
                    "error": error_msg,
                }

            # UI pagination failed for other reasons - fall back to synthesized URL
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

            return {
                "success": ensure_result["ready"],
                "is_last_page": False,
                "url": paginated_url,
                "state": ensure_result["state"],
                "method": "synthesized_fallback",
            }

        # Validate the pagination result if we have project_id
        if project_id:
            validation = validate_pagination_result(
                pagination_result, next_page, project_id
            )
            if not validation["valid"]:
                # Pagination succeeded but landed on wrong page - this is an error
                return {
                    "success": False,
                    "is_last_page": False,
                    "url": pagination_result.get("current_url", ""),
                    "state": "pagination_validation_failed",
                    "method": "ui_pagination",
                    "error": validation["error"],
                }

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
                # Page not ready - fail closed
                return {
                    "success": False,
                    "is_last_page": False,
                    "url": current_url,
                    "state": f"page_{current_page}_not_ready",
                    "method": "ui_pagination",
                    "error": f"Page {current_page} not ready: {ensure_result['state']}",
                }

    # Reached target page - ensure it's ready for extraction
    ensure_result = ensure_page_ready(
        cdp_port=cdp_port,
        work_dir=work_dir,
        target_url=current_url,
        context=f"navigate_to_page_{page}_ui",
    )

    return {
        "success": ensure_result["ready"],
        "is_last_page": False,
        "url": current_url,
        "state": ensure_result["state"],
        "method": "ui_pagination",
    }


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
        profile_url = candidate.get("url", "")

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

    result: dict[str, Any] = {
        "success": False,
        "exit_code": None,
        "message": "",
        "workbook_path": None,
        "existing_urls": set(),
        "project_id": None,
        "cdp_port": None,
        "work_dir": None,
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
            cdp_port = profile.get("CDP_PORT", "9230")
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
        result["message"] = f"Browser preflight failed: page state is '{state}'"
        result["exit_code"] = 1
        return result

    # Fail on unknown state with browser/CDP error
    if state == "unknown":
        details = state_result.get("details", {})
        error_text = details.get("error", "Unknown browser/CDP error")
        result["message"] = f"Browser preflight failed: {error_text}"
        result["exit_code"] = 1
        return result

    # Note: We don't reject ordinary recruiter pages that are merely not on
    # search results yet - this preflight is only for obviously bad states

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
        return result

    target_url = context_result["fresh_url"]
    print(f"Fresh search context resolved: {target_url}")

    # Process pages
    pages_to_process = args.max_pages if args.max_pages > 0 else float("inf")
    pages_processed_count = 0
    total_stats = {"total": 0, "new": 0, "updated": 0, "skipped": 0}
    max_pages_reached = False  # Track if stopped due to --max-pages limit

    print(f"Starting extraction from page {current_page}")
    print(f"Target URL: {target_url}")
    print(f"Workbook: {workbook_path}")
    if args.dry_run:
        print("DRY RUN: No changes will be written to workbook")
    print()

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
                    # Persist failed state for resume
                    state_saved = save_extraction_state(
                        state_path=state_path,
                        project_id=project_id,
                        workbook_path=workbook_path,
                        config_path=args.config,
                        status="failed",
                        last_completed_page=current_page - 1
                        if current_page > 1
                        else None,
                        next_start_page=current_page,
                        error=f"Navigation failed: {error_msg}",
                        fresh_url=target_url,
                        dry_run=args.dry_run,
                    )
                    if not state_saved:
                        result["message"] = (
                            f"Navigation failed on page {current_page}: {error_msg}; "
                            f"additionally, failed to persist state to {state_path}"
                        )
                        result["exit_code"] = 2
                        return result
                    result["message"] = (
                        f"Navigation failed on page {current_page}: {error_msg}"
                    )
                    result["exit_code"] = 1
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
                    # Persist failed state for resume
                    state_saved = save_extraction_state(
                        state_path=state_path,
                        project_id=project_id,
                        workbook_path=workbook_path,
                        config_path=args.config,
                        status="failed",
                        last_completed_page=current_page - 1
                        if current_page > 1
                        else None,
                        next_start_page=current_page,
                        error=f"Extraction failed: {extraction_result.get('message', 'Unknown error')}",
                        fresh_url=target_url,
                        dry_run=args.dry_run,
                    )
                    if not state_saved:
                        result["message"] = (
                            f"Extraction failed on page {current_page}: {extraction_result['message']}; "
                            f"additionally, failed to persist state to {state_path}"
                        )
                        result["exit_code"] = 2
                        return result
                    # Propagate the extraction failure exit code
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

            # Check for workbook I/O failure
            if page_stats.get("error"):
                # Persist failed state for resume
                state_saved = save_extraction_state(
                    state_path=state_path,
                    project_id=project_id,
                    workbook_path=workbook_path,
                    config_path=args.config,
                    status="failed",
                    last_completed_page=current_page - 1 if current_page > 1 else None,
                    next_start_page=current_page,
                    error=f"Workbook write failed: {page_stats['message']}",
                    fresh_url=target_url,
                    dry_run=args.dry_run,
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

            # Update running state after successful page processing
            state_saved = save_extraction_state(
                state_path=state_path,
                project_id=project_id,
                workbook_path=workbook_path,
                config_path=args.config,
                status="running",
                last_completed_page=current_page - 1,
                next_start_page=current_page,
                fresh_url=target_url,
                dry_run=args.dry_run,
            )
            if not state_saved:
                result["message"] = f"Failed to persist running state to {state_path}"
                result["exit_code"] = 2
                return result

            # Brief pause between pages to avoid overwhelming the browser
            if pages_processed_count < pages_to_process:
                time.sleep(1)
            else:
                # Loop condition will fail on next iteration - max_pages reached
                max_pages_reached = True

    except KeyboardInterrupt:
        # Persist resumable state for the current page before exiting
        # This ensures interrupted runs remain resumable/retryable
        print(f"\n  Interrupted during page {current_page}. Persisting state...")
        state_saved = save_extraction_state(
            state_path=state_path,
            project_id=project_id,
            workbook_path=workbook_path,
            config_path=args.config,
            status="running",
            last_completed_page=current_page - 1 if current_page > 1 else None,
            next_start_page=current_page,
            fresh_url=target_url,
            dry_run=args.dry_run,
        )
        if not state_saved:
            # Fail-closed: report state persistence failure but still exit
            print(
                f"  Warning: failed to persist state to {state_path}",
                file=sys.stderr,
            )
        else:
            print(f"  State persisted. Resume with: --resume")
        raise  # Re-raise KeyboardInterrupt to exit with code 130

    # Determine final state: completed only for true clean completion
    # max-pages partial stop persists as running with next_start_page set
    if max_pages_reached and pages_processed_count >= args.max_pages > 0:
        # Partial run due to --max-pages limit - remain resumable
        final_status = "running"
        final_next_start_page = current_page
        completion_message = f"Partial extraction: {result['pages_processed']} pages processed (max-pages limit reached)"
    else:
        # True completion: last page reached or no more results
        final_status = "completed"
        final_next_start_page = None
        completion_message = f"Extraction complete: {result['pages_processed']} pages"

    # Persist final state
    state_saved = save_extraction_state(
        state_path=state_path,
        project_id=project_id,
        workbook_path=workbook_path,
        config_path=args.config,
        status=final_status,
        last_completed_page=current_page - 1 if current_page > 1 else None,
        next_start_page=final_next_start_page,
        fresh_url=target_url,
        dry_run=args.dry_run,
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
        print("\n\nExtraction interrupted by user", file=sys.stderr)
        print(
            "You can resume by running the same command with --resume",
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
