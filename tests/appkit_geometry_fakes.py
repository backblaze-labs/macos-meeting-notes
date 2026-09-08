"""Fake `NSPoint`/`NSSize`/`NSRect` — shared by `appkit_fakes.py` (panel/drag)
and `appkit_widget_fakes.py` (vertical-layout widgets) so neither imports the
other."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakePoint:
    x: float
    y: float


@dataclass
class FakeSize:
    width: float
    height: float


@dataclass
class FakeRect:
    origin: FakePoint
    size: FakeSize


def fake_make_rect(x: float, y: float, width: float, height: float) -> FakeRect:
    return FakeRect(FakePoint(x, y), FakeSize(width, height))


def fake_make_point(x: float, y: float) -> FakePoint:
    return FakePoint(x, y)
