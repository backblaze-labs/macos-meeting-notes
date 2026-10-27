"""Regression coverage for incomplete speaker assignments and failed saves."""

import sys
from dataclasses import replace

import pytest
from speaker_review_fakes import FakeAppKit
from test_speaker_review_ui import FakeActions, FakeRumps, _state

from meeting_memory.ui import speaker_review as review
from meeting_memory.ui.speaker_review_fields import MANUAL_OPTION


def _actions(fake, confirm=None, keep=None, notes=None):
    return review.SpeakerReviewActions(
        fake.load_review,
        confirm or fake.confirm_aliases,
        keep or (lambda path: path / "transcript.md"),
        notes or fake.generate_notes,
    )


def test_missing_unknown_returns_to_form_preserving_names(tmp_path):
    fake = FakeActions(
        replace(
            _state(tmp_path),
            speaker_labels=("Speaker A", "Speaker B", "Unknown"),
            speaker_suggestions={"Speaker A": "Alex", "Speaker B": "Casey"},
        )
    )
    rumps = FakeRumps()
    drafts = []
    responses = iter(
        [
            {"Speaker A": "Alex", "Speaker B": "Casey", "Unknown": "   "},
            {"Speaker A": "Alex", "Speaker B": "Casey", "Unknown": "Unknown"},
        ]
    )

    def prompt(state):
        drafts.append(state)
        return next(responses)

    assert review.open_speaker_review_window(
        tmp_path,
        _actions(fake),
        rumps_module=rumps,
        prompt_aliases=prompt,
    )
    assert len(drafts) == 2
    assert drafts[1].speaker_aliases == {
        "Speaker A": "Alex",
        "Speaker B": "Casey",
        "Unknown": "   ",
    }
    assert drafts[1].speaker_suggestions == {}
    assert len(fake.confirmed) == 1
    assert fake.notes == [tmp_path]
    assert "Unknown" in rumps.alerts[0]["message"]


def test_cancel_after_invalid_assignment_never_saves(tmp_path):
    fake = FakeActions(_state(tmp_path))
    responses = iter([{"Speaker A": "Alex", "Speaker B": ""}, None])
    assert not review.open_speaker_review_window(
        tmp_path,
        _actions(fake),
        rumps_module=FakeRumps(),
        prompt_aliases=lambda state: next(responses),
    )
    assert fake.confirmed == []
    assert fake.notes == []


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_save_returns_to_review_with_draft(tmp_path, cancel):
    fake = FakeActions(_state(tmp_path))
    attempts = []
    drafts = []
    aliases = {"Speaker A": "Manual person", "Speaker B": "Casey"}

    def confirm(path, selected):
        attempts.append(selected)
        if len(attempts) == 1:
            raise OSError("Could not save. Try again.")
        return path / "transcript.md"

    def prompt(state):
        drafts.append(state)
        return None if cancel and len(drafts) == 2 else aliases

    assert review.open_speaker_review_window(
        tmp_path,
        _actions(fake, confirm=confirm),
        rumps_module=FakeRumps(),
        prompt_aliases=prompt,
    ) is (not cancel)
    assert drafts[1].speaker_aliases == aliases
    assert len(attempts) == (1 if cancel else 2)
    assert fake.notes == ([] if cancel else [tmp_path])


def test_keep_labels_save_failure_preserves_native_form_draft(monkeypatch, tmp_path):
    appkit = FakeAppKit(responses=[review.KEEP_LABELS_RESPONSE, 1000])
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    fake = FakeActions(
        replace(
            _state(tmp_path),
            speaker_suggestions={
                "Speaker A": "Alex",
                "Speaker B": "Casey",
            },
        )
    )
    kept = []

    def keep(path):
        kept.append(path)
        raise OSError("Could not save. Try again.")

    assert review.open_speaker_review_window(
        tmp_path,
        _actions(fake, keep=keep),
        rumps_module=FakeRumps(),
    )
    assert kept == [tmp_path]
    assert fake.confirmed == [(tmp_path, {"Speaker A": "Alex", "Speaker B": "Casey"})]
    assert fake.notes == [tmp_path]


def test_native_retry_does_not_restore_cleared_suggestion(monkeypatch, tmp_path):
    appkit = FakeAppKit(responses=[])
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    fake = FakeActions(
        replace(
            _state(tmp_path),
            speaker_suggestions={
                "Speaker A": "Alex",
                "Speaker B": "Casey",
            },
        )
    )
    selected = []

    def modal(alert):
        children = alert.accessory.document_view.children
        popup, manual = children[5:7]
        selected.append(popup.titleOfSelectedItem())
        if len(selected) == 1:
            popup.selectItemWithTitle_(MANUAL_OPTION)
        else:
            manual.setStringValue_("Manual person")
        return 1000

    monkeypatch.setattr(review, "run_modal", modal)
    assert review.open_speaker_review_window(
        tmp_path,
        _actions(fake),
        rumps_module=FakeRumps(),
    )
    assert selected == ["Casey", MANUAL_OPTION]
    assert fake.confirmed == [
        (
            tmp_path,
            {
                "Speaker A": "Alex",
                "Speaker B": "Manual person",
            },
        )
    ]


def test_text_fallback_reopens_with_partial_input(monkeypatch, tmp_path):
    fake = FakeActions(
        replace(
            _state(tmp_path),
            speaker_suggestions={
                "Speaker A": "Alex",
                "Speaker B": "Casey",
            },
        )
    )
    rumps = FakeRumps()
    defaults = []

    class Window:
        def __init__(self, **kwargs):
            defaults.append(kwargs["default_text"])

        def run(self):
            from types import SimpleNamespace

            return SimpleNamespace(
                clicked=True,
                text=(
                    "Speaker A=Alex\nSpeaker B="
                    if len(defaults) == 1
                    else "Speaker A=Alex\nSpeaker B=Unknown"
                ),
            )

    rumps.Window = Window

    def unavailable(*args):
        raise ImportError("AppKit unavailable")

    monkeypatch.setattr(review, "_prompt_aliases_appkit", unavailable)
    monkeypatch.setattr(review, "_load_rumps", lambda: rumps)
    assert review.open_speaker_review_window(
        tmp_path,
        _actions(fake),
        rumps_module=rumps,
    )
    assert defaults == ["Speaker A=Alex\nSpeaker B=Casey", "Speaker A=Alex\nSpeaker B="]
    assert len(fake.confirmed) == 1
    assert fake.notes == [tmp_path]


def test_notes_failure_does_not_repeat_confirmation(tmp_path):
    fake = FakeActions(_state(tmp_path))
    prompted = []
    rumps = FakeRumps()

    def prompt(state):
        prompted.append(state)
        return {"Speaker A": "Alex", "Speaker B": "Casey"}

    def notes(path):
        raise OSError("Notes unavailable")

    assert not review.open_speaker_review_window(
        tmp_path,
        _actions(fake, notes=notes),
        rumps_module=rumps,
        prompt_aliases=prompt,
    )
    assert len(fake.confirmed) == len(prompted) == 1
    assert rumps.alerts[-1]["title"] == "Generate Notes"
