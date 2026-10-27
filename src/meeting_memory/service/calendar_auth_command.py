"""Explicit Calendar authorization command shared by source and frozen entrypoints."""

import sys


def run_auth() -> int:
    from meeting_memory.repo.calendar_client import GoogleCalendarClient
    from meeting_memory.repo.calendar_oauth import CalendarAuthorizationError
    from meeting_memory.service.configuration_loader import (
        ConfigurationLoadError,
        load_configuration,
    )
    from meeting_memory.types.configuration_resolution import ConfigurationUse

    try:
        loaded = load_configuration(ConfigurationUse.AUTH)
    except ConfigurationLoadError:
        sys.stderr.write("Calendar configuration could not be loaded.\n")
        return 2
    settings = loaded.calendar_auth
    if settings is None:
        sys.stderr.write("Calendar is not configured or is disabled.\n")
        return 2

    try:
        GoogleCalendarClient(
            credentials_file=settings.credentials_file,
            calendar_id=settings.calendar_id,
            known_speakers=settings.known_speakers,
        ).authenticate()
    except CalendarAuthorizationError:
        sys.stderr.write("Google Calendar authorization failed safely.\n")
        sys.stderr.write("Check Calendar setup and try the explicit auth command again.\n")
        return 2

    sys.stderr.write("Google Calendar auth token saved to Keychain.\n")
    return 0
