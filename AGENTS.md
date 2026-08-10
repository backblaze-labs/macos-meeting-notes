# AGENTS.md

This is the read-first control surface for coding agents working on
`macos-meeting-notes`, the repository for the **Meeting Memory** macOS
app.

Naming boundaries:

- Repository/distribution metadata: `macos-meeting-notes`
- Visible macOS app name: `Meeting Memory`
- Python import package: `meeting_memory`
- CLI command: `meeting-memory`
- macOS bundle ID, Keychain service, LaunchAgent label, and log paths keep their
  existing `meeting-memory` identifiers unless a future migration explicitly
  changes them.

## Read Order

1. `AGENTS.md`
2. `SPEC.md`
3. `docs/local-first-contract.md` for capability composition, readiness,
   local artifact lifecycle, configuration migration, or onboarding work
4. `ARCHITECTURE.md`
5. `docs/deferred-work.md` when revisiting unresolved or partially implemented
   behavior
6. `docs/features/<feature>.md` when working on a specific feature

## Repository Map

- `src/meeting_memory/types/`: pure boundary data, including capability and
  progressive-configuration provenance types. No SDK imports and no
  cross-layer imports.
- `src/meeting_memory/config/`: validated runtime settings plus the typed
  schema, pure precedence resolver, and secret-payload codec used by the
  Phase 4B service composition boundary.
- `src/meeting_memory/repo/`: external adapters. This is the only layer allowed
  to import external SDKs such as `boto3`, `assemblyai`, `anthropic`,
  `googleapiclient`, `google_auth_oauthlib`, `google`, `keyring`, or
  `sounddevice`. The generic Keychain adapter reads and writes immutable
  generations; preferences activate only opaque references.
- `src/meeting_memory/service/`: orchestration, local behavior, and capability
  readiness. The private atomic preference store and fixed-scope composed
  configuration loader also live here. No SDKs and no `rumps`.
- `src/meeting_memory/ui/`: tray UI. This is the only layer allowed to import
  `rumps`.
- `src/meeting_memory/doctor.py`: preflight checks that can run before optional
  dependencies are installed.

## Layer Invariants

Import direction is:

```text
types <- config <- repo <- service <- ui
```

A module may import from its own layer or a lower layer only. Cross-cutting
entrypoints (`__main__.py`, `doctor.py`, `logging_config.py`) may import config,
repo, or service modules as needed.

## Commands

- `make setup`: create/update `.venv`, install dependencies, create `.env` if
  missing, install the local macOS app wrapper, and print setup diagnostics.
- `make install`: install the package and developer tools.
- `make run`: run the current application entrypoint.
- `make auth`: run the explicit Google Calendar auth flow.
- `make doctor`: run preflight checks.
- `make install-macos-app`: install the clickable app bundle at
  `~/Applications/Meeting Memory.app`.
- `make reload-macos-app`: install/update the official app bundle, quit the
  running official app, and reopen it.
- `make lint`: run Ruff.
- `make format`: format with Ruff.
- `make test`: run all tests.
- `make check:structure`: run structural enforcement tests.
- `make check`: run the full gate.

## Quality Bar

- Keep implementation scoped to the relevant requirement, feature document, or
  deferred-work note.
- Keep source files at or under 300 lines.
- Add or update structural tests when adding source modules or changing layer
  boundaries.
- Prefer typed boundary objects over raw dictionaries when crossing layers.
- Never commit real credentials, `.env`, OAuth tokens, or local meeting data.
- Do not add `Co-Authored-By` lines to commit messages.

## Change Workflow

1. Read the relevant spec and plan sections.
2. Inspect existing code before editing.
3. Make the smallest coherent change.
4. Run the strongest available check, usually `make check`.
5. After app behavior changes, run `make reload-macos-app` with the project
   virtualenv Python so the official clickable app is updated and restarted.
6. If requested behavior is not implemented or is only partially implemented,
   append the reason and future first-check guidance to `docs/deferred-work.md`.
7. Commit a passing, reviewable slice.

## Official macOS App

- The user expects the app to be clickable and searchable with Cmd+Space as
  `Meeting Memory`.
- Treat `~/Applications/Meeting Memory.app` as the official local app bundle.
- After making any change to the app, update the official bundle and restart it
  with `make PYTHON=.venv/bin/python reload-macos-app`.
