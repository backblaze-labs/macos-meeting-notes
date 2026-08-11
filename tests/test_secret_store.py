"""Immutable generic Keychain adapter tests."""

from __future__ import annotations

import pytest

from meeting_memory.repo import calendar_client, secret_store
from meeting_memory.repo.secret_store import (
    KeychainSecretStore,
    SecretStoreCleanupUncertain,
    SecretStoreError,
)
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


def test_late_write_failure_cleans_exact_new_payload_and_preserves_foreign_collision(
    monkeypatch,
) -> None:
    backend = LateFailureKeyring()
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    store = KeychainSecretStore(generation_factory=lambda: "1" * 32)

    backend.late_value = None
    with pytest.raises(SecretStoreError):
        store.write_new(_notes_bundle("intended"))
    assert backend.values == {}

    backend = LateFailureKeyring()
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    generations = iter(("2" * 32, "3" * 32))
    store = KeychainSecretStore(generation_factory=lambda: next(generations))
    backend.late_value = "foreign-payload"
    ref = store.write_new(_notes_bundle("intended"))
    assert backend.values[(store.service, f"notes:{'2' * 32}")] == "foreign-payload"
    assert ref == SecretRef(SecretId.NOTES, "3" * 32)
    assert _secret(store, ref, SettingKey.ANTHROPIC_API_KEY) == "intended"


def test_late_write_cleanup_failure_is_typed_and_sanitized(monkeypatch) -> None:
    backend = LateFailureKeyring()
    backend.late_value = None
    backend.fail_delete = True
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    store = KeychainSecretStore(generation_factory=lambda: "3" * 32)

    with pytest.raises(SecretStoreCleanupUncertain) as error:
        store.write_new(_notes_bundle("intended"))

    assert "intended" not in str(error.value)


def test_late_write_noop_cleanup_is_uncertain_and_preserves_account(monkeypatch) -> None:
    backend = LateFailureKeyring()
    backend.noop_delete = True
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: backend)
    store = KeychainSecretStore(generation_factory=lambda: "4" * 32)

    with pytest.raises(SecretStoreCleanupUncertain) as error:
        store.write_new(_notes_bundle("secret-sentinel"))

    assert backend.values[(store.service, f"notes:{'4' * 32}")]
    assert "secret-sentinel" not in str(error.value)


def test_nominal_noop_or_wrong_payload_never_returns_an_activatable_ref(monkeypatch) -> None:
    noop = NominalAnomalyKeyring("noop")
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: noop)
    generations = iter(f"{number:032x}" for number in range(10, 14))
    store = KeychainSecretStore(generation_factory=lambda: next(generations))

    with pytest.raises(SecretStoreError):
        store.write_new(_notes_bundle("secret-sentinel"))

    assert noop.set_calls == secret_store.MAX_GENERATION_ATTEMPTS
    assert noop.values == {}

    wrong = NominalAnomalyKeyring("wrong-once")
    monkeypatch.setattr(secret_store, "_load_keyring", lambda: wrong)
    generations = iter(("a" * 32, "b" * 32))
    store = KeychainSecretStore(generation_factory=lambda: next(generations))

    ref = store.write_new(_notes_bundle("secret-sentinel"))

    assert wrong.values[(store.service, f"notes:{'a' * 32}")] == "foreign-payload"
    assert ref == SecretRef(SecretId.NOTES, "b" * 32)
    assert _secret(store, ref, SettingKey.ANTHROPIC_API_KEY) == "secret-sentinel"


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
    backend.values[(store.service, ref.account)] = "x" * (secret_store.MAX_SECRET_PAYLOAD_CHARS + 1)

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


class LateFailureKeyring(FakeKeyring):
    def __init__(self) -> None:
        super().__init__()
        self.late_value: str | None = None
        self.fail_delete = False
        self.noop_delete = False
        self.fail_once = True

    def set_password(self, service: str, account: str, payload: str) -> None:
        if self.fail_once:
            self.fail_once = False
            self.values[(service, account)] = (
                payload if self.late_value is None else self.late_value
            )
            raise RuntimeError("late backend failure")
        super().set_password(service, account, payload)

    def delete_password(self, service: str, account: str) -> None:
        if self.noop_delete:
            return
        if self.fail_delete:
            raise RuntimeError("delete failure")
        super().delete_password(service, account)


class NominalAnomalyKeyring(FakeKeyring):
    def __init__(self, behavior: str) -> None:
        super().__init__()
        self.behavior = behavior
        self.set_calls = 0

    def set_password(self, service: str, account: str, payload: str) -> None:
        self.set_calls += 1
        if self.behavior == "noop":
            return
        if self.behavior == "wrong-once" and self.set_calls == 1:
            self.values[(service, account)] = "foreign-payload"
            return
        super().set_password(service, account, payload)


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
