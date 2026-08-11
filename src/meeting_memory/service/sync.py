"""Rescan local meetings and upload pending B2 artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from meeting_memory.service.frontmatter import replace_frontmatter
from meeting_memory.service.legacy_snapshot import (
    capture_legacy_snapshot,
    replace_legacy_metadata,
)
from meeting_memory.types.artifacts import LegacyBackupUpload
from meeting_memory.types.egress import EgressPaused
from meeting_memory.types.meeting import B2UploadResult


class B2Client(Protocol):
    def upload_legacy_snapshot(self, request: LegacyBackupUpload) -> B2UploadResult:
        """Upload pinned private legacy bytes."""


@dataclass(frozen=True)
class SyncResult:
    attempted: int = 0
    uploaded: int = 0
    failed: int = 0


def sync_pending_meetings(
    meetings_dir: Path,
    b2_client: B2Client,
    *,
    enabled: Callable[[], bool] = lambda: True,
) -> SyncResult:
    if not meetings_dir.exists():
        return SyncResult()

    attempted = uploaded = failed = 0
    for meeting_dir in sorted(path for path in meetings_dir.iterdir() if path.is_dir()):
        if not enabled():
            break
        try:
            manager = capture_legacy_snapshot(meeting_dir)
            snapshot = manager.__enter__()
        except (OSError, TypeError, UnicodeError, ValueError):
            continue
        try:
            legacy_status = str(snapshot.frontmatter.get("b2_status") or "").strip().casefold()
            if legacy_status in {"ok", "succeeded"}:
                continue
            if not enabled():
                break
            attempted += 1
            try:
                result = b2_client.upload_legacy_snapshot(snapshot.backup_request())
            except EgressPaused:
                return SyncResult(attempted=attempted, uploaded=uploaded, failed=failed)
            except Exception:
                _replace_backup_state(snapshot, None, "upload_failed")
                failed += 1
            else:
                _replace_backup_state(snapshot, result, "ok")
                uploaded += 1
        except Exception:
            failed += 1
        finally:
            manager.__exit__(None, None, None)
    return SyncResult(attempted=attempted, uploaded=uploaded, failed=failed)


def _replace_backup_state(snapshot, result: B2UploadResult | None, status: str) -> None:
    frontmatter = snapshot.frontmatter.copy()
    if result is not None:
        frontmatter["b2_audio"] = result.audio_key
        frontmatter["b2_transcript"] = result.transcript_key
    frontmatter["b2_status"] = status
    replace_legacy_metadata(
        snapshot,
        replace_frontmatter(snapshot.metadata_text, frontmatter),
    )
