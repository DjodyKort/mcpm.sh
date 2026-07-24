# mcpm-context

Layered Claude context + full `CLAUDE_CONFIG_DIR` profiles, coexisting with the
org-managed `~/.claude/CLAUDE.md` (cf-dev-tools).

- **Personal layer** — `rules/personal` in the canonical skills repo →
  `~/.claude/rules/personal.md`. Survives every org sync (cf-dev-tools never
  touches `rules/`).
- **Per-client layers** — `mcpm context client add <name>` scaffolds a
  path-scoped rule (`globs: ["**/clients/<name>/**"]`).
- **Profiles** — `mcpm context profile add bare --no-org --rules none --servers none`
  generates `~/.config/mcpm/claude-profiles/bare/` + a `claude-bare` shell shim.
  (First launch of each profile needs a one-time `/login`.)
- **Freshness wrapper** — the shims replace the default `claude()` (and
  `hrclaude()`) with a superset of cf-dev-tools' auto-sync: org sync + context
  sync in one throttle, so personal permissions are restored in the same beat
  cf clobbers them. Default `claude` = "codeforward mode" (org + your layers);
  `claude-bare` = clean escape hatch.
- **MCP dedupe** — removes cf-dev-tools' legacy `context7`/`playwright` entries
  when their `mcpm_*` twins exist.
- **Settings union** — re-adds policy-declared `permissions.allow`/`ask` entries
  after cf-dev-tools' array-clobbering jq merge.

```bash
mcpm context init        # scaffold personal layer, migrate stray settings
mcpm context sync        # apply: dedupe → settings → profiles → shims
mcpm context doctor      # drift/staleness checks incl. cf-dev-tools tripwire
mcpm context disable     # strip generated artifacts
```

Shell activation (one line in `~/.zshrc`):

```zsh
source ~/.config/mcpm/context-shims.zsh
```

See `ARCHITECTURE.md` for the ownership contract with cf-dev-tools.
