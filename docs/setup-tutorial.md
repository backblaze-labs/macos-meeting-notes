# Setup Tutorial

This tutorial gets Meeting Memory running as a local macOS menu-bar app from a
fresh clone of the `macos-meeting-notes` repository.

This is the current source-checkout setup. B2 Backup is optional and does not block the normal recording UI.
Enable only when authorized to upload meeting content; see
[`local-first-contract.md`](local-first-contract.md). Recording still commits
locally before attempting an upload and remains recoverable through temporary
network or provider failures. Phase 4B composes
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

Required for setup:

- Backblaze B2 account
- Dedicated private B2 bucket
- S3-compatible application key restricted to that bucket

Optional services:

- Google account with Calendar access for context and reminders
- Apple Silicon with a native arm64 process and Metal for Local transcription
  (no service credential; prepare models explicitly)
- AssemblyAI API key only for explicitly selected external transcription
- Anthropic API key for generated notes after speaker review

Install the system build tools once if they are not already present:

```bash
xcode-select --install
brew install python@3.11    # note: does not replace `python3`;
                            # use `make SETUP_PYTHON=python3.11 setup` if needed
```

## 2. Clone and Install the Python App

```bash
git clone https://github.com/backblaze-labs/macos-meeting-notes.git
cd macos-meeting-notes
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

## 4. Create Backblaze B2 Credentials (Optional)

Skip this section to keep backups local. Enable Backup only if authorized to
send meeting audio and transcripts to the destination bucket.

1. [Create a Backblaze B2 account](https://www.backblaze.com/sign-up/cloud-storage).
2. In the B2 web console, create a bucket dedicated to Meeting Memory and keep
   it private.
3. Create a Read and Write application key restricted to that bucket. Save the
   application key immediately; Backblaze displays it only once.
4. Keep the bucket's S3-compatible endpoint, region, key ID, application key,
   and bucket name ready for the native Configuration form.

Do not paste either credential into chat, commit it, or leave it in shell
history. Meeting Memory stores the pair in macOS Keychain.

## 5. Optionally Create Other Service Credentials

Local transcription needs no account or API key. On compatible Apple Silicon,
choose **Configuration › Prepare Local Models...**. The panel reuses validated
standard Hugging Face weights or downloads missing files without meeting
content, with progress, Cancel, and Retry. It does not transcribe old recordings.

AssemblyAI, only if you want external transcription:

1. Create or open an AssemblyAI account and obtain its API key.
2. Choose **Configuration › Transcription...**, select AssemblyAI, and accept
   its external-audio notice before saving. The free plan participates in model
   improvement without opt-out; paid accounts can explicitly opt out, but
   payment alone is not exclusion. Opt-out applies to future requests only.
3. Save and restart. An existing key alone, legacy import, or local error never
   selects cloud. Meeting Memory does not know your account's opt-out setting.
   See [the dated official sources](features/transcription.md#external-provider-consent).

Anthropic, optional:

1. Create or open an Anthropic account.
2. Copy an API key if you want `notes.md` generation.
3. Leave `ANTHROPIC_API_KEY` blank to record and transcribe without Notes or
   pre-review speaker suggestions. When enabled, those suggestions send
   transcript context to Anthropic before speaker confirmation.

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

## 6. Configure Optional Backup and Integrations

If you want remote backup and are authorized to send meeting content, open
**Configuration › Backup...** from the tray, select **Enabled
(app-managed)**, and enter all five required B2 values. Each form names the
provider, data sent, and trigger before it can be enabled. Credential fields use
native secure controls, are stored in Keychain, and are blank every time the
form reopens. Save, quit, and reopen Meeting Memory to activate uploads.
Leave Backup disabled to keep backup artifacts on this Mac only.

Transcription defaults to Local and enabled unless explicitly disabled.
Prepare its models on supported Apple Silicon. Use **Transcription...** to
disable it or explicitly select a consented cloud provider. Configure only the
optional **Calendar...** and **Notes...** capabilities you want. Saved
enablement or credential/destination changes require quitting and reopening Meeting Memory;
Disable pauses new work in the current session before reporting success.

Use **Configuration › Calendar...** for the native Known Speakers row editor.
Use **Authorize Google Calendar...** only after saving Calendar settings. OAuth
opens a browser only for that explicit action and stores the token in Keychain.

Existing `.env` profiles remain compatible. Use **Import Legacy
Configuration...** to preview exact recognized key names and states, choose
whole capabilities, review their disclosures, and confirm import. Nothing is
selected by default; process values are never imported and `.env` remains
byte-identical. `TRANSCRIPTION_PROVIDER` and `ASSEMBLYAI_CONSENT` accept only
app preferences and actual process overrides; values in `.env` or legacy
imports are intentionally ignored. Existing keys are preserved but do not
authorize external processing. Manual `.env` editing is a legacy/development
fallback only; do not commit it.

## 7. Run Preflight Checks

```bash
make doctor
```

`make doctor` renders Recording Core, Transcription, Backup, Calendar, and Notes
independently. Its exit status requires both a usable Recording Core and a
usable Backup configuration. Disabled or missing optional integrations remain
independent. Missing local models show a preparation action; unsupported
hardware/runtime and Calendar authorization affect only their own capability.
The check makes no provider network request and neither downloads nor loads
model weights. You can rerun the same report from
**Debugging › Check Setup & Dependencies** without blocking the tray UI.
The check verifies the helper and durable local storage but does not request
macOS capture permissions; those remain mode-specific and are validated when a
recording starts.

## 8. Authorize Google Calendar, Optional

Prefer **Configuration › Authorize Google Calendar...**. The compatible CLI
action remains available for development:

```bash
.venv/bin/meeting-memory auth
```

A browser opens for Google OAuth. When the flow succeeds, the token is saved to
Keychain and the command prints a success message.

## 9. Install and Open the macOS App

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

## 10. Validate a Recording and B2 Backup

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
7. Confirm that `recording.m4a` and `transcript.md` were uploaded under the
   matching `meetings/<slug>/` prefix in the private B2 bucket. If the upload
   failed, use **Debugging › Retry Pending B2 Backups**.
8. If Local is ready, wait for `transcript.md` to update. If models were missing,
   prepare them, then choose **Debugging › Retry Pending or Failed
   Transcriptions** separately and confirm the provider. Preparation and
   restart do not process history; successful transcripts remain terminal.

Expected files:

```text
recording.m4a
transcript.md
notes.md
```

`transcript.md` always exists as the local metadata stub. `notes.md` appears
after transcription, speaker review, and optional Anthropic Notes generation.

For a fuller checklist, use [manual-validation.md](manual-validation.md).

## 11. Start at Login, Optional

```bash
make PYTHON=.venv/bin/python install-launch-agent
```

To remove the login item:

```bash
make PYTHON=.venv/bin/python uninstall-launch-agent
```

## Troubleshooting

- Local models missing or corrupt: use **Prepare Local Models...**, then
  explicitly retry pending recordings. Recording remains available.
- Local incompatible: run a native arm64 app on Apple Silicon with Metal, or
  explicitly select AssemblyAI after reviewing its external-audio notice. The
  app does not switch providers automatically.
- Local inference or diarization failed: retain the original audio and use the
  explicit pending/failed retry action. Complete diarization failure does not
  publish partial text or start speaker review/Notes.
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
