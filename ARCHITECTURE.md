# Architecture

`macos-meeting-notes` is the repository for **Meeting Memory**, a Python
macOS menu bar application with strict layers under `src/meeting_memory/`.

The external repository/distribution name is `macos-meeting-notes`. The app name
remains `Meeting Memory`, the import package remains `meeting_memory`, and the
CLI remains `meeting-memory`.

## Layers

```text
types <- config <- repo <- service <- ui
```

| Layer | Package | Responsibility |
| --- | --- | --- |
| types | `types/` | Pure data models and UI event objects. |
| config | `config/` | Settings loading and fail-fast validation. |
| repo | `repo/` | External service and hardware adapters. |
| service | `service/` | Local behavior and orchestration. |
| ui | `ui/` | `rumps` tray UI and menu handling. |

Cross-cutting modules live directly under `meeting_memory`: `__main__.py`,
`doctor.py`, and `logging_config.py`.

## Native Audio Boundary

`repo/native/` contains a small Swift helper compiled during setup and copied
inside `Meeting Memory.app`. Python starts it as a subprocess and receives
newline-delimited lifecycle events through `repo/native_audio.py`.

- **Full Meeting** uses ScreenCaptureKit to capture system audio and the current
  default microphone without changing macOS input or output routing.
- **Silent System Only** uses a Core Audio process tap with muted playback. It
  captures system audio, excludes the microphone, and leaves the selected audio
  devices unchanged.
- The helper aligns and mixes captured streams into an incremental 16 kHz mono
  WAV. The same helper converts the completed WAV to M4A through AVFoundation.

This boundary intentionally avoids virtual audio drivers, Aggregate Devices,
`sounddevice`, and `ffmpeg`.

## Boundary Rules

- Modules may import from their own layer or a lower layer only.
- External SDK imports are contained to `repo/`.
- `rumps` imports are contained to `ui/`.
- Background workers communicate with the UI through `types/events.py` objects
  and a thread-safe queue.
- Source files stay at or below 300 lines.

These rules are enforced by `tests/test_structure.py`.

## Threading Model

- Main thread: tray UI and notifications.
- Calendar watcher: daemon poll loop.
- Native audio helper: ScreenCaptureKit/Core Audio capture callbacks and WAV
  writing in a separate process.
- Pipeline: one worker per recording session.

Background threads must not call UI APIs directly. They emit events, and the UI
drains those events on the main thread.
