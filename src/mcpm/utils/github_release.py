"""
GitHub Release utilities for mcpm update.

Handles version checking, asset matching, downloading, extraction, checksum
verification, and atomic binary installation from GitHub Releases.
"""

import fnmatch
import hashlib
import logging
import os
import platform as platform_mod
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 300  # 5 minutes for large binaries
GITHUB_API_BASE = "https://api.github.com"


# --- Result types (mirrors git.py pattern) ---


@dataclass
class ReleaseCheckResult:
    """Result of checking a GitHub release for updates."""

    latest_version: str = ""
    current_version: str = ""
    has_update: bool = False
    release_url: str = ""
    asset_name: Optional[str] = None
    asset_url: Optional[str] = None
    asset_size: int = 0
    checksum_url: Optional[str] = None
    is_prerelease: bool = False
    error: Optional[str] = None


@dataclass
class ReleaseUpdateResult:
    """Result of applying a GitHub release update."""

    success: bool = False
    old_version: Optional[str] = None
    new_version: Optional[str] = None
    message: str = ""
    error: Optional[str] = None


# --- GitHub API ---


def _get_github_token() -> Optional[str]:
    """Get GitHub token from environment."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _github_request(endpoint: str, token: Optional[str] = None) -> requests.Response:
    """Make an authenticated GitHub API request."""
    url = f"{GITHUB_API_BASE}/{endpoint.lstrip('/')}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mcpm-update/1.0",
    }

    if token is None:
        token = _get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

    # Check rate limiting
    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining is not None and int(remaining) < 5:
        logger.warning(f"GitHub API rate limit nearly exhausted ({remaining} remaining). Set GITHUB_TOKEN for higher limits.")

    resp.raise_for_status()
    return resp


# --- Version comparison ---


def compare_versions(current: str, latest: str) -> int:
    """Compare two version strings. Returns -1 (current < latest), 0 (equal), 1 (current > latest).

    Handles v-prefix stripping and simple semver (major.minor.patch).
    Pre-release suffixes (e.g., -rc1, -beta) are treated as less than clean releases.
    """
    current = current.lstrip("v").strip()
    latest = latest.lstrip("v").strip()

    if current == latest:
        return 0

    def _parse(v: str):
        # Split off prerelease suffix
        pre = ""
        for sep in ["-", "+"]:
            if sep in v:
                v, pre = v.split(sep, 1)
                break

        parts = []
        for p in v.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)

        # Pad to 3 segments
        while len(parts) < 3:
            parts.append(0)

        return tuple(parts[:3]), pre

    cur_parts, cur_pre = _parse(current)
    lat_parts, lat_pre = _parse(latest)

    if cur_parts != lat_parts:
        return -1 if cur_parts < lat_parts else 1

    # Same numeric version -- prerelease < release
    if cur_pre and not lat_pre:
        return -1  # current is prerelease, latest is stable
    if not cur_pre and lat_pre:
        return 1  # current is stable, latest is prerelease
    if cur_pre == lat_pre:
        return 0
    return -1 if cur_pre < lat_pre else 1


# --- Platform detection ---

_OS_VARIANTS: Dict[str, List[str]] = {
    "linux": ["linux", "Linux"],
    "darwin": ["darwin", "Darwin", "macos", "macOS", "apple"],
    "win32": ["windows", "Windows", "win"],
}

_ARCH_VARIANTS: Dict[str, List[str]] = {
    "x86_64": ["x86_64", "amd64", "AMD64", "x64"],
    "AMD64": ["x86_64", "amd64", "AMD64", "x64"],
    "aarch64": ["arm64", "aarch64"],
    "arm64": ["arm64", "aarch64"],
    "armv7l": ["arm", "armv7", "armv7l"],
}

# Rust target triples for cargo-dist builds
_RUST_TRIPLES: Dict[str, Dict[str, str]] = {
    "linux": {
        "x86_64": "x86_64-unknown-linux-gnu",
        "AMD64": "x86_64-unknown-linux-gnu",
        "aarch64": "aarch64-unknown-linux-gnu",
        "arm64": "aarch64-unknown-linux-gnu",
    },
    "darwin": {
        "x86_64": "x86_64-apple-darwin",
        "AMD64": "x86_64-apple-darwin",
        "aarch64": "aarch64-apple-darwin",
        "arm64": "aarch64-apple-darwin",
    },
    "win32": {
        "x86_64": "x86_64-pc-windows-msvc",
        "AMD64": "x86_64-pc-windows-msvc",
        "aarch64": "aarch64-pc-windows-msvc",
        "arm64": "aarch64-pc-windows-msvc",
    },
}


def get_platform_identifiers() -> tuple:
    """Get (os_names, arch_names, rust_triple) for the current platform."""
    os_names = _OS_VARIANTS.get(sys.platform, [sys.platform])
    machine = platform_mod.machine()
    arch_names = _ARCH_VARIANTS.get(machine, [machine])

    rust_triple = None
    os_triples = _RUST_TRIPLES.get(sys.platform, {})
    if os_triples:
        rust_triple = os_triples.get(machine)

    return os_names, arch_names, rust_triple


# --- Asset matching ---

# File extensions to skip (not downloadable binaries)
_SKIP_EXTENSIONS = {".sha256", ".sha256sum", ".sha512", ".asc", ".sig", ".crt", ".sbom", ".pem", ".jsonl"}
_SKIP_NAMES = {"checksums.txt", "SHA256SUMS.txt", "SHA256SUMS", "dist-manifest.json", "CHANGELOG.md", "LICENSE"}

# System package formats -- skip unless specifically targeted
_SYSTEM_PKG_EXTENSIONS = {".deb", ".rpm", ".apk", ".pkg.tar.zst", ".snap", ".AppImage", ".dmg", ".msi"}


def match_asset(
    assets: List[dict],
    os_names: Optional[List[str]] = None,
    arch_names: Optional[List[str]] = None,
    rust_triple: Optional[str] = None,
    asset_pattern: Optional[str] = None,
) -> Optional[dict]:
    """Find the best matching release asset for the current platform.

    Args:
        assets: List of GitHub release asset dicts (name, browser_download_url, size).
        os_names: OS name variants to match (auto-detected if None).
        arch_names: Architecture name variants to match (auto-detected if None).
        rust_triple: Rust target triple for cargo-dist builds.
        asset_pattern: User-specified fnmatch pattern (overrides auto-matching).

    Returns:
        The best matching asset dict, or None.
    """
    if os_names is None or arch_names is None:
        os_names, arch_names, rust_triple = get_platform_identifiers()

    # User override with fnmatch pattern
    if asset_pattern:
        for asset in assets:
            if fnmatch.fnmatch(asset["name"], asset_pattern):
                return asset
        return None

    candidates = []

    for asset in assets:
        name = asset["name"]
        name_lower = name.lower()

        # Skip checksums, signatures, metadata
        if name in _SKIP_NAMES:
            continue
        if any(name.endswith(ext) for ext in _SKIP_EXTENSIONS):
            continue
        if any(name.endswith(ext) for ext in _SYSTEM_PKG_EXTENSIONS):
            continue
        # Skip .mcpb bundles (handled separately by mcpm)
        if name.endswith(".mcpb"):
            continue

        # Check Rust target triple first (most specific match)
        if rust_triple and rust_triple in name:
            score = 100  # High score for exact triple match
            candidates.append((score, asset))
            continue

        # Check OS + arch match
        os_match = any(variant in name for variant in os_names)
        arch_match = any(variant in name for variant in arch_names)

        if not os_match or not arch_match:
            continue

        # Score: base 50, bonus for preferred format
        score = 50
        if sys.platform == "win32":
            if name_lower.endswith(".zip"):
                score += 10
            elif name_lower.endswith(".exe"):
                score += 5
        else:
            if name_lower.endswith(".tar.gz") or name_lower.endswith(".tgz"):
                score += 10
            elif name_lower.endswith(".zip"):
                score += 5
            # Raw binary (no extension or just the name) gets lower score
            if "." not in name.rsplit("-", 1)[-1] if "-" in name else "." not in name:
                score += 2

        candidates.append((score, asset))

    if not candidates:
        return None

    # Return highest scoring candidate
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def find_checksum_asset(assets: List[dict], target_asset_name: str) -> Optional[dict]:
    """Find a checksum file for the given asset in the release assets."""
    # Priority order: per-file .sha256, then multi-file checksums
    check_names = [
        f"{target_asset_name}.sha256",
        f"{target_asset_name}.sha256sum",
        "checksums.txt",
        "SHA256SUMS.txt",
        "SHA256SUMS",
        "sha256sum.txt",
    ]

    for check_name in check_names:
        for asset in assets:
            if asset["name"] == check_name:
                return asset

    return None


# --- Download ---


def download_asset(url: str, dest_path: Path, token: Optional[str] = None) -> bool:
    """Download a release asset to dest_path with streaming."""
    headers = {"User-Agent": "mcpm-update/1.0"}
    if token is None:
        token = _get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(url, headers=headers, stream=True, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()

    # Write to temp file in same directory (for atomic rename)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest_path.parent))
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        Path(tmp_path).replace(dest_path)
        return True
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


# --- Checksum verification ---


def verify_checksum(file_path: Path, checksum_file: Path, asset_name: str) -> bool:
    """Verify SHA256 checksum of a file.

    Handles both per-file format (just hash or hash + filename) and
    multi-file format (GoReleaser checksums.txt with hash + filename per line).
    """
    checksum_content = checksum_file.read_text(encoding="utf-8").strip()

    expected_hash = None

    for line in checksum_content.splitlines():
        line = line.strip()
        if not line:
            continue

        # Split on whitespace (handles "hash  filename", "hash filename", "hash\tfilename")
        parts = line.split()
        if len(parts) >= 2:
            hash_val, fname = parts[0], parts[-1]
            if fname == asset_name or fname.endswith(f"/{asset_name}"):
                expected_hash = hash_val
                break
        elif len(parts) == 1:
            # Per-file format: just the hash
            expected_hash = parts[0]
            break

    if not expected_hash:
        logger.warning(f"Could not find checksum for '{asset_name}' in {checksum_file}")
        return True  # Don't block on unparseable checksums

    # Compute actual hash
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)

    actual_hash = sha256.hexdigest()

    if actual_hash != expected_hash:
        logger.error(f"Checksum mismatch for {asset_name}: expected {expected_hash[:16]}..., got {actual_hash[:16]}...")
        return False

    return True


# --- Extraction ---


def extract_archive(archive_path: Path, dest_dir: Path) -> List[Path]:
    """Extract an archive and return paths to extracted files.

    Handles tar.gz, zip, and raw binaries. For archives, walks into
    subdirectories to find the actual binary.
    """
    name = archive_path.name.lower()

    if name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".tar.xz"):
        mode = "r:gz" if not name.endswith(".tar.xz") else "r:xz"
        with tarfile.open(archive_path, mode) as tar:
            # Security: check for path traversal
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise ValueError(f"Unsafe path in archive: {member.name}")
            tar.extractall(dest_dir, filter="data" if hasattr(tarfile, "data_filter") else None)

    elif name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                if info.filename.startswith("/") or ".." in info.filename:
                    raise ValueError(f"Unsafe path in archive: {info.filename}")
            zf.extractall(dest_dir)

    else:
        # Raw binary -- just copy it
        dest = dest_dir / archive_path.name
        shutil.copy2(archive_path, dest)
        return [dest]

    # Find extracted files, filter out non-binaries
    extracted = []
    skip_names = {"LICENSE", "LICENSE.md", "README", "README.md", "CHANGELOG", "CHANGELOG.md", "completions"}
    for item in dest_dir.rglob("*"):
        if item.is_file() and item.name not in skip_names:
            extracted.append(item)

    return extracted


def find_binary_in_extracted(extracted_files: List[Path], repo_name: str = "") -> Optional[Path]:
    """Find the actual executable binary from extracted archive files.

    Prefers files matching the repo name. Falls back to files with
    executable permissions or no file extension (Unix convention).
    """
    if not extracted_files:
        return None

    if len(extracted_files) == 1:
        return extracted_files[0]

    # Score candidates
    candidates = []
    binary_name = repo_name.split("/")[-1] if "/" in repo_name else repo_name

    for f in extracted_files:
        score = 0
        name = f.name.lower()

        # Exact name match with repo
        if binary_name and name == binary_name.lower():
            score += 100
        elif binary_name and binary_name.lower() in name:
            score += 50

        # Executable on Unix
        if os.name != "nt" and os.access(f, os.X_OK):
            score += 30

        # No extension = likely binary on Unix
        if "." not in f.name:
            score += 20

        # .exe on Windows
        if f.name.lower().endswith(".exe"):
            score += 20

        # Skip common non-binary files
        if f.suffix in {".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".sh", ".bat", ".ps1"}:
            continue

        candidates.append((score, f))

    if not candidates:
        return extracted_files[0]  # Fallback to first file

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# --- Atomic installation ---


def install_binary(source_path: Path, target_path: Path) -> bool:
    """Atomically install a binary to target_path with backup/rollback.

    Creates backup at target_path.bak, copies new binary, sets permissions,
    and performs atomic replacement. Restores backup on failure.
    """
    backup_path = target_path.with_suffix(target_path.suffix + ".bak")

    # Check write permissions
    target_dir = target_path.parent
    if target_dir.exists() and not os.access(target_dir, os.W_OK):
        raise PermissionError(
            f"Cannot update {target_path}: permission denied on {target_dir}. "
            f"Try running with elevated privileges or move the binary to a user-writable location."
        )

    try:
        # Backup existing binary
        if target_path.exists():
            shutil.copy2(target_path, backup_path)

        # Copy new binary to .new location
        new_path = target_path.with_suffix(target_path.suffix + ".new")
        shutil.copy2(source_path, new_path)

        # Set executable permissions on Unix
        if os.name != "nt":
            new_path.chmod(new_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # Atomic replace
        new_path.replace(target_path)

        # Clean up backup on success
        backup_path.unlink(missing_ok=True)
        return True

    except Exception:
        # Rollback: restore backup
        if backup_path.exists():
            backup_path.replace(target_path)
        # Clean up .new if it exists
        new_path = target_path.with_suffix(target_path.suffix + ".new")
        if new_path.exists():
            new_path.unlink(missing_ok=True)
        raise


# --- High-level orchestration ---


def check_for_update(
    repo: str,
    current_version: Optional[str] = None,
    asset_pattern: Optional[str] = None,
    include_prerelease: bool = False,
) -> ReleaseCheckResult:
    """Check a GitHub repository for a newer release.

    Args:
        repo: GitHub repo in "owner/repo" format.
        current_version: Currently installed version (e.g., "v1.2.3").
        asset_pattern: Optional fnmatch pattern for asset selection.
        include_prerelease: Whether to consider pre-release versions.
    """
    result = ReleaseCheckResult(current_version=current_version or "")

    try:
        if include_prerelease:
            resp = _github_request(f"repos/{repo}/releases")
            releases = resp.json()
            if not releases:
                result.error = "No releases found"
                return result
            release = releases[0]  # Most recent
        else:
            resp = _github_request(f"repos/{repo}/releases/latest")
            release = resp.json()

        result.latest_version = release.get("tag_name", "")
        result.release_url = release.get("html_url", "")
        result.is_prerelease = release.get("prerelease", False)

        # Version comparison
        if current_version:
            cmp = compare_versions(current_version, result.latest_version)
            result.has_update = cmp < 0
        else:
            # No current version known -- always consider it an update
            result.has_update = True

        # Find matching asset
        assets = release.get("assets", [])
        os_names, arch_names, rust_triple = get_platform_identifiers()

        matched = match_asset(assets, os_names, arch_names, rust_triple, asset_pattern)
        if matched:
            result.asset_name = matched["name"]
            result.asset_url = matched["browser_download_url"]
            result.asset_size = matched.get("size", 0)

            # Look for checksum
            checksum = find_checksum_asset(assets, matched["name"])
            if checksum:
                result.checksum_url = checksum["browser_download_url"]
        elif result.has_update:
            result.error = f"Update available ({result.latest_version}) but no matching asset for {sys.platform}/{platform_mod.machine()}"
            result.has_update = False  # Can't update without an asset

    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            result.error = f"Repository '{repo}' not found or has no releases"
        elif e.response is not None and e.response.status_code == 403:
            result.error = "GitHub API rate limit exceeded. Set GITHUB_TOKEN for higher limits."
        else:
            result.error = f"GitHub API error: {e}"
    except requests.RequestException as e:
        result.error = f"Network error: {e}"
    except Exception as e:
        result.error = f"Unexpected error: {e}"

    return result


def apply_update(
    binary_path: str,
    repo: str,
    check_result: ReleaseCheckResult,
) -> ReleaseUpdateResult:
    """Download and install a GitHub release update.

    Args:
        binary_path: Path to the currently installed binary.
        repo: GitHub repo in "owner/repo" format.
        check_result: Result from check_for_update().
    """
    result = ReleaseUpdateResult(old_version=check_result.current_version)

    if not check_result.asset_url:
        result.error = "No asset URL available"
        return result

    work_dir = Path(tempfile.mkdtemp(prefix="mcpm-release-"))

    try:
        # Download asset
        asset_path = work_dir / check_result.asset_name
        logger.info(f"Downloading {check_result.asset_name}...")
        download_asset(check_result.asset_url, asset_path)

        # Download and verify checksum (if available)
        if check_result.checksum_url:
            checksum_name = check_result.checksum_url.rsplit("/", 1)[-1]
            checksum_path = work_dir / checksum_name
            download_asset(check_result.checksum_url, checksum_path)

            if not verify_checksum(asset_path, checksum_path, check_result.asset_name):
                result.error = "Checksum verification failed"
                return result

        # Extract
        extract_dir = work_dir / "extracted"
        extract_dir.mkdir()
        extracted = extract_archive(asset_path, extract_dir)

        # Find the binary
        repo_name = repo.split("/")[-1] if "/" in repo else repo
        binary = find_binary_in_extracted(extracted, repo_name)
        if not binary:
            result.error = "Could not find binary in extracted archive"
            return result

        # Install atomically
        target = Path(binary_path)
        install_binary(binary, target)

        result.success = True
        result.new_version = check_result.latest_version
        result.message = f"Updated {check_result.current_version or 'unknown'} -> {check_result.latest_version}"

    except PermissionError as e:
        result.error = str(e)
    except Exception as e:
        result.error = f"Update failed: {e}"
    finally:
        # Clean up work directory
        shutil.rmtree(work_dir, ignore_errors=True)

    return result
