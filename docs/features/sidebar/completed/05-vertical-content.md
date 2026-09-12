# Sidebar 05 — Vertical panel content

> Status: active · Owner: Felipe Fumero · Created 2026-09-05

## Context

Plan 02 produced an empty floating panel; plan 04 produced a view model
describing everything the menu shows. This plan renders that view model as the
**vertical** layout — the shape used when the panel floats free or snaps to
left-center or right-center.

The two `▸` submenus have no panel equivalent. They become **collapsible
sections**, which is the one genuine redesign in this feature rather than a port.

The recording timer and the audio-health warning live here now, since the menu
bar carries neither (plan 03).

**Outcome:** a vertical `NSView` tree that renders a `SidebarViewModel` and
rebuilds cheaply when state changes.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Layout | Absolute frames via `NSMakeRect`, laid out top-down by a small cursor helper | Matches every existing window in this codebase (`ui/prompt_window.py`, `ui/configuration_forms.py`). Introducing Auto Layout here would be a second, inconsistent idiom. |
| Rebuild strategy | Tear down and rebuild the content view on state change | Exactly what `rebuild_menu()` does today, at the same 1 s tick. Simple, and the view count is small. Optimize only if it measurably stutters. |
| Timer updates | Update the recording label **in place**, not a full rebuild | It ticks every second. A full teardown at 1 Hz is wasteful and would collapse open sections. |
| Collapsible sections | Disclosure triangle + persisted open/closed per section | `▸ Configuration` and `▸ Debugging` have no menu equivalent in a panel. Persist to `NSUserDefaults` alongside the panel frame. |
| Default state | Recent / Pending open; Configuration / Diagnostics collapsed | Matches attention: live work is visible, settings are one click away. |
| Panel height | Content-driven, clamped to 80% of `visibleFrame.height`, scrolls beyond | Pending tasks and recovered recordings are unbounded lists. |
| Scrolling | `NSScrollView` around the section stack | Standard, gets elastic scrolling and correct trackpad behavior free. |
| Configuration/Diagnostics | Rows that **open the existing windows** | Those already exist as real `NSWindow`s. The panel is a launcher; it does not re-implement them. |
| Fonts and colors | System font, semantic `NSColor` (`labelColor`, `secondaryLabelColor`, `controlAccentColor`) | `PRODUCT.md`: native typography, correct in light and dark, never color alone for state. |

## Out of scope

- The horizontal layout for top/bottom snaps — plan 06.
- The cutover that retires the dropdown menu — plan 07.
- Any change to the windows the Configuration rows open.

## Files to create

```
src/meeting_memory/ui/sidebar_widgets.py       # row/section/label/button primitives
src/meeting_memory/ui/sidebar_sections.py      # collapsible section container + state
src/meeting_memory/ui/sidebar_vertical.py      # the vertical layout builder
tests/test_sidebar_vertical.py
```

Each is kept under the 300-line cap; splitting by role rather than by size keeps
plan 06 able to reuse `sidebar_widgets.py` wholesale.

### Layout — vertical (240 pt wide)

```
┌─────────────────────────────┐
│ ⠿  Meeting Memory        ✕  │  drag handle (plan 02) + close
├─────────────────────────────┤
│  ▶  Start Recording         │  or  ■ Stop Recording · 12:34
│  ⚠︎  Microphone silent 30s   │  only when audio_warning
├─────────────────────────────┤
│  Audio Mode                 │
│  ✓ Full Meeting             │
│    Silent System Only       │
├─────────────────────────────┤
│  ▾ Recent Meetings          │
│    2026-09-05 14:00 · …     │
│    Open Meetings Folder     │
├─────────────────────────────┤
│  ▾ Pending Meeting Tasks (2)│
│    … · Review speakers      │
├─────────────────────────────┤
│  ▾ Interrupted Recordings(1)│  hidden entirely when empty
├─────────────────────────────┤
│  ▸ Configuration            │
│  ▸ Diagnostics              │
├─────────────────────────────┤
│  Quit                       │
└─────────────────────────────┘
```

### `sidebar_widgets.py` — surface

```python
ROW_HEIGHT = 26.0
SECTION_HEADER_HEIGHT = 24.0
PANEL_WIDTH = 240.0

def row(view: RowView, y: float, width: float) -> NSView: ...
    # disabled rows -> secondaryLabelColor, no click target, tooltip preserved
def section_header(title: str, expanded: bool, y: float, on_toggle) -> NSView: ...
def separator(y: float, width: float) -> NSView: ...
def recording_row(view: RecordingView, y: float, width: float, on_click) -> NSView: ...
    # exposes .update(RecordingView) for the 1 Hz in-place tick
```

### Key gotchas

1. **Tooltips must survive.** `ui/submenus.py` sets a tooltip on nearly every
   item, including the disabled readiness lines. With no menu, tooltips are the
   only place that guidance lives. Call `setToolTip_` on every row view.
2. **Disabled rows are a real state.** Today `_menu_item` with `callback=None`
   renders a greyed, unclickable row (readiness lines, section headers, "No
   meetings yet", and Notes Customization before setup completes). Reproduce it
   — do not silently make everything clickable.
3. **Never color alone.** `PRODUCT.md` is explicit. The audio warning needs its
   `⚠︎` glyph and text, not just red.
4. **In-place timer updates must not collapse sections.** This is why
   `recording_row` exposes `.update()` rather than being rebuilt.
5. **The panel cannot take key focus** (plan 02, gotcha 3). No text fields, no
   editable rows. The recording-title prompt stays the existing modal
   (`ui/title_prompt.py`), raised via `ui/modal_focus.py`.
6. **Retain every view in Python.** Same pyobjc lifetime trap as plan 02.
7. **Clicking a Configuration row opens a real window** that *does* activate the
   app. That is correct and expected — only the panel is non-activating.
8. **Empty vs hidden differ.** Pending shows a `(0)` header; Interrupted
   disappears entirely. Plan 04 encodes this; honor it.

## Files to modify

| File | Change |
|---|---|
| `src/meeting_memory/ui/tray.py` | Behind the plan-03 flag: build the vertical content and hand it to `SidebarPanel.set_content_view`; on each drain tick, update the recording row in place and rebuild on state change. |
| `tests/test_structure.py` | Register the three new `ui/` modules. |

## Tests — `tests/test_sidebar_vertical.py`

Using the fake-AppKit approach from plan 02:

- A full view model renders the expected row labels in the expected order.
- Row labels match `ui/menu.py` helpers exactly (shared with the menu).
- Disabled rows carry no action and keep their tooltip.
- Every row has a non-empty tooltip.
- Empty recent renders "No meetings yet" and nothing clickable.
- Empty recovered renders **no header at all**.
- Pending with zero tasks renders a `(0)` header.
- `audio_warning` adds the warning row; clearing it removes the row.
- `recording_row.update()` changes the label without rebuilding the tree
  (assert section containers are the same objects).
- Section collapse state round-trips through fake `NSUserDefaults`.
- Clicking a row invokes the view model's action exactly once.

## Verification

> This is the plan where the feature becomes real and where the demo harness earns
> its keep. See [`VERIFICATION.md`](VERIFICATION.md) §2 — extend the harness built
> in plan 02 to render this layout, and work against it rather than launching the
> full app.

1. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_sidebar_vertical.py -v`
2. `make check` green.
3. **Look at all five states, no app launch required:**
   ```bash
   for s in idle recording warning busy empty; do
     PYTHONPATH=src .venv/bin/python "$SCRATCHPAD/sidebar_demo.py" "$s"
   done
   ```
   `busy` and `empty` are the states that break layouts — overflowing rows and
   zero rows. Do not skip them.
4. **Capture ten shots** — those five states in **both light and dark**
   (`VERIFICATION.md` §3). These go into `docs/features/sidebar.md` at plan 07.
5. **Manual, flag on** (`MEETING_MEMORY_SIDEBAR=1 make run`):
   - every action reachable in today's menu is reachable in the panel
   - timer ticks in the panel once per second while recording
   - an audio-health warning appears and clears
   - sections collapse and stay collapsed across a toggle and a relaunch
   - light and dark mode both legible; VoiceOver reads each row
   - long meeting titles truncate rather than overflow
6. `make PYTHON=.venv/bin/python reload-macos-app`.

## Execution order

1. `sidebar_widgets.py` primitives first, with their tests.
2. `sidebar_sections.py` collapse container.
3. `sidebar_vertical.py` assembling the view model into the layout.
4. Extend `$SCRATCHPAD/sidebar_demo.py` to render this layout, then wire into
   `ui/tray.py` behind `sidebar_enabled()`.
5. `make check`, manual pass, `reload-macos-app`.
6. Open the PR.

> Depends on plan 02 (panel) and plan 04 (view model).

---

Once the plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
