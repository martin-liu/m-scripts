# DEBUG ONLY

Do not use this file for normal execution.

Normal execution is always:

```bash
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}"
```

Use these commands only after the loop has failed and you are diagnosing that specific failure.

---

## Environment Setup

When running commands directly in a shell, you must set `SKILL_DIR` and source the runtime profile:

```bash
export SKILL_DIR="$HOME/.agents/skills/linkedin-sourcing"
source "$HOME/.config/linkedin-sourcing/profile.sh"
```

- `SKILL_DIR` must be set to the skill directory path
- `profile.sh` provides `WORK_DIR`, `CDP_PORT`, and `CHROME_PROFILE`
- Do NOT source `config.sh` for bootstrap; bootstrap creates it

## Check Status Without Changing Anything

```bash
python3 "$SKILL_DIR/scripts/status.py" "{PROJECT_ID}" --pretty
```

## Single-Phase Debug Commands

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

## Browser Probes

```bash
# Check CDP availability
curl -s "http://localhost:${CDP_PORT}/json/version"

# Check current URL
agent-browser --cdp "$CDP_PORT" get url

# Check for blocking dialogs
agent-browser --cdp "$CDP_PORT" dialog status

# Accept alert/confirm dialog
agent-browser --cdp "$CDP_PORT" dialog accept

# Dismiss dialog
agent-browser --cdp "$CDP_PORT" dialog dismiss
```

- Prefer `dialog accept` for plain alerts that block automation
- Be careful with confirm/beforeunload dialogs: they may discard search edits or an open InMail composer
- After clearing the dialog, rerun the loop

## State Files

- `workbook.xlsx`: row-level truth
- `project_state.json`: current checkpoint and `action_required`
- `config.sh`: project configuration

Agents should treat these as read-only unless the task explicitly requires changing config.

When checking workbook content, trust the named fields returned by `excel_utils.py`, not spreadsheet column letters.

## Workbook Model

- `status` = where the row is now
- `next_action` = what the loop will do next
- normal flow: `filter -> enrich -> draft -> review -> send -> done`

## Workbook Inspection

```bash
# Read all rows
python3 "$SKILL_DIR/scripts/excel_utils.py" read \
  "$HOME/Desktop/linkedin-sourcing/projects/{PROJECT_ID}_{PROJECT_SLUG}/workbook.xlsx"

# Filter by status
python3 "$SKILL_DIR/scripts/excel_utils.py" read \
  "$HOME/Desktop/linkedin-sourcing/projects/{PROJECT_ID}_{PROJECT_SLUG}/workbook.xlsx" \
  --filter next_action=send
```

## State Reconciliation

```bash
# Check for stale state
python3 "$SKILL_DIR/scripts/reconcile_state.py" "{PROJECT_ID}" --pretty

# Fix stale state
python3 "$SKILL_DIR/scripts/reconcile_state.py" "{PROJECT_ID}" --apply --pretty
```

## When to Use Debug Commands

| Scenario | What to do |
|----------|------------|
| Loop stops with `action_required` | Fix the blocker, then **return to the loop** |
| Loop stops with `failed` | Check logs, use single-phase debug to isolate, fix, then **return to the loop** |
| Need to verify one candidate's enrichment | Use `--row-id` debug, then **return to the loop** |
| Suspect workbook corruption | Use `reconcile_state.py`, then **return to the loop** |
| Browser seems stuck | Check dialog status, clear if needed, then **return to the loop** |

**After any debug command, always return to the loop:**

```bash
python3 "$SKILL_DIR/scripts/run_reachout_loop.py" --project "{PROJECT_ID}"
```
