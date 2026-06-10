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
