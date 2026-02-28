# AI Agent Configuration

This directory contains bootstrap instructions and configuration for different AI agents working on this project.

## Overview

Different AI agents (Claude, Cursor, Copilot, etc.) need specific instructions to work effectively with PWN framework and project context.

Each agent has:
- **`<agent>.md`** - Complete bootstrap instructions for that agent
- **Auto-load triggers** defined in `patterns/index.md`
- **Context loading order** for efficient session start
- **Task execution mode** (batch vs. interactive)

## Available Agents

### Claude Code (`claude.md`)
- **Status:** Primary agent
- **Recommended for:** Full-stack development, complex tasks, refactoring
- **Session model:** Interactive or batch (autonomous)
- **Model:** Claude Opus 4.5 (recommended)

### Cursor (Coming Soon)
- **Status:** Planned
- **Recommended for:** Single-file editing, rapid iteration
- **Session model:** Interactive
- **Model:** Latest Claude via Cursor

### GitHub Copilot (Coming Soon)
- **Status:** Planned
- **Recommended for:** In-IDE completion, pair programming
- **Session model:** Interactive
- **Model:** Copilot Plus

## Bootstrap Protocol

Every agent follows this sequence on session start:

1. **Load Session State**
   - Read `/.ai/state.json` for current session info
   - Identify developer and session mode

2. **Load Shared Context**
   - Read `memory/decisions.md` for architectural decisions
   - Read `memory/patterns.md` for discovered patterns
   - Read `memory/deadends.md` to avoid known failures

3. **Load Task Context**
   - Read `tasks/active.md` for current work
   - Optionally read `tasks/backlog.md` for planning

4. **Register Auto-Apply Triggers**
   - Read `patterns/index.md`
   - Register file watchers and import triggers
   - Load relevant patterns as needed

5. **Load Agent-Specific Instructions**
   - Read `agents/<agent>.md` for specific bootstrap
   - Configure agent settings from `state.json`
   - Prepare for interactive or batch mode

6. **Acknowledge Understanding**
   - Display what context was loaded
   - Show current task or available work
   - Ready to accept commands

## Agent-Specific Features

### Claude Code
- Full filesystem access
- Git repository integration
- Browser automation (Playwright)
- Network requests
- File editing and creation
- Batch task execution
- Pattern auto-application

### Cursor
- Single file focus
- In-editor quick-start
- Codebase navigation
- Inline suggestions
- Git integration (basic)

### Copilot
- In-IDE suggestions
- Autocomplete
- Ghost text
- Chat interface
- Limited filesystem access

## Adding New Agents

To add a new AI agent:

1. Create `agents/<agent-name>.md` with complete bootstrap instructions
2. Follow the template structure in `claude.md`
3. Include agent-specific capabilities and limitations
4. Define recommended use cases
5. Add instructions for pattern auto-application
6. Document any configuration needed in `state.json`
7. Commit with message: `docs: add <agent-name> agent bootstrap`

### Template Structure

```markdown
# [Agent Name] Bootstrap

## Overview
- What the agent is and does
- Recommended use cases
- Supported models

## Session Start Protocol
1. Step 1
2. Step 2
3. ...

## Configuration
- Settings in state.json
- Environment variables
- Installation requirements

## Capabilities
- What it can do
- Limitations
- Best practices

## Examples
- Example 1: Typical workflow
- Example 2: Complex scenario

## Troubleshooting
- Common issues
- Solutions
```

## Workflow Coordination

Multiple agents can work on same project:

- **Serial workflow:** Agent A finishes, Agent B continues
  - Commit state before switching agents
  - New agent reads latest context and tasks

- **Parallel workflow:** Different agents on different tasks
  - Each agent has separate active task
  - Coordinate via `tasks/active.md`
  - Merge regularly to avoid conflicts

## State Sharing

All agents share:

```
tasks/active.md          ← What's being worked on
tasks/backlog.md         ← What's next
memory/decisions.md      ← What was decided
memory/patterns.md       ← What was learned
memory/deadends.md       ← What failed
```

Each agent has personal state in:

```
.ai/state.json          ← Personal session state (git-ignored)
.ai/config/             ← Agent-specific configs (git-ignored)
```

## Configuration Format

Agent configuration in `state.json`:

```json
{
  "agent": "claude",
  "model": "claude-opus-4-5",
  "session_mode": "interactive",
  "auto_patterns": true,
  "batch_config": { ... },
  "developer": "username"
}
```

## Tips for Agent Integration

1. **Keep context compact** - Link to detailed docs, don't embed everything
2. **Make decisions explicit** - Use `memory/decisions.md` for reasoning
3. **Track failures** - Document dead ends to avoid repetition
4. **Commit frequently** - Small commits are easier to understand
5. **Update patterns** - Capture learned patterns for future use
6. **Test quality gates** - Automate verification to catch issues early

## Links

- [Claude Code Bootstrap](claude.md) - Full instructions for Claude
- [Patterns Auto-Apply System](../patterns/index.md) - How triggers work
- [Batch Execution Workflow](../workflows/batch-task.md) - Autonomous task execution

## Version

**Last Updated:** (Set on template injection)
**Supported Agents:** Claude, Cursor (planned), Copilot (planned)
**Framework:** PWN 1.0.0
