# Development Setup

Install mcpm from this fork with skills, agents, styles, and sync support.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Git

## macOS / Linux

```bash
# Clone
git clone git@github.com:DjodyKort/mcpm.sh.git
cd mcpm.sh
git checkout feat/skill-sync-system
git submodule update --init --recursive

# Install mcpm (editable — changes take effect immediately)
uv tool install --force --editable .

# Install sync plugin
uv pip install --python "$(uv tool dir)/mcpm/bin/python" -e plugins/mcpm-sync

# Verify
mcpm --version
mcpm skills ls
mcpm sync --help
```

## Windows (PowerShell)

```powershell
# Clone
git clone git@github.com:DjodyKort/mcpm.sh.git
cd mcpm.sh
git checkout feat/skill-sync-system
git submodule update --init --recursive

# Install mcpm (editable)
uv tool install --force --editable .

# Find the mcpm Python path (which doesn't exist on Windows)
$mcpmPython = Join-Path (uv tool dir) "mcpm\Scripts\python.exe"

# Install sync plugin
uv pip install --python $mcpmPython -e plugins/mcpm-sync

# Verify
mcpm --version
mcpm skills ls
mcpm sync --help
```

## Pull configs and skills on a new machine

```bash
# Configure skills repo sync
mcpm sync git-sync --repo git@github.com:DjodyKort/ai-skills.git --auto

# Pull MCP server configs + skills from sync repo
mcpm sync pull

# Servers are auto-resolved:
# - git repos: cloned + setup command run
# - github-release binaries: downloaded
# - npx/remote: ready immediately
```

## Update

Since mcpm is editable-installed, pulling new code is enough:

```bash
cd mcpm.sh
git pull origin feat/skill-sync-system
git submodule update --recursive
```

No reinstall needed — changes are live immediately.
