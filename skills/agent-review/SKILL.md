---
name: agent-review
description: Prepare, perform or integrate a formal independent Review of a bound unit. Not for ordinary implementation, planning, self-checks or repairs.
license: MIT
metadata:
  author: martinliu
  version: "3.1.0"
---

# Independent Review

For a formal Review, the parent and assigned reviewer read the exact bound `agent-review/references/review.md` for eligibility, submission, findings and correction. Use the assignment's bound `agents/references/execution.md`, `agents/references/coordination.md` and `agents/references/advisory.md`; a Review never grants permission to execute or contact the user.

Resolve this skill from the managed skill root or the designated repository's `skills/`; resolve `agents/` under the managed Pi config (normally `~/.pi/agent/`) or that repository's `shell/config/pi/`. Never resolve from a task record. If a required binding is missing or stale, report it and pause the dependent Review until restored, including on resume.
