"""Skills usage analytics -- track skill sync/install events using the existing monitor."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from mcpm.monitor.base import AccessEventType

logger = logging.getLogger(__name__)


class SkillsAnalytics:
    """Track skill-related events using mcpm's existing SQLite monitor.

    Events are stored in the same monitor_events table with:
    - event_type: RESOURCE_ACCESS (for sync/read) or TOOL_INVOCATION (for install/uninstall)
    - server_id: "mcpm-skills" (constant, to distinguish from server events)
    - resource_id: "skill:{action}:{skill_name}" (e.g. "skill:sync:code-review")
    - metadata: JSON with detailed skill info
    """

    def __init__(self, monitor=None):
        if monitor is None:
            from mcpm.monitor.sqlite import SQLiteAccessMonitor

            monitor = SQLiteAccessMonitor()
        self.monitor = monitor

    async def _ensure_initialized(self):
        """Initialize storage if needed."""
        await self.monitor.initialize_storage()

    async def track_sync(
        self,
        skill_name: str,
        clients_synced: List[str],
        warnings: List[str],
        duration_ms: Optional[int] = None,
    ) -> bool:
        """Track a skill sync event."""
        await self._ensure_initialized()
        return await self.monitor.track_event(
            event_type=AccessEventType.RESOURCE_ACCESS,
            server_id="mcpm-skills",
            resource_id=f"skill:sync:{skill_name}",
            timestamp=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            success=True,
            metadata={
                "action": "sync",
                "skill_name": skill_name,
                "clients_synced": clients_synced,
                "warnings": warnings,
            },
        )

    async def track_install(
        self,
        skill_name: str,
        source: str,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> bool:
        """Track a skill install event."""
        await self._ensure_initialized()
        return await self.monitor.track_event(
            event_type=AccessEventType.TOOL_INVOCATION,
            server_id="mcpm-skills",
            resource_id=f"skill:install:{skill_name}",
            timestamp=datetime.now(timezone.utc),
            success=success,
            error_message=error_message,
            metadata={
                "action": "install",
                "skill_name": skill_name,
                "source": source,
            },
        )

    async def track_uninstall(self, skill_name: str) -> bool:
        """Track a skill uninstall event."""
        await self._ensure_initialized()
        return await self.monitor.track_event(
            event_type=AccessEventType.TOOL_INVOCATION,
            server_id="mcpm-skills",
            resource_id=f"skill:uninstall:{skill_name}",
            timestamp=datetime.now(timezone.utc),
            success=True,
            metadata={
                "action": "uninstall",
                "skill_name": skill_name,
            },
        )

    async def get_skill_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get skill usage statistics.

        Returns:
            Dict with skill analytics: total syncs, installs, most-synced skills, etc.
        """
        await self._ensure_initialized()
        response = await self.monitor.query_events(
            offset=f"{days}d",
            page=1,
            limit=1000,
            event_type=None,
        )

        # Filter to skill events
        skill_events = [e for e in response.events if e.server_id == "mcpm-skills"]

        syncs = {}
        installs = {}
        uninstalls = 0

        for event in skill_events:
            metadata = event.metadata or {}
            action = metadata.get("action", "")
            skill_name = metadata.get("skill_name", "unknown")

            if action == "sync":
                syncs[skill_name] = syncs.get(skill_name, 0) + 1
            elif action == "install":
                installs[skill_name] = installs.get(skill_name, 0) + 1
            elif action == "uninstall":
                uninstalls += 1

        return {
            "total_syncs": sum(syncs.values()),
            "total_installs": sum(installs.values()),
            "total_uninstalls": uninstalls,
            "syncs_by_skill": dict(sorted(syncs.items(), key=lambda x: x[1], reverse=True)),
            "installs_by_skill": dict(sorted(installs.items(), key=lambda x: x[1], reverse=True)),
        }


def track_sync_event(skill_name: str, clients_synced: List[str], warnings: List[str]) -> None:
    """Convenience function to track a sync event (runs async in background)."""
    try:
        analytics = SkillsAnalytics()
        asyncio.run(analytics.track_sync(skill_name, clients_synced, warnings))
    except Exception:
        pass  # Analytics should never break the main flow


def track_install_event(skill_name: str, source: str, success: bool = True) -> None:
    """Convenience function to track an install event."""
    try:
        analytics = SkillsAnalytics()
        asyncio.run(analytics.track_install(skill_name, source, success))
    except Exception:
        pass
