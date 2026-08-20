"""Pure boundary data for native audio capture diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class CaptureSourceDiagnostics:
    """Bounded health evidence for one native capture source."""

    name: str
    callbacks: int
    frames: int
    peak: float
    discarded_frames: int = 0
    first_callback_seconds: float | None = None
    last_callback_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.name not in {"system", "microphone"}:
            raise ValueError("capture source name is invalid")
        if min(self.callbacks, self.frames, self.discarded_frames) < 0:
            raise ValueError("capture source counters must be non-negative")
        if not math.isfinite(self.peak) or self.peak < 0:
            raise ValueError("capture source peak must be finite and non-negative")
        for value in (self.first_callback_seconds, self.last_callback_seconds):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("capture callback time must be finite and non-negative")

    def to_payload(self) -> dict[str, object]:
        return {
            "callbacks": self.callbacks,
            "frames": self.frames,
            "peak": round(self.peak, 6),
            "discarded_frames": self.discarded_frames,
            "first_callback_seconds": _rounded(self.first_callback_seconds),
            "last_callback_seconds": _rounded(self.last_callback_seconds),
        }

    @classmethod
    def from_payload(cls, name: str, payload: object) -> CaptureSourceDiagnostics:
        if not isinstance(payload, dict):
            raise ValueError("capture source diagnostics must be an object")
        return cls(
            name=name,
            callbacks=_nonnegative_int(payload.get("callbacks")),
            frames=_nonnegative_int(payload.get("frames")),
            peak=_nonnegative_float(payload.get("peak")),
            discarded_frames=_nonnegative_int(payload.get("discarded_frames")),
            first_callback_seconds=_optional_nonnegative_float(
                payload.get("first_callback_seconds")
            ),
            last_callback_seconds=_optional_nonnegative_float(payload.get("last_callback_seconds")),
        )


@dataclass(frozen=True)
class CaptureDiagnostics:
    """Sanitized source evidence retained with one completed recording."""

    mode: str
    microphone: str | None
    elapsed_seconds: float
    sources: tuple[CaptureSourceDiagnostics, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"full-meeting", "silent-system-only"}:
            raise ValueError("capture mode is invalid")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("capture elapsed time must be finite and non-negative")
        names = tuple(source.name for source in self.sources)
        expected = ("system", "microphone") if self.mode == "full-meeting" else ("system",)
        if names != expected:
            raise ValueError("capture diagnostics do not match the selected mode")
        if not all(isinstance(code, str) and code for code in self.warnings):
            raise ValueError("capture warning codes must be non-blank strings")

    @property
    def status(self) -> str:
        return "warning" if self.warnings else "healthy"

    def source(self, name: str) -> CaptureSourceDiagnostics | None:
        return next((source for source in self.sources if source.name == name), None)

    def with_warnings(self, warnings: tuple[str, ...]) -> CaptureDiagnostics:
        return replace(self, warnings=tuple(dict.fromkeys(warnings)))

    def to_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "microphone": self.microphone,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "status": self.status,
            "warnings": list(self.warnings),
            "sources": {source.name: source.to_payload() for source in self.sources},
        }

    @classmethod
    def from_payload(cls, payload: object) -> CaptureDiagnostics:
        if not isinstance(payload, dict):
            raise ValueError("capture diagnostics must be an object")
        mode = str(payload.get("mode") or "")
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, dict):
            raise ValueError("capture diagnostics sources must be an object")
        names = ("system", "microphone") if mode == "full-meeting" else ("system",)
        raw_warnings = payload.get("warnings", ())
        if not isinstance(raw_warnings, list | tuple):
            raise ValueError("capture diagnostics warnings must be a list")
        microphone = payload.get("microphone")
        return cls(
            mode=mode,
            microphone=str(microphone) if microphone not in {None, "off", "unknown"} else None,
            elapsed_seconds=_nonnegative_float(payload.get("elapsed_seconds")),
            sources=tuple(
                CaptureSourceDiagnostics.from_payload(name, raw_sources.get(name)) for name in names
            ),
            warnings=tuple(str(code) for code in raw_warnings),
        )


@dataclass(frozen=True)
class CaptureHealthWarning:
    code: str
    message: str


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("capture counter must be an integer")
    number = int(value)
    if number < 0:
        raise ValueError("capture counter must be non-negative")
    return number


def _nonnegative_float(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("capture metric must be finite and non-negative")
    return number


def _optional_nonnegative_float(value: Any) -> float | None:
    return None if value is None else _nonnegative_float(value)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)
