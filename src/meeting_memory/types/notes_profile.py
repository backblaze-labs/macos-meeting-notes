"""Pure boundary types for configurable Notes generation profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

PROFILE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class NotesProfileKind(StrEnum):
    """Stable template identities exposed by the Notes workspace."""

    CLASSIC = "classic"
    PERSONAL = "personal"
    CUSTOM = "custom"


class NotesSectionFormat(StrEnum):
    """Markdown shape requested for one generated section."""

    PARAGRAPH = "paragraph"
    BULLETS = "bullets"
    CHECKLIST = "checklist"

    @property
    def label(self) -> str:
        return {
            NotesSectionFormat.PARAGRAPH: "Paragraph",
            NotesSectionFormat.BULLETS: "Bullet list",
            NotesSectionFormat.CHECKLIST: "Task checklist",
        }[self]


class NotesSectionAudience(StrEnum):
    """Whose contributions one generated section should cover."""

    MEETING = "meeting"
    EACH_PARTICIPANT = "each_participant"
    ME = "me"

    @property
    def label(self) -> str:
        return {
            NotesSectionAudience.MEETING: "Whole meeting",
            NotesSectionAudience.EACH_PARTICIPANT: "Each participant",
            NotesSectionAudience.ME: "Only me",
        }[self]


@dataclass(frozen=True, slots=True)
class NotesProfileVariable:
    """One user-provided value required by a reusable template."""

    key: str
    label: str
    value: str = ""
    required: bool = False

    def __post_init__(self) -> None:
        if not PROFILE_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("Template variable keys must use lowercase letters and underscores.")
        if not self.label.strip() or "\n" in self.label:
            raise ValueError("Template variable labels must be one non-empty line.")
        if len(self.value) > 240:
            raise ValueError("Template variable values must be 240 characters or fewer.")
        if type(self.required) is not bool:
            raise ValueError("Template variable required state must be boolean.")


@dataclass(frozen=True, slots=True)
class NotesProfileSection:
    """One configurable generated section in a Notes report."""

    key: str
    title: str
    instructions: str
    output_format: NotesSectionFormat
    audience: NotesSectionAudience

    def __post_init__(self) -> None:
        if not PROFILE_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("Section keys must use lowercase letters and underscores.")
        if not self.title.strip() or "\n" in self.title or any(c in self.title for c in "{}"):
            raise ValueError("Section titles must be one non-empty line without template fields.")
        if not self.instructions.strip():
            raise ValueError("Every section needs generation guidance.")
        if len(self.instructions) > 4_000:
            raise ValueError("Section guidance must be 4,000 characters or fewer.")
        if not isinstance(self.output_format, NotesSectionFormat):
            raise ValueError("Section output format must be typed.")
        if not isinstance(self.audience, NotesSectionAudience):
            raise ValueError("Section audience must be typed.")


@dataclass(frozen=True, slots=True)
class NotesProfile:
    """A complete, locally stored recipe for generating and rendering Notes."""

    kind: NotesProfileKind
    report_title: str
    sections: tuple[NotesProfileSection, ...]
    variables: tuple[NotesProfileVariable, ...] = ()
    include_source: bool = True
    include_date: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NotesProfileKind):
            raise ValueError("Notes profile kind must be typed.")
        if not self.report_title.strip() or "\n" in self.report_title:
            raise ValueError("Report title must be one non-empty line.")
        if not 1 <= len(self.sections) <= 8:
            raise ValueError("A Notes profile must contain between 1 and 8 sections.")
        section_keys = tuple(section.key for section in self.sections)
        variable_keys = tuple(variable.key for variable in self.variables)
        if len(set(section_keys)) != len(section_keys):
            raise ValueError("Notes profile section keys must be unique.")
        if len(set(variable_keys)) != len(variable_keys):
            raise ValueError("Notes profile variable keys must be unique.")
        if type(self.include_source) is not bool or type(self.include_date) is not bool:
            raise ValueError("Notes profile metadata choices must be boolean.")

    def variable_for(self, key: str) -> NotesProfileVariable | None:
        return next((variable for variable in self.variables if variable.key == key), None)
