"""Bounded no-follow Notes prompt storage tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from meeting_memory.config.settings import Settings
from meeting_memory.repo import prompt_source
from meeting_memory.service import summary_prompt
from meeting_memory.service.summary_prompt import (
    MAX_SUMMARY_PROMPT_BYTES,
    read_summary_prompt,
    write_summary_prompt,
)


def test_prompt_read_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    path = tmp_path / "prompt.fifo"
    os.mkfifo(path)

    with pytest.raises(OSError):
        read_summary_prompt(_settings(path))


def test_prompt_read_rejects_oversize_and_invalid_utf8(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.md"
    oversized.write_bytes(b"x" * (MAX_SUMMARY_PROMPT_BYTES + 1))
    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff")

    with pytest.raises(OSError):
        read_summary_prompt(_settings(oversized))
    with pytest.raises(UnicodeDecodeError):
        read_summary_prompt(_settings(invalid))


def test_prompt_symlink_is_never_followed_or_replaced(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_bytes(b"private-target-bytes")
    link = tmp_path / "prompt.md"
    link.symlink_to(target)

    with pytest.raises(OSError):
        read_summary_prompt(_settings(link))
    with pytest.raises(OSError):
        write_summary_prompt(_settings(link), "Replacement")

    assert link.is_symlink()
    assert target.read_bytes() == b"private-target-bytes"


def test_prompt_intermediate_symlink_is_never_followed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    prompt = target / "prompt.md"
    prompt.write_text("private-target-bytes", encoding="utf-8")
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(target, target_is_directory=True)
    linked_prompt = linked_parent / "prompt.md"

    with pytest.raises(OSError):
        read_summary_prompt(_settings(linked_prompt))
    with pytest.raises(OSError):
        write_summary_prompt(_settings(linked_prompt), "Replacement")

    assert linked_parent.is_symlink()
    assert prompt.read_text(encoding="utf-8") == "private-target-bytes"


def test_prompt_mutation_during_read_is_rejected(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "prompt.md"
    path.write_text("original", encoding="utf-8")
    original_read = prompt_source.os.read
    mutated = False

    def mutate_after_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        content = original_read(descriptor, size)
        if content and not mutated:
            mutated = True
            path.write_text("changed content", encoding="utf-8")
        return content

    monkeypatch.setattr(prompt_source.os, "read", mutate_after_read)

    with pytest.raises(OSError):
        read_summary_prompt(_settings(path))


def test_prompt_write_is_bounded_and_preserves_previous_on_replace_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "prompt.md"
    path.write_text("previous\n", encoding="utf-8")

    with pytest.raises(ValueError):
        write_summary_prompt(_settings(path), "x" * (MAX_SUMMARY_PROMPT_BYTES + 1))

    def fail_replace(*_args, **_kwargs):
        raise OSError("private-filesystem-sentinel")

    monkeypatch.setattr(summary_prompt, "atomic_replace_text_at", fail_replace)
    with pytest.raises(OSError):
        write_summary_prompt(_settings(path), "new content")
    assert path.read_text(encoding="utf-8") == "previous\n"


def _settings(path: Path) -> Settings:
    return Settings(
        _env_file=None,
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        summary_prompt_file=path,
    )
