"""Bounded read-only sources for effective configuration composition."""

from __future__ import annotations

import os
import queue
import stat
import threading
import time
from collections.abc import Callable
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values

from meeting_memory.repo.secret_store import KeychainSecretStore
from meeting_memory.service.preference_store import PreferenceStore
from meeting_memory.types.configuration import (
    AppPreferences,
    PreferenceSnapshot,
    SecretId,
    SecretMaterial,
    SecretRef,
)

MAX_LEGACY_ENV_BYTES = 1_048_576
SECRET_READ_TIMEOUT_SECONDS = 5.0
PreferenceReader = Callable[[], PreferenceSnapshot]
SecretReader = Callable[[SecretRef], SecretMaterial | None]


def load_legacy_environment(
    env_file: str | Path | None,
) -> tuple[dict[str, str], bool]:
    """Read one compatible dotenv snapshot without exposing parser failures."""

    if env_file is None:
        return {}, False
    try:
        content = _read_bounded_regular(Path(env_file))
        if content is None:
            return {}, False
        parsed = dotenv_values(stream=StringIO(content), interpolate=False)
        normalized = {
            str(key): "" if value is None else str(value) for key, value in parsed.items()
        }
        return normalized, False
    except Exception:
        return {}, True


def load_preferences(
    reader: PreferenceReader | None,
) -> tuple[AppPreferences | None, bool]:
    """Distinguish missing valid preferences from an unreadable document."""

    try:
        snapshot = (reader or PreferenceStore.default().load_snapshot)()
        if not isinstance(snapshot, PreferenceSnapshot):
            raise TypeError("preference reader returned an invalid snapshot")
        return snapshot.preferences, False
    except Exception:
        return None, True


def read_secret_materials(
    refs: tuple[SecretRef, ...],
    reader: SecretReader | None,
) -> tuple[tuple[SecretMaterial, ...], frozenset[SecretId]]:
    """Read exact immutable refs in parallel under one total deadline."""

    if not refs:
        return (), frozenset()
    try:
        read = reader or KeychainSecretStore().read
    except Exception:
        return (), frozenset(ref.secret_id for ref in refs)
    outcomes: queue.Queue[tuple[SecretRef, SecretMaterial | None]] = queue.Queue()
    failed: set[SecretId] = set()
    pending = set(refs)

    def run(ref: SecretRef) -> None:
        try:
            material = read(ref)
            if material is not None and material.ref != ref:
                material = None
            outcomes.put((ref, material))
        except Exception:
            outcomes.put((ref, None))

    for ref in refs:
        try:
            threading.Thread(target=run, args=(ref,), daemon=True).start()
        except Exception:
            pending.discard(ref)
            failed.add(ref.secret_id)
    deadline = time.monotonic() + SECRET_READ_TIMEOUT_SECONDS
    materials: list[SecretMaterial] = []
    while pending:
        try:
            timeout = max(0.0, deadline - time.monotonic())
            ref, material = outcomes.get(timeout=timeout)
        except queue.Empty:
            failed.update(ref.secret_id for ref in pending)
            break
        if ref not in pending:
            continue
        pending.remove(ref)
        if material is None:
            failed.add(ref.secret_id)
        else:
            materials.append(material)
    return tuple(materials), frozenset(failed)


def _read_bounded_regular(path: Path) -> str | None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_LEGACY_ENV_BYTES:
            raise OSError("legacy environment file is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = MAX_LEGACY_ENV_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > MAX_LEGACY_ENV_BYTES:
            raise OSError("legacy environment file is too large")
        return content.decode("utf-8")
    finally:
        os.close(descriptor)
