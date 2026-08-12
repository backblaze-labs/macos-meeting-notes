# Product

## Register

product

## Users

Knowledge workers on macOS who attend several video meetings each week and
want a private, searchable record without managing a server. They use the menu
bar app while moving between meetings and expect recording, transcription,
speaker review, and note generation to require little attention.

A first-time user is not assumed to have a Terminal workflow. They do need a
Backblaze B2 account and bucket-scoped credentials to complete onboarding;
Transcription, Calendar, and Notes remain progressive enhancements.

## Product Purpose

Meeting Memory records meetings, creates diarized transcripts, derives useful
notes, keeps the canonical artifacts on the user's Mac, and backs them up to
required Backblaze B2 storage. Success means the user can capture a
meeting reliably, understand what is happening at a glance, and later find
portable Markdown notes without having to reconstruct context.

The first success starts after required B2 setup: launch the app, record about
30 seconds of real audio, stop, play the local result, and confirm its private
B2 backup. Recording Core preserves the local artifact independently;
Transcription, Calendar, and Notes are optional capabilities.
Their composition and readiness semantics are defined in
[`docs/local-first-contract.md`](docs/local-first-contract.md).

## Brand Personality

Discreet, dependable, and practical. The app should feel calm during meetings,
plainspoken when it needs attention, and trustworthy around private data.

## Anti-references

Do not make the app feel like a marketing site, a decorative AI dashboard, or
an attention-seeking recording tool. Avoid novel controls where a standard
macOS affordance exists, hidden state, promotional copy, and visual decoration
that competes with the user's meeting.

## Design Principles

- Keep the meeting, not the app, at the center of attention.
- Make recording and processing state unmistakable at a glance.
- Prefer familiar macOS controls and language over custom interaction patterns.
- Preserve user control over private data, speaker identity, and AI behavior.
- Explain failures with a concrete recovery action.
- Let provider failures, including B2 upload failures after setup, preserve and
  expose the local recording with a concrete retry path.
- Name data egress before enabling an external integration.

## Accessibility & Inclusion

Use native macOS controls and system typography so keyboard navigation, focus,
VoiceOver semantics, contrast, and text scaling follow platform conventions.
Never rely on color alone to communicate state. Keep motion minimal and honor
the system's reduced-motion preference wherever custom motion is introduced.
