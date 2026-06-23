"""Tests for transcript review helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from meeting_memory.ui.transcript_view import open_markdown_in_vscode


def test_open_markdown_in_vscode_uses_visual_studio_code(tmp_path: Path) -> None:
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    transcript = tmp_path / "transcript.md"
    open_markdown_in_vscode(transcript, runner=runner)

    assert calls == [
        (["open", "-a", "Visual Studio Code", str(transcript)], {"check": False})
    ]


def test_open_markdown_in_vscode_falls_back_to_default_opener(tmp_path: Path) -> None:
    calls = []
    returncodes = [1, 0]

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=returncodes.pop(0))

    transcript = tmp_path / "transcript.md"
    open_markdown_in_vscode(transcript, runner=runner)

    assert calls == [
        (["open", "-a", "Visual Studio Code", str(transcript)], {"check": False}),
        (["open", str(transcript)], {"check": False}),
    ]
