# Feature: Transcription

## Purpose

Send completed meeting audio to AssemblyAI and write diarized transcript content
to `meeting.md`.

## Inputs

- `recording.m4a`
- `ASSEMBLYAI_API_KEY`

## Outputs

- `TranscriptResult`
- `assemblyai_id` in frontmatter
- `## Transcript` in `meeting.md`

## Threading

Transcription runs inside the background pipeline worker. It must not run on the
tray UI thread.

## Related Files

- `src/meeting_memory/repo/transcription.py`
- `src/meeting_memory/service/pipeline.py`
- `src/meeting_memory/service/markdown.py`

## Tests

- `tests/test_transcription.py`
- `tests/test_pipeline.py`
