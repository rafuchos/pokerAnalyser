# AI Workspace

This directory contains all AI-related context, memory, and configuration for this project.

## 📁 Structure

```
.ai/
├── README.md                     # This file
├── state.json                    # Current session state (git-ignored)
├── memory/                       # Persistent knowledge
│   ├── decisions.md              # Architectural decisions
│   ├── patterns.md               # Codebase patterns
│   ├── deadends.md               # Failed approaches
│   └── archive/                  # Historical context
├── tasks/                        # Work tracking
│   ├── active.md                 # Current tasks
│   └── backlog.md                # Future tasks
├── patterns/                     # Auto-applied patterns
│   ├── index.md                  # Trigger map
│   ├── frontend/                 # Frontend patterns
│   ├── backend/                  # Backend patterns
│   └── universal/                # Cross-cutting patterns
├── config/                       # Configurations (git-ignored)
│   └── notifications.json        # Notification settings
├── workflows/                    # Automation templates
│   └── batch-task.md             # Batch execution prompt
└── agents/                       # AI agent configs
    ├── README.md                 # Agent documentation
    └── claude.md                 # Claude Code bootstrap
```

## 🧠 Memory System

### decisions.md
Tracks major architectural decisions with rationale and impact.

**Format:**
```markdown
## DEC-001: Decision Title
**Date:** YYYY-MM-DD
**Context:** Why this decision was needed
**Decision:** What was decided
**Rationale:** Why this is the best choice
**Impact:** What this affects
```

### patterns.md
Captures recurring patterns learned during development.

**Format:**
```markdown
## Pattern Category

### Pattern Name
**Context:** When this applies
**Pattern:** Code example or description
**Rationale:** Why this is better
```

### deadends.md
Documents approaches that failed to avoid repeating mistakes.

**Format:**
```markdown
## DE-001: Failed Approach
**Date:** YYYY-MM-DD
**Attempted:** What we tried
**Problem:** Why it failed
**Solution:** What worked instead
```

## 📋 Tasks System

### active.md
Current work in progress. Use checkboxes for tracking:
```markdown
- [ ] US-001: Pending task
- [x] US-002: Completed task
```

### backlog.md
Future tasks, prioritized from top to bottom.

## 🎯 Patterns System

Patterns are auto-applied based on triggers defined in `patterns/index.md`.

**How it works:**
1. AI reads `patterns/index.md` on session start
2. Registers triggers (file extensions, imports, commands)
3. Auto-loads relevant patterns when triggered
4. Applies patterns to current work

**Example:**
```
User edits: src/components/Button.tsx
→ Triggers: *.tsx
→ Auto-loads: patterns/frontend/react/
→ Applies React patterns automatically
```

## 🔄 Workflows

### batch-task.md
Template for autonomous batch execution. Used by `pwn batch` command.

Defines:
- Task selection logic
- Quality gates (tests, lint, typecheck)
- Commit patterns
- Completion signals

### Writing stories for `prd.json`

Stories run with `--dangerously-skip-permissions` — the agent has full access. Write defensively.

**Never put these in batch stories:**
- Destructive git ops (`git filter-repo`, `BFG`, `push --force`, history rewriting)
- Destructive file ops (`rm -rf`, wiping directories)
- Database ops (`DROP TABLE`, prod migrations)
- Secret rotation (revoking keys, rotating credentials)
- External side effects (sending emails, creating PRs, publishing packages)

**Rule of thumb**: if a mistake needs human intervention to fix, it's not a batch story.

**Instead**, ask the agent to **prepare and document** — write the script, the docs, the config — but let a human execute the dangerous part.

**Always include in `notes`** what the agent must NOT do:
```json
"notes": "Do NOT run git-filter-repo. Do NOT modify prd.json."
```

## 🤖 Agents

### agent/claude.md
Bootstrap instructions for Claude Code.

Contains:
- Session start protocol
- Context loading order
- Pattern auto-application rules
- Batch execution mode

### Adding New Agents
Copy `agents/claude.md` as template for other AI agents (Cursor, Copilot, etc).

## 🔒 Git Ignore

**Tracked (committed):**
- memory/ (shared team knowledge)
- tasks/ (work visibility)
- patterns/ (team patterns)
- workflows/ (team automation)
- agents/ (team AI configs)

**Ignored (local only):**
- state.json (personal session state)
- config/notifications.json (personal notification settings)

## 🚀 Getting Started

### For AI Agents
1. Read `agents/<your-agent>.md` for bootstrap instructions
2. Load `memory/` files for context
3. Register patterns from `patterns/index.md`
4. Check `tasks/active.md` for current work

### For Humans
1. Review `memory/decisions.md` for architectural context
2. Check `tasks/active.md` for team's current work
3. Add tasks to `tasks/backlog.md` for AI to pick up
4. Update patterns in `memory/patterns.md` when you discover new ones

## 📚 Learn More

- [PWN Documentation](https://github.com/yourusername/pwn)
- [Quick Start Guide](https://github.com/yourusername/pwn/docs/quick-start.md)
- [Pattern Guide](https://github.com/yourusername/pwn/docs/patterns-guide.md)

---

**PWN Version:** 1.0.0
**Injected:** (automatically set on injection)
