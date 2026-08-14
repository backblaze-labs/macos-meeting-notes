"""Executable checks for native recording lifetime fail-safes."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "meeting_memory" / "repo" / "native" / "RecordingLifetime.swift"


@pytest.mark.skipif(sys.platform != "darwin", reason="native helper targets macOS")
def test_native_lifetime_stops_for_parent_exit_and_watchdog(tmp_path: Path) -> None:
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        pytest.skip("Swift compiler is unavailable")
    harness = tmp_path / "LifetimeHarness.swift"
    harness.write_text(
        """
        import Darwin
        import Foundation

        @main
        struct LifetimeHarness {
            static func main() async {
                let mode = CommandLine.arguments[1]
                let timeout = mode == "watchdog" ? 0.05 : 10.0
                let lifetime = RecordingLifetime(
                    parentPID: getppid(),
                    watchdogSeconds: timeout
                )
                if mode == "parent" {
                    try! Data("ready".utf8).write(
                        to: URL(fileURLWithPath: CommandLine.arguments[2])
                    )
                }
                let started = Date()
                if await lifetime.waitForStopOrFailure() != nil { exit(2) }
                if Date().timeIntervalSince(started) > 2 { exit(3) }
                if mode == "parent" {
                    try! Data("stopped".utf8).write(
                        to: URL(fileURLWithPath: CommandLine.arguments[3])
                    )
                }
                exit(0)
            }
        }
        """,
        encoding="utf-8",
    )
    executable = tmp_path / "lifetime-harness"
    module_cache = tmp_path / "module-cache"
    module_cache.mkdir()
    subprocess.run(
        [
            swiftc,
            "-module-cache-path",
            str(module_cache),
            str(SOURCE),
            str(harness),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    subprocess.run(
        [str(executable), "watchdog"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    ready = tmp_path / "parent-ready"
    stopped = tmp_path / "parent-stopped"
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        """
import subprocess
import sys
import time
from pathlib import Path

child = subprocess.Popen(
    [sys.argv[1], "parent", sys.argv[2], sys.argv[3]],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
deadline = time.monotonic() + 10
while not Path(sys.argv[2]).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not Path(sys.argv[2]).exists():
    child.kill()
    raise SystemExit(2)
print(child.pid, flush=True)
""",
        encoding="utf-8",
    )
    launched = subprocess.run(
        [sys.executable, str(launcher), str(executable), str(ready), str(stopped)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert int(launched.stdout.strip()) > 1
    deadline = time.monotonic() + 2
    while not stopped.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert stopped.read_text(encoding="utf-8") == "stopped"
