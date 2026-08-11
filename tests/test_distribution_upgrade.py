"""Release identity and mutable-state locations remain stable across upgrades."""

from pathlib import Path

from meeting_memory.repo.calendar_client import (
    KEYCHAIN_SERVICE as CALENDAR_KEYCHAIN_SERVICE,
)
from meeting_memory.repo.calendar_client import KEYCHAIN_USERNAME
from meeting_memory.repo.secret_store import KEYCHAIN_SERVICE as APP_KEYCHAIN_SERVICE
from meeting_memory.service.launch_agent import LABEL
from meeting_memory.service.macos_app import BUNDLE_IDENTIFIER, macos_app_plist
from meeting_memory.types.runtime_layout import APP_SUPPORT_DIRECTORY
from scripts.verify_distribution import FORBIDDEN_BASENAMES


def test_distribution_identity_is_upgrade_stable() -> None:
    assert BUNDLE_IDENTIFIER == "com.meeting-memory.app"
    assert LABEL == BUNDLE_IDENTIFIER
    assert macos_app_plist()["CFBundleIdentifier"] == BUNDLE_IDENTIFIER
    assert APP_KEYCHAIN_SERVICE == "meeting-memory.app-secrets.v1"
    assert CALENDAR_KEYCHAIN_SERVICE == "meeting-memory.google-calendar"
    assert KEYCHAIN_USERNAME == "oauth-token"


def test_mutable_state_is_external_to_the_application_bundle() -> None:
    assert APP_SUPPORT_DIRECTORY == Path("Library/Application Support/meeting-memory")
    assert "Contents" not in APP_SUPPORT_DIRECTORY.parts

    forbidden = {
        "preferences.json",
        "recording.m4a",
        "transcript.md",
        "notes.md",
    }
    assert forbidden <= FORBIDDEN_BASENAMES
