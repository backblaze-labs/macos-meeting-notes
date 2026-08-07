# Feature: B2 Backup

## Purpose

Upload local meeting artifacts to Backblaze B2 through the S3-compatible API.

## Inputs

- `recording.m4a`
- `transcript.md`
- `B2_APPLICATION_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_ENDPOINT`
- `B2_REGION`
- `B2_BUCKET_NAME`

## Outputs

- `meetings/<slug>/recording.m4a`
- `meetings/<slug>/transcript.md`
- Updated `b2_*` frontmatter fields
- `b2_status: ok` or `b2_status: upload_failed`

## Threading

B2 upload runs after the local files and completion event are written. The tray
`Retry Pending B2 Backups` starts a background retry worker.

## Behavior Notes

- Meeting Memory should use a bucket dedicated to this app and an application
  key restricted to that bucket. Reusing shared sample-app buckets risks mixing
  personal meeting artifacts with unrelated sample data.
- Completion notifications are emitted before B2 upload is attempted, so a slow
  or failed upload does not hide the local transcript from the user.
- The B2 adapter retries uploads with exponential backoff before marking a
  meeting as failed.
- `Retry Pending B2 Backups` scans local meeting directories and retries missing, pending, or
  failed uploads that belong to Meeting Memory, including legacy `meeting.md`
  directories and recordings split across `recording-part-*.m4a` files.
- Failed transcription is retried through `Retry Failed Transcriptions`, not
  `Retry Pending B2 Backups`.

## Related Files

- `src/meeting_memory/repo/b2_client.py`
- `src/meeting_memory/service/pipeline.py`
- `src/meeting_memory/service/sync.py`
- `src/meeting_memory/service/storage.py`

## Tests

- `tests/test_b2.py`
- `tests/test_sync.py`
- `tests/test_pipeline.py`
