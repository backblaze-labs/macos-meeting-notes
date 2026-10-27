"""Local process admission, cancellation, and secret inheritance boundaries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

import pytest

from meeting_memory.repo.local_process import child_environment, local_operation_lock
from meeting_memory.repo.local_worker import read_request
from meeting_memory.types.local_transcription import LocalTranscriptionCancelled


@pytest.mark.parametrize("offline", [False, True])
def test_children_do_not_inherit_any_parent_provider_tokens(monkeypatch, offline):
    sentinels = {
        "ASSEMBLYAI_API_KEY": "sentinel-assembly",
        "ANTHROPIC_API_KEY": "sentinel-anthropic",
        "AWS_SECRET_ACCESS_KEY": "sentinel-b2",
        "HF_TOKEN": "sentinel-hf",
        "SECRET_UNKNOWN_TO_APP": "sentinel-unexpected",
        "PYTHONSTARTUP": "sentinel-hook",
        "HTTPS_PROXY": "sentinel-proxy",
    }
    for key, value in sentinels.items():
        monkeypatch.setenv(key, value)
    environment = child_environment(offline=offline)
    assert all(key not in environment for key in sentinels)
    assert environment["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"
    assert environment.get("HF_HUB_OFFLINE") == ("1" if offline else None)
    result = subprocess.run(
        [sys.executable, "-c", "import json,os; print(json.dumps(dict(os.environ)))"],
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    actual = json.loads(result.stdout)
    assert all(key not in actual for key in sentinels)


def test_cancel_waiting_for_cross_instance_lock_never_enters_operation(tmp_path):
    path = tmp_path / "operation.lock"
    cancel = threading.Event()
    with local_operation_lock(progress=lambda _: None, cancelled=lambda: False, lock_path=path):
        with pytest.raises(LocalTranscriptionCancelled):
            with local_operation_lock(
                progress=lambda _: cancel.set(), cancelled=cancel.is_set, lock_path=path
            ):
                pytest.fail("waiting operation acquired busy lock")
    # flock releases on closing the descriptor even after cancellation.
    with local_operation_lock(progress=lambda _: None, cancelled=lambda: False, lock_path=path):
        assert path.stat().st_mode & 0o777 == 0o600


def test_lock_symlink_is_rejected(tmp_path):
    target = tmp_path / "other"
    target.write_text("unrelated")
    path = tmp_path / "lock"
    path.symlink_to(target)
    with pytest.raises(OSError):
        with local_operation_lock(progress=lambda _: None, cancelled=lambda: False, lock_path=path):
            pytest.fail("followed a lock symlink")
    assert target.read_text() == "unrelated"


def test_download_request_cannot_carry_audio_or_unrecognized_fields(tmp_path):
    os.chmod(tmp_path, 0o700)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"operation": "prepare", "cache": str(tmp_path), "audio": "bad"}))
    request.chmod(0o600)
    with pytest.raises(ValueError, match="schema"):
        read_request(request)


def test_worker_rejects_public_or_symlinked_request(tmp_path):
    os.chmod(tmp_path, 0o700)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"operation": "prepare", "cache": str(tmp_path)}))
    request.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        read_request(request)
    request.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(request)
    with pytest.raises(ValueError):
        read_request(link)
