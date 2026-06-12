# Google Calendar Auth

`meeting-memory` watches Google Calendar for Google Meet and Zoom links. It uses
OAuth with the read-only Calendar scope:

```text
https://www.googleapis.com/auth/calendar.readonly
```

Tokens are stored in the macOS Keychain through `keyring`, not in `.env` or a
plain-text token file.

Reference:

- Google Calendar Python quickstart:
  https://developers.google.com/workspace/calendar/api/quickstart/python

The Google quickstart was last checked for this guide on 2026-06-11. At that
time, it documented enabling the Calendar API, configuring OAuth consent,
creating a Desktop app OAuth client, and saving the downloaded JSON as
`credentials.json`.

## Create OAuth Credentials

1. Open the Google Cloud console.
2. Create or choose a project.
3. Enable the Google Calendar API.
4. Configure the OAuth consent screen.
5. Create an OAuth client ID.
6. Select application type `Desktop app`.
7. Download the JSON credentials file.
8. Save it in the repo as `credentials.json`, or put it elsewhere and set:

```bash
GOOGLE_CALENDAR_CREDENTIALS_FILE=/absolute/path/to/credentials.json
```

`credentials.json` is ignored by git.

## Configure Calendar ID

For all accessible calendars, which is the default:

```bash
GOOGLE_CALENDAR_ID=all
```

For only the primary calendar:

```bash
GOOGLE_CALENDAR_ID=primary
```

For only one other calendar, use the calendar ID shown in Google Calendar
settings.

## Run Auth

With the virtualenv active:

```bash
meeting-memory auth
```

Expected behavior:

1. A browser opens.
2. Google asks you to grant Calendar read-only access.
3. The app stores the resulting token in Keychain.
4. The command prints:

```text
Google Calendar auth token saved to Keychain.
```

If auth fails, rerun with:

```bash
make doctor
```

Common fixes:

- Ensure `GOOGLE_CALENDAR_CREDENTIALS_FILE` points to the downloaded JSON.
- Ensure the OAuth client type is `Desktop app`.
- Ensure the Google Calendar API is enabled for the same project.
- Ensure the account you authorize has Calendar enabled.

## Calendar Detection

The app treats an event as a meeting when `description` or `location` contains:

- `meet.google.com`
- `zoom.us/j/`
- `zoom.us/s/`

Use [manual-validation.md](manual-validation.md) to verify detection with a test
event.
