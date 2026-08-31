# mcpm-compression — architecture & integration contract

Status: living doc. headroom: **pinned exactly** via uv constraint `==<pin>` (extras
`proxy,code,ml`), recorded in `compression.json` → `provider_version.pin`. Current pin:
`0.29.0`. tokenade: **evaluated and rejected 2026-07-28** (see the tokenade section —
binary uninstalled, provider retained as the seam's reference hook implementation); its
pin (`tokenade_version.pin`, `1.0.1`) records the build the evaluation ran against.
Bumping a pin is a reviewed act, never a side effect (see Versioning; `pin`/`update`
take `--provider`).

> **Reversal note.** This supersedes `49e7fab` ("track latest headroom"), which replaced
> the earlier `==0.26.0` pin with a `>=` floor. Track-latest is what let 0.31.0 arrive
> unreviewed, carrying an open measured cache-busting bug (headroom#2085: 4.4x cache-write
> inflation) and a new `DEFAULT_PROFILE="coding"` that seeds 19 undeclared knobs into any
> proxy. Recorded here so the un-pin isn't re-litigated from first principles.
> Full rationale: `_docs/specs/open/compression-headroom-pinning.md`.

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

### Versioning — pin exactly, bump deliberately
- The uv constraint is `==provider_version.pin`. `mcpm compression pin <v> --install
  --refresh` sets it, installs that exact build, and re-snapshots every preset's knobs
  from **it**, recording `snapshot_version` so the config says which build it describes.
- `mcpm compression update [--to X | --latest] [--accept]` is the sanctioned bump: it
  resolves a target (newest published on PyPI when unspecified), records it as an **exact**
  pin, installs, and re-snapshots. It is *not* a return to track-latest — the constraint
  stays `==`, the target is resolved once and frozen into the config, and `--accept` gates
  the mutation (a bare invocation only previews). `hrupdate` = `update --latest --accept`.
  Newest is unverified against the recorded fixtures by construction, so it always prints a
  reminder to run `verify`.
- **Newer is unverified, not fine.** `status`/`doctor` hard-fail on any mismatch, in either
  direction. The old `>=` check reported 0.31-against-contract-0.27 as *ok* — which is how
  four releases of drift went unnoticed.
- **There is no offline fallback env.** A bundled constant made one preset name resolve to
  two runtimes depending on whether the binary was on PATH. `snapshot_profile_env` now
  raises `HeadroomUnavailable` instead of guessing.
- Knob applicability is **measured, not assumed**: knobs genuinely read from env are 114
  (0.27) → 137 (0.29) → 147 (0.31). `HEADROOM_PROTECT_READS`, `DEDUPE`, `TOOL_SEARCH` and
  `LOSSLESS_THEN_LOSSY` are 0.31-only, so declaring them on a 0.29 pin would claim
  properties that build never honours. `KnobSpec.applies` gates them.
- **Do not trust headroom's reported savings.** Its accounting was wrong four distinct ways
  across 0.28–0.31 (#1429 cached requests priced at $0, #1653 disagreeing dashboard
  denominators, #1800 cache-write premiums not subtracted, cache-mode history dropped).
  `mcpm compression verify` reads provider-billed usage from Claude Code's own transcripts
  instead.

### Drift / gotchas
- `POST /admin/runtime-env` **exists** (verified in the 0.27.0 wheel at `server.py:2386`,
  still present at 0.31.0) — an earlier revision of this doc claimed it was absent. But
  `HEADROOM_MODE` is **not** a registered hot-reload knob (`proxy/runtime_env.py` covers
  only the output-shaper knobs), so a mode change still requires a proxy **restart** and
  the two-port design stands. Right conclusion, wrong reason.
- From **0.30**, `seed_proxy_env_defaults()` runs at both proxy entry points and seeds
  `DEFAULT_PROFILE="coding"` into every unset knob (`setdefault` semantics, so explicit env
  still wins). An undeclared knob is therefore a knob the vendor owns — and silently
  re-owns on upgrade. This is why presets declare every knob explicitly, offs included.
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

## `tokenade` provider (second independent provider — the seam's first real swap)

> **Verdict: REJECTED 2026-07-28, before ever being engaged.** Built, tested, and
> live-verified up to (but not including) `enable`; the user walked away on the trust
> trade. Deciding factors, so this isn't re-litigated from first principles: (1) the
> engine is a closed Rust binary whose license forbids inspection, so every
> data-handling claim ("code never leaves the machine", redaction) is unverifiable on
> a machine that carries **client code**; (2) hooks are **global** — per-directory
> context rules cannot exempt client repos, so the only scoping is manual
> time-slicing; (3) 4 days on npm, zero independent reputation, no privacy policy, no
> legal entity, account-gated even on the free tier. None of these are code defects —
> re-evaluate if the engine goes open source or accrues months of independent track
> record. Machine state at rejection: binary + `~/.tokenade` removed, hooks were never
> installed, no account was ever created. The provider code below is retained as the
> seam's reference hook-runtime implementation (inert unless selected).

Added 2026-07-28. Tokenade (`@tokenade/cli`, closed-source Rust engine behind an
auditable npm installer shim) is **not** a proxy: no port, no `ANTHROPIC_BASE_URL`.
`tokenade install` writes PostToolUse/PreToolUse/passive **hooks** into Claude Code's
`settings.json` — compaction happens at the tool-output boundary, *after* the cached
prefix, which is structurally why it can't reproduce headroom's #2085 prefix-rewrite
failure. Trust posture at adoption: real credentialed author, clean installer (tarball
read line-by-line), but the engine is closed, 4 days on npm, zero independent
reputation, and its savings numbers come from the author's own benchmark. Hence:
opt-in, pinned, and judged only by `verify` (billed transcript usage), never by its
own `gain` ledger.

Adapter: `providers/tokenade_runtime.py` (the only module that shells out to
`tokenade`). Commands used: `install --only claude-code` / `uninstall` /
`unwrap-mcps` / `upgrade --off` / `healthcheck --json` / `--version`. Hook
presence/removal is done by reading/writing `settings.json` directly — the one
deviation from "drive the vendor", because the vendor's only removal path also wipes
`~/.tokenade` data, which is disproportionate for `disable` (the kill switch must
stay cheap).

Pilot posture (`TokenadeSettings`, both default off):

- **`mcp_wrap` off.** `tokenade install` wraps every MCP entry in `~/.claude.json`
  (16 on this machine) in `tokenade mcp-proxy`. That (a) fights mcpm's own client
  sync, which owns those entries, and (b) its on-demand tool loading varies the tool
  manifest turn-to-turn — tool definitions are part of the cached prefix, so this is
  the same failure *class* headroom was retired for, undisclosed by the vendor.
  `engage` runs `unwrap-mcps` right after `install`; the vendor's own docs say hooked
  agents get MCP-result folding without the wrap.
- **`claude_md` off.** The vendor's CLAUDE.md block would be appended to
  `~/.claude/CLAUDE.md`, which is generated by sync-claude and clobbered on next
  sync. If wanted, it belongs in the canonical Codeforward source.

Semantics that differ from the proxy provider — surfaced, not hidden:

- **Engagement is global.** Hooks apply to every session however launched. Context
  rules (`*/clients/*` → none) cannot exempt a launch; `run` records `routed` from
  *reality* (hooks present + binary live) and the ledger pin is the **installed**
  build, drifted or not. The kill switch is `disable` (hook removal + unwrap), not a
  per-launch refusal; drift refusal happens at **engage** time instead.
- **A/B is time-sliced.** While hooks are live, `unattributed` sessions are optimized
  too, so the baseline bucket is contaminated for that period — `verify` prints this
  whenever tokenade hooks are present. `verify --by-pin` keys buckets as
  `provider:pin` so headroom and tokenade arms never blend.
- **Self-updater off.** `engage` runs `tokenade upgrade --off` (sentinel
  `~/.tokenade/auto-update-off`); doctor flags it if re-enabled. A 24h background
  updater is track-latest with extra steps.
- **rtk overlap.** tokenade's Bash-rewrite hook duplicates rtk's PreToolUse hook;
  doctor flags double compaction. The vendor installer offers rtk migration
  interactively (we run it with stdin closed → prompts take their defaults, i.e. no).
- **Not yet delegated to vendor install:** per-project rule scaffolding ("CLAUDE.md,
  AGENTS.md, .cursorrules on first agent session") is vendor behaviour we have not
  found a switch for — audit client repos for stray scaffolds during the pilot.

`doctor` guardrails: pin drift, hooks-vs-policy mismatch **in both directions**
(enabled-but-absent = no-op; disabled-but-present = "off" is a lie), self-updater
state, `mcp-proxy` residue in `~/.claude.json`, rtk overlap, and a leftover
`ANTHROPIC_BASE_URL` under a non-proxy provider.

## Strip path

`mcpm compression disable [--teardown]`:
1. Always: remove `mcpm_headroom` from clients + `servers.json`; remove the shell
   snippet; clean up any legacy launchd plist left by older versions. When tokenade is
   (or its hooks are still) engaged: disengage first — `unwrap-mcps` + surgical hook
   removal from settings.json (backup at `settings.json.tokenade-bak`), keeping
   `~/.tokenade` data.
2. `--teardown` also (scoped to the outgoing provider): headroom → `headroom mcp
   uninstall` + `headroom unwrap claude`; tokenade → `tokenade uninstall` (which *does*
   wipe `~/.tokenade`).
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
