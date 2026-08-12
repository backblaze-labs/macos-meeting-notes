"""Recording Core readiness checks with mode-aware macOS authorization."""

from __future__ import annotations

import os
import platform
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from meeting_memory.config.runtime import RuntimeSettings
from meeting_memory.repo.native_audio import NativeAudioCaptureError, check_native_capture
from meeting_memory.service.audio_modes import audio_mode_by_key
from meeting_memory.service.recorder import DEFAULT_CAPTURE_MODE
from meeting_memory.types.capabilities import Capability, CapabilityState, CapabilityStatus

NativeProbe = Callable[[], Mapping[str, Any]]
DurableProbe = Callable[[Path], None]
ProbeWriter = Callable[[int, bytes], int]
ProbeSync = Callable[[int], None]
PROBE_BYTES = b"meeting-memory-readiness\n"
AUTHORIZED = "authorized"


def recording_core_status(
    settings: RuntimeSettings,
    *,
    native_probe: NativeProbe | None = None,
    durable_probe: DurableProbe | None = None,
    system_name: str | None = None,
    kernel_release: str | None = None,
    python_version: tuple[int, int] | None = None,
    capture_mode: str = DEFAULT_CAPTURE_MODE,
) -> CapabilityStatus:
    """Check whether the selected local capture mode is currently usable."""

    if (python_version or sys.version_info[:2]) < (3, 11):
        return _failed(
            "Python 3.11 or newer is required for local recording.",
            "Install Python 3.11 or newer, then rerun the setup check.",
        )
    if (system_name or platform.system()) != "Darwin" or not _supported_macos_release(
        kernel_release or platform.release()
    ):
        return _failed(
            "macOS 15 Sequoia or newer is required for native audio capture.",
            "Run Meeting Memory on a Mac with macOS 15 or newer.",
        )

    storage_problem = _meetings_directory_problem(
        settings.meetings_dir_path,
        durable_probe=durable_probe or _probe_durable_write,
    )
    if storage_problem is not None:
        return _failed(
            storage_problem,
            "Choose a writable local MEETINGS_DIR, then rerun the setup check.",
        )

    try:
        mode = audio_mode_by_key(capture_mode)
    except LookupError:
        return _failed(
            "The selected audio mode is invalid.",
            "Select Full Meeting or Silent System Only, then rerun the setup check.",
        )
    try:
        event = (native_probe or check_native_capture)()
    except NativeAudioCaptureError as exc:
        detail = str(exc).strip() or "the native helper check failed"
        return _failed(
            f"Native audio capture is unavailable: {detail}",
            "Run make setup to rebuild the native audio toolchain, then check macOS permissions.",
        )
    except Exception:
        return _failed(
            "The native audio readiness check could not complete.",
            "Run make setup, then rerun the setup check.",
        )

    system_permission = _event_value(event, "system_audio_permission")
    microphone_permission = _event_value(event, "microphone_permission")
    microphone = str(event.get("microphone", "unknown")).strip()
    has_microphone = microphone.lower() not in {"", "none", "unknown"}
    limitations: list[str] = []
    permissions: list[str] = []

    if system_permission != AUTHORIZED:
        limitations.append("Screen & System Audio Recording permission")
        permissions.append("Screen & System Audio Recording permission")
    if mode.capture_microphone and microphone_permission != AUTHORIZED:
        limitations.append("Microphone permission")
        permissions.append("Microphone permission")
    if mode.capture_microphone and not has_microphone:
        limitations.append("a default microphone")

    if limitations:
        summary = (
            f"Local storage and native audio are ready; {mode.label} is missing "
            f"{_joined(limitations)}."
        )
        steps = []
        if permissions:
            steps.append(f"start a short {mode.label} recording and grant {_joined(permissions)}")
        if mode.capture_microphone and not has_microphone:
            steps.append("select a macOS input device")
        action = f"{_sentence(steps)}, then rerun the setup check."
        if permissions:
            action += (
                " If access was previously denied, enable Meeting Memory in System Settings > "
                "Privacy & Security."
            )
        return CapabilityStatus(
            Capability.RECORDING_CORE,
            CapabilityState.DEGRADED,
            summary,
            action,
        )

    detail = f" using {microphone}" if mode.capture_microphone else ""
    return CapabilityStatus(
        Capability.RECORDING_CORE,
        CapabilityState.READY,
        f"Local storage, native audio, and {mode.label} permissions are ready{detail}.",
    )


def _event_value(event: Mapping[str, Any], key: str) -> str:
    return str(event.get(key, "unknown")).strip().lower()


def _joined(items: list[str]) -> str:
    unique = list(dict.fromkeys(items))
    if len(unique) < 2:
        return unique[0]
    return ", ".join(unique[:-1]) + f" and {unique[-1]}"


def _sentence(items: list[str]) -> str:
    text = _joined(items)
    return text[:1].upper() + text[1:]


def _meetings_directory_problem(path: Path, *, durable_probe: DurableProbe) -> str | None:
    try:
        if path.exists() and not path.is_dir():
            return "MEETINGS_DIR points to a file instead of a folder."
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            return "MEETINGS_DIR points to a file instead of a folder."
        durable_probe(path)
    except OSError:
        return "MEETINGS_DIR could not pass a durable local write check."
    return None


def _probe_durable_write(
    directory: Path,
    *,
    writer: ProbeWriter | None = None,
    sync: ProbeSync | None = None,
) -> None:
    write_bytes = writer or os.write
    sync_descriptor = sync or os.fsync
    descriptor = -1
    probe_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".meeting-memory-readiness-", dir=directory)
        probe_path = Path(raw_path)
        written = write_bytes(descriptor, PROBE_BYTES)
        if written != len(PROBE_BYTES):
            raise OSError("readiness probe write was incomplete")
        sync_descriptor(descriptor)
        os.close(descriptor)
        descriptor = -1
        _fsync_directory(directory, sync=sync_descriptor)
        probe_path.unlink()
        probe_path = None
        _fsync_directory(directory, sync=sync_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if probe_path is not None:
            try:
                probe_path.unlink()
            except FileNotFoundError:
                pass
            try:
                _fsync_directory(directory, sync=sync_descriptor)
            except OSError:
                pass


def _fsync_directory(directory: Path, *, sync: ProbeSync | None = None) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        (sync or os.fsync)(descriptor)
    finally:
        os.close(descriptor)


def _supported_macos_release(release: str) -> bool:
    try:
        return int(release.split(".", maxsplit=1)[0]) >= 24
    except (TypeError, ValueError):
        return False


def _failed(summary: str, action: str) -> CapabilityStatus:
    return CapabilityStatus(
        Capability.RECORDING_CORE,
        CapabilityState.FAILED,
        summary,
        action,
    )
