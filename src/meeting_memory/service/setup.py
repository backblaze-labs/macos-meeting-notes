"""First-run setup helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SetupAction:
    name: str
    message: str
    changed: bool = False


def ensure_env_file(project_dir: Path) -> SetupAction:
    env_path = project_dir / ".env"
    if env_path.exists():
        return SetupAction("env-file", ".env already exists.")

    example_path = project_dir / ".env.example"
    if not example_path.exists():
        return SetupAction("env-file", ".env.example is missing; could not create .env.")

    shutil.copyfile(example_path, env_path)
    return SetupAction("env-file", "Created .env from .env.example.", changed=True)


def setup_actions(project_dir: Path) -> list[SetupAction]:
    return [ensure_env_file(project_dir)]
