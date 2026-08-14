# Feature: Recording

## Purpose

Capture audio from the selected tray mode without changing macOS audio devices.
`Full Meeting` records system audio plus the current microphone; `Silent System
Only` records system audio with the microphone off and playback muted.

Recording is the local-first core. Complete B2 configuration is also required
to leave setup, while live B2 reachability never gates local commit. Its
composition and durable lifecycle are defined in
[`../local-first-contract.md`](../local-first-contract.md).

## Inputs

- Manual tray `Start Recording`
- Calendar notification `Record` action
- Manual tray `Stop Recording`
- Meeting-end notification `Stop` action
- Nearby calendar context or post-recording ad-hoc title prompt

## Outputs

- Recoverable WAV in a unique private indexed session on the `MEETINGS_DIR`
  filesystem
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
- WAV-to-M4A conversion prefers AVFoundation. Hosts without an AudioToolbox AAC
  encoder use `MeetingMemoryFFmpegAudioEncoder`, a separate minimal LGPL
  FFmpeg build whose network support and unrelated formats are disabled. The
  Swift helper supplies one fixed conversion command; it never accepts
  arbitrary encoder options or uses a system/Homebrew FFmpeg.
- The tray exposes audio modes for the next recording:
  - `Full Meeting` captures system audio and the current default microphone
    while the user keeps hearing the meeting through the current output.
  - `Silent System Only` captures system audio, never enables microphone
    capture, and mutes tapped playback for the recording's lifetime.
- Neither mode changes the system's selected input or output device.
- macOS prompts for Microphone and Screen & System Audio permissions when the
  relevant mode first needs them.
- Readiness checks inspect the current permission status without prompting and
  evaluate only the selected mode. Silent System Only therefore does not need a
  microphone; Full Meeting becomes ready when both permissions and a default
  input device are available.
- Audio mode changes are rejected while a recording is active.
- Manual starts use a nearby calendar event title when one is available within
  the recording-context window.
- If no calendar context is available, recording starts with a provisional
  title and the tray UI prompts for the final title after recording stops.
- A calendar-backed recording can emit a `Stop` reminder at the event end time;
  it does not fully auto-record meetings.
- An active recording emits a `Stop` reminder after one hour and every 30
  minutes after that. Reminders stop with the recording and do not duplicate
  the notification at the configured auto-stop boundary.
- `MAX_RECORDING_MINUTES` is enforced as a hard safety limit. When reached, the
  controller stops the active recording, atomically commits local artifacts,
  and starts only configured optional jobs.
- The native helper also watches the exact parent process that launched it. If
  the app exits or crashes, the helper stops within roughly one second and
  finalizes the staging WAV instead of continuing as an orphan. An independent
  native watchdog stops capture 30 seconds after the configured limit if the
  controller is alive but unable to perform its normal stop.
- Interrupted indexed WAV files appear in the tray as recovered recordings and
  can be committed by the user. Recovery never starts transcription or backup
  until the user explicitly selects that recording.
- The runtime commits `recording.m4a` locally before starting any
  optional provider work. A missing or failed Transcription, Backup, Calendar,
  or Notes capability must not discard or hide the recording.
- It assembles audio plus metadata in a same-filesystem staging
  directory and publishes the complete meeting directory with one atomic
  rename. **Debugging › Find Legacy Recordings...** can scan legacy system-temp
  files once, but normal launch never scans them or starts provider work for
  them.
- MeetingStore pins the stage directory and materialized audio before invoking
  the path-based native validator. Whole-stage or child replacement is rejected
  by identity, size, and digest checks before rename, and the same exact objects
  are checked again at the published destination before a cleanup receipt can
  be issued.
- Private indexed capture sessions, component-wise no-follow discovery, and
  identity-safe post-commit cleanup are active in the runtime.
  Indexed WAV recovery uses an injected path-based converter with a verified
  private input snapshot. Both converted WAV and direct M4A recovery require a
  caller-supplied validator for a complete AAC-bearing M4A; the service has no
  weak signature fallback, and RIFF bytes are never relabeled as
  `recording.m4a`. The native validator inherits a read-only descriptor for the
  exact pinned candidate, copies those bytes to a private 0600 temporary M4A so
  AVFoundation can inspect them, and deletes the copy before returning. The
  store revalidates identity, size, and digest across that boundary. Python owns
  and cleans the helper's private temporary directory even if the helper times
  out. Declared packet sizes are capped, packet counts must fit the audio byte
  count and integer range, and the subprocess has a fixed timeout so corrupt
  recovery input cannot consume unbounded memory or block a commit indefinitely.
- A capture starter failure removes its private session only when the WAV is
  absent or an empty regular file. Any nonempty source remains indexed for
  recovery. Already pinned source provenance is never refreshed at commit, so
  inode replacement or same-inode byte mutation is rejected.
- A visible publication whose parent fsync is uncertain is not announced as a
  saved recording and starts no optional work. Its pre-publication journal token
  identifies the exact visible directory; explicit reconciliation verifies and
  fsyncs it without creating a collision suffix before normal completion
  continues.

## Related Files

- `src/meeting_memory/service/recorder.py`
- `src/meeting_memory/service/recovery.py`
- `src/meeting_memory/service/recovery_index.py`
- `src/meeting_memory/service/recovery_audio.py`
- `src/meeting_memory/service/recovery_commit.py`
- `src/meeting_memory/service/recovery_cleanup.py`
- `src/meeting_memory/service/recovery_reconcile.py`
- `src/meeting_memory/service/runtime_legacy_recovery.py`
- `src/meeting_memory/service/recording_context.py`
- `src/meeting_memory/ui/controller.py`
- `src/meeting_memory/ui/processing_launch.py`
- `src/meeting_memory/ui/recording_transitions.py`
- `src/meeting_memory/repo/native_audio.py`
- `src/meeting_memory/repo/native_audio_build.py`
- `src/meeting_memory/repo/native/NativeCapture.swift`
- `src/meeting_memory/repo/native/RecordingLifetime.swift`
- `src/meeting_memory/ui/tray.py`
- `src/meeting_memory/ui/title_prompt.py`

## Tests

- `tests/test_recorder.py`
- `tests/test_native_audio.py`
- `tests/test_native_recording_lifetime.py`
- `tests/test_recovery.py`
- `tests/test_recovery_audio.py`
- `tests/test_recovery_receipt.py`
- `tests/test_tray.py`
- `tests/test_tray_recording_context.py`
- `tests/test_recording_context.py`
