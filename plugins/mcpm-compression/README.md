# mcpm-compression

A swappable **context-compression layer** for mcpm. Manage which compression
provider routes your AI clients' traffic — declaratively, version-controlled,
swappable per context — instead of wiring it imperatively per client.

```
mcpm compression status                 # what's active + health
mcpm compression enable                 # default provider: headroom
mcpm compression set-provider rtk-only  # swap (lighter, no key-handling proxy)
mcpm compression disable                # off
mcpm compression doctor                 # diagnose
```

## Providers
- **headroom** — full API proxy (compresses every tool result) + MCP retrieve/stats tools.
- **rtk-only** — Bash/CLI-output compression via rtk's hook; no proxy, no API-key handling.
- **none** — disabled.

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
