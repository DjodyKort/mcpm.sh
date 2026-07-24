#!/usr/bin/env bash
# Update this mcpm fork to the latest of the CURRENT branch and re-register all plugins.
#
# Why not just `git pull`? mcpm is an editable install, so code changes to packages that
# are ALREADY installed go live on pull. But a newly added plugin only exposes its command
# after it is (re)installed into mcpm's venv — a plain pull leaves it missing
# (`mcpm <cmd>` -> "No such command"). This script globs plugins/*/ so new plugins register
# automatically and empty/uninitialized submodules are skipped.
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

echo "==> reinstalling core (editable)"
uv tool install --force --editable .

mcpm_python="$(uv tool dir)/mcpm/bin/python"
echo "==> registering plugins under plugins/*/"
for plugin in plugins/*/; do
    if [ -f "${plugin}pyproject.toml" ]; then
        echo "    + ${plugin}"
        uv pip install --python "$mcpm_python" -e "$plugin"
    else
        echo "    - ${plugin} (skipped: no pyproject — empty/uninitialized submodule)"
    fi
done

echo "==> done"
mcpm --version 2>&1 | grep -iE "v[0-9]" || true
