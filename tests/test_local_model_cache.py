"""Pinned model cache integrity and supported-runtime readiness."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from meeting_memory.repo import local_model_cache as cache
from meeting_memory.repo import local_models
from meeting_memory.types.local_transcription import LocalTranscriptionError


@pytest.fixture
def model_cache(tmp_path, monkeypatch):
    content = b"declared local model"
    item = cache.ModelFile("model.safetensors", len(content), hashlib.sha256(content).hexdigest())
    model = cache.LocalModel("owner/model", "a" * 40, (item,))
    snapshot = model.snapshot(tmp_path)
    snapshot.mkdir(parents=True)
    blobs = snapshot.parent.parent / "blobs"
    blobs.mkdir()
    blob = blobs / item.sha256
    blob.write_bytes(content)
    (snapshot / item.name).symlink_to(blob)
    monkeypatch.setattr(cache, "models", lambda: (model,))
    return tmp_path, model, snapshot, blob


def test_complete_standard_snapshot_links_are_reused_offline(model_cache):
    root, _model, snapshot, _blob = model_cache
    assert cache.validate_models(root) == (snapshot,)


def test_truncated_or_corrupt_weights_are_not_ready(model_cache):
    root, _model, _snapshot, blob = model_cache
    blob.write_bytes(b"wrong-sized data")
    with pytest.raises(LocalTranscriptionError, match="could not be verified"):
        cache.validate_models(root)
    blob.write_bytes(b"x" * len(b"declared local model"))
    with pytest.raises(LocalTranscriptionError):
        cache.validate_models(root)


def test_link_outside_declared_blob_store_is_rejected(model_cache, tmp_path):
    root, model, snapshot, _blob = model_cache
    outside = tmp_path / "outside"
    outside.write_bytes(b"declared local model")
    (snapshot / model.files[0].name).unlink()
    (snapshot / model.files[0].name).symlink_to(outside)
    with pytest.raises(LocalTranscriptionError):
        cache.validate_models(root)


def test_extra_pickle_code_or_weights_are_rejected(model_cache):
    root, _model, snapshot, _blob = model_cache
    (snapshot / "unexpected.py").write_text("not executable model data")
    with pytest.raises(LocalTranscriptionError):
        cache.validate_models(root)


def test_inspection_does_not_load_models_or_use_network(model_cache, monkeypatch):
    root, _model, _snapshot, _blob = model_cache
    monkeypatch.setattr(local_models.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_models.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(local_models.importlib.util, "find_spec", lambda _: object())
    report = local_models.inspect_local_backend(cache=root)
    assert report.supported and report.runtime_available and report.models_ready


@pytest.mark.parametrize("system,machine", [("Darwin", "x86_64"), ("Windows", "arm64")])
def test_unsupported_hardware_has_no_cloud_side_effect(system, machine, monkeypatch):
    monkeypatch.setattr(local_models.platform, "system", lambda: system)
    monkeypatch.setattr(local_models.platform, "machine", lambda: machine)
    report = local_models.inspect_local_backend()
    assert not report.supported and not report.models_ready
    assert "explicitly" in report.action


def test_preparation_warm_cache_never_starts_download_or_processes_meetings(
    model_cache, monkeypatch, tmp_path
):
    root, _model, _snapshot, _blob = model_cache
    monkeypatch.setattr(local_models.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_models.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(local_models.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(local_models, "run_local_worker", lambda *a, **k: pytest.fail("download"))
    events = []
    local_models.prepare_models(cache=root, progress=events.append)
    assert [event.phase for event in events] == ["checking", "ready"]


def test_preparation_download_failure_remains_actionable_and_unready(
    model_cache, monkeypatch, tmp_path
):
    root, _model, snapshot, blob = model_cache
    blob.unlink()
    monkeypatch.setattr(local_models.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_models.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(local_models.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def interrupted(*_args, **_kwargs):
        raise LocalTranscriptionError("Download interrupted.", "Check connection and retry.")

    monkeypatch.setattr(local_models, "run_local_worker", interrupted)
    with pytest.raises(LocalTranscriptionError, match="interrupted"):
        local_models.prepare_models(cache=root)
    assert not local_models.inspect_local_backend(cache=root).models_ready
    assert snapshot.is_dir()  # Cancellation/failure never removes shared cached paths.


def test_explicit_metal_probe_is_bounded_and_can_disable_local(model_cache, monkeypatch):
    root, _model, _snapshot, _blob = model_cache
    monkeypatch.setattr(local_models.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_models.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(local_models.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(local_models, "verify_local_runtime", lambda **_: False)
    report = local_models.inspect_local_backend(cache=root, probe_metal=True)
    assert not report.supported and not report.models_ready
    assert "Metal" in report.summary


def test_cancelled_readiness_probe_never_imports_or_reports_unsupported(monkeypatch):
    from meeting_memory.types.local_transcription import LocalTranscriptionCancelled

    monkeypatch.setattr(
        local_models.platform, "system", lambda: pytest.fail("cancelled probe inspected hardware")
    )
    with pytest.raises(LocalTranscriptionCancelled):
        local_models.inspect_local_backend(probe_metal=True, cancelled=lambda: True)
