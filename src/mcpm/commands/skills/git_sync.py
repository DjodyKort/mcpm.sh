"""Skills git-sync command -- configure and run git-based skills sync."""

from rich.console import Console

from mcpm.skills.sync_git import SkillsSyncConfig, full_sync
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="git-sync")
@click.option("--repo", type=str, default=None, help="Git repo URL to sync from")
@click.option("--branch", type=str, default="main", help="Branch to use (default: main)")
@click.option("--auto", "auto_sync", is_flag=True, help="Enable auto-sync on 'mcpm sync'")
@click.option("--status", "show_status", is_flag=True, help="Show current sync configuration")
@click.option("--clear", is_flag=True, help="Remove sync configuration")
@click.help_option("-h", "--help")
def git_sync_skills(repo, branch, auto_sync, show_status, clear):
    """Configure and run git-based skills sync.

    Links a remote git repository as your skills source. When configured,
    'mcpm skills git-sync' pulls the latest skills and transpiles to all clients.

    \b
        mcpm skills git-sync --repo git@github.com:user/my-skills.git
        mcpm skills git-sync --repo https://github.com/user/my-skills.git --auto
        mcpm skills git-sync --status
        mcpm skills git-sync --clear
    """
    config = SkillsSyncConfig()

    if clear:
        config.clear()
        console.print("[green]Skills sync configuration cleared.[/]")
        return

    if show_status:
        repo_url = config.get_repo()
        if not repo_url:
            console.print("[yellow]No skills sync configured.[/]")
            console.print("Run: mcpm skills git-sync --repo <url>")
            return

        console.print("\n[cyan]Skills sync configuration:[/]")
        console.print(f"  Repository: {repo_url}")
        console.print(f"  Branch:     {config.get_branch()}")
        console.print(f"  Auto-sync:  {config.get_auto_sync()}")
        local = config.get_local_path()
        if local and local.exists():
            console.print(f"  Local path: {local} [green](cloned)[/]")
        elif local:
            console.print(f"  Local path: {local} [yellow](not yet cloned)[/]")
        return

    if repo:
        # Configure new repo
        local_path = config.configure(repo=repo, branch=branch, auto_sync=auto_sync)
        console.print("[green]Skills sync configured:[/]")
        console.print(f"  Repository: {repo}")
        console.print(f"  Branch:     {branch}")
        console.print(f"  Local path: {local_path}")
        if auto_sync:
            console.print("  Auto-sync:  enabled")
        console.print()

    # Run sync
    repo_url = config.get_repo()
    if not repo_url:
        console.print("[yellow]No skills sync configured. Use --repo to set one.[/]")
        return

    console.print("[cyan]Syncing skills from git...[/]")
    result = full_sync()

    if result["pulled"]:
        console.print("[green]Pulled latest changes.[/]")
    elif config.get_local_path() and config.get_local_path().exists():
        console.print("[yellow]Pull failed or no changes.[/]")

    if result["skills_count"] > 0:
        console.print(f"[green]Synced {result['skills_count']} skill(s) to clients.[/]")
    else:
        console.print("[yellow]No skills found in repository.[/]")
