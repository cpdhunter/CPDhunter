"""Conservative attendance-mode classification.

Absence of online evidence is UNKNOWN, not face-to-face.
online is False is not physical evidence by itself.
Do not use AI to infer mode.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

MODE_ONLINE = "ONLINE"
MODE_FACE_TO_FACE = "FACE_TO_FACE"
MODE_HYBRID = "HYBRID"
MODE_UNKNOWN = "UNKNOWN"
VALID = frozenset({MODE_ONLINE, MODE_FACE_TO_FACE, MODE_HYBRID, MODE_UNKNOWN})

HYBRID_PATTERNS = [
    re.compile(r"\bhybrid\b", re.I),
    re.compile(r"\bblended\b", re.I),
    re.compile(r"混合(?:模式|形式)?"),
    re.compile(r"線上[及和與/]實體"),
    re.compile(r"網上[及和與/]實體"),
    re.compile(
        r"online\s*(?:and|&)\s*(?:in[- ]?person|physical|face[- ]?to[- ]?face)",
        re.I,
    ),
    re.compile(
        r"(?:in[- ]?person|physical|face[- ]?to[- ]?face)\s*(?:and|&)\s*online",
        re.I,
    ),
]

ONLINE_PATTERNS = [
    re.compile(r"\bonline(?:\s+event|\s+seminar|\s+course|\s+session)?\b", re.I),
    re.compile(r"\bwebinar\b", re.I),
    re.compile(r"\bvirtual\b", re.I),
    re.compile(r"\bzoom\b", re.I),
    re.compile(r"\bmicrosoft teams\b", re.I),
    re.compile(r"\bwebex\b", re.I),
    re.compile(r"網上(?:活動|講座|課程|研討會)?"),
    re.compile(r"線上(?:活動|講座|課程|研討會)?"),
    re.compile(r"視像(?:會議|講座)?"),
]

FACE_PATTERNS = [
    re.compile(r"\bface[- ]?to[- ]?face\b", re.I),
    re.compile(r"\bin[- ]?person\b", re.I),
    re.compile(r"\bphysical attendance\b", re.I),
    re.compile(r"實體(?:活動|講座|課程|研討會|考察|參觀)?"),
    re.compile(r"面授(?:課程|講座)?"),
    re.compile(r"現場(?:參與|出席|講座)?"),
]


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def evidence_text(event: Optional[Dict[str, Any]]) -> str:
    if not event:
        return ""
    reg = event.get("registration") if isinstance(event.get("registration"), dict) else {}
    parts = [
        event.get("modeText"),
        event.get("attendanceMode"),
        event.get("name") or event.get("title"),
        event.get("venue"),
        event.get("location"),
        event.get("description"),
        reg.get("modeText") if reg else None,
    ]
    return " | ".join(_clean(p) for p in parts if _clean(p))


def _any(patterns: Iterable[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def infer_mode(event: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not event or not isinstance(event, dict):
        return {"mode": MODE_UNKNOWN, "confidence": "LOW", "reason": "no_event"}

    explicit = re.sub(r"[ -]+", "_", _clean(event.get("mode"))).upper()
    if explicit in VALID:
        return {"mode": explicit, "confidence": "HIGH", "reason": "explicit_mode"}

    text = evidence_text(event)
    if _any(HYBRID_PATTERNS, text):
        return {"mode": MODE_HYBRID, "confidence": "HIGH", "reason": "explicit_hybrid_text"}

    online = _any(ONLINE_PATTERNS, text)
    face = _any(FACE_PATTERNS, text)
    if online and face:
        return {"mode": MODE_HYBRID, "confidence": "HIGH", "reason": "online_and_face_evidence"}
    if online:
        return {"mode": MODE_ONLINE, "confidence": "HIGH", "reason": "explicit_online_text"}
    if face:
        return {"mode": MODE_FACE_TO_FACE, "confidence": "HIGH", "reason": "explicit_face_text"}

    if event.get("online") is True or event.get("is_online") is True:
        return {"mode": MODE_ONLINE, "confidence": "MEDIUM", "reason": "legacy_online_true"}

    online_flag = event.get("online")
    if online_flag is None:
        online_flag = event.get("is_online")
    return {
        "mode": MODE_UNKNOWN,
        "confidence": "LOW",
        "reason": "legacy_false_insufficient" if online_flag is False else "insufficient_evidence",
    }


def mode_of(event: Optional[Dict[str, Any]]) -> str:
    return infer_mode(event)["mode"]


def attach_mode(event: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp mode only when evidence is reliable. Never invent FACE_TO_FACE from online=false."""
    inferred = infer_mode(event)
    if inferred["mode"] != MODE_UNKNOWN:
        event["mode"] = inferred["mode"]
    return event
