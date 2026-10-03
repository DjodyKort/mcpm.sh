"""Doctor command for MCPM - System health check and diagnostics"""

import importlib.metadata as metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlparse

from rich.console import Console

from mcpm.clients.client_registry import ClientRegistry
from mcpm.profile.profile_config import ProfileConfigManager
from mcpm.utils.config import ConfigManager
from mcpm.utils.repository import RepositoryManager
from mcpm.utils.rich_click_config import click

console = Console()


def _direct_url(dist: metadata.Distribution) -> dict:
    return json.loads(dist.read_text("direct_url.json") or "{}")


def _check_plugins() -> int:
    """Report plugins that should be installed but are missing or come from elsewhere.

    For an editable checkout the expected set is read from ``plugins/*/pyproject.toml``
    rather than mcpm's own metadata, which goes stale when the venv is rebuilt from an
    older checkout. Any plugin not installed editable from that tree is flagged, since
    the plugin names are not reserved on PyPI.
    """
    source_root = None
    try:
        own = _direct_url(metadata.distribution("mcpm"))
        if own.get("dir_info", {}).get("editable"):
            source_root = Path(unquote(urlparse(own["url"]).path))
    except metadata.PackageNotFoundError:
        pass

    expected: dict[str, Path | None] = {}
    if source_root:
        for pyproject in sorted((source_root / "plugins").glob("*/pyproject.toml")):
            expected[tomllib.loads(pyproject.read_text())["project"]["name"]] = pyproject.parent
    else:
        for requirement in metadata.requires("mcpm") or []:
            name = re.split(r"[\s;<>=!~\[(@]", requirement, maxsplit=1)[0]
            if name.startswith("mcpm-"):
                expected[name] = None

    issues = 0
    for name, plugin_dir in expected.items():
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            console.print(f"  ❌ Plugin {name} is not installed")
            issues += 1
            continue
        if plugin_dir:
            origin = _direct_url(dist)
            if origin.get("url", "").rstrip("/") != plugin_dir.as_uri() or not origin.get("dir_info", {}).get(
                "editable"
            ):
                console.print(f"  ⚠️  Plugin {name} is not an editable install of {plugin_dir}")
                issues += 1
                continue
        console.print(f"  ✅ Plugin {name} {dist.version}")

    if source_root:
        for plugin_dir in sorted((source_root / "plugins").iterdir()):
            if plugin_dir.is_dir() and not (plugin_dir / "pyproject.toml").exists():
                console.print(f"  ⚠️  {plugin_dir} is empty - run 'git submodule update --init --recursive'")
                issues += 1
        if issues:
            console.print(f"  💡 Reinstall: uv tool install --force --editable {source_root}", soft_wrap=True)
    return issues


@click.command()
@click.help_option("-h", "--help")
def doctor():
    """Check system health and installed server status.

    Performs comprehensive diagnostics of MCPM installation, configuration,
    and installed servers.

    Examples:
        mcpm doctor    # Run complete system health check
    """
    console.print("[bold green]🩺 MCPM System Health Check[/]")
    console.print()

    # Track overall health status
    issues_found = 0

    # 1. Check MCPM installation
    console.print("[bold cyan]📦 MCPM Installation[/]")
    try:
        from mcpm import __version__

        console.print(f"  ✅ MCPM version: {__version__}")
    except Exception as e:
        console.print(f"  ❌ MCPM installation error: {e}")
        issues_found += 1
    issues_found += _check_plugins()

    # 2. Check Python environment
    console.print("[bold cyan]🐍 Python Environment[/]")
    console.print(f"  ✅ Python version: {sys.version.split()[0]}")
    console.print(f"  ✅ Python executable: {sys.executable}")

    # Helper function to check CLI tools
    def _check_cli_tool(tool_name: str, display_name: str, not_found_msg: str) -> int:
        """Checks for a CLI tool, prints status, and returns 1 if an issue is found."""
        tool_path = shutil.which(tool_name)
        if tool_path:
            try:
                version = subprocess.check_output([tool_path, "--version"], stderr=subprocess.DEVNULL).decode().strip()
                console.print(f"  ✅ {display_name} version: {version}")
                return 0
            except (subprocess.CalledProcessError, OSError):
                console.print(f"  ⚠️  {display_name} found but failed to get version")
                return 1
        else:
            console.print(f"  ⚠️  {not_found_msg}")
            return 1

    # 3. Check Node.js (for npx servers)
    # Use shutil.which() to find executables - handles Windows .cmd/.bat files via PATHEXT
    console.print("[bold cyan]📊 Node.js Environment[/]")
    issues_found += _check_cli_tool("node", "Node.js", "Node.js not found - npx servers will not work")
    issues_found += _check_cli_tool("npm", "npm", "npm not found - package installation may fail")

    # 4. Check MCPM configuration
    console.print("[bold cyan]⚙️  MCPM Configuration[/]")
    try:
        config_manager = ConfigManager()
        config = config_manager.get_config()
        console.print(f"  ✅ Config file: {config_manager.config_path}")

        if config.get("node_executable"):
            console.print(f"  ✅ Node executable: {config['node_executable']}")
        else:
            console.print("  ⚠️  No default node executable set")

    except Exception as e:
        console.print(f"  ❌ Configuration error: {e}")
        issues_found += 1

    # 5. Check repository cache
    console.print("[bold cyan]📚 Repository Cache[/]")
    try:
        repo_manager = RepositoryManager()
        if os.path.exists(repo_manager.cache_file):
            console.print(f"  ✅ Cache file: {repo_manager.cache_file}")

            # Check cache age
            cache_age = Path(repo_manager.cache_file).stat().st_mtime
            import time

            if time.time() - cache_age > 86400:  # 24 hours
                console.print("  ⚠️  Cache is older than 24 hours - consider refreshing")
        else:
            console.print("  ⚠️  No cache file found - run 'mcpm search' to build cache")

    except Exception as e:
        console.print(f"  ❌ Cache check error: {e}")
        issues_found += 1

    # 6. Check supported clients
    console.print("[bold cyan]🖥️  Supported Clients[/]")
    try:
        clients = ClientRegistry.get_supported_clients()
        console.print(f"  ✅ {len(clients)} clients supported:")

        # Get display names for better readability
        client_info = ClientRegistry.get_all_client_info()

        # Check which clients are installed
        installed_clients = []
        not_installed_clients = []

        for client in clients:
            try:
                client_manager = ClientRegistry.get_client_manager(client)
                if client_manager and client_manager.is_client_installed():
                    installed_clients.append(client)
                else:
                    not_installed_clients.append(client)
            except Exception:
                not_installed_clients.append(client)

        # Show installed clients
        if installed_clients:
            console.print(f"    ✅ Installed ({len(installed_clients)}): ", end="")
            display_names = []
            for client in installed_clients:
                info = client_info.get(client, {})
                display_name = info.get("name", client)
                display_names.append(display_name)
            console.print(", ".join(display_names))

        # Show available but not installed clients (first few)
        if not_installed_clients:
            console.print(f"    ⚪ Available ({len(not_installed_clients)}): ", end="")
            display_names = []
            for client in not_installed_clients[:3]:  # Show first 3
                info = client_info.get(client, {})
                display_name = info.get("name", client)
                display_names.append(display_name)
            if len(not_installed_clients) > 3:
                display_names.append(f"and {len(not_installed_clients) - 3} more")
            console.print(", ".join(display_names))

        if not installed_clients and not not_installed_clients:
            console.print("  ⚠️  No client information available")

    except Exception as e:
        console.print(f"  ❌ Client check error: {e}")
        issues_found += 1

    # 7. Check profiles
    console.print("[bold cyan]📁 Profiles[/]")
    try:
        profile_manager = ProfileConfigManager()
        profiles = profile_manager.list_profiles()
        console.print(f"  ✅ {len(profiles)} profiles configured")

        if profiles:
            profile_names = list(profiles.keys()) if isinstance(profiles, dict) else profiles
            for profile in profile_names[:3]:  # Show first 3
                console.print(f"    - {profile}")
            if len(profile_names) > 3:
                console.print(f"    ... and {len(profile_names) - 3} more")

    except Exception as e:
        console.print(f"  ❌ Profile check error: {e}")
        issues_found += 1

    # 8. Summary
    console.print()
    if issues_found == 0:
        console.print("[bold green]✅ All systems healthy! No issues found.[/]")
    else:
        console.print(f"[bold yellow]⚠️  {issues_found} issue(s) detected.[/]")
        console.print()
        console.print("[italic]Suggestions:[/]")
        console.print("  • Run 'mcpm config set' to configure node executable")
        console.print("  • Run 'mcpm search' to build repository cache")
        console.print("  • Install Node.js for npx server support")

    console.print()
    console.print("[italic]For more help, visit: https://github.com/pathintegral-institute/mcpm.sh[/]")
