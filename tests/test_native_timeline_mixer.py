"""Behavior tests for the Swift native audio timeline mixer."""

from __future__ import annotations

import array
import platform
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE_CAPTURE = ROOT / "src" / "meeting_memory" / "repo" / "native" / "NativeCapture.swift"

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS native helper")


def test_mixer_rebases_independent_system_and_microphone_clocks(tmp_path: Path) -> None:
    swiftc = shutil.which("swiftc")
    assert swiftc is not None
    harness = tmp_path / "TimelineMixerHarness.swift"
    executable = tmp_path / "TimelineMixerHarness"
    output = tmp_path / "mixed.wav"
    harness.write_text(
        """
import Foundation

@main
struct TimelineMixerHarness {
    static func main() throws {
        let output = URL(fileURLWithPath: CommandLine.arguments[1])
        let writer = try WAVWriter(url: output)
        let mixer = TimelineMixer(writer: writer, enabledSources: [.system, .microphone])
        try mixer.add(
            Array(repeating: Float.zero, count: 1_600),
            source: .system,
            presentationSeconds: 1_000,
            arrivalSeconds: 50
        )
        try mixer.add(
            Array(repeating: Float(1), count: 1_600),
            source: .microphone,
            presentationSeconds: 10,
            arrivalSeconds: 50.01
        )
        try mixer.finish()
    }
}
""",
        encoding="utf-8",
    )
    module_cache = tmp_path / "module-cache"
    architecture = "x86_64" if platform.machine() == "x86_64" else "arm64"
    subprocess.run(
        [
            swiftc,
            "-parse-as-library",
            "-module-cache-path",
            str(module_cache),
            "-target",
            f"{architecture}-apple-macosx15.0",
            str(NATIVE_CAPTURE),
            str(harness),
            "-framework",
            "AVFoundation",
            "-framework",
            "CoreAudio",
            "-framework",
            "CoreMedia",
            "-framework",
            "ScreenCaptureKit",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable), str(output)], check=True)

    with wave.open(str(output), "rb") as recording:
        frames = recording.getnframes()
        samples = array.array("h", recording.readframes(frames))
    if sys.byteorder != "little":
        samples.byteswap()

    assert 1_600 <= frames <= 2_000
    assert max(map(abs, samples)) > 20_000
