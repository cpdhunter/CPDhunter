"""
OSHC activity-system parser (sms.oshc.hk).

Source: https://sms.oshc.hk/online/activitiesE.aspx
Data path: server-rendered ASP.NET GridView (#GV_Activities). No public JSON API.
GET only — never postback/login/enrol.

Free-first: explicitly paid excluded; fee-not-stated kept as free=null.
H&S type set only when title/content justifies occupational safety/health.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

HS_RE = re.compile(
    r"safety|health|hazard|accident|risk|confined\s+space|lifting|crane|"
    r"scaffold|work(?:ing)?\s+at\s+height|heat\s+stress|osh|occupational|"
    r"職安|安全|健康|意外|吊運|棚架|高空",
    re.I,
)
SOCIAL_RE = re.compile(
    r"\b(?:dinner|agm|sport|social|gala|banquet|networking\s+reception|"
    r"cocktail|聯歡|晚宴|週年)\b",
    re.I,
)
PAID_RE = re.compile(
    r"(?:HK\$|Hkd\s*\$?|USD\s*\$|£)\s*\d|"
    r"(?:fee|charge|fees?)\s*:\s*(?!free)(?![^\n]{0,40}free)|"
    r"\bpaid\s+(?:training|course|seminar|workshop)\b",
    re.I,
)
FREE_RE = re.compile(
    r"\bfree\s+of\s+charge\b|\bfree\s+registration\b|\bfree\s+admission\b|"
    r"\bfree\s+online\b|\(free\)|\b免費\b",
    re.I,
)
DEADLINE_RE = re.compile(
    r"(?:Registration\s+Deadline|Deadline\s+of\s+application|"
    r"Deadline\s+application)\s*:?\s*([^\n<(]+)",
    re.I,
)
ACTIVITY_URL_RE = re.compile(
    r"https://sms\.oshc\.hk/(?:online|portal/enrollment)/activity[EI]\.aspx\?activityid=\d+",
    re.I,
)
CHECKBTN_RE = re.compile(
    r"checkButtonClick\(\s*'eng'\s*,\s*'seminars_conferences'\s*,\s*"
    r"'((?:\\'|[^'])*)'\s*,\s*'(https://sms\.oshc\.hk[^']*activityid=\d+)'",
    re.I,
)


def _parse_date(s: Optional[str]):
    from fetch import parse_date  # type: ignore

    return parse_date(s)


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (t or "").lower())


def _flexible_title_sim(a: str, b: str) -> float:
    """Title similarity tolerant of truncation / minor typos (URL enrich only)."""
    from difflib import SequenceMatcher
    if not a or not b:
        return 0.0
    best = SequenceMatcher(None, a, b).ratio()
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 40 and len(longer) > len(shorter):
        best = max(best, SequenceMatcher(None, shorter, longer[: len(shorter)]).ratio())
        step = max(1, len(shorter) // 10)
        for i in range(0, len(longer) - len(shorter) + 1, step):
            best = max(
                best,
                SequenceMatcher(None, shorter, longer[i : i + len(shorter)]).ratio(),
            )
    return best


def _norm_time_token(t: str) -> Optional[str]:
    t = t.strip().lower().replace(".", "")
    # Allow ((7:00-8:00 PM)) style — caller splits range first
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


def _extract_times(text: str) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None
    # Strip wrapping parens from timePhase e.g. ((7:00-8:00 PM)) or (3:30 p.m. – 4:45 p.m.)
    t = text.strip().strip("()")
    while t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    # Shared am/pm after the range: 7:00-8:00 PM
    m = re.search(
        r"(\d{1,2}:\d{2})\s*[–\-~to]+\s*(\d{1,2}:\d{2})\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)?",
        t,
        re.I,
    )
    if m:
        ap = (m.group(3) or "").lower().replace(".", "").replace(" ", "")
        a = _norm_time_token(m.group(1) + ((" " + ap) if ap else ""))
        b = _norm_time_token(m.group(2) + ((" " + ap) if ap else ""))
        return a, b
    m = re.search(
        r"(\d{1,2}:\d{2}\s*(?:a\.?\s*m\.?|p\.?\s*m\.?|am|pm)?)\s*[–\-~to]+\s*"
        r"(\d{1,2}:\d{2}\s*(?:a\.?\s*m\.?|p\.?\s*m\.?|am|pm)?)",
        t,
        re.I,
    )
    if not m:
        return None, None
    return _norm_time_token(m.group(1)), _norm_time_token(m.group(2))


def _is_online(venue: str, title: str) -> Optional[bool]:
    blob = f"{venue} {title}"
    if re.search(r"\bonline\b|網上|线上", blob, re.I):
        return True
    if re.search(r"\bphysical\b|面授|實體", blob, re.I):
        return False
    return None


def _fee_flag(title: str) -> Optional[bool]:
    if PAID_RE.search(title):
        return False
    if FREE_RE.search(title):
        return True
    return None


def extract_oshc_activity(soup: BeautifulSoup, base: str) -> List[Dict[str, Any]]:
    """Parse sms.oshc.hk activitiesE.aspx GridView into raw event dicts."""
    out: List[Dict[str, Any]] = []
    table = soup.find("table", id="GV_Activities")
    if table is None:
        # Fallback: any table whose header mentions Seminars / Date
        for cand in soup.find_all("table"):
            header = cand.find("tr")
            if not header:
                continue
            ht = header.get_text(" ", strip=True).lower()
            if "date" in ht and ("seminar" in ht or "conference" in ht or "活動" in ht):
                table = cand
                break
    if table is None:
        return out

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        # cols: # | Date+time | Title | Venue
        date_cell = tds[1]
        title = tds[2].get_text(" ", strip=True)
        venue = tds[3].get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        if SOCIAL_RE.search(title):
            continue
        if _fee_flag(title) is False:
            continue

        date_text = date_cell.get_text(" ", strip=True)
        time_el = date_cell.find(class_="timePhase")
        time_text = time_el.get_text(" ", strip=True) if time_el else ""
        d = _parse_date(date_text)
        if not d:
            continue

        start_t, end_t = _extract_times(time_text or date_text)
        online = _is_online(venue, title)
        is_free = _fee_flag(title)

        ev: Dict[str, Any] = {
            "title": title[:240],
            "date": d,
            "url": base.split("#")[0],
            "organizer": "OSHC",
            "venue": venue[:160] if venue else None,
            "is_online": online,
            "is_free": is_free,
            "start_time": start_t,
            "end_time": end_t,
        }
        if HS_RE.search(title) or HS_RE.search(venue or ""):
            ev["type"] = "H&S"
            ev["disciplines"] = ["General"]

        dl = DEADLINE_RE.search(title) or DEADLINE_RE.search(date_text)
        if dl:
            ev["registration_deadline"] = dl.group(1).strip()[:80]

        # Never treat row postback as a destination — listing URL only until enriched.
        out.append(ev)
    return out


def build_activity_url_index(html: str) -> Dict[str, str]:
    """Map normalised titles → public sms.oshc activity detail URLs (GET links)."""
    index: Dict[str, str] = {}
    if not html:
        return index
    for m in CHECKBTN_RE.finditer(html):
        title = m.group(1).replace("\\'", "'")
        href = m.group(2).replace("\\'", "'").strip()
        key = _norm_title(title)
        if key and ACTIVITY_URL_RE.search(href):
            # Prefer higher activityid when duplicates (newer run of same title)
            prev = index.get(key)
            if prev:
                am = re.search(r"activityid=(\d+)", href, re.I)
                bm = re.search(r"activityid=(\d+)", prev, re.I)
                if am and bm and int(am.group(1)) < int(bm.group(1)):
                    continue
            index[key] = href
    # Also accept bare activity URLs next to link text
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href") or ""
            m = ACTIVITY_URL_RE.search(href)
            if not m:
                m = ACTIVITY_URL_RE.search(href.replace("&amp;", "&"))
            if not m:
                continue
            title = a.get_text(" ", strip=True)
            key = _norm_title(title)
            if key and len(key) > 20:
                index.setdefault(key, m.group(0))
    except Exception:
        pass
    return index


def attach_activity_urls(
    events: List[Dict[str, Any]], index: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Attach public activity detail URL + registration destination when title matches."""
    if not index:
        return events
    out = []
    for e in events:
        ev = dict(e)
        key = _norm_title(ev.get("title") or "")
        href = index.get(key)
        if not href and key:
            # fuzzy: containment first, then high title similarity (typos / truncation)
            best = None
            best_n = 0
            best_sim = 0.0
            for jt, url in index.items():
                if not jt or len(jt) < 24:
                    continue
                if key in jt or jt in key:
                    n = min(len(key), len(jt))
                    if n > best_n:
                        best_n = n
                        best = url
                else:
                    sim = _flexible_title_sim(key, jt)
                    if sim >= 0.92 and sim > best_sim:
                        best_sim = sim
                        if best_n == 0:
                            best = url
            href = best
        if href and ACTIVITY_URL_RE.search(href):
            ev["url"] = href
            ev["registration_destination"] = href
        out.append(ev)
    return out


def parse_oshc_activity_html(html: str, base: str) -> List[Dict[str, Any]]:
    """Convenience for tests: parse HTML string."""
    if not html or not html.strip():
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []
    return extract_oshc_activity(soup, base)
