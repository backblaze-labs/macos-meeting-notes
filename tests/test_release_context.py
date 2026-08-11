"""Release tags must match the one canonical application version."""

from __future__ import annotations

import subprocess

import pytest

from meeting_memory.version import APP_VERSION
from scripts.validate_release_context import validate_release_context


def test_release_context_requires_exact_version_tag() -> None:
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=f"v{APP_VERSION}\n")

    validate_release_context(f"v{APP_VERSION}", runner=runner)

    assert calls[0][0] == ["git", "tag", "--points-at", "HEAD"]


@pytest.mark.parametrize("tag", ["main", "v0.0.0", "v0.1.0-rc1", "v0.1.0\x00other"])
def test_release_context_rejects_other_refs_before_git(tag: str) -> None:
    def runner(*_args, **_kwargs):
        raise AssertionError("git must not run for an invalid tag")

    with pytest.raises(ValueError, match="does not match"):
        validate_release_context(tag, runner=runner)


def test_release_context_rejects_version_tag_on_another_commit() -> None:
    def runner(command, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(command, 0, stdout="v9.9.9\n")

    with pytest.raises(RuntimeError, match="not the requested"):
        validate_release_context(f"v{APP_VERSION}", runner=runner)
