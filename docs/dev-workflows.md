# Development Workflows

## Local Setup

```bash
make setup
make doctor
```

## Checks

- `make check:structure`: repository architecture checks.
- `make test`: all tests.
- `make lint`: Ruff linting.
- `make check`: full deterministic gate with fakes, no GPU, model weights, or
  network required.
- `make check-local-transcription`: explicit real-audio Apple Silicon
  integration; see the example below.

## App Validation

Use [manual-validation.md](manual-validation.md) for a real credentialed run.
The automated test suite uses fakes and mocks for external services; it does not
spend API credits or require local audio hardware.

### Local Transcription Hardware Check

Prepare models explicitly from the native app, then run with an English or
Spanish M4A sample and a private output directory:

```bash
make PYTHON=.venv/bin/python check-local-transcription \
  LOCAL_CHECK_ARGS='"/path/to/recording.m4a" --expected-language es --helper .build/MeetingMemoryCapture --output /path/to/private-results/result.json'
```

Use `--expected-language en` for English. This exercises native mono 16 kHz
PCM decoding and pinned offline model inference without system FFmpeg. Keep
recordings and generated evidence outside Git. Doctor does not download or
load weights, and preparation does not process pending meetings. The separate
**Retry Pending or Failed Transcriptions** action confirms the provider before
processing history.

## Local macOS App

During development, prefer the generated local app bundle for real notification
and menu-bar behavior:

```bash
make PYTHON=.venv/bin/python install-macos-app
make PYTHON=.venv/bin/python open-macos-app
```

After changing app code or assets, reload the bundle:

```bash
make PYTHON=.venv/bin/python reload-macos-app
```

The bundle lives at `~/Applications/Meeting Memory.app`. It wraps this checkout
and virtualenv; it is not a signed, notarized, standalone build. Native
Configuration writes app-owned preferences and Keychain references, never
`.env`. Restart or reload when a saved form says the changed setting takes
effect after relaunch.

To stop a running app process without using the tray menu:

```bash
make PYTHON=.venv/bin/python quit-macos-app
```

## Login Item

Install the LaunchAgent when validating startup-at-login behavior:

```bash
make PYTHON=.venv/bin/python install-launch-agent
```

It writes `~/Library/LaunchAgents/com.meeting-memory.app.plist`, starts the app
in the background by opening `~/Applications/Meeting Memory.app` through
LaunchServices, and keeps opener stdout/stderr under
`~/Library/Logs/meeting-memory/launch-agent.*.log`. App logs are written to
`~/Library/Logs/meeting-memory/app.log`.

Remove it after validation unless you want Meeting Memory to keep starting at
login:

```bash
make PYTHON=.venv/bin/python uninstall-launch-agent
```

## Useful Commands

```bash
make setup
make doctor
.venv/bin/meeting-memory auth
.venv/bin/meeting-memory
.venv/bin/meeting-memory search "launch risks"
make PYTHON=.venv/bin/python install-macos-app
make PYTHON=.venv/bin/python reload-macos-app
make PYTHON=.venv/bin/python install-launch-agent
make PYTHON=.venv/bin/python uninstall-launch-agent
```

`meeting-memory` starts the tray process. Stop it from the tray menu with
`Quit`.

The tray's **Debugging** submenu exposes `Retry Pending B2 Backups`, `Retry
Pending or Failed Transcriptions`, `Check Setup & Dependencies`, and `Test macOS
Notifications` for local validation without adding new CLI commands.
