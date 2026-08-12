# Publishing Checklist

Use this checklist before pushing the **macos-meeting-notes** repository for the
Meeting Memory macOS app to GitHub.

## Files That Must Stay Local

Do not commit:

- `.env`
- `credentials.json` or any `client_secret*.json`
- OAuth token files
- API keys, private keys, certificates, or `.pem` files
- Local recordings, transcripts, or meeting folders
- `.venv`, caches, coverage output, and generated build artifacts

The repository `.gitignore` blocks these by default.

## Local Audit Commands

Check tracked files:

```bash
git ls-files
```

Check ignored sensitive files are still ignored:

```bash
git check-ignore -v .env credentials.json
```

Search tracked text for common secret and personal-data patterns:

```bash
git grep -n -E 'AIza|sk-|client_secret|refresh_token|private_key|BEGIN .*PRIVATE KEY'
git grep -n -E '@company\.com|/Users/|YOUR_NAME|YOUR_EMAIL'
```

If any real credential appears, remove it, rotate it with the provider, and do
not push until history is cleaned.

Check whether sensitive filenames were ever committed:

```bash
git log --all -- .env credentials.json token.json
```

If a real secret was committed in the past, assume it is compromised. Rotate the
secret and rewrite history before publishing.

Run a dedicated secret scanner against both the current snapshot and every
reachable Git ref:

```bash
gitleaks dir . --redact
gitleaks git --redact --log-opts='--all'
```

Review identity metadata and remote-only refs before making a formerly private
repository public:

```bash
git log --all --format='%an <%ae>' | sort -u
git ls-remote --refs origin
```

Git commit authors, pull-request refs, Actions artifacts, issues, comments,
releases, and deployment records may expose information even when the current
working tree is clean. Audit those GitHub surfaces separately. Rewriting only
the default branch is not sufficient when old refs or hosted artifacts remain
reachable.

When preserving private history matters, the safest publication pattern is a
new public repository created from one reviewed root commit. Keep the original
repository private as the history archive and do not copy its pull-request refs,
Actions artifacts, issues, or releases into the public repository.

## Publish to GitHub

Create an empty repository named `macos-meeting-notes` on GitHub, then connect
this local repo:

```bash
git remote add origin git@github.com:<owner>/macos-meeting-notes.git
git push -u origin <branch>
```

Replace `<owner>` and `<branch>` with your GitHub owner and current branch. Run
`git branch --show-current` if you are unsure which branch you are pushing.

Suggested repository description:

```text
Local-first macOS app for recording meetings, generating speaker-labeled notes, and backing them up to Backblaze B2.
```

Suggested repository topics:

```text
macos, meeting-notes, meeting-transcripts, transcription, speaker-diarization,
ai-notes, local-first, menu-bar-app, google-calendar, backblaze-b2, python
```

## After Publishing

- Confirm the GitHub file browser does not show `.env`, credentials, tokens, or
  local meeting data.
- Confirm the README links work.
- Confirm the setup tutorial is enough for a fresh clone.
- Confirm standalone artifacts contain `THIRD_PARTY_NOTICES.md`,
  `FFMPEG-COPYING.LGPLv2.1`, `FFMPEG_SOURCE_OFFER.md`, and the exact
  `ffmpeg-8.1.2.tar.xz` source, and that their encoder checksum/build recipe
  matches the committed source.
- Keep provider keys scoped to the minimum required permissions.
