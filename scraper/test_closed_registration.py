"""Closed-registration detection and catalogue-diagnostic tests.

Run: python3 scraper/test_closed_registration.py
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))

import reg_discover as rd
from reg_discover import (
    discover_generic_page,
    discover_oshc_family,
    explicit_closed_registration,
    registration_closed_count,
)

# Unit tests never consult live robots.txt.
rd.allowed = lambda url: True

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "oshc_activity")
EVENTS_JSON = os.path.join(os.path.dirname(os.path.dirname(__file__)), "events.json")
FETCH_PY = os.path.join(os.path.dirname(__file__), "fetch.py")


def _html(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


class DummySession:
    def __init__(self, mapping):
        self.mapping = mapping
        self.posts = []

    def get(self, url, **kwargs):
        html, code, final = self.mapping.get(url, ("", 200, url))
        if len(html) == 2 and not isinstance(html, str):
            pass

        class R:
            pass

        r = R()
        r.status_code = code
        r.text = html
        r.url = final or url
        return r

    def post(self, *a, **k):
        self.posts.append((a, k))
        raise RuntimeError("POST is not allowed in these tests")


def _sess(url, html, code=200):
    return DummySession({url: (html, code, url)})


def test_explicit_phrases():
    assert explicit_closed_registration("Registration closed.") 
    assert "Registration closed" in (explicit_closed_registration("Registration closed") or "")
    assert explicit_closed_registration("報名已截止，請勿再提交")
    assert explicit_closed_registration("此活動已截止報名")
    ev = explicit_closed_registration("此講座會議已經截止報名。")
    assert ev and "此講座會議已經截止報名" in ev
    assert explicit_closed_registration("Fully booked")
    assert explicit_closed_registration("Sold out")
    assert explicit_closed_registration("Enrollment closed")
    assert explicit_closed_registration("Enrolment closed")
    assert explicit_closed_registration("Application closed")
    assert explicit_closed_registration("Registration ended")
    assert explicit_closed_registration("名額已滿")
    assert explicit_closed_registration("已額滿")
    assert explicit_closed_registration("額滿")
    # "until full" is not a closed status
    assert explicit_closed_registration("額滿即止，歡迎報名") is None
    # Deadline field alone is not CLOSED
    assert explicit_closed_registration(_html("activity_open_deadline_only.html")) is None
    assert explicit_closed_registration("截止報名日期：2026年11月16日") is None
    print("explicit phrases OK")


def test_oshc_9921_fixtures():
    zh = _html("activity_9921_closed_zh.html")
    en = _html("activity_9921_closed_en.html")
    ev_zh = explicit_closed_registration(zh)
    ev_en = explicit_closed_registration(en)
    assert ev_zh and "此講座會議已經截止報名" in ev_zh, ev_zh
    assert ev_en and "has been closed" in ev_en.lower(), ev_en
    url_en = "https://sms.oshc.hk/online/activityE.aspx?activityid=9921"
    url_zh = "https://sms.oshc.hk/online/activityT.aspx?activityid=9921"
    event_en = {
        "id": "ac4470acffc73",
        "name": "Online Seminar on Office Practitioners",
        "date": "2026-11-17",
        "url": url_en,
        "source": "OSHC 職安局 研討會",
        "org": "OSHC",
    }
    event_zh = dict(event_en, url=url_zh, id="zh9921")
    r_en = discover_oshc_family(_sess(url_en, en), event_en, {})
    r_zh = discover_oshc_family(_sess(url_zh, zh), event_zh, {})
    assert r_en["status"] == "CLOSED", r_en
    assert r_en["mechanism"] == "REGISTRATION_CLOSED"
    assert r_en["destination"] == url_en
    assert r_en["discoveryMethod"] == "oshc_activity_closed_text"
    assert r_zh["status"] == "CLOSED", r_zh
    print("OSHC 9921 fixtures OK")


def test_missing_link_not_closed():
    html = "<html><body><h1>Seminar</h1><p>Details only. Contact the organiser.</p></body></html>"
    url = "https://example.org/events/detail/1"
    ev = {"id": "x", "name": "Seminar", "date": "2026-12-01", "url": url}
    result = discover_generic_page(_sess(url, html), ev, {})
    assert result["status"] != "CLOSED", result
    assert result["status"] in ("UNKNOWN",)
    assert result["mechanism"] in ("REGISTRATION_LINK_NOT_FOUND", "UNKNOWN")
    assert explicit_closed_registration(html) is None
    print("missing link not CLOSED OK")


def test_captcha_not_closed():
    html = (
        "<html><body>Attention Required! Cloudflare "
        "<div class='cf-browser-verification'>Enable JavaScript and cookies to continue. captcha</div>"
        "</body></html>"
    )
    url = "https://example.org/events/detail/2"
    ev = {"id": "c", "name": "Seminar", "date": "2026-12-01", "url": url}
    result = discover_generic_page(_sess(url, html, 403), ev, {})
    assert result["status"] != "CLOSED", result
    assert result["mechanism"] == "CAPTCHA_BLOCKED"
    print("CAPTCHA not CLOSED OK")


def test_login_required_not_closed():
    html = (
        "<html><body><h1>Sign in</h1><form>"
        "<label>Email</label><input type='text'>"
        "<label>Password</label><input type='password'>"
        "<button>Log in</button></form></body></html>"
    )
    url = "https://example.org/events/detail/3"
    ev = {"id": "l", "name": "Seminar", "date": "2026-12-01", "url": url}
    result = discover_generic_page(_sess(url, html), ev, {})
    assert result["status"] != "CLOSED", result
    assert result["status"] in ("LOGIN_REQUIRED", "UNKNOWN")
    assert result["mechanism"] in ("LOGIN_REQUIRED", "REGISTRATION_LINK_NOT_FOUND", "UNKNOWN")
    print("login required not CLOSED OK")


def test_inaccessible_not_closed():
    url = "https://sms.oshc.hk/online/activityE.aspx?activityid=9921"
    ev = {
        "id": "down",
        "name": "Online Seminar",
        "date": "2026-11-17",
        "url": url,
        "source": "OSHC",
        "org": "OSHC",
    }

    class Boom(DummySession):
        def get(self, *a, **k):
            raise OSError("network down")

    result = discover_oshc_family(Boom({}), ev, {})
    assert result["status"] != "CLOSED", result
    print("inaccessible not CLOSED OK")


def test_diagnostics_count():
    events = [
        {"id": "a", "registration": {"status": "CLOSED"}},
        {"id": "b", "registration": {"status": "OPEN"}},
        {"id": "c", "registration": {"status": "UNKNOWN"}},
        {"id": "d"},
        {"id": "e", "registration": {"status": "CLOSED", "mechanism": "GOOGLE_FORMS"}},
    ]
    assert registration_closed_count(events) == 2
    src = open(FETCH_PY, encoding="utf-8").read()
    assert 'log(f"registration_closed: {closed_n}")' in src
    assert "registration_closed_count" in src
    print("diagnostics count OK")


def test_no_manual_events_json_edit():
    before = _sha256(EVENTS_JSON)
    # Running detection must not write the production catalogue.
    test_oshc_9921_fixtures()
    after = _sha256(EVENTS_JSON)
    assert before == after
    print("events.json unchanged OK", after)


def test_gforms_closed_helper_still_present():
    import gforms

    closed_html = "This form is no longer accepting responses"
    assert gforms.detect_form_status(closed_html, "https://docs.google.com/forms/d/e/abc/viewform") == "CLOSED"
    assert (
        gforms.detect_form_status("", "https://docs.google.com/forms/d/e/abc/closedform")
        == "CLOSED"
    )
    login_html = "accounts.google.com/ServiceLogin please sign in to Google Forms"
    assert gforms.detect_form_status(login_html, "https://docs.google.com/forms/d/e/abc/viewform") == "LOGIN_REQUIRED"
    print("gforms CLOSED behavior unchanged OK")


def test_no_post_on_oshc_closed_inspect():
    url = "https://sms.oshc.hk/online/activityT.aspx?activityid=9921"
    sess = _sess(url, _html("activity_9921_closed_zh.html"))
    ev = {"id": "p", "name": "x", "date": "2026-11-17", "url": url, "source": "OSHC", "org": "OSHC"}
    discover_oshc_family(sess, ev, {})
    assert sess.posts == []
    print("no POST on OSHC inspect OK")


if __name__ == "__main__":
    sha_start = _sha256(EVENTS_JSON)
    test_explicit_phrases()
    test_oshc_9921_fixtures()
    test_missing_link_not_closed()
    test_captcha_not_closed()
    test_login_required_not_closed()
    test_inaccessible_not_closed()
    test_diagnostics_count()
    test_no_manual_events_json_edit()
    test_gforms_closed_helper_still_present()
    test_no_post_on_oshc_closed_inspect()
    assert _sha256(EVENTS_JSON) == sha_start
    print("All closed-registration tests passed")
