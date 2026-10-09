"""Private atomic suppression of repeated people-base offers."""

import hashlib
import json
from pathlib import Path

from meeting_memory.service.preference_store_fs import (
    locked_directory,
    read_document_at,
    replace_document_at,
)


class KnowledgeOfferStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def claim(self, names: tuple[str, ...], *, initial: bool = False) -> bool:
        if not names:
            return False
        hashes = {hashlib.sha256(name.encode()).hexdigest() for name in names}
        try:
            with locked_directory(self.path) as (directory, filename):
                raw = read_document_at(directory, filename)
                payload = json.loads(raw) if raw else {"initial": False, "names": []}
                if set(payload) != {"initial", "names"} or not isinstance(payload["names"], list):
                    return False
                known = set(payload["names"])
                if (initial and payload["initial"]) or hashes <= known:
                    return False
                updated = {
                    "initial": bool(initial or payload["initial"]),
                    "names": sorted(known | hashes)[-1000:],
                }
                replace_document_at(directory, filename, json.dumps(updated).encode())
                return True
        except (OSError, ValueError, TypeError):
            return False
