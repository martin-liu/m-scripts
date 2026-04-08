## Cost-aware balanced orchestration

Bias toward the lowest-cost path that preserves quality and speed.

- Prefer smaller specialist subagents when the task cleanly fits their lane and delegation overhead is lower than doing it yourself
- Default to @explorer for broad discovery, @librarian for library/API docs, and @fixer for bounded implementation or test work
- Keep work in the orchestrator when the task is tiny, tightly coupled, sequential, or needs integrated judgment across multiple steps
- Reserve @oracle for genuinely high-stakes decisions and @council for cases where extra consensus is worth the latency and cost
- Do not delegate just to delegate; use specialists only when they improve the quality/speed/cost/reliability balance overall
