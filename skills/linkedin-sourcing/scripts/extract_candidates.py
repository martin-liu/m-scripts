#!/usr/bin/env python3
"""Extract candidate data from LinkedIn Recruiter search results via agent-browser.

Usage:
    python3 extract_candidates.py [cdp_port]
    python3 extract_candidates.py --target-url <RECRUITER_PROJECT_URL> [cdp_port]
    python3 extract_candidates.py --project-config <config.sh> [cdp_port]

Prints JSON array of candidates to stdout.

Reads CDP_PORT from ~/.config/linkedin-sourcing/profile.sh if not provided.
Extracts from the current page only (no pagination — caller handles page navigation).

When --target-url or --project-config is provided, the script will:
  1. Navigate to the target URL before extraction if not already there
  2. Use the target URL for recovery on timeout/bad-page instead of blind refresh

Exit codes:
    0 - Success (candidates extracted or empty results with clear reason)
    1 - Timeout waiting for results to load
    2 - No results found (explicit "no results" state detected)
    3 - Selector mismatch (page loaded but expected elements not found)
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

# Import shared browser utilities
sys.path.insert(0, str(SCRIPT_DIR))
from browser_utils import run_browser_command as _run_browser_command
from browser_utils import format_timeout_error
from recruiter_page_utils import RecoveryHelper, PageStateProbe, ensure_page_ready


# Loading state detection patterns
LOADING_TEXT_PATTERNS = [
    "loading search results",
    "loading",
    "please wait",
]

NO_RESULTS_TEXT_PATTERNS = [
    "no results found",
    "no candidates found",
    "0 results",
    "zero results",
    "we couldn't find any",
    "try adjusting your search",
]


def read_cdp_port() -> str:
    """Read CDP_PORT from the global profile config.

    Uses RuntimeManager for consistent profile resolution.
    """
    # Import here to avoid circular imports at module load time
    from runtime_manager import RuntimeManager

    manager = RuntimeManager()
    profile = manager._resolve_profile()
    return profile.get("CDP_PORT", "9230")


def parse_config_file(config_path: str) -> dict[str, str]:
    """Parse a shell config file and extract key-value pairs.

    Handles simple VAR="value" or VAR='value' syntax.
    Returns a dict of config values.
    """
    config: dict[str, str] = {}
    path = Path(config_path)
    if not path.exists():
        return config

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Match VAR="value" or VAR='value' patterns
        match = re.match(r'^([A-Z_]+)=\s*["\'](.+?)["\']\s*$', line)
        if match:
            config[match.group(1)] = match.group(2)
        # Also match VAR=value (unquoted)
        match_unquoted = re.match(r"^([A-Z_]+)=([^\s#]+)", line)
        if match_unquoted and match_unquoted.group(1) not in config:
            config[match_unquoted.group(1)] = match_unquoted.group(2)

    return config


def resolve_target_url(args: argparse.Namespace) -> str | None:
    """Resolve target URL from command line args or config file.

    Priority:
    1. --target-url argument
    2. RECRUITER_PROJECT_URL from --project-config file
    """
    if args.target_url:
        return args.target_url

    if args.project_config:
        config = parse_config_file(args.project_config)
        return config.get("RECRUITER_PROJECT_URL")

    return None


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    Supports both new-style (--target-url, --project-config) and
    legacy-style (positional cdp_port) invocation for backward compatibility.
    """
    parser = argparse.ArgumentParser(
        description="Extract candidate data from LinkedIn Recruiter search results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 extract_candidates.py                    # Use default CDP port from profile
  python3 extract_candidates.py 9235               # Use specific CDP port
  python3 extract_candidates.py --target-url "https://..." 9235
  python3 extract_candidates.py --project-config /path/to/config.sh
        """,
    )

    parser.add_argument(
        "--target-url",
        dest="target_url",
        help="LinkedIn Recruiter project/search URL to extract from",
    )

    parser.add_argument(
        "--project-config",
        dest="project_config",
        help="Path to config.sh file containing RECRUITER_PROJECT_URL",
    )

    # Positional argument for backward compatibility
    parser.add_argument(
        "cdp_port_positional",
        nargs="?",
        help=argparse.SUPPRESS,  # Hidden from help, still works
    )

    args = parser.parse_args()

    # Handle backward compatibility: if cdp_port_positional provided, use it
    if args.cdp_port_positional:
        args.cdp_port = args.cdp_port_positional
    else:
        args.cdp_port = read_cdp_port()

    return args


def build_agent_browser_command(cdp_port: str) -> list[str]:
    """Build the base agent-browser command with CDP port."""
    return ["agent-browser", "--cdp", cdp_port]


def run_browser_command(cdp_port: str, *args: str) -> dict:
    """Run an agent-browser command and return parsed result.

    This wrapper uses the shared browser_utils helper for consistent
    timeout handling and dialog detection across all browser operations.

    Returns dict with:
        - stdout: raw stdout string
        - stderr: raw stderr string
        - returncode: process return code
        - parsed: parsed JSON if stdout was valid JSON, else None
        - error: error message if command failed
        - dialog_info: dialog status if timeout occurred
        - timed_out: whether the command timed out
    """
    result = _run_browser_command(cdp_port, *args, timeout=30)

    # Return format compatible with existing code, plus new fields
    return {
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "returncode": result.get("returncode", -1),
        "parsed": result.get("parsed"),
        "error": result.get("error"),
        "dialog_info": result.get("dialog_info"),
        "timed_out": result.get("timed_out", False),
    }


def detect_page_state_js() -> str:
    """Generate JavaScript to detect the current page state.

    Returns a JS snippet that evaluates to an object with:
        - state: 'loading' | 'no_results' | 'ready' | 'unknown'
        - hasCandidates: boolean (whether candidate selectors found)
        - candidateCount: number (how many candidate cards found)
        - loadingText: string | null (detected loading text)
        - noResultsText: string | null (detected no-results text)
        - hasLoadingOverlay: boolean (whether loading overlay DOM element found)
        - bodyText: string (first 500 chars of body text for debugging)
    """
    loading_patterns = json.dumps(LOADING_TEXT_PATTERNS)
    no_results_patterns = json.dumps(NO_RESULTS_TEXT_PATTERNS)

    return f"""
(() => {{
  const bodyText = document.body ? document.body.innerText.toLowerCase() : '';
  const bodyPreview = bodyText.substring(0, 500);

  // Check for loading indicators (text patterns)
  const loadingPatterns = {loading_patterns};
  let loadingText = null;
  for (const pattern of loadingPatterns) {{
    if (bodyText.includes(pattern)) {{
      loadingText = pattern;
      break;
    }}
  }}

  // Check for loading overlay DOM elements
  const loadingOverlaySelectors = [
    '.loading-overlay',
    '.loading-overlay__wrapper',
    '.screen-loader__content',
    '[class*="loading-overlay"]',
    '[class*="screen-loader"]'
  ];
  let hasLoadingOverlay = false;
  let loadingOverlaySelector = null;
  for (const selector of loadingOverlaySelectors) {{
    const el = document.querySelector(selector);
    if (el) {{
      hasLoadingOverlay = true;
      loadingOverlaySelector = selector;
      break;
    }}
  }}

  // Check for explicit no-results messages
  const noResultsPatterns = {no_results_patterns};
  let noResultsText = null;
  for (const pattern of noResultsPatterns) {{
    if (bodyText.includes(pattern)) {{
      noResultsText = pattern;
      break;
    }}
  }}

  // Check for candidate cards
  const candidates = document.querySelectorAll('li.profile-list__border-bottom');
  const hasCandidates = candidates.length > 0;
  const candidateCount = candidates.length;

  // Also check for profile links as secondary indicator
  const profileLinks = document.querySelectorAll('a[href*="/talent/profile/"]');
  const hasProfileLinks = profileLinks.length > 0;

  // Determine state
  let state = 'unknown';
  if (hasCandidates || hasProfileLinks) {{
    state = 'ready';
  }} else if (noResultsText) {{
    state = 'no_results';
  }} else if (loadingText || hasLoadingOverlay) {{
    state = 'loading';
  }}

  return {{
    state,
    hasCandidates,
    candidateCount,
    hasProfileLinks,
    profileLinkCount: profileLinks.length,
    loadingText,
    noResultsText,
    hasLoadingOverlay,
    loadingOverlaySelector,
    bodyText: bodyPreview
  }};
}})()
""".strip()


def wait_for_search_results(
    cdp_port: str,
    max_wait_seconds: float = 15.0,
    poll_interval_seconds: float = 0.5,
    work_dir: str | None = None,
    attempt_recovery_on_timeout: bool = True,
    target_url: str | None = None,
) -> dict:
    """Wait for search results to load with improved state detection and recovery.

    Polls the page state until either:
        - Results are ready (candidates found)
        - Explicit no-results state detected
        - Timeout reached (with optional recovery attempt)

    Args:
        cdp_port: Chrome DevTools Protocol port number
        max_wait_seconds: Maximum time to wait for results
        poll_interval_seconds: Interval between polls
        work_dir: Optional working directory for incident reporting
        attempt_recovery_on_timeout: Whether to attempt recovery on timeout

    Returns dict with:
        - status: 'ready' | 'no_results' | 'timeout' | 'error' | 'recovered'
        - state: the last detected page state
        - waited_seconds: how long we waited
        - message: human-readable status message
        - details: full state detection result
        - recovery_result: dict | None - recovery result if attempted
    """
    import time

    start_time = time.time()
    iterations = 0
    last_state = None
    state_info = None

    while True:
        elapsed = time.time() - start_time
        iterations += 1

        if elapsed >= max_wait_seconds:
            # Check for dialog on timeout
            from browser_utils import check_dialog_status

            dialog_info = check_dialog_status(cdp_port)

            # Check if recovery is possible and enabled
            if attempt_recovery_on_timeout and not dialog_info.get("has_dialog"):
                # Attempt recovery for loading timeouts
                probe = PageStateProbe(cdp_port)
                current_state = probe.classify_state()

                if current_state["state"] in ("loading", "unknown", "bad_page"):
                    recovery = RecoveryHelper(cdp_port, work_dir)
                    recovery_result = recovery.attempt_recovery(
                        context="wait_for_search_results",
                        target_url=target_url,  # Use target URL for recovery if available
                    )

                    if recovery_result["success"]:
                        # Recovery succeeded - check state again
                        check_result = run_browser_command(
                            cdp_port, "eval", detect_page_state_js()
                        )
                        if check_result.get("parsed"):
                            recovered_state = check_result["parsed"]
                            if recovered_state.get("state") == "ready":
                                return {
                                    "status": "recovered",
                                    "state": "ready",
                                    "waited_seconds": time.time() - start_time,
                                    "message": f"Search results ready after recovery ({recovered_state.get('candidateCount', 0)} candidates)",
                                    "details": recovered_state,
                                    "recovery_result": recovery_result,
                                }
                            elif recovered_state.get("state") == "no_results":
                                return {
                                    "status": "no_results",
                                    "state": "no_results",
                                    "waited_seconds": time.time() - start_time,
                                    "message": f"No results after recovery: '{recovered_state.get('noResultsText')}'",
                                    "details": recovered_state,
                                    "recovery_result": recovery_result,
                                }

                    # Recovery failed - return timeout with recovery info
                    message = (
                        f"Timeout after {elapsed:.1f}s; recovery attempted but failed"
                    )
                    return {
                        "status": "timeout",
                        "state": current_state.get("state", "unknown"),
                        "waited_seconds": elapsed,
                        "message": message,
                        "details": state_info if state_info else None,
                        "dialog_info": dialog_info,
                        "recovery_result": recovery_result,
                    }

            message = f"Timeout after {elapsed:.1f}s waiting for search results"
            if dialog_info.get("has_dialog"):
                dialog_type = dialog_info.get("dialog_type", "unknown")
                dialog_msg = dialog_info.get("message", "")
                message += (
                    f"; {dialog_type} dialog may be blocking progress"
                    f"{f': {dialog_msg}' if dialog_msg else ''}"
                )

            return {
                "status": "timeout",
                "state": last_state or "unknown",
                "waited_seconds": elapsed,
                "message": message,
                "details": state_info if state_info else None,
                "dialog_info": dialog_info,
                "recovery_result": None,
            }

        result = run_browser_command(cdp_port, "eval", detect_page_state_js())

        if result["error"]:
            return {
                "status": "error",
                "state": "error",
                "waited_seconds": elapsed,
                "message": f"Browser command failed: {result['error']}",
                "details": result,
                "recovery_result": None,
            }

        state_info = result.get("parsed", {})
        last_state = state_info.get("state", "unknown")

        if state_info.get("state") == "ready":
            return {
                "status": "ready",
                "state": "ready",
                "waited_seconds": elapsed,
                "message": f"Search results ready after {elapsed:.1f}s ({state_info.get('candidateCount', 0)} candidates)",
                "details": state_info,
                "recovery_result": None,
            }

        if state_info.get("state") == "no_results":
            return {
                "status": "no_results",
                "state": "no_results",
                "waited_seconds": elapsed,
                "message": f"No results detected after {elapsed:.1f}s: '{state_info.get('noResultsText')}'",
                "details": state_info,
                "recovery_result": None,
            }

        # Still loading or unknown - wait and retry
        time.sleep(poll_interval_seconds)


def scroll_to_load_candidates_js() -> str:
    """Generate JavaScript to scroll and trigger lazy loading of candidate cards."""
    return """
(async () => {
  for (let pass = 0; pass < 3; pass++) {
    scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 200));
    const h = document.body.scrollHeight;
    for (let pos = 0; pos < h; pos += 400) {
      scrollTo(0, pos);
      await new Promise(r => setTimeout(r, 200));
    }
    scrollTo(0, h);
    await new Promise(r => setTimeout(r, 500));
  }
  return document.querySelectorAll('li.profile-list__border-bottom a[href*="/talent/profile/"]').length;
})()
""".strip()


def extract_candidates_js() -> str:
    """Generate JavaScript to extract candidate data from the page.

    Extracts name, title, company, headline, location, and profile URL from each card.
    Uses li.profile-list__border-bottom as card selector and section.lockup for header info.
    """
    return r"""
JSON.stringify(
  Array.from(document.querySelectorAll('li.profile-list__border-bottom'))
    .map(c => {
      const article = c.querySelector('article article') || c.querySelector('article');
      if (!article) return null;
      const nameEl = article.querySelector('a[href*="/talent/profile/"]');
      if (!nameEl) return null;
      const name = nameEl.textContent.trim();
      const url = nameEl.href.split('?')[0];

      // Header section: headline + location
      const lockup = article.querySelector('section.lockup') || nameEl.closest('section');
      let headline = '', location = '';
      if (lockup) {
        const lines = lockup.innerText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        for (const line of lines) {
          if (line === name) continue;
          if (line.includes('degree connection')) continue;
          if (/^·\s*(1st|2nd|3rd)$/.test(line)) continue;
          if (!headline && line.length > 10 && !/^[A-Z][a-z].*·/.test(line)) { headline = line; continue; }
          if (!location && line.includes('·') && line.length > 5) { location = line; continue; }
        }
      }

      // First experience entry: title + company
      let title = '', company = '';
      for (const li of article.querySelectorAll('li')) {
        const txt = li.textContent.trim();
        if (txt.includes(' at ')) {
          const parts = txt.split(' at ');
          title = parts[0].trim();
          company = parts.slice(1).join(' at ').split(/[·\n]/)[0].trim();
          break;
        }
      }

      return { name, url, title, company, headline: headline.substring(0, 200), location };
    })
    .filter(Boolean)
)
""".strip()


def parse_extraction_output(output: str) -> list[dict]:
    """Parse the output from candidate extraction JavaScript.

    Handles double-encoded JSON from agent-browser.
    Returns empty list if parsing fails.
    """
    if not output or output == "null" or output == '"null"':
        return []

    try:
        parsed = json.loads(output)
        # If parsed is a string, it was double-encoded (JSON.stringify + agent-browser quoting)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        if isinstance(parsed, list):
            return parsed
        return []
    except json.JSONDecodeError:
        return []


def verify_target_url_match(
    cdp_port: str,
    target_url: str,
    context: str = "target_url_verification",
) -> dict[str, Any]:
    """Verify that the current URL matches the intended target URL.

    Allows benign query parameter variations (e.g., ?projectId=123 vs ?projectId=123&tab=search).

    Args:
        cdp_port: Chrome DevTools Protocol port number
        target_url: The expected target URL
        context: Context string for error messages

    Returns:
        Dict with:
            - matches: bool - whether current URL matches target
            - current_url: str - the actual current URL
            - target_url: str - the expected target URL
            - error: str | None - error message if mismatch
    """
    from recruiter_page_utils import (
        normalize_url_for_comparison,
        assert_page_identity,
    )

    # Get current URL
    result = run_browser_command(cdp_port, "eval", "({ url: window.location.href })")

    if result.get("error"):
        return {
            "matches": False,
            "current_url": "",
            "target_url": target_url,
            "error": f"{context}: Failed to get current URL: {result['error']}",
        }

    current_url = ""
    if result.get("parsed"):
        current_url = result["parsed"].get("url", "")
    else:
        # Try to parse from stdout
        try:
            parsed = json.loads(result.get("stdout", "{}"))
            current_url = parsed.get("url", "")
        except json.JSONDecodeError:
            pass

    if not current_url:
        return {
            "matches": False,
            "current_url": "",
            "target_url": target_url,
            "error": f"{context}: Could not determine current URL",
        }

    # Normalize URLs for comparison (remove query params and fragments)
    normalized_current = normalize_url_for_comparison(current_url)
    normalized_target = normalize_url_for_comparison(target_url)

    # Validate target URL is from LinkedIn before any matching
    from urllib.parse import urlparse

    target_parsed = urlparse(target_url)
    target_host = target_parsed.hostname or ""
    target_is_linkedin = target_host == "linkedin.com" or target_host.endswith(
        ".linkedin.com"
    )

    if not target_is_linkedin:
        return {
            "matches": False,
            "current_url": current_url,
            "target_url": target_url,
            "error": (
                f"{context}: Target URL '{target_url}' is not a valid LinkedIn URL. "
                f"Only linkedin.com and *.linkedin.com domains are allowed."
            ),
        }

    # Check for exact path match (both URLs already validated as LinkedIn)
    if normalized_current == normalized_target:
        return {
            "matches": True,
            "current_url": current_url,
            "target_url": target_url,
            "error": None,
        }

    # Check if we're at least on a valid talent page
    if "/talent/" not in current_url:
        return {
            "matches": False,
            "current_url": current_url,
            "target_url": target_url,
            "error": (
                f"{context}: Current URL '{current_url}' is not a LinkedIn Talent page. "
                f"Expected to be on: {target_url}"
            ),
        }

    # Partial match - we're on a talent page but not the exact target
    # This could be acceptable if we're on a derived search URL from the target project
    if "/talent/hire/" in current_url and "/talent/hire/" in target_url:
        # Extract project IDs
        import re

        # Validate current URL is from LinkedIn domain before same-project fallback
        # (target URL was already validated at the start of this function)
        current_parsed = urlparse(current_url)
        current_host = current_parsed.hostname or ""
        current_is_linkedin = current_host == "linkedin.com" or current_host.endswith(
            ".linkedin.com"
        )

        if current_is_linkedin:
            # Match /talent/hire/{numeric_id} followed by /, ?, #, or end of string
            # This accepts URLs with or without trailing slash
            current_match = re.search(r"/talent/hire/(\d+)(?:/|$|\?|#)", current_url)
            target_match = re.search(r"/talent/hire/(\d+)(?:/|$|\?|#)", target_url)

            if current_match and target_match:
                current_project_id = current_match.group(1)
                target_project_id = target_match.group(1)

                if current_project_id == target_project_id:
                    # Same project, different view - this is acceptable
                    return {
                        "matches": True,
                        "current_url": current_url,
                        "target_url": target_url,
                        "error": None,
                    }

    return {
        "matches": False,
        "current_url": current_url,
        "target_url": target_url,
        "error": (
            f"{context}: URL mismatch. "
            f"Current: '{current_url}', Expected: '{target_url}'"
        ),
    }


def extract_candidates(
    cdp_port: str,
    work_dir: str | None = None,
    target_url: str | None = None,
) -> dict:
    """Main extraction workflow.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        work_dir: Optional working directory for incident reporting
        target_url: Optional LinkedIn Recruiter URL to ensure we're on before extraction

    Returns dict with:
        - success: boolean
        - candidates: list of candidate dicts (empty if none found)
        - message: human-readable status
        - exit_code: appropriate exit code for the result
    """
    # Step 0: If target URL provided, ensure we're on the correct page
    if target_url:
        ensure_result = ensure_page_ready(
            cdp_port=cdp_port,
            work_dir=work_dir,
            target_url=target_url,
            context="extract_candidates_initial",
        )
        if not ensure_result["ready"]:
            return {
                "success": False,
                "candidates": [],
                "message": f"Failed to reach target URL: {ensure_result['state']}",
                "exit_code": 1,
            }

        # Verify we're actually on the target URL (or a valid project page derived from it)
        url_verification = verify_target_url_match(cdp_port, target_url)
        if not url_verification["matches"]:
            return {
                "success": False,
                "candidates": [],
                "message": url_verification["error"],
                "exit_code": 1,
            }

    # Step 1: Wait for search results with improved state detection and recovery
    wait_result = wait_for_search_results(
        cdp_port, work_dir=work_dir, target_url=target_url
    )

    if wait_result["status"] == "error":
        return {
            "success": False,
            "candidates": [],
            "message": wait_result["message"],
            "exit_code": 1,
        }

    if wait_result["status"] == "timeout":
        details = wait_result.get("details", {})
        body_preview = details.get("bodyText", "")[:200] if details else ""
        dialog_info = wait_result.get("dialog_info", {})

        # Check if we have profile links but no candidate cards (selector mismatch)
        if (
            details
            and details.get("hasProfileLinks")
            and not details.get("hasCandidates")
        ):
            message = (
                f"Selector mismatch: Found {details.get('profileLinkCount', 0)} profile links "
                f"but no candidate cards. Page structure may have changed. "
            )
            if dialog_info and dialog_info.get("has_dialog"):
                dialog_type = dialog_info.get("dialog_type", "unknown")
                message += f"A {dialog_type} dialog may also be blocking progress. "
            message += f"Body preview: {body_preview}..."

            return {
                "success": False,
                "candidates": [],
                "message": message,
                "exit_code": 3,
            }

        message = (
            f"Timeout waiting for search results after {wait_result['waited_seconds']:.1f}s. "
            f"Last state: {wait_result['state']}. "
        )
        if dialog_info and dialog_info.get("has_dialog"):
            dialog_type = dialog_info.get("dialog_type", "unknown")
            dialog_msg = dialog_info.get("message", "")
            message += f"A {dialog_type} dialog may be blocking progress"
            if dialog_msg:
                message += f": '{dialog_msg}'"
            message += ". "
        message += f"Body preview: {body_preview}..."

        return {
            "success": False,
            "candidates": [],
            "message": message,
            "exit_code": 1,
        }

    if wait_result["status"] == "no_results":
        return {
            "success": False,
            "candidates": [],
            "message": f"No results found: {wait_result['details'].get('noResultsText', 'search returned empty')}",
            "exit_code": 2,
        }

    # Step 2: Scroll to trigger lazy rendering
    scroll_result = run_browser_command(
        cdp_port, "eval", scroll_to_load_candidates_js()
    )
    if scroll_result["error"]:
        # Non-fatal: continue with extraction anyway
        pass

    # Step 3: Extract candidates
    extract_result = run_browser_command(cdp_port, "eval", extract_candidates_js())

    if extract_result["error"]:
        return {
            "success": False,
            "candidates": [],
            "message": f"Extraction failed: {extract_result['error']}",
            "exit_code": 3,
        }

    candidates = parse_extraction_output(extract_result.get("stdout", ""))

    if not candidates:
        # Page said ready but extraction returned nothing - selector mismatch
        details = wait_result.get("details", {})
        return {
            "success": False,
            "candidates": [],
            "message": (
                f"Page loaded but no candidates extracted. "
                f"Expected {details.get('candidateCount', 0)} cards but extraction returned empty. "
                f"Selectors may need updating."
            ),
            "exit_code": 3,
        }

    return {
        "success": True,
        "candidates": candidates,
        "message": f"Extracted {len(candidates)} candidates",
        "exit_code": 0,
    }


def main() -> int:
    """Main entry point."""
    args = parse_arguments()
    cdp_port = args.cdp_port

    # Resolve work_dir from RuntimeManager for consistent profile handling
    from runtime_manager import RuntimeManager

    manager = RuntimeManager()
    profile = manager._resolve_profile()
    work_dir = profile.get("WORK_DIR")

    # Resolve target URL from arguments
    target_url = resolve_target_url(args)

    result = extract_candidates(cdp_port, work_dir=work_dir, target_url=target_url)

    # Always output candidates as JSON to stdout
    print(json.dumps(result["candidates"]))

    # Output status message to stderr for operator visibility
    if not result["success"] or result["exit_code"] != 0:
        print(result["message"], file=sys.stderr)

    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
