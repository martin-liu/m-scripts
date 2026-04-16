#!/usr/bin/env python3
"""Shared utilities for LinkedIn Recruiter URL parsing and validation.

Provides helpers for extracting project IDs from Recruiter URLs and detecting
contextual search URLs (those with search context parameters).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


# Contextual params that indicate a real search context (not a bare URL)
CONTEXTUAL_SEARCH_PARAMS = [
    "searchContextId=",
    "searchHistoryId=",
    "searchRequestId=",
    "projectId=",
]


def extract_recruiter_id_from_url(url: str) -> str | None:
    """Extract numeric recruiter project ID from a LinkedIn Recruiter URL.

    Args:
        url: LinkedIn Recruiter URL (e.g., https://linkedin.com/talent/hire/12345/...)

    Returns:
        Recruiter project ID string if found, None otherwise
    """
    # Match /talent/hire/{numeric_id} followed by /, ?, #, or end of string
    # This accepts URLs with or without trailing slash, and with query params or hash
    match = re.search(r"/talent/hire/(\d+)(?:/|$|\?|#)", url)
    return match.group(1) if match else None


def is_recruiter_url(ref: str) -> bool:
    """Check if reference looks like a LinkedIn Recruiter URL.

    Args:
        ref: Project reference string

    Returns:
        True if ref appears to be a LinkedIn Recruiter URL
    """
    return "/talent/hire/" in ref and extract_recruiter_id_from_url(ref) is not None


def is_contextual_search_url(url: str, project_id: str | None = None) -> bool:
    """Check if URL has contextual search params needed for extraction.

    A bare /discover/recruiterSearch URL without context params will hang
    on "Loading search results". Contextual params include:
    - searchContextId
    - searchHistoryId
    - searchRequestId
    - projectId (from an actual search, not just the base project)

    Args:
        url: The URL to check
        project_id: Optional project ID to verify the URL belongs to

    Returns:
        True if URL has at least one contextual search parameter
        (and belongs to the specified project_id if provided)
    """
    if "discover/recruiterSearch" not in url:
        return False

    # If project_id specified, verify URL contains it
    if project_id is not None and f"/talent/hire/{project_id}/" not in url:
        return False

    # Must have at least one contextual search parameter
    return any(param in url for param in CONTEXTUAL_SEARCH_PARAMS)


def is_linkedin_domain(url: str) -> bool:
    """Check if URL is from a valid LinkedIn domain.

    Args:
        url: The URL to check

    Returns:
        True if URL is from linkedin.com or *.linkedin.com
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return hostname == "linkedin.com" or hostname.endswith(".linkedin.com")


def build_project_overview_url(project_id: str) -> str:
    """Build a stable project overview URL from project ID.

    Args:
        project_id: The project ID

    Returns:
        Project overview URL
    """
    return f"https://www.linkedin.com/talent/hire/{project_id}/overview"
