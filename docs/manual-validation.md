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

1. Create a Google Calendar event starting within the next 5 minutes.
2. Put a Google Meet link or Zoom `/j/` link in `description` or `location`.
3. Start the app:

```bash
meeting-memory
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
- Speaker labels are preserved, for example `Speaker A`.

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

## Known Limitations During Validation

- The app is run as a Python process, not as a signed packaged `.app`.
- Recording is manual only.
- Real participant names are not resolved.
- Calendar watching uses all accessible calendars unless `GOOGLE_CALENDAR_ID`
  is set to a specific calendar ID.
- Offline retry queueing is not implemented in v1.
- The preferences window writes `.env` and requires restart.
