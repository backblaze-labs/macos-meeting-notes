# macos-meeting-notes

> ⚠️ **Experimental.** This is an experimental
> sample app, not an officially supported Backblaze product. APIs, setup steps, and
> behavior may change without notice. Use at your own risk.

`macos-meeting-notes` is the repository for **Meeting Memory**, a local-first
macOS menu-bar app that records meetings, saves portable artifacts locally,
and backs up each meeting's audio and transcript to Backblaze B2 over the
S3-compatible API. It can also add speaker-diarized transcription (AssemblyAI),
Calendar context, and summaries (Anthropic Claude).

The repository/distribution name is `macos-meeting-notes`; the app visible to
users remains **Meeting Memory**, the Python import package remains
`meeting_memory`, and the installed CLI remains `meeting-memory`.

The app is local-first: each completed recording creates a directory under
`MEETINGS_DIR` containing:

- `recording.m4a`
- `transcript.md`
- `notes.md` after you confirm speaker aliases and generate derived notes

B2 is the required durable backup layer. The local files remain the user's
readable meeting archive and are committed before any upload begins.

Completing setup requires a Backblaze B2 account, a dedicated private bucket,
and a bucket-scoped application key. The app keeps local recording durable when
the network or B2 is temporarily unavailable, while Transcription, Calendar,
and Notes remain optional. The tray's native **Configuration** submenu stores
credentials in macOS Keychain; complete legacy `.env` groups remain compatible.
See [the capability contract](docs/local-first-contract.md).

After required B2 setup, the first-value acceptance test is concrete: record
about 30 seconds of real audio, stop, play the saved result, reveal its meeting
directory in Finder, and confirm its private B2 objects.

## Checkout Requirements

- macOS 15 Sequoia or later
- Python 3.11 or later
- Xcode Command Line Tools (`xcode-select --install`)
- A Backblaze B2 account, dedicated private bucket, and bucket-scoped
  S3-compatible application key
- Optional Google Calendar OAuth desktop credentials
- Optional AssemblyAI API key
- Optional Anthropic API key for summaries

The standalone `.app` validation artifact bundles Python, the Swift capture
helper, and its minimal offline AAC encoder; it does not require Python, Xcode,
Homebrew, or a system FFmpeg installation on the destination Mac. Developer ID
signing, notarization, and clean-user evidence are still required before it can
be described as a public release.

## Quick Start

### Ask an agent to install it

The fastest path is to hand this repository to Codex, Claude Code, or another
coding agent. Paste this prompt:

```text
Install Meeting Memory from https://github.com/backblaze-labs/macos-meeting-notes.
Follow docs/agent-setup.md and guide me through the required B2 setup.
```

The dedicated [agent setup guide](docs/agent-setup.md) gives the agent the full
workflow and credential-safety rules. You keep control of the Backblaze account
flow and enter credentials only in the app's secure form.

### Install manually

1. [Create a Backblaze B2 account](https://www.backblaze.com/sign-up/cloud-storage).
   Create a bucket dedicated to Meeting Memory, keep it **private**, and create
   a Read and Write application key restricted to that bucket. Save the key ID
   and application key when they are shown; the application key is displayed
   only once. Also copy the bucket's S3 endpoint, region, and name.

2. Clone and install the source checkout:

   ```bash
   git clone https://github.com/backblaze-labs/macos-meeting-notes.git
   cd macos-meeting-notes
   make setup
   ```

   `make setup` creates `.venv`, installs dependencies, installs
   `~/Applications/Meeting Memory.app`, and prints local diagnostics. It is
   normal for Backup to be `unconfigured` until the next step.

3. Open the app:

   ```bash
   make PYTHON=.venv/bin/python open-macos-app
   ```

4. From the menu bar, open **Configuration › Backup...**, select
   **Enabled (app-managed)**, and enter the B2 endpoint, region, bucket name,
   application key ID, and application key. Review the upload disclosure,
   save, then quit and reopen Meeting Memory. Secret fields are native secure
   controls, are stored in macOS Keychain, and reopen blank.

5. Verify the required setup:

   ```bash
   make doctor
   ```

   Both `Recording Core` and `Backup` must report `READY` (or a usable
   `DEGRADED` state) for the command to succeed. The check validates local
   configuration without contacting B2; the first completed recording verifies
   the real upload path.

6. Choose an audio mode from the tray, start a short recording, stop it, and
   confirm the local meeting folder is created. If an upload fails, use
   **Debugging › Retry Pending B2 Backups**.

For the full walkthrough, provider setup, permissions, and troubleshooting,
read [docs/setup-tutorial.md](docs/setup-tutorial.md).

### Local development commands

```bash
make PYTHON=.venv/bin/python reload-macos-app
```

This updates and restarts the official local app after code changes. To start
Meeting Memory automatically at login:

```bash
make PYTHON=.venv/bin/python install-launch-agent
```

`make doctor` renders one status for Recording Core, Transcription, Backup,
Calendar, and Notes. Its exit status requires usable Recording Core and Backup;
missing optional integrations remain `unconfigured`. The tray's **Debugging ›
Check Setup & Dependencies** action renders the same report on a background
worker. Neither path contacts a provider; configured Calendar may read its
existing OAuth token from Keychain during the explicit check. The local check
does not request macOS capture permissions, so Recording Core may remain
`degraded` until the selected mode validates permissions at recording start.

The clickable app is installed at `~/Applications/Meeting Memory.app` so it can
be launched from Finder or found with Cmd+Space by searching for
`Meeting Memory`.

To remove the login item:

```bash
make PYTHON=.venv/bin/python uninstall-launch-agent
```

## Using the App

Meeting Memory runs as a menu-bar app. Use `Start Recording` for ad-hoc calls,
or click `Record` from a pre-meeting notification when the calendar watcher
detects an upcoming Meet or Zoom event. Manual start uses only watcher-cached
Calendar context; without one, the app records under a provisional title and
asks for the final title after stop.

Choose the audio mode for the next recording from the tray:

- **Full Meeting** records system audio plus the current macOS microphone. Your
  current output, including AirPods, keeps playing normally.
- **Silent System Only** records system audio with the microphone off and mutes
  that system audio while recording.

Meeting Memory captures these streams through native macOS APIs. It does not
change the user's input/output devices and does not require BlackHole,
Aggregate Devices, or per-device configuration. The durable capture is first a
16 kHz mono WAV; conversion prefers AVFoundation and uses the separately
bundled, offline minimal LGPL encoder only when the host lacks AAC encoding.

While recording, the status bar shows a live timer and the tray menu switches to
`Stop Recording`. When a calendar-backed recording reaches the event end time,
the app sends a `Stop` reminder action. After transcription finishes, the app
writes `transcript.md`; the completion notification opens the meeting directory
so you can review speaker aliases.

If the app crashes during recording, restart it and check the tray for
**Debugging › Interrupted Recordings**. Failed B2 uploads can be retried with
**Debugging › Retry Pending B2 Backups**, and failed transcription states can
be retried with **Debugging › Retry Failed Transcriptions**. Old recordings
left in the former macOS temp location are scanned only when you choose
**Debugging › Find Legacy Recordings...**; the scan itself never starts cloud
work.

By default, the calendar watcher scans all non-deleted calendars accessible to
the authenticated Google account. Set `GOOGLE_CALENDAR_ID=primary` or a
specific calendar ID to narrow the watcher.

## Setup Guides

- [Full setup tutorial](docs/setup-tutorial.md)
- [Setup guide for coding agents](docs/agent-setup.md)
- [Removing legacy BlackHole setup](docs/blackhole-setup.md)
- [Google Calendar auth](docs/google-calendar-auth.md)
- [Manual validation checklist](docs/manual-validation.md)
- [Development workflows](docs/dev-workflows.md)
- [Publishing and privacy checklist](docs/publishing-checklist.md)
- [Deferred work and product notes](docs/deferred-work.md)
- [Local-first capability contract](docs/local-first-contract.md)

## Configuration

The app resolves configuration with this precedence: exact process-environment
name, active app preference/Keychain reference, legacy `.env`, then built-in
default. A missing app preference document preserves legacy behavior. An
unreadable app document fails optional egress closed unless a complete valid
process group overrides it; Recording Core remains local and available.

Recording Core (all have defaults):

- `MEETINGS_DIR`
- `MAX_RECORDING_MINUTES`

Optional Transcription:

- `ASSEMBLYAI_API_KEY`

Required Backup (the complete group unlocks the normal recording UI):

- `B2_APPLICATION_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_ENDPOINT`
- `B2_REGION`
- `B2_BUCKET_NAME`

Use a private bucket dedicated to Meeting Memory and an application key that
can read and write only that bucket. Do not reuse sample-app buckets.

Optional Calendar:

- `GOOGLE_CALENDAR_CREDENTIALS_FILE`
- `GOOGLE_CALENDAR_ID`

Optional Notes:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `SUMMARY_PROMPT_FILE`

Other optional local settings:

- `KNOWN_SPEAKERS`
- `NOTIFY_MINUTES_BEFORE`
- `CALENDAR_POLL_INTERVAL`

See [.env.example](.env.example).

## Privacy and Secrets

Real credentials, OAuth files, local recordings, transcripts, generated meeting
folders, and `.env` are ignored by git. Before publishing or pushing changes,
run the checks in [docs/publishing-checklist.md](docs/publishing-checklist.md).

Phase 4B composes the Phase 4A private preference store, immutable
generation-based Keychain secret references, legacy `.env`, and value-free
source provenance through fixed consumer scopes. Runtime and explicit
readiness load only the active generic Keychain references they need; auth,
search, and summarize use narrower scopes. The existing Google OAuth Keychain
identity is unchanged. Composition performs no provider request and never
writes `.env`, preferences, or Keychain. Phase 4C provides the
identity/digest-bound, non-destructive `.env` preview and confirmed migration
engine. Phase 4D exposes it only through an explicit native action and adds
per-capability app-owned forms, blank secure credential fields, exact egress
disclosures, explicit Calendar authorization, and worker-to-main typed events.
Successful optional changes pause current-session egress before their terminal
event; enablement and replacement take effect after relaunch. No reachable UI
action rewrites `.env`, and startup never previews, migrates, authorizes, or
runs readiness automatically.

`KNOWN_SPEAKERS` is intentionally empty by default. Use the tray's
**Configuration › Calendar...** structured speaker editor to add local aliases
for normalizing Calendar speaker candidates. The app stores them in app-owned
preferences at
`~/Library/Application Support/meeting-memory/preferences.json`, outside the
repository and with private filesystem permissions. Each row has one display
name and zero or more attendee names, emails, or email local-parts to match.

## Costs

Prices change; check provider pricing before recording long meetings.

As of 2026-06-11, AssemblyAI lists Universal-2 pre-recorded transcription at
`$0.15/hr` and speaker diarization at `$0.02/hr`, so this app's diarized
transcription path is roughly `$0.17/hr` before any optional features. See
[AssemblyAI pricing](https://www.assemblyai.com/pricing).

As of 2026-08-12, Backblaze lists B2 pay-as-you-go storage starting at
`$6.95/TB/month`, with free transactions and free egress up to 3x average
monthly storage. See [Backblaze B2 pricing](https://www.backblaze.com/cloud-storage/pricing).

Anthropic summary cost depends on the selected model, transcript length, and
current Anthropic pricing. Each request sends the fixed output-schema
instructions, your configured editable prompt, and only a speaker-confirmed
transcript excerpt capped at 60,000 characters.

## Summary Prompt

The versioned built-in template lives at
[prompts/summary.md](prompts/summary.md), but the app never writes personal
changes there. Until you customize it, the app uses that built-in text as a
fallback. Saving from the tray creates the private personal copy at
`~/Library/Application Support/meeting-memory/prompts/summary.md`, in checkout
and bundled execution alike. Set `SUMMARY_PROMPT_FILE` explicitly only when a
development or legacy workflow needs another path. If the selected file
contains `{transcript}`, the app replaces that placeholder with the clipped
transcript; otherwise it appends the transcript below the prompt.

Choose **Configuration › Notes Prompt...** in the tray to edit the effective
additional instructions in a native multiline editor. The required JSON output
contract stays fixed so custom text cannot change the parser-facing schema.
Saving updates the effective personal prompt file, and the next notes
generation uses the new text without restarting the app. The editor can also
restore the built-in default into that personal copy.

## Speaker Review

`transcript.md` is the source-of-truth transcript. It includes candidate
speaker names from Google Calendar attendees. Attendees are shown by their
Calendar full name, except configured matches from `KNOWN_SPEAKERS`, plus
editable aliases:

```yaml
speaker_candidates: ["Alex", "Ada Lovelace", "Casey"]
speaker_aliases: {"Speaker A": "Alex", "Speaker B": "Ada Lovelace"}
speaker_status: "needs_review"
```

After reviewing speakers from the tray UI, the app applies aliases locally and
starts notes generation automatically. For CLI backfill or repair, edit
`speaker_aliases` and apply the deterministic relabel step:

```bash
meeting-memory relabel ~/Meetings/<meeting-folder>
```

That updates `transcript.md` so the transcript itself says who said what.
Then generate or retry derived notes:

```bash
meeting-memory summarize ~/Meetings/<meeting-folder>
```

This writes `notes.md` with Summary, Decisions, and Action Items. If notes are
missing, skipped, or failed after speakers are confirmed, the tray shows it
under **Debugging › Pending Meeting Tasks**. No LLM is used for relabeling;
Anthropic is used for notes generation.

Per-meeting `speaker_aliases` are the source of truth for who spoke in a
specific recording. Global `Speaker A` / `Speaker B` mappings are intentionally
not supported because AssemblyAI labels can change between transcription jobs.

## Local Search

Search saved meeting markdown from the terminal:

```bash
meeting-memory search "launch risks"
```

## Known Limitations

- The `.app` bundle is a local wrapper around this repo and its Python virtual
  environment, not yet the standalone signed/notarized artifact. Runtime paths
  are already checkout/bundle aware and do not depend on the launch cwd.
- Reproducible thin `arm64` and `x86_64` standalone builds are documented in
  [docs/distribution.md](docs/distribution.md). Current CI artifacts are ad-hoc
  validation builds, not public Gatekeeper-ready releases.
- Recording requires an explicit user start. The app can remind the user to
  stop at the calendar event end time, but fully automatic recording is out of
  scope.
- Speaker labels are preserved by default until you confirm aliases in
  `transcript.md`.
- Calendar watching uses all accessible calendars by default; set
  `GOOGLE_CALENDAR_ID` to a specific ID to narrow it.
- Failed B2 uploads can be retried with `Retry Pending B2 Backups`. Failed
  transcription can be retried with `Retry Failed Transcriptions`; fully automatic
  connectivity-aware background queueing is future work.
- Enabling a capability or changing its credentials/destination requires
  quitting and reopening the app. Disable pauses new current-session egress;
  process environment overrides can enable it again after restart.
