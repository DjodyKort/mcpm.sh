"""Agents sync command -- transpile to all installed clients."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.agents.parser import discover_agents
from mcpm.skills.agents.transpiler import sync_agents
from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="sync")
@click.option("--client", type=str, default=None, help="Sync to a specific client only")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.option("--global", "global_mode", is_flag=True, help="Sync to user-level paths (~/) instead of project-level")
@click.help_option("-h", "--help")
def sync_agents_cmd(client, dry_run, path, global_mode):
    """Transpile canonical agents to all installed client formats.

    Reads AGENT.md files from the agents/ directory and renders them to each
    client's native agent format.

    Use --global to write to user-level paths (e.g. ~/.claude/agents/) instead
    of project-relative paths. Project-only clients (VS Code Copilot, Roo Code)
    are skipped in global mode.

    \b
        mcpm agents sync
        mcpm agents sync --global
        mcpm agents sync --client claude-code
        mcpm agents sync --dry-run
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    found_agents = discover_agents(repo_path)
    if not found_agents:
        console.print("[yellow]No agents found in repository.[/]")
        return

    # Project-mode footgun guard: without --global, sync writes to
    # <project_root>/.claude/agents/ etc. -- where project_root is the skills
    # repo returned by find_skills_repo. If the user didn't point at that
    # path explicitly (no --path) AND their cwd isn't inside it, then
    # find_skills_repo resolved via the git-sync fallback and the output
    # would never reach any installed client.
    #
    # When that fallback path is the canonical mcpm sync repo, the user is
    # almost certainly running `mcpm agents sync` from $HOME and meant
    # global mode -- auto-promote instead of erroring out. The hard error
    # remains for cases where some unrelated repo got picked up.
    if not global_mode and not path:
        repo_resolved = repo_path.resolve()
        cwd_resolved = Path.cwd().resolve()
        cwd_inside_repo = cwd_resolved == repo_resolved or repo_resolved in cwd_resolved.parents
        if not cwd_inside_repo:
            if _is_canonical_sync_repo(repo_resolved):
                console.print(
                    "[dim]Detected canonical skills repo at "
                    f"{repo_path}; cwd is outside it -- promoting to "
                    "[cyan]--global[/] mode.[/]"
                )
                global_mode = True
            else:
                console.print(
                    "[red]Error: project-mode sync would write into "
                    f"[yellow]{repo_path}[/] (auto-detected skills repo), but cwd is "
                    "not inside it -- no client will read from there.[/]"
                )
                console.print(
                    "Use [cyan]--global[/] to sync to user-level paths (e.g. "
                    "~/.claude/agents/), pass [cyan]--path[/] to opt in to a specific "
                    "project root explicitly, or cd into the skills repo first."
                )
                return

    client_keys = [client] if client else None

    if dry_run:
        console.print("[cyan]Dry run -- no files will be written.[/]\n")

    if global_mode:
        console.print("[cyan]Global mode -- writing to user-level paths.[/]\n")

    # Load existing lockfile to extend. In global mode the lockfile lives
    # under the global config directory, not the skills repo, so a global
    # sync and `agents clean --global` (which reads get_config_directory())
    # agree on where the managed-file record is kept.
    if global_mode:
        from mcpm.utils.platform import get_config_directory

        lock_dir = get_config_directory()
        lock_dir.mkdir(parents=True, exist_ok=True)
        config_manager = SkillsConfigManager(project_root=lock_dir)
    else:
        config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    lockfile = sync_agents(
        found_agents,
        repo_path,
        client_keys=client_keys,
        dry_run=dry_run,
        lockfile=lockfile,
        global_mode=global_mode,
    )

    if not dry_run:
        config_manager.save_lockfile(lockfile)

    total_agents = len(lockfile.agents)
    total_clients = len(set(c for e in lockfile.agents.values() for c in e.clients_synced))

    prefix = "[cyan](dry run)[/] " if dry_run else ""
    console.print(f"\n{prefix}[green]Synced {total_agents} agent(s) to {total_clients} client(s).[/]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Agent", style="cyan")
    table.add_column("Model")
    table.add_column("Clients synced", overflow="fold")
    table.add_column("Warnings", overflow="fold")

    for name, entry in lockfile.agents.items():
        agent = next((a for a in found_agents if a.name == name), None)
        model = agent.frontmatter.model or "[dim]default[/]" if agent else "--"
        clients_str = ", ".join(entry.clients_synced) if entry.clients_synced else "[dim]none[/]"
        warnings_str = "; ".join(entry.warnings) if entry.warnings else "[dim]--[/]"
        table.add_row(name, model, clients_str, warnings_str)

    console.print(table)


def _is_canonical_sync_repo(repo_path: Path) -> bool:
    """Return True if `repo_path` matches the cross-machine sync clone path.

    Reads the same `skills_sync.json` config that `find_skills_repo` uses as
    a fallback, so the auto-promotion to --global only fires for that one
    well-known location -- never for an unrelated project that happened to
    live above cwd.
    """
    try:
        import json

        from mcpm.utils.platform import get_config_directory

        config_path = get_config_directory() / "skills_sync.json"
        if not config_path.exists():
            return False
        data = json.loads(config_path.read_text(encoding="utf-8"))
        canonical = data.get("local_path")
        if not canonical:
            return False
        return Path(canonical).resolve() == repo_path
    except Exception:
        return False
