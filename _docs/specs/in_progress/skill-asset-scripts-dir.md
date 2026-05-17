# Skill asset sync — `scripts/` subdir + executable extensions

**Type:** Feature (bugfix-shaped, narrow surface)
**Scope:** `src/mcpm/skills/transpiler.py`, `tests/test_skills/test_asset_copy.py`
**Branch:** `feat/skill-asset-scripts-dir` off `feat/skill-sync-system`

---

## Status

| Phase | Status |
|-------|--------|
| 1. Analysis | Done — root cause traced to two hardcoded tuples |
| 2. Specification | Done — this document |
| 3. Implementation | In progress |
| 4. Tests | In progress |
| 5. Documentation update | Pending (`CLAUDE.md` mention of new subdir + extension list) |

---

## Context

Canonical skill repos can ship progressive-disclosure assets in subdirectories alongside `SKILL.md` so that the main skill body stays slim. The current implementation supports five subdirs (`modules`, `reference`, `templates`, `examples`, `assets`) and copies files with extensions `.md, .txt, .json, .yaml, .yml, .png, .svg, .jpg, .jpeg, .webp` into the per-client output during `mcpm skills sync`.

A real skill — `handoff` (project-handoff ritual, canonical at `~/.config/mcpm/skills_repo/skills/handoff/`) — bundles three Bash helpers used by the skill body at runtime:

- `scripts/detect-project.sh` — emits JSON describing the current project's persistence layout
- `scripts/precompact-hook.sh` — emergency state dump invoked by Claude Code's `PreCompact` hook
- `scripts/install-hook.sh` — idempotent installer that wires the PreCompact hook into `~/.claude/settings.json`

After `mcpm skills sync`, none of these files end up under `~/.claude/skills/handoff/`. The SKILL.md instructs the model to run `scripts/detect-project.sh`, but the file is absent from the synced output. The skill fails silently at the first script invocation.

### Root cause

`src/mcpm/skills/transpiler.py` lines 22-26:

```python
SKILL_ASSET_DIRS = ("modules", "reference", "templates", "examples", "assets")
SKILL_ASSET_EXTENSIONS = (
    ".md", ".txt", ".json", ".yaml", ".yml",
    ".png", ".svg", ".jpg", ".jpeg", ".webp",
)
```

Two hardcoded tuples that act as an allowlist. `scripts/` is not in the dir tuple, and `.sh` is not in the extension tuple. Either gap alone would block the sync; both together produce silent zero-file copies for any skill using executable assets.

Workarounds that exist today are unsatisfactory:

- Renaming `scripts/` to `assets/` — pollutes a semantic dir intended for binary assets (images, fonts) with executable code that lints flag as foreign.
- Embedding scripts as fenced code blocks in `templates/*.md` — requires the skill body to write the file out and `chmod +x` on first run. Adds two failure modes (write fails, chmod fails) and pollutes the skill body with infrastructure plumbing.
- Referencing the canonical path (`~/.config/mcpm/skills_repo/...`) directly — breaks cross-machine sync and assumes the user's canonical path on every consuming machine.

The correct fix is to extend the allowlists.

## Summary

Two-line change in `transpiler.py`: add `"scripts"` to `SKILL_ASSET_DIRS` and add `.sh`, `.bash`, `.py` to `SKILL_ASSET_EXTENSIONS`. Update `_copy_skill_assets` to preserve the executable bit on copy (already handled by `shutil.copy2`'s `copystat` — verified, but the new test asserts it explicitly so any future regression is caught).

The surface area is intentionally narrow: this spec adds nothing else (no new flags, no per-skill opt-in, no security toggle). Skills that don't ship scripts are unaffected; skills that do get one new working subdir.

## Implementation

### 1. Transpiler change

`src/mcpm/skills/transpiler.py`:

```python
SKILL_ASSET_DIRS = ("modules", "reference", "templates", "examples", "assets", "scripts")
SKILL_ASSET_EXTENSIONS = (
    ".md", ".txt", ".json", ".yaml", ".yml",
    ".png", ".svg", ".jpg", ".jpeg", ".webp",
    ".sh", ".bash", ".py",
)
```

Rationale for the extension additions:

- `.sh` is the primary use case (the example that motivated this fix).
- `.bash` covers Bash-specific scripts that rely on Bash features absent in POSIX `sh`. Same security profile as `.sh`.
- `.py` covers Python helpers. Common enough in skills that read JSON or run small data transformations.

Explicitly **not** added in this iteration:

- `.js`, `.mjs`, `.ts` — Node ecosystem; can be added in a follow-up if a real skill needs them. Keeping the surface tight reduces the security review burden for the initial change.
- `.rb`, `.pl`, `.go` etc. — same reasoning. Add on demand.
- Compiled binaries (`.so`, `.dylib`, `.dll`) — out of scope. Skills should not ship pre-compiled native code; if they need it they should depend on system tooling.

### 2. Executable bit preservation

`shutil.copy2` invokes `shutil.copystat` after the byte-copy, which preserves file mode bits including the executable flag. This is already the behavior for `.png` and other files in the existing extensions; no code change is needed to make it work for `.sh`.

The new test asserts this explicitly so the contract is enforced.

### 3. Documentation

`CLAUDE.md` "Skills System" section gets a one-line update:

> Asset subdirectories: `modules/`, `reference/`, `templates/`, `examples/`, `assets/`, `scripts/`. Extensions: markdown, plain text, structured data, images, plus `.sh`, `.bash`, `.py` for executable helpers (executable bit preserved on copy).

### 4. Security note

Adding executable extensions widens the trust boundary of `skills sync`: a malicious skill could ship a destructive shell script. This is mitigated by:

- Skills are user-installed (or user-authored), so the trust model is the same as for any code the user puts in `~/.local/bin/`.
- `mcpm skills audit` (existing tool) already scans skills for prompt injection and data exfiltration patterns; the audit logic does not need extending because shell scripts are not interpreted by an LLM but executed by the user's shell at invocation time — the same scrutiny the user already applies to any third-party shell script applies here.
- No auto-execution: the transpiler copies files but never runs them. Skills must explicitly invoke their bundled scripts via the model's Bash tool. The user is in control of when (if ever) those scripts run.

No additional gating (skill frontmatter opt-in, settings flag) is introduced. This matches the existing model for assets/, where binary blobs ship without per-skill consent.

## Tests

`tests/test_skills/test_asset_copy.py` gets four new cases:

1. `test_copies_scripts_subdir` — synth skill with `scripts/foo.sh`, run `_copy_skill_assets`, assert destination contains `scripts/foo.sh` and the file is non-empty.
2. `test_preserves_executable_bit_on_scripts` — same setup but source script has `os.chmod(..., 0o755)`. After copy, destination file has `os.stat(...).st_mode & 0o111 != 0`. Validates the contract.
3. `test_filters_non_script_extensions_in_scripts_dir` — synth skill with `scripts/foo.sh` AND `scripts/bar.zip`. Copy. Assert only `foo.sh` lands. `.zip` is silently dropped (existing extension filter behavior).
4. `test_copies_python_helper` — `scripts/helper.py` survives the copy. Mirrors the `.sh` test for the second new extension. (`.bash` is symmetric to `.sh`; one test for the symmetric case is enough.)

The existing `test_skips_files_outside_allowed_extensions` test passes unchanged — the extension allowlist still filters.

## Migration

None required. Existing skills that didn't use `scripts/` are unaffected. New skills can adopt `scripts/` immediately after this lands. The synced output gets one extra directory per affected skill — no breaking change for downstream consumers.

## Open questions

None.

## Out of scope (deferred)

- Per-skill or per-client opt-out of script syncing (no demand observed).
- Symlink support (skill authors can replicate via `scripts/` having multiple files; no demand for symlinks across the sync boundary).
- Compiled binary support (security review burden not justified by current demand).
- Node / TypeScript / Ruby / other interpreter extensions (add on demand).

## Future improvements

If skills grow more complex executable trees, a possible follow-up is a `bin/` convention separate from `scripts/`:

- `scripts/` = helpers invoked by the skill body via Bash tool calls.
- `bin/` = first-class executables intended to be added to `$PATH`.

Not needed today. Captured here for design memory.
