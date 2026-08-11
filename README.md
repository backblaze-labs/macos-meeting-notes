# macos-meeting-notes

> ⚠️ **Experimental.** This is an experimental
> sample app, not an officially supported Backblaze product. APIs, setup steps, and
> behavior may change without notice. Use at your own risk.

`macos-meeting-notes` is the repository for **Meeting Memory**, a local-first
macOS menu-bar app that records meetings, optionally transcribes them with
speaker diarization (AssemblyAI), optionally summarizes them (Anthropic
Claude), saves portable artifacts locally, and optionally backs up each
meeting's audio and transcript to Backblaze B2 over the S3-compatible API.

The repository/distribution name is `macos-meeting-notes`; the app visible to
users remains **Meeting Memory**, the Python import package remains
`meeting_memory`, and the installed CLI remains `meeting-memory`.

The app is local-first: each completed recording creates a directory under
`MEETINGS_DIR` containing:

- `recording.m4a`
- `transcript.md`
- `notes.md` after you confirm speaker aliases and generate derived notes

B2 is the durable backup layer. The local files remain the user's readable
meeting archive.

The local-first runtime makes **Recording Core** usable without a
Terminal, account, key, or network, with Transcription, Backup, Calendar, and
Notes enabled progressively. See
[the capability contract](docs/local-first-contract.md). Complete legacy
`.env` groups opt in to AssemblyAI, B2, Calendar, or Notes independently; a
missing or broken optional integration does not prevent local recording.

The first-value acceptance test is concrete: record about 30 seconds of real
audio, stop, play the saved result, and reveal its meeting directory in Finder
within five minutes of first launch.

## Requirements

- macOS 15 Sequoia or later
- Python 3.11 or later
- Xcode Command Line Tools (`xcode-select --install`)
- Optional Google Calendar OAuth desktop credentials
- Optional AssemblyAI API key
- Optional dedicated Backblaze B2 bucket and S3-compatible application key
- Optional Anthropic API key for summaries

## Quick Start

For a full fresh-clone walkthrough, follow
[docs/setup-tutorial.md](docs/setup-tutorial.md).

```bash
make setup
```

`make setup` creates `.venv`, installs dependencies, creates `.env` if needed,
installs the local app wrapper, and prints a setup checklist. You can open the
core app immediately:

```bash
make PYTHON=.venv/bin/python open-macos-app
```

`make doctor` renders one status for Recording Core, Transcription, Backup,
Calendar, and Notes. It exits successfully whenever Recording Core is usable;
missing optional integrations are `unconfigured`, not app failures. The tray's
**Debugging › Check Setup & Dependencies** action renders the same report on a
background worker. Neither path contacts a provider; configured Calendar may
read its existing OAuth token from Keychain during the explicit check. The
local check does not request macOS capture permissions, so Recording Core may
remain `degraded` until the selected mode validates permissions at recording
start.

The clickable app is installed at `~/Applications/Meeting Memory.app` so it can
be launched from Finder or found with Cmd+Space by searching for
`Meeting Memory`.

After changing app code, reload the official local app bundle:

```bash
make PYTHON=.venv/bin/python reload-macos-app
```

To start Meeting Memory automatically at login as a background menu-bar app:

```bash
make PYTHON=.venv/bin/python install-launch-agent
```

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
Aggregate Devices, or per-device configuration.

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

Optional Backup (the complete group enables it):

- `B2_APPLICATION_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_ENDPOINT`
- `B2_REGION`
- `B2_BUCKET_NAME`

Use a bucket dedicated to Meeting Memory and an application key that can read
and write only that bucket. Do not reuse sample-app buckets.

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
writes `.env`, preferences, or Keychain. Phase 4C now provides the inactive
service engine for explicit, identity/digest-bound, non-destructive `.env`
preview and confirmed migration. It is not called by startup, the CLI, or the
current UI. Phase 4D's internal edit/CAS and runtime-pause foundation is now in
place, but the dependent native slice still must add the trigger,
per-capability disclosure, secure entry, background events, and Calendar auth.
Until that UI ships, continue using the legacy configuration flow.

`KNOWN_SPEAKERS` is intentionally empty by default. Use the tray's
**Configuration › Known Speakers...** item to add local aliases for normalizing
Calendar speaker candidates. The app stores them in `.env` as a JSON object
whose keys are display names and whose values are attendee names, emails, or
email local-parts to match, for example
`{"Alex Rivera":["alex@example.com","alex.rivera"]}`.

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
current Anthropic pricing. Each request sends the fixed output-schema
instructions, your configured editable prompt, and only a speaker-confirmed
transcript excerpt capped at 60,000 characters.

## Summary Prompt

The default summary prompt lives at [prompts/summary.md](prompts/summary.md).
Set `SUMMARY_PROMPT_FILE` to point at another prompt file. If the file contains
`{transcript}`, the app replaces that placeholder with the clipped transcript;
otherwise it appends the transcript below the prompt.

Choose **Configuration › Notes Prompt...** in the tray to edit the effective
additional instructions in a native multiline editor. The required JSON output
contract stays fixed so custom text cannot change the parser-facing schema.
Saving updates `SUMMARY_PROMPT_FILE`, and the next notes generation uses the new
text without restarting the app. The editor can also restore the built-in
default.

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
  environment, not a standalone signed/notarized binary.
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
- The preferences window edits `.env`; restart the app after saving changes.
