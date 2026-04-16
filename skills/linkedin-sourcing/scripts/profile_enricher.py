#!/usr/bin/env python3
"""Profile enrichment utility for LinkedIn sourcing.

Provides compact profile enrichment with structured failure metadata.
Does NOT mutate the workbook directly - returns enrichment results for
upstream processing.

Usage:
    from profile_enricher import enrich_profile, EnrichmentResult

    result = enrich_profile(profile_url, cdp_port=9234)
    if result.success:
        print(result.enrichment_notes)
    else:
        print(result.action_required)
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


@dataclass
class EnrichmentResult:
    """Structured result from profile enrichment attempt.

    Attributes:
        success: Whether enrichment succeeded
        phase: Phase identifier (always "enrich" for this utility)
        failure_code: Machine-readable failure code if failed
        action_required: Structured manual intervention instructions if failed
        safe_to_retry: Whether the operation can be safely retried
        partial_result: Any partial data collected before failure
        enrichment_notes: Compact enrichment facts (skills, experience summary)
        resume_hint: One-line guidance for manual continuation
    """

    success: bool
    phase: str = "enrich"
    failure_code: str | None = None
    action_required: dict[str, Any] | None = None
    safe_to_retry: bool = True
    partial_result: dict[str, Any] | None = None
    enrichment_notes: str | None = None
    resume_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "phase": self.phase,
            "failure_code": self.failure_code,
            "action_required": self.action_required,
            "safe_to_retry": self.safe_to_retry,
            "partial_result": self.partial_result,
            "enrichment_notes": self.enrichment_notes,
            "resume_hint": self.resume_hint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnrichmentResult":
        """Create result from dictionary."""
        return cls(
            success=data.get("success", False),
            phase=data.get("phase", "enrich"),
            failure_code=data.get("failure_code"),
            action_required=data.get("action_required"),
            safe_to_retry=data.get("safe_to_retry", True),
            partial_result=data.get("partial_result"),
            enrichment_notes=data.get("enrichment_notes"),
            resume_hint=data.get("resume_hint"),
        )


def _build_action_required(
    code: str,
    summary: str,
    steps: list[str],
    context: dict[str, Any] | None = None,
    can_retry: bool = True,
) -> dict[str, Any]:
    """Build structured action_required dict for browser/manual failures.

    Args:
        code: Machine-readable error code
        summary: Human-readable summary
        steps: List of manual steps to resolve
        context: Optional additional context
        can_retry: Whether retry is expected to succeed after resolution

    Returns:
        Structured action_required dictionary
    """
    return {
        "code": code,
        "summary": summary,
        "steps": steps,
        "can_retry": can_retry,
        "context": context or {},
    }


def _extract_compact_facts(page_data: dict[str, Any]) -> str:
    """Extract compact enrichment facts from page data.

    Creates a concise summary suitable for storage in enrichment_notes column.
    Format: "Skills: X, Y | Experience: Z years at A, B | Recent: C"

    Args:
        page_data: Raw data extracted from profile page

    Returns:
        Compact enrichment notes string
    """
    facts = []

    # Extract skills (top 3-5)
    skills = page_data.get("skills", [])
    if skills:
        top_skills = skills[:5]
        facts.append(f"Skills: {', '.join(top_skills)}")

    # Extract experience summary
    experiences = page_data.get("experience", [])
    if experiences:
        companies = []
        total_years = 0
        for exp in experiences[:3]:  # Top 3 experiences
            company = exp.get("company", "")
            if company and company not in companies:
                companies.append(company)
            # Rough year extraction
            duration = exp.get("duration", "")
            if "year" in duration.lower():
                try:
                    years = int(duration.split()[0])
                    total_years += years
                except (ValueError, IndexError):
                    pass

        if companies:
            exp_str = f"Experience: {', '.join(companies[:3])}"
            if total_years > 0:
                exp_str += f" (~{total_years}y)"
            facts.append(exp_str)

    # Extract recent activity or headline insights
    headline = page_data.get("headline", "")
    if headline and len(headline) > 5:
        # Truncate long headlines
        short_headline = headline[:80] + "..." if len(headline) > 80 else headline
        facts.append(f"Headline: {short_headline}")

    # Extract education if available
    education = page_data.get("education", [])
    if education:
        schools = [edu.get("school", "") for edu in education[:2] if edu.get("school")]
        if schools:
            facts.append(f"Education: {', '.join(schools)}")

    if facts:
        return " | ".join(facts)

    # Fallback: return whatever headline we have
    return headline or "Profile viewed; no structured data extracted"


def enrich_profile(
    profile_url: str,
    cdp_port: str = "9234",
    timeout: int = 60,
    use_browser: bool = True,
) -> EnrichmentResult:
    """Enrich a candidate profile with compact facts from LinkedIn.

    This function attempts to extract additional profile information
    (skills, experience summary, education) to improve personalization.

    Args:
        profile_url: LinkedIn profile URL
        cdp_port: Chrome DevTools Protocol port
        timeout: Operation timeout in seconds
        use_browser: Whether to use browser automation (vs mock/test mode)

    Returns:
        EnrichmentResult with structured outcome data
    """
    if not profile_url:
        return EnrichmentResult(
            success=False,
            failure_code="invalid_input",
            action_required=_build_action_required(
                code="invalid_input",
                summary="No profile URL provided",
                steps=[
                    "Check that the candidate has a valid profile_url in the workbook"
                ],
                can_retry=False,
            ),
            safe_to_retry=False,
            resume_hint="Add profile_url to candidate row before enrichment",
        )

    if not use_browser:
        # Test/mock mode - return simulated success
        return EnrichmentResult(
            success=True,
            enrichment_notes="Skills: Python, ML | Experience: 5y at Tech Co | Headline: Senior Engineer",
            resume_hint="Enrichment complete (mock mode)",
        )

    # Attempt browser-based enrichment via agent-browser
    try:
        result = _enrich_via_browser(profile_url, cdp_port, timeout)
        return result
    except Exception as e:
        return EnrichmentResult(
            success=False,
            failure_code="browser_exception",
            action_required=_build_action_required(
                code="browser_exception",
                summary=f"Browser automation failed: {e}",
                steps=[
                    "Verify Chrome is running with CDP enabled",
                    "Check that the profile URL is accessible",
                    "Retry enrichment after browser is ready",
                ],
                context={"error": str(e), "profile_url": profile_url},
            ),
            safe_to_retry=True,
            resume_hint="Ensure Chrome is running on CDP port, then retry",
        )


# JavaScript for extracting profile data from LinkedIn profile pages
PROFILE_EXTRACTION_JS = r"""
(() => {
    const data = {
        skills: [],
        experience: [],
        education: [],
        headline: "",
        name: ""
    };

    // Extract name
    const nameEl = document.querySelector('h1[data-test-id="profile-name"], h1.inline.t-24.v-align-middle.break-words, h1.t-24.inline.break-words');
    if (nameEl) {
        data.name = nameEl.textContent.trim();
    }

    // Extract headline
    const headlineEl = document.querySelector('div[data-test-id="profile-headline"], div.text-body-medium.break-words, .pv-top-card-v2-ctas + div div.text-body-medium');
    if (headlineEl) {
        data.headline = headlineEl.textContent.trim();
    }

    // Extract skills from skills section
    const skillElements = document.querySelectorAll('[data-test-id="skill-pill"], .pv-skill-category-entity__name-text, .skill-category-entity__name, a[href*="/skills/"]');
    skillElements.forEach(el => {
        const skill = el.textContent.trim();
        if (skill && !data.skills.includes(skill)) {
            data.skills.push(skill);
        }
    });

    // Extract experience
    const expSections = document.querySelectorAll('section:has(#experience), section:has([data-test-id="experience-section"]) .artdeco-list__item, #experience ~ .pvs-list__outer-container .artdeco-list__item, [data-test-id="experience-section"] li');
    expSections.forEach(section => {
        const titleEl = section.querySelector('span[aria-hidden="true"], .t-bold span, .mr1.t-bold');
        const companyEl = section.querySelector('.t-14.t-normal:not(.t-black--light) span, .pv-entity__secondary-title, a[data-field="experience_company_logo"] + div span');
        const durationEl = section.querySelector('.t-14.t-black--light span, .pv-entity__date-range span:not(.visually-hidden)');

        if (titleEl || companyEl) {
            data.experience.push({
                title: titleEl ? titleEl.textContent.trim() : "",
                company: companyEl ? companyEl.textContent.trim() : "",
                duration: durationEl ? durationEl.textContent.trim() : ""
            });
        }
    });

    // Fallback experience extraction
    if (data.experience.length === 0) {
        const expTitles = document.querySelectorAll('#experience-section .pv-entity__summary-info h3, .experience-section h3');
        expTitles.forEach(el => {
            const parent = el.closest('li, .artdeco-list__item');
            const company = parent ? parent.querySelector('.pv-entity__secondary-title, .company-name') : null;
            data.experience.push({
                title: el.textContent.trim(),
                company: company ? company.textContent.trim() : "",
                duration: ""
            });
        });
    }

    // Extract education
    const eduSections = document.querySelectorAll('section:has(#education), #education ~ .pvs-list__outer-container .artdeco-list__item, [data-test-id="education-section"] li');
    eduSections.forEach(section => {
        const schoolEl = section.querySelector('.t-bold span, .pv-entity__school-name');
        if (schoolEl) {
            data.education.push({
                school: schoolEl.textContent.trim()
            });
        }
    });

    // Fallback education extraction
    if (data.education.length === 0) {
        const eduSchools = document.querySelectorAll('#education-section .pv-entity__school-name, .education-section .school-name');
        eduSchools.forEach(el => {
            data.education.push({ school: el.textContent.trim() });
        });
    }

    return data;
})()
"""


def _enrich_via_browser(
    profile_url: str,
    cdp_port: str,
    timeout: int,
) -> EnrichmentResult:
    """Attempt enrichment via browser automation.

    Uses agent-browser open + eval to navigate to profile and extract structured data.
    Returns structured failure metadata on any issue.

    Args:
        profile_url: LinkedIn profile URL
        cdp_port: Chrome DevTools Protocol port
        timeout: Operation timeout

    Returns:
        EnrichmentResult with success or structured failure
    """
    # Step 1: Navigate to profile URL
    open_cmd = [
        "agent-browser",
        "--cdp",
        cdp_port,
        "open",
        profile_url,
    ]

    try:
        open_result = subprocess.run(
            open_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if open_result.returncode != 0:
            error_msg = open_result.stderr.strip() or "Navigation failed"
            # Check for common navigation failures
            is_auth_error = any(
                kw in error_msg.lower()
                for kw in ["auth", "login", "signin", "checkpoint"]
            )
            is_timeout = "timeout" in error_msg.lower()

            if is_auth_error:
                return EnrichmentResult(
                    success=False,
                    failure_code="auth_required",
                    action_required=_build_action_required(
                        code="auth_required",
                        summary="LinkedIn authentication required",
                        steps=[
                            "Open Chrome and navigate to linkedin.com",
                            "Log in to your LinkedIn account",
                            "Ensure you can access the profile manually",
                            "Retry enrichment after authentication",
                        ],
                        context={"error": error_msg, "profile_url": profile_url},
                        can_retry=True,
                    ),
                    safe_to_retry=True,
                    resume_hint="Authenticate in Chrome, then retry",
                )

            return EnrichmentResult(
                success=False,
                failure_code="navigation_failed",
                action_required=_build_action_required(
                    code="navigation_failed",
                    summary=f"Failed to navigate to profile: {error_msg[:100]}",
                    steps=[
                        "Check browser state: verify Chrome is responsive",
                        "Navigate to profile manually to verify accessibility",
                        "Check for LinkedIn verification prompts or rate limits",
                        "Retry enrichment after resolving any prompts",
                    ],
                    context={
                        "error": error_msg[:500],
                        "profile_url": profile_url,
                    },
                    can_retry=True,
                ),
                safe_to_retry=True,
                resume_hint="Check browser for prompts, then retry",
            )

    except subprocess.TimeoutExpired:
        return EnrichmentResult(
            success=False,
            failure_code="navigation_timeout",
            action_required=_build_action_required(
                code="navigation_timeout",
                summary=f"Navigation to profile timed out after {timeout}s",
                steps=[
                    "Check if Chrome is responsive",
                    "Verify network connectivity to LinkedIn",
                    "Check for LinkedIn rate limiting or verification",
                    "Retry with longer timeout if needed",
                ],
                context={"timeout": timeout, "profile_url": profile_url},
                can_retry=True,
            ),
            safe_to_retry=True,
            resume_hint="Check browser responsiveness, then retry",
        )

    except FileNotFoundError:
        return EnrichmentResult(
            success=False,
            failure_code="agent_browser_not_found",
            action_required=_build_action_required(
                code="agent_browser_not_found",
                summary="agent-browser command not found in PATH",
                steps=[
                    "Install agent-browser: npm install -g agent-browser",
                    "Verify installation: agent-browser --version",
                    "Retry after installation",
                ],
                can_retry=False,
            ),
            safe_to_retry=False,
            resume_hint="Install agent-browser, then retry",
        )

    # Step 2: Extract profile data via JavaScript evaluation
    eval_cmd = [
        "agent-browser",
        "--cdp",
        cdp_port,
        "eval",
        PROFILE_EXTRACTION_JS,
    ]

    try:
        eval_result = subprocess.run(
            eval_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Check for extraction success BEFORE parsing stdout
        # This ensures JS/runtime failures are properly labeled as extraction_failed
        # rather than being mislabeled as parse errors
        if eval_result.returncode != 0:
            error_msg = eval_result.stderr.strip() or "JavaScript evaluation failed"
            return EnrichmentResult(
                success=False,
                failure_code="extraction_failed",
                action_required=_build_action_required(
                    code="extraction_failed",
                    summary=f"Profile data extraction failed: {error_msg[:100]}",
                    steps=[
                        "Check browser state and retry",
                        "Verify the profile page loaded correctly",
                        "Check for LinkedIn security checks",
                    ],
                    context={
                        "error": error_msg[:500],
                        "profile_url": profile_url,
                    },
                    can_retry=True,
                ),
                safe_to_retry=True,
                resume_hint="Check browser state and retry",
            )

        # Parse JSON output only after confirming success
        try:
            page_data = json.loads(eval_result.stdout.strip())
            # Handle double-encoded JSON
            if isinstance(page_data, str):
                page_data = json.loads(page_data)
        except json.JSONDecodeError:
            # Non-JSON output means extraction didn't complete properly
            return EnrichmentResult(
                success=False,
                failure_code="extraction_parse_error",
                action_required=_build_action_required(
                    code="extraction_parse_error",
                    summary="Profile extraction returned non-JSON output",
                    steps=[
                        "Check browser state: verify Chrome is responsive",
                        "Navigate to profile manually to verify accessibility",
                        "Check for LinkedIn verification prompts or rate limits",
                        "Retry enrichment after resolving any prompts",
                    ],
                    context={
                        "stdout": eval_result.stdout[:500],
                        "stderr": eval_result.stderr[:500],
                        "returncode": eval_result.returncode,
                    },
                ),
                safe_to_retry=True,
                resume_hint="Check browser for prompts, then retry",
            )

        # Success - extract compact facts from parsed data
        enrichment_notes = _extract_compact_facts(page_data)

        return EnrichmentResult(
            success=True,
            enrichment_notes=enrichment_notes,
            resume_hint="Enrichment complete - proceed to draft",
        )

    except subprocess.TimeoutExpired:
        return EnrichmentResult(
            success=False,
            failure_code="extraction_timeout",
            action_required=_build_action_required(
                code="extraction_timeout",
                summary=f"Profile data extraction timed out after {timeout}s",
                steps=[
                    "Check if Chrome is responsive",
                    "Verify network connectivity to LinkedIn",
                    "Check for LinkedIn rate limiting or verification",
                    "Retry with longer timeout if needed",
                ],
                context={"timeout": timeout, "profile_url": profile_url},
                can_retry=True,
            ),
            safe_to_retry=True,
            resume_hint="Check browser responsiveness, then retry",
        )

    except FileNotFoundError:
        return EnrichmentResult(
            success=False,
            failure_code="agent_browser_not_found",
            action_required=_build_action_required(
                code="agent_browser_not_found",
                summary="agent-browser command not found in PATH",
                steps=[
                    "Install agent-browser: npm install -g agent-browser",
                    "Verify installation: agent-browser --version",
                    "Retry after installation",
                ],
                can_retry=False,
            ),
            safe_to_retry=False,
            resume_hint="Install agent-browser, then retry",
        )


def enrich_profile_batch(
    profile_urls: list[str],
    cdp_port: str = "9234",
    timeout: int = 60,
    continue_on_failure: bool = True,
    use_browser: bool = True,
) -> list[EnrichmentResult]:
    """Enrich multiple profiles in batch.

    Args:
        profile_urls: List of LinkedIn profile URLs
        cdp_port: Chrome DevTools Protocol port
        timeout: Per-profile timeout
        continue_on_failure: Whether to continue after individual failures
        use_browser: Whether to use browser automation

    Returns:
        List of EnrichmentResult objects (same order as input)
    """
    results = []
    for url in profile_urls:
        result = enrich_profile(url, cdp_port, timeout, use_browser)
        results.append(result)

        if not result.success and not continue_on_failure:
            # Fill remaining with failure results
            for remaining_url in profile_urls[len(results) :]:
                results.append(
                    EnrichmentResult(
                        success=False,
                        failure_code="batch_aborted",
                        action_required=_build_action_required(
                            code="batch_aborted",
                            summary="Batch processing stopped due to failure",
                            steps=["Resolve the failed enrichment, then retry batch"],
                        ),
                        safe_to_retry=True,
                        resume_hint=f"Retry from URL: {remaining_url}",
                    )
                )
            break

    return results


if __name__ == "__main__":
    # CLI usage for testing
    if len(sys.argv) < 2:
        print(
            "Usage: python3 profile_enricher.py <profile_url> [--cdp-port PORT]",
            file=sys.stderr,
        )
        sys.exit(1)

    url = sys.argv[1]
    cdp_port = "9234"

    if "--cdp-port" in sys.argv:
        idx = sys.argv.index("--cdp-port")
        if idx + 1 < len(sys.argv):
            cdp_port = sys.argv[idx + 1]

    result = enrich_profile(url, cdp_port)
    print(json.dumps(result.to_dict(), indent=2))
    sys.exit(0 if result.success else 1)
