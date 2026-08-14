"""Local configuration checks for optional capabilities."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from pathlib import Path

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.config.validation import valid_b2_endpoint
from meeting_memory.repo.calendar_oauth import (
    is_valid_calendar_token_json,
    is_valid_desktop_client_file,
)
from meeting_memory.repo.prompt_source import read_prompt_text
from meeting_memory.service.configuration_loader import LoadedConfiguration
from meeting_memory.service.readiness_configuration import (
    effective_optional_status,
    safe_optional_status,
)
from meeting_memory.types.capabilities import Capability, CapabilityState, CapabilityStatus

TokenReader = Callable[[], str | None]
KEYCHAIN_TIMEOUT_SECONDS = 5.0
MAX_LOCAL_CONFIG_BYTES = 1_048_576


def optional_statuses(
    settings: RuntimeSettings,
    *,
    token_reader: TokenReader | None = None,
    configuration: LoadedConfiguration | None = None,
) -> tuple[CapabilityStatus, ...]:
    return (
        effective_optional_status(
            Capability.TRANSCRIPTION,
            configuration,
            lambda: _transcription_status(settings),
        ),
        effective_optional_status(
            Capability.BACKUP,
            configuration,
            lambda: _backup_status(settings),
        ),
        safe_optional_status(
            Capability.CALENDAR,
            lambda: effective_optional_status(
                Capability.CALENDAR,
                configuration,
                lambda: _calendar_status(settings, token_reader=token_reader),
            ),
        ),
        effective_optional_status(
            Capability.NOTES,
            configuration,
            lambda: _notes_status(settings),
        ),
    )


def _transcription_status(settings: RuntimeSettings) -> CapabilityStatus:
    if settings.transcription is None:
        return _unconfigured(
            Capability.TRANSCRIPTION,
            "Transcription is not configured; recordings remain local audio.",
            "Set ASSEMBLYAI_API_KEY to enable transcription for new recordings.",
        )
    return _ready(
        Capability.TRANSCRIPTION,
        "AssemblyAI transcription is configured for new recordings.",
    )


def _backup_status(settings: RuntimeSettings) -> CapabilityStatus:
    fields = {
        "B2_APPLICATION_KEY_ID": settings.b2_application_key_id,
        "B2_APPLICATION_KEY": settings.b2_application_key,
        "B2_ENDPOINT": settings.b2_endpoint,
        "B2_REGION": settings.b2_region,
        "B2_BUCKET_NAME": settings.b2_bucket_name,
    }
    missing = [name for name, value in fields.items() if not value]
    if missing:
        summary = "Backup is not configured."
        if len(missing) != len(fields):
            summary = f"Backup setup is incomplete; missing {', '.join(missing)}."
        return _unconfigured(
            Capability.BACKUP,
            summary,
            "Set the complete B2 configuration group to enable backup for new recordings.",
        )

    if not valid_b2_endpoint(settings.b2_endpoint):
        return _failed(
            Capability.BACKUP,
            "The configured B2 endpoint is not a valid HTTPS URL.",
            "Set B2_ENDPOINT to the bucket's S3-compatible HTTPS endpoint.",
        )
    return _ready(Capability.BACKUP, "Backblaze B2 backup is configured for new recordings.")


def _calendar_status(
    settings: RuntimeSettings,
    *,
    token_reader: TokenReader | None,
) -> CapabilityStatus:
    config = settings.calendar
    if settings.google_calendar_credentials_file is None:
        return _unconfigured(
            Capability.CALENDAR,
            "Calendar context and reminders are not configured.",
            "Set GOOGLE_CALENDAR_CREDENTIALS_FILE to opt in to Google Calendar.",
        )
    if config is None:
        return _failed(
            Capability.CALENDAR,
            "Calendar configuration contains an invalid local setting.",
            "Fix the Calendar ID, notification lead time, and polling interval.",
        )

    credentials = _local_path(config.credentials_file)
    if not _valid_google_credentials(credentials):
        return _failed(
            Capability.CALENDAR,
            "The configured Google OAuth Desktop app credentials file is missing or invalid.",
            "Download Desktop app OAuth credentials and update GOOGLE_CALENDAR_CREDENTIALS_FILE.",
        )

    try:
        token = _read_token_bounded(token_reader or _read_calendar_token)
    except Exception:
        return _failed(
            Capability.CALENDAR,
            "Google Calendar authorization could not be read from macOS Keychain.",
            "Unlock Keychain, then run meeting-memory auth and rerun the setup check.",
        )
    if not token:
        return _failed(
            Capability.CALENDAR,
            "Google Calendar is configured but has not been authorized.",
            "Run meeting-memory auth to save the Calendar grant in macOS Keychain.",
        )
    if not _valid_calendar_token(token):
        return _failed(
            Capability.CALENDAR,
            "Google Calendar authorization in macOS Keychain is invalid.",
            "Run meeting-memory auth again to replace the invalid Calendar grant.",
        )
    return _ready(Capability.CALENDAR, "Google Calendar configuration and authorization are ready.")


def _notes_status(settings: RuntimeSettings) -> CapabilityStatus:
    if settings.anthropic_api_key is None:
        return _unconfigured(
            Capability.NOTES,
            "Derived Notes are not configured; reviewed transcripts remain available.",
            "Set ANTHROPIC_API_KEY to enable Notes after speaker review.",
        )
    if settings.notes is None:
        return _failed(
            Capability.NOTES,
            "Notes configuration is invalid because the model name is missing.",
            "Set ANTHROPIC_MODEL or remove the invalid override to use the default model.",
        )

    prompt = settings.notes.prompt_file
    if prompt is not None:
        prompt_state, prompt_problem = _prompt_problem(_local_path(prompt))
        if prompt_problem is not None:
            return CapabilityStatus(
                Capability.NOTES,
                prompt_state,
                prompt_problem,
                "Fix SUMMARY_PROMPT_FILE or unset it to use the built-in Notes file.",
            )
    return _ready(Capability.NOTES, "Anthropic Notes are configured for reviewed transcripts.")


def _local_path(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ValueError("runtime configuration paths must be absolute")
    return expanded


def _valid_google_credentials(path: Path) -> bool:
    return is_valid_desktop_client_file(path)


def _prompt_problem(path: Path) -> tuple[CapabilityState, str | None]:
    try:
        text = read_prompt_text(path)
    except Exception:
        return (
            CapabilityState.FAILED,
            "Notes is blocked because its configured prompt source was rejected safely.",
        )
    if text is None:
        return (
            CapabilityState.DEGRADED,
            "Notes is configured, but its prompt file is missing; built-in text will be used.",
        )
    if not text.strip():
        return (
            CapabilityState.DEGRADED,
            "Notes is configured, but its prompt file is empty; built-in text will be used.",
        )
    return CapabilityState.READY, None


def _read_calendar_token() -> str | None:
    from meeting_memory.repo.calendar_client import KeychainTokenStore

    return KeychainTokenStore().read_token()


def _read_token_bounded(reader: TokenReader) -> str | None:
    outcomes: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            outcomes.put((True, reader()))
        except Exception as exc:
            outcomes.put((False, exc))

    threading.Thread(target=run, daemon=True).start()
    try:
        succeeded, value = outcomes.get(timeout=KEYCHAIN_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        raise TimeoutError("Keychain readiness check timed out") from exc
    if not succeeded:
        raise RuntimeError("Keychain readiness check failed")
    return str(value) if value is not None else None


def _valid_calendar_token(token: str) -> bool:
    return is_valid_calendar_token_json(token)


def _ready(capability: Capability, summary: str) -> CapabilityStatus:
    return CapabilityStatus(capability, CapabilityState.READY, summary)


def _unconfigured(capability: Capability, summary: str, action: str) -> CapabilityStatus:
    return CapabilityStatus(capability, CapabilityState.UNCONFIGURED, summary, action)


def _failed(capability: Capability, summary: str, action: str) -> CapabilityStatus:
    return CapabilityStatus(capability, CapabilityState.FAILED, summary, action)
