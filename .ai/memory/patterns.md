# Codebase Patterns

This file documents recurring patterns discovered during development.

## Format

Each pattern follows this structure:

```markdown
## Pattern Category

### Pattern Name
**Context:** When this pattern applies
**Pattern:** Code example or description
**Rationale:** Why this is the better approach
**Example Location:** Where to find real examples
```

---

## Add New Patterns

When you discover a useful pattern:

1. Identify the category (Frontend, Backend, Testing, etc.)
2. Fill in all sections
3. Add code example if possible
4. Commit with message: `docs: add pattern - [name]`
5. Update `patterns/index.md` if this should be auto-applied

---

## Pattern Categories

- **Frontend:** React, TypeScript, styling, component patterns
- **Backend:** API design, database queries, middleware
- **Testing:** Unit tests, integration tests, fixtures
- **Performance:** Caching, memoization, optimization
- **Security:** Input validation, authentication, authorization
- **Error Handling:** Exception patterns, recovery strategies
- **Data Structures:** Modeling domain objects effectively

---

## Template for New Pattern

```markdown
## [Category]

### [Pattern Name]
**Context:** (When to use this pattern)
**Pattern:** (Description or code example)
**Rationale:** (Why this is better)
**Example Location:** (Where in codebase)
```

---

## Notes

- Patterns should be language-agnostic when possible
- Prioritize patterns that prevent common bugs
- Link related patterns together
- Update this file as team learns new approaches
- Archive rarely-used patterns after 3 months of no references
