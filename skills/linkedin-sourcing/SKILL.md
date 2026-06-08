---
name: linkedin-sourcing
description: LinkedIn Recruiter (paid product) sourcing assistant for macOS. Excel-driven state, phased execution, resumable workflows, fast chained browser automation.
license: MIT
metadata:
  author: martinliu
  version: "1.2.0"
allowed-tools: Bash(npx agent-browser:*), Bash(agent-browser:*), Bash(grep:*), Bash(rg:*), Bash(ls:*), Bash(mkdir:*), Bash(cat:*), Bash(echo:*), Bash(date:*), Bash(timeout:*), Bash(python3:*), Bash(open:*), Bash(chmod:*), Bash(bash:*)
---

# LinkedIn Sourcing

## Golden Rule: Run the Loop

For normal operation, always run:

```bash
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}"
```

The loop decides the next phase from project and workbook state. Do not run individual phase scripts to advance a project.

> If you are trying to make progress, run the loop. If you are running anything else, you are debugging a loop failure.

## Quick Reference

### Bootstrap a new project

```bash
python3 "$SKILL_DIR/scripts/bootstrap_project.py" --jd-url "https://example.com/job"
```

**Agent responsibility during bootstrap:**
- Read the job description (JD) from the provided URL
- Infer `CORE_FUNCTION` (what the team does, e.g., "building scalable ML infrastructure") from the JD
- Infer `BUSINESS_IMPACT` (why it matters, e.g., "powering recommendation systems for billions of users") from the JD
- Pass them as CLI flags:
  ```bash
  python3 "$SKILL_DIR/scripts/bootstrap_project.py" --jd-url "..." --core-function "..." --business-impact "..."
  ```
- Only ask the user for these fields if the JD is ambiguous or you are genuinely uncertain after reading it

### Start or continue work

```bash
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}"
```

### After any stop

1. Read the loop's stop reason.
2. Fix only that blocker.
3. Run the same loop command again.

Do not guess the next phase.

## Stop Handling

| Stop reason | What to do |
|---|---|
| Login/auth required | Log into LinkedIn Recruiter, then rerun the loop |
| Browser/CDP unavailable | Reconnect Chrome (`connect_browser.sh`), then rerun the loop |
| Search creation required | Open Recruiter, create the search using the provided Copilot query, then rerun the loop |
| Confirm search required | User verifies the search is ready, then run with `--confirm-search` |
| Send confirmation required | Review drafted messages in workbook, get explicit user approval, then run with `--confirm-send` |
| Page/dialog blocked | Clear the blocker, then rerun the loop |
| Unclear failure | Stop and inspect `DEBUG.md`; do not manually advance phases |

## Review And Send Rules

- Do not rewrite generated drafts unless explicitly asked.
- Do not send InMails without explicit user confirmation.
- Only use `--confirm-send` after approval.
- If approval is missing or ambiguous, stop and ask.

Approved send command:

```bash
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}" --confirm-send
```

## Debugging

Debug commands are intentionally not listed here. For rare troubleshooting after the loop fails, see `DEBUG.md`.

Debug commands are not a normal workflow. Return to the loop immediately after diagnosis.

## Do Not

- **NEVER** run individual phase scripts to advance a project during normal operation.
- **NEVER** manually decide the next phase.
- **NEVER** use ad-hoc `agent-browser` commands to continue workflow progress.
- **NEVER** skip the loop because a phase name looks obvious.
- **NEVER** edit project state unless explicitly reconciling a known failure.
- **ONLY** run individual phase scripts when debugging a specific loop failure.

**Wrong:**

```bash
python3 "$SKILL_DIR/scripts/run_extraction.py" --project "{PROJECT_ID}"
python3 "$SKILL_DIR/scripts/run_filter.py" --project "{PROJECT_ID}"
python3 "$SKILL_DIR/scripts/run_enrich.py" --project "{PROJECT_ID}"
```

**Right:**

```bash
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}"
```
