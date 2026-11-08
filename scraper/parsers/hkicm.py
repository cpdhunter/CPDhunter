"""
HKICM Learning / CPD parser.

Source: https://hkicm.org.hk/learning-cpd/
Prefer Learning/CPD category cards; exclude news/media, dinners/sport/social,
membership recruitment sessions, and explicitly paid events.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

HKT = dt.timezone(dt.timedelta(hours=8))
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}


def _parse_date(s: Optional[str]):
    from fetch import parse_date  # type: ignore
    return parse_date(s)


def _year_from_slug(href: str) -> Optional[int]:
    m = re.search(r"cpd(20\d{2})(\d{2})(\d{2})", href or "", re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(20\d{2})", href or "")
    if m:
        return int(m.group(1))
    return None


def _date_from_slug(href: str) -> Optional[str]:
    m = re.search(r"cpd(20\d{2})(\d{2})(\d{2})", href or "", re.I)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _parse_day_mon(text: str, year_hint: Optional[int] = None) -> Optional[str]:
    """Parse '16 Dec' / '1 Dec' with optional year hint (else HKT today)."""
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\b", text)
    if not m:
        return None
    day = int(m.group(1))
    mon = m.group(2).lower()[:3]
    if mon not in MONTHS:
        return None
    today = dt.datetime.now(HKT).date()
    year = year_hint or today.year
    try:
        d = dt.date(year, MONTHS[mon], day)
    except ValueError:
        return None
    # If no slug year and date is >180d in the past, roll forward a year
    if year_hint is None and d < today - dt.timedelta(days=180):
        try:
            d = dt.date(year + 1, MONTHS[mon], day)
        except ValueError:
            return None
    return d.isoformat()


def _norm_time_token(t: str) -> Optional[str]:
    t = t.strip().lower().replace(".", "")
    m = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)?", t)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    ap = m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


def _extract_times(text: str):
    m = re.search(
        r"(\d{1,2}:\d{2}\s*(?:am|pm)?)\s*[–\-~to]+\s*(\d{1,2}:\d{2}\s*(?:am|pm)?)",
        text,
        re.I,
    )
    if not m:
        return None, None
    return _norm_time_token(m.group(1)), _norm_time_token(m.group(2))


def _fee_status(text: str):
    if re.search(r"free[\s-]*of[\s-]*charge|free\s+of\s+charge|免費", text, re.I):
        return True
    if re.search(r"HK\$\s*\d", text):
        return False
    return None


EXCLUDE_TITLE_RE = re.compile(
    r"how to become|membership\s+info|annual\s+dinner|cocktail|gala|banquet|"
    r"sport|social|agm|media\s+interview|press\s+release|awards?\s+night|"
    r"晚宴|聯歡|球賽|訪問",
    re.I,
)


def _disciplines(title: str) -> List[str]:
    t = title.lower()
    if any(k in t for k in ("safety", "aviation safety", "安全")):
        return ["General"]  # type via H&S
    if any(k in t for k in ("contract", "nec", "buildings ordinance", "administration")):
        return ["General"]
    if any(k in t for k in ("mic", "construction", "excavation", "waterproof", "basement")):
        return ["Civil", "Structural"] if "excavation" in t or "waterproof" in t else ["Civil"]
    return ["Civil"]


def _classify(title: str) -> str:
    from fetch import classify_rule  # type: ignore
    return classify_rule(title)


def extract_hkicm(soup: BeautifulSoup, base: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # Prefer upcoming Learning/CPD wrapper; never take finished/past block for production
    scope = soup.select_one(".events-wrapper.events-open") or soup
    # If page is news-category only, still iterate but filter
    items = scope.select(".item-event")
    if not items:
        items = soup.select(".item-event")

    seen = set()
    for it in items:
        classes = " ".join(it.get("class") or []).lower()
        # Prefer learning-cpd; reject pure news/media cards
        if "item-news" in classes or "item-media" in classes or "cat-news" in classes:
            continue
        # If parent wrapper is news-only without learning-cpd on item, skip
        if "item-learning-cpd" not in classes and "learning-cpd" not in classes:
            # still allow if href looks like /event/cpdYYYY...
            a_probe = it.find("a", href=True)
            href_probe = (a_probe.get("href") if a_probe else "") or ""
            if not re.search(r"/event/cpd\d|/event/.+", href_probe):
                continue

        a = it.find("a", href=True)
        title_el = it.select_one(".event-title") or a
        title = title_el.get_text(" ", strip=True) if title_el else ""
        title = re.sub(r"\s+", " ", title).strip()
        # Strip [FULL] marker from title but keep event
        title_clean = re.sub(r"^\[FULL\]\s*", "", title, flags=re.I).strip()
        if not title_clean or len(title_clean) < 8:
            continue
        if EXCLUDE_TITLE_RE.search(title_clean):
            continue

        href = (a.get("href") if a else "") or ""
        url = urljoin(base, href) if href else base
        text = it.get_text(" ", strip=True)

        fee = _fee_status(text)
        if fee is False:
            continue  # paid
        # fee missing: allow with free=null only for CPD-coded technical items
        if fee is None and not re.search(r"seminar|workshop|forum|cpd|visit|講座|研討", title_clean, re.I):
            continue

        d = _date_from_slug(href) or _parse_date(text)
        if not d:
            d = _parse_day_mon(text, _year_from_slug(href))
        if not d:
            continue

        start_t, end_t = _extract_times(text)
        hrs = None
        # Estimate from times later in clean(); leave None unless stated
        hm = re.search(r"(\d+(?:\.\d+)?)\s*(?:cpd\s*)?hours?", text, re.I)
        if hm:
            try:
                v = float(hm.group(1))
                if 0 < v < 50:
                    hrs = int(v) if v == int(v) else v
            except ValueError:
                pass

        online = bool(re.search(r"\bonline\b|webinar|zoom", title_clean + " " + text, re.I))
        # Register link on listing usually points to same event page
        reg = None
        for link in it.find_all("a", href=True):
            lab = link.get_text(" ", strip=True).lower()
            if "register" in lab or "報名" in lab:
                reg = urljoin(base, link["href"])
                break

        key = (d, title_clean[:80])
        if key in seen:
            continue
        seen.add(key)

        ev: Dict[str, Any] = {
            "title": title_clean[:200],
            "date": d,
            "url": url,
            "organizer": "HKICM",
            "is_free": fee,
            "is_online": online if online else None,
            "start_time": start_t,
            "end_time": end_t,
            "cpd_hours": hrs,
            "type": _classify(title_clean),
            "disciplines": _disciplines(title_clean),
        }
        if reg and reg != url:
            ev["registration_destination"] = reg
        out.append(ev)
    return out
