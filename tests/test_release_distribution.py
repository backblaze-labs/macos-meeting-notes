"""Protected release orchestration stays ordered and value-free."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import release_distribution as release

ROOT = Path(__file__).resolve().parents[1]


def _release_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    app = tmp_path / "Meeting Memory.app"
    app.mkdir()
    key = tmp_path / "AuthKey_private.p8"
    key.write_text("private-key-sentinel", encoding="utf-8")
    output = tmp_path / "release"
    return app, key, output


def test_release_verifies_notarizes_staples_and_archives(tmp_path: Path, monkeypatch) -> None:
    app, key, output = _release_inputs(tmp_path)
    calls: list[list[str]] = []
    verifications: list[tuple[str, bool]] = []

    def fake_verify(_app, arch, signature, notarized=False, team_id=None, *, runner):
        del runner
        assert arch == "arm64"
        assert team_id == "TEAM123"
        verifications.append((signature, notarized))

    def runner(command, **kwargs):
        del kwargs
        command = list(command)
        calls.append(command)
        if command[:2] == ["/usr/bin/ditto", "-c"]:
            Path(command[-1]).write_bytes(b"signed-archive")
        output_text = (
            '{"id":"opaque","status":"Accepted","issues":[]}' if "notarytool" in command else ""
        )
        return subprocess.CompletedProcess(command, 0, stdout=output_text)

    monkeypatch.setattr(release, "verify_distribution", fake_verify)
    artifacts = release.create_release(
        app,
        "arm64",
        key,
        "KEY123",
        "ISSUER123",
        "TEAM123",
        output,
        runner=runner,
    )

    assert verifications == [("developer-id", False), ("developer-id", True)]
    submit = next(command for command in calls if "submit" in command)
    assert submit[-5:] == [
        "--wait",
        "--timeout",
        "30m",
        "--output-format",
        "json",
    ]
    assert len([command for command in calls if "notarytool" in command]) == 2
    assert [command[:3] for command in calls if "stapler" in command] == [
        ["xcrun", "stapler", "staple"]
    ]
    expected = hashlib.sha256(b"signed-archive").hexdigest()
    assert artifacts.archive.read_bytes() == b"signed-archive"
    assert artifacts.checksum.read_text(encoding="ascii") == (
        f"{expected}  {artifacts.archive.name}\n"
    )


def test_release_rejects_nonaccepted_notarization(tmp_path: Path, monkeypatch) -> None:
    app, key, output = _release_inputs(tmp_path)
    monkeypatch.setattr(release, "verify_distribution", lambda *args, **kwargs: None)

    def runner(command, **kwargs):
        del kwargs
        command = list(command)
        if command[:2] == ["/usr/bin/ditto", "-c"]:
            Path(command[-1]).write_bytes(b"submission")
        response = '{"status":"Invalid","message":"private-key-sentinel"}'
        return subprocess.CompletedProcess(command, 0, stdout=response)

    with pytest.raises(RuntimeError, match="notarization was not accepted"):
        release.create_release(
            app,
            "arm64",
            key,
            "KEY123",
            "ISSUER123",
            "TEAM123",
            output,
            runner=runner,
        )

    assert not output.exists() or not tuple(output.glob("*.zip"))


def test_release_rejects_notary_log_with_issues(tmp_path: Path, monkeypatch) -> None:
    app, key, output = _release_inputs(tmp_path)
    monkeypatch.setattr(release, "verify_distribution", lambda *args, **kwargs: None)
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        command = list(command)
        calls.append(command)
        if command[:2] == ["/usr/bin/ditto", "-c"]:
            Path(command[-1]).write_bytes(b"submission")
        if "submit" in command:
            response = '{"id":"opaque","status":"Accepted"}'
        elif "log" in command:
            response = '{"status":"Accepted","issues":[{"severity":"error"}]}'
        else:
            response = ""
        return subprocess.CompletedProcess(command, 0, stdout=response)

    with pytest.raises(RuntimeError, match="log did not pass"):
        release.create_release(
            app,
            "arm64",
            key,
            "KEY123",
            "ISSUER123",
            "TEAM123",
            output,
            runner=runner,
        )

    assert not any("staple" in command for command in calls)


def test_release_main_sanitizes_notary_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    app, key, output = _release_inputs(tmp_path)

    def fail(*_args, **_kwargs):
        raise RuntimeError("private-key-sentinel")

    monkeypatch.setattr(release, "create_release", fail)
    result = release.main(
        [
            "--app",
            str(app),
            "--arch",
            "arm64",
            "--notary-key",
            str(key),
            "--notary-key-id",
            "KEY123",
            "--notary-issuer",
            "ISSUER123",
            "--team-id",
            "TEAM123",
            "--output-dir",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "private-key-sentinel" not in captured.err


def test_release_script_is_directly_executable() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/release_distribution.py"), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Notarize and archive" in result.stdout
