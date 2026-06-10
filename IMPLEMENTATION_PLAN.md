# Implementation Plan

This plan turns `SPEC.md` into a sequence of small, verifiable milestones. The goal is to make the build process robust for both humans and AI coding agents: every milestone should leave the repository in a coherent state, with tests or checks that prove the work did not break the architecture.

## Working Rules

- Treat `SPEC.md` as the source of product requirements.
- Treat this file as the delivery checklist.
- Keep each milestone small enough to review and commit independently.
- Prefer tests and mechanical checks before real external-service integration.
- Preserve the layer boundaries from `SPEC.md` Section 7.5.
- Run the strongest available check before finishing each milestone.

## Milestone 0: Repository Harness

Purpose: create the project skeleton and enforcement rails before feature work begins.

Deliverables:

- `pyproject.toml` with PEP 621 metadata, src layout, dependencies, and console entrypoint.
- `src/meeting_memory/` package tree from `SPEC.md` Section 7.4.
- Required empty or minimal modules for `types`, `config`, `repo`, `service`, and `ui`.
- `tests/test_structure.py` enforcing:
  - downward-only imports,
  - external SDK imports only under `repo/`,
  - `rumps` imports only under `ui/`,
  - max source file length,
  - required modules exist.
- `AGENTS.md`, `CLAUDE.md`, and `ARCHITECTURE.md`.
- `Makefile` with predictable commands.
- `.env.example`, `.gitignore`, `requirements.txt`, docs stubs.

Exit criteria:

- `pytest tests/test_structure.py` passes.
- `python -m meeting_memory.doctor` is importable/runnable in its initial form.
- The repo has a clear read order for future agents.

## Milestone 1: Local Core

Purpose: implement the pure local behavior with no real external APIs.

Deliverables:

- Data models for meetings, transcripts, summaries, and UI events.
- Settings loading and fail-fast validation.
- Meeting slug helpers.
- Markdown renderer for `meeting.md`.
- Local storage writer/reader for meeting directories.
- Frontmatter read/update behavior for B2 status fields.
- Tests for models, markdown rendering, storage, and config validation.

Exit criteria:

- Local meeting artifacts can be generated from fake transcript and summary data.
- No network, audio, tray, or external SDK behavior is required.
- `make check` or the closest available equivalent passes.

## Milestone 2: Pipeline With Fakes

Purpose: prove the orchestration flow using test doubles before integrating services.

Deliverables:

- Pipeline orchestration for:
  - audio copy/write,
  - transcription,
  - summarization,
  - `meeting.md` write,
  - completion event emission,
  - B2 upload/update attempt.
- Fake or protocol-style client boundaries for transcription, summarization, and B2.
- Error-path handling for transcription and summarization failures.
- Tests covering the happy path and failure modes.

Exit criteria:

- A fake end-to-end pipeline run writes the expected local files.
- Summarization failure does not block completion.
- Transcription failure still writes a non-empty `meeting.md`.
- UI communication happens through event objects, not direct UI calls.

## Milestone 3: External Adapters

Purpose: add real service integrations behind already-tested boundaries.

Deliverables:

- AssemblyAI adapter under `repo/transcription.py`.
- Anthropic adapter under `repo/summarizer.py`.
- B2 S3-compatible adapter under `repo/b2_client.py`.
- Google Calendar OAuth and event polling adapter under `repo/calendar_client.py`.
- Keychain token storage.
- Audio device lookup under `repo/audio_device.py`.
- Mocked tests for each adapter.

Exit criteria:

- External SDK imports remain contained under `repo/`.
- B2 client uses the required `user_agent_extra`.
- Required environment variable names match `SPEC.md`.
- Tests pass without real credentials.

## Milestone 4: macOS App Integration

Purpose: connect the local core and adapters to the actual desktop experience.

Deliverables:

- Recorder service using the configured audio device.
- Tray app using `rumps`.
- Menu actions for start/stop, recent meetings, sync, preferences, and quit.
- Main-thread-only UI handling through queued events.
- Doctor-lite startup checks surfaced through the tray.
- Minimal preferences window for supported settings.

Exit criteria:

- App starts as a macOS menu bar process.
- Recording can be manually started and stopped.
- Background processing does not call UI APIs directly.
- Manual local validation confirms notification and tray behavior.

## Milestone 5: Real-World Validation

Purpose: validate the full app against a real macOS environment and credentials.

Deliverables:

- BlackHole setup guide verified against the app.
- Google Calendar auth guide verified.
- README setup and cost notes.
- Manual test checklist for:
  - doctor,
  - auth,
  - calendar detection,
  - recording,
  - transcription,
  - summarization,
  - B2 upload,
  - recent meeting browsing.

Exit criteria:

- A real meeting or test recording produces `recording.m4a` and `meeting.md`.
- B2 contains `meetings/<slug>/recording.m4a` and `meetings/<slug>/meeting.md`.
- Known limitations are documented.

## Suggested Commit Sequence

1. `Add implementation plan`
2. `Scaffold repository harness`
3. `Add local meeting models and markdown rendering`
4. `Add local storage workflow`
5. `Add fake pipeline orchestration`
6. `Add external service adapters`
7. `Add tray app and recorder`
8. `Document setup and validation workflow`
