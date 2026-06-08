#!/usr/bin/env python3
"""Create Search phase runner for LinkedIn sourcing (internal/advanced use only).

This script is used internally by the reachout loop. For normal workflow,
use the loop command which handles phase sequencing automatically:
    python3 scripts/run_reachout_loop.py --project <PROJECT_ID>

This phase produces a compact search brief from project config + JD, builds a
Copilot query for manual search creation, and stores them in project state.
The user manually creates the search in Recruiter using the provided query,
then runs --confirm-search to proceed.

Exit codes:
    0 - Search brief and Copilot query generated successfully
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
    "confirm_search",
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
        from config_utils import parse_config_file
        from project_ref_utils import resolve_project_ref

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


def _is_tiktok_jd(jd_text: str, jd_url: str = "") -> bool:
    """Detect if JD is from TikTok/ByteDance based on URL or content.

    Args:
        jd_text: Job description text content
        jd_url: Job description URL if available

    Returns:
        True if JD appears to be from TikTok/ByteDance hiring site
    """
    url_lower = (jd_url or "").lower()
    text_lower = (jd_text or "").lower()

    # Check URL patterns
    if any(
        domain in url_lower
        for domain in ["lifeattiktok.com", "tiktok.com", "bytedance.com"]
    ):
        return True

    # Check content patterns - be more lenient to catch JDs that mention
    # ByteDance/TikTok without specific URL patterns
    url_patterns = ["lifeattiktok", "tiktok.com/careers", "bytedance.com"]
    company_patterns = ["bytedance", "tiktok"]
    if any(pattern in text_lower for pattern in url_patterns + company_patterns):
        return True

    return False


def _detect_hiring_company(
    config: dict[str, str], jd_text: str = "", jd_url: str = ""
) -> str | None:
    """Detect the hiring company from config or JD context.

    Priority:
    1. Explicit HIRING_COMPANY config field
    2. JD URL/content detection (TikTok/ByteDance)
    3. None (unknown)

    Returns:
        Lowercase hiring company name or None
    """
    # 1. Explicit config override
    hiring_company = config.get("HIRING_COMPANY", "").strip()
    if hiring_company:
        return hiring_company.lower()

    # 2. Detect from JD
    if _is_tiktok_jd(jd_text, jd_url):
        return "tiktok"  # Use tiktok as canonical; aliases cover ByteDance too

    return None


def _get_hiring_company_aliases(company_name: str) -> set[str]:
    """Get known aliases for a hiring company.

    Args:
        company_name: Primary company name

    Returns:
        Set of lowercase aliases for the company
    """
    aliases = {
        "tiktok": {"tiktok", "byte dance", "bytedance", "byte-dance"},
        "bytedance": {"bytedance", "byte dance", "byte-dance", "tiktok"},
    }
    return aliases.get(company_name.lower(), {company_name.lower()})


def _company_matches_alias(company: str, aliases: set[str]) -> bool:
    """Check if a company name matches any alias (handles variations like 'Inc.', 'Ltd.', etc.).

    Uses exact normalized matching and word-boundary substring matching to be robust
    without over-excluding unrelated names.
    """
    import re

    company_lower = company.lower().strip()
    company_normalized = company_lower.replace(" ", "").replace("-", "")

    for alias in aliases:
        alias_normalized = alias.replace(" ", "").replace("-", "")
        # Exact normalized match
        if company_normalized == alias_normalized:
            return True
        # Word-boundary match: alias is a distinct word in company name
        # e.g., "ByteDance" in "ByteDance Inc." or "TikTok" in "TikTok Pte. Ltd."
        # but NOT "TikTok" in "TikTokAnalytics"
        if re.search(r"\b" + re.escape(alias) + r"\b", company_lower):
            return True
        # Reverse: company is a distinct word in alias (less common)
        if re.search(r"\b" + re.escape(company_lower) + r"\b", alias):
            return True

    return False


def get_effective_target_companies(
    config: dict[str, str], jd_text: str = "", jd_url: str = ""
) -> list[str]:
    """Compute effective target companies, excluding the hiring company.

    For JDs where the hiring company is detected (e.g., TikTok/ByteDance),
    excludes the hiring company and its aliases from the target company list
    since those are the hiring company, not targets.

    Args:
        config: Project configuration dict
        jd_text: Job description text for context
        jd_url: Job description URL for context

    Returns:
        List of effective target company names (preserving original case from config)
    """
    companies_str = config.get("COMPANIES", "")
    if not companies_str:
        return []

    all_companies = _split_csv(companies_str)

    # Detect hiring company
    hiring_company = _detect_hiring_company(config, jd_text, jd_url)
    if not hiring_company:
        return all_companies

    # Get all aliases for the hiring company to exclude
    excluded_aliases = _get_hiring_company_aliases(hiring_company)

    # Filter out hiring company and its aliases
    effective = []
    for company in all_companies:
        if not _company_matches_alias(company, excluded_aliases):
            effective.append(company)

    return effective


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


def build_search_brief(config: dict[str, str], jd_text: str, jd_url: str = "") -> str:
    """Build a compact natural-language search brief for Recruiter.

    Args:
        config: Project configuration dict
        jd_text: Job description text for context
        jd_url: Optional job description URL for hiring company detection

    Returns:
        Compact natural-language search brief
    """
    title = config.get("POSITION_TITLE", "")
    team = config.get("TEAM_NAME", "")
    location = config.get("LOCATION", "")
    keywords = _split_csv(config.get("KEYWORDS", ""))
    # Use effective target companies (excludes hiring company for TikTok/ByteDance JDs)
    companies = get_effective_target_companies(config, jd_text, jd_url)
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
            "Search for candidates relevant to this project, then review titles, companies, locations, and exclusions in Recruiter"
        )

    return "\n".join(lines)


def build_copilot_search_query(
    config: dict[str, str],
    jd_text: str = "",
    jd_url: str = "",
) -> str:
    """Build a comprehensive natural-language query for LinkedIn Recruiter AI Copilot.

    The query instructs Copilot to create search filters (not just a text response)
    using the project configuration fields.
    """
    title = config.get("POSITION_TITLE", "").strip()
    location = config.get("LOCATION", "").strip()
    keywords = _split_csv(config.get("KEYWORDS", ""))
    companies = get_effective_target_companies(config, jd_text, jd_url)
    exclude_titles = _split_csv(config.get("EXCLUDE_TITLES", ""))

    lines = [
        "Create a LinkedIn Recruiter candidate search for this hiring project.",
        "Use Recruiter search filters, not just a text response.",
    ]

    if title:
        lines.append(
            f"Job title filter: target candidates with current or recent titles matching or closely related to: {title}."
        )

    if location:
        lines.append(f"Location filter: prioritize candidates in or near: {location}.")

    if companies:
        lines.append(
            "Company filter: prioritize candidates who currently or previously worked at these companies: "
            + ", ".join(companies[:15])
            + "."
        )

    if keywords:
        lines.append(
            "Skills/keywords filter: include candidates with experience in: "
            + ", ".join(keywords[:20])
            + "."
        )

    if exclude_titles:
        lines.append(
            "Exclusion filter: exclude candidates whose current title contains: "
            + ", ".join(exclude_titles[:15])
            + "."
        )

    lines.append(
        "After creating the search, show matching candidate results and keep the filters visible for review."
    )

    return "\n".join(lines)


def build_action_required(
    recruiter_url: str,
    search_brief: str,
    copilot_query: str = "",
) -> dict[str, Any]:
    """Build agent-actionable search-creation instructions."""
    context: dict[str, Any] = {
        "recruiter_url": recruiter_url,
        "search_brief": search_brief,
    }
    if copilot_query:
        context["copilot_query"] = copilot_query

    steps = [
        "Open the Recruiter project search page in Chrome",
        "Copy the ready-made query from context.copilot_query",
        "Paste it into the Copilot input and press Enter",
        "Wait for Copilot to generate the search, then review and adjust titles, companies, locations, and exclusions",
        "Confirm candidate cards or a real results count are visible",
        "After the search is ready, run the loop with --confirm-search to proceed",
    ]

    return {
        "code": "search_not_configured",
        "summary": "Create the candidate search in LinkedIn Recruiter using the provided Copilot query",
        "message": "Open the Recruiter project in Chrome and use the AI Copilot to create the candidate search",
        "steps": steps,
        "can_retry": True,
        "context": context,
        "actor": "agent",
    }


def run_create_search_phase(project_ref: str) -> dict[str, Any]:
    """Generate search brief and Copilot query for manual search creation."""
    config_path, config, recruiter_project_id = resolve_project(project_ref)
    project_dir = config_path.parent

    recruiter_url = config.get("RECRUITER_PROJECT_URL", "")
    if not recruiter_url:
        raise CreateSearchError("RECRUITER_PROJECT_URL is required")

    jd_text = read_jd_text(config_path)
    jd_url = config.get("JD_URL", "")
    search_brief = build_search_brief(config, jd_text, jd_url)
    copilot_query = build_copilot_search_query(config, jd_text, jd_url)

    # Build action_required for agent to create search manually
    action_req = build_action_required(
        recruiter_url=recruiter_url,
        search_brief=search_brief,
        copilot_query=copilot_query,
    )

    # Update project state
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_state import update_project_state

        update_project_state(
            project_dir=project_dir,
            current_phase="create_search",
            status="completed",
            action_required=False,
            last_result_summary="Copilot query generated; user must create and verify search",
            last_error=False,
            create_search_summary={
                "recruiter_url": recruiter_url,
                "copilot_query": copilot_query,
                "search_brief": search_brief,
            },
        )
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))

    return {
        "success": True,
        "phase": "create_search",
        "workflow_phases": WORKFLOW_PHASES,
        "status": "completed",
        "next_phase": "confirm_search",
        "project_ref": project_ref,
        "config_path": str(config_path),
        "project_id": config.get("PROJECT_ID", ""),
        "recruiter_project_id": recruiter_project_id,
        "recruiter_url": recruiter_url,
        "search_brief": search_brief,
        "copilot_query": copilot_query,
        "message": "Search brief and Copilot query generated. Open Recruiter and create the search.",
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate search brief and Copilot query for manual search creation (internal/advanced use only)"
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project reference (local PROJECT_ID, numeric Recruiter ID, URL, or config path)",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    try:
        result = run_create_search_phase(project_ref=args.project)
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
