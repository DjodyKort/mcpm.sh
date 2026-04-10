---
name: git-conventional-commits
description: "Write git commit messages following the Conventional Commits specification. Use when committing code, creating PRs, or reviewing commit history."
activation: agent
license: MIT
metadata:
  author: mcpm
  version: "1.0.0"
  tags: "git,commits,conventional-commits,semantic-release"
---

## Conventional Commits

Format: `<type>[optional scope]: <description>`

### Types

- `feat:` -- new feature (triggers MINOR release)
- `fix:` -- bug fix (triggers PATCH release)
- `docs:` -- documentation only
- `style:` -- formatting, whitespace (no code change)
- `refactor:` -- code restructuring (no behavior change)
- `perf:` -- performance improvement
- `test:` -- adding/fixing tests
- `chore:` -- maintenance (deps, CI, build)

### Rules

1. Subject line: imperative mood, lowercase, no period, under 72 chars
2. Body: explain *why*, not *what* (the diff shows what)
3. Breaking changes: add `BREAKING CHANGE:` footer (triggers MAJOR release)
4. Scope is optional but useful: `feat(parser):`, `fix(cli):`

### Examples

```
feat: add skills sync command for multi-client transpilation

fix(transpiler): handle Windsurf 12K char truncation correctly

docs: update README with skills sync usage examples

refactor(parser): extract frontmatter parsing into dedicated module

chore(deps): bump pydantic to 2.11.0

feat(cli)!: rename `mcpm rules` to `mcpm skills`

BREAKING CHANGE: The `mcpm rules` command has been renamed to `mcpm skills`.
```

### Anti-Patterns

- `update stuff` -- too vague
- `Fix bug` -- capitalize, no period, but what bug?
- `feat: Add new feature` -- don't capitalize after type
- `WIP` -- don't commit work-in-progress to shared branches
