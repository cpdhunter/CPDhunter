"""HKIE Events complete discovery from the official public eventlist API.

The official Events page (theme_event.js) loads the list with:

    POST https://hkie.org.hk/hkie_api/index.php
    action=eventlist  lang=en  site=main  listgroup=all
    daterange=DD/MM/YYYY - DD/MM/YYYY

The site date picker uses maxSpan=30 days (today + 30 by default). This
module iterates official 30-day windows from TODAY through TODAY+180
(CPD Hunter's existing KEEP_DAYS_AHEAD horizon) until that range is
covered. It does not invent recurrences and does not cap the event count.

Each discovery record is then passed to the existing event-detail
enrichment. This module does not parse venue, mode, hours, or
registration — those stay in hkie_event_detail.py.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

HKIE_API = "https://hkie.org.hk/hkie_api/index.php"
HKIE_EVENTS_LISTING_PATHS = frozenset({"/events", "/tc/events"})
DETAIL_URL_TMPL = "https://hkie.org.hk/events/event-detail/{eid}/"
# Official UI date-picker maxSpan (theme_event.js hkie_initDatePicker).
OFFICIAL_WINDOW_DAYS = 30
# Safety bound on date windows only — not an event-count ceiling.
# 180/30 = 6 windows; extra headroom for overlap / clock skew.
MAX_WINDOWS = 16
_DATE_SEP = " - "


def _horizon_days() -> int:
    try:
        from fetch import KEEP_DAYS_AHEAD  # type: ignore

        return int(KEEP_DAYS_AHEAD)
    except Exception:
        return 180


def _today() -> dt.date:
    try:
        from fetch import TODAY  # type: ignore

        return TODAY
    except Exception:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()


def is_hkie_events_listing_url(url: Optional[str]) -> bool:
    """True only for the official HKIE Events listing (not CPD Calendar or detail)."""
    if not url:
        return False
    p = urlparse(url.split("#")[0].strip())
    host = (p.netloc or "").lower()
    if host not in ("hkie.org.hk", "www.hkie.org.hk"):
        return False
    path = (p.path or "").rstrip("/").lower()
    return path in HKIE_EVENTS_LISTING_PATHS


def format_daterange(start: dt.date, end: dt.date) -> str:
    return f"{start.strftime('%d/%m/%Y')}{_DATE_SEP}{end.strftime('%d/%m/%Y')}"


def parse_daterange(value: Optional[str]) -> Optional[Tuple[dt.date, dt.date]]:
    if not value or _DATE_SEP not in value:
        return None
    left, right = value.split(_DATE_SEP, 1)
    try:
        start = dt.datetime.strptime(left.strip(), "%d/%m/%Y").date()
        end = dt.datetime.strptime(right.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None
    return start, end


def iter_hkie_date_windows(
    today: Optional[dt.date] = None,
    *,
    horizon_days: Optional[int] = None,
    window_days: int = OFFICIAL_WINDOW_DAYS,
) -> List[Tuple[dt.date, dt.date]]:
    """Inclusive official-style windows covering today .. today+horizon_days.

    Adjacent windows share the boundary day so events on a window edge are
    not missed. The final window ends exactly on the horizon date.
    """
    start = today or _today()
    horizon = start + dt.timedelta(days=horizon_days if horizon_days is not None else _horizon_days())
    if window_days <= 0:
        window_days = OFFICIAL_WINDOW_DAYS
    windows: List[Tuple[dt.date, dt.date]] = []
    cur = start
    while cur <= horizon:
        end = min(cur + dt.timedelta(days=window_days), horizon)
        windows.append((cur, end))
        if end >= horizon:
            break
        cur = end
    return windows


def hkie_event_detail_url(eid: str) -> str:
    return DETAIL_URL_TMPL.format(eid=eid)


def _clean_text(value: Optional[str]) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())



def _record_date(rec: Dict[str, Any]) -> Optional[dt.date]:
    raw = rec.get("date") or rec.get("date_from")
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _date_in_window(rec: Dict[str, Any], start: dt.date, end: dt.date) -> bool:
    d = _record_date(rec)
    if d is None:
        return True
    return start <= d <= end


def parse_hkie_eventlist_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one official eventlist object to a discovery record."""
    if not isinstance(item, dict):
        return None
    eid = _clean_text(str(item.get("id") or ""))
    if not eid:
        return None
    title = _clean_text(item.get("title") if isinstance(item.get("title"), str) else "")
    date_from = _clean_text(item.get("date_from") if isinstance(item.get("date_from"), str) else "")
    date_to = _clean_text(item.get("date_to") if isinstance(item.get("date_to"), str) else "")
    date = date_from
    if not date:
        # Fallback: official display date, e.g. "16 November 2026".
        try:
            from fetch import parse_date  # type: ignore

            date = parse_date(_clean_text(item.get("date") if isinstance(item.get("date"), str) else "")) or ""
        except Exception:
            date = ""
    if date and len(date) >= 10:
        date = date[:10]
    group = _clean_text(item.get("group_name") if isinstance(item.get("group_name"), str) else "")
    type_name = _clean_text(item.get("type_name") if isinstance(item.get("type_name"), str) else "")
    rec: Dict[str, Any] = {
        "official_id": eid,
        "title": title,
        "date": date or None,
        "date_from": date_from or None,
        "date_to": date_to or None,
        "url": hkie_event_detail_url(eid),
        "organizer": group or None,
        "division": group or None,
        "group_name": group or None,
        "type_name": type_name or None,
        "source_kind": "hkie-eventlist",
    }
    return rec


def parse_hkie_eventlist_payload(payload: Any) -> List[Dict[str, Any]]:
    """Parse an official eventlist JSON body (or a bare list / {data: [...]})."""
    data = payload
    if isinstance(payload, dict):
        data = payload.get("data")
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in data:
        rec = parse_hkie_eventlist_item(item) if isinstance(item, dict) else None
        if not rec:
            continue
        eid = rec["official_id"]
        if eid in seen:
            continue
        seen.add(eid)
        out.append(rec)
    return out


def discover_hkie_events(
    fetch_window: Callable[[str], Any],
    *,
    today: Optional[dt.date] = None,
    horizon_days: Optional[int] = None,
    window_days: int = OFFICIAL_WINDOW_DAYS,
    max_windows: int = MAX_WINDOWS,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Iterate official date windows and merge unique events by official id.

    fetch_window(daterange) should return an official eventlist payload
    (parsed JSON). Safety stops (not event-count ceilings):

    - max_windows
    - duplicate page (identical official-id set as an earlier window)
    - empty payload is recorded; mid-horizon gaps do not abort later windows
    - a window whose IDs are all repeats is counted; discovery continues
      unless the page is a duplicate of a previous window
    """
    start = today or _today()
    horizon = horizon_days if horizon_days is not None else _horizon_days()
    windows = iter_hkie_date_windows(start, horizon_days=horizon, window_days=window_days)
    stats: Dict[str, Any] = {
        "horizon_days": horizon,
        "window_days": window_days,
        "windows_planned": len(windows),
        "windows_fetched": 0,
        "empty_windows": 0,
        "failed_windows": 0,
        "unique_events": 0,
        "stopped": None,
        "dateranges": [],
    }
    by_id: Dict[str, Dict[str, Any]] = {}
    seen_signatures = set()
    for i, (wstart, wend) in enumerate(windows):
        if i >= max_windows:
            stats["stopped"] = "max_windows"
            break
        daterange = format_daterange(wstart, wend)
        stats["dateranges"].append(daterange)
        try:
            payload = fetch_window(daterange)
        except Exception:
            stats["failed_windows"] += 1
            stats["windows_fetched"] += 1
            continue
        stats["windows_fetched"] += 1
        records = parse_hkie_eventlist_payload(payload)
        sig = tuple(sorted(r["official_id"] for r in records))
        if not records:
            stats["empty_windows"] += 1
            seen_signatures.add(sig)
            continue
        if sig in seen_signatures:
            # Identical ID set is a real loop only when the payload is not
            # explained by the official 1-day window overlap (events dated
            # inside this window, typically the shared boundary day). If any
            # event falls outside this window, the feed is repeating a
            # previous page and we stop.
            if any(not _date_in_window(r, wstart, wend) for r in records):
                stats["stopped"] = "duplicate_page"
                break
        seen_signatures.add(sig)
        for rec in records:
            eid = rec["official_id"]
            if eid not in by_id:
                by_id[eid] = rec
    else:
        # for-loop completed without a safety break
        if stats["stopped"] is None:
            stats["stopped"] = "horizon"
    stats["unique_events"] = len(by_id)
    # Stable chronological order (official feed is already dated).
    events = sorted(
        by_id.values(),
        key=lambda r: ((r.get("date") or r.get("date_from") or ""), r.get("title") or ""),
    )
    return events, stats


def fetch_hkie_eventlist_payload(
    daterange: str,
    session=None,
) -> Dict[str, Any]:
    """POST one official public eventlist window. No login, no CAPTCHA bypass."""
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

    sess = session or requests.Session()
    r = sess.post(
        HKIE_API,
        headers={
            **HEADERS,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://hkie.org.hk/events/",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://hkie.org.hk",
        },
        data={
            "action": "eventlist",
            "lang": "en",
            "site": "main",
            "daterange": daterange,
            "group": "",
            "type": "",
            "search": "",
            "listgroup": "all",
        },
        timeout=40,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HKIE eventlist HTTP {r.status_code} for {daterange}")
    payload = r.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"HKIE eventlist non-object response for {daterange}")
    return payload


def discover_hkie_events_from_api(
    *,
    today: Optional[dt.date] = None,
    horizon_days: Optional[int] = None,
    window_days: int = OFFICIAL_WINDOW_DAYS,
    max_windows: int = MAX_WINDOWS,
    sleep_s: float = 0.2,
    session=None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    def fetch(daterange: str):
        payload = fetch_hkie_eventlist_payload(daterange, session=session)
        if sleep_s:
            time.sleep(sleep_s)
        return payload

    return discover_hkie_events(
        fetch,
        today=today,
        horizon_days=horizon_days,
        window_days=window_days,
        max_windows=max_windows,
    )

