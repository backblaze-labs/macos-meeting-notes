# Standalone Validation Evidence

This file records only sanitized distribution evidence. Never add recordings,
transcripts, usernames, local paths, permission-database contents, credentials,
or provider responses.

## Completed locally

The `arm64` ad-hoc app was built from a fresh Python 3.11 environment installed
only from `requirements-distribution.lock`. The artifact passed the static and
dynamic verifier after relocation to an unrelated temporary directory with a
fresh HOME and foreign working directory. The verifier confirmed the exact
architecture, self-contained Mach-O linkage, strict signature, bundled helper,
immutable resources, secret-free import smoke, and zero unexpected HOME writes.

Safe Computer Use validation opened the real standalone AppKit surface and
performed only non-mutating actions:

- opened and cancelled **Recording Core...**;
- verified the standard native form and restart-aware local settings;
- opened and cancelled the explicit legacy `.env` file picker;
- confirmed no automatic source scan or import;
- ran **Check Setup & Dependencies** with an isolated empty HOME;
- observed Recording Core as degraded and every optional capability as
  unconfigured, with no provider, OAuth, migration, Keychain, or save action.

The official checkout app was restored after the isolated standalone smoke.

## Evidence still required

These checks cannot be claimed from the developer-host smoke:

- a dedicated clean macOS 15 standard user or reset VM with no Python, Xcode,
  Terminal workflow, account, prior Keychain item, or prior TCC grant;
- an offline first launch followed by an explicit approximately 30-second real
  Full Meeting recording, stop, local playback, and Finder reveal in under five
  minutes;
- microphone denial and retry, Screen Recording denial and grant/relaunch,
  Silent System Only behavior, quit/relaunch, keyboard navigation, and explicit
  VoiceOver labels;
- the same validation on a notarized Developer ID artifact;
- a two-version N to N+1 replacement fixture proving preferences, exact
  Keychain accounts/refs, OAuth status, meeting bytes, recovery state, prompt,
  logs, and the single LaunchAgent target remain intact with zero provider work;
- real Intel audio/TCC validation when Intel is a supported release artifact.

A real recording captures private microphone and system audio. Do not execute
that step without the user's explicit permission and a suitable non-sensitive
test source.

## Release evidence still required

The protected release workflow is versioned but intentionally unexecuted. It
still needs the owner-controlled `release` Environment and reviewer, Apple
Developer Team ID, Developer ID Application P12 and password, team App Store
Connect notary key/ID/issuer, a matching version tag, and successful dual-arch
notarization. Until then, no artifact is Gatekeeper-ready and no public release
claim is valid.
