"""Explicit provider selection and consent, independent of inherited keys."""

from meeting_memory.config.validation import valid_required_setting
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import PreferenceKey, SettingKey
from meeting_memory.types.configuration_resolution import CapabilityResolution, SettingSource
from meeting_memory.types.transcription import ASSEMBLYAI_CONSENT_VERSION, TranscriptionProvider

SELECTION_KEYS = frozenset({SettingKey.TRANSCRIPTION_PROVIDER, SettingKey.ASSEMBLYAI_CONSENT})


def resolve_transcription(process, preferences, settings, *, preferences_available):
    preference = preferences.enabled_for(Capability.TRANSCRIPTION)
    selected = {item.provenance.key: item for item in settings}
    provider = selected[SettingKey.TRANSCRIPTION_PROVIDER]
    source = provider.provenance.source
    if preference is False:
        return CapabilityResolution(
            Capability.TRANSCRIPTION, False, False, SettingSource.APP_PREFERENCE
        )
    valid = provider.value in tuple(TranscriptionProvider)
    local = provider.value == TranscriptionProvider.LOCAL
    accepted = selected[SettingKey.ASSEMBLYAI_CONSENT].value == ASSEMBLYAI_CONSENT_VERSION
    key = selected[SettingKey.ASSEMBLYAI_API_KEY].value
    ready = valid and (
        local or accepted and valid_required_setting(SettingKey.ASSEMBLYAI_API_KEY, key)
    )
    override = (
        provider.provenance.source is SettingSource.PROCESS_ENV
        and ready
        and (
            local
            or all(
                key in process
                for key in (SettingKey.ASSEMBLYAI_CONSENT, SettingKey.ASSEMBLYAI_API_KEY)
            )
        )
    )
    enabled = ready and (preferences_available or override)
    return CapabilityResolution(
        Capability.TRANSCRIPTION,
        preference,
        enabled,
        source,
        process_override=override,
        configuration_error=not enabled,
    )


def selection_value(definition, process, preferences):
    if definition.key in process:
        return process[definition.key], SettingSource.PROCESS_ENV
    value = preferences.value_for(PreferenceKey(definition.key.value))
    if value is not None:
        return value, SettingSource.APP_PREFERENCE
    # New external-provider selection/acceptance is app/process-only. Legacy
    # imports may retain keys, but cannot grant permission to send meeting audio.
    return definition.default, SettingSource.DEFAULT


def active_transcription_setting(key, settings):
    if key not in {SettingKey.ASSEMBLYAI_API_KEY, SettingKey.ASSEMBLYAI_CONSENT}:
        return True
    return (
        next(
            item.value
            for item in settings
            if item.provenance.key is SettingKey.TRANSCRIPTION_PROVIDER
        )
        == TranscriptionProvider.ASSEMBLYAI
    )


def invalid_transcription_process(resolution):
    provider = resolution.value_for(SettingKey.TRANSCRIPTION_PROVIDER)
    process_keys = {
        item.key for item in resolution.provenance if item.source is SettingSource.PROCESS_ENV
    }
    if provider not in tuple(TranscriptionProvider):
        return SettingKey.TRANSCRIPTION_PROVIDER in process_keys
    if provider == TranscriptionProvider.LOCAL:
        return False
    return (
        SettingKey.ASSEMBLYAI_CONSENT in process_keys
        and resolution.value_for(SettingKey.ASSEMBLYAI_CONSENT) != ASSEMBLYAI_CONSENT_VERSION
    ) or (
        SettingKey.ASSEMBLYAI_API_KEY in process_keys
        and not valid_required_setting(
            SettingKey.ASSEMBLYAI_API_KEY, resolution.value_for(SettingKey.ASSEMBLYAI_API_KEY)
        )
    )
