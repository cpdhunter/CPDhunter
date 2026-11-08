"""
CIPHE Hong Kong Branch — Events Calendar parser.

Source: https://ciphe.org.hk/Events_Calendar.html
Free-first: explicitly paid excluded; explicitly free included;
fee-not-stated kept only for otherwise-qualifying technical CPD (free=null).
No login / CAPTCHA / form submit.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Lazy import of shared date helper to avoid circular imports at module load.
def _parse_date(s: Optional[str]):
    from fetch import parse_date  # type: ignore
    return parse_date(s)


SOCIAL_RE = re.compile(
    r"dinner|cocktail|gala|banquet|agm|sport|social|competition|"
    r"commemorative|booklet|nomination|election|dress\s*day|"
    r"晚宴|週年慶典|聯歡|提名|選舉",
    re.I,
)
VISIT_OVERSEAS_RE = re.compile(
    r"technical\s+visit|factory\s+at\s+dongguan|dongguan|guangzhou|shenzhen|"
    r"mainland|overseas\s+visit|參觀",
    re.I,
)
PAID_RE = re.compile(
    r"(?:HK\$|Hkd\s*\$?|USD\s*\$|£)\s*\d|"
    r"(?:registration\s+fee|charge|fees?)\s*:\s*(?!free)(?![^\n]{0,40}free)",
    re.I,
)
FREE_RE = re.compile(
    r"free\s+registration|free\s+of\s+charge|free\s+admission|"
    r"free\s*\(|\(free\s+registration\)|registration\s+fee\s*:\s*free|"
    r"charge\s*:\s*free|fees?\s*:\s*free\b|免費",
    re.I,
)
CPD_HRS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*hours?\s+attendance\s+CPD|"
    r"CPD\s*Hours?\s*:\s*(\d+(?:\.\d+)?)|"
    r"(\d+(?:\.\d+)?)\s*-?\s*hour\s+attendance\s+CPD|"
    r"(\d+(?:\.\d+)?)\s*hours?\s+CPD",
    re.I,
)
TIME_RE = re.compile(
    r"(\d{1,2}:\d{2}\s*(?:am|pm)?)\s*[–\-~to]+\s*(\d{1,2}:\d{2}\s*(?:am|pm)?)",
    re.I,
)
DEADLINE_RE = re.compile(
    r"(?:Registration\s+Deadline|Online\s+Registration\s+Deadline|"
    r"Deadline\s+application|Deadline\s+of\s+application)\s*:?\s*([^\n<]+)",
    re.I,
)


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
    if not ap and h <= 7 and "pm" in t:
        pass
    return f"{h:02d}:{mi:02d}"


def _extract_times(text: str):
    # Prefer the Details "Time:" row
    m = re.search(r"Time\s*:\s*([^\n]+)", text, re.I)
    chunk = m.group(1) if m else text
    tm = TIME_RE.search(chunk)
    if not tm:
        return None, None
    return _norm_time_token(tm.group(1)), _norm_time_token(tm.group(2))


def _fee_status(text: str):
    """Return True (free), False (paid), or None (unknown)."""
    # Explicit free wins when clearly stated (even if other tables exist)
    if FREE_RE.search(text):
        # But if member free / non-member paid tier table dominates without
        # a blanket free line, treat as paid — look for HK$ after free mention
        # only for member-tier tables without "Free registration" blanket.
        if re.search(r"Free registration|Free of charge|Free Admission|Charge:\s*Free|Fees?:\s*Free\b|免費報名", text, re.I):
            return True
        if re.search(r"\(Free Registration\)|Free Registration\)", text, re.I):
            return True
    if re.search(r"HK\$\s*\d", text):
        return False
    if re.search(r"(?:Registration\s+Fee|Charge|Fees?)\s*:\s*[^\n]*\d", text, re.I):
        if not FREE_RE.search(text):
            return False
    return None


def _cpd_hours(text: str) -> Optional[float]:
    m = CPD_HRS_RE.search(text)
    if not m:
        return None
    for g in m.groups():
        if g:
            try:
                v = float(g)
                if 0 < v < 50:
                    return int(v) if v == int(v) else v
            except ValueError:
                pass
    return None


def _reg_link(article) -> Optional[str]:
    for a in article.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        low = href.lower()
        if any(x in low for x in (
            "forms.gle/", "docs.google.com/forms", "google.com/forms",
            "forms.office.com", "eventbrite.", "zoom.us/",
        )):
            return href
        label = a.get_text(" ", strip=True).lower()
        if re.search(r"register\s*here|online\s+registration|報名", label):
            if href.startswith("http") and "ciphe.org.hk" not in low:
                return href
    return None


def _disciplines(title: str, text: str) -> List[str]:
    blob = f"{title} {text}".lower()
    discs = []
    if any(k in blob for k in ("plumb", "water", "ami", "metering", "drainage", "hydraulic")):
        discs.append("Building Services")
    if any(k in blob for k in ("hvac", "bacnet", "chilled", "air quality", "iaq")):
        discs.extend(["Building Services", "Mechanical"])
    if any(k in blob for k in ("electrical", "e&m", "electrical & mechanical")):
        discs.append("Electrical")
    if any(k in blob for k in ("fire",)):
        discs.append("Fire")
    if any(k in blob for k in ("civil", "infrastructure")):
        discs.append("Civil")
    # uniq preserve order
    out = []
    for d in discs:
        if d not in out:
            out.append(d)
    return out or ["Building Services"]


def _classify(title: str, text: str) -> str:
    from fetch import classify_rule  # type: ignore
    return classify_rule(f"{title} {text[:200]}")


def extract_ciphe(soup: BeautifulSoup, base: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    articles = soup.select("article.blog-item")
    if not articles:
        # fallback: h3 sections
        for h3 in soup.find_all("h3"):
            parent = h3.find_parent(["article", "div"])
            if parent and parent not in articles:
                articles.append(parent)

    seen = set()
    for art in articles:
        h = art.find(["h3", "h2"])
        if not h:
            continue
        title = h.get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 8:
            continue
        text = art.get_text("\n", strip=True)

        # Reject news / social / competition / booklet
        if SOCIAL_RE.search(title) or SOCIAL_RE.search(text[:400]):
            # allow technical titles that merely mention supporting orgs
            if re.search(r"dinner|晚宴|gala|banquet|competition|booklet|nomination|election|dress\s*day", title, re.I):
                continue
            if re.search(r"週年論壇及晚宴|週年慶典晚宴", title):
                continue
        if re.search(r"competition|commemorative booklet|nomination for election|biz-green dress", title, re.I):
            continue

        # Overseas technical visits — exclude (physical outside HK)
        if VISIT_OVERSEAS_RE.search(title):
            continue

        # Date from Details table preferred
        date_s = None
        m = re.search(r"Date\s*:\s*([^\n]+)", text, re.I)
        if m:
            date_s = m.group(1).strip()
        if not date_s:
            # post-meta <time>
            tim = art.find("time")
            if tim:
                date_s = tim.get_text(" ", strip=True)
        d = _parse_date(date_s) if date_s else _parse_date(text[:300])
        if not d:
            continue

        fee = _fee_status(text)
        if fee is False:
            continue  # paid — free-first exclude

        # Fee unknown: only keep if looks like technical CPD (not pure news)
        if fee is None:
            blob = title + " " + text[:800]
            looks_technical = bool(re.search(
                r"seminar|webinar|symposium|conference|talk|workshop|cpd|"
                r"technical|meter|water|hvac|plumbing|drainage|bim|研討|講座|課程",
                blob,
                re.I,
            ))
            has_details = bool(re.search(r"Date\s*:", text, re.I) and re.search(r"Time\s*:", text, re.I))
            if not (looks_technical or has_details):
                continue

        start_t, end_t = _extract_times(text)
        hrs = _cpd_hours(text)
        reg = _reg_link(art)
        online = bool(re.search(r"webinar|via\s+zoom|online\s+via|conducted in the form of webinar", text, re.I))
        venue_m = re.search(r"Venue\s*:\s*([^\n]+)", text, re.I)
        venue = venue_m.group(1).strip()[:160] if venue_m else None
        if venue and re.search(r"webinar|zoom", venue, re.I):
            online = True

        deadline = None
        dm = DEADLINE_RE.search(text)
        if dm:
            deadline = dm.group(1).strip()[:80]

        key = (d, title[:80])
        if key in seen:
            continue
        seen.add(key)

        ev: Dict[str, Any] = {
            "title": title[:200],
            "date": d,
            "url": base,  # listing is the official page (no per-event detail URLs)
            "organizer": "CIPHE Hong Kong",
            "is_free": fee,  # True / None
            "is_online": online if online else None,
            "start_time": start_t,
            "end_time": end_t,
            "cpd_hours": hrs,
            "type": _classify(title, text),
            "disciplines": _disciplines(title, text),
        }
        if reg:
            ev["registration_destination"] = reg
        if deadline:
            ev["registration_deadline"] = deadline
        if venue:
            ev["venue"] = venue
        out.append(ev)
    return out
