# Batch Task Execution Workflow

This file defines the template for autonomous batch task execution via the `pwn batch` command.

## Overview

Batch task execution uses `.ai/batch/batch_runner.sh` to autonomously:
- Read stories from `.ai/tasks/prd.json`
- Spawn fresh Claude sessions per task
- Run quality gates (tests, linting, type checking)
- Track progress and learnings between iterations
- Handle retries, rate limits, and circuit breaking

## Usage

```bash
# Preview next task
./.ai/batch/batch_runner.sh --dry-run

# Run batch (default 20 iterations)
./.ai/batch/batch_runner.sh

# Custom iteration limit
./.ai/batch/batch_runner.sh 50

# Specific phase only
./.ai/batch/batch_runner.sh --phase 3

# Via pwn CLI
pwn batch run
pwn batch run --dry-run
pwn batch status
```

## Batch Execution Protocol

### Phase 1: Task Selection

1. Read `tasks/prd.json` for stories
2. Find next story where `passes == false`
3. Verify all dependencies have `passes == true`
4. Apply phase filter if specified

### Phase 2: Execution

1. Build prompt from `.ai/batch/prompt.md` template
2. Substitute story placeholders ({STORY_ID}, {STORY_TITLE}, etc.)
3. Spawn: `claude --print --dangerously-skip-permissions -p "<prompt>"`
4. Capture output to `logs/` for debugging

### Phase 3: Quality Gates

Customize `run_quality_gates()` in `batch_runner.sh` for your stack:

**Node.js:**
```bash
npm test
npm run lint
npm run typecheck
```

**Python:**
```bash
pytest --tb=short
ruff check src/
mypy src/ --ignore-missing-imports
```

**Gate Strategy:**
- Fail fast on first error
- Retry up to 2x with error context fed back to Claude
- Circuit breaker after 3 consecutive failures

### Phase 4: Completion

1. Mark story as `passes: true` in prd.json
2. Append learnings to `progress.txt`
3. Commit prd.json + progress.txt update
4. Continue to next story

## Batch Configuration

Define batch settings in `state.json`:

```json
{
  "batch_config": {
    "max_tasks": 5,
    "max_duration_hours": 4,
    "quality_gates": ["typecheck", "lint", "test"],
    "skip_gates": [],
    "auto_commit": true,
    "auto_push": false,
    "create_pr": false,
    "branch_format": "feature/{id}-{slug}",
    "commit_format": "conventional"
  }
}
```

## Task Selection Strategy

### Default: Highest Priority
```
- High priority tasks first
- Within priority: ordered by position in backlog
- Skip blocked tasks (note reason in state)
```

### Alternative: By Effort
```
- Small (XS, S) tasks first
- Accumulate quick wins
- Build momentum
```

### Alternative: By Due Date
```
- Tasks with deadlines first
- Then by priority
- Suitable for time-sensitive work
```

## Error Handling

### Build Fails
```
1. Show error output
2. Offer options:
   a) Fix automatically (if pattern known)
   b) Pause for manual fix
   c) Skip to next task (with note)
3. Retry if auto-fixed
4. Abort batch if repeated failures
```

### Test Fails
```
1. Show failing test
2. Offer options:
   a) Debug and fix
   b) Review assertion (might be test issue)
   c) Pause for investigation
3. Don't commit until tests pass
```

### Git Conflicts
```
1. Pause batch execution
2. Notify user of conflict
3. Request manual resolution
4. Resume after rebase/merge
```

### Dependency Issues
```
1. Check if task dependencies are met
2. If not met:
   a) Add dependency task to batch
   b) Execute dependency first
   c) Resume original task
3. Don't proceed if can't satisfy dependencies
```

## Commit Message Format

Use conventional commits:

```
type(scope): subject

body

footer
```

**Types:**
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `style:` Code style (formatting, missing semicolons)
- `refactor:` Refactoring without feature changes
- `perf:` Performance improvement
- `test:` Adding/updating tests
- `chore:` Build, dependencies, tooling

**Example:**
```
feat(youtube-summarizer): add batch download mode

- Added batch processing for multiple URLs
- Implemented progress tracking
- Added resume capability for interrupted batches

Fixes: US-042
```

## Logging & Reporting

Log batch execution for review:

```
[14:23] Starting batch execution (max 5 tasks, 4 hours)
[14:23] → Selected US-042: Add batch download mode (High, M)
[14:25] ✓ Feature branch created
[14:28] ✓ Implementation complete
[14:30] ✓ Tests pass (18 specs, 0 failures)
[14:31] ✓ Linting pass (0 issues)
[14:31] ✓ Build successful (2.3s)
[14:32] ✓ Committed: feat(youtube-summarizer): add batch download mode
[14:33] ✓ Pushed to origin
[14:33] ✓ Task completed (10 min)
[14:33]
[14:33] → Selected US-043: Add schedule endpoint (High, M)
[14:35] ✗ Type check failed: ...
[14:35] ⓘ Pausing batch - manual intervention needed
```

## Resuming Batch

To resume after pause:

```bash
# Shows what was paused
pwn batch --status

# Continue from where it stopped
pwn batch --resume

# Skip current task and continue
pwn batch --resume --skip
```

State is stored in `state.json`:

```json
{
  "batch_state": {
    "current_task": "US-042",
    "started_at": "2026-01-21T14:23:00Z",
    "completed": ["US-041"],
    "pending": ["US-043", "US-044", "US-045"],
    "paused_at": "2026-01-21T14:35:00Z",
    "pause_reason": "Type check failed"
  }
}
```

## Safety Measures

1. **No destructive operations without confirmation**
   - Force push requires explicit approval
   - Deleting branches requires confirmation
   - Reverting commits shows diff first

2. **Rollback capability**
   - Each batch has unique branch
   - Can revert entire batch: `git reset --hard`
   - Commits are preserved in history

3. **Notifications**
   - Completion notification to user
   - Failure notification with context
   - Blockers notify team if configured

4. **Rate limiting**
   - Default 5 tasks max per batch
   - Configurable via `--count` or `batch_config`
   - Time-based limit (default 4 hours)

## Configuration Examples

### Quick Wins Mode
```json
{
  "batch_config": {
    "max_tasks": 10,
    "selection_strategy": "effort",
    "quality_gates": ["test"],
    "auto_commit": true
  }
}
```

### Safe Mode
```json
{
  "batch_config": {
    "max_tasks": 1,
    "quality_gates": ["typecheck", "lint", "test", "build"],
    "auto_commit": false,
    "create_pr": true
  }
}
```

### Aggressive Mode
```json
{
  "batch_config": {
    "max_tasks": 20,
    "quality_gates": ["test"],
    "skip_gates": ["typecheck"],
    "auto_commit": true,
    "auto_push": true
  }
}
```

## Monitoring

Track batch execution performance:

```json
{
  "batch_metrics": {
    "average_task_duration": "15 min",
    "success_rate": "92%",
    "most_common_blocker": "failing_tests",
    "total_tasks_completed": 47
  }
}
```

## Tips

- Start with small batches (1-3 tasks) to validate quality gates
- Increase batch size as confidence grows
- Monitor commit history for quality
- Adjust quality gates if too strict or too loose
- Use batch mode during focused work sessions
- Coordinate with team when executing larger batches
