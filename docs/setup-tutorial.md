# Setup Tutorial

This tutorial gets Meeting Memory running as a local macOS menu-bar app from a
fresh clone of the `macos-meeting-notes` repository.

## 1. Install System Requirements

You need:

- macOS 13 Ventura or later
- Python 3.11 or later
- `ffmpeg`
- BlackHole 2ch
- A Google account with Calendar access
- AssemblyAI API key
- Backblaze B2 bucket and S3-compatible application key
- Optional Anthropic API key for generated notes

With Homebrew, the common local tools are:

```bash
brew install python@3.11 ffmpeg blackhole-2ch
```

After installing BlackHole, restart meeting apps or restart macOS if the audio
device does not appear.

## 2. Clone and Install the Python App

```bash
git clone <repository-url> meeting-memory
cd meeting-memory
make setup
```

`make setup` creates or updates `.venv`, installs Python dependencies, creates
`.env` from `.env.example` if it is missing, installs the local macOS app
wrapper, and prints diagnostics. All Python dependencies install into `.venv`,
which is ignored by git.

## 3. Configure Audio Capture

Meeting Memory records from a macOS input device named `Meeting Aggregate` by
default.

Create it in Audio MIDI Setup:

1. Open `Audio MIDI Setup`.
2. Click `+` and choose `Create Aggregate Device`.
3. Rename it to `Meeting Aggregate`.
4. Include your microphone and `BlackHole 2ch`.
5. Use your microphone as the clock source when possible.
6. Enable drift correction for non-clock-source devices.

To capture remote meeting audio, route system output to BlackHole as described
in [blackhole-setup.md](blackhole-setup.md).

## 4. Create Service Credentials

Create credentials for each external service before filling `.env`.

Backblaze B2:

1. Create a bucket dedicated to Meeting Memory.
2. Create an application key restricted to that bucket.
3. Use the S3-compatible endpoint, region, key ID, key, and bucket name.

AssemblyAI:

1. Create or open an AssemblyAI account.
2. Copy an API key for transcription.

Anthropic, optional:

1. Create or open an Anthropic account.
2. Copy an API key if you want `notes.md` generation.
3. Leave `ANTHROPIC_API_KEY` blank to record and transcribe without notes.

Google Calendar:

1. Create or choose a Google Cloud project.
2. Enable the Google Calendar API.
3. Configure the OAuth consent screen.
4. Create an OAuth client ID with application type `Desktop app`.
5. Download the OAuth JSON as `credentials.json`.
6. Keep `credentials.json` in the repo root or set
   `GOOGLE_CALENDAR_CREDENTIALS_FILE` to another path.

`credentials.json` is ignored by git. OAuth tokens are stored in macOS Keychain,
not in the repository.

## 5. Fill Local Configuration

If `make setup` created `.env`, edit it and set:

```bash
B2_APPLICATION_KEY_ID=...
B2_APPLICATION_KEY=...
B2_ENDPOINT=https://s3.<region>.backblazeb2.com
B2_REGION=<region>
B2_BUCKET_NAME=<bucket>
ASSEMBLYAI_API_KEY=...
GOOGLE_CALENDAR_CREDENTIALS_FILE=credentials.json
```

Optional settings:

```bash
ANTHROPIC_API_KEY=
KNOWN_SPEAKERS=
MEETINGS_DIR=~/Meetings
AUDIO_DEVICE=Meeting Aggregate
GOOGLE_CALENDAR_ID=all
```

Use `KNOWN_SPEAKERS` only for your own local aliases, for example
`KNOWN_SPEAKERS=Alex,Blair`. Do not commit `.env`.

## 6. Run Preflight Checks

```bash
make doctor
```

`make doctor` checks configuration, B2, AssemblyAI, Google credentials/auth,
local files, `ffmpeg`, and audio device visibility. Some failures are expected
until credentials and audio setup are complete. B2 is required before Meeting
Memory is ready to record.

## 7. Authorize Google Calendar

```bash
.venv/bin/meeting-memory auth
```

A browser opens for Google OAuth. When the flow succeeds, the token is saved to
Keychain and the command prints a success message.

## 8. Install and Open the macOS App

```bash
make PYTHON=.venv/bin/python open-macos-app
```

The clickable app is installed at:

```text
~/Applications/Meeting Memory.app
```

You can launch it from Finder or with Spotlight by searching for
`Meeting Memory`.

After changing app code or `.env`, reload the local app bundle:

```bash
make PYTHON=.venv/bin/python reload-macos-app
```

## 9. Validate a Recording

1. Start Meeting Memory.
2. Choose `Send Test Notification` from the tray to confirm notification
   permissions.
3. Start an ad-hoc recording from the tray.
4. Speak for a few seconds and play remote audio if testing system capture.
5. Stop recording.
6. Wait for transcription.
7. Open the created meeting folder under `MEETINGS_DIR`.

Expected files:

```text
recording.m4a
transcript.md
notes.md
```

`notes.md` appears after speaker aliases are confirmed and Anthropic is
configured.

For a fuller checklist, use [manual-validation.md](manual-validation.md).

## 10. Start at Login, Optional

```bash
make PYTHON=.venv/bin/python install-launch-agent
```

To remove the login item:

```bash
make PYTHON=.venv/bin/python uninstall-launch-agent
```

## Troubleshooting

- `AUDIO_DEVICE` missing: confirm the exact device name in Audio MIDI Setup.
- No remote audio: confirm system output is routed to a Multi-Output Device
  that includes `BlackHole 2ch`.
- Google auth fails: confirm the OAuth client type is `Desktop app` and the
  Calendar API is enabled.
- B2 upload fails: confirm the application key is scoped to the bucket and the
  endpoint/region match the bucket.
- Notes are skipped: set `ANTHROPIC_API_KEY`, confirm speaker aliases, then run
  `meeting-memory summarize ~/Meetings/<meeting-folder>`.
