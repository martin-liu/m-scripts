---
name: linkedin-sourcing
description: LinkedIn Recruiter (paid product) sourcing assistant for macOS. Excel-driven state, phased execution, resumable workflows, fast chained browser automation.
license: MIT
metadata:
  author: martinliu
  version: "1.1.0"
allowed-tools: Bash(npx agent-browser:*), Bash(agent-browser:*), Bash(grep:*), Bash(rg:*), Bash(ls:*), Bash(mkdir:*), Bash(cat:*), Bash(echo:*), Bash(date:*), Bash(timeout:*), Bash(python3:*), Bash(open:*), Bash(chmod:*), Bash(bash:*)
---

# LinkedIn Sourcing

Automates candidate outreach via **LinkedIn Recruiter** (the paid hiring product at `linkedin.com/talent/hire/`). Requires macOS and Google Chrome.

## Install / Update

```bash
npx -y skills add martin-liu/m-scripts --skill linkedin-sourcing
npx -y skills update linkedin-sourcing
```

## Quick Start

```bash
# 1. Bootstrap a new project from JD
python3 $SKILL_DIR/scripts/bootstrap_project.py \
  --jd-url "https://example.com/job" \
  --position-title "Senior Engineer"

# 2. Run the reachout loop (stops cleanly at boundaries)
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}"

# 3. To include sending (requires explicit confirmation)
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}" --confirm-send
```

## Loop Rule

The loop is the primary workflow driver:

```
while True:
    status = get_status(project)
    if should_stop(status): break
    run_phase(project, status.next_phase)
```

**Stop conditions** (clean stops):
- `action_required` present (browser/manual blocker)
- Review phase reached (human boundary)
- Send phase reached (unless `--confirm-send`)
- Workflow complete (no more work)
- Phase failed

## Three Sources of Truth

| Source | Purpose |
|--------|---------|
| `workbook.xlsx` | Row-level truth (candidates, next_action, status) |
| `project_state.json` | Workflow checkpoint (current_phase, action_required) |
| `config.sh` | Project configuration |

## Phase Boundaries

| Phase | Type | Stop Behavior |
|-------|------|---------------|
| create_search | Browser | Stop if search not configured |
| extract | Browser | Stop on browser/manual blocker |
| filter | Automated | Continue automatically |
| enrich | Browser | Stop on browser/manual blocker |
| draft | Automated | Continue automatically |
| review | Human | **Always stop** - human review required |
| send | Browser | Stop unless `--confirm-send` |

## Key Commands

```bash
# Status check
python3 $SKILL_DIR/scripts/status.py "{PROJECT_ID}" --pretty

# Run single phase
python3 $SKILL_DIR/scripts/run_phase.py "{PROJECT_ID}" filter

# Run loop (recommended)
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}"

# With send confirmation
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}" --confirm-send

# Dry run (preview only)
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}" --dry-run

# Single iteration
python3 $SKILL_DIR/scripts/run_reachout_loop.py --project "{PROJECT_ID}" --once
```

## Bootstrap & Setup

**First-time setup** (creates `~/.config/linkedin-sourcing/profile.sh`):

```bash
python3 $SKILL_DIR/scripts/init_runtime.py
```

**Create new project**:

```bash
python3 $SKILL_DIR/scripts/bootstrap_project.py \
  --jd-url "https://lifeattiktok.com/search/..." \
  --position-title "SoC Digital Design Engineer" \
  --team-name "Multimedia Lab"
```

This creates:
- `$WORK_DIR/projects/{PROJECT_ID}_{slug}/config.sh`
- `$WORK_DIR/projects/{PROJECT_ID}_{slug}/workbook.xlsx`
- `$WORK_DIR/projects/{PROJECT_ID}_{slug}/job_description.txt`

## Browser Connection

```bash
# Connect to Chrome (auto-bootstrap auth if needed)
bash "$SKILL_DIR/scripts/connect_browser.sh"

# Check status
bash "$SKILL_DIR/scripts/connect_browser.sh" --status
```

## Excel Schema

Key columns: `row_id`, `name`, `company`, `title`, `profile_url`, `status`, `next_action`, `draft_subject`, `draft_body`, `enrichment_notes`

**Status flow**: `Extracted` → `Filtered` / `Enriched` / `Drafted` → `Approved` → `Sent`

**Next action flow**: `filter` → `enrich` → `draft` → `review` → `send` → `done`

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success / clean stop |
| 1 | Phase failure |
| 2 | Browser/manual intervention required |
| 3 | Configuration error |

## Path Rules

- `SKILL_DIR` = this skill directory
- `WORK_DIR` = runtime data from `~/.config/linkedin-sourcing/profile.sh`
- Scripts: `$SKILL_DIR/scripts/`
- Templates: `$SKILL_DIR/templates/`

**Permission trigger**: On fresh sessions, create `$WORK_DIR/.permission_probe` before browser operations.

## Legacy: Direct Phase Commands

Individual phase runners (used by loop internally):

```bash
python3 $SKILL_DIR/scripts/run_create_search.py --project "{PROJECT_ID}"
python3 $SKILL_DIR/scripts/run_extraction.py --config "$WORK_DIR/projects/{PROJECT_ID}/config.sh"
python3 $SKILL_DIR/scripts/run_filter.py "{PROJECT_ID}"
python3 $SKILL_DIR/scripts/run_enrich.py --project "{PROJECT_ID}"
python3 $SKILL_DIR/scripts/run_draft.py "{PROJECT_ID}"
python3 $SKILL_DIR/scripts/run_send.py --project "{PROJECT_ID}"
```
