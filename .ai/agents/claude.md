# Claude Code Bootstrap Instructions

Complete bootstrap protocol for Claude Code AI agent working with PWN framework.

**Version:** 1.0.0
**Agent:** Claude Code (Claude Opus 4.5+)
**Framework:** PWN (Project Workspace Network)

---

## Session Start Protocol

Follow this sequence every time you start a Claude Code session.

### Step 1: Load Session State (1 min)

Read `/.ai/state.json` to understand current session:

```json
{
  "developer": "your-git-username",
  "session_started": "2026-01-21T00:00:00Z",
  "session_mode": "interactive",
  "current_task": null,
  "context_loaded": []
}
```

This file is git-ignored and tracks your personal session state.

### Step 2: Load Shared Context (5 min)

Read these files in order:

1. **`/.ai/memory/decisions.md`**
   - Contains architectural decisions (DEC-XXX)
   - Reference these decisions when making changes
   - Ask user before deviating from active decisions

2. **`/.ai/memory/patterns.md`**
   - Codebase patterns learned by team
   - Apply these patterns to new work
   - Add new patterns when discovered

3. **`/.ai/memory/deadends.md`**
   - Failed approaches documented (DE-XXX)
   - Avoid these approaches
   - Reference when encountering similar problems

### Step 3: Check Current Work State (2 min)

Review `/.ai/state.json` for:
- `current_task`: What you were working on (if any)
- `context_loaded`: What context files you've already read
- `session_mode`: "interactive" or "batch"

Then check `/.ai/tasks/active.md`:
- What tasks are currently assigned
- What's blocked and why
- Priority ordering

If this is your first session:
- `current_task` will be null
- Proceed to check project-specific guidance in `/CLAUDE.md` or `/README.md`

### Step 4: Load Project Context (3 min)

1. **`/.ai/tasks/active.md`**
   - What work is currently in progress
   - Your task assignments
   - Blocked items and blockers
   - Priority ordering

2. **`/.ai/tasks/prd.json`** (if needed)
   - Future work as structured JSON stories
   - Use when no active work assigned
   - Pick next story with dependencies satisfied

3. **Project-specific notes** (if applicable)
   - Check `/CLAUDE.md` in project root
   - May override or extend these instructions
   - Always follow project-specific rules

### Step 5: Register Pattern Auto-Apply Triggers (2 min)

Update `/.ai/state.json` to mark context as loaded:
```json
{
  "context_loaded": ["memory", "tasks", "patterns"]
}
```

Read `/.ai/patterns/index.md`

For each trigger type:
- File extension patterns (`*.tsx`, `*.ts`)
- Import patterns (`from 'react'`, `import.*express`)
- Path patterns (`src/components/`, `routes/`)
- Keyword patterns (`interface`, `class`, `useEffect`)
- Command patterns (`npm build`, `git commit`)

When working, auto-load relevant patterns:
- Editing `.tsx` file → Load frontend/react patterns
- Writing tests → Load universal/testing patterns
- Creating API route → Load backend/express + universal/rest-api patterns

### Step 6: Check Configuration (1 min)

Read `/.ai/state.json` (if exists)

Important settings:
- `developer`: Your name
- `session_mode`: "interactive" or "batch"
- `auto_patterns`: true/false (pattern auto-apply enabled?)
- `batch_config`: Settings if running in batch mode
- `quality_gates`: Tests/lint/typecheck requirements

### Step 7: Acknowledge Understanding (1 min)

In your first message, confirm what you learned:

```
I've loaded the following context for this session:
- Decisions: DEC-001, DEC-002 (active)
- Current task: US-042 (from active.md)
- Recent dead end: DE-003 (avoided earlier approach)
- Developer: {username}
- Mode: Interactive

I'm ready to work on: [describe current task]
```

This confirms you understand the context before proceeding.

---

## Interactive Mode

When `session_mode` is "interactive":

### Your Role
- Respond to user requests and commands
- Ask clarifying questions when context is incomplete
- Reference decisions and patterns in your work
- Update patterns when you discover new approaches
- Document dead ends when approaches fail
- Commit changes with clear messages

### Workflow

```
User Request
    ↓
Load relevant context (decisions, patterns, active task)
    ↓
Understand requirement
    ↓
Check patterns/index.md for triggers
    ↓
Execute work following patterns
    ↓
Run quality gates (tests, lint, typecheck)
    ↓
Commit with clear message
    ↓
Update active task status
    ↓
Report completion
```

### Quality Gates

Before committing code, verify:

1. **Type Checking**
   ```bash
   npm run typecheck || tsc --noEmit
   ```
   Must pass without errors

2. **Linting**
   ```bash
   npm run lint || eslint .
   ```
   Must pass (or auto-fix if applicable)

3. **Unit Tests**
   ```bash
   npm run test || jest
   ```
   Must pass all tests

4. **Integration Tests** (if applicable)
   ```bash
   npm run test:integration
   ```
   Must pass

5. **Build Verification**
   ```bash
   npm run build
   ```
   Must complete successfully

If any gate fails:
- Show the error
- Offer to fix if pattern known
- Ask user if unsure how to proceed
- Don't commit until gates pass

### Commit Message Format

Use conventional commits:

```
type(scope): description

Detailed explanation of change.

Reference relevant decisions:
- See DEC-XXX for rationale
- Implements US-042

Related patterns:
- Applied frontend/react patterns
- Follows universal/typescript guidelines
```

Types:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `style:` Code formatting
- `refactor:` Code restructuring
- `perf:` Performance improvement
- `test:` Test additions/changes
- `chore:` Build, tooling, dependencies

### Task Tracking

When completing work:

1. Update `/.ai/tasks/active.md`
   ```markdown
   - [x] US-042: My completed task (YYYY-MM-DD)
   ```

2. Update `/.ai/memory/patterns.md` if new pattern discovered
   ```
   ## New Pattern Category

   ### Pattern Name
   **Context:** When to use
   **Pattern:** Description
   **Rationale:** Why it's better
   ```

3. Add to `/.ai/memory/deadends.md` if approach failed
   ```
   ## DE-XXX: What we tried
   **Date:** YYYY-MM-DD
   **Attempted:** Description
   **Problem:** Why it failed
   **Solution:** What worked instead
   ```

---

## Batch Mode

Autonomous task execution via `.ai/batch/batch_runner.sh`.

The runner reads stories from `.ai/tasks/prd.json`, spawns fresh Claude sessions
per task, runs quality gates, and tracks progress.

### Usage
```bash
./.ai/batch/batch_runner.sh --dry-run    # Preview next task
./.ai/batch/batch_runner.sh              # Run (default 20 iterations)
./.ai/batch/batch_runner.sh 50           # Custom iteration limit
./.ai/batch/batch_runner.sh --phase 3    # Specific phase only
```

### State Files
| File | Purpose |
|------|---------|
| .ai/tasks/prd.json | Single source of truth for task status |
| .ai/batch/progress.txt | Append-only operational learnings |
| .ai/batch/prompt.md | Prompt template for Claude sessions |
| logs/ | Per-task Claude output logs |

### How It Works
1. Read prd.json → find next incomplete story (deps satisfied)
2. Spawn: `claude --print --dangerously-skip-permissions -p "implement story X"`
3. Run quality gates (configurable per project)
4. If pass → mark story done in prd.json, commit
5. If fail → retry up to 2x with error context
6. Append learnings to progress.txt
7. Repeat until done or max iterations

### Safety
- Circuit breaker: 3 consecutive failures → stop
- Rate limit detection + auto-wait
- Graceful Ctrl+C shutdown
- Per-task logs for debugging

---

## Context Loading Order

Reference these files in this priority order:

1. **First Priority: Active Work**
   - `/.ai/state.json` - Your personal session state
   - `/.ai/tasks/active.md` - What's being done now
   - Current file being edited

2. **Second Priority: Decisions**
   - `/.ai/memory/decisions.md` - What was decided and why
   - `/CLAUDE.md` if exists - Project-specific overrides
   - Code comments referencing decisions

3. **Third Priority: Patterns**
   - `/.ai/patterns/index.md` - Trigger map for auto-apply
   - Relevant subdirectories in `/.ai/patterns/`
   - Code examples from existing codebase

4. **Fourth Priority: Historical Context**
   - `/.ai/memory/deadends.md` - What failed (avoid!)
   - `/.ai/memory/archive/` - Superseded decisions
   - Project changelog or git history

5. **Fifth Priority: Planning**
   - `/.ai/tasks/prd.json` - Future work (structured)
   - Roadmap or project documentation
   - Upstream issues or features

---

## Pattern Auto-Application

Patterns are automatically applied based on triggers in `/.ai/patterns/index.md`.

### How It Works

1. You start editing a file (e.g., `src/components/Button.tsx`)
2. Extension matches: `*.tsx`
3. Auto-load patterns:
   - `/.ai/patterns/frontend/react/` (React components)
   - `/.ai/patterns/universal/typescript/` (TypeScript)
4. Apply patterns to your work
5. Reference pattern in code comment if complex

### Example Triggers

```
File: src/components/Button.tsx
Triggers: *.tsx, path: src/components/
Load: frontend/react, universal/typescript
Apply: React component best practices

File: src/routes/api/videos.ts
Triggers: *.routes.ts, keyword: app.get|app.post|router.use
Load: backend/express, universal/rest-api
Apply: Express routing patterns

File: src/__tests__/utils.test.ts
Triggers: *.test.ts, import: jest|vitest
Load: universal/testing/unit
Apply: Unit testing patterns
```

### Overriding Patterns

If pattern doesn't apply:

1. Check if trigger condition is correct
2. Review pattern directory (might be different name)
3. Manually import pattern if needed
4. Update `patterns/index.md` if trigger was wrong

---

## Decision-Making Framework

When making architectural decisions:

1. **Check existing decisions** - Is this already decided?
   - Look in `/.ai/memory/decisions.md`
   - Reference decision with "See DEC-XXX"

2. **Check patterns** - Is there a pattern to follow?
   - Look in `/.ai/patterns/`
   - Apply pattern without deviation

3. **Check dead ends** - Has this failed before?
   - Look in `/.ai/memory/deadends.md`
   - Avoid approaches in DE-XXX

4. **When in doubt:** Ask the user
   - Don't make big architectural decisions alone
   - Explain options and ask for preference
   - Reference decisions and patterns in explanation

5. **Document new decisions**
   - If making significant choice: suggest updating `/.ai/memory/decisions.md`
   - Include context, rationale, and impact
   - Commit with message: `docs: add DEC-XXX decision`

---

## Common Questions

### Q: What if I can't find context I need?

**A:** Check these locations in order:
1. `/.ai/` directory (patterns, decisions, tasks)
2. Project root files (README.md, CLAUDE.md, etc.)
3. Codebase examples (similar code patterns)
4. Ask the user - context might not exist yet

### Q: Should I commit every small change?

**A:** Keep commits:
- Atomic (one logical change)
- Focused (don't mix unrelated changes)
- Well-described (use conventional commits)
- Under 300 lines if possible

Multiple small commits are better than one big commit.

### Q: When should I update patterns?md?

**A:** Add to patterns when:
- You discover a reusable approach
- Multiple tasks benefit from the pattern
- It prevents common mistakes
- It's team-relevant (not just personal preference)

Update commit message: `docs: add pattern - [name]`

### Q: What if quality gates fail in batch mode?

**A:** Batch mode stops and:
1. Shows error details
2. Pauses execution
3. Notifies user
4. Waits for manual intervention or approval

Batch never force-commits on failures.

### Q: How do I know if something is blocked?

**A:** Task is blocked if:
- Listed in `tasks/active.md` with "Blocked by:" section
- Depends on other unfinished task
- Waiting for external event (approval, API key, etc.)
- Resource constraint (hardware, capacity)

Don't skip blocked tasks - document blocker and move to next.

---

## Tips for Effective Sessions

1. **Start strong** - Read all context files before writing code
2. **Reference decisions** - Use DEC-XXX, DE-XXX, patterns in comments
3. **Commit often** - Small commits are easier to review and revert
4. **Test continuously** - Run quality gates before commit
5. **Update context** - Document patterns and dead ends as you learn
6. **Ask when uncertain** - Better to ask than make wrong assumption
7. **Keep patterns current** - Archive old patterns, add new discoveries
8. **Think long-term** - Each decision affects future sessions

---

## Troubleshooting

### "I can't find the context I need"
- Check if file exists in `/.ai/`
- Search with Grep tool for specific content
- Ask user where context is documented
- May need to create new context file

### "Pattern doesn't seem to apply"
- Verify trigger condition matches
- Check different pattern directory
- Manually load pattern if needed
- Update pattern or trigger

### "Quality gates failing"
- Show full error output
- If pattern known: apply fix
- If unsure: ask user or pause batch
- Never skip gates without explicit approval

### "Unsure if change follows decisions"
- Find relevant decision in `memories/decisions.md`
- If not found: ask user for guidance
- If contradicts decision: request user approval
- Reference decision in commit message

### "Need to deviate from pattern"
- Document deviation in code comment
- Explain why pattern doesn't apply
- Consider updating pattern if it's flawed
- Get user approval if architectural impact

---

## Session Completion

When finishing a session:

1. **Commit pending work**
   - All changes staged and committed
   - Commit message references task/decision

2. **Update task status**
   - Check boxes in `/.ai/tasks/active.md`
   - Add completion date if done

3. **Document learnings**
   - Update `/.ai/memory/patterns.md` if discovered pattern
   - Update `/.ai/memory/deadends.md` if failed approach
   - Reference in commit messages

4. **Clean up**
   - No uncommitted changes
   - Local branches cleaned up
   - Remote is up to date

5. **Summary to user**
   - What was accomplished
   - What's still pending
   - Next steps
   - Any blockers

---

## Next Session

When returning:

1. Read `/.ai/state.json` for your last session state
2. Check `current_task` to see what you were working on
3. Start from Step 2 of Session Start Protocol
4. Pick up from where you left off
5. Update `session_started` timestamp in state.json

---

**Document Version:** 1.0.0
**Last Updated:** Template injection date
**Framework:** PWN 1.0.0
**Supported Models:** Claude Opus 4.5+
