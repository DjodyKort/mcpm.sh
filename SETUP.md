# Development Setup

Install mcpm from this fork with skills, agents, styles, and sync support.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Git
- SSH key configured for GitHub

## macOS / Linux

```bash
# Clone
git clone git@github.com:DjodyKort/mcpm.sh.git
cd mcpm.sh
git checkout feat/skill-sync-system
git submodule update --init --recursive

# Install mcpm (editable — changes take effect immediately)
uv tool install --force --editable .

# Install plugins into mcpm's environment
mcpmPython="$(uv tool dir)/mcpm/bin/python"
uv pip install --python "$mcpmPython" -e plugins/mcpm-sync
uv pip install --python "$mcpmPython" -e plugins/mcpm-mcp

# Verify
mcpm --version
mcpm skills ls
mcpm sync --help
mcpm mcp doctor
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

# Install plugins into mcpm's environment
$mcpmPython = Join-Path (uv tool dir) "mcpm\Scripts\python.exe"
uv pip install --python $mcpmPython -e plugins/mcpm-sync
uv pip install --python $mcpmPython -e plugins/mcpm-mcp

# Verify
mcpm --version
mcpm skills ls
mcpm sync --help
mcpm mcp doctor
```

### Windows: "Access is denied" on `uv tool install`

On Windows, `uv tool install --force` can fail with:

```
error: failed to remove directory `...\uv\tools\mcpm\Scripts`: Access is denied. (os error 5)
```

This means another process is holding `mcpm.exe` or a DLL open — typically MCP servers spawned by Claude Code, Claude Desktop, or another shell running `mcpm run ...`.

Find and stop them before retrying:

```powershell
# List holding processes
Get-Process | Where-Object { $_.Path -like "*\uv\tools\mcpm\*" } |
    Format-Table Id, ProcessName, Path -AutoSize

# Kill them all
Get-Process | Where-Object { $_.Path -like "*\uv\tools\mcpm\*" } | Stop-Process -Force

# Retry
uv tool install --force --editable .
```

Clients that had MCP servers running (Claude Code/Desktop) will respawn them on next use.

## New machine setup

After installing mcpm + sync plugin, run these steps to pull everything down.

### 1. Initialize sync

```bash
mcpm sync init --backend git --repo git@github.com:DjodyKort/mcpm-sync-data.git
```

You will be prompted for a passphrase. Use the **same passphrase** as the machine that pushed — it derives the decryption key.

### 2. Pull configs + resolve servers

```bash
mcpm sync pull
```

This decrypts and restores:

| What                   | Detail                                                |
|------------------------|-------------------------------------------------------|
| `servers.json`         | 13 MCP server configs (commands, args, env vars / API keys) |
| `sources.json`         | Origin metadata per server (git URL, setup command, etc.)   |
| `server_origins.json`  | Auto-detected install info for the resolver                 |
| `skills_repo/`         | 5 skills, 1 profile, manifest                               |

And auto-resolves servers:

| Type             | Servers                                                        | Action                                                    |
|------------------|----------------------------------------------------------------|-----------------------------------------------------------|
| git              | codeforward-odoo, codeforward-typst, moodle-mcp, scihub, google-docs-mcp | Clone + run setup (`uv sync` / `npm install && npm run build`) |
| github-release   | anna-mcp                                                       | Download binary                                           |
| npx              | context7, playwright, drawio, stitch                           | Ready (npx fetches on first run)                          |
| remote           | figma, balsamiq, clickup                                       | Ready (HTTP endpoints)                                    |

### 3. Transpile skills to clients

```bash
mcpm skills sync
```

Writes skills from `~/.config/mcpm/skills_repo/skills/` to each client's native format (e.g. `~/.claude/skills/`).

### 4. Deploy servers to clients

```bash
mcpm client edit claude-desktop
mcpm client edit claude-code
```

Interactive selection — enable the servers you want per client. This writes `mcpm_*` entries (using `mcpm run <name>`) to each client's config.

### 5. Optional: register mcpm-mcp in clients

Expose mcpm's entity tools (skills/agents/styles/servers) to AI clients so they can list, scaffold, edit and sync via typed tool calls instead of re-deriving the sync architecture each session.

```bash
mcpm mcp install claude-code
mcpm mcp install claude-desktop
mcpm mcp tools             # list exposed tools
mcpm mcp doctor            # sanity check
```

Mutating tools require explicit `confirm=true`. See `plugins/mcpm-mcp/README.md` for the full tool matrix.

### 6. Optional: git-sync for direct skill editing

```bash
mcpm sync git-sync --repo git@github.com:DjodyKort/ai-skills.git --auto
```

With `--auto`, every `mcpm sync push/pull` also pulls the latest skills from this git repo. Useful for editing skills directly via git instead of only through the encrypted sync bundle.

## What is NOT covered by mcpm sync

| What                                      | Where              | How to get it                                                                     |
|-------------------------------------------|--------------------|-----------------------------------------------------------------------------------|
| Claude commands (`~/.claude/commands/`)   | cf-dev-tools       | `source ~/.claude/shell-wrapper.sh` triggers auto-sync                            |
| Global `CLAUDE.md`                        | cf-dev-tools       | Same as above                                                                     |
| `settings.json` / `settings.local.json`  | Claude Code config | cf-dev-tools syncs `settings.json`; `settings.local.json` is machine-specific     |
| Cloud MCPs (Gmail, Slack, Calendar, etc.) | claude.ai managed  | Re-authorize in Claude settings                                                   |
| Agents & styles                           | Not yet created    | `mcpm agents add` / `mcpm styles add` when needed                                |

## Update

Since mcpm is editable-installed, pulling new code is enough:

```bash
cd mcpm.sh
git pull origin feat/skill-sync-system
git submodule update --recursive
```

No reinstall needed — changes are live immediately.

## Daily workflow

```bash
# After changing server configs or skills locally
mcpm sync push

# On another machine
mcpm sync pull
mcpm skills sync    # if skills changed

# Check what would change before pulling
mcpm sync diff
```
