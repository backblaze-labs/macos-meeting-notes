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

## Release boundary

Developer ID signing, hardened-runtime verification, notarization with
`notarytool`, stapling, final archive checksums, and GitHub Release publication
belong to the protected release workflow. They require owner-controlled Apple
credentials and approval. Until those credentials and clean-user evidence are
available, the project can claim only a reproducible ad-hoc standalone build.
