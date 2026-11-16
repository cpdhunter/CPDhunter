"""HKGBC shadow parser: reject badge-only titles; prefer real headings / detail titles."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRAPER = os.path.join(ROOT, "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

from title_quality import is_good_title  # noqa: E402

from scraper.shadow.paths import (  # noqa: E402
    HKGBC_URL,
    PRODUCTION_HKGBC,
    PRODUCTION_HKGBC_DETAIL,
    STATE_HKGBC,
)
from scraper.shadow.scrapling_hkgbc import parse_hkgbc_html  # noqa: E402


def test_hkgbc_rejects_badges_and_keeps_titles():
    html = open(PRODUCTION_HKGBC, encoding="utf-8").read()
    detail = open(PRODUCTION_HKGBC_DETAIL, encoding="utf-8").read()

    def fetch_detail(url):
        if "9001" in url:
            return detail
        raise RuntimeError("no detail")

    result = parse_hkgbc_html(
        html, HKGBC_URL, storage_file=STATE_HKGBC + ".test", fetch_detail=fetch_detail
    )
    events = result["events"]
    titles = [e["title"] for e in events]
    assert "Supporting Event" not in titles
    assert "HKGBC Event" not in titles
    assert "CPD Event" not in titles
    assert all(is_good_title(t) for t in titles), titles
    assert any("Environment and Conservation Fund" in t for t in titles), titles
    assert any("IAMC" in t and "Modular" in t for t in titles), titles
    assert any(t == "Official Detail H1 Event Name" for t in titles), titles
    assert all("events-detail" in (e["url"] or "") or "eventId=" in (e["url"] or "").lower() for e in events)
    print("test_hkgbc_rejects_badges_and_keeps_titles OK", len(events), titles[:5])


if __name__ == "__main__":
    test_hkgbc_rejects_badges_and_keeps_titles()
    print("HKGBC shadow tests passed")
