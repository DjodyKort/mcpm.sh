"""Skills sync command -- transpile to all installed clients."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import discover_skills, find_skills_repo
from mcpm.skills.transpiler import sync_skills as do_sync
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="sync")
@click.option("--client", type=str, default=None, help="Sync to a specific client only")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.option("--global", "global_mode", is_flag=True, help="Sync to user-level paths (~/) instead of project-level")
@click.option(
    "--migrate/--no-migrate",
    "migrate",
    default=None,
    help="On collision with a pre-existing file (e.g. ~/.claude/commands/<name>.md): "
    "--migrate auto-replaces with backup, --no-migrate warns only. "
    "Default: prompt in a terminal, warn in non-interactive runs.",
)
@click.help_option("-h", "--help")
def sync_skills(client, dry_run, path, global_mode, migrate):
    """Transpile canonical skills to all installed client formats.

    Reads SKILL.md files from the skills repository, renders them to each client's
    native instruction format, and writes the output files. Updates the lockfile.

    Append-mode clients (Zed, AGENTS.md) get all skills concatenated into a single
    managed block. Per-file clients get one output file per skill.

    Use --global to write to user-level paths (e.g. ~/.claude/skills/) instead of
    project-relative paths. Project-only clients (VS Code Copilot, Zed, AGENTS.md)
    are skipped in global mode.

    \b
        mcpm skills sync
        mcpm skills sync --global
        mcpm skills sync --client claude-code
        mcpm skills sync --dry-run
        mcpm skills sync --global --migrate
    """
    # Find skills repo
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    # Discover skills
    skills = discover_skills(repo_path)
    if not skills:
        console.print("[yellow]No skills found in repository.[/]")
        return

    # Project-mode footgun guard: without --global, sync writes to
    # <project_root>/.claude/skills/ etc. -- where project_root is the skills
    # repo returned by find_skills_repo. If the user didn't point at that
    # path explicitly (no --path) AND their cwd isn't inside it, then
    # find_skills_repo resolved via the git-sync fallback and the output
    # would never reach any installed client.
    #
    # When that fallback path is the canonical mcpm sync repo, the user is
    # almost certainly running `mcpm skills sync` from $HOME and meant
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
                    "~/.claude/skills/), pass [cyan]--path[/] to opt in to a specific "
                    "project root explicitly, or cd into the skills repo first."
                )
                return

    # Determine target clients
    client_keys = [client] if client else None

    if dry_run:
        console.print("[cyan]Dry run -- no files will be written.[/]\n")

    if global_mode:
        console.print("[cyan]Global mode -- writing to user-level paths.[/]\n")

    # Run sync (handles both per-file and append-mode transpilers)
    result = do_sync(
        skills,
        repo_path,
        client_keys=client_keys,
        dry_run=dry_run,
        global_mode=global_mode,
        migrate=migrate,
        console=console,
    )
    lockfile = result.lockfile

    # Save lockfile
    if not dry_run:
        if global_mode:
            from mcpm.utils.platform import get_config_directory

            global_lockfile_dir = get_config_directory()
            global_lockfile_dir.mkdir(parents=True, exist_ok=True)
            config_manager = SkillsConfigManager(project_root=global_lockfile_dir)
        else:
            config_manager = SkillsConfigManager(project_root=repo_path)
        config_manager.save_lockfile(lockfile)

    # Report results
    all_entries = {**lockfile.skills, **lockfile.rules}
    total_skills = len(all_entries)
    total_clients = len(set(c for e in all_entries.values() for c in e.clients_synced))

    prefix = "[cyan](dry run)[/] " if dry_run else ""
    console.print(f"\n{prefix}[green]Synced {total_skills} skill(s) to {total_clients} client(s).[/]\n")

    # Show details table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Skill", style="cyan")
    table.add_column("Type")
    table.add_column("Clients synced", overflow="fold")
    table.add_column("Warnings", overflow="fold")

    for name, entry in all_entries.items():
        skill_type = "rule" if name in lockfile.rules else "skill"
        clients_str = ", ".join(entry.clients_synced) if entry.clients_synced else "[dim]none[/]"
        warnings_str = "; ".join(entry.warnings) if entry.warnings else "[dim]--[/]"
        table.add_row(name, skill_type, clients_str, warnings_str)

    console.print(table)

    # Check if append-mode transpilers produced output
    has_agents_md = any("agents-md" in e.clients_synced for e in all_entries.values())
    has_zed = any("zed" in e.clients_synced for e in all_entries.values())
    if has_agents_md:
        console.print(f"\n{prefix}Updated AGENTS.md with <available_skills> block.")
    if has_zed:
        console.print(f"{prefix}Updated .rules with concatenated skills for Zed.")

    # Stale-file cleanup summary
    if result.cleaned:
        console.print(
            f"\n{prefix}[yellow]Removed {len(result.cleaned)} stale file(s)[/] "
            "from prior syncs (renames or deletions):"
        )
        for p in result.cleaned:
            try:
                display = p.relative_to(result.output_root)
            except ValueError:
                display = p
            console.print(f"  [red]-[/] {display}")

    # Collision summary
    summary_obj = result.collision_summary
    if summary_obj and summary_obj.resolutions:
        replaced = len(summary_obj.replaced)
        kept = len(summary_obj.kept)
        if replaced:
            console.print(f"\n{prefix}[green]Replaced {replaced} colliding file(s)[/] (backed up).")
        if kept:
            console.print(
                f"\n{prefix}[yellow]{kept} unresolved collision(s).[/] "
                "Run [bold]mcpm skills resolve[/] to handle them, "
                "or re-run with [bold]--migrate[/] to auto-replace."
            )


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
