# Feature: Recovery and Retry

## Purpose

Recover interrupted recordings and retry failed local processing without
requiring a new recording.

## Inputs

- Indexed app-staging WAV sessions
- Existing meeting directories with Meeting Memory frontmatter
- Schema-v2 pending, failed, or stale-running optional-job state

## Outputs

- Converted recovered `recording.m4a`
- Normal meeting directory and `transcript.md`
- Retried transcript content
- Updated B2 frontmatter after backup retry

## Threading

Recovery and processing retry are launched from tray actions and run on
background threads. UI notifications are emitted through the event queue.

## Behavior Notes

- Recovery discovers private indexed sessions read-only. Selecting one uses the
  same verified local commit, typed event, cleanup receipt, and post-commit
  policy as a newly stopped recording.
- `Retry Failed Transcriptions` uses existing frontmatter as durable state
  instead of a separate job database.
- `Retry Pending B2 Backups` is only for backup retry; transcription retry
  handles failed transcription.
- Retries are user-triggered from the tray's **Debugging** submenu; automatic
  connectivity-triggered retry remains future work.
- The active recovery substrate uses a unique private app-owned
  session with an atomic `recovery.json` index. Discovery is read-only and
  no-follow; legacy WAV/M4A discovery has an explicit durable once-only marker.
  Normal stop persists source identity, size, and digest in that index. Menu
  discovery validates the stored shape and file stat without hashing the full
  recording; the background commit revalidates the exact bytes before use.
  The dedicated recovery commit keeps the exact no-follow source descriptor
  open while MeetingStore materializes and publishes it. A direct M4A copy must
  match the indexed size and digest before publication, followed by another
  source check. A WAV is never copied into `recording.m4a`: an injected
  converter receives a verified private WAV snapshot path, which is cleaned up
  before publication. Direct M4A and converted WAV paths both require an
  injected, native-compatible validator that proves a complete M4A container
  with AAC audio; there is deliberately no built-in `ftyp`-only acceptance.
  Conversion, validation, or pre-publication cleanup failure preserves the
  indexed source. Successful publication issues a sealed cleanup capability
  binding that source to the published directory and final audio device/inode,
  size, and digest. Any later source-descriptor close failure is a typed
  published outcome carrying that result and receipt, never an ambiguous
  ordinary exception. If parent durability and descriptor cleanup both fail,
  the durability outcome remains primary and carries the cleanup error; its
  receipt explicitly prohibits source cleanup. Cleanup otherwise re-pins and
  verifies both before source removal.
  The trusted configured legacy temp root primitive canonicalizes once before
  candidate-level no-follow traversal, preserving macOS temp aliases without
  permitting candidate symlinks. Indexed recovery is wired to the tray. The
  one-time legacy-temp migration scan runs only after the explicit Debugging
  action. An empty scan marks completion immediately; discovered entries remain
  unmarked and in memory until every selection commits, so a crash before
  selection permits a rescan. Scanning never starts provider work.
- The durable legacy once marker lives in its own 0700 child below the shared
  meeting staging directory; the parent may retain MeetingStore's normal mode.
- Before publication, a private app-owned journal binds exact source provenance
  and commit-time policy to an opaque token written inside the hidden meeting
  stage. The atomic directory rename publishes that token with the two local
  artifacts, so indexed and legacy retries reconcile the exact final rather
  than creating a suffix. Verified source cleanup precedes the success event
  and provider work. Journal and hidden-marker removal is best-effort after
  that irreversible cleanup; an orphaned opaque guard is inert because its
  source no longer exists and can be collected by future maintenance.

## Related Files

- `src/meeting_memory/service/recovery.py`
- `src/meeting_memory/service/recovery_index.py`
- `src/meeting_memory/service/legacy_recovery_index.py`
- `src/meeting_memory/service/recovery_cleanup.py`
- `src/meeting_memory/service/recovery_audio.py`
- `src/meeting_memory/service/recovery_commit.py`
- `src/meeting_memory/service/recovery_journal.py`
- `src/meeting_memory/service/recovery_marker.py`
- `src/meeting_memory/service/processing_retry.py`
- `src/meeting_memory/service/legacy_snapshot.py`
- `src/meeting_memory/service/local_commit.py`
- `src/meeting_memory/service/runtime_retry.py`
- `src/meeting_memory/service/runtime_legacy_recovery.py`
- `src/meeting_memory/ui/controller.py`
- `src/meeting_memory/ui/tray.py`
- `src/meeting_memory/service/sync.py`

## Tests

- `tests/test_recovery.py`
- `tests/test_recovery_index_v2.py`
- `tests/test_recovery_audio.py`
- `tests/test_recovery_receipt.py`
- `tests/test_legacy_recovery_index.py`
- `tests/test_processing_retry.py`
- `tests/test_tray.py`
- `tests/test_sync.py`
