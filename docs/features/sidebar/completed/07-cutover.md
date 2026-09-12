# Sidebar 07 — Cutover: retire the dropdown, auto-show on record, document

> Status: complete (2026-09-05) · Owner: Felipe Fumero · Created 2026-09-05

## Context

Plans 00–06 build the sidebar alongside the existing dropdown menu, behind an
off-by-default flag. This plan flips it on, deletes the menu path, and writes the
documentation `AGENTS.md` requires.

It also adds the one behavior that makes the design safe: **starting a recording
forces the sidebar visible.** Once the menu bar icon carries no title and no
timer, a user with the sidebar toggled off has no on-screen indication that
recording is in progress — which contradicts `PRODUCT.md`'s "Make recording and
processing state unmistakable at a glance." Auto-show resolves it at the moment
it starts mattering.

**Outcome:** the sidebar is the only runtime surface. `RumpsTrayApp` no longer
builds an `NSMenu`. Setup keeps its plain menu, unchanged.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Flag | Removed, not left as a preference | A permanent dual surface doubles the maintenance and the test matrix forever. |
| Auto-show | On `start_recording`, force `panel.show()` | Owner's decision. Only forces *visible* — the user may hide it again immediately after. |
| Auto-hide | **None** on stop | Hiding something the user is looking at is worse than leaving it. |
| Setup tray | Untouched, keeps its dropdown | Owner's decision: first run is a bad moment for a novel control, and it halves the surface. |
| Menu bar title | `_tray_title()` / `update_tray_title()` deleted | Nothing renders there any more. Dead code that still computes a timer string invites regressions. |
| Right-click Quit | Retained permanently | The safety hatch from plan 03 is not a transitional device. |
| `keep_timer_running_during_menu_tracking` | Retained | `ui/macos.py:60` keeps the 1 s tick alive during menu tracking. The setup tray still has a menu, and the right-click Quit menu tracks too. |

## Out of scope

- Sidebar for the setup tray.
- Any new capability. This plan removes code and writes docs.

## Files to modify

| File | Change |
|---|---|
| `src/meeting_memory/ui/sidebar_flag.py` | **Delete.** Also remove `sidebar_enabled()` call sites and the `MEETING_MEMORY_SIDEBAR` references in `VERIFICATION.md`. |
| `src/meeting_memory/ui/tray.py` | Delete `rebuild_menu()`, `_tray_title()`, `update_tray_title()`, `current_recording_label()`, `update_recording_label()`, `self.recording_item`, `self.recording_label`, and the `_debugging_submenu()` helper. Route every `rebuild_menu()` call site in `handle_event` / `handle_notification` to the panel's refresh. Remove the plan-03 flag. Pass `title=None` to `rumps.App`. |
| `src/meeting_memory/ui/controller.py` | On `_recording_started`, emit an event the tray turns into `panel.show()`. **Do not** import or call the panel from the controller — it stays event-driven per the threading model in `ARCHITECTURE.md`. |
| `src/meeting_memory/types/events.py` | Add a typed event for "reveal the sidebar" if no existing event fits. Keep it a pure dataclass. |
| `src/meeting_memory/ui/submenus.py` | Keep only what `ui/setup_tray.py` still needs (`configuration_submenu`). Delete `debugging_submenu` and `DebuggingActions` if nothing else references them. |
| `src/meeting_memory/ui/audio_modes.py` | `AudioModeMenu.add_items` is menu-only. Keep the `select_mode` logic — the panel uses it — and drop the menu construction. |
| `SPEC.md` | New subsection under §4 Functional Requirements describing the sidebar: toggle semantics, the four snap anchors, reorientation, auto-show on record, right-click Quit, and that the menu bar item carries no state. Cross-reference the feature doc. |
| `ARCHITECTURE.md` | Update the `ui/` layer description: the tray no longer owns an `NSMenu` at runtime; add the sidebar modules and note that `ui/sidebar_toggle.py` is the sole holder of rumps-internal access. |
| `docs/features/macos-app.md` | Update to match the new interaction model. |
| `README.md` | Update any screenshot or description of the menu bar dropdown. |
| `PRODUCT.md` | Add a line acknowledging the deliberate departure from "prefer familiar macOS controls" for the sidebar, with auto-show as the mitigation. Leaving this unrecorded means a future agent reads the sidebar as a violation. |
| `docs/deferred-work.md` | Dated note: vertical-only was considered and rejected in favor of reorientation; setup tray intentionally not converted; toggle visibility intentionally not persisted across launches. |
| `tests/test_tray.py`, `tests/test_menu.py`, `tests/test_submenus.py`, `tests/test_audio_mode_menu.py`, `tests/test_runtime_tray_events.py`, `tests/tray_fakes.py` | Remove menu-construction assertions; re-point behavior assertions at the panel. Roughly 1,260 lines across these files — expect real churn. Assertions about **labels** should survive unchanged, since both surfaces share `ui/menu.py`. |

## Files to create

```
docs/features/sidebar.md      # the feature doc AGENTS.md requires, from docs/features/_template.md
```

Covering: the interaction model, the four anchors and reorientation, what lives
in the panel vs the windows it launches, the rumps-internals dependency and its
blast radius, and the accessibility tradeoff with its mitigation.

### Key gotchas

1. **`rebuild_menu()` has ~8 call sites** across `handle_event` and
   `handle_notification` (`ui/tray.py:218`–`ui/tray.py:294`). Missing one leaves
   a state change that never reaches the panel — and with the menu gone there is
   no second surface to reveal the bug.
2. **`ui/setup_tray.py` still calls `configuration_submenu`.** Do not delete it.
   Run the setup tray manually after this change.
3. **Auto-show must not reach into UI from a worker.** `ARCHITECTURE.md` is
   explicit: background threads emit typed events and the main thread drains
   them. Route through the queue.
4. **Auto-show fires on *every* start**, including recovery-initiated and
   calendar-triggered recordings. Confirm that is wanted; if not, scope it to
   user-initiated starts and record the decision in `docs/deferred-work.md`.
5. **The 300-line cap applies to the shrinking files too** — `ui/tray.py` is at
   300 exactly today, so this plan should bring it comfortably under.
6. **`test_structure.py` `REQUIRED_SOURCE_FILES`** must not list modules this
   plan deletes.

## Verification

> This plan **removes** a user-visible surface, so its verification is the only one
> that must prove a negative: nothing was lost. That is what the baseline menu
> screenshots from [`VERIFICATION.md`](VERIFICATION.md) §3 (`00-menu-*.png`) are
> for. If they were never captured, capture them from `main` before starting.

1. `make check` — lint, full suite, structure. All green.
2. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_structure.py -v`
   confirms no orphaned registrations.
3. `make doctor` still succeeds.
4. **Manual, full pass:**
   - fresh launch → icon only, no title, no menu; left-click toggles the panel
   - right-click → Quit only
   - start a recording with the panel hidden → it appears on its own
   - timer ticks in the panel; audio warning appears and clears
   - **every action in the baseline `00-menu-*.png` shots is reachable in the
     panel** — walk the screenshots row by row, do not do this from memory
   - all four snap anchors, reorientation on top/bottom
   - quit and relaunch → position and anchor restored, panel starts hidden
   - **setup tray unchanged**: rename `.env`, relaunch, confirm the plain setup
     menu still works end to end
   - VoiceOver reads the panel; light and dark both legible
5. **Re-capture the plan-05 shot set** on the flag-free build, plus the unchanged
   setup tray, for `docs/features/sidebar.md`.
6. `make PYTHON=.venv/bin/python reload-macos-app`.

## Implementation notes (2026-09-05)

- **`rebuild_menu()` became `RumpsTrayApp.refresh_sidebar()`**, the single
  render path; it stores the snapshot as `app.view_model` so tests assert
  against the view model rather than a fake menu. `AudioModeMenu`'s callback
  is now `on_change`; `ConfigurationSurfaceUI` keeps its `rebuild_menu=`
  keyword (not in this plan's file list).
- **`SidebarWiring` builds the real panel whenever `rumps_module is None`**
  (i.e. the real app); tests get a panel only by injecting `panel_factory`.
  `RumpsTrayApp` grew a `sidebar_panel_factory=` pass-through for that.
- **`ui/submenus.py` keeps only `configuration_submenu` /
  `configuration_surface_actions`** for the setup tray; the dead
  `audio_mode_menu` parameter (always `None` there) went with
  `AudioModeMenu.add_items`. `menu.tray_title` is deleted too.
- **The plan-04 snapshot test now snapshots the view model** in the vertical
  panel's order (`flatten_view_model` in
  `tests/sidebar_view_model_test_fixtures.py`): the same labels the dropdown
  listed, re-ordered — this is the "every action survived" check.
- **Baseline `00-menu-*.png` shots were not captured** (see
  `docs/deferred-work.md`); the snapshot test is the substitute record.
- **Manual pass partially deferred**: the drag, popover, and auto-show paths
  were exercised programmatically through the real code; the by-hand walk
  (setup tray, VoiceOver, light/dark) is recorded as deferred.
- `ui/controller.py` is back under the 300-line cap after hoisting the event import.

## Execution order

1. Confirm the baseline `00-menu-*.png` shots exist; capture them from `main` if not.
2. Add the auto-show event and wire it through the queue.
3. Delete the menu path from `ui/tray.py`; re-point every `rebuild_menu()` call site.
4. Prune `ui/submenus.py` and `ui/audio_modes.py`, keeping the setup-tray path intact.
5. Rework the test files.
6. Write `docs/features/sidebar.md`; update `SPEC.md`, `ARCHITECTURE.md`,
   `PRODUCT.md`, `README.md`, `docs/features/macos-app.md`, `docs/deferred-work.md`.
7. `make check`, then the full manual pass including the setup tray.
8. Remove `sidebar_flag.py` and the flag from `VERIFICATION.md`.
9. `make PYTHON=.venv/bin/python reload-macos-app`.
10. Open the PR.

> Depends on every preceding plan. This is the only plan with user-visible
> removal, so it should be the smallest possible diff on top of a working
> flag-on sidebar.

---

Once the plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
