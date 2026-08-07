# Deferred Work and Product Notes

This file records requested behavior that was not implemented, was only
partially implemented, or depends on local macOS state that future coding agents
should check before changing code.

When ending a work session with deferred behavior, append a dated note with:

- what was requested,
- what was implemented or accepted instead,
- why the original request was deferred,
- the first thing to check if the user raises it again.

## 2026-06-18 Current Reliability and Product Notes

This snapshot reflects the tree at the time this note was written. Before
starting any item, verify whether another branch or worker has already landed
it.

### Hard Auto-Stop

Request: enforce `MAX_RECORDING_MINUTES` as a safety limit that automatically
stops active recordings, starts the pipeline, and notifies the user.

Outcome: implemented through `TrayController._schedule_auto_stop()` /
`_auto_stop_recording()`. The setting exists in config, `.env.example`, and
Preferences.

First thing to check if this comes up again: inspect `TrayController` and
tests for fake sleepers/timer thread factories before changing behavior.

### Crash Recovery

Request: recover partial recordings after a crash or force quit.

Outcome: implemented as tray-discoverable recovery. `service/recovery.py`
detects temp WAV files, the tray shows `Recovered Recordings`, and selecting one
converts and processes it through the pipeline.

First thing to check if this comes up again: search temp-dir handling in
`RecorderService` and `service/recovery.py`; keep UI selection in `ui/` and
conversion/pipeline handoff in service/controller boundaries.

### Failed Processing Retry

Request: retry failed transcription and backup work when
connectivity returns.

Outcome: partially implemented. B2 has retry behavior plus manual `Sync to B2`.
Failed transcription can be retried through `Retry Failed Processing`, using
existing transcript frontmatter as durable state. What remains deferred is
automatic connectivity-triggered retry.

First thing to check if this comes up again: inspect
`service/processing_retry.py` before adding a new state format. Prefer extending
frontmatter-based state unless a real queue becomes necessary.

### AssemblyAI and Anthropic Retry/Backoff

Request: make API failure behavior more resilient and explicit.

Outcome: implemented for the repo adapters via `repo/retry.py`.
`transcription.py` and `summarizer.py` use explicit retry/backoff for transient
errors while preserving local failure output if processing still fails.

First thing to check if this comes up again: keep retry logic in `repo/` or a
lower-layer helper that does not violate SDK containment.

### Diagnostics Tray Surface

Request: expose local diagnostics for notification permissions, observed
calendar scope, next detected event, auth/B2 setup, audio device, and logs.

Outcome: partially implemented. The tray includes `Run Diagnostics`, which
reruns doctor checks and notifies a compact result, plus `Send Test
Notification`. Richer diagnostics such as observed calendars, next detected
event, B2 object state, and direct log-path display remain future work.

First thing to check if this comes up again: reuse existing doctor checks and
avoid network calls on the UI thread.

### Search, MCP, and Speaker Review

Request: make the completed meeting library easier to query and make speaker
labels easier to interpret.

Outcome: local full-text search is implemented as `meeting-memory search`, and
speaker review is implemented through per-meeting `speaker_aliases` plus
`meeting-memory relabel`. MCP resources remain future work.

First thing to check if this comes up again: keep local search/indexing separate
from the recording pipeline, and keep speaker alias edits deterministic and
local.

## 2026-06-17 Feedback Follow-Up

### Active Meet/Zoom Microphone Detection

Request: record only the microphone that Google Meet or Zoom is actively
receiving, instead of the current macOS default microphone.

Outcome: Meeting Memory now uses native macOS capture and no longer configures
an input device. `Full Meeting` captures the current macOS default microphone;
`Silent System Only` disables microphone capture entirely.

Reason deferred: macOS, browser-hosted Meet, and Zoom do not expose a reliable
app-level API here for this Python menu bar app to know which mic another app is
currently receiving, or to gate capture only while that app is receiving it.

First thing to check if this comes up again: verify that Meet/Zoom and macOS are
using the same default input when local voice is expected in transcripts.

### Recording Timer While Menu Is Open

Request: make the open tray menu's recording timer update live.

Outcome: partially implemented/accepted. The menu item label is updated by the
timer, and the status bar itself now shows a live `mm:ss` timer while recording.
The status bar timer was accepted as the practical visible fix.

Reason deferred: macOS menus may not repaint already-open menu item titles
reliably during menu tracking. Forcing that would likely require deeper AppKit
custom menu/status-item work beyond the current rumps integration.

First thing to check if this comes up again: confirm whether the status bar
timer is visible and updating. If the user specifically requires the already-open
dropdown item to repaint, investigate an AppKit-native menu delegate/custom menu
view rather than only changing the rumps timer.

### Notification Popup Reliability

Request: explain/fix why no pre-meeting notification popup appeared.

Outcome: improved but not fully guaranteed by code. The app sends a macOS user
notification with a `Record` action, sets `ignoreDnD`, passes action data, and
installs a `NSUserNotificationCenter` delegate method so notifications can show
as banners even while the menu-bar app is active. It falls back to an AppleScript
`display notification` if `rumps.notification` throws. The app is not supposed
to open itself automatically; dismissing the notification should not start
recording, while clicking `Record` should.

Reason deferred: notification visibility can still be blocked by macOS state
outside the app, including notification permissions, Focus/Do Not Disturb, the
global Notifications setting for mirroring/sharing the display, running from an
unexpected host process, or calendar configuration that prevents the watcher
from detecting the event.

First thing to check if this comes up again: before changing code, ask the user
to check macOS System Settings > Notifications for Meeting Memory/Python and
Focus/Do Not Disturb, plus System Settings > Notifications > Show
Notifications: `when mirroring or sharing the display`. Then verify the app was
launched through the official `Meeting Memory.app`, Google Calendar auth is
valid, `GOOGLE_CALENDAR_ID=all` unless intentionally narrowed, and the calendar
event has a Meet/Zoom URL within the notification window.
