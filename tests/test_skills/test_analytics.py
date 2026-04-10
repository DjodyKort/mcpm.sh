"""Tests for skills usage analytics."""

import asyncio

import pytest

from mcpm.skills.analytics import SkillsAnalytics


@pytest.fixture
def analytics(tmp_path):
    """Create analytics with a temp database."""
    from mcpm.monitor.sqlite import SQLiteAccessMonitor

    monitor = SQLiteAccessMonitor(db_path=str(tmp_path / "test_monitor.db"))
    return SkillsAnalytics(monitor=monitor)


class TestSkillsAnalytics:
    def test_track_sync(self, analytics):
        """Test tracking a sync event."""
        result = asyncio.run(analytics.track_sync("code-review", ["claude-code", "cursor"], []))
        assert result is True

    def test_track_install(self, analytics):
        """Test tracking an install event."""
        result = asyncio.run(analytics.track_install("code-review", "@anthropics/skills"))
        assert result is True

    def test_track_uninstall(self, analytics):
        """Test tracking an uninstall event."""
        result = asyncio.run(analytics.track_uninstall("code-review"))
        assert result is True

    def test_get_stats_empty(self, analytics):
        """Test getting stats with no events."""
        stats = asyncio.run(analytics.get_skill_stats())
        assert stats["total_syncs"] == 0
        assert stats["total_installs"] == 0

    def test_get_stats_after_events(self, analytics):
        """Test getting stats after tracking events."""
        asyncio.run(analytics.track_sync("code-review", ["claude-code"], []))
        asyncio.run(analytics.track_sync("code-review", ["cursor"], []))
        asyncio.run(analytics.track_sync("terraform", ["claude-code"], []))
        asyncio.run(analytics.track_install("code-review", "@org/skills"))

        stats = asyncio.run(analytics.get_skill_stats())
        assert stats["total_syncs"] == 3
        assert stats["total_installs"] == 1
        assert stats["syncs_by_skill"]["code-review"] == 2
        assert stats["syncs_by_skill"]["terraform"] == 1

    def test_track_install_failure(self, analytics):
        """Test tracking a failed install."""
        result = asyncio.run(
            analytics.track_install("bad-skill", "@org/broken", success=False, error_message="clone failed")
        )
        assert result is True
