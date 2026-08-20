# Manual Validation Checklist

This checklist is the real-world validation path. Recording Core requires real
macOS audio setup and Backup requires a private B2 destination; validate only
the other services you configured. Use the standalone app for Phase 5
acceptance. The checkout commands remain useful for developer diagnostics.

## Preconditions

- macOS 15 or later
- Standalone track: a verified thin `.app` matching the Mac architecture
- Checkout track only: Python virtualenv active, `make setup` completed, and
  Xcode Command Line Tools installed
- A writable local `MEETINGS_DIR`
- Optional Calendar: OAuth credentials JSON plus successful
  `.venv/bin/meeting-memory auth`
- Optional Transcription: AssemblyAI account with available credit
- Required Backup: private B2 bucket and bucket-scoped S3-compatible credentials
- Optional Notes: Anthropic key

## 1. Doctor

From a checkout, run:

```bash
make doctor
```

Pass criteria:

- Recording Core, Transcription, Backup, Calendar, and Notes each appear once.
- Recording Core and Backup are `ready` or `degraded`, and the command exits
  `0`.
- The local meetings folder passes the temporary write and durability check.
- The native audio helper and offline AAC encoder are installed, and the helper
  reports local hardware support.
- The doctor explains that mode-specific macOS capture permissions are checked
  when a recording starts; it does not claim to pre-authorize them.
- Missing optional Transcription, Calendar, or Notes groups appear as
  `unconfigured`, not as app failures.
- Invalid configured integrations show their own action without changing the
  Recording Core state. Backup configuration failure makes doctor exit
  non-zero; optional integration failures do not.

## 2. Auth

Choose **Configuration › Authorize Calendar...** in the app. The checkout-only
equivalent is:

```bash
.venv/bin/meeting-memory auth
```

Pass criteria:

- Browser auth opens.
- Calendar read-only consent completes.
- Token is saved to Keychain.
- No token file is written to the repo.

## 3. Calendar Detection

1. Keep `GOOGLE_CALENDAR_ID=all`, or set it to the specific calendar you want
   to validate.
2. Create a Google Calendar event starting within the next 5 minutes on any
   watched calendar.
3. Put a Google Meet link or Zoom `/j/` or `/s/` link in `description`,
   `location`, or the event's native conferencing field.
4. Start the app:

```bash
make PYTHON=.venv/bin/python open-macos-app
```

Pass criteria:

- The menu bar app starts.
- A pre-meeting notification appears once.
- Dismissing the notification does not start recording.
- Clicking `Record` starts a recording named after the calendar event.

## 4. Manual Recording

1. Connect AirPods or select another preferred macOS input/output device.
2. Choose `Full Meeting` from the tray and join any test call.
3. Note the selected macOS input/output devices.
4. Click `Start Recording`.
5. Speak into the microphone and play remote or system audio.
6. Wait at least 30 seconds.
7. Click `Stop Recording`.

Pass criteria:

- The tray menu changes between start and stop states.
- The status bar title shows the live recording duration while recording.
- If no nearby calendar event exists, the app prompts for a recording title
  after stopping.
- A new meeting directory appears under `MEETINGS_DIR`.
- `recording.m4a` exists and is playable.
- Both the remote/system audio and local microphone are audible in the file.
- The selected macOS input/output devices did not change.
- Meeting playback remained audible through the selected output while
  recording.
- If the recording maps to a calendar event with an end time, a stop reminder
  appears at the event finish time.
- `transcript.md` contains `capture_status: healthy` and
  `capture_diagnostics` counters for both `system` and `microphone`.
- `~/Library/Logs/meeting-memory/app.log` contains a completion line with the
  meeting slug and the same source counters.

For live-loss detection, start another Full Meeting recording without any
Zoom/system sound. After 45 seconds, confirm the timer and Stop label gain `⚠︎`
and a notification offers **Stop**. Stop the test; confirm its transcript has
`capture_status: warning` and includes `system_silent`. A missing or stalled
source should warn at the next five-second health sample after ten seconds.

For back-to-back validation:

1. Stop a meeting while Transcription is enabled.
2. Before its transcript is ready, immediately start a second meeting.
3. Keep both microphone speech and remote/system speech active in the second
   call, then stop it.

The second timer must start without waiting for the first transcript. Both
meetings must commit separately, both recordings must contain both sources,
and each transcript must retain its own `capture_diagnostics`.

For system-audio-only validation:

1. Choose `Silent System Only` and start recording.
2. Play remote or system audio and speak near the microphone.
3. Confirm playback is muted while recording.
4. Stop and play `recording.m4a`.

The file must contain the remote/system audio, must not contain microphone
speech, and macOS must still have the same input/output devices selected.

## 5. Transcription

Pass criteria after stopping recording:

- `transcript.md` appears in the same meeting directory.
- YAML frontmatter exists at the top.
- `assemblyai_id` is present.
- `# Transcript` exists.
- Speaker labels are preserved by default, for example `Speaker A`.
- Calendar-backed recordings include `speaker_candidates` from event attendees.
  People matching optional `KNOWN_SPEAKERS` entries use those configured
  display names.

## 6. Speaker Review

1. Open the tray speaker-review flow.
2. Assign every detected speaker a name and choose **Confirm Names**, or choose
   **Keep Speaker Labels** when the names are unknown.

Pass criteria:

- `speaker_status: confirmed` appears in `transcript.md`.
- With assigned names, the participants and transcript lines use those names.
- With **Keep Speaker Labels**, `speaker_aliases` remains empty and labels such
  as `Speaker A` remain unchanged.
- Both choices start Notes generation and do not show a missing-alias error.

For CLI backfill, edit `speaker_aliases` in `transcript.md` and run
`meeting-memory relabel <meeting-folder>`.

## 7. Summarization

With `ANTHROPIC_API_KEY` set:

- Confirm speakers from the tray review flow.
- `notes.md` is written.
- `summary_status: ok`
- With the built-in layout, `## Summary`, `## Decisions`, and `## Action Items`
  are present.
- After selecting **Personal focus**, entering your name, and saving, the next
  generated `notes.md` contains `## Updates by person` and `## My tasks`, omits
  the Classic Decisions/Action Items sections, and includes no task assigned
  exclusively to someone else.
- After changing Advanced section titles, order, focus, formats, or guidance,
  the next generated `notes.md` contains exactly those configured sections.
- If notes are missing or failed after speakers were confirmed, use the tray's
  **Debugging › Pending Meeting Tasks** item or run
  `meeting-memory summarize <meeting-folder>`.

Without `ANTHROPIC_API_KEY`:

- confirmed speaker review or `meeting-memory summarize <meeting-folder>` still
  writes `notes.md`.
- `summary_status: skipped`
- The generated body contains `_Summarization skipped._`; the Classic layout
  places it under `## Summary`.

If Claude fails:

- `transcript.md` remains unchanged.
- `notes.md` records the failed summary state.

## 8. B2 Upload

Pass criteria:

- `transcript.md` frontmatter eventually shows `b2_status: ok`.
- `b2_audio` is `meetings/<slug>/recording.m4a`.
- `b2_transcript` is `meetings/<slug>/transcript.md`.
- B2 contains both objects under the same key paths.
- Objects are not public.

If upload fails:

- `b2_status: upload_failed` is written.
- `Retry Pending B2 Backups` retries pending or failed meetings.
- `Retry Failed Transcriptions` retries meetings with
  `assemblyai_id: transcription-failed`.

## 9. Recent Meeting Browsing

1. Open the tray menu.
2. Check `Recent Meetings`.
3. Click the newest meeting.

Pass criteria:

- At most three meetings are shown.
- The meeting directory opens in Finder.
- `transcript.md`, `recording.m4a`, and any generated `notes.md` are visible.

## 10. Native Configuration

1. Open `Configuration › Recording Core...`.
2. Change one of:
   - `MEETINGS_DIR`
   - `MAX_RECORDING_MINUTES`
3. Save and restart only when the result asks for it.

Pass criteria:

- App-owned preferences are updated; `.env` remains byte-identical.
- The app uses the new setting after restart.
- The tray remains responsive while preferences and filesystem work run.

Optional capability forms:

1. Open each item under **Configuration**.
2. Confirm the form shows app-owned non-secret values only.
3. Confirm every secure field is blank, including after reopening.
4. Read the provider, data, and trigger disclosure before enabling.
5. Cancel and confirm there are no preference or Keychain writes.

Explicit legacy import:

1. Choose **Configuration › Import Legacy Configuration...**.
2. Select an exact `.env` file in the native picker.
3. Review every value-free candidate and leave capabilities unselected first.
4. Cancel, then repeat and explicitly confirm one whole-capability import.

Pass criteria:

- No preview runs on launch or merely opening Configuration.
- Process values are identified only by presence and are never imported.
- The source `.env` content, inode, and mode remain unchanged on cancel,
  success, stale preview, and failure.
- Imported path values preserve the selected source's meaning after restart.

Notes customization workspace:

1. Open `Configuration › Notes Customization...` and confirm Templates is the
   initial view for the Classic profile.
2. Select Personal focus. Confirm Save rejects a blank **Your name**, then enter
   a name and verify the preview shows Updates by person and My tasks.
3. Open Advanced. Add a section, rename it, change its focus and format, move it,
   and verify each change in the live preview. Change the general AI guidance.
4. Save and generate notes for a confirmed transcript containing tasks assigned
   both to the configured user and to someone else.
5. Reopen the workspace, choose `Restore Classic`, and save again.

Pass criteria:

- The save confirmation shows the path from `SUMMARY_PROMPT_FILE`.
- The app-owned storage marker never appears in the standard workspace.
- The next notes generation uses both general guidance and the configured
  section recipe without restarting the app.
- The custom headings appear in `notes.md`; local layout text and storage
  metadata do not appear in the Anthropic request.
- Personal focus keeps only tasks explicitly assigned to the configured user.
- Restoring the default replaces the editor contents with the built-in prompt.

## 11. Auto-Stop, Recovery, Diagnostics, and Search

Auto-stop:

1. Temporarily set `MAX_RECORDING_MINUTES` to `1` in **Recording Core...**.
2. Save and restart the app.
3. Start a short test recording and do not click stop.

Pass criteria:

- After roughly one minute, the app sends `Recording limit reached`.
- Recording stops and the normal pipeline starts.

Recovery:

1. Start a short recording.
2. Force quit the app process before stopping.
3. Within two seconds, verify that no `MeetingMemoryCapture record` process
   remains and that the staging WAV size has stopped changing.
4. Reopen the app.

Pass criteria:

- The native capture helper exits and closes the WAV when its app parent dies.
- `Debugging` shows `Interrupted Recordings`.
- Clicking a recovered item converts and processes it.

Diagnostics:

- `Debugging › Test macOS Notifications` shows a local notification.
- `Debugging › Check Setup & Dependencies` immediately shows all five
  capabilities as `checking`, keeps recording controls available, and settles
  to the same capability states/actions as `make doctor` without freezing the
  tray.

Search:

```bash
meeting-memory search "decision"
```

Pass criteria:

- Matching meetings print date, title, path, and excerpt.
- A no-match query prints `No matching meetings found.`

## 12. Checkout Wrapper, Standalone App, and Login Item

Run:

```bash
make PYTHON=.venv/bin/python install-macos-app
make PYTHON=.venv/bin/python reload-macos-app
```

Pass criteria:

- `~/Applications/Meeting Memory.app` exists.
- Launching the app shows only a menu-bar item, not a Dock icon.
- `make PYTHON=.venv/bin/python quit-macos-app` quits the running app.

Then run:

```bash
make PYTHON=.venv/bin/python install-launch-agent
```

Pass criteria:

- `~/Library/LaunchAgents/com.meeting-memory.app.plist` exists.
- The background app starts without a terminal window.
- Logs are written under `~/Library/Logs/meeting-memory/`.

Standalone acceptance additionally requires:

- Copy the thin app to an unrelated directory and launch it without the source
  checkout, `PYTHONPATH`, developer Python, or Xcode tools.
- `--version` and `bundle-self-check` pass with a fresh HOME and foreign working
  directory before interactive validation.
- The bundled native helper is selected exactly; no checkout helper or `.env`
  is discovered.
- `MeetingMemoryFFmpegAudioEncoder`, `FFMPEG-COPYING.LGPLv2.1`,
  `FFMPEG_SOURCE_OFFER.md`, and the exact `ffmpeg-8.1.2.tar.xz` source are
  present in the bundle; the encoder has the same thin architecture as the app
  and helper.
- On a host without an AudioToolbox AAC encoder, stopping or recovering a real
  recording still produces a playable 16 kHz mono AAC M4A through the bundled
  offline fallback. No system/Homebrew FFmpeg is consulted.
- An ad-hoc app is described only as a validation build. Gatekeeper-ready claims
  require the Developer ID/notarized workflow and stapled artifact.

Remove it after validation if you do not want Meeting Memory to start at login:

```bash
make PYTHON=.venv/bin/python uninstall-launch-agent
```

## Known Limitations During Validation

- The `make install-macos-app` output is a checkout wrapper. The PyInstaller app
  is standalone but remains validation-only until Developer ID signing,
  notarization, stapling, and clean-user evidence pass.
- Recording requires an explicit user start; fully automatic recording is out of
  scope.
- Speaker names are not inferred automatically; Calendar attendee candidates
  are hints, and aliases are confirmed manually.
- Calendar watching uses all accessible calendars unless `GOOGLE_CALENDAR_ID`
  is set to a specific calendar ID.
- Failed work is retryable from the tray, but retries are not yet automatically
  triggered by connectivity changes.
- Native Configuration writes app-owned preferences and Keychain references;
  no reachable UI action rewrites `.env`. Enabling or replacing a capability
  asks for restart, while disabling pauses current-session egress first.
