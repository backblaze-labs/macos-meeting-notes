# Product

## Register

product

## Users

Knowledge workers on macOS who attend several video meetings each week and
want a private, searchable record without managing a server. They use the menu
bar app while moving between meetings and expect recording, transcription,
speaker review, and note generation to require little attention.

A first-time user is not assumed to have a Terminal workflow, cloud account,
or API credentials. Integrations are progressive enhancements for users who
choose them.

## Product Purpose

Meeting Memory records meetings, creates diarized transcripts, derives useful
notes, keeps the canonical artifacts on the user's Mac, and backs them up to
Backblaze B2 when the user enables Backup. Success means the user can capture a
meeting reliably, understand what is happening at a glance, and later find
portable Markdown notes without having to reconstruct context.

The first success is smaller and local: launch the app, record about 30 seconds
of real audio, stop, play the result, and reveal its directory in Finder in
under five minutes. Recording Core stands alone; Transcription, Backup,
Calendar, and Notes are optional capabilities.
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
- Let optional capabilities fail independently without hiding local recording.
- Name data egress before enabling an external integration.

## Accessibility & Inclusion

Use native macOS controls and system typography so keyboard navigation, focus,
VoiceOver semantics, contrast, and text scaling follow platform conventions.
Never rely on color alone to communicate state. Keep motion minimal and honor
the system's reduced-motion preference wherever custom motion is introduced.
