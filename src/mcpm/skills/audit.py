"""Security auditing for skills -- scan for prompt injection and suspicious patterns."""

import re
from dataclasses import dataclass, field
from typing import List

from mcpm.skills.schema import SkillConfig


@dataclass
class AuditFinding:
    """A single security finding."""

    severity: str  # "high", "medium", "low"
    skill_name: str
    message: str
    line: int = 0


@dataclass
class AuditResult:
    """Aggregate audit results."""

    findings: List[AuditFinding] = field(default_factory=list)

    @property
    def high(self) -> List[AuditFinding]:
        return [f for f in self.findings if f.severity == "high"]

    @property
    def has_high_severity(self) -> bool:
        return len(self.high) > 0

    def add(self, severity: str, skill_name: str, message: str, line: int = 0) -> None:
        self.findings.append(AuditFinding(severity=severity, skill_name=skill_name, message=message, line=line))


# Patterns that suggest prompt injection attempts
_INJECTION_PATTERNS = [
    (
        r"ignore\s+(all\s+)?previous\s+(instructions?|context|rules)",
        "high",
        "Prompt injection: ignore previous instructions",
    ),
    (r"disregard\s+(all\s+)?prior\s+(instructions?|context)", "high", "Prompt injection: disregard prior context"),
    (r"you\s+are\s+now\s+(a|an)\s+", "medium", "Possible prompt injection: role override attempt"),
    (
        r"override\s+(safety|security|system)\s+(guidelines?|rules?|restrictions?)",
        "high",
        "Prompt injection: safety override attempt",
    ),
    (r"system\s*:\s*you\s+are", "high", "Prompt injection: fake system prompt"),
]

# Patterns that suggest data exfiltration
_EXFILTRATION_PATTERNS = [
    (r"curl\s+.*\|\s*bash", "high", "Data exfiltration risk: piping curl to bash"),
    (r"wget\s+.*-O\s*-\s*\|\s*sh", "high", "Data exfiltration risk: piping wget to shell"),
    (r"base64\s+.*\|\s*curl", "high", "Data exfiltration risk: base64 encoding piped to curl"),
    (r"curl\s+-[dX]\s+POST\s+.*\$\(cat", "high", "Data exfiltration risk: posting file contents via curl"),
    (r"eval\s*\(\s*fetch\s*\(", "medium", "Suspicious: eval of fetched content"),
]

# Patterns that suggest excessive permissions
_PERMISSION_PATTERNS = [
    (r"rm\s+-rf\s+[/~]", "high", "Dangerous command: recursive delete of system paths"),
    (r"chmod\s+777", "medium", "Suspicious: setting world-writable permissions"),
    (r"sudo\s+", "medium", "Suspicious: sudo usage in skill instructions"),
    (r">\s*/etc/", "high", "Dangerous: writing to system config directory"),
]


def audit_skill(skill: SkillConfig) -> AuditResult:
    """Run security audit on a single skill."""
    result = AuditResult()
    body = skill.body
    lines = body.split("\n")

    for line_num, line in enumerate(lines, 1):
        line_lower = line.lower()

        for pattern, severity, message in _INJECTION_PATTERNS + _EXFILTRATION_PATTERNS + _PERMISSION_PATTERNS:
            if re.search(pattern, line_lower):
                result.add(severity, skill.name, message, line=line_num)

    # Check allowed-tools for excessive permissions
    if skill.frontmatter.allowed_tools:
        tools = skill.frontmatter.allowed_tools.split()
        broad_tools = [t for t in tools if t in ("Bash", "Bash(*)", "Write", "Edit")]
        if len(broad_tools) >= 3:
            result.add(
                "medium",
                skill.name,
                f"Broad tool permissions: {', '.join(broad_tools)}. Consider restricting to specific commands.",
            )

    return result


def audit_skills(skills: List[SkillConfig]) -> AuditResult:
    """Run security audit on a collection of skills."""
    result = AuditResult()
    for skill in skills:
        skill_result = audit_skill(skill)
        result.findings.extend(skill_result.findings)
    return result
