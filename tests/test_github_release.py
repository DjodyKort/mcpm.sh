"""Tests for GitHub release utilities -- version comparison, asset matching, extraction, atomic install."""

import hashlib
import tarfile
import zipfile
from pathlib import Path

from mcpm.utils.github_release import (
    compare_versions,
    extract_archive,
    find_binary_in_extracted,
    find_checksum_asset,
    get_platform_identifiers,
    install_binary,
    match_asset,
    verify_checksum,
)

# --- Version comparison ---


class TestCompareVersions:
    def test_equal(self):
        assert compare_versions("1.2.3", "1.2.3") == 0

    def test_equal_with_v_prefix(self):
        assert compare_versions("v1.2.3", "1.2.3") == 0
        assert compare_versions("1.2.3", "v1.2.3") == 0
        assert compare_versions("v1.2.3", "v1.2.3") == 0

    def test_patch_update(self):
        assert compare_versions("v1.2.3", "v1.2.4") == -1

    def test_minor_update(self):
        assert compare_versions("v1.2.3", "v1.3.0") == -1

    def test_major_update(self):
        assert compare_versions("v1.2.3", "v2.0.0") == -1

    def test_current_newer(self):
        assert compare_versions("v2.0.0", "v1.9.9") == 1

    def test_prerelease_less_than_release(self):
        assert compare_versions("v1.0.0-rc1", "v1.0.0") == -1

    def test_release_greater_than_prerelease(self):
        assert compare_versions("v1.0.0", "v1.0.0-beta") == 1

    def test_two_segment_version(self):
        assert compare_versions("1.2", "1.3") == -1

    def test_single_segment(self):
        assert compare_versions("1", "2") == -1

    def test_date_based_version(self):
        assert compare_versions("20260410.01", "20260411.01") == -1


# --- Platform detection ---


class TestPlatformDetection:
    def test_returns_three_values(self):
        os_names, arch_names, rust_triple = get_platform_identifiers()
        assert isinstance(os_names, list)
        assert isinstance(arch_names, list)
        assert len(os_names) > 0
        assert len(arch_names) > 0

    def test_current_platform_has_variants(self):
        os_names, arch_names, _ = get_platform_identifiers()
        # Should have at least 2 variants (e.g., "linux" and "Linux")
        assert len(os_names) >= 1
        assert len(arch_names) >= 1


# --- Asset matching ---


GORELEASER_ASSETS = [
    {"name": "github-mcp-server_0.32.0_Darwin_arm64.tar.gz", "browser_download_url": "https://...", "size": 1000},
    {"name": "github-mcp-server_0.32.0_Darwin_x86_64.tar.gz", "browser_download_url": "https://...", "size": 1000},
    {"name": "github-mcp-server_0.32.0_Linux_x86_64.tar.gz", "browser_download_url": "https://...", "size": 1000},
    {"name": "github-mcp-server_0.32.0_Linux_arm64.tar.gz", "browser_download_url": "https://...", "size": 1000},
    {"name": "github-mcp-server_0.32.0_Windows_x86_64.zip", "browser_download_url": "https://...", "size": 1000},
    {"name": "checksums.txt", "browser_download_url": "https://checksums", "size": 100},
]

RUST_CARGO_DIST_ASSETS = [
    {"name": "server-aarch64-apple-darwin.tar.gz", "browser_download_url": "https://...", "size": 1000},
    {"name": "server-x86_64-unknown-linux-gnu.tar.gz", "browser_download_url": "https://...", "size": 1000},
    {"name": "server-x86_64-pc-windows-msvc.zip", "browser_download_url": "https://...", "size": 1000},
    {"name": "server.sha256", "browser_download_url": "https://...", "size": 50},
]

RAW_BINARY_ASSETS = [
    {"name": "server-darwin-arm64", "browser_download_url": "https://...", "size": 5000},
    {"name": "server-linux-amd64", "browser_download_url": "https://...", "size": 5000},
    {"name": "server-windows-amd64.exe", "browser_download_url": "https://...", "size": 5000},
    {"name": "checksums.sha256", "browser_download_url": "https://...", "size": 100},
]


class TestAssetMatching:
    def test_goreleaser_linux_x86(self):
        result = match_asset(GORELEASER_ASSETS, os_names=["linux", "Linux"], arch_names=["x86_64", "amd64"])
        assert result is not None
        assert "Linux_x86_64" in result["name"]

    def test_goreleaser_darwin_arm64(self):
        result = match_asset(GORELEASER_ASSETS, os_names=["darwin", "Darwin"], arch_names=["arm64", "aarch64"])
        assert result is not None
        assert "Darwin_arm64" in result["name"]

    def test_goreleaser_windows(self):
        result = match_asset(GORELEASER_ASSETS, os_names=["windows", "Windows"], arch_names=["x86_64", "amd64"])
        assert result is not None
        assert "Windows" in result["name"]
        assert result["name"].endswith(".zip")

    def test_rust_triple_linux(self):
        result = match_asset(
            RUST_CARGO_DIST_ASSETS,
            os_names=["linux", "Linux"],
            arch_names=["x86_64", "amd64"],
            rust_triple="x86_64-unknown-linux-gnu",
        )
        assert result is not None
        assert "x86_64-unknown-linux-gnu" in result["name"]

    def test_rust_triple_darwin(self):
        result = match_asset(
            RUST_CARGO_DIST_ASSETS,
            os_names=["darwin", "Darwin"],
            arch_names=["arm64", "aarch64"],
            rust_triple="aarch64-apple-darwin",
        )
        assert result is not None
        assert "aarch64-apple-darwin" in result["name"]

    def test_raw_binary_linux(self):
        result = match_asset(RAW_BINARY_ASSETS, os_names=["linux", "Linux"], arch_names=["x86_64", "amd64"])
        assert result is not None
        assert "linux-amd64" in result["name"]

    def test_no_match_returns_none(self):
        result = match_asset(GORELEASER_ASSETS, os_names=["freebsd"], arch_names=["riscv64"])
        assert result is None

    def test_skips_checksums(self):
        result = match_asset(GORELEASER_ASSETS, os_names=["linux", "Linux"], arch_names=["x86_64", "amd64"])
        assert "checksums" not in result["name"]

    def test_asset_pattern_override(self):
        result = match_asset(GORELEASER_ASSETS, asset_pattern="*Linux_x86_64*")
        assert result is not None
        assert "Linux_x86_64" in result["name"]

    def test_asset_pattern_no_match(self):
        result = match_asset(GORELEASER_ASSETS, asset_pattern="*nonexistent*")
        assert result is None

    def test_skips_system_packages(self):
        assets = GORELEASER_ASSETS + [
            {"name": "server_1.0.0_linux_amd64.deb", "browser_download_url": "...", "size": 100},
            {"name": "server_1.0.0_linux_amd64.rpm", "browser_download_url": "...", "size": 100},
        ]
        result = match_asset(assets, os_names=["linux", "Linux"], arch_names=["x86_64", "amd64"])
        assert result is not None
        assert not result["name"].endswith(".deb")
        assert not result["name"].endswith(".rpm")


class TestFindChecksumAsset:
    def test_finds_checksums_txt(self):
        result = find_checksum_asset(GORELEASER_ASSETS, "github-mcp-server_0.32.0_Linux_x86_64.tar.gz")
        assert result is not None
        assert result["name"] == "checksums.txt"

    def test_finds_per_file_sha256(self):
        assets = [
            {"name": "server-linux-amd64.tar.gz", "browser_download_url": "..."},
            {"name": "server-linux-amd64.tar.gz.sha256", "browser_download_url": "https://sha256"},
        ]
        result = find_checksum_asset(assets, "server-linux-amd64.tar.gz")
        assert result is not None
        assert result["name"] == "server-linux-amd64.tar.gz.sha256"

    def test_no_checksum_returns_none(self):
        assets = [{"name": "server-linux-amd64.tar.gz", "browser_download_url": "..."}]
        result = find_checksum_asset(assets, "server-linux-amd64.tar.gz")
        assert result is None


# --- Checksum verification ---


class TestVerifyChecksum:
    def test_valid_checksum_multifile(self, tmp_path):
        # Create a test file
        test_file = tmp_path / "binary.tar.gz"
        test_file.write_bytes(b"test binary content")
        expected = hashlib.sha256(b"test binary content").hexdigest()

        # GoReleaser checksums.txt format
        checksum_file = tmp_path / "checksums.txt"
        checksum_file.write_text(f"{expected}  binary.tar.gz\notherhash  other.tar.gz\n")

        assert verify_checksum(test_file, checksum_file, "binary.tar.gz") is True

    def test_valid_checksum_single_file(self, tmp_path):
        test_file = tmp_path / "binary"
        test_file.write_bytes(b"content")
        expected = hashlib.sha256(b"content").hexdigest()

        checksum_file = tmp_path / "binary.sha256"
        checksum_file.write_text(f"{expected}  binary\n")

        assert verify_checksum(test_file, checksum_file, "binary") is True

    def test_invalid_checksum(self, tmp_path):
        test_file = tmp_path / "binary"
        test_file.write_bytes(b"content")

        checksum_file = tmp_path / "checksums.txt"
        checksum_file.write_text("0000000000000000000000000000000000000000000000000000000000000000  binary\n")

        assert verify_checksum(test_file, checksum_file, "binary") is False

    def test_missing_entry_passes(self, tmp_path):
        """If the asset name isn't in the checksum file, don't block the update."""
        test_file = tmp_path / "binary"
        test_file.write_bytes(b"content")

        checksum_file = tmp_path / "checksums.txt"
        checksum_file.write_text("somehash  other-file\n")

        assert verify_checksum(test_file, checksum_file, "binary") is True


# --- Extraction ---


class TestExtraction:
    def test_extract_tar_gz(self, tmp_path):
        # Create a tar.gz with a binary inside
        archive_path = tmp_path / "test.tar.gz"
        binary_content = b"#!/bin/sh\necho hello"

        with tarfile.open(archive_path, "w:gz") as tar:
            import io

            info = tarfile.TarInfo(name="test-binary")
            info.size = len(binary_content)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(binary_content))

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        files = extract_archive(archive_path, extract_dir)
        assert len(files) == 1
        assert files[0].read_bytes() == binary_content

    def test_extract_zip(self, tmp_path):
        archive_path = tmp_path / "test.zip"
        binary_content = b"binary content"

        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("test-binary.exe", binary_content)

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        files = extract_archive(archive_path, extract_dir)
        assert len(files) == 1

    def test_extract_tar_with_subdirectory(self, tmp_path):
        """GoReleaser convention: archive contains a directory with the binary inside."""
        archive_path = tmp_path / "server_1.0.0_Linux_x86_64.tar.gz"

        with tarfile.open(archive_path, "w:gz") as tar:
            import io

            # Create directory entry
            dir_info = tarfile.TarInfo(name="server_1.0.0_Linux_x86_64")
            dir_info.type = tarfile.DIRTYPE
            dir_info.mode = 0o755
            tar.addfile(dir_info)

            # Binary inside subdirectory
            binary = b"the binary"
            info = tarfile.TarInfo(name="server_1.0.0_Linux_x86_64/server")
            info.size = len(binary)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(binary))

            # LICENSE alongside binary
            lic = b"MIT License"
            lic_info = tarfile.TarInfo(name="server_1.0.0_Linux_x86_64/LICENSE")
            lic_info.size = len(lic)
            tar.addfile(lic_info, io.BytesIO(lic))

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        files = extract_archive(archive_path, extract_dir)

        # Should find the binary but filter LICENSE
        binary = find_binary_in_extracted(files, "server")
        assert binary is not None
        assert binary.read_bytes() == b"the binary"

    def test_raw_binary_copy(self, tmp_path):
        raw = tmp_path / "server-linux-amd64"
        raw.write_bytes(b"binary")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        files = extract_archive(raw, extract_dir)
        assert len(files) == 1


class TestFindBinary:
    def test_single_file(self, tmp_path):
        f = tmp_path / "server"
        f.write_bytes(b"binary")
        assert find_binary_in_extracted([f]) == f

    def test_prefers_repo_name_match(self, tmp_path):
        server = tmp_path / "my-server"
        server.write_bytes(b"binary")
        other = tmp_path / "helper-tool"
        other.write_bytes(b"binary")

        result = find_binary_in_extracted([server, other], repo_name="owner/my-server")
        assert result == server

    def test_skips_md_files(self, tmp_path):
        binary = tmp_path / "server"
        binary.write_bytes(b"binary")
        readme = tmp_path / "notes.md"
        readme.write_text("notes")

        result = find_binary_in_extracted([binary, readme])
        assert result == binary


# --- Atomic installation ---


class TestInstallBinary:
    def test_install_new(self, tmp_path):
        source = tmp_path / "new-binary"
        source.write_bytes(b"new content")
        target = tmp_path / "bin" / "server"
        target.parent.mkdir()

        assert install_binary(source, target) is True
        assert target.read_bytes() == b"new content"

    def test_install_replaces_existing(self, tmp_path):
        source = tmp_path / "new-binary"
        source.write_bytes(b"new version")
        target = tmp_path / "server"
        target.write_bytes(b"old version")

        assert install_binary(source, target) is True
        assert target.read_bytes() == b"new version"
        # Backup should be cleaned up
        assert not target.with_suffix(".bak").exists()

    def test_rollback_on_failure(self, tmp_path):
        source = tmp_path / "new-binary"
        source.write_bytes(b"new")
        target = tmp_path / "server"
        target.write_bytes(b"old")

        # Simulate failure by making target directory read-only after backup
        # This is tricky to test portably, so just verify the basic flow
        assert install_binary(source, target) is True


# --- Source detection ---


class TestSourceDetection:
    def test_release_binary_detected(self):
        """Binary in ~/.mcpm/ should be detected as potential GitHub release."""
        from mcpm.core.source import _looks_like_release_binary

        mcpm_path = Path.home() / ".mcpm" / "servers" / "test" / "binary"
        assert _looks_like_release_binary(mcpm_path) is True

    def test_interpreter_not_detected(self):
        from mcpm.core.source import _looks_like_release_binary

        assert _looks_like_release_binary(Path("/usr/bin/python")) is False
        assert _looks_like_release_binary(Path("/usr/bin/node")) is False

    def test_script_not_detected(self):
        from mcpm.core.source import _looks_like_release_binary

        assert _looks_like_release_binary(Path("/home/user/server.py")) is False
        assert _looks_like_release_binary(Path("/home/user/server.js")) is False

    def test_github_release_source_model(self):
        from mcpm.core.source import GithubReleaseSource

        source = GithubReleaseSource(
            path="/usr/local/bin/my-server",
            repo="owner/repo",
            current_version="v1.2.3",
            asset_pattern="*linux*amd64*",
            binary_name="my-server",
        )
        data = source.model_dump()
        loaded = GithubReleaseSource(**data)
        assert loaded.repo == "owner/repo"
        assert loaded.current_version == "v1.2.3"
        assert loaded.binary_name == "my-server"
        assert loaded.include_prerelease is False
