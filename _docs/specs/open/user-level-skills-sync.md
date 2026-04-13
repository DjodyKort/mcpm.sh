# User-Level Skills Sync (`--global` flag)

**Task:** Add `--global` flag to skills/agents/styles sync
**Type:** Feature
**Scope:** `src/mcpm/skills/transpiler.py`, all transpilers, `src/mcpm/commands/skills/sync.py`
**Priority:** Medium — blocks seamless user-level skills repos

---

## Status

| Phase | Status |
|-------|--------|
| 1. Analysis | Done |
| 2. Specification | Done |
| 3. Implementation | Not started |
| 4. Tests | Not started |

---

## Problem

`mcpm skills sync` writes transpiled output relative to the skills repo root:

```
~/Documents/GitHub/ai-skills/.claude/skills/explain-flow/SKILL.md
```

But Claude Code reads **user-level** skills from `~/.claude/skills/`. Same for other clients — Cursor reads user-level rules from `~/.cursor/rules/`, not from the repo directory.

Currently the only workaround is a manual symlink:
```bash
ln -s ~/Documents/GitHub/ai-skills/.claude/skills ~/.claude/skills
```

This breaks the promise of "write once, sync everywhere" because the user must manually wire up each client's user-level path.

## Prior Decision

The skills-sync spec (line 835) states:
> Project-level by default (matching most clients). `--global` flag not implemented yet.

This spec implements the deferred `--global` flag.

## Solution

### User-facing change

```bash
# Project-level (current behavior, unchanged)
mcpm skills sync

# User-level — writes to each client's home config path
mcpm skills sync --global
```

Same for agents and styles:
```bash
mcpm agents sync --global
mcpm styles sync --global
```

### How it works

Each transpiler already has `get_output_path(skill, project_root)`. Add a sibling method:

```python
def get_user_output_path(self, skill: SkillConfig) -> Path:
    """Return the user-level output path for this client."""
```

Per client, this returns the home-directory equivalent:

| Client | Project-level | User-level |
|--------|--------------|------------|
| Claude Code (skill) | `<root>/.claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` |
| Claude Code (rule) | `<root>/.claude/rules/<name>.md` | `~/.claude/rules/<name>.md` |
| Cursor | `<root>/.cursor/rules/<name>/RULE.md` | `~/.cursor/rules/<name>/RULE.md` |
| VS Code Copilot | `<root>/.github/skills/<name>/SKILL.md` | N/A (project-only) |
| Windsurf | `<root>/.windsurf/rules/<name>.md` | `~/.windsurf/rules/<name>.md` |
| Continue | `<root>/.continue/rules/<name>.md` | `~/.continue/rules/<name>.md` |
| Cline | `<root>/.clinerules/<name>.md` | `~/.clinerules/<name>.md` |
| JetBrains AI | `<root>/.aiassistant/rules/<name>.md` | `~/.aiassistant/rules/<name>.md` |
| Gemini CLI | `<root>/.gemini/skills/<name>/SKILL.md` | `~/.gemini/skills/<name>/SKILL.md` |
| Codex CLI | `<root>/.agents/skills/<name>/SKILL.md` | `~/.agents/skills/<name>/SKILL.md` |
| Zed | `<root>/.rules` | N/A (project-only) |
| AGENTS.md | `<root>/AGENTS.md` | N/A (project-only) |

Some clients are project-only (VS Code Copilot, Zed, AGENTS.md). When `--global` is used, these are silently skipped with a warning.

### Implementation

**1. Base transpiler** (`src/mcpm/skills/transpiler.py`):

Add `global_mode: bool = False` parameter to `sync_skills()`. When true, use `get_user_output_path()` instead of `get_output_path()`.

**2. Each transpiler**:

Add `get_user_output_path()` that returns `Path.home() / <client-specific-path>`. Transpilers that don't support user-level return `None` and are skipped.

**3. Sync command** (`src/mcpm/commands/skills/sync.py`):

Add `--global` flag:
```python
@click.option("--global", "global_mode", is_flag=True, help="Sync to user-level paths instead of project-level")
```

**4. Lockfile**:

When `--global`, the lockfile is written to `~/.config/mcpm/skills.lock` instead of `<repo>/mcpm-skills.lock`, so it doesn't pollute the skills repo.

**5. Clean command**:

`mcpm skills clean --global` removes user-level files. Without `--global`, behavior unchanged.

### git-sync integration

`mcpm skills git-sync` should automatically use `--global` mode since its entire purpose is cross-machine sync to user-level locations. The `full_sync()` function passes `global_mode=True` to `sync_skills()`.

## Files Changed

| Action | File | Description |
|--------|------|-------------|
| MOD | `src/mcpm/skills/transpiler.py` | Add `global_mode` param to `sync_skills()`, route to `get_user_output_path()` |
| MOD | `src/mcpm/skills/transpiler.py` | `BaseSkillTranspiler.get_user_output_path()` base method (returns None) |
| MOD | `src/mcpm/skills/transpilers/*.py` | Add `get_user_output_path()` per client (14 of 16, skip project-only) |
| MOD | `src/mcpm/commands/skills/sync.py` | Add `--global` flag |
| MOD | `src/mcpm/commands/skills/clean.py` | Add `--global` flag |
| MOD | `src/mcpm/skills/sync_git.py` | `full_sync()` uses `global_mode=True` |
| MOD | `src/mcpm/skills/agents/transpiler.py` | Same pattern for agents |
| MOD | `src/mcpm/styles/transpiler.py` | Same pattern for styles |

## Tests

| Test | Purpose |
|------|---------|
| `test_global_sync_writes_to_home` | Verify output goes to `~/.claude/skills/` with `--global` |
| `test_global_sync_skips_project_only` | Verify VS Code Copilot, Zed, AGENTS.md are skipped |
| `test_global_lockfile_location` | Lockfile at `~/.config/mcpm/skills.lock` |
| `test_global_clean_removes_user_files` | Clean only touches user-level files |
| `test_git_sync_uses_global` | git-sync automatically uses global mode |
| `test_project_sync_unchanged` | Default behavior is not affected |

## Out of Scope

- Per-client `--global` targeting (e.g., `--global --client claude-code`). The `--client` flag already exists and should compose with `--global`.
- Automatic detection of "is this a skills repo vs a project?" — too fragile. Explicit `--global` is better.
- Migration tooling for moving from symlink to native `--global`. Users can remove symlinks manually.

---

_Created: 2026-04-13_
