"""Shared fakes for tray tests."""

from __future__ import annotations


class FakeMenu:
    def __init__(self):
        self.items = []

    def clear(self) -> None:
        self.items.clear()

    def add(self, item) -> None:
        self.items.append(item)


class FakeRumps:
    def __init__(self):
        self.notifications = []
        self.notification_options = []

    class MenuItem:
        def __init__(self, title, callback=None):
            self.title = title
            self.callback = callback

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

        def run(self) -> None:
            pass

    def notification(self, title, subtitle, message, **kwargs) -> None:
        self.notifications.append((title, subtitle, message))
        self.notification_options.append(kwargs)

    def quit_application(self, _sender=None) -> None:
        pass
