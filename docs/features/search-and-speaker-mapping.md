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

- **Configuration › Known Speakers...** exposes the local people base without
  requiring Calendar setup. Ordinary edits use the saved roster; **Create from
  Previous Meetings** explicitly adds exact confirmed names to an editable draft.
  It reads at most 20 confirmed named transcripts in the latest 200 folders,
  each at most 2 MiB, and reports the included/scanned counts. Kept labels,
  unreviewed records, and foreign artifacts are excluded. No similarly named
  people or Calendar aliases are merged by guessing.
- The empty-roster runtime offers building the base once when confirmed history
  exists. After speaker confirmation attempts to start Notes, new named people
  receive a one-time addition offer. Private atomic suppression prevents repeats.
  Names-only editing works during setup and with Notes paused/unavailable.
- Optional **Suggest Topics** explicitly discloses sending confirmed names and
  their own excerpts to Haiku 5.5 low (4,000 characters per person, 60,000 total).
  Only unique supplied names with exact same-person quote evidence receive
  proposed descriptions; all descriptions remain editable, capped at 300 chars.
  Existing descriptions are preserved. Cancellation saves nothing, and failures
  retain the names-only draft.
- Saving changes only the private `KNOWN_SPEAKERS` preference via CAS. Concurrent
  configuration changes require reopening; effective runtime changes require
  restart. This does not change Calendar enablement or stop ongoing Notes.
- Search is local and case-insensitive.
- A search query must match all terms in the normalized meeting title/body text.
- Search only reads directories identified as Meeting Memory output.
- `speaker_aliases` in `transcript.md` is the preferred per-meeting source for
  confirmed names.
- Calendar attendees populate `speaker_candidates` as hints. Attendees are
  shown by Calendar full name, except aliases explicitly configured in
  `KNOWN_SPEAKERS` when the attendee name or email matches. The tray asks for
  explicit speaker review after every transcription (`transcription.md`).
- After transcription, a worker prepares review before the actionable
  **Transcript ready** notification. It fetches proposed names when every
  Calendar candidate matches the local roster. Clicking **Review Speakers**
  reuses the prepared result or joins the pending worker. Historical Debugging
  review actions prepare on demand.
  The existing native Known Speakers editor adds optional role/topics context
  of at most 300 characters per person. No separate KB service is required.
- Claude Haiku uses the existing Notes key and receives only relevant canonical
  names, descriptions, and diarized local transcript text, capped at 60,000
  characters on complete utterances. Matching emails/aliases, frontmatter,
  paths, and provider IDs stay local. AssemblyAI performs diarization only.
- Proposed names preselect the existing controls and show exact supporting
  quotes spoken by that label. Users must verify and confirm them. Existing
  manual selections take precedence; Cancel changes no meeting files.
- Speaker identification allows up to 8,192 response tokens, including model
  reasoning, with fixed Haiku 5.5 low effort. Output-limit responses are rejected
  before JSON parsing and expose a sanitized incomplete-response fallback. This
  does not change the Notes or topic-description response budget or add retries.
- Unknown attendees, insufficient evidence, ambiguous duplicates, paused Notes,
  and provider failures retain manual review. Partial proposals may leave
  speakers unresolved; every invited person need not have spoken.
- Prepared reviews, including empty/error manual fallbacks, are cached only
  for the app session. Canceling and reopening unchanged review makes no new
  API request. Successful proposals are bound to transcript and relevant roster
  context; changed review identity reloads on a worker before display. Restart
  clears these caches. Notes pause also suppresses cached proposals.
- Confirm Names or Keep Speaker Labels starts Notes from those reviewed
  identities. Notes receive no Calendar prefix and must not infer anonymous
  speaker names independently; explicitly named task recipients remain allowed.
- Confirmed relabeling remains local deterministic code. The proposal request
  does not change local aliases or the provider's diarized transcript. The CLI
  relabel command does not call an LLM.

## Related Files

- `src/meeting_memory/service/search.py`
- `src/meeting_memory/service/transcript_review.py`
- `src/meeting_memory/service/speaker_knowledge.py`
- `src/meeting_memory/service/speaker_history.py`
- `src/meeting_memory/service/speaker_knowledge_offers.py`
- `src/meeting_memory/repo/claude_speaker_topics.py`
- `src/meeting_memory/ui/speaker_knowledge.py`
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
- `tests/test_speaker_history.py`
- `tests/test_speaker_knowledge_ui.py`
- `tests/test_claude_speaker_topics.py`
- `tests/test_speaker_mapping.py`
- `tests/test_markdown.py`
