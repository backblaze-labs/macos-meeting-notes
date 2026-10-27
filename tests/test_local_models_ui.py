"""Nonmodal preparation controls and factual model progress on the UI thread."""

from types import SimpleNamespace

from meeting_memory.types.events import TranscriptionFailed, TranscriptionProgress
from meeting_memory.types.local_model_preparation import LocalModelState, LocalModelsUpdated
from meeting_memory.types.local_transcription import LocalBackendStatus, LocalModelProgress
from meeting_memory.types.meeting import MeetingRef
from meeting_memory.ui.local_models import LocalModelsUI, progress_fraction


class Coordinator:
    busy = False

    def __init__(self):
        self.calls = []

    def check(self):
        self.calls.append("check")
        return "current"

    def prepare(self):
        self.calls.append("prepare")
        self.busy = True
        return "current"

    def cancel(self):
        self.calls.append("cancel")
        return True

    def is_current(self, operation_id):
        return operation_id == "current"


class Panel:
    def __init__(self, _prepare, _cancel):
        self.updates = []
        self.shown = 0

    def show(self):
        self.shown += 1

    def update(self, **kwargs):
        self.updates.append(kwargs)


def test_open_only_checks_prepare_is_separate_and_cancel_is_nonmodal():
    coordinator = Coordinator()
    ui = LocalModelsUI(lambda _: None, object(), coordinator=coordinator, panel_factory=Panel)
    assert coordinator.calls == []
    ui.open()
    assert coordinator.calls == ["check"]
    assert ui._panel.shown == 1
    ui.prepare()
    assert coordinator.calls == ["check", "prepare"]
    assert ui._panel.updates[-1]["busy"]
    ui.cancel()
    assert coordinator.calls[-1] == "cancel"
    assert "Cancelling" in ui._panel.updates[-1]["summary"]


def test_stale_status_ignored_and_unsupported_disables_preparation():
    coordinator = Coordinator()
    ui = LocalModelsUI(lambda _: None, object(), coordinator=coordinator, panel_factory=Panel)
    ui.open()
    before = len(ui._panel.updates)
    stale = LocalModelsUpdated("old", LocalModelState.READY, "stale")
    assert ui.handle_event(stale)
    assert len(ui._panel.updates) == before
    unsupported = LocalBackendStatus(False, False, False, "Unsupported Mac.", "Use arm64.")
    ui.handle_event(
        LocalModelsUpdated(
            "current",
            LocalModelState.AVAILABLE,
            unsupported.summary,
            unsupported.action,
            unsupported,
        )
    )
    assert not ui._panel.updates[-1]["prepare_enabled"]
    assert ui._panel.updates[-1]["details"] == "Use arm64."


def test_progress_uses_only_valid_measured_bytes():
    assert progress_fraction(LocalModelProgress("download", "Downloading.")) is None
    assert progress_fraction(LocalModelProgress("download", "Downloading.", 5, 0)) is None
    assert progress_fraction(LocalModelProgress("download", "Downloading.", -1, 100)) is None
    assert progress_fraction(LocalModelProgress("download", "Downloading.", 101, 100)) is None
    assert progress_fraction(LocalModelProgress("download", "Downloading.", 25, 100)) == 0.25


def test_runtime_progress_updates_menu_without_opening_panel(tmp_path):
    coordinator = Coordinator()
    changes = []
    ui = LocalModelsUI(
        lambda _: None,
        object(),
        coordinator=coordinator,
        panel_factory=lambda *_: (_ for _ in ()).throw(AssertionError("panel")),
        on_change=lambda: changes.append(True),
    )
    meeting = MeetingRef("sample", "Sample", tmp_path)
    progress = TranscriptionProgress(
        meeting, LocalModelProgress("recognizing", "Recognizing speech.")
    )
    assert ui.handle_runtime_event(progress)
    assert "Recognizing speech" in ui.progress_label
    assert not ui.handle_runtime_event(TranscriptionFailed(meeting))
    assert ui.progress_label is None
    assert len(changes) == 2
    assert not ui.handle_runtime_event(SimpleNamespace())


def test_effective_provider_is_visible_without_startup_inspection():
    coordinator = Coordinator()
    ui = LocalModelsUI(lambda _: None, object(), coordinator=coordinator, provider="assemblyai")
    assert ui.progress_label == "Transcription provider: AssemblyAI (external)"
    assert coordinator.calls == []
