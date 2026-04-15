---
name: linkedin-sourcing
description: LinkedIn Recruiter (paid product) sourcing assistant for macOS. Excel-driven state, phased execution (extract → filter → draft → review → send), resumable workflows, fast chained browser automation with auto-recovering scripts.
license: MIT
metadata:
  author: martinliu
  version: "1.0.1"
allowed-tools: Bash(npx agent-browser:*), Bash(agent-browser:*), Bash(grep:*), Bash(rg:*), Bash(ls:*), Bash(mkdir:*), Bash(cat:*), Bash(echo:*), Bash(date:*), Bash(timeout:*), Bash(python3:*), Bash(open:*), Bash(chmod:*), Bash(bash:*)
---

# LinkedIn Sourcing

Automates candidate outreach via **LinkedIn Recruiter** (the paid hiring product at `linkedin.com/talent/hire/`). Requires macOS and Google Chrome.

## Install / Update

```bash
# Install only this skill
npx -y skills add martin-liu/m-scripts --skill linkedin-sourcing

# Install only this skill over SSH
npx -y skills add git@github.com:martin-liu/m-scripts.git --skill linkedin-sourcing

# Update this skill later
npx -y skills update linkedin-sourcing
```

| Mode | Flow | User action |
|------|------|-------------|
| **reachout** | JD → extract → filter → draft → **you review** → send | Review drafts in Excel, say "confirm" |
| **review** | Scan replies + due follow-ups → draft → **you review** → send | Review in Excel, approve |

---

## Goal

Build a stable, fast, resumable LinkedIn Recruiter workflow that collaborates with a human, never loses progress, and improves with each run.

---

## Workflow Overview

This skill separates **project bootstrapping** from **Recruiter execution**:

| Phase | Purpose | Input | Output |
|-------|---------|-------|--------|
| **Bootstrap** | Create project structure from JD | JD URL or raw text | Project directory, config.sh, workbook |
| **Extract** | Pull candidates from LinkedIn Recruiter | LinkedIn Recruiter search/project | Populated workbook with candidates |

`PROJECT_ID` is your local project ID. `RECRUITER_PROJECT_URL` points to the LinkedIn Recruiter search/project used for extraction. The JD is only for bootstrap.

---

## Operating Principles

- Excel is the source of truth
- Draft and send stay separate
- Workflows must be resumable and fail closed
- Browser steps should complete in seconds; hangs are bugs
- After 3 retries, ask the user to fix the blocker and continue

---

## Path Rules

`SKILL_DIR` = this skill directory.

`WORK_DIR` = the user's runtime data directory from `~/.config/linkedin-sourcing/profile.sh`.

**Canonical script locations** (derive from these variables only):
- Before runtime init or for debugging: `$SKILL_DIR/scripts`
- During normal execution: `$WORK_DIR/runtime/current/scripts`

**Forbidden**: Do not use global filesystem searches (find, glob, locate) to locate script files. Always derive paths from `SKILL_DIR` or `WORK_DIR/runtime/current`.

Permission rule: request approval once for top-level `$WORK_DIR`, not each child path.

**OpenCode permission trigger**: Before running runtime init or browser bootstrap on a fresh machine/session, the agent must create `$WORK_DIR` and touch `$WORK_DIR/.permission_probe` to trigger OpenCode approval at the WORK_DIR root. This ensures the agent itself (not just a script subprocess) has explicit permission to access the directory.

### Layout

```
$SKILL_DIR/                      ← this skill (installed or symlinked)
  SKILL.md                       ← workflow logic
  scripts/                       ← canonical scripts
    excel_utils.py               ← Excel CRUD (create/read/update/append/count)
    connect_browser.sh           ← connect to Chrome with automatic auth bootstrap
    send_inmail.sh               ← send one InMail (args: url, subject, body)
    check_blocked.sh             ← detect page interruptions (verification, usage limits)
    extract_candidates.py        ← low-level one-page extractor to JSON
    run_extraction.py            ← canonical multi-page extraction macro
  templates/                     ← message templates with {var} placeholders
    initial_inmail.txt           ← first outreach (line 1 = subject, rest = body)
    reply_*.txt                  ← reply templates by type (body only)
    followup_day*.txt            ← follow-up templates by day (body only)

$WORK_DIR/                       ← runtime data (user's machine)
  runtime/
    releases/{hash}/             ← versioned runtime bundles (scripts + templates + SKILL.md)
    current/                     ← active runtime bundle used for normal execution
    incidents/                   ← structured failure reports
  scripts/                       ← optional emergency overrides only
  projects/
    {PROJECT_ID}_{title_slug}/   ← project directory (new layout)
      config.sh                  ← project config (PROJECT_ID is source of truth)
      job_description.txt        ← saved JD
      workbook.xlsx              ← source of truth per project (new layout)
    {PROJECT_ID}/                ← project directory (legacy layout - still supported)
      config.sh
    {PROJECT_ID}.xlsx            ← workbook at root (legacy layout - still supported)
```

Normal execution uses `$WORK_DIR/runtime/current`. Fall back to `$SKILL_DIR` only before runtime init or for debugging.

---

## Runtime Initialization

Initialize once per session:

```bash
python3 $SKILL_DIR/scripts/init_runtime.py
```

This syncs the runtime bundle, checks dependencies, and makes `$WORK_DIR/runtime/current` the normal execution target.

---

## First-Time Setup

On first invocation, if `~/.config/linkedin-sourcing/profile.sh` does not exist, ask the user:

| Setting | Prompt | Default |
|---------|--------|---------|
| `WORK_DIR` | Work folder for all sourcing data? | `~/Desktop/linkedin-sourcing` |
| `USER_EMAIL` | Your recruiter email (for templates)? | — |
| `USER_NAME` | Your first name (for signatures)? | — |
| `ACCOUNT_NAME` | LinkedIn Recruiter account name? | — |
| `CDP_PORT` | Chrome debug port? | `9230` |
| `CHROME_PROFILE` | Chrome profile path? | `$WORK_DIR/chrome-profile` |

Save to `~/.config/linkedin-sourcing/profile.sh`:

```bash
WORK_DIR="$HOME/Desktop/linkedin-sourcing"
USER_EMAIL="recruiter@company.com"
USER_NAME="Daisy"
ACCOUNT_NAME="company-recruiter"
CDP_PORT="9230"
CHROME_PROFILE="$WORK_DIR/chrome-profile"
```

Then create the work directory and trigger OpenCode permission:

```bash
mkdir -p "$WORK_DIR"
touch "$WORK_DIR/.permission_probe"
mkdir -p "$WORK_DIR/projects"
```

## Project Bootstrap

Create a new sourcing project from a JD URL or raw text. The canonical flow derives `PROJECT_ID` from LinkedIn Recruiter project identity.

### Canonical Flow (Recommended)

Bootstrap automatically creates/ensures the LinkedIn Recruiter project and derives `PROJECT_ID` from it:

```bash
# Auto-create Recruiter project and derive PROJECT_ID (requires Chrome with CDP)
python3 $SKILL_DIR/scripts/bootstrap_project.py \
  --jd-url "https://lifeattiktok.com/search/7623929928426277125" \
  --position-title "SoC Digital Design Engineer" \
  --team-name "Multimedia Lab"
```

**What happens:**
1. Fetches and parses the JD URL
2. Creates/ensures a LinkedIn Recruiter project with the position title
3. Extracts the numeric Recruiter project ID (e.g., `12345` from `/talent/hire/12345/`)
4. Uses that ID as `PROJECT_ID`
5. Creates local project files with `RECRUITER_PROJECT_URL` pre-configured

### With Existing Recruiter URL

If you already have a Recruiter project URL, provide it to derive `PROJECT_ID`:

```bash
# Use existing Recruiter project URL
python3 $SKILL_DIR/scripts/bootstrap_project.py \
  --jd-url "https://example.com/job" \
  --recruiter-url "https://www.linkedin.com/talent/hire/12345/discover/recruiterSearch"
```

**PROJECT_ID will be:** `12345` (extracted from the URL)

### From Raw Text

```bash
# From raw text (with overrides)
python3 $SKILL_DIR/scripts/bootstrap_project.py \
  --jd-text "Senior ML Engineer position..." \
  --position-title "Senior ML Engineer" \
  --team-name "AI Platform"

# From file
python3 $SKILL_DIR/scripts/bootstrap_project.py \
  --jd-text @/path/to/job_description.txt \
  --location "San Jose, CA"
```

### What Bootstrap Creates

New canonical layout (NEW projects):
- Project directory: `$WORK_DIR/projects/{PROJECT_ID}_{title_slug}/` (e.g., `12345_senior-engineer`)
- `config.sh` - project configuration with `RECRUITER_PROJECT_URL` pre-configured
- `job_description.txt` - saved raw JD for reference
- `workbook.xlsx` - empty candidate workbook (inside project directory)

Legacy layout (existing projects - still supported):
- Project directory: `$WORK_DIR/projects/{PROJECT_ID}/`
- `config.sh` - project configuration
- `{PROJECT_ID}.xlsx` - workbook at projects root

The agent scans `config.sh` files to find projects by `PROJECT_ID` - it does NOT trust the folder name.

### Bootstrap Safety Rules

- **Fail closed**: If Recruiter identity cannot be resolved, bootstrap fails before creating local files
- **No local timestamp IDs**: Default flow never generates local timestamp PROJECT_IDs
- **Conflict detection**: If a different local project already uses the same Recruiter ID, bootstrap fails with a clear error
- **Idempotent**: Re-running bootstrap with the same Recruiter URL updates the existing project config

### Ensure Recruiter Project (Standalone)

If you need to create/ensure a Recruiter project separately (e.g., to get the search URL):

```bash
# Ensure project exists (creates if not found, returns URL)
python3 $SKILL_DIR/scripts/ensure_recruiter_project.py \
  --project-name "SoC Digital Design Engineer, Multimedia Lab" \
  --description "Hardware design role for video codec solutions" \
  --cdp-port 9230
```

**Prerequisites:**
- Run `bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh"` first (or the `SKILL_DIR` copy before runtime init)
- That script will reuse existing auth if available, or launch Chrome and bootstrap auth automatically if needed
- You must finish LinkedIn Recruiter login in the Chrome window if bootstrap is required

**Output:** JSON with `status` (existing|created), `url`, `project_id`, and `message`:
```json
{
  "status": "created",
  "project_name": "SoC Digital Design Engineer, Multimedia Lab",
  "project_id": "12345",
  "url": "https://www.linkedin.com/talent/hire/12345/discover/recruiterSearch",
  "message": "Created new project: SoC Digital Design Engineer, Multimedia Lab"
}
```

---

## Browser

Do not ask the user to launch Chrome manually. Use the canonical connect flow first so the skill can reuse either:
- an authenticated CDP browser on `$CDP_PORT`, or
- a saved auth-backed `agent-browser` session

Use `--cdp $CDP_PORT` only when you are intentionally targeting the authenticated CDP browser directly. Saved-auth flows may run in `agent-browser` session mode instead.

Connect via: `bash $WORK_DIR/runtime/current/scripts/connect_browser.sh` (or `$SKILL_DIR/scripts/connect_browser.sh` if runtime not yet initialized)

**Fresh session reminder**: On a fresh machine or new session, ensure `$WORK_DIR` exists and touch `$WORK_DIR/.permission_probe` before running connect_browser.sh to trigger OpenCode approval at the WORK_DIR root.

**Policy: Automatic Auth with Reusable State**

This skill implements an automated authentication flow:
1. **Fast path**: If the configured CDP browser (port 9230) is reachable AND authenticated to LinkedIn Recruiter, use it immediately
2. **Saved auth**: If valid saved auth exists (< 7 days old), start an agent-browser session from it
3. **Auto-bootstrap**: If no auth available, automatically launch Chrome with the configured profile, navigate to LinkedIn Recruiter, prompt you to log in, then export and save auth state for reuse

**Auth Flow**:
1. Check for existing authenticated CDP browser (port 9230)
2. Check for recent saved auth state (`$WORK_DIR/runtime/auth/linkedin-auth.json`)
3. If neither available: automatically launch Chrome with configured profile (`$CHROME_PROFILE`, default `$WORK_DIR/chrome-profile`)
4. Navigate to LinkedIn Recruiter login page
5. You complete SSO/2FA in the Chrome window
6. Script automatically detects successful login (no terminal input required)
7. Auth state automatically exported to `$WORK_DIR/runtime/auth/linkedin-auth.json`
8. Bootstrap Chrome closed automatically
9. New agent-browser session started from saved auth

**Browser Modes**:
- **CDP mode**: Direct connection to existing Chrome (fast path)
- **Agent-browser mode**: Managed session using saved auth state

The current mode is persisted in `$WORK_DIR/runtime/browser_mode.json`.

**Commands**:
```bash
# Check connection status (JSON output) - hermetic, no side effects
bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh" --status

# Check only (no side effects)
bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh" --check-only

# Connect with automatic auth (default) - checks existing auth or bootstraps automatically
bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh"

# Skip auto-bootstrap, fail closed if no auth available (for non-interactive use)
bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh" --no-bootstrap
```

**Rules**:
- Do not use `pkill` or `killall`
- When an account selector appears, select `$ACCOUNT_NAME`
- If session is lost, run connect_browser.sh to re-authenticate
- Auth state expires after 7 days; re-run connect_browser.sh to refresh when needed

---

## Excel

Use `python3 $WORK_DIR/runtime/current/scripts/excel_utils.py <command> <args>`:

| Command | Example |
|---------|---------|
| `create` | `excel_utils.py create $WORK_DIR/projects/123.xlsx` |
| `read` | `excel_utils.py read 123.xlsx --filter next_action=send` |
| `update` | `excel_utils.py update 123.xlsx 5 '{"status":"Sent"}'` |
| `append` | `excel_utils.py append 123.xlsx '{"name":"John"}'` |
| `count` | `excel_utils.py count 123.xlsx --filter status=Sent` |

**Columns**: `row_id`, `name`, `company`, `title`, `profile_url`, `est_yoe`, `highest_degree`, `school`, `status`, `next_action`, `draft_subject`, `draft_body`, `date_sent`, `attempts`, `last_contact`, `reply_type`, `reply_summary`, `notes`, `headline`, `location`

**Schema compatibility**: Old workbooks with 18 columns are automatically migrated when loaded. Missing `headline`/`location` columns are added without data loss. Personalization falls back to `notes` when `headline` is empty.

**Status flow**: `Extracted` → `Filtered` / `Drafted` → `Approved` → `Sent` / `AlreadyContacted` → `Replied` / `Cooldown`

**Follow-up schedule**: computed from `date_sent` + `attempts` (Day 3, 5, 7, 10, 14).

---

## Send Macro

`run_send.py` is the canonical send workflow.

```bash
# Send all rows with next_action=send
python3 $WORK_DIR/runtime/current/scripts/run_send.py --project "{PROJECT_ID}"

# Verify-only mode (dry run)
python3 $WORK_DIR/runtime/current/scripts/run_send.py --project "{PROJECT_ID}" --verify-only

# Verify specific rows
python3 $WORK_DIR/runtime/current/scripts/run_send.py --project "{PROJECT_ID}" --verify-only --row-id 5,6,7
```

**Safety requirements**:
- `send_inmail.sh` must output valid JSON with explicit `clean_state` field
- Non-JSON output or missing `clean_state` is treated as failure (browser state assumed unclean)
- Legacy plain-text output (`SENT`, `VERIFIED`, etc.) is not accepted

**Exit codes**:
| Code | Meaning |
|------|---------|
| 0 | Success - all sends completed (or verify-only passed) |
| 1 | Send failure - one or more rows failed |
| 2 | Browser state not clean - operator intervention required |
| 3 | Configuration error - check setup |

---

## Project Config (`$WORK_DIR/projects/{PROJECT_ID}/config.sh`)

```bash
PROJECT_ID="1683119140"
POSITION_TITLE="Large Model Training Acceleration Engineer"
TEAM_NAME="Intelligent Creation - AI Platform"
LOCATION="San Jose, California, United States"
CORE_FUNCTION="AI model training infrastructure"
BUSINESS_IMPACT="accelerating large model training for global users"

KEYWORDS="Large Model Training, Distributed Training, PyTorch, CUDA"
COMPANIES="Google, Meta, OpenAI, Anthropic, DeepMind, Microsoft, NVIDIA"
EXCLUDE_TITLES="Manager,Director,VP,Product Manager,Data Scientist,QA Engineer"

DAILY_LIMIT=200
CANDIDATE_DELAY_SEC=10

# Required for extraction: LinkedIn Recruiter project/search URL
# Use ensure_recruiter_project.py to get this URL, or create manually
RECRUITER_PROJECT_URL="https://www.linkedin.com/talent/hire/12345/discover/recruiterSearch"
```

`RECRUITER_PROJECT_URL` is required for extraction.

---

## Human Assist Protocol

When automation fails after 3 retries on any step:

1. Verify CDP first via `bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh"` (or `bash "$SKILL_DIR/scripts/connect_browser.sh"` before runtime init), then take a snapshot: `agent-browser --cdp $CDP_PORT snapshot`
2. Describe the problem clearly to the user
3. Ask: "Please [do X] in the Chrome window, then say **continue**"
4. Wait for user
5. Take fresh snapshot, verify resolved
6. If the fix reveals a new selector or flow → patch the canonical script in `SKILL_DIR`, add/update tests, then rerun `init_runtime.py` to sync a new runtime bundle
7. Resume from the exact row/step

Common interruptions: verification prompt, account selector, session timeout, unexpected modal, usage limit page.

Always process every candidate — do not silently skip rows or abandon the session.

---

## Mode: reachout

**Trigger**: User gives a JD, project link, or says "reach out" / "send InMails".

**Prerequisites**: Project must be bootstrapped (see Project Bootstrap section) and `RECRUITER_PROJECT_URL` must be set in `config.sh`.

### Phase 1: Extract (browser)

Use `run_extraction.py` as the normal extraction workflow.

1. Verify `RECRUITER_PROJECT_URL` is set
2. Connect browser via `bash "$WORK_DIR/runtime/current/scripts/connect_browser.sh"` (or `bash "$SKILL_DIR/scripts/connect_browser.sh"` before runtime init)
3. Run the canonical extractor:

```bash
# Full extraction (default: continue until no more pages/results)
python3 $WORK_DIR/runtime/current/scripts/run_extraction.py \
  --project "{PROJECT_ID}" \
  --cdp-port $CDP_PORT

# Pagination smoke test: require page 1 -> page 2 behavior
python3 $WORK_DIR/runtime/current/scripts/run_extraction.py \
  --project "{PROJECT_ID}" \
  --max-pages 2 \
  --cdp-port $CDP_PORT

# Resume a prior interrupted or partial run
python3 $WORK_DIR/runtime/current/scripts/run_extraction.py \
  --project "{PROJECT_ID}" \
  --resume \
  --cdp-port $CDP_PORT
```

Rules:
- Never infer completion from page 1 alone
- If page 2 / page 3 / next-page controls exist, extraction is **not** done
- For validation, require at least one successful page transition when more results exist
- Only stop when `run_extraction.py` reports true completion, `check_blocked.sh` returns INTERRUPTED, or `stop.flag` exists

Use `extract_candidates.py` only for low-level selector debugging.

### Phase 2: Filter (no browser)

For each row where `next_action=filter`:
- Match title against `EXCLUDE_TITLES`
- Excluded → `status=Filtered`, `next_action=done`
- Kept → `next_action=draft`

Print summary: N kept / M filtered.

### Phase 3: Draft (no browser)

For each row where `next_action=draft`:
- Load `$WORK_DIR/runtime/current/templates/initial_inmail.txt` — line 1 is the subject (`Subject: ...`), remaining lines are the body
- Fill `{var}` placeholders with candidate data + project config
- Personalize `{1 personalized sentence}` based on candidate's title/company/skills
- Write `draft_subject` and `draft_body` via `excel_utils.py update`
- Set `status=Drafted`, `next_action=review`

### Phase 4: Review (no browser)

Print summary, open Excel. User edits drafts if needed, says "confirm".

On confirm: all `Drafted` rows → `status=Approved`, `next_action=send`.

### Phase 5: Send (browser)

For each row where `next_action=send`, run the canonical Send Macro above.

**Manual per-row debugging only** (not recommended for batch operations):
```bash
bash "$WORK_DIR/runtime/current/scripts/send_inmail.sh" --json "{profile_url}" "{draft_subject}" "{draft_body}"
```

Without `--json`, `send_inmail.sh` prints a legacy plain-text status line and should not be used for fail-closed automation.

**Stop conditions**:
1. No more `next_action=send` rows
2. Browser state not clean (exit code 2) → operator intervention required

---

## Mode: review

**Trigger**: User says "review", "check replies", or "check follow-ups".

### Phase 1: Scan

**Inbox** (browser): navigate to inbox, read new messages, match to Excel rows, update `reply_type` + `reply_summary`.

**Follow-ups** (no browser): find rows where next follow-up is due (from `date_sent` + `attempts`), skip if replied or `attempts >= 6`. Set `next_action=followup`.

### Phase 2: Draft (no browser)

- For replies: load matching `$WORK_DIR/runtime/current/templates/reply_*.txt`, fill placeholders
- For follow-ups: load `$WORK_DIR/runtime/current/templates/followup_day{N}.txt` based on attempt number
- Write to `draft_subject`/`draft_body`, set `next_action=review`

### Phase 3: Review (no browser)

Print summary with draft previews. User approves in Excel, says "confirm".

On confirm: approved → `next_action=send`, skipped → `next_action=done`.

### Phase 4: Send (browser)

Same send loop as reachout Phase 5.

After attempt 6 with no reply: set `status=Cooldown`, `next_action=cooldown`.

---

## Template Format

All templates use `{var}` placeholders filled at runtime.

**`initial_inmail.txt`**: Line 1 is `Subject: ...`, blank line, then body. All other templates are body-only (replies use the existing thread subject).

| File | Used when | Key placeholders |
|------|-----------|-----------------|
| `initial_inmail.txt` | First outreach | `{FirstName}`, `{current_title}`, `{Company}`, `{POSITION_TITLE}`, `{TEAM_NAME}`, `{LOCATION}`, `{CORE_FUNCTION}`, `{BUSINESS_IMPACT}`, `{relevant_skills}`, `{USER_EMAIL}` |
| `reply_interested.txt` | Candidate says yes | `{FirstName}`, `{POSITION_TITLE}`, `{TEAM_NAME}` |
| `reply_not_interested.txt` | Candidate declines | `{FirstName}`, `{Company}` |
| `reply_questions.txt` | Candidate has questions | `{FirstName}` + agent fills answer |
| `reply_referral.txt` | Candidate refers someone | `{FirstName}` |
| `reply_not_now.txt` | Candidate says later | `{FirstName}`, `{timeframe}` |
| `followup_day3.txt` | Attempt 2 (day 3) | `{FirstName}`, `{POSITION_TITLE}`, `{TEAM_NAME}`, `{LOCATION}`, `{CORE_FUNCTION}`, `{relevant_skills}` |
| `followup_day5.txt` | Attempt 3 (day 5) | `{FirstName}`, `{POSITION_TITLE}`, `{TEAM_NAME}`, `{specific_skill}` |
| `followup_day7.txt` | Attempt 4 (day 7) | `{FirstName}`, `{POSITION_TITLE}`, `{TEAM_NAME}`, `{LOCATION}` |
| `followup_day10.txt` | Attempt 5 (day 10) | `{FirstName}`, `{POSITION_TITLE}`, `{Company}` |
| `followup_day14.txt` | Attempt 6 (day 14) | `{FirstName}`, `{Company}` |

Rules: English, personalized, NO signature on initial outreach. Reply templates may include `{USER_NAME}` signature.
