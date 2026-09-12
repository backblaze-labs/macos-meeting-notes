# Plan 002: PR 18 review fixes (feature-sidebar)

Source: review by EduPav on PR 18, 2026-09-10. Branch `feature-sidebar` on the
`ffumero2003` fork. `origin/main` is merged in (uncommitted) with one conflict
resolved in `service/runtime_notes.py`.

Work is done one task at a time, stopping after each for the user.

## Task 7. Screenshot staging key (first)

Problem: `service/screenshots.py` keys staging by the recording start minute
and matches it back from the slug prefix. Two recordings started in the same
minute share a key.

Change:
- `types/meeting.py`: `MeetingRef` gains `recording_session: str | None`.
  The value is the unique private capture session directory name created by
  `service/recovery_index.py:create_recovery_session` (`capture.<random>`).
  It survives title changes and crash recovery because the session directory
  is the recovery unit.
- `service/local_commit.py`: every `MeetingRef` it emits carries that name
  from the pinned entry.
- `service/screenshots.py`: `capture(session_id, ...)`, `pending_count(session_id)`,
  `attach(meeting)` reads `meeting.recording_session`. The session id must be
  one safe path component; anything else is ignored. Slug parsing is removed.
- `ui/screenshot_actions.py`: reads the id from the active session's recovery
  entry; a session without one gets the no-active-recording notice.
- Tests and `docs/features/screenshots.md` follow.

## Task 6. Notes guard

`TrayController.auto_generate_notes` must not confirm speakers or start Notes
when no notes generator exists or Notes is paused. Confirmation is a durable
transcript change, so it must not happen as a side effect of an optional
capability that cannot run.

## Task 3. Restore manual speaker review as the default

Restore from `origin/main`: `ui/speaker_review.py`, `service/processing_state.py`,
`types/processing.py`, `ui/processing_actions.py`, their tests, the
`review_speakers` notification action, and Pending Meeting Tasks in the
Debugging menu. The transcript-ready notification returns to
"review speakers" with the Review Speakers action when automatic mode is off.

## Task 4. Automatic notes as an opt-in toggle

A checkbox item under Configuration, off by default, stored in
`NSUserDefaults` next to the sidebar preferences (`ui/sidebar_prefs.py`).
Enabling shows an alert that states the tradeoff before the value is stored.
`tray.py` routes `TranscriptReady` to the automatic path only when on.

## Task 5. Reopen manual mapping after automatic notes

`service/speaker_state.py` treats `confirmed` as terminal. The automatic path
stores `speaker_status: confirmed` with empty aliases. Change: a confirmed
transcript whose stored aliases are empty (labels were kept) may be relabeled
once more with a full alias map; a confirmed transcript that already carries
aliases stays terminal. The Review Speakers window and Pending Meeting Tasks
then offer the correction. Notes regenerate through the existing action.

## Task 2. Sidebar visibility rules

- Auto-show on recording start from any source, via the existing
  `SidebarRevealRequested` event.
- Stays visible until the user closes it.
- Hide sidebar while recording suppresses auto-show for the session.
- A manual close during a recording suppresses auto-show until the next
  recording starts.

## Task 1. Menu bar click behavior

- Left-click and right-click both open the normal rumps menu.
- Start Recording / Stop Recording item returns to the top of that menu.
- Remove `ui/sidebar_toggle.py` internals; Show/Hide Sidebar stays a menu item.
- `pyproject.toml`: `rumps>=0.4` again.

## Task 8. Documentation sync

README.md, PRODUCT.md, SPEC.md (F3, F5, F8, F9, F12), docs/local-first-contract.md,
docs/features/sidebar.md, docs/features/transcription.md, docs/deferred-work.md.

## Task 9. Gate and reload

`make check`, then `make PYTHON=.venv/bin/python reload-macos-app`.
