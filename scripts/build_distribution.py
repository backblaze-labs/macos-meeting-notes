#!/usr/bin/env python3
"""Build one thin, relocatable Meeting Memory macOS application bundle."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from meeting_memory.repo.native_audio import build_native_capture_helper

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "MeetingMemory.spec"
APP_NAME = "Meeting Memory.app"
HELPER_NAME = "MeetingMemoryCapture"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--arch", choices=("arm64", "x86_64"), required=True)
    result.add_argument(
        "--identity",
        default="-",
        help="codesign identity, or '-' for an ad-hoc validation artifact",
    )
    result.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        app = build_distribution(args.arch, args.identity, args.output_dir)
    except Exception as exc:
        sys.stderr.write(f"Distribution build failed safely: {type(exc).__name__}.\n")
        return 2
    sys.stdout.write(f"Built {app}\n")
    return 0


def build_distribution(
    architecture: str,
    identity: str,
    output_dir: Path,
    *,
    runner=subprocess.run,
) -> Path:
    """Build and sign one native-architecture app without modifying user state."""

    if architecture not in {"arm64", "x86_64"}:
        raise ValueError("unsupported distribution architecture")
    if platform.machine() != architecture:
        raise ValueError("distribution builds require a matching native Python architecture")
    if not identity or "\x00" in identity:
        raise ValueError("invalid signing identity")

    output = output_dir.resolve() / architecture
    work = ROOT / "build" / "distribution" / architecture
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    helper = build_native_capture_helper(ROOT, work / HELPER_NAME, runner=runner)
    _require_architecture(helper, architecture, runner)

    environment = os.environ.copy()
    environment.update(
        {
            "MEETING_MEMORY_TARGET_ARCH": architecture,
            "MEETING_MEMORY_CODESIGN_IDENTITY": "" if identity == "-" else identity,
            "PYINSTALLER_CONFIG_DIR": str(work / "pyinstaller-cache"),
            "PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR": "1",
        }
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(output),
        "--workpath",
        str(work / "pyinstaller"),
        str(SPEC),
    ]
    runner(command, check=True, cwd=ROOT, env=environment)

    app = output / APP_NAME
    if not app.is_dir():
        raise RuntimeError("PyInstaller did not create the application bundle")
    bundled_helper = app / "Contents" / "MacOS" / HELPER_NAME
    shutil.copyfile(helper, bundled_helper)
    bundled_helper.chmod(0o755)
    _sign_after_helper_copy(app, bundled_helper, identity, runner)
    _require_architecture(bundled_helper, architecture, runner)
    runner(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    return app


def _sign_after_helper_copy(
    app: Path,
    helper: Path,
    identity: str,
    runner,
) -> None:
    signing_identity = "-" if identity == "-" else identity
    options = [] if identity == "-" else ["--options", "runtime", "--timestamp"]
    for target in (helper, app):
        runner(
            [
                "/usr/bin/codesign",
                "--force",
                "--sign",
                signing_identity,
                *options,
                str(target),
            ],
            check=True,
        )


def _require_architecture(path: Path, architecture: str, runner) -> None:
    result = runner(
        ["/usr/bin/lipo", "-archs", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    if set(result.stdout.split()) != {architecture}:
        raise RuntimeError("built binary architecture does not match the requested artifact")


if __name__ == "__main__":
    raise SystemExit(main())
