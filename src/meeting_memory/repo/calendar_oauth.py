"""Bounded, log-safe Google OAuth flow and exact token visibility checks."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from meeting_memory.repo.pinned_path import open_parent_directory

MAX_OAUTH_CONFIG_BYTES = 1_048_576
MAX_OAUTH_TOKEN_BYTES = 1_048_576


class TokenStore(Protocol):
    def read_token(self) -> str | None:
        raise NotImplementedError

    def write_token(self, token_json: str) -> None:
        raise NotImplementedError


class CalendarAuthorizationError(RuntimeError):
    """Authorization or token persistence failed without known activation."""


class CalendarAuthorizationUncertain(CalendarAuthorizationError):
    """A token write may be visible but could not be verified exactly."""


def authorize_calendar(
    flow_cls,
    credentials_file: Path,
    scopes: tuple[str, ...],
    token_store: TokenStore,
    *,
    timeout_seconds: int,
):
    try:
        config = _read_desktop_client(credentials_file)
        flow = flow_cls.from_client_config(config, list(scopes))
        credentials = flow.run_local_server(
            port=0,
            timeout_seconds=timeout_seconds,
            authorization_prompt_message="",
            success_message="Authorization complete. Return to Meeting Memory.",
            open_browser=True,
            prompt="consent",
        )
        token_json = credentials.to_json()
        write_verified_token(token_store, token_json)
        return credentials
    except CalendarAuthorizationError:
        raise
    except Exception:
        raise CalendarAuthorizationError("Calendar authorization failed.") from None


def write_verified_token(token_store: TokenStore, token_json: str) -> None:
    _validate_token_json(token_json)
    write_failed = False
    try:
        token_store.write_token(token_json)
    except Exception:
        write_failed = True
    try:
        observed = token_store.read_token()
    except Exception:
        raise CalendarAuthorizationUncertain("Calendar token visibility is uncertain.") from None
    if observed == token_json:
        return
    if observed is None and write_failed:
        raise CalendarAuthorizationError("Calendar token could not be saved.")
    raise CalendarAuthorizationUncertain("Calendar token visibility is uncertain.")


def _validate_token_json(token_json: str) -> None:
    if not is_valid_calendar_token_json(token_json):
        raise CalendarAuthorizationError("Calendar token is invalid.")


def is_valid_calendar_token_json(token_json: str) -> bool:
    """Validate a bounded durable Calendar grant without exposing its values."""

    try:
        encoded = token_json.encode("utf-8")
        if len(encoded) > MAX_OAUTH_TOKEN_BYTES:
            return False
        payload = json.loads(token_json, object_pairs_hook=_unique_object)
    except (TypeError, UnicodeError, json.JSONDecodeError, ValueError):
        return False
    required = ("refresh_token", "client_id", "client_secret")
    if not isinstance(payload, dict) or not all(
        isinstance(payload.get(key), str) and payload[key].strip() for key in required
    ):
        return False
    token_uri = payload.get("token_uri")
    if token_uri is not None:
        try:
            _require_google_endpoint(
                token_uri,
                {
                    "oauth2.googleapis.com": {"/token"},
                    "accounts.google.com": {"/o/oauth2/token"},
                },
            )
        except ValueError:
            return False
    scopes = payload.get("scopes")
    if scopes is not None and (
        not isinstance(scopes, list)
        or not scopes
        or not all(isinstance(scope, str) and scope.strip() for scope in scopes)
    ):
        return False
    return True


def is_valid_desktop_client_file(path: Path) -> bool:
    """Check the exact source rules used before browser authorization."""

    try:
        _read_desktop_client(path)
    except Exception:
        return False
    return True


def _read_desktop_client(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    directory_fd = open_parent_directory(path)
    try:
        descriptor = os.open(path.name, flags, dir_fd=directory_fd)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_OAUTH_CONFIG_BYTES:
                raise ValueError("OAuth configuration must be a bounded regular file")
            content = _read_bounded(descriptor)
            after = os.fstat(descriptor)
            if _identity(before) != _identity(after):
                raise ValueError("OAuth configuration changed while being read")
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)
    payload = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"installed"}:
        raise ValueError("OAuth configuration must contain one installed client")
    installed = payload["installed"]
    if not isinstance(installed, dict):
        raise ValueError("OAuth installed client is invalid")
    for key in ("client_id", "client_secret"):
        if not isinstance(installed.get(key), str) or not installed[key].strip():
            raise ValueError("OAuth installed client is incomplete")
    _require_google_endpoint(
        installed.get("auth_uri"),
        {"accounts.google.com": {"/o/oauth2/auth", "/o/oauth2/v2/auth"}},
    )
    _require_google_endpoint(
        installed.get("token_uri"),
        {
            "oauth2.googleapis.com": {"/token"},
            "accounts.google.com": {"/o/oauth2/token"},
        },
    )
    redirects = installed.get("redirect_uris")
    if (
        not isinstance(redirects, list)
        or not redirects
        or not all(_loopback_redirect(item) for item in redirects)
    ):
        raise ValueError("OAuth redirects must be loopback addresses")
    return payload


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_OAUTH_CONFIG_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > MAX_OAUTH_CONFIG_BYTES:
        raise ValueError("OAuth configuration exceeds the supported size")
    return content


def _identity(info) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _require_google_endpoint(value: object, routes: dict[str, set[str]]) -> None:
    try:
        parsed = urlsplit(value if isinstance(value, str) else "")
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("OAuth endpoint is not trusted") from None
    if (
        parsed.scheme != "https"
        or host not in routes
        or parsed.path not in routes[host]
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OAuth endpoint is not trusted")


def _loopback_redirect(value: object) -> bool:
    try:
        parsed = urlsplit(value if isinstance(value, str) else "")
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and host in {"localhost", "127.0.0.1", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.query == parsed.fragment == ""
        and (port is None or port > 0)
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("OAuth configuration has duplicate fields")
        result[key] = value
    return result
