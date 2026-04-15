#!/usr/bin/env python3
"""Bounded adaptive recovery layer for LinkedIn Recruiter browser automation.

This module provides page state classification and bounded recovery attempts
for LinkedIn Recruiter browser automation scripts. It handles common failure
modes like 404s, logged-out states, CAPTCHAs, blocking dialogs, and loading
timeouts with structured recovery attempts before giving up.

Usage:
    from recruiter_page_utils import PageStateProbe, RecoveryHelper

    probe = PageStateProbe(cdp_port="9230")
    state = probe.classify_state()

    recovery = RecoveryHelper(cdp_port="9230", work_dir="/path/to/work")
    result = recovery.attempt_recovery(target_url="https://...")
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Import shared browser utilities
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from browser_utils import check_dialog_status, run_browser_command


class PageState(Enum):
    """Classification states for LinkedIn Recruiter pages."""

    READY = "ready"
    LOADING = "loading"
    BAD_PAGE = "bad_page"
    LOGGED_OUT_OR_WRONG_PRODUCT = "logged_out_or_wrong_product"
    BLOCKED_OR_CAPTCHA = "blocked_or_captcha"
    DIALOG_BLOCKED = "dialog_blocked"
    UNKNOWN = "unknown"


# JavaScript to classify page state
CLASSIFY_PAGE_STATE_JS = """
(function() {
    const url = window.location.href;
    const title = document.title || '';
    const bodyText = document.body ? document.body.innerText.toLowerCase() : '';
    const bodyPreview = bodyText.substring(0, 1000);

    // Check for 404 / bad page
    const is404 = (
        title.includes('404') ||
        title.includes('Page not found') ||
        bodyText.includes('page not found') ||
        bodyText.includes("this page doesn't exist") ||
        url.includes('/404/') ||
        document.querySelector('.error-404, .not-found, [data-test-error-page]') !== null
    );

    // Check for login page / wrong product
    const isLoginPage = (
        url.includes('/login') ||
        url.includes('/checkpoint') ||
        title.toLowerCase().includes('login') ||
        title.toLowerCase().includes('sign in') ||
        bodyText.includes('sign in to linkedin') ||
        bodyText.includes('join now') ||
        document.querySelector('input[name="session_key"], input[type="email"]') !== null
    );

    // Check for non-recruiter LinkedIn (feed, etc.)
    const isWrongProduct = (
        url.includes('/feed/') ||
        url.includes('/in/') ||
        (url.includes('linkedin.com') && !url.includes('/talent/') && !url.includes('recruiter'))
    );

    // Check for CAPTCHA / verification
    const isBlocked = (
        title.toLowerCase().includes('captcha') ||
        title.toLowerCase().includes('security check') ||
        title.toLowerCase().includes('verification') ||
        bodyText.includes('captcha') ||
        bodyText.includes('security check') ||
        bodyText.includes('please verify') ||
        bodyText.includes('unusual activity') ||
        document.querySelector('iframe[src*="captcha"], .captcha, #captcha, [data-test-captcha]') !== null
    );

    // Check for loading state
    const loadingIndicators = [
        '.loading-overlay',
        '.loading-overlay__wrapper',
        '.screen-loader__content',
        '[class*="loading-overlay"]',
        '[class*="screen-loader"]'
    ];
    const isVisible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            style.opacity !== '0' &&
            (rect.width > 0 || rect.height > 0)
        );
    };
    let hasLoadingIndicator = false;
    for (const selector of loadingIndicators) {
        const element = document.querySelector(selector);
        if (element && isVisible(element)) {
            hasLoadingIndicator = true;
            break;
        }
    }
    const hasExplicitLoadingText = (
        bodyText.includes('loading search results') ||
        bodyText.includes('please wait')
    );
    const isLoading = (
        hasLoadingIndicator ||
        hasExplicitLoadingText ||
        document.readyState !== 'complete'
    );

    // Check for recruiter-specific ready indicators
    const hasRecruiterContent = (
        document.querySelector('.profile-list__border-bottom') !== null ||
        document.querySelector('a[href*="/talent/profile/"]') !== null ||
        document.querySelector('[data-test-id*="project"]') !== null ||
        document.querySelector('input[placeholder*="Search"]') !== null ||
        url.includes('/talent/') ||
        url.includes('recruiter')
    );
    const hasProjectsListContent = (
        url.includes('/talent/projects') && (
            document.querySelector('input[placeholder*="Search for a project"]') !== null ||
            document.querySelector('a[href*="/talent/hire/"][href*="/overview"]') !== null ||
            document.querySelector('a[href*="/talent/hire/"][href*="/discover/recruiterSearch"]') !== null
        )
    );
    // Overview page ready signal - takes precedence over loading wrappers
    // LinkedIn keeps .loading-overlay__wrapper in DOM on loaded pages
    // Live DOM selectors observed on project 1687654572 overview page:
    // - h1.t-24.t-white.project-name__name[data-test-project-name-name]
    // - [data-test-project-overview-layout], [data-test-overview-header]
    // - [data-test-project-overview-modules], [data-test-project-overview-sidebar]
    // - [data-test-overview-about-project-module], [data-test-title-bar-project-title]
    const hasOverviewContent = (
        url.includes('/overview') && (
            document.querySelector('h1[data-test-project-name-name]') !== null ||
            document.querySelector('[data-test-project-overview-layout]') !== null ||
            document.querySelector('[data-test-overview-header]') !== null ||
            document.querySelector('[data-test-project-overview-modules]') !== null ||
            document.querySelector('[data-test-project-overview-sidebar]') !== null ||
            document.querySelector('[data-test-overview-about-project-module]') !== null ||
            document.querySelector('[data-test-title-bar-project-title]') !== null ||
            document.querySelector('[data-test-project-meta-dropdown-trigger]') !== null ||
            document.querySelector('button[data-test-collapsible-menu-link="overview"]') !== null
        )
    );
    const candidateCardCount = document.querySelectorAll('li.profile-list__border-bottom').length;
    const profileLinkCount = document.querySelectorAll('a[href*="/talent/profile/"]').length;
    const hasSearchResultsContent = (
        candidateCardCount > 0 ||
        profileLinkCount > 0 ||
        document.querySelector('.results-container') !== null
    );

    return {
        url: url,
        title: title,
        is404: is404,
        isLoginPage: isLoginPage,
        isWrongProduct: isWrongProduct,
        isBlocked: isBlocked,
        isLoading: isLoading,
        hasLoadingIndicator: hasLoadingIndicator,
        hasExplicitLoadingText: hasExplicitLoadingText,
        hasRecruiterContent: hasRecruiterContent,
        hasProjectsListContent: hasProjectsListContent,
        hasOverviewContent: hasOverviewContent,
        hasSearchResultsContent: hasSearchResultsContent,
        candidateCardCount: candidateCardCount,
        profileLinkCount: profileLinkCount,
        bodyPreview: bodyPreview,
        readyState: document.readyState
    };
})()
"""


class PageStateProbe:
    """Probes and classifies the current state of a LinkedIn Recruiter page."""

    def __init__(self, cdp_port: str):
        """Initialize the page state probe.

        Args:
            cdp_port: Chrome DevTools Protocol port number
        """
        self.cdp_port = cdp_port

    def classify_state(self) -> dict[str, Any]:
        """Classify the current page state.

        Returns a dict with:
            - state: PageState enum value as string
            - details: Raw detection results from JavaScript probe
            - dialog_info: Dialog status if a dialog is blocking
            - timestamp: ISO timestamp of classification
        """
        # First check for blocking dialogs
        dialog_info = check_dialog_status(self.cdp_port)

        if dialog_info.get("has_dialog"):
            return {
                "state": PageState.DIALOG_BLOCKED.value,
                "details": {"dialog": dialog_info},
                "dialog_info": dialog_info,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Run page state detection
        result = run_browser_command(
            self.cdp_port, "eval", CLASSIFY_PAGE_STATE_JS, timeout=15
        )

        if result.get("error"):
            return {
                "state": PageState.UNKNOWN.value,
                "details": {"error": result["error"]},
                "dialog_info": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        details = result.get("parsed", {})

        # Classify based on detection results
        state = self._determine_state(details)

        return {
            "state": state.value,
            "details": details,
            "dialog_info": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _determine_state(self, details: dict) -> PageState:
        """Determine page state from detection details."""
        if details.get("is404"):
            return PageState.BAD_PAGE

        if details.get("isBlocked"):
            return PageState.BLOCKED_OR_CAPTCHA

        if details.get("isLoginPage") or details.get("isWrongProduct"):
            return PageState.LOGGED_OUT_OR_WRONG_PRODUCT

        # Overview content takes precedence over loading indicators
        # LinkedIn keeps loading wrapper classes in DOM on loaded pages
        if details.get("hasOverviewContent"):
            return PageState.READY

        if details.get("hasProjectsListContent"):
            return PageState.READY

        if details.get("hasSearchResultsContent"):
            return PageState.READY

        if details.get("isLoading"):
            return PageState.LOADING

        if details.get("hasRecruiterContent"):
            return PageState.READY

        # If we're on a LinkedIn domain but no specific indicators
        url = details.get("url", "")
        if "linkedin.com" in url:
            # Check if it's a talent/recruiter URL but no content detected
            if "/talent/" in url or "recruiter" in url:
                # Might still be loading or have an issue
                if details.get("readyState") != "complete":
                    return PageState.LOADING
                return PageState.READY

        return PageState.UNKNOWN

    def is_ready(self) -> bool:
        """Quick check if page is in ready state."""
        classification = self.classify_state()
        return classification["state"] == PageState.READY.value

    def is_blocked(self) -> bool:
        """Quick check if page is in a blocked state (non-recoverable)."""
        classification = self.classify_state()
        return classification["state"] in (
            PageState.BLOCKED_OR_CAPTCHA.value,
            PageState.LOGGED_OUT_OR_WRONG_PRODUCT.value,
        )


class RecoveryHelper:
    """Helper for bounded recovery attempts from bad page states."""

    DEFAULT_MAX_RECOVERY_ATTEMPTS = 2
    DEFAULT_RECOVERY_DELAY_SECONDS = 2

    def __init__(
        self,
        cdp_port: str,
        work_dir: str | Path | None = None,
        max_attempts: int = DEFAULT_MAX_RECOVERY_ATTEMPTS,
    ):
        """Initialize the recovery helper.

        Args:
            cdp_port: Chrome DevTools Protocol port number
            work_dir: Working directory for incident reporting (optional)
            max_attempts: Maximum recovery attempts before giving up
        """
        self.cdp_port = cdp_port
        self.work_dir = Path(work_dir) if work_dir else None
        self.max_attempts = max_attempts
        self.probe = PageStateProbe(cdp_port)
        self.attempt_count = 0
        self.recovery_log: list[dict] = []

    def attempt_recovery(
        self,
        target_url: str | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Attempt bounded recovery from a bad page state.

        Args:
            target_url: URL to navigate to if recovery involves navigation
            context: Optional context string for logging (e.g., function name)

        Returns:
            Dict with recovery result:
                - success: bool - whether recovery succeeded
                - final_state: str - final page state after recovery attempts
                - attempts_made: int - number of recovery attempts made
                - actions_taken: list - log of recovery actions attempted
                - error: str | None - error message if recovery failed
        """
        self.attempt_count = 0
        self.recovery_log = []

        # Get initial state
        initial_state = self.probe.classify_state()
        initial_state_value = initial_state["state"]

        # If already ready, no recovery needed
        if initial_state_value == PageState.READY.value:
            return {
                "success": True,
                "final_state": PageState.READY.value,
                "attempts_made": 0,
                "actions_taken": [],
                "error": None,
            }

        # Check for non-recoverable states
        if initial_state_value in (
            PageState.BLOCKED_OR_CAPTCHA.value,
            PageState.LOGGED_OUT_OR_WRONG_PRODUCT.value,
        ):
            error_msg = f"Non-recoverable state detected: {initial_state_value}"
            self._write_incident(initial_state, context, error_msg)
            return {
                "success": False,
                "final_state": initial_state_value,
                "attempts_made": 0,
                "actions_taken": [],
                "error": error_msg,
            }

        # Attempt recovery
        actions_taken: list[str] = []

        for attempt in range(1, self.max_attempts + 1):
            self.attempt_count = attempt

            # Check current state
            current_state = self.probe.classify_state()
            current_state_value = current_state["state"]

            # If recovered, return success
            if current_state_value == PageState.READY.value:
                return {
                    "success": True,
                    "final_state": PageState.READY.value,
                    "attempts_made": attempt,
                    "actions_taken": actions_taken,
                    "error": None,
                }

            # Handle dialog blocking
            if current_state_value == PageState.DIALOG_BLOCKED.value:
                # Dialogs require manual intervention - not recoverable via script
                error_msg = (
                    f"Blocking dialog detected on attempt {attempt}: "
                    f"{current_state.get('dialog_info', {})}"
                )
                self._write_incident(current_state, context, error_msg)
                return {
                    "success": False,
                    "final_state": current_state_value,
                    "attempts_made": attempt,
                    "actions_taken": actions_taken,
                    "error": error_msg,
                }

            # Attempt recovery action based on state
            if current_state_value == PageState.BAD_PAGE.value:
                if target_url and attempt == 1:
                    # Navigate to target URL
                    action = f"navigate_to_target: {target_url}"
                    actions_taken.append(action)
                    self._navigate_to_url(target_url)
                else:
                    # Refresh current page
                    action = "refresh_page"
                    actions_taken.append(action)
                    self._refresh_page()

            elif current_state_value == PageState.LOADING.value:
                # Wait for loading to complete, then refresh if stuck
                action = f"wait_for_loading (attempt {attempt})"
                actions_taken.append(action)
                time.sleep(self.DEFAULT_RECOVERY_DELAY_SECONDS * attempt)

                # Check if still loading
                check_state = self.probe.classify_state()
                if check_state["state"] == PageState.LOADING.value and attempt > 1:
                    # Still loading after wait - try refresh
                    action = "refresh_page (stuck loading)"
                    actions_taken.append(action)
                    self._refresh_page()

            elif current_state_value == PageState.UNKNOWN.value:
                # Try navigation if target URL provided, else refresh
                if target_url:
                    action = f"navigate_to_target: {target_url}"
                    actions_taken.append(action)
                    self._navigate_to_url(target_url)
                else:
                    action = "refresh_page"
                    actions_taken.append(action)
                    self._refresh_page()

            # Wait after action
            time.sleep(self.DEFAULT_RECOVERY_DELAY_SECONDS)

        # Max attempts reached - check final state
        final_state = self.probe.classify_state()
        final_state_value = final_state["state"]

        if final_state_value == PageState.READY.value:
            return {
                "success": True,
                "final_state": PageState.READY.value,
                "attempts_made": self.max_attempts,
                "actions_taken": actions_taken,
                "error": None,
            }

        # Recovery failed
        error_msg = (
            f"Recovery failed after {self.max_attempts} attempts. "
            f"Final state: {final_state_value}"
        )
        self._write_incident(final_state, context, error_msg)

        return {
            "success": False,
            "final_state": final_state_value,
            "attempts_made": self.max_attempts,
            "actions_taken": actions_taken,
            "error": error_msg,
        }

    def _navigate_to_url(self, url: str) -> None:
        """Navigate to the specified URL."""
        # Use guarded browser command to ensure CDP is available
        result = run_browser_command(self.cdp_port, "goto", url, timeout=30)
        if result.get("error"):
            # Log error but continue (best effort for recovery)
            pass
        time.sleep(2)  # Wait for navigation

    def _refresh_page(self) -> None:
        """Refresh the current page."""
        # Use guarded browser command to ensure CDP is available
        result = run_browser_command(
            self.cdp_port, "eval", "location.reload()", timeout=15
        )
        if result.get("error"):
            # Log error but continue (best effort for recovery)
            pass
        time.sleep(2)  # Wait for reload

    def _write_incident(
        self,
        state_info: dict[str, Any],
        context: str | None,
        error_message: str,
    ) -> None:
        """Write an incident report to the incidents directory."""
        if not self.work_dir:
            return

        incidents_dir = self.work_dir / "runtime" / "incidents"
        try:
            incidents_dir.mkdir(parents=True, exist_ok=True)

            incident = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cdp_port": self.cdp_port,
                "context": context,
                "state": state_info.get("state"),
                "state_details": state_info.get("details"),
                "dialog_info": state_info.get("dialog_info"),
                "recovery_attempts": self.attempt_count,
                "error_message": error_message,
            }

            # Generate filename with timestamp
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            state = state_info.get("state", "unknown")
            filename = f"incident_{ts}_{state}.json"

            incident_path = incidents_dir / filename
            incident_path.write_text(json.dumps(incident, indent=2))
        except Exception:
            pass  # Best effort - don't fail if incident writing fails


def with_recovery(
    cdp_port: str,
    work_dir: str | Path | None = None,
    target_url: str | None = None,
    context: str | None = None,
    max_attempts: int = RecoveryHelper.DEFAULT_MAX_RECOVERY_ATTEMPTS,
) -> dict[str, Any]:
    """Convenience function to run recovery and return result.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        work_dir: Working directory for incident reporting
        target_url: URL to navigate to if recovery involves navigation
        context: Optional context for logging
        max_attempts: Maximum recovery attempts

    Returns:
        Recovery result dict
    """
    helper = RecoveryHelper(
        cdp_port=cdp_port,
        work_dir=work_dir,
        max_attempts=max_attempts,
    )
    return helper.attempt_recovery(target_url=target_url, context=context)


def normalize_url_for_comparison(url: str) -> str:
    """Normalize URL for comparison by removing query params and fragments.

    Args:
        url: The URL to normalize

    Returns:
        Normalized URL (scheme + netloc + path only)
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def urls_match_allowing_params(url1: str, url2: str) -> bool:
    """Check if two URLs match, ignoring query parameters and fragments.

    Args:
        url1: First URL to compare
        url2: Second URL to compare

    Returns:
        True if URLs match (path-wise), False otherwise
    """
    return normalize_url_for_comparison(url1) == normalize_url_for_comparison(url2)


def _validate_target_url_match(
    cdp_port: str,
    target_url: str,
    context: str | None = None,
) -> dict[str, Any]:
    """Validate that current URL matches target_url, allowing extra query params.

    This is stricter than path-only matching (which fails for pagination)
    but more flexible than exact URL matching (allows LinkedIn's extra params).

    The validation ensures:
    - Path matches exactly
    - All query params in target_url are present in current_url
    - Current URL can have additional query params (trackingId, etc.)

    Args:
        cdp_port: Chrome DevTools Protocol port number
        target_url: The expected URL (may include query params like ?start=25)
        context: Optional context for error messages

    Returns:
        Dict with:
            - matches: bool - whether current URL matches target
            - current_url: str - the actual current URL
            - expected_patterns: list - the target URL that was checked
            - error: str | None - error message if mismatch
    """
    from urllib.parse import urlparse, parse_qs, urlencode

    result = run_browser_command(cdp_port, "eval", "({ url: window.location.href })")

    if result.get("error"):
        return {
            "matches": False,
            "current_url": "",
            "expected_patterns": [target_url],
            "error": f"Failed to get current URL: {result['error']}",
        }

    current_url = result.get("parsed", {}).get("url", "")
    if not current_url:
        try:
            parsed = json.loads(result.get("stdout", "{}"))
            current_url = parsed.get("url", "")
        except json.JSONDecodeError:
            pass

    parsed_target = urlparse(target_url)
    parsed_current = urlparse(current_url)

    # Path must match exactly
    if parsed_target.path != parsed_current.path:
        context_str = f" [{context}]" if context else ""
        return {
            "matches": False,
            "current_url": current_url,
            "expected_patterns": [target_url],
            "error": (
                f"Page identity mismatch{context_str}: "
                f"path mismatch (expected '{parsed_target.path}', got '{parsed_current.path}')"
            ),
        }

    # All query params in target must be present in current
    target_params = parse_qs(parsed_target.query)
    current_params = parse_qs(parsed_current.query)

    for key, target_values in target_params.items():
        current_values = current_params.get(key, [])
        # For each expected value, check it exists in current
        for val in target_values:
            if val not in current_values:
                context_str = f" [{context}]" if context else ""
                return {
                    "matches": False,
                    "current_url": current_url,
                    "expected_patterns": [target_url],
                    "error": (
                        f"Page identity mismatch{context_str}: "
                        f"missing query param '{key}={val}' (expected '{target_url}', got '{current_url}')"
                    ),
                }

    return {
        "matches": True,
        "current_url": current_url,
        "expected_patterns": [target_url],
        "error": None,
    }


def assert_page_identity(
    cdp_port: str,
    expected_url_patterns: list[str] | None = None,
    expected_path_patterns: list[str] | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Assert that the current page matches expected identity patterns.

    This function verifies the page is actually on the intended page,
    not just any ready /talent/ page.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        expected_url_patterns: List of URL substrings that must match (e.g., ["/talent/hire/", "/discover/recruiterSearch"])
        expected_path_patterns: List of path patterns that must match (e.g., ["/talent/projects"])
        context: Optional context for error messages

    Returns:
        Dict with:
            - matches: bool - whether page identity matches expectations
            - current_url: str - the actual current URL
            - expected_patterns: list - the patterns that were checked
            - error: str | None - error message if identity mismatch
    """
    result = run_browser_command(cdp_port, "eval", "({ url: window.location.href })")

    if result.get("error"):
        return {
            "matches": False,
            "current_url": "",
            "expected_patterns": expected_url_patterns or expected_path_patterns or [],
            "error": f"Failed to get current URL: {result['error']}",
        }

    current_url = result.get("parsed", {}).get("url", "")
    if not current_url:
        # Try to extract from stdout
        try:
            parsed = json.loads(result.get("stdout", "{}"))
            current_url = parsed.get("url", "")
        except json.JSONDecodeError:
            pass

    errors = []

    # Check URL patterns
    if expected_url_patterns:
        url_matches = any(pattern in current_url for pattern in expected_url_patterns)
        if not url_matches:
            errors.append(
                f"URL '{current_url}' does not contain any expected patterns: {expected_url_patterns}"
            )

    # Check path patterns
    if expected_path_patterns:
        from urllib.parse import urlparse

        path = urlparse(current_url).path
        path_matches = any(pattern in path for pattern in expected_path_patterns)
        if not path_matches:
            errors.append(
                f"Path '{path}' does not contain any expected patterns: {expected_path_patterns}"
            )

    if errors:
        context_str = f" [{context}]" if context else ""
        return {
            "matches": False,
            "current_url": current_url,
            "expected_patterns": expected_url_patterns or expected_path_patterns or [],
            "error": f"Page identity mismatch{context_str}: {'; '.join(errors)}",
        }

    return {
        "matches": True,
        "current_url": current_url,
        "expected_patterns": expected_url_patterns or expected_path_patterns or [],
        "error": None,
    }


def ensure_page_ready(
    cdp_port: str,
    work_dir: str | Path | None = None,
    target_url: str | None = None,
    context: str | None = None,
    max_wait_seconds: float = 30.0,
    require_page_identity: bool = True,
    expected_url_patterns: list[str] | None = None,
    _recursion_depth: int = 0,
) -> dict[str, Any]:
    """Ensure the page is ready, attempting recovery if needed.

    This is a higher-level helper that combines state checking with recovery.
    Optionally validates page identity to ensure we're on the intended page.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        work_dir: Working directory for incident reporting
        target_url: URL to navigate to if recovery involves navigation
        context: Optional context for logging
        max_wait_seconds: Maximum time to wait for page to be ready
        _recursion_depth: Internal recursion guard (do not use)
        require_page_identity: Whether to validate page identity after ready
        expected_url_patterns: URL patterns to validate if require_page_identity is True

    Returns:
        Dict with:
            - ready: bool - whether page is ready
            - state: str - final page state
            - recovery_result: dict | None - recovery result if attempted
            - identity_check: dict | None - identity validation result if performed
            - waited_seconds: float - how long we waited
    """
    import time

    # Recursion guard for wrong-page navigation retries
    MAX_RECURSION_DEPTH = 2

    start_time = time.time()
    probe = PageStateProbe(cdp_port)

    # Quick check if already ready
    if probe.is_ready():
        # Validate identity if required
        identity_result = None
        if require_page_identity:
            if expected_url_patterns:
                identity_result = assert_page_identity(
                    cdp_port,
                    expected_url_patterns=expected_url_patterns,
                    context=context,
                )
                if not identity_result["matches"]:
                    # Wrong page: navigate to target and re-validate (if not too deep)
                    if target_url and _recursion_depth < MAX_RECURSION_DEPTH:
                        recovery = RecoveryHelper(cdp_port, work_dir)
                        recovery._navigate_to_url(target_url)
                        time.sleep(2)  # Allow page to load
                        # Re-check readiness and identity after navigation
                        return ensure_page_ready(
                            cdp_port=cdp_port,
                            work_dir=work_dir,
                            target_url=target_url,
                            context=context,
                            max_wait_seconds=max_wait_seconds
                            - (time.time() - start_time),
                            require_page_identity=require_page_identity,
                            expected_url_patterns=expected_url_patterns,
                            _recursion_depth=_recursion_depth + 1,
                        )
                    return {
                        "ready": False,
                        "state": PageState.READY.value,
                        "recovery_result": None,
                        "identity_check": identity_result,
                        "waited_seconds": time.time() - start_time,
                    }
            elif target_url:
                # Validate target_url matches current URL, allowing extra query params
                identity_result = _validate_target_url_match(
                    cdp_port,
                    target_url=target_url,
                    context=context,
                )
                if not identity_result["matches"]:
                    # Wrong page: navigate to target and re-validate (if not too deep)
                    if _recursion_depth < MAX_RECURSION_DEPTH:
                        recovery = RecoveryHelper(cdp_port, work_dir)
                        recovery._navigate_to_url(target_url)
                        time.sleep(2)  # Allow page to load
                        # Re-check readiness and identity after navigation
                        return ensure_page_ready(
                            cdp_port=cdp_port,
                            work_dir=work_dir,
                            target_url=target_url,
                            context=context,
                            max_wait_seconds=max_wait_seconds
                            - (time.time() - start_time),
                            require_page_identity=require_page_identity,
                            expected_url_patterns=expected_url_patterns,
                            _recursion_depth=_recursion_depth + 1,
                        )
                    return {
                        "ready": False,
                        "state": PageState.READY.value,
                        "recovery_result": None,
                        "identity_check": identity_result,
                        "waited_seconds": time.time() - start_time,
                    }
                if not identity_result["matches"]:
                    # Wrong page: navigate to target and re-validate
                    if target_url:
                        recovery = RecoveryHelper(cdp_port, work_dir)
                        recovery._navigate_to_url(target_url)
                        time.sleep(2)  # Allow page to load
                        # Re-check readiness and identity after navigation
                        return ensure_page_ready(
                            cdp_port=cdp_port,
                            work_dir=work_dir,
                            target_url=target_url,
                            context=context,
                            max_wait_seconds=max_wait_seconds
                            - (time.time() - start_time),
                            require_page_identity=require_page_identity,
                            expected_url_patterns=expected_url_patterns,
                        )
                    return {
                        "ready": False,
                        "state": PageState.READY.value,
                        "recovery_result": None,
                        "identity_check": identity_result,
                        "waited_seconds": time.time() - start_time,
                    }
            elif target_url:
                # Validate target_url matches current URL, allowing extra query params
                identity_result = _validate_target_url_match(
                    cdp_port,
                    target_url=target_url,
                    context=context,
                )
                if not identity_result["matches"]:
                    # Wrong page: navigate to target and re-validate
                    recovery = RecoveryHelper(cdp_port, work_dir)
                    recovery._navigate_to_url(target_url)
                    time.sleep(2)  # Allow page to load
                    # Re-check readiness and identity after navigation
                    return ensure_page_ready(
                        cdp_port=cdp_port,
                        work_dir=work_dir,
                        target_url=target_url,
                        context=context,
                        max_wait_seconds=max_wait_seconds - (time.time() - start_time),
                        require_page_identity=require_page_identity,
                        expected_url_patterns=expected_url_patterns,
                    )

        return {
            "ready": True,
            "state": PageState.READY.value,
            "recovery_result": None,
            "identity_check": identity_result,
            "waited_seconds": time.time() - start_time,
        }

    # Check if blocked (non-recoverable)
    if probe.is_blocked():
        state = probe.classify_state()
        return {
            "ready": False,
            "state": state["state"],
            "recovery_result": None,
            "identity_check": None,
            "waited_seconds": time.time() - start_time,
        }

    # Attempt recovery
    recovery = RecoveryHelper(cdp_port, work_dir)
    recovery_result = recovery.attempt_recovery(
        target_url=target_url,
        context=context,
    )

    elapsed = time.time() - start_time

    # If recovery succeeded and we have time, wait a bit more
    if recovery_result["success"] and elapsed < max_wait_seconds:
        # Give page a moment to stabilize
        time.sleep(min(2, max_wait_seconds - elapsed))

    final_state = probe.classify_state()
    is_ready = final_state["state"] == PageState.READY.value

    # Validate identity if required and page is ready
    identity_result = None
    if is_ready and require_page_identity:
        if expected_url_patterns:
            identity_result = assert_page_identity(
                cdp_port,
                expected_url_patterns=expected_url_patterns,
                context=context,
            )
            if not identity_result["matches"]:
                is_ready = False
        elif target_url:
            # Validate target_url matches current URL, allowing extra query params
            identity_result = _validate_target_url_match(
                cdp_port,
                target_url=target_url,
                context=context,
            )
            if not identity_result["matches"]:
                is_ready = False

    return {
        "ready": is_ready,
        "state": final_state["state"],
        "recovery_result": recovery_result,
        "identity_check": identity_result,
        "waited_seconds": time.time() - start_time,
    }
