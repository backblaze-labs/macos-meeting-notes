"""Pure captured filesystem roots for checkout and bundled execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from meeting_memory.types.configuration import SettingKey
from meeting_memory.types.configuration_resolution import SettingSource

APP_SUPPORT_DIRECTORY = Path("Library/Application Support/meeting-memory")
NATIVE_HELPER_NAME = "MeetingMemoryCapture"
NATIVE_ENCODER_NAME = "MeetingMemoryFFmpegAudioEncoder"
PATH_SETTING_KEYS = frozenset(
    {
        SettingKey.MEETINGS_DIR,
        SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE,
        SettingKey.SUMMARY_PROMPT_FILE,
    }
)


class RuntimeMode(StrEnum):
    """Stable execution modes with different trusted filesystem roots."""

    CHECKOUT = "checkout"
    BUNDLED = "bundled"


class RelativeRuntimePathError(ValueError):
    """A relative external path has no trustworthy bundled source root."""


@dataclass(frozen=True, slots=True)
class RuntimeLayout:
    """Process-wide roots captured without consulting the ambient cwd."""

    mode: RuntimeMode
    home: Path
    project_root: Path | None
    bundle_root: Path | None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RuntimeMode):
            raise ValueError("runtime layout requires a typed mode")
        for root in (self.home, self.project_root, self.bundle_root):
            if root is not None and (not isinstance(root, Path) or not root.is_absolute()):
                raise ValueError("runtime layout roots must be absolute paths")
        if self.mode is RuntimeMode.CHECKOUT:
            if self.project_root is None or self.bundle_root is not None:
                raise ValueError("checkout layout requires only a project root")
        elif self.bundle_root is None or self.project_root is not None:
            raise ValueError("bundled layout requires only an app bundle root")

    @classmethod
    def development(cls, project_root: Path, *, home: Path) -> RuntimeLayout:
        return cls(RuntimeMode.CHECKOUT, _absolute(home), _absolute(project_root), None)

    @classmethod
    def bundled(cls, bundle_root: Path, *, home: Path) -> RuntimeLayout:
        return cls(RuntimeMode.BUNDLED, _absolute(home), None, _absolute(bundle_root))

    @property
    def application_support(self) -> Path:
        return self.home / APP_SUPPORT_DIRECTORY

    @property
    def resources_path(self) -> Path:
        if self.bundle_root is not None:
            return self.bundle_root / "Contents" / "Resources"
        assert self.project_root is not None
        return self.project_root / "src" / "meeting_memory"

    @property
    def legacy_env_path(self) -> Path | None:
        return self.project_root / ".env" if self.project_root is not None else None

    @property
    def native_helper_path(self) -> Path:
        if self.bundle_root is not None:
            return self.bundle_root / "Contents" / "MacOS" / NATIVE_HELPER_NAME
        assert self.project_root is not None
        return self.project_root / ".build" / NATIVE_HELPER_NAME

    @property
    def native_encoder_path(self) -> Path:
        if self.bundle_root is not None:
            return self.bundle_root / "Contents" / "MacOS" / NATIVE_ENCODER_NAME
        assert self.project_root is not None
        return self.project_root / ".build" / NATIVE_ENCODER_NAME

    @property
    def default_prompt_path(self) -> Path:
        return self.application_support / "prompts" / "summary.md"

    @property
    def default_credentials_path(self) -> Path:
        base = self.project_root if self.project_root is not None else self.application_support
        return base / "credentials.json"

    def legacy_source_path(self, value: str | Path | None = ".env") -> Path | None:
        """Anchor a development source or reject a bundled relative selection."""

        if value is None:
            return None
        path = _expand_home(Path(value), self.home)
        if path == Path(".env"):
            return self.legacy_env_path
        if path.is_absolute():
            return _normalized(path)
        if self.project_root is not None:
            return self.resolve_checkout_path(path)
        raise RelativeRuntimePathError("bundled legacy sources must be absolute")

    def resolve_checkout_path(self, value: str | Path) -> Path:
        """Anchor one developer-only path without consulting the ambient cwd."""

        if self.project_root is None:
            raise RelativeRuntimePathError("checkout paths are unavailable when bundled")
        path = _expand_home(Path(value), self.home)
        return _normalized(path if path.is_absolute() else self.project_root / path)

    def resolve_setting_path(
        self,
        key: SettingKey,
        value: str | Path,
        source: SettingSource,
        *,
        legacy_env_path: Path | None = None,
    ) -> Path:
        """Resolve one path against its source, never the ambient cwd."""

        if key not in PATH_SETTING_KEYS:
            raise ValueError("setting is not path-valued")
        path = _expand_home(Path(value), self.home)
        if path.is_absolute():
            return _normalized(path)
        if source is SettingSource.LEGACY_ENV:
            if legacy_env_path is None or not legacy_env_path.is_absolute():
                raise RelativeRuntimePathError("legacy relative paths require an absolute source")
            return _normalized(legacy_env_path.parent / path)
        if source is SettingSource.DEFAULT:
            return self._default_path(key, path)
        if source is SettingSource.APP_PREFERENCE:
            return _anchored(self.application_support, path)
        if source is SettingSource.PROCESS_ENV and self.project_root is not None:
            return _normalized(self.project_root / path)
        raise RelativeRuntimePathError("bundled external paths must be absolute")

    def _default_path(self, key: SettingKey, path: Path) -> Path:
        if key is SettingKey.MEETINGS_DIR:
            return _normalized(self.home / path)
        if key is SettingKey.GOOGLE_CALENDAR_CREDENTIALS_FILE:
            return self.default_credentials_path
        if key is SettingKey.SUMMARY_PROMPT_FILE:
            return self.default_prompt_path
        raise ValueError("setting is not path-valued")


def _absolute(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("runtime layout roots must be absolute paths")
    return _normalized(path)


def _expand_home(path: Path, home: Path) -> Path:
    text = str(path)
    if text == "~":
        return home
    if text.startswith("~/"):
        return home / text[2:]
    if text.startswith("~"):
        raise RelativeRuntimePathError("named-user paths are not supported")
    return path


def _normalized(path: Path) -> Path:
    return Path(os.path.normpath(str(path)))


def _anchored(root: Path, path: Path) -> Path:
    candidate = _normalized(root / path)
    if not candidate.is_relative_to(root):
        raise RelativeRuntimePathError("managed relative paths must stay in app storage")
    return candidate
