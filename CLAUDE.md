# Claude Project Conventions

Canonical `SKILL.md` files (YAML frontmatter + Markdown body) are transpiled to each client's native instruction format. Skills use progressive disclosure; rules (`activation: always`) are injected directly.

- `src/mcpm/skills/schema.py` — Pydantic models: `SkillFrontmatter`, `SkillConfig`, `TranspileResult`, `LockFile`
- `src/mcpm/skills/parser.py` — Parses SKILL.md (YAML frontmatter + body), discovers skills in a repo
- `src/mcpm/skills/transpiler.py` — `BaseSkillTranspiler` ABC + transpiler registry + `sync_skills()` orchestration
- `src/mcpm/skills/transpilers/` — 15 client transpilers + `agents_md.py` (AGENTS.md generation)
- `src/mcpm/skills/config.py` — `SkillsConfigManager`: lockfile, manifest, scaffolding
- `src/mcpm/skills/lint.py` — Format validation + best-practice checks
- `src/mcpm/skills/audit.py` — Security scan for prompt injection, data exfiltration
- `src/mcpm/skills/taps.py` — Homebrew-style tap system for remote skill repos
- `src/mcpm/skills/bundle.py`, `sync_git.py`, `registry.py`, `router.py`, `analytics.py` — Distribution, git sync, registry schema, MCP resource exposure, usage tracking

**Transpiler pattern** (shared across skills/agents/styles): Each transpiler subclass sets `client_key`/`display_name`, implements `transpile()` and `get_output_path()`. Transpilers register into a dict registry. The orchestration function iterates registered transpilers, calls `transpile()`, writes output files, and updates the lockfile. Append-mode clients (Zed, Aider) use `<!-- mcpm:start/end -->` delimiters.

**Activation mode downgrade**: When a client doesn't support the requested mode (always/auto/agent/manual), the transpiler downgrades toward "more visible" (manual → agent → auto → always) so skills never silently disappear.

### 3. Agents Sync (6 clients)

`AGENT.md` files define reusable AI personas (model, tools, permissions, system prompt). Simpler than skills -- no activation modes or globs.

- `src/mcpm/skills/agents/` — `schema.py`, `parser.py`, `transpiler.py`, `lint.py`
- `src/mcpm/skills/agents/transpilers/` — 6 clients: claude_code, cursor, codex_cli, gemini_cli, vscode_copilot, roo_code
- Roo Code uses `.roomodes` JSON (append-mode: all agents merged into one file)

### 4. Output Styles (15 clients, two-tier)

`STYLE.md` files control HOW the AI responds (tone, verbosity, persona). Styles are toggleable and mutually exclusive.

- `src/mcpm/styles/` — `schema.py`, `parser.py`, `transpiler.py`, `lint.py`
- `src/mcpm/styles/transpilers/` — 15 clients
- **Tier 1** (native toggle): Claude Code (`.claude/output-styles/`) and Roo Code (`.roomodes` with `style-` prefix). `sync` writes all styles; user toggles in UI.
- **Tier 2** (apply/remove): All other clients. `apply` injects one style as an always-on rule at a fixed `mcpm-output-style` path. `remove` deletes it.

### CLI Structure

Entry point: `src/mcpm/cli.py` → Click group `main` with subcommand groups: `skills`, `agents`, `styles`, `profile`, `client` + top-level commands. Plugins load via `importlib.metadata.entry_points(group="mcpm.plugins")`.

Commands live in `src/mcpm/commands/` — each subcommand group has its own package (e.g., `commands/skills/sync.py`).

### Key Conventions

- **YAML frontmatter parsing**: All three entity types (skills/agents/styles) use the same pattern: regex-split `---` blocks, parse YAML, normalize hyphenated keys to underscores (e.g., `allowed-tools` → `allowed_tools`)
- **Lockfile tracking**: `mcpm-skills.lock` records SHA256 hashes, synced clients, and warnings per entity. Enables drift detection.
- **Pydantic v2**: All schemas use Pydantic BaseModel with custom validators (name regex: lowercase + hyphens, 1-64 chars)
- **Rich console output**: `Console()` for stdout, `Console(stderr=True)` for errors/tracebacks
- **Non-interactive mode**: `MCPM_NON_INTERACTIVE=true`, `MCPM_FORCE=true`, `MCPM_JSON_OUTPUT=true` env vars

## Specs & Docs

- `_docs/specs/open/skills-sync.md` — Comprehensive spec: field mapping tables, activation modes, client constraints, competitive landscape, design decisions
- `_docs/specs/open/claude-desktop-skills.md` — Claude Desktop skills investigation (filesystem injection failed, API blocked — org-scoped not per-user)
- `_docs/skills-usage-guide.md` — Day-to-day usage guide for skills, agents, and styles
- `examples/skills-repo/` — Example repo with sample skills, rules, agents, styles, and profiles
