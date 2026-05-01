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

Interactive selection — enable the servers you want per client. This writes `mcpm_*` entries to each client's config in **legacy shape** (`{"command": "mcpm", "args": ["run", "<name>"]}`).

### 5. Optional: migrate to direct HTTP / router (recommended)

The default `mcpm run X` shape pipes every MCP request through a per-client `mcpm` Python process. That is fine, but it has two costs:

- HTTP MCP servers with OAuth lose their `WWW-Authenticate` flow because errors get stringified into JSON-RPC. Native client OAuth UX (the "Authenticate" prompt in `/mcp`) goes silent.
- Each connected client spawns its own copy of every server (~145 MB Python per stdio server, per client).

`mcpm client sync` rewrites those entries based on each server's `proxy_mode` so HTTP servers go direct (OAuth restored) and stdio servers can optionally share one worker via the local router.

```bash
# Preview what would change for every installed client
mcpm client sync --dry-run

# Migrate with a rollback companion (recommended for the first run)
mcpm client sync --safe

# Plain migration (also auto-cleans `_legacy_*` companions from a prior --safe run)
mcpm client sync

# Revert everything to mcpm run X
mcpm client sync --legacy

# Limit to one client
mcpm client sync --client cursor
```

`--safe` writes a `_legacy_<name>` companion alongside the new entry so you can roll back per server (rename `_legacy_mcpm_clickup` → `mcpm_clickup` in the client config) without losing other manual edits.

Backups land in `~/.cache/mcpm/migrations/<timestamp>/<client>.json.bak` regardless.

#### Per-server overrides

```bash
mcpm mode <server> <auto|direct|router|legacy|bridge>
```

| Mode    | Effect                                                                                         |
|---------|------------------------------------------------------------------------------------------------|
| `auto`  | Default. HTTP → direct, stdio on HTTP-capable clients → legacy, stdio on stdio-only → bridge   |
| `direct`| Raw command/url in client config. Bypasses mcpm at runtime entirely                            |
| `router`| Stdio servers share one worker via the local router (one `mcpm` per server, not per client)   |
| `legacy`| Original `mcpm run X` shape. Backward-compat escape hatch                                      |
| `bridge`| `mcpm bridge X` stdio shim that pipes to the router. For clients that can't speak HTTP MCP    |

Run `mcpm client sync` after `mcpm mode` to push the new shape into client configs.

#### Inspect / control the router

The router is self-launching (gpg-agent pattern, no launchd / systemd / scheduled task). It boots on first call, idle-shuts-down after 30 min of zero traffic.

```bash
mcpm gateway status     # PID, port, uptime, per-server worker PIDs + RSS
mcpm gateway ps         # quick worker PID list
mcpm gateway logs <X>   # cat the worker log
mcpm gateway tail <X>   # live-tail
mcpm gateway stop       # SIGTERM the router (workers cascade-die)
mcpm gateway restart    # stop + clear state, next call relaunches
mcpm gateway doctor     # tools/list probe per routed server
mcpm gateway doctor --rollback   # auto-revert via `client sync --legacy` if any probe fails
```

### 6. Optional: register mcpm-mcp in clients

Expose mcpm's entity tools (skills/agents/styles/servers) to AI clients so they can list, scaffold, edit and sync via typed tool calls instead of re-deriving the sync architecture each session.

```bash
mcpm mcp install claude-code
mcpm mcp install claude-desktop
mcpm mcp tools             # list exposed tools
mcpm mcp doctor            # sanity check
```

Mutating tools require explicit `confirm=true`. See `plugins/mcpm-mcp/README.md` for the full tool matrix.

### 7. Optional: git-sync for direct skill editing

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
mcpm skills sync           # if skills changed
mcpm client sync           # if servers.json changed (re-emits each client's mcpm_* entries)

# Check what would change before pulling/syncing
mcpm sync diff             # cross-machine bundle diff
mcpm client sync --dry-run # per-client config diff
```

### When you add a new MCP server

```bash
mcpm install <name>        # registers in servers.json (proxy_mode=auto)
mcpm client edit <client>  # interactive: enable in one client
mcpm client sync           # OR: re-emit all clients in one go
mcpm sync push             # share with other machines
```

### When OAuth on an HTTP server stops prompting in `/mcp`

That usually means the entry got reverted to `mcpm run X` somewhere. Verify and re-migrate:

```bash
mcpm client sync --dry-run               # see what's in legacy shape
mcpm client sync --safe                  # rewrite + keep rollback companions
# restart the client, test OAuth
mcpm gateway doctor                      # if a stdio server starts misbehaving
mcpm gateway doctor --rollback           # auto-revert if anything is broken
```
