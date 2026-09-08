"""Tests for SidebarToggle — see
docs/features/sidebar/completed/03-status-item-toggle.md."""

from __future__ import annotations

import pytest
from tray_fakes import FakeClickAppKit, FakeNSApp, FakeRumps

from meeting_memory.ui.sidebar_toggle import SidebarToggle


class FakeRumpsApp:
    """Stands in for the real `rumps.App` instance SidebarToggle wraps."""

    def __init__(self, raise_on: str | None = None):
        self.mainmenu = FakeRumps.App(name="Test").menu
        self._nsapp = FakeNSApp(mainmenu=self.mainmenu, raise_on=raise_on)


class FakePanel:
    def __init__(self):
        self.toggle_calls = 0

    def toggle(self) -> None:
        self.toggle_calls += 1


def _make_toggle(*, raise_on: str | None = None):
    rumps_app = FakeRumpsApp(raise_on=raise_on)
    panel = FakePanel()
    appkit = FakeClickAppKit(raise_on=raise_on)
    on_quit_calls: list[None] = []
    toggle = SidebarToggle(
        rumps_app, panel, on_quit=lambda: on_quit_calls.append(None), appkit=appkit
    )
    return toggle, rumps_app, panel, appkit, on_quit_calls


def test_install_detaches_menu_and_clears_title() -> None:
    toggle, rumps_app, _panel, _appkit, _on_quit = _make_toggle()
    toggle.install()
    status_item = rumps_app._nsapp.nsstatusitem
    assert status_item.menu is None
    assert status_item.title is None


def test_install_arms_button_target_and_action() -> None:
    toggle, rumps_app, _panel, _appkit, _on_quit = _make_toggle()
    toggle.install()
    button = rumps_app._nsapp.nsstatusitem._button
    # Bound-method attribute access creates a new wrapper object each time,
    # so compare by equality (same function + same instance), not identity.
    assert button.target == toggle._handle_left_click
    assert button.action == "statusItemClicked:"


def test_install_scopes_the_right_click_monitor_to_the_status_item_button() -> None:
    # The monitor must receive the button itself, not a window resolved at
    # install time: the status item's window isn't final during the first
    # timer tick, so a captured window never matches at event time and
    # right-clicks silently do nothing. A monitor that isn't scoped at all
    # would instead hijack right-clicks meant for the sidebar panel.
    toggle, rumps_app, _panel, appkit, _on_quit = _make_toggle()
    toggle.install()
    assert appkit.monitored_button is rumps_app._nsapp.nsstatusitem._button


def test_left_click_toggles_panel_exactly_once() -> None:
    toggle, _rumps_app, panel, _appkit, _on_quit = _make_toggle()
    toggle.install()
    toggle._handle_left_click(sender=None)
    assert panel.toggle_calls == 1


def test_right_click_does_not_toggle_and_shows_only_quit() -> None:
    toggle, rumps_app, panel, appkit, _on_quit = _make_toggle()
    toggle.install()
    appkit.right_click()
    assert panel.toggle_calls == 0
    assert len(appkit.quit_menus_shown) == 1
    assert appkit.quit_menus_shown[0]["status_item"] is rumps_app._nsapp.nsstatusitem


def test_quit_item_invokes_on_quit() -> None:
    toggle, _rumps_app, _panel, appkit, on_quit_calls = _make_toggle()
    toggle.install()
    appkit.right_click()
    appkit.quit_menus_shown[0]["on_quit"]()
    assert on_quit_calls == [None]


@pytest.mark.parametrize(
    "step",
    [
        "setMenu_",
        "setTitle_",
        "button",
        "setTarget_",
        "setAction_",
        "install_right_click_monitor",
    ],
)
def test_install_failure_restores_rumps_menu_and_logs(
    step: str, caplog: pytest.LogCaptureFixture
) -> None:
    toggle, rumps_app, _panel, _appkit, _on_quit = _make_toggle(raise_on=step)
    original_menu = rumps_app.mainmenu

    with caplog.at_level("ERROR"):
        toggle.install()

    assert toggle._installed is False
    status_item = rumps_app._nsapp.nsstatusitem
    assert status_item.menu is original_menu
    # The runtime app builds no menu, so the fallback must carry a Quit.
    assert [title for title, _ in original_menu.items] == ["Quit"]
    assert "Could not install sidebar toggle" in caplog.text


def test_install_is_idempotent() -> None:
    toggle, rumps_app, _panel, _appkit, _on_quit = _make_toggle()
    toggle.install()
    first_button = rumps_app._nsapp.nsstatusitem._button
    toggle.install()
    assert rumps_app._nsapp.nsstatusitem._button is first_button
    assert len(rumps_app._nsapp.nsstatusitem.set_menu_calls) == 1


def test_monitor_is_retained_after_install() -> None:
    # pyobjc will not keep the monitor alive for us; a collected monitor
    # silently stops delivering right-clicks.
    toggle, _rumps_app, _panel, _appkit, _on_quit = _make_toggle()
    toggle.install()
    assert toggle._monitor == "fake-monitor"
