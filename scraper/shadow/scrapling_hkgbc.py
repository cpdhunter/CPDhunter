"""Shadow HKGBC parser: reject badge-only titles; prefer heading / detail title."""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from ._prod import _SCRAPER  # noqa: F401
from event_mode import attach_mode
from fetch import _hkgbc_detail_title, parse_date
from title_quality import (
    clamp_title,
    is_filter_or_badge_title,
    is_good_title,
    strip_hkgbc_badges,
)

from .paths import CSS_HKGBC_CARD, HKGBC_URL, IDENT_HKGBC_CARD
from .schema import confidence_of, shadow_event
from .selector_util import css_attr, css_text, element_text, make_selector

SOURCE = "HKGBC"
CARD_CSS = CSS_HKGBC_CARD
DETAIL_HREF_RE = re.compile(r"events-detail|eventid=", re.I)


def _clean_title(title: str) -> str:
    title = strip_hkgbc_badges(title or "")
    title = re.sub(r"\s+", " ", title).strip()
    if "|" in title:
        bits = [b.strip() for b in title.split("|") if b.strip()]
        bits = [b for b in bits if not is_filter_or_badge_title(b) and not (parse_date(b) and len(b) < 24)]
        bits = sorted(bits, key=len, reverse=True)
        title = bits[0] if bits else title
        title = strip_hkgbc_badges(title)
    return title


def _is_badge_only(title: str) -> bool:
    t = strip_hkgbc_badges(title or "")
    return (not t) or is_filter_or_badge_title(t) or not is_good_title(t) or len(t) < 8


def parse_hkgbc_html(
    html: str,
    base: str = HKGBC_URL,
    storage_file: Optional[str] = None,
    adaptive: bool = False,
    fetch_detail: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    from .paths import STATE_HKGBC

    storage_file = storage_file or STATE_HKGBC
    page = make_selector(html, base, storage_file, adaptive=True)
    cards = page.css(CARD_CSS)
    selector_used = CARD_CSS
    adaptive_used = False
    if not cards and adaptive:
        recovered = page.css(CARD_CSS, adaptive=True, identifier=IDENT_HKGBC_CARD)
        if recovered:
            adaptive_used = True
            cards = recovered
            selector_used = f"{CARD_CSS}#adaptive:{IDENT_HKGBC_CARD}"

    events: List[Dict[str, Any]] = []
    detail_fetches = 0
    for card in cards or []:
        href = css_attr(card, "a", "href")
        # Skip page-level wrappers accidentally matching the card selector.
        if len(element_text(card)) > 1500:
            continue
        if not href or not DETAIL_HREF_RE.search(href):
            # Still accept a card that wraps a detail link one level down already missed.
            continue
        date_el = css_text(card, "span.eventDate")
        title_el = css_text(card, "p.title")
        title = _clean_title(title_el)
        d = parse_date(date_el) or parse_date(element_text(card))
        detail_url = urljoin(base, href)
        if _is_badge_only(title) and fetch_detail and detail_fetches < 8:
            try:
                html_d = fetch_detail(detail_url)
                title = _hkgbc_detail_title(html_d) or title
                title = _clean_title(title)
                detail_fetches += 1
            except Exception:
                pass
        if not d or _is_badge_only(title):
            continue
        if parse_date(title) and len(title) < 24:
            continue
        ev = shadow_event(
            source=SOURCE,
            title=clamp_title(title),
            date=d,
            url=detail_url,
            extraction_method="scrapling-adaptive" if adaptive_used else "scrapling-css",
            selector_strategy=selector_used,
            adaptive_match_used=adaptive_used,
            confidence=confidence_of(title, d, detail_url),
        )
        attach_mode(ev)
        if "mode" not in ev:
            ev["mode"] = "UNKNOWN"
        events.append(ev)

    seen = set()
    uniq = []
    for e in events:
        k = (e.get("date"), (e.get("title") or "")[:80])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    return {
        "events": uniq,
        "candidate_count": len(cards or []),
        "valid_title_count": len(uniq),
        "selector_strategy": selector_used,
        "adaptive_match_used": adaptive_used,
        "detail_fetches": detail_fetches,
    }
