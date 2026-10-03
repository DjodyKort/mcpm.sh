#!/usr/bin/env bash
# Update this mcpm fork to the latest of the CURRENT branch and reinstall it with its plugins.
#
# Why not just `git pull`? mcpm is an editable install, so code changes go live on pull,
# but dependency changes (including a newly declared plugin) only land on reinstall.
# Plugins are declared dependencies with editable path sources in pyproject.toml, so the
# one `uv tool install` below always brings every plugin along.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

branch="$(git rev-parse --abbrev-ref HEAD)"
echo "==> mcpm fork update — branch: ${branch}"

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "    working tree has uncommitted changes; pulling --ff-only so nothing is clobbered"
fi

git pull --ff-only
git submodule update --init --recursive

echo "==> reinstalling mcpm + plugins (editable)"
uv tool install --force --editable .

echo "==> done"
mcpm doctor 2>&1 | grep -E "MCPM version|Plugin|plugins/|Reinstall" || true
