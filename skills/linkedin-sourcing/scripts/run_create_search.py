#!/usr/bin/env python3
"""Create Search phase runner for LinkedIn sourcing (internal/advanced use only).

This script is used internally by the reachout loop. For normal workflow,
use the loop command which handles phase sequencing automatically:
    python3 scripts/run_reachout_loop.py --project <PROJECT_ID>

This phase produces a compact search brief from project config + JD, opens the
Recruiter project, and verifies whether the project is still on the search
creation screen or already has visible candidates.

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
    if any(domain in url_lower for domain in ["lifeattiktok.com", "tiktok.com", "bytedance.com"]):
        return True

    # Check content patterns - be more lenient to catch JDs that mention
    # ByteDance/TikTok without specific URL patterns
    url_patterns = ["lifeattiktok", "tiktok.com/careers", "bytedance.com"]
    company_patterns = ["bytedance", "tiktok"]
    if any(pattern in text_lower for pattern in url_patterns + company_patterns):
        return True

    return False


def _detect_hiring_company(config: dict[str, str], jd_text: str = "", jd_url: str = "") -> str | None:
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

    Uses both exact normalized matching and substring matching to be robust
    without over-excluding unrelated names.
    """
    company_lower = company.lower().strip()
    company_normalized = company_lower.replace(" ", "").replace("-", "")

    for alias in aliases:
        alias_normalized = alias.replace(" ", "").replace("-", "")
        # Exact normalized match
        if company_normalized == alias_normalized:
            return True
        # Substring match: alias is a distinct word in company name
        # e.g., "ByteDance" in "ByteDance Inc." or "TikTok" in "TikTok Pte. Ltd."
        if alias in company_lower:
            return True
        # Reverse: company is a distinct word in alias (less common)
        if company_lower in alias:
            return True

    return False


def get_effective_target_companies(config: dict[str, str], jd_text: str = "", jd_url: str = "") -> list[str]:
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
    recruiter_url: str, search_brief: str, current_url: str | None = None
) -> dict[str, Any]:
    """Build agent-actionable search-creation instructions."""
    context = {
        "recruiter_url": recruiter_url,
        "search_brief": search_brief,
    }
    if current_url:
        context["current_url"] = current_url

    return {
        "code": "search_not_configured",
        "summary": "The Recruiter project needs a candidate search configured",
        "message": "Open the Recruiter project in Chrome and create the candidate search using the provided search brief",
        "steps": [
            "Open the Recruiter project search page in Chrome",
            "If Recruiter shows 'Start a search', choose job description, Boolean search, or profile",
            "Use the search brief provided in context.search_brief",
            "Review and adjust titles, companies, locations, and exclusions",
            "Confirm candidate cards or a real results count are visible",
            "After the search is ready, Re-run the loop to continue",
        ],
        "can_retry": True,
        "context": context,
        "actor": "agent",
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


def _enrich_browser_unavailable_blocker(
    action_required: dict[str, Any],
    cdp_port: str,
    work_dir: Path | None,
    chrome_profile: Path | str | None = None,
) -> dict[str, Any]:
    """Enrich a browser_unavailable blocker with recovery details.

    Args:
        action_required: The original action_required dict
        cdp_port: CDP port for connection
        work_dir: Working directory for paths (from runtime context)
        chrome_profile: Chrome profile path (from runtime context, optional)

    Returns:
        Enriched action_required dict with recovery context
    """
    if action_required.get("code") != "browser_unavailable":
        return action_required

    # Already has recovery_command - no need to enrich
    if action_required.get("context", {}).get("recovery_command"):
        return action_required

    from browser_utils import CONNECT_BROWSER_SCRIPT

    # Use provided work_dir from runtime context, never fall back to SCRIPT_DIR.parent.parent
    resolved_work_dir = Path(work_dir) if work_dir else Path.home() / "Desktop" / "linkedin-sourcing"

    # Use provided chrome_profile from runtime context, or default to $WORK_DIR/chrome-profile
    if chrome_profile:
        if isinstance(chrome_profile, str):
            chrome_profile = chrome_profile.replace("$WORK_DIR", str(resolved_work_dir))
            chrome_profile = chrome_profile.replace("${WORK_DIR}", str(resolved_work_dir))
            chrome_profile = Path(chrome_profile).expanduser()
        resolved_chrome_profile = Path(chrome_profile)
    else:
        resolved_chrome_profile = resolved_work_dir / "chrome-profile"

    # Build enriched context
    context = action_required.get("context", {})
    context.update({
        "work_dir": str(resolved_work_dir),
        "cdp_port": cdp_port,
        "chrome_profile": str(resolved_chrome_profile),
        "connect_browser_script": str(CONNECT_BROWSER_SCRIPT),
        "recovery_command": f'bash "{CONNECT_BROWSER_SCRIPT}"',
        "agent_browser_command": f"agent-browser --cdp {cdp_port} get url",
    })

    # Build enriched steps
    steps = [
        f"Ensure Chrome is running with CDP enabled on port {cdp_port}",
        f"Run the recovery command: {context['recovery_command']}",
        "Navigate to LinkedIn Recruiter in the Chrome window",
        "Confirm the Recruiter interface is fully loaded",
        f"Verify connection with: {context['agent_browser_command']}",
        "Retry the operation once Chrome is ready",
    ]

    return {
        **action_required,
        "context": context,
        "steps": steps,
    }


def _normalize_chip_text(text: str) -> str:
    """Normalize chip text by removing extra whitespace and standardizing case."""
    if not text:
        return ""
    # Remove extra whitespace and normalize
    text = re.sub(r'\s+', ' ', text.strip())
    return text


def _detect_malformed_title_chips(title_chips: list[str]) -> list[str]:
    """Detect malformed/concatenated title chips.

    Looks for chips that appear to be multiple titles concatenated together
    without proper separation (e.g., "Platform EngineerInfrastructure Engineer").

    Args:
        title_chips: List of title chip texts from the Recruiter page

    Returns:
        List of malformed chip texts that need attention
    """
    malformed = []
    for chip in title_chips:
        normalized = _normalize_chip_text(chip)
        if not normalized:
            continue
        # Detect concatenation patterns:
        # - TitleCase words directly adjacent (e.g., "EngineerManager")
        # - Multiple job title keywords without separators
        # Pattern: word boundary between lowercase and uppercase (camelCase concatenation)
        if re.search(r'[a-z][A-Z]', normalized):
            malformed.append(chip)
        # Pattern: multiple title keywords in one chip (e.g., "Engineer - Infrastructure - Cloud")
        # This is actually valid, so we don't flag it
    return malformed


def _analyze_filter_state(
    config: dict[str, str],
    company_chips: list[str],
    title_chips: list[str],
    keyword_chips: list[str] | None = None,
    jd_text: str = "",
    jd_url: str = "",
) -> dict[str, Any]:
    """Analyze the filter state against config to detect issues.

    Args:
        config: Project configuration dict
        company_chips: List of company chip texts from Recruiter page
        title_chips: List of title chip texts from Recruiter page
        keyword_chips: List of keyword/skill chip texts from Recruiter page
        jd_text: Job description text for hiring company detection
        jd_url: Job description URL for hiring company detection

    Returns:
        Dict with inspection results including issues and guidance
    """
    issues = []
    guidance = []

    # Normalize config companies (use effective target companies)
    expected_companies = set()
    effective_companies = get_effective_target_companies(config, jd_text, jd_url)
    if effective_companies:
        expected_companies = {c.lower() for c in effective_companies}

    # Normalize observed companies
    observed_companies = set()
    for chip in company_chips:
        normalized = _normalize_chip_text(chip).lower()
        if normalized:
            observed_companies.add(normalized)

    # Check for missing expected companies
    missing_companies = expected_companies - observed_companies
    if missing_companies and expected_companies:
        issues.append(f"Missing expected companies: {', '.join(sorted(missing_companies))}")
        guidance.append("Verify the Companies filter includes all target companies from config")

    # Check for malformed title chips
    malformed_titles = _detect_malformed_title_chips(title_chips)
    if malformed_titles:
        issues.append(f"Malformed title chips detected: {len(malformed_titles)}")
        guidance.append("Review Job Titles filter - some chips appear concatenated/duplicated")

    # Analyze keywords/skills
    keyword_chips = keyword_chips or []
    expected_keywords = set()
    config_keywords = _split_csv(config.get("KEYWORDS", ""))
    if config_keywords:
        expected_keywords = {k.lower() for k in config_keywords}

    # Normalize observed keywords
    observed_keywords = set()
    for chip in keyword_chips:
        normalized = _normalize_chip_text(chip).lower()
        if normalized:
            observed_keywords.add(normalized)

    # Check for missing expected keywords
    missing_keywords = expected_keywords - observed_keywords
    if missing_keywords and expected_keywords:
        issues.append(f"Missing expected keywords: {', '.join(sorted(missing_keywords))}")
        guidance.append("Verify the Skills and Assessments filter includes all target keywords from config")

    return {
        "expected_companies": sorted(expected_companies) if expected_companies else [],
        "observed_companies": sorted(observed_companies) if observed_companies else [],
        "observed_titles": title_chips,
        "expected_keywords": sorted(expected_keywords) if expected_keywords else [],
        "observed_keywords": sorted(observed_keywords) if observed_keywords else [],
        "missing_companies": sorted(missing_companies) if missing_companies else [],
        "missing_keywords": sorted(missing_keywords) if missing_keywords else [],
        "malformed_titles": malformed_titles,
        "issues": issues,
        "guidance": guidance,
    }


def _extract_filter_chips_from_page(cdp_port: str) -> dict[str, list[str]]:
    """Extract company, title, and keyword chips from the current Recruiter page.

    Uses facet-specific DOM selectors to read visible filter chips from the
    actual Recruiter facet wrappers, not generic chip selectors.

    Args:
        cdp_port: Chrome DevTools Protocol port number

    Returns:
        Dict with 'companies', 'titles', and 'keywords' lists
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import run_browser_probe, safe_get_parsed

        # JavaScript to extract filter chips from facet-specific wrappers
        # Based on live DOM: .search-facet-wrapper.facet-companies, facet-titles, and facet-skills
        js_code = """
        (function() {
            const results = { companies: [], titles: [], keywords: [] };

            // Extract company chips from the companies facet wrapper
            const companiesWrapper = document.querySelector('.search-facet-wrapper.facet-companies');
            if (companiesWrapper) {
                // Look for chips with remove buttons - these are applied filters
                // Pattern: chip text followed by "Remove <chip>" aria-label
                const removeButtons = companiesWrapper.querySelectorAll('button[aria-label^="Remove"]');
                removeButtons.forEach(btn => {
                    const ariaLabel = btn.getAttribute('aria-label') || '';
                    // Extract chip name from "Remove <chip>" pattern
                    const match = ariaLabel.match(/^Remove\\s+(.+)$/i);
                    if (match && match[1]) {
                        const chipText = match[1].trim();
                        if (chipText && !results.companies.includes(chipText)) {
                            results.companies.push(chipText);
                        }
                    }
                });

                // Fallback: look for visible chip elements
                if (results.companies.length === 0) {
                    // Try to find chip elements - look for elements that contain text
                    // but also have a remove button or are marked as selected
                    const chipElements = companiesWrapper.querySelectorAll(
                        '[role="button"], .filter-chip, .search-filter-chip, .artdeco-pill'
                    );
                    chipElements.forEach(chip => {
                        // Skip the remove buttons themselves
                        const ariaLabel = chip.getAttribute('aria-label') || '';
                        if (ariaLabel.startsWith('Remove')) {
                            return;
                        }
                        const text = chip.textContent || '';
                        // Clean up text - remove "Remove" suffix if present
                        let cleanText = text.replace(/\\s*Remove\\s*$/i, '').trim();
                        if (cleanText && !results.companies.includes(cleanText)) {
                            results.companies.push(cleanText);
                        }
                    });
                }
            }

            // Extract title chips from the titles facet wrapper
            const titlesWrapper = document.querySelector('.search-facet-wrapper.facet-titles, .search-facet-wrapper.facet-title');
            if (titlesWrapper) {
                // Look for chips with remove buttons
                const removeButtons = titlesWrapper.querySelectorAll('button[aria-label^="Remove"]');
                removeButtons.forEach(btn => {
                    const ariaLabel = btn.getAttribute('aria-label') || '';
                    const match = ariaLabel.match(/^Remove\\s+(.+)$/i);
                    if (match && match[1]) {
                        const chipText = match[1].trim();
                        if (chipText && !results.titles.includes(chipText)) {
                            results.titles.push(chipText);
                        }
                    }
                });

                // Fallback: look for visible chip elements
                if (results.titles.length === 0) {
                    const chipElements = titlesWrapper.querySelectorAll(
                        '[role="button"], .filter-chip, .search-filter-chip, .artdeco-pill'
                    );
                    chipElements.forEach(chip => {
                        const ariaLabel = chip.getAttribute('aria-label') || '';
                        if (ariaLabel.startsWith('Remove')) {
                            return;
                        }
                        const text = chip.textContent || '';
                        let cleanText = text.replace(/\\s*Remove\\s*$/i, '').trim();
                        if (cleanText && !results.titles.includes(cleanText)) {
                            results.titles.push(cleanText);
                        }
                    });
                }
            }

            // Extract keyword chips from the skills facet wrapper
            const skillsWrapper = document.querySelector('.search-facet-wrapper.facet-skills, .search-facet-wrapper.facet-skill');
            if (skillsWrapper) {
                // Look for chips with remove buttons - these are applied skill filters
                const removeButtons = skillsWrapper.querySelectorAll('button[aria-label^="Remove"]');
                removeButtons.forEach(btn => {
                    const ariaLabel = btn.getAttribute('aria-label') || '';
                    const match = ariaLabel.match(/^Remove\\s+(.+)$/i);
                    if (match && match[1]) {
                        const chipText = match[1].trim();
                        if (chipText && !results.keywords.includes(chipText)) {
                            results.keywords.push(chipText);
                        }
                    }
                });

                // Fallback: look for visible chip elements
                if (results.keywords.length === 0) {
                    const chipElements = skillsWrapper.querySelectorAll(
                        '[role="button"], .filter-chip, .search-filter-chip, .artdeco-pill'
                    );
                    chipElements.forEach(chip => {
                        const ariaLabel = chip.getAttribute('aria-label') || '';
                        if (ariaLabel.startsWith('Remove')) {
                            return;
                        }
                        const text = chip.textContent || '';
                        let cleanText = text.replace(/\\s*Remove\\s*$/i, '').trim();
                        if (cleanText && !results.keywords.includes(cleanText)) {
                            results.keywords.push(cleanText);
                        }
                    });
                }
            }

            // Additional fallback: if no facet wrappers found, try generic selectors
            // but only as last resort
            if (results.companies.length === 0 && results.titles.length === 0 && results.keywords.length === 0) {
                // Look for any chip with "Remove" aria-label pattern
                const allRemoveButtons = document.querySelectorAll('button[aria-label^="Remove"]');
                allRemoveButtons.forEach(btn => {
                    const ariaLabel = btn.getAttribute('aria-label') || '';
                    const match = ariaLabel.match(/^Remove\\s+(.+)$/i);
                    if (match && match[1]) {
                        const chipText = match[1].trim();
                        // Try to determine if it's a company, title, or keyword based on context
                        const parentFacet = btn.closest('.search-facet-wrapper');
                        if (parentFacet) {
                            if (parentFacet.classList.contains('facet-companies')) {
                                if (!results.companies.includes(chipText)) {
                                    results.companies.push(chipText);
                                }
                            } else if (parentFacet.classList.contains('facet-titles') ||
                                       parentFacet.classList.contains('facet-title')) {
                                if (!results.titles.includes(chipText)) {
                                    results.titles.push(chipText);
                                }
                            } else if (parentFacet.classList.contains('facet-skills') ||
                                       parentFacet.classList.contains('facet-skill')) {
                                if (!results.keywords.includes(chipText)) {
                                    results.keywords.push(chipText);
                                }
                            }
                        }
                    }
                });
            }

            return results;
        })()
        """

        result = run_browser_probe(cdp_port, "eval", js_code)
        parsed = safe_get_parsed(result, default={})

        return {
            "companies": parsed.get("companies", []),
            "titles": parsed.get("titles", []),
            "keywords": parsed.get("keywords", []),
        }
    except Exception:
        # Return empty lists if extraction fails
        return {"companies": [], "titles": [], "keywords": []}
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


# Copilot widget JavaScript snippets
COPILOT_DETECT_JS = """
(function() {
  const widget = document.querySelector('[data-test-copilot-widget]');
  if (!widget) {
    return { found: false, state: "missing" };
  }
  const className = widget.className || "";
  const expanded = className.includes("copilot-widget--expanded");
  const collapsed = className.includes("copilot-widget--collapsed");
  const textarea = widget.querySelector('textarea.copilot-chat-input__textbox');
  const buttons = Array.from(widget.querySelectorAll('button, [role="button"]'))
    .map((el) => ({
      text: (el.textContent || "").trim(),
      ariaLabel: el.getAttribute("aria-label") || "",
      disabled: el.disabled || el.getAttribute("aria-disabled") === "true",
    }));
  return {
    found: true,
    state: expanded ? "expanded" : collapsed ? "collapsed" : "unknown",
    hasInput: !!textarea,
    buttons,
  };
})()
"""

COPILOT_EXPAND_JS = """
(function() {
  const widget = document.querySelector('[data-test-copilot-widget]');
  if (!widget) return { success: false, reason: "widget_missing" };
  if ((widget.className || "").includes("copilot-widget--expanded")) {
    return { success: true, alreadyExpanded: true };
  }
  const buttons = Array.from(widget.querySelectorAll('button, [role="button"]'));
  const expandButton = buttons.find((btn) => {
    const text = (btn.textContent || "").toLowerCase();
    const aria = (btn.getAttribute("aria-label") || "").toLowerCase();
    return (
      aria.includes("expand") || aria.includes("open") || aria.includes("copilot") ||
      text.includes("copilot") || text.includes("ask")
    );
  }) || buttons.find((btn) => !btn.disabled && btn.getAttribute("aria-disabled") !== "true");
  if (!expandButton) {
    return { success: false, reason: "expand_button_missing" };
  }
  expandButton.click();
  return {
    success: true, clicked: true,
    buttonText: (expandButton.textContent || "").trim(),
    ariaLabel: expandButton.getAttribute("aria-label") || "",
  };
})()
"""

COPILOT_FOCUS_INPUT_JS = """
(function() {
  const widget = document.querySelector('[data-test-copilot-widget]');
  if (!widget) return { success: false, reason: "widget_missing" };
  const textarea = widget.querySelector('textarea.copilot-chat-input__textbox');
  if (!textarea) return { success: false, reason: "textarea_missing" };
  // Store original styles as JSON so we can restore them later
  textarea.dataset.copilotOriginalStyles = JSON.stringify({
    visibility: textarea.style.visibility,
    display: textarea.style.display,
    opacity: textarea.style.opacity,
    position: textarea.style.position,
    zIndex: textarea.style.zIndex,
    width: textarea.style.width,
    height: textarea.style.height,
  });
  // Make hidden textarea interactable for keyboard input
  textarea.style.visibility = "visible";
  textarea.style.display = "block";
  textarea.style.opacity = "1";
  textarea.style.position = "fixed";
  textarea.style.zIndex = "2147483647";
  textarea.style.width = "600px";
  textarea.style.height = "160px";
  textarea.focus();
  textarea.click();
  // Clear any existing value using native setter so React detects the change
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
  const oldValue = textarea.value;
  setter.call(textarea, "");
  if (textarea._valueTracker) {
    textarea._valueTracker.setValue(oldValue);
  }
  textarea.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContent" }));
  return {
    success: true, tag: textarea.tagName,
    role: textarea.getAttribute("role") || "",
    contenteditable: textarea.isContentEditable,
  };
})()
"""

COPILOT_RESTORE_INPUT_JS = """
(function() {
  const widget = document.querySelector('[data-test-copilot-widget]');
  if (!widget) return { restored: false };
  const textarea = widget.querySelector('textarea.copilot-chat-input__textbox');
  if (!textarea) return { restored: false };
  const raw = textarea.dataset.copilotOriginalStyles;
  if (raw) {
    try {
      const styles = JSON.parse(raw);
      textarea.style.visibility = styles.visibility || "";
      textarea.style.display = styles.display || "";
      textarea.style.opacity = styles.opacity || "";
      textarea.style.position = styles.position || "";
      textarea.style.zIndex = styles.zIndex || "";
      textarea.style.width = styles.width || "";
      textarea.style.height = styles.height || "";
      delete textarea.dataset.copilotOriginalStyles;
      return { restored: true };
    } catch (e) {
      return { restored: false, error: e.message };
    }
  }
  return { restored: false };
})()
"""

COPILOT_TYPE_FALLBACK_JS = """
(function() {
  const widget = document.querySelector('[data-test-copilot-widget]');
  if (!widget) return { ok: false, reason: "widget_missing" };
  const query = widget.dataset.copilotPendingQuery || "";
  if (!query) return { ok: false, reason: "no_pending_query" };
  const textarea = widget.querySelector('textarea.copilot-chat-input__textbox');
  if (!textarea) return { ok: false, reason: "textarea_missing" };
  textarea.style.visibility = "visible";
  textarea.style.display = "block";
  textarea.style.opacity = "1";
  textarea.style.position = "fixed";
  textarea.style.zIndex = "2147483647";
  textarea.focus();
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
  const oldValue = textarea.value;
  setter.call(textarea, query);
  if (textarea._valueTracker) {
    textarea._valueTracker.setValue(oldValue);
  }
  textarea.dispatchEvent(new InputEvent("beforeinput", {
    bubbles: true, cancelable: true, inputType: "insertText", data: query
  }));
  textarea.dispatchEvent(new InputEvent("input", {
    bubbles: true, inputType: "insertText", data: query
  }));
  textarea.dispatchEvent(new Event("change", { bubbles: true }));
  const mirror = widget.querySelector('.copilot-chat-input__textbox-mirror');
  if (mirror) mirror.textContent = query;
  delete widget.dataset.copilotPendingQuery;
  return { ok: true, length: textarea.value.length };
})()
"""

COPILOT_SUBMIT_JS = """
(function() {
  const widget = document.querySelector('[data-test-copilot-widget]');
  if (!widget) return { success: false, reason: "widget_missing" };
  const form = widget.querySelector('form.copilot-chat-input');
  const buttons = Array.from((form || widget).querySelectorAll('button, [role="button"]'));
  const submitButton = buttons.find((btn) => {
    const text = (btn.textContent || "").toLowerCase().trim();
    const aria = (btn.getAttribute("aria-label") || "").toLowerCase();
    const disabled = btn.disabled || btn.getAttribute("aria-disabled") === "true";
    if (disabled) return false;
    return (
      aria.includes("send") || aria.includes("submit") || aria.includes("search") ||
      text.includes("send your request") || text === "send" || text === "submit" || text === "search"
    );
  });
  if (submitButton) {
    submitButton.click();
    return {
      success: true, method: "button",
      text: (submitButton.textContent || "").trim(),
      ariaLabel: submitButton.getAttribute("aria-label") || "",
    };
  }
  return { success: false, reason: "submit_button_missing" };
})()
"""

COPILOT_VALIDATE_INPUT_JS = """
(function() {
  const widget = document.querySelector('[data-test-copilot-widget]');
  if (!widget) return { ok: false, reason: "widget_missing" };
  const textarea = widget.querySelector('textarea.copilot-chat-input__textbox');
  const form = widget.querySelector('form.copilot-chat-input');
  const bodyText = document.body.innerText;
  // Check textarea has value
  const hasValue = textarea && textarea.value.length > 0;
  const valueLength = textarea ? textarea.value.length : 0;
  // Check for validation error
  const hasValidationError = bodyText.includes("Please enter valid text.");
  // Check char counter (look for pattern like "0 / 6,000")
  const counterEl = Array.from(document.querySelectorAll('*')).find(el => {
    const text = el.textContent ? el.textContent.trim() : "";
    return /^\\d+\\s*\\/\\s*6,000$/.test(text);
  });
  const counterText = counterEl ? counterEl.textContent.trim() : null;
  const counterIsZero = counterText === "0 / 6,000";
  // Check send button is present and enabled
  const buttons = Array.from((form || widget).querySelectorAll('button, [role="button"]'));
  const sendButton = buttons.find((btn) => {
    const text = (btn.textContent || "").toLowerCase().trim();
    const aria = (btn.getAttribute("aria-label") || "").toLowerCase();
    const disabled = btn.disabled || btn.getAttribute("aria-disabled") === "true";
    if (disabled) return false;
    return (
      aria.includes("send") || aria.includes("submit") ||
      text.includes("send your request") || text === "send" || text === "submit"
    );
  });
  const hasSendButton = !!sendButton;
  return {
    ok: hasValue && !hasValidationError && !counterIsZero && hasSendButton,
    hasValue,
    valueLength,
    hasValidationError,
    counterText,
    counterIsZero,
    hasSendButton,
  };
})()
"""

COPILOT_POLL_JS = """
(function() {
  const widget = document.querySelector('[data-test-copilot-widget]');
  const bodyText = document.body.innerText.toLowerCase();
  const widgetText = widget ? widget.innerText.toLowerCase() : "";
  return {
    hasWidget: !!widget,
    widgetState: widget
      ? ((widget.className || "").includes("copilot-widget--expanded")
          ? "expanded"
          : (widget.className || "").includes("copilot-widget--collapsed")
            ? "collapsed"
            : "unknown")
      : "missing",
    isGenerating:
      bodyText.includes("generating") || bodyText.includes("working on") ||
      bodyText.includes("creating search") || bodyText.includes("thinking") ||
      !!document.querySelector('[aria-busy="true"], .artdeco-spinner'),
    hasSearchCreationPrompt:
      bodyText.includes("start a search") ||
      bodyText.includes("create a search from a job description") ||
      bodyText.includes("generate or refine a boolean search"),
    copilotCreatedSearch:
      widgetText.includes("a search was created for you") ||
      widgetText.includes("updates to your search criteria have been made"),
    candidateCardCount: document.querySelectorAll('li.profile-list__border-bottom').length,
    profileLinkCount: document.querySelectorAll('a[href*="/talent/profile/"]').length,
    hasFacetWrappers: !!document.querySelector('.search-facet-wrapper, [class*="facet"]'),
    currentUrl: window.location.href,
  };
})()
"""


def _click_filter_button(cdp_port: str, filter_type: str) -> bool:
    """Click the edit button for a specific filter type.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        filter_type: Type of filter ('companies', 'titles', or 'skills')

    Returns:
        True if button was found and clicked, False otherwise
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import run_browser_command, safe_get_parsed

        # JavaScript to find and click the filter edit button
        # Based on CDP inspection: button text is "Companies or boolean" for companies
        js_code = f"""
        (function() {{
            const filterType = '{filter_type}';
            let button = null;

            if (filterType === 'companies') {{
                // Look for "Companies or boolean" button text
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {{
                    const text = (btn.textContent || btn.innerText || '').toLowerCase();
                    if (text.includes('companies') && text.includes('boolean')) {{
                        button = btn;
                        break;
                    }}
                }}
                // Fallback: look for facet-companies wrapper
                if (!button) {{
                    const wrapper = document.querySelector('.search-facet-wrapper.facet-companies');
                    if (wrapper) {{
                        button = wrapper.querySelector('button');
                    }}
                }}
            }} else if (filterType === 'titles') {{
                // Look for titles filter button
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {{
                    const text = (btn.textContent || btn.innerText || '').toLowerCase();
                    if (text.includes('title') || text.includes('job title')) {{
                        button = btn;
                        break;
                    }}
                }}
                // Fallback: look for facet-titles wrapper
                if (!button) {{
                    const wrapper = document.querySelector('.search-facet-wrapper.facet-titles');
                    if (wrapper) {{
                        button = wrapper.querySelector('button');
                    }}
                }}
            }} else if (filterType === 'skills') {{
                // Look for skills filter button
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {{
                    const text = (btn.textContent || btn.innerText || '').toLowerCase();
                    if (text.includes('skill') || text.includes('assessment')) {{
                        button = btn;
                        break;
                    }}
                }}
                // Fallback: look for facet-skills wrapper
                if (!button) {{
                    const wrapper = document.querySelector('.search-facet-wrapper.facet-skills, .search-facet-wrapper.facet-skill');
                    if (wrapper) {{
                        button = wrapper.querySelector('button');
                    }}
                }}
            }}

            if (button) {{
                button.click();
                return {{ success: true, clicked: true }};
            }}
            return {{ success: false, clicked: false, reason: 'Button not found' }};
        }})()
        """

        result = run_browser_command(cdp_port, "eval", js_code)
        parsed = safe_get_parsed(result, default={})
        return parsed.get("clicked", False)
    except Exception:
        return False
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def _normalize_facet_option_text(text: str) -> str:
    """Normalize facet option text for exact matching.

    Shared normalizer for company and keyword/skill options.
    Removes non-alphanumeric characters and lowercases for comparison.
    """
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# Backward-compatible aliases
def _normalize_company_option_text(text: str) -> str:
    """Normalize company option text for exact matching."""
    return _normalize_facet_option_text(text)


def _normalize_keyword_option_text(text: str) -> str:
    """Normalize keyword/skill option text for exact matching."""
    return _normalize_facet_option_text(text)


def _find_facet_option_ref(
    cdp_port: str,
    target_value: str,
    facet_selector: str,
) -> dict[str, Any]:
    """Find the agent-browser ref for an exact option in a facet dropdown.

    Uses a scoped accessibility snapshot so the returned ref can be clicked with a
    real browser interaction. Matches either the exact label or Recruiter
    suggestion labels like "Add <value> to list of filters".

    Args:
        cdp_port: Chrome DevTools Protocol port number
        target_value: The target value to search for (company, keyword, etc.)
        facet_selector: CSS selector for the facet wrapper (e.g., ".facet-companies")

    Returns:
        Dict with success status, matched label, ref, and available options on failure
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import run_browser_probe
        import time

        target = _normalize_facet_option_text(target_value)
        add_target = _normalize_facet_option_text(f"Add {target_value} to list of filters")
        snapshot_args = ("snapshot", "-i", "-s", facet_selector)

        for attempt in range(3):
            snapshot_result = run_browser_probe(cdp_port, *snapshot_args)
            if snapshot_result.get("error"):
                if attempt < 2:
                    time.sleep(0.3)
                    continue
                return {
                    "success": False,
                    "reason": "snapshot_failed",
                    "target": target_value,
                    "error": snapshot_result.get("error"),
                }

            snapshot_text = snapshot_result.get("stdout", "")
            matches = re.findall(r'option "([^"]+)" \[ref=([^\]]+)\]', snapshot_text)

            if not matches:
                if attempt < 2:
                    time.sleep(0.3)
                    continue
                return {
                    "success": False,
                    "reason": "no_exact_match",
                    "target": target_value,
                    "availableOptions": [],
                }

            available_options: list[str] = []
            add_ref: str | None = None
            add_label: str | None = None

            for raw_label, ref in matches:
                label = raw_label.strip(" ,")
                normalized = _normalize_facet_option_text(label)
                available_options.append(label)

                if normalized == target:
                    return {
                        "success": True,
                        "matched": label,
                        "ref": ref,
                    }

                if normalized == add_target and add_ref is None:
                    add_ref = ref
                    add_label = label

            if add_ref:
                return {
                    "success": True,
                    "matched": add_label or target_value,
                    "ref": add_ref,
                }

            return {
                "success": False,
                "reason": "no_exact_match",
                "target": target_value,
                "availableOptions": available_options[:10],
            }

        return {
            "success": False,
            "reason": "no_exact_match",
            "target": target_value,
            "availableOptions": [],
        }
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def _find_company_option_ref(cdp_port: str, company: str) -> dict[str, Any]:
    """Find the agent-browser ref for the exact company option in the Companies facet.

    Uses a scoped accessibility snapshot so the returned ref can be clicked with a
    real browser interaction. Matches either the exact company label or Recruiter
    suggestion labels like "Add <company> to list of filters".
    """
    return _find_facet_option_ref(
        cdp_port,
        company,
        ".search-facet-wrapper.facet-companies",
    )


def _find_keyword_option_ref(cdp_port: str, keyword: str) -> dict[str, Any]:
    """Find the agent-browser ref for the exact keyword option in the Skills facet.

    Uses a scoped accessibility snapshot so the returned ref can be clicked with a
    real browser interaction. Matches either the exact keyword label or Recruiter
    suggestion labels like "Add <keyword> to list of filters".
    """
    return _find_facet_option_ref(
        cdp_port,
        keyword,
        ".search-facet-wrapper.facet-skills, .search-facet-wrapper.facet-skill",
    )


def _add_facet_filters(
    cdp_port: str,
    values: list[str],
    facet_selector: str,
    find_option_ref_fn,
) -> dict[str, Any]:
    """Add values to a facet filter using real browser interaction.

    Uses deterministic real browser interactions (snapshot + explicit click)
    instead of synthetic DOM clicks for reliable selection. Captures
    a scoped snapshot of the facet, finds the exact match option,
    and clicks it directly via agent-browser. Verifies chip presence strictly
    via "Remove <value>" button before reporting success.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        values: List of values to add (companies, keywords, etc.)
        facet_selector: CSS selector for the facet wrapper
        find_option_ref_fn: Function to find option ref (e.g., _find_company_option_ref)

    Returns:
        Dict with added values and any that failed
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import run_browser_command, run_browser_probe, safe_get_parsed
        import time

        added = []
        failed = []

        for value in values:
            try:
                # Step 1: Focus the input within the facet wrapper
                focus_js = f"""
                (function() {{
                    const value = {json.dumps(value)};

                    // Find the facet wrapper
                    const wrapper = document.querySelector('{facet_selector}');
                    if (!wrapper) {{
                        return {{ success: false, reason: 'Facet wrapper not found' }};
                    }}

                    // Find the input within the facet
                    let input = wrapper.querySelector('input[type="text"], input[type="search"]');
                    if (!input) {{
                        // Try to open the facet first by clicking the button
                        const button = wrapper.querySelector('button');
                        if (button) {{
                            button.click();
                            return {{ success: false, reason: 'facet_closed', retry: true }};
                        }}
                        return {{ success: false, reason: 'Input field not found in facet' }};
                    }}

                    // Focus and clear the input
                    input.focus();
                    input.click();
                    input.value = '';  // Clear any previous value
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));

                    return {{ success: true, value: value, inputFocused: true }};
                }})()
                """

                result = run_browser_command(cdp_port, "eval", focus_js)
                parsed = safe_get_parsed(result, default={})

                if parsed.get("reason") == 'facet_closed':
                    # Wait for facet to open and retry
                    time.sleep(0.3)
                    result = run_browser_command(cdp_port, "eval", focus_js)
                    parsed = safe_get_parsed(result, default={})

                if not parsed.get("success"):
                    failed.append(value)
                    continue

                # Step 2: Type the value using real keyboard input
                type_result = run_browser_command(cdp_port, "keyboard", "inserttext", value)
                if type_result.get("error"):
                    # Fallback: try keyboard type if inserttext fails
                    type_result = run_browser_command(cdp_port, "keyboard", "type", value)
                    if type_result.get("error"):
                        failed.append(value)
                        continue

                # Step 3: Wait for suggestions and capture scoped snapshot
                time.sleep(0.6)  # Give suggestions time to appear

                option_result = find_option_ref_fn(cdp_port, value)

                if not option_result.get("success"):
                    # No exact match available - fail this value
                    failed.append(value)
                    continue

                # Step 4: Use real browser interaction to click the exact match option
                option_ref = option_result.get("ref")
                if not option_ref:
                    failed.append(value)
                    continue

                click_result = run_browser_command(cdp_port, "click", f"@{option_ref}")
                if click_result.get("error"):
                    failed.append(value)
                    continue

                # Step 5: Verify the chip was actually added
                time.sleep(0.5)  # Wait for chip to appear

                verify_js = f"""
                (function() {{
                    const targetValue = {json.dumps(value)};
                    const targetLower = targetValue.toLowerCase().trim();

                    // Find the facet wrapper
                    const wrapper = document.querySelector('{facet_selector}');
                    if (!wrapper) {{
                        return {{ success: false, reason: 'Facet wrapper not found' }};
                    }}

                    // Check for the chip by looking for "Remove <value>" button
                    // This is the ONLY valid evidence of a real chip - remove button aria-label
                    const removeButtons = wrapper.querySelectorAll('button[aria-label^="Remove"]');
                    for (const btn of removeButtons) {{
                        const ariaLabel = btn.getAttribute('aria-label') || '';
                        const match = ariaLabel.match(/^Remove\\s+(.+)$/i);
                        if (match && match[1]) {{
                            const chipName = match[1].trim().toLowerCase();
                            if (chipName === targetLower) {{
                                return {{ success: true, verified: true, chip: match[1].trim() }};
                            }}
                        }}
                    }}

                    // No fallback: typed text or suggestion text does NOT count as a chip
                    // This prevents false positives where text appears but no chip was added
                    return {{ success: false, reason: 'chip_not_found_after_add' }};
                }})()
                """
                verify_result = run_browser_probe(cdp_port, "eval", verify_js)
                verify_parsed = safe_get_parsed(verify_result, default={})

                # Only count as added if verification succeeds
                if verify_parsed.get("success"):
                    added.append(value)
                else:
                    # Verification failed - value goes to failed list
                    failed.append(value)

            except Exception:
                failed.append(value)

        return {"added": added, "failed": failed}
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def _add_company_filters(cdp_port: str, companies: list[str]) -> dict[str, Any]:
    """Add companies to the Companies filter using real browser interaction.

    Uses deterministic real browser interactions (snapshot + explicit click)
    instead of synthetic DOM clicks for reliable company selection. Captures
    a scoped snapshot of the Companies facet, finds the exact match option,
    and clicks it directly via agent-browser. Verifies chip presence strictly
    via "Remove <company>" button before reporting success.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        companies: List of company names to add

    Returns:
        Dict with added companies and any that failed
    """
    return _add_facet_filters(
        cdp_port,
        companies,
        ".search-facet-wrapper.facet-companies",
        _find_company_option_ref,
    )


def _add_keyword_filters(cdp_port: str, keywords: list[str]) -> dict[str, Any]:
    """Add keywords to the Skills and Assessments filter using real browser interaction.

    Uses deterministic real browser interactions (snapshot + explicit click)
    instead of synthetic DOM clicks for reliable keyword selection. Captures
    a scoped snapshot of the Skills facet, finds the exact match option,
    and clicks it directly via agent-browser. Verifies chip presence strictly
    via "Remove <keyword>" button before reporting success.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        keywords: List of keyword/skill names to add

    Returns:
        Dict with added keywords and any that failed
    """
    return _add_facet_filters(
        cdp_port,
        keywords,
        ".search-facet-wrapper.facet-skills, .search-facet-wrapper.facet-skill",
        _find_keyword_option_ref,
    )


def _remove_malformed_title_chips(cdp_port: str, malformed_titles: list[str]) -> dict[str, Any]:
    """Remove malformed title chips by clicking their remove buttons.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        malformed_titles: List of malformed title chip texts to remove

    Returns:
        Dict with removed titles and any that failed
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import run_browser_command, safe_get_parsed

        removed = []
        failed = []

        for title in malformed_titles:
            try:
                # JavaScript to find and click the remove button for a title chip
                # Based on CDP inspection: remove buttons are labeled "Remove <chip>"
                js_code = f"""
                (function() {{
                    const title = {json.dumps(title)};

                    // Find chips with this text
                    const chips = document.querySelectorAll('.filter-chip, .search-filter-chip, [data-test-id="filter-chip-title"]');
                    let targetChip = null;

                    for (const chip of chips) {{
                        const text = (chip.textContent || chip.innerText || '').trim();
                        if (text === title || text.includes(title)) {{
                            targetChip = chip;
                            break;
                        }}
                    }}

                    if (!targetChip) {{
                        return {{ success: false, reason: 'Chip not found' }};
                    }}

                    // Look for remove button within or near the chip
                    // Remove buttons typically have aria-label="Remove ..." or similar
                    let removeBtn = targetChip.querySelector('button[aria-label*="Remove"], button[title*="Remove"]');
                    if (!removeBtn) {{
                        // Try finding any button in the chip
                        removeBtn = targetChip.querySelector('button');
                    }}

                    if (removeBtn) {{
                        removeBtn.click();
                        return {{ success: true, title: title }};
                    }}

                    return {{ success: false, reason: 'Remove button not found' }};
                }})()
                """

                result = run_browser_command(cdp_port, "eval", js_code)
                parsed = safe_get_parsed(result, default={})

                if parsed.get("success"):
                    removed.append(title)
                else:
                    failed.append(title)

            except Exception:
                failed.append(title)

        return {"removed": removed, "failed": failed}
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def _reconcile_filter_state(
    cdp_port: str,
    current_analysis: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile live filter state against config by adding missing companies/keywords and removing malformed titles.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        current_analysis: Current filter analysis from _analyze_filter_state

    Returns:
        Dict with reconciliation results including what was changed
    """
    reconciliation = {
        "attempted": False,
        "companies_added": [],
        "companies_failed": [],
        "keywords_added": [],
        "keywords_failed": [],
        "titles_removed": [],
        "titles_failed": [],
        "errors": [],
    }

    missing_companies = current_analysis.get("missing_companies", [])
    missing_keywords = current_analysis.get("missing_keywords", [])
    malformed_titles = current_analysis.get("malformed_titles", [])

    # Only attempt reconciliation if there are issues to fix
    if not missing_companies and not missing_keywords and not malformed_titles:
        return reconciliation

    reconciliation["attempted"] = True

    # Reconcile missing companies (using effective target companies)
    if missing_companies:
        # Click the companies filter button to open the filter panel
        if _click_filter_button(cdp_port, "companies"):
            company_result = _add_company_filters(cdp_port, missing_companies)
            reconciliation["companies_added"] = company_result.get("added", [])
            reconciliation["companies_failed"] = company_result.get("failed", [])
        else:
            reconciliation["companies_failed"] = missing_companies
            reconciliation["errors"].append("Could not open Companies filter")

    # Reconcile missing keywords
    if missing_keywords:
        # Click the skills filter button to open the filter panel
        if _click_filter_button(cdp_port, "skills"):
            keyword_result = _add_keyword_filters(cdp_port, missing_keywords)
            reconciliation["keywords_added"] = keyword_result.get("added", [])
            reconciliation["keywords_failed"] = keyword_result.get("failed", [])
        else:
            reconciliation["keywords_failed"] = missing_keywords
            reconciliation["errors"].append("Could not open Skills filter")

    # Reconcile malformed titles
    if malformed_titles:
        # Click the titles filter button to open the filter panel
        if _click_filter_button(cdp_port, "titles"):
            title_result = _remove_malformed_title_chips(cdp_port, malformed_titles)
            reconciliation["titles_removed"] = title_result.get("removed", [])
            reconciliation["titles_failed"] = title_result.get("failed", [])
        else:
            reconciliation["titles_failed"] = malformed_titles
            reconciliation["errors"].append("Could not open Titles filter")

    return reconciliation


def create_initial_search_with_copilot(
    cdp_port: str,
    recruiter_url: str,
    config: dict[str, str],
    jd_text: str = "",
    jd_url: str = "",
    work_dir: Path | None = None,
    chrome_profile: Path | str | None = None,
) -> dict[str, Any]:
    """Create an initial Recruiter search using the AI Copilot widget.

    Flow:
        1. Open the recruiter search page
        2. Detect the Copilot widget
        3. Expand if collapsed
        4. Focus input and type query
        5. Submit query
        6. Poll for search creation (up to 90s)
        7. Verify search is ready via inspect_search_state

    Returns:
        Dict with success status and inspection results
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import (
            ActionRequired, FailureCode, run_browser_command, safe_get_parsed,
        )
        from recruiter_page_utils import ensure_page_ready

        # Step 1: Open search page
        open_result = run_browser_command(cdp_port, "open", recruiter_url, timeout=30)
        if open_result.get("error"):
            return {
                "success": False,
                "status": "browser_error",
                "failure_code": FailureCode.BROWSER_UNAVAILABLE,
                "action_required": ActionRequired.browser_unavailable(cdp_port=cdp_port).to_dict(),
            }

        ready_result = ensure_page_ready(
            cdp_port=cdp_port,
            target_url=recruiter_url,
            require_page_identity=True,
            context="create_initial_search_with_copilot",
            max_wait_seconds=20.0,
        )
        if not ready_result.get("ready"):
            return {
                "success": False,
                "status": ready_result.get("state", "unknown"),
                "failure_code": ready_result.get("failure_code", FailureCode.AMBIGUOUS_STATE),
                "action_required": ready_result.get("action_required"),
            }

        # Step 2: Detect Copilot widget
        detect_result = run_browser_command(cdp_port, "eval", COPILOT_DETECT_JS)
        detect_parsed = safe_get_parsed(detect_result, default={})
        if not detect_parsed.get("found"):
            return {
                "success": False,
                "status": "copilot_widget_missing",
                "failure_code": FailureCode.ELEMENT_MISSING,
                "action_required": ActionRequired.element_missing(
                    selector="data-test-copilot-widget",
                    page_url=recruiter_url,
                ).to_dict(),
            }

        # Step 3: Expand if collapsed
        if detect_parsed.get("state") == "collapsed":
            expand_result = run_browser_command(cdp_port, "eval", COPILOT_EXPAND_JS)
            expand_parsed = safe_get_parsed(expand_result, default={})
            if not expand_parsed.get("success"):
                return {
                    "success": False,
                    "status": "copilot_expand_failed",
                    "failure_code": FailureCode.ELEMENT_MISSING,
                    "action_required": ActionRequired.element_missing(
                        selector="Copilot expand button",
                        page_url=recruiter_url,
                    ).to_dict(),
                }
            # Wait for expansion
            import time
            time.sleep(1)
            # Re-detect
            for _ in range(5):
                detect_result = run_browser_command(cdp_port, "eval", COPILOT_DETECT_JS)
                detect_parsed = safe_get_parsed(detect_result, default={})
                if detect_parsed.get("state") == "expanded" and detect_parsed.get("hasInput"):
                    break
                time.sleep(1)
            else:
                return {
                    "success": False,
                    "status": "copilot_expand_timeout",
                    "failure_code": FailureCode.TIMEOUT,
                    "action_required": ActionRequired.timeout(
                        operation="wait for Copilot widget expansion"
                    ).to_dict(),
                }

        # Step 4: Focus input
        focus_result = run_browser_command(cdp_port, "eval", COPILOT_FOCUS_INPUT_JS)
        focus_parsed = safe_get_parsed(focus_result, default={})
        if not focus_parsed.get("success"):
            return {
                "success": False,
                "status": "copilot_input_missing",
                "failure_code": FailureCode.ELEMENT_MISSING,
                "action_required": ActionRequired.element_missing(
                    selector="Copilot input field",
                    page_url=recruiter_url,
                ).to_dict(),
            }

        # Step 5: Type query
        query = build_copilot_search_query(config, jd_text, jd_url)
        type_result = run_browser_command(cdp_port, "keyboard", "inserttext", query)
        if type_result.get("error"):
            type_result = run_browser_command(cdp_port, "keyboard", "type", query)

        # Step 5b: Validate input reached React state
        time.sleep(0.5)
        validate_result = run_browser_command(cdp_port, "eval", COPILOT_VALIDATE_INPUT_JS)
        validate_parsed = safe_get_parsed(validate_result, default={})
        if not validate_parsed.get("ok"):
            # Fallback: stash query in a data attribute, then run setter JS
            stash_js = """
            (function() {
              const widget = document.querySelector('[data-test-copilot-widget]');
              if (widget) widget.dataset.copilotPendingQuery = arguments[0];
              return { stashed: !!widget };
            })()
            """
            stash_result = run_browser_command(cdp_port, "eval", stash_js, query)
            if stash_result.get("error"):
                return {
                    "success": False,
                    "status": "copilot_type_failed",
                    "failure_code": FailureCode.BROWSER_UNAVAILABLE,
                    "action_required": ActionRequired.ambiguous_state(
                        details="Failed to stash Copilot query for fallback"
                    ).to_dict(),
                }
            fallback_result = run_browser_command(cdp_port, "eval", COPILOT_TYPE_FALLBACK_JS)
            fallback_parsed = safe_get_parsed(fallback_result, default={})
            if not fallback_parsed.get("ok"):
                return {
                    "success": False,
                    "status": "copilot_type_failed",
                    "failure_code": FailureCode.BROWSER_UNAVAILABLE,
                    "action_required": ActionRequired.ambiguous_state(
                        details="Failed to type Copilot query: keyboard and DOM fallback both failed"
                    ).to_dict(),
                }
            # Re-validate after fallback
            time.sleep(0.5)
            validate_result = run_browser_command(cdp_port, "eval", COPILOT_VALIDATE_INPUT_JS)
            validate_parsed = safe_get_parsed(validate_result, default={})
            if not validate_parsed.get("ok"):
                return {
                    "success": False,
                    "status": "copilot_type_validation_failed",
                    "failure_code": FailureCode.BROWSER_UNAVAILABLE,
                    "action_required": ActionRequired.ambiguous_state(
                        details=f"Copilot input validation failed: {validate_parsed}"
                    ).to_dict(),
                }

        # Step 6: Submit query
        submit_result = run_browser_command(cdp_port, "eval", COPILOT_SUBMIT_JS)
        submit_parsed = safe_get_parsed(submit_result, default={})
        if not submit_parsed.get("success"):
            return {
                "success": False,
                "status": "copilot_submit_failed",
                "failure_code": FailureCode.ELEMENT_MISSING,
                "action_required": ActionRequired.element_missing(
                    selector="Copilot submit button",
                    page_url=recruiter_url,
                ).to_dict(),
            }

        # Restore textarea styles so they don't block future interactions
        run_browser_command(cdp_port, "eval", COPILOT_RESTORE_INPUT_JS)

        # Step 7: Poll for creation (up to 90s)
        expected_project_id = _extract_project_id_from_url(recruiter_url)
        for attempt in range(45):
            time.sleep(2)
            poll_result = run_browser_command(cdp_port, "eval", COPILOT_POLL_JS)
            poll_parsed = safe_get_parsed(poll_result, default={})

            # Check if we're still on the right project
            current_url = poll_parsed.get("currentUrl", "")
            current_project_id = _extract_project_id_from_url(current_url)
            if current_project_id and current_project_id != expected_project_id:
                return {
                    "success": False,
                    "status": "copilot_wrong_project",
                    "failure_code": FailureCode.WRONG_PAGE,
                    "action_required": ActionRequired.wrong_page(
                        expected_url=recruiter_url,
                        actual_url=current_url,
                    ).to_dict(),
                }

            # Check if search was created
            has_creation_prompt = poll_parsed.get("hasSearchCreationPrompt", False)
            copilot_created = poll_parsed.get("copilotCreatedSearch", False)
            has_results = (
                poll_parsed.get("candidateCardCount", 0) > 0 or
                poll_parsed.get("profileLinkCount", 0) > 0 or
                poll_parsed.get("hasFacetWrappers", False)
            )
            is_generating = poll_parsed.get("isGenerating", False)

            if (copilot_created or not has_creation_prompt) and has_results and not is_generating:
                # Search appears ready - verify with inspect_search_state
                # Use current URL from poll if still on same project, to avoid losing Copilot-created state
                verification_url = current_url if current_project_id == expected_project_id else recruiter_url
                inspection = inspect_search_state(
                    cdp_port, verification_url,
                    work_dir=work_dir,
                    chrome_profile=chrome_profile,
                    config=config,
                    jd_text=jd_text,
                    jd_url=jd_url,
                )
                if inspection.get("success"):
                    return {
                        "success": True,
                        "status": "created",
                        "inspection": inspection,
                        "created_search_url": verification_url,
                    }
                # If inspect says not ready yet, keep polling
                if inspection.get("status") != "search_not_configured":
                    return {
                        "success": False,
                        "status": inspection.get("status", "unverified"),
                        "failure_code": inspection.get("failure_code"),
                        "action_required": inspection.get("action_required"),
                    }

            if attempt > 0 and attempt % 10 == 0:
                print(f"  Copilot still processing... ({attempt * 2}s)", file=sys.stderr)

        return {
            "success": False,
            "status": "copilot_no_results_timeout",
            "failure_code": FailureCode.TIMEOUT,
            "action_required": ActionRequired.timeout(
                operation="wait for Copilot to create search"
            ).to_dict(),
        }
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def inspect_search_state(
    cdp_port: str, recruiter_url: str, work_dir: Path | None = None, chrome_profile: Path | str | None = None,
    config: dict[str, str] | None = None, jd_text: str = "", jd_url: str = ""
) -> dict[str, Any]:
    """Open the project search page and inspect whether it is extraction-ready.

    Args:
        cdp_port: Chrome DevTools Protocol port number
        recruiter_url: LinkedIn Recruiter project URL
        work_dir: Optional working directory for recovery context enrichment (from runtime)
        chrome_profile: Optional Chrome profile path for recovery context (from runtime)
        config: Optional project configuration for filter analysis
        jd_text: Job description text for hiring company detection
        jd_url: Job description URL for hiring company detection

    Returns:
        Dict with inspection results, including enriched action_required for blockers
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import (
            ActionRequired,
            FailureCode,
            classify_browser_readiness,
            run_browser_command,
            safe_get_parsed,
            CONNECT_BROWSER_SCRIPT,
        )
        from recruiter_page_utils import PageStateProbe, ensure_page_ready

        # Extract expected project ID from the target URL for cross-project validation
        expected_project_id = _extract_project_id_from_url(recruiter_url)

        open_result = run_browser_command(cdp_port, "open", recruiter_url, timeout=30)
        if open_result.get("error"):
            readiness = classify_browser_readiness(
                cdp_port, error=open_result.get("error")
            )
            action_required = (
                readiness.action_required.to_dict()
                if readiness.action_required
                else ActionRequired.ambiguous_state(
                    details=open_result.get("error")
                ).to_dict()
            )
            # Enrich browser_unavailable blockers with recovery details
            action_required = _enrich_browser_unavailable_blocker(
                action_required, cdp_port, work_dir, chrome_profile
            )
            return {
                "success": False,
                "status": "browser_error",
                "failure_code": readiness.action_required.code
                if readiness.action_required
                else FailureCode.AMBIGUOUS_STATE,
                "action_required": action_required,
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
            action_required = ready_result.get("action_required")
            # Enrich browser_unavailable blockers with recovery details
            if action_required:
                action_required = _enrich_browser_unavailable_blocker(
                    action_required, cdp_port, work_dir, chrome_profile
                )
            return {
                "success": False,
                "status": ready_result.get("state", "unknown"),
                "failure_code": ready_result.get(
                    "failure_code", FailureCode.AMBIGUOUS_STATE
                ),
                "action_required": action_required,
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
            # Extract filter chips for analysis
            filter_chips = _extract_filter_chips_from_page(cdp_port)
            filter_analysis = None
            reconciliation_result = None

            if config:
                filter_analysis = _analyze_filter_state(
                    config,
                    filter_chips.get("companies", []),
                    filter_chips.get("titles", []),
                    keyword_chips=filter_chips.get("keywords", []),
                    jd_text=jd_text,
                    jd_url=jd_url,
                )

                # Attempt to reconcile filter state if there are issues
                if filter_analysis.get("missing_companies") or filter_analysis.get("missing_keywords") or filter_analysis.get("malformed_titles"):
                    reconciliation_result = _reconcile_filter_state(cdp_port, filter_analysis)

                    # If reconciliation was attempted and partially succeeded,
                    # re-extract and re-analyze to get updated state
                    if reconciliation_result.get("attempted"):
                        # Brief wait for UI to update
                        import time
                        time.sleep(1.0)
                        filter_chips = _extract_filter_chips_from_page(cdp_port)
                        filter_analysis = _analyze_filter_state(
                            config,
                            filter_chips.get("companies", []),
                            filter_chips.get("titles", []),
                            keyword_chips=filter_chips.get("keywords", []),
                            jd_text=jd_text,
                            jd_url=jd_url,
                        )

                        # Defensive guard: ensure companies_added matches final observed state
                        # This prevents false positives where text appeared but no chip was added
                        observed_companies = set(filter_analysis.get("observed_companies", []))
                        claimed_added = reconciliation_result.get("companies_added", [])
                        actually_added = [c for c in claimed_added if c.lower() in observed_companies]
                        falsely_claimed = [c for c in claimed_added if c.lower() not in observed_companies]

                        if falsely_claimed:
                            # Move falsely claimed companies to failed list
                            reconciliation_result["companies_added"] = actually_added
                            reconciliation_result["companies_failed"] = list(set(
                                reconciliation_result.get("companies_failed", []) + falsely_claimed
                            ))

                        # Defensive guard: ensure keywords_added matches final observed state
                        observed_keywords = set(filter_analysis.get("observed_keywords", []))
                        claimed_keywords_added = reconciliation_result.get("keywords_added", [])
                        actually_added_keywords = [k for k in claimed_keywords_added if k.lower() in observed_keywords]
                        falsely_claimed_keywords = [k for k in claimed_keywords_added if k.lower() not in observed_keywords]

                        if falsely_claimed_keywords:
                            # Move falsely claimed keywords to failed list
                            reconciliation_result["keywords_added"] = actually_added_keywords
                            reconciliation_result["keywords_failed"] = list(set(
                                reconciliation_result.get("keywords_failed", []) + falsely_claimed_keywords
                            ))

            return {
                "success": True,
                "status": "ready",
                "current_url": current_url,
                "failure_code": None,
                "action_required": None,
                "filter_analysis": filter_analysis,
                "filter_chips": filter_chips,
                "reconciliation": reconciliation_result,
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
            action_required = (
                readiness.action_required.to_dict()
                if readiness.action_required
                else ActionRequired.ambiguous_state(
                    details=f"Browser state: {state}"
                ).to_dict()
            )
            # Enrich browser_unavailable blockers with recovery details
            action_required = _enrich_browser_unavailable_blocker(
                action_required, cdp_port, work_dir, chrome_profile
            )
            return {
                "success": False,
                "status": state,
                "current_url": current_url,
                "failure_code": readiness.action_required.code
                if readiness.action_required
                else FailureCode.AMBIGUOUS_STATE,
                "action_required": action_required,
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


def _ensure_browser_ready(
    ctx: dict[str, Any], cdp_port: str | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Ensure browser is ready for automation, attempting bootstrap if needed.

    Uses existing runtime context + browser utilities to ensure readiness.
    Returns the effective CDP port and optional blocker details if unavailable.

    Args:
        ctx: Runtime context from load_runtime_context()
        cdp_port: Optional preferred CDP port (falls back to profile config)

    Returns:
        Tuple of (effective_cdp_port, blocker_dict_or_none)
        - If browser is ready: (cdp_port, None)
        - If browser unavailable: (cdp_port, blocker_dict_with_recovery_details)
        - If auth required: (cdp_port, blocker_dict_with_auth_required)
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from browser_utils import (
            ActionRequired,
            BrowserMode,
            check_browser_available,
            check_cdp_available,
            probe_recruiter_auth,
            CONNECT_BROWSER_SCRIPT,
            FailureCode,
        )
        from auth_bootstrap import bootstrap_auth_session

        # Use canonical runtime/profile resolution, never skill-dir fallback
        work_dir = Path(ctx["work_dir"]) if ctx.get("work_dir") else Path.home() / "Desktop" / "linkedin-sourcing"
        profile = ctx.get("profile", {})

        effective_cdp_port = cdp_port or profile.get("CDP_PORT", "9234")

        # Resolve Chrome profile path
        chrome_profile = profile.get("CHROME_PROFILE", work_dir / "chrome-profile")
        if isinstance(chrome_profile, str):
            chrome_profile = chrome_profile.replace("$WORK_DIR", str(work_dir))
            chrome_profile = chrome_profile.replace("${WORK_DIR}", str(work_dir))
            chrome_profile = Path(chrome_profile).expanduser()

        # Check if browser is already available and authenticated
        mode = BrowserMode(mode="cdp", cdp_port=effective_cdp_port)
        if check_browser_available(mode):
            auth_check = probe_recruiter_auth(effective_cdp_port)
            if auth_check["authenticated"]:
                return effective_cdp_port, None
            # Browser available but not authenticated - try bootstrap
        else:
            # Browser not available - try bootstrap
            pass

        # Attempt bootstrap with explicit opt-in (we're in a phase runner context)
        bootstrap_result = bootstrap_auth_session(
            work_dir=work_dir,
            preferred_cdp_port=effective_cdp_port,
            chrome_profile=chrome_profile,
            allow_browser_launch=True,
        )

        if bootstrap_result.get("success"):
            effective_port = bootstrap_result.get("cdp_port", effective_cdp_port)
            return effective_port, None

        # Bootstrap failed - determine if it's auth-related or browser-related
        error = bootstrap_result.get("error", "")
        error_lower = error.lower()

        # Check for auth/login related failures (Chrome is up but auth failed)
        if (
            "auth" in error_lower
            or "login" in error_lower
            or "not authenticated" in error_lower
            or "authentication" in error_lower
        ):
            # Auth failure - preserve as user blocker
            blocker = ActionRequired.auth_required()
            blocker.context.update({
                "work_dir": str(work_dir),
                "cdp_port": effective_cdp_port,
                "chrome_profile": str(chrome_profile),
                "bootstrap_error": error,
            })
            return effective_cdp_port, blocker.to_dict()

        # Browser unavailable failure - build rich blocker with recovery details
        blocker = ActionRequired.browser_unavailable(cdp_port=effective_cdp_port)
        # Enrich with exact recovery details from runtime config
        blocker.context.update({
            "work_dir": str(work_dir),
            "cdp_port": effective_cdp_port,
            "chrome_profile": str(chrome_profile),
            "connect_browser_script": str(CONNECT_BROWSER_SCRIPT),
            "recovery_command": f'bash "{CONNECT_BROWSER_SCRIPT}"',
            "agent_browser_command": f"agent-browser --cdp {effective_cdp_port} get url",
        })
        blocker.steps = [
            f"Ensure Chrome is running with CDP enabled on port {effective_cdp_port}",
            f"Run the recovery command: {blocker.context['recovery_command']}",
            "Navigate to LinkedIn Recruiter in the Chrome window",
            "Confirm the Recruiter interface is fully loaded",
            f"Verify connection with: {blocker.context['agent_browser_command']}",
            "Retry the operation once Chrome is ready",
        ]
        return effective_cdp_port, blocker.to_dict()
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))


def run_create_search_phase(
    project_ref: str, cdp_port: str | None = None, brief_only: bool = False
) -> dict[str, Any]:
    """Run the browser-driven Create Search phase."""
    ctx = load_runtime_context()

    # In normal mode (not brief_only), proactively ensure browser is ready
    if not brief_only:
        effective_cdp_port, blocker = _ensure_browser_ready(ctx, cdp_port)
        if blocker:
            # Browser cannot be made ready - return structured blocker immediately
            return {
                "success": False,
                "phase": "create_search",
                "workflow_phases": WORKFLOW_PHASES,
                "status": blocker.get("code", "browser_unavailable"),
                "next_phase": "create_search",
                "project_ref": project_ref,
                "cdp_port": effective_cdp_port,
                "action_required": blocker,
                "message": "Chrome browser is not available for automation",
            }
        cdp_port = effective_cdp_port
    else:
        # brief_only mode: use context CDP port without bootstrap attempt
        if cdp_port is None:
            cdp_port = ctx.get("profile", {}).get("CDP_PORT", "9234")

    # Ensure cdp_port is never None at this point
    effective_cdp_port: str = cdp_port or ctx.get("profile", {}).get("CDP_PORT", "9234")

    config_path, config, recruiter_project_id = resolve_project(project_ref)
    project_dir = config_path.parent
    recruiter_url = config.get("RECRUITER_PROJECT_URL", "")
    if not recruiter_url:
        raise CreateSearchError(
            "RECRUITER_PROJECT_URL is required before creating or verifying a search"
        )

    jd_text = read_jd_text(config_path)
    jd_url = config.get("JD_URL", "")
    search_brief = build_search_brief(config, jd_text, jd_url)

    result = {
        "success": True,
        "phase": "create_search",
        "workflow_phases": WORKFLOW_PHASES,
        "status": "brief_only" if brief_only else "ready",
        "next_phase": "create_search" if brief_only else "confirm_search",
        "project_ref": project_ref,
        "config_path": str(config_path),
        "project_id": config.get("PROJECT_ID", ""),
        "recruiter_project_id": recruiter_project_id,
        "recruiter_url": recruiter_url,
        "cdp_port": effective_cdp_port,
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

    # Use runtime work_dir and chrome_profile from context, not project_dir.parent
    runtime_work_dir = ctx.get("work_dir")
    runtime_chrome_profile = ctx.get("profile", {}).get("CHROME_PROFILE")
    inspection = inspect_search_state(
        effective_cdp_port, recruiter_url,
        work_dir=Path(runtime_work_dir) if runtime_work_dir else None,
        chrome_profile=runtime_chrome_profile,
        config=config,
        jd_text=jd_text,
        jd_url=jd_url,
    )
    result["status"] = inspection.get("status", "unknown")
    result["current_url"] = inspection.get("current_url")
    result["failure_code"] = inspection.get("failure_code")

    # If search is not configured, try creating it via Copilot
    if (
        not inspection.get("success")
        and inspection.get("status") == "search_not_configured"
    ):
        print("Search not configured - attempting AI Copilot search creation...", file=sys.stderr)
        copilot_result = create_initial_search_with_copilot(
            effective_cdp_port,
            recruiter_url,
            config,
            jd_text=jd_text,
            jd_url=jd_url,
            work_dir=Path(runtime_work_dir) if runtime_work_dir else None,
            chrome_profile=runtime_chrome_profile,
        )
        if copilot_result.get("success"):
            # Re-inspect to get full filter analysis
            inspection = inspect_search_state(
                effective_cdp_port,
                recruiter_url,
                work_dir=Path(runtime_work_dir) if runtime_work_dir else None,
                chrome_profile=runtime_chrome_profile,
                config=config,
                jd_text=jd_text,
                jd_url=jd_url,
            )
            result["status"] = inspection.get("status", "unknown")
            result["current_url"] = inspection.get("current_url")
            result["failure_code"] = inspection.get("failure_code")
        else:
            # Copilot creation failed - preserve the failure details
            result["success"] = False
            result["status"] = copilot_result.get("status", "copilot_failed")
            result["failure_code"] = copilot_result.get("failure_code")
            result["action_required"] = copilot_result.get("action_required")
            result["message"] = f"AI Copilot search creation failed: {copilot_result.get('status')}"
            return result

    # Update project state based on result
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from project_state import update_project_state

        if inspection.get("success"):
            # Build result summary including filter analysis details
            filter_analysis = inspection.get("filter_analysis")
            reconciliation = inspection.get("reconciliation")
            summary_parts = ["Recruiter search verified with visible candidates"]

            # Include reconciliation results if attempted
            if reconciliation and reconciliation.get("attempted"):
                if reconciliation.get("companies_added"):
                    added = reconciliation["companies_added"]
                    summary_parts.append(f"Auto-added companies: {', '.join(added[:5])}")
                if reconciliation.get("companies_failed"):
                    failed = reconciliation["companies_failed"]
                    summary_parts.append(f"Failed to add companies: {', '.join(failed[:5])}")
                if reconciliation.get("keywords_added"):
                    added = reconciliation["keywords_added"]
                    summary_parts.append(f"Auto-added keywords: {', '.join(added[:5])}")
                if reconciliation.get("keywords_failed"):
                    failed = reconciliation["keywords_failed"]
                    summary_parts.append(f"Failed to add keywords: {', '.join(failed[:5])}")
                if reconciliation.get("titles_removed"):
                    removed = reconciliation["titles_removed"]
                    summary_parts.append(f"Auto-removed malformed titles: {', '.join(removed[:3])}")
                if reconciliation.get("titles_failed"):
                    failed = reconciliation["titles_failed"]
                    summary_parts.append(f"Failed to remove titles: {', '.join(failed[:3])}")
                if reconciliation.get("errors"):
                    summary_parts.append(f"Reconciliation errors: {len(reconciliation['errors'])}")

            if filter_analysis:
                if filter_analysis.get("issues"):
                    summary_parts.append(f"Issues: {len(filter_analysis['issues'])}")
                    # Include actual issue details for operator visibility
                    for issue in filter_analysis["issues"]:
                        summary_parts.append(f"Issue: {issue}")
                if filter_analysis.get("missing_companies"):
                    missing = filter_analysis["missing_companies"]
                    summary_parts.append(f"Missing companies: {', '.join(missing[:5])}")
                if filter_analysis.get("missing_keywords"):
                    missing = filter_analysis["missing_keywords"]
                    summary_parts.append(f"Missing keywords: {', '.join(missing[:5])}")
                if filter_analysis.get("malformed_titles"):
                    malformed = filter_analysis["malformed_titles"]
                    summary_parts.append(f"Malformed titles: {', '.join(malformed[:3])}")
                if filter_analysis.get("observed_companies"):
                    observed = filter_analysis["observed_companies"]
                    summary_parts.append(f"Observed companies: {', '.join(observed[:5])}")
                if filter_analysis.get("observed_keywords"):
                    observed = filter_analysis["observed_keywords"]
                    summary_parts.append(f"Observed keywords: {', '.join(observed[:5])}")

            update_project_state(
                project_dir=project_dir,
                current_phase="create_search",
                status="completed",
                action_required=False,
                last_result_summary="; ".join(summary_parts),
                last_error=False,
                create_search_summary={
                    "filter_analysis": filter_analysis,
                    "reconciliation": reconciliation,
                },
            )
        elif inspection.get("action_required"):
            update_project_state(
                project_dir=project_dir,
                current_phase="create_search",
                status="action_required",
                action_required=inspection["action_required"],
                last_result_summary="Browser intervention required",
                last_error=False,
                create_search_summary=False,
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
                last_error=False,
                create_search_summary=False,
            )
    finally:
        if str(SCRIPT_DIR) in sys.path:
            sys.path.remove(str(SCRIPT_DIR))

    if inspection.get("success"):
        result["message"] = "Recruiter search has visible candidates - awaiting confirmation"
        result["filter_analysis"] = inspection.get("filter_analysis")
        result["filter_chips"] = inspection.get("filter_chips")
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
        "Open the Recruiter project and create the candidate search using the provided search brief"
    )
    return result


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create or verify a Recruiter search (internal/advanced use only)"
    )
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
