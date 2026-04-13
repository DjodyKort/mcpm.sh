# Claude Project Conventions

This file contains conventions that Claude should follow when working on this project.

## Upstream Conventions (preserved)

- **Dependency Management:** Use `uv` for all Python dependency management.
- **Python Environment:** You are in the uv `.venv` Python environment. All dependency code can be found in `.venv/`.
- **Formatting:** Always format Python code with `ruff` (line-length 120, rules: E, F, W, Q, I).
- **Committing:**
  - NEVER commit anything to git unless explicitly asked to do so.
  - Always double-check with the user before committing changes to git.
  - This project follows semantic release — commit messages MUST follow Conventional Commits format.
  - Examples: `feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `perf:`, `test:`, `chore:`
  - BREAKING CHANGES: Adding `BREAKING CHANGE:` in the commit footer triggers a major release. This is very uncommon — NEVER do this unless explicitly told to do so.

## Fork Context

This is a fork of `pathintegral-institute/mcpm.sh` (MIT license). We are adding the `mcpm update` command on the `feat/update-command` branch.

- **Upstream remote:** `upstream` → `github.com/pathintegral-institute/mcpm.sh`
- **Fork remote:** `origin` → `github.com/DjodyKort/mcpm.sh`
- **Goal:** Build the feature for our own use first, optionally contribute upstream later.

## Architecture Quick Reference

| Component | Path | Purpose |
|-----------|------|---------|
| CLI entry point | `src/mcpm/cli.py` | Click group, command registration |
| Commands | `src/mcpm/commands/*.py` | One file per command (Click commands) |
| Data models | `src/mcpm/core/schema.py` | Pydantic: `STDIOServerConfig`, `RemoteServerConfig`, `ServerConfig` union |
| Global config | `src/mcpm/global_config.py` | `GlobalConfigManager` — server CRUD, profiles, persistence |
| Registry | `src/mcpm/utils/repository.py` | `RepositoryManager` — fetches/caches `servers.json` from mcpm.sh API |
| Client integration | `src/mcpm/clients/` | Manages configs for Claude Code, Cursor, etc. |
| Server metadata | `~/.mcpm/servers/<name>/metadata.json` | Per-server metadata saved at install time |
| Global server config | `~/.mcpm/servers.json` | All server configs (command/args/env) |

### Adding a new command

1. Create `src/mcpm/commands/<name>.py` with a `@click.command()` function
2. Import and register in `src/mcpm/cli.py` via `main.add_command()`
3. Use `GlobalConfigManager` to read/write server configs
4. Use `Console()` for Rich output, `Console(stderr=True)` for errors
5. Support `MCPM_NON_INTERACTIVE=true` for non-interactive usage

## Specs

Feature specs live in `_docs/specs/`:
- `open/` — proposed, not yet started
- `in_progress/` — actively being built
- `done/` — completed and merged

Read the relevant spec before implementing. Update spec status when starting/finishing work.

## Testing

- Tests in `tests/` using pytest
- Run: `uv run pytest`
- Async tests use `pytest-asyncio`
