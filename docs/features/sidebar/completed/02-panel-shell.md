# Sidebar 02 — Floating panel shell: drag, snap, persist

> Status: active · Owner: Felipe Fumero · Created 2026-09-05

> **REVERSED on 2026-09-05:** the `setSharingType_(NSWindowSharingNone)`
> decision below (screen-share/screenshot hiding) was **removed** on
> request — the panel now appears in shots and shares like a normal
> window. See the removal marker in `src/meeting_memory/ui/sidebar_panel.py`
> `_build_panel` and the guard test
> `test_sharing_type_is_not_forced_and_defaults_to_visible_to_capture` in
> `tests/test_sidebar_panel.py`. Plan 00 question 7's finding still holds
> (the flag *does* work on this macOS), it's just no longer applied.

## Context

With snap math available from plan 01, this plan builds the window itself: a
borderless, non-activating `NSPanel` that floats above meeting apps, can be
dragged anywhere, animates flush to an edge when released near one, and
remembers where it was across launches.

It carries **no content** — a placeholder view only. Content lands in plans 05
and 06. Keeping them apart means the window mechanics can be exercised and fixed
without dragging the whole menu port along.

**Outcome:** `ui/sidebar_panel.py` — a `SidebarPanel` class exposing
`show()` / `hide()` / `toggle()` / `is_visible` and an `on_anchor_changed`
callback that plans 05/06 use to swap layouts.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Window class | `NSPanel`, `Borderless \| NonactivatingPanel` | Non-activating is the whole point: the user keeps typing in Zoom while the sidebar is up. |
| Level | `NSFloatingWindowLevel` | Above normal windows, below system UI. Do not use `NSStatusWindowLevel` — it would sit over menus and alerts. |
| Spaces | `CanJoinAllSpaces \| FullScreenAuxiliary` | Follows the user into a full-screen meeting, which is where it is needed most. |
| Show call | `orderFrontRegardless()` | `makeKeyAndOrderFront_` would activate the app and trip the Dock-hiding hook in `ui/macos.py:33`. |
| Dragging | Custom `mouseDown`/`mouseDragged`/`mouseUp` on a drag-handle view | `setMovableByWindowBackground_(True)` is one line but gives **no mouse-up signal**, and we must snap on release. Custom tracking is the only way to know a drag ended. |
| Snap feedback | `NSAnimationContext`, 0.18 s ease-out | Fast enough not to feel laggy, slow enough to read as magnetic. Honor `NSWorkspace.accessibilityDisplayShouldReduceMotion` per `PRODUCT.md` and jump instantly when set. |
| Position persistence | `setFrameAutosaveName_("MeetingMemorySidebar")` | Window chrome is not app configuration. Keeps this out of the Phase 4 preference allowlist, its schema, and its CAS machinery entirely. |
| Anchor persistence | `NSUserDefaults`, one string key, alongside the frame | Same reasoning. The anchor is needed at launch to pick the initial orientation. |
| Screen changes | Observe `NSApplicationDidChangeScreenParametersNotification` → re-clamp | Without this, unplugging a display strands the panel at coordinates that no longer exist. This is a guaranteed bug otherwise. |
| Screen-share visibility | `setSharingType_(NSWindowSharingNone)` **if plan 00 question 7 confirms it works** | A panel reading "■ Stop Recording · 12:34" must not appear over your slides when you share your screen in the meeting you are recording. If it does not work, note the limitation in `docs/deferred-work.md` rather than shipping silently. |
| Background | `NSVisualEffectView`, `.hudWindow` material, `behindWindow` blending | Native vibrancy, correct in light and dark, no custom color work. |
| Corner radius | Rounded on the free-floating side(s) only | A flush-snapped edge with rounded corners reads as broken. Nice-to-have; drop it if it costs more than an hour. |

## Out of scope

- The status-item click that calls `toggle()` — plan 03.
- Any real content, rows, or sections — plans 05 and 06.
- Auto-show on record start — plan 07.

## Files to create

```
src/meeting_memory/ui/sidebar_flag.py        # MEETING_MEMORY_SIDEBAR; see VERIFICATION.md §1
src/meeting_memory/ui/sidebar_panel.py       # the NSPanel + lifecycle; <= 300 lines
src/meeting_memory/ui/sidebar_drag.py        # drag-handle NSView subclass + tracking
tests/test_sidebar_panel.py                  # fake-AppKit tests, see below
```

### `sidebar_panel.py` — surface

```python
DEFAULT_VERTICAL = (240.0, 460.0)
DEFAULT_HORIZONTAL = (620.0, 132.0)
AUTOSAVE_NAME = "MeetingMemorySidebar"
ANCHOR_DEFAULTS_KEY = "MeetingMemorySidebarAnchor"

class SidebarPanel:
    def __init__(self, *, appkit=None, on_anchor_changed=None): ...
        # `appkit` injected for tests; None -> real `import AppKit`

    @property
    def is_visible(self) -> bool: ...
    @property
    def anchor(self) -> SnapAnchor: ...
    @property
    def orientation(self) -> Orientation: ...

    def show(self) -> None: ...      # orderFrontRegardless
    def hide(self) -> None: ...      # orderOut_
    def toggle(self) -> bool: ...    # returns the new visibility
    def set_content_view(self, view) -> None: ...   # plans 05/06 call this

    def _handle_drag_end(self) -> None:
        """Called by the drag view on mouseUp.
        1. read current frame + all screens
        2. resolve_drop(...) from sidebar_geometry
        3. if orientation changed: resize FIRST, then re-resolve the origin
        4. animate to the new origin
        5. persist anchor, fire on_anchor_changed
        """

    def _handle_screen_change(self, notification) -> None:
        """clamp_to_visible, then re-snap if still anchored."""
```

### Key gotchas

1. **Resize before placing on reorientation.** `snapped_origin` centers the rect
   it is handed. Swap the size first, then compute the origin, or a
   vertical-sized panel gets centered as if still vertical while drawn
   horizontal. Plan 01's docstring flags this; honor it here.
2. **`orderFrontRegardless`, not `makeKeyAndOrderFront_`.** The latter activates
   the app, fires `applicationDidBecomeActive_`, and trips the Dock-hiding patch
   in `ui/macos.py` on every single show.
3. **A borderless window returns `False` from `canBecomeKeyWindow` by default.**
   That is what we want — do **not** override it. It is why the panel cannot host
   text entry, which is fine: the recording-title prompt stays a modal
   (`ui/title_prompt.py`).
4. **Retain the panel and the drag view in Python.** pyobjc will not keep them
   alive for you; a garbage-collected panel vanishes mid-session. Hold strong
   refs on the owning object, the same way `ui/macos.py` retains `_UN_DELEGATE`.
5. **Remove the notification observer on teardown**, or a dealloc'd observer
   crashes the process at quit.
6. **`setFrameAutosaveName_` must be set after the frame is first applied**, and
   it silently no-ops if another window already claimed the name.
7. **Reduced motion.** `PRODUCT.md` commits to honoring it. Check it once per
   snap, not once at init — users change it live.
8. **Sharing type is set once, at construction.** Read plan 00's question 7
   finding first. If `NSWindowSharingNone` excludes the panel from capture, set
   it — and remember it also excludes the panel from `screencapture`, so the
   feature-doc shots in `VERIFICATION.md` §3 must be taken with it temporarily
   off. Add a test asserting the sharing type is applied, so a later refactor
   cannot silently drop it and leak the panel into users' screen shares.

## Files to modify

| File | Change |
|---|---|
| `tests/test_structure.py` | Add `"ui/sidebar_panel.py"`, `"ui/sidebar_drag.py"`, and `"ui/sidebar_flag.py"` to `REQUIRED_SOURCE_FILES`. |

## Tests — `tests/test_sidebar_panel.py`

Real AppKit cannot run in CI, so inject a fake module the way `tray_fakes.py`
already fakes rumps for the tray tests. Follow that file's conventions.

- `show`/`hide`/`toggle` drive visibility and return the right value.
- `show` calls `orderFrontRegardless`, **never** `makeKeyAndOrderFront_` — assert
  the second was not called. This is gotcha 2 and it is worth a dedicated test.
- Drag end at each of the four edges produces the right anchor, origin, and
  orientation, delegating to plan 01's functions.
- Reorientation resizes **before** computing the origin (assert call order).
- Drag end in open space leaves the panel where it was, anchor `FREE`.
- Screen-parameters notification with a shrunken screen re-clamps the frame.
- Reduced-motion set → no animation context is opened, frame set directly.
- `on_anchor_changed` fires exactly once per anchor change and not on re-drops
  onto the same anchor.
- Sharing type is set to `NSWindowSharingNone` at construction (guards against a
  refactor silently leaking the panel into screen shares).
- Anchor round-trips through the fake `NSUserDefaults`.

## Verification

> Read [`VERIFICATION.md`](VERIFICATION.md) first. This plan **creates two things
> every later plan depends on**: the `MEETING_MEMORY_SIDEBAR` flag module (§1) and
> the standalone demo harness (§2). Build the harness's five fake states here even
> though this plan renders only a placeholder — plans 05 and 06 need somewhere to
> render on day one.

1. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_sidebar_panel.py -v`
2. `make check` green.
3. **Look at it, without launching the app:**
   ```bash
   PYTHONPATH=src .venv/bin/python "$SCRATCHPAD/sidebar_demo.py" idle
   ```
4. **Capture the record** — panel at each of the four anchors plus free-floating:
   ```bash
   screencapture -o -x "$SCRATCHPAD/sidebar-shots/02-snap-left.png"
   ```
5. **Manual, on a real screen** (cannot be automated):
   - panel floats over a full-screen Zoom window and follows across Spaces
   - typing in another app is unaffected while it is visible
   - drag to each of the four edges snaps flush and reorients on top/bottom
   - quit and relaunch restores position and anchor
   - unplug the external display while snapped to it → panel returns onscreen
   - **screen-share check:** start a real screen share and confirm the panel is
     not visible to the other side (per plan 00 question 7)

## Execution order

1. Confirm plan 00's findings — especially that the panel shows without activating.
2. Write `sidebar_flag.py` (see `VERIFICATION.md` §1), then `sidebar_drag.py`,
   then `sidebar_panel.py`.
3. Register both in `tests/test_structure.py`.
4. Write the fake-AppKit tests.
5. `make check`, then the manual pass above.
6. `make PYTHON=.venv/bin/python reload-macos-app` per `AGENTS.md`, since app
   behavior changed.
7. Open the PR.

> Depends on plan 01 (geometry) and plan 00's findings.

---

Once the plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
