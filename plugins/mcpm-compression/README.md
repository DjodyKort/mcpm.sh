# mcpm-compression

A swappable **context-compression layer** for mcpm. Manage which compression
provider routes your AI clients' traffic — declaratively, version-controlled,
swappable per context — instead of wiring it imperatively per client.

```
mcpm compression status                 # what's active + health + active preset
mcpm compression enable                  # default provider: headroom, preset: interactive
mcpm compression run -- <claude args>    # launch claude under this dir's policy (ensures proxy, execs claude)
mcpm compression proxy up|down|restart   # proxy lifecycle for the active preset
mcpm compression presets                 # list presets (--refresh re-snapshots from headroom)
mcpm compression use agent               # switch the active preset
mcpm compression set-provider rtk-only   # swap provider (lighter, no key-handling proxy)
mcpm compression disable [--teardown]    # off (--teardown also runs headroom's own removal)
mcpm compression doctor                  # diagnose (binaries, version pin, port, MCP)
mcpm compression env --cwd <dir>         # resolved env for a dir (for `eval` in a shell)
```

## Shell shims
`enable`/`sync` generate `~/.config/mcpm/compression-shims.zsh` — source it from `~/.zshrc`
for short commands (`hrclaude` → `mcpm compression run --`, `hrup`/`hrdown`/`hrrestart`/
`hrstat`/`hrperf`/`hrdash`). This replaces the old hand-maintained `headroom-aliases.zsh`:
all launch/lifecycle logic now lives in tested Python.

## Providers
- **headroom** — full API proxy (compresses every tool result) + MCP retrieve/stats tools.
- **rtk-only** — Bash/CLI-output compression via rtk's hook; no proxy, no API-key handling.
- **none** — disabled.

## Presets (headroom)
A preset bundles headroom's knobs (`mode`, `savings_profile`, the Read-outliner, port) as
**policy in `compression.json`** — the `HEADROOM_*` env is a config-time snapshot seeded
from `headroom agent-savings`, so the launch path reads config only. Built-ins:
- **interactive** — `cache` mode on :8787. Preserves the prompt-cache prefix; best for
  long interactive sessions.
- **agent** — `token` + `agent-90` on :8788. For batch/agent launches that share no
  prefix (cache mode's benefit is moot → aggressive compression is near-pure gain). A
  separate port lets it run alongside `interactive` (mode is fixed per proxy process).
  Read-outliner OFF by default — it's an A/B hypothesis, not a verdict.
- **balanced** — headroom's mid profile (`token`, lighter).

Route per directory with context rules (`compression.json` → `contexts`), e.g.
`{"match": "*/agent-batch/*", "preset": "agent"}`. The wrapper starts the right proxy on
the resolved port on demand.

## Two surfaces (the hard boundary)
- **MCP server presence** is managed declaratively via mcpm's `servers.json` +
  `mcpm client sync`.
- **The API proxy + `ANTHROPIC_BASE_URL`** cannot be made fully declarative. This
  plugin *generates* activation artifacts:
  - a sourceable shell snippet (`~/.config/mcpm/compression-env.sh`)
  - a launchd plist (`~/Library/LaunchAgents/sh.mcpm.compression.proxy.plist`)
  A one-time `launchctl load` / shell source remains your step.

## Update model
- Provider **version** is managed by its own installer (e.g. `uv tool upgrade
  headroom-ai`). This plugin manages **presence + activation**, never the version.
  The two never collide.

## Install (into mcpm's environment)
```
uv pip install -e plugins/mcpm-compression --python "$(dirname "$(dirname "$(readlink -f "$(command -v mcpm)")")")"
```
Then `mcpm compression --help` should appear (loaded via the `mcpm.plugins`
entry point).
