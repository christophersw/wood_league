#!/usr/bin/env bash
# Title: build_tailwind.sh — Canonical Tailwind CSS rebuild
#
# Description:
#   Recompiles the served stylesheet from its authoring source:
#     static/css/main.css   (source, Tailwind v4 `@import "tailwindcss";`)
#       -> static/css/tailwind.css   (committed, linked by base.html)
#
#   Nothing in the Railway deploy recompiles this file, so it is a
#   committed artifact that MUST be regenerated whenever main.css (or
#   any template that uses a Tailwind utility) changes. Running this
#   script is the ONLY supported way to produce tailwind.css; CI runs
#   the same script and fails if the result differs from what is
#   committed (issue #140 — a stale tailwind.css shipped the worker
#   dashboard with every component class missing).
#
#   Tailwind v4 resolves `@import "tailwindcss"` relative to the
#   source file, so the `tailwindcss` package must exist under
#   services/app/node_modules. Deps are pinned by package.json and
#   locked by package-lock.json (both committed); this script runs
#   `npm ci` to reproduce that exact tree, so the compiled output is
#   byte-reproducible across machines and CI. node_modules itself is
#   gitignored and Railway (Python/RAILPACK builder) never installs
#   it. To upgrade Tailwind, bump package.json, run `npm install`,
#   rerun this script, and commit package-lock.json + tailwind.css
#   together.
#
# Usage:
#   services/app/bin/build_tailwind.sh
#
# Changelog:
#   2026-05-17 (#140): Initial creation. Pinned tailwindcss /
#               @tailwindcss/cli 4.3.0 via package.json + lockfile.
set -euo pipefail

# Resolve services/app regardless of caller's working directory
# (this script lives in services/app/bin/).
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
app_dir="$(cd "${script_dir}/.." && pwd)"
cd "${app_dir}"

input="static/css/main.css"
output="static/css/tailwind.css"

if [ ! -f "${input}" ]; then
  echo "error: ${input} not found (run from a checkout of the repo)" >&2
  exit 1
fi

# Reproduce the exact, pinned dependency tree from package-lock.json.
# `npm ci` is deterministic (fails if lockfile is out of sync) and
# does not mutate package-lock.json — required for the CI guard's
# byte-for-byte diff to be meaningful.
echo "Installing pinned CSS toolchain (npm ci)…"
npm ci --no-audit --no-fund

echo "Rebuilding ${output} from ${input}…"
npm run build:css

echo "Done: ${output}"
