# meeting-memory

`meeting-memory` is a macOS menu bar application that records meetings,
transcribes them with speaker diarization, summarizes them, saves portable
markdown files locally, and backs up meeting artifacts to Backblaze B2.

The app is local-first: each completed recording creates a directory under
`MEETINGS_DIR` containing:

- `recording.m4a`
- `meeting.md`

B2 is the durable backup layer. The local files remain the user's readable
meeting archive.

## Requirements

- macOS 13 Ventura or later
- Python 3.11 or later
- `ffmpeg`
- BlackHole 2ch plus a macOS Aggregate Device named `Meeting Aggregate`
- Google Calendar OAuth desktop credentials
- AssemblyAI API key
- Backblaze B2 bucket and S3-compatible application key
- Optional Anthropic API key for summaries

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
```

Fill in `.env`, then run:

```bash
make doctor
meeting-memory auth
meeting-memory
```

`make doctor` checks local setup. It is expected to fail until `.env`,
credentials, `ffmpeg`, and audio device setup are complete.

## Setup Guides

- [BlackHole setup](docs/blackhole-setup.md)
- [Google Calendar auth](docs/google-calendar-auth.md)
- [Manual validation checklist](docs/manual-validation.md)
- [Development workflows](docs/dev-workflows.md)

## Configuration

The app reads configuration from environment variables or `.env`.

Required:

- `B2_APPLICATION_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_ENDPOINT`
- `B2_REGION`
- `B2_BUCKET_NAME`
- `ASSEMBLYAI_API_KEY`
- `GOOGLE_CALENDAR_CREDENTIALS_FILE`

Optional:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `GOOGLE_CALENDAR_ID`
- `MEETINGS_DIR`
- `AUDIO_DEVICE`
- `NOTIFY_MINUTES_BEFORE`
- `MAX_RECORDING_MINUTES`
- `CALENDAR_POLL_INTERVAL`

See [.env.example](.env.example).

## Costs

Prices change; check provider pricing before recording long meetings.

As of 2026-06-11, AssemblyAI lists Universal-2 pre-recorded transcription at
`$0.15/hr` and speaker diarization at `$0.02/hr`, so this app's diarized
transcription path is roughly `$0.17/hr` before any optional features. See
[AssemblyAI pricing](https://www.assemblyai.com/pricing).

As of 2026-06-11, Backblaze lists B2 pay-as-you-go storage starting at
`$6.95/TB/month`, with free transactions and free egress up to 3x average
monthly storage. See [Backblaze B2 pricing](https://www.backblaze.com/cloud-storage/pricing).

Anthropic summary cost depends on the selected model, transcript length, and
current Anthropic pricing. The app sends at most the first 60,000 transcript
characters to Claude.

## Known Limitations

- The current implementation is a Python menu bar app, not a packaged `.app`.
- Recording requires manual start/stop.
- Speaker labels are preserved as AssemblyAI labels; the app does not map them
  to real attendee names.
- Calendar watching is limited to `GOOGLE_CALENDAR_ID` in v1.
- Failed offline/network work is surfaced through local status and manual retry;
  a durable offline queue is future work.
- The preferences window edits `.env`; restart the app after saving changes.
