# mcpm-compression

A swappable **context-compression layer** for mcpm. Manage which compression
provider routes your AI clients' traffic — declaratively, version-controlled,
swappable per context — instead of wiring it imperatively per client.

```
mcpm compression status                 # what's active + health + active preset
mcpm compression enable                  # default provider: headroom, preset: interactive
mcpm compression run -- <claude args>    # launch claude under this dir's policy (ensures proxy, execs claude)
mcpm compression proxy up|down|restart   # proxy lifecycle for the active preset
mcpm compression presets                 # list presets (--refresh re-snapshots from the pinned build)
mcpm compression pin [<version>]         # show/set the exact headroom pin (--install --refresh)
mcpm compression update [--latest]       # bump the pin to newest (or --to X), install + re-snapshot (--accept)
mcpm compression verify                  # measure real cache behaviour from Claude Code transcripts
mcpm compression use agent               # switch the active preset
mcpm compression set-provider rtk-only   # swap provider (lighter, no key-handling proxy)
mcpm compression disable [--teardown]    # off (--teardown also runs each provider's own removal)
mcpm compression doctor                  # diagnose (pin drift, provenance, port, MCP)
mcpm compression env --cwd <dir>         # resolved env for a dir (for `eval` in a shell)
```

## Shell shims
`enable`/`sync` generate `~/.config/mcpm/compression-shims.zsh` — source it from `~/.zshrc`
for short commands (`hrclaude` → `mcpm compression run --`, `hrup`/`hrdown`/`hrrestart`/
`hrstat`/`hrupdate`/`hrperf`/`hrdash`; `hrupdate` bumps the pin to newest + re-snapshots).
This replaces the old hand-maintained `headroom-aliases.zsh`:
all launch/lifecycle logic now lives in tested Python.

## Providers
- **headroom** — full API proxy (compresses every tool result) + MCP retrieve/stats tools.
- **rtk-only** — Bash/CLI-output compression via rtk's hook; no proxy, no API-key handling.
- **parsec** — Dasein Labs' Claude Code plugin: hook-level re-read/command-loop blocking
  plus its own local proxy and `scout` MCP tools. See below.
- **none** — disabled.

### parsec
```
mcpm compression enable --provider parsec    # install + enable the plugin
mcpm compression status                       # plugin state, routing, version, key
mcpm compression disable                      # off — reversible, keeps ~/.parsec
mcpm compression disable --teardown           # also deletes ~/.parsec and its savings ledger
```

Read this before enabling it — parsec is a different *kind* of thing from headroom:

| | headroom | parsec |
| --- | --- | --- |
| what it is | a binary mcpm starts | a Claude Code plugin Claude Code starts |
| what it routes | only launches wrapped by `mcpm compression run` | **every** `claude` session |
| how it routes | `ANTHROPIC_BASE_URL` in the launch env | `ANTHROPIC_BASE_URL` written into `~/.claude/settings.json` |
| hooks | none | `PreToolUse` on Read/Bash, `PostToolUse` on Read/Bash/Edit/Write, SessionStart, Stop |
| your agent | untouched | replaced with `parsec:code` (its own system prompt) |
| source | open (PyPI wheel we pin exactly) | closed prebuilt binary, self-updating via marketplace |
| off-machine | nothing (telemetry forced off) | your code leaves the machine on **every tier but Enterprise**: Pro sends chunk text + structural features to their scoring API, the free tier sends tokens "but never stored". A `psc_` key additionally reports savings to their dashboard |
| price | — | list $40/mo, **$0 at the time of writing** (2026-09-02: the site strikes the price through and shows "Free"). Cost is not the axis to decide this on; the data flow above is |

Because both providers claim `ANTHROPIC_BASE_URL`, they are mutually exclusive. Selecting
another provider therefore *disables* parsec's plugin rather than merely not configuring it
— its hooks would otherwise keep firing underneath. `doctor` has an **endpoint conflict**
check for the case where parsec is still routing while the policy says something else.

Not a replacement for `rtk-only`: parsec has no rtk in it. Its hook layer does a related
job (blocking re-reads, breaking repeated commands) but by a different mechanism, and its
own no-reread gate is off unless `PARSEC_NOREREAD=on`.

parsec is **not pinned** the way headroom is — it self-updates through the Claude Code
marketplace, so `CONTRACT_VERSION` in `parsec_runtime` is a marker the CLI reports drift
against, not a constraint it enforces.

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

## Version model
The provider version is **pinned exactly** in `compression.json`
(`provider_version.pin`), and this plugin owns it. headroom ships ~2 releases/week; from
0.30 a bare proxy seeds a default persona into every knob you didn't declare, so a
floating `>=` constraint rewrites your runtime without touching your config. It did:
0.31.0 arrived unreviewed with an open, measured cache-busting bug (headroom#2085).

```
mcpm compression pin                     # show pin vs installed
mcpm compression pin 0.29.0 --install --refresh   # set, install exactly, re-snapshot knobs
mcpm compression seal --apply            # declare the posture a live proxy is running
mcpm compression verify                  # measure real cache behaviour from your transcripts
```

## Measuring (does compression actually pay?)

`verify` reads **provider-billed** usage — `cache_read_input_tokens` /
`cache_creation_input_tokens` — from Claude Code's own transcripts. Never headroom's
`/stats`: its savings accounting was wrong four separate ways across 0.28–0.31.

Transcripts record no endpoint, so `run` keeps a launch ledger
(`~/.config/mcpm/compression-launches.jsonl`, machine-local, not synced) and `verify`
partitions sessions three ways:

| bucket | meaning |
| --- | --- |
| `proxied` | went through headroom |
| `plain` | `run` launched it but deliberately didn't route — a real control |
| `unattributed` | no matching launch (predates the ledger, or started outside `run`) — the baseline, but not a control |

The headline is the **read ratio** (`read / (read + create)`): a working cache reads far
more than it writes, and a busted prefix turns cheap reads into expensive writes. `verify`
fails under 90% read ratio or 15× read:write, and refuses to judge at all with no proxied
sessions rather than reporting a blended number.

`run` refuses to route through a build that doesn't match the pin and falls back to plain
`claude` (`--force` overrides). Losing compression is cheap; losing the prompt cache is not.

## Install (into mcpm's environment)
```
uv pip install -e plugins/mcpm-compression --python "$(dirname "$(dirname "$(readlink -f "$(command -v mcpm)")")")"
```
Then `mcpm compression --help` should appear (loaded via the `mcpm.plugins`
entry point).
