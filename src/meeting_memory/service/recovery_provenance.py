"""Shape validation for source provenance persisted at recording stop."""

from __future__ import annotations

import os


def source_provenance_from_payload(
    payload: dict[str, object],
    source_info: os.stat_result,
) -> tuple[int | None, int | None, int | None, str | None]:
    value = payload.get("source")
    if value is None:
        return None, None, None, None
    if not isinstance(value, dict):
        raise ValueError("recovery source provenance is invalid")
    device = int(value["device"])
    inode = int(value["inode"])
    size = int(value["size"])
    digest = str(value["sha256"])
    if (
        len(digest) != 64
        or size <= 0
        or (device, inode, size)
        != (source_info.st_dev, source_info.st_ino, source_info.st_size)
    ):
        raise ValueError("recovery source provenance does not match the source")
    return device, inode, size, digest
