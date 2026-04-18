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

## Normal Workflow

Use exactly this flow:

1. Bootstrap once.
2. Run the loop.
3. If the loop stops, do the required action.
4. Run the same loop command again.

```bash
# Bootstrap from a JD URL
python3 $SKILL_DIR/scripts/bootstrap_project.py \
  --jd-url "https://example.com/job"

# Main workflow after bootstrap
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}"

# Check current state without changing anything
python3 $SKILL_DIR/scripts/status.py "{PROJECT_ID}" --pretty
```

Do not choose phases manually in normal operation. The loop decides.

## Stop Conditions

- `action_required` with `actor=agent`: do the browser or automation action, then rerun the loop
- `action_required` with `actor=user`: stop and ask the user
- `review`: stop for human review
- `send`: stop unless `--confirm-send` is provided
- `complete`: no more work
- `failed`: fix the issue, then rerun the loop

## Review And Send

Review is a hard stop.

- Review the drafts in `workbook.xlsx`
- Approve them
- Resume with:

```bash
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}" --confirm-send
```

Never send without `--confirm-send`.

## State Files

- `workbook.xlsx`: row-level truth
- `project_state.json`: current checkpoint and `action_required`
- `config.sh`: project configuration

Agents should treat these as read-only unless the task explicitly requires changing config.

## Minimal Debug Surface

Use these only for debugging or live verification of a small slice.

```bash
# Verify one enrich row in the browser
python3 $SKILL_DIR/scripts/run_enrich.py --project "{PROJECT_ID}" --row-id 3

# Draft one row without touching the rest
python3 $SKILL_DIR/scripts/run_draft.py "{PROJECT_ID}" --row-id 3

# Verify send flow for one approved row without sending
python3 $SKILL_DIR/scripts/run_send.py --project "{PROJECT_ID}" --verify-only --row-id 3

# Run exactly one loop iteration
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}" --once
```

## If State Looks Wrong

Use reconcile only for obviously stale checkpoint state.

```bash
python3 $SKILL_DIR/scripts/reconcile_state.py "{PROJECT_ID}" --pretty
python3 $SKILL_DIR/scripts/reconcile_state.py "{PROJECT_ID}" --apply --pretty
```

## Do Not

- Do not orchestrate phases manually in normal flow
- Do not write directly to `workbook.xlsx` or `project_state.json`
- Do not skip review
- Do not send without `--confirm-send`
- Do not invent next steps when `status.py` or the loop already tells you what to do

## Workbook Model

- `status` = where the row is now
- `next_action` = what the loop will do next
- normal flow: `filter -> enrich -> draft -> review -> send -> done`
