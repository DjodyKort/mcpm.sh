# mcpm-compression — architecture & integration contract

Status: living doc. headroom: **track latest** via uv constraint `>=0.27.0` (extras
`proxy,code,ml`). `CONTRACT_VERSION` (currently `0.27.0`) marks the version the bundled
fallback + fixtures were verified against; `mcpm compression update` upgrades and
re-snapshots the live contract (see Versioning).

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

## Integration contract (verified at CONTRACT_VERSION 0.27.0)

### Documented-stable — safe to depend on at runtime
| Surface | Use |
| --- | --- |
| `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>` | route a client through the proxy |
| `headroom proxy --port <p> [--mode token\|cache]` | start a proxy |
| `GET /health` → `{service,status,ready,version,config{...}}` | liveness + running-config probe |
| `GET /stats` | savings/cache stats (read by `hrperf`/dashboard) |
| `headroom mcp install` / `headroom mcp uninstall` | MCP tool registration (idempotent) |
| core `HEADROOM_*` env vars | proxy configuration |

### Undocumented — re-verified on update, config-time only (never hot-path)
| Surface | Use | Mitigation |
| --- | --- | --- |
| `headroom agent-savings --profile <name> --format json` | seed a preset's env snapshot | snapshotted live into `compression.json`; `update` re-snapshots on every upgrade; fixtures pin the offline fallback (identical 0.26→0.27) |
| `headroom install apply\|start\|stop\|status\|remove` (`--profile/--port/--mode`) | optional always-on persistence | opt-in only; default is on-demand wrapper |
| profile names `agent-90`, `balanced` | preset seeds | captured in fixtures; user-overridable |

### Versioning — track latest, re-verify on update
- We do **not** hard-pin. uv constraint is `>=MIN_VERSION` (0.27.0); `mcpm compression
  update` runs `uv tool upgrade headroom-ai` and then **re-snapshots every preset's env**
  from the new binary, so the synced policy stays truthful across upgrades.
- `CONTRACT_VERSION` is the version the bundled fallback constant + `tests/fixtures/`
  were captured/verified at. Running newer is expected and fine — the **live snapshot is
  authoritative**; the constant is only an offline fallback (headroom off PATH).
- `status`/`doctor` report running vs contract: below contract ⇒ warn + suggest `update`;
  at/above ⇒ ok. Never a hard fail on "newer".
- The 0.26→0.27 bump was contract-clean: `agent-savings` (both profiles) and `/health`
  shape are byte-identical; 0.27's `HEADROOM_TELEMETRY=off` default is moot (we set it
  explicitly). When bumping, run `update` (and `presets --refresh`); if `agent-savings`
  ever changes, refresh `tests/fixtures/` + the fallback constant.

### Drift / gotchas
- `POST /admin/runtime-env` is in headroom's README but **absent through 0.27.0** → mode
  change requires a proxy **restart**, never per-request.
- Mode is **cold-start per process**; simultaneous cache+token ⇒ two proxies/ports.
- Subagents inherit the parent's `ANTHROPIC_BASE_URL` ⇒ routing is per **launched**
  client/dir, not per subagent.

## `headroom_runtime` adapter (the swap seam)

Single module `providers/headroom_runtime.py` — the only place that shells out to /
HTTP-calls headroom. Implemented:

- `snapshot_profile_env(profile) -> dict[str,str]` — config-time; runs `headroom
  agent-savings --profile <p> --format json`; falls back to `_FALLBACK_PROFILE_ENV`
  (lock-stepped to `tests/fixtures/`) when headroom is absent.
- `proxy_health(port) -> dict` — `GET /health` → `{ok,detail,version,config}`.
- `proxy_up(port, env) / proxy_down(port)` — on-demand lifecycle: reuse a healthy
  proxy, else detached `Popen` (mcpm's `RouterRuntime` pattern) + poll `/health`; stop
  via the pid from `/health` (fallback `lsof`).
- `version() -> str|None` / `version_tuple()` — `headroom --version` (status/doctor compare
  vs `CONTRACT_VERSION`).
- `upgrade() -> (ok, detail, before, after)` — `uv tool upgrade headroom-ai`; backs
  `mcpm compression update` (which then re-snapshots preset env).
- `mcp_uninstall() / unwrap(client)` — strip path; delegate to `headroom mcp uninstall`
  / `headroom unwrap`.

`providers/headroom.py` is a thin policy→env mapping (`env_for_preset`); no hardcoded env,
no plist generation (deleted).

**Launch + lifecycle = Python (mcpm owns it).** `mcpm compression run [-- args]` resolves
the per-cwd `(provider, preset)`, calls `proxy_up(preset.port, env)`, then `os.execvpe`s
`claude` with the preset env (hands over the TTY). `mcpm compression proxy up|down|restart`
manages the active preset's proxy. The plugin generates `~/.config/mcpm/compression-shims.zsh`
(`hrclaude → mcpm compression run --`, `hrup/hrdown/...`) as an activation artifact; the
user sources it from `~/.zshrc`, replacing the old hand-maintained `headroom-aliases.zsh`.
Mode-change requires `proxy restart` (cold-start only). A/B is preset-driven (`use agent`
/ `use interactive`).

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
(`config.py:71`). Verified syncing: `mcpm sync push` pushes it (and the binary skill
assets) into the encrypted bundle.

This needed a fix in the mcpm-sync submodule: `create_bundle` read every file as UTF-8 and
crashed on binary skill assets (`skills/figma-*/*.zip`/`*.png`), aborting *all* pushes.
Fixed by a per-entry `encoding: "utf-8"|"base64"` on `SyncEntry` with a binary round-trip
(base64 before encryption, `write_bytes` on apply) — mcpm-sync `181d88c`, superproject
pointer bump.

## Contract fixtures
`tests/fixtures/agent_savings_agent-90.json`, `…_balanced.json`, `health_contract.json`
— verified at `CONTRACT_VERSION` (0.27.0; identical to 0.26.0). Tests assert the emitted
env / fallback constant against these instead of a live shell-out. Refresh them only if a
future `headroom agent-savings` actually changes (run `update` first, then re-capture).
