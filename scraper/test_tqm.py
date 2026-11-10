"""TQM upcoming training parser fixture tests. Run: python scraper/test_tqm.py"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup

from event_mode import attach_mode, infer_mode, mode_of
from fetch import clean, parse_date, TODAY, KEEP_DAYS_AHEAD
from parsers.tqm import (
    extract_tqm,
    parse_tqm_course_detail,
    enrich_tqm_course_details,
    _is_tqm_public_source_url,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "tqm")
BASE = "https://tqm.com.hk/training/upcoming/"
SRC = {
    "name": "TQM Consultants Training",
    "group": "TQM",
    "region": "HK",
    "url": BASE,
    "accept_paid": True,
}
GFORM = "https://docs.google.com/forms/d/e/1FAIpQLSfjCkv-8D3wO9_t1q9G31YWgvqm0mtb1h7CK9z1dPRAX2fB9A/viewform"
DETAIL_DAY2 = "https://tqm.com.hk/course/6sigma-greenbelt-2/"
VENUE = "TQM Training Centre, 11/F Lockhart Centre, 301-307 Lockhart Road, Hong Kong"
FOOTER_HQ = "11/F, Lockhart Centre, 301 Lockhart Road, Wan Chai, Hong Kong"

EXPECTED = [
    ("2026-11-13", "Six Sigma Green Belt Training – Day 2 (of 4)", "https://tqm.com.hk/course/6sigma-greenbelt-2/", "9:30am - 5:00pm", "09:30", "17:00"),
    ("2026-11-20", "Six Sigma Green Belt Training – Day 3 (of 4)", "https://tqm.com.hk/course/6sigma-greenbelt-3/", "9:30am - 5:00pm", "09:30", "17:00"),
    ("2026-11-27", "Six Sigma Green Belt Training – Day 4 (of 4)", "https://tqm.com.hk/course/6sigma-greenbelt-4/", "9:30am - 5:00pm", "09:30", "17:00"),
    ("2026-12-11", "CPD1212/2026 Sustainable Development Planning and ESG for Engineers", "https://tqm.com.hk/course/cpd1212-2026-sustainable-development-planning-and-esg-workshop/", "1:30pm - 5:00pm", "13:30", "17:00"),
    ("2026-12-18", "CPD1213/2026 Project Management and Impactful Communication", "https://tqm.com.hk/course/cpd1213-2026-project-management-and-impactful-communication/", "9:30am - 5:00pm", "09:30", "17:00"),
    ("2027-06-18", "CPD0611/2027 Sustainable Development Planning and ESG for Engineers", "https://tqm.com.hk/course/cpd0611-2027-sustainable-development-planning-and-esg-workshop/", "1:30pm - 5:00pm", "13:30", "17:00"),
    ("2027-06-25", "CPD0614/2027 Project Management and Impactful Communication", "https://tqm.com.hk/course/cpd0614-2027-project-management-and-impactful-communication/", "9:30am - 5:00pm", "09:30", "17:00"),
]


def _html(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def _soup(name):
    return BeautifulSoup(_html(name), "html.parser")


def test_listing_extracts_seven_courses():
    raw = extract_tqm(_soup("upcoming.html"), BASE)
    assert len(raw) == 7, [e["title"] for e in raw]
    by_date = {(e["date"], e["title"]): e for e in raw}
    for date, title, url, time_s, start, end in EXPECTED:
        ev = by_date.get((date, title))
        assert ev, f"missing {date} {title} in {list(by_date)}"
        assert ev["url"] == url
        assert ev.get("start_time") == start
        assert ev.get("end_time") == end
        assert ev.get("time") == time_s
        assert ev.get("is_free") is False
        assert ev.get("registration_destination") == GFORM
        assert ev.get("venue") in (None, "",)
        assert ev.get("mode") in (None, "",)
        assert ev.get("venueSource") in (None, "",)
        # Titles must not be contaminated by times or footer
        assert "9:30" not in ev["title"] and "5:00" not in ev["title"]
        assert "Lockhart" not in ev["title"]
        assert "Apply Now" not in ev["title"]
        assert "Wan Chai" not in ev["title"]
    print("listing extracts 7 courses OK")


def test_listing_and_footer_must_not_classify_mode():
    raw = extract_tqm(_soup("upcoming.html"), BASE)
    for ev in raw:
        assert mode_of(ev) == "UNKNOWN"
        attached = dict(ev)
        attach_mode(attached)
        assert attached.get("mode") in (None, "", "UNKNOWN")
    # Official listing HTML must not yield a course-header venue (footer HQ only).
    listing_detail = parse_tqm_course_detail(_html("upcoming.html"))
    assert not listing_detail.get("venue"), listing_detail
    # Even a raw footer HQ address without venueSource stays UNKNOWN.
    assert mode_of({"venue": FOOTER_HQ}) == "UNKNOWN"
    assert mode_of({"venue": "Hong Kong HQ: " + FOOTER_HQ}) == "UNKNOWN"
    print("listing/footer must not classify mode OK")


def test_detail_venue_no_online_is_face_to_face():
    raw = extract_tqm(_soup("upcoming.html"), BASE)
    html = _html("course_6sigma_greenbelt_2.html")
    fixtures = {DETAIL_DAY2: html}
    enriched = enrich_tqm_course_details(raw, lambda u: fixtures.get(u))
    day2 = next(e for e in enriched if e["url"] == DETAIL_DAY2)
    assert day2["venue"] == VENUE
    assert day2["venueSource"] == "event_detail"
    assert day2["mode"] == "FACE_TO_FACE"
    # Footer wording must not replace the header venue
    assert "Wan Chai" not in day2["venue"]
    assert "Hong Kong HQ" not in day2["venue"]
    assert "Shenzhen" not in day2["venue"]
    # Other listing rows were not fetched — no venue/mode stamp
    others = [e for e in enriched if e["url"] != DETAIL_DAY2]
    assert all(not e.get("venue") and not e.get("mode") for e in others)
    print("detail venue + no online -> FACE_TO_FACE OK")


def test_detail_venue_plus_zoom_is_hybrid():
    ev = {
        "title": "Six Sigma Green Belt Training – Day 2 (of 4)",
        "date": "2026-11-13",
        "url": DETAIL_DAY2,
        "organizer": "TQM Consultants",
    }
    enriched = enrich_tqm_course_details(
        [ev], lambda u: _html("course_detail_hybrid_zoom.html")
    )
    assert enriched[0]["venue"] == VENUE
    assert enriched[0]["venueSource"] == "event_detail"
    assert enriched[0]["mode"] == "HYBRID"
    print("detail venue + Zoom -> HYBRID OK")


def test_detail_webinar_is_online():
    ev = {
        "title": "Six Sigma Green Belt Training – Day 2 (of 4)",
        "date": "2026-11-13",
        "url": DETAIL_DAY2,
        "organizer": "TQM Consultants",
    }
    enriched = enrich_tqm_course_details(
        [ev], lambda u: _html("course_detail_webinar.html")
    )
    # Footer HQ must not be used as venue on a webinar detail page
    assert not enriched[0].get("venue") or "Training Centre" not in (enriched[0].get("venue") or "")
    assert enriched[0].get("venueSource") in (None, "",)
    assert enriched[0]["mode"] == "ONLINE"
    print("explicit webinar on detail page -> ONLINE OK")


def test_org_district_online_false_remain_unknown():
    assert mode_of({"venue": "TQM Consultants"}) == "UNKNOWN"
    assert mode_of({"venue": "TQM", "venueSource": "event_detail"}) == "UNKNOWN"
    assert mode_of({"venue": "Wan Chai"}) == "UNKNOWN"
    assert mode_of({"venue": "Hong Kong", "venueSource": "event_detail"}) == "UNKNOWN"
    assert mode_of({"online": False}) == "UNKNOWN"
    assert infer_mode({"online": False})["reason"] == "legacy_false_insufficient"
    print("org/district/online=false remain UNKNOWN OK")


def test_google_forms_destination_no_auto_submit():
    raw = extract_tqm(_soup("upcoming.html"), BASE)
    fixtures = {DETAIL_DAY2: _html("course_6sigma_greenbelt_2.html")}
    enriched = enrich_tqm_course_details(raw, lambda u: fixtures.get(u))
    day2 = next(e for e in enriched if e["url"] == DETAIL_DAY2)
    rejects = {}
    out = clean(day2, SRC, rejects)
    assert out, rejects
    reg = out.get("registration") or {}
    assert reg.get("mechanism") == "GOOGLE_FORMS"
    assert reg.get("destination") == GFORM
    assert reg.get("requiresManualCompletion") is True
    assert reg.get("discoveryMethod") == "source_parser"
    assert "auto" not in (reg.get("status") or "").lower()
    print("Google Forms destination, no auto-submit OK")


def test_paid_survives_clean_with_mode_and_time():
    raw = extract_tqm(_soup("upcoming.html"), BASE)
    fixtures = {DETAIL_DAY2: _html("course_6sigma_greenbelt_2.html")}
    enriched = enrich_tqm_course_details(raw, lambda u: fixtures.get(u))
    day2 = next(e for e in enriched if e["url"] == DETAIL_DAY2)
    rejects = {}
    out = clean(day2, SRC, rejects)
    assert out, rejects
    assert out["free"] is False
    assert out["mode"] == "FACE_TO_FACE"
    assert out["venue"] == VENUE
    assert out["venueSource"] == "event_detail"
    assert out["time"] == "09:30-17:00"
    assert out["url"] == DETAIL_DAY2
    assert out["org"] == "TQM Consultants"
    assert "Lockhart" not in out["name"]
    assert "9:30" not in out["name"]
    # June 2027 rows are extracted but sit outside the 180-day keep window
    june = next(e for e in enriched if e["date"] == "2027-06-18")
    rejects2 = {}
    assert clean(june, SRC, rejects2) is None
    assert rejects2.get("date_range", 0) >= 1
    print("paid survives clean; mode/time/venue stamped OK")


def test_month_first_dates_parse():
    assert parse_date("November 13, 2026") == "2026-11-13"
    assert parse_date("June 18, 2027") == "2027-06-18"
    assert parse_date("December 11, 2026") == "2026-12-11"
    print("month-first dates OK")


def test_fetch_html_accepts_202_with_full_html():
    from unittest.mock import patch
    from fetch import fetch_html, StepError, _usable_html_response

    full = "<!DOCTYPE html><html><body>" + ("course " * 800) + "</body></html>"
    assert _usable_html_response(202, full)
    assert not _usable_html_response(202, "<html>short</html>")
    assert not _usable_html_response(403, full)
    assert not _usable_html_response(202, "")

    class _Resp:
        status_code = 202
        text = full
        apparent_encoding = "utf-8"
        encoding = "utf-8"

    with patch("fetch.allowed", return_value=True), patch("fetch.requests.get", return_value=_Resp()):
        got = fetch_html("https://tqm.com.hk/training/upcoming/")
    assert "course" in got
    print("HTTP 202 full HTML accepted OK")


def test_public_source_url_scope():
    assert _is_tqm_public_source_url(BASE)
    assert _is_tqm_public_source_url(DETAIL_DAY2)
    assert not _is_tqm_public_source_url("https://tqm.com.hk/")
    assert not _is_tqm_public_source_url("https://tqm.com.hk/about/")
    print("public source URL scope OK")


if __name__ == "__main__":
    test_listing_extracts_seven_courses()
    test_listing_and_footer_must_not_classify_mode()
    test_detail_venue_no_online_is_face_to_face()
    test_detail_venue_plus_zoom_is_hybrid()
    test_detail_webinar_is_online()
    test_org_district_online_false_remain_unknown()
    test_google_forms_destination_no_auto_submit()
    test_paid_survives_clean_with_mode_and_time()
    test_month_first_dates_parse()
    test_public_source_url_scope()
    test_fetch_html_accepts_202_with_full_html()
    print("All TQM tests passed")
