#!/usr/bin/env python3
"""Idempotent runtime initialization CLI for linkedin-sourcing skill.

This script provides a canonical init/preflight that other workflows can rely on.
It ensures the runtime environment is set up correctly and outputs structured JSON
with paths, release info, and sync status.

Usage:
    python3 init_runtime.py [--work-dir DIR] [--force-sync] [--json]

Options:
    --work-dir DIR    Override WORK_DIR (default: from profile.sh or ~/Desktop/linkedin-sourcing)
    --force-sync      Force a resync even if bundle hash hasn't changed
    --json            Output structured JSON (default: human-readable + JSON)
    --quiet           Only output JSON, no human-readable summary

Exit Codes:
    0 - Success (runtime initialized and ready)
    1 - Initialization failed (see stderr for details)

Output (JSON):
    {
        "success": true,
        "work_dir": "/path/to/work_dir",
        "current_release": {
            "hash": "abc123...",
            "path": "/path/to/release",
            "scripts_dir": "/path/to/release/scripts",
            "templates_dir": "/path/to/release/templates",
            "skill_md": "/path/to/release/SKILL.md"
        },
        "sync_happened": false,
        "permission_probe_created": false,
        "dependencies": {
            "checked_at": "2026-04-10T...",
            "agent_browser": {"available": true, "version": "..."},
            "openpyxl": {"available": true, "version": "..."}
        }
    }

Examples:
    # Standard initialization
    python3 init_runtime.py

    # Force resync
    python3 init_runtime.py --force-sync

    # JSON only (for programmatic use)
    python3 init_runtime.py --quiet

    # Custom work directory
    python3 init_runtime.py --work-dir ~/custom/workdir
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from runtime_manager import RuntimeManager


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Initialize linkedin-sourcing runtime environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment:
    LINKEDIN_SOURCING_PROFILE    Path to profile.sh (default: ~/.config/linkedin-sourcing/profile.sh)

Notes:
    - This script is idempotent; running multiple times is safe
    - Permission probe is only created on first run
    - Sync only happens when bundle hash changes or --force-sync is used
    - Use --quiet for JSON-only output suitable for piping
        """,
    )

    parser.add_argument(
        "--work-dir",
        metavar="DIR",
        help="Override WORK_DIR (default: from profile.sh or ~/Desktop/linkedin-sourcing)",
    )

    parser.add_argument(
        "--force-sync",
        action="store_true",
        help="Force a resync even if bundle hash hasn't changed",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help=argparse.SUPPRESS,  # JSON is always output; kept for backward compatibility
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Output JSON only, suppress human-readable summary",
    )

    return parser.parse_args()


def format_human_summary(ctx: dict) -> str:
    """Format a human-readable summary of the runtime context."""
    lines = [
        "=" * 60,
        "LINKEDIN-SOURCING RUNTIME INITIALIZED",
        "=" * 60,
        "",
        f"Work Directory:     {ctx['work_dir']}",
        f"Runtime Directory:  {ctx['runtime_dir']}",
        "",
        "Current Release:",
        f"  Hash:      {ctx['current_release']['hash']}",
        f"  Path:      {ctx['current_release']['path']}",
        f"  Scripts:   {ctx['current_release']['scripts_dir']}",
        f"  Templates: {ctx['current_release']['templates_dir']}",
        "",
    ]

    if ctx.get("sync_happened"):
        lines.append("Status: SYNC PERFORMED (bundle updated)")
    else:
        lines.append("Status: UP TO DATE (no sync needed)")

    if ctx.get("permission_probe_created"):
        lines.append("Permission Probe: CREATED (first run)")
    else:
        lines.append("Permission Probe: EXISTS")

    lines.extend(
        [
            "",
            "Dependencies:",
        ]
    )

    deps = ctx.get("dependencies", {})

    # Agent browser
    agent_browser = deps.get("agent_browser", {})
    if agent_browser.get("available"):
        lines.append(f"  agent-browser: OK ({agent_browser.get('version', 'unknown')})")
    else:
        lines.append(
            f"  agent-browser: MISSING ({agent_browser.get('error', 'unknown error')})"
        )

    # openpyxl
    openpyxl = deps.get("openpyxl", {})
    if openpyxl.get("available"):
        lines.append(f"  openpyxl:      OK ({openpyxl.get('version', 'unknown')})")
    else:
        lines.append(
            f"  openpyxl:      MISSING ({openpyxl.get('error', 'unknown error')})"
        )

    lines.extend(
        [
            "",
            "State Files:",
            f"  Runtime:    {ctx['runtime_state_path']}",
            f"  Dependency: {ctx['dependency_state_path']}",
            "",
            "=" * 60,
        ]
    )

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    args = parse_args()

    try:
        # Initialize runtime manager
        manager = RuntimeManager(work_dir=args.work_dir)

        # Run initialization
        ctx = manager.initialize(force_sync=args.force_sync)

        # Build output
        output = {
            "success": True,
            "work_dir": ctx["work_dir"],
            "runtime_dir": ctx["runtime_dir"],
            "current_release": ctx["current_release"],
            "current_link": ctx["current_link"],
            "incidents_dir": ctx["incidents_dir"],
            "runtime_state_path": ctx["runtime_state_path"],
            "dependency_state_path": ctx["dependency_state_path"],
            "sync_happened": ctx["sync_happened"],
            "permission_probe_created": ctx["permission_probe_created"],
            "dependencies": ctx["dependencies"],
        }

        # Output
        if not args.quiet:
            print(format_human_summary(ctx), file=sys.stderr)

        print(json.dumps(output, indent=2))
        return 0

    except Exception as e:
        error_output = {
            "success": False,
            "error": str(e),
        }

        if not args.quiet:
            print(f"Error: {e}", file=sys.stderr)

        print(json.dumps(error_output))
        return 1


if __name__ == "__main__":
    sys.exit(main())
