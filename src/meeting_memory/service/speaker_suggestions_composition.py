"""Compose Haiku proposals with the existing optional Notes key and pause gate."""

from collections.abc import Callable

from meeting_memory.repo.claude_speaker_identification import ClaudeSpeakerIdentificationClient
from meeting_memory.service.configuration_loaded import LoadedConfiguration
from meeting_memory.service.speaker_suggestions import SpeakerSuggestionLoader


def speaker_review_loader(
    configuration: LoadedConfiguration,
    *,
    enabled: Callable[[], bool] = lambda: True,
) -> SpeakerSuggestionLoader | None:
    config = configuration.notes
    if config is None:
        return None
    return SpeakerSuggestionLoader(
        ClaudeSpeakerIdentificationClient(config.api_key, admit_request=enabled),
        configuration.settings.known_speakers,
        enabled=enabled,
    )
