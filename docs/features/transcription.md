# Feature: Transcription

## Purpose

Produce the source-of-truth diarized `transcript.md` from committed meeting
audio. Transcription defaults to Local and is enabled unless explicitly
disabled. It remains independent of Recording Core under
[`../local-first-contract.md`](../local-first-contract.md): missing models,
incompatible hardware, and processing failures preserve local audio.

## Prepare and Use Local Transcription

Local requires native arm64 macOS on Apple Silicon, Metal, and the installed
MLX runtime. Intel, Windows, and translated x86_64 processes do not support this
backend. Installation remains possible without MLX on unsupported systems, and
recording remains available under the existing B2 onboarding requirements.

1. Choose **Configuration › Prepare Local Models...** and start preparation.
   The native panel shows phases or measured progress, supports cancellation
   and retry, and leaves the tray responsive.
2. Preparation first validates the standard Hugging Face cache and downloads
   only missing content. Weight downloads send no meeting audio or text.
3. Record a new meeting after preparation. To process a recording already
   pending or failed, choose **Debugging › Retry Pending or Failed
   Transcriptions** separately and confirm the effective provider.

Preparation changes readiness only. Startup, doctor, restart, and preparation
completion do not process historical recordings. Successful transcriptions are
terminal. Saving a provider pauses new transcription jobs and requires a
restart; there is no live backend switch or automatic cloud fallback.

### Models and Language

| Role | Model | Pinned revision |
| --- | --- | --- |
| Recognition | `mlx-community/whisper-large-v3-turbo-asr-fp16` | `624c19c9af5603fa73b83bce14d4aeea96156d18` |
| Diarization | `mlx-community/Nemotron-3-Diarization` | `59ed2dbfc1346dcea9d423c71306a3a2499c568f` |

Whisper uses word timestamps, `condition_on_previous_text=False`, automatic
language detection, and `task="transcribe"`. It preserves the spoken language
rather than translating. English and Spanish have been exercised with real
audio. This is not a universal multilingual-accuracy claim. Nemotron supports
up to eight anonymous labels and does not fully resolve overlapping speech.

The cache manifest fixes expected files, sizes, and hashes for each revision.
Preparation verifies integrity, including legitimate snapshot/blob cache links.
Incomplete or corrupt weights are not ready. Inference performs full
verification before loading; doctor uses bounded local checks without loading
weights or downloading. Cancellation preserves shared cache files. Remote code
and pickle are not used.

## Configuration and External Provider Consent

The relevant settings are:

| Setting | Accepted sources | Meaning |
| --- | --- | --- |
| `TRANSCRIPTION_PROVIDER` | App preference or actual process environment only | `local` by default; `assemblyai` only by explicit choice |
| `ASSEMBLYAI_CONSENT` | App preference or actual process environment only | `external-audio-v1` after notice acceptance |
| `ASSEMBLYAI_API_KEY` | Existing supported credential sources, including legacy `.env` | Credential for explicitly selected AssemblyAI |

The provider and consent settings are intentionally ignored in legacy `.env`
and legacy imports. An inherited API key does not select AssemblyAI or grant
consent. Existing keys and Keychain references remain preserved; Local does not
read or depend on them. Explicit disablement remains effective.

Prefer **Configuration › Transcription...**. Selecting AssemblyAI requires
acceptance of the versioned external-audio notice before saving and before any
submit, polling, or retry request. Canceling leaves the provider and permission
unchanged. Development and automation must supply equivalent explicit
selection and consent through the actual process environment or app settings;
copying these values into `.env` is insufficient.

### External Provider Consent

The AssemblyAI notice identifies the automatic post-stop audio upload and
explains that handling depends on plan, contract, and account controls. Its free
plan participates in model improvement and has no opt-out. Paid accounts can
explicitly opt out; paying does not automatically exclude content. Opt-out
affects future requests only. Meeting Memory does not read or assert the
account's actual opt-out setting.

Official sources verified on 2026-10-27:

- [Model-improvement opt-out](https://www.assemblyai.com/docs/faq/how-to-opt-out-of-data-sharing-for-our-model-improvement-program)
- [Data controls](https://www.assemblyai.com/docs/data-controls)

## Inputs and Outputs

Input is an owned, committed `recording.m4a`. Local needs prepared models; cloud
needs explicit selection, consent, and an AssemblyAI key. Optional Calendar
attendees and `KNOWN_SPEAKERS` provide speaker-review candidates. Optional
Anthropic settings enable speaker suggestions and Notes.

Output is a typed `TranscriptResult` and `transcript.md` containing an AI-error
notice, provider/attempt identity, optional cloud-only `assemblyai_id`,
timestamps, anonymous speaker labels, text, `speaker_candidates`, editable
`speaker_aliases`, and `speaker_status`. Local uses no invented remote IDs.
`notes.md` is derived separately after explicit speaker confirmation or the
`meeting-memory summarize` retry command.

## Execution and Durable Identity

Preparation, decoding, and inference run outside the tray UI thread. A serial
local worker and cross-instance lock prevent duplicate simultaneous downloads
or model loads. Each inference uses a subprocess that loads Whisper, releases
it, then loads Nemotron. The process exits after completion, failure, or
cancellation to release Metal allocations. Lock ownership includes teardown;
canceling while waiting does not start a child.

The repository adapter decodes validated M4A snapshots through the native
AVFoundation helper into private mono 16 kHz PCM. It does not require system
FFmpeg or reopen the mutable original meeting path. Temporary derivatives are
removed after completion or failure. Child environments are allowlisted,
exclude inherited credentials, close unrelated descriptors, and disable
inference network access and telemetry before SDK imports. Meeting content is
not placed in arguments or worker logs. This is a constrained process boundary,
not a claim of complete operating-system isolation.

Before execution, one atomic claim records the provider, attempt ID, and
running state. Claims, remote-ID updates, success, failure, and retry compare
the captured attempt, provider, directory identity, and source-audio identity.
A replaced directory/audio file or stale completion cannot update the meeting.
An old AssemblyAI ID never causes polling or upload under Local. Historical
cloud provenance supports artifact interpretation, not egress authorization.
AssemblyAI submission is attempted once because an ambiguous submission
retry could create an orphan; a durably persisted remote job may be resumed
only under the selected and consented cloud configuration.

Completion uses one locked whole-document replace for identity CAS, transcript
body, owned fields, and Backup revision reconciliation. Speaker confirmation
uses the same transactional boundary. Legacy retries use private read-only
metadata/audio snapshots and unchanged-identity checks instead of routing
historical files through the schema-v2 writer.

## Alignment and Failures

Words align to the diarization turn with greatest positive overlap, with
stable tie-breaking and half-open intervals for zero-duration words. Gaps use
Unknown rather than a guessed nearest speaker. Preserve text and segments when
word timing is absent, and reject invalid or non-finite timestamps. Anonymous
labels identify turns, not people.

Missing or corrupt models leave work pending with a preparation action.
Unsupported hardware, unavailable runtime, and inference errors report an
action while preserving audio. Complete Nemotron failure fails the whole job:
no partial transcript, review notification, or automatic Notes is published.
Unknown applies to gaps in otherwise completed diarization. No failure selects
AssemblyAI.

**Retry Pending or Failed Transcriptions** scans durable Transcription state
only, never Backup. It requires an explicit action and effective-provider
confirmation. A fresh attempt replaces the prior identity atomically, and
successful transcripts stay terminal. Neither provider changes nor model
preparation automatically retry history.

## Speaker Review and Notes

After successful transcription, a background worker prepares review before the
main thread sends **Transcript ready** with **Review Speakers**. Configured
Calendar attendees populate candidates; explicit `KNOWN_SPEAKERS` matches
normalize their names. When Notes is enabled, preparation can send a bounded
diarized excerpt, named Calendar candidates, and available roster descriptions
to Claude Haiku before confirmation. Missing profiles do not block other
suggestions; unresolved email-only candidates stay local and disable elimination.
Matching
emails/aliases, frontmatter, and provider IDs remain local. Suggestions honor
Notes pause, require exact evidence from the indicated label, and never assign
identities without user confirmation. After direct matches leave one candidate
and one substantive speaker, a context-supported elimination proposal may be
shown with an explicit **By elimination (verify)** clue. Unknown fragments and
extra labels do not force an assignment. Unresolved or ambiguous cases remain
manual. Prepared suggestions and manual fallbacks are session-only; opening
unchanged review reuses them. Historical review prepares on demand.

**Confirm Names** applies aliases through local deterministic code. **Keep
Speaker Labels** preserves anonymous labels, leaves aliases empty, and still
confirms review. Either can start enabled Notes. A kept-label transcript can
receive one later complete alias correction through **Debugging › Correct
Speakers**, which regenerates Notes. Named aliases are terminal. The former
automatic Notes toggle is ignored.

Notes send fixed schema/identity instructions, editable guidance, and only the
speaker-confirmed excerpt, capped at 60,000 characters. The local Markdown
layout and Calendar attendee prefix are excluded. Reviewed identities are
preserved; anonymous identities cannot be inferred from mentions or topics.
Explicitly named task recipients remain allowed. Output-limit responses are
rejected without partial publication. Failures preserve the transcript, and
`meeting-memory summarize <meeting-folder>` remains a manual retry for confirmed
transcripts. **Debugging › Pending Meeting Tasks** exposes missing Notes.

The native **Notes Customization...** workspace edits the private versioned
profile; the repository prompt is a read-only built-in fallback. The standalone
**Known Speakers...** editor can draft names locally from confirmed history.
Only its explicit **Suggest Topics** action sends historical quotes to
Anthropic. See [search and speaker mapping](search-and-speaker-mapping.md) for
roster and evidence rules.

Local transcription does not make the whole application offline or wholly
local: required B2 Backup sends audio/transcripts, and enabled Anthropic
suggestions and Notes send bounded content at the triggers above.

## Verification

`make check` uses fakes and requires neither GPU, model weights, nor network.
The explicit hardware check uses real audio, preserves the source meeting,
and writes results to the selected private output:

```bash
make PYTHON=.venv/bin/python check-local-transcription \
  LOCAL_CHECK_ARGS='"/path/to/recording.m4a" --expected-language es --helper .build/MeetingMemoryCapture --output /path/to/private-results/result.json'
```

Use `--expected-language en` for an English sample. Keep results and source
meeting content outside Git. Anonymized feasibility observations and delivery
checks are recorded with the approved execution plan.

## Related Files

- `src/meeting_memory/repo/local_transcription.py`
- `src/meeting_memory/repo/local_models.py`
- `src/meeting_memory/repo/local_model_cache.py`
- `src/meeting_memory/repo/local_process.py`
- `src/meeting_memory/repo/native_audio_decoding.py`
- `src/meeting_memory/repo/transcription.py`
- `src/meeting_memory/service/local_transcription.py`
- `src/meeting_memory/service/transcription_attempts.py`
- `src/meeting_memory/service/runtime_transcription.py`
- `src/meeting_memory/service/local_model_preparation.py`
- `src/meeting_memory/ui/transcription_form.py`
- `src/meeting_memory/ui/local_models.py`
- `scripts/check_local_transcription.py`

## Tests

- `tests/test_local_transcription_configuration.py`
- `tests/test_transcription_external_consent.py`
- `tests/test_local_model_cache.py`
- `tests/test_local_model_preparation.py`
- `tests/test_local_transcription_output.py`
- `tests/test_local_transcription_readiness.py`
- `tests/test_local_models_ui.py`
- `tests/test_transcription_form.py`
- `tests/test_runtime_job_identity.py`
- `tests/test_transcript_review.py`
- `tests/test_speaker_mapping.py`
