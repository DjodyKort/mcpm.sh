"""mcpm worker process.

A worker is one subprocess managed by the router's WorkerSupervisor. It
binds an IPC socket, spawns the upstream stdio MCP server as its child,
and multiplexes incoming JSON-RPC frames from the router onto the single
upstream child via id rewriting. Stderr from the child is teed to a log
file and broadcast to active sessions as `notifications/message`.
"""
