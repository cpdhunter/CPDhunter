"""Guards so the shadow pilot cannot write production catalog files."""
from __future__ import annotations

import hashlib
import os
from typing import Dict

from .paths import PRODUCTION_EVENTS, PRODUCTION_HEALTH

FORBIDDEN_WRITE_PATHS = (
    PRODUCTION_EVENTS,
    PRODUCTION_HEALTH,
)


def file_fingerprint(path: str) -> str:
    if not os.path.isfile(path):
        return "MISSING"
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    st = os.stat(path)
    return f"{h.hexdigest()}:{st.st_size}:{st.st_mtime_ns}"


def snapshot_production() -> Dict[str, str]:
    return {path: file_fingerprint(path) for path in FORBIDDEN_WRITE_PATHS}


def assert_production_unchanged(before: Dict[str, str], label: str = "") -> None:
    after = snapshot_production()
    for path, prev in before.items():
        cur = after.get(path)
        if cur != prev:
            raise AssertionError(
                f"shadow pilot must not change {path} ({label or 'run'}): {prev} -> {cur}"
            )


def shadow_source_mentions_forbidden_writes(root: str) -> list:
    """Static scan: flag shadow .py files that open production catalog paths for write."""
    hits = []
    forbidden_names = ("events.json", "source_health.json")
    for dirpath, _, files in os.walk(root):
        if dirpath.endswith(".venv") or "__pycache__" in dirpath:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            text = open(path, encoding="utf-8").read()
            # Allow comments / fingerprints / guards that mention the names
            # but reject obvious write calls targeting those files.
            lowered = text
            if "open(" in lowered and any(n in lowered for n in forbidden_names):
                for i, line in enumerate(lowered.splitlines(), 1):
                    if not any(n in line for n in forbidden_names):
                        continue
                    if "open(" in line and any(
                        flag in line for flag in ('"w"', "'w'", '"a"', "'a'", "w+", "a+")
                    ):
                        hits.append(f"{path}:{i}:{line.strip()}")
    return hits
