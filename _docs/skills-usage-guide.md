# mcpm Skills & Agents -- Usage Guide

How to actually use the skills sync system day-to-day across multiple AI coding clients.

## Quick Start (5 minutes)

### 1. Create your skills repo

Pick a directory where you want to keep your skills. This can be a standalone git repo (for sharing across machines) or inside an existing project.

```bash
# Standalone repo (recommended for personal skills)
mkdir ~/my-skills && cd ~/my-skills
mcpm skills init --name my-skills
git init && git add -A && git commit -m "init: skills repo"

# Or inside an existing project
cd ~/my-project
mcpm skills init --name my-project-skills
```

### 2. Add your first skill

```bash
mcpm skills add code-review
```

Edit `skills/code-review/SKILL.md`:

```markdown
---
name: code-review
description: "Review code for bugs and style. Use when reviewing PRs or code changes."
globs: "src/**/*.py,src/**/*.ts"
activation: auto
---

When reviewing code:
1. Check for logic errors and edge cases
2. Verify error handling
3. Look for security issues
4. Suggest specific fixes, not just flag problems
```

### 3. Add a rule (always-on)

```bash
mcpm skills add commit-style --type rule
```

Edit `rules/commit-style/SKILL.md`:

```markdown
---
name: commit-style
description: "Commit message conventions."
activation: always
---

Use conventional commits: feat:, fix:, docs:, refactor:, test:, chore:
Subject line: imperative mood, lowercase, no period, under 72 chars.
```

### 4. Add an agent

```bash
mcpm agents add reviewer
```

Edit `agents/reviewer/AGENT.md`:

```markdown
---
name: reviewer
description: "Code review specialist. Read-only, focuses on correctness and security."
model: sonnet
tools: [Read, Grep, Glob]
readonly: true
skills: [code-review]
---

You are a code reviewer. Focus on correctness, security, and maintainability.
Do NOT make changes. Report findings with severity and line references.
```

### 5. Sync to all clients

```bash
mcpm skills sync      # syncs skills + rules to all 15 clients
mcpm agents sync      # syncs agents to 6 clients
```

That's it. Your skills, rules, and agents are now in Claude Code, Cursor, Windsurf, VS Code Copilot, Continue.dev, JetBrains AI, Cline, Zed, Gemini CLI, Codex CLI, Amazon Q, Aider, Trae, Goose, and Roo Code.

## Day-to-Day Workflow

### Check what you have

```bash
mcpm skills ls        # list all skills and rules
mcpm agents ls        # list all agents
```

### Edit a skill, re-sync

```bash
# Edit the SKILL.md directly, then:
mcpm skills diff      # see what changed since last sync
mcpm skills sync      # re-transpile to all clients
```

### Validate before syncing

```bash
mcpm skills lint      # check format, best practices, Windsurf char limits
mcpm skills audit     # security scan for injection/exfiltration patterns
mcpm agents lint      # validate agent definitions
```

### Check sync status (useful for CI)

```bash
mcpm skills status            # shows ok/missing per client
mcpm skills status --strict   # exits non-zero on any drift (for CI pipelines)
```

### Remove a skill

```bash
mcpm skills uninstall code-review   # removes source + all 15 client outputs
```

### Clean all generated files

```bash
mcpm skills clean     # removes everything mcpm wrote, keeps your source files
```

## Sharing Skills

### Git-based sync across machines

```bash
# On machine 1: push your skills repo
cd ~/my-skills
git add -A && git commit -m "update skills" && git push

# On machine 2: configure git sync
mcpm skills git-sync --repo git@github.com:you/my-skills.git

# From now on, just run:
mcpm skills git-sync    # pulls + syncs to all clients
```

### Install from someone else's repo

```bash
# Add a tap (like Homebrew)
mcpm skills tap add anthropics/skills

# Search it
mcpm skills search "code review"

# Install a specific skill
mcpm skills install @anthropics/skills/code-review

# Install all skills from a repo
mcpm skills install @anthropics/skills
```

### Bundle for offline sharing

```bash
mcpm skills bundle --output my-skills.zip
# Send the zip to a colleague, then:
mcpm skills unbundle my-skills.zip
mcpm skills sync
```

## What Gets Generated Where

After `mcpm skills sync`, here's where files land per client:

| Client | Skills | Rules | Agents | Styles |
|--------|--------|-------|--------|--------|
| Claude Code | `.claude/skills/<name>/SKILL.md` | `.claude/rules/<name>.md` | `.claude/agents/<name>.md` | `.claude/output-styles/<name>.md` (Tier 1) |
| Cursor | `.cursor/rules/<name>/RULE.md` | `.cursor/rules/<name>/RULE.md` | `.cursor/agents/<name>.md` | `.cursor/rules/mcpm-output-style/RULE.md` (Tier 2) |
| Windsurf | `.windsurf/rules/<name>.md` | `.windsurf/rules/<name>.md` | -- | `.windsurf/rules/mcpm-output-style.md` (Tier 2) |
| VS Code Copilot | `.github/skills/<name>/SKILL.md` | `.github/instructions/<name>.instructions.md` | `.github/agents/<name>.agent.md` | `.github/instructions/mcpm-output-style.instructions.md` (Tier 2) |
| Continue.dev | `.continue/rules/<name>.md` | `.continue/rules/<name>.md` | -- | `.continue/rules/mcpm-output-style.md` (Tier 2) |
| JetBrains AI | `.aiassistant/rules/<name>.md` | `.aiassistant/rules/<name>.md` | -- | `.aiassistant/rules/mcpm-output-style.md` (Tier 2) |
| Cline | `.clinerules/<name>.md` | `.clinerules/<name>.md` | -- | `.clinerules/mcpm-output-style.md` (Tier 2) |
| Zed | `.rules` (all concatenated) | `.rules` (appended) | -- | `.rules` (managed block, Tier 2) |
| Gemini CLI | `.gemini/skills/<name>/SKILL.md` | `.gemini/skills/<name>/SKILL.md` | `.gemini/agents/<name>.md` | `.gemini/skills/mcpm-output-style/SKILL.md` (Tier 2) |
| Codex CLI | `.agents/skills/<name>/SKILL.md` | `AGENTS.md` (appended) | `.codex/agents/<name>.toml` | `.agents/skills/mcpm-output-style/SKILL.md` (Tier 2) |
| Amazon Q | `.amazonq/rules/<name>.md` | `.amazonq/rules/<name>.md` | -- | `.amazonq/rules/mcpm-output-style.md` (Tier 2) |
| Aider | `.mcpm/skills/<name>/SKILL.md` | `.mcpm/skills/<name>/SKILL.md` | -- | `.mcpm/skills/mcpm-output-style/SKILL.md` (Tier 2) |
| Trae | `.trae/rules/<name>.md` | `.trae/rules/<name>.md` | -- | `.trae/rules/mcpm-output-style.md` (Tier 2) |
| Goose | `.goose/skills/<name>/SKILL.md` | `.goose/rules/<name>.md` | -- | `.goose/rules/mcpm-output-style.md` (Tier 2) |
| Roo Code | `.roo/rules/<name>.md` | `.roo/rules/<name>.md` | `.roomodes` (JSON) | `.roomodes` with `style-` prefix (Tier 1) |
| AGENTS.md | `<available_skills>` block | `<available_skills>` block | -- | -- |

**Styles Tiers:** Tier 1 clients (Claude Code, Roo Code) get all styles synced -- user toggles in the client UI. Tier 2 clients get one style at a time via `mcpm styles apply`.

## Activation Modes Explained

| Mode | Behavior | Best for |
|------|----------|----------|
| `always` | Loaded into every conversation | Rules (coding standards, commit conventions) |
| `auto` | Agent decides based on description + file patterns | Skills scoped to specific file types |
| `agent` | Agent sees name+description, must choose to load | Specialized skills (API design, database optimization) |
| `manual` | User must explicitly invoke | Dangerous or expensive operations |

Not all clients support all modes. When a mode isn't supported, mcpm **downgrades toward more visible** (manual -> agent -> auto -> always) so the skill never silently disappears. Warnings are shown during sync.

## Output Styles

Output styles control HOW the AI responds -- tone, verbosity, persona. Unlike skills and rules, styles are **toggleable and mutually exclusive** (only one active at a time).

### Add a style

```bash
mcpm styles add concise-engineer
```

Edit `styles/concise-engineer/STYLE.md`:

```markdown
---
name: concise-engineer
description: "Terse, bullet-point responses. No filler."
keep-coding-instructions: true
---

- Answer in bullet points
- Skip preamble and summaries
- Code over prose
```

### Sync to native clients (Tier 1)

```bash
mcpm styles sync      # writes all styles to Claude Code + Roo Code
```

These clients have built-in style toggling -- the user picks one in the client UI.

### Apply to other clients (Tier 2)

```bash
mcpm styles apply concise-engineer    # injects into Cursor, Windsurf, etc.
mcpm styles apply teaching-mode       # replaces previous style
mcpm styles remove                    # deactivates on all Tier 2 clients
```

Only one style active per client. Applying a new one replaces the old.

### Check status

```bash
mcpm styles ls        # list available styles
mcpm styles status    # show active style per client
mcpm styles clean     # remove all style files from clients
```

## Gitignore

Add this to your project's `.gitignore` if you don't want generated files in version control:

```gitignore
# mcpm skills sync outputs (regenerated by mcpm skills sync)
.claude/skills/
.claude/rules/
.claude/agents/
.claude/output-styles/
.cursor/rules/
.cursor/agents/
.windsurf/rules/
.github/skills/
.github/instructions/
.github/agents/
.continue/rules/
.aiassistant/rules/
.clinerules/
.rules
.gemini/skills/
.gemini/agents/
.agents/skills/
.codex/agents/
.amazonq/rules/
.mcpm/skills/
.trae/rules/
.goose/
.roo/rules/
.roomodes
mcpm-skills.lock
```

Or keep them checked in so teammates who don't have mcpm still get the rules. Your call.

## Tips

- **Dry run first**: `mcpm skills sync --dry-run` shows what would change without writing
- **Single client testing**: `mcpm skills sync --client claude-code` to test one client at a time
- **The body is the same everywhere**: only frontmatter and file paths differ per client. Focus on writing good instructions, the transpilation handles the rest
- **Start with rules**: always-on rules (coding standards, commit conventions) are the simplest and most universally supported
- **Skills for scoped instructions**: use `globs` to make skills activate only for relevant files
- **Agents for personas**: agents bundle model + tools + skills + system prompt into a reusable package
- **Styles for tone**: output styles change how the AI responds without changing what it knows. Native toggle on Claude Code and Roo Code, apply/remove for everyone else
