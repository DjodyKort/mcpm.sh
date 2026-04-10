"""Tests for the tap system."""

import json

from mcpm.skills.taps import TapManager


class TestTapManager:
    def test_parse_spec_full(self):
        """Test parsing @user/repo/skill@version."""
        result = TapManager._parse_spec("@anthropics/skills/code-review@1.2.0")
        assert result == ("anthropics/skills", "code-review", "1.2.0")

    def test_parse_spec_repo_only(self):
        """Test parsing @user/repo (no skill, no version)."""
        result = TapManager._parse_spec("@anthropics/skills")
        assert result == ("anthropics/skills", None, None)

    def test_parse_spec_repo_and_skill(self):
        """Test parsing @user/repo/skill (no version)."""
        result = TapManager._parse_spec("@anthropics/skills/code-review")
        assert result == ("anthropics/skills", "code-review", None)

    def test_parse_spec_invalid(self):
        """Test parsing invalid spec."""
        result = TapManager._parse_spec("just-a-name")
        assert result is None

    def test_parse_spec_no_at(self):
        """Test parsing without @ prefix."""
        result = TapManager._parse_spec("anthropics/skills")
        assert result == ("anthropics/skills", None, None)

    def test_list_empty(self, tmp_path):
        """Test listing taps when none registered."""
        manager = TapManager(taps_dir=tmp_path / "taps", index_path=tmp_path / "index.json")
        assert manager.list_taps() == {}

    def test_add_and_list(self, tmp_path):
        """Test adding a tap via local git repo (simulated)."""
        taps_dir = tmp_path / "taps"
        index_path = tmp_path / "index.json"
        manager = TapManager(taps_dir=taps_dir, index_path=index_path)

        # Simulate a tap by directly creating the index entry and directory
        tap_path = taps_dir / "test-tap"
        tap_path.mkdir(parents=True)
        skills_dir = tap_path / "skills" / "example"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            '---\nname: example\ndescription: "An example skill."\n---\n\nExample body.'
        )

        index = {"test-tap": {"repo": "test/tap", "url": "local", "path": str(tap_path)}}
        index_path.write_text(json.dumps(index))

        taps = manager.list_taps()
        assert "test-tap" in taps

    def test_remove(self, tmp_path):
        """Test removing a tap."""
        taps_dir = tmp_path / "taps"
        index_path = tmp_path / "index.json"
        manager = TapManager(taps_dir=taps_dir, index_path=index_path)

        tap_path = taps_dir / "test-tap"
        tap_path.mkdir(parents=True)
        index = {"test-tap": {"repo": "test/tap", "url": "local", "path": str(tap_path)}}
        index_path.write_text(json.dumps(index))

        assert manager.remove("test-tap") is True
        assert manager.list_taps() == {}
        assert not tap_path.exists()

    def test_remove_nonexistent(self, tmp_path):
        """Test removing a non-existent tap."""
        manager = TapManager(taps_dir=tmp_path / "taps", index_path=tmp_path / "index.json")
        assert manager.remove("nonexistent") is False

    def test_search(self, tmp_path):
        """Test searching across taps."""
        taps_dir = tmp_path / "taps"
        index_path = tmp_path / "index.json"
        manager = TapManager(taps_dir=taps_dir, index_path=index_path)

        # Create a tap with skills
        tap_path = taps_dir / "test-tap"
        for name, desc in [("code-review", "Automated code review"), ("terraform", "Terraform best practices")]:
            skill_dir = tap_path / "skills" / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "{desc}"\n---\n\nBody.')

        index = {"test-tap": {"repo": "test/tap", "url": "local", "path": str(tap_path)}}
        index_path.write_text(json.dumps(index))

        results = manager.search("code review")
        assert len(results) == 1
        assert results[0]["name"] == "code-review"

        results = manager.search("terraform")
        assert len(results) == 1
        assert results[0]["name"] == "terraform"

        results = manager.search("nonexistent")
        assert len(results) == 0

    def test_tap_key(self):
        """Test tap key generation."""
        manager = TapManager()
        assert manager._tap_key("anthropics/skills") == "anthropics-skills"
