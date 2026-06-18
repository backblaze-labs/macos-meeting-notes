# Feature: Recording

## Purpose

Capture local microphone plus routed meeting/system audio from the configured
macOS aggregate input device.

## Inputs

- `AUDIO_DEVICE`
- Manual tray `Start Recording`
- Calendar notification `Record` action
- Manual tray `Stop Recording`
- Meeting-end notification `Stop` action
- Nearby calendar context or ad-hoc title prompt

## Outputs

- Temporary WAV in the system temp directory
- `recording.m4a` in the meeting directory
- `MeetingMeta` passed to the pipeline
- Visible recording duration in the status bar and tray menu

## Threading

The tray action runs on the main thread. Recording uses a `sounddevice`
callback created through `repo/audio_device.py`; the post-recording pipeline is
started on a background thread.

## Behavior Notes

- The recorder opens the configured aggregate input device and downmixes all
  input channels to mono.
- Manual starts use a nearby calendar event title when one is available within
  the recording-context window.
- If no calendar context is available, the tray UI prompts for a title before
  starting.
- A calendar-backed recording can emit a `Stop` reminder at the event end time;
  it does not fully auto-record meetings.
- `MAX_RECORDING_MINUTES` is enforced as a hard safety limit. When reached, the
  controller stops the active recording and starts the normal pipeline.
- Interrupted temp WAV files without a matching M4A sibling appear in the tray
  as recovered recordings and can be processed by the user.

## Related Files

- `src/meeting_memory/service/recorder.py`
- `src/meeting_memory/service/recovery.py`
- `src/meeting_memory/service/recording_context.py`
- `src/meeting_memory/ui/controller.py`
- `src/meeting_memory/repo/audio_device.py`
- `src/meeting_memory/ui/tray.py`
- `src/meeting_memory/ui/title_prompt.py`

## Tests

- `tests/test_recorder.py`
- `tests/test_recovery.py`
- `tests/test_tray.py`
- `tests/test_tray_recording_context.py`
- `tests/test_recording_context.py`
