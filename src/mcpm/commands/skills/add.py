"""Skills add command -- create a new skill from template."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.schema import SkillFrontmatter
from mcpm.utils.rich_click_config import click

console = Console()


# Stub content for progressive-disclosure subdirectories.
# Authors expand these once the skill grows beyond a single SKILL.md file.
PROGRESSIVE_STUBS = {
    "modules/example.md": (
        "# Module: Example\n"
        "\n"
        "**Status:** Optional.\n"
        "\n"
        "## Section heading\n"
        "\n"
        "`## Example`\n"
        "\n"
        "## Trigger signals\n"
        "\n"
        "- When this module belongs in the spec.\n"
        "\n"
        "## Default content shape\n"
        "\n"
        "The body of this section when included.\n"
    ),
    "reference/example.md": (
        "# Example reference\n"
        "\n"
        "Deep content the SKILL.md links to but does not inline.\n"
        "\n"
        "Keep one level deep, no nested references.\n"
    ),
    "templates/example.md": (
        "# Example template\n"
        "\n"
        "Reusable scaffolding the skill renders with task-specific values.\n"
    ),
}


@click.command(name="add")
@click.argument("name")
@click.option("--type", "skill_type", type=click.Choice(["skill", "rule"]), default="skill", help="Type of skill")
@click.option("--path", type=click.Path(), default=".", help="Skills repo root (default: current directory)")
@click.option(
    "--with-progressive",
    is_flag=True,
    default=False,
    help="Scaffold modules/, reference/, and templates/ subdirectories with stub files for progressive-disclosure skills.",
)
@click.help_option("-h", "--help")
def add_skill(name, skill_type, path, with_progressive):
    """Create a new skill or rule from a template.

    NAME should be kebab-case (e.g., 'code-review', 'commit-conventions').

    \b
        mcpm skills add code-review
        mcpm skills add commit-conventions --type rule
        mcpm skills add modular-thing --with-progressive
    """
    # Validate name early
    try:
        SkillFrontmatter(name=name, description="placeholder")
    except Exception as e:
        console.print(f"[red]Error: Invalid skill name '{name}': {e}[/]")
        return

    if with_progressive and skill_type != "skill":
        console.print(
            "[red]Error: --with-progressive is only valid for skills, not rules.[/]"
        )
        return

    repo_path = Path(path).resolve()
    manager = SkillsConfigManager(project_root=repo_path)

    # Check if skill already exists
    base_dir = "rules" if skill_type == "rule" else "skills"
    if (repo_path / base_dir / name).exists():
        console.print(f"[red]Error: {skill_type.capitalize()} '{name}' already exists.[/]")
        return

    skill_file = manager.scaffold_skill(name, skill_type=skill_type)
    skill_dir = skill_file.parent

    if with_progressive:
        for rel_path, content in PROGRESSIVE_STUBS.items():
            target = skill_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

    console.print(f"\n[green]{skill_type.capitalize()} '{name}' created at {skill_file}[/]\n")
    if with_progressive:
        console.print(
            "Progressive-disclosure scaffolding added: modules/, reference/, templates/.\n"
        )
    console.print("Edit the SKILL.md file, then run 'mcpm skills sync' to transpile to all clients.\n")
