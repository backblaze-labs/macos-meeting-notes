"""Tests for the local notes-prompt editor and storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from meeting_memory.config.defaults import (
    DEFAULT_NOTES_REPORT_TEMPLATE,
    DEFAULT_SUMMARY_PROMPT_TEMPLATE,
    NOTES_REPORT_TEMPLATE_MARKER,
)
from meeting_memory.config.notes_template import parse_notes_prompt_document
from meeting_memory.config.settings import Settings
from meeting_memory.service.summary_prompt import (
    read_summary_prompt,
    summary_prompt_path,
    write_summary_prompt,
)
from meeting_memory.ui.notes_prompt import open_notes_prompt_window


def test_summary_prompt_storage_uses_configured_file(tmp_path: Path) -> None:
    prompt_path = tmp_path / "preferences" / "notes-prompt.md"
    settings = _settings(prompt_path)

    assert summary_prompt_path(settings) == prompt_path
    assert read_summary_prompt(settings) == DEFAULT_SUMMARY_PROMPT_TEMPLATE

    saved_path = write_summary_prompt(settings, "Custom instructions\n{transcript}\n")

    assert saved_path == prompt_path
    assert read_summary_prompt(settings) == (
        "Custom instructions\n{transcript}\n\n"
        f"{NOTES_REPORT_TEMPLATE_MARKER}\n{DEFAULT_NOTES_REPORT_TEMPLATE}"
    )


def test_default_prompt_asset_matches_fallback() -> None:
    assert Path("prompts/summary.md").read_text(encoding="utf-8") == (
        DEFAULT_SUMMARY_PROMPT_TEMPLATE
    )


def test_summary_prompt_storage_rejects_blank_prompt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        write_summary_prompt(_settings(tmp_path / "prompt.md"), "  \n")


def test_summary_prompt_storage_rejects_layout_missing_required_content(
    tmp_path: Path,
) -> None:
    prompt = (
        f"Instructions\n{{transcript}}\n\n{NOTES_REPORT_TEMPLATE_MARKER}\n# Brief\n\n{{summary}}\n"
    )

    with pytest.raises(ValueError, match="missing required placeholders"):
        write_summary_prompt(_settings(tmp_path / "prompt.md"), prompt)


def test_summary_prompt_storage_rejects_unknown_layout_placeholder(
    tmp_path: Path,
) -> None:
    prompt = (
        f"Instructions\n\n{NOTES_REPORT_TEMPLATE_MARKER}\n"
        "{summary}\n{decisions}\n{action_items}\n{transcript}\n"
    )

    with pytest.raises(ValueError, match=r"unsupported placeholders: \{transcript\}"):
        write_summary_prompt(_settings(tmp_path / "prompt.md"), prompt)


def test_legacy_prompt_parses_with_default_local_layout() -> None:
    document = parse_notes_prompt_document("Focus on risks.\n{transcript}")

    assert document.instructions == "Focus on risks.\n{transcript}"
    assert document.report_template == DEFAULT_NOTES_REPORT_TEMPLATE.strip()


def test_notes_prompt_window_saves_editor_value_for_next_generation(tmp_path: Path) -> None:
    prompt_path = tmp_path / "notes-prompt.md"
    settings = _settings(prompt_path)
    rumps = FakeRumps()
    received: list[tuple[str, Path]] = []

    saved = open_notes_prompt_window(
        settings,
        rumps_module=rumps,
        prompt_editor=lambda prompt, path: (
            received.append((prompt, path)) or "Focus on risks.\n{transcript}"
        ),
    )

    assert saved is True
    assert received == [(DEFAULT_SUMMARY_PROMPT_TEMPLATE, prompt_path)]
    saved = prompt_path.read_text(encoding="utf-8")
    assert saved.startswith("Focus on risks.\n{transcript}\n\n")
    assert NOTES_REPORT_TEMPLATE_MARKER in saved
    assert rumps.alerts == [
        (
            "Notes Instructions & Layout Saved",
            f"The next notes generation will use {prompt_path}.",
        )
    ]


def test_notes_prompt_window_does_not_write_when_cancelled(tmp_path: Path) -> None:
    prompt_path = tmp_path / "notes-prompt.md"

    saved = open_notes_prompt_window(
        _settings(prompt_path),
        rumps_module=FakeRumps(),
        prompt_editor=lambda _prompt, _path: None,
    )

    assert saved is False
    assert not prompt_path.exists()


def test_notes_prompt_window_reports_blank_prompt(tmp_path: Path) -> None:
    rumps = FakeRumps()

    saved = open_notes_prompt_window(
        _settings(tmp_path / "notes-prompt.md"),
        rumps_module=rumps,
        prompt_editor=lambda _prompt, _path: "",
    )

    assert saved is False
    assert rumps.alerts == [
        (
            "Notes Instructions & Layout",
            "The Notes instructions and layout cannot be empty.",
        )
    ]


def _settings(prompt_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        b2_application_key_id="key-id",
        b2_application_key="secret",
        b2_endpoint="https://s3.example.com",
        b2_region="us-west-004",
        b2_bucket_name="bucket",
        assemblyai_api_key="assembly-key",
        summary_prompt_file=prompt_path,
    )


class FakeRumps:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []

    def alert(self, *, title: str, message: str) -> None:
        self.alerts.append((title, message))
