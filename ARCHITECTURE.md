# Architecture

`macos-meeting-notes` is the repository for **Meeting Memory**, a Python
macOS menu bar application with strict layers under `src/meeting_memory/`.

The external repository/distribution name is `macos-meeting-notes`. The app name
remains `Meeting Memory`, the import package remains `meeting_memory`, and the
CLI remains `meeting-memory`.

## Layers

```text
types <- config <- repo <- service <- ui
```

| Layer | Package | Responsibility |
| --- | --- | --- |
| types | `types/` | Pure data models, UI events, and value-free configuration provenance. |
| config | `config/` | Capability-scoped settings, typed schema, pure precedence resolution, and isolated legacy validation. |
| repo | `repo/` | External service, hardware, and Keychain adapters. |
| service | `service/` | Local behavior, orchestration, and private app-owned filesystem stores. |
| ui | `ui/` | `rumps` tray UI and menu handling. |

Cross-cutting modules live directly under `meeting_memory`: `__main__.py`,
`doctor.py`, and `logging_config.py`.

`types/capabilities.py` defines the stable capability IDs, five-state lifecycle,
and readiness report used by the local-first transition. The composition rules
and phase boundaries are canonical in
[`docs/local-first-contract.md`](docs/local-first-contract.md).
`types/artifacts.py`, `types/meeting.py`, and the local-first event objects define
the pure artifact, job-owner, post-commit policy, and worker-to-UI boundaries.

## Capability Composition

```text
Recording Core
├── Transcription (optional)
├── Backup (optional)
├── Calendar (optional)
└── Notes (optional; consumes a reviewed transcript)
```

Recording Core is the only first-value gate. Optional adapters are constructed,
checked, and failed independently. All optional processing starts from a
durably committed local recording and must preserve it on failure. Recording
Core assembles `recording.m4a` and the schema-v2 metadata stub in app-owned
staging on the `MEETINGS_DIR` filesystem, then publishes the complete meeting
directory with one atomic rename.

`config/runtime.py` loads Recording Core independently and treats each complete
legacy `.env` provider group as an explicit opt-in. `ui/runtime_app.py` is the
composition root: it builds only configured adapters, starts Calendar only when
configured, and captures Transcription/Backup policy at local commit time.

The local-first runtime substrate is split by filesystem responsibility:
`service/atomic_io.py` owns fsync and macOS no-clobber rename primitives,
`pinned_fs.py` owns component-wise no-follow staging access, and
`meeting_document.py` pins an owned schema-v2 meeting directory for all state,
body, and revision operations. `meeting_locks.py` owns per-meeting
serialization, while `meeting_store.py` assembles and publishes complete local
directories. `stage_integrity.py` pins the private stage and accepted audio
before any path-based native validation, then revalidates their identities,
size, and digest immediately before rename and against the published final.
`meeting_state.py`, `transcript_state.py`, and `speaker_state.py`
own CAS transitions and whole-document Transcription/speaker transactions with
same-write Backup reconciliation. `file_snapshot.py` provides stable regular
file reads for local Notes input. `recovery_index.py`, `recovery_journal.py`,
`recovery_marker.py`, `legacy_recovery_index.py`, `recovery_audio.py`,
`recovery_commit.py`, and `recovery_cleanup.py` provide private indexed capture
sessions, explicit
once-only legacy discovery, and verified M4A materialization. The trusted
configured legacy root is canonicalized once so macOS temporary-directory
aliases remain compatible; candidates beneath it stay no-follow. Recovery
keeps the exact source pinned while MeetingStore publishes it. Direct M4A
recovery checks copied size and digest; WAV recovery gives an injected
converter a verified private snapshot path and removes that snapshot before
publication. Both paths require a caller-supplied, native-compatible M4A
validator that establishes a complete container with AAC audio—the service has
no signature-only fallback. The validator receives a read-only inherited file
descriptor for the exact pinned candidate; because AVFoundation cannot open
that descriptor path directly, the native helper copies it to a private 0600
temporary M4A inside a Python-owned 0700 directory and validates the entire
copy. Python removes that directory even if the helper times out. The store
still compares the pinned candidate's identity, size, and digest before and
after validation and after publication. A successful commit
issues a sealed cleanup capability binding both the published directory and
the final audio device/inode, size, and digest.
`backup_revision.py` and `backup_snapshot_fs.py` capture immutable revision
snapshots from one pinned meeting directory; their meeting slug comes from that
directory's owned transcript rather than a caller argument. Default snapshot
staging is beneath the pinned root's canonical path, including when the
configured meetings root is a lexical symlink; explicit snapshot roots retain
the component-wise no-follow boundary.
`repo/b2_snapshot.py` copies the verified pair through private writers, closes
those writers, reopens read-only views, and unlinks their names. Identity and
revision come from those exact anonymous bytes, and only the read-only streams
reach the per-object adapter. Path or provider mutation therefore
cannot change bytes between validation, upload, or retry. The adapter also honors
monotonic worker cancellation at provider boundaries. Pure revision framing
lives in `types/backup.py` so the service and repository cannot drift.

`service/local_commit.py` enforces atomic commit → verified recovery cleanup →
typed success event → optional worker order. Cleanup failure emits a typed
pending outcome and starts no provider work. `runtime_transcription.py`,
`runtime_jobs.py`, and
`runtime_retry.py` own provider-ID CAS, per-meeting single flight, immutable B2
snapshots, cancellation, and explicit ownership-aware retries. Schema-v2 work
never passes through the compatibility `Pipeline` or legacy whole-file writers.
`runtime_files.py` rejects caller metadata or paths that disagree with the
single pinned owned meeting before either optional provider runs. MeetingStore
seals the published directory device/inode in `MeetingFiles`; explicit retries
seal it from their pinned scan. Runtime then binds that identity into a handle
before thread start;
Transcription and Backup require that identity again inside every capture,
claim, provider-ID CAS, completion, failure, and retry write. Replacing the
path with an otherwise valid owned clone therefore cannot cause egress or
mutate the clone.
`legacy_snapshot.py` keeps compatibility retries isolated: provider bytes and
identity come from one private read-only snapshot, and the local legacy update
is allowed only if the pinned directory and metadata remain unchanged.
`runtime_legacy_recovery.py` owns the explicit, once-only legacy scan session;
normal startup never scans the old temp root.
`runtime_notes.py` snapshots a confirmed owned transcript, calls Notes outside
the meeting lock, then revalidates and atomically publishes through the pinned
directory. Legacy Notes compatibility uses the same private metadata snapshot
and compare-before-write boundary without routing legacy files through a v2
state writer.

`service/readiness.py` builds the complete typed `ReadinessReport` and owns
Recording Core checks. `service/readiness_integrations.py` evaluates optional
legacy configuration groups independently and short-circuits Calendar before
any Keychain read when its local opt-in or credentials file is absent. The CLI
doctor and `ui/setup_readiness.py` consume that same report. Explicit in-app
checks run on a worker and return `ReadinessChecked` to the main thread; normal
startup performs no readiness, native-helper, Keychain, or provider probe.

Before publication, a private app-owned journal binds source provenance and
commit-time policy to an opaque token. MeetingStore puts that token inside the
hidden stage before the same atomic directory rename. Both app and legacy
retries can therefore locate and validate the exact visible directory/audio
without republishing, including after an uncertain parent fsync or cleanup
failure. The tray reports uncertainty/pending state and starts no provider;
verified cleanup and journal clearing precede `RecordingCommitted` and jobs.

## Native Audio Boundary

`repo/native/` contains a small Swift helper compiled during setup and copied
inside `Meeting Memory.app`. Python starts it as a subprocess and receives
newline-delimited lifecycle events through `repo/native_audio.py`.

- **Full Meeting** uses ScreenCaptureKit to capture system audio and the current
  default microphone without changing macOS input or output routing.
- **Silent System Only** uses a Core Audio process tap with muted playback. It
  captures system audio, excludes the microphone, and leaves the selected audio
  devices unchanged.
- The helper aligns and mixes captured streams into an incremental 16 kHz mono
  WAV. The same helper converts the completed WAV to M4A through AVFoundation.

This boundary intentionally avoids virtual audio drivers, Aggregate Devices,
`sounddevice`, and `ffmpeg`.

## Boundary Rules

- Modules may import from their own layer or a lower layer only.
- External SDK imports are contained to `repo/`.
- `rumps` imports are contained to `ui/`.
- Background workers communicate with the UI through `types/events.py` objects
  and a thread-safe queue.
- Python and Swift source files stay at or below 300 lines.

These rules are enforced by `tests/test_structure.py`.

## Threading Model

- Main thread: tray UI and notifications.
- Calendar watcher: daemon poll loop.
- Native audio helper: ScreenCaptureKit/Core Audio capture callbacks and WAV
  writing in a separate process.
- Local commit: one background worker per stopped recording or explicit recovery.
- Optional jobs: independent per-meeting Transcription and Backup workers.

Background threads must not call UI APIs directly. They emit events, and the UI
drains those events on the main thread.

The local-commit worker emits `RecordingCommitted`
after atomic publication and optional transcription emits `TranscriptReady`
only after job success or `TranscriptionFailed` on failure. The tray main thread
alone translates those typed events into the separate Recording saved,
Transcript ready, and Transcription failed notifications.

Runtime startup follows the same boundary and isolates optional adapter
construction failures from Recording Core. Capability-aware setup/doctor is
active.

## Progressive Configuration Foundation

Phase 4A is present but deliberately inactive. `types/configuration.py` and
`types/configuration_resolution.py` define the allowlisted non-secret document,
opaque versioned `SecretRef`, typed provider secret bundles, enablement, and
value-free provenance. `config/schema.py` and `config/resolution.py` implement a
pure resolver with the future precedence `process env > app preference/active
Keychain ref > legacy .env > default`. An explicit optional disable masks app
and legacy values; only a complete valid process-environment group overrides
it. An unavailable/corrupt app document fails optional capability selection
closed while Recording Core remains resolvable.

`service/preference_store.py` and `preference_store_fs.py` store only allowlisted
non-secrets, enablement, and opaque references in a private atomic JSON file
under Application Support. Component-wise no-follow directory pinning, strict
0700/0600 ownership/modes, a writer lock, and revision compare-and-swap prevent
unsafe paths and lost concurrent updates. Unconditional `save` is create-only
bootstrap; every later Phase 4 writer must load a snapshot and use
compare-and-swap.
`repo/secret_store.py` writes provider payloads under immutable generated
Keychain accounts in a service distinct from the compatible Google OAuth token
service. Multi-field B2 credentials form one payload, so a single preference
replace activates the matching secret and destination settings together.

No active loader calls these modules yet. Runtime, readiness, auth, search,
summarize, existing UI, and `.env` behavior remain unchanged in 4A. Phase 4B
adds composed loading; Phase 4C adds digest-bound, explicit, non-destructive
migration; Phase 4D adds native disclosure/consent forms, background store
writes, and explicit Calendar auth.
