"""Shared fakes for tray tests."""

from __future__ import annotations


class FakeMenu:
    def __init__(self):
        self.items = []

    def clear(self) -> None:
        self.items.clear()

    def add(self, item) -> None:
        self.items.append(item)


class FakeButton:
    def __init__(self, raise_on: str | None = None, window: object = "status-item-window"):
        self._raise_on = raise_on
        self._window = window
        self.target = None
        self.action = None

    def setTarget_(self, target) -> None:
        self._maybe_raise("setTarget_")
        self.target = target

    def setAction_(self, action) -> None:
        self._maybe_raise("setAction_")
        self.action = action

    def window(self):
        self._maybe_raise("window")
        return self._window

    def _maybe_raise(self, step: str) -> None:
        if self._raise_on == step:
            raise RuntimeError(f"boom at {step}")


class FakeStatusItem:
    def __init__(self, initial_menu, raise_on: str | None = None):
        self._raise_on = raise_on
        self.menu = initial_menu
        self.title: object = "initial-title"
        self.set_menu_calls: list[object] = []
        self.set_title_calls: list[object] = []
        self.popped_up_menus: list[object] = []
        self._button = FakeButton(raise_on=raise_on)

    def setMenu_(self, menu) -> None:
        self._maybe_raise("setMenu_")
        self.menu = menu
        self.set_menu_calls.append(menu)

    def setTitle_(self, title) -> None:
        self._maybe_raise("setTitle_")
        self.title = title
        self.set_title_calls.append(title)

    def button(self):
        self._maybe_raise("button")
        return self._button

    def popUpMenu_(self, menu) -> None:
        self.popped_up_menus.append(menu)

    def _maybe_raise(self, step: str) -> None:
        if self._raise_on == step:
            raise RuntimeError(f"boom at {step}")


class FakeMainMenuHolder:
    """Mimics the rumps App instance enough for SidebarToggle's menu restore
    path: `rumps_app._nsapp._app["_menu"]._menu`."""

    def __init__(self, menu):
        self._menu = menu


class FakeNSApp:
    def __init__(self, mainmenu, raise_on: str | None = None):
        self.nsstatusitem = FakeStatusItem(initial_menu=mainmenu, raise_on=raise_on)
        self._app = {"_menu": FakeMainMenuHolder(mainmenu)}


class FakeClickAppKit:
    """Fake `sidebar_toggle.ClickAppKit` — no AppKit needed for these tests.

    `right_click()` stands in for the real local event monitor firing, so a
    test can simulate a right-click on the status item without a display.
    """

    def __init__(self, raise_on: str | None = None):
        self._raise_on = raise_on
        self.monitored_button: object = None
        self.menus_shown: list[object] = []
        self.indicator_states: list[bool] = []
        self._right_click_handler = None

    def make_click_target(self, handler):
        return handler  # the fake button never calls it; identity is enough

    def install_right_click_monitor(self, button, handler):
        if self._raise_on == "install_right_click_monitor":
            raise RuntimeError("boom at install_right_click_monitor")
        self.monitored_button = button
        self._right_click_handler = handler
        return "fake-monitor"

    def show_menu(self, status_item, menu) -> None:
        self.menus_shown.append({"status_item": status_item, "menu": menu})

    def ensure_quit_item(self, menu, on_quit) -> None:
        if not menu.items:
            menu.add(("Quit", on_quit))

    def set_recording_indicator(self, button, on) -> None:
        self.indicator_states.append(on)

    def right_click(self) -> None:
        """Simulate the local event monitor seeing a RightMouseDown."""

        if self._right_click_handler is None:
            raise AssertionError("no right-click monitor installed")
        self._right_click_handler()


class FakeRumps:
    def __init__(self):
        self.notifications = []
        self.notification_options = []
        self.alerts = []
        self.alert_response = 1  # rumps: 1 means the default (ok) button

    class MenuItem:
        def __init__(self, title, callback=None):
            self.title = title
            self.callback = callback
            self.items = []

        def add(self, item) -> None:
            self.items.append(item)

    class Timer:
        def __init__(self, callback, interval):
            self.callback = callback
            self.interval = interval

        def start(self) -> None:
            pass

    class App:
        def __init__(self, name, title=None, icon=None, template=None, quit_button="Quit"):
            self.name = name
            self.title = title
            self.icon = icon
            self.template = template
            self.quit_button = quit_button
            self.menu = FakeMenu()
            self._nsapp = FakeNSApp(mainmenu=self.menu)

        def run(self) -> None:
            pass

    def notification(self, title, subtitle, message, **kwargs) -> None:
        self.notifications.append((title, subtitle, message))
        self.notification_options.append(kwargs)

    def alert(self, *, title, message, ok=None, cancel=None) -> int:
        self.alerts.append((title, message))
        return self.alert_response

    def quit_application(self, _sender=None) -> None:
        pass


def submenu_titles(app, title: str) -> list[str]:
    submenu = next(item for item in app.app.menu.items if item and item.title == title)
    return [item.title for item in submenu.items if item is not None]
