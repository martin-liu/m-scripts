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
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))
from excel_utils import create


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


def extract_recruiter_id_from_url(url: str) -> str | None:
    """Extract numeric recruiter project ID from a LinkedIn Recruiter URL.

    Args:
        url: LinkedIn Recruiter URL (e.g., https://linkedin.com/talent/hire/12345/...)

    Returns:
        Recruiter project ID string if found, None otherwise
    """
    # Match /talent/hire/{numeric_id} followed by /, ?, #, or end of string
    # This accepts URLs with or without trailing slash, and with query params
    match = re.search(r"/talent/hire/(\d+)(?:/|$|\?|#)", url)
    return match.group(1) if match else None


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

        try:
            content = config_path.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("RECRUITER_PROJECT_URL="):
                    url_match = re.search(
                        r'RECRUITER_PROJECT_URL=["\']?([^"\'\n]+)', line
                    )
                    if url_match:
                        url = url_match.group(1)
                        existing_id = extract_recruiter_id_from_url(url)
                        if existing_id == recruiter_id:
                            return config_path
        except (OSError, IOError):
            continue

    return None


def ensure_recruiter_project_and_get_id(
    project_name: str, description: str, cdp_port: str, work_dir: Path
) -> dict[str, Any]:
    """Ensure Recruiter project exists and return its ID and URL.

    Args:
        project_name: Name for the Recruiter project
        description: Description for the project
        cdp_port: Chrome DevTools Protocol port
        work_dir: Working directory for incident reporting

    Returns:
        Dict with success status, project_id, url, and error message if failed
    """
    # Import here to avoid circular dependencies
    from ensure_recruiter_project import ensure_project_exists

    result = ensure_project_exists(
        project_name=project_name,
        description=description,
        cdp_port=cdp_port,
        work_dir=str(work_dir),
        require_contextual_url=False,  # Bootstrap only needs project identity, not search URL
    )

    return {
        "success": result["status"] in ("existing", "created"),
        "project_id": result.get("project_id"),
        "url": result.get("url"),
        "status": result["status"],
        "message": result.get("message", ""),
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

    keyword_patterns = [
        (r"verilog|systemverilog", ["Verilog", "SystemVerilog"]),
        (r"\bsoc\b", ["SoC Design"]),
        (r"rtl", ["RTL Design"]),
        (r"fpga|asic", ["FPGA", "ASIC"]),
        (r"video codec|encoding|codec", ["Video Codec"]),
        (r"clock domain crossing|\bcdc\b", ["CDC"]),
        (r"reset domain crossing|\brdc\b", ["RDC"]),
        (r"low-power|power gating|clock gating|\bupf\b", ["Low Power Design"]),
        (r"npu|ai hardware acceleration", ["AI Hardware Acceleration"]),
        (
            r"synthesis|design compiler|primetime|sta",
            ["Synthesis", "Static Timing Analysis"],
        ),
    ]
    keywords = []
    for pattern, values in keyword_patterns:
        if re.search(pattern, html_text, re.IGNORECASE):
            for value in values:
                if value not in keywords:
                    keywords.append(value)
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


def infer_keywords(position_title: str) -> str:
    """Infer keywords from position title."""
    if not position_title:
        return ""

    title_lower = position_title.lower()
    keywords = []

    if any(kw in title_lower for kw in ["pytorch", "deep learning", "neural"]):
        keywords.extend(["PyTorch", "Deep Learning", "Neural Networks"])
    if any(kw in title_lower for kw in ["tensorflow", "tf ", "keras"]):
        keywords.extend(["TensorFlow", "Keras"])
    if any(kw in title_lower for kw in ["cuda", "gpu", "kernel"]):
        keywords.extend(["CUDA", "GPU Optimization", "Kernel Development"])
    if any(kw in title_lower for kw in ["distributed", "training", "large scale"]):
        keywords.extend(["Distributed Training", "Large-Scale Systems"])
    if any(kw in title_lower for kw in ["infrastructure", "platform"]):
        keywords.extend(["Infrastructure", "Platform Engineering"])
    if any(kw in title_lower for kw in ["ml", "machine learning"]):
        keywords.extend(["Machine Learning", "ML Systems"])

    return ", ".join(keywords) if keywords else ""


def get_default_companies() -> str:
    """Return default target companies."""
    return "Google, Meta, OpenAI, Anthropic, DeepMind, Microsoft, NVIDIA, Amazon, Apple, Netflix"


def get_default_exclude_titles() -> str:
    """Return default excluded titles."""
    return "Manager, Director, VP, Head of, Product Manager, Data Scientist, QA Engineer, Recruiter, HR"


def parse_existing_config(config_path: Path) -> dict[str, str]:
    """Parse an existing config file to extract current values.

    Args:
        config_path: Path to existing config.sh file

    Returns:
        Dict of existing config key-value pairs
    """
    config: dict[str, str] = {}
    if not config_path.exists():
        return config

    try:
        for line in config_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                config[key] = value
    except (OSError, IOError):
        pass

    return config


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
            "[CORE FUNCTION - PLEASE UPDATE]",
        ),
        "BUSINESS_IMPACT": get_value(
            "business_impact",
            "business_impact",
            "BUSINESS_IMPACT",
            "[BUSINESS IMPACT - PLEASE UPDATE]",
        ),
        "KEYWORDS": get_value("keywords", "keywords", "KEYWORDS", "", infer_keywords),
        "COMPANIES": overrides.get("companies")
        or existing.get("COMPANIES", "")
        or get_default_companies(),
        "EXCLUDE_TITLES": overrides.get("exclude_titles")
        or existing.get("EXCLUDE_TITLES", "")
        or get_default_exclude_titles(),
        "DAILY_LIMIT": existing.get("DAILY_LIMIT", "200"),
        "CANDIDATE_DELAY_SEC": existing.get("CANDIDATE_DELAY_SEC", "10"),
    }

    # Add recruiter URL if provided (authoritative from bootstrap)
    recruiter_url = overrides.get("recruiter_url")
    if recruiter_url:
        config["RECRUITER_PROJECT_URL"] = recruiter_url
    elif existing.get("RECRUITER_PROJECT_URL"):
        config["RECRUITER_PROJECT_URL"] = existing["RECRUITER_PROJECT_URL"]

    return config


def shell_escape(value: str) -> str:
    """Escape a string for safe use in shell variable assignment.

    Uses shlex.quote to handle quotes, newlines, backslashes, and other
    special characters safely while keeping the output readable.
    """
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
            config = parse_existing_config(config_path)
            if config.get("PROJECT_ID") == project_id:
                return project_dir
        except (OSError, IOError):
            continue

    return None


def bootstrap_project(args: argparse.Namespace) -> dict[str, Any]:
    """Main bootstrap logic with Recruiter-derived PROJECT_ID.

    Canonical flow:
    1. Gather JD content and extract metadata
    2. Determine PROJECT_ID from Recruiter identity (URL or ensure_project)
    3. Check for existing project conflicts by scanning config.sh files
    4. Create local project files in new canonical layout
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
    }

    # Step 1: Gather JD content and metadata
    jd_content = ""
    inferred: dict[str, str] = {}

    if args.jd_url:
        # Fetch URL
        status, content = fetch_url(args.jd_url)

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

    # Step 2: Determine PROJECT_ID from Recruiter identity
    project_id: str | None = None
    recruiter_url: str | None = None
    recruiter_project_id: str | None = None

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
        # Explicit override (advanced use only)
        project_id = args.project_id
        # recruiter_project_id already validated above if URL was provided
    elif recruiter_project_id:
        # Use the validated recruiter ID as project ID
        project_id = recruiter_project_id
    else:
        # Create/ensure Recruiter project and derive PROJECT_ID
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
            cdp_port=args.cdp_port,
            work_dir=work_dir,
        )

        if not ensure_result["success"]:
            raise RuntimeError(
                f"Failed to ensure Recruiter project: {ensure_result.get('message', 'Unknown error')}. "
                "Please provide --recruiter-url or ensure Chrome with CDP is running."
            )

        project_id = ensure_result["project_id"]
        if not project_id:
            raise RuntimeError(
                "Recruiter project was created but no project ID was returned. "
                "This is unexpected - please check the browser state."
            )

        recruiter_url = ensure_result["url"]
        recruiter_project_id = project_id

    # Step 3: Check for existing project conflicts
    # First check by PROJECT_ID (authoritative) - scans all config.sh files
    existing_project_dir = find_project_by_project_id(work_dir, project_id)

    # Also check by recruiter ID for backward compatibility
    existing_config_path: Path | None = None
    if recruiter_project_id:
        existing_config = check_existing_project_by_recruiter_id(
            work_dir, recruiter_project_id
        )
        if existing_config:
            existing_config_path = existing_config
            # Use the existing project directory if found by recruiter ID
            if not existing_project_dir:
                existing_project_dir = existing_config.parent
                # Read the actual PROJECT_ID from the existing config
                existing_config_data = parse_existing_config(existing_config)
                project_id = existing_config_data.get("PROJECT_ID", project_id)

    # Step 4: Create project directory and files
    # Use existing project directory if found, otherwise create new with canonical layout
    if existing_project_dir:
        project_dir = existing_project_dir
    else:
        # New canonical layout: <PROJECT_ID>_<title_slug>
        title_slug = slugify_title(
            args.position_title or inferred.get("position_title", "")
        )
        folder_name = f"{project_id}_{title_slug}"
        project_dir = work_dir / "projects" / folder_name
        project_dir.mkdir(parents=True, exist_ok=True)

    result["project_id"] = project_id
    result["project_dir"] = str(project_dir)
    result["recruiter_url"] = recruiter_url

    # Save raw JD
    jd_path = project_dir / "job_description.txt"
    jd_path.write_text(jd_content, encoding="utf-8")
    result["jd_path"] = str(jd_path)

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
        "recruiter_url": recruiter_url,
    }

    # Parse existing config when reusing a project to preserve curated values
    existing_config: dict[str, str] = {}
    if existing_config_path:
        existing_config = parse_existing_config(existing_config_path)

    # Build and write config (preserving existing values when reusing)
    config = build_config(project_id, inferred, overrides, existing_config)
    config_path = project_dir / "config.sh"
    write_config(config, config_path)
    result["config_path"] = str(config_path)

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

    if recruiter_url:
        if "discover/recruiterSearch" in recruiter_url:
            next_steps.append(
                "3. Recruiter project configured with search URL - ready for extraction"
            )
        else:
            next_steps.append(
                "3. Recruiter project configured - run ensure_recruiter_project.py to get search URL"
            )
    else:
        next_steps.append(
            "3. WARNING: No Recruiter URL configured - extraction will not work"
        )

    next_steps.extend(
        [
            f"4. Workbook ready at: {workbook_path}",
            "5. Run extraction when ready: see SKILL.md for workflow",
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


if __name__ == "__main__":
    sys.exit(main())
