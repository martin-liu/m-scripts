#!/usr/bin/env python3
"""Ensure a LinkedIn Recruiter project exists and return its URL.

This script automates the project creation flow in LinkedIn Recruiter:
1. Navigate to the Projects page
2. Search for an existing project by exact name
3. If found, open it and return the URL
4. If not found, create a new project, handle form submission, rename if needed

Usage:
    python3 ensure_recruiter_project.py \
        --project-name "SoC Digital Design Engineer, Multimedia Lab" \
        --description "Hardware design role for video codec solutions" \
        --location "San Jose, CA" \
        --job-title "SoC Digital Design Engineer" \
        --cdp-port 9230

Output:
    Prints structured JSON to stdout:
    {
        "status": "existing" | "created",
        "project_name": "...",
        "url": "https://www.linkedin.com/talent/hire/...",
        "message": "..."
    }

Notes:
    - Requires agent-browser to be installed and Chrome running with CDP
    - The script uses fast waits and explicit checks for stability
    - If creation lands on "Untitled Project", it performs inline rename
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

# Import shared browser utilities
sys.path.insert(0, str(SCRIPT_DIR))
from browser_utils import (
    ActionRequired,
    BrowserMode,
    FailureCode,
    classify_browser_readiness,
    format_timeout_error,
)
from browser_utils import run_browser_command as _run_browser_command
from recruiter_page_utils import PageStateProbe, RecoveryHelper, ensure_page_ready
from recruiter_url_utils import (
    extract_recruiter_id_from_url,
)
from recruiter_url_utils import (
    is_contextual_search_url as _is_contextual_search_url,
)

# LinkedIn Recruiter URLs
RECRUITER_BASE = "https://www.linkedin.com/talent"
RECRUITER_HOME_URL = f"{RECRUITER_BASE}/home"
PROJECTS_URL = f"{RECRUITER_BASE}/projects"

# JavaScript snippets for browser automation
# Note: Double braces {{ and }} are used to escape Python string formatting
SEARCH_PROJECT_JS = """
(function() {{
    const searchInput = document.querySelector('input[placeholder*="Search"], input[aria-label*="Search"], input[data-test-id*="search"]');
    if (!searchInput) return {{ found: false, error: "Search input not found" }};

    searchInput.value = {project_name!r};
    searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
    searchInput.dispatchEvent(new Event('change', {{ bubbles: true }}));

    // Trigger search via Enter key
    searchInput.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }}));

    return {{ found: true, action: "searched" }};
}})()
"""

CHECK_PROJECT_EXISTS_JS = """
(function() {{
    const projectName = {project_name!r};
    // Check both /projects/ URLs and /discover/recruiterSearch URLs (live observed pattern)
    const projectLinks = Array.from(document.querySelectorAll(
        'a[href*="/talent/hire/"][href*="/projects/"], a[href*="/talent/hire/"][href*="/discover/recruiterSearch"]'
    ));

    for (const link of projectLinks) {{
        const text = link.textContent.trim();
        const ariaLabel = link.getAttribute('aria-label') || '';

        if (text === projectName || ariaLabel.includes(projectName)) {{
            return {{
                found: true,
                url: link.href,
                name: text
            }};
        }}
    }}

    // Also check for project cards/tiles
    const projectCards = Array.from(document.querySelectorAll('[data-test-id*="project"], .project-card, [class*="project"]'));
    for (const card of projectCards) {{
        const titleEl = card.querySelector('h3, h4, .title, [class*="title"]');
        if (titleEl && titleEl.textContent.trim() === projectName) {{
            const link = card.querySelector('a[href*="/talent/hire/"]');
            if (link) {{
                return {{ found: true, url: link.href, name: titleEl.textContent.trim() }};
            }}
        }}
    }}

    return {{ found: false }};
}})()
"""

CLICK_CREATE_PROJECT_JS = """
(function() {
    // Strategy 1: Look for exact "Create new" text (observed on live page)
    const allElements = Array.from(document.querySelectorAll('button, a, [role="button"]'));
    const createNewBtn = allElements.find(b => {
        const text = b.textContent.trim().toLowerCase();
        return text === 'create new' || text === 'create project' || text === 'new project';
    });
    if (createNewBtn) {
        createNewBtn.click();
        return { clicked: true, text: createNewBtn.textContent.trim(), method: 'exact' };
    }

    // Strategy 2: Look for primary button containing "create"
    const primaryBtn = allElements.find(b => {
        const text = b.textContent.trim().toLowerCase();
        const className = (b.className || '').toLowerCase();
        return text.includes('create') && className.includes('primary');
    });
    if (primaryBtn) {
        primaryBtn.click();
        return { clicked: true, text: primaryBtn.textContent.trim(), method: 'primary' };
    }

    // Strategy 3: Fallback to any element containing create/new project text
    const fallbackBtn = allElements.find(b => {
        const text = b.textContent.trim().toLowerCase();
        return text.includes('create project') || text.includes('new project') || text.includes('create');
    });
    if (fallbackBtn) {
        fallbackBtn.click();
        return { clicked: true, text: fallbackBtn.textContent.trim(), method: 'fallback' };
    }

    // Strategy 4: Try data-test-id patterns
    const testBtn = document.querySelector('[data-test-id*="create"], [data-test-id*="new-project"]');
    if (testBtn) {
        testBtn.click();
        return { clicked: true, testId: true, method: 'test-id' };
    }

    return { clicked: false, error: "Create button not found" };
})()
"""

FILL_CREATE_FORM_JS = """
(function() {{
    const projectName = {project_name!r};
    const description = {description!r} || '';

    function setFieldValue(el, value) {{
        if (!el) return false;

        const proto = Object.getPrototypeOf(el);
        const valueDescriptor = Object.getOwnPropertyDescriptor(proto, 'value')
            || (window.HTMLInputElement && Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'))
            || (window.HTMLTextAreaElement && Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value'));

        if (valueDescriptor && valueDescriptor.set) {{
            valueDescriptor.set.call(el, value);
        }} else {{
            el.value = value;
        }}

        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
        
        return el.value === value;
    }}

    // Fill project name - try id-based selectors first (observed on live page as #ember1131-projectName)
    // then fall back to broader selectors
    const nameInput = document.querySelector(
        'input[id$="-projectName"], ' +
        'input[id*="-projectName"], ' +
        'input[name*="name"], ' +
        'input[placeholder*="name" i], ' +
        'input[aria-label*="name" i], ' +
        'input[data-test-id*="name"]'
    );
    let nameVerified = false;
    if (nameInput) {{
        nameVerified = setFieldValue(nameInput, projectName);
        // If direct value setting didn't work, try focus + keyboard approach
        if (!nameVerified) {{
            nameInput.focus();
            nameInput.click();
            nameInput.select();
            nameInput.value = projectName;
            nameInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            nameVerified = nameInput.value === projectName;
        }}
    }}

    // Fill description if field exists - try id-based selectors first (observed as #ember1131-projectDescription)
    const descInput = document.querySelector(
        'textarea[id$="-projectDescription"], ' +
        'textarea[id*="-projectDescription"], ' +
        'textarea[name*="description"], ' +
        'textarea[placeholder*="description" i], ' +
        'textarea[aria-label*="description" i], ' +
        'input[name*="description"]'
    );
    let descVerified = false;
    if (descInput && description) {{
        descVerified = setFieldValue(descInput, description);
    }}

    return {{
        nameFilled: !!nameInput,
        nameVerified: nameVerified,
        descFilled: !!descInput,
        descVerified: descVerified,
        projectName: projectName,
        actualNameValue: nameInput ? nameInput.value : null
    }};
}})()
"""

SUBMIT_FORM_JS = """
(function() {
    // Look for submit/create button
    const buttons = Array.from(document.querySelectorAll('button[type="submit"], button'));
    const submitBtn = buttons.find(b => {
        const text = b.textContent.trim().toLowerCase();
        return text.includes('create') || text.includes('save') || text.includes('submit') || text.includes('done');
    });

    if (submitBtn && !submitBtn.disabled) {
        submitBtn.click();
        return { submitted: true, text: submitBtn.textContent.trim() };
    }

    // Try form submit
    const form = document.querySelector('form');
    if (form) {
        form.dispatchEvent(new Event('submit', { bubbles: true }));
        return { submitted: true, viaForm: true };
    }

    return { submitted: false };
})()
"""

CLICK_OUTSIDE_JS = """
(function() {
    // Click on a neutral area to close any typeahead overlays
    const main = document.querySelector('main, body, [role="main"]');
    if (main) {
        const rect = main.getBoundingClientRect();
        const clickEvent = new MouseEvent('click', {
            bubbles: true,
            cancelable: true,
            clientX: rect.left + 50,
            clientY: rect.top + 50
        });
        main.dispatchEvent(clickEvent);
    }
    return { clicked: !!main };
})()
"""

CHECK_UNTITLED_JS = """
(function() {
    // Check page title first
    if (document.title && document.title.toLowerCase().includes('untitled')) {
        return { isUntitled: true, title: document.title, selector: 'document.title' };
    }

    // Check multiple possible title locations
    const titleSelectors = [
        'h1[data-test-project-name-name]',
        'h1.project-name__name',
        'h1',
        '[data-test-id*="title"]',
        '.project-title',
        '[data-test-project-name-name]'
    ];

    for (const sel of titleSelectors) {
        const titleEl = document.querySelector(sel);
        if (titleEl) {
            const text = titleEl.textContent.trim();
            if (text) {
                return {
                    isUntitled: text.toLowerCase().includes('untitled') || text === '',
                    title: text,
                    selector: sel
                };
            }
        }
    }
    return { isUntitled: false, title: null };
})()
"""

RENAME_PROJECT_JS = """
(function() {{
    const newName = {project_name!r};

    function sleep(ms) {{
        const start = Date.now();
        while (Date.now() - start < ms) {{}}
    }}

    function findInputWithUntitled() {{
        const inputs = Array.from(document.querySelectorAll('input[type="text"]'));
        return inputs.find(input => input.value.toLowerCase().includes('untitled'));
    }}

    function findSaveButton() {{
        return Array.from(document.querySelectorAll('button')).find(
            b => b.textContent.trim() === 'Save'
        );
    }}

    // Strategy 1: Try clicking "Edit project name" button in settings panel
    const editNameBtn = document.querySelector('button[aria-label*="Edit project name" i]');
    if (editNameBtn) {{
        editNameBtn.click();
        // Synchronous polling loop: wait for input to appear
        let nameInput = null;
        for (let i = 0; i < 10; i++) {{
            sleep(100);
            nameInput = findInputWithUntitled();
            if (nameInput) break;
        }}
        if (nameInput) {{
            nameInput.value = newName;
            nameInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            nameInput.dispatchEvent(new Event('change', {{ bubbles: true }}));

            // Click Save
            let saveBtn = null;
            for (let i = 0; i < 10; i++) {{
                sleep(100);
                saveBtn = findSaveButton();
                if (saveBtn) break;
            }}
            if (saveBtn) {{
                saveBtn.click();
                return {{ attempted: true, method: 'settings_edit', newName: newName }};
            }}
            return {{ attempted: true, method: 'settings_edit', newName: newName, warning: 'Save button not found' }};
        }}
        return {{ attempted: false, error: 'Input with untitled value not found after clicking edit' }};
    }}

    // Strategy 2: Try clicking on the title directly (older UI)
    const titleEl = document.querySelector('h1, [data-test-id*="title"], .project-title');
    if (titleEl) {{
        titleEl.click();
        let input = null;
        for (let i = 0; i < 10; i++) {{
            sleep(100);
            input = document.querySelector('input[type="text"], input:not([type])');
            if (input) break;
        }}
        if (input) {{
            input.value = newName;
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }}));
            return {{ attempted: true, method: 'direct_click', newName: newName }};
        }}
        return {{ attempted: false, error: 'Input not found after clicking title' }};
    }}

    return {{ attempted: false, error: 'Could not find rename mechanism' }};
}})()
"""

GET_CURRENT_URL_JS = """
(function() {
    return {
        url: window.location.href,
        title: document.title
    };
})()
"""

# JavaScript to find and click the Recruiter search tab/link
NAVIGATE_TO_SEARCH_JS = """
(function() {
    // Strategy 1: Specific stable selector for the Recruiter Search button
    // CDP finding: button[data-test-collapsible-menu-link="recruiterSearch"] works
    // The wrapper div[data-test-sourcing-channels-tab] does NOT work (no-op on click)
    const specificButton = document.querySelector('button[data-test-collapsible-menu-link="recruiterSearch"]');
    if (specificButton) {
        specificButton.click();
        return { clicked: true, method: 'specific_button', testId: 'recruiterSearch' };
    }

    // Strategy 2: Alternative button with role=link (observed in some layouts)
    const roleLinkButton = document.querySelector('button[role="link"][data-test-collapsible-menu-link="recruiterSearch"]');
    if (roleLinkButton) {
        roleLinkButton.click();
        return { clicked: true, method: 'role_link_button', testId: 'recruiterSearch' };
    }

    // Strategy 3: Look for href containing discover/recruiterSearch
    const searchLink = document.querySelector('a[href*="discover/recruiterSearch"]');
    if (searchLink) {
        searchLink.click();
        return { clicked: true, method: 'link', href: searchLink.href };
    }

    // Strategy 4: Generic text heuristic fallback (less reliable, use last)
    // Note: Avoids wrapper divs that have no click handler
    const tabs = Array.from(document.querySelectorAll('a, button[role="link"], [role="tab"]'));
    const searchTab = tabs.find(el => {
        const text = el.textContent.trim().toLowerCase();
        return text.includes('recruiter search') || text.includes('search');
    });

    if (searchTab) {
        searchTab.click();
        return { clicked: true, method: 'text_fallback', text: searchTab.textContent.trim() };
    }

    // Strategy 5: Check if already on search page
    if (window.location.href.includes('discover/recruiterSearch')) {
        return { clicked: false, alreadyOnSearch: true, url: window.location.href };
    }

    return { clicked: false, error: 'Recruiter search tab/link not found' };
})()
"""

# JavaScript to derive search URL from project ID if available
DERIVE_SEARCH_URL_JS = r"""
(function() {
    const url = window.location.href;
    // Match /talent/hire/{numeric_id} followed by /, ?, #, or end of string
    const match = url.match(/\/talent\/hire\/(\d+)(?:\/|$|\?|#)/);
    if (match) {
        const projectId = match[1];
        const searchUrl = `https://www.linkedin.com/talent/hire/${projectId}/discover/recruiterSearch`;
        return { derived: true, projectId: projectId, searchUrl: searchUrl };
    }
    return { derived: false, url: url };
})()
"""

WAIT_FOR_LOAD_JS = """
(function() {
    return {
        ready: document.readyState === 'complete',
        state: document.readyState
    };
})()
"""


def run_browser_command(
    browser_mode: BrowserMode | str, action: str, js_code: str
) -> dict[str, Any]:
    """Run an agent-browser eval command and return parsed JSON result.

    This wrapper uses the shared browser_utils helper for consistent
    timeout handling and dialog detection across all browser operations.

    Args:
        browser_mode: BrowserMode instance or CDP port string for browser operations
        action: The action to perform (e.g., "eval", "goto")
        js_code: JavaScript code to execute or URL to navigate to
    """
    from browser_utils import ActionRequired, FailureCode, safe_get_parsed

    result = _run_browser_command(browser_mode, "eval", js_code, timeout=30)

    # Handle timeout with dialog info
    if result.get("timed_out"):
        error_msg = result["error"]
        # Return format compatible with existing code
        return {
            "error": error_msg,
            "timed_out": True,
            "dialog_info": result.get("dialog_info"),
            "failure_code": FailureCode.TIMEOUT,
            "action_required": ActionRequired.timeout(operation=action).to_dict(),
        }

    # Handle other errors
    if result.get("error"):
        return {
            "error": result["error"],
            "stderr": result.get("stderr", ""),
            "failure_code": FailureCode.AMBIGUOUS_STATE,
            "action_required": ActionRequired.ambiguous_state(
                details=f"Browser command failed: {result['error']}"
            ).to_dict(),
        }

    # Return parsed JSON result for backward compatibility using safe helper
    parsed = safe_get_parsed(result, default=None, require_dict=False)
    if parsed is not None:
        if isinstance(parsed, dict):
            parsed["failure_code"] = None
            parsed["action_required"] = None
        return parsed

    # No valid JSON - return raw output
    output = result.get("stdout", "")
    if not output:
        return {
            "error": "Empty output",
            "stderr": result.get("stderr", ""),
            "failure_code": FailureCode.PARSE_ERROR,
            "action_required": ActionRequired.ambiguous_state(
                details="Empty output from browser command"
            ).to_dict(),
        }

    return {
        "raw_output": output,
        "parse_error": True,
        "failure_code": FailureCode.PARSE_ERROR,
        "action_required": ActionRequired.ambiguous_state(
            details="Failed to parse browser command output as JSON"
        ).to_dict(),
    }


def navigate_to_projects(
    browser_mode: BrowserMode | str, work_dir: str | None = None
) -> dict[str, Any]:
    """Navigate to the LinkedIn Recruiter Projects page with recovery.

    Args:
        browser_mode: BrowserMode instance or CDP port string for browser operations
        work_dir: Optional working directory for incident reporting

    Returns:
        Dict with success status and optional error information:
        - success: bool - whether navigation succeeded
        - error: str | None - error message if navigation failed
        - dialog_info: dict | None - dialog status if timeout occurred
        - recovery_attempted: bool - whether recovery was attempted
    """
    # Pre-flight: ensure we're in the Recruiter context by visiting home first
    # This handles cases where the browser is on a non-LinkedIn page
    home_result = _run_browser_command(
        browser_mode, "goto", RECRUITER_HOME_URL, timeout=30, check_dialog_on_timeout=True
    )
    if not home_result.get("error") and not home_result.get("timed_out"):
        time.sleep(2)

    # First attempt: direct navigation to Projects page
    result = _run_browser_command(
        browser_mode, "goto", PROJECTS_URL, timeout=30, check_dialog_on_timeout=True
    )

    if result.get("timed_out"):
        readiness = classify_browser_readiness(
            browser_mode,
            error=result.get("error"),
            dialog_info=result.get("dialog_info"),
        )
        error_msg = format_timeout_error(
            "navigate to Projects page",
            result,
            context=f"url={PROJECTS_URL}",
        )
        return {
            "success": False,
            "error": error_msg,
            "dialog_info": result.get("dialog_info"),
            "recovery_attempted": False,
            "failure_code": readiness.action_required.code
            if readiness.action_required
            else FailureCode.TIMEOUT,
            "action_required": readiness.action_required.to_dict()
            if readiness.action_required
            else ActionRequired.timeout(
                operation="navigate to Projects page"
            ).to_dict(),
        }

    if result.get("error"):
        readiness = classify_browser_readiness(browser_mode, error=result.get("error"))
        return {
            "success": False,
            "error": result["error"],
            "dialog_info": None,
            "recovery_attempted": False,
            "failure_code": readiness.action_required.code
            if readiness.action_required
            else FailureCode.AMBIGUOUS_STATE,
            "action_required": readiness.action_required.to_dict()
            if readiness.action_required
            else ActionRequired.ambiguous_state(details=result["error"]).to_dict(),
        }

    # Wait for page to load
    time.sleep(2)

    # Check page state and attempt recovery if needed
    probe = PageStateProbe(browser_mode)
    state = probe.classify_state()

    if state["state"] == "ready":
        return {
            "success": True,
            "error": None,
            "dialog_info": None,
            "recovery_attempted": False,
        }

    # Page not ready - attempt recovery
    recovery = RecoveryHelper(browser_mode, work_dir)
    recovery_result = recovery.attempt_recovery(
        target_url=PROJECTS_URL,
        context="navigate_to_projects",
    )

    if recovery_result["success"]:
        return {
            "success": True,
            "error": None,
            "dialog_info": None,
            "recovery_attempted": True,
        }

    return {
        "success": False,
        "error": recovery_result.get("error", "Page recovery failed"),
        "dialog_info": state.get("dialog_info"),
        "recovery_attempted": True,
        "failure_code": recovery_result.get("failure_code"),
        "action_required": recovery_result.get("action_required"),
    }


def wait_for_page_load(browser_mode: BrowserMode | str, max_wait: int = 10) -> bool:
    """Wait for page to be fully loaded."""
    for _ in range(max_wait * 2):
        result = run_browser_command(browser_mode, "eval", WAIT_FOR_LOAD_JS)
        if result.get("ready"):
            return True
        time.sleep(0.5)
    return False


def search_for_project(
    browser_mode: BrowserMode | str, project_name: str
) -> dict[str, Any]:
    """Search for a project by name on the Projects page."""
    js = SEARCH_PROJECT_JS.format(project_name=project_name)
    return run_browser_command(browser_mode, "eval", js)


def check_project_exists(
    browser_mode: BrowserMode | str, project_name: str
) -> dict[str, Any]:
    """Check if a project with the given name exists on the current page."""
    js = CHECK_PROJECT_EXISTS_JS.format(project_name=project_name)
    return run_browser_command(browser_mode, "eval", js)


def click_create_project(browser_mode: BrowserMode | str) -> dict[str, Any]:
    """Click the Create Project button."""
    return run_browser_command(browser_mode, "eval", CLICK_CREATE_PROJECT_JS)


def fill_create_form(
    browser_mode: BrowserMode | str, project_name: str, description: str
) -> dict[str, Any]:
    """Fill the project creation form."""
    js = FILL_CREATE_FORM_JS.format(project_name=project_name, description=description)
    return run_browser_command(browser_mode, "eval", js)


def submit_form(browser_mode: BrowserMode | str) -> dict[str, Any]:
    """Submit the form, with click-outside fallback for typeahead overlays."""
    # First try direct submit
    result = run_browser_command(browser_mode, "eval", SUBMIT_FORM_JS)

    if not result.get("submitted"):
        # Try clicking outside first to close any overlays
        run_browser_command(browser_mode, "eval", CLICK_OUTSIDE_JS)
        time.sleep(0.5)
        # Try submit again
        result = run_browser_command(browser_mode, "eval", SUBMIT_FORM_JS)

    return result


def check_untitled(browser_mode: BrowserMode | str) -> dict[str, Any]:
    """Check if the current project is untitled."""
    return run_browser_command(browser_mode, "eval", CHECK_UNTITLED_JS)


def rename_project(
    browser_mode: BrowserMode | str, project_name: str
) -> dict[str, Any]:
    """Rename an untitled project."""
    js = RENAME_PROJECT_JS.format(project_name=project_name)
    return run_browser_command(browser_mode, "eval", js)


def get_current_url(browser_mode: BrowserMode | str) -> dict[str, Any]:
    """Get the current page URL and title."""
    return run_browser_command(browser_mode, "eval", GET_CURRENT_URL_JS)


def navigate_to_search_page(browser_mode: BrowserMode | str) -> dict[str, Any]:
    """Navigate to the Recruiter search page by clicking the search tab/link.

    Args:
        browser_mode: BrowserMode instance or CDP port string for browser operations

    Returns:
        Dict with success status and the final URL.
    """
    # First try clicking the search tab/link
    result = run_browser_command(browser_mode, "eval", NAVIGATE_TO_SEARCH_JS)

    if result.get("alreadyOnSearch"):
        return {"success": True, "url": result.get("url"), "method": "already_there"}

    if result.get("clicked"):
        # Wait for navigation to complete
        time.sleep(2)
        if wait_for_page_load(browser_mode, max_wait=5):
            # Poll for URL transition - the recruiterSearch URL may update after page load
            # This handles the delayed URL transition observed in live testing
            # Keep polling past bare URLs until a contextual URL appears
            for _ in range(10):  # Poll for up to 5 seconds
                url_result = get_current_url(browser_mode)
                final_url = url_result.get("url", "")
                if is_contextual_search_url(final_url):
                    return {"success": True, "url": final_url, "method": "click"}
                time.sleep(0.5)

    # Fallback: try to derive search URL from current URL
    derive_result = run_browser_command(browser_mode, "eval", DERIVE_SEARCH_URL_JS)
    if derive_result.get("derived"):
        search_url = derive_result.get("searchUrl")
        # Navigate to derived URL using guarded browser command
        goto_result = _run_browser_command(browser_mode, "goto", search_url, timeout=30)
        if goto_result.get("error"):
            return {
                "success": False,
                "error": f"Could not navigate to search page: {goto_result['error']}",
            }
        time.sleep(2)
        if wait_for_page_load(browser_mode, max_wait=5):
            url_result = get_current_url(browser_mode)
            final_url = url_result.get("url", "")
            if "discover/recruiterSearch" in final_url:
                return {"success": True, "url": final_url, "method": "derived"}

    return {"success": False, "error": "Could not navigate to search page"}


def is_contextual_search_url(url: str) -> bool:
    """Check if URL has contextual search params needed for extraction.

    A bare /discover/recruiterSearch URL without context params will hang
    on "Loading search results". Contextual params include:
    - searchContextId
    - searchHistoryId
    - searchRequestId
    - projectId (from an actual search, not just the base project)

    Args:
        url: The URL to check

    Returns:
        True if URL has at least one contextual search parameter
    """
    # Use shared implementation (no project_id validation needed here)
    return _is_contextual_search_url(url)


def resolve_search_url(browser_mode: BrowserMode | str, current_url: str) -> str | None:
    """Resolve the best search URL from current page state.

    Tries multiple strategies:
    1. If already on contextual recruiterSearch page, return current URL
    2. Click search tab/link and return resulting URL (if contextual)
    3. Derive search URL from project ID and navigate (if contextual)
    4. Return None if only a bare URL is available (fail closed)

    Args:
        browser_mode: BrowserMode instance or CDP port string for browser operations
        current_url: The current page URL

    Returns:
        Contextual search URL if available, None otherwise
    """
    # Already on search page with context?
    if is_contextual_search_url(current_url):
        return current_url

    # If we're on a bare search page without context, don't treat it as ready
    # This prevents the "hang on Loading search results" bug
    if "discover/recruiterSearch" in current_url:
        # Try navigation to get a contextual URL
        pass  # Fall through to navigation attempt

    # Try navigation via click
    nav_result = navigate_to_search_page(browser_mode)
    if nav_result.get("success"):
        nav_url = nav_result.get("url", "")
        if is_contextual_search_url(nav_url):
            return nav_url
        # Navigation succeeded but still no context - don't return bare URL
        return None

    # All strategies failed - fail closed rather than returning bare URL
    return None


def validate_navigation_result(
    browser_mode: BrowserMode | str,
    expected_url_patterns: list[str],
    context: str,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """Validate that navigation succeeded and we're on the expected page.

    Args:
        browser_mode: BrowserMode instance or CDP port string for browser operations
        expected_url_patterns: URL patterns that must be present after navigation
        context: Context string for error messages
        work_dir: Optional working directory for incident reporting

    Returns:
        Dict with:
            - success: bool - whether validation passed
            - current_url: str - the actual current URL
            - error: str | None - error message if validation failed
    """
    # Get current URL
    url_result = get_current_url(browser_mode)
    current_url = url_result.get("url", "")

    # Check if URL matches expected patterns
    if not current_url:
        return {
            "success": False,
            "current_url": "",
            "error": f"{context}: Could not retrieve current URL after navigation",
        }

    # Check if we're on a talent page
    if "/talent/" not in current_url:
        return {
            "success": False,
            "current_url": current_url,
            "error": f"{context}: Navigation landed on non-talent page: {current_url}",
        }

    # Check expected patterns
    if expected_url_patterns:
        matches = any(pattern in current_url for pattern in expected_url_patterns)
        if not matches:
            return {
                "success": False,
                "current_url": current_url,
                "error": f"{context}: URL '{current_url}' does not match expected patterns: {expected_url_patterns}",
            }

    return {
        "success": True,
        "current_url": current_url,
        "error": None,
    }


def validate_project_context(
    browser_mode: BrowserMode | str,
    project_name: str,
    expected_project_id: str | None = None,
) -> dict[str, Any]:
    """Validate that the current page belongs to the intended project context.

    Args:
        browser_mode: BrowserMode instance or CDP port string for browser operations
        project_name: Expected project name
        expected_project_id: Optional expected project ID from URL

    Returns:
        Dict with:
            - valid: bool - whether project context is valid
            - current_url: str - the actual current URL
            - project_id: str | None - extracted project ID from URL
            - error: str | None - error message if validation failed
    """
    url_result = get_current_url(browser_mode)
    current_url = url_result.get("url", "")

    if not current_url:
        return {
            "valid": False,
            "current_url": "",
            "project_id": None,
            "error": "Could not retrieve current URL for project context validation",
        }

    # Extract project ID from URL
    import re

    # Match /talent/hire/{numeric_id} followed by /, ?, #, or end of string
    match = re.search(r"/talent/hire/(\d+)(?:/|$|\?|#)", current_url)
    project_id = match.group(1) if match else None

    # Validate project ID if expected
    if expected_project_id and project_id != expected_project_id:
        return {
            "valid": False,
            "current_url": current_url,
            "project_id": project_id,
            "error": f"Project ID mismatch: expected {expected_project_id}, got {project_id}",
        }

    # Check if URL is a valid talent project URL
    if "/talent/hire/" not in current_url:
        return {
            "valid": False,
            "current_url": current_url,
            "project_id": project_id,
            "error": f"URL does not appear to be a valid project page: {current_url}",
        }

    return {
        "valid": True,
        "current_url": current_url,
        "project_id": project_id,
        "error": None,
    }


def ensure_project_exists(
    project_name: str,
    description: str,
    browser_mode: BrowserMode | str,
    work_dir: str | None = None,
    require_contextual_url: bool = True,
) -> dict[str, Any]:
    """Main logic to ensure a Recruiter project exists.

    Args:
        project_name: Name of the project to find or create
        description: Description for new projects
        browser_mode: BrowserMode instance or CDP port string for browser operations
        work_dir: Optional working directory for incident reporting
        require_contextual_url: If False, returns project URL even without search context
            (used by bootstrap when project identity is known but search URL not yet available)

    Returns dict with status, url, project_id, and message.
    """
    result = {
        "status": "error",
        "project_name": project_name,
        "url": None,
        "project_id": None,
        "message": "",
        "failure_code": None,
        "action_required": None,
    }

    # Step 1: Navigate to Projects page (with recovery)
    nav_result = navigate_to_projects(browser_mode, work_dir)
    if not nav_result["success"]:
        result["message"] = (
            nav_result.get("error") or "Failed to navigate to Projects page"
        )
        result["failure_code"] = nav_result.get("failure_code")
        result["action_required"] = nav_result.get("action_required")
        return result

    if not wait_for_page_load(browser_mode):
        result["message"] = "Page did not load in time"
        result["failure_code"] = FailureCode.TIMEOUT
        result["action_required"] = ActionRequired.timeout(
            operation="wait for Projects page load"
        ).to_dict()
        return result

    # Validate we're on the Projects page
    validation = validate_navigation_result(
        browser_mode,
        expected_url_patterns=["/talent/projects"],
        context="Navigate to Projects page",
        work_dir=work_dir,
    )
    if not validation["success"]:
        result["message"] = validation["error"]
        result["failure_code"] = FailureCode.WRONG_PAGE
        result["action_required"] = ActionRequired.wrong_page(
            actual_url=validation.get("current_url", ""),
            expected_url="/talent/projects",
        ).to_dict()
        return result

    # Step 2: Search for existing project
    search_result = search_for_project(browser_mode, project_name)
    time.sleep(1)  # Wait for search results

    # Step 3: Check if project exists
    exists_result = check_project_exists(browser_mode, project_name)

    if exists_result.get("found"):
        # Project exists - navigate to it and get URL
        url = exists_result.get("url")
        if url:
            # Navigate to the project URL using guarded browser command
            goto_result = _run_browser_command(browser_mode, "goto", url, timeout=30)
            if goto_result.get("error"):
                result["message"] = (
                    f"Failed to navigate to project: {goto_result['error']}"
                )
                result["failure_code"] = FailureCode.BROWSER_UNAVAILABLE
                result["action_required"] = ActionRequired.browser_unavailable(
                    cdp_port=browser_mode.cdp_port
                    if hasattr(browser_mode, "cdp_port")
                    else None
                ).to_dict()
                return result
            time.sleep(2)

            # Validate navigation succeeded
            open_validation = validate_navigation_result(
                browser_mode,
                expected_url_patterns=["/talent/hire/"],
                context="Open existing project",
                work_dir=work_dir,
            )
            if not open_validation["success"]:
                result["message"] = open_validation["error"]
                result["failure_code"] = FailureCode.WRONG_PAGE
                result["action_required"] = ActionRequired.wrong_page(
                    actual_url=open_validation.get("current_url", ""),
                    expected_url="/talent/hire/",
                ).to_dict()
                return result

            # Wait for page load and resolve search URL
            wait_for_page_load(browser_mode)
            url_result = get_current_url(browser_mode)
            current_url = url_result.get("url", url)

            # Validate project context and extract project_id
            context_validation = validate_project_context(browser_mode, project_name)
            if not context_validation["valid"]:
                result["message"] = context_validation["error"]
                result["failure_code"] = FailureCode.VERIFICATION_FAILED
                result["action_required"] = ActionRequired.verification_failed(
                    details=f"Project context validation failed: {context_validation['error']}"
                ).to_dict()
                return result

            # Store project_id for bootstrap use
            result["project_id"] = context_validation.get("project_id")

            # Resolve to search URL (extraction-ready)
            search_url = resolve_search_url(browser_mode, current_url)

            # If not requiring contextual URL, return with whatever we have
            if not require_contextual_url:
                result["status"] = "existing"
                result["url"] = search_url or current_url
                result["message"] = f"Found existing project: {project_name}"
                return result

            # Validate search URL was resolved with context
            if search_url is None:
                result["message"] = (
                    f"Could not resolve contextual search URL from {current_url}. "
                    "The page may not have active search context. "
                    "Try performing a search in LinkedIn Recruiter first."
                )
                result["failure_code"] = FailureCode.AMBIGUOUS_STATE
                result["action_required"] = ActionRequired.ambiguous_state(
                    details="Could not resolve contextual search URL. Try performing a search in LinkedIn Recruiter first."
                ).to_dict()
                return result

            # Validate final URL is search-ready
            if "discover/recruiterSearch" not in search_url:
                result["message"] = (
                    f"Final URL is not search-ready: {search_url}. "
                    "Expected /discover/recruiterSearch path."
                )
                result["failure_code"] = FailureCode.WRONG_PAGE
                result["action_required"] = ActionRequired.wrong_page(
                    actual_url=search_url,
                    expected_url="/discover/recruiterSearch",
                ).to_dict()
                return result

            result["status"] = "existing"
            result["url"] = search_url
            result["message"] = f"Found existing project: {project_name}"
            return result

    # Step 4: Create new project
    create_btn_result = click_create_project(browser_mode)
    if not create_btn_result.get("clicked"):
        result["message"] = (
            f"Could not click Create Project button: {create_btn_result.get('error', 'Unknown error')}"
        )
        result["failure_code"] = FailureCode.ELEMENT_MISSING
        result["action_required"] = ActionRequired.element_missing(
            selector="Create Project button",
            page_url="",
        ).to_dict()
        return result

    time.sleep(2)  # Wait for form to appear

    # Verify form appeared by checking for project name input
    form_verify = run_browser_command(
        browser_mode,
        "eval",
        """
    (function() {
        const nameInput = document.querySelector('input[id$="-projectName"], input[id*="-projectName"]');
        const heading = document.querySelector('h1, h2, h3');
        return {
            formReady: !!nameInput,
            inputId: nameInput ? nameInput.id : null,
            pageHeading: heading ? heading.textContent.trim() : null
        };
    })()
    """,
    )
    if not form_verify.get("formReady"):
        result["message"] = (
            "Project creation form did not appear after clicking Create new"
        )
        result["failure_code"] = FailureCode.ELEMENT_MISSING
        result["action_required"] = ActionRequired.element_missing(
            selector="project creation form",
            page_url="",
        ).to_dict()
        return result

    # Step 5: Fill the form
    fill_result = fill_create_form(browser_mode, project_name, description)
    if not fill_result.get("nameFilled"):
        result["message"] = "Could not find project name input in form"
        result["failure_code"] = FailureCode.ELEMENT_MISSING
        result["action_required"] = ActionRequired.element_missing(
            selector="project name input",
            page_url="",
        ).to_dict()
        return result

    # Verify the name was actually set correctly
    if not fill_result.get("nameVerified"):
        result["message"] = (
            f"Project name input found but value could not be set. Actual value: {fill_result.get('actualNameValue')}"
        )
        result["failure_code"] = FailureCode.ELEMENT_MISSING
        result["action_required"] = ActionRequired.element_missing(
            selector="project name input value setting",
            page_url="",
        ).to_dict()
        return result

    time.sleep(1)

    # Step 6: Submit the form
    submit_result = submit_form(browser_mode)

    # Validate submission succeeded by checking we're no longer on projects page
    time.sleep(3)  # Wait for creation

    submit_validation = validate_navigation_result(
        browser_mode,
        expected_url_patterns=["/talent/hire/"],
        context="Project creation submit",
        work_dir=work_dir,
    )
    if not submit_validation["success"]:
        result["message"] = f"Form submission failed: {submit_validation['error']}"
        result["failure_code"] = FailureCode.WRONG_PAGE
        result["action_required"] = ActionRequired.wrong_page(
            actual_url=submit_validation.get("current_url", ""),
            expected_url="/talent/hire/",
        ).to_dict()
        return result

    # Step 7: Check if we landed on an untitled project
    untitled_check = check_untitled(browser_mode)
    if untitled_check.get("isUntitled"):
        # Need to rename - navigate to project settings for reliable rename
        url_result = get_current_url(browser_mode)
        current_url = url_result.get("url", "")
        project_id_match = re.search(r"/talent/hire/(\d+)", current_url)
        if project_id_match:
            overview_url = f"https://www.linkedin.com/talent/hire/{project_id_match.group(1)}/overview"
            # Navigate to overview page where rename is more reliable
            goto_result = _run_browser_command(
                browser_mode, "goto", overview_url, timeout=30
            )
            if not goto_result.get("error"):
                time.sleep(2)
                rename_project(browser_mode, project_name)
                time.sleep(1)
                # Verify rename succeeded
                untitled_check = check_untitled(browser_mode)
                if untitled_check.get("isUntitled"):
                    # Retry once more
                    rename_project(browser_mode, project_name)
                    time.sleep(1)
                    untitled_check = check_untitled(browser_mode)
                    if untitled_check.get("isUntitled"):
                        print(
                            f"Warning: Project rename may not have succeeded. Still showing: {untitled_check.get('title')}",
                            file=sys.stderr,
                        )
        else:
            rename_project(browser_mode, project_name)
            time.sleep(1)
            # Verify rename succeeded
            untitled_check = check_untitled(browser_mode)
            if untitled_check.get("isUntitled"):
                # Retry once more
                rename_project(browser_mode, project_name)
                time.sleep(1)
                untitled_check = check_untitled(browser_mode)
                if untitled_check.get("isUntitled"):
                    print(
                        f"Warning: Project rename may not have succeeded. Still showing: {untitled_check.get('title')}",
                        file=sys.stderr,
                    )

    # Step 8: Get the final URL and resolve to search URL
    url_result = get_current_url(browser_mode)
    final_url = url_result.get("url")

    if final_url and "/talent/" in final_url:
        # Validate project context
        context_validation = validate_project_context(browser_mode, project_name)
        if not context_validation["valid"]:
            result["message"] = context_validation["error"]
            result["failure_code"] = FailureCode.VERIFICATION_FAILED
            result["action_required"] = ActionRequired.verification_failed(
                details=f"Project context validation failed: {context_validation['error']}"
            ).to_dict()
            return result

        # Store project_id for bootstrap use
        result["project_id"] = context_validation.get("project_id")

        # Resolve to search URL (extraction-ready)
        search_url = resolve_search_url(browser_mode, final_url)

        # If not requiring contextual URL, return with whatever we have
        if not require_contextual_url:
            result["status"] = "created"
            result["url"] = search_url or final_url
            result["message"] = f"Created new project: {project_name}"
            return result

        # Validate search URL was resolved with context
        if search_url is None:
            result["message"] = (
                f"Could not resolve contextual search URL from {final_url}. "
                "The page may not have active search context. "
                "Try performing a search in LinkedIn Recruiter first."
            )
            result["failure_code"] = FailureCode.AMBIGUOUS_STATE
            result["action_required"] = ActionRequired.ambiguous_state(
                details="Could not resolve contextual search URL. Try performing a search in LinkedIn Recruiter first."
            ).to_dict()
            return result

        # Validate final URL is search-ready and belongs to project context
        if "discover/recruiterSearch" not in search_url:
            result["message"] = (
                f"Final URL is not search-ready: {search_url}. "
                "Expected /discover/recruiterSearch path."
            )
            result["failure_code"] = FailureCode.WRONG_PAGE
            result["action_required"] = ActionRequired.wrong_page(
                actual_url=search_url,
                expected_url="/discover/recruiterSearch",
            ).to_dict()
            return result

        # Validate the search URL contains the expected project ID
        project_id = context_validation.get("project_id")
        if project_id and project_id not in search_url:
            result["message"] = (
                f"Search URL does not contain expected project ID {project_id}: {search_url}"
            )
            result["failure_code"] = FailureCode.VERIFICATION_FAILED
            result["action_required"] = ActionRequired.verification_failed(
                details=f"Search URL does not contain expected project ID {project_id}"
            ).to_dict()
            return result

        result["status"] = "created"
        result["url"] = search_url
        result["message"] = f"Created new project: {project_name}"
    else:
        result["message"] = (
            f"Project creation may have succeeded but could not verify URL. Current: {final_url}"
        )
        result["failure_code"] = FailureCode.AMBIGUOUS_STATE
        result["action_required"] = ActionRequired.ambiguous_state(
            details=f"Project creation may have succeeded but could not verify URL. Current: {final_url}"
        ).to_dict()

    return result


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Ensure a LinkedIn Recruiter project exists and return its URL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 ensure_recruiter_project.py \\
        --project-name "SoC Digital Design Engineer, Multimedia Lab" \\
        --description "Hardware design role for video codec solutions" \\

    python3 ensure_recruiter_project.py \\
        --project-name "Senior ML Engineer Search" \\
        --cdp-port 9231

Output:
    JSON with status (existing|created), project_name, url, and message
        """,
    )

    parser.add_argument(
        "--project-name",
        required=True,
        help="Exact name of the project to find or create",
    )
    parser.add_argument(
        "--description", default="", help="Project description (used when creating new)"
    )
    parser.add_argument(
        "--cdp-port",
        default="9230",
        help="Chrome DevTools Protocol port (default: 9230)",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Resolve work_dir from RuntimeManager for consistent profile handling
    from runtime_manager import RuntimeManager

    manager = RuntimeManager()
    profile = manager._resolve_profile()
    work_dir = profile.get("WORK_DIR")

    # Create BrowserMode from CLI arguments (CDP mode by default for CLI)
    browser_mode = BrowserMode(mode="cdp", cdp_port=args.cdp_port)

    result = ensure_project_exists(
        project_name=args.project_name,
        description=args.description,
        browser_mode=browser_mode,
        work_dir=work_dir,
    )

    # Print JSON output
    print(json.dumps(result, indent=2))

    # Return appropriate exit code
    if result["status"] in ("existing", "created"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
