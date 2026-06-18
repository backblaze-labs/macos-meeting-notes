# Development Workflows

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
make doctor
```

## Checks

- `make check:structure`: repository architecture checks.
- `make test`: all tests.
- `make lint`: Ruff linting.
- `make check`: full gate.

## App Validation

Use [manual-validation.md](manual-validation.md) for a real credentialed run.
The automated test suite uses fakes and mocks for external services; it does not
spend API credits or require local audio hardware.

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
and virtualenv; it is not a signed, notarized, standalone build. After changing
`.env` through Preferences, restart or reload the app so the process reads the
new values.

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
in the background, and sends stdout/stderr to
`~/Library/Logs/meeting-memory/launch-agent.*.log`.

Remove it after validation unless you want Meeting Memory to keep starting at
login:

```bash
make PYTHON=.venv/bin/python uninstall-launch-agent
```

## Useful Commands

```bash
make doctor
meeting-memory auth
meeting-memory
meeting-memory search "launch risks"
make PYTHON=.venv/bin/python install-macos-app
make PYTHON=.venv/bin/python reload-macos-app
make PYTHON=.venv/bin/python install-launch-agent
make PYTHON=.venv/bin/python uninstall-launch-agent
```

`meeting-memory` starts the tray process. Stop it from the tray menu with
`Quit`.

The tray menu also exposes `Sync to B2`, `Retry Failed Processing`, `Run
Diagnostics`, and `Send Test Notification` for local validation without adding
new CLI commands.
