# mcpm-compression — architecture & integration contract

Status: living doc. Pinned headroom: **`headroom-ai==0.26.0`** (extras `proxy,code,ml`).

## What this plugin is (and is not)

mcpm owns the compression **policy**; headroom owns the compression **runtime**.

- **Policy (mcpm, this plugin):** which provider is active, the compression *mode*
  (cache/token) and *preset*, per-directory routing rules, which clients get the MCP
  entry — all in one declarative, synced `~/.config/mcpm/compression.json`.
- **Runtime (headroom binary):** the proxy process, the ML compression, the savings
  profiles, MCP tools. We never reimplement these; we drive them.

The hard boundary: a plugin/hook **cannot** set `ANTHROPIC_BASE_URL` for the `claude`
process (read at launch), so the activation env is emitted for a thin shell wrapper to
`eval`. Everything else is declarative.

## Modularity: two swap axes

1. **Swap the provider** (headroom → future compressor). Seam = the
   `CompressionProvider` ABC (`provider.py`). Every headroom-specific CLI/HTTP call is
   confined to **one** adapter module, `providers/headroom_runtime.py`. A headroom
   version bump or a provider swap touches that one file.
2. **Strip the whole layer.** `mcpm compression disable` removes our MCP presence +
   generated artifacts. Optional `--teardown` additionally runs headroom's documented
   removal. Policy is one deletable file. (headroom's own `~/.headroom/` data persists —
   upstream issue #748, no single uninstall.)

Rule: the **launch hot-path depends only on documented-stable contracts**. Undocumented
commands are used only at **config time** (snapshotting into our config), never per launch.

## Integration contract (against pinned 0.26.0)

### Documented-stable — safe to depend on at runtime
| Surface | Use |
| --- | --- |
| `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>` | route a client through the proxy |
| `headroom proxy --port <p> [--mode token\|cache]` | start a proxy |
| `GET /health` → `{service,status,ready,version,config{...}}` | liveness + running-config probe |
| `GET /stats` | savings/cache stats (read by `hrperf`/dashboard) |
| `headroom mcp install` / `headroom mcp uninstall` | MCP tool registration (idempotent) |
| core `HEADROOM_*` env vars | proxy configuration |

### Undocumented — version-pinned, config-time only (never hot-path)
| Surface | Use | Mitigation |
| --- | --- | --- |
| `headroom agent-savings --profile <name> --format json` | seed a preset's env snapshot | snapshot once into `compression.json`; pinned to 0.26.0; fixtures in `tests/fixtures/` |
| `headroom install apply\|start\|stop\|status\|remove` (`--profile/--port/--mode`) | optional always-on persistence | opt-in only; default is on-demand wrapper |
| profile names `agent-90`, `balanced` | preset seeds | captured in fixtures; user-overridable |

### Drift / gotchas (0.26.0)
- `POST /admin/runtime-env` is in headroom's README but **absent in 0.26.0** → mode
  change requires a proxy **restart**, never per-request.
- Mode is **cold-start per process**; simultaneous cache+token ⇒ two proxies/ports.
- Subagents inherit the parent's `ANTHROPIC_BASE_URL` ⇒ routing is per **launched**
  client/dir, not per subagent.
- 0.27.0 (released 2026-06-22) flips `HEADROOM_TELEMETRY` default to off and extends
  `unwrap`; we pin 0.26.0. `doctor` warns when the live `headroom --version` ≠ pin.

## `headroom_runtime` adapter (the swap seam)

Single module `providers/headroom_runtime.py` — the only place that shells out to /
HTTP-calls headroom. Implemented:

- `snapshot_profile_env(profile) -> dict[str,str]` — config-time; runs `headroom
  agent-savings --profile <p> --format json`; falls back to `_FALLBACK_PROFILE_ENV`
  (lock-stepped to `tests/fixtures/`) when headroom is absent.
- `proxy_health(port) -> dict` — `GET /health` → `{ok,detail,version,config}`.
- `version() -> str|None` — `headroom --version` (doctor drift check vs `PINNED_VERSION`).
- `mcp_uninstall() / unwrap(client)` — strip path; delegate to `headroom mcp uninstall`
  / `headroom unwrap`.

`providers/headroom.py` is a thin policy→env mapping (`env_for_preset`); no hardcoded env,
no plist generation (deleted).

**Lifecycle = on-demand wrapper (default).** The slimmed `~/.config/headroom-aliases.zsh`
`eval`s `mcpm compression env --cwd $PWD` and starts a proxy on the resolved
`HRCOMPRESS_PORT` with the full preset env. This is the only lifecycle path and it fully
supports presets (mode + savings) per port.

**`headroom install` persistence: deferred.** `install apply` bakes `HEADROOM_MODE` but
exposes no way to inject the savings-profile env, so a persisted proxy couldn't carry
agent-90. Rather than hack the generated plist, persistence is left to the on-demand
wrapper (which carries the full env). Revisit if headroom adds env injection.

## Strip path

`mcpm compression disable [--teardown]`:
1. Always: remove `mcpm_headroom` from clients + `servers.json`; remove the shell
   snippet; clean up any legacy launchd plist left by older versions.
2. `--teardown` also: `headroom mcp uninstall` + `headroom unwrap claude` (best-effort,
   reported).
3. Residue: `~/.headroom/` (toin/savings/memory) is left in place — documented, not ours.

## Sync

`compression.json` carries the full policy (provider + presets + mode + contexts) and is
wired into mcpm-sync `get_global_sync_files()` as `global/compression.json`
(`config.py:71`). The migrated policy is in place and ready to sync.

**Known external blocker:** `mcpm sync push` currently fails for an *unrelated*
mcpm-sync defect — `engine.py:94` reads every `skills_repo` file as UTF-8 and crashes on
binary skill assets (e.g. a `.zip`/`.png` under `skills/figma-*`). This breaks *all*
pushes (the reason nothing has synced since those assets were added), not just
compression. Fix belongs in the mcpm-sync submodule (read bytes / base64 for non-text, or
skip with a warning) — tracked separately from this plugin.

## Contract fixtures
`tests/fixtures/agent_savings_agent-90.json`, `…_balanced.json`, `health_contract.json`
— captured from pinned 0.26.0; Phase 2 tests assert emitted env against these instead of
a live shell-out.
