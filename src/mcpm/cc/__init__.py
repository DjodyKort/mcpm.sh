"""Claude Code plugin lifecycle (Claude-Code-only).

Phase 1 ships the "pull latest from remote" slice: refresh marketplace catalogs and
update installed Claude Code plugins from their remotes, mirroring ``mcpm update`` for
MCP servers.

Mechanism is hybrid: state is read from Claude Code's on-disk JSON
(``~/.claude/plugins/known_marketplaces.json``, ``~/.claude/settings.json``) while every
mutation is performed through the ``claude plugin`` CLI -- the authoritative path that
avoids desyncing Claude Code's internal tracking.
"""
