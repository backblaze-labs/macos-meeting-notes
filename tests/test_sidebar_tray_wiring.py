"""Tests for SidebarWiring: compact content, tick, reveal,
the hide-while-recording preference, and the visibility rules from
docs/features/sidebar.md (auto-show once per recording, user closes win)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from appkit_fakes import reset_fake_appkit_state
from sidebar_view_model_fixtures import RecordingView, idle_view_model
from sidebar_wiring_fakes import FakePanel, _FakeController
from tray_fakes import FakeRumps

from meeting_memory.ui.sidebar_geometry import Orientation, SnapAnchor
from meeting_memory.ui.sidebar_tray_wiring import SidebarWiring


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def _buttons(root):
    return [sub for sub in root.subviews if hasattr(sub, "_mm_image_view")]


def test_no_panel_when_using_a_fake_rumps_module() -> None:
    # A non-None rumps_module means tests/a fake, so nothing sidebar-related
    # should touch real AppKit unless a fake panel is injected explicitly.
    wiring = SidebarWiring(FakeRumps())
    assert wiring.panel is None
    assert wiring.is_visible is False


def test_an_injected_panel_factory_is_used_even_with_a_fake_rumps_module() -> None:
    wiring = SidebarWiring(FakeRumps(), panel_factory=FakePanel)
    assert isinstance(wiring.panel, FakePanel)


def test_rebuild_is_a_noop_without_a_panel() -> None:
    wiring = SidebarWiring(FakeRumps())
    wiring.rebuild(idle_view_model())
    assert wiring.panel is None


def test_rebuild_sets_compact_content_with_four_buttons() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)

    wiring.rebuild(idle_view_model())

    assert len(_buttons(wiring.panel.content_view)) == 4


def test_callbacks_are_bound_at_construction() -> None:
    calls: list[str] = []
    wiring = SidebarWiring(
        None,
        on_toggle_recording=lambda: calls.append("record"),
        on_screenshot=lambda: calls.append("shot"),
        on_hide_sidebar=lambda: calls.append("hide"),
        on_quit=lambda: calls.append("quit"),
        panel_factory=FakePanel,
    )

    wiring.rebuild(idle_view_model())
    for button in _buttons(wiring.panel.content_view):
        button.mouseUp_(None)

    assert calls == ["record", "shot", "hide", "quit"]


def test_tick_updates_the_record_button_in_place_while_recording() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(replace(idle_view_model(), recording=_recording(True, 1)))
    content_before = wiring.panel.content_view

    wiring.tick(_FakeController(is_recording=True, duration=5))

    assert wiring.panel.content_view is content_before
    assert _buttons(content_before)[0].tooltip == "Stop recording · 00:05"


def test_tick_rebuilds_when_the_recording_state_flips() -> None:
    # The timer slot changes the panel size, so a start/stop that reached
    # the recorder without a tray refresh still resizes the panel.
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())
    idle_content = wiring.panel.content_view

    wiring.tick(_FakeController(is_recording=True, duration=2))

    assert wiring.panel.content_view is not idle_content
    assert _buttons(wiring.panel.content_view)[0].tooltip == "Stop recording · 00:02"


def test_tick_is_a_noop_before_the_first_rebuild() -> None:
    wiring = SidebarWiring(FakeRumps())
    wiring.tick(_FakeController())  # should not raise


def test_orientation_change_rebuilds_against_the_last_view_model() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())
    vertical = wiring.panel.content_view

    wiring.panel.drag_to(SnapAnchor.RIGHT, Orientation.VERTICAL)
    assert wiring.panel.content_view is vertical  # same orientation: nothing to do

    wiring.panel.drag_to(SnapAnchor.TOP, Orientation.HORIZONTAL)
    horizontal = wiring.panel.content_view
    assert horizontal is not vertical
    assert horizontal.frame().size.width > horizontal.frame().size.height


def test_reveal_shows_the_panel() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)

    wiring.reveal()

    assert wiring.panel.show_calls == 1
    assert wiring.is_visible is True


def test_hide_while_recording_suppresses_the_auto_show_without_hiding() -> None:
    from meeting_memory.ui.sidebar_prefs import set_hide_while_recording

    wiring = SidebarWiring(None, panel_factory=FakePanel)
    set_hide_while_recording(wiring.panel.appkit, True)

    wiring.reveal()
    assert (wiring.panel.show_calls, wiring.panel.hide_calls) == (0, 0)

    # A panel the user opened before the recording is left alone.
    wiring.panel.show()
    wiring.reveal()
    assert wiring.is_visible is True
    assert wiring.panel.hide_calls == 0


def test_preference_rows_toggle_hide_while_recording_and_notify() -> None:
    from meeting_memory.ui.sidebar_prefs import hide_while_recording

    changes: list[int] = []
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    (row,) = wiring.preference_rows(on_change=lambda: changes.append(1))
    assert row.label == "Hide sidebar while recording"

    row.action()

    assert hide_while_recording(wiring.panel.appkit) is True
    assert changes == [1]
    assert wiring.preference_rows(on_change=lambda: None)[0].label.startswith("✓ ")
    assert SidebarWiring(FakeRumps()).preference_rows(on_change=lambda: None) == ()


def test_reveal_and_toggle_are_noops_without_a_panel() -> None:
    wiring = SidebarWiring(FakeRumps())
    wiring.reveal()
    wiring.toggle_panel()
    assert wiring.panel is None


def test_hide_while_recording_leaves_a_manually_shown_panel_alone() -> None:
    from meeting_memory.ui.sidebar_prefs import set_hide_while_recording

    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())
    set_hide_while_recording(wiring.panel.appkit, True)

    wiring.reveal()  # recording starts: suppressed
    assert wiring.is_visible is False

    wiring.toggle_panel()  # the user opens it anyway
    wiring.tick(_FakeController(is_recording=True, duration=2))
    wiring.tick(_FakeController(is_recording=True, duration=3))
    assert wiring.is_visible is True
    assert wiring.panel.hide_calls == 0


def test_a_panel_closed_during_a_recording_stays_closed_until_the_next_start() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())

    wiring.reveal()  # first recording starts: auto-show
    assert wiring.is_visible is True

    wiring.toggle_panel()  # the user closes it mid-recording
    wiring.tick(_FakeController(is_recording=True, duration=5))
    wiring.panel.drag_to(SnapAnchor.TOP, Orientation.HORIZONTAL)  # rebuilds content
    wiring.tick(_FakeController(is_recording=False))
    assert wiring.is_visible is False
    assert wiring.panel.show_calls == 1

    wiring.reveal()  # the next recording starts
    assert wiring.is_visible is True
    assert wiring.panel.show_calls == 2


def test_the_panel_hides_after_recording_stops() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())

    wiring.reveal()
    wiring.tick(_FakeController(is_recording=True, duration=1))
    wiring.tick(_FakeController(is_recording=False))
    wiring.tick(_FakeController(is_recording=False))

    assert wiring.is_visible is False
    assert wiring.panel.hide_calls == 1


def test_hide_hides_the_panel_on_request() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.panel.show()

    wiring.hide()

    assert wiring.is_visible is False
    assert wiring.panel.hide_calls == 1


def _recording(is_recording: bool, duration: int = 0) -> RecordingView:
    return RecordingView(
        is_recording=is_recording, duration_seconds=duration, audio_warning=False, label="x"
    )
