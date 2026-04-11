# Claude Desktop Skills Integration

| Phase | Status |
|-------|--------|
| Investigation | Done |
| Filesystem injection | Failed -- server-managed cache |
| API injection | Blocked -- org-scoped, not per-user |
| Implementation | Deferred |

## Summary

Investigated programmatic skill injection into Claude Desktop. The goal was to let `mcpm skills sync` push skills directly into Desktop alongside the 15+ other clients. This turned out to be significantly harder than expected.

## What We Learned

### 1. The `skills-plugin/` directory is a server-managed download cache

**Path:** `%APPDATA%/Claude/local-agent-mode-sessions/skills-plugin/{org_id}/{account_id}/`

This directory contains:
- `manifest.json` -- registry of all skills (Anthropic + user)
- `skills/{name}/SKILL.md` -- skill files
- `.claude-plugin/plugin.json` -- plugin metadata

**The SkillsPlugin sync cycle (every 600s or on restart):**
1. Calls `GET ${apiBase}/api/organizations/${orgId}/skills/list-skills?include_wiggle_skills=true`
2. Compares server response with local manifest
3. Downloads new/updated skills, **removes anything not from the server as "orphans"**
4. Writes manifest

Any files we inject get cleaned up on the next sync cycle. We confirmed this by watching the logs:
```
[SkillsPlugin] Delta: 0 to download, 1 to remove   ← our injected skill
[SkillsPlugin] Sync complete: 0 downloaded, 1 removed, 0 orphans cleaned
```

### 2. Multiple org/account directories

The directory has `{org_id}/{account_id}` subdirectories. A user can belong to multiple orgs. The active org changes based on which workspace they're in. This made auto-detection unreliable -- we kept writing to stale/inactive account dirs.

### 3. The Skills API is org-scoped, not per-user

The `POST /v1/skills` API (beta, requires `anthropic-beta: skills-2025-10-02`) creates skills at the organization level. There is:
- No `visibility` or `scope` field
- No per-user filtering
- `creatorType: "user"` is attribution, not access control

**Impact:** In a team org, any skill uploaded via API is visible to ALL org members. This is unacceptable for personal skill configurations.

### 4. UI upload goes through the web frontend

The skill upload in Claude Desktop is handled by the Electron renderer (web context) calling claude.ai's frontend API, not by the main process. The main process only handles the sync/download side. This means we can't intercept or replicate the upload flow from the main process.

### 5. Skills are synced cross-device

Confirmed: a skill uploaded via UI on Windows appeared on macOS immediately. The server is the source of truth, not the filesystem.

## What Works Today

| Approach | Status | Notes |
|----------|--------|-------|
| Claude Code CLI (`~/.claude/skills/`) | **Works** | Already implemented in mcpm |
| All other 15+ clients | **Works** | Already implemented in mcpm |
| Claude Desktop MCP servers | **Works** | Via `claude_desktop_config.json` |
| Claude Desktop skills via API | **Blocked** | Org-scoped, not per-user |
| Claude Desktop skills via filesystem | **Failed** | Server overwrites on sync |
| Claude Desktop skills via UI | **Manual** | ZIP upload, per-user, works |

## Future Options

### 1. ZIP bundler (low effort, manual)
`mcpm skills export --format zip` generates upload-ready ZIPs. User drags into Desktop's Customize > Skills > +. Per-user because each user uploads their own.

### 2. Anthropic adds per-user skills (waiting)
GitHub issues requesting this: #20697, #25771, #22648. No timeline from Anthropic.

### 3. Browser automation via CDP (fragile)
Launch Desktop with `--remote-debugging-port=9222`, automate the upload UI via Playwright/CDP. Confirmed feasible by community. Fragile, breaks on app updates.

### 4. Per-user API scope (if Anthropic adds it)
A `visibility: "personal"` or `scope: "user"` field on `POST /v1/skills` would solve everything. We already have the API transpiler code ready to reactivate.

## Source Code from Investigation (removed, preserved here)

The following files were created and then removed after the approach proved unviable:
- `src/mcpm/utils/claude_desktop.py` -- path discovery, manifest helpers
- `src/mcpm/skills/transpilers/claude_desktop.py` -- filesystem injection transpiler
- `src/mcpm/styles/transpilers/claude_desktop.py` -- styles as Desktop skills
- `src/mcpm/skills/transpilers/claude_api.py` -- Anthropic Skills API transpiler

Key findings from the source code (`app.asar/.vite/build/index.js`):
- Skills fetched via: `GET ${Pr()}/api/organizations/${orgId}/skills/list-skills`
- Skills downloaded via: `GET ${Pr()}/api/organizations/${orgId}/skills/download-dot-skill-file?skill_id=${id}`
- OAuth token scopes: `user:inference user:file_upload`
- Sync interval: 600,000ms (10 minutes)
- Orphan cleanup: any skill not in server response gets deleted locally
