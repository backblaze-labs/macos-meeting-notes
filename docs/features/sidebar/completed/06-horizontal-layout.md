# Sidebar 06 — Horizontal layout and reorientation on snap

> Status: complete (2026-09-05) · Owner: Felipe Fumero · Created 2026-09-05

## Context

When the panel snaps to **top-center or bottom-center**, it becomes a horizontal
strip; left-center and right-center keep the vertical layout from plan 05. Plan
01 already derives the orientation from the anchor and plan 02 already fires
`on_anchor_changed` — this plan supplies the second layout and the swap.

A horizontal strip cannot show everything the vertical panel shows: a stack of
sections is a vertical idea. So the horizontal form is a **compact control bar**
— the live controls inline, everything else behind a single overflow button that
opens the vertical content as a popover.

**Outcome:** `ui/sidebar_horizontal.py` plus orientation switching wired through
`ui/tray.py`, reusing every primitive from `sidebar_widgets.py`.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Horizontal contents | Record control, timer, warning, audio mode, pending count badge, overflow `⋯` | These are the things worth seeing at a glance. Section stacks do not survive rotation. |
| Everything else | Behind `⋯`, opening the **vertical** section stack as an `NSPopover` | Reuses plan 05 wholesale instead of designing a second full layout. Halves the work and guarantees the two agree. |
| Default size | 620 × 132 pt | Wide enough for controls plus a truncated meeting title; short enough not to eat the screen edge. |
| Swap trigger | `on_anchor_changed` from plan 02 | Single source of truth; no orientation state of its own. |
| Swap cost | Full content rebuild | Happens only on a drag release across an orientation boundary. Not a hot path. |
| Popover behavior | `NSPopoverBehaviorTransient` | Dismisses on outside click, standard macOS. |
| Popover and focus | Popover **may** take focus; the panel still does not | Acceptable: the popover is an explicit, momentary interaction. |

## Out of scope

- Changing the vertical layout — plan 05 owns it.
- New actions. This is a re-arrangement of what plans 04/05 already expose.

## Files to create

```
src/meeting_memory/ui/sidebar_horizontal.py    # compact bar; <= 220 lines
tests/test_sidebar_horizontal.py
```

### Layout — horizontal (620 × 132 pt)

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⠿ │ ■ Stop Recording · 12:34 │ ⚠︎ Mic silent │ Full Meeting ▾ │ 2 │ ⋯ │
└──────────────────────────────────────────────────────────────────────┘
   drag   record control + timer   warning       audio mode      pending
                                   (conditional)                 badge  overflow
```

- The `⚠︎` segment is present only when `audio_warning` is set.
- The pending badge shows `SidebarViewModel.pending` row count; hidden at zero.
- `⋯` opens an `NSPopover` hosting the plan-05 vertical section stack.

### `sidebar_horizontal.py` — surface

```python
PANEL_WIDTH = 620.0
PANEL_HEIGHT = 132.0

def build_horizontal(view_model: SidebarViewModel, *, on_overflow) -> HorizontalViews: ...

@dataclass(frozen=True, slots=True)
class HorizontalViews:
    root: Any
    recording: Any        # same .update(RecordingView) contract as plan 05
    warning: Any
    pending_badge: Any
```

### Key gotchas

1. **Reuse `sidebar_widgets.py`.** Plan 05 deliberately split primitives out.
   Re-implementing rows here guarantees the two layouts drift.
2. **`recording_row` keeps the same `.update()` contract** so the 1 Hz tick in
   `ui/tray.py` does not need to know which orientation is showing.
3. **Resize before placing.** Plan 01 gotcha 2 and plan 02 gotcha 1 land here for
   real: on a vertical→horizontal swap, set 620×132 first, *then* ask
   `snapped_origin` for the origin.
4. **The audio-mode control is a popup, not a stack.** Two radio rows do not fit;
   use an `NSPopUpButton` reading the same `audio_modes` tuple, checkmark prefix
   stripped for display.
5. **Truncate, do not wrap.** `setLineBreakMode_(NSLineBreakByTruncatingTail)` on
   the recording label — a long calendar title must not push the overflow button
   off the bar.
6. **The popover anchors to the `⋯` button**, and must pick its edge from the
   anchor: bottom-snapped bar → popover opens upward (`NSMaxYEdge`), top-snapped
   → downward (`NSMinYEdge`). Getting this wrong opens it offscreen.
7. **A popover on a non-activating panel needs the panel ordered front first.**
   Verify during the manual pass; if it misbehaves, `orderFrontRegardless()`
   immediately before `showRelativeToRect_ofView_preferredEdge_`.
8. **Collapse state is shared** with the vertical layout — the popover shows the
   same sections, so it reads the same `NSUserDefaults` keys.

## Files to modify

| File | Change |
|---|---|
| `src/meeting_memory/ui/tray.py` | Subscribe to `on_anchor_changed`; rebuild content for the new orientation and call `set_content_view`. Keep the in-place timer update working across both. |
| `src/meeting_memory/ui/sidebar_panel.py` | Use `DEFAULT_HORIZONTAL` / `DEFAULT_VERTICAL` on orientation change, resizing before re-origin. |
| `tests/test_structure.py` | Register `"ui/sidebar_horizontal.py"`. |

## Tests — `tests/test_sidebar_horizontal.py`

- A full view model renders record control, audio-mode popup, and overflow.
- Warning segment appears only when `audio_warning`.
- Pending badge hidden at zero, shows the count otherwise.
- `recording.update()` changes the label in place, same contract as vertical.
- Overflow click invokes `on_overflow` once.
- Popover edge is `NSMaxYEdge` for `BOTTOM` and `NSMinYEdge` for `TOP`.
- Audio-mode popup selection invokes the same action as the vertical row.
- **Orientation swap** (in `tests/test_sidebar_panel.py`): a drag from left-center
  to top-center resizes to 620×132 *before* computing the origin, and fires
  `on_anchor_changed` exactly once.

## Verification

> Extend the demo harness ([`VERIFICATION.md`](VERIFICATION.md) §2) with a second
> argument so a state can be rendered in either orientation:
> `sidebar_demo.py recording horizontal`.

1. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_sidebar_horizontal.py tests/test_sidebar_panel.py -v`
2. `make check` green.
3. **Look at it, no app launch required:**
   ```bash
   PYTHONPATH=src .venv/bin/python "$SCRATCHPAD/sidebar_demo.py" busy horizontal
   ```
4. **Capture four shots** — bar at top and at bottom, overflow popover open in
   each (`VERIFICATION.md` §3).
5. **Manual** (`MEETING_MEMORY_SIDEBAR=1 make run`):
   - drag from right-center to top-center → bar reorients, sits flush under the
     menu bar on the built-in display (33 pt inset respected)
   - drag to bottom-center → popover opens **upward**
   - timer keeps ticking across a reorientation mid-recording
   - overflow popover shows the same sections with the same collapse state
   - audio-mode popup matches the vertical radio rows
6. `make PYTHON=.venv/bin/python reload-macos-app`.

## Implementation notes (partial — see status below)

- **`sidebar_panel.py` needed no changes.** Plan 02 already implemented
  resize-before-place on orientation swap (`_handle_drag_end` resizes to
  `DEFAULT_HORIZONTAL`/`DEFAULT_VERTICAL` before calling `snapped_origin`,
  and `_set_anchor` fires `on_anchor_changed` exactly once per anchor
  change, not on a re-drop). `tests/test_sidebar_panel.py` already covers
  both — `test_reorientation_resizes_before_computing_origin` and
  `test_on_anchor_changed_fires_once_not_on_redrop` — so this plan's own
  test item for that behavior needed no new test, either.
- **`build_horizontal`'s signature gained `appkit` and `on_toggle_recording`**
  beyond the plan's illustrative stub, matching the convention every other
  plan-05/06 module already uses (`appkit` first positional; the panel
  needs a way to start/stop recording just like the vertical layout's
  `recording_row`).
- **Reuse of `sidebar_widgets.py` is partial, not wholesale**, despite the
  plan's "Outcome" line. Every primitive there positions itself at a fixed
  `x=0` for vertical stacking, which does not fit a row of side-by-side
  segments — so each horizontal segment is its own view, positioned
  explicitly. What *is* reused directly: `_clickable_container` (the
  click-detection trick) and `_apply_warning_color` (the warning-color
  rule), so those two behaviors still can't drift between layouts. This is
  documented in the module's own docstring.
- **`recording.update()` also toggles the warning segment's visibility**,
  not just the label — `HorizontalViews.warning` is a separate segment
  from `HorizontalViews.recording` (unlike the vertical layout, where the
  warning is just a color change on the same label), so the single
  per-tick hook needs to touch both to keep `ui/tray.py`'s tick
  orientation-agnostic, per gotcha 2.

### Status: complete

Plan 05 landed first (its own `ui/tray.py` wiring — `SidebarWiring.rebuild()`
and `.tick()`), so the orientation-switch wiring below builds on the final
API rather than a moving target.

- `ui/sidebar_horizontal.py` (`build_horizontal`, `popover_edge_for`,
  `show_overflow_popover`) — 8 tests in `tests/test_sidebar_horizontal.py`.
- `sidebar_panel.py` needed no changes (see above) — confirmed by its
  existing tests.
- **`ui/sidebar_tray_wiring.py` extended, not `ui/tray.py`.** All of the
  orientation-switch logic lives in `SidebarWiring`:
  - `panel_factory(on_anchor_changed=self._handle_anchor_changed)` at
    construction — `SidebarPanel` already fires this on every real anchor
    change (plan 02).
  - `_handle_anchor_changed` compares `self.panel.orientation` against the
    orientation tracked from the last `rebuild()` and only re-rebuilds when
    it actually changed — an anchor change within the same orientation
    (e.g. LEFT → RIGHT) does nothing here, matching the "not a hot path"
    decision.
  - `rebuild()` branches on `self.panel.orientation`, calling
    `build_horizontal` (with `_show_overflow` bound as `on_overflow`) or
    the existing `build_vertical` path.
  - `_show_overflow` closes any previously-shown popover first (a section
    toggle inside it re-opens fresh rather than stacking), then builds a
    **fresh vertical stack** from the same `SectionState` and shows it via
    `show_overflow_popover`, anchored to `self.panel.anchor`.
  - `ui/tray.py` itself needed **zero changes** for any of this — it
    already just calls `self.sidebar.rebuild(view)`, and now that call
    transparently produces whichever orientation the panel is in.
  - `show_overflow_popover`'s `panel` parameter takes `SidebarPanel` itself
    (calling its public `.show()`), not the raw `NSPanel` — keeps
    `is_visible` bookkeeping correct; changed from the original draft,
    which called `orderFrontRegardless()` directly.
  - `HorizontalViews` gained an `overflow_button` field (not in the plan's
    original stub) so the wiring layer can hand it to
    `show_overflow_popover` without reaching into `root.subviews`.
  - Tests: `tests/test_sidebar_tray_wiring_orientation.py` (6 tests) —
    split from the existing `test_sidebar_tray_wiring.py` because
    exercising the horizontal path needs a richer fake AppKit
    (`NSPopUpButton`, `NSObject`, `NSViewController`, `NSPopover`) than that
    file's panel-focused fakes provide.

**Manual pass (2026-09-05) — three real bugs, none reachable by the unit
tests, all fixed:**

1. **The vertical panel had no grabbable strip.** The content view covered
   the drag view entirely, so nothing dragged. `sidebar_panel.py` now
   reserves `DRAG_HANDLE_HEIGHT` (14 pt) above the content and
   `sidebar_drag.py` draws a `⠿` grabber in it. The grabber label itself
   then swallowed the mouse-down at the exact spot that invites a drag
   (`hitTest_` at the strip's center returned `NSTextField`), so it is a
   Python `NSTextField` subclass whose `hitTest_` returns `None` — verified
   in-process: every point across the strip now resolves to `DragHandleView`.
2. **The production AppKit namespace lacked every symbol the horizontal
   layout uses** (`NSPopUpButton`, `NSPopover`, `NSViewController`,
   `NSObject`, `NSMaxYEdge`/`NSMinYEdge`, `NSPopoverBehaviorTransient`), so
   the first real reorientation raised `AttributeError`. The namespace moved
   to its own module, `ui/sidebar_appkit.py`, with the missing symbols and a
   note that this failure mode is runtime-only.
3. **pyobjc refuses ad-hoc attributes on a real `NSPopUpButton`**, so
   `popup._meeting_memory_target = target` raised and the audio-mode popup
   would have lost its action target. The popup is now a cached Python
   subclass, same pattern as `sidebar_widgets._clickable_view_class`.

Verified through the extended demo harness (`sidebar_demo.py busy top|bottom
--shot DIR`), which drives the real `SidebarPanel._handle_drag_end` →
`on_anchor_changed` → `SidebarWiring.rebuild` → `show_overflow_popover`
path: bar snaps flush under the menu bar at the top and opens its popover
downward; at the bottom it opens upward; the vertical panel shows the `⠿`
grabber. Four screenshots captured (VERIFICATION.md §3). The physical mouse
drag itself was not performed from the agent shell (no accessibility
access); its hit-testing was verified instead — see `docs/deferred-work.md`
(2026-09-05).

## Execution order

1. Build the compact bar from plan 05's primitives.
2. Add an orientation argument to `$SCRATCHPAD/sidebar_demo.py`.
3. Add the overflow popover hosting plan 05's section stack.
4. Wire `on_anchor_changed` in `ui/tray.py`.
5. Add the orientation-swap test to the panel suite.
6. `make check`, manual pass, `reload-macos-app`.
7. Open the PR.

> Depends on plans 02 and 05. This is the plan the owner added by choosing
> reorientation over vertical-only — it is optional in the sense that plans 00–05
> and 07 ship a working sidebar without it, snapping to all four edges in one shape.

---

Once the plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
