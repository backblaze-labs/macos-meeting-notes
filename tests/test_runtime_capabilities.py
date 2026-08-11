"""Monotonic runtime capability pause coordination."""

from __future__ import annotations

import threading

from meeting_memory.service.runtime_capabilities import RuntimeCapabilityPause
from meeting_memory.types.capabilities import Capability


def test_pause_is_authoritative_even_when_side_effect_callback_fails() -> None:
    calls = 0

    def fail_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private-callback-sentinel")

    controls = RuntimeCapabilityPause({Capability.BACKUP: fail_once})

    assert controls.pause(Capability.BACKUP) is False
    assert controls.allows(Capability.BACKUP) is False
    assert controls.pause(Capability.BACKUP) is True
    assert calls == 2


def test_concurrent_pause_waits_until_callback_reaches_safe_boundary() -> None:
    entered = threading.Event()
    release = threading.Event()
    results: list[bool] = []

    def callback() -> None:
        entered.set()
        release.wait(timeout=2)

    controls = RuntimeCapabilityPause({Capability.TRANSCRIPTION: callback})
    first = threading.Thread(
        target=lambda: results.append(controls.pause(Capability.TRANSCRIPTION))
    )
    second = threading.Thread(
        target=lambda: results.append(controls.pause(Capability.TRANSCRIPTION))
    )

    first.start()
    assert entered.wait(timeout=1)
    second.start()
    assert results == []
    assert controls.allows(Capability.TRANSCRIPTION) is False
    release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert results == [True, True]


def test_recording_core_is_never_paused() -> None:
    controls = RuntimeCapabilityPause()

    assert controls.pause(Capability.RECORDING_CORE) is True
    assert controls.allows(Capability.RECORDING_CORE) is True
