"""Shadow HKIE CPD parser: extract title/date/url/time/hours inside ONE course card."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from ._prod import _SCRAPER  # noqa: F401
from event_mode import attach_mode
from fetch import hours_from_range, parse_date, parse_time_range, stated_cpd_hours
from title_quality import (
    is_date_only_title,
    is_filter_or_badge_title,
    is_good_title,
    is_time_only_title,
)

from .paths import CSS_HKIE_CARD, HKIE_URL, IDENT_HKIE_CARD
from .schema import confidence_of, shadow_event
from .selector_util import css_attr, css_text, element_text, make_selector

SOURCE = "HKIE"
CARD_CSS = CSS_HKIE_CARD
FALLBACK_CSS = ".elementor-widget-wrap"


def _card_lines(card) -> List[str]:
    """Collect text nodes inside THIS card only (never a page-global scan)."""
    lines: List[str] = []
    seen = set()
    for el in card.css(
        "h1, h2, h3, h4, .elementor-heading-title, "
        ".elementor-icon-list-text, li, span, p, time, a"
    ) or []:
        t = re.sub(r"\s+", " ", element_text(el)).strip()
        if t and t not in seen:
            seen.add(t)
            lines.append(t)
    raw = element_text(card)
    for ln in re.split(r"[\n\r]+", raw):
        t = ln.strip()
        if t and t not in seen:
            seen.add(t)
            lines.append(t)
    return lines


def _extract_from_card(card, base: str, selector_used: str, adaptive_used: bool) -> Optional[Dict[str, Any]]:
    lines = _card_lines(card)
    if not lines:
        return None
    title = None
    date_s = None
    start_t = end_t = None
    cpd_h = None

    # Headings inside THIS card only.
    headings = card.css("h1, h2, h3, h4, .elementor-heading-title") or []
    for h in headings:
        ht = re.sub(r"\s+", " ", element_text(h)).strip()
        if not ht:
            continue
        if re.match(r"^CPD\d", ht, re.I):
            continue
        if is_date_only_title(ht) or is_time_only_title(ht) or parse_time_range(ht) or stated_cpd_hours(ht) is not None:
            continue
        if len(ht) >= 15:
            title = ht
            break

    for ln in lines:
        if re.match(r"^CPD\d", ln, re.I):
            continue
        sh = stated_cpd_hours(ln)
        if sh is not None:
            cpd_h = sh
            continue
        tr = parse_time_range(ln)
        if tr or is_time_only_title(ln):
            if tr:
                start_t, end_t = tr
            continue
        if is_date_only_title(ln) or parse_date(ln):
            if date_s is None and parse_date(ln):
                date_s = ln
            continue
        if title is None and len(ln) >= 15 and not is_filter_or_badge_title(ln):
            title = ln

    if not title or not date_s:
        return None
    if is_date_only_title(title) or is_time_only_title(title) or parse_time_range(title) or stated_cpd_hours(title) is not None:
        return None
    if not is_good_title(title):
        return None
    d = parse_date(date_s)
    if not d:
        return None
    href = css_attr(card, "a", "href") or css_attr(card, "h2 a, h3 a, a", "href")
    url = urljoin(base, href) if href else base
    ev = shadow_event(
        source=SOURCE,
        title=title,
        date=d,
        start_time=start_t,
        end_time=end_t,
        url=url,
        hrs=cpd_h if cpd_h is not None else (hours_from_range(start_t, end_t) if start_t and end_t else None),
        extraction_method="scrapling-adaptive" if adaptive_used else "scrapling-css",
        selector_strategy=selector_used,
        adaptive_match_used=adaptive_used,
        confidence=confidence_of(title, d, url, start_time=start_t, end_time=end_t, hrs=cpd_h),
    )
    # Preserve stated hours separately when present (shadow-only extra is OK;
    # hrs already set). attach_mode is listing-only here.
    attach_mode(ev)
    if "mode" not in ev:
        ev["mode"] = "UNKNOWN"
    if cpd_h is not None:
        ev["hrs"] = cpd_h
        ev["cpd_hours"] = cpd_h  # diagnostic only; not a production field copy
    return ev


def parse_hkie_cpd_html(
    html: str,
    base: str = HKIE_URL,
    storage_file: Optional[str] = None,
    adaptive: bool = False,
) -> Dict[str, Any]:
    from .paths import STATE_HKIE

    storage_file = storage_file or STATE_HKIE
    page = make_selector(html, base, storage_file, adaptive=True)
    cards = page.css(CARD_CSS)
    selector_used = CARD_CSS
    adaptive_used = False
    if not cards:
        # Fallback: populated wraps that contain a CPD code heading, still per-container.
        fallback = []
        for wrap in page.css(FALLBACK_CSS) or []:
            if re.search(r"\bCPD\d{3,}/\d{4}\b", element_text(wrap)):
                fallback.append(wrap)
        cards = fallback
        if cards:
            selector_used = FALLBACK_CSS
    if not cards and adaptive:
        recovered = page.css(CARD_CSS, adaptive=True, identifier=IDENT_HKIE_CARD)
        if recovered:
            adaptive_used = True
            cards = recovered
            selector_used = f"{CARD_CSS}#adaptive:{IDENT_HKIE_CARD}"

    events: List[Dict[str, Any]] = []
    for card in cards or []:
        ev = _extract_from_card(card, base, selector_used, adaptive_used)
        if ev:
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
    }
