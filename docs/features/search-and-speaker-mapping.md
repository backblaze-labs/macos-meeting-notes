# Feature: Search and Speaker Review

## Purpose

Make the local meeting library easier to query and read after meetings are
processed.

## Inputs

- `MEETINGS_DIR`
- Local `KNOWN_SPEAKERS` roster (canonical names, match aliases/emails, optional role/topics)
- Optional existing Notes Anthropic key and current-session Notes pause
- `meeting-memory search <query>`
- `meeting-memory relabel <meeting-folder>`
- Meeting Memory-owned `transcript.md` files

## Outputs

- CLI search results with date, title, path, and excerpt
- In-memory Claude Haiku name proposals with supporting quotes for review
- Reviewed `transcript.md` files with user-confirmed speaker aliases

## Behavior Notes

- Search is local and case-insensitive.
- A search query must match all terms in the normalized meeting title/body text.
- Search only reads directories identified as Meeting Memory output.
- `speaker_aliases` in `transcript.md` is the preferred per-meeting source for
  confirmed names.
- Calendar attendees populate `speaker_candidates` as hints. Attendees are
  shown by Calendar full name, except aliases explicitly configured in
  `KNOWN_SPEAKERS` when the attendee name or email matches. The tray asks for
  a speaker review after each transcription unless the opt-in automatic
  Notes mode is on (`transcription.md`).
- Opening **Review Speakers** or **Correct Speakers** fetches proposed names in
  a background worker when every Calendar candidate matches the local roster.
  The existing native Known Speakers editor adds optional role/topics context
  of at most 300 characters per person. No separate KB service is required.
- Claude Haiku uses the existing Notes key and receives only relevant canonical
  names, descriptions, and diarized local transcript text, capped at 60,000
  characters on complete utterances. Matching emails/aliases, frontmatter,
  paths, and provider IDs stay local. AssemblyAI performs diarization only.
- Proposed names preselect the existing controls and show exact supporting
  quotes spoken by that label. Users must verify and confirm them. Existing
  manual selections take precedence; Cancel changes no meeting files.
- Unknown attendees, insufficient evidence, ambiguous duplicates, paused Notes,
  and provider failures retain manual review. Partial proposals may leave
  speakers unresolved; every invited person need not have spoken.
- Successful proposals are cached only for the app session, bound to the
  transcript and relevant roster context. Changed local state drops stale
  proposals before display. Reopening review retries unsuccessful requests.
- Confirmed relabeling remains local deterministic code. The proposal request
  does not change local aliases or the provider's diarized transcript. The CLI
  relabel command does not call an LLM.

## Related Files

- `src/meeting_memory/service/search.py`
- `src/meeting_memory/service/transcript_review.py`
- `src/meeting_memory/service/speaker_suggestions.py`
- `src/meeting_memory/service/speaker_excerpt.py`
- `src/meeting_memory/repo/claude_speaker_identification.py`
- `src/meeting_memory/ui/speaker_review_flow.py`
- `src/meeting_memory/ui/preference_forms.py`
- `src/meeting_memory/service/speaker_mapping.py`
- `src/meeting_memory/service/markdown.py`
- `src/meeting_memory/__main__.py`

## Tests

- `tests/test_search.py`
- `tests/test_transcript_review.py`
- `tests/test_speaker_suggestions.py`
- `tests/test_speaker_suggestions_ui.py`
- `tests/test_claude_speaker_identification.py`
- `tests/test_speaker_knowledge.py`
- `tests/test_speaker_mapping.py`
- `tests/test_markdown.py`
