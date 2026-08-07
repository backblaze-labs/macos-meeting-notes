# Feature: Recording

## Purpose

Capture audio from the selected tray mode without changing macOS audio devices.
`Full Meeting` records system audio plus the current microphone; `Silent System
Only` records system audio with the microphone off and playback muted.

## Inputs

- Manual tray `Start Recording`
- Calendar notification `Record` action
- Manual tray `Stop Recording`
- Meeting-end notification `Stop` action
- Nearby calendar context or post-recording ad-hoc title prompt

## Outputs

- Temporary WAV in the system temp directory
- `recording.m4a` in the meeting directory
- `MeetingMeta` passed to the pipeline
- Visible recording duration in the status bar and tray menu

## Threading

The tray action runs on the main thread. A Swift subprocess performs native
capture and incremental WAV writing; the post-recording pipeline is started on
a background thread.

## Behavior Notes

- The helper resamples and downmixes native streams into a 16 kHz mono WAV.
- The tray exposes audio modes for the next recording:
  - `Full Meeting` captures system audio and the current default microphone
    while the user keeps hearing the meeting through the current output.
  - `Silent System Only` captures system audio, never enables microphone
    capture, and mutes tapped playback for the recording's lifetime.
- Neither mode changes the system's selected input or output device.
- macOS prompts for Microphone and Screen & System Audio permissions when the
  relevant mode first needs them.
- Audio mode changes are rejected while a recording is active.
- Manual starts use a nearby calendar event title when one is available within
  the recording-context window.
- If no calendar context is available, recording starts with a provisional
  title and the tray UI prompts for the final title after recording stops.
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
- `src/meeting_memory/repo/native_audio.py`
- `src/meeting_memory/repo/native/NativeCapture.swift`
- `src/meeting_memory/ui/tray.py`
- `src/meeting_memory/ui/title_prompt.py`

## Tests

- `tests/test_recorder.py`
- `tests/test_native_audio.py`
- `tests/test_recovery.py`
- `tests/test_tray.py`
- `tests/test_tray_recording_context.py`
- `tests/test_recording_context.py`
