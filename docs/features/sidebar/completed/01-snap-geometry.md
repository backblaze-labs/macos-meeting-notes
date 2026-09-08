# Sidebar 01 — Pure snap geometry and orientation model

> Status: active · Owner: Felipe Fumero · Created 2026-09-05

## Context

The sidebar is dragged freely and snaps flush when released near **left-center,
right-center, top-center, or bottom-center** of the screen it is on. Snapping to
top or bottom also **reorients** the panel to a horizontal strip; left and right
keep it vertical.

All of that is arithmetic, and it is where the bugs will be — notch insets,
multiple displays with different scales, a display being unplugged mid-session.
This plan isolates that arithmetic into a module with **no AppKit import**, so it
is fully unit-testable without a screen. Every later plan consumes it.

Measured on the owner's machine, which is why this matters:

| Display | `frame` | `visibleFrame` | Top inset |
|---|---|---|---|
| Built-in | 1728×1117 | 1728×1084 | 33 pt (menu bar / notch) |
| External | 1920×1080 | 1920×1080 | 0 pt |

Snap targets must be computed against `visibleFrame`, per screen, never `frame`.

**Outcome:** `ui/sidebar_geometry.py` — pure functions plus a small frozen type
vocabulary, with exhaustive tests covering both screen shapes above.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Layer | `ui/` | It is UI geometry. It imports nothing, so it satisfies every layer rule trivially. |
| AppKit | **None** | Callers pass plain rects. Keeps the module testable with no display and no pyobjc. |
| Rect type | Own frozen dataclass `Rect(x, y, width, height)` | Avoids `NSRect` in a pure module. Plan 02 converts at the boundary. |
| Coordinate space | AppKit convention: origin bottom-left, y grows up | Matches what `NSWindow.frame` / `NSScreen.visibleFrame` give us, so plan 02 needs no flipping. |
| Anchors | `LEFT`, `RIGHT`, `TOP`, `BOTTOM`, `FREE` | Exactly the four the owner specified, plus the unsnapped state. |
| Orientation | Derived from anchor, not stored independently | `LEFT`/`RIGHT`/`FREE` → `VERTICAL`; `TOP`/`BOTTOM` → `HORIZONTAL`. One source of truth prevents drift. |
| Snap threshold | 48 pt, a module constant | Generous enough to feel magnetic, tight enough not to fight a deliberate free placement. Tune later from one place. |
| Multi-screen | Snap against the screen containing the **largest area** of the panel | Standard macOS behavior; unambiguous when a panel straddles two displays. |
| Margin | 0 pt — flush to the visible edge | "Sticks there" per the owner. A gap would read as not-quite-snapped. |

## Out of scope

- Any `NSPanel`, drag tracking, or animation — plan 02.
- The actual vertical/horizontal view layouts — plans 05 and 06.
- Persisting the anchor — plan 02 owns frame autosave.

## Files to create

```
src/meeting_memory/ui/sidebar_geometry.py     # pure; target <= 160 lines
tests/test_sidebar_geometry.py                # the real deliverable
```

### `sidebar_geometry.py` — surface

```python
SNAP_THRESHOLD = 48.0

class SnapAnchor(StrEnum):
    FREE = "free"; LEFT = "left"; RIGHT = "right"; TOP = "top"; BOTTOM = "bottom"

class Orientation(StrEnum):
    VERTICAL = "vertical"; HORIZONTAL = "horizontal"

@dataclass(frozen=True, slots=True)
class Rect:
    x: float; y: float; width: float; height: float
    @property
    def center_x(self) -> float: ...
    @property
    def center_y(self) -> float: ...

def orientation_for(anchor: SnapAnchor) -> Orientation:
    """LEFT/RIGHT/FREE -> VERTICAL; TOP/BOTTOM -> HORIZONTAL."""

def screen_for(panel: Rect, screens: Sequence[Rect]) -> Rect:
    """The visible frame holding the largest area of `panel`.
    Falls back to screens[0] when there is no overlap at all."""

def nearest_anchor(panel: Rect, visible: Rect,
                   threshold: float = SNAP_THRESHOLD) -> SnapAnchor:
    """FREE unless one edge-center is within `threshold`.
    Ties resolve in LEFT, RIGHT, TOP, BOTTOM order (deterministic)."""

def snapped_origin(panel: Rect, visible: Rect, anchor: SnapAnchor) -> tuple[float, float]:
    """Flush origin for `anchor`, centered on the perpendicular axis.
    Returns panel's own origin unchanged for FREE."""

def clamp_to_visible(panel: Rect, visible: Rect) -> tuple[float, float]:
    """Pull a fully- or partly-offscreen panel back inside `visible`.
    Used after a display is disconnected or resolution changes."""

def resolve_drop(panel: Rect, screens: Sequence[Rect],
                 threshold: float = SNAP_THRESHOLD) -> tuple[SnapAnchor, float, float, Orientation]:
    """One call for plan 02's mouse-up: pick screen, pick anchor, place, orient."""
```

### Key gotchas

1. **`visibleFrame`, never `frame`.** The 33 pt built-in inset above is the menu
   bar. Snapping TOP against `frame` puts the panel *under* the menu bar.
2. **A snapped panel's size changes on reorientation.** `snapped_origin` receives
   the panel rect it is placing. Plan 02 must resize *first*, then ask for the
   origin — otherwise a 240×420 vertical panel gets centered as if it were still
   vertical while being drawn horizontal. Document this ordering in the docstring.
3. **`screens` may be empty** in headless/CI contexts. Guard it; do not index
   blindly.
4. **Y grows up.** `TOP` means the panel's *max* y equals `visible` max y, i.e.
   `y = visible.y + visible.height - panel.height`. Easy to invert.
5. **Ties must be deterministic** or the tests flake. A panel dead-center in a
   tiny screen can be within threshold of two anchors.

## Files to modify

| File | Change |
|---|---|
| `tests/test_structure.py` | Add `"ui/sidebar_geometry.py"` to `REQUIRED_SOURCE_FILES`. Without this the module is unregistered and later plans have nothing to build on. |

## Tests — `tests/test_sidebar_geometry.py`

Parametrize over both real screen shapes (1728×1084 visible with 33 pt inset,
1920×1080 with none):

- `orientation_for` covers all five anchors.
- `nearest_anchor` returns `FREE` at screen center; each anchor just inside
  threshold; `FREE` just outside threshold; deterministic tie order.
- `snapped_origin` for all four anchors puts the panel flush and centered on the
  perpendicular axis. Assert against explicit numbers, not recomputed formulas.
- **TOP respects the 33 pt inset** on the built-in display — dedicated test.
- `screen_for` picks the majority-overlap screen; straddling; zero overlap
  falls back to `screens[0]`; empty sequence raises or returns a documented default.
- `clamp_to_visible`: fully offscreen, partly offscreen each edge, panel larger
  than the screen.
- `resolve_drop` end-to-end: drop near external-display right edge →
  `(RIGHT, x, y, VERTICAL)`; drop near built-in top edge →
  `(TOP, x, y, HORIZONTAL)`.
- Resize-then-place ordering (gotcha 2) has an explicit test.

## Verification

> **This plan has no visual output.** It is pure arithmetic — there is nothing to
> look at, and no screenshot to take. A green test file is the entire deliverable,
> which is why it is worth over-testing here: nothing downstream reveals a subtle
> geometry bug until a panel lands 33 pt underneath the menu bar.
> See [`VERIFICATION.md`](VERIFICATION.md) §4.

1. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_sidebar_geometry.py -v`
2. `make check` — lint + full suite + structure, all green.
3. Confirm the module imports with no AppKit available:
   `PYTHONPATH=src .venv/bin/python -c "import meeting_memory.ui.sidebar_geometry"`
   after asserting `AppKit` is not in `sys.modules`.

## Execution order

1. Write `sidebar_geometry.py`.
2. Register it in `tests/test_structure.py`.
3. Write the tests, including both measured screen shapes.
4. `make check`.
5. Open the PR.

> This plan is independent of plan 00 and can run in parallel with it.

---

Once the plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
