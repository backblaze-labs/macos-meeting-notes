# meeting-memory

`meeting-memory` is a planned macOS menu bar application for recording meetings,
transcribing them with diarization, summarizing them, saving portable markdown
files locally, and backing up meeting artifacts to Backblaze B2.

This repository is currently at Milestone 0: repository harness only. The code
contains the package skeleton, structural tests, docs control surface, and a
zero-dependency doctor preflight.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
make doctor
make check
```

`ffmpeg` is an external system dependency. It is checked by `make doctor`, not
installed by Python packaging.

## Cost Note

AssemblyAI transcription is estimated at about `$0.72` per hour at `$0.012` per
minute. Anthropic and B2 costs depend on account usage and retention choices.
