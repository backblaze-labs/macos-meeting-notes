"""Generic immutable-generation macOS Keychain secret adapter."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from meeting_memory.config.secret_payloads import decode_secret_bundle, encode_secret_bundle
from meeting_memory.types.configuration import SecretBundle, SecretMaterial, SecretRef

KEYCHAIN_SERVICE = "meeting-memory.app-secrets.v1"
MAX_SECRET_PAYLOAD_CHARS = 1_048_576
MAX_GENERATION_ATTEMPTS = 4


class SecretStoreError(RuntimeError):
    """A sanitized Keychain failure safe for capability-local handling."""


class SecretStoreCleanupUncertain(SecretStoreError):
    """A failed immutable write may have left one inactive generation."""


def _new_generation() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class KeychainSecretStore:
    """Write immutable payloads and address them through opaque references."""

    service: str = KEYCHAIN_SERVICE
    generation_factory: Callable[[], str] = field(
        default=_new_generation,
        repr=False,
        compare=False,
    )

    def write_new(self, bundle: SecretBundle) -> SecretRef:
        payload = encode_secret_bundle(bundle)
        if len(payload) > MAX_SECRET_PAYLOAD_CHARS:
            raise ValueError("secret payload must be non-empty and bounded")
        try:
            backend = _load_keyring()
            for _attempt in range(MAX_GENERATION_ATTEMPTS):
                ref = SecretRef(bundle.secret_id, self.generation_factory())
                if backend.get_password(self.service, ref.account) is not None:
                    continue
                try:
                    backend.set_password(self.service, ref.account, payload)
                except Exception:
                    if _cleanup_failed_write(backend, self.service, ref, payload):
                        continue
                    raise
                if _written_payload_matches(backend, self.service, ref, payload):
                    return ref
        except SecretStoreCleanupUncertain:
            raise
        except Exception:
            raise SecretStoreError("Keychain secret could not be written.") from None
        raise SecretStoreError("Keychain secret could not allocate a new generation.")

    def read(self, ref: SecretRef) -> SecretMaterial | None:
        try:
            payload = _load_keyring().get_password(self.service, ref.account)
            if payload is None:
                return None
            if not isinstance(payload, str) or len(payload) > MAX_SECRET_PAYLOAD_CHARS:
                raise ValueError("stored Keychain payload is not bounded text")
            bundle = decode_secret_bundle(payload, expected=ref.secret_id)
            return SecretMaterial(ref, bundle)
        except Exception:
            raise SecretStoreError("Keychain secret could not be read.") from None

    def delete(self, ref: SecretRef) -> None:
        try:
            backend = _load_keyring()
            if backend.get_password(self.service, ref.account) is None:
                return
            try:
                backend.delete_password(self.service, ref.account)
            except Exception:
                if backend.get_password(self.service, ref.account) is None:
                    return
                raise
        except Exception:
            raise SecretStoreError("Keychain secret could not be deleted.") from None


def _load_keyring():
    import keyring

    return keyring


def _cleanup_failed_write(backend, service: str, ref: SecretRef, payload: str) -> bool:
    """Clean this attempt, returning true only for a preserved foreign collision."""

    try:
        observed = backend.get_password(service, ref.account)
    except Exception:
        raise SecretStoreCleanupUncertain(
            "Keychain write failed and inactive credential cleanup is uncertain."
        ) from None
    if observed is None:
        return False
    if observed != payload:
        return True
    try:
        backend.delete_password(service, ref.account)
    except Exception:
        try:
            if backend.get_password(service, ref.account) is None:
                return False
        except Exception:
            # The sanitized cleanup-uncertain error below remains authoritative.
            pass
        raise SecretStoreCleanupUncertain(
            "Keychain write failed and inactive credential cleanup is uncertain."
        ) from None
    try:
        if backend.get_password(service, ref.account) is not None:
            raise RuntimeError("credential cleanup was not visible")
    except Exception:
        raise SecretStoreCleanupUncertain(
            "Keychain write failed and inactive credential cleanup is uncertain."
        ) from None
    return False


def _written_payload_matches(backend, service: str, ref: SecretRef, payload: str) -> bool:
    try:
        return backend.get_password(service, ref.account) == payload
    except Exception:
        raise SecretStoreCleanupUncertain(
            "Keychain write could not be verified and inactive cleanup is uncertain."
        ) from None
