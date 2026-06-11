# Feature: Recording

## Purpose

Capture local microphone plus routed meeting/system audio from the configured
macOS aggregate input device.

## Inputs

- `AUDIO_DEVICE`
- Manual tray `Start Recording`
- Manual tray `Stop Recording`

## Outputs

- Temporary WAV in the system temp directory
- `recording.m4a` in the meeting directory
- `MeetingMeta` passed to the pipeline

## Threading

The tray action runs on the main thread. Recording uses a `sounddevice`
callback created through `repo/audio_device.py`; the post-recording pipeline is
started on a background thread.

## Related Files

- `src/meeting_memory/service/recorder.py`
- `src/meeting_memory/repo/audio_device.py`
- `src/meeting_memory/ui/tray.py`

## Tests

- `tests/test_recorder.py`
- `tests/test_tray.py`
