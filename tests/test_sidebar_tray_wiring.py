"""Tests for SidebarWiring — see
docs/features/sidebar/completed/03-status-item-toggle.md (toggle) and
docs/features/sidebar/completed/05-vertical-content.md (content)."""

from __future__ import annotations

import pytest
from appkit_fakes import reset_fake_appkit_state
from sidebar_view_model_fixtures import idle_view_model
from sidebar_wiring_fakes import (
    FakePanel,
    _all_containers,
    _FakeController,
    _label_text,
)
from tray_fakes import FakeRumps

from meeting_memory.ui.sidebar_tray_wiring import SidebarWiring


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def test_no_panel_when_using_a_fake_rumps_module() -> None:
    # A non-None rumps_module means tests/a fake, so nothing sidebar-related
    # should touch real AppKit unless a fake panel is injected explicitly.
    wiring = SidebarWiring(FakeRumps())
    assert wiring.panel is None


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


def test_rebuild_sets_the_panel_content_view() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)

    wiring.rebuild(idle_view_model())

    assert wiring.panel.content_view is not None


def test_rebuild_reuses_one_section_state_across_calls() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)

    wiring.rebuild(idle_view_model())
    first_section_state = wiring._section_state
    wiring.rebuild(idle_view_model())

    assert wiring._section_state is first_section_state


def test_a_section_toggle_rebuilds_against_the_same_view_model() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    view_model = idle_view_model()

    wiring.rebuild(view_model)
    first_content_view = wiring.panel.content_view
    configuration_header = next(
        sub for sub in _all_containers(first_content_view) if _label_text(sub) == "▸ Configuration"
    )

    configuration_header.mouseUp_(None)

    assert wiring.panel.content_view is not first_content_view


def test_toggle_recording_and_quit_callbacks_are_bound_at_construction() -> None:
    recording_toggles = []
    quits = []
    wiring = SidebarWiring(
        None,
        on_toggle_recording=lambda: recording_toggles.append(1),
        on_quit=lambda: quits.append(1),
        panel_factory=FakePanel,
    )
    view_model = idle_view_model()

    wiring.rebuild(view_model)
    recording_row = next(
        sub
        for sub in _all_containers(wiring.panel.content_view)
        if _label_text(sub) == "▶ Start Recording"
    )
    quit_row = next(
        sub for sub in _all_containers(wiring.panel.content_view) if _label_text(sub) == "Quit"
    )

    recording_row.mouseUp_(None)
    quit_row.mouseUp_(None)

    assert recording_toggles == [1]
    assert quits == [1]


def test_tick_updates_the_recording_row_in_place() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())
    content_before = wiring.panel.content_view

    wiring.tick(_FakeController(is_recording=True, duration=5))

    assert wiring.panel.content_view is content_before
    recording_row = next(
        sub for sub in _all_containers(content_before) if getattr(sub, "update", None) is not None
    )
    assert "0:05" in _label_text(recording_row)


def test_tick_is_a_noop_before_the_first_rebuild() -> None:
    wiring = SidebarWiring(FakeRumps())
    wiring.tick(_FakeController())  # should not raise


def test_reveal_shows_the_panel() -> None:
    wiring = SidebarWiring(None, panel_factory=FakePanel)

    wiring.reveal()

    assert wiring.panel.show_calls == 1


def test_reveal_hides_instead_when_hide_while_recording_is_on() -> None:
    from meeting_memory.ui.sidebar_prefs import set_hide_while_recording

    wiring = SidebarWiring(None, panel_factory=FakePanel)
    set_hide_while_recording(wiring.panel.appkit, True)

    wiring.reveal()

    assert (wiring.panel.show_calls, wiring.panel.hide_calls) == (0, 1)


def test_hide_while_recording_row_lives_in_configuration_and_toggles() -> None:
    from meeting_memory.ui.sidebar_prefs import hide_while_recording

    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())
    wiring._section_state.toggle("configuration")  # expanded so the row renders
    wiring.rebuild(idle_view_model())
    row = next(
        sub
        for sub in _all_containers(wiring.panel.content_view)
        if _label_text(sub) == "Hide sidebar while recording"
    )

    row.mouseUp_(None)

    assert hide_while_recording(wiring.panel.appkit) is True
    assert any(
        _label_text(sub) == "✓ Hide sidebar while recording"
        for sub in _all_containers(wiring.panel.content_view)
    )


def test_reveal_is_a_noop_without_a_panel() -> None:
    wiring = SidebarWiring(FakeRumps())
    wiring.reveal()  # should not raise
    assert wiring.panel is None


def test_section_toggle_does_not_duplicate_the_preference_row() -> None:
    # Regression: rebuild() used to store the augmented snapshot and hand it
    # back to on_rebuild, so every header click appended another copy.
    wiring = SidebarWiring(None, panel_factory=FakePanel)
    wiring.rebuild(idle_view_model())

    for _ in range(3):  # expand, collapse, expand — each goes through on_rebuild
        header = next(
            sub
            for sub in _all_containers(wiring.panel.content_view)
            if (_label_text(sub) or "").endswith("Configuration")
        )
        header.mouseUp_(None)

    labels = [_label_text(sub) for sub in _all_containers(wiring.panel.content_view)]
    assert labels.count("Hide sidebar while recording") == 1


def test_vertical_content_is_capped_by_the_panels_max_content_height() -> None:
    from appkit_widget_fakes import FakeNSScrollView

    class ShortPanel(FakePanel):
        def max_content_height(self) -> float:
            return 100.0

    wiring = SidebarWiring(None, panel_factory=ShortPanel)
    wiring.rebuild(idle_view_model())

    assert isinstance(wiring.panel.content_view, FakeNSScrollView)
    assert wiring.panel.content_view.frame().size.height == 100.0


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
