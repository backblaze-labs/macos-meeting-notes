"""Speaker candidate helpers for Google Calendar attendees."""

from __future__ import annotations

import re
from collections.abc import Iterable

TEAM_SPEAKER_ALIASES = ("Alex", "Blair", "Casey", "Drew")
TEAM_ALIAS_KEYS = {
    "alex": "Alex",
    "blair": "Blair",
    "casey": "Casey",
    "casey": "Casey",
    "jd": "Drew",
}


def speaker_candidates_from_event(
    item: dict[str, object],
    team_aliases: tuple[str, ...] = (),
) -> tuple[str, ...]:
    attendees = item.get("attendees")
    if not isinstance(attendees, list):
        return ()

    aliases = _team_aliases(team_aliases)
    candidates: list[str] = []
    for attendee in attendees:
        if not isinstance(attendee, dict) or _skip_attendee(attendee):
            continue
        candidate = _candidate_for_attendee(attendee, aliases)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _team_aliases(configured_aliases: Iterable[str]) -> tuple[str, ...]:
    aliases: list[str] = []
    for raw_alias in (*TEAM_SPEAKER_ALIASES, *configured_aliases):
        alias = TEAM_ALIAS_KEYS.get(_match_key(str(raw_alias)))
        if alias and alias not in aliases:
            aliases.append(alias)
    return tuple(aliases)


def _skip_attendee(attendee: dict[str, object]) -> bool:
    if attendee.get("resource") is True:
        return True
    return str(attendee.get("responseStatus") or "").casefold() == "declined"


def _candidate_for_attendee(
    attendee: dict[str, object],
    team_aliases: tuple[str, ...],
) -> str | None:
    names = _attendee_names(attendee)
    for alias in team_aliases:
        if _attendee_matches_alias(attendee, alias, names):
            return alias
    return names[0] if names else _name_from_email(str(attendee.get("email") or ""))


def _attendee_matches_alias(
    attendee: dict[str, object],
    alias: str,
    names: tuple[str, ...],
) -> bool:
    alias_keys = _alias_keys(alias)
    if any(_name_matches_alias(name, alias_keys) for name in names):
        return True
    return _email_matches_alias(
        str(attendee.get("email") or ""),
        alias_keys,
        allow_initial_fallback=not names,
    )


def _attendee_names(attendee: dict[str, object]) -> tuple[str, ...]:
    names: list[str] = []
    for field_name in ("displayName", "name"):
        name = _clean_name(str(attendee.get(field_name) or ""))
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _clean_name(value: str) -> str:
    name = re.sub(r"\s+", " ", value).strip()
    if not name or ("@" in name and " " not in name):
        return ""
    return name


def _name_matches_alias(value: str, alias_keys: set[str]) -> bool:
    tokens = [_match_key(token) for token in re.split(r"\W+", value) if token]
    return any(key in tokens or key == _initials(tokens) for key in alias_keys)


def _email_matches_alias(
    value: str,
    alias_keys: set[str],
    *,
    allow_initial_fallback: bool,
) -> bool:
    local_part = value.split("@", 1)[0].split("+", 1)[0]
    tokens = [_match_key(token) for token in re.split(r"[._+\-\W]+", local_part) if token]
    local_key = _match_key(local_part)
    for key in alias_keys:
        if key in tokens or key == local_key or local_key.startswith(key):
            return True
        if allow_initial_fallback and len(key) >= 3 and local_key.startswith(key[0]):
            return True
        if key == _initials(tokens):
            return True
    return False


def _name_from_email(value: str) -> str | None:
    email = value.strip()
    if not email:
        return None
    local_part = email.split("@", 1)[0].split("+", 1)[0]
    tokens = [token for token in re.split(r"[._\-\s]+", local_part) if token]
    if len(tokens) < 2:
        return email
    return " ".join(_title_token(token) for token in tokens)


def _title_token(value: str) -> str:
    return value[:1].upper() + value[1:].lower()


def _alias_keys(alias: str) -> set[str]:
    key = _match_key(alias)
    return {
        candidate for candidate, canonical in TEAM_ALIAS_KEYS.items() if canonical == alias
    } | {key}


def _initials(tokens: Iterable[str]) -> str:
    return "".join(token[:1] for token in tokens if token)


def _match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())
