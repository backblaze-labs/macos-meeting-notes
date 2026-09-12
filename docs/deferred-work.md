# Deferred Work and Product Notes

This file records requested behavior that was not implemented, was only
partially implemented, or depends on local macOS state that future coding agents
should check before changing code.

When ending a work session with deferred behavior, append a dated note with:

- what was requested,
- what was implemented or accepted instead,
- why the original request was deferred,
- the first thing to check if the user raises it again.

## 2026-08-12 Required B2 Onboarding

Request: require Backblaze B2 credentials, direct new users to sign up, and do
not expose the normal recording UI until Backup is configured.

Outcome: B2 account/bucket/key setup is now part of the supported onboarding
contract. Doctor success requires usable Recording Core and Backup
configuration, and missing or disabled Backup routes startup to the setup tray.
The earlier offline-first onboarding notes below remain as historical context,
but their Backup-optional product policy is superseded. Local commit still
precedes upload, and provider/network failure after setup preserves the local
recording and retry path.

First thing to check: inspect `ui/runtime_app.py`, `types/capabilities.py`, and
the Quick Start before changing the setup gate. Do not add a provider network
probe to startup or make upload success a prerequisite for local commit.

## 2026-08-07 Local-First Contract Transition

Request: make a fresh user's first recording possible in under five minutes
without Terminal, cloud accounts, API keys, Google auth, or network access. The
acceptance path is about 30 seconds of real audio that can be played and
revealed in Finder within that window.

Outcome through the capability-aware setup slice: accepted the
capability/readiness, durable-audio, privacy, legacy migration, and phased
acceptance contract in `docs/local-first-contract.md`; added pure boundary
types, atomic local commit/state primitives, locked transcript and speaker
transactions, private indexed recovery, stable no-follow reads, and a verified
cancellable B2 snapshot-upload seam. Runtime startup now composes optional
adapters independently; capture uses indexed app staging; stopped and recovered
recordings share the atomic schema-v2 commit path; typed events, v2 retry, safe
Notes, and ownership-aware Recent/Search are active. CLI doctor and both tray
setup surfaces now share one five-capability `ReadinessReport`; only Recording
Core controls the default exit status, and explicit in-app checks run off the UI
thread without provider network calls.

Phase 4A provides a typed resolver, private atomic non-secret preference store,
and immutable generation-based generic Keychain adapter.
The store includes pinned no-follow I/O and revision compare-and-swap; the
Keychain API accepts and returns typed provider bundles, including one atomic
B2 credential pair. Phase 4B now wires one read-only, fixed-scope loader into
runtime, readiness, auth, search, and summarize. It snapshots exact process
names, `.env`, and app preferences once; reads only active generic Keychain
references required by the consumer; and fails corrupt app preferences closed
for optional egress unless a complete valid process group overrides them. It
performs no provider request, Google OAuth-token read, migration, or write.
The digest-bound `.env` migration engine is Phase 4C. Phase 4D now supplies the
explicit native per-capability disclosure/consent forms, secure entry, typed
workers/events, migration trigger, Calendar auth, and current-session pause
ordering. Clean-user computer validation remains Phase 5; signed/notarized
standalone distribution remains Phase 6.

The Phase 6 runtime-path prerequisite is now implemented. One captured
checkout/bundled layout anchors every active path by provenance and removes
ambient-cwd fallbacks. Bundled mode does not auto-discover `.env`; its migration
action must receive an explicit absolute selection. The PyInstaller artifact,
dual-architecture verification, clean-user evidence, and signed/notarized
release pipeline remain the next distribution slices.

The standalone-build slice now has a versioned PyInstaller spec, fully pinned
macOS distribution environment, thin `arm64`/`x86_64` CI matrix, ad-hoc signer,
relocation smoke, and static/dynamic bundle verifier. A manual, protected
release workflow defines Developer ID signing, notarization-log inspection,
stapling, final checksums, and publication, but cannot execute without the
owner-controlled `release` Environment, Apple credentials, and approval. Clean
standard-user audio/TCC evidence also remains pending its hardware boundary.

Phase 4C provides the migration engine. Its strict bounded preview
is privately bound to `.env` identity/digest and one preference revision;
confirmed apply reparses the unchanged file, writes only selected new immutable
secret generations, rechecks `.env`, and performs one preference CAS. Process
values are presence-only and never imported. `.env` is never rewritten or
deleted. Partial failures clean only refs created by that attempt; a visible but
directory-sync-uncertain preference activation retains its refs. An ambiguous
CAS also retains refs without claiming activation and requires a check before
retry. Failed cleanup may leave an unreachable immutable generation and is
reported for attention rather than deleting any pre-existing ref. The engine
has no CLI, startup, automatic runtime, or readiness invocation; Phase 4D calls
it only from an explicit native preview and confirmation. Keychain/filesystem
work stays off the UI thread, secrets are never prefilled or redisplayed, and
provider egress and automatic triggers are disclosed before consent.

Legacy recording recovery is explicitly user-triggered from Debugging. Its
successful empty scan writes the durable once marker immediately; this is
separate from `.env` configuration migration. A nonempty result stays
in memory and unmarked until every discovered entry is explicitly committed,
so a crash before selection intentionally permits a safe rescan. Normal launch
does not scan the legacy temp root. WAV-to-M4A conversion now prefers the
original AVFoundation exporter and falls back to a source-pinned, minimal,
offline LGPL encoder when the host exposes no AAC encoder. The real conversion
test therefore MUST run rather than skip on encoder availability. The strong
validator checks M4A type, AAC, 16 kHz mono, positive packets/duration, and a
full packet read; do not weaken it to accommodate a host limitation.

First thing to check: read `docs/local-first-contract.md`, then inspect
`service/configuration_loader.py` and `service/configuration_migration.py` with
their fixed-scope/single-use tests before runtime commit, job, recovery, and
snapshot tests. Do not wire migration before the native disclosure/consent
worker boundary, or add broad Keychain reads, background scans, or provider
calls to startup.

Runtime configuration canonicalizes the trusted `MEETINGS_DIR` root once, so a
configured root symlink works while meeting children and artifacts remain
no-follow. Invalid Calendar or Notes-only values disable only that capability;
they do not route Recording Core to setup.

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
detects temp WAV files, **Debugging** shows `Interrupted Recordings`, and selecting one
converts and processes it through the pipeline.

First thing to check if this comes up again: search temp-dir handling in
`RecorderService` and `service/recovery.py`; keep UI selection in `ui/` and
conversion/pipeline handoff in service/controller boundaries.

### Failed Processing Retry

Request: retry failed transcription and backup work when
connectivity returns.

Outcome: partially implemented. B2 has retry behavior plus manual `Retry Pending B2 Backups`.
Failed transcription can be retried through `Retry Failed Transcriptions`, using
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

Outcome: partially implemented. The tray includes `Check Setup & Dependencies`, which
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

## 2026-09-05 Sidebar Cutover

Request: replace the runtime dropdown menu with a draggable, edge-snapping
sidebar panel (`docs/features/sidebar.md`, plans in
`docs/features/sidebar/completed/`).

Outcome: shipped. Decisions that were considered and deliberately not taken,
so they are not re-litigated by accident:

- **Vertical-only was rejected** in favor of reorientation: a bar snapped to
  the top or bottom edge is horizontal, with the section stack behind an
  overflow popover. Without plan 06 the panel would still snap to all four
  edges in one shape; the owner chose the reorienting version.
- **The setup tray is intentionally not converted.** First run is a poor
  moment for a novel control, and keeping the plain menu halves the surface.
  `ui/submenus.py` now exists only for it.
- **Toggle visibility is intentionally not persisted** across launches; the
  panel starts hidden every time. Position and anchor are persisted.
- **Auto-show fires on every recording start**, including notification- and
  recovery-initiated ones (plan 07 gotcha 4). Not scoped to user-initiated
  starts: the point is that recording state is never invisible.

Deferred from the manual pass:

- The baseline `00-menu-*.png` screenshots of the retired dropdown were never
  captured (no accessibility access to click the status item from the agent
  shell). The substitute record is the label snapshot in
  `tests/test_sidebar_view_model.py`, which lists every row the dropdown
  showed and asserts the sidebar view model still renders each one.
- The real-mouse drag gesture, the setup-tray walk-through, VoiceOver, and
  the light/dark check were not exercised by hand. The drag path was verified
  in-process instead: `hitTest_` over the whole `⠿` strip resolves to the
  drag view, and the demo harness drives `SidebarPanel._handle_drag_end`
  through the real reorientation and popover code.

First thing to check if this comes up again: launch the installed bundle,
left-click the icon, drag the panel by the `⠿` strip to the top edge, and
confirm it becomes the horizontal bar with `⋯` opening a popover downward.
If the status item does nothing, check `ui/sidebar_toggle.py`'s install log
line first — it restores the rumps menu on failure.

## 2026-09-06 Sidebar Refinements From Competitor Research

Request: research comparable macOS meeting recorders (Granola, Krisp, Otter,
Fireflies, Fathom, Notion AI Meeting Notes, MacWhisper, Superwhisper, Cleft,
tl;dv, Apple Notes/FaceTime) and improve the sidebar accordingly.

Implemented (see `docs/features/sidebar.md`):

- A red dot on the menu bar icon while recording. *(Superseded 2026-09-12:
  the status bar shows `● mm:ss` again through the plain rumps title, so no
  rumps internals are needed.)*
- A post-stop status row (Fireflies "instant summary" / Notion auto-generate
  pattern): the latest lifecycle message with a click-through to reveal the
  meeting or review speakers.
- The pre-meeting notification's **Record** action also opens the meeting
  link (Granola's one-click join + record).

Deliberately not implemented yet, in value order:

- **Global start/stop hotkey** (Superwhisper, MacWhisper, Cleft). Needs a
  Carbon `RegisterEventHotKey` binding or an `NSEvent` global monitor; the
  latter requires Input Monitoring permission. Worth a small plan of its own.
- **Meeting-app detection** ("Zoom call detected — Record", Notion/Granola/
  MacWhisper). Needs mic-in-use polling; belongs with the calendar watcher in
  `service/`, not the sidebar.
- **Pause/Resume** (Otter, Apple Notes). The recorder has no pause; backend.
- **Live transcript peek** and a **collapsed timer pill** for the
  hide-while-recording mode. Both UI-only but medium-sized; the red dot
  covers the indicator need for now.

First thing to check if this comes up again: the status row is driven by
`RumpsTrayApp.last_status` (every `NotifyEvent`, including runtime-mapped
ones); if a message is missing from the row, check that the event reaches
`handle_event` rather than only `handle_notification`.

## 2026-09-08 Screenshots, Compact Sidebar, and Automatic Notes

Requests, in the order they arrived on the `screenshot-functionality` branch:

1. A screenshot button and key that files images with the meeting (one image
   loose in the meeting folder, several in a `screenshots/` subfolder).
2. The sidebar reduced to start/resume/stop, screenshot, and quit, with every
   other option moved to the menu behind the menu bar icon.
3. A rounded, as-small-as-possible sidebar whose controls are icons, not words.
4. Participant names taken from Google Meet/Zoom or the Calendar so nothing
   has to be typed after a meeting, and the post-meeting "pending tasks" gate
   removed.

Outcome: all four shipped (`docs/features/screenshots.md`,
`docs/features/sidebar.md`, `docs/features/transcription.md`). Decisions:

- **Meet/Zoom integration was not built.** Neither Google Meet nor Zoom
  exposes an API a local menu-bar app can use to learn who is on the call or
  speaking without a Workspace/Zoom developer app and OAuth grant. The
  Calendar invite's attendee list (already `speaker_candidates`) is the
  participant source; the summarizer receives it ahead of the transcript and
  names owners only where the conversation makes the mapping clear.
- **Speaker review is retired from the UI**, not from the data model.
  *(Superseded 2026-09-12: manual review is the default again and automatic
  Notes is an opt-in; the deleted modules were restored. See the review
  entry below.)*
- **"Resume" recording is not implemented.** The recorder has no pause, so
  the sidebar's record button toggles start/stop only (see the 2026-09-06
  note on Pause/Resume). Adding it is backend work in `service/recorder.py`
  and the native helper first.
- **The sidebar shows a timer while recording.** It is digits, not words, and
  it is the only text on the panel; the panel grows by one small slot while
  recording so the timer never overlaps a button.
- **Right-click, not left-click, opens the menu.** *(Superseded 2026-09-12:
  either click opens the menu; see the review entry below.)*

First thing to check if this comes up again: `ui/status_menu.py` for what the
menu holds, `ui/sidebar_compact.py` for the three buttons and their tooltips,
`service/screenshots.py:attach` for the one-file-vs-folder rule, and
`ui/controller.py:auto_generate_notes` for the transcript-to-notes handoff.
The global shortcut lives in `ui/screenshot_hotkey.py`; if it stops firing
after a macOS update, check `app.log` for the "Global screenshot hotkey"
line first.

## 2026-09-12 PR 18 Review Follow-Up

Request (review on PR 18): open the normal menu on any icon click and keep
Start Recording in it; make the sidebar auto-show on recording start and
otherwise leave visibility to the user; keep manual speaker review as the
default with automatic Notes as an explicit opt-in that cannot lock out a
later correction; never start or fail Notes when it is unavailable; key
screenshot staging by the durable capture session; synchronize the docs.

Outcome: all implemented. The `rumps` pin returned to `>=0.4` because the
status item toggle module and its internals are gone. Decisions:

- **Automatic Notes lives in `NSUserDefaults`** (`ui/notes_mode.py`) next to
  the sidebar preferences, as session UI behavior rather than a Phase 4
  preference-document field. Move it there if it ever needs migration or
  disclosure through the capability forms.
- **Attendee context only for kept labels.** The `Calendar attendees:` line
  reaches the summarizer only when the review stored no aliases, so the
  manual flow sends exactly what it sent before.
- **One correction for kept labels.** A confirmed transcript with empty
  `speaker_aliases` accepts one full alias map; named aliases stay terminal.
  Recent kept-label meetings appear under **Debugging › Correct Speakers**.
- **Screenshot staging key** is the recovery session directory name carried
  on `MeetingRef.recording_session` by the local-commit events.

Still open from the review's manual checklist: a real-mouse pass of the
menu, the auto-show and close rules, a same-minute double recording with
screenshots, and one automatic-mode meeting followed by a correction.

First thing to check if this comes up again: `ui/status_menu.py` for the menu
order, `ui/sidebar_tray_wiring.py:reveal` for the only automatic show,
`ui/notes_mode.py` and `ui/tray.py:handle_event` for the transcript-ready
routing, `service/speaker_state.py:_confirm_locked` for the kept-label rule,
and `service/screenshots.py` for the session key.
