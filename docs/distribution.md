# Standalone macOS Distribution

Meeting Memory uses a PyInstaller `onedir + windowed` app bundle. Each build is
native to one architecture: `arm64` or `x86_64`. The project intentionally does
not use `onefile` or claim a universal binary when its embedded Python extensions
contain only one architecture.

## Local ad-hoc build

Create a clean Python 3.11 environment, then install the locked distribution
set and build for the current machine:

```bash
python -m pip install -r requirements-distribution.lock
make PYTHON=python ARCH="$(uname -m)" build-distribution
make PYTHON=python ARCH="$(uname -m)" verify-distribution
```

The verifier checks:

- bundle ID, version, build number, minimum macOS version, and TCC usage copy;
- every Mach-O file has exactly the requested architecture;
- load commands contain no checkout, virtualenv, Homebrew, or other external
  developer-machine dependency;
- no `.env`, OAuth credentials, token, Swift source, or external symlink is in
  the artifact;
- the helper is executable and the app has a strict valid signature;
- `--version` and the secret-free `bundle-self-check` work after relocating the
  app to a temporary directory with a fresh HOME.

Ad-hoc output is validation-only. It is not Gatekeeper-ready and must never be
published as a release.

## Architecture builds

CI builds two separate validation artifacts:

| Runner | Artifact architecture |
| --- | --- |
| `macos-15` | `arm64` |
| `macos-15-intel` | `x86_64` |

The same spec, version, bundle identifier, resources, and verifier are used for
both. PyInstaller receives a native Python and native third-party extensions on
each runner rather than attempting to manufacture missing universal slices.
The distribution lock deliberately holds `cryptography==48.0.1`: version 49
[removed macOS x86_64 support](https://cryptography.io/en/stable/changelog/#v49-0-0).
Do not raise that pin while Meeting Memory publishes an Intel artifact.

## Release boundary

`.github/workflows/release.yml` is the only public-release path. It is manually
dispatched for an existing `v<APP_VERSION>` tag and both its build and publish
jobs use the protected GitHub Environment named `release`. Each architecture
imports the Developer ID certificate into an ephemeral keychain, signs with the
hardened runtime and secure timestamp, verifies the complete thin bundle,
submits it with `notarytool`, checks the accepted notarization log, staples and
reverifies it, then creates a final ZIP and SHA-256 file. Publication happens
only after both architectures complete.

The repository owner must create and protect the `release` Environment with a
required reviewer and configure these Environment secrets:

| Secret | Purpose |
| --- | --- |
| `APPLE_DEVELOPER_ID_P12_BASE64` | Base64-encoded Developer ID Application certificate and private key |
| `APPLE_DEVELOPER_ID_P12_PASSWORD` | P12 export password |
| `APPLE_SIGNING_IDENTITY` | Exact `Developer ID Application: ...` identity |
| `APPLE_TEAM_ID` | Stable Apple Developer Team ID |
| `APPLE_NOTARY_KEY_P8_BASE64` | Base64-encoded team App Store Connect API key |
| `APPLE_NOTARY_KEY_ID` | Notary API key ID |
| `APPLE_NOTARY_ISSUER_ID` | Notary API issuer ID |

The workflow contains no fallback to repository-level credentials, ad-hoc
publication, automatic tag release, or forbidden hardened-runtime exception.
It does not create or modify the Environment itself. Until owner approval,
Apple credentials, successful notarization, and clean-user evidence are all
available, the project can claim only a reproducible ad-hoc standalone build.

Sanitized completed and pending validation evidence is tracked in
[standalone-validation-evidence.md](standalone-validation-evidence.md).

## Upgrades

An upgrade replaces only the existing `Meeting Memory.app`; it never moves or
stores mutable state inside the signed bundle. Quit the app, replace the one
installed copy in place, then reopen it. Do not keep old and new copies under
different names because LaunchServices and TCC may select the wrong bundle.

The stable bundle ID, Application Support path, generic secret service, Google
OAuth service/account, LaunchAgent label, meeting root, recovery state, prompt,
and log paths are versioned compatibility boundaries. An upgrade must not
redisplay, export, rotate, delete, or migrate their contents automatically, and
must not schedule historical provider work. A checkout `.env` is not installed
state; use the explicit in-app import before replacing the checkout wrapper.

Moving from an ad-hoc wrapper to Developer ID, or changing the signing team,
may cause a one-time macOS permission prompt even when the bundle ID is stable.
The release must document that OS-owned transition instead of deleting TCC
state or installing a second app copy.
