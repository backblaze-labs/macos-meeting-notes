# Feature: Recording

## Purpose

Capture audio from the selected tray mode without changing macOS audio devices.
`Full Meeting` records system audio plus the current microphone; `Silent System
Only` records system audio with the microphone off and playback muted.

Recording is the local-first core and the only capability that gates first
value. Its composition and durable lifecycle are defined in
[`../local-first-contract.md`](../local-first-contract.md).

## Inputs

- Manual tray `Start Recording`
- Calendar notification `Record` action
- Manual tray `Stop Recording`
- Meeting-end notification `Stop` action
- Nearby calendar context or post-recording ad-hoc title prompt

## Outputs

- Current legacy runtime: temporary WAV in the system temp directory
- Accepted target: recoverable WAV in app-owned staging on the
  `MEETINGS_DIR` filesystem
- `recording.m4a` in the meeting directory
- Schema-v2 `transcript.md` metadata stub published atomically with the audio
- `MeetingMeta` passed to the pipeline
- Visible recording duration in the status bar and tray menu

## Threading

The tray action only schedules a single-flight background transition. Calendar
context lookup, native-helper startup/shutdown, and WAV-to-M4A conversion never
run on the main thread. A Swift subprocess performs capture and incremental WAV
writing; local commit and configured optional jobs also run in background
workers and emit typed events for the tray main thread to render.

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
  controller stops the active recording, atomically commits local artifacts,
  and starts only configured optional jobs.
- Interrupted temp WAV files without a matching M4A sibling appear in the tray
  as recovered recordings and can be processed by the user.
- The accepted target commits `recording.m4a` locally before starting any
  optional provider work. A missing or failed Transcription, Backup, Calendar,
  or Notes capability must not discard or hide the recording.
- The accepted target assembles audio plus metadata in a same-filesystem staging
  directory and publishes the complete meeting directory with one atomic
  rename. Legacy system-temp files are discovered locally once and never start
  provider work without an explicit recovery action.
- Private indexed capture sessions, component-wise no-follow discovery, and
  identity-safe post-commit cleanup now exist as inactive service primitives.
  Indexed WAV recovery uses an injected path-based converter with a verified
  private input snapshot. Both converted WAV and direct M4A recovery require a
  caller-supplied validator for a complete AAC-bearing M4A; the service has no
  weak signature fallback, and RIFF bytes are never relabeled as
  `recording.m4a`.
  Recorder startup/stop still follows the current legacy path until the atomic
  runtime cutover activates the complete flow together.

## Related Files

- `src/meeting_memory/service/recorder.py`
- `src/meeting_memory/service/recovery.py`
- `src/meeting_memory/service/recovery_index.py`
- `src/meeting_memory/service/recovery_audio.py`
- `src/meeting_memory/service/recovery_commit.py`
- `src/meeting_memory/service/recovery_cleanup.py`
- `src/meeting_memory/service/recording_context.py`
- `src/meeting_memory/ui/controller.py`
- `src/meeting_memory/ui/processing_launch.py`
- `src/meeting_memory/ui/recording_transitions.py`
- `src/meeting_memory/repo/native_audio.py`
- `src/meeting_memory/repo/native/NativeCapture.swift`
- `src/meeting_memory/ui/tray.py`
- `src/meeting_memory/ui/title_prompt.py`

## Tests

- `tests/test_recorder.py`
- `tests/test_native_audio.py`
- `tests/test_recovery.py`
- `tests/test_recovery_audio.py`
- `tests/test_recovery_receipt.py`
- `tests/test_tray.py`
- `tests/test_tray_recording_context.py`
- `tests/test_recording_context.py`
