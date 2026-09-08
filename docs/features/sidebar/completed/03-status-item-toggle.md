# Sidebar 03 — Status item becomes a toggle button

> Status: active · Owner: Felipe Fumero · Created 2026-09-05

## Context

Today the menu bar item shows a title (`12:34`, `⚠︎ 12:34`) and opens an
`NSMenu` on click. The target design is a **dumb toggle**: an icon with no text,
whose left-click shows or hides the sidebar. The elapsed timer and the audio
health warning move into the panel (plans 05/06).

This is the most fragile plan in the set, because `rumps` 0.4.0 owns the status
item and attaches a menu to it at
`applicationDidFinishLaunching_` (`rumps/rumps.py:954`,
`self.nsstatusitem.setMenu_(mainmenu._menu)`). While a menu is attached, macOS
opens the menu on click and **never delivers the item's action**. We have to
detach it and install our own target/action.

A right-click fallback menu containing only **Quit** is kept deliberately: if the
panel ever fails to draw, the app would otherwise be unquittable except through
Activity Monitor.

**Outcome:** `ui/sidebar_toggle.py` — one small module that owns every piece of
rumps-internal access, so a future rumps upgrade breaks exactly one file.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Left-click | Toggle sidebar visibility | The owner's design. |
| Right-click | 1-item menu: **Quit** | Safety hatch. A different gesture, so it does not compromise the left-click toggle. |
| Menu bar title | Removed entirely — icon only | Owner's decision: timer and warning move to the sidebar. |
| Where the hack lives | One module, nothing else touches `_nsapp` | rumps internals are the single largest upgrade risk here. Contain them. |
| rumps version | **Pin it** in `pyproject.toml` | We depend on documented-by-accident behavior. An unpinned minor bump can silently break the toggle. |
| Fallback if `button()` is absent | Construct our own `NSStatusItem` and let rumps keep only the run loop | rumps 0.4.0 predates the `button()`-first API. Plan 00 question 5 settles which path we take. |
| Toggle state persistence | **Not** persisted — starts hidden each launch | The panel's *position* persists (plan 02); its visibility should not surprise the user at login. Plan 07's auto-show covers the case that matters. |

## Out of scope

- Auto-showing the panel when recording starts — plan 07.
- Removing `rebuild_menu()` and the dropdown — plan 07 does the cutover.
  **This plan leaves the existing menu code intact and unreferenced by the toggle**,
  so the two can coexist behind a flag.

## Files to create

```
src/meeting_memory/ui/sidebar_toggle.py      # all rumps-internal access; <= 120 lines
tests/test_sidebar_toggle.py
```

### `sidebar_toggle.py` — surface

```python
class SidebarToggle:
    """Owns the status item's click behavior. The ONLY module allowed to
    reach into rumps internals (`app._nsapp.nsstatusitem`)."""

    def __init__(self, rumps_app, panel, *, on_quit, appkit=None): ...

    def install(self) -> None:
        """1. detach the rumps menu:      nsstatusitem.setMenu_(None)
           2. clear the title:            nsstatusitem.setTitle_(None)
           3. target/action on button():  setTarget_(self._handler)
                                          setAction_("statusItemClicked:")
           4. sendActionOn_(LeftMouseUp | RightMouseUp)
           Every step wrapped: a failure logs and falls back to the menu
           rather than leaving an inert icon."""

    def _handle_click(self, sender) -> None:
        """Right-click (or ctrl-click) -> popUpMenu with a single Quit item.
           Left-click -> panel.toggle()."""
```

### Key gotchas

1. **`setMenu_(None)` is mandatory and must happen after rumps has launched.**
   Calling it in `__init__` runs before `applicationDidFinishLaunching_`
   re-attaches the menu. Install from `run()` or a first-timer-tick, not the
   constructor.
2. ~~**Detect right-click properly.** Read `NSApp.currentEvent().type()` and check
   for `NSEventTypeRightMouseUp`, plus `NSEventModifierFlagControl` on a left-up
   (ctrl-click is a right-click on macOS). Missing the modifier case is a common
   accessibility bug.~~
   **This does not work on Darwin 25.6.0 — see "Right-click detection findings"
   below.** The status-item button swallows the mouse-up, so the action always
   sees a synthesized left-mouse-up. Detect on mouse-*down* with a local event
   monitor instead.
3. **Right-click menus are shown with `popUpMenu`, then immediately detached.**
   Leaving the menu attached restores the old click-opens-menu behavior for
   left-clicks too.
4. **The action target must be a retained `NSObject` subclass.** A plain Python
   object will not do, and an unretained one is collected and crashes on click.
   Follow the `ModernNotificationDelegate` pattern in `ui/macos.py`.
5. **`quit_button=None` is already passed** to `rumps.App` in both
   `ui/tray.py:71` and `ui/setup_tray.py:56`, so rumps adds no Quit of its own.
   Our fallback menu is the only one.
6. **Never leave the icon inert.** Every failure path in `install()` must restore
   the rumps menu, so a broken toggle degrades to today's behavior instead of an
   unusable app.

## Files to modify

| File | Change |
|---|---|
| `tests/test_structure.py` | Add `"ui/sidebar_toggle.py"` to `REQUIRED_SOURCE_FILES`. |
| `pyproject.toml` | Pin rumps to the exact working version (currently `0.4.0`) with a comment pointing at this plan. We rely on its internals. |
| `src/meeting_memory/ui/tray.py` | Construct `SidebarToggle` and call `install()` from `run()`, behind an off-by-default flag. Do **not** yet remove `rebuild_menu()`, `_tray_title()`, or `update_tray_title()`. |

## Tests — `tests/test_sidebar_toggle.py`

Extend the existing fake-rumps helpers in `tests/tray_fakes.py` with a fake
status item recording `setMenu_`, `setTitle_`, `setTarget_`, `setAction_`, and
`sendActionOn_` calls.

- `install()` detaches the menu and clears the title.
- Left-click calls `panel.toggle()` exactly once.
- Right-click does **not** toggle; it pops up a menu whose single item is Quit.
- Ctrl+left-click behaves as right-click.
- Quit item invokes `on_quit`.
- `install()` failing at any step restores the rumps menu and logs (parametrize
  a raise at each step).
- `install()` is idempotent — calling twice does not double-install.

## Verification

1. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_sidebar_toggle.py -v`
2. `make check` green.
3. **Manual, flag on** (`MEETING_MEMORY_SIDEBAR=1 make run` — see
   [`VERIFICATION.md`](VERIFICATION.md) §1): left-click toggles the panel,
   right-click shows only Quit, no title or timer ever appears in the menu bar.
4. **Manual, flag off** (`make run`): today's dropdown menu is completely
   unchanged. This is the regression that matters — the flag must be a real
   switch, not a one-way door.
5. `make PYTHON=.venv/bin/python reload-macos-app`.

## Right-click detection findings

The plan's gotcha 2 turned out to be wrong on this machine, and finding that
cost four throwaway probe scripts. The probes are gone; the conclusions are
recorded here so plan 07 and any future rumps upgrade don't re-derive them.

**What does not work:**

1. `sendActionOn_(LeftMouseUp | RightMouseUp)` + `NSApp.currentEvent().type()`
   — the documented approach. `currentEvent()` reports type `2`
   (`LeftMouseUp`) for *every* click, left or right, and `buttonNumber()` is
   always `0`. Only a literal Ctrl-key press shows up, via `modifierFlags`;
   a real secondary click is indistinguishable.
2. `NSClickGestureRecognizer` with `buttonMask = 0x2` on the button — never
   fires at all.

**Why:** a local event monitor logging every mouse event showed
`RightMouseDown` (type 3, `buttonNumber=1`) arriving normally, but **no
mouse-*up* events ever arrive**. The status-item button runs its own modal
tracking loop on mouse-down and consumes the up event, so the action fires
against a synthesized left-up.

**What works** (`ui/sidebar_toggle.py` does this): a local
`NSEventMaskRightMouseDown` monitor, scoped to the status item's own window,
which handles the click and returns `None` to swallow it so the button never
starts tracking. Left-clicks stay on the ordinary target/action path, and
the button keeps its default left-mouse-up action mask — no `sendActionOn_`.

**Two pyobjc lifetime traps found while implementing it.** Both fail
*silently*, because an exception raised inside an event-monitor block is
swallowed rather than printed to stderr:

- Defining an `NSObject` subclass inside a function that runs more than once
  — pyobjc registers ObjC classes by name and rejects the second
  registration. Define the class once and cache it.
- Assigning a Python attribute to a pure ObjC object (`menu._my_target = ...`)
  to keep a reference alive — that raises. Only Python-defined ObjC
  subclasses accept arbitrary attributes; hold strong refs on the Python
  side instead.

A third, subtler one: resolve `button.window()` at **event** time, not at
install time. During the first timer tick the status item's window is not yet
its final one, so a window captured at install never matches and every
right-click falls through silently.

## Execution order

1. Read plan 00's findings for questions 4 and 5 — they decide whether we patch
   the rumps status item or construct our own.
2. Write `sidebar_toggle.py`.
3. Register it; pin rumps.
4. Extend `tray_fakes.py`; write the tests.
5. Wire it into `ui/tray.py` behind `sidebar_enabled()` from plan 02.
6. `make check`, manual pass, `reload-macos-app`.
7. Open the PR.

> Depends on plan 00 (findings) and plan 02 (a panel with `toggle()`).

---

Once the plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
