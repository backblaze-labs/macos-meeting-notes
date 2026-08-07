# Manual Validation Checklist

This checklist is the real-world validation path. It requires real macOS audio
setup and real service credentials.

## Preconditions

- macOS 15 or later
- Python virtualenv active
- `make setup` completed
- `.env` exists and contains real values
- Xcode Command Line Tools installed
- Google Calendar OAuth credentials JSON exists
- `.venv/bin/meeting-memory auth` completed successfully
- AssemblyAI account has available credit
- B2 bucket exists and credentials have S3 write access
- Optional: Anthropic key set for summaries

## 1. Doctor

Run:

```bash
make doctor
```

Pass criteria:

- Python is supported.
- macOS is supported.
- `.env` exists.
- Required env values are not placeholders.
- Google OAuth credentials file exists.
- The native audio helper is installed, reports the current microphone, and
  provides capture plus M4A conversion.

## 2. Auth

Run:

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

1. Edit `speaker_aliases` in `transcript.md`, for example
   `{"Speaker A": "Alex"}`.
2. Run `meeting-memory relabel <meeting-folder>`.

Pass criteria:

- `speaker_status: confirmed` appears in `transcript.md`.
- The participants line uses confirmed names.
- Transcript lines use confirmed names, for example `**Alex**`.

## 7. Summarization

With `ANTHROPIC_API_KEY` set:

- Confirm speakers from the tray review flow.
- `notes.md` is written.
- `summary_status: ok`
- `## Summary`, `## Decisions`, and `## Action Items` are present.
- If notes are missing or failed after speakers were confirmed, use the tray's
  `Continue Processing` item or run `meeting-memory summarize <meeting-folder>`.

Without `ANTHROPIC_API_KEY`:

- confirmed speaker review or `meeting-memory summarize <meeting-folder>` still
  writes `notes.md`.
- `summary_status: skipped`
- `## Summary` contains `_Summarization skipped._`

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
- `Sync to B2` retries pending or failed meetings.
- `Retry Failed Processing` retries meetings with
  `assemblyai_id: transcription-failed`.

## 9. Recent Meeting Browsing

1. Open the tray menu.
2. Check `Recent Meetings`.
3. Click the newest meeting.

Pass criteria:

- At most five meetings are shown.
- The meeting directory opens in Finder.
- `transcript.md`, `recording.m4a`, and any generated `notes.md` are visible.

## 10. Preferences

1. Open `Preferences...`.
2. Change one of:
   - `MEETINGS_DIR`
   - `NOTIFY_MINUTES_BEFORE`
   - `MAX_RECORDING_MINUTES`
3. Save.
4. Restart the app.

Pass criteria:

- `.env` is updated.
- The app uses the new setting after restart.

## 10. Auto-Stop, Recovery, Diagnostics, and Search

Auto-stop:

1. Temporarily set `MAX_RECORDING_MINUTES=1` in `.env`.
2. Restart the app.
3. Start a short test recording and do not click stop.

Pass criteria:

- After roughly one minute, the app sends `Recording limit reached`.
- Recording stops and the normal pipeline starts.

Recovery:

1. Start a short recording.
2. Force quit the app process before stopping.
3. Reopen the app.

Pass criteria:

- The tray menu shows `Recovered Recordings`.
- Clicking a recovered item converts and processes it.

Diagnostics:

- `Send Test Notification` shows a local notification.
- `Run Diagnostics` reports either `All checks passed.` or actionable setup
  failures.

Search:

```bash
meeting-memory search "decision"
```

Pass criteria:

- Matching meetings print date, title, path, and excerpt.
- A no-match query prints `No matching meetings found.`

## 11. Local App and Login Item

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

Remove it after validation if you do not want Meeting Memory to start at login:

```bash
make PYTHON=.venv/bin/python uninstall-launch-agent
```

## Known Limitations During Validation

- The `.app` is a local wrapper around this checkout and virtualenv, not a
  signed/notarized/standalone binary.
- Recording requires an explicit user start; fully automatic recording is out of
  scope.
- Speaker names are not inferred automatically; Calendar attendee candidates
  are hints, and aliases are confirmed manually.
- Calendar watching uses all accessible calendars unless `GOOGLE_CALENDAR_ID`
  is set to a specific calendar ID.
- Failed work is retryable from the tray, but retries are not yet automatically
  triggered by connectivity changes.
- The preferences window writes `.env` and requires restart.
