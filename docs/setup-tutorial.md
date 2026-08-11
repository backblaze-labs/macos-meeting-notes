# Setup Tutorial

This tutorial gets Meeting Memory running as a local macOS menu-bar app from a
fresh clone of the `macos-meeting-notes` repository.

This is the current source-checkout setup. Recording Core requires no cloud
integration for a first recording; see
[`local-first-contract.md`](local-first-contract.md). Phase 4B now composes
exact process-environment overrides, active app preferences/immutable Keychain
references, legacy `.env`, and defaults. Phase 4D's native Configuration submenu
now owns app-managed capability forms, disclosure/consent, secure secret entry,
explicit legacy import, and explicit in-app Calendar authorization. The native
UI never writes `.env`.
The ad-hoc standalone build and native configuration surface are implemented.
Dedicated clean-user audio/TCC evidence remains Phase 5, and an owner-approved
Developer ID/notarized public release remains Phase 6.

## 1. Install System Requirements

You need:

- macOS 15 Sequoia or later
- Python 3.11 or later
- Xcode Command Line Tools

Only configure the optional services you want:

- Google account with Calendar access for context and reminders
- AssemblyAI API key for diarized transcription
- Backblaze B2 bucket and S3-compatible application key for private backup
- Anthropic API key for generated notes after speaker review

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
native audio helper plus a source-pinned minimal offline AAC encoder as part of
`make setup` and supports two tray-selectable modes:

- `Full Meeting`: records system audio plus the current default microphone and
  lets you keep listening through the current output, including AirPods.
- `Silent System Only`: records system audio without the microphone and mutes
  playback for the duration of the recording.

The app never changes macOS input or output selection. BlackHole, Aggregate
Devices, and Multi-Output Devices are not required. On first use, allow the
Microphone and Screen & System Audio permissions requested by macOS.
No system or Homebrew FFmpeg installation is used.

## 4. Optionally Create Service Credentials

Skip this section if you only want local recording. Create credentials only for
the capabilities you want to enable in the native Configuration submenu.

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

## 5. Optionally Enable Integrations

Open **Configuration** from the tray, then configure only the capabilities you
want: **Transcription...**, **Backup...**, **Calendar...**, or **Notes...**.
Each form names the provider, data sent, and trigger before it can be enabled.
Credential fields use native secure controls, are stored in Keychain, and are
blank every time the form reopens. Saved enablement or credential/destination
changes require quitting and reopening Meeting Memory; Disable pauses new work
in the current session before reporting success.

Use **Configuration › Calendar...** for the native Known Speakers row editor.
Use **Authorize Google Calendar...** only after saving Calendar settings. OAuth
opens a browser only for that explicit action and stores the token in Keychain.

Existing `.env` profiles remain compatible. Use **Import Legacy
Configuration...** to preview exact recognized key names and states, choose
whole capabilities, review their disclosures, and confirm import. Nothing is
selected by default; process values are never imported and `.env` remains
byte-identical. Manual `.env` editing is a legacy/development fallback only;
do not commit it.

## 6. Run Preflight Checks

```bash
make doctor
```

`make doctor` renders Recording Core, Transcription, Backup, Calendar, and Notes
independently. Its exit status depends only on whether Recording Core has a
compatible runtime/helper and passes its durable storage probe. Missing
optional configuration is `unconfigured`; invalid
local configuration or Calendar authorization affects only that capability.
The check makes no provider network request. You can rerun the same report from
**Debugging › Check Setup & Dependencies** without blocking the tray UI.
The check verifies the helper and durable local storage but does not request
macOS capture permissions; those remain mode-specific and are validated when a
recording starts.

## 7. Authorize Google Calendar, Optional

Prefer **Configuration › Authorize Google Calendar...**. The compatible CLI
action remains available for development:

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

After changing app code, reload the local app bundle:

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
6. Open the created meeting folders under `MEETINGS_DIR` and play
   `recording.m4a`.
7. If Transcription is configured, wait for `transcript.md` to update.

Expected files:

```text
recording.m4a
transcript.md
notes.md
```

`transcript.md` always exists as the local metadata stub. `notes.md` appears
after transcription, speaker review, and optional Anthropic Notes generation.

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

- Native audio build fails: confirm Xcode Command Line Tools are installed and
  the vendored FFmpeg source archive is present, then rerun `make setup`. The
  checksum is verified before any source is extracted or compiled.
- No audio capture: open System Settings › Privacy & Security and allow Meeting
  Memory under Microphone and Screen & System Audio Recording, then restart the
  app.
- Google auth fails: confirm the OAuth client type is `Desktop app` and the
  Calendar API is enabled.
- B2 upload fails: confirm the application key is scoped to the bucket and the
  endpoint/region match the bucket.
- Notes are skipped: set `ANTHROPIC_API_KEY`, confirm speaker aliases, then run
  `meeting-memory summarize ~/Meetings/<meeting-folder>`.
