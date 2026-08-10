# Feature: B2 Backup

## Purpose

Upload local meeting artifacts to Backblaze B2 through the S3-compatible API.
Backup is opt-in and never gates Recording Core; see
[`../local-first-contract.md`](../local-first-contract.md).

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
- Legacy `b2_status: ok` or `b2_status: upload_failed`

The accepted schema-v2 target uploads exactly `recording.m4a` and
`transcript.md`. `notes.md` remains local unless a future, separately disclosed
opt-in expands Backup. `backup_status` replaces `b2_status`; the latter remains
listed here only for legacy runtime compatibility.

`backup_uploaded_revision` records the SHA-256 revision of the last completely
uploaded audio/transcript snapshot. Revision normalization excludes only Backup
bookkeeping fields, so recording or meaningful transcript changes become
`pending` while status/key updates do not self-reenqueue. The worker uploads a
captured revision and marks success only if current content still matches it.
Disable stops new work at safe boundaries, preserves visible pending work, and
never deletes remote objects. The exact algorithm and transitions are canonical
in `../local-first-contract.md`; no manifest file is added.

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
- Missing B2 configuration is `unconfigured`, not an application failure, in
  the accepted target. The current fail-fast settings behavior remains only
  until the runtime transition.
- An inactive snapshot-upload seam now verifies the captured directory
  identity, owned schema-v2 transcript slug, regular files, and canonical
  revision before constructing a B2 client. Capture accepts one owned meeting
  directory—not independent audio/transcript paths—and the upload request
  cannot supply or retarget its slug. It uploads one object at a time and
  accepts a monotonic per-worker cancellation token before client construction,
  each object, and each retry.
  Before any provider call, the repo copies both verified files into anonymous
  private handles and recomputes slug/revision from those exact streams. The
  private writers are then closed and their names unlinked; only read-only
  views reach the provider. Provider `write`/`truncate` calls are rejected, and
  every retry rewinds the same immutable bytes, so path or provider mutation
  cannot change an upload.
  Partial/cancelled outcomes contain provider progress only; the service layer
  remains responsible for durable `pending` state. Default snapshot staging is
  rooted under the canonical pinned `MEETINGS_DIR`, so a configured root
  symlink remains compatible; an explicitly supplied snapshot root is still
  opened component by component without following symlinks. The legacy
  pipeline still uses its existing whole-meeting upload path.

## Related Files

- `src/meeting_memory/repo/b2_client.py`
- `src/meeting_memory/repo/b2_snapshot.py`
- `src/meeting_memory/types/backup.py`
- `src/meeting_memory/service/backup_revision.py`
- `src/meeting_memory/service/backup_snapshot_fs.py`
- `src/meeting_memory/service/pipeline.py`
- `src/meeting_memory/service/sync.py`
- `src/meeting_memory/service/storage.py`

## Tests

- `tests/test_b2.py`
- `tests/test_b2_snapshot_upload.py`
- `tests/test_b2_snapshot_immutability.py`
- `tests/test_backup_revision.py`
- `tests/test_backup_snapshot_root.py`
- `tests/test_sync.py`
- `tests/test_pipeline.py`
