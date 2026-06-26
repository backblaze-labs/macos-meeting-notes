# Publishing Checklist

Use this checklist before pushing Meeting Memory to a public GitHub repository.

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

## Publish to GitHub

Create an empty repository on GitHub, then connect this local repo:

```bash
git remote add origin git@github.com:<owner>/meeting-memory.git
git push -u origin <branch>
```

Replace `<owner>` and `<branch>` with your GitHub owner and current branch. Run
`git branch --show-current` if you are unsure which branch you are pushing.

## After Publishing

- Confirm the GitHub file browser does not show `.env`, credentials, tokens, or
  local meeting data.
- Confirm the README links work.
- Confirm the setup tutorial is enough for a fresh clone.
- Keep provider keys scoped to the minimum required permissions.
