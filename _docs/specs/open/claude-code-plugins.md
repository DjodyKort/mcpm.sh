# Claude Code plugins in mcpm (`mcpm cc`)

Status: Phase 1 implemented — "pull latest from remote".

## Goal

Claude-Code-only functionality to download, install, maintain, update, and (eventually) sync
Claude Code plugins across devices, integrated into mcpm. This document covers **Phase 1**:
updating from remote. Everything else is deferred (see below).

## Two capabilities, one theme

1. **`mcpm cc update`** — refresh Claude Code marketplace catalogs and update installed
   plugins from their remotes, mirroring `mcpm update` for MCP servers.
2. **Fork self-update** (`scripts/sync-upstream.sh`) — keep this mcpm.sh fork current with its
   `upstream` (pathintegral-institute), so fork work builds on upstream without drift.

## Mechanism (hybrid)

State is **read** from Claude Code's on-disk JSON; every **mutation** goes through the
`claude plugin` CLI. This is deliberate:

- Marketplaces are **not always git clones** — the official one is fetched via GCS (no `.git`),
  so mcpm cannot reliably `git pull` marketplace dirs. `claude plugin marketplace update` is the
  authoritative refresh.
- Editing `known_marketplaces.json` / plugin cache directly risks desyncing Claude Code's
  internal tracking.

### On-disk state read (never written)
- `~/.claude/plugins/known_marketplaces.json` — object keyed by name →
  `{source, installLocation, lastUpdated}`.
- `~/.claude/plugins/<marketplace>/.claude-plugin/marketplace.json` — catalog (plugin entries
  with `version` / `source.sha` / `source.ref`).
- `~/.claude/plugins/blocklist.json` — blocked `plugin@marketplace` ids.
- `~/.claude/settings.json` — `enabledPlugins`, `extraKnownMarketplaces`.
- Resolution honors `CLAUDE_CONFIG_DIR` (note: `ClaudeCodeManager` only handles `~/.claude.json`
  for MCP servers and does NOT honor it — `mcpm.cc.state.claude_root()` does).

### CLI driven (mutations)
- `claude plugin marketplace update [NAME]` — refresh catalogs.
- `claude plugin list --json` — read installed plugins.
- `claude plugin update <plugin>` — apply (requires a Claude Code restart to take effect).

## Code layout
- `src/mcpm/cc/claude_cli.py` — subprocess wrapper (`is_available`, `plugin_list_json`,
  `marketplace_update`, `plugin_update`); honors `MCPM_CLAUDE_BIN`.
- `src/mcpm/cc/state.py` — defensive read-only readers (missing/malformed files → empty).
- `src/mcpm/cc/updater.py` — `CcUpdateCheck` / `CcUpdateApply` / `CcCheckResult`, never-raises.
- `src/mcpm/commands/cc/{update,list}.py` — `mcpm cc update`, `mcpm cc list`.
- `scripts/sync-upstream.sh` — fork self-update.

## Known caveat: update-availability detection is best-effort

`claude plugin list --json` and the catalog don't always expose comparable versions. When a
version can be compared, the plugin shows `current -> latest`; otherwise it's reported as
`version unknown`. `mcpm cc update <plugin>` still works in the unknown case because
`claude plugin update` is idempotent — a bare `mcpm cc update` only auto-applies plugins with a
detected newer version, and prints a hint to name a plugin explicitly otherwise.

## Deferred (later phases)
- `mcpm cc install` / `mcpm cc add-marketplace` (download + install).
- **Cross-device sync** of CC plugin state (`enabledPlugins`, `extraKnownMarketplaces`,
  configured marketplaces) folded into the encrypted `sync push/pull` bundle via
  `SyncConfigManager.get_global_sync_files()` in `plugins/mcpm-sync`. State syncs; per-device
  materialization happens via `claude plugin` CLI on pull.
- MCP tools in `plugins/mcpm-mcp` (`cc_list`, `cc_check_updates`, `cc_apply_update`).
