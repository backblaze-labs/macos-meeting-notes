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
                backend.set_password(self.service, ref.account, payload)
                return ref
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
