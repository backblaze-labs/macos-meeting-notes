# Feature: Recovery and Retry

## Purpose

Recover interrupted recordings and retry failed local processing without
requiring a new recording.

## Inputs

- Temporary `meeting-memory-*.wav` files in the recorder temp directory
- Existing meeting directories with Meeting Memory frontmatter
- `assemblyai_id: transcription-failed`
- `summary_status: failed`

## Outputs

- Converted recovered `recording.m4a`
- Normal meeting directory and `meeting.md`
- Retried transcript and summary content
- Updated B2 frontmatter after backup retry

## Threading

Recovery and processing retry are launched from tray actions and run on
background threads. UI notifications are emitted through the event queue.

## Behavior Notes

- Recovery finds non-empty temp WAV files without a matching `.m4a` sibling.
- Selecting a recovered recording converts it, removes the temp WAV after
  conversion, and sends it through the standard pipeline.
- `Retry Failed Processing` uses existing frontmatter as durable state instead
  of a separate job database.
- `Sync to B2` is only for backup retry; processing retry handles failed
  transcription or summarization.
- Retries are user-triggered from the tray; automatic connectivity-triggered
  retry remains future work.

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
