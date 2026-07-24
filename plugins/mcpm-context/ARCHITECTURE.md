# mcpm-context — architecture & ownership contract

Layered Claude context + full `CLAUDE_CONFIG_DIR` profiles, designed to coexist
with cf-dev-tools (the Codeforward org tool) **without either side fighting the
other**. Everything here was validated against cf-dev-tools' live install
(`~/.local/share/cf-dev-tools`, origin/main) before building.

## Ownership contract

| Asset | Owner | Notes |
|---|---|---|
| `~/.claude/CLAUDE.md` | **cf-dev-tools** | Verbatim overwrite every 4h (shell-wrapper) + on `sync-claude`. We never write it. |
| `~/.claude/settings.json` team keys (`permissions.allow` team list, `attribution`) | **cf-dev-tools** | Its `jq -s '.[0] * .[1]'` merge replaces arrays wholesale. |
| `~/.claude/settings.json` policy entries | **mcpm-context** | `ensure_allow`/`ensure_ask` re-unioned on every `sync` (additive only; team entries never removed). |
| `~/.claude/commands/*.md` (5 org files) | **cf-dev-tools** | Copy-only sync; never deletes extras. |
| `~/.claude/rules/` | **mcpm skills pipeline** | cf-dev-tools has zero code touching it (verified `claude.py:59-113`). This is where the personal + per-client layers live. |
| `~/.claude.json` → `mcpServers` | **mcpm** (`mcpm_*` entries) | cf's legacy bare-name entries are deduped by us when an `mcpm_<name>` twin exists. |
| `~/.config/mcpm/context.json` | **mcpm-context** | Policy file; carried in the mcpm-sync encrypted bundle. |
| `~/.config/mcpm/claude-profiles/<name>/` | **mcpm-context** | Fully generated; safe to delete; `sync` regenerates. |
| `~/.config/mcpm/context-shims.zsh` | **mcpm-context** | One `claude-<name>()` function per profile. |

## Layers (default profile)

The default `claude` stays exactly as cf-dev-tools ships it. Personal and
per-client context ride Claude Code's native **user-level rules**:

```
skills_repo/rules/personal/SKILL.md          (activation: always)
skills_repo/rules/client-<slug>/SKILL.md     (activation: always, globs: "**/clients/<dir>/**")
        │  mcpm skills sync --global --client claude-code
        ▼
~/.claude/rules/personal.md                  (always-on)
~/.claude/rules/client-<slug>.md             (paths: ["**/clients/<dir>/**"])
```

Because cf-dev-tools never touches `rules/`, layers survive every org sync with
no markers, no recompose, no wrapper.

### Per-client scoping — two mechanisms (both required)

Empirically settled (Claude Code 2.1.202): rule `paths:` globs match
**project-root-relative file paths** — not the launch cwd, not absolute paths.
Consequences:

- **Session rooted above the client** (e.g. the ODH root): the rule's
  `paths: ["**/clients/<dir>/**"]` activates when a matching file is read. ✓
- **Session rooted inside the client repo**: every file path is relative to the
  client repo itself (`xx_module/…`), so no glob can discriminate between
  clients. For this case `mcpm context sync` **deploys the layer body as
  `<client>/CLAUDE.local.md`** (native personal project memory, loaded at
  session start) and registers it in `.git/info/exclude` (local ignore — never
  committed, invisible to colleagues). Existing unmanaged `CLAUDE.local.md`
  files are left alone.

Format notes (empirically settled):
- mcpm's `SkillFrontmatter.globs` is a **comma-separated string** (Cursor
  convention), not a YAML list.
- The claude-code transpiler renders it as a YAML flow list
  (`paths: ["**/clients/x/**"]`) — Claude Code's documented rules format
  (scalar `paths:` strings and absolute globs do not match).
- Skill names allow only `[a-z0-9-]`; client dir names may contain underscores
  (`v18_arp`) → the rule name is slugged (`client-v18-arp`), the glob keeps the
  raw dir name, and the CLAUDE.local.md deploy matches client dirs by slug.

## Profiles

A profile is a generated stand-in for `~/.claude`:

| Piece | Mechanism |
|---|---|
| `CLAUDE.md` | `org: true` + `org_mode: import` → one `@~/.claude/CLAUDE.md` line (always fresh; one-time approval dialog per project). `org_mode: copy` inlines at sync time (no dialogs, fresh until next `sync`). `org: false` → bare. |
| `rules/` | `inherit` → dir symlink to `~/.claude/rules` · `none` · explicit list → per-file symlinks (`link_rules: false` → copies) |
| `commands/`, `skills/`, `agents/` | dir symlinks into `~/.claude` (shared, stay fresh) |
| `settings.json` | composed **copy** (symlink would let cf's jq merge write through): base ∪ profile-accumulated ∪ `settings_overrides` (arrays = ordered union). Base hash tracked for doctor staleness. |
| `.claude.json` | merged in place: identity keys (`oauthAccount`, `userID` — gated by `copy_auth`) + onboarding flags + `mcpServers` (`inherit` = mirror minus legacy · list = shaped via `ClaudeCodeManager(config_path_override=…).to_client_format()` · `none`). Claude Code's own accumulated state is preserved. |
| shim | `claude-<name>() { _mcpm_context_presync; CLAUDE_CONFIG_DIR="<dir>" command claude "$@"; }` — `command claude` prevents wrapper recursion. |

### Auth: one-time /login per profile (empirical, Claude Code 2.1.202 / macOS)

Setting `CLAUDE_CONFIG_DIR` to **any** value — even `~/.claude` itself —
changes the credential lookup: the session reports "Not logged in" until a
one-time `/login` in that profile. The Keychain holds `Claude Code-credentials`
for the default dir only. Copying `oauthAccount`/`userID` into the profile's
`.claude.json` does NOT transfer auth (those are display/state fields). So:
**first launch of each new profile → `/login` once.**

## Freshness wrapper (default on: `wrap_default_claude`)

"Codeforward mode" = the default `claude`: org CLAUDE.md (cf-synced) + personal
and client layers (rules). To keep that mode *and* the union-restores fresh
automatically, the shims file replaces the default `claude()` — and
`hrclaude()` when the compression shims define it — with a superset of
cf-dev-tools' own wrapper:

```
_mcpm_context_presync:
  1. cf org sync   — cf's exact python entry points (sync_claude_files +
                     auto_update_mcp_repos), cf's own throttle cache
                     (~/.claude/.last_auto_sync, CLAUDE_SYNC_INTERVAL)
  2. context sync  — immediately after a cf run (so a permissions clobber is
                     repaired in the same launch beat), else own 4h throttle
```

Verified live: cf clobber (allow 95→4) + one wrapped `claude --version` →
allow back to 95 in the same invocation.

Notes:
- `hrclaude` calls `mcpm compression run`, which spawns the claude *binary* —
  it never passed through cf's shell function, so wrapping it actually adds
  org-sync freshness that daily `hrclaude` use previously missed.
- The hrclaude override is conditional (`$+functions[hrclaude]`) — absent
  compression shims, no broken function is defined.
- Source-order contract: context-shims.zsh must be sourced AFTER cf's
  shell-wrapper.sh and compression-shims.zsh (function redefinition wins by
  order). Doctor checks this.
- The copied cf sync logic is the client-side stand-in for the proposed
  upstream post-sync hook (see `_docs/specs/open/cf-dev-tools-upstream-proposal.md`);
  the cf-wrapper hash tripwire guards the copy against upstream drift.
- Escape hatch: `wrap_default_claude: false` in context.json → dumb
  profile-only shims, default `claude` stays 100% cf's.

## Dedupe & settings-union (coexistence repairs)

- **Dedupe**: cf's `sync-claude` registers `context7`/`playwright` (and
  interactively `codeforward-odoo`/`codeforward-typst`) under bare names via
  `claude mcp add`. Only the *manual* path does this — the 4-hourly auto-sync
  never touches `mcpServers` (verified: `shell-wrapper.sh` calls
  `sync_claude_files` + `auto_update_mcp_repos` only). We remove a bare entry
  only when its `mcpm_<name>` twin exists, with a timestamped backup under
  `~/.cache/mcpm/context/backups/`.
- **Settings-union**: policy entries live in `context.json`; `sync` re-adds
  them after any cf clobber. `init` migrates `~/.claude/settings.local.json`
  allow-entries here (user-level settings.local.json is unsupported by Claude
  Code — docs FAQ), refusing credential-embedding entries.

## Doctor tripwires (cf drift)

cf-dev-tools has no extension points, so we defend with detection:

- sha256 baseline of cf's `claude/shell-wrapper.sh` — a change warns to
  re-verify the coexistence assumptions.
- The known set of cf-synced assets (`CLAUDE.md`, `CLAUDE.uncompressed.md`,
  `settings.json`, `shell-wrapper.sh`, `commands`) — new files in its `claude/`
  source dir (e.g. a future `rules/`) warn about scope expansion.

## Strip path

`mcpm context disable` removes the shims; `--purge-profiles` also removes the
generated profile dirs. `~/.claude`, `~/.claude.json`, layer rules, and
`context.json` are never touched by disable. Deployed `CLAUDE.local.md` files
in client repos are inert managed artifacts — delete manually if unwanted
(identifiable by their managed header). `sync` reconverges from policy.

## Sync

`context.json` is registered in mcpm-sync's `get_global_sync_files()`
(like `compression.json`). Layer content rides the existing `skills_repo/rules/`
walk. Generated profile dirs are not synced — they're machine-local artifacts.
