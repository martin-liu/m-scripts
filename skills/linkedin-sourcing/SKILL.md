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

Automates LinkedIn Recruiter sourcing with a loop-first workflow. Live-proven path: `bootstrap -> loop -> review boundary -> send boundary`.

## Environment Setup

When running commands directly in a shell, you must set `SKILL_DIR` and source the runtime profile:

```bash
export SKILL_DIR="$HOME/.agents/skills/linkedin-sourcing"
source "$HOME/.config/linkedin-sourcing/profile.sh"
```

- `SKILL_DIR` must be set to the skill directory path
- `profile.sh` provides `WORK_DIR`, `CDP_PORT`, and `CHROME_PROFILE`
- Do NOT source `config.sh` for bootstrap; bootstrap creates it

## Normal Workflow

Use exactly this flow:

1. Bootstrap once.
2. Run the loop.
3. If the loop stops, do the required action.
4. Run the same loop command again.

```bash
# Bootstrap from a JD URL
python3 "$SKILL_DIR/scripts/bootstrap_project.py" \
  --jd-url "https://example.com/job"

# Main workflow after bootstrap
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}"

# Check current state without changing anything
python3 "$SKILL_DIR/scripts/status.py" "{PROJECT_ID}" --pretty
```

Do not choose phases manually in normal operation. The loop decides.

## Stop Conditions

- `action_required` with `actor=agent`: do the browser or automation action, then rerun the loop
- `action_required` with `actor=user`: stop and ask the user
- `review`: stop for human review
- `send`: stop unless `--confirm-send` is provided
- `complete`: no more work
- `failed`: fix the issue, then rerun the loop

## Dialog Unblock

If a browser command appears hung or times out with no progress for about 30 seconds, check for a blocking JavaScript dialog before doing anything else.

Use `agent-browser` directly:

```bash
# Check whether a dialog is blocking browser automation
agent-browser --cdp "$CDP_PORT" dialog status

# Accept alert/confirm dialog
agent-browser --cdp "$CDP_PORT" dialog accept

# Dismiss dialog
agent-browser --cdp "$CDP_PORT" dialog dismiss
```

- Prefer `dialog accept` for plain alerts that block automation
- Be careful with confirm/beforeunload dialogs: they may discard search edits or an open InMail composer
- After clearing the dialog, rerun the same loop command or the same single-phase debug command
- If a command response mentions a dialog warning, treat that as the first thing to resolve

## Review And Send

Review is a hard stop.

- Review the drafts in `workbook.xlsx`
- Send phase uses existing workbook `draft_subject` and `draft_body` as-is; it does not regenerate content (draft generation happens in the draft phase)
- When automation falls back to agent action for sending, you MUST read `draft_subject` and `draft_body` from the workbook row and use them exactly as-is
- NEVER rewrite, modify, or regenerate InMail content during the send phase; the workbook draft is the source of truth
- Read the workbook with `excel_utils.py`; do not try to open `.xlsx` as plain text
- Treat the workbook schema as immutable; never add, remove, reorder, or rename columns
- Do not write workbook cells directly from ad hoc scripts; use the phase scripts and `excel_utils.py`
- Approval is represented by `status` and `next_action`, not by editing that column
- Approve them by keeping the review boundary intact, then resume the loop with `--confirm-send`
- Resume with:

```bash
# Inspect all workbook rows as structured JSON
python3 "$SKILL_DIR/scripts/excel_utils.py" read \
  "$HOME/Desktop/linkedin-sourcing/projects/{PROJECT_ID}_{PROJECT_SLUG}/workbook.xlsx"

# Inspect only rows waiting at the send boundary
python3 "$SKILL_DIR/scripts/excel_utils.py" read \
  "$HOME/Desktop/linkedin-sourcing/projects/{PROJECT_ID}_{PROJECT_SLUG}/workbook.xlsx" \
  --filter next_action=send
```

Then resume with:

```bash
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}" --confirm-send
```

Never send without `--confirm-send`.

## State Files

- `workbook.xlsx`: row-level truth
- `project_state.json`: current checkpoint and `action_required`
- `config.sh`: project configuration

Inspect the workbook through the helper script:

```bash
python3 "$SKILL_DIR/scripts/excel_utils.py" read \
  "$HOME/Desktop/linkedin-sourcing/projects/{PROJECT_ID}_{PROJECT_SLUG}/workbook.xlsx"
```

Agents should treat these as read-only unless the task explicitly requires changing config.

When checking workbook content, trust the named fields returned by `excel_utils.py`, not spreadsheet column letters.

## Minimal Debug Surface

Use these only for debugging or live verification of a small slice.

```bash
# Verify one enrich row in the browser
python3 "$SKILL_DIR/scripts/run_enrich.py" --project "{PROJECT_ID}" --row-id 3

# Draft one row without touching the rest
python3 "$SKILL_DIR/scripts/run_draft.py" "{PROJECT_ID}" --row-id 3

# Run exactly one loop iteration
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}" --once
```

There is no verify-only send mode. Use the normal send boundary with `--confirm-send` instead.

## If State Looks Wrong

Use reconcile only for obviously stale checkpoint state.

```bash
python3 "$SKILL_DIR/scripts/reconcile_state.py" "{PROJECT_ID}" --pretty
python3 "$SKILL_DIR/scripts/reconcile_state.py" "{PROJECT_ID}" --apply --pretty
```

## Do Not

- Do not orchestrate phases manually in normal flow
- Do not write directly to `workbook.xlsx` or `project_state.json`
- Do not add or reorder workbook columns, even for debugging
- Do not use generic spreadsheet tooling that rewrites columns by position
- Do not skip review
- Do not send without `--confirm-send`
- Do not invent next steps when `status.py` or the loop already tells you what to do

## Workbook Model

- `status` = where the row is now
- `next_action` = what the loop will do next
- normal flow: `filter -> enrich -> draft -> review -> send -> done`
