"""Runtime/setup parity and zero-startup-I/O tests for configuration UI."""

from __future__ import annotations

from tray_fakes import FakeRumps

from meeting_memory.service.configuration_surface import ConfigurationSurfaceCoordinator
from meeting_memory.types.capabilities import Capability
from meeting_memory.ui import menu
from meeting_memory.ui.setup_tray import RumpsSetupApp


class ExplodingServices:
    def open(self, *_args, **_kwargs):
        raise AssertionError("configuration I/O ran during construction")

    preview = apply = authorize = save = open


class Surface:
    def __init__(self) -> None:
        self.calls = []

    def open_configuration(self, capability):
        self.calls.append(capability)
        return object()

    def preview_migration(self):
        self.calls.append("migration")
        return object()

    def authorize_calendar(self):
        self.calls.append("authorization")
        return object()

    def load_prompt(self):
        raise AssertionError("setup prompt must stay disabled")


def test_coordinator_and_setup_construction_perform_zero_store_or_provider_io() -> None:
    services = ExplodingServices()
    events = []

    ConfigurationSurfaceCoordinator(
        events.append,
        configuration=services,
        migration=services,
        authorization=services,
        prompt_settings=object(),
        prompt_reader=services.open,
        prompt_writer=services.open,
    )
    RumpsSetupApp(
        rumps_module=FakeRumps(),
        configuration_surface=Surface(),
    )

    assert events == []


def test_setup_exposes_same_capabilities_auth_and_import_with_prompt_disabled(
    monkeypatch,
) -> None:
    surface = Surface()
    app = RumpsSetupApp(rumps_module=FakeRumps(), configuration_surface=surface)
    submenu = next(
        item for item in app.app.menu.items if item and item.title == menu.CONFIGURATION_LABEL
    )
    items = {item.title: item for item in submenu.items if item is not None}
    monkeypatch.setattr(
        "meeting_memory.ui.configuration_surface.confirm_calendar_authorization",
        lambda: True,
    )

    for capability in Capability:
        items[f"{capability.label}..."].callback(object())
    items[menu.AUTHORIZE_CALENDAR_LABEL].callback(object())
    items[menu.IMPORT_LEGACY_LABEL].callback(object())

    assert surface.calls == [*Capability, "authorization", "migration"]
    assert menu.NOTES_PROMPT_LABEL in items
    assert items[menu.NOTES_PROMPT_LABEL].callback is None
