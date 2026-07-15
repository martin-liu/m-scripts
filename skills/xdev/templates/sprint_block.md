### Sprint N: {Title}

#### Contract
- **Scope:** (reference `## Design` subsections — or design.md if extracted)
- **Success criteria:** (hard thresholds — each independently verifiable)
  - [ ] `<test command>` exits 0
  - [ ] `<file or output>` exists / matches expected
  - [ ] Live verification: `<command from AGENTS.md>` passes  ← include if sprint is user-facing; omit or replace with `Live verification: waived — <reason>` in Out-of-scope if not applicable
- **Out-of-scope:** (what NOT to touch; list pre-existing failing tests to exclude)
- **Validation command:** `<scoped command that proves all criteria>`

#### Contract Review Verdict

```
Contract verdict: PASS | FAIL
Rounds: 0/2
Issues (if FAIL):
- [criterion text] — too vague because: [reason] — rewrite as: [concrete alternative]
```

#### Completion Report

<!-- Fixer fills this section at step 3c after implementation is complete.
     Replace this comment with the report body. Do not add or remove the heading above. Format:
     - **Files changed:** (list — at least one entry required; use `git diff --name-only` to populate)
     - **Validation output:** (paste or summary — required)
     - **Criteria status:** (mirror each contract criterion)
       - [x] criterion — passed
       - [ ] criterion — pre-existing failure: [test name] (excluded per contract Out-of-scope)
     - **Notes:** (deviations from contract, if any)
     Submitted = Files changed non-empty + Validation output non-empty + all criteria [x] passed
     (only exception: pre-existing failures named in contract Out-of-scope may appear as [ ]).
     An empty or placeholder body is NOT submitted and routes back to 3c on cold resume. -->

#### Evaluation Verdict

```
Sprint verdict: PASS | FAIL
Rounds: 0/2
Issues (if FAIL — must contain at least one critical or major):
- [criterion or file] — severity: critical|major|minor — [specific actionable description]
Minor-only findings (list here, set verdict to PASS):
```
