"""`mcpm context` — layered Claude context + CLAUDE_CONFIG_DIR profiles."""
from __future__ import annotations

import json

import click
from rich.console import Console
from rich.table import Table

from .backup import snapshot
from .config import load_config, save_config
from .dedupe import apply_dedupe, plan_dedupe
from .doctor import run_checks
from .layers import list_layers, scaffold_client_rule, scaffold_personal_rule
from .paths import claude_home, claude_json_path, profiles_root, shims_path
from .schema import ProfileSpec
from .settings import looks_secret_bearing
from .sync import apply, disable as do_disable

console = Console()
err = Console(stderr=True)


def _print_report(report) -> None:
    for a in report.actions:
        console.print(f"  [green]✓[/] {a}")
    for w in report.warnings:
        err.print(f"  [yellow]![/] {w}")


def _parse_spec_value(value: str):
    if value in ("inherit", "none"):
        return value
    return [v.strip() for v in value.split(",") if v.strip()]


@click.group(
    help="Layered Claude context (org/personal/per-client rules) + full CLAUDE_CONFIG_DIR profiles.",
    context_settings=dict(help_option_names=["-h", "--help"]),
)
def context() -> None:
    pass


@context.command(help="Show layers, profiles, dedupe state, and artifacts.")
def status() -> None:
    config = load_config()

    table = Table(show_header=False, box=None, pad_edge=False)
    layers = list_layers()
    table.add_row("layers", ", ".join(
        f"{layer.name}{' [' + ','.join(layer.globs) + ']' if layer.globs else ''}" for layer in layers
    ) or "[dim]none — run `mcpm context init`[/]")
    if config.profiles:
        for name, spec in sorted(config.profiles.items()):
            rules = spec.rules if isinstance(spec.rules, str) else ",".join(spec.rules)
            servers = spec.servers if isinstance(spec.servers, str) else f"{len(spec.servers)} selected"
            generated = (profiles_root() / name).is_dir()
            table.add_row(
                f"profile {name}",
                f"org={'on' if spec.org else 'off'}({spec.org_mode}) rules={rules} servers={servers} "
                + ("" if generated else "[yellow]not generated[/]"),
            )
    else:
        table.add_row("profiles", "[dim]none[/]")
    dupes = plan_dedupe(claude_json_path(), config.dedupe)
    table.add_row("legacy MCP dupes", f"[yellow]{', '.join(dupes)}[/]" if dupes else "[green]none[/]")
    table.add_row("shims", str(shims_path()) if shims_path().exists() else "[dim]none[/]")
    console.print(table)


@context.command(help="Seed config, scaffold the personal layer, offer settings.local.json migration.")
@click.option("--yes", is_flag=True, help="Non-interactive: accept defaults, skip prompts.")
def init(yes: bool) -> None:
    config = load_config()
    created = scaffold_personal_rule()
    if created:
        console.print(f"  [green]✓[/] scaffolded personal layer: {created}")
    else:
        console.print("  [dim]personal layer already scaffolded[/]")

    _offer_settings_local_migration(config, assume_yes=yes)
    save_config(config)
    console.print("  [green]✓[/] saved context.json")

    console.print("\n[bold]Next steps[/]:")
    console.print("  1. Edit your personal layer, then:  [cyan]mcpm skills sync --global[/]")
    console.print("  2. Per-client layer:                [cyan]mcpm context client add <name>[/]")
    console.print("  3. Profiles:                        [cyan]mcpm context profile add bare --no-org --rules none --servers none[/]")
    console.print("  4. Apply everything:                [cyan]mcpm context sync[/]")


def _offer_settings_local_migration(config, *, assume_yes: bool) -> None:
    """User-level settings.local.json is not supported by Claude Code (docs FAQ)
    — its allow entries silently do nothing there. Migrate them into
    ensure_allow so `sync` keeps them alive in settings.json past cf clobbers."""
    path = claude_home() / "settings.local.json"
    if not path.exists():
        return
    try:
        allow = json.loads(path.read_text()).get("permissions", {}).get("allow", [])
    except json.JSONDecodeError:
        err.print(f"  [yellow]![/] {path} unparseable — skipping migration")
        return
    if not allow:
        return
    secretish = [e for e in allow if looks_secret_bearing(e)]
    clean = [e for e in allow if e not in secretish and e not in config.settings.ensure_allow]
    console.print(f"\n  [yellow]![/] {path} is not read by Claude Code at user level (unsupported).")
    console.print(f"      {len(allow)} allow entr(y/ies) found; {len(clean)} migratable.")
    if secretish:
        err.print(f"      [red]{len(secretish)} entr(y/ies) embed credentials — NOT migrating; rotate + re-add manually:[/]")
        for e in secretish:
            err.print(f"        [dim]{e[:60]}…[/]" if len(e) > 60 else f"        [dim]{e}[/]")
    if clean and (assume_yes or click.confirm(f"      Migrate {len(clean)} entries into ensure_allow policy?", default=True)):
        config.settings.ensure_allow.extend(clean)
        console.print(f"  [green]✓[/] migrated {len(clean)} entries into ensure_allow")
        # File removal is destructive — never implied by --yes.
        if not assume_yes and click.confirm(f"      Back up and remove {path.name}? (file is inert)", default=False):
            snapshot(path)
            path.unlink()
            console.print(f"  [green]✓[/] backed up and removed {path}")


@context.command(help="Apply the config: dedupe, settings union, profiles, shims.")
def sync() -> None:
    _print_report(apply(load_config()))


@context.command(help="Health checks: dupes, staleness, broken links, cf-dev-tools drift.")
def doctor() -> None:
    checks = run_checks(load_config())
    icons = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]"}
    for level, msg in checks:
        console.print(f"  {icons[level]} {msg}")
    if any(level == "fail" for level, _ in checks):
        raise SystemExit(1)


@context.command(help="Remove cf-dev-tools' legacy MCP duplicates from ~/.claude.json.")
@click.option("--dry-run", is_flag=True, help="Show what would be removed.")
def dedupe(dry_run: bool) -> None:
    config = load_config()
    if dry_run:
        planned = plan_dedupe(claude_json_path(), config.dedupe)
        if planned:
            console.print(f"  would remove: [yellow]{', '.join(planned)}[/]")
        else:
            console.print("  [green]nothing to remove[/]")
        return
    removed = apply_dedupe(claude_json_path(), config.dedupe)
    if removed:
        console.print(f"  [green]✓[/] removed: {', '.join(removed)} (backup in ~/.cache/mcpm/context/backups)")
    else:
        console.print("  [green]nothing to remove[/]")


@context.group(help="Per-client context layers (path-scoped rules).")
def client() -> None:
    pass


@client.command("add", help="Scaffold a path-scoped client layer rule.")
@click.argument("name")
@click.option("--glob", "glob_", default=None, help='Path glob (default: "**/clients/<name>/**").')
def client_add(name: str, glob_: str | None) -> None:
    config = load_config()
    created = scaffold_client_rule(name, glob_, config.clients_root)
    if created:
        console.print(f"  [green]✓[/] scaffolded {created}")
        console.print("  fill in the body, then:  [cyan]mcpm skills sync --global[/]")
    else:
        console.print(f"  [dim]client layer {name!r} already exists[/]")


@client.command("list", help="List all context layers with their globs.")
def client_list() -> None:
    for layer in list_layers():
        scope = ", ".join(layer.globs) if layer.globs else "always-on"
        console.print(f"  [bold]{layer.name}[/]  [dim]{scope}[/]")


@context.group(help="Full CLAUDE_CONFIG_DIR profiles (claude-<name> shims).")
def profile() -> None:
    pass


@profile.command("add", help="Define a profile and generate it.")
@click.argument("name")
@click.option("--no-org", is_flag=True, help="Exclude the org CLAUDE.md layer.")
@click.option("--org-mode", type=click.Choice(["import", "copy"]), default="import", show_default=True)
@click.option("--rules", default="inherit", show_default=True, help='"inherit", "none", or CSV of layer names.')
@click.option("--servers", default="inherit", show_default=True, help='"inherit", "none", or CSV of mcpm server names.')
@click.option("--no-commands", is_flag=True, help="Don't link ~/.claude/commands.")
@click.option("--no-skills", is_flag=True, help="Don't link ~/.claude/skills.")
def profile_add(name: str, no_org: bool, org_mode: str, rules: str, servers: str,
                no_commands: bool, no_skills: bool) -> None:
    config = load_config()
    config.profiles[name] = ProfileSpec(
        org=not no_org,
        org_mode=org_mode,
        rules=_parse_spec_value(rules),
        servers=_parse_spec_value(servers),
        commands=not no_commands,
        skills=not no_skills,
    )
    # Re-validate (profile name shell-safety lives in the schema validator).
    config = type(config).model_validate(config.model_dump())
    _print_report(apply(config))


@profile.command("remove", help="Drop a profile from config (--purge also deletes its dir).")
@click.argument("name")
@click.option("--purge", is_flag=True, help="Also delete the generated profile dir.")
def profile_remove(name: str, purge: bool) -> None:
    from .profiles import remove_profile

    from .sync import ApplyReport

    config = load_config()
    if name not in config.profiles:
        err.print(f"  [yellow]![/] no profile {name!r} in config")
    config.profiles.pop(name, None)
    report = ApplyReport()
    if purge:
        remove_profile(name, report)  # before apply(), so no orphan warning
    inner = apply(config)
    report.actions.extend(inner.actions)
    report.warnings.extend(inner.warnings)
    _print_report(report)


@profile.command("list", help="List configured profiles.")
def profile_list() -> None:
    config = load_config()
    if not config.profiles:
        console.print("  [dim]no profiles — `mcpm context profile add <name>`[/]")
        return
    for name, spec in sorted(config.profiles.items()):
        rules = spec.rules if isinstance(spec.rules, str) else ",".join(spec.rules)
        servers = spec.servers if isinstance(spec.servers, str) else ",".join(spec.servers)
        console.print(f"  [bold]claude-{name}[/]  org={'on' if spec.org else 'off'}({spec.org_mode})  "
                      f"rules={rules}  servers={servers}")


@context.command(help="Strip generated artifacts (shims; --purge-profiles also profile dirs).")
@click.option("--purge-profiles", is_flag=True)
def disable(purge_profiles: bool) -> None:
    _print_report(do_disable(purge_profiles=purge_profiles))
