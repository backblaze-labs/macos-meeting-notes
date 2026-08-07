# Setup Tutorial

This tutorial gets Meeting Memory running as a local macOS menu-bar app from a
fresh clone of the `macos-meeting-notes` repository.

## 1. Install System Requirements

You need:

- macOS 15 Sequoia or later
- Python 3.11 or later
- Xcode Command Line Tools
- A Google account with Calendar access
- AssemblyAI API key
- Backblaze B2 bucket and S3-compatible application key
- Optional Anthropic API key for generated notes

Install the system build tools once if they are not already present:

```bash
xcode-select --install
brew install python@3.11
```

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

There are no audio devices to configure. Meeting Memory builds and installs a
native audio helper as part of `make setup` and supports two tray-selectable
modes:

- `Full Meeting`: records system audio plus the current default microphone and
  lets you keep listening through the current output, including AirPods.
- `Silent System Only`: records system audio without the microphone and mutes
  playback for the duration of the recording.

The app never changes macOS input or output selection. BlackHole, Aggregate
Devices, and Multi-Output Devices are not required. On first use, allow the
Microphone and Screen & System Audio permissions requested by macOS.

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
KNOWN_SPEAKERS={}
MEETINGS_DIR=~/Meetings
GOOGLE_CALENDAR_ID=all
```

Use the tray's **Configuration › Known Speakers...** item to edit this later. It saves
`KNOWN_SPEAKERS` as a JSON object that maps display names to attendee names,
emails, or email local-parts to match, for example
`KNOWN_SPEAKERS='{"Alex Rivera":["alex@example.com","alex.rivera"]}'`. Do not
commit `.env`.

## 6. Run Preflight Checks

```bash
make doctor
```

`make doctor` checks configuration, B2, AssemblyAI, Google credentials/auth,
the bundled native audio helper, and local files. Some failures are expected
until credentials are complete. B2 is required before Meeting Memory is ready
to record.

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
2. Choose `Debugging › Test macOS Notifications` from the tray to confirm notification
   permissions.
3. Select `Full Meeting` and start an ad-hoc recording from the tray.
4. Speak for a few seconds and play remote audio. Confirm you can still hear it
   through your current output.
5. Stop recording, then repeat with `Silent System Only`; confirm the microphone
   is not recorded and playback is muted during capture.
6. Wait for transcription.
7. Open the created meeting folders under `MEETINGS_DIR`.

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

- Native helper build fails: run `xcode-select --install`, then rerun
  `make setup`.
- No audio capture: open System Settings › Privacy & Security and allow Meeting
  Memory under Microphone and Screen & System Audio Recording, then restart the
  app.
- Google auth fails: confirm the OAuth client type is `Desktop app` and the
  Calendar API is enabled.
- B2 upload fails: confirm the application key is scoped to the bucket and the
  endpoint/region match the bucket.
- Notes are skipped: set `ANTHROPIC_API_KEY`, confirm speaker aliases, then run
  `meeting-memory summarize ~/Meetings/<meeting-folder>`.
