# Skill lifecycle hooks — declarative install via SKILL.md frontmatter

**Type:** Feature
**Scope:** `src/mcpm/skills/schema.py`, `src/mcpm/skills/parser.py`, `src/mcpm/skills/transpiler.py`, `src/mcpm/skills/transpilers/claude_code.py`, `tests/test_skills/test_hooks.py` (new)
**Branch:** `feat/skill-lifecycle-hooks` off `main`

---

## Status

| Phase | Status |
|-------|--------|
| 1. Analysis | Done |
| 2. Specification | Done — this document |
| 3. Implementation | In progress |
| 4. Tests | In progress |
| 5. Migration of `handoff` skill to new API | Pending (sibling work) |

---

## Context

Skills can ship executable helpers (Bash, Python, etc.) in their `scripts/` subdirectory — the [`feat/skill-asset-scripts-dir` commit `5d777b7`](../../src/mcpm/skills/transpiler.py) added the sync support for this. The natural next case is **lifecycle hooks**: a skill author wants their script to fire automatically at a specific client event such as Claude Code's `PreCompact`.

Today, the only path is for each skill to ship its own `install-hook.sh` that:

1. Symlinks `~/.claude/hooks/<name>.sh` to the skill's script
2. Edits `~/.claude/settings.json` to register the hook
3. Re-runs `chmod +x`

This is **per-client and per-skill duplication**. The skill author has to know Claude Code's settings.json schema, has to write idempotent install logic, and has to repeat the whole exercise if they want the same skill to register a hook on another client that supports them.

The `handoff` skill (the immediate motivation) does exactly this — its `scripts/install-hook.sh` is 155 lines of Claude-Code-specific logic that mcpm itself should own.

### Client landscape

| Client | Lifecycle hooks supported? |
|---|---|
| Claude Code | Yes — `PreCompact`, `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PostToolUse`, `Stop` |
| Cursor | No |
| Codex CLI | No |
| Continue | No (slash commands only) |
| Aider | No |
| Gemini CLI | No |
| Roo Code | No |
| Windsurf | No |
| JetBrains AI | No |
| Zed | No |
| VSCode Copilot | No |

Today only Claude Code has a real hook surface. That makes this a low-risk addition: one transpiler implements hook install, every other transpiler returns a single-warning no-op. If/when another client adds lifecycle hooks, only that client's transpiler needs extending — every skill author has already declared their intent in frontmatter.

### Why frontmatter, not a separate file

Anthropic's [Agent Skills spec](https://code.claude.com/docs/en/skills) already reserves a `hooks:` frontmatter field for exactly this purpose. mcpm currently parses it implicitly (via `metadata`) but doesn't transpile it. Adopting the existing field name keeps mcpm-authored skills compatible with non-mcpm consumers (e.g. raw Claude Code reading the skill directly from `~/.claude/skills/`).

## Summary

Add a `hooks:` field to `SkillFrontmatter`. Parse it in `parser.py`. Extend `BaseSkillTranspiler` with `install_hooks()` / `uninstall_hooks()` methods (default no-op + one-line warning). Override them in `ClaudeCodeTranspiler` to wire entries into `~/.claude/settings.json`. Track installed hooks per client in the lockfile so cleanup works when a skill is removed or renamed.

The surface area is intentionally narrow: one new schema field, two new transpiler methods, one client implementation, lockfile additions, tests. No new CLI commands. No new flags. No per-skill opt-in toggle.

## Implementation

### 1. Schema

`src/mcpm/skills/schema.py`:

```python
class SkillHook(BaseModel):
    """A single lifecycle hook declared by a skill."""

    # Path to the executable, relative to the skill's source directory.
    # Resolved to an absolute path at install time by the per-client transpiler.
    command: str

    # Optional matcher (semantics depend on the client). For Claude Code:
    # passed through as the hook entry's `matcher` field. Defaults to "*".
    matcher: str = "*"

    # Hook type. For Claude Code: "command" (the only supported type today).
    # Reserved field; future-proof for clients that distinguish e.g. "script"
    # vs "exec" vs "webhook".
    type: str = "command"
```

`SkillFrontmatter` gains:

```python
# Lifecycle hooks. Keyed by client-side event name (e.g. "PreCompact",
# "SessionStart"). Each value is a SkillHook. Clients that don't support
# lifecycle hooks ignore the field with a single warning per sync.
hooks: Optional[Dict[str, SkillHook]] = None
```

`LockFileEntry` gains:

```python
# Per-client list of hook identifiers that were installed by the last
# successful sync. Used during cleanup to remove stale entries from
# client-side config when the skill is renamed/removed.
hooks_installed: Dict[str, List[str]] = {}
```

A "hook identifier" is the absolute resolved command path. It's unique per skill (paths embed the skill name) and uniquely identifies the entry in client config files.

### 2. Parser

`src/mcpm/skills/parser.py`:

No code changes needed beyond what Pydantic gives for free — `SkillFrontmatter(**fm_data)` will populate `hooks` from a `hooks:` block in the YAML. The validator on `SkillHook` ensures `command` is a non-empty string.

Add one validation pass in the post-parse hook to ensure each declared hook's `command` resolves to an existing file inside the skill source directory. Missing scripts fail fast at parse time, not silently at sync time.

### 3. Transpiler base class

`src/mcpm/skills/transpiler.py`, add to `BaseSkillTranspiler`:

```python
def install_hooks(
    self,
    skill: SkillConfig,
    output_root: Path,
) -> List[str]:
    """Install this skill's declared lifecycle hooks into the client's config.

    Default implementation: log a single warning if the skill declares any
    hooks but this client doesn't support them. Returns an empty list.

    Override in client transpilers that have a lifecycle hook surface to
    write the appropriate config entries. Implementations must be
    idempotent: re-running on an already-installed skill is a no-op.

    Args:
        skill: Parsed canonical SkillConfig (with .frontmatter.hooks set).
        output_root: Sync output root.

    Returns:
        List of hook identifiers (absolute command paths) that were
        installed or were already present. Stored in the lockfile for
        cleanup tracking.
    """
    if skill.frontmatter.hooks:
        logger.warning(
            f"{self.client_key}: skill '{skill.name}' declares lifecycle hooks "
            f"({list(skill.frontmatter.hooks)}) but this client does not support hooks; skipped"
        )
    return []


def uninstall_hooks(
    self,
    output_root: Path,
    hook_ids: List[str],
) -> List[str]:
    """Remove previously-installed hook entries from the client's config.

    Default implementation: no-op (hooks were never installed, so nothing
    to remove). Override alongside `install_hooks()`.

    Args:
        output_root: Sync output root.
        hook_ids: Identifiers returned by a prior `install_hooks()` call.

    Returns:
        List of identifiers actually removed.
    """
    return []
```

### 4. Claude Code transpiler

`src/mcpm/skills/transpilers/claude_code.py`:

```python
def install_hooks(self, skill, output_root):
    if not skill.frontmatter.hooks:
        return []

    settings_path = output_root / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    settings.setdefault("hooks", {})

    skill_dir = output_root / ".claude" / "skills" / skill.name
    installed: List[str] = []

    for event, hook in skill.frontmatter.hooks.items():
        # Resolve command to absolute path under the synced skill dir
        cmd = str((skill_dir / hook.command).resolve())

        entry = {
            "matcher": hook.matcher,
            "hooks": [{"type": hook.type, "command": cmd}],
        }

        existing = settings["hooks"].setdefault(event, [])
        # Idempotent: only add if no entry with the same command exists
        already = any(
            any(h.get("command") == cmd for h in e.get("hooks", []))
            for e in existing
        )
        if not already:
            existing.append(entry)

        # Ensure executable bit on the target script (skill_dir already exists
        # post-transpile + asset-copy)
        target = Path(cmd)
        if target.exists():
            mode = target.stat().st_mode
            if mode & 0o111 == 0:
                target.chmod(mode | 0o755)

        installed.append(cmd)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2))
    return installed


def uninstall_hooks(self, output_root, hook_ids):
    settings_path = output_root / ".claude" / "settings.json"
    if not settings_path.exists():
        return []
    settings = json.loads(settings_path.read_text())
    hooks_section = settings.get("hooks", {})
    removed: List[str] = []

    for event, entries in list(hooks_section.items()):
        kept = []
        for entry in entries:
            filtered = [h for h in entry.get("hooks", []) if h.get("command") not in hook_ids]
            if filtered:
                entry["hooks"] = filtered
                kept.append(entry)
            else:
                removed.extend(h.get("command", "") for h in entry.get("hooks", []) if h.get("command") in hook_ids)
        if kept:
            hooks_section[event] = kept
        else:
            del hooks_section[event]

    if not hooks_section:
        settings.pop("hooks", None)

    settings_path.write_text(json.dumps(settings, indent=2))
    return removed
```

### 5. Orchestration in `sync_skills`

After the existing transpile + asset-copy block:

```python
if not dry_run and skill.frontmatter.hooks:
    try:
        installed = transpiler.install_hooks(skill, output_root)
        if installed:
            entry.hooks_installed[client_key] = installed
    except Exception as e:
        logger.warning(f"Failed to install hooks for {skill.name} on {client_key}: {e}")
        entry.warnings.append(f"{client_key}: hook install failed: {e}")
```

For cleanup during sync (when a skill was in the previous lockfile but not in the current sync), compare old vs new lockfiles and call `transpiler.uninstall_hooks(output_root, old_entry.hooks_installed[client_key])`. The orchestration already has lockfile-diff logic for removed output files; this slots in alongside it.

### 6. Tests

New file `tests/test_skills/test_hooks.py`:

- `test010_parse_hooks_from_frontmatter` — `SkillFrontmatter(**{"name": "x", "description": "y", "hooks": {"PreCompact": {"command": "scripts/foo.sh"}}})` produces a populated `hooks` dict
- `test011_parse_hooks_default_matcher_is_star` — `matcher` defaults to `"*"` when omitted
- `test012_parse_hooks_default_type_is_command` — `type` defaults to `"command"` when omitted
- `test020_base_transpiler_install_hooks_warns_and_returns_empty` — install on a class that doesn't override gives a warning and `[]`
- `test030_claude_code_install_writes_settings_json` — settings.json gets a populated `hooks.PreCompact` entry with absolute command path
- `test031_claude_code_install_is_idempotent` — second install adds no duplicate entry
- `test032_claude_code_install_preserves_other_hooks` — pre-existing unrelated hook entries are not removed
- `test033_claude_code_install_chmods_target_script` — the target script gets `+x` if it didn't have it
- `test040_claude_code_uninstall_removes_only_matching` — uninstall removes only the entries with matching command paths, leaves others alone
- `test041_claude_code_uninstall_removes_empty_event_section` — when last hook in an event is removed, the event key disappears from settings.json
- `test042_claude_code_uninstall_handles_missing_settings` — uninstall on a non-existent settings.json is a no-op (no crash)
- `test050_sync_skills_tracks_hooks_in_lockfile` — end-to-end sync of a skill with hooks populates `entry.hooks_installed["claude-code"]`
- `test060_unsupported_extension_in_hook_command` — declaring `command: scripts/foo.zip` fails at parse time (extension not whitelisted) — wait, this is handled by asset filter, not hook parser. Skip.
- `test061_hook_command_must_exist` — parser validates that the script file exists under the skill source dir; missing file = parse error

## Migration

Existing skills with no `hooks:` frontmatter field are unaffected.

The `handoff` skill (in `~/.config/mcpm/skills_repo/skills/handoff/`) will be migrated as sibling work:

1. Add `hooks:` block to SKILL.md frontmatter pointing at `scripts/precompact-hook.sh`
2. Delete `scripts/install-hook.sh` (no longer needed)
3. Remove Step 8 of the skill's process (auto-install) — mcpm sync now handles it
4. Add a note in SKILL.md that hook install is mcpm-managed

This migration is **out of scope for this spec** but listed in tasks.

## Open questions

None for v1.

## Out of scope (deferred)

- **Per-client matcher translation.** Claude Code's `matcher: "*"` is currently passed through verbatim. If a future client has a different matcher syntax, we'll need translation at the transpiler level. Not relevant today.
- **Hook event aliasing.** A skill might want one hook to fire on Claude Code's `PreCompact` and on a hypothetical Cursor `BeforeCompact` event. We'd need an event-alias table. Defer until a second hook-capable client exists.
- **Lifecycle for multiple hooks per event.** Today: one hook entry per event per skill. If a skill needs N hooks on the same event, declare them under separate events or extend the schema to accept lists. Defer until a real need surfaces.
- **`mcpm skills hooks` CLI command** (`list`, `status`, `clean-orphans`). Useful debugging but not required for the core flow.

## Future improvements

- Adopt the same `install_hooks()` / `uninstall_hooks()` shape for the **agents** and **styles** subsystems if a real use case emerges (currently neither has hook needs).
- Add a hook-install dry-run that prints diffs without writing.
- Audit hook commands during `mcpm skills audit` for obvious red flags (sourcing unknown URLs, `rm -rf`, etc.) — same risk model as audit already applies to skill bodies.
