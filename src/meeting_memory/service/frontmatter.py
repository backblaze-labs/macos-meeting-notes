"""Small frontmatter helpers for the meeting markdown format."""

from __future__ import annotations

import json
from collections.abc import Mapping

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


def dump_frontmatter(values: Mapping[str, object]) -> str:
    lines = ["---"]
    for key in FRONTMATTER_FIELDS:
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


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list | tuple):
        return json.dumps(list(value))
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
    if raw_value.startswith(('"', "[")):
        return json.loads(raw_value)
    if raw_value.isdigit():
        return int(raw_value)
    return raw_value
