# Manual Validation Checklist

This checklist is the Milestone 5 real-world validation path. It requires real
macOS audio setup and real service credentials.

## Preconditions

- macOS 13 or later
- Python virtualenv active
- `make install` completed
- `.env` exists and contains real values
- `ffmpeg` installed
- BlackHole 2ch installed
- `Meeting Aggregate` audio device exists, or `AUDIO_DEVICE` names the actual
  aggregate device
- Google Calendar OAuth credentials JSON exists
- `meeting-memory auth` completed successfully
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
- `ffmpeg` is on `PATH`.
- Google OAuth credentials file exists.
- Audio device exists.

## 2. Auth

Run:

```bash
meeting-memory auth
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

1. Join any test call or play audio routed through the meeting audio path.
2. Click `Start Recording`.
3. Speak into the microphone and play remote/system audio.
4. Wait at least 30 seconds.
5. Click `Stop Recording`.

Pass criteria:

- The tray menu changes between start and stop states.
- The status bar title shows the live recording duration while recording.
- If no nearby calendar event exists, the app prompts for a recording title
  before starting.
- A new meeting directory appears under `MEETINGS_DIR`.
- `recording.m4a` exists and is playable.
- If the recording maps to a calendar event with an end time, a stop reminder
  appears at the event finish time.

## 5. Transcription

Pass criteria after stopping recording:

- `meeting.md` appears in the same meeting directory.
- YAML frontmatter exists at the top.
- `assemblyai_id` is present.
- `## Transcript` exists.
- Speaker labels are preserved by default, for example `Speaker A`.
- If `SPEAKER_MAPPING_FILE` points to a JSON mapping, mapped names appear in
  participants and transcript speaker labels.

## 6. Summarization

With `ANTHROPIC_API_KEY` set:

- `summary_status: ok`
- `## Summary`, `## Decisions`, and `## Action Items` are present.

Without `ANTHROPIC_API_KEY`:

- `summary_status: skipped`
- `## Summary` contains `_Summarization skipped._`

If Claude fails:

- `meeting.md` is still written.
- Completion notification still appears.
- The completion notification's `Open` action opens the meeting directory.

## 7. B2 Upload

Pass criteria:

- `meeting.md` frontmatter eventually shows `b2_status: ok`.
- `b2_audio` is `meetings/<slug>/recording.m4a`.
- `b2_transcript` is `meetings/<slug>/meeting.md`.
- B2 contains both objects under the same key paths.
- Objects are not public.

If upload fails:

- `b2_status: upload_failed` is written.
- `Sync to B2` retries pending or failed meetings.
- `Retry Failed Processing` retries meetings with `assemblyai_id:
  transcription-failed` or `summary_status: failed`.

## 8. Recent Meeting Browsing

1. Open the tray menu.
2. Check `Recent Meetings`.
3. Click the newest meeting.

Pass criteria:

- At most five meetings are shown.
- The meeting directory opens in Finder.
- Both `meeting.md` and `recording.m4a` are visible.

## 9. Preferences

1. Open `Preferences...`.
2. Change one of:
   - `MEETINGS_DIR`
   - `NOTIFY_MINUTES_BEFORE`
   - `MAX_RECORDING_MINUTES`
   - `AUDIO_DEVICE`
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
- Speaker names are not inferred automatically; only the optional
  `SPEAKER_MAPPING_FILE` is applied.
- Calendar watching uses all accessible calendars unless `GOOGLE_CALENDAR_ID`
  is set to a specific calendar ID.
- Failed work is retryable from the tray, but retries are not yet automatically
  triggered by connectivity changes.
- The preferences window writes `.env` and requires restart.
