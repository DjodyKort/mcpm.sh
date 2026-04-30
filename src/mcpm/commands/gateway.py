"""`mcpm gateway` command group: inspect, stop, restart the router daemon."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import psutil
from rich.console import Console
from rich.table import Table

from mcpm.router.runtime import RouterRuntime
from mcpm.router.supervisor import WORKER_LOG_DIR
from mcpm.utils.rich_click_config import click

console = Console()
err_console = Console(stderr=True)


@click.group(name="gateway", context_settings=dict(help_option_names=["-h", "--help"]))
def gateway():
    """Inspect and control the local mcpm router daemon.

    The router self-launches on first need (gpg-agent pattern) and self-shuts
    down after `router_idle_timeout` of zero traffic. These subcommands are
    for diagnostics; nothing here is required for normal use.
    """


@gateway.command(name="status", context_settings=dict(help_option_names=["-h", "--help"]))
def status_cmd():
    """Show router PID, port, uptime, and per-server worker info."""
    rt = RouterRuntime.read()
    if rt is None:
        console.print("[yellow]Router is not running.[/]")
        console.print(
            "[dim]It will auto-launch the next time a stdio MCP server is called "
            "through the router.[/]"
        )
        return

    if not _http_alive(rt):
        console.print(
            f"[red]State file references PID {rt.pid} on port {rt.port}, "
            "but /_health does not respond.[/]"
        )
        console.print("[dim]Try: mcpm gateway restart[/]")
        return

    uptime = time.time() - rt.started_at
    console.print()
    console.print("[bold]Router[/]: [green]running[/]")
    console.print(f"  PID:    {rt.pid}")
    console.print(f"  Port:   {rt.port}")
    console.print(f"  Uptime: {_fmt_duration(uptime)}")
    console.print(f"  State:  {RouterRuntime.state_path()}")
    console.print()

    status_payload = _fetch_status(rt)
    if status_payload is None:
        console.print("[yellow]Could not fetch /_status.[/]")
        return

    servers = status_payload.get("servers") or []
    active_workers = status_payload.get("active_workers", 0)
    console.print(f"[bold]Routed servers[/]: {len(servers)}")
    console.print(f"[bold]Active workers[/]: {active_workers}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Server")
    table.add_column("Worker PID", justify="right")
    table.add_column("RSS", justify="right")
    table.add_column("Socket")
    table.add_column("Log")

    from mcpm.router.supervisor import WORKER_SOCKET_DIR

    for name in servers:
        sock_path = WORKER_SOCKET_DIR / f"{name}.sock"
        log_path = WORKER_LOG_DIR / f"{name}.log"
        worker_pid, rss = _resolve_worker(name)
        table.add_row(
            name,
            str(worker_pid) if worker_pid else "[dim]—[/]",
            _fmt_bytes(rss) if rss else "[dim]—[/]",
            "[green]live[/]" if sock_path.exists() else "[dim]—[/]",
            "[green]ok[/]" if log_path.exists() else "[dim]—[/]",
        )
    console.print(table)


@gateway.command(name="ps", context_settings=dict(help_option_names=["-h", "--help"]))
def ps_cmd():
    """Light status: just worker PIDs and uptime."""
    rt = RouterRuntime.read()
    if rt is None or not _http_alive(rt):
        console.print("[dim]Router not running.[/]")
        return
    payload = _fetch_status(rt)
    servers = (payload or {}).get("servers") or []
    if not servers:
        console.print("[dim]No active workers.[/]")
        return
    for name in servers:
        worker_pid, _ = _resolve_worker(name)
        console.print(f"  {name}\t{worker_pid or '—'}")


@gateway.command(name="stop", context_settings=dict(help_option_names=["-h", "--help"]))
def stop_cmd():
    """Send SIGTERM to the router. Workers cascade-terminate."""
    rt = RouterRuntime.read()
    if rt is None:
        console.print("[dim]Router is not running.[/]")
        return
    try:
        os.kill(rt.pid, signal.SIGTERM)
    except ProcessLookupError:
        console.print("[dim]Router PID gone, cleaning state.[/]")
        RouterRuntime.unlink()
        return
    # Wait briefly for graceful exit.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            os.kill(rt.pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            console.print(f"[green]Stopped router (pid={rt.pid}).[/]")
            RouterRuntime.unlink()
            return
    console.print(f"[yellow]Router (pid={rt.pid}) did not exit within 5s.[/]")


@gateway.command(name="restart", context_settings=dict(help_option_names=["-h", "--help"]))
def restart_cmd():
    """Stop the router (if running). Next mcpm call will relaunch it."""
    rt = RouterRuntime.read()
    if rt is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(rt.pid, signal.SIGTERM)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                os.kill(rt.pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                break
    RouterRuntime.unlink()
    console.print("[green]Router cleared.[/]")
    console.print("[dim]It will auto-launch on next stdio MCP call.[/]")


@gateway.command(name="logs", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("server_name")
def logs_cmd(server_name: str):
    """Print the worker log file for a server."""
    log_path = WORKER_LOG_DIR / f"{server_name}.log"
    if not log_path.exists():
        err_console.print(f"[red]No log at {log_path}.[/]")
        sys.exit(1)
    sys.stdout.write(log_path.read_text())


@gateway.command(name="doctor", context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--probe-timeout", type=float, default=3.0, help="Per-server probe timeout in seconds.")
@click.option(
    "--rollback",
    is_flag=True,
    help="If any server probe fails, run `mcpm client sync --legacy` to revert all entries.",
)
def doctor_cmd(probe_timeout: float, rollback: bool):
    """Probe each routed server with `tools/list`. Report healthy / degraded.

    The doctor exists so users can verify a freshly-migrated client config
    actually works before relying on it. It is *not* the same as the
    pre-existing `mcpm doctor` (which is a generic health check).
    """
    rt = RouterRuntime.read()
    if rt is None:
        console.print("[yellow]Router is not running, nothing to probe.[/]")
        console.print("[dim]Run a stdio MCP call from any client to auto-launch it.[/]")
        return

    if not _http_alive(rt):
        console.print(
            f"[red]Router state references PID {rt.pid} on port {rt.port}, "
            "but /_health did not respond.[/]"
        )
        console.print("[dim]Run `mcpm gateway restart` to clear stale state.[/]")
        sys.exit(1)

    payload = _fetch_status(rt)
    servers = (payload or {}).get("servers") or []
    if not servers:
        console.print("[dim]Router is up but no stdio servers are routed.[/]")
        return

    failures: list[tuple[str, str]] = []
    healthy: list[str] = []
    for name in servers:
        ok, detail = _probe_server(rt, name, timeout=probe_timeout)
        if ok:
            healthy.append(name)
            console.print(f"  [green]✓[/] {name}")
        else:
            failures.append((name, detail))
            console.print(f"  [red]✗[/] {name} [dim]({detail})[/]")

    console.print()
    console.print(f"[bold]{len(healthy)}/{len(servers)} servers healthy.[/]")

    if failures and rollback:
        console.print("[yellow]Rolling back via `mcpm client sync --legacy`...[/]")
        from click.testing import CliRunner

        from mcpm.commands.client import sync_clients

        result = CliRunner().invoke(sync_clients, ["--legacy"])
        console.print(result.output)
        sys.exit(0 if result.exit_code == 0 else result.exit_code)

    if failures:
        sys.exit(1)


def _probe_server(rt: RouterRuntime, name: str, *, timeout: float) -> tuple[bool, str]:
    """Send a `tools/list` JSON-RPC request through the router. Returns (ok, detail)."""
    url = f"http://127.0.0.1:{rt.port}/{name}/mcp"
    headers = {
        "Mcp-Mcpm-Token": rt.token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    body = json.dumps({"jsonrpc": "2.0", "id": "doctor-probe", "method": "tools/list"})
    try:
        r = httpx.post(url, headers=headers, content=body, timeout=timeout)
    except httpx.TimeoutException:
        return False, f"timeout (>{timeout}s)"
    except httpx.RequestError as exc:
        return False, f"request error: {exc.__class__.__name__}"

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    try:
        data = r.json()
    except json.JSONDecodeError:
        return False, "non-JSON response"
    if "error" in data:
        return False, f"JSON-RPC error: {data['error'].get('message', 'unknown')}"
    if "result" not in data:
        return False, "missing result field"
    return True, "ok"


@gateway.command(name="tail", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("server_name")
@click.option("-n", "--lines", type=int, default=200, help="Lines of history before tailing.")
def tail_cmd(server_name: str, lines: int):
    """Tail the worker log file for a server (uses `tail -F`)."""
    log_path = WORKER_LOG_DIR / f"{server_name}.log"
    if not log_path.exists():
        err_console.print(f"[red]No log at {log_path}.[/]")
        sys.exit(1)
    cmd = ["tail", "-n", str(lines), "-F", str(log_path)]
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        return
    except FileNotFoundError:
        # No `tail` binary (Windows without Git Bash). Fall back to a polling reader.
        _poll_tail(log_path)


def _poll_tail(path: Path) -> None:
    pos = 0
    try:
        while True:
            with open(path, "r") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


# ----- Helpers ----------------------------------------------------------


def _http_alive(rt: RouterRuntime) -> bool:
    try:
        r = httpx.get(
            f"http://127.0.0.1:{rt.port}/_health",
            headers={"Mcp-Mcpm-Token": rt.token},
            timeout=0.5,
        )
        return r.status_code == 200
    except httpx.RequestError:
        return False


def _fetch_status(rt: RouterRuntime) -> Optional[dict]:
    try:
        r = httpx.get(
            f"http://127.0.0.1:{rt.port}/_status",
            headers={"Mcp-Mcpm-Token": rt.token},
            timeout=1.0,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except (httpx.RequestError, json.JSONDecodeError):
        return None


def _resolve_worker(name: str) -> tuple[Optional[int], Optional[int]]:
    """Find the worker PID + RSS via psutil. Heuristic: scan for a process
    whose cmdline contains 'mcpm', '_worker', and the server name."""
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if not cmdline:
                continue
            joined = " ".join(cmdline)
            if "mcpm" in joined and "_worker" in cmdline and name in cmdline:
                rss = proc.memory_info().rss
                return proc.info["pid"], rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None, None


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n_f = n / 1024
        if n_f < 1024:
            return f"{n_f:.1f} {unit}"
        n = n_f  # type: ignore
    return f"{n_f:.1f} TB"


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
