# Local-First Capability Contract

**Status:** Accepted product contract; implemented through the Phase 4D native
configuration surface
**Canonical for:** onboarding, capability readiness, data lifecycle, migration,
and provider-service behavior

This document defines the target behavior for Meeting Memory's local-first
transition. `SPEC.md` owns detailed feature requirements; this document owns
how those features compose. Complete B2 configuration is an onboarding gate;
provider reachability is not a local-commit gate after onboarding.

## Product Promise

A new user configures a Backblaze B2 account, dedicated private bucket, and
bucket-scoped application key before the normal recording UI becomes available.
After that setup, the user can grant the macOS permissions needed by the
selected audio mode, record about 30 seconds of real audio, stop it, play the
saved local result, and reveal its meeting directory in Finder. A temporary
network or B2 failure does not discard or hide the local recording.

The app MUST explain why a macOS permission is needed immediately before it
requests that permission. Declining an optional permission or integration MUST
NOT make Recording Core unavailable when the selected recording mode can still
work.

## Capability Boundaries

| Capability | Responsibility | Dependencies | Blocks first value? |
| --- | --- | --- | --- |
| **Recording Core** | Capture, recover, convert, store, browse, and search local audio | Supported macOS, writable local folder, native helper, mode-specific macOS permission | **Yes** |
| **Transcription** | Produce a diarized `transcript.md` | Recording Core, network, AssemblyAI credential | No |
| **Backup** | Copy owned meeting artifacts to B2 | Local artifact, network, B2 destination credentials | **Configuration only** |
| **Calendar** | Detect meeting context and reminders | Network, Google credentials and OAuth grant | No |
| **Notes** | Produce derived `notes.md` after speaker review | Completed transcript, network, Anthropic credential | No |

Recording Core is always present. Backup credentials and destination settings
are required to leave setup; Transcription, Calendar, and Notes are opt-in.
Capabilities remain independently configurable and retryable. Enabling one
MUST NOT implicitly enable another, and local audio does not require
Transcription or live B2 reachability.

## Capability State Model

Every capability reports exactly one of these stable wire values:

| State | Meaning | UI/readiness behavior |
| --- | --- | --- |
| `unconfigured` | The user has not opted in or required configuration is absent. | Explain the benefit and provide a non-empty setup action; never present as an error. |
| `checking` | A bounded readiness check is in progress. | Preserve the previous usable path; show progress without blocking unrelated capabilities. |
| `ready` | The capability can perform its promised work now. | Enable its normal actions. |
| `degraded` | The capability remains useful but has a known limitation or retryable external problem. | Keep safe actions enabled and provide a non-empty recovery action. |
| `failed` | The capability cannot perform its promised work. | Disable only the affected action and provide a non-empty recovery action. |

State is capability-local. A failed Backup does not turn Recording Core red. A
missing Anthropic key is Notes `unconfigured`, not an application failure.
`checking` MUST be bounded by a timeout and settle to another state.

## Readiness and Doctor Semantics

The readiness report contains one `CapabilityStatus` for each capability. Each
status has a stable capability ID, state, plain-language summary, and optional
recovery context. The action is required for `unconfigured`, `degraded`, and
`failed`; only `checking` and `ready` may omit it. Recording Core is usable in
`ready` or `degraded`; it is not usable in `unconfigured`, `checking`, or
`failed`.

The app MUST allow Start Recording when Recording Core is usable and Backup has
complete enabled configuration. Transcription, Calendar, and Notes states MUST
NOT gate that action. Before a recording starts, the app MUST validate only the
requirements for the selected audio mode; it MUST NOT make a B2 network probe.

`meeting-memory doctor` and the in-app setup check share the same report:

- exit `0` when Recording Core and Backup configuration are usable;
- exit non-zero when Recording Core cannot produce durable local audio or
  Backup configuration is absent, disabled, or invalid;
- render every capability, not a flat list of undifferentiated failures; and
- never make a network request on the UI thread.

A future explicit provider verification mode MAY contact B2. The default doctor
MUST remain local-only and validate configuration without provider requests.

The active runtime and readiness report keep these capabilities independent.
Characterization tests retain only the isolated legacy APIs that remain for
compatible historical artifact and CLI behavior.

## Durable Audio Lifecycle

Local audio is the source artifact and MUST survive every optional-service
failure.

1. **Capturing:** write 16 kHz mono PCM incrementally to a unique app-owned
   staging directory located on the same filesystem as `MEETINGS_DIR`. The WAV
   is recoverable after a crash.
2. **Stopping:** close the helper and validate that the WAV is non-empty.
3. **Committing locally:** finish a collision-safe staging directory containing
   two closed, readable artifacts—`recording.m4a` plus a compatible
   `transcript.md` metadata stub—then publish that whole directory into
   `MEETINGS_DIR` with one same-filesystem atomic rename before any cloud
   request. WAV conversion prefers AVFoundation and otherwise uses the bundled
   offline, source-pinned minimal LGPL encoder. Either route MUST produce the
   same validated 16 kHz mono AAC-bearing M4A. A partially assembled final
   meeting directory is never visible.
4. **Queuing provider work:** record independent local state for transcription
   and backup. A disabled optional integration leaves its meeting job
   `not_requested`, not lost or failed.
5. **Processing:** provider adapters read the committed local artifact. Their
   errors update only their own state and retain the audio.
6. **Recovery:** interrupted app-owned staging WAVs remain discoverable until
   conversion and local commit succeed. Recovery MUST use the same post-commit
   optional-work path as a normal stop.
7. **Retention:** Meeting Memory never automatically deletes local source audio
   in this transition. Any future purge policy requires explicit user opt-in
   and is outside this contract.

The metadata stub uses `schema_version: 2` and `created_by: meeting-memory`, plus
the existing meeting identity/date/title/duration/speaker fields. Before a
remote transcript exists, `assemblyai_id` is `null`; ownership MUST be detected
from `created_by` and supported schema, never from an AssemblyAI sentinel. It
also includes independent durable states:

```yaml
schema_version: 2
created_by: meeting-memory
assemblyai_id: null
transcription_status: not_requested | pending | running | succeeded | failed
backup_status: not_requested | pending | running | succeeded | failed
backup_uploaded_revision: null
speaker_status: not_available
```

The transcript body explains the current state without exposing raw provider
exceptions. A meeting directory MUST NOT be considered committed while its
only audio is an open staging file, its metadata stub is absent, or the staging
directory has not been atomically published. Once committed, optional
processing MUST NOT rename, replace, or delete `recording.m4a`.

For compatibility, the first upgraded launch discovers legacy
`meeting-memory-*.wav`/`.m4a` files in the old system temp location and presents
them as local recovery choices. Discovery is local-only, runs once per migrated
profile, and MUST NOT trigger Transcription or Backup without the user's
explicit recovery action.

Capability state and per-meeting job state are deliberately different. A
capability may be `ready` while one meeting's job is `failed`; a capability may
be `unconfigured` while an older meeting remains `succeeded`. `not_requested`
means no work has been requested for that meeting; it does not diagnose why.

Valid job transitions are:

```text
not_requested -> pending   (new-record auto policy or explicit historical action)
pending -> running
running -> succeeded | failed
running -> pending         (crash reconciliation)
failed -> pending          (explicit retry)
succeeded -> pending       (Backup only; see the authorized update rule below)
```

`succeeded` is terminal for Transcription. Backup uses a content revision to
separate meaningful artifact changes from its own bookkeeping:

- `backup_uploaded_revision` is the lowercase 64-character SHA-256 revision of
  the last completely uploaded snapshot, or `null` before one succeeds.
- The current revision covers the exact `recording.m4a` bytes and normalized
  `transcript.md`. Transcript normalization removes the top-level frontmatter
  fields `backup_status`, `b2_audio`, `b2_transcript`, and
  `backup_uploaded_revision`, preserves every other byte, converts line endings
  to LF, and ends with exactly one LF.
- The hash input is domain-separated and length-framed:
  `meeting-memory-backup-v2\0`, then the unsigned 8-byte big-endian audio byte
  length plus audio bytes, then the unsigned 8-byte big-endian normalized
  transcript length plus normalized transcript bytes.
- Changes only to the four excluded bookkeeping fields never change the
  revision and never enqueue Backup.

The worker captures current revision `R` and a matching immutable audio and
prepared-transcript snapshot, then uploads that snapshot. It marks
`backup_status: succeeded` and `backup_uploaded_revision: R` only if the current
revision is still `R` at completion. If current content changed, status remains
`pending`; when Backup is still enabled it re-enqueues automatically, otherwise
it remains visibly pending without running.

Any meaningful owned-artifact change where current revision differs from
`backup_uploaded_revision` changes `succeeded` to `pending`, even while Backup
is disabled. Re-enabling Backup does not auto-scan historical meetings; the
user invokes **Retry Pending B2 Backups** to process that visible backlog.

Disabling Backup while a job is `running` prevents new requests and retries. A
request already in flight may finish until its next safe boundary. If the full
captured snapshot completed, the worker records its result using the revision
check above; a partial snapshot returns to `pending`. Disabling Backup never
deletes remote objects.

When an integration is enabled, automatic post-stop work applies to recordings
committed after opt-in. Historical meetings are queued only by an explicit
backfill/retry action; enabling an integration MUST NOT silently upload or
process the backlog.

## Privacy, Data Egress, and Secret Ownership

Meeting Memory is private and local by default. The app MUST identify data
egress before an integration is enabled:

| Integration | Data sent | Purpose |
| --- | --- | --- |
| AssemblyAI | Completed meeting audio | Diarized transcription |
| Backblaze B2 | `recording.m4a` and `transcript.md` for eligible schema-v2 meetings | Durable private backup |
| Google Calendar | OAuth/API requests; event metadata is received locally | Context and reminders |
| Anthropic | The fixed output-schema instructions, the editable instruction block, and only a speaker-confirmed transcript excerpt capped at 60,000 characters; the Markdown layout remains local | Derived notes |

No provider receives data merely because the app launched or Recording Core
ran. Configuration is consent to make the integration available for new
recordings; the UI MUST still describe automatic triggers such as post-stop
transcription or backup. Historical artifacts require a separate explicit
backfill action.

B2 objects remain private. A dedicated private bucket and least-privilege,
bucket-scoped credentials are required for supported setup.

The installed app owns runtime secrets. The target store is macOS Keychain for
API secrets and OAuth tokens; non-secret preferences belong in app-managed
configuration. Secrets MUST NOT appear in logs, notifications, diagnostics,
meeting metadata, or exported support text.

App-managed personal state MUST stay outside the source checkout. Structured
non-secret preferences, including `KNOWN_SPEAKERS`, live in the private
Application Support preference document. A customized Notes prompt lives at
`~/Library/Application Support/meeting-memory/prompts/summary.md`; the tracked
repository prompt is only the built-in fallback. Explicit process and legacy
path overrides remain development/compatibility inputs and are not rewritten.
The exact former scaffold value `SUMMARY_PROMPT_FILE=prompts/summary.md` is
interpreted as the built-in default during upgrade, not as an intentional
custom path; other explicit legacy values retain their original path semantics.

## Compatible Migration from `.env`

Existing checkouts and their files continue to work during migration.

1. Only after the explicit **Import Legacy Configuration...** action, detect
   recognized `.env` and process-environment presence without modifying either.
2. Show which capabilities can be migrated, never secret values.
3. Import secrets into Keychain only after an explicit user confirmation.
4. Import non-secret preferences into the app-managed store while preserving
   paths and current defaults.
5. Resolve every setting with this fixed precedence: process environment >
   app-owned preference/Keychain value > legacy `.env` > built-in default.
   Process environment exists for development and automation and MUST be
   identifiable in diagnostics as an override without revealing its value.
6. Never delete, rewrite, or commit the legacy `.env` automatically. Offer a
   safe cleanup explanation after verification.
7. Preserve existing meeting directories, legacy `meeting.md`/frontmatter,
   recoverable temp WAVs, OAuth Keychain entries, bundle identifiers, and the
   current `meeting-memory` CLI. Normalize a legacy meeting to schema v2 only
   when it is next safely written; do not require an eager bulk rewrite.

`.env` remains a legacy fallback that is read-only to the composed loader and
native UI. Phase 4B reads existing app-owned preferences and only their
activated generic Keychain references. Phase 4D offers an explicit preview and
confirmed import; it performs no automatic import and never mutates `.env`.

## Phase Acceptance Criteria

### Phase 1 — Contract and characterization (complete)

- This document is canonical and linked from product, spec, architecture, and
  contributor-facing docs.
- Pure capability/readiness types use the five stable states.
- Passing tests characterize global fail-fast configuration and pipeline
  coupling that later phases intentionally replace.
- macOS CI runs lint/tests/structure and builds the Swift helper.
- No runtime behavior, secret, `.env`, or user data is migrated.

### Phase 2 — Local core and isolated adapters (complete)

- The local recording substrate remains operable without provider reachability;
  the product-level B2 configuration gate is applied by the setup/runtime UI.
- Local audio is committed before optional work.
- The committed artifact is `recording.m4a` plus the schema-v2 metadata stub;
  ownership no longer depends on `assemblyai_id`.
- Capture staging is app-owned on the `MEETINGS_DIR` filesystem and the complete
  meeting directory is published atomically.
- Transcription, Backup, Calendar, and Notes construct and fail independently.
- Existing `.env` setups continue to run without manual conversion.
- Backup revision hashing, snapshot completion, concurrent artifact changes,
  and disable-at-safe-boundary behavior follow the deterministic rules above;
  no separate manifest is introduced.

### Phase 3 — Coherent setup and doctor (complete)

- In-app setup and doctor render the same capability report.
- Default doctor success depends on Recording Core and Backup configuration.
- Provider failures have capability-specific actions and never remove a local
  recording.

### Phase 4 — Secure progressive configuration

- Native setup can configure capabilities one at a time.
- Secrets are stored in Keychain and are never redisplayed.
- Legacy `.env` import follows the compatible migration rules above.
- Every integration names its data egress and automatic trigger before consent.

Phase 4 is intentionally split into independently reviewable slices:

- **Phase 4A (complete foundation):** typed setting/provenance data, a private
  atomic non-secret preference store, immutable generation-based Keychain
  references, typed provider secret bundles, and a pure precedence resolver.
  The store pins every path component without following symlinks and uses a
  revision compare-and-swap boundary for concurrent writers.
  It performs no migration by itself.
- **Phase 4B (complete):** one fixed-scope composed loader serves runtime,
  readiness, auth, search, and summarize. Process environment remains the
  highest-priority override; explicit disable masks `.env`; corrupt app
  preferences fail optional egress closed except for a complete valid process
  override. Only active, in-scope generic Keychain references are read under a
  bounded deadline. Loading performs no provider request or configuration
  write, and the Google OAuth Keychain identity remains unchanged.
- **Phase 4C (complete engine):** strict bounded `.env`
  preview is bound privately to file identity, content digest, and the exact
  preference revision. Typed confirmation selects whole capabilities. The
  engine writes new immutable secret generations first and activates all
  selected preferences with one compare-and-swap. It never imports process
  values, rewrites or deletes `.env`, contacts a provider, or runs
  automatically. Public previews identify keys, state, secret presence, and
  process-override presence without values or source fingerprints. If CAS
  visibility is ambiguous, new refs are retained but activation is not claimed;
  configuration must be checked before retry.
- **Phase 4D (complete implementation):** native per-capability forms share one
  worker coordinator in runtime and setup trays. Exact egress disclosure,
  secure blank-on-redisplay entry, app/process/legacy provenance, explicit
  migration, explicit Calendar authorization, Notes instructions/layout editing, operation-ID
  stale suppression, and pause-before-terminal ordering are active. Setup keeps
  Notes Instructions & Layout visibly unavailable until Recording Core is
  repaired and the app restarts, avoiding ambient or incorrect path capture.

The Phase 4 implementation criteria above are complete; Phase 5 owns official
computer-use validation of the installed app.

### Phase 5 — Native onboarding validation

- A clean macOS user configures required B2 backup, records about 30 seconds of
  real audio, stops, plays the saved result, reveals its directory in Finder,
  and confirms the private bucket objects.
- Keyboard, VoiceOver labels, denial/retry paths, relaunch, and permission
  prompts pass computer-use validation.

### Phase 6 — Standalone distribution

- The runtime-layout foundation is complete: bundled execution has no implicit
  checkout/cwd or `.env` discovery, and explicit legacy imports persist selected
  relative paths as absolute app-owned values.
- Reproducible ad-hoc thin bundles and a manual protected Developer ID/notary
  workflow are versioned. The latter remains unexecuted until owner-controlled
  credentials, Environment approval, and clean-user evidence are available.
- A signed/notarized build launches without a source checkout or developer
  Python.
- Upgrade preserves app configuration, Keychain items, and meeting data.
- Apple developer identity and release approval remain owner-provided inputs.

## Explicitly Deferred

- Local/offline transcription and local/offline notes models.
- Automatic recording based on meeting-app detection.
- Cross-machine restore from B2.
- Client-side encryption before provider upload.
- Automatic local-audio deletion or retention policies.
- Connectivity-triggered retry without a user action.
- MCP resources and calendar write-back.
- Signed/notarized distribution until the standalone phase.

These are not prerequisites for the first-value promise. Additions must retain
capability isolation and the durable local-audio invariant.
