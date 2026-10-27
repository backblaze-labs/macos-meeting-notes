---
status: approved
approved: 2026-10-27
spec: spec.md
---

# Implementation plan: local transcription and diarization

## Approval and evidence boundaries

The specification and plan were approved on 2026-10-27, including Spanish audio
validation. English support is required. Automatic language detection for
Spanish and other languages is preferred when it adds little overhead or
complexity. The original approval statement, installation-specific checks, and
private validation data remain outside Git. Public evidence is limited to
anonymized aggregate observations and reproducible checks.

S0A is the first implementation gate. Complete it before broad configuration,
runtime, or UI changes. Existing product documentation describes the current
implementation until its corresponding behavior changes in S1 through S4.

## Design and technical decisions

- Transcription distinguishes enabled state, provider, and versioned acceptance
  of external processing. An absent provider means Local. An API key alone
  changes neither selection nor consent. Preserve explicit disablement. Apply
  existing precedence without allowing a process key to activate cloud
  transcription. CLI and automation require equivalent documented external
  selection and acceptance.
- Retain AssemblyAI Keychain references. Local neither reads them nor depends on
  their availability. The preference store writes minimal changes through CAS
  without touching `.env` or unrelated capabilities.
- Saving a provider preserves pause and restart behavior. Stop new requests
  immediately after the change. A remote request already sent cannot be
  recalled. No local configuration change schedules historical processing.
- Introduce typed provider, attempt, and job identity. Keep `assemblyai_id`
  optional and cloud-specific. Historical readers infer remote provenance only
  to interpret artifacts, never to authorize egress. Claiming a job atomically
  stores provider, attempt, and running state before execution. Success,
  failure, and retry compare attempt identity, provider, and captured
  directory/audio identity. Audit persistence, field ownership, speaker review
  and mapping, suggestion caches, and every `assemblyai_id` consumer without
  introducing a generic job framework. Never route an old ID to the selected
  backend accidentally.
- A serial coordinator handles local meetings with app-level single flight and
  a cross-instance lock for model loading and downloads. Each job uses a child
  process controlled by the repository adapter. Load Whisper, run it, and
  release it; then load Nemotron, run it, and release it. Exit the process to
  recover Metal memory. The lock covers inference and teardown. Canceling a job
  waiting for the lock removes it without starting a child. Do not create a
  persistent worker pool. Scheduling, durable state, and alignment stay in
  `service/`; SDKs, subprocesses, downloads, and native decoding stay in `repo/`.
- Separate model downloading from inference. The downloader receives only
  allowlisted model IDs and revisions, never audio or text. Use the standard
  Hugging Face cache, resolve locally before network access, and resume missing
  content. Maintain a per-revision manifest of expected files, sizes, and hashes
  from official metadata, validated before publication. Accept legitimate
  snapshot/blob cache links only after validating their destinations against
  the manifest. Reject arbitrary paths. Load only safetensors and approved
  declarative resources, never pickle or remote code. Incomplete or corrupt
  caches remain unready. Canceling never removes shared weights. Readiness uses
  bounded local checks; full verification runs in a worker before loading.
  The UI does not run pip or remote code.
- Both downloader and inference children receive a minimal allowlisted
  environment without inherited cloud or Hugging Face credentials, with
  unrelated file descriptors closed. Inference receives approved model
  snapshots and private temporary audio, with offline mode and telemetry
  disabled before imports. Keep meeting audio and text out of arguments and
  logs. Test with decoy parent credentials and prove their absence in both
  children.
- Evaluated model revisions are Whisper
  `624c19c9af5603fa73b83bce14d4aeea96156d18` and Nemotron
  `59ed2dbfc1346dcea9d423c71306a3a2499c568f`. Evaluated package versions are
  `mlx-audio==0.6.2`, `mlx==0.32.4`, `mlx-metal==0.32.4`, and
  `huggingface-hub==2.3.0`. Resolve a compatible reproducible dependency set
  before final pinning and record justified technical adjustments.
- Decode M4A through AVFoundation in the native helper into private temporary
  mono 16 kHz PCM. Do not expand the minimal encoder or require system FFmpeg or
  Homebrew. The adapter and helper consume an existing validated snapshot or
  its private derivative, never reopen the original mutable meeting path, and
  clean temporary files in `finally`.
- Align words deterministically by maximum positive overlap with Nemotron
  turns, stable tie-breaking, and half-open intervals for zero-duration words.
  Use Unknown for gaps rather than the nearest speaker. Preserve segments and
  text when word timing is absent. Reject non-finite or invalid timestamps. Do
  not infer people. Diarization supports up to eight labels and does not fully
  resolve overlapping speech.
- Complete Nemotron failure fails the whole job while preserving audio and
  offering Retry. Publish no partial transcript and do not start review or
  Notes. Unknown is reserved for assignment gaps within completed diarization.
- Model preparation changes readiness only. A new recording pending because
  models are missing remains pending after preparation. Offer a separate
  **Retry Pending or Failed Transcriptions** action that confirms the effective
  provider. Never scan or process backlog automatically. Successful
  transcriptions remain terminal.
- Native UI shows the effective provider, Prepare, Cancel, Retry, and phase
  status. Show percentages only from actual measurements. Identify downloads
  from Hugging Face and the capabilities that send content externally.
  Doctor/readiness perform bounded local checks without loading weights or
  contacting providers.
- The child boundary accepts local model/audio snapshots and private output,
  with no external secrets as input. This is not a claim of complete OS
  isolation. Validate IPC messages, sizes, timestamps, source identity, and
  schema before consuming results. Generated text must never determine
  commands, paths, references, URLs, or executable code.
- Require English support and validate a Spanish sample. At S0A, verify whether
  automatic language detection preserves Spanish and other spoken languages
  without material added complexity. Do not add translation. If language
  support needs broader product scope, report the concrete evidence rather
  than silently expanding implementation or claiming validation.

## Steps and gates

### S0. Record approval and prepare delivery

Dependencies: explicit approval, received on 2026-10-27.

Publish this neutral approval record and retain private evidence separately.
Preserve existing untracked files and primary-checkout changes. Verify the
required personal Git identity and appropriate repository authentication
without exposing credentials. Fetch `origin/main` and use the dedicated
`codex/local-transcription` branch in a managed worktree. Keep the primary
checkout unchanged while developing.

Check: record primary/worktree status and the remote baseline. Run the baseline
gate before relevant implementation changes.

### S0A. Local feasibility gate

Dependencies: S0. This precedes S1 through S4.

Install the pinned MLX dependency set in the isolated worktree environment and
verify actual APIs against validated local snapshots. Establish automatic
language-detection support and absence of implicit downloads. Implement the
bounded native decoder reused by S2 and validate real M4A input. Exercise MLX
collection and imports in the existing arm64 build target before integrating
configuration or UI.

Check: typed output with timestamps; effective
`condition_on_previous_text=False`; offline inference using local snapshots;
correct mono 16 kHz PCM decoding; and library loading from the arm64 artifact.
Check English support and record a Spanish-sample result or the specific
remaining validation step. Document a justified version correction without
changing models or product commitments. If the required outcome is infeasible,
stop broad implementation and report concrete evidence.

### S1. Configuration, consent, and contracts

Dependencies: S0A.

Add provider and consent to types, schema, resolution, validation, runtime, and
editing/import flows. Keep Local independent of cloud secrets. Generalize
`TranscriptResult`, durable attempt identity, and legacy compatibility without
invented remote IDs.

Check: regression tests for new/upgrade defaults, inherited-key inactivity,
explicit disablement, overrides, unavailable Keychain under Local, canceled
consent, preference CAS, historical readers, and stale completions.

### S2. Audio, models, and worker

Dependencies: S1.

Consolidate S0A's validated native M4A decoder. Add lazy MLX/Hugging Face
adapters, single-flight preparation, and a cancelable serial subprocess worker.
Install compatible platform-conditioned dependencies and include license
notices. Jobs receive no external secrets.

Check: real M4A decodes correctly without system FFmpeg; a complete cache works
with network blocked; simulated interrupted/incomplete downloads, corrupt or
truncated weights, permissions, and disk failures recover correctly; valid
cache links pass and invalid targets fail; preparation processes no pending
meetings; decoy secrets are absent from children; concurrent meetings and
instances do not duplicate loads; cancellation/failure releases locks, child
resources, and temporary files; structural checks reject SDK imports outside
`repo/`.

### S3. Runtime integration, alignment, and retries

Dependencies: S1 and S2.

Connect one selected backend to existing snapshots, states, and events. Preserve
formatting, speaker review, Notes, and Backup. Local retry creates its own
attempt. An inherited cloud ID cannot cause upload or polling under Local.
Explain unsupported pending work without changing provider.

Check: alignment covers overlap, gaps, silence, punctuation, and incomplete
timing; runtime/legacy identity CAS rejects replaced directories and stale
attempts; cancellation/failure preserves audio; fake cloud paths retain
submit/persist/resume behavior; spies prove zero AssemblyAI calls from Local
and no cloud fallback on any local failure; Notes and Backup retain their
contracts.

### S4. UI and documentation

Dependencies: S1 through S3.

Extend the native Transcription form, model preparation, typed events,
recovery, and readiness. Show the cloud notice before persisting acceptance,
with official sources. Review `README.md`, `PRODUCT.md`, `SPEC.md`,
`docs/local-first-contract.md`, `ARCHITECTURE.md`, the transcription feature
document, `.env.example`, agent setup, help, and active guides. Update current
references to the replaced flow. Recheck sources before final notice wording.
Record genuinely incomplete work in `docs/deferred-work.md` with its reason and
first future check.

Check: configuration/UI tests cover cancel, confirm, restart, incompatibility,
and phases; inspect the rendered native flow; run doctor without a key and
without network; search for stale claims that AssemblyAI is required, all
processing is private, or the whole application works offline.

### S5. Integrated validation and review

Dependencies: S1 through S4.

Run full `make check` with fakes and without requiring Metal, weights, or
network. Add a named Apple Silicon integration command for real audio/models
and another for arm64 target verification. Exercise the real adapter offline
against the three English benchmark recordings, preserving private results and
leaving source meetings unchanged. Check text completeness, timestamps, and
labels, and use comparative word discrepancy only as a diagnostic rather than
human ground truth. Add a Spanish sample to validate execution and text
preservation without claiming broad multilingual accuracy.

Record peak-memory observations without requiring an exact decrease in
OS-reported RAM. Assert child termination, descriptor closure, temporary-file
cleanup, lock release, and absence of duplicate work. Build and verify MLX in
the existing standalone arm64 artifact. Do not claim a notarized release.

Check: `make check` exits zero; real M4A/model evidence exists; inference makes
no external calls and succeeds with network blocked; code/diff review finds no
credentials or private meeting data. The coordinating agent runs checks and
records evidence independently of an implementer's statement.

### S6. PR, merge, and official app

Dependencies: S5.

Commit and push a passing complete slice. Create an assigned draft PR and
attach it to the chat. Wait for all checks and bot reviews on the latest head,
evaluate their findings, and fix applicable issues. Merge follows the approved
end-to-end delivery workflow. Fast-forward the primary checkout from
`origin/main` without overwriting prior changes. Install compatible dependencies
from the primary checkout and run
`make PYTHON=.venv/bin/python reload-macos-app` there. Verify effective Local
selection, reuse of the validated cache, and the running official app. Delete
the merged feature branch and archive the managed worktree.

Check: latest-commit CI and review findings are resolved; main contains the
merge; the launcher uses the permanent primary checkout; the official app is
restarted with correct local preparation/status; unrelated configuration is
preserved without exposing secrets; prior primary-checkout changes remain.
Complete the validation table and move this plan and specification to
`docs/exec-plans/completed/` at delivery.

## Requirement validation

| Requirement | Required evidence | Observed |
| --- | --- | --- |
| 1 | Exact configuration, real offline inference, word timestamps, English and Spanish sample checks | Passed real integrated native-decoder checks on three English recordings and one Spanish recording, with expected auto detection, word timestamps, and unchanged input hashes. |
| 2 | New/upgrade/disabled/override cases and no implicit cloud calls | Passed new/upgrade/default, explicit disable, malformed and mixed-source override, no-fallback composition, and unused-cloud-Keychain tests. |
| 3 | Consent cancel/confirm and guards before submit, poll, and retry | Passed native form cancel/confirm tests and actual-SDK MockTransport admission tests across upload, create, polling, retries, and deadlines; no real cloud audio requests. |
| 4 | Dated official sources and notice without automatic paid-plan exclusion claims | Official sources verified 2026-10-27; dated linked native notice and copy tests confirm free-plan limits and explicit prospective paid-account opt-out. |
| 5 | Separate B2, Anthropic, Hugging Face, and local disclosures | Native forms and synchronized docs separately disclose local inference, model download, B2 Backup, Anthropic Notes, and speaker suggestions. |
| 6 | Complete-cache reuse, simulated missing downloads, native cancel/retry | Passed complete-cache reuse with network blocked, simulated missing/corrupt downloads, cancellation, and readiness-only preparation tests. |
| 7 | Platform, Metal, and runtime tests with native recovery action | Passed platform/runtime fakes and bounded real no-weights Metal probe; dependency resolution excludes MLX on Intel. |
| 8 | Serial worker, responsive UI, child termination and temporary cleanup | Passed native rendering and cancellation/shutdown tests, inherited-lock and parent-death child-process tests, private cleanup, and serial-worker tests. |
| 9 | Formatting, review, aliases, Notes, Backup, and real samples | Passed alignment, Markdown, review, alias, Notes, Backup, legacy, and local runtime regressions plus four complete real audio checks. |
| 10 | Provider/attempt CAS and legacy handling without egress | Passed provider/attempt/source CAS, stale-completion rejection, restart source checks, cloud ID retention, and explicit changed-source recovery tests. |
| 11 | Preserved audio, unchanged `.env`, unrelated preferences retained | Passed source-unchanged checks for all audio inputs, byte-hash checks for existing .env/preferences, and unrelated-reference preservation tests. |
| 12 | Full gate, dependency markers, and packaging verification | Passed make check with 1,364 tests plus five structural tests; clean locked arm64 install, arm64/Intel resolution, arm64 bundle build and strict relocated verification. Remote CI remains part of S6. |
| 13 | Reviewed docs/guides/doctor/licenses and real M4A decoding | Canonical docs and active guides synchronized; notices/licenses reviewed; doctor/provider readiness tested; final native decode verified after lifecycle fixes. |
| 14 | PR/merge, latest reviews, and official app from main | Pending remote PR checks, merge, primary fast-forward, official installation/restart, and final delivery evidence. |

## Progress

| Step | Status | Recorded evidence |
| --- | --- | --- |
| S0 | Complete | Approved public records and isolated feature worktree prepared; private evidence retained outside Git |
| S0A | Passed | Native M4A decode, pinned offline inference, language detection, cache reuse, and arm64 artifact viability established |
| S1 | Complete | Provider configuration, consent, and compatibility tests passed |
| S2 | Complete | Native decoding, pinned cache, serial worker, cleanup, and packaging checks passed |
| S3 | Complete | Provider/source attempts, retries, alignment, Notes, and Backup regressions passed |
| S4 | Complete | Native forms/progress, disclosures, canonical docs, and active guides synchronized |
| S5 | Complete | Local full gate, four real audio checks, independent reviews, and strict arm64 bundle verification passed |
| S6 | Pending | Remote checks, merge, primary checkout update, official app reload, and final evidence remain required |

### S0A Feasibility Evidence

- An independent integration run decoded real M4A input through the native
  helper to mono 16 kHz PCM and verified private temporary cleanup.
- Real inference used the pinned model snapshots without implicit downloads.
  English and Spanish clips preserved the same text with automatic and forced
  language selection. Measured automatic-detection overhead was below one
  second in those clips, supporting automatic detection without added product
  controls or translation.
- A complete 69.8-minute Spanish recording was detected as Spanish. Comparative
  word discrepancy was approximately 16.3 percent against an existing
  AI-generated transcript, not human ground truth. About 99.945 percent of
  words received an assignment. Four anonymous labels were produced against
  three reviewed speakers; the fourth label covered five words. Coverage is
  not a speaker-correctness score. These are bounded observations, not a
  universal multilingual-accuracy claim.
- A full arm64 standalone app build passed. Frozen imports and a Metal
  operation passed in that artifact. This establishes MLX collection/runtime
  viability, not notarized release acceptance.
- Explicit preparation reused validated cached weights with network access
  disabled. Historical-processing behavior remains part of the integrated
  validation gate.

The R1 language-validation condition has feasibility evidence. The final
integrated implementation must still preserve these settings and pass S5.
Source recordings, detailed results, machine-specific diagnostics, and approval
wording remain private.

## Independent review findings

Independent reviewers examined the design in fresh contexts without editing the
checkout. Their findings are incorporated as follows:

- Security, essential: specify child environment isolation. Added an allowlisted
  environment, no inherited credentials, closed descriptors, content outside
  arguments/logs, and tests with decoy secrets.
- Security, essential: specify cache integrity and cancellation. Added
  per-revision manifests, Hugging Face link validation, no pickle or remote
  code, incomplete-cache rejection, and preservation of shared weights.
- Public readiness, essential: separate installation-specific evidence from
  publishable records. Added private evidence/original approval storage and
  neutral public decisions.
- Security, minor: clarify that opt-out is prospective. Included in the notice
  requirement.
- Simplification and developer experience: separate preparation from retry and
  define pending/failed work. Preparation never processes history.
- Simplification and developer experience: verify MLX, decode, and packaging
  feasibility before broad changes. Added S0A.
- Simplification and developer experience: define complete diarization failure.
  The job fails without partial transcript publication or automatic Notes.
- Simplification and developer experience: constrain layers and snapshots. Do
  not reopen mutable originals or introduce a generic framework.
- Simplification and developer experience: persist atomic identity before
  execution and audit consumers. Included in design and S1/S3.
- Simplification and developer experience: separate deterministic checks from
  hardware integration and verify observable cleanup. Included in S5, with the
  lock covering teardown and cancellation while waiting.

The reviews identified no conflicting recommendations. Both reviewers found
the design coherent, including serial processing and restart-based provider
changes.

## Log

- 2026-10-27: incorporated independent reviews before approval; reviewers
  reported no checkout changes.
- 2026-10-27: approved specification and plan, including Spanish validation.
  English support remains mandatory; automatic detection is preferred subject
  to the bounded feasibility check.
- 2026-10-27: recorded only anonymized aggregate English benchmark evidence in
  the public specification. Spanish validation and implementation checks remain
  pending.

- 2026-10-27: S0 completed with approval records and isolated worktree. S0A
  passed real native decoding, offline pinned-model inference, English/Spanish
  language checks, warm-cache offline preparation, and arm64 frozen-runtime
  viability. Automatic detection selected for the integrated implementation.
- 2026-10-27: recorded anonymized Spanish language and diarization observations
  for R1. Integrated validation, latest-revision reviews, and delivery remain
  pending; no later step is marked complete by this evidence.

- 2026-10-27: integrated adapter checks processed all three English recordings
  and the Spanish recording with expected automatic language detection and
  unchanged input hashes. English micro word discrepancy was 6.06 percent;
  Spanish word discrepancy was 15.51 percent, both against imperfect existing
  AI transcripts. Private outputs remain outside the repository.
- 2026-10-27: orchestrator gate passed: 1,364 tests plus five structural tests,
  with Ruff passing. A subsequent focused run of 46 SDK, retry, configuration,
  local-state, and legacy tests passed on the final affected source.
- 2026-10-27: independent implementation reviews identified and resolved worker
  lifetime cleanup, word timestamp bounds, per-request external admission and
  deadlines, mixed-source credential resolution, and changed-source retry
  recovery. Additional ID-retention tests cover deadline responses and legacy
  submit/persist/resume. A reviewer independently confirmed the three state
  and provider findings resolved with 25 focused tests.
- 2026-10-27: graceful shutdown routes menu, Cocoa termination, normal return,
  and SIGTERM through idempotent cancellation. Harmless child-process tests
  verify parent-death cleanup and inherited operation-lock retention. Native
  audio decoding was rebuilt and independently verified after lifecycle fixes.
- 2026-10-27: the distribution lock preserves existing shared versions and
  adds platform-scoped backend pins. Clean arm64 installation, dependency
  consistency, selected imports, and Metal probe passed. Both arm64 and Intel
  dependency resolution passed; Intel excludes MLX. Final artifact verification
  and remote CI remain pending.
- 2026-10-27: omit the optional Tokenizers CycloneDX build report from bundled
  metadata because its filename matches the strict token-file denylist.
  Runtime metadata and licenses remain included; the credential verifier is
  unchanged. This corrects packaging contents rather than relaxing the gate.
- 2026-10-27: official installation remains a post-merge delivery step. The
  running official application and primary checkout have not been changed.

- 2026-10-27: final locked arm64 artifact built and passed the strict verifier,
  including relocated self-check and signature checks. The final frozen worker
  dispatch and bounded no-weights Metal check also passed. Distribution
  contract/structure tests passed separately (23 tests). A test collection check
  confirmed the final full-gate count remains 1,364.
