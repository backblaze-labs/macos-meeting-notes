import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meeting_memory.service.recorder import RecorderService
from meeting_memory.service.recovery_index import discover_indexed_recoveries


class Capture:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE" + b"audio")

    def stop(self) -> None:
        return None


def test_recorder_uses_unique_private_indexed_session_and_persists_final_meta(
    tmp_path: Path,
) -> None:
    started = datetime(2026, 8, 10, 10, tzinfo=UTC)
    times = iter((started, started + timedelta(minutes=3)))
    staging = tmp_path / "meetings" / ".meeting-memory-staging" / "recordings"
    seen: list[Path] = []

    def start_capture(_mode: str, path: Path) -> Capture:
        seen.append(path)
        assert path.parent.stat().st_mode & 0o077 == 0
        assert (path.parent / "recovery.json").is_file()
        return Capture(path)

    recorder = RecorderService(
        temp_dir=staging,
        now=lambda: next(times),
        capture_starter=start_capture,
    )
    session = recorder.start("Product Sync")
    result = recorder.stop()

    assert session is not None and result is not None
    assert seen == [session.recovery.source_path]
    assert result.recovery is not None
    assert result.recovery.source_path.is_file()
    recovered = discover_indexed_recoveries(staging)
    assert len(recovered) == 1
    assert recovered[0].meta.duration_minutes == 3
    assert recovered[0].source_sha256 == result.recovery.source_sha256


def test_capture_starter_failure_preserves_nonempty_recoverable_wav(tmp_path: Path) -> None:
    staging = tmp_path / "meetings" / ".meeting-memory-staging" / "recordings"

    def write_then_fail(_mode: str, path: Path):
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(b"\0\0" * 16_000)
        raise RuntimeError("helper failed after samples")

    recorder = RecorderService(temp_dir=staging, capture_starter=write_then_fail)

    with pytest.raises(RuntimeError, match="after samples"):
        recorder.start("Recoverable")

    recovered = discover_indexed_recoveries(staging)
    assert len(recovered) == 1
    assert recovered[0].source_path.stat().st_size > 0


def test_capture_starter_failure_discards_header_only_wav(tmp_path: Path) -> None:
    staging = tmp_path / "meetings" / ".meeting-memory-staging" / "recordings"

    def write_header_then_fail(_mode: str, path: Path):
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
        raise RuntimeError("helper failed before samples")

    recorder = RecorderService(temp_dir=staging, capture_starter=write_header_then_fail)

    with pytest.raises(RuntimeError, match="before samples"):
        recorder.start("Empty")

    assert discover_indexed_recoveries(staging) == ()
    assert list(staging.iterdir()) == []
