"""Generate a launchd user-agent plist that keeps the compression proxy warm."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List
from xml.sax.saxutils import escape

LAUNCHD_LABEL = "sh.mcpm.compression.proxy"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def launchd_plist(program_args: List[str], env: Dict[str, str]) -> str:
    """Render a KeepAlive launchd plist for `program_args` with `env`.

    Logs go to ~/.headroom/logs so they sit next to the proxy's own logs.
    """
    args_xml = "\n".join(f"        <string>{escape(a)}</string>" for a in program_args)
    env_xml = "\n".join(
        f"        <key>{escape(k)}</key>\n        <string>{escape(v)}</string>"
        for k, v in env.items()
    )
    log_dir = Path.home() / ".headroom" / "logs"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>EnvironmentVariables</key>
    <dict>
{env_xml}
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir / "proxy.out"}</string>
    <key>StandardErrorPath</key>
    <string>{log_dir / "proxy.err"}</string>
</dict>
</plist>
"""
