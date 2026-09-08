# Feature: Sidebar

## Purpose

The runtime menu bar item is an icon-only toggle for a small floating,
draggable, edge-snapping panel with exactly three icon buttons: record/stop,
screenshot, and quit. Everything else the old dropdown showed — recent
meetings, the meetings folder, audio mode, configuration, diagnostics — is the
menu behind a right-click on the same icon (`ui/status_menu.py`). The menu bar
item itself carries no title, no timer, and no warning glyph. The setup tray
(before Recording Core is configured) keeps its plain dropdown menu and is
not affected.

## Interaction model

| Gesture | Result |
|---|---|
| Left-click the menu bar icon | Toggle the panel. It starts hidden on every launch. While recording the icon carries a small red dot (no timer), so a hidden panel never hides the fact that a recording is running. |
| Right-click the menu bar icon | The app menu: Show/Hide Sidebar, Recent Meetings, Open Meetings Folder, Configuration (audio mode, capability forms, notes customization, calendar auth, legacy import, hide-while-recording), Debugging (readiness, interrupted recordings, retries, diagnostics), Quit. |
| Click the record button | Start or stop recording. Idle: teal `record.circle`. Recording: red `stop.circle.fill` plus a small `mm:ss` timer; orange when the audio-health monitor is warning. |
| Click the camera button, or press **⌥⇧S** anywhere | Take a screenshot for the active recording (`docs/features/screenshots.md`). |
| Click the power button | Quit. |
| Start a recording (any source) | The panel is forced visible (auto-show). With **Hide sidebar while recording** on (Configuration submenu; stored in `NSUserDefaults`) it is hidden instead and kept hidden for the whole recording; only a click on the menu bar icon shows it, until the recording ends. Stopping never changes visibility. |
| Drag the panel by its `⠿` grip | Free-float, or snap when one of the panel's edges is released within 64 pt of the matching screen edge. A snapped panel is sticky: it stays on its edge unless dragged more than 160 pt clear of it. |

Every button has a tooltip; there are no words on the panel apart from the
timer digits.

### Anchors and reorientation

Four snap anchors: left-center, right-center, top-center, bottom-center.
Anywhere else the panel free-floats. Left/right show the **vertical** layout
(44 × 130 pt: the top `⠿` strip, then record, screenshot, quit stacked; the
timer slot adds 14 pt while recording). Top/bottom and free-floating show the
**horizontal** layout (134 × 44 pt: a transparent `⠿` grip area, then the three
buttons in a row; the timer adds 46 pt while recording). Snapping under the
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
- `SidebarRevealRequested` (`types/events.py`) — queued by
  `TrayController._recording_started`; the tray turns it into `panel.show()`.
- The 1 Hz tray timer — `SidebarWiring.tick` updates the record button's
  glyph, tint, tooltip, and timer in place; when the recording state flips
  between ticks it rebuilds so the timer slot resizes the panel.

## Outputs

- The panel window: a borderless, non-activating, floating `NSPanel` with a
  14 pt corner radius on the HUD vibrancy material, joining all Spaces and
  floating over full-screen apps.
- The rumps `App.menu`, detached from the status item and popped up on
  right-click. Button and menu actions call straight back into the same
  `TrayController` methods the dropdown used.

## Threading

Main thread only. Background workers never touch the panel: they emit typed
events into the queue and `RumpsTrayApp.drain_events` renders them. Auto-show
is the same — the recorder's start callback queues `SidebarRevealRequested`
rather than calling the panel.

## Dependencies and blast radius

`ui/sidebar_toggle.py` is the only module that reaches into rumps 0.4.0
internals (`rumps_app._nsapp.nsstatusitem`, `_app["_menu"]._menu`) to detach
the menu rumps attaches, arm the status item's button directly, and pop the
detached menu up on right-click. `rumps` is pinned to `0.4.0` in
`pyproject.toml` for that reason. If a rumps upgrade breaks the toggle, that
file is the only place to fix; on failure it logs and restores the rumps menu
so the app stays usable and quittable.

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
controls" — a dropdown needs no discovery. The mitigations: auto-show when a
recording starts so recording state is never hidden; the right-click menu
with Show/Hide Sidebar and Quit; tooltips on every button; recording and
warning state carried by glyph shape and tooltip text, not color alone; snap
animation honors the reduce-motion preference.

## Related Files

- `src/meeting_memory/ui/tray.py` — `refresh_sidebar()`, event routing
- `src/meeting_memory/ui/status_menu.py` — the right-click menu
- `src/meeting_memory/ui/sidebar_tray_wiring.py` — panel + toggle + content wiring, orientation switch
- `src/meeting_memory/ui/sidebar_toggle.py` — status item left/right click
- `src/meeting_memory/ui/sidebar_compact.py` — the three icon buttons in both orientations
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
- `tests/test_sidebar_toggle.py` — status item behavior and the restore path
- `tests/test_sidebar_compact.py`, `tests/test_sidebar_widgets.py` — the icon buttons
- `tests/test_status_menu.py` — the right-click menu
- `tests/test_sidebar_view_model.py` (label snapshot: every retired menu row is still rendered), `tests/test_sidebar_view_model_rows.py`
- `tests/test_sidebar_tray_wiring.py`, `tests/test_sidebar_autoshow.py`, `tests/test_sidebar_status_and_indicator.py`
- `tests/test_tray.py`, `tests/test_tray_notifications.py`, `tests/test_setup_readiness.py`
