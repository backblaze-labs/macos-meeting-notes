"""Executable regression test for independent ScreenCaptureKit audio clocks."""

from __future__ import annotations

import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "meeting_memory" / "repo" / "native" / "NativeCapture.swift"


@pytest.mark.skipif(sys.platform != "darwin", reason="native mixer targets macOS")
def test_timeline_mixer_rebases_each_source_clock_without_dropping_it(
    tmp_path: Path,
) -> None:
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        pytest.skip("Swift compiler is unavailable")
    harness = tmp_path / "TimelineHarness.swift"
    harness.write_text(
        """
        import Foundation

        @main
        struct TimelineHarness {
            static func main() throws {
                let output = URL(fileURLWithPath: CommandLine.arguments[1])
                let mixer = TimelineMixer(
                    writer: try WAVWriter(url: output),
                    enabledSources: [.system, .microphone]
                )
                try mixer.add(
                    Array(repeating: 0.2, count: 1600),
                    source: .system,
                    presentationSeconds: 1000,
                    arrivalSeconds: 10
                )
                try mixer.add(
                    Array(repeating: 0.4, count: 1600),
                    source: .microphone,
                    presentationSeconds: 0,
                    arrivalSeconds: 10.05
                )
                let values = mixer.metrics(startedAt: 10, now: 10.2)
                let microphone = values["microphone"] as! [String: Any]
                if (microphone["discarded_frames"] as! Int64) != 0 { exit(2) }
                try mixer.finish()
            }
        }
        """,
        encoding="utf-8",
    )
    executable = tmp_path / "timeline-harness"
    module_cache = tmp_path / "module-cache"
    module_cache.mkdir()
    command = [
        swiftc,
        "-module-cache-path",
        str(module_cache),
    ]
    for framework in (
        "AVFoundation",
        "CoreAudio",
        "CoreMedia",
        "ScreenCaptureKit",
    ):
        command.extend(["-framework", framework])
    command.extend([str(SOURCE), str(harness), "-o", str(executable)])
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = tmp_path / "mixed.wav"
    subprocess.run([str(executable), str(output)], check=True, timeout=10)

    with wave.open(str(output), "rb") as audio:
        assert audio.getnframes() == 2_400
