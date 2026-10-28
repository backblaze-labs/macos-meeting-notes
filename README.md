# macos-meeting-notes

> ⚠️ **Experimental.** This is an experimental
> sample app, not an officially supported Backblaze product. APIs, setup steps, and
> behavior may change without notice. Use at your own risk.

`macos-meeting-notes` is the repository for **Meeting Memory**, a local-first
macOS menu-bar app that records meetings, saves portable artifacts locally,
and backs up each meeting's audio and transcript to Backblaze B2 over the
S3-compatible API. On Apple Silicon, speech recognition and diarization run
locally by default through MLX. Calendar context and Anthropic Notes are
optional; AssemblyAI is an explicit external transcription choice.

The repository/distribution name is `macos-meeting-notes`; the app visible to
users remains **Meeting Memory**, the Python import package remains
`meeting_memory`, and the installed CLI remains `meeting-memory`.

The app is local-first: each completed recording creates a directory under
`MEETINGS_DIR` containing:

- `recording.m4a`
- `transcript.md`
- `notes.md` after you confirm speaker names or explicitly keep the detected labels
- `screenshot-*.png` (or a `screenshots/` folder) when you captured the screen
  during the recording

B2 is the required durable backup layer. The local files remain the user's
readable meeting archive and are committed before any upload begins.

Completing setup requires a Backblaze B2 account, a dedicated private bucket,
and a bucket-scoped application key. The app keeps local recording durable when
the network or B2 is temporarily unavailable, while Transcription, Calendar,
and Notes remain optional. The tray's native **Configuration** submenu stores
credentials in macOS Keychain; legacy `.env` credentials remain compatible.
A legacy AssemblyAI key does not select cloud transcription or grant consent.
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
- Apple Silicon with a native arm64 process and Metal for Local transcription
- Optional AssemblyAI API key plus explicit external-processing consent
- Optional Anthropic API key for Notes and speaker suggestions

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

2. Confirm you have Python 3.11 or later. **macOS ships Python 3.9**, which
   cannot run Meeting Memory:

   ```bash
   python3 --version
   ```

   If that reports 3.9 (or the command is missing), install a supported
   interpreter first:

   ```bash
   brew install python@3.11
   ```

   Note that this formula does **not** replace `python3`. `make setup` searches
   for `python3.11`/`3.12`/`3.13`/`3.14` on its own; if it cannot find one, pass
   it explicitly with `make SETUP_PYTHON=python3.11 setup`.

3. Clone and install the source checkout:

   ```bash
   git clone https://github.com/backblaze-labs/macos-meeting-notes.git
   cd macos-meeting-notes
   make setup
   ```

   `make setup` creates `.venv`, installs dependencies, copies `.env.example`
   to `.env`, compiles the Swift capture helper and a minimal FFmpeg AAC
   encoder from source, installs `~/Applications/Meeting Memory.app`, and
   prints local diagnostics. It is normal for Backup to be `unconfigured`
   until the next step. Model weights are not downloaded during installation
   or startup; prepare them explicitly from the app.

4. Open the app:

   ```bash
   make open-macos-app
   ```

   Until B2 is configured the menu bar shows a reduced **Setup Required** menu
   with no **Start Recording** item. That is expected; the next step unlocks it.

5. From the menu bar, open **Configuration › Backup...**, select
   **Enabled (app-managed)**, and enter the B2 endpoint, region, bucket name,
   application key ID, and application key. Review the upload disclosure,
   save, then quit and reopen Meeting Memory. Secret fields are native secure
   controls, are stored in macOS Keychain, and reopen blank.

6. Verify the required setup:

   ```bash
   make doctor
   ```

   Both `Recording Core` and `Backup` must report `READY` (or a usable
   `DEGRADED` state) for the command to succeed. The check validates local
   configuration without contacting B2; the first completed recording verifies
   the real upload path.

7. Choose an audio mode from the tray, start a short recording, stop it, and
   confirm the local meeting folder is created. If an upload fails, use
   **Debugging › Retry Pending B2 Backups**.

8. On Apple Silicon, choose **Configuration › Prepare Local Models...** and
   start preparation. The app reuses the validated standard Hugging Face cache
   and downloads missing weights without sending meeting content. Cancel or
   retry in the native panel. Missing models do not prevent recording. Once
   preparation completes, new recordings can transcribe locally; choose
   **Debugging › Retry Pending or Failed Transcriptions** separately for
   recordings that were already pending.

For the full walkthrough, provider setup, permissions, and troubleshooting,
read [docs/setup-tutorial.md](docs/setup-tutorial.md).

### Local development commands

```bash
make reload-macos-app
```

This updates and restarts the official local app after code changes. To start
Meeting Memory automatically at login:

```bash
make install-launch-agent
```

`make doctor` renders one status for Recording Core, Transcription, Backup,
Calendar, and Notes. Its exit status requires usable Recording Core and Backup;
disabled or missing optional integrations remain separate from those gates.
Transcription defaults to Local and reports a preparation action when weights
are missing, or an actionable incompatibility on unsupported systems. The
tray's **Debugging › Check Setup & Dependencies** action renders the same report on a background
worker. Neither path contacts a provider; configured Calendar may read its
existing OAuth token from Keychain during the explicit check. The local check
does not request macOS capture permissions, but it reads their current status.
Recording Core reports `ready` when the selected mode's permissions and devices
are available, and `degraded` with a recovery action while any are missing.

The clickable app is installed at `~/Applications/Meeting Memory.app` so it can
be launched from Finder or found with Cmd+Space by searching for
`Meeting Memory`.

That bundle is a thin wrapper that runs this checkout with absolute paths, so
**moving, renaming, or deleting the cloned repository breaks the installed app**.
Your recordings under `MEETINGS_DIR` are unaffected. Rerun `make setup` from the
new location if you move the checkout.

To remove the login item:

```bash
make uninstall-launch-agent
```

## Using the App

Meeting Memory runs as a menu-bar app. Click the menu bar icon (left or right
button) for the app menu: `Start Recording`, Show/Hide Sidebar, recent
meetings, the meetings folder, Configuration, Debugging, and Quit. Use
`Start Recording` for ad-hoc calls, or click `Record` from a pre-meeting
notification when the calendar watcher detects an upcoming Meet or Zoom
event. Manual start uses only watcher-cached Calendar context; without one,
the app records under a provisional title and asks for the final title after
stop.

When Calendar announces an upcoming meeting, a small floating sidebar appears:
a pill with icon buttons for record/stop, screenshot, hide, and quit. It
remains available while you record that meeting, then hides once recording has
actually stopped. You can hide it sooner with its eye-slash button or reopen
it from the menu at any time. Ad-hoc recordings do not open the sidebar on
their own.

While recording, click the camera button or press **⌥⇧S** anywhere to capture
the screen. A single screenshot is saved next to `recording.m4a`; two or more
go into a `screenshots/` folder inside the meeting directory, each named with
its offset into the recording.

Choose the audio mode for the next recording under **Configuration › Audio
Mode** in the right-click menu:

- **Full Meeting** records system audio plus the current macOS microphone. Your
  current output, including AirPods, keeps playing normally. If you change the
  default route mid-recording (for example, speakers to AirPods), the app
  refreshes capture and shows a warning so you can immediately confirm the call
  is still audible.
- **Silent System Only** records system audio with the microphone off and mutes
  that system audio while recording.

Meeting Memory captures these streams through native macOS APIs. It does not
change the user's input/output devices and does not require BlackHole,
Aggregate Devices, or per-device configuration. The durable capture is first a
16 kHz mono WAV; conversion prefers AVFoundation and uses the separately
bundled, offline minimal LGPL encoder only when the host lacks AAC encoding.

While recording, the status bar shows a dot and a live timer next to the icon
and the menu switches to `Stop Recording`. The sidebar's record button turns
into a red stop button with the same timer. Drag the panel by its `⠿` grip to
snap it to any screen edge: top and bottom turn it into a horizontal row.
Turn on **Configuration › Hide sidebar while recording** if you never want
the panel to appear on its own; you can still open it from the menu. Selecting
`Record` dismisses that meeting-start notification. When a
calendar-backed recording reaches the event end time, the app sends a `Stop`
reminder action. Long recordings also send a reminder after one hour and
every 30 minutes after that, until recording stops. After transcription
finishes, the app writes `transcript.md`; the completion notification offers
`Review Speakers` so you can confirm who said what before Notes run.

Meeting Memory checks the system and microphone streams throughout each
recording. If a source never starts, stalls, loses a material share or burst of
frames during mixing, or either source remains silent for 90 seconds, the timer
and Stop label gain `⚠︎` and a notification offers a Stop action. The warning
clears when the source recovers. Final source counters, unresolved warnings,
and recovered warning history are saved as `capture_diagnostics` in
`transcript.md` and are also logged in
`~/Library/Logs/meeting-memory/app.log` under the meeting slug.

You can stop one call and immediately start the next. Conversion, local commit,
transcription, backup, and notes for the earlier call continue independently;
the next recording does not wait for its transcript. Local inference is serial
across meetings and runs in a separate process, leaving the tray responsive.

If the app crashes during recording, restart it and check the tray for
**Debugging › Interrupted Recordings**. Failed B2 uploads can be retried with
**Debugging › Retry Pending B2 Backups**. Pending or failed transcription can
be retried with **Debugging › Retry Pending or Failed Transcriptions**. Old recordings
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
default. `TRANSCRIPTION_PROVIDER` and `ASSEMBLYAI_CONSENT` are accepted only
from app preferences or the actual process environment, never from legacy
`.env` or import. An inherited key alone is inert. A missing provider setting
selects Local, enabled unless explicitly disabled. An unreadable app document fails optional egress closed unless a complete valid
process group overrides it; Recording Core remains local and available.

Recording Core (all have defaults):

- `MEETINGS_DIR`
- `MAX_RECORDING_MINUTES`

Transcription, enabled with Local by default unless explicitly disabled:

- `TRANSCRIPTION_PROVIDER`: `local` (default) or `assemblyai`; app/process only
- `ASSEMBLYAI_CONSENT`: `external-audio-v1` after acceptance; app/process only
- `ASSEMBLYAI_API_KEY`: required only for explicitly selected AssemblyAI

Prefer **Configuration › Transcription...** to select a provider and review its
notice. Saving pauses new transcription jobs until the app restarts. A local
failure never selects cloud transcription. Development or automation that
intentionally uses AssemblyAI must set both app/process-only values explicitly;
putting them in `.env` does not authorize external audio processing.

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

## Data Boundaries and Secrets

Local recognition and diarization can run offline after model preparation.
Meeting Memory as a whole still uses the configured external capabilities:

| Capability | Data leaving the Mac | Trigger |
| --- | --- | --- |
| Model preparation | Requests for pinned weights from Hugging Face; no meeting content | Explicit Prepare action |
| B2 Backup | Meeting audio and transcript | After local commit and owned-artifact updates |
| AssemblyAI | Meeting audio | New recordings or explicit retry after provider selection and consent |
| Anthropic | Transcript excerpts and relevant context | Speaker suggestions before review when Notes is enabled, Notes after confirmation, or explicit topic suggestions |
| Google Calendar | OAuth and Calendar API requests | Explicit authorization and enabled watcher |

AssemblyAI's notice explains that the free plan participates in model
improvement without opt-out. Paid accounts can explicitly opt out; payment
alone is not exclusion, and opt-out affects future requests only. Handling also
depends on account controls and contract. Meeting Memory does not read the
account's actual opt-out setting. See the dated official sources in
[the transcription guide](docs/features/transcription.md#external-provider-consent).

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
**Configuration › Known Speakers...** editor to build an editable base from
confirmed named history or add people manually. Add explicit Calendar matches
when known; no identity linking is guessed. The app stores the roster in app-owned
preferences at
`~/Library/Application Support/meeting-memory/preferences.json`, outside the
repository and with private filesystem permissions. Each row has one display
name and zero or more attendee names, emails, or email local-parts to match.

## Costs

Prices change; check provider pricing before recording long meetings.

Local transcription has no per-minute provider charge. It uses local compute
and disk space for model weights. If you explicitly choose cloud transcription,
check [AssemblyAI pricing](https://www.assemblyai.com/pricing) for current
transcription and diarization charges.

As of 2026-08-12, Backblaze lists B2 pay-as-you-go storage starting at
`$6.95/TB/month`, with free transactions and free egress up to 3x average
monthly storage. See [Backblaze B2 pricing](https://www.backblaze.com/cloud-storage/pricing).

Anthropic summary cost depends on the selected model, transcript length, and
current Anthropic pricing. Each request sends the fixed output-schema
instructions, your editable instruction block, and only a speaker-confirmed
transcript excerpt capped at 60,000 characters. The report layout stays on your
Mac. Notes allow up to 4,096 output tokens so longer meetings can finish the
structured response; an answer that still reaches that limit is rejected
rather than saved as partial notes.

## Customize Notes

The versioned built-in template lives at
[prompts/summary.md](prompts/summary.md), but the app never writes personal
changes there. Until you customize it, the app uses that built-in text as a
fallback. Saving from the tray creates the private personal copy at
`~/Library/Application Support/meeting-memory/prompts/summary.md`, in checkout
and bundled execution alike. Set `SUMMARY_PROMPT_FILE` explicitly only when a
development or legacy workflow needs another path. Meeting Memory inserts the
speaker-confirmed transcript excerpt automatically when Notes runs. Advanced
instruction templates may place `{transcript}` explicitly; otherwise the app
appends it after the instruction block.

Older `.env` files created from the repository scaffold may contain
`SUMMARY_PROMPT_FILE=prompts/summary.md`. That exact former scaffold default is
treated as the app-owned default during upgrade, so it no longer keeps personal
edits in the checkout. Other explicit legacy and process paths remain honored.

Choose **Configuration › Notes Customization...** in the tray. Start in
**Templates** with either:

- **Classic meeting notes**: Summary, Decisions, and Action Items for everyone.
- **Personal focus**: bullet updates grouped by participant, followed only by
  tasks explicitly assigned to you. Enter **Your name** so the model can apply
  that boundary without guessing.

Open **Advanced** to change the report title and build one to eight ordered
sections. Each section has its own title, plain-language guidance, focus
(whole meeting, each participant, or only you), and output format (paragraph,
bullet list, or task checklist). Source/date metadata and the general AI
guidance are configured separately, with a live `notes.md` preview throughout.
Saving applies to the next Notes generation without restarting. **Restore
Classic** returns to the built-in profile.

For compatibility, the private prompt file still stores the general guidance,
local report layout, and versioned profile metadata behind app-owned markers.
The workspace parses those details internally and never displays them. Older
saved three-section layouts remain readable and are upgraded when saved from
the new workspace.

## Participants and Speaker Names

`transcript.md` is the source-of-truth transcript. It carries candidate
speaker names from the Google Calendar event's attendee list (by Calendar
full name, except configured matches from `KNOWN_SPEAKERS`), the diarized
`Speaker A`, `Speaker B` labels the selected backend produced, and an editable alias
map:

```yaml
speaker_candidates: ["Alex", "Ada Lovelace", "Casey"]
speaker_aliases: {"Speaker A": "Alex", "Speaker B": "Ada Lovelace"}
speaker_status: "needs_review"
```

After each transcription, the app prepares speaker review in a background
worker before sending the **Transcript ready** notification. It prepares
unconfirmed name suggestions for named Calendar attendees, using optional
`KNOWN_SPEAKERS` profiles where available. An attendee without a profile does
not block the other suggestions. Email-only candidates are resolved through
exact local roster matches; unresolved emails stay local. Clicking **Review Speakers** opens that prepared
review, including a manual fallback when no proposals were accepted, without
another API request. Historical **Debugging** review actions prepare review
on demand. Claude Haiku receives only a diarized local transcript
excerpt (at most 60,000 characters, ending at a complete utterance), relevant
canonical attendee names, and their optional role/topics descriptions. The app
reuses the existing Anthropic key; the Notes pause also pauses suggestions.
AssemblyAI continues to supply diarized audio transcription only.

The review preselects proposals and shows an exact supporting quote from that
speaker. Verify each name before choosing **Confirm Names**. Cancel leaves
meeting files unchanged. Insufficient evidence, ambiguous
assignments, paused Notes, or provider failures keep manual review available.
Partial proposals leave unresolved speakers for manual selection. Prepared
reviews, including empty or failed proposals, are cached only for the app
session. Canceling and reopening the same review reuses that result. Changed
transcript text or participants invalidate it; a restart also clears the cache.
When direct matches leave one candidate and one substantive speaker, Haiku may
propose that remaining name by elimination if the conversation supports it.
The review marks this **By elimination (verify)** alongside a real utterance
from the proposed speaker. Silent invitees, extra speaker labels, and Unknown
fragments must not force a match. Unresolved email-only attendees disable
elimination while leaving direct suggestions available.
Speaker proposal diagnostics are retained locally in
`~/Library/Logs/meeting-memory/app.log`: the meeting folder name, proposed
label/name, evidence quote (up to 2,000 characters, with truncation marked), and
whether validation accepted the proposal. JSON escaping keeps each diagnostic
on one log line. Raw provider responses and the full transcript are excluded.
For direct identification, the prompt requires a concise quote showing the
distinguishing identity signal rather than a generic acknowledgement.

Review Speakers always displays each speaker's longest line as a clue, alongside
any suggested-name evidence. Both clues remain visible in the scrollable review.

Incomplete speaker assignments return to Review Speakers with the selected names
and blank fields preserved, and identify the labels that still need a name.
A save failure also returns to review for correction, retry, or cancellation.
To keep one anonymous label while naming the others, enter its exact text
(for example, `Unknown`) as the manual name. **Keep Speaker Labels** keeps
all labels. Notes start only after a successful confirmation.

The app does not display a numerical speaker identity-confidence score. Identification allows up
to 8,192 response tokens, including model reasoning. A response that reaches
that limit is rejected and leaves manual review available; no automatic retry
is made.

Build the local people base in **Configuration › Known Speakers...**, available
independently of Calendar setup:

1. Choose **Create from Previous Meetings** to draft exact names already confirmed
   in local transcripts, or **Edit Current Base** to maintain the saved roster.
   The draft reports its count: at most 20 confirmed named meetings within the
   latest 200 meeting folders. Kept anonymous labels are excluded.
2. Edit canonical names and optional Calendar match aliases/emails. Similar names
   stay separate; add a match only when you know it identifies that person.
   Existing entries, matches, and descriptions are preserved in the draft.
3. Choose **Save Locally**, or explicitly choose **Suggest Topics** to send the
   confirmed names and their own bounded quotes to Anthropic Claude Haiku. This
   optional action uses the existing Notes key and pause. Review and edit the
   proposed usual topics (maximum 300 characters) before saving. Names-only
   editing works when Notes is unavailable or paused.
4. Quit and reopen Meeting Memory to use the saved base. Saving updates only
   `KNOWN_SPEAKERS`; concurrent configuration edits require reopening the draft.

When the roster is empty and confirmed named history exists, the app offers
**Create my people base** once. After speaker confirmation starts Notes, a new
confirmed person can trigger a one-time addition offer. Dismissing offers leaves
the menu available without repeating the same names every meeting. Topic generation requires choosing **Suggest Topics**. Canceling any draft
leaves preferences and meeting files unchanged. The same roster is also editable
inside **Configuration › Calendar...**. Matching aliases/emails remain local;
no separate KB service or voice enrollment is required.

In the review window, choose **Confirm Names** to apply names or **Keep Speaker
Labels** when you do not know them. Both choices mark the review as confirmed
and start notes generation; keeping labels leaves `speaker_aliases` empty and
preserves names such as `Speaker A`.

Notes use the reviewed transcript labels as their sole speaker identity source.
They do not receive a Calendar attendee prefix or infer who an anonymous
speaker is from mentions or topics. An explicitly named task recipient can
still appear as the task owner. The former Automatic Notes toggle is removed;
its saved preference is ignored. A kept-label meeting remains available under
**Debugging › Correct Speakers** for one later name correction and Notes
regeneration. The configured Notes model remains independent of Haiku speaker
suggestions.

For CLI backfill or repair, edit `speaker_aliases` and apply the
deterministic relabel step (then `meeting-memory summarize` to regenerate
notes):

```bash
meeting-memory relabel ~/Meetings/<meeting-folder>
```

That updates `transcript.md` so the transcript itself says who said what.
Then generate or retry derived notes:

```bash
meeting-memory summarize ~/Meetings/<meeting-folder>
```

This writes `notes.md` with the configured local layout (the built-in default
uses Summary, Decisions, and Action Items). If notes are missing, skipped, or
failed after speakers are confirmed, the tray shows it under **Debugging ›
Pending Meeting Tasks**. No LLM is used for relabeling; Anthropic is used for
notes generation.

Per-meeting `speaker_aliases` are the source of truth for who spoke in a
specific recording. Global `Speaker A` / `Speaker B` mappings are intentionally
not supported because anonymous labels can change between transcription jobs.

## Local Search

Search saved meeting markdown from the terminal:

```bash
meeting-memory search "launch risks"
```

## FAQ

**Do I need an AssemblyAI key to transcribe?** No. Prepare Local models on a
native Apple Silicon Mac with Metal. Existing AssemblyAI keys do not activate
cloud transcription; select it explicitly and accept its notice if desired.

**Does Local keep all meeting content on my Mac?** Recognition and diarization
run locally, but required B2 Backup sends audio/transcripts. Enabled Anthropic
speaker suggestions and Notes send bounded transcript context at their
respective triggers. Model preparation downloads weights without meeting
content.

**Why did preparing models not transcribe an older recording?** Preparation
changes readiness only. Use **Retry Pending or Failed Transcriptions**
separately and confirm the provider. Restart does not process history, and
successful transcripts stay terminal.

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
- Local transcription requires native arm64 macOS on Apple Silicon with Metal.
  Intel and translated x86_64 processes cannot run this backend. Recording
  remains available under the existing setup contract; cloud transcription
  requires a separate explicit selection and consent.
- Local uses pinned Whisper and Nemotron models with automatic language
  detection and preserves the spoken language. English and Spanish have been
  exercised; this does not establish accuracy for every language or recording.
  Diarization supports up to eight labels and does not fully resolve overlap.
- Missing or corrupt local models leave transcription pending with audio
  preserved. Prepare models, then explicitly retry pending work. A complete
  diarization failure publishes no partial transcript or automatic Notes.
- Failed B2 uploads can be retried with `Retry Pending B2 Backups`. Transcription
  uses `Retry Pending or Failed Transcriptions`; automatic connectivity-aware
  retry remains future work. Preparation and restart do not process history.
- Enabling a capability or changing its credentials/destination requires
  quitting and reopening the app. Disable pauses new current-session egress;
  process environment overrides can enable it again after restart.
