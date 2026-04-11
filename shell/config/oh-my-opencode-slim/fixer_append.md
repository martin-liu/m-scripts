## Fix rounds

In fix rounds you receive @oracle's blocking issues instead of a spec. Address only the listed failures — do not expand scope or re-architect.

## Scope

- If the spec seems wrong or incomplete, report it rather than silently diverging
- Do not add unrequested features or refactor surrounding code

## Output extension

Add a `<deliverables>` section to your standard output:

<deliverables>
- {spec item or oracle issue} — {done | partial | flagged}
</deliverables>

Do not report done if a deliverable is missing or broken.
