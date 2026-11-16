"""Helpers for constructing Scrapling Selectors with isolated JSON adaptive state."""
from __future__ import annotations

from typing import Optional

from scrapling import Selector

from .json_storage import JsonFileStorage


def make_selector(html: str, url: str, storage_file: str, adaptive: bool = True) -> Selector:
    return Selector(
        html,
        url=url,
        adaptive=adaptive,
        storage=JsonFileStorage,
        storage_args={"storage_file": storage_file, "url": url},
    )


def element_text(el) -> str:
    """Visible text of a Scrapling node. Never use .get() — that returns HTML."""
    if el is None:
        return ""
    text = getattr(el, "text", None)
    if isinstance(text, str) and text.strip():
        return " ".join(text.split()).strip()
    if hasattr(el, "get_all_text"):
        try:
            raw = el.get_all_text(separator=" ")
        except TypeError:
            raw = el.get_all_text()
        if isinstance(raw, str) and raw.strip():
            return " ".join(raw.split()).strip()
    return ""


def css_text(el, selector: str) -> str:
    if el is None:
        return ""
    found = el.css(selector)
    if not found:
        return ""
    # Join unique non-empty descendant texts of each match, in order.
    parts = []
    seen = set()
    for node in found:
        t = element_text(node)
        if t and t not in seen:
            seen.add(t)
            parts.append(t)
    return " ".join(parts)


def css_attr(el, selector: str, attr: str) -> str:
    if el is None:
        return ""
    found = el.css(selector)
    if not found:
        return ""
    attrib = getattr(found[0], "attrib", None) or {}
    return (attrib.get(attr) or "").strip()
