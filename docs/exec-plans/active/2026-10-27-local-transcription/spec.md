---
status: approved
approved: 2026-10-27
plan: plan.md
---

# Specification: local transcription by default

## Approval

The specification and implementation plan were approved on 2026-10-27.
Approval includes validation with a Spanish audio sample. English support is
required. Automatic language detection for Spanish and other languages is
preferred when it adds little implementation overhead or complexity. The
original approval statement and installation-specific evidence remain in a
private record.

## Problem

Meeting Memory currently couples Transcription to a credential, a remote job,
and an AssemblyAI result. Speech recognition and diarization should run on a
supported Mac while preserving the existing workflows. AssemblyAI remains an
explicit external-provider choice.

## Desired outcome

New installations and upgrades without an explicit selection of the new
provider setting resolve to Local by default. Existing meetings, secrets,
preferences, Backup, Calendar, Notes, and their consent records are preserved.
An explicit Transcription disable remains effective.

## Checkable requirements

1. Run `mlx-community/whisper-large-v3-turbo-asr-fp16` locally through MLX with
   `condition_on_previous_text=False` and word timestamps. Run diarization with
   `mlx-community/Nemotron-3-Diarization`. Pin reproducible model revisions.
   Support English and validate execution and text preservation with a Spanish
   sample. Prefer automatic language detection without translation when it adds
   little overhead or complexity; establish its feasibility at S0A.
2. Select Local by default without requiring an API key. An inherited key,
   legacy import, or local failure must never select or activate AssemblyAI.
   Explicit provider overrides remain visible and respect external-processing
   consent.
3. Permit AssemblyAI only after explicit selection and acceptance of the
   external-processing notice, before any audio is sent. Persist acceptance with
   configuration. Canceling changes neither the provider nor permission to send
   audio. The app must not presume knowledge of an account's actual opt-out
   setting.
4. Explain that audio leaves the Mac and its handling depends on the plan,
   contract, and controls. Explain that the free plan participates in model
   improvement and does not permit opt-out, while a paid account can explicitly
   disable it. Payment alone does not establish exclusion; opt-out affects only
   future requests. Link official sources and date their verification.
5. Disclose each boundary separately: recognition and diarization run locally;
   model weights download from Hugging Face without meeting content; Backup
   sends audio and transcripts to B2; Notes and speaker suggestions send content
   to Anthropic when enabled. Do not claim complete privacy or that the entire
   application works offline.
6. Prepare models through native controls without Terminal. Check the standard
   cache first, download only missing content, and verify integrity before
   declaring readiness. Show measured progress or an indeterminate phase, with
   cancellation and actionable recovery. Do not download on startup or from
   doctor. Preparation is explicit and changes availability only. It does not
   process pending or failed meetings; those require a separate retry action.
   Recording remains available while models are missing, subject to the
   existing onboarding requirements.
7. Detect macOS Apple Silicon, actual process architecture, Metal availability,
   and runtime support. Intel, Windows, and other incompatibilities disable
   local execution only and provide an action without activating cloud
   transcription.
8. Run preparation, decoding, and inference outside the UI thread. Prevent
   duplicate simultaneous downloads or model loads. Release memory and private
   temporary files after completion, cancellation, or failure. Child processes
   receive a minimal environment without inherited credentials, and meeting
   content must not appear in command arguments or logs.
9. Preserve timestamps, text, punctuation, anonymous speakers, review and
   aliases, Notes, search, Backup, and retries. Preserve all text when speaker
   assignment is missing, using Unknown. Invent neither identities nor
   AssemblyAI IDs. If Nemotron fails completely, fail the transcription job with
   an actionable message, retain the audio, publish no partial transcript, and
   do not automatically start review or Notes.
10. Persist the provider and attempt identity for each job durably and
    atomically. Reject stale completions. An inherited remote ID must never
    start polling or upload when Local is selected. Restart must not
    automatically process historical meetings. Successful transcriptions remain
    terminal.
11. Preserve committed audio, compare-and-swap (CAS) contracts, private
    snapshots, Backup reconciliation, pause controls, and capability-based
    configuration. Do not rewrite `.env`, delete secrets, or migrate meeting
    history in bulk.
12. Preserve layers, external SDK imports exclusively in `repo/`, typed boundary
    objects, and the 300-line source limit. Condition dependencies on supported
    platforms so installation remains possible on incompatible systems.
13. Update canonical documentation, active guides, help and doctor output,
    notices, and licenses. Validate the real M4A-to-PCM path without requiring
    system FFmpeg.
14. Pass checks, review bots and CI on the latest commit, deliver through a PR
    and merge, update the primary checkout without losing existing changes, and
    reinstall and restart the official app from that checkout.

## Evidence and limits

Available comparative evidence covers three complete English meetings totaling
126.5 minutes. Aggregate word discrepancy against other AI-generated
transcripts is approximately 6 percent. This is not an error rate against human
ground truth. Semantic review found the main meaning preserved with localized
differences. Universal accuracy is not promised.

S0A also exercised a 69.8-minute Spanish recording, detected as Spanish, through
the real local pipeline. Word discrepancy against an existing AI-generated
transcript was approximately 16.3 percent, not an accuracy score against human
ground truth. Approximately 99.945 percent of words received a diarization
assignment. Four anonymous labels were produced against three reviewed
speakers; the additional label covered five words. Assignment coverage does
not measure speaker correctness. Short English and Spanish clip checks
produced matching text with automatic and forced language selection, with
measured detection overhead below one second in those clips. These observations
support the selected language-detection path without establishing general
multilingual or diarization accuracy. Private source audio and detailed results
remain outside Git.

Model cache and runtime readiness are deployment-specific checks. No personal
installation state is part of this specification.

The integrated native-decoder adapter also processed the same three complete
English recordings and one complete Spanish recording. Automatic detection
returned the expected language for every recording, and input content hashes
were unchanged. Normalized word discrepancy against the existing AI
transcripts was 6.06 percent across the English recordings and 15.51 percent for
the Spanish recording. These observations are not human-reference accuracy or
a controlled comparison between languages. The earlier 16.3 percent Spanish
observation belongs to the initial feasibility path.

## Approved product decisions

- English is required. Validate a Spanish sample and prefer automatic language
  detection when S0A establishes that it adds little overhead or complexity.
  Preserve the spoken language rather than translating the meeting. Report
  language-validation limits explicitly.
- Initial preparation uses **Prepare Local Models**. Reuse complete validated
  weights in the standard cache. Missing models do not block recording under
  the existing onboarding contract.
- Preserve the current save-provider, pause-new-jobs, and restart flow. Do not
  add live backend switching.
- Preserve existing enabled B2 and Anthropic flows with visible boundaries and
  notices. Local Notes generation and local speaker-name suggestions are
  outside this migration.

## Implementation direction

Use a serial process worker, shared cache, and fixed revisions. Generalize
attempt identity while retaining `assemblyai_id` as an optional cloud-specific
compatibility field. Technical feasibility is checked at S0A before broad
integration. Routine technical adjustments may preserve the specified product
behavior without reopening approved decisions.

## Out of scope

Live transcription; local Intel or Windows backends; alternative models; bulk
retranscription; changing the B2 onboarding gate; new retention policies; and
publishing a notarized release.

## Official sources verified on 2026-10-27

- [AssemblyAI model-improvement opt-out](https://www.assemblyai.com/docs/faq/how-to-opt-out-of-data-sharing-for-our-model-improvement-program)
- [AssemblyAI data controls](https://www.assemblyai.com/docs/data-controls)
- [Whisper model](https://huggingface.co/mlx-community/whisper-large-v3-turbo-asr-fp16)
- [Nemotron diarization model](https://huggingface.co/mlx-community/Nemotron-3-Diarization)
