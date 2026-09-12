# Sidebar — shared verification appendix

> Status: active · Owner: Felipe Fumero · Created 2026-09-05

Every plan in this directory answers "how do I know it worked" by pointing here.
This file owns the things all of them share: **the standalone demo harness**,
**the screenshot record**, and (historically) the feature flag.

Read this before starting plan 02.

---

## 1. The feature flag (removed in plan 07)

Plans 02–06 built the sidebar alongside the dropdown menu behind
`MEETING_MEMORY_SIDEBAR` (`ui/sidebar_flag.py`). Plan 07 deleted both: the
sidebar is now the only runtime surface, so `make run` and the installed
bundle show it unconditionally. Earlier plan documents that say "flag on"
describe history, not a switch that still exists.

---

## 2. The demo harness

Without this, the first time you can *look* at the sidebar is plan 05, inside a
full app launch with real B2 config and real recordings. That is a bad place to
debug a layout.

The harness renders the panel from a hand-built fake `SidebarViewModel` — no
recording, no B2, no calendar, no Keychain, no meetings directory.

| | |
|---|---|
| Location | Scratchpad, **not** the repo |
| File | `<scratchpad>/sidebar_demo.py` |
| Created in | Plan 02 (skeleton) — extended by plans 05 and 06 (`sidebar_demo.py <state> [vertical\|top\|bottom\|horizontal] [--shot DIR]`) |
| Committed | Never. It would trip `test_structure.py` registration and the 300-line audit. |

```python
# <scratchpad>/sidebar_demo.py
"""Open the sidebar standalone with fake data. Not part of the app."""
import sys; sys.path.insert(0, "src")

from meeting_memory.ui.sidebar_panel import SidebarPanel
from meeting_memory.ui.sidebar_vertical import build_vertical   # plan 05
from meeting_memory.ui.macos import configure_background_app_identity

STATES = {
    "idle":       ...,   # nothing recording, 3 recent, 0 pending
    "recording":  ...,   # 12:34 elapsed, no warning
    "warning":    ...,   # recording + audio_warning set
    "busy":       ...,   # 2 pending tasks, 1 interrupted recording
    "empty":      ...,   # no meetings yet, readiness None
}

state = sys.argv[1] if len(sys.argv) > 1 else "idle"
# build panel, set content from STATES[state], run an NSApplication loop
```

```bash
PYTHONPATH=src .venv/bin/python "$SCRATCHPAD/sidebar_demo.py" recording
```

Build the five states **once**, in plan 02, even though plan 02 renders only a
placeholder. Plans 05 and 06 then have somewhere to render into on day one.

`empty` and `busy` are the states that break layouts — zero rows and overflowing
rows. Do not skip them.

---

## 3. The screenshot record

Nothing in the plans currently captures what the sidebar looked like, so there is
no visual record and nothing for plan 07 to diff against the menu it retires.

```bash
mkdir -p "$SCRATCHPAD/sidebar-shots"
screencapture -o -x "$SCRATCHPAD/sidebar-shots/<plan>-<state>-<theme>.png"
```

`-o` drops the window shadow, `-x` silences the shutter.

**Capture before you start plan 07**, while the dropdown still exists:

```
00-menu-idle.png   00-menu-recording.png   00-menu-busy.png
```

Those three are the baseline. Plan 07 must be able to show that every action in
them survived.

Per plan, capture at minimum:

| Plan | Shots |
|---|---|
| 02 | Panel snapped at each of the four anchors, plus free-floating |
| 05 | `idle`, `recording`, `warning`, `busy`, `empty` — **each in light and dark** |
| 06 | Horizontal bar at top and at bottom; overflow popover open in both |
| 07 | Final state of every plan-05 shot, plus the setup tray unchanged |

Ten of these live in `docs/features/sidebar.md` when plan 07 writes it. The rest
stay in the scratchpad as working evidence.

---

## 4. What success looks like, per plan

Be honest about which plans you can *see* and which you can only *prove*.

| Plan | Evidence | Can you look at it? |
|---|---|---|
| 00 Spike | Six answered questions in its Findings section | Yes — a bare panel on screen |
| 01 Geometry | `tests/test_sidebar_geometry.py` green | **No.** Pure math. A green suite is the entire deliverable. |
| 02 Panel shell | Tests + demo harness + 5 anchor screenshots | Yes — an empty panel that drags and snaps |
| 03 Toggle | Tests + manual click behavior | Partly — the panel appearing is the only visible signal |
| 04 Render seam | Snapshot test unchanged + full suite green | **No.** Success is indistinguishable from doing nothing. See below. |
| 05 Vertical | Tests + harness + 10 screenshots | Yes — this is the plan where the feature becomes real |
| 06 Horizontal | Tests + harness + 4 screenshots | Yes |
| 07 Cutover | Full suite + full manual pass + setup-tray regression | Yes — and the baseline shots prove nothing was lost |

### The two invisible plans

**Plan 01** has no screen output whatsoever. Do not go looking for one. The test
file is the deliverable, and it is worth over-testing precisely because nothing
downstream will reveal a subtle arithmetic bug until a panel lands 33 pt under
the menu bar.

**Plan 04** is a refactor whose success criterion is *nothing changed*. The only
real proof is the snapshot test, and **it must be written and passing against the
current menu before any refactoring begins**. A snapshot written afterward proves
only that the code agrees with itself.

```bash
# Before touching rebuild_menu(), capture the current menu:
PYTHONPATH=src .venv/bin/python -m pytest tests/test_sidebar_view_model.py -k snapshot -v
# ...refactor...
# Same command must still pass, with the expected list untouched.
```

If the expected list needs editing to make the test pass, plan 04 changed
behavior and the diff needs review, not a new snapshot.

---

## 5. The gate, every time

From `AGENTS.md`, non-negotiable before any plan is considered done:

```bash
make check
```

Lint, the full 1000-test suite, and the structural enforcement tests. Then, for
any plan that changed app behavior:

```bash
make PYTHON=.venv/bin/python reload-macos-app
```

---

Once a plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
