#!/usr/bin/env python3
"""Bootstrap a new LinkedIn sourcing project from a JD URL or raw JD text.

The canonical flow derives PROJECT_ID from LinkedIn Recruiter project identity:
1. If --recruiter-url is provided, extract the numeric ID from /talent/hire/{id}/
2. If --recruiter-url is not provided, create/ensure the Recruiter project first,
   then derive PROJECT_ID from the resulting project
3. Fail closed if Recruiter identity cannot be resolved

Usage:
    python3 bootstrap_project.py --jd-url <url> [--work-dir <dir>] [--recruiter-url <url>] [overrides...]
    python3 bootstrap_project.py --jd-text <text> [--work-dir <dir>] [--recruiter-url <url>] [overrides...]

Required (one of):
    --jd-url URL          Job description URL (supports lifeattiktok.com and generic URLs)
    --jd-text TEXT        Raw job description text (use @file.txt to read from file)

Optional:
    --work-dir DIR        Working directory for projects (default: ~/Desktop/linkedin-sourcing)
    --recruiter-url URL   LinkedIn Recruiter project URL (if not provided, will create/ensure project)
    --cdp-port PORT       Chrome DevTools Protocol port for ensure_recruiter_project (default: 9230)
    --project-id ID       Override project identifier (only for advanced use; normally derived from Recruiter)
    --position-title TITLE    Override position title
    --team-name NAME      Override team name
    --location LOC        Override location
    --core-function DESC  Override core function description
    --business-impact DESC    Override business impact description
    --keywords KW         Override keywords (comma-separated)
    --companies COS       Override target companies (comma-separated)
    --exclude-titles TITLES   Override excluded titles (comma-separated)

Examples:
    # Auto-create Recruiter project and derive PROJECT_ID (canonical flow)
    python3 bootstrap_project.py --jd-url "https://lifeattiktok.com/search/7623929928426277125"

    # Use existing Recruiter project URL
    python3 bootstrap_project.py --jd-url "https://example.com/job" --recruiter-url "https://linkedin.com/talent/hire/12345/"

    # From file with overrides
    python3 bootstrap_project.py --jd-text @job_description.txt --position-title "Senior Engineer"

Output:
    Prints JSON with created paths and inferred fields:
    {
        "project_id": "...",
        "project_dir": "...",
        "workbook_path": "...",
        "config_path": "...",
        "jd_path": "...",
        "recruiter_url": "...",
        "inferred": {
            "position_title": "...",
            "team_name": "...",
            "location": "...",
            "job_code": "..."
        },
        "next_steps": ["..."]
    }
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))
# Import auth_bootstrap for browser availability check
import auth_bootstrap
from config_utils import parse_config_file
from excel_utils import create
from recruiter_url_utils import (
    build_project_overview_url,
    extract_recruiter_id_from_url,
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Bootstrap a LinkedIn sourcing project from JD URL or text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment:
    LINKEDIN_SOURCING_WORK_DIR    Default work directory (overrides ~/Desktop default)

Notes:
    - TikTok URLs are fetched and parsed for basic metadata (title, location, job code)
    - For other URLs, raw HTML is saved; human review required for extraction
    - PROJECT_ID is derived from LinkedIn Recruiter project identity (not generated locally)
    - If --recruiter-url is not provided, Chrome with CDP must be running to create/ensure project
    - All inferred fields can be overridden via CLI flags
        """,
    )

    # Source input (required - one of)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--jd-url",
        metavar="URL",
        help="Job description URL to fetch and parse",
    )
    source_group.add_argument(
        "--jd-text",
        metavar="TEXT",
        help="Raw job description text (prefix with @ to read from file)",
    )

    # Project configuration
    parser.add_argument(
        "--work-dir",
        metavar="DIR",
        help="Working directory for projects (default: ~/Desktop/linkedin-sourcing)",
    )
    parser.add_argument(
        "--recruiter-url",
        metavar="URL",
        help="LinkedIn Recruiter project URL (if not provided, will create/ensure project via browser automation)",
    )
    parser.add_argument(
        "--cdp-port",
        metavar="PORT",
        default="9230",
        help="Chrome DevTools Protocol port for ensure_recruiter_project (default: 9230)",
    )
    parser.add_argument(
        "--project-id",
        metavar="ID",
        help="Override project identifier (advanced use only; normally derived from Recruiter URL)",
    )

    # Field overrides
    parser.add_argument(
        "--position-title",
        metavar="TITLE",
        help="Position title (e.g., 'Senior ML Engineer')",
    )
    parser.add_argument(
        "--team-name",
        metavar="NAME",
        help="Team name (e.g., 'AI Platform')",
    )
    parser.add_argument(
        "--location",
        metavar="LOC",
        help="Job location (e.g., 'San Jose, CA' or 'Remote')",
    )
    parser.add_argument(
        "--core-function",
        metavar="DESC",
        help="Core function description (e.g., 'building ML infrastructure')",
    )
    parser.add_argument(
        "--business-impact",
        metavar="DESC",
        help="Business impact description (e.g., 'improving user experience')",
    )
    parser.add_argument(
        "--keywords",
        metavar="KW",
        help="Keywords for candidate matching (comma-separated)",
    )
    parser.add_argument(
        "--companies",
        metavar="COS",
        help="Target companies (comma-separated)",
    )
    parser.add_argument(
        "--exclude-titles",
        metavar="TITLES",
        help="Titles to exclude (comma-separated, e.g., 'Manager,Director,VP')",
    )
    parser.add_argument(
        "--hiring-company",
        metavar="COMPANY",
        help="Hiring company name (e.g., 'TikTok', 'ByteDance'). Auto-excludes from target companies.",
    )

    return parser.parse_args()


def get_work_dir(cli_value: str | None) -> Path:
    """Resolve working directory from CLI arg or environment.

    Uses RuntimeManager for consistent profile resolution.
    """
    if cli_value:
        return Path(cli_value).expanduser().resolve()

    # Use RuntimeManager for consistent profile resolution
    from runtime_manager import RuntimeManager

    manager = RuntimeManager()
    return manager.work_dir


def check_existing_project_by_recruiter_id(
    work_dir: Path, recruiter_id: str
) -> Path | None:
    """Check if a project already exists for the given recruiter ID.

    Args:
        work_dir: The working directory
        recruiter_id: The LinkedIn Recruiter project ID

    Returns:
        Path to existing config.sh if found, None otherwise
    """
    projects_dir = work_dir / "projects"
    if not projects_dir.exists():
        return None

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        config_path = project_dir / "config.sh"
        if not config_path.exists():
            continue

        config = parse_config_file(config_path)
        recruiter_url = config.get("RECRUITER_PROJECT_URL", "")
        existing_id = extract_recruiter_id_from_url(recruiter_url)
        if existing_id == recruiter_id:
            return config_path

    return None


def ensure_browser_auth(work_dir: Path, cdp_port: str) -> dict[str, Any]:
    """Ensure a headed browser is available and authenticated to LinkedIn Recruiter.

    Delegates to auth_bootstrap.bootstrap_auth_session for the canonical auth flow,
    then transforms the result into the format expected by bootstrap_project callers.

    Args:
        work_dir: Working directory for runtime data
        cdp_port: Preferred Chrome DevTools Protocol port

    Returns:
        Dict with success status, browser mode, and error message if failed.
    """
    from browser_utils import ActionRequired, BrowserMode, FailureCode

    result = auth_bootstrap.bootstrap_auth_session(
        work_dir=work_dir,
        preferred_cdp_port=cdp_port,
        allow_browser_launch=True,
    )

    if result["success"]:
        mode_str = result.get("mode", "cdp")
        headed = result.get("headed", True)
        if mode_str == "cdp":
            return {
                "success": True,
                "mode": BrowserMode(
                    mode="cdp",
                    cdp_port=result.get("cdp_port", cdp_port),
                    headed=headed,
                ),
                "error": None,
                "action_required": None,
                "failure_code": None,
            }
        else:
            # Agent-browser mode (legacy/unsupported in bootstrap)
            return {
                "success": True,
                "mode": BrowserMode(
                    mode="agent-browser",
                    session_name=result.get("session_name"),
                    auth_file=result.get("auth_file"),
                    headed=headed,
                ),
                "error": None,
                "action_required": None,
                "failure_code": None,
            }

    # Failure — map to structured action_required
    error = result.get("error", "Unknown auth failure")
    if "not allowed without explicit opt-in" in error:
        return {
            "success": False,
            "mode": None,
            "error": error,
            "action_required": ActionRequired.browser_unavailable(
                cdp_port=cdp_port
            ).to_dict(),
            "failure_code": FailureCode.BROWSER_UNAVAILABLE,
        }

    return {
        "success": False,
        "mode": None,
        "error": error,
        "action_required": ActionRequired.auth_required().to_dict(),
        "failure_code": FailureCode.AUTH_REQUIRED,
    }


def ensure_recruiter_project_and_get_id(
    project_name: str,
    description: str,
    browser_mode: "BrowserMode | str",
    work_dir: Path,
) -> dict[str, Any]:
    """Ensure Recruiter project exists and return its ID and URL.

    Args:
        project_name: Name for the Recruiter project
        description: Description for the project
        browser_mode: BrowserMode instance or CDP port string for browser operations
        work_dir: Working directory for incident reporting

    Returns:
        Dict with success status, project_id, url, and error message if failed
    """
    # Import here to avoid circular dependencies
    from ensure_recruiter_project import ensure_project_exists

    result = ensure_project_exists(
        project_name=project_name,
        description=description,
        browser_mode=browser_mode,
        work_dir=str(work_dir),
        require_contextual_url=False,  # Bootstrap only needs project identity, not search URL
    )

    return {
        "success": result["status"] in ("existing", "created"),
        "project_id": result.get("project_id"),
        "url": result.get("url"),
        "status": result["status"],
        "message": result.get("message", ""),
        "failure_code": result.get("failure_code"),
        "action_required": result.get("action_required"),
    }


def fetch_url(url: str, timeout: int = 30) -> tuple[int, str]:
    """Fetch URL content with basic error handling.

    Returns:
        Tuple of (status_code, content or error_message)
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "identity",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="replace")
            return response.getcode(), content
    except HTTPError as e:
        return e.code, f"HTTP Error: {e.reason}"
    except URLError as e:
        return 0, f"URL Error: {e.reason}"
    except Exception as e:
        return 0, f"Error: {str(e)}"


def normalize_to_plain_text(content: str) -> str:
    """Normalize content to UTF-8 plain text, stripping HTML if present.

    Best-effort conversion that:
    - Strips HTML tags, scripts, and styles
    - Preserves basic paragraph and list structure
    - Normalizes whitespace
    - Keeps UTF-8 plain text output

    If content is already plain text (no HTML markers), applies light
    whitespace normalization only.

    Args:
        content: Raw content (may be HTML or plain text)

    Returns:
        Normalized plain text
    """
    if not content:
        return ""

    # Check if content looks like HTML
    looks_like_html = bool(
        re.search(
            r"<\s*!doctype|<\s*html|<\s*head|<\s*body|<\s*div|<\s*p\b|<\s*h[1-6]\b|"
            r"<\s*title\b|<\s*meta\b|<\s*script\b|<\s*style\b|</[a-z][^>]*>",
            content,
            re.IGNORECASE,
        )
    )

    if not looks_like_html:
        # Already plain text - just normalize whitespace
        return re.sub(r"\s+", " ", content).strip()

    # HTML content - convert to plain text
    text = content

    # Remove scripts and styles first (they may contain text that looks like content)
    text = re.sub(
        r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(
        r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL
    )

    # Convert common block elements to newlines for structure preservation
    block_elements = r"<(p|div|h[1-6]|li|tr|td|th|br)\b[^>]*>"
    text = re.sub(block_elements, "\n", text, flags=re.IGNORECASE)

    # Remove remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Decode HTML entities
    text = html.unescape(text)

    # Normalize whitespace: collapse multiple spaces, preserve paragraph breaks
    lines = text.split("\n")
    normalized_lines = []
    for line in lines:
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            normalized_lines.append(line)

    # Join with double newlines for paragraph separation
    text = "\n\n".join(normalized_lines)

    return text.strip()


def extract_tiktok_metadata(html: str) -> dict[str, str]:
    """Extract basic metadata from TikTok job page HTML.

    Uses lightweight regex patterns - no heavy parsing libraries.
    Returns empty strings for fields that cannot be found.
    """
    metadata = {
        "position_title": "",
        "team_name": "",
        "location": "",
        "job_code": "",
        "core_function": "",
        "business_impact": "",
        "keywords": "",
        "description": "",
    }

    html_text = re.sub(r"<[^>]+>", " ", html)
    html_text = re.sub(r"\s+", " ", html_text).strip()

    def normalize_text(value: str) -> str:
        """Normalize scraped text for config-safe output."""
        return re.sub(r"\s+", " ", value.replace("\\n", " ")).strip()

    # Try to extract job title from various patterns
    title_patterns = [
        r"<h1[^>]*>([^<]+)</h1>",  # Simple h1
        r'"jobTitle"\s*:\s*"([^"]+)"',  # JSON-LD
        r"<title>([^<]+)</title>",  # Page title
        r'data-testid="job-title"[^>]*>([^<]+)',  # Test ID
    ]

    for pattern in title_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            # Clean up common suffixes
            title = re.sub(r"\s*[-|]\s*TikTok\s*$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s*[-|]\s*ByteDance\s*$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s*[-|]\s*Careers?\s*$", "", title, flags=re.IGNORECASE)
            if title and len(title) > 3:
                metadata["position_title"] = title
                break

    # Extract location
    location_patterns = [
        r'"jobLocation"[^}]*"address"[^}]*"addressLocality"\s*:\s*"([^"]+)"',
        r'"addressLocality"\s*:\s*"([^"]+)"',
        r'location["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'class="[^"]*location[^"]*"[^>]*>([^<]+)',
    ]

    for pattern in location_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            location = match.group(1).strip()
            if location and len(location) > 2:
                metadata["location"] = location
                break

    if not metadata["location"]:
        label_match = re.search(
            r'\\"Location\\".*?\\"children\\":\\"([^\\"]+)\\"',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if label_match:
            metadata["location"] = label_match.group(1).strip()

    if not metadata["location"]:
        label_match = re.search(
            r"Location:\s*([A-Za-z][A-Za-z\s,.-]+?)\s+(?:Employment Type:|Job Code:)",
            html_text,
            re.IGNORECASE,
        )
        if label_match:
            metadata["location"] = label_match.group(1).strip()

    # Extract job code from URL patterns or content
    job_code_patterns = [
        r"/search/(\d+)",  # TikTok URL pattern
        r'job[_-]?code["\']?\s*[:=]\s*["\']?([A-Z0-9-]+)',
        r'requisition[_-]?id["\']?\s*[:=]\s*["\']?([A-Z0-9-]+)',
    ]

    for pattern in job_code_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            metadata["job_code"] = match.group(1)
            break

    if not metadata["job_code"]:
        label_match = re.search(
            r'\\"Job Code\\".*?\\"children\\":\\"([A-Z0-9-]+)\\"',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if label_match:
            metadata["job_code"] = label_match.group(1).strip()

    if not metadata["job_code"]:
        label_match = re.search(r"Job Code:\s*([A-Z0-9-]+)", html_text, re.IGNORECASE)
        if label_match:
            metadata["job_code"] = label_match.group(1).strip()

    team_match = re.search(
        r"(?:^|\s)(Technology|Product|Design|E-Commerce|Advertising\s*&\s*Sales|Corporate Functions|Global Operations|Marketing\s*&\s*Communications|TikTok USDS Joint Venture)\s+##\s+",
        html_text,
        re.IGNORECASE,
    )
    if team_match:
        metadata["team_name"] = team_match.group(1).replace("  ", " ").strip()

    about_team_match = re.search(
        r"About the team:\s*(.+?)(?:Responsibilities\s*-|Qualifications|Job Information)",
        html_text,
        re.IGNORECASE,
    )
    if about_team_match:
        about_team = about_team_match.group(1).strip()
        sentences = [
            s.strip(" .") for s in re.split(r"(?<=[.!?])\s+", about_team) if s.strip()
        ]
        if sentences:
            metadata["core_function"] = normalize_text(sentences[0])
        impact_match = re.search(
            r"to\s+([^.]+(?:users|creators|customers|businesses|platforms|services))",
            about_team,
            re.IGNORECASE,
        )
        if impact_match:
            metadata["business_impact"] = normalize_text(impact_match.group(1))

    # Use shared keyword extraction for consistent results
    keywords = extract_keywords_from_text(html_text)
    metadata["keywords"] = ", ".join(keywords)

    # Extract description (first substantial paragraph)
    desc_patterns = [
        r'<meta[^>]*description[^>]*content="([^"]+)"',
        r"<div[^>]*job-description[^>]*>(.*?)</div>",
        r"<section[^>]*description[^>]*>(.*?)</section>",
    ]

    for pattern in desc_patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            desc = match.group(1)
            # Strip HTML tags
            desc = re.sub(r"<[^>]+>", " ", desc)
            # Normalize whitespace
            desc = re.sub(r"\s+", " ", desc).strip()
            if len(desc) > 50:
                metadata["description"] = desc[:2000]  # Limit length
                break

    return metadata


# Shared keyword rule table for conservative keyword extraction
# Each rule: (pattern, [keywords_to_add])
# Patterns are matched case-insensitively with word boundaries where appropriate
KEYWORD_RULES: list[tuple[str, list[str]]] = [
    # Programming languages
    (r"\bpython\b", ["Python"]),
    (r"\bjava\b", ["Java"]),
    (
        r"\bgolang\b|\bgo\b(?=\s+(developer|engineer|programming|language|backend|services?|microservices?))",
        ["Go"],
    ),
    (r"\brust\b", ["Rust"]),
    (r"\bc\+\+|\bcpp\b", ["C++"]),
    (r"\bjavascript\b|\bjs\b", ["JavaScript"]),
    (r"\btypescript\b|\bts\b", ["TypeScript"]),
    # ML/AI frameworks
    (r"\bpytorch\b", ["PyTorch", "Deep Learning"]),
    (r"\btensorflow\b|\btf\b", ["TensorFlow", "Keras"]),
    (r"\bkeras\b", ["Keras"]),
    (r"\bneural\b|\bdeep learning\b", ["Deep Learning", "Neural Networks"]),
    (r"\bcuda\b", ["CUDA", "GPU Optimization"]),
    (r"\bgpu\b", ["GPU Optimization"]),
    (r"\bkernel\b", ["Kernel Development"]),
    (
        r"\bdistributed\b|\blarge[- ]?scale\b",
        ["Distributed Training", "Large-Scale Systems"],
    ),
    (r"\bmachine learning\b|\bml\b", ["Machine Learning", "ML Systems"]),
    # Infrastructure/DevOps
    (r"\bkubernetes\b|\bk8s\b", ["Kubernetes", "Container Orchestration"]),
    (r"\bdocker\b", ["Docker", "Containerization"]),
    (r"\bterraform\b", ["Terraform", "Infrastructure as Code"]),
    (r"\baws\b|\bamazon web services\b", ["AWS", "Cloud Infrastructure"]),
    (r"\bgcp\b|\bgoogle cloud\b", ["GCP", "Cloud Infrastructure"]),
    (r"\bazure\b", ["Azure", "Cloud Infrastructure"]),
    (r"\bcdn\b", ["CDN", "Content Delivery"]),
    (r"\binfrastructure\b|\bplatform\b", ["Infrastructure", "Platform Engineering"]),
    (r"\bdistributed systems\b", ["Distributed Systems"]),
    (r"\bcloud infrastructure\b", ["Cloud Infrastructure"]),
    (r"\btraffic management\b", ["Traffic Management"]),
    (r"\bload balancing\b", ["Load Balancing"]),
    (r"\bedge computing\b", ["Edge Computing"]),
    # Hardware/Embedded
    (r"\bverilog\b|\bsystemverilog\b", ["Verilog", "SystemVerilog"]),
    (r"\bsoc\b", ["SoC Design"]),
    (r"\brtl\b", ["RTL Design"]),
    (r"\bfpga\b", ["FPGA"]),
    (r"\basic\b", ["ASIC"]),
    (r"\bvideo codec\b|\bencoding\b", ["Video Codec"]),
    (r"\bcdc\b|\bclock domain crossing\b", ["CDC"]),
    (r"\brdc\b|\breset domain crossing\b", ["RDC"]),
    (r"\blow[- ]?power\b|\bpower gating\b|\bclock gating\b", ["Low Power Design"]),
    (r"\bnpu\b|\bai hardware\b", ["AI Hardware Acceleration"]),
    (
        r"\bsynthesis\b|\bsta\b|\bstatic timing\b",
        ["Synthesis", "Static Timing Analysis"],
    ),
]


def extract_keywords_from_text(text: str, jd_text: str | None = None) -> list[str]:
    """Extract keywords from text using shared rule table.

    Applies conservative keyword rules with whole-word matching.
    Results are deduplicated while preserving order of first match.

    Args:
        text: Primary text to search (e.g., position title, HTML content)
        jd_text: Optional additional JD text for fallback inference

    Returns:
        List of extracted keywords in order of first match
    """
    if not text:
        text = ""

    # Combine text sources if jd_text provided
    search_text = text
    if jd_text:
        search_text = f"{text} {jd_text}"

    text_lower = search_text.lower()
    keywords: list[str] = []
    seen: set[str] = set()

    for pattern, keywords_to_add in KEYWORD_RULES:
        if re.search(pattern, text_lower, re.IGNORECASE):
            for kw in keywords_to_add:
                if kw.lower() not in seen:
                    keywords.append(kw)
                    seen.add(kw.lower())

    return keywords


def infer_team_name(position_title: str) -> str:
    """Infer team name from position title."""
    if not position_title:
        return ""

    title_lower = position_title.lower()

    # Common team mappings
    if any(kw in title_lower for kw in ["ml", "machine learning", "ai ", "model"]):
        return "AI/ML Platform"
    if any(
        kw in title_lower
        for kw in [
            "soc",
            "rtl",
            "verilog",
            "systemverilog",
            "fpga",
            "asic",
            "codec",
            "hardware",
        ]
    ):
        return "Engineering & Technology"
    if any(kw in title_lower for kw in ["infra", "platform", "infrastructure"]):
        return "Infrastructure Platform"
    if any(kw in title_lower for kw in ["data", "analytics"]):
        return "Data Platform"
    if any(kw in title_lower for kw in ["search", "recommendation", "recsys"]):
        return "Search & Recommendations"
    if any(kw in title_lower for kw in ["frontend", "ui", "ux", "web"]):
        return "Frontend Platform"
    if any(kw in title_lower for kw in ["backend", "server", "api"]):
        return "Backend Platform"

    return "Engineering"


def infer_keywords(position_title: str, jd_text: str | None = None) -> str:
    """Infer keywords from position title and optional JD text.

    Uses the shared keyword rule table for conservative extraction.
    Precedence: explicit title keywords > JD fallback keywords

    Args:
        position_title: Position title to infer from
        jd_text: Optional JD text for additional keyword inference

    Returns:
        Comma-separated string of inferred keywords
    """
    keywords = extract_keywords_from_text(position_title, jd_text)
    return ", ".join(keywords) if keywords else ""


def get_default_companies() -> str:
    """Return default target companies."""
    return "Google, Meta, OpenAI, Anthropic, DeepMind, Microsoft, NVIDIA, Amazon, Apple, Netflix"


def get_default_exclude_titles() -> str:
    """Return default excluded titles."""
    return "Manager, Director, VP, Head of, Product Manager, Data Scientist, QA Engineer, Recruiter, HR"


def build_config(
    project_id: str,
    inferred: dict[str, str],
    overrides: dict[str, str | None],
    existing: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build project configuration with overrides and existing value preservation.

    Merge order (highest to lowest precedence):
    1. CLI overrides (user explicitly provided)
    2. Existing config values (when reusing a project)
    3. Inferred values from JD
    4. Defaults

    Args:
        project_id: The project identifier (authoritative)
        inferred: Values inferred from JD parsing
        overrides: CLI override values
        existing: Existing config values when reusing a project

    Returns:
        Complete configuration dict
    """
    existing = existing or {}
    fallback_keyword_text = " ".join(
        part
        for part in [
            inferred.get("description", ""),
            inferred.get("core_function", ""),
            inferred.get("business_impact", ""),
            inferred.get("team_name", ""),
        ]
        if part
    )

    # Helper to get value with proper precedence: override > existing > inferred > default
    def get_value(
        override_key: str,
        inferred_key: str,
        existing_key: str,
        default: str,
        infer_fn=None,
    ) -> str:
        # CLI override takes highest precedence
        if overrides.get(override_key):
            return overrides[override_key]
        # Existing curated value (when reusing project)
        existing_val = existing.get(existing_key, "")
        if existing_val and not existing_val.startswith("["):
            return existing_val
        # Inferred from JD
        inferred_val = inferred.get(inferred_key, "")
        if inferred_val:
            return inferred_val
        # Inference function as fallback
        if infer_fn:
            inferred_from_fn = infer_fn(inferred.get("position_title", ""))
            if inferred_from_fn:
                return inferred_from_fn
        # Default placeholder
        return default

    config = {
        "PROJECT_ID": project_id,
        "POSITION_TITLE": get_value(
            "position_title",
            "position_title",
            "POSITION_TITLE",
            "[POSITION TITLE - PLEASE UPDATE]",
        ),
        "TEAM_NAME": get_value(
            "team_name",
            "team_name",
            "TEAM_NAME",
            "[TEAM NAME - PLEASE UPDATE]",
            infer_team_name,
        ),
        "LOCATION": get_value(
            "location", "location", "LOCATION", "[LOCATION - PLEASE UPDATE]"
        ),
        "CORE_FUNCTION": get_value(
            "core_function",
            "core_function",
            "CORE_FUNCTION",
            "[AGENT: infer from JD - what does this team do?]",
        ),
        "BUSINESS_IMPACT": get_value(
            "business_impact",
            "business_impact",
            "BUSINESS_IMPACT",
            "[AGENT: infer from JD - why does this work matter?]",
        ),
        "KEYWORDS": (
            overrides.get("keywords")
            or (
                existing.get("KEYWORDS", "")
                if existing.get("KEYWORDS", "")
                and not existing.get("KEYWORDS", "").startswith("[")
                else ""
            )
            or inferred.get("keywords", "")
            or infer_keywords(inferred.get("position_title", ""), fallback_keyword_text)
            or ""
        ),
        "COMPANIES": overrides.get("companies")
        or existing.get("COMPANIES", "")
        or get_default_companies(),
        "EXCLUDE_TITLES": overrides.get("exclude_titles")
        or existing.get("EXCLUDE_TITLES", "")
        or get_default_exclude_titles(),
        "HIRING_COMPANY": overrides.get("hiring_company")
        or existing.get("HIRING_COMPANY", "")
        or "",
        "DAILY_LIMIT": existing.get("DAILY_LIMIT", "200"),
        "CANDIDATE_DELAY_SEC": existing.get("CANDIDATE_DELAY_SEC", "10"),
    }

    # Add recruiter URL if provided (authoritative from bootstrap)
    recruiter_url = overrides.get("recruiter_url")
    if recruiter_url:
        config["RECRUITER_PROJECT_URL"] = recruiter_url
    elif existing.get("RECRUITER_PROJECT_URL"):
        config["RECRUITER_PROJECT_URL"] = existing["RECRUITER_PROJECT_URL"]

    # Add JD URL for deduplication (persisted for future exact URL matching)
    jd_url = overrides.get("jd_url")
    if jd_url:
        config["JD_URL"] = jd_url
    elif existing.get("JD_URL"):
        config["JD_URL"] = existing["JD_URL"]

    return config


def shell_escape(value: str) -> str:
    """Escape a string for safe use in shell variable assignment.

    Uses shlex.quote to handle quotes, newlines, backslashes, and other
    special characters safely while keeping the output readable.
    """
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    return shlex.quote(value)


def write_config(config: dict[str, str], config_path: Path) -> None:
    """Write configuration to config.sh file."""
    lines = [
        "# LinkedIn Sourcing Project Configuration",
        "# Generated by bootstrap_project.py",
        "",
        f"PROJECT_ID={shell_escape(config['PROJECT_ID'])}",
        f"POSITION_TITLE={shell_escape(config['POSITION_TITLE'])}",
        f"TEAM_NAME={shell_escape(config['TEAM_NAME'])}",
        f"LOCATION={shell_escape(config['LOCATION'])}",
        f"CORE_FUNCTION={shell_escape(config['CORE_FUNCTION'])}",
        f"BUSINESS_IMPACT={shell_escape(config['BUSINESS_IMPACT'])}",
        "",
        "# Search and filtering configuration",
        f"KEYWORDS={shell_escape(config['KEYWORDS'])}",
        f"COMPANIES={shell_escape(config['COMPANIES'])}",
        f"EXCLUDE_TITLES={shell_escape(config['EXCLUDE_TITLES'])}",
        "",
        "# Hiring company (optional): set to auto-exclude hiring company from target companies",
        "# e.g., HIRING_COMPANY='TikTok' will exclude TikTok/ByteDance from the company filter",
        f"HIRING_COMPANY={shell_escape(config.get('HIRING_COMPANY', ''))}",
        "",
        "# Rate limiting",
        f"DAILY_LIMIT={shell_escape(config['DAILY_LIMIT'])}",
        f"CANDIDATE_DELAY_SEC={shell_escape(config['CANDIDATE_DELAY_SEC'])}",
    ]

    if "RECRUITER_PROJECT_URL" in config:
        lines.extend(
            [
                "",
                "# LinkedIn Recruiter project URL (auto-configured from project identity)",
                f"RECRUITER_PROJECT_URL={shell_escape(config['RECRUITER_PROJECT_URL'])}",
            ]
        )

    if "JD_URL" in config:
        lines.extend(
            [
                "",
                "# JD source URL (for deduplication)",
                f"JD_URL={shell_escape(config['JD_URL'])}",
            ]
        )

    lines.extend(
        [
            "",
            "# Notes:",
            "# - Update fields marked with [PLEASE UPDATE] before running extraction",
            "# - RECRUITER_PROJECT_URL must be set to enable candidate extraction",
            "# - See SKILL.md for full workflow documentation",
        ]
    )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines))


def read_jd_text(source: str) -> str:
    """Read JD text from string or file."""
    if source.startswith("@"):
        file_path = Path(source[1:]).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"JD file not found: {file_path}")
        return file_path.read_text(encoding="utf-8")
    return source


def extract_title_from_jd_content(jd_content: str) -> str | None:
    """Extract a position title from raw JD content.

    Uses a simple deterministic heuristic: take the first meaningful non-empty line
    and strip common prefixes like "Title:" or "Job Title:" if present.

    Args:
        jd_content: Raw job description text

    Returns:
        Extracted title string or None if no meaningful title found
    """
    if not jd_content or not jd_content.strip():
        return None

    def strip_tags(text: str) -> str:
        """Remove HTML tags and normalize whitespace."""
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    def normalize_candidate(text: str) -> str:
        """Normalize title candidates extracted from HTML metadata."""
        cleaned = strip_tags(text)
        for separator in (" | ", " – ", " — ", " - "):
            if separator in cleaned:
                cleaned = cleaned.split(separator, 1)[0].strip()
        return cleaned

    looks_like_html = bool(
        re.search(
            r"<\s*!doctype|<\s*html|<\s*head|<\s*body|<\s*h1\b|<\s*title\b|<\s*meta\b|</[a-z][^>]*>",
            jd_content,
            re.IGNORECASE,
        )
    )
    candidate_lines: list[str] = []

    if looks_like_html:
        html_patterns = [
            r"<meta\b[^>]*\bproperty=[\"']og:title[\"'][^>]*\bcontent=[\"']([^\"']+)[\"']",
            r"<meta\b[^>]*\bcontent=[\"']([^\"']+)[\"'][^>]*\bproperty=[\"']og:title[\"']",
            r"<meta\b[^>]*\bname=[\"']title[\"'][^>]*\bcontent=[\"']([^\"']+)[\"']",
            r"<meta\b[^>]*\bcontent=[\"']([^\"']+)[\"'][^>]*\bname=[\"']title[\"']",
            r"<h1\b[^>]*>(.*?)</h1>",
            r"<title\b[^>]*>(.*?)</title>",
        ]
        for pattern in html_patterns:
            match = re.search(pattern, jd_content, re.IGNORECASE | re.DOTALL)
            if match:
                candidate = normalize_candidate(match.group(1))
                if candidate:
                    candidate_lines.append(candidate)

        text_content = html.unescape(re.sub(r"<[^>]+>", "\n", jd_content))
        candidate_lines.extend(text_content.splitlines())
    else:
        candidate_lines = jd_content.splitlines()

    # Common prefixes to strip (case-insensitive)
    prefixes = [
        r"^\s*title\s*:?\s*",
        r"^\s*job\s*title\s*:?\s*",
        r"^\s*position\s*:?\s*",
        r"^\s*position\s*title\s*:?\s*",
        r"^\s*role\s*:?\s*",
        r"^\s*job\s*role\s*:?\s*",
        r"^\s*#+\s*",  # Markdown headers
    ]

    # Words that indicate a line is NOT a title (description markers)
    description_markers = [
        "description",
        "responsibilities",
        "qualifications",
        "requirements",
        "about",
        "overview",
        "summary",
        "we are",
        "we're",
        "our company",
        "the role",
        "the position",
        "what you'll do",
        "what you will",
        "who you are",
    ]

    # Split into lines and find first non-empty meaningful line
    for line in candidate_lines:
        line = line.strip()
        if not line:
            continue

        # Skip lines that are clearly not titles (URLs, markers, etc.)
        if line.startswith(("http://", "https://", "---", "===", "```")):
            continue
        if len(line) < 3:
            continue

        # Strip common prefixes
        cleaned = line
        for prefix in prefixes:
            cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()
        if cleaned and len(cleaned) >= 3:
            # Check if this looks like a description, not a title
            cleaned_lower = cleaned.lower()
            if any(marker in cleaned_lower for marker in description_markers):
                continue

            # Limit length to reasonable title length
            if len(cleaned) > 100:
                cleaned = cleaned[:100].rsplit(" ", 1)[0]
            return cleaned

    return None


def slugify_title(title: str) -> str:
    """Convert a title to a URL-safe slug for folder naming.

    Args:
        title: The position title to slugify

    Returns:
        A lowercase, hyphenated slug with special characters removed
    """
    if not title:
        return "project"

    # Convert to lowercase
    slug = title.lower()
    # Replace common separators with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)
    # Remove non-alphanumeric characters except hyphens
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    # Trim hyphens from ends
    slug = slug.strip("-")
    # Limit length
    if len(slug) > 50:
        slug = slug[:50].rsplit("-", 1)[0]
    return slug or "project"


def find_project_by_project_id(work_dir: Path, project_id: str) -> Path | None:
    """Find a project directory by reading PROJECT_ID from config.sh files.

    This function does NOT trust the folder name - it reads config.sh and
    verifies the PROJECT_ID value inside.

    Args:
        work_dir: The working directory
        project_id: The PROJECT_ID to search for

    Returns:
        Path to the project directory if found, None otherwise
    """
    projects_dir = work_dir / "projects"
    if not projects_dir.exists():
        return None

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        config_path = project_dir / "config.sh"
        if not config_path.exists():
            continue

        try:
            config = parse_config_file(config_path)
            if config.get("PROJECT_ID") == project_id:
                return project_dir
        except (OSError, IOError):
            continue

    return None


def find_projects_by_jd_url(work_dir: Path, jd_url: str) -> list[Path]:
    """Find project directories that match the given JD source URL.

    Matches by exact canonical JD URL stored in project config.

    Args:
        work_dir: The working directory
        jd_url: The JD source URL to match

    Returns:
        List of project directory paths with matching JD_URL
    """
    projects_dir = work_dir / "projects"
    if not projects_dir.exists():
        return []

    matches: list[Path] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        config_path = project_dir / "config.sh"
        if not config_path.exists():
            continue

        try:
            config = parse_config_file(config_path)
            if config.get("JD_URL") == jd_url:
                matches.append(project_dir)
        except (OSError, IOError):
            continue

    return matches


def compute_jd_fingerprint(jd_content: str) -> str:
    """Compute a normalized fingerprint for JD content matching.

    Normalizes whitespace and lowercases content for exact matching.
    This is a simple fingerprint - not a hash, but a normalized form.

    Args:
        jd_content: Raw JD content (plain text)

    Returns:
        Normalized fingerprint string
    """
    if not jd_content:
        return ""
    # Normalize: lowercase, collapse whitespace, strip
    normalized = re.sub(r"\s+", " ", jd_content.lower()).strip()
    return normalized


def find_projects_by_jd_content(work_dir: Path, jd_content: str) -> list[Path]:
    """Find project directories that match the given JD content.

    Matches by exact normalized JD text fingerprint.

    Args:
        work_dir: The working directory
        jd_content: The JD content to match

    Returns:
        List of project directory paths with matching JD content
    """
    projects_dir = work_dir / "projects"
    if not projects_dir.exists():
        return []

    target_fingerprint = compute_jd_fingerprint(jd_content)
    if not target_fingerprint:
        return []

    matches: list[Path] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        jd_path = project_dir / "job_description.txt"
        if not jd_path.exists():
            continue

        try:
            existing_jd = jd_path.read_text(encoding="utf-8")
            existing_fingerprint = compute_jd_fingerprint(existing_jd)
            if existing_fingerprint == target_fingerprint:
                matches.append(project_dir)
        except (OSError, IOError):
            continue

    return matches


class AmbiguousProjectError(Exception):
    """Raised when multiple projects match the search criteria.

    Contains actionable information for the caller to specify project_id.
    """

    def __init__(self, message: str, candidates: list[dict[str, str]]):
        super().__init__(message)
        self.candidates = candidates


def gather_project_candidates(
    work_dir: Path,
    project_id: str | None = None,
    jd_url: str | None = None,
    jd_content: str | None = None,
) -> dict[str, list[Path]]:
    """Gather all potential project matches based on available criteria.

    Args:
        work_dir: The working directory
        project_id: Optional explicit project ID to match
        jd_url: Optional JD source URL to match
        jd_content: Optional JD content to match

    Returns:
        Dict mapping match type to list of matching project paths
    """
    candidates: dict[str, list[Path]] = {
        "by_project_id": [],
        "by_jd_url": [],
        "by_jd_content": [],
    }

    if project_id:
        by_id = find_project_by_project_id(work_dir, project_id)
        if by_id:
            candidates["by_project_id"].append(by_id)

    if jd_url:
        candidates["by_jd_url"] = find_projects_by_jd_url(work_dir, jd_url)

    if jd_content:
        candidates["by_jd_content"] = find_projects_by_jd_content(work_dir, jd_content)

    return candidates


def resolve_project_reuse(
    work_dir: Path,
    explicit_project_id: str | None = None,
    jd_url: str | None = None,
    jd_content: str | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    """Determine if an existing project should be reused.

    Implements the deduplication logic:
    1. Explicit project_id takes precedence - if provided and exists, reuse it
    2. If explicit project_id provided but not found, fail clearly
    3. Otherwise match by exact JD URL or exact JD content fingerprint
    4. Exactly one exact match => auto-reuse
    5. Multiple matches => raise AmbiguousProjectError with candidates
    6. No matches => return None (create new project)

    Args:
        work_dir: The working directory
        explicit_project_id: User-provided --project-id (optional)
        jd_url: JD source URL if available
        jd_content: JD content if available

    Returns:
        Tuple of (project_dir or None, metadata dict with match info)

    Raises:
        ValueError: If explicit project_id not found
        AmbiguousProjectError: If multiple projects match ambiguously
    """
    # Case 1: Explicit project_id provided
    if explicit_project_id:
        existing = find_project_by_project_id(work_dir, explicit_project_id)
        if existing:
            return existing, {
                "match_type": "explicit_project_id",
                "project_id": explicit_project_id,
            }
        else:
            raise ValueError(
                f"Explicit project_id '{explicit_project_id}' not found. "
                f"Use an existing project_id or omit --project-id to create a new project."
            )

    # Gather all potential matches
    candidates = gather_project_candidates(work_dir, None, jd_url, jd_content)

    # Collect unique matches with their match types
    all_matches: dict[Path, list[str]] = {}
    for match_type, paths in candidates.items():
        for path in paths:
            if path not in all_matches:
                all_matches[path] = []
            all_matches[path].append(match_type)

    # Case 2: No matches - create new project
    if not all_matches:
        return None, {"match_type": "none", "candidates": []}

    # Case 3: Exactly one match - auto-reuse
    if len(all_matches) == 1:
        project_dir = list(all_matches.keys())[0]
        match_types = all_matches[project_dir]
        # Determine primary match type
        if "by_jd_url" in match_types:
            match_type = "jd_url"
        elif "by_jd_content" in match_types:
            match_type = "jd_content"
        else:
            match_type = "other"
        return project_dir, {"match_type": match_type, "project_id": None}

    # Case 4: Multiple matches - raise ambiguity error
    candidate_info: list[dict[str, str]] = []
    for project_dir, match_types in all_matches.items():
        config_path = project_dir / "config.sh"
        project_id = "unknown"
        position_title = "unknown"
        try:
            config = parse_config_file(config_path)
            project_id = config.get("PROJECT_ID", "unknown")
            position_title = config.get("POSITION_TITLE", "unknown")
        except (OSError, IOError):
            pass

        candidate_info.append(
            {
                "project_id": project_id,
                "project_dir": str(project_dir.name),
                "position_title": position_title,
                "match_types": match_types,
            }
        )

    raise AmbiguousProjectError(
        f"Multiple existing projects match the criteria. Specify --project-id to choose one.",
        candidates=candidate_info,
    )


def bootstrap_project(args: argparse.Namespace) -> dict[str, Any]:
    """Main bootstrap logic with Recruiter-derived PROJECT_ID.

    Canonical flow:
    1. Gather JD content and extract metadata
    2. Check for existing project to reuse (by explicit ID, JD URL, or JD content)
    3. Determine PROJECT_ID from Recruiter identity (URL or ensure_project)
    4. Create local project files in new canonical layout (if not reusing)
    5. Fail closed if Recruiter identity cannot be resolved

    New layout:
    - $WORK_DIR/projects/<PROJECT_ID>_<title_slug>/config.sh
    - $WORK_DIR/projects/<PROJECT_ID>_<title_slug>/job_description.txt
    - $WORK_DIR/projects/<PROJECT_ID>_<title_slug>/workbook.xlsx
    """
    # Resolve paths
    work_dir = get_work_dir(args.work_dir)

    # Initialize result structure
    result: dict[str, Any] = {
        "project_id": None,
        "project_dir": None,
        "workbook_path": None,
        "config_path": None,
        "jd_path": None,
        "recruiter_url": None,
        "inferred": {},
        "next_steps": [],
        "reused": False,
        "match_type": None,
    }

    # Step 1: Gather JD content and metadata
    jd_content = ""
    inferred: dict[str, str] = {}

    if args.jd_url:
        # Fetch URL
        status, content = fetch_jd_url(args.jd_url)

        if status == 200:
            jd_content = content

            # Try to extract metadata for known sites
            if "lifeattiktok.com" in args.jd_url or "tiktok.com" in args.jd_url:
                inferred = extract_tiktok_metadata(content)
                inferred["source_url"] = args.jd_url

                # Extract job code from URL if not found in content
                if not inferred.get("job_code"):
                    url_match = re.search(r"/search/(\d+)", args.jd_url)
                    if url_match:
                        inferred["job_code"] = url_match.group(1)
            else:
                # Generic URL - save raw HTML, minimal inference
                inferred["source_url"] = args.jd_url
                inferred["position_title"] = "[EXTRACT FROM JD]"
        else:
            # Fetch failed - create placeholder
            jd_content = f"# Failed to fetch URL: {args.jd_url}\n# Error: {content}\n\n# Please paste JD content here manually"
            inferred["source_url"] = args.jd_url
            inferred["fetch_error"] = content

    elif args.jd_text:
        # Read from text or file
        jd_content = read_jd_text(args.jd_text)
        inferred["position_title"] = "[EXTRACT FROM JD]"

    # Step 1b: If position_title is the placeholder, try to extract from JD content
    if inferred.get("position_title") == "[EXTRACT FROM JD]" and jd_content:
        extracted_title = extract_title_from_jd_content(jd_content)
        if extracted_title:
            inferred["position_title"] = extracted_title

    # Step 2: Check for existing project to reuse (deduplication logic)
    # Normalize JD content for matching
    normalized_jd = normalize_to_plain_text(jd_content) if jd_content else ""

    # Check for existing project before determining PROJECT_ID
    # This allows explicit project_id to take precedence and fail if not found
    # Always pass jd_content for matching to support legacy projects without JD_URL
    try:
        existing_project_dir, reuse_metadata = resolve_project_reuse(
            work_dir=work_dir,
            explicit_project_id=args.project_id,
            jd_url=args.jd_url,
            jd_content=normalized_jd,
        )
        result["match_type"] = reuse_metadata.get("match_type")
        result["reused"] = existing_project_dir is not None
    except AmbiguousProjectError as e:
        # Multiple matches - return actionable error
        candidate_list = "\n".join(
            f"  - {c['project_id']} ({c['project_dir']}): {c['position_title']}"
            for c in e.candidates
        )
        raise ValueError(
            f"{e}\n\nMatching projects:\n{candidate_list}\n\n"
            f"Specify --project-id with one of the above project IDs to proceed."
        )

    # Step 3: Determine PROJECT_ID from Recruiter identity
    project_id: str | None = None
    recruiter_url: str | None = None
    recruiter_project_id: str | None = None

    if existing_project_dir:
        # Reusing existing project - read its PROJECT_ID and recruiter URL
        existing_config_path = existing_project_dir / "config.sh"
        existing_config = parse_config_file(existing_config_path)
        project_id = existing_config.get("PROJECT_ID")
        recruiter_url = existing_config.get("RECRUITER_PROJECT_URL")
        if recruiter_url:
            recruiter_project_id = extract_recruiter_id_from_url(recruiter_url)
    else:
        # No existing project - determine PROJECT_ID from Recruiter identity
        # Validate recruiter URL first if provided (fail closed before any file operations)
        if args.recruiter_url:
            recruiter_project_id = extract_recruiter_id_from_url(args.recruiter_url)
            if not recruiter_project_id:
                raise ValueError(
                    f"Could not extract project ID from Recruiter URL: {args.recruiter_url}. "
                    "Expected format: https://linkedin.com/talent/hire/{numeric_id}/..."
                )
            recruiter_url = args.recruiter_url

        if args.project_id:
            # Explicit override (advanced use only) - already checked it exists above
            project_id = args.project_id
            # recruiter_project_id already validated above if URL was provided
        elif recruiter_project_id:
            # Use the validated recruiter ID as project ID
            project_id = recruiter_project_id
        else:
            # Create/ensure Recruiter project and derive PROJECT_ID
            # First ensure browser is available and authenticated
            browser_check = ensure_browser_auth(work_dir, args.cdp_port)
            if not browser_check["success"]:
                # Include structured fallback in error for agent handling
                error_msg = (
                    f"Browser authentication required but failed: {browser_check.get('error', 'Unknown error')}. "
                    "Please provide --recruiter-url or ensure Chrome is running with CDP."
                )
                # Re-raise with structured context if available
                if browser_check.get("action_required"):
                    raise RuntimeError(
                        f"{error_msg} [action_required: {browser_check['action_required']}]"
                    )
                raise RuntimeError(error_msg)

            # Use the browser mode returned from auth bootstrap (CDP or agent-browser)
            browser_mode = browser_check.get("mode")
            if browser_mode is None:
                # Fallback to CDP mode with provided port for backward compatibility
                from browser_utils import BrowserMode

                browser_mode = BrowserMode(mode="cdp", cdp_port=args.cdp_port)

            # Use position title as project name, or placeholder if not available
            position_title_for_name = inferred.get("position_title", "")
            # Avoid using placeholder for Recruiter project name
            if position_title_for_name == "[EXTRACT FROM JD]":
                position_title_for_name = ""
            project_name = (
                args.position_title or position_title_for_name or "New Sourcing Project"
            )
            description = inferred.get("core_function", "")

            ensure_result = ensure_recruiter_project_and_get_id(
                project_name=project_name,
                description=description,
                browser_mode=browser_mode,
                work_dir=work_dir,
            )

            if not ensure_result["success"]:
                # Preserve structured failure info for agent manual guidance
                failure_code = ensure_result.get("failure_code")
                action_required = ensure_result.get("action_required")
                message = ensure_result.get("message", "Unknown error")

                # Build error message with structured guidance if available
                if action_required:
                    steps = "\n".join(
                        f"  - {step}" for step in action_required.get("steps", [])
                    )
                    error_msg = (
                        f"Failed to ensure Recruiter project: {message}\n"
                        f"Failure code: {failure_code}\n"
                        f"Action required: {action_required.get('summary', 'Manual intervention needed')}\n"
                        f"Steps:\n{steps}"
                    )
                else:
                    error_msg = (
                        f"Failed to ensure Recruiter project: {message}. "
                        "Please provide --recruiter-url or ensure Chrome with CDP is running."
                    )

                raise RuntimeError(error_msg)

            project_id = ensure_result["project_id"]
            if not project_id:
                raise RuntimeError(
                    "Recruiter project was created but no project ID was returned. "
                    "This is unexpected - please check the browser state."
                )

            recruiter_url = ensure_result["url"]
            recruiter_project_id = project_id

    # Step 4: Create or reuse project directory and files
    if existing_project_dir:
        project_dir = existing_project_dir
        existing_config_path = project_dir / "config.sh"
    else:
        # New canonical layout: <PROJECT_ID>_<title_slug>
        title_slug = slugify_title(
            args.position_title or inferred.get("position_title", "")
        )
        base_folder_name = f"{project_id}_{title_slug}"
        project_dir = work_dir / "projects" / base_folder_name

        # If directory exists and we're not reusing, generate a unique name
        # to avoid overwriting an existing non-matching project
        if project_dir.exists():
            counter = 1
            while True:
                folder_name = f"{project_id}_{title_slug}_{counter}"
                project_dir = work_dir / "projects" / folder_name
                if not project_dir.exists():
                    break
                counter += 1

        project_dir.mkdir(parents=True, exist_ok=True)
        existing_config_path = None

    result["project_id"] = project_id
    result["project_dir"] = str(project_dir)
    result["recruiter_url"] = recruiter_url

    # Save JD as normalized plain text (not raw HTML)
    jd_path = project_dir / "job_description.txt"
    normalized_jd = normalize_to_plain_text(jd_content)
    jd_path.write_text(normalized_jd, encoding="utf-8")
    result["jd_path"] = str(jd_path)

    # Initialize project state
    from project_state import update_project_state

    update_project_state(
        project_dir=project_dir,
        project_id=project_id,
        workflow_mode="reachout",
        current_phase="bootstrap",
        status="completed",
        action_required=False,
        last_result_summary=f"Project bootstrapped with JD from {'URL' if args.jd_url else 'text input'}",
        last_error=False,
    )

    # Build overrides dict
    overrides = {
        "position_title": args.position_title,
        "team_name": args.team_name,
        "location": args.location,
        "core_function": args.core_function,
        "business_impact": args.business_impact,
        "keywords": args.keywords,
        "companies": args.companies,
        "exclude_titles": args.exclude_titles,
        "hiring_company": args.hiring_company,
        "recruiter_url": recruiter_url,
        "jd_url": args.jd_url,  # Persist JD URL for future deduplication
    }

    # Parse existing config when reusing a project to preserve curated values
    existing_config: dict[str, str] = {}
    if existing_config_path:
        existing_config = parse_config_file(existing_config_path)

    # Build and write config (preserving existing values when reusing)
    config = build_config(project_id, inferred, overrides, existing_config)
    config_path = project_dir / "config.sh"
    write_config(config, config_path)
    result["config_path"] = str(config_path)

    from config_utils import get_unresolved_project_messaging_fields

    unresolved_project_fields = get_unresolved_project_messaging_fields(config)
    result["unresolved_project_messaging_fields"] = unresolved_project_fields

    # Create workbook in project directory (new canonical layout)
    # For legacy projects, also check for root-level workbook
    workbook_path = project_dir / "workbook.xlsx"
    legacy_workbook_path = work_dir / "projects" / f"{project_id}.xlsx"

    if not workbook_path.exists():
        if legacy_workbook_path.exists():
            # Legacy project with root-level workbook - keep using it
            workbook_path = legacy_workbook_path
        else:
            # Create new workbook in project directory
            create(workbook_path)
    result["workbook_path"] = str(workbook_path)

    search_ready_at_bootstrap = False
    if recruiter_url and "discover/recruiterSearch" in recruiter_url:
        try:
            from run_phase import run_phase

            create_search_result = run_phase(
                project_ref=project_id,
                phase="create_search",
            )
            if create_search_result.get("success"):
                search_ready_at_bootstrap = True
                update_project_state(
                    project_dir=project_dir,
                    project_id=project_id,
                    workflow_mode="reachout",
                    current_phase="create_search",
                    status="completed",
                    action_required=False,
                    last_result_summary="Recruiter search created and verified at bootstrap",
                    last_error=False,
                )
            else:
                # Search creation failed - update state with action required
                phase_result = create_search_result.get("phase_result") or {}
                update_project_state(
                    project_dir=project_dir,
                    project_id=project_id,
                    workflow_mode="reachout",
                    current_phase="create_search",
                    status="action_required",
                    action_required=phase_result.get("action_required")
                    or create_search_result.get("action_required"),
                    last_result_summary=f"Search creation failed: {phase_result.get('error') or create_search_result.get('error', 'Unknown error')}",
                    last_error=True,
                )
        except Exception as exc:
            import traceback

            traceback.print_exc()
            update_project_state(
                project_dir=project_dir,
                project_id=project_id,
                workflow_mode="reachout",
                current_phase="create_search",
                status="failed",
                last_result_summary=f"Bootstrap search creation crashed: {exc}",
                last_error=True,
            )

    # Build inferred output
    result["inferred"] = {
        "position_title": config["POSITION_TITLE"],
        "team_name": config["TEAM_NAME"],
        "location": config["LOCATION"],
        "job_code": inferred.get("job_code", ""),
    }

    # Determine next steps
    next_steps = [
        f"1. Review and update config: {config_path}",
        f"2. Review saved JD: {jd_path}",
    ]

    if unresolved_project_fields:
        next_steps.append(
            "3. Finalize project messaging fields before drafting: "
            f"{', '.join(unresolved_project_fields)}"
        )

    if recruiter_url:
        if "discover/recruiterSearch" in recruiter_url:
            if search_ready_at_bootstrap:
                next_steps.append(
                    f"{len(next_steps) + 1}. Recruiter search already shows candidates; continue from current state with: python3 {SCRIPT_DIR / 'status.py'} {project_id} --pretty"
                )
            else:
                next_steps.append(
                    f"{len(next_steps) + 1}. Open the Recruiter project search page and create/review the candidate search before extraction"
                )
        else:
            next_steps.append(
                f"{len(next_steps) + 1}. Recruiter project configured - run ensure_recruiter_project.py to get the project search page URL"
            )
    else:
        next_steps.append(
            f"{len(next_steps) + 1}. WARNING: No Recruiter URL configured - extraction will not work"
        )

    next_steps.extend(
        [
            f"{len(next_steps) + 1}. Workbook ready at: {workbook_path}",
            (
                f"{len(next_steps) + 2}. Resume with the loop: python3 {SCRIPT_DIR / 'run_reachout_loop.py'} --project {project_id}"
                if search_ready_at_bootstrap
                else f"{len(next_steps) + 2}. After the search shows candidates in Recruiter, run extraction: see SKILL.md for workflow"
            ),
        ]
    )

    result["next_steps"] = next_steps

    return result


def main():
    """Main entry point."""
    args = parse_args()

    try:
        result = bootstrap_project(args)

        # Print JSON output for programmatic use
        print(json.dumps(result, indent=2))

        # Also print human-readable summary
        print("\n" + "=" * 60, file=sys.stderr)
        print("PROJECT BOOTSTRAP COMPLETE", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"\nProject ID: {result['project_id']}", file=sys.stderr)
        print(f"Project Dir: {result['project_dir']}", file=sys.stderr)
        print(f"\nInferred Fields:", file=sys.stderr)
        for key, value in result["inferred"].items():
            if value:
                print(f"  {key}: {value}", file=sys.stderr)
        print(f"\nNext Steps:", file=sys.stderr)
        for step in result["next_steps"]:
            print(f"  {step}", file=sys.stderr)
        print("", file=sys.stderr)

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1


def fetch_jd_url(url: str, timeout: int = 30) -> tuple[int, str]:
    """Fetch JD content via plain HTTP."""
    return fetch_url(url, timeout=timeout)


if __name__ == "__main__":
    sys.exit(main())
