---
name: agent-review
description: Prepare, perform or integrate a formal independent Review of a bound unit. Not for ordinary implementation, planning, self-checks or repairs.
license: MIT
metadata:
  author: martinliu
  version: "3.1.0"
---

# Independent Review

For a formal Review, the parent and assigned reviewer read the exact bound `agent-review/references/review.md` (eligibility, submission, result and correction). Use it with `agent-review/references/execution.md`, `agent-review/references/coordination.md` and `agent-review/references/advisory.md`; a Review never grants execution or contact permission. Resolve `agent-review/…` from an installed skill root or repository `skills/`, never relative to the current task record. Missing required policy stops dependent work; report it, never guess. Reload lost bindings on resume.

For an older non-Review assignment, read the bound `agent-review/references/execution.md`. Non-Review advisers also need the bound coordination and advisory references; if missing, have the parent reissue the assignment. Do not load the Review protocol for ordinary execution or advice.
