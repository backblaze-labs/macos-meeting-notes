"""Tests for first-run setup helpers."""

from __future__ import annotations

from pathlib import Path

from meeting_memory.service.setup import ensure_env_file, setup_actions


def test_ensure_env_file_copies_example_when_missing(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("B2_BUCKET_NAME=replace-me\n", encoding="utf-8")

    result = ensure_env_file(tmp_path)

    assert result.changed is True
    assert result.name == "env-file"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "B2_BUCKET_NAME=replace-me\n"


def test_ensure_env_file_leaves_existing_env_alone(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("B2_BUCKET_NAME=real-bucket\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("B2_BUCKET_NAME=replace-me\n", encoding="utf-8")

    result = ensure_env_file(tmp_path)

    assert result.changed is False
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "B2_BUCKET_NAME=real-bucket\n"


def test_setup_actions_include_env_file_step(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("", encoding="utf-8")

    assert [action.name for action in setup_actions(tmp_path)] == ["env-file"]
