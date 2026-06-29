"""Speaker candidate helpers for Google Calendar attendees."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from meeting_memory.types.speakers import KnownSpeaker

TEAM_SPEAKER_ALIASES: tuple[str, ...] = ()
TEAM_ALIAS_KEYS: dict[str, str] = {}
KNOWN_SPEAKER_MATCH_SEPARATORS = re.compile(r"[|;]")


@dataclass(frozen=True)
class _SpeakerMatcher:
    name: str
    keys: tuple[str, ...]
    emails: tuple[str, ...] = ()


def speaker_candidates_from_event(
    item: dict[str, object],
    team_aliases: Iterable[KnownSpeaker | str] = (),
) -> tuple[str, ...]:
    attendees = item.get("attendees")
    if not isinstance(attendees, list):
        return ()

    known_speakers = _known_speakers(team_aliases)
    candidates: list[str] = []
    for attendee in attendees:
        if not isinstance(attendee, dict) or _skip_attendee(attendee):
            continue
        candidate = _candidate_for_attendee(attendee, known_speakers)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _known_speakers(
    configured_aliases: Iterable[KnownSpeaker | str],
) -> tuple[_SpeakerMatcher, ...]:
    known_speakers: list[_SpeakerMatcher] = []
    seen_names: set[str] = set()
    for raw_alias in (*TEAM_SPEAKER_ALIASES, *configured_aliases):
        known_speaker = _known_speaker(raw_alias)
        if known_speaker and known_speaker.name not in seen_names:
            known_speakers.append(known_speaker)
            seen_names.add(known_speaker.name)
    return tuple(known_speakers)


def _known_speaker(raw_alias: KnownSpeaker | str) -> _SpeakerMatcher | None:
    speaker = raw_alias if isinstance(raw_alias, KnownSpeaker) else _legacy_known_speaker(raw_alias)
    if speaker is None:
        return None

    display = TEAM_ALIAS_KEYS.get(_match_key(speaker.name), speaker.name)
    if not display:
        return None

    team_keys = [
        candidate for candidate, canonical in TEAM_ALIAS_KEYS.items() if canonical == display
    ]
    keys: list[str] = []
    emails: list[str] = []
    for value in (display, *speaker.matches, *team_keys):
        emails.extend(_email_values(value))
        keys.extend(_match_keys(value))
    return _SpeakerMatcher(display, tuple(dict.fromkeys(keys)), tuple(dict.fromkeys(emails)))


def _legacy_known_speaker(raw_alias: str) -> KnownSpeaker | None:
    display, match_values = _split_known_speaker(str(raw_alias))
    return KnownSpeaker(display, match_values) if display else None


def _split_known_speaker(raw_alias: str) -> tuple[str, tuple[str, ...]]:
    value = raw_alias.strip()
    if not value:
        return "", ()

    name, separator, raw_matches = value.partition("=")
    match_values = _split_match_values(raw_matches) if separator else ()
    if not match_values:
        match = re.fullmatch(r"(.+?)\s*<([^>]+)>", name.strip())
        if match:
            return match.group(1).strip(), (match.group(2).strip(),)
    return name.strip(), match_values


def _split_match_values(raw_matches: str) -> tuple[str, ...]:
    return tuple(
        value.strip()
        for value in KNOWN_SPEAKER_MATCH_SEPARATORS.split(raw_matches)
        if value.strip()
    )


def _skip_attendee(attendee: dict[str, object]) -> bool:
    if attendee.get("resource") is True:
        return True
    return str(attendee.get("responseStatus") or "").casefold() == "declined"


def _candidate_for_attendee(
    attendee: dict[str, object],
    known_speakers: tuple[_SpeakerMatcher, ...],
) -> str | None:
    names = _attendee_names(attendee)
    for known_speaker in known_speakers:
        if _attendee_matches_known_speaker(attendee, known_speaker, names):
            return known_speaker.name
    return names[0] if names else _name_from_email(str(attendee.get("email") or ""))


def _attendee_matches_known_speaker(
    attendee: dict[str, object],
    known_speaker: _SpeakerMatcher,
    names: tuple[str, ...],
) -> bool:
    if any(_name_matches_alias(name, known_speaker.keys) for name in names):
        return True
    return _email_matches_known_speaker(
        str(attendee.get("email") or ""),
        known_speaker,
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


def _name_matches_alias(value: str, alias_keys: Iterable[str]) -> bool:
    tokens = [_match_key(token) for token in re.split(r"\W+", value) if token]
    return any(key in tokens or key == _initials(tokens) for key in alias_keys)


def _email_matches_known_speaker(
    value: str,
    known_speaker: _SpeakerMatcher,
) -> bool:
    email = value.strip().casefold()
    if not email:
        return False

    local_part = email.split("@", 1)[0].split("+", 1)[0]
    tokens = _email_local_tokens(local_part)
    local_key = _match_key(local_part)
    if email in known_speaker.emails:
        return True
    for key in known_speaker.keys:
        if key in tokens or key == local_key or local_key.startswith(key):
            return True
        if key == _initials(tokens):
            return True
    return False


def _match_keys(value: str) -> tuple[str, ...]:
    text = value.strip()
    if not text:
        return ()

    local_part = text.split("@", 1)[0].split("+", 1)[0] if "@" in text else text
    tokens = [_match_key(token) for token in re.split(r"[._+\-\W]+", local_part) if token]
    keys = [_match_key(local_part), *tokens]
    if len(tokens) > 1:
        keys.append(_initials(tokens))
    return tuple(key for key in dict.fromkeys(keys) if key)


def _email_values(value: str) -> tuple[str, ...]:
    text = value.strip().casefold()
    return (text,) if "@" in text else ()


def _email_local_tokens(local_part: str) -> tuple[str, ...]:
    return tuple(_match_key(token) for token in re.split(r"[._+\-\W]+", local_part) if token)


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


def _initials(tokens: Iterable[str]) -> str:
    return "".join(token[:1] for token in tokens if token)


def _match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())
