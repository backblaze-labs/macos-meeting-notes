# Feature: Transcription

## Purpose

Send completed meeting audio to AssemblyAI and write the source-of-truth
diarized transcript to `transcript.md`.

Transcription is an optional capability under
[`../local-first-contract.md`](../local-first-contract.md). Recording Core runs
without its credential; a complete legacy environment group opts it in.

## Inputs

- `recording.m4a`
- `ASSEMBLYAI_API_KEY`
- Optional `KNOWN_SPEAKERS`, used to normalize configured people in Calendar
  speaker suggestions
- Optional `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, and `SUMMARY_PROMPT_FILE` for
  automatic notes after speaker review or the `meeting-memory summarize` retry
  command

## Outputs

- `TranscriptResult`
- `transcript.md` with:
  - `assemblyai_id`
  - `speaker_candidates`
  - editable `speaker_aliases`
  - `speaker_status`
  - diarized transcript lines
- `notes.md` after confirmed speaker review starts notes generation, or after
  `meeting-memory summarize` is run manually

## Threading

Transcription runs inside a dedicated background worker. It must not run on the
tray UI thread. Speaker review relabeling is local deterministic code. Notes
generation runs in a background thread from the tray, or through the local
`meeting-memory summarize` command.

## Behavior Notes

- AssemblyAI is the transcription source of truth and returns diarized speaker
  labels such as `Speaker A`.
- Runtime submission copies audio through the pinned owned meeting descriptor
  into a private file reopened read-only and unlinked before the adapter sees
  it. Later path swaps cannot change or redirect the bytes. Provider job create
  is attempted once because retrying an ambiguous submit timeout could create
  an orphan; persisted job-ID resume remains retryable.
- Before the worker thread starts, runtime binds the meeting directory
  device/inode sealed by local publication, or by an explicit retry scan. Audio
  capture and every Transcription claim, job-ID
  CAS, success, failure, and retry write require that same identity, so an
  owned same-slug directory replacement reaches neither AssemblyAI nor the
  replacement transcript.
- The Stop Recording pipeline writes `transcript.md` only. It does not call
  Anthropic and does not write summaries or decisions.
- Google Calendar attendees populate `speaker_candidates`. Attendees are shown
  by Calendar full name, except aliases explicitly configured in
  `KNOWN_SPEAKERS` through the tray's **Configuration › Known Speakers...**
  editor. This is a local hint, not automatic identification.
- The user can confirm speaker aliases in the tray UI, or choose **Keep Speaker
  Labels** when the names are unknown. The latter preserves labels such as
  `Speaker A`, leaves `speaker_aliases` empty, and still records the review as
  confirmed. Relabeling is deterministic code, not an LLM step.
- Either confirmed speaker-review choice starts notes generation
  automatically. If notes are missing, skipped, or failed, the tray shows a
  **Debugging › Pending Meeting Tasks** action.
- Anthropic receives the fixed output-schema instructions, the configured
  editable instruction block, and only a speaker-confirmed transcript excerpt clipped to
  at most 60,000 characters. Notes reserve up to 4,096 output tokens so longer
  meetings can complete the structured response; a response that still stops
  at the output limit is rejected rather than parsed or published. Anthropic
  never receives an unreviewed metadata stub.
- The tray's **Configuration › Notes Customization...** item opens a native
  workspace for the effective `SUMMARY_PROMPT_FILE`. AI Instructions and Report
  Layout are separate tabs. The visual layout editor supports titles, required
  section ordering, metadata toggles, and a live preview; advanced Markdown
  remains available for arbitrary local formatting. The app-owned storage
  marker is parsed internally and never appears in the standard workspace.
  `{summary}`, `{decisions}`, and `{action_items}` remain required so the fixed
  JSON contract stays complete. Saved changes apply to the next notes
  generation without restarting the app. Without an explicit path override,
  the editable copy is personal state at
  `~/Library/Application Support/meeting-memory/prompts/summary.md`; the
  repository prompt remains an unchanged built-in fallback.
- `meeting-memory summarize <meeting-folder>` requires
  `speaker_status: confirmed` and remains available as a backfill/retry command
  for `notes.md`.
- If AssemblyAI fails, the worker atomically writes a provider-detail-free
  transcription failure state while retaining local audio.
- Failed transcription states can be retried later with `Retry Failed
  Transcriptions`, using transcript frontmatter as durable state.
- Before a failed retry submits a replacement provider job, one locked replace
  moves the job to pending and clears the previous provider ID. The new ID is
  then persisted before polling, so an old ID cannot orphan a new submission.
- `Retry Failed Transcriptions` scans only Transcription state; it never starts
  Backup work.
- Legacy retry compatibility snapshots the owned legacy metadata and audio into
  private read-only streams before the adapter runs. The provider job and
  request identity therefore come from the same captured bytes, and a changed
  legacy file fails closed instead of letting the compatibility writer touch a
  schema-v2 or foreign artifact.
- An unconfigured or failed transcription
  leaves the committed audio usable and reports only Transcription's state.
- The runtime finishes schema-v2 transcription with
  one locked whole-document replace: provider-ID CAS, transcript body, owned
  fields, and Backup revision reconciliation succeed or conflict together.
  Speaker confirmation uses the same model. Notes snapshots a confirmed owned
  transcript, revalidates it after the provider call, and atomically publishes
  `notes.md` without following an existing symlink or FIFO. Existing legacy
  meetings use a separate private metadata snapshot and unchanged-identity
  check, so the tray action and `meeting-memory summarize` remain compatible
  without sending legacy artifacts through the schema-v2 writer.

## Related Files

- `src/meeting_memory/repo/transcription.py`
- `src/meeting_memory/repo/summarizer.py`
- `src/meeting_memory/repo/retry.py`
- `src/meeting_memory/service/pipeline.py`
- `src/meeting_memory/service/transcription_audio.py`
- `src/meeting_memory/service/markdown.py`
- `src/meeting_memory/service/transcript_review.py`
- `src/meeting_memory/service/transcript_state.py`
- `src/meeting_memory/service/runtime_transcription.py`
- `src/meeting_memory/service/runtime_notes.py`
- `src/meeting_memory/service/speaker_state.py`
- `src/meeting_memory/service/file_snapshot.py`
- `src/meeting_memory/service/summary_prompt.py`
- `src/meeting_memory/service/processing_retry.py`
- `src/meeting_memory/service/legacy_snapshot.py`
- `src/meeting_memory/service/speaker_mapping.py`
- `src/meeting_memory/ui/notes_prompt.py`
- `prompts/summary.md`

## Tests

- `tests/test_transcription.py`
- `tests/test_transcript_review.py`
- `tests/test_transcript_state.py`
- `tests/test_speaker_state.py`
- `tests/test_file_snapshot.py`
- `tests/test_summarizer.py`
- `tests/test_summary_prompt.py`
- `tests/test_pipeline.py`
- `tests/test_processing_retry.py`
- `tests/test_runtime_job_identity.py`
- `tests/test_speaker_mapping.py`
