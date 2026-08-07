# Feature: Search and Speaker Review

## Purpose

Make the local meeting library easier to query and read after meetings are
processed.

## Inputs

- `MEETINGS_DIR`
- `meeting-memory search <query>`
- `meeting-memory relabel <meeting-folder>`
- Meeting Memory-owned `transcript.md` files

## Outputs

- CLI search results with date, title, path, and excerpt
- Reviewed `transcript.md` files with user-confirmed speaker aliases

## Behavior Notes

- Search is local and case-insensitive.
- A search query must match all terms in the normalized meeting title/body text.
- Search only reads directories identified as Meeting Memory output.
- `speaker_aliases` in `transcript.md` is the preferred per-meeting source for
  confirmed names.
- Calendar attendees populate `speaker_candidates` as hints. Attendees are
  shown by Calendar full name, except aliases explicitly configured in
  `KNOWN_SPEAKERS` when the attendee name or email matches.
- Relabeling is local deterministic code; it does not infer names from audio or
  use an LLM.

## Related Files

- `src/meeting_memory/service/search.py`
- `src/meeting_memory/service/transcript_review.py`
- `src/meeting_memory/service/speaker_mapping.py`
- `src/meeting_memory/service/markdown.py`
- `src/meeting_memory/__main__.py`

## Tests

- `tests/test_search.py`
- `tests/test_transcript_review.py`
- `tests/test_speaker_mapping.py`
- `tests/test_markdown.py`
