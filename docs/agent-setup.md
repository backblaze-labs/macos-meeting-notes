# Setup Guide for Coding Agents

Use this guide when a user asks you to install Meeting Memory from
`https://github.com/backblaze-labs/macos-meeting-notes`.

## Safety Boundaries

- Read `AGENTS.md` and `README.md` before running commands.
- Backblaze B2 configuration is optional. Enable only when the user is authorized
  to upload meeting audio and transcripts to the destination bucket. Local transcription is the enabled
  default unless explicitly disabled. It requires native Apple Silicon macOS,
  Metal, and explicit model preparation; missing models do not block recording.
- AssemblyAI, Google Calendar, and Anthropic are optional. Do not configure an
  external integration without the user's request and its app disclosure.
  AssemblyAI needs explicit provider selection and `external-audio-v1` consent;
  an existing key or local failure never permits cloud fallback.
- Explain that Hugging Face receives weight-download requests without meeting
  content, B2 receives audio/transcripts, and enabled Anthropic speaker
  suggestions can send transcript context before the user reviews names.
  Do not describe the whole application as offline or entirely local.
- Never ask the user to paste credentials into chat, source files, command-line
  arguments, or shell history.
- Never inspect an existing `.env`, Keychain item, OAuth token, recording, or
  transcript unless the user explicitly asks you to diagnose that local data.
- The user must enter the B2 key ID and application key in Meeting Memory's
  native **Configuration › Backup...** form.

## Installation Workflow

1. Confirm the Mac meets the requirements in `README.md`. Help install missing
   public prerequisites, but do not change unrelated system configuration.
2. If needed, clone the repository, enter it, and run:

   ```bash
   make setup
   ```

3. Only if Backup is requested, guide the user to [create a Backblaze B2 account](https://www.backblaze.com/sign-up/cloud-storage),
   a dedicated private bucket, and a Read and Write application key restricted
   to that bucket. The user keeps the key ID and application key private.
4. Open the installed app:

   ```bash
   make PYTHON=.venv/bin/python open-macos-app
   ```

5. Only if Backup is requested, ask the user to open **Configuration › Backup...**, select **Enabled
   (app-managed)**, enter the endpoint, region, bucket name, key ID, and
   application key, then save and quit the app. Wait for the user to confirm
   completion; do not request the entered values.
6. Reopen Meeting Memory and verify required local readiness:

   ```bash
   make doctor
   ```

   Only Recording Core must be usable; Backup is non-blocking. The check validates configuration
   locally and does not contact B2, download weights, or load models.
7. Guide the user through a short recording. Confirm the local meeting folder
   exists. If Backup was requested, ask the user to verify the matching private
   B2 objects. If the upload failed, use **Debugging › Retry Pending B2 Backups**.
8. On compatible Apple Silicon, guide the user to **Configuration › Prepare
   Local Models...**. Preparation reuses validated cached weights and downloads
   only missing content; its panel supports progress, cancellation, and retry.
   Do not download at startup or infer approval for processing old recordings.
   After preparation, use **Debugging › Retry Pending or Failed Transcriptions**
   only when the user requests the displayed backlog action.
9. If the user requests AssemblyAI, use **Configuration › Transcription...**
   and its external-audio notice, then restart. Never infer selection or consent
   from `.env` keys or imports. `TRANSCRIPTION_PROVIDER` and
   `ASSEMBLYAI_CONSENT` accept only app preferences or actual process overrides.

## Completion Criteria

Do not declare setup complete until:

- Meeting Memory opens from `~/Applications/Meeting Memory.app`;
- `make doctor` succeeds with usable Recording Core;
- a short recording is committed locally; and
- if Backup was requested, the user confirms its objects reached the dedicated private B2 bucket.

For troubleshooting and optional integrations, follow
[`setup-tutorial.md`](setup-tutorial.md).
