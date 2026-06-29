# Feature: Transcription

## Purpose

Send completed meeting audio to AssemblyAI and write the source-of-truth
diarized transcript to `transcript.md`.

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

Transcription runs inside the background pipeline worker. It must not run on the
tray UI thread. Speaker review relabeling is local deterministic code. Notes
generation runs in a background thread from the tray, or through the local
`meeting-memory summarize` command.

## Behavior Notes

- AssemblyAI is the transcription source of truth and returns diarized speaker
  labels such as `Speaker A`.
- The Stop Recording pipeline writes `transcript.md` only. It does not call
  Anthropic and does not write summaries or decisions.
- Google Calendar attendees populate `speaker_candidates`. Attendees are shown
  by Calendar full name, except aliases explicitly configured in
  `KNOWN_SPEAKERS` through the tray's **Known Speakers...** editor. This is a
  local hint, not automatic identification.
- The user confirms speaker aliases in the tray UI. Relabeling is deterministic
  code, not an LLM step.
- Confirmed speaker review starts notes generation automatically. If notes are
  missing, skipped, or failed, the tray shows a `Continue Processing` action.
- `meeting-memory summarize <meeting-folder>` requires
  `speaker_status: confirmed` and remains available as a backfill/retry command
  for `notes.md`.
- If AssemblyAI fails, the pipeline still writes a non-empty `transcript.md`
  with a transcription failure state.
- Failed transcription states can be retried later with `Retry Failed
  Processing`, using transcript frontmatter as durable state.

## Related Files

- `src/meeting_memory/repo/transcription.py`
- `src/meeting_memory/repo/summarizer.py`
- `src/meeting_memory/repo/retry.py`
- `src/meeting_memory/service/pipeline.py`
- `src/meeting_memory/service/markdown.py`
- `src/meeting_memory/service/transcript_review.py`
- `src/meeting_memory/service/processing_retry.py`
- `src/meeting_memory/service/speaker_mapping.py`
- `prompts/summary.md`

## Tests

- `tests/test_transcription.py`
- `tests/test_transcript_review.py`
- `tests/test_summarizer.py`
- `tests/test_pipeline.py`
- `tests/test_processing_retry.py`
- `tests/test_speaker_mapping.py`
