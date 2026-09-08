# Sidebar 04 — Extract a state→view seam from `rebuild_menu()`

> Status: active · Owner: Felipe Fumero · Created 2026-09-05

## Context

`RumpsTrayApp.rebuild_menu()` (`src/meeting_memory/ui/tray.py:96`) does two jobs
at once: it **queries current state** from `TrayController` (recent meetings,
pending tasks, recovered recordings, readiness, recording status, audio mode) and
it **constructs `NSMenu` items** from that state. It is called from roughly eight
event paths in `handle_event` and `handle_notification`.

If the panel duplicates that querying, the two surfaces drift the moment anyone
adds a state field. This plan splits the two halves so both surfaces consume one
immutable snapshot.

This plan is **pure refactor: no user-visible change**. That is deliberate — it
is the riskiest edit to existing behavior, so it ships alone where a regression
is unambiguous and easy to bisect.

**Outcome:** `ui/sidebar_view_model.py` — a frozen view model plus one
`build_view_model(controller, readiness_report, audio_mode_key)` function.
`rebuild_menu()` is rewritten to consume it and must produce byte-identical
menus.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Shape | Frozen dataclasses, no behavior | `AGENTS.md`: "Prefer typed boundary objects over raw dictionaries when crossing layers." Also trivially assertable in tests. |
| Location | `ui/` | It holds UI-shaped strings and menu state. Not a `types/` concern. |
| Labels | Reuse `ui/menu.py` helpers **unchanged** | `recording_label`, `recent_meeting_label`, `processing_task_label`, `recovered_header_label` etc. already exist and are tested. Both surfaces must render the same words. |
| Dead constants | Delete `KNOWN_SPEAKERS_LABEL`, `PREFERENCES_LABEL`, `REVIEW_SPEAKERS_HEADER` | Verified unreferenced anywhere outside `ui/menu.py`. They describe menu items that no longer exist and will mislead whoever builds the panel. |
| Behavior change | **None** | Any diff in the rendered menu is a bug in this plan. |
| Actions | Kept as callables on the view model | The panel needs the same click targets. Bundling them keeps plans 05/06 from re-deriving `TrayController` wiring. |

## Out of scope

- Any panel rendering — plans 05/06.
- Removing the menu — plan 07.

## Files to create

```
src/meeting_memory/ui/sidebar_view_model.py    # <= 200 lines
tests/test_sidebar_view_model.py
```

### `sidebar_view_model.py` — surface

```python
@dataclass(frozen=True, slots=True)
class RecordingView:
    is_recording: bool
    duration_seconds: int
    audio_warning: bool
    label: str                    # from menu.recording_label(...)

@dataclass(frozen=True, slots=True)
class RowView:
    label: str
    tooltip: str
    enabled: bool
    action: Callable[[], None] | None

@dataclass(frozen=True, slots=True)
class SectionView:
    title: str                    # "Recent Meetings", "Pending Meeting Tasks (2)"
    rows: tuple[RowView, ...]
    empty_label: str | None       # "No meetings yet"

@dataclass(frozen=True, slots=True)
class SidebarViewModel:
    recording: RecordingView
    audio_modes: tuple[RowView, ...]     # checkmark already in the label
    recent: SectionView
    pending: SectionView
    recovered: SectionView               # rows empty -> section hidden
    readiness: tuple[RowView, ...]       # five capability status lines
    configuration: tuple[RowView, ...]   # capability windows, Notes, Calendar, Import
    diagnostics: tuple[RowView, ...]     # scan, sync, retry, check setup, test notification
    open_meetings_folder: RowView
    quit: RowView

def build_view_model(controller, *, readiness_report, audio_mode_key,
                     configuration_actions, debugging_actions) -> SidebarViewModel: ...
```

### Key gotchas

1. **`rebuild_menu()` must render identically.** Diff the produced menu titles
   before and after — a snapshot test over the fake rumps menu is the cheapest
   way to prove it.
2. **`recovered` is conditionally hidden today.** `_add_recovered_recordings`
   (`ui/submenus.py:172`) returns early when the list is empty, adding no header
   at all. `pending` always shows a header, even at zero. Preserve both.
3. **Audio mode checkmarks live in the label**, prefixed `"✓ "` by
   `AudioModeMenu._mode_label`. Keep that so the panel and menu agree; do not
   invent a separate `selected` flag.
4. **Do not call `build_view_model` during `__init__` before the controller is
   fully wired.** `rebuild_menu()` is currently the last statement of
   `RumpsTrayApp.__init__` for exactly this reason.
5. **The 300-line cap.** If the view model plus builder crowds the limit, split
   the builder into `sidebar_view_model_sections.py` rather than shortening names.
6. **`ui/setup_tray.py` also calls `configuration_submenu`.** It is out of scope
   (setup keeps its plain menu, per the feature decisions), so `configuration_submenu`
   must keep its current signature working for that caller.

## Files to modify

| File | Change |
|---|---|
| `src/meeting_memory/ui/tray.py` | `rebuild_menu()` builds a view model, then renders it. No behavior change. |
| `src/meeting_memory/ui/submenus.py` | `configuration_submenu` / `debugging_submenu` accept the view model's row tuples. Must stay compatible with `ui/setup_tray.py`. |
| `src/meeting_memory/ui/menu.py` | Delete the three verified-dead constants. |
| `tests/test_structure.py` | Register `"ui/sidebar_view_model.py"`. |
| `tests/test_menu.py`, `tests/test_submenus.py`, `tests/test_tray.py` | Update for the new signatures. Assertions about rendered **labels** should not change — if they do, this plan changed behavior. |

## Tests — `tests/test_sidebar_view_model.py`

- Recording view reflects idle / recording / recording-with-warning, and its
  `label` matches `menu.recording_label(...)` for the same inputs.
- Empty recent → `empty_label == "No meetings yet"`, no rows.
- Recent list is capped at 3, matching `menu.recent_meeting_labels`.
- Pending section header shows `(0)` and still renders when empty.
- Recovered section has no rows and is marked hidden when empty.
- Readiness `None` → empty tuple, not a crash.
- Every `RowView.action` invokes the right `TrayController` method (use the
  existing fakes in `tests/tray_fakes.py`).
- **Snapshot test:** the full menu titles rendered by `rebuild_menu()` are
  unchanged from a checked-in expected list. This is the real safety net.

## Verification

> **This plan has no visual output — success is indistinguishable from doing
> nothing.** The only real proof is the snapshot test, and **it must be written and
> passing against the current menu before any refactoring begins.** A snapshot
> written afterward proves only that the code agrees with itself.
> See [`VERIFICATION.md`](VERIFICATION.md) §4.
>
> If the expected list needs editing to make the test pass, this plan changed
> behavior and the diff needs review — not a new snapshot.

1. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_sidebar_view_model.py tests/test_tray.py tests/test_submenus.py tests/test_menu.py -v`
2. `make check` green — **the full 1000-test suite must pass with no assertion
   edits beyond signature changes.**
3. **Manual:** open the dropdown menu and confirm it is visually identical to
   before this plan, in every state (idle, recording, pending tasks, recovered
   recordings present). If you captured the baseline shots from
   [`VERIFICATION.md`](VERIFICATION.md) §3 (`00-menu-*.png`), diff against them.

## Implementation notes

Two deviations from the literal plan, both to satisfy gotcha 6
(`configuration_submenu` must keep working unchanged for `ui/setup_tray.py`)
without a circular import between `submenus.py` and the new
`sidebar_view_model.py`:

- **`configuration_submenu`'s signature is untouched.** It still takes
  `audio_mode_menu` + `ConfigurationActions` directly and builds its own rows,
  exactly as before. Only `debugging_submenu` was changed to accept
  `pending`/`recovered`/`readiness`/`diagnostics` from the view model — it has
  no `setup_tray.py` caller to protect, and it's where the actual
  controller-derived, drift-risky state (processing tasks, recovered
  recordings, readiness) lives. The view model's `configuration`/`audio_modes`
  fields exist for the panel (plans 05/06) but the dropdown's Configuration
  submenu does not currently route through them — there is no real drift risk
  there since both derivations are deterministic from the static `Capability`
  enum and actions, not from mutable `TrayController` state.
- **`ConfigurationActions` and `DebuggingActions` moved into
  `sidebar_view_model.py`** (from `submenus.py`), since `submenus.py`'s new
  `debugging_submenu` needs `RowView`/`SectionView` from the view-model
  module — keeping the action dataclasses there too makes the dependency
  one-directional. `submenus.py` re-exports both names, so existing imports
  of `from meeting_memory.ui.submenus import ConfigurationActions` keep
  working.

The snapshot test in `tests/test_sidebar_view_model.py` was written first,
against the unmodified code, and its expected lists were never touched after
— both pass byte-for-byte post-refactor, which is the plan's actual proof
of no behavior change.

## Execution order

1. **Capture the baseline menu screenshots** (`VERIFICATION.md` §3) — they are
   also plan 07's proof that nothing was lost.
2. Add the snapshot test **against the current menu, before writing any new code**.
3. Write the view model types.
4. Write `build_view_model`, reusing `ui/menu.py` label helpers verbatim.
5. Rewrite `rebuild_menu()` and the submenu builders to consume it.
6. Confirm the snapshot still passes, with its expected list untouched.
7. Delete the dead constants.
8. `make check`, manual pass.
9. Open the PR.

> Independent of plans 00–03; can run in parallel with them. Plans 05 and 06
> depend on it.

---

Once the plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
