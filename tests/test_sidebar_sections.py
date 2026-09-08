"""Tests for collapsible-section expand/collapsed state persistence."""

from __future__ import annotations

import pytest
from appkit_fakes import FakeAppKit, reset_fake_appkit_state

from meeting_memory.ui.sidebar_sections import SectionState


@pytest.fixture(autouse=True)
def _reset_appkit_state():
    reset_fake_appkit_state()
    yield
    reset_fake_appkit_state()


def test_defaults_recent_and_pending_expanded_rest_collapsed():
    state = SectionState(FakeAppKit())

    assert state.is_expanded("recent") is True
    assert state.is_expanded("pending") is True
    assert state.is_expanded("configuration") is False
    assert state.is_expanded("diagnostics") is False
    assert state.is_expanded("recovered") is False


def test_toggle_flips_and_returns_new_state():
    state = SectionState(FakeAppKit())

    assert state.toggle("configuration") is True
    assert state.is_expanded("configuration") is True
    assert state.toggle("configuration") is False
    assert state.is_expanded("configuration") is False


def test_state_round_trips_through_fake_user_defaults():
    appkit = FakeAppKit()
    state = SectionState(appkit)
    state.toggle("configuration")
    state.toggle("recent")  # collapse a default-expanded section

    restarted = SectionState(appkit)

    assert restarted.is_expanded("configuration") is True
    assert restarted.is_expanded("recent") is False
    assert restarted.is_expanded("pending") is True
