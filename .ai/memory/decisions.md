# Architectural Decisions

This file tracks major architectural decisions made for this project.

## Format

Each decision follows this structure:

```markdown
## DEC-XXX: Decision Title
**Date:** YYYY-MM-DD
**Status:** Active | Superseded | Deprecated
**Context:** Why this decision was needed
**Decision:** What was decided
**Rationale:** Why this is the best choice
**Impact:** What this affects
**Alternatives Considered:** Other options we evaluated
```

---

## DEC-001: Example Decision
**Date:** 2026-01-21
**Status:** Active
**Context:** (Describe the situation that required this decision)
**Decision:** (State what was decided)
**Rationale:** (Explain why this is the right choice)
**Impact:** (List what this affects - files, patterns, dependencies)
**Alternatives Considered:**
- Option A: (why rejected)
- Option B: (why rejected)

---

## Adding New Decisions

When making significant architectural choices:
1. Assign next DEC number (DEC-002, DEC-003, etc.)
2. Fill in all sections
3. Commit with message: `docs: add DEC-XXX decision`
4. Reference in code comments: `// See DEC-XXX`

## Decision Categories

- **Technology Choices:** Frameworks, libraries, tools
- **Architecture Patterns:** How systems interact
- **Data Models:** Database schemas, API contracts
- **Security:** Authentication, authorization, encryption
- **Performance:** Caching, optimization strategies
- **DevOps:** Deployment, CI/CD, monitoring

## Superseding Decisions

When a decision changes:
1. Update status to "Superseded"
2. Link to new decision: "Superseded by DEC-XXX"
3. Don't delete - keep for historical context
4. Move to `.ai/memory/archive/` after 90 days unused
