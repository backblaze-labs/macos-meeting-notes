"""Reproducible native capture and minimal AAC encoder builds."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from meeting_memory.repo.native_audio_source import (
    FFMPEG_SOURCE_ARCHIVE_NAME,
    FFMPEG_VERSION,
    NativeAudioSourceError,
    extract_source,
    verified_source_archive,
    write_verified_source_archive,
)
from meeting_memory.repo.native_layout import BUILD_DIR_NAME, HELPER_NAME
from meeting_memory.types.runtime_layout import NATIVE_ENCODER_NAME

ENCODER_NAME = NATIVE_ENCODER_NAME
FFMPEG_LICENSE_NAME = "FFMPEG-COPYING.LGPLv2.1"
Runner = Callable[..., subprocess.CompletedProcess]
PARENT_MAKE_VARIABLES = frozenset(
    {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKE_TERMOUT", "MAKE_TERMERR"}
)


class NativeAudioCaptureError(RuntimeError):
    """Raised when the native audio toolchain cannot run or be built."""


def build_native_capture_helper(
    project_dir: Path,
    output_path: Path,
    *,
    runner: Runner = subprocess.run,
    build_encoder: bool = True,
) -> Path:
    """Compile the Swift helper and its sibling minimal AAC encoder."""

    source_dir = project_dir / "src" / "meeting_memory" / "repo" / "native"
    sources = sorted(source_dir.glob("*.swift"))
    if not sources:
        raise NativeAudioCaptureError("Native capture sources are missing.")
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        raise NativeAudioCaptureError("Swift compiler is missing. Install Xcode tools.")
    architecture = _native_architecture()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    module_cache = output_path.parent / "swift-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    command = [
        swiftc,
        "-O",
        "-module-cache-path",
        str(module_cache),
        "-sdk",
        str(_compatible_sdk_path()),
        "-target",
        f"{architecture}-apple-macosx15.0",
    ]
    for framework in ("AVFoundation", "CoreAudio", "CoreMedia", "ScreenCaptureKit"):
        command.extend(["-framework", framework])
    command.extend(str(path) for path in sources)
    command.extend(["-o", str(output_path)])
    _run_build(command, runner=runner, stage="Swift capture helper")
    _require_executable(output_path, "Swift capture helper")
    if build_encoder:
        build_audio_encoder(
            project_dir,
            output_path.with_name(ENCODER_NAME),
            architecture=architecture,
            runner=runner,
        )
    return output_path


def build_audio_encoder(
    project_dir: Path,
    output_path: Path,
    *,
    architecture: str | None = None,
    runner: Runner = subprocess.run,
    archive_path: Path | None = None,
) -> Path:
    """Build a thin static LGPL FFmpeg with only WAV-to-AAC/M4A support."""
    selected_arch = architecture or _native_architecture()
    if selected_arch not in {"arm64", "x86_64"} or selected_arch != _native_architecture():
        raise NativeAudioCaptureError("AAC encoder builds require the native architecture.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        archive_bytes = verified_source_archive(project_dir, archive_path)
    except NativeAudioSourceError:
        raise NativeAudioCaptureError("Verified FFmpeg source is unavailable.") from None
    with tempfile.TemporaryDirectory("meeting-memory-ffmpeg-", dir=output_path.parent) as tmp:
        temporary = Path(tmp)
        source = temporary / f"ffmpeg-{FFMPEG_VERSION}"
        try:
            extract_source(archive_bytes, temporary)
        except NativeAudioSourceError:
            raise NativeAudioCaptureError("Verified FFmpeg source layout is invalid.") from None
        if not (source / "configure").is_file():
            raise NativeAudioCaptureError("Verified FFmpeg source layout is invalid.")
        build = temporary / "build"
        build.mkdir()
        build_environment = _isolated_build_environment(temporary)
        _run_build(
            [str(source / "configure"), *_configure_args(selected_arch)],
            runner=runner,
            stage="AAC encoder configuration",
            cwd=build,
            env=build_environment,
        )
        _run_build(
            ["/usr/bin/make", f"-j{min(os.cpu_count() or 1, 8)}"],
            runner=runner,
            stage="AAC encoder compilation",
            cwd=build,
            env=build_environment,
        )
        candidate = build / "ffmpeg"
        _require_executable(candidate, "AAC encoder")
        _require_architecture(candidate, selected_arch, runner)
        _require_lgpl(candidate, runner)
        _replace_file(candidate, output_path, 0o755)
        _replace_file(
            source / "COPYING.LGPLv2.1",
            output_path.with_name(FFMPEG_LICENSE_NAME),
            0o644,
        )
        try:
            write_verified_source_archive(
                archive_bytes,
                output_path.with_name(FFMPEG_SOURCE_ARCHIVE_NAME),
            )
        except NativeAudioSourceError:
            raise NativeAudioCaptureError("FFmpeg source could not be retained.") from None
    return output_path


def default_build_helper_path(project_dir: Path) -> Path:
    return project_dir / BUILD_DIR_NAME / HELPER_NAME


def _configure_args(architecture: str) -> list[str]:
    return [
        f"--arch={architecture}",
        "--target-os=darwin",
        "--cc=/usr/bin/clang",
        "--disable-everything",
        "--enable-ffmpeg",
        "--disable-ffprobe",
        "--disable-ffplay",
        "--disable-network",
        "--disable-autodetect",
        "--disable-x86asm",
        "--enable-protocol=file",
        "--enable-demuxer=wav",
        "--enable-decoder=pcm_s16le",
        "--enable-encoder=aac",
        "--enable-muxer=ipod",
        "--enable-filter=aresample",
        "--enable-filter=aformat",
        "--enable-small",
        "--enable-static",
        "--disable-shared",
        "--extra-cflags=-mmacosx-version-min=15.0",
        "--extra-ldflags=-mmacosx-version-min=15.0",
    ]


def _run_build(
    command: list[str],
    *,
    runner: Runner,
    stage: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    try:
        runner(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise NativeAudioCaptureError(f"{stage} failed safely.") from None


def _isolated_build_environment(build_root: Path | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for name in PARENT_MAKE_VARIABLES:
        environment.pop(name, None)
    for name in ("CPPFLAGS", "CXXFLAGS", "LDFLAGS", "OBJCFLAGS"):
        environment.pop(name, None)
    if build_root is None:
        environment.pop("CFLAGS", None)
    else:
        stable_root = "/usr/src/meeting-memory-audio"
        environment["CFLAGS"] = " ".join(
            (
                f"-ffile-prefix-map={build_root}={stable_root}",
                f"-fdebug-prefix-map={build_root}={stable_root}",
            )
        )
    return environment


def _require_executable(path: Path, label: str) -> None:
    if not path.is_file():
        raise NativeAudioCaptureError(f"{label} did not produce an executable.")
    path.chmod(0o755)


def _replace_file(source: Path, destination: Path, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _require_architecture(path: Path, architecture: str, runner: Runner) -> None:
    result = runner(
        ["/usr/bin/lipo", "-archs", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    if set(result.stdout.split()) != {architecture}:
        raise NativeAudioCaptureError("AAC encoder architecture does not match.")


def _require_lgpl(path: Path, runner: Runner) -> None:
    result = runner(
        [str(path), "-hide_banner", "-L"],
        check=True,
        capture_output=True,
        text=True,
    )
    if "GNU Lesser General Public" not in result.stdout or "version 2.1" not in result.stdout:
        raise NativeAudioCaptureError("AAC encoder license does not match the allowlist.")


def _native_architecture() -> str:
    return "x86_64" if platform.machine() == "x86_64" else "arm64"


def _compatible_sdk_path() -> Path:
    result = subprocess.run(
        ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
        check=True,
        capture_output=True,
        text=True,
    )
    sdk = Path(result.stdout.strip())
    if not sdk.is_dir():
        raise NativeAudioCaptureError("The active macOS SDK is unavailable.")
    return sdk
