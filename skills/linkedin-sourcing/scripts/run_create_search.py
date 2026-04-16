#!/usr/bin/env python3
"""Manual-first Create Search phase runner for LinkedIn sourcing.

This phase does not fully automate LinkedIn Recruiter search creation yet.
Instead, it produces a compact search brief from project config + JD, opens the
Recruiter project, and verifies whether the project is still on the search
creation screen or already has visible candidates.

Agents should use the normal command path first. Preview mode is debug-only.

Exit codes:
    0 - Search is already configured or brief-only preview succeeded
    2 - Manual browser intervention required to create/review the search
    3 - Configuration or setup error
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
# Loop-facing workflow phases (bootstrap is a pre-loop entrypoint)
WORKFLOW_PHASES = [
    "create_search",
    "extract",
    "filter",
    "enrich",
    "draft",
    "review",
    "send",
]


class CreateSearchError(Exception):
    """Raised when create-search setup is invalid."""

    def __init__(self, message: str, exit_code: int = 3):
        super().__init__(message)
        self.exit_code = exit_code


def load_runtime_context() -> dict[str, Any]:
    """Load runtime context via RuntimeManager."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from runtime_manager import RuntimeManager

        manager = RuntimeManager()
        ctx = manager.get_runtime_context()
        if ctx is None:
            ctx = manager.initialize()
        return ctx
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def resolve_project(project_ref: str) -> tuple[Path, dict[str, str], str]:
    """Resolve project reference to config and parsed config."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_ref_utils import resolve_project_ref
        from config_utils import parse_config_file

        resolution = resolve_project_ref(project_ref)
        if not resolution.get("success"):
            raise CreateSearchError(
                resolution.get("error", "Project resolution failed"), exit_code=3
            )

        config_path = resolution.get("config_path")
        if not config_path:
            raise CreateSearchError("Resolved project is missing config_path")

        config = parse_config_file(config_path)
        return Path(config_path), config, resolution.get("recruiter_project_id", "")
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def read_jd_text(config_path: Path) -> str:
    """Read job_description.txt from the project directory if present."""
    jd_path = config_path.parent / "job_description.txt"
    if not jd_path.exists():
        return ""
    try:
        return jd_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _split_csv(value: str) -> list[str]:
    """Split comma-delimited config values into clean tokens."""
    return [item.strip() for item in value.split(",") if item.strip()]


def sanitize_jd_text(jd_text: str) -> str:
    """Normalize JD text, stripping HTML markup and common page chrome noise."""
    if not jd_text:
        return ""

    text = html.unescape(jd_text)

    if re.search(r"<!doctype html|<html\b|<body\b|<div\b|<p\b", text, re.IGNORECASE):
        text = re.sub(
            r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL
        )
        text = re.sub(
            r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL
        )
        text = re.sub(r"<[^>]+>", " ", text)

    text = re.sub(r"\bLifeAtTikTok\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bHow we hire\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bEarly Careers\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLocations\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bJobs\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def build_search_brief(config: dict[str, str], jd_text: str) -> str:
    """Build a compact natural-language search brief for Recruiter."""
    title = config.get("POSITION_TITLE", "")
    team = config.get("TEAM_NAME", "")
    location = config.get("LOCATION", "")
    keywords = _split_csv(config.get("KEYWORDS", ""))
    companies = _split_csv(config.get("COMPANIES", ""))
    exclude_titles = _split_csv(config.get("EXCLUDE_TITLES", ""))

    lines: list[str] = []
    opening_parts = [part for part in [title, team] if part]
    if opening_parts:
        lines.append(f"Search for candidates aligned with: {' - '.join(opening_parts)}")
    if location:
        lines.append(f"Preferred locations: {location}")
    if keywords:
        lines.append(f"Target skills/keywords: {', '.join(keywords[:10])}")
    if companies:
        lines.append(f"Target companies: {', '.join(companies[:10])}")
    if exclude_titles:
        lines.append(f"Exclude titles: {', '.join(exclude_titles[:10])}")

    jd_excerpt = sanitize_jd_text(jd_text)
    if jd_excerpt:
        if len(jd_excerpt) > 900:
            jd_excerpt = jd_excerpt[:900].rstrip() + "..."
        lines.append(f"JD context: {jd_excerpt}")

    if not lines:
        lines.append(
            "Search for candidates relevant to this project, then review titles, companies, locations, and exclusions manually"
        )

    return "\n".join(lines)


def build_action_required(
    recruiter_url: str, search_brief: str, current_url: str | None = None
) -> dict[str, Any]:
    """Build manual search-creation fallback instructions."""
    context = {
        "recruiter_url": recruiter_url,
        "search_brief": search_brief,
    }
    if current_url:
        context["current_url"] = current_url

    return {
        "code": "search_not_configured",
        "summary": "Recruiter project still needs a reviewed candidate search",
        "steps": [
            "Open the Recruiter project search page in Chrome",
            "If Recruiter shows Start a search, choose job description, Boolean search, or profile",
            "Paste the generated search brief from the command output",
            "Review and fix titles, companies, locations, and exclusions",
            "Confirm candidate cards or a real results count are visible",
            "Re-run run_create_search.py to verify the search is ready",
        ],
        "can_retry": True,
        "context": context,
    }


def _extract_project_id_from_url(url: str) -> str | None:
    """Extract the project ID from a LinkedIn Recruiter URL.

    Args:
        url: LinkedIn Recruiter URL (e.g., https://linkedin.com/talent/hire/123/discover/...)

    Returns:
        The project ID string if found, None otherwise
    """
    import re

    # Match patterns like /talent/hire/123456/ or /talent/hire/1234567890/
    match = re.search(r"/talent/hire/(\d+)/", url)
    if match:
        return match.group(1)
    return None


def inspect_search_state(cdp_port: str, recruiter_url: str) -> dict[str, Any]:
    """Open the project search page and inspect whether it is extraction-ready."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import (
            ActionRequired,
            FailureCode,
            classify_browser_readiness,
            run_browser_command,
            safe_get_parsed,
        )
        from recruiter_page_utils import PageStateProbe, ensure_page_ready

        # Extract expected project ID from the target URL for cross-project validation
        expected_project_id = _extract_project_id_from_url(recruiter_url)

        open_result = run_browser_command(cdp_port, "open", recruiter_url, timeout=30)
        if open_result.get("error"):
            readiness = classify_browser_readiness(
                cdp_port, error=open_result.get("error")
            )
            return {
                "success": False,
                "status": "browser_error",
                "failure_code": readiness.action_required.code
                if readiness.action_required
                else FailureCode.AMBIGUOUS_STATE,
                "action_required": readiness.action_required.to_dict()
                if readiness.action_required
                else ActionRequired.ambiguous_state(
                    details=open_result.get("error")
                ).to_dict(),
                "current_url": None,
            }

        ready_result = ensure_page_ready(
            cdp_port=cdp_port,
            target_url=recruiter_url,
            require_page_identity=True,
            context="run_create_search verify recruiter search page",
            max_wait_seconds=20.0,
        )
        if not ready_result.get("ready"):
            return {
                "success": False,
                "status": ready_result.get("state", "unknown"),
                "failure_code": ready_result.get(
                    "failure_code", FailureCode.AMBIGUOUS_STATE
                ),
                "action_required": ready_result.get("action_required"),
                "current_url": ready_result.get("identity_check", {}).get("current_url")
                if ready_result.get("identity_check")
                else None,
            }

        url_result = run_browser_command(
            cdp_port, "eval", "({ url: window.location.href })"
        )
        current_url = safe_get_parsed(url_result, default={}).get("url", recruiter_url)

        # Cross-project validation: ensure current URL matches expected project ID
        if expected_project_id:
            current_project_id = _extract_project_id_from_url(current_url)
            if current_project_id and current_project_id != expected_project_id:
                return {
                    "success": False,
                    "status": "wrong_project",
                    "current_url": current_url,
                    "failure_code": FailureCode.WRONG_PAGE,
                    "action_required": ActionRequired.wrong_page(
                        expected_url=recruiter_url,
                        actual_url=current_url,
                    ).to_dict(),
                }

        probe = PageStateProbe(cdp_port)
        state_result = probe.classify_state()
        state = state_result.get("state", "unknown")
        details = state_result.get("details", {})

        # Require BOTH search results content AND no search creation prompt
        # to confirm the search is truly ready (fixes false-positive gap)
        has_results = details.get("hasSearchResultsContent", False)
        has_creation_prompt = details.get("hasSearchCreationPrompt", False)

        if has_results and not has_creation_prompt:
            return {
                "success": True,
                "status": "ready",
                "current_url": current_url,
                "failure_code": None,
                "action_required": None,
            }

        if has_creation_prompt:
            return {
                "success": False,
                "status": "search_not_configured",
                "current_url": current_url,
                "failure_code": "search_not_configured",
                "action_required": None,
            }

        if state in {
            "dialog_blocked",
            "logged_out_or_wrong_product",
            "blocked_or_captcha",
            "unknown",
        }:
            readiness = classify_browser_readiness(
                cdp_port,
                current_url=current_url,
                error=details.get("error"),
                dialog_info=state_result.get("dialog_info"),
            )
            return {
                "success": False,
                "status": state,
                "current_url": current_url,
                "failure_code": readiness.action_required.code
                if readiness.action_required
                else FailureCode.AMBIGUOUS_STATE,
                "action_required": readiness.action_required.to_dict()
                if readiness.action_required
                else ActionRequired.ambiguous_state(
                    details=f"Browser state: {state}"
                ).to_dict(),
            }

        return {
            "success": False,
            "status": "unverified",
            "current_url": current_url,
            "failure_code": "search_not_configured",
            "action_required": None,
        }
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def run_create_search_phase(
    project_ref: str, cdp_port: str | None = None, brief_only: bool = False
) -> dict[str, Any]:
    """Run the manual-first Create Search phase."""
    ctx = load_runtime_context()
    if cdp_port is None:
        cdp_port = ctx.get("profile", {}).get("CDP_PORT", "9234")

    config_path, config, recruiter_project_id = resolve_project(project_ref)
    project_dir = config_path.parent
    recruiter_url = config.get("RECRUITER_PROJECT_URL", "")
    if not recruiter_url:
        raise CreateSearchError(
            "RECRUITER_PROJECT_URL is required before creating or verifying a search"
        )

    jd_text = read_jd_text(config_path)
    search_brief = build_search_brief(config, jd_text)

    result = {
        "success": True,
        "phase": "create_search",
        "workflow_phases": WORKFLOW_PHASES,
        "status": "brief_only" if brief_only else "ready",
        "next_phase": "create_search" if brief_only else "extract",
        "project_ref": project_ref,
        "config_path": str(config_path),
        "project_id": config.get("PROJECT_ID", ""),
        "recruiter_project_id": recruiter_project_id,
        "recruiter_url": recruiter_url,
        "cdp_port": cdp_port,
        "search_brief": search_brief,
        "message": "",
    }

    if brief_only:
        result["message"] = "Create Search brief preview complete"
        # Update project state for brief-only mode
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            from project_state import update_project_state

            update_project_state(
                project_dir=project_dir,
                current_phase="create_search",
                status="brief_only",
                last_result_summary="Search brief generated (preview mode)",
            )
        finally:
            if str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))
        return result

    inspection = inspect_search_state(cdp_port, recruiter_url)
    result["status"] = inspection.get("status", "unknown")
    result["current_url"] = inspection.get("current_url")
    result["failure_code"] = inspection.get("failure_code")

    # Update project state based on result
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_state import update_project_state

        if inspection.get("success"):
            update_project_state(
                project_dir=project_dir,
                current_phase="create_search",
                status="completed",
                action_required=False,
                last_result_summary="Recruiter search verified with visible candidates",
                last_error=False,
            )
        elif inspection.get("action_required"):
            update_project_state(
                project_dir=project_dir,
                current_phase="create_search",
                status="action_required",
                action_required=inspection["action_required"],
                last_result_summary="Browser intervention required",
            )
        else:
            action_req = build_action_required(
                recruiter_url=recruiter_url,
                search_brief=search_brief,
                current_url=inspection.get("current_url"),
            )
            update_project_state(
                project_dir=project_dir,
                current_phase="create_search",
                status="search_not_configured",
                action_required=action_req,
                last_result_summary="Recruiter search not configured yet",
            )
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))

    if inspection.get("success"):
        result["message"] = "Recruiter search already has visible candidates"
        return result

    if inspection.get("action_required"):
        result["action_required"] = inspection["action_required"]
        result["success"] = False
        result["next_phase"] = "create_search"
        result["message"] = (
            "Browser intervention required before search can be verified"
        )
        return result

    result["success"] = False
    result["next_phase"] = "create_search"
    result["action_required"] = build_action_required(
        recruiter_url=recruiter_url,
        search_brief=search_brief,
        current_url=inspection.get("current_url"),
    )
    result["message"] = (
        "Recruiter search is not configured yet; review filters and ensure candidates are visible"
    )
    return result


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Create or verify a Recruiter search")
    parser.add_argument(
        "--project",
        required=True,
        help="Project reference (local PROJECT_ID, numeric Recruiter ID, URL, or config path)",
    )
    parser.add_argument(
        "--cdp-port",
        default=None,
        help="Chrome DevTools Protocol port (default: from profile or 9234)",
    )
    parser.add_argument(
        "--brief-only",
        action="store_true",
        help="Print the generated search brief without opening Recruiter (debug only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    try:
        result = run_create_search_phase(
            project_ref=args.project,
            cdp_port=args.cdp_port,
            brief_only=(args.brief_only or args.dry_run),
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("success") else 2
    except CreateSearchError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "message": str(exc),
                },
                indent=2,
            )
        )
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
