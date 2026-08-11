#!/usr/bin/env python3
"""Verify a thin Meeting Memory app without provider or user-state access."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from meeting_memory.repo.native_audio_source import (
    FFMPEG_SOURCE_ARCHIVE_NAME,
    NativeAudioSourceError,
    read_verified_source_archive,
)
from meeting_memory.service.bundle_self_check import BUNDLE_SELF_CHECK_EXIT_CODES
from meeting_memory.service.macos_app import BUNDLE_IDENTIFIER, macos_app_plist
from meeting_memory.types.runtime_layout import NATIVE_ENCODER_NAME
from meeting_memory.version import APP_VERSION, BUNDLE_BUILD

if __package__:
    from scripts.distribution_signature import verify_signature as _verify_signature
else:
    from distribution_signature import verify_signature as _verify_signature

ROOT = Path(__file__).resolve().parents[1]
APP_EXECUTABLE, HELPER_NAME = "Meeting Memory", "MeetingMemoryCapture"
FORBIDDEN_BASENAMES = frozenset(
    ".env .env.example credentials.json token.json "
    "notes.md preferences.json recording.m4a transcript.md".split()
)
FORBIDDEN_PRIVATE_PATTERNS = (
    "client_secret*.json",
    "credentials*.json",
    "token*.json",
)


class DistributionVerificationError(RuntimeError):
    def __init__(self, stage: str) -> None:
        super().__init__(f"distribution verification failed at {stage}")
        self.stage = stage


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--app", type=Path, required=True)
    result.add_argument("--arch", choices=("arm64", "x86_64"), required=True)
    result.add_argument("--signature", choices=("adhoc", "developer-id"), required=True)
    result.add_argument("--team-id")
    result.add_argument("--notarized", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        verify_distribution(args.app, args.arch, args.signature, args.notarized, args.team_id)
    except DistributionVerificationError as exc:
        sys.stderr.write(f"Distribution verification failed safely at {exc.stage}.\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"Distribution verification failed safely: {type(exc).__name__}.\n")
        return 2
    sys.stdout.write("Distribution verification passed.\n")
    return 0


def verify_distribution(
    app: Path,
    architecture: str,
    signature: str,
    notarized: bool = False,
    team_id: str | None = None,
    *,
    runner=subprocess.run,
) -> None:
    app = _run_stage("application", app.resolve, strict=True)
    _run_stage("metadata", _verify_plist, app)
    _run_stage("manifest", _verify_manifest, app)
    macho_files = _run_stage("mach-o-inventory", _macho_files, app, runner)
    if not macho_files:
        raise DistributionVerificationError("mach-o-inventory")
    for binary in macho_files:
        _run_stage("architecture", _verify_architecture, binary, architecture, runner)
        _run_stage("linkage", _verify_linkage, binary, app, runner)
    _run_stage("build-paths", _verify_no_build_paths, app)
    _run_stage(
        "signature",
        _verify_signature,
        app,
        macho_files,
        signature,
        team_id,
        runner,
    )
    _run_stage("relocated-smoke", _verify_smoke, app, runner)
    if notarized:
        _run_stage(
            "staple",
            runner,
            ["xcrun", "stapler", "validate", str(app)],
            check=True,
        )
        _run_stage(
            "gatekeeper",
            runner,
            ["spctl", "--assess", "--type", "execute", "--verbose=4", str(app)],
            check=True,
        )


def _run_stage(stage: str, operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except DistributionVerificationError:
        raise
    except Exception as exc:
        raise DistributionVerificationError(stage) from exc


def _verify_plist(app: Path) -> None:
    plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    expected = macos_app_plist()
    required = {
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": BUNDLE_BUILD,
        "LSMinimumSystemVersion": "15.0",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": expected["NSMicrophoneUsageDescription"],
        "NSScreenCaptureUsageDescription": expected["NSScreenCaptureUsageDescription"],
    }
    if any(plist.get(key) != value for key, value in required.items()):
        raise RuntimeError("bundle metadata does not match the distribution contract")


def _verify_manifest(app: Path) -> None:
    for path in app.rglob("*"):
        private_name = any(path.match(pattern) for pattern in FORBIDDEN_PRIVATE_PATTERNS)
        if path.name in FORBIDDEN_BASENAMES or path.suffix == ".swift" or private_name:
            raise RuntimeError("bundle contains a forbidden source or private configuration file")
        if path.is_symlink() and not path.resolve().is_relative_to(app):
            raise RuntimeError("bundle contains a symlink outside the application")
    executable = app / "Contents/MacOS" / APP_EXECUTABLE
    helper = app / "Contents/MacOS" / HELPER_NAME
    encoder = app / "Contents/MacOS" / NATIVE_ENCODER_NAME
    for path in (executable, helper, encoder):
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError("bundle executable is missing or not executable")
    source = app / "Contents/Resources" / FFMPEG_SOURCE_ARCHIVE_NAME
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("bundled FFmpeg source is unavailable")
    try:
        read_verified_source_archive(source)
    except NativeAudioSourceError:
        raise RuntimeError("bundled FFmpeg source does not match the encoder build") from None


def _macho_files(app: Path, runner) -> tuple[Path, ...]:
    result = []
    for path in app.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        inspected = runner(
            ["/usr/bin/file", "-b", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        if "Mach-O" in inspected.stdout:
            result.append(path)
    return tuple(result)


def _verify_architecture(path: Path, architecture: str, runner) -> None:
    result = runner(
        ["/usr/bin/lipo", "-archs", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    if set(result.stdout.split()) != {architecture}:
        raise RuntimeError("bundle contains a mismatched architecture slice")


def _verify_linkage(path: Path, app: Path, runner) -> None:
    result = runner(
        ["/usr/bin/otool", "-L", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    dependencies = result.stdout.splitlines()[1:]
    forbidden = (str(ROOT), str(Path(sys.prefix)), "/opt/homebrew/", "/usr/local/opt/")
    if any(value in line for value in forbidden for line in dependencies):
        raise RuntimeError("bundle contains a developer-machine library dependency")
    for line in dependencies:
        dependency = line.strip().split(" ", 1)[0]
        if dependency.startswith("/") and not dependency.startswith(("/System/", "/usr/lib/")):
            if not Path(dependency).is_relative_to(app):
                raise RuntimeError("bundle contains an external absolute library dependency")


def _verify_no_build_paths(app: Path) -> None:
    sentinels = _build_path_sentinels()
    for path in app.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as handle:
            tail = b""
            while chunk := handle.read(1_048_576):
                searchable = tail + chunk
                for stage, sentinel in sentinels:
                    if sentinel in searchable:
                        raise DistributionVerificationError(stage)
                overlap = max((len(sentinel) for _stage, sentinel in sentinels), default=1) - 1
                tail = searchable[-overlap:] if overlap else b""


def _build_path_sentinels() -> tuple[tuple[str, bytes], ...]:
    values = [("checkout-path", str(ROOT))]
    if Path(sys.prefix) not in {Path(sys.base_prefix), ROOT}:
        values.append(("python-prefix", str(Path(sys.prefix))))
    return tuple((stage, value.encode()) for stage, value in values if value and value != "/")


def _verify_smoke(app: Path, runner) -> None:
    with tempfile.TemporaryDirectory(prefix="meeting-memory-smoke-") as temporary:
        root = Path(temporary)
        relocated = root / "Relocated Meeting Memory.app"
        _run_stage("relocation-copy", shutil.copytree, app, relocated, symlinks=True)
        executable = relocated / "Contents/MacOS" / APP_EXECUTABLE
        home = root / "home"
        home.mkdir()
        environment = {"HOME": str(home), "PATH": "/usr/bin:/bin", "TMPDIR": str(home / "tmp")}
        (home / "tmp").mkdir()
        version = _run_stage(
            "version-launch",
            runner,
            [str(executable), "--version"],
            cwd=home,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if APP_VERSION not in version.stdout:
            raise DistributionVerificationError("version-result")
        try:
            smoke = runner(
                [str(executable), "bundle-self-check"],
                cwd=home,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            child_stage = next(
                (
                    stage
                    for stage, code in BUNDLE_SELF_CHECK_EXIT_CODES.items()
                    if code == exc.returncode
                ),
                None,
            )
            stage = f"self-check-{child_stage}" if child_stage else "self-check-launch"
            raise DistributionVerificationError(stage) from None
        except Exception:
            raise DistributionVerificationError("self-check-launch") from None
        payload = _run_stage("self-check-result", json.loads, smoke.stdout)
        if payload.get("event") != "bundle-self-check" or payload.get("ready") is not True:
            raise DistributionVerificationError("self-check-result")
        unexpected = [path for path in home.rglob("*") if path != home / "tmp"]
        if unexpected:
            raise DistributionVerificationError("home-writes")


if __name__ == "__main__":
    raise SystemExit(main())
