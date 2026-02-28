# Active Tasks

This file tracks work currently in progress.

## Format

Use checkboxes to track completion status:

```markdown
- [x] US-001: Pending task (2026-02-28)
- [x] US-002: Completed task
```

Each task can have:
- **Status indicator:** [ ] = pending, [x] = completed
- **ID:** US-XXX, BUG-XXX, DEV-XXX, or SPIKE-XXX
- **Title:** Clear, actionable description
- **Notes:** Optional context or blockers
- **Assignee:** Who's working on it (optional)

---

## Task Types

- **US-XXX:** User Story (feature work)
- **BUG-XXX:** Bug fix
- **DEV-XXX:** Developer task (refactoring, tech debt)
- **SPIKE-XXX:** Research or investigation
- **DOCS-XXX:** Documentation

---

## Management Rules

1. **Limit WIP:** Keep 3-5 tasks active max
2. **Prioritize:** Order from highest to lowest priority
3. **Clarify blockers:** Note if task is blocked
4. **Update daily:** Check boxes as you work
5. **Archive completion:** Move finished tasks to backlog with date

---

## Template for New Task

```markdown
- [ ] US-XXX: [Clear title]
  - Assignee: (your name or team)
  - Priority: High/Medium/Low
  - Blocked by: (if applicable)
  - Notes: (context)
```

---

## Current Sprint

Update this section weekly with sprint goals and dates.

**Sprint:** YYYY-MM-DD to YYYY-MM-DD
**Goal:** (What we're trying to accomplish)
**Capacity:** (Team capacity/points)

---

## Today's Focus

- [x] US-000: Reestruturação do Projeto + Banco SQLite com Import Pipeline (2026-02-28)
- [x] US-001: Parser de Ações Detalhadas por Street (2026-02-28)

---

## Completed

- [x] US-001: Parser de Ações Detalhadas por Street (2026-02-28)
  - Parse every player action (fold, call, raise, check, bet, all-in) with amounts
  - Separate actions by street: preflop, flop, turn, river
  - Identify table positions (BTN, SB, BB, UTG, MP, CO) for each player
  - Extract board cards per street (flop 3 cards, turn 1, river 1)
  - Detect VPIP (voluntary pot entry excluding forced blinds)
  - Works for both GGPoker and PokerStars hand histories
  - Persist actions in hand_actions SQLite table with schema migration
  - Backward compatible with existing financial parser and reports
  - 61 new tests (83 total passing)

- [x] US-000: Reestruturação do Projeto + Banco SQLite com Import Pipeline (2026-02-28)
  - Reorganized project structure under src/ with parsers/, db/, analyzers/, reports/
  - Implemented SQLite database with schema for hands, sessions, tournaments
  - Created incremental import pipeline with file hash deduplication
  - Built CLI entry point (main.py) with import, report, stats subcommands
  - Extracted parsers from original monolithic scripts into dedicated modules
  - Reports now read from database instead of memory
  - 22 tests passing

---

## Notes

- Check prd.json for upcoming stories
- Move completed tasks to archive or backlog with completion date
- When stuck, create SPIKE task to investigate
- Reference decisions from `memory/decisions.md`
- Flag architectural changes for team discussion
