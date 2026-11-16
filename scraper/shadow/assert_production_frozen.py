#!/usr/bin/env python3
"""Record or verify that events.json and source_health.json were not written.

Read-only with respect to the production files themselves. The optional
snapshot file is a temporary checksum list (never a production catalog).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRAPER = os.path.dirname(_HERE)
_REPO = os.path.dirname(_SCRAPER)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scraper.shadow.observation import sha256_file  # noqa: E402
from scraper.shadow.paths import PRODUCTION_EVENTS, PRODUCTION_HEALTH  # noqa: E402

PATHS = (PRODUCTION_EVENTS, PRODUCTION_HEALTH)


def snapshot() -> dict:
    return {
        path: {
            "sha256": sha256_file(path),
            "exists": os.path.isfile(path),
            "size": os.path.getsize(path) if os.path.isfile(path) else 0,
        }
        for path in PATHS
    }


def save_snapshot(path: str) -> dict:
    data = snapshot()
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    return data


def check_snapshot(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        before = json.load(fh)
    after = snapshot()
    mismatches = []
    for file_path in PATHS:
        prev = before.get(file_path) or {}
        cur = after.get(file_path) or {}
        if prev.get("sha256") != cur.get("sha256"):
            mismatches.append(
                f"{file_path}: {prev.get('sha256')} -> {cur.get('sha256')}"
            )
    if mismatches:
        raise SystemExit(
            "production catalog changed during shadow run (forbidden):\n  "
            + "\n  ".join(mismatches)
        )
    return after


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Assert events.json and source_health.json stay unchanged"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--save", metavar="PATH", help="Write checksum snapshot")
    group.add_argument("--check", metavar="PATH", help="Verify checksums unchanged")
    parser.add_argument("--print", action="store_true", dest="print_snapshot")
    args = parser.parse_args(argv)
    if args.save:
        data = save_snapshot(args.save)
    else:
        data = check_snapshot(args.check)
    if args.print_snapshot or args.save:
        for path, meta in data.items():
            print(f"{meta['sha256']}  {path}")
    else:
        print("production checksums unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
