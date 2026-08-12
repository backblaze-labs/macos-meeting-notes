# Software Requirements Specification
# `macos-meeting-notes` — Meeting Memory macOS Meeting Notes App

**Status:** Draft  
**Author:** Meeting Memory contributors
**Date:** 2026-08-07
**Version:** 0.6
**Methodology:** RFC-inspired SRS (requirement language per RFC 2119: MUST / SHOULD / MAY / MUST NOT)

**Revision note (v0.2):** Added a second, first-class design goal — **the
repository must be easy for AI coding agents to read and modify** — using an
`AGENTS.md` control surface, import-enforced module layering, mechanical
structural tests, a doctor preflight, and fail-fast config. §7 was restructured
into enforced layers (§7.1, §7.5, §7.6) and all v0.1 Open Questions were
resolved (§11).

**Revision note (v0.3):** Aligned the spec with the implemented macOS app wrapper, LaunchAgent workflow, all-calendar default (`GOOGLE_CALENDAR_ID=all`), notification actions (`Record`, `Open`, `Stop`), status-bar recording timer, calendar-context recording titles, configurable summary prompt, recording auto-stop, temp-recording recovery, retry/backoff, failed-processing retry, local search, separate `transcript.md` / `notes.md` artifacts, Calendar-derived speaker candidates, and manual speaker aliases. Remaining product limitations are called out in §10.

**Revision note (v0.4):** Accepted the phased local-first capability contract.
Recording Core is the only first-value gate; Transcription, Backup, Calendar,
and Notes are independent optional capabilities. The current fail-fast runtime
is explicitly legacy until the implementation phases replace it. See §2.5 and
`docs/local-first-contract.md`. The v0.6 onboarding policy supersedes the
Backup-optional portion of this historical note.

**Revision note (v0.5):** Made the durable WAV-to-M4A boundary independent of
the host's optional AudioToolbox AAC encoder. Conversion prefers AVFoundation
and falls back offline to a separately bundled, minimal LGPL FFmpeg executable
compiled from pinned source with networking and unrelated codecs disabled.

**Revision note (v0.6):** Made a complete Backblaze B2 configuration a required
onboarding gate. Recording remains locally durable and provider failures remain
isolated after setup; Transcription, Calendar, and Notes remain optional.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Overall Description](#2-overall-description)
3. [External Interface Requirements](#3-external-interface-requirements)
4. [Functional Requirements](#4-functional-requirements)
5. [Non-Functional Requirements](#5-non-functional-requirements)
6. [Data Models](#6-data-models)
7. [System Architecture](#7-system-architecture)
8. [Configuration Reference](#8-configuration-reference)
9. [Constraints and Assumptions](#9-constraints-and-assumptions)
10. [Future Work (Out of Scope for v1)](#10-future-work-out-of-scope-for-v1)
11. [Resolved Decisions](#11-resolved-decisions)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements for **Meeting Memory**, a macOS menu
bar application whose repository is named **macos-meeting-notes**. The app
records meetings locally, backs up portable artifacts to required Backblaze B2
storage, and can optionally transcribe them with speaker diarization and
generate AI summaries.

### 1.2 Scope

`macos-meeting-notes` is a Python application repository targeting macOS. It is designed as a personal productivity tool and as a Backblaze B2 sample demonstrating local-first AI data pipelines with object storage as the durable backup layer.

Naming is intentionally split during the low-risk external rename: the visible app remains **Meeting Memory**, the Python import package remains `meeting_memory`, and the CLI remains `meeting-memory`. The macOS bundle ID, Keychain service, LaunchAgent label, and log paths keep their current `meeting-memory` identifiers until a deliberate migration is planned.

It is a native, local-first B2 sample: rather than a browser upload flow, it
captures real system + microphone audio on the desktop and saves it locally.
B2 is the required durable archive; users may opt into calendar context,
remote transcription, and derived notes.

A **second, explicit design goal** sits alongside the user-facing app: the
repository itself must be **easy for AI coding agents to read and modify**.
The repo uses an authoritative `AGENTS.md`, import-enforced layering,
mechanical structural tests, a doctor preflight, and fail-fast configuration
(see §7.5 and §7.6).

### 1.3 Definitions

| Term | Definition |
|---|---|
| **Meeting** | A calendar event with a Google Meet or Zoom URL |
| **Recording session** | The period between "Start Recording" and "Stop Recording" |
| **Audio mode** | A tray-selectable native capture policy for the next recording; it does not change macOS audio devices |
| **Native audio helper** | The bundled Swift subprocess that captures ScreenCaptureKit/Core Audio streams and writes WAV data |
| **Diarization** | Speaker segmentation: labeling transcript segments by speaker identity |
| **Meeting slug** | URL-safe identifier derived from the meeting date/time and calendar title (e.g. `2026-06-10_09-00_standup`) |
| **Meeting directory** | Local folder `$MEETINGS_DIR/<slug>/` containing `recording.m4a`, `transcript.md`, and optional `notes.md` |
| **B2** | Backblaze B2 cloud storage, accessed via the S3-compatible API |

### 1.4 References

- AssemblyAI Universal-2 transcription API docs
- Anthropic Claude API (claude-haiku-4-5)
- Google Calendar API v3
- Apple ScreenCaptureKit and Core Audio frameworks
- RFC 2119 key words for requirement levels
- Backblaze B2 S3-compatible API

---

## 2. Overall Description

### 2.1 Product Perspective

**Meeting Memory** is a standalone macOS application with no server-side
component, maintained in the `macos-meeting-notes` repository. It runs as a
menu bar process, interfaces with external services (Google Calendar,
AssemblyAI, Anthropic, B2) via HTTPS, and reads/writes to the local filesystem.
There is no web UI, no application database, and no always-on server.

```
┌─────────────────────────────────────────────────┐
│                  macOS                           │
│  ┌──────────────┐    ┌───────────────────────┐  │
│  │  meeting-    │    │  ~/Meetings/           │  │
│  │  memory      │◄──►│    2026-06-10_standup/ │  │
│  │  (tray app)  │    │      transcript.md     │  │
│  └──────┬───────┘    │      recording.m4a     │  │
│         │            └───────────────────────┘  │
│  ┌──────▼────────────┐                          │
│  │ Native Audio      │                          │
│  │ system + mic      │                          │
│  │ or muted system   │                          │
│  └───────────────────┘                          │
└────────────────────────┬────────────────────────┘
                         │ HTTPS
         ┌───────────────┼───────────────────┐
         ▼               ▼                   ▼
  Google Calendar   AssemblyAI         Backblaze B2
  API v3            (transcription     (object storage
  (event polling)    + diarization)     backup)
                         │
                    Anthropic Claude
                    (summarization)
```

### 2.2 Product Functions (Summary)

- F0: Local-first capability readiness — require B2 configuration for onboarding while preserving local artifacts through provider failures
- F1: Optional calendar watching — detect upcoming meetings with video conferencing links
- F2: Pre-meeting notification — remind the user to start recording
- F3: Audio recording — natively capture system audio with optional microphone and playback by mode
- F4: Optional transcription — diarized speech-to-text via AssemblyAI
- F5: Optional summarization — extract summary, decisions, and action items via Claude
- F6: Local storage — save structured markdown + audio to `~/Meetings/`
- F7: Required B2 backup — upload meeting artifacts to Backblaze B2 after local write
- F8: Tray menu — control recording, browse recent meetings, trigger sync
- F9: Completion notification — alert user when transcript is ready
- F10: Local macOS app wrapper — install, reload, launch, quit, and optionally start at login
- F11: Local search and retry tools — search stored meetings and retry failed processing

### 2.3 User Characteristics

Primary user: a knowledge worker who attends multiple video meetings per week, wants a private transcript archive, and uses Claude Code or other AI tools to query their meeting history.

Technical profile: no Terminal or developer experience is required for the
first-value path. Advanced development and legacy-checkout workflows may use
the CLI.

### 2.4 Constraints

- macOS 15 (Sequoia) or later
- The current source-checkout wrapper requires Python 3.11+ and Xcode Command
  Line Tools; the Phase 6 distributed target MUST bundle its runtime/helper and
  MUST NOT require developer tools
- Recording requires the user to explicitly trigger start/stop (no fully automatic recording)
- Recording Core preserves captures without internet access after onboarding
- B2 credentials are required for onboarding; uploads require internet access,
  while a temporary provider or network failure does not remove local artifacts
- Transcription, summarization, and Calendar require internet access only when
  the user enables them
- Google Calendar OAuth credentials are required only for the optional Calendar capability
- The current checkout-installed `.app` is a local wrapper around this repo and
  Python environment; the Phase 6 distributed target is signed, notarized, and
  standalone

### 2.5 Local-First Capability Contract

`docs/local-first-contract.md` is canonical for composition, readiness,
durable-audio lifecycle, privacy/data egress, secret ownership, compatible
migration, and phase acceptance. If a pre-v0.4 statement implies that an
provider reachability blocks local commit, the local-first contract takes
precedence.

**REQ-LF-01** A new user MUST configure a Backblaze B2 account, dedicated
private bucket, and bucket-scoped application key before the normal recording
UI becomes available. After setup, a temporary network or provider failure MUST
NOT prevent local commit, playback, or reveal-in-Finder behavior.

**REQ-LF-02** The application MUST model Recording Core, Transcription, Backup,
Calendar, and Notes as separate capabilities. Recording Core and complete
Backup configuration MAY gate access to Start Recording. Live B2 reachability
MUST NOT gate local commit after onboarding.

**REQ-LF-03** Each capability MUST report exactly one of `unconfigured`,
`checking`, `ready`, `degraded`, or `failed`, with a plain-language summary and
an actionable recovery step. `unconfigured`, `degraded`, and `failed` MUST have
a non-empty action; only `checking` and `ready` MAY omit it.

**REQ-LF-04** The default doctor and in-app setup check MUST share one typed
readiness report. Default doctor success MUST require usable Recording Core and
Backup configuration; Transcription, Calendar, and Notes failures MUST remain
visible and non-blocking.

**REQ-LF-05** The application MUST commit durable local audio plus its schema-v2
metadata stub before invoking an optional remote adapter. Optional failures
MUST NOT delete, replace, or hide that local artifact.

**REQ-LF-06** Before an integration is enabled, the app MUST identify what data
leaves the Mac, which provider receives it, and what automatic trigger sends it.

**REQ-LF-07** Runtime API secrets and OAuth tokens MUST be owned by the installed
app and stored in macOS Keychain in the target progressive-configuration flow.
They MUST NOT appear in diagnostics, logs, notifications, or meeting artifacts.

**REQ-LF-08** Migration from recognized `.env` values MUST be explicit,
non-destructive, and compatible with existing meeting data and identifiers. The
app MUST NOT delete or rewrite `.env` automatically.

**REQ-LF-09** Delivery MUST follow the acceptance phases in the canonical
contract. Contract/type work MUST NOT claim that later runtime, onboarding, or
standalone-distribution acceptance criteria are already implemented.

**REQ-LF-10** Enabling an integration MUST apply its documented automatic
trigger only to recordings committed after opt-in. Historical meeting
processing or upload MUST require an explicit user backfill/retry action.

---

## 3. External Interface Requirements

### 3.1 Google Calendar API

**REQ-EXT-01** When Calendar is configured, the application MUST authenticate to the Google Calendar API using OAuth 2.0 with the `https://www.googleapis.com/auth/calendar.readonly` scope.

**REQ-EXT-02** OAuth tokens MUST be stored in the macOS Keychain, not in a plain-text file on disk.

**REQ-EXT-03** The application MUST support a one-time interactive auth flow triggered by `python -m meeting_memory auth`, which opens a browser and saves the resulting token to the macOS Keychain.

**REQ-EXT-04** The application MUST automatically refresh expired OAuth tokens using the stored refresh token, without user interaction.

### 3.2 AssemblyAI Transcription API

**REQ-EXT-05** When Transcription is configured and invoked, the application MUST upload audio to AssemblyAI using the `assemblyai` Python SDK (not raw HTTP).

**REQ-EXT-06** Every transcription request MUST include `speaker_labels=True` to enable diarization.

**REQ-EXT-07** The application MUST poll AssemblyAI for job completion, with a polling interval of 5 seconds and a maximum wait time of 30 minutes.

**REQ-EXT-08** If the transcription job fails (status `error`), the application MUST update the existing `transcript.md` stub with a safe failure state and recovery action, MUST NOT expose a raw provider exception, and MUST preserve the committed local audio.

### 3.3 Anthropic Claude API

**REQ-EXT-09** When Notes is configured and invoked, the application MUST use the `anthropic` Python SDK to call Claude, defaulting to `claude-haiku-4-5` and honoring an optional `ANTHROPIC_MODEL` override (§8).

**REQ-EXT-10** The summarization prompt MUST request three structured outputs in a single call: (a) a summary paragraph, (b) a bullet list of decisions, (c) a list of action items each with optional owner name.

**REQ-EXT-11** If the Claude API call fails or times out, the application MUST leave `transcript.md` untouched and write a failed/skipped derived-notes state without blocking transcript completion.

**REQ-EXT-12** Each Anthropic request MUST contain the fixed output-schema
instructions, the configured editable prompt, and only speaker-confirmed
transcript text. It MUST NOT include more than the first 60,000 transcript
characters.

### 3.4 Backblaze B2 (S3-Compatible API)

**REQ-EXT-13** When Backup is configured and invoked, the application MUST access B2 exclusively via the S3-compatible API endpoint (`B2_ENDPOINT`). The b2-native API MUST NOT be used.

**REQ-EXT-14** Every `boto3` S3 client instance MUST be initialized with `botocore.config.Config(user_agent_extra='b2ai-meeting-memory')`.

**REQ-EXT-15** When B2 configuration is supplied through the legacy `.env` or
process-environment compatibility paths, it MUST use the following names; no
alternate environment aliases are accepted. The app-managed target stores the
secret values in Keychain per REQ-LF-07:
```
B2_APPLICATION_KEY_ID
B2_APPLICATION_KEY
B2_ENDPOINT
B2_REGION
B2_BUCKET_NAME
```

### 3.5 Audio Capture Interface

**REQ-EXT-16** In Full Meeting mode, the application MUST capture system audio and the current macOS default microphone while leaving system playback audible through the current output device.

**REQ-EXT-17** In Silent System Only mode, the application MUST capture system audio, MUST NOT capture the microphone, and MUST mute playback for the recording's lifetime.

**REQ-EXT-17a** Neither audio mode MAY change the current macOS input or output device. BlackHole, Aggregate Devices, Multi-Output Devices, and per-device environment configuration MUST NOT be required.

**REQ-EXT-18** If native capture cannot start because the helper, hardware, or macOS permissions are unavailable, the application MUST surface a visible, actionable error rather than silently failing.

**REQ-EXT-19** Audio MUST be captured at 16000 Hz sample rate, mono channel,
and encoded as a 16-bit PCM WAV during capture. Before local publication or
upload, it MUST be converted to a validated 16000 Hz mono AAC-bearing M4A.
Conversion MUST prefer AVFoundation when the host exposes AAC encoding and MUST
otherwise use the bundled, offline, minimal LGPL encoder. The fallback MUST
have networking disabled and MUST accept only the app's fixed WAV-to-AAC/M4A
operation.

---

## 4. Functional Requirements

### F1: Calendar Watcher

**REQ-F1-01** When Calendar is `ready` or `degraded`, the calendar watcher MUST start automatically when the application launches. When Calendar is `unconfigured` or `failed`, the watcher MUST remain stopped without blocking ad-hoc recording.

**REQ-F1-02** The watcher MUST poll the Google Calendar API every 120 seconds (configurable via `CALENDAR_POLL_INTERVAL`).

**REQ-F1-03** The watcher MUST fetch events that start within the next `NOTIFY_MINUTES_BEFORE + 2` minutes (lookahead window) from the calendar scope configured by `GOOGLE_CALENDAR_ID`. The default value `all` means every non-deleted calendar accessible to the authenticated account; `primary` or a specific calendar ID narrows the scope.

**REQ-F1-04** An event is considered a "meeting" if its `description`,
`location`, Google Calendar `hangoutLink`, or Google Calendar `conferenceData`
fields contain at least one of:
- `meet.google.com`
- `zoom.us/j/`
- `zoom.us/s/`

**REQ-F1-05** Events whose self attendee response is `declined` MUST NOT be considered meetings for notification purposes.

**REQ-F1-06** The watcher MUST NOT fire a notification for the same event more than once per application session.

**REQ-F1-07** The watcher MUST run on a background thread and MUST NOT block the tray menu or any UI interaction.

### F2: Pre-Meeting Notification

**REQ-F2-01** When a meeting is detected (per REQ-F1-04) that starts within `NOTIFY_MINUTES_BEFORE` minutes, the application MUST send a macOS User Notification with:
- Title: `"Meeting starting soon"`
- Body: `"<calendar_title> starts in <N> minutes"`
- Action button: `"Record"` — clicking starts recording immediately

**REQ-F2-02** The application MUST send the notification no more than once per detected meeting, regardless of how many polling cycles occur before the meeting starts.

**REQ-F2-03** If the user dismisses the notification without clicking "Record", no recording MUST be started automatically.

### F3: Recording Control

**REQ-F3-01** The tray menu MUST expose a **Start Recording** item when no recording is active, and a **Stop Recording** item (with recording duration) when a session is active. While recording, the status-bar title MUST show a live duration timer.

**REQ-F3-02** The application MUST NOT allow more than one recording session to be active at a time. If **Start Recording** is triggered while a session is active, it MUST be ignored.

**REQ-F3-03** The tray MUST expose visible recording state through the status-bar timer and the **Stop Recording** menu label.

**REQ-F3-04** The application MUST accept start-recording input from two sources: (a) the tray menu item, (b) the "Record" action in a pre-meeting notification. It MUST accept stop-recording input from the tray menu and from a "Stop" notification action.

**REQ-F3-05** When recording starts, the application MUST resolve a title from the matched calendar event within ±5 minutes when available. If no matching event is available, manual tray starts SHOULD prompt for an ad-hoc title before falling back to `"Untitled"`.

**REQ-F3-06** The recording MUST be written incrementally to an app-owned
staging directory on the same filesystem as `MEETINGS_DIR` to prevent data loss
and permit atomic publication if the application crashes. Legacy system-temp
recordings remain discoverable only for compatible recovery.

**REQ-F3-07** A configurable maximum recording duration (`MAX_RECORDING_MINUTES`, default: 180) MUST exist in settings and preferences. If this limit is reached, the application MUST automatically stop recording, atomically commit the local artifacts, emit the recording-committed event, and enqueue only jobs whose capabilities are configured for that new recording.

**REQ-F3-08** The tray MUST expose Full Meeting and Silent System Only as the two audio modes for the next recording. Mode changes while recording MUST be rejected.

### F4: Transcription

**REQ-F4-01** When Transcription is `ready`, the transcription pipeline MUST start automatically after durable local audio is committed. When it is unavailable, the application MUST retain the local recording and expose transcription setup/retry without blocking recording completion.

**REQ-F4-02** The application MUST write the schema-v2 `transcript.md` metadata
stub before uploading audio to AssemblyAI. AssemblyAI is the source of truth
for remote transcript content, not for local artifact ownership or recording
completion.

**REQ-F4-03** Transcript segments MUST be formatted as `**<Speaker Label>** (<HH:MM:SS>): <text>` in `transcript.md`.

**REQ-F4-04** Speaker labels returned by AssemblyAI (e.g. "Speaker A", "Speaker B") MUST be preserved until the user either confirms local `speaker_aliases` or explicitly confirms that the detected labels should be kept. Keeping labels MUST leave `speaker_aliases` empty, set `speaker_status` to `confirmed`, and MUST NOT prevent Notes generation. The application MUST NOT infer real attendee names automatically.

**REQ-F4-05** After AssemblyAI creates a transcript job, the application MUST record its ID in the meeting's YAML frontmatter (`assemblyai_id` field) for future retrieval. Before then the field MUST remain `null`, never a failure sentinel.

**REQ-F4-06** Google Calendar attendees MAY populate `speaker_candidates`. Candidates SHOULD use the attendee's Calendar full name, except aliases explicitly configured in `KNOWN_SPEAKERS`. These candidates are hints for manual review, not automatic speaker identification.

**REQ-F4-07** `meeting-memory relabel <meeting-folder>` MUST apply `speaker_aliases` from `transcript.md` deterministically by code, without using an LLM or re-transcribing audio.

### F5: Summarization

**REQ-F5-01** When Notes is `ready`, summarization MUST start automatically
after UI speaker review confirms `speaker_status`, whether the user assigns
names or explicitly keeps the detected labels. When Notes is unavailable,
the reviewed transcript MUST remain complete and the Notes state MUST offer
setup/retry without blocking it. `meeting-memory summarize <meeting-folder>`
MUST remain available as a manual backfill/retry command for confirmed
transcripts.

**REQ-F5-02** The Claude prompt MUST instruct the model to produce output in a structured format parseable into three distinct sections: Summary, Decisions, and Action Items.

**REQ-F5-03** Each action item MUST include at minimum a task description. An owner name (extracted from context) SHOULD be included when identifiable. A due date SHOULD be included only when explicitly mentioned in the meeting.

**REQ-F5-04** Action items MUST be formatted as GitHub Flavored Markdown task list items: `- [ ] <owner>: <task>` or `- [ ] <task>` when no owner is identifiable.

**REQ-F5-05** The summarize command MUST write `notes.md` and MUST NOT modify `transcript.md`.

**REQ-F5-06** The summarization prompt MUST be configurable through `SUMMARY_PROMPT_FILE` and the tray's **Configuration › Notes Prompt...** editor. If the file contains `{transcript}`, the app MUST replace that placeholder with the clipped transcript; otherwise it MUST append the transcript below the prompt text. A saved UI change MUST apply to the next notes generation without an app restart.

### F6: Local Storage

**REQ-F6-01** The application MUST create a meeting directory at `$MEETINGS_DIR/<slug>/` for every completed recording session, where `$MEETINGS_DIR` defaults to `~/Meetings`.

**REQ-F6-02** The meeting slug MUST follow the format `YYYY-MM-DD_HH-MM_<title-slug>` where:
- `YYYY-MM-DD_HH-MM` is the recording start time in local time
- `<title-slug>` is the calendar event title lowercased, with spaces replaced by hyphens, non-alphanumeric characters stripped, and truncated to 40 characters

**REQ-F6-03** Two closed, readable files MUST be durably committed to each meeting directory before optional network work:
- `recording.m4a` — the audio file (M4A/AAC format)
- `transcript.md` — a schema-v2 metadata stub that becomes the source-of-truth transcript when transcription succeeds

**REQ-F6-03a** The application MUST assemble both files in an app-owned staging
directory on the `MEETINGS_DIR` filesystem and atomically rename the completed
directory into its final collision-safe path. It MUST NOT expose a partially
committed final directory.

**REQ-F6-03b** `notes.md` MAY be generated later with summary, decisions, and action items after speaker aliases are confirmed.

**REQ-F6-04** `transcript.md` MUST contain a YAML frontmatter block (between `---` delimiters) as its first section, containing the fields specified in Section 6.1. Before transcription, its body MUST explain the local job state without raw provider exceptions.

**REQ-F6-05** `notes.md` MUST contain the following H2 sections in order when generated: `## Summary`, `## Decisions`, `## Action Items`. Each section MUST be present even if empty (use `_None identified._` as placeholder).

**REQ-F6-06** The application MUST update the `b2_audio`, `b2_transcript`, and `backup_status` frontmatter fields after a successful B2 upload (see F7).

**REQ-F6-07** The application MUST NOT delete or overwrite a meeting directory once created. If a slug collision occurs (same timestamp + title), it MUST append `-2`, `-3`, etc.

### F7: B2 Backup

**REQ-F7-01** With required Backup configured, the schema-v2 automatic policy MUST
upload exactly `recording.m4a` and `transcript.md` for eligible Meeting
Memory-owned meetings. `notes.md` is excluded unless a future separate opt-in
expands the disclosed scope. A failed upload MUST NOT block local completion;
missing or disabled Backup routes the app to setup before recording.

**REQ-F7-02** The B2 object key MUST follow the pattern: `meetings/<slug>/<filename>`.

**REQ-F7-03** B2 upload MUST NOT block the recording-saved notification. The
local-commit worker MUST enqueue the typed `RecordingCommitted` event after the
atomic commit and before any B2 attempt; the tray main thread renders the exact
REQ-F9-04 notification from that event.

**REQ-F7-04** If a B2 upload fails, the application MUST retry up to 3 times with exponential backoff (2s, 4s, 8s). After 3 failures, it MUST set `backup_status: failed`, retain local artifacts, and offer retry. When safely updating an existing legacy artifact, migration MAY preserve its legacy `b2_status`; new schema-v2 artifacts MUST NOT write that field.

**REQ-F7-05** The **Retry Pending B2 Backups** tray menu item MUST scan Meeting Memory-owned directories for `backup_status: pending | failed` and re-attempt upload. It MUST continue to recognize missing or `upload_failed` legacy `b2_status` during migration.

**REQ-F7-06** The application MUST NOT upload any file from `$MEETINGS_DIR`
that was not created by Meeting Memory. Schema-v2 ownership is identified by
`created_by: meeting-memory` and a supported `schema_version`, not by
`assemblyai_id`. Legacy ownership detection remains supported during migration.

**REQ-F7-07** `succeeded` is terminal for Transcription. For Backup only, if
the current content revision differs from `backup_uploaded_revision`,
`succeeded` MUST transition to `pending`, including while Backup is disabled.
If enabled, new-record workflow changes MAY re-enqueue automatically. If
disabled, pending work stays visible and MUST NOT run. Re-enabling Backup MUST
NOT auto-scan historical meetings; **Retry Pending B2 Backups** is the explicit
backlog action.

**REQ-F7-08** The Backup revision MUST be lowercase SHA-256 over the exact
`recording.m4a` bytes plus normalized `transcript.md`, using the domain-separated
length-framed algorithm in `docs/local-first-contract.md`. Normalization MUST
exclude only `backup_status`, `b2_audio`, `b2_transcript`, and
`backup_uploaded_revision`. Changes only to those fields MUST NOT re-enqueue.

**REQ-F7-09** A Backup worker MUST capture revision `R` and a matching immutable
audio/transcript snapshot. It MUST record `succeeded` and
`backup_uploaded_revision: R` only after both snapshot objects upload and the
current revision still equals `R`. If content changed it MUST leave the job
`pending`, automatically re-enqueueing only while Backup remains enabled.

**REQ-F7-10** Disabling Backup during `running` MUST prevent new requests and
retries. An in-flight request MAY finish to the next safe boundary. A complete
snapshot records its result subject to REQ-F7-09; a partial snapshot returns to
`pending`. Disabling Backup MUST NOT delete remote objects.

### F8: Tray Menu

**REQ-F8-01** The tray menu MUST contain the following items, in order:

```
● Meeting Memory                  (app title, non-interactive)
─────────────────
▶ Start Recording                 (or ■ Stop Recording · <HH:MM> while active)
─────────────────
Recent Meetings                   (section header, non-interactive)
  <date> · <title>  ×3           (one item per recent meeting, most recent first)
─────────────────
Open Meetings Folder
─────────────────
Configuration                      (hover submenu)
  Audio Mode
  Recording Core…
  Transcription…
  Backup…
  Calendar…
  Notes…
  Notes Prompt…
  Authorize Google Calendar…
  Import Legacy Configuration…
Debugging                          (hover submenu)
  Pending Meeting Tasks (<count>)
  Interrupted Recordings (<count>)  (when present)
  Retry Pending B2 Backups
  Retry Failed Transcriptions
  Check Setup & Dependencies
  Test macOS Notifications
Quit
```

**REQ-F8-02** Clicking a **Recent Meetings** item MUST open the corresponding meeting directory in Finder (not the `transcript.md` file directly, so the user can see all artifacts).

**REQ-F8-03** The **Recent Meetings** list MUST show at most 3 entries. If there are no meetings, the section MUST show `No meetings yet`.

**REQ-F8-04** The **Recent Meetings** list MUST be rebuilt from the filesystem each time the menu is opened (not cached in memory).

**REQ-F8-05** **Open Meetings Folder** MUST open `$MEETINGS_DIR` in Finder.

**REQ-F8-06** **Configuration** MUST expose one native form per capability.
Forms show only app-owned values, keep generic secrets blank in secure fields,
separate app intent from value-free process/legacy provenance, and require the
capability's egress disclosure before enabling or returning an explicit disable
to compatibility mode.

**REQ-F8-07** If recoverable temporary recordings are found, **Debugging** MUST show an **Interrupted Recordings** section with one action per recoverable item.

**REQ-F8-08** **Retry Failed Transcriptions** MUST scan local meeting directories and retry meetings whose transcript frontmatter indicates failed transcription.

**REQ-F8-09** **Check Setup & Dependencies** MUST rerun doctor-lite checks and surface the result through a notification and tray setup items.

**REQ-F8-10** **Test macOS Notifications** MUST send a local notification for validating macOS notification behavior.

**REQ-F8-11** **Configuration › Notes Prompt...** MUST open a native multiline editor for the effective `SUMMARY_PROMPT_FILE`, allow restoring the built-in default, reject an empty prompt, and show the file updated after saving.

**REQ-F8-12** **Configuration** and **Debugging** MUST be native hover submenus. Audio modes and user-editable settings MUST live under **Configuration**. Pending meeting tasks, interrupted recordings, backup/transcription retry, setup checks, and test notifications MUST live under **Debugging**, not at the tray root. Debugging actions MUST use explicit labels and native hover help that describes their scope.

### F9: Completion Notification

**REQ-F9-01** Only after `transcription_status` becomes `succeeded`, the
application MUST enqueue a typed transcript-ready event and the tray main
thread MUST send this separate macOS notification:
- Title: `"Transcript ready"`
- Body: `"<meeting-title> · review speakers"`
- Action button: `"Review Speakers"` — opens the speaker-review flow

**REQ-F9-02** Both the required recording-saved notification and any later
transcript-ready notification MUST be independent of Backup state or completion.

**REQ-F9-03** When `transcription_status` becomes `failed`, the worker MUST
enqueue typed `TranscriptionFailed`; the tray main thread MUST render this
mandatory notification without any worker UI call:
- Title: `"Transcription failed"`
- Body: `"<meeting-title> · audio saved locally"`
- Action button: `"Open"` — opens the meeting directory in Finder

**REQ-F9-04** Immediately after the audio and metadata stub are atomically
committed, the local-commit worker MUST enqueue `RecordingCommitted` and the
tray main thread MUST send this notification without waiting for any optional
capability:
- Title: `"Recording saved"`
- Body: `"<meeting-title> · audio saved locally"`
- Action button: `"Reveal"` — reveals the meeting directory in Finder

### F10: Local macOS App Wrapper and Login Item

**REQ-F10-01** The application MUST provide commands to install, reload, open, and quit a clickable local app bundle at `~/Applications/Meeting Memory.app`.

**REQ-F10-02** The local app bundle MUST run the current checkout with the selected Python executable and `PYTHONPATH=src`.

**REQ-F10-03** The local app bundle MUST be configured as a menu-bar/background app (`LSUIElement`) and include the Meeting Memory icon asset.

**REQ-F10-04** The application MUST provide commands to install and uninstall a LaunchAgent at `~/Library/LaunchAgents/com.meeting-memory.app.plist` so the menu-bar app can start at login.

**REQ-F10-05** The LaunchAgent MUST run the current checkout as a background process and write stdout/stderr to `~/Library/Logs/meeting-memory/`.

### F11: Local Search, Recovery, and Retry

**REQ-F11-01** The CLI MUST expose `meeting-memory search <query>` to perform case-insensitive full-text search across Meeting Memory-owned `transcript.md` files.

**REQ-F11-02** Search results MUST include the meeting date, title, markdown path, and a short excerpt.

**REQ-F11-03** The retry-processing flow MUST use durable
`transcription_status` to identify failed work. During migration it MUST also
recognize legacy failure sentinels without writing new sentinels.

**REQ-F11-04** Recovered recordings MUST be converted from staging/legacy temp
WAV to M4A and committed through the same local path as stopped recordings.
Legacy system-temp discovery is local-only and once per migrated profile; no
provider work starts until the user explicitly chooses recovery. Source temp
data is removed only after the atomic local commit succeeds.

---

## 5. Non-Functional Requirements

### 5.1 Performance

**REQ-NF-01** The tray menu MUST open and render within 300ms at all times, including during active recording or background pipeline processing.

**REQ-NF-02** All network calls (Google Calendar, AssemblyAI, Anthropic, B2) MUST run on background threads and MUST NOT execute on the main thread.

**REQ-NF-03** Audio capture MUST introduce no more than 100ms of latency between real-world sound and write to the app-owned staging buffer.

### 5.2 Reliability

**REQ-NF-04** If the application crashes during recording, partial audio in
app-owned staging MUST be discoverable from the tray on restart. If the user
selects recovery, the application MUST perform the normal atomic local commit
and enqueue only jobs currently configured for that explicit recovery.

**REQ-NF-05** The application MUST preserve local audio and write a usable, sanitized `transcript.md` failure state when AssemblyAI calls fail. AssemblyAI and Anthropic adapter calls MUST use explicit retry/backoff for transient failures and rate limits.

### 5.3 Security and Privacy

**REQ-NF-06** OAuth tokens for Google Calendar MUST be stored in the macOS Keychain using the `keyring` Python library. They MUST NOT be written to `.env` or any plain-text file.

**REQ-NF-07** The `.env` file MUST be listed in `.gitignore`. The repository MUST NOT include any real credentials.

**REQ-NF-08** App-owned B2 secret values MUST be read from macOS Keychain in
the progressive-configuration target. Legacy `.env` and process-environment
sources remain supported with the names and precedence in REQ-EXT-15 and the
local-first contract. Credentials MUST NOT be logged, displayed, or included in
error messages.

**REQ-NF-09** Meeting audio and transcripts are private by default. B2 objects MUST NOT be made public. No presigned URLs are generated or shared in v1.

### 5.4 Compatibility

**REQ-NF-10** The application MUST run on macOS 15 (Sequoia) or later on both Intel and Apple Silicon.

**REQ-NF-11** The application MUST NOT depend on any paid macOS feature or third-party subscription beyond the services listed in Section 3.

**REQ-NF-12** The Python application MUST be distributable as a `pip install`
from a Git URL. The repository MAY contain native-helper source and a pinned
third-party source recipe that setup compiles for the current Mac, but MUST NOT
commit a prebuilt third-party executable. The standalone app artifact MAY
bundle the separately built minimal LGPL audio encoder together with its
license and exact source/relinking information. Static UI assets such as the
app icon MAY be stored in the repository.

### 5.5 Observability

**REQ-NF-13** The application MUST write structured logs to `~/Library/Logs/meeting-memory/app.log` using Python's standard `logging` module at INFO level by default.

**REQ-NF-14** Each stage MUST emit a start/completion log with meeting slug and
elapsed time in lifecycle order: record, local-commit, then any configured
upload-to-assemblyai/poll, summarize, or b2-upload work.

### 5.6 Agent-Handleability

**REQ-NF-15** The structural tests in `tests/test_structure.py` MUST pass on every commit. The layering, SDK-containment, UI-containment, file-size, and required-module rules of §7.5–§7.6 are enforced mechanically, not by convention.

**REQ-NF-16** The doctor preflight (`python -m meeting_memory.doctor`) MUST report capability readiness and failures with a concrete fix. Its default exit status MUST follow REQ-LF-04; optional configuration checks remain informational unless an explicit integration check is requested.

**REQ-NF-17** Layer boundaries (§7.5) MUST be import-enforced: external SDKs only under `repo/`, `rumps` only under `ui/`, and no imports pointing "upward" in the layer order.

**REQ-NF-18** `AGENTS.md` and `ARCHITECTURE.md` MUST exist and be kept current. `AGENTS.md` is the read-first control surface for any agent or contributor, and `CLAUDE.md` MUST be a thin pointer to it.

**REQ-NF-19** No source file MAY exceed 300 lines; modules approaching the limit MUST be split by responsibility.

---

## 6. Data Models

### 6.1 transcript.md Frontmatter Schema

```yaml
---
schema_version: 2                # integer, local artifact schema
created_by: meeting-memory       # stable local ownership marker
id: <meeting-slug>               # string, matches directory name
date: <ISO-8601 datetime>        # recording start time, local timezone
duration_minutes: <integer>      # rounded to nearest minute
calendar_title: <string>         # from Google Calendar event, or "Untitled"
participants: [<string>, ...]    # speaker labels, or mapped speaker names when configured
assemblyai_id: <string | null>   # null until AssemblyAI assigns a remote job ID
transcription_status: not_requested | pending | running | succeeded | failed
speaker_candidates: [<string>, ...] # Calendar-derived known-speaker hints
speaker_aliases: {<label>: <name>}  # user-confirmed local aliases
speaker_status: not_available | needs_review | confirmed
b2_audio: <string | null>        # B2 object key, null until upload succeeds
b2_transcript: <string | null>   # B2 object key, null until upload succeeds
backup_status: not_requested | pending | running | succeeded | failed
backup_uploaded_revision: <sha256 | null> # last fully uploaded content revision
---
```

`transcription_status` and `backup_status` are per-meeting job states, not
capability readiness. Their transition graph is canonical in
`docs/local-first-contract.md`. New schema-v2 artifacts MUST NOT write
`b2_status`; compatibility readers still accept that legacy field while using
`backup_status` for new orchestration. Raw provider exceptions MUST NOT be
stored in user-facing transcript text.
`speaker_status` is `not_available` in the initial stub and changes to
`needs_review` only after diarized speaker labels exist.
`backup_uploaded_revision` is computed without a manifest using REQ-F7-08. Its
own value and the other Backup bookkeeping fields are excluded from the hash.

### 6.2 transcript.md Body Structure

```markdown
# Transcript

**Date:** <human-readable date and time>
**Duration:** <N> minutes
**Participants:** <comma-separated speaker labels>

**Speaker A** (0:00:05): <text>
**Speaker B** (0:00:12): <text>
…
```

### 6.3 notes.md Body Structure

```markdown
# Meeting Notes

**Source:** transcript.md

## Summary

<paragraph generated by Claude, or "_Summarization skipped._">

## Decisions

- <decision 1>
- <decision 2>
(or: _None identified._)

## Action Items

- [ ] <Owner>: <task>
- [ ] <task with no identified owner>
(or: _None identified._)
```

### 6.4 B2 Object Layout

```
meetings/
  <slug>/
    recording.m4a
    transcript.md
```

No additional manifest file. The `transcript.md` frontmatter serves as the per-meeting index record.

### 6.5 Local Directory Layout

```
$MEETINGS_DIR/            (default: ~/Meetings)
  <slug-1>/
    recording.m4a
    transcript.md
    notes.md              (optional, after summarize)
  <slug-2>/
    recording.m4a
    transcript.md
  …
```

---

## 7. System Architecture

### 7.1 Component Map (layered)

The codebase is organized into five strictly-ordered layers under `src/meeting_memory/`, plus cross-cutting modules. The layering exists so boundary rules are **mechanically enforceable** (§7.5–§7.6): every component maps to exactly one layer. This supersedes the flat component list of SPEC v0.1 — the same components are preserved, regrouped into layers.

| Layer | Package | Components (file → responsibility) |
|---|---|---|
| **types** | `types/` | `capabilities.py` (`Capability`, `CapabilityState`, `CapabilityStatus`, `MeetingJobState`, `ReadinessReport`) · `configuration.py` / `configuration_resolution.py` (Phase 4 allowlists, secret references, fixed consumer scopes, issues, enablement, and value-free provenance) · `meeting.py` (`MeetingMeta`, slug helpers-as-data) · `transcript.py` (`TranscriptResult`, `TranscriptSegment`) · `summary.py` (`SummaryResult` with decisions + action items) · `events.py` (UI events emitted to the tray: `MeetingDetected`, `NotifyEvent`, `RecordingStateChanged`). Pure data — **no SDK imports, no cross-layer imports.** |
| **config** | `config/` | Capability-scoped settings, typed schema, pure precedence resolution, and secret payload codec; depends only on `types`. `settings.py` retains characterized legacy APIs. Source I/O and active composition stay in `service/`. |
| **repo** | `repo/` | Existing provider/native adapters plus `secret_store.py`, the generic immutable-generation Keychain adapter activated only through opaque preference references. `calendar_client.py` retains the compatible Google OAuth Keychain identity. **The only layer permitted to import external SDKs.** |
| **service** | `service/` | Existing local orchestration plus readiness, the private atomic preference store, and `configuration_loader.py` with its bounded source readers and fixed runtime/readiness/auth/search/summarize scopes. Calls `repo`, returns `types`; **no `rumps`, no SDKs.** |
| **ui** | `ui/` | `tray.py` (`rumps.App` subclass; menu state, action dispatch, notifications, status timer, `rumps.Timer` draining the event queue) · `setup_readiness.py` (background setup check + UI rendering) · `controller.py` (recording/pipeline/sync handoff) · `menu.py` (menu label helpers) · `submenus.py` (Configuration and Debugging menu composition) · `preferences.py` (minimal settings window) · `notes_prompt.py` (native prompt editor) · `notifications.py` (rumps notification wrapper + fallback) · `title_prompt.py` (ad-hoc title prompt) · `macos.py` / `icons.py` (macOS UI helpers). **The only layer permitted to import `rumps`.** |
| *cross-cutting* | — | `__main__.py` (entrypoint; subcommands; logging; starts the capability-scoped runtime) · `doctor.py` (typed preflight renderer, §7.6) · `logging_config.py` (logs → `~/Library/Logs/meeting-memory/app.log`). |

### 7.2 Processing Sequence (Happy Path)

```
[User clicks Stop Recording]
        │
        ▼
Recorder.stop() → closes $MEETINGS_DIR/.meeting-memory-staging/<id>/recording.wav
        │
        ▼
LocalCommit.run(audio_path, meeting_meta)
  ├── Storage.write_audio(recording.m4a)
  ├── Storage.write_metadata_stub(transcript.md)  ← schema v2 + job states
  └── event_queue.put(RecordingCommitted)         ← typed boundary event
        │
        ▼
Tray main thread → notify("Recording saved")      ← first value is complete
        │
        ├── Transcription ready? enqueue pending job
        │     └── AssemblyAI upload → poll → update transcript/status
        │           └── event_queue.put(TranscriptReady) on success
        │           └── event_queue.put(TranscriptionFailed) on failure
        └── Backup ready? enqueue pending job
              └── capture revision R/snapshot → upload → compare current R

[User confirms speaker aliases or explicitly keeps detected labels]
        │
        ▼
Tray speaker review relabels transcript.md       ← local deterministic rewrite
        │
        ▼
Tray starts notes generation automatically
  ├── Summarizer.summarize(transcript)
  │       └── Claude API → SummaryResult
  └── Storage.write_notes_md(notes.md)

meeting-memory summarize <meeting-folder> remains available for manual
backfill/retry after speaker_status is confirmed.

The current runtime performs transcription before it writes full transcript
metadata. Its behavior is covered by legacy characterization tests and MUST be
replaced with the local commit boundary above in Phase 2.
```

### 7.3 Threading Model

- **Main thread**: `rumps` event loop (tray, menus, notifications)
- **Thread 1**: `CalendarWatcher` polling loop (daemon)
- **Native helper process**: ScreenCaptureKit/Core Audio callbacks, stream mixing, and incremental WAV writing
- **Thread 3**: `Pipeline` post-recording processing (created per session, joins before app quit)

The `TrayApp` communicates with background threads via a thread-safe
`queue.Queue`. Background threads MUST NOT call `rumps` UI methods directly —
instead they enqueue `types/events.py` objects (including the target
`RecordingCommitted`, `TranscriptReady`, and `TranscriptionFailed` events), and a `rumps.Timer` on the
main thread drains the queue and performs **all** `rumps` calls. This rule is
mechanically enforced: `rumps` may be imported only under `ui/` (§7.6,
`test_rumps_only_in_ui`). Local commit and optional workers emit typed events;
only the tray renders the REQ-F9-04, REQ-F9-01, and REQ-F9-03 notifications.

### 7.4 Project File Structure

```
macos-meeting-notes/
  src/
    meeting_memory/
      __main__.py            # entrypoint; subcommands + logging; starts capability-scoped runtime
      doctor.py              # preflight checks (§7.6)
      logging_config.py      # logging → ~/Library/Logs/meeting-memory/app.log
      types/                 # boundary models — no SDKs, no cross-layer imports
        __init__.py
        capabilities.py
        meeting.py
        transcript.py
        summary.py
        events.py
      config/                # pydantic-settings; fail-fast validation
        __init__.py
        settings.py
      repo/                  # ALL external-SDK calls live here, nowhere else
        __init__.py
        b2_client.py         # boto3 S3 adapter
        transcription.py     # AssemblyAI adapter
        summarizer.py        # Anthropic adapter
        calendar_client.py   # Google Calendar OAuth + Keychain
        native_audio.py      # native helper build/process adapter
        native/              # Swift ScreenCaptureKit/Core Audio helper source
        retry.py             # retry/backoff helper for external adapter calls
      service/               # orchestration; no rumps, no SDKs
        __init__.py
        readiness.py         # complete Recording Core + optional capability report
        readiness_integrations.py # isolated local checks for optional integrations
        storage.py
        markdown.py
        recorder.py
        pipeline.py
        calendar_watcher.py
        recording_context.py
        recovery.py
        processing_retry.py
        search.py
        speaker_mapping.py
        sync.py
        macos_app.py
        launch_agent.py
        assets/
          MeetingMemory.icns
      ui/                    # the only layer that imports rumps
        __init__.py
        tray.py
        setup_readiness.py   # background explicit check + typed UI handoff
        controller.py
        menu.py
        preferences.py
        notifications.py
        title_prompt.py
        macos.py
        icons.py
  tests/
    test_structure.py        # mechanical enforcement (§7.6): layering, SDK/UI containment, file size
    test_storage.py
    test_markdown.py
    test_transcription.py    (mocked)
    test_summarizer.py       (mocked)
    test_b2.py               (mocked)
    test_pipeline.py         (mocked)
  docs/
    blackhole-setup.md
    google-calendar-auth.md
    dev-workflows.md
    features/                # one doc per feature (recording, transcription, …)
      _template.md
  scripts/
    doctor.py                # thin wrapper → python -m meeting_memory.doctor
  AGENTS.md                  # authoritative agent control surface
  CLAUDE.md                  # thin pointer to AGENTS.md
  ARCHITECTURE.md            # layering + threading model
  Makefile                   # install / run / auth / doctor / app / launch-agent / lint / test / check
  README.md
  pyproject.toml             # canonical packaging (PEP 621, src-layout)
  requirements.txt           # convenience: `-e .`
  .pre-commit-config.yaml
  .env.example
  .gitignore
```

### 7.5 Layering & Boundary Rules

These rules make the codebase predictable for AI coding agents. They are not style guidance — each is enforced by a test in `tests/test_structure.py` (§7.6) or by a lint rule.

- **Downward-only dependencies.** The import direction is `types ← config ← repo ← service ← ui`. A module MUST NOT import from a layer above it. (`__main__`, `doctor`, `logging_config` are cross-cutting entrypoints and may import `config` / `service` / `repo`.)
- **SDK containment.** External Python SDKs (`boto3`/`botocore`, `assemblyai`, `anthropic`, `googleapiclient`/`google.*`/`google_auth_oauthlib`) MUST be imported only within `repo/`. Every other layer reaches the outside world exclusively through `repo` adapter functions that take and return `types`.
- **UI containment.** `rumps` MUST be imported only within `ui/`. Background threads communicate with the tray through `types/events.py` + a thread-safe queue (§7.3).
- **Typed boundaries.** Functions crossing a layer boundary MUST accept and return declared `types` (dataclasses / pydantic models), never raw `dict`s.
- **File size.** Every `.py` file MUST stay under 300 lines; split by responsibility when approaching the limit.

### 7.6 Repository Conventions for AI Agents

A first-class design goal (alongside the user-facing app) is that **the
repository is easy for AI coding agents to read and modify**. These conventions
are independent of the desktop stack.

**Control surface & docs (progressive disclosure):**

- `AGENTS.md` — the authoritative control surface an agent reads first: repository map, the §7.5 invariants, the command set, the quality bar, and the recommended change workflow.
- `CLAUDE.md` — a thin pointer: "Follow AGENTS.md. Read order: AGENTS.md → ARCHITECTURE.md → docs/features/<feature>.md. Gate: `make check`."
- `ARCHITECTURE.md` — the layer diagram (§7.1), boundary rules (§7.5), and the threading model (§7.3).
- `docs/features/<feature>.md` — one doc per feature (inputs, outputs, threading, tests, related files), seeded from `docs/features/_template.md`; plus `docs/dev-workflows.md`.

**Mechanical enforcement — `tests/test_structure.py`** (AST / import-graph based, pure Python):

- `test_no_backward_imports` — no module imports a higher layer (enforces the §7.5 direction).
- `test_external_sdks_only_in_repo` — the SDK set is imported only under `repo/`.
- `test_rumps_only_in_ui` — `rumps` is imported only under `ui/`.
- `test_file_size_limits` — every `.py` file is ≤ 300 lines.
- `test_required_modules_exist` — the §7.1 component files are all present (an agent cannot silently drop one).

**Preflight — `python -m meeting_memory.doctor`** and the tray's explicit
**Check Setup & Dependencies** action render the same typed report from
REQ-LF-04. The report checks Recording Core requirements and each configured
integration independently; every problem says what is wrong and how to fix it.
The in-app check runs on a worker and returns a typed event to the main thread.
Normal app startup does not run readiness, provider, native-helper, or Google
OAuth-token probes. It may read only exact active generic Keychain references
needed by configured runtime capabilities. Readiness makes no provider network
request; configured Calendar may read its existing OAuth token from Keychain
only during the explicit check.

**Tooling & commands** — `ruff` (lint + format; rule `T20` forbids bare `print()` — use std `logging`), `pytest`, `pre-commit`. A `Makefile` exposes the predictable command set: `make setup | install | run | auth | doctor | install-macos-app | reload-macos-app | open-macos-app | quit-macos-app | install-launch-agent | uninstall-launch-agent | lint | format | test | check:structure | check`, where `check` = lint + tests + structure (the full gate `AGENTS.md` tells agents to run before finishing). The installed CLI also exposes `meeting-memory setup` and `meeting-memory search <query>`.

**Packaging** — `pyproject.toml` is canonical (PEP 621, src-layout,
console-script entrypoint, and `pip install` from a Git URL per REQ-NF-12). A
thin `requirements.txt` (`-e .`) supports the plain `python -m venv` + `pip`
path. Setup compiles the repository's Swift helper and the pinned minimal LGPL
AAC encoder for the current architecture; no prebuilt third-party executable
is committed. The generated local `.app` remains a wrapper around the checkout
and virtualenv. The standalone artifact bundles those two executables with the
encoder license and source offer, but is not a public release until Developer
ID signing and notarization pass.

---

## 8. Configuration Reference

Phase 4B actively resolves exact process-environment names, app-owned
preferences/activated generic Keychain references, legacy `.env`, and defaults
in that order. A missing preference document preserves the legacy path;
corrupt or unreadable preferences fail optional egress closed except for a
complete valid process override. Explicit disable masks legacy values. The
loader is read-only and scoped per consumer, and it does not construct a
provider or contact the network. Variables marked "Integration" below are
required only when that optional capability is enabled; missing groups are
reported as `unconfigured` and never gate Recording Core.

Phase 4C provides a digest-and-identity-bound migration engine with
explicit preview, capability selection, and typed confirmation. It never
imports process values or rewrites `.env`. Phase 4D provides redacted app-owned
edit models, immutable-secret/CAS activation, monotonic current-session egress
pause gates, and native disclosure, secure-entry, migration, prompt, and
Calendar-auth surfaces. Both runtime and setup trays expose the shared surface
explicitly. No reachable native UI action writes `.env`.

| Variable | Capability | Default | Description |
|---|---|---|---|
| `B2_APPLICATION_KEY_ID` | Backup | — | B2 key ID |
| `B2_APPLICATION_KEY` | Backup | — | B2 application key |
| `B2_ENDPOINT` | Backup | — | B2 S3 endpoint URL |
| `B2_REGION` | Backup | — | B2 region (e.g. `us-west-004`) |
| `B2_BUCKET_NAME` | Backup | — | Target B2 bucket |
| `ASSEMBLYAI_API_KEY` | Transcription | — | AssemblyAI key |
| `ANTHROPIC_API_KEY` | Notes | — | Claude key for the `summarize` command |
| `ANTHROPIC_MODEL` | Notes | `claude-haiku-4-5` | Summarization model override (OQ-5) |
| `SUMMARY_PROMPT_FILE` | Notes | `prompts/summary.md` | Prompt template used for Summary, Decisions, and Action Items; editable from **Configuration › Notes Prompt...** |
| `KNOWN_SPEAKERS` | Calendar | `{}` | Optional JSON object mapping speaker display names to Calendar attendee match hints |
| `GOOGLE_CALENDAR_CREDENTIALS_FILE` | Calendar | `credentials.json` | Path to OAuth client secrets |
| `GOOGLE_CALENDAR_ID` | Calendar | `all` | Calendar scope to watch: `all`, `primary`, or a specific calendar ID |
| `MEETINGS_DIR` | Recording Core | `~/Meetings` | Local directory for meeting files |
| `NOTIFY_MINUTES_BEFORE` | Calendar | `5` | Minutes ahead to send pre-meeting notification |
| `MAX_RECORDING_MINUTES` | Recording Core | `180` | Auto-stop active recordings after this duration |
| `CALENDAR_POLL_INTERVAL` | Calendar | `120` | Seconds between calendar polls |

---

## 9. Constraints and Assumptions

**C1** The user grants Meeting Memory the macOS Microphone and Screen & System Audio Recording permissions required by the selected mode.

**C2** A user who enables Calendar has a Google account and OAuth 2.0 client credentials. Recording Core has no Google dependency. The app provides a setup guide (`docs/google-calendar-auth.md`).

**C3** AssemblyAI transcription for a 1-hour meeting costs approximately $0.72 (at $0.012/min). Users should be aware of this cost. The README MUST state estimated costs per hour.

**C4** Meetings that are not tracked in Google Calendar (ad-hoc calls, manual sessions) can still be recorded manually via the tray menu. The UI prompts for a title when no nearby calendar context exists; `"Untitled"` is the fallback.

**C5** The application does not infer speaker names. It suggests known Calendar attendees and applies user-confirmed `speaker_aliases` from `transcript.md` with deterministic local code.

**C6** Internet connectivity is required only while an enabled remote capability performs network work. Recording itself works offline. Failed B2 uploads can be retried with **Retry Pending B2 Backups**; failed transcription states can be retried with **Retry Failed Transcriptions**.

---

## 10. Future Work (Out of Scope for v1)

| Feature | Notes |
|---|---|
| MCP server | Expose meetings as MCP resources for Claude Code and other clients |
| Automatic connectivity retry | Automatically run failed-processing retry when connectivity returns, instead of requiring the tray action |
| Rich diagnostics panel | Add observed calendars, next detected event, B2 object status, and log path to the current doctor/test-notification diagnostics |
| Auto-recording | Automatically start recording when a meeting app opens (requires macOS accessibility permissions) |
| Cross-machine sync | Restore local `~/Meetings/` from B2 on a new machine |
| Meeting calendar enrichment | Write summary bullet points back to the Google Calendar event description |
| Client-side encryption | Encrypt audio before B2 upload |
| Local audio retention policy | Optional purge of `recording.m4a` after a successful B2 upload, after a configurable age — see OQ-1 |

---

## 11. Resolved Decisions

All v0.1 open questions are resolved as of v0.2 (section retitled from "Open Questions").

| # | Question | Decision (v0.2) |
|---|---|---|
| OQ-1 | Keep `recording.m4a` locally long-term, or purge after B2 upload? | **Keep locally in v1; no purge.** REQ-F6-07 already forbids deleting meeting directories. A retention/purge policy is deferred to Future Work (§10). |
| OQ-2 | Expected B2 bucket retention policy for audio? | **No lifecycle policy shipped in v1.** Retention is left to the bucket owner as an ops choice and noted in the README. |
| OQ-3 | Watch multiple Google calendars, or one configured calendar ID? | **Watch all accessible calendars by default.** `GOOGLE_CALENDAR_ID=all` scans non-deleted calendars visible to the authenticated account; set `primary` or a specific calendar ID to narrow. |
| OQ-4 | Preferences as a native macOS window, or terminal config editor? | **Native settings UI.** Phase 4 stores non-secret values in app-owned preferences and secrets in Keychain while retaining read-only `.env` compatibility and explicit import. |
| OQ-5 | Is `claude-haiku-4-5` right, or should the model be configurable? | **Use `claude-haiku-4-5`** as the default, with optional `ANTHROPIC_MODEL` and `SUMMARY_PROMPT_FILE` overrides (§8, REQ-EXT-09, REQ-F5-06). Speaker label display names are handled separately by per-meeting `speaker_aliases`. |
