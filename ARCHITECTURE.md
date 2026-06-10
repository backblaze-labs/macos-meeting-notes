# Architecture

`meeting-memory` is a Python macOS menu bar application with strict layers under
`src/meeting_memory/`.

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
- Recorder: audio capture callback.
- Pipeline: one worker per recording session.

Background threads must not call UI APIs directly. They emit events, and the UI
drains those events on the main thread.
