# Skills Sync System

| Phase | Status |
|-------|--------|
| Analysis | Done |
| Specification | Done |
| Implementation | Done (Phase 1-3) |
| Tests | Done (183 tests) |
| Documentation | Done |

## Summary

Universal skills sync system for mcpm that manages AI coding instructions (skills, rules, templates) across all supported clients. Extends mcpm from "MCP server package manager" to "complete AI coding environment manager" by adding the ability to author skills once in a canonical format and transpile them to every client's native instruction format.

Key differentiator: no existing tool combines MCP server management with skills distribution. Skills can declare MCP server dependencies, and `mcpm skills install` provisions both instructions and servers in one step.

**Standards alignment:**
- [Agent Skills (SKILL.md)](https://agentskills.io) -- open format by Anthropic, adopted by 30+ agents. Progressive disclosure: name+description at startup (~100 tokens), full instructions on demand (<5K tokens).
- [AGENTS.md](https://agents.md) -- plain Markdown project context file under Linux Foundation AAIF. Read natively by 20+ tools, used in 60K+ open-source projects. No frontmatter required.

---

## 1. Canonical Skill Format

### 1.1 Directory structure

Each skill is a directory containing a `SKILL.md` file and optional supporting files. This follows the Agent Skills specification exactly:

```
skill-name/
├── SKILL.md          # Required: canonical frontmatter + instructions
├── servers.json      # Optional: MCP server dependencies (mcpm extension)
├── scripts/          # Optional: executable code referenced by instructions
├── references/       # Optional: additional documentation loaded on demand
├── assets/           # Optional: templates, schemas, static resources
└── ...
```

### 1.2 Universal frontmatter schema

The canonical `SKILL.md` uses YAML frontmatter that is a **superset** of the Agent Skills spec, extended with fields needed for cross-client transpilation and mcpm integration:

```yaml
---
# === Agent Skills spec fields (required) ===
name: kebab-case-skill-name          # 1-64 chars, lowercase + hyphens, must match directory name
description: >-                       # 1-1024 chars. What the skill does AND when to use it.
  Extract text from PDFs, fill forms, merge files.
  Use when working with PDF documents.

# === Agent Skills spec fields (optional) ===
license: MIT
compatibility: "Requires Python 3.11+ and uv"
allowed-tools: "Bash(git:*) Read Write"
metadata:
  author: username
  version: "1.0.0"
  tags: "frontend,react,testing"

# === mcpm extension fields ===
globs: "src/**/*.ts,src/**/*.tsx"     # File-scoping for activation
activation: auto                      # always | auto | agent | manual
priority: 100                         # Conflict resolution (higher wins, default: 0)
dependencies:                          # MCP server + skill dependencies
  servers: [github, filesystem]
  skills: [code-review-base]
---

Instructions body in Markdown...
```

#### Field definitions

| Field | Required | Source | Description |
|-------|----------|--------|-------------|
| `name` | Yes | Agent Skills spec | Skill identifier. Lowercase alphanumeric + hyphens only. No consecutive hyphens. Must not start/end with hyphen. Must match parent directory name. |
| `description` | Yes | Agent Skills spec | What the skill does and when to use it. Used for agent discovery. |
| `license` | No | Agent Skills spec | License name or reference to bundled LICENSE file. |
| `compatibility` | No | Agent Skills spec | Environment requirements (max 500 chars). |
| `allowed-tools` | No | Agent Skills spec | Space-delimited pre-approved tools. Experimental. |
| `metadata` | No | Agent Skills spec | Arbitrary key-value map. mcpm uses `author`, `version`, `tags`. |
| `globs` | No | mcpm extension | Comma-separated glob patterns for file-scoped activation. |
| `activation` | No | mcpm extension | When the skill activates. Default: `auto`. See Section 1.3. |
| `priority` | No | mcpm extension | Integer for conflict resolution. Higher wins. Default: `0`. |
| `dependencies` | No | mcpm extension | Declares required MCP servers and other skills. See Section 5. |

#### Frontmatter extension convention

mcpm extension fields are clearly separated from spec fields. Clients that don't understand them ignore them (standard YAML frontmatter behavior). If the Agent Skills spec adds conflicting fields in the future, mcpm fields will be namespaced under `mcpm:`.

### 1.3 Activation modes

Generalized from the union of all client activation models:

| Mode | Description | Clients that support natively |
|------|-------------|-------------------------------|
| `always` | Loaded into every conversation. Maps to Cursor `alwaysApply: true`, Windsurf `trigger: always_on`, Continue `alwaysApply: true`. | Cursor, Windsurf, Continue, Cline, JetBrains AI |
| `auto` | Agent decides based on `description` + `globs` match. Maps to Cursor `description` + `globs` (auto-attached), Claude Code skill progressive disclosure, JetBrains AI "By File Patterns" / "By Model Decision". Default mode. | Cursor, Claude Code, VS Code Copilot, Windsurf, Gemini CLI, JetBrains AI |
| `agent` | Agent sees name+description but must explicitly choose to load. Maps to Cursor `agent_requested`, Claude Code skill model, JetBrains AI "By Model Decision". | Cursor, Claude Code, Codex CLI, Gemini CLI, JetBrains AI |
| `manual` | User must explicitly invoke. Maps to Cursor `manual`, Claude Code `disable-model-invocation: true`, JetBrains AI "Manually" (`@rule:`). | Cursor, Claude Code, Windsurf, JetBrains AI |

### 1.4 Rules vs Skills

Skills use progressive disclosure (name+description loaded first, full body on demand). Rules are always-on instructions with no progressive disclosure -- they're injected directly into every conversation.

The canonical format handles both:
- **Skills**: `activation: auto` or `activation: agent` -- stored in `skills/` directory
- **Rules**: `activation: always` -- stored in `rules/` directory

Both use the same `SKILL.md` format. The distinction is organizational and affects how the transpilation engine renders them per client.

---

## 2. Repository Structure

### 2.1 Skills repository layout

```
my-skills/
├── mcpm-skills.yaml              # Repo manifest
├── skills/
│   ├── code-review/
│   │   ├── SKILL.md              # Canonical format
│   │   ├── scripts/
│   │   │   └── review-checklist.sh
│   │   └── references/
│   │       └── style-guide.md
│   ├── terraform-azure/
│   │   ├── SKILL.md
│   │   ├── servers.json          # MCP server dependencies
│   │   └── templates/
│   │       └── main.tf.template
│   └── react-components/
│       └── SKILL.md
├── rules/                         # Always-on rules (no progressive disclosure)
│   ├── coding-standards/
│   │   └── SKILL.md              # activation: always
│   └── commit-conventions/
│       └── SKILL.md              # activation: always
└── profiles/                      # Named groupings
    ├── work.yaml
    └── personal.yaml
```

### 2.2 Repo manifest (`mcpm-skills.yaml`)

```yaml
name: my-skills
description: "Personal AI coding skills collection"
author: username
version: "1.0.0"
license: MIT

# Optional: default profile applied on install
default_profile: work
```

### 2.3 Profile definitions

Profiles group skills and rules for specific contexts. Stored in `profiles/`:

```yaml
# profiles/work.yaml
name: work
description: "Skills for work projects"
skills:
  - code-review
  - terraform-azure
rules:
  - coding-standards
  - commit-conventions
```

Profiles reference skill/rule names (directory names). Profiles compose -- you can apply multiple profiles and they merge additively.

---

## 3. Client Transpilation Engine

### 3.1 Rendering pipeline

```
1. Read canonical SKILL.md
2. Parse universal frontmatter + body
3. For each target client:
   a. Map frontmatter fields to client-specific fields (Section 3.2)
   b. Apply client-specific constraints (Section 3.3)
   c. Determine output path and file extension (Section 3.4)
   d. Render to client's expected format
   e. Emit warnings for lossy conversions
4. Generate AGENTS.md available_skills block (Section 3.5)
5. Write lockfile mcpm-skills.lock (Section 3.6)
```

### 3.2 Field mapping table

This table defines how each canonical field maps to each client's native format. `--` means the client has no equivalent -- the field is dropped and a warning is emitted on `mcpm skills lint`.

**Client Capabilities Matrix:**

Shows which activation modes each client supports natively (without downgrade):

| Client | `always` | `auto` | `agent` | `manual` |
|--------|----------|--------|---------|----------|
| Claude Code | Y | Y | Y | Y (`disable-model-invocation`) |
| Cursor | Y | Y | Y | Y |
| Windsurf | Y | Y | Y | Y (`trigger: manual`) |
| VS Code Copilot | Y | Y | -- | -- |
| Continue.dev | Y | Y | -- | -- |
| Cline | Y | Y (via `paths`) | -- | -- |
| Gemini CLI | Y | Y | Y | -- |
| Codex CLI | Y | Y | Y | -- |
| JetBrains AI | Y | Y | Y | Y (`@rule:` mention) |
| Zed | Y | -- | -- | -- |
| Amazon Q | Y | -- | -- | -- |
| Aider | Y | -- | -- | -- |
| Trae | Y | Y | -- | -- |
| Goose | Y | Y | Y | -- |
| Roo Code | Y | Y | Y | -- |

**Field mapping table:**

| Canonical field | Claude Code | Cursor | Windsurf | VS Code Copilot | Continue.dev | Cline | Zed | Gemini CLI | Codex CLI | Amazon Q | JetBrains AI | Aider |
|-----------------|-------------|--------|----------|-----------------|--------------|-------|-----|------------|-----------|----------|-------------|-------|
| `name` | directory name | directory name / filename | filename | directory name | filename | filename | -- | directory name | directory name | filename | filename | -- |
| `description` | frontmatter `description` | frontmatter `description` | frontmatter `description` | frontmatter `description` | frontmatter `description` | -- | -- | frontmatter `description` | frontmatter `description` | -- | instruction field | -- |
| `globs` | frontmatter `paths` | frontmatter `globs` | frontmatter `globs` | frontmatter `applyTo` | frontmatter `globs` | frontmatter `paths` | -- | -- | -- | -- | file pattern config | -- |
| `activation: always` | `.claude/rules/` | `alwaysApply: true` | `trigger: always_on` | no `applyTo` | `alwaysApply: true` | `.clinerules/` | `.rules` append | `GEMINI.md` append | `AGENTS.md` append | `.amazonq/rules/` | Always mode | `CONVENTIONS.md` append |
| `activation: auto` | `.claude/skills/*/SKILL.md` | `description` + `globs` set | `trigger: glob` | `applyTo` set | `description` + `globs` set | `.clinerules/` + `paths` | -- (downgrade to always) | skill progressive disclosure | `.agents/skills/*/SKILL.md` | -- (downgrade to always) | By File Patterns / By Model Decision | -- (downgrade to always) |
| `activation: agent` | `.claude/skills/*/SKILL.md` | `agent_requested` mode | `trigger: model` | -- (downgrade to auto) | -- (downgrade to auto) | -- (downgrade to auto) | -- (downgrade to always) | skill progressive disclosure | `.agents/skills/*/SKILL.md` | -- (downgrade to always) | By Model Decision | -- (downgrade to always) |
| `activation: manual` | `disable-model-invocation: true` | `manual` mode | `trigger: manual` | -- (downgrade to auto) | -- (downgrade to auto) | -- (downgrade to auto) | -- (downgrade to always) | -- (downgrade to agent) | -- (downgrade to agent) | -- (downgrade to always) | Manually (`@rule:`) | -- (downgrade to always) |
| `allowed-tools` | frontmatter `allowed-tools` | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |
| `priority` | -- | -- | -- | -- | frontmatter `priority` | -- | -- | -- | -- | -- | -- | -- |

**Downgrade** means the activation mode is replaced with the closest supported mode for that client. Downgrades always go toward "more visible" (manual -> agent -> auto -> always) to avoid silent skill loss.

### 3.3 Client-specific constraints

| Client | Constraint | Handling |
|--------|-----------|----------|
| Windsurf | Global rules: 6K chars. Workspace rules: 12K chars/file. Combined total truncated if exceeding limits. | Truncate body with `[truncated -- see full skill at ...]` comment. Warn on `mcpm skills lint`. Prioritize workspace rules (where skills sync writes). |
| Zed | Single active rules file only (first match from priority list: `.rules`, `.cursorrules`, `.windsurfrules`, etc.). Also reads `AGENTS.md`. | Concatenate all active skills into `.rules` with `---` separators. Also generate `AGENTS.md` `<available_skills>` block as fallback. |
| Gemini CLI | Hierarchical `GEMINI.md` (per-directory). `@./path` imports. Also reads `.agents/skills/` and `.gemini/skills/`. | Generate `.gemini/skills/<name>/SKILL.md` for skills (native progressive disclosure). `@./path` references in `GEMINI.md` for always-on rules. |
| Aider | File reference via `read:` in `.aider.conf.yml`. Also reads `AGENTS.md`. | Add `read: .mcpm/skills/<name>/SKILL.md` entries to config. Generate AGENTS.md block as supplementary. |
| Cursor | Format transition: legacy `.mdc` files still work, new format is `.cursor/rules/<name>/RULE.md` folders. | Generate folder format (`.cursor/rules/<name>/RULE.md`) for Cursor 2.2+. Fall back to `.mdc` if legacy Cursor detected. |
| VS Code Copilot | `.instructions.md` extension. Discovers skills from `.github/skills/`, `.claude/skills/`, `.agents/skills/`. | Generate to `.github/skills/<name>/SKILL.md` for skills. Generate to `.github/instructions/<name>.instructions.md` for rules. |
| Codex CLI | TOML-based MCP config. Reads `AGENTS.md`, `AGENTS.override.md`, `.agents/skills/`. | Generate `.agents/skills/*/SKILL.md` + `AGENTS.md` block. |

### 3.4 Output paths

| Client | Skills path | Rules path |
|--------|------------|------------|
| Claude Code | `.claude/skills/<name>/SKILL.md` | `.claude/rules/<name>.md` |
| Cursor | `.cursor/rules/<name>/RULE.md` (2.2+) or `.cursor/rules/<name>.mdc` (legacy) | `.cursor/rules/<name>/RULE.md` or `.cursor/rules/<name>.mdc` |
| Windsurf | `.windsurf/rules/<name>.md` | `.windsurf/rules/<name>.md` |
| VS Code Copilot | `.github/skills/<name>/SKILL.md` | `.github/instructions/<name>.instructions.md` |
| Continue.dev | `.continue/rules/<name>.md` | `.continue/rules/<name>.md` |
| Cline | `.clinerules/<name>.md` | `.clinerules/<name>.md` |
| Zed | `.rules` (appended) + `AGENTS.md` block | `.rules` (appended) |
| Gemini CLI | `.gemini/skills/<name>/SKILL.md` | `GEMINI.md` (appended via `@./path`) |
| Codex CLI | `.agents/skills/<name>/SKILL.md` | `AGENTS.md` (appended) |
| Amazon Q | `.amazonq/rules/<name>.md` | `.amazonq/rules/<name>.md` |
| JetBrains AI | `.aiassistant/rules/<name>.md` | `.aiassistant/rules/<name>.md` |
| Aider | `.mcpm/skills/<name>/SKILL.md` (via `read:`) | `CONVENTIONS.md` (appended) |
| Trae | `.trae/rules/<name>.md` | `.trae/rules/<name>.md` |
| Goose | `.goose/skills/<name>/SKILL.md` | `.goose/rules/<name>.md` |
| Roo Code | `.roo/rules/<name>.md` | `.roo/rules/<name>.md` |

Files in append-mode targets (Zed `.rules`, `GEMINI.md`, `AGENTS.md`, `CONVENTIONS.md`) are managed within clearly delimited `<!-- mcpm:start -->` / `<!-- mcpm:end -->` blocks to allow safe re-sync without clobbering user content.

### 3.5 AGENTS.md generation

For clients that read `AGENTS.md` natively (Codex, Gemini CLI, Zed, Aider, and many others), generate an `<available_skills>` XML block following the [OpenSkills](https://github.com/OpenSkillsProject/openskills) pattern:

```markdown
<!-- mcpm:start -->
<available_skills>
<skill name="code-review" description="Automated code review with style and correctness checks." />
<skill name="terraform-azure" description="Terraform best practices for Azure infrastructure." />
</available_skills>
<!-- mcpm:end -->
```

This gives AGENTS.md-only agents skill discovery without full progressive disclosure support.

### 3.6 Lockfile

`mcpm-skills.lock` pins the exact state after a sync:

```yaml
version: 1
synced_at: "2026-04-04T12:00:00Z"
skills:
  code-review:
    source: "@user/my-skills/code-review"
    version: "1.0.0"
    hash: "sha256:abc123..."
    clients_synced:
      - claude-code
      - cursor
      - windsurf
    warnings:
      - "windsurf: body truncated from 7200 to 6000 chars"
rules:
  coding-standards:
    source: "local"
    hash: "sha256:def456..."
    clients_synced:
      - claude-code
      - cursor
```

---

## 4. CLI Commands

All commands are under the `mcpm skills` subcommand group. Designed to mirror existing mcpm patterns (`mcpm install`, `mcpm ls`, `mcpm profile`).

### 4.1 Local skill management

```
mcpm skills init [--path PATH]
```
Scaffold a new skills repository at PATH (default: current directory). Creates `mcpm-skills.yaml`, `skills/`, `rules/`, `profiles/` structure.

```
mcpm skills add <name> [--type skill|rule] [--template TEMPLATE]
```
Create a new skill or rule from a template. Generates the directory with a starter `SKILL.md`.

```
mcpm skills remove <name>
```
Remove a skill from the local repository AND remove all transpiled outputs from installed clients.

```
mcpm skills list [--client CLIENT]
```
Show installed skills with activation status per client. With `--client`, filter to a specific client.

```
mcpm skills diff
```
Show what has changed since last sync: new/modified/deleted skills, which clients would be affected.

```
mcpm skills lint [--fix]
```
Validate canonical format. Check constraints per client (Windsurf char limits, name conventions). Warn on lossy conversions. `--fix` auto-corrects fixable issues (e.g. name casing).

### 4.2 Sync

```
mcpm skills sync [--client CLIENT] [--profile PROFILE] [--dry-run]
```
Core command. Reads canonical skills, transpiles to all installed clients (or specific `--client`), writes output files, updates lockfile. `--dry-run` shows what would change without writing.

Leverages existing `mcpm client ls` to detect installed clients. Only syncs to clients that are actually installed.

```
mcpm skills clean [--client CLIENT]
```
Remove all mcpm-managed skill files from clients. Only removes files within mcpm-managed paths/blocks.

```
mcpm skills status [--strict]
```
Detect drift between canonical source and transpiled output files. Reports per-client, per-skill whether the output matches source. `--strict` exits non-zero on any drift (useful for CI).

```
mcpm skills audit [name]
```
Security scan skills for prompt injection patterns, data exfiltration attempts, suspicious scripts, and excessive permission requests. Runs automatically on `mcpm skills install` from remote sources.

### 4.3 Install from remote

```
mcpm skills install @user/repo[/skill-name][@version]
```
Install skills from a GitHub repository. Examples:
- `mcpm skills install @anthropics/skills` -- install all skills from repo
- `mcpm skills install @anthropics/skills/code-review` -- install specific skill
- `mcpm skills install @anthropics/skills/code-review@1.2.0` -- pin version

When `servers.json` is present, also runs `mcpm install` for declared MCP server dependencies (see Section 5).

```
mcpm skills uninstall <name>
```
Remove an installed remote skill and its transpiled outputs. Does NOT uninstall MCP servers (they may be used by other skills).

```
mcpm skills update [name]
```
Update installed remote skills to latest (or specific skill by name). Respects semver ranges if pinned.

### 4.4 Taps (skill repositories)

```
mcpm skills tap add <user/repo> [--name ALIAS]
```
Register a remote skills repository as a tap (Homebrew model). Clones/caches locally.

```
mcpm skills tap remove <name>
```
Unregister a tap.

```
mcpm skills tap update [name]
```
Git pull all taps (or specific tap).

```
mcpm skills tap list
```
List registered taps.

```
mcpm skills search <query>
```
Search across all taps and installed skills by name, description, and tags.

### 4.5 Profile integration (extends existing `mcpm profile`)

Skills are managed through the existing `mcpm profile` command, not a separate subcommand. This avoids confusion about having two profile systems.

```
mcpm profile create <name> [--servers s1,s2] [--skills s1,s2] [--rules r1,r2]
```
Create a profile with both servers and skills. Extends the existing `profile create` command with `--skills` and `--rules` flags.

```
mcpm profile apply <name>
```
Existing command gains skills awareness: activates servers in clients AND runs `mcpm skills sync` for the profile's skills/rules.

```
mcpm profile edit <name>
```
Existing interactive editor extended to show and manage both servers and skills.

### 4.6 Packaging

```
mcpm skills bundle [--output PATH]
```
Create a portable zip/tar package containing skills + manifest + server configs. For offline sharing or air-gapped environments.

---

## 5. Skills + MCP Server Bundling

### 5.1 Server dependency declaration

A skill can declare MCP server dependencies in `servers.json` adjacent to its `SKILL.md`:

```json
{
  "servers": {
    "github": {
      "source": "@modelcontextprotocol/server-github",
      "required": true
    },
    "filesystem": {
      "source": "@anthropics/mcp-server-filesystem",
      "required": true
    },
    "custom-api": {
      "source": "https://my-remote-server.com/mcp",
      "transport": "streamable-http",
      "required": false
    }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `source` | Yes | Registry name (for `mcpm install`) or URL (for remote servers). |
| `transport` | No | `stdio` (default), `streamable-http`, `sse`. |
| `required` | No | If `true` (default), skill install fails when server install fails. If `false`, warn and continue. |

### 5.2 Install flow

When `mcpm skills install @user/repo/skill-name` encounters a `servers.json`:

1. Parse `servers.json`
2. For each server:
   a. Check if server already installed globally (`mcpm ls`)
   b. If not installed, run `mcpm install <source>` using existing mcpm server install infrastructure
   c. If `required: true` and install fails, abort skill install and report error
   d. If `required: false` and install fails, warn and continue
3. Install the skill itself (copy to local skills directory)
4. Run `mcpm skills sync` to transpile to clients

### 5.3 Server config in profiles

Extend existing mcpm profile system to include skills:

```bash
# Create profile with both servers and skills
mcpm profile create work --servers github,filesystem --skills code-review,terraform

# Apply profile -- activates both servers in clients AND syncs skills
mcpm profile apply work
```

This uses the existing virtual profile tag system. Skills get `profile_tags` just like servers.

---

## 6. Secrets and Environment Variables

### 6.1 Env var interpolation

Follow the convention established by Windsurf and VS Code:

```
${env:GITHUB_TOKEN}
```

This syntax is used in `servers.json` for server configs that need secrets:

```json
{
  "servers": {
    "github": {
      "source": "@modelcontextprotocol/server-github",
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
      }
    }
  }
}
```

### 6.2 Required env vars

Skills can declare required environment variables in the `metadata` frontmatter:

```yaml
metadata:
  required_env:
    - name: GITHUB_TOKEN
      description: "GitHub personal access token for API access"
      secret: true
    - name: PROJECT_ID
      description: "GCP project ID"
      secret: false
```

### 6.3 Validation

`mcpm skills sync` validates before writing:
1. Check all `required_env` variables are set in the environment
2. If missing and `secret: false`, prompt user for value
3. If missing and `secret: true`, error with message to set the env var
4. Never write secret values into instruction files -- only into MCP server configs via `${env:}` references

---

## 7. Registry and Distribution

### 7.1 Phase 1: Git-based taps

Modeled after Homebrew taps. A tap is a Git repository containing skills in the standard repository layout (Section 2).

```bash
# Add a tap
mcpm skills tap add anthropics/skills

# Tap is cached locally at:
# ~/.config/mcpm/taps/anthropics-skills/

# Search across taps
mcpm skills search "code review"

# Install from tap
mcpm skills install @anthropics/skills/code-review
```

**Tap resolution order:**
1. Local skills repository (current project)
2. Registered taps (in order added)
3. Direct GitHub URL fallback

### 7.2 Phase 2: Central registry (future)

Integrate with mcpm's existing server registry infrastructure at `mcp-registry/`:

- Skills listed alongside MCP servers in registry
- `mcpm skills publish` uploads to central registry
- Semver versioning with tagged releases
- Quality signals: download count, star count, compatibility matrix

This phase is deferred. The tap model provides sufficient distribution for initial launch.

---

## 8. Integration with Existing mcpm Features

### 8.1 Client detection

`mcpm skills sync` reuses `mcpm client ls` (the `ClientRegistry` and `detect_installed_clients()`) to determine which clients are installed. Only transpiles to installed clients.

**Note:** The current `ClientRegistry` supports 14 clients but is missing several that this spec targets: Amazon Q, JetBrains AI, Aider, and Zed. These client managers need to be added to `src/mcpm/clients/managers/` before skills sync can target them. Conversely, clients already in the registry but not yet in the transpilation tables (Trae, Goose, Roo Code) are included in Phase 2.

### 8.2 Profile integration

Skills become first-class members of mcpm profiles alongside servers. The existing `ProfileConfigManager` virtual profile tag system extends naturally. Profiles are managed through the existing `mcpm profile` command (not a separate `mcpm skills profile`):

```python
# Existing: servers have profile_tags
class BaseServerConfig(BaseModel):
    name: str
    profile_tags: List[str] = []

# New: skills also have profile_tags in the global config
class InstalledSkill(BaseModel):
    name: str
    source: str  # "local" or "@user/repo/skill"
    version: Optional[str] = None
    profile_tags: List[str] = []
```

The existing `ProfileMetadata` model extends to track skill membership:

```python
class ProfileMetadata(BaseModel):
    name: str
    api_key: Optional[str] = None
    description: Optional[str] = None
    # New fields:
    skills: List[str] = []  # Skill names in this profile
    rules: List[str] = []   # Rule names in this profile
```

### 8.3 Git sync

mcpm already supports git-based config sync. Extend to include skills repo reference:

```yaml
# In mcpm global config
skills:
  repo: "git@github.com:user/my-skills.git"
  branch: main
  auto_sync: true
```

When `mcpm sync` runs on a new machine, it:
1. Clones/pulls the skills repo
2. Installs any server dependencies from `servers.json` files
3. Runs `mcpm skills sync` to transpile to all installed clients

### 8.4 Router

The mcpm router could expose skills metadata as an MCP resource:

```
Resource: mcpm://skills/list
Resource: mcpm://skills/{name}/instructions
```

This allows MCP-connected agents to discover and read skills programmatically. Deferred to post-Phase 1.

---

## 9. Implementation Status

All three phases are implemented. 183 tests, 62 source files, 19 CLI commands, 15 client transpilers + AGENTS.md.

### Phase 1: Local skills + sync -- DONE

1. ~~Canonical SKILL.md parser (frontmatter + body)~~ `src/mcpm/skills/parser.py`
2. ~~Transpilation engine for top 6 clients~~ `src/mcpm/skills/transpilers/` (claude_code, cursor, windsurf, vscode_copilot, continue_dev, jetbrains)
3. ~~CLI commands~~ `src/mcpm/commands/skills/` (init, add, sync, ls, diff, lint, clean, status)
4. ~~Lockfile generation~~ `src/mcpm/skills/config.py`
5. ~~AGENTS.md generation~~ `src/mcpm/skills/transpilers/agents_md.py`
6. Profile extension deferred (requires modifying existing profile commands)
7. ~~Drift detection~~ `src/mcpm/commands/skills/status.py`
8. ~~Best-practice linting~~ `src/mcpm/skills/lint.py`

### Phase 2: Remote install + taps -- DONE

9. ~~Remote install~~ `src/mcpm/commands/skills/install.py`
10. ~~Tap system~~ `src/mcpm/skills/taps.py` + `src/mcpm/commands/skills/tap.py`
11. ~~servers.json bundling~~ detected during install, user prompted to run `mcpm install`
12. ~~Uninstall~~ `src/mcpm/commands/skills/uninstall.py`
13. ~~Security audit~~ `src/mcpm/skills/audit.py` + `src/mcpm/commands/skills/audit.py`
14. ~~9 additional client transpilers~~ cline, zed, gemini_cli, codex_cli, amazon_q, aider, trae, goose, roo_code
15. `mcpm skills import` deferred (reverse transpilation is complex)
16. ~~Simulated features~~ metadata in HTML comments for unsupported targets (JetBrains, Amazon Q)

### Phase 3: Ecosystem integration -- DONE

17. ~~Git sync~~ `src/mcpm/skills/sync_git.py` + `src/mcpm/commands/skills/git_sync.py`
18. ~~Bundle packaging~~ `src/mcpm/skills/bundle.py` + `src/mcpm/commands/skills/bundle.py`
19. ~~Registry schema~~ `src/mcpm/skills/registry.py` (schema defined, actual registry server deferred)
20. ~~Router resource exposure~~ `src/mcpm/skills/router.py` (registers `mcpm://skills/*` resources)
21. ~~Usage analytics~~ `src/mcpm/skills/analytics.py` (tracks sync/install/uninstall via SQLite monitor)

---

## 10. Decisions

1. **Use Agent Skills SKILL.md as the base format** rather than inventing a new one. The spec is adopted by 30+ agents. mcpm extends it with transpilation-specific fields (`globs`, `activation`, `priority`, `dependencies`) that are safely ignored by spec-compliant parsers.

2. **Extend rather than fork the Agent Skills spec.** mcpm extension fields live in the same frontmatter. If spec conflicts arise in the future, namespace under `mcpm:`.

3. **Downgrade activation modes toward "more visible"** when a client doesn't support the requested mode. A skill set to `manual` that can only be `always` on Zed is better than a skill that silently disappears.

4. **Use `<!-- mcpm:start -->` / `<!-- mcpm:end -->` blocks** for append-mode targets (Zed, Gemini CLI, Aider) to allow safe re-sync.

5. **Do not auto-uninstall MCP servers** when removing a skill. Servers may be shared across skills or manually configured.

6. **Phase 1 covers 6 clients** (Claude Code, Cursor, Windsurf, VS Code Copilot, Continue.dev, JetBrains AI), chosen by market share and activation mode support. Remaining clients added in Phase 2.

7. **Merge skills into existing `mcpm profile`** rather than creating a separate `mcpm skills profile` subcommand. One profile system manages both servers and skills.

8. **Map `activation: manual` to `disable-model-invocation: true` for Claude Code** rather than downgrading. This is the exact semantic match.

9. **Deterministic transpilation, not LLM-based adaptation.** DevSync's LLM approach is clever but non-deterministic. For CI/CD and team consistency, mcpm uses template-based transpilation with known, predictable output.

10. **No runtime dependencies for agents.** OpenSkills requires `npx openskills read` at runtime. mcpm writes static files that agents read directly -- no process invocation needed.

11. **Pre-seed the registry before opening it.** Paks launched with an empty registry and got ~100 total downloads. When mcpm launches its central registry (Phase 3), it should be pre-populated with curated, high-quality skills.

12. **Deep support for fewer targets over shallow support for many.** Rulesync supports 25+ targets but maintenance burden is high. mcpm prioritizes 6 clients deeply in Phase 1, expanding in Phase 2 only after the transpilation architecture proves stable.

---

## 11. Competitive Landscape

Existing tools in this space and mcpm's positioning relative to them:

| Tool | Stars | Language | Approach | Strengths | Gaps |
|------|-------|----------|----------|-----------|------|
| **Rulesync** | ~970 | TypeScript | Transpiles `.rulesync/` to 25+ targets. 7 feature types: rules, commands, MCP, ignore, subagents, skills, hooks. | Most mature transpiler. Widest target coverage. `rulesync import` for reverse sync. "Simulated" features for unsupported targets. `rulesync fetch` for community packs. | No server management. No registry. No quality evaluation. |
| **OpenSkills** | ~9.4K | TypeScript | `<available_skills>` XML in AGENTS.md. Progressive disclosure via `npx openskills read`. | Most popular tool. Cross-tool discovery via AGENTS.md. Priority cascade (project > global). | Requires npx at runtime. No transpilation. No MCP integration. No versioning. |
| **skillshare** | ~1.3K | Go | Single binary. Symlinks/NTFS junctions. 50+ targets. Built-in security audit. Web dashboard UI. | **Security scanning** for prompt injection/data exfiltration. Zero runtime deps. Windows NTFS junction support. GitHub Actions integration. | No format conversion. No MCP. No registry. |
| **block/ai-rules** | ~90 | Rust | Single source `ai-rules/*.md`. Drift detection (`status`). Symlink mode. 11 agents. | Enterprise-backed (Square). Drift detection for CI. Auto-gitignore generated files. | Small community. No registry. No quality evaluation. |
| **Paks** | ~50 | Rust + TS | NPM-style centralized registry (paks.stakpak.dev). Semver. Validation. Templates. | **Only tool with proper versioned registry.** Dry-run publishing. Strict validation. | Registry has low adoption (~100 downloads). No transpilation. Cold-start problem. |
| **Tessl** | SaaS | Closed | Quality evaluation platform. Baseline vs with-skill comparison. Auto-optimization. GitHub Actions review gate. | **Skill quality measurement** is unique. Auto-optimization. Scenario generation from commits. "Tiles" bundle skills+docs+rules. | Proprietary SaaS. API key required. Cost per evaluation. Vendor lock-in. |
| **skills-supply/sk** | ~30 | TypeScript | `agents.toml` manifest. Claude plugin extraction for cross-agent use. Smart reconciliation. | **Cleanest declarative manifest.** Claude marketplace bridge. Alias system prevents name collisions. | 5 agents only. No registry. No rules/MCP. |
| **DevSync** | ~18 | Python | **LLM-powered** extraction and adaptation. Semantic understanding of practices. MCP credential handling. | Novel LLM-based approach. Intelligent merging. Credential prompting at install (never stored). | Non-deterministic. Requires API key. Cost per operation. Small community. |
| **Skillshub** | ~4 | Rust | Homebrew taps model. External skill discovery. Star list import. | Tap pattern is intuitive. Cross-agent sync from external skills. `doctor` diagnostics. | Tiny community. db.json is fragile. Skills only. |
| **ai-rules-sync** | ~23 | TypeScript | Symlink-based. VS Code extension. Multi-repo mixing. Local overrides. | IDE integration. Team onboarding via manifest. Private override file for enterprise. | Symlinks break on Windows. Limited conversion. |
| **rule-porter** | ~5 | JavaScript | Bidirectional format conversion. Auto-detects source. Preserves globs as comments. | "No silent data loss" principle. Bidirectional. Companion tools (cursor-doctor). | 5 formats only. One-time conversion, no sync. |

**mcpm's unique position:** The only tool that combines (a) MCP server management with (b) skills transpilation and (c) cross-client config management. The `servers.json` bundling -- installing MCP servers alongside skills -- is a capability no competitor offers.

### 11.1 Features to adopt from competitors

Based on competitive analysis, the following features are worth incorporating:

**1. Security auditing (inspired by skillshare)**

```
mcpm skills audit [name]
```
Scan skills for common prompt injection patterns, data exfiltration attempts, and suspicious script content before installation. Especially important since mcpm skills can bundle MCP servers that execute code. Run automatically on `mcpm skills install` from remote sources.

Patterns to detect:
- Instructions to ignore previous context or override safety guidelines
- Exfiltration patterns (curl/wget to unknown URLs, base64 encoding of file contents)
- Excessive permission requests in `allowed-tools`
- Scripts that modify system files or install packages without declaration

**2. Drift detection (inspired by block/ai-rules)**

```
mcpm skills status
```
Detect when transpiled output files have been modified after sync (manual edits, other tools, IDE changes). Report drift per client, per skill. Useful for CI pipelines:

```bash
# In CI: fail if generated files are out of sync with source
mcpm skills status --strict && echo "Skills in sync" || exit 1
```

Also auto-add mcpm-generated files to `.gitignore` with `mcpm skills sync --gitignore`.

**3. Simulated features for unsupported targets (inspired by rulesync)**

When a target client doesn't support a feature natively (e.g., Zed doesn't support activation modes, Amazon Q doesn't support description), instead of silently dropping the metadata, inject it as a structured markdown comment:

```markdown
<!-- mcpm: activation=agent, globs=src/**/*.ts -->
<!-- mcpm: This skill should be loaded when working with TypeScript files -->

[Skill instructions here...]
```

This preserves intent for human readers and future-proofs against clients adding support later.

**4. Lightweight skill quality linting (inspired by Tessl)**

Extend `mcpm skills lint` beyond format validation to include best-practice checks:

- Description quality: too short (<20 chars), too vague ("helps with code"), missing "when to use" guidance
- Body length: warn if >500 lines (Agent Skills spec recommends keeping under 500)
- Reference depth: warn if references chain more than 1 level deep
- Glob coverage: warn if globs are overly broad (`**/*`) or suspiciously narrow
- Conflict detection: warn if two skills have overlapping globs and same activation mode

---

## 12. Open Questions (Resolved)

1. **Conflict resolution across skills repos.** RESOLVED: Last-installed wins. `mcpm skills lint` detects duplicate names and overlapping globs. Implemented in `lint.py`.

2. **Bidirectional sync.** DEFERRED: Not implemented. Reverse transpilation is complex and low priority. Users should author in canonical format and sync outward.

3. **Skill versioning granularity.** RESOLVED: Repo-level semver in `mcpm-skills.yaml`. Skill-level version in `metadata.version` (informational). Lockfile tracks per-skill hashes for change detection.

4. **Workspace vs global skills.** RESOLVED: Project-level by default (matching most clients). Skills are synced into the project root where `mcpm skills sync` is run. `--global` flag not implemented yet.

5. **Interaction with existing `.cursorrules`, `.clinerules`, `CLAUDE.md` files.** RESOLVED: mcpm only manages files it created. Lockfile tracks all managed files. `mcpm skills clean` only removes lockfile-tracked files. Append-mode targets use `<!-- mcpm:start/end -->` delimiters to avoid clobbering user content.

6. **File ownership conflicts with other sync tools.** RESOLVED: mcpm uses lockfile tracking + managed block delimiters. Does not touch files it didn't create. `mcpm skills doctor` not yet implemented -- could be added as a lightweight check.

7. **Atomic sync failures.** RESOLVED: Sync is idempotent. On partial failure, the lockfile records which clients succeeded. Warnings are recorded per-skill per-client. Re-running `mcpm skills sync` fixes partial state.

8. **Security of remote skills.** RESOLVED: `mcpm skills audit` scans for prompt injection, data exfiltration, dangerous commands, and excessive permissions. Runs automatically on `mcpm skills install` (skippable with `--no-audit`). Scripts are informational -- agents decide whether to run them. `--verify` for signed skills not yet implemented.

9. **`.agents/skills/` as shared output path.** RESOLVED: Each client gets its own output path. Codex CLI writes to `.agents/skills/`, VS Code Copilot to `.github/skills/`, Gemini CLI to `.gemini/skills/`. No shared path -- simpler to reason about and clean.

10. **Cursor format transition.** RESOLVED: Default to new `RULE.md` folder format (`.cursor/rules/<name>/RULE.md`). Legacy `.mdc` not generated. `--cursor-legacy` flag not implemented -- can be added if users request it.
