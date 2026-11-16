"""Shadow-only event record. Never copied automatically into production schema."""
from __future__ import annotations

from typing import Any, Dict, Optional


SHADOW_FIELDS = (
    "source",
    "title",
    "date",
    "start_time",
    "end_time",
    "url",
    "registration_url",
    "hrs",
    "free",
    "mode",
    "extraction_method",
    "selector_strategy",
    "adaptive_match_used",
    "confidence",
)


def shadow_event(
    *,
    source: str,
    title: str,
    date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    url: Optional[str] = None,
    registration_url: Optional[str] = None,
    hrs: Optional[float] = None,
    free: Optional[bool] = None,
    mode: Optional[str] = None,
    extraction_method: str = "scrapling-css",
    selector_strategy: str = "",
    adaptive_match_used: bool = False,
    confidence: float = 0.0,
) -> Dict[str, Any]:
    return {
        "source": source,
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "url": url,
        "registration_url": registration_url or url,
        "hrs": hrs,
        "free": free,
        "mode": mode or "UNKNOWN",
        "extraction_method": extraction_method,
        "selector_strategy": selector_strategy,
        "adaptive_match_used": bool(adaptive_match_used),
        "confidence": round(float(confidence), 3),
    }


def confidence_of(title: str, date: Optional[str], url: Optional[str], **extra) -> float:
    score = 0.0
    if title:
        score += 0.4
    if date:
        score += 0.3
    if url:
        score += 0.2
    if extra.get("start_time") and extra.get("end_time"):
        score += 0.05
    if extra.get("hrs") is not None:
        score += 0.05
    return min(score, 1.0)
