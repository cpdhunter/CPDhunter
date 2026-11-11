"""
TQM Consultants — upcoming training parser.

Source: https://tqm.com.hk/training/upcoming/

Mode is stamped only from each official course DETAIL page header venue,
never from the upcoming listing or the site footer (Hong Kong HQ / China Office).
Absence of an online joining option on that same detail page, plus a
high-confidence physical venue, is FACE_TO_FACE. Listing addresses and
online=false are not enough.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

MAX_DETAIL_FETCHES = 20
ORGANIZER = "TQM Consultants"
TQM_VENUE_EXAMPLE = (
    "TQM Training Centre, 11/F Lockhart Centre, 301-307 Lockhart Road, Hong Kong"
)

_REG_CHROME_RE = re.compile(
    r"\bonline\s+registration\b|\benroll\s+now\b|\bapply\s+now\b",
    re.I,
)
_PRICE_RE = re.compile(r"(?:HK|US)?\$\s*[\d,]+", re.I)
_FREE_RE = re.compile(r"\bfree\s+(?:of\s+charge|admission|registration)\b|\bfree\b", re.I)
_FOOTER_OFFICE_RE = re.compile(
    r"Hong Kong HQ|China Office|Galaxy Century|Caitian|\bShenzhen\b|"
    r"Guangdong|\bPRC\b",
    re.I,
)
_COURSE_PATH_RE = re.compile(r"/course/[^/?#]+", re.I)


def _parse_date(s: Optional[str]):
    from fetch import parse_date  # type: ignore

    return parse_date(s)


def _parse_time_range(s: Optional[str]):
    from fetch import parse_time_range  # type: ignore

    return parse_time_range(s)


def _clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _is_tqm_course_url(url: str) -> bool:
    if not url:
        return False
    p = urlparse(url)
    host = (p.netloc or "").lower()
    return host.endswith("tqm.com.hk") and bool(_COURSE_PATH_RE.search(p.path or ""))


def _is_tqm_public_source_url(url: str) -> bool:
    """Upcoming listing or official /course/ detail pages only."""
    if not url:
        return False
    p = urlparse(url)
    host = (p.netloc or "").lower()
    if not host.endswith("tqm.com.hk"):
        return False
    path = (p.path or "").rstrip("/") + "/"
    if path.startswith("/training/upcoming/") or path == "/training/upcoming/":
        return True
    return bool(_COURSE_PATH_RE.search(p.path or ""))


def _strip_chrome(text: str) -> str:
    return _clean(_REG_CHROME_RE.sub(" ", text or ""))


def _decompose_noise(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for sel in (
        "footer",
        "#footer",
        ".footer",
        ".elementor-location-footer",
        "header",
        "nav",
        ".elementor-location-header",
        ".elementor-location-popup",
    ):
        for el in soup.select(sel):
            el.decompose()


def _looks_like_header_venue(text: str) -> bool:
    from event_mode import has_physical_address  # type: ignore

    t = _clean(text)
    if not t or _FOOTER_OFFICE_RE.search(t):
        return False
    if _parse_date(t) or _parse_time_range(t) or _PRICE_RE.search(t):
        return False
    if has_physical_address({"venue": t}):
        return True
    if re.search(r"\btraining\s+cent(?:re|er)\b", t, re.I) and re.search(
        r"\b(?:Road|Street|Avenue|Rd\.?|St\.?)\b|\d+\s*/\s*F", t, re.I
    ):
        return True
    return False


def _fee_flag(price_text: Optional[str]) -> Optional[bool]:
    t = _clean(price_text)
    if not t:
        return None
    if _PRICE_RE.search(t) and not re.search(r"HK\$\s*0\b", t):
        return False
    if _FREE_RE.search(t) and not _PRICE_RE.search(t):
        return True
    return None


def extract_tqm(soup: BeautifulSoup, base: str) -> List[Dict[str, Any]]:
    """Parse the upcoming listing only. Do not read venue or mode from this page."""
    out: List[Dict[str, Any]] = []
    rows = soup.select("div.row.course")
    for row in rows:
        title_a = row.select_one(".course__title a[href], a[href*='/course/']")
        if not title_a:
            continue
        title = _clean(title_a.get_text(" ", strip=True))
        if not title or len(title) < 4:
            continue
        date_el = row.select_one("span.date, .course__date")
        date_s = _clean(date_el.get_text(" ", strip=True) if date_el else "")
        d = _parse_date(date_s)
        if not d:
            continue
        href = title_a.get("href") or ""
        url = urljoin(base, href) if href else base
        ev: Dict[str, Any] = {
            "title": title,
            "date": d,
            "url": url,
            "organizer": ORGANIZER,
        }
        time_el = row.select_one("span.time, .course__time-price .time")
        time_s = _clean(time_el.get_text(" ", strip=True) if time_el else "")
        if time_s:
            ev["time"] = time_s
            times = _parse_time_range(time_s)
            if times:
                ev["start_time"], ev["end_time"] = times
        price_el = row.select_one("span.price")
        price_s = _clean(price_el.get_text(" ", strip=True) if price_el else "")
        if price_s:
            ev["price"] = price_s
        fee = _fee_flag(price_s)
        if fee is not None:
            ev["is_free"] = fee
        apply_a = row.select_one(".course__apply a[href], a[href*='docs.google.com/forms'], a[href*='forms.gle']")
        dest = ""
        if apply_a and apply_a.get("href"):
            dest = urljoin(base, apply_a["href"])
        if dest.lower().startswith("http"):
            ev["registration_destination"] = dest
        out.append(ev)

    seen = set()
    uniq: List[Dict[str, Any]] = []
    for e in out:
        k = (e["date"], e["title"][:80], e.get("url") or "")
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    return uniq[:40]


def parse_tqm_course_detail(html: str) -> Dict[str, Any]:
    """Extract header venue and visible text from an official course detail page.

    Footer HQ / China Office addresses are ignored. Scripts and chrome are ignored.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    enroll = ""
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        low = href.lower()
        if "docs.google.com/forms" in low or "forms.gle" in low or "google.com/forms" in low:
            enroll = href
            break

    work = BeautifulSoup(str(soup), "html.parser")
    _decompose_noise(work)

    title = ""
    date_s = ""
    time_s = ""
    venue = ""
    price_s = ""

    header = None
    for sec in work.select("section"):
        if sec.select_one("span.date") and sec.find(["h1", "h2", "h3"]):
            header = sec
            break
    scope = header or work

    title_el = scope.find(["h1", "h2", "h3"])
    if title_el:
        title = _clean(title_el.get_text(" ", strip=True))
    date_el = scope.select_one("span.date")
    if date_el:
        date_s = _clean(date_el.get_text(" ", strip=True))
    price_el = scope.select_one("span.price")
    if price_el:
        price_s = _clean(price_el.get_text(" ", strip=True))

    for el in scope.select(".elementor-heading-title, span.time"):
        text = _clean(el.get_text(" ", strip=True))
        if not text or text == title:
            continue
        if _parse_date(text):
            if not date_s:
                date_s = text
            continue
        if _parse_time_range(text) or el.get("class") and "time" in el.get("class"):
            if not time_s and _parse_time_range(text):
                time_s = text
            continue
        if _PRICE_RE.search(text):
            if not price_s:
                price_s = text
            continue
        if _looks_like_header_venue(text) and not venue:
            venue = text

    visible = _strip_chrome(work.get_text(" ", strip=True))
    # Keep a bounded description for mode evidence; never include footer (already removed).
    description = visible
    if title and description.startswith(title):
        description = _clean(description[len(title) :])
    # Optional labelled Venue / Mode / Registration fields (live TQM pages
    # currently omit these labels; synthetic fixtures cover the distinction).
    from event_mode import parse_labelled_fields  # type: ignore

    labelled = parse_labelled_fields(visible, description)
    labelled_venue = _clean(labelled.get("venue") or "")
    if not venue and labelled_venue and _looks_like_header_venue(labelled_venue):
        venue = labelled_venue
    return {
        "title": title,
        "venue": venue,
        "date": date_s,
        "time": time_s,
        "price": price_s,
        "description": description[:2000],
        "registration_destination": enroll,
        "modeText": _clean(labelled.get("mode") or ""),
        "registrationText": _clean(labelled.get("registration") or ""),
    }


def enrich_tqm_course_details(
    events: Optional[List[Dict[str, Any]]],
    fetch_detail: Callable[[str], Optional[str]],
    max_fetches: int = MAX_DETAIL_FETCHES,
) -> List[Dict[str, Any]]:
    """Classify TQM courses from each official course detail page, not the listing."""
    from event_mode import infer_mode, MODE_UNKNOWN  # type: ignore

    out: List[Dict[str, Any]] = []
    fetches = 0
    for ev in events or []:
        item = dict(ev)
        url = item.get("url") or ""
        if not _is_tqm_course_url(url) or not callable(fetch_detail):
            out.append(item)
            continue
        if fetches >= max_fetches:
            out.append(item)
            continue
        try:
            html = fetch_detail(url)
        except Exception:
            out.append(item)
            continue
        fetches += 1
        if not html:
            out.append(item)
            continue
        detail = parse_tqm_course_detail(html)
        detail_venue = (detail.get("venue") or "").strip()
        if detail_venue:
            item["venueSource"] = "event_detail"
            item["venue"] = detail_venue
        if detail.get("registration_destination") and not item.get("registration_destination"):
            item["registration_destination"] = detail["registration_destination"]
        desc = (detail.get("description") or "").strip()
        evidence = {
            "name": detail.get("title") or item.get("title"),
            "venue": detail_venue or None,
            "description": desc or None,
            "venueSource": "event_detail" if detail_venue else "",
            "modeText": (detail.get("modeText") or "").strip() or None,
        }
        inferred = infer_mode(evidence)
        if inferred["mode"] != MODE_UNKNOWN:
            item["mode"] = inferred["mode"]
        out.append(item)
    return out
