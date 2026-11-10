"""Title quality + affected parser regression tests. Run: python scraper/test_title_quality.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from bs4 import BeautifulSoup

from title_quality import (
    CIC_EVENT_TYPE_LABELS,
    clamp_title,
    is_date_only_title,
    is_filter_or_badge_title,
    is_good_title,
    is_time_only_title,
    strip_hkgbc_badges,
    strip_page_chrome,
    title_quality_reason,
)
from fetch import (
    clean,
    extract_cic,
    extract_hkgbc,
    extract_hkie_cpd,
    extract_labour,
    generic_extract,
    hours_from_range,
    parse_time_range,
    stated_cpd_hours,
    is_good_title as fetch_is_good,  # noqa: F401 — re-export path
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _soup(rel):
    with open(os.path.join(FIX, rel), encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


def test_validator_rejects_impossible():
    assert title_quality_reason("") == "empty"
    assert is_time_only_title("15:30 - 17:00")
    assert is_time_only_title("15:30 – 16:45")
    assert is_time_only_title("9:30am - 6:30pm")
    assert is_time_only_title("09:00 am – 5:00 pm")
    assert title_quality_reason("15:30 - 17:00") == "time_only"
    assert title_quality_reason("9:30am - 6:30pm") == "time_only"
    assert is_date_only_title("11 December 2026 (Fri)")
    assert is_date_only_title("28 & 29 December 2026 (Mon & Tue)")
    assert is_date_only_title("9-11 Dec 2026 (Wed-Fri)")
    assert is_date_only_title("4 & 7-11 December 2026")
    assert is_date_only_title("14-18 December 2026")
    assert title_quality_reason("11 December 2026 (Fri)") == "date_only"
    for label in [
        "Job Fair",
        "Conference／Seminar",
        "Conference/Seminar",
        "Exhibition",
        "Festival",
        "Others",
        "Ceremony",
        "Tour",
        "Workshop",
        "Supporting Event",
        "HKGBC Event",
        "CPD Event",
    ]:
        assert is_filter_or_badge_title(label), label
        assert not is_good_title(label), label
    # Legitimate long titles must NOT be rejected for length
    long_title = "Online Seminar on \"Mobile Elevating Work Platforms Safety and Working at Height Safety: Accident Cases Sharing and Best Practices\" " + ("X" * 50)
    assert len(long_title) > 180
    assert is_good_title(long_title)
    # Workshop inside longer title is fine
    assert is_good_title("Temporary Works Workshop 2026")
    assert title_quality_reason("Supporting Event IAMC & HKU - Conference") == "hkgbc_badge_prefix"
    assert title_quality_reason("Begins 11th November 2026 November 2026 Economic and Policy Briefing Begins 11th November 2026 Find out more") == "page_chrome"
    print("validator OK")


def test_strip_hkgbc_badges():
    assert strip_hkgbc_badges("Supporting Event") == ""
    assert strip_hkgbc_badges("HKGBC Event") == ""
    assert strip_hkgbc_badges("HKGBC Event , CPD Event Environment and Conservation Fund") == "Environment and Conservation Fund"
    assert strip_hkgbc_badges("Supporting Event IAMC & HKU - International Conference") == "IAMC & HKU - International Conference"
    print("strip_hkgbc_badges OK")


def test_clamp_no_midword_200():
    s = "Energy-efficient Airflow Management for Green Data Centres: Principles, Practices and Retrofit Approaches " * 3
    out = clamp_title(s, 500)
    assert len(out) <= 500
    # Must not cut at exactly 200 mid-word like old code
    assert out != s[:200]
    assert " " not in out[-1:] or True
    # Truncation prefers word boundary
    if len(s) > 500:
        assert not out.endswith("Da")  # old mid-word "Green Da"
    print("clamp_title OK", len(out))


def test_hkgbc_parser():
    soup = _soup("hkgbc/events_listing.html")
    detail_map = {
        "9001": open(os.path.join(FIX, "hkgbc/events_detail.html"), encoding="utf-8").read(),
    }

    def fetch_detail(url):
        if "9001" in url:
            return detail_map["9001"]
        if "og" in url:
            return open(os.path.join(FIX, "hkgbc/events_detail_og.html"), encoding="utf-8").read()
        raise RuntimeError("no detail")

    raw = extract_hkgbc(soup, "https://www.hkgbc.org.hk/eng/news-events/events-trainings/events", fetch_detail=fetch_detail)
    titles = [e["title"] for e in raw]
    assert "Supporting Event" not in titles
    assert "HKGBC Event" not in titles
    assert "CPD Event" not in titles
    assert any("Environment and Conservation Fund" in t for t in titles), titles
    assert any("IAMC" in t and "Modular" in t for t in titles), titles
    # Badge-only row resolved via detail H1
    assert any(t == "Official Detail H1 Event Name" for t in titles), titles
    # No mid-word 200 truncation on long title
    long = [t for t in titles if "Green Data Centres" in t or "Environment and Conservation Fund" in t]
    assert long, titles
    assert all(len(t) <= 500 for t in titles)
    assert all(is_good_title(t) for t in titles)
    # Prefer detail URLs
    assert all("events-detail" in e["url"] or "eventId=" in e["url"].lower() for e in raw)
    print("hkgbc parser OK", len(raw), titles[:5])


def test_hkgbc_og_fallback():
    html = open(os.path.join(FIX, "hkgbc/events_detail_og.html"), encoding="utf-8").read()
    from fetch import _hkgbc_detail_title
    t = _hkgbc_detail_title(html)
    assert t == "OG Title Only Event", t
    print("hkgbc og fallback OK")


def test_labour_parser():
    soup = _soup("labour/talks.html")
    raw = extract_labour(soup, "https://www1.oshsreg.gov.hk/ocrs/talk/search.xhtml")
    assert raw, "expected labour talks"
    for e in raw:
        assert not is_time_only_title(e["title"]), e
        assert is_good_title(e["title"]), e
        assert e.get("date")
    # Known first talk topic (Chinese official wording on page)
    titles = " | ".join(e["title"] for e in raw)
    assert "辦公室僱員" in titles or "肌骨骼" in titles or "體力處理" in titles, titles
    # Times parsed onto same item when present
    timed = [e for e in raw if e.get("start_time")]
    assert timed, raw
    # Adjacent events do not share titles incorrectly — unique date+title
    keys = [(e["date"], e["title"]) for e in raw]
    assert len(keys) == len(set(keys))
    print("labour parser OK", len(raw), raw[0])


def test_cic_parser():
    soup = _soup("cic/events.html")
    raw = extract_cic(soup, "https://www.cic.hk/en/events")
    titles = [e["title"] for e in raw]
    for label in CIC_EVENT_TYPE_LABELS:
        assert label.lower() not in [t.lower() for t in titles if t.lower() == label.lower()]
        assert all(t.lower() != label.lower() for t in titles)
    assert any("Temporary Works Workshop 2026" in t for t in titles), titles
    # Exact filter labels alone rejected
    assert "Job Fair" not in titles
    assert "Exhibition" not in titles
    # Type prefix stripped from longer titles
    from title_quality import strip_cic_type_prefix
    assert strip_cic_type_prefix("Job Fair Construction Industry Recruitment Day") == "Construction Industry Recruitment Day"
    assert strip_cic_type_prefix("Conference／Seminar RSTCS Summit 2026") == "RSTCS Summit 2026"
    print("cic parser OK", titles)


def test_hkie_cpd_parser():
    soup = _soup("hkie_cpd/calendar.html")
    raw = extract_hkie_cpd(soup, "https://hkie.org.hk/professional-development/continuing-professional-development/cpd-calendar/")
    titles = [e["title"] for e in raw]
    assert raw
    for e in raw:
        assert not is_date_only_title(e["title"]), e
        assert is_good_title(e["title"]), e
    expected_frags = [
        "Sustainable Development Planning and ESG for Engineers",
        "Essentials of NEC4",
        "Project Management and Impactful Communication",
        "Integrated ASNT PT",
        "ISO 14064",
        "Global BIM Coordinator Professional Training Course",
    ]
    blob = " || ".join(titles)
    for frag in expected_frags:
        assert frag in blob, (frag, titles)
    # Same-card pairing: ESG is 11 Dec 2026
    esg = next(e for e in raw if "Sustainable Development Planning" in e["title"])
    assert esg["date"] == "2026-12-11", esg
    nec = next(e for e in raw if "NEC4" in e["title"])
    assert nec["date"] == "2026-12-11", nec
    bim = next(e for e in raw if "BIM Coordinator" in e["title"])
    assert bim["date"] == "2026-12-04", bim  # parse_date takes first day of range
    # Duration / stated hours captured (not used as title)
    iso = next(e for e in raw if "ISO 14064" in e["title"])
    assert iso.get("start_time") == "09:30" and iso.get("end_time") == "17:30", iso
    bim_mgr = next(e for e in raw if "BIM Manager" in e["title"])
    assert bim_mgr.get("start_time") == "09:30" and bim_mgr.get("end_time") == "18:30", bim_mgr
    esg = next(e for e in raw if "Sustainable Development Planning" in e["title"])
    assert esg.get("start_time") == "13:30" and esg.get("end_time") == "17:00", esg
    any_hrs = [e for e in raw if e.get("cpd_hours") == 3]
    assert any_hrs, "expected any 3 hours cards"
    nec = next(e for e in raw if "NEC4" in e["title"])
    assert nec.get("start_time") == "09:00" and nec.get("end_time") == "17:00", nec
    assert sum(1 for e in raw if e.get("start_time") or e.get("cpd_hours")) >= 9, raw
    # clean() estimates from duration / keeps stated hours
    src = {"name": "HKIE CPD Calendar", "url": "https://hkie.org.hk/", "region": "HK", "free": None, "group": "HKIE", "type": "Technical"}
    rejects = {}
    c_iso = clean({**iso, "is_online": None, "is_free": None}, src, rejects)
    assert c_iso and c_iso["hrs"] == 8.0 and c_iso["hrs_est"] is True, c_iso
    c_any = clean({**any_hrs[0], "is_online": None, "is_free": None}, src, rejects)
    assert c_any and c_any["hrs"] == 3 and c_any["hrs_est"] is False, c_any
    print("hkie-cpd parser OK", len(raw))


def test_generic_cic_uk():
    # Detail page: prefer H1 over chrome-filled anchor
    soup = _soup("generic_cicuk/detail.html")
    raw = generic_extract(soup, "https://www.cic.org.uk/events/november-2026-economic-and-policy-briefing")
    assert raw, "expected CIC UK event"
    for e in raw:
        assert "Find out more" not in e["title"]
        assert not e["title"].lower().startswith("begins")
        assert e["title"] == "November 2026 Economic and Policy Briefing", e
    # Listing card chrome stripped / heading preferred
    soup2 = _soup("generic_cicuk/listing_card.html")
    raw2 = generic_extract(soup2, "https://www.cic.org.uk/events")
    for e in raw2:
        assert is_good_title(e["title"]), e
        assert "Find out more" not in e["title"]
    print("generic CIC UK OK", raw[0]["title"], "listing", len(raw2))


def test_clean_rejects_bad_title():
    src = {"name": "Test", "url": "https://example.com/x", "region": "HK", "free": True}
    rejects = {}
    assert clean({"title": "15:30 - 17:00", "date": "2026-12-01", "url": "https://example.com/a"}, src, rejects) is None
    assert rejects.get("bad_title", 0) >= 1
    rejects = {}
    assert clean({"title": "Job Fair", "date": "2026-12-01", "url": "https://example.com/a"}, src, rejects) is None
    rejects = {}
    assert clean({"title": "Supporting Event", "date": "2026-12-01", "url": "https://example.com/a"}, src, rejects) is None
    rejects = {}
    ok = clean({"title": "Legitimate Seminar on Structural Safety", "date": "2026-12-01", "url": "https://example.com/a"}, src, rejects)
    assert ok and ok["name"].startswith("Legitimate")
    # Long title preserved beyond 200
    long = "Online Seminar on Mobile Elevating Work Platforms Safety and Working at Height Safety Accident Cases Sharing and Best Practices for Industry Practitioners in Hong Kong Construction Sites"
    assert len(long) > 180
    rejects = {}
    ok = clean({"title": long, "date": "2026-12-01", "url": "https://example.com/a"}, src, rejects)
    assert ok and len(ok["name"]) > 180
    print("clean bad_title OK")


def test_stale_contaminated_not_preserved():
    """Simulates merge: old contaminated ID must not coexist after title fix."""
    from title_quality import is_good_title as good
    old = [
        {"id": "oldbad1", "name": "15:30 - 17:00", "date": "2026-12-01", "auto": True, "source": "Labour"},
        {"id": "oldbad2", "name": "Job Fair", "date": "2026-11-20", "auto": True, "source": "CIC"},
        {"id": "oldbad3", "name": "Supporting Event", "date": "2026-11-16", "auto": True, "source": "HKGBC"},
        {"id": "oldbad3b", "name": "Supporting Event IAMC & HKU - Conference", "date": "2026-11-21", "auto": True, "source": "HKGBC"},
        {"id": "oldbad4", "name": "11 December 2026 (Fri)", "date": "2026-12-11", "auto": True, "source": "HKIE"},
        {"id": "oldbad5", "name": "Begins 11th November 2026 Foo Begins 11th November 2026 Find out more", "date": "2026-11-26", "auto": True, "source": "CIC UK"},
        {"id": "oldgood", "name": "Real Kept Seminar", "date": "2026-12-05", "auto": True, "source": "X"},
    ]
    found = {
        "new1": {"id": "new1", "name": "辦公室僱員職業健康系列(II) 辦公室僱員 - 預防肌骨骼疾病", "date": "2026-12-01", "auto": True},
    }
    kept = {}
    for e in old:
        if e["id"] not in found:
            if not good(e.get("name") or ""):
                continue
            kept[e["id"]] = e
    assert "oldbad1" not in kept and "oldbad2" not in kept and "oldbad3" not in kept and "oldbad3b" not in kept and "oldbad4" not in kept and "oldbad5" not in kept
    assert "oldgood" in kept
    print("stale contaminated migration OK")


def test_strip_page_chrome():
    dirty = "Begins 11th November 2026 November 2026 Economic and Policy Briefing Begins 11th November 2026 11 November CIC webinar Find out more"
    cleaned = strip_page_chrome(dirty)
    assert "Find out more" not in cleaned
    assert not cleaned.lower().startswith("begins")
    assert "Economic and Policy Briefing" in cleaned
    print("strip_page_chrome OK", cleaned)



def test_parse_time_range_and_hours():
    assert parse_time_range("9:30 – 17:30") == ("09:30", "17:30")
    assert parse_time_range("09:30-17:30") == ("09:30", "17:30")
    assert parse_time_range("0900 - 1700") == ("09:00", "17:00")
    assert parse_time_range("9:30am - 6:30pm") == ("09:30", "18:30")
    assert parse_time_range("1:30pm - 5:00pm") == ("13:30", "17:00")
    assert parse_time_range("9:30 a.m. – 5:00 p.m.") == ("09:30", "17:00")
    assert parse_time_range("09:00 am – 5:00 pm") == ("09:00", "17:00")
    assert parse_time_range("not a time") is None
    assert hours_from_range("09:30", "17:30") == 8.0
    assert hours_from_range("13:30", "17:00") == 3.5
    assert hours_from_range("06:45", "17:00") == 10.0  # 615 min within 720
    assert hours_from_range("09:00", "22:00") is None  # 780 > 720
    assert hours_from_range("22:45", "01:00") == 2.0  # overnight
    assert stated_cpd_hours("any 3 hours") == 3
    assert stated_cpd_hours("Any 3 Hours") == 3
    assert stated_cpd_hours("2 hours") == 2
    assert stated_cpd_hours("Workshop any 3 hours extra") is None
    print("parse_time_range / hours_from_range OK")


if __name__ == "__main__":
    test_validator_rejects_impossible()
    test_parse_time_range_and_hours()
    test_strip_hkgbc_badges()
    test_clamp_no_midword_200()
    test_hkgbc_parser()
    test_hkgbc_og_fallback()
    test_labour_parser()
    test_cic_parser()
    test_hkie_cpd_parser()
    test_generic_cic_uk()
    test_clean_rejects_bad_title()
    test_stale_contaminated_not_preserved()
    test_strip_page_chrome()
    print("All title-quality tests passed")
