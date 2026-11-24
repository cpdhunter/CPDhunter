"""CIC / i-Club newsletter parser and isolated discovery pipeline.

Input: .eml or saved newsletter HTML/text. No live mailbox access.
Output: normalized candidates and a pilot report. Never writes events.json
or source_health.json. HTTP, if used at all, is GET-only and never submits
registration or fetches tracking pixels / remote email images.
"""
from __future__ import annotations

import email
import email.header
import email.policy
import email.utils
import hashlib
import json
import os
import re
import sys
from email.message import EmailMessage
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRAPER = os.path.dirname(_HERE)
if _SCRAPER not in sys.path:
    sys.path.insert(0, _SCRAPER)

from newsletter.normalize import (
    CANCELLED_RE,
    CIC_EVENT_RE,
    DISCOVERY,
    ORGANISATION,
    SOURCE_NAME,
    STATUS_ELIGIBLE,
    STATUS_REJECTED,
    STATUS_REVIEW,
    UNSUBSCRIBE_RE,
    ZOOM_JOIN_RE,
    ZOOM_MEETING_RE,
    ZOOM_WEBINAR_RE,
    apply_quality_gates,
    canonical_registration_url,
    classify_registration_url,
    classify_type_and_civil,
    clean_url,
    compare_to_production,
    confidence_for,
    destination_title_mismatch,
    infer_attendance_mode,
    infer_fee,
    is_legitimate_destination,
    looks_cancelled,
    parse_any_date,
    parse_any_time_range,
    public_candidate_view,
    set_hours,
    split_bilingual_title,
    title_is_clean,
)
from title_quality import clamp_title, strip_page_chrome
from reg_discover import explicit_closed_registration

# Explicit trusted sender / domain allowlist for CIC / i-Club newsletters.
# Subdomains of these registrable domains are accepted (e.g. mail.cic.hk).
# Arbitrary forwarded promotional mail is not authoritative.
TRUSTED_DOMAINS = frozenset({
    "cic.hk",
    "cic.org.hk",
})

# Headers that may identify a subscriber or are unrelated to provenance.
DROPPED_HEADERS = frozenset({
    "to", "cc", "bcc", "delivered-to", "x-original-to", "x-forwarded-to",
    "return-path", "message-id", "in-reply-to", "references",
    "list-unsubscribe", "list-unsubscribe-post", "list-id",
    "x-mailer", "x-originating-ip", "received", "received-spf",
    "authentication-results", "dkim-signature", "arc-seal",
    "arc-message-signature", "arc-authentication-results",
    "x-google-original-from", "x-gm-gg", "x-gm-message-state",
    "reply-to",
})

# Image / pixel URLs must never be fetched and must not appear in output.
PIXEL_HINT_RE = re.compile(
    r"(?:/pixel(?:/|\?|$)|/(?:track|tracking)(?:/|\?|$)|open\.gif|pixel\.gif|"
    r"transparent\.gif|\bbeacon\b|/collect(?:/|\?|$)|/open/(?:click|mail))",
    re.I,
)
IMG_EXT_RE = re.compile(r"\.(?:gif|png|jpe?g|webp|svg|bmp)(?:\?|$)", re.I)

# Words near a link that suggest it is a registration CTA.
REG_CTA_RE = re.compile(
    r"register|registration|enrol|enroll|sign[\s-]?up|報名|登記|立即報名|網上報名",
    re.I,
)


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def extract_sender_address(from_header: str) -> Tuple[str, str]:
    """Return (display_name, email_address_lower)."""
    name, addr = email.utils.parseaddr(from_header or "")
    return (name or "").strip(), (addr or "").strip().lower()


def sender_domain(address: str) -> str:
    if "@" not in (address or ""):
        return ""
    return address.rsplit("@", 1)[-1].strip().lower().rstrip(".")


def is_trusted_domain(domain: str) -> bool:
    d = (domain or "").lower().rstrip(".")
    if not d:
        return False
    for allowed in TRUSTED_DOMAINS:
        if d == allowed or d.endswith("." + allowed):
            return True
    return False


def is_trusted_sender(from_header: str) -> bool:
    _, addr = extract_sender_address(from_header)
    return is_trusted_domain(sender_domain(addr))


def _header_values(msg: email.message.Message, *names: str) -> List[str]:
    found = []
    for name in names:
        for val in msg.get_all(name, []):
            text = _decode_header(str(val))
            if text:
                found.append(text)
    return found


def collect_forbidden_tokens(msg: email.message.Message) -> List[str]:
    """Subscriber identity and tracking tokens that must never be emitted."""
    tokens: List[str] = []
    for raw in _header_values(
        msg,
        "To", "Cc", "Bcc", "Delivered-To", "X-Original-To", "X-Forwarded-To",
        "Message-ID", "Return-Path", "List-Unsubscribe",
    ):
        tokens.append(raw)
        name, addr = extract_sender_address(raw)
        if name and len(name) >= 3 and name.lower() not in ("cic", "cic i-club", "i-club", "iclub"):
            tokens.append(name)
        if addr and "@" in addr:
            tokens.append(addr)
            local = addr.split("@", 1)[0]
            if local and local not in ("noreply", "no-reply", "iclub", "i-club", "newsletter", "info"):
                tokens.append(local)
    # Personalization in List-Unsubscribe URLs
    for raw in _header_values(msg, "List-Unsubscribe"):
        for m in re.finditer(r"[?&](?:token|email|hash|uid)=([^&>\s]+)", raw, re.I):
            tokens.append(m.group(1))
    # Unique-ish tokens only
    cleaned = []
    for t in tokens:
        t = (t or "").strip().strip("<>").strip()
        if len(t) >= 3:
            cleaned.append(t)
    return cleaned


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def scrub_pii_text(text: str, forbidden: Iterable[str]) -> str:
    """Remove subscriber emails, names, and tokens from event text."""
    out = text or ""
    out = EMAIL_RE.sub("", out)
    # Longest tokens first so a full address is removed before its local part
    toks = sorted({(tok or "").strip().strip("<>") for tok in (forbidden or [])}, key=len, reverse=True)
    for val in toks:
        if len(val) >= 3:
            out = out.replace(val, "")
    return re.sub(r"\s+", " ", out).strip()


def _part_payload(part: email.message.Message) -> str:
    """Return a Unicode body. Prefer the already-decoded string payload.

    get_payload(decode=True) after message_from_string can re-encode
    non-ASCII as unicode-escape sequences; the string payload is reliable.
    """
    payload = part.get_payload(decode=False)
    if isinstance(payload, str) and payload:
        return payload
    try:
        body = part.get_payload(decode=True)
    except Exception:
        body = None
    if body is None:
        return payload if isinstance(payload, str) else ""
    if isinstance(body, str):
        return body
    charset = part.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def extract_bodies(msg: email.message.Message) -> Tuple[str, str]:
    html, text = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype == "text/html" and not html:
                html = _part_payload(part)
            elif ctype == "text/plain" and not text:
                text = _part_payload(part)
    else:
        ctype = (part := msg).get_content_type()
        raw = _part_payload(msg)
        if ctype == "text/html":
            html = raw
        else:
            text = raw
    return html, text


def parse_message(source: Any) -> Dict[str, Any]:
    """Parse .eml bytes/str, or treat a raw HTML/text file as a body."""
    result = {
        "kind": "unknown",
        "from_header": "",
        "subject": "",
        "html": "",
        "text": "",
        "trusted": False,
        "sender_domain": "",
        "forbidden_tokens": [],
        "parse_error": None,
        "malformed": False,
    }
    raw = source
    if hasattr(source, "read"):
        raw = source.read()
    if isinstance(raw, bytes):
        try:
            raw_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = raw.decode("utf-8", errors="replace")
    else:
        raw_text = str(raw or "")

    looks_email = bool(re.search(r"(?im)^(from|subject|mime-version|content-type):", raw_text))
    if looks_email:
        try:
            raw_bytes = raw if isinstance(raw, (bytes, bytearray)) else raw_text.encode("utf-8")
            msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
        except Exception as ex:
            result["parse_error"] = type(ex).__name__
            result["malformed"] = True
            result["kind"] = "eml"
            result["text"] = raw_text
            return result
        result["kind"] = "eml"
        result["from_header"] = _decode_header(msg.get("From", ""))
        result["subject"] = _decode_header(msg.get("Subject", ""))
        result["html"], result["text"] = extract_bodies(msg)
        _, addr = extract_sender_address(result["from_header"])
        result["sender_domain"] = sender_domain(addr)
        result["trusted"] = is_trusted_sender(result["from_header"])
        result["forbidden_tokens"] = collect_forbidden_tokens(msg)
        if not result["html"] and not result["text"] and not result["subject"]:
            result["malformed"] = True
        return result

    stripped = raw_text.strip()
    if not stripped:
        result["malformed"] = True
        result["parse_error"] = "empty"
        return result
    if re.search(r"<html|<!doctype html|<body|<table|<a\s", stripped, re.I):
        result["kind"] = "html"
        result["html"] = stripped
    else:
        result["kind"] = "text"
        result["text"] = stripped
    # Saved HTML/text has no From: not trusted unless a marker is supplied elsewhere.
    result["trusted"] = False
    return result


def apply_trusted_override(parsed: Dict[str, Any], from_header: Optional[str] = None) -> Dict[str, Any]:
    if from_header:
        parsed["from_header"] = from_header
        _, addr = extract_sender_address(from_header)
        parsed["sender_domain"] = sender_domain(addr)
        parsed["trusted"] = is_trusted_sender(from_header)
    return parsed


def _drop_footer(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    kept = []
    for line in lines:
        if UNSUBSCRIBE_RE.search(line) or re.search(
            r"this email was sent to|此電郵發送予|如不想", line, re.I
        ):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def html_event_text(html: str) -> Tuple[str, List[Dict[str, str]]]:
    """Visible text plus hrefs. Images / pixels are not fetched and not kept."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    # Drop tracking pixels from the tree so their URLs never leak into text/links
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        width = str(img.get("width") or "")
        height = str(img.get("height") or "")
        if PIXEL_HINT_RE.search(src) or IMG_EXT_RE.search(src) or (width == "1" and height == "1"):
            img.decompose()
            continue
        # Do not retain remote image URLs in output
        img.decompose()
    for tag in list(soup.find_all(["a", "p", "div", "span", "td"])):
        if tag is None or getattr(tag, "attrs", None) is None:
            continue
        href = tag.get("href") or ""
        visible = tag.get_text(" ", strip=True)[:200]
        mech, _cleaned = classify_registration_url(href) if href else (None, None)
        is_unsub = bool(UNSUBSCRIBE_RE.search(visible) or UNSUBSCRIBE_RE.search(href))
        is_pixel = bool(PIXEL_HINT_RE.search(href)) and not mech
        if is_unsub or is_pixel:
            tag.decompose()
    links = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if href.lower().startswith(("mailto:", "javascript:", "cid:", "data:")):
            continue
        if PIXEL_HINT_RE.search(href) or IMG_EXT_RE.search(href):
            continue
        if UNSUBSCRIBE_RE.search(href) or UNSUBSCRIBE_RE.search(a.get_text(" ", strip=True)):
            continue
        cleaned = clean_url(href)
        if not cleaned:
            continue
        links.append({
            "url": cleaned,
            "text": re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:200],
        })
    text = _drop_footer(soup.get_text("\n", strip=True))
    return text, links


def text_links(text: str) -> List[Dict[str, str]]:
    links = []
    for m in re.finditer(r"https?://[^\s<>\"']+", text or ""):
        href = m.group(0).rstrip(").,;]>'\"")
        if PIXEL_HINT_RE.search(href) or UNSUBSCRIBE_RE.search(href) or IMG_EXT_RE.search(href):
            continue
        cleaned = clean_url(href)
        if cleaned:
            links.append({"url": cleaned, "text": ""})
    return links


def pick_registration(links: List[Dict[str, str]], body: str) -> Tuple[Optional[str], Optional[str]]:
    """Prefer Zoom register / forms over ordinary CIC info links. Ignore join URLs."""
    ranked: List[Tuple[int, str, str]] = []
    for item in links:
        url = item.get("url") or ""
        text = item.get("text") or ""
        mech, cleaned = classify_registration_url(url)
        if not cleaned:
            continue
        if ZOOM_JOIN_RE.search(cleaned) and mech is None:
            continue
        score = 0
        if mech == "ZOOM_WEBINAR":
            score = 100
        elif mech == "ZOOM_MEETING":
            score = 90
        elif mech in ("GOOGLE_FORMS", "MICROSOFT_FORMS"):
            score = 80
        elif mech == "EVENTBRITE":
            score = 70
        elif mech == "CIC_EVENT_URL":
            score = 50
        elif mech == "OTHER_PUBLIC_FORM":
            score = 40
        else:
            score = 0
        if REG_CTA_RE.search(text) or REG_CTA_RE.search(url):
            score += 5
        if score:
            ranked.append((score, mech, cleaned))
    if ranked:
        ranked.sort(key=lambda x: -x[0])
        return ranked[0][1], ranked[0][2]
    # Bare URLs in the body (already classified via text_links)
    return None, None


def extract_titles(subject: str, body: str) -> Tuple[str, Optional[str], Optional[str]]:
    # Prefer a substantial subject; else first meaningful line / heading-like line.
    candidates = []
    if subject:
        sub = re.sub(r"^(?:fwd|fw|re)\s*:\s*", "", subject, flags=re.I).strip()
        candidates.append(sub)
    for line in (body or "").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line or len(line) < 8:
            continue
        if re.match(r"^(date|time|venue|mode|註冊|報名|日期|時間|地點|形式)\s*[:：]", line, re.I):
            continue
        if UNSUBSCRIBE_RE.search(line):
            continue
        candidates.append(line)
        if len(candidates) >= 6:
            break
    # Prefer bilingual / longer event-like titles
    def score(t: str) -> int:
        s = 0
        if re.search(r"[\u4e00-\u9fff]", t):
            s += 2
        if re.search(r"[A-Za-z]{3,}", t):
            s += 2
        if re.search(r"研討會|webinar|seminar|workshop|講座|forum|briefing", t, re.I):
            s += 3
        if title_is_clean(t):
            s += 2
        s += min(len(t), 80) // 20
        return s
    best = ""
    if candidates:
        best = max(candidates, key=score)
        # If subject is already bilingual and clean, keep it
        if candidates and title_is_clean(candidates[0]) and score(candidates[0]) >= score(best) - 2:
            best = candidates[0]
    display, zh, en = split_bilingual_title(best)
    display = clamp_title(strip_page_chrome(display)) if display else ""
    return display, zh, en


def _labelled_value(body: str, *labels: str) -> Optional[str]:
    lab = "|".join(re.escape(l) for l in labels)
    m = re.search(rf"(?:{lab})\s*[:：]\s*(.+)", body, re.I)
    if m:
        return m.group(1).strip().splitlines()[0].strip()
    return None


def extract_event_fields(subject: str, body: str, links: List[Dict[str, str]]) -> Dict[str, Any]:
    title, title_zh, title_en = extract_titles(subject, body)
    date_text = _labelled_value(
        body, "Date", "Event Date", "日期", "舉辦日期", "活動日期", "Date & Time", "Date and Time"
    )
    time_text = _labelled_value(body, "Time", "時間", "舉辦時間", "活動時間")
    date = parse_any_date(date_text or "") or parse_any_date(subject) or parse_any_date(body)
    times = parse_any_time_range(time_text or "") or parse_any_time_range(date_text or "") or parse_any_time_range(body)
    start = end = None
    if times:
        start, end = times
    mech, dest = pick_registration(links, body)
    typ, civil, discs = classify_type_and_civil(title, title_zh or "", title_en or "", body)
    mode = infer_attendance_mode(title, body)
    fee = infer_fee(body, subject)
    cancelled = looks_cancelled(subject, title, body)
    deadline_text = _labelled_value(
        body, "Registration deadline", "Deadline", "報名截止日期", "截止報名", "報名截止"
    )
    deadline = parse_any_date(deadline_text or "")
    # Description: first few non-footer body lines, capped
    desc_lines = []
    for line in (body or "").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if UNSUBSCRIBE_RE.search(line):
            break
        desc_lines.append(line)
        if len(" ".join(desc_lines)) > 1800:
            break
    description = " ".join(desc_lines)[:2000]
    cand = {
        "title": title,
        "title_zh": title_zh,
        "title_en": title_en,
        "date": date,
        "start_time": start,
        "end_time": end,
        "time": f"{start}-{end}" if start and end else (start or ""),
        "mode": mode,
        "type": typ,
        "civil_related": civil,
        "disc": discs,
        "free": fee,
        "registration_deadline": deadline,
        "registration": {
            "mechanism": mech,
            "destination": dest,
            "status": "UNKNOWN",
        },
        "description": description,
        "cancelled": cancelled,
        "organisation": ORGANISATION,
        "discovery": DISCOVERY,
        "source": SOURCE_NAME,
    }
    set_hours(cand, [subject, body, description])
    return cand


class PassiveHttp:
    """GET-only HTTP. POST and registration submission are forbidden."""

    def __init__(self, getter: Optional[Callable[..., Any]] = None):
        self.getter = getter
        self.gets: List[str] = []
        self.posts: List[str] = []

    def get(self, url: str, **kwargs) -> "SimpleResponse":
        if self._forbidden_url(url):
            raise RuntimeError(f"refusing to fetch tracking/image URL: {url}")
        self.gets.append(url)
        kwargs = dict(kwargs)
        kwargs.setdefault("timeout", 30)
        kwargs.setdefault("allow_redirects", True)
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (compatible; CPDHunterBot/2.2; free CPD calendar)",
        )
        headers.setdefault("Accept", "text/html,application/xhtml+xml")
        kwargs["headers"] = headers
        if self.getter is not None:
            resp = self.getter(url, **kwargs)
            if hasattr(resp, "text"):
                return SimpleResponse(getattr(resp, "status_code", 200), resp.text, url)
            return SimpleResponse(200, str(resp), url)
        import requests
        r = requests.get(url, **kwargs)
        return SimpleResponse(r.status_code, r.text, r.url)

    def post(self, url: str, **kwargs):
        self.posts.append(url)
        raise RuntimeError("POST is forbidden in the newsletter pilot (no registration submission)")

    @staticmethod
    def _forbidden_url(url: str) -> bool:
        return bool(PIXEL_HINT_RE.search(url or "") or IMG_EXT_RE.search(url or ""))


class SimpleResponse:
    def __init__(self, status_code: int, text: str, url: str):
        self.status_code = status_code
        self.text = text
        self.url = url


def parse_zoom_data_model(html: str) -> Dict[str, Any]:
    """Extract official topic / schedule / close flags from a Zoom register page."""
    out: Dict[str, Any] = {}
    if not html:
        return out
    m = re.search(r"window\.dataModel\s*=\s*\{", html)
    if m:
        # Brace-match a shallow object; good enough for the known sanitized shape.
        start = m.end() - 1
        depth = 0
        end = None
        for i, ch in enumerate(html[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        blob = html[start:end] if end else ""
        # Pull known fields without eval
        def _unescape_js(s):
            if not s:
                return s
            return (
                s.replace(r"\n", "\n")
                .replace(r"\r", "\r")
                .replace(r"\t", "\t")
                .replace(r"\'", "'")
                .replace(r'\"', '"')
            )

        def js_str(key):
            mm = re.search(rf"{key}\s*:\s*'((?:\\'|[^'])*)'", blob)
            if mm:
                return _unescape_js(mm.group(1))
            mm = re.search(rf'{key}\s*:\s*"((?:\\"|[^"])*)"', blob)
            if mm:
                return _unescape_js(mm.group(1))
            return None

        def js_bool(key):
            mm = re.search(rf"{key}\s*:\s*(true|false)", blob, re.I)
            return mm.group(1).lower() == "true" if mm else None

        topic = js_str("topic")
        desc = js_str("desc")
        type_flag = js_str("typeFlag")
        close = js_bool("closeRegistration")
        sm = re.search(r"scheduleTime\s*:\s*\[\s*\"([^\"]+)\"", blob) or re.search(
            r"scheduleTime\s*:\s*\[\s*'([^']+)'", blob
        )
        schedule = sm.group(1) if sm else None
        if topic:
            out["topic"] = topic
        if desc:
            out["desc"] = desc.replace("\\n", "\n")
        if type_flag:
            out["typeFlag"] = type_flag
        if close is not None:
            out["closeRegistration"] = close
        if schedule:
            out["scheduleTime"] = schedule
    soup = BeautifulSoup(html, "html.parser")
    visible = soup.get_text(" ", strip=True)
    if visible:
        out.setdefault("visible_text", visible[:4000])
    if not out.get("topic"):
        # Fallback: first substantial heading
        for h in soup.find_all(["h1", "h2", "h3"]):
            t = h.get_text(" ", strip=True)
            if t and len(t) >= 8:
                out["topic"] = t
                break
    return out


def inspect_destination(
    url: str,
    html: str,
    newsletter_title: str = "",
) -> Dict[str, Any]:
    """Passive inspection of a public registration page (already fetched or fixture)."""
    info: Dict[str, Any] = {
        "status": "UNKNOWN",
        "closed_wording": None,
        "cancelled": False,
        "title": None,
        "date": None,
        "start_time": None,
        "end_time": None,
        "title_mismatch": False,
        "source": "destination",
    }
    zoom = parse_zoom_data_model(html) if html else {}
    topic = zoom.get("topic")
    desc = zoom.get("desc") or ""
    visible = " ".join(x for x in (topic, desc, zoom.get("visible_text") or "") if x)
    if topic:
        info["title"] = re.sub(r"^\[活動取消\]\s*", "", topic).strip() or topic
    if looks_cancelled(topic or "", desc, visible):
        info["cancelled"] = True
    wording = explicit_closed_registration(html or "")
    close_flag = zoom.get("closeRegistration") is True
    type_flag = (zoom.get("typeFlag") or "").lower()
    ended = type_flag in ("ended", "end", "cancel", "cancelled", "canceled")
    if wording or close_flag or ended or info["cancelled"]:
        info["status"] = "CLOSED"
        info["closed_wording"] = wording or (
            "closeRegistration=true" if close_flag else None
        ) or (f"typeFlag={type_flag}" if ended else None) or "cancelled"
    # Official date/time only if visibly present — never invent.
    sched = zoom.get("scheduleTime") or ""
    date = parse_any_date(desc) or parse_any_date(sched) or parse_any_date(visible)
    times = parse_any_time_range(desc) or parse_any_time_range(sched) or parse_any_time_range(visible)
    # scheduleTime like "Nov 19, 2026 02:00 PM" may only have a start
    if not times and sched:
        tm = re.search(r"(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?))", sched, re.I)
        if tm:
            # start only; do not invent an end
            rng = parse_any_time_range(f"{tm.group(1)}-{tm.group(1)}")
            # Don't store a zero-length range as hours later
            start_only = None
            m2 = re.search(
                r"^(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)$",
                tm.group(1).strip(),
                re.I,
            )
            if m2:
                h = int(m2.group(1))
                mi = int(m2.group(2) or 0)
                ap = (m2.group(3) or "").lower().replace(".", "")
                if ap.startswith("p") and h != 12:
                    h += 12
                elif ap.startswith("a") and h == 12:
                    h = 0
                if 0 <= h <= 23:
                    start_only = f"{h:02d}:{mi:02d}"
            if start_only:
                info["start_time"] = start_only
    if date:
        info["date"] = date
    if times:
        info["start_time"], info["end_time"] = times
    if topic and newsletter_title and destination_title_mismatch(newsletter_title, topic):
        info["title_mismatch"] = True
    return info


def merge_destination(candidate: Dict[str, Any], info: Dict[str, Any]) -> Dict[str, Any]:
    """Fill official fields that are missing from the newsletter. Do not invent."""
    if info.get("cancelled"):
        candidate["cancelled"] = True
    if info.get("status") == "CLOSED":
        candidate.setdefault("registration", {})
        candidate["registration"]["status"] = "CLOSED"
        if info.get("closed_wording"):
            candidate["registration"]["closed_wording"] = info["closed_wording"]
    elif info.get("status") == "OPEN":
        if candidate.get("registration", {}).get("status") != "CLOSED":
            candidate.setdefault("registration", {})
            candidate["registration"]["status"] = "OPEN"
    # Official date/time only when the destination actually showed them
    if not candidate.get("date") and info.get("date"):
        candidate["date"] = info["date"]
        candidate["date_source"] = "official_destination"
    if not candidate.get("start_time") and info.get("start_time"):
        candidate["start_time"] = info["start_time"]
        if info.get("end_time"):
            candidate["end_time"] = info["end_time"]
        candidate["time"] = (
            f"{candidate['start_time']}-{candidate['end_time']}"
            if candidate.get("end_time")
            else candidate["start_time"]
        )
        candidate["time_source"] = "official_destination"
        set_hours(candidate, [candidate.get("description") or "", info.get("title") or ""])
    if info.get("title") and not candidate.get("title"):
        display, zh, en = split_bilingual_title(info["title"])
        candidate["title"] = display
        candidate["title_zh"] = zh
        candidate["title_en"] = en
    if info.get("title_mismatch"):
        candidate["destination_title_mismatch"] = True
    return candidate


def assert_no_pii(payload: Any, forbidden: Iterable[str]) -> List[str]:
    """Return any forbidden subscriber tokens found in emitted payload."""
    dumped = json.dumps(payload, ensure_ascii=False)
    hits = []
    for tok in forbidden:
        t = (tok or "").strip()
        if len(t) < 5:
            continue
        # Ignore generic words
        if t.lower() in ("cic.hk", "cic.org.hk", "newsletter", "iclub"):
            continue
        if t in dumped:
            hits.append(t)
    return hits


def process_newsletter(
    source: Any,
    *,
    from_header: Optional[str] = None,
    production_events: Optional[List[Dict[str, Any]]] = None,
    http: Optional[PassiveHttp] = None,
    destination_html: Optional[str] = None,
    destination_map: Optional[Dict[str, str]] = None,
    verify: bool = False,
    trusted_html: bool = False,
) -> Dict[str, Any]:
    """Full isolated pipeline for one newsletter message."""
    parsed = parse_message(source)
    if from_header:
        apply_trusted_override(parsed, from_header)
    elif trusted_html and parsed["kind"] in ("html", "text") and not parsed.get("from_header"):
        # Saved official HTML provided without envelope: only when caller asserts
        # it is a trusted CIC/i-Club fixture, never for arbitrary uploads.
        parsed["trusted"] = True
        parsed["sender_domain"] = "cic.hk"

    record = {
        "trusted": bool(parsed.get("trusted")),
        "sender_domain": parsed.get("sender_domain") or None,
        "kind": parsed.get("kind"),
        "malformed": bool(parsed.get("malformed")),
        "candidates": [],
        "pii_leaks": [],
        "posts": 0,
    }

    if parsed.get("malformed") and not (parsed.get("html") or parsed.get("text") or parsed.get("subject")):
        cand = {
            "title": "",
            "title_zh": None,
            "title_en": None,
            "date": None,
            "mode": "UNKNOWN",
            "type": "Technical",
            "civil_related": False,
            "registration": {"mechanism": None, "destination": None, "status": "UNKNOWN"},
            "cancelled": False,
            "organisation": ORGANISATION,
            "discovery": DISCOVERY,
            "source": SOURCE_NAME,
            "confidence": "LOW",
            "hrs": None,
            "hrs_est": False,
            "free": None,
        }
        apply_quality_gates(cand, trusted=False)
        cand["pilot_status"] = STATUS_REJECTED
        cand["confidence"] = "LOW"
        record["candidates"] = [cand]
        return record

    html, text = parsed.get("html") or "", parsed.get("text") or ""
    body_text, links = html_event_text(html) if html else (_drop_footer(text), [])
    if text:
        links = links + text_links(text)
        if not body_text:
            body_text = _drop_footer(text)
    # De-duplicate links by canonical URL
    seen = set()
    uniq_links = []
    for item in links:
        key = canonical_registration_url(item.get("url") or "") or item.get("url")
        if key in seen:
            continue
        seen.add(key)
        uniq_links.append(item)

    cand = extract_event_fields(parsed.get("subject") or "", body_text, uniq_links)

    # Explicit closed wording in the newsletter itself (strong phrases only).
    closed_wording = explicit_closed_registration(html or body_text)
    if closed_wording:
        cand.setdefault("registration", {})
        cand["registration"]["status"] = "CLOSED"
        cand["registration"]["closed_wording"] = closed_wording

    # Destination inspection:
    dest = (cand.get("registration") or {}).get("destination")
    html_for_dest = destination_html
    if not html_for_dest and dest and destination_map:
        key = canonical_registration_url(dest) or dest
        for k, v in destination_map.items():
            if canonical_registration_url(k) == key or k == dest:
                html_for_dest = v
                break
    if not html_for_dest and dest and verify and http is not None:
        try:
            resp = http.get(dest)
            html_for_dest = resp.text
        except RuntimeError:
            raise
        except Exception:
            html_for_dest = None
    if html_for_dest:
        info = inspect_destination(dest or "", html_for_dest, cand.get("title") or "")
        merge_destination(cand, info)
        if info.get("title_mismatch"):
            cand["confidence"] = "LOW"
    else:
        info = None

    # Recompute hours after destination merge may have added times
    set_hours(cand, [parsed.get("subject") or "", body_text, cand.get("description") or ""])
    typ, civil, discs = classify_type_and_civil(
        cand.get("title") or "", cand.get("title_zh") or "", cand.get("title_en") or "", body_text
    )
    cand["type"] = typ
    cand["civil_related"] = civil
    cand["disc"] = discs
    if not cand.get("mode") or cand.get("mode") == "UNKNOWN":
        cand["mode"] = infer_attendance_mode(cand.get("title") or "", body_text)

    trusted = bool(parsed.get("trusted"))
    cand["confidence"] = confidence_for(cand, trusted)
    if cand.get("destination_title_mismatch"):
        cand["confidence"] = "LOW"
    apply_quality_gates(cand, trusted=trusted)
    if cand.get("destination_title_mismatch") and cand.get("pilot_status") == STATUS_ELIGIBLE:
        cand["pilot_status"] = STATUS_REVIEW
        cand.setdefault("gate_failures", []).append("E")
        cand.setdefault("gates", {})["E"] = {"pass": False, "reason": "destination_title_mismatch"}
    compare_to_production(cand, production_events)

    # Scrub subscriber PII from any retained event text
    forbidden = parsed.get("forbidden_tokens") or []
    for key in ("title", "title_zh", "title_en", "description"):
        if isinstance(cand.get(key), str):
            cand[key] = scrub_pii_text(cand[key], forbidden)
    dest = (cand.get("registration") or {}).get("destination")
    if isinstance(dest, str):
        cand["registration"]["destination"] = clean_url(dest) or dest

    # Provenance only — never emit the From mailbox or subscriber identity
    cand["provenance"] = {
        "discovery": DISCOVERY,
        "source": SOURCE_NAME,
        "organisation": ORGANISATION,
        "sender_domain": parsed.get("sender_domain") if trusted else None,
    }

    leaks = assert_no_pii(
        {"candidate": public_candidate_view(cand), "provenance": cand.get("provenance")},
        parsed.get("forbidden_tokens") or [],
    )
    record["pii_leaks"] = leaks
    record["candidates"] = [cand]
    record["http_gets"] = list(http.gets) if http is not None else []
    record["http_posts"] = list(http.posts) if http is not None else []
    return record
