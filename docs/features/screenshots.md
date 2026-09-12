# Feature: Screenshots

## Purpose

Capture the screen during a recording with one click or one key press, and
file the images with that meeting. One screenshot lands directly in the
meeting directory; two or more are grouped in a `screenshots/` subfolder.

## Inputs

- The sidebar's camera button (`docs/features/sidebar.md`)
- The global shortcut **⌥⇧S** (Option+Shift+S), registered through the Carbon
  hot-key API so it works from any app without Accessibility or Input
  Monitoring permission
- The active recording's capture session and start time (screenshots need a
  recording; without one the app notifies "No active recording")

## Outputs

- `<meeting>/screenshot-01-at-05m12s.png` when a meeting has exactly one
  screenshot (the suffix is the offset into the recording)
- `<meeting>/screenshots/screenshot-NN-at-MMmSSs.png` when it has two or more
- A "Screenshot saved" notification per capture

## Threading

Capture runs on the main thread (`screencapture` returns in well under a
second) from the sidebar button or the Carbon hot-key handler, which AppKit
dispatches on the main thread. Attachment happens on the main thread when a
`RecordingCommitted` (or publication-uncertain / cleanup-pending) event
reaches the tray: the meeting directory only exists after the local commit's
atomic rename, so screenshots are staged until then.

## Behavior Notes

- While recording, screenshots are staged under
  `MEETINGS_DIR/.meeting-memory-staging/screenshots/<capture-session>/` on
  the same filesystem as the meetings, keyed by the recording's unique
  capture session name (the private recovery session directory). That name
  survives title changes and crash recovery, and the committed-meeting event
  carries it, so two recordings that start within the same minute never mix
  screenshots. When the meeting directory is published the files are renamed
  into it.
- Staged screenshots survive a crash: a recovered recording that commits later
  still receives them.
- `screencapture -x -t png` captures the main display silently. If macOS
  Screen Recording permission is missing, macOS returns a desktop-only image
  rather than failing; the notification body points at the permission when
  capture fails outright.
- If the meeting directory already has a `screenshots/` folder, later
  attachments join it; name collisions get a `-2`, `-3` suffix.
- The setup tray has no screenshot control; the shortcut is registered only
  by the runtime tray.

## Related Files

- `src/meeting_memory/repo/screen_capture.py` — `screencapture` adapter
- `src/meeting_memory/service/screenshots.py` — staging, naming, attachment
- `src/meeting_memory/ui/screenshot_actions.py` — tray capture + event hook
- `src/meeting_memory/ui/screenshot_hotkey.py` — Carbon global shortcut
- `src/meeting_memory/ui/sidebar_compact.py` — the camera button
- `src/meeting_memory/ui/tray.py`

## Tests

- `tests/test_screen_capture.py`
- `tests/test_screenshots.py`
- `tests/test_screenshot_actions.py`
- `tests/test_screenshot_hotkey.py`
