# Feature: Sidebar

## Purpose

The runtime menu bar item is an icon-only toggle for a floating, draggable,
edge-snapping panel that replaces the old dropdown menu. Everything the menu
used to show — the recording control and timer, audio mode, recent meetings,
pending tasks, interrupted recordings, configuration, diagnostics, Quit — lives
in the panel. The menu bar item itself carries no title, no timer, and no
warning glyph. The setup tray (before Recording Core is configured) keeps its
plain dropdown menu and is not affected.

## Interaction model

| Gesture | Result |
|---|---|
| Left-click the menu bar icon | Toggle the panel. It starts hidden on every launch. While recording the icon carries a small red dot (no timer), so a hidden panel never hides the fact that a recording is running. |
| Right-click the menu bar icon | A one-item **Quit** menu — the safety hatch if the panel is ever unreachable. |
| Start a recording (any source) | The panel is forced visible (auto-show). With **Hide sidebar while recording** on (Configuration section; stored in `NSUserDefaults`) it is hidden instead and kept hidden for the whole recording, in either orientation; only a click on the menu bar icon shows it, until the recording ends. Stopping never changes visibility. |
| Drag the panel by its header (the `⠿` strip or the title bar) | Free-float, or snap when one of the panel's edges is released within 64 pt of the matching screen edge. A snapped panel is sticky: it stays on its edge unless dragged more than 160 pt clear of it. |
| Click `⋯` on the horizontal bar | A transient popover with the full vertical section stack. |
| Click **Record** on the pre-meeting notification | Starts recording and opens the meeting link in one click. |

### Anchors and reorientation

Four snap anchors: left-center, right-center, top-center, bottom-center.
Anywhere else the panel free-floats. Left/right show the **vertical** layout
(240 × content height, capped at 80% of the screen's visible height, scrolling
beyond that): a title bar, the recording row, a status row with the latest
lifecycle message once one exists ("Recording saved · … · processing queued",
"Transcript ready · … · review speakers" — clickable when it points at a
meeting), then collapsible sections. Top/bottom show the **horizontal** layout (620 × 56): a gradient brand
block with the `⠿` grip, record control with timer, an audio-warning segment
when set, the audio-mode popup, a teal pending-task pill, and the `⋯` overflow
button. The overflow
popover opens downward from a top-snapped bar and upward from a bottom-snapped
bar. Snapping under the menu bar respects the display's visible frame.

Position and anchor persist through `NSUserDefaults` (frame autosave name
`MeetingMemorySidebar`, anchor key `MeetingMemorySidebarAnchor`) — not the
Phase 4 preference store. Whether the panel was visible is **not** persisted.
Section collapse state is shared between the vertical layout and the overflow
popover.

### What lives in the panel vs. the windows it launches

The panel is a launcher, not a workspace. Rows either act immediately
(start/stop, open a folder, retry, run diagnostics) or open the existing
windows: capability configuration, notes customization, speaker review, the
title prompt. Those windows are unchanged.

## Inputs

- `SidebarViewModel` — one immutable snapshot built by
  `ui/sidebar_view_model.py:build_view_model` from `TrayController`, the
  readiness report, the audio-mode state, and the configuration/debugging
  actions. `ui/tray.py:refresh_sidebar` rebuilds it after every state change.
- `SidebarRevealRequested` (`types/events.py`) — queued by
  `TrayController._recording_started`; the tray turns it into `panel.show()`.
- The 1 Hz tray timer — `SidebarWiring.tick` updates the recording row's
  label in place, without a rebuild, in either orientation.

## Outputs

- The panel window: a borderless, non-activating, floating `NSPanel` that
  joins all Spaces, floats over full-screen apps, and is excluded from screen
  capture and sharing (`NSWindowSharingNone`).
- Row actions call straight back into the same `TrayController` methods the
  menu used.

## Threading

Main thread only. Background workers never touch the panel: they emit typed
events into the queue and `RumpsTrayApp.drain_events` renders them. Auto-show
is the same — the recorder's start callback queues `SidebarRevealRequested`
rather than calling the panel.

## Dependencies and blast radius

`ui/sidebar_toggle.py` is the only module that reaches into rumps 0.4.0
internals (`rumps_app._nsapp.nsstatusitem`) to detach the menu rumps attaches
and arm the status item's button directly. `rumps` is pinned to `0.4.0` in
`pyproject.toml` for that reason. If a rumps upgrade breaks the toggle, that
file is the only place to fix; on failure it logs and restores the rumps menu
so the app stays quittable.

Every sidebar module takes an injected AppKit namespace. In production that
is `ui/sidebar_appkit.py:real_appkit`; tests inject fakes. Any AppKit symbol a
sidebar module uses must be listed there — a missing one surfaces only at
runtime on the path that touches it.

## Look

The header block (drag strip plus title bar) is the app icon's navy→teal
gradient, drawn by `ui/sidebar_theme.py`; section headings, the idle record
control, and the `⠿`/`⋯` glyphs use the teal as an accent. Body rows stay
system-colored on the vibrancy material so light/dark mode and accessibility
settings keep working; the panel has 12 pt rounded corners.

## Accessibility

A floating panel is a departure from `PRODUCT.md`'s "prefer familiar macOS
controls" — a dropdown needs no discovery. The mitigations: auto-show when a
recording starts so recording state is never hidden; the right-click Quit
hatch; native `NSTextField`/`NSPopUpButton` controls with system typography;
warning state carried by a `⚠︎` glyph and text, not color alone; snap animation
honors the reduce-motion preference.

## Related Files

- `src/meeting_memory/ui/tray.py` — `refresh_sidebar()`, event routing
- `src/meeting_memory/ui/sidebar_tray_wiring.py` — panel + toggle + content wiring, orientation switch, overflow popover
- `src/meeting_memory/ui/sidebar_toggle.py` — status item left/right click
- `src/meeting_memory/ui/sidebar_panel.py` — the `NSPanel` shell: show/hide, drag-to-snap, persistence
- `src/meeting_memory/ui/sidebar_drag.py` — drag tracking view and the `⠿` grabber
- `src/meeting_memory/ui/sidebar_geometry.py` — pure snap/orientation math
- `src/meeting_memory/ui/sidebar_view_model.py` — the render seam
- `src/meeting_memory/ui/sidebar_vertical.py`, `sidebar_widgets.py`, `sidebar_sections.py` — vertical layout
- `src/meeting_memory/ui/sidebar_horizontal.py` — horizontal bar and popover
- `src/meeting_memory/ui/sidebar_appkit.py` — the production AppKit namespace
- `src/meeting_memory/ui/sidebar_theme.py` — icon palette, fonts, gradient header
- `src/meeting_memory/ui/sidebar_prefs.py` — sidebar-only preferences (hide while recording)
- `src/meeting_memory/ui/audio_modes.py`, `menu.py`, `submenus.py` — shared labels/actions; `submenus.py` now serves only the setup tray
- Plans and findings: `docs/features/sidebar/completed/`

## Tests

- `tests/test_sidebar_geometry.py` — snap math
- `tests/test_sidebar_panel.py`, `tests/test_sidebar_drag.py` — panel shell, drag, grabber
- `tests/test_sidebar_toggle.py` — status item behavior and the restore path
- `tests/test_sidebar_view_model.py` (label snapshot: every retired menu row is still rendered), `tests/test_sidebar_view_model_rows.py`
- `tests/test_sidebar_vertical.py`, `tests/test_sidebar_widgets.py`, `tests/test_sidebar_sections.py`
- `tests/test_sidebar_horizontal.py`, `tests/test_sidebar_tray_wiring.py`, `tests/test_sidebar_tray_wiring_orientation.py`
- `tests/test_sidebar_autoshow.py` — auto-show via the event queue
- `tests/test_tray.py`, `tests/test_tray_notifications.py`, `tests/test_setup_readiness.py` — tray behavior now asserted against the view model
