# Feature: Search and Speaker Mapping

## Purpose

Make the local meeting library easier to query and read after meetings are
processed.

## Inputs

- `MEETINGS_DIR`
- `meeting-memory search <query>`
- Optional `SPEAKER_MAPPING_FILE`
- Meeting Memory-owned `meeting.md` files

## Outputs

- CLI search results with date, title, path, and excerpt
- Rendered participants and transcript labels with user-provided speaker names

## Behavior Notes

- Search is local and case-insensitive.
- A search query must match all terms in the normalized meeting title/body text.
- Search only reads directories identified as Meeting Memory output.
- `SPEAKER_MAPPING_FILE` is a JSON object such as
  `{"Speaker A": "Alex"}`.
- Speaker mapping is applied when rendering markdown; it does not infer names
  from the calendar or transcript.

## Related Files

- `src/meeting_memory/service/search.py`
- `src/meeting_memory/service/speaker_mapping.py`
- `src/meeting_memory/service/markdown.py`
- `src/meeting_memory/__main__.py`

## Tests

- `tests/test_search.py`
- `tests/test_speaker_mapping.py`
- `tests/test_markdown.py`
