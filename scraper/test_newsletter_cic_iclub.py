#!/usr/bin/env python3
"""CIC i-Club newsletter discovery pilot tests (items 1–28).

Run: python3 scraper/test_newsletter_cic_iclub.py
Does not write events.json or source_health.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from newsletter.cic_iclub import (
    TRUSTED_DOMAINS,
    PassiveHttp,
    inspect_destination,
    is_trusted_sender,
    parse_message,
    process_newsletter,
)
from newsletter.normalize import (
    STATUS_ELIGIBLE,
    STATUS_REJECTED,
    STATUS_REVIEW,
    classify_registration_url,
    clean_url,
    compare_to_production,
    infer_attendance_mode,
    parse_any_date,
    parse_any_time_range,
    public_candidate_view,
)
from newsletter.run_pilot import (
    EVENTS_JSON,
    HEALTH_JSON,
    run_pilot,
    sha256_file,
    snapshot_production,
)

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "newsletter", "fixtures")
ROOT = os.path.dirname(HERE)


def _load(name: str) -> bytes:
    path = os.path.join(FIX, name)
    with open(path, "rb") as f:
        return f.read()


def _dest(name: str) -> str:
    with open(os.path.join(FIX, "destinations", name), encoding="utf-8") as f:
        return f.read()


def _dest_map() -> dict:
    path = os.path.join(FIX, "destination_map.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for url, rel in raw.items():
        html_path = os.path.join(FIX, rel)
        with open(html_path, encoding="utf-8") as f:
            out[url] = f.read()
    return out


def _process(name: str, **kwargs):
    kwargs.setdefault("destination_map", _dest_map())
    return process_newsletter(_load(name), **kwargs)


def _cand(name: str, **kwargs):
    rec = _process(name, **kwargs)
    assert rec["candidates"], f"no candidates for {name}"
    return rec, rec["candidates"][0]


def test_01_trusted_iclub_newsletter_accepted():
    rec, c = _cand("trusted_future_webinar.eml")
    assert rec["trusted"] is True
    assert rec["sender_domain"] == "cic.hk"
    assert is_trusted_sender("CIC i-Club <iclub@cic.hk>")
    assert is_trusted_sender("newsletter@cic.hk")
    assert is_trusted_sender("i-club@mail.cic.hk")
    assert c["pilot_status"] == STATUS_ELIGIBLE
    assert c["organisation"] == "CIC"
    assert c["discovery"] == "NEWSLETTER"
    assert c["source"] == "CIC i-Club Newsletter"
    print("1 trusted i-Club newsletter accepted OK")


def test_02_untrusted_sender_rejected():
    rec, c = _cand("untrusted_forward.eml")
    assert rec["trusted"] is False
    assert not is_trusted_sender("Promotions Desk <promo@example-marketing.com>")
    assert not is_trusted_sender("friend@gmail.com")
    assert c["pilot_status"] == STATUS_REJECTED
    assert "A" in c["gate_failures"]
    print("2 untrusted sender rejected OK")


def test_03_chinese_title_extraction():
    _, c = _cand("chinese_title_date.eml")
    assert "密閉空間工作安全講座" in (c["title"] or "")
    assert c.get("title_zh") and "密閉空間" in c["title_zh"]
    print("3 Chinese title extraction OK")


def test_04_bilingual_title_extraction():
    rec, c = _cand("life_first_work_at_height.eml")
    title = c.get("title") or ""
    assert "高空工作安全" in title or "高空工作安全" in (c.get("title_zh") or "")
    assert "Life First" in title or "Life First" in (c.get("title_en") or "")
    assert c.get("title_zh") and c.get("title_en")
    print("4 bilingual title extraction OK")


def test_05_date_extraction():
    _, c = _cand("chinese_title_date.eml")
    assert c["date"] == "2027-03-10"
    assert parse_any_date("2027年3月10日") == "2027-03-10"
    assert parse_any_date("18 March 2027") == "2027-03-18"
    # Life First date is official destination data, not invented in the newsletter
    _, life = _cand("life_first_work_at_height.eml")
    assert life["date"] == "2026-11-19"
    assert life.get("date_source") == "official_destination"
    print("5 date extraction OK")


def test_06_time_extraction():
    _, c = _cand("chinese_title_date.eml")
    assert c["start_time"] == "14:00"
    assert c["end_time"] == "16:00"
    assert parse_any_time_range("下午2時至4時") == ("14:00", "16:00")
    _, life = _cand("life_first_work_at_height.eml")
    # Official dest: 下午2時至3時05分
    assert life["start_time"] == "14:00"
    assert life["end_time"] == "15:05"
    assert life.get("time_source") == "official_destination"
    print("6 time extraction OK")


def test_07_zoom_webinar_registration():
    _, c = _cand("life_first_work_at_height.eml")
    reg = c["registration"]
    assert reg["mechanism"] == "ZOOM_WEBINAR"
    assert "cic-hk.zoom.us/webinar/register/WN_-U1WusN5Tq2LAxe2o70Ujw" in (reg["destination"] or "")
    mech, url = classify_registration_url(
        "https://cic-hk.zoom.us/webinar/register/WN_-U1WusN5Tq2LAxe2o70Ujw#/registration"
    )
    assert mech == "ZOOM_WEBINAR"
    print("7 Zoom webinar registration extraction OK")


def test_08_zoom_meeting_registration():
    _, c = _cand("zoom_meeting_register.eml")
    assert c["registration"]["mechanism"] == "ZOOM_MEETING"
    assert "meeting/register" in (c["registration"]["destination"] or "")
    print("8 Zoom meeting registration extraction OK")


def test_09_zoom_join_not_registration():
    _, c = _cand("zoom_join_only.eml")
    assert c["registration"]["mechanism"] is None
    dest = c["registration"].get("destination")
    assert not dest or "/j/" not in dest or "register" in (dest or "")
    # classify helper
    mech, _ = classify_registration_url("https://cic-hk.zoom.us/j/98765432101?pwd=abc")
    assert mech is None
    print("9 ordinary Zoom join link not treated as registration OK")


def test_10_webinar_is_online():
    _, c = _cand("trusted_future_webinar.eml")
    assert c["mode"] == "ONLINE"
    _, life = _cand("life_first_work_at_height.eml")
    assert life["mode"] == "ONLINE"
    print("10 Webinar => ONLINE OK")


def test_11_online_registration_alone_unknown():
    _, c = _cand("online_registration_only.eml")
    assert c["mode"] == "UNKNOWN"
    assert infer_attendance_mode(
        "CIC Technical Practice Briefing on Concrete Specification",
        "Registration: Online Registration 網上報名",
    ) == "UNKNOWN"
    print("11 Online Registration alone => UNKNOWN OK")


def test_12_work_at_height_is_hs():
    _, c = _cand("life_first_work_at_height.eml")
    assert c["type"] == "H&S"
    print("12 work-at-height => H&S OK")


def test_13_construction_safety_relevance():
    _, life = _cand("life_first_work_at_height.eml")
    assert life["civil_related"] is True
    assert "Civil" in (life.get("disc") or [])
    _, oh = _cand("generic_occupational_health.eml")
    assert oh["civil_related"] is False
    # Generic OH may still be H&S from health keywords, but must not be Civil
    # merely because the sender is CIC.
    print("13 construction-safety relevance OK")


def test_14_explicit_cpd_hours():
    _, c = _cand("explicit_cpd_hours.eml")
    assert c["hrs"] == 3 or c["hrs"] == 3.0
    assert c["hrs_est"] is False
    print("14 explicit CPD hours OK")


def test_15_estimated_duration():
    _, c = _cand("estimated_duration.eml")
    assert c["hrs"] == 2.5
    assert c["hrs_est"] is True
    print("15 estimated duration OK")


def test_16_closed_registration_rejected():
    _, c = _cand("closed_registration.eml")
    assert c["registration"]["status"] == "CLOSED"
    assert c["pilot_status"] == STATUS_REJECTED
    assert "F" in c["gate_failures"]
    _, life = _cand("life_first_work_at_height.eml")
    assert life["cancelled"] is True
    assert life["registration"]["status"] == "CLOSED"
    assert life["pilot_status"] == STATUS_REJECTED
    print("16 closed registration rejected OK")


def test_17_malformed_newsletter():
    rec, c = _cand("malformed.txt")
    assert rec["malformed"] is True
    assert c["pilot_status"] == STATUS_REJECTED
    print("17 malformed newsletter OK")


def test_18_tracking_url_cleanup():
    _, c = _cand("tracking_and_pii.eml")
    dest = c["registration"]["destination"] or ""
    assert "utm_" not in dest
    assert "fbclid" not in dest
    assert "gclid" not in dest
    assert "email=" not in dest
    assert "WN_PILOTTRACKING01" in dest
    cleaned = clean_url(
        "https://cic-hk.zoom.us/webinar/register/WN_X?utm_source=email&fbclid=1&gclid=2&email=a@b.com"
    )
    assert "utm_" not in cleaned and "fbclid" not in cleaned and "gclid" not in cleaned
    assert "email=" not in cleaned
    print("18 tracking URL cleanup OK")


def test_19_tracking_pixel_ignored():
    rec, c = _cand("tracking_and_pii.eml")
    view = public_candidate_view(c)
    blob = json.dumps({"rec": {k: rec[k] for k in rec if k != "candidates"}, "view": view, "cand": view}, ensure_ascii=False)
    # Pixel URL must not be fetched or retained in emitted payload
    assert "open.gif" not in blob
    assert "pixel.gif" not in blob
    assert "click.cic.example" not in blob
    http = PassiveHttp()
    try:
        http.get("https://click.cic.example/track/open.gif")
        raise AssertionError("pixel fetch should have been refused")
    except RuntimeError:
        pass
    assert http.gets == []
    print("19 tracking pixel ignored OK")


def test_20_recipient_pii_removed():
    rec, c = _cand("tracking_and_pii.eml")
    view = public_candidate_view(c)
    blob = json.dumps({"view": view, "provenance": c.get("provenance"), "leaks": rec.get("pii_leaks")}, ensure_ascii=False)
    assert "chan.tai.man.pilot@example.com" not in blob
    assert "Chan Tai Man" not in blob
    assert "SECRETUNSUBTOKEN99" not in blob
    assert "pii-message-id-9f3a" not in blob
    assert rec["pii_leaks"] == []
    # Full candidate dump used by the pipeline report also scrubbed in public view
    assert "chan.tai.man.pilot@example.com" not in (c.get("description") or "")
    print("20 recipient PII removed OK")


def test_21_newsletter_footer_unsubscribe_ignored():
    rec, c = _cand("tracking_and_pii.eml")
    view = public_candidate_view(c)
    blob = json.dumps(view, ensure_ascii=False) + (c.get("description") or "")
    assert "SECRETUNSUBTOKEN99" not in blob
    assert "unsubscribe?email=" not in blob
    print("21 newsletter footer/unsubscribe ignored OK")


def test_22_duplicate_against_cic_production():
    production = [
        {
            "id": "cic-cwro-test",
            "name": "Webinar on “Construction Workers Registration Ordinance” (CWRO)",
            "org": "CIC",
            "date": "2026-11-20",
            "source": "CIC 建造業議會 Events",
            "group": "CIC",
            "url": "https://www.cic.hk/eform/cwrbriefingsession/regform.aspx?lang=en-US",
            "time": "",
            "hrs": None,
            "hrs_est": False,
            "registration": {
                "mechanism": "OTHER_PUBLIC_FORM",
                "destination": "https://www.cic.hk/eform/cwrbriefingsession/regform.aspx?lang=en-US",
                "status": "UNKNOWN",
            },
        }
    ]
    rec, c = _cand("dup_cic.eml", production_events=production)
    assert c["duplicate"]["is_duplicate"] is True
    assert c["duplicate"]["matched_id"] == "cic-cwro-test"
    assert c["duplicate"].get("merge")
    # Live catalogue path: also compare against current events if present
    print("22 duplicate against CIC production event OK")


def test_23_duplicate_against_oshc_labour():
    production = [
        {
            "id": "oshc-9924",
            "name": "Physical Seminar on Construction Lifting Safety",
            "org": "OSHC",
            "date": "2026-12-04",
            "source": "OSHC 職安局 研討會",
            "group": "OSHC",
            "url": "https://sms.oshc.hk/online/activityE.aspx?activityid=9924",
            "time": "09:30-17:00",
            "hrs": 7.5,
            "hrs_est": True,
        }
    ]
    rec, c = _cand("dup_oshc_lifting.eml", production_events=production)
    assert c["duplicate"]["is_duplicate"] is True
    assert c["duplicate"]["matched_id"] == "oshc-9924"
    assert "OSHC" in (c["duplicate"].get("matched_source") or "")
    print("23 duplicate against OSHC/Labour event OK")


def test_24_uncertain_event_remains_review():
    _, c = _cand("uncertain_no_date.eml")
    assert c["pilot_status"] == STATUS_REVIEW
    assert "C" in c["gate_failures"] or "I" in c["gate_failures"] or "E" in c["gate_failures"]
    print("24 uncertain event remains REVIEW OK")


def test_25_pilot_does_not_write_events_json():
    before = sha256_file(EVENTS_JSON)
    report = run_pilot(FIX, verify=False, report_path=None)
    after = sha256_file(EVENTS_JSON)
    assert before == after
    assert report["summary"]["events_json_unchanged"] is True
    print("25 pilot does not write events.json OK")


def test_26_source_health_unchanged():
    before = sha256_file(HEALTH_JSON)
    report = run_pilot(FIX, verify=False, report_path=None)
    after = sha256_file(HEALTH_JSON)
    assert before == after
    assert report["summary"]["source_health_unchanged"] is True
    print("26 source_health.json unchanged OK")


def test_27_no_network_post():
    posts = []

    def getter(url, **kwargs):
        class R:
            status_code = 200
            text = "<html><body>ok</body></html>"
            url = url
        return R()

    probe = PassiveHttp(getter=getter)
    try:
        probe.post("https://cic-hk.zoom.us/webinar/register/WN_PILOTTRUSTEDFUTURE01", data={"name": "x"})
        raise AssertionError("POST should have been refused")
    except RuntimeError as ex:
        assert "POST is forbidden" in str(ex)
    assert probe.posts  # the refused attempt is recorded, never sent
    http = PassiveHttp(getter=getter)
    rec = process_newsletter(
        _load("trusted_future_webinar.eml"),
        http=http,
        verify=True,
        destination_map={},
    )
    assert http.posts == []
    assert rec.get("http_posts") == []
    assert rec.get("http_gets")  # GET-only inspection may run
    print("27 no network POST OK")


def test_28_no_registration_submission():
    submitted = {"posted": False}

    def getter(url, **kwargs):
        # A misbehaving client would post; our PassiveHttp never does.
        class R:
            status_code = 200
            text = "<html><form method='post' action='/webinar/register'><input name='email'></form></html>"
            url = url
        return R()

    http = PassiveHttp(getter=getter)
    process_newsletter(
        _load("trusted_future_webinar.eml"),
        http=http,
        verify=True,
        destination_map={},
    )
    assert http.posts == []
    # Confirm the helper cannot be used to submit
    try:
        http.post("https://cic-hk.zoom.us/webinar/register/WN_PILOTTRUSTEDFUTURE01", data={"email": "x@y.z"})
    except RuntimeError:
        submitted["posted"] = False
    else:
        submitted["posted"] = True
    assert submitted["posted"] is False
    print("28 no registration submission OK")


def test_paid_excluded_by_free_first():
    _, c = _cand("paid_event.eml")
    assert c["free"] is False
    assert c["pilot_status"] == STATUS_REJECTED
    assert "H" in c["gate_failures"]
    print("paid event excluded by free-first OK")


def test_trusted_domains_configured():
    assert "cic.hk" in TRUSTED_DOMAINS
    assert "cic.org.hk" in TRUSTED_DOMAINS
    print("trusted sender domains configured OK")


def test_life_first_expected_fields():
    _, c = _cand("life_first_work_at_height.eml")
    assert c["organisation"] == "CIC"
    assert c["discovery"] == "NEWSLETTER"
    assert c["type"] == "H&S"
    assert c["mode"] == "ONLINE"
    assert c["registration"]["mechanism"] == "ZOOM_WEBINAR"
    print("Life First expected fields OK")


def main():
    tests = [
        test_01_trusted_iclub_newsletter_accepted,
        test_02_untrusted_sender_rejected,
        test_03_chinese_title_extraction,
        test_04_bilingual_title_extraction,
        test_05_date_extraction,
        test_06_time_extraction,
        test_07_zoom_webinar_registration,
        test_08_zoom_meeting_registration,
        test_09_zoom_join_not_registration,
        test_10_webinar_is_online,
        test_11_online_registration_alone_unknown,
        test_12_work_at_height_is_hs,
        test_13_construction_safety_relevance,
        test_14_explicit_cpd_hours,
        test_15_estimated_duration,
        test_16_closed_registration_rejected,
        test_17_malformed_newsletter,
        test_18_tracking_url_cleanup,
        test_19_tracking_pixel_ignored,
        test_20_recipient_pii_removed,
        test_21_newsletter_footer_unsubscribe_ignored,
        test_22_duplicate_against_cic_production,
        test_23_duplicate_against_oshc_labour,
        test_24_uncertain_event_remains_review,
        test_25_pilot_does_not_write_events_json,
        test_26_source_health_unchanged,
        test_27_no_network_post,
        test_28_no_registration_submission,
        test_paid_excluded_by_free_first,
        test_trusted_domains_configured,
        test_life_first_expected_fields,
    ]
    failed = []
    for fn in tests:
        try:
            fn()
        except Exception as ex:
            failed.append((fn.__name__, type(ex).__name__, ex))
            print(f"FAIL {fn.__name__}: {type(ex).__name__}: {ex}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} newsletter pilot tests passed")
    if failed:
        for name, typ, ex in failed:
            print(f"  {name}: {typ}: {ex}")
        raise SystemExit(1)
    print("All newsletter pilot tests passed")


if __name__ == "__main__":
    main()
