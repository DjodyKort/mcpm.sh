"""mcpm-compression — a swappable context-compression layer for mcpm.

Models the compression layer (headroom today, rtk-only or none as alternatives)
as a declarative, version-controlled mcpm concern that can be synced across
clients/machines and swapped per context.

Two surfaces, deliberately separated (see provider.py):
- MCP server presence  → managed declaratively via mcpm's servers.json.
- API proxy + env vars → cannot be made fully declarative; this plugin GENERATES
  the activation artifacts (launchd plist, shell snippet) and a one-time manual
  load/login remains.
"""

__version__ = "0.1.0"
