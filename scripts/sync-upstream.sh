#!/bin/bash
#
# sync-upstream.sh -- keep this mcpm.sh fork current with its upstream.
#
# Fetches the upstream remote (pathintegral-institute/mcpm.sh), shows what's incoming,
# and merges (or rebases) it onto a dated integration branch. It NEVER pushes -- per repo
# practice you review, test, then push and open a PR yourself.
#
# Usage:
#   scripts/sync-upstream.sh [--check] [--rebase]
#     --check    Show commits this fork is behind upstream/main, then stop (no changes).
#     --rebase   Integrate with `git rebase` instead of the default `git merge`.

set -e

UPSTREAM_REMOTE="upstream"
UPSTREAM_URL="git@github.com:pathintegral-institute/mcpm.sh.git"
BASE_BRANCH="main"

# Function to display error messages
error_exit() {
  echo "❌ $1"
  exit 1
}

# Function to display status messages
status_message() {
  echo -e "🔄 $1"
}

# --- Parse arguments ---
CHECK_ONLY=0
USE_REBASE=0
for arg in "$@"; do
  case "$arg" in
    --check|--dry-run) CHECK_ONLY=1 ;;
    --rebase) USE_REBASE=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) error_exit "Unknown argument: $arg (try --help)" ;;
  esac
done

# Resolve the repo root so the script works from anywhere.
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || error_exit "Not inside a git repository."
cd "$PROJECT_ROOT"

# --- Ensure the upstream remote exists ---
if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  status_message "Adding '$UPSTREAM_REMOTE' remote ($UPSTREAM_URL)..."
  git remote add "$UPSTREAM_REMOTE" "$UPSTREAM_URL"
fi

# --- Fetch upstream ---
status_message "Fetching $UPSTREAM_REMOTE..."
git fetch --tags "$UPSTREAM_REMOTE" || error_exit "Failed to fetch $UPSTREAM_REMOTE (SSH agent running?)."

UPSTREAM_REF="$UPSTREAM_REMOTE/$BASE_BRANCH"

# --- Show what's incoming ---
BEHIND=$(git rev-list --count "HEAD..$UPSTREAM_REF" 2>/dev/null || echo "0")
if [ "$BEHIND" -eq 0 ]; then
  echo "✅ Already up to date with $UPSTREAM_REF."
  exit 0
fi

echo ""
echo "📥 $BEHIND commit(s) behind $UPSTREAM_REF:"
git log --oneline --reverse "HEAD..$UPSTREAM_REF"
echo ""
git diff --stat "HEAD..$UPSTREAM_REF"
echo ""

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "ℹ️  --check: stopping before integration. Re-run without --check to merge."
  exit 0
fi

# --- Guard: clean working tree ---
if [ -n "$(git status --porcelain)" ]; then
  error_exit "Working tree has uncommitted changes. Commit or stash them first."
fi

# --- Integrate on a dated branch ---
INTEGRATION_BRANCH="sync-upstream-$(date +%Y%m%d)"
status_message "Creating integration branch '$INTEGRATION_BRANCH'..."
git checkout -B "$INTEGRATION_BRANCH"

if [ "$USE_REBASE" -eq 1 ]; then
  status_message "Rebasing onto $UPSTREAM_REF..."
  if ! git rebase "$UPSTREAM_REF"; then
    git rebase --abort || true
    error_exit "Rebase hit conflicts and was aborted. Resolve manually: git rebase $UPSTREAM_REF"
  fi
else
  status_message "Merging $UPSTREAM_REF..."
  if ! git merge --no-edit "$UPSTREAM_REF"; then
    echo "⚠️  Merge has conflicts. Resolve them, then 'git commit'. To bail out: 'git merge --abort'."
    exit 1
  fi
fi

# --- Submodules ---
status_message "Updating submodules..."
git submodule update --init --recursive || echo "⚠️  Submodule update reported issues -- review manually."

if ! git diff --quiet "HEAD..$UPSTREAM_REF" -- .gitmodules 2>/dev/null; then
  echo "⚠️  Upstream changed .gitmodules -- review the fork's submodules (mcpm-mcp / mcpm-sync / mcpm-council)."
fi

echo ""
echo "✅ Integrated $UPSTREAM_REF into '$INTEGRATION_BRANCH'."
echo "   Next: run tests, then 'git push origin $INTEGRATION_BRANCH' and open a PR. (No push was performed.)"
