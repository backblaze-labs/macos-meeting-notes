# Feature: Calendar Notifications

## Purpose

Detect upcoming Google Meet or Zoom events and prompt the user to start or stop
recording at the right time.

## Inputs

- `GOOGLE_CALENDAR_CREDENTIALS_FILE`
- `GOOGLE_CALENDAR_ID`
- `NOTIFY_MINUTES_BEFORE`
- `CALENDAR_POLL_INTERVAL`
- Google Calendar OAuth token stored in Keychain

## Outputs

- `MeetingDetected` events from the watcher
- Pre-meeting macOS notification with `Record`
- Meeting-end notification with `Stop` when a recording has an event end time
- Calendar-derived recording title

## Threading

Calendar polling runs in `CalendarWatcher` on a background thread. The watcher
emits typed events into the tray queue; `RumpsTrayApp` renders notifications on
the UI thread.

Google API connections prefer IPv4 before falling back to IPv6. This avoids
long watcher stalls on networks that advertise IPv6 DNS records but cannot
actually route IPv6 traffic. Repeated failures during one uninterrupted outage
are logged but produce only one user notification; a successful poll resets the
notification guard.

## Behavior Notes

- `GOOGLE_CALENDAR_ID=all` is the default and scans every non-deleted calendar
  accessible to the authenticated account.
- Set `GOOGLE_CALENDAR_ID=primary` or a specific calendar ID to narrow the
  watcher.
- Meeting detection checks event description, location, and native
  `hangoutLink` fields for Meet or Zoom URLs.
- Events where the authenticated account's self attendee response is
  `declined` are ignored and do not produce recording notifications.
- Dismissing `Record` does not start recording.
- Notification visibility can still be affected by macOS notification
  permissions and Focus settings.

## Related Files

- `src/meeting_memory/repo/calendar_client.py`
- `src/meeting_memory/service/calendar_watcher.py`
- `src/meeting_memory/service/recording_context.py`
- `src/meeting_memory/types/events.py`
- `src/meeting_memory/ui/tray.py`
- `src/meeting_memory/ui/controller.py`
- `src/meeting_memory/ui/notifications.py`

## Tests

- `tests/test_calendar_client.py`
- `tests/test_calendar_watcher.py`
- `tests/test_recording_context.py`
- `tests/test_tray_notifications.py`
- `tests/test_tray_recording_context.py`
