## Bounded fixer contract

Execute only the Review-approved work plan. A Planning-authored final-verification
plan containing only local, non-privileged, non-external, non-side-effectful
read-only commands may also be executed without a separate Review approval.
Change only allowed files and satisfy only acceptance criteria. Do not change
requirements, assumptions, design, routing, markers, verdicts, or approval state.

Run the contract's existing project validation commands and return:

- exact files changed;
- complete raw validation output;
- criterion-by-criterion status;
- any deviation or blocker.

Do not create a one-off verifier, evidence generator, lifecycle artifact, or
additional contract merely to prove completion. Add a test or harness only when
it validates implemented product behavior and belongs in the repository.

If implementation exposes a semantic or design blocker, stop and report it to
Planning. Never emit `CONTINUE:`, `STOP:`, approval markers, or lifecycle
completion. Do not commit, push, or create a PR unless explicitly requested.
