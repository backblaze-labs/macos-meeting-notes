"""Immutable generic Keychain adapter tests."""

from __future__ import annotations

import pytest

from meeting_memory.repo import calendar_client, secret_store
from meeting_memory.repo.secret_store import KeychainSecretStore, SecretStoreError
from meeting_memory.types.configuration import (
    SecretBundle,
    SecretId,
    SecretRef,
    SecretValue,
    SettingKey,
)


def test_generic_service_is_distinct_from_google_oauth_and_uses_versioned_accounts(
    monkeypatch,
) -> None:
    backend = FakeKeyring()
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    generations = iter(("a" * 32, "b" * 32))
    store = KeychainSecretStore(generation_factory=lambda: next(generations))

    first = store.write_new(_backup_bundle("first"))
    second = store.write_new(_backup_bundle("second"))

    assert store.service != calendar_client.KEYCHAIN_SERVICE
    assert first != second
    assert first.account == f"backup:{'a' * 32}"
    assert _secret(store, first, SettingKey.B2_APPLICATION_KEY) == "first-key"
    assert _secret(store, second, SettingKey.B2_APPLICATION_KEY) == "second-key"
    assert len(backend.values) == 2


def test_delete_is_exact_and_idempotent(monkeypatch) -> None:
    backend = FakeKeyring()
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    store = KeychainSecretStore(generation_factory=lambda: "c" * 32)
    ref = store.write_new(_notes_bundle("secret"))
    other = SecretRef(SecretId.NOTES, "d" * 32)
    backend.values[(store.service, other.account)] = secret_store.encode_secret_bundle(
        _notes_bundle("other")
    )

    store.delete(ref)
    store.delete(ref)

    assert store.read(ref) is None
    assert _secret(store, other, SettingKey.ANTHROPIC_API_KEY) == "other"


def test_failed_new_write_never_overwrites_an_active_generation(monkeypatch) -> None:
    backend = FakeKeyring()
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    generations = iter(("e" * 32, "f" * 32))
    store = KeychainSecretStore(generation_factory=lambda: next(generations))
    active = store.write_new(_transcription_bundle("active-secret"))
    backend.fail_next_write = True

    with pytest.raises(SecretStoreError) as error:
        store.write_new(_transcription_bundle("new-secret"))

    assert _secret(store, active, SettingKey.ASSEMBLYAI_API_KEY) == "active-secret"
    assert len(backend.values) == 1
    assert "backend failed" not in str(error.value)


def test_generation_collision_never_overwrites_existing_payload(monkeypatch) -> None:
    backend = FakeKeyring()
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    generations = iter(("a" * 32, "a" * 32, "b" * 32))
    store = KeychainSecretStore(generation_factory=lambda: next(generations))

    first = store.write_new(_notes_bundle("first"))
    second = store.write_new(_notes_bundle("second"))

    assert _secret(store, first, SettingKey.ANTHROPIC_API_KEY) == "first"
    assert _secret(store, second, SettingKey.ANTHROPIC_API_KEY) == "second"


def test_payload_is_bounded_and_never_appears_in_store_repr() -> None:
    payload = "secret-sentinel"
    store = KeychainSecretStore(generation_factory=lambda: "a" * 32)

    assert payload not in repr(store)
    with pytest.raises(ValueError, match="bounded") as error:
        store.write_new(_notes_bundle("x" * (secret_store.MAX_SECRET_PAYLOAD_CHARS + 1)))
    assert payload not in str(error.value)


def test_read_rejects_mismatched_typed_payload_without_echoing_it(monkeypatch) -> None:
    backend = FakeKeyring()
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    store = KeychainSecretStore()
    ref = SecretRef(SecretId.NOTES, "f" * 32)
    sentinel = "mismatched-secret-sentinel"
    backend.values[(store.service, ref.account)] = secret_store.encode_secret_bundle(
        _transcription_bundle(sentinel)
    )

    with pytest.raises(SecretStoreError) as error:
        store.read(ref)

    assert sentinel not in str(error.value)


def test_read_rejects_oversize_payload_before_decoding(monkeypatch) -> None:
    backend = FakeKeyring()
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    monkeypatch.setattr(
        secret_store,
        "decode_secret_bundle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("oversize payload was decoded")
        ),
    )
    store = KeychainSecretStore()
    ref = SecretRef(SecretId.NOTES, "1" * 32)
    backend.values[(store.service, ref.account)] = "x" * (
        secret_store.MAX_SECRET_PAYLOAD_CHARS + 1
    )

    with pytest.raises(SecretStoreError):
        store.read(ref)


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail_next_write = False

    def set_password(self, service: str, account: str, payload: str) -> None:
        if self.fail_next_write:
            self.fail_next_write = False
            raise RuntimeError("backend failed")
        self.values[(service, account)] = payload

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def _transcription_bundle(secret: str) -> SecretBundle:
    return SecretBundle(
        SecretId.TRANSCRIPTION,
        (SecretValue(SettingKey.ASSEMBLYAI_API_KEY, secret),),
    )


def _notes_bundle(secret: str) -> SecretBundle:
    return SecretBundle(
        SecretId.NOTES,
        (SecretValue(SettingKey.ANTHROPIC_API_KEY, secret),),
    )


def _backup_bundle(prefix: str) -> SecretBundle:
    return SecretBundle(
        SecretId.BACKUP,
        (
            SecretValue(SettingKey.B2_APPLICATION_KEY_ID, f"{prefix}-id"),
            SecretValue(SettingKey.B2_APPLICATION_KEY, f"{prefix}-key"),
        ),
    )


def _secret(store, ref: SecretRef, key: SettingKey) -> str | None:
    material = store.read(ref)
    assert material is not None
    return material.bundle.value_for(key)
