# Readiness for a named decision

Act on the decision requested: PR, merge, release or rollout are different targets. Assess the integrated candidate against the criteria due for that decision. Use applicable existing evidence. The parent assigns missing checks to an execution owner; the reviewer assesses the resulting evidence without executing checks. A later rollout gate is not a merge requirement.

Inspect the actual change: what data can leave its intended audience, what shared state or permissions can change, and what evidence covers those effects? Check only applicable boundaries and binding requirements. For example, a proposed PR may need a diff checked for exposed credentials; it does not require proving production isolation to validate an unrelated local edit. A required real-source check needs an observed result from that source, not a fixture.

Report what passed, failed or is unverified. A failed required check means not ready; missing proof means readiness is not demonstrated. Assessing does not authorize fixing, publishing, deploying or changing production. For a requested operation use the existing grant for its actual effect and destination; a staging grant does not cover a production write.
