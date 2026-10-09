"""Compose local people drafts and optional Notes-backed Haiku topics."""

from meeting_memory.repo.claude_speaker_topics import ClaudeSpeakerTopicsClient
from meeting_memory.service.speaker_knowledge import SpeakerKnowledgeService


def speaker_knowledge_service(configuration, *, enabled=lambda: True):
    topics = (
        ClaudeSpeakerTopicsClient(configuration.notes.api_key, enabled=enabled)
        if configuration.notes is not None
        else None
    )
    return SpeakerKnowledgeService(configuration.settings, topics=topics, enabled=enabled)


def local_speaker_knowledge_service():
    from meeting_memory.service.configuration_loader import (
        ConfigurationLoadError,
        load_configuration,
    )
    from meeting_memory.types.configuration_resolution import ConfigurationUse

    try:
        configuration = load_configuration(ConfigurationUse.RUNTIME)
    except ConfigurationLoadError:
        configuration = load_configuration(ConfigurationUse.SEARCH)
    return SpeakerKnowledgeService(configuration.settings)
