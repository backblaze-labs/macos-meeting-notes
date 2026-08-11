#!/usr/bin/env python3
"""Require a release build to run from the exact version tag."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from meeting_memory.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--tag", required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        validate_release_context(args.tag)
    except Exception as exc:
        sys.stderr.write(f"Release context rejected safely: {type(exc).__name__}.\n")
        return 2
    sys.stdout.write(f"Release context matches Meeting Memory {APP_VERSION}.\n")
    return 0


def validate_release_context(tag: str, *, runner=subprocess.run) -> None:
    expected = f"v{APP_VERSION}"
    if tag != expected or "\x00" in tag:
        raise ValueError("release tag does not match the application version")
    result = runner(
        ["git", "tag", "--points-at", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if expected not in set(result.stdout.splitlines()):
        raise RuntimeError("checked-out commit is not the requested release tag")


if __name__ == "__main__":
    raise SystemExit(main())
