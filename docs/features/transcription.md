# Feature: Transcription

## Purpose

Send completed meeting audio to AssemblyAI and write diarized transcript content
to `meeting.md`.

## Inputs

- `recording.m4a`
- `ASSEMBLYAI_API_KEY`
- Optional `ANTHROPIC_API_KEY`
- Optional `ANTHROPIC_MODEL`
- Optional `SUMMARY_PROMPT_FILE`
- Optional `SPEAKER_MAPPING_FILE`

## Outputs

- `TranscriptResult`
- `SummaryResult`
- `assemblyai_id` in frontmatter
- `summary_status` in frontmatter
- `## Transcript` in `meeting.md`
- `## Summary`, `## Decisions`, and `## Action Items` in `meeting.md`

## Threading

Transcription runs inside the background pipeline worker. It must not run on the
tray UI thread.

## Behavior Notes

- AssemblyAI is the transcription source of truth and returns diarized speaker
  labels.
- If AssemblyAI fails, the pipeline still writes a local `meeting.md` with a
  transcription failure state.
- If Anthropic is not configured, summarization is skipped and transcription
  still completes.
- `SUMMARY_PROMPT_FILE` can contain a `{transcript}` placeholder. If it does
  not, the transcript is appended below the prompt.
- AssemblyAI and Anthropic calls use retry/backoff for likely transient errors.
- Failed transcription or summarization states can be retried later with `Retry
  Failed Processing`, using meeting frontmatter as durable state.
- `SPEAKER_MAPPING_FILE` can replace AssemblyAI labels in rendered participants
  and transcript text.

## Related Files

- `src/meeting_memory/repo/transcription.py`
- `src/meeting_memory/repo/summarizer.py`
- `src/meeting_memory/repo/retry.py`
- `src/meeting_memory/service/pipeline.py`
- `src/meeting_memory/service/markdown.py`
- `src/meeting_memory/service/processing_retry.py`
- `src/meeting_memory/service/speaker_mapping.py`
- `prompts/summary.md`

## Tests

- `tests/test_transcription.py`
- `tests/test_summarizer.py`
- `tests/test_pipeline.py`
- `tests/test_processing_retry.py`
- `tests/test_speaker_mapping.py`
