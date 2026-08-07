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

## Related Files

- `src/meeting_memory/service/recovery.py`
- `src/meeting_memory/service/processing_retry.py`
- `src/meeting_memory/ui/controller.py`
- `src/meeting_memory/ui/tray.py`
- `src/meeting_memory/service/sync.py`

## Tests

- `tests/test_recovery.py`
- `tests/test_processing_retry.py`
- `tests/test_tray.py`
- `tests/test_sync.py`
