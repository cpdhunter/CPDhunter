"""Guard: shadow code must not write events.json or source_health.json."""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRAPER = os.path.join(ROOT, "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

from scraper.shadow.build_fixtures import build_all  # noqa: E402
from scraper.shadow.paths import (  # noqa: E402
    PRODUCTION_CIC,
    PRODUCTION_EVENTS,
    PRODUCTION_HEALTH,
    SHADOW_ROOT,
)
from scraper.shadow.safety import (  # noqa: E402
    assert_production_unchanged,
    shadow_source_mentions_forbidden_writes,
    snapshot_production,
)
from scraper.shadow.scrapling_cic import parse_cic_html  # noqa: E402
from scraper.shadow.scrapling_shadow import run_pilot  # noqa: E402


def test_static_scan_no_production_writes():
    hits = shadow_source_mentions_forbidden_writes(SHADOW_ROOT)
    assert hits == [], hits
    print("test_static_scan_no_production_writes OK")


def test_runtime_does_not_touch_catalog():
    assert os.path.isfile(PRODUCTION_EVENTS)
    before = snapshot_production()
    build_all()
    html = open(PRODUCTION_CIC, encoding="utf-8").read()
    with tempfile.TemporaryDirectory() as td:
        parse_cic_html(html, storage_file=os.path.join(td, "cic.json"))
        report = os.path.join(td, "scrapling-shadow.json")
        run_pilot(try_live=False, report_path=report)
        assert os.path.isfile(report)
    assert_production_unchanged(before, "guard")
    print("test_runtime_does_not_touch_catalog OK")


if __name__ == "__main__":
    test_static_scan_no_production_writes()
    test_runtime_does_not_touch_catalog()
    print("guard tests passed")
