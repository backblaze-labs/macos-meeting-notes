# Sidebar feature — execution plans

> Status: complete (all plans in `completed/`) · Owner: Felipe Fumero · Created 2026-09-05

Replace the menu bar dropdown with a draggable, edge-snapping floating panel.
The status item becomes a dumb toggle button carrying no title, no timer, and no
warning glyph — everything moves into the panel.

## Agreed behavior

| Question | Decision |
|---|---|
| Menu bar item | Icon only. Left-click toggles the sidebar. |
| Quit safety hatch | Right-click opens a 1-item Quit menu. *(Superseded 2026-09-08: the right-click menu now holds everything but record/screenshot/quit, and the panel is three icon buttons — see `../../sidebar.md`.)* |
| Recording visibility | Starting a recording forces the sidebar visible. |
| Setup tray | Unchanged — keeps its plain dropdown menu. |
| Orientation | Reorients: horizontal on top/bottom snap, vertical on left/right. |
| Snap anchors | left-center, right-center, top-center, bottom-center. Free-float elsewhere. |
| Position persistence | Yes, via `NSUserDefaults` frame autosave — **not** the Phase 4 preference store. |
| Toggle persistence | No. Starts hidden each launch. |

## How to verify any of this

[`VERIFICATION.md`](VERIFICATION.md) is the shared appendix every plan points at.
It owns the standalone demo harness that
renders the panel with fake data (no recording, no B2, no meetings), the
screenshot record, and a per-plan table of what success actually looks like.

Two plans — 01 and 04 — have **no visual output at all** and can only be proved by
tests. That is called out in both, and in `VERIFICATION.md` §4.

## Plans

All eight plans shipped on 2026-09-05; the feature doc is
[`docs/features/sidebar.md`](../../sidebar.md).

| # | Plan | Depends on | Ships |
|---|---|---|---|
| — | [Verification appendix](VERIFICATION.md) | — | Flag, demo harness, screenshot record |
| 00 | [Throwaway spike](../completed/00-panel-spike.md) | — | Nothing (findings only) |
| 01 | [Snap geometry](../completed/01-snap-geometry.md) | — | Pure math + tests |
| 02 | [Panel shell](../completed/02-panel-shell.md) | 00, 01 | Empty floating panel that drags and snaps |
| 03 | [Status item toggle](../completed/03-status-item-toggle.md) | 00, 02 | Click-to-toggle, right-click Quit |
| 04 | [Render seam](../completed/04-render-seam.md) | — | Pure refactor, no visible change |
| 05 | [Vertical content](../completed/05-vertical-content.md) | 02, 04 | The panel does everything the menu did |
| 06 | [Horizontal layout](../completed/06-horizontal-layout.md) | 02, 05 | Reorientation on top/bottom snap |
| 07 | [Cutover](../completed/07-cutover.md) | all | Dropdown retired, docs written |

Plans 01 and 04 are independent of everything else and can run in parallel with
00–03. Plan 06 is the only one that could be dropped without losing a working
feature — without it the panel snaps to all four edges in a single shape.

## Standing constraints

From `AGENTS.md` and `ARCHITECTURE.md`, applying to every plan here:

- Python source files stay at or below **300 lines**. This is why the work splits
  into ~9 modules rather than 3.
- New `ui/` modules must be registered in `REQUIRED_SOURCE_FILES` in
  `tests/test_structure.py`, or the structure gate fails.
- `rumps` imports stay inside `ui/`. Layer direction `types <- config <- repo <- service <- ui`
  is mechanically enforced.
- Background threads never touch UI directly — they emit typed events from
  `types/events.py` and the main thread drains them.
- Gate before finishing: `make check`.
- After app behavior changes: `make PYTHON=.venv/bin/python reload-macos-app`.
- Work happens in a dedicated worktree on a feature branch, merged back to `main`.

## Known risk

`ui/sidebar_toggle.py` (plan 03) depends on `rumps` 0.4.0 internals —
specifically detaching the menu that `rumps.py:954` attaches to the status item.
That access is contained to one module and the rumps version is pinned. If a
future upgrade breaks the toggle, that file is the only place to fix.

---

Once a plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
