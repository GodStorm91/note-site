#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOG_PREFIX="[auto-sync]"

echo "$LOG_PREFIX Starting at $(date)"

# 1) Sync Bear notes (only #publish)
if npm run sync-bear --silent; then
  echo "$LOG_PREFIX sync-bear ok"
else
  echo "$LOG_PREFIX sync-bear FAILED" >&2
  exit 1
fi

# 2) Build Astro into ../docs for GitHub Pages
if npm run build --silent; then
  echo "$LOG_PREFIX build ok"
else
  echo "$LOG_PREFIX build FAILED" >&2
  exit 1
fi

cd "$ROOT_DIR/.."  # go to /Users/khanhnguyen/clawd

# 3) Commit docs if there are changes
if git diff --quiet -- docs; then
  echo "$LOG_PREFIX no changes in docs, nothing to commit"
  exit 0
fi

COMMIT_MSG="Auto update notes $(date +"%Y-%m-%d %H:%M:%S")"

echo "$LOG_PREFIX committing: $COMMIT_MSG"

git add docs
if git commit -m "$COMMIT_MSG"; then
  echo "$LOG_PREFIX commit ok"
else
  echo "$LOG_PREFIX git commit failed" >&2
  exit 1
fi

# 4) Push
if git push; then
  echo "$LOG_PREFIX push ok"
else
  echo "$LOG_PREFIX git push failed" >&2
  exit 1
fi

echo "$LOG_PREFIX done"
