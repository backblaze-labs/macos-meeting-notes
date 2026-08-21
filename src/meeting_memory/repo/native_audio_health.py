"""Thread-safe health state for native audio helper events."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from meeting_memory.types.audio import (
    CaptureDiagnostics,
    CaptureHealthWarning,
    CaptureSourceDiagnostics,
)

SOURCE_CALLBACK_GRACE_SECONDS = 10
SOURCE_STALL_SECONDS = 10
SYSTEM_SILENCE_GRACE_SECONDS = 90
SYSTEM_SILENCE_PEAK = 0.00001
DISCARDED_FRAME_WARNING_MINIMUM = 1_600
DISCARDED_FRAME_WARNING_RATIO = 0.01
LOGGER = logging.getLogger(__name__)


@dataclass
class HelperStatus:
    _failure_message: str | None = None
    _final_diagnostics: CaptureDiagnostics | None = None
    _warning_codes: list[str] = field(default_factory=list)
    _active_warnings: tuple[CaptureHealthWarning, ...] = ()
    _pending_warnings: list[CaptureHealthWarning] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, event: dict[str, Any]) -> None:
        event_name = event.get("event")
        if event_name in {"error", "fatal"}:
            message = str(event.get("message") or "native helper reported an error")
            with self._lock:
                self._failure_message = message
            return
        if event_name not in {"health", "stopped"}:
            return
        try:
            diagnostics = CaptureDiagnostics.from_payload(event)
        except (TypeError, ValueError) as exc:
            LOGGER.warning("Invalid native capture diagnostics: %s", exc)
            if event_name == "stopped":
                with self._lock:
                    self._failure_message = "native helper returned invalid final diagnostics"
            return
        warnings = diagnostic_warnings(diagnostics, final=event_name == "stopped")
        with self._lock:
            self._active_warnings = warnings
            known = set(self._warning_codes)
            for warning in warnings:
                if warning.code in known:
                    continue
                known.add(warning.code)
                self._warning_codes.append(warning.code)
                self._pending_warnings.append(warning)
            if event_name == "stopped":
                self._final_diagnostics = diagnostics.with_warning_state(
                    tuple(warning.code for warning in warnings),
                    tuple(self._warning_codes),
                )

    def failure_message(self) -> str | None:
        with self._lock:
            return self._failure_message

    def next_warning(self) -> CaptureHealthWarning | None:
        with self._lock:
            return self._pending_warnings.pop(0) if self._pending_warnings else None

    def active_warning(self) -> CaptureHealthWarning | None:
        with self._lock:
            return self._active_warnings[0] if self._active_warnings else None

    def final_diagnostics(self) -> CaptureDiagnostics | None:
        with self._lock:
            return self._final_diagnostics


def diagnostic_warnings(
    diagnostics: CaptureDiagnostics,
    *,
    final: bool,
) -> tuple[CaptureHealthWarning, ...]:
    warnings: list[CaptureHealthWarning] = []
    for source in diagnostics.sources:
        missing = source.callbacks == 0 and (
            final or diagnostics.elapsed_seconds >= SOURCE_CALLBACK_GRACE_SECONDS
        )
        if missing:
            warnings.append(_missing_source_warning(source))
        elif _source_stalled(source, diagnostics.elapsed_seconds):
            warnings.append(
                CaptureHealthWarning(
                    code=f"{source.name}_stalled",
                    message=(
                        f"{source.name.capitalize()} audio stopped arriving. "
                        "This recording may now be incomplete; stop and restart it."
                    ),
                )
            )
        if _has_material_discard(source):
            warnings.append(
                CaptureHealthWarning(
                    code=f"{source.name}_timing_discard",
                    message=(
                        f"{source.name.capitalize()} audio lost a material burst or share "
                        "of frames during mixing. "
                        "This recording may be incomplete; stop and restart it."
                    ),
                )
            )
    system = diagnostics.source("system")
    if (
        system is not None
        and system.callbacks > 0
        and system.peak <= SYSTEM_SILENCE_PEAK
        and diagnostics.elapsed_seconds >= SYSTEM_SILENCE_GRACE_SECONDS
    ):
        warnings.append(
            CaptureHealthWarning(
                code="system_silent",
                message=(
                    "No system audio has been detected for 90 seconds. "
                    "If the call is intentionally quiet, you can ignore this; "
                    "otherwise verify Zoom output."
                ),
            )
        )
    return tuple(warnings)


def _missing_source_warning(source: CaptureSourceDiagnostics) -> CaptureHealthWarning:
    label = "Zoom/system" if source.name == "system" else "Microphone"
    return CaptureHealthWarning(
        code=f"{source.name}_missing",
        message=(
            f"No {label} audio is reaching this recording. "
            "Stop and restart it before continuing the meeting."
        ),
    )


def _source_stalled(source: CaptureSourceDiagnostics, elapsed_seconds: float) -> bool:
    return (
        source.last_callback_seconds is not None
        and elapsed_seconds - source.last_callback_seconds >= SOURCE_STALL_SECONDS
    )


def _has_material_discard(source: CaptureSourceDiagnostics) -> bool:
    if source.discarded_frames < DISCARDED_FRAME_WARNING_MINIMUM:
        return False
    if source.largest_discarded_run >= DISCARDED_FRAME_WARNING_MINIMUM:
        return True
    return (
        source.frames > 0
        and source.discarded_frames / source.frames >= DISCARDED_FRAME_WARNING_RATIO
    )
