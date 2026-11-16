"""Shadow CIC parser: real event cards only; never treat Event Types vocabulary as a title."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from ._prod import _SCRAPER  # noqa: F401  # ensures scraper/ is on sys.path
from event_mode import attach_mode
from fetch import _cic_clean_title, hours_from_range, parse_date, parse_time_range
from title_quality import CIC_EVENT_TYPE_LABELS, is_filter_or_badge_title, is_good_title

from .paths import CIC_URL, CSS_CIC_CARD, IDENT_CIC_CARD
from .schema import confidence_of, shadow_event
from .selector_util import css_attr, css_text, element_text, make_selector

# All card wrappers on the current CIC listing fixture/page.
CARD_CSS = "article.event-card, div.event-card"
SOURCE = "CIC"


def _reject_title(title: str) -> bool:
    if not title:
        return True
    if is_filter_or_badge_title(title):
        return True
    if title.strip().lower() in CIC_EVENT_TYPE_LABELS:
        return True
    if not is_good_title(title):
        return True
    return False


def parse_cic_html(
    html: str,
    base: str = CIC_URL,
    storage_file: Optional[str] = None,
    adaptive: bool = False,
) -> Dict[str, Any]:
    """Parse CIC events listing HTML via Scrapling.

    Returns shadow events plus diagnostic candidate counts. Does not write files
    other than optional adaptive-state updates when storage_file is provided and
    a baseline save is requested by the caller (this function only reads).
    """
    from .paths import STATE_CIC

    storage_file = storage_file or STATE_CIC
    page = make_selector(html, base, storage_file, adaptive=True)
    cards = page.css(CARD_CSS)
    selector_used = CARD_CSS
    adaptive_used = False
    if not cards and adaptive:
        # Try the saved article-card fingerprint, then look for similar cards.
        recovered = page.css(CSS_CIC_CARD, adaptive=True, identifier=IDENT_CIC_CARD)
        if recovered:
            adaptive_used = True
            cards = recovered
            selector_used = f"{CSS_CIC_CARD}#adaptive:{IDENT_CIC_CARD}"

    candidates: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    for card in cards or []:
        raw_heading = css_text(card, "h1, h2, h3, h4")
        raw_link = css_text(card, "a")
        href = css_attr(card, "a", "href")
        date_el = css_text(card, "span.date, .date, time")
        ctx = element_text(card)
        title = _cic_clean_title(raw_heading) or _cic_clean_title(raw_link)
        date_s = parse_date(date_el) or parse_date(ctx)
        href = urljoin(base, href) if href else None
        cand = {
            "raw_heading": raw_heading,
            "raw_link": raw_link,
            "title": title,
            "date": date_s,
            "url": href,
        }
        candidates.append(cand)
        if _reject_title(title) or not date_s:
            continue
        times = parse_time_range(ctx) or (None, None)
        start_t, end_t = times if times and times[0] else (None, None)
        hrs = hours_from_range(start_t, end_t) if start_t and end_t else None
        ev = shadow_event(
            source=SOURCE,
            title=title,
            date=date_s,
            start_time=start_t,
            end_time=end_t,
            url=href,
            hrs=hrs,
            extraction_method="scrapling-adaptive" if adaptive_used else "scrapling-css",
            selector_strategy=selector_used,
            adaptive_match_used=adaptive_used,
            confidence=confidence_of(title, date_s, href, start_time=start_t, end_time=end_t, hrs=hrs),
        )
        # Listing-only: attach_mode may stay UNKNOWN; that is correct.
        attach_mode(ev)
        if "mode" not in ev:
            ev["mode"] = "UNKNOWN"
        events.append(ev)

    # Dedup by date+title (shadow-local; not production dedup).
    seen = set()
    uniq = []
    for e in events:
        k = (e.get("date"), (e.get("title") or "")[:80])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)

    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    future = [e for e in uniq if (e.get("date") or "") >= today]
    return {
        "events": uniq,
        "candidate_count": len(candidates),
        "valid_title_count": len(uniq),
        "future_event_count": len(future),
        "selector_strategy": selector_used,
        "adaptive_match_used": adaptive_used,
        "candidates": candidates,
    }
