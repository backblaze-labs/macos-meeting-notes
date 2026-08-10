# Feature: Recovery and Retry

## Purpose

Recover interrupted recordings and retry failed local processing without
requiring a new recording.

## Inputs

- Temporary `meeting-memory-*.wav` files in the recorder temp directory
- Existing meeting directories with Meeting Memory frontmatter
- `assemblyai_id: transcription-failed`

## Outputs

- Converted recovered `recording.m4a`
- Normal meeting directory and `transcript.md`
- Retried transcript content
- Updated B2 frontmatter after backup retry

## Threading

Recovery and processing retry are launched from tray actions and run on
background threads. UI notifications are emitted through the event queue.

## Behavior Notes

- Recovery finds non-empty temp WAV files without a matching `.m4a` sibling.
- Selecting a recovered recording under **Debugging** converts it, removes the
  temp WAV after conversion, and sends it through the standard pipeline.
- `Retry Failed Transcriptions` uses existing frontmatter as durable state
  instead of a separate job database.
- `Retry Pending B2 Backups` is only for backup retry; transcription retry
  handles failed transcription.
- Retries are user-triggered from the tray's **Debugging** submenu; automatic
  connectivity-triggered retry remains future work.
- The inactive local-first recovery substrate uses a unique private app-owned
  session with an atomic `recovery.json` index. Discovery is read-only and
  no-follow; legacy WAV/M4A discovery has an explicit durable once-only marker.
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
  The trusted configured legacy temp root is canonicalized once before
  candidate-level no-follow traversal, preserving macOS temp aliases without
  permitting candidate symlinks. These APIs are not wired into startup, the
  recovery tray, or provider jobs; this slice selects neither converter nor
  validator.

## Related Files

- `src/meeting_memory/service/recovery.py`
- `src/meeting_memory/service/recovery_index.py`
- `src/meeting_memory/service/legacy_recovery_index.py`
- `src/meeting_memory/service/recovery_cleanup.py`
- `src/meeting_memory/service/recovery_audio.py`
- `src/meeting_memory/service/recovery_commit.py`
- `src/meeting_memory/service/processing_retry.py`
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
