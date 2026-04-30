"""mcpm router daemon.

A self-launching, token-authenticated, idle-evicting HTTP gateway for stdio
MCP servers. Boots via the gpg-agent pattern (no launchd / systemd / Windows
scheduled task), shares one upstream child across all connected clients, and
self-shutdowns after `router_idle_timeout` of zero traffic.
"""
