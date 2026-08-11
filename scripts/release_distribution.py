#!/usr/bin/env python3
"""Notarize and archive one already signed Meeting Memory application."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.version import APP_VERSION

if __package__:
    from scripts.verify_distribution import verify_distribution
else:
    from verify_distribution import verify_distribution

APP_NAME = "Meeting Memory.app"


@dataclass(frozen=True, slots=True)
class ReleaseArtifacts:
    """Final public artifact paths, never signing or notarization material."""

    archive: Path
    checksum: Path


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--app", type=Path, required=True)
    result.add_argument("--arch", choices=("arm64", "x86_64"), required=True)
    result.add_argument("--notary-key", type=Path, required=True)
    result.add_argument("--notary-key-id", required=True)
    result.add_argument("--notary-issuer", required=True)
    result.add_argument("--team-id", required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        artifacts = create_release(
            args.app,
            args.arch,
            args.notary_key,
            args.notary_key_id,
            args.notary_issuer,
            args.team_id,
            args.output_dir,
        )
    except Exception as exc:
        sys.stderr.write(f"Release packaging failed safely: {type(exc).__name__}.\n")
        return 2
    sys.stdout.write(f"Created {artifacts.archive.name} and SHA-256 checksum.\n")
    return 0


def create_release(
    app: Path,
    architecture: str,
    notary_key: Path,
    notary_key_id: str,
    notary_issuer: str,
    team_id: str,
    output_dir: Path,
    *,
    runner=subprocess.run,
) -> ReleaseArtifacts:
    """Verify, notarize, staple, reverify, and archive one thin app."""

    if architecture not in {"arm64", "x86_64"}:
        raise ValueError("unsupported release architecture")
    app = app.resolve(strict=True)
    key = notary_key.resolve(strict=True)
    if app.name != APP_NAME or not app.is_dir() or not key.is_file():
        raise ValueError("invalid release input")
    for value in (notary_key_id, notary_issuer, team_id):
        if not value.strip() or "\x00" in value:
            raise ValueError("invalid notarization identity")

    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    base_name = f"Meeting-Memory-{APP_VERSION}-{architecture}"
    final_archive = destination / f"{base_name}.zip"
    checksum = destination / f"{base_name}.sha256"
    final_archive.unlink(missing_ok=True)
    checksum.unlink(missing_ok=True)

    verify_distribution(app, architecture, "developer-id", team_id=team_id, runner=runner)
    with tempfile.TemporaryDirectory(prefix="meeting-memory-notary-") as temporary:
        submission = Path(temporary) / f"{base_name}-submission.zip"
        _archive(app, submission, runner)
        result = runner(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(submission),
                "--key",
                str(key),
                "--key-id",
                notary_key_id,
                "--issuer",
                notary_issuer,
                "--wait",
                "--timeout",
                "30m",
                "--output-format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2_100,
        )
        response = json.loads(result.stdout)
        job_id = response.get("id") if isinstance(response, dict) else None
        if (
            not isinstance(response, dict)
            or response.get("status") != "Accepted"
            or not isinstance(job_id, str)
            or not job_id
        ):
            raise RuntimeError("notarization was not accepted")
        log_result = runner(
            [
                "xcrun",
                "notarytool",
                "log",
                job_id,
                "--key",
                str(key),
                "--key-id",
                notary_key_id,
                "--issuer",
                notary_issuer,
                "--output-format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        log = json.loads(log_result.stdout)
        if (
            not isinstance(log, dict)
            or log.get("status") != "Accepted"
            or log.get("issues") not in (None, [])
        ):
            raise RuntimeError("notarization log did not pass verification")

    runner(["xcrun", "stapler", "staple", str(app)], check=True, timeout=120)
    verify_distribution(
        app,
        architecture,
        "developer-id",
        notarized=True,
        team_id=team_id,
        runner=runner,
    )
    _archive(app, final_archive, runner)
    digest = _sha256(final_archive)
    checksum.write_text(f"{digest}  {final_archive.name}\n", encoding="ascii")
    return ReleaseArtifacts(final_archive, checksum)


def _archive(app: Path, destination: Path, runner) -> None:
    runner(
        [
            "/usr/bin/ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(app),
            str(destination),
        ],
        check=True,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
