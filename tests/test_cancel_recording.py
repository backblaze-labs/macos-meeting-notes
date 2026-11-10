"""Confirmed cancellation discards capture without publishing it."""
from pathlib import Path
from unittest.mock import Mock

from test_recorder import FakeCapture

from meeting_memory.service.recorder import RecorderService


def test_cancel_removes_only_active_capture_without_conversion(tmp_path: Path):
    def start(mode, path):
        capture = FakeCapture(mode, path)
        capture.write_audio()
        return capture
    converter = Mock()
    recorder = RecorderService(temp_dir=tmp_path, capture_starter=start, converter=converter)
    session = recorder.start('Discard me')
    unrelated = tmp_path / 'keep.txt'
    unrelated.write_text('keep')
    assert recorder.cancel(session) is True
    assert not recorder.is_recording
    assert not session.recovery.session_directory.exists()
    assert unrelated.read_text() == 'keep'
    converter.assert_not_called()
    assert recorder.cancel(session) is False
    next_session = recorder.start('Keep me')
    assert recorder.cancel(session) is False
    assert recorder.active_session is next_session
    recorder.cancel(next_session)


def test_confirmation_keeps_recording_unless_discard_is_chosen():
    from types import SimpleNamespace

    from tray_fakes import FakeRumps

    from meeting_memory.ui.status_menu import cancel_active_recording

    session = object()
    controller = SimpleNamespace(
        recorder=SimpleNamespace(active_session=session), cancel_recording=Mock()
    )
    rumps = FakeRumps()
    app = SimpleNamespace(controller=controller, rumps=rumps, refresh_sidebar=Mock())
    cancel_active_recording(app)
    controller.cancel_recording.assert_not_called()
    rumps.alert_response = 0
    cancel_active_recording(app)
    controller.cancel_recording.assert_called_once_with(session)


def test_controller_cancel_never_publishes_or_queues_processing(tmp_path):
    from test_tray import ImmediateThread, _settings

    from meeting_memory.ui.controller import TrayController

    def start(mode, path):
        capture = FakeCapture(mode, path)
        capture.write_audio()
        return capture

    recorder = RecorderService(temp_dir=tmp_path, capture_starter=start)
    session = recorder.start("Discard")
    pipeline, committer = Mock(), Mock()
    controller = TrayController(
        settings=_settings(tmp_path), recorder=recorder,
        pipeline=pipeline, committer=committer, thread_factory=ImmediateThread,
    )
    controller.cancel_recording(session)
    assert not recorder.is_recording
    assert not session.wav_path.exists()
    pipeline.process.assert_not_called()
    committer.commit.assert_not_called()
    assert not any(type(event).__name__ == "RecordingTitleNeeded"
                   for event in controller.drain_events())
