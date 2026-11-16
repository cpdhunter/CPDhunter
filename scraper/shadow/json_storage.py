"""Small, auditable JSON storage for Scrapling adaptive fingerprints.

Default Scrapling storage is a SQLite file inside the package directory
(elements_storage.db). That is ephemeral on GitHub Actions runners and is a
binary artefact. This backend writes a compact, source-specific JSON file
instead (persistence option A). Records are keyed by (domain, identifier) and
overwritten in place so the file cannot grow without bound.
"""
from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from typing import Any, Dict, Optional

from scrapling.core.storage import StorageSystemMixin
from scrapling.core.utils import _StorageTools

# Soft cap for a single experimental state file (pilot limit is 1 MB total).
MAX_STATE_BYTES = 200_000


def _as_html_element(element):
    # Selector wrappers expose the lxml node as _root.
    root = getattr(element, "_root", element)
    return root


@lru_cache(None)
class JsonFileStorage(StorageSystemMixin):
    """Scrapling-compatible storage that persists fingerprints as UTF-8 JSON."""

    def __init__(self, storage_file: str, url: Optional[str] = None):
        super().__init__(url)
        self.storage_file = storage_file
        self._lock = threading.RLock()
        parent = os.path.dirname(os.path.abspath(storage_file))
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _load(self) -> Dict[str, Any]:
        if not os.path.isfile(self.storage_file):
            return {"version": 1, "records": {}}
        with open(self.storage_file, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError:
                return {"version": 1, "records": {}}
        if not isinstance(data, dict) or "records" not in data:
            return {"version": 1, "records": {}}
        return data

    def _dump(self, data: Dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        encoded = payload.encode("utf-8")
        if len(encoded) > MAX_STATE_BYTES:
            raise RuntimeError(
                f"adaptive state {self.storage_file} would exceed "
                f"{MAX_STATE_BYTES} bytes; refusing to write"
            )
        tmp = self.storage_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.write("\n")
        os.replace(tmp, self.storage_file)

    def _key(self, identifier: str) -> str:
        return f"{self._get_base_url()}::{identifier}"

    def save(self, element, identifier: str) -> None:
        element_dict = _StorageTools.element_to_dict(_as_html_element(element))
        with self._lock:
            data = self._load()
            data.setdefault("records", {})[self._key(identifier)] = element_dict
            self._dump(data)

    def retrieve(self, identifier: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._load()
            rec = data.get("records", {}).get(self._key(identifier))
            return rec if isinstance(rec, dict) else None
