"""HKIE CPD shadow parser: container-scoped title+date pairs; never date-only titles."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRAPER = os.path.join(ROOT, "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

from title_quality import is_date_only_title, is_good_title  # noqa: E402

from scraper.shadow.paths import HKIE_URL, PRODUCTION_HKIE, STATE_HKIE  # noqa: E402
from scraper.shadow.scrapling_hkie_cpd import parse_hkie_cpd_html  # noqa: E402


def test_hkie_card_scope_pairs():
    html = open(PRODUCTION_HKIE, encoding="utf-8").read()
    result = parse_hkie_cpd_html(html, HKIE_URL, storage_file=STATE_HKIE + ".test")
    events = result["events"]
    assert events, "expected HKIE course cards"
    for e in events:
        assert not is_date_only_title(e["title"]), e
        assert is_good_title(e["title"]), e
        assert e.get("date"), e
    titles = " || ".join(e["title"] for e in events)
    for frag in (
        "Sustainable Development Planning and ESG for Engineers",
        "Essentials of NEC4",
        "Project Management and Impactful Communication",
        "ISO 14064",
        "Global BIM Coordinator Professional Training Course",
    ):
        assert frag in titles, (frag, [e["title"] for e in events])
    esg = next(e for e in events if "Sustainable Development Planning" in e["title"])
    assert esg["date"] == "2026-12-11", esg
    assert esg.get("start_time") == "13:30" and esg.get("end_time") == "17:00", esg
    nec = next(e for e in events if "NEC4" in e["title"])
    assert nec["date"] == "2026-12-11", nec
    bim = next(e for e in events if "BIM Coordinator" in e["title"])
    assert bim["date"] == "2026-12-04", bim
    iso = next(e for e in events if "ISO 14064" in e["title"])
    assert iso.get("start_time") == "09:30" and iso.get("end_time") == "17:30", iso
    print("test_hkie_card_scope_pairs OK", len(events))


if __name__ == "__main__":
    test_hkie_card_scope_pairs()
    print("HKIE shadow tests passed")
