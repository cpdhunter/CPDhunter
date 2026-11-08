"""
Registration destination discovery (Sprint 2C).

GET-only public discovery of registration destinations for CPD events.
Never invents URLs, never logs in, never bypasses CAPTCHA, never POSTs forms
(except reusing the existing public HKIE eventdetail organiser-content API),
never stores PII / profile values.

Discovery runs before Google Forms schema enrichment so newly found forms.gle
links can be schema-parsed. Existing Google Forms fields/formId/safePrefill
are preserved when merging.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from fetch import HEADERS, ROOT, OUT, log, allowed  # type: ignore
except Exception:  # pragma: no cover
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    OUT = os.path.join(ROOT, "events.json")
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 "
            "(compatible; CPDHunterBot/2.2; free CPD calendar)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9,zh-HK;q=0.8",
    }

    def log(*a):
        print(*a, file=sys.stderr, flush=True)

    def allowed(url):
        return True

try:
    from gforms import (
        HKIE_EVENT_DETAIL_RE,
        extract_gform_urls,
        fetch_hkie_eventdetail_html,
    )
except Exception:  # pragma: no cover
    HKIE_EVENT_DETAIL_RE = re.compile(
        r"https?://(?:www\.)?hkie\.org\.hk/(?:tc/)?events/event-detail/([A-Za-z0-9]+)/?",
        re.I,
    )

    def extract_gform_urls(text: str) -> List[str]:
        if not text:
            return []
        found = []
        seen = set()
        for m in re.finditer(
            r"""https?://(?:forms\.gle/[A-Za-z0-9_-]+|docs\.google\.com/forms/(?:d/e/|d/)[A-Za-z0-9_-]+(?:/[^"'\\\s<>]*)?)""",
            text,
            re.I,
        ):
            u = m.group(0).rstrip(").,;'\"")
            if u not in seen:
                seen.add(u)
                found.append(u)
        return found

    def fetch_hkie_eventdetail_html(session, event_page_url):
        return None


MECHANISMS = (
    "GOOGLE_FORMS",
    "MICROSOFT_FORMS",
    "EVENTBRITE",
    "ZOOM",
    "OSHC_PORTAL",
    "CIC_PORTAL",
    "HKIE_PORTAL",
    "PLAIN_HTML_FORM",
    "OTHER_PUBLIC_FORM",
    "LOGIN_REQUIRED",
    "CAPTCHA_BLOCKED",
    "REGISTRATION_CLOSED",
    "REGISTRATION_LINK_NOT_FOUND",
    "UNKNOWN",
)

URL_CLASSES = (
    "EVENT_DETAIL",
    "LISTING_PAGE",
    "DIRECT_REGISTRATION",
    "REDIRECT",
    "PDF_FLYER",
    "LOGIN_REQUIRED",
    "CAPTCHA_BLOCKED",
    "CLOSED",
    "UNKNOWN",
)

POS_TEXT = re.compile(
    r"\b(?:register|registration|enrol(?:ment)?|enroll(?:ment)?|apply|rsvp|book\s*now|sign[\s-]?up)\b|"
    r"報名|登記|立即報名|網上報名|即時報名",
    re.I,
)
NEG_TEXT = re.compile(
    r"\b(?:newsletter|subscribe|sponsorship|sponsor|donate|donation|share|facebook|twitter|linkedin|"
    r"instagram|whatsapp|wechat|map|direction|contact\s+us|learn\s+more|membership\s+application|"
    r"become\s+a\s+member|join\s+now|login|log\s*in|sign\s*in)\b|"
    r"贊助|捐款|分享|會員申請|登入",
    re.I,
)

GFORM_HOST = re.compile(r"(?:forms\.gle|docs\.google\.com/forms)", re.I)
MSFORM_HOST = re.compile(r"forms\.cloud\.microsoft|forms\.office\.com", re.I)
EVENTBRITE_HOST = re.compile(r"eventbrite\.(?:com|hk|co\.uk)", re.I)
ZOOM_HOST = re.compile(r"zoom\.us/(?:webinar/register|meeting/register|j/)", re.I)
OSHC_HOST = re.compile(r"sms\.oshc\.hk/.+activity", re.I)
HKIE_PORTAL_HOST = re.compile(r"event\.hkie\.org\.hk", re.I)
CIC_PORTAL_HOST = re.compile(r"(?:cic\.hk|bim\.cic|citac\.cic|rstc\.cic).*(?:register|enrol|apply)", re.I)

LISTING_HINTS = re.compile(
    r"/(?:events|event-list|upcoming-events|seminars_conferences|cpd-calendar|coming-events|"
    r"events-trainings/events|search)(?:/|\?|$)|/en/events$",
    re.I,
)
DETAIL_HINTS = re.compile(
    r"event-detail|events-detail|activity[ei]\.aspx|/events/[a-z0-9-]+/?$|cpd-courses/",
    re.I,
)
CAPTCHA_HINTS = re.compile(
    r"cf-browser-verification|attention required|just a moment|challenge-platform|"
    r"cf-challenge|enable javascript and cookies|captcha",
    re.I,
)
CLOSED_HINTS = re.compile(
    r"registration\s+closed|fully\s+booked|no longer accepting|報名已截止|名額已滿|已截止報名",
    re.I,
)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (s or "").lower())


def _title_sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def classify_source_url(url: str) -> str:
    """Classify the official event/source URL (not the registration destination)."""
    u = (url or "").strip()
    if not u.startswith("http"):
        return "UNKNOWN"
    ul = u.lower()
    path = urlparse(u).path or ""
    if ul.endswith(".pdf") or "/files/" in ul and ul.endswith(".pdf"):
        return "PDF_FLYER"
    if GFORM_HOST.search(u) or MSFORM_HOST.search(u) or EVENTBRITE_HOST.search(u) or ZOOM_HOST.search(u):
        return "DIRECT_REGISTRATION"
    if OSHC_HOST.search(u) or HKIE_PORTAL_HOST.search(u):
        return "DIRECT_REGISTRATION"
    if HKIE_EVENT_DETAIL_RE.match(u.split("#")[0].split("?")[0]):
        return "EVENT_DETAIL"
    if DETAIL_HINTS.search(u) and not LISTING_HINTS.search(path.rstrip("/") + "/"):
        return "EVENT_DETAIL"
    if "events-detail" in ul or "eventid=" in ul:
        return "EVENT_DETAIL"
    if LISTING_HINTS.search(u) or path.rstrip("/").endswith("/events"):
        return "LISTING_PAGE"
    if "localevents.theiet.org/network" in ul:
        return "LISTING_PAGE"
    return "UNKNOWN"


def classify_mechanism(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return "UNKNOWN"
    if GFORM_HOST.search(u):
        return "GOOGLE_FORMS"
    if MSFORM_HOST.search(u):
        return "MICROSOFT_FORMS"
    if EVENTBRITE_HOST.search(u):
        return "EVENTBRITE"
    if ZOOM_HOST.search(u):
        return "ZOOM"
    if OSHC_HOST.search(u):
        return "OSHC_PORTAL"
    if HKIE_PORTAL_HOST.search(u):
        return "HKIE_PORTAL"
    if re.search(r"(?:cic\.hk|bim\.cic\.hk|citac\.cic\.hk|rstc\.cic\.hk)", u, re.I) and re.search(
        r"register|enrol|apply|報名", u, re.I
    ):
        return "CIC_PORTAL"
    if u.lower().endswith(".pdf"):
        return "OTHER_PUBLIC_FORM"
    if "oshsreg.gov.hk" in u.lower():
        return "OTHER_PUBLIC_FORM"
    return "OTHER_PUBLIC_FORM"


def score_candidate(
    href: str,
    link_text: str = "",
    *,
    in_event_detail: bool = False,
    title_match: float = 0.0,
    structured: bool = False,
) -> Tuple[int, List[str]]:
    """
    Deterministic candidate score. Higher is better.
    Returns (score, reason_tags). Negative / low scores should not be stored as destinations.
    """
    href = (href or "").strip()
    text = (link_text or "").strip()
    reasons: List[str] = []
    score = 0
    if not href.startswith("http"):
        return -100, ["not_http"]

    hl = href.lower()
    # Hard negatives
    if any(
        x in hl
        for x in (
            "facebook.com/sharer",
            "twitter.com/intent",
            "linkedin.com/share",
            "mailto:",
            "javascript:",
            "wa.me/",
            "api.whatsapp",
        )
    ):
        return -50, ["social_share"]
    if re.search(
        r"/(?:login|signin|sign-in|membership/join|become-a-member|memberprofile/registration|"
        r"member-registration|join-us|membership|school-ambassadors-programme)(?:/|\?|$)",
        hl,
    ):
        return -40, ["membership_or_login"]
    if "memberprofile" in hl or "membership" in hl or "school-ambassadors" in hl:
        return -40, ["membership_or_login"]
    # HKIE site chrome "Registration" pointing at non-event programmes
    if "hkie.org.hk" in hl and "cpd-courses" not in hl and "event-detail" not in hl:
        if hl.rstrip("/").endswith("/registration") or "/registration/" in hl:
            return -35, ["site_chrome_registration"]
    if NEG_TEXT.search(text) and not POS_TEXT.search(text):
        score -= 25
        reasons.append("neg_text")

    # Strong destination hosts
    if GFORM_HOST.search(href):
        score += 80
        reasons.append("google_forms")
    elif MSFORM_HOST.search(href):
        score += 80
        reasons.append("microsoft_forms")
    elif EVENTBRITE_HOST.search(href):
        score += 70
        reasons.append("eventbrite")
    elif ZOOM_HOST.search(href):
        score += 70
        reasons.append("zoom_reg")
    elif OSHC_HOST.search(href):
        score += 75
        reasons.append("oshc_portal")
    elif HKIE_PORTAL_HOST.search(href):
        score += 70
        reasons.append("hkie_portal")
    elif href.lower().endswith(".pdf") and ("labour.gov.hk" in hl or "csb.gov.hk" in hl or "oshc" in hl):
        score += 55
        reasons.append("official_pdf")
    elif href.lower().endswith(".pdf"):
        score += 25
        reasons.append("pdf")

    if POS_TEXT.search(text) or POS_TEXT.search(href):
        score += 35
        reasons.append("pos_text")
    if structured:
        score += 40
        reasons.append("structured")
    if in_event_detail:
        score += 20
        reasons.append("in_detail")
    if title_match >= 0.92:
        score += 30
        reasons.append("title_exactish")
    elif title_match >= 0.75:
        score += 15
        reasons.append("title_close")

    # Generic homepage / listing penalty
    path = urlparse(href).path or ""
    if path in ("", "/") or LISTING_HINTS.search(href):
        if not (GFORM_HOST.search(href) or MSFORM_HOST.search(href) or OSHC_HOST.search(href)):
            score -= 40
            reasons.append("generic_listing")

    return score, reasons


def confidence_from_score(score: int, mechanism: str, reasons: Optional[list] = None) -> str:
    reasons = reasons or []
    if mechanism in ("GOOGLE_FORMS", "MICROSOFT_FORMS", "OSHC_PORTAL", "HKIE_PORTAL", "EVENTBRITE", "ZOOM"):
        if score >= 70:
            return "HIGH"
        if score >= 50:
            return "MEDIUM"
    if score >= 90:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    # In-detail "Register" / 報名 link to an official-looking destination
    if score >= 55 and "pos_text" in reasons and "in_detail" in reasons:
        return "MEDIUM"
    return "LOW"


def _safe_get(
    session: requests.Session, url: str, timeout: int = 40
) -> Tuple[str, str, int]:
    """GET only. Returns (final_url, text, status_code)."""
    r = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    return (r.url or url), (r.text or ""), r.status_code


def _detect_page_blockers(html: str, status_code: int, final_url: str) -> Optional[str]:
    """Return CAPTCHA_BLOCKED / LOGIN_REQUIRED / None."""
    if status_code in (401, 403):
        if CAPTCHA_HINTS.search(html or "") or status_code == 403:
            # ICE / Cloudflare often 403 with challenge body
            if CAPTCHA_HINTS.search(html or "") or "cloudflare" in (html or "").lower() or status_code == 403:
                return "CAPTCHA_BLOCKED"
        return "LOGIN_REQUIRED"
    if CAPTCHA_HINTS.search(html or "") and len(html or "") < 20000 and "cf-" in (html or "").lower():
        return "CAPTCHA_BLOCKED"
    hl = (html or "").lower()
    if ("sign in" in hl or "log in" in hl) and "password" in hl and len(html or "") < 15000:
        if not POS_TEXT.search(html or ""):
            return "LOGIN_REQUIRED"
    return None


def _extract_anchors(html: str, base: str) -> List[Tuple[str, str]]:
    """Return list of (abs_url, link_text)."""
    out: List[Tuple[str, str]] = []
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        abs_u = urljoin(base, href)
        if abs_u.startswith("http"):
            out.append((abs_u, a.get_text(" ", strip=True)[:200]))
    # Also raw URL hosts in HTML (forms.gle etc. in JS/JSON)
    for u in extract_gform_urls(html):
        out.append((u, "google forms"))
    for m in MSFORM_HOST.finditer(html):
        # expand to full URL nearby
        start = max(0, m.start() - 20)
        frag = html[start : m.end() + 80]
        um = re.search(r"https?://forms\.cloud\.microsoft/[A-Za-z0-9_./\-?=&%]+", frag, re.I)
        if um:
            out.append((um.group(0).rstrip(").,\"'"), "microsoft forms"))
    for m in re.finditer(
        r"https?://(?:www\.)?eventbrite\.(?:com|hk|co\.uk)/e/[A-Za-z0-9\-]+", html, re.I
    ):
        out.append((m.group(0), "eventbrite"))
    for m in re.finditer(
        r"https?://[A-Za-z0-9.-]*zoom\.us/(?:webinar/register|meeting/register)/[A-Za-z0-9_?=&%\-]+",
        html,
        re.I,
    ):
        out.append((m.group(0), "zoom register"))
    for m in re.finditer(
        r"https?://event\.hkie\.org\.hk/events/share\?[A-Za-z0-9_=&%\-]+", html, re.I
    ):
        out.append((m.group(0), "hkie portal"))
    for m in re.finditer(
        r"https?://sms\.oshc\.hk/online/activity[ei]\.aspx\?activityid=\d+", html, re.I
    ):
        out.append((m.group(0), "oshc activity"))
    return out


def _best_candidate(
    candidates: List[Tuple[str, str, int, List[str]]],
) -> Optional[Tuple[str, int, List[str]]]:
    """Pick highest-scoring unique href. candidates: (href, text, score, reasons)."""
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[2])
    if best[2] < 50:
        return None
    return best[0], best[2], best[3]


def discover_hkie(session: requests.Session, event: dict) -> Optional[dict]:
    url = (event.get("url") or "").strip()
    m = HKIE_EVENT_DETAIL_RE.match(url.split("#")[0].split("?")[0])
    if not m:
        return None
    html = fetch_hkie_eventdetail_html(session, url)
    src_class = "EVENT_DETAIL"
    if not html:
        return {
            "mechanism": "REGISTRATION_LINK_NOT_FOUND",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": src_class,
            "confidence": "LOW",
            "discoveryMethod": "hkie_eventdetail_empty",
        }
    # Prefer Google Forms, then Eventbrite, then HKIE portal
    gforms = extract_gform_urls(html)
    if gforms:
        return {
            "mechanism": "GOOGLE_FORMS",
            "destination": gforms[0],
            "status": "UNKNOWN",  # schema enrich will set OPEN/CLOSED
            "sourceUrlClass": src_class,
            "confidence": "HIGH",
            "discoveryMethod": "hkie_eventdetail_gform",
        }
    eb = re.findall(r"https?://(?:www\.)?eventbrite\.(?:com|hk|co\.uk)/e/[A-Za-z0-9\-]+", html, re.I)
    if eb:
        return {
            "mechanism": "EVENTBRITE",
            "destination": eb[0],
            "status": "OPEN",
            "sourceUrlClass": src_class,
            "confidence": "HIGH",
            "discoveryMethod": "hkie_eventdetail_eventbrite",
        }
    portal = re.findall(
        r"https?://event\.hkie\.org\.hk/events/share\?[A-Za-z0-9_=&%\-]+", html, re.I
    )
    if portal:
        return {
            "mechanism": "HKIE_PORTAL",
            "destination": portal[0],
            "status": "LOGIN_REQUIRED",
            "sourceUrlClass": src_class,
            "confidence": "HIGH",
            "discoveryMethod": "hkie_eventdetail_portal",
        }
    if CLOSED_HINTS.search(html):
        return {
            "mechanism": "REGISTRATION_CLOSED",
            "destination": None,
            "status": "CLOSED",
            "sourceUrlClass": src_class,
            "confidence": "MEDIUM",
            "discoveryMethod": "hkie_eventdetail_closed_text",
        }
    return {
        "mechanism": "REGISTRATION_LINK_NOT_FOUND",
        "destination": None,
        "status": "UNKNOWN",
        "sourceUrlClass": src_class,
        "confidence": "LOW",
        "discoveryMethod": "hkie_eventdetail_no_reg_link",
    }


def _load_hkgbc_index(session: requests.Session, cache: dict) -> List[dict]:
    """Parse HKGBC listing into [{date, title, detail_url}]."""
    key = "hkgbc_index"
    if key in cache:
        return cache[key]
    url = "https://www.hkgbc.org.hk/eng/news-events/events-trainings/events"
    out: List[dict] = []
    try:
        final, html, code = _safe_get(session, url)
        if code != 200:
            cache[key] = out
            return out
        # Date then detail link nearby
        for m in re.finditer(
            r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}).{0,200}?events-detail\?eventId=(\d+)",
            html,
            re.S | re.I,
        ):
            date_s = m.group(1)
            eid = m.group(2)
            # title often after date in same card
            frag = m.group(0)
            title_m = re.search(r"events-detail\?eventId=\d+[\"'][^>]*>([^<]{8,200})", frag)
            title = title_m.group(1).strip() if title_m else f"HKGBC event {eid}"
            # normalize date
            from fetch import parse_date  # local import

            d = parse_date(date_s)
            if d:
                out.append(
                    {
                        "date": d,
                        "title": title,
                        "detail_url": f"https://www.hkgbc.org.hk/eng/news-events/events-trainings/events-detail?eventId={eid}",
                    }
                )
        # Also parse anchors with parent context
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "events-detail?eventId=" not in href:
                continue
            parent = a.find_parent(["div", "li", "article", "tr"])
            ctx = parent.get_text(" ", strip=True) if parent else a.get_text(" ", strip=True)
            from fetch import parse_date

            d = parse_date(ctx)
            if not d:
                continue
            abs_u = urljoin(final, href)
            title = a.get_text(" ", strip=True) or ctx[:120]
            if not any(x["detail_url"] == abs_u and x["date"] == d for x in out):
                out.append({"date": d, "title": title[:200], "detail_url": abs_u})
    except Exception as ex:
        log(f"  reg_discover: hkgbc index fail: {ex}")
    cache[key] = out
    return out


def discover_hkgbc(session: requests.Session, event: dict, cache: dict) -> Optional[dict]:
    src = (event.get("source") or "") + " " + (event.get("group") or "")
    if "HKGBC" not in src and "hkgbc" not in (event.get("url") or "").lower():
        return None
    src_class = classify_source_url(event.get("url") or "")
    index = _load_hkgbc_index(session, cache)
    date = event.get("date")
    name = event.get("name") or ""
    # Match by date; require title similarity unless only one card that day
    same_day = [x for x in index if x.get("date") == date]
    if not same_day:
        return {
            "mechanism": "REGISTRATION_LINK_NOT_FOUND",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": src_class,
            "confidence": "LOW",
            "discoveryMethod": "hkgbc_no_detail_for_date",
        }
    ranked = sorted(same_day, key=lambda x: _title_sim(name, x.get("title") or ""), reverse=True)
    pick = None
    if len(same_day) == 1:
        # Only safe if event title is generic or matches
        sim = _title_sim(name, same_day[0].get("title") or "")
        if sim >= 0.5 or _norm(name) in ("hkgbcevent", "supportingevent", "hkgbc"):
            pick = same_day[0]
        elif sim >= 0.75:
            pick = same_day[0]
    else:
        if _title_sim(name, ranked[0].get("title") or "") >= 0.75:
            pick = ranked[0]
        elif _norm(name) in ("hkgbcevent",) and len(same_day) == 1:
            pick = ranked[0]
    if not pick:
        # Generic "HKGBC Event": if multiple same-day cards, probe for a form destination
        if _norm(name) == "hkgbcevent" and same_day:
            form_picks = []
            for card in same_day:
                detail = card["detail_url"]
                try:
                    pages = cache.setdefault("pages", {})
                    if detail not in pages:
                        final, html, code = _safe_get(session, detail)
                        pages[detail] = (final, html, code)
                        time.sleep(0.35)
                    else:
                        final, html, code = pages[detail]
                except Exception:
                    continue
                for href, text in _extract_anchors(html, final):
                    sc, reasons = score_candidate(href, text, in_event_detail=True, title_match=0.9)
                    if sc >= 70 and classify_mechanism(href) in (
                        "GOOGLE_FORMS",
                        "MICROSOFT_FORMS",
                        "EVENTBRITE",
                        "ZOOM",
                    ):
                        form_picks.append((card, href, sc, reasons, classify_mechanism(href)))
            if len(form_picks) == 1:
                card, href, sc, reasons, mech = form_picks[0]
                return {
                    "mechanism": mech,
                    "destination": href,
                    "status": "OPEN",
                    "sourceUrlClass": "EVENT_DETAIL",
                    "confidence": "HIGH",
                    "discoveryMethod": "hkgbc_generic_unique_form_" + ",".join(reasons[:3]),
                }
            return {
                "mechanism": "REGISTRATION_LINK_NOT_FOUND",
                "destination": None,
                "status": "UNKNOWN",
                "sourceUrlClass": src_class,
                "confidence": "LOW",
                "discoveryMethod": "hkgbc_ambiguous_date_match",
            }
        if _norm(name) in ("hkgbcevent", "supportingevent") and len(same_day) == 1:
            pick = same_day[0]
        else:
            return {
                "mechanism": "REGISTRATION_LINK_NOT_FOUND",
                "destination": None,
                "status": "UNKNOWN",
                "sourceUrlClass": src_class,
                "confidence": "LOW",
                "discoveryMethod": "hkgbc_ambiguous_date_match",
            }
    detail = pick["detail_url"]
    try:
        if detail in cache.get("pages", {}):
            final, html, code = cache["pages"][detail]
        else:
            final, html, code = _safe_get(session, detail)
            cache.setdefault("pages", {})[detail] = (final, html, code)
            time.sleep(0.4)
    except Exception as ex:
        log(f"  reg_discover: hkgbc detail fail: {ex}")
        return {
            "mechanism": "REGISTRATION_LINK_NOT_FOUND",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": "EVENT_DETAIL",
            "confidence": "LOW",
            "discoveryMethod": "hkgbc_detail_fetch_fail",
        }
    cands = []
    for href, text in _extract_anchors(html, final):
        sc, reasons = score_candidate(href, text, in_event_detail=True, title_match=0.9)
        if sc >= 50:
            cands.append((href, text, sc, reasons))
    best = _best_candidate(cands)
    if best:
        dest, sc, reasons = best
        mech = classify_mechanism(dest)
        return {
            "mechanism": mech,
            "destination": dest,
            "status": "OPEN",
            "sourceUrlClass": "EVENT_DETAIL",
            "confidence": confidence_from_score(sc, mech, reasons),
            "discoveryMethod": "hkgbc_detail_" + ",".join(reasons[:3]),
        }
    return {
        "mechanism": "REGISTRATION_LINK_NOT_FOUND",
        "destination": None,
        "status": "UNKNOWN",
        "sourceUrlClass": "EVENT_DETAIL",
        "confidence": "LOW",
        "discoveryMethod": "hkgbc_detail_no_reg",
    }


def _load_oshc_index(session: requests.Session, cache: dict) -> List[dict]:
    key = "oshc_index"
    if key in cache:
        return cache[key]
    out: List[dict] = []
    url = "https://www.oshc.org.hk/eng/main/training/seminars_conferences/"
    try:
        final, html, code = _safe_get(session, url, timeout=50)
        if code == 200:
            # checkButtonClick('eng', 'seminars_conferences', 'TITLE', 'URL'
            pat = re.compile(
                r"checkButtonClick\(\s*'eng'\s*,\s*'seminars_conferences'\s*,\s*'((?:\\'|[^'])*)'\s*,\s*'((?:\\'|[^'])*)'",
                re.I,
            )
            for m in pat.finditer(html):
                title = m.group(1).replace("\\'", "'")
                href = m.group(2).replace("\\'", "'").strip()
                if href.startswith("http"):
                    out.append({"title": title, "url": href})
    except Exception as ex:
        log(f"  reg_discover: oshc index fail: {ex}")
    # CSB coming-events also carries direct activity / PDF links
    try:
        csb = "https://www.csb.gov.hk/english/oshcs/events/coming-events.html"
        final, html, code = _safe_get(session, csb)
        if code == 200:
            soup = BeautifulSoup(html, "html.parser")
            from fetch import parse_date

            for tr in soup.find_all("tr"):
                tds = tr.find_all(["td", "th"])
                if len(tds) < 2:
                    continue
                d = parse_date(tds[0].get_text(strip=True))
                a = tds[1].find("a", href=True)
                if not a:
                    continue
                href = urljoin(final, (a.get("href") or "").strip())
                title = a.get_text(" ", strip=True) or tds[1].get_text(" ", strip=True)
                if href.startswith("http"):
                    out.append({"title": title, "url": href, "date": d})
    except Exception as ex:
        log(f"  reg_discover: csb index fail: {ex}")
    cache[key] = out
    return out


def discover_oshc_family(session: requests.Session, event: dict, cache: dict) -> Optional[dict]:
    src = (event.get("source") or "") + (event.get("group") or "") + (event.get("org") or "")
    url = (event.get("url") or "").lower()
    if not any(
        x in src or x in url
        for x in ("OSHC", "oshc", "公務員", "CSB", "csb.gov", "勞工處", "Labour", "oshsreg")
    ):
        return None
    src_class = classify_source_url(event.get("url") or "")
    # Direct activity / PDF already on event.url
    eu = (event.get("url") or "").strip()
    if OSHC_HOST.search(eu):
        return {
            "mechanism": "OSHC_PORTAL",
            "destination": eu.split("#")[0],
            "status": "OPEN",
            "sourceUrlClass": "DIRECT_REGISTRATION",
            "confidence": "HIGH",
            "discoveryMethod": "event_url_oshc_activity",
        }
    if eu.lower().endswith(".pdf") and ("labour.gov.hk" in eu.lower() or "csb.gov.hk" in eu.lower()):
        return {
            "mechanism": "OTHER_PUBLIC_FORM",
            "destination": eu,
            "status": "OPEN",
            "sourceUrlClass": "PDF_FLYER",
            "confidence": "HIGH",
            "discoveryMethod": "event_url_pdf_flyer",
        }

    index = _load_oshc_index(session, cache)
    name = event.get("name") or ""
    date = event.get("date")
    best = None
    best_sim = 0.0
    for item in index:
        sim = _title_sim(name, item.get("title") or "")
        if item.get("date") and date and item["date"] != date:
            # soft penalty — still allow strong title match
            if sim < 0.85:
                continue
        if sim > best_sim:
            best_sim = sim
            best = item
    if best and best_sim >= 0.72:
        dest = best["url"]
        mech = classify_mechanism(dest)
        if dest.lower().endswith(".pdf"):
            mech = "OTHER_PUBLIC_FORM"
        status = "OPEN"
        # Light closed check for OSHC activity pages (GET only)
        if mech == "OSHC_PORTAL":
            try:
                pages = cache.setdefault("pages", {})
                if dest not in pages:
                    final, html, code = _safe_get(session, dest)
                    pages[dest] = (final, html, code)
                    time.sleep(0.3)
                else:
                    final, html, code = pages[dest]
                hl = (html or "").lower()
                if "registration closed" in hl or "報名已截止" in html or "activity is closed" in hl:
                    return {
                        "mechanism": "REGISTRATION_CLOSED",
                        "destination": dest,
                        "status": "CLOSED",
                        "sourceUrlClass": src_class,
                        "confidence": "HIGH",
                        "discoveryMethod": f"oshc_title_match_closed:{best_sim:.2f}",
                    }
            except Exception:
                pass
        return {
            "mechanism": mech,
            "destination": dest,
            "status": status,
            "sourceUrlClass": src_class,
            "confidence": "HIGH" if best_sim >= 0.85 else "MEDIUM",
            "discoveryMethod": f"oshc_title_match:{best_sim:.2f}",
        }

    # Labour listing with no per-talk URL — do not invent a destination
    if "oshsreg.gov.hk" in url:
        return {
            "mechanism": "REGISTRATION_LINK_NOT_FOUND",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": "LISTING_PAGE",
            "confidence": "LOW",
            "discoveryMethod": "labour_oshsreg_listing_no_per_event_link",
        }
    return {
        "mechanism": "REGISTRATION_LINK_NOT_FOUND",
        "destination": None,
        "status": "UNKNOWN",
        "sourceUrlClass": src_class,
        "confidence": "LOW",
        "discoveryMethod": "oshc_family_no_match",
    }


def discover_ice(session: requests.Session, event: dict, cache: dict) -> Optional[dict]:
    url = (event.get("url") or "").strip()
    if "ice.org.uk" not in url.lower():
        return None
    src_class = classify_source_url(url)
    try:
        pages = cache.setdefault("pages", {})
        if url in pages:
            final, html, code = pages[url]
        else:
            final, html, code = _safe_get(session, url)
            pages[url] = (final, html, code)
            time.sleep(0.4)
    except Exception as ex:
        return {
            "mechanism": "CAPTCHA_BLOCKED",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": src_class,
            "confidence": "MEDIUM",
            "discoveryMethod": f"ice_fetch_error:{type(ex).__name__}",
        }
    block = _detect_page_blockers(html, code, final)
    if block == "CAPTCHA_BLOCKED" or code == 403:
        return {
            "mechanism": "CAPTCHA_BLOCKED",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": "CAPTCHA_BLOCKED",
            "confidence": "HIGH",
            "discoveryMethod": "ice_cloudflare_or_403",
        }
    cands = []
    for href, text in _extract_anchors(html, final):
        sc, reasons = score_candidate(href, text, in_event_detail=True)
        if sc >= 50:
            cands.append((href, text, sc, reasons))
    best = _best_candidate(cands)
    if best:
        dest, sc, reasons = best
        mech = classify_mechanism(dest)
        return {
            "mechanism": mech,
            "destination": dest,
            "status": "OPEN",
            "sourceUrlClass": src_class,
            "confidence": confidence_from_score(sc, mech, reasons),
            "discoveryMethod": "ice_page_" + ",".join(reasons[:3]),
        }
    return {
        "mechanism": "REGISTRATION_LINK_NOT_FOUND",
        "destination": None,
        "status": "UNKNOWN",
        "sourceUrlClass": src_class,
        "confidence": "LOW",
        "discoveryMethod": "ice_no_reg_link",
    }


def discover_generic_page(session: requests.Session, event: dict, cache: dict) -> Optional[dict]:
    url = (event.get("url") or "").strip()
    if not url.startswith("http"):
        return None
    src_class = classify_source_url(url)
    # Direct registration URL already
    if src_class == "DIRECT_REGISTRATION":
        mech = classify_mechanism(url)
        return {
            "mechanism": mech,
            "destination": url.split("#")[0],
            "status": "OPEN",
            "sourceUrlClass": src_class,
            "confidence": "HIGH",
            "discoveryMethod": "event_url_direct_reg",
        }
    if src_class == "PDF_FLYER":
        return {
            "mechanism": "OTHER_PUBLIC_FORM",
            "destination": url,
            "status": "OPEN",
            "sourceUrlClass": src_class,
            "confidence": "HIGH",
            "discoveryMethod": "event_url_pdf",
        }
    try:
        if not allowed(url):
            return {
                "mechanism": "REGISTRATION_LINK_NOT_FOUND",
                "destination": None,
                "status": "UNKNOWN",
                "sourceUrlClass": src_class,
                "confidence": "LOW",
                "discoveryMethod": "robots_blocked",
            }
        pages = cache.setdefault("pages", {})
        if url in pages:
            final, html, code = pages[url]
        else:
            final, html, code = _safe_get(session, url)
            pages[url] = (final, html, code)
            time.sleep(0.35)
    except Exception as ex:
        return {
            "mechanism": "UNKNOWN",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": src_class,
            "confidence": "LOW",
            "discoveryMethod": f"fetch_error:{type(ex).__name__}",
        }
    block = _detect_page_blockers(html, code, final)
    if block:
        return {
            "mechanism": block,
            "destination": None,
            "status": "LOGIN_REQUIRED" if block == "LOGIN_REQUIRED" else "UNKNOWN",
            "sourceUrlClass": block,
            "confidence": "MEDIUM",
            "discoveryMethod": f"page_{block.lower()}",
        }
    if code >= 400:
        return {
            "mechanism": "REGISTRATION_LINK_NOT_FOUND",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": src_class,
            "confidence": "LOW",
            "discoveryMethod": f"http_{code}",
        }
    # Thin JS shell (IET etc.)
    if len(html) < 1500 and "localevents.theiet" in url:
        return {
            "mechanism": "UNKNOWN",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": src_class,
            "confidence": "LOW",
            "discoveryMethod": "iet_js_shell_or_ssl",
        }
    in_detail = src_class == "EVENT_DETAIL"
    cands = []
    for href, text in _extract_anchors(html, final):
        # skip self listing
        if href.rstrip("/") == url.rstrip("/"):
            continue
        sc, reasons = score_candidate(
            href, text, in_event_detail=in_detail, title_match=_title_sim(event.get("name") or "", text)
        )
        if sc >= 50:
            cands.append((href, text, sc, reasons))
    best = _best_candidate(cands)
    if best:
        dest, sc, reasons = best
        # Never replace / confuse official url: destination must differ or be direct form
        mech = classify_mechanism(dest)
        conf = confidence_from_score(sc, mech, reasons)
        if conf == "LOW":
            return {
                "mechanism": "REGISTRATION_LINK_NOT_FOUND",
                "destination": None,
                "status": "UNKNOWN",
                "sourceUrlClass": src_class,
                "confidence": "LOW",
                "discoveryMethod": "low_confidence_candidate",
            }
        return {
            "mechanism": mech,
            "destination": dest,
            "status": "OPEN",
            "sourceUrlClass": src_class,
            "confidence": conf,
            "discoveryMethod": "page_scan_" + ",".join(reasons[:3]),
        }
    if CLOSED_HINTS.search(html or ""):
        return {
            "mechanism": "REGISTRATION_CLOSED",
            "destination": None,
            "status": "CLOSED",
            "sourceUrlClass": src_class,
            "confidence": "MEDIUM",
            "discoveryMethod": "page_closed_text",
        }
    return {
        "mechanism": "REGISTRATION_LINK_NOT_FOUND",
        "destination": None,
        "status": "UNKNOWN",
        "sourceUrlClass": src_class,
        "confidence": "LOW",
        "discoveryMethod": "page_no_candidate",
    }


def discover_one(session: requests.Session, event: dict, cache: dict) -> dict:
    """
    Discover registration metadata for one event. Never mutates event['url'].
    Always returns a registration dict (may be NOT_FOUND).
    """
    url = (event.get("url") or "").strip()
    base_class = classify_source_url(url)
    # Preserve official URL separately — callers must not overwrite event['url']
    official_url = url

    try:
        result = None
        # Family-specific first
        if HKIE_EVENT_DETAIL_RE.match((url or "").split("#")[0].split("?")[0]):
            result = discover_hkie(session, event)
        if result is None:
            result = discover_hkgbc(session, event, cache)
        if result is None:
            result = discover_oshc_family(session, event, cache)
        if result is None and "ice.org.uk" in url.lower():
            result = discover_ice(session, event, cache)
        if result is None:
            result = discover_generic_page(session, event, cache)
        if result is None:
            result = {
                "mechanism": "REGISTRATION_LINK_NOT_FOUND",
                "destination": None,
                "status": "UNKNOWN",
                "sourceUrlClass": base_class,
                "confidence": "LOW",
                "discoveryMethod": "no_strategy",
            }
    except Exception as ex:
        log(f"  reg_discover: error {event.get('id')}: {type(ex).__name__}: {ex}")
        result = {
            "mechanism": "UNKNOWN",
            "destination": None,
            "status": "UNKNOWN",
            "sourceUrlClass": base_class,
            "confidence": "LOW",
            "discoveryMethod": f"exception:{type(ex).__name__}",
        }

    # Precision: drop destination when confidence too low (unless closed/captcha/login markers)
    conf = result.get("confidence") or "LOW"
    mech = result.get("mechanism") or "UNKNOWN"
    if conf == "LOW" and mech not in (
        "CAPTCHA_BLOCKED",
        "LOGIN_REQUIRED",
        "REGISTRATION_CLOSED",
        "REGISTRATION_LINK_NOT_FOUND",
        "UNKNOWN",
    ):
        result["destination"] = None
        result["mechanism"] = "REGISTRATION_LINK_NOT_FOUND"
        result["discoveryMethod"] = (result.get("discoveryMethod") or "") + "|dropped_low_conf"

    # Never store destination equal to inventing — must be http
    dest = result.get("destination")
    if dest is not None and not str(dest).startswith("http"):
        result["destination"] = None
        result["mechanism"] = "REGISTRATION_LINK_NOT_FOUND"

    # Reject membership / generic portal false positives
    if isinstance(dest, str) and re.search(
        r"memberprofile|membership|/join(?:/|$)|become-a-member", dest, re.I
    ):
        result["destination"] = None
        result["mechanism"] = "REGISTRATION_LINK_NOT_FOUND"
        result["confidence"] = "LOW"
        result["discoveryMethod"] = (result.get("discoveryMethod") or "") + "|rejected_membership_url"

    # Do not treat the official listing URL itself as a "discovered" destination
    if (
        isinstance(dest, str)
        and official_url
        and dest.rstrip("/") == official_url.rstrip("/")
        and classify_source_url(official_url) == "LISTING_PAGE"
    ):
        result["destination"] = None
        if result.get("mechanism") not in (
            "CAPTCHA_BLOCKED",
            "LOGIN_REQUIRED",
            "REGISTRATION_CLOSED",
        ):
            result["mechanism"] = "REGISTRATION_LINK_NOT_FOUND"
            result["confidence"] = "LOW"
        result["discoveryMethod"] = (result.get("discoveryMethod") or "") + "|rejected_self_listing"

    # Safety: ensure we did not ask caller to change official url
    result.setdefault("sourceUrlClass", base_class)
    result["_officialUrlUnchanged"] = official_url  # stripped before attach
    return result


def merge_registration(existing: Optional[dict], discovered: dict) -> dict:
    """
    Merge discovery into existing registration.
    Preserve Google Forms schema fields/formId/safePrefill/requiresManualCompletion.
    Never keep profile values.
    """
    discovered = dict(discovered)
    discovered.pop("_officialUrlUnchanged", None)
    if not existing:
        # Strip null destination key noise? keep explicit null for not-found
        out = {
            "mechanism": discovered.get("mechanism") or "UNKNOWN",
            "destination": discovered.get("destination"),
            "status": discovered.get("status") or "UNKNOWN",
            "sourceUrlClass": discovered.get("sourceUrlClass") or "UNKNOWN",
            "confidence": discovered.get("confidence") or "LOW",
            "discoveryMethod": discovered.get("discoveryMethod") or "",
        }
        return out

    out = dict(existing)
    # Always enhance discovery fields
    for k in ("sourceUrlClass", "confidence", "discoveryMethod"):
        if discovered.get(k):
            out[k] = discovered[k]

    exist_mech = existing.get("mechanism")
    disc_mech = discovered.get("mechanism")

    if exist_mech == "GOOGLE_FORMS":
        # Preserve schema; only fill destination/status gaps
        if discovered.get("destination") and not existing.get("destination"):
            out["destination"] = discovered["destination"]
        if disc_mech == "GOOGLE_FORMS" and discovered.get("destination"):
            # keep existing destination (canonical viewform) if present
            out["destination"] = existing.get("destination") or discovered["destination"]
        out["mechanism"] = "GOOGLE_FORMS"
        # status: prefer existing OPEN/CLOSED from schema parse
        if existing.get("status") in ("OPEN", "CLOSED", "LOGIN_REQUIRED"):
            out["status"] = existing["status"]
        elif discovered.get("status"):
            out["status"] = discovered["status"]
        return out

    # Non-gforms existing: prefer higher-confidence discovery
    rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    if rank.get(discovered.get("confidence") or "LOW", 0) >= rank.get(
        existing.get("confidence") or "LOW", 0
    ):
        out["mechanism"] = disc_mech or exist_mech
        if discovered.get("destination") is not None:
            out["destination"] = discovered.get("destination")
        if discovered.get("status"):
            out["status"] = discovered["status"]
    return out


def enrich_registration_discovery(
    events: List[dict],
    *,
    session: Optional[requests.Session] = None,
    sleep_s: float = 0.25,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """
    Attach/merge registration discovery metadata on each event.
    Never modifies event['url']. Never stores PII.
    """
    sess = session or requests.Session()
    stats = {
        "scanned": 0,
        "with_destination": 0,
        "errors": 0,
        "by_mechanism": {},
    }
    cache: dict = {}
    n = 0
    for ev in events:
        if limit is not None and n >= limit:
            break
        n += 1
        stats["scanned"] += 1
        official = ev.get("url")
        try:
            discovered = discover_one(sess, ev, cache)
            # Guarantee url not replaced
            if ev.get("url") != official:
                ev["url"] = official
            discovered.pop("_officialUrlUnchanged", None)
            merged = merge_registration(ev.get("registration"), discovered)
            # PII guard
            blob = json.dumps(merged, ensure_ascii=False)
            if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob):
                raise RuntimeError("refusing registration meta with email-like strings")
            if "value" in merged or any(
                isinstance(f, dict) and ("value" in f or "answer" in f)
                for f in (merged.get("fields") or [])
            ):
                raise RuntimeError("refusing registration meta with value/answer")
            ev["registration"] = merged
            mech = merged.get("mechanism") or "UNKNOWN"
            stats["by_mechanism"][mech] = stats["by_mechanism"].get(mech, 0) + 1
            if merged.get("destination"):
                stats["with_destination"] += 1
            if sleep_s:
                time.sleep(sleep_s)
        except Exception as ex:
            stats["errors"] += 1
            log(f"  reg_discover: attach error {ev.get('id')}: {type(ex).__name__}: {ex}")
            # restore url
            ev["url"] = official
    return stats


def enrich_events_file(path: str = None, limit: Optional[int] = None) -> Dict[str, int]:
    path = path or OUT
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events") or []
    stats = enrich_registration_discovery(events, limit=limit)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Discover registration destinations for events.json")
    p.add_argument("--events", default=OUT, help="Path to events.json")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    with open(args.events, encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events") or []
    # Snapshot urls
    urls_before = {e.get("id"): e.get("url") for e in events}
    stats = enrich_registration_discovery(events, limit=args.limit)
    # Verify no url replacement
    for e in events:
        if urls_before.get(e.get("id")) != e.get("url"):
            raise SystemExit(f"URL replaced for {e.get('id')}")
    if not args.dry_run:
        with open(args.events, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
    log("reg_discover:", stats)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
