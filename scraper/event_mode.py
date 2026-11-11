"""Conservative attendance-mode classification.

online is False is not physical evidence by itself.
A high-confidence physical venue/address may be FACE_TO_FACE only when it was
extracted from the official event-specific detail page (venueSource=event_detail)
and that same page has no online joining option.
Listing-page venues, district names, and organisation names alone remain UNKNOWN.
Do not use AI to infer mode.

Registration-channel wording (Online Registration, Register Online, 網上報名, …)
is not attendance-mode evidence. Labelled Venue / Mode / Registration fields
are parsed separately and never concatenated into one keyword scan.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

MODE_ONLINE = "ONLINE"
MODE_FACE_TO_FACE = "FACE_TO_FACE"
MODE_HYBRID = "HYBRID"
MODE_UNKNOWN = "UNKNOWN"
VALID = frozenset({MODE_ONLINE, MODE_FACE_TO_FACE, MODE_HYBRID, MODE_UNKNOWN})

MODE_EVIDENCE_EXPLICIT_MODE_FIELD = "explicit_mode_field"
MODE_EVIDENCE_EXPLICIT_ATTENDANCE_TEXT = "explicit_attendance_text"
MODE_EVIDENCE_EXPLICIT_ONLINE_TEXT = "explicit_online_text"
MODE_EVIDENCE_EXPLICIT_FACE_TEXT = "explicit_face_text"
MODE_EVIDENCE_PHYSICAL_ADDRESS_NO_ONLINE = "physical_address_no_online"
MODE_EVIDENCE_LEGACY_ONLINE_TRUE = "legacy_online_true"
MODE_EVIDENCE_UNKNOWN = "unknown"
VALID_MODE_EVIDENCE = frozenset({
    MODE_EVIDENCE_EXPLICIT_MODE_FIELD,
    MODE_EVIDENCE_EXPLICIT_ATTENDANCE_TEXT,
    MODE_EVIDENCE_EXPLICIT_ONLINE_TEXT,
    MODE_EVIDENCE_EXPLICIT_FACE_TEXT,
    MODE_EVIDENCE_PHYSICAL_ADDRESS_NO_ONLINE,
    MODE_EVIDENCE_LEGACY_ONLINE_TRUE,
    MODE_EVIDENCE_UNKNOWN,
})

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
    re.compile(r"網上(?:活動|講座|課程|研討會|參與|出席|進行)?"),
    re.compile(r"線上(?:活動|講座|課程|研討會|參與|出席|進行)?"),
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

# Structured Mode / Attendance / Format values only (not body-text scans).
_STRUCTURED_HYBRID_RE = re.compile(
    r"^\s*(?:hybrid|blended|混合(?:模式|形式)?)\s*$", re.I
)
_STRUCTURED_FACE_RE = re.compile(
    r"\bface[- ]?to[- ]?face\b|\bin[- ]?person\b|\bphysical\b|實體|面授|現場",
    re.I,
)
_STRUCTURED_ONLINE_RE = re.compile(
    r"^\s*(?:online|virtual|網上|線上)\s*$", re.I
)

# Longest labels first so "Attendance Mode" wins over "Mode".
_LABEL_SPECS = (
    ("registration", (
        "registration", "enrolment", "enrollment",
        "報名方法", "報名方式", "報名途徑", "報名須知", "報名",
        "登記方法", "登記方式", "登記",
    )),
    ("mode", (
        "attendance mode", "attendance", "format",
        "上課形式", "參與形式", "上課模式", "進行形式", "活動形式",
        "形式", "模式", "mode",
    )),
    ("venue", (
        "講座地點", "舉辦地點", "venue", "location", "場地", "地點",
    )),
)

_LABEL_TO_CANON = {
    label.lower(): canon
    for canon, labels in _LABEL_SPECS
    for label in labels
}
_LABEL_ALT = "|".join(
    sorted((re.escape(label) for label in _LABEL_TO_CANON), key=len, reverse=True)
)
_LABELLED_FIELD_RE = re.compile(
    rf"(?P<label>{_LABEL_ALT})\s*[:：]\s*(?P<value>.+?)(?=\s+(?:{_LABEL_ALT})\s*[:：]|$)",
    re.I | re.S,
)

REGISTRATION_CHANNEL_PATTERNS = [
    re.compile(r"\bonline\s+registrations?\b", re.I),
    re.compile(r"\bonline\s+enrolments?\b", re.I),
    re.compile(r"\bonline\s+enrollments?\b", re.I),
    re.compile(r"\bregister(?:ing|ed)?\s+online\b", re.I),
    re.compile(r"\benrol(?:s|ling|led|ment)?\s+online\b", re.I),
    re.compile(r"\benroll(?:s|ing|ed|ment)?\s+online\b", re.I),
    re.compile(r"\bonline\s+enrol(?:s|ment|ments)?\b", re.I),
    re.compile(r"\bonline\s+enroll(?:s|ment|ments)?\b", re.I),
    re.compile(r"\bonline\s+applications?\b", re.I),
    re.compile(r"\bapply(?:ing|ied)?\s+online\b", re.I),
    re.compile(r"網上報名(?:須知|表格|系統|連結|鏈接)?"),
    re.compile(r"網上登記(?:須知|表格|系統)?"),
    re.compile(r"網上註冊"),
    re.compile(r"網上申請"),
    re.compile(r"線上報名(?:須知|表格|系統|連結|鏈接)?"),
    re.compile(r"線上登記(?:須知|表格|系統)?"),
    re.compile(r"線上註冊"),
    re.compile(r"線上申請"),
]

STREET_NUMBER_RE = re.compile(r"[道街路里巷]\s*\d+\s*號|\d+\s*號")
ENGLISH_STREET_RE = re.compile(
    r"\d+\s+[A-Za-z][\w.'-]*(?:\s+[A-Za-z][\w.'-]*)*\s+"
    r"(?:Street|Road|Avenue|Drive|Lane|Boulevard|Place|Square|Highway|"
    r"Rd\.?|St\.?|Ave\.?|Dr\.?|Ln\.?|Blvd\.?)\b",
    re.I,
)
NAMED_PLACE_RE = re.compile(
    r"演講廳|講座室|職業健康診所|太空館|圖書館|會議展覽中心|會展中心|"
    r"培訓中心|會議室|會議廳|"
    r"\bconvention\s+cent(?:re|er)\b|\bexhibition\s+cent(?:re|er)\b|"
    r"\bauditorium\b|\blecture\s+(?:room|theatre|theater|hall)\b|"
    r"\b(?:training|conference)\s+cent(?:re|er)\b|\bconference\s+room\b",
    re.I,
)
LECTURE_ROOM_RE = re.compile(
    r"\b(?:lecture\s+(?:room|theatre|theater|hall)|room)\s+[A-Z0-9]",
    re.I,
)
FLOOR_OR_BLOCK_RE = re.compile(r"\d+\s*/\s*F|\d+\s*樓|\b(?:floor|block|campus)\b", re.I)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _any(patterns: Iterable[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def strip_registration_channel(text: str) -> str:
    """Remove registration-channel wording before attendance-mode scans."""
    out = text or ""
    for pattern in REGISTRATION_CHANNEL_PATTERNS:
        out = pattern.sub(" ", out)
    return _clean(out)


def parse_labelled_fields(*texts: Any) -> Dict[str, str]:
    """Parse labelled Venue / Mode / Registration fields from official page text.

    Fields are returned separately. Registration is never used as attendance
    evidence; callers must not concatenate these values into one keyword scan.
    """
    found: Dict[str, str] = {}
    for raw in texts:
        text = str(raw or "")
        if not text.strip():
            continue
        for match in _LABELLED_FIELD_RE.finditer(text):
            canon = _LABEL_TO_CANON.get(match.group("label").lower())
            value = _clean(match.group("value"))
            if canon and value and canon not in found:
                found[canon] = value
    return found


def _event_source_texts(event: Optional[Dict[str, Any]]) -> list[str]:
    if not event:
        return []
    return [
        event.get("modeText"),
        event.get("attendanceMode"),
        event.get("format"),
        event.get("name") or event.get("title"),
        event.get("venue"),
        event.get("location"),
        event.get("description"),
    ]


def labelled_fields_from_event(event: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Collect structured venue / mode / registration fields from an event."""
    if not event or not isinstance(event, dict):
        return {}
    fields = parse_labelled_fields(*_event_source_texts(event))
    # Dedicated attendance/format keys are structured mode fields, not body text.
    for key in ("attendanceMode", "format"):
        raw = _clean(event.get(key))
        if raw and "mode" not in fields:
            parsed = parse_labelled_fields(raw)
            fields["mode"] = parsed.get("mode") or raw
    mode_text = _clean(event.get("modeText"))
    if mode_text and "mode" not in fields:
        parsed = parse_labelled_fields(mode_text)
        if parsed.get("mode"):
            fields["mode"] = parsed["mode"]
        elif map_structured_mode(mode_text):
            fields["mode"] = mode_text
    if "venue" not in fields:
        for key in ("venue", "location"):
            raw = _clean(event.get(key))
            if raw:
                parsed = parse_labelled_fields(raw)
                if parsed.get("venue"):
                    fields["venue"] = parsed["venue"]
                    break
    reg = event.get("registration") if isinstance(event.get("registration"), dict) else {}
    for candidate in (
        fields.get("registration"),
        event.get("registrationText"),
        reg.get("modeText") if reg else None,
        reg.get("channel") if reg else None,
    ):
        raw = _clean(candidate)
        if raw:
            parsed = parse_labelled_fields(raw)
            fields["registration"] = parsed.get("registration") or raw
            break
    return fields


def map_structured_mode(value: Any) -> Optional[str]:
    """Map an explicit Mode / Attendance / Format field value. Not a body-text scan."""
    t = strip_registration_channel(_clean(value))
    if not t:
        return None
    if _STRUCTURED_HYBRID_RE.search(t) or _any(HYBRID_PATTERNS, t):
        return MODE_HYBRID
    face = bool(_STRUCTURED_FACE_RE.search(t) or _any(FACE_PATTERNS, t))
    online = bool(_STRUCTURED_ONLINE_RE.search(t) or _any(ONLINE_PATTERNS, t))
    if face and online:
        return MODE_HYBRID
    if face:
        return MODE_FACE_TO_FACE
    if online:
        return MODE_ONLINE
    return None


def _drop_labelled_registration(text: str) -> str:
    def repl(match: re.Match) -> str:
        canon = _LABEL_TO_CANON.get(match.group("label").lower())
        return " " if canon == "registration" else match.group(0)
    return _LABELLED_FIELD_RE.sub(repl, text or "")


def attendance_evidence_text(event: Optional[Dict[str, Any]]) -> str:
    """Attendance-only evidence: registration fields and phrases are removed first."""
    if not event:
        return ""
    parts = []
    for raw in _event_source_texts(event):
        text = _clean(raw)
        if not text:
            continue
        text = _drop_labelled_registration(text)
        text = strip_registration_channel(text)
        if text:
            parts.append(text)
    return " | ".join(parts)


def evidence_text(event: Optional[Dict[str, Any]]) -> str:
    """Attendance evidence only. Registration-channel text is never included."""
    return attendance_evidence_text(event)


def from_event_detail(event: Optional[Dict[str, Any]]) -> bool:
    """True when venue/mode evidence was taken from an official event detail page."""
    if not event or not isinstance(event, dict):
        return False
    src = _clean(
        event.get("venueSource") or event.get("modeSource") or event.get("evidenceSource")
    ).lower()
    return src in {"event_detail", "detail", "official_detail"}


def _venue_evidence_text(event: Optional[Dict[str, Any]]) -> str:
    if not event or not isinstance(event, dict):
        return ""
    fields = labelled_fields_from_event(event)
    parts = [event.get("venue"), event.get("location"), fields.get("venue")]
    return " | ".join(_clean(p) for p in parts if _clean(p))


def has_physical_address(event: Optional[Dict[str, Any]]) -> bool:
    """True only for a real physical address/venue, not a district or org name."""
    if not event or not isinstance(event, dict):
        return False
    text = _venue_evidence_text(event)
    if not text:
        return False
    if STREET_NUMBER_RE.search(text) or ENGLISH_STREET_RE.search(text):
        return True
    if NAMED_PLACE_RE.search(text):
        return True
    if LECTURE_ROOM_RE.search(text) and FLOOR_OR_BLOCK_RE.search(text):
        return True
    return False


def _result(mode: str, confidence: str, reason: str, mode_evidence: str) -> Dict[str, str]:
    if mode_evidence not in VALID_MODE_EVIDENCE:
        mode_evidence = MODE_EVIDENCE_UNKNOWN
    return {
        "mode": mode,
        "confidence": confidence,
        "reason": reason,
        "mode_evidence": mode_evidence,
    }


def infer_mode(event: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not event or not isinstance(event, dict):
        return _result(MODE_UNKNOWN, "LOW", "no_event", MODE_EVIDENCE_UNKNOWN)

    explicit = re.sub(r"[ -]+", "_", _clean(event.get("mode"))).upper()
    if explicit in VALID:
        evidence = (
            MODE_EVIDENCE_EXPLICIT_MODE_FIELD
            if explicit != MODE_UNKNOWN
            else MODE_EVIDENCE_UNKNOWN
        )
        return _result(explicit, "HIGH" if explicit != MODE_UNKNOWN else "LOW", "explicit_mode", evidence)

    structured = map_structured_mode(labelled_fields_from_event(event).get("mode"))
    if structured:
        return _result(
            structured, "HIGH", "explicit_mode_field", MODE_EVIDENCE_EXPLICIT_MODE_FIELD
        )

    text = attendance_evidence_text(event)
    if _any(HYBRID_PATTERNS, text):
        return _result(
            MODE_HYBRID, "HIGH", "explicit_hybrid_text", MODE_EVIDENCE_EXPLICIT_ATTENDANCE_TEXT
        )

    online = _any(ONLINE_PATTERNS, text)
    face = _any(FACE_PATTERNS, text)
    physical = from_event_detail(event) and has_physical_address(event)
    if online and (face or physical):
        return _result(
            MODE_HYBRID, "HIGH", "online_and_face_evidence", MODE_EVIDENCE_EXPLICIT_ATTENDANCE_TEXT
        )
    if online:
        return _result(
            MODE_ONLINE, "HIGH", "explicit_online_text", MODE_EVIDENCE_EXPLICIT_ONLINE_TEXT
        )
    if face:
        return _result(
            MODE_FACE_TO_FACE, "HIGH", "explicit_face_text", MODE_EVIDENCE_EXPLICIT_FACE_TEXT
        )

    if event.get("online") is True or event.get("is_online") is True:
        return _result(
            MODE_ONLINE, "MEDIUM", "legacy_online_true", MODE_EVIDENCE_LEGACY_ONLINE_TRUE
        )

    if physical:
        return _result(
            MODE_FACE_TO_FACE,
            "HIGH",
            "physical_address_no_online",
            MODE_EVIDENCE_PHYSICAL_ADDRESS_NO_ONLINE,
        )

    online_flag = event.get("online")
    if online_flag is None:
        online_flag = event.get("is_online")
    return _result(
        MODE_UNKNOWN,
        "LOW",
        "legacy_false_insufficient" if online_flag is False else "insufficient_evidence",
        MODE_EVIDENCE_UNKNOWN,
    )


def mode_of(event: Optional[Dict[str, Any]]) -> str:
    return infer_mode(event)["mode"]


def attach_mode(event: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp mode only when evidence is reliable. Never invent FACE_TO_FACE from online=false or a listing-only venue.

    mode_evidence is a classifier diagnostic only and is not written onto the event.
    """
    inferred = infer_mode(event)
    if inferred["mode"] != MODE_UNKNOWN:
        event["mode"] = inferred["mode"]
    return event
