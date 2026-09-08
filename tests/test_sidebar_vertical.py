"""Tests for the vertical layout assembler, against real `SidebarViewModel`
fixtures (see sidebar_view_model_fixtures.py)."""

from __future__ import annotations

import pytest
from appkit_fakes import FakeAppKit, reset_fake_appkit_state
from sidebar_view_model_fixtures import RecordingView, RowView, SectionView, idle_view_model

from meeting_memory.ui.sidebar_sections import SectionState
from meeting_memory.ui.sidebar_theme import accent_color
from meeting_memory.ui.sidebar_vertical import build_vertical


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def _labels(view) -> list[str]:
    labels = []
    for sub in getattr(view, "subviews", ()):
        if hasattr(sub, "text"):
            labels.append(sub.text)
        else:
            labels.extend(_labels(sub))
    return labels


def _all_containers(view):
    yield view
    for sub in getattr(view, "subviews", ()):
        yield from _all_containers(sub)


def _label_text(container) -> str | None:
    subviews = getattr(container, "subviews", None)
    if not subviews:
        return None
    return getattr(subviews[0], "text", None)


def _build(appkit, view_model, section_state, **overrides):
    kwargs = {
        "on_toggle_recording": lambda: None,
        "on_quit": lambda: None,
        "on_rebuild": lambda: None,
        **overrides,
    }
    return build_vertical(appkit, view_model, section_state, **kwargs)


def test_full_view_model_renders_expected_rows_in_order():
    appkit = FakeAppKit()
    view_model = idle_view_model()
    section_state = SectionState(appkit)

    content, recording_view = _build(appkit, view_model, section_state)

    labels = _labels(content)
    assert labels == [
        "Meeting Memory",
        "▶ Start Recording",
        "Audio Mode",
        "✓ Full Meeting",
        "Silent System Only",
        "▾ Recent Meetings",
        "2026-09-05 14:00 · Standup",
        "Open Meetings Folder",
        "▾ Pending Meeting Tasks (0)",
        "▸ Configuration",
        "▸ Diagnostics",
        "Quit",
    ]
    assert recording_view is not None


def test_disabled_rows_carry_no_action_and_keep_tooltip():
    appkit = FakeAppKit()
    view_model = idle_view_model()
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state)

    # readiness row lives inside the collapsed Diagnostics section by
    # default, so expand it to reach it.
    section_state.toggle("diagnostics")
    content, _ = _build(appkit, view_model, section_state)
    readiness_container = next(
        sub for sub in _all_containers(content) if _label_text(sub) == "Calendar: connected"
    )
    assert readiness_container.tooltip == "Google Calendar linked"
    assert not hasattr(readiness_container, "mouseUp_")


def test_every_view_model_row_has_a_non_empty_tooltip():
    # `quit` is excluded here: its raw view-model tooltip is None by design
    # (see sidebar_view_model.py) — sidebar_vertical.py fills one in at
    # render time, covered by test_quit_row_gets_a_fallback_tooltip below.
    view_model = idle_view_model()
    all_rows = (
        *view_model.audio_modes,
        *view_model.recent.rows,
        *view_model.readiness,
        *view_model.configuration,
        *view_model.diagnostics,
        view_model.open_meetings_folder,
    )
    assert all(r.tooltip for r in all_rows)


def test_quit_row_gets_a_fallback_tooltip():
    appkit = FakeAppKit()
    view_model = idle_view_model()
    assert view_model.quit.tooltip is None
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state)

    quit_row = next(sub for sub in _all_containers(content) if _label_text(sub) == "Quit")
    assert quit_row.tooltip


def test_empty_recent_renders_empty_label_and_nothing_clickable():
    appkit = FakeAppKit()
    view_model = idle_view_model()
    view_model = _replace(
        view_model, recent=SectionView("Recent Meetings", rows=(), empty_label="No meetings yet")
    )
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state)

    labels = _labels(content)
    assert "No meetings yet" in labels
    empty_row = next(
        sub for sub in _all_containers(content) if _label_text(sub) == "No meetings yet"
    )
    assert not hasattr(empty_row, "mouseUp_")


def test_empty_recovered_renders_no_header_at_all():
    appkit = FakeAppKit()
    view_model = idle_view_model()  # recovered.rows == () already
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state)

    assert "Interrupted Recordings" not in _labels(content)


def test_pending_with_zero_tasks_still_renders_header():
    appkit = FakeAppKit()
    view_model = idle_view_model()
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state)

    assert "▾ Pending Meeting Tasks (0)" in _labels(content)


def test_audio_warning_row_added_and_removed():
    appkit = FakeAppKit()
    base = idle_view_model()
    section_state = SectionState(appkit)

    warned = _replace(
        base,
        recording=RecordingView(
            is_recording=True, duration_seconds=5, audio_warning=True, label="⚠︎ ■ Stop · 0:05"
        ),
    )
    content, recording_view = _build(appkit, warned, section_state)
    label = recording_view.subviews[0]
    assert label.text_color == appkit.NSColor.systemOrangeColor()

    recording_view.update(base.recording)
    assert label.text_color == accent_color(appkit)  # idle "Start" reads in the icon teal


def test_recording_row_update_does_not_rebuild_section_containers():
    appkit = FakeAppKit()
    view_model = idle_view_model()
    section_state = SectionState(appkit)

    content, recording_view = _build(appkit, view_model, section_state)
    section_containers_before = [sub for sub in content.subviews]

    recording_view.update(
        RecordingView(
            is_recording=True, duration_seconds=5, audio_warning=False, label="■ Stop · 0:05"
        )
    )

    assert [sub for sub in content.subviews] == section_containers_before


def test_section_toggle_invokes_on_rebuild():
    appkit = FakeAppKit()
    view_model = idle_view_model()
    section_state = SectionState(appkit)
    rebuilds = []

    content, _ = _build(appkit, view_model, section_state, on_rebuild=lambda: rebuilds.append(1))
    configuration_header = next(
        sub for sub in _all_containers(content) if _label_text(sub) == "▸ Configuration"
    )

    configuration_header.mouseUp_(None)

    assert rebuilds == [1]
    assert section_state.is_expanded("configuration") is True


def test_clicking_a_row_invokes_its_view_model_action_exactly_once():
    appkit = FakeAppKit()
    calls = []
    view_model = idle_view_model()
    view_model = _replace(
        view_model,
        open_meetings_folder=RowView(
            "Open Meetings Folder", tooltip="Open in Finder", action=lambda: calls.append(1)
        ),
    )
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state)
    folder_row = next(
        sub for sub in _all_containers(content) if _label_text(sub) == "Open Meetings Folder"
    )

    folder_row.mouseUp_(None)

    assert calls == [1]


def test_clicking_quit_invokes_on_quit_exactly_once():
    appkit = FakeAppKit()
    calls = []
    view_model = idle_view_model()
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state, on_quit=lambda: calls.append(1))
    quit_row = next(sub for sub in _all_containers(content) if _label_text(sub) == "Quit")

    quit_row.mouseUp_(None)

    assert calls == [1]


def test_max_height_wraps_content_in_a_scroll_view():
    appkit = FakeAppKit()
    view_model = idle_view_model()
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state, max_height=10.0)

    assert content.document_view is not None


def _replace(view_model, **kwargs):
    from dataclasses import replace

    return replace(view_model, **kwargs)


def test_open_meetings_folder_is_rendered_even_when_recent_is_empty_or_collapsed():
    # Regression: the row used to trail the Recent rows, so it vanished with
    # zero meetings (REQ-F8-01 lists it unconditionally).
    appkit = FakeAppKit()
    view_model = _replace(
        idle_view_model(),
        recent=SectionView("Recent Meetings", rows=(), empty_label="No meetings yet"),
    )
    section_state = SectionState(appkit)

    content, _ = _build(appkit, view_model, section_state)
    assert "Open Meetings Folder" in _labels(content)

    section_state.toggle("recent")  # collapse
    content, _ = _build(appkit, view_model, section_state)
    assert "Open Meetings Folder" in _labels(content)
