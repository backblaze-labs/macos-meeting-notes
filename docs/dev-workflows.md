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

## Useful Commands

```bash
make doctor
meeting-memory auth
meeting-memory
```

`meeting-memory` starts the tray process. Stop it from the tray menu with
`Quit`.
