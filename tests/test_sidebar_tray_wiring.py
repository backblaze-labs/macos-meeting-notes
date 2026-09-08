"""Tests for SidebarWiring: toggle install, compact content, tick, reveal,
and the hide-while-recording preference."""

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


def test_install_once_is_a_noop_without_a_panel() -> None:
    wiring = SidebarWiring(FakeRumps())
    app = FakeRumps.App(name="Test")
    wiring.install_once(app, FakeRumps())
    assert wiring.toggle is None


def test_install_once_installs_and_is_idempotent() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    app = FakeRumps.App(name="Test")
    rumps_module = FakeRumps()

    wiring.install_once(app, rumps_module)
    assert wiring.toggle is not None
    status_item = app._nsapp.nsstatusitem
    assert status_item.menu is None  # detached by the real install()

    first_toggle = wiring.toggle
    wiring.install_once(app, rumps_module)
    assert wiring.toggle is first_toggle


def test_rebuild_is_a_noop_without_a_panel() -> None:
    wiring = SidebarWiring(FakeRumps())
    wiring.rebuild(idle_view_model())
    assert wiring.panel is None


def test_rebuild_sets_compact_content_with_three_buttons() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)

    wiring.rebuild(idle_view_model())

    assert len(_buttons(wiring.panel.content_view)) == 3


def test_callbacks_are_bound_at_construction() -> None:
    calls: list[str] = []
    wiring = SidebarWiring(
        None,
        on_toggle_recording=lambda: calls.append("record"),
        on_screenshot=lambda: calls.append("shot"),
        on_quit=lambda: calls.append("quit"),
        panel_factory=FakePanel,
    )

    wiring.rebuild(idle_view_model())
    for button in _buttons(wiring.panel.content_view):
        button.mouseUp_(None)

    assert calls == ["record", "shot", "quit"]


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


def test_reveal_hides_instead_when_hide_while_recording_is_on() -> None:
    from meeting_memory.ui.sidebar_prefs import set_hide_while_recording

    wiring = SidebarWiring(None, panel_factory=FakePanel)
    set_hide_while_recording(wiring.panel.appkit, True)

    wiring.reveal()

    assert (wiring.panel.show_calls, wiring.panel.hide_calls) == (0, 1)


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


def test_a_failed_toggle_install_is_retried_a_bounded_number_of_times() -> None:
    from tray_fakes import FakeClickAppKit

    from meeting_memory.ui.sidebar_tray_wiring import MAX_INSTALL_ATTEMPTS

    failing = FakeClickAppKit(raise_on="install_right_click_monitor")
    wiring = SidebarWiring(None, panel_factory=FakePanel, click_appkit=failing)
    app = FakeRumps.App(name="Test")
    status_item = app._nsapp.nsstatusitem

    for _ in range(MAX_INSTALL_ATTEMPTS + 2):
        wiring.install_once(app, FakeRumps())

    # Retried exactly MAX times (each attempt detaches then restores the menu),
    # then parked — and the restored menu is quittable.
    assert len(status_item.set_menu_calls) == 2 * MAX_INSTALL_ATTEMPTS
    assert wiring.toggle is not None and wiring.toggle._installed is False
    assert status_item.menu.items[0][0] == "Quit"


def test_hide_while_recording_keeps_the_panel_hidden_for_the_whole_recording() -> None:
    from meeting_memory.ui.sidebar_prefs import set_hide_while_recording

    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())
    set_hide_while_recording(wiring.panel.appkit, True)
    wiring.panel.show()  # e.g. it was open before the recording started

    wiring.tick(_FakeController(is_recording=True, duration=1))
    assert wiring.panel.is_visible is False

    # Whatever re-shows it mid-recording is undone on the next tick...
    wiring.panel.show()
    wiring.tick(_FakeController(is_recording=True, duration=2))
    assert wiring.panel.is_visible is False

    # ...except the user's own icon click, which is a deliberate peek.
    wiring.toggle_panel()
    wiring.tick(_FakeController(is_recording=True, duration=3))
    assert wiring.panel.is_visible is True

    # The peek does not outlive the recording: the next one hides again.
    wiring.tick(_FakeController(is_recording=False))
    wiring.tick(_FakeController(is_recording=True, duration=1))
    assert wiring.panel.is_visible is False


def test_hide_while_recording_off_leaves_visibility_alone() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())
    wiring.panel.show()

    wiring.tick(_FakeController(is_recording=True, duration=1))

    assert wiring.panel.is_visible is True


def _recording(is_recording: bool, duration: int = 0) -> RecordingView:
    return RecordingView(
        is_recording=is_recording, duration_seconds=duration, audio_warning=False, label="x"
    )
