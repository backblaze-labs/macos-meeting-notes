# Feature: Sidebar

## Purpose

A small floating, draggable, edge-snapping panel with exactly four icon
buttons: record/stop, screenshot, hide, and quit. It is a companion to the normal
app menu, not the entry point: clicking the menu bar icon with either button
opens the menu (`ui/status_menu.py`) with Start/Stop Recording first, then
Show/Hide Sidebar, recent meetings, the meetings folder, Configuration,
Debugging, and Quit. Calendar reveals the panel with its upcoming-meeting
prompt; it hides when that recording ends or when the user presses its hide
button. While recording the status bar shows a dot and the
live timer beside the icon. The setup tray (before Recording Core is
configured) keeps its plain dropdown menu and is not affected.

## Interaction model

| Gesture | Result |
|---|---|
| Click the menu bar icon (either button) | The app menu: Start/Stop Recording, Show/Hide Sidebar, Recent Meetings, Open Meetings Folder, Configuration (audio mode, capability forms, notes customization, calendar auth, legacy import, automatic Notes, hide-while-recording), Debugging (pending tasks, speaker corrections, readiness, interrupted recordings, retries, diagnostics), Quit. The panel starts hidden on every launch. |
| Status bar while recording | `● mm:ss` beside the icon (`⚠︎ mm:ss` on an audio warning), so a hidden panel never hides the fact that a recording is running. |
| Click the record button | Start or stop recording. Idle: teal `record.circle`. Recording: red `stop.circle.fill` plus a small `mm:ss` timer; orange when the audio-health monitor is warning. |
| Click the camera button, or press **⌥⇧S** anywhere | Take a screenshot for the active recording (`docs/features/screenshots.md`). |
| Click the eye-slash button | Hide the panel. The app menu can show it again. |
| Click the power button | Quit. |
| Calendar detects an upcoming meeting | The panel is shown with the meeting-start notification. With **Hide sidebar while recording** on (Configuration submenu; stored in `NSUserDefaults`) that auto-show is suppressed for the session. |
| Stop a recording | The panel hides after capture has actually stopped. Ad-hoc starts never auto-show it. |
| Drag the panel by its `⠿` grip | Free-float, or snap when one of the panel's edges is released within 64 pt of the matching screen edge. A snapped panel is sticky: it stays on its edge unless dragged more than 160 pt clear of it. |

Every button has a tooltip; there are no words on the panel apart from the
timer digits.

### Anchors and reorientation

Four snap anchors: left-center, right-center, top-center, bottom-center.
Anywhere else the panel free-floats. Left/right show the **vertical** layout
(44 × 166 pt: the top `⠿` strip, then record, screenshot, hide, quit stacked;
the timer slot adds 14 pt while recording). Top/bottom and free-floating show
the **horizontal** layout (170 × 44 pt: a transparent `⠿` grip area, then the
four buttons in a row; the timer adds 46 pt while recording). Snapping under the
menu bar respects the display's visible frame.

Position and anchor persist through `NSUserDefaults` (frame autosave name
`MeetingMemorySidebar`, anchor key `MeetingMemorySidebarAnchor`) — not the
Phase 4 preference store. Whether the panel was visible is **not** persisted.

## Inputs

- `SidebarViewModel` — one immutable snapshot built by
  `ui/sidebar_view_model.py:build_view_model` from `TrayController`, the
  readiness report, the audio-mode state, and the configuration/debugging
  actions. `ui/tray.py:refresh_sidebar` rebuilds the panel content and the
  status menu from it after every state change.
- `MeetingDetected` (`types/events.py`) — the tray turns Calendar's upcoming
  meeting event into `panel.show()` and the meeting-start notification.
- `SidebarHideRequested` (`types/events.py`) — queued after recorder shutdown;
  the tray turns it into `panel.hide()`.
- The 1 Hz tray timer — `SidebarWiring.tick` updates the record button's
  glyph, tint, tooltip, and timer in place; when the recording state flips
  between ticks it rebuilds so the timer slot resizes the panel.

## Outputs

- The panel window: a borderless, non-activating, floating `NSPanel` with a
  14 pt corner radius on the HUD vibrancy material, joining all Spaces and
  floating over full-screen apps.
- The rumps `App.menu`, attached to the status item as usual and opened by
  either mouse button. Button and menu actions call straight back into the
  same `TrayController` methods the dropdown used.

## Threading

Main thread only. Background workers never touch the panel: they emit typed
events into the queue and `RumpsTrayApp.drain_events` renders them. Calendar
detection reaches the tray through its typed event, while recorder shutdown
queues `SidebarHideRequested`; neither worker calls the panel.

## Dependencies and blast radius

No sidebar module reaches into rumps internals: the status item keeps the
menu rumps attaches, and `rumps` is required as `>=0.4` like before.

Every sidebar module takes an injected AppKit namespace. In production that
is `ui/sidebar_appkit.py:real_appkit`; tests inject fakes. Any AppKit symbol a
sidebar module uses must be listed there — a missing one surfaces only at
runtime on the path that touches it. The buttons are SF Symbols
(`NSImage.imageWithSystemSymbolName_…`); on an AppKit without them the
compact layout falls back to text glyphs.

## Look

The `⠿` grip (the top strip in the vertical layout, the left area in the
horizontal one) is transparent — a secondary-colored glyph on the same
surface, so nothing inside the panel reads as a band or border. The idle
record button uses the icon's teal (`ui/sidebar_theme.py`) as an accent. Buttons stay system-tinted
on the vibrancy material so light/dark mode and accessibility settings keep
working. The whole panel is a rounded pill: 14 pt corners, no title bar, no
text.

## Accessibility

A floating panel is a departure from `PRODUCT.md`'s "prefer familiar macOS
controls" — a dropdown needs no discovery. The mitigations: the ordinary menu
stays the entry point with Start Recording, Show/Hide Sidebar, and Quit;
Calendar-triggered show for an upcoming meeting, the status-bar timer, and
status-bar timer; tooltips on every button; recording and warning state
carried by glyph shape and tooltip text, not color alone; snap animation
honors the reduce-motion preference.

## Related Files

- `src/meeting_memory/ui/tray.py` — `refresh_sidebar()`, event routing
- `src/meeting_memory/ui/status_menu.py` — the app menu
- `src/meeting_memory/ui/sidebar_tray_wiring.py` — panel + content wiring, orientation switch
- `src/meeting_memory/ui/notes_mode.py` — the automatic Notes opt-in row and its confirmation
- `src/meeting_memory/ui/sidebar_compact.py` — the four icon buttons in both orientations
- `src/meeting_memory/ui/sidebar_panel.py` — the `NSPanel` shell: show/hide, drag-to-snap, persistence
- `src/meeting_memory/ui/sidebar_drag.py` — drag tracking view and the `⠿` grabber
- `src/meeting_memory/ui/sidebar_geometry.py` — pure snap/orientation math
- `src/meeting_memory/ui/sidebar_view_model.py` — the render seam
- `src/meeting_memory/ui/sidebar_widgets.py` — click-tracking view primitive
- `src/meeting_memory/ui/sidebar_appkit.py` — the production AppKit namespace
- `src/meeting_memory/ui/sidebar_theme.py` — icon palette, fonts, gradient header
- `src/meeting_memory/ui/sidebar_prefs.py` — sidebar-only preferences (hide while recording)
- `src/meeting_memory/ui/audio_modes.py`, `menu.py`, `submenus.py` — shared labels/actions; `submenus.py` serves only the setup tray
- Plans and findings: `docs/features/sidebar/completed/`

## Tests

- `tests/test_sidebar_geometry.py` — snap math
- `tests/test_sidebar_panel.py`, `tests/test_sidebar_drag.py` — panel shell, drag, grabber
- `tests/test_sidebar_compact.py`, `tests/test_sidebar_widgets.py` — the icon buttons
- `tests/test_status_menu.py` — the app menu
- `tests/test_notes_mode.py` — the automatic Notes opt-in
- `tests/test_sidebar_view_model.py` (label snapshot: every retired menu row is still rendered), `tests/test_sidebar_view_model_rows.py`
- `tests/test_sidebar_tray_wiring.py`, `tests/test_sidebar_autoshow.py`, `tests/test_sidebar_status_and_indicator.py`
- `tests/test_tray.py`, `tests/test_tray_notifications.py`, `tests/test_setup_readiness.py`
