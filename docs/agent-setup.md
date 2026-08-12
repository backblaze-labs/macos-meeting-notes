# Setup Guide for Coding Agents

Use this guide when a user asks you to install Meeting Memory from
`https://github.com/backblaze-labs/macos-meeting-notes`.

## Safety Boundaries

- Read `AGENTS.md` and `README.md` before running commands.
- Backblaze B2 configuration is required; AssemblyAI, Google Calendar, and
  Anthropic are optional and must not be configured unless the user asks.
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

3. Guide the user to [create a Backblaze B2 account](https://www.backblaze.com/sign-up/cloud-storage),
   a dedicated private bucket, and a Read and Write application key restricted
   to that bucket. The user keeps the key ID and application key private.
4. Open the installed app:

   ```bash
   make PYTHON=.venv/bin/python open-macos-app
   ```

5. Ask the user to open **Configuration › Backup...**, select **Enabled
   (app-managed)**, enter the endpoint, region, bucket name, key ID, and
   application key, then save and quit the app. Wait for the user to confirm
   completion; do not request the entered values.
6. Reopen Meeting Memory and verify required local readiness:

   ```bash
   make doctor
   ```

   Recording Core and Backup must be usable. The check validates configuration
   locally and does not contact B2.
7. Guide the user through a short recording. Confirm the local meeting folder
   exists and ask the user to verify the matching private B2 objects. If the
   upload failed, use **Debugging › Retry Pending B2 Backups**.

## Completion Criteria

Do not declare setup complete until:

- Meeting Memory opens from `~/Applications/Meeting Memory.app`;
- `make doctor` succeeds with usable Recording Core and Backup;
- a short recording is committed locally; and
- the user confirms its objects reached the dedicated private B2 bucket.

For troubleshooting and optional integrations, follow
[`setup-tutorial.md`](setup-tutorial.md).
