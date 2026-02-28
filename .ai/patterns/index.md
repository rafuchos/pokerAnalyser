# Pattern Auto-Apply Trigger Map

This file defines triggers that automatically load relevant patterns during AI sessions.

## How It Works

1. AI agent starts session
2. Reads this file to register triggers
3. Monitors file changes, imports, and commands
4. When trigger matches, loads relevant patterns from `patterns/` subdirectories
5. Applies patterns to current work

---

## Trigger Types

- **`fileExt`** - File extension patterns (e.g., `*.tsx`, `*.py`)
- **`import`** - Import statements (e.g., `from react import`)
- **`command`** - CLI commands (e.g., `pnpm dev`, `npm test`)
- **`path`** - Directory path patterns (e.g., `src/components/`)
- **`keyword`** - Code keywords (e.g., `interface`, `class`)

---

## Trigger Format

```yaml
triggers:
  - name: "Pattern Name"
    type: "fileExt | import | command | path | keyword"
    value: "*.tsx"
    patterns:
      - "frontend/react"
      - "universal/typescript"
    description: "Loads when working with React components"
```

---

## Trigger Registry

### Frontend Triggers

```yaml
triggers:
  - name: "React Components"
    type: "fileExt"
    value: "*.tsx"
    patterns:
      - "frontend/react"
      - "universal/typescript"
    description: "Auto-loads React component patterns"

  - name: "React Hooks"
    type: "import"
    value: "import.*useEffect|useState|useContext"
    patterns:
      - "frontend/react/hooks"
    description: "Loads when using React hooks"

  - name: "Styling"
    type: "fileExt"
    value: "*.css,*.scss,*.tailwind"
    patterns:
      - "frontend/styling"
    description: "CSS/styling patterns"

  - name: "Component Library"
    type: "import"
    value: "from.*@shadcn|from.*@mui"
    patterns:
      - "frontend/component-libs"
    description: "Component library patterns"
```

### Backend Triggers

```yaml
triggers:
  - name: "Express Routes"
    type: "fileExt"
    value: "*.routes.ts,routes/*.ts"
    patterns:
      - "backend/express"
      - "universal/rest-api"
    description: "Express route patterns"

  - name: "Database Queries"
    type: "import"
    value: "from.*prisma|from.*knex|from.*typeorm"
    patterns:
      - "backend/database"
    description: "Database query patterns"

  - name: "API Endpoints"
    type: "keyword"
    value: "app.get|app.post|router.put"
    patterns:
      - "backend/express"
      - "universal/rest-api"
    description: "REST API patterns"

  - name: "Error Handling"
    type: "keyword"
    value: "try|catch|throw|Error"
    patterns:
      - "universal/error-handling"
    description: "Error handling patterns"
```

### Testing Triggers

```yaml
triggers:
  - name: "Unit Tests"
    type: "import"
    value: "from.*jest|from.*vitest|describe|it"
    patterns:
      - "universal/testing/unit"
    description: "Unit test patterns"

  - name: "Integration Tests"
    type: "path"
    value: "**/*.integration.test.ts"
    patterns:
      - "universal/testing/integration"
    description: "Integration test patterns"

  - name: "E2E Tests"
    type: "path"
    value: "**/*.e2e.test.ts,cypress/**/*,playwright/**/*"
    patterns:
      - "universal/testing/e2e"
    description: "End-to-end test patterns"
```

### Universal Triggers

```yaml
triggers:
  - name: "TypeScript"
    type: "fileExt"
    value: "*.ts,*.tsx"
    patterns:
      - "universal/typescript"
    description: "TypeScript patterns"

  - name: "Git Workflow"
    type: "command"
    value: "git commit|git push|git pull"
    patterns:
      - "universal/git"
    description: "Git workflow patterns"

  - name: "Build Tools"
    type: "command"
    value: "npm|pnpm|yarn|webpack|vite"
    patterns:
      - "universal/build-tools"
    description: "Build and package patterns"
```

---

## Priority Order

Triggers are applied in priority order:
1. **Highest:** `fileExt` (most specific)
2. **High:** `path` (directory context)
3. **Medium:** `import` (code context)
4. **Low:** `keyword` (broad matches)
5. **Lowest:** `command` (least specific)

If multiple triggers match, load all associated patterns.

---

## Adding New Triggers

1. Identify the pattern category
2. Determine trigger type
3. Define pattern value
4. Link to pattern files in `patterns/` subdirectories
5. Add entry to appropriate section
6. Commit with message: `docs: add trigger for [pattern]`

---

## Pattern Directory Structure

Patterns are organized in subdirectories matching triggers:

```
patterns/
├── frontend/
│   ├── react/
│   ├── styling/
│   └── component-libs/
├── backend/
│   ├── express/
│   └── database/
└── universal/
    ├── typescript/
    ├── testing/
    ├── error-handling/
    ├── git/
    └── build-tools/
```

Each directory contains:
- `<category>.template.md` - Template showing pattern format (don't edit)
- `<pattern-name>.md` - Actual patterns created by AI as it learns
- `*.example.ts` - Code examples (optional)

---

## Examples

### Example 1: React Component Trigger

**Condition:** User edits `src/components/Button.tsx`
**Triggers:** `*.tsx` matches
**Load:** `patterns/frontend/react-components.md` (if exists)
**Apply:** React component patterns learned in this project

### Example 2: API Endpoint Trigger

**Condition:** User imports `from 'express'`
**Triggers:** `import.*express` matches
**Load:** `patterns/backend/api-routes.md` (if exists)
**Apply:** Express + REST API patterns learned in this project

### Example 3: Test File Trigger

**Condition:** User creates `src/__tests__/utils.test.ts`
**Triggers:** `*.test.ts` matches
**Load:** `patterns/universal/testing.md` (if exists)
**Apply:** Test patterns learned in this project

---

## Disabling Triggers

To temporarily disable pattern auto-apply:

1. Add to `state.json`: `"auto_patterns_enabled": false`
2. Manually import patterns as needed
3. Re-enable: `"auto_patterns_enabled": true`

---

## Feedback

- If pattern is irrelevant, note in `state.json` to refine triggers
- Patterns that save time: commit and document
- Patterns that cause friction: update or disable
