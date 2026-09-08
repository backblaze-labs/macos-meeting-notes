"""Fake-AppKit tests for the vertical layout's row/section/separator widgets."""

from __future__ import annotations

import pytest
from appkit_fakes import FakeAppKit, reset_fake_appkit_state
from sidebar_view_model_fixtures import RecordingView, RowView

from meeting_memory.ui.sidebar_widgets import (
    label_row,
    recording_row,
    row,
    section_header,
    separator,
)


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def test_enabled_row_gets_click_target_and_tooltip():
    appkit = FakeAppKit()
    calls = []
    view = RowView("Open Meetings Folder", tooltip="Open in Finder", action=lambda: calls.append(1))

    container = row(appkit, view, y=10.0)

    assert container.tooltip == "Open in Finder"
    container.mouseUp_(None)
    assert calls == [1]


def test_disabled_row_has_no_click_target_but_keeps_tooltip():
    appkit = FakeAppKit()
    view = RowView("Calendar: connected", enabled=False, tooltip="Google Calendar linked")

    container = row(appkit, view, y=10.0)

    assert container.tooltip == "Google Calendar linked"
    assert not hasattr(container, "mouseUp_")
    label = container.subviews[0]
    assert label.text_color == appkit.NSColor.secondaryLabelColor()


def test_recording_row_update_changes_label_without_new_container():
    appkit = FakeAppKit()
    clicks = []
    view = RecordingView(
        is_recording=False, duration_seconds=0, audio_warning=False, label="▶ Start Recording"
    )

    container = recording_row(appkit, view, y=0.0, width=240.0, on_click=lambda: clicks.append(1))
    label = container.subviews[0]
    assert label.text == "▶ Start Recording"

    container.update(
        RecordingView(
            is_recording=True, duration_seconds=754, audio_warning=False, label="■ Stop · 12:34"
        )
    )

    assert label.text == "■ Stop · 12:34"
    assert container.subviews[0] is label

    container.mouseUp_(None)
    assert clicks == [1]


def test_recording_row_audio_warning_colors_without_relying_on_color_alone():
    appkit = FakeAppKit()
    warning_view = RecordingView(
        is_recording=True, duration_seconds=5, audio_warning=True, label="⚠︎ ■ Stop · 0:05"
    )

    container = recording_row(appkit, warning_view, y=0.0, width=240.0, on_click=lambda: None)

    label = container.subviews[0]
    assert label.text_color == appkit.NSColor.systemOrangeColor()
    # The glyph in the label text carries the meaning; color is supplementary.
    assert "⚠︎" in label.text


def test_section_header_shows_expanded_and_collapsed_glyphs():
    appkit = FakeAppKit()
    toggles = []

    expanded = section_header(
        appkit, "Recent Meetings", True, y=0.0, on_toggle=lambda: toggles.append("e")
    )
    collapsed = section_header(
        appkit, "Configuration", False, y=0.0, on_toggle=lambda: toggles.append("c")
    )

    assert expanded.subviews[0].text == "▾ Recent Meetings"
    assert collapsed.subviews[0].text == "▸ Configuration"

    expanded.mouseUp_(None)
    collapsed.mouseUp_(None)
    assert toggles == ["e", "c"]


def test_clickable_rows_reuse_one_view_class_per_appkit_binding():
    # Regression guard: pyobjc registers a real Objective-C class the first
    # time a Python class subclasses NSView. A fresh `class ClickableRow(...)`
    # per row (the original implementation) redefines that same-named class
    # on every call and crashes with `objc.error: ... overriding existing
    # Objective-C class` against real AppKit — the fakes here don't enforce
    # that pyobjc rule, so this must be asserted structurally instead.
    appkit = FakeAppKit()
    calls_a = []
    calls_b = []

    first = row(appkit, RowView("A", action=lambda: calls_a.append(1)), y=0.0)
    second = row(appkit, RowView("B", action=lambda: calls_b.append(1)), y=0.0)

    assert type(first) is type(second)
    first.mouseUp_(None)
    second.mouseUp_(None)
    assert calls_a == [1]
    assert calls_b == [1]


def test_separator_and_label_row_are_non_interactive():
    appkit = FakeAppKit()

    sep = separator(appkit, y=5.0)
    title = label_row(appkit, "Meeting Memory", y=0.0)

    assert not hasattr(sep, "mouseUp_")
    assert not hasattr(title, "mouseUp_")
    assert title.subviews[0].text == "Meeting Memory"


def test_recording_row_update_skips_appkit_when_the_view_is_unchanged():
    from sidebar_view_model_fixtures import RecordingView

    from meeting_memory.ui.sidebar_widgets import recording_row

    appkit = FakeAppKit()
    idle = RecordingView(
        is_recording=False, duration_seconds=0, audio_warning=False, label="▶ Start Recording"
    )
    container = recording_row(appkit, idle, 0.0, 240.0, lambda: None)
    label = container.subviews[0]
    label.text = "sentinel"  # would be overwritten by a real update

    container.update(RecordingView(**idle.__dict__) if hasattr(idle, "__dict__") else idle)

    assert label.text == "sentinel"
