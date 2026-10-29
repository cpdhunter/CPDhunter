"""
CPD Hunter - 每日自動搵免費 CPD 活動
流程：讀 sources.json -> 逐個網站攞 HTML（遵守 robots.txt）
     -> 先試 schema.org Event (JSON-LD)，冇就用 AI 抽取活動資料
     -> 過濾（未過期、唔係明確收費、海外只要網上、剔走社交活動）
     -> 合併 -> 寫 events.json
"""
import json, os, re, sys, time, hashlib, datetime as dt
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "events.json")
SOURCES = os.path.join(ROOT, "sources.json")
MANUAL = os.path.join(ROOT, "manual.json")

UA = "CPDHunterBot/1.0 (free CPD calendar for engineers; respects robots.txt)"
HKT = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(HKT).date()
KEEP_DAYS_AHEAD = 180
KEEP_DAYS_PAST = 31          # 月曆保留上個月嘅活動
MAX_TEXT = 12000             # GitHub Models 免費額度每次輸入有上限

API = os.getenv("LLM_API", "https://models.github.ai/inference/chat/completions")
MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
TOKEN = os.getenv("LLM_TOKEN") or os.getenv("GITHUB_TOKEN")

TYPES = ["Technical", "GPM", "H&S"]
# HKIE 22 個專業界別 + General
DISCS = ["Aircraft", "Biomedical", "Building", "Building Services", "Chemical", "Civil",
         "Control, Automation & Instrumentation", "Electrical", "Electronics", "Energy",
         "Environmental", "Fire", "Gas", "Geotechnical", "Information", "Logistics & Transportation",
         "Manufacturing, Industrial & Systems", "Marine & Naval Architecture", "Materials",
         "Mechanical", "Nuclear", "Structural", "General"]
_robots = {}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- 抓網頁 ----------
def allowed(url):
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=15)
            rp.parse(r.text.splitlines() if r.ok else [])
        except Exception:
            rp.parse([])
        _robots[base] = rp
    return _robots[base].can_fetch(UA, url)


def fetch(url):
    if not allowed(url):
        log("  robots.txt 唔俾，跳過", url)
        return None
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


# ---------- 方法 1：JSON-LD ----------
def walk(o):
    if isinstance(o, list):
        for x in o:
            yield from walk(x)
    elif isinstance(o, dict):
        t = o.get("@type")
        t = t if isinstance(t, list) else [t]
        if any(str(x).endswith("Event") for x in t if x):
            yield o
        for k in ("@graph", "itemListElement", "item", "subEvent"):
            if k in o:
                yield from walk(o[k])


def norm_off(off):
    if not off:
        return None
    if off == "Z":
        return "+00:00"
    return off if ":" in off else off[:3] + ":" + off[3:]


def jsonld_events(soup, base):
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except Exception:
            continue
        for e in walk(data):
            m = re.match(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?(?::\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?",
                         str(e.get("startDate", "")))
            if not m:
                continue
            em = re.search(r"T(\d{2}:\d{2})", str(e.get("endDate", "")))
            offers = e.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = str(offers.get("price", "")) if isinstance(offers, dict) else ""
            org = e.get("organizer") or {}
            out.append({
                "title": e.get("name"),
                "organizer": org.get("name") if isinstance(org, dict) else str(org),
                "date": m.group(1), "start_time": m.group(2),
                "end_time": em.group(1) if em else None,
                "utc_offset": norm_off(m.group(3)),
                "url": urljoin(base, e.get("url") or base),
                "is_online": ("Online" in str(e.get("eventAttendanceMode", ""))) or None,
                "is_free": (price in ("0", "0.0", "0.00")) if price else None,
                "cpd_hours": None, "type": None, "disciplines": None,
            })
    return out


# ---------- 方法 2：AI 抽取 ----------
def page_text(soup, base):
    for t in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form"]):
        t.decompose()
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if txt:
            a.replace_with(f"{txt} <{urljoin(base, a['href'])}>")
    return re.sub(r"\s+", " ", (soup.body or soup).get_text(" ", strip=True))[:MAX_TEXT]


PROMPT = """You extract upcoming professional development events from a web page for engineers.
Today is {today}. Source: {name} ({region}).
Return JSON: {{"events":[...]}}. Each event:
- title (string)
- organizer (string or null)
- date (YYYY-MM-DD, first day; for a date range use first day)
- start_time, end_time ("HH:MM" 24h, local time as written on page, or null)
- utc_offset (offset of that local time, e.g. "+08:00" for HKT, "+00:00" for GMT, "+01:00" for BST; null if unknown)
- url (the most specific registration/detail link shown for this event, absolute URL)
- is_online (true/false/null)
- is_free (true if page says free/no charge, false if a price is shown, null if not stated)
- cpd_hours (number or null; only if CPD hours/points are stated on the page)
- type: one of "Technical" (engineering/technical content), "GPM" (general professional matters: management, law, contracts, ethics, integrity, communication, ESG policy, AI/IT skills for professionals), "H&S" (health & safety incl. occupational safety and health)
- disciplines: list of engineering disciplines the content mainly concerns, choose from {discs}; use ["General"] if not discipline specific
- is_social: true if it is mainly a dinner, AGM, party, tour, sport or networking with no technical content
Only include events dated today or later. Do not invent anything not on the page. If none, return {{"events":[]}}.

PAGE:
{text}"""


def llm_extract(text, src):
    if not TOKEN:
        log("  冇 LLM token，跳過 AI 抽取")
        return []
    body = {
        "model": MODEL, "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": PROMPT.format(
            today=TODAY.isoformat(), name=src["name"], region=src["region"], discs=DISCS, text=text)}],
    }
    for attempt in range(3):
        r = requests.post(API, json=body, timeout=90, headers={
            "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        if r.status_code == 429:
            time.sleep(30 * (attempt + 1))
            continue
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"]).get("events", [])
    log("  AI 額度用晒 (429)")
    return []


# ---------- 整理 ----------
def norm_title(t):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (t or "").lower())


def to_hkt(e):
    """將當地時間轉做香港時間"""
    if not (e.get("start_time") and e.get("utc_offset")):
        return e["date"], e.get("start_time"), e.get("end_time")
    m = re.match(r"([+-])(\d{2}):?(\d{2})", e["utc_offset"])
    if not m:
        return e["date"], e.get("start_time"), e.get("end_time")
    sign = 1 if m.group(1) == "+" else -1
    tz = dt.timezone(sign * dt.timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))

    def conv(t):
        x = dt.datetime.fromisoformat(f"{e['date']}T{t}").replace(tzinfo=tz).astimezone(HKT)
        return x.date().isoformat(), x.strftime("%H:%M")
    d, s = conv(e["start_time"])
    end = conv(e["end_time"])[1] if e.get("end_time") else None
    return d, s, end


def est_hours(s, e):
    """冇註明 CPD 時數時，按活動時長估算（四捨五入至 0.5 小時）"""
    try:
        mins = (dt.datetime.strptime(e, "%H:%M") - dt.datetime.strptime(s, "%H:%M")).seconds / 60
        if 20 <= mins <= 8 * 60:
            return round(mins / 30) / 2
    except Exception:
        pass
    return None


def clean(e, src):
    try:
        title = (e.get("title") or "").strip()
        e["date"] = dt.date.fromisoformat(str(e.get("date"))[:10]).isoformat()
        url = e.get("url") or src["url"]
        if not title or not url.startswith("http"):
            return None
        for k in ("start_time", "end_time"):
            if e.get(k) and not re.fullmatch(r"\d{2}:\d{2}", str(e[k])):
                e[k] = None
        d_hkt, s_hkt, e_hkt = to_hkt(e)
    except Exception:
        return None
    d = dt.date.fromisoformat(d_hkt)
    if d < TODAY or d > TODAY + dt.timedelta(days=KEEP_DAYS_AHEAD):
        return None
    if e.get("is_free") is False:                                   # 明確收費唔要
        return None
    if src["region"] != "HK" and e.get("is_online") is False:       # 海外實體活動唔要
        return None
    if e.get("is_social"):                                          # 晚宴、AGM 等唔要
        return None
    if e.get("is_free") is None and src.get("free"):                # 來源講明全部免費
        e["is_free"] = True
    typ = e.get("type") if e.get("type") in TYPES else (src.get("type") or "Technical")
    discs = [x for x in (e.get("disciplines") or []) if x in DISCS] or ["General"]
    hrs = e.get("cpd_hours")
    hrs = hrs if isinstance(hrs, (int, float)) and 0 < hrs < 50 else None
    est = False
    if hrs is None and s_hkt and e_hkt:
        hrs = est_hours(s_hkt, e_hkt)
        est = hrs is not None
    return {
        "id": "a" + hashlib.sha1(f"{norm_title(title)}|{d_hkt}".encode()).hexdigest()[:12],
        "name": title[:200],
        "org": (e.get("organizer") or src["name"])[:120],
        "date": d_hkt,
        "time": f"{s_hkt}-{e_hkt}" if s_hkt and e_hkt else (s_hkt or ""),
        "hrs": hrs, "hrs_est": est,
        "type": typ, "disc": discs,
        "url": url, "region": src["region"],
        "online": e.get("is_online"), "free": e.get("is_free"),
        "source": src["name"], "group": src.get("group") or src["name"],
        "auto": True,
    }


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    sources = load(SOURCES, [])
    old = load(OUT, {}).get("events", [])
    found, status = {}, []

    for src in sources:
        if src.get("disabled"):
            continue
        log(f"▶ {src['name']}")
        try:
            html = fetch(src["url"])
            if not html:
                status.append({"source": src["name"], "ok": False, "n": 0, "err": "robots"})
                continue
            soup = BeautifulSoup(html, "html.parser")
            raw, method = jsonld_events(soup, src["url"]), "jsonld"
            if not raw:
                raw, method = llm_extract(page_text(soup, src["url"]), src), "ai"
            n = 0
            for e in raw:
                c = clean(e, src)
                if c:
                    found[c["id"]] = c
                    n += 1
            log(f"  {method}: 抽到 {len(raw)}，保留 {n}")
            status.append({"source": src["name"], "ok": True, "n": n})
        except Exception as ex:
            log("  失敗:", ex)
            status.append({"source": src["name"], "ok": False, "n": 0, "err": str(ex)[:120]})
        time.sleep(3)  # 對網站有禮貌

    # 保留舊活動：未來嘅（網站可能分頁）同上個月嘅（月曆參考）
    cutoff = (TODAY - dt.timedelta(days=KEEP_DAYS_PAST)).isoformat()
    for e in old:
        if e.get("auto") and e["date"] >= cutoff and e["id"] not in found:
            found[e["id"]] = e
    # 人手加嘅活動
    for e in load(MANUAL, []):
        if e.get("date", "") >= cutoff:
            e.setdefault("id", "m" + hashlib.sha1((e["url"] + e["date"]).encode()).hexdigest()[:12])
            e["auto"] = False
            found[e["id"]] = e

    events = sorted(found.values(), key=lambda x: (x["date"], x.get("time") or ""))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now(HKT).isoformat(timespec="minutes"),
                   "status": status, "events": events}, f, ensure_ascii=False, indent=1)
    log(f"完成：共 {len(events)} 個活動")


if __name__ == "__main__":
    main()
