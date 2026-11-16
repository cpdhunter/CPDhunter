"""Build realistic DOM-drift and decoy fixtures from official production fixtures."""
from __future__ import annotations

import os

from bs4 import BeautifulSoup, Tag

from .paths import (
    CIC_DECOY,
    CIC_DRIFT,
    HKGBC_DECOY,
    HKGBC_DRIFT,
    HKIE_DECOY,
    HKIE_DRIFT,
    PRODUCTION_CIC,
    PRODUCTION_HKGBC,
    PRODUCTION_HKIE,
    SHADOW_FIXTURES,
)


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _rename_class(el: Tag, old: str, new: str) -> None:
    classes = list(el.get("class") or [])
    el["class"] = [new if c == old else c for c in classes]


def _prepend(soup: BeautifulSoup, snippet_html: str) -> None:
    body = soup.body or soup
    fragment = BeautifulSoup(snippet_html, "html.parser")
    # insert nodes in reverse so original order is kept
    nodes = list(fragment.contents)
    for node in reversed(nodes):
        if str(node).strip():
            body.insert(0, node)


CIC_SIDEBAR = """
<aside class="site-nav" id="sidebar">
  <article class="nav-card">
    <h3>Events</h3>
    <span class="date">Calendar</span>
    <a href="/en/events">CIC Events Calendar</a>
  </article>
</aside>
"""

HKIE_SIDEBAR = """
<nav class="site-sidebar" id="sidebar">
  <div class="sidebar-widget">
    <h2 class="elementor-heading-title"><a href="https://hkie.org.hk/events/">Upcoming HKIE Events</a></h2>
    <span>All year</span>
  </div>
</nav>
"""

HKGBC_SIDEBAR = """
<aside class="site-nav" id="sidebar">
  <div class="nav-card">
    <p class="date"><span class="eventDate">Menu</span></p>
    <p class="category">HKGBC Event</p>
    <a href="/eng/news-events/events-trainings/events">All HKGBC Events</a>
  </div>
</aside>
"""


def build_cic_fixtures() -> None:
    html = open(PRODUCTION_CIC, encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select(".event-card"):
        _rename_class(card, "event-card", "event-tile")
    calendar = soup.select_one(".calendar")
    if calendar and calendar.parent:
        wrap = soup.new_tag("div", attrs={"class": "listing-wrap"})
        calendar.wrap(wrap)
    _prepend(soup, CIC_SIDEBAR)
    _write(CIC_DRIFT, str(soup))

    decoy = BeautifulSoup("<!DOCTYPE html><html><body></body></html>", "html.parser")
    _prepend(decoy, CIC_SIDEBAR)
    cal = decoy.new_tag("div", attrs={"class": "calendar"})
    decoy.body.append(cal)
    _write(CIC_DECOY, str(decoy))


def build_hkie_fixtures() -> None:
    html = open(PRODUCTION_HKIE, encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select(".e-loop-item"):
        _rename_class(card, "e-loop-item", "course-loop-item")
        wrap = soup.new_tag("div", attrs={"class": "inserted-wrapper"})
        # Move existing children into an extra wrapper (one wrapper inserted).
        children = list(card.contents)
        for child in children:
            wrap.append(child.extract())
        card.append(wrap)
    _prepend(soup, HKIE_SIDEBAR)
    _write(HKIE_DRIFT, str(soup))

    decoy = BeautifulSoup(html, "html.parser")
    for card in list(decoy.select(".e-loop-item")):
        card.decompose()
    _prepend(decoy, HKIE_SIDEBAR)
    _write(HKIE_DECOY, str(decoy))


def build_hkgbc_fixtures() -> None:
    html = open(PRODUCTION_HKGBC, encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select(".event-card, .eventpost"):
        classes = list(card.get("class") or [])
        card["class"] = [
            "event-block" if c in {"event-card", "eventpost"} else c for c in classes
        ]
    _prepend(soup, HKGBC_SIDEBAR)
    _write(HKGBC_DRIFT, str(soup))

    decoy = BeautifulSoup("<!DOCTYPE html><html><body></body></html>", "html.parser")
    _prepend(decoy, HKGBC_SIDEBAR)
    _write(HKGBC_DECOY, str(decoy))


def build_all() -> list:
    os.makedirs(SHADOW_FIXTURES, exist_ok=True)
    build_cic_fixtures()
    build_hkie_fixtures()
    build_hkgbc_fixtures()
    return [CIC_DRIFT, CIC_DECOY, HKIE_DRIFT, HKIE_DECOY, HKGBC_DRIFT, HKGBC_DECOY]


if __name__ == "__main__":
    for p in build_all():
        print("wrote", p, os.path.getsize(p))
