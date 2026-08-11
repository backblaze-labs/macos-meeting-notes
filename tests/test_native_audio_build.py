"""Security and reproducibility checks for the minimal AAC encoder build."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from meeting_memory.repo import native_audio_build, native_audio_source


def test_encoder_configuration_is_offline_and_allowlisted() -> None:
    arguments = native_audio_build._configure_args("arm64")

    assert "--disable-everything" in arguments
    assert "--disable-network" in arguments
    assert "--disable-autodetect" in arguments
    assert "--disable-x86asm" in arguments
    assert "--disable-shared" in arguments
    assert "--enable-static" in arguments
    assert {
        "--enable-protocol=file",
        "--enable-demuxer=wav",
        "--enable-decoder=pcm_s16le",
        "--enable-encoder=aac",
        "--enable-muxer=ipod",
        "--enable-filter=aresample",
        "--enable-filter=aformat",
    }.issubset(arguments)
    assert not any("gpl" in argument or "nonfree" in argument for argument in arguments)


def test_encoder_build_drops_parent_make_state(monkeypatch) -> None:
    for name in native_audio_build.PARENT_MAKE_VARIABLES:
        monkeypatch.setenv(name, "inherited-parent-state")
    monkeypatch.setenv("CFLAGS", "inherited-compiler-flags")
    monkeypatch.setenv("LDFLAGS", "inherited-linker-flags")
    monkeypatch.setenv("MEETING_MEMORY_BUILD_SENTINEL", "preserved")
    build_root = Path("/private/tmp/native-audio-build")

    environment = native_audio_build._isolated_build_environment(build_root)

    assert not native_audio_build.PARENT_MAKE_VARIABLES.intersection(environment)
    assert "inherited-compiler-flags" not in environment["CFLAGS"]
    assert f"-ffile-prefix-map={build_root}=" in environment["CFLAGS"]
    assert f"-fdebug-prefix-map={build_root}=" in environment["CFLAGS"]
    assert "LDFLAGS" not in environment
    assert environment["MEETING_MEMORY_BUILD_SENTINEL"] == "preserved"
    assert environment is not os.environ


def test_encoder_archive_requires_exact_regular_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = tmp_path / "ffmpeg.tar.xz"
    archive.write_bytes(b"verified-source")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(native_audio_source, "FFMPEG_ARCHIVE_SHA256", digest)

    native_audio_source.read_verified_source_archive(archive)

    link = tmp_path / "source-link.tar.xz"
    link.symlink_to(archive)
    with pytest.raises(native_audio_source.NativeAudioSourceError, match="unavailable"):
        native_audio_source.read_verified_source_archive(link)

    archive.write_bytes(b"changed-source")
    with pytest.raises(native_audio_source.NativeAudioSourceError, match="checksum"):
        native_audio_source.read_verified_source_archive(archive)


def test_encoder_source_prefers_the_verified_vendored_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"vendored-source"
    monkeypatch.setattr(
        native_audio_source,
        "FFMPEG_ARCHIVE_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    vendored = (
        tmp_path
        / native_audio_source.VENDORED_SOURCE_DIRECTORY
        / native_audio_source.FFMPEG_SOURCE_ARCHIVE_NAME
    )
    vendored.parent.mkdir(parents=True)
    vendored.write_bytes(payload)
    monkeypatch.setattr(
        native_audio_source,
        "_cached_archive",
        lambda _root: pytest.fail("vendored source must avoid network/cache fallback"),
    )

    assert native_audio_source.verified_source_archive(tmp_path) == payload


def test_encoder_archive_rejects_link_members(tmp_path: Path) -> None:
    archive = tmp_path / "ffmpeg.tar.xz"
    with tarfile.open(archive, "w:xz") as destination:
        member = tarfile.TarInfo("ffmpeg-8.1.2/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../foreign"
        destination.addfile(member)

    with pytest.raises(native_audio_source.NativeAudioSourceError, match="contains links"):
        native_audio_source.extract_source(archive.read_bytes(), tmp_path / "output")


def test_source_offer_matches_the_pinned_archive() -> None:
    root = Path(__file__).resolve().parents[1]
    offer = (root / "packaging" / "FFMPEG_SOURCE_OFFER.md").read_text(encoding="utf-8")
    vendored = (
        root
        / native_audio_source.VENDORED_SOURCE_DIRECTORY
        / native_audio_source.FFMPEG_SOURCE_ARCHIVE_NAME
    )

    assert native_audio_source.FFMPEG_ARCHIVE_URL in offer
    assert native_audio_source.FFMPEG_ARCHIVE_SHA256 in offer
    assert native_audio_source.FFMPEG_VERSION in offer
    assert hashlib.sha256(vendored.read_bytes()).hexdigest() == (
        native_audio_source.FFMPEG_ARCHIVE_SHA256
    )


def test_encoder_build_rejects_non_native_architecture_before_source_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(native_audio_build, "_native_architecture", lambda: "arm64")

    with pytest.raises(native_audio_build.NativeAudioCaptureError, match="native architecture"):
        native_audio_build.build_audio_encoder(
            tmp_path,
            tmp_path / native_audio_build.ENCODER_NAME,
            architecture="x86_64",
        )


def test_encoder_archive_rejects_oversize_without_reading_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = tmp_path / "oversize.tar.xz"
    archive.write_bytes(b"x")
    monkeypatch.setattr(native_audio_source, "MAX_ARCHIVE_BYTES", 0)

    with pytest.raises(native_audio_source.NativeAudioSourceError, match="unavailable"):
        native_audio_source.read_verified_source_archive(archive)


def test_encoder_archive_rejects_traversal_members(tmp_path: Path) -> None:
    archive = tmp_path / "ffmpeg.tar.xz"
    payload = b"source"
    with tarfile.open(archive, "w:xz") as destination:
        for name in ("ffmpeg-8.1.2/configure", "../escape"):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            destination.addfile(member, io.BytesIO(payload))

    with pytest.raises(native_audio_source.NativeAudioSourceError):
        native_audio_source.extract_source(archive.read_bytes(), tmp_path / "output")


def test_encoder_activation_replaces_a_link_without_touching_its_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "verified-encoder"
    source.write_bytes(b"new-encoder")
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"keep-me")
    destination = tmp_path / native_audio_build.ENCODER_NAME
    destination.symlink_to(foreign)

    native_audio_build._replace_file(source, destination, 0o755)

    assert destination.is_file()
    assert not destination.is_symlink()
    assert destination.read_bytes() == b"new-encoder"
    assert destination.stat().st_mode & 0o777 == 0o755
    assert foreign.read_bytes() == b"keep-me"


def test_active_sdk_is_used_with_the_macos_15_deployment_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sdk = tmp_path / "MacOSX.sdk"
    sdk.mkdir()
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        return subprocess.CompletedProcess(command, 0, stdout=f"{sdk}\n")

    monkeypatch.setattr(native_audio_build.subprocess, "run", runner)

    assert native_audio_build._compatible_sdk_path() == sdk
    assert calls == [["xcrun", "--sdk", "macosx", "--show-sdk-path"]]
    assert "--extra-cflags=-mmacosx-version-min=15.0" in native_audio_build._configure_args("arm64")


def test_verified_source_activation_replaces_a_link_without_touching_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = b"exact-source"
    monkeypatch.setattr(
        native_audio_source,
        "FFMPEG_ARCHIVE_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"keep-me")
    destination = tmp_path / native_audio_source.FFMPEG_SOURCE_ARCHIVE_NAME
    destination.symlink_to(foreign)

    native_audio_source.write_verified_source_archive(payload, destination)

    assert not destination.is_symlink()
    assert destination.read_bytes() == payload
    assert foreign.read_bytes() == b"keep-me"
