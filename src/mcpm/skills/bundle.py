"""Bundle packaging -- create portable skill packages."""

import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from mcpm.skills.parser import discover_skills

logger = logging.getLogger(__name__)


def create_bundle(
    repo_path: Path,
    output_path: Optional[Path] = None,
    skill_names: Optional[List[str]] = None,
) -> Path:
    """Create a portable zip bundle of skills.

    The bundle contains:
    - mcpm-skills-bundle.json (manifest with metadata)
    - skills/ and rules/ directories with SKILL.md files and supporting files
    - Any servers.json files for MCP server dependencies

    Args:
        repo_path: Root of the skills repository.
        output_path: Output zip path. Defaults to <repo_name>-skills-bundle.zip.
        skill_names: Specific skills to include. None = all.

    Returns:
        Path to the created bundle file.
    """
    skills = discover_skills(repo_path)

    if skill_names:
        skills = [s for s in skills if s.name in skill_names]

    if not skills:
        raise ValueError("No skills found to bundle")

    # Determine output path
    if output_path is None:
        manifest_path = repo_path / "mcpm-skills.yaml"
        if manifest_path.exists():
            # Use repo name from manifest
            from mcpm.skills.config import SkillsConfigManager

            manager = SkillsConfigManager(project_root=repo_path)
            manifest = manager.load_manifest()
            name = manifest.name if manifest else "skills"
        else:
            name = repo_path.name
        output_path = repo_path / f"{name}-bundle.zip"

    # Build bundle manifest
    bundle_manifest = {
        "format": "mcpm-skills-bundle",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "skills": [],
        "rules": [],
    }

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for skill in skills:
            skill_dir = skill.source_path.parent
            base_dir = "rules" if skill.skill_type == "rule" else "skills"
            rel_base = f"{base_dir}/{skill.name}"

            # Add all files from the skill directory
            for file_path in skill_dir.rglob("*"):
                if file_path.is_file():
                    arcname = f"{rel_base}/{file_path.relative_to(skill_dir)}"
                    zf.write(file_path, arcname)

            entry = {
                "name": skill.name,
                "description": skill.frontmatter.description,
                "activation": skill.frontmatter.activation,
                "type": skill.skill_type,
            }

            # Check for server dependencies
            servers_json = skill_dir / "servers.json"
            if servers_json.exists():
                entry["has_server_deps"] = True

            if skill.skill_type == "rule":
                bundle_manifest["rules"].append(entry)
            else:
                bundle_manifest["skills"].append(entry)

        # Also include repo manifest if it exists
        manifest_path = repo_path / "mcpm-skills.yaml"
        if manifest_path.exists():
            zf.write(manifest_path, "mcpm-skills.yaml")

        # Write bundle manifest
        zf.writestr("mcpm-skills-bundle.json", json.dumps(bundle_manifest, indent=2))

    return output_path


def extract_bundle(bundle_path: Path, target_path: Path) -> List[str]:
    """Extract a skills bundle to a target directory.

    Args:
        bundle_path: Path to the zip bundle.
        target_path: Directory to extract into.

    Returns:
        List of extracted skill names.
    """
    extracted_names = []

    with zipfile.ZipFile(bundle_path, "r") as zf:
        # Read manifest
        try:
            manifest_data = json.loads(zf.read("mcpm-skills-bundle.json"))
        except (KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid bundle: {e}")

        if manifest_data.get("format") != "mcpm-skills-bundle":
            raise ValueError("Not a valid mcpm skills bundle")

        # Extract all files
        for info in zf.infolist():
            if info.filename == "mcpm-skills-bundle.json":
                continue
            # Ensure paths are safe (no absolute paths, no ..)
            if info.filename.startswith("/") or ".." in info.filename:
                logger.warning(f"Skipping unsafe path: {info.filename}")
                continue
            zf.extract(info, target_path)

        # Collect names
        for entry in manifest_data.get("skills", []):
            extracted_names.append(entry["name"])
        for entry in manifest_data.get("rules", []):
            extracted_names.append(entry["name"])

    return extracted_names
