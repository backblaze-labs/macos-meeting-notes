"""Atomic private storage for non-secret app configuration and secret references."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from meeting_memory.service.preference_store_fs import (
    MAX_PREFERENCES_BYTES,
    DirectorySyncUncertain,
    locked_directory,
    read_document,
    read_document_at,
    replace_document_at,
)
from meeting_memory.types.capabilities import Capability
from meeting_memory.types.configuration import (
    AppPreferences,
    CapabilityPreference,
    PreferenceKey,
    PreferenceSnapshot,
    PreferenceValue,
    SecretId,
    SecretRef,
)


class PreferencesStoreError(RuntimeError):
    """A sanitized preference-store failure safe for user-facing diagnostics."""


class PreferencesConflictError(PreferencesStoreError):
    """The preference document changed after its caller loaded it."""


class PreferencesDurabilityUncertain(PreferencesStoreError):
    """The new document is visible, but its directory entry did not flush."""

    def __init__(self, snapshot: PreferenceSnapshot) -> None:
        self.snapshot = snapshot
        super().__init__("App preferences were replaced, but durability is uncertain.")


def default_preferences_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "meeting-memory" / "preferences.json"


@dataclass(frozen=True, slots=True)
class PreferenceStore:
    """Load and atomically compare-and-swap an allowlisted document."""

    path: Path

    @classmethod
    def default(cls) -> PreferenceStore:
        return cls(default_preferences_path())

    def load(self) -> AppPreferences:
        return self.load_snapshot().preferences

    def load_snapshot(self) -> PreferenceSnapshot:
        try:
            return _snapshot(read_document(self.path))
        except Exception:
            raise PreferencesStoreError("App preferences could not be loaded.") from None

    def save(self, preferences: AppPreferences) -> PreferenceSnapshot:
        """Create the first document; later writers must use compare-and-swap."""

        content = _encode_preferences(preferences)
        snapshot = _snapshot(content)
        try:
            with locked_directory(self.path) as (directory_fd, filename):
                if read_document_at(directory_fd, filename) is not None:
                    raise PreferencesConflictError(
                        "App preferences already exist; reload before saving."
                    )
                replace_document_at(directory_fd, filename, content)
        except PreferencesConflictError:
            raise
        except DirectorySyncUncertain:
            raise PreferencesDurabilityUncertain(snapshot) from None
        except Exception:
            raise PreferencesStoreError("App preferences could not be saved.") from None
        return snapshot

    def compare_and_swap(
        self,
        expected: PreferenceSnapshot,
        replacement: AppPreferences,
    ) -> PreferenceSnapshot:
        content = _encode_preferences(replacement)
        snapshot = _snapshot(content)
        try:
            with locked_directory(self.path) as (directory_fd, filename):
                current = _snapshot(read_document_at(directory_fd, filename))
                if current.revision != expected.revision:
                    raise PreferencesConflictError("App preferences changed; reload before saving.")
                replace_document_at(directory_fd, filename, content)
        except (PreferencesConflictError, PreferencesDurabilityUncertain):
            raise
        except DirectorySyncUncertain:
            raise PreferencesDurabilityUncertain(snapshot) from None
        except Exception:
            raise PreferencesStoreError("App preferences could not be saved.") from None
        return snapshot


def _snapshot(content: bytes | None) -> PreferenceSnapshot:
    if content is None:
        return PreferenceSnapshot(AppPreferences(), None)
    return PreferenceSnapshot(
        _decode_preferences(content),
        hashlib.sha256(content).hexdigest(),
    )


def _encode_preferences(preferences: AppPreferences) -> bytes:
    payload = {
        "schema_version": preferences.schema_version,
        "capabilities": {item.capability.value: item.enabled for item in preferences.capabilities},
        "values": {item.key.value: item.value for item in preferences.values},
        "secret_refs": {ref.secret_id.value: ref.generation for ref in preferences.secret_refs},
    }
    content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(content) > MAX_PREFERENCES_BYTES:
        raise PreferencesStoreError("App preferences exceed the supported size.")
    return content


def _decode_preferences(content: bytes) -> AppPreferences:
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "capabilities",
            "values",
            "secret_refs",
        }:
            raise ValueError("invalid preference document")
        version = payload["schema_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("invalid preference schema")
        return AppPreferences(
            _decode_values(payload["values"]),
            _decode_capabilities(payload["capabilities"]),
            _decode_refs(payload["secret_refs"]),
            version,
        )
    except Exception:
        raise PreferencesStoreError("App preferences could not be loaded.") from None


def _decode_capabilities(value: object) -> tuple[CapabilityPreference, ...]:
    if not isinstance(value, dict):
        raise ValueError("invalid capability preferences")
    results = []
    for raw_capability, enabled in value.items():
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("invalid capability preference")
        results.append(CapabilityPreference(Capability(str(raw_capability)), enabled))
    return tuple(results)


def _decode_values(value: object) -> tuple[PreferenceValue, ...]:
    if not isinstance(value, dict) or not all(isinstance(item, str) for item in value.values()):
        raise ValueError("invalid preference values")
    return tuple(PreferenceValue(PreferenceKey(str(key)), item) for key, item in value.items())


def _decode_refs(value: object) -> tuple[SecretRef, ...]:
    if not isinstance(value, dict) or not all(isinstance(item, str) for item in value.values()):
        raise ValueError("invalid secret references")
    return tuple(
        SecretRef(SecretId(str(secret_id)), generation) for secret_id, generation in value.items()
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
