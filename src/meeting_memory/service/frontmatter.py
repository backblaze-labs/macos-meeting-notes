"""Small frontmatter helpers for the meeting markdown format."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

FRONTMATTER_FIELDS = (
    "id",
    "date",
    "duration_minutes",
    "calendar_title",
    "participants",
    "assemblyai_id",
    "summary_status",
    "b2_audio",
    "b2_transcript",
    "b2_status",
)


def dump_frontmatter(
    values: Mapping[str, object],
    *,
    fields: Sequence[str] | None = None,
) -> str:
    lines = ["---"]
    for key in _ordered_fields(values, fields):
        lines.append(f"{key}: {_format_value(values.get(key))}")
    lines.append("---")
    return "\n".join(lines)


def split_frontmatter(markdown: str) -> tuple[dict[str, object], str]:
    lines = markdown.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("meeting markdown is missing YAML frontmatter")

    try:
        end_index = lines[1:].index("---") + 1
    except ValueError as exc:
        raise ValueError("meeting markdown frontmatter is not closed") from exc

    frontmatter = _parse_lines(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    if markdown.endswith("\n"):
        body += "\n"
    return frontmatter, body


def replace_frontmatter(markdown: str, values: Mapping[str, object]) -> str:
    _, body = split_frontmatter(markdown)
    return f"{dump_frontmatter(values)}\n{body}"


def merge_frontmatter_fields(markdown: str, updates: Mapping[str, object]) -> str:
    """Replace selected top-level scalar fields while preserving all other text."""

    split_frontmatter(markdown)
    lines = markdown.splitlines(keepends=True)
    closing_index = next(
        index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"
    )
    remaining = dict(updates)
    for index in range(1, closing_index):
        line = lines[index]
        if line[:1].isspace() or ":" not in line:
            continue
        key = line.split(":", 1)[0]
        if key not in remaining:
            continue
        ending = "\r\n" if line.endswith("\r\n") else "\n"
        lines[index] = f"{key}: {_format_value(remaining.pop(key))}{ending}"
    for key, value in remaining.items():
        lines.insert(closing_index, f"{key}: {_format_value(value)}\n")
        closing_index += 1
    return "".join(lines)


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list | tuple):
        return json.dumps(list(value))
    if isinstance(value, dict):
        return json.dumps(value)
    return json.dumps(str(value))


def _parse_lines(lines: list[str]) -> dict[str, object]:
    values: dict[str, object] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        values[key.strip()] = _parse_value(raw_value.strip())
    return values


def _parse_value(raw_value: str) -> object:
    if raw_value == "null":
        return None
    if raw_value.startswith(('"', "[", "{")):
        return json.loads(raw_value)
    if raw_value.isdigit():
        return int(raw_value)
    return raw_value


def _ordered_fields(
    values: Mapping[str, object],
    fields: Sequence[str] | None,
) -> tuple[str, ...]:
    if fields is not None:
        return tuple(fields)

    ordered = list(FRONTMATTER_FIELDS)
    for key in values:
        if key not in ordered:
            ordered.append(key)
    return tuple(key for key in ordered if key in values)
