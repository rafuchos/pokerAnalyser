# Failed Approaches & Dead Ends

This file documents approaches that failed, to avoid repeating mistakes.

## Format

Each dead end follows this structure:

```markdown
## DE-XXX: Failed Approach Title
**Date:** YYYY-MM-DD
**Attempted:** What we tried
**Problem:** Why it failed
**Solution:** What worked instead
**Time Spent:** Approximate hours
**Reference:** Related decision or issue
```

---

## Adding New Dead Ends

When an approach fails:

1. Assign next DE number (DE-001, DE-002, etc.)
2. Fill in all sections while fresh in memory
3. Commit with message: `docs: add DE-XXX dead end`
4. Reference in code: `// See DE-XXX - why we don't use X`

---

## Categories

- **Architecture:** Structural decisions that didn't work
- **Performance:** Optimization attempts that backfired
- **Dependencies:** Library choices that caused problems
- **Testing:** Test strategies that were too brittle
- **Integration:** External service integrations that failed
- **Data Modeling:** Schema or object structure issues
- **DevOps:** Deployment/infrastructure approaches

---

## Template for New Dead End

```markdown
## DE-XXX: [Title]
**Date:** YYYY-MM-DD
**Attempted:** (What we tried and why we thought it would work)
**Problem:** (Why it failed - specific errors, limitations, etc.)
**Solution:** (What we did instead - working approach)
**Time Spent:** X hours
**Reference:** (Link to related DEC, issue, or PR)
```

---

## Tips for Recording Dead Ends

- Be honest about what failed
- Include error messages and specific blockers
- Document the solution for future reference
- Note if this is a category-wide dead end or specific case
- Update if you discover new info about why it failed

---

## Archiving

Dead ends are archived to `/context/dead-ends/archive/` after:
- 90 days with no new references
- Superseded by later approaches
- External changes (library update) invalidate the issue

---

## Current Backlog

Document new dead ends as they occur. Keep the most recent 5-10 active.
