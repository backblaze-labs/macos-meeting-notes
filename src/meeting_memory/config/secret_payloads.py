"""Sanitized serialization for typed immutable Keychain payloads."""

from __future__ import annotations

import json

from meeting_memory.types.configuration import (
    SCHEMA_VERSION,
    SecretBundle,
    SecretId,
    SecretValue,
    SettingKey,
)


class SecretPayloadError(ValueError):
    """A stored credential is malformed without exposing its content."""


def encode_secret_bundle(bundle: SecretBundle) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "secret_id": bundle.secret_id.value,
        "values": {item.key.value: item.value for item in bundle.values},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def decode_secret_bundle(payload: str, *, expected: SecretId) -> SecretBundle:
    try:
        if not isinstance(expected, SecretId):
            raise ValueError("invalid expected provider")
        document = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(document, dict) or set(document) != {
            "schema_version",
            "secret_id",
            "values",
        }:
            raise ValueError("invalid payload shape")
        if (
            type(document["schema_version"]) is not int
            or document["schema_version"] != SCHEMA_VERSION
        ):
            raise ValueError("unsupported payload schema")
        if SecretId(str(document["secret_id"])) is not expected:
            raise ValueError("payload provider mismatch")
        raw_values = document["values"]
        if not isinstance(raw_values, dict) or not all(
            isinstance(value, str) for value in raw_values.values()
        ):
            raise ValueError("invalid payload values")
        values = tuple(
            SecretValue(SettingKey(str(key)), value) for key, value in raw_values.items()
        )
        return SecretBundle(expected, values)
    except Exception:
        raise SecretPayloadError("Stored credential could not be decoded.") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
