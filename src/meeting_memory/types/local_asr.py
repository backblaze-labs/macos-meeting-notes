"""Validated, content-bounded language and vocabulary hints for local ASR."""

from dataclasses import dataclass

MAX_PROMPT_CHARS = 2000


def language_code(value: object) -> str | None:
    if value not in ("auto", "en", "es") or not isinstance(value, str):
        raise ValueError("language must be auto, en, or es")
    return None if value == "auto" else value


@dataclass(frozen=True, slots=True)
class LocalASROptions:
    language: str | None = None
    initial_prompt: str | None = None

    def __post_init__(self) -> None:
        if self.language is not None:
            language_code(self.language)
            if self.language == "auto":
                raise ValueError("wire language must use null for automatic detection")
        if self.initial_prompt is not None and (
            not isinstance(self.initial_prompt, str)
            or not self.initial_prompt.strip()
            or len(self.initial_prompt) > MAX_PROMPT_CHARS
            or any(ord(c) < 32 for c in self.initial_prompt)
        ):
            raise ValueError("invalid local vocabulary prompt")

    @classmethod
    def from_wire(cls, value: object) -> "LocalASROptions":
        if not isinstance(value, dict) or set(value) != {"language", "initial_prompt"}:
            raise ValueError("invalid local ASR options")
        return cls(**value)

    def to_wire(self) -> dict:
        return {"language": self.language, "initial_prompt": self.initial_prompt}


@dataclass(frozen=True, slots=True)
class LocalASRProfile:
    default_language: str | None = None
    language_overrides: tuple[tuple[str, str | None], ...] = ()
    glossary: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, value: object) -> "LocalASRProfile":
        if not isinstance(value, dict) or set(value) - {
            "default_language",
            "language_overrides",
            "glossary",
        }:
            raise ValueError("invalid local transcription profile")
        default = language_code(value.get("default_language", "auto"))
        rules = value.get("language_overrides", [])
        glossary = value.get("glossary", [])
        if not isinstance(rules, list) or len(rules) > 32:
            raise ValueError("invalid language overrides")
        overrides = []
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != {"title_contains", "language"}:
                raise ValueError("invalid language override")
            title = rule["title_contains"]
            if not isinstance(title, str) or not title.strip() or len(title) > 120:
                raise ValueError("invalid title match")
            overrides.append((title.casefold(), language_code(rule["language"])))
        if not isinstance(glossary, list) or len(glossary) > 64:
            raise ValueError("invalid glossary")
        if any(
            not isinstance(term, str) or not term.strip() or len(term) > 80 for term in glossary
        ):
            raise ValueError("invalid glossary term")
        profile = cls(default, tuple(overrides), tuple(dict.fromkeys(glossary)))
        profile.options("")  # Validate the complete composed prompt before accepting the file.
        return profile

    def options(self, meeting_title: str) -> LocalASROptions:
        language = self.default_language
        for title, override in self.language_overrides:
            if title in meeting_title.casefold():
                language = override
                break
        prompt = "Vocabulary: " + ", ".join(self.glossary) if self.glossary else None
        return LocalASROptions(language, prompt)
