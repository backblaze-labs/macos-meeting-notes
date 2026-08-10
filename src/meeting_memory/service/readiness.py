"""Capability-scoped, local-first readiness diagnostics."""

from __future__ import annotations

import os
import platform
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from meeting_memory.config.runtime import RuntimeSettings, load_runtime_settings
from meeting_memory.repo.native_audio import NativeAudioCaptureError, check_native_capture
from meeting_memory.service.readiness_integrations import TokenReader, optional_statuses
from meeting_memory.types.capabilities import (
    Capability,
    CapabilityState,
    CapabilityStatus,
    ReadinessReport,
)

NativeProbe = Callable[[], Mapping[str, Any]]
DurableProbe = Callable[[Path], None]
ProbeWriter = Callable[[int, bytes], int]
ProbeSync = Callable[[int], None]
PROBE_BYTES = b"meeting-memory-readiness\n"


def load_readiness_report(env_file: str | Path | None = ".env") -> ReadinessReport:
    """Load legacy-compatible settings and always return a complete report."""

    try:
        settings = load_runtime_settings(env_file)
    except Exception:
        return _configuration_failure_report()
    return build_readiness_report(settings)


def build_readiness_report(
    settings: RuntimeSettings,
    *,
    native_probe: NativeProbe | None = None,
    token_reader: TokenReader | None = None,
    durable_probe: DurableProbe | None = None,
    system_name: str | None = None,
    kernel_release: str | None = None,
    python_version: tuple[int, int] | None = None,
) -> ReadinessReport:
    """Check local readiness without contacting an optional provider."""

    try:
        core = _recording_core_status(
            settings,
            native_probe=native_probe or check_native_capture,
            durable_probe=durable_probe or _probe_durable_write,
            system_name=system_name or platform.system(),
            kernel_release=kernel_release or platform.release(),
            python_version=python_version or sys.version_info[:2],
        )
        statuses = (
            core,
            *optional_statuses(settings, token_reader=token_reader),
        )
        return ReadinessReport(statuses)
    except Exception:
        return failed_readiness_report()


def checking_readiness_report() -> ReadinessReport:
    """Return the non-blocking transient report rendered during an explicit check."""

    return ReadinessReport(
        tuple(
            CapabilityStatus(capability, CapabilityState.CHECKING, "Readiness check in progress.")
            for capability in Capability
        )
    )


def failed_readiness_report() -> ReadinessReport:
    """Return a sanitized terminal report when the diagnostic itself fails."""

    return ReadinessReport(
        tuple(
            CapabilityStatus(
                capability,
                CapabilityState.FAILED,
                f"{capability.label} readiness could not be determined.",
                "Retry Check Setup & Dependencies.",
            )
            for capability in Capability
        )
    )


def _recording_core_status(
    settings: RuntimeSettings,
    *,
    native_probe: NativeProbe,
    durable_probe: DurableProbe,
    system_name: str,
    kernel_release: str,
    python_version: tuple[int, int],
) -> CapabilityStatus:
    if python_version < (3, 11):
        return _failed(
            Capability.RECORDING_CORE,
            "Python 3.11 or newer is required for local recording.",
            "Install Python 3.11 or newer, then rerun the setup check.",
        )
    if system_name != "Darwin" or not _supported_macos_release(kernel_release):
        return _failed(
            Capability.RECORDING_CORE,
            "macOS 15 Sequoia or newer is required for native audio capture.",
            "Run Meeting Memory on a Mac with macOS 15 or newer.",
        )

    storage_problem = _meetings_directory_problem(
        settings.meetings_dir_path,
        durable_probe=durable_probe,
    )
    if storage_problem is not None:
        return _failed(
            Capability.RECORDING_CORE,
            storage_problem,
            "Choose a writable local MEETINGS_DIR, then rerun the setup check.",
        )

    try:
        event = native_probe()
    except NativeAudioCaptureError as exc:
        detail = str(exc).strip() or "the native helper check failed"
        return _failed(
            Capability.RECORDING_CORE,
            f"Native audio capture is unavailable: {detail}",
            "Run make setup to rebuild the native audio helper, then check macOS permissions.",
        )
    except Exception:
        return _failed(
            Capability.RECORDING_CORE,
            "The native audio readiness check could not complete.",
            "Run make setup, then rerun the setup check.",
        )

    microphone = str(event.get("microphone", "unknown")).strip().lower()
    if microphone in {"", "none", "unknown"}:
        return CapabilityStatus(
            Capability.RECORDING_CORE,
            CapabilityState.DEGRADED,
            "Local storage and the native audio helper are available; capture "
            "permissions are unchecked, and Full Meeting has no microphone.",
            "Connect or select a macOS input device for Full Meeting, then start a "
            "short recording and grant the mode-specific permissions when prompted.",
        )
    return CapabilityStatus(
        Capability.RECORDING_CORE,
        CapabilityState.DEGRADED,
        "Local storage and the native audio helper are ready; capture permissions are unchecked.",
        "Start a short recording and grant the mode-specific macOS permissions when prompted.",
    )


def _meetings_directory_problem(
    path: Path,
    *,
    durable_probe: DurableProbe,
) -> str | None:
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
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".meeting-memory-readiness-",
            dir=directory,
        )
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
                # The main path may already have removed the best-effort probe.
                pass
            try:
                _fsync_directory(directory, sync=sync_descriptor)
            except OSError:
                # Cleanup durability must not replace the original probe failure.
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


def _configuration_failure_report() -> ReadinessReport:
    core = _failed(
        Capability.RECORDING_CORE,
        "Recording Core configuration could not be loaded.",
        "Fix MEETINGS_DIR and MAX_RECORDING_MINUTES, then rerun the setup check.",
    )
    return _report_with_unconfigured_optionals(core)


def _report_with_unconfigured_optionals(core: CapabilityStatus) -> ReadinessReport:
    return ReadinessReport(
        (
            core,
            *(
                _unconfigured(
                    capability,
                    "Readiness is unavailable until local configuration is valid.",
                    "Fix Recording Core configuration, then rerun the setup check.",
                )
                for capability in Capability
                if capability is not Capability.RECORDING_CORE
            ),
        )
    )


def _unconfigured(capability: Capability, summary: str, action: str) -> CapabilityStatus:
    return CapabilityStatus(capability, CapabilityState.UNCONFIGURED, summary, action)


def _failed(capability: Capability, summary: str, action: str) -> CapabilityStatus:
    return CapabilityStatus(capability, CapabilityState.FAILED, summary, action)
