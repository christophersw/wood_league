# git-issues Workflow

This project uses [`git-issues`](https://github.com/steviee/git-issues) for issue tracking. Issues are Markdown files stored in `.issues/` and committed to git alongside code.

## Workflow
- **Before starting work**: check `issues list` for existing issues or `issues next` for the next actionable one
- **When identifying a bug or task**: create it with `issues new --title "..." --priority <low|medium|high>`
- **When picking up work**: `issues claim <id>` to mark in-progress
- **When finishing work**: `issues done <id>` to close

## Branch and Claim Rules
- **New issues must be created on main.** Before running `issues new`, checkout main.
  1. create the issue
  2. commit the new issue with an appropriate git message (be sure to include issue number)
- **Starting work on an issue:** ask the user if a dedicated branch should be opened from main. If confirmed:
  1. Checkout main (if not already there)
  2. Create and checkout a new branch named `<issue-number>-<kebab-case-title>` (e.g. `4-add-ec-alerts`)
  3. Only then run `issues claim <id>` — never claim before the branch exists
  4. Begin work by reading the issue - consider the body as the prompt - make plan, ask follow-up questions if needed.

## Key Commands
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

## Notes
- Use `--format json` for scripting or parsing output
- Issues live in `.issues/*.md` — commit them with related code changes
- Prefer creating issues for any non-trivial bug, feature, or task before implementing
