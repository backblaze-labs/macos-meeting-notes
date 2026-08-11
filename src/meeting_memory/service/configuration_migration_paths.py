"""Private path anchoring for explicit legacy migration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from meeting_memory.config.schema import definitions_for
from meeting_memory.service.configuration_migration_plan import (
    MigrationPlan,
    build_migration_plan,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import AppPreferences, SettingKey
from meeting_memory.types.configuration_resolution import SettingSource
from meeting_memory.types.runtime_layout import PATH_SETTING_KEYS, RuntimeLayout


def migration_preference_values(
    values: Mapping[SettingKey, str],
    selected: tuple[Capability, ...],
    layout: RuntimeLayout,
    source_path: Path,
) -> dict[SettingKey, str]:
    """Return app-owned values with selected legacy paths made absolute."""

    result = dict(values)
    selected_keys = {
        definition.key for capability in selected for definition in definitions_for(capability)
    }
    for key in PATH_SETTING_KEYS & selected_keys & set(values):
        raw = values[key]
        if not raw.strip() or "\x00" in raw:
            continue
        result[key] = str(
            layout.resolve_setting_path(
                key,
                raw,
                SettingSource.LEGACY_ENV,
                legacy_env_path=source_path,
            )
        )
    return result


def migration_apply_plan(
    values: Mapping[SettingKey, str],
    preferences: AppPreferences,
    selected: tuple[Capability, ...],
    layout: RuntimeLayout,
    source_path: Path,
) -> MigrationPlan | None:
    plan = build_migration_plan(values, preferences)
    if not set(selected) <= set(plan.selectable):
        return None
    persisted = migration_preference_values(values, selected, layout, source_path)
    return build_migration_plan(values, preferences, preference_values=persisted)
