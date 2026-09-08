"""Vertical sidebar layout: assembles a `SidebarViewModel` into an NSView tree.

`SidebarViewModel` (plan 04, `ui/sidebar_view_model.py`) is accessed only by
attribute here, never imported — this was written and tested against its
documented shape before that module existed, and staying duck-typed costs
nothing now that it does.

Layout decisions not pinned down by that surface:

- "Configuration" and "Diagnostics" are plain `tuple[RowView, ...]`, not
  `SectionView` — they never have an empty state, so the collapsible header
  text is a fixed local string, not a view-model field.
- `readiness` rows render inside the Diagnostics section, above its own rows
  — matching where `debugging_submenu` puts them today
  (`ui/submenus.py:131`).
- `recovered` follows the "hidden entirely when empty" rule; `recent` and
  `pending` always show their header and fall back to `empty_label` as a
  disabled row when empty.
- `quit.action` and the recording toggle are `None`/absent on the view model
  by design (real callbacks are rumps-specific) — the caller supplies
  `on_quit` and `on_toggle_recording` instead.
- No close-button affordance in the title bar — the status item already
  toggles the panel (plan 03); a close button isn't in the plan's widget
  surface and would need its own click wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, NamedTuple

from meeting_memory.ui.sidebar_sections import SectionState
from meeting_memory.ui.sidebar_theme import header_view, on_header_color, title_font
from meeting_memory.ui.sidebar_widgets import (
    PANEL_WIDTH,
    ROW_HEIGHT,
    SECTION_HEADER_HEIGHT,
    SEPARATOR_HEIGHT,
    header_label,
    recording_row,
    row,
    section_header,
    separator,
)

TITLE_BAR_HEIGHT = 34.0
TITLE_TEXT = "Meeting Memory"
CONFIGURATION_TITLE = "Configuration"
DIAGNOSTICS_TITLE = "Diagnostics"


@dataclass
class _PlannedItem:
    height: float
    build: Callable[[Any, float], Any]
    kind: str = "row"


class _DisabledRow(NamedTuple):
    """A `RowView`-shaped wrapper for a section's plain `empty_label` string
    (e.g. "No meetings yet") — disabled, no tooltip, no action."""

    label: str
    tooltip: str = ""
    enabled: bool = False
    action: Callable[[], None] | None = None


def build_vertical(
    appkit: Any,
    view_model: Any,
    section_state: SectionState,
    *,
    on_toggle_recording: Callable[[], None],
    on_quit: Callable[[], None],
    on_rebuild: Callable[[], None],
    max_height: float | None = None,
) -> tuple[Any, Any]:
    """Return `(content_view, recording_row_view)`.

    The caller keeps `recording_row_view` to call `.update(recording_view)`
    on the 1 Hz tick without a full rebuild, and calls this function again
    (swapping `SidebarPanel.set_content_view`) whenever anything else in the
    view model changes, including a section toggle via `on_rebuild`.

    `on_toggle_recording` and `on_quit` are supplied by the caller rather
    than read off the view model: `SidebarViewModel.quit.action` is `None` by
    design (its real callback is rumps-specific — see `sidebar_view_model.py`),
    and the recording toggle isn't part of `RecordingView` at all.
    """

    plan = _plan(view_model, section_state, on_toggle_recording, on_quit, on_rebuild)
    total_height = sum(item.height for item in plan)

    stack = appkit.NSView.alloc().initWithFrame_(
        appkit.NSMakeRect(0.0, 0.0, PANEL_WIDTH, total_height)
    )

    recording_view = None
    y = total_height
    for item in plan:
        y -= item.height
        built = item.build(appkit, y)
        stack.addSubview_(built)
        if item.kind == "recording":
            recording_view = built

    if max_height is not None and total_height > max_height:
        scroll = appkit.NSScrollView.alloc().initWithFrame_(
            appkit.NSMakeRect(0.0, 0.0, PANEL_WIDTH, max_height)
        )
        scroll.setDocumentView_(stack)
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setDrawsBackground_(False)
        return scroll, recording_view

    return stack, recording_view


def _plan(
    view_model: Any,
    section_state: SectionState,
    on_toggle_recording: Callable[[], None],
    on_quit: Callable[[], None],
    on_rebuild: Callable[[], None],
) -> list[_PlannedItem]:
    items: list[_PlannedItem] = [
        _PlannedItem(TITLE_BAR_HEIGHT, lambda appkit, y: _title_bar(appkit, y)),
        _PlannedItem(
            ROW_HEIGHT,
            lambda appkit, y: recording_row(
                appkit, view_model.recording, y, PANEL_WIDTH, on_toggle_recording
            ),
            kind="recording",
        ),
    ]
    status = getattr(view_model, "status", None)
    if status is not None:
        items.append(_PlannedItem(ROW_HEIGHT, lambda appkit, y: row(appkit, status, y)))
    items += [
        _PlannedItem(SEPARATOR_HEIGHT, lambda appkit, y: separator(appkit, y)),
        _PlannedItem(
            SECTION_HEADER_HEIGHT,
            lambda appkit, y: _fixed_header(appkit, "Audio Mode", y),
        ),
    ]
    items.extend(_row_items(view_model.audio_modes))
    items.append(_PlannedItem(SEPARATOR_HEIGHT, lambda appkit, y: separator(appkit, y)))

    items.extend(_collapsible_section_items("recent", view_model.recent, section_state, on_rebuild))
    # Always reachable, like the retired dropdown's item — not part of the
    # collapsible section, and present with zero meetings (REQ-F8-01).
    folder_row = view_model.open_meetings_folder
    items.append(_PlannedItem(ROW_HEIGHT, lambda appkit, y: row(appkit, folder_row, y)))
    items.append(_PlannedItem(SEPARATOR_HEIGHT, lambda appkit, y: separator(appkit, y)))

    items.extend(
        _collapsible_section_items("pending", view_model.pending, section_state, on_rebuild)
    )

    if view_model.recovered.rows:
        items.append(_PlannedItem(SEPARATOR_HEIGHT, lambda appkit, y: separator(appkit, y)))
        items.extend(
            _collapsible_section_items("recovered", view_model.recovered, section_state, on_rebuild)
        )

    items.append(_PlannedItem(SEPARATOR_HEIGHT, lambda appkit, y: separator(appkit, y)))
    items.extend(
        _static_section_items(
            "configuration",
            CONFIGURATION_TITLE,
            view_model.configuration,
            section_state,
            on_rebuild,
        )
    )
    items.extend(
        _static_section_items(
            "diagnostics",
            DIAGNOSTICS_TITLE,
            (*view_model.readiness, *view_model.diagnostics),
            section_state,
            on_rebuild,
        )
    )

    # Gotcha 1: tooltips are the only guidance left with no menu — fall back
    # to one here since `SidebarViewModel.quit` doesn't carry one.
    quit_row = replace(
        view_model.quit, action=on_quit, tooltip=view_model.quit.tooltip or "Quit Meeting Memory"
    )
    items.append(_PlannedItem(SEPARATOR_HEIGHT, lambda appkit, y: separator(appkit, y)))
    items.append(_PlannedItem(ROW_HEIGHT, lambda appkit, y: row(appkit, quit_row, y)))
    return items


def _row_items(rows: tuple[Any, ...]) -> list[_PlannedItem]:
    return [_PlannedItem(ROW_HEIGHT, lambda appkit, y, r=r: row(appkit, r, y)) for r in rows]


def _collapsible_section_items(
    key: str,
    section: Any,
    section_state: SectionState,
    on_rebuild: Callable[[], None],
) -> list[_PlannedItem]:
    expanded = section_state.is_expanded(key)
    items = [
        _PlannedItem(
            SECTION_HEADER_HEIGHT,
            lambda appkit, y: section_header(
                appkit, section.title, expanded, y, _make_toggle(section_state, key, on_rebuild)
            ),
        )
    ]
    if not expanded:
        return items

    if section.rows:
        items.extend(_row_items(section.rows))
    elif section.empty_label is not None:
        empty_row = _DisabledRow(label=section.empty_label)
        items.append(_PlannedItem(ROW_HEIGHT, lambda appkit, y: row(appkit, empty_row, y)))
    return items


def _static_section_items(
    key: str,
    title: str,
    rows: tuple[Any, ...],
    section_state: SectionState,
    on_rebuild: Callable[[], None],
) -> list[_PlannedItem]:
    expanded = section_state.is_expanded(key)
    items = [
        _PlannedItem(
            SECTION_HEADER_HEIGHT,
            lambda appkit, y: section_header(
                appkit, title, expanded, y, _make_toggle(section_state, key, on_rebuild)
            ),
        )
    ]
    if expanded:
        items.extend(_row_items(rows))
    return items


def _make_toggle(
    section_state: SectionState, key: str, on_rebuild: Callable[[], None]
) -> Callable[[], None]:
    def _toggle() -> None:
        section_state.toggle(key)
        on_rebuild()

    return _toggle


def _title_bar(appkit: Any, y: float) -> Any:
    """Icon-colored gradient block; also a grab area (see `header_view`)."""

    bar = header_view(appkit, appkit.NSMakeRect(0.0, y, PANEL_WIDTH, TITLE_BAR_HEIGHT))
    title = appkit.NSTextField.labelWithString_(TITLE_TEXT)
    title.setFrame_(appkit.NSMakeRect(12.0, 8.0, PANEL_WIDTH - 24.0, 18.0))
    title.setTextColor_(on_header_color(appkit))
    title.setFont_(title_font(appkit))
    title.setLineBreakMode_(appkit.NSLineBreakByTruncatingTail)
    bar.addSubview_(title)
    return bar


def _fixed_header(appkit: Any, title: str, y: float) -> Any:
    container = appkit.NSView.alloc().initWithFrame_(
        appkit.NSMakeRect(0.0, y, PANEL_WIDTH, SECTION_HEADER_HEIGHT)
    )
    container.addSubview_(header_label(appkit, title, PANEL_WIDTH))
    return container
