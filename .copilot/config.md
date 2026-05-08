## common terms

- When user says "app" or "website" they are referring to wood_league_app repo in this folder
- When user says "lc0 runpod" or "stockfish runpod" they mean the wood_league_lc0_runpod, or wood_league_stockfish_runpod respectively
- When the user asks about an issue or issues, they are referring to git-issues, which each repo uses. check inside the right repo to find the right issues. 

## vexp — Context-Aware AI Coding <!-- vexp v2.0.12 -->

### MANDATORY: use vexp pipeline — do NOT grep or glob the codebase
For every task — bug fixes, features, refactors, debugging:
**call `run_pipeline` FIRST**. It executes context search + impact analysis +
memory recall in a single call, returning compressed results.

Do NOT use grep, glob, Bash, or cat to search/explore the codebase.
vexp returns pre-indexed, graph-ranked context that is more relevant and
uses fewer tokens than manual searching. Prefer `get_skeleton` over Read to
inspect files (detail: minimal/standard/detailed, 70-90% token savings).
Only use Read when you need exact raw content to edit a specific line.

### Primary Tool
- `run_pipeline` — **USE THIS FOR EVERYTHING**. Single call that runs
  capsule + impact + memory server-side. Returns compressed results.
  Auto-detects intent (debug/modify/refactor/explore) from your task.
  Includes full file content for pivots.
  Examples:
  - `run_pipeline({ "task": "fix JWT validation bug" })` — auto-detect
  - `run_pipeline({ "task": "refactor db layer", "preset": "refactor" })` — explicit
  - `run_pipeline({ "task": "add auth", "observation": "using JWT" })` — save insight in same call

### Other MCP tools (use only when run_pipeline is insufficient)
- `get_skeleton` — **preferred over Read** for inspecting files (minimal/standard/detailed detail levels, 70-90% token savings)
- `index_status` — indexing status and health check
- `expand_vexp_ref` — expand V-REF hash placeholders in v2 compact output

### Workflow
1. `run_pipeline("your task")` — ALWAYS FIRST. Returns pivots + impact + memories in 1 call
2. Need more detail on a file? Use `get_skeleton({ files: [...], detail: "detailed" })` — avoid Read unless editing
3. Make targeted changes based on the context returned
4. `run_pipeline` again ONLY if you need more context during implementation
5. Do NOT chain multiple vexp calls — one `run_pipeline` replaces capsule + impact + memory + observation

### Subagent / Explore / Plan mode
- Subagents CAN and MUST call `run_pipeline` — always include the task description
- The PreToolUse hook blocks Grep/Glob when vexp daemon is running
- Do NOT spawn Agent(Explore) to freely search — call `run_pipeline` first,
  then pass the returned context into the agent prompt if needed
- Always: `run_pipeline` → get context → spawn agent with context

### Smart Features (automatic — no action needed)
- **Intent Detection**: auto-detects from your task keywords. "fix bug" → Debug, "refactor" → blast-radius, "add" → Modify
- **Hybrid Search**: keyword + semantic + graph centrality ranking
- **Session Memory**: auto-captures observations; memories auto-surfaced in results
- **LSP Bridge**: VS Code captures type-resolved call edges
- **Change Coupling**: co-changed files included as related context

### Advanced Parameters
- `preset: "debug"` — forces debug mode (capsule+tests+impact+memory)
- `preset: "refactor"` — deep impact analysis (depth 5)
- `max_tokens: 12000` — increase total budget for complex tasks
- `include_tests: true` — include test files in results
- `include_file_content: false` — omit full file content (lighter response)

### Multi-Repo Workspaces
`run_pipeline` auto-queries all indexed repos. Use `repos: ["alias"]` to scope.
Use `index_status` to discover available repo aliases.
<!-- /vexp -->

## Communication Style

Be brief. Minimize output to preserve tokens:
- No preamble, no summaries, no "here's what I did" wrap-ups
- Skip explanations unless asked
- Code and diffs speak for themselves
- One sentence max per status update

## Model Selection

Before starting any sub-task, select the cheapest capable model:

- **Haiku**: docs, formatting, search, file reading, classification
- **Sonnet**: code generation, review, refactoring, tests, summarization
- **Opus**: debugging complex issues, architecture design, deep analysis

Always default to the cheapest model that can handle the task.

## Style and Design 
For any task involving design or styling: 
- make things look like a nineteenth century data visualization ala Web Du Bois

## Issue Tracking — git-issues

This project uses [`git-issues`](https://github.com/steviee/git-issues) for issue tracking. Issues are Markdown files stored in `.issues/` and committed to git alongside code.

### Workflow
- **Before starting work**: check `issues list` for existing issues or `issues next` for the next actionable one
- **When identifying a bug or task**: create it with `issues new --title "..." --priority <low|medium|high>`
- **When picking up work**: `issues claim <id>` to mark in-progress
- **When finishing work**: `issues done <id>` to close

### Branch and Claim Rules
- **New issues must be created on main.** Before running `issues new`, checkout main.
  1. create the issue
  2. commit the new issue with an appropriate git message (be sure to include issue number)
- **Starting work on an issue:** ask the user if a dedicated branch should be opened from main. If confirmed:
  1. Checkout main (if not already there)
  2. Create and checkout a new branch named `<issue-number>-<kebab-case-title>` (e.g. `4-add-ec-alerts`)
  3. Only then run `issues claim <id>` — never claim before the branch exists
  4. Begin work by reading the issue - consider the body as the prompt - make plan, ask follow-up questions if needed.


### Key Commands
```bash
git-issues list                        # list all open issues
git-issues next                        # next actionable issue (AI-optimized)
git-issues show <id>                   # full issue details
git-issues new --title "..." --priority high  # create issue
git-issues claim <id>                  # mark in-progress
git-issues done <id>                   # close issue
git-issues relate <id> blocks <id2>    # link dependencies
git-issues graph                       # visualize dependencies
```

### Notes
- Use `--format json` for scripting or parsing output
- Issues live in `.issues/*.md` — commit them with related code changes
- Prefer creating issues for any non-trivial bug, feature, or task before implementing
