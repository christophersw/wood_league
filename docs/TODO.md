# Post-Migration Manual TODOs

These steps could not be automated and require manual action.

---

## 1. Configure Railway Dashboard

For each Railway service, set the Root Directory and Watch Paths so Railway only redeploys when relevant files change.

**App service:**
- Settings → Source → Root Directory: `services/app`
- Watch Paths: `services/app/**`, `packages/shared/**`

**Dispatchers service:**
- Settings → Source → Root Directory: `services/dispatchers`
- Watch Paths: `services/dispatchers/**`, `packages/shared/**`

After updating, trigger a test deployment for each service and verify health checks pass.

---

## 2. Install git-issue and Initialize Issue Tracker

`git-issue` is not currently installed. Install it, then initialize the tracker at the monorepo root.

```bash
# Install (Homebrew)
brew install git-issue

# Initialize at repo root
cd /Users/christopherwebster/Projects/wood_league
git issue init

# Copy config from the old app repo
cp services/app/.issues/.config.yml .issues/.config.yml

# Commit the tracker
git add .issues/
git commit -m "chore: initialize git-issue tracker"
git push origin main
```

---

## 3. Archive the Old Repos

Once the monorepo has been live for at least one successful deployment cycle, archive the four old repos.

**Step 1:** Push a deprecation notice to each old repo's README:

```markdown
# ⚠️ Archived

This repo has been merged into the Wood League monorepo:
https://github.com/christophersw/wood_league

This repo is archived and no longer maintained.
```

**Step 2:** Archive each repo on GitHub (Settings → Danger Zone → Archive this repository):

- https://github.com/christophersw/wood_league_app
- https://github.com/christophersw/wood_league_dispatchers
- https://github.com/christophersw/wood_league_stockfish_runpod
- https://github.com/christophersw/wood_league_lc0_runpod
