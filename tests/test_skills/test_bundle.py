"""Tests for skills bundle packaging."""

import json
import zipfile

import pytest

from mcpm.skills.bundle import create_bundle, extract_bundle

from .conftest import SAMPLE_RULE_MD, SAMPLE_SKILL_MD


def _setup_repo(tmp_path):
    """Create a minimal skills repo for bundling tests."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / "mcpm-skills.yaml"
    manifest.write_text("name: test-bundle\ndescription: Test bundle\nauthor: tester\nversion: '1.0.0'\n")

    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)

    # Add a script file to verify bundling of supporting files
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "check.sh").write_text("#!/bin/bash\necho 'checking'\n")

    rule_dir = tmp_path / "rules" / "coding-standards"
    rule_dir.mkdir(parents=True)
    (rule_dir / "SKILL.md").write_text(SAMPLE_RULE_MD)

    return tmp_path


class TestCreateBundle:
    def test_creates_zip(self, tmp_path):
        """Test that bundle creates a valid zip file."""
        repo = _setup_repo(tmp_path / "repo")
        bundle_path = create_bundle(repo)
        assert bundle_path.exists()
        assert bundle_path.suffix == ".zip"
        assert zipfile.is_zipfile(bundle_path)

    def test_bundle_contains_skills(self, tmp_path):
        """Test that bundle contains the expected files."""
        repo = _setup_repo(tmp_path / "repo")
        bundle_path = create_bundle(repo)

        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = zf.namelist()
            assert "skills/code-review/SKILL.md" in names
            assert "rules/coding-standards/SKILL.md" in names
            assert "mcpm-skills-bundle.json" in names

    def test_bundle_contains_scripts(self, tmp_path):
        """Test that supporting files (scripts/) are included."""
        repo = _setup_repo(tmp_path / "repo")
        bundle_path = create_bundle(repo)

        with zipfile.ZipFile(bundle_path, "r") as zf:
            names = zf.namelist()
            assert "skills/code-review/scripts/check.sh" in names

    def test_bundle_manifest(self, tmp_path):
        """Test that bundle manifest has correct metadata."""
        repo = _setup_repo(tmp_path / "repo")
        bundle_path = create_bundle(repo)

        with zipfile.ZipFile(bundle_path, "r") as zf:
            manifest = json.loads(zf.read("mcpm-skills-bundle.json"))
            assert manifest["format"] == "mcpm-skills-bundle"
            assert manifest["version"] == 1
            assert len(manifest["skills"]) == 1
            assert len(manifest["rules"]) == 1
            assert manifest["skills"][0]["name"] == "code-review"

    def test_bundle_specific_skills(self, tmp_path):
        """Test bundling only specific skills."""
        repo = _setup_repo(tmp_path / "repo")
        bundle_path = create_bundle(repo, skill_names=["code-review"])

        with zipfile.ZipFile(bundle_path, "r") as zf:
            manifest = json.loads(zf.read("mcpm-skills-bundle.json"))
            assert len(manifest["skills"]) == 1
            assert len(manifest["rules"]) == 0

    def test_bundle_custom_output(self, tmp_path):
        """Test custom output path."""
        repo = _setup_repo(tmp_path / "repo")
        output = tmp_path / "custom.zip"
        bundle_path = create_bundle(repo, output_path=output)
        assert bundle_path == output
        assert output.exists()

    def test_bundle_no_skills_raises(self, tmp_path):
        """Test error when no skills to bundle."""
        empty_repo = tmp_path / "empty"
        empty_repo.mkdir()
        (empty_repo / "skills").mkdir()
        with pytest.raises(ValueError, match="No skills found"):
            create_bundle(empty_repo)


class TestExtractBundle:
    def test_roundtrip(self, tmp_path):
        """Test creating and extracting a bundle."""
        repo = _setup_repo(tmp_path / "repo")
        bundle_path = create_bundle(repo)

        target = tmp_path / "extracted"
        target.mkdir()
        names = extract_bundle(bundle_path, target)

        assert "code-review" in names
        assert "coding-standards" in names
        assert (target / "skills" / "code-review" / "SKILL.md").exists()
        assert (target / "rules" / "coding-standards" / "SKILL.md").exists()
        assert (target / "skills" / "code-review" / "scripts" / "check.sh").exists()

    def test_invalid_bundle(self, tmp_path):
        """Test extracting an invalid bundle."""
        bad_zip = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("random.txt", "not a bundle")

        with pytest.raises(ValueError, match="Invalid bundle"):
            extract_bundle(bad_zip, tmp_path / "out")
