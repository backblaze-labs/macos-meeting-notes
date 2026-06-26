# Software Requirements Specification
# `macos-meeting-notes` — Meeting Memory macOS Meeting Notes App

**Status:** Draft  
**Author:** Meeting Memory contributors
**Date:** 2026-06-18
**Version:** 0.3
**Methodology:** RFC-inspired SRS (requirement language per RFC 2119: MUST / SHOULD / MAY / MUST NOT)

**Revision note (v0.2):** Added a second, first-class design goal — **the repository must be easy for AI coding agents to read and modify** — and the conventions that deliver it, ported from the *portable* (non-web-specific) patterns of the team's `agent-friendly reference project`: an `AGENTS.md` control surface, import-enforced module layering, mechanical structural tests, a doctor preflight, and fail-fast config. §7 was restructured into enforced layers (§7.1, §7.5, §7.6) and all v0.1 Open Questions were resolved (§11). This app is deliberately **not** built on the reference project web template (Next.js + FastAPI) — see §1.2 and §2.1.

**Revision note (v0.3):** Aligned the spec with the implemented macOS app wrapper, LaunchAgent workflow, all-calendar default (`GOOGLE_CALENDAR_ID=all`), notification actions (`Record`, `Open`, `Stop`), status-bar recording timer, calendar-context recording titles, configurable summary prompt, recording auto-stop, temp-recording recovery, retry/backoff, failed-processing retry, local search, separate `transcript.md` / `notes.md` artifacts, Calendar-derived speaker candidates, and manual speaker aliases. Remaining product limitations are called out in §10.

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

This document specifies the requirements for **Meeting Memory**, a macOS menu bar application whose repository is named **macos-meeting-notes**. The app records meetings, transcribes them with speaker diarization, generates AI summaries, and saves everything as portable markdown files backed up to Backblaze B2.

### 1.2 Scope

`macos-meeting-notes` is a Python application repository targeting macOS. It is designed as a personal productivity tool and as a Backblaze B2 sample demonstrating local-first AI data pipelines with object storage as the durable backup layer.

Naming is intentionally split during the low-risk external rename: the visible app remains **Meeting Memory**, the Python import package remains `meeting_memory`, and the CLI remains `meeting-memory`. The macOS bundle ID, Keychain service, LaunchAgent label, and log paths keep their current `meeting-memory` identifiers until a deliberate migration is planned.

It is the **native, local-first counterpart** to the B2 sample fleet's web meeting app (`web meeting sample`): rather than a browser upload flow, it captures real system + microphone audio on the desktop, watches the calendar, and treats B2 as the durable archive. It is deliberately **not** built on the team's `agent-friendly reference project` (reference project) web template, which is a Next.js + FastAPI stack whose scaffolder only emits web apps and cannot host a macOS menu-bar process.

A **second, explicit design goal** sits alongside the user-facing app: the repository itself must be **easy for AI coding agents to read and modify**. This is achieved not by inheriting reference project's web stack but by porting its *portable* repo conventions — an authoritative `AGENTS.md`, import-enforced layering, mechanical structural tests, a doctor preflight, and fail-fast configuration (see §7.5 and §7.6).

### 1.3 Definitions

| Term | Definition |
|---|---|
| **Meeting** | A calendar event with a Google Meet or Zoom URL |
| **Recording session** | The period between "Start Recording" and "Stop Recording" |
| **Aggregate Device** | A macOS virtual audio device combining mic input + BlackHole system audio output |
| **Diarization** | Speaker segmentation: labeling transcript segments by speaker identity |
| **Meeting slug** | URL-safe identifier derived from the meeting date/time and calendar title (e.g. `2026-06-10_09-00_standup`) |
| **Meeting directory** | Local folder `$MEETINGS_DIR/<slug>/` containing `recording.m4a`, `transcript.md`, and optional `notes.md` |
| **B2** | Backblaze B2 cloud storage, accessed via the S3-compatible API |

### 1.4 References

- AssemblyAI Universal-2 transcription API docs
- Anthropic Claude API (claude-haiku-4-5)
- Google Calendar API v3
- BlackHole virtual audio driver (Existential Audio)
- RFC 2119 key words for requirement levels
- Backblaze B2 S3-compatible API
- `agent-friendly reference project` — source of the *portable* agent-repo conventions adopted here (`AGENTS.md` control surface, structural tests, doctor preflight, layered modules)

---

## 2. Overall Description

### 2.1 Product Perspective

**Meeting Memory** is a standalone macOS application with no server-side component, maintained in the `macos-meeting-notes` repository. It runs as a menu bar process, interfaces with external services (Google Calendar, AssemblyAI, Anthropic, B2) via HTTPS, and reads/writes to the local filesystem. There is no web UI, no application database, and no always-on server. It is **not** built on the team's `agent-friendly reference project` web template (Next.js + FastAPI); it is a Python desktop app that ports only that template's *portable* repo conventions (§7.6), not its stack.

```
┌─────────────────────────────────────────────────┐
│                  macOS                           │
│  ┌──────────────┐    ┌───────────────────────┐  │
│  │  meeting-    │    │  ~/Meetings/           │  │
│  │  memory      │◄──►│    2026-06-10_standup/ │  │
│  │  (tray app)  │    │      transcript.md     │  │
│  └──────┬───────┘    │      recording.m4a     │  │
│         │            └───────────────────────┘  │
│  ┌──────▼───────┐                               │
│  │  Aggregate   │                               │
│  │  Audio Device│                               │
│  │  (BlackHole  │                               │
│  │   + Mic)     │                               │
│  └──────────────┘                               │
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

- F1: Calendar watching — detect upcoming meetings with video conferencing links
- F2: Pre-meeting notification — remind the user to start recording
- F3: Audio recording — capture system audio + microphone via aggregate device
- F4: Transcription — diarized speech-to-text via AssemblyAI
- F5: Summarization — extract summary, decisions, and action items via Claude
- F6: Local storage — save structured markdown + audio to `~/Meetings/`
- F7: B2 backup — upload meeting artifacts to Backblaze B2 after local write
- F8: Tray menu — control recording, browse recent meetings, trigger sync
- F9: Completion notification — alert user when transcript is ready
- F10: Local macOS app wrapper — install, reload, launch, quit, and optionally start at login
- F11: Local search and retry tools — search stored meetings and retry failed processing

### 2.3 User Characteristics

Primary user: a knowledge worker who attends multiple video meetings per week, wants a private transcript archive, and uses Claude Code or other AI tools to query their meeting history.

Technical profile: comfortable with terminal setup (installing Python packages, running an auth flow), not necessarily a software developer.

### 2.4 Constraints

- macOS 13 (Ventura) or later
- Python 3.11 or later
- BlackHole 2ch must be installed and an Aggregate Device must be configured before first use
- Recording requires the user to explicitly trigger start/stop (no fully automatic recording)
- Transcription and summarization require internet access
- Google Calendar OAuth credentials file must be obtained from Google Cloud Console
- The installed `.app` is a local wrapper around this repo and Python environment; it is not a signed, notarized, standalone distribution artifact.

---

## 3. External Interface Requirements

### 3.1 Google Calendar API

**REQ-EXT-01** The application MUST authenticate to the Google Calendar API using OAuth 2.0 with the `https://www.googleapis.com/auth/calendar.readonly` scope.

**REQ-EXT-02** OAuth tokens MUST be stored in the macOS Keychain, not in a plain-text file on disk.

**REQ-EXT-03** The application MUST support a one-time interactive auth flow triggered by `python -m meeting_memory auth`, which opens a browser and saves the resulting token to the macOS Keychain.

**REQ-EXT-04** The application MUST automatically refresh expired OAuth tokens using the stored refresh token, without user interaction.

### 3.2 AssemblyAI Transcription API

**REQ-EXT-05** The application MUST upload audio to AssemblyAI using the `assemblyai` Python SDK (not raw HTTP).

**REQ-EXT-06** Every transcription request MUST include `speaker_labels=True` to enable diarization.

**REQ-EXT-07** The application MUST poll AssemblyAI for job completion, with a polling interval of 5 seconds and a maximum wait time of 30 minutes.

**REQ-EXT-08** If the transcription job fails (status `error`), the application MUST write a `transcript.md` file with the transcript section replaced by an error message, and MUST NOT leave the meeting directory empty.

### 3.3 Anthropic Claude API

**REQ-EXT-09** The application MUST use the `anthropic` Python SDK to call Claude, defaulting to `claude-haiku-4-5` and honoring an optional `ANTHROPIC_MODEL` override (§8).

**REQ-EXT-10** The summarization prompt MUST request three structured outputs in a single call: (a) a summary paragraph, (b) a bullet list of decisions, (c) a list of action items each with optional owner name.

**REQ-EXT-11** If the Claude API call fails or times out, the application MUST leave `transcript.md` untouched and write a failed/skipped derived-notes state without blocking transcript completion.

**REQ-EXT-12** The application MUST NOT send more than the first 60,000 characters of transcript text to Claude (to stay within context limits).

### 3.4 Backblaze B2 (S3-Compatible API)

**REQ-EXT-13** The application MUST access B2 exclusively via the S3-compatible API endpoint (`B2_ENDPOINT`). The b2-native API MUST NOT be used.

**REQ-EXT-14** Every `boto3` S3 client instance MUST be initialized with `botocore.config.Config(user_agent_extra='b2ai-meeting-memory')`.

**REQ-EXT-15** B2 credentials MUST be read from the following environment variables only — no other naming scheme is acceptable:
```
B2_APPLICATION_KEY_ID
B2_APPLICATION_KEY
B2_ENDPOINT
B2_REGION
B2_BUCKET_NAME
```

### 3.5 Audio Hardware Interface

**REQ-EXT-16** The application MUST record from the audio device named by the `AUDIO_DEVICE` environment variable.

**REQ-EXT-17** The default value of `AUDIO_DEVICE` MUST be `"Meeting Aggregate"`. Users who name their aggregate device differently can override via env var.

**REQ-EXT-18** If the configured audio device is not found at startup, the application MUST surface a visible error (tray notification or menu item) rather than silently failing.

**REQ-EXT-19** Audio MUST be captured at 16000 Hz sample rate, mono channel, encoded as a 16-bit PCM WAV during capture, then converted to M4A (AAC, ~128kbps) before saving and uploading, to balance file size and audio quality.

---

## 4. Functional Requirements

### F1: Calendar Watcher

**REQ-F1-01** The calendar watcher MUST start automatically when the application launches.

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

**REQ-F3-06** The recording MUST be written incrementally to a temporary file to prevent data loss if the application crashes.

**REQ-F3-07** A configurable maximum recording duration (`MAX_RECORDING_MINUTES`, default: 180) MUST exist in settings and preferences. If this limit is reached, the application MUST automatically stop recording, enqueue the post-recording pipeline, and notify the user.

### F4: Transcription

**REQ-F4-01** The transcription pipeline MUST start automatically after the user stops recording.

**REQ-F4-02** The application MUST upload the audio file to AssemblyAI before writing any transcript to disk (the remote job is the source of truth).

**REQ-F4-03** Transcript segments MUST be formatted as `**<Speaker Label>** (<HH:MM:SS>): <text>` in `transcript.md`.

**REQ-F4-04** Speaker labels returned by AssemblyAI (e.g. "Speaker A", "Speaker B") MUST be preserved until the user confirms local `speaker_aliases`. The application MUST NOT infer real attendee names automatically.

**REQ-F4-05** The application MUST record the AssemblyAI transcript ID in the meeting's YAML frontmatter (`assemblyai_id` field) for future retrieval.

**REQ-F4-06** Google Calendar attendees MAY populate `speaker_candidates`. Candidates SHOULD use the attendee's Calendar full name, except aliases explicitly configured in `KNOWN_SPEAKERS`. These candidates are hints for manual review, not automatic speaker identification.

**REQ-F4-07** `meeting-memory relabel <meeting-folder>` MUST apply `speaker_aliases` from `transcript.md` deterministically by code, without using an LLM or re-transcribing audio.

### F5: Summarization

**REQ-F5-01** Summarization MUST start automatically after UI speaker review confirms
`speaker_status`. `meeting-memory summarize <meeting-folder>` MUST remain available
as a manual backfill/retry command for confirmed transcripts.

**REQ-F5-02** The Claude prompt MUST instruct the model to produce output in a structured format parseable into three distinct sections: Summary, Decisions, and Action Items.

**REQ-F5-03** Each action item MUST include at minimum a task description. An owner name (extracted from context) SHOULD be included when identifiable. A due date SHOULD be included only when explicitly mentioned in the meeting.

**REQ-F5-04** Action items MUST be formatted as GitHub Flavored Markdown task list items: `- [ ] <owner>: <task>` or `- [ ] <task>` when no owner is identifiable.

**REQ-F5-05** The summarize command MUST write `notes.md` and MUST NOT modify `transcript.md`.

**REQ-F5-06** The summarization prompt MUST be configurable through `SUMMARY_PROMPT_FILE`. If the file contains `{transcript}`, the app MUST replace that placeholder with the clipped transcript; otherwise it MUST append the transcript below the prompt text.

### F6: Local Storage

**REQ-F6-01** The application MUST create a meeting directory at `$MEETINGS_DIR/<slug>/` for every completed recording session, where `$MEETINGS_DIR` defaults to `~/Meetings`.

**REQ-F6-02** The meeting slug MUST follow the format `YYYY-MM-DD_HH-MM_<title-slug>` where:
- `YYYY-MM-DD_HH-MM` is the recording start time in local time
- `<title-slug>` is the calendar event title lowercased, with spaces replaced by hyphens, non-alphanumeric characters stripped, and truncated to 40 characters

**REQ-F6-03** Two files MUST be written to each meeting directory after transcription:
- `recording.m4a` — the audio file (M4A/AAC format)
- `transcript.md` — the source-of-truth transcript with frontmatter and speaker aliases

**REQ-F6-03a** `notes.md` MAY be generated later with summary, decisions, and action items after speaker aliases are confirmed.

**REQ-F6-04** `transcript.md` MUST contain a YAML frontmatter block (between `---` delimiters) as its first section, containing the fields specified in Section 6.1.

**REQ-F6-05** `notes.md` MUST contain the following H2 sections in order when generated: `## Summary`, `## Decisions`, `## Action Items`. Each section MUST be present even if empty (use `_None identified._` as placeholder).

**REQ-F6-06** The application MUST update the `b2_audio` and `b2_transcript` frontmatter fields after a successful B2 upload (see F7).

**REQ-F6-07** The application MUST NOT delete or overwrite a meeting directory once created. If a slug collision occurs (same timestamp + title), it MUST append `-2`, `-3`, etc.

### F7: B2 Backup

**REQ-F7-01** The application MUST upload both `recording.m4a` and `transcript.md` to B2 after the local transcript has been written.

**REQ-F7-02** The B2 object key MUST follow the pattern: `meetings/<slug>/<filename>`.

**REQ-F7-03** B2 upload MUST NOT block the completion notification (REQ-F9-01). The app MUST emit the completion event after local write and before attempting B2 upload.

**REQ-F7-04** If a B2 upload fails, the application MUST retry up to 3 times with exponential backoff (2s, 4s, 8s). After 3 failures, the upload MUST be logged and silently abandoned (with the frontmatter `b2_status: upload_failed` written to `transcript.md`).

**REQ-F7-05** The **Sync to B2** tray menu item MUST scan `$MEETINGS_DIR` for meeting directories where `b2_status` is missing or `upload_failed` and re-attempt upload.

**REQ-F7-06** The application MUST NOT upload any file from `$MEETINGS_DIR` that was not created by `meeting-memory` itself (identified by the presence of valid YAML frontmatter with the `assemblyai_id` field).

### F8: Tray Menu

**REQ-F8-01** The tray menu MUST contain the following items, in order:

```
● Meeting Memory                  (app title, non-interactive)
─────────────────
▶ Start Recording                 (or ■ Stop Recording · <HH:MM> while active)
─────────────────
Recent Meetings                   (section header, non-interactive)
  <date> · <title>  ×5           (one item per recent meeting, most recent first)
─────────────────
Open Meetings Folder
Sync to B2
Retry Failed Processing
─────────────────
Run Diagnostics
Send Test Notification
Preferences…
Quit
```

**REQ-F8-02** Clicking a **Recent Meetings** item MUST open the corresponding meeting directory in Finder (not the `transcript.md` file directly, so the user can see all artifacts).

**REQ-F8-03** The **Recent Meetings** list MUST show at most 5 entries. If there are no meetings, the section MUST show `No meetings yet`.

**REQ-F8-04** The **Recent Meetings** list MUST be rebuilt from the filesystem each time the menu is opened (not cached in memory).

**REQ-F8-05** **Open Meetings Folder** MUST open `$MEETINGS_DIR` in Finder.

**REQ-F8-06** **Preferences** MUST open a simple settings view where the user can configure: `MEETINGS_DIR`, `NOTIFY_MINUTES_BEFORE`, `MAX_RECORDING_MINUTES`, and `AUDIO_DEVICE`.

**REQ-F8-07** If recoverable temporary recordings are found, the tray menu MUST show a **Recovered Recordings** section with one action per recoverable item.

**REQ-F8-08** **Retry Failed Processing** MUST scan local meeting directories and retry meetings whose transcript frontmatter indicates failed transcription.

**REQ-F8-09** **Run Diagnostics** MUST rerun doctor-lite checks and surface the result through a notification and tray setup items.

**REQ-F8-10** **Send Test Notification** MUST send a local notification for validating macOS notification behavior.

### F9: Completion Notification

**REQ-F9-01** After `transcript.md` has been written to disk, the application MUST send a macOS notification with:
- Title: `"Meeting ready"`
- Body: `"<meeting-title> · transcript ready · review speakers"`
- Action button: `"Open"` — opens the meeting directory in Finder

**REQ-F9-02** The completion notification MUST be sent regardless of whether the B2 upload has completed.

**REQ-F9-03** If transcription failed, the notification body MUST indicate failure: `"<meeting-title> · transcription failed. Audio saved locally."`.

### F10: Local macOS App Wrapper and Login Item

**REQ-F10-01** The application MUST provide commands to install, reload, open, and quit a clickable local app bundle at `~/Applications/Meeting Memory.app`.

**REQ-F10-02** The local app bundle MUST run the current checkout with the selected Python executable and `PYTHONPATH=src`.

**REQ-F10-03** The local app bundle MUST be configured as a menu-bar/background app (`LSUIElement`) and include the Meeting Memory icon asset.

**REQ-F10-04** The application MUST provide commands to install and uninstall a LaunchAgent at `~/Library/LaunchAgents/com.meeting-memory.app.plist` so the menu-bar app can start at login.

**REQ-F10-05** The LaunchAgent MUST run the current checkout as a background process and write stdout/stderr to `~/Library/Logs/meeting-memory/`.

### F11: Local Search, Recovery, and Retry

**REQ-F11-01** The CLI MUST expose `meeting-memory search <query>` to perform case-insensitive full-text search across Meeting Memory-owned `transcript.md` files.

**REQ-F11-02** Search results MUST include the meeting date, title, markdown path, and a short excerpt.

**REQ-F11-03** The retry-processing flow MUST use durable local transcript frontmatter state (`assemblyai_id`) to identify failed transcription work.

**REQ-F11-04** Recovered recordings MUST be converted from temp WAV to M4A, copied into a normal meeting directory, processed through the same pipeline as stopped recordings, and removed from temp after successful conversion.

---

## 5. Non-Functional Requirements

### 5.1 Performance

**REQ-NF-01** The tray menu MUST open and render within 300ms at all times, including during active recording or background pipeline processing.

**REQ-NF-02** All network calls (Google Calendar, AssemblyAI, Anthropic, B2) MUST run on background threads and MUST NOT execute on the main thread.

**REQ-NF-03** Audio capture MUST introduce no more than 100ms of latency between real-world sound and write to the temp file buffer.

### 5.2 Reliability

**REQ-NF-04** If the application crashes during recording, the partial audio written to the temp file MUST be discoverable from the tray on restart. If the user selects a recovered recording, the application MUST process it through the normal pipeline.

**REQ-NF-05** The application MUST preserve local audio and write a usable `transcript.md` failure state when AssemblyAI calls fail. AssemblyAI and Anthropic adapter calls MUST use explicit retry/backoff for transient failures and rate limits.

### 5.3 Security and Privacy

**REQ-NF-06** OAuth tokens for Google Calendar MUST be stored in the macOS Keychain using the `keyring` Python library. They MUST NOT be written to `.env` or any plain-text file.

**REQ-NF-07** The `.env` file MUST be listed in `.gitignore`. The repository MUST NOT include any real credentials.

**REQ-NF-08** B2 credentials MUST only be read from environment variables at runtime. They MUST NOT be logged or included in error messages.

**REQ-NF-09** Meeting audio and transcripts are private by default. B2 objects MUST NOT be made public. No presigned URLs are generated or shared in v1.

### 5.4 Compatibility

**REQ-NF-10** The application MUST run on macOS 13 (Ventura) or later on both Intel and Apple Silicon.

**REQ-NF-11** The application MUST NOT depend on any paid macOS feature or third-party subscription beyond the services listed in Section 3.

**REQ-NF-12** The application MUST be distributable as a `pip install` from a Git URL, with no bundled third-party executables or application binaries. Static UI assets such as the app icon MAY be stored in the repository.

### 5.5 Observability

**REQ-NF-13** The application MUST write structured logs to `~/Library/Logs/meeting-memory/app.log` using Python's standard `logging` module at INFO level by default.

**REQ-NF-14** Each pipeline stage (record, upload-to-assemblyai, poll, summarize, local-write, b2-upload) MUST emit a log entry at start and completion with the meeting slug and elapsed time.

### 5.6 Agent-Handleability

**REQ-NF-15** The structural tests in `tests/test_structure.py` MUST pass on every commit. The layering, SDK-containment, UI-containment, file-size, and required-module rules of §7.5–§7.6 are enforced mechanically, not by convention.

**REQ-NF-16** The doctor preflight (`python -m meeting_memory.doctor`) MUST be runnable on a fresh clone *before* dependencies are installed (for its environment / `.env` / ffmpeg / credentials checks), and MUST report each failure with a concrete fix.

**REQ-NF-17** Layer boundaries (§7.5) MUST be import-enforced: external SDKs only under `repo/`, `rumps` only under `ui/`, and no imports pointing "upward" in the layer order.

**REQ-NF-18** `AGENTS.md` and `ARCHITECTURE.md` MUST exist and be kept current. `AGENTS.md` is the read-first control surface for any agent or contributor, and `CLAUDE.md` MUST be a thin pointer to it.

**REQ-NF-19** No source file MAY exceed 300 lines; modules approaching the limit MUST be split by responsibility.

---

## 6. Data Models

### 6.1 transcript.md Frontmatter Schema

```yaml
---
id: <meeting-slug>               # string, matches directory name
date: <ISO-8601 datetime>        # recording start time, local timezone
duration_minutes: <integer>      # rounded to nearest minute
calendar_title: <string>         # from Google Calendar event, or "Untitled"
participants: [<string>, ...]    # speaker labels, or mapped speaker names when configured
assemblyai_id: <string>          # AssemblyAI transcript job ID
speaker_candidates: [<string>, ...] # Calendar-derived known-speaker hints
speaker_aliases: {<label>: <name>}  # user-confirmed local aliases
speaker_status: needs_review | confirmed
b2_audio: <string | null>        # B2 object key, null until upload succeeds
b2_transcript: <string | null>   # B2 object key, null until upload succeeds
b2_status: ok | upload_failed | pending
---
```

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
| **types** | `types/` | `meeting.py` (`MeetingMeta`, slug helpers-as-data) · `transcript.py` (`TranscriptResult`, `TranscriptSegment`) · `summary.py` (`SummaryResult` with decisions + action items) · `events.py` (UI events emitted to the tray: `MeetingDetected`, `NotifyEvent`, `RecordingStateChanged`). Pure data — **no SDK imports, no cross-layer imports.** |
| **config** | `config/` | `settings.py` — `pydantic-settings` `Settings` class (the §8 table) + `validate_or_exit()` fail-fast validation and placeholder detection. Depends only on `types`. |
| **repo** | `repo/` | `b2_client.py` (boto3 S3 adapter) · `transcription.py` (AssemblyAI adapter; `transcribe(audio_path) -> TranscriptResult`) · `summarizer.py` (Anthropic adapter; `summarize(text) -> SummaryResult`) · `calendar_client.py` (Google Calendar OAuth + Keychain + event list) · `audio_device.py` (sounddevice device lookup) · `retry.py` (repo-adapter retry policy). **The only layer permitted to import external SDKs.** |
| **service** | `service/` | `storage.py` (`write_meeting_dir()`, `list_recent_meetings()`, frontmatter read/update, `is_ours()`) · `markdown.py` (renders `transcript.md` and `notes.md`) · `transcript_review.py` (local relabel + derived notes generation) · `processing_state.py` (resumable post-processing task detection) · `recorder.py` (sounddevice stream → temp WAV → m4a; `start()/stop()`) · `pipeline.py` (orchestrates transcription → local transcript write → B2 upload) · `calendar_watcher.py` (daemon poll loop; emits `MeetingDetected`) · `recording_context.py` (nearby-calendar title lookup) · `recovery.py` (temp-recording discovery/conversion) · `processing_retry.py` (frontmatter-based retry) · `search.py` (local full-text search) · `speaker_mapping.py` (optional speaker label mapping) · `sync.py` (Sync-to-B2 rescan) · `macos_app.py` (local app wrapper commands) · `launch_agent.py` (login item install/uninstall). Calls `repo`, returns `types`; **no `rumps`, no SDKs.** |
| **ui** | `ui/` | `tray.py` (`rumps.App` subclass; menu state, action dispatch, notifications, status timer, `rumps.Timer` draining the event queue) · `controller.py` (recording/pipeline/sync handoff) · `menu.py` (menu label helpers) · `preferences.py` (minimal settings window) · `notifications.py` (rumps notification wrapper + fallback) · `title_prompt.py` (ad-hoc title prompt) · `macos.py` / `icons.py` (macOS UI helpers). **The only layer permitted to import `rumps`.** |
| *cross-cutting* | — | `__main__.py` (entrypoint; `auth` subcommand; loads `.env`; logging; doctor-lite; starts tray) · `doctor.py` (preflight, §7.6) · `logging_config.py` (logs → `~/Library/Logs/meeting-memory/app.log`). |

### 7.2 Processing Sequence (Happy Path)

```
[User clicks Stop Recording]
        │
        ▼
Recorder.stop() → saves /tmp/meeting-memory-<ts>.wav
        │
        ▼
Pipeline.run(audio_path, meeting_meta)
  ├── Storage.write_audio(recording.m4a)         ← local write first
  ├── TranscriptionClient.transcribe(audio_path)
  │       └── AssemblyAI upload → poll → TranscriptResult
  ├── Storage.write_transcript_md(transcript.md)  ← local write
  ├── TrayApp.notify("Meeting ready")             ← notification event here
  └── Storage.upload_to_b2()                      ← async, after notification
          ├── PutObject meetings/<slug>/recording.m4a
          ├── PutObject meetings/<slug>/transcript.md
          └── Storage.update_frontmatter_b2_fields()

[User confirms speaker_aliases]
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
```

### 7.3 Threading Model

- **Main thread**: `rumps` event loop (tray, menus, notifications)
- **Thread 1**: `CalendarWatcher` polling loop (daemon)
- **Thread 2**: `Recorder` sounddevice stream callback (daemon)
- **Thread 3**: `Pipeline` post-recording processing (created per session, joins before app quit)

The `TrayApp` communicates with background threads via a thread-safe `queue.Queue`. Background threads MUST NOT call `rumps` UI methods directly — instead they enqueue `types/events.py` objects (e.g. `MeetingDetected`, `NotifyEvent`), and a `rumps.Timer` on the main thread drains the queue and performs **all** `rumps` calls. This rule is mechanically enforced: `rumps` may be imported only under `ui/` (§7.6, `test_rumps_only_in_ui`). It resolves the tension between "the pipeline must fire notifications" (REQ-F9-01) and "background threads must not touch the UI" — the pipeline emits an event; the tray renders it.

### 7.4 Project File Structure

```
macos-meeting-notes/
  src/
    meeting_memory/
      __main__.py            # entrypoint; `auth` subcommand; .env + logging + doctor-lite; starts tray
      doctor.py              # preflight checks (§7.6)
      logging_config.py      # logging → ~/Library/Logs/meeting-memory/app.log
      types/                 # boundary models — no SDKs, no cross-layer imports
        __init__.py
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
        audio_device.py      # sounddevice device lookup
        retry.py             # retry/backoff helper for external adapter calls
      service/               # orchestration; no rumps, no SDKs
        __init__.py
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
- **SDK containment.** External SDKs (`boto3`/`botocore`, `assemblyai`, `anthropic`, `googleapiclient`/`google.*`/`google_auth_oauthlib`, `sounddevice`) MUST be imported only within `repo/`. Every other layer reaches the outside world exclusively through `repo` adapter functions that take and return `types`.
- **UI containment.** `rumps` MUST be imported only within `ui/`. Background threads communicate with the tray through `types/events.py` + a thread-safe queue (§7.3).
- **Typed boundaries.** Functions crossing a layer boundary MUST accept and return declared `types` (dataclasses / pydantic models), never raw `dict`s.
- **File size.** Every `.py` file MUST stay under 300 lines; split by responsibility when approaching the limit.

### 7.6 Repository Conventions for AI Agents

A first-class design goal (alongside the user-facing app) is that **the repository is easy for AI coding agents to read and modify**. These conventions are ported from the *portable* (non-web-specific) patterns of the team's `agent-friendly reference project`; they are independent of the desktop stack.

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

**Preflight — `python -m meeting_memory.doctor`** (zero-dependency where possible; the audio-device check is guarded so doctor can run before deps are installed): verifies Python ≥ 3.11, macOS ≥ 13, `.env` present and filled (no placeholder values), required `B2_*` + `ASSEMBLYAI_API_KEY` set, `ffmpeg` on `PATH`, the configured audio device exists, and the Google OAuth credentials file is present. Each failure prints exactly what is wrong and how to fix it. A doctor-lite subset runs at app startup and surfaces failures via a tray notification + a visible menu item rather than crashing (REQ-EXT-18).

**Tooling & commands** — `ruff` (lint + format; rule `T20` forbids bare `print()` — use std `logging`), `pytest`, `pre-commit`. A `Makefile` exposes the predictable command set: `make setup | install | run | auth | doctor | install-macos-app | reload-macos-app | open-macos-app | quit-macos-app | install-launch-agent | uninstall-launch-agent | lint | format | test | check:structure | check`, where `check` = lint + tests + structure (the full gate `AGENTS.md` tells agents to run before finishing). The installed CLI also exposes `meeting-memory setup` and `meeting-memory search <query>`.

**Packaging** — `pyproject.toml` is canonical (PEP 621, src-layout, console-script entrypoint, `pip install` from a git URL per REQ-NF-12; no bundled third-party executables). A thin `requirements.txt` (`-e .`) supports the plain `python -m venv` + `pip` path; `uv` is documented as an optional faster installer. `ffmpeg` is an external system dependency (doctor-checked, not pip-installed). The local `.app` bundle is a generated wrapper around the checkout and virtualenv, not a signed/notarized standalone app.

---

## 8. Configuration Reference

All configuration is read from environment variables, with `.env` file support via `python-dotenv`. Pydantic `Settings` class validates on startup and exits with a clear error if required fields are missing.

| Variable | Required | Default | Description |
|---|---|---|---|
| `B2_APPLICATION_KEY_ID` | ✓ | — | B2 key ID |
| `B2_APPLICATION_KEY` | ✓ | — | B2 application key |
| `B2_ENDPOINT` | ✓ | — | B2 S3 endpoint URL |
| `B2_REGION` | ✓ | — | B2 region (e.g. `us-west-004`) |
| `B2_BUCKET_NAME` | ✓ | — | Target B2 bucket |
| `ASSEMBLYAI_API_KEY` | ✓ | — | AssemblyAI key |
| `ANTHROPIC_API_KEY` | — | — | Claude key for the `summarize` command |
| `ANTHROPIC_MODEL` | — | `claude-haiku-4-5` | Summarization model override (OQ-5) |
| `SUMMARY_PROMPT_FILE` | — | `prompts/summary.md` | Prompt template used for Summary, Decisions, and Action Items |
| `SPEAKER_MAPPING_FILE` | — | — | Optional JSON map from AssemblyAI labels to display names |
| `KNOWN_SPEAKERS` | — | — | Optional aliases used when Calendar attendee speaker candidates match configured people |
| `GOOGLE_CALENDAR_CREDENTIALS_FILE` | ✓ | `credentials.json` | Path to OAuth client secrets |
| `GOOGLE_CALENDAR_ID` | — | `all` | Calendar scope to watch: `all`, `primary`, or a specific calendar ID |
| `MEETINGS_DIR` | — | `~/Meetings` | Local directory for meeting files |
| `AUDIO_DEVICE` | — | `Meeting Aggregate` | sounddevice device name |
| `NOTIFY_MINUTES_BEFORE` | — | `5` | Minutes ahead to send pre-meeting notification |
| `MAX_RECORDING_MINUTES` | — | `180` | Auto-stop active recordings after this duration |
| `CALENDAR_POLL_INTERVAL` | — | `120` | Seconds between calendar polls |

---

## 9. Constraints and Assumptions

**C1** The user has installed BlackHole 2ch and configured an Aggregate Device before first use. The app provides a setup guide (`docs/blackhole-setup.md`) but does not automate this step.

**C2** The user has a Google account with Google Calendar, and has downloaded OAuth 2.0 client credentials from Google Cloud Console. The app provides a setup guide (`docs/google-calendar-auth.md`).

**C3** AssemblyAI transcription for a 1-hour meeting costs approximately $0.72 (at $0.012/min). Users should be aware of this cost. The README MUST state estimated costs per hour.

**C4** Meetings that are not tracked in Google Calendar (ad-hoc calls, manual sessions) can still be recorded manually via the tray menu. The UI prompts for a title when no nearby calendar context exists; `"Untitled"` is the fallback.

**C5** The application does not infer speaker names. It suggests known Calendar attendees and applies user-confirmed `speaker_aliases` from `transcript.md` with deterministic local code.

**C6** Internet connectivity is required during transcription and derived-note summarization. Recording itself works offline. Failed B2 uploads can be retried with **Sync to B2**; failed transcription states can be retried with **Retry Failed Processing**.

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
| OQ-4 | Preferences as a native macOS window, or terminal config editor? | **Minimal `rumps` settings window** exposing the four REQ-F8-06 fields (`MEETINGS_DIR`, `NOTIFY_MINUTES_BEFORE`, `MAX_RECORDING_MINUTES`, `AUDIO_DEVICE`); it writes `.env` and prompts a restart. |
| OQ-5 | Is `claude-haiku-4-5` right, or should the model be configurable? | **Use `claude-haiku-4-5`** as the default, with optional `ANTHROPIC_MODEL` and `SUMMARY_PROMPT_FILE` overrides (§8, REQ-EXT-09, REQ-F5-06). Speaker label display names are handled separately by per-meeting `speaker_aliases`. |
