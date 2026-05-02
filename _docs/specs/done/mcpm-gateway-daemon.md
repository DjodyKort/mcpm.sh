# mcpm Router and Direct HTTP Configuration

**Type:** Feature (architectural)
**Scope:** `src/mcpm/clients/`, `src/mcpm/commands/`, new `src/mcpm/router/` and `src/mcpm/worker/`
**Branch:** `feat/router-and-direct-http` off `main`

> Earlier iterations of this spec proposed a monolithic gateway daemon. That design is preserved as the Alternative Architecture section. The current recommendation is the ultra-hybrid model below: a small self-launching router for stdio servers, raw direct configuration for HTTP servers, and a stdio shim for clients that do not speak HTTP MCP.

---

## Status

| Phase | Status | Landed in |
|-------|--------|-----------|
| 1. Analysis | Done | discovery + live JSON-RPC trace, Apr 2026 |
| 2. Specification | Done | this document |
| 3. Implementation: Phase 1 (direct HTTP for HTTP servers) | Done | `1e7b0cd` |
| 3. Implementation: Phase 2 (RouterRuntime + token + Starlette app) | Done | `1e7b0cd` |
| 3. Implementation: Phase 3 (worker supervisor + shim + multiplexing) | Done | `1e7b0cd` |
| 3. Implementation: Phase 4 (gateway / mode / bridge / client sync) | Done | `1e7b0cd` |
| 3. Implementation: Phase 5 (bridge mode + stdio-only-client routing) | Done | `1e7b0cd` |
| 3. Implementation: Phase 6 (gateway doctor, cross-platform polish) | Done | `1e7b0cd` |
| 4. Tests | Done | 706 passing across runtime / supervisor / shim / commands / integration |
| 5. Documentation | Done | `SETUP.md` Phase-4-onwards section, `a37ae8a` |
| 6. Reconcile (orphan removal, profile-rm propagation, client-edit resolver pass) | Done | `42c55c4`, `9122be5`, `6315142` |

This spec is closed. The architecture as built matches the recommendation in the Architectural Decisions section (A.2 split paths / B.3 self-launch / C.3 lazy worker / D.1 hand-rolled supervisor / E.2 Unix-socket IPC / F.1 TCP loopback Streamable HTTP / G.2 per-session token / H.2 dual-entry migration), with one known scope-down: stateless Streamable HTTP migration (Future Improvements section) is deferred until upstream MCP roadmap lands the `initialize` removal.

---

## Context

mcpm currently installs every managed MCP server into clients (Claude Code, Gemini CLI, Cursor, Codex, etc.) as `command: "mcpm", args: ["run", "<name>"]`. Each client process spawns one `mcpm run X` Python process per server, which wraps a FastMCP proxy around the underlying server.

Two problems were verified by live testing.

1. **Native client OAuth UX is destroyed for HTTP upstreams.** A live JSON-RPC trace against `mcpm run clickup` shows the upstream's `401 Unauthorized` plus `WWW-Authenticate` plus RFC 9728 `resource_metadata` URL get stringified into a generic JSON-RPC error with `code: 0`. No client-side OAuth metadata path remains. Of the user's HTTP servers, only `figma` (wired directly as raw `type: http` in `~/.claude.json`) shows the native authenticate prompt in Claude Code's `/mcp`. Every server proxied through `mcpm run` is silent.
2. **Idle resource cost is high and scales linearly with clients.** Measured on the author's machine: 13 idle `mcpm run X` processes, 145 MB RSS each, total 1830 MB resident, plus 600 ms cold-start per server when a client launches. Each client running concurrently re-spawns the full set, so two clients open at once doubles the cost. This is the same shape as the [Google Antigravity multi-workspace report](https://discuss.ai.google.dev/t/bug-mcp-servers-spawn-per-workspace-causes-process-explosion-and-10-gb-idle-ram/129054) (4 workspaces times 9 servers times 2 processes = 72 node procs, ~4.5 GB).

A naive "always-on monolithic gateway" fixes both, but trades them for new costs: cross-platform daemon registration (launchd, systemd, Windows tasks), one shared process for all servers (loses v2's process isolation), tighter coupling to FastMCP HTTP transport quality, and a non-trivial migration risk. The mcpm v2 design doc explicitly chose direct execution over a daemon model for those reasons.

The architecture below keeps v2's process isolation and on-demand spirit while solving the OAuth-loss and multi-client RAM problems.

## Summary

Split the routing path by upstream transport.

- **HTTP upstreams** (`RemoteServerConfig`) get written directly into client configs as `{"type": "http", "url": "..."}`. mcpm is not in the request path. Native client OAuth UX is preserved end to end. Zero RAM cost. This is the Stage 1 PR-shaped subset of the design and is independently valuable.
- **Stdio upstreams** (`STDIOServerConfig`) route through a tiny self-launching router on `localhost:<kernel-port>`. The router spawns one worker subprocess per server lazily on first request, multiplexes client sessions onto each worker, and idle-evicts workers via SIGTERM after `child_idle_timeout`. The router itself self-shutdowns after `router_idle_timeout` of zero clients and self-relaunches on next need (gpg-agent pattern). No launchd, systemd, or Windows scheduled task required.
- **Stdio-only clients** (Claude Desktop and similar) use a thin `mcpm bridge <server>` shim that pipes their stdio JSON-RPC to the local router over HTTP. Each shim is ~10 MB Python instead of ~145 MB.

Net effect: zero idle RAM when nothing is being used, ~30 MB router footprint plus ~50 MB per actively-used stdio server (shared across all clients), native OAuth for HTTP servers, single process per server for isolation.

## Branch Strategy

- Base branch: `main`
- Branch name: `feat/router-and-direct-http`
- Notes: Single-author repo, no staging branch. Land in a long-running feature branch with incremental commits, PR to `main` once Phase 4 integration tests pass. Phase 1 (direct HTTP) is upstream-PR-shaped on its own, even before the router lands.

## What Already Exists

| Area | Description |
|------|-------------|
| FastMCP integration | `src/mcpm/fastmcp_integration/proxy.py` builds a per-call `FastMCP.as_proxy()` with mcpm middleware. Currently invoked once per `mcpm run` call, so the proxy is per-client-per-server. |
| Run commands | `src/mcpm/commands/run.py` spawns a single proxy in stdio or HTTP/SSE mode, lifetime tied to that one CLI invocation. |
| Share command | `src/mcpm/commands/share.py` exposes a single server over HTTP via tunnel. Closest existing primitive to what we want, but not multi-server, not persistent. |
| Client config writers | `src/mcpm/commands/client.py:610-616` constructs `STDIOServerConfig(name=..., command="mcpm", args=["run", server_name])` for every install, fed through `JSONClientManager.to_client_format()` (`src/mcpm/clients/base.py:285`). |
| Server schema | `src/mcpm/core/schema.py` defines `STDIOServerConfig`, `RemoteServerConfig`, `CustomServerConfig`. `RemoteServerConfig.to_mcp_proxy_stdio()` already shows the bridge shape. No proxy-mode hint today. |
| Tracking middleware | `MCPMUnifiedTrackingMiddleware` (`src/mcpm/fastmcp_integration/middleware.py:207`) writes to `~/.config/mcpm/monitor.db` per call. |
| Constants | `DEFAULT_PORT = 6276` in `src/mcpm/utils/config.py:19`. Used as the share-mode port today. We will not reuse it because the router uses kernel-assigned ports. |
| v2 design doc | `docs/router_tech_design.md` on upstream/main lays out the explicit reasons v2 removed the v1 daemon: process isolation, no daemon overhead, simplified debugging, on-demand servers. The router-and-workers model preserves all four. |

## Architectural Decisions

### A. Path split by upstream transport

**Options:**
- **A.1** Single uniform path. All upstreams (HTTP and stdio) routed through one mechanism.
- **A.2** Split paths. HTTP upstreams written directly into client configs. Stdio upstreams routed through the local router.

**Recommendation:** A.2. HTTP upstreams have nothing to centralize (no local secrets, OAuth is server-side). Routing them through anything destroys the OAuth metadata flow proven broken in the live trace. They go raw. Stdio upstreams benefit from sharing one worker across clients and from centralized stderr/tracking, so they go through the router.

**Lock:** Pending user confirmation.

### B. Router lifecycle

**Options:**
- **B.1** Always-on via launchd / systemd / Windows scheduled task. User registers at install time, OS supervises.
- **B.2** Socket-activated via launchd / systemd. Idle-out, OS respawns on connection.
- **B.3** Self-launching via gpg-agent pattern. First mcpm command needing the router does `os.fork()` plus `os.setsid()` (Unix) or `subprocess.Popen(..., creationflags=DETACHED_PROCESS)` (Windows). Writes PID, port, and token to a runtime state file. Subsequent calls read the state file. Self-shutdown after `router_idle_timeout` of zero clients.

**Recommendation:** B.3. gpg-agent and ssh-agent have used this pattern across every desktop OS for two decades. No system-level registration. No platform-specific config files for users to manage. Zero infrastructure surface from the user's perspective: "starts when you need it, stops when you don't". B.1 imposes always-on RAM cost. B.2 requires per-OS launcher units, which the v2 doc explicitly avoided.

**Lock:** Pending user confirmation.

### C. Worker process model

**Options:**
- **C.1** Single process for all stdio servers, async tasks per upstream (the original spec).
- **C.2** One worker subprocess per server, eagerly spawned at router start.
- **C.3** One worker subprocess per server, lazily spawned on first request, idle-evicted via SIGTERM after `child_idle_timeout`. Worker multiplexes multiple MCP sessions onto a single upstream stdio child via JSON-RPC request-id rewriting.

**Recommendation:** C.3. Matches v2's process isolation guarantee per server. Preserves the boot-once-share-across-clients property because the worker keeps one upstream child alive across multiple client sessions. Has zero idle floor when no calls are happening (router can keep its registry but no children are running). C.2 wastes RAM on servers the user has installed but does not actively use.

**Multiplexing constraint.** FastMCP's `as_proxy()` deliberately uses session isolation by default (one upstream `Client`, and thus one stdio child, per MCP session). Achieving boot-once-share requires our worker to do its own multiplexing instead of relying on FastMCP-as-proxy. This works for stateless upstream servers (the vast majority of stdio MCP servers in the wild: tool calls are independent JSON-RPC round-trips that do not depend on session-keyed state held inside the server). It does not work for servers that maintain per-session state inside the upstream child process. For those, add `requires_session_pinning: true` to the server config in `servers.json`. The router then keeps one upstream child per `Mcp-Session-Id` instead of one per server. Default is `false` (multiplex). Document the implication clearly in `mcpm install --help` so users with stateful servers know how to opt out.

**Lock:** Pending user confirmation.

### D. Worker process supervision strategy

**Options:**
- **D.1** Hand-rolled supervisor: `subprocess.Popen` plus a watchdog asyncio task per worker. ~150 lines.
- **D.2** Embed [Circus](https://circus.readthedocs.io/en/latest/tutorial/rationale/) as a library via `circus.get_arbiter`. ~30 lines. Adds a runtime dep.
- **D.3** Use Python's `multiprocessing` + `Manager`. Less suitable for managing arbitrary external commands.

**Recommendation:** D.1 for v1. Circus is well-engineered but adds a dependency for what amounts to "spawn, monitor, signal, await exit". 150 lines of well-tested code is a fair trade for one fewer dep. Revisit if the supervisor grows non-trivial features.

**Lock:** Pending user confirmation.

### E. Router-to-worker IPC

**Options:**
- **E.1** TCP loopback. Each worker binds to its own kernel-assigned port. Router connects.
- **E.2** Unix domain socket per worker. `~/.cache/mcpm/router/<name>.sock`. Owner-only file mode.
- **E.3** Pipe + JSON-RPC stdio between router and worker, just like a regular MCP stdio server.

**Recommendation:** E.2 on Unix, E.3 on Windows. Unix sockets are filesystem-permission-protected (mode 0600), have no port-collision risk, and are faster than loopback TCP. Windows lacks portable Unix-socket support pre-Windows 10 1803, so fall back to stdio-pipe IPC there. E.1 multiplies port management problems.

**Lock:** Pending user confirmation.

### F. Client-to-router transport

**Options:**
- **F.1** TCP loopback Streamable HTTP. Kernel-assigned port at router start, persisted to runtime state file. Clients always re-read the state file before connecting if their cached port is dead.
- **F.2** Unix domain socket Streamable HTTP. Stalled in the spec ([proposal still in triage](https://github.com/modelcontextprotocol/java-sdk/issues/415)).
- **F.3** Stdio-only, force every client through `mcpm bridge <server>`. Loses Claude Code's native HTTP-MCP UX.

**Recommendation:** F.1. F.2 is currently not implementable across MCP clients. F.3 reintroduces the per-client per-server process count we are eliminating.

**Lock:** Pending user confirmation.

### G. Localhost security

**Options:**
- **G.1** No auth. Anything on the loopback can call any worker.
- **G.2** Per-router-session token stored in the runtime state file (mode 0600), required as a `Mcp-Mcpm-Token` header on every request.
- **G.3** Full OAuth between client and router.

**Recommendation:** G.2. Token rotates every router restart. Required only on stdio-server endpoints because direct-HTTP servers are not in the router's path. Defends against stray loopback connections from other processes on the same machine. G.3 is overkill for single-user dev boxes. G.1 is acceptable for personal use but cheap to upgrade.

**Lock:** Pending user confirmation.

### H. Migration safety

**Options:**
- **H.1** In-place rewrite. `mcpm client sync` overwrites the old `mcpm run X` entries with new shapes.
- **H.2** Dual-entry. `mcpm client sync --safe` writes the new entry alongside the old one (suffixed `_legacy`). `mcpm gateway doctor` probes the new entry, removes the legacy on success, otherwise points the user at the legacy.
- **H.3** Versioned config. Bump a schema version in client config, and old mcpm builds reject newer configs.

**Recommendation:** H.2. Backups under `~/.cache/mcpm/migrations/<timestamp>/` plus the dual-entry approach gives both a rollback file and a same-config rollback path. H.1 has no recovery path. H.3 requires every mcpm install to upgrade in lockstep, which is not realistic for a personal repo.

**Lock:** Pending user confirmation.

## Technical Specification

### 1. Schema additions

```python
# src/mcpm/core/schema.py

from typing import Literal


class BaseServerConfig(BaseModel):
    name: str
    profile_tags: List[str] = []
    proxy_mode: Literal["auto", "router", "direct", "legacy"] = "auto"
    requires_session_pinning: bool = False  # Stdio servers that hold per-session state inside the upstream child set this true. Default off (multiplex sessions onto one child).
```

Pydantic v2 with default values lets existing `servers.json` files load unmodified. Old configs read as `proxy_mode="auto"`, `requires_session_pinning=False`. No migration script is needed for the schema bump itself.

| `proxy_mode` | Resolved behavior in client config |
|---|---|
| `auto` (default) | HTTP `RemoteServerConfig` becomes `direct`. `STDIOServerConfig` becomes `router`. `CustomServerConfig` is left alone. |
| `direct` | Raw command/url is written into the client config. No mcpm involvement at runtime. |
| `router` | Only valid for stdio servers. Client config points at the local router URL. |
| `legacy` | Backward-compat: `{"command": "mcpm", "args": ["run", name]}`. Kept indefinitely. |

### 2. Direct HTTP path (Phase 1, upstream-PR-shaped)

`JSONClientManager.to_client_format()` (`src/mcpm/clients/base.py:285`) gets a branch on resolved `proxy_mode`:

```python
def to_client_format(self, server_config: ServerConfig) -> Dict[str, Any]:
    effective = self._resolve_proxy_mode(server_config)

    if effective == "direct":
        if isinstance(server_config, RemoteServerConfig):
            result = {"type": "http", "url": server_config.url}
            if server_config.headers:
                result["headers"] = {k: str(v) for k, v in server_config.headers.items()}
            return result
        if isinstance(server_config, STDIOServerConfig):
            result = {"command": server_config.command, "args": server_config.args}
            non_empty_env = server_config.get_filtered_env_vars(os.environ)
            if non_empty_env:
                result["env"] = non_empty_env
            return result

    if effective == "router":
        runtime = RouterRuntime.read_or_launch()
        return {
            "type": "http",
            "url": f"http://127.0.0.1:{runtime.port}/{server_config.name}/mcp",
            "headers": {"Mcp-Mcpm-Token": runtime.token},
        }

    # Legacy fallback (current behavior, byte-identical for proxy_mode=legacy or unrecognized).
    if isinstance(server_config, STDIOServerConfig):
        result = {"command": server_config.command, "args": server_config.args}
        non_empty_env = server_config.get_filtered_env_vars(os.environ)
        if non_empty_env:
            result["env"] = non_empty_env
        return result
    return server_config.to_dict()


def _resolve_proxy_mode(self, server_config: ServerConfig) -> str:
    explicit = getattr(server_config, "proxy_mode", "auto")
    if explicit != "auto":
        return explicit
    if not getattr(self, "supports_http_mcp", True):
        return "legacy"
    if isinstance(server_config, RemoteServerConfig):
        return "direct"
    if isinstance(server_config, STDIOServerConfig):
        return "router"
    return "legacy"
```

Phase 1 ships only the `direct` branch. Phase 2 adds the `router` branch and `RouterRuntime`.

### 3. Router daemon

The router is a Starlette app that owns a `WorkerSupervisor`. It is intentionally tiny.

```python
# src/mcpm/router/app.py

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route, Mount

from mcpm.global_config import GlobalConfigManager
from mcpm.router.auth import RequireMcpmToken
from mcpm.router.proxy import worker_proxy_endpoint
from mcpm.router.supervisor import WorkerSupervisor


def build_app(supervisor: WorkerSupervisor, token: str) -> Starlette:
    config_manager = GlobalConfigManager()

    routes = []
    for name, server in config_manager.list_servers().items():
        if not isinstance(server, STDIOServerConfig):
            continue
        if server.proxy_mode in ("auto", "router"):
            routes.append(Mount(f"/{name}", routes=[
                Route("/mcp", endpoint=worker_proxy_endpoint(name, supervisor),
                      methods=["GET", "POST", "DELETE", "OPTIONS"]),
                Route("/mcp/{rest:path}", endpoint=worker_proxy_endpoint(name, supervisor),
                      methods=["GET", "POST", "DELETE", "OPTIONS"]),
            ]))

    routes.append(Route("/_health", endpoint=lambda r: PlainTextResponse("ok")))

    return Starlette(
        routes=routes,
        middleware=[Middleware(RequireMcpmToken, token=token)],
    )
```

`worker_proxy_endpoint(name, supervisor)` returns an async ASGI handler. On each request it:

1. Calls `supervisor.touch(name)` to reset the per-worker idle timer.
2. Calls `supervisor.connect(name)` to obtain a Unix-socket connection (or stdio pipe on Windows) to the worker, spawning the worker if it is not running.
3. Forwards the request bytes verbatim to the worker over the IPC channel.
4. Streams the worker's response back, including any `Mcp-Session-Id` header that the worker emits.
5. On disconnect, releases the IPC connection back to the supervisor's pool.

The router also runs an asyncio task that scans connected sessions and exits cleanly when all clients have been disconnected for `router_idle_timeout` (default 30 minutes). On exit, the supervisor signals all live workers with SIGTERM and waits for graceful shutdown before unlinking the runtime state file.

### 4. Worker supervisor

```python
# src/mcpm/router/supervisor.py

import asyncio
import os
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from mcpm.core.schema import STDIOServerConfig
from mcpm.global_config import GlobalConfigManager


@dataclass
class WorkerHandle:
    name: str
    process: subprocess.Popen
    ipc_path: Path
    last_touch: float = field(default_factory=time.time)
    spawned_at: float = field(default_factory=time.time)


class WorkerSupervisor:
    def __init__(self, child_idle_timeout: float = 900.0):
        self.child_idle_timeout = child_idle_timeout
        self.workers: dict[str, WorkerHandle] = {}
        self.config_manager = GlobalConfigManager()
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._reaper_task = asyncio.create_task(self._reap_idle())

    async def shutdown(self) -> None:
        if self._reaper_task is not None:
            self._reaper_task.cancel()
        for handle in list(self.workers.values()):
            await self._terminate(handle)

    def touch(self, name: str) -> None:
        handle = self.workers.get(name)
        if handle is not None:
            handle.last_touch = time.time()

    async def connect(self, name: str) -> socket.socket:
        async with self._lock:
            handle = self.workers.get(name)
            if handle is None or handle.process.poll() is not None:
                handle = await self._spawn(name)
                self.workers[name] = handle

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.setblocking(False)
        await asyncio.get_running_loop().sock_connect(sock, str(handle.ipc_path))
        return sock

    async def _spawn(self, name: str) -> WorkerHandle:
        server = self.config_manager.get_server(name)
        if not isinstance(server, STDIOServerConfig):
            raise ValueError(f"Server '{name}' is not stdio")

        ipc_dir = Path.home() / ".cache" / "mcpm" / "router"
        ipc_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        ipc_path = ipc_dir / f"{name}.sock"
        ipc_path.unlink(missing_ok=True)

        log_path = ipc_dir / f"{name}.log"
        log_fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)

        env = {
            **os.environ,
            "MCPM_WORKER_IPC": str(ipc_path),
            "MCPM_PARENT_PID": str(os.getpid()),
            "MCPM_REQUIRES_SESSION_PINNING": "1" if server.requires_session_pinning else "0",
            **(server.env or {}),
        }
        cmd = [shutil.which("mcpm") or "mcpm", "_worker", name]

        # On Linux the worker uses prctl(PR_SET_PDEATHSIG, SIGTERM) to die with the
        # router. On macOS / Windows the worker polls MCPM_PARENT_PID and self-exits
        # if the parent disappears. Implementation lives in worker/main.py.
        process = subprocess.Popen(
            cmd, env=env, stdin=subprocess.DEVNULL, stdout=log_fd, stderr=log_fd,
            start_new_session=True,
        )

        await self._await_socket(ipc_path, timeout=5.0)
        return WorkerHandle(name=name, process=process, ipc_path=ipc_path)

    @staticmethod
    async def _await_socket(path: Path, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return
            await asyncio.sleep(0.05)
        raise TimeoutError(f"Worker socket {path} did not appear within {timeout}s")

    async def _reap_idle(self) -> None:
        while True:
            await asyncio.sleep(30)
            now = time.time()
            stale = [h for h in self.workers.values()
                     if now - h.last_touch > self.child_idle_timeout]
            for handle in stale:
                await self._terminate(handle)
                self.workers.pop(handle.name, None)

    async def _terminate(self, handle: WorkerHandle) -> None:
        if handle.process.poll() is None:
            handle.process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(None, handle.process.wait),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                handle.process.kill()
        handle.ipc_path.unlink(missing_ok=True)
```

### 5. Worker process (stdio↔HTTP shim)

A worker is invoked as `mcpm _worker <server-name>` (the leading underscore marks it as not-for-direct-user-invocation). It:

1. Reads `MCPM_WORKER_IPC` to learn the Unix socket path (or stdio file descriptors on Windows) it should bind to.
2. Spawns the actual upstream stdio child via `asyncio.create_subprocess_exec(server.command, *server.args)` with `start_new_session=True`. On Linux, sets `prctl(PR_SET_PDEATHSIG, SIGTERM)` so the child dies with the worker. On macOS, the worker polls its parent (the router) and self-exits if the parent disappears.
3. The router sends and receives newline-delimited JSON-RPC frames over the IPC. The worker does **not** speak HTTP. HTTP termination happens at the router.
4. For each incoming JSON-RPC request from the IPC, the worker rewrites the `id` field to a globally-unique value (per worker), records `(new_id, original_id, session_id)`, forwards the rewritten request to the upstream child's stdin, and routes the response back to the right session by matching `id`.
5. Notifications from the upstream child (no `id` field) get tagged with the originating session's identity if applicable, otherwise broadcast to all active sessions for that server (e.g. `notifications/tools/list_changed`).
6. Tee's the child's stderr to two destinations: the log file (for `mcpm gateway tail` to follow) AND wraps each stderr line as an MCP `notifications/message` (per [MCP spec](https://modelcontextprotocol.io/docs/tutorials/security/authorization)) sent to whichever sessions are currently subscribed, so clients see warnings inline (which is what Gemini does today, restoring parity for Claude Code).
7. Self-shutdown when the IPC socket has had no traffic for `worker_idle_self_timeout` (slightly longer than `child_idle_timeout` so the supervisor wins races).

The worker uses the raw `mcp` Python SDK only for typed message validation. The framing shim is intentionally minimal (~200 lines) so a regression in FastMCP's HTTP server cannot affect a worker. The router (not the worker) handles Streamable HTTP, OAuth headers, SSE responses, and `Mcp-Session-Id`.

When `requires_session_pinning=true` for a server, the worker maintains a `dict[session_id, subprocess]` instead of a single child. New session = new child spawn. Eviction is per-session: a session whose last touch exceeds `child_idle_timeout` has its child terminated, and the router invalidates that session's mapping.

### 6. Self-launch and runtime state

```python
# src/mcpm/router/runtime.py

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from pydantic import BaseModel


class RouterRuntime(BaseModel):
    pid: int
    port: int
    token: str
    started_at: float

    @classmethod
    def state_path(cls) -> Path:
        return Path.home() / ".config" / "mcpm" / "router-runtime.json"

    @classmethod
    def read(cls) -> "RouterRuntime | None":
        path = cls.state_path()
        if not path.exists():
            return None
        try:
            return cls.model_validate_json(path.read_text())
        except Exception:
            return None

    @classmethod
    def read_or_launch(cls) -> "RouterRuntime":
        existing = cls.read()
        if existing is not None and cls._is_alive(existing):
            return existing
        return cls._launch()

    @staticmethod
    def _is_alive(rt: "RouterRuntime") -> bool:
        try:
            os.kill(rt.pid, 0)
        except (OSError, ProcessLookupError):
            return False
        try:
            r = httpx.get(f"http://127.0.0.1:{rt.port}/_health",
                          headers={"Mcp-Mcpm-Token": rt.token}, timeout=0.5)
            return r.status_code == 200
        except httpx.RequestError:
            return False

    @classmethod
    def _launch(cls) -> "RouterRuntime":
        # Pre-bind a kernel-assigned port and pass the FD to the child via env.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        token = secrets.token_urlsafe(32)
        cls.state_path().parent.mkdir(parents=True, exist_ok=True)

        env = {**os.environ, "MCPM_ROUTER_PORT": str(port), "MCPM_ROUTER_TOKEN": token}
        if sys.platform == "win32":
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(["mcpm", "_router"], env=env, creationflags=flags,
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        else:
            proc = subprocess.Popen(["mcpm", "_router"], env=env, start_new_session=True,
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)

        # Wait for the router to write its runtime state.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            rt = cls.read()
            if rt is not None and cls._is_alive(rt):
                return rt
            time.sleep(0.05)
        raise RuntimeError("Router failed to start within 5s")
```

The state file is mode 0600. The token rotates on every router launch. PID-file race protection is handled by an advisory lock on the state file during `_launch` (omitted in the sketch above for clarity, present in the implementation).

### 7. Stdio-only client bridge

For clients flagged `supports_http_mcp = False`. Recent Claude Desktop versions (2025+) accept `type: http` entries in `claude_desktop_config.json`, so the bridge is only required for older builds and for clients that have not adopted Streamable HTTP yet (e.g. some embedded extensions). Detection is conservative: `ClaudeDesktopManager` and similar managers default `supports_http_mcp = True`. A user pinned to an older Claude Desktop can override the registry by setting `MCPM_FORCE_STDIO_BRIDGE_FOR=claude-desktop` or by patching the manager class. Defaulting to HTTP avoids the bridge tax for users on current versions.

Bridge implementation. Points at the runtime port plus token from the state file:

```python
# src/mcpm/commands/bridge.py

import asyncio
import sys

import httpx
from mcpm.utils.rich_click_config import click

from mcpm.router.runtime import RouterRuntime


@click.command()
@click.argument("server_name")
def bridge(server_name: str) -> None:
    """Stdio shim for clients that do not support HTTP MCP."""
    asyncio.run(_pump(server_name))


async def _pump(server_name: str) -> None:
    rt = RouterRuntime.read_or_launch()
    url = f"http://127.0.0.1:{rt.port}/{server_name}/mcp"
    headers = {
        "Mcp-Mcpm-Token": rt.token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    session_id: str | None = None

    async with httpx.AsyncClient(timeout=None) as client:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            req_headers = dict(headers)
            if session_id:
                req_headers["Mcp-Session-Id"] = session_id

            async with client.stream("POST", url, content=line, headers=req_headers) as resp:
                new_session = resp.headers.get("Mcp-Session-Id")
                if new_session:
                    session_id = new_session

                content_type = resp.headers.get("Content-Type", "")
                if content_type.startswith("text/event-stream"):
                    # Streamable HTTP SSE response: each "data: <json>" line is one MCP message.
                    async for sse_line in resp.aiter_lines():
                        if sse_line.startswith("data: "):
                            sys.stdout.write(sse_line[6:] + "\n")
                            sys.stdout.flush()
                else:
                    # Plain JSON response.
                    body = await resp.aread()
                    sys.stdout.write(body.decode())
                    sys.stdout.flush()
```

For Claude Desktop (or any client manager flagged `supports_http_mcp = False`), `mcpm client sync` emits:

```json
{ "command": "mcpm", "args": ["bridge", "clickup"] }
```

instead of `type: http`.

### 8. Stderr propagation

Three destinations for each upstream stdio child's stderr:

1. **Log file**: `~/.cache/mcpm/router/<name>.log` (mode 0600). Tail via `mcpm gateway tail <name>`.
2. **Inline as MCP `notifications/message`**: each stderr line is wrapped in a `notification` JSON-RPC frame and emitted on whichever client sessions are currently subscribed. Clients that surface server log notifications (Gemini does, Claude Code's `/mcp` view will pick it up) get the warning text without log-file hunting.
3. **Counters in `monitor.db`** for the existing `MCPMUnifiedTrackingMiddleware` (`src/mcpm/fastmcp_integration/middleware.py:207`) to record stderr activity rate per server. Useful for spotting noisy or crashing servers in `mcpm gateway status`.

### 9. Migration: dual-entry mode

`mcpm client sync --safe` writes both shapes simultaneously into client configs:

```jsonc
// ~/.claude.json (illustrative)
{
  "mcpServers": {
    "mcpm_clickup": { "type": "http", "url": "https://mcp.clickup.com/mcp" },
    "_legacy_mcpm_clickup": { "command": "mcpm", "args": ["run", "clickup"] }
  }
}
```

`mcpm gateway doctor` then probes `mcpm_clickup` (the new entry):

- If the new entry passes a `tools/list` round-trip: remove `_legacy_mcpm_clickup`, log success.
- If it fails: log the reason, leave `_legacy_*` in place so the user has a path back, surface a `Status: degraded` warning in `mcpm gateway status` recommending `mcpm client sync --legacy` to revert all entries.
- Backups under `~/.cache/mcpm/migrations/<timestamp>/<client>.json.bak` are written before the first `mcpm client sync` after gateway enablement.

`mcpm client sync --legacy` is the explicit revert: rewrites every entry to the `mcpm run X` shape, regardless of `proxy_mode`.

### 10. CLI surface

The top-level `mcpm sync` namespace is already taken by the `mcpm-sync` plugin (cross-machine push/pull, registered as a click group via the `mcpm.plugins` entry point in `plugins/mcpm-sync/pyproject.toml`). Likewise `mcpm doctor` already exists as a system health check (`src/mcpm/commands/doctor.py`). To avoid colliding, this spec adds new commands under the existing `mcpm client` and a new `mcpm gateway` group.

```
mcpm install <server>                  # registers in servers.json, proxy_mode=auto by default
mcpm install <server> --mode <mode>    # explicit override at install time
mcpm mode <server> <mode>              # change mode post-install

mcpm client sync                       # rewrite client configs based on resolved modes
mcpm client sync --safe                # dual-entry mode (writes both new and _legacy_ entries)
mcpm client sync --legacy              # force every entry back to mcpm run X (revert path)

mcpm gateway status                    # show: router pid, port, uptime, per-server worker PIDs/RSS/last-call/idle-deadline
mcpm gateway tail <server>             # live-tail the worker log
mcpm gateway logs <server>             # cat the log file
mcpm gateway ps                        # lighter-weight: just worker PIDs and uptime
mcpm gateway stop                      # SIGTERM router (clients re-launch on next call)
mcpm gateway restart                   # stop + bare relaunch
mcpm gateway doctor                    # probe new client entries, heal or surface degraded state
mcpm gateway doctor --rollback         # explicit revert path (calls `mcpm client sync --legacy`)

mcpm bridge <server>                   # internal: stdio shim, used by Claude Desktop config
mcpm _router                           # internal: actually be the router (called by self-launch)
mcpm _worker <name>                    # internal: actually be a worker (called by supervisor)
```

`mcpm gateway install` and `mcpm gateway uninstall` are intentionally absent. There is nothing to install at the OS level.

The existing `mcpm doctor` (system health check) is left untouched. Gateway-specific probing lives under `mcpm gateway doctor` so users coming from older versions are not surprised by behavior changes.

## Files Changed

| Action | File | Description |
|--------|------|-------------|
| MOD | `src/mcpm/core/schema.py` | Add `proxy_mode` to `BaseServerConfig`. |
| MOD | `src/mcpm/clients/base.py` | `to_client_format()` branches on resolved mode. New `_resolve_proxy_mode()`. New `supports_http_mcp` class attribute on `JSONClientManager` (default `True`). |
| MOD | `src/mcpm/clients/managers/claude_desktop.py` | Set `supports_http_mcp = False`. |
| MOD | `src/mcpm/commands/client.py` | Recognize router-shaped, direct-shaped, bridge-shaped, and legacy-shaped entries in `enable_for_client` / `disable_for_client` paths currently keyed off `command == "mcpm"` (`src/mcpm/commands/client.py:118-148`). |
| ADD | `src/mcpm/router/__init__.py` | Module init. |
| ADD | `src/mcpm/router/runtime.py` | `RouterRuntime` with `read_or_launch()`. |
| ADD | `src/mcpm/router/app.py` | Starlette app builder. |
| ADD | `src/mcpm/router/supervisor.py` | `WorkerSupervisor` with lazy spawn + idle reap. |
| ADD | `src/mcpm/router/proxy.py` | Per-worker IPC proxy endpoint. |
| ADD | `src/mcpm/router/auth.py` | `RequireMcpmToken` Starlette middleware. |
| ADD | `src/mcpm/router/server_main.py` | `mcpm _router` entry point: read env, build app, run uvicorn on the env-passed port. |
| ADD | `src/mcpm/worker/__init__.py` | Module init. |
| ADD | `src/mcpm/worker/main.py` | `mcpm _worker <name>` entry point: spawn child, bind IPC socket, translate framing, tee stderr. |
| ADD | `src/mcpm/worker/shim.py` | Stdio↔Streamable-HTTP framing using the raw `mcp` SDK. |
| ADD | `src/mcpm/commands/gateway.py` | `mcpm gateway status / tail / logs / ps / stop / restart`. |
| ADD | `src/mcpm/commands/mode.py` | `mcpm mode <server> <mode>`. |
| ADD | `src/mcpm/commands/bridge.py` | `mcpm bridge <server>` stdio-to-router shim. |
| MOD | `src/mcpm/commands/client.py` | Add `sync` subcommand to the existing `client` click group (at line 28, alongside `ls` / `edit` / `import`). |
| MOD | `src/mcpm/cli.py` | Register new command groups + the underscore-prefixed internal entry points. |
| MOD | `pyproject.toml` | Add `starlette` and `uvicorn[standard]` to runtime deps. Add `httpx` explicitly (currently transitive via `fastmcp` and `mcp`, but we now use it directly in `bridge.py` and `runtime.py`). `mcp>=1.8.0` and `fastmcp==2.13.0` already present. `psutil` already a dep, used for `mcpm gateway ps`. `watchfiles` already a dep, used for `mcpm gateway tail`. |
| ADD | `tests/router/test_runtime.py` | `RouterRuntime` lifecycle. |
| ADD | `tests/router/test_supervisor.py` | Lazy spawn, idle reap, signal handling. |
| ADD | `tests/router/test_proxy.py` | Token check, request forwarding, session header passthrough. |
| ADD | `tests/router/test_self_launch.py` | gpg-agent pattern, PID race. |
| ADD | `tests/worker/test_shim.py` | Framing, stderr tee, child lifecycle. |
| ADD | `tests/clients/test_to_client_format_modes.py` | Direct, router, legacy resolution. |
| ADD | `tests/commands/test_doctor.py` | Dual-entry probe + heal + rollback. |
| ADD | `tests/commands/test_bridge.py` | Stdio shim correctness. |

## Performance Estimate

Measured baseline: 13 mcpm-managed servers, idle on the author's machine, current `mcpm run X` model.

| Scenario | Current v2 (per-client `mcpm run`) | Original gateway daemon (Alternative below) | This spec (router + workers) |
|---|---|---|---|
| Daemon idle, no clients open | 0 MB | 0 (or 200 MB always-on) | **0 MB** (router self-shut) |
| 1 client open, no MCP calls yet | 1830 MB (every server cold-spawned by the client) | 200 MB | **30 MB** (router only, no workers) |
| 1 client open, 3 servers actively used | 1830 MB | 200 MB | **30 + 3 × 50 = 180 MB** |
| 2 clients open, same 3 servers in use | **3660 MB** (each client has its own) | 200 MB (shared) | **180 MB** (workers shared) |
| 2 clients open, 6 distinct servers in use | 3660 MB | 200 MB | **30 + 6 × 50 = 330 MB** |
| Cold-start when client launches | 600 ms × N (every server cold-spawned) | ~200 ms (gateway already running) or ~1.5 s (wake) | **~30 ms** (HTTP servers go direct, no router involved) or **~200 ms** (first stdio call wakes the router) |
| First call to a cold worker | included above | ~500 ms | ~500 ms (one-time per server) |
| Steady-state n-th call | ~50 µs (raw stdio) | ~1-2 ms (loopback HTTP) | ~1-2 ms (loopback HTTP + Unix-socket worker hop) |
| Per-call overhead from middleware | ~1 ms (SQLite write per process) | ~1 ms (single shared SQLite) | ~1 ms (single shared SQLite, in router) |
| Token check overhead | n/a | n/a | ~0.05 ms |

The headline numbers: **zero idle floor when nothing is being used**, **shared workers across clients**, **direct HTTP for OAuth servers (no proxy at all)**, **per-server process isolation preserved**.

What would flip the recommendation: if MCP clients converged on stdio-only transport for security reasons (unlikely given the stated 2026 roadmap), or if the per-worker subprocess overhead turned out to be more than 50 MB in practice (revisit with measurements after Phase 2).

## Alternative architecture: monolithic gateway daemon

**Status: documented for review. The router-and-workers model (this spec) remains the locked recommendation unless self-launching cross-platform reliability proves brittle, in which case fall back to launchd / systemd registration with the monolithic-daemon shape.**

The original v1 of this spec proposed a single FastAPI process hosting every server behind one HTTP endpoint, started on demand via launchd or systemd socket activation, with stdio servers multiplexed onto session-keyed FastMCP-as-proxy children inside the gateway process.

### Architecture summary

1. One Starlette app, one process, all servers mounted at `/<name>/mcp`.
2. HTTP upstreams use a transparent httpx reverse proxy inside the gateway.
3. Stdio upstreams use FastMCP-as-proxy with `streamable_http_app()`, multiplexing client sessions via `Mcp-Session-Id` onto a single in-process child.
4. Activated via launchd plist on macOS, systemd user socket on Linux. `RunAtLoad=false`, socket activation, idle-out.
5. `mcpm gateway install` writes the plist or unit. `mcpm gateway uninstall` removes it.

### Failure modes

| Failure | When detected | What the user sees |
|---|---|---|
| One bad upstream crashes inside the gateway process | At runtime when calling that server | Usually contained by FastMCP, but if it raises at import time it can cascade to the gateway. Workaround: restart gateway. |
| launchd plist or systemd unit drifts from current binary location after `pip install --upgrade` | Next reboot | Gateway fails to start. User sees broken `/mcp` in clients. Workaround: `mcpm gateway install` again. |
| Socket activation FD passing flakes on a specific OS version | At launch | Daemon fails silently. Workaround: manually start with `mcpm gateway start`. |

### Bill of materials

| Component | Effort |
|-----------|--------|
| Schema field + branching | 0.5 day |
| FastAPI gateway scaffold | 1 day |
| Transparent HTTP reverse proxy | 1 day |
| FastMCP-as-proxy session multiplexing | 1 day |
| launchd plist generator and installer | 1 day |
| systemd user unit generator and installer | 1 day |
| Migration + tests | 2 days |

Total: about 7-8 days. The router-and-workers model is roughly the same total effort (8-10 days) but avoids the launchd / systemd surface.

### Risks specific to this alternative

- Cross-platform daemon registration is real maintenance burden over time.
- One bad upstream can cascade if it raises during FastMCP import.
- Tighter coupling to FastMCP HTTP transport quality.
- v2's "no daemon overhead" claim is broken in this design, making upstream contribution harder.

### When to choose this over the locked decision

- Self-launching gpg-agent pattern proves brittle on a specific OS or under concurrent invocations
- Operational data after Phase 2 shows the per-worker process model has unforeseen cost (e.g. > 100 MB per worker due to dependency closure)
- Maintenance preference for a single Python process over many

### What stays the same

- Schema field `proxy_mode` is identical
- Direct-HTTP path for `RemoteServerConfig` is identical
- Stdio bridge for legacy clients is identical
- Migration strategy (dual-entry) is identical

So choosing this alternative later would only require swapping the router-supervisor pair for a single FastAPI process. The client-facing contract is unchanged.

## Future Improvements / Worth Discussing

- **Stateless Streamable HTTP migration.** The [MCP transport roadmap (Dec 2025)](https://blog.modelcontextprotocol.io/posts/2025-12-19-mcp-transport-future/) commits to making Streamable HTTP stateless: removing the `initialize` handshake, embedding shared info per request. When this lands (~mid-2026 per the roadmap), the worker shim can drop session-tracking complexity and become smaller. Plan a refactor PR aligned with the spec release.
- **Tracking dashboard.** `mcpm gateway dashboard` opens a local web UI with per-server call counts, latencies, error rates, last 24 h timeline. Single source of truth for stdio servers. HTTP servers are direct so unobservable via mcpm, which is acceptable.
- **Worker pre-warm on client launch.** Optionally pre-warm a configured shortlist of workers when a client first connects, trading idle RAM for first-call latency.
- **Single aggregate worker for tool-namespacing setups.** For users who want a "one super-server" UX, allow a `--aggregate` flag that runs one worker hosting all stdio servers via FastMCP combined-server. Loses isolation, gains slightly less RAM. Defer until demand surfaces.
- **Per-server worker resource caps.** Use cgroups (Linux) or `setrlimit` (macOS) to bound a worker's RSS and CPU. Defends against runaway upstream MCPs. Phase 5+.
- **Encrypted token at rest.** Today the token sits in a 0600 file. If shared filesystems become a use case, integrate macOS Keychain / Linux Secret Service / Windows Credential Manager.
- **Crash-loop detection and quarantine.** If a worker crashes more than N times in M minutes, mark the server as quarantined, stop respawning, surface in `mcpm gateway status`. Avoids tight-loop spawning.
- **`mcpm gateway export-clients`.** Render configs for each installed client so users can copy-paste into hand-managed setups.

## Out of Scope

- Authentication between clients beyond the per-session token. Multi-user scenarios on a shared host are not v1.
- TLS for the router. Loopback only, plain HTTP per the MCP spec's localhost guidance.
- Windows full parity for the worker IPC. Workers on Windows fall back to stdio-pipe IPC instead of Unix sockets.
- Replacing `mcpm run` CLI. Stays as the legacy escape hatch indefinitely.
- A web UI. Future Improvement.
- An always-on supervised daemon mode. Future Improvement if self-launching proves insufficient.

## Open Questions / Decisions

| # | Question | Source | Blocking? | Phase | Plan |
|---|----------|--------|-----------|-------|------|
| 1 | Default `child_idle_timeout`: 5, 15, or 30 minutes? | stakeholder | No | 2 | 15 minutes. Configurable in `gateway.json`. |
| 2 | Default `router_idle_timeout`: 30 or 60 minutes? | stakeholder | No | 2 | 30 minutes. |
| 3 | Should `mcpm install` for a stdio server eagerly start a worker so first client call is hot? | stakeholder | Yes | 2 | No. `mcpm install` should not have side effects on the running router. The first request triggers spawn, with ~500 ms one-time latency the user will not notice. |
| 4 | Race-condition strategy for two `mcpm` invocations launching the router simultaneously? | codebase | Yes | 2 | Advisory lock (`fcntl.flock` on Unix, `msvcrt.locking` on Windows) on the runtime state file during `_launch`. Lock-holder spawns and writes. Lock-loser reads after release. |
| 5 | If `RouterRuntime.read()` returns a runtime referencing a dead PID, do we delete the file or leave it? | codebase | No | 2 | Delete it before relaunching, so subsequent reads see a clean slate. |
| 6 | Worker death during a streaming response: do we retry the request once or surface the error? | spec | No | 2 | Surface. Retrying could double-execute side-effecting tools. |
| 7 | Should `mcpm client sync` rewrite client configs immediately on first install with `proxy_mode=auto`, or require explicit `mcpm client sync --safe`? | stakeholder | Yes | 4 | Implicit on `mcpm install` for new servers. Explicit `mcpm client sync --safe` for migrating existing servers. |
| 8 | How does `mcpm gateway doctor` decide a worker is healthy? `tools/list` round-trip, or just TCP connect? | codebase | No | 4 | `tools/list` round-trip with 3 s timeout. Reflects real upstream availability. |
| 9 | Where should `monitor.db` live now that one router writes to it? | codebase | No | 2 | `~/.config/mcpm/monitor.db` (current location). Single writer, no contention. |
| 10 | Should the router accept connections only from `127.0.0.1` or also `::1`? | codebase | No | 2 | Bind to `127.0.0.1` only. IPv6 loopback adds attack surface for marginal benefit on dev boxes. |

## Tests

### Python

| Test | Purpose |
|------|---------|
| `test010_schema_proxy_mode_default_is_auto` | New `proxy_mode` field defaults to `auto` for all server types. |
| `test020_resolve_auto_for_remote_returns_direct` | `_resolve_proxy_mode(RemoteServerConfig(...))` returns `"direct"`. |
| `test030_resolve_auto_for_stdio_returns_router` | `_resolve_proxy_mode(STDIOServerConfig(...))` returns `"router"`. |
| `test040_resolve_auto_for_stdio_only_client_returns_legacy` | Client manager with `supports_http_mcp=False` causes resolution to `"legacy"` for stdio servers. |
| `test050_to_client_format_direct_remote_writes_raw_http_url` | `RemoteServerConfig` resolved to `direct` produces `{"type": "http", "url": ...}`. |
| `test060_to_client_format_direct_stdio_writes_raw_command` | `STDIOServerConfig` with explicit `proxy_mode=direct` produces raw command/args/env. |
| `test070_to_client_format_router_writes_runtime_url_with_token` | Router-mode resolution writes `{"type": "http", "url": "http://127.0.0.1:<port>/<name>/mcp", "headers": {"Mcp-Mcpm-Token": "..."}}`. |
| `test080_to_client_format_legacy_writes_mcpm_run` | `proxy_mode=legacy` produces `{"command": "mcpm", "args": ["run", name]}`. |
| `test090_to_client_format_for_stdio_only_client_writes_bridge` | Client manager with `supports_http_mcp=False`, server resolved to router-equivalent, produces `{"command": "mcpm", "args": ["bridge", name]}`. |
| `test100_router_runtime_read_returns_none_when_state_file_missing` | Clean slate. |
| `test110_router_runtime_read_returns_none_when_pid_dead` | Stale state file with dead PID is treated as not-running. |
| `test120_router_runtime_read_or_launch_starts_router_when_absent` | Spawn happens via `_launch`. State file appears within 5 s. |
| `test130_router_runtime_read_or_launch_reuses_running_router` | If state file references a live PID with a healthy `/_health`, no new spawn. |
| `test140_router_runtime_concurrent_launch_no_double_spawn` | Two simultaneous `read_or_launch()` calls produce one router process (advisory-lock test). |
| `test150_router_token_required_on_every_endpoint_except_health` | Request without `Mcp-Mcpm-Token` returns 401. `/_health` unauthenticated. |
| `test160_router_token_rotates_across_restarts` | After router restart, old token rejected, new token accepted. |
| `test170_supervisor_spawns_worker_on_first_request` | `connect("X")` triggers `_spawn`. Subsequent `connect("X")` reuses. |
| `test180_supervisor_evicts_idle_worker_after_timeout` | After `child_idle_timeout` of zero traffic, worker process gone, IPC socket unlinked. |
| `test190_supervisor_respawns_evicted_worker_on_next_request` | Post-eviction `connect("X")` works (re-spawns). |
| `test200_worker_crash_logged_and_marked_dead_in_supervisor` | Worker crash leaves no zombie. Next request triggers respawn. |
| `test210_router_self_shutdowns_after_no_clients_for_idle_timeout` | After `router_idle_timeout` of zero connected sessions, router exits cleanly, state file unlinked. |
| `test220_router_terminates_all_workers_on_shutdown` | SIGTERM to router cascades to all workers within 5 s grace. |
| `test230_worker_shim_forwards_initialize_response` | Send a JSON-RPC `initialize` over IPC, assert response carries the upstream's `serverInfo` (not a faked one). |
| `test240_worker_shim_forwards_tools_list` | Tools listed by the upstream child appear unchanged in the HTTP response from the router. |
| `test250_worker_shim_tees_stderr_to_log_file` | Upstream stderr writes appear in `~/.cache/mcpm/router/<name>.log`. |
| `test260_worker_shim_emits_stderr_as_notifications_message` | Upstream stderr lines arrive at the connected client as MCP `notifications/message` frames. |
| `test270_worker_shim_passes_through_session_id_header` | First response from upstream sets `Mcp-Session-Id`. Subsequent client requests carry it. Router forwards it correctly. |
| `test280_concurrent_clients_multiplex_onto_one_worker` | Two simulated client sessions to the same server, observe one worker PID. |
| `test290_concurrent_clients_isolate_their_session_state` | Session A's `tools/list` and session B's `tools/list` are independent calls to the upstream, not cross-contaminated. |
| `test300_direct_http_server_bypass_router_when_proxy_mode_auto` | Confirm `to_client_format()` for HTTP server in `auto` mode never reads `RouterRuntime`. |
| `test310_bridge_pumps_stdin_to_router_and_back` | `mcpm bridge clickup` round-trips a JSON-RPC request via stdin to router HTTP and back. |
| `test320_bridge_attaches_runtime_token_to_outgoing_requests` | Bridge always sends `Mcp-Mcpm-Token` header. |
| `test330_bridge_self_launches_router_if_not_running` | First bridge invocation triggers router self-launch. |
| `test340_sync_safe_writes_dual_entries` | Both `mcpm_<name>` and `_legacy_mcpm_<name>` appear in client config after `mcpm client sync --safe`. |
| `test350_doctor_removes_legacy_when_new_entry_passes_probe` | Probe success cleans up `_legacy_*`. |
| `test360_doctor_keeps_legacy_when_new_entry_fails_probe` | Probe failure preserves `_legacy_*` and emits warning. |
| `test370_sync_legacy_force_reverts_all_entries` | `mcpm client sync --legacy` rewrites every entry to `mcpm run X` shape. |
| `test380_migration_writes_backup_before_first_rewrite` | Backup file appears under `~/.cache/mcpm/migrations/<timestamp>/`. |
| `test390_gateway_status_reports_correct_worker_pids_and_last_call_times` | `mcpm gateway status --json` matches actual `ps` output and supervisor state. |
| `test400_supervisor_reaper_does_not_evict_active_workers` | Worker with recent traffic (within `child_idle_timeout`) is not evicted. |
| `test410_worker_multiplexes_two_sessions_onto_one_child_when_pinning_off` | `requires_session_pinning=False`. Two simulated MCP sessions issue tools/list concurrently, observe one upstream child PID, both responses correct, request-id rewriting verified. |
| `test420_worker_isolates_sessions_when_pinning_on` | `requires_session_pinning=True`. Two sessions produce two child PIDs. |
| `test430_worker_pinning_evicts_per_session_idle` | Session A idle for `child_idle_timeout`, child for A terminated, child for B unaffected. |
| `test440_worker_dies_when_router_dies_linux` | On Linux, SIGKILL the router PID. Workers exit within 1s via `PR_SET_PDEATHSIG`. |
| `test450_worker_dies_when_router_dies_macos` | On macOS, kill the router PID. Worker self-exits within polling-interval seconds via `MCPM_PARENT_PID` polling. |
| `test460_bridge_handles_sse_response` | Mock router returns `Content-Type: text/event-stream` with two `data:` lines. Bridge writes both as JSON to stdout, separated by newlines. |
| `test470_bridge_handles_json_response` | Mock router returns `Content-Type: application/json`. Bridge writes the body verbatim. |
| `test480_router_terminates_workers_on_sigterm_within_grace` | `kill -TERM router_pid`, all workers gone within 5 s. |
| `test490_schema_loads_old_servers_json_without_proxy_mode_field` | Pydantic loads existing `servers.json` produced by older mcpm versions, defaults `proxy_mode='auto'` and `requires_session_pinning=False`. |

### Manual verification

- [ ] On macOS: `mcpm install <stdio-server>`, no router running. Open Claude Code. Open `/mcp`. Observe latency on first call. Confirm `ps -ef | grep mcpm` shows one router and one worker for the called server only.
- [ ] On macOS: open Claude Code AND Cursor side-by-side. Call the same stdio server from both. Observe single worker PID serving both. `monitor.db` records calls from both client identifiers.
- [ ] On macOS: register `clickup` (HTTP, OAuth-required). Confirm `~/.claude.json` shows `{"type": "http", "url": "https://mcp.clickup.com/mcp"}` directly. Open Claude Code, click `/mcp`, see the Authenticate prompt. Complete OAuth in browser. Confirm tools appear.
- [ ] On macOS: close all clients. Wait beyond `router_idle_timeout`. Confirm router process gone, state file unlinked. Open Claude Code. Confirm router self-launches transparently within ~200 ms.
- [ ] On macOS: trigger a worker to crash mid-call. Observe error surfaces to client. Next call to that server re-spawns the worker.
- [ ] On macOS: kill the router with SIGKILL. Observe state file is stale (`PID alive` check fails). Next mcpm invocation cleans state file and relaunches.
- [ ] On Linux (Ubuntu): repeat the macOS steps. Confirm Unix-socket IPC works and file modes are 0600.
- [ ] On Linux: test under flatpak / sandboxed clients. Confirm `127.0.0.1` is reachable from inside sandbox (some flatpak clients block loopback by default).
- [ ] On Windows: stub path. Confirm router self-launches via `DETACHED_PROCESS`, worker IPC falls back to stdio-pipe, no other regressions.
- [ ] Stdio-only client (Claude Desktop on macOS): install `mcpm bridge clickup` shape via `mcpm client sync`. Confirm Claude Desktop connects, tool calls round-trip.
- [ ] Pre-commit hooks pass. `pytest` green. `ruff` clean.

## Implementation Checklist

Phase boundaries are designed so each phase is independently shippable.

- [ ] **Phase 1: Direct HTTP for `RemoteServerConfig`.** Schema field, `_resolve_proxy_mode`, `to_client_format` direct branch, migration helper. ~250 lines + tests. **Upstream-PR-shaped on its own.**
- [ ] **Phase 2: Router daemon scaffold.** `RouterRuntime`, self-launch with advisory locking, Starlette app, token middleware, health endpoint. No workers yet (worker calls return 503). ~400 lines + tests.
- [ ] **Phase 3: Worker process and supervisor.** `WorkerSupervisor`, `mcpm _worker` entry, stdio↔HTTP shim, stderr tee, `notifications/message` forwarding, lazy spawn, idle reap. ~600 lines + tests.
- [ ] **Phase 4: CLI surface.** `mcpm gateway status / tail / logs / ps / stop / restart / doctor`, `mcpm mode`, `mcpm client sync --safe / --legacy`. ~300 lines + tests.
- [ ] **Phase 5: Stdio-only client bridge.** `supports_http_mcp` attribute on relevant client managers, `mcpm bridge` command, end-to-end Claude Desktop test. ~150 lines + tests.
- [ ] **Phase 6: Cross-platform polish.** Windows DETACHED_PROCESS path, Windows stdio-pipe IPC fallback, Linux flatpak loopback note. Per-OS manual verification.
- [ ] **Phase 7: Documentation + announcement.** Update `_docs/skills-usage-guide.md`, README section, internal blog note.

## Appendix: gpg-agent self-launching pattern primer

This is the first place mcpm uses a self-spawning daemon pattern. A short primer to anchor reviewers, since the design rests on it.

### What is gpg-agent's self-launching pattern

`gpg-agent`, `ssh-agent`, `polkit`, and many other Unix-native daemons solve the "I need a long-running helper but don't want users to register a system service" problem the same way:

1. The first client call detects there is no running agent (state file missing or PID dead).
2. The client `fork()`s + `setsid()`s + `execve()`s the agent binary in detached mode. On Windows: `subprocess.Popen` with `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`.
3. The agent binds its socket / port, writes its credentials (PID, port, token) to a known state file, and starts serving.
4. Subsequent client calls read the state file, verify liveness, and connect.
5. Periodically the agent self-tests its socket. If it detects a stolen socket (a competitor agent is now bound), it terminates itself rather than fight.
6. The agent exits cleanly on idle and is relaunched on next need.

### How it runs

```
First mcpm call needing the router
  └─► RouterRuntime.read_or_launch()
        ├─► state file missing OR PID dead
        ├─► acquire advisory lock on state file path
        ├─► subprocess.Popen("mcpm", "_router", env={MCPM_ROUTER_PORT, MCPM_ROUTER_TOKEN}, detached)
        ├─► child writes runtime.json with {pid, port, token, started_at}, mode 0600
        ├─► parent waits for healthy /_health response (up to 5s)
        └─► returns runtime

Subsequent calls
  └─► RouterRuntime.read() returns cached, verified live, return immediately

Router idle for router_idle_timeout
  └─► self-shutdown: SIGTERM all workers, unlink state file, exit
```

### Why it fits this spec

The mcpm v2 design doc explicitly listed "no daemon overhead" as a v2 advantage. Self-launching agents preserve that property. The user never registers a service, never learns `launchctl` or `systemctl`, never edits a plist or unit file. From their perspective, mcpm is still a CLI tool. The router exists only when used.

### Authoritative references

- [GnuPG agent manual, "stolen socket" detection and self-termination](https://www.gnupg.org/documentation/manuals/gnupg26/gpg-agent.1.html)
- [Sander van der Burg, "On-demand service activation and self termination"](http://sandervanderburg.blogspot.com/2015/12/on-demand-service-activation-and-self.html)
- [Circus arbiter, embedded process supervisor in Python](https://circus.readthedocs.io/en/latest/tutorial/rationale/)
- [MCP Authorization Tutorial, OAuth flow that the direct-HTTP path preserves](https://modelcontextprotocol.io/docs/tutorials/security/authorization)
- [RFC 9728, OAuth 2.0 Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728)
- [MCP transport roadmap (Dec 2025), stateless Streamable HTTP plan](https://blog.modelcontextprotocol.io/posts/2025-12-19-mcp-transport-future/)
- [MCP 2026 roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/)
- [Google Antigravity multi-workspace MCP RAM explosion report](https://discuss.ai.google.dev/t/bug-mcp-servers-spawn-per-workspace-causes-process-explosion-and-10-gb-idle-ram/129054)

### Requirements

- Runtime: Python 3.11+, `starlette`, `uvicorn[standard]`. `httpx` already a transitive dep of FastMCP. The `mcp` SDK already a transitive dep.
- Cross-platform: macOS, Linux, Windows. No platform-specific service registration needed.
- Filesystem: `~/.config/mcpm/router-runtime.json` (mode 0600), `~/.cache/mcpm/router/*.{sock,log}` (mode 0600).

### File layout for this spec

```
src/mcpm/router/
├── __init__.py
├── runtime.py        # RouterRuntime (read/launch/state file)
├── app.py            # Starlette routing
├── supervisor.py     # WorkerSupervisor (lazy + idle reap)
├── proxy.py          # IPC pump from HTTP to worker socket
├── auth.py           # token middleware
└── server_main.py    # mcpm _router entry point

src/mcpm/worker/
├── __init__.py
├── main.py           # mcpm _worker <name> entry point
└── shim.py           # stdio↔streamable-HTTP framing

src/mcpm/commands/
├── gateway.py        # status / tail / logs / ps / stop / restart
├── mode.py           # mcpm mode <server> <mode>
├── bridge.py         # mcpm bridge <server> stdio shim
└── doctor.py         # post-migration probe + heal
```

### Recommended action

If Phase 1 (direct HTTP) lands cleanly here, propose it as the upstream Stage-1 PR. Phase 2-5 ship locally first, gather operational data over 4-6 weeks, then propose upstream as an RFC with measurements rather than design arguments.

---

_Created: 2026-04-30. Revised: 2026-04-30 to ultra-hybrid (router + workers + direct HTTP)._
