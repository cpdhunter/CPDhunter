"""HKIE official event-detail enrichment.

Discovery (listing/calendar/canary) still finds the event. This layer then
reads the official event-detail payload (public hkie_api eventdetail, or
recorded HTML) and updates the same discovered record.

It never appends a second event. Date, time, and venue are taken from the
labelled Event Information fields on that same detail page, not from a
concatenated page blob.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

from bs4 import BeautifulSoup

MAX_DETAIL_FETCHES = 40
HKIE_EVENT_DETAIL_RE = re.compile(
    r"https?://(?:www\.)?hkie\.org\.hk/(?:tc/)?events/event-detail/([A-Za-z0-9]+)/?",
    re.I,
)
HKIE_API = "https://hkie.org.hk/hkie_api/index.php"

# Official HKIE Division / organiser labels → catalogue disciplines.
# Combined official names may map to more than one existing DISCS value.
# Geotechnical / Structural also carry a Civil relevance signal.
DIVISION_MAP = (
    ("control, automation & instrumentation division", ["Control, Automation & Instrumentation"]),
    ("control, automation and instrumentation division", ["Control, Automation & Instrumentation"]),
    ("manufacturing, industrial & systems division", ["Manufacturing, Industrial & Systems"]),
    ("manufacturing, industrial and systems division", ["Manufacturing, Industrial & Systems"]),
    ("logistics & transportation division", ["Logistics & Transportation"]),
    ("logistics and transportation division", ["Logistics & Transportation"]),
    ("marine & naval architecture division", ["Marine & Naval Architecture"]),
    ("marine and naval architecture division", ["Marine & Naval Architecture"]),
    ("building services division", ["Building Services"]),
    ("geotechnical division", ["Geotechnical"]),
    ("structural division", ["Structural"]),
    ("environmental division", ["Environmental"]),
    ("electronics division", ["Electronics"]),
    ("electrical division", ["Electrical"]),
    ("biomedical division", ["Biomedical"]),
    ("materials division", ["Materials"]),
    ("chemical division", ["Chemical"]),
    ("aircraft division", ["Aircraft"]),
    ("nuclear division", ["Nuclear"]),
    ("building division", ["Building"]),
    ("civil division", ["Civil"]),
    ("mechanical division", ["Mechanical"]),
    ("information division", ["Information"]),
    ("fire division", ["Fire"]),
    ("gas division", ["Gas"]),
)

# Official combined MMNC division used by HKIE event pages.
_MMNC_RE = re.compile(
    r"mechanical,?\s*marine,?\s*(?:naval architecture|& naval architecture)"
    r".{0,40}chemical division",
    re.I,
)

CIVIL_RELEVANCE_DIVISIONS = frozenset({"Civil", "Geotechnical", "Structural"})

_CHROME_TITLES = frozenset({
    "event detail",
    "event details",
    "events",
    "event",
    "event information",
    "events - hkie",
    "hkie",
    "home",
    "navigation",
    "breadcrumb",
    "upcoming events",
    "cpd calendar",
})

_ATTENDANCE_SPLIT_RE = re.compile(
    r"\s*/\s*(?=(?:hybrid|webinar|online|zoom|teams|webex|virtual|網上|線上)\b)",
    re.I,
)
_ONLINE_ATTENDANCE_RE = re.compile(
    r"\b(?:webinar|zoom|teams|webex|virtual)\b|網上|線上|"
    r"\bonline(?:\s+zoom|\s+webinar|\s+event|\s+seminar)?\b",
    re.I,
)
_PLACEHOLDER_TIME_RE = re.compile(r"^00:00\s*[-–—]\s*00:00$")
_CPD_HOURS_RE = re.compile(
    r"(?:official\s+)?(?:cpd\s+)?(?:hours?|hrs|points?)\s*[:：]?\s*(\d+(?:\.\d+)?)"
    r"|(\d+(?:\.\d+)?)\s*(?:official\s+)?cpd\s*(?:hours?|hrs|points?)",
    re.I,
)
_FREE_RE = re.compile(r"\bfree of charge\b|免費(?:入場|參加|參與)?", re.I)
_EVENT_MODE_MAP = {
    "hybrid": "HYBRID",
    "hybrid with webinar": "HYBRID",
    "blended": "HYBRID",
    "online": "ONLINE",
    "webinar": "ONLINE",
    "virtual": "ONLINE",
    "zoom": "ONLINE",
    "onsite": "FACE_TO_FACE",
    "on-site": "FACE_TO_FACE",
    "on site": "FACE_TO_FACE",
    "face to face": "FACE_TO_FACE",
    "face-to-face": "FACE_TO_FACE",
    "in person": "FACE_TO_FACE",
    "in-person": "FACE_TO_FACE",
    "physical": "FACE_TO_FACE",
}


def is_hkie_event_detail_url(url: Optional[str]) -> bool:
    if not url:
        return False
    return bool(HKIE_EVENT_DETAIL_RE.match(url.split("#")[0].split("?")[0].strip()))


def hkie_event_id_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    m = HKIE_EVENT_DETAIL_RE.match(url.split("#")[0].split("?")[0].strip())
    return m.group(1) if m else None


def _clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _usable_title(title: Optional[str]) -> bool:
    from title_quality import (
        is_date_only_title,
        is_good_title,
        is_time_only_title,
        title_quality_reason,
    )

    t = _clean(title)
    if not t or len(t) < 8:
        return False
    low = t.lower()
    if low in _CHROME_TITLES:
        return False
    if "event detail" in low or low.startswith("home /") or low.startswith("home>"):
        return False
    # Breadcrumb paths ("Home / Events / …") are navigation, not titles.
    if " / " in t and all(len(_clean(p)) <= 20 for p in t.split("/")):
        return False
    if is_date_only_title(t) or is_time_only_title(t):
        return False
    if title_quality_reason(t) or not is_good_title(t):
        return False
    return True


def disciplines_from_hkie_division(organiser: Optional[str]) -> Tuple[List[str], bool]:
    """Map official HKIE organiser/division text to catalogue disciplines.

    Returns (disciplines, civil_related). Does not invent Structural unless
    the official metadata names the Structural Division (or existing mapped
    rules match). Official Civil/Geo/Structural divisions set civil_related.
    """
    text = _clean(organiser)
    if not text:
        return [], False
    low = text.lower()
    found: List[str] = []

    def _add(items: List[str]) -> None:
        for item in items:
            if item not in found:
                found.append(item)

    if _MMNC_RE.search(low):
        _add(["Mechanical", "Marine & Naval Architecture", "Chemical"])

    for label, discs in DIVISION_MAP:
        if label in low:
            _add(discs)

    civil_related = any(d in CIVIL_RELEVANCE_DIVISIONS for d in found)
    if civil_related and "Civil" not in found and any(
        d in ("Geotechnical", "Structural") for d in found
    ):
        # Civil relevance signal for Geo/Structural official divisions.
        found.append("Civil")
    return found, civil_related


def _parse_labelled_info(soup: BeautifulSoup) -> Dict[str, str]:
    """Parse Event Information labels independently from the official list."""
    fields: Dict[str, str] = {}
    info = soup.select_one("ul.einfoList")
    items = info.find_all("li") if info else []
    if not items:
        # Fallback: labelled <li><b>Label:</b><span>value</span> anywhere in
        # an Event Information block, still field-by-field (not a page blob).
        block = None
        for node in soup.find_all(["div", "section"]):
            h = node.find(["h1", "h2", "h3"])
            if h and "event information" in _clean(h.get_text()).lower():
                block = node
                break
        if block:
            items = block.find_all("li")
    for li in items:
        label = ""
        value = ""
        b = li.find("b") or li.find("strong")
        span = li.find("span")
        if b:
            label = _clean(b.get_text(" ", strip=True)).rstrip(":")
            if span:
                value = _clean(span.get_text(" ", strip=True))
            else:
                raw = _clean(li.get_text(" ", strip=True))
                value = _clean(raw[len(b.get_text(" ", strip=True)):]) if raw else ""
        else:
            raw = _clean(li.get_text(" ", strip=True))
            if ":" in raw:
                label, value = raw.split(":", 1)
                label, value = _clean(label), _clean(value)
        key = label.lower().rstrip(".")
        if not key or not value or key in fields:
            continue
        if key in ("date", "time", "venue", "event mode", "mode", "duration", "cpd hours", "cpd hour", "cpd points"):
            fields[key] = value
    return fields


def _section_text(soup: BeautifulSoup, heading: str) -> str:
    want = heading.lower().rstrip(":")
    for sec in soup.select(".einfoSection"):
        h = sec.find(["h1", "h2", "h3"])
        if not h:
            continue
        label = _clean(h.get_text(" ", strip=True)).lower().rstrip(":")
        if label == want or label.rstrip("s") == want.rstrip("s"):
            body = sec.find("div")
            text = body.get_text(" ", strip=True) if body else sec.get_text(" ", strip=True)
            text = _clean(text)
            if text.lower().startswith(_clean(h.get_text()).lower()):
                text = _clean(text[len(_clean(h.get_text())):])
            return text
    return ""


def _split_venue_attendance(venue_raw: str) -> Tuple[str, str]:
    """Split a labelled Venue value into physical venue + attendance wording."""
    raw = _clean(venue_raw)
    if not raw:
        return "", ""
    attendance_parts: List[str] = []
    venue = raw

    # "(Online) Zoom; (Physical) <venue>"
    m = re.search(
        r"\(online\)\s*([^;]+);\s*\(physical\)\s*(.+)$",
        raw,
        re.I,
    )
    if m:
        attendance_parts.append(_clean(m.group(1)))
        venue = _clean(m.group(2))
        return venue, _clean(" / ".join(attendance_parts))

    m = _ATTENDANCE_SPLIT_RE.search(raw)
    if m:
        venue = _clean(raw[: m.start()])
        attendance_parts.append(_clean(raw[m.end():]))

    # "… or via online(Zoom)" / "… and Online"
    m2 = re.search(r"\s+(?:or via|and|/)\s+(online(?:\s*\([^)]+\))?)\s*$", venue, re.I)
    if m2:
        attendance_parts.append(_clean(m2.group(1)))
        venue = _clean(venue[: m2.start()])
    return venue, _clean(" / ".join(p for p in attendance_parts if p))


def _map_event_mode(value: Optional[str]) -> Optional[str]:
    t = _clean(value).lower()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return None
    if t in _EVENT_MODE_MAP:
        return _EVENT_MODE_MAP[t]
    if "hybrid" in t:
        return "HYBRID"
    if t in ("online", "webinar") or t.startswith("online ") or t.startswith("webinar"):
        return "ONLINE"
    if t.startswith("onsite") or t.startswith("on-site") or t.startswith("on site"):
        return "FACE_TO_FACE"
    return None


def _first_date(value: Optional[str]) -> Optional[str]:
    from fetch import parse_date  # type: ignore

    text = _clean(value)
    if not text:
        return None
    # Prefer the first official YYYY-MM-DD in a "start - end" range.
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:\s*[-–—]\s*\d{4}-\d{2}-\d{2})?$", text)
    if m:
        return m.group(1)
    return parse_date(text)


def _parse_time_field(value: Optional[str]) -> Optional[Tuple[str, str]]:
    from fetch import parse_time_range  # type: ignore

    text = _clean(value)
    if not text or _PLACEHOLDER_TIME_RE.match(text):
        return None
    return parse_time_range(text)


def _official_cpd_hours(*texts: Optional[str]) -> Optional[float]:
    from fetch import stated_cpd_hours  # type: ignore

    for raw in texts:
        text = _clean(raw)
        if not text:
            continue
        stated = stated_cpd_hours(text)
        if stated is not None:
            return stated
        # Labelled "CPD hours: 1" / "1 CPD hour" only — not attendance prose.
        if re.search(r"attendance|first-come|participants?\s+is\s+limited", text, re.I):
            continue
        m = _CPD_HOURS_RE.search(text)
        if m:
            v = float(m.group(1) or m.group(2))
            if 0 < v < 50:
                return v
    return None


def _choose_title(api_title: Optional[str], soup: BeautifulSoup, existing: Optional[str]) -> str:
    from title_quality import clamp_title, strip_page_chrome

    h1 = soup.find("h1")
    h1_title = strip_page_chrome(h1.get_text(" ", strip=True)) if h1 else ""
    crumb = ""
    nav = soup.select_one("nav, .breadcrumb, .breadcrumbs")
    if nav:
        parts = [_clean(a.get_text(" ", strip=True)) for a in nav.find_all("a")]
        texts = [_clean(t) for t in nav.get_text("\n", strip=True).splitlines() if _clean(t)]
        segments = []
        for line in texts:
            segments.extend(_clean(p) for p in re.split(r"\s*/\s*", line) if _clean(p))
        for cand in list(reversed(segments)) + list(reversed(parts)):
            if _usable_title(cand):
                crumb = cand
                break
    explicit = strip_page_chrome(api_title or "")
    # Event Description often repeats the official title as a heading/strong.
    desc_title = ""
    desc = _section_text(soup, "Event Description")
    if desc:
        first = desc.split(" Organised by")[0].split(" Organized by")[0]
        first = _clean(first)
        if _usable_title(first) and len(first) <= 200:
            desc_title = first

    for cand in (h1_title, crumb, explicit, desc_title, existing):
        if _usable_title(cand):
            return clamp_title(cand)
    return clamp_title(existing or explicit or h1_title or "")


def _extract_registration_destination(html: str) -> Optional[str]:
    try:
        from gforms import extract_gform_urls, canonical_viewform_url
    except Exception:
        extract_gform_urls = None  # type: ignore
        canonical_viewform_url = None  # type: ignore

    texts = [html or ""]
    unquoted = unquote(html or "")
    if unquoted != html:
        texts.append(unquoted)
    found: List[str] = []
    if extract_gform_urls:
        for text in texts:
            for u in extract_gform_urls(text) or []:
                if u not in found:
                    found.append(u)
    if found:
        url = found[0]
        if canonical_viewform_url:
            return canonical_viewform_url(url)
        return url
    return None


def parse_hkie_event_detail(
    html: str,
    *,
    api_title: Optional[str] = None,
    existing_title: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse one official HKIE event-detail HTML payload."""
    soup = BeautifulSoup(html or "", "html.parser")
    fields = _parse_labelled_info(soup)
    organisers = _section_text(soup, "Organisers") or _section_text(soup, "Organizer")
    description = _section_text(soup, "Event Description")
    venue_raw = fields.get("venue") or ""
    venue, venue_attendance = _split_venue_attendance(venue_raw)
    event_mode_raw = fields.get("event mode") or fields.get("mode") or ""
    attendance = _clean(" / ".join(p for p in (event_mode_raw, venue_attendance) if p))
    mode = _map_event_mode(event_mode_raw)
    if mode is None and venue_attendance:
        if re.search(r"\bhybrid\b", venue_attendance, re.I):
            mode = "HYBRID"
        elif venue and _ONLINE_ATTENDANCE_RE.search(venue_attendance):
            mode = "HYBRID"
        elif _ONLINE_ATTENDANCE_RE.search(venue_attendance):
            mode = "ONLINE"
    # Physical venue + explicit online attendance in the venue label.
    if mode is None and venue and _ONLINE_ATTENDANCE_RE.search(venue_raw):
        mode = "HYBRID"

    start_end = _parse_time_field(fields.get("time"))
    date = _first_date(fields.get("date"))
    cpd = _official_cpd_hours(
        fields.get("cpd hours"),
        fields.get("cpd hour"),
        fields.get("cpd points"),
        fields.get("duration"),
    )
    discs, civil_related = disciplines_from_hkie_division(organisers)
    if not discs:
        # "Organised by: HKIE Civil Division" in the description is official too.
        discs, civil_related = disciplines_from_hkie_division(description[:400] if description else "")

    title = _choose_title(api_title, soup, existing_title)
    is_free = True if _FREE_RE.search(description or "") or _FREE_RE.search(soup.get_text(" ", strip=True)[:2000]) else None
    dest = _extract_registration_destination(html or "")

    out: Dict[str, Any] = {
        "title": title,
        "date": date,
        "time": f"{start_end[0]}-{start_end[1]}" if start_end else None,
        "start_time": start_end[0] if start_end else None,
        "end_time": start_end[1] if start_end else None,
        "venue": venue or None,
        "venue_raw": venue_raw or None,
        "attendanceMode": attendance or None,
        "modeText": attendance or None,
        "mode": mode,
        "division": organisers or None,
        "disciplines": discs,
        "civil_related": civil_related,
        "description": description or None,
        "cpd_hours": cpd,
        "is_free": is_free,
        "registration_destination": dest,
        "venueSource": "event_detail" if (venue or attendance or event_mode_raw) else None,
        "detail_ok": bool(fields or organisers or title),
    }
    return out


def apply_hkie_detail(event: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
    """Update a discovered event in place from official detail fields."""
    if not event or not detail or not detail.get("detail_ok"):
        return event

    if _usable_title(detail.get("title")):
        # Never replace a good title with chrome; _choose_title already guarded.
        event["title"] = detail["title"]
    if detail.get("date"):
        event["date"] = detail["date"]
    if detail.get("start_time") and detail.get("end_time"):
        event["start_time"] = detail["start_time"]
        event["end_time"] = detail["end_time"]
        event["time"] = detail.get("time") or f"{detail['start_time']}-{detail['end_time']}"
        event["time_raw"] = detail.get("time")
    if detail.get("venue"):
        event["venue"] = detail["venue"]
    if detail.get("venueSource"):
        event["venueSource"] = detail["venueSource"]
    if detail.get("attendanceMode"):
        event["attendanceMode"] = detail["attendanceMode"]
        event["modeText"] = detail["modeText"] or detail["attendanceMode"]
    if detail.get("mode"):
        event["mode"] = detail["mode"]
    if detail.get("division"):
        event["division"] = detail["division"]
    if detail.get("disciplines"):
        event["disciplines"] = list(detail["disciplines"])
    if detail.get("civil_related"):
        event["civil_related"] = True
    if detail.get("description") and not event.get("description"):
        event["description"] = detail["description"]
    if detail.get("cpd_hours") is not None:
        event["cpd_hours"] = detail["cpd_hours"]
    if detail.get("is_free") is True and event.get("is_free") is None:
        event["is_free"] = True
    if detail.get("registration_destination") and not event.get("registration_destination"):
        event["registration_destination"] = detail["registration_destination"]
    event["hkie_detail_enriched"] = True
    return event


def enrich_hkie_events(
    events: List[dict],
    fetch_payload: Callable[[str], Optional[Dict[str, Any]]],
    *,
    today: Optional[str] = None,
) -> Tuple[List[dict], Dict[str, int]]:
    """Enrich already-discovered HKIE events. Never appends new events."""
    from fetch import TODAY  # type: ignore

    cutoff = today or TODAY.isoformat()
    stats = {
        "candidates": 0,
        "fetched": 0,
        "enriched": 0,
        "failed": 0,
        "skipped_no_url": 0,
        "skipped_past": 0,
    }
    fetches = 0
    out = events or []
    for ev in out:
        url = ev.get("url") or ""
        if not is_hkie_event_detail_url(url):
            stats["skipped_no_url"] += 1
            continue
        ev_date = ev.get("date") or ""
        if ev_date and ev_date < cutoff:
            stats["skipped_past"] += 1
            continue
        stats["candidates"] += 1
        if fetches >= MAX_DETAIL_FETCHES:
            stats["failed"] += 1
            continue
        try:
            payload = fetch_payload(url)
        except Exception:
            stats["failed"] += 1
            continue
        fetches += 1
        stats["fetched"] += 1
        if not payload:
            stats["failed"] += 1
            continue
        html = payload.get("html") if isinstance(payload, dict) else None
        if not html:
            stats["failed"] += 1
            continue
        detail = parse_hkie_event_detail(
            html,
            api_title=payload.get("title") if isinstance(payload, dict) else None,
            existing_title=ev.get("title"),
        )
        if not detail.get("detail_ok"):
            stats["failed"] += 1
            continue
        apply_hkie_detail(ev, detail)
        stats["enriched"] += 1
    return out, stats


def fetch_hkie_detail_payload(
    event_page_url: str,
    session=None,
) -> Optional[Dict[str, Any]]:
    """POST the public HKIE eventdetail API (organiser content only)."""
    import requests
    try:
        from fetch import HEADERS, log  # type: ignore
    except Exception:  # pragma: no cover
        HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 "
                "(compatible; CPDHunterBot/2.2; free CPD calendar)"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-GB,en;q=0.9,zh-HK;q=0.8",
        }

        def log(*a):
            return None

    eid = hkie_event_id_from_url(event_page_url)
    if not eid:
        return None
    sess = session or requests.Session()
    try:
        r = sess.post(
            HKIE_API,
            headers={
                **HEADERS,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": event_page_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            data={"action": "eventdetail", "lang": "en", "eid": eid},
            timeout=40,
        )
        if r.status_code != 200:
            return None
        payload = r.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        html = data.get("html")
        title = data.get("title")
        if not isinstance(html, str) or not html.strip():
            return None
        return {
            "title": title if isinstance(title, str) else None,
            "html": html,
            "eid": eid,
        }
    except Exception as ex:
        log(f"  HKIE eventdetail enrich fail {eid}: {ex}")
        return None


def enrich_hkie_events_from_api(events: List[dict], *, sleep_s: float = 0.2) -> Tuple[List[dict], Dict[str, int]]:
    cache: Dict[str, Optional[Dict[str, Any]]] = {}

    def fetch(url: str):
        key = (url or "").split("#")[0].split("?")[0]
        if key not in cache:
            cache[key] = fetch_hkie_detail_payload(url)
            if sleep_s:
                time.sleep(sleep_s)
        return cache[key]

    return enrich_hkie_events(events, fetch)
