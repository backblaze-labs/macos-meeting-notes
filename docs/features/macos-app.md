# Feature: Local macOS App

## Purpose

Install and run Meeting Memory as a clickable menu-bar app from the current
checkout, with an optional LaunchAgent for startup at login.

## Inputs

- Current project directory
- Python executable, usually `.venv/bin/python`
- `src/meeting_memory/service/assets/MeetingMemory.icns`

## Outputs

- `~/Applications/Meeting Memory.app`
- `~/Library/LaunchAgents/com.meeting-memory.app.plist`
- Logs under `~/Library/Logs/meeting-memory/`

## Commands

```bash
make PYTHON=.venv/bin/python install-macos-app
make PYTHON=.venv/bin/python reload-macos-app
make PYTHON=.venv/bin/python open-macos-app
make PYTHON=.venv/bin/python quit-macos-app
make PYTHON=.venv/bin/python install-launch-agent
make PYTHON=.venv/bin/python uninstall-launch-agent
```

## Behavior Notes

- The `.app` is a generated local wrapper around this repo and virtualenv.
- The app uses `LSUIElement`, so it appears as a menu-bar app rather than a
  regular Dock app.
- The wrapper sets `PYTHONPATH=src` and runs `python -m meeting_memory`.
- It is not signed, notarized, or standalone.
- After changing code, assets, or `.env`, use `reload-macos-app` or quit and
  reopen the app.

## Related Files

- `src/meeting_memory/service/macos_app.py`
- `src/meeting_memory/service/launch_agent.py`
- `src/meeting_memory/service/assets/MeetingMemory.icns`
- `src/meeting_memory/__main__.py`
- `Makefile`

## Tests

- `tests/test_macos_app.py`
- `tests/test_launch_agent.py`
