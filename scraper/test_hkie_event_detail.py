"""HKIE official event-detail enrichment tests.

Run: python scraper/test_hkie_event_detail.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from fetch import clean, dedup_events
from parsers.hkie_event_detail import (
    apply_hkie_detail,
    disciplines_from_hkie_division,
    enrich_hkie_events,
    parse_hkie_event_detail,
)
from title_quality import title_quality_reason

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hkie_event_detail")
FRC_URL = "https://hkie.org.hk/events/event-detail/6af419991f1d426669c456b1/"
FRC_TITLE = "Technical Seminar: Infrastructure Construction using Fibre Reinforced Concrete"
SRC = {
    "name": "HKIE Events",
    "group": "HKIE",
    "region": "HK",
    "url": "https://hkie.org.hk/events/",
}


def _html(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def _listing(title, date, url, **extra):
    ev = {"title": title, "date": date, "url": url, "organizer": None}
    ev.update(extra)
    return ev


def _clean(raw):
    rejects = {}
    out = clean(raw, SRC, rejects)
    assert out, f"clean rejected: {rejects} raw={raw}"
    return out


def test_frc_official_structure():
    detail = parse_hkie_event_detail(
        _html("frc_civil_hybrid.html"),
        api_title=FRC_TITLE,
        existing_title="Technical Seminar: Infrastructure Construction using Fibre Reinforced Concrete",
    )
    assert detail["title"] == FRC_TITLE
    assert title_quality_reason(detail["title"]) is None
    assert detail["date"] == "2026-11-26"
    assert detail["start_time"] == "19:00"
    assert detail["end_time"] == "20:00"
    assert detail["time"] == "19:00-20:00"
    venue = detail["venue"] or ""
    assert "Chun Wo & Hsin Chong Room" in venue
    assert "Island Beverley" in venue
    assert "Great George Street" in venue
    assert "Causeway Bay" in venue
    assert "Hybrid" not in venue  # attendance split out of venue
    assert detail["mode"] == "HYBRID"
    assert "Hybrid with Webinar" in (detail["attendanceMode"] or "")
    assert "Civil" in detail["disciplines"]
    assert detail["division"] == "Civil Division"
    assert detail["civil_related"] is True
    assert detail["cpd_hours"] is None  # no official CPD-hour statement
    assert detail["is_free"] is True
    dest = detail["registration_destination"] or ""
    assert "docs.google.com/forms" in dest
    assert "1FAIpQLScErtdzIwNadmPRQ8z11eece5xkizYKOstkxfoISuqQEWSCLw" in dest

    listing = _listing(FRC_TITLE, "2026-11-26", FRC_URL)
    apply_hkie_detail(listing, detail)
    cleaned = _clean(listing)
    assert cleaned["name"] == FRC_TITLE
    assert cleaned["date"] == "2026-11-26"
    assert cleaned["time"] == "19:00-20:00"
    assert cleaned["mode"] == "HYBRID"
    assert "Civil" in cleaned["disc"]
    assert cleaned["type"] == "Technical"
    assert cleaned["hrs"] == 1.0
    assert cleaned["hrs_est"] is True
    assert cleaned.get("venueSource") == "event_detail"
    assert "Island Beverley" in (cleaned.get("venue") or "")
    # Deadline wording must not become CLOSED during enrichment.
    assert (cleaned.get("registration") or {}).get("status") != "CLOSED"
    print("FRC official structure OK")


def test_enrichment_does_not_duplicate():
    listing = _listing(FRC_TITLE, "2026-11-26", FRC_URL)
    payload = {"title": FRC_TITLE, "html": _html("frc_civil_hybrid.html")}
    raw, stats = enrich_hkie_events(
        [listing],
        lambda url: payload,
        today="2026-11-16",
    )
    assert len(raw) == 1
    assert stats["enriched"] == 1
    assert raw[0]["url"] == FRC_URL
    cleaned = [_clean(raw[0])]
    # A second cleaned listing-only row with the same title/date/url must dedup.
    listing_only = _clean(_listing(FRC_TITLE, "2026-11-26", FRC_URL))
    merged = dedup_events(cleaned + [listing_only])
    assert len(merged) == 1
    assert merged[0]["mode"] == "HYBRID"
    print("enrichment does not duplicate OK")


def test_a_physical_venue_only_is_face_to_face():
    detail = parse_hkie_event_detail(_html("physical_venue_only.html"))
    ev = _listing(
        "Technical Visit to a Harbour Crossing Tunnel Site",
        "2026-12-03",
        "https://hkie.org.hk/events/event-detail/physicalonly0001/",
    )
    apply_hkie_detail(ev, detail)
    cleaned = _clean(ev)
    assert cleaned["mode"] == "FACE_TO_FACE"
    assert "Civil" in cleaned["disc"]
    print("A physical venue only FACE_TO_FACE OK")


def test_b_venue_plus_zoom_is_hybrid():
    detail = parse_hkie_event_detail(_html("venue_plus_zoom.html"))
    ev = _listing(
        "Technical Seminar on Temporary Works for Deep Excavation",
        "2026-12-04",
        "https://hkie.org.hk/events/event-detail/venuezoom0000001/",
    )
    apply_hkie_detail(ev, detail)
    cleaned = _clean(ev)
    assert cleaned["mode"] == "HYBRID"
    print("B venue + Zoom HYBRID OK")


def test_c_webinar_only_is_online():
    detail = parse_hkie_event_detail(_html("webinar_only.html"))
    ev = _listing(
        "Webinar on The Emerging Space Economy",
        "2026-12-05",
        "https://hkie.org.hk/events/event-detail/webinaronly000001/",
    )
    apply_hkie_detail(ev, detail)
    cleaned = _clean(ev)
    assert cleaned["mode"] == "ONLINE"
    print("C Zoom/Webinar only ONLINE OK")


def test_d_online_registration_physical_is_face_to_face():
    detail = parse_hkie_event_detail(_html("online_registration_physical.html"))
    ev = _listing(
        "Technical Seminar on Highway Drainage Design",
        "2026-12-06",
        "https://hkie.org.hk/events/event-detail/onlineregphys00001/",
    )
    apply_hkie_detail(ev, detail)
    cleaned = _clean(ev)
    assert cleaned["mode"] == "FACE_TO_FACE"
    assert cleaned["mode"] != "ONLINE"
    print("D Online Registration + physical venue FACE_TO_FACE OK")


def test_e_unknown_venue_mode():
    detail = parse_hkie_event_detail(_html("unknown_venue_mode.html"))
    ev = _listing(
        "General CPD Briefing for Members",
        "2026-12-07",
        "https://hkie.org.hk/events/event-detail/unknownmode000001/",
    )
    apply_hkie_detail(ev, detail)
    cleaned = _clean(ev)
    assert cleaned.get("mode") in (None, "", "UNKNOWN")
    print("E unknown venue/mode UNKNOWN OK")


def test_f_civil_division_maps_to_civil():
    discs, civil = disciplines_from_hkie_division("Civil Division")
    assert "Civil" in discs
    assert civil is True
    detail = parse_hkie_event_detail(_html("frc_civil_hybrid.html"), api_title=FRC_TITLE)
    assert "Civil" in detail["disciplines"]
    print("F official Civil Division → Civil OK")


def test_g_geotechnical_division_civil_relevance():
    discs, civil = disciplines_from_hkie_division("Geotechnical Division")
    assert "Geotechnical" in discs
    assert civil is True
    assert "Civil" in discs
    detail = parse_hkie_event_detail(_html("geotechnical_division.html"))
    ev = _listing(
        "Technical Visit to the Route 6- Central Kowloon Bypass (Kowloon Bay Section)",
        "2026-11-16",
        "https://hkie.org.hk/events/event-detail/6aed9c7c1f1d426669c1d6bd/",
    )
    apply_hkie_detail(ev, detail)
    cleaned = _clean(ev)
    assert "Geotechnical" in cleaned["disc"]
    assert "Civil" in cleaned["disc"]
    assert cleaned["mode"] == "FACE_TO_FACE"
    print("G Geotechnical Division → Geotechnical + Civil relevance OK")


def test_h_structural_division_civil_relevance():
    discs, civil = disciplines_from_hkie_division("Structural Division")
    assert "Structural" in discs
    assert civil is True
    assert "Civil" in discs
    detail = parse_hkie_event_detail(_html("structural_division.html"))
    ev = _listing(
        "Technical Seminar on Foundation Design for Tall Buildings",
        "2026-12-08",
        "https://hkie.org.hk/events/event-detail/structuraldiv0001/",
    )
    apply_hkie_detail(ev, detail)
    cleaned = _clean(ev)
    assert "Structural" in cleaned["disc"]
    assert "Civil" in cleaned["disc"]
    print("H Structural Division → Structural + Civil relevance OK")


def test_does_not_invent_structural():
    discs, civil = disciplines_from_hkie_division("Civil Division")
    assert "Structural" not in discs
    discs2, _ = disciplines_from_hkie_division("The Hong Kong Institution of Engineers")
    assert discs2 == []
    print("does not invent Structural OK")


def test_placeholder_midnight_time_ignored():
    html = """
    <ul class="einfoList">
      <li><b>Date:</b> <span>2026-11-16 - 2026-11-27</span></li>
      <li><b>Time:</b> <span>00:00 - 00:00</span></li>
      <li><b>Venue:</b> <span>Cathay City, 8 Scenic Road, Hong Kong International Airport</span></li>
      <li><b>Event Mode:</b> <span>ONSITE</span></li>
    </ul>
    <div class="einfoSection"><h2>Organisers:</h2><div>Aircraft Division</div></div>
    """
    detail = parse_hkie_event_detail(html, api_title="Hong Kong Airworthiness Course")
    assert detail["date"] == "2026-11-16"
    assert detail["start_time"] is None
    assert detail["time"] is None
    assert detail["mode"] == "FACE_TO_FACE"
    assert "Aircraft" in detail["disciplines"]
    print("placeholder 00:00-00:00 ignored OK")


def test_title_not_replaced_with_chrome():
    html = """
    <h1>Event Detail</h1>
    <nav class="breadcrumb">Home / Events / Event Detail</nav>
    <ul class="einfoList">
      <li><b>Date:</b> <span>2026-11-26 - 2026-11-26</span></li>
      <li><b>Time:</b> <span>19:00 - 20:00</span></li>
      <li><b>Venue:</b> <span>HKIE Headquarters</span></li>
    </ul>
    """
    detail = parse_hkie_event_detail(
        html,
        api_title="Event Detail",
        existing_title=FRC_TITLE,
    )
    assert detail["title"] == FRC_TITLE
    print("title not replaced with chrome OK")


def test_past_events_not_enriched():
    ev = _listing(FRC_TITLE, "2026-11-01", FRC_URL)
    raw, stats = enrich_hkie_events(
        [ev],
        lambda url: (_ for _ in ()).throw(AssertionError("must not fetch past events")),
        today="2026-11-16",
    )
    assert stats["skipped_past"] == 1
    assert stats["enriched"] == 0
    assert ev.get("hkie_detail_enriched") is None
    print("past events not enriched OK")


if __name__ == "__main__":
    test_frc_official_structure()
    test_enrichment_does_not_duplicate()
    test_a_physical_venue_only_is_face_to_face()
    test_b_venue_plus_zoom_is_hybrid()
    test_c_webinar_only_is_online()
    test_d_online_registration_physical_is_face_to_face()
    test_e_unknown_venue_mode()
    test_f_civil_division_maps_to_civil()
    test_g_geotechnical_division_civil_relevance()
    test_h_structural_division_civil_relevance()
    test_does_not_invent_structural()
    test_placeholder_midnight_time_ignored()
    test_title_not_replaced_with_chrome()
    test_past_events_not_enriched()
    print("ALL HKIE EVENT DETAIL TESTS PASSED")
