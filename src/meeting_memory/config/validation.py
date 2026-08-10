"""Pure validation shared by precedence, composition, and readiness."""

from __future__ import annotations

from urllib.parse import urlsplit

from meeting_memory.config.settings import looks_placeholder
from meeting_memory.types.configuration import SettingKey


def configured_value(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, str):
        return True
    return not looks_placeholder(value)


def valid_required_setting(key: SettingKey, value: object) -> bool:
    """Validate one required setting without consulting lower-priority sources."""

    if not configured_value(value):
        return False
    if key is SettingKey.B2_ENDPOINT:
        return valid_b2_endpoint(value)
    return True


def valid_b2_endpoint(value: object) -> bool:
    """Accept a bounded HTTPS origin without userinfo or routing components."""

    try:
        endpoint = urlsplit(str(value))
        host = endpoint.hostname
        port = endpoint.port
    except (TypeError, ValueError):
        return False
    if (
        endpoint.scheme != "https"
        or not host
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
        or (port is not None and port < 1)
    ):
        return False
    hostname = host.rstrip(".")
    labels = hostname.split(".")
    return len(hostname) <= 253 and all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    )
