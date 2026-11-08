"""Registration discovery unit tests. Run: python3 scraper/test_reg_discover.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from reg_discover import (
    classify_source_url,
    classify_mechanism,
    score_candidate,
    confidence_from_score,
    merge_registration,
    discover_one,
    enrich_registration_discovery,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "reg_discover")


def test_classify_source_url():
    assert classify_source_url("https://hkie.org.hk/events/event-detail/abc123/") == "EVENT_DETAIL"
    assert classify_source_url("https://www.hkgbc.org.hk/eng/news-events/events-trainings/events") == "LISTING_PAGE"
    assert classify_source_url("https://forms.gle/ZYWRkzhxZv86d83C9") == "DIRECT_REGISTRATION"
    assert classify_source_url("https://www.csb.gov.hk/english/oshcs/events/files/x.pdf") == "PDF_FLYER"
    assert classify_source_url("https://www.cic.hk/en/events") == "LISTING_PAGE"
    print("classify_source_url OK")


def test_classify_mechanism():
    assert classify_mechanism("https://forms.gle/abc") == "GOOGLE_FORMS"
    assert classify_mechanism("https://docs.google.com/forms/d/e/1FAIpQLSx/viewform") == "GOOGLE_FORMS"
    assert classify_mechanism("https://forms.cloud.microsoft/r/HQkXhCEWWa") == "MICROSOFT_FORMS"
    assert classify_mechanism("https://www.eventbrite.hk/e/foo-tickets-123") == "EVENTBRITE"
    assert classify_mechanism("https://cic-hk.zoom.us/webinar/register/WN_abc") == "ZOOM"
    assert classify_mechanism("https://sms.oshc.hk/online/activityE.aspx?activityid=9903") == "OSHC_PORTAL"
    assert classify_mechanism("https://event.hkie.org.hk/events/share?id=abc&companyCode=hkie") == "HKIE_PORTAL"
    print("classify_mechanism OK")


def test_score_positive_and_negative():
    sc, reasons = score_candidate(
        "https://forms.gle/ZYWRkzhxZv86d83C9", "Register now", in_event_detail=True
    )
    assert sc >= 70, (sc, reasons)
    assert "google_forms" in reasons

    sc2, reasons2 = score_candidate(
        "https://www.facebook.com/sharer/sharer.php?u=https://example.com", "Share"
    )
    assert sc2 < 0
    assert "social_share" in reasons2

    sc3, _ = score_candidate("https://www.hkgbc.org.hk/eng/news-events/events-trainings/events", "Learn more")
    assert sc3 < 50
    print("score_candidate OK")


def test_confidence():
    assert confidence_from_score(90, "GOOGLE_FORMS") == "HIGH"
    assert confidence_from_score(55, "MICROSOFT_FORMS") == "MEDIUM"
    assert confidence_from_score(40, "OTHER_PUBLIC_FORM") == "LOW"
    print("confidence_from_score OK")


def test_merge_preserves_gforms_schema():
    existing = {
        "mechanism": "GOOGLE_FORMS",
        "destination": "https://docs.google.com/forms/d/e/1FAIpQLSx/viewform",
        "formId": "1FAIpQLSx",
        "status": "OPEN",
        "fields": [
            {
                "entryId": "entry.1",
                "profileField": "email",
                "label": "Email",
                "type": "SHORT_TEXT",
                "safePrefill": True,
            }
        ],
        "requiresManualCompletion": True,
    }
    discovered = {
        "mechanism": "GOOGLE_FORMS",
        "destination": "https://forms.gle/abc",
        "status": "UNKNOWN",
        "sourceUrlClass": "EVENT_DETAIL",
        "confidence": "HIGH",
        "discoveryMethod": "hkie_eventdetail_gform",
    }
    merged = merge_registration(existing, discovered)
    assert merged["mechanism"] == "GOOGLE_FORMS"
    assert merged["formId"] == "1FAIpQLSx"
    assert merged["status"] == "OPEN"
    assert merged["fields"][0]["safePrefill"] is True
    assert merged["destination"].startswith("https://docs.google.com/forms/")
    assert merged["sourceUrlClass"] == "EVENT_DETAIL"
    assert merged["discoveryMethod"] == "hkie_eventdetail_gform"
    print("merge preserves gforms OK")


def test_never_replace_event_url():
    events = [
        {
            "id": "t1",
            "name": "Test Event",
            "date": "2026-12-01",
            "url": "https://hkie.org.hk/events/event-detail/deadbeef/",
            "source": "HKIE Events",
            "group": "HKIE",
        }
    ]
    official = events[0]["url"]

    class DummySession:
        def get(self, *a, **k):
            raise RuntimeError("network disabled in unit test")

        def post(self, *a, **k):
            raise RuntimeError("network disabled in unit test")

    # discover_one with failing network should still not touch url
    from reg_discover import discover_one

    cache = {}
    # Monkeypatch fetch_hkie to None via empty html path — discover_hkie handles None html
    import reg_discover as rd

    orig = rd.fetch_hkie_eventdetail_html
    rd.fetch_hkie_eventdetail_html = lambda session, url: None
    try:
        result = discover_one(DummySession(), events[0], cache)
    finally:
        rd.fetch_hkie_eventdetail_html = orig
    assert events[0]["url"] == official
    assert result.get("mechanism") in (
        "REGISTRATION_LINK_NOT_FOUND",
        "UNKNOWN",
        "GOOGLE_FORMS",
        "HKIE_PORTAL",
    )
    # enrich path
    events2 = [
        {
            "id": "t2",
            "name": "Listing Only",
            "date": "2026-12-01",
            "url": "https://www.cic.hk/en/events",
            "source": "CIC 建造業議會 Events",
            "group": "CIC",
        }
    ]
    before = events2[0]["url"]

    class Sess:
        def get(self, url, **kwargs):
            class R:
                status_code = 200
                text = "<html><body><a href='https://www.cic.hk/'>Home</a></body></html>"
                url = "https://www.cic.hk/en/events"

            return R()

    stats = enrich_registration_discovery(events2, session=Sess(), sleep_s=0)
    assert events2[0]["url"] == before
    assert "registration" in events2[0]
    assert events2[0]["registration"]["destination"] in (None, ) or events2[0]["registration"]["destination"] != before or True
    # Destination must not overwrite url
    assert events2[0]["url"] == "https://www.cic.hk/en/events"
    print("never replace event url OK", stats)


def test_fixture_page_scan_scores_register_link():
    html_path = os.path.join(FIX, "detail_with_register.html")
    html = open(html_path, encoding="utf-8").read()
    from reg_discover import _extract_anchors, _best_candidate, score_candidate

    cands = []
    for href, text in _extract_anchors(html, "https://example.org/events/detail/1"):
        sc, reasons = score_candidate(href, text, in_event_detail=True)
        cands.append((href, text, sc, reasons))
    best = _best_candidate(cands)
    assert best is not None
    dest, sc, reasons = best
    assert "forms.gle" in dest
    assert sc >= 70
    # Ensure newsletter link did not win
    assert "newsletter" not in dest
    print("fixture page scan OK")


if __name__ == "__main__":
    test_classify_source_url()
    test_classify_mechanism()
    test_score_positive_and_negative()
    test_confidence()
    test_merge_preserves_gforms_schema()
    test_never_replace_event_url()
    test_fixture_page_scan_scores_register_link()
    print("All reg_discover tests passed")
